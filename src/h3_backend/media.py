"""Small-file media operations; no decoded frame batches enter the orchestrator."""

from __future__ import annotations

import asyncio
import json
import math
import os
import uuid
from pathlib import Path
from typing import Any

from PIL import Image


def verify_image(path: Path) -> dict[str, Any]:
    if path.stat().st_size > 32 * 1024**2:
        raise ValueError("Identity image exceeds the 32 MiB input limit")
    try:
        with Image.open(path) as image:
            if image.format not in ("PNG", "JPEG", "WEBP"):
                raise ValueError("Unsupported identity image format")
            if image.width * image.height > 16_000_000 or getattr(image, "n_frames", 1) != 1:
                raise ValueError("Identity image must be a single still of at most 16 megapixels")
            info = {"width": image.width, "height": image.height, "format": image.format}
            image.verify()
        # JPEG verify() checks the container, not all compressed pixels; decode once before upload.
        with Image.open(path) as image:
            image.load()
        return info
    except (OSError, Image.DecompressionBombError) as exc:
        raise ValueError(f"Corrupt or oversized identity image: {exc}") from exc


async def _command(*arguments: str) -> bytes:
    process = await asyncio.create_subprocess_exec(
        *arguments, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=120)
    except BaseException:
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except TimeoutError:
                process.kill()
                await process.wait()
        raise
    if process.returncode:
        raise ValueError(f"{arguments[0]} failed: {stderr.decode(errors='replace')[-2000:]}")
    return stdout


async def probe(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError("Media file not found")
    data = await _command(
        "ffprobe",
        "-v",
        "error",
        "-count_frames",
        "-show_streams",
        "-show_format",
        "-of",
        "json",
        str(path.resolve()),
    )
    return json.loads(data)


async def prepare_tail(
    parent_video: Path,
    destination: Path,
    seconds: int,
    include_audio: bool = True,
) -> dict[str, Any]:
    if seconds not in (2, 3):
        raise ValueError("Reference tail must be two or three seconds")
    details = await probe(parent_video)
    video = next((s for s in details["streams"] if s["codec_type"] == "video"), None)
    if not video:
        raise ValueError("Parent contains no video stream")
    duration = float(video.get("duration", details["format"]["duration"]))
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Invalid parent duration")
    actual = min(float(seconds), duration)
    start = max(0.0, duration - actual)
    audio = include_audio and any(s["codec_type"] == "audio" for s in details["streams"])
    destination = destination.absolute()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        raise ValueError("Refusing to overwrite the reference tail")
    temporary = destination.parent / f".{destination.stem}-{uuid.uuid4().hex}.part.mp4"
    arguments = [
        "ffmpeg",
        "-v",
        "error",
        "-n",
        "-i",
        str(parent_video.resolve()),
        "-ss",
        f"{start:.9f}",
        "-t",
        f"{actual:.9f}",
        "-map",
        "0:v:0",
        "-vf",
        "fps=24,format=yuv420p",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "18",
    ]
    if audio:
        arguments += ["-map", "0:a:0", "-c:a", "aac", "-b:a", "192k"]
    else:
        arguments += ["-an"]
    arguments += [str(temporary)]
    try:
        await _command(*arguments)
        output = await probe(temporary)
        output_video = next(s for s in output["streams"] if s["codec_type"] == "video")
        # Linking publishes atomically without overwriting another file created during encoding.
        os.link(temporary, destination)
    finally:
        if temporary.is_file():
            temporary.unlink()
    return {
        "path": str(destination),
        "actual_seconds": float(output_video.get("duration", actual)),
        "requested_seconds": seconds,
        "has_audio": audio,
        "width": int(output_video["width"]),
        "height": int(output_video["height"]),
        "source_start_seconds": start,
        "fps": 24,
    }


async def concatenate(chunks: list[Path], destination: Path) -> dict[str, Any]:
    """Make a plainly labelled assembled preview; never discard presumed reference overlap."""
    if not chunks:
        raise ValueError("No accepted chunks to assemble")
    probes = [await probe(chunk) for chunk in chunks]
    video_streams = [
        next(s for s in data["streams"] if s["codec_type"] == "video") for data in probes
    ]
    signatures = [
        tuple(s.get(k) for k in ("width", "height", "r_frame_rate", "codec_name", "pix_fmt"))
        for s in video_streams
    ]
    if len(set(signatures)) != 1:
        raise ValueError("Chunks have incompatible video parameters")
    have_audio = [any(s["codec_type"] == "audio" for s in data["streams"]) for data in probes]
    if len(set(have_audio)) != 1:
        raise ValueError("Chunks disagree on audio presence")
    if destination.exists() or destination.is_symlink():
        raise ValueError("Refusing to overwrite assembled preview")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / f".{destination.stem}-{uuid.uuid4().hex}.part.mp4"
    arguments = ["ffmpeg", "-v", "error", "-n"]
    for chunk in chunks:
        arguments += ["-i", str(chunk.resolve())]
    # Audio can be slightly shorter than video in H3; pad to the chunk boundary to avoid drift.
    filters = []
    inputs = []
    for index, stream in enumerate(video_streams):
        duration = float(stream["duration"])
        filters.append(f"[{index}:v]setpts=PTS-STARTPTS[v{index}]")
        inputs.append(f"[v{index}]")
        if have_audio[0]:
            filters.append(
                f"[{index}:a]apad,atrim=duration={duration:.9f},asetpts=PTS-STARTPTS[a{index}]"
            )
            inputs.append(f"[a{index}]")
    audio_flag = int(have_audio[0])
    filters.append(
        "".join(inputs)
        + f"concat=n={len(chunks)}:v=1:a={audio_flag}[v]"
        + ("[a]" if audio_flag else "")
    )
    arguments += ["-filter_complex", ";".join(filters), "-map", "[v]"]
    if audio_flag:
        arguments += ["-map", "[a]", "-c:a", "aac"]
    arguments += ["-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", str(temporary)]
    try:
        await _command(*arguments)
        details = await probe(temporary)
        os.link(temporary, destination)
    finally:
        if temporary.is_file():
            temporary.unlink()
    return {
        "path": str(destination),
        "assembly": "external_concat_no_overlap_trim_no_crossfade",
        "probe": details,
    }

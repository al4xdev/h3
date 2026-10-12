"""Small-file media operations; no decoded frame batches enter the orchestrator."""

from __future__ import annotations

import asyncio
import json
import math
import os
import uuid
from fractions import Fraction
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


def _guard_path(path: Path) -> Path:
    absolute = path.absolute()
    if ".." in absolute.parts or any(p.is_symlink() for p in (absolute, *absolute.parents)):
        raise ValueError("Media paths must not contain traversal or symlinks")
    return absolute


def _destination(path: Path) -> Path:
    destination = _guard_path(path)
    if destination.exists():
        raise ValueError("Refusing to overwrite prepared media")
    destination.parent.mkdir(parents=True, exist_ok=True)
    return _guard_path(destination)


def _video_stream(details: dict[str, Any]) -> dict[str, Any]:
    video = next((s for s in details["streams"] if s["codec_type"] == "video"), None)
    if video is None:
        raise ValueError("Parent contains no video stream")
    return video


def _frame_count(video: dict[str, Any]) -> int:
    try:
        count = int(video["nb_read_frames"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Could not count decoded video frames") from exc
    if count <= 0:
        raise ValueError("Parent contains no decoded video frames")
    return count


def _strip_png_metadata(path: Path) -> None:
    # FFmpeg writes pHYs even with metadata disabled; retain only critical PNG chunks.
    # This edits the encoded container, never decoding or loading pixels in Python.
    data = path.read_bytes()
    clean = bytearray(data[:8])
    offset = 8
    while offset < len(data):
        length = int.from_bytes(data[offset:offset + 4], "big")
        end = offset + length + 12
        if end > len(data):
            raise ValueError("Invalid extracted PNG container")
        if data[offset + 4:offset + 8] in (b"IHDR", b"PLTE", b"IDAT", b"IEND"):
            clean.extend(data[offset:end])
        offset = end
    path.write_bytes(clean)


async def _reference_loader_count(path: Path) -> int:
    # Mirror Fantastic H3's timestamp sampler at 24 fps, including half-grid tolerance.
    # ffprobe returns timestamps only: no decoded frame batch enters this process.
    data = json.loads(await _command(
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
        "frame=best_effort_timestamp:stream=time_base", "-of", "json", str(path),
    ))
    time_base = Fraction(data["streams"][0]["time_base"])
    count, want = 0, 0.0
    grid = 1 / 24
    for frame in data["frames"]:
        timestamp = frame.get("best_effort_timestamp")
        if timestamp is None:
            continue
        # Integer PTS avoids ffprobe's decimal rounding at the half-grid boundary.
        time = float(int(timestamp) * time_base)
        while time >= want - grid / 2:
            count += 1
            want += grid
    return count


async def prepare_last_frame(parent_video: Path, destination: Path) -> dict[str, Any]:
    """Decode the counted final frame, rather than guessing a timestamp near EOF."""
    parent_video = _guard_path(parent_video)
    destination = _destination(destination)
    video = _video_stream(await probe(parent_video))
    count = _frame_count(video)
    temporary = destination.parent / f".{destination.stem}-{uuid.uuid4().hex}.part.png"
    try:
        await _command(
            "ffmpeg", "-v", "error", "-n", "-i", str(parent_video),
            "-map", "0:v:0", "-vf", f"select=eq(n\\,{count - 1}),format=rgb24,setsar=0",
            "-fps_mode", "passthrough", "-frames:v", "1", "-an", "-map_metadata", "-1",
            "-c:v", "png", "-pix_fmt", "rgb24", str(temporary),
        )
        _strip_png_metadata(temporary)
        with Image.open(temporary) as image:
            image.verify()
            if image.format != "PNG" or image.mode != "RGB":
                raise ValueError("Final frame must be an RGB PNG")
            width, height = image.size
        _guard_path(destination)
        # Hard-link publication is atomic and refuses even a destination created mid-decode.
        os.link(temporary, destination)
    finally:
        if temporary.is_file():
            temporary.unlink()
    return {
        "path": str(destination),
        "source_frame_count": count,
        "source_frame_index": count - 1,
        "width": width,
        "height": height,
        "format": "PNG",
        "mode": "RGB",
    }


async def prepare_tail(
    parent_video: Path,
    destination: Path,
    seconds: int,
    include_audio: bool = True,
    *,
    reference_frame_limit: int | None = None,
) -> dict[str, Any]:
    if reference_frame_limit is not None and reference_frame_limit < 5:
        raise ValueError("Reference generation limit must be at least five frames")
    if seconds not in (2, 3):
        raise ValueError("Reference tail must be two or three seconds")
    parent_video = _guard_path(parent_video)
    destination = _destination(destination)
    details = await probe(parent_video)
    video = _video_stream(details)
    try:
        fps = Fraction(video.get("avg_frame_rate") or video["r_frame_rate"])
        if fps <= 0:
            raise ValueError
        duration = float(video.get("duration") or details["format"]["duration"])
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
        raise ValueError("Invalid parent timing") from exc
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Invalid parent duration")
    actual = min(float(seconds), duration)
    start = max(0.0, duration - actual)
    audio = include_audio and any(s["codec_type"] == "audio" for s in details["streams"])
    # References are sampled at 24 fps by the native loader, not at the retained source rate.
    requested_frames = math.ceil(actual * 24 - 1e-5)
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
        "format=yuv420p",
        "-fps_mode",
        "passthrough",
        "-map_metadata",
        "-1",
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
        source_frames = _frame_count(output_video)
        loaded_frames = await _reference_loader_count(temporary)
        limited_frames = min(loaded_frames, reference_frame_limit or loaded_frames)
        if limited_frames < 5:
            raise ValueError("MiniMax H3 reference videos need at least five frames")
        # Native H3 caps to generation length first, then consumes a valid prefix.
        effective_frames = 5 + 17 * ((limited_frames - 5) // 17)
        _guard_path(destination)
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
        "fps": float(fps),
        "source_frame_count": source_frames,
        "reference_fps": 24,
        "reference_frame_limit": reference_frame_limit,
        "requested_reference_frames": requested_frames,
        "loaded_reference_frames": loaded_frames,
        "effective_reference_frames": effective_frames,
        "final_edge_loss_frames": loaded_frames - effective_frames,
        "final_edge_loss_seconds": (loaded_frames - effective_frames) / 24,
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

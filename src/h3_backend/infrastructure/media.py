"""Small-file media operations; no decoded frame batches enter the orchestrator."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import uuid
from fractions import Fraction
from pathlib import Path
from typing import Any

COMMAND_TIMEOUT = 120
STDOUT_LIMIT = 8 * 1024**2
STDERR_LIMIT = 2000


def sha256_file(path: Path) -> str:
    """Hash original encoded bytes with a bounded buffer, without decoding media."""
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


async def _image_header(path: Path) -> dict[str, Any]:
    data = await _command(
        "ffprobe", "-v", "error", "-probesize", "1048576", "-analyzeduration", "0",
        "-show_entries", "stream=codec_name,codec_type,width,height,pix_fmt:format=format_name",
        "-of", "json", str(path),
    )
    details = json.loads(data)
    streams = details.get("streams", [])
    formats = {"png": "PNG", "mjpeg": "JPEG", "webp": "WEBP"}
    if len(streams) != 1 or streams[0].get("codec_name") not in formats:
        raise ValueError("Unsupported identity image format")
    stream = streams[0]
    # Reject video containers carrying a permitted codec; do not trust the filename suffix.
    if details.get("format", {}).get("format_name") not in (
        "png_pipe", "jpeg_pipe", "webp_pipe", "image2",
    ):
        raise ValueError("Identity image must be a single still")
    width, height = int(stream.get("width", 0)), int(stream.get("height", 0))
    if width <= 0 or height <= 0 or width * height > 16_000_000:
        raise ValueError("Identity image must be a single still of at most 16 megapixels")
    return {**stream, "format": formats[stream["codec_name"]]}


async def _verify_image(path: Path) -> dict[str, Any]:
    header = await _image_header(path)
    # Geometry is checked before full decode. Only progress metadata crosses this pipe;
    # at most two frames suffice to reject multi-frame inputs, including concatenated stills.
    progress = await _command(
        "ffmpeg", "-v", "error", "-xerror", "-err_detect", "crccheck+explode", "-nostdin",
        "-i", str(path), "-map", "0:v:0", "-frames:v", "2", "-an",
        "-fps_mode", "passthrough", "-progress", "pipe:1", "-f", "null", "-",
    )
    counts = [int(line[6:]) for line in progress.splitlines() if line.startswith(b"frame=")]
    if not counts or counts[-1] != 1:
        raise ValueError("Identity image must be a single still")
    return {key: header[key] for key in ("width", "height", "format")}


def verify_image(path: Path) -> dict[str, Any]:
    """Synchronous contract for to_thread callers; all pixel work stays external."""
    path = _guard_path(path)
    if not path.is_file():
        raise ValueError("Media file not found")
    if path.stat().st_size > 32 * 1024**2:
        raise ValueError("Identity image exceeds the 32 MiB input limit")
    try:
        return asyncio.run(_verify_image(path))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Corrupt or unsupported identity image: {exc}") from exc


async def _command(*arguments: str) -> bytes:
    process = await asyncio.create_subprocess_exec(
        *arguments, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    async def capture(stream, limit, *, tail=False):
        data = bytearray()
        while block := await stream.read(65536):
            data.extend(block)
            if len(data) > limit:
                if not tail:
                    raise ValueError("Media command metadata exceeds bounded output limit")
                del data[:-limit]
        return bytes(data)

    readers = [
        asyncio.create_task(capture(process.stdout, STDOUT_LIMIT)),
        asyncio.create_task(capture(process.stderr, STDERR_LIMIT, tail=True)),
    ]
    try:
        stdout, stderr, _ = await asyncio.wait_for(
            asyncio.gather(*readers, process.wait()), timeout=COMMAND_TIMEOUT,
        )
    except BaseException:
        for reader in readers:
            reader.cancel()
        await asyncio.gather(*readers, return_exceptions=True)

        async def discard(stream):
            while await stream.read(65536):
                pass

        # Drain without retaining bytes during shutdown: a full pipe must not block
        # wait() after an output-limit violation or cancellation.
        drains = [asyncio.create_task(discard(s)) for s in (process.stdout, process.stderr)]
        try:
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=5)
                except TimeoutError:
                    process.kill()
                    await process.wait()
        finally:
            await asyncio.gather(*drains, return_exceptions=True)
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
        # FFmpeg emits pHYs and may emit standard sRGB cHRM/gAMA tags, but no
        # inherited prompt/EXIF/orientation. External RGB hashes establish exact
        # native pixel preservation; do not rewrite the PNG container in Python.
        header = await _image_header(temporary)
        if header["format"] != "PNG" or header["pix_fmt"] != "rgb24":
            raise ValueError("Final frame must be an RGB PNG")
        width, height = header["width"], header["height"]
        if (width, height) != (int(video["width"]), int(video["height"])):
            raise ValueError("Final frame geometry differs from parent")
        await _verify_image(temporary)
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
    chunks = [_guard_path(chunk) for chunk in chunks]
    destination = _destination(destination)
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
        _guard_path(destination)
        os.link(temporary, destination)
    finally:
        if temporary.is_file():
            temporary.unlink()
    return {
        "path": str(destination),
        "assembly": "external_concat_no_overlap_trim_no_crossfade",
        "probe": details,
    }

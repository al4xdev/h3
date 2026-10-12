import asyncio
from fractions import Fraction
from pathlib import Path

import pytest
from PIL import Image

from h3_backend import media
from h3_backend.media import concatenate, prepare_last_frame, prepare_tail, probe, verify_image


async def fixture_video(path: Path, audio: bool, *, fps="24", frames=56):
    arguments = [
        "ffmpeg", "-v", "error", "-n", "-f", "lavfi", "-i",
        f"testsrc2=size=64x96:rate={fps}",
    ]
    if audio:
        arguments += ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=32000", "-c:a", "aac"]
    arguments += [
        "-t", str(frames / float(Fraction(fps))),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-metadata", "comment=private prompt must not propagate", str(path),
    ]
    process = await asyncio.create_subprocess_exec(*arguments, stderr=asyncio.subprocess.PIPE)
    _, stderr = await process.communicate()
    assert process.returncode == 0, stderr.decode()


@pytest.mark.parametrize("audio", [False, True])
async def test_tail_exact_duration_and_optional_audio(tmp_path, audio):
    parent = tmp_path / "parent.mp4"
    await fixture_video(parent, audio)
    result = await prepare_tail(parent, tmp_path / "tail.mp4", 2, include_audio=audio)
    assert result["requested_seconds"] == 2
    assert result["actual_seconds"] == pytest.approx(2, abs=1 / 24)
    assert result["has_audio"] == audio
    assert result["requested_reference_frames"] == 48
    assert result["loaded_reference_frames"] == 48
    assert result["effective_reference_frames"] == 39
    assert result["final_edge_loss_frames"] == 9
    assert result["final_edge_loss_seconds"] == 9 / 24
    details = await probe(Path(result["path"]))
    video = next(s for s in details["streams"] if s["codec_type"] == "video")
    assert int(video["nb_read_frames"]) == 48
    assert video["r_frame_rate"] == "24/1"
    assert any(s["codec_type"] == "audio" for s in details["streams"]) == audio


async def test_three_second_tail_clamps_to_existing_short_video(tmp_path):
    parent = tmp_path / "parent.mp4"
    await fixture_video(parent, True)
    result = await prepare_tail(parent, tmp_path / "tail.mp4", 3)
    assert result["actual_seconds"] == pytest.approx(56 / 24, abs=1 / 24)
    assert result["source_start_seconds"] == 0
    assert result["requested_reference_frames"] == 56
    assert result["loaded_reference_frames"] == 56
    assert result["effective_reference_frames"] == 56
    assert result["final_edge_loss_frames"] == result["final_edge_loss_seconds"] == 0
    with pytest.raises(ValueError, match="overwrite"):
        await prepare_tail(parent, tmp_path / "tail.mp4", 2)
    with pytest.raises(ValueError, match="two or three"):
        await prepare_tail(parent, tmp_path / "invalid.mp4", 5)


@pytest.mark.parametrize("fps,frames,source_frames,loaded,effective", [
    ("24", 120, 72, 72, 56),
    ("30", 150, 90, 72, 56),
    # Fractional cuts retain 89 source frames with a 1-frame PTS offset; the loader yields 72.
    ("30000/1001", 150, 89, 72, 56),
])
async def test_tail_preserves_source_rate_and_records_prefix_loss(
    tmp_path, fps, frames, source_frames, loaded, effective,
):
    parent = tmp_path / "parent.mp4"
    await fixture_video(parent, True, fps=fps, frames=frames)
    result = await prepare_tail(parent, tmp_path / "tail.mp4", 3)
    output = await probe(Path(result["path"]))
    video = next(s for s in output["streams"] if s["codec_type"] == "video")
    assert Fraction(video["avg_frame_rate"]) == Fraction(fps)
    assert result["fps"] == float(Fraction(fps))
    assert (result["width"], result["height"]) == (64, 96)
    assert result["has_audio"]
    assert result["source_frame_count"] == source_frames
    assert result["reference_fps"] == 24
    assert result["requested_reference_frames"] == 72
    assert result["loaded_reference_frames"] == loaded
    assert result["effective_reference_frames"] == effective
    assert result["final_edge_loss_frames"] == loaded - effective
    assert result["final_edge_loss_seconds"] == (loaded - effective) / 24
    assert result["source_start_seconds"] > 0
    assert "comment" not in output.get("format", {}).get("tags", {})


async def test_reference_prefix_is_capped_to_generation_length_first(tmp_path):
    parent = tmp_path / "parent.mp4"
    await fixture_video(parent, False, frames=120)
    result = await prepare_tail(
        parent, tmp_path / "tail.mp4", 3, reference_frame_limit=39,
    )
    assert result["loaded_reference_frames"] == 72
    assert result["effective_reference_frames"] == 39
    assert result["final_edge_loss_frames"] == 33
    assert result["final_edge_loss_seconds"] == 33 / 24
    assert result["reference_frame_limit"] == 39


async def test_reference_rejects_fewer_than_five_loaded_frames(tmp_path):
    parent = tmp_path / "parent.mp4"
    await fixture_video(parent, False, frames=4)
    destination = tmp_path / "tail.mp4"
    with pytest.raises(ValueError, match="five frames"):
        await prepare_tail(parent, destination, 3)
    assert not destination.exists()
    assert not list(tmp_path.glob(".*.part.*"))


async def test_tail_audio_can_be_explicitly_excluded(tmp_path):
    parent = tmp_path / "parent.mp4"
    await fixture_video(parent, True)
    result = await prepare_tail(parent, tmp_path / "silent.mp4", 2, include_audio=False)
    assert not result["has_audio"]
    assert not any(s["codec_type"] == "audio" for s in (await probe(
        Path(result["path"])
    ))["streams"])


async def test_last_frame_is_exact_rgb_and_not_penultimate(tmp_path):
    parent = tmp_path / "parent.mp4"
    await fixture_video(parent, True)
    # Decode every frame independently in FFmpeg; this also proves the fixture changes at EOF.
    process = await asyncio.create_subprocess_exec(
        "ffmpeg", "-v", "error", "-i", str(parent), "-map", "0:v:0", "-an",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-fps_mode", "passthrough", "pipe:1",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    pixels, stderr = await process.communicate()
    assert process.returncode == 0, stderr.decode()
    size = 64 * 96 * 3
    assert len(pixels) == 56 * size
    assert pixels[-size:] != pixels[-2 * size:-size]
    destination = tmp_path / "last.png"
    result = await prepare_last_frame(parent, destination)
    assert result == {
        "path": str(destination), "source_frame_count": 56, "source_frame_index": 55,
        "width": 64, "height": 96, "format": "PNG", "mode": "RGB",
    }
    with Image.open(destination) as image:
        assert image.mode == "RGB"
        assert image.tobytes() == pixels[-size:]
        assert not image.info
    assert not list(tmp_path.glob("*.part.png"))


async def test_last_frame_rejects_uncounted_or_missing_video(tmp_path, monkeypatch):
    parent = tmp_path / "parent.mp4"
    parent.write_bytes(b"mocked parent")
    destination = tmp_path / "last.png"
    for streams, message in [
        ([], "no video"),
        ([{"codec_type": "video", "nb_read_frames": "N/A"}], "count decoded"),
        ([{"codec_type": "video", "nb_read_frames": "0"}], "no decoded"),
    ]:
        async def fake_probe(path, streams=streams):
            return {"streams": streams}

        monkeypatch.setattr(media, "probe", fake_probe)
        with pytest.raises(ValueError, match=message):
            await prepare_last_frame(parent, destination)
        assert not destination.exists()


@pytest.mark.parametrize("operation", ["frame", "tail"])
async def test_prepared_media_rejects_overwrite_symlinks_and_traversal(tmp_path, operation):
    parent = tmp_path / "parent.mp4"
    await fixture_video(parent, False)

    async def prepare(source, target):
        if operation == "frame":
            return await prepare_last_frame(source, target)
        return await prepare_tail(source, target, 3)

    existing = tmp_path / "existing"
    existing.write_bytes(b"do not change")
    with pytest.raises(ValueError, match="overwrite"):
        await prepare(parent, existing)
    assert existing.read_bytes() == b"do not change"
    link = tmp_path / "link"
    link.symlink_to(tmp_path / "absent")
    with pytest.raises(ValueError, match="symlinks"):
        await prepare(parent, link)
    directory = tmp_path / "directory"
    directory.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(directory, target_is_directory=True)
    with pytest.raises(ValueError, match="symlinks"):
        await prepare(parent, alias / "output")
    source_alias = tmp_path / "source_alias.mp4"
    source_alias.symlink_to(parent)
    with pytest.raises(ValueError, match="symlinks"):
        await prepare(source_alias, tmp_path / "output")
    with pytest.raises(ValueError, match="traversal"):
        await prepare(parent, directory / ".." / "output")


@pytest.mark.parametrize("operation", ["frame", "tail"])
async def test_prepared_media_atomic_publication_never_overwrites(tmp_path, monkeypatch, operation):
    parent = tmp_path / "parent.mp4"
    await fixture_video(parent, False)
    destination = tmp_path / ("last.png" if operation == "frame" else "tail.mp4")
    command = media._command

    async def create_competing_destination(*arguments):
        result = await command(*arguments)
        if arguments[0] == "ffmpeg":
            destination.write_bytes(b"competitor")
        return result

    monkeypatch.setattr(media, "_command", create_competing_destination)
    with pytest.raises(FileExistsError):
        if operation == "frame":
            await prepare_last_frame(parent, destination)
        else:
            await prepare_tail(parent, destination, 3)
    assert destination.read_bytes() == b"competitor"
    assert not list(tmp_path.glob(".*.part.*"))


async def test_assembled_preview_retains_all_frames(tmp_path):
    first, second = tmp_path / "first.mp4", tmp_path / "second.mp4"
    await fixture_video(first, True)
    await fixture_video(second, True)
    result = await concatenate([first, second], tmp_path / "assembled.mp4")
    assert result["assembly"] == "external_concat_no_overlap_trim_no_crossfade"
    video = next(s for s in result["probe"]["streams"] if s["codec_type"] == "video")
    assert int(video["nb_read_frames"]) == 112
    assert float(video["duration"]) == pytest.approx(112 / 24, abs=1 / 24)


def test_image_format_and_integrity(tmp_path):
    path = tmp_path / "safe.png"
    Image.new("RGB", (32, 48)).save(path)
    assert verify_image(path) == {"width": 32, "height": 48, "format": "PNG"}


def test_truncated_jpeg_is_rejected_before_upload(tmp_path):
    path = tmp_path / "truncated.jpg"
    Image.new("RGB", (32, 48)).save(path, format="JPEG")
    path.write_bytes(path.read_bytes()[:-20])
    with pytest.raises(ValueError, match="Corrupt"):
        verify_image(path)

import asyncio
from pathlib import Path

import pytest
from PIL import Image

from h3_backend.media import concatenate, prepare_tail, probe, verify_image


async def fixture_video(path: Path, audio: bool):
    arguments = ["ffmpeg", "-v", "error", "-n", "-f", "lavfi", "-i", "testsrc2=size=64x96:rate=24"]
    if audio:
        arguments += ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=32000", "-c:a", "aac"]
    arguments += ["-t", str(56 / 24), "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)]
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
    with pytest.raises(ValueError, match="overwrite"):
        await prepare_tail(parent, tmp_path / "tail.mp4", 2)
    with pytest.raises(ValueError, match="two or three"):
        await prepare_tail(parent, tmp_path / "invalid.mp4", 5)


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

"""CPU-only comparators may use Pillow; the application must not import it."""
import asyncio
import hashlib
import sys
from pathlib import Path

import pytest
from PIL import Image

from h3_backend.infrastructure import media


@pytest.mark.parametrize("format", ["PNG", "JPEG", "WEBP"])
def test_format_is_content_not_extension(tmp_path, format):
    path = tmp_path / "untrusted.extension"
    Image.new("RGB", (32, 48), "red").save(path, format=format)
    assert media.verify_image(path) == {"width": 32, "height": 48, "format": format}


@pytest.mark.parametrize("format", ["PNG", "JPEG", "WEBP"])
def test_corrupt_compressed_image_rejected(tmp_path, format):
    path = tmp_path / "corrupt"
    Image.new("RGB", (128, 128), "red").save(path, format=format)
    data = path.read_bytes()
    path.write_bytes(data[:len(data) // 2])
    with pytest.raises(ValueError, match="Corrupt"):
        media.verify_image(path)


@pytest.mark.parametrize("format", ["PNG", "WEBP", "GIF"])
def test_animated_images_rejected(tmp_path, format):
    path = tmp_path / "animation"
    Image.new("RGB", (32, 48), "red").save(
        path, format=format, save_all=True,
        append_images=[Image.new("RGB", (32, 48), "blue")], duration=100, loop=0,
    )
    with pytest.raises(ValueError):
        media.verify_image(path)


def test_image_size_limit_precedes_tools(tmp_path, monkeypatch):
    path = tmp_path / "large"
    with path.open("wb") as file:
        file.truncate(32 * 1024**2 + 1)

    async def forbidden(*args):
        pytest.fail("Oversized encoded input must not reach tools")

    monkeypatch.setattr(media, "_command", forbidden)
    with pytest.raises(ValueError, match="32 MiB"):
        media.verify_image(path)


async def test_geometry_limit_precedes_full_decode(tmp_path, monkeypatch):
    async def command(*arguments):
        assert arguments[0] == "ffprobe"
        return (b'{"streams":[{"codec_name":"png","width":10000,"height":10000}],'
                b'"format":{"format_name":"png_pipe"}}')

    monkeypatch.setattr(media, "_command", command)
    with pytest.raises(ValueError, match="megapixels"):
        await media._verify_image(tmp_path / "bomb.png")


def test_identity_path_guards(tmp_path):
    source = tmp_path / "image.png"
    Image.new("RGB", (32, 48)).save(source)
    link = tmp_path / "alias.png"
    link.symlink_to(source)
    with pytest.raises(ValueError, match="symlinks"):
        media.verify_image(link)
    with pytest.raises(ValueError, match="traversal"):
        media.verify_image(tmp_path / ".." / "image.png")


def test_hash_never_uses_whole_file_read(tmp_path, monkeypatch):
    path = tmp_path / "encoded"
    data = b"raw encoded bytes" * 100000
    path.write_bytes(data)

    def forbidden(*args):
        pytest.fail("Whole file reads forbidden")

    monkeypatch.setattr(Path, "read_bytes", forbidden)
    assert media.sha256_file(path) == hashlib.sha256(data).hexdigest()


async def test_assembly_path_guards_precede_decoding(tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"not decoded")
    alias = tmp_path / "alias.mp4"
    alias.symlink_to(source)
    with pytest.raises(ValueError, match="symlinks"):
        await media.concatenate([alias], tmp_path / "output.mp4")
    with pytest.raises(ValueError, match="traversal"):
        await media.concatenate([source], tmp_path / ".." / "output.mp4")


async def test_command_bounds_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(media, "STDOUT_LIMIT", 1024)
    with pytest.raises(ValueError, match="bounded output"):
        await asyncio.wait_for(media._command(
            sys.executable, "-c", "import sys;sys.stdout.write('x'*10000000)",
        ), timeout=3)


async def test_command_stderr_keeps_only_tail(monkeypatch):
    with pytest.raises(ValueError) as error:
        await media._command(
            sys.executable, "-c", "import sys;sys.stderr.write('x'*20000+'END');sys.exit(1)",
        )
    assert str(error.value).endswith("END")
    assert len(str(error.value)) < 2100


@pytest.mark.parametrize("cancel", [False, True])
async def test_command_timeout_and_cancellation_reap_child(tmp_path, monkeypatch, cancel):
    pid = tmp_path / "pid"
    monkeypatch.setattr(media, "COMMAND_TIMEOUT", 0.3)
    task = asyncio.create_task(media._command(
        sys.executable, "-c",
        "import os,time,pathlib;pathlib.Path(__import__('sys').argv[1]).write_text(str(os.getpid()));"
        "time.sleep(60)", str(pid),
    ))
    if cancel:
        # Wait for a deterministic child signal rather than guessing startup latency.
        for _ in range(100):
            if pid.exists():
                break
            await asyncio.sleep(0.005)
        task.cancel()
    with pytest.raises(asyncio.CancelledError if cancel else TimeoutError):
        await task
    assert pid.exists()
    assert not Path(f"/proc/{pid.read_text()}").exists()

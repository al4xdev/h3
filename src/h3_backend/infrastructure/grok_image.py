"""Owned encoded stills for the independent text editor, never generation state."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import re
import tempfile
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from stat import S_ISREG
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

IMAGE_MAX_BYTES = 20 * 1024**2
BUFFER_BYTES = 48 * 1024  # Divisible by three: only the final base64 chunk needs padding.
METADATA_MAX_BYTES = 1024 * 1024


class EditorReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_root: Literal["assets", "inputs", "runs"]
    path: str = Field(min_length=1, max_length=1024, strict=True)

    @field_validator("path")
    @classmethod
    def public_relative(cls, value: str) -> str:
        parts = value.split("/")
        if (value.startswith("/") or "\\" in value or any(ord(c) < 32 for c in value)
                or any(not p or p in (".", "..") for p in parts)
                or any(p.startswith(".") for p in parts[1:])
                or (parts[0].startswith(".") and not value.startswith(".data/runs/"))):
            raise ValueError("Use an owned public image path")
        return value


def _regular(descriptor: int, limit: int):
    info = os.fstat(descriptor)
    if (not S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1
            or not 0 < info.st_size <= limit):
        raise ValueError("Image or ownership metadata has invalid type, owner, links or size")
    return info


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


@contextmanager
def _directory(root: Path, parts: tuple[str, ...], *, create: bool = False):
    # Traverse every component by held no-follow descriptors, not resolve/check/open.
    descriptors = []
    try:
        absolute = root.absolute()
        if ".." in absolute.parts:
            raise ValueError("Project root must not contain traversal")
        directory = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        descriptors.append(directory)
        for part in absolute.parts[1:]:
            directory = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                dir_fd=directory)
            descriptors.append(directory)
        for part in parts:
            if create:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=directory)
                except FileExistsError:
                    pass
            directory = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                dir_fd=directory)
            descriptors.append(directory)
        yield directory
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


@contextmanager
def _open(root: Path, parts: tuple[str, ...]):
    with _directory(root, parts[:-1]) as directory:
        descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                             dir_fd=directory)
        try:
            yield descriptor
        finally:
            os.close(descriptor)


@contextmanager
def _snapshot(root: Path):
    # Keep scratch on the project filesystem, not /tmp (which can be RAM-backed).
    # The held directory fd also protects TemporaryFile's fallback unlink from path replacement.
    with (
        _directory(root, (".dumps", "grok-editor"), create=True) as directory,
        tempfile.TemporaryFile(mode="w+b", dir=f"/proc/self/fd/{directory}") as snapshot,
    ):
        yield snapshot


def _metadata(root: Path, parts: tuple[str, ...]) -> dict:
    with _open(root, parts) as descriptor:
        before = _regular(descriptor, METADATA_MAX_BYTES)
        raw = bytearray()
        while block := os.read(descriptor, min(BUFFER_BYTES, METADATA_MAX_BYTES + 1 - len(raw))):
            raw.extend(block)
            if len(raw) > METADATA_MAX_BYTES:
                raise ValueError("Ownership metadata exceeds limit")
        if _identity(before) != _identity(os.fstat(descriptor)):
            raise ValueError("Ownership metadata changed during read")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Ownership metadata must be an object")  # noqa: TRY004 - bad media is HTTP400.
    return value


def _uuid(value: str) -> str:
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("Noncanonical media identity")
    return value


def _digest(value) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ValueError("Image has no published SHA proof")
    return value


def _migration(root: Path, run_id: str, filename: str) -> str:
    receipt = _metadata(root, (".data", "state", "migration.json"))
    ident = _uuid(receipt.get("id", ""))
    proof = _metadata(root, (".data", "migrations", ident, "verified.json"))
    inventory = receipt.get("inventory", {})
    if (not isinstance(inventory, dict) or proof != receipt
            or not isinstance(receipt.get("run_ids"), list)
            or receipt.get("schema_version") != 1 or receipt.get("state") != "complete"
            or receipt.get("root") != str(root.absolute())
            or receipt.get("destination") != ".data/runs"
            or receipt.get("run_ids") != inventory.get("run_ids")
            or run_id not in receipt.get("run_ids", [])
            or receipt.get("inventory_sha256") != hashlib.sha256(
                json.dumps(inventory, sort_keys=True).encode()).hexdigest()):
        raise ValueError("Run image has no verified migration ownership")
    files = inventory.get("files", {})
    if not isinstance(files, dict) or not isinstance(files.get(f"{run_id}/{filename}"), dict):
        raise ValueError("Run image missing from migration inventory")  # noqa: TRY004
    return _digest(files[f"{run_id}/{filename}"].get("sha256"))


def _source(root: Path, reference: EditorReference) -> tuple[tuple[str, ...], str | None]:
    parts = tuple(reference.path.split("/"))
    suffix = Path(parts[-1]).suffix.lower()
    if suffix not in (".png", ".jpg", ".jpeg"):
        raise ValueError("Grok accepts only JPEG or PNG images; no automatic conversion")
    if reference.source_root == "assets":
        if any(p.startswith(".") for p in parts):
            raise ValueError("Private asset is not a reference")
        return ("assets", *parts), None
    if reference.source_root == "inputs":
        if len(parts) != 2 or parts[1] not in ("original.png", "original.jpg", "original.jpeg"):
            raise ValueError("Input must be a published original image")
        ident = _uuid(parts[0])
        metadata = _metadata(root, (".data", "inputs", ident, "metadata.json"))
        if (metadata.get("id") != ident or metadata.get("source_root") != "inputs"
                or metadata.get("path") != reference.path):
            raise ValueError("Input ownership metadata disagrees with selected image")
        # A publication in progress is not an image capability, even if metadata exists.
        try:
            with _open(root, (".data", "inputs", ident, ".part")):
                raise ValueError("Input publication is incomplete")
        except FileNotFoundError:
            pass
        return (".data", "inputs", *parts), _digest(metadata.get("sha256"))
    if len(parts) == 4 and parts[:2] == (".data", "runs"):
        run_id, filename = parts[2:]
        legacy = False
    elif len(parts) == 3 and parts[0] == "runs":
        run_id, filename = parts[1:]
        legacy = True
    else:
        raise ValueError("Run image must be a canonical own frame path")
    _uuid(run_id)
    if filename not in ("initial_frame.png", "last_frame.png"):
        raise ValueError("Only published run still frames are supported")
    manifest = _metadata(root, (".data", "runs", run_id, "manifest.json"))
    if manifest.get("id") != run_id:
        raise ValueError("Run manifest identity disagrees with directory")
    if not legacy:
        references = manifest.get("references", [])
        if not isinstance(references, list):
            raise ValueError("Invalid run ownership references")
        for row in references:
            if (isinstance(row, dict) and row.get("type") == "image"
                    and row.get("source_root") == "runs" and row.get("source") == reference.path):
                return (".data", "runs", run_id, filename), _digest(row.get("sha256"))
    # Legacy aliases and unreferenced migrated frames require the exact receipt pair.
    return (".data", "runs", run_id, filename), _migration(root, run_id, filename)


def _copy_owned(root: Path, reference: EditorReference, snapshot) -> None:
    parts, proof = _source(root, reference)
    digest = hashlib.sha256()
    with _open(root, parts) as descriptor:
        before = _regular(descriptor, IMAGE_MAX_BYTES)
        size = 0
        while block := os.read(descriptor, BUFFER_BYTES):
            size += len(block)
            if size > IMAGE_MAX_BYTES:
                raise ValueError("Grok image exceeds 20 MiB")
            snapshot.write(block)
            digest.update(block)
        if size != before.st_size or _identity(before) != _identity(os.fstat(descriptor)):
            raise ValueError("Source image changed while copying")
        with _open(root, parts) as current:
            if _identity(before) != _identity(_regular(current, IMAGE_MAX_BYTES)):
                raise ValueError("Source image was replaced while copying")
        # Re-read bounded ownership proof after the copy, too; a receipt race fails closed.
        if _source(root, reference) != (parts, proof) or (proof and digest.hexdigest() != proof):
            raise ValueError("Image SHA disagrees with published ownership proof")
    snapshot.flush()
    snapshot.seek(0)


async def _command(descriptor: int, *arguments: str) -> bytes:
    async def reap(process):
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass

        async def discard(stream):
            while await stream.read(4096):
                pass

        # Discard while reaping; a full pipe must not block wait().
        await asyncio.gather(discard(process.stdout), discard(process.stderr), process.wait())

    creation = asyncio.create_task(asyncio.create_subprocess_exec(
        *arguments, pass_fds=(descriptor,), stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    ))
    try:
        process = await asyncio.shield(creation)
    except asyncio.CancelledError:
        # Cancellation can arrive while the OS has spawned a child but before it is returned.
        process = await creation
        await reap(process)
        raise

    async def capture(stream):
        result = bytearray()
        while block := await stream.read(4096):
            result.extend(block)
            if len(result) > 16384:
                raise ValueError("Image validation metadata exceeds limit")
        return bytes(result)

    readers = [asyncio.create_task(capture(s)) for s in (process.stdout, process.stderr)]
    try:
        stdout, _, _ = await asyncio.wait_for(
            asyncio.gather(*readers, process.wait()), timeout=120,
        )
        if process.returncode:
            raise ValueError("Image is corrupt or unsupported")
        return stdout
    finally:
        for reader in readers:
            reader.cancel()
        await asyncio.gather(*readers, return_exceptions=True)
        await reap(process)


async def _validate(snapshot) -> str:
    descriptor = snapshot.fileno()
    path = f"/proc/self/fd/{descriptor}"
    header = json.loads(await _command(
        descriptor, "ffprobe", "-v", "error", "-probesize", "1048576", "-analyzeduration", "0",
        "-show_entries", "stream=codec_name,width,height:format=format_name", "-of", "json", path,
    ))
    if not isinstance(header, dict):
        raise ValueError("Invalid image validation metadata")  # noqa: TRY004
    streams = header.get("streams", [])
    if (not isinstance(streams, list) or len(streams) != 1 or not isinstance(streams[0], dict)
            or streams[0].get("codec_name") not in ("png", "mjpeg")
            or header.get("format", {}).get("format_name") not in ("png_pipe", "jpeg_pipe", "image2")):
        raise ValueError("Grok accepts only a single JPEG or PNG still")
    width, height = streams[0].get("width", 0), streams[0].get("height", 0)
    if (type(width) is not int or type(height) is not int or width <= 0 or height <= 0
            or width * height > 16_000_000):
        raise ValueError("Image exceeds the local 16 megapixel safety limit")
    progress = await _command(
        descriptor, "ffmpeg", "-v", "error", "-xerror", "-err_detect", "crccheck+explode",
        "-nostdin", "-i", path, "-map", "0:v:0", "-frames:v", "2", "-an",
        "-fps_mode", "passthrough", "-progress", "pipe:1", "-f", "null", "-",
    )
    counts = [int(line[6:]) for line in progress.splitlines() if line.startswith(b"frame=")]
    if not counts or counts[-1] != 1:
        raise ValueError("Image must be one complete still, not an animation")
    snapshot.seek(0)  # Child processes may advance the shared open file description.
    return "image/png" if streams[0]["codec_name"] == "png" else "image/jpeg"


@asynccontextmanager
async def owned_image(root: Path, reference: EditorReference):
    # An anonymous private disk snapshot freezes validated bytes without a media-sized heap.
    with _snapshot(root) as snapshot:
        task = asyncio.create_task(asyncio.to_thread(_copy_owned, root, reference, snapshot))
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            # to_thread cannot be cancelled: finish before closing its owned descriptor.
            await asyncio.gather(task, return_exceptions=True)
            raise
        mime = await _validate(snapshot)
        yield snapshot, mime


def image_json_body(model: str, system: str, prompt: str, snapshot, mime: str):
    messages = [{"role": "system", "content": system}] if system else []
    prefix = json.dumps({"model": model}, ensure_ascii=False).encode()[:-1] + b',"input":['
    if messages:
        prefix += json.dumps(messages[0], ensure_ascii=False).encode() + b","
    prefix += (b'{"role":"user","content":[{"type":"input_image","image_url":"data:'
               + mime.encode("ascii") + b";base64,")
    suffix = (b'"},{"type":"input_text","text":' + json.dumps(prompt, ensure_ascii=False).encode()
              + b'}]}],"max_output_tokens":8192,"stream":false,"store":false}')
    size = os.fstat(snapshot.fileno()).st_size

    async def chunks():
        yield prefix
        carry = b""
        while True:
            task = asyncio.create_task(asyncio.to_thread(snapshot.read, BUFFER_BYTES))
            try:
                block = await asyncio.shield(task)
            except asyncio.CancelledError:
                await asyncio.gather(task, return_exceptions=True)
                raise
            if not block:
                break
            block = carry + block
            complete = len(block) - len(block) % 3
            carry = block[complete:]
            if complete:
                yield base64.b64encode(block[:complete])
        if carry:
            yield base64.b64encode(carry)
        yield suffix

    return chunks(), len(prefix) + 4 * ((size + 2) // 3) + len(suffix)

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

import anyio
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
    with _directory(root, (".dumps", "grok-editor"), create=True) as directory:
        info = os.fstat(directory)
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("Editor scratch directory must be owner-private")
        with tempfile.TemporaryFile(mode="w+b", dir=f"/proc/self/fd/{directory}") as snapshot:
            yield snapshot


def _metadata(root: Path, parts: tuple[str, ...], *, with_identity: bool = False):
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
    return (value, _identity(before)) if with_identity else value


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


async def _command(descriptor: int | tuple[int, ...], *arguments: str) -> bytes:
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
        *arguments, pass_fds=(descriptor,) if isinstance(descriptor, int) else descriptor,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    ))
    try:
        process = await asyncio.shield(creation)
    except asyncio.CancelledError:
        # Cancellation can arrive while the OS has spawned a child but before it is returned.
        with anyio.CancelScope(shield=True):
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
        with anyio.CancelScope(shield=True):
            for reader in readers:
                reader.cancel()
            await asyncio.gather(*readers, return_exceptions=True)
            await reap(process)


async def _validate(snapshot) -> str:
    descriptor = snapshot.fileno()
    path = f"/proc/self/fd/{descriptor}"
    header = json.loads(await _command(
        descriptor, "ffprobe", "-v", "error", "-probesize", "1048576", "-analyzeduration", "0",
        "-protocol_whitelist", "file,pipe", "-format_whitelist", "png_pipe,jpeg_pipe,image2",
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
        "-nostdin", "-protocol_whitelist", "file,pipe", "-format_whitelist",
        "png_pipe,jpeg_pipe,image2", "-i", path, "-map", "0:v:0", "-frames:v", "2", "-an",
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
        await _thread(_copy_owned, root, reference, snapshot)
        mime = await _validate(snapshot)
        yield snapshot, mime


def image_json_body(model: str, system: str, prompt: str, snapshot, mime: str):
    """Compatibility wrapper: preserve the original single-image wire/chunk shape."""
    return images_json_body(model, system, prompt, [(snapshot, mime)])


VIDEO_MAX_BYTES = 256 * 1024**2
VIDEO_MAX_FRAMES = 3600  # Editor CPU budget, not a generation/model limit.
CONTINUATION_LABEL = (
    "Analise AMBAS as imagens: a primeira é a referência original de identidade/aparência; "
    "a segunda é o último frame do pai aceito, com a pose, roupa e estado atual da cena. "
    "Preserve a identidade da primeira e a continuidade da segunda, respeitando somente "
    "as mudanças da instrução do usuário abaixo."
)


def _parent(root: Path, parent_id: str):
    ident = _uuid(parent_id)
    manifest, marker_identity = _metadata(
        root, (".data", "runs", ident, "manifest.json"), with_identity=True)
    output, decision = manifest.get("output"), manifest.get("decision")
    if (manifest.get("id") != ident or manifest.get("state") != "accepted"
            or manifest.get("error") is not None or not isinstance(decision, dict)
            or decision.get("accepted") is not True or not isinstance(output, dict)):
        raise ValueError("Parent is not an accepted canonical video publication")
    video_digest = None
    if output.get("path") == f".data/runs/{ident}/chunk.mp4":
        if manifest.get("publication_mode") != "atomic_copy_from_comfy_output":
            raise ValueError("Parent has no atomic canonical publication")
    elif output.get("path") == f"runs/{ident}/chunk.mp4":
        # A legacy logical alias is never a path capability: only the verified
        # migration inventory authorizes reading the fixed canonical disk location.
        video_digest = _migration(root, ident, "chunk.mp4")
    else:
        raise ValueError("Parent output is not its own canonical video")
    references = manifest.get("references")
    if not isinstance(references, list) or any(not isinstance(row, dict) for row in references):
        raise ValueError("Invalid parent identity metadata")
    if any((row.get("type"), row.get("role")) not in {
        ("image", "identity"), ("image", "initial_frame"), ("video", "motion_video"),
    } for row in references):
        raise ValueError("Unsupported or ambiguous parent reference roles")
    identities = [row for row in references if row.get("role") == "identity"]
    if len(identities) != 1 or identities[0].get("type") != "image":
        raise ValueError("Continuation editor requires exactly one original identity image")
    row = identities[0]
    reference = EditorReference(source_root=row.get("source_root"), path=row.get("source"))
    return manifest, reference, _digest(row.get("sha256")), marker_identity, video_digest


def _file_digest(root: Path, parts: tuple[str, ...], limit: int, snapshot=None):
    digest, size = hashlib.sha256(), 0
    with _open(root, parts) as descriptor:
        before = _regular(descriptor, limit)
        while block := os.read(descriptor, BUFFER_BYTES):
            size += len(block)
            if size > limit:
                raise ValueError("Source exceeds editor operational byte budget")
            digest.update(block)
            if snapshot is not None:
                snapshot.write(block)
        if size != before.st_size or _identity(before) != _identity(os.fstat(descriptor)):
            raise ValueError("Source changed during snapshot")
        with _open(root, parts) as current:
            if _identity(before) != _identity(_regular(current, limit)):
                raise ValueError("Source replaced during snapshot")
    if snapshot is not None:
        snapshot.flush()
        snapshot.seek(0)
    return _identity(before), digest.hexdigest()


async def _thread(operation, *arguments):
    # A disk-copy thread must finish before cancellation closes its held file.
    task = asyncio.create_task(asyncio.to_thread(operation, *arguments))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        with anyio.CancelScope(shield=True):
            await asyncio.gather(task, return_exceptions=True)
        raise


async def _final_frame(video, frame):
    descriptor = video.fileno()
    path = f"/proc/self/fd/{descriptor}"
    header = json.loads(await _command(
        descriptor, "ffprobe", "-v", "error", "-select_streams", "v",
        "-protocol_whitelist", "file,pipe", "-f", "mov",
        "-show_entries", "stream=width,height:format=format_name", "-of", "json", path,
    ))
    streams = header.get("streams", [])
    if (len(streams) != 1 or header.get("format", {}).get("format_name")
            != "mov,mp4,m4a,3gp,3g2,mj2"):
        raise ValueError("Parent must contain one MP4 video stream")
    width, height = streams[0].get("width"), streams[0].get("height")
    if (type(width) is not int or type(height) is not int or width <= 0 or height <= 0
            or width * height > 16_000_000):
        raise ValueError("Parent exceeds editor 16 megapixel budget")
    details = json.loads(await _command(
        descriptor, "ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
        "-protocol_whitelist", "file,pipe", "-f", "mov",
        "-show_entries", "stream=nb_read_frames", "-of", "json", path,
    ))
    count = int(details["streams"][0]["nb_read_frames"])
    if not 0 < count <= VIDEO_MAX_FRAMES:
        raise ValueError("Parent exceeds editor decoded-frame budget")
    await _command(
        (descriptor, frame.fileno()), "ffmpeg", "-v", "error", "-xerror", "-nostdin", "-y",
        "-protocol_whitelist", "file,pipe", "-f", "mov", "-i", path, "-map", "0:v:0", "-vf",
        f"select=eq(n\\,{count - 1}),format=rgb24,setsar=0", "-fps_mode", "passthrough",
        "-frames:v", "1", "-an", "-map_metadata", "-1", "-c:v", "png", "-pix_fmt", "rgb24",
        "-fs", str(IMAGE_MAX_BYTES + 1), "-f", "image2pipe", f"/proc/self/fd/{frame.fileno()}",
    )
    # Anonymous snapshots intentionally have zero links, unlike published sources.
    info = os.fstat(frame.fileno())
    if (not S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 0
            or not 0 < info.st_size <= IMAGE_MAX_BYTES):
        raise ValueError("Derived frame exceeds private snapshot budget")
    frame.seek(0)
    derived = json.loads(await _command(
        frame.fileno(), "ffprobe", "-v", "error", "-show_entries",
        "stream=width,height,pix_fmt", "-of", "json", f"/proc/self/fd/{frame.fileno()}",
    ))
    if derived.get("streams") != [{"width": width, "height": height, "pix_fmt": "rgb24"}]:
        raise ValueError("Derived frame geometry or RGB mode disagrees with parent")
    if await _validate(frame) != "image/png":
        raise ValueError("Derived final frame must be PNG")


@asynccontextmanager
async def continuation_frame(root: Path, parent_id: str, reference: EditorReference | None = None):
    """Read-only publication proof; only private anonymous editor scratch is written."""
    proof = await _thread(_parent, root, parent_id)
    _, original, digest, _, published_video_digest = proof
    if reference is not None and reference != original:
        raise ValueError("Selected identity does not match accepted parent")
    parts = (".data", "runs", parent_id, "chunk.mp4")
    with _snapshot(root) as video, _snapshot(root) as frame:
        video_proof = await _thread(_file_digest, root, parts, VIDEO_MAX_BYTES, video)
        if published_video_digest is not None and video_proof[1] != published_video_digest:
            raise ValueError("Migrated video SHA disagrees with verified publication")
        await _final_frame(video, frame)

        def recheck():
            if _parent(root, parent_id) != proof:
                raise ValueError("Parent publication changed during preparation")
            if _file_digest(root, parts, VIDEO_MAX_BYTES) != video_proof:
                raise ValueError("Parent video changed during preparation")
            if reference is not None:
                image_parts, image_proof = _source(root, reference)
                if image_proof is not None and image_proof != digest:
                    raise ValueError("Identity publication disagrees with parent")
                if _file_digest(root, image_parts, IMAGE_MAX_BYTES)[1] != digest:
                    raise ValueError("Identity SHA disagrees with accepted parent")
            if _parent(root, parent_id) != proof:
                raise ValueError("Parent proof changed during final source check")

        await _thread(recheck)
        yield frame, recheck, digest


def snapshot_digest(snapshot):
    snapshot.seek(0)
    digest = hashlib.sha256()
    while block := snapshot.read(BUFFER_BYTES):
        digest.update(block)
    snapshot.seek(0)
    return digest.hexdigest()


async def encoded_chunks(snapshot):
    """Encoded disk bytes only; cancellation joins an in-flight read before close."""
    while block := await _thread(snapshot.read, BUFFER_BYTES):
        yield block


def images_json_body(model: str, system: str, prompt: str, images):
    """One or two flat Responses images, no media-sized Python allocation."""
    if len(images) not in (1, 2):
        raise ValueError("Editor requires one image or both continuation contexts")
    sizes = [os.fstat(snapshot.fileno()).st_size for snapshot, _ in images]
    if any(not 0 < size <= IMAGE_MAX_BYTES for size in sizes):
        raise ValueError("Editor image exceeds encoded byte budget")
    prefix = json.dumps({"model": model}, ensure_ascii=False).encode()[:-1] + b',"input":['
    if system:
        prefix += json.dumps({"role": "system", "content": system}, ensure_ascii=False).encode() + b","
    prefix += b'{"role":"user","content":['
    if len(images) == 2:
        prefix += json.dumps({"type": "input_text", "text": CONTINUATION_LABEL},
                             ensure_ascii=False).encode() + b","
    heads = [b'{"type":"input_image","image_url":"data:' + mime.encode("ascii") + b";base64,"
             for _, mime in images]
    suffix = (b',{"type":"input_text","text":' + json.dumps(prompt, ensure_ascii=False).encode()
              + b'}]}],"max_output_tokens":8192,"stream":false,"store":false}')

    async def chunks():
        initial = prefix + heads[0]
        for offset in range(0, len(initial), BUFFER_BYTES):
            yield initial[offset:offset + BUFFER_BYTES]
        for index, (snapshot, _) in enumerate(images):
            if index:
                yield heads[index]
            carry = b""
            async for block in encoded_chunks(snapshot):
                block = carry + block
                complete = len(block) - len(block) % 3
                carry = block[complete:]
                if complete:
                    yield base64.b64encode(block[:complete])
            if carry:
                yield base64.b64encode(carry)
            if index < len(images) - 1:
                yield b'"},'
        ending = b'"}' + suffix
        for offset in range(0, len(ending), BUFFER_BYTES):
            yield ending[offset:offset + BUFFER_BYTES]

    length = (len(prefix) + sum(len(head) for head in heads)
              + sum(4 * ((size + 2) // 3) for size in sizes)
              + 3 * (len(images) - 1) + 2 + len(suffix))
    return chunks(), length

"""Linux filesystem hints; recovery invalidates metadata and never replays intent."""

from __future__ import annotations

import asyncio
import ctypes
import errno
import os
import stat
import struct
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from uuid import UUID

from .store import safe_path

CREATE = 0x100
MOVED_TO = 0x80
CLOSE_WRITE = 0x8
DELETE = 0x200
ATTRIB = 0x4
DELETE_SELF = 0x400
MOVE_SELF = 0x800
OVERFLOW = 0x4000
IGNORED = 0x8000
ISDIR = 0x40000000
MASK = CREATE | MOVED_TO | CLOSE_WRITE | DELETE | ATTRIB | DELETE_SELF | MOVE_SELF
HEADER = struct.Struct("iIII")


class FileWatcher:
    """One fd, fixed application roots, bounded path-only subscriber queues."""

    def __init__(
        self, project_root: Path, *, on_request: Callable[[str], None] | None = None,
        queue_size: int = 64, max_watches: int = 4096, max_subscribers: int = 64,
    ):
        if not 1 <= queue_size <= 1024 or not 3 <= max_watches <= 16384:
            raise ValueError("Invalid watcher bounds")
        if not 1 <= max_subscribers <= 1024:
            raise ValueError("Invalid subscriber bound")
        self.root = project_root.resolve()
        self.data = safe_path(self.root, ".data")
        self.on_request = on_request
        self.queue_size = queue_size
        self.max_watches = max_watches
        self.max_subscribers = max_subscribers
        self.fd: int | None = None
        self._loop = None
        self._watches: dict[int, Path] = {}
        self._subscribers: set[asyncio.Queue] = set()
        self._libc = ctypes.CDLL(None, use_errno=True)
        self._libc.inotify_init1.argtypes = [ctypes.c_int]
        self._libc.inotify_init1.restype = ctypes.c_int
        self._libc.inotify_add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
        self._libc.inotify_add_watch.restype = ctypes.c_int

    def start(self) -> None:
        if self.fd is not None:
            raise ValueError("Watcher already started")
        self._loop = asyncio.get_running_loop()
        self.data.mkdir(exist_ok=True)
        for name in ("runs", "inputs", "assemblies"):
            safe_path(self.data, name).mkdir(exist_ok=True)
        try:
            self._install()
        except Exception:
            self.close()
            raise

    def _install(self) -> None:
        fd = self._libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
        if fd < 0:
            raise OSError(ctypes.get_errno(), "inotify_init1 failed")
        self.fd = fd
        self._loop.add_reader(fd, self._readable)
        # Register before scanning, also when rebuilding after an overflow.
        self._register(self.data, execute=False)

    def _register(self, directory: Path, *, execute: bool) -> None:
        try:
            safe_path(self.root, directory.relative_to(self.root))
            info = directory.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_dev != self.data.stat().st_dev:
                return
        except (OSError, ValueError):
            return
        if directory in self._watches.values():
            return
        if len(self._watches) >= self.max_watches:
            self._emit(".data")
            return
        wd = self._libc.inotify_add_watch(
            self.fd, os.fsencode(directory), MASK | 0x01000000 | 0x02000000,
        )  # ONLYDIR and DONT_FOLLOW close the final-component symlink race.
        if wd < 0:
            error = ctypes.get_errno()
            if error in (errno.ENOENT, errno.ENOTDIR, errno.ELOOP):
                return
            raise OSError(error, "inotify_add_watch failed")
        self._watches[wd] = directory
        # No media content is opened; new directories are watched BEFORE their immediate scan.
        with os.scandir(directory) as entries:
            for entry in entries:
                if entry.name.startswith(".") or entry.is_symlink():
                    continue
                path = directory / entry.name
                if entry.is_dir(follow_symlinks=False):
                    if self._allowed_directory(path):
                        self._register(path, execute=execute)
                elif execute:
                    self._candidate(path)

    def _allowed_directory(self, path: Path) -> bool:
        parts = path.relative_to(self.data).parts
        if len(parts) == 1:
            return parts[0] in {"runs", "inputs", "assemblies", "roteiros", "roteiro-batches", "library"}
        if parts[0] == "runs":
            return len(parts) == 2 and self._uuid(parts[1])
        if parts[0] == "roteiros":
            return len(parts) == 2 and self._uuid(parts[1])
        # Match accepted category-relative reference lengths, not an arbitrary nesting depth.
        # The fixed roots and global watch budget still bound this single technical observer.
        return parts[0] in {"inputs", "assemblies"} and len("/".join(parts[1:])) <= 1024

    @staticmethod
    def _uuid(value: str) -> bool:
        try:
            return str(UUID(value)) == value
        except ValueError:
            return False

    def _candidate(self, path: Path) -> None:
        parts = path.relative_to(self.data).parts
        if (len(parts) == 3 and parts[0] == "runs" and self._uuid(parts[1])
                and parts[2] == "request.json" and self.on_request is not None):
            # This is only a hint. Store validates file type/schema and dispatcher owns admission.
            self.on_request(parts[1])

    def _emit(self, path: str) -> None:
        for queue in tuple(self._subscribers):
            if queue.full():
                # Slow clients must reconnect/re-read metadata, not grow a RAM event ledger.
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait(None)
                self._subscribers.discard(queue)
            else:
                queue.put_nowait(path)

    def _readable(self) -> None:
        try:
            for _ in range(16):
                try:
                    raw = os.read(self.fd, 65536)
                except BlockingIOError:
                    return
                offset = 0
                while offset + HEADER.size <= len(raw):
                    wd, mask, _, length = HEADER.unpack_from(raw, offset)
                    offset += HEADER.size
                    name = os.fsdecode(raw[offset:offset + length].split(b"\0", 1)[0])
                    offset += length
                    if mask & (OVERFLOW | IGNORED | DELETE_SELF | MOVE_SELF):
                        self.recover()
                        return
                    directory = self._watches.get(wd)
                    if directory is None or not name or name.startswith(".") or "/" in name:
                        continue
                    path = directory / name
                    if path.relative_to(self.data).parts[0] not in {
                        "runs", "inputs", "assemblies", "roteiros", "roteiro-batches", "library",
                    }:
                        continue
                    self._emit(path.relative_to(self.root).as_posix())
                    if mask & ISDIR:
                        if mask & (CREATE | MOVED_TO) and self._allowed_directory(path):
                            self._register(path, execute=True)
                    elif mask & (CREATE | MOVED_TO | CLOSE_WRITE):
                        self._candidate(path)
        except OSError:
            # A lost watch is diagnostic metadata loss, never permission to replay requests.
            self.close()

    def recover(self) -> None:
        """Reinstall and scan metadata only. Public for explicit loss recovery/testing."""
        self._detach()
        self._install()
        self._emit(".data")

    def _detach(self) -> None:
        if self.fd is not None:
            self._loop.remove_reader(self.fd)
            os.close(self.fd)
            self.fd = None
        self._watches.clear()

    def close(self) -> None:
        self._detach()
        for queue in self._subscribers:
            while not queue.empty():
                queue.get_nowait()
            queue.put_nowait(None)
        self._subscribers.clear()

    async def events(self) -> AsyncIterator[str]:
        """Subscribe to logical relative path hints; disconnect means re-read on reconnect."""
        if self.fd is None:
            raise ValueError("Watcher is not running")
        if len(self._subscribers) >= self.max_subscribers:
            raise ValueError("Too many filesystem subscribers")
        queue = asyncio.Queue(maxsize=self.queue_size)
        self._subscribers.add(queue)
        try:
            yield ".data"  # Each browser connection begins with metadata invalidation, not replay.
            while True:
                path = await queue.get()
                if path is None:
                    return
                yield path
        finally:
            self._subscribers.discard(queue)

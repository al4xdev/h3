"""Offline, verified legacy copy. Import never migrates, starts an API or submits GPU work."""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import shutil
from pathlib import Path
from uuid import UUID, uuid4

from h3_backend.generation.models import Run
from h3_backend.infrastructure.store import Store, safe_path, storage_lock, timestamp

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def inventory(directory: Path) -> dict:
    """Read every regular file, including hidden/nested diagnostics, without following links."""
    files, ids, states, directories = {}, [], {}, []
    if not directory.exists():
        return {"files": files, "directories": directories, "run_ids": ids, "states": states, "bytes": 0}
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("Storage source must be a real directory")
    for child in sorted(directory.iterdir()):
        if child.is_symlink() or not child.is_dir() or str(UUID(child.name)) != child.name:
            raise ValueError("Storage root must contain only canonical UUID directories")
        manifest = safe_path(directory, f"{child.name}/manifest.json")
        run = Run.model_validate_json(manifest.read_text(encoding="utf-8"))
        if run.id != child.name or run.state in {"queued", "running"}:
            raise ValueError("Manifest identity mismatch or pending run; migration must be offline")
        ids.append(run.id)
        directories.append(child.name)
        states[run.id] = run.state
        for path in sorted(child.rglob("*")):
            if path.is_symlink() or not (path.is_file() or path.is_dir()):
                raise ValueError("Symlinks and special files cannot be migrated")
            if path.is_file():
                contents = path.read_bytes()
                files[str(path.relative_to(directory))] = {
                    "sha256": digest(contents), "bytes": len(contents),
                }
            else:
                directories.append(str(path.relative_to(directory)))
    return {"files": files, "directories": sorted(directories), "run_ids": ids, "states": states,
            "bytes": sum(v["bytes"] for v in files.values())}


def publish_json(path: Path, data: dict) -> None:
    """Immutable intent/proof/receipt publication; link never replaces existing files."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}-{uuid4()}.tmp")
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.link(temporary, path)
    # Evidence temporaries are retained if publication fails; successful unlink has an exact path.
    temporary.unlink()
    fd = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def publish_directory(source: Path, destination: Path) -> None:
    """Linux no-replace rename: a concurrent empty destination is a collision, not replaceable."""
    if source.is_symlink() or destination.is_symlink():
        raise ValueError("Publication cannot follow symlinks")
    if source.resolve() != source or destination.resolve() != destination:
        raise ValueError("Publication requires verified absolute canonical paths")
    libc = ctypes.CDLL(None, use_errno=True)
    rename = libc.renameat2
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(source), -100, os.fsencode(destination), 1):
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(destination))
    fd = os.open(destination.parent, os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _finish(root: Path, intent: dict) -> dict:
    source = safe_path(root, "runs")
    destination = safe_path(root, ".data/runs")
    expected = intent["inventory"]
    if inventory(source) != expected or inventory(destination) != expected:
        raise ValueError("Source or published copy differs; preserve evidence and investigate")
    receipt = {"schema_version": 1, "id": intent["id"], "root": str(root),
               "state": "complete", "destination": ".data/runs", "run_ids": expected["run_ids"],
               "inventory": expected, "inventory_sha256": digest(json.dumps(expected, sort_keys=True).encode()),
               "completed_at": timestamp()}
    proof = safe_path(root, f".data/migrations/{intent['id']}/verified.json")
    if proof.exists():
        receipt = json.loads(proof.read_text(encoding="utf-8"))
        if (receipt.get("inventory") != expected or receipt.get("root") != str(root)
                or receipt.get("id") != intent["id"] or receipt.get("state") != "complete"):
            raise ValueError("Existing proof does not match this migration")
    else:
        publish_json(proof, receipt)
    publish_json(safe_path(root, ".data/state/migration.json"), receipt)
    return receipt


def migrate(project_root: Path, *, execute: bool = False, offline: bool = False,
            reconcile: str | None = None) -> dict:
    if project_root.is_symlink():
        raise ValueError("Project root cannot be a symlink")
    root = project_root.resolve(strict=True)
    if execute and not offline:
        raise ValueError("--offline is mandatory for execution")
    # Exclusive lock is also used for preflight: do not report safe while a runtime is active.
    lock = storage_lock(root, exclusive=True)
    try:
        source = safe_path(root, "runs")
        destination = safe_path(root, ".data/runs")
        receipt_path = safe_path(root, ".data/state/migration.json")
        migrations = safe_path(root, ".data/migrations")
        if receipt_path.exists():
            store = Store(root)
            store._authority()  # Read-only validation; no terminal-manifest rewrite.
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            if inventory(source) != receipt["inventory"]:
                raise ValueError("Legacy anchor changed after migration")
            return {"state": "already_complete", "receipt": receipt,
                    "canonical_mutable_data_compared_to_legacy": False}
        if reconcile:
            if not execute or str(UUID(reconcile)) != reconcile:
                raise ValueError("Explicit execute/offline and canonical intent id required")
            intent_path = safe_path(root, f".data/migrations/{reconcile}/intent.json")
            intent = json.loads(intent_path.read_text(encoding="utf-8"))
            if (intent.get("id") != reconcile or intent.get("root") != str(root)
                    or intent.get("destination") != ".data/runs"):
                raise ValueError("Foreign or invalid migration intent")
            if not destination.exists():
                stage = safe_path(root, f".data/migrations/{reconcile}/staging/runs")
                try:
                    verified = inventory(stage) == intent["inventory"] and inventory(source) == intent["inventory"]
                except (OSError, ValueError) as exc:
                    raise ValueError("Staging is incomplete or source changed; no automatic copy/replay") from exc
                if not verified:
                    raise ValueError("Staging is incomplete or source changed; no automatic copy/replay")
                publish_directory(stage, destination)
            return _finish(root, intent)
        if migrations.exists() and any(migrations.iterdir()):
            raise ValueError("Incomplete migration: inspect evidence and explicitly reconcile its id")
        snapshot = inventory(source)
        if not snapshot["run_ids"]:
            return {"state": "fresh_project", "inventory": snapshot}
        if destination.exists():
            raise ValueError("Destination exists without a receipt; refusing ambiguous authority")
        required = snapshot["bytes"] + 1024 * 1024
        if shutil.disk_usage(root).free < required:
            raise ValueError("Insufficient disk space for a verified copy")
        if not execute:
            return {"state": "preflight_safe", "root": str(root), "destination": ".data/runs",
                    "inventory": snapshot, "required_free_bytes": required}
        migration_id = str(uuid4())
        owned = safe_path(root, f".data/migrations/{migration_id}")
        owned.mkdir(parents=True, exist_ok=False)
        intent = {"schema_version": 1, "id": migration_id, "root": str(root),
                  "destination": ".data/runs", "inventory": snapshot, "created_at": timestamp()}
        publish_json(owned / "intent.json", intent)
        sync_directory(owned.parent)
        stage = safe_path(root, f".data/migrations/{migration_id}/staging/runs")
        stage.mkdir(parents=True, exist_ok=False)
        for relative in snapshot["directories"]:
            safe_path(stage, relative).mkdir(parents=True, exist_ok=False)
        for relative, expected in snapshot["files"].items():
            incoming = safe_path(source, relative)
            contents = incoming.read_bytes()
            if digest(contents) != expected["sha256"] or len(contents) != expected["bytes"]:
                raise ValueError("Source changed while copying")
            outgoing = safe_path(stage, relative)
            outgoing.parent.mkdir(parents=True, exist_ok=True)
            with outgoing.open("xb") as stream:
                stream.write(contents)
                stream.flush()
                os.fsync(stream.fileno())
        if inventory(stage) != snapshot or inventory(source) != snapshot:
            raise ValueError("Verification failed before publication")
        for relative in reversed(snapshot["directories"]):
            sync_directory(safe_path(stage, relative))
        sync_directory(stage)
        # Paths were fully traversed/read above; both are explicit owned paths on the same filesystem.
        publish_directory(stage, destination)
        return _finish(root, intent)
    finally:
        lock.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--execute", action="store_true")
    action.add_argument("--dry-run", "--preflight", action="store_true",
                        help="Read-only preflight (also the default)")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--reconcile", help="Explicitly finalize a verified published intent UUID")
    args = parser.parse_args(argv)
    try:
        result = migrate(args.project_root, execute=args.execute, offline=args.offline,
                         reconcile=args.reconcile)
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f"Migration stopped: {type(exc).__name__}: {exc}\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

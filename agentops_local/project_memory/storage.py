from __future__ import annotations

import hashlib
import os
import re
import uuid
from pathlib import Path


_SAFE_SUFFIX = re.compile(r"[^a-z0-9.]", re.IGNORECASE)


class MaterialStorageConflict(ValueError):
    def __init__(self, received_bytes: int):
        self.received_bytes = received_bytes
        super().__init__(f"chunk offset does not match received bytes ({received_bytes})")


def storage_root() -> Path:
    root = Path(os.environ.get("MATERIAL_UPLOAD_STORAGE_DIR", "/var/lib/agentops/material-uploads"))
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def build_storage_key(
    *,
    project_id: uuid.UUID,
    intake_id: uuid.UUID,
    file_id: uuid.UUID,
    filename: str,
) -> str:
    suffix = _SAFE_SUFFIX.sub("", Path(filename).suffix.lower())[:16]
    return f"{project_id}/{intake_id}/{file_id}{suffix}"


def resolve_storage_key(storage_key: str) -> Path:
    relative = Path(storage_key)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("invalid material storage key")
    root = storage_root()
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise ValueError("material storage key escapes storage root") from error
    return path


def append_chunk(storage_key: str, *, offset: int, chunk: bytes) -> int:
    if offset < 0:
        raise ValueError("chunk offset cannot be negative")
    if not chunk:
        return file_size(storage_key)
    path = resolve_storage_key(storage_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    current_size = path.stat().st_size if path.exists() else 0

    if offset < current_size:
        if offset + len(chunk) <= current_size:
            with path.open("rb") as handle:
                handle.seek(offset)
                if handle.read(len(chunk)) == chunk:
                    return current_size
        raise MaterialStorageConflict(current_size)
    if offset != current_size:
        raise MaterialStorageConflict(current_size)

    with path.open("ab") as handle:
        handle.write(chunk)
        handle.flush()
        os.fsync(handle.fileno())
    return current_size + len(chunk)


def file_size(storage_key: str) -> int:
    path = resolve_storage_key(storage_key)
    return path.stat().st_size if path.exists() else 0


def sha256_file(storage_key: str) -> str:
    digest = hashlib.sha256()
    with resolve_storage_key(storage_key).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_bytes(storage_key: str) -> bytes:
    return resolve_storage_key(storage_key).read_bytes()


def delete_storage_key(storage_key: str) -> None:
    resolve_storage_key(storage_key).unlink(missing_ok=True)

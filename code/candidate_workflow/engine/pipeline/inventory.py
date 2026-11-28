"""Read-only source discovery and reproducible inventory generation."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pypdf
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from pipeline.models import SourceRecord


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Return the SHA-256 digest of *path* without changing its metadata."""

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _assert_below_root(path: Path, root: Path) -> Path:
    resolved = path.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"source path escapes project root: {path}") from exc
    return resolved


def _pdf_page_count(path: Path) -> int | None:
    try:
        return len(PdfReader(path).pages)
    except (PdfReadError, ValueError, OSError):
        return None


def inventory_sources(
    root: Path,
    source_dirs: dict[str, Path],
) -> list[SourceRecord]:
    """Inventory files below configured source directories without mutation."""

    root = root.resolve(strict=True)
    records: list[SourceRecord] = []
    for tier, relative_dir in sorted(source_dirs.items()):
        directory = _assert_below_root(root / relative_dir, root)
        if not directory.is_dir():
            raise ValueError(f"source directory is not a directory: {relative_dir}")
        for candidate in sorted(directory.rglob("*"), key=lambda item: item.as_posix()):
            if candidate.is_symlink():
                resolved = _assert_below_root(candidate, root)
                if not resolved.is_file():
                    continue
            elif not candidate.is_file():
                continue
            resolved = _assert_below_root(candidate, root)
            stat = resolved.stat()
            records.append(
                SourceRecord(
                    source_path=candidate.relative_to(root).as_posix(),
                    tier=tier,
                    byte_size=stat.st_size,
                    sha256=sha256_file(resolved),
                    page_count=(
                        _pdf_page_count(resolved)
                        if candidate.suffix.casefold() == ".pdf"
                        else None
                    ),
                    parser_version=f"pypdf-{pypdf.__version__}",
                )
            )
    return sorted(records, key=lambda record: record.source_path)


def write_inventory(records: list[SourceRecord], output: Path) -> None:
    """Write a stable JSON inventory using atomic replacement."""

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    payload = [record.model_dump(mode="json") for record in records]
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    try:
        with temporary.open("wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)

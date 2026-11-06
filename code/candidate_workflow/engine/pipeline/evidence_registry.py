"""Queue-scoped registry for validated literature evidence caches."""

from __future__ import annotations

import json
import os
import tempfile
from hashlib import sha256
from pathlib import Path

from pydantic import BaseModel, ConfigDict


class EvidenceRegistryError(RuntimeError):
    """Raised when corpus scope and validated caches disagree."""


class EvidenceRegistryRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_path: str
    sha256: str
    tier: str
    validated_path: str
    cache_key: str
    evidence_item_count: int
    contradiction_count: int
    visual_review_page_count: int


class EvidenceRegistrySummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    queue_digest: str
    queue_paper_count: int
    scoped_record_count: int
    evidence_item_count: int
    contradiction_count: int
    visual_review_page_count: int
    off_queue_cache_count: int
    missing_source_paths: tuple[str, ...]
    records: tuple[EvidenceRegistryRecord, ...]


def file_digest(path: Path) -> str:
    """Return a content digest for an immutable evidence artifact."""

    try:
        return sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise EvidenceRegistryError(f"cannot read evidence artifact: {path}") from exc


def _load_object(path: Path) -> dict:
    if not path.is_file():
        raise EvidenceRegistryError(f"required JSON file is missing: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceRegistryError(f"cannot read valid JSON from {path}") from exc
    if not isinstance(value, dict):
        raise EvidenceRegistryError(f"expected a JSON object in {path}")
    return value


def build_evidence_registry(output_root: Path) -> EvidenceRegistrySummary:
    """Build a fail-closed registry scoped to the current full-corpus queue."""

    output_root = output_root.resolve()
    corpus_root = output_root / "derived" / "full_corpus"
    queue = _load_object(corpus_root / "queue.json")
    queue_items = queue.get("items")
    if not isinstance(queue_items, list):
        raise EvidenceRegistryError("queue items must be a list")

    queue_by_path: dict[str, dict] = {}
    for item in queue_items:
        if not isinstance(item, dict) or not isinstance(item.get("source_path"), str):
            raise EvidenceRegistryError("every queue item requires a source_path")
        source_path = item["source_path"]
        if source_path in queue_by_path:
            raise EvidenceRegistryError(f"duplicate source path in queue: {source_path}")
        queue_by_path[source_path] = item

    cache_by_path: dict[str, tuple[Path, dict]] = {}
    off_queue = 0
    for validated_path in sorted((corpus_root / "papers").glob("*/validated.json")):
        payload = _load_object(validated_path)
        extraction = payload.get("extraction")
        if not isinstance(extraction, dict) or not isinstance(extraction.get("source_file"), str):
            raise EvidenceRegistryError(f"validated cache lacks extraction.source_file: {validated_path}")
        source_path = extraction["source_file"]
        if source_path not in queue_by_path:
            off_queue += 1
            continue
        if source_path in cache_by_path:
            raise EvidenceRegistryError(
                f"duplicate validated records for current source: {source_path}"
            )
        cache_by_path[source_path] = (validated_path, payload)

    records: list[EvidenceRegistryRecord] = []
    for source_path, item in sorted(queue_by_path.items()):
        cached = cache_by_path.get(source_path)
        if cached is None:
            continue
        validated_path, payload = cached
        extraction = payload["extraction"]
        expected_sha = item.get("sha256")
        actual_sha = extraction.get("sha256")
        if actual_sha != expected_sha:
            raise EvidenceRegistryError(
                f"SHA-256 mismatch for {source_path}: queue={expected_sha} cache={actual_sha}"
            )
        evidence_items = extraction.get("evidence_items", [])
        contradictions = extraction.get("contradictions", [])
        visual_pages = extraction.get("visual_review_pages", [])
        if not all(isinstance(value, list) for value in (evidence_items, contradictions, visual_pages)):
            raise EvidenceRegistryError(f"invalid extraction collection fields for {source_path}")
        records.append(
            EvidenceRegistryRecord(
                source_path=source_path,
                sha256=str(expected_sha),
                tier=str(item.get("tier", "")),
                validated_path=str(validated_path.relative_to(output_root)),
                cache_key=str(payload.get("cache_key", "")),
                evidence_item_count=len(evidence_items),
                contradiction_count=len(contradictions),
                visual_review_page_count=len(visual_pages),
            )
        )

    missing = tuple(sorted(set(queue_by_path) - set(cache_by_path)))
    return EvidenceRegistrySummary(
        queue_digest=str(queue.get("queue_digest", "")),
        queue_paper_count=len(queue_by_path),
        scoped_record_count=len(records),
        evidence_item_count=sum(record.evidence_item_count for record in records),
        contradiction_count=sum(record.contradiction_count for record in records),
        visual_review_page_count=sum(record.visual_review_page_count for record in records),
        off_queue_cache_count=off_queue,
        missing_source_paths=missing,
        records=tuple(records),
    )


def _atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def write_evidence_registry(output_root: Path) -> Path:
    """Write and return the deterministic local registry path."""

    output_root = output_root.resolve()
    registry = build_evidence_registry(output_root)
    destination = output_root / "derived" / "principles" / "evidence_registry.json"
    _atomic_json(destination, registry.model_dump(mode="json"))
    return destination

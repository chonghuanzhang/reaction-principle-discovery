import json
from pathlib import Path

import pytest

from pipeline.evidence_registry import EvidenceRegistryError, build_evidence_registry


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _validated(source_path: str, sha256: str, evidence_count: int = 1) -> dict:
    return {
        "cache_key": "cache-key",
        "extraction": {
            "source_file": source_path,
            "sha256": sha256,
            "paper_id": source_path,
            "evidence_items": [
                {"evidence_id": f"E{index:03d}"} for index in range(evidence_count)
            ],
            "contradictions": [],
            "visual_review_pages": [],
        },
    }


def test_registry_excludes_off_queue_caches(tmp_path):
    sha_a = "a" * 64
    sha_b = "b" * 64
    sha_old = "c" * 64
    _write_json(
        tmp_path / "derived/full_corpus/queue.json",
        {
            "queue_digest": "queue-1",
            "items": [
                {"source_path": "papers/a.pdf", "sha256": sha_a, "tier": "tier_1"},
                {"source_path": "papers/b.pdf", "sha256": sha_b, "tier": "tier_2"},
            ],
        },
    )
    papers = tmp_path / "derived/full_corpus/papers"
    _write_json(papers / "tier_1-a/validated.json", _validated("papers/a.pdf", sha_a, 2))
    _write_json(papers / "tier_2-b/validated.json", _validated("papers/b.pdf", sha_b, 3))
    _write_json(papers / "tier_4-old/validated.json", _validated("papers/old.pdf", sha_old, 7))

    registry = build_evidence_registry(tmp_path)

    assert registry.queue_paper_count == 2
    assert registry.scoped_record_count == 2
    assert registry.evidence_item_count == 5
    assert registry.off_queue_cache_count == 1
    assert [record.source_path for record in registry.records] == [
        "papers/a.pdf",
        "papers/b.pdf",
    ]


def test_registry_fails_closed_on_sha_mismatch(tmp_path):
    _write_json(
        tmp_path / "derived/full_corpus/queue.json",
        {
            "queue_digest": "queue-1",
            "items": [
                {"source_path": "papers/a.pdf", "sha256": "a" * 64, "tier": "tier_1"}
            ],
        },
    )
    _write_json(
        tmp_path / "derived/full_corpus/papers/tier_1-a/validated.json",
        _validated("papers/a.pdf", "b" * 64),
    )

    with pytest.raises(EvidenceRegistryError, match="SHA-256 mismatch"):
        build_evidence_registry(tmp_path)


def test_registry_fails_closed_on_duplicate_source_records(tmp_path):
    sha = "a" * 64
    _write_json(
        tmp_path / "derived/full_corpus/queue.json",
        {
            "queue_digest": "queue-1",
            "items": [
                {"source_path": "papers/a.pdf", "sha256": sha, "tier": "tier_1"}
            ],
        },
    )
    papers = tmp_path / "derived/full_corpus/papers"
    _write_json(papers / "tier_1-a/validated.json", _validated("papers/a.pdf", sha))
    _write_json(papers / "tier_1-copy/validated.json", _validated("papers/a.pdf", sha))

    with pytest.raises(EvidenceRegistryError, match="duplicate validated records"):
        build_evidence_registry(tmp_path)

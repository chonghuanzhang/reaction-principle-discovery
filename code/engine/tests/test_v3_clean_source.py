from __future__ import annotations

from pipeline.leakage_audit import LeakagePolicy
from pipeline.v3_clean_source import (
    bind_seed_evidence_references,
    contains_sealed_content,
    filter_transfer_rows,
    sanitize_seed_document,
)


def _policy() -> LeakagePolicy:
    return LeakagePolicy(policy_id="synthetic-clean-source", sealed_terms=("SEALED_TERM",))


def test_contains_sealed_content_uses_the_leakage_scanner() -> None:
    assert contains_sealed_content({"claim": "contains SEALED_TERM"}, _policy())
    assert not contains_sealed_content({"claim": "clean mechanism"}, _policy())


def test_seed_sanitizer_drops_contaminated_list_items_and_redacts_scalar() -> None:
    sanitized = sanitize_seed_document(
        {
            "claim": "SEALED_TERM disclosed answer",
            "reaction_center": ["clean center", "SEALED_TERM center"],
            "evidence_ids": ["SE-001"],
        },
        _policy(),
    )

    assert sanitized == {
        "claim": "withheld by pre-reveal leakage policy",
        "reaction_center": ["clean center"],
        "evidence_ids": ["SE-001"],
    }


def test_seed_reference_binding_removes_dropped_evidence_ids() -> None:
    mechanism, principle = bind_seed_evidence_references(
        {"evidence_ids": ["SE-001", "SE-002"]},
        {"supporting_seed_evidence": ["SE-001", "SE-002"]},
        {"SE-002"},
    )

    assert mechanism["evidence_ids"] == ["SE-002"]
    assert principle["supporting_seed_evidence"] == ["SE-002"]


def test_transfer_filter_rejects_rows_with_dropped_seed_references() -> None:
    rows = [
        {"source_paper_id": "P1", "seed_feature_ids": ["SE-001"]},
        {"source_paper_id": "P1", "seed_feature_ids": ["SE-002"]},
    ]

    retained = filter_transfer_rows(rows, {"P1"}, {"SE-002"}, _policy())

    assert retained == (rows[1],)

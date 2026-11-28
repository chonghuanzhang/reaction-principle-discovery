import json
from pathlib import Path

import pytest

from pipeline.paper_mechanism_bundles import (
    PaperMechanismBundleError,
    load_paper_mechanism_bundles,
    write_source_revisit_registry,
)


def _normalization(source_path: str, sha: str) -> dict:
    return {
        "cache_key": f"cache-{sha[:12]}",
        "source_file": source_path,
        "source_sha256": sha,
        "normalization": {
            "mechanism_evidence": [
                {
                    "mechanism_evidence_id": "ME001",
                    "source_paper_id": "chunk-001",
                    "source_evidence_ids": ["E001"],
                    "evidence_type": "elementary_step",
                    "elementary_step": "nucleophilic trapping",
                    "starting_state": "electrophile plus nucleophile",
                    "ending_state": "trapped product",
                    "bond_changes": ["form C-Nu"],
                    "catalyst_role": "palladium activation",
                    "nucleophile_requirements": ["soft nucleophile"],
                    "electrophile_requirements": ["activated C-F center"],
                    "condition_requirements": ["moderate base"],
                    "observed_outcome": "defluorinative trapping",
                    "failure_mode": None,
                    "evidence_label": "LITERATURE FACT",
                    "evidence_strength": "direct",
                    "quotation": "The nucleophile trapped the activated substrate.",
                    "pdf_page": 2,
                    "confidence": "high",
                }
            ],
            "boundary_constraints": [
                {
                    "constraint_id": "BC001",
                    "dimension": "electronic",
                    "applies_to": ["activated C-F center"],
                    "direction": "incompatible",
                    "statement": "An unactivated center does not react.",
                    "quantitative_range": None,
                    "supporting_evidence_ids": ["E001"],
                    "contradictory_evidence_ids": [],
                    "confidence": "high",
                }
            ],
            "source_revisit_requests": [
                {
                    "request_id": "SR001",
                    "source_paper_id": "chunk-001",
                    "pdf_pages": [2],
                    "reason": "critical_visual",
                    "question": "Confirm the depicted intermediate.",
                    "status": "pending",
                }
            ],
        },
        "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
    }


def _write_fixture(root: Path) -> None:
    records = []
    for index, source_path in enumerate(("papers/one.pdf", "papers/two.pdf"), start=1):
        sha = str(index) * 64
        records.append(
            {
                "source_path": source_path,
                "sha256": sha,
                "tier": "tier_1",
                "validated_path": f"derived/full_corpus/papers/{sha[:12]}/validated.json",
                "cache_key": f"literature-{index}",
                "evidence_item_count": 1,
                "contradiction_count": 0,
                "visual_review_page_count": 0,
            }
        )
        target = root / "derived/principles/normalization" / sha[:12] / "validated.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(_normalization(source_path, sha)), encoding="utf-8")
    registry = root / "derived/principles/evidence_registry.json"
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text(
        json.dumps(
            {
                "queue_digest": "d" * 64,
                "queue_paper_count": 2,
                "scoped_record_count": 2,
                "evidence_item_count": 2,
                "contradiction_count": 0,
                "visual_review_page_count": 0,
                "off_queue_cache_count": 1,
                "missing_source_paths": [],
                "records": records,
            }
        ),
        encoding="utf-8",
    )
    off_queue = root / "derived/principles/normalization" / ("9" * 12) / "validated.json"
    off_queue.parent.mkdir(parents=True)
    off_queue.write_text(
        json.dumps(_normalization("papers/excluded.pdf", "9" * 64)), encoding="utf-8"
    )


def test_paper_bundles_namespace_local_ids_and_ignore_off_queue_cache(tmp_path):
    _write_fixture(tmp_path)

    bundles = load_paper_mechanism_bundles(tmp_path)

    assert len(bundles) == 2
    assert {bundle.source_path for bundle in bundles} == {"papers/one.pdf", "papers/two.pdf"}
    mechanism_ids = {bundle.mechanisms[0].mechanism_evidence_id for bundle in bundles}
    constraint_ids = {bundle.constraints[0].constraint_id for bundle in bundles}
    revisit_ids = {bundle.revisits[0].request_id for bundle in bundles}
    assert mechanism_ids == {f"{'1' * 12}::ME001", f"{'2' * 12}::ME001"}
    assert constraint_ids == {f"{'1' * 12}::BC001", f"{'2' * 12}::BC001"}
    assert revisit_ids == {f"{'1' * 12}::SR001", f"{'2' * 12}::SR001"}
    for bundle in bundles:
        assert bundle.mechanisms[0].source_paper_id == bundle.source_path
        assert bundle.constraints[0].constraint_id.startswith(bundle.namespace + "::")
        assert bundle.constraints[0].supporting_evidence_ids == (
            f"{bundle.namespace}::E001",
        )


def test_revisit_registry_preserves_same_local_id_from_different_papers(tmp_path):
    _write_fixture(tmp_path)
    bundles = load_paper_mechanism_bundles(tmp_path)

    destination = write_source_revisit_registry(tmp_path, bundles)
    payload = json.loads(destination.read_text(encoding="utf-8"))

    assert payload["revisit_count"] == 2
    assert len(payload["revisits"]) == 2
    assert len({row["request_id"] for row in payload["revisits"]}) == 2


def test_bundle_loader_fails_when_normalization_source_does_not_match_registry(tmp_path):
    _write_fixture(tmp_path)
    path = tmp_path / "derived/principles/normalization" / ("1" * 12) / "validated.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["source_file"] = "papers/wrong.pdf"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(PaperMechanismBundleError, match="source path mismatch"):
        load_paper_mechanism_bundles(tmp_path)

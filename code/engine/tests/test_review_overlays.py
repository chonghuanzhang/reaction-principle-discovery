import json
from pathlib import Path


PILOT_ROOT = Path("derived/pilot")
ALLOWED_DECISIONS = {"accepted", "revised", "rejected", "not_assessable"}


def test_review_overlays_cover_every_validated_evidence_item() -> None:
    paper_directories = sorted(path.parent for path in PILOT_ROOT.glob("tier_*/validated.json"))
    assert len(paper_directories) == 4

    for paper_directory in paper_directories:
        validated = json.loads((paper_directory / "validated.json").read_text(encoding="utf-8"))
        review = json.loads((paper_directory / "human_review.json").read_text(encoding="utf-8"))
        evidence_ids = {
            item["evidence_id"] for item in validated["extraction"]["evidence_items"]
        }
        decisions = review["evidence_decisions"]

        assert review["human_signoff_required"] is True
        assert review["source_sha256"] == validated["extraction"]["sha256"]
        assert {item["evidence_id"] for item in decisions} == evidence_ids
        assert len(decisions) == len(evidence_ids)
        assert all(item["decision"] in ALLOWED_DECISIONS for item in decisions)
        assert all(item["rationale"].strip() for item in decisions)


def test_tier_2_scale_up_discrepancy_is_preserved_as_a_revision() -> None:
    review_path = PILOT_ROOT / "tier_2-8635b71801a5" / "human_review.json"
    review = json.loads(review_path.read_text(encoding="utf-8"))
    decision = next(
        item for item in review["evidence_decisions"] if item["evidence_id"] == "E09"
    )

    assert decision["decision"] == "revised"
    assert "92% ee" in decision["revised_claim"]
    assert "91% ee" in decision["revised_claim"]

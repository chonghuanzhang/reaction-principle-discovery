"""Versioned source merging must not re-enumerate historical chemistry."""
import importlib.util
from pathlib import Path

BUILDER = Path(__file__).resolve().parents[2] / "literature/merge_catalog.py"


def merger():
    assert BUILDER.exists(), "Versioned evidence builder is missing"
    spec = importlib.util.spec_from_file_location("evidence_update_builder", BUILDER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.merge_catalog


def original():
    return [{"si_id": "L001", "catalog_id": "L001", "source_id": "historical",
             "doi": "10.0000/existing", "tier_number": 2, "tier": "tier_2",
             "evidence_record_count": 2, "historical_evidence_count": 2,
             "later_evidence_count": 0, "title": "Original source"}]


def review(**updates):
    record = {"catalog_id": "L001", "doi": "10.0000/existing", "title": "Original source",
              "metadata_status": "verified", "primary_tier": 2, "secondary_tiers": [4],
              "source_access": "primary_full_text", "full_reference": "Test source.",
              "review_summary": "Current applicability review.", "evidence": []}
    record.update(updates)
    return record


def test_existing_doi_is_enriched_without_replacing_history():
    old = original()
    out = merger()(old, [review()])
    assert len(out) == 1
    assert out[0]["source_id"] == "historical"
    assert out[0]["historical_evidence_count"] == 2
    assert old[0].get("current_review") is None


def test_new_record_appends_and_metadata_only_has_no_chemical_evidence():
    out = merger()(original(), [review(catalog_id="L002", doi="10.0000/new",
                                      source_access="metadata_only", primary_tier=4)])
    assert [x["si_id"] for x in out] == ["L001", "L002"]
    assert out[1]["evidence_record_count"] == 0
    assert out[1]["contribution_kind"] == "bibliographic_topic_only"


def test_existing_doi_with_new_identifier_is_rejected():
    try:
        merger()(original(), [review(catalog_id="L002")])
    except ValueError as exc:
        assert "existing DOI" in str(exc)
    else:
        raise AssertionError("Duplicate source accepted under a new identifier")


def test_unverified_metadata_is_rejected():
    try:
        merger()(original(), [review(metadata_status="unverified")])
    except ValueError as exc:
        assert "metadata" in str(exc)
    else:
        raise AssertionError("Unverified source admitted")

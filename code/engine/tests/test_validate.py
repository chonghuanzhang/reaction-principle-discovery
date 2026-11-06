import json
from copy import deepcopy
from pathlib import Path

from pipeline.models import PageRecord, SourceRecord
from pipeline.validate import validate_extraction


SCHEMA_PATH = Path("config/extraction_schema.json")


def source() -> SourceRecord:
    return SourceRecord(
        source_path="Tier1/paper.pdf",
        tier="tier_1",
        byte_size=100,
        sha256="a" * 64,
        page_count=2,
        parser_version="pypdf-test",
    )


def pages() -> list[PageRecord]:
    return [
        PageRecord(
            pdf_page=1,
            text="The reaction afforded the product in 82% yield.",
            character_count=48,
            replacement_character_count=0,
        ),
        PageRecord(
            pdf_page=2,
            text="A radical pathway may be involved.",
            character_count=34,
            replacement_character_count=0,
        ),
    ]


def valid_record() -> dict:
    return {
        "paper_id": "tier1-paper-a",
        "source_file": "Tier1/paper.pdf",
        "sha256": "a" * 64,
        "bibliography": {
            "title": "Test reaction",
            "authors": ["A. Author"],
            "journal": "Test Journal",
            "year": 2024,
            "doi": None,
        },
        "primary_tier": "tier_1",
        "secondary_tiers": [],
        "evidence_types": ["direct_positive_evidence"],
        "reaction_summary": {
            "reaction_class": "Selective defluorinative coupling",
            "electrophile": "UNKNOWN",
            "nucleophile_or_partner": "UNKNOWN",
            "nu_atom": "UNKNOWN",
            "nu_subclass": "UNKNOWN",
            "new_bond": "UNKNOWN",
            "catalyst": "UNKNOWN",
            "ligand": "UNKNOWN",
            "base": "UNKNOWN",
            "solvent": "UNKNOWN",
            "temperature": "UNKNOWN",
            "product_type": "UNKNOWN",
            "selectivity": "UNKNOWN",
            "proposed_intermediate": "UNKNOWN",
            "activation_mode": "UNKNOWN",
            "successful_scope": [],
            "failed_scope": [],
            "side_reactions": [],
            "relevance_to_seed_reaction": "Direct evidence candidate.",
            "transferability_assessment": "UNKNOWN",
        },
        "evidence_items": [
            {
                "evidence_id": "E1",
                "claim": "The reported yield was 82%.",
                "evidence_label": "LITERATURE FACT",
                "quotation": "The reaction afforded the product in 82% yield.",
                "source_span_ids": ["P001-S001"],
                "pdf_page": 1,
                "additional_pdf_pages": [],
                "section_context": "Results",
                "attribution": "author_observation",
                "evidence_strength": "direct",
                "visual_review_reference": None,
                "reviewer_status": "pending",
            }
        ],
        "uncertainties": [],
        "contradictions": [],
        "visual_review_pages": [],
        "review_status": "pending",
    }


def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def test_validator_rejects_quote_not_on_cited_page() -> None:
    record = valid_record()
    record["evidence_items"][0]["quotation"] = "Invented quotation."

    report = validate_extraction(record, pages(), source(), schema())

    assert "quotation_not_found" in [error.code for error in report.errors]


def test_validator_rejects_hypothesis_as_fact() -> None:
    record = valid_record()
    record["evidence_items"][0]["attribution"] = "author_hypothesis"

    report = validate_extraction(record, pages(), source(), schema())

    assert "epistemic_label_conflict" in [error.code for error in report.errors]


def test_validator_accepts_normalized_verbatim_quote() -> None:
    record = valid_record()
    record["evidence_items"][0]["quotation"] = (
        "The reaction afforded\n the product in 82% yield."
    )

    report = validate_extraction(record, pages(), source(), schema())

    assert report.is_valid


def test_validator_rejects_wrong_source_checksum_and_page() -> None:
    record = valid_record()
    record["sha256"] = "b" * 64
    record["evidence_items"][0]["pdf_page"] = 3

    report = validate_extraction(record, pages(), source(), schema())

    assert [error.code for error in report.errors] == [
        "source_checksum_mismatch",
        "page_out_of_range",
    ]


def test_validator_accepts_unknown_model_inference_without_source_quote() -> None:
    record = valid_record()
    item = record["evidence_items"][0]
    item.update(
        {
            "evidence_label": "UNKNOWN",
            "attribution": "model_inference",
            "quotation": None,
            "source_span_ids": [],
            "pdf_page": None,
            "evidence_strength": "unknown",
        }
    )

    report = validate_extraction(record, pages(), source(), schema())

    assert report.is_valid


def test_validator_rejects_more_than_twelve_evidence_items() -> None:
    record = valid_record()
    template = record["evidence_items"][0]
    record["evidence_items"] = []
    for index in range(13):
        item = deepcopy(template)
        item["evidence_id"] = f"E{index + 1:03d}"
        record["evidence_items"].append(item)

    report = validate_extraction(record, pages(), source(), schema())

    assert [error.code for error in report.errors] == [
        "evidence_item_limit_exceeded"
    ]

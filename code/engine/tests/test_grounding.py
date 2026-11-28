from pipeline.grounding import build_source_spans, ground_extraction
from pipeline.models import PageRecord
from tests.test_validate import pages, source, valid_record


def test_grounding_replaces_normalized_model_quote_with_exact_source_span() -> None:
    page = PageRecord(
        pdf_page=1,
        text="The triﬂuoropropanamide afforded product in 82% yield.",
        character_count=54,
        replacement_character_count=0,
    )
    spans = build_source_spans([page])
    record = valid_record()
    record["evidence_items"][0]["claim"] = "The product formed in 82% yield."
    record["evidence_items"][0]["quotation"] = (
        "The trifluoropropanamide afforded product in 82% yield."
    )
    record["evidence_items"][0]["source_span_ids"] = [spans[0].span_id]

    grounded, changes = ground_extraction(record, spans)

    assert grounded["evidence_items"][0]["quotation"] == (
        "The triﬂuoropropanamide afforded product in 82% yield."
    )
    assert changes[0]["evidence_id"] == "E1"
    assert changes[0]["reason"] == "materialized_from_source_spans"


def test_grounding_rejects_unknown_span_id() -> None:
    page = PageRecord(
        pdf_page=1,
        text="Evidence.",
        character_count=9,
        replacement_character_count=0,
    )
    record = valid_record()
    record["evidence_items"][0]["source_span_ids"] = ["P999-S999"]

    try:
        ground_extraction(record, build_source_spans([page]))
    except ValueError as exc:
        assert "unknown source span" in str(exc)
    else:
        raise AssertionError("unknown source span was accepted")


def test_external_author_observation_is_relabelled_as_literature_fact() -> None:
    page = PageRecord(
        pdf_page=1,
        text="The reaction afforded the product in 82% yield.",
        character_count=48,
        replacement_character_count=0,
    )
    spans = build_source_spans([page])
    record = valid_record()
    record["evidence_items"][0]["evidence_label"] = "EXPERIMENTAL FACT"
    record["evidence_items"][0]["source_span_ids"] = [spans[0].span_id]

    grounded, changes = ground_extraction(record, spans)

    assert grounded["evidence_items"][0]["evidence_label"] == "LITERATURE FACT"
    assert any(change["reason"] == "external_observation_relabelled" for change in changes)


def test_grounding_corrects_pdf_page_from_single_page_source_spans() -> None:
    page = PageRecord(
        pdf_page=2,
        text="The measured rate constant was reproducible.",
        character_count=44,
        replacement_character_count=0,
    )
    spans = build_source_spans([page])
    record = valid_record()
    item = record["evidence_items"][0]
    item["source_span_ids"] = [spans[0].span_id]
    item["pdf_page"] = 1

    grounded, changes = ground_extraction(record, spans)

    assert grounded["evidence_items"][0]["pdf_page"] == 2
    assert any(change["reason"] == "page_materialized_from_source_spans" for change in changes)


def test_grounding_materializes_additional_pages_for_cross_page_evidence() -> None:
    pages = [
        PageRecord(
            pdf_page=3,
            text="The authors estimated 73 electrophilicity values.",
            character_count=50,
            replacement_character_count=0,
        ),
        PageRecord(
            pdf_page=5,
            text="The estimated precision was plus or minus two E units.",
            character_count=55,
            replacement_character_count=0,
        ),
    ]
    spans = build_source_spans(pages)
    record = valid_record()
    item = record["evidence_items"][0]
    item["source_span_ids"] = [span.span_id for span in spans]
    item["pdf_page"] = 3

    grounded, changes = ground_extraction(record, spans)

    item = grounded["evidence_items"][0]
    assert item["pdf_page"] == 3
    assert item["additional_pdf_pages"] == [5]
    assert any(change["reason"] == "pages_materialized_from_source_spans" for change in changes)


def test_grounding_materializes_authoritative_inventory_metadata() -> None:
    record = valid_record()
    record["source_file"] = "Tier1/model-completed-title.pdf"
    record["sha256"] = "b" * 64
    record["primary_tier"] = "tier_4"

    grounded, changes = ground_extraction(
        record, build_source_spans(pages()), source=source()
    )

    assert grounded["source_file"] == "Tier1/paper.pdf"
    assert grounded["sha256"] == "a" * 64
    assert grounded["primary_tier"] == "tier_1"
    assert record["source_file"] == "Tier1/model-completed-title.pdf"
    assert {change["reason"] for change in changes} == {
        "source_file_materialized_from_inventory",
        "sha256_materialized_from_inventory",
        "primary_tier_materialized_from_inventory",
    }

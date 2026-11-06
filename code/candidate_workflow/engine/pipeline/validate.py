"""Local structural and source-grounding validation."""

from __future__ import annotations

from pydantic import ValidationError

from pipeline.grounding import build_source_spans
from pipeline.models import (
    ExtractionRecord,
    PageRecord,
    SourceRecord,
    ValidationIssue,
    ValidationReport,
)
from pipeline.pdf_extract import normalize_quote


def validate_extraction(
    record: dict,
    pages: list[PageRecord],
    source: SourceRecord,
    schema: dict,
) -> ValidationReport:
    """Validate one extraction against its typed schema and cited PDF pages."""

    del schema  # The Pydantic contract is the executable form of the versioned schema.
    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []
    evidence_items = record.get("evidence_items")
    if isinstance(evidence_items, list) and len(evidence_items) > 12:
        return ValidationReport(
            is_valid=False,
            errors=(
                ValidationIssue(
                    code="evidence_item_limit_exceeded",
                    message="Validated literature records may contain at most 12 evidence items.",
                ),
            ),
            warnings=(),
        )
    try:
        parsed = ExtractionRecord.model_validate(record)
    except ValidationError as exc:
        return ValidationReport(
            is_valid=False,
            errors=(
                ValidationIssue(code="schema_validation", message=str(exc)),
            ),
            warnings=(),
        )

    if parsed.source_file != source.source_path:
        errors.append(
            ValidationIssue(
                code="source_path_mismatch",
                message="Extraction source_file does not match the inventoried source path.",
            )
        )
    if parsed.sha256 != source.sha256:
        errors.append(
            ValidationIssue(
                code="source_checksum_mismatch",
                message="Extraction checksum does not match the inventoried source.",
            )
        )
    page_by_number = {page.pdf_page: page for page in pages}
    span_by_id = {span.span_id: span for span in build_source_spans(pages)}
    for item in parsed.evidence_items:
        if item.pdf_page is not None and item.pdf_page not in page_by_number:
            errors.append(
                ValidationIssue(
                    code="page_out_of_range",
                    message=f"Cited PDF page {item.pdf_page} is unavailable.",
                    evidence_id=item.evidence_id,
                )
            )
            continue
        for additional_page in item.additional_pdf_pages:
            if additional_page not in page_by_number:
                errors.append(
                    ValidationIssue(
                        code="page_out_of_range",
                        message=f"Additional cited PDF page {additional_page} is unavailable.",
                        evidence_id=item.evidence_id,
                    )
                )
        if item.source_span_ids:
            cited_spans = [span_by_id.get(span_id) for span_id in item.source_span_ids]
            if any(span is None for span in cited_spans):
                errors.append(
                    ValidationIssue(
                        code="unknown_source_span",
                        message="Evidence cites a source span that is unavailable.",
                        evidence_id=item.evidence_id,
                    )
                )
            elif {span.pdf_page for span in cited_spans if span} != {
                item.pdf_page,
                *item.additional_pdf_pages,
            }:
                errors.append(
                    ValidationIssue(
                        code="source_span_page_mismatch",
                        message="Evidence source spans do not belong to the cited PDF page.",
                        evidence_id=item.evidence_id,
                    )
                )
            else:
                materialized = "\n".join(span.text for span in cited_spans if span)
                if normalize_quote(item.quotation or "") != normalize_quote(materialized):
                    errors.append(
                        ValidationIssue(
                            code="quotation_not_found",
                            message="Quotation does not equal its deterministic source spans.",
                            evidence_id=item.evidence_id,
                        )
                    )
        elif item.quotation is not None and item.pdf_page is not None:
            page_text = normalize_quote(page_by_number[item.pdf_page].text)
            quotation = normalize_quote(item.quotation)
            if quotation not in page_text:
                errors.append(
                    ValidationIssue(
                        code="quotation_not_found",
                        message="Normalized quotation is absent from the cited PDF page.",
                        evidence_id=item.evidence_id,
                    )
                )
        if item.attribution == "author_hypothesis" and item.evidence_label != "AUTHOR HYPOTHESIS":
            errors.append(
                ValidationIssue(
                    code="epistemic_label_conflict",
                    message="Author hypotheses must use AUTHOR HYPOTHESIS.",
                    evidence_id=item.evidence_id,
                )
            )
        if item.attribution == "model_inference" and item.evidence_label not in {
            "MODEL INFERENCE",
            "UNKNOWN",
        }:
            errors.append(
                ValidationIssue(
                    code="epistemic_label_conflict",
                    message="Model inferences must use MODEL INFERENCE.",
                    evidence_id=item.evidence_id,
                )
            )
        needs_source_evidence = item.evidence_label in {
            "LITERATURE FACT",
            "AUTHOR HYPOTHESIS",
        }
        if needs_source_evidence and not (
            (
                item.quotation is not None
                and item.pdf_page is not None
                and bool(item.source_span_ids)
            )
            or item.visual_review_reference is not None
        ):
            errors.append(
                ValidationIssue(
                    code="missing_source_evidence",
                    message="Literature claims require a page quotation or visual reference.",
                    evidence_id=item.evidence_id,
                )
            )
    return ValidationReport(
        is_valid=not errors,
        errors=tuple(errors),
        warnings=tuple(warnings),
    )

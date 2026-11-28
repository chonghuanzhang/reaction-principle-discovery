"""Human-readable English review records for model extractions."""

from __future__ import annotations

import os
from pathlib import Path

from pipeline.models import ExtractionRecord, ValidationReport


def _atomic_write_text(output: Path, text: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


def write_review_markdown(
    raw: dict,
    validation: ValidationReport,
    output: Path,
) -> None:
    """Write an auditable review form without changing the raw extraction."""

    record = ExtractionRecord.model_validate(raw)
    lines = [
        f"# Pilot Review: {record.bibliography.title}",
        "",
        f"Source file: {record.source_file}",
        f"SHA-256: {record.sha256}",
        f"Primary Tier: {record.primary_tier}",
        f"Validation status: {'PASSED' if validation.is_valid else 'FAILED'}",
        "Reviewer status: pending",
        "",
        "## Validation Findings",
        "",
    ]
    if not validation.errors and not validation.warnings:
        lines.append("No local validation findings.")
    for issue in validation.errors:
        lines.append(f"- ERROR `{issue.code}`: {issue.message}")
    for issue in validation.warnings:
        lines.append(f"- WARNING `{issue.code}`: {issue.message}")
    lines.extend(["", "## Reaction Summary", ""])
    for field, value in record.reaction_summary.model_dump().items():
        label = field.replace("_", " ").capitalize()
        lines.append(f"- {label}: {value}")
    for index, item in enumerate(record.evidence_items, start=1):
        lines.extend(
            [
                "",
                f"## Evidence Item {index}",
                "",
                f"Evidence ID: {item.evidence_id}",
                f"Claim: {item.claim}",
                f"Evidence label: {item.evidence_label}",
                f"Attribution: {item.attribution}",
                f"Evidence strength: {item.evidence_strength}",
                f"PDF page: {item.pdf_page if item.pdf_page is not None else 'not cited'}",
                f"Additional PDF pages: {', '.join(str(page) for page in item.additional_pdf_pages) or 'none'}",
                f"Section context: {item.section_context}",
                f"Quotation: {item.quotation if item.quotation is not None else 'not provided'}",
                f"Source spans: {', '.join(item.source_span_ids) or 'none'}",
                f"Visual review reference: {item.visual_review_reference or 'none'}",
                f"Reviewer decision: {item.reviewer_status}",
                "Reviewer rationale:",
            ]
        )
    lines.extend(
        [
            "",
            "## Visual Review Pages",
            "",
            ", ".join(str(page) for page in record.visual_review_pages) or "None requested.",
            "",
            "## Uncertainties",
            "",
            *(f"- {item}" for item in record.uncertainties),
            "",
            "## Contradictions",
            "",
            *(f"- {item}" for item in record.contradictions),
            "",
        ]
    )
    _atomic_write_text(output, "\n".join(lines))

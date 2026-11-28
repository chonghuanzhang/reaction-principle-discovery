"""Deterministic source spans and evidence quotation materialization."""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass

from pipeline.models import PageRecord, SourceRecord
from pipeline.pdf_extract import normalize_quote


@dataclass(frozen=True)
class SourceSpan:
    span_id: str
    pdf_page: int
    text: str


def _bounded_sentences(text: str, maximum: int = 800) -> list[str]:
    sentences = [
        part.strip()
        for part in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9(αβγ])", text)
        if part.strip()
    ]
    bounded: list[str] = []
    for sentence in sentences:
        remaining = sentence
        while len(remaining) > maximum:
            boundary = remaining.rfind(" ", 0, maximum + 1)
            if boundary < 1:
                boundary = maximum
            bounded.append(remaining[:boundary])
            remaining = remaining[boundary:].lstrip()
        if remaining:
            bounded.append(remaining)
    return bounded


def build_source_spans(pages: list[PageRecord]) -> list[SourceSpan]:
    """Create stable page-local span identifiers over whitespace-normalized text."""

    spans: list[SourceSpan] = []
    for page in pages:
        normalized = normalize_quote(page.text)
        for index, text in enumerate(_bounded_sentences(normalized), start=1):
            spans.append(
                SourceSpan(
                    span_id=f"P{page.pdf_page:03d}-S{index:03d}",
                    pdf_page=page.pdf_page,
                    text=text,
                )
            )
    return spans


def ground_extraction(
    record: dict,
    spans: list[SourceSpan],
    source: SourceRecord | None = None,
) -> tuple[dict, list[dict[str, str]]]:
    """Materialize quotations from cited spans while preserving raw output elsewhere."""

    span_by_id = {span.span_id: span for span in spans}
    grounded = copy.deepcopy(record)
    changes: list[dict[str, str]] = []
    if source is not None:
        authoritative_metadata = {
            "source_file": source.source_path,
            "sha256": source.sha256,
            "primary_tier": source.tier,
        }
        for field, value in authoritative_metadata.items():
            if grounded.get(field) != value:
                grounded[field] = value
                changes.append(
                    {
                        "evidence_id": "",
                        "reason": f"{field}_materialized_from_inventory",
                    }
                )
    for item in grounded.get("evidence_items", []):
        item.setdefault("additional_pdf_pages", [])
        if (
            item.get("attribution") in {"author_observation", "source_metadata"}
            and item.get("evidence_label") == "EXPERIMENTAL FACT"
        ):
            item["evidence_label"] = "LITERATURE FACT"
            changes.append(
                {
                    "evidence_id": str(item.get("evidence_id", "")),
                    "reason": "external_observation_relabelled",
                }
            )
        span_ids = item.get("source_span_ids", [])
        if not span_ids:
            continue
        selected: list[SourceSpan] = []
        for span_id in span_ids:
            if span_id not in span_by_id:
                raise ValueError(f"unknown source span: {span_id}")
            selected.append(span_by_id[span_id])
        span_pages = {span.pdf_page for span in selected}
        previous_page = item.get("pdf_page")
        previous_additional = item.get("additional_pdf_pages", [])
        materialized_page = (
            previous_page if previous_page in span_pages else min(span_pages)
        )
        materialized_additional = sorted(span_pages - {materialized_page})
        if previous_page != materialized_page or previous_additional != materialized_additional:
            item["pdf_page"] = materialized_page
            item["additional_pdf_pages"] = materialized_additional
            changes.append(
                {
                    "evidence_id": str(item.get("evidence_id", "")),
                    "reason": (
                        "page_materialized_from_source_spans"
                        if len(span_pages) == 1
                        else "pages_materialized_from_source_spans"
                    ),
                }
            )
        materialized = "\n".join(span.text for span in selected)
        if item.get("quotation") != materialized:
            changes.append(
                {
                    "evidence_id": str(item.get("evidence_id", "")),
                    "reason": "materialized_from_source_spans",
                }
            )
        item["quotation"] = materialized
    return grounded, changes

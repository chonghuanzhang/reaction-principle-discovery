"""Extract PDF text while preserving page-level provenance."""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader

from pipeline.models import PageRecord

VISUAL_MARKERS = ("scheme", "figure", "table", "scope")


def normalize_quote(text: str) -> str:
    """Normalize whitespace without altering punctuation or characters."""

    return " ".join(text.split())


def extract_pages(
    pdf_path: Path,
    *,
    low_text_threshold: int = 80,
    replacement_character_threshold: int = 3,
) -> list[PageRecord]:
    """Return one record per physical PDF page using one-based numbering."""

    reader = PdfReader(pdf_path)
    records: list[PageRecord] = []
    for index, page in enumerate(reader.pages):
        extraction_failed = False
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
            extraction_failed = True
        normalized = normalize_quote(text)
        reasons: list[str] = []
        if extraction_failed:
            reasons.append("text_extraction_error")
        if len(normalized) < low_text_threshold:
            reasons.append("low_text_density")
        replacement_count = text.count("\ufffd")
        if replacement_count >= replacement_character_threshold:
            reasons.append("replacement_characters")
        folded = normalized.casefold()
        if len(normalized) < low_text_threshold and any(
            marker in folded for marker in VISUAL_MARKERS
        ):
            reasons.append("scheme_or_figure_marker")
        records.append(
            PageRecord(
                pdf_page=index + 1,
                text=text,
                character_count=len(normalized),
                replacement_character_count=replacement_count,
                visual_review_reasons=tuple(reasons),
            )
        )
    return records

"""Build bounded, page-addressable evidence extraction inputs."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from pipeline.grounding import build_source_spans
from pipeline.models import PageChunk, PageRecord, SourceRecord


def load_seed_context(path: Path) -> dict[str, object]:
    """Load a frozen seed-reaction mapping used only as project context."""

    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("Seed-reaction context must contain a mapping.")
    return loaded


def build_page_chunks(
    pages: list[PageRecord],
    max_characters: int,
) -> list[PageChunk]:
    """Group complete pages into bounded chunks without splitting a page."""

    if max_characters < 1:
        raise ValueError("max_characters must be positive")
    chunks: list[PageChunk] = []
    current: list[PageRecord] = []
    current_size = 0
    for page in pages:
        page_size = len(page.text)
        if current and current_size + page_size > max_characters:
            chunks.append(
                PageChunk(chunk_id=f"chunk-{len(chunks) + 1:03d}", pages=tuple(current))
            )
            current = []
            current_size = 0
        current.append(page)
        current_size += page_size
    if current:
        chunks.append(
            PageChunk(chunk_id=f"chunk-{len(chunks) + 1:03d}", pages=tuple(current))
        )
    return chunks


def build_extraction_input(
    metadata: SourceRecord,
    chunk: PageChunk,
    prompt_text: str,
    seed_context: dict[str, object] | None = None,
) -> str:
    """Combine the stable extraction contract with explicit source pages."""

    source_metadata = json.dumps(
        {
            "source_file": metadata.source_path,
            "sha256": metadata.sha256,
            "primary_tier": metadata.tier,
            "chunk_id": chunk.chunk_id,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    page_sections = []
    for page in chunk.pages:
        spans = build_source_spans([page])
        span_text = "\n".join(f"[[{span.span_id}]] {span.text}" for span in spans)
        page_sections.append(
            f"<<<PDF_PAGE_{page.pdf_page}>>>\n{span_text}\n<<<END_PDF_PAGE_{page.pdf_page}>>>"
        )
    context_section = ""
    if seed_context is not None:
        context_json = json.dumps(
            seed_context, ensure_ascii=False, indent=2, sort_keys=True
        )
        context_section = (
            "PROJECT_CONTEXT_NOT_SOURCE_EVIDENCE\n"
            "Use this project context only to assess relevance and transferability. "
            "It must not be quoted or cited as literature evidence.\n"
            f"{context_json}\n"
            "END_PROJECT_CONTEXT_NOT_SOURCE_EVIDENCE\n\n"
        )
    return (
        f"{prompt_text.strip()}\n\n"
        f"{context_section}"
        f"SOURCE_METADATA\n{source_metadata}\n\n"
        "SOURCE_TEXT\n"
        + "\n\n".join(page_sections)
        + "\n"
    )

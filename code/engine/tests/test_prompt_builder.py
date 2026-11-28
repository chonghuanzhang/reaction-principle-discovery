from pipeline.models import PageChunk, PageRecord, SourceRecord
from pipeline.prompt_builder import build_extraction_input, build_page_chunks


PROMPT = "Use only the supplied source text. Keep MODEL_INFERENCE explicit."


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
            text="First page evidence.",
            character_count=20,
            replacement_character_count=0,
        ),
        PageRecord(
            pdf_page=2,
            text="Second page evidence.",
            character_count=21,
            replacement_character_count=0,
        ),
    ]


def test_prompt_contains_boundary_and_page_markers() -> None:
    chunk = PageChunk(chunk_id="chunk-001", pages=tuple(pages()))

    text = build_extraction_input(source(), chunk, PROMPT)

    assert "Use only the supplied source text" in text
    assert "<<<PDF_PAGE_1>>>" in text
    assert "<<<PDF_PAGE_2>>>" in text
    assert "[[P001-S001]]" in text
    assert "MODEL_INFERENCE" in text
    assert "a" * 64 in text


def test_page_chunking_never_splits_one_page() -> None:
    records = pages()

    chunks = build_page_chunks(records, max_characters=25)

    assert [[page.pdf_page for page in chunk.pages] for chunk in chunks] == [[1], [2]]


def test_oversized_page_remains_a_single_auditable_chunk() -> None:
    page = PageRecord(
        pdf_page=7,
        text="x" * 200,
        character_count=200,
        replacement_character_count=0,
    )

    chunks = build_page_chunks([page], max_characters=50)

    assert len(chunks) == 1
    assert chunks[0].pages == (page,)

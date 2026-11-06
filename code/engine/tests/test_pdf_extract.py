from pathlib import Path

import pytest

from pipeline.pdf_extract import extract_pages, normalize_quote
from tests.fixtures.make_fixture_pdf import create_fixture_pdf


@pytest.fixture
def fixture_pdf(tmp_path: Path) -> Path:
    return create_fixture_pdf(tmp_path / "fixture.pdf")


def test_extract_pages_preserves_pdf_page_numbers(fixture_pdf: Path) -> None:
    pages = extract_pages(fixture_pdf)

    assert [page.pdf_page for page in pages] == [1, 2]
    assert "Experimental yield was 82%." in pages[0].text


def test_low_text_scheme_page_requires_visual_review(fixture_pdf: Path) -> None:
    page = extract_pages(fixture_pdf)[1]

    assert "low_text_density" in page.visual_review_reasons
    assert "scheme_or_figure_marker" in page.visual_review_reasons


def test_quote_normalization_changes_whitespace_only() -> None:
    assert normalize_quote("C–F\n activation") == "C–F activation"
    assert normalize_quote("C-F activation") != normalize_quote("C–F activation")


def test_malformed_page_is_retained_for_visual_review(tmp_path: Path, monkeypatch) -> None:
    class BrokenPage:
        def extract_text(self):
            raise ValueError("malformed content stream")

    class Reader:
        pages = (BrokenPage(),)

    monkeypatch.setattr("pipeline.pdf_extract.PdfReader", lambda path: Reader())

    pages = extract_pages(tmp_path / "broken.pdf")

    assert pages[0].pdf_page == 1
    assert pages[0].text == ""
    assert "text_extraction_error" in pages[0].visual_review_reasons

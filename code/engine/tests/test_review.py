from pathlib import Path

from pipeline.models import ValidationReport
from pipeline.review import write_review_markdown
from tests.test_validate import valid_record


def test_review_lists_claim_quote_page_label_and_decision(tmp_path: Path) -> None:
    output = tmp_path / "review.md"

    write_review_markdown(
        valid_record(),
        ValidationReport(is_valid=True, errors=(), warnings=()),
        output,
    )

    text = output.read_text(encoding="utf-8")
    assert "## Evidence Item 1" in text
    assert "PDF page: 1" in text
    assert "Evidence label: LITERATURE FACT" in text
    assert "Reviewer decision: pending" in text
    assert "The reaction afforded the product in 82% yield." in text


def test_review_displays_validation_failure_without_hiding_raw_claim(tmp_path: Path) -> None:
    output = tmp_path / "review.md"
    report = ValidationReport(
        is_valid=False,
        errors=(),
        warnings=(),
    )

    write_review_markdown(valid_record(), report, output)

    text = output.read_text(encoding="utf-8")
    assert "Validation status: FAILED" in text
    assert "The reported yield was 82%." in text

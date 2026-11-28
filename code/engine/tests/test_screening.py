from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from pipeline.api_client import ApiResult, ApiUsage
from pipeline.models import PageRecord, SourceRecord
from pipeline.screening import (
    ScreeningDecision,
    build_screening_input,
    deduplicate_sources,
    screen_corpus,
)
from tests.fixtures.make_fixture_pdf import create_fixture_pdf


def _source(path: str, sha256: str, *, tier: str = "tier_1") -> SourceRecord:
    return SourceRecord(
        source_path=path,
        tier=tier,
        byte_size=100,
        sha256=sha256,
        page_count=2,
        parser_version="pypdf-test",
    )


def test_deduplicate_sources_retains_lexically_first_path() -> None:
    shared_sha = "a" * 64
    sources = [
        _source("文献1/N/z-copy.pdf", shared_sha),
        _source("文献1/C/a-original.pdf", shared_sha),
        _source("文献2/unique.pdf", "b" * 64, tier="tier_2"),
    ]

    retained, exclusions = deduplicate_sources(sources)

    assert [source.source_path for source in retained] == [
        "文献1/C/a-original.pdf",
        "文献2/unique.pdf",
    ]
    assert len(exclusions) == 1
    assert exclusions[0].excluded_path == "文献1/N/z-copy.pdf"
    assert exclusions[0].retained_path == "文献1/C/a-original.pdf"
    assert exclusions[0].sha256 == shared_sha


def test_build_screening_input_bounds_source_text_and_separates_context() -> None:
    source = _source("文献1/C/example-paper.pdf", "c" * 64)
    pages = [
        PageRecord(
            pdf_page=1,
            text="A" * 5_000,
            character_count=5_000,
            replacement_character_count=0,
        ),
        PageRecord(
            pdf_page=2,
            text="B" * 5_000,
            character_count=5_000,
            replacement_character_count=0,
        ),
    ]

    built = build_screening_input(
        source,
        pages,
        {"seed_reaction_id": "SRC-CC-001", "net_transformation": "seed only"},
        "Classify relevance conservatively.",
        max_characters=6_000,
    )

    assert "PROJECT_CONTEXT_NOT_SOURCE_EVIDENCE" in built
    assert "SCREENING_CONTENT_NOT_LITERATURE_EVIDENCE" in built
    assert '"source_path": "文献1/C/example-paper.pdf"' in built
    assert "A" * 5_000 in built
    assert "B" * 1_000 in built
    assert "B" * 1_001 not in built
    assert "example-paper" in built


def test_screening_decision_rejects_unknown_category() -> None:
    with pytest.raises(ValidationError):
        ScreeningDecision(
            source_path="文献1/C/example.pdf",
            sha256="d" * 64,
            category="maybe_relevant",
            confidence="medium",
            rationale="Unsupported category must fail validation.",
            matched_dimensions=[],
        )


@pytest.mark.parametrize(
    ("category", "included"),
    [
        ("direct_precedent", True),
        ("shared_reaction_manifold", True),
        ("physical_organic_support", True),
        ("failure_boundary", True),
        ("uncertain", True),
        ("unrelated", False),
    ],
)
def test_screening_decision_includes_every_category_except_unrelated(
    category: str,
    included: bool,
) -> None:
    decision = ScreeningDecision(
        source_path="文献1/C/example.pdf",
        sha256="e" * 64,
        category=category,
        confidence="high",
        rationale="Literal fixture decision.",
        matched_dimensions=["electrophile-class similarity"],
    )

    assert decision.included is included


class ScreeningClient:
    def __init__(self, *, omit_last: bool = False, fail: bool = False) -> None:
        self.batch_sizes: list[int] = []
        self.omit_last = omit_last
        self.fail = fail

    def create_structured(self, model, input_text, schema, schema_name):
        if self.fail:
            raise RuntimeError("controlled screening failure")
        records_text = input_text.split("SCREENING_RECORDS_JSON\n", 1)[1].split(
            "\nEND_SCREENING_RECORDS_JSON", 1
        )[0]
        records = json.loads(records_text)
        self.batch_sizes.append(len(records))
        decisions = []
        for record in records:
            name = Path(record["source_path"]).name
            category = (
                "unrelated"
                if "unrelated" in name
                else "uncertain"
                if "uncertain" in name
                else "direct_precedent"
            )
            decisions.append(
                {
                    "source_path": record["source_path"],
                    "sha256": record["sha256"],
                    "category": category,
                    "confidence": "high",
                    "rationale": f"Fixture classification for {name}.",
                    "matched_dimensions": ["electrophile-class similarity"],
                }
            )
        if self.omit_last and decisions:
            decisions.pop()
        call_number = len(self.batch_sizes)
        return ApiResult(
            response_id=f"resp-screen-{call_number}",
            returned_model=model,
            status="completed",
            parsed_output={"decisions": decisions},
            usage=ApiUsage(
                input_tokens=100 * len(records),
                output_tokens=10 * len(decisions),
                total_tokens=100 * len(records) + 10 * len(decisions),
            ),
        )


class InterruptingScreeningClient(ScreeningClient):
    def create_structured(self, model, input_text, schema, schema_name):
        if self.batch_sizes:
            raise KeyboardInterrupt("controlled interruption")
        return super().create_structured(model, input_text, schema, schema_name)


def _write_screening_config(tmp_path: Path) -> Path:
    seed_path = tmp_path / "seed.yaml"
    seed_path.write_text(
        yaml.safe_dump({"freeze_version": "test", "seed_reaction_id": "SRC-CC-001"}),
        encoding="utf-8",
    )
    prompt_path = tmp_path / "screening.md"
    prompt_path.write_text("Classify fixture records conservatively.\n", encoding="utf-8")
    config = {
        "source_directories": {
            "tier_1": "Tier1",
            "tier_2": "Tier2",
            "tier_3": "Tier3",
            "tier_4": "Tier4",
        },
        "model": "gpt-5.6-sol",
        "seed_context_path": str(seed_path),
        "screening_prompt_path": str(prompt_path),
        "screening_schema_path": str(Path("config/screening_schema.json").resolve()),
        "screening": {"batch_size": 8, "max_characters_per_paper": 6000},
    }
    config_path = tmp_path / "pilot.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return config_path


def _screening_sources(tmp_path: Path, names: list[str]) -> Path:
    root = tmp_path / "sources"
    for tier in ("Tier1", "Tier2", "Tier3", "Tier4"):
        (root / tier).mkdir(parents=True)
    for index, name in enumerate(names):
        pdf = create_fixture_pdf(root / "Tier1" / name)
        pdf.write_bytes(pdf.read_bytes() + f"\n% unique-{index}\n".encode())
    return root


def test_screen_corpus_batches_persists_and_resumes_deterministically(
    tmp_path: Path,
) -> None:
    names = [f"paper-{index:02d}.pdf" for index in range(8)] + [
        "unrelated-paper.pdf",
        "uncertain-paper.pdf",
    ]
    source_root = _screening_sources(tmp_path, names)
    config_path = _write_screening_config(tmp_path)
    output_root = tmp_path / "output"
    client = ScreeningClient()

    first = screen_corpus(config_path, source_root, output_root, client=client)
    jsonl_path = output_root / "derived/screening/corpus_screening.jsonl"
    csv_path = output_root / "derived/screening/corpus_screening.csv"
    first_bytes = (jsonl_path.read_bytes(), csv_path.read_bytes())
    second = screen_corpus(config_path, source_root, output_root, client=client)

    assert client.batch_sizes == [8, 2]
    assert first == second
    assert first["completed_count"] == 10
    assert first["included_count"] == 9
    assert first["excluded_count"] == 1
    assert first["uncertain_count"] == 1
    assert (jsonl_path.read_bytes(), csv_path.read_bytes()) == first_bytes
    assert len(list((output_root / "derived/screening/papers").glob("*/decision.json"))) == 10


def test_screen_corpus_prompt_change_invalidates_cached_decisions(tmp_path: Path) -> None:
    source_root = _screening_sources(tmp_path, ["paper-a.pdf", "paper-b.pdf"])
    config_path = _write_screening_config(tmp_path)
    output_root = tmp_path / "output"
    client = ScreeningClient()

    screen_corpus(config_path, source_root, output_root, client=client)
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    Path(config["screening_prompt_path"]).write_text(
        "Changed screening contract.\n", encoding="utf-8"
    )
    screen_corpus(config_path, source_root, output_root, client=client)

    assert client.batch_sizes == [2, 2]


def test_screen_corpus_keeps_missing_or_failed_decisions_as_uncertain(
    tmp_path: Path,
) -> None:
    source_root = _screening_sources(tmp_path, ["paper-a.pdf", "paper-b.pdf"])
    config_path = _write_screening_config(tmp_path)

    missing_output = tmp_path / "missing-output"
    missing = screen_corpus(
        config_path,
        source_root,
        missing_output,
        client=ScreeningClient(omit_last=True),
    )
    failed_output = tmp_path / "failed-output"
    failed = screen_corpus(
        config_path,
        source_root,
        failed_output,
        client=ScreeningClient(fail=True),
    )

    assert missing["category_counts"] == {"direct_precedent": 1, "uncertain": 1}
    assert missing["included_count"] == 2
    assert failed["category_counts"] == {"uncertain": 2}
    assert failed["included_count"] == 2


def test_screen_corpus_publishes_progress_after_each_completed_batch(
    tmp_path: Path,
) -> None:
    source_root = _screening_sources(
        tmp_path, [f"paper-{index:02d}.pdf" for index in range(10)]
    )
    config_path = _write_screening_config(tmp_path)
    output_root = tmp_path / "output"

    with pytest.raises(KeyboardInterrupt, match="controlled interruption"):
        screen_corpus(
            config_path,
            source_root,
            output_root,
            client=InterruptingScreeningClient(),
        )

    progress = json.loads(
        (output_root / "derived/screening/screening_summary.json").read_text()
    )
    assert progress["completed_count"] == 8
    assert progress["unique_pdf_count"] == 10

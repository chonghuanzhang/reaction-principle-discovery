from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.models import CandidateRecord, SourceRecord
from pipeline.full_corpus import (
    FullCorpusError,
    _restrict_previous_state,
    build_full_corpus_queue,
    finalize_calibration,
    finalize_full_corpus,
    load_screened_paths,
    process_source,
    select_calibration_paths,
)
from tests.fixtures.make_fixture_pdf import create_fixture_pdf
from tests.test_pilot_select import CONFIG as SELECTION_CONFIG
from tests.test_run_pilot import SourceAwareClient


def _candidate(tier_index: int, item_index: int) -> CandidateRecord:
    tier = f"tier_{tier_index}"
    keyword = SELECTION_CONFIG["tier_keywords"][tier][0]
    text = (keyword + " ") * (item_index + 1) * 20
    return CandidateRecord(
        source_path=f"Tier{tier_index}/paper-{item_index}.pdf",
        tier=tier,
        sha256=f"{tier_index}{item_index}".ljust(64, str(item_index)),
        page_count=item_index + 1,
        searchable_character_count=len(text),
        searchable_text=text,
        visual_page_count=item_index % 3,
    )


def _source(candidate: CandidateRecord) -> SourceRecord:
    return SourceRecord(
        source_path=candidate.source_path,
        tier=candidate.tier,
        byte_size=100,
        sha256=candidate.sha256,
        page_count=candidate.page_count,
        parser_version="pypdf-test",
    )


def test_calibration_queue_has_five_distinct_papers_per_tier() -> None:
    candidates = [
        _candidate(tier_index, item_index)
        for tier_index in range(1, 5)
        for item_index in range(6)
    ]

    selected = select_calibration_paths(candidates, SELECTION_CONFIG)
    queue = build_full_corpus_queue(
        [_source(candidate) for candidate in candidates],
        candidates,
        SELECTION_CONFIG,
    )

    assert len(selected) == 20
    assert len(set(selected)) == 20
    for tier_index in range(1, 5):
        assert sum(path.startswith(f"Tier{tier_index}/") for path in selected) == 5
    assert len(queue.items) == 24
    assert sum(item.phase == "calibration" for item in queue.items) == 20
    assert {item.source_path for item in queue.items} == {
        candidate.source_path for candidate in candidates
    }


def test_queue_deduplicates_by_sha_and_is_byte_stable(tmp_path: Path) -> None:
    candidates = [_candidate(tier, item) for tier in range(1, 5) for item in range(6)]
    duplicate = candidates[0].model_copy(
        update={"source_path": "Tier1/z-duplicate.pdf"}
    )
    candidates.append(duplicate)
    sources = [_source(candidate) for candidate in candidates]

    first = build_full_corpus_queue(sources, candidates, SELECTION_CONFIG)
    second = build_full_corpus_queue(sources, list(reversed(candidates)), SELECTION_CONFIG)

    assert first.model_dump_json() == second.model_dump_json()
    assert len(first.items) == 24
    assert len(first.duplicate_exclusions) == 1
    assert first.duplicate_exclusions[0].excluded_path == "Tier1/z-duplicate.pdf"


def test_load_screened_paths_excludes_only_unrelated_and_fails_closed_when_stale(
    tmp_path: Path,
) -> None:
    screening = tmp_path / "derived" / "screening"
    screening.mkdir(parents=True)
    summary = {
        "inventory_digest": "a" * 64,
        "inventoried_pdf_count": 3,
        "unique_pdf_count": 3,
        "duplicate_count": 0,
        "completed_count": 3,
        "included_count": 2,
        "excluded_count": 1,
        "uncertain_count": 1,
        "category_counts": {
            "direct_precedent": 1,
            "uncertain": 1,
            "unrelated": 1,
        },
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
    }
    (screening / "screening_summary.json").write_text(
        json.dumps(summary), encoding="utf-8"
    )
    rows = [
        {"source_path": "Tier1/direct.pdf", "included": True},
        {"source_path": "Tier1/uncertain.pdf", "included": True},
        {"source_path": "Tier1/unrelated.pdf", "included": False},
    ]
    (screening / "corpus_screening.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )

    assert load_screened_paths(tmp_path, "a" * 64) == {
        "Tier1/direct.pdf",
        "Tier1/uncertain.pdf",
    }
    with pytest.raises(FullCorpusError, match="stale"):
        load_screened_paths(tmp_path, "b" * 64)


def test_process_source_reuses_only_matching_seed_context(tmp_path: Path) -> None:
    source_root = tmp_path / "sources"
    pdf = source_root / "Tier1" / "paper.pdf"
    pdf.parent.mkdir(parents=True)
    create_fixture_pdf(pdf)
    from pipeline.inventory import inventory_sources

    source = inventory_sources(source_root, {"tier_1": Path("Tier1")})[0]
    client = SourceAwareClient()
    config = {
        "model": "gpt-5.6-sol",
        "schema_version": "1.0",
        "prompt_version": "1.0",
        "max_chunk_characters": 200000,
    }
    schema = json.loads(Path("config/extraction_schema.json").read_text())
    prompt = Path("config/prompts/evidence_extraction.md").read_text()

    first = process_source(
        source,
        config,
        schema,
        prompt,
        {"freeze_version": "1.0", "seed_reaction_id": "SRC-CC-001"},
        source_root,
        tmp_path / "output",
        client,
        resume=True,
    )
    second = process_source(
        source,
        config,
        schema,
        prompt,
        {"freeze_version": "1.0", "seed_reaction_id": "SRC-CC-001"},
        source_root,
        tmp_path / "output",
        client,
        resume=True,
    )
    changed = process_source(
        source,
        config,
        schema,
        prompt,
        {"freeze_version": "2.0", "seed_reaction_id": "SRC-CC-001"},
        source_root,
        tmp_path / "output",
        client,
        resume=True,
    )

    assert [first.status, second.status, changed.status] == [
        "validated",
        "reused",
        "validated",
    ]
    assert client.call_count == 2


def test_process_source_rejects_multiple_chunks_without_calling_api(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "sources"
    pdf = source_root / "Tier1" / "paper.pdf"
    pdf.parent.mkdir(parents=True)
    create_fixture_pdf(pdf)
    from pipeline.inventory import inventory_sources

    source = inventory_sources(source_root, {"tier_1": Path("Tier1")})[0]
    client = SourceAwareClient()

    result = process_source(
        source,
        {
            "model": "gpt-5.6-sol",
            "schema_version": "1.0",
            "prompt_version": "1.0",
            "max_chunk_characters": 10,
        },
        json.loads(Path("config/extraction_schema.json").read_text()),
        Path("config/prompts/evidence_extraction.md").read_text(),
        {"freeze_version": "1.0"},
        source_root,
        tmp_path / "output",
        client,
        resume=True,
    )

    assert result.status == "source_too_long"
    assert client.call_count == 0


def test_process_source_uses_bounded_oversized_limit_for_one_call(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "sources"
    pdf = source_root / "Tier1" / "paper.pdf"
    pdf.parent.mkdir(parents=True)
    create_fixture_pdf(pdf)
    from pipeline.inventory import inventory_sources

    source = inventory_sources(source_root, {"tier_1": Path("Tier1")})[0]
    client = SourceAwareClient()

    result = process_source(
        source,
        {
            "model": "gpt-5.6-sol",
            "schema_version": "1.0",
            "prompt_version": "1.0",
            "max_chunk_characters": 10,
            "max_oversized_characters": 100_000,
        },
        json.loads(Path("config/extraction_schema.json").read_text()),
        Path("config/prompts/evidence_extraction.md").read_text(),
        {"freeze_version": "1.0"},
        source_root,
        tmp_path / "output",
        client,
        resume=True,
    )

    assert result.status == "validated"
    assert client.call_count == 1


def test_finalize_calibration_writes_compact_local_summary(tmp_path: Path) -> None:
    manifest = {
        "queue_digest": "q" * 64,
        "seed_context_digest": "s" * 64,
        "prompt_digest": "p" * 64,
        "schema_digest": "h" * 64,
        "paper_statuses": {"Tier1/a.pdf": "api_failed"},
        "results": [
            {
                "source_path": "Tier1/a.pdf",
                "status": "api_failed",
                "failure_reason": "controlled failure",
            }
        ],
    }

    finalize_calibration(tmp_path, manifest)

    summary = json.loads(
        (tmp_path / "derived/full_corpus/calibration_summary.json").read_text()
    )
    assert summary["completed_paper_count"] == 0
    assert summary["failed_paper_count"] == 1
    assert (tmp_path / "derived/synthesis/api_usage_summary.json").is_file()


def test_previous_manifest_state_is_restricted_to_current_queue() -> None:
    previous = {
        "paper_statuses": {
            "Tier1/current.pdf": "validated",
            "Tier1/historical.pdf": "validated",
        },
        "results": [
            {"source_path": "Tier1/current.pdf", "status": "validated"},
            {"source_path": "Tier1/historical.pdf", "status": "validated"},
        ],
    }

    statuses, results = _restrict_previous_state(
        previous, {"Tier1/current.pdf"}
    )

    assert statuses == {"Tier1/current.pdf": "validated"}
    assert results == [
        {"source_path": "Tier1/current.pdf", "status": "validated"}
    ]


def test_finalize_full_corpus_writes_scoped_summary(tmp_path: Path) -> None:
    manifest = {
        "queue_digest": "q" * 64,
        "paper_statuses": {
            "Tier1/current.pdf": "api_failed",
            "Tier1/historical.pdf": "validated",
        },
        "results": [
            {
                "source_path": "Tier1/current.pdf",
                "status": "api_failed",
                "failure_reason": "controlled failure",
            },
            {"source_path": "Tier1/historical.pdf", "status": "validated"},
        ],
    }

    finalize_full_corpus(tmp_path, manifest, {"Tier1/current.pdf"})

    summary = json.loads(
        (tmp_path / "derived/full_corpus/full_corpus_summary.json").read_text()
    )
    assert summary["completed_paper_count"] == 0
    assert summary["failed_paper_count"] == 1
    assert summary["failures"][0]["source_path"] == "Tier1/current.pdf"

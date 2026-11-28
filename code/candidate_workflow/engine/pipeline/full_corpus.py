"""API-first, resumable processing for every unique literature PDF."""

from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from pipeline.api_client import ApiClientError, ApiResult, ResponsesClient
from pipeline.grounding import build_source_spans, ground_extraction
from pipeline.inventory import inventory_sources, sha256_file
from pipeline.models import CandidateRecord, DuplicateExclusion, SourceRecord
from pipeline.pdf_extract import extract_pages
from pipeline.pilot_select import select_pilot
from pipeline.prompt_builder import (
    build_extraction_input,
    build_page_chunks,
    load_seed_context,
)
from pipeline.review import write_review_markdown
from pipeline.screening import deduplicate_sources, inventory_digest
from pipeline.run_pilot import (
    PilotRunError,
    _atomic_json,
    _cache_key,
    _candidate_from_source,
    _configured_path,
    _default_client,
    _load_config,
)
from pipeline.validate import validate_extraction


class FullCorpusError(RuntimeError):
    """A global full-corpus failure that cannot be isolated to one paper."""


class CorpusQueueItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_path: str
    tier: str
    sha256: str
    page_count: int
    searchable_character_count: int
    total_score: int
    phase: Literal["calibration", "remaining"]
    calibration_role: str | None = None


class CorpusQueue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    queue_digest: str
    items: tuple[CorpusQueueItem, ...]
    duplicate_exclusions: tuple[DuplicateExclusion, ...]


class PaperProcessResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_path: str
    status: str
    response_id: str | None = None
    returned_model: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    failure_reason: str | None = None


def _ordered_role_candidates(
    candidates: list[CandidateRecord],
    score_by_path: dict[str, int],
) -> list[tuple[str, list[CandidateRecord]]]:
    by_score = sorted(
        candidates,
        key=lambda item: (-score_by_path[item.source_path], item.source_path),
    )
    by_median = sorted(
        candidates,
        key=lambda item: (score_by_path[item.source_path], item.source_path),
    )
    midpoint = len(by_median) // 2
    median_order = sorted(
        by_median,
        key=lambda item: (
            abs(by_median.index(item) - midpoint),
            item.source_path,
        ),
    )
    return [
        ("highest_relevance", by_score),
        (
            "longest_text",
            sorted(
                candidates,
                key=lambda item: (-item.searchable_character_count, item.source_path),
            ),
        ),
        (
            "lowest_searchable_coverage",
            sorted(
                candidates,
                key=lambda item: (item.searchable_character_count, item.source_path),
            ),
        ),
        (
            "strongest_visual_signal",
            sorted(
                candidates,
                key=lambda item: (-item.visual_page_count, item.source_path),
            ),
        ),
        ("median_relevance", median_order),
    ]


def _calibration_roles(
    candidates: list[CandidateRecord],
    selection_config: dict[str, object],
) -> dict[str, str]:
    audit = select_pilot(candidates, selection_config)
    retained_paths = {item.source_path for item in audit.ranked_candidates}
    retained = [item for item in candidates if item.source_path in retained_paths]
    score_by_path = {
        item.source_path: item.total_score for item in audit.ranked_candidates
    }
    roles: dict[str, str] = {}
    for tier in sorted({item.tier for item in retained}):
        tier_candidates = [item for item in retained if item.tier == tier]
        used: set[str] = set()
        for role, ordered in _ordered_role_candidates(tier_candidates, score_by_path):
            selected = next(
                (item for item in ordered if item.source_path not in used),
                None,
            )
            if selected is None:
                continue
            roles[selected.source_path] = role
            used.add(selected.source_path)
            if len(used) == min(5, len(tier_candidates)):
                break
    return roles


def select_calibration_paths(
    candidates: list[CandidateRecord],
    selection_config: dict[str, object],
) -> tuple[str, ...]:
    """Return a stable five-paper coverage sample for every Tier."""

    roles = _calibration_roles(candidates, selection_config)
    role_order = {
        "highest_relevance": 0,
        "longest_text": 1,
        "lowest_searchable_coverage": 2,
        "strongest_visual_signal": 3,
        "median_relevance": 4,
    }
    candidate_by_path = {item.source_path: item for item in candidates}
    return tuple(
        sorted(
            roles,
            key=lambda path: (
                candidate_by_path[path].tier,
                role_order[roles[path]],
                path,
            ),
        )
    )


def build_full_corpus_queue(
    sources: list[SourceRecord],
    candidates: list[CandidateRecord],
    selection_config: dict[str, object],
    duplicate_exclusions: tuple[DuplicateExclusion, ...] | None = None,
) -> CorpusQueue:
    """Deduplicate all candidates and partition a stable calibration queue."""

    audit = select_pilot(candidates, selection_config)
    candidate_by_path = {item.source_path: item for item in candidates}
    source_by_path = {item.source_path: item for item in sources}
    retained_paths = {item.source_path for item in audit.ranked_candidates}
    retained_candidates = [
        candidate_by_path[path] for path in sorted(retained_paths)
    ]
    roles = _calibration_roles(retained_candidates, selection_config)
    score_by_path = {
        item.source_path: item.total_score for item in audit.ranked_candidates
    }
    role_order = {
        "highest_relevance": 0,
        "longest_text": 1,
        "lowest_searchable_coverage": 2,
        "strongest_visual_signal": 3,
        "median_relevance": 4,
    }
    calibration_paths = sorted(
        roles,
        key=lambda path: (
            candidate_by_path[path].tier,
            role_order[roles[path]],
            path,
        ),
    )
    remaining_paths = sorted(
        retained_paths - set(calibration_paths),
        key=lambda path: (
            candidate_by_path[path].tier,
            -score_by_path[path],
            path,
        ),
    )
    ordered_paths = calibration_paths + remaining_paths
    items = tuple(
        CorpusQueueItem(
            source_path=path,
            tier=source_by_path[path].tier,
            sha256=source_by_path[path].sha256,
            page_count=candidate_by_path[path].page_count,
            searchable_character_count=candidate_by_path[path].searchable_character_count,
            total_score=score_by_path[path],
            phase="calibration" if path in roles else "remaining",
            calibration_role=roles.get(path),
        )
        for path in ordered_paths
    )
    effective_exclusions = (
        audit.duplicate_exclusions
        if duplicate_exclusions is None
        else duplicate_exclusions
    )
    digest_payload = {
        "items": [item.model_dump(mode="json") for item in items],
        "duplicate_exclusions": [
            item.model_dump(mode="json") for item in effective_exclusions
        ],
    }
    digest = hashlib.sha256(
        json.dumps(digest_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return CorpusQueue(
        queue_digest=digest,
        items=items,
        duplicate_exclusions=effective_exclusions,
    )


def load_screened_paths(output_root: Path, expected_inventory_digest: str) -> set[str]:
    """Load a complete compatible screening checkpoint or fail closed."""

    screening_root = output_root / "derived" / "screening"
    summary_path = screening_root / "screening_summary.json"
    decisions_path = screening_root / "corpus_screening.jsonl"
    if not summary_path.is_file() or not decisions_path.is_file():
        raise FullCorpusError("Complete corpus screening is required before queue construction.")
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        rows = [
            json.loads(line)
            for line in decisions_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (json.JSONDecodeError, OSError) as exc:
        raise FullCorpusError("Corpus screening artifacts are unreadable.") from exc
    if summary.get("inventory_digest") != expected_inventory_digest:
        raise FullCorpusError("Corpus screening is stale for the current PDF inventory.")
    unique_count = int(summary.get("unique_pdf_count", -1))
    completed_count = int(summary.get("completed_count", -1))
    if completed_count != unique_count or len(rows) != unique_count:
        raise FullCorpusError("Corpus screening is incomplete for the current PDF inventory.")
    paths = [row.get("source_path") for row in rows]
    if any(not isinstance(path, str) or not path for path in paths) or len(set(paths)) != len(paths):
        raise FullCorpusError("Corpus screening contains invalid or duplicate source paths.")
    included = {row["source_path"] for row in rows if row.get("included") is True}
    if len(included) != int(summary.get("included_count", -1)):
        raise FullCorpusError("Corpus screening included count does not match its decisions.")
    return included


def process_source(
    source: SourceRecord,
    config: dict,
    schema: dict,
    prompt_text: str,
    seed_context: dict[str, object],
    source_root: Path,
    output_root: Path,
    api: ResponsesClient | object,
    *,
    resume: bool = True,
) -> PaperProcessResult:
    """Process one immutable source without raising paper-local failures."""

    source_path = source_root / source.source_path
    if sha256_file(source_path) != source.sha256:
        return PaperProcessResult(
            source_path=source.source_path,
            status="source_changed",
            failure_reason="Source checksum changed after queue construction.",
        )
    paper_dir = (
        output_root
        / "derived"
        / "full_corpus"
        / "papers"
        / f"{source.tier}-{source.sha256[:12]}"
    )
    validated_path = paper_dir / "validated.json"
    key = _cache_key(
        source,
        str(config["model"]),
        prompt_text,
        schema,
        config,
        seed_context,
    )
    if resume and validated_path.is_file():
        existing = json.loads(validated_path.read_text(encoding="utf-8"))
        if existing.get("cache_key") == key and existing.get("validation", {}).get(
            "is_valid"
        ):
            return PaperProcessResult(source_path=source.source_path, status="reused")

    pages = extract_pages(source_path)
    chunks = build_page_chunks(pages, int(config["max_chunk_characters"]))
    if len(chunks) != 1:
        oversized_limit = int(
            config.get("max_oversized_characters", config["max_chunk_characters"])
        )
        if oversized_limit > int(config["max_chunk_characters"]):
            oversized_chunks = build_page_chunks(pages, oversized_limit)
            if len(oversized_chunks) == 1:
                chunks = oversized_chunks
                oversized_config = dict(config)
                oversized_config["max_chunk_characters"] = oversized_limit
                key = _cache_key(
                    source,
                    str(config["model"]),
                    prompt_text,
                    schema,
                    oversized_config,
                    seed_context,
                )
                if resume and validated_path.is_file():
                    existing = json.loads(validated_path.read_text(encoding="utf-8"))
                    if existing.get("cache_key") == key and existing.get(
                        "validation", {}
                    ).get("is_valid"):
                        return PaperProcessResult(
                            source_path=source.source_path, status="reused"
                        )
    if len(chunks) != 1:
        return PaperProcessResult(
            source_path=source.source_path,
            status="source_too_long",
            failure_reason=(
                f"Source requires {len(chunks)} chunks at the configured character limit."
            ),
        )
    extraction_input = build_extraction_input(
        source,
        chunks[0],
        prompt_text,
        seed_context=seed_context,
    )
    try:
        result: ApiResult = api.create_structured(
            str(config["model"]),
            extraction_input,
            schema,
            "full_corpus_paper_evidence",
        )
    except ApiClientError as exc:
        status = "authentication_failed" if exc.status in {401, 403} else "api_failed"
        return PaperProcessResult(
            source_path=source.source_path,
            status=status,
            failure_reason=str(exc),
        )
    except Exception as exc:
        return PaperProcessResult(
            source_path=source.source_path,
            status="api_failed",
            failure_reason=f"{type(exc).__name__}: {str(exc)[:500]}",
        )

    raw_payload = {
        "cache_key": key,
        "api": {
            "response_id": result.response_id,
            "returned_model": result.returned_model,
            "status": result.status,
            "usage": asdict(result.usage),
        },
        "extraction": result.parsed_output,
    }
    _atomic_json(paper_dir / "raw.json", raw_payload)
    try:
        grounded, grounding_changes = ground_extraction(
            result.parsed_output, build_source_spans(pages), source=source
        )
    except ValueError as exc:
        _atomic_json(
            paper_dir / "grounding_failed.json",
            {"cache_key": key, "message": str(exc)},
        )
        return PaperProcessResult(
            source_path=source.source_path,
            status="grounding_failed",
            response_id=result.response_id,
            returned_model=result.returned_model,
            input_tokens=result.usage.input_tokens or 0,
            output_tokens=result.usage.output_tokens or 0,
            total_tokens=result.usage.total_tokens or 0,
            failure_reason=str(exc),
        )
    validation = validate_extraction(grounded, pages, source, schema)
    if not validation.is_valid:
        _atomic_json(
            paper_dir / "validation_failed.json",
            {"cache_key": key, "validation": validation.model_dump(mode="json")},
        )
        return PaperProcessResult(
            source_path=source.source_path,
            status="validation_failed",
            response_id=result.response_id,
            returned_model=result.returned_model,
            input_tokens=result.usage.input_tokens or 0,
            output_tokens=result.usage.output_tokens or 0,
            total_tokens=result.usage.total_tokens or 0,
            failure_reason=",".join(issue.code for issue in validation.errors),
        )

    visual_pages = sorted(
        set(grounded["visual_review_pages"])
        | {page.pdf_page for page in pages if page.visual_review_reasons}
    )
    _atomic_json(
        paper_dir / "visual_review_queue.json",
        {
            "source_file": source.source_path,
            "sha256": source.sha256,
            "pdf_pages": visual_pages,
            "status": "pending",
        },
    )
    write_review_markdown(grounded, validation, paper_dir / "review.md")
    _atomic_json(
        validated_path,
        {
            "cache_key": key,
            "api": raw_payload["api"],
            "validation": validation.model_dump(mode="json"),
            "extraction": grounded,
            "grounding": {"changes": grounding_changes},
        },
    )
    return PaperProcessResult(
        source_path=source.source_path,
        status="validated",
        response_id=result.response_id,
        returned_model=result.returned_model,
        input_tokens=result.usage.input_tokens or 0,
        output_tokens=result.usage.output_tokens or 0,
        total_tokens=result.usage.total_tokens or 0,
    )


def _prepare_queue(
    config: dict,
    source_root: Path,
    output_root: Path,
) -> tuple[list[SourceRecord], list[SourceRecord], CorpusQueue]:
    directories = {
        tier: Path(relative) for tier, relative in config["source_directories"].items()
    }
    all_sources = [
        source
        for source in inventory_sources(source_root, directories)
        if source.source_path.casefold().endswith(".pdf")
    ]
    sources = all_sources
    duplicate_exclusions: tuple[DuplicateExclusion, ...] | None = None
    if "screening" in config:
        retained_sources, duplicate_exclusions = deduplicate_sources(all_sources)
        expected_digest = inventory_digest(all_sources, duplicate_exclusions)
        included_paths = load_screened_paths(output_root, expected_digest)
        retained_by_path = {source.source_path: source for source in retained_sources}
        missing = included_paths - set(retained_by_path)
        if missing:
            raise FullCorpusError("Corpus screening references sources absent from inventory.")
        sources = [retained_by_path[path] for path in sorted(included_paths)]
    candidates = [_candidate_from_source(source_root, source) for source in sources]
    queue = build_full_corpus_queue(
        sources,
        candidates,
        config["selection"],
        duplicate_exclusions=duplicate_exclusions,
    )
    _atomic_json(
        output_root / "derived" / "full_corpus" / "queue.json",
        queue.model_dump(mode="json"),
    )
    return all_sources, sources, queue


def _approval_matches(output_root: Path, queue: CorpusQueue, digests: dict) -> bool:
    approval_path = output_root / "derived" / "full_corpus" / "calibration_approved.json"
    if not approval_path.is_file():
        return False
    approval = json.loads(approval_path.read_text(encoding="utf-8"))
    return bool(approval.get("approved")) and all(
        approval.get(key) == value
        for key, value in {"queue_digest": queue.queue_digest, **digests}.items()
    )


def _restrict_previous_state(
    previous: dict, allowed_paths: set[str]
) -> tuple[dict[str, str], list[dict]]:
    """Keep resumable state only for sources in the current screened queue."""

    statuses = {
        path: status
        for path, status in previous.get("paper_statuses", {}).items()
        if path in allowed_paths
    }
    results = [
        row
        for row in previous.get("results", [])
        if row.get("source_path") in allowed_paths
    ]
    return statuses, results


def finalize_calibration(
    output_root: Path,
    manifest: dict,
    source_paths: set[str] | None = None,
) -> None:
    """Create model-free evidence tables and the compact calibration checkpoint."""

    from pipeline.aggregate import aggregate_validated_records, write_calibration_summary

    selected_paths = source_paths or set(manifest.get("paper_statuses", {}))
    summary = aggregate_validated_records(
        output_root / "derived" / "full_corpus" / "papers",
        output_root / "derived" / "synthesis",
        source_paths=selected_paths,
    )
    scoped_manifest = dict(manifest)
    scoped_statuses, scoped_results = _restrict_previous_state(
        manifest, selected_paths
    )
    scoped_manifest["paper_statuses"] = scoped_statuses
    scoped_manifest["results"] = scoped_results
    write_calibration_summary(
        scoped_manifest,
        summary,
        output_root / "derived" / "full_corpus" / "calibration_summary.json",
    )


def finalize_full_corpus(
    output_root: Path,
    manifest: dict,
    source_paths: set[str],
) -> None:
    """Create final evidence tables and a scoped full-corpus checkpoint."""

    from pipeline.aggregate import aggregate_validated_records, write_calibration_summary

    summary = aggregate_validated_records(
        output_root / "derived" / "full_corpus" / "papers",
        output_root / "derived" / "synthesis",
        source_paths=source_paths,
    )
    scoped_manifest = dict(manifest)
    scoped_statuses, scoped_results = _restrict_previous_state(
        manifest, source_paths
    )
    scoped_manifest["paper_statuses"] = scoped_statuses
    scoped_manifest["results"] = scoped_results
    write_calibration_summary(
        scoped_manifest,
        summary,
        output_root / "derived" / "full_corpus" / "full_corpus_summary.json",
    )


def run_full_corpus(
    config_path: Path,
    source_root: Path,
    output_root: Path,
    phase: Literal["queue", "calibration", "remaining", "status"],
    *,
    client: ResponsesClient | object | None = None,
) -> dict:
    """Build or execute one stable phase of the full-corpus queue."""

    config_path = config_path.resolve()
    source_root = source_root.resolve(strict=True)
    output_root = output_root.resolve()
    manifest_path = output_root / "derived" / "full_corpus" / "manifest.json"
    if phase == "status":
        if not manifest_path.is_file():
            return {"status": "not_started"}
        return json.loads(manifest_path.read_text(encoding="utf-8"))

    config = _load_config(config_path)
    schema_path = _configured_path(config_path, config, "schema_path", "extraction_schema.json")
    prompt_path = _configured_path(
        config_path, config, "prompt_path", "prompts/evidence_extraction.md"
    )
    seed_path = _configured_path(
        config_path, config, "seed_context_path", "seed_reaction.yaml"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    prompt_text = prompt_path.read_text(encoding="utf-8")
    seed_context = load_seed_context(seed_path)
    run_config = dict(config)
    run_config["max_chunk_characters"] = int(
        config.get("full_corpus", {}).get("max_chunk_characters", 200000)
    )
    run_config["max_oversized_characters"] = int(
        config.get("full_corpus", {}).get(
            "max_oversized_characters", run_config["max_chunk_characters"]
        )
    )
    all_sources, sources, queue = _prepare_queue(config, source_root, output_root)
    if phase == "queue":
        return {
            "status": "queued",
            "inventoried_pdf_count": len(all_sources),
            "unique_pdf_count": len(queue.items),
            "duplicate_count": len(queue.duplicate_exclusions),
            "calibration_count": sum(item.phase == "calibration" for item in queue.items),
            "queue_digest": queue.queue_digest,
        }

    digests = {
        "seed_context_digest": hashlib.sha256(seed_path.read_bytes()).hexdigest(),
        "prompt_digest": hashlib.sha256(prompt_path.read_bytes()).hexdigest(),
        "schema_digest": hashlib.sha256(schema_path.read_bytes()).hexdigest(),
    }
    if phase == "remaining" and not _approval_matches(
        output_root, queue, digests
    ):
        raise FullCorpusError(
            "Remaining-corpus execution requires a matching calibration approval."
        )

    source_by_path = {source.source_path: source for source in sources}
    api = client or _default_client(str(config["model"]))
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    previous = (
        json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest_path.is_file()
        else {}
    )
    items = [item for item in queue.items if item.phase == phase]
    resumable_paths = (
        {item.source_path for item in queue.items}
        if phase == "remaining"
        else {item.source_path for item in items}
    )
    statuses, results = _restrict_previous_state(previous, resumable_paths)
    for item in items:
        result = process_source(
            source_by_path[item.source_path],
            run_config,
            schema,
            prompt_text,
            seed_context,
            source_root,
            output_root,
            api,
            resume=True,
        )
        statuses[item.source_path] = result.status
        results = [row for row in results if row.get("source_path") != item.source_path]
        results.append(result.model_dump(mode="json"))
        manifest = {
            "run_id": run_id,
            "phase": phase,
            "queue_digest": queue.queue_digest,
            **digests,
            "paper_statuses": dict(sorted(statuses.items())),
            "results": sorted(results, key=lambda row: row["source_path"]),
            "updated_at": datetime.now(UTC).isoformat(),
        }
        _atomic_json(manifest_path, manifest)
        _atomic_json(output_root / "runs" / run_id / "manifest.json", manifest)
        if result.status == "authentication_failed":
            raise FullCorpusError(result.failure_reason or "API authentication failed.")
    completed_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if phase == "calibration":
        finalize_calibration(
            output_root,
            completed_manifest,
            {item.source_path for item in items},
        )
    elif phase == "remaining":
        finalize_full_corpus(
            output_root,
            completed_manifest,
            {item.source_path for item in queue.items},
        )
    return completed_manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, default=Path.cwd())
    parser.add_argument("--output-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--phase",
        choices=["queue", "calibration", "remaining", "status"],
        required=True,
    )
    args = parser.parse_args()
    result = run_full_corpus(
        args.config,
        args.source_root,
        args.output_root,
        args.phase,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

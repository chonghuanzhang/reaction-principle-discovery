"""Conservative, auditable relevance screening for the literature corpus."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from pipeline.api_client import ApiClientError, ApiResult, ResponsesClient
from pipeline.inventory import inventory_sources
from pipeline.models import DuplicateExclusion, PageRecord, SourceRecord
from pipeline.pdf_extract import extract_pages
from pipeline.prompt_builder import load_seed_context
from pipeline.run_pilot import _atomic_json, _configured_path, _default_client, _load_config


ScreeningCategory = Literal[
    "direct_precedent",
    "shared_reaction_manifold",
    "physical_organic_support",
    "failure_boundary",
    "unrelated",
    "uncertain",
]


class ScreeningInput(BaseModel):
    """Bounded local metadata supplied for one screening decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_path: str = Field(min_length=1)
    tier: str = Field(pattern=r"^tier_[1-4]$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    page_count: int = Field(ge=1)
    title_hint: str = Field(min_length=1)
    excerpt: str


class ScreeningDecision(BaseModel):
    """One validated relevance decision returned by the screening model."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    category: ScreeningCategory
    confidence: Literal["low", "medium", "high"]
    rationale: str = Field(min_length=1)
    matched_dimensions: list[str]

    @property
    def included(self) -> bool:
        """Retain every decision except a definite unrelated classification."""

        return self.category != "unrelated"


class ScreeningSummary(BaseModel):
    """Compact deterministic screening checkpoint."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    inventory_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    inventoried_pdf_count: int = Field(ge=0)
    unique_pdf_count: int = Field(ge=0)
    duplicate_count: int = Field(ge=0)
    completed_count: int = Field(ge=0)
    included_count: int = Field(ge=0)
    excluded_count: int = Field(ge=0)
    uncertain_count: int = Field(ge=0)
    category_counts: dict[str, int]
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)


def deduplicate_sources(
    sources: list[SourceRecord],
) -> tuple[list[SourceRecord], tuple[DuplicateExclusion, ...]]:
    """Retain the lexical-first source path for every PDF digest."""

    retained_by_sha: dict[str, SourceRecord] = {}
    exclusions: list[DuplicateExclusion] = []
    for source in sorted(sources, key=lambda item: item.source_path):
        retained = retained_by_sha.get(source.sha256)
        if retained is None:
            retained_by_sha[source.sha256] = source
            continue
        exclusions.append(
            DuplicateExclusion(
                excluded_path=source.source_path,
                retained_path=retained.source_path,
                sha256=source.sha256,
            )
        )
    retained_sources = sorted(retained_by_sha.values(), key=lambda item: item.source_path)
    return retained_sources, tuple(exclusions)


def _screening_record(
    source: SourceRecord,
    pages: list[PageRecord],
    max_characters: int,
) -> ScreeningInput:
    if max_characters < 1:
        raise ValueError("max_characters must be positive")
    remaining = max_characters
    pieces: list[str] = []
    for page in pages:
        if remaining == 0:
            break
        piece = page.text[:remaining]
        pieces.append(piece)
        remaining -= len(piece)
    return ScreeningInput(
        source_path=source.source_path,
        tier=source.tier,
        sha256=source.sha256,
        page_count=source.page_count or len(pages),
        title_hint=Path(source.source_path).stem,
        excerpt="".join(pieces),
    )


def build_screening_input(
    source: SourceRecord,
    pages: list[PageRecord],
    seed_context: dict[str, object],
    prompt_text: str,
    max_characters: int = 6000,
) -> str:
    """Build one bounded screening record with an explicit evidence boundary."""

    record = _screening_record(source, pages, max_characters)
    return (
        f"{prompt_text.strip()}\n\n"
        "PROJECT_CONTEXT_NOT_SOURCE_EVIDENCE\n"
        "Use this only to assess relevance. Never treat it as literature evidence.\n"
        f"{json.dumps(seed_context, ensure_ascii=False, sort_keys=True)}\n"
        "END_PROJECT_CONTEXT_NOT_SOURCE_EVIDENCE\n\n"
        "SCREENING_CONTENT_NOT_LITERATURE_EVIDENCE\n"
        f"{json.dumps(record.model_dump(mode='json'), ensure_ascii=False, sort_keys=True)}\n"
        "END_SCREENING_CONTENT_NOT_LITERATURE_EVIDENCE\n"
    )


class ScreeningError(RuntimeError):
    """A global screening failure that cannot be reduced to `uncertain`."""


def _cache_key(
    source: SourceRecord,
    model: str,
    prompt_text: str,
    schema: dict,
    seed_context: dict[str, object],
    max_characters: int,
) -> str:
    material = {
        "source_sha256": source.sha256,
        "model": model,
        "prompt": prompt_text,
        "schema": schema,
        "seed_context": seed_context,
        "max_characters": max_characters,
    }
    return hashlib.sha256(
        json.dumps(material, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def inventory_digest(
    sources: list[SourceRecord], exclusions: tuple[DuplicateExclusion, ...]
) -> str:
    payload = {
        "sources": [source.model_dump(mode="json") for source in sources],
        "duplicate_exclusions": [
            exclusion.model_dump(mode="json") for exclusion in exclusions
        ],
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _build_batch_input(
    records: list[ScreeningInput],
    seed_context: dict[str, object],
    prompt_text: str,
) -> str:
    return (
        f"{prompt_text.strip()}\n\n"
        "PROJECT_CONTEXT_NOT_SOURCE_EVIDENCE\n"
        "Use this only to assess relevance. Never treat it as literature evidence.\n"
        f"{json.dumps(seed_context, ensure_ascii=False, sort_keys=True)}\n"
        "END_PROJECT_CONTEXT_NOT_SOURCE_EVIDENCE\n\n"
        "SCREENING_RECORDS_JSON\n"
        f"{json.dumps([record.model_dump(mode='json') for record in records], ensure_ascii=False, sort_keys=True)}\n"
        "END_SCREENING_RECORDS_JSON\n"
    )


def _uncertain(source: SourceRecord, reason: str) -> ScreeningDecision:
    return ScreeningDecision(
        source_path=source.source_path,
        sha256=source.sha256,
        category="uncertain",
        confidence="low",
        rationale=reason[:500],
        matched_dimensions=[],
    )


def _decision_path(output_root: Path, source: SourceRecord) -> Path:
    return (
        output_root
        / "derived"
        / "screening"
        / "papers"
        / f"{source.tier}-{source.sha256[:12]}"
        / "decision.json"
    )


def _load_cached_decision(
    output_root: Path, source: SourceRecord, cache_key: str
) -> tuple[ScreeningDecision, dict] | None:
    path = _decision_path(output_root, source)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("cache_key") != cache_key:
            return None
        return ScreeningDecision.model_validate(payload["decision"]), payload
    except (json.JSONDecodeError, KeyError, ValueError):
        return None


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _csv_text(rows: list[dict[str, object]], fieldnames: list[str]) -> str:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


def _aggregate_outputs(
    output_root: Path,
    all_sources: list[SourceRecord],
    retained_sources: list[SourceRecord],
    duplicate_exclusions: tuple[DuplicateExclusion, ...],
    decisions: list[tuple[ScreeningDecision, dict]],
) -> dict:
    screening_root = output_root / "derived" / "screening"
    ordered = sorted(decisions, key=lambda item: item[0].source_path)
    rows: list[dict[str, object]] = []
    for decision, payload in ordered:
        rows.append(
            {
                **decision.model_dump(mode="json"),
                "included": decision.included,
                "matched_dimensions": " | ".join(decision.matched_dimensions),
                "response_id": payload.get("api", {}).get("response_id", ""),
                "returned_model": payload.get("api", {}).get("returned_model", ""),
                "batch_key": payload.get("batch_key", ""),
            }
        )
    jsonl = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
    )
    _write_text_atomic(screening_root / "corpus_screening.jsonl", jsonl)
    fields = [
        "source_path",
        "sha256",
        "category",
        "confidence",
        "included",
        "rationale",
        "matched_dimensions",
        "response_id",
        "returned_model",
        "batch_key",
    ]
    _write_text_atomic(
        screening_root / "corpus_screening.csv", _csv_text(rows, fields)
    )
    excluded = [row for row in rows if not row["included"]]
    _write_text_atomic(
        screening_root / "screening_exclusions.csv", _csv_text(excluded, fields)
    )

    category_counts = Counter(decision.category for decision, _ in ordered)
    referenced_batch_keys = {
        str(payload.get("batch_key"))
        for _, payload in ordered
        if payload.get("batch_key")
    }
    usage = Counter()
    for batch_key in referenced_batch_keys:
        batch_path = screening_root / "batches" / f"{batch_key}.json"
        if not batch_path.is_file():
            continue
        batch = json.loads(batch_path.read_text(encoding="utf-8"))
        for key in ("input_tokens", "output_tokens", "total_tokens"):
            usage[key] += int(batch.get("usage", {}).get(key) or 0)
    summary = ScreeningSummary(
        inventory_digest=inventory_digest(all_sources, duplicate_exclusions),
        inventoried_pdf_count=len(all_sources),
        unique_pdf_count=len(retained_sources),
        duplicate_count=len(duplicate_exclusions),
        completed_count=len(ordered),
        included_count=sum(decision.included for decision, _ in ordered),
        excluded_count=sum(not decision.included for decision, _ in ordered),
        uncertain_count=category_counts["uncertain"],
        category_counts=dict(sorted(category_counts.items())),
        input_tokens=usage["input_tokens"],
        output_tokens=usage["output_tokens"],
        total_tokens=usage["total_tokens"],
    ).model_dump(mode="json")
    _atomic_json(screening_root / "screening_summary.json", summary)
    _atomic_json(
        screening_root / "duplicate_exclusions.json",
        [item.model_dump(mode="json") for item in duplicate_exclusions],
    )
    return summary


def screen_corpus(
    config_path: Path,
    source_root: Path,
    output_root: Path,
    *,
    client: ResponsesClient | object | None = None,
) -> dict:
    """Screen every unique PDF with resumable conservative batch decisions."""

    config_path = config_path.resolve(strict=True)
    source_root = source_root.resolve(strict=True)
    output_root = output_root.resolve()
    config = _load_config(config_path)
    directories = {
        tier: Path(relative) for tier, relative in config["source_directories"].items()
    }
    all_sources = [
        source
        for source in inventory_sources(source_root, directories)
        if source.source_path.casefold().endswith(".pdf")
    ]
    retained_sources, duplicate_exclusions = deduplicate_sources(all_sources)
    prompt_path = _configured_path(
        config_path, config, "screening_prompt_path", "prompts/corpus_screening.md"
    )
    schema_path = _configured_path(
        config_path, config, "screening_schema_path", "screening_schema.json"
    )
    seed_path = _configured_path(
        config_path, config, "seed_context_path", "seed_reaction.yaml"
    )
    prompt_text = prompt_path.read_text(encoding="utf-8")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    seed_context = load_seed_context(seed_path)
    screening_config = config.get("screening", {})
    batch_size = int(screening_config.get("batch_size", 8))
    max_characters = int(screening_config.get("max_characters_per_paper", 6000))
    if not 1 <= batch_size <= 8:
        raise ScreeningError("screening.batch_size must be between 1 and 8")
    if max_characters < 1:
        raise ScreeningError("screening.max_characters_per_paper must be positive")
    model = str(config["model"])
    api = client or _default_client(model)

    decisions_by_sha: dict[str, tuple[ScreeningDecision, dict]] = {}
    pending: list[tuple[SourceRecord, str, ScreeningInput]] = []
    for source in retained_sources:
        key = _cache_key(
            source, model, prompt_text, schema, seed_context, max_characters
        )
        cached = _load_cached_decision(output_root, source, key)
        if cached is not None:
            decisions_by_sha[source.sha256] = cached
            continue
        try:
            pages = extract_pages(source_root / source.source_path)
            record = _screening_record(source, pages, max_characters)
        except Exception as exc:
            decision = _uncertain(
                source, f"Local PDF screening preparation failed: {type(exc).__name__}."
            )
            payload = {
                "cache_key": key,
                "decision": decision.model_dump(mode="json"),
                "api": {},
                "batch_key": "",
            }
            _atomic_json(_decision_path(output_root, source), payload)
            decisions_by_sha[source.sha256] = (decision, payload)
            continue
        pending.append((source, key, record))

    for offset in range(0, len(pending), batch_size):
        batch = pending[offset : offset + batch_size]
        records = [record for _, _, record in batch]
        batch_material = [key for _, key, _ in batch]
        batch_key = hashlib.sha256(
            json.dumps(batch_material, sort_keys=True).encode("utf-8")
        ).hexdigest()
        result: ApiResult | None = None
        failure_reason: str | None = None
        try:
            result = api.create_structured(
                model,
                _build_batch_input(records, seed_context, prompt_text),
                schema,
                "corpus_relevance_screening",
            )
        except ApiClientError as exc:
            if exc.status in {401, 403}:
                raise ScreeningError(str(exc)) from exc
            failure_reason = f"Screening API failure: {exc.error_type or 'unknown'}."
        except Exception as exc:
            failure_reason = f"Screening API failure: {type(exc).__name__}."

        returned: dict[tuple[str, str], ScreeningDecision] = {}
        if result is not None:
            for raw in result.parsed_output.get("decisions", []):
                try:
                    decision = ScreeningDecision.model_validate(raw)
                except ValueError:
                    continue
                returned[(decision.source_path, decision.sha256)] = decision
            _atomic_json(
                output_root
                / "derived"
                / "screening"
                / "batches"
                / f"{batch_key}.json",
                {
                    "batch_key": batch_key,
                    "response_id": result.response_id,
                    "returned_model": result.returned_model,
                    "status": result.status,
                    "source_sha256s": [source.sha256 for source, _, _ in batch],
                    "usage": {
                        "input_tokens": result.usage.input_tokens,
                        "output_tokens": result.usage.output_tokens,
                        "total_tokens": result.usage.total_tokens,
                    },
                },
            )
        for source, key, _ in batch:
            decision = returned.get((source.source_path, source.sha256))
            if decision is None:
                decision = _uncertain(
                    source,
                    failure_reason
                    or "The screening response omitted or invalidated this source.",
                )
            payload = {
                "cache_key": key,
                "decision": decision.model_dump(mode="json"),
                "api": (
                    {
                        "response_id": result.response_id,
                        "returned_model": result.returned_model,
                        "status": result.status,
                    }
                    if result is not None
                    else {}
                ),
                "batch_key": batch_key if result is not None else "",
            }
            _atomic_json(_decision_path(output_root, source), payload)
            decisions_by_sha[source.sha256] = (decision, payload)
        completed_decisions = [
            decisions_by_sha[source.sha256]
            for source in retained_sources
            if source.sha256 in decisions_by_sha
        ]
        _aggregate_outputs(
            output_root,
            all_sources,
            retained_sources,
            duplicate_exclusions,
            completed_decisions,
        )

    ordered_decisions = [
        decisions_by_sha[source.sha256] for source in retained_sources
    ]
    return _aggregate_outputs(
        output_root,
        all_sources,
        retained_sources,
        duplicate_exclusions,
        ordered_decisions,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    summary = screen_corpus(args.config, args.source_root, args.output_root)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()

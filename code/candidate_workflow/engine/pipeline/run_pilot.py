"""Resumable orchestration for the four-paper evidence pilot."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import yaml

from pipeline.api_client import (
    DEFAULT_READ_TIMEOUT_SECONDS,
    ApiResult,
    ResponsesClient,
    read_keychain_secret,
)
from pipeline.grounding import build_source_spans, ground_extraction
from pipeline.inventory import inventory_sources, sha256_file, write_inventory
from pipeline.models import CandidateRecord, PageChunk, SelectionAudit, SourceRecord
from pipeline.pdf_extract import extract_pages
from pipeline.pilot_select import select_pilot, write_selection_audit
from pipeline.prompt_builder import (
    build_extraction_input,
    build_page_chunks,
    load_seed_context,
)
from pipeline.render import render_pages
from pipeline.review import write_review_markdown
from pipeline.validate import validate_extraction


class PilotRunError(RuntimeError):
    """Failure that leaves previously validated records unchanged."""


@dataclass(frozen=True)
class RunManifest:
    run_id: str
    started_at: str
    completed_at: str
    model: str
    selected_paper_count: int
    api_call_count: int
    reused_paper_count: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    paper_statuses: dict[str, str]


def _atomic_json(output: Path, payload: object) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    try:
        with temporary.open("wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


def _load_config(config_path: Path) -> dict:
    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise PilotRunError("Pilot configuration must contain a mapping.")
    return loaded


def _configured_path(config_path: Path, config: dict, key: str, default: str) -> Path:
    value = Path(str(config.get(key, default)))
    return value if value.is_absolute() else config_path.parent / value


def _candidate_from_source(source_root: Path, source: SourceRecord) -> CandidateRecord:
    pages = extract_pages(source_root / source.source_path)
    searchable_text = "\n".join(page.text for page in pages)
    return CandidateRecord(
        source_path=source.source_path,
        tier=source.tier,
        sha256=source.sha256,
        page_count=len(pages),
        searchable_character_count=sum(page.character_count for page in pages),
        searchable_text=searchable_text,
        visual_page_count=sum(bool(page.visual_review_reasons) for page in pages),
    )


def _cache_key(
    source: SourceRecord,
    model: str,
    prompt_text: str,
    schema: dict,
    config: dict,
    seed_context: dict[str, object] | None = None,
) -> str:
    material = {
        "source_sha256": source.sha256,
        "model": model,
        "prompt": prompt_text,
        "schema": schema,
        "schema_version": config["schema_version"],
        "prompt_version": config["prompt_version"],
        "max_chunk_characters": config["max_chunk_characters"],
        "seed_context": seed_context,
    }
    encoded = json.dumps(material, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _default_client(
    model: str,
    *,
    read_timeout_seconds: int = DEFAULT_READ_TIMEOUT_SECONDS,
) -> ResponsesClient:
    del model
    return ResponsesClient(
        "https://cs.jaspervault.pro/v1",
        lambda: read_keychain_secret("reaction-principle-jaspervault", os.environ["USER"]),
        read_timeout_seconds=read_timeout_seconds,
    )


def _prepare_selection(
    config: dict,
    source_root: Path,
    output_root: Path,
) -> tuple[list[SourceRecord], SelectionAudit]:
    directories = {
        tier: Path(relative)
        for tier, relative in config["source_directories"].items()
    }
    sources = [
        source
        for source in inventory_sources(source_root, directories)
        if source.source_path.casefold().endswith(".pdf")
    ]
    write_inventory(sources, output_root / "derived" / "inventory" / "pilot_sources.json")
    candidates = [_candidate_from_source(source_root, source) for source in sources]
    audit = select_pilot(candidates, config["selection"])
    write_selection_audit(audit, output_root / "derived" / "pilot" / "selection.json")
    return sources, audit


def run_pilot(
    config_path: Path,
    source_root: Path,
    output_root: Path,
    *,
    client: ResponsesClient | object | None = None,
    resume: bool = True,
    select_only: bool = False,
    tiers: set[str] | None = None,
) -> RunManifest:
    """Select and extract one paper per Tier with atomic validated outputs."""

    started = datetime.now(UTC)
    run_id = started.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    config_path = config_path.resolve()
    source_root = source_root.resolve(strict=True)
    output_root = output_root.resolve()
    config = _load_config(config_path)
    schema_path = _configured_path(config_path, config, "schema_path", "extraction_schema.json")
    prompt_path = _configured_path(
        config_path, config, "prompt_path", "prompts/evidence_extraction.md"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    prompt_text = prompt_path.read_text(encoding="utf-8")
    seed_context_path = _configured_path(
        config_path, config, "seed_context_path", "seed_reaction.yaml"
    )
    seed_context = load_seed_context(seed_context_path)
    sources, audit = _prepare_selection(config, source_root, output_root)
    if len(audit.selected) != 4:
        raise PilotRunError(f"Expected four selected Tiers, found {len(audit.selected)}.")
    if select_only:
        completed = datetime.now(UTC)
        return RunManifest(
            run_id=run_id,
            started_at=started.isoformat(),
            completed_at=completed.isoformat(),
            model=str(config["model"]),
            selected_paper_count=4,
            api_call_count=0,
            reused_paper_count=0,
            input_tokens=0,
            output_tokens=0,
            total_tokens=0,
            paper_statuses={item.source_path: "selected" for item in audit.selected},
        )

    source_by_path = {source.source_path: source for source in sources}
    api = client or _default_client(str(config["model"]))
    calls = reused = input_tokens = output_tokens = total_tokens = 0
    statuses: dict[str, str] = {}
    for selected in audit.selected:
        if tiers is not None and selected.tier not in tiers:
            statuses[selected.source_path] = "not_requested"
            continue
        source = source_by_path[selected.source_path]
        source_path = source_root / source.source_path
        if sha256_file(source_path) != source.sha256:
            raise PilotRunError(f"Source changed after selection: {source.source_path}")
        paper_dir = output_root / "derived" / "pilot" / f"{source.tier}-{source.sha256[:12]}"
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
                reused += 1
                statuses[source.source_path] = "reused"
                continue
        pages = extract_pages(source_path)
        chunks = build_page_chunks(pages, int(config["max_chunk_characters"]))
        if len(chunks) != 1:
            raise PilotRunError(
                f"Pilot paper requires {len(chunks)} chunks; increase the audited pilot chunk limit "
                f"or implement reviewed chunk merging: {source.source_path}"
            )
        extraction_input = build_extraction_input(
            source, chunks[0], prompt_text, seed_context=seed_context
        )
        try:
            result: ApiResult = api.create_structured(
                str(config["model"]),
                extraction_input,
                schema,
                "paper_evidence_extraction",
            )
        except Exception as exc:
            statuses[source.source_path] = "failed"
            raise PilotRunError(f"Extraction failed for {source.source_path}: {exc}") from exc
        calls += 1
        input_tokens += result.usage.input_tokens or 0
        output_tokens += result.usage.output_tokens or 0
        total_tokens += result.usage.total_tokens or 0
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
            grounded_output, grounding_changes = ground_extraction(
                result.parsed_output, build_source_spans(pages)
            )
        except ValueError as exc:
            _atomic_json(
                paper_dir / "grounding_failed.json",
                {"cache_key": key, "message": str(exc)},
            )
            raise PilotRunError(f"Source grounding failed for {source.source_path}: {exc}") from exc
        validation = validate_extraction(grounded_output, pages, source, schema)
        if not validation.is_valid:
            _atomic_json(
                paper_dir / "validation_failed.json",
                {"cache_key": key, "validation": validation.model_dump(mode="json")},
            )
            raise PilotRunError(f"Local validation failed for {source.source_path}")
        reviewed_pages = sorted(
            set(grounded_output["visual_review_pages"])
            | {
                page.pdf_page
                for page in pages
                if page.visual_review_reasons
            }
        )
        render_pages(source_path, reviewed_pages, output_root / "tmp" / "pdfs" / run_id / paper_dir.name)
        write_review_markdown(grounded_output, validation, paper_dir / "review.md")
        validated_payload = {
            "cache_key": key,
            "validation": validation.model_dump(mode="json"),
            "extraction": grounded_output,
            "grounding": {"changes": grounding_changes},
        }
        _atomic_json(validated_path, validated_payload)
        statuses[source.source_path] = "validated"

    completed = datetime.now(UTC)
    manifest = RunManifest(
        run_id=run_id,
        started_at=started.isoformat(),
        completed_at=completed.isoformat(),
        model=str(config["model"]),
        selected_paper_count=len(audit.selected),
        api_call_count=calls,
        reused_paper_count=reused,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        paper_statuses=statuses,
    )
    _atomic_json(output_root / "runs" / run_id / "manifest.json", asdict(manifest))
    return manifest


def revalidate_cached_raw(
    config_path: Path,
    source_root: Path,
    output_root: Path,
    *,
    tiers: set[str] | None = None,
) -> dict[str, str]:
    """Apply current deterministic grounding and validation to cached raw output."""

    config_path = config_path.resolve()
    source_root = source_root.resolve(strict=True)
    output_root = output_root.resolve()
    config = _load_config(config_path)
    schema_path = _configured_path(config_path, config, "schema_path", "extraction_schema.json")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    sources, audit = _prepare_selection(config, source_root, output_root)
    source_by_path = {source.source_path: source for source in sources}
    statuses: dict[str, str] = {}
    revalidation_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    for selected in audit.selected:
        if tiers is not None and selected.tier not in tiers:
            continue
        source = source_by_path[selected.source_path]
        source_path = source_root / source.source_path
        if sha256_file(source_path) != source.sha256:
            raise PilotRunError(f"Source changed before revalidation: {source.source_path}")
        paper_dir = output_root / "derived" / "pilot" / f"{source.tier}-{source.sha256[:12]}"
        raw_path = paper_dir / "raw.json"
        if not raw_path.is_file():
            raise PilotRunError(f"Cached raw extraction is unavailable: {source.source_path}")
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        pages = extract_pages(source_path)
        try:
            grounded, grounding_changes = ground_extraction(
                raw["extraction"], build_source_spans(pages)
            )
        except ValueError as exc:
            raise PilotRunError(f"Source grounding failed for {source.source_path}: {exc}") from exc
        validation = validate_extraction(grounded, pages, source, schema)
        if not validation.is_valid:
            _atomic_json(
                paper_dir / "validation_failed.json",
                {
                    "cache_key": raw.get("cache_key"),
                    "validation": validation.model_dump(mode="json"),
                },
            )
            raise PilotRunError(f"Cached extraction remains invalid: {source.source_path}")
        reviewed_pages = sorted(
            set(grounded["visual_review_pages"])
            | {page.pdf_page for page in pages if page.visual_review_reasons}
        )
        render_pages(
            source_path,
            reviewed_pages,
            output_root / "tmp" / "pdfs" / revalidation_id / paper_dir.name,
        )
        write_review_markdown(grounded, validation, paper_dir / "review.md")
        _atomic_json(
            paper_dir / "validated.json",
            {
                "cache_key": raw.get("cache_key"),
                "validation": validation.model_dump(mode="json"),
                "extraction": grounded,
                "revalidation": {
                    "revalidation_id": revalidation_id,
                    "grounding_changes": grounding_changes,
                },
            },
        )
        statuses[source.source_path] = "revalidated"
    return statuses


def verify_sources(config_path: Path, source_root: Path, output_root: Path) -> None:
    """Recompute configured source checksums and compare with the pilot inventory."""

    config = _load_config(config_path)
    directories = {
        tier: Path(relative)
        for tier, relative in config["source_directories"].items()
    }
    current = [
        source
        for source in inventory_sources(source_root, directories)
        if source.source_path.casefold().endswith(".pdf")
    ]
    baseline_path = output_root / "derived" / "inventory" / "pilot_sources.json"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    current_pairs = {(item.source_path, item.sha256) for item in current}
    baseline_pairs = {(item["source_path"], item["sha256"]) for item in baseline}
    if current_pairs != baseline_pairs:
        raise PilotRunError("Configured source inventory differs from the pilot baseline.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, default=Path.cwd())
    parser.add_argument("--output-root", type=Path, default=Path.cwd())
    parser.add_argument("--select-only", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--revalidate-only", action="store_true")
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument(
        "--tiers",
        nargs="+",
        choices=["tier_1", "tier_2", "tier_3", "tier_4"],
        help="Process only the requested Tiers while preserving the four-Tier selection audit.",
    )
    args = parser.parse_args()
    if args.verify_only:
        verify_sources(args.config, args.source_root, args.output_root)
        print("Source verification passed.")
        return
    if args.revalidate_only:
        statuses = revalidate_cached_raw(
            args.config,
            args.source_root,
            args.output_root,
            tiers=set(args.tiers) if args.tiers else None,
        )
        print(json.dumps(statuses, ensure_ascii=False, indent=2, sort_keys=True))
        return
    manifest = run_pilot(
        args.config,
        args.source_root,
        args.output_root,
        resume=not args.no_resume,
        select_only=args.select_only,
        tiers=set(args.tiers) if args.tiers else None,
    )
    print(json.dumps(asdict(manifest), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

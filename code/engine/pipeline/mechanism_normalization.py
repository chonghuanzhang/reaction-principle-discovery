"""Normalize validated paper evidence into reusable mechanistic units."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, ValidationError

from pipeline.api_client import ApiResult
from pipeline.evidence_registry import _atomic_json
from pipeline.principle_models import (
    BoundaryConstraint,
    MechanismEvidence,
    SourceRevisitRequest,
)


class StructuredClient(Protocol):
    def create_structured(
        self,
        model: str,
        input_text: str,
        schema: dict,
        schema_name: str,
    ) -> ApiResult: ...


class MechanismNormalizationError(RuntimeError):
    """Raised when model output cannot be grounded to validated evidence."""


class MechanismNormalizationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mechanism_evidence: list[MechanismEvidence]
    boundary_constraints: list[BoundaryConstraint]
    source_revisit_requests: list[SourceRevisitRequest]


class NormalizationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["validated", "reused"]
    cache_key: str
    source_file: str
    mechanism_evidence: tuple[MechanismEvidence, ...]
    boundary_constraints: tuple[BoundaryConstraint, ...]
    source_revisit_requests: tuple[SourceRevisitRequest, ...]
    usage: dict[str, int | None]


_ALLOWED_EXTRACTION_FIELDS = (
    "paper_id",
    "source_file",
    "sha256",
    "primary_tier",
    "secondary_tiers",
    "evidence_types",
    "reaction_summary",
    "evidence_items",
    "uncertainties",
    "contradictions",
    "visual_review_pages",
    "review_status",
)


def _extraction(record: dict) -> dict:
    extraction = record.get("extraction")
    if not isinstance(extraction, dict):
        raise MechanismNormalizationError("validated record lacks extraction object")
    return extraction


def build_normalization_input(record: dict, prompt_text: str) -> str:
    """Build an allowlisted input that cannot include hidden project results."""

    extraction = _extraction(record)
    allowed = {
        field: extraction[field]
        for field in _ALLOWED_EXTRACTION_FIELDS
        if field in extraction
    }
    return (
        f"{prompt_text.strip()}\n\n"
        "BEGIN_VALIDATED_LITERATURE_RECORD\n"
        f"{json.dumps(allowed, ensure_ascii=False, sort_keys=True)}\n"
        "END_VALIDATED_LITERATURE_RECORD\n"
    )


def normalization_schema() -> dict:
    return MechanismNormalizationPayload.model_json_schema()


def _cache_key(record: dict, config: dict) -> str:
    extraction = _extraction(record)
    payload = {
        "source_sha256": extraction.get("sha256"),
        "literature_cache_key": record.get("cache_key"),
        "model": config.get("model"),
        "prompt_version": config.get("prompt_version"),
        "schema_version": config.get("schema_version"),
        "prompt_text": config.get("prompt_text"),
        "schema": normalization_schema(),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _authoritative_evidence(extraction: dict) -> dict[str, dict]:
    items = extraction.get("evidence_items")
    if not isinstance(items, list):
        raise MechanismNormalizationError("validated extraction lacks evidence_items")
    indexed: dict[str, dict] = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("evidence_id"), str):
            raise MechanismNormalizationError("validated evidence item lacks evidence_id")
        indexed[item["evidence_id"]] = item
    return indexed


def _ground_payload(payload: MechanismNormalizationPayload, extraction: dict) -> MechanismNormalizationPayload:
    source_items = _authoritative_evidence(extraction)
    span_sources: dict[str, list[str]] = {}
    for evidence_id, item in source_items.items():
        for span_id in item.get("source_span_ids", []):
            if isinstance(span_id, str):
                span_sources.setdefault(span_id, []).append(evidence_id)
    contradiction_spans = {
        span_id
        for statement in extraction.get("contradictions", [])
        if isinstance(statement, str)
        for span_id in re.findall(r"P\d+-S\d+", statement)
    }
    grounded_mechanisms: list[MechanismEvidence] = []
    mechanism_sources: dict[str, tuple[str, ...]] = {}
    for mechanism in payload.mechanism_evidence:
        missing = [item for item in mechanism.source_evidence_ids if item not in source_items]
        if missing:
            raise MechanismNormalizationError(
                f"unknown source evidence ID(s): {', '.join(missing)}"
            )
        mechanism_sources[mechanism.mechanism_evidence_id] = mechanism.source_evidence_ids
        first = source_items[mechanism.source_evidence_ids[0]]
        grounded_mechanisms.append(
            mechanism.model_copy(
                update={
                    "source_paper_id": str(extraction.get("paper_id", "")),
                    "quotation": first.get("quotation"),
                    "pdf_page": first.get("pdf_page"),
                }
            )
        )

    def source_ids(references: tuple[str, ...]) -> tuple[str, ...]:
        resolved: list[str] = []
        for reference in references:
            if reference in source_items:
                resolved.append(reference)
            elif reference in mechanism_sources:
                resolved.extend(mechanism_sources[reference])
            elif reference in span_sources:
                resolved.extend(span_sources[reference])
            elif reference in contradiction_spans:
                resolved.append(reference)
            else:
                raise MechanismNormalizationError(f"unknown source evidence ID(s): {reference}")
        return tuple(dict.fromkeys(resolved))

    grounded_constraints = [
        constraint.model_copy(
            update={
                "supporting_evidence_ids": source_ids(constraint.supporting_evidence_ids),
                "contradictory_evidence_ids": source_ids(constraint.contradictory_evidence_ids),
            }
        )
        for constraint in payload.boundary_constraints
    ]

    return MechanismNormalizationPayload(
        mechanism_evidence=grounded_mechanisms,
        boundary_constraints=grounded_constraints,
        source_revisit_requests=payload.source_revisit_requests,
    )


def _load_cached(path: Path, expected_key: str) -> NormalizationResult | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("cache_key") != expected_key:
        return None
    try:
        parsed = MechanismNormalizationPayload.model_validate(payload.get("normalization"))
    except ValidationError:
        return None
    return NormalizationResult(
        status="reused",
        cache_key=expected_key,
        source_file=str(payload.get("source_file", "")),
        mechanism_evidence=tuple(parsed.mechanism_evidence),
        boundary_constraints=tuple(parsed.boundary_constraints),
        source_revisit_requests=tuple(parsed.source_revisit_requests),
        usage={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
    )


def normalize_record(
    record: dict,
    client: StructuredClient,
    config: dict,
    cache_root: Path,
) -> NormalizationResult:
    """Normalize one record, preserving raw output and reusing valid caches."""

    extraction = _extraction(record)
    source_file = str(extraction.get("source_file", ""))
    source_sha = str(extraction.get("sha256", ""))
    key = _cache_key(record, config)
    paper_dir = cache_root.resolve() / source_sha[:12]
    validated_path = paper_dir / "validated.json"
    cached = _load_cached(validated_path, key)
    if cached is not None:
        return cached

    input_text = build_normalization_input(record, str(config.get("prompt_text", "")))
    api_result = client.create_structured(
        str(config.get("model", "")),
        input_text,
        normalization_schema(),
        "mechanism_normalization",
    )
    raw_payload = {
        "cache_key": key,
        "source_file": source_file,
        "api": {
            "response_id": api_result.response_id,
            "returned_model": api_result.returned_model,
            "status": api_result.status,
            "usage": asdict(api_result.usage),
        },
        "normalization": api_result.parsed_output,
    }
    _atomic_json(paper_dir / "raw.json", raw_payload)

    try:
        parsed = MechanismNormalizationPayload.model_validate(api_result.parsed_output)
        grounded = _ground_payload(parsed, extraction)
    except ValidationError as exc:
        raise MechanismNormalizationError(f"invalid normalization schema: {exc}") from exc

    usage = asdict(api_result.usage)
    validated_payload = {
        "cache_key": key,
        "source_file": source_file,
        "source_sha256": source_sha,
        "normalization": grounded.model_dump(mode="json"),
        "usage": usage,
    }
    _atomic_json(validated_path, validated_payload)
    return NormalizationResult(
        status="validated",
        cache_key=key,
        source_file=source_file,
        mechanism_evidence=tuple(grounded.mechanism_evidence),
        boundary_constraints=tuple(grounded.boundary_constraints),
        source_revisit_requests=tuple(grounded.source_revisit_requests),
        usage=usage,
    )


def write_normalization_schema(path: Path) -> None:
    _atomic_json(path, normalization_schema())

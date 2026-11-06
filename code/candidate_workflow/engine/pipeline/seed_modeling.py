"""High-resolution, hidden-answer-safe modeling of the Seed Reaction."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Literal, Protocol
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from pydantic import BaseModel, ConfigDict, ValidationError

from pipeline.api_client import ApiResult
from pipeline.evidence_registry import _atomic_json
from pipeline.principle_models import SeedEvidence, SeedMechanism, SeedPrinciple
from pipeline.seed_inputs import SeedInputInventory, assert_principle_building_safe


class StructuredClient(Protocol):
    def create_structured(
        self, model: str, input_text: str, schema: dict, schema_name: str
    ) -> ApiResult: ...


class SeedModelPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seed_evidence: list[SeedEvidence]
    seed_mechanism: SeedMechanism
    seed_principle: SeedPrinciple


class SeedModelingResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["validated", "reused"]
    cache_key: str
    seed_evidence: tuple[SeedEvidence, ...]
    seed_mechanism: SeedMechanism
    seed_principle: SeedPrinciple
    usage: dict[str, int | None]


class SeedModelingError(RuntimeError):
    """Raised when Seed output is ungrounded or crosses an access boundary."""


def _docx_paragraphs(path: Path) -> list[str]:
    try:
        with ZipFile(path) as archive:
            xml = archive.read("word/document.xml")
    except (BadZipFile, KeyError, OSError) as exc:
        raise SeedModelingError(f"cannot parse allowlisted DOCX seed source: {path}") from exc
    root = ElementTree.fromstring(xml)
    paragraphs: list[str] = []
    for element in root.iter():
        if not element.tag.endswith("}p"):
            continue
        text = "".join(
            node.text or "" for node in element.iter() if node.tag.endswith("}t")
        ).strip()
        if text:
            paragraphs.append(text)
    return paragraphs


def _source_paragraphs(inventory: SeedInputInventory) -> dict[str, dict[str, str]]:
    assert_principle_building_safe(inventory)
    source_root = Path(inventory.source_root).resolve()
    result: dict[str, dict[str, str]] = {}
    for item in inventory.principle_building_files:
        path = (source_root / item.path).resolve()
        try:
            path.relative_to(source_root)
        except ValueError as exc:
            raise SeedModelingError(f"seed source escapes inventory root: {item.path}") from exc
        if path.suffix.lower() != ".docx":
            raise SeedModelingError(
                f"unsupported principle-building seed source format: {item.path}"
            )
        result[item.path] = {
            f"paragraph:{index:04d}": text
            for index, text in enumerate(_docx_paragraphs(path), start=1)
        }
    if not result:
        raise SeedModelingError("no principle-building seed sources were allowlisted")
    return result


def build_seed_input(inventory: SeedInputInventory, prompt_text: str) -> str:
    """Build a paragraph-addressable prompt from allowlisted Seed sources only."""

    sources = _source_paragraphs(inventory)
    sections: list[str] = []
    for source_id, paragraphs in sorted(sources.items()):
        lines = [f"[[{locator}]] {text}" for locator, text in paragraphs.items()]
        sections.append(
            f"BEGIN_SEED_SOURCE {source_id}\n"
            + "\n".join(lines)
            + f"\nEND_SEED_SOURCE {source_id}"
        )
    return (
        f"{prompt_text.strip()}\n\n"
        "Use only the allowlisted first-party Seed sources below. Preserve facts, "
        "hypotheses, inferences, and unknowns as distinct evidence labels. Every "
        "Seed evidence item must quote one exact paragraph and cite its source_id "
        "and paragraph locator. Do not infer hidden experimental outcomes.\n\n"
        + "\n\n".join(sections)
        + "\n"
    )


def seed_model_schema() -> dict:
    schema = SeedModelPayload.model_json_schema()
    _require_all_properties(schema)
    return schema


def _require_all_properties(node: object) -> None:
    if isinstance(node, dict):
        properties = node.get("properties")
        if isinstance(properties, dict):
            node["required"] = list(properties)
            node["additionalProperties"] = False
        for value in node.values():
            _require_all_properties(value)
    elif isinstance(node, list):
        for value in node:
            _require_all_properties(value)


def _cache_key(inventory: SeedInputInventory, config: dict) -> str:
    payload = {
        "principle_building_digest": inventory.principle_building_digest,
        "model": config.get("model"),
        "prompt_text": config.get("prompt_text"),
        "prompt_version": config.get("prompt_version"),
        "schema": seed_model_schema(),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _ground_payload(
    payload: SeedModelPayload, inventory: SeedInputInventory
) -> SeedModelPayload:
    sources = _source_paragraphs(inventory)
    known_ids: set[str] = set()
    for item in payload.seed_evidence:
        reference = item.evidence
        if reference.evidence_id in known_ids:
            raise SeedModelingError(f"duplicate Seed evidence ID: {reference.evidence_id}")
        known_ids.add(reference.evidence_id)
        paragraphs = sources.get(reference.source_id)
        paragraph = paragraphs.get(reference.locator or "") if paragraphs else None
        quotation = " ".join((reference.quotation or "").split())
        normalized_paragraph = " ".join((paragraph or "").split())
        if not paragraph or not quotation or quotation not in normalized_paragraph:
            raise SeedModelingError(
                f"Seed evidence quotation is not grounded at {reference.source_id} "
                f"{reference.locator}"
            )
    mechanism_unknown = sorted(set(payload.seed_mechanism.evidence_ids) - known_ids)
    principle_unknown = sorted(
        set(payload.seed_principle.supporting_seed_evidence) - known_ids
    )
    if mechanism_unknown or principle_unknown:
        unknown = sorted(set(mechanism_unknown) | set(principle_unknown))
        raise SeedModelingError("unknown Seed evidence references: " + ", ".join(unknown))
    return payload


def _cached(path: Path, key: str) -> SeedModelingResult | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        payload = SeedModelPayload.model_validate(
            {
                "seed_evidence": value.get("seed_evidence"),
                "seed_mechanism": value.get("seed_mechanism"),
                "seed_principle": value.get("seed_principle"),
            }
        )
    except (OSError, json.JSONDecodeError, ValidationError):
        return None
    if value.get("cache_key") != key:
        return None
    return SeedModelingResult(
        status="reused",
        cache_key=key,
        seed_evidence=tuple(payload.seed_evidence),
        seed_mechanism=payload.seed_mechanism,
        seed_principle=payload.seed_principle,
        usage={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
    )


def model_seed_reaction(
    inventory: SeedInputInventory,
    client: StructuredClient,
    config: dict,
    cache_root: Path,
) -> SeedModelingResult:
    """Extract and synthesize one grounded Seed model with immutable raw cache."""

    key = _cache_key(inventory, config)
    run_root = cache_root.resolve() / key
    validated_path = run_root / "validated.json"
    cached = _cached(validated_path, key)
    if cached is not None:
        return cached
    api_result = client.create_structured(
        str(config.get("model", "")),
        build_seed_input(inventory, str(config.get("prompt_text", ""))),
        seed_model_schema(),
        "seed_reaction_model",
    )
    raw = {
        "cache_key": key,
        "api": {
            "response_id": api_result.response_id,
            "returned_model": api_result.returned_model,
            "status": api_result.status,
            "usage": asdict(api_result.usage),
        },
        "model_output": api_result.parsed_output,
    }
    _atomic_json(run_root / "raw.json", raw)
    try:
        parsed = SeedModelPayload.model_validate(api_result.parsed_output)
        grounded = _ground_payload(parsed, inventory)
    except ValidationError as exc:
        raise SeedModelingError(f"invalid Seed model schema: {exc}") from exc
    usage = asdict(api_result.usage)
    validated = {
        "cache_key": key,
        **grounded.model_dump(mode="json"),
        "usage": usage,
    }
    _atomic_json(validated_path, validated)
    return SeedModelingResult(
        status="validated",
        cache_key=key,
        seed_evidence=tuple(grounded.seed_evidence),
        seed_mechanism=grounded.seed_mechanism,
        seed_principle=grounded.seed_principle,
        usage=usage,
    )

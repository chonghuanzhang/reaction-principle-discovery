"""Conservatively screen Tier 2-4 supplement candidates from title and abstract."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from pipeline.api_client import ChatCompletionsStructuredClient, read_keychain_secret
from pipeline.evidence_registry import _atomic_json
from pipeline.principle_models import FrozenStrictModel


Tier = Literal["tier_2", "tier_3", "tier_4"]
Decision = Literal["include", "exclude", "uncertain"]
Confidence = Literal["low", "medium", "high"]
EvidenceLevel = Literal["metadata_screening", "abstract_screening"]
Priority = Literal["none", "low", "medium", "high"]


TIER_DEFINITIONS = {
    "tier_2": (
        "Selective fluorine loss, fluorinated-alkene reaction manifolds, "
        "carbon-fluorine activation, beta-fluoride elimination, and subsequent "
        "bond formation or trapping."
    ),
    "tier_3": (
        "Physical-organic evidence for nucleophilicity or electrophilicity, "
        "acid-base state, ion pairing, solvent effects, hard-soft behavior, "
        "ambident selectivity, catalyst coordination, or reaction selectivity."
    ),
    "tier_4": (
        "Explicit failure-boundary evidence involving excessive fluorine loss, "
        "catalyst poisoning or inhibition, oxidation, decomposition, competing "
        "pathways, or condition incompatibility."
    ),
}


class AbstractDecision(FrozenStrictModel):
    """One abstract-level screening decision; never decision-grade evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str = Field(min_length=1)
    decision: Decision
    primary_tier: Tier
    confidence: Confidence
    evidence_roles: list[str]
    transferable_steps: list[str]
    condition_signals: list[str]
    failure_boundary_signals: list[str]
    rationale: str = Field(min_length=1)
    limitations: list[str]
    evidence_level: EvidenceLevel
    full_text_priority: Priority
    full_text_reasons: list[str]

    @model_validator(mode="after")
    def enforce_screening_boundary(self) -> "AbstractDecision":
        if self.evidence_level not in {"metadata_screening", "abstract_screening"}:
            raise ValueError("abstract decisions are screening evidence only")
        if self.decision == "exclude" and self.full_text_priority == "high":
            raise ValueError("excluded records cannot have high full-text priority")
        return self


class AbstractDecisionBatch(FrozenStrictModel):
    decisions: list[AbstractDecision]


SCREENING_INSTRUCTIONS = """
You are screening literature for a blinded, general reaction-principle workflow.
Use only the supplied title, abstract, and proposed Tier definitions. Do not
invent chemical facts or treat the project objective as source evidence.

Classify every record as include, exclude, or uncertain. Include a paper only
when the supplied abstract supports at least one proposed Tier. Use uncertain
when the abstract is absent or too vague. A review can be included when it
contains useful mechanistic or physical-organic scope, but mark the limitation.

Record evidence roles, transferable elementary steps or rules, reported
condition signals, and any failure-boundary signals using only abstract wording.
Abstract signals are screening evidence, never hard incompatibility or formal
negative evidence. Unknown must remain unknown. Use full-text priority high only
when the paper could materially affect a reaction principle, a family ranking,
a critical condition, or a negative boundary. Choose primary_tier only from the
record's prefilter_tiers. Do not infer or recommend named target substrates.
""".strip()


def _screening_record(candidate: dict[str, object]) -> dict[str, object]:
    return {
        "candidate_id": candidate["candidate_id"],
        "doi": candidate.get("doi"),
        "title": candidate.get("title"),
        "abstract": candidate.get("abstract"),
        "prefilter_tiers": candidate.get("prefilter_tiers", []),
        "tier_definitions": {
            tier: TIER_DEFINITIONS[tier]
            for tier in candidate.get("prefilter_tiers", [])
            if tier in TIER_DEFINITIONS
        },
    }


def build_batch_prompt(candidates: list[dict[str, object]]) -> str:
    records = [_screening_record(candidate) for candidate in candidates]
    return (
        SCREENING_INSTRUCTIONS
        + "\n\nSCREENING_RECORDS_JSON\n"
        + json.dumps(records, ensure_ascii=False, sort_keys=True)
        + "\nEND_SCREENING_RECORDS_JSON"
    )


def validate_batch_decisions(
    candidates: list[dict[str, object]], decisions: list[AbstractDecision]
) -> None:
    expected = [str(candidate["candidate_id"]) for candidate in candidates]
    actual = [decision.candidate_id for decision in decisions]
    if len(actual) != len(set(actual)) or set(actual) != set(expected):
        raise ValueError("decisions must exactly cover each supplied candidate once")
    by_id = {str(candidate["candidate_id"]): candidate for candidate in candidates}
    for decision in decisions:
        allowed = by_id[decision.candidate_id].get("prefilter_tiers", [])
        if decision.primary_tier not in allowed:
            raise ValueError(
                f"{decision.candidate_id} selected a Tier outside prefilter_tiers"
            )


def request_validated_batch(
    client: object,
    candidates: list[dict[str, object]],
    model: str,
    *,
    max_attempts: int = 3,
) -> tuple[AbstractDecisionBatch, object]:
    """Retry model outputs that do not exactly cover the supplied batch."""

    last_error: ValueError | None = None
    for _ in range(max_attempts):
        try:
            result = client.create_structured(
                model,
                build_batch_prompt(candidates),
                AbstractDecisionBatch.model_json_schema(),
                "tier_supplement_abstract_screening",
            )
        except (TimeoutError, OSError) as exc:
            last_error = ValueError(f"transient transport failure: {exc}")
            continue
        try:
            parsed = AbstractDecisionBatch.model_validate(result.parsed_output)
            validate_batch_decisions(candidates, parsed.decisions)
        except ValueError as exc:
            last_error = exc
            continue
        return parsed, result
    assert last_error is not None
    raise last_error


def _cache_key(candidates: list[dict[str, object]], model: str) -> str:
    material = {
        "model": model,
        "instructions": SCREENING_INSTRUCTIONS,
        "records": [_screening_record(candidate) for candidate in candidates],
        "schema": AbstractDecisionBatch.model_json_schema(),
    }
    return hashlib.sha256(
        json.dumps(material, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _metadata_uncertain(candidate: dict[str, object]) -> AbstractDecision:
    tiers = candidate.get("prefilter_tiers", [])
    return AbstractDecision(
        candidate_id=str(candidate["candidate_id"]),
        decision="uncertain",
        primary_tier=tiers[0],
        confidence="low",
        evidence_roles=[],
        transferable_steps=[],
        condition_signals=[],
        failure_boundary_signals=[],
        rationale="No abstract was available; title metadata is insufficient.",
        limitations=["Metadata only; full text is required for relevance screening."],
        evidence_level="metadata_screening",
        full_text_priority="low",
        full_text_reasons=["abstract unavailable"],
    )


def _read_cached(path: Path, cache_key: str) -> list[AbstractDecision] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("cache_key") != cache_key:
            return None
        return [AbstractDecision.model_validate(row) for row in payload["decisions"]]
    except (OSError, json.JSONDecodeError, KeyError, ValueError):
        return None


def _client() -> ChatCompletionsStructuredClient:
    return ChatCompletionsStructuredClient(
        "https://cs.jaspervault.pro/v1",
        lambda: read_keychain_secret(
            "reaction-principle-jaspervault", os.environ["USER"]
        ),
        read_timeout_seconds=1200,
        max_retries=3,
    )


def screen(
    candidates_path: Path,
    output_root: Path,
    *,
    model: str,
    batch_size: int,
) -> dict[str, object]:
    candidates = json.loads(candidates_path.read_text(encoding="utf-8"))["candidates"]
    output_root.mkdir(parents=True, exist_ok=True)
    abstract_candidates = [candidate for candidate in candidates if candidate.get("abstract")]
    metadata_candidates = [candidate for candidate in candidates if not candidate.get("abstract")]
    decisions = [_metadata_uncertain(candidate) for candidate in metadata_candidates]
    batch_keys: list[str] = []
    client = _client()
    for offset in range(0, len(abstract_candidates), batch_size):
        batch = abstract_candidates[offset : offset + batch_size]
        key = _cache_key(batch, model)
        batch_keys.append(key)
        path = output_root / "screening_batches" / f"{key}.json"
        cached = _read_cached(path, key)
        if cached is not None:
            validate_batch_decisions(batch, cached)
            decisions.extend(cached)
            print(f"batch {offset // batch_size + 1}: cached", flush=True)
            continue
        parsed, result = request_validated_batch(client, batch, model)
        _atomic_json(
            path,
            {
                "cache_key": key,
                "candidate_ids": [candidate["candidate_id"] for candidate in batch],
                "decisions": [item.model_dump(mode="json") for item in parsed.decisions],
                "api": {
                    "response_id": result.response_id,
                    "returned_model": result.returned_model,
                    "transport": result.transport,
                    "usage": result.usage.__dict__,
                },
            },
        )
        decisions.extend(parsed.decisions)
        print(
            f"batch {offset // batch_size + 1}: completed "
            f"({len(decisions)}/{len(candidates)})",
            flush=True,
        )

    validate_batch_decisions(candidates, decisions)
    ordered = sorted(decisions, key=lambda item: item.candidate_id)
    by_id = {str(candidate["candidate_id"]): candidate for candidate in candidates}
    records = [
        {
            **by_id[item.candidate_id],
            "abstract_screening": item.model_dump(mode="json"),
        }
        for item in ordered
    ]
    decision_counts = Counter(item.decision for item in ordered)
    tier_counts = Counter(
        item.primary_tier for item in ordered if item.decision == "include"
    )
    priority_counts = Counter(item.full_text_priority for item in ordered)
    manifest = {
        "candidate_count": len(candidates),
        "completed_count": len(ordered),
        "abstract_screened_count": len(abstract_candidates),
        "metadata_only_count": len(metadata_candidates),
        "decision_counts": dict(sorted(decision_counts.items())),
        "included_primary_tier_counts": dict(sorted(tier_counts.items())),
        "full_text_priority_counts": dict(sorted(priority_counts.items())),
        "model": model,
        "batch_size": batch_size,
        "batch_count": len(batch_keys),
        "batch_keys": batch_keys,
        "evidence_boundary": (
            "All decisions are metadata/abstract screening evidence only. "
            "No hard incompatibility or formal negative evidence is established."
        ),
        "answer_isolation": {
            "known_outcome_terms_provided_to_model": False,
            "named_target_substrates_requested": False,
            "generic_nucleophilic_centers_allowed": ["N", "O", "S", "C", "P"],
        },
    }
    _atomic_json(output_root / "abstract_screening_records.json", {"records": records})
    _atomic_json(output_root / "abstract_screening_manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("runs/tier_supplement_v1/prefiltered_candidates.json"),
    )
    parser.add_argument(
        "--output", type=Path, default=Path("runs/tier_supplement_v1")
    )
    parser.add_argument("--model", default="gpt-5.6-sol")
    parser.add_argument("--batch-size", type=int, default=10)
    args = parser.parse_args()
    manifest = screen(
        args.input, args.output, model=args.model, batch_size=args.batch_size
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()

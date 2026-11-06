"""Perform blinded paper-level knowledge transfer for supplement evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from pipeline.api_client import ChatCompletionsStructuredClient, read_keychain_secret
from pipeline.evidence_registry import _atomic_json
from pipeline.principle_models import TransferabilityAssessment


SEED_TRANSFER_FIELDS = (
    "reaction_center", "electrophile_state", "nucleophile_state", "bond_changes",
    "reactive_intermediates", "elementary_steps", "electronic_requirements",
    "steric_requirements", "catalyst_roles", "condition_window", "failed_scope",
    "competing_pathways", "evidence_ids",
)


class RawTransferJudgment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_evidence_ids: list[str] = Field(min_length=1)
    seed_feature_ids: list[str] = Field(min_length=1)
    shared_elementary_step: str
    matched_requirements: list[str]
    mismatched_requirements: list[str]
    blocking_constraints: list[str]
    transfer_status: Literal["transferable", "conditional", "non_transferable", "unknown"]
    transferable_claim: str
    conditions: list[str]
    uncertainty: list[str]
    falsifying_test: str = Field(min_length=1)


class RawPaperTransfer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assessments: list[RawTransferJudgment] = Field(min_length=1, max_length=3)


def _seed_projection(seed: dict[str, Any]) -> dict[str, Any]:
    return {key: seed.get(key, []) for key in SEED_TRANSFER_FIELDS}


def _evidence_projection(record: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in record.get("evidence_items", []):
        result.append({
            "evidence_id": item.get("evidence_id"), "claim": item.get("claim"),
            "quotation": item.get("quotation"),
            "locators": item.get("locators") or ([f"PDF page {item['pdf_page']}"] if item.get("pdf_page") else []),
            "transferable_step_from_source": item.get("transferable_step") or "UNKNOWN",
            "reported_conditions": item.get("conditions", []),
            "reported_failure_boundaries": item.get("failure_boundaries", []),
            "evidence_strength": item.get("evidence_strength", "unknown"),
        })
    return result


def build_transfer_prompt(seed: dict[str, Any], record: dict[str, Any]) -> str:
    bundle = {
        "seed": _seed_projection(seed),
        "literature": {
            "candidate_id": record.get("candidate_id"), "title": record.get("title"),
            "doi": record.get("doi"), "tier": record.get("primary_tier"),
            "reaction_summary": record.get("reaction_summary", {}),
            "evidence": _evidence_projection(record),
        },
    }
    return f"""
Perform blinded Knowledge Transfer from one literature paper to the supplied Seed mechanism.
Do not use outside project outcomes, named target substrates, hidden results, or expected
answers. The Seed successful-scope list is intentionally absent. Compare local elementary
steps and requirements, not paper-topic similarity or a complete catalytic cycle.

Return one to three independent assessments. Cite only supplied literature evidence IDs and
Seed evidence IDs. Preserve explicit conditions, mismatches, blocking constraints, negative
evidence, contradictions, and unknowns. A literature failure is not automatically a Seed
failure. A source-supported operation may be transferable even when the complete reaction is
not. Do not assign scores or ranks. Set transfer_status to unknown when evidence cannot support
a comparison. State a concrete falsifying test.

BEGIN_TRANSFER_BUNDLE
{json.dumps(bundle, ensure_ascii=False, sort_keys=True)}
END_TRANSFER_BUNDLE
""".strip()


def _score(judgment: RawTransferJudgment, evidence_strengths: dict[str, str]) -> dict[str, int]:
    components = {
        "shared_step": 2 if judgment.shared_elementary_step.strip().casefold() != "unknown" else 0,
        "matched_requirements": min(2, len(judgment.matched_requirements)),
        "mismatch_penalty": -min(2, len(judgment.mismatched_requirements)),
        "blocking_penalty": -min(3, len(judgment.blocking_constraints)),
        "condition_specificity": 1 if judgment.conditions else 0,
        "evidence_quality": 2 if any(evidence_strengths.get(item) == "direct" for item in judgment.source_evidence_ids) else 1,
        "status_signal": {"transferable": 2, "conditional": 1, "unknown": 0, "non_transferable": -1}[judgment.transfer_status],
    }
    return {**components, "total": sum(components.values())}


def materialize_assessments(raw: dict[str, Any], seed: dict[str, Any], record: dict[str, Any]) -> list[TransferabilityAssessment]:
    parsed = RawPaperTransfer.model_validate(raw)
    known_source = {str(item["evidence_id"]) for item in record.get("evidence_items", [])}
    known_seed = {str(item) for item in seed.get("evidence_ids", [])}
    strengths = {str(item["evidence_id"]): str(item.get("evidence_strength", "unknown")) for item in record.get("evidence_items", [])}
    assessments: list[TransferabilityAssessment] = []
    for judgment in parsed.assessments:
        if not set(judgment.source_evidence_ids) <= known_source:
            raise ValueError("transfer judgment cites unknown literature evidence")
        if not set(judgment.seed_feature_ids) <= known_seed:
            raise ValueError("transfer judgment cites unknown Seed evidence")
        identity = json.dumps({
            "candidate_id": record["candidate_id"],
            "source_evidence_ids": sorted(judgment.source_evidence_ids),
            "shared_elementary_step": judgment.shared_elementary_step,
        }, ensure_ascii=False, sort_keys=True)
        assessment_id = "KT2-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
        assessments.append(TransferabilityAssessment(
            assessment_id=assessment_id,
            source_paper_id=str(record["candidate_id"]),
            source_mechanism_id=None,
            source_evidence_ids=tuple(judgment.source_evidence_ids),
            seed_feature_ids=tuple(judgment.seed_feature_ids),
            shared_elementary_step=judgment.shared_elementary_step,
            matched_requirements=tuple(judgment.matched_requirements),
            mismatched_requirements=tuple(judgment.mismatched_requirements),
            blocking_constraints=tuple(judgment.blocking_constraints),
            transfer_status=judgment.transfer_status,
            transferable_claim=judgment.transferable_claim,
            conditions=tuple(judgment.conditions),
            uncertainty=tuple(judgment.uncertainty),
            falsifying_test=judgment.falsifying_test,
            score_components=_score(judgment, strengths),
        ))
    if len({item.assessment_id for item in assessments}) != len(assessments):
        raise ValueError("paper transfer produced duplicate assessment identities")
    return assessments


def client() -> ChatCompletionsStructuredClient:
    return ChatCompletionsStructuredClient(
        "https://cs.jaspervault.pro/v1",
        lambda: read_keychain_secret("reaction-principle-jaspervault", os.environ["USER"]),
        read_timeout_seconds=1200,
        max_retries=3,
    )


def process(seed: dict[str, Any], record: dict[str, Any], output_root: Path, api: Any) -> dict[str, Any]:
    candidate_id = str(record["candidate_id"])
    paper_root = output_root / candidate_id
    validated_path = paper_root / "validated.json"
    if validated_path.is_file():
        payload = json.loads(validated_path.read_text(encoding="utf-8"))
        return {"candidate_id": candidate_id, "tier": record["primary_tier"], "status": "cached", "assessment_count": len(payload["assessments"])}
    prompt = build_transfer_prompt(seed, record)
    try:
        response = api.create_structured("gpt-5.6-sol", prompt, RawPaperTransfer.model_json_schema(), "supplement_knowledge_transfer")
        assessments = materialize_assessments(response.parsed_output, seed, record)
        payload = {
            "candidate_id": candidate_id, "doi": record.get("doi"), "title": record.get("title"),
            "tier": record["primary_tier"], "source_registry_sha256": record.get("source_sha256") or record.get("sha256"),
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "assessments": [item.model_dump(mode="json") for item in assessments],
            "api": {"response_id": response.response_id, "returned_model": response.returned_model, "transport": response.transport, "usage": response.usage.__dict__},
            "answer_isolation": {"seed_success_scope_provided": False, "known_outcomes_provided": False},
        }
        _atomic_json(validated_path, payload)
        return {"candidate_id": candidate_id, "tier": record["primary_tier"], "status": "validated", "assessment_count": len(assessments)}
    except Exception as exc:
        failure = {"candidate_id": candidate_id, "tier": record["primary_tier"], "status": "failed", "error_type": type(exc).__name__, "safe_error": str(exc)[:500]}
        _atomic_json(paper_root / "failure.json", failure)
        return failure


def aggregate(output_root: Path, registry_sha256: str) -> dict[str, Any]:
    assessments: list[dict[str, Any]] = []
    paper_ids: list[str] = []
    for path in sorted(output_root.glob("*/validated.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        paper_ids.append(payload["candidate_id"])
        assessments.extend(payload["assessments"])
    ids = [row["assessment_id"] for row in assessments]
    if len(ids) != len(set(ids)):
        raise ValueError("aggregate transfer assessments contain duplicate IDs")
    result = {
        "semantic_transfer_version": "tier-supplement-v2.0",
        "source_registry_sha256": registry_sha256,
        "paper_count": len(paper_ids), "assessment_count": len(assessments),
        "status_counts": dict(sorted(Counter(row["transfer_status"] for row in assessments).items())),
        "paper_ids": paper_ids, "assessments": assessments,
    }
    _atomic_json(output_root / "transfer_assessments.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=Path("runs/tier_supplement_v1/supplement_evidence_registry_v2.json"))
    parser.add_argument("--seed", type=Path, default=Path("derived/principles/seed_mechanism.json"))
    parser.add_argument("--output", type=Path, default=Path("runs/tier_supplement_v1/knowledge_transfer"))
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    registry = json.loads(args.registry.read_text(encoding="utf-8"))
    seed = json.loads(args.seed.read_text(encoding="utf-8"))
    records = registry["records"][: args.limit] if args.limit is not None else registry["records"]
    api = client()
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(process, seed, row, args.output, api) for row in records]
        for index, future in enumerate(as_completed(futures), start=1):
            result = future.result()
            results.append(result)
            print(f"transferred {index}/{len(futures)} {result['candidate_id']} {result['status']}", flush=True)
    summary = aggregate(args.output, registry["registry_sha256"])
    manifest = {
        "record_count": len(results), "status_counts": dict(sorted(Counter(row["status"] for row in results).items())),
        "paper_count": summary["paper_count"], "assessment_count": summary["assessment_count"],
        "transfer_status_counts": summary["status_counts"], "results": sorted(results, key=lambda row: row["candidate_id"]),
    }
    _atomic_json(args.output / "manifest.json", manifest)
    print(json.dumps({key: manifest[key] for key in ("record_count", "status_counts", "paper_count", "assessment_count", "transfer_status_counts")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

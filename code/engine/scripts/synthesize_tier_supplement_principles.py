"""Synthesize, independently review, and freeze supplement-informed Principles."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from pipeline.api_client import ChatCompletionsStructuredClient, read_keychain_secret
from pipeline.evidence_registry import _atomic_json
from pipeline.freeze import freeze_principles
from pipeline.model_proposals import _strict_schema, propose_reaction_principles
from pipeline.principle_induction import validate_principle_candidate
from pipeline.principle_models import (
    FrozenReactionPrincipleSet,
    ReactionPrinciple,
    SeedMechanism,
    TransferabilityAssessment,
)


SEED_REVIEW_FIELDS = (
    "reaction_center", "electrophile_state", "nucleophile_state", "bond_changes",
    "reactive_intermediates", "elementary_steps", "electronic_requirements",
    "steric_requirements", "catalyst_roles", "condition_window", "failed_scope",
    "competing_pathways", "evidence_ids",
)


def _seed_projection(seed: dict[str, Any]) -> dict[str, Any]:
    return {key: seed.get(key, []) for key in SEED_REVIEW_FIELDS}


class ReviewedPrinciplePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    principles: list[ReactionPrinciple] = Field(min_length=1)


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def build_review_prompt(
    seed: dict[str, Any], proposals: list[dict[str, Any]],
    assessments: dict[str, dict[str, Any]],
) -> str:
    cited_ids = {
        str(assessment_id)
        for proposal in proposals
        for key in ("supporting_transferred_evidence", "contradictory_evidence")
        for assessment_id in proposal.get(key, [])
    }
    bundle = {
        "seed": _seed_projection(seed),
        "proposals": proposals,
        "cited_transfer_assessments": {
            assessment_id: assessments[assessment_id]
            for assessment_id in sorted(cited_ids)
            if assessment_id in assessments
        },
    }
    return f"""
Conduct an independent evidence review of every proposed Reaction Principle. The Seed
successful-scope list and hidden validation outcomes are intentionally absent. Return every
proposal exactly once with the same principle_id. Set both status and review_status to accepted,
revised, or rejected. Preserve freeze_version=null.

Accept only if the claim is anchored to supplied Seed evidence and at least one transferable or
conditional assessment, does not transfer a complete catalytic cycle from a local analogy,
preserves material contradictions and unknowns, separates Seed-specific from transferable
content, gives bounded condition and failure statements, and is experimentally falsifiable.
Revise overbroad claims using only supplied evidence IDs. Reject unsupported claims. Do not add
new evidence IDs, named expected outcomes, rankings, or a predefined nucleophile ontology. This
is independent evidence review, not stylistic editing.

BEGIN_REVIEW_BUNDLE
{json.dumps(bundle, ensure_ascii=False, sort_keys=True)}
END_REVIEW_BUNDLE
""".strip()


def _client() -> ChatCompletionsStructuredClient:
    return ChatCompletionsStructuredClient(
        "https://cs.jaspervault.pro/v1",
        lambda: read_keychain_secret("reaction-principle-jaspervault", os.environ["USER"]),
        read_timeout_seconds=1200,
        max_retries=3,
    )


def _clean_transfer_path(root: Path) -> Path:
    manifest = json.loads((root / "derived/principles_v3/evidence_import_manifest.json").read_text(encoding="utf-8"))
    paths = [Path(row["path"]) for row in manifest.get("accepted", []) if row.get("artifact_type") == "transfer"]
    if len(paths) != 1:
        raise ValueError("expected one accepted clean baseline transfer artifact")
    return root / paths[0]


def _load_assessments(root: Path, supplement_path: Path) -> dict[str, TransferabilityAssessment]:
    baseline = json.loads(_clean_transfer_path(root).read_text(encoding="utf-8"))["assessments"]
    supplement = json.loads(supplement_path.read_text(encoding="utf-8"))["assessments"]
    assessments: dict[str, TransferabilityAssessment] = {}
    for row in [*baseline, *supplement]:
        item = TransferabilityAssessment.model_validate(row)
        if item.assessment_id in assessments:
            raise ValueError(f"duplicate transfer assessment ID: {item.assessment_id}")
        assessments[item.assessment_id] = item
    return assessments


def validate_review(
    raw: dict[str, Any], proposals: tuple[ReactionPrinciple, ...],
    seed: SeedMechanism, assessments: dict[str, TransferabilityAssessment],
) -> tuple[list[ReactionPrinciple], list[ReactionPrinciple]]:
    reviewed = ReviewedPrinciplePayload.model_validate(raw).principles
    expected = {item.principle_id for item in proposals}
    returned = {item.principle_id for item in reviewed}
    if len(reviewed) != len(returned) or returned != expected:
        raise ValueError("review must exactly cover proposed Principle IDs")
    accepted: list[ReactionPrinciple] = []
    rejected: list[ReactionPrinciple] = []
    for item in reviewed:
        if item.status != item.review_status or item.status not in {"accepted", "revised", "rejected"}:
            raise ValueError("review status and principle status must agree")
        validated = validate_principle_candidate(
            item, known_seed_evidence_ids=set(seed.evidence_ids),
            transfer_assessments=assessments,
        )
        (accepted if item.status in {"accepted", "revised"} else rejected).append(validated)
    if {item.principle_layer for item in accepted} != {"seed_specific", "transferable_super"}:
        raise ValueError("reviewed Principle set must retain both required layers")
    return accepted, rejected


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--supplement", type=Path, default=Path("runs/tier_supplement_v1/knowledge_transfer/transfer_assessments.json"))
    parser.add_argument("--registry", type=Path, default=Path("runs/tier_supplement_v1/supplement_evidence_registry_v2.json"))
    parser.add_argument("--output", type=Path, default=Path("runs/tier_supplement_v1/workflow_rerun"))
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output.resolve()
    seed = SeedMechanism.model_validate_json((root / "derived/principles/seed_mechanism.json").read_text(encoding="utf-8"))
    assessments = _load_assessments(root, args.supplement)
    api = _client()
    config = {
        "model": "gpt-5.6-sol", "prompt_version": "tier-supplement-v2.0",
        "max_assessments": 120, "max_per_paper": 1,
        "prompt_text": (
            "Propose a compact, falsifiable Reaction Principle set from the Seed and blinded "
            "Knowledge Transfer assessments. Include at least one seed_specific and one "
            "transferable_super Principle. Transfer only local elementary steps and bounded "
            "requirements; preserve contradictions, condition dependence, non-transferable "
            "features, and unknowns. Use mechanism-level partner descriptions, not a predefined "
            "nucleophile ontology or expected outcomes. Every Principle must cite supplied Seed "
            "and transfer assessment IDs, state an experimental consequence and a falsifying "
            "experiment, use status=proposed, review_status=pending, and freeze_version=null."
        ),
    }
    proposed = propose_reaction_principles(
        seed, assessments, api, config,
        output / "principle_modeling", exploration_brief=None,
    )
    proposal_payload = {
        "cache_key": proposed.cache_key,
        "principles": [item.model_dump(mode="json") for item in proposed.principles],
        "usage": proposed.usage,
    }
    _atomic_json(output / "principle_proposals.json", proposal_payload)
    review_path = output / "principle_review.json"
    if review_path.is_file():
        reviewed_raw = json.loads(review_path.read_text(encoding="utf-8"))["model_output"]
        review_api = None
    else:
        prompt = build_review_prompt(
            seed.model_dump(mode="json"), proposal_payload["principles"],
            {key: value.model_dump(mode="json") for key, value in assessments.items()},
        )
        response = api.create_structured("gpt-5.6-sol", prompt, _strict_schema(ReviewedPrinciplePayload), "independent_principle_review")
        reviewed_raw = response.parsed_output
        review_api = {"response_id": response.response_id, "returned_model": response.returned_model, "transport": response.transport, "usage": response.usage.__dict__, "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest()}
        _atomic_json(review_path, {"model_output": reviewed_raw, "api": review_api})
    accepted, rejected = validate_review(reviewed_raw, proposed.principles, seed, assessments)
    _atomic_json(output / "reviewed_principles.json", {
        "accepted": [item.model_dump(mode="json") for item in accepted],
        "rejected": [item.model_dump(mode="json") for item in rejected],
    })
    registry = json.loads(args.registry.read_text(encoding="utf-8"))
    source_digest = _digest({
        "baseline_evidence_import": json.loads((root / "derived/principles_v3/evidence_import_manifest.json").read_text(encoding="utf-8"))["manifest_digest"],
        "supplement_registry": registry["registry_sha256"],
        "supplement_transfer": hashlib.sha256(args.supplement.read_bytes()).hexdigest(),
    })
    scoring_digest = _digest({"transfer_scoring": "tier-supplement-v2-deterministic", "principle_review": "independent-model-v1"})
    frozen_path = output / "frozen_principles.json"
    if frozen_path.is_file():
        frozen = FrozenReactionPrincipleSet.model_validate_json(frozen_path.read_text(encoding="utf-8"))
    else:
        frozen = freeze_principles(
            accepted, source_digest=source_digest, scoring_digest=scoring_digest,
            freeze_version="tier-supplement-v2", destination=frozen_path,
            created_at=datetime.now(UTC).isoformat(),
        )
    summary = {
        "assessment_count": len(assessments), "proposed_count": len(proposed.principles),
        "accepted_count": len(accepted), "rejected_count": len(rejected),
        "layers": dict(sorted({layer: sum(item.principle_layer == layer for item in accepted) for layer in {item.principle_layer for item in accepted}}.items())),
        "source_digest": source_digest, "scoring_digest": scoring_digest,
        "frozen_path": str(frozen_path), "frozen_principle_count": len(frozen.principles),
    }
    _atomic_json(output / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

"""Validation gates for model-proposed Reaction Principles."""

from __future__ import annotations

from collections.abc import Collection, Mapping

from pipeline.principle_models import ReactionPrinciple, TransferabilityAssessment


class PrincipleInductionError(RuntimeError):
    """Raised when a proposed Principle lacks traceable support."""


def validate_principle_candidate(
    principle: ReactionPrinciple,
    *,
    known_seed_evidence_ids: Collection[str],
    transfer_assessments: Mapping[str, TransferabilityAssessment],
) -> ReactionPrinciple:
    """Validate evidence references without upgrading human review state."""

    if principle.principle_layer == "seed_specific":
        universal_labels = {"all nucleophiles", "universal nucleophile", "any nucleophile"}
        claimed_families = {
            value.strip().casefold() for value in principle.applicable_nucleophile_families
        }
        if claimed_families & universal_labels:
            raise PrincipleInductionError(
                "Seed-specific Principle cannot claim universal nucleophile scope"
            )

    unknown_seed = sorted(set(principle.supporting_seed_evidence) - set(known_seed_evidence_ids))
    if unknown_seed:
        raise PrincipleInductionError(f"unknown seed evidence: {', '.join(unknown_seed)}")
    if not principle.supporting_transferred_evidence:
        raise PrincipleInductionError("Reaction Principle requires a transfer assessment")
    unknown_transfer = sorted(
        set(principle.supporting_transferred_evidence) - set(transfer_assessments)
    )
    if unknown_transfer:
        raise PrincipleInductionError(
            f"unknown transfer assessment: {', '.join(unknown_transfer)}"
        )
    unknown_contradictory = sorted(
        set(principle.contradictory_evidence) - set(transfer_assessments)
    )
    if unknown_contradictory:
        raise PrincipleInductionError(
            "unknown contradictory assessment: "
            + ", ".join(unknown_contradictory)
        )
    supported = [
        transfer_assessments[assessment_id]
        for assessment_id in principle.supporting_transferred_evidence
        if transfer_assessments[assessment_id].transfer_status in {"transferable", "conditional"}
    ]
    if not supported:
        raise PrincipleInductionError(
            "Reaction Principle requires a transferable or conditional assessment"
        )
    if principle.freeze_version is not None:
        raise PrincipleInductionError("proposed Principle cannot already carry a freeze version")
    return principle.model_copy(deep=True)

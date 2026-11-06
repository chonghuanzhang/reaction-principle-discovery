"""Deterministic checks for transferring literature mechanisms to a seed."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping

from pipeline.principle_models import (
    BoundaryConstraint,
    MechanismEvidence,
    SeedMechanism,
    TransferabilityAssessment,
)
from pipeline.paper_mechanism_bundles import PaperMechanismBundle
from pipeline.semantic_transfer import MechanismTransferProposal


def _normal(value: str) -> str:
    return " ".join(value.casefold().split())


def _contains_unknown(values: Iterable[str]) -> bool:
    return any(_normal(value) in {"unknown", "not established", "not reported"} for value in values)


def _overlaps(left: Iterable[str], right: Iterable[str]) -> bool:
    left_values = {_normal(value) for value in left}
    right_values = {_normal(value) for value in right}
    return bool(left_values & right_values)


def _constraint_applies(constraint: BoundaryConstraint, chemical_context: Iterable[str]) -> bool:
    context = [_normal(value) for value in chemical_context]
    for target in constraint.applies_to:
        normalized_target = _normal(target)
        if any(
            normalized_target == value
            or normalized_target in value
            or value in normalized_target
            for value in context
        ):
            return True
    return False


def score_transferability_components(
    seed: SeedMechanism,
    evidence: MechanismEvidence,
    rubric: Mapping[str, object],
) -> dict[str, int | str]:
    """Return transparent compatibility components without deciding blockers."""

    raw_weights = rubric.get("weights", {})
    weights = raw_weights if isinstance(raw_weights, Mapping) else {}

    def weight(name: str) -> int:
        value = weights.get(name, 0)
        return int(value) if isinstance(value, int) else 0

    shared_step = _overlaps([evidence.elementary_step], seed.elementary_steps)
    electrophile_match = _overlaps(
        evidence.electrophile_requirements,
        [*seed.electrophile_state, *seed.electronic_requirements],
    )
    nucleophile_match = _overlaps(evidence.nucleophile_requirements, seed.nucleophile_state)
    catalyst_match = _overlaps([evidence.catalyst_role], seed.catalyst_roles)
    condition_match = _overlaps(evidence.condition_requirements, seed.condition_window)
    components: dict[str, int | str] = {
        "shared_elementary_step": weight("shared_elementary_step") if shared_step else 0,
        "electrophile_match": weight("electrophile_match") if electrophile_match else 0,
        "nucleophile_match": weight("nucleophile_match") if nucleophile_match else 0,
        "catalyst_match": weight("catalyst_match") if catalyst_match else 0,
        "condition_match": weight("condition_match") if condition_match else 0,
    }
    components["total"] = sum(value for value in components.values() if isinstance(value, int))
    return components


def assess_transferability(
    seed: SeedMechanism,
    evidence: MechanismEvidence,
    constraints: Iterable[BoundaryConstraint],
    rubric: Mapping[str, object],
) -> TransferabilityAssessment:
    """Assess one mechanism item in an ordered, fail-explicit manner."""

    components = score_transferability_components(seed, evidence, rubric)
    matched: list[str] = []
    mismatched: list[str] = []
    uncertainty: list[str] = []

    if components["shared_elementary_step"]:
        matched.append("shared elementary step")
    else:
        mismatched.append("elementary step mismatch")
    if components["electrophile_match"]:
        matched.append("electrophile and electronic requirements")
    else:
        mismatched.append("electrophile or electronic mismatch")
    if _contains_unknown(evidence.nucleophile_requirements):
        uncertainty.append("nucleophile reactive form is unknown")
    elif components["nucleophile_match"]:
        matched.append("nucleophile reactive form")
    else:
        mismatched.append("nucleophile reactive form mismatch")
    if components["catalyst_match"]:
        matched.append("catalyst role")
    else:
        mismatched.append("catalyst role mismatch")
    if components["condition_match"]:
        matched.append("condition window")
    else:
        mismatched.append("condition window mismatch")

    chemical_context = [
        evidence.catalyst_role,
        *evidence.nucleophile_requirements,
        *evidence.electrophile_requirements,
        *evidence.condition_requirements,
        *seed.catalyst_roles,
    ]
    blockers = tuple(
        constraint.constraint_id
        for constraint in constraints
        if constraint.direction == "incompatible"
        and _constraint_applies(constraint, chemical_context)
    )

    if blockers:
        status = "non_transferable"
    elif uncertainty:
        status = "unknown"
    elif not components["shared_elementary_step"]:
        status = "non_transferable"
    elif mismatched:
        status = "conditional"
    else:
        status = "transferable"

    identity = {
        "seed": seed.seed_reaction_id,
        "mechanism": evidence.mechanism_evidence_id,
        "blockers": blockers,
        "status": status,
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:12]
    return TransferabilityAssessment(
        assessment_id=f"TA-{digest}",
        source_evidence_ids=evidence.source_evidence_ids,
        seed_feature_ids=tuple(seed.evidence_ids),
        shared_elementary_step=evidence.elementary_step,
        matched_requirements=tuple(matched),
        mismatched_requirements=tuple(mismatched),
        blocking_constraints=blockers,
        transfer_status=status,
        transferable_claim=(
            f"{evidence.elementary_step} is {status.replace('_', ' ')} for {seed.seed_reaction_id}."
        ),
        conditions=tuple(evidence.condition_requirements),
        uncertainty=tuple(uncertainty),
        falsifying_test=(
            f"Test {evidence.elementary_step} while controlling the recorded matched and mismatched requirements."
        ),
        score_components=components,
    )


def adjudicate_transfer_proposal(
    seed: SeedMechanism,
    bundle: PaperMechanismBundle,
    proposal: MechanismTransferProposal,
    rubric: Mapping[str, object],
) -> TransferabilityAssessment:
    """Derive one final transfer status from a grounded semantic proposal."""

    mechanisms = {
        item.mechanism_evidence_id: item for item in bundle.mechanisms
    }
    mechanism = mechanisms.get(proposal.mechanism_id)
    if mechanism is None:
        raise ValueError(f"mechanism does not belong to paper bundle: {proposal.mechanism_id}")
    constraints = {item.constraint_id: item for item in bundle.constraints}
    for blocker_id in proposal.hard_blocker_constraint_ids:
        constraint = constraints.get(blocker_id)
        if constraint is None or constraint.direction != "incompatible":
            raise ValueError(f"invalid same-paper hard blocker: {blocker_id}")

    raw_weights = rubric.get("weights", {})
    weights = raw_weights if isinstance(raw_weights, Mapping) else {}
    raw_critical = rubric.get("critical_unknown_dimensions", [])
    critical_unknowns = {
        str(value) for value in raw_critical
    } if isinstance(raw_critical, list) else set()
    judgments = {item.dimension: item.judgment for item in proposal.components}
    score_components: dict[str, int | str] = {}
    denominator = 0
    total = 0
    for component in proposal.components:
        weight_value = weights.get(component.dimension, 0)
        weight = int(weight_value) if isinstance(weight_value, int) else 0
        if component.judgment == "unknown":
            score_components[component.dimension] = "unknown"
            continue
        denominator += weight
        if component.judgment == "match":
            value = weight
        elif component.judgment == "conditional":
            value = max(1, weight // 2) if weight else 0
        else:
            value = 0
        score_components[component.dimension] = value
        total += value
    score_components["denominator"] = denominator
    score_components["total"] = total

    unknown_dimensions = {
        dimension for dimension, judgment in judgments.items() if judgment == "unknown"
    }
    if proposal.hard_blocker_constraint_ids:
        status = "non_transferable"
    elif unknown_dimensions & critical_unknowns:
        status = "unknown"
    elif judgments.get("shared_elementary_step") == "mismatch":
        status = "non_transferable"
    elif any(value in {"mismatch", "conditional"} for value in judgments.values()):
        status = "conditional"
    else:
        status = "transferable"

    matched = tuple(
        component.dimension
        for component in proposal.components
        if component.judgment == "match"
    )
    mismatched = tuple(
        component.dimension
        for component in proposal.components
        if component.judgment == "mismatch"
    )
    uncertainty = tuple(
        dict.fromkeys(
            [
                *proposal.uncertainty,
                *(f"unknown transfer dimension: {value}" for value in sorted(unknown_dimensions)),
            ]
        )
    )
    literature_ids = tuple(
        dict.fromkeys(
            evidence_id
            for component in proposal.components
            for evidence_id in component.literature_evidence_ids
        )
    )
    seed_ids = tuple(
        dict.fromkeys(
            evidence_id
            for component in proposal.components
            for evidence_id in component.seed_evidence_ids
        )
    ) or tuple(seed.evidence_ids)
    identity = {
        "seed": seed.seed_reaction_id,
        "bundle": bundle.namespace,
        "mechanism": proposal.mechanism_id,
        "judgments": judgments,
        "blockers": proposal.hard_blocker_constraint_ids,
        "status": status,
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    return TransferabilityAssessment(
        assessment_id=f"TA-{digest}",
        source_paper_id=bundle.source_path,
        source_mechanism_id=proposal.mechanism_id,
        source_evidence_ids=literature_ids,
        seed_feature_ids=seed_ids,
        shared_elementary_step=mechanism.elementary_step,
        matched_requirements=matched,
        mismatched_requirements=mismatched,
        blocking_constraints=proposal.hard_blocker_constraint_ids,
        transfer_status=status,
        transferable_claim=proposal.transferable_claim,
        conditions=proposal.conditions,
        uncertainty=uncertainty,
        falsifying_test=proposal.falsifying_test,
        score_components=score_components,
    )

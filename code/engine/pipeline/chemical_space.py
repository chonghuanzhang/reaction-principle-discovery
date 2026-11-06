"""Deterministic family-level chemical boundary classification."""

from __future__ import annotations

from collections.abc import Mapping

from pipeline.principle_models import FamilyBoundaryPrediction


def classify_family(
    *,
    family_id: str,
    family_type: str,
    compatibility: Mapping[str, int | None],
    risks: Mapping[str, int | None],
    compatible_principle_ids: tuple[str, ...],
    violated_principle_ids: tuple[str, ...],
    required_conditions: tuple[str, ...],
    evidence_ids: tuple[str, ...],
    hard_blockers: tuple[str, ...],
    uncertainty: tuple[str, ...],
    rubric: Mapping[str, object],
    superclass_id: str | None = None,
    representative_nucleophile: str | None = None,
    reactive_form: str | None = None,
    fixed_electrophile_id: str | None = None,
    catalyst_requirement: str | None = None,
    condition_window: dict[str, str | list[str] | None] | None = None,
    diagnostic_status: str | None = None,
    no_experiment_rationale: str | None = None,
) -> FamilyBoundaryPrediction:
    """Classify a family while keeping blockers and unknowns explicit."""

    raw_weights = rubric.get("weights", {})
    weights = raw_weights if isinstance(raw_weights, Mapping) else {}
    raw_penalties = rubric.get("risk_penalties", {})
    penalties = raw_penalties if isinstance(raw_penalties, Mapping) else {}
    raw_thresholds = rubric.get("thresholds", {})
    thresholds = raw_thresholds if isinstance(raw_thresholds, Mapping) else {}

    score_components: dict[str, int | str] = {}
    propagated_uncertainty = set(uncertainty)
    has_unknown_component = False
    total = 0
    for name in sorted(weights):
        level = compatibility.get(name)
        if level is None:
            has_unknown_component = True
            propagated_uncertainty.add(f"compatibility:{name} unknown")
            score_components[name] = "unknown"
            continue
        weighted = int(level) * int(weights.get(name, 0))
        score_components[name] = weighted
        total += weighted
    for name in sorted(penalties):
        level = risks.get(name)
        if level is None:
            has_unknown_component = True
            propagated_uncertainty.add(f"risk:{name} unknown")
            score_components[f"risk:{name}"] = "unknown"
            continue
        weighted = int(level) * int(penalties.get(name, 0))
        score_components[f"risk:{name}"] = -weighted
        total -= weighted
    score_components["total"] = total

    if hard_blockers:
        classification = "exclude"
    elif has_unknown_component:
        classification = "insufficient_evidence"
    elif total >= int(thresholds.get("explore", 0)):
        classification = "explore"
    elif total >= int(thresholds.get("conditional", 0)):
        classification = "conditional"
    elif total >= int(thresholds.get("deprioritize", 0)):
        classification = "deprioritize"
    else:
        classification = "deprioritize"

    return FamilyBoundaryPrediction(
        family_id=family_id,
        family_type=family_type,
        classification=classification,
        compatible_principle_ids=compatible_principle_ids,
        violated_principle_ids=tuple(sorted(set(violated_principle_ids) | set(hard_blockers))),
        required_conditions=required_conditions,
        dominant_risks=tuple(
            sorted(
                {name for name, level in risks.items() if level is not None and level > 0}
                | set(hard_blockers)
            )
        ),
        evidence_ids=evidence_ids,
        score_components=score_components,
        total_score=total,
        uncertainty=tuple(sorted(propagated_uncertainty)),
        superclass_id=superclass_id,
        representative_nucleophile=representative_nucleophile,
        reactive_form=reactive_form,
        fixed_electrophile_id=fixed_electrophile_id,
        catalyst_requirement=catalyst_requirement,
        condition_window=condition_window,
        diagnostic_status=diagnostic_status,
        no_experiment_rationale=no_experiment_rationale,
    )

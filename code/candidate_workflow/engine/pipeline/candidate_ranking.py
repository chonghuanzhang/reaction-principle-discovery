"""Concrete experiment ranking built on family boundary predictions."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence

from pipeline.principle_models import ExperimentCandidate, FamilyBoundaryPrediction


_PROVENANCE_FIELDS = {
    "freeze_status",
    "freeze_version",
    "principle_digest",
    "scoring_digest",
    "candidate_list_digest",
}


def candidate_list_digest(predictions: Sequence[ExperimentCandidate]) -> str:
    """Return a stable digest of scientific content and candidate order."""

    payload = [
        prediction.model_dump(mode="json", exclude=_PROVENANCE_FIELDS)
        for prediction in predictions
    ]
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def rank_experiment_candidates(
    candidates: Sequence[Mapping[str, object]],
    families: Mapping[str, FamilyBoundaryPrediction],
    rubric: Mapping[str, object],
) -> tuple[ExperimentCandidate, ...]:
    """Rank concrete experiments deterministically with explicit components."""

    raw_penalties = rubric.get("risk_penalties", {})
    penalties = raw_penalties if isinstance(raw_penalties, Mapping) else {}
    family_order = {
        family_id: rank
        for rank, family_id in enumerate(
            sorted(families, key=lambda key: (-families[key].total_score, key)),
            start=1,
        )
    }
    prepared: list[tuple[int, str, dict, FamilyBoundaryPrediction, dict[str, int]]] = []
    for candidate in candidates:
        experiment_id = str(candidate["experiment_id"])
        family_id = str(candidate["family_id"])
        if family_id not in families:
            raise ValueError(f"unknown family for experiment {experiment_id}: {family_id}")
        family = families[family_id]
        components: dict[str, int] = {"family_score": family.total_score}
        total = family.total_score
        bonuses = candidate.get("bonus_components", {})
        if isinstance(bonuses, Mapping):
            for name, raw_value in sorted(bonuses.items()):
                value = int(raw_value)
                components[f"bonus:{name}"] = value
                total += value
        risks = candidate.get("risk_components", {})
        if isinstance(risks, Mapping):
            for name, raw_value in sorted(risks.items()):
                value = int(raw_value) * int(penalties.get(name, 0))
                components[f"risk:{name}"] = -value
                total -= value
        components["total"] = total
        prepared.append((total, experiment_id, dict(candidate), family, components))

    ranked: list[ExperimentCandidate] = []
    for experiment_rank, (_, experiment_id, candidate, family, components) in enumerate(
        sorted(prepared, key=lambda row: (-row[0], row[1])),
        start=1,
    ):
        ranked.append(
            ExperimentCandidate(
                experiment_id=experiment_id,
                family_id=family.family_id,
                electrophile=str(candidate.get("electrophile", "")),
                nucleophile=str(candidate.get("nucleophile", "")),
                catalyst=str(candidate.get("catalyst", "")),
                ligand=str(candidate.get("ligand", "")),
                base=str(candidate.get("base", "")),
                solvent=str(candidate.get("solvent", "")),
                temperature=str(candidate.get("temperature", "")),
                time=str(candidate.get("time", "")),
                atmosphere=str(candidate.get("atmosphere", "")),
                predicted_outcome=family.classification,
                predicted_failure_modes=tuple(candidate.get("predicted_failure_modes", [])),
                family_priority=family_order[family.family_id],
                experiment_priority=experiment_rank,
                supporting_principle_ids=tuple(candidate.get("supporting_principle_ids", [])),
                evidence_ids=tuple(candidate.get("evidence_ids", [])),
                minimal_diagnostic_plan=tuple(candidate.get("minimal_diagnostic_plan", [])),
                score_components=components,
                total_score=components["total"],
                uncertainty=tuple(candidate.get("uncertainty", [])),
                freeze_status="provisional",
            )
        )
    return tuple(ranked)

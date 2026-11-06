"""Deterministic robustness analyses for v3 family rankings."""

from __future__ import annotations

import hashlib
import json
import random
import weakref
from collections.abc import Mapping, Sequence
from statistics import median
from types import MappingProxyType
from typing import Any, Literal

from pydantic import Field, ValidationError, field_serializer, model_validator

from pipeline.family_evaluation import (
    DerivedFamilyMetrics,
    EvaluationRubric,
    EvidenceContribution,
    EvidenceQualificationError,
    ScoredFamilyEvaluation,
    derive_family_metrics,
    verify_scored_family_evaluation,
)
from pipeline.principle_models import FrozenStrictModel
from pipeline.v3_models import (
    DIMENSIONS,
    DimensionName,
    JudgmentState,
    PriorityRegion,
    RankingRecord,
)


class RankingAnalysisError(ValueError):
    """Raised when v3 ranking inputs violate the scored-family contract."""


_RANKING_BUILDER_TOKEN = object()
_RANKING_ATTESTATIONS: dict[
    int, tuple[weakref.ReferenceType[object], str, str, str, str]
] = {}


def _stable_digest(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class LeaveOnePaperOutStress(FrozenStrictModel):
    source_paper: str = Field(min_length=1)
    priority_region: PriorityRegion
    disposition: Literal["ranked", "boundary", "excluded", "unknown"]
    rank: int | None = Field(default=None, ge=1)
    dimension_states: Mapping[DimensionName, JudgmentState]
    compatibility_index: float | None = Field(ge=0, le=4)
    evidence_confidence: float | None = Field(ge=0, le=4)
    uncertainty_burden: float = Field(ge=0, le=4)
    failure_risk: float | None = Field(ge=0, le=4)
    critical_unknowns: tuple[DimensionName, ...]

    @model_validator(mode="after")
    def validate_disposition(self) -> "LeaveOnePaperOutStress":
        if self.disposition == "ranked" and self.rank is None:
            raise ValueError("ranked paper-omission stress requires a rank")
        if self.disposition != "ranked" and self.rank is not None:
            raise ValueError("non-testable paper-omission stress cannot have a rank")
        object.__setattr__(
            self,
            "dimension_states",
            MappingProxyType(
                {
                    dimension: self.dimension_states[dimension]
                    for dimension in DIMENSIONS
                }
            ),
        )
        return self

    @field_serializer("dimension_states")
    def serialize_dimension_states(
        self, dimension_states: Mapping[DimensionName, JudgmentState]
    ) -> dict[DimensionName, JudgmentState]:
        return dict(dimension_states)


class RobustnessRankingRecord(RankingRecord):
    evaluation_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    sampled_rank_median: float | None = Field(default=None, ge=1)
    sampled_rank_range: tuple[int, int] | None = None
    leave_one_paper_out_interval: tuple[int, int] | None = None
    leave_one_paper_out_range: tuple[int, int] | None = None
    leave_one_paper_out_stress: tuple[LeaveOnePaperOutStress, ...] = ()
    stability_label: Literal[
        "stable", "weight_sensitive", "paper_sensitive", "unstable"
    ] | None = None

    @model_validator(mode="after")
    def prevent_non_testable_robustness_ranks(self) -> "RobustnessRankingRecord":
        if self.priority_region in {"boundary", "excluded", "unknown"} and any(
            value is not None
            for value in (
                self.sampled_rank_median,
                self.sampled_rank_range,
                self.leave_one_paper_out_interval,
                self.leave_one_paper_out_range,
                self.leave_one_paper_out_stress or None,
                self.stability_label,
            )
        ):
            raise ValueError("non-testable priority region cannot have robustness ranks")
        return self


def _objective_values(
    evaluation: ScoredFamilyEvaluation | DerivedFamilyMetrics,
) -> tuple[float | None, ...]:
    return tuple(
        None
        if evaluation.dimension_scores[dimension] is None
        else float(
            4 - evaluation.dimension_scores[dimension]
            if dimension == "competing_pathway_risk"
            else evaluation.dimension_scores[dimension]
        )
        for dimension in DIMENSIONS
    )


def _dominates(
    left: ScoredFamilyEvaluation,
    right: ScoredFamilyEvaluation,
    rubric: EvaluationRubric,
) -> bool:
    left_values = dict(zip(DIMENSIONS, _objective_values(left), strict=True))
    right_values = dict(zip(DIMENSIONS, _objective_values(right), strict=True))
    objective_dimensions = (
        *rubric.core_dimensions,
        rubric.failure_risk_dimension,
    )
    pairs = tuple(
        (left_values[dimension], right_values[dimension])
        for dimension in objective_dimensions
    )
    if any(left_value is None or right_value is None for left_value, right_value in pairs):
        return False
    numeric = tuple(
        (left_value, right_value)
        for left_value, right_value in pairs
        if left_value is not None and right_value is not None
    )
    return all(left_value >= right_value for left_value, right_value in numeric) and any(
        left_value > right_value for left_value, right_value in numeric
    )


class RankingAnalysis(FrozenStrictModel):
    records: tuple[RobustnessRankingRecord, ...]
    seed: int
    sample_count: int = Field(ge=100)
    rubric_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    context_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    evaluations_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    def __init__(self, **data: Any) -> None:
        token = data.pop("_builder_token", None)
        if token is not _RANKING_BUILDER_TOKEN:
            raise RankingAnalysisError(
                "RankingAnalysis requires analyze_ranking attestation"
            )
        super().__init__(**data)

    @property
    def by_family(self) -> Mapping[str, RobustnessRankingRecord]:
        return {record.family_id: record for record in self.records}


def _evaluations_digest(evaluations: Sequence[ScoredFamilyEvaluation]) -> str:
    return _stable_digest(
        [
            {
                "family_id": evaluation.family_id,
                "scored_content_digest": evaluation.scored_content_digest,
            }
            for evaluation in sorted(evaluations, key=lambda item: item.family_id)
        ]
    )


def _analysis_content_digest(analysis: RankingAnalysis) -> str:
    return _stable_digest(
        analysis.model_dump(mode="json", exclude={"content_digest"})
    )


def _attest_ranking_analysis(analysis: RankingAnalysis) -> None:
    analysis_id = id(analysis)

    def discard(_: weakref.ReferenceType[object]) -> None:
        _RANKING_ATTESTATIONS.pop(analysis_id, None)

    _RANKING_ATTESTATIONS[analysis_id] = (
        weakref.ref(analysis, discard),
        analysis.content_digest,
        analysis.rubric_digest,
        analysis.context_digest,
        analysis.evaluations_digest,
    )


def _build_ranking_analysis(**data: Any) -> RankingAnalysis:
    provisional = RankingAnalysis(
        _builder_token=_RANKING_BUILDER_TOKEN,
        content_digest="0" * 64,
        **data,
    )
    analysis = RankingAnalysis(
        _builder_token=_RANKING_BUILDER_TOKEN,
        content_digest=_analysis_content_digest(provisional),
        **data,
    )
    _attest_ranking_analysis(analysis)
    return analysis


def verify_ranking_analysis(
    analysis: RankingAnalysis,
    evaluations: Sequence[ScoredFamilyEvaluation],
    rubric: EvaluationRubric,
) -> RankingAnalysis:
    """Verify analysis identity, content, and exact Task 8 evaluation binding."""

    if not isinstance(analysis, RankingAnalysis):
        raise RankingAnalysisError("ranking analysis failed attestation")
    try:
        verified = tuple(
            verify_scored_family_evaluation(evaluation, rubric)
            for evaluation in evaluations
        )
    except EvidenceQualificationError as exc:
        raise RankingAnalysisError(
            f"ranking evaluation attestation failed: {exc}"
        ) from exc
    if not verified or len({item.family_id for item in verified}) != len(verified):
        raise RankingAnalysisError(
            "ranking analysis requires unique attested evaluations"
        )
    rubric_digests = {item.rubric_digest for item in verified}
    context_digests = {item.context_digest for item in verified}
    if len(rubric_digests) != 1 or len(context_digests) != 1:
        raise RankingAnalysisError(
            "ranking analysis evaluations require one rubric and context digest"
        )
    expected_evaluations_digest = _evaluations_digest(verified)
    attestation = _RANKING_ATTESTATIONS.get(id(analysis))
    if (
        attestation is None
        or attestation[0]() is not analysis
        or attestation[1] != analysis.content_digest
        or attestation[2] != analysis.rubric_digest
        or attestation[3] != analysis.context_digest
        or attestation[4] != analysis.evaluations_digest
        or _analysis_content_digest(analysis) != analysis.content_digest
        or analysis.rubric_digest != next(iter(rubric_digests))
        or analysis.context_digest != next(iter(context_digests))
    ):
        raise RankingAnalysisError("RankingAnalysis failed analysis attestation")
    if analysis.evaluations_digest != expected_evaluations_digest:
        raise RankingAnalysisError("ranking analysis evaluation digest set mismatch")
    evaluation_by_id = {item.family_id: item for item in verified}
    if set(analysis.by_family) != set(evaluation_by_id):
        raise RankingAnalysisError("ranking analysis evaluation digest set mismatch")
    for record in analysis.records:
        evaluation = evaluation_by_id[record.family_id]
        if (
            record.evaluation_digest != evaluation.scored_content_digest
            or record.priority_region != evaluation.priority_region
        ):
            raise RankingAnalysisError(
                f"ranking record evaluation digest or region mismatch: {record.family_id}"
            )
    return analysis


def _score(
    evaluation: ScoredFamilyEvaluation | DerivedFamilyMetrics,
    weights: Mapping[str, float],
) -> float | None:
    observed = tuple(
        (float(weights[dimension]), objective)
        for dimension, objective in zip(
            DIMENSIONS, _objective_values(evaluation), strict=True
        )
        if objective is not None
    )
    if not observed:
        return None
    total_weight = sum(weight for weight, _ in observed)
    return sum(weight * objective for weight, objective in observed) / total_weight


def _ranks(
    evaluations: Sequence[tuple[str, ScoredFamilyEvaluation | DerivedFamilyMetrics]],
    weights: Mapping[str, float],
) -> dict[str, int]:
    scores = {
        family_id: _score(evaluation, weights)
        for family_id, evaluation in evaluations
    }
    ordered = sorted(
        evaluations,
        key=lambda item: (
            scores[item[0]] is None,
            -scores[item[0]]
            if scores[item[0]] is not None
            else 0.0,
            item[0],
        ),
    )
    return {
        family_id: rank
        for rank, (family_id, _) in enumerate(ordered, start=1)
    }


def _aggregate_states_without_paper(
    evaluation: ScoredFamilyEvaluation,
    rubric: EvaluationRubric,
    source_paper: str,
) -> Mapping[DimensionName, JudgmentState]:
    states: dict[DimensionName, JudgmentState] = {
        judgment.dimension: judgment.state for judgment in evaluation.judgments
    }
    affected_dimensions = {
        contribution.dimension
        for contribution in evaluation.evidence_contributions
        if contribution.source_paper == source_paper
    }
    for dimension in DIMENSIONS:
        if dimension not in affected_dimensions:
            continue
        remaining = tuple(
            contribution
            for contribution in evaluation.evidence_contributions
            if contribution.dimension == dimension
            and contribution.source_paper != source_paper
            and (
                dimension != rubric.evidence_confidence_dimension
                or contribution.direction == "adverse"
                or contribution.quality_eligible
            )
        )
        directions = {contribution.direction for contribution in remaining}
        if directions == {"positive"}:
            disposition = (
                "conditional"
                if any(
                    contribution.state == "conditional_support"
                    for contribution in remaining
                )
                else "positive"
            )
        elif directions == {"adverse"}:
            disposition = "adverse"
        elif directions == {"positive", "adverse"}:
            disposition = "mixed"
        else:
            disposition = "none"
        states[dimension] = rubric.evidence_aggregation_policy[disposition]
    return states


def _stress_disposition(region: PriorityRegion) -> str:
    if region in {"priority_a", "priority_b", "priority_c"}:
        return "ranked"
    return region


def _stability_label(weight_sensitive: bool, paper_sensitive: bool) -> str:
    if weight_sensitive and paper_sensitive:
        return "unstable"
    if weight_sensitive:
        return "weight_sensitive"
    if paper_sensitive:
        return "paper_sensitive"
    return "stable"


def analyze_ranking(
    evaluations: Sequence[ScoredFamilyEvaluation],
    rubric: EvaluationRubric,
    *,
    seed: int,
) -> RankingAnalysis:
    """Return the deterministic primary and equal-weight family ordering."""

    if type(rubric) is not EvaluationRubric:
        raise RankingAnalysisError("ranking requires a valid EvaluationRubric")
    try:
        rubric = EvaluationRubric.model_validate(rubric.model_dump(mode="python"))
    except ValidationError as exc:
        raise RankingAnalysisError("ranking requires a valid EvaluationRubric") from exc
    try:
        verified = tuple(
            verify_scored_family_evaluation(evaluation, rubric)
            for evaluation in evaluations
        )
    except EvidenceQualificationError as exc:
        raise RankingAnalysisError(
            f"ranking rubric/scored attestation failed: {exc}"
        ) from exc
    if len({evaluation.context_digest for evaluation in verified}) > 1:
        raise RankingAnalysisError(
            "ranking scored attestation requires one trusted context digest"
        )
    family_ids = [evaluation.family_id for evaluation in verified]
    if len(set(family_ids)) != len(family_ids):
        raise RankingAnalysisError("duplicate family ID in canonical evaluations")
    ordered_evaluations = tuple(sorted(verified, key=lambda item: item.family_id))
    testable = tuple(
        evaluation
        for evaluation in ordered_evaluations
        if evaluation.priority_region in {"priority_a", "priority_b", "priority_c"}
    )
    testable_pairs = tuple(
        (evaluation.family_id, evaluation) for evaluation in testable
    )
    primary_ranks = _ranks(testable_pairs, rubric.ranking_weights)
    equal_ranks = _ranks(
        testable_pairs, {dimension: 1.0 for dimension in DIMENSIONS}
    )
    sampled_ranks = {evaluation.family_id: [] for evaluation in testable}
    generator = random.Random(seed)
    for _ in range(rubric.ranking_sample_count):
        sampled = {
            dimension: generator.uniform(*rubric.ranking_weight_bounds[dimension])
            for dimension in DIMENSIONS
        }
        total = sum(sampled.values())
        normalized = {
            dimension: weight / total for dimension, weight in sampled.items()
        }
        for family_id, rank in _ranks(testable_pairs, normalized).items():
            sampled_ranks[family_id].append(rank)
    paper_keys = tuple(
        sorted(
            {
                contribution.source_paper
                for evaluation in testable
                for contribution in evaluation.evidence_contributions
                if contribution.source_paper is not None
            }
        )
    )
    stress_metrics: dict[
        str,
        dict[
            str,
            tuple[Mapping[DimensionName, JudgmentState], DerivedFamilyMetrics],
        ],
    ] = {}
    stress_ranks: dict[str, dict[str, int]] = {}
    for paper in paper_keys:
        by_family: dict[
            str,
            tuple[Mapping[DimensionName, JudgmentState], DerivedFamilyMetrics],
        ] = {}
        for evaluation in testable:
            states = _aggregate_states_without_paper(evaluation, rubric, paper)
            metrics = derive_family_metrics(
                states, evaluation.qualified_blocker_ids, rubric
            )
            by_family[evaluation.family_id] = (states, metrics)
        stress_metrics[paper] = by_family
        stress_ranks[paper] = _ranks(
            tuple(
                (family_id, metrics)
                for family_id, (_, metrics) in by_family.items()
                if metrics.priority_region
                in {"priority_a", "priority_b", "priority_c"}
            ),
            rubric.ranking_weights,
        )
    ordered_testable = sorted(
        testable,
        key=lambda evaluation: primary_ranks[evaluation.family_id],
    )
    testable_records: list[RobustnessRankingRecord] = []
    for evaluation in ordered_testable:
        family_id = evaluation.family_id
        sampled_range = (
            min(sampled_ranks[family_id]),
            max(sampled_ranks[family_id]),
        )
        stresses = tuple(
            LeaveOnePaperOutStress(
                source_paper=paper,
                priority_region=(metrics := stress_metrics[paper][family_id][1]).priority_region,
                disposition=_stress_disposition(metrics.priority_region),  # type: ignore[arg-type]
                rank=stress_ranks[paper].get(family_id),
                dimension_states=stress_metrics[paper][family_id][0],
                compatibility_index=metrics.compatibility_index,
                evidence_confidence=metrics.evidence_confidence,
                uncertainty_burden=metrics.uncertainty_burden,
                failure_risk=metrics.failure_risk,
                critical_unknowns=metrics.critical_unknowns,
            )
            for paper in paper_keys
        )
        numeric_stress_ranks = tuple(
            stress.rank for stress in stresses if stress.rank is not None
        )
        paper_rank_values = (primary_ranks[family_id], *numeric_stress_ranks)
        paper_range = (min(paper_rank_values), max(paper_rank_values))
        weight_sensitive = (
            primary_ranks[family_id] != equal_ranks[family_id]
            or sampled_range[1] - sampled_range[0]
            > rubric.ranking_stability_max_span
        )
        paper_sensitive = any(
            stress.rank != primary_ranks[family_id]
            or stress.priority_region != evaluation.priority_region
            for stress in stresses
        )
        testable_records.append(
            RobustnessRankingRecord(
                family_id=evaluation.family_id,
                evaluation_digest=evaluation.scored_content_digest,
                priority_region=evaluation.priority_region,
                primary_rank=primary_ranks[family_id],
                equal_weight_rank=equal_ranks[family_id],
                sampled_rank_median=median(sampled_ranks[family_id]),
                rank_interval=sampled_range,
                sampled_rank_range=sampled_range,
                leave_one_paper_out_interval=paper_range,
                leave_one_paper_out_range=paper_range,
                leave_one_paper_out_stress=stresses,
                pareto_optimal=not any(
                    _dominates(other, evaluation, rubric)
                    for other in testable
                    if other.family_id != family_id
                ),
                weight_sensitive=weight_sensitive,
                stability_label=_stability_label(weight_sensitive, paper_sensitive),
                rationale="Testable family ranked from preregistered v3 scores.",
            )
        )
    non_testable_records = tuple(
        RobustnessRankingRecord(
            family_id=evaluation.family_id,
            evaluation_digest=evaluation.scored_content_digest,
            priority_region=evaluation.priority_region,
            rationale=(
                f"{evaluation.priority_region} family retained outside the numeric "
                "testable ordering."
            ),
        )
        for region in ("boundary", "excluded", "unknown")
        for evaluation in ordered_evaluations
        if evaluation.priority_region == region
    )
    return _build_ranking_analysis(
        records=tuple(testable_records) + non_testable_records,
        seed=seed,
        sample_count=rubric.ranking_sample_count,
        rubric_digest=ordered_evaluations[0].rubric_digest,
        context_digest=ordered_evaluations[0].context_digest,
        evaluations_digest=_evaluations_digest(ordered_evaluations),
    )

"""Freeze-gated retrospective and prospective validation metrics."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Literal

from pydantic import Field, model_validator

from pipeline.candidate_ranking import candidate_list_digest
from pipeline.principle_models import (
    ExperimentalOutcome,
    ExperimentCandidate,
    FrozenStrictModel,
)


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ValidationGateError(RuntimeError):
    """Raised when hidden outcomes are requested before a valid freeze."""


class MetricValue(FrozenStrictModel):
    numerator: float
    denominator: float = Field(ge=0)
    value: float | None


class ValidationMetrics(FrozenStrictModel):
    confirmed_hit_rate: MetricValue
    analytical_hit_rate: MetricValue
    precision_at_k: MetricValue
    enrichment: MetricValue
    boundary_accuracy: MetricValue
    failure_mode_agreement: MetricValue
    coverage: MetricValue
    abstention: MetricValue


class MetricAvailability(FrozenStrictModel):
    """A metric that stays explicitly unavailable instead of becoming zero."""

    status: Literal["available", "unavailable"]
    value: float | None
    reason: str | None = None

    @model_validator(mode="after")
    def preserve_unavailable_as_unknown(self) -> "MetricAvailability":
        if self.status == "unavailable" and self.value is not None:
            raise ValueError("unavailable metric must not encode unknown as zero")
        return self


class ProspectiveBoundaryStratum(FrozenStrictModel):
    stratum: Literal[
        "priority_a",
        "priority_b",
        "priority_c",
        "boundary",
        "negative_control",
    ]
    preregistered: bool = True
    required_outcome_evidence: Literal["traceable_experiment"] = "traceable_experiment"


class ValidationReadiness(FrozenStrictModel):
    historical_negative_status: Literal["missing", "insufficient", "sufficient"]
    historical_negative_record_count: int = Field(ge=0)
    resolved_negative_record_count: int = Field(default=0, ge=0)
    historical_negative_digest: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    failure_discrimination_metrics: MetricAvailability
    prospective_boundary_matrix_required: bool
    prospective_boundary_matrix: tuple[ProspectiveBoundaryStratum, ...]
    negative_record_reminder: str
    workflow_construction_blocked: bool = False
    retrospective_reveal_blocked: bool = False
    fixed_scope: Literal["SR001_nucleophile_condition"] = "SR001_nucleophile_condition"
    electrophile_expansion_blocked: bool = True


def classify_outcome(record: Mapping[str, object]) -> ExperimentalOutcome:
    """Classify one project result without promoting weak signals to success."""

    experiment_id = str(record["experiment_id"])
    isolated_product = bool(record.get("isolated_product", False))
    characterization_complete = bool(record.get("characterization_complete", False))
    detected_target_signal = bool(record.get("detected_target_signal", False))
    target_identity_confirmed = bool(record.get("target_identity_confirmed", False))
    controls_passed = bool(record.get("controls_passed", False))
    analysis_complete = bool(record.get("analysis_complete", False))
    off_target_product = bool(record.get("off_target_product", False))
    analytical_yield = _optional_float(record.get("analytical_yield"))
    isolated_yield = _optional_float(record.get("isolated_yield"))

    if off_target_product:
        status = "off_target"
    elif isolated_product and characterization_complete and target_identity_confirmed:
        status = "confirmed_success"
    elif (
        analytical_yield is not None
        and analytical_yield > 0
        and target_identity_confirmed
        and analysis_complete
    ):
        status = "analytical_success"
    elif detected_target_signal:
        status = "signal_only"
    elif controls_passed and analysis_complete:
        status = "confirmed_failure"
    else:
        status = "inconclusive"

    raw_failure_modes = record.get("observed_failure_modes", ())
    failure_modes = (
        tuple(str(value) for value in raw_failure_modes)
        if isinstance(raw_failure_modes, (list, tuple))
        else ()
    )
    return ExperimentalOutcome(
        experiment_id=experiment_id,
        status=status,
        isolated_product=isolated_product,
        characterization_complete=characterization_complete,
        analytical_yield=analytical_yield,
        isolated_yield=isolated_yield,
        detected_target_signal=detected_target_signal,
        observed_failure_modes=failure_modes,
        notes=str(record.get("notes", "")),
    )


def evaluate_predictions(
    predictions: Sequence[ExperimentCandidate],
    outcomes: Sequence[ExperimentalOutcome],
    baseline: Mapping[str, object],
    *,
    frozen_principle_digest: str,
    candidate_digest: str,
    precision_k: int = 10,
) -> ValidationMetrics:
    """Evaluate only a digest-matched, fully frozen prediction set."""

    _validate_reveal_gate(
        predictions,
        baseline,
        frozen_principle_digest=frozen_principle_digest,
        candidate_digest=candidate_digest,
    )
    if precision_k < 1:
        raise ValueError("precision_k must be positive")

    prediction_by_id = _unique_by_experiment(predictions, "prediction")
    outcome_by_id = _unique_by_experiment(outcomes, "outcome")
    unknown_outcomes = sorted(set(outcome_by_id) - set(prediction_by_id))
    if unknown_outcomes:
        raise ValueError("outcomes lack frozen predictions: " + ", ".join(unknown_outcomes))

    conclusive_statuses = {
        "confirmed_success",
        "analytical_success",
        "signal_only",
        "confirmed_failure",
        "off_target",
    }
    total_predictions = len(predictions)
    conclusive_count = sum(
        outcome.status in conclusive_statuses for outcome in outcome_by_id.values()
    )
    confirmed_count = sum(
        outcome.status == "confirmed_success" for outcome in outcome_by_id.values()
    )
    analytical_count = sum(
        outcome.status == "analytical_success" for outcome in outcome_by_id.values()
    )

    ranked = sorted(predictions, key=lambda item: (item.experiment_priority, item.experiment_id))
    top_predictions = ranked[:precision_k]
    top_confirmed = sum(
        outcome_by_id.get(prediction.experiment_id) is not None
        and outcome_by_id[prediction.experiment_id].status == "confirmed_success"
        for prediction in top_predictions
    )

    positive_predictions = {"explore", "conditional"}
    positive_outcomes = {"confirmed_success", "analytical_success"}
    boundary_correct = 0
    for prediction in predictions:
        outcome = outcome_by_id.get(prediction.experiment_id)
        if (
            outcome is not None
            and outcome.status in conclusive_statuses
            and prediction.predicted_outcome != "insufficient_evidence"
            and (prediction.predicted_outcome in positive_predictions)
            == (outcome.status in positive_outcomes)
        ):
            boundary_correct += 1

    failure_pairs = [
        (prediction, outcome_by_id[prediction.experiment_id])
        for prediction in predictions
        if prediction.experiment_id in outcome_by_id
        and outcome_by_id[prediction.experiment_id].status
        in {"confirmed_failure", "off_target"}
    ]
    agreed_failures = sum(
        bool(set(prediction.predicted_failure_modes) & set(outcome.observed_failure_modes))
        for prediction, outcome in failure_pairs
    )

    abstained_count = sum(
        prediction.predicted_outcome == "insufficient_evidence"
        for prediction in predictions
    )
    baseline_rate = float(baseline.get("confirmed_hit_rate", 0.0))
    confirmed_rate = _ratio(confirmed_count, total_predictions)
    enrichment_value = (
        confirmed_rate / baseline_rate
        if confirmed_rate is not None and baseline_rate > 0
        else None
    )

    return ValidationMetrics(
        confirmed_hit_rate=_metric(confirmed_count, total_predictions),
        analytical_hit_rate=_metric(analytical_count, total_predictions),
        precision_at_k=_metric(top_confirmed, len(top_predictions)),
        enrichment=MetricValue(
            numerator=confirmed_rate or 0.0,
            denominator=baseline_rate,
            value=enrichment_value,
        ),
        boundary_accuracy=_metric(boundary_correct, total_predictions),
        failure_mode_agreement=_metric(agreed_failures, len(failure_pairs)),
        coverage=_metric(conclusive_count, total_predictions),
        abstention=_metric(abstained_count, total_predictions),
    )


def _validate_reveal_gate(
    predictions: Sequence[ExperimentCandidate],
    baseline: Mapping[str, object],
    *,
    frozen_principle_digest: str,
    candidate_digest: str,
) -> None:
    if not predictions or any(item.freeze_status != "frozen" for item in predictions):
        raise ValidationGateError("all candidates must be frozen before outcome reveal")
    if (
        not _SHA256.fullmatch(candidate_digest)
        or candidate_digest != candidate_list_digest(predictions)
        or any(item.candidate_list_digest != candidate_digest for item in predictions)
    ):
        raise ValidationGateError("candidate-list digest does not match frozen predictions")
    expected_principle_digest = str(baseline.get("frozen_principle_digest", ""))
    if (
        not _SHA256.fullmatch(frozen_principle_digest)
        or frozen_principle_digest != expected_principle_digest
        or any(item.principle_digest != frozen_principle_digest for item in predictions)
    ):
        raise ValidationGateError("frozen Principle digest does not match validation baseline")
    expected_scoring_digest = str(baseline.get("scoring_digest", ""))
    if (
        not _SHA256.fullmatch(expected_scoring_digest)
        or any(item.scoring_digest != expected_scoring_digest for item in predictions)
    ):
        raise ValidationGateError("scoring digest does not match frozen predictions")


def _unique_by_experiment(values: Sequence[object], label: str) -> dict[str, object]:
    result: dict[str, object] = {}
    for value in values:
        experiment_id = getattr(value, "experiment_id")
        if experiment_id in result:
            raise ValueError(f"duplicate {label} experiment ID: {experiment_id}")
        result[experiment_id] = value
    return result


def _optional_float(value: object) -> float | None:
    return None if value is None else float(value)


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _metric(numerator: int, denominator: int) -> MetricValue:
    return MetricValue(
        numerator=float(numerator),
        denominator=float(denominator),
        value=_ratio(numerator, denominator),
    )

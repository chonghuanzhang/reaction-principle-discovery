import pytest

from pipeline.candidate_ranking import candidate_list_digest
from pipeline.principle_models import ExperimentCandidate
from pipeline.validation_study import (
    ValidationGateError,
    classify_outcome,
    evaluate_predictions,
)


def _prediction(**updates):
    values = {
        "experiment_id": "EXP-001",
        "family_id": "NF-TEST",
        "electrophile": "trifluoroethyl carbonyl",
        "nucleophile": "thiol",
        "catalyst": "Pd",
        "ligand": "L1",
        "base": "base",
        "solvent": "solvent",
        "temperature": "60 C",
        "time": "8 h",
        "atmosphere": "N2",
        "predicted_outcome": "explore",
        "predicted_failure_modes": (),
        "family_priority": 1,
        "experiment_priority": 1,
        "supporting_principle_ids": ("RP-001",),
        "evidence_ids": ("E001",),
        "minimal_diagnostic_plan": ("19F NMR",),
        "score_components": {"total": 20},
        "total_score": 20,
        "uncertainty": (),
        "freeze_status": "provisional",
    }
    values.update(updates)
    return ExperimentCandidate(**values)


def _frozen_predictions(*predictions):
    digest = candidate_list_digest(predictions)
    return [
        ExperimentCandidate.model_validate(
            {
                **prediction.model_dump(mode="json"),
                "freeze_status": "frozen",
                "freeze_version": "RP-1.0",
                "principle_digest": "a" * 64,
                "scoring_digest": "b" * 64,
                "candidate_list_digest": digest,
            }
        )
        for prediction in predictions
    ]


def test_lcms_only_record_is_signal_only():
    outcome = classify_outcome(
        {
            "experiment_id": "EXP-001",
            "isolated_product": False,
            "characterization_complete": False,
            "analytical_yield": None,
            "isolated_yield": None,
            "detected_target_signal": True,
            "target_identity_confirmed": False,
            "controls_passed": True,
            "analysis_complete": True,
            "off_target_product": False,
            "notes": "candidate LCMS peak only",
        }
    )

    assert outcome.status == "signal_only"
    assert outcome.counts_as_confirmed_success is False


def test_isolated_characterized_product_is_confirmed_success():
    outcome = classify_outcome(
        {
            "experiment_id": "EXP-001",
            "isolated_product": True,
            "characterization_complete": True,
            "analytical_yield": 72.0,
            "isolated_yield": 61.0,
            "detected_target_signal": True,
            "target_identity_confirmed": True,
            "controls_passed": True,
            "analysis_complete": True,
            "off_target_product": False,
            "notes": "isolated and fully characterized",
        }
    )

    assert outcome.status == "confirmed_success"


def test_quantitative_analytical_success_is_reported_separately():
    outcome = classify_outcome(
        {
            "experiment_id": "EXP-001",
            "isolated_product": False,
            "characterization_complete": False,
            "analytical_yield": 18.0,
            "isolated_yield": None,
            "detected_target_signal": True,
            "target_identity_confirmed": True,
            "controls_passed": True,
            "analysis_complete": True,
            "off_target_product": False,
            "notes": "quantitative NMR",
        }
    )

    assert outcome.status == "analytical_success"
    assert outcome.counts_as_confirmed_success is False


def test_metrics_refuse_unfrozen_candidate_list():
    prediction = _prediction()
    digest = candidate_list_digest([prediction])

    with pytest.raises(ValidationGateError, match="frozen"):
        evaluate_predictions(
            [prediction],
            [],
            {
                "confirmed_hit_rate": 0.1,
                "frozen_principle_digest": "a" * 64,
                "scoring_digest": "b" * 64,
            },
            frozen_principle_digest="a" * 64,
            candidate_digest=digest,
        )


def test_metrics_require_matching_candidate_and_principle_digests():
    prediction = _frozen_predictions(_prediction())[0]

    with pytest.raises(ValidationGateError, match="candidate-list digest"):
        evaluate_predictions(
            [prediction],
            [],
            {
                "confirmed_hit_rate": 0.1,
                "frozen_principle_digest": "a" * 64,
                "scoring_digest": "b" * 64,
            },
            frozen_principle_digest="a" * 64,
            candidate_digest="b" * 64,
        )

    with pytest.raises(ValidationGateError, match="Principle digest"):
        evaluate_predictions(
            [prediction],
            [],
            {
                "confirmed_hit_rate": 0.1,
                "frozen_principle_digest": "b" * 64,
                "scoring_digest": "b" * 64,
            },
            frozen_principle_digest="a" * 64,
            candidate_digest=candidate_list_digest([prediction]),
        )


def test_metrics_report_explicit_denominators_and_boundary_performance():
    predictions = _frozen_predictions(
        _prediction(),
        _prediction(
            experiment_id="EXP-002",
            predicted_outcome="exclude",
            predicted_failure_modes=("catalyst poisoning",),
            experiment_priority=2,
            total_score=-5,
            score_components={"total": -5},
        ),
        _prediction(
            experiment_id="EXP-003",
            predicted_outcome="insufficient_evidence",
            experiment_priority=3,
            total_score=0,
            score_components={"total": 0},
        ),
    )
    outcomes = [
        classify_outcome(
            {
                "experiment_id": "EXP-001",
                "isolated_product": True,
                "characterization_complete": True,
                "analytical_yield": 55.0,
                "isolated_yield": 44.0,
                "detected_target_signal": True,
                "target_identity_confirmed": True,
                "controls_passed": True,
                "analysis_complete": True,
                "off_target_product": False,
                "notes": "confirmed",
            }
        ),
        classify_outcome(
            {
                "experiment_id": "EXP-002",
                "isolated_product": False,
                "characterization_complete": False,
                "analytical_yield": None,
                "isolated_yield": None,
                "detected_target_signal": False,
                "target_identity_confirmed": False,
                "controls_passed": True,
                "analysis_complete": True,
                "off_target_product": False,
                "observed_failure_modes": ["catalyst poisoning"],
                "notes": "no target; poisoning control positive",
            }
        ),
    ]

    metrics = evaluate_predictions(
        predictions,
        outcomes,
        {
            "confirmed_hit_rate": 0.25,
            "frozen_principle_digest": "a" * 64,
            "scoring_digest": "b" * 64,
        },
        frozen_principle_digest="a" * 64,
        candidate_digest=candidate_list_digest(predictions),
        precision_k=2,
    )

    assert metrics.confirmed_hit_rate.value == 1 / 3
    assert metrics.analytical_hit_rate.value == 0.0
    assert metrics.precision_at_k.value == 0.5
    assert metrics.enrichment.value == pytest.approx(4 / 3)
    assert metrics.boundary_accuracy.value == 2 / 3
    assert metrics.failure_mode_agreement.value == 1.0
    assert metrics.coverage.value == 2 / 3
    assert metrics.abstention.value == 1 / 3
    assert metrics.confirmed_hit_rate.denominator == 3


def test_metrics_require_one_matching_scoring_digest():
    predictions = _frozen_predictions(_prediction(), _prediction(experiment_id="EXP-002"))
    mixed = [
        predictions[0],
        predictions[1].model_copy(update={"scoring_digest": "c" * 64}),
    ]

    with pytest.raises(ValidationGateError, match="scoring digest"):
        evaluate_predictions(
            mixed,
            [],
            {
                "confirmed_hit_rate": 0.1,
                "frozen_principle_digest": "a" * 64,
                "scoring_digest": "b" * 64,
            },
            frozen_principle_digest="a" * 64,
            candidate_digest=candidate_list_digest(mixed),
        )


def test_inconclusive_top_candidate_remains_in_metric_denominators():
    predictions = _frozen_predictions(_prediction(), _prediction(experiment_id="EXP-002"))
    inconclusive = classify_outcome(
        {
            "experiment_id": "EXP-001",
            "isolated_product": False,
            "characterization_complete": False,
            "detected_target_signal": False,
            "target_identity_confirmed": False,
            "controls_passed": False,
            "analysis_complete": False,
            "off_target_product": False,
            "notes": "analysis failed",
        }
    )

    metrics = evaluate_predictions(
        predictions,
        [inconclusive],
        {
            "confirmed_hit_rate": 0.1,
            "frozen_principle_digest": "a" * 64,
            "scoring_digest": "b" * 64,
        },
        frozen_principle_digest="a" * 64,
        candidate_digest=candidate_list_digest(predictions),
        precision_k=1,
    )

    assert metrics.confirmed_hit_rate.denominator == 2
    assert metrics.precision_at_k.denominator == 1
    assert metrics.boundary_accuracy.denominator == 2
    assert metrics.coverage.value == 0


def test_missing_failure_prediction_counts_as_disagreement():
    predictions = _frozen_predictions(_prediction(predicted_failure_modes=()))
    failure = classify_outcome(
        {
            "experiment_id": "EXP-001",
            "isolated_product": False,
            "characterization_complete": False,
            "detected_target_signal": False,
            "target_identity_confirmed": False,
            "controls_passed": True,
            "analysis_complete": True,
            "off_target_product": False,
            "observed_failure_modes": ["catalyst poisoning"],
            "notes": "controlled failure",
        }
    )

    metrics = evaluate_predictions(
        predictions,
        [failure],
        {
            "confirmed_hit_rate": 0.1,
            "frozen_principle_digest": "a" * 64,
            "scoring_digest": "b" * 64,
        },
        frozen_principle_digest="a" * 64,
        candidate_digest=candidate_list_digest(predictions),
    )

    assert metrics.failure_mode_agreement.denominator == 1
    assert metrics.failure_mode_agreement.value == 0

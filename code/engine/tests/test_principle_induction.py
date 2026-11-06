import pytest

from pipeline.principle_induction import PrincipleInductionError, validate_principle_candidate
from pipeline.principle_models import ReactionPrinciple, TransferabilityAssessment


def _principle(**updates) -> ReactionPrinciple:
    values = {
        "principle_id": "RP-001",
        "title": "Conditional nucleophilic trapping",
        "status": "proposed",
        "claim": "Compatible nucleophiles can trap the activated fluorinated manifold.",
        "mechanistic_basis": ["nucleophilic trapping"],
        "applicable_electrophile_families": ["trifluoroethyl carbonyl"],
        "applicable_nucleophile_families": ["soft nucleophile"],
        "required_reactive_form": "activated nucleophile",
        "catalyst_requirements": ["palladium-compatible"],
        "condition_window": ["moderate base"],
        "structural_promoters": [],
        "structural_inhibitors": [],
        "supporting_seed_evidence": ["SEED-E001"],
        "supporting_transferred_evidence": ["TA-001"],
        "contradictory_evidence": [],
        "known_exceptions": [],
        "predicted_failure_modes": ["catalyst poisoning"],
        "confidence": "medium",
        "experimental_consequence": "Prioritize compatible soft nucleophiles.",
        "falsifying_experiment": "Test a controlled matched series.",
        "review_status": "pending",
        "provenance": {"run_id": "run-1"},
        "freeze_version": None,
    }
    values.update(updates)
    return ReactionPrinciple(**values)


def _transfer(status="transferable") -> TransferabilityAssessment:
    return TransferabilityAssessment(
        assessment_id="TA-001",
        source_evidence_ids=("E001",),
        seed_feature_ids=("SEED-E001",),
        shared_elementary_step="nucleophilic trapping",
        matched_requirements=("soft nucleophile",),
        mismatched_requirements=(),
        blocking_constraints=(),
        transfer_status=status,
        transferable_claim="The trapping step transfers.",
        conditions=(),
        uncertainty=(),
        falsifying_test="Run the matched pair.",
        score_components={"total": 8},
    )


def test_principle_candidate_requires_known_seed_anchor():
    with pytest.raises(PrincipleInductionError, match="unknown seed evidence"):
        validate_principle_candidate(
            _principle(supporting_seed_evidence=["SEED-E999"]),
            known_seed_evidence_ids={"SEED-E001"},
            transfer_assessments={"TA-001": _transfer()},
        )


def test_principle_candidate_requires_known_transfer_assessment():
    with pytest.raises(PrincipleInductionError, match="unknown transfer assessment"):
        validate_principle_candidate(
            _principle(supporting_transferred_evidence=["TA-999"]),
            known_seed_evidence_ids={"SEED-E001"},
            transfer_assessments={"TA-001": _transfer()},
        )


def test_principle_candidate_rejects_unknown_contradictory_assessment():
    with pytest.raises(PrincipleInductionError, match="unknown contradictory assessment"):
        validate_principle_candidate(
            _principle(contradictory_evidence=["TA-999"]),
            known_seed_evidence_ids={"SEED-E001"},
            transfer_assessments={"TA-001": _transfer()},
        )


def test_valid_principle_candidate_preserves_pending_human_review():
    result = validate_principle_candidate(
        _principle(),
        known_seed_evidence_ids={"SEED-E001"},
        transfer_assessments={"TA-001": _transfer()},
    )

    assert result.review_status == "pending"
    assert result.freeze_version is None


@pytest.mark.parametrize("status", ["unknown", "non_transferable"])
def test_principle_candidate_rejects_unsupported_transfer_status(status):
    with pytest.raises(PrincipleInductionError, match="transferable or conditional"):
        validate_principle_candidate(
            _principle(),
            known_seed_evidence_ids={"SEED-E001"},
            transfer_assessments={"TA-001": _transfer(status)},
        )

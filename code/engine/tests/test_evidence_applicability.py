"""Scientific admission checks use hypothetical fixtures, not project outcomes."""
from copy import deepcopy
import importlib.util
from pathlib import Path

MODULE = Path(__file__).parents[1] / "pipeline/evidence_applicability.py"


def assess(record):
    assert MODULE.exists(), "Evidence applicability implementation is missing"
    spec = importlib.util.spec_from_file_location("evidence_applicability", MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.assess_evidence(record)


def fixture(**changes):
    record = {
        "evidence_id": "SYNTHETIC-TEST-01", "catalog_id": "TEST-ONLY",
        "claim": "Hypothetical target product not detected in the stated test.",
        "donor_form_match": "exact", "acceptor_match": "exact",
        "activation_match": "exact", "endpoint_match": "exact",
        "observation_kind": "measured_no_target",
        "source_access": "primary_full_text", "evidence_timing": "later_review",
        "scope": "tested_reaction", "quotation": "Target product was not detected.",
        "locator": "Synthetic test fixture; not a chemical source",
    }
    record.update(changes)
    return record


def test_exact_measured_negative_is_restricted_to_tested_reaction():
    out = assess(fixture())
    assert out["target_negative"] is True
    assert out["assessment"] == "supported_scoped_negative"
    assert out["validated_model_prediction"] is False
    assert out["evidence_timing"] == "later_review"


def test_wrong_endpoint_cannot_negate_earlier_positive_formation():
    out = assess(fixture(endpoint_match="mismatch"))
    assert out["target_negative"] is False
    assert out["assessment"] == "conditional_caution"
    assert "endpoint_match:mismatch" in out["reasons"]


def test_adjacent_carbonyl_system_is_not_exact_target_negative():
    out = assess(fixture(acceptor_match="adjacent"))
    assert out["target_negative"] is False
    assert out["assessment"] == "conditional_caution"


def test_metadata_only_cannot_support_failure_even_with_claimed_exact_matches():
    out = assess(fixture(source_access="metadata_only"))
    assert out["target_negative"] is False
    assert out["assessment"] == "unresolved"


def test_missing_reaction_scope_is_not_a_negative():
    record = fixture()
    del record["acceptor_match"]
    out = assess(record)
    assert out["target_negative"] is False
    assert out["assessment"] == "unresolved"


def test_interpretation_cannot_be_promoted_to_measured_failure():
    out = assess(fixture(observation_kind="author_mechanistic_interpretation"))
    assert out["target_negative"] is False
    assert out["assessment"] == "unsupported_transfer"


def test_positive_is_retained_even_for_mismatched_reaction_domain():
    record = fixture(observation_kind="measured_positive", acceptor_match="mismatch")
    before = deepcopy(record)
    out = assess(record)
    assert out["target_negative"] is False
    assert out["preserve_positive_evidence"] is True
    assert out["assessment"] == "unsupported_transfer"
    assert record == before


def test_universal_element_ban_is_rejected():
    out = assess(fixture(scope="element_class_ban"))
    assert out["target_negative"] is False
    assert out["assessment"] == "unsupported_transfer"
    assert "universal_element_ban_not_admissible" in out["reasons"]


def test_missing_quote_cannot_support_negative():
    out = assess(fixture(quotation=""))
    assert out["target_negative"] is False
    assert out["assessment"] == "unresolved"


def test_author_abstract_positive_preserves_counterevidence():
    out = assess(fixture(source_access="primary_author_abstract", observation_kind="measured_positive"))
    assert out["preserve_positive_evidence"] is True
    assert out["assessment"] == "supported_scoped_positive"


def test_positive_alternative_endpoint_is_preserved_as_positive_in_its_domain():
    out = assess(fixture(observation_kind="measured_alternative_endpoint", endpoint_match="mismatch"))
    assert out["preserve_positive_evidence"] is True
    assert out["target_negative"] is False


def test_suppression_without_zero_is_a_condition_effect_not_target_failure():
    out = assess(fixture(observation_kind="measured_condition_effect"))
    assert out["assessment"] == "conditional_caution"
    assert out["target_negative"] is False


def test_choice_of_element_does_not_change_admission():
    a, b = fixture(element="P"), fixture(element="N")
    assert assess(a) == assess(b)


def test_unknown_timing_is_not_assigned_to_historical_generation():
    record = fixture()
    del record["evidence_timing"]
    out = assess(record)
    assert out["evidence_timing"] == "unknown"
    assert out["validated_model_prediction"] is False

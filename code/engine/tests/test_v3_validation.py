from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml

from pipeline.leakage_audit import (
    LeakagePolicy,
    build_structure_fingerprint_factory,
    derive_structure_fingerprint_receipt,
)
from pipeline.sealed_registry import (
    SealedValidationRecordInput,
    create_registry_commitment,
    create_sealed_validation_registry,
)
from pipeline.v3_freeze import (
    freeze_manifest_digest,
    freeze_stage_one,
    freeze_stage_three,
    freeze_stage_two,
)
from pipeline.v3_validation import (
    FrozenFamilyReference,
    HistoricalNegativeEvidence,
    HistoricalNegativeRecord,
    RevealedSuccessRecord,
    ValidationGateError,
    build_historical_negative_evidence_resolver,
    build_validation_readiness,
    evaluate_retrospective_reveal,
    historical_negative_registry_digest,
    map_revealed_successes,
    resolve_historical_negative_record,
    _require_unique_chemistry_units,
    _verify_negative_resolution,
)
from pipeline.validation_study import MetricAvailability
from tests.test_v3_freeze import (
    _freeze_one_inputs,
    _freeze_three_inputs,
    _freeze_two_inputs,
    _trusted_scored_base,
)
from tests.test_diagnostic_design import _STRUCTURE_FACTORY


_SALT = b"synthetic-task-12-salt"


_ALTERNATE_FACTORY = build_structure_fingerprint_factory(
    factory_id="synthetic-structure-factory",
    receipt_key=b"synthetic-alternate-factory-key",
)


def _mechanism(family):
    return {
        "nucleophilic_center": family.nucleophilic_center,
        "reactive_state": family.reactive_state,
        "bond_forming_mode": family.bond_forming_mode,
        "activation_mode": family.activation_mode,
    }


def _condition(plan):
    condition = plan.conditions[0]
    return {
        key: getattr(condition, key)
        for key in (
            "protonation_state",
            "catalyst_state",
            "medium_state",
            "temperature_state",
            "concentration_state",
            "atmosphere_state",
            "time_state",
        )
    }


def _registry_input(family, plan, index: int = 1) -> SealedValidationRecordInput:
    return SealedValidationRecordInput(
        record_id=f"SYNTHETIC-SUCCESS-{index}",
        terms=(f"synthetic disclosed family {index}",),
        structure_inputs=(
            f"[CH4:{int(hashlib.sha256(family.representative_reactive_state_candidates[0].encode()).hexdigest()[:6], 16)}]",
        ),
        mechanistic_definition=_mechanism(family),
        conditions=_condition(plan),
        outcome="disclosed_success",
        evidence_ids=(f"SYNTHETIC-EVIDENCE-{index}",),
        evidence_basis="traceable_experiment",
    )


def _write_registry(
    path: Path,
    family,
    plan,
    *,
    distinct_id_duplicate: bool = False,
    duplicate: bool = False,
    factory=_STRUCTURE_FACTORY,
    copied_opaque_hash: bool = False,
) -> Path:
    inputs = [_registry_input(family, plan)]
    if distinct_id_duplicate:
        inputs.append(_registry_input(family, plan, 2))
    registry = create_sealed_validation_registry(
        "synthetic-v1", tuple(inputs), factory
    )
    records = [record.model_dump(mode="json") for record in registry.records]
    if duplicate:
        records.append(dict(records[0]))
    if copied_opaque_hash:
        records[0]["structure_fingerprint_receipts"] = []
    path.write_text(
        yaml.safe_dump({"version": "synthetic-v1", "records": records}),
        encoding="utf-8",
    )
    return path


def _frozen_fixture(
    root: Path,
    *,
    duplicate: bool = False,
    distinct_id_duplicate: bool = False,
    registry_factory=_STRUCTURE_FACTORY,
    copied_opaque_hash: bool = False,
):
    preliminary = _freeze_one_inputs(root)
    freeze_stage_one(root, preliminary)
    taxonomy_inputs, saturation, family = _freeze_two_inputs(root)
    freeze_stage_two(root, taxonomy_inputs, saturation)
    ranking_inputs, plans = _freeze_three_inputs(root, family)

    registry = _write_registry(
        root / "synthetic-registry.yaml",
        family,
        plans[0],
        duplicate=duplicate,
        distinct_id_duplicate=distinct_id_duplicate,
        factory=registry_factory,
        copied_opaque_hash=copied_opaque_hash,
    )
    commitment = create_registry_commitment(registry.read_bytes(), _SALT).commitment

    # Rebuild in a sibling root because the registry commitment is immutable from Freeze 1.
    committed_root = root / "committed"
    freeze_stage_one(
        committed_root,
        _freeze_one_inputs(committed_root).model_copy(
            update={"hidden_registry_commitment": commitment}
        ),
    )
    taxonomy_inputs, saturation, family = _freeze_two_inputs(committed_root)
    freeze_stage_two(committed_root, taxonomy_inputs, saturation)
    ranking_inputs, plans = _freeze_three_inputs(
        committed_root,
        family,
        policy=LeakagePolicy(
            policy_id="final-clean",
            structure_fingerprint_factory=_STRUCTURE_FACTORY,
        ),
    )
    freeze_stage_three(committed_root, ranking_inputs, plans)
    committed_registry = _write_registry(
        committed_root / "synthetic-registry.yaml",
        family,
        plans[0],
        duplicate=duplicate,
        distinct_id_duplicate=distinct_id_duplicate,
        factory=registry_factory,
        copied_opaque_hash=copied_opaque_hash,
    )
    return {
        "root": committed_root,
        "registry": committed_registry,
        "taxonomy": taxonomy_inputs.taxonomy,
        "ranking": ranking_inputs.ranking,
        "diagnostics": plans,
        "trusted_digest": freeze_manifest_digest(committed_root, "Freeze 3"),
        "policy": ranking_inputs.leakage_policy,
        "structure_factory": _STRUCTURE_FACTORY,
    }


def _evaluate(fixture, **updates):
    values = {
        "root": fixture["root"],
        "registry_path": fixture["registry"],
        "taxonomy": fixture["taxonomy"],
        "ranking": fixture["ranking"],
        "diagnostics": fixture["diagnostics"],
        "trusted_freeze_three_digest": fixture["trusted_digest"],
        "leakage_policy": fixture["policy"],
        "registry_salt": _SALT,
        "reveal_decision": "reveal",
        "expected_structure_factory": fixture["structure_factory"],
    }
    values.update(updates)
    return evaluate_retrospective_reveal(**values)


def test_reveal_refuses_without_verified_freeze_three(tmp_path):
    registry = tmp_path / "synthetic-registry.yaml"
    registry.write_text("version: synthetic\nrecords: []\n", encoding="utf-8")

    with pytest.raises(ValidationGateError, match="Freeze 3"):
        evaluate_retrospective_reveal(
            root=tmp_path,
            registry_path=registry,
            taxonomy=None,
            ranking=None,
            diagnostics=(),
            trusted_freeze_three_digest="f" * 64,
            leakage_policy=LeakagePolicy(policy_id="synthetic"),
            registry_salt=_SALT,
            reveal_decision="reveal",
        )


def test_recall_metrics_are_computed_after_reveal_only(tmp_path):
    fixture = _frozen_fixture(tmp_path)

    result = _evaluate(fixture)

    assert result.metric_unit == "unique_canonical_structure_mechanism_outcome"
    assert result.family_recall.denominator == 1
    assert result.family_recall.value == 1.0
    assert set(result.top_k_recall) == {"top_5", "top_10", "top_20_percent"}
    assert result.normalized_rank.total_revealed == 1
    assert result.mechanistic_match.denominator == 1
    assert result.condition_proximity.available_count == 1
    assert result.final_leakage_status == "passed"
    assert result.fixed_scope == "SR001_nucleophile_condition"
    assert result.electrophile_expansion_blocked is True


def test_reveal_requires_a_separate_explicit_decision(tmp_path):
    fixture = _frozen_fixture(tmp_path)

    with pytest.raises(ValidationGateError, match="explicit reveal decision"):
        _evaluate(fixture, reveal_decision=None)


def test_wrong_trusted_digest_fails_closed(tmp_path):
    fixture = _frozen_fixture(tmp_path)

    with pytest.raises(ValidationGateError, match="Freeze 3"):
        _evaluate(fixture, trusted_freeze_three_digest="f" * 64)


def test_tampered_registry_fails_commitment_check(tmp_path):
    fixture = _frozen_fixture(tmp_path)
    fixture["registry"].write_text(
        fixture["registry"].read_text(encoding="utf-8") + "# tampered\n",
        encoding="utf-8",
    )

    with pytest.raises(ValidationGateError, match="registry commitment"):
        _evaluate(fixture)


def test_leakage_policy_mismatch_fails_closed(tmp_path):
    fixture = _frozen_fixture(tmp_path)

    with pytest.raises(
        ValidationGateError, match="Freeze 3|structure fingerprint factory"
    ):
        _evaluate(fixture, leakage_policy=LeakagePolicy(policy_id="wrong-policy"))


def test_canonicalizer_substitution_with_same_serialized_policy_fails(tmp_path):
    fixture = _frozen_fixture(tmp_path)
    substituted = fixture["policy"].model_copy(
        update={
            "structure_fingerprint_factory": _ALTERNATE_FACTORY,
        }
    )

    with pytest.raises(ValidationGateError, match="structure.*factory|canonicalizer"):
        _evaluate(fixture, leakage_policy=substituted)


def test_registry_fingerprint_factory_must_match_frozen_factory(tmp_path):
    fixture = _frozen_fixture(tmp_path, registry_factory=_ALTERNATE_FACTORY)

    with pytest.raises(ValidationGateError, match="fingerprint factory"):
        _evaluate(fixture)


def test_copied_opaque_structure_hash_without_factory_receipt_fails(tmp_path):
    fixture = _frozen_fixture(tmp_path, copied_opaque_hash=True)

    with pytest.raises(ValidationGateError, match="fingerprint receipt"):
        _evaluate(fixture)


def test_taxonomy_and_ranking_must_match_frozen_artifacts(tmp_path):
    fixture = _frozen_fixture(tmp_path)
    empty_taxonomy = fixture["taxonomy"].model_copy(update={"families": ()})

    with pytest.raises(ValidationGateError, match="taxonomy"):
        _evaluate(fixture, taxonomy=empty_taxonomy)

    altered_ranking = fixture["ranking"].model_copy(update={"seed": 999})
    with pytest.raises(ValidationGateError, match="ranking"):
        _evaluate(fixture, ranking=altered_ranking)


def test_duplicate_revealed_records_fail_closed(tmp_path):
    fixture = _frozen_fixture(tmp_path, duplicate=True)

    with pytest.raises(ValidationGateError, match="duplicate revealed"):
        _evaluate(fixture)


def test_distinct_ids_cannot_duplicate_one_chemistry_metric_unit(tmp_path):
    fixture = _frozen_fixture(tmp_path, distinct_id_duplicate=True)

    with pytest.raises(ValidationGateError, match="duplicate canonical chemistry"):
        _evaluate(fixture)


def test_overlapping_atomic_structure_mechanism_outcome_units_fail_closed():
    mechanism = {
        "nucleophilic_center": "synthetic center",
        "reactive_state": "synthetic state",
        "bond_forming_mode": "synthetic bond mode",
        "activation_mode": "synthetic activation",
    }
    shared = hashlib.sha256(b"shared synthetic structure").hexdigest()
    additional = hashlib.sha256(b"additional synthetic structure").hexdigest()
    records = (
        RevealedSuccessRecord(
            record_id="SYNTHETIC-SUCCESS-TWO",
            structure_hashes=(shared, additional),
            mechanistic_definition=mechanism,
            conditions=None,
            evidence_ids=("SYNTHETIC-EVIDENCE-TWO",),
        ),
    )

    with pytest.raises(ValidationGateError, match="duplicate canonical chemistry"):
        _require_unique_chemistry_units(records)


def test_disclosed_metric_record_requires_exactly_one_canonical_structure():
    record = RevealedSuccessRecord(
        record_id="SYNTHETIC-MULTI-STRUCTURE",
        structure_hashes=("a" * 64, "b" * 64),
        mechanistic_definition={
            "nucleophilic_center": "synthetic center",
            "reactive_state": "synthetic state",
            "bond_forming_mode": "synthetic bond mode",
            "activation_mode": "synthetic activation",
        },
        conditions=None,
        evidence_ids=("SYNTHETIC-EVIDENCE",),
    )

    with pytest.raises(ValidationGateError, match="exactly one canonical structure"):
        _require_unique_chemistry_units((record,))


def test_ambiguous_structure_mapping_fails_closed():
    shared = hashlib.sha256(b"shared synthetic structure").hexdigest()
    record = RevealedSuccessRecord(
        record_id="SYNTHETIC-SUCCESS",
        structure_hashes=(shared,),
        mechanistic_definition={
            "nucleophilic_center": "synthetic center",
            "reactive_state": "synthetic state",
            "bond_forming_mode": "synthetic bond mode",
            "activation_mode": "synthetic activation",
        },
        conditions=None,
        evidence_ids=("SYNTHETIC-EVIDENCE",),
    )
    references = tuple(
        FrozenFamilyReference(
            family_id=family_id,
            structure_hashes=(shared,),
            mechanistic_definition=record.mechanistic_definition,
            conditions=(),
            primary_rank=index,
        )
        for index, family_id in enumerate(("FAM-A", "FAM-B"), start=1)
    )

    with pytest.raises(ValidationGateError, match="ambiguous structure mapping"):
        map_revealed_successes((record,), references)


def test_non_testable_frozen_family_without_representatives_remains_unmapped():
    reference = FrozenFamilyReference(
        family_id="FAM-SYNTHETIC-EXCLUDED",
        structure_hashes=(),
        mechanistic_definition={
            "nucleophilic_center": "synthetic excluded center",
            "reactive_state": "synthetic excluded state",
            "bond_forming_mode": "synthetic excluded bond mode",
            "activation_mode": "synthetic excluded activation",
        },
        conditions=(),
        primary_rank=None,
        testability="non_testable",
    )
    record = RevealedSuccessRecord(
        record_id="SYNTHETIC-UNMAPPED-SUCCESS",
        structure_hashes=(hashlib.sha256(b"unmapped synthetic").hexdigest(),),
        mechanistic_definition=reference.mechanistic_definition,
        conditions=None,
        evidence_ids=("SYNTHETIC-UNMAPPED-EVIDENCE",),
    )

    adjudication = map_revealed_successes((record,), (reference,))[0]

    assert adjudication.status == "unmapped"
    assert adjudication.structure_candidate_ids == ()


def test_missing_negative_history_creates_required_reminder(tmp_path):
    fixture = _frozen_fixture(tmp_path)

    readiness = build_validation_readiness(
        fixture["root"],
        historical_negatives=(),
        trusted_freeze_three_digest=fixture["trusted_digest"],
        leakage_policy=fixture["policy"],
    )

    assert readiness.historical_negative_status == "missing"
    assert readiness.failure_discrimination_metrics.status == "unavailable"
    assert readiness.prospective_boundary_matrix_required is True
    assert {item.stratum for item in readiness.prospective_boundary_matrix} == {
        "priority_a",
        "priority_b",
        "priority_c",
        "boundary",
        "negative_control",
    }
    assert readiness.workflow_construction_blocked is False
    assert readiness.retrospective_reveal_blocked is False


def test_insufficient_negatives_are_unknown_not_failures_or_zero(tmp_path):
    fixture = _frozen_fixture(tmp_path)
    negative = HistoricalNegativeRecord(
        record_id="SYNTHETIC-NEGATIVE",
        matrix_stratum="priority_a",
        outcome="confirmed_failure",
        evidence_ids=("SYNTHETIC-NEGATIVE-EVIDENCE",),
        evidence_basis="traceable_experiment",
    )
    digest = historical_negative_registry_digest((negative,))

    readiness = build_validation_readiness(
        fixture["root"],
        historical_negatives=(negative,),
        trusted_freeze_three_digest=fixture["trusted_digest"],
        leakage_policy=fixture["policy"],
        trusted_historical_negative_digest=digest,
        negative_evidence_resolver=None,
        trusted_negative_evidence_resolver_digest=None,
    )

    assert readiness.historical_negative_status == "insufficient"
    assert readiness.failure_discrimination_metrics.status == "unavailable"
    assert readiness.failure_discrimination_metrics.value is None
    assert readiness.prospective_boundary_matrix_required is True


def test_model_inference_cannot_establish_a_negative_record():
    with pytest.raises(ValueError, match="model inference"):
        HistoricalNegativeRecord(
            record_id="SYNTHETIC-INFERENCE",
            matrix_stratum="negative_control",
            outcome="confirmed_failure",
            evidence_ids=("MODEL-ONLY",),
            evidence_basis="model_inference",
        )


def test_five_unresolved_negative_claims_remain_unavailable(tmp_path):
    fixture = _frozen_fixture(tmp_path)
    negatives = tuple(
        HistoricalNegativeRecord(
            record_id=f"SYNTHETIC-NEGATIVE-{stratum}",
            matrix_stratum=stratum,
            outcome="confirmed_failure",
            evidence_ids=(f"UNRESOLVED-{stratum}",),
            evidence_basis="traceable_experiment",
        )
        for stratum in (
            "priority_a",
            "priority_b",
            "priority_c",
            "boundary",
            "negative_control",
        )
    )

    readiness = build_validation_readiness(
        fixture["root"],
        historical_negatives=negatives,
        trusted_freeze_three_digest=fixture["trusted_digest"],
        leakage_policy=fixture["policy"],
        trusted_historical_negative_digest=historical_negative_registry_digest(
            negatives
        ),
    )

    assert readiness.historical_negative_status == "insufficient"
    assert readiness.resolved_negative_record_count == 0
    assert readiness.failure_discrimination_metrics.status == "unavailable"
    assert readiness.prospective_boundary_matrix_required is True


def test_authoritative_negative_receipts_enable_complete_history(tmp_path):
    fixture = _frozen_fixture(tmp_path)
    strata = (
        "priority_a",
        "priority_b",
        "priority_c",
        "boundary",
        "negative_control",
    )
    evidence = tuple(
        HistoricalNegativeEvidence(
            evidence_id=f"NEG-EVIDENCE-{stratum}",
            record_id=f"SYNTHETIC-NEGATIVE-{stratum}",
            matrix_stratum=stratum,
            subject_chemistry_digest=hashlib.sha256(
                f"synthetic-chemistry:{stratum}".encode()
            ).hexdigest(),
            outcome="confirmed_failure",
            source_digest=hashlib.sha256(stratum.encode()).hexdigest(),
            source_locator=f"synthetic-source:{stratum}",
        )
        for stratum in strata
    )
    resolver = build_historical_negative_evidence_resolver(evidence)
    negatives = tuple(
        resolve_historical_negative_record(
            HistoricalNegativeRecord(
                record_id=f"SYNTHETIC-NEGATIVE-{stratum}",
                matrix_stratum=stratum,
                subject_chemistry_digest=hashlib.sha256(
                    f"synthetic-chemistry:{stratum}".encode()
                ).hexdigest(),
                outcome="confirmed_failure",
                evidence_ids=(f"NEG-EVIDENCE-{stratum}",),
                evidence_basis="traceable_experiment",
            ),
            resolver,
        )
        for stratum in strata
    )

    readiness = build_validation_readiness(
        fixture["root"],
        historical_negatives=negatives,
        trusted_freeze_three_digest=fixture["trusted_digest"],
        leakage_policy=fixture["policy"],
        trusted_historical_negative_digest=historical_negative_registry_digest(
            negatives
        ),
        negative_evidence_resolver=resolver,
        trusted_negative_evidence_resolver_digest=resolver.content_digest,
    )

    assert readiness.historical_negative_status == "sufficient"
    assert readiness.resolved_negative_record_count == 5
    assert readiness.failure_discrimination_metrics.status == "available"


def test_negative_receipt_cannot_be_reused_for_another_stratum():
    chemistry_digest = hashlib.sha256(b"synthetic negative chemistry").hexdigest()
    resolver = build_historical_negative_evidence_resolver(
        (
            HistoricalNegativeEvidence(
                evidence_id="NEG-EVIDENCE-BOUND",
                record_id="SYNTHETIC-NEGATIVE-BOUND",
                matrix_stratum="priority_a",
                subject_chemistry_digest=chemistry_digest,
                outcome="confirmed_failure",
                source_digest=hashlib.sha256(b"synthetic source").hexdigest(),
                source_locator="synthetic-source:bound",
            ),
        )
    )
    resolved = resolve_historical_negative_record(
        HistoricalNegativeRecord(
            record_id="SYNTHETIC-NEGATIVE-BOUND",
            matrix_stratum="priority_a",
            subject_chemistry_digest=chemistry_digest,
            outcome="confirmed_failure",
            evidence_ids=("NEG-EVIDENCE-BOUND",),
            evidence_basis="traceable_experiment",
        ),
        resolver,
    )
    reused = resolved.model_copy(update={"matrix_stratum": "boundary"})

    with pytest.raises(ValidationGateError, match="resolution receipt"):
        _verify_negative_resolution(reused, resolver)


def test_negative_evidence_subject_must_match_exact_record_chemistry():
    evidence_chemistry = hashlib.sha256(b"synthetic evidence chemistry").hexdigest()
    record_chemistry = hashlib.sha256(b"different synthetic chemistry").hexdigest()
    resolver = build_historical_negative_evidence_resolver(
        (
            HistoricalNegativeEvidence(
                evidence_id="NEG-EVIDENCE-SUBJECT",
                record_id="SYNTHETIC-NEGATIVE-SUBJECT",
                matrix_stratum="priority_b",
                subject_chemistry_digest=evidence_chemistry,
                outcome="confirmed_failure",
                source_digest=hashlib.sha256(b"synthetic source subject").hexdigest(),
                source_locator="synthetic-source:subject",
            ),
        )
    )

    with pytest.raises(ValueError, match="subject chemistry"):
        resolve_historical_negative_record(
            HistoricalNegativeRecord(
                record_id="SYNTHETIC-NEGATIVE-SUBJECT",
                matrix_stratum="priority_b",
                subject_chemistry_digest=record_chemistry,
                outcome="confirmed_failure",
                evidence_ids=("NEG-EVIDENCE-SUBJECT",),
                evidence_basis="traceable_experiment",
            ),
            resolver,
        )


def test_duplicate_authoritative_source_identity_is_rejected_across_evidence_ids():
    source_digest = hashlib.sha256(b"one authoritative synthetic source").hexdigest()
    chemistry_a = hashlib.sha256(b"synthetic chemistry a").hexdigest()
    chemistry_b = hashlib.sha256(b"synthetic chemistry b").hexdigest()
    evidence = (
        HistoricalNegativeEvidence(
            evidence_id="NEG-EVIDENCE-SOURCE-A",
            record_id="SYNTHETIC-NEGATIVE-SOURCE-A",
            matrix_stratum="priority_a",
            subject_chemistry_digest=chemistry_a,
            outcome="confirmed_failure",
            source_digest=source_digest,
            source_locator="synthetic-source:one-authority",
        ),
        HistoricalNegativeEvidence(
            evidence_id="NEG-EVIDENCE-SOURCE-B",
            record_id="SYNTHETIC-NEGATIVE-SOURCE-B",
            matrix_stratum="priority_b",
            subject_chemistry_digest=chemistry_b,
            outcome="confirmed_failure",
            source_digest=source_digest,
            source_locator="synthetic-source:one-authority",
        ),
    )

    with pytest.raises(ValueError, match="duplicate authoritative source"):
        build_historical_negative_evidence_resolver(evidence)


def test_unavailable_metric_cannot_encode_unknown_as_zero():
    with pytest.raises(ValueError, match="unavailable metric"):
        MetricAvailability(status="unavailable", value=0.0, reason="missing evidence")

import pytest
from pydantic import ValidationError

from pipeline.principle_models import (
    EvidenceRef,
    ExperimentalOutcome,
    ExperimentCandidate,
    ReactionPrinciple,
)


def test_evidence_reference_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        EvidenceRef(
            evidence_id="P001-E001",
            source_type="literature",
            source_id="paper-1",
            evidence_label="LITERATURE FACT",
            quotation="Observed target product.",
            locator="PDF page 3",
            unexpected="not allowed",
        )


def test_literature_evidence_requires_a_source_locator():
    with pytest.raises(ValidationError, match="locator"):
        EvidenceRef(
            evidence_id="P001-E001",
            source_type="literature",
            source_id="paper-1",
            evidence_label="LITERATURE FACT",
            quotation="Observed target product.",
            locator=None,
        )


def test_reaction_principle_requires_seed_evidence_anchor():
    with pytest.raises(ValidationError, match="seed evidence"):
        ReactionPrinciple(
            principle_id="RP-001",
            title="Selective trapping",
            status="proposed",
            claim="A compatible nucleophile can trap the activated electrophile.",
            mechanistic_basis=["nucleophilic trapping"],
            applicable_electrophile_families=["trifluoroethyl carbonyl"],
            applicable_nucleophile_families=["thiol"],
            required_reactive_form="nucleophilic sulfur species",
            catalyst_requirements=["compatible with palladium"],
            condition_window=["non-oxidizing"],
            structural_promoters=[],
            structural_inhibitors=[],
            supporting_seed_evidence=[],
            supporting_transferred_evidence=["P001-E001"],
            contradictory_evidence=[],
            known_exceptions=[],
            predicted_failure_modes=["catalyst poisoning"],
            confidence="medium",
            experimental_consequence="Test a thiol under the seed condition window.",
            falsifying_experiment="No trapping across a catalyst-compatible thiol panel.",
            review_status="pending",
            provenance={"run_id": "run-1"},
            freeze_version=None,
        )


def test_confirmed_success_requires_isolation_and_characterization():
    with pytest.raises(ValidationError, match="isolated"):
        ExperimentalOutcome(
            experiment_id="EXP-001",
            status="confirmed_success",
            isolated_product=False,
            characterization_complete=True,
            analytical_yield=42.0,
            isolated_yield=None,
            detected_target_signal=True,
            notes="LCMS and NMR signal only",
        )


def test_signal_only_never_counts_as_confirmed_success():
    outcome = ExperimentalOutcome(
        experiment_id="EXP-002",
        status="signal_only",
        isolated_product=False,
        characterization_complete=False,
        analytical_yield=None,
        isolated_yield=None,
        detected_target_signal=True,
        notes="Candidate LCMS signal",
    )

    assert outcome.counts_as_confirmed_success is False


def test_frozen_candidate_requires_hex_sha256_provenance():
    with pytest.raises(ValidationError, match="pattern"):
        ExperimentCandidate(
            experiment_id="EXP-001",
            family_id="NF-TEST",
            electrophile="E",
            nucleophile="N",
            catalyst="Pd",
            ligand="L",
            base="B",
            solvent="S",
            temperature="60 C",
            time="8 h",
            atmosphere="N2",
            predicted_outcome="explore",
            predicted_failure_modes=(),
            family_priority=1,
            experiment_priority=1,
            supporting_principle_ids=("RP-001",),
            evidence_ids=("E001",),
            minimal_diagnostic_plan=("19F NMR",),
            score_components={"total": 1},
            total_score=1,
            uncertainty=(),
            freeze_status="frozen",
            freeze_version="RP-1.0",
            principle_digest="z" * 64,
            scoring_digest="b" * 64,
            candidate_list_digest="c" * 64,
        )

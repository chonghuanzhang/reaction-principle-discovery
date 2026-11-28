import pytest

from pipeline.full_space_retrieval import (
    FullSpaceRetrievalError,
    build_hypothesis_stage_manifest,
    build_seed_stage_manifest,
    validate_retrieval_sequence,
)
from pipeline.principle_models import PrincipleProvenance, ReactionPrinciple, SeedMechanism
from pipeline.v3_models import FamilyDefinition


def _seed() -> SeedMechanism:
    return SeedMechanism(
        seed_reaction_id="SR-TEST-001",
        reaction_center=["activated C-X center"],
        electrophile_state=["polarized electrophile"],
        nucleophile_state=["reactive partner state"],
        bond_changes=["form C-Nu"],
        reactive_intermediates=["addition intermediate"],
        elementary_steps=["local addition"],
        electronic_requirements=["electron-poor center"],
        steric_requirements=[],
        catalyst_roles=["Lewis-acid activation"],
        condition_window=["low water activity"],
        successful_scope=["seed substrate"],
        failed_scope=[],
        competing_pathways=["premature protonation"],
        evidence_ids=["SE-001"],
        confidence="high",
    )


def _principles() -> tuple[ReactionPrinciple, ...]:
    return (ReactionPrinciple(
        principle_id="RP-001", title="p", status="accepted", claim="claim",
        mechanistic_basis=["local addition"], applicable_electrophile_families=[],
        applicable_nucleophile_families=[], required_reactive_form="activated",
        catalyst_requirements=[], condition_window=[], structural_promoters=[],
        structural_inhibitors=[], supporting_seed_evidence=["SE-001"],
        supporting_transferred_evidence=[], contradictory_evidence=[], known_exceptions=[],
        predicted_failure_modes=[], confidence="medium",
        experimental_consequence="probe", falsifying_experiment="measure",
        review_status="accepted", provenance=PrincipleProvenance(run_id="run"),
        freeze_version=None,
    ),)


def _family() -> FamilyDefinition:
    return FamilyDefinition(
        family_id="FAM-001", nucleophilic_center="heteroatom", reactive_state="deprotonated",
        bond_forming_mode="polar addition", activation_mode="base enabled",
        critical_conditions=("dry",), dominant_failure_modes=("termination",),
    )


def test_hypothesis_retrieval_requires_frozen_open_taxonomy():
    seed_manifest = build_seed_stage_manifest(_seed(), _principles())
    with pytest.raises(FullSpaceRetrievalError, match="taxonomy"):
        build_hypothesis_stage_manifest(families=(), taxonomy_digest=None, prior_seed_manifest=seed_manifest)


def test_seed_manifest_has_no_candidate_family_terms():
    manifest = build_seed_stage_manifest(_seed(), _principles())
    assert manifest.stage == "seed_mechanism"
    assert all(query.candidate_family_terms == () for query in manifest.queries)


def test_hypothesis_manifest_links_frozen_taxonomy_and_seed():
    seed_manifest = build_seed_stage_manifest(_seed(), _principles())
    hypothesis = build_hypothesis_stage_manifest([_family()], "a" * 64, seed_manifest)
    assert hypothesis.predecessor_digest == seed_manifest.query_digest
    assert hypothesis.queries[0].candidate_family_terms[0] == "heteroatom"
    assert validate_retrieval_sequence(seed_manifest, hypothesis) is None


def test_sequence_rejects_tampered_query_provenance():
    seed_manifest = build_seed_stage_manifest(_seed(), _principles())
    hypothesis = build_hypothesis_stage_manifest([_family()], "a" * 64, seed_manifest)
    query = hypothesis.queries[0].model_copy(update={"candidate_family_terms": ("hidden",)})
    tampered = hypothesis.model_copy(update={"queries": (query,)})
    with pytest.raises(FullSpaceRetrievalError, match="digest"):
        validate_retrieval_sequence(seed_manifest, tampered)


def test_hypothesis_builder_rejects_tampered_seed_predecessor():
    seed_manifest = build_seed_stage_manifest(_seed(), _principles())
    tampered_query = seed_manifest.queries[0].model_copy(update={"text": "tampered"})
    tampered_seed = seed_manifest.model_copy(update={"queries": (tampered_query,)})

    with pytest.raises(FullSpaceRetrievalError, match="predecessor.*digest"):
        build_hypothesis_stage_manifest([_family()], "a" * 64, tampered_seed)

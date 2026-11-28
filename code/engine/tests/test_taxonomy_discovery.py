from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import ValidationError

from pipeline.api_client import ApiResult, ApiUsage
from pipeline.literature_retrieval import SearchRecord
from pipeline.principle_models import (
    PrincipleProvenance,
    ReactionPrinciple,
    TransferabilityAssessment,
)
from pipeline.taxonomy_discovery import (
    DISCOVERY_CHANNELS,
    MechanismCoordinateAssignment,
    TaxonomyDiscoveryContext,
    TaxonomyEvidenceRegistry,
    TaxonomyLanePayload,
    TaxonomyModelInvocationConfig,
    TaxonomyProposalError,
    build_taxonomy_cache_key,
    coordinate_assignment_key,
    propose_family_lane,
    propose_family_round,
    validate_center_symmetric_lane_inputs,
    validate_lane_payload,
)
from pipeline.v3_models import (
    ExplorationBriefV3,
    RoleSpecV3,
    TargetTransformationV3,
)


class RecordingClient:
    def __init__(self, payload: dict | None = None):
        self.payload = payload
        self.inputs: list[str] = []
        self.schemas: list[dict] = []
        self.calls = 0

    def create_structured(self, model, input_text, schema, schema_name):
        self.calls += 1
        self.inputs.append(input_text)
        self.schemas.append(schema)
        payload = self.payload
        if payload is None:
            channel = next(item for item in DISCOVERY_CHANNELS if item in input_text)
            evidence_ids = (
                ("RP-001",)
                if channel == "seed_derived"
                else ("TA-001",)
                if channel == "literature_derived"
                else ()
            )
            payload = _synthetic_family_payload(
                f"TMP-{self.calls}", channel=channel, evidence_ids=evidence_ids
            )
        return ApiResult(
            response_id=f"response-{self.calls}",
            returned_model=model,
            status="completed",
            parsed_output=payload,
            usage=ApiUsage(input_tokens=10, output_tokens=5, total_tokens=15),
            transport="test_transport",
        )


def _brief() -> ExplorationBriefV3:
    return ExplorationBriefV3(
        version="3.0",
        study_id="synthetic-open-taxonomy",
        fixed_role=RoleSpecV3(
            role="electrophile", label="fixed seed component", seed_reaction_id="SR001"
        ),
        variable_role=RoleSpecV3(role="nucleophile", label="open reaction partner"),
        target_transformation=TargetTransformationV3(
            new_bond="new bond to variable partner",
            retained_features=("one retained feature",),
        ),
        allowed_evidence_levels=(
            "traceable_external_evidence",
            "model_physical_organic_inference",
            "unknown",
        ),
    )


def _principle() -> ReactionPrinciple:
    return ReactionPrinciple(
        principle_id="RP-001",
        principle_layer="transferable_super",
        title="Local mechanistic requirement",
        status="accepted",
        claim="An accessible reactive partner state can enter the local step.",
        mechanistic_basis=["local bond formation"],
        applicable_electrophile_families=[],
        applicable_nucleophile_families=[],
        required_reactive_form="accessible reactive state",
        catalyst_requirements=["compatible activation"],
        condition_window=["bounded conditions"],
        structural_promoters=[],
        structural_inhibitors=[],
        supporting_seed_evidence=["SE-001"],
        supporting_transferred_evidence=["TA-001"],
        contradictory_evidence=[],
        known_exceptions=[],
        predicted_failure_modes=["premature termination"],
        confidence="medium",
        experimental_consequence="Test local bond formation.",
        falsifying_experiment="Measure whether the local step occurs.",
        review_status="accepted",
        provenance=PrincipleProvenance(run_id="run-v3"),
        freeze_version=None,
    )


def _assessment() -> TransferabilityAssessment:
    return TransferabilityAssessment(
        assessment_id="TA-001",
        source_paper_id="paper-001",
        source_mechanism_id="source::ME-001",
        source_evidence_ids=("source::E-001",),
        seed_feature_ids=("SE-001",),
        shared_elementary_step="local bond formation",
        matched_requirements=("accessible reactive state",),
        mismatched_requirements=(),
        blocking_constraints=(),
        transfer_status="transferable",
        transferable_claim="The local step is observed.",
        conditions=("bounded conditions",),
        uncertainty=(),
        falsifying_test="Probe the local step.",
        score_components={},
    )


def _retrieval_record() -> SearchRecord:
    return SearchRecord(
        record_id="SR-doi-10.1000-synthetic",
        provider="openalex",
        query_id="Q-SEED-001",
        query_text="local bond formation",
        query_origin_type="seed_mechanism",
        origin_ids=("SR001",),
        retrieved_at="2026-08-13",
        hit_count=1,
        doi="10.1000/synthetic",
        title="Synthetic local mechanism record",
        abstract="A synthetic fixture abstract.",
        abstract_available=True,
        access_level="abstract",
        evidence_location="abstract",
        deduplication_key="doi:10.1000/synthetic",
        screening_decision="include",
    )


def _full_space_assignment(center: str) -> MechanismCoordinateAssignment:
    return MechanismCoordinateAssignment(
        nucleophilic_center=center,
        reactive_state="neutral_lone_pair_or_pi_state",
        bond_forming_mode="conjugate_or_vinylic_addition",
        activation_mode="intrinsic_nucleophilicity",
        attack_topology="fluorinated_alkene_carbon",
        target_termination="protonation_then_selective_fluoride_elimination",
    )


def _full_space_context(
    tmp_path,
    *,
    centers: tuple[str, ...] = (
        "carbon_center",
        "nitrogen_center",
        "oxygen_center",
        "sulfur_center",
        "phosphorus_center",
    ),
) -> TaxonomyDiscoveryContext:
    assignments = tuple(_full_space_assignment(center) for center in centers)
    vocabulary = {
        field: tuple(sorted({getattr(item, field) for item in assignments}))
        for field in MechanismCoordinateAssignment.model_fields
    }
    return _context(
        tmp_path,
        prompt_version="taxonomy-discovery-v3.6-complete-coordinate-contract",
        coordinate_vocabulary=vocabulary,
        allowed_coordinate_assignments=assignments,
    )


def _context(tmp_path, **updates) -> TaxonomyDiscoveryContext:
    values = {
        "brief": _brief(),
        "reviewed_principles": (_principle(),),
        "selected_transfer_assessments": (_assessment(),),
        "retrieval_evidence": (_retrieval_record(),),
        "evidence_import_digest": "a" * 64,
        "output_root": tmp_path,
        "model_config": TaxonomyModelInvocationConfig(model="fixture-model"),
        "prompt_version": "taxonomy-discovery-v3.0",
    }
    values.update(updates)
    return TaxonomyDiscoveryContext(**values)


def _synthetic_family_payload(
    proposal_id: str,
    *,
    channel: str = "seed_derived",
    evidence_ids: tuple[str, ...] = ("RP-001",),
) -> dict:
    return {
        "proposals": [
            {
                "proposal_id": proposal_id,
                "mechanistic_definition": {
                    "nucleophilic_center": "synthetic reactive center",
                    "reactive_state": "activated synthetic state",
                    "bond_forming_mode": "local polar bond formation",
                    "activation_mode": "condition enabled",
                    "critical_conditions": ["bounded activation"],
                    "dominant_failure_modes": ["premature termination"],
                },
                "source_channel": channel,
                "evidence_level": (
                    "model_physical_organic_inference"
                    if channel == "model_hypothesis"
                    else "traceable_external_evidence"
                ),
                "evidence_ids": list(evidence_ids),
                "parent_hypothesis": "An accessible state can enter the local step.",
                "representative_reactive_state": "A generated, non-ontological state description.",
                "counterarguments": ["The state may be inaccessible."],
                "unknowns": ["Condition dependence is unresolved."],
                "suggested_search_terms": ["activated state local bond formation"],
            }
        ]
    }


def _empty_evidence_registry() -> TaxonomyEvidenceRegistry:
    return TaxonomyEvidenceRegistry()


def _source_bundle(input_text: str) -> dict:
    encoded = input_text.split("BEGIN_TAXONOMY_LANE_INPUT\n", 1)[1].split(
        "\nEND_TAXONOMY_LANE_INPUT", 1
    )[0]
    return json.loads(encoded)["source_bundle"]


def test_evidence_registry_rejects_cross_channel_id_collisions():
    with pytest.raises(ValidationError, match="disjoint"):
        TaxonomyEvidenceRegistry(
            seed_derived=("COLLIDING-ID",),
            literature_derived=("COLLIDING-ID",),
        )


def test_lane_prompt_does_not_contain_other_lane_output(tmp_path):
    client = RecordingClient(_synthetic_family_payload("TMP-A"))

    propose_family_lane(
        _context(tmp_path), client, lane_id="lane-a", round_id=1, channel="seed_derived"
    )

    assert "lane-b" not in client.inputs[0]
    assert "FAM-B" not in client.inputs[0]


def test_lane_schema_fixes_current_channel_and_evidence_level(tmp_path):
    client = RecordingClient(_synthetic_family_payload("TMP-A"))

    propose_family_lane(
        _context(tmp_path), client, lane_id="lane-a", round_id=1, channel="seed_derived"
    )

    proposal = client.schemas[0]["$defs"]["TaxonomyProposal"]["properties"]
    assert proposal["source_channel"]["const"] == "seed_derived"
    assert proposal["evidence_level"]["const"] == "traceable_external_evidence"
    assert proposal["evidence_ids"]["minItems"] == 1
    assert proposal["evidence_ids"]["items"]["enum"] == ["RP-001"]


def test_lane_rejects_coordinate_mixture_outside_complete_allowlist(tmp_path):
    alpha = MechanismCoordinateAssignment(
        nucleophilic_center="center-alpha",
        reactive_state="state-alpha",
        bond_forming_mode="mode-alpha",
        activation_mode="activation-alpha",
        attack_topology="topology-alpha",
        target_termination="termination-alpha",
    )
    beta = alpha.model_copy(
        update={
            "reactive_state": "state-beta",
            "bond_forming_mode": "mode-beta",
            "activation_mode": "activation-beta",
            "attack_topology": "topology-beta",
            "target_termination": "termination-beta",
        }
    )
    mixed = alpha.model_copy(update={"reactive_state": "state-beta"})
    payload = _synthetic_family_payload("TMP-MIXED")
    payload["proposals"][0]["coordinate_assignment"] = mixed.model_dump(mode="json")
    vocabulary = {
        field: tuple(sorted({getattr(alpha, field), getattr(beta, field)}))
        for field in MechanismCoordinateAssignment.model_fields
    }
    context = _context(
        tmp_path,
        coordinate_vocabulary=vocabulary,
        allowed_coordinate_assignments=(alpha, beta),
    )

    with pytest.raises(TaxonomyProposalError, match="complete allowed assignment"):
        propose_family_lane(
            context,
            RecordingClient(payload),
            lane_id="lane-a",
            round_id=1,
            channel="seed_derived",
        )


def test_lane_schema_constrains_complete_coordinate_assignments(tmp_path):
    assignment = MechanismCoordinateAssignment(
        nucleophilic_center="center-alpha",
        reactive_state="state-alpha",
        bond_forming_mode="mode-alpha",
        activation_mode="activation-alpha",
        attack_topology="topology-alpha",
        target_termination="termination-alpha",
    )
    payload = _synthetic_family_payload("TMP-ALLOWED")
    payload["proposals"][0]["coordinate_assignment_key"] = coordinate_assignment_key(
        assignment
    )
    vocabulary = {
        field: (getattr(assignment, field),)
        for field in MechanismCoordinateAssignment.model_fields
    }
    client = RecordingClient(payload)

    propose_family_lane(
        _context(
            tmp_path,
            coordinate_vocabulary=vocabulary,
            allowed_coordinate_assignments=(assignment,),
        ),
        client,
        lane_id="lane-a",
        round_id=1,
        channel="seed_derived",
    )

    proposal_schema = client.schemas[0]["$defs"]["TaxonomyProposal"]
    assert proposal_schema["properties"]["coordinate_assignment_key"]["enum"] == [
        coordinate_assignment_key(assignment)
    ]
    assert "coordinate_assignment_key" in proposal_schema["required"]
    raw = json.loads(
        (
            tmp_path
            / "derived/principles_v3/taxonomy/round-1/lane-a/seed_derived/raw.json"
        ).read_text()
    )
    assert raw["model_output"]["proposals"][0]["coordinate_assignment"] == assignment.model_dump(
        mode="json"
    )


def test_full_space_lane_rejects_asymmetric_center_contract(tmp_path):
    context = _full_space_context(
        tmp_path, centers=("nitrogen_center", "oxygen_center")
    )
    with pytest.raises(TaxonomyProposalError, match="symmetric"):
        validate_center_symmetric_lane_inputs(
            context,
            (
                "carbon_center",
                "nitrogen_center",
                "oxygen_center",
                "sulfur_center",
                "phosphorus_center",
            ),
        )


def test_full_space_prompt_is_open_and_center_symmetric(tmp_path):
    assignment = _full_space_assignment("carbon_center")
    payload = _synthetic_family_payload("TMP-FS")
    payload["proposals"][0]["coordinate_assignment_key"] = coordinate_assignment_key(
        assignment
    )
    client = RecordingClient(payload)

    propose_family_lane(
        _full_space_context(tmp_path),
        client,
        lane_id="lane-a",
        round_id=1,
        channel="seed_derived",
    )

    prompt_text = Path("config/prompts/full_space_taxonomy_v3_6.md").read_text().strip()
    assert client.inputs[0].startswith(prompt_text)
    assert "SR001" not in prompt_text
    assert "successful family" in prompt_text


@pytest.mark.parametrize(
    "forbidden",
    (
        {"prior_lane_outputs": "FAM-B"},
        {"peer_results": ["FAM-B"]},
        {"context": {"lane-b": "FAM-B"}},
    ),
)
def test_model_invocation_config_rejects_peer_and_nested_context(forbidden):
    with pytest.raises(ValidationError):
        TaxonomyModelInvocationConfig.model_validate(
            {"model": "fixture-model", **forbidden}
        )


def test_model_invocation_config_subclass_cannot_add_peer_cache_inputs(tmp_path):
    class PeerConfig(TaxonomyModelInvocationConfig):
        peer_results: tuple[str, ...]

    peer_config = PeerConfig(model="fixture-model", peer_results=("FAM-B",))

    with pytest.raises(TypeError, match="exact TaxonomyModelInvocationConfig"):
        _context(tmp_path, model_config=peer_config)

    base = {
        "brief_digest": "a" * 64,
        "evidence_import_digest": "b" * 64,
        "principle_digest": "c" * 64,
        "transfer_digest": "d" * 64,
        "retrieval_digest": "e" * 64,
        "lane_id": "lane-a",
        "channel": "seed_derived",
        "round_id": 1,
        "prompt_version": "prompt-v1",
        "prompt_digest": "f" * 64,
        "schema_version": "schema-v1",
        "model_config": peer_config,
    }
    with pytest.raises(TypeError, match="exact TaxonomyModelInvocationConfig"):
        build_taxonomy_cache_key(**base)


def test_channel_prompts_receive_only_their_permitted_source_bundle(tmp_path):
    seed_client = RecordingClient(_synthetic_family_payload("TMP-S"))
    literature_client = RecordingClient(
        _synthetic_family_payload(
            "TMP-L", channel="literature_derived", evidence_ids=("TA-001",)
        )
    )
    hypothesis_client = RecordingClient(
        _synthetic_family_payload(
            "TMP-H", channel="model_hypothesis", evidence_ids=()
        )
    )
    context = _context(tmp_path)

    propose_family_lane(context, seed_client, lane_id="lane-a", round_id=1, channel="seed_derived")
    propose_family_lane(
        context, literature_client, lane_id="lane-a", round_id=1, channel="literature_derived"
    )
    propose_family_lane(
        context, hypothesis_client, lane_id="lane-a", round_id=1, channel="model_hypothesis"
    )

    assert "RP-001" in seed_client.inputs[0]
    assert "TA-001" not in seed_client.inputs[0]
    assert "SR-doi-10.1000-synthetic" not in seed_client.inputs[0]
    assert "TA-001" in literature_client.inputs[0]
    assert "SR-doi-10.1000-synthetic" in literature_client.inputs[0]
    assert "RP-001" not in hypothesis_client.inputs[0]
    assert "TA-001" not in hypothesis_client.inputs[0]


def test_seed_prompt_projects_out_legacy_named_family_fields(tmp_path):
    sealed_label = "SYNTHETIC_PRELOADED_FAMILY_LABEL"
    principle = _principle().model_copy(
        update={
            "title": sealed_label,
            "applicable_electrophile_families": [sealed_label],
            "applicable_nucleophile_families": [sealed_label],
        }
    )
    context = replace(_context(tmp_path), reviewed_principles=(principle,))
    client = RecordingClient(_synthetic_family_payload("TMP-S"))

    propose_family_lane(
        context, client, lane_id="lane-a", round_id=1, channel="seed_derived"
    )

    assert sealed_label not in client.inputs[0]


def test_model_hypothesis_cannot_claim_external_evidence():
    payload = _synthetic_family_payload(
        "TMP-H", channel="model_hypothesis", evidence_ids=("E-1",)
    )

    with pytest.raises(TaxonomyProposalError, match="model hypothesis"):
        validate_lane_payload(payload, _empty_evidence_registry())


def test_model_hypothesis_cannot_declare_external_evidence_level():
    payload = _synthetic_family_payload(
        "TMP-H", channel="model_hypothesis", evidence_ids=()
    )
    payload["proposals"][0]["evidence_level"] = "traceable_external_evidence"

    with pytest.raises(TaxonomyProposalError, match="inference evidence level"):
        validate_lane_payload(payload, _empty_evidence_registry())


@pytest.mark.parametrize(
    ("forbidden_key", "value"),
    [
        ("family_id", "FAM-STABLE"),
        ("total_score", 99),
        ("rank", 1),
        ("classification", "priority_a"),
        ("freeze_state", "frozen"),
    ],
)
def test_model_cannot_assign_final_identity_or_decision_fields(forbidden_key, value):
    payload = _synthetic_family_payload("TMP-A")
    payload["proposals"][0][forbidden_key] = value

    with pytest.raises(ValidationError):
        TaxonomyLanePayload.model_validate(payload)


def test_evidence_references_are_channel_scoped():
    registry = TaxonomyEvidenceRegistry(
        seed_derived=("RP-001",), literature_derived=("TA-001", "SR-001")
    )

    validated = validate_lane_payload(_synthetic_family_payload("TMP-S"), registry)
    assert validated.proposals[0].evidence_ids == ("RP-001",)

    wrong = _synthetic_family_payload("TMP-L", channel="literature_derived")
    with pytest.raises(TaxonomyProposalError, match="literature_derived"):
        validate_lane_payload(wrong, registry)

    seed_with_transfer_id = _synthetic_family_payload(
        "TMP-S2", channel="seed_derived", evidence_ids=("TA-001",)
    )
    with pytest.raises(TaxonomyProposalError, match="seed_derived"):
        validate_lane_payload(seed_with_transfer_id, registry)


@pytest.mark.parametrize("channel", ("seed_derived", "literature_derived"))
def test_evidence_derived_proposals_require_channel_evidence(channel):
    payload = _synthetic_family_payload(
        "TMP-E", channel=channel, evidence_ids=()
    )

    with pytest.raises(TaxonomyProposalError, match="requires channel evidence"):
        validate_lane_payload(payload, _empty_evidence_registry())


def test_lane_output_is_cached_at_v3_taxonomy_path(tmp_path):
    client = RecordingClient(_synthetic_family_payload("TMP-A"))
    context = _context(tmp_path)

    first = propose_family_lane(
        context, client, lane_id="lane-a", round_id=2, channel="seed_derived"
    )
    second = propose_family_lane(
        context, client, lane_id="lane-a", round_id=2, channel="seed_derived"
    )

    lane_root = tmp_path / "derived/principles_v3/taxonomy/round-2/lane-a/seed_derived"
    assert first.status == "validated"
    assert second.status == "reused"
    assert client.calls == 1
    raw = json.loads((lane_root / "raw.json").read_text())
    assert raw["cache_key"] == first.cache_key
    assert raw["api"]["transport"] == "test_transport"
    assert json.loads((lane_root / "validated.json").read_text())["cache_key"] == first.cache_key


def test_literature_lane_rejects_query_ids_as_evidence(tmp_path):
    client = RecordingClient(
        _synthetic_family_payload(
            "TMP-L", channel="literature_derived", evidence_ids=("Q-SEED-001",)
        )
    )

    with pytest.raises(TaxonomyProposalError, match="outside its channel"):
        propose_family_lane(
            _context(tmp_path),
            client,
            lane_id="lane-a",
            round_id=1,
            channel="literature_derived",
        )


def test_prompt_allowed_evidence_ids_exactly_match_validator_registry(tmp_path):
    client = RecordingClient(
        _synthetic_family_payload(
            "TMP-L", channel="literature_derived", evidence_ids=("TA-001",)
        )
    )
    propose_family_lane(
        _context(tmp_path),
        client,
        lane_id="lane-a",
        round_id=1,
        channel="literature_derived",
    )

    bundle = _source_bundle(client.inputs[0])
    assert bundle["allowed_evidence_ids"] == [
        "SR-doi-10.1000-synthetic",
        "TA-001",
    ]
    assert "source::E-001" in client.inputs[0]
    assert "source::E-001" not in bundle["allowed_evidence_ids"]
    invalid = _synthetic_family_payload(
        "TMP-L2",
        channel="literature_derived",
        evidence_ids=("source::E-001",),
    )
    with pytest.raises(TaxonomyProposalError, match="outside its channel"):
        validate_lane_payload(
            invalid,
            TaxonomyEvidenceRegistry(
                literature_derived=tuple(bundle["allowed_evidence_ids"])
            ),
        )


def test_literature_lane_rejects_unscreened_retrieval_records(tmp_path):
    pending = _retrieval_record().model_copy(update={"screening_decision": "pending"})
    context = replace(_context(tmp_path), retrieval_evidence=(pending,))
    client = RecordingClient(
        _synthetic_family_payload(
            "TMP-L",
            channel="literature_derived",
            evidence_ids=(pending.record_id,),
        )
    )

    with pytest.raises(TaxonomyProposalError, match="outside its channel"):
        propose_family_lane(
            context,
            client,
            lane_id="lane-a",
            round_id=1,
            channel="literature_derived",
        )


def test_failed_cache_replacement_cannot_leave_stale_validated_output(tmp_path):
    context = _context(tmp_path)
    propose_family_lane(
        context,
        RecordingClient(_synthetic_family_payload("TMP-S")),
        lane_id="lane-a",
        round_id=1,
        channel="seed_derived",
    )
    changed = replace(context, prompt_version="taxonomy-discovery-v3.1")

    with pytest.raises(TaxonomyProposalError, match="invalid taxonomy lane schema"):
        propose_family_lane(
            changed,
            RecordingClient({"proposals": [{"invalid": True}]}),
            lane_id="lane-a",
            round_id=1,
            channel="seed_derived",
        )

    root = tmp_path / "derived/principles_v3/taxonomy/round-1/lane-a/seed_derived"
    assert not (root / "validated.json").exists()
    assert json.loads((root / "raw.json").read_text())["cache_key"] != ""


def test_cache_key_includes_all_upstream_lane_and_model_inputs():
    base = {
        "brief_digest": "a" * 64,
        "evidence_import_digest": "b" * 64,
        "principle_digest": "c" * 64,
        "transfer_digest": "d" * 64,
        "retrieval_digest": "e" * 64,
        "lane_id": "lane-a",
        "channel": "seed_derived",
        "round_id": 1,
        "prompt_version": "prompt-v1",
        "prompt_digest": "f" * 64,
        "schema_version": "schema-v1",
        "model_config": TaxonomyModelInvocationConfig(model="fixture"),
    }
    changes = {
        "brief_digest": "1" * 64,
        "evidence_import_digest": "2" * 64,
        "principle_digest": "3" * 64,
        "transfer_digest": "4" * 64,
        "retrieval_digest": "5" * 64,
        "lane_id": "lane-b",
        "channel": "literature_derived",
        "round_id": 2,
        "prompt_version": "prompt-v2",
        "prompt_digest": "6" * 64,
        "schema_version": "schema-v2",
        "model_config": TaxonomyModelInvocationConfig(model="fixture-2"),
    }
    original = build_taxonomy_cache_key(**base)

    for name, changed in changes.items():
        assert build_taxonomy_cache_key(**(base | {name: changed})) != original, name


def test_lane_a_cache_identity_is_independent_of_lane_b_results(tmp_path):
    context = _context(tmp_path)
    lane_a_client = RecordingClient(_synthetic_family_payload("TMP-A"))
    first = propose_family_lane(
        context,
        lane_a_client,
        lane_id="lane-a",
        round_id=1,
        channel="seed_derived",
    )
    propose_family_lane(
        context,
        RecordingClient(_synthetic_family_payload("FAM-B")),
        lane_id="lane-b",
        round_id=1,
        channel="seed_derived",
    )
    unused_client = RecordingClient(_synthetic_family_payload("SHOULD-NOT-RUN"))
    second = propose_family_lane(
        context,
        unused_client,
        lane_id="lane-a",
        round_id=1,
        channel="seed_derived",
    )

    assert second.cache_key == first.cache_key
    assert second.status == "reused"
    assert unused_client.calls == 0


def test_round_requires_two_lanes_and_runs_all_three_channels(tmp_path):
    context = _context(tmp_path)
    with pytest.raises(TaxonomyProposalError, match="at least two"):
        propose_family_round(context, RecordingClient(), lane_ids=("lane-a",), round_id=1)

    client = RecordingClient()
    results = propose_family_round(
        context, client, lane_ids=("lane-a", "lane-b"), round_id=1
    )

    assert len(results) == 6
    assert {(result.lane_id, result.channel) for result in results} == {
        (lane, channel)
        for lane in ("lane-a", "lane-b")
        for channel in DISCOVERY_CHANNELS
    }
    assert client.calls == 6


def test_context_requires_reviewed_principles(tmp_path):
    pending = _principle().model_copy(update={"review_status": "pending"})
    context = replace(_context(tmp_path), reviewed_principles=(pending,))

    with pytest.raises(TaxonomyProposalError, match="reviewed Principles"):
        propose_family_lane(
            context,
            RecordingClient(_synthetic_family_payload("TMP-A")),
            lane_id="lane-a",
            round_id=1,
            channel="seed_derived",
        )

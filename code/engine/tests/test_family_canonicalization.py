from __future__ import annotations

import json
import re

import pytest
from pydantic import ValidationError

import pipeline.family_canonicalization as family_canonicalization
from pipeline.api_client import ApiClientError
from pipeline.family_canonicalization import (
    MAX_ADJUDICATION_BATCH_SIZE,
    MAX_ADJUDICATION_CALLS,
    CanonicalTaxonomy,
    CanonicalizationError,
    canonicalize_proposals,
)
from pipeline.taxonomy_discovery import (
    MechanismCoordinateAssignment,
    MechanisticProposalDefinition,
    TaxonomyLaneResult,
    TaxonomyProposal,
)


def _proposal(
    proposal_id: str,
    *,
    alias: str,
    reactive_state: str = "Neutral donor state",
    bond_forming_mode: str = "Direct addition",
    activation_mode: str = "Base activation",
    conditions: tuple[str, ...] = ("Dry solvent", "Mild base"),
    failures: tuple[str, ...] = ("Competitive decomposition",),
    nucleophilic_center: str = "Heteroatom center",
    evidence_ids: tuple[str, ...] = ("EV-1",),
    counterarguments: tuple[str, ...] = (),
    unknowns: tuple[str, ...] = (),
    coordinate_assignment: MechanismCoordinateAssignment | None = None,
) -> TaxonomyProposal:
    return TaxonomyProposal(
        proposal_id=proposal_id,
        mechanistic_definition=MechanisticProposalDefinition(
            nucleophilic_center=nucleophilic_center,
            reactive_state=reactive_state,
            bond_forming_mode=bond_forming_mode,
            activation_mode=activation_mode,
            critical_conditions=conditions,
            dominant_failure_modes=failures,
        ),
        coordinate_assignment=coordinate_assignment,
        source_channel="seed_derived",
        evidence_level="traceable_external_evidence",
        evidence_ids=evidence_ids,
        parent_hypothesis=alias,
        representative_reactive_state=f"representative {alias}",
        counterarguments=counterarguments,
        unknowns=unknowns,
        suggested_search_terms=("mechanism query",),
    )


def _lane(
    lane_id: str,
    *proposals: TaxonomyProposal,
    round_id: int = 1,
) -> TaxonomyLaneResult:
    return TaxonomyLaneResult(
        status="validated",
        cache_key=(lane_id.encode("utf-8").hex() + "0" * 64)[:64],
        lane_id=lane_id,
        round_id=round_id,
        channel="seed_derived",
        proposals=proposals,
        usage={"input_tokens": None, "output_tokens": None, "total_tokens": None},
    )


def test_equivalent_mechanism_definitions_merge_despite_names():
    first = _proposal("PROP-A", alias="alias-a")
    second = _proposal(
        "PROP-B",
        alias="alias-b",
        reactive_state=" neutral   donor STATE ",
        bond_forming_mode="direct addition",
        conditions=("mild base", "dry solvent"),
    )

    taxonomy = canonicalize_proposals(
        [_lane("lane-a", first), _lane("lane-b", second)], None
    )

    assert len(taxonomy.families) == 1
    assert taxonomy.decisions[0].decision == "merge"
    assert taxonomy.families[0].aliases == ("alias-a", "alias-b")
    assert taxonomy.families[0].proposal_ids == ("PROP-A", "PROP-B")


def test_exact_merge_precedes_retained_proposal_unknowns_in_decision_log():
    first = _proposal(
        "PROP-A",
        alias="alias-a",
        unknowns=("Condition boundary remains unresolved",),
    )
    second = _proposal("PROP-B", alias="alias-b")

    taxonomy = canonicalize_proposals(
        [_lane("lane-a", first), _lane("lane-b", second)], None
    )

    assert taxonomy.decisions[0].decision == "merge"
    assert taxonomy.unresolved_proposal_ids == ("PROP-A",)


def test_different_reactive_state_wording_is_unresolved_without_adjudicator():
    neutral = _proposal("PROP-N", alias="shared-name", reactive_state="neutral")
    radical = _proposal("PROP-R", alias="shared-name", reactive_state="radical")

    taxonomy = canonicalize_proposals(
        [_lane("lane-a", neutral), _lane("lane-b", radical)], None
    )

    assert len(taxonomy.families) == 2
    assert taxonomy.decisions[0].decision == "unresolved"


def test_different_bond_forming_wording_is_unresolved_without_adjudicator():
    direct = _proposal("PROP-D", alias="same", bond_forming_mode="direct addition")
    transfer = _proposal("PROP-T", alias="same", bond_forming_mode="group transfer")

    taxonomy = canonicalize_proposals(
        [_lane("lane-a", direct), _lane("lane-b", transfer)], None
    )

    assert len(taxonomy.families) == 2
    assert taxonomy.decisions[0].decision == "unresolved"


def test_unresolved_proposal_is_preserved():
    ambiguous = _proposal(
        "PROP-X",
        alias="ambiguous family",
        unknowns=("Reactive state assignment remains ambiguous",),
    )

    taxonomy = canonicalize_proposals([_lane("lane-a", ambiguous)], None)

    assert taxonomy.unresolved_proposal_ids == ("PROP-X",)
    assert taxonomy.families[0].proposal_ids == ("PROP-X",)
    assert taxonomy.families[0].unresolved_disagreements == (
        "Reactive state assignment remains ambiguous",
    )


def test_family_id_uses_canonical_six_field_mechanism_payload():
    proposal = _proposal("PROP-A", alias="alias-a")

    taxonomy = canonicalize_proposals([_lane("lane-a", proposal)], None)
    renamed = canonicalize_proposals(
        [_lane("lane-z", proposal.model_copy(update={"parent_hypothesis": "renamed"}))],
        None,
    )

    assert re.fullmatch(r"NFV3-[0-9a-f]{12}", taxonomy.families[0].family_id)
    assert taxonomy.families[0].family_id == renamed.families[0].family_id


def test_canonical_family_preserves_proposal_provenance_and_evidence():
    first = _proposal("PROP-A", alias="alias-a", evidence_ids=("EV-2",))
    second = _proposal("PROP-B", alias="alias-b", evidence_ids=("EV-1", "EV-2"))

    taxonomy = canonicalize_proposals(
        [_lane("lane-b", second), _lane("lane-a", first)], None
    )
    family = taxonomy.families[0]

    assert family.evidence_ids == ("EV-1", "EV-2")
    assert tuple(
        (
            item.proposal_id,
            item.lane_id,
            item.channel,
            item.round_id,
            item.evidence_level,
            item.evidence_ids,
        )
        for item in family.proposal_provenance
    ) == (
        (
            "PROP-A",
            "lane-a",
            "seed_derived",
            1,
            "traceable_external_evidence",
            ("EV-2",),
        ),
        (
            "PROP-B",
            "lane-b",
            "seed_derived",
            1,
            "traceable_external_evidence",
            ("EV-1", "EV-2"),
        ),
    )


def test_canonicalization_rejects_mixed_round_results():
    first = _proposal("PROP-A", alias="a")
    second = _proposal("PROP-B", alias="b")

    with pytest.raises(CanonicalizationError, match="one taxonomy round"):
        canonicalize_proposals(
            [_lane("lane-a", first, round_id=1), _lane("lane-b", second, round_id=2)],
            None,
        )


def test_output_is_byte_stable_under_lane_and_proposal_reordering():
    first = _proposal("PROP-A", alias="alias-a", evidence_ids=("EV-2",))
    second = _proposal("PROP-B", alias="alias-b", evidence_ids=("EV-1",))
    third = _proposal("PROP-C", alias="alias-c", reactive_state="radical")
    forward = [_lane("lane-a", first, second), _lane("lane-b", third)]
    reverse = [_lane("lane-b", third), _lane("lane-a", second, first)]

    assert canonicalize_proposals(forward, None).model_dump_json() == (
        canonicalize_proposals(reverse, None).model_dump_json()
    )


class _FakeAdjudicator:
    def __init__(self, output: dict[str, object]):
        self.output = output
        self.calls: list[tuple[str, str, dict, str]] = []

    def create_structured(
        self, model: str, input_text: str, schema: dict, schema_name: str
    ):
        self.calls.append((model, input_text, schema, schema_name))
        return type("Result", (), {"parsed_output": self.output})()


def _judgment(
    state: str, evidence_ids: tuple[str, ...] = ("EV-1",)
) -> dict[str, object]:
    return {
        "state": state,
        "evidence_ids": [] if state == "unknown" else list(evidence_ids),
    }


def _comparison(
    proposal_ids: tuple[str, str],
    outcome: str,
    *,
    evidence_ids: tuple[str, ...] = ("EV-1",),
) -> dict[str, object]:
    if outcome == "merge":
        states = ("support", "support", "unknown", "unknown", "contradiction")
    elif outcome == "parent_left":
        states = (
            "contradiction",
            "support",
            "support",
            "contradiction",
            "support",
        )
    elif outcome == "parent_right":
        states = (
            "contradiction",
            "support",
            "contradiction",
            "support",
            "support",
        )
    elif outcome == "split":
        states = (
            "contradiction",
            "support",
            "contradiction",
            "contradiction",
            "support",
        )
    elif outcome == "distinct":
        states = (
            "contradiction",
            "contradiction",
            "contradiction",
            "contradiction",
            "support",
        )
    else:
        states = ("unknown",) * 5
    return {
        "compared_proposal_ids": list(proposal_ids),
        "same_mechanism": _judgment(states[0], evidence_ids),
        "shared_scope": _judgment(states[1], evidence_ids),
        "left_contains_right": _judgment(states[2], evidence_ids),
        "right_contains_left": _judgment(states[3], evidence_ids),
        "experimentally_distinguishable": _judgment(states[4], evidence_ids),
        "uncertainties": (
            ["The comparison remains unresolved."] if outcome == "unresolved" else []
        ),
    }


def _comparison_input(input_text: str) -> dict[str, object]:
    encoded = input_text.split("BEGIN_FAMILY_COMPARISONS\n", 1)[1].split(
        "\nEND_FAMILY_COMPARISONS", 1
    )[0]
    return json.loads(encoded)


def test_adjudicated_parent_child_relation_is_preserved_on_both_families():
    parent = _proposal("PROP-P", alias="broad", activation_mode="general activation")
    child = _proposal("PROP-C", alias="narrow", activation_mode="specific activation")
    adjudicator = _FakeAdjudicator(
        {"comparisons": [_comparison(("PROP-C", "PROP-P"), "parent_right")]}
    )

    taxonomy = canonicalize_proposals(
        [_lane("lane-p", parent), _lane("lane-c", child)], adjudicator
    )
    by_alias = {family.aliases[0]: family for family in taxonomy.families}

    assert by_alias["narrow"].parent_family_ids == (by_alias["broad"].family_id,)
    assert by_alias["broad"].child_family_ids == (by_alias["narrow"].family_id,)
    assert taxonomy.decisions[0].compared_proposal_ids == ("PROP-C", "PROP-P")
    assert adjudicator.calls[0][0] == "gpt-5.6-terra"


def test_invented_comparison_ids_fall_back_to_explicit_unresolved_pair():
    first = _proposal("PROP-A", alias="a", activation_mode="activation a")
    second = _proposal("PROP-B", alias="b", activation_mode="activation b")
    adjudicator = _FakeAdjudicator(
        {"comparisons": [_comparison(("PROP-A", "PROP-Z"), "distinct")]}
    )

    taxonomy = canonicalize_proposals(
        [_lane("lane-a", first), _lane("lane-b", second)], adjudicator
    )

    assert taxonomy.decisions[0].decision == "unresolved"
    assert taxonomy.decisions[0].compared_proposal_ids == ("PROP-A", "PROP-B")
    assert "structured_output_validation_failed" in taxonomy.decisions[
        0
    ].unresolved_disagreements[0]


def test_adjudicator_schema_has_no_final_decision_action():
    first = _proposal("PROP-A", alias="a", activation_mode="activation a")
    second = _proposal("PROP-B", alias="b", activation_mode="activation b")
    adjudicator = _FakeAdjudicator(
        {
            "decisions": [
                {
                    "compared_proposal_ids": ["PROP-A", "PROP-B"],
                    "decision": "merge",
                    "parent_proposal_id": None,
                    "child_proposal_id": None,
                    "rationale": "An impermissible final decision attempt.",
                    "unresolved_disagreements": [],
                }
            ]
        }
    )

    taxonomy = canonicalize_proposals(
        [_lane("lane-a", first), _lane("lane-b", second)], adjudicator
    )

    assert taxonomy.decisions[0].decision == "unresolved"
    assert taxonomy.decisions[0].compared_proposal_ids == ("PROP-A", "PROP-B")


def test_adjudicator_fixed_tuple_schema_includes_gateway_array_items():
    first = _proposal("PROP-A", alias="a", activation_mode="activation a")
    second = _proposal("PROP-B", alias="b", activation_mode="activation b")
    adjudicator = _FakeAdjudicator(
        {"comparisons": [_comparison(("PROP-A", "PROP-B"), "unresolved")]}
    )

    canonicalize_proposals(
        [_lane("lane-a", first), _lane("lane-b", second)], adjudicator
    )

    schema = adjudicator.calls[0][2]
    comparison = schema["$defs"]["AdjudicationComparison"]
    compared_ids = comparison["properties"]["compared_proposal_ids"]
    assert compared_ids["items"] == {"type": "string"}
    assert compared_ids["minItems"] == 2
    assert compared_ids["maxItems"] == 2


def test_nonexact_adjudicated_merge_retains_both_mechanism_candidates():
    first = _proposal("PROP-A", alias="a", activation_mode="activation a")
    second = _proposal("PROP-B", alias="b", activation_mode="activation b")
    adjudicator = _FakeAdjudicator(
        {"comparisons": [_comparison(("PROP-A", "PROP-B"), "merge")]}
    )

    taxonomy = canonicalize_proposals(
        [_lane("lane-a", first), _lane("lane-b", second)], adjudicator
    )

    assert len(taxonomy.families) == 1
    assert taxonomy.families[0].proposal_ids == ("PROP-A", "PROP-B")
    assert len(taxonomy.families[0].mechanistic_definition_candidates) == 2
    assert taxonomy.decisions[0].evidence_ids == ("EV-1",)


@pytest.mark.parametrize("outcome", ("split", "distinct"))
def test_qualified_comparison_states_map_deterministically(outcome: str):
    first = _proposal("PROP-A", alias="a", activation_mode="activation a")
    second = _proposal("PROP-B", alias="b", activation_mode="activation b")
    adjudicator = _FakeAdjudicator(
        {"comparisons": [_comparison(("PROP-A", "PROP-B"), outcome)]}
    )

    taxonomy = canonicalize_proposals(
        [_lane("lane-a", first), _lane("lane-b", second)], adjudicator
    )

    assert taxonomy.decisions[0].decision == outcome
    assert taxonomy.decisions[0].source == "deterministic"


def test_adjudicator_disagreement_is_preserved_on_every_affected_family():
    first = _proposal("PROP-A", alias="a", activation_mode="activation a")
    second = _proposal("PROP-B", alias="b", activation_mode="activation b")
    adjudicator = _FakeAdjudicator(
        {"comparisons": [_comparison(("PROP-A", "PROP-B"), "unresolved")]}
    )

    taxonomy = canonicalize_proposals(
        [_lane("lane-a", first), _lane("lane-b", second)], adjudicator
    )

    assert taxonomy.unresolved_proposal_ids == ("PROP-A", "PROP-B")
    assert all(
        "The comparison remains unresolved."
        in family.unresolved_disagreements
        for family in taxonomy.families
    )


def test_unqualified_comparison_evidence_remains_unresolved():
    first = _proposal("PROP-A", alias="a", activation_mode="activation a")
    second = _proposal("PROP-B", alias="b", activation_mode="activation b")
    adjudicator = _FakeAdjudicator(
        {
            "comparisons": [
                _comparison(
                    ("PROP-A", "PROP-B"),
                    "merge",
                    evidence_ids=("UNQUALIFIED-EVIDENCE",),
                )
            ]
        }
    )

    taxonomy = canonicalize_proposals(
        [_lane("lane-a", first), _lane("lane-b", second)], adjudicator
    )

    assert len(taxonomy.families) == 2
    assert taxonomy.decisions[0].decision == "unresolved"
    assert taxonomy.unresolved_proposal_ids == ("PROP-A", "PROP-B")


def test_comparison_input_aggregates_every_exact_group_proposal():
    first = _proposal("PROP-A", alias="a", evidence_ids=("EV-A",))
    second = _proposal(
        "PROP-B",
        alias="b",
        evidence_ids=("EV-B",),
        counterarguments=("Counterargument from B",),
        unknowns=("Unknown from B",),
    )
    third = _proposal(
        "PROP-C",
        alias="c",
        activation_mode="different activation",
        evidence_ids=("EV-C",),
    )
    adjudicator = _FakeAdjudicator(
        {"comparisons": [_comparison(("PROP-A", "PROP-C"), "unresolved")]}
    )

    canonicalize_proposals(
        [_lane("lane-a", first, second), _lane("lane-c", third)], adjudicator
    )
    comparison = _comparison_input(adjudicator.calls[0][1])["comparisons"][0]
    left = comparison["left_group"]

    assert left["proposal_ids"] == ["PROP-A", "PROP-B"]
    assert left["evidence_ids"] == ["EV-A", "EV-B"]
    assert left["evidence_levels"] == ["traceable_external_evidence"]
    assert left["disagreements"] == ["Counterargument from B", "Unknown from B"]
    assert [item["proposal_id"] for item in left["proposal_evidence"]] == [
        "PROP-A",
        "PROP-B",
    ]


def test_prompt_and_schema_request_states_not_final_decisions():
    first = _proposal("PROP-A", alias="a", activation_mode="activation a")
    second = _proposal("PROP-B", alias="b", activation_mode="activation b")
    adjudicator = _FakeAdjudicator(
        {"comparisons": [_comparison(("PROP-A", "PROP-B"), "unresolved")]}
    )

    canonicalize_proposals(
        [_lane("lane-a", first), _lane("lane-b", second)], adjudicator
    )
    prompt, schema = adjudicator.calls[0][1], adjudicator.calls[0][2]
    schema_text = json.dumps(schema, sort_keys=True).lower()

    assert "return only comparison states" in prompt.lower()
    assert all(
        forbidden not in schema_text
        for forbidden in ("decision", "score", "rank", "classification", "freeze")
    )


def test_missing_batch_comparison_falls_back_to_explicit_unresolved_pair():
    proposals = tuple(
        _proposal(
            f"PROP-{suffix}",
            alias=suffix,
            activation_mode=f"activation-{suffix}",
        )
        for suffix in ("A", "B", "C")
    )
    adjudicator = _FakeAdjudicator(
        {"comparisons": [_comparison(("PROP-A", "PROP-B"), "unresolved")]}
    )

    taxonomy = canonicalize_proposals(
        [_lane("lane-batch", *proposals)], adjudicator
    )

    unresolved_pairs = {
        decision.compared_proposal_ids
        for decision in taxonomy.decisions
        if decision.decision == "unresolved"
    }
    assert unresolved_pairs == {
        ("PROP-A", "PROP-B"),
        ("PROP-A", "PROP-C"),
        ("PROP-B", "PROP-C"),
    }


class _BatchAdjudicator:
    def __init__(self):
        self.calls: list[tuple[str, str, dict, str]] = []

    def create_structured(
        self, model: str, input_text: str, schema: dict, schema_name: str
    ):
        self.calls.append((model, input_text, schema, schema_name))
        pairs = [
            tuple(item["compared_proposal_ids"])
            for item in _comparison_input(input_text)["comparisons"]
        ]
        output = {
            "comparisons": [_comparison(pair, "unresolved") for pair in pairs]
        }
        return type("Result", (), {"parsed_output": output})()


def test_candidate_adjudication_is_narrowed_batched_and_bounded():
    proposals = tuple(
        _proposal(
            f"PROP-{index:03d}",
            alias=f"alias-{index:03d}",
            activation_mode=f"activation-{index:03d}",
        )
        for index in range(50)
    )
    adjudicator = _BatchAdjudicator()

    taxonomy = canonicalize_proposals([_lane("lane-scale", *proposals)], adjudicator)

    comparison_count = sum(
        len(_comparison_input(call[1])["comparisons"])
        for call in adjudicator.calls
    )
    assert len(adjudicator.calls) <= MAX_ADJUDICATION_CALLS
    assert all(
        len(_comparison_input(call[1])["comparisons"])
        <= MAX_ADJUDICATION_BATCH_SIZE
        for call in adjudicator.calls
    )
    assert MAX_ADJUDICATION_BATCH_SIZE == 4
    assert comparison_count <= MAX_ADJUDICATION_BATCH_SIZE * MAX_ADJUDICATION_CALLS
    assert comparison_count < len(proposals) * (len(proposals) - 1) // 2
    assert len(taxonomy.families) == len(proposals)
    assert taxonomy.unresolved_proposal_ids == tuple(
        proposal.proposal_id for proposal in proposals
    )


def test_adjudication_budget_prioritizes_same_coordinate_cross_lane_pair():
    assignment = MechanismCoordinateAssignment(
        nucleophilic_center="center-a",
        reactive_state="state-a",
        bond_forming_mode="mode-a",
        activation_mode="activation-a",
        attack_topology="topology-a",
        target_termination="termination-a",
    )
    decoys = tuple(
        _proposal(
            f"PROP-{index:03d}",
            alias=f"decoy-{index:03d}",
            activation_mode=f"activation-{index:03d}",
        )
        for index in range(40)
    )
    left = _proposal(
        "ZZ-TARGET-LEFT",
        alias="target-left",
        activation_mode="target activation left",
        coordinate_assignment=assignment,
    )
    right = _proposal(
        "ZZ-TARGET-RIGHT",
        alias="target-right",
        activation_mode="target activation right",
        coordinate_assignment=assignment,
    )
    adjudicator = _BatchAdjudicator()

    canonicalize_proposals(
        [_lane("lane-a", *decoys, left), _lane("lane-b", right)], adjudicator
    )
    submitted_pairs = {
        tuple(item["compared_proposal_ids"])
        for call in adjudicator.calls
        for item in _comparison_input(call[1])["comparisons"]
    }

    assert ("ZZ-TARGET-LEFT", "ZZ-TARGET-RIGHT") in submitted_pairs


@pytest.mark.parametrize(
    ("outcome", "expected_family_count"),
    (("merge", 1), ("parent_left", 2)),
)
def test_cross_center_wording_can_be_adjudicated(
    outcome: str, expected_family_count: int
):
    first = _proposal(
        "PROP-A",
        alias="broad center",
        nucleophilic_center="heteroatom donor center",
        activation_mode="activation a",
    )
    second = _proposal(
        "PROP-B",
        alias="narrow center",
        nucleophilic_center="localized heteroatom site",
        activation_mode="activation b",
    )
    adjudicator = _FakeAdjudicator(
        {"comparisons": [_comparison(("PROP-A", "PROP-B"), outcome)]}
    )

    taxonomy = canonicalize_proposals(
        [_lane("lane-a", first), _lane("lane-b", second)], adjudicator
    )

    assert len(adjudicator.calls) == 1
    assert len(taxonomy.families) == expected_family_count
    assert taxonomy.decisions[0].decision == (
        "merge" if outcome == "merge" else "parent_child"
    )


def test_paraphrased_protected_fields_across_lanes_reach_adjudication():
    first = _proposal(
        "PROP-A",
        alias="neutral donor wording a",
        reactive_state="accessible neutral donor state",
        bond_forming_mode="direct addition to the electrophile",
        activation_mode="mild base reveals the donor",
    )
    second = _proposal(
        "PROP-B",
        alias="neutral donor wording b",
        reactive_state="neutral donor configuration is accessible",
        bond_forming_mode="the donor adds directly at the electrophilic center",
        activation_mode="donor generation by mild base",
    )
    adjudicator = _FakeAdjudicator(
        {"comparisons": [_comparison(("PROP-A", "PROP-B"), "merge")]}
    )

    taxonomy = canonicalize_proposals(
        [_lane("lane-a", first), _lane("lane-b", second)], adjudicator
    )

    assert len(adjudicator.calls) == 1
    assert len(taxonomy.families) == 1
    assert taxonomy.families[0].proposal_ids == ("PROP-A", "PROP-B")


def test_every_nonadjacent_pair_in_admissible_block_is_preserved():
    proposals = tuple(
        _proposal(
            f"PROP-{suffix}",
            alias=suffix,
            activation_mode=f"activation-{suffix}",
        )
        for suffix in ("A", "B", "C")
    )
    adjudicator = _BatchAdjudicator()

    canonicalize_proposals([_lane("lane-all-pairs", *proposals)], adjudicator)
    submitted_pairs = {
        tuple(item["compared_proposal_ids"])
        for call in adjudicator.calls
        for item in _comparison_input(call[1])["comparisons"]
    }

    assert submitted_pairs == {
        ("PROP-A", "PROP-B"),
        ("PROP-A", "PROP-C"),
        ("PROP-B", "PROP-C"),
    }


def test_call_budget_overflow_preserves_each_explicit_unresolved_pair():
    proposals = tuple(
        _proposal(
            f"PROP-{index:02d}",
            alias=f"alias-{index:02d}",
            activation_mode=f"activation-{index:02d}",
        )
        for index in range(10)
    )
    adjudicator = _BatchAdjudicator()

    taxonomy = canonicalize_proposals(
        [_lane("lane-overflow", *proposals)], adjudicator
    )
    expected_pairs = {
        (left.proposal_id, right.proposal_id)
        for index, left in enumerate(proposals)
        for right in proposals[index + 1 :]
    }
    decision_pairs = {
        decision.compared_proposal_ids
        for decision in taxonomy.decisions
        if len(decision.compared_proposal_ids) == 2
    }

    assert len(adjudicator.calls) == MAX_ADJUDICATION_CALLS
    assert decision_pairs == expected_pairs
    assert any(
        decision.decision == "unresolved"
        and "call limit" in decision.unresolved_disagreements[0]
        for decision in taxonomy.decisions
    )


class _FailingAdjudicator:
    def create_structured(
        self, model: str, input_text: str, schema: dict, schema_name: str
    ):
        raise ApiClientError(None, "synthetic_failure", None, "safe model failure")


def test_failed_batch_preserves_each_explicit_unresolved_pair():
    proposals = tuple(
        _proposal(
            f"PROP-{suffix}",
            alias=suffix,
            activation_mode=f"activation-{suffix}",
        )
        for suffix in ("A", "B", "C")
    )

    taxonomy = canonicalize_proposals(
        [_lane("lane-failed", *proposals)], _FailingAdjudicator()
    )

    assert {
        decision.compared_proposal_ids
        for decision in taxonomy.decisions
        if decision.decision == "unresolved"
    } == {
        ("PROP-A", "PROP-B"),
        ("PROP-A", "PROP-C"),
        ("PROP-B", "PROP-C"),
    }
    assert all(
        "model_invocation_failed" in decision.unresolved_disagreements[0]
        for decision in taxonomy.decisions
        if decision.decision == "unresolved"
    )


def test_missing_adjudication_prompt_propagates_configuration_error(
    tmp_path, monkeypatch
):
    first = _proposal("PROP-A", alias="a", activation_mode="activation-a")
    second = _proposal("PROP-B", alias="b", activation_mode="activation-b")
    monkeypatch.setattr(
        family_canonicalization,
        "_PROMPT_PATH",
        tmp_path / "missing-family-adjudication-prompt.md",
    )

    with pytest.raises(CanonicalizationError, match="prompt is unavailable"):
        canonicalize_proposals(
            [_lane("lane-a", first), _lane("lane-b", second)],
            _BatchAdjudicator(),
        )


def test_unexpected_local_adjudication_exception_is_not_swallowed(monkeypatch):
    first = _proposal("PROP-A", alias="a", activation_mode="activation-a")
    second = _proposal("PROP-B", alias="b", activation_mode="activation-b")

    def fail_locally(*args, **kwargs):
        raise RuntimeError("unexpected local programming failure")

    monkeypatch.setattr(family_canonicalization, "_adjudication_input", fail_locally)

    with pytest.raises(RuntimeError, match="unexpected local programming failure"):
        canonicalize_proposals(
            [_lane("lane-a", first), _lane("lane-b", second)],
            _BatchAdjudicator(),
        )


def test_canonical_taxonomy_validates_both_relation_directions():
    parent = _proposal("PROP-P", alias="broad", activation_mode="general activation")
    child = _proposal("PROP-C", alias="narrow", activation_mode="specific activation")
    adjudicator = _FakeAdjudicator(
        {"comparisons": [_comparison(("PROP-C", "PROP-P"), "parent_right")]}
    )
    taxonomy = canonicalize_proposals(
        [_lane("lane-p", parent), _lane("lane-c", child)], adjudicator
    )
    payload = taxonomy.model_dump(mode="python")
    for family in payload["families"]:
        if family["aliases"] == ("narrow",):
            family["parent_family_ids"] = ()

    with pytest.raises(ValidationError, match="bidirectional"):
        CanonicalTaxonomy.model_validate(payload)


def test_output_contains_no_score_or_rank_fields():
    taxonomy = canonicalize_proposals(
        [_lane("lane-a", _proposal("PROP-A", alias="a"))], None
    )

    dumped = taxonomy.model_dump(mode="json")
    assert "score" not in str(dumped).lower()
    assert "rank" not in str(dumped).lower()

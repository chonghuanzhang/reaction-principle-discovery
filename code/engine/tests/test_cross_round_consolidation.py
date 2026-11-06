from __future__ import annotations

import pytest

from pipeline.cross_round_consolidation import (
    ConsolidationError,
    ConsolidationPolicy,
    compare_fingerprints,
    consolidate_fingerprints,
    fingerprint_proposal,
)
from pipeline.taxonomy_discovery import (
    MechanismCoordinateAssignment,
    MechanisticProposalDefinition,
    TaxonomyProposal,
)


COORDINATE = MechanismCoordinateAssignment(
    nucleophilic_center="carbon_center",
    reactive_state="anionic_state",
    bond_forming_mode="polar_addition_elimination",
    activation_mode="base_activation",
    attack_topology="fluorinated_alkene_carbon",
    target_termination="protonation_then_selective_fluoride_elimination",
)


def _policy() -> ConsolidationPolicy:
    return ConsolidationPolicy(
        version="3.4",
        source_version="3.3",
        maximum_new_family_rate=0.05,
        required_consecutive_low_novelty_transitions=2,
        minimum_independent_lanes=2,
        minimum_core_token_jaccard=0.35,
        minimum_context_token_jaccard=0.20,
        qualifying_evidence_prefixes=("TA-",),
        model_only_merge_policy="exact_fingerprint_only",
        cross_coordinate_policy="prohibited",
        unresolved_policy="preserve",
    )


def _proposal(
    proposal_id: str,
    *,
    coordinate: MechanismCoordinateAssignment = COORDINATE,
    parent: str = "Base-generated carbon donor capture",
    reactive_state: str = "a resonance-stabilized carbon anion",
    bond_mode: str = "polar addition followed by fluoride elimination",
    activation: str = "base-assisted donor generation",
    conditions: tuple[str, ...] = ("moderate base and controlled water activity",),
    failures: tuple[str, ...] = ("competitive carbonyl addition",),
    evidence_level: str = "traceable_external_evidence",
    evidence_ids: tuple[str, ...] = ("TA-1",),
) -> TaxonomyProposal:
    return TaxonomyProposal(
        proposal_id=proposal_id,
        mechanistic_definition=MechanisticProposalDefinition(
            nucleophilic_center="carbon donor center",
            reactive_state=reactive_state,
            bond_forming_mode=bond_mode,
            activation_mode=activation,
            critical_conditions=conditions,
            dominant_failure_modes=failures,
        ),
        coordinate_assignment=coordinate,
        coordinate_assignment_key="synthetic-key",
        source_channel="literature_derived",
        evidence_level=evidence_level,
        evidence_ids=evidence_ids,
        parent_hypothesis=parent,
        representative_reactive_state=reactive_state,
        counterarguments=(),
        unknowns=(),
        suggested_search_terms=("synthetic query",),
    )


def _fingerprint(
    proposal: TaxonomyProposal,
    *,
    lane_id: str = "LANE-A",
    round_id: int = 1,
):
    return fingerprint_proposal(
        proposal,
        lane_id=lane_id,
        round_id=round_id,
        channel=proposal.source_channel,
    )


def test_exact_normalized_fingerprints_merge_without_external_evidence() -> None:
    left = _fingerprint(
        _proposal("P1", parent="Carbon donor capture", evidence_ids=())
    )
    right = _fingerprint(
        _proposal("P2", parent="  carbon   donor capture ", evidence_ids=())
    )

    decision = compare_fingerprints(left, right, _policy())

    assert decision is not None
    assert decision.decision == "merge"
    assert decision.rule_id == "exact_fingerprint"


def test_different_complete_coordinates_are_not_compared_for_merge() -> None:
    other = COORDINATE.model_copy(update={"nucleophilic_center": "nitrogen_center"})
    left = _fingerprint(_proposal("P1"))
    right = _fingerprint(_proposal("P2", coordinate=other))

    assert compare_fingerprints(left, right, _policy()) is None


def test_approximate_merge_requires_shared_qualifying_external_evidence() -> None:
    left = _fingerprint(_proposal("P1", evidence_ids=("TA-1",)))
    right = _fingerprint(
        _proposal(
            "P2",
            parent="capture by a carbon nucleophile formed with base",
            reactive_state="resonance stabilized anionic carbon donor",
            bond_mode="polar carbon attack then selective fluoride loss",
            activation="base assisted formation of the donor",
            evidence_ids=("TA-1", "TA-2"),
        ),
        round_id=2,
    )

    decision = compare_fingerprints(left, right, _policy())

    assert decision is not None
    assert decision.decision == "merge"
    assert decision.rule_id == "evidence_supported_paraphrase"
    assert decision.shared_qualifying_evidence_ids == ("TA-1",)


def test_shared_seed_anchor_alone_remains_unresolved() -> None:
    left = _fingerprint(_proposal("P1", evidence_ids=("RPV3-SEED-001",)))
    right = _fingerprint(
        _proposal(
            "P2",
            parent="capture by a carbon nucleophile formed with base",
            reactive_state="resonance stabilized anionic carbon donor",
            bond_mode="polar carbon attack then selective fluoride loss",
            activation="base assisted formation of the donor",
            evidence_ids=("RPV3-SEED-001",),
        ),
        round_id=2,
    )

    decision = compare_fingerprints(left, right, _policy())

    assert decision is not None
    assert decision.decision == "unresolved"
    assert decision.shared_qualifying_evidence_ids == ()


def test_model_only_approximate_match_remains_unresolved() -> None:
    left = _fingerprint(
        _proposal(
            "P1",
            evidence_level="model_physical_organic_inference",
            evidence_ids=(),
        )
    )
    right = _fingerprint(
        _proposal(
            "P2",
            parent="capture by a carbon nucleophile formed with base",
            reactive_state="resonance stabilized anionic carbon donor",
            bond_mode="polar carbon attack then selective fluoride loss",
            activation="base assisted formation of the donor",
            evidence_level="model_physical_organic_inference",
            evidence_ids=(),
        ),
        round_id=2,
    )

    decision = compare_fingerprints(left, right, _policy())

    assert decision is not None
    assert decision.decision == "unresolved"


def test_later_exact_paraphrase_preserves_stable_family_id_and_novelty() -> None:
    first = _fingerprint(_proposal("P1", evidence_ids=()), round_id=1)
    later = _fingerprint(
        _proposal(
            "P2",
            parent="  base-generated  carbon donor capture ",
            evidence_ids=(),
        ),
        lane_id="LANE-B",
        round_id=2,
    )

    first_result = consolidate_fingerprints(
        (first,), _policy(), source_digest="a" * 64, policy_digest="b" * 64
    )
    later_result = consolidate_fingerprints(
        (first, later), _policy(), source_digest="a" * 64, policy_digest="b" * 64
    )

    assert first_result.families[0].family_id == later_result.families[0].family_id
    assert later_result.prefix_metrics[-1].new_family_rate == 0
    assert later_result.families[0].lane_ids == ("LANE-A", "LANE-B")


def test_every_proposal_is_preserved_exactly_once() -> None:
    fingerprints = tuple(
        _fingerprint(_proposal(f"P{index}"), round_id=index)
        for index in range(1, 4)
    )

    result = consolidate_fingerprints(
        fingerprints, _policy(), source_digest="a" * 64, policy_digest="b" * 64
    )
    members = [
        proposal_id
        for family in result.families
        for proposal_id in family.member_proposal_ids
    ]

    assert sorted(members) == sorted(set(members)) == ["P1", "P2", "P3"]


def test_qualified_inherited_merge_component_is_preserved_atomically() -> None:
    fingerprints = tuple(
        _fingerprint(_proposal(f"P{index}"), round_id=1).model_copy(
            update={
                "exact_fingerprint": f"{index:064x}",
                "core_tokens": frozenset({f"core:{index}"}),
                "context_tokens": frozenset({f"context:{index}"}),
            }
        )
        for index in range(1, 4)
    )

    result = consolidate_fingerprints(
        fingerprints,
        _policy(),
        source_digest="a" * 64,
        policy_digest="b" * 64,
        inherited_merge_pairs={
            ("P1", "P2"): ("TA-1",),
            ("P2", "P3"): ("TA-1",),
        },
    )

    assert len(result.families) == 1
    assert result.families[0].member_proposal_ids == ("P1", "P2", "P3")
    inherited = [
        row for row in result.decisions if row.rule_id == "inherited_v3_3_qualified_merge"
    ]
    assert len(inherited) == 2


def test_cross_coordinate_inherited_merge_fails_closed() -> None:
    other = COORDINATE.model_copy(update={"nucleophilic_center": "nitrogen_center"})
    fingerprints = (
        _fingerprint(_proposal("P1")),
        _fingerprint(_proposal("P2", coordinate=other)),
    )

    with pytest.raises(ConsolidationError, match="cross-coordinate"):
        consolidate_fingerprints(
            fingerprints,
            _policy(),
            source_digest="a" * 64,
            policy_digest="b" * 64,
            inherited_merge_pairs={("P1", "P2"): ("TA-1",)},
        )

from __future__ import annotations

import pytest

from pipeline.family_canonicalization import CanonicalTaxonomy, canonicalize_proposals
import pipeline.saturation as saturation
from pipeline.saturation import (
    SaturationConfigurationError,
    _new_family_rate,
    audit_mechanism_coverage,
    expand_coordinate_assignments,
    evaluate_saturation,
)
from pipeline.taxonomy_discovery import (
    MechanismCoordinateAssignment,
    MechanisticProposalDefinition,
    TaxonomyLaneResult,
    TaxonomyProposal,
)


def _coordinate_config() -> dict[str, object]:
    return {
        "coordinate_vocabulary": {
            "nucleophilic_center": ["center-alpha"],
            "reactive_state": ["state-alpha"],
            "bond_forming_mode": ["mode-alpha"],
            "activation_mode": ["activation-alpha"],
            "attack_topology": ["topology-alpha"],
            "target_termination": ["termination-alpha"],
        },
        "relevant_coordinate_cells": [
            {
                "coordinate_id": "cell-alpha",
                "nucleophilic_center": "center-alpha",
                "reactive_state": "state-alpha",
                "bond_forming_mode": "mode-alpha",
                "activation_mode": "activation-alpha",
                "attack_topology": "topology-alpha",
                "target_termination": "termination-alpha",
                "disposition": "covered",
                "rationale": "Synthetic coordinate cell is represented.",
            }
        ],
        "saturation": {
            "maximum_new_family_rate": 0.05,
            "maximum_material_taxonomy_change_rate": 0.0,
            "required_consecutive_low_novelty_rounds": 2,
            "minimum_independent_lanes": 2,
        },
    }


def _cell(center: str, disposition: str = "covered") -> saturation.MechanismCoverageCell:
    return saturation.MechanismCoverageCell(
        coordinate_id=f"{center}-{disposition}",
        nucleophilic_center=center,
        reactive_state="state-alpha",
        bond_forming_mode="mode-alpha",
        activation_mode="activation-alpha",
        attack_topology="topology-alpha",
        target_termination="termination-alpha",
        disposition=disposition,
        rationale="fixture",
    )


def _proposal(
    index: int,
    *,
    activation_mode: str = "activation-alpha",
    coordinate_assignment: MechanismCoordinateAssignment | None = None,
) -> TaxonomyProposal:
    return TaxonomyProposal(
        proposal_id=f"proposal-{index}",
        mechanistic_definition=MechanisticProposalDefinition(
            nucleophilic_center="center-alpha",
            reactive_state="state-alpha",
            bond_forming_mode="mode-alpha",
            activation_mode=activation_mode,
            critical_conditions=(f"condition-{index}",),
            dominant_failure_modes=("failure-alpha",),
        ),
        coordinate_assignment=coordinate_assignment,
        source_channel="seed_derived",
        evidence_level="traceable_external_evidence",
        evidence_ids=(f"evidence-{index}",),
        parent_hypothesis=f"synthetic-family-{index}",
        representative_reactive_state="state-alpha",
        counterarguments=(),
        unknowns=(),
        suggested_search_terms=("synthetic query",),
    )


def _lane(lane_id: str, round_id: int, proposals: tuple[TaxonomyProposal, ...]) -> TaxonomyLaneResult:
    return TaxonomyLaneResult(
        status="validated",
        cache_key=(lane_id.encode().hex() + "0" * 64)[:64],
        lane_id=lane_id,
        round_id=round_id,
        channel="seed_derived",
        proposals=proposals,
        usage={"input_tokens": None, "output_tokens": None, "total_tokens": None},
    )


def _taxonomy(round_id: int = 1, count: int = 1, *, activation_mode: str = "activation-alpha"):
    proposals = tuple(_proposal(index, activation_mode=activation_mode) for index in range(count))
    convergent_proposals = tuple(
        proposal.model_copy(update={"proposal_id": f"independent-{proposal.proposal_id}"})
        for proposal in proposals
    )
    return canonicalize_proposals(
        (
            _lane("lane-alpha", round_id, proposals),
            _lane("lane-beta", round_id, convergent_proposals),
        ),
        None,
    )


def _three_round_fixture(counts: tuple[int, int, int] = (30, 30, 30)):
    return tuple(_taxonomy(round_id, count) for round_id, count in enumerate(counts, 1))


def _coverage():
    return audit_mechanism_coverage(_taxonomy(), _coordinate_config())


def _config():
    return _coordinate_config()


def test_new_family_rate_uses_mechanistic_signature_not_textual_family_id():
    previous = _taxonomy(1, 1)
    payload = previous.model_dump(mode="python")
    family = payload["families"][0]
    family["family_id"] = "NFV3-paraphrased"
    family["nucleophilic_center"] = "the same alpha carbon donor center"
    family["reactive_state"] = "an accessible alpha carbon reactive state"
    family["bond_forming_mode"] = "mode-alpha direct bond formation at the electrophilic site"
    family["activation_mode"] = "activation-alpha of the donor"
    current = CanonicalTaxonomy.model_validate(payload)

    assert _new_family_rate(previous, current) == 0


def _rounds_with_new_coordinate():
    return (_taxonomy(1, 30), _taxonomy(2, 31), _taxonomy(3, 32, activation_mode="activation-beta"))


def test_coverage_audit_requires_disposition_not_named_family():
    audit = audit_mechanism_coverage(_taxonomy(), _coordinate_config())

    assert audit.required_family_ids == ()
    assert all(
        cell.disposition
        in {"covered", "chemically_inapplicable", "unsupported", "unknown"}
        for cell in audit.cells
    )


def test_required_centers_are_audited_without_named_families():
    audit = saturation.MechanismCoverageAudit(
        cells=(_cell("carbon_center"), _cell("nitrogen_center")),
        rationale="fixture",
    )
    result = saturation.audit_nucleophilic_centers(
        audit,
        (
            "carbon_center",
            "nitrogen_center",
            "oxygen_center",
            "sulfur_center",
            "phosphorus_center",
        ),
    )

    assert result.complete is False
    assert result.missing_centers == (
        "oxygen_center",
        "phosphorus_center",
        "sulfur_center",
    )
    assert result.required_family_ids == ()


def test_out_of_experimental_scope_is_not_failure():
    assert _cell(
        "other_main_group_center", "out_of_experimental_scope"
    ).disposition == "out_of_experimental_scope"


def test_coordinate_templates_expand_symmetrically_across_all_center_types():
    config = _coordinate_config()
    config["coordinate_vocabulary"]["nucleophilic_center"] = [
        "center-alpha",
        "center-beta",
    ]
    config.pop("relevant_coordinate_cells")
    config["coordinate_cell_templates"] = [
        {
            "template_id": "generic-polar-capture",
            "nucleophilic_center": "*",
            "reactive_state": "state-alpha",
            "bond_forming_mode": "mode-alpha",
            "activation_mode": "activation-alpha",
            "attack_topology": "topology-alpha",
            "target_termination": "termination-alpha",
            "disposition": "unknown",
            "rationale": "Symmetric answer-independent template.",
        }
    ]

    audit = audit_mechanism_coverage(_taxonomy(), config)

    assert len(audit.cells) == 2
    assert {cell.nucleophilic_center for cell in audit.cells} == {
        "center-alpha",
        "center-beta",
    }


def test_coordinate_template_expansion_returns_complete_allowed_assignments():
    config = _coordinate_config()
    config["coordinate_vocabulary"]["nucleophilic_center"] = [
        "center-alpha",
        "center-beta",
    ]
    config.pop("relevant_coordinate_cells")
    config["coordinate_cell_templates"] = [
        {
            "template_id": "generic-polar-capture",
            "nucleophilic_center": "*",
            "reactive_state": "state-alpha",
            "bond_forming_mode": "mode-alpha",
            "activation_mode": "activation-alpha",
            "attack_topology": "topology-alpha",
            "target_termination": "termination-alpha",
            "disposition": "unknown",
            "rationale": "Symmetric answer-independent template.",
        }
    ]

    assignments = expand_coordinate_assignments(config)

    assert len(assignments) == 2
    assert {item.nucleophilic_center for item in assignments} == {
        "center-alpha",
        "center-beta",
    }
    assert all(item.activation_mode == "activation-alpha" for item in assignments)


def test_coverage_uses_structured_coordinates_instead_of_free_text_equality():
    assignment = MechanismCoordinateAssignment(
        nucleophilic_center="center-alpha",
        reactive_state="state-alpha",
        bond_forming_mode="mode-alpha",
        activation_mode="activation-alpha",
        attack_topology="topology-alpha",
        target_termination="termination-alpha",
    )
    proposal = _proposal(1, coordinate_assignment=assignment)
    definition = proposal.mechanistic_definition.model_copy(
        update={
            "nucleophilic_center": "a polarizable donor atom bearing available electron density",
            "reactive_state": "the reactive species generated under the stated medium",
            "bond_forming_mode": "capture followed by selective fluoride loss",
            "activation_mode": "base-assisted generation of the donor state",
        }
    )
    proposal = proposal.model_copy(update={"mechanistic_definition": definition})
    taxonomy = canonicalize_proposals(
        (
            _lane("lane-alpha", 1, (proposal,)),
            _lane(
                "lane-beta",
                1,
                (proposal.model_copy(update={"proposal_id": "independent-proposal-1"}),),
            ),
        ),
        None,
    )

    audit = audit_mechanism_coverage(taxonomy, _coordinate_config())

    assert audit.cells[0].disposition == "covered"
    assert audit.unrecognized_observed_coordinates == ()


def test_saturation_requires_two_consecutive_low_novelty_rounds():
    audit = evaluate_saturation(_three_round_fixture(), _coverage(), _config())

    assert audit.saturated is True


def test_saturation_fails_after_only_one_low_novelty_round():
    audit = evaluate_saturation(
        (
            _taxonomy(1, 30),
            _taxonomy(2, 32, activation_mode="activation-beta"),
            _taxonomy(3, 32, activation_mode="activation-beta"),
        ),
        _coverage(),
        _config(),
    )

    assert audit.consecutive_low_new_family_rounds == 1
    assert audit.saturated is False


def test_saturation_fails_when_new_mechanism_combination_appears():
    audit = evaluate_saturation(
        _rounds_with_new_coordinate(), _coverage(), _config()
    )

    assert audit.saturated is False


def test_saturation_fails_when_a_relevant_cell_remains_unknown():
    config = _config()
    config["relevant_coordinate_cells"][0]["disposition"] = "unknown"  # type: ignore[index]
    coverage = audit_mechanism_coverage(_taxonomy(), config)

    audit = evaluate_saturation(_three_round_fixture(), coverage, config)

    assert audit.coverage_dispositioned is False
    assert audit.saturated is False


def test_saturation_requires_independent_lane_convergence():
    config = _config()
    config["saturation"]["minimum_independent_lanes"] = 3  # type: ignore[index]

    audit = evaluate_saturation(
        _three_round_fixture(), _coverage(), config
    )

    assert audit.lane_converged is False
    assert audit.saturated is False


def test_single_lane_family_with_explicit_retained_disposition_does_not_block():
    taxonomy = _taxonomy()
    payload = taxonomy.model_dump(mode="python")
    payload["families"][0]["proposal_ids"] = payload["families"][0]["proposal_ids"][:1]
    payload["families"][0]["proposal_provenance"] = payload["families"][0][
        "proposal_provenance"
    ][:1]
    payload["families"][0]["mechanistic_definition_candidates"] = payload["families"][0][
        "mechanistic_definition_candidates"
    ][:1]
    payload["families"][0]["aliases"] = payload["families"][0]["aliases"][:1]
    payload["families"][0]["representative_reactive_state_candidates"] = payload[
        "families"
    ][0]["representative_reactive_state_candidates"][:1]
    payload["decisions"] = ()
    payload["unresolved_proposal_ids"] = ()
    single_lane = CanonicalTaxonomy.model_validate(payload)
    config = _config()
    config["family_convergence_dispositions"] = [
        {
            "family_id": single_lane.families[0].family_id,
            "disposition": "retained_for_validation",
            "rationale": "Mechanistically plausible singleton retained in the prospective panel.",
            "evidence_ids": ["evidence-0"],
        }
    ]
    coverage = audit_mechanism_coverage(single_lane, config)

    audit = evaluate_saturation((single_lane, single_lane, single_lane), coverage, config)

    assert audit.lane_converged is True
    assert audit.saturated is True


def test_single_lane_family_without_explicit_disposition_still_blocks():
    taxonomy = _taxonomy()
    payload = taxonomy.model_dump(mode="python")
    payload["families"][0]["proposal_ids"] = payload["families"][0]["proposal_ids"][:1]
    payload["families"][0]["proposal_provenance"] = payload["families"][0][
        "proposal_provenance"
    ][:1]
    payload["families"][0]["mechanistic_definition_candidates"] = payload["families"][0][
        "mechanistic_definition_candidates"
    ][:1]
    payload["families"][0]["aliases"] = payload["families"][0]["aliases"][:1]
    payload["families"][0]["representative_reactive_state_candidates"] = payload[
        "families"
    ][0]["representative_reactive_state_candidates"][:1]
    payload["decisions"] = ()
    payload["unresolved_proposal_ids"] = ()
    single_lane = CanonicalTaxonomy.model_validate(payload)
    coverage = audit_mechanism_coverage(single_lane, _config())

    audit = evaluate_saturation(
        (single_lane, single_lane, single_lane), coverage, _config()
    )

    assert audit.lane_converged is False
    assert audit.saturated is False


def test_saturation_fails_when_additional_evidence_batch_changes_taxonomy_materially():
    rounds = (_taxonomy(1, 10), _taxonomy(2, 10), _taxonomy(3, 11))

    audit = evaluate_saturation(rounds, _coverage(), _config())

    assert audit.coordinate_combinations_stable is True
    assert audit.additional_evidence_batch_no_material_change is False
    assert audit.saturated is False


@pytest.mark.parametrize(
    "change", ("definition", "relations", "unresolved", "decision", "decision_unresolved")
)
def test_saturation_fails_when_low_novelty_taxonomy_content_changes(change: str):
    stable = _taxonomy(2, 2)
    payload = stable.model_dump(mode="python")
    if change == "definition":
        payload["families"][0]["critical_conditions"] = ("condition-changed",)
    elif change == "relations":
        first_id = payload["families"][0]["family_id"]
        second_id = payload["families"][1]["family_id"]
        payload["families"][0]["child_family_ids"] = (second_id,)
        payload["families"][1]["parent_family_ids"] = (first_id,)
    elif change == "decision":
        unresolved = next(
            decision for decision in payload["decisions"] if decision["decision"] == "unresolved"
        )
        unresolved["decision"] = "distinct"
    elif change == "decision_unresolved":
        unresolved = next(
            decision for decision in payload["decisions"] if decision["decision"] == "unresolved"
        )
        unresolved["unresolved_disagreements"] = (
            "Synthetic decision uncertainty changed.",
        )
    else:
        payload["families"][0]["unresolved_disagreements"] = (
            "Synthetic coordinate assignment remains unresolved.",
        )
    changed = CanonicalTaxonomy.model_validate(payload)

    audit = evaluate_saturation((_taxonomy(1, 2), stable, changed), _coverage(), _config())

    assert audit.new_family_rate == 0
    assert audit.additional_evidence_batch_no_material_change is False
    assert audit.saturated is False


def test_saturation_ignores_provenance_only_taxonomy_churn():
    stable = _taxonomy(2, 2)
    payload = stable.model_dump(mode="python")
    proposal_id_map = {
        proposal_id: f"batch-two-{proposal_id}"
        for family in payload["families"]
        for proposal_id in family["proposal_ids"]
    }
    for family in payload["families"]:
        family["proposal_ids"] = tuple(proposal_id_map[item] for item in family["proposal_ids"])
        family["aliases"] = tuple(f"renamed-{item}" for item in family["aliases"])
        family["evidence_ids"] = ("evidence-batch-two",)
        for provenance in family["proposal_provenance"]:
            provenance["proposal_id"] = proposal_id_map[provenance["proposal_id"]]
            provenance["lane_id"] = f"batch-two-{provenance['lane_id']}"
            provenance["round_id"] = 3
            provenance["evidence_ids"] = ("evidence-batch-two",)
    for decision in payload["decisions"]:
        decision["compared_proposal_ids"] = tuple(
            sorted(proposal_id_map[item] for item in decision["compared_proposal_ids"])
        )
        decision["evidence_ids"] = ("evidence-batch-two",)
        decision["rationale"] = "Evidence-only audit text changed."
    payload["unresolved_proposal_ids"] = tuple(
        proposal_id_map[item] for item in payload["unresolved_proposal_ids"]
    )
    churned = CanonicalTaxonomy.model_validate(payload)

    audit = evaluate_saturation((_taxonomy(1, 2), stable, churned), _coverage(), _config())

    assert audit.material_taxonomy_change_rate == 0
    assert audit.additional_evidence_batch_no_material_change is True
    assert audit.saturated is True


def test_saturation_accepts_stable_taxonomy_content_after_additional_batch():
    audit = evaluate_saturation(_three_round_fixture(), _coverage(), _config())

    assert audit.additional_evidence_batch_no_material_change is True
    assert audit.saturated is True


def test_empty_taxonomy_does_not_converge_lanes():
    empty = CanonicalTaxonomy(families=(), decisions=(), unresolved_proposal_ids=())
    coverage = audit_mechanism_coverage(empty, _config())

    audit = evaluate_saturation((empty, empty, empty), coverage, _config())

    assert audit.lane_converged is False
    assert audit.saturated is False


def test_coverage_rejects_whitespace_only_rationale():
    config = _config()
    config["relevant_coordinate_cells"][0]["rationale"] = "   "  # type: ignore[index]

    with pytest.raises(SaturationConfigurationError):
        audit_mechanism_coverage(_taxonomy(), config)

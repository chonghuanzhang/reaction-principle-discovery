from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml

from pipeline.taxonomy_discovery import (
    MechanismCoordinateAssignment,
    MechanisticProposalDefinition,
    TaxonomyLaneResult,
    TaxonomyProposal,
)
from scripts.run_v3_4_consolidation import (
    SourceIntegrityError,
    consolidate,
    prepare,
)


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _assignments() -> list[dict[str, str]]:
    rows = []
    for center in (
        "carbon_center",
        "nitrogen_center",
        "oxygen_center",
        "sulfur_center",
        "phosphorus_center",
        "radical_center",
        "other_main_group_center",
    ):
        for index in range(5):
            rows.append(
                MechanismCoordinateAssignment(
                    nucleophilic_center=center,
                    reactive_state=f"state-{index}",
                    bond_forming_mode=f"bond-{index}",
                    activation_mode=f"activation-{index}",
                    attack_topology=f"topology-{index}",
                    target_termination=f"termination-{index}",
                ).model_dump(mode="json")
            )
    return rows


def _proposal(round_id: int, assignment: dict[str, str]) -> TaxonomyProposal:
    coordinate = MechanismCoordinateAssignment.model_validate(assignment)
    return TaxonomyProposal(
        proposal_id=f"P-{round_id}",
        mechanistic_definition=MechanisticProposalDefinition(
            nucleophilic_center="synthetic donor",
            reactive_state=f"reactive state {round_id}",
            bond_forming_mode=f"bond formation {round_id}",
            activation_mode=f"activation pathway {round_id}",
            critical_conditions=(f"condition {round_id}",),
            dominant_failure_modes=(f"failure {round_id}",),
        ),
        coordinate_assignment=coordinate,
        coordinate_assignment_key=f"assignment-{round_id}",
        source_channel="literature_derived",
        evidence_level="traceable_external_evidence",
        evidence_ids=(f"TA-{round_id}",),
        parent_hypothesis=f"hypothesis {round_id}",
        representative_reactive_state=f"reactive state {round_id}",
        counterarguments=(),
        unknowns=(),
        suggested_search_terms=("synthetic",),
    )


def _production_fixture(tmp_path: Path) -> tuple[Path, Path]:
    source_root = tmp_path / "source" / "derived" / "principles_v3"
    rounds_root = source_root / "rounds"
    rounds_root.mkdir(parents=True)
    assignments = _assignments()
    preregistration = {
        "version": "3.3",
        "inputs": {
            "allowed_coordinate_assignment_count": 35,
            "allowed_coordinate_assignments": assignments,
            "allowed_coordinate_assignment_digest": _canonical_digest(assignments),
        },
        "answer_isolation": {
            "named_family_targets_used": False,
            "sealed_registry_read": False,
            "withheld_results_used": False,
        },
    }
    (source_root / "preregistration.json").write_text(
        json.dumps(preregistration), encoding="utf-8"
    )
    for round_id in range(1, 6):
        proposal = _proposal(round_id, assignments[round_id - 1])
        lane = TaxonomyLaneResult(
            status="validated",
            cache_key=f"{round_id:064x}",
            lane_id="LANE-A" if round_id % 2 else "LANE-B",
            round_id=round_id,
            channel="literature_derived",
            proposals=(proposal,),
            usage={"input_tokens": None, "output_tokens": None, "total_tokens": None},
        )
        (rounds_root / f"round_{round_id}.json").write_text(
            json.dumps(
                {
                    "round_id": round_id,
                    "lane_results": [lane.model_dump(mode="json")],
                    "taxonomy": {"families": []},
                    "platform_failures": [],
                }
            ),
            encoding="utf-8",
        )
    (source_root / "chemical_review.json").write_text(
        json.dumps(
            {
                "freeze_2_allowed": False,
                "freeze_2_blockers": ["all_coordinate_cells_dispositioned"],
            }
        ),
        encoding="utf-8",
    )
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "version": "3.4",
                "source_version": "3.3",
                "expected_round_count": 5,
                "expected_proposal_count": 5,
                "expected_assignment_count": 35,
                "maximum_new_family_rate": 0.05,
                "required_consecutive_low_novelty_transitions": 2,
                "minimum_independent_lanes": 2,
                "minimum_core_token_jaccard": 0.35,
                "minimum_context_token_jaccard": 0.20,
                "qualifying_evidence_prefixes": ["TA-"],
                "model_only_merge_policy": "exact_fingerprint_only",
                "cross_coordinate_policy": "prohibited",
                "unresolved_policy": "preserve",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return source_root, config_path


def test_prepare_records_source_policy_and_assignment_contract(tmp_path: Path) -> None:
    source_root, config_path = _production_fixture(tmp_path)
    run_root = tmp_path / "run"

    path = prepare(run_root, source_root, config_path)
    payload = json.loads(path.read_text())

    assert payload["version"] == "3.4"
    assert payload["source_version"] == "3.3"
    assert payload["round_count"] == 5
    assert payload["proposal_count"] == 5
    assert payload["allowed_coordinate_assignment_count"] == 35
    assert payload["answer_isolation"] == {
        "named_family_targets_used": False,
        "sealed_registry_read": False,
        "withheld_results_used": False,
    }
    assert len(payload["source_digest"]) == 64
    assert len(payload["policy_digest"]) == 64


def test_prepare_accepts_v36_discovery_source_version(tmp_path: Path) -> None:
    source_root, config_path = _production_fixture(tmp_path)
    preregistration_path = source_root / "preregistration.json"
    preregistration = json.loads(preregistration_path.read_text())
    preregistration["version"] = "3.6"
    preregistration_path.write_text(json.dumps(preregistration), encoding="utf-8")
    config = yaml.safe_load(config_path.read_text())
    config["source_version"] = "3.6"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    payload = json.loads(prepare(tmp_path / "run", source_root, config_path).read_text())

    assert payload["source_version"] == "3.6"


def test_v36_namespaces_reused_local_proposal_ids_by_round(tmp_path: Path) -> None:
    source_root, config_path = _production_fixture(tmp_path)
    preregistration_path = source_root / "preregistration.json"
    preregistration = json.loads(preregistration_path.read_text())
    preregistration["version"] = "3.6"
    preregistration_path.write_text(json.dumps(preregistration), encoding="utf-8")
    config = yaml.safe_load(config_path.read_text())
    config["source_version"] = "3.6"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    round_two_path = source_root / "rounds/round_2.json"
    round_two = json.loads(round_two_path.read_text())
    round_two["lane_results"][0]["proposals"][0]["proposal_id"] = "P-1"
    round_two_path.write_text(json.dumps(round_two), encoding="utf-8")
    run_root = tmp_path / "run"

    prepare(run_root, source_root, config_path)
    payload = json.loads(consolidate(run_root, source_root, config_path).read_text())
    members = {
        proposal_id
        for family in payload["families"]
        for proposal_id in family["member_proposal_ids"]
    }

    assert "R001:P-1" in members
    assert "R002:P-1" in members


def test_consolidate_rejects_source_change_after_prepare(tmp_path: Path) -> None:
    source_root, config_path = _production_fixture(tmp_path)
    run_root = tmp_path / "run"
    prepare(run_root, source_root, config_path)
    round_five = source_root / "rounds" / "round_5.json"
    payload = json.loads(round_five.read_text())
    payload["round_id"] = 99
    round_five.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SourceIntegrityError, match="source digest"):
        consolidate(run_root, source_root, config_path)


def test_consolidation_preserves_fixture_proposals_and_public_blocker(tmp_path: Path) -> None:
    source_root, config_path = _production_fixture(tmp_path)
    run_root = tmp_path / "run"
    prepare(run_root, source_root, config_path)

    path = consolidate(run_root, source_root, config_path)
    payload = json.loads(path.read_text())

    assert payload["proposal_count"] == 5
    assert sum(len(row["member_proposal_ids"]) for row in payload["families"]) == 5
    assert payload["freeze_2_allowed"] is False
    assert "all_coordinate_cells_dispositioned" in payload["freeze_2_blockers"]


def test_runner_inherits_qualified_same_coordinate_v3_3_merge(tmp_path: Path) -> None:
    source_root, config_path = _production_fixture(tmp_path)
    round_one_path = source_root / "rounds" / "round_1.json"
    round_one = json.loads(round_one_path.read_text())
    first = TaxonomyProposal.model_validate(
        round_one["lane_results"][0]["proposals"][0]
    )
    second = first.model_copy(
        update={
            "proposal_id": "P-1B",
            "mechanistic_definition": first.mechanistic_definition.model_copy(
                update={
                    "reactive_state": "orthogonal low-similarity donor description",
                    "bond_forming_mode": "distinct wording retained by prior adjudication",
                    "activation_mode": "different descriptive activation vocabulary",
                    "critical_conditions": ("unrelated condition wording",),
                    "dominant_failure_modes": ("unrelated failure wording",),
                }
            ),
            "parent_hypothesis": "orthogonal prior family wording",
            "representative_reactive_state": "orthogonal donor description",
        }
    )
    second_lane = TaxonomyLaneResult(
        status="validated",
        cache_key="f" * 64,
        lane_id="LANE-B",
        round_id=1,
        channel="literature_derived",
        proposals=(second,),
        usage={"input_tokens": None, "output_tokens": None, "total_tokens": None},
    )
    round_one["lane_results"].append(second_lane.model_dump(mode="json"))
    round_one["taxonomy"]["decisions"] = [
        {
            "compared_proposal_ids": ["P-1", "P-1B"],
            "decision": "merge",
            "source": "deterministic",
            "evidence_ids": ["TA-1"],
        }
    ]
    round_one_path.write_text(json.dumps(round_one), encoding="utf-8")
    config = yaml.safe_load(config_path.read_text())
    config["version"] = "3.4.1"
    config["expected_proposal_count"] = 6
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    run_root = tmp_path / "run"

    prepare(run_root, source_root, config_path)
    result = json.loads(
        consolidate(run_root, source_root, config_path).read_text()
    )

    inherited = [
        row
        for row in result["decisions"]
        if row["rule_id"] == "inherited_v3_3_qualified_merge"
    ]
    assert len(inherited) == 1
    family = next(row for row in result["families"] if "P-1" in row["member_proposal_ids"])
    assert family["member_proposal_ids"] == ["P-1", "P-1B"]

import json
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from pipeline.principle_workflow import PrincipleWorkflowGateError, run_principle_workflow
from tests.test_principle_induction import _principle, _transfer
from tests.test_v2_chemical_space import FakeClient, _payload


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _prepare_v2_rank(tmp_path: Path, *, stage: str = "fixed_electrophile_nucleophile_condition") -> Path:
    config = yaml.safe_load(Path("config/principle_workflow.yaml").read_text())
    config["exploration_brief"]["stage"] = stage
    config["chemical_space_modeling"]["model"] = "fixture"
    config["chemical_space_modeling"]["superclass_batch_size"] = 0
    config["candidate_scoring_config"] = "candidate_scoring.yaml"
    config_path = tmp_path / "workflow.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    (tmp_path / "candidate_scoring.yaml").write_text(
        Path("config/candidate_scoring.yaml").read_text(), encoding="utf-8"
    )
    principle = _principle(status="accepted", review_status="accepted")
    _write_json(
        tmp_path / "derived/principles/principle_review.json",
        {"principles": [principle.model_dump(mode="json")]},
    )
    _write_json(
        tmp_path / "derived/principles/transfer_assessments.json",
        {
            "semantic_transfer_version": "2.0",
            "assessments": [_transfer().model_dump(mode="json")],
        },
    )
    return config_path


def test_rank_writes_exploration_and_complete_coverage_artifacts(tmp_path):
    config_path = _prepare_v2_rank(tmp_path)

    result = run_principle_workflow(
        config_path,
        tmp_path,
        tmp_path,
        "rank",
        live=True,
        client=FakeClient(_payload()),
    )

    brief = json.loads(
        (tmp_path / "derived/principles/exploration_brief.json").read_text()
    )
    coverage = json.loads(
        (tmp_path / "derived/principles/coverage_audit.json").read_text()
    )
    assert result["coverage_complete"] is True
    assert brief["variable_role"]["role"] == "nucleophile"
    assert coverage["missing_superclass_ids"] == []


def test_disclosed_outcome_registry_never_enters_space_prompt(tmp_path):
    config_path = _prepare_v2_rank(tmp_path)
    config = yaml.safe_load(config_path.read_text())
    config["retrospective_development_registry"] = (
        "retrospective_development_outcomes.yaml"
    )
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    (tmp_path / "retrospective_development_outcomes.yaml").write_text(
        "prospective_metric_eligible: false\noutcomes:\n  - family: SH/thiol\n    status: confirmed_success\n",
        encoding="utf-8",
    )
    client = FakeClient(_payload())

    run_principle_workflow(
        config_path, tmp_path, tmp_path, "rank", live=True, client=client
    )

    assert "confirmed_success" not in client.inputs[0]
    assert "retrospective_development_outcomes" not in client.inputs[0]


def test_stage_two_requires_reviewed_stage_one_manifest(tmp_path):
    config_path = _prepare_v2_rank(
        tmp_path, stage="electrophile_family_expansion"
    )

    with pytest.raises(PrincipleWorkflowGateError, match="reviewed Stage 1"):
        run_principle_workflow(
            config_path,
            tmp_path,
            tmp_path,
            "rank",
            live=True,
            client=FakeClient(deepcopy(_payload())),
        )

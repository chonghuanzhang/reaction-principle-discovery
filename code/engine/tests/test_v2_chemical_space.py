from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from pipeline.api_client import ApiResult, ApiUsage
from pipeline.exploration_brief import load_exploration_brief
from pipeline.model_proposals import ModelProposalError, propose_chemical_space
from pipeline.model_proposals import (
    _select_batch_context,
    select_chemical_space_evidence,
)
from tests.test_candidate_ranking import RUBRIC
from tests.test_principle_induction import _principle, _transfer


SUPERCLASSES = (
    "NUC-ORGANOMETALLIC-C",
    "NUC-SOFT-ANIONIC-S",
    "NUC-NEUTRAL-PI-C",
    "NUC-O-C-AMBIDENT",
    "NUC-SULFUR-TRANSFER",
    "NUC-ANIONIC-C",
    "NUC-O",
    "NUC-N",
)


def _brief():
    config = yaml.safe_load(Path("config/principle_workflow.yaml").read_text())
    return load_exploration_brief(config)


def _component(name: str, value: int | None, evidence_ids=("TA-001",)) -> dict:
    return {
        "name": name,
        "value": value,
        "rationale": f"Judgment for {name}.",
        "evidence_ids": list(evidence_ids),
    }


def _family(superclass_id: str) -> dict:
    suffix = superclass_id.removeprefix("NUC-")
    return {
        "superclass_id": superclass_id,
        "family_id": f"NF-{suffix}",
        "family_type": "nucleophile",
        "representative_nucleophile": f"representative {suffix}",
        "reactive_form": f"accessible {suffix} reactive form",
        "fixed_electrophile_id": "SR001",
        "catalyst_requirement": "unknown",
        "condition_window": {
            "catalyst": None,
            "ligand": None,
            "base": "screen mild base and no-base controls",
            "solvent": "screen polar and non-polar conditions",
            "temperature": "25-80 C",
            "time": "1-24 h",
            "atmosphere": "inert",
            "water_activity": "controlled",
            "additives": [],
        },
        "diagnostic_status": "proposed",
        "no_experiment_rationale": None,
        "compatibility_components": [
            _component(name, 1) for name in RUBRIC["weights"]
        ],
        "risk_components": [
            _component(name, 0) for name in RUBRIC["risk_penalties"]
        ],
        "compatible_principle_ids": ["RP-001"],
        "violated_principle_ids": [],
        "evidence_ids": ["TA-001"],
        "hard_blockers": [],
        "uncertainty": [],
    }


def _experiment(superclass_id: str, index: int) -> dict:
    suffix = superclass_id.removeprefix("NUC-")
    return {
        "experiment_id": f"EXP-V2-{index:02d}",
        "family_id": f"NF-{suffix}",
        "electrophile": "SR001 Chemical Science trifluoroethyl carbonyl substrate",
        "nucleophile": f"representative {suffix}",
        "catalyst": "screened",
        "ligand": "screened",
        "base": "mild base and no-base control",
        "solvent": "screened",
        "temperature": "25-80 C",
        "time": "1-24 h",
        "atmosphere": "inert",
        "bonus_components": [],
        "risk_components": [],
        "predicted_failure_modes": [],
        "supporting_principle_ids": ["RP-001"],
        "evidence_ids": ["TA-001"],
        "minimal_diagnostic_plan": ["19F NMR time course"],
        "uncertainty": [],
    }


def _payload() -> dict:
    return {
        "families": [_family(item) for item in SUPERCLASSES],
        "experiments": [
            _experiment(item, index) for index, item in enumerate(SUPERCLASSES, 1)
        ],
    }


class FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.inputs: list[str] = []

    def create_structured(self, model, input_text, schema, schema_name):
        self.inputs.append(input_text)
        return ApiResult(
            response_id="space-v2",
            returned_model=model,
            status="completed",
            parsed_output=self.payload,
            usage=ApiUsage(input_tokens=10, output_tokens=5, total_tokens=15),
        )


class SequencedFakeClient(FakeClient):
    def __init__(self, payloads):
        super().__init__(None)
        self.payloads = list(payloads)

    def create_structured(self, model, input_text, schema, schema_name):
        self.inputs.append(input_text)
        payload = self.payloads.pop(0)
        return ApiResult(
            response_id=f"space-v2-batch-{len(self.inputs)}",
            returned_model=model,
            status="completed",
            parsed_output=payload,
            usage=ApiUsage(input_tokens=10, output_tokens=5, total_tokens=15),
        )


def _propose(tmp_path, payload):
    principle = _principle(status="accepted", review_status="accepted")
    return propose_chemical_space(
        [principle],
        {"TA-001": _transfer()},
        FakeClient(payload),
        {"model": "fixture", "prompt_text": "Map v2 space.", "prompt_version": "6"},
        RUBRIC,
        tmp_path,
        exploration_brief=_brief(),
    )


def test_complete_v2_payload_covers_every_required_superclass(tmp_path):
    result = _propose(tmp_path, _payload())

    assert result.coverage_audit is not None
    assert result.coverage_audit.complete is True
    assert result.coverage_audit.missing_superclass_ids == ()
    assert {family.superclass_id for family in result.families} == set(SUPERCLASSES)


def test_batch_context_keeps_only_role_relevant_principles_and_evidence():
    soft = _principle(
        principle_id="RP-S",
        status="accepted",
        review_status="accepted",
        applicable_nucleophile_superclasses=["NUC-SOFT-ANIONIC-S"],
        supporting_transferred_evidence=["TA-S"],
    )
    nitrogen = _principle(
        principle_id="RP-N",
        status="accepted",
        review_status="accepted",
        applicable_nucleophile_superclasses=["NUC-N"],
        supporting_transferred_evidence=["TA-N"],
    )
    sulfur_assessment = _transfer().model_copy(
        update={
            "assessment_id": "TA-S",
            "matched_requirements": ("thiolate soft nucleophile",),
        }
    )
    nitrogen_assessment = _transfer().model_copy(
        update={
            "assessment_id": "TA-N",
            "matched_requirements": ("amine nitrogen nucleophile",),
        }
    )
    assessments = {"TA-S": sulfur_assessment, "TA-N": nitrogen_assessment}
    selection = select_chemical_space_evidence(
        [soft, nitrogen], assessments, max_assessments=2, max_per_paper=3
    )

    principles, selected, scoped_selection = _select_batch_context(
        [soft, nitrogen],
        assessments,
        selection,
        _brief(),
        ("NUC-SOFT-ANIONIC-S",),
        max_assessments=8,
        max_per_paper=3,
    )

    assert [row.principle_id for row in principles] == ["RP-S"]
    assert set(selected) == {"TA-S"}
    assert scoped_selection.assessment_ids == ("TA-S",)


def test_v2_space_can_generate_and_merge_cached_superclass_batches(tmp_path):
    payload = _payload()
    batches = []
    for start in (0, 4):
        superclass_ids = set(SUPERCLASSES[start : start + 4])
        batches.append(
            {
                "families": [
                    row for row in payload["families"]
                    if row["superclass_id"] in superclass_ids
                ],
                "experiments": [
                    row for row in payload["experiments"]
                    if row["family_id"]
                    in {family["family_id"] for family in payload["families"] if family["superclass_id"] in superclass_ids}
                ],
            }
        )
    principle = _principle(status="accepted", review_status="accepted")
    config = {
        "model": "fixture",
        "prompt_text": "Map v2 space.",
        "prompt_version": "6",
        "superclass_batch_size": 4,
    }
    first_client = SequencedFakeClient(batches)

    first = propose_chemical_space(
        [principle],
        {"TA-001": _transfer()},
        first_client,
        config,
        RUBRIC,
        tmp_path,
        exploration_brief=_brief(),
    )

    assert first.coverage_audit is not None and first.coverage_audit.complete is True
    assert len(first_client.inputs) == 2
    assert '"NUC-ORGANOMETALLIC-C"' in first_client.inputs[0]
    assert '"NUC-N"' not in first_client.inputs[0]
    assert '"NUC-N"' in first_client.inputs[1]

    next(tmp_path.glob("*/validated.json")).unlink()
    reuse_client = SequencedFakeClient([])
    reused = propose_chemical_space(
        [principle],
        {"TA-001": _transfer()},
        reuse_client,
        config,
        RUBRIC,
        tmp_path,
        exploration_brief=_brief(),
    )

    assert reused.coverage_audit is not None and reused.coverage_audit.complete is True
    assert reuse_client.inputs == []


def test_missing_required_superclass_rejects_space_proposal(tmp_path):
    payload = _payload()
    payload["families"] = [
        row for row in payload["families"]
        if row["superclass_id"] != "NUC-NEUTRAL-PI-C"
    ]

    with pytest.raises(ModelProposalError, match="missing nucleophile superclasses"):
        _propose(tmp_path, payload)


def test_insufficient_evidence_family_satisfies_coverage_without_fake_evidence(tmp_path):
    payload = _payload()
    family = next(row for row in payload["families"] if row["superclass_id"] == "NUC-N")
    family["compatibility_components"] = [
        _component(name, None, evidence_ids=()) for name in RUBRIC["weights"]
    ]
    family["risk_components"] = [
        _component(name, None, evidence_ids=()) for name in RUBRIC["risk_penalties"]
    ]
    family["evidence_ids"] = []
    family["diagnostic_status"] = "not_executable"
    family["no_experiment_rationale"] = "No evidence-grounded executable condition window."
    payload["experiments"] = [
        row for row in payload["experiments"] if row["family_id"] != "NF-N"
    ]

    result = _propose(tmp_path, payload)

    prediction = next(row for row in result.families if row.superclass_id == "NUC-N")
    assert prediction.classification == "insufficient_evidence"
    assert result.coverage_audit.missing_superclass_ids == ()


def test_stage_one_family_cannot_change_fixed_electrophile(tmp_path):
    payload = deepcopy(_payload())
    payload["families"][0]["fixed_electrophile_id"] = "different-electrophile"

    with pytest.raises(ModelProposalError, match="fixed electrophile"):
        _propose(tmp_path, payload)

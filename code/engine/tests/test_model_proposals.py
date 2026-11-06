import pytest

from pipeline.api_client import ApiResult, ApiUsage
from pipeline.model_proposals import (
    ChemicalSpaceProposalPayload,
    ModelProposalError,
    PrincipleProposalPayload,
    _strict_schema,
    propose_chemical_space,
    propose_reaction_principles,
    select_chemical_space_evidence,
    select_principle_evidence,
)
from pipeline.seed_modeling import seed_model_schema
from pipeline.principle_models import SeedMechanism
from tests.test_candidate_ranking import RUBRIC
from tests.test_principle_induction import _principle, _transfer


class FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0
        self.inputs = []

    def create_structured(self, model, input_text, schema, schema_name):
        self.calls += 1
        self.inputs.append(input_text)
        return ApiResult(
            response_id="proposal-response",
            returned_model=model,
            status="completed",
            parsed_output=self.payload,
            usage=ApiUsage(input_tokens=10, output_tokens=5, total_tokens=15),
        )


def _seed() -> SeedMechanism:
    return SeedMechanism(
        seed_reaction_id="SEED-001",
        reaction_center=["C-F-bearing carbon"],
        electrophile_state=["activated fluorinated substrate"],
        nucleophile_state=["organoboron-derived carbon"],
        bond_changes=["C-C formation"],
        reactive_intermediates=["fluorinated alkene-like intermediate"],
        elementary_steps=["activation", "nucleophilic trapping"],
        electronic_requirements=["selective activation"],
        steric_requirements=[],
        catalyst_roles=["palladium activation"],
        condition_window=["moderate base"],
        successful_scope=["organoboron"],
        failed_scope=[],
        competing_pathways=["over-defluorination"],
        evidence_ids=["SEED-E001"],
        confidence="medium",
    )


def _component(name, value, evidence_ids=("TA-001",)):
    return {
        "name": name,
        "value": value,
        "rationale": f"Judgment for {name}.",
        "evidence_ids": list(evidence_ids),
    }


def _chemical_space_payload():
    compatibility = [_component(name, 1) for name in RUBRIC["weights"]]
    risks = [_component(name, 0) for name in RUBRIC["risk_penalties"]]
    return {
        "families": [
            {
                "family_id": "NU-S",
                "family_type": "nucleophile",
                "compatibility_components": compatibility,
                "risk_components": risks,
                "compatible_principle_ids": ["RP-001"],
                "violated_principle_ids": [],
                "required_conditions": ["non-oxidizing"],
                "evidence_ids": ["TA-001"],
                "hard_blockers": [],
                "uncertainty": [],
            }
        ],
        "experiments": [
            {
                "experiment_id": "EXP-001",
                "family_id": "NU-S",
                "electrophile": "trifluoroethyl amide",
                "nucleophile": "thiophenol",
                "catalyst": "Pd",
                "ligand": "L1",
                "base": "base",
                "solvent": "solvent",
                "temperature": "60 C",
                "time": "8 h",
                "atmosphere": "N2",
                "bonus_components": [],
                "risk_components": [],
                "predicted_failure_modes": [],
                "supporting_principle_ids": ["RP-001"],
                "evidence_ids": ["TA-001"],
                "minimal_diagnostic_plan": ["19F NMR time course"],
                "uncertainty": [],
            }
        ],
    }


def _assessment(
    assessment_id,
    status,
    paper_id,
    step,
    *,
    blockers=(),
    mismatches=(),
):
    return _transfer(status).model_copy(
        update={
            "assessment_id": assessment_id,
            "source_paper_id": paper_id,
            "source_mechanism_id": f"{paper_id}::ME001",
            "shared_elementary_step": step,
            "blocking_constraints": tuple(blockers),
            "mismatched_requirements": tuple(mismatches),
        }
    )


def test_principle_evidence_selection_is_stratified_bounded_and_paper_diverse():
    assessments = {
        row.assessment_id: row
        for row in (
            _assessment("TA-P", "transferable", "paper-1", "trapping"),
            _assessment("TA-C", "conditional", "paper-2", "elimination"),
            _assessment(
                "TA-N",
                "non_transferable",
                "paper-3",
                "activation",
                blockers=("paper-3::BC001",),
            ),
            _assessment(
                "TA-X",
                "non_transferable",
                "paper-4",
                "transmetalation",
                mismatches=("shared_elementary_step",),
            ),
            _assessment("TA-U", "unknown", "paper-5", "product stability"),
            _assessment("TA-P2", "transferable", "paper-1", "trapping"),
        )
    }

    selection = select_principle_evidence(
        _seed(), assessments, max_assessments=5, max_per_paper=1
    )

    assert selection.seed_evidence_ids == ("SEED-E001",)
    assert set(selection.strata) == {
        "positive",
        "conditional",
        "explicit_negative",
        "contradictory",
        "unknown",
    }
    assert all(len(ids) == 1 for ids in selection.strata.values())
    assert len(selection.assessment_ids) == 5
    assert max(selection.paper_counts.values()) == 1


def test_principle_model_prompt_contains_only_bounded_selected_assessments(tmp_path):
    proposed = _principle().model_dump(mode="json")
    client = FakeClient({"principles": [proposed]})
    selected = _transfer()
    omitted = selected.model_copy(
        update={
            "assessment_id": "TA-OMITTED",
            "source_paper_id": "same-paper",
            "source_mechanism_id": "same-paper::ME002",
        }
    )

    propose_reaction_principles(
        _seed(),
        {selected.assessment_id: selected, omitted.assessment_id: omitted},
        client,
        {
            "model": "fixture",
            "prompt_text": "Propose.",
            "prompt_version": "1",
            "max_assessments": 1,
            "max_per_paper": 1,
        },
        tmp_path,
    )

    assert "TA-001" in client.inputs[0]
    assert "TA-OMITTED" not in client.inputs[0]


def test_principle_model_proposal_stays_pending_and_validates_anchors(tmp_path):
    proposed = _principle().model_dump(mode="json")
    client = FakeClient({"principles": [proposed]})

    result = propose_reaction_principles(
        _seed(),
        {"TA-001": _transfer()},
        client,
        {"model": "fixture", "prompt_text": "Propose.", "prompt_version": "1"},
        tmp_path,
    )

    assert result.principles[0].review_status == "pending"
    assert result.principles[0].status == "proposed"
    assert client.calls == 1


def test_principle_model_rejects_unknown_transfer_anchor(tmp_path):
    proposed = _principle(supporting_transferred_evidence=["TA-999"]).model_dump(mode="json")

    with pytest.raises(ModelProposalError, match="unknown transfer assessment"):
        propose_reaction_principles(
            _seed(),
            {"TA-001": _transfer()},
            FakeClient({"principles": [proposed]}),
            {"model": "fixture", "prompt_text": "Propose.", "prompt_version": "1"},
            tmp_path,
        )


def test_chemical_space_evidence_selection_retains_reviewed_anchors_and_is_bounded():
    assessments = {
        row.assessment_id: row
        for row in (
            _assessment("TA-P", "transferable", "paper-1", "trapping"),
            _assessment("TA-C", "conditional", "paper-2", "elimination"),
            _assessment(
                "TA-N",
                "non_transferable",
                "paper-3",
                "activation",
                blockers=("paper-3::BC001",),
            ),
            _assessment(
                "TA-X",
                "non_transferable",
                "paper-4",
                "transmetalation",
                mismatches=("shared_elementary_step",),
            ),
            _assessment("TA-U", "unknown", "paper-5", "product stability"),
            _assessment("TA-EXTRA", "conditional", "paper-6", "elimination"),
        )
    }
    reviewed = _principle(
        status="accepted",
        review_status="accepted",
        supporting_transferred_evidence=["TA-C"],
        contradictory_evidence=["TA-N"],
    )

    selection = select_chemical_space_evidence(
        [reviewed], assessments, max_assessments=5, max_per_paper=1
    )

    assert set(selection.anchor_assessment_ids) == {"TA-C", "TA-N"}
    assert set(selection.anchor_assessment_ids).issubset(selection.assessment_ids)
    assert len(selection.assessment_ids) == 5
    assert selection.strata["positive"] == ("TA-P",)
    assert selection.strata["contradictory"] == ("TA-X",)
    assert selection.strata["unknown"] == ("TA-U",)
    assert max(selection.paper_counts.values()) == 1


def test_chemical_space_model_proposal_is_deterministically_classified_and_ranked(tmp_path):
    payload = _chemical_space_payload()

    omitted = _assessment(
        "TA-OMITTED", "unknown", "omitted-paper", "unresolved pathway"
    )
    client = FakeClient(payload)
    result = propose_chemical_space(
        [_principle(status="accepted", review_status="accepted")],
        {"TA-001": _transfer(), omitted.assessment_id: omitted},
        client,
        {
            "model": "fixture",
            "prompt_text": "Map space.",
            "prompt_version": "1",
            "max_assessments": 1,
            "max_per_paper": 1,
        },
        RUBRIC,
        tmp_path,
    )

    assert result.families[0].classification == "explore"
    assert result.candidates[0].experiment_id == "EXP-001"
    assert result.candidates[0].freeze_status == "provisional"
    assert "TA-001" in client.inputs[0]
    assert "TA-OMITTED" not in client.inputs[0]
    assert "Principle IDs are not evidence IDs" in client.inputs[0]
    assert "experiment.family_id must exactly equal one proposed family_id" in client.inputs[0]
    assert '"allowed_hard_blocker_constraint_ids": []' in client.inputs[0]
    assert '"required_compatibility_component_names"' in client.inputs[0]
    assert '"required_risk_component_names"' in client.inputs[0]


def test_chemical_space_revalidates_raw_cache_without_another_model_call(tmp_path):
    principle = _principle(status="accepted", review_status="accepted")
    client = FakeClient(_chemical_space_payload())
    config = {"model": "fixture", "prompt_text": "Map space.", "prompt_version": "1"}

    first = propose_chemical_space(
        [principle], {"TA-001": _transfer()}, client, config, RUBRIC, tmp_path
    )
    next(tmp_path.glob("*/validated.json")).unlink()
    second = propose_chemical_space(
        [principle], {"TA-001": _transfer()}, client, config, RUBRIC, tmp_path
    )

    assert first.families == second.families
    assert second.status == "reused"
    assert client.calls == 1


def test_chemical_space_rejects_unqualified_hard_blocker(tmp_path):
    compatibility = [_component(name, 1) for name in RUBRIC["weights"]]
    risks = [_component(name, 0) for name in RUBRIC["risk_penalties"]]
    payload = {
        "families": [
            {
                "family_id": "NU-S",
                "family_type": "nucleophile",
                "compatibility_components": compatibility,
                "risk_components": risks,
                "compatible_principle_ids": ["RP-001"],
                "violated_principle_ids": [],
                "required_conditions": [],
                "evidence_ids": ["TA-001"],
                "hard_blockers": ["inferred catalyst poisoning"],
                "uncertainty": [],
            }
        ],
        "experiments": [
            {
                "experiment_id": "EXP-001",
                "family_id": "NU-S",
                "electrophile": "electrophile",
                "nucleophile": "nucleophile",
                "catalyst": "Pd",
                "ligand": "unknown",
                "base": "KHCO3",
                "solvent": "DCE",
                "temperature": "80 C",
                "time": "12 h",
                "atmosphere": "sealed",
                "bonus_components": [],
                "risk_components": [],
                "predicted_failure_modes": [],
                "supporting_principle_ids": ["RP-001"],
                "evidence_ids": ["TA-001"],
                "minimal_diagnostic_plan": ["19F NMR"],
                "uncertainty": [],
            }
        ],
    }

    with pytest.raises(ModelProposalError, match="unknown hard blocker"):
        propose_chemical_space(
            [_principle(status="accepted", review_status="accepted")],
            {"TA-001": _transfer()},
            FakeClient(payload),
            {"model": "fixture", "prompt_text": "Map space."},
            RUBRIC,
            tmp_path,
        )


def test_live_model_schemas_forbid_extra_fields_on_every_object():
    schemas = [
        seed_model_schema(),
        _strict_schema(PrincipleProposalPayload),
        _strict_schema(ChemicalSpaceProposalPayload),
    ]

    def objects(value):
        if isinstance(value, dict):
            if value.get("type") == "object" or "properties" in value:
                yield value
            for child in value.values():
                yield from objects(child)
        elif isinstance(value, list):
            for child in value:
                yield from objects(child)

    assert all(
        node.get("additionalProperties") is False
        for schema in schemas
        for node in objects(schema)
    )
    space_schema = _strict_schema(ChemicalSpaceProposalPayload)
    assert set(
        space_schema["$defs"]["CompatibilityComponentJudgment"]["properties"]["name"]["enum"]
    ) == set(RUBRIC["weights"])
    assert set(
        space_schema["$defs"]["RiskComponentJudgment"]["properties"]["name"]["enum"]
    ) == set(RUBRIC["risk_penalties"])

from pathlib import Path

import pytest
import yaml

from pipeline.api_client import ApiResult, ApiUsage
from pipeline.exploration_brief import load_exploration_brief
from pipeline.model_proposals import (
    index_assessments_by_nucleophile_role,
    propose_reaction_principles,
    select_principle_evidence,
)
from pipeline.principle_induction import PrincipleInductionError, validate_principle_candidate
from pipeline.principle_models import (
    ReactionPrinciple,
    SeedMechanism,
    TransferabilityAssessment,
)


def _brief():
    config = yaml.safe_load(Path("config/principle_workflow.yaml").read_text())
    return load_exploration_brief(config)


def _transfer(
    assessment_id: str,
    claim: str,
    matched: tuple[str, ...],
) -> TransferabilityAssessment:
    return TransferabilityAssessment(
        assessment_id=assessment_id,
        source_paper_id=f"paper-{assessment_id}",
        source_mechanism_id=f"paper-{assessment_id}::ME001",
        source_evidence_ids=(f"{assessment_id}-E001",),
        seed_feature_ids=("SEED-E001",),
        shared_elementary_step="nucleophilic trapping",
        matched_requirements=matched,
        mismatched_requirements=(),
        blocking_constraints=(),
        transfer_status="conditional",
        transferable_claim=claim,
        conditions=(),
        uncertainty=(),
        falsifying_test="Run the matched pair.",
        score_components={"total": 5},
    )


def _principle(**updates) -> ReactionPrinciple:
    values = {
        "principle_id": "RP-V2-001",
        "principle_layer": "seed_specific",
        "title": "Seed-specific transfer",
        "status": "proposed",
        "claim": "A compatible partner can trap the activated Seed manifold.",
        "mechanistic_basis": ["nucleophilic trapping"],
        "applicable_electrophile_families": ["Seed trifluoroethyl carbonyl"],
        "applicable_nucleophile_families": ["organoboron"],
        "applicable_nucleophile_superclasses": [],
        "required_reactive_form": "transmetalation-competent organoboron",
        "catalyst_requirements": ["palladium-compatible"],
        "condition_window": ["moderate base"],
        "structural_promoters": [],
        "structural_inhibitors": [],
        "supporting_seed_evidence": ["SEED-E001"],
        "supporting_transferred_evidence": ["TA-S"],
        "contradictory_evidence": [],
        "known_exceptions": [],
        "predicted_failure_modes": ["catalyst poisoning"],
        "confidence": "low",
        "experimental_consequence": "Test a matched partner series.",
        "falsifying_experiment": "Run a controlled matched series.",
        "review_status": "pending",
        "provenance": {"run_id": "run-v2"},
        "freeze_version": None,
    }
    values.update(updates)
    return ReactionPrinciple(**values)


def _seed() -> SeedMechanism:
    return SeedMechanism(
        seed_reaction_id="SR001",
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


class FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.inputs: list[str] = []

    def create_structured(self, model, input_text, schema, schema_name):
        self.inputs.append(input_text)
        return ApiResult(
            response_id="v2-response",
            returned_model=model,
            status="completed",
            parsed_output=self.payload,
            usage=ApiUsage(input_tokens=10, output_tokens=5, total_tokens=15),
        )


def test_seed_specific_principle_cannot_claim_universal_nucleophile_scope():
    assessment = _transfer("TA-S", "A thiolate can trap the activated alkene.", ("thiolate",))
    principle = _principle(applicable_nucleophile_families=["all nucleophiles"])

    with pytest.raises(PrincipleInductionError, match="universal"):
        validate_principle_candidate(
            principle,
            known_seed_evidence_ids={"SEED-E001"},
            transfer_assessments={assessment.assessment_id: assessment},
        )


def test_role_aware_index_preserves_superclass_buckets_and_unmapped_rows():
    assessments = {
        "TA-S": _transfer(
            "TA-S", "A thiolate sulfur nucleophile traps the alkene.", ("thiolate",)
        ),
        "TA-X": _transfer(
            "TA-X", "A locally similar step has no stated partner identity.", ("unknown",)
        ),
    }

    index = index_assessments_by_nucleophile_role(assessments, _brief())

    assert index.superclass_assessment_ids["NUC-SOFT-ANIONIC-S"] == ("TA-S",)
    assert index.unmapped_assessment_ids == ("TA-X",)


def test_principle_selection_preserves_each_available_nucleophile_superclass():
    assessments = {
        "TA-S": _transfer("TA-S", "Thiolate trapping is reported.", ("thiolate",)),
        "TA-PI": _transfer("TA-PI", "Indole pi nucleophile attack is reported.", ("indole",)),
        "TA-SS": _transfer("TA-SS", "Disulfide sulfur transfer is reported.", ("disulfide",)),
    }

    selection = select_principle_evidence(
        _seed(),
        assessments,
        max_assessments=20,
        max_per_paper=2,
        exploration_brief=_brief(),
    )

    assert selection.superclass_counts["NUC-SOFT-ANIONIC-S"] >= 1
    assert selection.superclass_counts["NUC-NEUTRAL-PI-C"] >= 1
    assert selection.superclass_counts["NUC-SULFUR-TRANSFER"] >= 1


def test_principle_prompt_contains_brief_evidence_index_and_layer_contract(tmp_path):
    assessment = _transfer("TA-S", "A thiolate can trap the activated alkene.", ("thiolate",))
    payload = {
        "principles": [
            _principle().model_dump(mode="json"),
            _principle(
                principle_id="RP-V2-002",
                principle_layer="transferable_super",
                title="General local trapping",
                applicable_nucleophile_families=["soft sulfur nucleophile"],
                required_reactive_form="accessible nucleophilic sulfur species",
                applicable_nucleophile_superclasses=["NUC-SOFT-ANIONIC-S"],
            ).model_dump(mode="json"),
        ]
    }
    client = FakeClient(payload)

    propose_reaction_principles(
        _seed(),
        {assessment.assessment_id: assessment},
        client,
        {"model": "fixture", "prompt_text": "Propose.", "prompt_version": "2"},
        tmp_path,
        exploration_brief=_brief(),
    )

    prompt = client.inputs[0]
    assert '"label": "substrate B"' in prompt
    assert '"NUC-SOFT-ANIONIC-S": ["TA-S"]' in prompt
    assert "seed_specific" in prompt
    assert "transferable_super" in prompt

import json

import pytest

from pipeline.api_client import ApiResult, ApiUsage
from pipeline.paper_mechanism_bundles import load_paper_mechanism_bundles
from pipeline.principle_models import SeedMechanism
from pipeline.semantic_transfer import (
    ModelSemanticTransferError,
    TRANSFER_DIMENSIONS,
    build_semantic_transfer_input,
    propose_paper_transfer,
    semantic_transfer_schema,
)
from tests.test_paper_mechanism_bundles import _write_fixture


class FakeClient:
    def __init__(self, payload: dict):
        self.payload = payload
        self.calls = 0

    def create_structured(self, model, input_text, schema, schema_name):
        self.calls += 1
        return ApiResult(
            response_id="transfer-response",
            returned_model=model,
            status="completed",
            parsed_output=self.payload,
            usage=ApiUsage(input_tokens=20, output_tokens=10, total_tokens=30),
        )


def _seed() -> SeedMechanism:
    return SeedMechanism(
        seed_reaction_id="SEED-001",
        reaction_center=["trifluoroethyl carbonyl"],
        electrophile_state=["activated C-F center"],
        nucleophile_state=["soft nucleophile"],
        bond_changes=["form C-Nu", "break C-F"],
        reactive_intermediates=["gem-difluoroalkene"],
        elementary_steps=["nucleophilic trapping", "beta-F elimination"],
        electronic_requirements=["electrophilic fluorinated carbon"],
        steric_requirements=["accessible reaction center"],
        catalyst_roles=["palladium activation"],
        condition_window=["moderate base"],
        successful_scope=["organoboron"],
        failed_scope=["alkyl organoboron under the reported condition"],
        competing_pathways=["over-defluorination"],
        evidence_ids=["SE-001", "SE-002"],
        confidence="medium",
    )


def _component(dimension: str, bundle, judgment: str = "match") -> dict:
    return {
        "dimension": dimension,
        "judgment": judgment,
        "rationale": f"Grounded comparison for {dimension}.",
        "seed_evidence_ids": ["SE-001"],
        "literature_evidence_ids": [bundle.mechanisms[0].source_evidence_ids[0]],
    }


def _payload(bundle, *, blocker_ids=()) -> dict:
    return {
        "mechanisms": [
            {
                "mechanism_id": bundle.mechanisms[0].mechanism_evidence_id,
                "components": [
                    _component(dimension, bundle) for dimension in TRANSFER_DIMENSIONS
                ],
                "hard_blocker_constraint_ids": list(blocker_ids),
                "conditions": ["moderate base"],
                "uncertainty": [],
                "transferable_claim": "This trapping step may transfer to the Seed manifold.",
                "falsifying_test": "Remove the activated fluorinated center and test for trapping.",
            }
        ]
    }


def _config() -> dict:
    return {
        "model": "fixture-model",
        "prompt_version": "1.0",
        "rubric_version": "2.0",
        "prompt_text": "Compare one literature mechanism bundle with the Seed Reaction.",
    }


def test_semantic_transfer_schema_is_strict_for_every_object():
    schema = semantic_transfer_schema()

    def objects(value):
        if isinstance(value, dict):
            if value.get("type") == "object" or "properties" in value:
                yield value
            for child in value.values():
                yield from objects(child)
        elif isinstance(value, list):
            for child in value:
                yield from objects(child)

    for node in objects(schema):
        assert node.get("additionalProperties") is False
        assert set(node.get("required", [])) == set(node.get("properties", {}))


def test_semantic_transfer_input_contains_one_bundle_and_no_hidden_answers(tmp_path):
    _write_fixture(tmp_path)
    bundle = load_paper_mechanism_bundles(tmp_path)[0]

    prompt = build_semantic_transfer_input(_seed(), bundle, _config()["prompt_text"])

    assert bundle.source_path in prompt
    assert load_paper_mechanism_bundles(tmp_path)[1].source_path not in prompt
    assert set(TRANSFER_DIMENSIONS) <= {dimension for dimension in TRANSFER_DIMENSIONS if dimension in prompt}
    assert "PL30.xlsx" not in prompt
    assert "新反应发现.pptx" not in prompt


def test_semantic_transfer_validates_provenance_and_reuses_cache(tmp_path):
    _write_fixture(tmp_path)
    bundle = load_paper_mechanism_bundles(tmp_path)[0]
    client = FakeClient(_payload(bundle))

    first = propose_paper_transfer(_seed(), bundle, client, _config(), tmp_path)
    second = propose_paper_transfer(_seed(), bundle, client, _config(), tmp_path)

    assert first.status == "validated"
    assert second.status == "reused"
    assert client.calls == 1
    assert first.proposals[0].components[0].judgment == "match"
    paper_root = tmp_path / bundle.namespace
    assert (paper_root / "raw.json").stat().st_mtime_ns <= (
        paper_root / "validated_proposal.json"
    ).stat().st_mtime_ns


def test_semantic_transfer_rejects_cross_paper_constraint(tmp_path):
    _write_fixture(tmp_path)
    first, second = load_paper_mechanism_bundles(tmp_path)

    with pytest.raises(ModelSemanticTransferError, match="unknown same-paper constraint"):
        propose_paper_transfer(
            _seed(),
            first,
            FakeClient(_payload(first, blocker_ids=[second.constraints[0].constraint_id])),
            _config(),
            tmp_path,
        )


def test_semantic_transfer_downgrades_same_paper_non_incompatible_blocker(tmp_path):
    _write_fixture(tmp_path)
    bundle = load_paper_mechanism_bundles(tmp_path)[0]
    threshold = bundle.constraints[0].model_copy(update={"direction": "threshold"})
    bundle = bundle.model_copy(update={"constraints": (threshold,)})

    result = propose_paper_transfer(
        _seed(),
        bundle,
        FakeClient(_payload(bundle, blocker_ids=[threshold.constraint_id])),
        _config(),
        tmp_path,
    )

    proposal = result.proposals[0]
    assert proposal.hard_blocker_constraint_ids == ()
    assert proposal.uncertainty == (
        f"model-nominated non-incompatible constraint retained as a conditional concern: "
        f"{threshold.constraint_id} (threshold)",
    )


def test_semantic_transfer_requires_each_mechanism_exactly_once(tmp_path):
    _write_fixture(tmp_path)
    bundle = load_paper_mechanism_bundles(tmp_path)[0]

    with pytest.raises(ModelSemanticTransferError, match="mechanism coverage mismatch"):
        propose_paper_transfer(
            _seed(), bundle, FakeClient({"mechanisms": []}), _config(), tmp_path
        )

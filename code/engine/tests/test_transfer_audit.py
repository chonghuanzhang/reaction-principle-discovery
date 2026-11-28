import json

import pytest
import yaml

from pipeline.principle_workflow import run_principle_workflow
from pipeline.semantic_transfer import TRANSFER_DIMENSIONS
from pipeline.transfer_audit import TransferAuditError, audit_knowledge_transfer
from pipeline.paper_mechanism_bundles import (
    load_paper_mechanism_bundles,
    write_source_revisit_registry,
)
from tests.test_paper_mechanism_bundles import _write_fixture
from tests.test_principle_workflow import SemanticTransferFakeClient
from tests.test_transferability import _seed


def _write_completed_transfer(root):
    _write_fixture(root)
    write_source_revisit_registry(root, load_paper_mechanism_bundles(root))
    principles = root / "derived/principles"
    (principles / "seed_mechanism.json").write_text(
        _seed().model_dump_json(), encoding="utf-8"
    )
    rubric = {
        "version": "2.0",
        "weights": {dimension: 2 for dimension in TRANSFER_DIMENSIONS},
        "critical_unknown_dimensions": list(TRANSFER_DIMENSIONS[:3]),
    }
    (root / "transferability.yaml").write_text(
        yaml.safe_dump(rubric), encoding="utf-8"
    )
    config = root / "workflow.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "seed_mechanism_path": "derived/principles/seed_mechanism.json",
                "transferability_config": "transferability.yaml",
                "semantic_transfer": {
                    "model": "fixture",
                    "prompt_text": "Assess semantic transfer.",
                    "prompt_version": "2.0",
                    "rubric_version": "2.0",
                },
            }
        ),
        encoding="utf-8",
    )
    run_principle_workflow(
        config,
        root,
        root,
        "transfer",
        live=True,
        client=SemanticTransferFakeClient(),
    )
    return config


def test_transfer_audit_accounts_for_every_paper_mechanism_and_revisit(tmp_path):
    _write_completed_transfer(tmp_path)

    audit = audit_knowledge_transfer(tmp_path)

    assert audit.paper_count == 2
    assert audit.mechanism_count == 2
    assert audit.assessment_count == 2
    assert audit.unique_assessment_count == 2
    assert audit.missing_paper_count == 0
    assert audit.missing_mechanism_count == 0
    assert audit.provenance_violation_count == 0


def test_transfer_audit_rejects_duplicate_aggregate_assessment_ids(tmp_path):
    _write_completed_transfer(tmp_path)
    path = tmp_path / "derived/principles/transfer_assessments.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["assessments"][1]["assessment_id"] = payload["assessments"][0]["assessment_id"]
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(TransferAuditError, match="duplicate assessment IDs"):
        audit_knowledge_transfer(tmp_path)


def test_transfer_audit_rejects_unknown_component_scored_as_zero(tmp_path):
    _write_completed_transfer(tmp_path)
    namespace = "1" * 12
    proposal_path = (
        tmp_path
        / "derived/principles/semantic_transfer"
        / namespace
        / "validated_proposal.json"
    )
    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
    proposal["proposal"]["mechanisms"][0]["components"][0]["judgment"] = "unknown"
    proposal_path.write_text(json.dumps(proposal), encoding="utf-8")
    adjudicated_path = proposal_path.parent / "adjudicated.json"
    adjudicated = json.loads(adjudicated_path.read_text(encoding="utf-8"))
    adjudicated["assessments"][0]["score_components"]["shared_elementary_step"] = 0
    adjudicated_path.write_text(json.dumps(adjudicated), encoding="utf-8")

    with pytest.raises(TransferAuditError, match="unknown component was scored numerically"):
        audit_knowledge_transfer(tmp_path)


def test_transfer_audit_rejects_hidden_marker_in_paper_level_artifact(tmp_path):
    _write_completed_transfer(tmp_path)
    proposal_path = (
        tmp_path
        / "derived/principles/semantic_transfer"
        / ("1" * 12)
        / "validated_proposal.json"
    )
    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
    proposal["proposal"]["mechanisms"][0]["components"][0][
        "rationale"
    ] = "Leaked marker: PL30.xlsx"
    proposal_path.write_text(json.dumps(proposal), encoding="utf-8")

    with pytest.raises(TransferAuditError, match="hidden-answer marker"):
        audit_knowledge_transfer(tmp_path)

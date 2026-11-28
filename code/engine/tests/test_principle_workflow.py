import json
import threading
from pathlib import Path

import pytest
import yaml

import pipeline.principle_workflow as principle_workflow
import pipeline.run_pilot as run_pilot
from pipeline.api_client import ApiResult, ApiUsage
from pipeline.principle_workflow import (
    PrincipleWorkflowError,
    PrincipleWorkflowGateError,
    build_principle_status,
    run_principle_workflow,
)
from tests.test_seed_modeling import FakeClient as SeedFakeClient
from tests.test_seed_modeling import _docx, _payload as seed_payload
from tests.test_model_proposals import FakeClient as ProposalFakeClient
from tests.test_model_proposals import _component, _seed
from tests.test_principle_induction import _principle, _transfer
from tests.test_candidate_ranking import RUBRIC
from tests.test_paper_mechanism_bundles import _write_fixture as _write_bundle_fixture
from tests.test_transferability import _seed as _transfer_seed
from pipeline.semantic_transfer import TRANSFER_DIMENSIONS
from pipeline.transfer_audit import KnowledgeTransferAudit


def test_default_client_forwards_configured_read_timeout(monkeypatch):
    observed: dict[str, object] = {}
    sentinel = object()

    def build_client(model: str, *, read_timeout_seconds: int):
        observed.update(
            model=model,
            read_timeout_seconds=read_timeout_seconds,
        )
        return sentinel

    monkeypatch.setattr(run_pilot, "_default_client", build_client)

    assert (
        principle_workflow._default_client("fixture", read_timeout_seconds=1200)
        is sentinel
    )
    assert observed == {"model": "fixture", "read_timeout_seconds": 1200}


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def create_structured(self, model, input_text, schema, schema_name):
        source = json.loads(input_text.split("BEGIN_VALIDATED_LITERATURE_RECORD\n", 1)[1].split("\nEND_VALIDATED", 1)[0])["source_file"]
        self.calls.append(source)
        if source == "papers/two.pdf":
            raise RuntimeError("fixture normalization failure")
        revisit = []
        if source == "papers/three.pdf":
            revisit = [
                {
                    "request_id": "SR-003",
                    "source_paper_id": "paper-3",
                    "pdf_pages": [2],
                    "reason": "critical_visual",
                    "question": "Confirm the visual mechanism assignment.",
                    "status": "pending",
                }
            ]
        return ApiResult(
            response_id="resp-" + source,
            returned_model=model,
            status="completed",
            parsed_output={
                "mechanism_evidence": [
                    {
                        "mechanism_evidence_id": "ME-" + source,
                        "source_paper_id": source.replace("papers/", "paper-").replace(".pdf", ""),
                        "source_evidence_ids": ["E001"],
                        "evidence_type": "elementary_step",
                        "elementary_step": "nucleophilic trapping",
                        "starting_state": "starting state",
                        "ending_state": "ending state",
                        "bond_changes": ["form C-S"],
                        "catalyst_role": "none established",
                        "nucleophile_requirements": ["sulfur nucleophile"],
                        "electrophile_requirements": ["fluorinated alkene"],
                        "condition_requirements": ["base-compatible"],
                        "observed_outcome": "monofluoroalkene",
                        "failure_mode": None,
                        "evidence_label": "LITERATURE FACT",
                        "evidence_strength": "direct",
                        "quotation": None,
                        "pdf_page": None,
                        "confidence": "high",
                    }
                ],
                "boundary_constraints": [],
                "source_revisit_requests": revisit,
            },
            usage=ApiUsage(input_tokens=3, output_tokens=2, total_tokens=5),
        )


class SemanticTransferFakeClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def create_structured(self, model, input_text, schema, schema_name):
        bundle = json.loads(
            input_text.split("BEGIN_ONE_PAPER_MECHANISM_BUNDLE\n", 1)[1].split(
                "\nEND_ONE_PAPER_MECHANISM_BUNDLE", 1
            )[0]
        )
        self.calls.append(bundle["source_path"])
        mechanisms = []
        for mechanism in bundle["mechanisms"]:
            mechanisms.append(
                {
                    "mechanism_id": mechanism["mechanism_evidence_id"],
                    "components": [
                        {
                            "dimension": dimension,
                            "judgment": "match",
                            "rationale": f"Grounded match for {dimension}.",
                            "seed_evidence_ids": ["SEED-E001"],
                            "literature_evidence_ids": [mechanism["source_evidence_ids"][0]],
                        }
                        for dimension in TRANSFER_DIMENSIONS
                    ],
                    "hard_blocker_constraint_ids": [],
                    "conditions": ["moderate base"],
                    "uncertainty": [],
                    "transferable_claim": "The mechanism is compatible with the Seed manifold.",
                    "falsifying_test": "Remove the activated C-F center.",
                }
            )
        return ApiResult(
            response_id="semantic-" + bundle["namespace"],
            returned_model=model,
            status="completed",
            parsed_output={"mechanisms": mechanisms},
            usage=ApiUsage(input_tokens=5, output_tokens=4, total_tokens=9),
        )


class ConcurrentSemanticTransferFakeClient(SemanticTransferFakeClient):
    def __init__(self) -> None:
        super().__init__()
        self.barrier = threading.Barrier(2)
        self.lock = threading.Lock()
        self.active = 0
        self.peak_active = 0

    def create_structured(self, model, input_text, schema, schema_name):
        with self.lock:
            self.active += 1
            self.peak_active = max(self.peak_active, self.active)
        try:
            try:
                self.barrier.wait(timeout=1)
            except threading.BrokenBarrierError:
                pass
            return super().create_structured(model, input_text, schema, schema_name)
        finally:
            with self.lock:
                self.active -= 1


def _record(source: str, sha: str) -> dict:
    return {
        "cache_key": "literature-" + sha,
        "extraction": {
            "paper_id": source.replace("papers/", "paper-").replace(".pdf", ""),
            "source_file": source,
            "sha256": sha,
            "primary_tier": "tier_1",
            "secondary_tiers": [],
            "evidence_types": ["shared_reaction_manifold"],
            "reaction_summary": {},
            "evidence_items": [
                {
                    "evidence_id": "E001",
                    "claim": "The literature record supports trapping.",
                    "evidence_label": "LITERATURE FACT",
                    "quotation": "The literature record supports trapping.",
                    "source_span_ids": ["P001-S001"],
                    "pdf_page": 1,
                    "additional_pdf_pages": [],
                    "section_context": "Results",
                    "attribution": "author_observation",
                    "evidence_strength": "direct",
                    "visual_review_reference": None,
                    "reviewer_status": "pending",
                }
            ],
            "uncertainties": [],
            "contradictions": [],
            "visual_review_pages": [],
            "review_status": "pending",
        },
    }


def _write_workflow_fixture(tmp_path: Path) -> Path:
    corpus = tmp_path / "derived" / "full_corpus"
    rows = [
        ("papers/one.pdf", "a" * 64),
        ("papers/two.pdf", "b" * 64),
        ("papers/three.pdf", "c" * 64),
    ]
    (corpus / "queue.json").parent.mkdir(parents=True)
    (corpus / "queue.json").write_text(
        json.dumps(
            {
                "queue_digest": "d" * 64,
                "items": [
                    {"source_path": source, "sha256": sha, "tier": "tier_1"}
                    for source, sha in rows
                ],
            }
        ),
        encoding="utf-8",
    )
    for source, sha in rows:
        target = corpus / "papers" / sha[:12] / "validated.json"
        target.parent.mkdir(parents=True)
        target.write_text(json.dumps(_record(source, sha)), encoding="utf-8")
    config = {
        "normalization": {
            "model": "fixture-model",
            "prompt_text": "Normalize the validated literature record.",
            "prompt_version": "1.0",
            "schema_version": "1.0",
        },
        "transferability_config": "transferability.yaml",
        "candidate_scoring_config": "candidate_scoring.yaml",
    }
    config_path = tmp_path / "principle_workflow.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return config_path


def test_status_tolerates_absent_artifacts_without_constructing_a_client(tmp_path, monkeypatch):
    def client_forbidden(*args, **kwargs):
        raise AssertionError("status must not construct a model client")

    monkeypatch.setattr("pipeline.principle_workflow._default_client", client_forbidden)

    status = build_principle_status(tmp_path)

    assert status["registry"]["state"] == "absent"
    assert status["normalization"]["record_count"] == 0
    assert status["human_review"]["pending_count"] == 0


def test_status_tolerates_incomplete_artifacts(tmp_path):
    principles = tmp_path / "derived" / "principles"
    principles.mkdir(parents=True)
    (principles / "manifest.json").write_text('{"phases": {"normalize": []}}', encoding="utf-8")
    (principles / "principle_review.json").write_text('{"principles": "partial"}', encoding="utf-8")
    (principles / "frozen_candidates.json").write_text('{"candidates": "partial"}', encoding="utf-8")

    status = build_principle_status(tmp_path)

    assert status["normalization"]["record_count"] == 0
    assert status["human_review"]["pending_principle_ids"] == []
    assert status["freeze"]["digest_linked"] is False


def test_status_prefers_qualified_source_revisit_registry(tmp_path):
    principles = tmp_path / "derived/principles"
    principles.mkdir(parents=True)
    (principles / "manifest.json").write_text(
        json.dumps({"phases": {}, "source_revisits": []}), encoding="utf-8"
    )
    (principles / "source_revisit_registry.json").write_text(
        json.dumps(
            {
                "paper_count": 2,
                "revisit_count": 2,
                "revisits": [
                    {"request_id": "aaa::SR001", "status": "pending"},
                    {"request_id": "bbb::SR001", "status": "pending"},
                ],
            }
        ),
        encoding="utf-8",
    )

    status = build_principle_status(tmp_path)

    assert status["normalization"]["pending_source_revisit_count"] == 2


def test_normalization_requires_live_opt_in(tmp_path):
    config_path = _write_workflow_fixture(tmp_path)
    run_principle_workflow(config_path, tmp_path, tmp_path, "inventory")

    with pytest.raises(PrincipleWorkflowGateError, match="--live"):
        run_principle_workflow(config_path, tmp_path, tmp_path, "normalize")


def test_seed_phase_requires_live_and_writes_grounded_model(tmp_path):
    _docx(
        tmp_path / "manuscript.docx",
        ["The palladium catalyst affords selective monodefluorinative coupling."],
    )
    (tmp_path / "hidden.xlsx").write_text("hidden outcome", encoding="utf-8")
    (tmp_path / "seed_sources.yaml").write_text(
        yaml.safe_dump(
            {
                "sources": [
                    {
                        "path": "manuscript.docx",
                        "role": "manuscript",
                        "access_class": "principle_building",
                    },
                    {
                        "path": "hidden.xlsx",
                        "role": "experimental_results",
                        "access_class": "hidden_answer",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    config_path = tmp_path / "workflow.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "seed_sources_config": "seed_sources.yaml",
                "seed_modeling": {
                    "model": "fixture",
                    "prompt_text": "Extract Seed evidence and mechanism.",
                    "prompt_version": "1",
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(PrincipleWorkflowGateError, match="--live"):
        run_principle_workflow(config_path, tmp_path, tmp_path, "seed")

    result = run_principle_workflow(
        config_path,
        tmp_path,
        tmp_path,
        "seed",
        live=True,
        client=SeedFakeClient(seed_payload()),
    )

    assert result["status"] == "complete"
    assert (tmp_path / "derived/principles/seed_mechanism.json").is_file()
    assert (tmp_path / "derived/principles/seed_principle.json").is_file()
    prompt_inventory = json.loads(
        (tmp_path / "derived/principles/seed_input_inventory.json").read_text()
    )
    assert prompt_inventory["hidden_answers_revealed"] is False


def test_normalization_continues_after_failure_and_records_revisit(tmp_path):
    config_path = _write_workflow_fixture(tmp_path)
    run_principle_workflow(config_path, tmp_path, tmp_path, "inventory")
    client = FakeClient()

    result = run_principle_workflow(
        config_path, tmp_path, tmp_path, "normalize", live=True, client=client
    )

    assert result["records"]["papers/one.pdf"]["status"] == "validated"
    assert result["records"]["papers/two.pdf"]["status"] == "failed"
    assert result["records"]["papers/three.pdf"]["status"] == "validated"
    assert result["source_revisits"][0]["request_id"] == "SR-003"
    assert (tmp_path / "derived/principles/normalization" / ("a" * 12) / "validated.json").is_file()
    manifest = json.loads((tmp_path / "derived/principles/manifest.json").read_text(encoding="utf-8"))
    assert manifest["phases"]["normalize"]["records"]["papers/two.pdf"]["status"] == "failed"


def test_normalization_reuses_cached_success_on_resume(tmp_path):
    config_path = _write_workflow_fixture(tmp_path)
    run_principle_workflow(config_path, tmp_path, tmp_path, "inventory")
    first = FakeClient()
    run_principle_workflow(config_path, tmp_path, tmp_path, "normalize-smoke", live=True, client=first)
    second = FakeClient()

    result = run_principle_workflow(
        config_path, tmp_path, tmp_path, "normalize-smoke", live=True, client=second
    )

    assert result["records"]["papers/one.pdf"]["status"] == "reused"
    assert second.calls == []


def test_normalization_smoke_does_not_mark_the_full_queue_complete(tmp_path):
    config_path = _write_workflow_fixture(tmp_path)
    run_principle_workflow(config_path, tmp_path, tmp_path, "inventory")

    result = run_principle_workflow(
        config_path, tmp_path, tmp_path, "normalize-smoke", live=True, client=FakeClient()
    )

    manifest = json.loads(
        (tmp_path / "derived/principles/manifest.json").read_text(encoding="utf-8")
    )
    assert result["status"] == "complete"
    assert manifest["phases"]["normalize-smoke"]["status"] == "complete"
    assert manifest["phases"]["normalize"]["status"] == "running"
    assert len(manifest["phases"]["normalize"]["records"]) == 1


def test_normalization_records_an_empty_queue_without_constructing_a_client(tmp_path):
    config_path = _write_workflow_fixture(tmp_path)
    queue_path = tmp_path / "derived" / "full_corpus" / "queue.json"
    queue_path.write_text(json.dumps({"queue_digest": "d" * 64, "items": []}), encoding="utf-8")
    run_principle_workflow(config_path, tmp_path, tmp_path, "inventory")
    client = FakeClient()

    result = run_principle_workflow(
        config_path, tmp_path, tmp_path, "normalize", live=True, client=client
    )

    assert result["status"] == "complete"
    assert result["records"] == {}
    assert client.calls == []


def test_semantic_transfer_smoke_full_run_and_cache_resume(tmp_path):
    _write_bundle_fixture(tmp_path)
    principles = tmp_path / "derived/principles"
    (principles / "seed_mechanism.json").write_text(
        _transfer_seed().model_dump_json(), encoding="utf-8"
    )
    rubric = {
        "version": "2.0",
        "weights": {dimension: 2 for dimension in TRANSFER_DIMENSIONS},
        "critical_unknown_dimensions": list(TRANSFER_DIMENSIONS[:3]),
    }
    (tmp_path / "transferability.yaml").write_text(
        yaml.safe_dump(rubric), encoding="utf-8"
    )
    config_path = tmp_path / "workflow.yaml"
    config_path.write_text(
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

    with pytest.raises(PrincipleWorkflowGateError, match="--live"):
        run_principle_workflow(
            config_path, tmp_path, tmp_path, "transfer-smoke", live=False
        )

    first = SemanticTransferFakeClient()
    smoke = run_principle_workflow(
        config_path, tmp_path, tmp_path, "transfer-smoke", live=True, client=first
    )
    full = run_principle_workflow(
        config_path, tmp_path, tmp_path, "transfer", live=True, client=first
    )
    resumed_client = SemanticTransferFakeClient()
    resumed = run_principle_workflow(
        config_path,
        tmp_path,
        tmp_path,
        "transfer",
        live=False,
        client=resumed_client,
    )

    aggregate = json.loads(
        (principles / "transfer_assessments.json").read_text(encoding="utf-8")
    )["assessments"]
    assert smoke["assessment_count"] == 1
    assert full["assessment_count"] == 2
    assert resumed["assessment_count"] == 2
    assert first.calls == ["papers/one.pdf", "papers/two.pdf"]
    assert resumed_client.calls == []
    assert len({row["assessment_id"] for row in aggregate}) == 2
    assert {row["transfer_status"] for row in aggregate} == {"transferable"}


def test_semantic_transfer_uses_bounded_parallel_paper_workers(tmp_path):
    _write_bundle_fixture(tmp_path)
    principles = tmp_path / "derived/principles"
    (principles / "seed_mechanism.json").write_text(
        _transfer_seed().model_dump_json(), encoding="utf-8"
    )
    rubric = {
        "version": "2.0",
        "weights": {dimension: 2 for dimension in TRANSFER_DIMENSIONS},
        "critical_unknown_dimensions": list(TRANSFER_DIMENSIONS[:3]),
    }
    (tmp_path / "transferability.yaml").write_text(
        yaml.safe_dump(rubric), encoding="utf-8"
    )
    config_path = tmp_path / "workflow.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "seed_mechanism_path": "derived/principles/seed_mechanism.json",
                "transferability_config": "transferability.yaml",
                "semantic_transfer": {
                    "model": "fixture",
                    "prompt_text": "Assess semantic transfer.",
                    "prompt_version": "2.0",
                    "rubric_version": "2.0",
                    "max_workers": 2,
                },
            }
        ),
        encoding="utf-8",
    )
    client = ConcurrentSemanticTransferFakeClient()

    result = run_principle_workflow(
        config_path, tmp_path, tmp_path, "transfer", live=True, client=client
    )

    assert result["status"] == "complete"
    assert result["assessment_count"] == 2
    assert client.peak_active == 2


def test_status_exposes_pending_review_and_validate_refuses_unfrozen_artifacts(tmp_path):
    principles = tmp_path / "derived" / "principles"
    principles.mkdir(parents=True)
    (principles / "principle_review.json").write_text(
        json.dumps({"principles": [{"principle_id": "RP-001", "review_status": "pending"}]}),
        encoding="utf-8",
    )
    config_path = _write_workflow_fixture(tmp_path)

    status = build_principle_status(tmp_path)

    assert status["human_review"]["pending_principle_ids"] == ["RP-001"]
    with pytest.raises(PrincipleWorkflowGateError, match="frozen"):
        run_principle_workflow(config_path, tmp_path, tmp_path, "validate")


def test_unknown_phase_is_rejected(tmp_path):
    config_path = _write_workflow_fixture(tmp_path)

    with pytest.raises(PrincipleWorkflowError, match="unknown workflow phase"):
        run_principle_workflow(config_path, tmp_path, tmp_path, "reveal")


def test_default_live_stage_models_match_the_verified_pilot_model():
    pilot = yaml.safe_load(Path("config/pilot.yaml").read_text(encoding="utf-8"))
    workflow = yaml.safe_load(
        Path("config/principle_workflow.yaml").read_text(encoding="utf-8")
    )

    assert {
        workflow[stage]["model"]
        for stage in (
            "seed_modeling",
            "principle_modeling",
            "chemical_space_modeling",
            "normalization",
            "semantic_transfer",
        )
    } == {pilot["model"]}


def test_induce_calls_model_only_when_proposals_are_absent(tmp_path, monkeypatch):
    root = tmp_path / "derived/principles"
    root.mkdir(parents=True)
    (root / "seed_mechanism.json").write_text(
        _seed().model_dump_json(), encoding="utf-8"
    )
    (root / "transfer_assessments.json").write_text(
        json.dumps(
            {
                "semantic_transfer_version": "2.0",
                "assessments": [_transfer().model_dump(mode="json")],
            }
        ),
        encoding="utf-8",
    )
    config_path = tmp_path / "workflow.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "principle_modeling": {
                    "model": "fixture",
                    "prompt_text": "Propose Reaction Principles.",
                    "prompt_version": "1",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "pipeline.principle_workflow.audit_knowledge_transfer",
        lambda output_root: KnowledgeTransferAudit(
            paper_count=1,
            mechanism_count=1,
            assessment_count=1,
            unique_assessment_count=1,
            revisit_count=0,
            missing_paper_count=0,
            missing_mechanism_count=0,
            provenance_violation_count=0,
            status_counts={"transferable": 1},
            component_judgment_counts={"shared_elementary_step:match": 1},
        ),
    )

    with pytest.raises(PrincipleWorkflowGateError, match="--live"):
        run_principle_workflow(config_path, tmp_path, tmp_path, "induce")

    result = run_principle_workflow(
        config_path,
        tmp_path,
        tmp_path,
        "induce",
        live=True,
        client=ProposalFakeClient(
            {"principles": [_principle().model_dump(mode="json")]}
        ),
    )

    assert result["status"] == "review_required"
    assert (root / "principle_proposals.json").is_file()
    assert (tmp_path / "reports/knowledge_transfer_audit.json").is_file()


def test_induce_rejects_degenerate_audited_transfer(tmp_path, monkeypatch):
    root = tmp_path / "derived/principles"
    root.mkdir(parents=True)
    (root / "seed_mechanism.json").write_text(
        _seed().model_dump_json(), encoding="utf-8"
    )
    assessments = [
        _transfer().model_copy(update={"assessment_id": f"TA-{index:03d}"})
        for index in range(10)
    ]
    (root / "transfer_assessments.json").write_text(
        json.dumps(
            {
                "semantic_transfer_version": "2.0",
                "assessments": [item.model_dump(mode="json") for item in assessments],
            }
        ),
        encoding="utf-8",
    )
    config_path = tmp_path / "workflow.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "principle_modeling": {
                    "model": "fixture",
                    "prompt_text": "Propose Reaction Principles.",
                    "prompt_version": "1",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "pipeline.principle_workflow.audit_knowledge_transfer",
        lambda output_root: KnowledgeTransferAudit(
            paper_count=10,
            mechanism_count=10,
            assessment_count=10,
            unique_assessment_count=10,
            revisit_count=0,
            missing_paper_count=0,
            missing_mechanism_count=0,
            provenance_violation_count=0,
            status_counts={"transferable": 10},
            component_judgment_counts={"shared_elementary_step:match": 10},
        ),
    )

    with pytest.raises(PrincipleWorkflowGateError, match="degenerate"):
        run_principle_workflow(
            config_path,
            tmp_path,
            tmp_path,
            "induce",
            live=True,
            client=ProposalFakeClient(
                {"principles": [_principle().model_dump(mode="json")]}
            ),
        )


def test_rank_calls_model_for_missing_chemical_space_inputs(tmp_path):
    root = tmp_path / "derived/principles"
    root.mkdir(parents=True)
    accepted = _principle(status="accepted", review_status="accepted")
    (root / "principle_review.json").write_text(
        json.dumps({"principles": [accepted.model_dump(mode="json")]}),
        encoding="utf-8",
    )
    (root / "transfer_assessments.json").write_text(
        json.dumps({"assessments": [_transfer().model_dump(mode="json")]}),
        encoding="utf-8",
    )
    (tmp_path / "candidate_scoring.yaml").write_text(
        yaml.safe_dump(RUBRIC), encoding="utf-8"
    )
    config_path = tmp_path / "workflow.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "candidate_scoring_config": "candidate_scoring.yaml",
                "chemical_space_modeling": {
                    "model": "fixture",
                    "prompt_text": "Map chemical space.",
                    "prompt_version": "1",
                },
            }
        ),
        encoding="utf-8",
    )
    payload = {
        "families": [
            {
                "family_id": "NU-S",
                "family_type": "nucleophile",
                "compatibility_components": [
                    _component(name, 1) for name in RUBRIC["weights"]
                ],
                "risk_components": [
                    _component(name, 0) for name in RUBRIC["risk_penalties"]
                ],
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
                "minimal_diagnostic_plan": ["19F NMR"],
                "uncertainty": [],
            }
        ],
    }

    with pytest.raises(PrincipleWorkflowGateError, match="--live"):
        run_principle_workflow(config_path, tmp_path, tmp_path, "rank")

    result = run_principle_workflow(
        config_path,
        tmp_path,
        tmp_path,
        "rank",
        live=True,
        client=ProposalFakeClient(payload),
    )

    assert result["candidate_count"] == 1
    assert (root / "family_predictions.json").is_file()
    assert (root / "provisional_candidates.json").is_file()


def test_report_phase_routes_to_provisional_report_writer(tmp_path, monkeypatch):
    config_path = tmp_path / "workflow.yaml"
    config_path.write_text("{}", encoding="utf-8")
    report_root = tmp_path / "reports"
    report_root.mkdir()
    markdown_path = report_root / "reaction_principle_report.md"
    json_path = report_root / "reaction_principle_report.json"
    calls = []

    def fake_writer(output_root, *, max_assessments, max_per_paper):
        calls.append((output_root, max_assessments, max_per_paper))
        return markdown_path, json_path

    monkeypatch.setattr(
        "pipeline.principle_workflow.write_principle_report", fake_writer
    )

    result = run_principle_workflow(
        config_path, tmp_path, tmp_path, "report", live=False
    )

    assert result == {
        "status": "provisional_unreviewed",
        "markdown_path": str(markdown_path),
        "json_path": str(json_path),
    }
    assert calls == [(tmp_path.resolve(), 80, 3)]

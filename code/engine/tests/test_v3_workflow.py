from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

import pipeline.v3_workflow as workflow
from pipeline.v3_workflow import V3WorkflowError, V3WorkflowGateError, run_v3_workflow
from pipeline.validation_study import MetricAvailability, ValidationReadiness


def _config(tmp_path: Path) -> Path:
    path = tmp_path / "workflow.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "version": "3.0",
                "output_root": "derived/principles_v3",
                "exploration_brief": {
                    "version": "3.0",
                    "study_id": "test",
                    "fixed_role": {
                        "role": "electrophile",
                        "label": "fixed",
                        "seed_reaction_id": "SR001",
                    },
                    "variable_role": {"role": "nucleophile", "label": "variable"},
                    "target_transformation": {
                        "new_bond": "new bond",
                        "retained_features": ["one fluorine"],
                    },
                    "allowed_evidence_levels": ["unknown"],
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def test_discover_requires_freeze_one(tmp_path: Path) -> None:
    with pytest.raises(V3WorkflowGateError, match="Freeze 1"):
        run_v3_workflow(_config(tmp_path), tmp_path, tmp_path, "discover", live=False)


def test_evaluate_requires_freeze_two(tmp_path: Path) -> None:
    with pytest.raises(V3WorkflowGateError, match="Freeze 2"):
        run_v3_workflow(_config(tmp_path), tmp_path, tmp_path, "evaluate", live=False)


def test_reveal_requires_freeze_three(tmp_path: Path) -> None:
    with pytest.raises(V3WorkflowGateError, match="Freeze 3"):
        run_v3_workflow(_config(tmp_path), tmp_path, tmp_path, "reveal", live=False)


def test_status_does_not_read_sealed_registry(tmp_path: Path) -> None:
    config = _config(tmp_path)
    sealed = tmp_path / "config" / "sealed_validation_registry.yaml"
    sealed.parent.mkdir(parents=True)
    sealed.write_text("SH: secret", encoding="utf-8")
    result = run_v3_workflow(config, tmp_path, tmp_path, "status", live=False)
    assert result["namespace"] == "derived/principles_v3"
    assert "secret" not in json.dumps(result)


def test_prepare_source_digest_does_not_read_sealed_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)
    sealed = tmp_path / "sealed_validation_registry.yaml"
    sealed.write_text("synthetic: secret", encoding="utf-8")
    original = Path.read_bytes

    def guarded(path: Path) -> bytes:
        if path.resolve() == sealed.resolve():
            raise AssertionError("sealed plaintext was read")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", guarded)
    result = run_v3_workflow(config, tmp_path, tmp_path, "prepare", live=False)
    assert result["status"] == "complete"


def test_prepare_hashes_workspace_symlink_without_following_external_target(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    external = tmp_path.parent / f"{tmp_path.name}-external.txt"
    external.write_text("external runtime", encoding="utf-8")
    (tmp_path / "runtime-link").symlink_to(external)

    result = run_v3_workflow(config, tmp_path, tmp_path, "prepare", live=False)

    assert result["status"] == "complete"


def test_freeze_one_requires_prepare(tmp_path: Path) -> None:
    with pytest.raises(V3WorkflowGateError, match="prepare"):
        run_v3_workflow(_config(tmp_path), tmp_path, tmp_path, "freeze-1", live=False)


def test_v2_cache_path_is_rejected(tmp_path: Path) -> None:
    config = _config(tmp_path)
    config.write_text(config.read_text().replace("version: '3.0'", "version: '3.0'"), encoding="utf-8")
    payload = yaml.safe_load(config.read_text())
    payload["v2_cache_root"] = "derived/principles/coverage_audit.json"
    config.write_text(yaml.safe_dump(payload), encoding="utf-8")
    with pytest.raises(V3WorkflowError, match="v2 artifact/cache"):
        run_v3_workflow(config, tmp_path, tmp_path, "prepare", live=False)


def test_freeze_one_delegates_to_task_11(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config(tmp_path)
    run_v3_workflow(config, tmp_path, tmp_path, "prepare", live=False)
    expected = object()
    called = []
    monkeypatch.setattr(workflow, "freeze_stage_one", lambda root, inputs: called.append((root, inputs)) or {"freeze_version": "Freeze 1"})
    monkeypatch.setattr(workflow, "freeze_manifest_digest", lambda root, stage: "a" * 64)
    result = run_v3_workflow(config, tmp_path, tmp_path, "freeze-1", client={"freeze-1": {"inputs": expected}})
    assert called == [(tmp_path.resolve(), expected)]
    assert result["freeze_digest"] == "a" * 64


def test_required_freeze_three_uses_chain_verifier(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config(tmp_path)
    manifest = tmp_path / "derived/principles_v3/freezes/freeze_3_manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(workflow, "freeze_manifest_digest", lambda root, stage: "c" * 64)
    verified = type("Verified", (), {"valid": True, "verified_stages": ("Freeze 1", "Freeze 2", "Freeze 3"), "manifest_digests": {"Freeze 3": "c" * 64}})()
    calls = []
    monkeypatch.setattr(workflow, "verify_freeze_chain", lambda root, digest, policy: calls.append((digest, policy)) or verified)
    monkeypatch.setattr(workflow, "evaluate_retrospective_reveal", lambda **kwargs: type("Reveal", (), {"model_dump": lambda self, mode: {"fixed_scope": "SR001_nucleophile_condition"}})())
    policy = object()
    payload = {"leakage_policy": policy, "registry_path": tmp_path / "sealed.yaml", "taxonomy": object(), "ranking": object(), "diagnostics": (), "registry_salt": b"salt", "reveal_decision": "reveal", "expected_structure_factory": object()}
    run_v3_workflow(config, tmp_path, tmp_path, "reveal", client={"reveal": payload})
    assert calls == [("c" * 64, policy)]


def test_validate_delegates_to_task_12_readiness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config(tmp_path)
    monkeypatch.setattr(workflow, "_required_freeze", lambda *args: "d" * 64)
    readiness = type("Readiness", (), {"model_dump": lambda self, mode: {"fixed_scope": "SR001_nucleophile_condition", "electrophile_expansion_blocked": True}})()
    calls = []
    monkeypatch.setattr(workflow, "build_validation_readiness", lambda root, **kwargs: calls.append((root, kwargs)) or readiness)
    policy = object()
    result = run_v3_workflow(config, tmp_path, tmp_path, "validate", client={"validate": {"leakage_policy": policy, "historical_negatives": ()}})
    assert calls and calls[0][1]["trusted_freeze_three_digest"] == "d" * 64
    assert Path(result["artifact"]).name == "validation_readiness.json"


def test_source_mutation_invalidates_cached_phase(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config(tmp_path)
    source = tmp_path / "source.txt"
    source.write_text("one", encoding="utf-8")
    monkeypatch.setattr(workflow, "_required_freeze", lambda *args: "e" * 64)
    calls = []
    operation = lambda: calls.append(1) or {"result": len(calls)}
    provider = {"discover": {"operation": operation}}
    run_v3_workflow(config, tmp_path, tmp_path, "discover", live=True, client=provider)
    run_v3_workflow(config, tmp_path, tmp_path, "discover", live=False, client=provider)
    source.write_text("two", encoding="utf-8")
    run_v3_workflow(config, tmp_path, tmp_path, "discover", live=True, client=provider)
    assert len(calls) == 2


def test_electrophile_expand_consumes_real_fixed_scope_review(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config(tmp_path)
    namespace = tmp_path / "derived/principles_v3"
    namespace.mkdir(parents=True)
    readiness = ValidationReadiness(
        historical_negative_status="missing",
        historical_negative_record_count=0,
        failure_discrimination_metrics=MetricAvailability(status="unavailable", value=None, reason="missing"),
        prospective_boundary_matrix_required=True,
        prospective_boundary_matrix=(),
        negative_record_reminder="register negatives",
    )
    readiness_path = namespace / "validation_readiness.json"
    readiness_path.write_text(json.dumps(readiness.model_dump(mode="json")), encoding="utf-8")
    digest = workflow._file_digest(readiness_path)
    (namespace / "validation_readiness_review.json").write_text(
        json.dumps({"decision": "accepted", "readiness_digest": digest, "fixed_scope": readiness.fixed_scope}),
        encoding="utf-8",
    )
    monkeypatch.setattr(workflow, "_required_freeze", lambda *args: "f" * 64)
    calls = []
    result = run_v3_workflow(
        config,
        tmp_path,
        tmp_path,
        "electrophile-expand",
        live=False,
        client={"electrophile-expand": {"operation": lambda: calls.append(1) or {"expanded": True}}},
    )
    assert calls == [1]
    assert result["status"] == "complete"
    assert workflow._file_digest(readiness_path) == digest

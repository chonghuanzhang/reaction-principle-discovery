from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
import hashlib

from pipeline.full_space_run import (
    FullSpaceFreezeReadiness,
    FullSpaceRunError,
    FullSpaceRunGateError,
    assert_full_space_freeze_ready,
    run_full_space_phase,
)


def _config(tmp_path: Path) -> Path:
    path = tmp_path / "workflow_v3_6.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "version": "3.6",
                "output_root": "derived/principles_v3",
                "exploration_brief": {
                    "version": "3.0",
                    "study_id": "fixed-sr001-open-reaction-partner-exploration-v3-6",
                    "fixed_role": {
                        "role": "electrophile",
                        "label": "SR001 fixed Seed component",
                        "seed_reaction_id": "SR001",
                    },
                    "variable_role": {
                        "role": "nucleophile",
                        "label": "reaction-partner family, representative reagent, and conditions",
                    },
                    "target_transformation": {
                        "new_bond": "new bond to the variable reaction partner",
                        "retained_features": ["selective retention of one fluorine"],
                    },
                    "allowed_evidence_levels": [
                        "traceable_external_evidence",
                        "model_physical_organic_inference",
                        "unknown",
                    ],
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def _prepared_frozen_run(tmp_path: Path) -> Path:
    run_root = tmp_path / "reaction_principle_v3_6"
    namespace = run_root / "derived" / "principles_v3"
    namespace.mkdir(parents=True)
    freeze_manifest = {
        "freeze_version": "Freeze 3",
        "created_at": "2026-08-28T00:00:00Z",
        "brief_digest": "a" * 64,
        "artifact_digests": {"placeholder": "b" * 64},
        "hidden_registry_commitment": "c" * 64,
        "software_version": "test",
    }
    for name in ("freeze_1_manifest.json", "freeze_2_manifest.json", "freeze_3_manifest.json"):
        (namespace / "freezes").mkdir(parents=True, exist_ok=True)
        (namespace / "freezes" / name).write_text(
            json.dumps(freeze_manifest), encoding="utf-8"
        )
    (namespace / "frozen_principles.json").write_text('{"kept": true}', encoding="utf-8")
    (namespace / "freeze_manifest_v3.json").write_text('{"freeze_version":"Freeze 3"}', encoding="utf-8")
    (namespace / "taxonomy.json").write_text('{"taxonomy": true}', encoding="utf-8")
    (namespace / "ranking.json").write_text('{"ranking": true}', encoding="utf-8")
    (namespace / "diagnostics.json").write_text('{"diagnostics": true}', encoding="utf-8")
    return run_root


def _synthetic_payload() -> dict[str, object]:
    return {
        "leakage_policy": object(),
        "registry_path": Path("sealed.yaml"),
        "taxonomy": object(),
        "ranking": object(),
        "diagnostics": (),
        "registry_salt": b"salt",
        "reveal_decision": "reveal",
        "expected_structure_factory": object(),
    }


def _frozen_artifact_digests(run_root: Path) -> dict[str, str]:
    namespace = run_root / "derived" / "principles_v3"
    return {
        path.relative_to(namespace).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(namespace.rglob("*"))
        if path.is_file() and not path.relative_to(namespace).parts[0] == "post_reveal"
    }


def test_retrieve_hypotheses_requires_discovery(tmp_path: Path) -> None:
    with pytest.raises(FullSpaceRunGateError, match="discover"):
        run_full_space_phase(
            _config(tmp_path),
            tmp_path,
            tmp_path / "reaction_principle_v3_6",
            "retrieve-hypotheses",
        )


def test_reveal_requires_freeze_three_and_preserves_frozen_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_root = _prepared_frozen_run(tmp_path)
    before = _frozen_artifact_digests(run_root)
    monkeypatch.setattr(
        "pipeline.full_space_run.evaluate_retrospective_reveal",
        lambda **kwargs: {"revealed": True},
    )
    run_full_space_phase(
        _config(tmp_path),
        tmp_path,
        run_root,
        "reveal",
        reveal_payload=_synthetic_payload(),
    )
    after = _frozen_artifact_digests(run_root)
    assert after == before


def test_freeze_readiness_rejects_unready_state() -> None:
    readiness = FullSpaceFreezeReadiness(
        answer_isolation_clean=True,
        center_coverage_complete=True,
        operationally_saturated=False,
        named_family_requirements_absent=True,
        unknown_preserved=True,
        decision_critical_evidence_qualified=True,
        tier_roles_independent=True,
        blockers=("saturation incomplete",),
    )
    with pytest.raises(FullSpaceRunGateError, match="Freeze 2 readiness"):
        assert_full_space_freeze_ready(readiness)

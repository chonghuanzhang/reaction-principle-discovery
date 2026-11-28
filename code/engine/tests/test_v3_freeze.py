from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

import pipeline.v3_freeze as freeze_module
from pipeline.diagnostic_design import design_family_diagnostics
from pipeline.family_canonicalization import (
    CanonicalFamily,
    CanonicalTaxonomy,
    ProposalProvenance,
)
from pipeline.family_evaluation import (
    EvidenceQualificationContext,
    load_evaluation_rubric,
    restore_evidence_qualification_context,
    score_family,
)
from pipeline.leakage_audit import LeakagePolicy
from pipeline.principle_models import FrozenReactionPrincipleSet, ReactionPrinciple
from pipeline.ranking_robustness import analyze_ranking
from pipeline.saturation import audit_mechanism_coverage, evaluate_saturation
from pipeline.taxonomy_discovery import (
    MechanisticProposalDefinition,
    TaxonomyLaneResult,
    TaxonomyProposal,
)
from pipeline.v3_freeze import (
    FreezeEnvironmentV3,
    FreezeOneInputs,
    FreezeThreeDiagnosticInputs,
    FreezeThreeRankingInputs,
    FreezeTwoTaxonomyInputs,
    ModelArtifactExecutionV3,
    ModelExecutionMetadataV3,
    V3FreezeError,
    bind_evaluation_context_to_freeze_chain,
    freeze_manifest_digest,
    freeze_stage_one,
    freeze_stage_three,
    freeze_stage_two,
    verify_freeze_chain,
)
from tests.test_diagnostic_design import (
    _STRUCTURE_FACTORY,
    _family,
    _inventories_for_family,
)
from tests.test_family_evaluation import (
    _all_supporting_judgments,
    _build_from_environment,
    _context_with_record_update,
    _score,
    _write_environment,
)
from tests.test_v3_evidence_import import _brief, _clean_v2_fixture, _policy
import tests.test_diagnostic_design as diagnostic_test_module


_TRUSTED_CONTEXT: EvidenceQualificationContext | None = None
_TRUSTED_PRINCIPLES: tuple[ReactionPrinciple, ...] = ()
_TRUSTED_FAMILY_EVIDENCE_ID = ""
_TRUSTED_CONTEXT_ROOT: Path | None = None


@pytest.fixture(scope="module", autouse=True)
def _trusted_scored_base(tmp_path_factory: pytest.TempPathFactory):
    global _TRUSTED_CONTEXT, _TRUSTED_PRINCIPLES, _TRUSTED_FAMILY_EVIDENCE_ID
    global _TRUSTED_CONTEXT_ROOT
    root = tmp_path_factory.mktemp("freeze-trust")
    registry, frozen_path, manifest_path = _write_environment(root)
    queue_path = root / "derived/full_corpus/queue.json"
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    queue_path.write_text(
        json.dumps(
            {
                "queue_digest": registry.queue_digest,
                "items": [
                    {
                        "source_path": record.source_path,
                        "sha256": record.sha256,
                        "tier": record.tier,
                    }
                    for record in registry.records
                ],
            }
        ),
        encoding="utf-8",
    )
    registry_path = root / "derived/principles/evidence_registry.json"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(
        json.dumps(registry.model_dump(mode="json")), encoding="utf-8"
    )
    freeze_module.import_reusable_evidence(root, _brief(), _policy(root))
    import_manifest_path = (
        root / "derived/principles_v3/evidence_import_manifest.json"
    )
    synthetic_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    synthetic_manifest["artifact_digests"][
        "evidence_import_manifest"
    ] = hashlib.sha256(import_manifest_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(synthetic_manifest), encoding="utf-8")
    context = _build_from_environment(root, registry, frozen_path, manifest_path)
    frozen = FrozenReactionPrincipleSet.model_validate_json(frozen_path.read_bytes())
    _TRUSTED_CONTEXT = context
    _TRUSTED_CONTEXT_ROOT = root
    _TRUSTED_PRINCIPLES = frozen.principles
    _TRUSTED_FAMILY_EVIDENCE_ID = _all_supporting_judgments()[0].evidence_ids[0]
    diagnostic_test_module._TRUSTED_BASE = _score(
        _all_supporting_judgments(), context
    )
    yield
    _TRUSTED_CONTEXT = None
    _TRUSTED_CONTEXT_ROOT = None
    _TRUSTED_PRINCIPLES = ()
    _TRUSTED_FAMILY_EVIDENCE_ID = ""
    diagnostic_test_module._TRUSTED_BASE = None


def _freeze_one_inputs(root: Path) -> FreezeOneInputs:
    _clean_v2_fixture(root)
    assert _TRUSTED_CONTEXT is not None and _TRUSTED_CONTEXT_ROOT is not None
    paths = {
        item.path
        for item in _TRUSTED_CONTEXT.frozen_dependencies
        if not item.path.startswith("registry://")
        and item.artifact_key
        not in {"freeze_manifest_v3", "evidence_import_manifest"}
    }.union(
        {
            "derived/principles/evidence_registry.json",
            "derived/full_corpus/queue.json",
        }
    )
    for relative in paths:
        source = _TRUSTED_CONTEXT_ROOT / relative
        if source.is_file():
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    return FreezeOneInputs(
        brief=_brief(),
        leakage_policy=_policy(root),
        hidden_registry_commitment="a" * 64,
        software_version="test-version",
        created_at="2026-08-18T00:00:00Z",
    )


def test_freeze_one_passes_clean_source_prefix_to_importer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _freeze_one_inputs(tmp_path).model_copy(
        update={"evidence_source_prefix": Path("derived/principles_v3/clean_inputs/v1")}
    )
    captured = []

    def stop_after_capture(*args, **kwargs):
        captured.append(kwargs.get("source_prefix"))
        raise freeze_module.EvidenceImportError("stop")

    monkeypatch.setattr(freeze_module, "import_reusable_evidence", stop_after_capture)

    with pytest.raises(V3FreezeError, match="clean evidence import"):
        freeze_stage_one(tmp_path, inputs)
    assert captured == [inputs.evidence_source_prefix]


def test_freeze_context_resolves_registry_inside_clean_source_prefix() -> None:
    marker = object()

    resolved = freeze_module._registry_source_snapshot(
        {
            "derived/principles_v3/clean_inputs/v1/derived/principles/evidence_registry.json": marker
        }
    )

    assert resolved is marker


def test_freeze_one_does_not_read_rejected_v2_artifact_content(tmp_path: Path) -> None:
    inputs = _freeze_one_inputs(tmp_path)
    rejected = tmp_path / "derived/principles/provisional_candidates.json"
    rejected.write_text('{"candidate":"SEALED_REJECTED_TERM"}', encoding="utf-8")
    inputs = inputs.model_copy(
        update={
            "leakage_policy": inputs.leakage_policy.model_copy(
                update={"sealed_terms": ("SEALED_REJECTED_TERM",)}
            )
        }
    )

    manifest = freeze_stage_one(tmp_path, inputs)

    assert manifest.freeze_version == "Freeze 1"


def _proposal(
    family: CanonicalFamily, proposal_id: str, lane_id: str, round_id: int
) -> TaxonomyProposal:
    definition = family.mechanistic_definition_candidates[0]
    return TaxonomyProposal(
        proposal_id=proposal_id,
        mechanistic_definition=definition,
        source_channel="seed_derived",
        evidence_level="traceable_external_evidence",
        evidence_ids=family.evidence_ids,
        parent_hypothesis=f"source-{proposal_id}",
        representative_reactive_state=family.representative_reactive_state_candidates[0],
        counterarguments=(),
        unknowns=(),
        suggested_search_terms=("synthetic mechanism query",),
    )


def _lane(
    family: CanonicalFamily, lane_id: str, proposal_id: str, round_id: int
) -> TaxonomyLaneResult:
    return TaxonomyLaneResult(
        status="validated",
        cache_key=hashlib.sha256(f"{lane_id}:{round_id}".encode()).hexdigest(),
        lane_id=lane_id,
        round_id=round_id,
        channel="seed_derived",
        proposals=(_proposal(family, proposal_id, lane_id, round_id),),
        usage={"input_tokens": None, "output_tokens": None, "total_tokens": None},
    )


def _taxonomy_round(round_id: int) -> tuple[CanonicalTaxonomy, tuple[TaxonomyLaneResult, ...]]:
    base = _family(family_evidence_ids=(_TRUSTED_FAMILY_EVIDENCE_ID,))
    proposal_ids = ("PROP-SYNTHETIC-A", "PROP-SYNTHETIC-B")
    lanes = tuple(
        _lane(base, lane_id, proposal_id, round_id)
        for lane_id, proposal_id in zip(
            ("LANE-SYNTHETIC-A", "LANE-SYNTHETIC-B"), proposal_ids, strict=True
        )
    )
    provenance = tuple(
        ProposalProvenance(
            proposal_id=proposal_id,
            lane_id=lane.lane_id,
            channel=lane.channel,
            round_id=round_id,
            evidence_level=lane.proposals[0].evidence_level,
            evidence_ids=lane.proposals[0].evidence_ids,
        )
        for lane, proposal_id in zip(lanes, proposal_ids, strict=True)
    )
    family = CanonicalFamily.model_validate(
        {
            **base.model_dump(mode="python"),
            "proposal_ids": proposal_ids,
            "proposal_provenance": provenance,
            "aliases": tuple(item.proposals[0].parent_hypothesis for item in lanes),
        }
    )
    return (
        CanonicalTaxonomy(
            families=(family,), decisions=(), unresolved_proposal_ids=()
        ),
        lanes,
    )


def _write_lane_artifact(root: Path, lane: TaxonomyLaneResult) -> None:
    path = (
        root
        / "derived"
        / "principles_v3"
        / "taxonomy"
        / f"round-{lane.round_id}"
        / lane.lane_id
        / lane.channel
        / "validated.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(lane.model_dump(mode="json", exclude={"status"})),
        encoding="utf-8",
    )
    (path.parent / "raw.json").write_text(
        json.dumps(
            {
                "cache_key": lane.cache_key,
                "lane_id": lane.lane_id,
                "round_id": lane.round_id,
                "channel": lane.channel,
                "api": {
                    "response_id": "MODEL-EXEC-1",
                    "returned_model": "structured-test",
                    "status": "completed",
                    "usage": lane.usage,
                },
                "model_output": {
                    "proposals": [
                        item.model_dump(mode="json") for item in lane.proposals
                    ]
                },
            }
        ),
        encoding="utf-8",
    )


def _saturation_config(family: CanonicalFamily) -> dict[str, object]:
    return {
        "coordinate_vocabulary": {
            "nucleophilic_center": [family.nucleophilic_center],
            "reactive_state": [family.reactive_state],
            "bond_forming_mode": [family.bond_forming_mode],
            "activation_mode": [family.activation_mode],
            "attack_topology": ["synthetic topology"],
            "target_termination": ["synthetic termination"],
        },
        "relevant_coordinate_cells": [
            {
                "coordinate_id": "cell-synthetic",
                "nucleophilic_center": family.nucleophilic_center,
                "reactive_state": family.reactive_state,
                "bond_forming_mode": family.bond_forming_mode,
                "activation_mode": family.activation_mode,
                "attack_topology": "synthetic topology",
                "target_termination": "synthetic termination",
                "disposition": "covered",
                "rationale": "The canonical family covers this synthetic cell.",
            }
        ],
        "saturation": {
            "maximum_new_family_rate": 0.05,
            "maximum_material_taxonomy_change_rate": 0.0,
            "required_consecutive_low_novelty_rounds": 2,
            "minimum_independent_lanes": 2,
        },
    }


def _freeze_two_inputs(root: Path) -> tuple[FreezeTwoTaxonomyInputs, object, CanonicalFamily]:
    rounds_with_lanes = tuple(_taxonomy_round(round_id) for round_id in (1, 2, 3))
    rounds = tuple(item[0] for item in rounds_with_lanes)
    taxonomy = rounds[-1]
    family = taxonomy.families[0]
    for _, lanes in rounds_with_lanes:
        for lane in lanes:
            _write_lane_artifact(root, lane)
    config = _saturation_config(family)
    coverage = audit_mechanism_coverage(taxonomy, config)
    saturation = evaluate_saturation(rounds, coverage, config)
    inputs = FreezeTwoTaxonomyInputs(
        taxonomy=taxonomy,
        source_results=rounds_with_lanes[-1][1],
        round_source_results=tuple(item[1] for item in rounds_with_lanes),
        taxonomy_rounds=rounds,
        coverage=coverage,
        saturation_config=config,
        scoring_policy=load_evaluation_rubric(),
        trusted_freeze_one_digest=freeze_manifest_digest(root, "Freeze 1"),
        created_at="2026-08-18T00:01:00Z",
    )
    return inputs, saturation, family


def _environment() -> FreezeEnvironmentV3:
    lanes = tuple(
        lane
        for round_id in (1, 2, 3)
        for lane in _taxonomy_round(round_id)[1]
    )
    return FreezeEnvironmentV3(
        software_version="test-version",
        python_version="3.12.4",
        dependency_lock_digest="b" * 64,
        execution_id="EXEC-FREEZE-3",
        started_at="2026-08-18T00:02:00Z",
        completed_at="2026-08-18T00:03:00Z",
        model_executions=(
            ModelExecutionMetadataV3(
                provider="test-provider",
                model="structured-test",
                model_version="2026-08-01",
                configuration_digest="c" * 64,
                parameters={"temperature": 0, "seed": 17},
                execution_id="MODEL-EXECUTION-1",
                started_at="2026-08-18T00:02:10Z",
                completed_at="2026-08-18T00:02:20Z",
                artifacts=tuple(
                    ModelArtifactExecutionV3(
                        response_id="MODEL-EXEC-1",
                        cache_key=lane.cache_key,
                        output_digest=freeze_module._stable_digest(
                            {
                                "proposals": [
                                    item.model_dump(mode="json")
                                    for item in lane.proposals
                                ]
                            }
                        ),
                        status="completed",
                        usage_digest=freeze_module._stable_digest(lane.usage),
                    )
                    for lane in lanes
                ),
            ),
        ),
    )


def _freeze_three_inputs(
    root: Path,
    family: CanonicalFamily,
    *,
    policy: LeakagePolicy | None = None,
    rubric=None,
) -> tuple[FreezeThreeRankingInputs, tuple[object, ...]]:
    assert _TRUSTED_CONTEXT is not None
    trusted_digest = freeze_manifest_digest(root, "Freeze 2")
    bound_context = bind_evaluation_context_to_freeze_chain(
        root, _TRUSTED_CONTEXT, trusted_digest
    )
    active_rubric = rubric or load_evaluation_rubric()
    evaluation = score_family(
        _all_supporting_judgments(),
        (),
        active_rubric,
        bound_context,
        family_id=family.family_id,
    )
    ranking = analyze_ranking((evaluation,), active_rubric, seed=17)
    diagnostic_evidence = bound_context.records
    inventory_records = _inventories_for_family(family)
    plans = design_family_diagnostics(
        (family,),
        (evaluation,),
        _TRUSTED_PRINCIPLES,
        diagnostic_evidence,
        ranking,
        inventory_records=inventory_records,
        rubric=active_rubric,
    )
    inputs = FreezeThreeRankingInputs(
        evaluations=(evaluation,),
        ranking=ranking,
        rubric=active_rubric,
        evaluation_context=bound_context,
        diagnostic_inputs=FreezeThreeDiagnosticInputs(
            families=(family,),
            principles=_TRUSTED_PRINCIPLES,
            evidence=diagnostic_evidence,
            inventory_records=inventory_records,
        ),
        environment=_environment(),
        leakage_policy=policy
        or LeakagePolicy(
            policy_id="final-clean",
            structure_fingerprint_factory=_STRUCTURE_FACTORY,
        ),
        trusted_freeze_two_digest=trusted_digest,
        created_at="2026-08-18T00:04:00Z",
    )
    return inputs, plans


def _write_freeze_one_and_two(root: Path) -> CanonicalFamily:
    freeze_stage_one(root, _freeze_one_inputs(root))
    taxonomy_inputs, saturation, family = _freeze_two_inputs(root)
    freeze_stage_two(root, taxonomy_inputs, saturation)
    return family


def _write_full_chain(root: Path) -> tuple[str, LeakagePolicy]:
    family = _write_freeze_one_and_two(root)
    ranking_inputs, plans = _freeze_three_inputs(root, family)
    freeze_stage_three(root, ranking_inputs, plans)
    return freeze_manifest_digest(root, "Freeze 3"), ranking_inputs.leakage_policy


def _replace_freeze_three_role(
    root: Path, role: str, payload: object, policy: LeakagePolicy
) -> str:
    manifest_path = freeze_module.freeze_manifest_path(root, "Freeze 3")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    role_key = next(
        key for key in manifest["artifact_digests"] if key.startswith(f"{role}:")
    )
    old_relative = role_key.partition(":")[2]
    encoded = freeze_module._stable_json_bytes(payload)
    digest = hashlib.sha256(encoded).hexdigest()
    replacement = (
        root
        / "derived/principles_v3/freezes/objects"
        / f"{role}-{digest}.json"
    )
    replacement.write_bytes(encoded)
    new_relative = replacement.relative_to(root).as_posix()
    del manifest["artifact_digests"][role_key]
    manifest["artifact_digests"][f"{role}:{new_relative}"] = digest

    substitutions = {old_relative: new_relative}
    if role not in {"critical_audit", "final_leakage_audit"}:
        critical_key = next(
            key
            for key in manifest["artifact_digests"]
            if key.startswith("critical_audit:")
        )
        critical_path = root / critical_key.partition(":")[2]
        critical = json.loads(critical_path.read_text())
        critical["dependency_digests"].pop(old_relative)
        critical["dependency_digests"][new_relative] = digest
        critical_encoded = freeze_module._stable_json_bytes(critical)
        critical_digest = hashlib.sha256(critical_encoded).hexdigest()
        critical_replacement = (
            root
            / "derived/principles_v3/freezes/objects"
            / f"critical-audit-{critical_digest}.json"
        )
        critical_replacement.write_bytes(critical_encoded)
        old_critical_relative = critical_key.partition(":")[2]
        new_critical_relative = critical_replacement.relative_to(root).as_posix()
        del manifest["artifact_digests"][critical_key]
        manifest[
            "artifact_digests"
        ][f"critical_audit:{new_critical_relative}"] = critical_digest
        substitutions[old_critical_relative] = new_critical_relative

    audit_key = next(
        key
        for key in manifest["artifact_digests"]
        if key.startswith("final_leakage_audit:")
    )
    audit_path = root / audit_key.partition(":")[2]
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    dependencies = tuple(
        root / substitutions.get(relative, relative)
        for relative in audit["dependency_digests"]
    )
    replacement_audit, _ = freeze_module._run_current_audit(root, dependencies, policy)
    audit_encoded = freeze_module._stable_json_bytes(
        replacement_audit.model_dump(mode="json")
    )
    audit_digest = hashlib.sha256(audit_encoded).hexdigest()
    audit_replacement = (
        root
        / "derived/principles_v3/freezes/objects"
        / f"freeze3-leakage-{audit_digest}.json"
    )
    audit_replacement.write_bytes(audit_encoded)
    del manifest["artifact_digests"][audit_key]
    audit_relative = audit_replacement.relative_to(root).as_posix()
    manifest["artifact_digests"][
        f"final_leakage_audit:{audit_relative}"
    ] = audit_digest
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return freeze_manifest_digest(root, "Freeze 3")


def test_public_positional_typed_apis_succeed(tmp_path):
    trusted_digest, policy = _write_full_chain(tmp_path)

    verification = verify_freeze_chain(tmp_path, trusted_digest, policy)

    assert verification.valid is True
    assert verification.verified_stages == ("Freeze 1", "Freeze 2", "Freeze 3")


def test_external_freeze_three_digest_is_required_and_rejects_replacement(tmp_path):
    trusted_digest, policy = _write_full_chain(tmp_path)
    manifest = freeze_module.freeze_manifest_path(tmp_path, "Freeze 3")
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["created_at"] = "2026-08-18T00:05:00Z"
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    verification = verify_freeze_chain(tmp_path, trusted_digest, policy)

    assert verification.valid is False
    assert "trusted Freeze 3 digest" in verification.errors[0]


def test_snapshot_read_rejects_intermediate_directory_substitution(
    tmp_path, monkeypatch
):
    directory = tmp_path / "trusted"
    directory.mkdir()
    (directory / "artifact.json").write_text('{"trusted": true}')
    attacker = tmp_path / "attacker"
    attacker.mkdir()
    (attacker / "artifact.json").write_text('{"trusted": false}')
    original_open = os.open
    substituted = False

    def swap_then_open(path, flags, *args, **kwargs):
        nonlocal substituted
        if not substituted and (
            path == "trusted" or str(path).endswith("trusted/artifact.json")
        ):
            directory.rename(tmp_path / "trusted-original")
            directory.symlink_to(attacker, target_is_directory=True)
            substituted = True
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", swap_then_open)

    with pytest.raises(V3FreezeError, match="substitution"):
        freeze_module._read_snapshot(tmp_path, directory / "artifact.json")


def test_leakage_audit_scans_snapshot_bytes_not_reopened_paths(tmp_path, monkeypatch):
    path = tmp_path / "artifact.json"
    path.write_text('{"value": "clean"}')
    policy = LeakagePolicy(policy_id="snapshot", sealed_terms=("sealed",))
    original = freeze_module.audit_paths

    def replace_before_reopen(paths, active_policy):
        path.write_text('{"value": "sealed"}')
        return original(paths, active_policy)

    monkeypatch.setattr(freeze_module, "audit_paths", replace_before_reopen)

    snapshot, _ = freeze_module._run_current_audit(tmp_path, (path,), policy)

    assert snapshot.hit_count == 0


def test_verifier_rejects_incomplete_final_audit_dependency_closure(tmp_path):
    _, policy = _write_full_chain(tmp_path)
    manifest_path = freeze_module.freeze_manifest_path(tmp_path, "Freeze 3")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    environment_key = next(
        key for key in manifest["artifact_digests"] if key.startswith("environment:")
    )
    environment_path = environment_key.partition(":")[2]
    audit_key = next(
        key
        for key in manifest["artifact_digests"]
        if key.startswith("final_leakage_audit:")
    )
    audit_path = tmp_path / audit_key.partition(":")[2]
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    dependencies = tuple(
        tmp_path / relative
        for relative in audit["dependency_digests"]
        if relative != environment_path
    )
    replacement_audit, _ = freeze_module._run_current_audit(
        tmp_path, dependencies, policy
    )
    encoded = freeze_module._stable_json_bytes(
        replacement_audit.model_dump(mode="json")
    )
    digest = hashlib.sha256(encoded).hexdigest()
    replacement = (
        tmp_path
        / "derived/principles_v3/freezes/objects"
        / f"freeze3-leakage-{digest}.json"
    )
    replacement.write_bytes(encoded)
    del manifest["artifact_digests"][audit_key]
    relative = replacement.relative_to(tmp_path).as_posix()
    manifest["artifact_digests"][f"final_leakage_audit:{relative}"] = digest
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    replacement_anchor = freeze_manifest_digest(tmp_path, "Freeze 3")

    verification = verify_freeze_chain(tmp_path, replacement_anchor, policy)

    assert verification.valid is False
    assert "final leakage audit dependency closure" in verification.errors[0]


@pytest.mark.parametrize("role", ("evaluations", "ranking", "diagnostics"))
def test_verifier_rejects_invalid_freeze_three_internal_digest(tmp_path, role):
    _, policy = _write_full_chain(tmp_path)
    manifest_path = freeze_module.freeze_manifest_path(tmp_path, "Freeze 3")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    role_key = next(
        key for key in manifest["artifact_digests"] if key.startswith(f"{role}:")
    )
    payload = json.loads((tmp_path / role_key.partition(":")[2]).read_text())
    if role == "evaluations":
        payload[0]["scored_content_digest"] = "f" * 64
    elif role == "ranking":
        payload["content_digest"] = "f" * 64
    else:
        payload[0]["content_digest"] = "f" * 64
    replacement_anchor = _replace_freeze_three_role(
        tmp_path, role, payload, policy
    )

    verification = verify_freeze_chain(tmp_path, replacement_anchor, policy)

    assert verification.valid is False
    assert "persisted Freeze 3" in verification.errors[0]


def test_verifier_recomputes_scored_evaluation_not_only_internal_digest(tmp_path):
    _, policy = _write_full_chain(tmp_path)
    manifest = json.loads(
        freeze_module.freeze_manifest_path(tmp_path, "Freeze 3").read_text()
    )
    key = next(
        item for item in manifest["artifact_digests"] if item.startswith("evaluations:")
    )
    payload = json.loads((tmp_path / key.partition(":")[2]).read_text())
    payload[0]["compatibility_index"] = 0.5
    payload[0]["scored_content_digest"] = freeze_module._stable_digest(
        {
            key: value
            for key, value in payload[0].items()
            if key != "scored_content_digest"
        }
    )
    anchor = _replace_freeze_three_role(tmp_path, "evaluations", payload, policy)

    verification = verify_freeze_chain(tmp_path, anchor, policy)

    assert verification.valid is False
    assert "recomputed" in verification.errors[0]


def test_verifier_recomputes_diagnostic_plan_not_only_internal_digests(tmp_path):
    _, policy = _write_full_chain(tmp_path)
    manifest = json.loads(
        freeze_module.freeze_manifest_path(tmp_path, "Freeze 3").read_text()
    )
    key = next(
        item for item in manifest["artifact_digests"] if item.startswith("diagnostics:")
    )
    payload = json.loads((tmp_path / key.partition(":")[2]).read_text())
    payload[0]["representatives"][0]["mechanistic_representativeness"] = (
        "Coordinated forged rationale."
    )
    plan_material = {
        key: value
        for key, value in payload[0].items()
        if key
        not in {
            "plan_digest",
            "content_digest",
            "diagnostic_records",
            "optimization_plans",
            "operational_actions",
        }
    }
    payload[0]["plan_digest"] = freeze_module._stable_digest(plan_material)
    payload[0]["content_digest"] = freeze_module._stable_digest(
        {key: value for key, value in payload[0].items() if key != "content_digest"}
    )
    anchor = _replace_freeze_three_role(tmp_path, "diagnostics", payload, policy)

    verification = verify_freeze_chain(tmp_path, anchor, policy)

    assert verification.valid is False
    assert "recomputed Task 10" in verification.errors[0]


def test_freeze_two_authenticates_every_saturation_round_lane(tmp_path):
    freeze_stage_one(tmp_path, _freeze_one_inputs(tmp_path))
    inputs, saturation, _ = _freeze_two_inputs(tmp_path)
    path = (
        tmp_path
        / "derived/principles_v3/taxonomy/round-1"
        / "LANE-SYNTHETIC-A/seed_derived/validated.json"
    )
    payload = json.loads(path.read_text())
    payload["cache_key"] = "f" * 64
    path.write_text(json.dumps(payload))

    with pytest.raises(V3FreezeError, match="saturation history"):
        freeze_stage_two(tmp_path, inputs, saturation)


def test_freeze_three_persists_critical_audit_closure(tmp_path):
    _write_full_chain(tmp_path)
    manifest = json.loads(
        freeze_module.freeze_manifest_path(tmp_path, "Freeze 3").read_text()
    )

    assert any(
        key.startswith("critical_audit:") for key in manifest["artifact_digests"]
    )


def test_verifier_rejects_diagnostic_ranking_basis_mismatch(tmp_path):
    _, policy = _write_full_chain(tmp_path)
    manifest = json.loads(
        freeze_module.freeze_manifest_path(tmp_path, "Freeze 3").read_text()
    )
    key = next(
        item for item in manifest["artifact_digests"] if item.startswith("diagnostics:")
    )
    payload = json.loads((tmp_path / key.partition(":")[2]).read_text())
    payload[0]["ranking_basis"]["evaluation_digest"] = "f" * 64
    plan_material = {
        key: value
        for key, value in payload[0].items()
        if key
        not in {
            "plan_digest",
            "content_digest",
            "diagnostic_records",
            "optimization_plans",
            "operational_actions",
        }
    }
    payload[0]["plan_digest"] = freeze_module._stable_digest(plan_material)
    payload[0]["content_digest"] = freeze_module._stable_digest(
        {key: value for key, value in payload[0].items() if key != "content_digest"}
    )
    anchor = _replace_freeze_three_role(tmp_path, "diagnostics", payload, policy)

    verification = verify_freeze_chain(tmp_path, anchor, policy)

    assert verification.valid is False
    assert "ranking basis" in verification.errors[0]


def test_freeze_one_requires_exact_import_role_closure(tmp_path, monkeypatch):
    original = freeze_module._import_source_snapshots

    def omit_provenance(*args, **kwargs):
        return tuple(
            item for item in original(*args, **kwargs) if item[0] != "provenance_0000"
        )

    monkeypatch.setattr(freeze_module, "_import_source_snapshots", omit_provenance)
    freeze_stage_one(tmp_path, _freeze_one_inputs(tmp_path))
    inputs, saturation, _ = _freeze_two_inputs(tmp_path)

    with pytest.raises(V3FreezeError, match="Freeze 1 artifact set"):
        freeze_stage_two(tmp_path, inputs, saturation)


def test_freeze_three_keeps_orchestration_execution_id_distinct(tmp_path):
    family = _write_freeze_one_and_two(tmp_path)
    inputs, plans = _freeze_three_inputs(tmp_path, family)
    execution = inputs.environment.model_executions[0].model_copy(
        update={"execution_id": "UNRELATED-EXECUTION"}
    )
    environment = inputs.environment.model_copy(update={"model_executions": (execution,)})

    manifest = freeze_stage_three(
        tmp_path, inputs.model_copy(update={"environment": environment}), plans
    )

    assert manifest.freeze_version == "Freeze 3"


def test_freeze_three_requires_real_task_six_response_tuple(tmp_path):
    family = _write_freeze_one_and_two(tmp_path)
    inputs, plans = _freeze_three_inputs(tmp_path, family)
    execution = inputs.environment.model_executions[0]
    first, *rest = execution.artifacts
    changed = first.model_copy(update={"response_id": "UNRELATED-RESPONSE"})
    environment = inputs.environment.model_copy(
        update={
            "model_executions": (
                execution.model_copy(update={"artifacts": (changed, *rest)}),
            )
        }
    )

    with pytest.raises(V3FreezeError, match="Task 6 model execution"):
        freeze_stage_three(
            tmp_path, inputs.model_copy(update={"environment": environment}), plans
        )


def test_environment_rejects_non_iso_or_out_of_bounds_model_timestamps():
    with pytest.raises(ValidationError, match="timestamp"):
        FreezeEnvironmentV3(
            **{
                **_environment().model_dump(mode="python"),
                "started_at": "not-a-time",
            }
        )


def test_freeze_one_reopens_and_authenticates_accepted_sources(tmp_path, monkeypatch):
    inputs = _freeze_one_inputs(tmp_path)
    source = tmp_path / "derived/principles/seed_mechanism.json"
    original = freeze_module.import_reusable_evidence

    def import_then_tamper(*args, **kwargs):
        manifest = original(*args, **kwargs)
        source.write_text(source.read_text(encoding="utf-8") + " ", encoding="utf-8")
        return manifest

    monkeypatch.setattr(
        freeze_module, "import_reusable_evidence", import_then_tamper
    )

    with pytest.raises(V3FreezeError, match="accepted source digest"):
        freeze_stage_one(tmp_path, inputs)


def test_freeze_one_rejects_hard_link_aliases(tmp_path):
    inputs = _freeze_one_inputs(tmp_path)
    source = tmp_path / "derived/principles/seed_mechanism.json"
    os.link(source, tmp_path / "derived/principles/seed_mechanism-alias.json")

    with pytest.raises(V3FreezeError, match="hard-link|physical alias"):
        freeze_stage_one(tmp_path, inputs)


def test_freeze_two_rejects_incomplete_persisted_freeze_one_audit(tmp_path):
    freeze_stage_one(tmp_path, _freeze_one_inputs(tmp_path))
    manifest_path = freeze_module.freeze_manifest_path(tmp_path, "Freeze 1")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    audit_key = next(
        key for key in manifest["artifact_digests"] if key.startswith("leakage_audit:")
    )
    audit_path = tmp_path / audit_key.partition(":")[2]
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    audit["dependency_digests"].pop(next(iter(audit["dependency_digests"])))
    encoded = (
        json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    replacement = (
        tmp_path
        / "derived/principles_v3/freezes/objects"
        / f"freeze1-leakage-{digest}.json"
    )
    replacement.write_bytes(encoded)
    del manifest["artifact_digests"][audit_key]
    relative = replacement.relative_to(tmp_path).as_posix()
    manifest["artifact_digests"][f"leakage_audit:{relative}"] = digest
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    inputs, saturation, _ = _freeze_two_inputs(tmp_path)

    with pytest.raises(V3FreezeError, match="leakage audit dependency closure"):
        freeze_stage_two(tmp_path, inputs, saturation)


def test_freeze_two_rejects_changed_v2_rejection_inventory(tmp_path):
    freeze_stage_one(tmp_path, _freeze_one_inputs(tmp_path))
    taxonomy_inputs, saturation, _ = _freeze_two_inputs(tmp_path)
    forbidden = tmp_path / "derived/principles/family_predictions.json"
    forbidden.write_text("{}", encoding="utf-8")

    with pytest.raises(V3FreezeError, match="rejection inventory"):
        freeze_stage_two(tmp_path, taxonomy_inputs, saturation)


def test_freeze_two_rejects_reduced_source_proposal_set(tmp_path):
    freeze_stage_one(tmp_path, _freeze_one_inputs(tmp_path))
    inputs, saturation, _ = _freeze_two_inputs(tmp_path)
    family = inputs.taxonomy.families[0]
    reduced_family = CanonicalFamily.model_validate(
        {
            **family.model_dump(mode="python"),
            "proposal_ids": family.proposal_ids[:1],
            "proposal_provenance": family.proposal_provenance[:1],
        }
    )
    reduced_taxonomy = CanonicalTaxonomy(
        families=(reduced_family,), decisions=(), unresolved_proposal_ids=()
    )
    reduced = inputs.model_copy(
        update={
            "taxonomy": reduced_taxonomy,
            "taxonomy_rounds": (*inputs.taxonomy_rounds[:-1], reduced_taxonomy),
        }
    )

    with pytest.raises(V3FreezeError, match="every Task 6 proposal"):
        freeze_stage_two(tmp_path, reduced, saturation)


def test_freeze_two_rejects_structurally_valid_fabricated_lane_result(tmp_path):
    freeze_stage_one(tmp_path, _freeze_one_inputs(tmp_path))
    inputs, saturation, _ = _freeze_two_inputs(tmp_path)
    original = inputs.source_results[0]
    forged = TaxonomyLaneResult(
        **{
            **original.model_dump(mode="python"),
            "cache_key": "f" * 64,
        }
    )
    changed = inputs.model_copy(
        update={"source_results": (forged, *inputs.source_results[1:])}
    )

    with pytest.raises(V3FreezeError, match="authoritative Task 6 lane artifact"):
        freeze_stage_two(tmp_path, changed, saturation)


def test_freeze_three_rejects_shallow_dictionary_inputs(tmp_path):
    _write_freeze_one_and_two(tmp_path)

    with pytest.raises(V3FreezeError, match="typed Task 8/9"):
        freeze_stage_three(tmp_path, {"records": []}, {"plans": []})


def test_freeze_three_requires_freeze_two_scoring_policy(tmp_path):
    freeze_stage_one(tmp_path, _freeze_one_inputs(tmp_path))
    inputs, saturation, family = _freeze_two_inputs(tmp_path)
    alternate_rubric = inputs.scoring_policy.model_copy(
        update={
            "ranking_stability_max_span": (
                inputs.scoring_policy.ranking_stability_max_span + 1
            )
        }
    )
    freeze_stage_two(
        tmp_path,
        inputs.model_copy(update={"scoring_policy": alternate_rubric}),
        saturation,
    )
    ranking, plans = _freeze_three_inputs(
        tmp_path, family, rubric=alternate_rubric
    )
    ranking = ranking.model_copy(update={"rubric": load_evaluation_rubric()})

    with pytest.raises(V3FreezeError, match="Freeze 2 scoring policy"):
        freeze_stage_three(tmp_path, ranking, plans)


@pytest.mark.parametrize("tamper", ("unattested", "incomplete", "fabricated_blocker"))
def test_freeze_three_rejects_unattested_or_incomplete_evaluations(tmp_path, tamper):
    family = _write_freeze_one_and_two(tmp_path)
    inputs, plans = _freeze_three_inputs(tmp_path, family)
    valid = inputs.evaluations[0]
    if tamper == "unattested":
        forged = valid.model_construct(**valid.model_dump(mode="python"))
    elif tamper == "incomplete":
        forged = valid.model_construct(
            **{**valid.model_dump(mode="python"), "judgments": valid.judgments[:-1]}
        )
    else:
        forged = valid.model_copy(
            update={"priority_region": "excluded", "qualified_blocker_ids": ("FAKE",)}
        )
    forged_inputs = inputs.model_construct(
        **{**inputs.model_dump(mode="python"), "evaluations": (forged,), "ranking": inputs.ranking}
    )

    with pytest.raises(V3FreezeError, match="attested scored evaluation"):
        freeze_stage_three(tmp_path, forged_inputs, plans)


def test_freeze_three_rejects_incomplete_ranking_robustness(tmp_path):
    family = _write_freeze_one_and_two(tmp_path)
    inputs, plans = _freeze_three_inputs(tmp_path, family)
    record = inputs.ranking.records[0].model_copy(update={"pareto_optimal": None})
    ranking = inputs.ranking.model_copy(update={"records": (record,)})
    forged = inputs.model_copy(update={"ranking": ranking})

    with pytest.raises(V3FreezeError, match="attested ranking|robustness"):
        freeze_stage_three(tmp_path, forged, plans)


def test_freeze_three_rejects_tampered_diagnostic_plan(tmp_path):
    family = _write_freeze_one_and_two(tmp_path)
    inputs, plans = _freeze_three_inputs(tmp_path, family)
    tampered = plans[0].model_copy(update={"plan_role": "no_experiment"})

    with pytest.raises(V3FreezeError, match="attested diagnostic"):
        freeze_stage_three(tmp_path, inputs, (tampered,))


def test_freeze_three_runs_current_leakage_audit_over_model_metadata(tmp_path):
    family = _write_freeze_one_and_two(tmp_path)
    policy = LeakagePolicy(
        policy_id="final-sealed",
        sealed_terms=("sealed-token",),
        structure_fingerprint_factory=_STRUCTURE_FACTORY,
    )
    inputs, plans = _freeze_three_inputs(tmp_path, family, policy=policy)
    execution = inputs.environment.model_executions[0].model_copy(
        update={"parameters": {"note": "sealed-token"}}
    )
    environment = inputs.environment.model_copy(update={"model_executions": (execution,)})
    changed = inputs.model_copy(update={"environment": environment})

    with pytest.raises(V3FreezeError, match="current Freeze 3 leakage audit"):
        freeze_stage_three(tmp_path, changed, plans)


def test_environment_requires_complete_model_execution_metadata():
    with pytest.raises(ValidationError):
        ModelExecutionMetadataV3.model_validate(
            {"provider": "test", "model": "test", "parameters": {}}
        )


def test_manifest_publication_has_no_colocated_sidecar(tmp_path):
    freeze_stage_one(tmp_path, _freeze_one_inputs(tmp_path))

    manifest = freeze_module.freeze_manifest_path(tmp_path, "Freeze 1")
    assert manifest.is_file()
    assert not manifest.with_suffix(manifest.suffix + ".sha256").exists()


def test_failed_manifest_publication_leaves_retryable_objects(tmp_path, monkeypatch):
    inputs = _freeze_one_inputs(tmp_path)
    original = freeze_module._publish_manifest

    def fail(*args, **kwargs):
        raise V3FreezeError("synthetic publication failure")

    monkeypatch.setattr(freeze_module, "_publish_manifest", fail)
    with pytest.raises(V3FreezeError, match="synthetic publication failure"):
        freeze_stage_one(tmp_path, inputs)
    monkeypatch.setattr(freeze_module, "_publish_manifest", original)

    manifest = freeze_stage_one(tmp_path, inputs)

    assert manifest.freeze_version == "Freeze 1"


def test_publication_directory_failure_closes_every_open_descriptor(
    tmp_path, monkeypatch
):
    original_open = os.open

    for _ in range(20):
        opened: list[int] = []

        def fail_later_open(path, flags, *args, **kwargs):
            if path == "principles_v3":
                raise PermissionError("synthetic traversal failure")
            descriptor = original_open(path, flags, *args, **kwargs)
            opened.append(descriptor)
            return descriptor

        monkeypatch.setattr(os, "open", fail_later_open)
        with pytest.raises(PermissionError, match="synthetic traversal failure"):
            freeze_module._open_publication_directory(
                tmp_path, ("derived", "principles_v3", "freezes")
            )
        monkeypatch.setattr(os, "open", original_open)

        assert opened
        for descriptor in opened:
            with pytest.raises(OSError):
                os.fstat(descriptor)


@pytest.mark.parametrize("escape", ("absolute", "traversal"))
def test_context_materialization_rejects_path_escape_without_writing(
    tmp_path, escape
):
    owned = tmp_path / "owned"
    owned.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_bytes(b"trusted")
    relative = outside.as_posix() if escape == "absolute" else "../outside.json"

    try:
        with pytest.raises(V3FreezeError, match="materialization path"):
            freeze_module._materialize_snapshot(owned, relative, b"attacker")
    finally:
        assert outside.read_bytes() == b"trusted"


def test_context_materialization_rejects_symlink_escape_without_writing(tmp_path):
    owned = tmp_path / "owned"
    owned.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (owned / "redirect").symlink_to(outside, target_is_directory=True)
    target = outside / "escaped.json"

    try:
        with pytest.raises(V3FreezeError, match="materialization"):
            freeze_module._materialize_snapshot(
                owned, "redirect/escaped.json", b"attacker"
            )
    finally:
        assert not target.exists()


def test_manifest_publication_rejects_directory_substitution(tmp_path, monkeypatch):
    original_link = os.link
    substituted = False

    def link_then_substitute(src, dst, *args, **kwargs):
        nonlocal substituted
        result = original_link(src, dst, *args, **kwargs)
        if dst == "freeze_1_manifest.json" and not substituted:
            freeze_dir = tmp_path / "derived/principles_v3/freezes"
            freeze_dir.rename(tmp_path / "detached-freezes")
            freeze_dir.mkdir()
            substituted = True
        return result

    monkeypatch.setattr(os, "link", link_then_substitute)

    with pytest.raises(V3FreezeError, match="publication|substitution"):
        freeze_stage_one(tmp_path, _freeze_one_inputs(tmp_path))


def test_freeze_three_rejects_same_id_alternate_canonical_definition(tmp_path):
    family = _write_freeze_one_and_two(tmp_path)
    inputs, plans = _freeze_three_inputs(tmp_path, family)
    alternate = family.model_copy(update={"aliases": (*family.aliases, "alternate")})
    diagnostic_inputs = inputs.diagnostic_inputs.model_copy(
        update={"families": (alternate,)}
    )

    with pytest.raises(V3FreezeError, match="canonical definitions"):
        freeze_stage_three(
            tmp_path,
            inputs.model_copy(update={"diagnostic_inputs": diagnostic_inputs}),
            plans,
        )


def test_freeze_three_rejects_re_attested_alternate_evidence_context(tmp_path):
    family = _write_freeze_one_and_two(tmp_path)
    inputs, _ = _freeze_three_inputs(tmp_path, family)
    first_record = inputs.evaluation_context.records[0]
    alternate_context = _context_with_record_update(
        inputs.evaluation_context,
        first_record.evidence_id,
        source_path="papers/coordinated-alternate.pdf",
    )
    alternate_evaluation = score_family(
        _all_supporting_judgments(),
        (),
        inputs.rubric,
        alternate_context,
        family_id=family.family_id,
    )
    alternate_ranking = analyze_ranking(
        (alternate_evaluation,), inputs.rubric, seed=17
    )
    alternate_diagnostic_inputs = inputs.diagnostic_inputs.model_copy(
        update={"evidence": alternate_context.records}
    )
    alternate_plans = design_family_diagnostics(
        alternate_diagnostic_inputs.families,
        (alternate_evaluation,),
        alternate_diagnostic_inputs.principles,
        alternate_diagnostic_inputs.evidence,
        alternate_ranking,
        inventory_records=alternate_diagnostic_inputs.inventory_records,
        rubric=inputs.rubric,
    )
    alternate_inputs = inputs.model_copy(
        update={
            "evaluations": (alternate_evaluation,),
            "ranking": alternate_ranking,
            "evaluation_context": alternate_context,
            "diagnostic_inputs": alternate_diagnostic_inputs,
        }
    )

    with pytest.raises(V3FreezeError, match="authoritative|prefix"):
        freeze_stage_three(tmp_path, alternate_inputs, alternate_plans)


def test_public_binder_rejects_re_attested_alternate_principle_context(tmp_path):
    _write_freeze_one_and_two(tmp_path)
    assert _TRUSTED_CONTEXT is not None
    principle = _TRUSTED_PRINCIPLES[0]
    alternate_principle = principle.model_copy(
        update={"title": "Coordinated alternate Principle"}
    )
    principle_digests = dict(_TRUSTED_CONTEXT.frozen_principle_digests)
    principle_digests[principle.principle_id] = freeze_module._stable_digest(
        alternate_principle.model_dump(mode="json")
    )
    payload = _TRUSTED_CONTEXT.model_dump(mode="python")
    payload["frozen_principle_digests"] = principle_digests
    payload["content_digest"] = freeze_module._context_content_digest(
        _TRUSTED_CONTEXT.records,
        _TRUSTED_CONTEXT.frozen_dependencies,
        _TRUSTED_CONTEXT.freeze_manifest_digest,
        _TRUSTED_CONTEXT.evidence_import_manifest_digest,
        _TRUSTED_CONTEXT.rubric_raw_digest,
        _TRUSTED_CONTEXT.rubric_canonical_digest,
        _TRUSTED_CONTEXT.frozen_principle_ids,
        principle_digests,
    )
    alternate_context = restore_evidence_qualification_context(payload)

    with pytest.raises(V3FreezeError, match="authoritative|prefix"):
        bind_evaluation_context_to_freeze_chain(
            tmp_path,
            alternate_context,
            freeze_manifest_digest(tmp_path, "Freeze 2"),
        )


def test_freeze_three_rejects_cross_assigned_model_artifact_tuples(tmp_path):
    family = _write_freeze_one_and_two(tmp_path)
    inputs, plans = _freeze_three_inputs(tmp_path, family)
    execution = inputs.environment.model_executions[0]
    first, second, *rest = execution.artifacts
    swapped = (
        first.model_copy(update={"cache_key": second.cache_key}),
        second.model_copy(update={"cache_key": first.cache_key}),
        *rest,
    )
    changed_execution = execution.model_copy(update={"artifacts": swapped})
    environment = inputs.environment.model_copy(
        update={"model_executions": (changed_execution,)}
    )

    with pytest.raises(V3FreezeError, match="model execution linkage"):
        freeze_stage_three(
            tmp_path, inputs.model_copy(update={"environment": environment}), plans
        )


def test_verifier_requires_exact_critical_audit_completed_checks(tmp_path):
    _, policy = _write_full_chain(tmp_path)
    manifest = json.loads(
        freeze_module.freeze_manifest_path(tmp_path, "Freeze 3").read_text()
    )
    key = next(
        item
        for item in manifest["artifact_digests"]
        if item.startswith("critical_audit:")
    )
    payload = json.loads((tmp_path / key.partition(":")[2]).read_text())
    payload["completed_checks"] = ["authoritative_evaluations"]
    anchor = _replace_freeze_three_role(tmp_path, "critical_audit", payload, policy)

    verification = verify_freeze_chain(tmp_path, anchor, policy)

    assert verification.valid is False
    assert "completed-check set" in verification.errors[0]

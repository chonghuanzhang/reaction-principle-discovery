"""Resumable, freeze-gated orchestration for Reaction Principle discovery."""

from __future__ import annotations

import argparse
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from pipeline.candidate_ranking import candidate_list_digest, rank_experiment_candidates
from pipeline.chemical_space import FamilyBoundaryPrediction
from pipeline.evidence_registry import _atomic_json, write_evidence_registry
from pipeline.freeze import FreezeError, freeze_candidate_list, freeze_principles
from pipeline.mechanism_normalization import normalize_record
from pipeline.model_proposals import propose_chemical_space, propose_reaction_principles
from pipeline.paper_mechanism_bundles import (
    PaperMechanismBundle,
    load_paper_mechanism_bundles,
    write_source_revisit_registry,
)
from pipeline.principle_induction import validate_principle_candidate
from pipeline.principle_report import write_principle_report
from pipeline.principle_models import (
    BoundaryConstraint,
    ExperimentCandidate,
    FrozenReactionPrincipleSet,
    MechanismEvidence,
    ReactionPrinciple,
    SeedMechanism,
    TransferabilityAssessment,
)
from pipeline.seed_inputs import write_seed_input_inventory
from pipeline.seed_inputs import SeedInputInventory
from pipeline.seed_modeling import model_seed_reaction
from pipeline.semantic_transfer import PaperTransferResult, propose_paper_transfer
from pipeline.transferability import adjudicate_transfer_proposal, assess_transferability
from pipeline.transfer_audit import audit_knowledge_transfer
from pipeline.validation_study import (
    ValidationGateError,
    classify_outcome,
    evaluate_predictions,
)


PHASES = (
    "status",
    "inventory",
    "seed",
    "normalize-smoke",
    "normalize",
    "transfer-smoke",
    "transfer",
    "induce",
    "report",
    "rank",
    "freeze",
    "validate",
)


class PrincipleWorkflowError(RuntimeError):
    """Raised when a local workflow input or phase is invalid."""


class PrincipleWorkflowGateError(PrincipleWorkflowError):
    """Raised when a paid or hidden-answer operation is not yet allowed."""


class _ClientRequired(RuntimeError):
    pass


class _DeferredClient:
    """Avoid Keychain access when normalization can be satisfied from cache."""

    def create_structured(self, *args: object, **kwargs: object) -> Any:
        del args, kwargs
        raise _ClientRequired


def _default_client(model: str, *, read_timeout_seconds: int = 600) -> object:
    """Import the paid client only when a live cache miss requires it."""

    from pipeline.run_pilot import _default_client as build_client

    return build_client(model, read_timeout_seconds=read_timeout_seconds)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _safe_json(path: Path) -> dict[str, object] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _load_json(path: Path, label: str) -> dict[str, object]:
    value = _safe_json(path)
    if value is None:
        raise PrincipleWorkflowError(f"required {label} is missing or invalid: {path}")
    return value


def _load_config(path: Path) -> dict[str, object]:
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PrincipleWorkflowError(f"workflow config is unavailable: {path}") from exc
    if not isinstance(loaded, dict):
        raise PrincipleWorkflowError("workflow configuration must contain a mapping")
    return loaded


def _configured_path(config_path: Path, config: Mapping[str, object], key: str, default: str) -> Path:
    value = Path(str(config.get(key, default)))
    return value if value.is_absolute() else config_path.parent / value


def _artifact_path(output_root: Path, config: Mapping[str, object], key: str, default: str) -> Path:
    value = Path(str(config.get(key, default)))
    return value if value.is_absolute() else output_root / value


def _json_digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _manifest_path(output_root: Path) -> Path:
    return output_root / "derived" / "principles" / "manifest.json"


def _manifest(output_root: Path) -> dict[str, object]:
    existing = _safe_json(_manifest_path(output_root)) or {}
    phases = existing.get("phases")
    if not isinstance(phases, dict):
        phases = {}
    return {
        "version": 1,
        "phases": phases,
        "source_revisits": existing.get("source_revisits", []) if isinstance(existing.get("source_revisits"), list) else [],
        "updated_at": existing.get("updated_at", _now()),
    }


def _write_manifest(output_root: Path, manifest: dict[str, object]) -> None:
    manifest["updated_at"] = _now()
    _atomic_json(_manifest_path(output_root), manifest)


def _set_phase(
    output_root: Path,
    phase: str,
    payload: Mapping[str, object],
    *,
    source_revisits: Sequence[dict[str, object]] | None = None,
) -> dict[str, object]:
    manifest = _manifest(output_root)
    phases = manifest["phases"]
    assert isinstance(phases, dict)
    phases[phase] = {**payload, "updated_at": _now()}
    if source_revisits is not None:
        manifest["source_revisits"] = list(source_revisits)
    _write_manifest(output_root, manifest)
    return manifest


def _items(value: object, key: str) -> list[dict[str, object]]:
    if isinstance(value, dict):
        value = value.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise PrincipleWorkflowError(f"{key} must be a list of objects")
    return list(value)


def _status_items(value: object, key: str) -> list[dict[str, object]]:
    try:
        return _items(value, key)
    except PrincipleWorkflowError:
        return []


def _status_int(value: object) -> int:
    return value if isinstance(value, int) else 0


def _registry_records(output_root: Path) -> list[dict[str, object]]:
    registry = _load_json(output_root / "derived" / "principles" / "evidence_registry.json", "evidence registry")
    records = _items(registry, "records")
    return sorted(records, key=lambda record: str(record.get("source_path", "")))


def _normalization_config(config_path: Path, config: Mapping[str, object]) -> dict[str, object]:
    normalized = config.get("normalization")
    if not isinstance(normalized, dict):
        raise PrincipleWorkflowError("workflow config requires a normalization mapping")
    required = {"model", "prompt_text", "prompt_version", "schema_version"}
    missing = sorted(required - set(normalized))
    if missing:
        raise PrincipleWorkflowError("normalization config is missing: " + ", ".join(missing))
    del config_path
    return dict(normalized)


def _status_counts(records: Mapping[str, object]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in records.values():
        if isinstance(row, dict):
            status = str(row.get("status", "unknown"))
            counts[status] = counts.get(status, 0) + 1
    return dict(sorted(counts.items()))


def build_principle_status(output_root: Path) -> dict[str, object]:
    """Return a best-effort local snapshot without parsing hidden-answer inputs."""

    root = output_root.resolve()
    registry = _safe_json(root / "derived" / "principles" / "evidence_registry.json")
    seed = _safe_json(root / "derived" / "principles" / "seed_input_inventory.json")
    manifest = _safe_json(_manifest_path(root)) or {}
    phases = manifest.get("phases", {}) if isinstance(manifest.get("phases"), dict) else {}
    normalize = phases.get("normalize", {}) if isinstance(phases.get("normalize"), dict) else {}
    records = normalize.get("records", {}) if isinstance(normalize.get("records"), dict) else {}
    transfer_manifest = _safe_json(
        root / "derived" / "principles" / "transfer_manifest.json"
    ) or {}
    transfer_records = (
        transfer_manifest.get("records", {})
        if isinstance(transfer_manifest.get("records"), dict)
        else {}
    )
    review = _safe_json(root / "derived" / "principles" / "principle_review.json")
    review_principles = _status_items(review, "principles") if review is not None else []
    exploration_brief = _safe_json(
        root / "derived" / "principles" / "exploration_brief.json"
    )
    coverage_audit = _safe_json(
        root / "derived" / "principles" / "coverage_audit.json"
    )
    role_index = _safe_json(
        root / "derived" / "principles" / "role_aware_evidence_index.json"
    )
    retrospective = _safe_json(
        root / "derived" / "principles" / "retrospective_development_registry.json"
    )
    principle_layers: dict[str, int] = {}
    for item in review_principles:
        layer = str(item.get("principle_layer", "seed_specific"))
        principle_layers[layer] = principle_layers.get(layer, 0) + 1
    pending = sorted(
        str(item.get("principle_id", ""))
        for item in review_principles
        if item.get("review_status") not in {"accepted", "revised"}
        and isinstance(item.get("principle_id"), str)
    )
    frozen_principles = root / "derived" / "principles" / "frozen_principles.json"
    frozen_candidates = root / "derived" / "principles" / "frozen_candidates.json"
    candidate_payload = _safe_json(frozen_candidates)
    candidate_linked = False
    if candidate_payload is not None and frozen_principles.is_file():
        try:
            candidates = [ExperimentCandidate.model_validate(item) for item in _status_items(candidate_payload, "candidates")]
            digest = candidate_list_digest(candidates)
            principle_digest = hashlib.sha256(frozen_principles.read_bytes()).hexdigest()
            candidate_linked = bool(candidates) and all(
                item.freeze_status == "frozen"
                and item.candidate_list_digest == digest
                and item.principle_digest == principle_digest
                for item in candidates
            )
        except (OSError, ValueError, PrincipleWorkflowError):
            candidate_linked = False
    revisit_registry = _safe_json(
        root / "derived" / "principles" / "source_revisit_registry.json"
    )
    revisits = (
        revisit_registry.get("revisits", [])
        if revisit_registry is not None
        and isinstance(revisit_registry.get("revisits"), list)
        else manifest.get("source_revisits", [])
    )
    pending_revisits = [
        item for item in revisits
        if isinstance(item, dict) and item.get("status") == "pending"
    ] if isinstance(revisits, list) else []
    failures = [
        {
            "source_path": str(source_path),
            "reason": str(row.get("failure_reason", "unknown failure")),
        }
        for source_path, row in sorted(records.items())
        if isinstance(row, dict) and row.get("status") == "failed"
    ]
    failures.extend(
        {
            "source_path": str(source_path),
            "reason": str(row.get("failure_reason", "unknown failure")),
        }
        for source_path, row in sorted(transfer_records.items())
        if isinstance(row, dict) and row.get("status") == "failed"
    )
    transfer_total = _status_int(transfer_manifest.get("paper_count")) or 0
    transfer_success = sum(
        isinstance(row, dict) and row.get("status") in {"validated", "reused"}
        for row in transfer_records.values()
    )
    transfer_failed = sum(
        isinstance(row, dict) and row.get("status") == "failed"
        for row in transfer_records.values()
    )
    transfer_processed = len(transfer_records)
    transfer_percent = (
        round(transfer_processed * 100 / transfer_total, 1) if transfer_total else 0.0
    )
    transfer_assessments = sum(
        _status_int(row.get("assessment_count")) or 0
        for row in transfer_records.values()
        if isinstance(row, dict)
    )

    family_payload = _safe_json(root / "derived" / "principles" / "family_predictions.json")
    family_rows = _status_items(family_payload, "families") if family_payload else []
    family_counts: dict[str, int] = {}
    for row in family_rows:
        classification = str(row.get("classification", "unknown"))
        family_counts[classification] = family_counts.get(classification, 0) + 1

    provisional_path = root / "derived" / "principles" / "provisional_candidates.json"
    visible_candidate_path = frozen_candidates if frozen_candidates.is_file() else provisional_path
    visible_candidate_payload = _safe_json(visible_candidate_path)
    candidate_rows = (
        _status_items(visible_candidate_payload, "candidates")
        if visible_candidate_payload
        else []
    )
    chemistry_review = _safe_json(root / "reports" / "chemistry_review.json")
    candidate_review = (
        chemistry_review.get("candidate_review", {})
        if chemistry_review is not None
        and isinstance(chemistry_review.get("candidate_review"), dict)
        else {}
    )
    rejected_candidate_ids = {
        str(value)
        for value in candidate_review.get(
            "out_of_scope_intermediate_experiment_ids", []
        )
        if isinstance(value, str)
    }
    reviewed_candidate_rows = [
        row
        for row in candidate_rows
        if str(row.get("experiment_id", "")) not in rejected_candidate_ids
    ]
    top_candidates = [
        {
            "experiment_id": str(row.get("experiment_id", "")),
            "electrophile": str(row.get("electrophile", "")),
            "nucleophile": str(row.get("nucleophile", "")),
            "predicted_outcome": str(row.get("predicted_outcome", "unknown")),
            "experiment_priority": _status_int(row.get("experiment_priority")),
            "total_score": _status_int(row.get("total_score")),
            "provisional": row.get("freeze_status") != "frozen",
        }
        for row in sorted(
            reviewed_candidate_rows,
            key=lambda value: (
                _status_int(value.get("experiment_priority")) or 10**9,
                str(value.get("experiment_id", "")),
            ),
        )[:10]
    ]

    if candidate_linked:
        state = "frozen"
    elif pending:
        state = "review_required"
    elif failures:
        state = "failed"
    elif records or transfer_records:
        state = "running"
    elif registry is not None or seed is not None or family_rows or candidate_rows:
        state = "ready"
    else:
        state = "absent"

    stage_names = (
        "inventory",
        "seed",
        "normalize",
        "transfer",
        "induce",
        "report",
        "rank",
        "freeze",
        "validate",
    )
    stages = [
        {
            "name": name,
            "status": str(phases.get(name, {}).get("status", "not_started"))
            if isinstance(phases.get(name), dict)
            else "not_started",
        }
        for name in stage_names
    ]
    return {
        "state": state,
        "stages": stages,
        "registry": {
            "state": "ready" if registry is not None else "absent",
            "queue_paper_count": _status_int(registry.get("queue_paper_count")) if registry else 0,
            "scoped_record_count": _status_int(registry.get("scoped_record_count")) if registry else 0,
            "missing_record_count": len(registry.get("missing_source_paths", [])) if registry and isinstance(registry.get("missing_source_paths"), list) else 0,
        },
        "seed_inputs": {
            "state": "ready" if seed is not None else "absent",
            "principle_building_count": len(seed.get("principle_building_files", [])) if seed and isinstance(seed.get("principle_building_files"), list) else 0,
            "hidden_answers_revealed": False,
        },
        "normalization": {
            "record_count": len(records),
            "status_counts": _status_counts(records),
            "pending_source_revisit_count": len(pending_revisits),
        },
        "knowledge_transfer": {
            "state": str(transfer_manifest.get("status", "not_started")),
            "processed_count": transfer_processed,
            "successful_count": transfer_success,
            "failed_count": transfer_failed,
            "paper_count": transfer_total,
            "assessment_count": transfer_assessments,
            "percent": transfer_percent,
            "updated_at": transfer_manifest.get("updated_at"),
        },
        "human_review": {
            "pending_count": len(pending),
            "pending_principle_ids": pending,
        },
        "freeze": {
            "principles_frozen": frozen_principles.is_file(),
            "candidates_frozen": frozen_candidates.is_file(),
            "digest_linked": candidate_linked,
        },
        "validation": {"ready": candidate_linked and not pending},
        "family_boundaries": {
            "provisional": not candidate_linked,
            "counts": dict(sorted(family_counts.items())),
        },
        "exploration": {
            "state": "configured" if exploration_brief is not None else "absent",
            "version": exploration_brief.get("version") if exploration_brief else None,
            "stage": exploration_brief.get("stage") if exploration_brief else None,
            "fixed_role": (
                exploration_brief.get("fixed_role", {}).get("role")
                if exploration_brief
                and isinstance(exploration_brief.get("fixed_role"), dict)
                else None
            ),
            "variable_role": (
                exploration_brief.get("variable_role", {}).get("role")
                if exploration_brief
                and isinstance(exploration_brief.get("variable_role"), dict)
                else None
            ),
            "digest": exploration_brief.get("digest") if exploration_brief else None,
        },
        "principle_layers": dict(sorted(principle_layers.items())),
        "nucleophile_coverage": {
            "state": "complete"
            if coverage_audit is not None and coverage_audit.get("complete") is True
            else "incomplete"
            if coverage_audit is not None
            else "not_started",
            "required_count": (
                len(coverage_audit.get("required_superclass_ids", []))
                if coverage_audit is not None
                and isinstance(coverage_audit.get("required_superclass_ids"), list)
                else None
            ),
            "covered_count": (
                len(coverage_audit.get("covered_superclass_ids", []))
                if coverage_audit is not None
                and isinstance(coverage_audit.get("covered_superclass_ids"), list)
                else None
            ),
            "missing_count": (
                len(coverage_audit.get("missing_superclass_ids", []))
                if coverage_audit is not None
                and isinstance(coverage_audit.get("missing_superclass_ids"), list)
                else None
            ),
            "missing_superclass_ids": (
                coverage_audit.get("missing_superclass_ids", [])
                if coverage_audit is not None
                else []
            ),
            "mapped_evidence_count": (
                _status_int(role_index.get("mapped_count")) if role_index else None
            ),
            "unmapped_evidence_count": (
                _status_int(role_index.get("unmapped_count")) if role_index else None
            ),
        },
        "retrospective_development": {
            "state": "registered" if retrospective is not None else "absent",
            "usage": retrospective.get("usage") if retrospective else None,
            "prospective_metric_eligible": (
                retrospective.get("prospective_metric_eligible")
                if retrospective is not None
                else None
            ),
            "outcome_count": (
                len(retrospective.get("outcomes", []))
                if retrospective is not None
                and isinstance(retrospective.get("outcomes"), list)
                else 0
            ),
        },
        "candidate_scope_review": {
            "reviewed_count": _status_int(
                candidate_review.get("reviewed_candidate_count")
            ),
            "stage_one_compliant_count": _status_int(
                candidate_review.get("fixed_seed_substrate_compliant_count")
            ),
            "rejected_count": _status_int(
                candidate_review.get("out_of_scope_intermediate_count")
            ),
            "decision": candidate_review.get("overall_decision"),
        },
        "top_candidates": top_candidates,
        "failures": failures,
        "hidden_answers": {
            "state": "validation_revealed"
            if isinstance(phases.get("validate"), dict)
            and phases["validate"].get("status") == "complete"
            else "locked",
            "revealed": bool(
                isinstance(phases.get("validate"), dict)
                and phases["validate"].get("status") == "complete"
            ),
        },
    }


def _run_inventory(output_root: Path) -> dict[str, object]:
    path = write_evidence_registry(output_root)
    registry = _load_json(path, "written evidence registry")
    result = {
        "status": "complete",
        "queue_paper_count": registry.get("queue_paper_count", 0),
        "scoped_record_count": registry.get("scoped_record_count", 0),
        "missing_record_count": len(registry.get("missing_source_paths", [])),
    }
    _set_phase(output_root, "inventory", result)
    return result


def _run_seed(
    config_path: Path,
    source_root: Path,
    output_root: Path,
    config: Mapping[str, object],
    *,
    live: bool,
    client: object | None,
) -> dict[str, object]:
    if not live:
        raise PrincipleWorkflowGateError("seed requires the explicit --live flag")
    seed_config_path = _configured_path(config_path, config, "seed_sources_config", "seed_sources.yaml")
    loaded = _load_config(seed_config_path)
    destination = write_seed_input_inventory(source_root, output_root, loaded)
    inventory_payload = _load_json(destination, "seed input inventory")
    inventory = SeedInputInventory.model_validate(
        {
            key: inventory_payload.get(key)
            for key in (
                "source_root",
                "files",
                "principle_building_digest",
                "hidden_answer_digest",
                "hidden_answers_revealed",
            )
        }
    )
    modeling = config.get("seed_modeling")
    if not isinstance(modeling, dict):
        raise PrincipleWorkflowError("workflow config requires a seed_modeling mapping")
    required = {"model", "prompt_text", "prompt_version"}
    missing = sorted(required - set(modeling))
    if missing:
        raise PrincipleWorkflowError("seed_modeling config is missing: " + ", ".join(missing))
    active_client: object = client if client is not None else _DeferredClient()
    cache_root = output_root / "derived" / "principles" / "seed_modeling"
    try:
        result_model = model_seed_reaction(
            inventory, active_client, dict(modeling), cache_root  # type: ignore[arg-type]
        )
    except _ClientRequired:
        active_client = _default_client(str(modeling["model"]))
        result_model = model_seed_reaction(
            inventory, active_client, dict(modeling), cache_root  # type: ignore[arg-type]
        )
    principle_root = output_root / "derived" / "principles"
    _atomic_json(
        principle_root / "seed_evidence.json",
        {
            "cache_key": result_model.cache_key,
            "evidence": [item.model_dump(mode="json") for item in result_model.seed_evidence],
        },
    )
    _atomic_json(
        principle_root / "seed_mechanism.json",
        result_model.seed_mechanism.model_dump(mode="json"),
    )
    _atomic_json(
        principle_root / "seed_principle.json",
        result_model.seed_principle.model_dump(mode="json"),
    )
    result = {
        "status": "complete",
        "cache_status": result_model.status,
        "principle_building_count": len(inventory.principle_building_files),
        "hidden_answer_count": len(inventory.hidden_answer_files),
        "seed_evidence_count": len(result_model.seed_evidence),
        "hidden_answers_revealed": False,
    }
    _set_phase(output_root, "seed", result)
    return result


def _normalize(
    config_path: Path,
    output_root: Path,
    config: Mapping[str, object],
    phase: str,
    *,
    live: bool,
    client: object | None,
) -> dict[str, object]:
    if not live:
        raise PrincipleWorkflowGateError(f"{phase} requires the explicit --live flag")
    all_records = _registry_records(output_root)
    records = all_records[:1] if phase == "normalize-smoke" else all_records
    normalization = _normalization_config(config_path, config)
    cache_root = output_root / "derived" / "principles" / "normalization"
    active_client: object = client if client is not None else _DeferredClient()
    manifest = _manifest(output_root)
    phases = manifest["phases"]
    assert isinstance(phases, dict)
    state = phases.get("normalize", {}) if isinstance(phases.get("normalize"), dict) else {}
    state_records = state.get("records", {}) if isinstance(state.get("records"), dict) else {}
    scoped_paths = {str(record.get("source_path", "")) for record in all_records}
    current = {
        source_path: value
        for source_path, value in state_records.items()
        if source_path in scoped_paths and isinstance(value, dict)
    }
    revisits = manifest.get("source_revisits", []) if isinstance(manifest.get("source_revisits"), list) else []
    revisit_by_id = {str(item.get("request_id")): item for item in revisits if isinstance(item, dict)}
    state = {
        "status": "complete" if not all_records else "running",
        "records": dict(sorted(current.items())),
        "source_revisit_count": len(revisit_by_id),
    }
    if not records:
        phases["normalize"] = {**state, "updated_at": _now()}
        if phase == "normalize-smoke":
            phases[phase] = {**state, "record_limit": 1, "updated_at": _now()}
        _write_manifest(output_root, manifest)
        return {**state, "source_revisits": [revisit_by_id[key] for key in sorted(revisit_by_id)]}
    for registry_record in records:
        source_path = str(registry_record.get("source_path", ""))
        validated_path = output_root / str(registry_record.get("validated_path", ""))
        try:
            record = _load_json(validated_path, f"validated literature record {source_path}")
            try:
                result = normalize_record(record, active_client, normalization, cache_root)  # type: ignore[arg-type]
            except _ClientRequired:
                active_client = _default_client(str(normalization["model"]))
                result = normalize_record(record, active_client, normalization, cache_root)  # type: ignore[arg-type]
            current[source_path] = {
                "status": result.status,
                "cache_key": result.cache_key,
                "mechanism_evidence_count": len(result.mechanism_evidence),
                "boundary_constraint_count": len(result.boundary_constraints),
            }
            for revisit in result.source_revisit_requests:
                revisit_by_id[revisit.request_id] = revisit.model_dump(mode="json")
        except Exception as exc:
            current[source_path] = {"status": "failed", "failure_reason": str(exc)}
        has_failures = any(
            item.get("status") == "failed"
            for item in current.values()
            if isinstance(item, dict)
        )
        full_status = (
            "completed_with_failures" if has_failures else "complete"
        ) if len(current) == len(all_records) else "running"
        state = {
            "status": full_status,
            "records": dict(sorted(current.items())),
            "source_revisit_count": len(revisit_by_id),
        }
        phases["normalize"] = {**state, "updated_at": _now()}
        if phase == "normalize-smoke":
            smoke_state = {
                **state,
                "status": "completed_with_failures" if has_failures else "complete",
                "record_limit": 1,
                "updated_at": _now(),
            }
            phases[phase] = smoke_state
        manifest["source_revisits"] = [revisit_by_id[key] for key in sorted(revisit_by_id)]
        _write_manifest(output_root, manifest)
    result_state = phases[phase] if phase == "normalize-smoke" else state
    result_revisits = [revisit_by_id[key] for key in sorted(revisit_by_id)]
    if phase == "normalize" and state.get("status") == "complete":
        bundles = load_paper_mechanism_bundles(output_root)
        revisit_path = write_source_revisit_registry(output_root, bundles)
        revisit_payload = _load_json(revisit_path, "source revisit registry")
        result_revisits = _items(revisit_payload, "revisits")
        state["source_revisit_count"] = len(result_revisits)
        phases["normalize"] = {**state, "updated_at": _now()}
        manifest["source_revisit_registry"] = str(revisit_path.relative_to(output_root))
        _write_manifest(output_root, manifest)
        result_state = state
    return {**result_state, "source_revisits": result_revisits}


def _normalization_outputs(output_root: Path) -> tuple[list[MechanismEvidence], list[BoundaryConstraint]]:
    mechanisms: list[MechanismEvidence] = []
    constraints: list[BoundaryConstraint] = []
    for path in sorted((output_root / "derived" / "principles" / "normalization").glob("*/validated.json")):
        payload = _safe_json(path)
        if payload is None or not isinstance(payload.get("normalization"), dict):
            continue
        normalization = payload["normalization"]
        mechanisms.extend(MechanismEvidence.model_validate(item) for item in _items(normalization, "mechanism_evidence"))
        constraints.extend(BoundaryConstraint.model_validate(item) for item in _items(normalization, "boundary_constraints"))
    return mechanisms, constraints


def _run_transfer(config_path: Path, output_root: Path, config: Mapping[str, object]) -> dict[str, object]:
    seed_path = _artifact_path(output_root, config, "seed_mechanism_path", "derived/principles/seed_mechanism.json")
    seed = SeedMechanism.model_validate(_load_json(seed_path, "seed mechanism"))
    rubric = _load_config(_configured_path(config_path, config, "transferability_config", "transferability.yaml"))
    mechanisms, constraints = _normalization_outputs(output_root)
    assessments: list[TransferabilityAssessment] = []
    for evidence in sorted(mechanisms, key=lambda item: item.mechanism_evidence_id):
        assessments.append(assess_transferability(seed, evidence, constraints, rubric))
        _atomic_json(output_root / "derived" / "principles" / "transfer_assessments.json", {"assessments": [item.model_dump(mode="json") for item in assessments]})
        _set_phase(output_root, "transfer", {"status": "running", "assessment_count": len(assessments)})
    result = {"status": "complete", "assessment_count": len(assessments)}
    _set_phase(output_root, "transfer", result)
    return result


def _run_semantic_transfer(
    config_path: Path,
    output_root: Path,
    config: Mapping[str, object],
    phase: str,
    *,
    live: bool,
    client: object | None,
) -> dict[str, object]:
    seed = SeedMechanism.model_validate(
        _load_json(
            _artifact_path(
                output_root,
                config,
                "seed_mechanism_path",
                "derived/principles/seed_mechanism.json",
            ),
            "seed mechanism",
        )
    )
    raw_modeling = config.get("semantic_transfer")
    if not isinstance(raw_modeling, dict):
        raise PrincipleWorkflowError("workflow config requires a semantic_transfer mapping")
    modeling = dict(raw_modeling)
    rubric = _load_config(
        _configured_path(
            config_path, config, "transferability_config", "transferability.yaml"
        )
    )
    bundles = list(load_paper_mechanism_bundles(output_root))
    selected = bundles[:1] if phase == "transfer-smoke" else bundles
    cache_root = output_root / "derived/principles/semantic_transfer"
    manifest_path = output_root / "derived/principles/transfer_manifest.json"
    manifest = _safe_json(manifest_path) or {"version": 2, "records": {}}
    records = manifest.get("records")
    if not isinstance(records, dict):
        records = {}
    max_workers = 1 if phase == "transfer-smoke" else int(modeling.get("max_workers", 1))
    if max_workers < 1 or max_workers > 4:
        raise PrincipleWorkflowError("semantic_transfer.max_workers must be between 1 and 4")
    active_client: object
    if client is not None:
        active_client = client
    elif live:
        active_client = _default_client(str(modeling.get("model", "")))
    else:
        active_client = _DeferredClient()
    paper_results: dict[str, list[TransferabilityAssessment]] = {}

    def process_bundle(
        bundle: PaperMechanismBundle,
    ) -> tuple[PaperTransferResult, list[TransferabilityAssessment]]:
        proposed = propose_paper_transfer(
            seed, bundle, active_client, modeling, cache_root  # type: ignore[arg-type]
        )
        paper_assessments = [
            adjudicate_transfer_proposal(seed, bundle, proposal, rubric)
            for proposal in proposed.proposals
        ]
        _atomic_json(
            cache_root / bundle.namespace / "adjudicated.json",
            {
                "cache_key": proposed.cache_key,
                "namespace": bundle.namespace,
                "source_path": bundle.source_path,
                "assessments": [
                    item.model_dump(mode="json") for item in paper_assessments
                ],
            },
        )
        return proposed, paper_assessments

    def record_progress(
        bundle: PaperMechanismBundle,
        outcome: tuple[PaperTransferResult, list[TransferabilityAssessment]] | Exception,
    ) -> None:
        if isinstance(outcome, Exception):
            if isinstance(outcome, _ClientRequired):
                raise PrincipleWorkflowGateError(
                    f"{phase} requires the explicit --live flag when semantic caches are absent"
                ) from outcome
            if isinstance(outcome, PrincipleWorkflowGateError):
                raise outcome
            records[bundle.source_path] = {
                "status": "failed",
                "namespace": bundle.namespace,
                "failure_reason": str(outcome),
            }
        else:
            proposed, paper_assessments = outcome
            paper_results[bundle.source_path] = paper_assessments
            records[bundle.source_path] = {
                "status": proposed.status,
                "namespace": bundle.namespace,
                "cache_key": proposed.cache_key,
                "assessment_count": len(paper_assessments),
            }
        selected_sources = {item.source_path for item in selected}
        current_manifest = {
            "version": 2,
            "status": "running",
            "paper_count": len(bundles),
            "records": dict(sorted(records.items())),
            "updated_at": _now(),
        }
        _atomic_json(manifest_path, current_manifest)
        _set_phase(
            output_root,
            "transfer" if phase == "transfer" else "transfer-smoke",
            {
                "status": "running",
                "paper_count": len(selected),
                "completed_paper_count": len(
                    [
                        row
                        for source_path, row in records.items()
                        if source_path in selected_sources
                        and isinstance(row, dict)
                        and row.get("status") != "failed"
                    ]
                ),
            },
        )

    if max_workers == 1:
        for bundle in selected:
            try:
                outcome = process_bundle(bundle)
            except Exception as exc:
                outcome = exc
            record_progress(bundle, outcome)
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(process_bundle, bundle): bundle for bundle in selected
            }
            for future in as_completed(futures):
                bundle = futures[future]
                try:
                    outcome = future.result()
                except Exception as exc:
                    outcome = exc
                record_progress(bundle, outcome)

    assessments: list[TransferabilityAssessment] = []
    for bundle in selected:
        assessments.extend(paper_results.get(bundle.source_path, []))
    duplicate_ids = len(assessments) != len(
        {item.assessment_id for item in assessments}
    )
    if duplicate_ids:
        raise PrincipleWorkflowError("semantic transfer produced duplicate assessment IDs")
    failures = [
        row
        for source_path, row in records.items()
        if source_path in {bundle.source_path for bundle in selected}
        and isinstance(row, dict)
        and row.get("status") == "failed"
    ]
    status = "completed_with_failures" if failures else "complete"
    aggregate_payload = {
        "semantic_transfer_version": "2.0",
        "paper_count": len(selected),
        "assessment_count": len(assessments),
        "assessments": [item.model_dump(mode="json") for item in assessments],
    }
    if phase == "transfer-smoke":
        destination = output_root / "derived/principles/transfer_smoke_assessments.json"
    else:
        destination = output_root / "derived/principles/transfer_assessments.json"
        legacy = output_root / "derived/principles/transfer_assessments_legacy_exact_text.json"
        if destination.is_file():
            current = _safe_json(destination)
            if current is not None and current.get("semantic_transfer_version") != "2.0":
                if not legacy.exists():
                    destination.replace(legacy)
    _atomic_json(destination, aggregate_payload)
    manifest = {
        "version": 2,
        "status": status,
        "paper_count": len(bundles),
        "records": dict(sorted(records.items())),
        "updated_at": _now(),
    }
    _atomic_json(manifest_path, manifest)
    result = {
        "status": status,
        "paper_count": len(selected),
        "assessment_count": len(assessments),
        "failure_count": len(failures),
    }
    _set_phase(
        output_root,
        "transfer" if phase == "transfer" else "transfer-smoke",
        result,
    )
    return result


def _run_induce(
    output_root: Path,
    config: Mapping[str, object],
    *,
    live: bool,
    client: object | None,
) -> dict[str, object]:
    seed = SeedMechanism.model_validate(_load_json(_artifact_path(output_root, config, "seed_mechanism_path", "derived/principles/seed_mechanism.json"), "seed mechanism"))
    review_path = _artifact_path(output_root, config, "principle_review_path", "derived/principles/principle_review.json")
    proposal_path = _artifact_path(output_root, config, "principle_proposals_path", "derived/principles/principle_proposals.json")
    transfer_payload = _load_json(output_root / "derived" / "principles" / "transfer_assessments.json", "transfer assessments")
    if transfer_payload.get("semantic_transfer_version") != "2.0":
        raise PrincipleWorkflowGateError(
            "induce requires audited semantic_transfer_version=2.0 assessments"
        )
    assessments = {
        item.assessment_id: item
        for item in (TransferabilityAssessment.model_validate(row) for row in _items(transfer_payload, "assessments"))
    }
    audit = audit_knowledge_transfer(output_root)
    if audit.assessment_count != len(assessments):
        raise PrincipleWorkflowGateError(
            "Knowledge Transfer audit count does not match induction assessments"
        )
    if audit.assessment_count >= 10:
        active_statuses = {
            name for name, count in audit.status_counts.items() if count > 0
        }
        active_judgments = {
            name.rsplit(":", 1)[-1]
            for name, count in audit.component_judgment_counts.items()
            if count > 0
        }
        if len(active_statuses) < 2 or len(active_judgments) < 2:
            raise PrincipleWorkflowGateError(
                "Knowledge Transfer distribution is degenerate; Principle induction blocked"
            )
    _atomic_json(
        output_root / "reports/knowledge_transfer_audit.json",
        audit.model_dump(mode="json"),
    )
    if not review_path.is_file() and not proposal_path.is_file():
        if not live:
            raise PrincipleWorkflowGateError(
                "induce requires the explicit --live flag when proposals are absent"
            )
        active_client: object = client if client is not None else _DeferredClient()
        cache_root = output_root / "derived" / "principles" / "principle_modeling"
        try:
            proposed = propose_reaction_principles(
                seed, assessments, active_client, dict(modeling), cache_root  # type: ignore[arg-type]
            )
        except _ClientRequired:
            active_client = _default_client(
                str(modeling.get("model", "")),
                read_timeout_seconds=int(modeling.get("read_timeout_seconds", 600)),
            )
            proposed = propose_reaction_principles(
                seed, assessments, active_client, dict(modeling), cache_root  # type: ignore[arg-type]
            )
        _atomic_json(
            proposal_path,
            {
                "cache_key": proposed.cache_key,
                "principles": [
                    item.model_dump(mode="json") for item in proposed.principles
                ],
            },
        )
    source = review_path if review_path.is_file() else proposal_path
    proposals = _items(_load_json(source, "principle proposals"), "principles")
    accepted: list[ReactionPrinciple] = []
    failures: dict[str, str] = {}
    for row in proposals:
        principle_id = str(row.get("principle_id", "unknown"))
        try:
            accepted.append(validate_principle_candidate(ReactionPrinciple.model_validate(row), known_seed_evidence_ids=set(seed.evidence_ids), transfer_assessments=assessments))
        except Exception as exc:
            failures[principle_id] = str(exc)
        _atomic_json(review_path, {"principles": [item.model_dump(mode="json") for item in accepted], "failures": failures})
        _set_phase(output_root, "induce", {"status": "running", "validated_count": len(accepted), "failure_count": len(failures)})
    pending = sorted(item.principle_id for item in accepted if item.review_status not in {"accepted", "revised"})
    result = {"status": "review_required" if pending else "ready_to_freeze", "validated_count": len(accepted), "failure_count": len(failures), "pending_principle_ids": pending}
    _set_phase(output_root, "induce", result)
    return result


def _run_rank(
    config_path: Path,
    output_root: Path,
    config: Mapping[str, object],
    *,
    live: bool,
    client: object | None,
) -> dict[str, object]:
    exploration_brief, brief_digest = _persist_exploration_brief(output_root, config)
    retrospective_path = _configured_path(
        config_path,
        config,
        "retrospective_development_registry",
        "retrospective_development_outcomes.yaml",
    )
    if retrospective_path.is_file():
        retrospective = _load_config(retrospective_path)
        if retrospective.get("prospective_metric_eligible") is not False:
            raise PrincipleWorkflowGateError(
                "retrospective development outcomes must be prospectively ineligible"
            )
        _atomic_json(
            output_root
            / "derived/principles/retrospective_development_registry.json",
            retrospective,
        )
    if exploration_brief.stage == "electrophile_family_expansion":
        stage_one = _safe_json(
            output_root / "derived/principles/stage1_manifest.json"
        )
        if (
            stage_one is None
            or stage_one.get("exploration_brief_digest") != brief_digest
            or stage_one.get("reviewed") is not True
            or stage_one.get("coverage_complete") is not True
        ):
            raise PrincipleWorkflowGateError(
                "electrophile expansion requires a reviewed Stage 1 manifest"
            )
    families_path = _artifact_path(output_root, config, "family_predictions_path", "derived/principles/family_predictions.json")
    candidates_path = _artifact_path(output_root, config, "experiment_candidates_path", "derived/principles/experiment_candidates.json")
    rubric = _load_config(_configured_path(config_path, config, "candidate_scoring_config", "candidate_scoring.yaml"))
    coverage_path = output_root / "derived/principles/coverage_audit.json"
    reuse_v2_space = (
        families_path.is_file()
        and candidates_path.is_file()
        and _artifact_matches_brief(families_path, brief_digest)
        and _artifact_matches_brief(coverage_path, brief_digest)
    )
    coverage_audit: dict[str, object] | None = None
    if reuse_v2_space:
        families = {item.family_id: item for item in (FamilyBoundaryPrediction.model_validate(row) for row in _items(_load_json(families_path, "family predictions"), "families"))}
        candidate_inputs = _items(_load_json(candidates_path, "experiment candidates"), "candidates")
        ranked = rank_experiment_candidates(candidate_inputs, families, rubric)
        coverage_audit = _load_json(coverage_path, "coverage audit")
    else:
        if not live:
            raise PrincipleWorkflowGateError(
                "rank requires the explicit --live flag when chemical-space inputs are absent"
            )
        review_path = _artifact_path(
            output_root,
            config,
            "principle_review_path",
            "derived/principles/principle_review.json",
        )
        principles = [
            ReactionPrinciple.model_validate(row)
            for row in _items(_load_json(review_path, "principle review"), "principles")
        ]
        transfer_payload = _load_json(
            output_root / "derived" / "principles" / "transfer_assessments.json",
            "transfer assessments",
        )
        assessments = {
            item.assessment_id: item
            for item in (
                TransferabilityAssessment.model_validate(row)
                for row in _items(transfer_payload, "assessments")
            )
        }
        modeling = config.get("chemical_space_modeling")
        if not isinstance(modeling, dict):
            raise PrincipleWorkflowError(
                "workflow config requires a chemical_space_modeling mapping"
            )
        active_client: object = client if client is not None else _DeferredClient()
        cache_root = output_root / "derived" / "principles" / "chemical_space_modeling"
        try:
            space = propose_chemical_space(
                principles,
                assessments,
                active_client,  # type: ignore[arg-type]
                dict(modeling),
                rubric,
                cache_root,
                exploration_brief=exploration_brief,
            )
        except _ClientRequired:
            active_client = _default_client(str(modeling.get("model", "")))
            space = propose_chemical_space(
                principles,
                assessments,
                active_client,  # type: ignore[arg-type]
                dict(modeling),
                rubric,
                cache_root,
                exploration_brief=exploration_brief,
            )
        if space.coverage_audit is None:
            raise PrincipleWorkflowGateError(
                "v2 chemical-space proposal did not return a coverage audit"
            )
        coverage_audit = {
            **space.coverage_audit.model_dump(mode="json"),
            "exploration_brief_digest": brief_digest,
        }
        _atomic_json(coverage_path, coverage_audit)
        families = {item.family_id: item for item in space.families}
        ranked = space.candidates
        _atomic_json(
            families_path,
            {
                "cache_key": space.cache_key,
                **(
                    {"exploration_brief_digest": brief_digest}
                    if brief_digest is not None
                    else {}
                ),
                "families": [item.model_dump(mode="json") for item in space.families],
            },
        )
    scoring_snapshot = {"scoring_digest": _json_digest(rubric), "config": rubric}
    _atomic_json(output_root / "derived" / "principles" / "scoring_snapshot.json", scoring_snapshot)
    destination = _artifact_path(output_root, config, "provisional_candidates_path", "derived/principles/provisional_candidates.json")
    _atomic_json(destination, {"candidates": [item.model_dump(mode="json") for item in ranked]})
    coverage_complete = bool(
        coverage_audit is not None and coverage_audit.get("complete") is True
    )
    if exploration_brief.stage == "fixed_electrophile_nucleophile_condition":
        reviewed = all(
            item.status in {"accepted", "revised"}
            and item.review_status in {"accepted", "revised"}
            for item in principles
        ) if "principles" in locals() else True
        _atomic_json(
            output_root / "derived/principles/stage1_manifest.json",
            {
                **(
                    {"exploration_brief_digest": brief_digest}
                    if brief_digest is not None
                    else {}
                ),
                "reviewed": reviewed,
                "coverage_complete": coverage_complete,
                "candidate_count": len(ranked),
            },
        )
    result = {
        "status": "complete",
        "candidate_count": len(ranked),
        "coverage_complete": coverage_complete,
        "scoring_digest": scoring_snapshot["scoring_digest"],
    }
    _set_phase(output_root, "rank", result)
    return result


def _run_freeze(output_root: Path, config: Mapping[str, object]) -> dict[str, object]:
    review_path = _artifact_path(output_root, config, "principle_review_path", "derived/principles/principle_review.json")
    principles = [ReactionPrinciple.model_validate(row) for row in _items(_load_json(review_path, "principle review"), "principles")]
    registry = _load_json(output_root / "derived" / "principles" / "evidence_registry.json", "evidence registry")
    source_digest = str(registry.get("queue_digest", ""))
    scoring = _load_json(output_root / "derived" / "principles" / "scoring_snapshot.json", "scoring snapshot")
    scoring_digest = str(scoring.get("scoring_digest", ""))
    if len(source_digest) != 64 or len(scoring_digest) != 64:
        raise PrincipleWorkflowGateError("a queue digest and scoring snapshot are required before freeze")
    version = str(config.get("freeze_version", "v1"))
    frozen_path = _artifact_path(output_root, config, "frozen_principles_path", "derived/principles/frozen_principles.json")
    try:
        frozen = FrozenReactionPrincipleSet.model_validate(_load_json(frozen_path, "frozen principles")) if frozen_path.is_file() else freeze_principles(principles, source_digest=source_digest, scoring_digest=scoring_digest, freeze_version=version, destination=frozen_path, created_at=_now())
    except FreezeError as exc:
        raise PrincipleWorkflowGateError(str(exc)) from exc
    provisional_path = _artifact_path(output_root, config, "provisional_candidates_path", "derived/principles/provisional_candidates.json")
    provisional = [ExperimentCandidate.model_validate(row) for row in _items(_load_json(provisional_path, "provisional candidates"), "candidates")]
    candidates_path = _artifact_path(output_root, config, "frozen_candidates_path", "derived/principles/frozen_candidates.json")
    try:
        frozen_candidates = [ExperimentCandidate.model_validate(row) for row in _items(_load_json(candidates_path, "frozen candidates"), "candidates")] if candidates_path.is_file() else list(freeze_candidate_list(provisional, frozen_principles=frozen, frozen_principle_path=frozen_path, destination=candidates_path))
    except FreezeError as exc:
        raise PrincipleWorkflowGateError(str(exc)) from exc
    result = {"status": "complete", "freeze_version": frozen.freeze_version, "principle_count": len(frozen.principles), "candidate_count": len(frozen_candidates)}
    _set_phase(output_root, "freeze", result)
    return result


def _run_validate(output_root: Path, config: Mapping[str, object]) -> dict[str, object]:
    frozen_path = _artifact_path(output_root, config, "frozen_principles_path", "derived/principles/frozen_principles.json")
    candidates_path = _artifact_path(output_root, config, "frozen_candidates_path", "derived/principles/frozen_candidates.json")
    if not frozen_path.is_file() or not candidates_path.is_file():
        raise PrincipleWorkflowGateError("Principle set and candidate list must be frozen before hidden-answer validation")
    frozen = FrozenReactionPrincipleSet.model_validate(_load_json(frozen_path, "frozen principles"))
    candidates = [ExperimentCandidate.model_validate(row) for row in _items(_load_json(candidates_path, "frozen candidates"), "candidates")]
    principle_digest = hashlib.sha256(frozen_path.read_bytes()).hexdigest()
    candidate_digest = candidate_list_digest(candidates)
    if not candidates or any(
        item.freeze_status != "frozen"
        or item.principle_digest != principle_digest
        or item.scoring_digest != frozen.scoring_digest
        or item.candidate_list_digest != candidate_digest
        for item in candidates
    ):
        raise PrincipleWorkflowGateError("frozen candidate list is not digest-linked to the frozen Principle set")
    baseline = _load_json(_artifact_path(output_root, config, "validation_baseline_path", "derived/principles/validation_baseline.json"), "validation baseline")
    outcomes_payload = _load_json(_artifact_path(output_root, config, "validation_outcomes_path", "derived/principles/validation_outcomes.json"), "hidden validation outcomes")
    outcomes = [classify_outcome(row) for row in _items(outcomes_payload, "outcomes")]
    try:
        metrics = evaluate_predictions(candidates, outcomes, baseline, frozen_principle_digest=principle_digest, candidate_digest=candidate_digest, precision_k=int(config.get("precision_k", 10)))
    except ValidationGateError as exc:
        raise PrincipleWorkflowGateError(str(exc)) from exc
    destination = _artifact_path(output_root, config, "validation_metrics_path", "derived/principles/validation_metrics.json")
    _atomic_json(destination, metrics.model_dump(mode="json"))
    result = {"status": "complete", "evaluated_outcome_count": len(outcomes)}
    _set_phase(output_root, "validate", result)
    return result


def _run_report(output_root: Path, config: Mapping[str, object]) -> dict[str, object]:
    modeling = config.get("principle_modeling")
    limits = modeling if isinstance(modeling, Mapping) else {}
    markdown_path, json_path = write_principle_report(
        output_root,
        max_assessments=int(limits.get("max_assessments", 80)),
        max_per_paper=int(limits.get("max_per_paper", 3)),
    )
    report_payload = _safe_json(json_path) or {}
    report_status = str(
        report_payload.get("report_status", "provisional_unreviewed")
    )
    result = {
        "status": report_status,
        "markdown_path": str(markdown_path),
        "json_path": str(json_path),
    }
    _set_phase(output_root, "report", result)
    return result


def run_principle_workflow(
    config_path: Path,
    source_root: Path,
    output_root: Path,
    phase: str,
    *,
    live: bool = False,
    client: object | None = None,
) -> dict[str, object]:
    """Run one bounded phase while preserving already-completed local artifacts."""

    # Keep the established v2 entry point source-compatible while exposing the
    # isolated v3 orchestrator through the same public workflow surface.  The
    # import is lazy so v2 callers never load v3-only dependencies or artifacts.
    from pipeline.v3_workflow import PHASES as V3_PHASES, run_v3_workflow

    # Overlapping names (status/validate) remain v2 unless the supplied
    # configuration explicitly identifies a v3 brief.  This preserves the
    # legacy API while allowing the new phase names through this entry point.
    is_v3_config = False
    if phase in V3_PHASES:
        try:
            raw_config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            is_v3_config = isinstance(raw_config, dict) and (
                raw_config.get("version") == "3.0"
                or (
                    isinstance(raw_config.get("exploration_brief"), dict)
                    and raw_config["exploration_brief"].get("version") == "3.0"
                )
            )
        except (OSError, yaml.YAMLError):
            is_v3_config = False
    if phase in V3_PHASES and is_v3_config:
        return run_v3_workflow(
            config_path,
            source_root,
            output_root,
            phase,
            live=live,
            client=client,
        )

    if phase not in PHASES:
        raise PrincipleWorkflowError(f"unknown workflow phase: {phase}")
    config_path = config_path.resolve()
    source_root = source_root.resolve()
    output_root = output_root.resolve()
    if phase == "status":
        result = build_principle_status(output_root)
        _set_phase(output_root, "status", {"status": "complete"})
        return result
    config = _load_config(config_path)
    if phase == "inventory":
        return _run_inventory(output_root)
    if phase == "seed":
        return _run_seed(
            config_path,
            source_root,
            output_root,
            config,
            live=live,
            client=client,
        )
    if phase in {"normalize-smoke", "normalize"}:
        return _normalize(config_path, output_root, config, phase, live=live, client=client)
    if phase in {"transfer-smoke", "transfer"}:
        return _run_semantic_transfer(
            config_path,
            output_root,
            config,
            phase,
            live=live,
            client=client,
        )
    if phase == "induce":
        return _run_induce(output_root, config, live=live, client=client)
    if phase == "report":
        return _run_report(output_root, config)
    if phase == "rank":
        return _run_rank(
            config_path, output_root, config, live=live, client=client
        )
    if phase == "freeze":
        return _run_freeze(output_root, config)
    return _run_validate(output_root, config)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config/principle_workflow.yaml"))
    parser.add_argument("--source-root", type=Path, default=Path.cwd())
    parser.add_argument("--output-root", type=Path, default=Path.cwd())
    parser.add_argument("--phase", choices=PHASES, required=True)
    parser.add_argument("--live", action="store_true", help="Permit the opt-in normalization API call.")
    args = parser.parse_args()
    result = run_principle_workflow(args.config, args.source_root, args.output_root, args.phase, live=args.live)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

"""Resumable, namespace-isolated orchestration for the v3 workflow.

The scientific implementations remain in Tasks 2--12.  This module owns only
phase ordering, cache identity, resumability, and the public CLI/API boundary.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping

import yaml

from pipeline.evidence_registry import _atomic_json
from pipeline.v3_freeze import (
    freeze_manifest_digest,
    freeze_manifest_path,
    freeze_stage_one,
    freeze_stage_three,
    freeze_stage_two,
    verify_freeze_chain,
)
from pipeline.v3_models import V3BriefError, load_v3_brief, v3_brief_digest
from pipeline.v3_validation import (
    build_validation_readiness,
    evaluate_retrospective_reveal,
)
from pipeline.validation_study import ValidationReadiness


PHASES = (
    "status",
    "prepare",
    "freeze-1",
    "retrieve-seed",
    "discover",
    "retrieve-hypotheses",
    "saturate",
    "freeze-2",
    "evaluate",
    "diagnostics",
    "freeze-3",
    "reveal",
    "validate",
    "electrophile-expand",
)
_V3_NAMESPACE = Path("derived/principles_v3")
_MANIFEST = _V3_NAMESPACE / "manifest.json"
_FREEZE_FOR_PHASE = {
    "retrieve-seed": "Freeze 1",
    "discover": "Freeze 1",
    "retrieve-hypotheses": "Freeze 1",
    "saturate": "Freeze 1",
    "freeze-2": "Freeze 1",
    "evaluate": "Freeze 2",
    "diagnostics": "Freeze 2",
    "freeze-3": "Freeze 2",
    "reveal": "Freeze 3",
    "validate": "Freeze 3",
    "electrophile-expand": "Freeze 3",
}
_LIVE_PHASES = frozenset(
    {"retrieve-seed", "discover", "retrieve-hypotheses", "saturate", "evaluate", "diagnostics"}
)
_PHASE_DEPENDENCIES: Mapping[str, tuple[str, ...]] = {
    "freeze-1": ("prepare",),
    "retrieve-seed": ("prepare", "freeze-1"),
    "discover": ("prepare", "freeze-1", "retrieve-seed"),
    "retrieve-hypotheses": ("discover",),
    "saturate": ("discover", "retrieve-hypotheses"),
    "freeze-2": ("freeze-1", "saturate"),
    "evaluate": ("freeze-2",),
    "diagnostics": ("evaluate",),
    "freeze-3": ("freeze-2", "evaluate", "diagnostics"),
    "reveal": ("freeze-3",),
    "validate": ("freeze-3", "reveal"),
    "electrophile-expand": ("validate",),
}


class V3WorkflowError(RuntimeError):
    """Raised when a v3 workflow input or operation is invalid."""


class V3WorkflowGateError(V3WorkflowError):
    """Raised when phase ordering or explicit authorization is missing."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_digest(source_root: Path, output_root: Path) -> str:
    """Bind source identity without feeding v3's own mutable outputs back in."""

    rows: list[tuple[str, str]] = []
    excluded = (output_root / _V3_NAMESPACE).resolve()
    if source_root.is_file():
        return _file_digest(source_root)
    for path in sorted(source_root.rglob("*")):
        if not path.is_file():
            continue
        if "sealed" in path.name.casefold() and "registry" in path.name.casefold():
            continue
        lexical = path.absolute()
        try:
            lexical.relative_to(excluded)
        except ValueError:
            pass
        else:
            continue
        relative = path.relative_to(source_root).as_posix()
        digest = (
            hashlib.sha256(str(path.readlink()).encode()).hexdigest()
            if path.is_symlink()
            else _file_digest(path)
        )
        rows.append((relative, digest))
    return _digest(rows)


def _existing_v3_artifacts(root: Path) -> dict[str, str]:
    namespace = root / _V3_NAMESPACE
    ignored = {"manifest.json", "electrophile_expand.json"}
    return {
        path.relative_to(namespace).as_posix(): _file_digest(path)
        for path in sorted(namespace.rglob("*"))
        if path.is_file() and path.name not in ignored
    }


def _jsonable(value: object) -> object:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bytes):
        return hashlib.sha256(value).hexdigest()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items() if key != "operation"}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return {"type": f"{type(value).__module__}.{type(value).__qualname__}"}


def _phase_input_digest(value: object) -> str:
    """Hash typed values and the bytes of every explicit artifact path."""

    def material(item: object) -> object:
        if isinstance(item, Path):
            resolved = item.resolve()
            return {
                "path": str(resolved),
                "sha256": _file_digest(resolved) if resolved.is_file() else None,
            }
        if hasattr(item, "model_dump"):
            return material(item.model_dump(mode="python"))
        if isinstance(item, Mapping):
            return {
                str(key): material(child)
                for key, child in item.items()
                if key != "operation"
            }
        if isinstance(item, (list, tuple)):
            return [material(child) for child in item]
        return _jsonable(item)

    return _digest(material(value))


def _record_failure(
    root: Path, phase: str, upstream: Mapping[str, str], exc: Exception
) -> None:
    _phase_record(
        root,
        phase,
        status="failed",
        reason=str(exc),
        resumable=True,
        upstream_digests=dict(upstream),
    )


def _phase_payload(client: object | None, phase: str) -> Mapping[str, object]:
    if isinstance(client, Mapping):
        payload = client.get(phase)
    else:
        provider = getattr(client, "v3_workflow_inputs", None)
        payload = provider(phase) if callable(provider) else None
    if not isinstance(payload, Mapping):
        raise V3WorkflowGateError(f"{phase} requires typed Task 2-12 workflow inputs")
    return payload


def _dependency_digests(root: Path, phase: str) -> dict[str, str]:
    phases = _load_manifest(root).get("phases", {})
    result: dict[str, str] = {}
    if not isinstance(phases, Mapping):
        return result
    for dependency in _PHASE_DEPENDENCIES.get(phase, ()):
        record = phases.get(dependency)
        if not isinstance(record, Mapping) or record.get("status") != "complete":
            continue
        digest = record.get("artifact_digest") or record.get("freeze_digest")
        if isinstance(digest, str):
            result[f"phase:{dependency}"] = digest
    return result


def _safe_json(path: Path) -> dict[str, object] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _load_config(path: Path) -> dict[str, object]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise V3WorkflowError(f"workflow config is unavailable: {path}") from exc
    if not isinstance(value, dict):
        raise V3WorkflowError("workflow configuration must contain a mapping")
    _reject_v2_config_inputs(value)
    try:
        load_v3_brief(value)
    except V3BriefError as exc:
        raise V3WorkflowError(str(exc)) from exc
    return value


def _reject_v2_config_inputs(value: object, key_path: str = "config") -> None:
    """Reject explicit v2 artifact/cache paths before they can be loaded."""

    forbidden = (
        "derived/principles/coverage_audit.json",
        "derived/principles/family_predictions.json",
        "derived/principles/provisional_candidates.json",
        "derived/principles/chemical_space",
        "derived/chemical_space",
    )
    if isinstance(value, Mapping):
        for key, item in value.items():
            _reject_v2_config_inputs(item, f"{key_path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_v2_config_inputs(item, f"{key_path}[{index}]")
        return
    if isinstance(value, str):
        normalized = value.replace("\\", "/")
        if any(marker in normalized for marker in forbidden):
            raise V3WorkflowError(f"v2 artifact/cache path is not valid v3 input: {key_path}")
        if any(part == ".." for part in Path(value).parts):
            raise V3WorkflowError(f"path traversal is not valid v3 input: {key_path}")


def _root(output_root: Path) -> Path:
    root = output_root.resolve()
    namespace = (root / _V3_NAMESPACE).resolve()
    namespace.mkdir(parents=True, exist_ok=True)
    return root


def _manifest_path(root: Path) -> Path:
    return root / _MANIFEST


def _load_manifest(root: Path) -> dict[str, object]:
    value = _safe_json(_manifest_path(root)) or {}
    phases = value.get("phases")
    if not isinstance(phases, dict):
        phases = {}
    return {"version": 3, "namespace": _V3_NAMESPACE.as_posix(), "phases": phases, "updated_at": value.get("updated_at", _now())}


def _save_manifest(root: Path, manifest: dict[str, object]) -> None:
    manifest["updated_at"] = _now()
    _atomic_json(_manifest_path(root), manifest)


def _phase_record(root: Path, phase: str, **payload: object) -> dict[str, object]:
    manifest = _load_manifest(root)
    phases = manifest["phases"]
    assert isinstance(phases, dict)
    record = {**payload, "updated_at": _now()}
    phases[phase] = record
    _save_manifest(root, manifest)
    return record


def _assert_no_v2_path(path: Path, label: str) -> None:
    resolved = path.resolve()
    parts = resolved.parts
    if "derived" in parts:
        index = parts.index("derived")
        tail = parts[index + 1 :]
        if tail and tail[0] == "principles":
            raise V3WorkflowError(f"v2 artifact namespace is not valid v3 input: {label}")
        if any(part in {"chemical_space", "chemical-space", "chemical_space_cache"} for part in tail):
            raise V3WorkflowError(f"v2 chemical-space cache is not valid v3 input: {label}")


def _required_freeze(
    root: Path, phase: str, payload: Mapping[str, object] | None = None
) -> str | None:
    stage = _FREEZE_FOR_PHASE.get(phase)
    if stage is None:
        return None
    path = freeze_manifest_path(root, stage)
    if not path.is_file():
        _phase_record(root, phase, status="failed", reason=f"{phase} requires verified {stage}", resumable=True, upstream_digests={})
        raise V3WorkflowGateError(f"{phase} requires verified {stage}")
    try:
        digest = freeze_manifest_digest(root, stage)
        if stage == "Freeze 3":
            policy = payload.get("leakage_policy") if payload is not None else None
            if policy is None:
                raise ValueError("Freeze 3 verification requires leakage policy")
            verification = verify_freeze_chain(root, digest, policy)
            if (
                not verification.valid
                or verification.verified_stages != ("Freeze 1", "Freeze 2", "Freeze 3")
                or verification.manifest_digests.get("Freeze 3") != digest
            ):
                raise ValueError("Freeze 3 chain verification failed")
    except Exception as exc:  # malformed or replaced manifest
        _phase_record(root, phase, status="failed", reason=f"{phase} requires verified {stage}", resumable=True, upstream_digests={})
        raise V3WorkflowGateError(f"{phase} requires verified {stage}") from exc
    if len(digest) != 64:
        raise V3WorkflowGateError(f"{phase} requires verified {stage}")
    return digest


def _status(root: Path) -> dict[str, object]:
    manifest = _load_manifest(root)
    phases = manifest.get("phases", {})
    summary: dict[str, object] = {
        "namespace": _V3_NAMESPACE.as_posix(),
        "manifest": str(_manifest_path(root)),
        "phases": phases if isinstance(phases, dict) else {},
    }
    # Deliberately inspect only v3 metadata; never open the sealed registry.
    freezes = {}
    for stage in ("Freeze 1", "Freeze 2", "Freeze 3"):
        path = freeze_manifest_path(root, stage)
        if path.is_file():
            try:
                freezes[stage] = {"present": True, "digest": freeze_manifest_digest(root, stage)}
            except Exception:
                freezes[stage] = {"present": False}
    summary["freezes"] = freezes
    return summary


def _run_bounded_phase(
    root: Path,
    phase: str,
    *,
    live: bool,
    upstream: Mapping[str, str],
    operation: Callable[[], object],
) -> dict[str, object]:
    prior = _load_manifest(root).get("phases", {})
    if isinstance(prior, dict):
        previous = prior.get(phase)
        if isinstance(previous, dict) and previous.get("status") == "complete" and previous.get("upstream_digests") == dict(upstream):
            artifact_name = previous.get("artifact")
            expected_digest = previous.get("artifact_digest")
            if isinstance(artifact_name, str) and isinstance(expected_digest, str):
                artifact = Path(artifact_name)
                if artifact.is_file() and hashlib.sha256(artifact.read_bytes()).hexdigest() == expected_digest:
                    return previous
    if phase in _LIVE_PHASES and not live:
        record = _phase_record(
            root,
            phase,
            status="failed",
            reason="live=True is required for a model/network/cache miss",
            resumable=True,
            upstream_digests=dict(upstream),
        )
        raise V3WorkflowGateError("live=True is required for this phase")
    try:
        result = operation()
    except Exception as exc:
        _phase_record(root, phase, status="failed", reason=str(exc), resumable=True, upstream_digests=dict(upstream))
        raise
    artifact = root / _V3_NAMESPACE / f"{phase.replace('-', '_')}.json"
    _atomic_json(artifact, _jsonable(result))
    return _phase_record(
        root,
        phase,
        status="complete",
        artifact=str(artifact),
        artifact_digest=hashlib.sha256(artifact.read_bytes()).hexdigest(),
        upstream_digests=dict(upstream),
        resumable=False,
    )


def run_v3_workflow(
    config_path: Path,
    source_root: Path,
    output_root: Path,
    phase: str,
    *,
    live: bool = False,
    client: object | None = None,
) -> dict[str, object]:
    """Run one bounded v3 phase and persist a resumable manifest record."""

    if phase not in PHASES:
        raise V3WorkflowError(f"unknown workflow phase: {phase}")
    config_path = config_path.resolve()
    source_root = source_root.resolve()
    root = _root(output_root)
    _assert_no_v2_path(config_path, "config")
    _assert_no_v2_path(source_root, "source_root")
    _assert_no_v2_path(root, "output_root")
    if phase == "status":
        result = _status(root)
        _phase_record(root, phase, status="complete", resumable=False, upstream_digests={})
        return result
    config = _load_config(config_path)
    brief = load_v3_brief(config)
    brief_digest = v3_brief_digest(brief)
    source_digest = _source_digest(source_root, root)
    if phase == "prepare":
        artifact = root / _V3_NAMESPACE / "exploration_brief.json"
        _atomic_json(artifact, {**brief.model_dump(mode="json"), "digest": brief_digest})
        return _phase_record(
            root,
            phase,
            status="complete",
            artifact=str(artifact),
            artifact_digest=_file_digest(artifact),
            brief_digest=brief_digest,
            upstream_digests={"source_root": source_digest},
        )
    if phase == "freeze-1":
        prior = _load_manifest(root).get("phases", {})
        prepared = prior.get("prepare") if isinstance(prior, dict) else None
        if not isinstance(prepared, dict) or prepared.get("status") != "complete":
            _phase_record(root, phase, status="failed", reason="freeze-1 requires completed prepare", resumable=True, upstream_digests={"brief": brief_digest})
            raise V3WorkflowGateError("freeze-1 requires completed prepare")
    preliminary_payload: Mapping[str, object] = {}
    if isinstance(client, Mapping) and isinstance(client.get(phase), Mapping):
        preliminary_payload = client[phase]
    elif callable(getattr(client, "v3_workflow_inputs", None)):
        candidate = client.v3_workflow_inputs(phase)
        if isinstance(candidate, Mapping):
            preliminary_payload = candidate
    freeze_digest = _required_freeze(root, phase, preliminary_payload)
    payload = _phase_payload(client, phase)
    upstream = {
        "brief": brief_digest,
        "source_root": source_digest,
        "phase_inputs": _phase_input_digest(payload),
        **_dependency_digests(root, phase),
    }
    if freeze_digest:
        upstream[_FREEZE_FOR_PHASE[phase].lower().replace(" ", "_")] = freeze_digest
    if phase == "freeze-1":
        inputs = payload.get("inputs")
        try:
            manifest = freeze_stage_one(root, inputs)
        except Exception as exc:
            _record_failure(root, phase, upstream, exc)
            raise
        digest = freeze_manifest_digest(root, "Freeze 1")
        return _phase_record(
            root,
            phase,
            status="complete",
            artifact=str(freeze_manifest_path(root, "Freeze 1")),
            artifact_digest=digest,
            freeze_digest=digest,
            freeze_manifest=_jsonable(manifest),
            upstream_digests=upstream,
            resumable=False,
        )
    if phase == "freeze-2":
        try:
            manifest = freeze_stage_two(root, payload.get("taxonomy"), payload.get("saturation"))
        except Exception as exc:
            _record_failure(root, phase, upstream, exc)
            raise
        digest = freeze_manifest_digest(root, "Freeze 2")
        return _phase_record(
            root,
            phase,
            status="complete",
            artifact=str(freeze_manifest_path(root, "Freeze 2")),
            artifact_digest=digest,
            freeze_digest=digest,
            freeze_manifest=_jsonable(manifest),
            upstream_digests=upstream,
            resumable=False,
        )
    if phase == "freeze-3":
        try:
            manifest = freeze_stage_three(root, payload.get("ranking"), payload.get("diagnostics", ()))
        except Exception as exc:
            _record_failure(root, phase, upstream, exc)
            raise
        digest = freeze_manifest_digest(root, "Freeze 3")
        policy = payload.get("leakage_policy")
        verification = verify_freeze_chain(root, digest, policy)
        if not verification.valid:
            raise V3WorkflowGateError("Freeze 3 chain verification failed")
        return _phase_record(
            root,
            phase,
            status="complete",
            artifact=str(freeze_manifest_path(root, "Freeze 3")),
            artifact_digest=digest,
            freeze_digest=digest,
            freeze_manifest=_jsonable(manifest),
            upstream_digests=upstream,
            resumable=False,
        )
    if phase == "reveal":
        if payload.get("reveal_decision") != "reveal":
            _phase_record(root, phase, status="failed", reason="reveal requires explicit reveal authorization", resumable=True, upstream_digests=upstream)
            raise V3WorkflowGateError("reveal requires explicit reveal authorization")
        try:
            result = evaluate_retrospective_reveal(
                root=root,
                registry_path=Path(payload["registry_path"]),
                taxonomy=payload.get("taxonomy"),
                ranking=payload.get("ranking"),
                diagnostics=payload.get("diagnostics", ()),
                trusted_freeze_three_digest=freeze_digest,
                leakage_policy=payload.get("leakage_policy"),
                registry_salt=payload.get("registry_salt"),
                reveal_decision="reveal",
                expected_structure_factory=payload.get("expected_structure_factory"),
            )
        except Exception as exc:
            _record_failure(root, phase, upstream, exc)
            raise
        artifact = root / _V3_NAMESPACE / "retrospective_validation.json"
        _atomic_json(artifact, _jsonable(result))
        return _phase_record(root, phase, status="complete", artifact=str(artifact), artifact_digest=_file_digest(artifact), upstream_digests=upstream, resumable=False)
    if phase == "validate":
        try:
            result = build_validation_readiness(
                root,
                historical_negatives=payload.get("historical_negatives", ()),
                trusted_freeze_three_digest=freeze_digest,
                leakage_policy=payload.get("leakage_policy"),
                trusted_historical_negative_digest=payload.get("trusted_historical_negative_digest"),
                negative_evidence_resolver=payload.get("negative_evidence_resolver"),
                trusted_negative_evidence_resolver_digest=payload.get("trusted_negative_evidence_resolver_digest"),
            )
        except Exception as exc:
            _record_failure(root, phase, upstream, exc)
            raise
        artifact = root / _V3_NAMESPACE / "validation_readiness.json"
        _atomic_json(artifact, _jsonable(result))
        return _phase_record(root, phase, status="complete", artifact=str(artifact), artifact_digest=_file_digest(artifact), upstream_digests=upstream, resumable=False)
    if phase == "electrophile-expand":
        readiness_path = root / _V3_NAMESPACE / "validation_readiness.json"
        readiness_payload = _safe_json(readiness_path)
        try:
            readiness = ValidationReadiness.model_validate(readiness_payload)
        except Exception as exc:
            raise V3WorkflowGateError("electrophile expansion requires actual validation-readiness") from exc
        review_path = root / _V3_NAMESPACE / "validation_readiness_review.json"
        review = _safe_json(review_path)
        readiness_digest = _file_digest(readiness_path)
        if (
            readiness.fixed_scope != "SR001_nucleophile_condition"
            or not isinstance(review, dict)
            or review.get("decision") != "accepted"
            or review.get("readiness_digest") != readiness_digest
            or review.get("fixed_scope") != readiness.fixed_scope
        ):
            _phase_record(root, phase, status="failed", reason="electrophile expansion requires reviewed Phase 1 validation-readiness", resumable=True, upstream_digests=upstream)
            raise V3WorkflowGateError("electrophile expansion requires reviewed Phase 1 validation-readiness")
        upstream["validation_readiness"] = readiness_digest
        upstream["validation_readiness_review"] = _file_digest(review_path)
    operation = payload.get("operation")
    if not callable(operation):
        raise V3WorkflowGateError(f"{phase} requires a bounded Task 2-12 operation")
    if phase == "electrophile-expand":
        fixed_artifacts = _existing_v3_artifacts(root)
        bounded_operation = operation

        def immutable_operation() -> object:
            result = bounded_operation()
            current = _existing_v3_artifacts(root)
            if any(current.get(path) != digest for path, digest in fixed_artifacts.items()):
                raise V3WorkflowGateError(
                    "electrophile expansion cannot rewrite fixed-SR001 artifacts"
                )
            return result

        operation = immutable_operation
    return _run_bounded_phase(
        root,
        phase,
        live=live,
        upstream=upstream,
        operation=operation,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, default=Path.cwd())
    parser.add_argument("--output-root", type=Path, default=Path.cwd())
    parser.add_argument("--phase", choices=PHASES, required=True)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run_v3_workflow(args.config, args.source_root, args.output_root, args.phase, live=args.live), indent=2, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()

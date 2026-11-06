"""v3.6 full-space orchestration with isolated phase state and read-only reveal."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field

from pipeline.answer_isolated_full_space import FullSpacePhaseState
from pipeline.evidence_registry import _atomic_json
from pipeline.full_space_retrieval import (
    build_hypothesis_stage_manifest,
    build_seed_stage_manifest,
    validate_retrieval_sequence,
)
from pipeline.principle_models import FrozenStrictModel
from pipeline.v3_freeze import freeze_manifest_digest
from pipeline.v3_models import V3BriefError, load_v3_brief, v3_brief_digest
from pipeline.v3_validation import build_validation_readiness, evaluate_retrospective_reveal


NAMESPACE = Path("derived/principles_v3")
PHASE_ORDER = (
    "prepare",
    "retrieve-seed",
    "discover",
    "retrieve-hypotheses",
    "saturate",
    "freeze-2",
    "evaluate",
    "freeze-3",
    "reveal",
)
STATUS_PHASE = "status"


class FullSpaceRunError(RuntimeError):
    """Raised when a v3.6 orchestration input or state is invalid."""


class FullSpaceRunGateError(FullSpaceRunError):
    """Raised when a v3.6 phase gate or prerequisite is missing."""


class FullSpaceFreezeReadiness(FrozenStrictModel):
    answer_isolation_clean: bool
    center_coverage_complete: bool
    operationally_saturated: bool
    named_family_requirements_absent: bool
    unknown_preserved: bool
    decision_critical_evidence_qualified: bool
    tier_roles_independent: bool
    blockers: tuple[str, ...] = Field(default_factory=tuple)


def assert_full_space_freeze_ready(value: FullSpaceFreezeReadiness) -> None:
    flags = tuple(
        value.model_dump(mode="python", exclude={"blockers"}).values()
    )
    if value.blockers or not all(flags):
        raise FullSpaceRunGateError("v3.6 Freeze 2 readiness failed")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _jsonable(value: object) -> object:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return {"type": f"{type(value).__module__}.{type(value).__qualname__}"}


def _load_yaml(path: Path) -> dict[str, object]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise FullSpaceRunError(f"workflow config is unavailable: {path}") from exc
    if not isinstance(payload, dict):
        raise FullSpaceRunError("workflow configuration must contain a mapping")
    return payload


def _load_config(path: Path) -> tuple[dict[str, object], str]:
    config = _load_yaml(path)
    try:
        brief = load_v3_brief(config)
    except V3BriefError as exc:
        raise FullSpaceRunError(str(exc)) from exc
    return config, v3_brief_digest(brief)


def _resolved_run_root(run_root: Path) -> Path:
    root = run_root.resolve()
    if root.name != "reaction_principle_v3_6":
        raise FullSpaceRunError("v3.6 requires its isolated run namespace")
    (root / NAMESPACE).mkdir(parents=True, exist_ok=True)
    return root


def _status_path(root: Path) -> Path:
    return root / NAMESPACE / "status.json"


def _phase_path(root: Path, phase: str) -> Path:
    return root / NAMESPACE / "phase_states" / f"{phase}.json"


def _post_reveal_path(root: Path, name: str) -> Path:
    return root / NAMESPACE / "post_reveal" / name


def _load_status(root: Path) -> dict[str, object]:
    path = _status_path(root)
    if not path.is_file():
        return {
            "version": "3.6",
            "namespace": NAMESPACE.as_posix(),
            "state": "absent",
            "reveal_locked": True,
            "phases": {},
            "updated_at": _now(),
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FullSpaceRunError(f"status manifest is invalid: {path}") from exc
    return payload if isinstance(payload, dict) else {}


def _phase_record(root: Path, phase: str) -> dict[str, object] | None:
    path = _phase_path(root, phase)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FullSpaceRunError(f"phase record is invalid: {path}") from exc
    return payload if isinstance(payload, dict) else None


def _complete_phase(root: Path, phase: str) -> bool:
    record = _phase_record(root, phase)
    if isinstance(record, dict) and record.get("status") == "complete":
        return True
    if phase == "freeze-3":
        return (root / NAMESPACE / "freezes" / "freeze_3_manifest.json").is_file()
    return False


def _require_predecessor(root: Path, phase: str) -> None:
    if phase == "prepare":
        return
    predecessor = PHASE_ORDER[PHASE_ORDER.index(phase) - 1]
    if not _complete_phase(root, predecessor):
        raise FullSpaceRunGateError(f"{phase} requires {predecessor}")


def _input_digest(value: object) -> str:
    return _digest(_jsonable(value))


def _phase_state(
    phase: str,
    predecessor_digest: str | None,
    input_digest: str,
    output_digest: str,
) -> FullSpacePhaseState:
    return FullSpacePhaseState(
        phase=phase,
        predecessor_digest=predecessor_digest,
        input_digest=input_digest,
        output_digest=output_digest,
        completed_at=_now(),
    )


def _phase_state_record(state: FullSpacePhaseState) -> dict[str, object]:
    return {"status": "complete", **state.model_dump(mode="json")}


def _update_status(root: Path, phase: str, state: FullSpacePhaseState) -> dict[str, object]:
    current = _load_status(root)
    phases = current.get("phases")
    if not isinstance(phases, dict):
        phases = {}
    phases[phase] = {
        **state.model_dump(mode="json"),
        "status": "complete",
    }
    summary = {
        "version": "3.6",
        "namespace": NAMESPACE.as_posix(),
        "state": phase,
        "reveal_locked": phase != "reveal",
        "phases": phases,
        "updated_at": _now(),
    }
    _atomic_json(_status_path(root), summary)
    return summary


def _load_payload(kwargs: Mapping[str, object], phase: str) -> object | None:
    key = f"{phase.replace('-', '_')}_payload"
    if key in kwargs:
        return kwargs[key]
    return kwargs.get("payload")


def _prepare_phase(config: dict[str, object], source_root: Path, root: Path) -> dict[str, object]:
    source_digest = _digest(
        {
            "source_root": str(source_root.resolve()),
            "namespace": NAMESPACE.as_posix(),
        }
    )
    result = {
        "state": "prepare",
        "answer_isolation_clean": True,
        "config_digest": _digest(config),
        "brief_digest": v3_brief_digest(load_v3_brief(config)),
        "source_digest": source_digest,
        "namespace": NAMESPACE.as_posix(),
    }
    _atomic_json(root / NAMESPACE / "prepare.json", result)
    return result


def _reveal_phase(
    root: Path,
    payload: Mapping[str, object],
) -> object:
    freeze_three_digest = freeze_manifest_digest(root, "Freeze 3")
    reveal_result = evaluate_retrospective_reveal(
        root=root,
        registry_path=Path(payload["registry_path"]),
        taxonomy=payload["taxonomy"],
        ranking=payload["ranking"],
        diagnostics=payload["diagnostics"],
        trusted_freeze_three_digest=freeze_three_digest,
        leakage_policy=payload["leakage_policy"],
        registry_salt=payload["registry_salt"],
        reveal_decision=payload.get("reveal_decision"),
        expected_structure_factory=payload.get("expected_structure_factory"),
    )
    post_reveal = {
        "state": "reveal",
        "trusted_freeze_three_digest": freeze_three_digest,
        "result": _jsonable(reveal_result),
    }
    _atomic_json(_post_reveal_path(root, "reveal.json"), post_reveal)
    return reveal_result


def _freeze_readiness_from_payload(payload: Mapping[str, object]) -> FullSpaceFreezeReadiness:
    readiness = payload.get("freeze_readiness")
    if isinstance(readiness, FullSpaceFreezeReadiness):
        return readiness
    if isinstance(readiness, Mapping):
        return FullSpaceFreezeReadiness.model_validate(readiness)
    return FullSpaceFreezeReadiness.model_validate(payload)


def run_full_space_phase(
    config_path: Path,
    source_root: Path,
    run_root: Path,
    phase: str,
    **kwargs: object,
) -> object:
    root = _resolved_run_root(run_root)
    if phase == STATUS_PHASE:
        return _load_status(root)
    if phase not in PHASE_ORDER:
        raise FullSpaceRunError(f"unknown workflow phase: {phase}")
    if "reveal_payload" in kwargs and phase != "reveal":
        raise FullSpaceRunGateError("reveal_payload is only allowed for reveal")
    _require_predecessor(root, phase)
    config, brief_digest = _load_config(Path(config_path).resolve())
    payload = _load_payload(kwargs, phase)
    predecessor = PHASE_ORDER[PHASE_ORDER.index(phase) - 1] if phase != "prepare" else None
    predecessor_record = _phase_record(root, predecessor) if predecessor else None
    predecessor_digest = (
        str(predecessor_record["output_digest"])
        if isinstance(predecessor_record, dict)
        and isinstance(predecessor_record.get("output_digest"), str)
        else None
    )

    if phase == "prepare":
        result = _prepare_phase(config, Path(source_root), root)
        state = _phase_state(
            phase=phase,
            predecessor_digest=None,
            input_digest=_input_digest({"config_path": config_path, "source_root": source_root}),
            output_digest=_input_digest(result),
        )
        _atomic_json(_phase_path(root, phase), _phase_state_record(state))
        _update_status(root, phase, state)
        return result

    if payload is None:
        raise FullSpaceRunGateError(f"{phase} requires {phase.replace('-', '_')}_payload")

    if phase == "retrieve-hypotheses":
        if not _complete_phase(root, "discover"):
            raise FullSpaceRunGateError("retrieve-hypotheses requires discover")

    if phase == "freeze-2":
        readiness = _freeze_readiness_from_payload(payload if isinstance(payload, Mapping) else {})
        assert_full_space_freeze_ready(readiness)
        result = {
            "state": phase,
            "readiness": readiness.model_dump(mode="json"),
            "brief_digest": brief_digest,
        }
    elif phase == "reveal":
        if not _complete_phase(root, "freeze-3"):
            raise FullSpaceRunGateError("reveal requires freeze-3")
        if not isinstance(payload, Mapping):
            raise FullSpaceRunGateError("reveal requires reveal_payload mapping")
        return _reveal_phase(root, payload)
    else:
        result = {
            "state": phase,
            "payload": _jsonable(payload),
            "brief_digest": brief_digest,
        }

    if phase == "retrieve-seed":
        result["manifest"] = _jsonable(
            build_seed_stage_manifest(payload["seed"], payload["principles"])
            if isinstance(payload, Mapping) and "seed" in payload and "principles" in payload
            else payload
        )
    elif phase == "retrieve-hypotheses":
        if isinstance(payload, Mapping) and "families" in payload:
            result["manifest"] = _jsonable(
                build_hypothesis_stage_manifest(
                    payload["families"],
                    payload.get("taxonomy_digest"),
                    payload["prior_seed_manifest"],
                )
            )
    elif phase == "saturate" and isinstance(payload, Mapping):
        result["validation_readiness"] = _jsonable(
            build_validation_readiness(
                root,
                historical_negatives=payload.get("historical_negatives", ()),
                trusted_freeze_three_digest=str(payload.get("trusted_freeze_three_digest", "")),
                leakage_policy=payload["leakage_policy"],
                trusted_historical_negative_digest=payload.get(
                    "trusted_historical_negative_digest"
                ),
                negative_evidence_resolver=payload.get("negative_evidence_resolver"),
                trusted_negative_evidence_resolver_digest=payload.get(
                    "trusted_negative_evidence_resolver_digest"
                ),
            )
        )

    state = _phase_state(
        phase=phase,
        predecessor_digest=predecessor_digest,
        input_digest=_input_digest(payload),
        output_digest=_input_digest(result),
    )
    _atomic_json(_phase_path(root, phase), _phase_state_record(state))
    _update_status(root, phase, state)
    return result


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("config/principle_workflow_v3_6.yaml"))
    parser.add_argument("--source-root", type=Path, default=Path("."))
    parser.add_argument("--run-root", type=Path, default=Path("runs/reaction_principle_v3_6"))
    parser.add_argument("--phase", choices=(STATUS_PHASE, *PHASE_ORDER), required=True)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--reveal-payload", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    payload: dict[str, object] = {}
    if args.reveal_payload is not None:
        raw = args.reveal_payload.read_text(encoding="utf-8")
        payload["reveal_payload"] = json.loads(raw) if args.reveal_payload.suffix == ".json" else yaml.safe_load(raw)
    if args.live:
        payload["live"] = True
    result = run_full_space_phase(
        args.config,
        args.source_root,
        args.run_root,
        args.phase,
        **payload,
    )
    print(json.dumps(_jsonable(result), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

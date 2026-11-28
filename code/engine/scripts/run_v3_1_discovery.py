"""Run the answer-isolated v3.1 open taxonomy discovery and saturation audit."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import yaml

from pipeline.api_client import ApiClientError, ResponsesClient, read_keychain_secret
from pipeline.evidence_registry import _atomic_json
from pipeline.family_canonicalization import CanonicalTaxonomy, canonicalize_proposals
from pipeline.principle_models import (
    FrozenReactionPrincipleSet,
    TransferabilityAssessment,
)
from pipeline.saturation import audit_mechanism_coverage, evaluate_saturation
from pipeline.taxonomy_discovery import (
    DISCOVERY_CHANNELS,
    TaxonomyDiscoveryContext,
    TaxonomyLaneResult,
    TaxonomyModelInvocationConfig,
    propose_family_lane,
)
from pipeline.v3_models import load_v3_brief


SOURCE_NAMESPACE = Path("derived/principles_v3")
RUN_NAMESPACE = Path("runs/reaction_principle_v3_2")
LANES = ("LANE-SR001-A", "LANE-SR001-B")


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _load_yaml(path: Path) -> dict[str, object]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a mapping in {path}")
    return value


def _current_clean_root(source_root: Path) -> Path:
    manifest = _read_json(source_root / SOURCE_NAMESPACE / "evidence_import_manifest.json")
    if not isinstance(manifest, dict):
        raise ValueError("evidence import manifest is invalid")
    accepted = manifest.get("accepted")
    if not isinstance(accepted, list) or not accepted:
        raise ValueError("evidence import manifest has no accepted evidence")
    first_path = Path(str(accepted[0]["path"]))
    parts = first_path.parts
    index = parts.index("clean_inputs")
    return source_root.joinpath(*parts[: index + 2])


def _selected_assessments(source_root: Path) -> tuple[TransferabilityAssessment, ...]:
    clean_root = _current_clean_root(source_root)
    payload = _read_json(clean_root / "derived/principles/transfer_assessments.json")
    if not isinstance(payload, dict) or not isinstance(payload.get("assessments"), list):
        raise ValueError("transfer assessment artifact is invalid")
    assessments = tuple(
        TransferabilityAssessment.model_validate(row)
        for row in payload["assessments"]
    )
    status_order = {"conditional": 0, "unknown": 1, "non_transferable": 2}

    def key(item: TransferabilityAssessment) -> tuple[int, int, str]:
        total = item.score_components.get("total", 0)
        numeric_total = total if isinstance(total, int) else 0
        return status_order[item.transfer_status], -numeric_total, item.assessment_id

    # The rule is fixed before v3.1 discovery and uses no named-family labels.
    return tuple(sorted(assessments, key=key)[:80])


def _coordinate_vocabulary(config: dict[str, object]) -> dict[str, tuple[str, ...]]:
    raw = config.get("coordinate_vocabulary")
    if not isinstance(raw, dict):
        raise ValueError("coordinate vocabulary is missing")
    result: dict[str, tuple[str, ...]] = {}
    for key, values in raw.items():
        if not isinstance(key, str) or not isinstance(values, list):
            raise ValueError("coordinate vocabulary is invalid")
        result[key] = tuple(str(value) for value in values)
    return result


def _inputs(source_root: Path, workflow_config: Path, coordinate_config: Path):
    workflow = _load_yaml(workflow_config)
    coordinates = _load_yaml(coordinate_config)
    brief = load_v3_brief(workflow)
    frozen = FrozenReactionPrincipleSet.model_validate(
        _read_json(source_root / SOURCE_NAMESPACE / "frozen_principles.json")
    )
    assessments = _selected_assessments(source_root)
    evidence_manifest = _read_json(
        source_root / SOURCE_NAMESPACE / "evidence_import_manifest.json"
    )
    assert isinstance(evidence_manifest, dict)
    evidence_digest = str(evidence_manifest["manifest_digest"])
    return workflow, coordinates, brief, frozen, assessments, evidence_digest


def prepare(
    source_root: Path,
    run_root: Path,
    workflow_config: Path,
    coordinate_config: Path,
) -> dict[str, object]:
    workflow, coordinates, brief, frozen, assessments, evidence_digest = _inputs(
        source_root, workflow_config, coordinate_config
    )
    del workflow, coordinates
    namespace = run_root / SOURCE_NAMESPACE
    namespace.mkdir(parents=True, exist_ok=True)
    record = {
        "version": "3.1",
        "created_at": _now(),
        "answer_isolation": {
            "sealed_registry_read": False,
            "named_family_targets_used": False,
            "withheld_results_used": False,
        },
        "inputs": {
            "workflow_config": str(workflow_config.resolve()),
            "workflow_config_sha256": _sha256(workflow_config),
            "coordinate_config": str(coordinate_config.resolve()),
            "coordinate_config_sha256": _sha256(coordinate_config),
            "evidence_import_manifest_digest": evidence_digest,
            "frozen_principle_source_digest": frozen.source_digest,
            "brief": brief.model_dump(mode="json"),
            "assessment_selection_rule": (
                "conditional first, then unknown, then non-transferable; "
                "descending pre-existing component total; assessment_id tie-break; top 80"
            ),
            "selected_assessment_ids": [item.assessment_id for item in assessments],
        },
    }
    _atomic_json(namespace / "preregistration.json", record)
    return record


def _client() -> ResponsesClient:
    return ResponsesClient(
        "https://cs.jaspervault.pro/v1",
        lambda: read_keychain_secret("reaction-principle-jaspervault", os.environ["USER"]),
        read_timeout_seconds=1200,
    )


def _context(
    source_root: Path,
    run_root: Path,
    workflow_config: Path,
    coordinate_config: Path,
) -> TaxonomyDiscoveryContext:
    workflow, coordinates, brief, frozen, assessments, evidence_digest = _inputs(
        source_root, workflow_config, coordinate_config
    )
    discovery = workflow.get("taxonomy_discovery")
    if not isinstance(discovery, dict):
        raise ValueError("taxonomy discovery configuration is missing")
    return TaxonomyDiscoveryContext(
        brief=brief,
        reviewed_principles=frozen.principles,
        selected_transfer_assessments=assessments,
        retrieval_evidence=(),
        evidence_import_digest=evidence_digest,
        output_root=run_root,
        model_config=TaxonomyModelInvocationConfig(model=str(discovery["model"])),
        prompt_version=str(discovery["prompt_version"]),
        coordinate_vocabulary=_coordinate_vocabulary(coordinates),
    )


def discover_round(
    source_root: Path,
    run_root: Path,
    workflow_config: Path,
    coordinate_config: Path,
    round_id: int,
    *,
    adjudicate: bool,
) -> dict[str, object]:
    preregistration = run_root / SOURCE_NAMESPACE / "preregistration.json"
    if not preregistration.is_file():
        prepare(source_root, run_root, workflow_config, coordinate_config)
    context = _context(source_root, run_root, workflow_config, coordinate_config)
    client = _client()
    completed: list[TaxonomyLaneResult] = []
    failures: list[dict[str, object]] = []
    for lane_id in LANES:
        for channel in DISCOVERY_CHANNELS:
            try:
                completed.append(
                    propose_family_lane(
                        context,
                        client,
                        lane_id=lane_id,
                        round_id=round_id,
                        channel=channel,
                    )
                )
            except ApiClientError as exc:
                failures.append(
                    {
                        "lane_id": lane_id,
                        "channel": channel,
                        "status": "platform_failure_skipped",
                        "error_type": exc.error_type,
                        "error_code": exc.error_code,
                        "http_status": exc.status,
                        "chemical_disposition": "unknown",
                    }
                )
    results = tuple(completed)
    if not results:
        raise RuntimeError("no discovery channel completed in this round")
    taxonomy = canonicalize_proposals(results, client if adjudicate else None)
    artifact = {
        "round_id": round_id,
        "lane_results": [item.model_dump(mode="json") for item in results],
        "taxonomy": taxonomy.model_dump(mode="json"),
        "adjudication": "bounded_model" if adjudicate else "explicit_unresolved",
        "platform_failures": failures,
    }
    _atomic_json(
        run_root / SOURCE_NAMESPACE / "rounds" / f"round_{round_id}.json",
        artifact,
    )
    return artifact


def saturation(run_root: Path, coordinate_config: Path) -> dict[str, object]:
    round_paths = sorted((run_root / SOURCE_NAMESPACE / "rounds").glob("round_*.json"))
    if len(round_paths) < 2:
        raise ValueError("saturation requires at least two completed discovery rounds")
    rounds = tuple(
        CanonicalTaxonomy.model_validate(_read_json(path)["taxonomy"])  # type: ignore[index]
        for path in round_paths
    )
    config = _load_yaml(coordinate_config)
    coverage = audit_mechanism_coverage(rounds[-1], config)
    audit = evaluate_saturation(rounds, coverage, config)
    artifact = {
        "round_count": len(rounds),
        "family_counts": [len(item.families) for item in rounds],
        "coverage": coverage.model_dump(mode="json"),
        "saturation": audit.model_dump(mode="json"),
    }
    _atomic_json(run_root / SOURCE_NAMESPACE / "saturation.json", artifact)
    return artifact


def status(run_root: Path) -> dict[str, object]:
    namespace = run_root / SOURCE_NAMESPACE
    rounds = sorted((namespace / "rounds").glob("round_*.json"))
    result: dict[str, object] = {
        "run_root": str(run_root),
        "preregistered": (namespace / "preregistration.json").is_file(),
        "completed_rounds": [path.stem for path in rounds],
        "saturation_audited": (namespace / "saturation.json").is_file(),
    }
    if (namespace / "saturation.json").is_file():
        result["saturation"] = _read_json(namespace / "saturation.json")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("prepare", "discover", "saturate", "status"), required=True)
    parser.add_argument("--round", type=int)
    parser.add_argument("--adjudicate", action="store_true")
    parser.add_argument("--source-root", type=Path, default=Path.cwd())
    parser.add_argument("--run-root", type=Path, default=Path.cwd() / RUN_NAMESPACE)
    parser.add_argument("--workflow-config", type=Path, default=Path("config/principle_workflow_v3_2.yaml"))
    parser.add_argument("--coordinate-config", type=Path, default=Path("config/mechanism_coordinates_v3_2.yaml"))
    args = parser.parse_args()
    source_root = args.source_root.resolve()
    run_root = args.run_root.resolve()
    workflow_config = args.workflow_config.resolve()
    coordinate_config = args.coordinate_config.resolve()
    if args.phase == "prepare":
        result = prepare(source_root, run_root, workflow_config, coordinate_config)
    elif args.phase == "discover":
        if args.round is None or args.round < 1:
            parser.error("--round must be a positive integer for discover")
        result = discover_round(
            source_root,
            run_root,
            workflow_config,
            coordinate_config,
            args.round,
            adjudicate=args.adjudicate,
        )
    elif args.phase == "saturate":
        result = saturation(run_root, coordinate_config)
    else:
        result = status(run_root)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

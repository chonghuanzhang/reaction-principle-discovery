"""Preregister and run deterministic v3.4 cross-round consolidation."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path
from typing import Any

import yaml

from pipeline.cross_round_consolidation import (
    ConsolidationError,
    ConsolidationPolicy,
    EvidenceFingerprint,
    consolidate_fingerprints,
    fingerprint_proposal,
)
from pipeline.evidence_registry import _atomic_json
from pipeline.taxonomy_discovery import (
    MechanismCoordinateAssignment,
    TaxonomyLaneResult,
)


RUN_ROOT = Path("runs/reaction_principle_v3_4_1")
SOURCE_ROOT = Path("runs/reaction_principle_v3_3/derived/principles_v3")
CONFIG_PATH = Path("config/cross_round_consolidation_v3_4_1.yaml")
_POLICY_FIELDS = frozenset(ConsolidationPolicy.model_fields)


class SourceIntegrityError(RuntimeError):
    """Raised when source or policy bytes change after preregistration."""


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SourceIntegrityError(f"invalid JSON source: {path}") from exc
    if not isinstance(value, dict):
        raise SourceIntegrityError(f"JSON source must be an object: {path}")
    return value


def _read_config(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise SourceIntegrityError(f"invalid v3.4 config: {path}") from exc
    if not isinstance(value, dict):
        raise SourceIntegrityError("v3.4 config must be a mapping")
    return value


def _policy(config: dict[str, Any]) -> ConsolidationPolicy:
    return ConsolidationPolicy.model_validate(
        {key: config[key] for key in _POLICY_FIELDS if key in config}
    )


def _positive_expected(config: dict[str, Any], key: str) -> int:
    value = config.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise SourceIntegrityError(f"{key} must be a positive integer")
    return value


def _global_proposal_id(source_version: str, round_id: int, local_id: str) -> str:
    if source_version == "3.6":
        return f"R{round_id:03d}:{local_id}"
    return local_id


def _source_files(source_root: Path) -> tuple[Path, ...]:
    round_paths = tuple(sorted((source_root / "rounds").glob("round_*.json")))
    return (
        source_root / "preregistration.json",
        *round_paths,
        source_root / "chemical_review.json",
    )


def _source_manifest(source_root: Path) -> dict[str, str]:
    files = _source_files(source_root)
    missing = [str(path) for path in files if not path.is_file()]
    if missing:
        raise SourceIntegrityError(f"missing public v3.3 source files: {missing}")
    return {
        str(path.relative_to(source_root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in files
    }


def _coordinate_contract(
    source_root: Path,
    expected_assignment_count: int,
    expected_source_version: str,
) -> tuple[tuple[MechanismCoordinateAssignment, ...], str]:
    preregistration = _read_json(source_root / "preregistration.json")
    if str(preregistration.get("version")) != expected_source_version:
        raise SourceIntegrityError(
            "source preregistration version does not match consolidation policy"
        )
    inputs = preregistration.get("inputs")
    if not isinstance(inputs, dict):
        raise SourceIntegrityError("v3.3 preregistration lacks inputs")
    raw_assignments = inputs.get("allowed_coordinate_assignments")
    if not isinstance(raw_assignments, list):
        raise SourceIntegrityError("v3.3 preregistration lacks allowed assignments")
    try:
        assignments = tuple(
            MechanismCoordinateAssignment.model_validate(row)
            for row in raw_assignments
        )
    except ValueError as exc:
        raise SourceIntegrityError("invalid v3.3 coordinate assignment") from exc
    keys = {
        tuple(item.model_dump(mode="json").items())
        for item in assignments
    }
    if len(assignments) != expected_assignment_count or len(keys) != len(assignments):
        raise SourceIntegrityError(
            "allowed coordinate assignment count or uniqueness does not match policy"
        )
    assignment_rows = [item.model_dump(mode="json") for item in assignments]
    assignment_digest = _digest(assignment_rows)
    if assignment_digest != inputs.get("allowed_coordinate_assignment_digest"):
        raise SourceIntegrityError("allowed coordinate assignment digest mismatch")
    return assignments, assignment_digest


def _load_fingerprints(
    source_root: Path,
    policy: ConsolidationPolicy,
    config: dict[str, Any],
) -> tuple[
    tuple[EvidenceFingerprint, ...],
    dict[tuple[str, str], tuple[str, ...]],
    tuple[str, ...],
    str,
]:
    expected_rounds = _positive_expected(config, "expected_round_count")
    expected_proposals = _positive_expected(config, "expected_proposal_count")
    expected_assignments = _positive_expected(config, "expected_assignment_count")
    assignments, assignment_digest = _coordinate_contract(
        source_root, expected_assignments, policy.source_version
    )
    allowed = {
        tuple(item.model_dump(mode="json").items())
        for item in assignments
    }
    round_paths = tuple(sorted((source_root / "rounds").glob("round_*.json")))
    if len(round_paths) != expected_rounds:
        raise SourceIntegrityError(
            f"expected {expected_rounds} completed rounds, found {len(round_paths)}"
        )
    fingerprints: list[EvidenceFingerprint] = []
    inherited_rows: list[dict[str, Any]] = []
    for expected_round_id, path in enumerate(round_paths, 1):
        payload = _read_json(path)
        if payload.get("round_id") != expected_round_id:
            raise SourceIntegrityError(f"unexpected round ID in {path}")
        lane_rows = payload.get("lane_results")
        if not isinstance(lane_rows, list):
            raise SourceIntegrityError(f"round lacks lane results: {path}")
        for row in lane_rows:
            try:
                lane = TaxonomyLaneResult.model_validate(row)
            except ValueError as exc:
                raise SourceIntegrityError(f"invalid lane result in {path}") from exc
            if lane.round_id != expected_round_id:
                raise SourceIntegrityError(f"lane round mismatch in {path}")
            for proposal in lane.proposals:
                assignment = proposal.coordinate_assignment
                if assignment is None:
                    raise SourceIntegrityError(
                        f"proposal {proposal.proposal_id} lacks a coordinate assignment"
                    )
                if tuple(assignment.model_dump(mode="json").items()) not in allowed:
                    raise SourceIntegrityError(
                        f"proposal {proposal.proposal_id} uses an assignment outside the allowlist"
                    )
                fingerprints.append(
                    fingerprint_proposal(
                        proposal.model_copy(
                            update={
                                "proposal_id": _global_proposal_id(
                                    policy.source_version,
                                    lane.round_id,
                                    proposal.proposal_id,
                                )
                            }
                        ),
                        lane_id=lane.lane_id,
                        round_id=lane.round_id,
                        channel=lane.channel,
                    )
                )
        taxonomy = payload.get("taxonomy")
        if not isinstance(taxonomy, dict):
            raise SourceIntegrityError(f"round lacks taxonomy: {path}")
        decision_rows = taxonomy.get("decisions", [])
        if not isinstance(decision_rows, list):
            raise SourceIntegrityError(f"taxonomy decisions must be a list: {path}")
        for row in decision_rows:
            if not (
                isinstance(row, dict)
                and row.get("decision") == "merge"
                and row.get("source") == "deterministic"
            ):
                continue
            qualified = dict(row)
            raw_ids = row.get("compared_proposal_ids")
            if isinstance(raw_ids, list):
                qualified["compared_proposal_ids"] = [
                    _global_proposal_id(
                        policy.source_version, expected_round_id, str(proposal_id)
                    )
                    for proposal_id in raw_ids
                ]
            inherited_rows.append(qualified)
    if len(fingerprints) != expected_proposals:
        raise SourceIntegrityError(
            f"expected {expected_proposals} proposals, found {len(fingerprints)}"
        )
    proposal_ids = tuple(item.proposal_id for item in fingerprints)
    if len(proposal_ids) != len(set(proposal_ids)):
        raise SourceIntegrityError("proposal IDs are not unique across source rounds")
    fingerprints_by_id = {item.proposal_id: item for item in fingerprints}
    inherited: dict[tuple[str, str], tuple[str, ...]] = {}
    for row in inherited_rows:
        raw_ids = row.get("compared_proposal_ids")
        raw_evidence = row.get("evidence_ids")
        if not isinstance(raw_ids, list) or len(set(raw_ids)) < 2:
            raise SourceIntegrityError("qualified merge decision has invalid proposal IDs")
        if not isinstance(raw_evidence, list):
            continue
        evidence_ids = tuple(
            sorted(
                {
                    str(value)
                    for value in raw_evidence
                    if any(
                        str(value).startswith(prefix)
                        for prefix in policy.qualifying_evidence_prefixes
                    )
                }
            )
        )
        if not evidence_ids:
            continue
        if not set(raw_ids).issubset(fingerprints_by_id):
            raise SourceIntegrityError("qualified merge cites an unknown proposal")
        round_ids = {fingerprints_by_id[value].round_id for value in raw_ids}
        if len(round_ids) != 1:
            raise SourceIntegrityError("qualified merge spans source rounds")
        for left_id, right_id in combinations(sorted(set(raw_ids)), 2):
            pair = (left_id, right_id)
            inherited[pair] = tuple(
                sorted(set(inherited.get(pair, ())) | set(evidence_ids))
            )
    review = _read_json(source_root / "chemical_review.json")
    raw_blockers = review.get("freeze_2_blockers", [])
    blockers = (
        tuple(str(value) for value in raw_blockers)
        if isinstance(raw_blockers, list)
        else ()
    )
    return tuple(fingerprints), inherited, blockers, assignment_digest


def _namespace(run_root: Path) -> Path:
    return run_root.resolve() / "derived" / "principles_v3"


def prepare(run_root: Path, source_root: Path, config_path: Path) -> Path:
    """Write the immutable v3.4 source and policy contract before consolidation."""

    source_root = source_root.resolve()
    config_path = config_path.resolve()
    config = _read_config(config_path)
    policy = _policy(config)
    fingerprints, inherited, _, assignment_digest = _load_fingerprints(
        source_root, policy, config
    )
    source_manifest = _source_manifest(source_root)
    source_digest = _digest(source_manifest)
    policy_digest = _digest(config)
    artifact = {
        "version": policy.version,
        "source_version": policy.source_version,
        "created_at": datetime.now(UTC).isoformat(),
        "round_count": len({item.round_id for item in fingerprints}),
        "proposal_count": len(fingerprints),
        "allowed_coordinate_assignment_count": _positive_expected(
            config, "expected_assignment_count"
        ),
        "allowed_coordinate_assignment_digest": assignment_digest,
        "source_manifest": source_manifest,
        "source_digest": source_digest,
        "policy": policy.model_dump(mode="json"),
        "policy_digest": policy_digest,
        "inherited_merge_pair_count": len(inherited),
        "inherited_merge_pair_digest": _digest(
            [
                {"proposal_ids": list(pair), "evidence_ids": list(evidence_ids)}
                for pair, evidence_ids in sorted(inherited.items())
            ]
        ),
        "answer_isolation": {
            "named_family_targets_used": False,
            "sealed_registry_read": False,
            "withheld_results_used": False,
        },
    }
    path = _namespace(run_root) / "preregistration.json"
    _atomic_json(path, artifact)
    return path


def consolidate(run_root: Path, source_root: Path, config_path: Path) -> Path:
    """Verify preregistration and write deterministic cross-round families."""

    namespace = _namespace(run_root)
    preregistration = _read_json(namespace / "preregistration.json")
    source_root = source_root.resolve()
    config_path = config_path.resolve()
    config = _read_config(config_path)
    policy = _policy(config)
    source_digest = _digest(_source_manifest(source_root))
    policy_digest = _digest(config)
    if source_digest != preregistration.get("source_digest"):
        raise SourceIntegrityError("source digest changed after v3.4 preregistration")
    if policy_digest != preregistration.get("policy_digest"):
        raise SourceIntegrityError("policy digest changed after v3.4 preregistration")
    fingerprints, inherited, blockers, assignment_digest = _load_fingerprints(
        source_root, policy, config
    )
    if assignment_digest != preregistration.get(
        "allowed_coordinate_assignment_digest"
    ):
        raise SourceIntegrityError("coordinate digest changed after preregistration")
    inherited_digest = _digest(
        [
            {"proposal_ids": list(pair), "evidence_ids": list(evidence_ids)}
            for pair, evidence_ids in sorted(inherited.items())
        ]
    )
    if len(inherited) != preregistration.get("inherited_merge_pair_count") or (
        inherited_digest != preregistration.get("inherited_merge_pair_digest")
    ):
        raise SourceIntegrityError("inherited merge contract changed after preregistration")
    try:
        result = consolidate_fingerprints(
            fingerprints,
            policy,
            source_digest=source_digest,
            policy_digest=policy_digest,
            inherited_freeze_2_blockers=blockers,
            inherited_merge_pairs=inherited,
        )
    except ConsolidationError as exc:
        raise SourceIntegrityError(str(exc)) from exc
    result_path = namespace / "consolidation.json"
    _atomic_json(result_path, result.model_dump(mode="json"))
    status = {
        "version": result.version,
        "source_version": result.source_version,
        "state": (
            "converged" if result.consolidation_converged else "not_converged"
        ),
        "proposal_count": result.proposal_count,
        "consolidated_family_count": len(result.families),
        "unresolved_pair_count": sum(
            item.decision == "unresolved" for item in result.decisions
        ),
        "prefix_metrics": [item.model_dump(mode="json") for item in result.prefix_metrics],
        "consolidation_converged": result.consolidation_converged,
        "freeze_2_allowed": result.freeze_2_allowed,
        "freeze_2_blockers": list(result.freeze_2_blockers),
    }
    _atomic_json(namespace / "status.json", status)
    return result_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("prepare", "consolidate"), required=True)
    parser.add_argument("--source-root", type=Path, default=SOURCE_ROOT)
    parser.add_argument("--run-root", type=Path, default=RUN_ROOT)
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    args = parser.parse_args()
    path = (
        prepare(args.run_root, args.source_root, args.config)
        if args.phase == "prepare"
        else consolidate(args.run_root, args.source_root, args.config)
    )
    print(path)


if __name__ == "__main__":
    main()

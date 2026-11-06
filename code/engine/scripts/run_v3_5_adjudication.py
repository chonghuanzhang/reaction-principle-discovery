"""Preregister and run answer-isolated v3.5 comparison adjudication."""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from datetime import UTC, datetime
import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from pipeline.api_client import (
    ApiClientError,
    ChatCompletionsStructuredClient,
    ResponsesClient,
    UpstreamFallbackStructuredClient,
    read_keychain_secret,
)
from pipeline.comparison_adjudication import (
    ConsensusDecision,
    ComparisonReviewPayload,
    ComparisonTriage,
    ComparisonTriagePolicy,
    EvidenceDossier,
    apply_consensus_candidates,
    build_evidence_dossiers,
    canonical_dossier_digest,
    combine_review_lanes,
    map_lane_review,
    triage_unresolved_comparisons,
    validate_review_payload,
)
from pipeline.cross_round_consolidation import (
    CrossRoundConsolidation,
    EvidenceFingerprint,
    fingerprint_proposal,
)
from pipeline.evidence_registry import _atomic_json
from pipeline.principle_models import TransferabilityAssessment
from pipeline.model_proposals import StructuredClient, strict_model_schema
from pipeline.taxonomy_discovery import TaxonomyLaneResult, TaxonomyProposal
from pipeline.v3_evidence_import import EvidenceImportManifest, _manifest_digest


RUN_ROOT = Path("runs/reaction_principle_v3_5")
V341_ROOT = Path("runs/reaction_principle_v3_4_1/derived/principles_v3")
V33_ROOT = Path("runs/reaction_principle_v3_3/derived/principles_v3")
TRANSFER_PATH = Path(
    "derived/principles_v3/clean_inputs/"
    "64711df47d25faab0125d3d3cd9d52eeb04913e62d2d7b7b25fa0bef43d8cf7f/"
    "derived/principles/transfer_assessments.json"
)
EVIDENCE_IMPORT_MANIFEST_PATH = Path(
    "derived/principles_v3/evidence_import_manifest.json"
)
CONFIG_PATH = Path("config/comparison_adjudication_v3_5.yaml")
PROMPT_PATH = Path("config/prompts/comparison_adjudication_v3_5.md")


class V35IntegrityError(RuntimeError):
    """Raised when a v3.5 preregistered input changes or is incomplete."""


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise V35IntegrityError(f"invalid JSON input: {path.name}") from exc


def _read_config(path: Path) -> dict[str, Any]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise V35IntegrityError("invalid v3.5 policy") from exc
    if not isinstance(payload, dict):
        raise V35IntegrityError("v3.5 policy must be a mapping")
    return payload


def _validate_allowlisted_transfer_registry(
    transfer_path: Path,
    manifest_path: Path,
    repository_root: Path,
    expected_manifest_digest: str | None = None,
) -> None:
    manifest = _read_json(manifest_path)
    if not isinstance(manifest, dict):
        raise V35IntegrityError("evidence import manifest must be an object")
    accepted = manifest.get("accepted")
    rejected = manifest.get("rejected_paths")
    if not isinstance(accepted, list) or not isinstance(rejected, list):
        raise V35IntegrityError("evidence import manifest is malformed")
    if expected_manifest_digest is not None:
        try:
            validated_manifest = EvidenceImportManifest.model_validate(manifest)
        except ValidationError as exc:
            raise V35IntegrityError("evidence import manifest is malformed") from exc
        digest_material = validated_manifest.model_dump(
            mode="json",
            exclude={
                "rejected_paths",
                "rejection_reasons",
                "cache_namespace",
                "manifest_digest",
            },
        )
        content_digest = _manifest_digest(digest_material)
        if validated_manifest.manifest_digest != content_digest:
            raise V35IntegrityError("evidence import manifest content digest changed")
        if validated_manifest.manifest_digest != expected_manifest_digest:
            raise V35IntegrityError("evidence import manifest differs from v3.3 anchor")

    repository_root = repository_root.resolve()
    transfer_path = transfer_path.resolve()
    try:
        relative_path = transfer_path.relative_to(repository_root).as_posix()
    except ValueError as exc:
        raise V35IntegrityError("transfer registry is outside the repository") from exc
    if relative_path in rejected:
        raise V35IntegrityError("transfer registry is explicitly rejected")
    matches = [
        row
        for row in accepted
        if isinstance(row, dict)
        and row.get("artifact_type") == "transfer"
        and row.get("path") == relative_path
    ]
    if len(matches) != 1:
        raise V35IntegrityError("transfer registry is not uniquely allowlisted")
    actual_digest = hashlib.sha256(transfer_path.read_bytes()).hexdigest()
    if matches[0].get("sha256") != actual_digest:
        raise V35IntegrityError("transfer registry digest does not match allowlist")


def _validate_phase_transfer_registry(v33_root: Path, transfer_path: Path) -> None:
    preregistration = _read_json(v33_root / "preregistration.json")
    if not isinstance(preregistration, dict):
        raise V35IntegrityError("v3.3 preregistration must be an object")
    inputs = preregistration.get("inputs")
    expected_digest = (
        inputs.get("evidence_import_manifest_digest")
        if isinstance(inputs, dict)
        else None
    )
    if not isinstance(expected_digest, str) or len(expected_digest) != 64:
        raise V35IntegrityError("v3.3 evidence import anchor is unavailable")
    repository_root = Path(__file__).resolve().parents[1]
    _validate_allowlisted_transfer_registry(
        transfer_path,
        repository_root / EVIDENCE_IMPORT_MANIFEST_PATH,
        repository_root,
        expected_digest,
    )


def _policy(config: dict[str, Any]) -> ComparisonTriagePolicy:
    return ComparisonTriagePolicy.model_validate(
        {
            key: config[key]
            for key in ComparisonTriagePolicy.model_fields
            if key in config
        }
    )


def _namespace(run_root: Path) -> Path:
    return run_root.resolve() / "derived" / "principles_v3"


def _v33_paths(v33_root: Path) -> tuple[Path, ...]:
    return (
        v33_root / "preregistration.json",
        *tuple(sorted((v33_root / "rounds").glob("round_*.json"))),
        v33_root / "chemical_review.json",
    )


def _source_manifest(
    v341_root: Path,
    v33_root: Path,
    transfer_path: Path,
) -> dict[str, str]:
    paths = (
        ("v3.4.1/preregistration.json", v341_root / "preregistration.json"),
        ("v3.4.1/consolidation.json", v341_root / "consolidation.json"),
        ("v3.4.1/status.json", v341_root / "status.json"),
        *tuple(
            (f"v3.3/{path.relative_to(v33_root)}", path)
            for path in _v33_paths(v33_root)
        ),
        ("transfer_assessments.json", transfer_path),
    )
    missing = [label for label, path in paths if not path.is_file()]
    if missing:
        raise V35IntegrityError(f"missing public input: {missing[0]}")
    return {
        label: hashlib.sha256(path.read_bytes()).hexdigest()
        for label, path in paths
    }


def _validate_v33_manifest(v341_root: Path, v33_root: Path) -> None:
    preregistration = _read_json(v341_root / "preregistration.json")
    if not isinstance(preregistration, dict):
        raise V35IntegrityError("v3.4.1 preregistration must be an object")
    expected = preregistration.get("source_manifest")
    if not isinstance(expected, dict):
        raise V35IntegrityError("v3.4.1 source manifest is unavailable")
    actual = {
        str(path.relative_to(v33_root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in _v33_paths(v33_root)
    }
    if actual != expected:
        raise V35IntegrityError("v3.3 sources differ from the v3.4.1 contract")


def _load_proposals_and_fingerprints(
    v33_root: Path,
    expected_count: int,
) -> tuple[dict[str, TaxonomyProposal], dict[str, EvidenceFingerprint]]:
    proposals: dict[str, TaxonomyProposal] = {}
    fingerprints: dict[str, EvidenceFingerprint] = {}
    round_paths = tuple(sorted((v33_root / "rounds").glob("round_*.json")))
    if len(round_paths) != 5:
        raise V35IntegrityError("v3.5 requires exactly five v3.3 rounds")
    for expected_round, path in enumerate(round_paths, 1):
        payload = _read_json(path)
        if not isinstance(payload, dict) or payload.get("round_id") != expected_round:
            raise V35IntegrityError("v3.3 round order changed")
        lane_rows = payload.get("lane_results")
        if not isinstance(lane_rows, list):
            raise V35IntegrityError("v3.3 round lacks lane results")
        for lane_row in lane_rows:
            lane = TaxonomyLaneResult.model_validate(lane_row)
            if lane.round_id != expected_round:
                raise V35IntegrityError("v3.3 lane round mismatch")
            for proposal in lane.proposals:
                if proposal.proposal_id in proposals:
                    raise V35IntegrityError("duplicate proposal ID in v3.3")
                proposals[proposal.proposal_id] = proposal
                fingerprints[proposal.proposal_id] = fingerprint_proposal(
                    proposal,
                    lane_id=lane.lane_id,
                    round_id=lane.round_id,
                    channel=lane.channel,
                )
    if len(proposals) != expected_count:
        raise V35IntegrityError(
            f"expected {expected_count} proposals, found {len(proposals)}"
        )
    return proposals, fingerprints


def _load_assessments(path: Path) -> dict[str, TransferabilityAssessment]:
    payload = _read_json(path)
    if not isinstance(payload, dict) or not isinstance(payload.get("assessments"), list):
        raise V35IntegrityError("transfer assessment registry is malformed")
    rows = tuple(
        TransferabilityAssessment.model_validate(row)
        for row in payload["assessments"]
    )
    by_id = {item.assessment_id: item for item in rows}
    if len(by_id) != len(rows):
        raise V35IntegrityError("transfer assessment IDs are not unique")
    return by_id


def _load_inputs(
    v341_root: Path,
    v33_root: Path,
    transfer_path: Path,
    config_path: Path,
) -> tuple[
    CrossRoundConsolidation,
    dict[str, TaxonomyProposal],
    dict[str, EvidenceFingerprint],
    dict[str, TransferabilityAssessment],
    ComparisonTriagePolicy,
    dict[str, Any],
]:
    _validate_phase_transfer_registry(v33_root, transfer_path)
    config = _read_config(config_path)
    policy = _policy(config)
    _validate_v33_manifest(v341_root, v33_root)
    consolidation = CrossRoundConsolidation.model_validate(
        _read_json(v341_root / "consolidation.json")
    )
    if consolidation.version != policy.source_version:
        raise V35IntegrityError("v3.4.1 consolidation version mismatch")
    expected_count = config.get("expected_proposal_count")
    if not isinstance(expected_count, int):
        raise V35IntegrityError("expected proposal count is missing")
    proposals, fingerprints = _load_proposals_and_fingerprints(
        v33_root, expected_count
    )
    members = {
        proposal_id
        for family in consolidation.families
        for proposal_id in family.member_proposal_ids
    }
    if members != set(proposals):
        raise V35IntegrityError("v3.4.1 does not preserve the v3.3 proposal set")
    return (
        consolidation,
        proposals,
        fingerprints,
        _load_assessments(transfer_path),
        policy,
        config,
    )


def scan_answer_isolation(
    paths: tuple[Path, ...], forbidden_terms: tuple[str, ...]
) -> tuple[Path, ...]:
    """Return paths containing caller-supplied forbidden terms without logging terms."""

    normalized_terms = tuple(value.casefold() for value in forbidden_terms if value)
    return tuple(
        path
        for path in paths
        if any(
            term in path.read_text(encoding="utf-8").casefold()
            for term in normalized_terms
        )
    )


def _write_raw_provenance_manifest(namespace: Path) -> Path:
    required_fields = ("created_at", "request_digest", "client_type")
    records: list[dict[str, Any]] = []
    for path in sorted((namespace / "review" / "raw").glob("*/*.json")):
        payload = _read_json(path)
        if not isinstance(payload, dict):
            raise V35IntegrityError("raw review record must be an object")
        provenance_status = (
            "recorded"
            if all(payload.get(field) for field in required_fields)
            else "legacy_metadata_unavailable"
        )
        records.append(
            {
                "path": path.relative_to(namespace).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "lane_id": payload.get("lane_id"),
                "cache_key": payload.get("cache_key"),
                "provenance_status": provenance_status,
            }
        )
    output = {
        "version": 1,
        "record_count": len(records),
        "legacy_record_count": sum(
            row["provenance_status"] == "legacy_metadata_unavailable"
            for row in records
        ),
        "recorded_provenance_count": sum(
            row["provenance_status"] == "recorded" for row in records
        ),
        "new_record_required_fields": list(required_fields),
        "legacy_fields_not_reconstructed": [
            "created_at",
            "request_digest",
            "client_type",
            "request_endpoint",
        ],
        "records": records,
    }
    path = namespace / "review_raw_provenance_manifest.json"
    _atomic_json(path, output)
    return path


def prepare(
    run_root: Path,
    v341_root: Path,
    v33_root: Path,
    transfer_path: Path,
    config_path: Path,
    prompt_path: Path,
) -> Path:
    """Preregister source, policy, prompt, and unresolved-pair digests."""

    v341_root = v341_root.resolve()
    v33_root = v33_root.resolve()
    transfer_path = transfer_path.resolve()
    config_path = config_path.resolve()
    prompt_path = prompt_path.resolve()
    consolidation, _, _, _, policy, config = _load_inputs(
        v341_root, v33_root, transfer_path, config_path
    )
    unresolved_pairs = [
        list(item.compared_proposal_ids)
        for item in consolidation.decisions
        if item.decision == "unresolved"
    ]
    expected_unresolved = config.get("expected_unresolved_pair_count")
    if len(unresolved_pairs) != expected_unresolved:
        raise V35IntegrityError("unresolved comparison count does not match policy")
    source_manifest = _source_manifest(v341_root, v33_root, transfer_path)
    artifact = {
        "version": policy.version,
        "source_version": policy.source_version,
        "created_at": datetime.now(UTC).isoformat(),
        "proposal_count": consolidation.proposal_count,
        "unresolved_pair_count": len(unresolved_pairs),
        "unresolved_pair_digest": _digest(unresolved_pairs),
        "source_manifest": source_manifest,
        "source_digest": _digest(source_manifest),
        "policy": config,
        "policy_digest": _digest(config),
        "prompt_digest": hashlib.sha256(prompt_path.read_bytes()).hexdigest(),
        "answer_isolation": {
            "sealed_registry_read": False,
            "named_family_targets_used": False,
            "withheld_results_used": False,
        },
    }
    path = _namespace(run_root) / "preregistration.json"
    _atomic_json(path, artifact)
    return path


def _verify_preregistration(
    run_root: Path,
    v341_root: Path,
    v33_root: Path,
    transfer_path: Path,
    config_path: Path,
    prompt_path: Path,
) -> dict[str, Any]:
    preregistration = _read_json(_namespace(run_root) / "preregistration.json")
    if not isinstance(preregistration, dict):
        raise V35IntegrityError("v3.5 preregistration is unavailable")
    source_digest = _digest(_source_manifest(v341_root, v33_root, transfer_path))
    if source_digest != preregistration.get("source_digest"):
        raise V35IntegrityError("source digest changed after prepare")
    config = _read_config(config_path)
    if _digest(config) != preregistration.get("policy_digest"):
        raise V35IntegrityError("policy digest changed after prepare")
    if hashlib.sha256(prompt_path.read_bytes()).hexdigest() != preregistration.get(
        "prompt_digest"
    ):
        raise V35IntegrityError("prompt digest changed after prepare")
    return preregistration


def triage(
    run_root: Path,
    v341_root: Path,
    v33_root: Path,
    transfer_path: Path,
    config_path: Path,
    prompt_path: Path,
) -> Path:
    """Write exhaustive triage and local evidence dossiers."""

    run_root = run_root.resolve()
    v341_root = v341_root.resolve()
    v33_root = v33_root.resolve()
    transfer_path = transfer_path.resolve()
    config_path = config_path.resolve()
    prompt_path = prompt_path.resolve()
    preregistration = _verify_preregistration(
        run_root, v341_root, v33_root, transfer_path, config_path, prompt_path
    )
    consolidation, proposals, fingerprints, assessments, policy, config = _load_inputs(
        v341_root, v33_root, transfer_path, config_path
    )
    result = triage_unresolved_comparisons(consolidation, fingerprints, policy)
    if len(result.records) != preregistration.get("unresolved_pair_count"):
        raise V35IntegrityError("triage did not preserve all unresolved comparisons")
    expected_counts = {
        "shared_external_evidence": config.get(
            "expected_shared_external_evidence_count"
        ),
        "text_compatible_evidence_gap": config.get(
            "expected_text_compatible_evidence_gap_count"
        ),
        "insufficient_linkage": config.get("expected_insufficient_linkage_count"),
    }
    if result.counts != expected_counts:
        raise V35IntegrityError("formal triage counts do not match preregistration policy")
    dossiers = build_evidence_dossiers(
        result, fingerprints, proposals, assessments
    )
    namespace = _namespace(run_root)
    triage_path = namespace / "comparison_triage.json"
    _atomic_json(triage_path, result.model_dump(mode="json"))
    _atomic_json(
        namespace / "evidence_dossiers.json",
        {
            "version": policy.version,
            "source_version": policy.source_version,
            "dossier_count": len(dossiers),
            "dossiers": [item.model_dump(mode="json") for item in dossiers],
        },
    )
    return triage_path


def _default_review_client() -> StructuredClient:
    secret_provider = lambda: read_keychain_secret(
        "reaction-principle-jaspervault", os.environ["USER"]
    )
    chat_client = ChatCompletionsStructuredClient(
        "https://cs.jaspervault.pro/v1",
        secret_provider,
        read_timeout_seconds=1200,
    )
    return UpstreamFallbackStructuredClient(
        ResponsesClient(
            "https://cs.jaspervault.pro/v1",
            secret_provider,
            read_timeout_seconds=1200,
        ),
        chat_client,
    )


def comparison_review_schema() -> dict[str, Any]:
    """Return the strict review schema with gateway-compatible tuple arrays."""

    schema = deepcopy(strict_model_schema(ComparisonReviewPayload))
    comparison = schema.get("$defs", {}).get("ComparisonReview", {})
    pair = comparison.get("properties", {}).get("compared_proposal_ids", {})
    if not isinstance(pair, dict):
        raise V35IntegrityError("comparison review schema lacks proposal IDs")
    pair["items"] = {"type": "string"}
    pair["minItems"] = 2
    pair["maxItems"] = 2
    fields = comparison.get("properties", {}).get("field_judgments", {})
    if not isinstance(fields, dict):
        raise V35IntegrityError("comparison review schema lacks field judgments")
    judgment_schema = fields.get("additionalProperties")
    if not isinstance(judgment_schema, dict):
        raise V35IntegrityError("comparison field judgment schema is unavailable")
    field_names = (
        "nucleophilic_center",
        "reactive_state",
        "bond_forming_mode",
        "activation_mode",
        "critical_conditions",
        "dominant_failure_modes",
    )
    fields.pop("propertyNames", None)
    fields["properties"] = {
        field: deepcopy(judgment_schema) for field in field_names
    }
    fields["required"] = list(field_names)
    fields["additionalProperties"] = False
    return schema


def _load_dossiers(namespace: Path) -> tuple[EvidenceDossier, ...]:
    payload = _read_json(namespace / "evidence_dossiers.json")
    if not isinstance(payload, dict) or not isinstance(payload.get("dossiers"), list):
        raise V35IntegrityError("v3.5 evidence dossiers are unavailable")
    dossiers = tuple(EvidenceDossier.model_validate(row) for row in payload["dossiers"])
    if any(item.dossier_digest != canonical_dossier_digest(item) for item in dossiers):
        raise V35IntegrityError("v3.5 dossier digest mismatch")
    return dossiers


def _build_offline_artifacts(
    v341_root: Path,
    v33_root: Path,
    transfer_path: Path,
    config_path: Path,
) -> tuple[ComparisonTriage, tuple[EvidenceDossier, ...]]:
    consolidation, proposals, fingerprints, assessments, policy, _ = _load_inputs(
        v341_root, v33_root, transfer_path, config_path
    )
    triage_payload = triage_unresolved_comparisons(
        consolidation, fingerprints, policy
    )
    dossiers = build_evidence_dossiers(
        triage_payload, fingerprints, proposals, assessments
    )
    return triage_payload, dossiers


def _verify_offline_artifacts(
    namespace: Path,
    v341_root: Path,
    v33_root: Path,
    transfer_path: Path,
    config_path: Path,
) -> tuple[ComparisonTriage, tuple[EvidenceDossier, ...]]:
    recorded_triage = ComparisonTriage.model_validate(
        _read_json(namespace / "comparison_triage.json")
    )
    recorded_dossiers = _load_dossiers(namespace)
    expected_triage, expected_dossiers = _build_offline_artifacts(
        v341_root, v33_root, transfer_path, config_path
    )
    if recorded_triage != expected_triage or recorded_dossiers != expected_dossiers:
        raise V35IntegrityError("offline artifacts differ from frozen sources")
    return recorded_triage, recorded_dossiers


def _review_cache_key(
    *,
    lane_id: str,
    model: str,
    prompt_digest: str,
    schema_digest: str,
    batch: tuple[EvidenceDossier, ...],
) -> str:
    return _digest(
        {
            "lane_id": lane_id,
            "model": model,
            "prompt_digest": prompt_digest,
            "schema_digest": schema_digest,
            "dossier_digests": [item.dossier_digest for item in batch],
        }
    )


def _expected_lane_batches(
    dossiers: tuple[EvidenceDossier, ...],
    *,
    lane_id: str,
    model: str,
    prompt_digest: str,
    schema_digest: str,
    batch_size: int,
) -> dict[str, tuple[EvidenceDossier, ...]]:
    batches: dict[str, tuple[EvidenceDossier, ...]] = {}
    for start in range(0, len(dossiers), batch_size):
        batch = dossiers[start : start + batch_size]
        cache_key = _review_cache_key(
            lane_id=lane_id,
            model=model,
            prompt_digest=prompt_digest,
            schema_digest=schema_digest,
            batch=batch,
        )
        batches[cache_key] = batch
    return batches


def _validate_review_cache_file(
    path: Path,
    *,
    lane_id: str,
    cache_key: str,
    model: str,
    batch: tuple[EvidenceDossier, ...],
) -> ComparisonReviewPayload:
    payload = _read_json(path)
    if (
        not isinstance(payload, dict)
        or payload.get("lane_id") != lane_id
        or payload.get("cache_key") != cache_key
        or payload.get("model") != model
        or path.stem != cache_key
        or not isinstance(payload.get("comparisons"), list)
    ):
        raise V35IntegrityError("validated review cache metadata mismatch")
    review_payload = ComparisonReviewPayload.model_validate(
        {"comparisons": payload["comparisons"]}
    )
    validate_review_payload(
        review_payload,
        {item.compared_proposal_ids: item for item in batch},
    )
    return review_payload


def _usage_payload(result: Any) -> dict[str, int | None]:
    usage = getattr(result, "usage", None)
    return {
        "input_tokens": getattr(usage, "input_tokens", None),
        "output_tokens": getattr(usage, "output_tokens", None),
        "total_tokens": getattr(usage, "total_tokens", None),
    }


def review(
    run_root: Path,
    v341_root: Path,
    v33_root: Path,
    transfer_path: Path,
    config_path: Path,
    prompt_path: Path,
    *,
    client_factory=None,
    max_batches: int | None = None,
) -> Path:
    """Run resumable, independent structured review lanes."""

    run_root = run_root.resolve()
    v341_root = v341_root.resolve()
    v33_root = v33_root.resolve()
    transfer_path = transfer_path.resolve()
    config_path = config_path.resolve()
    prompt_path = prompt_path.resolve()
    _verify_preregistration(
        run_root, v341_root, v33_root, transfer_path, config_path, prompt_path
    )
    namespace = _namespace(run_root)
    config = _read_config(config_path)
    triage_payload, dossiers = _verify_offline_artifacts(
        namespace, v341_root, v33_root, transfer_path, config_path
    )
    dossiers_by_pair = {item.compared_proposal_ids: item for item in dossiers}
    if tuple(dossiers_by_pair) != triage_payload.review_queue:
        raise V35IntegrityError("dossier order differs from the preregistered queue")
    lane_ids = config.get("review_lane_ids")
    batch_size = config.get("maximum_batch_size")
    model = config.get("model")
    if (
        not isinstance(lane_ids, list)
        or len(lane_ids) != 2
        or len(set(map(str, lane_ids))) != 2
        or not isinstance(batch_size, int)
        or batch_size < 1
        or not isinstance(model, str)
        or not model
    ):
        raise V35IntegrityError("review configuration is invalid")
    schema = comparison_review_schema()
    schema_digest = _digest(schema)
    prompt = prompt_path.read_text(encoding="utf-8").strip()
    prompt_digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    failures_path = namespace / "review_failures.json"
    existing_failures = _read_json(failures_path) if failures_path.is_file() else {}
    failure_rows = list(existing_failures.get("failures", [])) if isinstance(existing_failures, dict) else []
    failure_keys = {
        (str(item.get("lane_id")), str(item.get("cache_key")))
        for item in failure_rows
        if isinstance(item, dict)
    }
    processed_batches = 0
    reused_batches = 0
    for raw_lane_id in lane_ids:
        lane_id = str(raw_lane_id)
        lane_batches = 0
        client = (
            client_factory(lane_id)
            if client_factory is not None
            else _default_review_client()
        )
        expected_batches = _expected_lane_batches(
            dossiers,
            lane_id=lane_id,
            model=model,
            prompt_digest=prompt_digest,
            schema_digest=schema_digest,
            batch_size=batch_size,
        )
        validated_root = namespace / "review" / "validated" / lane_id
        unexpected_cache_paths = {
            path.stem for path in validated_root.glob("*.json")
        } - set(expected_batches)
        if unexpected_cache_paths:
            raise V35IntegrityError("unexpected validated review cache")
        for cache_key, batch in expected_batches.items():
            if max_batches is not None and lane_batches >= max_batches:
                break
            validated_path = namespace / "review" / "validated" / lane_id / f"{cache_key}.json"
            if validated_path.is_file():
                _validate_review_cache_file(
                    validated_path,
                    lane_id=lane_id,
                    cache_key=cache_key,
                    model=model,
                    batch=batch,
                )
                reused_batches += 1
                lane_batches += 1
                continue
            input_text = prompt + "\nDOSSIERS_JSON\n" + json.dumps(
                [item.model_dump(mode="json") for item in batch],
                ensure_ascii=False,
                sort_keys=True,
            )
            try:
                result = client.create_structured(
                    model=model,
                    input_text=input_text,
                    schema=schema,
                    schema_name="comparison_adjudication_v3_5",
                )
                raw_path = namespace / "review" / "raw" / lane_id / f"{cache_key}.json"
                _atomic_json(
                    raw_path,
                    {
                        "created_at": datetime.now(UTC).isoformat(),
                        "lane_id": lane_id,
                        "cache_key": cache_key,
                        "request_digest": hashlib.sha256(
                            input_text.encode("utf-8")
                        ).hexdigest(),
                        "client_type": type(client).__name__,
                        "response_id": str(getattr(result, "response_id", "")),
                        "returned_model": str(getattr(result, "returned_model", "")),
                        "status": str(getattr(result, "status", "")),
                        "usage": _usage_payload(result),
                        "parsed_output": result.parsed_output,
                    },
                )
                payload = ComparisonReviewPayload.model_validate(result.parsed_output)
                validate_review_payload(
                    payload,
                    {item.compared_proposal_ids: item for item in batch},
                )
                _atomic_json(
                    validated_path,
                    {
                        "lane_id": lane_id,
                        "cache_key": cache_key,
                        "model": model,
                        "comparisons": [
                            item.model_dump(mode="json") for item in payload.comparisons
                        ],
                    },
                )
                processed_batches += 1
            except (ApiClientError, ValidationError, ValueError) as exc:
                key = (lane_id, cache_key)
                if key not in failure_keys:
                    if isinstance(exc, ApiClientError):
                        failure = {
                            "lane_id": lane_id,
                            "cache_key": cache_key,
                            "status": exc.status,
                            "error_type": exc.error_type,
                            "error_code": exc.error_code,
                            "reason": exc.safe_message,
                            "compared_proposal_ids": [
                                list(item.compared_proposal_ids) for item in batch
                            ],
                        }
                    else:
                        failure = {
                            "lane_id": lane_id,
                            "cache_key": cache_key,
                            "status": None,
                            "error_type": type(exc).__name__,
                            "error_code": None,
                            "reason": str(exc)[:500],
                            "compared_proposal_ids": [
                                list(item.compared_proposal_ids) for item in batch
                            ],
                        }
                    failure_rows.append(failure)
                    failure_keys.add(key)
            lane_batches += 1
    _atomic_json(
        failures_path,
        {
            "version": "3.5",
            "failure_count": len(failure_rows),
            "failures": failure_rows,
        },
    )
    status_path = namespace / "review_status.json"
    _atomic_json(
        status_path,
        {
            "version": "3.5",
            "dossier_count": len(dossiers),
            "processed_batch_count": processed_batches,
            "reused_batch_count": reused_batches,
            "failure_count": len(failure_rows),
        },
    )
    _write_raw_provenance_manifest(namespace)
    return status_path


def _validated_reviews(
    namespace: Path,
    lane_id: str,
    expected_batches: dict[str, tuple[EvidenceDossier, ...]],
    model: str,
) -> dict[tuple[str, str], Any]:
    reviews: dict[tuple[str, str], Any] = {}
    validated_root = namespace / "review" / "validated" / lane_id
    actual_paths = {
        path.stem: path for path in sorted(validated_root.glob("*.json"))
    }
    unexpected = set(actual_paths) - set(expected_batches)
    if unexpected:
        raise V35IntegrityError("unexpected validated review cache")
    for cache_key, batch_dossiers in expected_batches.items():
        path = actual_paths.get(cache_key)
        if path is None:
            continue
        batch = _validate_review_cache_file(
            path,
            lane_id=lane_id,
            cache_key=cache_key,
            model=model,
            batch=batch_dossiers,
        )
        for item in batch.comparisons:
            if item.compared_proposal_ids in reviews:
                raise V35IntegrityError("duplicate validated review comparison")
            reviews[item.compared_proposal_ids] = item
    return reviews


def consensus(
    run_root: Path,
    v341_root: Path,
    v33_root: Path,
    transfer_path: Path,
    config_path: Path,
    prompt_path: Path,
) -> Path:
    """Combine review lanes and write a conservative candidate consolidation."""

    run_root = run_root.resolve()
    v341_root = v341_root.resolve()
    v33_root = v33_root.resolve()
    transfer_path = transfer_path.resolve()
    config_path = config_path.resolve()
    prompt_path = prompt_path.resolve()
    _verify_preregistration(
        run_root, v341_root, v33_root, transfer_path, config_path, prompt_path
    )
    namespace = _namespace(run_root)
    config = _read_config(config_path)
    lane_ids = tuple(str(value) for value in config.get("review_lane_ids", ()))
    if len(lane_ids) != 2 or len(set(lane_ids)) != 2:
        raise V35IntegrityError("consensus requires two configured lanes")
    _, dossiers = _verify_offline_artifacts(
        namespace, v341_root, v33_root, transfer_path, config_path
    )
    dossiers_by_pair = {item.compared_proposal_ids: item for item in dossiers}
    model = config.get("model")
    batch_size = config.get("maximum_batch_size")
    if not isinstance(model, str) or not isinstance(batch_size, int) or batch_size < 1:
        raise V35IntegrityError("consensus review configuration is invalid")
    schema_digest = _digest(comparison_review_schema())
    prompt = prompt_path.read_text(encoding="utf-8").strip()
    prompt_digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    expected_batches_by_lane = {
        lane_id: _expected_lane_batches(
            dossiers,
            lane_id=lane_id,
            model=model,
            prompt_digest=prompt_digest,
            schema_digest=schema_digest,
            batch_size=batch_size,
        )
        for lane_id in lane_ids
    }
    reviews_by_lane = {
        lane_id: _validated_reviews(
            namespace, lane_id, expected_batches_by_lane[lane_id], model
        )
        for lane_id in lane_ids
    }
    failures_payload = (
        _read_json(namespace / "review_failures.json")
        if (namespace / "review_failures.json").is_file()
        else {}
    )
    failed_by_lane: dict[str, set[tuple[str, str]]] = {
        lane_id: set() for lane_id in lane_ids
    }
    if isinstance(failures_payload, dict):
        for row in failures_payload.get("failures", []):
            if not isinstance(row, dict) or str(row.get("lane_id")) not in failed_by_lane:
                continue
            lane_id = str(row["lane_id"])
            cache_key = str(row.get("cache_key"))
            expected_batch = expected_batches_by_lane[lane_id].get(cache_key)
            if expected_batch is None:
                continue
            expected_pairs = {
                item.compared_proposal_ids for item in expected_batch
            }
            recorded_pairs = {
                tuple(sorted(map(str, raw_pair)))
                for raw_pair in row.get("compared_proposal_ids", [])
                if isinstance(raw_pair, list) and len(raw_pair) == 2
            }
            if recorded_pairs != expected_pairs:
                raise V35IntegrityError("review failure cache metadata mismatch")
            failed_by_lane[lane_id].update(expected_pairs)
    consensus_rows: list[ConsensusDecision] = []
    for pair in sorted(dossiers_by_pair):
        if all(pair in reviews_by_lane[lane_id] for lane_id in lane_ids):
            consensus_rows.extend(
                combine_review_lanes(
                    {
                        lane_id: {pair: reviews_by_lane[lane_id][pair]}
                        for lane_id in lane_ids
                    },
                    {pair: dossiers_by_pair[pair]},
                    required_lane_ids=lane_ids,  # type: ignore[arg-type]
                )
            )
            continue
        mapped = []
        for lane_id in lane_ids:
            review_item = reviews_by_lane[lane_id].get(pair)
            mapped.append(
                map_lane_review(review_item).outcome
                if review_item is not None
                else "platform_or_validation_failure"
            )
        evidence_ids = tuple(
            sorted(
                {
                    evidence_id
                    for lane_id in lane_ids
                    for review_item in (reviews_by_lane[lane_id].get(pair),)
                    if review_item is not None
                    for evidence_id in map_lane_review(review_item).evidence_ids
                }
            )
        )
        consensus_rows.append(
            ConsensusDecision(
                compared_proposal_ids=pair,
                disposition="unresolved",
                lane_outcomes=tuple(mapped),  # type: ignore[arg-type]
                evidence_ids=evidence_ids,
                rationale="At least one independent review lane lacks a valid result.",
            )
        )
    baseline = CrossRoundConsolidation.model_validate(
        _read_json(v341_root / "consolidation.json")
    )
    candidate = apply_consensus_candidates(baseline, tuple(consensus_rows))
    consensus_counts = {
        key: sum(item.disposition == key for item in consensus_rows)
        for key in (
            "consensus_merge_candidate",
            "evidence_supported_distinct_candidate",
            "parent_child_candidate",
            "unresolved",
        )
    }
    review_complete = all(
        set(dossiers_by_pair).issubset(
            set(reviews_by_lane[lane_id]) | failed_by_lane[lane_id]
        )
        for lane_id in lane_ids
    )
    triage_payload = ComparisonTriage.model_validate(
        _read_json(namespace / "comparison_triage.json")
    )
    remaining_unresolved = (
        triage_payload.counts["text_compatible_evidence_gap"]
        + triage_payload.counts["insufficient_linkage"]
        + consensus_counts["unresolved"]
    )
    _atomic_json(
        namespace / "consensus.json",
        {
            "version": "3.5",
            "source_version": "3.4.1",
            "review_complete": review_complete,
            "consensus_counts": consensus_counts,
            "decisions": [item.model_dump(mode="json") for item in consensus_rows],
        },
    )
    _atomic_json(
        namespace / "candidate_consolidation.json",
        candidate.model_dump(mode="json"),
    )
    status_path = namespace / "status.json"
    _atomic_json(
        status_path,
        {
            "version": "3.5",
            "source_version": "3.4.1",
            "state": (
                "review_complete_not_converged"
                if review_complete
                else "review_incomplete"
            ),
            "triage_counts": triage_payload.counts,
            "dossier_count": len(dossiers),
            "reviewed_in_both_lanes_count": sum(
                all(pair in reviews_by_lane[lane_id] for lane_id in lane_ids)
                for pair in dossiers_by_pair
            ),
            "consensus_counts": consensus_counts,
            "candidate_family_count": candidate.candidate_family_count,
            "remaining_unresolved_comparison_count": remaining_unresolved,
            "consolidation_converged": False,
            "freeze_2_allowed": False,
            "freeze_2_blockers": list(
                dict.fromkeys(
                    (*baseline.freeze_2_blockers, "v3_5_review_not_converged")
                )
            ),
        },
    )
    _write_raw_provenance_manifest(namespace)
    return status_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase", choices=("prepare", "triage", "review", "consensus"), required=True
    )
    parser.add_argument("--run-root", type=Path, default=RUN_ROOT)
    parser.add_argument("--v341-root", type=Path, default=V341_ROOT)
    parser.add_argument("--v33-root", type=Path, default=V33_ROOT)
    parser.add_argument("--transfer-path", type=Path, default=TRANSFER_PATH)
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--prompt", type=Path, default=PROMPT_PATH)
    parser.add_argument("--max-batches", type=int)
    args = parser.parse_args()
    _validate_allowlisted_transfer_registry(
        args.transfer_path,
        EVIDENCE_IMPORT_MANIFEST_PATH,
        Path.cwd(),
    )
    kwargs = {
        "run_root": args.run_root,
        "v341_root": args.v341_root,
        "v33_root": args.v33_root,
        "transfer_path": args.transfer_path,
        "config_path": args.config,
        "prompt_path": args.prompt,
    }
    if args.phase == "prepare":
        path = prepare(**kwargs)
    elif args.phase == "triage":
        path = triage(**kwargs)
    elif args.phase == "review":
        path = review(**kwargs, max_batches=args.max_batches)
    else:
        path = consensus(**kwargs)
    print(path)


if __name__ == "__main__":
    main()
    apply_consensus_candidates,
    combine_review_lanes,
    map_lane_review,

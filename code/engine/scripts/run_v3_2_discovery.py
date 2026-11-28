"""Restore v3.2/v3.3 orchestration using the retained v3 pipeline contracts.

This is a source reconstruction, not a byte-identical historical restoration.
Selection is explicitly preregistered and never uses named reaction partners.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from pipeline.api_client import (
    ApiClientError, ChatCompletionsStructuredClient, ResponsesClient,
    UpstreamFallbackStructuredClient, read_keychain_secret,
)
from pipeline.evidence_registry import _atomic_json
from pipeline.family_canonicalization import canonicalize_proposals
from pipeline.principle_models import TransferabilityAssessment
from pipeline.saturation import expand_coordinate_assignments
from pipeline.taxonomy_discovery import (
    TaxonomyDiscoveryContext, TaxonomyModelInvocationConfig, propose_family_lane,
)

if __package__:
    from scripts import run_v3_1_discovery as previous
else:
    import run_v3_1_discovery as previous


SOURCE_NAMESPACE = previous.SOURCE_NAMESPACE
saturation = previous.saturation
status = previous.status
SELECTION_RULE = (
    "Round-robin transferable, conditional, non_transferable, unknown; "
    "prefer less represented papers, then descending existing total, then ID; "
    "top 80, with no named-family selection. Reconstructed runner rule."
)


def select_stratified_assessments(assessments, limit=80):
    if limit < 1:
        raise ValueError("assessment limit must be positive")
    groups = {key: [] for key in (
        "transferable", "conditional", "non_transferable", "unknown")}
    seen = set()
    for item in assessments:
        if item.assessment_id in seen:
            raise ValueError("duplicate assessment ID")
        seen.add(item.assessment_id)
        if item.transfer_status not in groups:
            raise ValueError("unknown transfer status")
        groups[item.transfer_status].append(item)
    result = []
    papers = {}

    def paper(item):
        return item.source_paper_id or item.assessment_id

    def priority(item):
        total = item.score_components.get("total", 0)
        return (papers.get(paper(item), 0),
                -total if isinstance(total, int) else 0, item.assessment_id)

    while len(result) < limit and any(groups.values()):
        for rows in groups.values():
            if not rows or len(result) >= limit:
                continue
            item = min(rows, key=priority)
            rows.remove(item)
            result.append(item)
            papers[paper(item)] = papers.get(paper(item), 0) + 1
    return tuple(result)


def coordinate_preregistration(config, *, version):
    assignments = [item.model_dump(mode="json")
                   for item in expand_coordinate_assignments(config)]
    if str(version) == "3.3" and len(assignments) != 35:
        raise ValueError("v3.3 requires exactly 35 coordinate assignments")
    encoded = json.dumps(assignments, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return {
        "allowed_coordinate_assignment_count": len(assignments),
        "allowed_coordinate_assignments": assignments,
        "allowed_coordinate_assignment_digest": hashlib.sha256(encoded).hexdigest(),
    }


def _client():
    args = ("https://cs.jaspervault.pro/v1",
            lambda: read_keychain_secret("reaction-principle-jaspervault", os.environ["USER"]))
    options = {"read_timeout_seconds": 1200}
    transport = os.environ.get("JASPER_API_TRANSPORT", "responses")
    if transport == "chat_completions":
        return ChatCompletionsStructuredClient(*args, **options)
    if transport != "responses":
        raise ValueError("unsupported JASPER_API_TRANSPORT")
    return UpstreamFallbackStructuredClient(
        ResponsesClient(*args, **options),
        ChatCompletionsStructuredClient(*args, **options),
    )


def _transfer_path(source_root, manifest):
    rows = [row for row in manifest.get("accepted", [])
            if isinstance(row, dict) and row.get("artifact_type") == "transfer"]
    if len(rows) != 1:
        raise ValueError("evidence import must accept exactly one transfer artifact")
    row = rows[0]
    relative = Path(str(row.get("path", "")))
    root = source_root.resolve()
    path = (root / relative).resolve()
    if relative.is_absolute() or ".." in relative.parts or not path.is_relative_to(root):
        raise ValueError("transfer artifact path is not canonical inside source root")
    if path.relative_to(root).as_posix() != relative.as_posix():
        raise ValueError("transfer artifact path is not canonical inside source root")
    expected = row.get("sha256")
    if not isinstance(expected, str) or len(expected) != 64:
        raise ValueError("transfer artifact requires a SHA-256 commitment")
    if previous._sha256(path) != expected:
        raise ValueError("transfer artifact changed or SHA-256 mismatch")
    return path


def _inputs(source_root, workflow_config, coordinate_config):
    workflow = previous._load_yaml(workflow_config)
    coordinates = previous._load_yaml(coordinate_config)
    coordinate_preregistration(coordinates, version=workflow["version"])
    brief = previous.load_v3_brief(workflow)
    frozen = previous.FrozenReactionPrincipleSet.model_validate(
        previous._read_json(source_root / SOURCE_NAMESPACE / "frozen_principles.json"))
    manifest = previous._read_json(source_root / SOURCE_NAMESPACE / "evidence_import_manifest.json")
    payload = previous._read_json(_transfer_path(source_root, manifest))
    assessments = select_stratified_assessments(tuple(
        TransferabilityAssessment.model_validate(row) for row in payload["assessments"]))
    return workflow, coordinates, brief, frozen, assessments, manifest["manifest_digest"]


def _registration(source_root, workflow_config, coordinate_config):
    workflow, coordinates, brief, frozen, assessments, digest = _inputs(
        source_root, workflow_config, coordinate_config)
    return {
        "version": str(workflow["version"]),
        "runner_restoration": "retained-contract-reconstruction-v1",
        "answer_isolation": {"sealed_registry_read": False,
                             "named_family_targets_used": False,
                             "withheld_results_used": False},
        "inputs": {
            "workflow_config": str(workflow_config.resolve()),
            "workflow_config_sha256": previous._sha256(workflow_config),
            "coordinate_config": str(coordinate_config.resolve()),
            "coordinate_config_sha256": previous._sha256(coordinate_config),
            "evidence_import_manifest_digest": digest,
            "evidence_import_manifest_sha256": previous._sha256(
                source_root / SOURCE_NAMESPACE / "evidence_import_manifest.json"),
            "transfer_assessments_sha256": previous._sha256(
                _transfer_path(source_root, previous._read_json(
                    source_root / SOURCE_NAMESPACE / "evidence_import_manifest.json"))),
            "frozen_principles_sha256": previous._sha256(
                source_root / SOURCE_NAMESPACE / "frozen_principles.json"),
            "frozen_principle_source_digest": frozen.source_digest,
            "brief": brief.model_dump(mode="json"),
            "assessment_selection_rule": SELECTION_RULE,
            "selected_assessment_ids": [item.assessment_id for item in assessments],
            **coordinate_preregistration(coordinates, version=workflow["version"]),
        },
    }


def prepare(source_root, run_root, workflow_config, coordinate_config):
    record = _registration(source_root, workflow_config, coordinate_config)
    path = run_root / SOURCE_NAMESPACE / "preregistration.json"
    if path.is_file():
        existing = previous._read_json(path)
        if {key: value for key, value in existing.items() if key != "created_at"} != record:
            raise ValueError("discovery inputs changed since preregistration")
        return existing
    record["created_at"] = previous._now()
    _atomic_json(path, record)
    return record


def discover_round(source_root, run_root, workflow_config, coordinate_config,
                   round_id, *, adjudicate):
    workflow, coordinates, brief, frozen, assessments, digest = _inputs(
        source_root, workflow_config, coordinate_config)
    cap = int(workflow.get("saturation", {}).get("maximum_completed_rounds", 5))
    if not 1 <= round_id <= cap:
        raise ValueError("discovery round exceeds configured cap")
    prepare(source_root, run_root, workflow_config, coordinate_config)
    discovery = workflow["taxonomy_discovery"]
    context = TaxonomyDiscoveryContext(
        brief=brief, reviewed_principles=frozen.principles,
        selected_transfer_assessments=assessments, retrieval_evidence=(),
        evidence_import_digest=digest, output_root=run_root,
        model_config=TaxonomyModelInvocationConfig(model=str(discovery["model"])),
        prompt_version=str(discovery["prompt_version"]),
        coordinate_vocabulary=previous._coordinate_vocabulary(coordinates),
        allowed_coordinate_assignments=expand_coordinate_assignments(coordinates),
    )
    api = _client()
    completed, failures = [], []
    for lane_id in previous.LANES:
        for channel in previous.DISCOVERY_CHANNELS:
            try:
                completed.append(propose_family_lane(
                    context, api, lane_id=lane_id, round_id=round_id, channel=channel))
            except ApiClientError as exc:
                failures.append({"lane_id": lane_id, "channel": channel,
                                 "status": "platform_failure_skipped",
                                 "error_type": exc.error_type, "error_code": exc.error_code,
                                 "http_status": exc.status, "chemical_disposition": "unknown"})
    if not completed:
        raise RuntimeError("no discovery channel completed in this round")
    taxonomy = canonicalize_proposals(tuple(completed), api if adjudicate else None)
    artifact = {
        "round_id": round_id,
        "lane_results": [item.model_dump(mode="json") for item in completed],
        "taxonomy": taxonomy.model_dump(mode="json"),
        "adjudication": "bounded_model" if adjudicate else "explicit_unresolved",
        "platform_failures": failures,
    }
    _atomic_json(run_root / SOURCE_NAMESPACE / "rounds" / f"round_{round_id}.json", artifact)
    return artifact

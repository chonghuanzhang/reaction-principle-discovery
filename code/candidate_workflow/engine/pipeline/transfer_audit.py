"""Fail-closed audit for paper-scoped semantic Knowledge Transfer."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from pipeline.evidence_registry import _atomic_json
from pipeline.paper_mechanism_bundles import load_paper_mechanism_bundles
from pipeline.principle_models import TransferabilityAssessment
from pipeline.semantic_transfer import PaperTransferProposal


class TransferAuditError(RuntimeError):
    """Raised when semantic transfer artifacts are incomplete or inconsistent."""


class KnowledgeTransferAudit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    paper_count: int
    mechanism_count: int
    assessment_count: int
    unique_assessment_count: int
    revisit_count: int
    missing_paper_count: int
    missing_mechanism_count: int
    provenance_violation_count: int
    status_counts: dict[str, int]
    component_judgment_counts: dict[str, int]


def _load(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TransferAuditError(f"cannot read {label}: {path}") from exc
    if not isinstance(value, dict):
        raise TransferAuditError(f"{label} must be a JSON object")
    return value


def audit_knowledge_transfer(output_root: Path) -> KnowledgeTransferAudit:
    """Cross-check every semantic proposal, adjudication, and aggregate row."""

    root = output_root.resolve()
    bundles = load_paper_mechanism_bundles(root)
    transfer_root = root / "derived/principles/semantic_transfer"
    manifest = _load(root / "derived/principles/transfer_manifest.json", "transfer manifest")
    records = manifest.get("records")
    if not isinstance(records, dict):
        raise TransferAuditError("transfer manifest records must be an object")
    expected_sources = {bundle.source_path for bundle in bundles}
    complete_sources = {
        source
        for source, row in records.items()
        if source in expected_sources
        and isinstance(row, dict)
        and row.get("status") in {"validated", "reused"}
    }
    missing_sources = expected_sources - complete_sources
    if missing_sources:
        raise TransferAuditError(
            "missing or failed transfer papers: " + ", ".join(sorted(missing_sources))
        )

    all_assessments: list[TransferabilityAssessment] = []
    expected_mechanism_ids: set[str] = set()
    component_counts: Counter[str] = Counter()
    paper_level_artifacts: list[dict] = []
    for bundle in bundles:
        expected = {item.mechanism_evidence_id for item in bundle.mechanisms}
        expected_mechanism_ids.update(expected)
        raw_payload = _load(
            transfer_root / bundle.namespace / "raw.json",
            f"raw transfer proposal for {bundle.source_path}",
        )
        proposal_payload = _load(
            transfer_root / bundle.namespace / "validated_proposal.json",
            f"validated transfer proposal for {bundle.source_path}",
        )
        proposal = PaperTransferProposal.model_validate(proposal_payload.get("proposal"))
        proposals = {item.mechanism_id: item for item in proposal.mechanisms}
        if len(proposals) != len(proposal.mechanisms) or set(proposals) != expected:
            raise TransferAuditError(
                f"mechanism proposal coverage mismatch for {bundle.source_path}"
            )
        adjudicated_payload = _load(
            transfer_root / bundle.namespace / "adjudicated.json",
            f"adjudicated transfer for {bundle.source_path}",
        )
        paper_level_artifacts.extend(
            [raw_payload, proposal_payload, adjudicated_payload]
        )
        rows = adjudicated_payload.get("assessments")
        if not isinstance(rows, list):
            raise TransferAuditError("adjudicated assessments must be a list")
        assessments = [TransferabilityAssessment.model_validate(row) for row in rows]
        by_mechanism = {item.source_mechanism_id: item for item in assessments}
        if len(by_mechanism) != len(assessments) or set(by_mechanism) != expected:
            raise TransferAuditError(
                f"mechanism assessment coverage mismatch for {bundle.source_path}"
            )
        constraint_ids = {item.constraint_id for item in bundle.constraints}
        for mechanism_id, assessment in by_mechanism.items():
            if assessment.source_paper_id != bundle.source_path:
                raise TransferAuditError(
                    f"cross-paper assessment provenance for {mechanism_id}"
                )
            if set(assessment.blocking_constraints) - constraint_ids:
                raise TransferAuditError(
                    f"cross-paper constraint provenance for {mechanism_id}"
                )
            proposal_row = proposals[mechanism_id]
            for component in proposal_row.components:
                component_counts[f"{component.dimension}:{component.judgment}"] += 1
                value = assessment.score_components.get(component.dimension)
                if component.judgment == "unknown" and value != "unknown":
                    raise TransferAuditError(
                        f"unknown component was scored numerically for {mechanism_id}"
                    )
                if component.judgment != "unknown" and not isinstance(value, int):
                    raise TransferAuditError(
                        f"known component lacks numeric score for {mechanism_id}"
                    )
        all_assessments.extend(assessments)

    assessment_ids = [item.assessment_id for item in all_assessments]
    if len(assessment_ids) != len(set(assessment_ids)):
        raise TransferAuditError("duplicate assessment IDs in paper caches")
    aggregate_payload = _load(
        root / "derived/principles/transfer_assessments.json",
        "aggregate transfer assessments",
    )
    aggregate_rows = aggregate_payload.get("assessments")
    if not isinstance(aggregate_rows, list):
        raise TransferAuditError("aggregate assessments must be a list")
    aggregate = [TransferabilityAssessment.model_validate(row) for row in aggregate_rows]
    aggregate_ids = [item.assessment_id for item in aggregate]
    if len(aggregate_ids) != len(set(aggregate_ids)):
        raise TransferAuditError("duplicate assessment IDs in aggregate")
    if set(aggregate_ids) != set(assessment_ids):
        raise TransferAuditError("aggregate assessment IDs do not match paper caches")

    revisit_payload = _load(
        root / "derived/principles/source_revisit_registry.json",
        "source revisit registry",
    )
    revisit_rows = revisit_payload.get("revisits")
    if not isinstance(revisit_rows, list):
        raise TransferAuditError("source revisit registry rows must be a list")
    revisit_ids = [str(row.get("request_id", "")) for row in revisit_rows if isinstance(row, dict)]
    if len(revisit_ids) != len(set(revisit_ids)):
        raise TransferAuditError("duplicate qualified source revisit IDs")

    serialized = json.dumps(
        {
            "aggregate": aggregate_payload,
            "revisits": revisit_payload,
            "paper_level_artifacts": paper_level_artifacts,
        },
        ensure_ascii=False,
    )
    hidden_markers = ("PL30.xlsx", "新反应发现.pptx", "KNOWN_RETROSPECTIVE_SECRET")
    if any(marker in serialized for marker in hidden_markers):
        raise TransferAuditError("hidden-answer marker detected in transfer artifacts")
    status_counts = Counter(item.transfer_status for item in aggregate)
    return KnowledgeTransferAudit(
        paper_count=len(bundles),
        mechanism_count=len(expected_mechanism_ids),
        assessment_count=len(aggregate),
        unique_assessment_count=len(set(aggregate_ids)),
        revisit_count=len(revisit_rows),
        missing_paper_count=0,
        missing_mechanism_count=0,
        provenance_violation_count=0,
        status_counts=dict(sorted(status_counts.items())),
        component_judgment_counts=dict(sorted(component_counts.items())),
    )


def write_knowledge_transfer_audit(output_root: Path) -> Path:
    """Audit real artifacts and write the report only after all checks pass."""

    audit = audit_knowledge_transfer(output_root)
    destination = output_root.resolve() / "reports/knowledge_transfer_audit.json"
    _atomic_json(destination, audit.model_dump(mode="json"))
    return destination

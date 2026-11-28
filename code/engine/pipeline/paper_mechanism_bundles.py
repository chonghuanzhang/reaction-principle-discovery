"""Paper-scoped views over immutable normalized mechanism caches."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from pipeline.evidence_registry import EvidenceRegistrySummary, _atomic_json
from pipeline.principle_models import (
    BoundaryConstraint,
    MechanismEvidence,
    SourceRevisitRequest,
)


class PaperMechanismBundleError(RuntimeError):
    """Raised when queue provenance and normalization caches disagree."""


class PaperMechanismBundle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    namespace: str
    source_path: str
    source_sha256: str
    normalization_cache_key: str
    bundle_digest: str
    evidence_ids: tuple[str, ...]
    mechanisms: tuple[MechanismEvidence, ...]
    constraints: tuple[BoundaryConstraint, ...]
    revisits: tuple[SourceRevisitRequest, ...]


def _load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PaperMechanismBundleError(f"cannot read valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise PaperMechanismBundleError(f"expected JSON object: {path}")
    return value


def _qualified(namespace: str, local_id: str) -> str:
    if not local_id or "::" in local_id:
        raise PaperMechanismBundleError(f"invalid local provenance ID: {local_id}")
    return f"{namespace}::{local_id}"


def _bundle_digest(payload: dict) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def load_paper_mechanism_bundles(
    output_root: Path, *, source_paths: set[str] | None = None,
) -> tuple[PaperMechanismBundle, ...]:
    """Load queue-scoped normalization caches with globally unique provenance IDs."""

    output_root = output_root.resolve()
    registry_path = output_root / "derived/principles/evidence_registry.json"
    registry = EvidenceRegistrySummary.model_validate(_load_json(registry_path))
    if source_paths is not None:
        unknown_paths = source_paths - {record.source_path for record in registry.records}
        if unknown_paths:
            raise PaperMechanismBundleError(
                "requested sources outside evidence registry: " + ", ".join(sorted(unknown_paths))
            )
    bundles: list[PaperMechanismBundle] = []
    for record in registry.records:
        if source_paths is not None and record.source_path not in source_paths:
            continue
        namespace = record.sha256[:12]
        cache_path = (
            output_root
            / "derived/principles/normalization"
            / namespace
            / "validated.json"
        )
        payload = _load_json(cache_path)
        if payload.get("source_file") != record.source_path:
            raise PaperMechanismBundleError(
                f"normalization source path mismatch for {record.source_path}"
            )
        if payload.get("source_sha256") != record.sha256:
            raise PaperMechanismBundleError(
                f"normalization source SHA mismatch for {record.source_path}"
            )
        normalization = payload.get("normalization")
        if not isinstance(normalization, dict):
            raise PaperMechanismBundleError(
                f"normalization payload missing for {record.source_path}"
            )
        mechanisms = tuple(
            MechanismEvidence.model_validate(row).model_copy(
                update={
                    "mechanism_evidence_id": _qualified(
                        namespace, str(row.get("mechanism_evidence_id", ""))
                    ),
                    "source_paper_id": record.source_path,
                    "source_evidence_ids": tuple(
                        _qualified(namespace, str(value))
                        for value in row.get("source_evidence_ids", [])
                    ),
                }
            )
            for row in normalization.get("mechanism_evidence", [])
        )
        constraints = tuple(
            BoundaryConstraint.model_validate(row).model_copy(
                update={
                    "constraint_id": _qualified(
                        namespace, str(row.get("constraint_id", ""))
                    ),
                    "supporting_evidence_ids": tuple(
                        _qualified(namespace, str(value))
                        for value in row.get("supporting_evidence_ids", [])
                    ),
                    "contradictory_evidence_ids": tuple(
                        _qualified(namespace, str(value))
                        for value in row.get("contradictory_evidence_ids", [])
                    ),
                }
            )
            for row in normalization.get("boundary_constraints", [])
        )
        revisits = tuple(
            SourceRevisitRequest.model_validate(row).model_copy(
                update={
                    "request_id": _qualified(namespace, str(row.get("request_id", ""))),
                    "source_paper_id": record.source_path,
                }
            )
            for row in normalization.get("source_revisit_requests", [])
        )
        evidence_ids = tuple(
            sorted(
                {
                    evidence_id
                    for mechanism in mechanisms
                    for evidence_id in mechanism.source_evidence_ids
                }
                | {
                    evidence_id
                    for constraint in constraints
                    for evidence_id in (
                        *constraint.supporting_evidence_ids,
                        *constraint.contradictory_evidence_ids,
                    )
                }
            )
        )
        digest_material = {
            "namespace": namespace,
            "source_path": record.source_path,
            "source_sha256": record.sha256,
            "normalization_cache_key": payload.get("cache_key"),
            "mechanisms": [item.model_dump(mode="json") for item in mechanisms],
            "constraints": [item.model_dump(mode="json") for item in constraints],
            "revisits": [item.model_dump(mode="json") for item in revisits],
        }
        bundles.append(
            PaperMechanismBundle(
                namespace=namespace,
                source_path=record.source_path,
                source_sha256=record.sha256,
                normalization_cache_key=str(payload.get("cache_key", "")),
                bundle_digest=_bundle_digest(digest_material),
                evidence_ids=evidence_ids,
                mechanisms=mechanisms,
                constraints=constraints,
                revisits=revisits,
            )
        )
    return tuple(bundles)


def write_source_revisit_registry(
    output_root: Path, bundles: tuple[PaperMechanismBundle, ...]
) -> Path:
    """Write every qualified revisit without cross-paper local-ID collisions."""

    destination = output_root.resolve() / "derived/principles/source_revisit_registry.json"
    rows = [
        {
            "namespace": bundle.namespace,
            "source_path": bundle.source_path,
            **revisit.model_dump(mode="json"),
        }
        for bundle in bundles
        for revisit in bundle.revisits
    ]
    rows.sort(key=lambda row: str(row["request_id"]))
    _atomic_json(
        destination,
        {
            "paper_count": len(bundles),
            "revisit_count": len(rows),
            "revisits": rows,
        },
    )
    return destination

"""Build a leakage-clean, provenance-preserving v3 evidence source bundle."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Mapping

from pydantic import Field

from pipeline.evidence_registry import EvidenceRegistrySummary, _atomic_json
from pipeline.leakage_audit import (
    LeakagePolicy,
    assert_clean,
    audit_paths,
    audit_snapshot_bytes,
)
from pipeline.principle_models import FrozenStrictModel


class CleanSourceError(RuntimeError):
    """Raised when a clean source bundle cannot be built safely."""


class CleanSourceBundle(FrozenStrictModel):
    source_prefix: Path
    dependency_manifest_path: Path
    retained_paper_count: int = Field(ge=1)
    excluded_paper_count: int = Field(ge=0)
    retained_transfer_count: int = Field(ge=0)
    excluded_transfer_count: int = Field(ge=0)
    excluded_artifact_digests: tuple[str, ...]
    bundle_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def contains_sealed_content(value: object, policy: LeakagePolicy) -> bool:
    audit = audit_snapshot_bytes((("candidate.json", _json_bytes(value)),), policy)
    return bool(audit.hits)


def sanitize_seed_document(
    value: Mapping[str, object], policy: LeakagePolicy
) -> dict[str, object]:
    sanitized: dict[str, object] = {}
    for key, item in value.items():
        if isinstance(item, list):
            sanitized[key] = [
                child for child in item if not contains_sealed_content(child, policy)
            ]
        elif isinstance(item, Mapping):
            sanitized[key] = sanitize_seed_document(item, policy)
        elif isinstance(item, str) and contains_sealed_content(item, policy):
            if key.endswith("_id") or key.endswith("_ids"):
                raise CleanSourceError("sealed content occurred in a provenance identifier")
            sanitized[key] = "withheld by pre-reveal leakage policy"
        else:
            sanitized[key] = item
    return sanitized


def bind_seed_evidence_references(
    mechanism: Mapping[str, object],
    principle: Mapping[str, object],
    retained_evidence_ids: set[str],
) -> tuple[dict[str, object], dict[str, object]]:
    bound_mechanism = dict(mechanism)
    mechanism_ids = bound_mechanism.get("evidence_ids", [])
    if retained_evidence_ids and isinstance(mechanism_ids, list):
        bound_mechanism["evidence_ids"] = [
            item for item in mechanism_ids if item in retained_evidence_ids
        ]
    retained_mechanism_ids = set(bound_mechanism.get("evidence_ids", []))
    bound_principle = dict(principle)
    principle_ids = bound_principle.get("supporting_seed_evidence", [])
    if retained_evidence_ids and isinstance(principle_ids, list):
        bound_principle["supporting_seed_evidence"] = [
            item for item in principle_ids if item in retained_mechanism_ids
        ]
    return bound_mechanism, bound_principle


def filter_transfer_rows(
    rows: list[object],
    retained_source_paths: set[str],
    retained_seed_ids: set[str],
    policy: LeakagePolicy,
) -> tuple[dict[str, object], ...]:
    retained: list[dict[str, object]] = []
    for row in rows:
        if not isinstance(row, dict) or row.get("source_paper_id") not in retained_source_paths:
            continue
        seed_ids = row.get("seed_feature_ids")
        if (
            not isinstance(seed_ids, list)
            or not set(seed_ids) <= retained_seed_ids
            or contains_sealed_content(row, policy)
        ):
            continue
        retained.append(row)
    return tuple(retained)


def _digest_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bundle_identity(root: Path, policy: LeakagePolicy) -> str:
    primary_paths = (
        root / "derived/principles/seed_evidence.json",
        root / "derived/principles/seed_mechanism.json",
        root / "derived/principles/seed_principle.json",
        root / "derived/principles/transfer_assessments.json",
        root / "derived/principles/evidence_registry.json",
        root / "derived/full_corpus/queue.json",
    )
    registry = EvidenceRegistrySummary.model_validate(
        _load(root / "derived/principles/evidence_registry.json")
    )
    evidence_paths = tuple(
        path
        for record in registry.records
        for path in (
            root / record.validated_path,
            root
            / "derived/principles/normalization"
            / record.sha256[:12]
            / "validated.json",
        )
    )
    paths = (*primary_paths, *evidence_paths)
    material = {
        "sources": [(path.relative_to(root).as_posix(), _digest_file(path)) for path in paths],
        "policy": hashlib.sha256(_json_bytes(policy.sealed_terms)).hexdigest(),
    }
    return hashlib.sha256(_json_bytes(material)).hexdigest()


def _load(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CleanSourceError(f"unable to load source artifact digest={_digest_file(path)}") from exc
    if not isinstance(value, dict):
        raise CleanSourceError("source artifact must be a JSON object")
    return value


def build_clean_source_bundle(root: Path, policy: LeakagePolicy) -> CleanSourceBundle:
    root = root.resolve()
    identity = _bundle_identity(root, policy)
    prefix = Path("derived/principles_v3/clean_inputs") / identity
    destination = root / prefix
    principles = destination / "derived/principles"
    corpus = destination / "derived/full_corpus"
    principles.mkdir(parents=True, exist_ok=True)
    corpus.mkdir(parents=True, exist_ok=True)

    original_registry = EvidenceRegistrySummary.model_validate(
        _load(root / "derived/principles/evidence_registry.json")
    )
    retained_records = []
    excluded_digests: list[str] = []
    for record in original_registry.records:
        normalized_source = (
            root
            / "derived/principles/normalization"
            / record.sha256[:12]
            / "validated.json"
        )
        evidence_source = root / record.validated_path
        normalized_payload = _load(normalized_source)
        evidence_payload = _load(evidence_source)
        if contains_sealed_content(
            normalized_payload, policy
        ) or contains_sealed_content(evidence_payload, policy):
            excluded_digests.extend(
                (_digest_file(normalized_source), _digest_file(evidence_source))
            )
            continue
        normalized_target = (
            principles / "normalization" / record.sha256[:12] / "validated.json"
        )
        normalized_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(normalized_source, normalized_target)
        evidence_target = destination / record.validated_path
        evidence_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(evidence_source, evidence_target)
        retained_records.append(
            record.model_copy(
                update={
                    "validated_path": evidence_target.relative_to(root).as_posix()
                }
            )
        )
    retained_paths = {record.source_path for record in retained_records}
    if not retained_records:
        raise CleanSourceError("leakage policy excluded every normalized mechanism record")

    queue = _load(root / "derived/full_corpus/queue.json")
    items = [
        item
        for item in queue.get("items", [])
        if isinstance(item, dict) and item.get("source_path") in retained_paths
    ]
    duplicate_exclusions = queue.get("duplicate_exclusions", [])
    queue_digest = hashlib.sha256(
        json.dumps(
            {"items": items, "duplicate_exclusions": duplicate_exclusions},
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    clean_queue = {
        **queue,
        "queue_digest": queue_digest,
        "items": items,
        "duplicate_exclusions": duplicate_exclusions,
    }
    _atomic_json(corpus / "queue.json", clean_queue)

    clean_registry = original_registry.model_copy(
        update={
            "queue_digest": queue_digest,
            "queue_paper_count": len(retained_records),
            "scoped_record_count": len(retained_records),
            "evidence_item_count": sum(item.evidence_item_count for item in retained_records),
            "contradiction_count": sum(item.contradiction_count for item in retained_records),
            "visual_review_page_count": sum(
                item.visual_review_page_count for item in retained_records
            ),
            "off_queue_cache_count": 0,
            "missing_source_paths": (),
            "records": tuple(retained_records),
        }
    )
    _atomic_json(
        principles / "evidence_registry.json", clean_registry.model_dump(mode="json")
    )

    seed_source = root / "derived/principles/seed_evidence.json"
    seed = _load(seed_source)
    wrapper = "evidence" if "evidence" in seed else "seed_evidence"
    rows = seed.get(wrapper, [])
    clean_rows = [row for row in rows if not contains_sealed_content(row, policy)]
    if clean_rows:
        clean_seed = {key: value for key, value in seed.items() if key != wrapper}
        clean_seed[wrapper] = clean_rows
        _atomic_json(principles / "seed_evidence.json", clean_seed)
    else:
        excluded_digests.append(_digest_file(seed_source))
    retained_seed_ids = {
        str(row["evidence"]["evidence_id"])
        for row in clean_rows
        if isinstance(row, dict)
        and isinstance(row.get("evidence"), dict)
        and isinstance(row["evidence"].get("evidence_id"), str)
    }
    mechanism = sanitize_seed_document(
        _load(root / "derived/principles/seed_mechanism.json"), policy
    )
    principle = sanitize_seed_document(
        _load(root / "derived/principles/seed_principle.json"), policy
    )
    mechanism, principle = bind_seed_evidence_references(
        mechanism, principle, retained_seed_ids
    )
    _atomic_json(principles / "seed_mechanism.json", mechanism)
    _atomic_json(principles / "seed_principle.json", principle)

    transfer_source = root / "derived/principles/transfer_assessments.json"
    transfer = _load(transfer_source)
    rows = transfer.get("assessments", [])
    retained_transfer = filter_transfer_rows(
        rows, retained_paths, set(mechanism.get("evidence_ids", [])), policy
    )
    clean_transfer = {
        **transfer,
        "assessments": retained_transfer,
        "assessment_count": len(retained_transfer),
        "paper_count": len({row["source_paper_id"] for row in retained_transfer}),
    }
    _atomic_json(principles / "transfer_assessments.json", clean_transfer)

    dependencies = sorted(
        (
            *principles.rglob("*.json"),
            corpus / "queue.json",
        )
    )
    dependencies.append(root / "config/seed_claim_types_v3.yaml")
    dependency_manifest = destination / "import_dependency_manifest.json"
    _atomic_json(
        dependency_manifest,
        {
            "dependency_paths": [
                os.path.relpath(path, dependency_manifest.parent) for path in dependencies
            ],
            "query_ids": [],
        },
    )
    bound_policy = policy.model_copy(update={"run_manifest_path": dependency_manifest})
    assert_clean(audit_paths(dependencies, bound_policy))
    bundle = CleanSourceBundle(
        source_prefix=prefix,
        dependency_manifest_path=dependency_manifest.relative_to(root),
        retained_paper_count=len(retained_records),
        excluded_paper_count=len(original_registry.records) - len(retained_records),
        retained_transfer_count=len(retained_transfer),
        excluded_transfer_count=len(rows) - len(retained_transfer),
        excluded_artifact_digests=tuple(sorted(excluded_digests)),
        bundle_digest=identity,
    )
    _atomic_json(
        destination / "clean_source_manifest.json", bundle.model_dump(mode="json")
    )
    return bundle

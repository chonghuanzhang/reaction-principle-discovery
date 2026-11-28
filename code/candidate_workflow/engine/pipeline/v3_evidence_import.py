"""Fail-closed import of traceable, uncontaminated v2 evidence into v3."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import Field, ValidationError, field_serializer, model_validator

from pipeline.evidence_registry import (
    EvidenceRegistrySummary,
    _atomic_json,
    file_digest,
)
from pipeline.leakage_audit import (
    LeakageAuditError,
    LeakagePolicy,
    assert_clean,
    audit_paths,
)
from pipeline.mechanism_normalization import MechanismNormalizationPayload
from pipeline.principle_models import (
    FrozenStrictModel,
    SeedEvidence,
    SeedMechanism,
    SeedPrinciple,
    TransferabilityAssessment,
)
from pipeline.seed_claim_types import (
    SEED_CLAIM_TYPE_CONTRACT_PATH,
    SEED_EVIDENCE_PROJECTION_PATH,
    SeedClaimTypeContract,
    SeedClaimTypeError,
    SeedEvidenceProjection,
    parse_seed_claim_type_contract,
    project_seed_evidence,
    seed_claim_type_contract_digest,
)
from pipeline.v3_models import ExplorationBriefV3, v3_brief_digest


class EvidenceImportError(RuntimeError):
    """Raised when evidence cannot be traced, validated, or safely imported."""


class EvidenceImportArtifact(FrozenStrictModel):
    """One immutable evidence source that crossed the v3 import boundary."""

    path: str = Field(min_length=1)
    artifact_type: str = Field(pattern=r"^(seed|normalized_mechanism|transfer)$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    schema_version: str = Field(min_length=1)


class EvidenceImportManifest(FrozenStrictModel):
    """Cache identity and provenance for the reusable v3 evidence layer."""

    version: str = Field(default="3.0", frozen=True)
    brief_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    leakage_policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    queue_digest: str = Field(min_length=1)
    queue_scope: tuple[str, ...]
    provenance_paths: tuple[str, ...]
    seed_claim_type_contract_version: str = Field(min_length=1)
    seed_claim_type_contract_path: str = Field(min_length=1)
    seed_claim_type_contract_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    seed_claim_type_contract_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    accepted: tuple[EvidenceImportArtifact, ...]
    rejected_paths: tuple[str, ...]
    rejection_reasons: Mapping[str, str]
    schema_versions: Mapping[str, str]
    cache_namespace: str = Field(min_length=1)
    manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_rejections(self) -> "EvidenceImportManifest":
        if set(self.rejected_paths) != set(self.rejection_reasons):
            raise ValueError("rejection reasons must exactly cover rejected paths")
        return self

    @field_serializer("rejection_reasons", "schema_versions")
    def serialize_mappings(self, value: Mapping[str, str]) -> dict[str, str]:
        return dict(sorted(value.items()))

    @property
    def accepted_types(self) -> tuple[str, ...]:
        present = {artifact.artifact_type for artifact in self.accepted}
        return tuple(
            artifact_type
            for artifact_type in ("seed", "normalized_mechanism", "transfer")
            if artifact_type in present
        )

    @property
    def accepted_paths(self) -> tuple[str, ...]:
        return tuple(artifact.path for artifact in self.accepted)


_SEED_FILENAMES = frozenset(
    {"seed_evidence.json", "seed_mechanism.json", "seed_principle.json"}
)
_V2_REJECTION_REASONS = {
    "exploration_brief.json": "v2_exploration_artifact",
    "role_aware_evidence_index.json": "v2_taxonomy_artifact",
    "coverage_audit.json": "v2_coverage_artifact",
    "taxonomy_proposals.json": "v2_taxonomy_artifact",
    "family_predictions.json": "v2_family_artifact",
    "provisional_candidates.json": "v2_candidate_artifact",
}
_SCHEMA_VERSIONS = {
    "seed": "pipeline.principle_models.seed-v1",
    "seed_projection": "pipeline.seed_claim_types.projection-v1",
    "normalized_mechanism": "pipeline.principle_models.normalization-v1",
    "transfer": "pipeline.principle_models.transfer-v1",
    "paper_provenance": "pipeline.evidence_registry.queue-v1",
}
_NORMALIZATION_TOP_LEVEL_KEYS = frozenset(
    {"cache_key", "source_file", "source_sha256", "normalization", "usage"}
)
_NORMALIZATION_KEYS = frozenset(
    {"mechanism_evidence", "boundary_constraints", "source_revisit_requests"}
)
_USAGE_KEYS = frozenset({"input_tokens", "output_tokens", "total_tokens"})
_PROHIBITED_CONTENT_KEYS = frozenset(
    {
        "chemical_space",
        "chemical_space_cache",
        "coverage_audit",
        "exploration_brief",
        "family_predictions",
        "provisional_candidates",
        "role_aware_evidence_index",
        "taxonomy_proposals",
    }
)


@dataclass
class _AcceptedReferences:
    seed_evidence_ids: set[str] = field(default_factory=set)
    mechanism_sources: dict[str, str] = field(default_factory=dict)
    literature_evidence_sources: dict[str, str] = field(default_factory=dict)
    constraint_sources: dict[str, str] = field(default_factory=dict)


def _load_json(path: Path, label: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceImportError(f"required {label} is missing or invalid") from exc
    if not isinstance(value, dict):
        raise EvidenceImportError(f"required {label} must be a JSON object")
    return value


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError as exc:
        raise EvidenceImportError("evidence artifact escaped output root") from exc


def _policy_digest(policy: LeakagePolicy) -> str:
    encoded = json.dumps(
        policy.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _manifest_digest(material: Mapping[str, object]) -> str:
    encoded = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _queue_scope(queue: dict[str, object]) -> tuple[str, tuple[str, ...], dict[str, str]]:
    queue_digest = queue.get("queue_digest")
    items = queue.get("items")
    if not isinstance(queue_digest, str) or not queue_digest:
        raise EvidenceImportError("queue manifest requires queue_digest")
    if not isinstance(items, list):
        raise EvidenceImportError("queue manifest requires items")
    paths: list[str] = []
    sha_by_path: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict):
            raise EvidenceImportError("queue manifest contains an invalid item")
        source_path, source_sha = item.get("source_path"), item.get("sha256")
        if not isinstance(source_path, str) or not isinstance(source_sha, str):
            raise EvidenceImportError("queue item requires source_path and sha256")
        if source_path in sha_by_path:
            raise EvidenceImportError("queue manifest contains duplicate source paths")
        paths.append(source_path)
        sha_by_path[source_path] = source_sha
    return queue_digest, tuple(sorted(paths)), sha_by_path


def _validate_seed(
    path: Path,
    payload: dict[str, object],
    *,
    source_path: str,
    source_sha256: str,
    claim_type_contract: SeedClaimTypeContract,
) -> tuple[set[str], set[str], set[str], SeedEvidenceProjection | None]:
    """Return Seed evidence, mechanism anchors, and principle anchors."""

    try:
        if path.name == "seed_evidence.json":
            has_legacy_wrapper = "seed_evidence" in payload
            has_current_wrapper = "evidence" in payload
            if has_legacy_wrapper == has_current_wrapper:
                raise ValueError("seed evidence requires exactly one supported wrapper")
            if has_current_wrapper:
                if set(payload) != {"cache_key", "evidence"} or not isinstance(
                    payload.get("cache_key"), str
                ):
                    raise ValueError("current seed evidence wrapper is invalid")
                rows = payload.get("evidence")
            else:
                rows = payload.get("seed_evidence")
            if not isinstance(rows, list):
                raise ValueError("seed_evidence must be a list")
            seeds = tuple(SeedEvidence.model_validate(row) for row in rows)
            return (
                {seed.evidence.evidence_id for seed in seeds},
                set(),
                set(),
                project_seed_evidence(
                    seeds,
                    source_path=source_path,
                    source_sha256=source_sha256,
                    contract=claim_type_contract,
                ),
            )
        elif path.name == "seed_mechanism.json":
            return (
                set(),
                set(SeedMechanism.model_validate(payload).evidence_ids),
                set(),
                None,
            )
        elif path.name == "seed_principle.json":
            return (
                set(),
                set(),
                set(SeedPrinciple.model_validate(payload).supporting_seed_evidence),
                None,
            )
        else:
            raise ValueError("unknown seed artifact")
    except SeedClaimTypeError as exc:
        raise EvidenceImportError(str(exc)) from exc
    except (ValidationError, ValueError) as exc:
        raise EvidenceImportError("invalid grounded seed artifact") from exc


def _validate_normalization(
    payload: dict[str, object], *, source_path: str, source_sha256: str, namespace: str,
    references: _AcceptedReferences,
) -> str:
    _require_exact_keys(payload, _NORMALIZATION_TOP_LEVEL_KEYS, "normalization top-level")
    _reject_prohibited_content(payload)
    if payload.get("source_file") != source_path or payload.get("source_sha256") != source_sha256:
        raise EvidenceImportError("normalized mechanism provenance does not match queue")
    if not isinstance(payload.get("cache_key"), str) or not payload["cache_key"]:
        raise EvidenceImportError("normalized mechanism cache metadata is invalid")
    _validate_usage(payload.get("usage"))
    normalization = payload.get("normalization")
    if not isinstance(normalization, dict):
        raise EvidenceImportError("normalized mechanism lacks normalization payload")
    _require_exact_keys(normalization, _NORMALIZATION_KEYS, "normalization payload")
    try:
        normalized = MechanismNormalizationPayload.model_validate(normalization)
        for mechanism in normalized.mechanism_evidence:
            mechanism_id = _qualified_id(namespace, mechanism.mechanism_evidence_id)
            if mechanism_id in references.mechanism_sources:
                raise ValueError("duplicate normalized mechanism ID")
            references.mechanism_sources[mechanism_id] = source_path
            for evidence_id in mechanism.source_evidence_ids:
                references.literature_evidence_sources[
                    _qualified_id(namespace, evidence_id)
                ] = source_path
        for constraint in normalized.boundary_constraints:
            constraint_id = _qualified_id(namespace, constraint.constraint_id)
            if constraint_id in references.constraint_sources:
                raise ValueError("duplicate normalized constraint ID")
            references.constraint_sources[constraint_id] = source_path
            for evidence_id in (
                *constraint.supporting_evidence_ids,
                *constraint.contradictory_evidence_ids,
            ):
                references.literature_evidence_sources[
                    _qualified_id(namespace, evidence_id)
                ] = source_path
    except (ValidationError, ValueError) as exc:
        raise EvidenceImportError("invalid normalized mechanism artifact") from exc
    return _manifest_digest(
        {
            "cache_key": payload["cache_key"],
            "source_file": source_path,
            "source_sha256": source_sha256,
            "normalization": {
                "mechanism_evidence": [
                    item.model_dump(mode="json")
                    for item in normalized.mechanism_evidence
                ],
                "boundary_constraints": [
                    item.model_dump(mode="json")
                    for item in normalized.boundary_constraints
                ],
            },
        }
    )


def _require_exact_keys(
    payload: Mapping[str, object], allowed: frozenset[str], label: str
) -> None:
    unknown = set(payload) - allowed
    if unknown:
        raise EvidenceImportError(f"{label} contains unallowlisted keys")


def _reject_prohibited_content(value: object) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if isinstance(key, str) and key.casefold() in _PROHIBITED_CONTENT_KEYS:
                raise EvidenceImportError("normalized mechanism contains prohibited content")
            _reject_prohibited_content(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_prohibited_content(nested)


def _validate_usage(value: object) -> None:
    if not isinstance(value, dict) or set(value) != _USAGE_KEYS:
        raise EvidenceImportError("normalization usage is invalid")
    if any(
        token_count is not None
        and (not isinstance(token_count, int) or isinstance(token_count, bool))
        for token_count in value.values()
    ):
        raise EvidenceImportError("normalization usage is invalid")


def _qualified_id(namespace: str, local_id: str) -> str:
    if not local_id or "::" in local_id:
        raise ValueError("invalid local normalized provenance ID")
    return f"{namespace}::{local_id}"


def _validate_transfer(
    payload: dict[str, object], queue_scope: tuple[str, ...], references: _AcceptedReferences
) -> None:
    rows = payload.get("assessments")
    if not isinstance(rows, list):
        raise EvidenceImportError("transfer assessments must be a list")
    try:
        for row in rows:
            assessment = TransferabilityAssessment.model_validate(row)
            if assessment.source_paper_id not in queue_scope:
                raise ValueError("transfer source is outside the current queue")
            if assessment.source_mechanism_id is None:
                raise ValueError("transfer mechanism reference is required")
            mechanism_source = references.mechanism_sources.get(assessment.source_mechanism_id)
            if mechanism_source is None or mechanism_source != assessment.source_paper_id:
                raise ValueError("transfer mechanism reference is not accepted")
            if not set(assessment.source_evidence_ids) <= set(
                references.literature_evidence_sources
            ):
                raise ValueError("transfer evidence reference is not accepted")
            if any(
                references.literature_evidence_sources[evidence_id]
                != assessment.source_paper_id
                for evidence_id in assessment.source_evidence_ids
            ):
                raise ValueError("transfer evidence reference has foreign provenance")
            if not set(assessment.seed_feature_ids) <= references.seed_evidence_ids:
                raise ValueError("transfer seed reference is not accepted")
            if not set(assessment.blocking_constraints) <= set(references.constraint_sources):
                raise ValueError("transfer constraint reference is not accepted")
            if any(
                references.constraint_sources[constraint_id] != assessment.source_paper_id
                for constraint_id in assessment.blocking_constraints
            ):
                raise ValueError("transfer constraint reference has foreign provenance")
    except ValidationError as exc:
        raise EvidenceImportError("invalid transfer assessment artifact") from exc
    except ValueError as exc:
        raise EvidenceImportError("invalid transfer reference") from exc


def _rejections(
    root: Path, accepted_paths: set[Path], provenance_paths: set[Path]
) -> tuple[tuple[str, ...], dict[str, str]]:
    rejected: dict[str, str] = {}
    v2_root = root / "derived" / "principles"
    for path in sorted(v2_root.rglob("*")) if v2_root.is_dir() else ():
        if not path.is_file() or path in accepted_paths or path in provenance_paths:
            continue
        relative = _relative(root, path)
        filename = path.name
        if filename in _V2_REJECTION_REASONS:
            reason = _V2_REJECTION_REASONS[filename]
        elif "chemical_space" in relative or "chemical-space" in relative:
            reason = "v2_chemical_space_cache"
        elif "/semantic_transfer/" in f"/{relative}":
            reason = "v2_transfer_model_cache"
        elif "report" in filename or "/reports/" in f"/{relative}":
            reason = "v2_report_artifact"
        else:
            reason = "not_allowlisted_v2_artifact"
        rejected[relative] = reason
    for root_path in (
        root / "derived" / "chemical_space",
        root / "derived" / "chemical-space",
        root / "reports",
    ):
        if not root_path.is_dir():
            continue
        for path in sorted(candidate for candidate in root_path.rglob("*") if candidate.is_file()):
            rejected[_relative(root, path)] = (
                "v2_chemical_space_cache"
                if root_path.name in {"chemical_space", "chemical-space"}
                else "v2_report_artifact"
            )
    return tuple(sorted(rejected)), dict(sorted(rejected.items()))


def import_reusable_evidence(
    output_root: Path,
    brief: ExplorationBriefV3,
    policy: LeakagePolicy,
    *,
    source_prefix: Path | None = None,
) -> EvidenceImportManifest:
    """Import only traced source-grounded evidence after an exact leakage audit."""

    root = output_root.resolve()
    source_root = root
    if source_prefix is not None:
        if source_prefix.is_absolute() or ".." in source_prefix.parts:
            raise EvidenceImportError("clean source prefix must be root-relative")
        source_root = (root / source_prefix).resolve()
        try:
            source_root.relative_to(root)
        except ValueError as exc:
            raise EvidenceImportError("clean source prefix escapes output root") from exc
    principles = source_root / "derived" / "principles"
    queue_path = source_root / "derived" / "full_corpus" / "queue.json"
    registry_path = principles / "evidence_registry.json"
    root_contract_path = root / SEED_CLAIM_TYPE_CONTRACT_PATH
    if _relative(root, root_contract_path) != SEED_CLAIM_TYPE_CONTRACT_PATH:
        raise EvidenceImportError("Seed claim type contract path is not canonical")
    try:
        claim_type_contract_bytes = root_contract_path.read_bytes()
        claim_type_contract = parse_seed_claim_type_contract(
            claim_type_contract_bytes
        )
    except OSError as exc:
        raise EvidenceImportError(
            "required Seed claim type contract is missing"
        ) from exc
    except SeedClaimTypeError as exc:
        raise EvidenceImportError(str(exc)) from exc
    claim_type_contract_digest = seed_claim_type_contract_digest(
        claim_type_contract
    )
    claim_type_contract_sha256 = hashlib.sha256(
        claim_type_contract_bytes
    ).hexdigest()
    queue = _load_json(queue_path, "queue manifest")
    registry_payload = _load_json(registry_path, "evidence registry")
    try:
        registry = EvidenceRegistrySummary.model_validate(registry_payload)
    except ValidationError as exc:
        raise EvidenceImportError("invalid evidence registry") from exc
    queue_digest, queue_scope, queue_sha = _queue_scope(queue)
    if (
        registry.queue_digest != queue_digest
        or registry.queue_paper_count != len(queue_scope)
        or registry.scoped_record_count != len(registry.records)
    ):
        raise EvidenceImportError("evidence registry does not match current queue scope")
    if registry.missing_source_paths:
        raise EvidenceImportError("evidence registry has missing queue-scoped sources")

    accepted: list[EvidenceImportArtifact] = []
    accepted_paths: set[Path] = set()
    references = _AcceptedReferences()
    seed_evidence_ids: set[str] = set()
    seed_mechanism_ids: set[str] = set()
    seed_principle_ids: set[str] = set()
    seed_projection: SeedEvidenceProjection | None = None
    for filename in sorted(_SEED_FILENAMES):
        path = principles / filename
        if not path.is_file():
            if filename == "seed_mechanism.json":
                raise EvidenceImportError("required seed mechanism is missing")
            continue
        payload = _load_json(path, "seed evidence")
        source_digest = file_digest(path)
        evidence_ids, mechanism_ids, principle_ids, projection = _validate_seed(
            path,
            payload,
            source_path=_relative(root, path),
            source_sha256=source_digest,
            claim_type_contract=claim_type_contract,
        )
        seed_evidence_ids.update(evidence_ids)
        seed_mechanism_ids.update(mechanism_ids)
        seed_principle_ids.update(principle_ids)
        accepted_paths.add(path)
        if projection is not None:
            if seed_projection is not None:
                raise EvidenceImportError("duplicate Seed evidence projection")
            seed_projection = projection
            continue
        accepted.append(
            EvidenceImportArtifact(
                path=_relative(root, path),
                artifact_type="seed",
                sha256=source_digest,
                evidence_digest=source_digest,
                schema_version=_SCHEMA_VERSIONS["seed"],
            )
        )

    if seed_evidence_ids and not seed_mechanism_ids <= seed_evidence_ids:
        raise EvidenceImportError("seed mechanism references ungrounded seed evidence")
    if not seed_principle_ids <= seed_mechanism_ids:
        raise EvidenceImportError("seed Principle references ungrounded seed evidence")
    references.seed_evidence_ids = seed_mechanism_ids

    record_paths = {record.source_path for record in registry.records}
    if record_paths != set(queue_scope):
        raise EvidenceImportError("evidence registry records do not equal current queue scope")
    for record in registry.records:
        if queue_sha.get(record.source_path) != record.sha256:
            raise EvidenceImportError("evidence registry SHA does not match current queue")
        path = principles / "normalization" / record.sha256[:12] / "validated.json"
        payload = _load_json(path, "normalized mechanism")
        evidence_digest = _validate_normalization(
            payload,
            source_path=record.source_path,
            source_sha256=record.sha256,
            namespace=record.sha256[:12],
            references=references,
        )
        accepted_paths.add(path)
        accepted.append(
            EvidenceImportArtifact(
                path=_relative(root, path),
                artifact_type="normalized_mechanism",
                sha256=file_digest(path),
                evidence_digest=evidence_digest,
                schema_version=_SCHEMA_VERSIONS["normalized_mechanism"],
            )
        )

    transfer_path = principles / "transfer_assessments.json"
    transfer = _load_json(transfer_path, "transfer assessments")
    _validate_transfer(transfer, queue_scope, references)
    accepted_paths.add(transfer_path)
    source_digest = file_digest(transfer_path)
    accepted.append(
        EvidenceImportArtifact(
            path=_relative(root, transfer_path),
            artifact_type="transfer",
            sha256=source_digest,
            evidence_digest=source_digest,
            schema_version=_SCHEMA_VERSIONS["transfer"],
        )
    )

    provenance_paths = {queue_path, registry_path}
    audit_dependencies = tuple(
        sorted(
            (*accepted_paths, *provenance_paths, root_contract_path),
            key=str,
        )
    )
    try:
        assert_clean(audit_paths(audit_dependencies, policy))
    except LeakageAuditError as exc:
        raise EvidenceImportError("leakage audit rejected reusable evidence") from exc

    manifest_provenance_paths = set(provenance_paths)
    if seed_projection is not None:
        projection_path = root / SEED_EVIDENCE_PROJECTION_PATH
        _atomic_json(projection_path, seed_projection.model_dump(mode="json"))
        projection_digest = file_digest(projection_path)
        accepted.append(
            EvidenceImportArtifact(
                path=SEED_EVIDENCE_PROJECTION_PATH,
                artifact_type="seed",
                sha256=projection_digest,
                evidence_digest=projection_digest,
                schema_version=_SCHEMA_VERSIONS["seed_projection"],
            )
        )
        manifest_provenance_paths.add(root / seed_projection.source_path)
    accepted.sort(key=lambda artifact: artifact.path)
    rejected_paths, rejection_reasons = _rejections(root, accepted_paths, provenance_paths)
    digest_material = {
        "version": "3.0",
        "brief_digest": v3_brief_digest(brief),
        "leakage_policy_digest": _policy_digest(policy),
        "queue_digest": queue_digest,
        "queue_scope": queue_scope,
        "provenance_paths": tuple(
            sorted(_relative(root, path) for path in manifest_provenance_paths)
        ),
        "seed_claim_type_contract_version": claim_type_contract.version,
        "seed_claim_type_contract_path": SEED_CLAIM_TYPE_CONTRACT_PATH,
        "seed_claim_type_contract_digest": claim_type_contract_digest,
        "seed_claim_type_contract_sha256": claim_type_contract_sha256,
        "accepted": [artifact.model_dump(mode="json") for artifact in accepted],
        "schema_versions": _SCHEMA_VERSIONS,
    }
    digest = _manifest_digest(digest_material)
    manifest = EvidenceImportManifest(
        **digest_material,
        rejected_paths=rejected_paths,
        rejection_reasons=rejection_reasons,
        cache_namespace=f"principles_v3/evidence/{digest}",
        manifest_digest=digest,
    )
    _atomic_json(
        root / "derived" / "principles_v3" / "evidence_import_manifest.json",
        manifest.model_dump(mode="json"),
    )
    return manifest

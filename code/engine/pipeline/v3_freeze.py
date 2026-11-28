"""Externally anchored immutable Freeze 1 -> Freeze 2 -> Freeze 3 chain."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import stat
import tempfile
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

from pydantic import Field, field_serializer, model_validator

from pipeline.diagnostic_design import (
    BoundaryFalsificationRecord,
    DiagnosticDesignError,
    DiagnosticDesignProposal,
    DiagnosticFailureRecord,
    DiagnosticRecord,
    DiagnosticSuccessRecord,
    FamilyDiagnosticPlan,
    RepresentativeInventoryRecord,
    RepresentativeReadinessRecord,
    _build_plan,
    design_family_diagnostics,
    restore_diagnostic_record,
    restore_representative_inventory_record,
    restore_representative_readiness_record,
    verify_family_diagnostic_plan,
)
from pipeline.family_canonicalization import CanonicalFamily, CanonicalTaxonomy
from pipeline.family_evaluation import (
    EVIDENCE_IMPORT_MANIFEST_ARTIFACT_KEY,
    EVIDENCE_REGISTRY_ARTIFACT_KEY,
    FAMILY_EVALUATION_RUBRIC_ARTIFACT_KEY,
    FROZEN_PRINCIPLES_ARTIFACT_KEY,
    SCORING_RUBRIC_ARTIFACT_KEY,
    EvaluationRubric,
    EvidenceQualificationContext,
    EvidenceQualificationError,
    FrozenDependencyDigest,
    QualifiedEvidenceRecord,
    ScoredFamilyEvaluation,
    _context_content_digest,
    _build_scored_evaluation,
    evaluation_rubric_digest,
    build_evidence_qualification_context,
    restore_evidence_qualification_context,
    score_family,
    validated_evidence_artifact_key,
    verify_scored_family_evaluation,
)
from pipeline.evidence_registry import EvidenceRegistrySummary
from pipeline.leakage_audit import (
    LeakageAudit,
    LeakageAuditError,
    LeakagePolicy,
    StructureFingerprintFactory,
    assert_clean,
    audit_snapshot_bytes,
    audit_paths,
    verify_policy_structure_factory,
    verify_structure_fingerprint_receipt,
)
from pipeline.principle_models import FrozenReactionPrincipleSet, FrozenStrictModel
from pipeline.principle_models import ReactionPrinciple
from pipeline.ranking_robustness import (
    RankingAnalysis,
    RankingAnalysisError,
    _build_ranking_analysis,
    analyze_ranking,
    verify_ranking_analysis,
)
from pipeline.saturation import (
    MechanismCoverageAudit,
    SaturationAudit,
    evaluate_saturation,
)
from pipeline.taxonomy_discovery import TaxonomyLaneResult
from pipeline.v3_evidence_import import (
    EvidenceImportError,
    EvidenceImportManifest,
    _rejections,
    import_reusable_evidence,
)
from pipeline.v3_models import ExplorationBriefV3, FreezeManifestV3, v3_brief_digest


FREEZE_DIRECTORY = Path("derived/principles_v3/freezes")
FREEZE_OBJECT_DIRECTORY = FREEZE_DIRECTORY / "objects"
FREEZE_MANIFEST_PATHS: Mapping[str, Path] = MappingProxyType(
    {
        "Freeze 1": FREEZE_DIRECTORY / "freeze_1_manifest.json",
        "Freeze 2": FREEZE_DIRECTORY / "freeze_2_manifest.json",
        "Freeze 3": FREEZE_DIRECTORY / "freeze_3_manifest.json",
    }
)
_STAGES = ("Freeze 1", "Freeze 2", "Freeze 3")
_HEX = frozenset("0123456789abcdef")
_CRITICAL_AUDIT_CHECKS = (
    "authoritative_evaluations",
    "deterministic_ranking",
    "complete_diagnostics",
    "environment_provenance",
    "fixed_sr001_nucleophile_condition",
)
_FROZEN_PRINCIPLES_PATH = Path(
    "derived/principles_v3/frozen_principles.json"
)


class V3FreezeError(RuntimeError):
    """Raised when an immutable v3 freeze cannot be authenticated."""


class ModelArtifactExecutionV3(FrozenStrictModel):
    response_id: str = Field(min_length=1)
    cache_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["completed"] = "completed"
    usage_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class ModelExecutionMetadataV3(FrozenStrictModel):
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    configuration_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    parameters: Mapping[str, str | int | float | bool | None] = Field(min_length=1)
    execution_id: str = Field(min_length=1)
    started_at: str = Field(min_length=1)
    completed_at: str = Field(min_length=1)
    artifacts: tuple[ModelArtifactExecutionV3, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def freeze_parameters(self) -> "ModelExecutionMetadataV3":
        started = _timestamp(self.started_at)
        completed = _timestamp(self.completed_at)
        if started > completed:
            raise ValueError("model execution timestamps are out of order")
        tuples = tuple(
            (
                item.response_id,
                item.cache_key,
                item.output_digest,
                item.status,
                item.usage_digest,
            )
            for item in self.artifacts
        )
        if len(tuples) != len(set(tuples)):
            raise ValueError("model artifact execution tuples must be unique")
        object.__setattr__(
            self, "parameters", MappingProxyType(dict(sorted(self.parameters.items())))
        )
        return self

    @field_serializer("parameters")
    def serialize_parameters(
        self, value: Mapping[str, str | int | float | bool | None]
    ) -> dict[str, str | int | float | bool | None]:
        return dict(value)


class FreezeEnvironmentV3(FrozenStrictModel):
    software_version: str = Field(min_length=1)
    python_version: str = Field(min_length=1)
    dependency_lock_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    execution_id: str = Field(min_length=1)
    started_at: str = Field(min_length=1)
    completed_at: str = Field(min_length=1)
    model_executions: tuple[ModelExecutionMetadataV3, ...] = Field(min_length=1)
    workflow_phase: Literal["fixed_sr001_nucleophile_condition"] = (
        "fixed_sr001_nucleophile_condition"
    )

    @model_validator(mode="after")
    def validate_execution(self) -> "FreezeEnvironmentV3":
        started = _timestamp(self.started_at)
        completed = _timestamp(self.completed_at)
        if started > completed:
            raise ValueError("environment execution timestamps are out of order")
        ids = tuple(item.execution_id for item in self.model_executions)
        if len(ids) != len(set(ids)):
            raise ValueError("model execution IDs must be unique")
        if any(
            _timestamp(item.started_at) < started
            or _timestamp(item.completed_at) > completed
            for item in self.model_executions
        ):
            raise ValueError("model execution timestamp is outside environment bounds")
        return self


class FreezeOneInputs(FrozenStrictModel):
    brief: ExplorationBriefV3
    leakage_policy: LeakagePolicy
    hidden_registry_commitment: str = Field(pattern=r"^[0-9a-f]{64}$")
    software_version: str = Field(min_length=1)
    created_at: str = Field(min_length=1)
    evidence_source_prefix: Path | None = None

    @model_validator(mode="after")
    def require_exact_contracts(self) -> "FreezeOneInputs":
        if type(self.brief) is not ExplorationBriefV3:
            raise TypeError("Freeze 1 requires the exact ExplorationBriefV3 type")
        if type(self.leakage_policy) is not LeakagePolicy:
            raise TypeError("Freeze 1 requires the exact LeakagePolicy type")
        return self


class FreezeTwoTaxonomyInputs(FrozenStrictModel):
    taxonomy: CanonicalTaxonomy
    source_results: tuple[TaxonomyLaneResult, ...] = Field(min_length=1)
    round_source_results: tuple[tuple[TaxonomyLaneResult, ...], ...] = Field(
        min_length=2
    )
    taxonomy_rounds: tuple[CanonicalTaxonomy, ...] = Field(min_length=2)
    coverage: MechanismCoverageAudit
    saturation_config: Mapping[str, object]
    scoring_policy: EvaluationRubric
    trusted_freeze_one_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: str = Field(min_length=1)

    @model_validator(mode="after")
    def require_exact_contracts(self) -> "FreezeTwoTaxonomyInputs":
        if type(self.taxonomy) is not CanonicalTaxonomy:
            raise TypeError("Freeze 2 requires the exact CanonicalTaxonomy type")
        if any(type(item) is not TaxonomyLaneResult for item in self.source_results):
            raise TypeError("Freeze 2 requires exact Task 6 lane results")
        if any(
            not lanes or any(type(item) is not TaxonomyLaneResult for item in lanes)
            for lanes in self.round_source_results
        ):
            raise TypeError("Freeze 2 requires exact Task 6 saturation history")
        if len(self.round_source_results) != len(self.taxonomy_rounds):
            raise ValueError("Freeze 2 saturation history must cover every round")
        if self.round_source_results[-1] != self.source_results:
            raise ValueError("Freeze 2 final lane results must match saturation history")
        if any(type(item) is not CanonicalTaxonomy for item in self.taxonomy_rounds):
            raise TypeError("Freeze 2 requires exact canonical taxonomy rounds")
        if type(self.coverage) is not MechanismCoverageAudit:
            raise TypeError("Freeze 2 requires the exact coverage audit type")
        if type(self.scoring_policy) is not EvaluationRubric:
            raise TypeError("Freeze 2 requires the exact evaluation rubric type")
        return self


class FreezeThreeRankingInputs(FrozenStrictModel):
    evaluations: tuple[ScoredFamilyEvaluation, ...] = Field(min_length=1)
    ranking: RankingAnalysis
    rubric: EvaluationRubric
    evaluation_context: EvidenceQualificationContext
    diagnostic_inputs: "FreezeThreeDiagnosticInputs"
    environment: FreezeEnvironmentV3
    leakage_policy: LeakagePolicy
    trusted_freeze_two_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: str = Field(min_length=1)
    unresolved_critical_audit_errors: tuple[str, ...] = ()

    @model_validator(mode="after")
    def require_exact_contracts(self) -> "FreezeThreeRankingInputs":
        if any(type(item) is not ScoredFamilyEvaluation for item in self.evaluations):
            raise TypeError("Freeze 3 requires exact scored evaluation types")
        if type(self.ranking) is not RankingAnalysis:
            raise TypeError("Freeze 3 requires the exact RankingAnalysis type")
        if type(self.rubric) is not EvaluationRubric:
            raise TypeError("Freeze 3 requires the exact EvaluationRubric type")
        if type(self.evaluation_context) is not EvidenceQualificationContext:
            raise TypeError("Freeze 3 requires the exact Task 8 evidence context")
        if type(self.diagnostic_inputs) is not FreezeThreeDiagnosticInputs:
            raise TypeError("Freeze 3 requires exact Task 10 diagnostic inputs")
        if type(self.environment) is not FreezeEnvironmentV3:
            raise TypeError("Freeze 3 requires complete environment metadata")
        if type(self.leakage_policy) is not LeakagePolicy:
            raise TypeError("Freeze 3 requires the exact LeakagePolicy type")
        if self.unresolved_critical_audit_errors:
            raise ValueError("Freeze 3 has unresolved critical audit errors")
        return self


class FreezeThreeDiagnosticInputs(FrozenStrictModel):
    families: tuple[CanonicalFamily, ...] = Field(min_length=1)
    principles: tuple[ReactionPrinciple, ...]
    evidence: tuple[QualifiedEvidenceRecord, ...] = Field(min_length=1)
    proposals: tuple[DiagnosticDesignProposal, ...] = ()
    model_artifacts: tuple["DiagnosticModelArtifactV3", ...] = ()
    diagnostic_records: tuple[DiagnosticRecord, ...] = ()
    inventory_records: tuple[RepresentativeInventoryRecord, ...] = ()
    readiness_records: tuple[RepresentativeReadinessRecord, ...] = ()

    @model_validator(mode="after")
    def require_exact_contracts(self) -> "FreezeThreeDiagnosticInputs":
        if any(type(item) is not CanonicalFamily for item in self.families):
            raise TypeError("Freeze 3 requires exact canonical diagnostic families")
        if any(type(item) is not ReactionPrinciple for item in self.principles):
            raise TypeError("Freeze 3 requires exact reviewed Principle inputs")
        if any(type(item) is not QualifiedEvidenceRecord for item in self.evidence):
            raise TypeError("Freeze 3 requires exact qualified diagnostic evidence")
        if any(type(item) is not DiagnosticDesignProposal for item in self.proposals):
            raise TypeError("Freeze 3 requires exact diagnostic proposals")
        proposal_by_family = {item.family_id: item for item in self.proposals}
        artifact_by_family = {item.family_id: item for item in self.model_artifacts}
        if (
            len(proposal_by_family) != len(self.proposals)
            or len(artifact_by_family) != len(self.model_artifacts)
            or set(proposal_by_family) != set(artifact_by_family)
            or any(
                artifact.output_digest
                != _stable_digest(proposal_by_family[family_id].model_dump(mode="json"))
                for family_id, artifact in artifact_by_family.items()
            )
        ):
            raise ValueError("Task 10 proposal model artifact closure mismatch")
        if any(
            not isinstance(
                item,
                (
                    DiagnosticSuccessRecord,
                    DiagnosticFailureRecord,
                    BoundaryFalsificationRecord,
                ),
            )
            for item in self.diagnostic_records
        ):
            raise TypeError("Freeze 3 requires exact diagnostic execution records")
        if any(
            type(item) is not RepresentativeInventoryRecord
            for item in self.inventory_records
        ):
            raise TypeError("Freeze 3 requires exact representative inventory records")
        if any(
            type(item) is not RepresentativeReadinessRecord
            for item in self.readiness_records
        ):
            raise TypeError("Freeze 3 requires exact representative readiness records")
        return self


class DiagnosticModelArtifactV3(FrozenStrictModel):
    family_id: str = Field(min_length=1)
    execution_id: str = Field(min_length=1)
    response_id: str = Field(min_length=1)
    cache_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    model: str = Field(min_length=1)
    output_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["completed"] = "completed"
    usage_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


FreezeThreeDiagnosticInputs.model_rebuild()
FreezeThreeRankingInputs.model_rebuild()


_CONTEXT_PREFIX_ARTIFACT_KEYS = frozenset(
    {
        "freeze_manifest_v3",
        EVIDENCE_IMPORT_MANIFEST_ARTIFACT_KEY,
        FAMILY_EVALUATION_RUBRIC_ARTIFACT_KEY,
    }
)


def _freeze_one_source_map(
    imported: EvidenceImportManifest,
    roles: Mapping[str, _FileSnapshot],
) -> dict[str, _FileSnapshot]:
    accepted_roles = sorted(role for role in roles if role.startswith("accepted_"))
    provenance_roles = sorted(
        role for role in roles if role.startswith("provenance_")
    )
    provenance_paths = (
        *imported.provenance_paths,
        imported.seed_claim_type_contract_path,
    )
    if len(accepted_roles) != len(imported.accepted) or len(provenance_roles) != len(
        provenance_paths
    ):
        raise V3FreezeError("Freeze 1 context authority source closure mismatch")
    sources: dict[str, _FileSnapshot] = {}
    for relative, role in (
        *(
            (artifact.path, role)
            for artifact, role in zip(
                imported.accepted, accepted_roles, strict=True
            )
        ),
        *zip(provenance_paths, provenance_roles, strict=True),
    ):
        if relative in sources:
            raise V3FreezeError("Freeze 1 context authority contains duplicate paths")
        sources[relative] = roles[role]
    return sources


def _registry_source_snapshot(sources: Mapping[str, Any]) -> Any:
    suffix = "derived/principles/evidence_registry.json"
    matches = [
        snapshot
        for path, snapshot in sources.items()
        if path == suffix or path.endswith(f"/{suffix}")
    ]
    if len(matches) != 1:
        raise V3FreezeError("Freeze 1 requires one authoritative evidence registry")
    return matches[0]


def _bound_context_from_authority(
    context: EvidenceQualificationContext,
    manifest_snapshot: _FileSnapshot,
    import_snapshot: _FileSnapshot,
    scoring_snapshot: _FileSnapshot,
) -> EvidenceQualificationContext:
    replacements = {
        "freeze_manifest_v3": (
            manifest_snapshot.relative_path,
            manifest_snapshot.digest,
        ),
        "evidence_import_manifest": (
            import_snapshot.relative_path,
            import_snapshot.digest,
        ),
        "family_evaluation_rubric": (
            scoring_snapshot.relative_path,
            scoring_snapshot.digest,
        ),
    }
    dependencies = tuple(
        FrozenDependencyDigest(
            artifact_key=item.artifact_key,
            path=replacements.get(item.artifact_key, (item.path, item.sha256))[0],
            sha256=replacements.get(item.artifact_key, (item.path, item.sha256))[1],
        )
        for item in context.frozen_dependencies
    )
    rubric = EvaluationRubric.model_validate(
        _json_from_snapshot(scoring_snapshot, "Freeze 2 scoring policy")
    )
    payload = context.model_dump(mode="python")
    payload.update(
        frozen_dependencies=dependencies,
        freeze_manifest_digest=manifest_snapshot.digest,
        evidence_import_manifest_digest=import_snapshot.digest,
        rubric_raw_digest=scoring_snapshot.digest,
        rubric_canonical_digest=evaluation_rubric_digest(rubric),
        artifact_commitment=_stable_digest(
            [item.model_dump(mode="json") for item in dependencies]
        ),
    )
    payload["content_digest"] = _context_content_digest(
        context.records,
        dependencies,
        manifest_snapshot.digest,
        import_snapshot.digest,
        scoring_snapshot.digest,
        evaluation_rubric_digest(rubric),
        context.frozen_principle_ids,
        context.frozen_principle_digests,
    )
    return restore_evidence_qualification_context(payload)


def _canonical_materialization_path(relative: str) -> Path:
    relative_path = Path(relative)
    if (
        not relative
        or relative_path.is_absolute()
        or not relative_path.parts
        or any(part in {"", ".", ".."} for part in relative_path.parts)
        or relative_path.as_posix() != relative
    ):
        raise V3FreezeError("context materialization path is not canonical")
    return relative_path


def _materialize_snapshot(root: Path, relative: str, content: bytes) -> Path:
    relative_path = _canonical_materialization_path(relative)

    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory_only = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory_only is None:
        raise V3FreezeError("secure context materialization is unavailable")
    directory_flags = os.O_RDONLY | directory_only | nofollow
    file_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow
    descriptors: list[int] = []
    try:
        current = os.open(root, directory_flags)
        descriptors.append(current)
        for part in relative_path.parts[:-1]:
            try:
                next_descriptor = os.open(part, directory_flags, dir_fd=current)
            except FileNotFoundError:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=current)
                except FileExistsError:
                    pass
                next_descriptor = os.open(part, directory_flags, dir_fd=current)
            descriptors.append(next_descriptor)
            current = next_descriptor
        output = os.open(
            relative_path.name,
            file_flags,
            0o600,
            dir_fd=current,
        )
        descriptors.append(output)
        remaining = memoryview(content)
        while remaining:
            written = os.write(output, remaining)
            if not written:
                raise V3FreezeError("context snapshot materialization stalled")
            remaining = remaining[written:]
        os.fsync(output)
    except V3FreezeError:
        raise
    except OSError as exc:
        raise V3FreezeError("context snapshot materialization failed") from exc
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
    return root / relative_path


def _authoritative_context_from_prefix(
    manifest_snapshot: _FileSnapshot,
    roles: Mapping[str, _FileSnapshot],
    scoring_snapshot: _FileSnapshot,
) -> EvidenceQualificationContext:
    try:
        import_snapshot = roles["evidence_import"]
        imported = EvidenceImportManifest.model_validate(
            _json_from_snapshot(import_snapshot, "Freeze 1 evidence import")
        )
        sources = _freeze_one_source_map(imported, roles)
        registry_snapshot = _registry_source_snapshot(sources)
        registry = EvidenceRegistrySummary.model_validate(
            _json_from_snapshot(registry_snapshot, "Freeze 1 evidence registry")
        )
        frozen_snapshot = roles["frozen_principles"]
        frozen = FrozenReactionPrincipleSet.model_validate(
            _json_from_snapshot(frozen_snapshot, "Freeze 1 frozen Principles")
        )
        validated_roles = sorted(
            role for role in roles if role.startswith("validated_evidence_")
        )
        records = tuple(sorted(registry.records, key=lambda item: item.validated_path))
        if len(validated_roles) != len(records):
            raise V3FreezeError(
                "Freeze 1 context authority validated evidence closure mismatch"
            )
        validated_snapshots = tuple(
            (record, roles[role])
            for record, role in zip(records, validated_roles, strict=True)
        )
        materialization_targets = (
            *sources,
            _FROZEN_PRINCIPLES_PATH.as_posix(),
            *(record.validated_path for record, _ in validated_snapshots),
            "derived/principles_v3/evidence_import_manifest.json",
            "config/family_evaluation_v3.yaml",
            "derived/principles_v3/context_authority_manifest.json",
        )
        canonical_targets = tuple(
            _canonical_materialization_path(relative).as_posix()
            for relative in materialization_targets
        )
        if len(canonical_targets) != len(set(canonical_targets)):
            raise V3FreezeError(
                "Freeze 1 context authority contains duplicate materialization paths"
            )

        with tempfile.TemporaryDirectory(prefix="v3-freeze-context-") as directory:
            temporary_root = Path(directory)
            for relative, snapshot in sources.items():
                _materialize_snapshot(temporary_root, relative, snapshot.content)
            frozen_path = _materialize_snapshot(
                temporary_root,
                _FROZEN_PRINCIPLES_PATH.as_posix(),
                frozen_snapshot.content,
            )
            for record, snapshot in validated_snapshots:
                _materialize_snapshot(
                    temporary_root, record.validated_path, snapshot.content
                )
            import_path = _materialize_snapshot(
                temporary_root,
                "derived/principles_v3/evidence_import_manifest.json",
                import_snapshot.content,
            )
            rubric_path = _materialize_snapshot(
                temporary_root,
                "config/family_evaluation_v3.yaml",
                scoring_snapshot.content,
            )
            artifact_digests = {
                FROZEN_PRINCIPLES_ARTIFACT_KEY: frozen_snapshot.digest,
                EVIDENCE_REGISTRY_ARTIFACT_KEY: _stable_digest(
                    registry.model_dump(mode="json")
                ),
                SCORING_RUBRIC_ARTIFACT_KEY: frozen.scoring_digest,
                EVIDENCE_IMPORT_MANIFEST_ARTIFACT_KEY: import_snapshot.digest,
                FAMILY_EVALUATION_RUBRIC_ARTIFACT_KEY: scoring_snapshot.digest,
            }
            for record, snapshot in validated_snapshots:
                key = validated_evidence_artifact_key(record.validated_path)
                if key in artifact_digests:
                    raise V3FreezeError(
                        "Freeze 1 context authority artifact key collision"
                    )
                artifact_digests[key] = snapshot.digest
            synthetic_manifest = FreezeManifestV3(
                freeze_version=frozen.freeze_version,
                created_at=frozen.created_at,
                brief_digest="0" * 64,
                artifact_digests=artifact_digests,
                hidden_registry_commitment="0" * 64,
                software_version="context-reconstruction",
            )
            synthetic_manifest_path = _materialize_snapshot(
                temporary_root,
                "derived/principles_v3/context_authority_manifest.json",
                _stable_json_bytes(synthetic_manifest.model_dump(mode="json")),
            )
            authoritative = build_evidence_qualification_context(
                temporary_root,
                registry,
                frozen_path,
                synthetic_manifest_path,
                import_path,
                rubric_path,
            )
    except (
        EvidenceQualificationError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise V3FreezeError(
            "Freeze 1/2 prefix cannot reconstruct authoritative evaluation context"
        ) from exc
    return _bound_context_from_authority(
        authoritative,
        manifest_snapshot,
        import_snapshot,
        scoring_snapshot,
    )


def _context_authority_material(
    context: EvidenceQualificationContext,
) -> tuple[object, ...]:
    dependencies = tuple(
        item
        for item in context.frozen_dependencies
        if item.artifact_key not in _CONTEXT_PREFIX_ARTIFACT_KEYS
    )
    return (
        context.records,
        context.registry_commitment,
        dependencies,
        context.frozen_principle_ids,
        dict(context.frozen_principle_digests),
    )


def _bind_context_to_prefix(
    context: EvidenceQualificationContext,
    manifest_snapshot: _FileSnapshot,
    roles: Mapping[str, _FileSnapshot],
    scoring_snapshot: _FileSnapshot,
    *,
    require_bound: bool,
) -> EvidenceQualificationContext:
    authoritative = _authoritative_context_from_prefix(
        manifest_snapshot, roles, scoring_snapshot
    )
    if _context_authority_material(context) != _context_authority_material(
        authoritative
    ):
        raise V3FreezeError(
            "evaluation context differs from authoritative Freeze 1/2 prefix"
        )
    if require_bound and context != authoritative:
        raise V3FreezeError("evaluation context is not bound to authoritative prefix")
    return authoritative


class LeakageAuditSnapshotV3(FrozenStrictModel):
    policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    dependency_digests: Mapping[str, str] = Field(min_length=1)
    scanned_artifact_ids: tuple[str, ...]
    hit_count: int = Field(ge=0)

    @model_validator(mode="after")
    def freeze_dependencies(self) -> "LeakageAuditSnapshotV3":
        if self.hit_count:
            raise ValueError("a frozen leakage audit must be clean")
        object.__setattr__(
            self,
            "dependency_digests",
            MappingProxyType(dict(sorted(self.dependency_digests.items()))),
        )
        return self

    @field_serializer("dependency_digests")
    def serialize_dependencies(self, value: Mapping[str, str]) -> dict[str, str]:
        return dict(value)


class CriticalAuditSnapshotV3(FrozenStrictModel):
    completed_checks: tuple[str, ...] = Field(min_length=1)
    dependency_digests: Mapping[str, str] = Field(min_length=1)
    unresolved_errors: tuple[str, ...] = ()

    @model_validator(mode="after")
    def require_clean_complete_audit(self) -> "CriticalAuditSnapshotV3":
        if self.unresolved_errors:
            raise ValueError("critical audit contains unresolved errors")
        if self.completed_checks != _CRITICAL_AUDIT_CHECKS:
            raise ValueError("critical audit completed-check set mismatch")
        object.__setattr__(
            self,
            "dependency_digests",
            MappingProxyType(dict(sorted(self.dependency_digests.items()))),
        )
        return self

    @field_serializer("dependency_digests")
    def serialize_critical_dependencies(
        self, value: Mapping[str, str]
    ) -> dict[str, str]:
        return dict(value)


class FreezeChainVerification(FrozenStrictModel):
    valid: bool
    verified_stages: tuple[Literal["Freeze 1", "Freeze 2", "Freeze 3"], ...]
    manifest_digests: Mapping[str, str]
    errors: tuple[str, ...]

    @model_validator(mode="after")
    def freeze_manifest_digests(self) -> "FreezeChainVerification":
        object.__setattr__(
            self,
            "manifest_digests",
            MappingProxyType(dict(sorted(self.manifest_digests.items()))),
        )
        return self

    @field_serializer("manifest_digests")
    def serialize_manifest_digests(self, value: Mapping[str, str]) -> dict[str, str]:
        return dict(value)


class _FileSnapshot(FrozenStrictModel):
    path: Path
    relative_path: str
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    device: int
    inode: int
    content: bytes


def _stable_json_bytes(payload: object) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _stable_digest(payload: object) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _valid_digest(value: str) -> bool:
    return len(value) == 64 and not (set(value) - _HEX)


def _timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("timestamp must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed


def _root(root: Path) -> Path:
    try:
        return root.resolve(strict=True)
    except OSError as exc:
        raise V3FreezeError("freeze root does not exist") from exc


def _lexical_path(root: Path, path: Path) -> tuple[Path, str]:
    resolved_root = _root(root)
    candidate = path if path.is_absolute() else resolved_root / path
    try:
        relative = candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise V3FreezeError("artifact path is outside freeze root") from exc
    if relative.is_absolute() or ".." in relative.parts:
        raise V3FreezeError("artifact path traversal is not allowed")
    return candidate, relative.as_posix()


def _read_snapshot(root: Path, path: Path) -> _FileSnapshot:
    candidate, relative = _lexical_path(root, path)
    parts = Path(relative).parts
    if not parts:
        raise V3FreezeError("artifact path is empty")
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | nofollow
    file_flags = os.O_RDONLY | nofollow
    descriptors: list[int] = []
    try:
        current = os.open(_root(root), directory_flags)
        descriptors.append(current)
        for part in parts[:-1]:
            current = os.open(part, directory_flags, dir_fd=current)
            descriptors.append(current)
        descriptor = os.open(parts[-1], file_flags, dir_fd=current)
        descriptors.append(descriptor)
    except OSError as exc:
        for opened in reversed(descriptors):
            os.close(opened)
        raise V3FreezeError("artifact path substitution is not allowed") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise V3FreezeError("artifact path substitution is not allowed")
        if before.st_nlink != 1:
            raise V3FreezeError("hard-link physical alias is not allowed")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise V3FreezeError("artifact changed while it was being read")
        content = b"".join(chunks)
        if len(content) != before.st_size:
            raise V3FreezeError("artifact changed while it was being read")
        return _FileSnapshot(
            path=candidate,
            relative_path=relative,
            digest=hashlib.sha256(content).hexdigest(),
            device=before.st_dev,
            inode=before.st_ino,
            content=content,
        )
    finally:
        for opened in reversed(descriptors):
            os.close(opened)


def _json_from_snapshot(snapshot: _FileSnapshot, label: str) -> Mapping[str, Any]:
    try:
        payload = json.loads(snapshot.content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise V3FreezeError(f"{label} must be valid JSON") from exc
    if not isinstance(payload, Mapping):
        raise V3FreezeError(f"{label} must be a JSON object")
    return payload


def _assert_unique_physical(snapshots: Sequence[_FileSnapshot]) -> None:
    identities = tuple((item.device, item.inode) for item in snapshots)
    if len(identities) != len(set(identities)):
        raise V3FreezeError("duplicate physical artifact alias is not allowed")


def freeze_manifest_path(root: Path, stage: str) -> Path:
    if stage not in FREEZE_MANIFEST_PATHS:
        raise V3FreezeError("unknown freeze stage")
    return _root(root) / FREEZE_MANIFEST_PATHS[stage]


def freeze_manifest_digest(root: Path, stage: str) -> str:
    return _read_snapshot(root, freeze_manifest_path(root, stage)).digest


def _publish_object(root: Path, label: str, payload: object) -> _FileSnapshot:
    encoded = _stable_json_bytes(payload)
    digest = hashlib.sha256(encoded).hexdigest()
    relative = FREEZE_OBJECT_DIRECTORY / f"{label}-{digest}.json"
    return _publish_bytes(root, relative, encoded, reusable=True)


def _publish_snapshot_copy(
    root: Path, label: str, snapshot: _FileSnapshot
) -> _FileSnapshot:
    relative = FREEZE_OBJECT_DIRECTORY / f"{label}-{snapshot.digest}.snapshot"
    return _publish_bytes(root, relative, snapshot.content, reusable=True)


def _snapshot_from_descriptor(
    root: Path, relative: Path, descriptor: int
) -> _FileSnapshot:
    before = os.fstat(descriptor)
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise V3FreezeError("published artifact identity is invalid")
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    while chunk := os.read(descriptor, 1024 * 1024):
        chunks.append(chunk)
    after = os.fstat(descriptor)
    if (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    ) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    ):
        raise V3FreezeError("published artifact changed during readback")
    content = b"".join(chunks)
    return _FileSnapshot(
        path=_root(root) / relative,
        relative_path=relative.as_posix(),
        digest=hashlib.sha256(content).hexdigest(),
        device=before.st_dev,
        inode=before.st_ino,
        content=content,
    )


def _open_publication_directory(root: Path, parts: Sequence[str]) -> tuple[int, list[int]]:
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | nofollow
    descriptors: list[int] = []
    try:
        current = os.open(_root(root), flags)
        descriptors.append(current)
        for part in parts:
            try:
                next_descriptor = os.open(part, flags, dir_fd=current)
            except FileNotFoundError:
                try:
                    os.mkdir(part, mode=0o755, dir_fd=current)
                except FileExistsError:
                    pass
                next_descriptor = os.open(part, flags, dir_fd=current)
            descriptors.append(next_descriptor)
            current = next_descriptor
        return current, descriptors
    except BaseException:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
        raise


def _publish_bytes(
    root: Path, relative: Path, content: bytes, *, reusable: bool
) -> _FileSnapshot:
    if relative.is_absolute() or ".." in relative.parts or not relative.name:
        raise V3FreezeError("publication path is invalid")
    directory, descriptors = _open_publication_directory(root, relative.parts[:-1])
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    read_flags = os.O_RDONLY | nofollow
    temporary_name = f".{relative.name}.{secrets.token_hex(12)}"
    temporary = -1
    published = -1
    try:
        temporary = os.open(
            temporary_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow,
            0o600,
            dir_fd=directory,
        )
        view = memoryview(content)
        while view:
            written = os.write(temporary, view)
            view = view[written:]
        os.fsync(temporary)
        os.fchmod(temporary, 0o644)
        try:
            os.link(
                temporary_name,
                relative.name,
                src_dir_fd=directory,
                dst_dir_fd=directory,
                follow_symlinks=False,
            )
        except FileExistsError as exc:
            if not reusable:
                raise V3FreezeError(
                    f"freeze destination already exists: {_root(root) / relative}"
                ) from exc
        os.close(temporary)
        temporary = -1
        os.unlink(temporary_name, dir_fd=directory)
        published = os.open(relative.name, read_flags, dir_fd=directory)
        snapshot = _snapshot_from_descriptor(root, relative, published)
        if snapshot.content != content:
            raise V3FreezeError("published artifact readback mismatch")
        canonical = _read_snapshot(root, _root(root) / relative)
        if (
            canonical.device,
            canonical.inode,
            canonical.content,
        ) != (snapshot.device, snapshot.inode, snapshot.content):
            raise V3FreezeError("published artifact destination changed")
        return canonical
    except OSError as exc:
        raise V3FreezeError("descriptor-bound publication failed") from exc
    finally:
        if temporary >= 0:
            os.close(temporary)
        if published >= 0:
            os.close(published)
        try:
            os.unlink(temporary_name, dir_fd=directory)
        except FileNotFoundError:
            pass
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _publish_manifest(
    root: Path, path: Path, manifest: FreezeManifestV3
) -> _FileSnapshot:
    _, relative = _lexical_path(root, path)
    encoded = _stable_json_bytes(manifest.model_dump(mode="json"))
    return _publish_bytes(root, Path(relative), encoded, reusable=False)


def _role_key(role: str, snapshot: _FileSnapshot) -> str:
    if ":" in role:
        raise V3FreezeError("freeze artifact role cannot contain a colon")
    return f"{role}:{snapshot.relative_path}"


def _artifact_digests(
    role_snapshots: Sequence[tuple[str, _FileSnapshot]],
) -> dict[str, str]:
    snapshots = tuple(item[1] for item in role_snapshots)
    _assert_unique_physical(snapshots)
    roles = tuple(item[0] for item in role_snapshots)
    if len(roles) != len(set(roles)):
        raise V3FreezeError("duplicate freeze artifact role")
    return {
        _role_key(role, snapshot): snapshot.digest
        for role, snapshot in role_snapshots
    }


def _role_snapshots(
    root: Path, manifest: FreezeManifestV3
) -> dict[str, _FileSnapshot]:
    results: dict[str, _FileSnapshot] = {}
    for key, digest in manifest.artifact_digests.items():
        role, separator, relative = key.partition(":")
        if not separator or not role or not relative:
            raise V3FreezeError("manifest artifact lacks an exact path")
        snapshot = _read_snapshot(root, Path(relative))
        if snapshot.relative_path != relative or snapshot.digest != digest:
            raise V3FreezeError(f"{manifest.freeze_version} artifact digest mismatch")
        if role in results:
            raise V3FreezeError("duplicate freeze artifact role")
        results[role] = snapshot
    _assert_unique_physical(tuple(results.values()))
    return results


def _policy_digest(policy: LeakagePolicy) -> str:
    payload = policy.model_dump(
        mode="json",
        exclude={"run_manifest_path", "declared_dependency_paths"},
    )
    return _stable_digest(payload)


def _run_current_audit(
    root: Path, paths: Sequence[Path], policy: LeakagePolicy
) -> tuple[LeakageAuditSnapshotV3, LeakageAudit]:
    snapshots = tuple(_read_snapshot(root, path) for path in paths)
    return _run_snapshot_audit(snapshots, policy)


def _run_snapshot_audit(
    snapshots: Sequence[_FileSnapshot], policy: LeakagePolicy
) -> tuple[LeakageAuditSnapshotV3, LeakageAudit]:
    snapshots = tuple(snapshots)
    _assert_unique_physical(snapshots)
    try:
        audit = audit_snapshot_bytes(
            tuple((item.relative_path, item.content) for item in snapshots),
            policy,
        )
        assert_clean(audit)
    except LeakageAuditError as exc:
        raise V3FreezeError("current Freeze 3 leakage audit failed") from exc
    return (
        LeakageAuditSnapshotV3(
            policy_digest=_policy_digest(policy),
            dependency_digests={
                item.relative_path: item.digest for item in snapshots
            },
            scanned_artifact_ids=audit.scanned_artifact_ids,
            hit_count=len(audit.hits),
        ),
        audit,
    )


def _validate_import_manifest(manifest: EvidenceImportManifest) -> None:
    material = {
        "version": manifest.version,
        "brief_digest": manifest.brief_digest,
        "leakage_policy_digest": manifest.leakage_policy_digest,
        "queue_digest": manifest.queue_digest,
        "queue_scope": manifest.queue_scope,
        "provenance_paths": manifest.provenance_paths,
        "seed_claim_type_contract_version": manifest.seed_claim_type_contract_version,
        "seed_claim_type_contract_path": manifest.seed_claim_type_contract_path,
        "seed_claim_type_contract_digest": manifest.seed_claim_type_contract_digest,
        "seed_claim_type_contract_sha256": manifest.seed_claim_type_contract_sha256,
        "accepted": [item.model_dump(mode="json") for item in manifest.accepted],
        "schema_versions": dict(manifest.schema_versions),
    }
    if (
        manifest.manifest_digest != _stable_digest(material)
        or manifest.cache_namespace
        != f"principles_v3/evidence/{manifest.manifest_digest}"
    ):
        raise V3FreezeError("Freeze 1 requires a clean evidence import")


def _import_source_snapshots(
    root: Path, manifest: EvidenceImportManifest
) -> tuple[tuple[str, _FileSnapshot], ...]:
    results: list[tuple[str, _FileSnapshot]] = []
    for index, artifact in enumerate(manifest.accepted):
        snapshot = _read_snapshot(root, Path(artifact.path))
        if snapshot.digest != artifact.sha256:
            raise V3FreezeError("Freeze 1 accepted source digest mismatch")
        results.append((f"accepted_{index:04d}", snapshot))
    provenance = tuple(manifest.provenance_paths) + (
        manifest.seed_claim_type_contract_path,
    )
    for index, relative in enumerate(provenance):
        results.append((f"provenance_{index:04d}", _read_snapshot(root, Path(relative))))
    _assert_unique_physical(tuple(item[1] for item in results))
    return tuple(results)


def _context_authority_source_snapshots(
    root: Path,
    import_sources: Sequence[tuple[str, _FileSnapshot]],
) -> tuple[tuple[str, _FileSnapshot], ...]:
    try:
        registry_snapshot = _registry_source_snapshot(
            {snapshot.relative_path: snapshot for _, snapshot in import_sources}
        )
        registry = EvidenceRegistrySummary.model_validate(
            _json_from_snapshot(registry_snapshot, "evidence registry")
        )
    except (StopIteration, TypeError, ValueError) as exc:
        raise V3FreezeError(
            "Freeze 1 requires an authoritative evidence registry"
        ) from exc
    results: list[tuple[str, _FileSnapshot]] = [
        (
            "frozen_principles",
            _read_snapshot(root, _FROZEN_PRINCIPLES_PATH),
        )
    ]
    for index, record in enumerate(
        sorted(registry.records, key=lambda item: item.validated_path)
    ):
        results.append(
            (
                f"validated_evidence_{index:04d}",
                _read_snapshot(root, Path(record.validated_path)),
            )
        )
    _assert_unique_physical(
        tuple(snapshot for _, snapshot in (*import_sources, *results))
    )
    return tuple(results)


def _validate_rejection_inventory(root: Path, manifest: EvidenceImportManifest) -> None:
    accepted = {_root(root) / item.path for item in manifest.accepted}
    provenance = {_root(root) / item for item in manifest.provenance_paths}
    paths, reasons = _rejections(_root(root), accepted, provenance)
    if paths != manifest.rejected_paths or reasons != dict(manifest.rejection_reasons):
        raise V3FreezeError("Freeze 1 v2 rejection inventory changed")


def _taxonomy_lane_artifact_path(lane: TaxonomyLaneResult) -> Path:
    return (
        Path("derived")
        / "principles_v3"
        / "taxonomy"
        / f"round-{lane.round_id}"
        / lane.lane_id
        / lane.channel
        / "validated.json"
    )


def _taxonomy_lane_raw_path(lane: TaxonomyLaneResult) -> Path:
    return _taxonomy_lane_artifact_path(lane).with_name("raw.json")


def _parse_authoritative_lane_snapshot(
    snapshot: _FileSnapshot,
    expected: TaxonomyLaneResult | None = None,
    *,
    require_canonical_path: bool = False,
) -> TaxonomyLaneResult:
    try:
        payload = _json_from_snapshot(snapshot, "Task 6 lane artifact")
        lane = TaxonomyLaneResult(status="validated", **payload)
    except (TypeError, ValueError) as exc:
        raise V3FreezeError(
            "Freeze 2 saturation history requires an authoritative Task 6 lane artifact"
        ) from exc
    if require_canonical_path and (
        snapshot.relative_path != _taxonomy_lane_artifact_path(lane).as_posix()
    ):
        raise V3FreezeError(
            "Freeze 2 requires an authoritative Task 6 lane artifact"
        )
    if expected is not None and lane.model_dump(
        mode="json", exclude={"status"}
    ) != expected.model_dump(mode="json", exclude={"status"}):
        raise V3FreezeError(
            "Freeze 2 requires an authoritative Task 6 lane artifact"
        )
    return lane


def _authoritative_lane_snapshots(
    root: Path, round_lanes: Sequence[Sequence[TaxonomyLaneResult]]
) -> tuple[tuple[str, _FileSnapshot], ...]:
    ordered = tuple(
        sorted(
            (lane for lanes in round_lanes for lane in lanes),
            key=lambda item: (item.round_id, item.lane_id, item.channel),
        )
    )
    identities = tuple(
        (item.round_id, item.lane_id, item.channel) for item in ordered
    )
    if len(identities) != len(set(identities)):
        raise V3FreezeError("Freeze 2 Task 6 lane identities are not unique")
    results: list[tuple[str, _FileSnapshot]] = []
    try:
        for index, lane in enumerate(ordered):
            validated = _read_snapshot(root, _taxonomy_lane_artifact_path(lane))
            _parse_authoritative_lane_snapshot(
                validated, lane, require_canonical_path=True
            )
            raw = _read_snapshot(root, _taxonomy_lane_raw_path(lane))
            raw_payload = _json_from_snapshot(raw, "Task 6 raw lane artifact")
            if (
                raw_payload.get("cache_key") != lane.cache_key
                or raw_payload.get("lane_id") != lane.lane_id
                or raw_payload.get("round_id") != lane.round_id
                or raw_payload.get("channel") != lane.channel
                or raw_payload.get("model_output")
                != {
                    "proposals": [
                        item.model_dump(mode="json") for item in lane.proposals
                    ]
                }
                or not isinstance(raw_payload.get("api"), Mapping)
                or raw_payload["api"].get("status") != "completed"
            ):
                raise V3FreezeError("Task 6 raw/validated lane mismatch")
            results.extend(
                (
                    (
                        f"source_result_{index:04d}",
                        _publish_snapshot_copy(
                            root, f"task6-validated-{index:04d}", validated
                        ),
                    ),
                    (
                        f"source_raw_{index:04d}",
                        _publish_snapshot_copy(
                            root, f"task6-raw-{index:04d}", raw
                        ),
                    ),
                )
            )
    except V3FreezeError as exc:
        raise V3FreezeError(
            "Freeze 2 saturation history requires an authoritative Task 6 lane artifact"
        ) from exc
    _assert_unique_physical(tuple(item[1] for item in results))
    return tuple(results)


def _validate_taxonomy_accounting(inputs: FreezeTwoTaxonomyInputs) -> None:
    if inputs.taxonomy_rounds[-1] != inputs.taxonomy:
        raise V3FreezeError("Freeze 2 taxonomy is not the final saturation round")
    source: dict[str, tuple[TaxonomyLaneResult, object]] = {}
    for lane in inputs.source_results:
        if lane.status not in {"validated", "reused"}:
            raise V3FreezeError("Freeze 2 requires validated Task 6 results")
        for proposal in lane.proposals:
            if proposal.proposal_id in source:
                raise V3FreezeError("Freeze 2 source proposal IDs are not unique")
            source[proposal.proposal_id] = (lane, proposal)
    canonical = {
        proposal_id: (family, provenance)
        for family in inputs.taxonomy.families
        for proposal_id, provenance in zip(
            family.proposal_ids, family.proposal_provenance, strict=True
        )
    }
    if set(source) != set(canonical):
        raise V3FreezeError("Freeze 2 must preserve every Task 6 proposal")
    for proposal_id, (lane, proposal) in source.items():
        family, provenance = canonical[proposal_id]
        if (
            provenance.lane_id != lane.lane_id
            or provenance.channel != lane.channel
            or provenance.round_id != lane.round_id
            or provenance.evidence_level != proposal.evidence_level
            or provenance.evidence_ids != proposal.evidence_ids
            or proposal.mechanistic_definition
            not in family.mechanistic_definition_candidates
        ):
            raise V3FreezeError("Freeze 2 proposal provenance mismatch")


def _validate_saturation_history(inputs: FreezeTwoTaxonomyInputs) -> None:
    for taxonomy, lanes in zip(
        inputs.taxonomy_rounds, inputs.round_source_results, strict=True
    ):
        round_inputs = inputs.model_copy(
            update={
                "taxonomy": taxonomy,
                "source_results": lanes,
                "taxonomy_rounds": (taxonomy, taxonomy),
                "round_source_results": (lanes, lanes),
            }
        )
        try:
            _validate_taxonomy_accounting(round_inputs)
        except V3FreezeError as exc:
            raise V3FreezeError("Freeze 2 saturation history mismatch") from exc


def _validate_saturation(
    inputs: FreezeTwoTaxonomyInputs, saturation: SaturationAudit
) -> None:
    if type(saturation) is not SaturationAudit:
        raise V3FreezeError("Freeze 2 requires the exact SaturationAudit type")
    recomputed = evaluate_saturation(
        inputs.taxonomy_rounds, inputs.coverage, inputs.saturation_config
    )
    if recomputed != saturation or not saturation.saturated:
        raise V3FreezeError("Freeze 2 requires passing authoritative saturation")
    if (
        not saturation.coverage_dispositioned
        or "unknown" in saturation.uncovered_coordinate_dispositions.values()
    ):
        raise V3FreezeError("Freeze 2 saturation contains unknown coverage")


def _evaluation_evidence_ids(evaluation: ScoredFamilyEvaluation) -> set[str]:
    return {
        evidence_id
        for judgment in evaluation.judgments
        for evidence_id in (*judgment.evidence_ids, *judgment.counterevidence_ids)
    }.union(
        evidence_id
        for blocker in evaluation.qualified_blockers
        for evidence_id in (*blocker.evidence_ids, *blocker.counterevidence_ids)
    )


def _validate_freeze_three(
    inputs: FreezeThreeRankingInputs,
    plans: Sequence[FamilyDiagnosticPlan],
    family_ids: set[str],
) -> tuple[ScoredFamilyEvaluation, ...]:
    try:
        supplied_evaluations = tuple(
            verify_scored_family_evaluation(item, inputs.rubric)
            for item in inputs.evaluations
        )
        evaluations = tuple(
            score_family(
                item.judgments,
                item.qualified_blockers,
                inputs.rubric,
                inputs.evaluation_context,
                family_id=item.family_id,
            )
            for item in supplied_evaluations
        )
        if evaluations != supplied_evaluations:
            raise V3FreezeError(
                "Freeze 3 evaluation differs from recomputed Task 8 output"
            )
    except (EvidenceQualificationError, AttributeError, ValueError) as exc:
        raise V3FreezeError("Freeze 3 requires an attested scored evaluation") from exc
    try:
        verified_ranking = verify_ranking_analysis(
            inputs.ranking, evaluations, inputs.rubric
        )
        recomputed_ranking = analyze_ranking(
            evaluations, inputs.rubric, seed=verified_ranking.seed
        )
        if recomputed_ranking != verified_ranking:
            raise V3FreezeError(
                "Freeze 3 ranking differs from recomputed Task 9 output"
            )
    except (RankingAnalysisError, AttributeError, ValueError) as exc:
        raise V3FreezeError("Freeze 3 requires attested ranking robustness") from exc
    verified_plans: list[FamilyDiagnosticPlan] = []
    try:
        for plan in plans:
            verified_plans.append(verify_family_diagnostic_plan(plan))
    except (DiagnosticDesignError, AttributeError, ValueError) as exc:
        raise V3FreezeError("Freeze 3 requires an attested diagnostic plan") from exc
    diagnostic_inputs = inputs.diagnostic_inputs
    try:
        recomputed_plans = design_family_diagnostics(
            diagnostic_inputs.families,
            evaluations,
            diagnostic_inputs.principles,
            diagnostic_inputs.evidence,
            verified_ranking,
            proposals=diagnostic_inputs.proposals,
            diagnostic_records=diagnostic_inputs.diagnostic_records,
            inventory_records=diagnostic_inputs.inventory_records,
            readiness_records=diagnostic_inputs.readiness_records,
            rubric=inputs.rubric,
        )
    except (DiagnosticDesignError, AttributeError, ValueError) as exc:
        raise V3FreezeError("Freeze 3 Task 10 inputs are invalid") from exc
    if tuple(verified_plans) != recomputed_plans:
        raise V3FreezeError(
            "Freeze 3 diagnostics differ from recomputed Task 10 output"
        )
    _validate_freeze_three_links(
        evaluations, verified_ranking, verified_plans, family_ids
    )
    return evaluations


def _require_inventory_factory_binding(
    records: Sequence[RepresentativeInventoryRecord],
    structure_factory: StructureFingerprintFactory,
) -> None:
    try:
        for record in records:
            verify_structure_fingerprint_receipt(
                structure_factory,
                record.record_id,
                record.structure_fingerprint_receipt,
            )
            if (
                record.structural_fingerprint
                != record.structure_fingerprint_receipt.fingerprint
            ):
                raise ValueError("inventory fingerprint differs from factory receipt")
    except ValueError as exc:
        raise V3FreezeError("Freeze 3 structure fingerprint factory mismatch") from exc


def _validate_freeze_three_links(
    evaluations: Sequence[ScoredFamilyEvaluation],
    ranking: RankingAnalysis,
    plans: Sequence[FamilyDiagnosticPlan],
    family_ids: set[str],
) -> None:
    if set(ranking.by_family) != family_ids:
        raise V3FreezeError("Freeze 3 ranking must cover every canonical family")
    plan_by_id = {item.family_id: item for item in plans}
    evaluation_by_id = {item.family_id: item for item in evaluations}
    if len(plan_by_id) != len(plans) or set(plan_by_id) != family_ids:
        raise V3FreezeError("Freeze 3 requires a plan for every canonical family")
    for family_id, plan in plan_by_id.items():
        evaluation = evaluation_by_id[family_id]
        record = ranking.by_family[family_id]
        if (
            plan.priority_region != evaluation.priority_region
            or record.priority_region != evaluation.priority_region
            or set(plan.supporting_principle_ids)
            != set(evaluation.reviewed_principle_ids)
            or not _evaluation_evidence_ids(evaluation).issubset(plan.evidence_ids)
        ):
            raise V3FreezeError("Freeze 3 evaluation/ranking/diagnostic mismatch")
        if plan.ranking_basis is not None and (
            plan.ranking_basis.evaluation_digest
            != evaluation.scored_content_digest
            or plan.ranking_basis.analysis_content_digest != ranking.content_digest
        ):
            raise V3FreezeError("Freeze 3 diagnostic ranking basis mismatch")
        if evaluation.priority_region in {"priority_a", "priority_b", "priority_c"}:
            if (
                record.primary_rank is None
                or record.equal_weight_rank is None
                or record.sampled_rank_median is None
                or record.sampled_rank_range is None
                or record.pareto_optimal is None
                or record.weight_sensitive is None
                or record.leave_one_paper_out_range is None
                or record.stability_label is None
            ):
                raise V3FreezeError("Freeze 3 ranking robustness is incomplete")


def _json_array_from_snapshot(
    snapshot: _FileSnapshot, label: str
) -> tuple[Mapping[str, Any], ...]:
    try:
        payload = json.loads(snapshot.content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise V3FreezeError(f"{label} must be valid JSON") from exc
    if not isinstance(payload, list) or not payload or any(
        not isinstance(item, Mapping) for item in payload
    ):
        raise V3FreezeError(f"{label} must be a nonempty JSON array")
    return tuple(payload)


def _verify_freeze_three_persisted(
    roles: Mapping[str, _FileSnapshot],
    rubric: EvaluationRubric,
    family_ids: set[str],
    freeze_one_manifest: _FileSnapshot,
    freeze_one_roles: Mapping[str, _FileSnapshot],
    freeze_two_roles: Mapping[str, _FileSnapshot],
    structure_factory: StructureFingerprintFactory,
) -> tuple[DiagnosticModelArtifactV3, ...]:
    try:
        context = restore_evidence_qualification_context(
            _json_from_snapshot(
                roles["evaluation_context"],
                "persisted Freeze 3 evaluation context",
            )
        )
        _bind_context_to_prefix(
            context,
            freeze_one_manifest,
            freeze_one_roles,
            freeze_two_roles["scoring_policy"],
            require_bound=True,
        )
        evaluations: list[ScoredFamilyEvaluation] = []
        for payload in _json_array_from_snapshot(
            roles["evaluations"], "persisted Freeze 3 evaluations"
        ):
            data = dict(payload)
            supplied_digest = data.pop("scored_content_digest")
            rebuilt = _build_scored_evaluation(**data)
            if rebuilt.scored_content_digest != supplied_digest:
                raise V3FreezeError(
                    "persisted Freeze 3 evaluation content digest mismatch"
                )
            supplied = verify_scored_family_evaluation(rebuilt, rubric)
            recomputed = score_family(
                supplied.judgments,
                supplied.qualified_blockers,
                rubric,
                context,
                family_id=supplied.family_id,
            )
            if recomputed != supplied:
                raise V3FreezeError(
                    "persisted Freeze 3 evaluation differs from recomputed Task 8 output"
                )
            evaluations.append(recomputed)

        ranking_payload = dict(
            _json_from_snapshot(roles["ranking"], "persisted Freeze 3 ranking")
        )
        ranking_digest = ranking_payload.pop("content_digest")
        ranking = _build_ranking_analysis(**ranking_payload)
        if ranking.content_digest != ranking_digest:
            raise V3FreezeError("persisted Freeze 3 ranking content digest mismatch")
        ranking = verify_ranking_analysis(ranking, evaluations, rubric)
        recomputed_ranking = analyze_ranking(
            evaluations, rubric, seed=ranking.seed
        )
        if recomputed_ranking != ranking:
            raise V3FreezeError(
                "persisted Freeze 3 ranking differs from recomputed Task 9 output"
            )

        diagnostic_payload = _json_from_snapshot(
            roles["diagnostic_inputs"],
            "persisted Freeze 3 diagnostic inputs",
        )
        diagnostic_inputs = FreezeThreeDiagnosticInputs(
            families=tuple(
                CanonicalFamily.model_validate(item)
                for item in diagnostic_payload.get("families", ())
            ),
            principles=tuple(
                ReactionPrinciple.model_validate(item)
                for item in diagnostic_payload.get("principles", ())
            ),
            evidence=tuple(
                QualifiedEvidenceRecord.model_validate(item)
                for item in diagnostic_payload.get("evidence", ())
            ),
            proposals=tuple(
                DiagnosticDesignProposal.model_validate(item)
                for item in diagnostic_payload.get("proposals", ())
            ),
            model_artifacts=tuple(
                DiagnosticModelArtifactV3.model_validate(item)
                for item in diagnostic_payload.get("model_artifacts", ())
            ),
            diagnostic_records=tuple(
                restore_diagnostic_record(item)
                for item in diagnostic_payload.get("diagnostic_records", ())
            ),
            inventory_records=tuple(
                restore_representative_inventory_record(item, structure_factory)
                for item in diagnostic_payload.get("inventory_records", ())
            ),
            readiness_records=tuple(
                restore_representative_readiness_record(item)
                for item in diagnostic_payload.get("readiness_records", ())
            ),
        )
        if {item.family_id for item in diagnostic_inputs.families} != family_ids:
            raise V3FreezeError("persisted Freeze 3 diagnostic family set mismatch")
        _require_inventory_factory_binding(
            diagnostic_inputs.inventory_records, structure_factory
        )
        taxonomy = CanonicalTaxonomy.model_validate(
            _json_from_snapshot(freeze_two_roles["taxonomy"], "Freeze 2 taxonomy")
        )
        if diagnostic_inputs.families != taxonomy.families:
            raise V3FreezeError("persisted Freeze 3 diagnostic definitions mismatch")
        if diagnostic_inputs.evidence != context.records:
            raise V3FreezeError("persisted Freeze 3 diagnostic evidence mismatch")
        principle_digests = {
            item.principle_id: _stable_digest(item.model_dump(mode="json"))
            for item in diagnostic_inputs.principles
        }
        if principle_digests != dict(context.frozen_principle_digests):
            raise V3FreezeError("persisted Freeze 3 diagnostic Principle mismatch")

        plans: list[FamilyDiagnosticPlan] = []
        for payload in _json_array_from_snapshot(
            roles["diagnostics"], "persisted Freeze 3 diagnostics"
        ):
            data = dict(payload)
            supplied_plan_digest = data.pop("plan_digest")
            supplied_content_digest = data.pop("content_digest")
            plan = _build_plan(**data)
            if (
                plan.plan_digest != supplied_plan_digest
                or plan.content_digest != supplied_content_digest
            ):
                raise V3FreezeError(
                    "persisted Freeze 3 diagnostic content digest mismatch"
                )
            plans.append(verify_family_diagnostic_plan(plan))

        _validate_freeze_three_links(evaluations, ranking, plans, family_ids)
        recomputed_plans = design_family_diagnostics(
            diagnostic_inputs.families,
            evaluations,
            diagnostic_inputs.principles,
            diagnostic_inputs.evidence,
            ranking,
            proposals=diagnostic_inputs.proposals,
            diagnostic_records=diagnostic_inputs.diagnostic_records,
            inventory_records=diagnostic_inputs.inventory_records,
            readiness_records=diagnostic_inputs.readiness_records,
            rubric=rubric,
        )
        if tuple(plans) != recomputed_plans:
            raise V3FreezeError(
                "persisted Freeze 3 diagnostics differ from recomputed Task 10 output"
            )

        FreezeEnvironmentV3.model_validate(
            _json_from_snapshot(roles["environment"], "Freeze 3 environment")
        )
        _validate_freeze_three_links(evaluations, ranking, plans, family_ids)
        return diagnostic_inputs.model_artifacts
    except V3FreezeError:
        raise
    except (
        AttributeError,
        DiagnosticDesignError,
        EvidenceQualificationError,
        KeyError,
        RankingAnalysisError,
        TypeError,
        ValueError,
    ) as exc:
        raise V3FreezeError("persisted Freeze 3 contract is invalid") from exc


def _task_six_execution_material(
    roles: Mapping[str, _FileSnapshot],
) -> set[tuple[str, str, str, str, str, str]]:
    material: set[tuple[str, str, str, str, str, str]] = set()
    for role, snapshot in roles.items():
        if not role.startswith("source_raw_"):
            continue
        payload = _json_from_snapshot(snapshot, "Task 6 raw lane artifact")
        api = payload.get("api")
        if not isinstance(api, Mapping):
            raise V3FreezeError("Task 6 raw model execution is invalid")
        response_id = api.get("response_id")
        model = api.get("returned_model")
        status = api.get("status")
        usage = api.get("usage")
        cache_key = payload.get("cache_key")
        if not all(
            isinstance(value, str) and value
            for value in (response_id, model, status)
        ):
            raise V3FreezeError("Task 6 raw model execution is invalid")
        if not isinstance(cache_key, str) or not _valid_digest(cache_key):
            raise V3FreezeError("Task 6 raw model cache key is invalid")
        material.add(
            (
                response_id,
                cache_key,
                _stable_digest(payload.get("model_output")),
                model,
                status,
                _stable_digest(usage),
            )
        )
    if not material:
        raise V3FreezeError("Task 6 model execution closure is empty")
    return material


def _validate_environment_links(
    environment: FreezeEnvironmentV3,
    freeze_two_roles: Mapping[str, _FileSnapshot],
    diagnostic_artifacts: Sequence[DiagnosticModelArtifactV3] = (),
) -> None:
    expected = _task_six_execution_material(freeze_two_roles)
    executions = environment.model_executions
    expected.update(
        (
            item.response_id,
            item.cache_key,
            item.output_digest,
            item.model,
            item.status,
            item.usage_digest,
        )
        for item in diagnostic_artifacts
    )
    actual = {
        (
            artifact.response_id,
            artifact.cache_key,
            artifact.output_digest,
            execution.model,
            artifact.status,
            artifact.usage_digest,
        )
        for execution in executions
        for artifact in execution.artifacts
    }
    if actual != expected:
        raise V3FreezeError("Freeze 3 Task 6 model execution linkage mismatch")


def _read_manifest(root: Path, stage: str) -> tuple[FreezeManifestV3, _FileSnapshot]:
    snapshot = _read_snapshot(root, freeze_manifest_path(root, stage))
    try:
        manifest = FreezeManifestV3.model_validate_json(snapshot.content)
    except ValueError as exc:
        raise V3FreezeError(f"{stage} manifest is invalid") from exc
    if manifest.freeze_version != stage:
        raise V3FreezeError(f"{stage} manifest stage mismatch")
    return manifest, snapshot


def _verify_freeze_one_persisted(
    root: Path, manifest: FreezeManifestV3, roles: Mapping[str, _FileSnapshot]
) -> None:
    required = {"brief", "evidence_import", "frozen_principles", "leakage_audit"}
    if not required.issubset(roles):
        raise V3FreezeError("Freeze 1 artifact set mismatch")
    try:
        brief = ExplorationBriefV3.model_validate(
            _json_from_snapshot(roles["brief"], "Freeze 1 brief")
        )
        imported = EvidenceImportManifest.model_validate(
            _json_from_snapshot(roles["evidence_import"], "evidence import")
        )
        source_map = _freeze_one_source_map(imported, roles)
        registry = EvidenceRegistrySummary.model_validate(
            _json_from_snapshot(
                _registry_source_snapshot(source_map),
                "evidence registry",
            )
        )
        FrozenReactionPrincipleSet.model_validate(
            _json_from_snapshot(roles["frozen_principles"], "frozen Principles")
        )
        audit_snapshot = LeakageAuditSnapshotV3.model_validate(
            _json_from_snapshot(roles["leakage_audit"], "Freeze 1 leakage audit")
        )
    except V3FreezeError as exc:
        raise V3FreezeError("Freeze 1 artifact set mismatch") from exc
    except (KeyError, ValueError) as exc:
        raise V3FreezeError("Freeze 1 persisted contract is invalid") from exc
    _validate_import_manifest(imported)
    _validate_rejection_inventory(root, imported)
    expected_roles = required.union(
        {f"accepted_{index:04d}" for index in range(len(imported.accepted))},
        {
            f"provenance_{index:04d}"
            for index in range(len(imported.provenance_paths) + 1)
        },
        {
            f"validated_evidence_{index:04d}"
            for index in range(len(registry.records))
        },
    )
    if set(roles) != expected_roles:
        raise V3FreezeError("Freeze 1 artifact set mismatch")
    if imported.brief_digest != v3_brief_digest(brief):
        raise V3FreezeError("Freeze 1 brief/import mismatch")
    if manifest.brief_digest != v3_brief_digest(brief) or audit_snapshot.hit_count:
        raise V3FreezeError("Freeze 1 gate mismatch")
    expected_dependencies = {
        snapshot.relative_path: snapshot.digest
        for role, snapshot in roles.items()
        if role != "leakage_audit"
    }
    if dict(audit_snapshot.dependency_digests) != expected_dependencies:
        raise V3FreezeError("Freeze 1 leakage audit dependency closure mismatch")
    accepted_roles = sorted(role for role in roles if role.startswith("accepted_"))
    if len(accepted_roles) != len(imported.accepted):
        raise V3FreezeError("Freeze 1 accepted source set mismatch")
    for role, artifact in zip(accepted_roles, imported.accepted, strict=True):
        snapshot = roles[role]
        if snapshot.digest != artifact.sha256:
            raise V3FreezeError("Freeze 1 accepted source digest mismatch")


def _verify_freeze_two_persisted(
    root: Path, roles: Mapping[str, _FileSnapshot]
) -> set[str]:
    required = {
        "taxonomy",
        "taxonomy_rounds",
        "coverage",
        "saturation",
        "saturation_config",
        "scoring_policy",
        "preceding_freeze",
    }
    source_roles = sorted(
        role for role in roles if role.startswith("source_result_")
    )
    raw_roles = sorted(role for role in roles if role.startswith("source_raw_"))
    if (
        not source_roles
        or len(source_roles) != len(raw_roles)
        or set(roles) != required.union(source_roles, raw_roles)
    ):
        raise V3FreezeError("Freeze 2 artifact set mismatch")
    try:
        taxonomy = CanonicalTaxonomy.model_validate(
            _json_from_snapshot(roles["taxonomy"], "taxonomy")
        )
        rounds_payload = json.loads(roles["taxonomy_rounds"].content)
        source_results = tuple(
            _parse_authoritative_lane_snapshot(roles[role])
            for role in source_roles
        )
        for lane, role in zip(source_results, raw_roles, strict=True):
            raw = _json_from_snapshot(roles[role], "Task 6 raw lane artifact")
            if (
                raw.get("cache_key") != lane.cache_key
                or raw.get("lane_id") != lane.lane_id
                or raw.get("round_id") != lane.round_id
                or raw.get("channel") != lane.channel
                or raw.get("model_output")
                != {
                    "proposals": [
                        item.model_dump(mode="json") for item in lane.proposals
                    ]
                }
            ):
                raise V3FreezeError("Freeze 2 saturation history mismatch")
        results_by_round = tuple(
            tuple(item for item in source_results if item.round_id == round_id)
            for round_id in sorted({item.round_id for item in source_results})
        )
        rounds = tuple(CanonicalTaxonomy.model_validate(item) for item in rounds_payload)
        coverage = MechanismCoverageAudit.model_validate(
            _json_from_snapshot(roles["coverage"], "coverage")
        )
        saturation = SaturationAudit.model_validate(
            _json_from_snapshot(roles["saturation"], "saturation")
        )
        config = _json_from_snapshot(roles["saturation_config"], "saturation config")
        rubric = EvaluationRubric.model_validate(
            _json_from_snapshot(roles["scoring_policy"], "scoring policy")
        )
        rebuilt = FreezeTwoTaxonomyInputs(
            taxonomy=taxonomy,
            source_results=results_by_round[-1],
            round_source_results=results_by_round,
            taxonomy_rounds=rounds,
            coverage=coverage,
            saturation_config=config,
            scoring_policy=rubric,
            trusted_freeze_one_digest="0" * 64,
            created_at="persisted-verification",
        )
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise V3FreezeError("Freeze 2 persisted contract is invalid") from exc
    _validate_taxonomy_accounting(rebuilt)
    _validate_saturation_history(rebuilt)
    _validate_saturation(rebuilt, saturation)
    return {item.family_id for item in taxonomy.families}


def _verify_prefix(
    root: Path, stage_count: int, trusted_latest_digest: str
) -> tuple[
    dict[str, FreezeManifestV3],
    dict[str, dict[str, _FileSnapshot]],
    dict[str, _FileSnapshot],
]:
    if not _valid_digest(trusted_latest_digest):
        raise V3FreezeError("trusted freeze digest must be SHA-256")
    manifests: dict[str, FreezeManifestV3] = {}
    role_maps: dict[str, dict[str, _FileSnapshot]] = {}
    manifest_snapshots: dict[str, _FileSnapshot] = {}
    latest_stage = _STAGES[stage_count - 1]
    latest, latest_snapshot = _read_manifest(root, latest_stage)
    if latest_snapshot.digest != trusted_latest_digest:
        raise V3FreezeError(f"trusted {latest_stage} digest mismatch")
    manifests[latest_stage] = latest
    manifest_snapshots[latest_stage] = latest_snapshot
    role_maps[latest_stage] = _role_snapshots(root, latest)
    current_stage = latest_stage
    for previous_stage in reversed(_STAGES[: stage_count - 1]):
        roles = role_maps[current_stage]
        predecessor = roles.get("preceding_freeze")
        expected_path = freeze_manifest_path(root, previous_stage)
        if predecessor is None or predecessor.path != expected_path:
            raise V3FreezeError(f"{current_stage} predecessor path mismatch")
        try:
            previous = FreezeManifestV3.model_validate_json(predecessor.content)
        except ValueError as exc:
            raise V3FreezeError(f"{previous_stage} manifest is invalid") from exc
        if previous.freeze_version != previous_stage:
            raise V3FreezeError(f"{previous_stage} manifest stage mismatch")
        if (
            manifests[current_stage].brief_digest != previous.brief_digest
            or manifests[current_stage].hidden_registry_commitment
            != previous.hidden_registry_commitment
            or manifests[current_stage].software_version != previous.software_version
        ):
            raise V3FreezeError(f"{current_stage} chain metadata mismatch")
        manifests[previous_stage] = previous
        manifest_snapshots[previous_stage] = predecessor
        role_maps[previous_stage] = _role_snapshots(root, previous)
        current_stage = previous_stage
    _verify_freeze_one_persisted(root, manifests["Freeze 1"], role_maps["Freeze 1"])
    if stage_count >= 2:
        _verify_freeze_two_persisted(root, role_maps["Freeze 2"])
    return manifests, role_maps, manifest_snapshots


def bind_evaluation_context_to_freeze_chain(
    root: Path,
    context: EvidenceQualificationContext,
    trusted_freeze_two_digest: str,
) -> EvidenceQualificationContext:
    """Derive Task 8 context commitments from a verified Freeze 1/2 prefix."""

    _, roles, manifests = _verify_prefix(root, 2, trusted_freeze_two_digest)
    return _bind_context_to_prefix(
        context,
        manifests["Freeze 1"],
        roles["Freeze 1"],
        roles["Freeze 2"]["scoring_policy"],
        require_bound=False,
    )


def freeze_stage_one(root: Path, inputs: FreezeOneInputs) -> FreezeManifestV3:
    """Create Freeze 1 from a current authoritative Task 2 import."""

    root = _root(root)
    destination = freeze_manifest_path(root, "Freeze 1")
    if destination.exists():
        raise V3FreezeError(f"freeze destination already exists: {destination}")
    if type(inputs) is not FreezeOneInputs:
        raise V3FreezeError("Freeze 1 requires typed authoritative inputs")
    try:
        imported = import_reusable_evidence(
            root,
            inputs.brief,
            inputs.leakage_policy,
            source_prefix=inputs.evidence_source_prefix,
        )
    except EvidenceImportError as exc:
        raise V3FreezeError("Freeze 1 requires a clean evidence import") from exc
    _validate_import_manifest(imported)
    _validate_rejection_inventory(root, imported)
    source_snapshots = _import_source_snapshots(root, imported)
    context_snapshots = _context_authority_source_snapshots(root, source_snapshots)
    brief_object = _publish_object(root, "brief", inputs.brief.model_dump(mode="json"))
    import_path = root / "derived/principles_v3/evidence_import_manifest.json"
    import_source_snapshot = _read_snapshot(root, import_path)
    persisted_import = EvidenceImportManifest.model_validate(
        _json_from_snapshot(import_source_snapshot, "evidence import")
    )
    if persisted_import != imported:
        raise V3FreezeError("Freeze 1 persisted import does not match current import")
    source_roles = tuple(
        (
            role,
            _publish_snapshot_copy(root, f"freeze1-{role}", snapshot),
        )
        for role, snapshot in source_snapshots
    )
    context_roles = tuple(
        (
            role,
            _publish_snapshot_copy(root, f"freeze1-{role}", snapshot),
        )
        for role, snapshot in context_snapshots
    )
    import_snapshot = _publish_snapshot_copy(
        root, "freeze1-evidence-import", import_source_snapshot
    )
    try:
        audit_snapshot, _ = _run_snapshot_audit(
            tuple(item[1] for item in source_roles)
            + tuple(item[1] for item in context_roles)
            + (brief_object, import_snapshot),
            inputs.leakage_policy,
        )
    except V3FreezeError as exc:
        raise V3FreezeError("Freeze 1 requires a current clean leakage audit") from exc
    audit_object = _publish_object(
        root, "freeze1-leakage", audit_snapshot.model_dump(mode="json")
    )
    role_snapshots = (
        ("brief", brief_object),
        ("evidence_import", import_snapshot),
        ("leakage_audit", audit_object),
        *source_roles,
        *context_roles,
    )
    manifest = FreezeManifestV3(
        freeze_version="Freeze 1",
        created_at=inputs.created_at,
        brief_digest=v3_brief_digest(inputs.brief),
        artifact_digests=_artifact_digests(role_snapshots),
        hidden_registry_commitment=inputs.hidden_registry_commitment,
        software_version=inputs.software_version,
    )
    published = _publish_manifest(root, destination, manifest)
    if published.content != _stable_json_bytes(manifest.model_dump(mode="json")):
        raise V3FreezeError("Freeze 1 manifest readback mismatch")
    return manifest


def freeze_stage_two(
    root: Path,
    taxonomy: FreezeTwoTaxonomyInputs,
    saturation: SaturationAudit,
) -> FreezeManifestV3:
    """Create Freeze 2 from exact Task 6/7 typed outputs."""

    root = _root(root)
    if type(taxonomy) is not FreezeTwoTaxonomyInputs:
        raise V3FreezeError("Freeze 2 requires typed Task 6/7 taxonomy inputs")
    if taxonomy.source_results != taxonomy.round_source_results[-1]:
        raise V3FreezeError(
            "Freeze 2 requires an authoritative Task 6 lane artifact history"
        )
    manifests, _, manifest_snapshots = _verify_prefix(
        root, 1, taxonomy.trusted_freeze_one_digest
    )
    destination = freeze_manifest_path(root, "Freeze 2")
    if destination.exists():
        raise V3FreezeError(f"freeze destination already exists: {destination}")
    lane_snapshots = _authoritative_lane_snapshots(
        root, taxonomy.round_source_results
    )
    _validate_taxonomy_accounting(taxonomy)
    _validate_saturation_history(taxonomy)
    _validate_saturation(taxonomy, saturation)
    objects = (
        ("taxonomy", _publish_object(root, "taxonomy", taxonomy.taxonomy.model_dump(mode="json"))),
        *lane_snapshots,
        (
            "taxonomy_rounds",
            _publish_object(
                root,
                "taxonomy-rounds",
                [item.model_dump(mode="json") for item in taxonomy.taxonomy_rounds],
            ),
        ),
        ("coverage", _publish_object(root, "coverage", taxonomy.coverage.model_dump(mode="json"))),
        ("saturation", _publish_object(root, "saturation", saturation.model_dump(mode="json"))),
        (
            "saturation_config",
            _publish_object(root, "saturation-config", taxonomy.saturation_config),
        ),
        (
            "scoring_policy",
            _publish_object(
                root,
                "scoring-policy",
                taxonomy.scoring_policy.model_dump(mode="json"),
            ),
        ),
        ("preceding_freeze", manifest_snapshots["Freeze 1"]),
    )
    predecessor = manifests["Freeze 1"]
    manifest = FreezeManifestV3(
        freeze_version="Freeze 2",
        created_at=taxonomy.created_at,
        brief_digest=predecessor.brief_digest,
        artifact_digests=_artifact_digests(objects),
        hidden_registry_commitment=predecessor.hidden_registry_commitment,
        software_version=predecessor.software_version,
    )
    published = _publish_manifest(root, destination, manifest)
    if published.content != _stable_json_bytes(manifest.model_dump(mode="json")):
        raise V3FreezeError("Freeze 2 manifest readback mismatch")
    return manifest


def _all_chain_snapshots(
    role_maps: Mapping[str, Mapping[str, _FileSnapshot]],
) -> tuple[_FileSnapshot, ...]:
    snapshots = {
        snapshot.relative_path: snapshot
        for roles in role_maps.values()
        for snapshot in roles.values()
    }
    return tuple(snapshots[key] for key in sorted(snapshots))


def _deduplicate_snapshots(
    snapshots: Sequence[_FileSnapshot],
) -> tuple[_FileSnapshot, ...]:
    by_path: dict[str, _FileSnapshot] = {}
    for snapshot in snapshots:
        existing = by_path.get(snapshot.relative_path)
        if existing is not None and (
            existing.device,
            existing.inode,
            existing.digest,
            existing.content,
        ) != (
            snapshot.device,
            snapshot.inode,
            snapshot.digest,
            snapshot.content,
        ):
            raise V3FreezeError("trusted snapshot identity conflict")
        by_path[snapshot.relative_path] = snapshot
    return tuple(by_path[key] for key in sorted(by_path))


def freeze_stage_three(
    root: Path,
    ranking: FreezeThreeRankingInputs,
    diagnostics: Sequence[FamilyDiagnosticPlan],
) -> FreezeManifestV3:
    """Create Freeze 3 from exact Task 8/9/10 attested outputs."""

    root = _root(root)
    if type(ranking) is not FreezeThreeRankingInputs:
        raise V3FreezeError("Freeze 3 requires typed Task 8/9 ranking inputs")
    manifests, role_maps, manifest_snapshots = _verify_prefix(
        root, 2, ranking.trusted_freeze_two_digest
    )
    destination = freeze_manifest_path(root, "Freeze 3")
    if destination.exists():
        raise V3FreezeError(f"freeze destination already exists: {destination}")
    family_ids = _verify_freeze_two_persisted(root, role_maps["Freeze 2"])
    if type(ranking.evaluation_context) is not EvidenceQualificationContext:
        _validate_freeze_three(ranking, diagnostics, family_ids)
        raise V3FreezeError("Freeze 3 evaluation context is invalid")
    expected_context = _bind_context_to_prefix(
        ranking.evaluation_context,
        manifest_snapshots["Freeze 1"],
        role_maps["Freeze 1"],
        role_maps["Freeze 2"]["scoring_policy"],
        require_bound=True,
    )
    if ranking.evaluation_context != expected_context:
        raise V3FreezeError("Freeze 3 evaluation context is not chain-bound")
    taxonomy_snapshot = CanonicalTaxonomy.model_validate(
        _json_from_snapshot(role_maps["Freeze 2"]["taxonomy"], "Freeze 2 taxonomy")
    )
    if ranking.diagnostic_inputs.families != taxonomy_snapshot.families:
        raise V3FreezeError("Freeze 3 diagnostic canonical definitions mismatch")
    if ranking.diagnostic_inputs.evidence != ranking.evaluation_context.records:
        raise V3FreezeError("Freeze 3 diagnostic evidence/context mismatch")
    if {
        item.principle_id: _stable_digest(item.model_dump(mode="json"))
        for item in ranking.diagnostic_inputs.principles
    } != dict(ranking.evaluation_context.frozen_principle_digests):
        raise V3FreezeError("Freeze 3 diagnostic Principle/context mismatch")
    try:
        frozen_rubric = EvaluationRubric.model_validate(
            _json_from_snapshot(
                role_maps["Freeze 2"]["scoring_policy"],
                "Freeze 2 scoring policy",
            )
        )
        rubric_matches = evaluation_rubric_digest(
            frozen_rubric
        ) == evaluation_rubric_digest(ranking.rubric)
    except (TypeError, ValueError) as exc:
        raise V3FreezeError("Freeze 2 scoring policy is invalid") from exc
    if not rubric_matches:
        raise V3FreezeError("Freeze 3 rubric does not match Freeze 2 scoring policy")
    evaluations = _validate_freeze_three(ranking, diagnostics, family_ids)
    try:
        structure_factory = verify_policy_structure_factory(ranking.leakage_policy)
    except (AttributeError, LeakageAuditError) as exc:
        raise V3FreezeError("Freeze 3 structure fingerprint factory is invalid") from exc
    if structure_factory is None:
        raise V3FreezeError("Freeze 3 requires a trusted structure fingerprint factory")
    _require_inventory_factory_binding(
        ranking.diagnostic_inputs.inventory_records, structure_factory
    )
    if ranking.environment.software_version != manifests["Freeze 2"].software_version:
        raise V3FreezeError("Freeze 3 environment software version mismatch")
    if _timestamp(ranking.created_at) < _timestamp(ranking.environment.completed_at):
        raise V3FreezeError("Freeze 3 creation timestamp precedes model execution")
    _validate_environment_links(
        ranking.environment,
        role_maps["Freeze 2"],
        ranking.diagnostic_inputs.model_artifacts,
    )
    evaluation_object = _publish_object(
        root,
        "evaluations",
        [item.model_dump(mode="json") for item in evaluations],
    )
    context_object = _publish_object(
        root,
        "evaluation-context",
        ranking.evaluation_context.model_dump(mode="json"),
    )
    diagnostic_inputs_object = _publish_object(
        root,
        "diagnostic-inputs",
        ranking.diagnostic_inputs.model_dump(mode="json"),
    )
    ranking_object = _publish_object(
        root, "ranking", ranking.ranking.model_dump(mode="json")
    )
    diagnostic_object = _publish_object(
        root,
        "diagnostics",
        [item.model_dump(mode="json") for item in diagnostics],
    )
    environment_object = _publish_object(
        root, "environment", ranking.environment.model_dump(mode="json")
    )
    predecessor = manifest_snapshots["Freeze 2"]
    critical_dependencies = (
        ("preceding_freeze", predecessor),
        ("evaluations", evaluation_object),
        ("evaluation_context", context_object),
        ("diagnostic_inputs", diagnostic_inputs_object),
        ("ranking", ranking_object),
        ("diagnostics", diagnostic_object),
        ("environment", environment_object),
    )
    critical_object = _publish_object(
        root,
        "critical-audit",
        CriticalAuditSnapshotV3(
            completed_checks=_CRITICAL_AUDIT_CHECKS,
            dependency_digests={
                item.relative_path: item.digest
                for _, item in critical_dependencies
            },
        ).model_dump(mode="json"),
    )
    current_snapshots = _deduplicate_snapshots(
        _all_chain_snapshots(role_maps)
        + tuple(
            snapshot
            for stage, snapshot in manifest_snapshots.items()
            if stage in {"Freeze 1", "Freeze 2"}
        )
        + (
            evaluation_object,
            context_object,
            diagnostic_inputs_object,
            ranking_object,
            diagnostic_object,
            environment_object,
            critical_object,
        )
    )
    try:
        audit_snapshot, _ = _run_snapshot_audit(
            current_snapshots, ranking.leakage_policy
        )
    except V3FreezeError as exc:
        raise V3FreezeError("current Freeze 3 leakage audit failed") from exc
    audit_object = _publish_object(
        root, "freeze3-leakage", audit_snapshot.model_dump(mode="json")
    )
    objects = (
        *critical_dependencies,
        ("critical_audit", critical_object),
        ("final_leakage_audit", audit_object),
    )
    manifest = FreezeManifestV3(
        freeze_version="Freeze 3",
        created_at=ranking.created_at,
        brief_digest=manifests["Freeze 2"].brief_digest,
        artifact_digests=_artifact_digests(objects),
        hidden_registry_commitment=manifests["Freeze 2"].hidden_registry_commitment,
        software_version=manifests["Freeze 2"].software_version,
    )
    published = _publish_manifest(root, destination, manifest)
    if published.content != _stable_json_bytes(manifest.model_dump(mode="json")):
        raise V3FreezeError("Freeze 3 manifest readback mismatch")
    return manifest


def verify_freeze_chain(
    root: Path,
    trusted_freeze_three_digest: str,
    leakage_policy: LeakagePolicy,
) -> FreezeChainVerification:
    """Verify the chain from an external Freeze 3 digest and current policy."""

    verified: list[Literal["Freeze 1", "Freeze 2", "Freeze 3"]] = []
    digests: dict[str, str] = {}
    try:
        structure_factory = verify_policy_structure_factory(leakage_policy)
        if structure_factory is None:
            raise V3FreezeError(
                "Freeze 3 requires a trusted structure fingerprint factory"
            )
        manifests, role_maps, manifest_snapshots = _verify_prefix(
            root, 3, trusted_freeze_three_digest
        )
        verified.extend(("Freeze 1", "Freeze 2"))
        freeze_three_roles = role_maps["Freeze 3"]
        required = {
            "preceding_freeze",
            "evaluations",
            "evaluation_context",
            "diagnostic_inputs",
            "ranking",
            "diagnostics",
            "environment",
            "critical_audit",
            "final_leakage_audit",
        }
        if set(freeze_three_roles) != required:
            raise V3FreezeError("Freeze 3 artifact set mismatch")
        family_ids = _verify_freeze_two_persisted(root, role_maps["Freeze 2"])
        rubric = EvaluationRubric.model_validate(
            _json_from_snapshot(
                role_maps["Freeze 2"]["scoring_policy"],
                "Freeze 2 scoring policy",
            )
        )
        diagnostic_artifacts = _verify_freeze_three_persisted(
            freeze_three_roles,
            rubric,
            family_ids,
            manifest_snapshots["Freeze 1"],
            role_maps["Freeze 1"],
            role_maps["Freeze 2"],
            structure_factory,
        )
        environment = FreezeEnvironmentV3.model_validate(
            _json_from_snapshot(
                freeze_three_roles["environment"], "Freeze 3 environment"
            )
        )
        _validate_environment_links(
            environment, role_maps["Freeze 2"], diagnostic_artifacts
        )
        critical = CriticalAuditSnapshotV3.model_validate(
            _json_from_snapshot(
                freeze_three_roles["critical_audit"], "Freeze 3 critical audit"
            )
        )
        expected_critical_dependencies = {
            snapshot.relative_path: snapshot.digest
            for role, snapshot in freeze_three_roles.items()
            if role not in {"critical_audit", "final_leakage_audit"}
        }
        if dict(critical.dependency_digests) != expected_critical_dependencies:
            raise V3FreezeError("Freeze 3 critical audit closure mismatch")
        audit_snapshot = LeakageAuditSnapshotV3.model_validate(
            _json_from_snapshot(
                freeze_three_roles["final_leakage_audit"],
                "final leakage audit",
            )
        )
        if audit_snapshot.policy_digest != _policy_digest(leakage_policy):
            raise V3FreezeError("Freeze 3 leakage policy mismatch")
        expected_dependencies = {
            snapshot.relative_path: snapshot.digest
            for stage, roles in role_maps.items()
            for role, snapshot in roles.items()
            if not (stage == "Freeze 3" and role == "final_leakage_audit")
        }
        for stage in ("Freeze 1", "Freeze 2"):
            snapshot = manifest_snapshots[stage]
            expected_dependencies[snapshot.relative_path] = snapshot.digest
        if dict(audit_snapshot.dependency_digests) != expected_dependencies:
            raise V3FreezeError("final leakage audit dependency closure mismatch")
        available_snapshots = {
            snapshot.relative_path: snapshot
            for roles in role_maps.values()
            for snapshot in roles.values()
        }
        available_snapshots.update(
            (snapshot.relative_path, snapshot)
            for snapshot in manifest_snapshots.values()
        )
        dependency_snapshots = tuple(
            available_snapshots[relative]
            for relative in audit_snapshot.dependency_digests
        )
        current_audit, _ = _run_snapshot_audit(
            dependency_snapshots, leakage_policy
        )
        if current_audit != audit_snapshot:
            raise V3FreezeError("Freeze 3 leakage audit is stale")
        for stage in _STAGES:
            digests[stage] = manifest_snapshots[stage].digest
        verified.append("Freeze 3")
        return FreezeChainVerification(
            valid=True,
            verified_stages=tuple(verified),
            manifest_digests=digests,
            errors=(),
        )
    except (V3FreezeError, ValueError, TypeError) as exc:
        return FreezeChainVerification(
            valid=False,
            verified_stages=tuple(verified),
            manifest_digests=digests,
            errors=(str(exc),),
        )

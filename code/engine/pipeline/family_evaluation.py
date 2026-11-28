"""Deterministic v3 family evaluation with exact evidence qualification."""

from __future__ import annotations

import hashlib
import json
import weakref
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

import yaml
from pydantic import Field, ValidationError, field_serializer, model_validator

from pipeline.evidence_registry import EvidenceRegistrySummary
from pipeline.mechanism_normalization import MechanismNormalizationPayload
from pipeline.models import EvidenceItem
from pipeline.principle_models import FrozenReactionPrincipleSet, FrozenStrictModel
from pipeline.principle_models import (
    SeedMechanism,
    SeedPrinciple,
    TransferabilityAssessment,
)
from pipeline.seed_claim_types import (
    SEED_CLAIM_TYPE_CONTRACT_ARTIFACT_KEY,
    SEED_CLAIM_TYPE_CONTRACT_PATH,
    SEED_EVIDENCE_PROJECTION_PATH,
    SeedClaimTypeError,
    SeedEvidenceProjection,
    parse_seed_claim_type_contract,
    seed_claim_type_contract_digest,
)
from pipeline.v3_evidence_import import EvidenceImportManifest
from pipeline.v3_models import (
    DIMENSIONS,
    DimensionJudgment,
    DimensionName,
    EvidenceLevel,
    FamilyEvaluation as CanonicalFamilyEvaluation,
    FreezeManifestV3,
    JudgmentState,
    PriorityRegion,
)


DEFAULT_RUBRIC_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "family_evaluation_v3.yaml"
)


class EvidenceQualificationError(ValueError):
    """Raised when evidence is missing, untrusted, or inadmissible."""


class HardBlockerError(EvidenceQualificationError):
    """Raised when a proposed hard blocker lacks qualifying evidence."""


class EvaluationRubricError(ValueError):
    """Raised when a preregistered evaluation rubric is invalid."""


class ReviewedPrincipleLink(FrozenStrictModel):
    principle_id: str = Field(min_length=1)
    admissible_dimensions: tuple[DimensionName, ...] = Field(min_length=1)


class DimensionPrincipleLink(FrozenStrictModel):
    """One exact evidence/dimension/Principle relationship used in scoring."""

    evidence_id: str = Field(min_length=1)
    dimension: DimensionName
    principle_id: str = Field(min_length=1)


EvidenceClass = Literal[
    "seed",
    "normalized_mechanism",
    "normalized_constraint",
    "transfer_assessment",
    "external_literature",
]


class QualifiedEvidenceRecord(FrozenStrictModel):
    """One exact evidence identity and its trusted admissibility metadata."""

    evidence_id: str = Field(min_length=1)
    evidence_class: EvidenceClass
    source_path: str = Field(min_length=1)
    provenance_path: str = Field(min_length=1)
    locator: str | None
    evidence_level: EvidenceLevel
    admissible_dimensions: tuple[DimensionName, ...] = Field(min_length=1)
    hard_blocker_eligible: bool = False
    reviewed_principle_links: tuple[ReviewedPrincipleLink, ...] = ()

    @model_validator(mode="after")
    def validate_qualification(self) -> "QualifiedEvidenceRecord":
        if len(set(self.admissible_dimensions)) != len(self.admissible_dimensions):
            raise ValueError("admissible dimensions must be unique")
        if (
            self.evidence_level == "traceable_external_evidence"
            and not self.locator
        ):
            raise ValueError("traceable external evidence requires a locator")
        if (
            self.hard_blocker_eligible
            and self.evidence_level != "traceable_external_evidence"
        ):
            raise ValueError("hard blocker evidence must be traceable external evidence")
        return self

    @property
    def reviewed_principle_ids(self) -> tuple[str, ...]:
        return tuple(link.principle_id for link in self.reviewed_principle_links)


_CONTEXT_BUILDER_TOKEN = object()
_SCORED_BUILDER_TOKEN = object()
_CONTEXT_ATTESTATIONS: dict[
    int, tuple[weakref.ReferenceType[object], str, str, str]
] = {}
_SCORED_ATTESTATIONS: dict[
    int, tuple[weakref.ReferenceType[object], str, str, str]
] = {}


def _stable_digest(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _records_digest(records: Sequence[QualifiedEvidenceRecord]) -> str:
    return _stable_digest(
        [record.model_dump(mode="json") for record in records]
    )


class FrozenDependencyDigest(FrozenStrictModel):
    """One immutable dependency captured in the evaluation snapshot."""

    artifact_key: str = Field(min_length=1)
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def _context_content_digest(
    records: Sequence[QualifiedEvidenceRecord],
    dependencies: Sequence[FrozenDependencyDigest],
    freeze_manifest_digest: str,
    evidence_import_manifest_digest: str,
    rubric_raw_digest: str,
    rubric_canonical_digest: str,
    frozen_principle_ids: Sequence[str],
    frozen_principle_digests: Mapping[str, str],
) -> str:
    return _stable_digest(
        {
            "records": [record.model_dump(mode="json") for record in records],
            "dependencies": [
                dependency.model_dump(mode="json") for dependency in dependencies
            ],
            "freeze_manifest_digest": freeze_manifest_digest,
            "evidence_import_manifest_digest": evidence_import_manifest_digest,
            "rubric_raw_digest": rubric_raw_digest,
            "rubric_canonical_digest": rubric_canonical_digest,
            "frozen_principle_ids": list(frozen_principle_ids),
            "frozen_principle_digests": dict(sorted(frozen_principle_digests.items())),
        }
    )


class EvidenceQualificationContext(FrozenStrictModel):
    """Attested immutable snapshot; later dependency replacement has no effect."""

    records: tuple[QualifiedEvidenceRecord, ...] = Field(min_length=1)
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    registry_commitment: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_commitment: str = Field(pattern=r"^[0-9a-f]{64}$")
    freeze_manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_import_manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    rubric_raw_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    rubric_canonical_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    frozen_dependencies: tuple[FrozenDependencyDigest, ...] = Field(min_length=1)
    frozen_principle_ids: tuple[str, ...] = Field(min_length=1)
    frozen_principle_digests: Mapping[str, str]

    def __init__(self, **data: Any) -> None:
        token = data.pop("_builder_token", None)
        if token is not _CONTEXT_BUILDER_TOKEN:
            raise EvidenceQualificationError(
                "EvidenceQualificationContext requires builder attestation"
            )
        super().__init__(**data)
        _attest_context(self)

    @model_validator(mode="after")
    def reject_exact_id_collisions(self) -> "EvidenceQualificationContext":
        seen: dict[str, str] = {}
        for record in self.records:
            previous = seen.get(record.evidence_id)
            if previous is not None:
                raise ValueError(
                    "exact evidence ID collision: "
                    f"{record.evidence_id} ({previous}, {record.source_path})"
                )
            seen[record.evidence_id] = record.source_path
        if set(self.frozen_principle_digests) != set(self.frozen_principle_ids):
            raise ValueError("frozen Principle digest keys must match frozen IDs")
        if any(
            len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            for digest in self.frozen_principle_digests.values()
        ):
            raise ValueError("frozen Principle digests must be SHA-256 hex")
        object.__setattr__(
            self,
            "frozen_principle_digests",
            MappingProxyType(dict(sorted(self.frozen_principle_digests.items()))),
        )
        return self

    @field_serializer("frozen_principle_digests")
    def serialize_frozen_principle_digests(
        self, value: Mapping[str, str]
    ) -> dict[str, str]:
        return dict(value)

    def require(
        self,
        evidence_id: str,
        dimension: DimensionName,
        *,
        external: bool = False,
        hard_blocker: bool = False,
        reviewed_principle: bool = False,
    ) -> QualifiedEvidenceRecord:
        record = next(
            (item for item in self.records if item.evidence_id == evidence_id), None
        )
        if record is None:
            raise EvidenceQualificationError(
                f"unknown exact evidence ID: {evidence_id}"
            )
        if dimension not in record.admissible_dimensions:
            raise EvidenceQualificationError(
                f"evidence {evidence_id} is not admissible for {dimension}"
            )
        if external and record.evidence_level != "traceable_external_evidence":
            raise EvidenceQualificationError(
                f"{dimension} requires traceable external evidence: {evidence_id}"
            )
        if hard_blocker and not record.hard_blocker_eligible:
            raise EvidenceQualificationError(
                f"evidence is not qualified for a hard blocker: {evidence_id}"
            )
        if reviewed_principle and not any(
            dimension in link.admissible_dimensions
            for link in record.reviewed_principle_links
        ):
            raise EvidenceQualificationError(
                "evidence lacks an applicable reviewed Principle binding: "
                f"{evidence_id} ({dimension})"
            )
        return record


def restore_evidence_qualification_context(
    payload: Mapping[str, Any],
) -> EvidenceQualificationContext:
    """Restore a frozen context after independently checking its commitments."""

    context = EvidenceQualificationContext(
        _builder_token=_CONTEXT_BUILDER_TOKEN,
        **dict(payload),
    )
    expected_content = _context_content_digest(
        context.records,
        context.frozen_dependencies,
        context.freeze_manifest_digest,
        context.evidence_import_manifest_digest,
        context.rubric_raw_digest,
        context.rubric_canonical_digest,
        context.frozen_principle_ids,
        context.frozen_principle_digests,
    )
    expected_artifacts = _stable_digest(
        [item.model_dump(mode="json") for item in context.frozen_dependencies]
    )
    registry_dependencies = tuple(
        item
        for item in context.frozen_dependencies
        if item.artifact_key == EVIDENCE_REGISTRY_ARTIFACT_KEY
    )
    if (
        context.content_digest != expected_content
        or context.artifact_commitment != expected_artifacts
        or len(registry_dependencies) != 1
        or registry_dependencies[0].sha256 != context.registry_commitment
    ):
        raise EvidenceQualificationError(
            "frozen evidence qualification context commitment mismatch"
        )
    return context


def _attest_context(context: EvidenceQualificationContext) -> None:
    context_id = id(context)

    def discard(_: weakref.ReferenceType[object]) -> None:
        _CONTEXT_ATTESTATIONS.pop(context_id, None)

    _CONTEXT_ATTESTATIONS[context_id] = (
        weakref.ref(context, discard),
        context.content_digest,
        context.registry_commitment,
        context.artifact_commitment,
    )


class HardBlockerCandidate(FrozenStrictModel):
    """A proposed exclusion gate that still requires evidence qualification."""

    blocker_id: str = Field(min_length=1)
    dimension: DimensionName
    statement: str = Field(min_length=1)
    evidence_ids: tuple[str, ...] = Field(min_length=1)
    counterevidence_ids: tuple[str, ...]
    evidence_level: EvidenceLevel
    source_paths: tuple[str, ...] = Field(min_length=1)


class QualifiedBlocker(FrozenStrictModel):
    """A blocker whose evidence must still be reverified at scoring time."""

    blocker_id: str = Field(min_length=1)
    dimension: DimensionName
    statement: str = Field(min_length=1)
    evidence_ids: tuple[str, ...] = Field(min_length=1)
    counterevidence_ids: tuple[str, ...]
    source_paths: tuple[str, ...] = Field(min_length=1)
    reviewed_principle_ids: tuple[str, ...] = ()
    evidence_level: Literal["traceable_external_evidence"] = (
        "traceable_external_evidence"
    )


class RegionThreshold(FrozenStrictModel):
    min_compatibility: float = Field(ge=0, le=4)
    min_evidence_confidence: float = Field(ge=0, le=4)
    max_uncertainty_burden: float = Field(ge=0, le=4)
    max_failure_risk: float = Field(ge=0, le=4)


class EvaluationRubric(FrozenStrictModel):
    """Pre-registered deterministic state mapping and decision boundaries."""

    version: Literal["3.0"]
    state_scores: Mapping[JudgmentState, int | None]
    core_dimensions: tuple[DimensionName, ...]
    critical_dimensions: tuple[DimensionName, ...]
    evidence_confidence_dimension: Literal["evidence_quality"]
    failure_risk_dimension: Literal["competing_pathway_risk"]
    risk_direction: Literal["adverse"]
    ranking_weights: Mapping[DimensionName, float]
    ranking_weight_bounds: Mapping[DimensionName, tuple[float, float]]
    ranking_sample_count: int = Field(ge=100)
    ranking_stability_max_span: int = Field(ge=0)
    evidence_aggregation_policy: Mapping[
        Literal["positive", "conditional", "adverse", "mixed", "none"],
        JudgmentState,
    ]
    seed_evidence_type_dimensions: Mapping[str, tuple[DimensionName, ...]]
    priority_regions: Mapping[str, RegionThreshold | None]

    @model_validator(mode="after")
    def validate_complete_rubric(self) -> "EvaluationRubric":
        expected_states = {
            "support": 4,
            "conditional_support": 2,
            "contradiction": 0,
            "unknown": None,
        }
        if dict(self.state_scores) != expected_states:
            raise ValueError("state_scores must preserve the preregistered default mapping")
        if not self.core_dimensions or len(set(self.core_dimensions)) != len(
            self.core_dimensions
        ):
            raise ValueError("core_dimensions must be non-empty and unique")
        if not set(self.critical_dimensions).issubset(self.core_dimensions):
            raise ValueError("critical_dimensions must be core dimensions")
        if not self.seed_evidence_type_dimensions or any(
            not evidence_type
            or not dimensions
            or len(set(dimensions)) != len(dimensions)
            or "evidence_quality" in dimensions
            for evidence_type, dimensions in self.seed_evidence_type_dimensions.items()
        ):
            raise ValueError(
                "seed evidence type mappings must be nonempty, unique, and conservative"
            )
        if set(self.ranking_weights) != set(DIMENSIONS) or any(
            weight <= 0 for weight in self.ranking_weights.values()
        ):
            raise ValueError("ranking_weights must define seven positive weights")
        if set(self.ranking_weight_bounds) != set(DIMENSIONS):
            raise ValueError("ranking_weight_bounds must define all seven dimensions")
        for dimension, bounds in self.ranking_weight_bounds.items():
            lower, upper = bounds
            primary = self.ranking_weights[dimension]
            if lower <= 0 or lower > upper or not lower <= primary <= upper:
                raise ValueError(
                    "ranking weight bounds must be positive and contain primary weights"
                )
        if dict(self.evidence_aggregation_policy) != {
            "positive": "support",
            "conditional": "conditional_support",
            "adverse": "contradiction",
            "mixed": "conditional_support",
            "none": "unknown",
        }:
            raise ValueError(
                "evidence_aggregation_policy must preserve preregistered states"
            )
        expected_regions = {
            "priority_a",
            "priority_b",
            "priority_c",
            "boundary",
            "excluded",
            "unknown",
        }
        if set(self.priority_regions) != expected_regions:
            raise ValueError("priority_regions must define all six regions")
        if any(
            self.priority_regions[name] is None
            for name in ("priority_a", "priority_b", "priority_c")
        ):
            raise ValueError("positive priority regions require thresholds")
        if any(
            self.priority_regions[name] is not None
            for name in ("boundary", "excluded", "unknown")
        ):
            raise ValueError("gate and fallback regions cannot define thresholds")
        return self


def evaluation_rubric_digest(rubric: EvaluationRubric) -> str:
    """Return the canonical digest used to bind scoring to its snapshot."""

    validated = EvaluationRubric.model_validate(rubric.model_dump(mode="python"))
    return _stable_digest(validated.model_dump(mode="json"))


class EvidenceContribution(FrozenStrictModel):
    """One attested evidence contribution used for paper-omission stress tests."""

    dimension: DimensionName
    evidence_id: str = Field(min_length=1)
    source_paper: str | None
    direction: Literal["positive", "adverse"]
    state: JudgmentState
    evidence_class: EvidenceClass
    evidence_level: EvidenceLevel
    is_external: bool
    quality_eligible: bool
    is_counterevidence: bool


class DerivedFamilyMetrics(FrozenStrictModel):
    dimension_scores: Mapping[DimensionName, int | None]
    compatibility_index: float | None = Field(ge=0, le=4)
    evidence_confidence: float | None = Field(ge=0, le=4)
    uncertainty_burden: float = Field(ge=0, le=4)
    failure_risk: float | None = Field(ge=0, le=4)
    critical_unknowns: tuple[DimensionName, ...]
    priority_region: PriorityRegion

    @model_validator(mode="after")
    def freeze_dimension_scores(self) -> "DerivedFamilyMetrics":
        object.__setattr__(
            self,
            "dimension_scores",
            MappingProxyType(dict(self.dimension_scores)),
        )
        return self

    @field_serializer("dimension_scores")
    def serialize_dimension_scores(
        self, dimension_scores: Mapping[DimensionName, int | None]
    ) -> dict[DimensionName, int | None]:
        return dict(dimension_scores)


class ScoredFamilyEvaluation(FrozenStrictModel):
    """Deterministic metrics layered over the canonical v3 evaluation."""

    family_id: str = Field(min_length=1)
    judgments: tuple[DimensionJudgment, ...]
    dimension_scores: Mapping[DimensionName, int | None]
    compatibility_index: float | None = Field(ge=0, le=4)
    evidence_confidence: float | None = Field(ge=0, le=4)
    uncertainty_burden: float = Field(ge=0, le=4)
    failure_risk: float | None = Field(ge=0, le=4)
    critical_unknowns: tuple[DimensionName, ...]
    qualified_blocker_ids: tuple[str, ...]
    qualified_blockers: tuple[QualifiedBlocker, ...]
    reviewed_principle_ids: tuple[str, ...]
    reviewed_principle_digests: Mapping[str, str]
    evidence_principle_links: Mapping[str, tuple[ReviewedPrincipleLink, ...]]
    dimension_principle_links: tuple[DimensionPrincipleLink, ...]
    evidence_record_digests: Mapping[str, str]
    evidence_source_paths: Mapping[str, str] = Field(default_factory=dict)
    evidence_contributions: tuple[EvidenceContribution, ...]
    rubric_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    context_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    scored_content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    priority_region: PriorityRegion

    def __init__(self, **data: Any) -> None:
        token = data.pop("_builder_token", None)
        if token is not _SCORED_BUILDER_TOKEN:
            raise EvidenceQualificationError(
                "ScoredFamilyEvaluation requires score_family attestation"
            )
        super().__init__(**data)

    @model_validator(mode="after")
    def freeze_scored_mappings(self) -> "ScoredFamilyEvaluation":
        object.__setattr__(
            self,
            "dimension_scores",
            MappingProxyType(
                {
                    dimension: self.dimension_scores[dimension]
                    for dimension in DIMENSIONS
                }
            ),
        )
        object.__setattr__(
            self,
            "evidence_source_paths",
            MappingProxyType(dict(sorted(self.evidence_source_paths.items()))),
        )
        if set(self.reviewed_principle_digests) != set(self.reviewed_principle_ids):
            raise ValueError("reviewed Principle digest keys must match reviewed IDs")
        object.__setattr__(
            self,
            "reviewed_principle_digests",
            MappingProxyType(dict(sorted(self.reviewed_principle_digests.items()))),
        )
        object.__setattr__(
            self,
            "evidence_principle_links",
            MappingProxyType(
                {
                    evidence_id: tuple(links)
                    for evidence_id, links in sorted(
                        self.evidence_principle_links.items()
                    )
                }
            ),
        )
        if tuple(blocker.blocker_id for blocker in self.qualified_blockers) != (
            self.qualified_blocker_ids
        ):
            raise ValueError("qualified blocker details must match blocker IDs")
        referenced_evidence_ids = {
            evidence_id
            for judgment in self.judgments
            for evidence_id in (*judgment.evidence_ids, *judgment.counterevidence_ids)
        }.union(
            evidence_id
            for blocker in self.qualified_blockers
            for evidence_id in (*blocker.evidence_ids, *blocker.counterevidence_ids)
        )
        if set(self.evidence_record_digests) != referenced_evidence_ids:
            raise ValueError(
                "evidence record digest keys must match all scored evidence IDs"
            )
        if set(self.evidence_principle_links) != referenced_evidence_ids:
            raise ValueError(
                "evidence Principle-link keys must match all scored evidence IDs"
            )
        dimension_links = tuple(
            sorted(
                self.dimension_principle_links,
                key=lambda item: (item.evidence_id, item.dimension, item.principle_id),
            )
        )
        if len(set(dimension_links)) != len(dimension_links):
            raise ValueError("dimension-qualified Principle links must be unique")
        usage_pairs = {
            (evidence_id, judgment.dimension)
            for judgment in self.judgments
            for evidence_id in (*judgment.evidence_ids, *judgment.counterevidence_ids)
        }.union(
            (evidence_id, blocker.dimension)
            for blocker in self.qualified_blockers
            for evidence_id in (*blocker.evidence_ids, *blocker.counterevidence_ids)
        )
        if any(
            (link.evidence_id, link.dimension) not in usage_pairs
            or not any(
                reviewed.principle_id == link.principle_id
                and link.dimension in reviewed.admissible_dimensions
                for reviewed in self.evidence_principle_links[link.evidence_id]
            )
            for link in dimension_links
        ):
            raise ValueError(
                "dimension-qualified Principle link lacks exact admissibility"
            )
        required_pairs = {
            (evidence_id, judgment.dimension)
            for judgment in self.judgments
            for evidence_id in judgment.evidence_ids
        }.union(
            (evidence_id, blocker.dimension)
            for blocker in self.qualified_blockers
            for evidence_id in blocker.evidence_ids
        )
        linked_pairs = {
            (link.evidence_id, link.dimension) for link in dimension_links
        }
        if not required_pairs.issubset(linked_pairs):
            raise ValueError(
                "positive judgment and blocker evidence requires a dimension-qualified Principle"
            )
        if {link.principle_id for link in dimension_links} != set(
            self.reviewed_principle_ids
        ):
            raise ValueError(
                "reviewed Principle IDs must match dimension-qualified links"
            )
        object.__setattr__(self, "dimension_principle_links", dimension_links)
        if any(
            len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            for digest in self.evidence_record_digests.values()
        ):
            raise ValueError("evidence record digests must be SHA-256 hex")
        if self.priority_region == "excluded" and not self.qualified_blockers:
            raise ValueError("excluded scored evaluation requires qualified blockers")
        if self.priority_region == "unknown" and not self.critical_unknowns:
            raise ValueError("unknown scored evaluation requires critical unknowns")
        object.__setattr__(
            self,
            "evidence_record_digests",
            MappingProxyType(dict(sorted(self.evidence_record_digests.items()))),
        )
        return self

    @field_serializer("dimension_scores")
    def serialize_scored_dimension_scores(
        self, dimension_scores: Mapping[DimensionName, int | None]
    ) -> dict[DimensionName, int | None]:
        return dict(dimension_scores)

    @field_serializer("evidence_source_paths")
    def serialize_evidence_source_paths(
        self, evidence_source_paths: Mapping[str, str]
    ) -> dict[str, str]:
        return dict(evidence_source_paths)

    @field_serializer("reviewed_principle_digests")
    def serialize_reviewed_principle_digests(
        self, value: Mapping[str, str]
    ) -> dict[str, str]:
        return dict(value)

    @field_serializer("evidence_principle_links")
    def serialize_evidence_principle_links(
        self, value: Mapping[str, tuple[ReviewedPrincipleLink, ...]]
    ) -> dict[str, tuple[ReviewedPrincipleLink, ...]]:
        return dict(value)

    @field_serializer("evidence_record_digests")
    def serialize_evidence_record_digests(
        self, value: Mapping[str, str]
    ) -> dict[str, str]:
        return dict(value)

    def to_canonical(self) -> CanonicalFamilyEvaluation:
        return to_canonical_family_evaluation(self)


def _scored_content_digest(evaluation: ScoredFamilyEvaluation) -> str:
    return _stable_digest(
        evaluation.model_dump(
            mode="json", exclude={"scored_content_digest"}
        )
    )


def _attest_scored_evaluation(evaluation: ScoredFamilyEvaluation) -> None:
    evaluation_id = id(evaluation)

    def discard(_: weakref.ReferenceType[object]) -> None:
        _SCORED_ATTESTATIONS.pop(evaluation_id, None)

    _SCORED_ATTESTATIONS[evaluation_id] = (
        weakref.ref(evaluation, discard),
        evaluation.scored_content_digest,
        evaluation.rubric_digest,
        evaluation.context_digest,
    )


def _build_scored_evaluation(
    *, attest: bool = True, **data: Any
) -> ScoredFamilyEvaluation:
    provisional = ScoredFamilyEvaluation(
        _builder_token=_SCORED_BUILDER_TOKEN,
        scored_content_digest="0" * 64,
        **data,
    )
    evaluation = ScoredFamilyEvaluation(
        _builder_token=_SCORED_BUILDER_TOKEN,
        scored_content_digest=_scored_content_digest(provisional),
        **data,
    )
    if attest:
        _attest_scored_evaluation(evaluation)
    return evaluation


def verify_scored_family_evaluation(
    evaluation: ScoredFamilyEvaluation, rubric: EvaluationRubric
) -> ScoredFamilyEvaluation:
    """Verify score-family provenance, immutable content, and rubric binding."""

    if not isinstance(evaluation, ScoredFamilyEvaluation):
        raise EvidenceQualificationError(
            "ranking requires an attested ScoredFamilyEvaluation"
        )
    try:
        supplied_rubric_digest = evaluation_rubric_digest(rubric)
    except (AttributeError, ValidationError) as exc:
        raise EvidenceQualificationError(
            "ranking requires the canonical attested EvaluationRubric"
        ) from exc
    attestation = _SCORED_ATTESTATIONS.get(id(evaluation))
    if (
        attestation is None
        or attestation[0]() is not evaluation
        or attestation[1] != evaluation.scored_content_digest
        or attestation[2] != evaluation.rubric_digest
        or attestation[3] != evaluation.context_digest
        or _scored_content_digest(evaluation) != evaluation.scored_content_digest
        or supplied_rubric_digest != evaluation.rubric_digest
    ):
        raise EvidenceQualificationError(
            "ScoredFamilyEvaluation failed score_family attestation"
        )
    return evaluation


_MECHANISM_DIMENSIONS: dict[str, tuple[DimensionName, ...]] = {
    "elementary_step": ("elementary_step_match",),
    "intermediate": (
        "electrophile_state_match",
        "reactive_state_accessibility",
    ),
    "electronic_requirement": ("electrophile_state_match",),
    "nucleophile_requirement": ("reactive_state_accessibility",),
    "catalyst_role": ("condition_compatibility",),
    "condition_effect": ("condition_compatibility",),
    "failure_boundary": ("competing_pathway_risk",),
}
_CONSTRAINT_DIMENSIONS: dict[str, tuple[DimensionName, ...]] = {
    "electronic": ("electrophile_state_match",),
    "steric": ("target_selectivity",),
    "catalyst": ("condition_compatibility",),
    "condition": ("condition_compatibility",),
    "stability": ("reactive_state_accessibility", "competing_pathway_risk"),
}
FROZEN_PRINCIPLES_ARTIFACT_KEY = "frozen_principles"
EVIDENCE_REGISTRY_ARTIFACT_KEY = "evidence_registry"
SCORING_RUBRIC_ARTIFACT_KEY = "scoring_rubric"
FAMILY_EVALUATION_RUBRIC_ARTIFACT_KEY = "family_evaluation_rubric"
EVIDENCE_IMPORT_MANIFEST_ARTIFACT_KEY = "evidence_import_manifest"
VALIDATED_EVIDENCE_ARTIFACT_PREFIX = "validated_evidence"


def validated_evidence_artifact_key(relative_path: str) -> str:
    """Return the collision-resistant freeze-manifest key for raw evidence bytes."""

    path_digest = hashlib.sha256(relative_path.encode("utf-8")).hexdigest()
    return f"{VALIDATED_EVIDENCE_ARTIFACT_PREFIX}:{path_digest}"


def _read_json_snapshot(
    path: Path, label: str
) -> tuple[bytes, dict[str, object]]:
    try:
        dependency_bytes = path.read_bytes()
        payload = json.loads(dependency_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceQualificationError(
            f"required {label} is missing or invalid: {path}"
        ) from exc
    if not isinstance(payload, dict):
        raise EvidenceQualificationError(f"required {label} must be an object")
    return dependency_bytes, payload


def _read_authorized_json_snapshot(
    path: Path, label: str, expected_digest: str
) -> tuple[bytes, dict[str, object]]:
    try:
        dependency_bytes = path.read_bytes()
    except OSError as exc:
        raise EvidenceQualificationError(f"required {label} is missing: {path}") from exc
    if hashlib.sha256(dependency_bytes).hexdigest() != expected_digest:
        raise EvidenceQualificationError(f"{label} digest mismatch: {path}")
    try:
        payload = json.loads(dependency_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceQualificationError(f"required {label} is invalid: {path}") from exc
    if not isinstance(payload, dict):
        raise EvidenceQualificationError(f"required {label} must be an object")
    return dependency_bytes, payload


def _evidence_import_content_digest(manifest: EvidenceImportManifest) -> str:
    return _stable_digest(
        {
            "version": manifest.version,
            "brief_digest": manifest.brief_digest,
            "leakage_policy_digest": manifest.leakage_policy_digest,
            "queue_digest": manifest.queue_digest,
            "queue_scope": manifest.queue_scope,
            "provenance_paths": manifest.provenance_paths,
            "seed_claim_type_contract_version": (
                manifest.seed_claim_type_contract_version
            ),
            "seed_claim_type_contract_path": (
                manifest.seed_claim_type_contract_path
            ),
            "seed_claim_type_contract_digest": (
                manifest.seed_claim_type_contract_digest
            ),
            "seed_claim_type_contract_sha256": (
                manifest.seed_claim_type_contract_sha256
            ),
            "accepted": [
                artifact.model_dump(mode="json") for artifact in manifest.accepted
            ],
            "schema_versions": manifest.schema_versions,
        }
    )


def _external_qualification(item: EvidenceItem) -> bool:
    return bool(
        item.reviewer_status in {"accepted", "revised"}
        and item.attribution == "author_observation"
        and item.evidence_label in {"LITERATURE FACT", "EXPERIMENTAL FACT"}
        and item.quotation
        and (item.source_span_ids or item.pdf_page)
    )


def build_evidence_qualification_context(
    output_root: Path,
    registry: EvidenceRegistrySummary,
    frozen_principle_path: Path,
    freeze_manifest_path: Path,
    evidence_import_manifest_path: Path,
    rubric_path: Path | None = None,
) -> EvidenceQualificationContext:
    """Build one immutable snapshot from manifest-bound canonical dependencies."""

    root = output_root.resolve()
    seed_contract_path = root / SEED_CLAIM_TYPE_CONTRACT_PATH
    resolved_dependencies: list[tuple[Path, str]] = []
    for dependency_path, label in (
        (frozen_principle_path, "frozen Principle artifact"),
        (freeze_manifest_path, "v3 freeze manifest"),
        (evidence_import_manifest_path, "evidence import manifest"),
        (rubric_path or DEFAULT_RUBRIC_PATH, "family evaluation rubric"),
        (seed_contract_path, "Seed claim type contract"),
    ):
        try:
            resolved = dependency_path.resolve()
            resolved.relative_to(root)
        except (OSError, ValueError) as exc:
            raise EvidenceQualificationError(
                f"{label} must be inside the output root"
            ) from exc
        resolved_dependencies.append((resolved, label))
    frozen_path = resolved_dependencies[0][0]
    manifest_path = resolved_dependencies[1][0]
    import_manifest_path = resolved_dependencies[2][0]
    resolved_rubric_path = resolved_dependencies[3][0]
    resolved_seed_contract_path = resolved_dependencies[4][0]
    if (
        resolved_seed_contract_path.relative_to(root).as_posix()
        != SEED_CLAIM_TYPE_CONTRACT_PATH
    ):
        raise EvidenceQualificationError(
            "Seed claim type contract resolved path must be canonical"
        )
    namespaces: dict[str, str] = {}
    for registry_record in registry.records:
        namespace = registry_record.sha256[:12]
        prior_source = namespaces.get(namespace)
        if prior_source is not None and prior_source != registry_record.source_path:
            raise EvidenceQualificationError(
                f"evidence namespace collision: {namespace}"
            )
        namespaces[namespace] = registry_record.source_path
    registry_commitment = _stable_digest(registry.model_dump(mode="json"))
    dependency_digests: list[FrozenDependencyDigest] = [
        FrozenDependencyDigest(
            artifact_key=EVIDENCE_REGISTRY_ARTIFACT_KEY,
            path="registry://current-snapshot",
            sha256=registry_commitment,
        )
    ]
    import_manifest_bytes, _ = _read_json_snapshot(
        import_manifest_path, "evidence import manifest"
    )
    try:
        rubric_bytes = resolved_rubric_path.read_bytes()
        evidence_import_manifest = EvidenceImportManifest.model_validate_json(
            import_manifest_bytes
        )
        rubric_payload = yaml.safe_load(rubric_bytes.decode("utf-8"))
        evaluation_rubric = EvaluationRubric.model_validate(rubric_payload)
        seed_contract_bytes = resolved_seed_contract_path.read_bytes()
        seed_claim_type_contract = parse_seed_claim_type_contract(
            seed_contract_bytes
        )
    except (
        OSError,
        SeedClaimTypeError,
        ValidationError,
        UnicodeDecodeError,
        yaml.YAMLError,
    ) as exc:
        raise EvidenceQualificationError(
            "evidence import manifest, evaluation rubric, or Seed claim type "
            "contract is invalid"
        ) from exc
    seed_contract_digest = seed_claim_type_contract_digest(
        seed_claim_type_contract
    )
    seed_contract_sha256 = hashlib.sha256(seed_contract_bytes).hexdigest()
    if (
        evidence_import_manifest.manifest_digest
        != _evidence_import_content_digest(evidence_import_manifest)
        or evidence_import_manifest.queue_digest != registry.queue_digest
        or set(evidence_import_manifest.queue_scope)
        != {record.source_path for record in registry.records}
    ):
        raise EvidenceQualificationError(
            "evidence import manifest content or queue binding is invalid"
        )
    if (
        evidence_import_manifest.seed_claim_type_contract_path
        != SEED_CLAIM_TYPE_CONTRACT_PATH
        or evidence_import_manifest.seed_claim_type_contract_version
        != seed_claim_type_contract.version
        or evidence_import_manifest.seed_claim_type_contract_digest
        != seed_contract_digest
        or evidence_import_manifest.seed_claim_type_contract_sha256
        != seed_contract_sha256
    ):
        raise EvidenceQualificationError(
            "Seed claim type contract does not match evidence import manifest"
        )
    dependency_digests.append(
        FrozenDependencyDigest(
            artifact_key=SEED_CLAIM_TYPE_CONTRACT_ARTIFACT_KEY,
            path=resolved_seed_contract_path.relative_to(root).as_posix(),
            sha256=seed_contract_sha256,
        )
    )
    accepted_paths: dict[str, tuple[str, bytes, dict[str, object]]] = {}
    if set(evidence_import_manifest.accepted_paths).intersection(
        evidence_import_manifest.rejected_paths
    ):
        raise EvidenceQualificationError(
            "evidence import manifest accepts a rejected source"
        )
    for artifact in evidence_import_manifest.accepted:
        artifact_path = (root / artifact.path).resolve()
        try:
            normalized_artifact_path = artifact_path.relative_to(root).as_posix()
        except ValueError as exc:
            raise EvidenceQualificationError(
                "accepted evidence artifact escaped the output root"
            ) from exc
        if normalized_artifact_path != artifact.path:
            raise EvidenceQualificationError(
                f"accepted evidence artifact path is not canonical: {artifact.path}"
            )
        artifact_bytes, artifact_payload = _read_json_snapshot(
            artifact_path, "accepted evidence artifact"
        )
        if hashlib.sha256(artifact_bytes).hexdigest() != artifact.sha256:
            raise EvidenceQualificationError(
                f"accepted evidence artifact digest mismatch: {artifact.path}"
            )
        if artifact.path in accepted_paths:
            raise EvidenceQualificationError(
                f"duplicate accepted evidence artifact path: {artifact.path}"
            )
        accepted_paths[artifact.path] = (
            artifact.artifact_type,
            artifact_bytes,
            artifact_payload,
        )
        dependency_digests.append(
            FrozenDependencyDigest(
                artifact_key=f"evidence_import:{artifact.artifact_type}:{artifact.path}",
                path=artifact.path,
                sha256=artifact.sha256,
            )
        )
    evidence_import_raw_digest = hashlib.sha256(import_manifest_bytes).hexdigest()
    rubric_raw_digest = hashlib.sha256(rubric_bytes).hexdigest()
    rubric_canonical_digest = evaluation_rubric_digest(evaluation_rubric)
    frozen_bytes, _ = _read_json_snapshot(frozen_path, "frozen Principle artifact")
    manifest_bytes, _ = _read_json_snapshot(manifest_path, "v3 freeze manifest")
    try:
        frozen_principles = FrozenReactionPrincipleSet.model_validate_json(frozen_bytes)
        freeze_manifest = FreezeManifestV3.model_validate_json(manifest_bytes)
    except ValidationError as exc:
        raise EvidenceQualificationError(
            "canonical frozen Principle set or v3 freeze manifest is invalid"
        ) from exc
    frozen_digest = hashlib.sha256(frozen_bytes).hexdigest()
    manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
    required_manifest_digests = {
        FROZEN_PRINCIPLES_ARTIFACT_KEY: frozen_digest,
        EVIDENCE_REGISTRY_ARTIFACT_KEY: registry_commitment,
        SCORING_RUBRIC_ARTIFACT_KEY: frozen_principles.scoring_digest,
        EVIDENCE_IMPORT_MANIFEST_ARTIFACT_KEY: evidence_import_raw_digest,
        FAMILY_EVALUATION_RUBRIC_ARTIFACT_KEY: rubric_raw_digest,
    }
    for artifact_key, expected_digest in required_manifest_digests.items():
        actual_digest = freeze_manifest.artifact_digests.get(artifact_key)
        if actual_digest != expected_digest:
            raise EvidenceQualificationError(
                "v3 freeze manifest has missing or mismatched dependency digest: "
                f"{artifact_key}"
            )
    if (
        frozen_principles.source_digest != registry.queue_digest
        or frozen_principles.freeze_version != freeze_manifest.freeze_version
        or frozen_principles.created_at != freeze_manifest.created_at
    ):
        raise EvidenceQualificationError(
            "frozen Principle source/scoring/freeze metadata does not match manifest"
        )
    principle_ids = [
        principle.principle_id for principle in frozen_principles.principles
    ]
    if len(principle_ids) != len(set(principle_ids)) or any(
        principle.status not in {"accepted", "revised"}
        or principle.review_status not in {"accepted", "revised"}
        or principle.freeze_version != frozen_principles.freeze_version
        for principle in frozen_principles.principles
    ):
        raise EvidenceQualificationError(
            "canonical frozen Principle set is not authoritatively reviewed"
        )
    dependency_digests.extend(
        (
            FrozenDependencyDigest(
                artifact_key=EVIDENCE_IMPORT_MANIFEST_ARTIFACT_KEY,
                path=import_manifest_path.relative_to(root).as_posix(),
                sha256=evidence_import_raw_digest,
            ),
            FrozenDependencyDigest(
                artifact_key=FAMILY_EVALUATION_RUBRIC_ARTIFACT_KEY,
                path=resolved_rubric_path.relative_to(root).as_posix(),
                sha256=rubric_raw_digest,
            ),
            FrozenDependencyDigest(
                artifact_key=FROZEN_PRINCIPLES_ARTIFACT_KEY,
                path=frozen_path.relative_to(root).as_posix(),
                sha256=frozen_digest,
            ),
            FrozenDependencyDigest(
                artifact_key="freeze_manifest_v3",
                path=manifest_path.relative_to(root).as_posix(),
                sha256=manifest_digest,
            ),
        )
    )
    pending: list[QualifiedEvidenceRecord] = []
    seed_mechanism_references: set[str] = set()
    seed_principle_references: set[str] = set()
    for accepted_path, (artifact_type, _, payload) in accepted_paths.items():
        if artifact_type != "seed":
            continue
        try:
            if accepted_path == SEED_EVIDENCE_PROJECTION_PATH:
                projection = SeedEvidenceProjection.model_validate(payload)
                if (
                    projection.claim_type_contract_version
                    != evidence_import_manifest.seed_claim_type_contract_version
                    or projection.claim_type_contract_digest
                    != evidence_import_manifest.seed_claim_type_contract_digest
                    or projection.source_path
                    not in evidence_import_manifest.provenance_paths
                ):
                    raise ValueError(
                        "Seed projection contract or provenance metadata is invalid"
                    )
                raw_source_path = (root / projection.source_path).resolve()
                try:
                    normalized_source_path = raw_source_path.relative_to(
                        root
                    ).as_posix()
                except ValueError as exc:
                    raise ValueError(
                        "Seed projection source escaped the output root"
                    ) from exc
                if normalized_source_path != projection.source_path:
                    raise ValueError("Seed projection source path is not canonical")
                try:
                    raw_source_bytes = raw_source_path.read_bytes()
                except OSError as exc:
                    raise ValueError("Seed projection source is missing") from exc
                if (
                    hashlib.sha256(raw_source_bytes).hexdigest()
                    != projection.source_sha256
                ):
                    raise ValueError("Seed projection source digest mismatch")
                dependency_digests.append(
                    FrozenDependencyDigest(
                        artifact_key=(
                            f"evidence_import:seed_provenance:{projection.source_path}"
                        ),
                        path=projection.source_path,
                        sha256=projection.source_sha256,
                    )
                )
                for seed in projection.seed_evidence:
                    seed_dimensions = evaluation_rubric.seed_evidence_type_dimensions.get(
                        seed.normalized_claim_type
                    )
                    if (
                        seed.reviewer_status not in {"accepted", "revised"}
                        or seed.evidence.source_type != "seed"
                        or "::" in seed.evidence.evidence_id
                        or seed_dimensions is None
                    ):
                        raise ValueError(
                            "normalized Seed claim type or exact Seed ID is not accepted"
                        )
                    pending.append(
                        QualifiedEvidenceRecord(
                            evidence_id=seed.evidence.evidence_id,
                            evidence_class="seed",
                            source_path=seed.evidence.source_id,
                            provenance_path=accepted_path,
                            locator=seed.evidence.locator,
                            evidence_level="model_physical_organic_inference",
                            admissible_dimensions=seed_dimensions,
                        )
                    )
            elif Path(accepted_path).name == "seed_evidence.json":
                raise ValueError(
                    "accepted Seed evidence must be a normalized Seed projection"
                )
            elif Path(accepted_path).name == "seed_mechanism.json":
                seed_mechanism_references.update(
                    SeedMechanism.model_validate(payload).evidence_ids
                )
            elif Path(accepted_path).name == "seed_principle.json":
                seed_principle_references.update(
                    SeedPrinciple.model_validate(payload).supporting_seed_evidence
                )
            else:
                raise ValueError("unknown accepted seed artifact")
        except (ValidationError, ValueError) as exc:
            raise EvidenceQualificationError(
                "invalid accepted Seed artifact; evidence must use a normalized "
                f"Seed projection: {accepted_path}"
            ) from exc

    seed_ids = {
        record.evidence_id for record in pending if record.evidence_class == "seed"
    }
    if not seed_mechanism_references <= seed_ids:
        raise EvidenceQualificationError(
            "accepted seed mechanism references unknown exact seed evidence"
        )
    if not seed_principle_references <= seed_mechanism_references:
        raise EvidenceQualificationError(
            "accepted seed Principle references ungrounded seed evidence"
        )

    authorized_validated_paths: dict[
        str, tuple[Path, str, str]
    ] = {}
    validated_keys: dict[str, str] = {}
    for registry_record in registry.records:
        provenance_path = (root / registry_record.validated_path).resolve()
        try:
            relative_path = provenance_path.relative_to(root).as_posix()
        except ValueError as exc:
            raise EvidenceQualificationError(
                "validated evidence artifact escaped the output root"
            ) from exc
        if relative_path != registry_record.validated_path:
            raise EvidenceQualificationError(
                "evidence registry validated path is not canonical"
            )
        artifact_key = validated_evidence_artifact_key(relative_path)
        prior_path = validated_keys.get(artifact_key)
        if prior_path is not None and prior_path != relative_path:
            raise EvidenceQualificationError(
                "validated evidence artifact key collision"
            )
        expected_digest = freeze_manifest.artifact_digests.get(artifact_key)
        if expected_digest is None:
            raise EvidenceQualificationError(
                "v3 freeze manifest has missing validated evidence dependency digest: "
                f"{artifact_key}"
            )
        validated_keys[artifact_key] = relative_path
        authorized_validated_paths[registry_record.source_path] = (
            provenance_path,
            artifact_key,
            expected_digest,
        )

    for registry_record in registry.records:
        provenance_path, artifact_key, expected_digest = authorized_validated_paths[
            registry_record.source_path
        ]
        _, validated = _read_authorized_json_snapshot(
            provenance_path,
            "validated evidence artifact",
            expected_digest,
        )
        dependency_digests.append(
            FrozenDependencyDigest(
                artifact_key=artifact_key,
                path=registry_record.validated_path,
                sha256=expected_digest,
            )
        )
        extraction = validated.get("extraction")
        if not isinstance(extraction, dict):
            raise EvidenceQualificationError("validated artifact lacks extraction")
        if (
            extraction.get("source_file") != registry_record.source_path
            or extraction.get("sha256") != registry_record.sha256
            or validated.get("cache_key") != registry_record.cache_key
        ):
            raise EvidenceQualificationError(
                "validated artifact provenance does not match evidence registry"
            )
        raw_items = extraction.get("evidence_items")
        if not isinstance(raw_items, list) or len(raw_items) != (
            registry_record.evidence_item_count
        ):
            raise EvidenceQualificationError(
                "validated artifact evidence count does not match registry"
            )
        try:
            evidence_items = [EvidenceItem.model_validate(item) for item in raw_items]
        except ValidationError as exc:
            raise EvidenceQualificationError("invalid validated evidence item") from exc
        local_items: dict[str, EvidenceItem] = {}
        for item in evidence_items:
            if item.evidence_id in local_items or "::" in item.evidence_id:
                raise EvidenceQualificationError(
                    f"duplicate or invalid local evidence ID: {item.evidence_id}"
                )
            local_items[item.evidence_id] = item

        normalized_path = (
            root
            / "derived"
            / "principles"
            / "normalization"
            / registry_record.sha256[:12]
            / "validated.json"
        )
        normalized_relative_path = normalized_path.relative_to(root).as_posix()
        accepted_normalized = accepted_paths.get(normalized_relative_path)
        if accepted_normalized is None or accepted_normalized[0] != (
            "normalized_mechanism"
        ):
            raise EvidenceQualificationError(
                "normalization artifact is not accepted by the evidence import manifest"
            )
        normalized_envelope = accepted_normalized[2]
        if (
            normalized_envelope.get("source_file") != registry_record.source_path
            or normalized_envelope.get("source_sha256") != registry_record.sha256
        ):
            raise EvidenceQualificationError(
                "normalization provenance does not match evidence registry"
            )
        try:
            normalized = MechanismNormalizationPayload.model_validate(
                normalized_envelope.get("normalization")
            )
        except ValidationError as exc:
            raise EvidenceQualificationError(
                "invalid validated normalization artifact"
            ) from exc

        dimensions_by_local_id: dict[str, set[DimensionName]] = {}
        adverse_local_ids: set[str] = set()

        def add_dimensions(
            local_ids: Sequence[str], dimensions: Sequence[DimensionName]
        ) -> None:
            for local_id in local_ids:
                if local_id not in local_items:
                    raise EvidenceQualificationError(
                        f"normalization references unknown exact evidence ID: {local_id}"
                    )
                dimensions_by_local_id.setdefault(local_id, set()).update(dimensions)

        for mechanism in normalized.mechanism_evidence:
            if "::" in mechanism.mechanism_evidence_id:
                raise EvidenceQualificationError(
                    "normalized mechanism has an invalid local exact ID"
                )
            if mechanism.source_paper_id != registry_record.source_path:
                raise EvidenceQualificationError(
                    "normalized mechanism source does not match evidence registry"
                )
            mechanism_dimensions = _MECHANISM_DIMENSIONS[mechanism.evidence_type]
            add_dimensions(
                mechanism.source_evidence_ids,
                mechanism_dimensions,
            )
            pending.append(
                QualifiedEvidenceRecord(
                    evidence_id=(
                        f"{registry_record.sha256[:12]}::"
                        f"{mechanism.mechanism_evidence_id}"
                    ),
                    evidence_class="normalized_mechanism",
                    source_path=registry_record.source_path,
                    provenance_path=normalized_relative_path,
                    locator=(
                        f"{registry_record.source_path}:page-{mechanism.pdf_page}"
                        if mechanism.pdf_page is not None
                        else None
                    ),
                    evidence_level="model_physical_organic_inference",
                    admissible_dimensions=mechanism_dimensions,
                )
            )
            if mechanism.evidence_type == "failure_boundary":
                adverse_local_ids.update(mechanism.source_evidence_ids)
        for constraint in normalized.boundary_constraints:
            if "::" in constraint.constraint_id:
                raise EvidenceQualificationError(
                    "normalized constraint has an invalid local exact ID"
                )
            dimensions = _CONSTRAINT_DIMENSIONS[constraint.dimension]
            add_dimensions(constraint.supporting_evidence_ids, dimensions)
            add_dimensions(constraint.contradictory_evidence_ids, dimensions)
            pending.append(
                QualifiedEvidenceRecord(
                    evidence_id=(
                        f"{registry_record.sha256[:12]}::{constraint.constraint_id}"
                    ),
                    evidence_class="normalized_constraint",
                    source_path=registry_record.source_path,
                    provenance_path=normalized_relative_path,
                    locator=None,
                    evidence_level="model_physical_organic_inference",
                    admissible_dimensions=dimensions,
                )
            )
            if constraint.direction in {"inhibits", "incompatible"}:
                adverse_local_ids.update(constraint.supporting_evidence_ids)

        for local_id, dimensions in sorted(dimensions_by_local_id.items()):
            item = local_items[local_id]
            is_external = _external_qualification(item)
            dimensions.add("evidence_quality")
            locator = None
            if item.pdf_page is not None:
                locator = f"{registry_record.source_path}:page-{item.pdf_page}"
            elif item.source_span_ids:
                locator = (
                    f"{registry_record.source_path}:{item.source_span_ids[0]}"
                )
            pending.append(
                QualifiedEvidenceRecord(
                    evidence_id=f"{registry_record.sha256[:12]}::{local_id}",
                    evidence_class="external_literature",
                    source_path=registry_record.source_path,
                    provenance_path=registry_record.validated_path,
                    locator=locator,
                    evidence_level=(
                        "traceable_external_evidence"
                        if is_external
                        else "model_physical_organic_inference"
                    ),
                    admissible_dimensions=tuple(sorted(dimensions)),
                    hard_blocker_eligible=(
                        is_external and local_id in adverse_local_ids
                    ),
                )
            )

    records_by_id = {record.evidence_id: record for record in pending}
    if len(records_by_id) != len(pending):
        duplicates = sorted(
            evidence_id
            for evidence_id in records_by_id
            if sum(item.evidence_id == evidence_id for item in pending) > 1
        )
        raise EvidenceQualificationError(
            f"exact evidence ID collision across sources: {', '.join(duplicates)}"
        )
    transfer_dependencies: dict[str, tuple[str, ...]] = {}
    for accepted_path, (artifact_type, _, payload) in accepted_paths.items():
        if artifact_type != "transfer":
            continue
        rows = payload.get("assessments")
        if not isinstance(rows, list):
            raise EvidenceQualificationError(
                f"invalid accepted transfer artifact: {accepted_path}"
            )
        try:
            assessments = [
                TransferabilityAssessment.model_validate(row) for row in rows
            ]
        except ValidationError as exc:
            raise EvidenceQualificationError(
                f"invalid accepted transfer artifact: {accepted_path}"
            ) from exc
        for assessment in assessments:
            if (
                assessment.assessment_id in records_by_id
                or assessment.assessment_id in transfer_dependencies
                or assessment.source_paper_id is None
                or assessment.source_mechanism_id is None
            ):
                raise EvidenceQualificationError(
                    "transfer assessment has a duplicate ID or missing exact source"
                )
            source_mechanism = records_by_id.get(assessment.source_mechanism_id)
            if (
                source_mechanism is None
                or source_mechanism.evidence_class != "normalized_mechanism"
                or source_mechanism.source_path != assessment.source_paper_id
            ):
                raise EvidenceQualificationError(
                    "transfer assessment references an unaccepted normalized mechanism"
                )
            source_records: list[QualifiedEvidenceRecord] = []
            for evidence_id in assessment.source_evidence_ids:
                source_record = records_by_id.get(evidence_id)
                if (
                    source_record is None
                    or source_record.evidence_class != "external_literature"
                    or source_record.source_path != assessment.source_paper_id
                ):
                    raise EvidenceQualificationError(
                        "transfer assessment references evidence outside the accepted projection"
                    )
                source_records.append(source_record)
            for evidence_id in assessment.seed_feature_ids:
                seed_record = records_by_id.get(evidence_id)
                if seed_record is None or seed_record.evidence_class != "seed":
                    raise EvidenceQualificationError(
                        "transfer assessment references unknown exact seed evidence"
                    )
            for evidence_id in assessment.blocking_constraints:
                constraint_record = records_by_id.get(evidence_id)
                if (
                    constraint_record is None
                    or constraint_record.evidence_class != "normalized_constraint"
                    or constraint_record.source_path != assessment.source_paper_id
                ):
                    raise EvidenceQualificationError(
                        "transfer assessment references an unaccepted constraint"
                    )
            dependency_ids = tuple(
                dict.fromkeys(
                    (
                        assessment.source_mechanism_id,
                        *assessment.source_evidence_ids,
                        *assessment.seed_feature_ids,
                        *assessment.blocking_constraints,
                    )
                )
            )
            transfer_dimensions = tuple(
                sorted(
                    {
                        dimension
                        for record in (source_mechanism, *source_records)
                        for dimension in record.admissible_dimensions
                    }
                )
            )
            pending.append(
                QualifiedEvidenceRecord(
                    evidence_id=assessment.assessment_id,
                    evidence_class="transfer_assessment",
                    source_path=assessment.source_paper_id,
                    provenance_path=accepted_path,
                    locator=None,
                    evidence_level="model_physical_organic_inference",
                    admissible_dimensions=transfer_dimensions,
                )
            )
            transfer_dependencies[assessment.assessment_id] = dependency_ids
    records_by_id = {record.evidence_id: record for record in pending}
    if len(records_by_id) != len(pending):
        raise EvidenceQualificationError(
            "exact evidence ID collision across accepted evidence classes"
        )
    links_by_evidence: dict[str, dict[str, ReviewedPrincipleLink]] = {}
    for principle in frozen_principles.principles:
        resolved_principle_evidence: list[str] = []
        for evidence_id in principle.supporting_seed_evidence:
            record = records_by_id.get(evidence_id)
            if record is None or record.evidence_class != "seed":
                raise EvidenceQualificationError(
                    "canonical frozen Principle references unknown exact evidence ID "
                    "for seed evidence: "
                    f"{evidence_id}"
                )
            resolved_principle_evidence.append(evidence_id)
        for evidence_id in principle.supporting_transferred_evidence:
            record = records_by_id.get(evidence_id)
            if record is None or record.evidence_class != "transfer_assessment":
                raise EvidenceQualificationError(
                    "canonical frozen Principle references unknown exact evidence ID "
                    "for transfer evidence: "
                    f"{evidence_id}"
                )
            resolved_principle_evidence.extend(
                (evidence_id, *transfer_dependencies[evidence_id])
            )
        for evidence_id in principle.contradictory_evidence:
            record = records_by_id.get(evidence_id)
            if record is None:
                raise EvidenceQualificationError(
                    "canonical frozen Principle references unknown exact evidence ID: "
                    f"{evidence_id}"
                )
            resolved_principle_evidence.append(evidence_id)
            if record.evidence_class == "transfer_assessment":
                resolved_principle_evidence.extend(transfer_dependencies[evidence_id])
        for evidence_id in dict.fromkeys(resolved_principle_evidence):
            record = records_by_id[evidence_id]
            links_by_evidence.setdefault(evidence_id, {})[
                principle.principle_id
            ] = ReviewedPrincipleLink(
                principle_id=principle.principle_id,
                admissible_dimensions=record.admissible_dimensions,
            )
    bound_records = tuple(
        record.model_copy(
            update={
                "reviewed_principle_links": tuple(
                    sorted(
                        links_by_evidence.get(record.evidence_id, {}).values(),
                        key=lambda link: link.principle_id,
                    )
                )
            }
        )
        for record in pending
    )
    if not bound_records:
        raise EvidenceQualificationError(
            "trusted evidence qualification context contains no accepted evidence"
        )
    frozen_dependencies = tuple(
        sorted(
            dependency_digests,
            key=lambda dependency: (dependency.artifact_key, dependency.path),
        )
    )
    frozen_principle_ids = tuple(sorted(principle_ids))
    frozen_principle_digests = {
        principle.principle_id: _stable_digest(principle.model_dump(mode="json"))
        for principle in frozen_principles.principles
    }
    artifact_commitment = _stable_digest(
        [dependency.model_dump(mode="json") for dependency in frozen_dependencies]
    )
    return EvidenceQualificationContext(
        _builder_token=_CONTEXT_BUILDER_TOKEN,
        records=bound_records,
        content_digest=_context_content_digest(
            bound_records,
            frozen_dependencies,
            manifest_digest,
            evidence_import_raw_digest,
            rubric_raw_digest,
            rubric_canonical_digest,
            frozen_principle_ids,
            frozen_principle_digests,
        ),
        registry_commitment=registry_commitment,
        artifact_commitment=artifact_commitment,
        freeze_manifest_digest=manifest_digest,
        evidence_import_manifest_digest=evidence_import_raw_digest,
        rubric_raw_digest=rubric_raw_digest,
        rubric_canonical_digest=rubric_canonical_digest,
        frozen_dependencies=frozen_dependencies,
        frozen_principle_ids=frozen_principle_ids,
        frozen_principle_digests=frozen_principle_digests,
    )


def load_evaluation_rubric(path: Path | None = None) -> EvaluationRubric:
    """Load the preregistered YAML rubric, failing closed on invalid input."""

    source = path or DEFAULT_RUBRIC_PATH
    try:
        payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise EvaluationRubricError(f"cannot load evaluation rubric: {source}") from exc
    if not isinstance(payload, dict):
        raise EvaluationRubricError("evaluation rubric must be a YAML object")
    try:
        return EvaluationRubric.model_validate(payload)
    except ValueError as exc:
        raise EvaluationRubricError(str(exc)) from exc


def _require_context(
    context: EvidenceQualificationContext | None,
) -> EvidenceQualificationContext:
    if context is None:
        raise EvidenceQualificationError(
            "trusted evidence qualification context is required"
        )
    if not isinstance(context, EvidenceQualificationContext):
        raise EvidenceQualificationError(
            "trusted evidence qualification context requires builder attestation"
        )
    attestation = _CONTEXT_ATTESTATIONS.get(id(context))
    if (
        attestation is None
        or attestation[0]() is not context
        or attestation[1] != context.content_digest
        or attestation[2] != context.registry_commitment
        or attestation[3] != context.artifact_commitment
        or _context_content_digest(
            context.records,
            context.frozen_dependencies,
            context.freeze_manifest_digest,
            context.evidence_import_manifest_digest,
            context.rubric_raw_digest,
            context.rubric_canonical_digest,
            context.frozen_principle_ids,
            context.frozen_principle_digests,
        )
        != context.content_digest
        or _stable_digest(
            [
                dependency.model_dump(mode="json")
                for dependency in context.frozen_dependencies
            ]
        )
        != context.artifact_commitment
    ):
        raise EvidenceQualificationError(
            "trusted evidence qualification context failed builder attestation"
        )
    return context


def _verify_blocker(
    blocker: HardBlockerCandidate | QualifiedBlocker,
    context: EvidenceQualificationContext,
) -> QualifiedBlocker:
    if blocker.evidence_level != "traceable_external_evidence":
        raise HardBlockerError(
            "hard blocker requires qualified traceable external evidence"
        )
    records: list[QualifiedEvidenceRecord] = []
    try:
        for evidence_id in blocker.evidence_ids:
            records.append(
                context.require(
                    evidence_id,
                    blocker.dimension,
                    external=True,
                    hard_blocker=True,
                    reviewed_principle=True,
                )
            )
        for evidence_id in blocker.counterevidence_ids:
            context.require(evidence_id, blocker.dimension)
    except EvidenceQualificationError as exc:
        raise HardBlockerError(
            f"hard blocker exact evidence ID is not qualified: {exc}"
        ) from exc
    exact_sources = {record.source_path for record in records}
    if exact_sources != set(blocker.source_paths):
        raise HardBlockerError(
            "hard blocker exact evidence source does not match trusted context"
        )
    principle_ids = tuple(
        sorted(
            {
                link.principle_id
                for record in records
                for link in record.reviewed_principle_links
                if blocker.dimension in link.admissible_dimensions
            }
        )
    )
    return QualifiedBlocker(
        blocker_id=blocker.blocker_id,
        dimension=blocker.dimension,
        statement=blocker.statement,
        evidence_ids=blocker.evidence_ids,
        counterevidence_ids=blocker.counterevidence_ids,
        source_paths=tuple(sorted(exact_sources)),
        reviewed_principle_ids=principle_ids,
    )


def qualify_hard_blockers(
    candidates: Sequence[HardBlockerCandidate],
    context: EvidenceQualificationContext | None,
) -> tuple[QualifiedBlocker, ...]:
    """Qualify proposed blockers against exact trusted evidence identities."""

    trusted = _require_context(context)
    qualified: list[QualifiedBlocker] = []
    seen_ids: set[str] = set()
    for raw_candidate in candidates:
        candidate = HardBlockerCandidate.model_validate(raw_candidate)
        if candidate.blocker_id in seen_ids:
            raise HardBlockerError(f"duplicate hard blocker id: {candidate.blocker_id}")
        seen_ids.add(candidate.blocker_id)
        qualified.append(_verify_blocker(candidate, trusted))
    return tuple(qualified)


def _validated_judgments(
    judgments: Sequence[DimensionJudgment],
    context: EvidenceQualificationContext,
) -> tuple[
    tuple[DimensionJudgment, ...],
    tuple[str, ...],
    Mapping[str, str],
    tuple[EvidenceContribution, ...],
    Mapping[str, tuple[ReviewedPrincipleLink, ...]],
    tuple[DimensionPrincipleLink, ...],
]:
    validated = tuple(DimensionJudgment.model_validate(item) for item in judgments)
    dimensions = tuple(judgment.dimension for judgment in validated)
    if len(validated) != 7 or set(dimensions) != set(DIMENSIONS):
        raise ValueError("family evaluation requires exactly seven unique judgments")
    principle_ids: set[str] = set()
    evidence_source_paths: dict[str, str] = {}
    evidence_principle_links: dict[str, tuple[ReviewedPrincipleLink, ...]] = {}
    dimension_principle_links: set[DimensionPrincipleLink] = set()
    contributions: list[EvidenceContribution] = []
    for judgment in validated:
        if judgment.state != "unknown" and not judgment.evidence_ids:
            raise ValueError(
                f"non-unknown judgment requires evidence: {judgment.dimension}"
            )
        for evidence_id in judgment.evidence_ids:
            record = context.require(
                evidence_id,
                judgment.dimension,
                external=judgment.dimension == "evidence_quality",
                reviewed_principle=True,
            )
            qualified_links = tuple(
                link
                for link in record.reviewed_principle_links
                if judgment.dimension in link.admissible_dimensions
            )
            principle_ids.update(link.principle_id for link in qualified_links)
            dimension_principle_links.update(
                DimensionPrincipleLink(
                    evidence_id=evidence_id,
                    dimension=judgment.dimension,
                    principle_id=link.principle_id,
                )
                for link in qualified_links
            )
            evidence_principle_links[evidence_id] = record.reviewed_principle_links
            if record.evidence_class != "seed":
                evidence_source_paths[evidence_id] = record.source_path
            contributions.append(
                EvidenceContribution(
                    dimension=judgment.dimension,
                    evidence_id=evidence_id,
                    source_paper=(
                        None
                        if record.evidence_class == "seed"
                        else record.source_path
                    ),
                    direction=(
                        "adverse"
                        if judgment.state == "contradiction"
                        else "positive"
                    ),
                    state=judgment.state,
                    evidence_class=record.evidence_class,
                    evidence_level=record.evidence_level,
                    is_external=(
                        record.evidence_level == "traceable_external_evidence"
                    ),
                    quality_eligible=(
                        record.evidence_level == "traceable_external_evidence"
                    ),
                    is_counterevidence=False,
                )
            )
        for evidence_id in judgment.counterevidence_ids:
            record = context.require(evidence_id, judgment.dimension)
            qualified_links = tuple(
                link
                for link in record.reviewed_principle_links
                if judgment.dimension in link.admissible_dimensions
            )
            principle_ids.update(link.principle_id for link in qualified_links)
            dimension_principle_links.update(
                DimensionPrincipleLink(
                    evidence_id=evidence_id,
                    dimension=judgment.dimension,
                    principle_id=link.principle_id,
                )
                for link in qualified_links
            )
            evidence_principle_links[evidence_id] = record.reviewed_principle_links
            if record.evidence_class != "seed":
                evidence_source_paths[evidence_id] = record.source_path
            contributions.append(
                EvidenceContribution(
                    dimension=judgment.dimension,
                    evidence_id=evidence_id,
                    source_paper=(
                        None
                        if record.evidence_class == "seed"
                        else record.source_path
                    ),
                    direction="adverse",
                    state="contradiction",
                    evidence_class=record.evidence_class,
                    evidence_level=record.evidence_level,
                    is_external=(
                        record.evidence_level == "traceable_external_evidence"
                    ),
                    quality_eligible=(
                        record.evidence_level == "traceable_external_evidence"
                    ),
                    is_counterevidence=True,
                )
            )
    return (
        validated,
        tuple(sorted(principle_ids)),
        dict(sorted(evidence_source_paths.items())),
        tuple(contributions),
        dict(sorted(evidence_principle_links.items())),
        tuple(
            sorted(
                dimension_principle_links,
                key=lambda item: (item.evidence_id, item.dimension, item.principle_id),
            )
        ),
    )


def _observed_mean(
    dimensions: Sequence[DimensionName],
    scores: Mapping[DimensionName, int | None],
) -> float | None:
    numeric = [scores[dimension] for dimension in dimensions]
    observed = [score for score in numeric if score is not None]
    if not observed:
        return None
    return sum(observed) / len(observed)


def derive_family_metrics(
    states: Mapping[DimensionName, JudgmentState],
    blocker_ids: Sequence[str],
    rubric: EvaluationRubric,
) -> DerivedFamilyMetrics:
    """Derive all deterministic Task 8 metrics from a complete state mapping."""

    if set(states) != set(DIMENSIONS):
        raise ValueError("family metrics require exactly seven dimension states")
    scores = {
        dimension: rubric.state_scores[states[dimension]]
        for dimension in DIMENSIONS
    }
    critical_unknowns = tuple(
        dimension
        for dimension in rubric.critical_dimensions
        if scores[dimension] is None
    )
    compatibility = (
        None
        if blocker_ids
        else _observed_mean(rubric.core_dimensions, scores)
    )
    evidence_confidence = scores[rubric.evidence_confidence_dimension]
    failure_risk = scores[rubric.failure_risk_dimension]
    uncertainty_points = sum(
        4
        if states[dimension] == "unknown"
        else 2
        if states[dimension] == "conditional_support"
        else 0
        for dimension in DIMENSIONS
    )
    uncertainty_burden = uncertainty_points / len(DIMENSIONS)
    if blocker_ids:
        region: PriorityRegion = "excluded"
    elif critical_unknowns:
        region = "unknown"
    elif any(
        value is None
        for value in (compatibility, evidence_confidence, failure_risk)
    ):
        region = "boundary"
    else:
        region = "boundary"
        for name in ("priority_a", "priority_b", "priority_c"):
            threshold = rubric.priority_regions[name]
            if threshold is not None and (
                compatibility >= threshold.min_compatibility
                and evidence_confidence >= threshold.min_evidence_confidence
                and uncertainty_burden <= threshold.max_uncertainty_burden
                and failure_risk <= threshold.max_failure_risk
            ):
                region = name  # type: ignore[assignment]
                break
    return DerivedFamilyMetrics(
        dimension_scores=scores,
        compatibility_index=compatibility,
        evidence_confidence=evidence_confidence,
        uncertainty_burden=uncertainty_burden,
        failure_risk=failure_risk,
        critical_unknowns=critical_unknowns,
        priority_region=region,
    )


def assign_priority_region(
    evaluation: ScoredFamilyEvaluation, rubric: EvaluationRubric
) -> PriorityRegion:
    """Apply non-compensable gates, then preregistered region thresholds."""

    if evaluation.qualified_blocker_ids:
        return "excluded"
    if evaluation.critical_unknowns:
        return "unknown"
    metrics = (
        evaluation.compatibility_index,
        evaluation.evidence_confidence,
        evaluation.failure_risk,
    )
    if any(value is None for value in metrics):
        return "boundary"
    for name in ("priority_a", "priority_b", "priority_c"):
        threshold = rubric.priority_regions[name]
        if threshold is None:
            continue
        if (
            evaluation.compatibility_index >= threshold.min_compatibility
            and evaluation.evidence_confidence
            >= threshold.min_evidence_confidence
            and evaluation.uncertainty_burden
            <= threshold.max_uncertainty_burden
            and evaluation.failure_risk <= threshold.max_failure_risk
        ):
            return name  # type: ignore[return-value]
    return "boundary"


def score_family(
    judgments: Sequence[DimensionJudgment],
    blockers: Sequence[QualifiedBlocker],
    rubric: EvaluationRubric,
    context: EvidenceQualificationContext | None,
    *,
    family_id: str,
) -> ScoredFamilyEvaluation:
    """Reverify evidence and derive separate metrics from seven judgments."""

    trusted = _require_context(context)
    try:
        passed_rubric_digest = evaluation_rubric_digest(rubric)
    except ValidationError as exc:
        raise EvidenceQualificationError(
            "family evaluation rubric does not match the attested snapshot"
        ) from exc
    if passed_rubric_digest != trusted.rubric_canonical_digest:
        raise EvidenceQualificationError(
            "family evaluation rubric does not match the attested snapshot"
        )
    (
        validated,
        judgment_principle_ids,
        evidence_source_paths,
        evidence_contributions,
        evidence_principle_links,
        dimension_principle_links,
    ) = _validated_judgments(judgments, trusted)
    qualified = tuple(
        _verify_blocker(QualifiedBlocker.model_validate(item), trusted)
        for item in blockers
    )
    for blocker in qualified:
        for evidence_id in (*blocker.evidence_ids, *blocker.counterevidence_ids):
            record = trusted.require(evidence_id, blocker.dimension)
            evidence_principle_links[evidence_id] = record.reviewed_principle_links
            dimension_principle_links += tuple(
                DimensionPrincipleLink(
                    evidence_id=evidence_id,
                    dimension=blocker.dimension,
                    principle_id=link.principle_id,
                )
                for link in record.reviewed_principle_links
                if blocker.dimension in link.admissible_dimensions
            )
            if record.evidence_class != "seed":
                evidence_source_paths[evidence_id] = record.source_path
    by_dimension = {judgment.dimension: judgment for judgment in validated}
    scores = {
        dimension: rubric.state_scores[by_dimension[dimension].state]
        for dimension in DIMENSIONS
    }
    critical_unknowns = tuple(
        dimension
        for dimension in rubric.critical_dimensions
        if scores[dimension] is None
    )
    uncertainty_points = sum(
        4
        if judgment.state == "unknown"
        else 2
        if judgment.state == "conditional_support"
        else 0
        for judgment in validated
    )
    blocker_ids = tuple(blocker.blocker_id for blocker in qualified)
    referenced_evidence_ids = {
        evidence_id
        for judgment in validated
        for evidence_id in (*judgment.evidence_ids, *judgment.counterevidence_ids)
    }.union(
        evidence_id
        for blocker in qualified
        for evidence_id in (*blocker.evidence_ids, *blocker.counterevidence_ids)
    )
    context_records = {record.evidence_id: record for record in trusted.records}
    compatibility = (
        None
        if blocker_ids
        else _observed_mean(rubric.core_dimensions, scores)
    )
    evidence_confidence = scores[rubric.evidence_confidence_dimension]
    failure_risk = scores[rubric.failure_risk_dimension]
    dimension_principle_links = tuple(
        sorted(
            set(dimension_principle_links),
            key=lambda item: (item.evidence_id, item.dimension, item.principle_id),
        )
    )
    reviewed_principle_ids = tuple(
        sorted({link.principle_id for link in dimension_principle_links})
    )
    scored_data = dict(
        family_id=family_id,
        judgments=validated,
        dimension_scores=scores,
        compatibility_index=compatibility,
        evidence_confidence=evidence_confidence,
        uncertainty_burden=uncertainty_points / len(DIMENSIONS),
        failure_risk=failure_risk,
        critical_unknowns=critical_unknowns,
        qualified_blocker_ids=blocker_ids,
        qualified_blockers=qualified,
        reviewed_principle_ids=reviewed_principle_ids,
        reviewed_principle_digests={
            principle_id: trusted.frozen_principle_digests[principle_id]
            for principle_id in reviewed_principle_ids
        },
        evidence_principle_links=evidence_principle_links,
        dimension_principle_links=dimension_principle_links,
        evidence_record_digests={
            evidence_id: _stable_digest(
                context_records[evidence_id].model_dump(mode="json")
            )
            for evidence_id in sorted(referenced_evidence_ids)
        },
        evidence_source_paths=evidence_source_paths,
        evidence_contributions=evidence_contributions,
        rubric_digest=passed_rubric_digest,
        context_digest=trusted.content_digest,
        priority_region="boundary",
    )
    evaluation = _build_scored_evaluation(attest=False, **scored_data)
    return _build_scored_evaluation(
        **{
            **scored_data,
            "priority_region": assign_priority_region(evaluation, rubric),
        }
    )


def to_canonical_family_evaluation(
    evaluation: ScoredFamilyEvaluation,
) -> CanonicalFamilyEvaluation:
    """Project deterministic scoring details onto the canonical v3 contract."""

    return CanonicalFamilyEvaluation(
        family_id=evaluation.family_id,
        judgments=evaluation.judgments,
        critical_unknowns=evaluation.critical_unknowns,
        qualified_blocker_ids=evaluation.qualified_blocker_ids,
    )

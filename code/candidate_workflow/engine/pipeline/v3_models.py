"""Reaction-agnostic strict contracts for the v3 discovery workflow."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from types import MappingProxyType
from typing import Literal

from pydantic import Field, ValidationError, field_serializer, model_validator

from pipeline.principle_models import FrozenStrictModel


EvidenceLevel = Literal[
    "traceable_external_evidence",
    "model_physical_organic_inference",
    "unknown",
]
DimensionName = Literal[
    "elementary_step_match",
    "electrophile_state_match",
    "reactive_state_accessibility",
    "condition_compatibility",
    "target_selectivity",
    "competing_pathway_risk",
    "evidence_quality",
]
JudgmentState = Literal["support", "conditional_support", "contradiction", "unknown"]
PriorityRegion = Literal[
    "priority_a", "priority_b", "priority_c", "boundary", "excluded", "unknown"
]

DIMENSIONS: tuple[DimensionName, ...] = (
    "elementary_step_match",
    "electrophile_state_match",
    "reactive_state_accessibility",
    "condition_compatibility",
    "target_selectivity",
    "competing_pathway_risk",
    "evidence_quality",
)
FORBIDDEN_BRIEF_KEYS = frozenset(
    {"nucleophile_ontology", "required_superclasses", "mapping_terms"}
)


class V3BriefError(ValueError):
    """Raised when a v3 exploration brief includes legacy family ontology."""


class RoleSpecV3(FrozenStrictModel):
    role: Literal["electrophile", "nucleophile", "catalyst", "condition"]
    label: str = Field(min_length=1)
    seed_reaction_id: str | None = None


class TargetTransformationV3(FrozenStrictModel):
    new_bond: str = Field(min_length=1)
    retained_features: tuple[str, ...] = Field(min_length=1)
    removed_features: tuple[str, ...] = ()
    selectivity_constraints: tuple[str, ...] = ()


class ExplorationBriefV3(FrozenStrictModel):
    version: Literal["3.0"]
    study_id: str = Field(min_length=1)
    fixed_role: RoleSpecV3
    variable_role: RoleSpecV3
    target_transformation: TargetTransformationV3
    allowed_evidence_levels: tuple[EvidenceLevel, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_fixed_seed_axis(self) -> "ExplorationBriefV3":
        if self.fixed_role.role != "electrophile":
            raise ValueError("v3 fixed role must be electrophile")
        if self.fixed_role.seed_reaction_id != "SR001":
            raise ValueError("v3 fixed role must reference Seed reaction SR001")
        if self.variable_role.role != "nucleophile":
            raise ValueError("v3 variable role must be nucleophile")
        return self


class MechanismCoordinate(FrozenStrictModel):
    coordinate_id: str = Field(min_length=1)
    nucleophilic_center: str = Field(min_length=1)
    reactive_state: str = Field(min_length=1)
    bond_forming_mode: str = Field(min_length=1)
    activation_mode: str = Field(min_length=1)
    attack_topology: str = Field(min_length=1)
    target_termination_compatibility: JudgmentState
    evidence_ids: tuple[str, ...] = ()
    evidence_level: EvidenceLevel
    rationale: str = Field(min_length=1)


class FamilyDefinition(FrozenStrictModel):
    family_id: str = Field(min_length=1)
    nucleophilic_center: str = Field(min_length=1)
    reactive_state: str = Field(min_length=1)
    bond_forming_mode: str = Field(min_length=1)
    activation_mode: str = Field(min_length=1)
    critical_conditions: tuple[str, ...] = Field(min_length=1)
    dominant_failure_modes: tuple[str, ...] = Field(min_length=1)


class FamilyProposalV3(FrozenStrictModel):
    proposal_id: str = Field(min_length=1)
    family: FamilyDefinition
    channel: Literal["seed_derived", "literature_derived", "model_hypothesis"]
    lane_id: str = Field(min_length=1)
    round_id: str = Field(min_length=1)
    evidence_ids: tuple[str, ...] = ()
    evidence_level: EvidenceLevel
    rationale: str = Field(min_length=1)
    unresolved_questions: tuple[str, ...] = ()


class DimensionJudgment(FrozenStrictModel):
    dimension: DimensionName
    state: JudgmentState
    evidence_ids: tuple[str, ...]
    rationale: str = Field(min_length=1)
    counterevidence_ids: tuple[str, ...]
    unresolved_questions: tuple[str, ...]

    @model_validator(mode="after")
    def preserve_unknown(self) -> "DimensionJudgment":
        if self.state == "unknown" and self.evidence_ids:
            raise ValueError("unknown dimension cannot claim supporting evidence")
        return self


class FamilyEvaluation(FrozenStrictModel):
    family_id: str = Field(min_length=1)
    judgments: tuple[DimensionJudgment, ...]
    critical_unknowns: tuple[str, ...]
    qualified_blocker_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def require_complete_dimension_set(self) -> "FamilyEvaluation":
        dimensions = {judgment.dimension for judgment in self.judgments}
        if len(self.judgments) != len(DIMENSIONS) or dimensions != set(DIMENSIONS):
            raise ValueError(
                "FamilyEvaluation requires exactly one judgment per dimension"
            )
        return self


class RankingRecord(FrozenStrictModel):
    family_id: str = Field(min_length=1)
    priority_region: PriorityRegion
    primary_rank: int | None = Field(default=None, ge=1)
    equal_weight_rank: int | None = Field(default=None, ge=1)
    rank_interval: tuple[int, int] | None = None
    pareto_optimal: bool | None = None
    weight_sensitive: bool | None = None
    rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def prevent_non_testable_numeric_rank(self) -> "RankingRecord":
        if self.priority_region in {"boundary", "excluded", "unknown"} and any(
            value is not None
            for value in (self.primary_rank, self.equal_weight_rank, self.rank_interval)
        ):
            raise ValueError("non-testable priority region cannot have a numeric rank")
        return self


class SaturationAudit(FrozenStrictModel):
    completed_rounds: int = Field(ge=1)
    consecutive_low_new_family_rounds: int = Field(ge=0)
    new_family_rate: float = Field(ge=0, le=1)
    lane_converged: bool
    coordinate_combinations_stable: bool
    uncovered_coordinate_dispositions: dict[str, Literal[
        "chemically_inapplicable", "unsupported", "unknown"
    ]]
    additional_evidence_batch_no_material_change: bool
    operationally_saturated: bool
    rationale: str = Field(min_length=1)


class FreezeManifestV3(FrozenStrictModel):
    freeze_version: Literal["Freeze 1", "Freeze 2", "Freeze 3"]
    created_at: str = Field(min_length=1)
    brief_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_digests: Mapping[str, str] = Field(min_length=1)
    hidden_registry_commitment: str = Field(pattern=r"^[0-9a-f]{64}$")
    software_version: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_artifact_digests(self) -> "FreezeManifestV3":
        if any(
            len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest)
            for digest in self.artifact_digests.values()
        ):
            raise ValueError("artifact digests must be SHA-256 hex strings")
        object.__setattr__(
            self,
            "artifact_digests",
            MappingProxyType(dict(sorted(self.artifact_digests.items()))),
        )
        return self

    @field_serializer("artifact_digests")
    def serialize_artifact_digests(self, artifact_digests: Mapping[str, str]) -> dict[str, str]:
        return dict(artifact_digests)


def _contains_forbidden_brief_key(value: object) -> bool:
    if isinstance(value, Mapping):
        return any(
            key in FORBIDDEN_BRIEF_KEYS or _contains_forbidden_brief_key(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_forbidden_brief_key(item) for item in value)
    return False


def load_v3_brief(config: Mapping[str, object]) -> ExplorationBriefV3:
    """Load a v3 brief while rejecting all legacy named-family ontology input."""

    if _contains_forbidden_brief_key(config):
        raise V3BriefError("v3 brief cannot contain named family ontology")
    raw_brief = config.get("exploration_brief")
    if not isinstance(raw_brief, Mapping):
        raise V3BriefError("workflow config requires exploration_brief")
    try:
        return ExplorationBriefV3.model_validate(raw_brief)
    except ValidationError as exc:
        raise V3BriefError(str(exc)) from exc


def v3_brief_digest(brief: ExplorationBriefV3) -> str:
    """Return a stable v3 brief digest for run and cache isolation."""

    encoded = json.dumps(
        brief.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

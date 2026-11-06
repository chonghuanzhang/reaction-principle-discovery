"""Strict contracts for evidence-grounded Reaction Principle discovery."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pipeline.models import EvidenceLabel, ReviewerStatus


Confidence = Literal["low", "medium", "high", "unknown"]
TransferStatus = Literal["transferable", "conditional", "non_transferable", "unknown"]
BoundaryClassification = Literal[
    "explore",
    "conditional",
    "deprioritize",
    "exclude",
    "insufficient_evidence",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FrozenStrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EvidenceRef(FrozenStrictModel):
    evidence_id: str = Field(min_length=1)
    source_type: Literal["seed", "literature", "project_experiment"]
    source_id: str = Field(min_length=1)
    evidence_label: EvidenceLabel
    quotation: str | None
    locator: str | None

    @model_validator(mode="after")
    def require_grounding(self) -> "EvidenceRef":
        if self.source_type in {"seed", "literature"} and not self.locator:
            raise ValueError("source-grounded evidence requires a locator")
        if self.evidence_label in {"LITERATURE FACT", "EXPERIMENTAL FACT"} and not self.quotation:
            raise ValueError("fact evidence requires a quotation or record excerpt")
        return self


class SeedEvidence(FrozenStrictModel):
    evidence: EvidenceRef
    claim: str = Field(min_length=1)
    evidence_type: str = Field(min_length=1)
    reviewer_status: ReviewerStatus = "pending"


class SeedMechanism(StrictModel):
    seed_reaction_id: str = Field(min_length=1)
    reaction_center: list[str]
    electrophile_state: list[str]
    nucleophile_state: list[str]
    bond_changes: list[str]
    reactive_intermediates: list[str]
    elementary_steps: list[str]
    electronic_requirements: list[str]
    steric_requirements: list[str]
    catalyst_roles: list[str]
    condition_window: list[str]
    successful_scope: list[str]
    failed_scope: list[str]
    competing_pathways: list[str]
    evidence_ids: list[str] = Field(min_length=1)
    confidence: Confidence


class SeedPrinciple(FrozenStrictModel):
    seed_principle_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    claim: str = Field(min_length=1)
    reaction_center: tuple[str, ...] = Field(min_length=1)
    reactive_intermediates: tuple[str, ...]
    electronic_requirements: tuple[str, ...]
    nucleophile_requirements: tuple[str, ...]
    catalyst_roles: tuple[str, ...]
    condition_window: tuple[str, ...]
    failure_boundaries: tuple[str, ...]
    supporting_seed_evidence: tuple[str, ...] = Field(min_length=1)
    confidence: Confidence
    uncertainty: tuple[str, ...]


class MechanismEvidence(FrozenStrictModel):
    mechanism_evidence_id: str = Field(min_length=1)
    source_paper_id: str = Field(min_length=1)
    source_evidence_ids: tuple[str, ...] = Field(min_length=1)
    evidence_type: Literal[
        "elementary_step",
        "intermediate",
        "electronic_requirement",
        "nucleophile_requirement",
        "catalyst_role",
        "condition_effect",
        "failure_boundary",
    ]
    elementary_step: str
    starting_state: str
    ending_state: str
    bond_changes: tuple[str, ...]
    catalyst_role: str
    nucleophile_requirements: tuple[str, ...]
    electrophile_requirements: tuple[str, ...]
    condition_requirements: tuple[str, ...]
    observed_outcome: str
    failure_mode: str | None
    evidence_label: EvidenceLabel
    evidence_strength: Literal["direct", "indirect", "hypothesis", "inference", "unknown"]
    quotation: str | None
    pdf_page: int | None = Field(ge=1)
    confidence: Confidence


class BoundaryConstraint(FrozenStrictModel):
    constraint_id: str = Field(min_length=1)
    dimension: Literal["electronic", "steric", "catalyst", "condition", "stability"]
    applies_to: tuple[str, ...] = Field(min_length=1)
    direction: Literal["promotes", "inhibits", "threshold", "incompatible"]
    statement: str = Field(min_length=1)
    quantitative_range: str | None
    supporting_evidence_ids: tuple[str, ...] = Field(min_length=1)
    contradictory_evidence_ids: tuple[str, ...]
    confidence: Confidence


class SourceRevisitRequest(FrozenStrictModel):
    request_id: str = Field(min_length=1)
    source_paper_id: str = Field(min_length=1)
    pdf_pages: tuple[int, ...] = Field(min_length=1)
    reason: Literal[
        "critical_visual",
        "missing_mechanistic_field",
        "blocking_contradiction",
    ]
    question: str = Field(min_length=1)
    status: Literal["pending", "resolved", "not_assessable"]


class TransferabilityAssessment(FrozenStrictModel):
    assessment_id: str = Field(min_length=1)
    source_paper_id: str | None = None
    source_mechanism_id: str | None = None
    source_evidence_ids: tuple[str, ...] = Field(min_length=1)
    seed_feature_ids: tuple[str, ...] = Field(min_length=1)
    shared_elementary_step: str
    matched_requirements: tuple[str, ...]
    mismatched_requirements: tuple[str, ...]
    blocking_constraints: tuple[str, ...]
    transfer_status: TransferStatus
    transferable_claim: str
    conditions: tuple[str, ...]
    uncertainty: tuple[str, ...]
    falsifying_test: str = Field(min_length=1)
    score_components: dict[str, int | str]


class PrincipleProvenance(FrozenStrictModel):
    run_id: str = Field(min_length=1)
    model: str | None = None
    prompt_version: str | None = None
    seed_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    transfer_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class ReactionPrinciple(StrictModel):
    principle_id: str = Field(min_length=1)
    principle_layer: Literal["seed_specific", "transferable_super"] = "seed_specific"
    title: str = Field(min_length=1)
    status: Literal["proposed", "accepted", "revised", "rejected"]
    claim: str = Field(min_length=1)
    mechanistic_basis: list[str] = Field(min_length=1)
    applicable_electrophile_families: list[str]
    applicable_nucleophile_families: list[str]
    applicable_nucleophile_superclasses: list[str] = Field(default_factory=list)
    required_reactive_form: str
    catalyst_requirements: list[str]
    condition_window: list[str]
    structural_promoters: list[str]
    structural_inhibitors: list[str]
    supporting_seed_evidence: list[str]
    supporting_transferred_evidence: list[str]
    contradictory_evidence: list[str]
    known_exceptions: list[str]
    predicted_failure_modes: list[str]
    confidence: Confidence
    experimental_consequence: str = Field(min_length=1)
    falsifying_experiment: str = Field(min_length=1)
    review_status: ReviewerStatus
    provenance: PrincipleProvenance
    freeze_version: str | None

    @model_validator(mode="after")
    def require_seed_anchor(self) -> "ReactionPrinciple":
        if not self.supporting_seed_evidence:
            raise ValueError("Reaction Principle requires at least one seed evidence anchor")
        return self


class FrozenReactionPrincipleSet(FrozenStrictModel):
    freeze_version: str = Field(min_length=1)
    created_at: str = Field(min_length=1)
    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    scoring_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    hidden_answers_revealed: Literal[False] = False
    principles: tuple[ReactionPrinciple, ...] = Field(min_length=1)


class FamilyBoundaryPrediction(FrozenStrictModel):
    family_id: str = Field(min_length=1)
    family_type: Literal["electrophile", "nucleophile"]
    classification: BoundaryClassification
    compatible_principle_ids: tuple[str, ...]
    violated_principle_ids: tuple[str, ...]
    required_conditions: tuple[str, ...]
    dominant_risks: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    score_components: dict[str, int | str]
    total_score: int
    uncertainty: tuple[str, ...]
    superclass_id: str | None = None
    representative_nucleophile: str | None = None
    reactive_form: str | None = None
    fixed_electrophile_id: str | None = None
    catalyst_requirement: Literal["required", "optional", "incompatible", "unknown"] | None = None
    condition_window: dict[str, str | list[str] | None] | None = None
    diagnostic_status: Literal["proposed", "not_executable"] | None = None
    no_experiment_rationale: str | None = None


class ExperimentCandidate(FrozenStrictModel):
    experiment_id: str = Field(min_length=1)
    family_id: str = Field(min_length=1)
    electrophile: str
    nucleophile: str
    catalyst: str
    ligand: str
    base: str
    solvent: str
    temperature: str
    time: str
    atmosphere: str
    predicted_outcome: BoundaryClassification
    predicted_failure_modes: tuple[str, ...]
    family_priority: int
    experiment_priority: int
    supporting_principle_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    minimal_diagnostic_plan: tuple[str, ...]
    score_components: dict[str, int]
    total_score: int
    uncertainty: tuple[str, ...]
    freeze_status: Literal["provisional", "frozen"] = "provisional"
    freeze_version: str | None = Field(default=None, min_length=1)
    principle_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    scoring_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    candidate_list_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def require_frozen_provenance(self) -> "ExperimentCandidate":
        provenance = (
            self.freeze_version,
            self.principle_digest,
            self.scoring_digest,
            self.candidate_list_digest,
        )
        if self.freeze_status == "frozen":
            if not all(provenance):
                raise ValueError("frozen candidate requires complete freeze provenance")
        elif any(provenance):
            raise ValueError("provisional candidate cannot carry freeze provenance")
        return self


class ExperimentalOutcome(FrozenStrictModel):
    experiment_id: str = Field(min_length=1)
    status: Literal[
        "confirmed_success",
        "analytical_success",
        "signal_only",
        "confirmed_failure",
        "inconclusive",
        "off_target",
    ]
    isolated_product: bool
    characterization_complete: bool
    analytical_yield: float | None = Field(default=None, ge=0, le=100)
    isolated_yield: float | None = Field(default=None, ge=0, le=100)
    detected_target_signal: bool
    observed_failure_modes: tuple[str, ...] = ()
    notes: str

    @model_validator(mode="after")
    def enforce_status_evidence(self) -> "ExperimentalOutcome":
        if self.status == "confirmed_success":
            if not self.isolated_product:
                raise ValueError("confirmed_success requires an isolated target product")
            if not self.characterization_complete:
                raise ValueError("confirmed_success requires sufficient characterization")
        return self

    @property
    def counts_as_confirmed_success(self) -> bool:
        return self.status == "confirmed_success"

"""Typed data contracts shared by the literature pipeline."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SourceRecord(BaseModel):
    """Stable metadata for one immutable project input."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_path: str = Field(min_length=1)
    tier: str = Field(min_length=1)
    byte_size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    page_count: int | None = Field(default=None, ge=1)
    parser_version: str = Field(min_length=1)


class PageRecord(BaseModel):
    """Page-preserving PDF text and conservative review signals."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    pdf_page: int = Field(ge=1)
    text: str
    character_count: int = Field(ge=0)
    replacement_character_count: int = Field(ge=0)
    visual_review_reasons: tuple[str, ...] = ()


class CandidateRecord(BaseModel):
    """Locally derived information used to rank a pilot candidate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_path: str = Field(min_length=1)
    tier: str = Field(pattern=r"^tier_[1-4]$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    page_count: int = Field(ge=1)
    searchable_character_count: int = Field(ge=0)
    searchable_text: str
    visual_page_count: int = Field(ge=0)


class ScoredCandidate(BaseModel):
    """Candidate plus a complete, inspectable score explanation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_path: str
    tier: str
    sha256: str
    page_count: int
    total_score: int
    score_components: dict[str, int]
    matched_keywords: tuple[str, ...]
    selection_reason: str


class DuplicateExclusion(BaseModel):
    """Audit record for a byte-identical candidate excluded from ranking."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    excluded_path: str
    retained_path: str
    sha256: str
    reason: str = "identical_sha256"


class SelectionAudit(BaseModel):
    """Complete deterministic outcome of pilot candidate selection."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    selected: tuple[ScoredCandidate, ...]
    ranked_candidates: tuple[ScoredCandidate, ...]
    duplicate_exclusions: tuple[DuplicateExclusion, ...]
    weights: dict[str, object]


class PageChunk(BaseModel):
    """A bounded collection of complete PDF pages."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_id: str = Field(pattern=r"^chunk-[0-9]{3}$")
    pages: tuple[PageRecord, ...] = Field(min_length=1)


EvidenceLabel = Literal[
    "EXPERIMENTAL FACT",
    "KNOWN RETROSPECTIVE ANSWER",
    "LITERATURE FACT",
    "AUTHOR HYPOTHESIS",
    "MODEL INFERENCE",
    "WORKING HYPOTHESIS",
    "UNKNOWN",
]
ReviewerStatus = Literal["pending", "accepted", "revised", "rejected", "not_assessable"]


class Bibliography(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    authors: list[str]
    journal: str
    year: int | None
    doi: str | None


class ReactionSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reaction_class: str
    electrophile: str
    nucleophile_or_partner: str
    nu_atom: str
    nu_subclass: str
    new_bond: str
    catalyst: str
    ligand: str
    base: str
    solvent: str
    temperature: str
    product_type: str
    selectivity: str
    proposed_intermediate: str
    activation_mode: str
    successful_scope: list[str]
    failed_scope: list[str]
    side_reactions: list[str]
    relevance_to_seed_reaction: str
    transferability_assessment: str


class EvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    claim: str
    evidence_label: EvidenceLabel
    quotation: str | None
    source_span_ids: list[str]
    pdf_page: int | None = Field(ge=1)
    additional_pdf_pages: list[int]
    section_context: str
    attribution: Literal[
        "author_observation",
        "author_hypothesis",
        "model_inference",
        "source_metadata",
    ]
    evidence_strength: Literal["direct", "indirect", "hypothesis", "inference", "unknown"]
    visual_review_reference: str | None
    reviewer_status: ReviewerStatus


class ExtractionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paper_id: str
    source_file: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bibliography: Bibliography
    primary_tier: Literal["tier_1", "tier_2", "tier_3", "tier_4"]
    secondary_tiers: list[Literal["tier_1", "tier_2", "tier_3", "tier_4"]]
    evidence_types: list[str]
    reaction_summary: ReactionSummary
    evidence_items: list[EvidenceItem] = Field(max_length=12)
    uncertainties: list[str]
    contradictions: list[str]
    visual_review_pages: list[int]
    review_status: ReviewerStatus


class ValidationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    message: str
    evidence_id: str | None = None


class ValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    is_valid: bool
    errors: tuple[ValidationIssue, ...]
    warnings: tuple[ValidationIssue, ...]

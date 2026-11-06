"""Structured model proposals for Reaction Principles and chemical space."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from pipeline.api_client import ApiResult
from pipeline.candidate_ranking import rank_experiment_candidates
from pipeline.chemical_space import classify_family
from pipeline.evidence_registry import _atomic_json
from pipeline.exploration_brief import ExplorationBrief
from pipeline.principle_induction import PrincipleInductionError, validate_principle_candidate
from pipeline.principle_models import (
    ExperimentCandidate,
    FamilyBoundaryPrediction,
    ReactionPrinciple,
    SeedMechanism,
    TransferabilityAssessment,
)


class StructuredClient(Protocol):
    def create_structured(
        self, model: str, input_text: str, schema: dict, schema_name: str
    ) -> ApiResult: ...


class PrincipleProposalPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    principles: list[ReactionPrinciple] = Field(min_length=1)


class ComponentJudgment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str = Field(min_length=1)
    value: int | None
    rationale: str = Field(min_length=1)
    evidence_ids: tuple[str, ...]

    @model_validator(mode="after")
    def require_evidence_for_scored_value(self) -> "ComponentJudgment":
        if self.value is not None and not self.evidence_ids:
            raise ValueError("non-null component judgment requires evidence")
        return self


class CompatibilityComponentJudgment(ComponentJudgment):
    name: Literal[
        "seed_match",
        "elementary_step",
        "electronic",
        "reactive_form",
        "catalyst",
        "condition",
        "evidence",
    ]


class RiskComponentJudgment(ComponentJudgment):
    name: Literal[
        "contradiction",
        "poisoning",
        "decomposition",
        "over_defluorination",
        "instability",
    ]


class ConditionWindow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    catalyst: str | None = None
    ligand: str | None = None
    base: str | None = None
    solvent: str | None = None
    temperature: str | None = None
    time: str | None = None
    atmosphere: str | None = None
    water_activity: str | None = None
    additives: tuple[str, ...] = ()


class FamilyProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    family_id: str = Field(min_length=1)
    family_type: Literal["electrophile", "nucleophile"]
    superclass_id: str | None = None
    representative_nucleophile: str | None = None
    reactive_form: str | None = None
    fixed_electrophile_id: str | None = None
    catalyst_requirement: Literal["required", "optional", "incompatible", "unknown"] | None = None
    condition_window: ConditionWindow | None = None
    diagnostic_status: Literal["proposed", "not_executable"] | None = None
    no_experiment_rationale: str | None = None
    compatibility_components: tuple[CompatibilityComponentJudgment, ...]
    risk_components: tuple[RiskComponentJudgment, ...]
    compatible_principle_ids: tuple[str, ...]
    violated_principle_ids: tuple[str, ...]
    required_conditions: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...]
    hard_blockers: tuple[str, ...]
    uncertainty: tuple[str, ...]


class ExperimentProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
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
    bonus_components: tuple[CompatibilityComponentJudgment, ...]
    risk_components: tuple[RiskComponentJudgment, ...]
    predicted_failure_modes: tuple[str, ...]
    supporting_principle_ids: tuple[str, ...] = Field(min_length=1)
    evidence_ids: tuple[str, ...] = Field(min_length=1)
    minimal_diagnostic_plan: tuple[str, ...] = Field(min_length=1)
    uncertainty: tuple[str, ...]


class ChemicalSpaceProposalPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    families: list[FamilyProposal] = Field(min_length=1)
    experiments: list[ExperimentProposal] = Field(min_length=1)


class PrincipleProposalResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: Literal["validated", "reused"]
    cache_key: str
    principles: tuple[ReactionPrinciple, ...]
    usage: dict[str, int | None]


class ChemicalSpaceProposalResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: Literal["validated", "reused"]
    cache_key: str
    families: tuple[FamilyBoundaryPrediction, ...]
    candidates: tuple[ExperimentCandidate, ...]
    usage: dict[str, int | None]
    coverage_audit: "CoverageAudit | None" = None


class ModelProposalError(RuntimeError):
    """Raised when a model proposal is ungrounded or bypasses deterministic gates."""


PRINCIPLE_EVIDENCE_STRATA = (
    "positive",
    "conditional",
    "explicit_negative",
    "contradictory",
    "unknown",
)
CHEMICAL_SPACE_CLASSIFICATION_VERSION = "3.0"


class PrincipleEvidenceSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    seed_evidence_ids: tuple[str, ...] = Field(min_length=1)
    assessment_ids: tuple[str, ...]
    strata: dict[str, tuple[str, ...]]
    paper_counts: dict[str, int]
    elementary_step_counts: dict[str, int]
    superclass_counts: dict[str, int] = Field(default_factory=dict)
    max_assessments: int = Field(ge=1)
    max_per_paper: int = Field(ge=1)


class ChemicalSpaceEvidenceSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    anchor_assessment_ids: tuple[str, ...]
    assessment_ids: tuple[str, ...]
    strata: dict[str, tuple[str, ...]]
    paper_counts: dict[str, int]
    elementary_step_counts: dict[str, int]
    max_assessments: int = Field(ge=1)
    max_per_paper: int = Field(ge=1)


class RoleAwareEvidenceIndex(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    superclass_assessment_ids: dict[str, tuple[str, ...]]
    unmapped_assessment_ids: tuple[str, ...]
    mapped_count: int = Field(ge=0)
    unmapped_count: int = Field(ge=0)


class CoverageAudit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ontology_version: str = Field(min_length=1)
    required_superclass_ids: tuple[str, ...]
    covered_superclass_ids: tuple[str, ...]
    missing_superclass_ids: tuple[str, ...]
    extra_superclass_ids: tuple[str, ...]
    complete: bool


def validate_nucleophile_coverage(
    families: Iterable[FamilyProposal], brief: ExplorationBrief
) -> CoverageAudit:
    """Require an explicit family judgment for every configured superclass."""

    family_rows = tuple(families)
    required = {row.superclass_id for row in brief.required_superclasses}
    covered = {row.superclass_id for row in family_rows if row.superclass_id}
    missing = tuple(sorted(required - covered))
    audit = CoverageAudit(
        ontology_version=brief.ontology_version,
        required_superclass_ids=tuple(sorted(required)),
        covered_superclass_ids=tuple(sorted(covered & required)),
        missing_superclass_ids=missing,
        extra_superclass_ids=tuple(sorted(covered - required)),
        complete=not missing,
    )
    if missing:
        raise ModelProposalError(
            "missing nucleophile superclasses: " + ", ".join(missing)
        )
    return audit


def index_assessments_by_nucleophile_role(
    assessments: Mapping[str, TransferabilityAssessment],
    brief: ExplorationBrief,
) -> RoleAwareEvidenceIndex:
    """Index existing assessments by configured role terms without creating evidence."""

    buckets: dict[str, list[str]] = {
        item.superclass_id: [] for item in brief.required_superclasses
    }
    unmapped: list[str] = []
    for assessment_id in sorted(assessments):
        assessment = assessments[assessment_id]
        searchable = " ".join(
            [assessment.shared_elementary_step, assessment.transferable_claim]
            + list(assessment.matched_requirements)
            + list(assessment.mismatched_requirements)
            + list(assessment.conditions)
        ).casefold()
        matches = [
            item.superclass_id
            for item in brief.required_superclasses
            if any(term.casefold() in searchable for term in item.mapping_terms)
        ]
        if not matches:
            unmapped.append(assessment_id)
            continue
        for superclass_id in matches:
            buckets[superclass_id].append(assessment_id)
    return RoleAwareEvidenceIndex(
        superclass_assessment_ids={
            key: tuple(value) for key, value in sorted(buckets.items())
        },
        unmapped_assessment_ids=tuple(unmapped),
        mapped_count=len(assessments) - len(unmapped),
        unmapped_count=len(unmapped),
    )


def _evidence_stratum(assessment: TransferabilityAssessment) -> str:
    if assessment.transfer_status == "transferable":
        return "positive"
    if assessment.transfer_status == "conditional":
        return "conditional"
    if assessment.transfer_status == "unknown":
        return "unknown"
    if assessment.blocking_constraints:
        return "explicit_negative"
    return "contradictory"


def select_principle_evidence(
    seed: SeedMechanism,
    assessments: dict[str, TransferabilityAssessment],
    *,
    max_assessments: int,
    max_per_paper: int,
    exploration_brief: ExplorationBrief | None = None,
) -> PrincipleEvidenceSelection:
    """Select a bounded, paper-diverse set spanning all available evidence strata."""

    if max_assessments < 1 or max_per_paper < 1:
        raise ModelProposalError("Principle evidence limits must be positive")
    grouped: dict[str, list[TransferabilityAssessment]] = {
        name: [] for name in PRINCIPLE_EVIDENCE_STRATA
    }
    for assessment_id, assessment in assessments.items():
        if assessment_id != assessment.assessment_id:
            raise ModelProposalError(
                f"assessment mapping key does not match payload: {assessment_id}"
            )
        grouped[_evidence_stratum(assessment)].append(assessment)
    for rows in grouped.values():
        rows.sort(key=lambda item: item.assessment_id)

    selected: list[TransferabilityAssessment] = []
    selected_ids: set[str] = set()
    paper_counts: dict[str, int] = {}
    step_counts: dict[str, int] = {}
    selected_by_stratum: dict[str, list[str]] = {
        name: [] for name in PRINCIPLE_EVIDENCE_STRATA
    }

    def paper_key(item: TransferabilityAssessment) -> str:
        return item.source_paper_id or f"unscoped:{item.assessment_id}"

    def add_item(item: TransferabilityAssessment, stratum: str) -> None:
        selected.append(item)
        selected_ids.add(item.assessment_id)
        selected_by_stratum[stratum].append(item.assessment_id)
        paper = paper_key(item)
        paper_counts[paper] = paper_counts.get(paper, 0) + 1
        step = item.shared_elementary_step
        step_counts[step] = step_counts.get(step, 0) + 1

    def take_one(stratum: str) -> bool:
        eligible = [
            item
            for item in grouped[stratum]
            if item.assessment_id not in selected_ids
            and paper_counts.get(paper_key(item), 0) < max_per_paper
        ]
        if not eligible:
            return False
        item = min(
            eligible,
            key=lambda row: (
                step_counts.get(row.shared_elementary_step, 0),
                paper_counts.get(paper_key(row), 0),
                row.assessment_id,
            ),
        )
        add_item(item, stratum)
        return True

    for stratum in PRINCIPLE_EVIDENCE_STRATA:
        if len(selected) >= max_assessments:
            break
        take_one(stratum)
    full_role_index = (
        index_assessments_by_nucleophile_role(assessments, exploration_brief)
        if exploration_brief is not None
        else None
    )
    if full_role_index is not None:
        for superclass_id in sorted(full_role_index.superclass_assessment_ids):
            if len(selected) >= max_assessments:
                break
            for assessment_id in full_role_index.superclass_assessment_ids[
                superclass_id
            ]:
                item = assessments[assessment_id]
                if (
                    assessment_id not in selected_ids
                    and paper_counts.get(paper_key(item), 0) < max_per_paper
                ):
                    add_item(item, _evidence_stratum(item))
                    break
    while len(selected) < max_assessments:
        progress = False
        for stratum in PRINCIPLE_EVIDENCE_STRATA:
            if len(selected) >= max_assessments:
                break
            progress = take_one(stratum) or progress
        if not progress:
            break

    selected_role_index = (
        index_assessments_by_nucleophile_role(
            {item.assessment_id: item for item in selected}, exploration_brief
        )
        if exploration_brief is not None
        else None
    )
    return PrincipleEvidenceSelection(
        seed_evidence_ids=tuple(seed.evidence_ids),
        assessment_ids=tuple(item.assessment_id for item in selected),
        strata={name: tuple(selected_by_stratum[name]) for name in PRINCIPLE_EVIDENCE_STRATA},
        paper_counts=dict(sorted(paper_counts.items())),
        elementary_step_counts=dict(sorted(step_counts.items())),
        superclass_counts=(
            {
                key: len(value)
                for key, value in selected_role_index.superclass_assessment_ids.items()
            }
            if selected_role_index is not None
            else {}
        ),
        max_assessments=max_assessments,
        max_per_paper=max_per_paper,
    )


def select_chemical_space_evidence(
    principles: list[ReactionPrinciple],
    assessments: dict[str, TransferabilityAssessment],
    *,
    max_assessments: int,
    max_per_paper: int,
) -> ChemicalSpaceEvidenceSelection:
    """Retain reviewed anchors, then add bounded and diverse boundary evidence."""

    if max_assessments < 1 or max_per_paper < 1:
        raise ModelProposalError("Chemical-space evidence limits must be positive")
    anchor_ids = sorted(
        {
            assessment_id
            for principle in principles
            for assessment_id in (
                *principle.supporting_transferred_evidence,
                *principle.contradictory_evidence,
            )
        }
    )
    unknown_anchors = sorted(set(anchor_ids) - set(assessments))
    if unknown_anchors:
        raise ModelProposalError(
            "reviewed Principle references unknown assessment: "
            + ", ".join(unknown_anchors)
        )
    if len(anchor_ids) > max_assessments:
        raise ModelProposalError(
            "reviewed Principle anchors exceed chemical-space evidence budget"
        )

    grouped: dict[str, list[TransferabilityAssessment]] = {
        name: [] for name in PRINCIPLE_EVIDENCE_STRATA
    }
    for assessment_id, assessment in assessments.items():
        if assessment_id != assessment.assessment_id:
            raise ModelProposalError(
                f"assessment mapping key does not match payload: {assessment_id}"
            )
        grouped[_evidence_stratum(assessment)].append(assessment)
    for rows in grouped.values():
        rows.sort(key=lambda item: item.assessment_id)

    selected_ids = set(anchor_ids)
    selected = [assessments[assessment_id] for assessment_id in anchor_ids]
    paper_counts: dict[str, int] = {}
    step_counts: dict[str, int] = {}
    selected_by_stratum: dict[str, list[str]] = {
        name: [] for name in PRINCIPLE_EVIDENCE_STRATA
    }

    def paper_key(item: TransferabilityAssessment) -> str:
        return item.source_paper_id or f"unscoped:{item.assessment_id}"

    def record(item: TransferabilityAssessment) -> None:
        paper = paper_key(item)
        paper_counts[paper] = paper_counts.get(paper, 0) + 1
        step_counts[item.shared_elementary_step] = (
            step_counts.get(item.shared_elementary_step, 0) + 1
        )
        selected_by_stratum[_evidence_stratum(item)].append(item.assessment_id)

    for item in selected:
        record(item)

    def take_one(stratum: str) -> bool:
        eligible = [
            item
            for item in grouped[stratum]
            if item.assessment_id not in selected_ids
            and paper_counts.get(paper_key(item), 0) < max_per_paper
        ]
        if not eligible:
            return False
        item = min(
            eligible,
            key=lambda row: (
                step_counts.get(row.shared_elementary_step, 0),
                paper_counts.get(paper_key(row), 0),
                row.assessment_id,
            ),
        )
        selected.append(item)
        selected_ids.add(item.assessment_id)
        record(item)
        return True

    for stratum in PRINCIPLE_EVIDENCE_STRATA:
        if len(selected) >= max_assessments:
            break
        if not selected_by_stratum[stratum]:
            take_one(stratum)
    while len(selected) < max_assessments:
        progress = False
        for stratum in PRINCIPLE_EVIDENCE_STRATA:
            if len(selected) >= max_assessments:
                break
            progress = take_one(stratum) or progress
        if not progress:
            break

    return ChemicalSpaceEvidenceSelection(
        anchor_assessment_ids=tuple(anchor_ids),
        assessment_ids=tuple(item.assessment_id for item in selected),
        strata={
            name: tuple(selected_by_stratum[name])
            for name in PRINCIPLE_EVIDENCE_STRATA
        },
        paper_counts=dict(sorted(paper_counts.items())),
        elementary_step_counts=dict(sorted(step_counts.items())),
        max_assessments=max_assessments,
        max_per_paper=max_per_paper,
    )


def _strict_schema(model: type[BaseModel]) -> dict:
    schema = model.model_json_schema()

    def require(node: object) -> None:
        if isinstance(node, dict):
            properties = node.get("properties")
            if isinstance(properties, dict):
                node["required"] = list(properties)
                node["additionalProperties"] = False
            for value in node.values():
                require(value)
        elif isinstance(node, list):
            for value in node:
                require(value)

    require(schema)
    return schema


def _digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def strict_model_schema(model: type[BaseModel]) -> dict:
    """Expose the established strict Responses schema builder to v3 stages."""

    return _strict_schema(model)


def stable_model_digest(value: object) -> str:
    """Expose the established canonical JSON digest used by model caches."""

    return _digest(value)


def _proposal_input(
    prompt_text: str,
    seed: SeedMechanism,
    assessments: dict[str, TransferabilityAssessment],
    selection: PrincipleEvidenceSelection,
    exploration_brief: ExplorationBrief | None = None,
    role_aware_evidence_index: RoleAwareEvidenceIndex | None = None,
) -> str:
    payload = {
        "seed_mechanism": seed.model_dump(mode="json"),
        "transferability_assessments": [
            assessments[key].model_dump(mode="json") for key in sorted(assessments)
        ],
        "evidence_selection": selection.model_dump(mode="json"),
    }
    if exploration_brief is not None and role_aware_evidence_index is not None:
        payload["exploration_brief"] = exploration_brief.model_dump(mode="json")
        payload["role_aware_evidence_index"] = role_aware_evidence_index.model_dump(
            mode="json"
        )
    layer_contract = (
        " For this v2 run, propose both principle_layer='seed_specific' and "
        "principle_layer='transferable_super'. Keep organoboron transmetalation "
        "specific to the Seed layer; the super layer may transfer only supported "
        "local elementary steps and must preserve mechanistic mismatches. Across "
        "the transferable_super proposals, cover every nucleophile superclass that "
        "has selected evidence in role_aware_evidence_index. Record the exact "
        "configured superclass IDs in applicable_nucleophile_superclasses; do not "
        "omit a mapped role merely because the Seed instance is organoboron."
        if exploration_brief is not None
        else ""
    )
    return (
        f"{prompt_text.strip()}\n\n"
        "Propose falsifiable Reaction Principles only. Every Principle must retain "
        "a Seed evidence anchor and at least one transferable or conditional "
        "assessment ID. contradictory_evidence may be empty; otherwise it must "
        "contain only supplied assessment IDs. Set status='proposed', "
        "review_status='pending', and "
        f"freeze_version=null. Do not accept or freeze your own proposal.{layer_contract}\n\n"
        f"BEGIN_GROUNDED_TRANSFER_BUNDLE\n{json.dumps(payload, ensure_ascii=False, sort_keys=True)}\n"
        "END_GROUNDED_TRANSFER_BUNDLE\n"
    )


def propose_reaction_principles(
    seed: SeedMechanism,
    assessments: dict[str, TransferabilityAssessment],
    client: StructuredClient,
    config: dict,
    cache_root: Path,
    *,
    exploration_brief: ExplorationBrief | None = None,
) -> PrincipleProposalResult:
    """Request model proposals, then enforce evidence and review-state gates."""

    selection = select_principle_evidence(
        seed,
        assessments,
        max_assessments=int(config.get("max_assessments", 80)),
        max_per_paper=int(config.get("max_per_paper", 3)),
        exploration_brief=exploration_brief,
    )
    selected_assessments = {
        assessment_id: assessments[assessment_id]
        for assessment_id in selection.assessment_ids
    }
    role_index = (
        index_assessments_by_nucleophile_role(selected_assessments, exploration_brief)
        if exploration_brief is not None
        else None
    )
    key_payload = {
        "seed": seed.model_dump(mode="json"),
        "assessments": {
            key: value.model_dump(mode="json")
            for key, value in selected_assessments.items()
        },
        "selection": selection.model_dump(mode="json"),
        "config": config,
        "schema": _strict_schema(PrincipleProposalPayload),
    }
    if exploration_brief is not None and role_index is not None:
        key_payload["exploration_brief"] = exploration_brief.model_dump(mode="json")
        key_payload["role_aware_evidence_index"] = role_index.model_dump(mode="json")
    key = _digest(key_payload)
    root = cache_root.resolve() / key
    cached = _read_principle_cache(root / "validated.json", key)
    if cached is not None:
        return cached
    api_result = client.create_structured(
        str(config.get("model", "")),
        _proposal_input(
            str(config.get("prompt_text", "")),
            seed,
            selected_assessments,
            selection,
            exploration_brief,
            role_index,
        ),
        _strict_schema(PrincipleProposalPayload),
        "reaction_principle_proposals",
    )
    _atomic_json(
        root / "raw.json",
        {
            "cache_key": key,
            "api": {
                "response_id": api_result.response_id,
                "returned_model": api_result.returned_model,
                "status": api_result.status,
                "usage": asdict(api_result.usage),
            },
            "model_output": api_result.parsed_output,
        },
    )
    try:
        payload = PrincipleProposalPayload.model_validate(api_result.parsed_output)
        validated: list[ReactionPrinciple] = []
        for principle in payload.principles:
            if principle.status != "proposed" or principle.review_status != "pending":
                raise ModelProposalError("model Principle proposal cannot self-accept")
            validated.append(
                validate_principle_candidate(
                    principle,
                    known_seed_evidence_ids=set(seed.evidence_ids),
                    transfer_assessments=selected_assessments,
                )
            )
        if exploration_brief is not None:
            layers = {item.principle_layer for item in validated}
            required_layers = {"seed_specific", "transferable_super"}
            if not required_layers <= layers:
                missing_layers = sorted(required_layers - layers)
                raise ModelProposalError(
                    "v2 Principle proposal missing layers: " + ", ".join(missing_layers)
                )
            mapped_superclasses = {
                superclass_id
                for superclass_id, assessment_ids in role_index.superclass_assessment_ids.items()
                if assessment_ids
            }
            claimed_superclasses = {
                superclass_id
                for item in validated
                if item.principle_layer == "transferable_super"
                for superclass_id in item.applicable_nucleophile_superclasses
            }
            missing_superclasses = sorted(
                mapped_superclasses - claimed_superclasses
            )
            if missing_superclasses:
                raise ModelProposalError(
                    "v2 super-principles omit selected nucleophile superclasses: "
                    + ", ".join(missing_superclasses)
                )
    except (ValidationError, PrincipleInductionError) as exc:
        raise ModelProposalError(str(exc)) from exc
    usage = asdict(api_result.usage)
    _atomic_json(
        root / "validated.json",
        {
            "cache_key": key,
            "principles": [item.model_dump(mode="json") for item in validated],
            "usage": usage,
        },
    )
    return PrincipleProposalResult(
        status="validated", cache_key=key, principles=tuple(validated), usage=usage
    )


def _read_principle_cache(path: Path, key: str) -> PrincipleProposalResult | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("cache_key") != key:
            return None
        principles = tuple(
            ReactionPrinciple.model_validate(row) for row in value.get("principles", [])
        )
    except (OSError, json.JSONDecodeError, ValidationError, AttributeError):
        return None
    return PrincipleProposalResult(
        status="reused",
        cache_key=key,
        principles=principles,
        usage={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
    )


def _space_input(
    prompt_text: str,
    principles: list[ReactionPrinciple],
    assessments: dict[str, TransferabilityAssessment],
    selection: ChemicalSpaceEvidenceSelection,
    rubric: dict,
    exploration_brief: ExplorationBrief | None = None,
) -> str:
    allowed_evidence_ids = set(assessments)
    allowed_hard_blockers: set[str] = set()
    for assessment in assessments.values():
        allowed_evidence_ids.update(assessment.source_evidence_ids)
        allowed_evidence_ids.update(assessment.seed_feature_ids)
        allowed_hard_blockers.update(assessment.blocking_constraints)
    payload = {
        "reviewed_principles": [item.model_dump(mode="json") for item in principles],
        "transferability_assessments": [
            assessments[key].model_dump(mode="json") for key in sorted(assessments)
        ],
        "evidence_selection": selection.model_dump(mode="json"),
        "citation_contract": {
            "allowed_evidence_ids": sorted(allowed_evidence_ids),
            "allowed_hard_blocker_constraint_ids": sorted(allowed_hard_blockers),
            "required_compatibility_component_names": sorted(
                rubric.get("weights", {})
            ),
            "required_risk_component_names": sorted(
                rubric.get("risk_penalties", {})
            ),
        },
        "scoring_rubric": rubric,
    }
    coverage_contract = ""
    if exploration_brief is not None:
        payload["exploration_brief"] = exploration_brief.model_dump(mode="json")
        coverage_contract = (
            " This is Stage 1: keep fixed_electrophile_id equal to the supplied "
            "Seed reaction ID, propose only nucleophile families, and return at "
            "least one explicit family judgment for every required superclass. "
            "Return no family outside the supplied required_superclasses. "
            "Organoboron is an observed Seed instance, not the definition of the "
            "nucleophile role. Supply representative_nucleophile, reactive_form, "
            "catalyst_requirement, condition_window, and diagnostic_status. Use "
            "diagnostic_status='not_executable' only with a specific rationale."
        )
    return (
        f"{prompt_text.strip()}\n\n"
        "Propose family-level component judgments and concrete experiment tuples. "
        "Return every configured compatibility and risk component exactly once; "
        "use null, never zero, when evidence is unknown. Hard blockers must be "
        "explicit. Component, family, and experiment evidence_ids must cite supplied "
        "assessment, source, or Seed evidence IDs. Principle IDs are not evidence IDs; "
        "use them only in compatible_principle_ids, violated_principle_ids, or "
        "supporting_principle_ids. experiment.family_id must exactly equal one proposed "
        "family_id; choose the single family boundary that the experiment primarily "
        "diagnoses and do not concatenate electrophile and nucleophile family IDs. "
        "Every hard_blockers item must exactly equal one supplied "
        "allowed_hard_blocker_constraint_id; inferred concerns belong in risks or "
        "uncertainty, and an unsupported hard_blockers list must be empty. "
        f"Do not assign final classifications, scores, ranks, or freeze state.{coverage_contract}\n\n"
        f"BEGIN_REVIEWED_PRINCIPLE_BUNDLE\n{json.dumps(payload, ensure_ascii=False, sort_keys=True)}\n"
        "END_REVIEWED_PRINCIPLE_BUNDLE\n"
    )


def _select_batch_context(
    principles: list[ReactionPrinciple],
    selected_assessments: dict[str, TransferabilityAssessment],
    selection: ChemicalSpaceEvidenceSelection,
    exploration_brief: ExplorationBrief,
    superclass_ids: tuple[str, ...],
    *,
    max_assessments: int,
    max_per_paper: int,
) -> tuple[
    list[ReactionPrinciple],
    dict[str, TransferabilityAssessment],
    ChemicalSpaceEvidenceSelection,
]:
    """Scope one model call to Principles and evidence relevant to its roles."""

    requested = set(superclass_ids)
    batch_principles = [
        principle
        for principle in principles
        if not principle.applicable_nucleophile_superclasses
        or requested.intersection(principle.applicable_nucleophile_superclasses)
    ]
    if not batch_principles:
        raise ModelProposalError(
            "chemical-space batch has no applicable reviewed Principle"
        )
    role_index = index_assessments_by_nucleophile_role(
        selected_assessments, exploration_brief
    )
    assessment_ids = {
        assessment_id
        for superclass_id in superclass_ids
        for assessment_id in role_index.superclass_assessment_ids.get(
            superclass_id, ()
        )
    }
    assessment_ids.update(
        assessment_id
        for principle in batch_principles
        for assessment_id in (
            *principle.supporting_transferred_evidence,
            *principle.contradictory_evidence,
        )
    )
    candidate_assessments = {
        assessment_id: selected_assessments[assessment_id]
        for assessment_id in sorted(assessment_ids)
        if assessment_id in selected_assessments
    }
    anchor_count = len(
        {
            assessment_id
            for principle in batch_principles
            for assessment_id in (
                *principle.supporting_transferred_evidence,
                *principle.contradictory_evidence,
            )
        }
    )
    batch_selection = select_chemical_space_evidence(
        batch_principles,
        candidate_assessments,
        max_assessments=max(max_assessments, anchor_count),
        max_per_paper=max_per_paper,
    )
    batch_assessments = {
        assessment_id: candidate_assessments[assessment_id]
        for assessment_id in batch_selection.assessment_ids
    }
    return batch_principles, batch_assessments, batch_selection


def propose_chemical_space(
    principles: list[ReactionPrinciple],
    assessments: dict[str, TransferabilityAssessment],
    client: StructuredClient,
    config: dict,
    rubric: dict,
    cache_root: Path,
    *,
    exploration_brief: ExplorationBrief | None = None,
) -> ChemicalSpaceProposalResult:
    """Request chemical-space judgments and deterministically classify/rank them."""

    if not principles or any(
        item.status not in {"accepted", "revised"}
        or item.review_status not in {"accepted", "revised"}
        for item in principles
    ):
        raise ModelProposalError("chemical-space proposal requires reviewed Principles")
    selection = select_chemical_space_evidence(
        principles,
        assessments,
        max_assessments=int(config.get("max_assessments", 120)),
        max_per_paper=int(config.get("max_per_paper", 3)),
    )
    selected_assessments = {
        assessment_id: assessments[assessment_id]
        for assessment_id in selection.assessment_ids
    }
    key_payload = {
            "principles": [item.model_dump(mode="json") for item in principles],
            "assessments": {
                name: item.model_dump(mode="json")
                for name, item in selected_assessments.items()
            },
            "selection": selection.model_dump(mode="json"),
            "rubric": rubric,
            "config": config,
            "schema": _strict_schema(ChemicalSpaceProposalPayload),
        }
    if exploration_brief is not None:
        key_payload["exploration_brief"] = exploration_brief.model_dump(mode="json")
    key = _digest(key_payload)
    root = cache_root.resolve() / key
    cached = _read_space_cache(root / "validated.json", key)
    if cached is not None:
        return cached
    raw_payload = _read_space_raw(root / "raw.json", key)
    if raw_payload is not None:
        try:
            families, candidates, coverage_audit = _validate_and_rank_space(
                raw_payload,
                principles,
                selected_assessments,
                rubric,
                exploration_brief=exploration_brief,
            )
        except ModelProposalError:
            pass
        else:
            _write_space_cache(
                root / "validated.json",
                key,
                families,
                candidates,
                {},
                coverage_audit,
            )
            return ChemicalSpaceProposalResult(
                status="reused",
                cache_key=key,
                families=families,
                candidates=candidates,
                usage={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
                coverage_audit=coverage_audit,
            )
    batch_size = int(config.get("superclass_batch_size", 0))
    use_batches = (
        exploration_brief is not None
        and batch_size > 0
        and batch_size < len(exploration_brief.required_superclasses)
    )
    usage: dict[str, int | None]
    if use_batches:
        merged_families: list[FamilyProposal] = []
        merged_experiments: list[ExperimentProposal] = []
        usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        batch_records: list[dict[str, object]] = []
        model_called = False
        required = exploration_brief.required_superclasses
        for start in range(0, len(required), batch_size):
            batch_number = start // batch_size + 1
            batch_rows = required[start : start + batch_size]
            batch_ids = tuple(row.superclass_id for row in batch_rows)
            batch_key = _digest({"parent_cache_key": key, "superclass_ids": batch_ids})
            batch_path = root / "batches" / f"batch-{batch_number:02d}" / "raw.json"
            batch_payload = _read_space_raw(batch_path, batch_key)
            scoped_brief = exploration_brief.model_copy(
                update={"required_superclasses": batch_rows}
            )
            batch_principles, batch_assessments, batch_selection = (
                _select_batch_context(
                    principles,
                    selected_assessments,
                    selection,
                    exploration_brief,
                    batch_ids,
                    max_assessments=int(
                        config.get("max_assessments_per_batch", 32)
                    ),
                    max_per_paper=int(config.get("max_per_paper", 3)),
                )
            )
            if batch_payload is not None:
                try:
                    _validate_and_rank_space(
                        batch_payload,
                        batch_principles,
                        batch_assessments,
                        rubric,
                        exploration_brief=scoped_brief,
                    )
                    returned_ids = {row.superclass_id for row in batch_payload.families}
                    if returned_ids != set(batch_ids):
                        raise ModelProposalError(
                            "chemical-space batch returned superclasses outside its scope"
                        )
                except ModelProposalError:
                    batch_payload = None
            if batch_payload is None:
                api_result = client.create_structured(
                    str(config.get("model", "")),
                    _space_input(
                        str(config.get("prompt_text", "")),
                        batch_principles,
                        batch_assessments,
                        batch_selection,
                        rubric,
                        scoped_brief,
                    ),
                    _strict_schema(ChemicalSpaceProposalPayload),
                    f"chemical_space_batch_{batch_number:02d}",
                )
                model_called = True
                try:
                    batch_payload = ChemicalSpaceProposalPayload.model_validate(
                        api_result.parsed_output
                    )
                    _validate_and_rank_space(
                        batch_payload,
                        batch_principles,
                        batch_assessments,
                        rubric,
                        exploration_brief=scoped_brief,
                    )
                except ValidationError as exc:
                    raise ModelProposalError(
                        f"invalid chemical-space batch schema: {exc}"
                    ) from exc
                returned_ids = {row.superclass_id for row in batch_payload.families}
                if returned_ids != set(batch_ids):
                    raise ModelProposalError(
                        "chemical-space batch returned superclasses outside its scope"
                    )
                batch_usage = asdict(api_result.usage)
                for name in usage:
                    value = batch_usage.get(name)
                    if value is None or usage[name] is None:
                        usage[name] = None
                    else:
                        usage[name] = int(usage[name]) + int(value)
                _atomic_json(
                    batch_path,
                    {
                        "cache_key": batch_key,
                        "api": {
                            "response_id": api_result.response_id,
                            "returned_model": api_result.returned_model,
                            "status": api_result.status,
                            "usage": batch_usage,
                        },
                        "superclass_ids": batch_ids,
                        "model_output": batch_payload.model_dump(mode="json"),
                    },
                )
            merged_families.extend(batch_payload.families)
            merged_experiments.extend(batch_payload.experiments)
            batch_records.append(
                {
                    "batch_number": batch_number,
                    "superclass_ids": batch_ids,
                    "principle_ids": [
                        row.principle_id for row in batch_principles
                    ],
                    "assessment_count": len(batch_assessments),
                }
            )
        payload = ChemicalSpaceProposalPayload(
            families=merged_families,
            experiments=merged_experiments,
        )
        _atomic_json(
            root / "raw.json",
            {
                "cache_key": key,
                "api": {
                    "status": "completed",
                    "usage": usage,
                    "batches": batch_records,
                },
                "model_output": payload.model_dump(mode="json"),
            },
        )
        proposal_status = "validated" if model_called else "reused"
    else:
        api_result = client.create_structured(
            str(config.get("model", "")),
            _space_input(
                str(config.get("prompt_text", "")),
                principles,
                selected_assessments,
                selection,
                rubric,
                exploration_brief,
            ),
            _strict_schema(ChemicalSpaceProposalPayload),
            "chemical_space_proposals",
        )
        _atomic_json(
            root / "raw.json",
            {
                "cache_key": key,
                "api": {
                    "response_id": api_result.response_id,
                    "returned_model": api_result.returned_model,
                    "status": api_result.status,
                    "usage": asdict(api_result.usage),
                },
                "model_output": api_result.parsed_output,
            },
        )
        try:
            payload = ChemicalSpaceProposalPayload.model_validate(api_result.parsed_output)
        except ValidationError as exc:
            raise ModelProposalError(f"invalid chemical-space schema: {exc}") from exc
        usage = asdict(api_result.usage)
        proposal_status = "validated"
    try:
        families, candidates, coverage_audit = _validate_and_rank_space(
            payload,
            principles,
            selected_assessments,
            rubric,
            exploration_brief=exploration_brief,
        )
    except ValidationError as exc:
        raise ModelProposalError(f"invalid chemical-space schema: {exc}") from exc
    _write_space_cache(
        root / "validated.json",
        key,
        families,
        candidates,
        usage,
        coverage_audit,
    )
    return ChemicalSpaceProposalResult(
        status=proposal_status,
        cache_key=key,
        families=families,
        candidates=candidates,
        usage=usage,
        coverage_audit=coverage_audit,
    )


def _validate_and_rank_space(
    payload: ChemicalSpaceProposalPayload,
    principles: list[ReactionPrinciple],
    assessments: dict[str, TransferabilityAssessment],
    rubric: dict,
    *,
    exploration_brief: ExplorationBrief | None = None,
) -> tuple[
    tuple[FamilyBoundaryPrediction, ...],
    tuple[ExperimentCandidate, ...],
    CoverageAudit | None,
]:
    principle_ids = {item.principle_id for item in principles}
    evidence_ids = set(assessments)
    allowed_hard_blockers: set[str] = set()
    for item in assessments.values():
        evidence_ids.update(item.source_evidence_ids)
        evidence_ids.update(item.seed_feature_ids)
        allowed_hard_blockers.update(item.blocking_constraints)
    expected_compatibility = set(rubric.get("weights", {}))
    expected_risks = set(rubric.get("risk_penalties", {}))
    coverage_audit = (
        validate_nucleophile_coverage(payload.families, exploration_brief)
        if exploration_brief is not None
        else None
    )
    fixed_electrophile_id = (
        exploration_brief.fixed_role.seed_reaction_id
        if exploration_brief is not None
        else None
    )
    family_predictions: dict[str, FamilyBoundaryPrediction] = {}
    for family in payload.families:
        if exploration_brief is not None:
            if family.family_type != "nucleophile":
                raise ModelProposalError("Stage 1 accepts nucleophile families only")
            if not family.superclass_id:
                raise ModelProposalError("v2 family requires superclass_id")
            if family.fixed_electrophile_id != fixed_electrophile_id:
                raise ModelProposalError(
                    "Stage 1 family changed the fixed electrophile"
                )
            if not family.representative_nucleophile or not family.reactive_form:
                raise ModelProposalError(
                    "v2 family requires representative nucleophile and reactive form"
                )
            if family.condition_window is None or family.catalyst_requirement is None:
                raise ModelProposalError(
                    "v2 family requires catalyst requirement and condition window"
                )
        compatibility = _component_map(
            family.compatibility_components,
            expected_compatibility,
            evidence_ids,
            "compatibility",
        )
        risks = _component_map(
            family.risk_components, expected_risks, evidence_ids, "risk"
        )
        referenced_principles = set(family.compatible_principle_ids) | set(
            family.violated_principle_ids
        )
        if not referenced_principles <= principle_ids:
            raise ModelProposalError("family proposal references an unknown Principle")
        if not set(family.evidence_ids) <= evidence_ids:
            raise ModelProposalError("family proposal references unknown evidence")
        if not set(family.hard_blockers) <= allowed_hard_blockers:
            raise ModelProposalError("family proposal references unknown hard blocker")
        if family.family_id in family_predictions:
            raise ModelProposalError(f"duplicate family ID: {family.family_id}")
        family_predictions[family.family_id] = classify_family(
            family_id=family.family_id,
            family_type=family.family_type,
            compatibility=compatibility,
            risks=risks,
            compatible_principle_ids=family.compatible_principle_ids,
            violated_principle_ids=family.violated_principle_ids,
            required_conditions=family.required_conditions,
            evidence_ids=family.evidence_ids,
            hard_blockers=family.hard_blockers,
            uncertainty=family.uncertainty,
            rubric=rubric,
            superclass_id=family.superclass_id,
            representative_nucleophile=family.representative_nucleophile,
            reactive_form=family.reactive_form,
            fixed_electrophile_id=family.fixed_electrophile_id,
            catalyst_requirement=family.catalyst_requirement,
            condition_window=(
                family.condition_window.model_dump(mode="json")
                if family.condition_window is not None
                else None
            ),
            diagnostic_status=family.diagnostic_status,
            no_experiment_rationale=family.no_experiment_rationale,
        )
    experiment_rows: list[dict[str, object]] = []
    seen_experiments: set[str] = set()
    for experiment in payload.experiments:
        if experiment.experiment_id in seen_experiments:
            raise ModelProposalError(f"duplicate experiment ID: {experiment.experiment_id}")
        seen_experiments.add(experiment.experiment_id)
        if experiment.family_id not in family_predictions:
            raise ModelProposalError("experiment references an unknown family")
        if not set(experiment.supporting_principle_ids) <= principle_ids:
            raise ModelProposalError("experiment references an unknown Principle")
        if not set(experiment.evidence_ids) <= evidence_ids:
            raise ModelProposalError("experiment references unknown evidence")
        experiment_rows.append(
            {
                **experiment.model_dump(
                    mode="json", exclude={"bonus_components", "risk_components"}
                ),
                "bonus_components": {
                    item.name: item.value or 0 for item in experiment.bonus_components
                },
                "risk_components": {
                    item.name: item.value or 0 for item in experiment.risk_components
                },
            }
        )
    if exploration_brief is not None:
        experiments_by_family = {
            family_id: sum(row.family_id == family_id for row in payload.experiments)
            for family_id in family_predictions
        }
        for family in payload.families:
            prediction = family_predictions[family.family_id]
            if family.diagnostic_status == "proposed":
                if experiments_by_family[family.family_id] < 1:
                    raise ModelProposalError(
                        f"family {family.family_id} requires a diagnostic experiment"
                    )
                if family.no_experiment_rationale is not None:
                    raise ModelProposalError(
                        "proposed diagnostic cannot carry no_experiment_rationale"
                    )
            elif family.diagnostic_status == "not_executable":
                if not family.no_experiment_rationale:
                    raise ModelProposalError(
                        "not_executable family requires a rationale"
                    )
                if prediction.classification not in {"exclude", "insufficient_evidence"}:
                    raise ModelProposalError(
                        "not_executable is limited to excluded or evidence-insufficient families"
                    )
                if experiments_by_family[family.family_id]:
                    raise ModelProposalError(
                        "not_executable family cannot have an experiment tuple"
                    )
            else:
                raise ModelProposalError("v2 family requires diagnostic_status")
    ranked = rank_experiment_candidates(experiment_rows, family_predictions, rubric)
    families = tuple(family_predictions[key] for key in sorted(family_predictions))
    return families, ranked, coverage_audit


def _component_map(
    components: tuple[ComponentJudgment, ...],
    expected_names: set[str],
    known_evidence_ids: set[str],
    label: str,
) -> dict[str, int | None]:
    values: dict[str, int | None] = {}
    for component in components:
        if component.name in values:
            raise ModelProposalError(f"duplicate {label} component: {component.name}")
        if not set(component.evidence_ids) <= known_evidence_ids:
            raise ModelProposalError(f"{label} component references unknown evidence")
        values[component.name] = component.value
    if set(values) != expected_names:
        missing = sorted(expected_names - set(values))
        extra = sorted(set(values) - expected_names)
        raise ModelProposalError(
            f"{label} components do not match rubric; missing={missing}, extra={extra}"
        )
    return values


def _read_space_cache(path: Path, key: str) -> ChemicalSpaceProposalResult | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if (
            value.get("cache_key") != key
            or value.get("classification_version")
            != CHEMICAL_SPACE_CLASSIFICATION_VERSION
        ):
            return None
        families = tuple(
            FamilyBoundaryPrediction.model_validate(row) for row in value.get("families", [])
        )
        candidates = tuple(
            ExperimentCandidate.model_validate(row) for row in value.get("candidates", [])
        )
        raw_audit = value.get("coverage_audit")
        coverage_audit = (
            CoverageAudit.model_validate(raw_audit)
            if isinstance(raw_audit, dict)
            else None
        )
    except (OSError, json.JSONDecodeError, ValidationError, AttributeError):
        return None
    return ChemicalSpaceProposalResult(
        status="reused",
        cache_key=key,
        families=families,
        candidates=candidates,
        usage={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        coverage_audit=coverage_audit,
    )


def _read_space_raw(path: Path, key: str) -> ChemicalSpaceProposalPayload | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("cache_key") != key:
            return None
        return ChemicalSpaceProposalPayload.model_validate(value.get("model_output"))
    except (OSError, json.JSONDecodeError, ValidationError, AttributeError):
        return None


def _write_space_cache(
    path: Path,
    key: str,
    families: tuple[FamilyBoundaryPrediction, ...],
    candidates: tuple[ExperimentCandidate, ...],
    usage: dict[str, int | None],
    coverage_audit: CoverageAudit | None = None,
) -> None:
    _atomic_json(
        path,
        {
            "cache_key": key,
            "classification_version": CHEMICAL_SPACE_CLASSIFICATION_VERSION,
            "families": [item.model_dump(mode="json") for item in families],
            "candidates": [item.model_dump(mode="json") for item in candidates],
            "coverage_audit": (
                coverage_audit.model_dump(mode="json")
                if coverage_audit is not None
                else None
            ),
            "usage": usage,
        },
    )

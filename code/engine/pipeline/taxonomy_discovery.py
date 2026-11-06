"""Independent, provenance-separated lanes for open v3 taxonomy proposals."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError, model_validator

from pipeline.evidence_registry import _atomic_json
from pipeline.literature_retrieval import SearchRecord
from pipeline.model_proposals import (
    StructuredClient,
    stable_model_digest,
    strict_model_schema,
)
from pipeline.principle_models import (
    FrozenStrictModel,
    ReactionPrinciple,
    TransferabilityAssessment,
)
from pipeline.v3_models import EvidenceLevel, ExplorationBriefV3, v3_brief_digest


DiscoveryChannel = Literal[
    "seed_derived", "literature_derived", "model_hypothesis"
]
DISCOVERY_CHANNELS: tuple[DiscoveryChannel, ...] = (
    "seed_derived",
    "literature_derived",
    "model_hypothesis",
)
TAXONOMY_SCHEMA_VERSION = "taxonomy-lane-v3.5-coordinate-compat-v1"
MAX_MODEL_LANES = 4
FULL_SPACE_REQUIRED_CENTERS = (
    "carbon_center",
    "nitrogen_center",
    "oxygen_center",
    "sulfur_center",
    "phosphorus_center",
)
_LEGACY_PROMPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "config"
    / "prompts"
    / "taxonomy_discovery_v3.md"
)
_FULL_SPACE_PROMPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "config"
    / "prompts"
    / "full_space_taxonomy_v3_6.md"
)


class TaxonomyProposalError(RuntimeError):
    """Raised when a taxonomy lane breaks isolation or provenance rules."""


class TaxonomyModelInvocationConfig(FrozenStrictModel):
    """Scalar model identity accepted by the current StructuredClient contract."""

    model: str = Field(min_length=1)


class MechanismCoordinateAssignment(FrozenStrictModel):
    """Answer-independent labels used only for coverage and stability audits."""

    nucleophilic_center: str = Field(min_length=1)
    reactive_state: str = Field(min_length=1)
    bond_forming_mode: str = Field(min_length=1)
    activation_mode: str = Field(min_length=1)
    attack_topology: str = Field(min_length=1)
    target_termination: str = Field(min_length=1)


class MechanisticProposalDefinition(FrozenStrictModel):
    """Mechanistic coordinates without a final, stable family identifier."""

    nucleophilic_center: str = Field(min_length=1)
    reactive_state: str = Field(min_length=1)
    bond_forming_mode: str = Field(min_length=1)
    activation_mode: str = Field(min_length=1)
    critical_conditions: tuple[str, ...] = Field(min_length=1)
    dominant_failure_modes: tuple[str, ...] = Field(min_length=1)


class TaxonomyProposal(FrozenStrictModel):
    proposal_id: str = Field(min_length=1)
    mechanistic_definition: MechanisticProposalDefinition
    coordinate_assignment: MechanismCoordinateAssignment | None = None
    coordinate_assignment_key: str | None = None
    source_channel: DiscoveryChannel
    evidence_level: EvidenceLevel
    evidence_ids: tuple[str, ...] = ()
    parent_hypothesis: str = Field(min_length=1)
    representative_reactive_state: str = Field(min_length=1)
    counterarguments: tuple[str, ...]
    unknowns: tuple[str, ...]
    suggested_search_terms: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_coordinate(cls, value):
        if not isinstance(value, Mapping):
            return value
        result = dict(value)
        definition = result.get("mechanistic_definition")
        if isinstance(definition, Mapping) and "coordinate_assignment" in definition:
            definition = dict(definition)
            nested = definition.pop("coordinate_assignment")
            outer = result.get("coordinate_assignment")
            if nested is not None:
                nested = MechanismCoordinateAssignment.model_validate(nested)
                if outer is not None and MechanismCoordinateAssignment.model_validate(outer) != nested:
                    raise ValueError("conflicting nested and top-level coordinate assignments")
                result["coordinate_assignment"] = nested
            result["mechanistic_definition"] = definition
        return result

    @model_validator(mode="after")
    def check_coordinate_key(self):
        if (self.coordinate_assignment is not None
                and self.coordinate_assignment_key is not None
                and coordinate_assignment_key(self.coordinate_assignment) != self.coordinate_assignment_key):
            raise ValueError("conflicting coordinate assignment and key")
        return self


class TaxonomyLanePayload(FrozenStrictModel):
    proposals: tuple[TaxonomyProposal, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def require_unique_temporary_ids(self) -> "TaxonomyLanePayload":
        proposal_ids = tuple(item.proposal_id for item in self.proposals)
        if len(proposal_ids) != len(set(proposal_ids)):
            raise ValueError("taxonomy lane proposal IDs must be unique")
        return self


class TaxonomyEvidenceRegistry(FrozenStrictModel):
    """Evidence identifiers that each proposal channel is allowed to cite."""

    seed_derived: tuple[str, ...] = ()
    literature_derived: tuple[str, ...] = ()

    @model_validator(mode="after")
    def require_unique_ids(self) -> "TaxonomyEvidenceRegistry":
        for channel, values in (
            ("seed_derived", self.seed_derived),
            ("literature_derived", self.literature_derived),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"{channel} evidence registry contains duplicate IDs")
        if set(self.seed_derived).intersection(self.literature_derived):
            raise ValueError("taxonomy evidence channel registries must be disjoint")
        return self

    def allowed_ids(self, channel: DiscoveryChannel) -> frozenset[str]:
        if channel == "model_hypothesis":
            return frozenset()
        return frozenset(getattr(self, channel))


class TaxonomyLaneResult(FrozenStrictModel):
    status: Literal["validated", "reused"]
    cache_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    lane_id: str = Field(min_length=1)
    round_id: int = Field(ge=1)
    channel: DiscoveryChannel
    proposals: tuple[TaxonomyProposal, ...] = Field(min_length=1)
    usage: dict[str, int | None]


@dataclass(frozen=True)
class TaxonomyDiscoveryContext:
    """All pre-canonicalization inputs available to one independent lane."""

    brief: ExplorationBriefV3
    reviewed_principles: Sequence[ReactionPrinciple]
    selected_transfer_assessments: (
        Sequence[TransferabilityAssessment]
        | Mapping[str, TransferabilityAssessment]
    )
    retrieval_evidence: Sequence[SearchRecord]
    evidence_import_digest: str
    output_root: Path
    model_config: TaxonomyModelInvocationConfig
    prompt_version: str = "taxonomy-discovery-v3.1"
    coordinate_vocabulary: Mapping[str, tuple[str, ...]] | None = None
    allowed_coordinate_assignments: Sequence[MechanismCoordinateAssignment] | None = None

    def __post_init__(self) -> None:
        if type(self.model_config) is not TaxonomyModelInvocationConfig:
            raise TypeError(
                "model_config must be the exact TaxonomyModelInvocationConfig type"
            )
        if (
            len(self.evidence_import_digest) != 64
            or any(char not in "0123456789abcdef" for char in self.evidence_import_digest)
        ):
            raise ValueError("evidence import digest must be SHA-256 hex")
        if not self.prompt_version.strip():
            raise ValueError("taxonomy prompt version is required")
        if self.coordinate_vocabulary is not None:
            required = set(MechanismCoordinateAssignment.model_fields)
            if set(self.coordinate_vocabulary) != required:
                raise ValueError("coordinate vocabulary must define all six mechanism axes")
            if any(
                not values
                or len(values) != len(set(values))
                or any(not value.strip() for value in values)
                for values in self.coordinate_vocabulary.values()
            ):
                raise ValueError("coordinate vocabulary values must be unique and non-empty")
        if self.allowed_coordinate_assignments is not None:
            if not self.allowed_coordinate_assignments:
                raise ValueError("allowed coordinate assignments cannot be empty")
            if self.coordinate_vocabulary is None:
                raise ValueError("allowed coordinate assignments require a vocabulary")
            keys = tuple(MechanismCoordinateAssignment.model_fields)
            assignments = {
                tuple(getattr(item, key) for key in keys)
                for item in self.allowed_coordinate_assignments
            }
            if len(assignments) != len(self.allowed_coordinate_assignments):
                raise ValueError("allowed coordinate assignments must be unique")


def coordinate_assignment_key(assignment: MechanismCoordinateAssignment) -> str:
    payload = assignment.model_dump(mode="json")
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "MCV3-" + hashlib.sha256(encoded).hexdigest()[:16]


def _assessment_rows(
    assessments: Sequence[TransferabilityAssessment]
    | Mapping[str, TransferabilityAssessment],
) -> tuple[TransferabilityAssessment, ...]:
    if isinstance(assessments, Mapping):
        for assessment_id, assessment in assessments.items():
            if assessment_id != assessment.assessment_id:
                raise TaxonomyProposalError(
                    "selected assessment mapping key does not match payload"
                )
        rows = tuple(assessments.values())
    else:
        rows = tuple(assessments)
    if len({item.assessment_id for item in rows}) != len(rows):
        raise TaxonomyProposalError("selected transfer assessment IDs must be unique")
    return tuple(sorted(rows, key=lambda item: item.assessment_id))


def _retrieval_rows(records: Sequence[SearchRecord]) -> tuple[SearchRecord, ...]:
    rows = tuple(records)
    if len({item.record_id for item in rows}) != len(rows):
        raise TaxonomyProposalError("retrieval evidence record IDs must be unique")
    return tuple(sorted(rows, key=lambda item: item.record_id))


def _reviewed_principles(
    principles: Sequence[ReactionPrinciple],
) -> tuple[ReactionPrinciple, ...]:
    rows = tuple(principles)
    invalid = sorted(
        item.principle_id
        for item in rows
        if item.status not in {"accepted", "revised"}
        or item.review_status not in {"accepted", "revised"}
    )
    if not rows or invalid:
        detail = ": " + ", ".join(invalid) if invalid else ""
        raise TaxonomyProposalError("taxonomy discovery requires reviewed Principles" + detail)
    if len({item.principle_id for item in rows}) != len(rows):
        raise TaxonomyProposalError("reviewed Principle IDs must be unique")
    return tuple(sorted(rows, key=lambda item: item.principle_id))


def _prompt_path(prompt_version: str) -> Path:
    if prompt_version.startswith("taxonomy-discovery-v3.6"):
        return _FULL_SPACE_PROMPT_PATH
    return _LEGACY_PROMPT_PATH


def _prompt_text(prompt_version: str) -> str:
    try:
        return _prompt_path(prompt_version).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise TaxonomyProposalError("taxonomy discovery prompt is unavailable") from exc


def validate_center_symmetric_lane_inputs(
    context: TaxonomyDiscoveryContext, required_centers: Sequence[str]
) -> None:
    assignments = context.allowed_coordinate_assignments or ()
    by_center = {
        center: frozenset(
            (
                a.reactive_state,
                a.bond_forming_mode,
                a.activation_mode,
                a.attack_topology,
                a.target_termination,
            )
            for a in assignments
            if a.nucleophilic_center == center
        )
        for center in required_centers
    }
    signatures = tuple(by_center.values())
    if not signatures or not signatures[0] or len(set(signatures)) != 1:
        raise TaxonomyProposalError("full-space center contract must be symmetric")


def _evidence_registry(
    principles: Sequence[ReactionPrinciple],
    assessments: Sequence[TransferabilityAssessment],
    records: Sequence[SearchRecord],
) -> TaxonomyEvidenceRegistry:
    return TaxonomyEvidenceRegistry(
        seed_derived=tuple(item.principle_id for item in principles),
        literature_derived=tuple(
            sorted(
                {item.assessment_id for item in assessments}
                | {
                    item.record_id
                    for item in records
                    if item.screening_decision == "include"
                }
            )
        ),
    )


def validate_lane_payload(
    payload: TaxonomyLanePayload | Mapping[str, object],
    evidence_registry: TaxonomyEvidenceRegistry,
    *,
    expected_channel: DiscoveryChannel | None = None,
) -> TaxonomyLanePayload:
    """Validate strict shape, channel identity, and cited evidence provenance."""

    validated = (
        payload
        if isinstance(payload, TaxonomyLanePayload)
        else TaxonomyLanePayload.model_validate(payload)
    )
    for proposal in validated.proposals:
        channel = proposal.source_channel
        if expected_channel is not None and channel != expected_channel:
            raise TaxonomyProposalError(
                f"{expected_channel} lane returned a {channel} proposal"
            )
        if channel == "model_hypothesis" and proposal.evidence_ids:
            raise TaxonomyProposalError(
                "model hypothesis proposal cannot claim external evidence"
            )
        if (
            channel == "model_hypothesis"
            and proposal.evidence_level != "model_physical_organic_inference"
        ):
            raise TaxonomyProposalError(
                "model hypothesis proposal requires the model inference evidence level"
            )
        if (
            channel == "literature_derived"
            and proposal.evidence_level != "traceable_external_evidence"
        ):
            raise TaxonomyProposalError(
                "literature-derived proposal requires traceable external evidence"
            )
        if channel != "model_hypothesis" and not proposal.evidence_ids:
            raise TaxonomyProposalError(
                f"{channel} proposal requires channel evidence"
            )
        unknown = sorted(
            set(proposal.evidence_ids) - evidence_registry.allowed_ids(channel)
        )
        if unknown:
            raise TaxonomyProposalError(
                f"{channel} proposal cites evidence outside its channel: "
                + ", ".join(unknown)
            )
    return validated


def build_taxonomy_cache_key(
    *,
    brief_digest: str,
    evidence_import_digest: str,
    principle_digest: str,
    transfer_digest: str,
    retrieval_digest: str,
    lane_id: str,
    channel: DiscoveryChannel,
    round_id: int,
    prompt_version: str,
    prompt_digest: str,
    schema_version: str,
    model_config: TaxonomyModelInvocationConfig,
    coordinate_digest: str | None = None,
) -> str:
    """Hash every upstream and execution identity for one lane call."""

    if type(model_config) is not TaxonomyModelInvocationConfig:
        raise TypeError(
            "model_config must be the exact TaxonomyModelInvocationConfig type"
        )
    return stable_model_digest(
        {
            "brief_digest": brief_digest,
            "evidence_import_digest": evidence_import_digest,
            "principle_digest": principle_digest,
            "transfer_digest": transfer_digest,
            "retrieval_digest": retrieval_digest,
            "lane_id": lane_id,
            "channel": channel,
            "round_id": round_id,
            "prompt_version": prompt_version,
            "prompt_digest": prompt_digest,
            "schema_version": schema_version,
            "model_config": model_config.model_dump(mode="json"),
            "coordinate_digest": coordinate_digest,
        }
    )


def _validate_lane_identity(
    lane_id: str, round_id: int, channel: DiscoveryChannel
) -> None:
    if (
        not lane_id
        or lane_id in {".", ".."}
        or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for char in lane_id)
    ):
        raise TaxonomyProposalError("lane ID must be a path-safe identifier")
    if round_id < 1:
        raise TaxonomyProposalError("taxonomy round ID must be positive")
    if channel not in DISCOVERY_CHANNELS:
        raise TaxonomyProposalError("unknown taxonomy discovery channel")


def _channel_bundle(
    context: TaxonomyDiscoveryContext,
    channel: DiscoveryChannel,
    principles: Sequence[ReactionPrinciple],
    assessments: Sequence[TransferabilityAssessment],
    records: Sequence[SearchRecord],
    evidence_registry: TaxonomyEvidenceRegistry,
) -> dict[str, object]:
    bundle: dict[str, object] = {
        "exploration_brief": context.brief.model_dump(mode="json"),
        "allowed_evidence_ids": sorted(evidence_registry.allowed_ids(channel)),
    }
    if context.coordinate_vocabulary is not None:
        bundle["coordinate_vocabulary"] = {
            key: list(values)
            for key, values in sorted(context.coordinate_vocabulary.items())
        }
    if context.allowed_coordinate_assignments is not None:
        bundle["allowed_coordinate_assignments"] = [
            {
                "coordinate_assignment_key": coordinate_assignment_key(item),
                "coordinate_assignment": item.model_dump(mode="json"),
            }
            for item in context.allowed_coordinate_assignments
        ]
    if channel == "seed_derived":
        bundle["reviewed_principles"] = [
            _principle_projection(item) for item in principles
        ]
    elif channel == "literature_derived":
        bundle["selected_transfer_assessments"] = [
            item.model_dump(mode="json") for item in assessments
        ]
        bundle["retrieval_evidence"] = [
            item.model_dump(mode="json")
            for item in records
            if item.screening_decision == "include"
        ]
    return bundle


def _principle_projection(principle: ReactionPrinciple) -> dict[str, object]:
    """Expose mechanistic Principle fields without legacy named-family ontology."""

    return {
        "principle_id": principle.principle_id,
        "principle_layer": principle.principle_layer,
        "claim": principle.claim,
        "mechanistic_basis": principle.mechanistic_basis,
        "required_reactive_form": principle.required_reactive_form,
        "catalyst_requirements": principle.catalyst_requirements,
        "condition_window": principle.condition_window,
        "structural_promoters": principle.structural_promoters,
        "structural_inhibitors": principle.structural_inhibitors,
        "known_exceptions": principle.known_exceptions,
        "predicted_failure_modes": principle.predicted_failure_modes,
        "experimental_consequence": principle.experimental_consequence,
        "falsifying_experiment": principle.falsifying_experiment,
    }


def _lane_input(
    prompt_text: str,
    context: TaxonomyDiscoveryContext,
    lane_id: str,
    round_id: int,
    channel: DiscoveryChannel,
    principles: Sequence[ReactionPrinciple],
    assessments: Sequence[TransferabilityAssessment],
    records: Sequence[SearchRecord],
    evidence_registry: TaxonomyEvidenceRegistry,
) -> str:
    source_bundle = _channel_bundle(
        context,
        channel,
        principles,
        assessments,
        records,
        evidence_registry,
    )
    evidence_instruction = (
        "Cite no evidence IDs and make no external-evidence claim; this channel is "
        "model physical-organic inference only."
        if channel == "model_hypothesis"
        else (
            "Cite only IDs in source_bundle.allowed_evidence_ids. Other nested IDs "
            "are provenance metadata and are not citable in this proposal."
        )
    )
    envelope = {
        "lane_id": lane_id,
        "round_id": round_id,
        "channel": channel,
        "source_bundle": source_bundle,
    }
    return (
        f"{prompt_text}\n\n"
        f"Active independent lane: {lane_id}; round: {round_id}; channel: {channel}. "
        "No output from any other lane is available. "
        f"{evidence_instruction} Use temporary proposal_id values only. Do not return "
        "a stable family ID, score, rank, classification, review decision, or freeze state.\n\n"
        "BEGIN_TAXONOMY_LANE_INPUT\n"
        f"{_canonical_json(envelope)}\n"
        "END_TAXONOMY_LANE_INPUT\n"
    )


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _lane_schema(
    channel: DiscoveryChannel,
    allowed_evidence_ids: Sequence[str],
    coordinate_vocabulary: Mapping[str, Sequence[str]] | None = None,
    allowed_coordinate_assignments: Sequence[MechanismCoordinateAssignment] | None = None,
) -> dict[str, object]:
    schema = deepcopy(strict_model_schema(TaxonomyLanePayload))
    proposal = schema["$defs"]["TaxonomyProposal"]["properties"]
    proposal["source_channel"] = {"type": "string", "const": channel}
    evidence_level = (
        "model_physical_organic_inference"
        if channel == "model_hypothesis"
        else "traceable_external_evidence"
    )
    proposal["evidence_level"] = {"type": "string", "const": evidence_level}
    proposal["evidence_ids"] = {
        "type": "array",
        "items": {
            "type": "string",
            **(
                {"enum": sorted(allowed_evidence_ids)}
                if channel != "model_hypothesis"
                else {}
            ),
        },
        **({"maxItems": 0} if channel == "model_hypothesis" else {"minItems": 1}),
    }
    if coordinate_vocabulary is not None and allowed_coordinate_assignments is None:
        assignment = schema["$defs"]["MechanismCoordinateAssignment"]
        proposal_definition = schema["$defs"]["TaxonomyProposal"]
        proposal_definition["required"] = sorted(
            set(proposal_definition.get("required", ())) | {"coordinate_assignment"}
        )
        for key, values in coordinate_vocabulary.items():
            assignment["properties"][key] = {
                "type": "string",
                "enum": sorted(values),
            }
    if allowed_coordinate_assignments is not None:
        proposal_definition = schema["$defs"]["TaxonomyProposal"]
        proposal_definition["properties"].pop("coordinate_assignment", None)
        proposal_definition["properties"]["coordinate_assignment_key"] = {
            "type": "string",
            "enum": sorted(
                coordinate_assignment_key(item)
                for item in allowed_coordinate_assignments
            ),
        }
        proposal_definition["required"] = sorted(
            (
                set(proposal_definition.get("required", ()))
                - {"coordinate_assignment"}
            )
            | {"coordinate_assignment_key"}
        )
    return schema


def _materialize_coordinate_assignments(
    payload: TaxonomyLanePayload,
    allowed_assignments: Sequence[MechanismCoordinateAssignment] | None,
) -> TaxonomyLanePayload:
    if allowed_assignments is None:
        return payload
    by_key = {
        coordinate_assignment_key(item): item for item in allowed_assignments
    }
    proposals: list[TaxonomyProposal] = []
    for proposal in payload.proposals:
        key = proposal.coordinate_assignment_key
        if key is None and proposal.coordinate_assignment is not None:
            key = coordinate_assignment_key(proposal.coordinate_assignment)
        if key not in by_key:
            raise TaxonomyProposalError(
                "taxonomy proposal is outside the complete allowed assignment set"
            )
        proposals.append(
            proposal.model_copy(update={"coordinate_assignment": by_key[key]})
        )
    return TaxonomyLanePayload(proposals=tuple(proposals))


def _validate_coordinate_assignments(
    payload: TaxonomyLanePayload,
    vocabulary: Mapping[str, Sequence[str]] | None,
    allowed_assignments: Sequence[MechanismCoordinateAssignment] | None = None,
) -> None:
    if vocabulary is None:
        return
    allowed = {key: set(values) for key, values in vocabulary.items()}
    for proposal in payload.proposals:
        assignment = proposal.coordinate_assignment
        if assignment is None:
            raise TaxonomyProposalError("taxonomy proposal is missing coordinate assignment")
        if any(getattr(assignment, key) not in values for key, values in allowed.items()):
            raise TaxonomyProposalError("taxonomy proposal uses a coordinate outside the vocabulary")
    if allowed_assignments is not None:
        keys = tuple(MechanismCoordinateAssignment.model_fields)
        permitted = {
            tuple(getattr(item, key) for key in keys) for item in allowed_assignments
        }
        if any(
            tuple(getattr(proposal.coordinate_assignment, key) for key in keys)
            not in permitted
            for proposal in payload.proposals
        ):
            raise TaxonomyProposalError(
                "taxonomy proposal is outside the complete allowed assignment set"
            )


def _qualify_temporary_ids(
    payload: TaxonomyLanePayload, lane_id: str, channel: DiscoveryChannel
) -> TaxonomyLanePayload:
    return TaxonomyLanePayload(
        proposals=tuple(
            proposal.model_copy(
                update={
                    "proposal_id": f"{lane_id}:{channel}:{proposal.proposal_id}"
                }
            )
            for proposal in payload.proposals
        )
    )


def _read_cached_lane(
    path: Path,
    cache_key: str,
    lane_id: str,
    round_id: int,
    channel: DiscoveryChannel,
    registry: TaxonomyEvidenceRegistry,
) -> TaxonomyLaneResult | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if (
            value.get("cache_key") != cache_key
            or value.get("lane_id") != lane_id
            or value.get("round_id") != round_id
            or value.get("channel") != channel
        ):
            return None
        payload = validate_lane_payload(
            {"proposals": value.get("proposals")},
            registry,
            expected_channel=channel,
        )
        usage = value.get("usage")
        if not isinstance(usage, dict):
            return None
        return TaxonomyLaneResult(
            status="reused",
            cache_key=cache_key,
            lane_id=lane_id,
            round_id=round_id,
            channel=channel,
            proposals=payload.proposals,
            usage=usage,
        )
    except (
        OSError,
        json.JSONDecodeError,
        ValidationError,
        TaxonomyProposalError,
        AttributeError,
    ):
        return None


def propose_family_lane(
    context: TaxonomyDiscoveryContext,
    client: StructuredClient,
    *,
    lane_id: str,
    round_id: int,
    channel: DiscoveryChannel,
) -> TaxonomyLaneResult:
    """Generate one lane/channel proposal without reading peer-lane output."""

    _validate_lane_identity(lane_id, round_id, channel)
    principles = _reviewed_principles(context.reviewed_principles)
    assessments = _assessment_rows(context.selected_transfer_assessments)
    records = _retrieval_rows(context.retrieval_evidence)
    if context.prompt_version.startswith("taxonomy-discovery-v3.6"):
        validate_center_symmetric_lane_inputs(context, FULL_SPACE_REQUIRED_CENTERS)
    prompt_text = _prompt_text(context.prompt_version)
    registry = _evidence_registry(principles, assessments, records)
    principle_digest = stable_model_digest(
        [item.model_dump(mode="json") for item in principles]
    )
    transfer_digest = stable_model_digest(
        [item.model_dump(mode="json") for item in assessments]
    )
    retrieval_digest = stable_model_digest(
        [item.model_dump(mode="json") for item in records]
    )
    prompt_digest = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()
    cache_key = build_taxonomy_cache_key(
        brief_digest=v3_brief_digest(context.brief),
        evidence_import_digest=context.evidence_import_digest,
        principle_digest=principle_digest,
        transfer_digest=transfer_digest,
        retrieval_digest=retrieval_digest,
        lane_id=lane_id,
        channel=channel,
        round_id=round_id,
        prompt_version=context.prompt_version,
        prompt_digest=prompt_digest,
        schema_version=TAXONOMY_SCHEMA_VERSION,
        model_config=context.model_config,
        coordinate_digest=(
            stable_model_digest(
                {
                    "vocabulary": context.coordinate_vocabulary,
                    "allowed_assignments": [
                        item.model_dump(mode="json")
                        for item in (context.allowed_coordinate_assignments or ())
                    ],
                }
            )
            if context.coordinate_vocabulary is not None
            else None
        ),
    )
    root = (
        context.output_root.resolve()
        / "derived"
        / "principles_v3"
        / "taxonomy"
        / f"round-{round_id}"
        / lane_id
        / channel
    )
    validated_path = root / "validated.json"
    cached = _read_cached_lane(
        validated_path,
        cache_key,
        lane_id,
        round_id,
        channel,
        registry,
    )
    if cached is not None:
        _validate_coordinate_assignments(
            TaxonomyLanePayload(proposals=cached.proposals),
            context.coordinate_vocabulary,
            context.allowed_coordinate_assignments,
        )
        return cached

    model = context.model_config.model
    validated_path.unlink(missing_ok=True)
    api_result = client.create_structured(
        model,
        _lane_input(
            prompt_text,
            context,
            lane_id,
            round_id,
            channel,
            principles,
            assessments,
            records,
            registry,
        ),
        _lane_schema(
            channel,
            tuple(registry.allowed_ids(channel)),
            context.coordinate_vocabulary,
            context.allowed_coordinate_assignments,
        ),
        "taxonomy_lane_proposals_v3",
    )
    try:
        provider_payload = validate_lane_payload(
            api_result.parsed_output, registry, expected_channel=channel
        )
        provider_payload = _materialize_coordinate_assignments(
            provider_payload, context.allowed_coordinate_assignments
        )
        _validate_coordinate_assignments(
            provider_payload,
            context.coordinate_vocabulary,
            context.allowed_coordinate_assignments,
        )
        payload = _qualify_temporary_ids(provider_payload, lane_id, channel)
    except ValidationError as exc:
        raise TaxonomyProposalError(f"invalid taxonomy lane schema: {exc}") from exc
    _atomic_json(
        root / "raw.json",
        {
            "cache_key": cache_key,
            "lane_id": lane_id,
            "round_id": round_id,
            "channel": channel,
            "api": {
                "response_id": api_result.response_id,
                "returned_model": api_result.returned_model,
                "status": api_result.status,
                "transport": api_result.transport,
                "usage": asdict(api_result.usage),
            },
            "provider_model_output_digest": hashlib.sha256(
                _canonical_json(api_result.parsed_output).encode("utf-8")
            ).hexdigest(),
            "model_output": payload.model_dump(mode="json"),
        },
    )
    usage = asdict(api_result.usage)
    _atomic_json(
        validated_path,
        {
            "cache_key": cache_key,
            "lane_id": lane_id,
            "round_id": round_id,
            "channel": channel,
            "proposals": [item.model_dump(mode="json") for item in payload.proposals],
            "usage": usage,
        },
    )
    return TaxonomyLaneResult(
        status="validated",
        cache_key=cache_key,
        lane_id=lane_id,
        round_id=round_id,
        channel=channel,
        proposals=payload.proposals,
        usage=usage,
    )


def propose_family_round(
    context: TaxonomyDiscoveryContext,
    client: StructuredClient,
    *,
    lane_ids: Sequence[str],
    round_id: int,
) -> tuple[TaxonomyLaneResult, ...]:
    """Run two to four isolated lanes across every discovery channel."""

    lanes = tuple(lane_ids)
    if len(lanes) < 2:
        raise TaxonomyProposalError("taxonomy discovery requires at least two lanes")
    if len(lanes) > MAX_MODEL_LANES:
        raise TaxonomyProposalError(
            f"taxonomy discovery supports at most {MAX_MODEL_LANES} lanes"
        )
    if len(lanes) != len(set(lanes)):
        raise TaxonomyProposalError("taxonomy lane IDs must be unique")
    results: list[TaxonomyLaneResult] = []
    for lane_id in lanes:
        for channel in DISCOVERY_CHANNELS:
            results.append(
                propose_family_lane(
                    context,
                    client,
                    lane_id=lane_id,
                    round_id=round_id,
                    channel=channel,
                )
            )
    return tuple(results)


propose_family_lanes = propose_family_round

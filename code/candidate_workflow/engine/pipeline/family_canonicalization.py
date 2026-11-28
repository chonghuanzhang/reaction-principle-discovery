"""Deterministic, lossless canonicalization of validated v3 family proposals."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError, model_validator

from pipeline.api_client import ApiClientError
from pipeline.model_proposals import StructuredClient, strict_model_schema
from pipeline.principle_models import FrozenStrictModel
from pipeline.taxonomy_discovery import (
    DiscoveryChannel,
    MechanismCoordinateAssignment,
    MechanisticProposalDefinition,
    TaxonomyLaneResult,
    TaxonomyProposal,
)
from pipeline.v3_models import EvidenceLevel, FamilyDefinition, JudgmentState


CanonicalizationDecisionType = Literal[
    "merge", "split", "parent_child", "distinct", "unresolved"
]
DecisionSource = Literal["deterministic"]
FAMILY_ADJUDICATION_SCHEMA_NAME = "family_adjudication_v3"
FAMILY_ADJUDICATION_MODEL = "gpt-5.6-terra"
MAX_ADJUDICATION_BATCH_SIZE = 4
MAX_ADJUDICATION_CALLS = 8
_DECISION_ORDER = {
    "merge": 0,
    "split": 1,
    "parent_child": 2,
    "distinct": 3,
    "unresolved": 4,
}
_PROMPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "config"
    / "prompts"
    / "family_adjudication_v3.md"
)
_SPACE = re.compile(r"\s+")
_TOKEN = re.compile(r"[a-z0-9]+")
_PARAPHRASE_CANDIDATE_THRESHOLD = 0.25


class CanonicalizationError(RuntimeError):
    """Raised when proposals or adjudication output cannot be losslessly resolved."""


class ProposalProvenance(FrozenStrictModel):
    proposal_id: str = Field(min_length=1)
    lane_id: str = Field(min_length=1)
    channel: DiscoveryChannel
    round_id: int = Field(ge=1)
    evidence_level: EvidenceLevel
    evidence_ids: tuple[str, ...]


class CanonicalFamily(FamilyDefinition):
    """A v3 mechanism-defined family plus every originating proposal record."""

    proposal_ids: tuple[str, ...] = Field(min_length=1)
    proposal_provenance: tuple[ProposalProvenance, ...] = Field(min_length=1)
    evidence_ids: tuple[str, ...] = ()
    aliases: tuple[str, ...] = Field(min_length=1)
    unresolved_disagreements: tuple[str, ...] = ()
    parent_family_ids: tuple[str, ...] = ()
    child_family_ids: tuple[str, ...] = ()
    representative_reactive_state_candidates: tuple[str, ...] = Field(min_length=1)
    mechanistic_definition_candidates: tuple[MechanisticProposalDefinition, ...] = Field(
        min_length=1
    )
    coordinate_assignments: tuple[MechanismCoordinateAssignment, ...] = ()

    @model_validator(mode="after")
    def validate_preserved_provenance(self) -> "CanonicalFamily":
        provenance_ids = tuple(item.proposal_id for item in self.proposal_provenance)
        if self.proposal_ids != provenance_ids:
            raise ValueError("canonical family proposal IDs must match provenance")
        if len(self.proposal_ids) != len(set(self.proposal_ids)):
            raise ValueError("canonical family proposal IDs must be unique")
        if set(self.parent_family_ids).intersection(self.child_family_ids):
            raise ValueError("a canonical family relation cannot be both parent and child")
        if self.family_id in set(self.parent_family_ids) | set(self.child_family_ids):
            raise ValueError("a canonical family cannot be related to itself")
        return self


class CanonicalizationDecision(FrozenStrictModel):
    compared_proposal_ids: tuple[str, ...] = Field(min_length=1)
    decision: CanonicalizationDecisionType
    family_ids: tuple[str, ...] = Field(min_length=1)
    parent_family_id: str | None = None
    child_family_id: str | None = None
    rationale: str = Field(min_length=1)
    source: DecisionSource
    evidence_ids: tuple[str, ...] = ()
    unresolved_disagreements: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_relation(self) -> "CanonicalizationDecision":
        if tuple(sorted(set(self.compared_proposal_ids))) != self.compared_proposal_ids:
            raise ValueError("compared proposal IDs must be unique and sorted")
        if self.decision == "parent_child":
            if self.parent_family_id is None or self.child_family_id is None:
                raise ValueError("parent_child decision requires both family relations")
            if self.parent_family_id == self.child_family_id:
                raise ValueError("parent_child decision requires distinct families")
        elif self.parent_family_id is not None or self.child_family_id is not None:
            raise ValueError("only parent_child decisions may assign family relations")
        return self


class CanonicalTaxonomy(FrozenStrictModel):
    families: tuple[CanonicalFamily, ...]
    decisions: tuple[CanonicalizationDecision, ...]
    unresolved_proposal_ids: tuple[str, ...]

    @model_validator(mode="after")
    def validate_lossless_taxonomy(self) -> "CanonicalTaxonomy":
        family_ids = tuple(item.family_id for item in self.families)
        if len(family_ids) != len(set(family_ids)):
            raise ValueError("canonical family IDs must be unique")
        proposal_ids = tuple(
            proposal_id
            for family in self.families
            for proposal_id in family.proposal_ids
        )
        if len(proposal_ids) != len(set(proposal_ids)):
            raise ValueError("each proposal must occur in exactly one canonical family")
        if not set(self.unresolved_proposal_ids).issubset(proposal_ids):
            raise ValueError("unresolved proposals must remain in the canonical taxonomy")
        known_families = set(family_ids)
        for family in self.families:
            if not set(family.parent_family_ids).issubset(known_families):
                raise ValueError("parent relation cites an unknown family")
            if not set(family.child_family_ids).issubset(known_families):
                raise ValueError("child relation cites an unknown family")
            for parent_id in family.parent_family_ids:
                parent = self.families[family_ids.index(parent_id)]
                if family.family_id not in parent.child_family_ids:
                    raise ValueError("parent/child family relations must be bidirectional")
            for child_id in family.child_family_ids:
                child = self.families[family_ids.index(child_id)]
                if family.family_id not in child.parent_family_ids:
                    raise ValueError("parent/child family relations must be bidirectional")
        if any(
            not set(decision.compared_proposal_ids).issubset(proposal_ids)
            for decision in self.decisions
        ):
            raise ValueError("canonicalization decision cites an unknown proposal")
        return self


class ComparisonJudgment(FrozenStrictModel):
    """Evidence-bearing state for one mechanistic comparison dimension."""

    state: JudgmentState
    evidence_ids: tuple[str, ...]

    @model_validator(mode="after")
    def validate_evidence_state(self) -> "ComparisonJudgment":
        if self.state == "unknown" and self.evidence_ids:
            raise ValueError("unknown comparison state cannot cite supporting evidence")
        if self.state != "unknown" and not self.evidence_ids:
            raise ValueError("non-unknown comparison state requires cited evidence IDs")
        object.__setattr__(self, "evidence_ids", tuple(sorted(set(self.evidence_ids))))
        return self


class AdjudicationComparison(FrozenStrictModel):
    """Model-returned states that deterministic code maps to an outcome."""

    compared_proposal_ids: tuple[str, str]
    same_mechanism: ComparisonJudgment
    shared_scope: ComparisonJudgment
    left_contains_right: ComparisonJudgment
    right_contains_left: ComparisonJudgment
    experimentally_distinguishable: ComparisonJudgment
    uncertainties: tuple[str, ...]

    @model_validator(mode="after")
    def validate_compared_ids(self) -> "AdjudicationComparison":
        compared = tuple(sorted(self.compared_proposal_ids))
        if len(set(compared)) != 2:
            raise ValueError("adjudication must cite two distinct compared proposal IDs")
        object.__setattr__(self, "compared_proposal_ids", compared)
        object.__setattr__(self, "uncertainties", tuple(sorted(set(self.uncertainties))))
        return self


class FamilyAdjudicationPayload(FrozenStrictModel):
    comparisons: tuple[AdjudicationComparison, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def require_unique_comparisons(self) -> "FamilyAdjudicationPayload":
        comparisons = tuple(item.compared_proposal_ids for item in self.comparisons)
        if len(comparisons) != len(set(comparisons)):
            raise ValueError("adjudication cannot decide the same comparison twice")
        return self


class _ProposalRecord(FrozenStrictModel):
    proposal: TaxonomyProposal
    provenance: ProposalProvenance
    payload_json: str


class _PendingDecision(FrozenStrictModel):
    compared_proposal_ids: tuple[str, ...]
    decision: CanonicalizationDecisionType
    rationale: str
    source: DecisionSource
    evidence_ids: tuple[str, ...] = ()
    unresolved_disagreements: tuple[str, ...] = ()
    parent_proposal_id: str | None = None
    child_proposal_id: str | None = None


class _UnionFind:
    def __init__(self, values: Sequence[str]) -> None:
        self._parent = {value: value for value in values}

    def find(self, value: str) -> str:
        parent = self._parent[value]
        if parent != value:
            self._parent[value] = self.find(parent)
        return self._parent[value]

    def union(self, left: str, right: str) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return
        canonical_root, merged_root = sorted((left_root, right_root))
        self._parent[merged_root] = canonical_root


def _normalize_text(value: str) -> str:
    return _SPACE.sub(" ", unicodedata.normalize("NFKC", value).strip()).casefold()


def _normalize_multivalue(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(sorted({_normalize_text(value) for value in values}))


def _normalized_definition(
    definition: MechanisticProposalDefinition,
) -> MechanisticProposalDefinition:
    return MechanisticProposalDefinition(
        nucleophilic_center=_normalize_text(definition.nucleophilic_center),
        reactive_state=_normalize_text(definition.reactive_state),
        bond_forming_mode=_normalize_text(definition.bond_forming_mode),
        activation_mode=_normalize_text(definition.activation_mode),
        critical_conditions=_normalize_multivalue(definition.critical_conditions),
        dominant_failure_modes=_normalize_multivalue(
            definition.dominant_failure_modes
        ),
    )


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _definition_payload(definition: MechanisticProposalDefinition) -> dict[str, object]:
    return definition.model_dump(mode="json")


def _family_id(payload_json: str) -> str:
    return "NFV3-" + hashlib.sha256(payload_json.encode("utf-8")).hexdigest()[:12]


def _validated_records(
    results: Sequence[TaxonomyLaneResult],
) -> tuple[_ProposalRecord, ...]:
    records: list[_ProposalRecord] = []
    proposal_ids: set[str] = set()
    round_ids: set[int] = set()
    for candidate in results:
        if type(candidate) is not TaxonomyLaneResult:
            raise TypeError("canonicalization requires TaxonomyLaneResult objects")
        try:
            result = TaxonomyLaneResult.model_validate(candidate.model_dump(mode="python"))
        except ValidationError as exc:
            raise CanonicalizationError("invalid taxonomy lane result") from exc
        round_ids.add(result.round_id)
        for proposal in result.proposals:
            if proposal.source_channel != result.channel:
                raise CanonicalizationError(
                    f"proposal {proposal.proposal_id} does not match its lane channel"
                )
            if proposal.proposal_id in proposal_ids:
                raise CanonicalizationError(
                    f"duplicate proposal ID across taxonomy lanes: {proposal.proposal_id}"
                )
            proposal_ids.add(proposal.proposal_id)
            normalized = _normalized_definition(proposal.mechanistic_definition)
            records.append(
                _ProposalRecord(
                    proposal=proposal,
                    provenance=ProposalProvenance(
                        proposal_id=proposal.proposal_id,
                        lane_id=result.lane_id,
                        channel=result.channel,
                        round_id=result.round_id,
                        evidence_level=proposal.evidence_level,
                        evidence_ids=tuple(sorted(set(proposal.evidence_ids))),
                    ),
                    payload_json=_canonical_json(_definition_payload(normalized)),
                )
            )
    if len(round_ids) > 1:
        raise CanonicalizationError("canonicalization accepts one taxonomy round")
    return tuple(sorted(records, key=lambda item: item.proposal.proposal_id))


def _group_records(
    records: Sequence[_ProposalRecord],
) -> tuple[tuple[_ProposalRecord, ...], ...]:
    grouped: dict[str, list[_ProposalRecord]] = defaultdict(list)
    for record in records:
        grouped[record.payload_json].append(record)
    groups = [
        tuple(sorted(group, key=lambda item: item.proposal.proposal_id))
        for group in grouped.values()
    ]
    return tuple(sorted(groups, key=lambda group: group[0].proposal.proposal_id))


def _representative(group: Sequence[_ProposalRecord]) -> str:
    return min(item.proposal.proposal_id for item in group)


def _pair(
    group_a: Sequence[_ProposalRecord], group_b: Sequence[_ProposalRecord]
) -> tuple[str, str]:
    left, right = sorted((_representative(group_a), _representative(group_b)))
    return left, right


def _prompt_text() -> str:
    try:
        return _PROMPT_PATH.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise CanonicalizationError("family adjudication prompt is unavailable") from exc


def _adjudication_input(
    candidate_pairs: Sequence[tuple[tuple[_ProposalRecord, ...], tuple[_ProposalRecord, ...]]]
) -> str:
    comparisons: list[dict[str, object]] = []
    for left, right in candidate_pairs:
        comparisons.append(
            {
                "compared_proposal_ids": _pair(left, right),
                "left_group": _group_comparison_payload(left),
                "right_group": _group_comparison_payload(right),
            }
        )
    return (
        _prompt_text()
        + "\n\nBEGIN_FAMILY_COMPARISONS\n"
        + _canonical_json({"comparisons": comparisons})
        + "\nEND_FAMILY_COMPARISONS\n"
    )


def _group_comparison_payload(
    group: Sequence[_ProposalRecord],
) -> dict[str, object]:
    return {
        "proposal_ids": [item.proposal.proposal_id for item in group],
        "mechanistic_definition": _definition_payload(
            _normalized_definition(group[0].proposal.mechanistic_definition)
        ),
        "evidence_levels": sorted(
            {item.proposal.evidence_level for item in group}
        ),
        "evidence_ids": sorted(
            {
                evidence_id
                for item in group
                for evidence_id in item.proposal.evidence_ids
            }
        ),
        "proposal_evidence": [
            {
                "proposal_id": item.proposal.proposal_id,
                "evidence_level": item.proposal.evidence_level,
                "evidence_ids": sorted(set(item.proposal.evidence_ids)),
            }
            for item in group
        ],
        "disagreements": sorted(
            {
                text
                for item in group
                for text in item.proposal.counterarguments + item.proposal.unknowns
            }
        ),
    }


def _adjudicate(
    candidate_pairs: Sequence[tuple[tuple[_ProposalRecord, ...], tuple[_ProposalRecord, ...]]],
    adjudicator: StructuredClient,
) -> tuple[
    tuple[AdjudicationComparison, ...],
    tuple[
        tuple[
            tuple[tuple[_ProposalRecord, ...], tuple[_ProposalRecord, ...]],
            str,
        ],
        ...,
    ],
]:
    comparisons: list[AdjudicationComparison] = []
    unresolved: list[
        tuple[
            tuple[tuple[_ProposalRecord, ...], tuple[_ProposalRecord, ...]],
            str,
        ]
    ] = []
    for start in range(0, len(candidate_pairs), MAX_ADJUDICATION_BATCH_SIZE):
        batch = candidate_pairs[start : start + MAX_ADJUDICATION_BATCH_SIZE]
        input_text = _adjudication_input(batch)
        schema = strict_model_schema(FamilyAdjudicationPayload)
        comparison_schema = schema.get("$defs", {}).get(
            "AdjudicationComparison", {}
        )
        compared_ids_schema = comparison_schema.get("properties", {}).get(
            "compared_proposal_ids", {}
        )
        if isinstance(compared_ids_schema, dict):
            # Some OpenAI-compatible gateways reject JSON Schema's
            # ``prefixItems`` form unless the array also declares ``items``.
            # Pydantic emits prefixItems for tuple[str, str], so provide the
            # equivalent homogeneous item contract without relaxing length.
            compared_ids_schema["items"] = {"type": "string"}
            compared_ids_schema["minItems"] = 2
            compared_ids_schema["maxItems"] = 2
        try:
            result = adjudicator.create_structured(
                FAMILY_ADJUDICATION_MODEL,
                input_text,
                schema,
                FAMILY_ADJUDICATION_SCHEMA_NAME,
            )
        except ApiClientError as exc:
            reason = (
                "model_invocation_failed: "
                f"{exc.error_type or 'unknown_model_error'}."
            )
            unresolved.extend((pair, reason) for pair in batch)
            continue
        try:
            payload = FamilyAdjudicationPayload.model_validate(result.parsed_output)
        except (AttributeError, ValidationError):
            unresolved.extend(
                (
                    pair,
                    "structured_output_validation_failed: "
                    "adjudication response did not match the required schema.",
                )
                for pair in batch
            )
            continue
        expected = {_pair(left, right): (left, right) for left, right in batch}
        actual = {item.compared_proposal_ids for item in payload.comparisons}
        if not actual.issubset(expected):
            unresolved.extend(
                (
                    pair,
                    "structured_output_validation_failed: "
                    "adjudication response cited an unsubmitted comparison.",
                )
                for pair in batch
            )
            continue
        comparisons.extend(payload.comparisons)
        unresolved.extend(
            (
                expected[pair_id],
                "Adjudication batch omitted this submitted comparison.",
            )
            for pair_id in sorted(set(expected) - actual)
        )
    return (
        tuple(sorted(comparisons, key=lambda item: item.compared_proposal_ids)),
        tuple(sorted(unresolved, key=lambda item: _pair(*item[0]))),
    )


def _ordered_group_pair(
    left: tuple[_ProposalRecord, ...], right: tuple[_ProposalRecord, ...]
) -> tuple[tuple[_ProposalRecord, ...], tuple[_ProposalRecord, ...]]:
    if _representative(left) <= _representative(right):
        return left, right
    return right, left


def _protected_key(group: Sequence[_ProposalRecord]) -> tuple[str, str]:
    definition = _normalized_definition(group[0].proposal.mechanistic_definition)
    return (
        definition.reactive_state,
        definition.bond_forming_mode,
    )


def _mechanism_tokens(group: Sequence[_ProposalRecord]) -> frozenset[str]:
    definition = _normalized_definition(group[0].proposal.mechanistic_definition)
    text = " ".join(
        (
            definition.nucleophilic_center,
            definition.reactive_state,
            definition.bond_forming_mode,
            definition.activation_mode,
            *definition.critical_conditions,
            *definition.dominant_failure_modes,
        )
    )
    return frozenset(_TOKEN.findall(text))


def _cross_lane(left: Sequence[_ProposalRecord], right: Sequence[_ProposalRecord]) -> bool:
    left_lanes = {item.provenance.lane_id for item in left}
    right_lanes = {item.provenance.lane_id for item in right}
    return bool(left_lanes - right_lanes) and bool(right_lanes - left_lanes)


def _same_coordinate_assignment(
    left: Sequence[_ProposalRecord], right: Sequence[_ProposalRecord]
) -> bool:
    left_assignments = {
        item.proposal.coordinate_assignment
        for item in left
        if item.proposal.coordinate_assignment is not None
    }
    right_assignments = {
        item.proposal.coordinate_assignment
        for item in right
        if item.proposal.coordinate_assignment is not None
    }
    return bool(left_assignments & right_assignments)


def _mechanism_similarity(
    left: Sequence[_ProposalRecord], right: Sequence[_ProposalRecord]
) -> float:
    left_tokens = _mechanism_tokens(left)
    right_tokens = _mechanism_tokens(right)
    union = left_tokens | right_tokens
    return len(left_tokens & right_tokens) / len(union) if union else 0.0


def _candidate_plan(
    groups: Sequence[tuple[_ProposalRecord, ...]],
) -> tuple[
    tuple[tuple[tuple[_ProposalRecord, ...], tuple[_ProposalRecord, ...]], ...],
    tuple[tuple[tuple[_ProposalRecord, ...], tuple[_ProposalRecord, ...]], ...],
    tuple[tuple[tuple[_ProposalRecord, ...], tuple[_ProposalRecord, ...]], ...],
]:
    candidates: dict[
        tuple[str, str],
        tuple[tuple[_ProposalRecord, ...], tuple[_ProposalRecord, ...]],
    ] = {}
    distinct: dict[
        tuple[str, str],
        tuple[tuple[_ProposalRecord, ...], tuple[_ProposalRecord, ...]],
    ] = {}

    protected_blocks: dict[tuple[str, str], list[tuple[_ProposalRecord, ...]]] = (
        defaultdict(list)
    )
    for group in groups:
        key = _protected_key(group)
        protected_blocks[key].append(group)

    for block in protected_blocks.values():
        rows = sorted(block, key=_representative)
        for index, left in enumerate(rows):
            for right in rows[index + 1 :]:
                pair = _ordered_group_pair(left, right)
                candidates[_pair(*pair)] = pair

    block_keys = sorted(protected_blocks)
    paraphrase_candidates: list[
        tuple[
            float,
            tuple[str, str],
            tuple[tuple[_ProposalRecord, ...], tuple[_ProposalRecord, ...]],
        ]
    ] = []
    for index, left_key in enumerate(block_keys):
        left_rows = sorted(protected_blocks[left_key], key=_representative)
        for right_key in block_keys[index + 1 :]:
            right_rows = sorted(protected_blocks[right_key], key=_representative)
            for left in left_rows:
                for right in right_rows:
                    pair = _ordered_group_pair(left, right)
                    pair_id = _pair(*pair)
                    similarity = _mechanism_similarity(*pair)
                    if (
                        _cross_lane(*pair)
                        and similarity >= _PARAPHRASE_CANDIDATE_THRESHOLD
                    ):
                        paraphrase_candidates.append((similarity, pair_id, pair))
                    else:
                        distinct[pair_id] = pair

    for _, pair_id, pair in sorted(
        paraphrase_candidates, key=lambda item: (-item[0], item[1])
    ):
        candidates[pair_id] = pair
        distinct.pop(pair_id, None)

    exact_ids = {
        _pair(left, right)
        for block in protected_blocks.values()
        for index, left in enumerate(sorted(block, key=_representative))
        for right in sorted(block, key=_representative)[index + 1 :]
    }
    similarity_by_id = {
        pair_id: similarity
        for similarity, pair_id, _ in paraphrase_candidates
    }

    def priority(pair_id: tuple[str, str]) -> tuple[int, int, float, tuple[str, str]]:
        left, right = candidates[pair_id]
        return (
            0 if _same_coordinate_assignment(left, right) else 1,
            0 if _cross_lane(left, right) else 1,
            -similarity_by_id.get(pair_id, _mechanism_similarity(left, right)),
            pair_id,
        )

    ordered_candidate_ids = tuple(sorted(candidates, key=priority))
    ordered_candidates = tuple(candidates[key] for key in ordered_candidate_ids)
    capacity = MAX_ADJUDICATION_BATCH_SIZE * MAX_ADJUDICATION_CALLS
    selected = ordered_candidates[:capacity]
    overflow_pairs = ordered_candidates[capacity:]
    ordered_distinct = tuple(distinct[key] for key in sorted(distinct))
    return selected, ordered_distinct, overflow_pairs


def _comparison_judgments(
    comparison: AdjudicationComparison,
) -> tuple[ComparisonJudgment, ...]:
    return (
        comparison.same_mechanism,
        comparison.shared_scope,
        comparison.left_contains_right,
        comparison.right_contains_left,
        comparison.experimentally_distinguishable,
    )


def _qualified(
    judgment: ComparisonJudgment,
    state: Literal["support", "contradiction"],
    qualified_evidence_ids: frozenset[str],
) -> bool:
    return (
        judgment.state == state
        and bool(judgment.evidence_ids)
        and set(judgment.evidence_ids).issubset(qualified_evidence_ids)
    )


def _qualified_evidence_ids(
    left: Sequence[_ProposalRecord], right: Sequence[_ProposalRecord]
) -> frozenset[str]:
    return frozenset(
        evidence_id
        for group in (left, right)
        for item in group
        if item.proposal.evidence_level == "traceable_external_evidence"
        for evidence_id in item.proposal.evidence_ids
    )


def _map_comparison(
    comparison: AdjudicationComparison,
    left: tuple[_ProposalRecord, ...],
    right: tuple[_ProposalRecord, ...],
) -> _PendingDecision:
    qualified_ids = _qualified_evidence_ids(left, right)
    same = comparison.same_mechanism
    shared = comparison.shared_scope
    left_contains = comparison.left_contains_right
    right_contains = comparison.right_contains_left
    distinguishable = comparison.experimentally_distinguishable
    decision: CanonicalizationDecisionType = "unresolved"
    parent_proposal_id = None
    child_proposal_id = None
    rationale = "Comparison states are insufficient for deterministic resolution."

    if all(
        (
            _qualified(same, "support", qualified_ids),
            _qualified(shared, "support", qualified_ids),
            _qualified(distinguishable, "contradiction", qualified_ids),
        )
    ):
        decision = "merge"
        rationale = "Qualified comparison states establish mechanism equivalence."
    elif all(
        (
            _qualified(same, "contradiction", qualified_ids),
            _qualified(shared, "support", qualified_ids),
            _qualified(distinguishable, "support", qualified_ids),
            _qualified(left_contains, "support", qualified_ids),
            _qualified(right_contains, "contradiction", qualified_ids),
        )
    ):
        decision = "parent_child"
        parent_proposal_id, child_proposal_id = comparison.compared_proposal_ids
        rationale = "Qualified comparison states establish left-to-right scope containment."
    elif all(
        (
            _qualified(same, "contradiction", qualified_ids),
            _qualified(shared, "support", qualified_ids),
            _qualified(distinguishable, "support", qualified_ids),
            _qualified(left_contains, "contradiction", qualified_ids),
            _qualified(right_contains, "support", qualified_ids),
        )
    ):
        decision = "parent_child"
        child_proposal_id, parent_proposal_id = comparison.compared_proposal_ids
        rationale = "Qualified comparison states establish right-to-left scope containment."
    elif all(
        (
            _qualified(same, "contradiction", qualified_ids),
            _qualified(shared, "support", qualified_ids),
            _qualified(distinguishable, "support", qualified_ids),
            _qualified(left_contains, "contradiction", qualified_ids),
            _qualified(right_contains, "contradiction", qualified_ids),
        )
    ):
        decision = "split"
        rationale = "Qualified comparison states establish distinguishable sibling mechanisms."
    elif all(
        (
            _qualified(same, "contradiction", qualified_ids),
            _qualified(shared, "contradiction", qualified_ids),
            _qualified(distinguishable, "support", qualified_ids),
            _qualified(left_contains, "contradiction", qualified_ids),
            _qualified(right_contains, "contradiction", qualified_ids),
        )
    ):
        decision = "distinct"
        rationale = "Qualified comparison states establish separate mechanistic scopes."

    cited_qualified_ids = tuple(
        sorted(
            {
                evidence_id
                for judgment in _comparison_judgments(comparison)
                for evidence_id in judgment.evidence_ids
                if evidence_id in qualified_ids
            }
        )
    )
    disagreements: tuple[str, ...] = ()
    if decision == "unresolved":
        disagreements = tuple(
            sorted(
                set(comparison.uncertainties)
                | {"Comparison lacks a complete set of qualified evidence states."}
            )
        )
    return _PendingDecision(
        compared_proposal_ids=comparison.compared_proposal_ids,
        decision=decision,
        rationale=rationale,
        source="deterministic",
        evidence_ids=cited_qualified_ids,
        unresolved_disagreements=disagreements,
        parent_proposal_id=parent_proposal_id,
        child_proposal_id=child_proposal_id,
    )


def _unresolved_pair(
    left: tuple[_ProposalRecord, ...],
    right: tuple[_ProposalRecord, ...],
    reason: str,
) -> _PendingDecision:
    return _PendingDecision(
        compared_proposal_ids=_pair(left, right),
        decision="unresolved",
        rationale=reason,
        source="deterministic",
        unresolved_disagreements=(reason,),
    )


def _pending_decisions(
    groups: Sequence[tuple[_ProposalRecord, ...]],
    adjudicator: StructuredClient | None,
) -> tuple[_PendingDecision, ...]:
    pending: list[_PendingDecision] = []
    for group in groups:
        proposal_ids = tuple(item.proposal.proposal_id for item in group)
        if len(group) > 1:
            pending.append(
                _PendingDecision(
                    compared_proposal_ids=proposal_ids,
                    decision="merge",
                    rationale="Exact normalized six-field mechanism definitions match.",
                    source="deterministic",
                )
            )
    candidates, distinct_pairs, overflow_pairs = _candidate_plan(groups)
    for left, right in distinct_pairs:
        if adjudicator is None:
            pending.append(
                _PendingDecision(
                    compared_proposal_ids=_pair(left, right),
                    decision="distinct",
                    rationale=(
                        "Reactive state or bond-forming mode differs; names cannot "
                        "override a mechanistic distinction."
                    ),
                    source="deterministic",
                )
            )
        else:
            pending.append(
                _unresolved_pair(
                    left,
                    right,
                    "Pair was outside the bounded paraphrase-adjudication candidate set.",
                )
            )
    if candidates and adjudicator is None:
        for left, right in candidates + overflow_pairs:
            pending.append(
                _unresolved_pair(
                    left,
                    right,
                    "Non-identical mechanism definitions require adjudication.",
                )
            )
    elif candidates:
        pairs_by_id = {_pair(left, right): (left, right) for left, right in candidates}
        comparisons, failed_pairs = _adjudicate(candidates, adjudicator)
        for item in comparisons:
            left, right = pairs_by_id[item.compared_proposal_ids]
            pending.append(_map_comparison(item, left, right))
        for (left, right), reason in failed_pairs:
            pending.append(_unresolved_pair(left, right, reason))
    if adjudicator is not None:
        for left, right in overflow_pairs:
            pending.append(
                _unresolved_pair(
                    left,
                    right,
                    "Comparison exceeded the bounded adjudication call limit.",
                )
            )
    for group in groups:
        for record in group:
            disagreements = tuple(
                sorted(
                    set(record.proposal.counterarguments)
                    | set(record.proposal.unknowns)
                )
            )
            if disagreements:
                pending.append(
                    _PendingDecision(
                        compared_proposal_ids=(record.proposal.proposal_id,),
                        decision="unresolved",
                        rationale=(
                            "The originating proposal records unresolved questions "
                            "or counterarguments."
                        ),
                        source="deterministic",
                        unresolved_disagreements=disagreements,
                    )
                )
    return tuple(
        sorted(
            pending,
            key=lambda item: (
                _DECISION_ORDER[item.decision],
                item.compared_proposal_ids,
                item.source,
                item.rationale,
            ),
        )
    )


def _merged_records(
    records: Sequence[_ProposalRecord], decisions: Sequence[_PendingDecision]
) -> tuple[tuple[_ProposalRecord, ...], ...]:
    union = _UnionFind(tuple(item.proposal.proposal_id for item in records))
    for decision in decisions:
        if decision.decision == "merge":
            anchor = decision.compared_proposal_ids[0]
            for proposal_id in decision.compared_proposal_ids[1:]:
                union.union(anchor, proposal_id)
    for decision in decisions:
        if decision.decision in {"split", "distinct", "parent_child"}:
            left, right = decision.compared_proposal_ids
            if union.find(left) == union.find(right):
                raise CanonicalizationError(
                    "adjudication contains contradictory merge and separation decisions"
                )
    grouped: dict[str, list[_ProposalRecord]] = defaultdict(list)
    for record in records:
        grouped[union.find(record.proposal.proposal_id)].append(record)
    merged = [
        tuple(sorted(group, key=lambda item: item.proposal.proposal_id))
        for group in grouped.values()
    ]
    return tuple(sorted(merged, key=lambda group: group[0].proposal.proposal_id))


def _family_ids_by_proposal(
    groups: Sequence[tuple[_ProposalRecord, ...]],
) -> tuple[dict[str, str], dict[str, str]]:
    proposal_to_family: dict[str, str] = {}
    family_to_payload: dict[str, str] = {}
    for group in groups:
        canonical_payload = min(item.payload_json for item in group)
        family_id = _family_id(canonical_payload)
        previous_payload = family_to_payload.get(family_id)
        if previous_payload is not None and previous_payload != canonical_payload:
            raise CanonicalizationError("canonical family ID digest collision")
        family_to_payload[family_id] = canonical_payload
        for record in group:
            proposal_to_family[record.proposal.proposal_id] = family_id
    return proposal_to_family, family_to_payload


def _relations(
    decisions: Sequence[_PendingDecision], proposal_to_family: Mapping[str, str]
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    parents: dict[str, set[str]] = defaultdict(set)
    children: dict[str, set[str]] = defaultdict(set)
    for decision in decisions:
        if decision.decision != "parent_child":
            continue
        assert decision.parent_proposal_id is not None
        assert decision.child_proposal_id is not None
        parent_id = proposal_to_family[decision.parent_proposal_id]
        child_id = proposal_to_family[decision.child_proposal_id]
        if parent_id == child_id:
            raise CanonicalizationError("parent and child proposals merged into one family")
        parents[child_id].add(parent_id)
        children[parent_id].add(child_id)
    return parents, children


def _canonical_family(
    records: Sequence[_ProposalRecord],
    family_id: str,
    canonical_payload: str,
    parents: Mapping[str, set[str]],
    children: Mapping[str, set[str]],
    decision_disagreements: Mapping[str, set[str]],
) -> CanonicalFamily:
    payload = json.loads(canonical_payload)
    proposal_ids = tuple(item.proposal.proposal_id for item in records)
    disagreements = tuple(
        sorted(
            {
                text
                for item in records
                for text in (
                    item.proposal.counterarguments
                    + item.proposal.unknowns
                    + tuple(decision_disagreements.get(item.proposal.proposal_id, set()))
                )
            }
        )
    )
    candidates_by_payload = {
        item.payload_json: _normalized_definition(item.proposal.mechanistic_definition)
        for item in records
    }
    return CanonicalFamily(
        family_id=family_id,
        **payload,
        proposal_ids=proposal_ids,
        proposal_provenance=tuple(item.provenance for item in records),
        evidence_ids=tuple(
            sorted(
                {
                    evidence_id
                    for item in records
                    for evidence_id in item.proposal.evidence_ids
                }
            )
        ),
        aliases=tuple(sorted({item.proposal.parent_hypothesis for item in records})),
        unresolved_disagreements=disagreements,
        parent_family_ids=tuple(sorted(parents.get(family_id, set()))),
        child_family_ids=tuple(sorted(children.get(family_id, set()))),
        representative_reactive_state_candidates=tuple(
            sorted({item.proposal.representative_reactive_state for item in records})
        ),
        mechanistic_definition_candidates=tuple(
            candidates_by_payload[key] for key in sorted(candidates_by_payload)
        ),
        coordinate_assignments=tuple(
            sorted(
                {
                    item.proposal.coordinate_assignment
                    for item in records
                    if item.proposal.coordinate_assignment is not None
                },
                key=lambda assignment: _canonical_json(
                    assignment.model_dump(mode="json")
                ),
            )
        ),
    )


def _canonical_decision(
    decision: _PendingDecision, proposal_to_family: Mapping[str, str]
) -> CanonicalizationDecision:
    family_ids = tuple(
        sorted({proposal_to_family[item] for item in decision.compared_proposal_ids})
    )
    parent_family_id = None
    child_family_id = None
    if decision.decision == "parent_child":
        assert decision.parent_proposal_id is not None
        assert decision.child_proposal_id is not None
        parent_family_id = proposal_to_family[decision.parent_proposal_id]
        child_family_id = proposal_to_family[decision.child_proposal_id]
    return CanonicalizationDecision(
        compared_proposal_ids=decision.compared_proposal_ids,
        decision=decision.decision,
        family_ids=family_ids,
        parent_family_id=parent_family_id,
        child_family_id=child_family_id,
        rationale=decision.rationale,
        source=decision.source,
        evidence_ids=decision.evidence_ids,
        unresolved_disagreements=decision.unresolved_disagreements,
    )


def canonicalize_proposals(
    results: Sequence[TaxonomyLaneResult],
    adjudicator: StructuredClient | None,
) -> CanonicalTaxonomy:
    """Canonicalize validated round proposals without dropping any proposal."""

    records = _validated_records(tuple(results))
    if not records:
        return CanonicalTaxonomy(
            families=(), decisions=(), unresolved_proposal_ids=()
        )
    exact_groups = _group_records(records)
    pending = _pending_decisions(exact_groups, adjudicator)
    merged_groups = _merged_records(records, pending)
    proposal_to_family, family_to_payload = _family_ids_by_proposal(merged_groups)
    parents, children = _relations(pending, proposal_to_family)
    decision_disagreements: dict[str, set[str]] = defaultdict(set)
    for decision in pending:
        for proposal_id in decision.compared_proposal_ids:
            decision_disagreements[proposal_id].update(
                decision.unresolved_disagreements
            )
    families = tuple(
        sorted(
            (
                _canonical_family(
                    group,
                    proposal_to_family[group[0].proposal.proposal_id],
                    family_to_payload[proposal_to_family[group[0].proposal.proposal_id]],
                    parents,
                    children,
                    decision_disagreements,
                )
                for group in merged_groups
            ),
            key=lambda family: family.family_id,
        )
    )
    decisions = tuple(
        sorted(
            (_canonical_decision(item, proposal_to_family) for item in pending),
            key=lambda item: (
                _DECISION_ORDER[item.decision],
                item.compared_proposal_ids,
                item.source,
                item.family_ids,
            ),
        )
    )
    unresolved = tuple(
        sorted(
            {
                proposal_id
                for decision in pending
                if decision.decision == "unresolved"
                or decision.unresolved_disagreements
                for proposal_id in decision.compared_proposal_ids
            }
        )
    )
    return CanonicalTaxonomy(
        families=families,
        decisions=decisions,
        unresolved_proposal_ids=unresolved,
    )

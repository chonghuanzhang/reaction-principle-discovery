"""Deterministic cross-round consolidation for answer-isolated v3 proposals."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Literal

from pydantic import Field, model_validator

from pipeline.principle_models import FrozenStrictModel
from pipeline.taxonomy_discovery import (
    DiscoveryChannel,
    MechanismCoordinateAssignment,
    TaxonomyProposal,
)
from pipeline.v3_models import EvidenceLevel


MergeDecision = Literal["merge", "unresolved"]
_SPACE = re.compile(r"\s+")
_TOKEN = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "at",
        "by",
        "for",
        "from",
        "in",
        "of",
        "on",
        "or",
        "the",
        "then",
        "to",
        "with",
        "followed",
        "formation",
        "formed",
    }
)
_COORDINATE_FIELDS = tuple(MechanismCoordinateAssignment.model_fields)


class ConsolidationError(ValueError):
    """Raised when the consolidation contract cannot be satisfied."""


class ConsolidationPolicy(FrozenStrictModel):
    version: Literal["3.4", "3.4.1"]
    source_version: Literal["3.3", "3.6"]
    maximum_new_family_rate: float = Field(ge=0, le=1)
    required_consecutive_low_novelty_transitions: int = Field(ge=1)
    minimum_independent_lanes: int = Field(ge=2)
    minimum_core_token_jaccard: float = Field(ge=0, le=1)
    minimum_context_token_jaccard: float = Field(ge=0, le=1)
    qualifying_evidence_prefixes: tuple[str, ...] = Field(min_length=1)
    model_only_merge_policy: Literal["exact_fingerprint_only"]
    cross_coordinate_policy: Literal["prohibited"]
    unresolved_policy: Literal["preserve"]

    @model_validator(mode="after")
    def validate_prefixes(self) -> "ConsolidationPolicy":
        if len(self.qualifying_evidence_prefixes) != len(
            set(self.qualifying_evidence_prefixes)
        ):
            raise ValueError("qualifying evidence prefixes must be unique")
        if any(not prefix.strip() for prefix in self.qualifying_evidence_prefixes):
            raise ValueError("qualifying evidence prefixes cannot be empty")
        return self


class EvidenceFingerprint(FrozenStrictModel):
    proposal_id: str = Field(min_length=1)
    lane_id: str = Field(min_length=1)
    round_id: int = Field(ge=1)
    channel: DiscoveryChannel
    evidence_level: EvidenceLevel
    evidence_ids: tuple[str, ...]
    coordinate: MechanismCoordinateAssignment
    exact_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    core_tokens: frozenset[str]
    context_tokens: frozenset[str]
    normalized_assertions: tuple[tuple[str, tuple[str, ...]], ...]


class CrossRoundDecision(FrozenStrictModel):
    compared_proposal_ids: tuple[str, str]
    decision: MergeDecision
    rule_id: Literal[
        "exact_fingerprint",
        "evidence_supported_paraphrase",
        "inherited_v3_3_qualified_merge",
        "insufficient_merge_evidence",
    ]
    shared_qualifying_evidence_ids: tuple[str, ...] = ()
    core_token_jaccard: float = Field(ge=0, le=1)
    context_token_jaccard: float = Field(ge=0, le=1)
    rationale: str = Field(min_length=1)


class CrossRoundFamily(FrozenStrictModel):
    family_id: str = Field(pattern=r"^NFV34-[0-9a-f]{12}$")
    coordinate: MechanismCoordinateAssignment
    representative_proposal_id: str = Field(min_length=1)
    representative_exact_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    member_proposal_ids: tuple[str, ...] = Field(min_length=1)
    round_ids: tuple[int, ...] = Field(min_length=1)
    lane_ids: tuple[str, ...] = Field(min_length=1)
    channels: tuple[DiscoveryChannel, ...] = Field(min_length=1)
    evidence_ids: tuple[str, ...]
    evidence_bearing: bool


class PrefixMetrics(FrozenStrictModel):
    round_id: int = Field(ge=1)
    proposal_count: int = Field(ge=1)
    family_count: int = Field(ge=1)
    new_family_count: int = Field(ge=0)
    new_family_rate: float = Field(ge=0, le=1)
    coordinate_count: int = Field(ge=1)
    multi_lane_family_fraction: float = Field(ge=0, le=1)
    unresolved_pair_count: int = Field(ge=0)


class CrossRoundConsolidation(FrozenStrictModel):
    version: Literal["3.4", "3.4.1"]
    source_version: Literal["3.3", "3.6"]
    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    proposal_count: int = Field(ge=1)
    families: tuple[CrossRoundFamily, ...] = Field(min_length=1)
    decisions: tuple[CrossRoundDecision, ...]
    prefix_metrics: tuple[PrefixMetrics, ...] = Field(min_length=1)
    consecutive_low_novelty_transitions: int = Field(ge=0)
    coordinate_coverage_stable: bool
    evidence_bearing_lane_converged: bool
    consolidation_converged: bool
    freeze_2_allowed: bool
    freeze_2_blockers: tuple[str, ...]

    @model_validator(mode="after")
    def preserve_every_proposal_once(self) -> "CrossRoundConsolidation":
        members = tuple(
            proposal_id
            for family in self.families
            for proposal_id in family.member_proposal_ids
        )
        if len(members) != self.proposal_count or len(members) != len(set(members)):
            raise ValueError("every proposal must occur in exactly one cross-round family")
        return self


def _normalize(value: str) -> str:
    return _SPACE.sub(" ", unicodedata.normalize("NFKC", value).strip()).casefold()


def _normalized_values(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(sorted({_normalize(value) for value in values}))


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _coordinate_key(
    coordinate: MechanismCoordinateAssignment,
) -> tuple[str, str, str, str, str, str]:
    return tuple(getattr(coordinate, field) for field in _COORDINATE_FIELDS)  # type: ignore[return-value]


def _field_tokens(field: str, values: Sequence[str]) -> frozenset[str]:
    return frozenset(
        f"{field}:{token}"
        for value in values
        for token in _TOKEN.findall(value)
        if token not in _STOPWORDS
    )


def fingerprint_proposal(
    proposal: TaxonomyProposal,
    *,
    lane_id: str,
    round_id: int,
    channel: DiscoveryChannel,
) -> EvidenceFingerprint:
    """Build a provenance-bearing chemical fingerprint for one raw proposal."""

    if type(proposal) is not TaxonomyProposal:
        raise TypeError("proposal must be the exact TaxonomyProposal type")
    if proposal.coordinate_assignment is None:
        raise ConsolidationError(
            f"proposal {proposal.proposal_id} lacks a complete coordinate assignment"
        )
    if proposal.source_channel != channel:
        raise ConsolidationError(
            f"proposal {proposal.proposal_id} channel does not match its lane result"
        )
    definition = proposal.mechanistic_definition
    fields: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("nucleophilic_center", (_normalize(definition.nucleophilic_center),)),
        ("reactive_state", (_normalize(definition.reactive_state),)),
        ("bond_forming_mode", (_normalize(definition.bond_forming_mode),)),
        ("activation_mode", (_normalize(definition.activation_mode),)),
        (
            "representative_reactive_state",
            (_normalize(proposal.representative_reactive_state),),
        ),
        ("parent_hypothesis", (_normalize(proposal.parent_hypothesis),)),
        ("critical_conditions", _normalized_values(definition.critical_conditions)),
        (
            "dominant_failure_modes",
            _normalized_values(definition.dominant_failure_modes),
        ),
    )
    core_fields = fields[:6]
    context_fields = fields[6:]
    core_tokens = frozenset().union(
        *(_field_tokens(field, values) for field, values in core_fields)
    )
    context_tokens = frozenset().union(
        *(_field_tokens(field, values) for field, values in context_fields)
    )
    exact_payload = {
        "coordinate": proposal.coordinate_assignment.model_dump(mode="json"),
        "assertions": fields,
    }
    exact_fingerprint = hashlib.sha256(
        _canonical_json(exact_payload).encode("utf-8")
    ).hexdigest()
    return EvidenceFingerprint(
        proposal_id=proposal.proposal_id,
        lane_id=lane_id,
        round_id=round_id,
        channel=channel,
        evidence_level=proposal.evidence_level,
        evidence_ids=tuple(sorted(set(proposal.evidence_ids))),
        coordinate=proposal.coordinate_assignment,
        exact_fingerprint=exact_fingerprint,
        core_tokens=core_tokens,
        context_tokens=context_tokens,
        normalized_assertions=fields,
    )


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 1.0


def _qualifying_evidence(
    fingerprint: EvidenceFingerprint, policy: ConsolidationPolicy
) -> frozenset[str]:
    return frozenset(
        evidence_id
        for evidence_id in fingerprint.evidence_ids
        if any(
            evidence_id.startswith(prefix)
            for prefix in policy.qualifying_evidence_prefixes
        )
    )


def compare_fingerprints(
    left: EvidenceFingerprint,
    right: EvidenceFingerprint,
    policy: ConsolidationPolicy,
) -> CrossRoundDecision | None:
    """Return a conservative pair decision inside one exact coordinate."""

    if _coordinate_key(left.coordinate) != _coordinate_key(right.coordinate):
        return None
    ids = tuple(sorted((left.proposal_id, right.proposal_id)))
    core_similarity = _jaccard(left.core_tokens, right.core_tokens)
    context_similarity = _jaccard(left.context_tokens, right.context_tokens)
    shared = tuple(
        sorted(
            _qualifying_evidence(left, policy)
            & _qualifying_evidence(right, policy)
        )
    )
    if left.exact_fingerprint == right.exact_fingerprint:
        return CrossRoundDecision(
            compared_proposal_ids=ids,
            decision="merge",
            rule_id="exact_fingerprint",
            shared_qualifying_evidence_ids=shared,
            core_token_jaccard=core_similarity,
            context_token_jaccard=context_similarity,
            rationale="Complete coordinate and normalized chemical assertions match exactly.",
        )
    external_pair = all(
        item.evidence_level == "traceable_external_evidence"
        for item in (left, right)
    )
    if (
        external_pair
        and shared
        and core_similarity >= policy.minimum_core_token_jaccard
        and context_similarity >= policy.minimum_context_token_jaccard
    ):
        return CrossRoundDecision(
            compared_proposal_ids=ids,
            decision="merge",
            rule_id="evidence_supported_paraphrase",
            shared_qualifying_evidence_ids=shared,
            core_token_jaccard=core_similarity,
            context_token_jaccard=context_similarity,
            rationale=(
                "Same complete coordinate, compatible chemical assertions, and shared "
                "qualifying external evidence support a paraphrase merge."
            ),
        )
    return CrossRoundDecision(
        compared_proposal_ids=ids,
        decision="unresolved",
        rule_id="insufficient_merge_evidence",
        shared_qualifying_evidence_ids=shared,
        core_token_jaccard=core_similarity,
        context_token_jaccard=context_similarity,
        rationale=(
            "The pair does not satisfy the preregistered evidence and chemical-field "
            "requirements for merging."
        ),
    )


def _stable_family_id(representative: EvidenceFingerprint) -> str:
    payload = _canonical_json(
        {
            "coordinate": representative.coordinate.model_dump(mode="json"),
            "representative_exact_fingerprint": representative.exact_fingerprint,
        }
    )
    return "NFV34-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def _cluster_partition(
    fingerprints: Sequence[EvidenceFingerprint],
    policy: ConsolidationPolicy,
    inherited_merge_pairs: Mapping[tuple[str, str], tuple[str, ...]],
) -> tuple[tuple[tuple[EvidenceFingerprint, ...], ...], tuple[CrossRoundDecision, ...]]:
    decisions: dict[tuple[str, str], CrossRoundDecision] = {}

    def decision(left: EvidenceFingerprint, right: EvidenceFingerprint) -> CrossRoundDecision:
        ids = tuple(sorted((left.proposal_id, right.proposal_id)))
        if ids not in decisions:
            inherited_evidence = inherited_merge_pairs.get(ids)
            compared = (
                CrossRoundDecision(
                    compared_proposal_ids=ids,
                    decision="merge",
                    rule_id="inherited_v3_3_qualified_merge",
                    shared_qualifying_evidence_ids=inherited_evidence,
                    core_token_jaccard=_jaccard(left.core_tokens, right.core_tokens),
                    context_token_jaccard=_jaccard(
                        left.context_tokens, right.context_tokens
                    ),
                    rationale=(
                        "A public deterministic v3.3 decision with qualifying external "
                        "evidence established this same-coordinate merge."
                    ),
                )
                if inherited_evidence is not None
                else compare_fingerprints(left, right, policy)
            )
            if compared is None:
                raise ConsolidationError("cross-coordinate comparison entered a partition")
            decisions[ids] = compared
        return decisions[ids]

    by_id = {item.proposal_id: item for item in fingerprints}
    parent = {proposal_id: proposal_id for proposal_id in by_id}

    def find(proposal_id: str) -> str:
        if parent[proposal_id] != proposal_id:
            parent[proposal_id] = find(parent[proposal_id])
        return parent[proposal_id]

    def union(left_id: str, right_id: str) -> None:
        left_root, right_root = find(left_id), find(right_id)
        if left_root == right_root:
            return
        keep, merge = sorted((left_root, right_root))
        parent[merge] = keep

    for left_id, right_id in inherited_merge_pairs:
        union(left_id, right_id)
    atomic: dict[str, list[EvidenceFingerprint]] = defaultdict(list)
    for fingerprint in fingerprints:
        atomic[find(fingerprint.proposal_id)].append(fingerprint)
    components = sorted(
        (
            sorted(values, key=lambda item: (item.round_id, item.proposal_id))
            for values in atomic.values()
        ),
        key=lambda values: (values[0].round_id, values[0].proposal_id),
    )
    clusters: list[list[EvidenceFingerprint]] = []
    for component in components:
        matching_cluster = next(
            (
                cluster
                for cluster in clusters
                if all(
                    decision(fingerprint, member).decision == "merge"
                    for fingerprint in component
                    for member in cluster
                )
            ),
            None,
        )
        if matching_cluster is None:
            clusters.append(list(component))
        else:
            matching_cluster.extend(component)
    # Record every same-coordinate pair so unresolved comparisons remain auditable.
    ordered = sorted(fingerprints, key=lambda item: (item.round_id, item.proposal_id))
    for index, left in enumerate(ordered):
        for right in ordered[index + 1 :]:
            decision(left, right)
    return (
        tuple(tuple(cluster) for cluster in clusters),
        tuple(decisions[key] for key in sorted(decisions)),
    )


def _families_and_decisions(
    fingerprints: Sequence[EvidenceFingerprint],
    policy: ConsolidationPolicy,
    inherited_merge_pairs: Mapping[tuple[str, str], tuple[str, ...]],
) -> tuple[tuple[CrossRoundFamily, ...], tuple[CrossRoundDecision, ...]]:
    partitions: dict[
        tuple[str, str, str, str, str, str], list[EvidenceFingerprint]
    ] = defaultdict(list)
    for fingerprint in fingerprints:
        partitions[_coordinate_key(fingerprint.coordinate)].append(fingerprint)
    families: list[CrossRoundFamily] = []
    decisions: list[CrossRoundDecision] = []
    for coordinate_key in sorted(partitions):
        partition_ids = {item.proposal_id for item in partitions[coordinate_key]}
        partition_inherited = {
            pair: evidence_ids
            for pair, evidence_ids in inherited_merge_pairs.items()
            if set(pair).issubset(partition_ids)
        }
        clusters, partition_decisions = _cluster_partition(
            partitions[coordinate_key], policy, partition_inherited
        )
        decisions.extend(partition_decisions)
        for cluster in clusters:
            ordered = tuple(
                sorted(cluster, key=lambda item: (item.round_id, item.proposal_id))
            )
            representative = ordered[0]
            evidence_ids = tuple(
                sorted({value for item in ordered for value in item.evidence_ids})
            )
            families.append(
                CrossRoundFamily(
                    family_id=_stable_family_id(representative),
                    coordinate=representative.coordinate,
                    representative_proposal_id=representative.proposal_id,
                    representative_exact_fingerprint=representative.exact_fingerprint,
                    member_proposal_ids=tuple(item.proposal_id for item in ordered),
                    round_ids=tuple(sorted({item.round_id for item in ordered})),
                    lane_ids=tuple(sorted({item.lane_id for item in ordered})),
                    channels=tuple(sorted({item.channel for item in ordered})),
                    evidence_ids=evidence_ids,
                    evidence_bearing=any(
                        item.evidence_level == "traceable_external_evidence"
                        and bool(item.evidence_ids)
                        for item in ordered
                    ),
                )
            )
    return (
        tuple(sorted(families, key=lambda item: item.family_id)),
        tuple(sorted(decisions, key=lambda item: item.compared_proposal_ids)),
    )


def _prefix_metrics(
    fingerprints: Sequence[EvidenceFingerprint],
    policy: ConsolidationPolicy,
    inherited_merge_pairs: Mapping[tuple[str, str], tuple[str, ...]],
) -> tuple[PrefixMetrics, ...]:
    metrics: list[PrefixMetrics] = []
    previous_ids: set[str] = set()
    for round_id in sorted({item.round_id for item in fingerprints}):
        prefix = tuple(item for item in fingerprints if item.round_id <= round_id)
        prefix_ids = {item.proposal_id for item in prefix}
        prefix_inherited = {
            pair: evidence_ids
            for pair, evidence_ids in inherited_merge_pairs.items()
            if set(pair).issubset(prefix_ids)
        }
        families, decisions = _families_and_decisions(
            prefix, policy, prefix_inherited
        )
        family_ids = {item.family_id for item in families}
        new_ids = family_ids - previous_ids
        metrics.append(
            PrefixMetrics(
                round_id=round_id,
                proposal_count=len(prefix),
                family_count=len(families),
                new_family_count=len(new_ids),
                new_family_rate=len(new_ids) / len(families),
                coordinate_count=len({_coordinate_key(item.coordinate) for item in prefix}),
                multi_lane_family_fraction=(
                    sum(len(item.lane_ids) >= policy.minimum_independent_lanes for item in families)
                    / len(families)
                ),
                unresolved_pair_count=sum(
                    item.decision == "unresolved" for item in decisions
                ),
            )
        )
        previous_ids = family_ids
    return tuple(metrics)


def consolidate_fingerprints(
    fingerprints: Sequence[EvidenceFingerprint],
    policy: ConsolidationPolicy,
    *,
    source_digest: str,
    policy_digest: str,
    inherited_freeze_2_blockers: Sequence[str] = (),
    inherited_merge_pairs: Mapping[tuple[str, str], Sequence[str]] | None = None,
) -> CrossRoundConsolidation:
    """Consolidate ordered proposal fingerprints without model adjudication."""

    if not fingerprints:
        raise ConsolidationError("at least one fingerprint is required")
    ids = tuple(item.proposal_id for item in fingerprints)
    if len(ids) != len(set(ids)):
        raise ConsolidationError("proposal IDs must be unique across rounds")
    by_id = {item.proposal_id: item for item in fingerprints}
    normalized_inherited: dict[tuple[str, str], tuple[str, ...]] = {}
    for raw_pair, raw_evidence_ids in (inherited_merge_pairs or {}).items():
        pair = tuple(sorted(raw_pair))
        if len(pair) != 2 or len(set(pair)) != 2 or not set(pair).issubset(by_id):
            raise ConsolidationError("inherited merge cites unknown or duplicate proposals")
        if _coordinate_key(by_id[pair[0]].coordinate) != _coordinate_key(
            by_id[pair[1]].coordinate
        ):
            raise ConsolidationError("cross-coordinate inherited merge is prohibited")
        evidence_ids = tuple(sorted(set(raw_evidence_ids)))
        if not evidence_ids or any(
            not any(value.startswith(prefix) for prefix in policy.qualifying_evidence_prefixes)
            for value in evidence_ids
        ):
            raise ConsolidationError(
                "inherited merge requires qualifying external evidence IDs"
            )
        normalized_inherited[pair] = evidence_ids
    families, decisions = _families_and_decisions(
        fingerprints, policy, normalized_inherited
    )
    metrics = _prefix_metrics(fingerprints, policy, normalized_inherited)
    consecutive = 0
    for metric in reversed(metrics[1:]):
        if metric.new_family_rate > policy.maximum_new_family_rate:
            break
        consecutive += 1
    coordinate_stable = len(metrics) >= 2 and (
        metrics[-1].coordinate_count == metrics[-2].coordinate_count
    )
    evidence_lane_converged = all(
        not family.evidence_bearing
        or len(family.lane_ids) >= policy.minimum_independent_lanes
        for family in families
    )
    consolidation_converged = all(
        (
            consecutive >= policy.required_consecutive_low_novelty_transitions,
            coordinate_stable,
            evidence_lane_converged,
        )
    )
    blockers = list(dict.fromkeys(inherited_freeze_2_blockers))
    if not consolidation_converged:
        blockers.append("cross_round_consolidation_not_converged")
    return CrossRoundConsolidation(
        version=policy.version,
        source_version=policy.source_version,
        source_digest=source_digest,
        policy_digest=policy_digest,
        proposal_count=len(fingerprints),
        families=families,
        decisions=decisions,
        prefix_metrics=metrics,
        consecutive_low_novelty_transitions=consecutive,
        coordinate_coverage_stable=coordinate_stable,
        evidence_bearing_lane_converged=evidence_lane_converged,
        consolidation_converged=consolidation_converged,
        freeze_2_allowed=consolidation_converged and not blockers,
        freeze_2_blockers=tuple(blockers),
    )

"""Answer-isolated evidence triage for unresolved v3.4.1 comparisons."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
import hashlib
import json
from itertools import combinations
from typing import Literal

from pydantic import Field, model_validator

from pipeline.cross_round_consolidation import (
    CrossRoundConsolidation,
    EvidenceFingerprint,
)
from pipeline.principle_models import FrozenStrictModel
from pipeline.principle_models import TransferabilityAssessment
from pipeline.taxonomy_discovery import (
    DiscoveryChannel,
    MechanismCoordinateAssignment,
    MechanisticProposalDefinition,
    TaxonomyProposal,
)
from pipeline.v3_models import JudgmentState


TriageClass = Literal[
    "shared_external_evidence",
    "text_compatible_evidence_gap",
    "insufficient_linkage",
]
MechanisticField = Literal[
    "nucleophilic_center",
    "reactive_state",
    "bond_forming_mode",
    "activation_mode",
    "critical_conditions",
    "dominant_failure_modes",
]
LaneOutcome = Literal[
    "same_mechanism_supported",
    "different_mechanism_supported",
    "parent_child_granularity",
    "unresolved",
    "platform_or_validation_failure",
]
ConsensusDisposition = Literal[
    "consensus_merge_candidate",
    "evidence_supported_distinct_candidate",
    "parent_child_candidate",
    "unresolved",
]
_MECHANISTIC_FIELDS: tuple[MechanisticField, ...] = (
    "nucleophilic_center",
    "reactive_state",
    "bond_forming_mode",
    "activation_mode",
    "critical_conditions",
    "dominant_failure_modes",
)


class ComparisonAdjudicationError(ValueError):
    """Raised when comparison review inputs violate the frozen contract."""


class ComparisonTriagePolicy(FrozenStrictModel):
    version: Literal["3.5"]
    source_version: Literal["3.4.1"]
    minimum_core_token_jaccard: float = Field(ge=0, le=1)
    minimum_context_token_jaccard: float = Field(ge=0, le=1)
    qualifying_evidence_prefixes: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_prefixes(self) -> "ComparisonTriagePolicy":
        if len(self.qualifying_evidence_prefixes) != len(
            set(self.qualifying_evidence_prefixes)
        ) or any(not value.strip() for value in self.qualifying_evidence_prefixes):
            raise ValueError("qualifying evidence prefixes must be unique and non-empty")
        return self


class ComparisonTriageRecord(FrozenStrictModel):
    compared_proposal_ids: tuple[str, str]
    triage_class: TriageClass
    shared_qualifying_evidence_ids: tuple[str, ...]
    core_token_jaccard: float = Field(ge=0, le=1)
    context_token_jaccard: float = Field(ge=0, le=1)
    threshold_coverage_ratio: float = Field(ge=0)
    cross_lane: bool

    @model_validator(mode="after")
    def validate_pair(self) -> "ComparisonTriageRecord":
        if tuple(sorted(set(self.compared_proposal_ids))) != self.compared_proposal_ids:
            raise ValueError("triage proposal pair must contain two sorted unique IDs")
        return self


class ComparisonTriage(FrozenStrictModel):
    version: Literal["3.5"]
    source_version: Literal["3.4.1"]
    records: tuple[ComparisonTriageRecord, ...]
    counts: dict[TriageClass, int]
    review_queue: tuple[tuple[str, str], ...]

    @model_validator(mode="after")
    def validate_exhaustive_records(self) -> "ComparisonTriage":
        pairs = tuple(item.compared_proposal_ids for item in self.records)
        if len(pairs) != len(set(pairs)):
            raise ValueError("triage records must contain unique comparison pairs")
        actual = Counter(item.triage_class for item in self.records)
        if any(self.counts.get(key, 0) != actual.get(key, 0) for key in self.counts):
            raise ValueError("triage counts do not match records")
        review_pairs = {
            item.compared_proposal_ids
            for item in self.records
            if item.triage_class == "shared_external_evidence"
        }
        if len(self.review_queue) != len(set(self.review_queue)) or set(
            self.review_queue
        ) != review_pairs:
            raise ValueError("review queue must contain every shared-evidence pair once")
        return self


class DossierProposal(FrozenStrictModel):
    proposal_id: str = Field(min_length=1)
    lane_id: str = Field(min_length=1)
    round_id: int = Field(ge=1)
    channel: DiscoveryChannel
    coordinate: MechanismCoordinateAssignment
    normalized_assertions: tuple[tuple[str, tuple[str, ...]], ...]
    mechanistic_definition: MechanisticProposalDefinition
    parent_hypothesis: str = Field(min_length=1)
    representative_reactive_state: str = Field(min_length=1)
    evidence_ids: tuple[str, ...]


class EvidenceDossier(FrozenStrictModel):
    compared_proposal_ids: tuple[str, str]
    proposals: tuple[DossierProposal, DossierProposal]
    shared_qualifying_evidence_ids: tuple[str, ...] = Field(min_length=1)
    shared_assessments: tuple[TransferabilityAssessment, ...] = Field(min_length=1)
    core_token_jaccard: float = Field(ge=0, le=1)
    context_token_jaccard: float = Field(ge=0, le=1)
    caution: str = Field(min_length=1)
    dossier_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_evidence_and_pair(self) -> "EvidenceDossier":
        proposal_ids = tuple(item.proposal_id for item in self.proposals)
        if proposal_ids != self.compared_proposal_ids:
            raise ValueError("dossier proposals must match the compared pair")
        assessment_ids = tuple(item.assessment_id for item in self.shared_assessments)
        if assessment_ids != self.shared_qualifying_evidence_ids:
            raise ValueError("dossier assessment records must match shared evidence IDs")
        return self


class ComparisonEvidenceJudgment(FrozenStrictModel):
    state: JudgmentState
    evidence_ids: tuple[str, ...]

    @model_validator(mode="after")
    def validate_evidence(self) -> "ComparisonEvidenceJudgment":
        evidence_ids = tuple(sorted(set(self.evidence_ids)))
        if self.state == "unknown" and evidence_ids:
            raise ValueError("unknown comparison state cannot cite evidence")
        if self.state != "unknown" and not evidence_ids:
            raise ValueError("non-unknown comparison state requires evidence")
        object.__setattr__(self, "evidence_ids", evidence_ids)
        return self


class ComparisonReview(FrozenStrictModel):
    compared_proposal_ids: tuple[str, str]
    field_judgments: dict[MechanisticField, ComparisonEvidenceJudgment]
    same_mechanism: ComparisonEvidenceJudgment
    left_contains_right: ComparisonEvidenceJudgment
    right_contains_left: ComparisonEvidenceJudgment
    experimentally_distinguishable: ComparisonEvidenceJudgment
    uncertainties: tuple[str, ...]

    @model_validator(mode="after")
    def validate_review(self) -> "ComparisonReview":
        pair = tuple(sorted(set(self.compared_proposal_ids)))
        if len(pair) != 2 or pair != self.compared_proposal_ids:
            raise ValueError("review pair must contain two sorted unique proposal IDs")
        if set(self.field_judgments) != set(_MECHANISTIC_FIELDS):
            raise ValueError("review must judge exactly the six mechanistic fields")
        object.__setattr__(self, "uncertainties", tuple(sorted(set(self.uncertainties))))
        return self


class ComparisonReviewPayload(FrozenStrictModel):
    comparisons: tuple[ComparisonReview, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_pairs(self) -> "ComparisonReviewPayload":
        pairs = tuple(item.compared_proposal_ids for item in self.comparisons)
        if len(pairs) != len(set(pairs)):
            raise ValueError("review payload contains duplicate comparison pairs")
        return self


class LaneMappedDecision(FrozenStrictModel):
    compared_proposal_ids: tuple[str, str]
    outcome: LaneOutcome
    parent_proposal_id: str | None = None
    child_proposal_id: str | None = None
    evidence_ids: tuple[str, ...]
    uncertainties: tuple[str, ...]

    @model_validator(mode="after")
    def validate_relation(self) -> "LaneMappedDecision":
        if self.outcome == "parent_child_granularity":
            if (
                self.parent_proposal_id is None
                or self.child_proposal_id is None
                or self.parent_proposal_id == self.child_proposal_id
            ):
                raise ValueError("parent-child outcome requires a directed relation")
        elif self.parent_proposal_id is not None or self.child_proposal_id is not None:
            raise ValueError("only parent-child outcome may contain a relation")
        return self


class ConsensusDecision(FrozenStrictModel):
    compared_proposal_ids: tuple[str, str]
    disposition: ConsensusDisposition
    lane_outcomes: tuple[LaneOutcome, LaneOutcome]
    parent_proposal_id: str | None = None
    child_proposal_id: str | None = None
    evidence_ids: tuple[str, ...]
    rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_consensus(self) -> "ConsensusDecision":
        if tuple(sorted(set(self.compared_proposal_ids))) != self.compared_proposal_ids:
            raise ValueError("consensus pair must contain two sorted unique IDs")
        if self.disposition == "parent_child_candidate":
            if (
                self.parent_proposal_id is None
                or self.child_proposal_id is None
                or self.parent_proposal_id == self.child_proposal_id
            ):
                raise ValueError("parent-child consensus requires a directed relation")
        elif self.parent_proposal_id is not None or self.child_proposal_id is not None:
            raise ValueError("only parent-child consensus may contain a relation")
        return self


class CandidateFamily(FrozenStrictModel):
    family_id: str = Field(pattern=r"^NFV35-[0-9a-f]{12}$")
    coordinate: MechanismCoordinateAssignment
    baseline_family_ids: tuple[str, ...] = Field(min_length=1)
    member_proposal_ids: tuple[str, ...] = Field(min_length=1)


class CandidateConsolidation(FrozenStrictModel):
    version: Literal["3.5"]
    source_version: Literal["3.4.1"]
    baseline_family_count: int = Field(ge=1)
    candidate_family_count: int = Field(ge=1)
    families: tuple[CandidateFamily, ...] = Field(min_length=1)
    consensus: tuple[ConsensusDecision, ...]
    parent_child_relations: tuple[tuple[str, str], ...]

    @model_validator(mode="after")
    def validate_preservation(self) -> "CandidateConsolidation":
        if self.candidate_family_count != len(self.families):
            raise ValueError("candidate family count does not match families")
        members = tuple(
            proposal_id
            for family in self.families
            for proposal_id in family.member_proposal_ids
        )
        if len(members) != len(set(members)):
            raise ValueError("candidate consolidation must preserve proposals once")
        return self


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_dossier_digest(dossier: EvidenceDossier) -> str:
    payload = dossier.model_dump(mode="json", exclude={"dossier_digest"})
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _review_judgments(review: ComparisonReview) -> tuple[ComparisonEvidenceJudgment, ...]:
    return (
        *(review.field_judgments[field] for field in _MECHANISTIC_FIELDS),
        review.same_mechanism,
        review.left_contains_right,
        review.right_contains_left,
        review.experimentally_distinguishable,
    )


def validate_review_payload(
    payload: ComparisonReviewPayload,
    dossiers_by_pair: Mapping[tuple[str, str], EvidenceDossier],
) -> ComparisonReviewPayload:
    """Require exact dossier coverage and dossier-local evidence citations."""

    reviews = {item.compared_proposal_ids: item for item in payload.comparisons}
    if set(reviews) != set(dossiers_by_pair):
        raise ComparisonAdjudicationError("review payload does not match dossier pairs")
    for pair, review in reviews.items():
        allowed = set(dossiers_by_pair[pair].shared_qualifying_evidence_ids)
        for judgment in _review_judgments(review):
            if not set(judgment.evidence_ids).issubset(allowed):
                raise ComparisonAdjudicationError(
                    "review cites evidence outside dossier"
                )
    return payload


def map_lane_review(review: ComparisonReview) -> LaneMappedDecision:
    """Map evidence states to one provisional identity outcome."""

    field_states = tuple(
        review.field_judgments[field].state for field in _MECHANISTIC_FIELDS
    )
    outcome: LaneOutcome = "unresolved"
    parent_id: str | None = None
    child_id: str | None = None
    if (
        review.same_mechanism.state == "support"
        and "contradiction" not in field_states
        and review.experimentally_distinguishable.state == "contradiction"
    ):
        outcome = "same_mechanism_supported"
    elif (
        review.same_mechanism.state == "contradiction"
        and "contradiction" in field_states
        and review.experimentally_distinguishable.state == "support"
    ):
        outcome = "different_mechanism_supported"
    elif (
        review.experimentally_distinguishable.state == "support"
        and review.left_contains_right.state == "support"
        and review.right_contains_left.state != "support"
    ):
        outcome = "parent_child_granularity"
        parent_id, child_id = review.compared_proposal_ids
    elif (
        review.experimentally_distinguishable.state == "support"
        and review.right_contains_left.state == "support"
        and review.left_contains_right.state != "support"
    ):
        outcome = "parent_child_granularity"
        child_id, parent_id = review.compared_proposal_ids
    evidence_ids = tuple(
        sorted(
            {
                evidence_id
                for judgment in _review_judgments(review)
                for evidence_id in judgment.evidence_ids
            }
        )
    )
    return LaneMappedDecision(
        compared_proposal_ids=review.compared_proposal_ids,
        outcome=outcome,
        parent_proposal_id=parent_id,
        child_proposal_id=child_id,
        evidence_ids=evidence_ids,
        uncertainties=review.uncertainties,
    )


def combine_review_lanes(
    reviews_by_lane: Mapping[
        str, Mapping[tuple[str, str], ComparisonReview]
    ],
    dossiers_by_pair: Mapping[tuple[str, str], EvidenceDossier],
    *,
    required_lane_ids: tuple[str, str],
) -> tuple[ConsensusDecision, ...]:
    """Combine exactly two independent, validated lane outputs."""

    if tuple(sorted(set(required_lane_ids))) != tuple(sorted(required_lane_ids)):
        raise ComparisonAdjudicationError("review lane IDs must be two unique values")
    if set(reviews_by_lane) != set(required_lane_ids):
        raise ComparisonAdjudicationError("both configured review lanes are required")
    decisions: list[ConsensusDecision] = []
    for pair in sorted(dossiers_by_pair):
        mapped: list[LaneMappedDecision] = []
        for lane_id in required_lane_ids:
            review = reviews_by_lane[lane_id].get(pair)
            if review is None:
                raise ComparisonAdjudicationError("review lane is missing a dossier pair")
            validate_review_payload(
                ComparisonReviewPayload(comparisons=(review,)),
                {pair: dossiers_by_pair[pair]},
            )
            mapped.append(map_lane_review(review))
        left, right = mapped
        disposition: ConsensusDisposition = "unresolved"
        parent_id: str | None = None
        child_id: str | None = None
        if left.outcome == right.outcome == "same_mechanism_supported":
            disposition = "consensus_merge_candidate"
        elif left.outcome == right.outcome == "different_mechanism_supported":
            disposition = "evidence_supported_distinct_candidate"
        elif (
            left.outcome == right.outcome == "parent_child_granularity"
            and left.parent_proposal_id == right.parent_proposal_id
            and left.child_proposal_id == right.child_proposal_id
        ):
            disposition = "parent_child_candidate"
            parent_id = left.parent_proposal_id
            child_id = left.child_proposal_id
        evidence_ids = tuple(sorted(set(left.evidence_ids) | set(right.evidence_ids)))
        decisions.append(
            ConsensusDecision(
                compared_proposal_ids=pair,
                disposition=disposition,
                lane_outcomes=(left.outcome, right.outcome),
                parent_proposal_id=parent_id,
                child_proposal_id=child_id,
                evidence_ids=evidence_ids,
                rationale=(
                    "Both independent review lanes produced the same evidence-state "
                    "mapping."
                    if disposition != "unresolved"
                    else "The independent review lanes did not produce an identical "
                    "actionable evidence-state mapping."
                ),
            )
        )
    return tuple(decisions)


def _candidate_family_id(baseline_family_ids: tuple[str, ...]) -> str:
    digest = hashlib.sha256(_canonical_json(baseline_family_ids).encode("utf-8"))
    return "NFV35-" + digest.hexdigest()[:12]


def apply_consensus_candidates(
    baseline: CrossRoundConsolidation,
    consensus: tuple[ConsensusDecision, ...],
) -> CandidateConsolidation:
    """Apply merge candidates with complete-link semantics over baseline families."""

    by_proposal = {
        proposal_id: family
        for family in baseline.families
        for proposal_id in family.member_proposal_ids
    }
    consensus_pairs = tuple(item.compared_proposal_ids for item in consensus)
    if len(consensus_pairs) != len(set(consensus_pairs)):
        raise ComparisonAdjudicationError("consensus contains duplicate pairs")
    if any(not set(pair).issubset(by_proposal) for pair in consensus_pairs):
        raise ComparisonAdjudicationError("consensus cites unknown proposal")
    eligible = {
        item.compared_proposal_ids
        for item in consensus
        if item.disposition == "consensus_merge_candidate"
    }
    clusters: list[set[str]] = [
        set(family.member_proposal_ids)
        for family in sorted(baseline.families, key=lambda item: item.family_id)
    ]
    for pair in sorted(eligible):
        left_index = next(i for i, values in enumerate(clusters) if pair[0] in values)
        right_index = next(i for i, values in enumerate(clusters) if pair[1] in values)
        if left_index == right_index:
            continue
        left_cluster = clusters[left_index]
        right_cluster = clusters[right_index]
        cross_pairs = {
            tuple(sorted((left_id, right_id)))
            for left_id, right_id in combinations(
                sorted(left_cluster | right_cluster), 2
            )
            if (left_id in left_cluster) != (right_id in left_cluster)
        }
        if not cross_pairs.issubset(eligible):
            continue
        coordinates = {
            _canonical_json(by_proposal[proposal_id].coordinate.model_dump(mode="json"))
            for proposal_id in left_cluster | right_cluster
        }
        if len(coordinates) != 1:
            raise ComparisonAdjudicationError("candidate merge crosses coordinates")
        merged = left_cluster | right_cluster
        for index in sorted((left_index, right_index), reverse=True):
            del clusters[index]
        clusters.append(merged)
        clusters.sort(key=lambda values: tuple(sorted(values)))
    candidate_families: list[CandidateFamily] = []
    for member_ids in sorted(clusters, key=lambda values: tuple(sorted(values))):
        baseline_ids = tuple(
            sorted({by_proposal[proposal_id].family_id for proposal_id in member_ids})
        )
        coordinate = by_proposal[min(member_ids)].coordinate
        candidate_families.append(
            CandidateFamily(
                family_id=_candidate_family_id(baseline_ids),
                coordinate=coordinate,
                baseline_family_ids=baseline_ids,
                member_proposal_ids=tuple(sorted(member_ids)),
            )
        )
    relations = tuple(
        sorted(
            (item.parent_proposal_id, item.child_proposal_id)
            for item in consensus
            if item.disposition == "parent_child_candidate"
            and item.parent_proposal_id is not None
            and item.child_proposal_id is not None
        )
    )
    return CandidateConsolidation(
        version="3.5",
        source_version="3.4.1",
        baseline_family_count=len(baseline.families),
        candidate_family_count=len(candidate_families),
        families=tuple(candidate_families),
        consensus=tuple(sorted(consensus, key=lambda item: item.compared_proposal_ids)),
        parent_child_relations=relations,
    )


def _coordinate_key(fingerprint: EvidenceFingerprint) -> tuple[str, ...]:
    return tuple(
        str(value)
        for value in fingerprint.coordinate.model_dump(mode="json").values()
    )


def triage_unresolved_comparisons(
    consolidation: CrossRoundConsolidation,
    fingerprints_by_id: Mapping[str, EvidenceFingerprint],
    policy: ComparisonTriagePolicy,
) -> ComparisonTriage:
    """Partition unresolved comparisons without changing family identity."""

    if consolidation.version != policy.source_version:
        raise ComparisonAdjudicationError("triage source version does not match policy")
    records: list[ComparisonTriageRecord] = []
    for decision in consolidation.decisions:
        if decision.decision != "unresolved":
            continue
        pair = decision.compared_proposal_ids
        if any(proposal_id not in fingerprints_by_id for proposal_id in pair):
            raise ComparisonAdjudicationError("triage comparison cites unknown proposal")
        left, right = (fingerprints_by_id[proposal_id] for proposal_id in pair)
        if _coordinate_key(left) != _coordinate_key(right):
            raise ComparisonAdjudicationError("triage comparison crosses coordinates")
        shared = tuple(sorted(set(decision.shared_qualifying_evidence_ids)))
        if any(
            not any(value.startswith(prefix) for prefix in policy.qualifying_evidence_prefixes)
            for value in shared
        ):
            raise ComparisonAdjudicationError("triage comparison cites invalid evidence")
        if shared:
            triage_class: TriageClass = "shared_external_evidence"
        elif (
            decision.core_token_jaccard >= policy.minimum_core_token_jaccard
            and decision.context_token_jaccard
            >= policy.minimum_context_token_jaccard
        ):
            triage_class = "text_compatible_evidence_gap"
        else:
            triage_class = "insufficient_linkage"
        coverage = min(
            decision.core_token_jaccard / policy.minimum_core_token_jaccard,
            decision.context_token_jaccard / policy.minimum_context_token_jaccard,
        )
        records.append(
            ComparisonTriageRecord(
                compared_proposal_ids=pair,
                triage_class=triage_class,
                shared_qualifying_evidence_ids=shared,
                core_token_jaccard=decision.core_token_jaccard,
                context_token_jaccard=decision.context_token_jaccard,
                threshold_coverage_ratio=coverage,
                cross_lane=left.lane_id != right.lane_id,
            )
        )
    ordered = tuple(sorted(records, key=lambda item: item.compared_proposal_ids))
    counts = Counter(item.triage_class for item in ordered)
    review_records = sorted(
        (
            item
            for item in ordered
            if item.triage_class == "shared_external_evidence"
        ),
        key=lambda item: (
            -int(item.cross_lane),
            -item.threshold_coverage_ratio,
            -len(item.shared_qualifying_evidence_ids),
            item.compared_proposal_ids,
        ),
    )
    return ComparisonTriage(
        version=policy.version,
        source_version=policy.source_version,
        records=ordered,
        counts={
            "shared_external_evidence": counts["shared_external_evidence"],
            "text_compatible_evidence_gap": counts["text_compatible_evidence_gap"],
            "insufficient_linkage": counts["insufficient_linkage"],
        },
        review_queue=tuple(item.compared_proposal_ids for item in review_records),
    )


def build_evidence_dossiers(
    triage: ComparisonTriage,
    fingerprints_by_id: Mapping[str, EvidenceFingerprint],
    proposals_by_id: Mapping[str, TaxonomyProposal],
    assessments_by_id: Mapping[str, TransferabilityAssessment],
) -> tuple[EvidenceDossier, ...]:
    """Build immutable local dossiers for shared-evidence review pairs."""

    records = {
        item.compared_proposal_ids: item
        for item in triage.records
        if item.triage_class == "shared_external_evidence"
    }
    dossiers: list[EvidenceDossier] = []
    for pair in triage.review_queue:
        record = records[pair]
        missing = [
            evidence_id
            for evidence_id in record.shared_qualifying_evidence_ids
            if evidence_id not in assessments_by_id
        ]
        if missing:
            raise ComparisonAdjudicationError(
                f"missing transfer assessment for shared evidence: {missing[0]}"
            )
        dossier_proposals: list[DossierProposal] = []
        for proposal_id in pair:
            if proposal_id not in fingerprints_by_id or proposal_id not in proposals_by_id:
                raise ComparisonAdjudicationError("dossier cites unknown proposal")
            fingerprint = fingerprints_by_id[proposal_id]
            proposal = proposals_by_id[proposal_id]
            if proposal.coordinate_assignment != fingerprint.coordinate:
                raise ComparisonAdjudicationError("proposal coordinate changed before dossier")
            if not set(record.shared_qualifying_evidence_ids).issubset(
                set(fingerprint.evidence_ids) & set(proposal.evidence_ids)
            ):
                raise ComparisonAdjudicationError(
                    "shared evidence is not cited by both dossier proposals"
                )
            dossier_proposals.append(
                DossierProposal(
                    proposal_id=proposal_id,
                    lane_id=fingerprint.lane_id,
                    round_id=fingerprint.round_id,
                    channel=fingerprint.channel,
                    coordinate=fingerprint.coordinate,
                    normalized_assertions=fingerprint.normalized_assertions,
                    mechanistic_definition=proposal.mechanistic_definition,
                    parent_hypothesis=proposal.parent_hypothesis,
                    representative_reactive_state=proposal.representative_reactive_state,
                    evidence_ids=tuple(sorted(set(proposal.evidence_ids))),
                )
            )
        provisional = EvidenceDossier(
            compared_proposal_ids=pair,
            proposals=tuple(dossier_proposals),  # type: ignore[arg-type]
            shared_qualifying_evidence_ids=record.shared_qualifying_evidence_ids,
            shared_assessments=tuple(
                assessments_by_id[evidence_id]
                for evidence_id in record.shared_qualifying_evidence_ids
            ),
            core_token_jaccard=record.core_token_jaccard,
            context_token_jaccard=record.context_token_jaccard,
            caution=(
                "Shared literature evidence is a review anchor and does not by itself "
                "establish equivalent mechanism-family identity."
            ),
            dossier_digest="0" * 64,
        )
        dossiers.append(
            provisional.model_copy(
                update={"dossier_digest": canonical_dossier_digest(provisional)}
            )
        )
    return tuple(dossiers)

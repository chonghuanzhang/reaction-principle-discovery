from __future__ import annotations

import pytest
from pydantic import ValidationError
from pathlib import Path

from pipeline.comparison_adjudication import (
    ComparisonEvidenceJudgment,
    ComparisonReview,
    ComparisonReviewPayload,
    ComparisonTriagePolicy,
    ConsensusDecision,
    apply_consensus_candidates,
    build_evidence_dossiers,
    canonical_dossier_digest,
    combine_review_lanes,
    map_lane_review,
    triage_unresolved_comparisons,
    validate_review_payload,
)
from pipeline.cross_round_consolidation import (
    CrossRoundConsolidation,
    CrossRoundDecision,
    CrossRoundFamily,
    EvidenceFingerprint,
    PrefixMetrics,
)
from pipeline.principle_models import TransferabilityAssessment
from pipeline.taxonomy_discovery import (
    MechanismCoordinateAssignment,
    MechanisticProposalDefinition,
    TaxonomyProposal,
)


COORDINATE = MechanismCoordinateAssignment(
    nucleophilic_center="oxygen_center",
    reactive_state="anionic_state",
    bond_forming_mode="polar_addition_elimination",
    activation_mode="base_activation",
    attack_topology="fluorinated_alkene_carbon",
    target_termination="protonation_then_selective_fluoride_elimination",
)


def _policy() -> ComparisonTriagePolicy:
    return ComparisonTriagePolicy(
        version="3.5",
        source_version="3.4.1",
        minimum_core_token_jaccard=0.35,
        minimum_context_token_jaccard=0.20,
        qualifying_evidence_prefixes=("TA-",),
    )


def _fingerprint(
    proposal_id: str,
    *,
    lane_id: str,
    evidence_ids: tuple[str, ...] = (),
) -> EvidenceFingerprint:
    return EvidenceFingerprint(
        proposal_id=proposal_id,
        lane_id=lane_id,
        round_id=1,
        channel="literature_derived",
        evidence_level="traceable_external_evidence",
        evidence_ids=evidence_ids,
        coordinate=COORDINATE,
        exact_fingerprint=(proposal_id[-1].lower() * 64),
        core_tokens=frozenset({f"core:{proposal_id}"}),
        context_tokens=frozenset({f"context:{proposal_id}"}),
        normalized_assertions=(("nucleophilic_center", (proposal_id.lower(),)),),
    )


def _decision(
    left: str,
    right: str,
    *,
    decision: str = "unresolved",
    shared: tuple[str, ...] = (),
    core: float = 0.1,
    context: float = 0.1,
) -> CrossRoundDecision:
    return CrossRoundDecision(
        compared_proposal_ids=tuple(sorted((left, right))),
        decision=decision,
        rule_id=(
            "insufficient_merge_evidence"
            if decision == "unresolved"
            else "evidence_supported_paraphrase"
        ),
        shared_qualifying_evidence_ids=shared,
        core_token_jaccard=core,
        context_token_jaccard=context,
        rationale="fixture decision",
    )


def _family(fingerprint: EvidenceFingerprint) -> CrossRoundFamily:
    return CrossRoundFamily(
        family_id="NFV34-" + fingerprint.exact_fingerprint[:12],
        coordinate=fingerprint.coordinate,
        representative_proposal_id=fingerprint.proposal_id,
        representative_exact_fingerprint=fingerprint.exact_fingerprint,
        member_proposal_ids=(fingerprint.proposal_id,),
        round_ids=(fingerprint.round_id,),
        lane_ids=(fingerprint.lane_id,),
        channels=(fingerprint.channel,),
        evidence_ids=fingerprint.evidence_ids,
        evidence_bearing=bool(fingerprint.evidence_ids),
    )


def _consolidation(
    fingerprints: tuple[EvidenceFingerprint, ...],
    decisions: tuple[CrossRoundDecision, ...],
) -> CrossRoundConsolidation:
    return CrossRoundConsolidation(
        version="3.4.1",
        source_version="3.3",
        source_digest="a" * 64,
        policy_digest="b" * 64,
        proposal_count=len(fingerprints),
        families=tuple(_family(item) for item in fingerprints),
        decisions=decisions,
        prefix_metrics=(
            PrefixMetrics(
                round_id=1,
                proposal_count=len(fingerprints),
                family_count=len(fingerprints),
                new_family_count=len(fingerprints),
                new_family_rate=1.0,
                coordinate_count=1,
                multi_lane_family_fraction=0.0,
                unresolved_pair_count=sum(
                    item.decision == "unresolved" for item in decisions
                ),
            ),
        ),
        consecutive_low_novelty_transitions=0,
        coordinate_coverage_stable=False,
        evidence_bearing_lane_converged=False,
        consolidation_converged=False,
        freeze_2_allowed=False,
        freeze_2_blockers=("cross_round_consolidation_not_converged",),
    )


def _proposal(proposal_id: str, evidence_ids: tuple[str, ...]) -> TaxonomyProposal:
    return TaxonomyProposal(
        proposal_id=proposal_id,
        mechanistic_definition=MechanisticProposalDefinition(
            nucleophilic_center="oxygen center",
            reactive_state="anionic state",
            bond_forming_mode="polar addition elimination",
            activation_mode="base activation",
            critical_conditions=("dry solvent",),
            dominant_failure_modes=("decomposition",),
        ),
        coordinate_assignment=COORDINATE,
        coordinate_assignment_key="fixture-coordinate",
        source_channel="literature_derived",
        evidence_level="traceable_external_evidence",
        evidence_ids=evidence_ids,
        parent_hypothesis=f"hypothesis {proposal_id}",
        representative_reactive_state=f"state {proposal_id}",
        counterarguments=(),
        unknowns=("scope unknown",),
        suggested_search_terms=("fixture search",),
    )


def _assessment(assessment_id: str) -> TransferabilityAssessment:
    return TransferabilityAssessment(
        assessment_id=assessment_id,
        source_paper_id="paper-1.pdf",
        source_mechanism_id="paper-1::ME001",
        source_evidence_ids=("paper-1::E001",),
        seed_feature_ids=("SE-001",),
        shared_elementary_step="A traced elementary step.",
        matched_requirements=("shared_elementary_step",),
        mismatched_requirements=("condition_overlap",),
        blocking_constraints=(),
        transfer_status="conditional",
        transferable_claim="Only the elementary step may transfer.",
        conditions=("Condition identity is not established.",),
        uncertainty=("Seed applicability remains unknown.",),
        falsifying_test="Test the isolated Seed-relevant intermediate.",
        score_components={"total": 1, "denominator": 22},
    )


def _shared_triage_fixture():
    fingerprints = (
        _fingerprint("P1", lane_id="A", evidence_ids=("TA-1",)),
        _fingerprint("P2", lane_id="B", evidence_ids=("TA-1",)),
    )
    triage = triage_unresolved_comparisons(
        _consolidation(
            fingerprints,
            (
                _decision(
                    "P1", "P2", shared=("TA-1",), core=0.2, context=0.1
                ),
            ),
        ),
        {item.proposal_id: item for item in fingerprints},
        _policy(),
    )
    return triage, fingerprints


def test_triage_partitions_every_unresolved_pair_once() -> None:
    fingerprints = (
        _fingerprint("P1", lane_id="A", evidence_ids=("TA-1",)),
        _fingerprint("P2", lane_id="B", evidence_ids=("TA-1",)),
        _fingerprint("P3", lane_id="A"),
        _fingerprint("P4", lane_id="B"),
        _fingerprint("P5", lane_id="A"),
        _fingerprint("P6", lane_id="B"),
    )
    decisions = (
        _decision("P1", "P2", shared=("TA-1",), core=0.2, context=0.1),
        _decision("P3", "P4", core=0.4, context=0.3),
        _decision("P5", "P6", core=0.1, context=0.1),
    )

    triage = triage_unresolved_comparisons(
        _consolidation(fingerprints, decisions),
        {item.proposal_id: item for item in fingerprints},
        _policy(),
    )

    assert triage.counts == {
        "shared_external_evidence": 1,
        "text_compatible_evidence_gap": 1,
        "insufficient_linkage": 1,
    }
    assert len({row.compared_proposal_ids for row in triage.records}) == 3


def test_triage_never_reclassifies_merge_decisions() -> None:
    fingerprints = (
        _fingerprint("P1", lane_id="A", evidence_ids=("TA-1",)),
        _fingerprint("P2", lane_id="B", evidence_ids=("TA-1",)),
        _fingerprint("P3", lane_id="A"),
    )
    decisions = (
        _decision(
            "P1",
            "P2",
            decision="merge",
            shared=("TA-1",),
            core=0.8,
            context=0.8,
        ),
        _decision("P2", "P3"),
    )

    triage = triage_unresolved_comparisons(
        _consolidation(fingerprints, decisions),
        {item.proposal_id: item for item in fingerprints},
        _policy(),
    )

    assert tuple(row.compared_proposal_ids for row in triage.records) == (("P2", "P3"),)


def test_shared_evidence_review_order_is_cross_lane_then_threshold_coverage() -> None:
    fingerprints = (
        _fingerprint("P1", lane_id="A", evidence_ids=("TA-1",)),
        _fingerprint("P2", lane_id="A", evidence_ids=("TA-1",)),
        _fingerprint("P3", lane_id="A", evidence_ids=("TA-1",)),
        _fingerprint("P4", lane_id="B", evidence_ids=("TA-1",)),
        _fingerprint("P5", lane_id="A", evidence_ids=("TA-1",)),
        _fingerprint("P6", lane_id="B", evidence_ids=("TA-1",)),
    )
    decisions = (
        _decision("P1", "P2", shared=("TA-1",), core=0.34, context=0.19),
        _decision("P3", "P4", shared=("TA-1",), core=0.20, context=0.10),
        _decision("P5", "P6", shared=("TA-1",), core=0.30, context=0.18),
    )

    triage = triage_unresolved_comparisons(
        _consolidation(fingerprints, decisions),
        {item.proposal_id: item for item in fingerprints},
        _policy(),
    )

    assert triage.review_queue == (("P5", "P6"), ("P3", "P4"), ("P1", "P2"))


def test_dossier_resolves_only_shared_frozen_assessments() -> None:
    triage, fingerprints = _shared_triage_fixture()

    dossiers = build_evidence_dossiers(
        triage,
        {item.proposal_id: item for item in fingerprints},
        {
            "P1": _proposal("P1", ("TA-1",)),
            "P2": _proposal("P2", ("TA-1",)),
        },
        {"TA-1": _assessment("TA-1")},
    )

    assert dossiers[0].shared_assessments[0].assessment_id == "TA-1"
    assert dossiers[0].dossier_digest == canonical_dossier_digest(dossiers[0])


def test_dossier_rejects_missing_shared_assessment() -> None:
    triage, fingerprints = _shared_triage_fixture()

    try:
        build_evidence_dossiers(
            triage,
            {item.proposal_id: item for item in fingerprints},
            {
                "P1": _proposal("P1", ("TA-1",)),
                "P2": _proposal("P2", ("TA-1",)),
            },
            {},
        )
    except ValueError as exc:
        assert "missing transfer assessment" in str(exc)
    else:
        raise AssertionError("missing transfer assessment was accepted")


def _judgment(
    state: str,
    evidence_ids: tuple[str, ...] = ("TA-1",),
) -> ComparisonEvidenceJudgment:
    return ComparisonEvidenceJudgment(
        state=state,
        evidence_ids=() if state == "unknown" else evidence_ids,
    )


def _review(
    *,
    evidence_ids: tuple[str, ...] = ("TA-1",),
    outcome: str = "same",
) -> ComparisonReview:
    if outcome == "same":
        same = _judgment("support", evidence_ids)
        distinguishable = _judgment("contradiction", evidence_ids)
        fields = {
            name: _judgment("support", evidence_ids)
            for name in (
                "nucleophilic_center",
                "reactive_state",
                "bond_forming_mode",
                "activation_mode",
                "critical_conditions",
                "dominant_failure_modes",
            )
        }
    else:
        same = _judgment("unknown")
        distinguishable = _judgment("unknown")
        fields = {
            name: _judgment("unknown")
            for name in (
                "nucleophilic_center",
                "reactive_state",
                "bond_forming_mode",
                "activation_mode",
                "critical_conditions",
                "dominant_failure_modes",
            )
        }
    return ComparisonReview(
        compared_proposal_ids=("P1", "P2"),
        field_judgments=fields,
        same_mechanism=same,
        left_contains_right=_judgment("unknown"),
        right_contains_left=_judgment("unknown"),
        experimentally_distinguishable=distinguishable,
        uncertainties=("Seed applicability remains unknown.",),
    )


def _distinct_review() -> ComparisonReview:
    review = _review(outcome="unknown")
    fields = dict(review.field_judgments)
    fields["bond_forming_mode"] = _judgment("contradiction")
    return review.model_copy(
        update={
            "field_judgments": fields,
            "same_mechanism": _judgment("contradiction"),
            "experimentally_distinguishable": _judgment("support"),
        }
    )


def _consensus(
    left: str,
    right: str,
    disposition: str,
) -> ConsensusDecision:
    parent_id = left if disposition == "parent_child_candidate" else None
    child_id = right if disposition == "parent_child_candidate" else None
    return ConsensusDecision(
        compared_proposal_ids=tuple(sorted((left, right))),
        disposition=disposition,
        lane_outcomes=(
            "same_mechanism_supported",
            "same_mechanism_supported",
        ),
        parent_proposal_id=parent_id,
        child_proposal_id=child_id,
        evidence_ids=("TA-1",),
        rationale="fixture consensus",
    )


def test_unknown_review_state_cites_no_evidence() -> None:
    with pytest.raises(ValidationError, match="unknown"):
        ComparisonEvidenceJudgment(state="unknown", evidence_ids=("TA-1",))


def test_non_unknown_review_state_requires_in_dossier_evidence() -> None:
    triage, fingerprints = _shared_triage_fixture()
    dossier = build_evidence_dossiers(
        triage,
        {item.proposal_id: item for item in fingerprints},
        {
            "P1": _proposal("P1", ("TA-1",)),
            "P2": _proposal("P2", ("TA-1",)),
        },
        {"TA-1": _assessment("TA-1")},
    )[0]
    payload = ComparisonReviewPayload(
        comparisons=(_review(evidence_ids=("TA-OUTSIDE",)),)
    )

    with pytest.raises(ValueError, match="outside dossier"):
        validate_review_payload(
            payload, {dossier.compared_proposal_ids: dossier}
        )


def test_supported_same_mechanism_states_map_deterministically() -> None:
    mapped = map_lane_review(_review())

    assert mapped.outcome == "same_mechanism_supported"


def test_review_prompt_requests_states_and_prohibits_final_decisions() -> None:
    prompt = (
        Path(__file__).resolve().parents[1]
        / "config/prompts/comparison_adjudication_v3_5.md"
    ).read_text(encoding="utf-8")

    assert "Return only structured evidence states" in prompt
    assert "Do not return merge, distinct, parent-child, rank, or freeze decisions" in prompt
    assert "Shared evidence is not proof of mechanism-family identity" in prompt
    assert "KNOWN RETROSPECTIVE ANSWER" not in prompt


def test_identical_supported_lane_outcomes_create_consensus_candidate() -> None:
    triage, fingerprints = _shared_triage_fixture()
    dossier = build_evidence_dossiers(
        triage,
        {item.proposal_id: item for item in fingerprints},
        {
            "P1": _proposal("P1", ("TA-1",)),
            "P2": _proposal("P2", ("TA-1",)),
        },
        {"TA-1": _assessment("TA-1")},
    )[0]

    consensus = combine_review_lanes(
        {
            "REVIEW-V35-A": {("P1", "P2"): _review()},
            "REVIEW-V35-B": {("P1", "P2"): _review()},
        },
        {dossier.compared_proposal_ids: dossier},
        required_lane_ids=("REVIEW-V35-A", "REVIEW-V35-B"),
    )

    assert consensus[0].disposition == "consensus_merge_candidate"


def test_lane_disagreement_remains_unresolved() -> None:
    triage, fingerprints = _shared_triage_fixture()
    dossier = build_evidence_dossiers(
        triage,
        {item.proposal_id: item for item in fingerprints},
        {
            "P1": _proposal("P1", ("TA-1",)),
            "P2": _proposal("P2", ("TA-1",)),
        },
        {"TA-1": _assessment("TA-1")},
    )[0]

    consensus = combine_review_lanes(
        {
            "REVIEW-V35-A": {("P1", "P2"): _review()},
            "REVIEW-V35-B": {("P1", "P2"): _distinct_review()},
        },
        {dossier.compared_proposal_ids: dossier},
        required_lane_ids=("REVIEW-V35-A", "REVIEW-V35-B"),
    )

    assert consensus[0].disposition == "unresolved"


def test_candidate_merge_requires_consensus_for_every_cross_family_pair() -> None:
    fingerprints = tuple(
        _fingerprint(proposal_id, lane_id=lane, evidence_ids=("TA-1",))
        for proposal_id, lane in (("P1", "A"), ("P2", "B"), ("P3", "A"))
    )
    baseline = _consolidation(fingerprints, ())

    result = apply_consensus_candidates(
        baseline,
        (
            _consensus("P1", "P2", "consensus_merge_candidate"),
            _consensus("P2", "P3", "consensus_merge_candidate"),
        ),
    )

    assert sorted(len(item.member_proposal_ids) for item in result.families) == [1, 2]


@pytest.mark.parametrize(
    "disposition",
    ("evidence_supported_distinct_candidate", "parent_child_candidate"),
)
def test_non_merge_consensus_never_merges_members(disposition: str) -> None:
    fingerprints = (
        _fingerprint("P1", lane_id="A", evidence_ids=("TA-1",)),
        _fingerprint("P2", lane_id="B", evidence_ids=("TA-1",)),
    )
    baseline = _consolidation(fingerprints, ())
    consensus = _consensus("P1", "P2", disposition)

    result = apply_consensus_candidates(baseline, (consensus,))

    assert len(result.families) == 2

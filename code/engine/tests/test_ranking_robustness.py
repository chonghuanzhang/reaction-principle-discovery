import pytest

import pipeline.family_evaluation as family_evaluation_module
from pipeline.family_evaluation import (
    EvidenceContribution,
    DimensionPrincipleLink,
    QualifiedBlocker,
    ReviewedPrincipleLink,
    ScoredFamilyEvaluation,
    load_evaluation_rubric,
    verify_scored_family_evaluation,
)
from pipeline.ranking_robustness import (
    RankingAnalysisError,
    analyze_ranking,
    verify_ranking_analysis,
)
from pipeline.v3_models import DIMENSIONS, DimensionJudgment
from tests.test_family_evaluation import (
    _all_supporting_judgments,
    _build_context,
    _score,
)


_TRUSTED_BASE: ScoredFamilyEvaluation | None = None


@pytest.fixture(scope="module", autouse=True)
def _trusted_scored_base(tmp_path_factory: pytest.TempPathFactory):
    global _TRUSTED_BASE
    context = _build_context(tmp_path_factory.mktemp("ranking-trust"))
    _TRUSTED_BASE = _score(_all_supporting_judgments(), context)
    yield
    _TRUSTED_BASE = None


def _evaluation(
    family_id: str,
    *,
    states: dict[str, str] | None = None,
    papers_by_dimension: dict[str, tuple[str | None, ...]] | None = None,
    counter_papers_by_dimension: dict[str, tuple[str | None, ...]] | None = None,
    opaque_ids: bool = False,
    priority_region: str = "priority_a",
) -> ScoredFamilyEvaluation:
    assert _TRUSTED_BASE is not None
    rubric = load_evaluation_rubric()
    selected_states = {
        dimension: (
            "contradiction" if dimension == "competing_pathway_risk" else "support"
        )
        for dimension in DIMENSIONS
    }
    selected_states.update(states or {})
    if priority_region == "unknown" and not states:
        selected_states["reactive_state_accessibility"] = "unknown"
    state_scores = {
        "support": 4,
        "conditional_support": 2,
        "contradiction": 0,
        "unknown": None,
    }
    evidence_ids_by_dimension = {
        dimension: tuple(
            f"EV-{family_id}-{dimension}-{index}"
            if opaque_ids
            else f"{paper}::{family_id}-{dimension}-{index}"
            for index, paper in enumerate(
                (papers_by_dimension or {}).get(dimension, ("paper-a",)), start=1
            )
        )
        for dimension in DIMENSIONS
    }
    counter_ids_by_dimension = {
        dimension: tuple(
            f"COUNTER-{family_id}-{dimension}-{index}"
            if opaque_ids
            else f"{paper}::COUNTER-{family_id}-{dimension}-{index}"
            for index, paper in enumerate(
                (counter_papers_by_dimension or {}).get(dimension, ()), start=1
            )
        )
        for dimension in DIMENSIONS
    }
    judgments = tuple(
        DimensionJudgment(
            dimension=dimension,
            state=selected_states[dimension],
            evidence_ids=evidence_ids_by_dimension[dimension]
            if selected_states[dimension] != "unknown"
            else (),
            rationale=f"Synthetic judgment for {dimension}",
            counterevidence_ids=counter_ids_by_dimension[dimension],
            unresolved_questions=(),
        )
        for dimension in DIMENSIONS
    )
    scores = {
        dimension: state_scores[selected_states[dimension]] for dimension in DIMENSIONS
    }
    core_scores = [
        scores[dimension]
        for dimension in load_evaluation_rubric().core_dimensions
        if scores[dimension] is not None
    ]
    contributions = tuple(
        EvidenceContribution(
            dimension=dimension,
            evidence_id=evidence_id,
            source_paper=paper,
            direction=(
                "adverse"
                if selected_states[dimension] == "contradiction"
                else "positive"
            ),
            state=selected_states[dimension],
            evidence_class="external_literature",
            evidence_level="traceable_external_evidence",
            is_external=True,
            quality_eligible=True,
            is_counterevidence=False,
        )
        for dimension in DIMENSIONS
        for evidence_id, paper in zip(
            evidence_ids_by_dimension[dimension],
            (papers_by_dimension or {}).get(dimension, ("paper-a",)),
            strict=True,
        )
        if selected_states[dimension] != "unknown"
    ) + tuple(
        EvidenceContribution(
            dimension=dimension,
            evidence_id=evidence_id,
            source_paper=paper,
            direction="adverse",
            state="contradiction",
            evidence_class="external_literature",
            evidence_level="traceable_external_evidence",
            is_external=True,
            quality_eligible=True,
            is_counterevidence=True,
        )
        for dimension in DIMENSIONS
        for evidence_id, paper in zip(
            counter_ids_by_dimension[dimension],
            (counter_papers_by_dimension or {}).get(dimension, ()),
            strict=True,
        )
    )
    source_paths = {
        contribution.evidence_id: contribution.source_paper
        for contribution in contributions
        if contribution.source_paper is not None
    }
    evidence_principle_links = {
        evidence_id: (
            ReviewedPrincipleLink(
                principle_id="PRINCIPLE-SYNTHETIC",
                admissible_dimensions=(dimension,),
            ),
        )
        for dimension in DIMENSIONS
        for evidence_id in (
            *evidence_ids_by_dimension[dimension],
            *counter_ids_by_dimension[dimension],
        )
        if selected_states[dimension] != "unknown"
        or evidence_id in counter_ids_by_dimension[dimension]
    }
    qualified_blockers = (
        (
            QualifiedBlocker(
                blocker_id=f"BLOCK-{family_id}",
                dimension="condition_compatibility",
                statement="Synthetic attested ranking blocker.",
                evidence_ids=(
                    evidence_ids_by_dimension["condition_compatibility"][0],
                ),
                counterevidence_ids=(),
                source_paths=(
                    source_paths[
                        evidence_ids_by_dimension["condition_compatibility"][0]
                    ],
                ),
                reviewed_principle_ids=("PRINCIPLE-SYNTHETIC",),
            ),
        )
        if priority_region == "excluded"
        else ()
    )
    evaluation = family_evaluation_module._build_scored_evaluation(
        family_id=family_id,
        judgments=judgments,
        dimension_scores=scores,
        compatibility_index=(
            None
            if priority_region == "excluded"
            else sum(core_scores) / len(core_scores)
        ),
        evidence_confidence=scores["evidence_quality"],
        uncertainty_burden=sum(
            4 if state == "unknown" else 2 if state == "conditional_support" else 0
            for state in selected_states.values()
        )
        / len(DIMENSIONS),
        failure_risk=scores["competing_pathway_risk"],
        critical_unknowns=tuple(
            dimension
            for dimension in load_evaluation_rubric().critical_dimensions
            if scores[dimension] is None
        ),
        qualified_blocker_ids=tuple(
            blocker.blocker_id for blocker in qualified_blockers
        ),
        qualified_blockers=qualified_blockers,
        reviewed_principle_ids=("PRINCIPLE-SYNTHETIC",),
        reviewed_principle_digests={"PRINCIPLE-SYNTHETIC": "f" * 64},
        evidence_principle_links=evidence_principle_links,
        dimension_principle_links=tuple(
            sorted(
                {
                    DimensionPrincipleLink(
                        evidence_id=evidence_id,
                        dimension=judgment.dimension,
                        principle_id="PRINCIPLE-SYNTHETIC",
                    )
                    for judgment in judgments
                    for evidence_id in (
                        *judgment.evidence_ids,
                        *judgment.counterevidence_ids,
                    )
                }.union(
                    DimensionPrincipleLink(
                        evidence_id=evidence_id,
                        dimension=blocker.dimension,
                        principle_id="PRINCIPLE-SYNTHETIC",
                    )
                    for blocker in qualified_blockers
                    for evidence_id in (
                        *blocker.evidence_ids,
                        *blocker.counterevidence_ids,
                    )
                ),
                key=lambda item: (
                    item.evidence_id,
                    item.dimension,
                    item.principle_id,
                ),
            )
        ),
        evidence_record_digests={
            contribution.evidence_id: "e" * 64
            for contribution in contributions
        },
        evidence_source_paths=source_paths,
        evidence_contributions=contributions,
        rubric_digest=_TRUSTED_BASE.rubric_digest,
        context_digest=_TRUSTED_BASE.context_digest,
        priority_region=priority_region,
    )
    assert verify_scored_family_evaluation(evaluation, rubric) is evaluation
    return evaluation


def test_equal_weight_and_primary_ranks_are_both_reported():
    analysis = analyze_ranking(
        (
            _evaluation("FAM-A"),
            _evaluation(
                "FAM-B",
                states={"condition_compatibility": "conditional_support"},
                priority_region="priority_b",
            ),
        ),
        load_evaluation_rubric(),
        seed=7,
    )

    assert analysis.records[0].primary_rank >= 1
    assert analysis.records[0].equal_weight_rank >= 1


def test_pareto_frontier_excludes_dominated_family():
    dominated_states = {
        dimension: "contradiction"
        for dimension in DIMENSIONS
        if dimension != "competing_pathway_risk"
    }
    dominated_states["competing_pathway_risk"] = "support"

    analysis = analyze_ranking(
        (
            _evaluation("FAM-DOMINANT"),
            _evaluation(
                "FAM-DOMINATED",
                states=dominated_states,
                priority_region="priority_c",
            ),
        ),
        load_evaluation_rubric(),
        seed=7,
    )

    assert analysis.by_family["FAM-DOMINATED"].pareto_optimal is False


def test_evidence_quality_alone_does_not_define_pareto_dominance():
    analysis = analyze_ranking(
        (
            _evaluation("FAM-HIGH-EVIDENCE"),
            _evaluation(
                "FAM-LOW-EVIDENCE",
                states={"evidence_quality": "contradiction"},
                priority_region="priority_b",
            ),
        ),
        load_evaluation_rubric(),
        seed=11,
    )

    assert analysis.by_family["FAM-HIGH-EVIDENCE"].pareto_optimal is True
    assert analysis.by_family["FAM-LOW-EVIDENCE"].pareto_optimal is True


def test_rubric_preregisters_complete_ranking_sensitivity_policy():
    rubric = load_evaluation_rubric()

    assert set(rubric.ranking_weights) == set(DIMENSIONS)
    assert set(rubric.ranking_weight_bounds) == set(DIMENSIONS)
    assert rubric.ranking_sample_count >= 100
    assert rubric.ranking_stability_max_span >= 0


def test_sampled_weight_ranking_is_reproducible_and_reports_distribution():
    evaluations = (
        _evaluation("FAM-A"),
        _evaluation(
            "FAM-B",
            states={
                "elementary_step_match": "conditional_support",
                "target_selectivity": "conditional_support",
            },
            priority_region="priority_b",
        ),
    )

    left = analyze_ranking(evaluations, load_evaluation_rubric(), seed=19)
    right = analyze_ranking(evaluations, load_evaluation_rubric(), seed=19)

    assert left == right
    assert left.records[0].sampled_rank_median >= 1
    assert left.records[0].rank_interval is not None
    assert left.records[0].sampled_rank_range == left.records[0].rank_interval


def test_complete_order_appends_non_testable_sections_without_numeric_ranks():
    evaluations = (
        _evaluation("FAM-UNK", priority_region="unknown"),
        _evaluation("FAM-BDY-Z", priority_region="boundary"),
        _evaluation("FAM-A"),
        _evaluation("FAM-EX", priority_region="excluded"),
        _evaluation("FAM-BDY-A", priority_region="boundary"),
    )

    analysis = analyze_ranking(evaluations, load_evaluation_rubric(), seed=23)

    assert [record.family_id for record in analysis.records] == [
        "FAM-A",
        "FAM-BDY-A",
        "FAM-BDY-Z",
        "FAM-EX",
        "FAM-UNK",
    ]
    assert len(analysis.by_family) == len(evaluations)
    for family_id in ("FAM-BDY-A", "FAM-BDY-Z", "FAM-EX", "FAM-UNK"):
        record = analysis.by_family[family_id]
        assert record.primary_rank is None
        assert record.equal_weight_rank is None
        assert record.rank_interval is None
        assert record.sampled_rank_median is None


def test_duplicate_canonical_family_is_rejected():
    evaluation = _evaluation("FAM-DUPLICATE")

    with pytest.raises(RankingAnalysisError, match="duplicate family ID"):
        analyze_ranking(
            (evaluation, evaluation), load_evaluation_rubric(), seed=29
        )


def test_leave_one_paper_out_reports_rank_range():
    concentrated = _evaluation(
        "FAM-CONCENTRATED",
        states={"condition_compatibility": "contradiction"},
        papers_by_dimension={"condition_compatibility": ("paper-b",)},
    )
    distributed = _evaluation(
        "FAM-DISTRIBUTED",
        states={
            dimension: "conditional_support"
            for dimension in DIMENSIONS
        },
        papers_by_dimension={dimension: ("paper-b",) for dimension in DIMENSIONS},
        priority_region="priority_b",
    )

    analysis = analyze_ranking(
        (concentrated, distributed), load_evaluation_rubric(), seed=31
    )

    record = analysis.by_family["FAM-CONCENTRATED"]
    assert record.leave_one_paper_out_interval == (1, 1)
    assert record.leave_one_paper_out_range == (1, 1)
    assert {stress.source_paper for stress in record.leave_one_paper_out_stress} == {
        "paper-a",
        "paper-b",
    }
    assert any(
        stress.disposition == "unknown"
        for stress in record.leave_one_paper_out_stress
    )
    assert record.stability_label == "paper_sensitive"


def test_leave_one_out_uses_frozen_source_map_for_opaque_evidence_ids():
    concentrated = _evaluation(
        "FAM-OPAQUE-CONCENTRATED",
        states={"condition_compatibility": "contradiction"},
        papers_by_dimension={
            dimension: (
                "paper-b.pdf",
            )
            if dimension == "condition_compatibility"
            else ("paper-a.pdf",)
            for dimension in DIMENSIONS
        },
        opaque_ids=True,
    )
    distributed = _evaluation(
        "FAM-OPAQUE-DISTRIBUTED",
        states={dimension: "conditional_support" for dimension in DIMENSIONS},
        papers_by_dimension={dimension: ("paper-b.pdf",) for dimension in DIMENSIONS},
        opaque_ids=True,
        priority_region="priority_b",
    )

    analysis = analyze_ranking(
        (concentrated, distributed), load_evaluation_rubric(), seed=35
    )

    record = analysis.by_family["FAM-OPAQUE-CONCENTRATED"]
    assert record.leave_one_paper_out_range == (1, 1)
    assert {stress.source_paper for stress in record.leave_one_paper_out_stress} == {
        "paper-a.pdf",
        "paper-b.pdf",
    }
    assert record.stability_label == "paper_sensitive"


def test_canonical_projection_cannot_bypass_scored_evidence_gate():
    canonical = _evaluation("FAM-CANONICAL").to_canonical()

    with pytest.raises(RankingAnalysisError, match="ScoredFamilyEvaluation"):
        analyze_ranking((canonical,), load_evaluation_rubric(), seed=37)  # type: ignore[arg-type]


def test_unvalidated_rubric_copy_cannot_bypass_frozen_sensitivity_policy():
    rubric = load_evaluation_rubric()
    bounds = dict(rubric.ranking_weight_bounds)
    bounds["evidence_quality"] = (-1.0, 1.0)
    tampered = rubric.model_copy(update={"ranking_weight_bounds": bounds})

    with pytest.raises(RankingAnalysisError, match="valid EvaluationRubric"):
        analyze_ranking((_evaluation("FAM-A"),), tampered, seed=41)


@pytest.mark.parametrize("mutation", ("weights", "bounds", "sample_count", "stability"))
def test_structurally_valid_rubric_change_fails_canonical_digest_binding(
    mutation: str,
):
    rubric = load_evaluation_rubric()
    evaluation = _evaluation("FAM-RUBRIC-BOUND")
    if mutation == "weights":
        altered = rubric.model_copy(
            update={
                "ranking_weights": {
                    **rubric.ranking_weights,
                    "evidence_quality": 0.9,
                }
            }
        )
    elif mutation == "bounds":
        altered = rubric.model_copy(
            update={
                "ranking_weight_bounds": {
                    **rubric.ranking_weight_bounds,
                    "evidence_quality": (0.5, 1.2),
                }
            }
        )
    elif mutation == "sample_count":
        altered = rubric.model_copy(
            update={"ranking_sample_count": rubric.ranking_sample_count + 1}
        )
    else:
        altered = rubric.model_copy(update={"ranking_stability_max_span": 1})

    with pytest.raises(RankingAnalysisError, match="rubric.*attestation"):
        analyze_ranking((evaluation,), altered, seed=42)


@pytest.mark.parametrize("tamper", ("model_construct", "model_copy"))
def test_unattested_scored_tamper_fails_ranking(tamper: str):
    rubric = load_evaluation_rubric()
    evaluation = _evaluation("FAM-SCORED-BOUND")
    if tamper == "model_construct":
        forged = ScoredFamilyEvaluation.model_construct(
            **evaluation.model_dump(mode="python")
        )
    else:
        forged = evaluation.model_copy(update={"family_id": "FAM-FORGED"})

    with pytest.raises(RankingAnalysisError, match="attestation"):
        analyze_ranking((forged,), rubric, seed=42)


def test_fixed_seed_output_is_byte_stable_under_input_reordering():
    evaluations = (
        _evaluation("FAM-Z", priority_region="boundary"),
        _evaluation("FAM-A"),
        _evaluation(
            "FAM-B",
            states={"target_selectivity": "conditional_support"},
            priority_region="priority_b",
        ),
    )
    rubric = load_evaluation_rubric()

    forward = analyze_ranking(evaluations, rubric, seed=43)
    reverse = analyze_ranking(tuple(reversed(evaluations)), rubric, seed=43)

    assert forward.model_dump_json() == reverse.model_dump_json()


def test_noncritical_unknown_is_missing_not_zero_in_numeric_ranking():
    missing = _evaluation(
        "FAM-MISSING",
        states={"target_selectivity": "unknown"},
        priority_region="priority_b",
    )
    contradicted = _evaluation(
        "FAM-CONTRADICTED",
        states={"target_selectivity": "contradiction"},
        priority_region="priority_c",
    )

    analysis = analyze_ranking(
        (contradicted, missing), load_evaluation_rubric(), seed=47
    )

    assert analysis.by_family["FAM-MISSING"].primary_rank == 1
    assert analysis.by_family["FAM-CONTRADICTED"].primary_rank == 2


def test_counterevidence_only_source_is_enumerated_and_reaggregated():
    evaluation = _evaluation(
        "FAM-MIXED",
        states={"condition_compatibility": "conditional_support"},
        papers_by_dimension={
            dimension: ("paper-a",) for dimension in DIMENSIONS
        },
        counter_papers_by_dimension={
            "condition_compatibility": ("paper-counter-only",)
        },
        priority_region="priority_b",
    )

    record = analyze_ranking(
        (evaluation,), load_evaluation_rubric(), seed=53
    ).by_family["FAM-MIXED"]
    by_paper = {
        stress.source_paper: stress for stress in record.leave_one_paper_out_stress
    }

    assert "paper-counter-only" in by_paper
    assert by_paper["paper-counter-only"].dimension_states[
        "condition_compatibility"
    ] == "conditional_support"
    assert by_paper["paper-a"].dimension_states[
        "condition_compatibility"
    ] == "contradiction"


def test_single_paper_rank_change_is_compared_with_primary_and_not_stable():
    concentrated = _evaluation("FAM-PRIMARY-FIRST")
    resilient = _evaluation(
        "FAM-PRIMARY-SECOND",
        states={dimension: "conditional_support" for dimension in DIMENSIONS},
        papers_by_dimension={dimension: (None,) for dimension in DIMENSIONS},
        priority_region="priority_b",
    )

    analysis = analyze_ranking(
        (concentrated, resilient), load_evaluation_rubric(), seed=59
    )
    record = analysis.by_family["FAM-PRIMARY-SECOND"]

    assert record.primary_rank == 2
    assert tuple(
        (stress.source_paper, stress.rank)
        for stress in record.leave_one_paper_out_stress
    ) == (("paper-a", 1),)
    assert record.stability_label != "stable"
    assert record.leave_one_paper_out_range == (1, 2)


def test_paper_omission_that_removes_critical_evidence_is_explicit_unknown():
    concentrated = _evaluation("FAM-BECOMES-UNKNOWN")
    resilient = _evaluation(
        "FAM-REMAINS-TESTABLE",
        states={dimension: "conditional_support" for dimension in DIMENSIONS},
        papers_by_dimension={dimension: (None,) for dimension in DIMENSIONS},
        priority_region="priority_b",
    )

    record = analyze_ranking(
        (concentrated, resilient), load_evaluation_rubric(), seed=61
    ).by_family["FAM-BECOMES-UNKNOWN"]
    stress = record.leave_one_paper_out_stress[0]

    assert stress.source_paper == "paper-a"
    assert stress.priority_region == "unknown"
    assert stress.disposition == "unknown"
    assert stress.rank is None
    assert record.stability_label != "stable"
    with pytest.raises(TypeError):
        stress.dimension_states["elementary_step_match"] = "support"  # type: ignore[index]


def test_omission_preserves_unaffected_conditional_dimension_and_rank():
    affected = _evaluation(
        "FAM-AFFECTED",
        states={"condition_compatibility": "conditional_support"},
        papers_by_dimension={
            dimension: (
                ("paper-a",)
                if dimension == "target_selectivity"
                else ("paper-b",)
                if dimension == "condition_compatibility"
                else (None,)
            )
            for dimension in DIMENSIONS
        },
        priority_region="priority_b",
    )
    comparator = _evaluation(
        "FAM-COMPARATOR",
        states={"evidence_quality": "conditional_support"},
        papers_by_dimension={dimension: (None,) for dimension in DIMENSIONS},
        priority_region="priority_b",
    )

    analysis = analyze_ranking(
        (affected, comparator), load_evaluation_rubric(), seed=67
    )
    record = analysis.by_family["FAM-AFFECTED"]
    stress = next(
        item for item in record.leave_one_paper_out_stress
        if item.source_paper == "paper-a"
    )

    assert record.primary_rank == 2
    assert stress.dimension_states["target_selectivity"] == "unknown"
    assert stress.dimension_states["condition_compatibility"] == "conditional_support"
    assert stress.compatibility_index == 3.5
    assert stress.uncertainty_burden == pytest.approx(6 / 7)
    assert stress.priority_region == "priority_b"
    assert stress.rank == 2


def test_affected_dimension_preserves_remaining_conditional_contribution():
    evaluation = _evaluation(
        "FAM-DIRECT-CONDITIONAL",
        states={"condition_compatibility": "conditional_support"},
        papers_by_dimension={
            dimension: (
                ("paper-a", "paper-b")
                if dimension == "condition_compatibility"
                else (None,)
            )
            for dimension in DIMENSIONS
        },
        priority_region="priority_b",
    )

    record = analyze_ranking(
        (evaluation,), load_evaluation_rubric(), seed=71
    ).by_family["FAM-DIRECT-CONDITIONAL"]
    stress = next(
        item for item in record.leave_one_paper_out_stress
        if item.source_paper == "paper-a"
    )

    assert stress.dimension_states["condition_compatibility"] == "conditional_support"
    assert stress.compatibility_index == 3.6
    assert stress.uncertainty_burden == pytest.approx(2 / 7)


def test_ranking_analysis_attests_exact_scored_evaluations_and_rubric():
    evaluations = (
        _evaluation("FAM-ATTEST-A"),
        _evaluation("FAM-ATTEST-B", priority_region="boundary"),
    )
    rubric = load_evaluation_rubric()

    analysis = analyze_ranking(evaluations, rubric, seed=73)

    assert verify_ranking_analysis(analysis, evaluations, rubric) is analysis
    assert analysis.rubric_digest == evaluations[0].rubric_digest
    assert analysis.context_digest == evaluations[0].context_digest
    assert len(analysis.evaluations_digest) == 64
    assert len(analysis.content_digest) == 64
    assert {
        record.family_id: record.evaluation_digest for record in analysis.records
    } == {
        evaluation.family_id: evaluation.scored_content_digest
        for evaluation in evaluations
    }


@pytest.mark.parametrize("tamper", ("analysis_copy", "nested_record"))
def test_unattested_or_nested_tampered_ranking_analysis_is_rejected(tamper: str):
    evaluation = _evaluation("FAM-ANALYSIS-TAMPER")
    rubric = load_evaluation_rubric()
    analysis = analyze_ranking((evaluation,), rubric, seed=79)
    if tamper == "analysis_copy":
        candidate = analysis.model_copy(update={"seed": 80})
    else:
        forged_record = analysis.records[0].model_copy(
            update={"rationale": "Synthetic altered rationale."}
        )
        candidate = analysis.model_copy(update={"records": (forged_record,)})

    with pytest.raises(RankingAnalysisError, match="attestation"):
        verify_ranking_analysis(candidate, (evaluation,), rubric)


def test_ranking_analysis_rejects_same_family_with_different_evaluation_content():
    original = _evaluation("FAM-EVALUATION-BIND")
    replacement = _evaluation(
        "FAM-EVALUATION-BIND",
        states={"target_selectivity": "conditional_support"},
        priority_region="priority_b",
    )
    rubric = load_evaluation_rubric()
    analysis = analyze_ranking((original,), rubric, seed=83)

    with pytest.raises(RankingAnalysisError, match="evaluation digest"):
        verify_ranking_analysis(analysis, (replacement,), rubric)

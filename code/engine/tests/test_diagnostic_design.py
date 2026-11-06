from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence

import pytest
from pydantic import ValidationError

import pipeline.family_evaluation as family_evaluation_module
from pipeline.diagnostic_design import (
    BoundaryFalsificationRecord,
    DiagnosticDesignError,
    DiagnosticDesignProposal,
    DiagnosticAnalytics,
    DiagnosticSuccessRecord,
    ExecutionResultInput,
    FamilyDiagnosticPlan,
    ProposedRepresentativeState,
    ReadinessVerificationInput,
    RepresentativeInventoryInput,
    RepresentativeInventoryRecord,
    RepresentativeReadinessRecord,
    design_family_diagnostics,
    record_diagnostic_result,
    record_representative_inventory,
    record_representative_readiness,
    verify_family_diagnostic_plan,
)
from pipeline.family_canonicalization import CanonicalFamily, ProposalProvenance
from pipeline.family_evaluation import (
    EvidenceContribution,
    DimensionPrincipleLink,
    QualifiedBlocker,
    QualifiedEvidenceRecord,
    ReviewedPrincipleLink,
    ScoredFamilyEvaluation,
    load_evaluation_rubric,
    verify_scored_family_evaluation,
)
from pipeline.leakage_audit import (
    StructureFingerprintFactory,
    build_structure_fingerprint_factory,
    derive_structure_fingerprint,
)
from pipeline.principle_models import PrincipleProvenance, ReactionPrinciple
from pipeline.ranking_robustness import RankingAnalysis, analyze_ranking
from pipeline.taxonomy_discovery import MechanisticProposalDefinition
from pipeline.v3_models import DIMENSIONS, DimensionJudgment, FamilyEvaluation
from tests.test_family_evaluation import _all_supporting_judgments, _build_context, _score


_PRINCIPLE_ID = "PRINCIPLE-SYNTHETIC"
_TRUSTED_BASE: ScoredFamilyEvaluation | None = None


@pytest.fixture(scope="module", autouse=True)
def _trusted_scored_base(tmp_path_factory: pytest.TempPathFactory):
    global _TRUSTED_BASE
    context = _build_context(tmp_path_factory.mktemp("diagnostic-trust"))
    _TRUSTED_BASE = _score(_all_supporting_judgments(), context)
    yield
    _TRUSTED_BASE = None


def _digest(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _principle(**updates: object) -> ReactionPrinciple:
    values: dict[str, object] = {
        "principle_id": _PRINCIPLE_ID,
        "principle_layer": "transferable_super",
        "title": "Synthetic transfer rule",
        "status": "accepted",
        "claim": "A synthetic reactive state can test the proposed step.",
        "mechanistic_basis": ["synthetic elementary step"],
        "applicable_electrophile_families": ["synthetic electrophile class"],
        "applicable_nucleophile_families": ["synthetic variable-role class"],
        "applicable_nucleophile_superclasses": [],
        "required_reactive_form": "synthetic reactive state",
        "catalyst_requirements": ["synthetic catalyst state"],
        "condition_window": ["synthetic mild window"],
        "structural_promoters": ["synthetic promoter feature"],
        "structural_inhibitors": ["synthetic inhibitor feature"],
        "supporting_seed_evidence": ["SEED-SYNTHETIC"],
        "supporting_transferred_evidence": ["EV-JUDGMENT"],
        "contradictory_evidence": [],
        "known_exceptions": [],
        "predicted_failure_modes": ["synthetic competing pathway"],
        "confidence": "medium",
        "experimental_consequence": "Use a one-factor synthetic matched pair.",
        "falsifying_experiment": "Observe no target product in the matched pair.",
        "review_status": "accepted",
        "provenance": PrincipleProvenance(run_id="RUN-SYNTHETIC"),
        "freeze_version": "Freeze 2",
    }
    values.update(updates)
    return ReactionPrinciple.model_validate(values)


def _principle_digest(principle: ReactionPrinciple) -> str:
    return _digest(principle.model_dump(mode="json"))


def _evidence_record(
    evidence_id: str,
    *,
    dimensions: tuple[str, ...] = DIMENSIONS,
    linked: bool = True,
) -> QualifiedEvidenceRecord:
    return QualifiedEvidenceRecord(
        evidence_id=evidence_id,
        evidence_class="external_literature",
        source_path=f"papers/{evidence_id.casefold()}.pdf",
        provenance_path=f"derived/{evidence_id.casefold()}.json",
        locator="page 1, synthetic paragraph",
        evidence_level="traceable_external_evidence",
        admissible_dimensions=dimensions,
        reviewed_principle_links=(
            (
                ReviewedPrincipleLink(
                    principle_id=_PRINCIPLE_ID,
                    admissible_dimensions=dimensions,
                ),
            )
            if linked
            else ()
        ),
    )


def _evidence(*ids: str) -> tuple[QualifiedEvidenceRecord, ...]:
    selected = ids or ("EV-FAMILY", "EV-JUDGMENT")
    return tuple(_evidence_record(evidence_id) for evidence_id in selected)


def _family(
    family_id: str = "FAM-SYNTHETIC-A",
    *,
    family_evidence_ids: tuple[str, ...] = ("EV-FAMILY",),
    candidates: tuple[str, ...] = (
        "synthetic state alpha",
        "synthetic state beta",
        "synthetic state gamma",
        "synthetic state delta",
    ),
) -> CanonicalFamily:
    definition = MechanisticProposalDefinition(
        nucleophilic_center="synthetic center",
        reactive_state="synthetic reactive state",
        bond_forming_mode="synthetic bond-forming mode",
        activation_mode="synthetic activation mode",
        critical_conditions=("synthetic dry medium", "synthetic mild activation"),
        dominant_failure_modes=("synthetic competing pathway",),
    )
    return CanonicalFamily(
        family_id=family_id,
        **definition.model_dump(),
        proposal_ids=(f"PROP-{family_id}",),
        proposal_provenance=(
            ProposalProvenance(
                proposal_id=f"PROP-{family_id}",
                lane_id="LANE-SYNTHETIC",
                channel="model_hypothesis",
                round_id=1,
                evidence_level="traceable_external_evidence",
                evidence_ids=family_evidence_ids,
            ),
        ),
        evidence_ids=family_evidence_ids,
        aliases=(f"alias-{family_id}",),
        representative_reactive_state_candidates=candidates,
        mechanistic_definition_candidates=(definition,),
    )


def _raw_evaluation(
    family_id: str = "FAM-SYNTHETIC-A",
    *,
    unknown: bool = False,
    excluded: bool = False,
) -> FamilyEvaluation:
    return FamilyEvaluation(
        family_id=family_id,
        judgments=tuple(
            DimensionJudgment(
                dimension=dimension,
                state=(
                    "unknown"
                    if unknown and dimension == "reactive_state_accessibility"
                    else "contradiction"
                    if excluded and dimension == "condition_compatibility"
                    else "support"
                ),
                evidence_ids=(
                    ()
                    if unknown and dimension == "reactive_state_accessibility"
                    else ("EV-JUDGMENT",)
                ),
                rationale=f"Synthetic assessment of {dimension}.",
                counterevidence_ids=(),
                unresolved_questions=(
                    ("Acquire synthetic state evidence.",)
                    if unknown and dimension == "reactive_state_accessibility"
                    else ()
                ),
            )
            for dimension in DIMENSIONS
        ),
        critical_unknowns=(
            ("reactive_state_accessibility",) if unknown else ()
        ),
        qualified_blocker_ids=(("BLOCK-SYNTHETIC",) if excluded else ()),
    )


def _scored_evaluation(
    family_id: str = "FAM-SYNTHETIC-A",
    *,
    region: str = "priority_a",
    judgment_evidence_id: str = "EV-JUDGMENT",
    family_evidence_id: str = "EV-FAMILY",
    counterevidence_id: str | None = None,
) -> ScoredFamilyEvaluation:
    assert _TRUSTED_BASE is not None
    principle = _principle()
    evidence_ids = tuple(
        dict.fromkeys((judgment_evidence_id, family_evidence_id))
    )
    unknown_dimension = (
        "reactive_state_accessibility" if region == "unknown" else None
    )
    judgments = tuple(
        DimensionJudgment(
            dimension=dimension,
            state=(
                "unknown"
                if dimension == unknown_dimension
                else
                "contradiction"
                if dimension == "competing_pathway_risk"
                else "support"
            ),
            evidence_ids=(() if dimension == unknown_dimension else evidence_ids),
            rationale=f"Synthetic assessment of {dimension}.",
            counterevidence_ids=(
                (counterevidence_id,)
                if counterevidence_id is not None
                and dimension == "condition_compatibility"
                else ()
            ),
            unresolved_questions=(),
        )
        for dimension in DIMENSIONS
    )
    source_ids = set(evidence_ids)
    if region == "excluded":
        source_ids.add("EV-BLOCKER")
    if counterevidence_id:
        source_ids.add(counterevidence_id)
    source_paths = {
        evidence_id: f"papers/{evidence_id.casefold()}.pdf"
        for evidence_id in source_ids
    }
    links = {
        evidence_id: (
            ReviewedPrincipleLink(
                principle_id=_PRINCIPLE_ID,
                admissible_dimensions=DIMENSIONS,
            ),
        )
        for evidence_id in source_ids
    }
    contributions = tuple(
        EvidenceContribution(
            dimension=judgment.dimension,
            evidence_id=evidence_id,
            source_paper=source_paths[evidence_id],
            direction=(
                "adverse"
                if is_counter or judgment.state == "contradiction"
                else "positive"
            ),
            state="contradiction" if is_counter else judgment.state,
            evidence_class="external_literature",
            evidence_level="traceable_external_evidence",
            is_external=True,
            quality_eligible=True,
            is_counterevidence=is_counter,
        )
        for judgment in judgments
        for evidence_id, is_counter in (
            *((item, False) for item in judgment.evidence_ids),
            *((item, True) for item in judgment.counterevidence_ids),
        )
    )
    scores = {
        dimension: (
            None
            if dimension == unknown_dimension
            else 0
            if dimension == "competing_pathway_risk"
            else 4
        )
        for dimension in DIMENSIONS
    }
    qualified_blockers = (
        (
            QualifiedBlocker(
                blocker_id="BLOCK-SYNTHETIC",
                dimension="condition_compatibility",
                statement="Synthetic qualified blocker.",
                evidence_ids=("EV-BLOCKER",),
                counterevidence_ids=(),
                source_paths=(source_paths["EV-BLOCKER"],),
                reviewed_principle_ids=(_PRINCIPLE_ID,),
            ),
        )
        if region == "excluded"
        else ()
    )
    evaluation = family_evaluation_module._build_scored_evaluation(
        family_id=family_id,
        judgments=judgments,
        dimension_scores=scores,
        compatibility_index=(None if region == "excluded" else 4),
        evidence_confidence=4,
        uncertainty_burden=0,
        failure_risk=0,
        critical_unknowns=((unknown_dimension,) if unknown_dimension else ()),
        qualified_blocker_ids=tuple(
            blocker.blocker_id for blocker in qualified_blockers
        ),
        qualified_blockers=qualified_blockers,
        reviewed_principle_ids=(_PRINCIPLE_ID,),
        reviewed_principle_digests={
            _PRINCIPLE_ID: _principle_digest(principle)
        },
        evidence_principle_links=links,
        dimension_principle_links=tuple(
            sorted(
                {
                    DimensionPrincipleLink(
                        evidence_id=evidence_id,
                        dimension=judgment.dimension,
                        principle_id=_PRINCIPLE_ID,
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
                        principle_id=_PRINCIPLE_ID,
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
            evidence_id: _digest(
                _evidence_record(evidence_id).model_dump(mode="json")
            )
            for evidence_id in source_ids
        },
        evidence_source_paths=source_paths,
        evidence_contributions=contributions,
        rubric_digest=_TRUSTED_BASE.rubric_digest,
        context_digest=_TRUSTED_BASE.context_digest,
        priority_region=region,
    )
    assert verify_scored_family_evaluation(
        evaluation, load_evaluation_rubric()
    ) is evaluation
    return evaluation


def _condition_scoped_inputs() -> tuple[
    ScoredFamilyEvaluation,
    tuple[ReactionPrinciple, ...],
    tuple[QualifiedEvidenceRecord, ...],
]:
    base = _scored_evaluation()
    outside = _principle(
        principle_id="PRINCIPLE-OUTSIDE-CONDITIONS",
        catalyst_requirements=("excluded catalyst requirement",),
        condition_window=("excluded condition window",),
    )
    condition = _principle(
        principle_id="PRINCIPLE-CONDITION-COMPATIBILITY",
        catalyst_requirements=("trusted catalyst requirement",),
        condition_window=("trusted condition window",),
    )
    non_condition_dimensions = tuple(
        dimension for dimension in DIMENSIONS if dimension != "condition_compatibility"
    )
    reviewed_links = (
        ReviewedPrincipleLink(
            principle_id=outside.principle_id,
            admissible_dimensions=non_condition_dimensions,
        ),
        ReviewedPrincipleLink(
            principle_id=condition.principle_id,
            admissible_dimensions=("condition_compatibility",),
        ),
    )
    evidence = tuple(
        _evidence_record(evidence_id).model_copy(
            update={"reviewed_principle_links": reviewed_links}
        )
        for evidence_id in base.evidence_principle_links
    )
    evidence_by_id = {record.evidence_id: record for record in evidence}
    dimension_links = tuple(
        DimensionPrincipleLink(
            evidence_id=evidence_id,
            dimension=judgment.dimension,
            principle_id=(
                condition.principle_id
                if judgment.dimension == "condition_compatibility"
                else outside.principle_id
            ),
        )
        for judgment in base.judgments
        for evidence_id in (*judgment.evidence_ids, *judgment.counterevidence_ids)
    )
    evaluation = family_evaluation_module._build_scored_evaluation(
        family_id=base.family_id,
        judgments=base.judgments,
        dimension_scores=base.dimension_scores,
        compatibility_index=base.compatibility_index,
        evidence_confidence=base.evidence_confidence,
        uncertainty_burden=base.uncertainty_burden,
        failure_risk=base.failure_risk,
        critical_unknowns=base.critical_unknowns,
        qualified_blocker_ids=base.qualified_blocker_ids,
        qualified_blockers=base.qualified_blockers,
        reviewed_principle_ids=tuple(
            sorted((outside.principle_id, condition.principle_id))
        ),
        reviewed_principle_digests={
            outside.principle_id: _principle_digest(outside),
            condition.principle_id: _principle_digest(condition),
        },
        evidence_principle_links={
            evidence_id: reviewed_links for evidence_id in evidence_by_id
        },
        dimension_principle_links=dimension_links,
        evidence_record_digests={
            evidence_id: _digest(record.model_dump(mode="json"))
            for evidence_id, record in evidence_by_id.items()
        },
        evidence_source_paths=base.evidence_source_paths,
        evidence_contributions=base.evidence_contributions,
        rubric_digest=base.rubric_digest,
        context_digest=base.context_digest,
        priority_region=base.priority_region,
    )
    assert verify_scored_family_evaluation(
        evaluation, load_evaluation_rubric()
    ) is evaluation
    return evaluation, (outside, condition), evidence


def _ranking(*evaluations: ScoredFamilyEvaluation) -> RankingAnalysis:
    return analyze_ranking(evaluations, load_evaluation_rubric(), seed=17)


def _synthetic_structure_input(subject: str) -> str:
    atom_map = int(hashlib.sha256(subject.encode()).hexdigest()[:6], 16)
    return f"[CH4:{atom_map}]"


def _fingerprint(reactive_state: str) -> str:
    return derive_structure_fingerprint(
        _STRUCTURE_FACTORY, _synthetic_structure_input(reactive_state)
    )


_STRUCTURE_FACTORY = build_structure_fingerprint_factory(
    factory_id="synthetic-structure-factory",
    receipt_key=b"synthetic-structure-receipt-key",
)


def _candidate(
    state_id: str,
    reactive_state: str,
    *,
    coverage: tuple[str, ...] = (
        "nucleophilic_center",
        "reactive_state",
        "bond_forming_mode",
        "activation_mode",
    ),
    contrasts: tuple[str, ...] = ("synthetic competing pathway",),
    availability: str = "verified_available",
    handling_status: str = "cleared",
) -> dict[str, object]:
    fingerprint = _fingerprint(reactive_state)
    return {
        "state_id": state_id,
        "reactive_state": reactive_state,
        "mechanistic_coordinate_coverage": coverage,
        "diagnostic_contrasts": contrasts,
        "structural_fingerprint": fingerprint,
        "cluster_key": f"cluster-{fingerprint[:12]}",
        "availability_state": availability,
        "handling_prerequisites": [
            {
                "prerequisite_id": f"HANDLE-{state_id}",
                "description": "Synthetic dry handling prerequisite.",
                "status": handling_status,
            }
        ],
    }


def _conditions() -> list[dict[str, str]]:
    baseline = {
        "state_id": "COND-SYNTHETIC-BASE",
        "protonation_state": "synthetic protonation state alpha",
        "catalyst_state": "synthetic catalyst state",
        "medium_state": "synthetic dry medium",
        "temperature_state": "synthetic temperature",
        "concentration_state": "synthetic concentration",
        "atmosphere_state": "synthetic atmosphere",
        "time_state": "synthetic time",
    }
    comparison = {
        **baseline,
        "state_id": "COND-SYNTHETIC-CONTROL",
        "protonation_state": "synthetic protonation state beta",
    }
    return [baseline, comparison]


def _proposal(
    *candidates: dict[str, object],
    family_id: str = "FAM-SYNTHETIC-A",
) -> DiagnosticDesignProposal:
    return DiagnosticDesignProposal.model_validate(
        {
            "family_id": family_id,
            "representative_states": candidates,
            "condition_states": (),
        }
    )


def _inventory(
    candidate: dict[str, object] | ProposedRepresentativeState,
    *,
    family: CanonicalFamily | None = None,
    structure_input: str | None = None,
    coverage: tuple[str, ...] | None = None,
    contrasts: tuple[str, ...] | None = None,
    evidence_ids: tuple[str, ...] | None = None,
    canonicalizer: object | None = None,
) -> RepresentativeInventoryRecord:
    selected_family = family or _family()
    state = (
        candidate
        if isinstance(candidate, ProposedRepresentativeState)
        else ProposedRepresentativeState.model_validate(candidate)
    )
    if canonicalizer is not None and not isinstance(
        canonicalizer, StructureFingerprintFactory
    ):
        raise TypeError("test inventory requires the fixed structure factory")
    structure_factory = canonicalizer or _STRUCTURE_FACTORY
    return record_representative_inventory(
        selected_family,
        RepresentativeInventoryInput(
            inventory_id=f"VERIFIED-{state.state_id}",
            family_id=selected_family.family_id,
            state_id=state.state_id,
            reactive_state=state.reactive_state,
            structure_input=structure_input
            or _synthetic_structure_input(state.reactive_state),
            mechanistic_coordinate_coverage=coverage
            or (
                "nucleophilic_center",
                "reactive_state",
                "bond_forming_mode",
                "activation_mode",
            ),
            diagnostic_contrasts=contrasts
            or selected_family.dominant_failure_modes,
            availability_state=(
                "unavailable"
                if state.availability_state == "unavailable"
                else "needs_verification"
            ),
            evidence_ids=evidence_ids or (selected_family.evidence_ids[0],),
            inventory_artifact_digest="9" * 64,
        ),
        structure_factory,
    )


def _readiness(
    candidate: dict[str, object],
    *,
    family: CanonicalFamily | None = None,
    inventory: RepresentativeInventoryRecord | None = None,
    verification_id: str | None = None,
    handling_artifact_digest: str = "d" * 64,
) -> RepresentativeReadinessRecord:
    selected_family = family or _family()
    state = ProposedRepresentativeState.model_validate(candidate)
    inventory_record = inventory or _inventory(state, family=selected_family)
    return record_representative_readiness(
        selected_family,
        state,
        ReadinessVerificationInput(
            verification_id=verification_id or f"VERIFY-{state.state_id}",
            family_id=selected_family.family_id,
            state_id=state.state_id,
            availability_verified=True,
            cleared_prerequisite_ids=tuple(
                sorted(
                    {
                        *(
                            prerequisite.prerequisite_id
                            for prerequisite in state.handling_prerequisites
                        ),
                        *(
                            f"HANDLE-{selected_family.family_id}-{index}"
                            for index, _ in enumerate(
                                selected_family.critical_conditions, start=1
                            )
                        ),
                    }
                )
            ),
            inventory_artifact_digest=inventory_record.inventory_artifact_digest,
            handling_artifact_digest=handling_artifact_digest,
        ),
        inventory_record,
    )


def _inventories_for_family(
    family: CanonicalFamily,
) -> tuple[RepresentativeInventoryRecord, ...]:
    return tuple(
        _inventory(
            _candidate(f"STATE-{family.family_id}-{index}", reactive_state),
            family=family,
        )
        for index, reactive_state in enumerate(
            family.representative_reactive_state_candidates, start=1
        )
    )


def _plan(
    *,
    region: str = "priority_a",
    proposal: DiagnosticDesignProposal | None = None,
    records: Sequence[object] = (),
    inventory: Sequence[RepresentativeInventoryRecord] = (),
    readiness: Sequence[RepresentativeReadinessRecord] = (),
) -> FamilyDiagnosticPlan:
    evaluation = _scored_evaluation(region=region)
    family = _family()
    selected_inventory = tuple(inventory)
    if not selected_inventory and region not in {"excluded", "unknown"}:
        proposal_candidates = (
            proposal.representative_states if proposal is not None else ()
        )
        if proposal_candidates:
            selected_inventory = tuple(
                _inventory(candidate, family=family)
                for candidate in proposal_candidates
            )
        else:
            selected_inventory = _inventories_for_family(family)
    return design_family_diagnostics(
        (family,),
        (evaluation,),
        (_principle(),),
        _evidence(),
        _ranking(evaluation),
        proposals=((proposal,) if proposal else ()),
        diagnostic_records=records,
        inventory_records=selected_inventory,
        readiness_records=readiness,
    )[0]


@pytest.mark.parametrize("region", ("priority_a", "priority_b", "priority_c"))
def test_each_priority_region_gets_one_to_three_representatives(region: str):
    plan = _plan(region=region)

    assert plan.chemistry_planned is True
    assert 1 <= len(plan.representatives) <= 3
    assert plan.plan_role == "diagnostic"


def test_boundary_is_an_explicit_negative_control_with_distinct_semantics():
    plan = _plan(region="boundary")

    assert plan.chemistry_planned is True
    assert plan.plan_role == "negative_control"
    assert plan.negative_control_label
    assert plan.expected_outcome == "target_product_absent"


@pytest.mark.parametrize(
    ("evaluation", "expected_role"),
    [
        (_raw_evaluation(excluded=True), "no_experiment"),
        (_raw_evaluation(unknown=True), "evidence_first"),
    ],
)
def test_raw_evaluation_cannot_assign_non_chemistry_disposition(
    evaluation: FamilyEvaluation, expected_role: str
):
    with pytest.raises(DiagnosticDesignError, match="attested scored evaluation"):
        design_family_diagnostics(
            (_family(),),
            (evaluation,),
            (),
            (_evidence_record("EV-FAMILY", linked=False),),
        )


@pytest.mark.parametrize(
    ("region", "expected_role"),
    [("excluded", "no_experiment"), ("unknown", "evidence_first")],
)
def test_attested_scored_non_chemistry_regions_keep_non_chemistry_disposition(
    region: str, expected_role: str
):
    evaluation = _scored_evaluation(region=region)

    plan = design_family_diagnostics(
        (_family(),),
        (evaluation,),
        (),
        _evidence(
            "EV-FAMILY",
            "EV-JUDGMENT",
            *(("EV-BLOCKER",) if region == "excluded" else ()),
        ),
    )[0]

    assert plan.priority_region == region
    assert plan.plan_role == expected_role
    assert plan.chemistry_planned is False
    assert plan.executable is False
    assert plan.evidence_ids == (
        ("EV-BLOCKER", "EV-FAMILY", "EV-JUDGMENT")
        if region == "excluded"
        else ("EV-FAMILY", "EV-JUDGMENT")
    )
    assert plan.principle_evidence_links == {
        _PRINCIPLE_ID: (
            ("EV-BLOCKER", "EV-FAMILY", "EV-JUDGMENT")
            if region == "excluded"
            else ("EV-FAMILY", "EV-JUDGMENT")
        )
    }


def test_all_chemistry_plans_require_canonical_ranking_analysis():
    evaluation = _scored_evaluation(region="boundary")

    with pytest.raises(DiagnosticDesignError, match="ranking analysis"):
        design_family_diagnostics(
            (_family(),),
            (evaluation,),
            (_principle(),),
            _evidence(),
        )


def test_tampered_ranking_analysis_is_rejected():
    evaluation = _scored_evaluation()
    ranking = _ranking(evaluation).model_copy(update={"seed": 99})

    with pytest.raises(DiagnosticDesignError, match="ranking.*attestation"):
        design_family_diagnostics(
            (_family(),),
            (evaluation,),
            (_principle(),),
            _evidence(),
            ranking,
        )


@pytest.mark.parametrize("tamper", ("model_construct", "model_copy"))
def test_unattested_scored_evaluation_is_rejected(tamper: str):
    evaluation = _scored_evaluation()
    ranking = _ranking(evaluation)
    if tamper == "model_construct":
        forged = ScoredFamilyEvaluation.model_construct(
            **evaluation.model_dump(mode="python")
        )
    else:
        forged = evaluation.model_copy(update={"priority_region": "priority_b"})

    with pytest.raises(DiagnosticDesignError, match="evaluation.*attestation"):
        design_family_diagnostics(
            (_family(),),
            (forged,),
            (_principle(),),
            _evidence(),
            ranking,
        )


def test_ranking_record_must_bind_exact_evaluation_digest_and_region():
    ranked = _scored_evaluation(region="priority_a")
    supplied = _scored_evaluation(region="priority_b")

    with pytest.raises(DiagnosticDesignError, match="evaluation digest|region"):
        design_family_diagnostics(
            (_family(),),
            (supplied,),
            (_principle(),),
            _evidence(),
            _ranking(ranked),
        )


def test_mixed_input_order_uses_attested_rank_order():
    family_a = _family("FAM-A", family_evidence_ids=("EV-FAMILY-A",))
    family_b = _family("FAM-B", family_evidence_ids=("EV-FAMILY-B",))
    evaluation_a = _scored_evaluation(
        "FAM-A",
        judgment_evidence_id="EV-J-A",
        family_evidence_id="EV-FAMILY-A",
    )
    evaluation_b = _scored_evaluation(
        "FAM-B",
        region="priority_b",
        judgment_evidence_id="EV-J-B",
        family_evidence_id="EV-FAMILY-B",
    )
    evidence = _evidence("EV-FAMILY-A", "EV-FAMILY-B", "EV-J-A", "EV-J-B")
    ranking = _ranking(evaluation_a, evaluation_b)
    inventory = (
        *_inventories_for_family(family_a),
        *_inventories_for_family(family_b),
    )

    forward = design_family_diagnostics(
        (family_b, family_a),
        (evaluation_b, evaluation_a),
        (_principle(),),
        evidence,
        ranking,
        inventory_records=inventory,
    )
    reverse = design_family_diagnostics(
        (family_a, family_b),
        (evaluation_a, evaluation_b),
        (_principle(),),
        tuple(reversed(evidence)),
        ranking,
        inventory_records=tuple(reversed(inventory)),
    )

    assert [plan.family_id for plan in forward] == ["FAM-A", "FAM-B"]
    assert [plan.family_id for plan in reverse] == ["FAM-A", "FAM-B"]


def test_one_factor_control_is_computed_and_a_second_change_is_rejected():
    proposal = _proposal(
        _candidate("STATE-A", "synthetic state alpha")
    )
    plan = _plan(proposal=proposal)
    assert plan.paired_controls[0].changed_fields == ("protonation_state",)

    payload = plan.paired_controls[0].model_dump(mode="python")
    payload["comparison"]["temperature_state"] = "synthetic hotter state"
    with pytest.raises(DiagnosticDesignError, match="exactly one mechanistic factor"):
        type(plan.paired_controls[0]).model_validate(payload)


def test_model_proposed_condition_values_are_rejected():
    candidate = _candidate("STATE-A", "synthetic state alpha")
    proposal = DiagnosticDesignProposal.model_validate(
        {
            "family_id": "FAM-SYNTHETIC-A",
            "representative_states": (candidate,),
            "condition_states": _conditions(),
        }
    )

    with pytest.raises(DiagnosticDesignError, match="model.*condition"):
        _plan(proposal=proposal)


def test_condition_ids_are_unique_and_derived_inside_plan():
    plan = _plan()

    assert len({condition.state_id for condition in plan.conditions}) == len(
        plan.conditions
    )
    assert all(condition.state_id.startswith(f"COND-{plan.family_id}-") for condition in plan.conditions)


def test_conditions_use_only_dimension_qualified_principles():
    family = _family()
    evaluation, principles, evidence = _condition_scoped_inputs()
    plan = design_family_diagnostics(
        (family,),
        (evaluation,),
        principles,
        evidence,
        _ranking(evaluation),
        inventory_records=_inventories_for_family(family),
    )[0]

    baseline = plan.conditions[0]
    assert "trusted catalyst requirement" in baseline.catalyst_state
    assert "trusted condition window" in baseline.medium_state
    assert "excluded catalyst requirement" not in baseline.catalyst_state
    assert "excluded condition window" not in baseline.medium_state


def test_model_cannot_partition_coverage_or_control_inventory_selection():
    candidate_a = _candidate(
        "STATE-A",
        "synthetic state alpha",
        coverage=("nucleophilic_center", "reactive_state"),
    )
    candidate_b = _candidate(
        "STATE-B",
        "synthetic state beta",
        coverage=("bond_forming_mode", "activation_mode"),
    )
    plan = _plan(proposal=_proposal(candidate_b, candidate_a))

    assert len(plan.representatives) == 1
    assert set(plan.representatives[0].mechanistic_coordinate_coverage) == {
        "nucleophilic_center",
        "reactive_state",
        "bond_forming_mode",
        "activation_mode",
    }


def test_model_candidate_must_match_canonical_state_and_derived_fingerprint():
    wrong_state = _candidate("STATE-X", "unrelated synthetic state")
    wrong_fingerprint = {
        **_candidate("STATE-A", "synthetic state alpha"),
        "structural_fingerprint": "0" * 64,
    }

    with pytest.raises(DiagnosticDesignError, match="inventory.*state"):
        _plan(proposal=_proposal(wrong_state))
    plan = _plan(proposal=_proposal(wrong_fingerprint))
    assert plan.representatives[0].structural_fingerprint != "0" * 64


def test_representative_inventory_requires_factory_attestation():
    with pytest.raises(DiagnosticDesignError, match="inventory.*attestation"):
        RepresentativeInventoryRecord(
            record_id="INVENTORY-FORGED",
            family_id="FAM-SYNTHETIC-A",
            state_id="STATE-A",
            reactive_state="synthetic state alpha",
            mechanistic_coordinate_coverage=("nucleophilic_center",),
            diagnostic_contrasts=("synthetic competing pathway",),
            availability_state="needs_verification",
            structural_fingerprint="a" * 64,
            cluster_key="cluster-forged",
            evidence_ids=("EV-FAMILY",),
            inventory_artifact_digest="b" * 64,
            content_digest="c" * 64,
        )


@pytest.mark.parametrize("tamper", (False, True))
def test_copied_or_tampered_inventory_record_is_rejected(tamper: bool):
    candidate = _candidate("STATE-A", "synthetic state alpha")
    inventory = _inventory(candidate)
    copied = inventory.model_copy(
        update=(
            {"inventory_artifact_digest": "f" * 64}
            if tamper
            else None
        )
    )

    with pytest.raises(DiagnosticDesignError, match="inventory.*attestation"):
        _plan(
            proposal=_proposal(candidate),
            inventory=(copied,),
        )


def test_inventory_canonical_aliases_deduplicate_before_selection():
    candidate_a = _candidate("STATE-A", "synthetic state alpha")
    candidate_b = _candidate("STATE-B", "synthetic state beta")
    candidate_c = _candidate("STATE-C", "synthetic state gamma")

    inventory_a = _inventory(
        candidate_a,
        structure_input="CC",
        coverage=("nucleophilic_center", "reactive_state"),
    )
    inventory_b = _inventory(
        candidate_b,
        structure_input="CCO",
        coverage=("bond_forming_mode", "activation_mode"),
    )
    inventory_c = _inventory(
        candidate_c,
        structure_input="OCC",
        coverage=("bond_forming_mode", "activation_mode"),
    )
    proposal = _proposal(
        {
            **candidate_c,
            "mechanistic_coordinate_coverage": ("nucleophilic_center",),
            "structural_fingerprint": "c" * 64,
        },
        {
            **candidate_b,
            "mechanistic_coordinate_coverage": ("reactive_state",),
            "structural_fingerprint": "b" * 64,
        },
        {
            **candidate_a,
            "mechanistic_coordinate_coverage": (
                "nucleophilic_center",
                "reactive_state",
                "bond_forming_mode",
                "activation_mode",
            ),
            "structural_fingerprint": "a" * 64,
        },
    )

    plan = _plan(
        proposal=proposal,
        inventory=(inventory_c, inventory_a, inventory_b),
    )

    assert inventory_b.structural_fingerprint == inventory_c.structural_fingerprint
    assert inventory_b.cluster_key == inventory_c.cluster_key
    assert tuple(item.state_id for item in plan.representatives) == (
        "STATE-A",
        "STATE-B",
    )
    assert tuple(
        item.mechanistic_coordinate_coverage for item in plan.representatives
    ) == (
        ("nucleophilic_center", "reactive_state"),
        ("bond_forming_mode", "activation_mode"),
    )


def test_inventory_evidence_must_be_attested_evaluation_evidence():
    candidate = _candidate("STATE-A", "synthetic state alpha")
    inventory = _inventory(candidate, evidence_ids=("EV-INVENTORY-UNTRUSTED",))

    with pytest.raises(DiagnosticDesignError, match="inventory evidence"):
        _plan(proposal=_proposal(candidate), inventory=(inventory,))


def test_representative_preserves_exact_inventory_evidence_ids():
    candidate = _candidate("STATE-A", "synthetic state alpha")
    inventory = _inventory(candidate, evidence_ids=("EV-FAMILY",))

    plan = _plan(proposal=_proposal(candidate), inventory=(inventory,))

    assert plan.representatives[0].evidence_ids == inventory.evidence_ids
    assert plan.evidence_ids == ("EV-FAMILY", "EV-JUDGMENT")


def test_needs_verification_is_planned_but_not_executable():
    plan = _plan(
        proposal=_proposal(
            _candidate(
                "STATE-A",
                "synthetic state alpha",
                availability="needs_verification",
            )
        )
    )

    assert plan.chemistry_planned is True
    assert plan.executable is False
    assert {action.action_type for action in plan.operational_actions} == {
        "verify_availability",
        "clear_handling_prerequisite",
    }


def test_model_verified_and_cleared_claims_cannot_make_plan_executable():
    plan = _plan(
        proposal=_proposal(
            _candidate(
                "STATE-A",
                "synthetic state alpha",
                availability="verified_available",
                handling_status="cleared",
            )
        )
    )

    assert plan.executable is False
    assert {action.action_type for action in plan.operational_actions} == {
        "verify_availability",
        "clear_handling_prerequisite",
    }


def test_model_cannot_omit_or_replace_canonical_handling_prerequisites():
    candidate = _candidate("STATE-A", "synthetic state alpha")
    plan = _plan(proposal=_proposal(candidate))
    descriptions = {
        prerequisite.description
        for prerequisite in plan.representatives[0].handling_prerequisites
    }
    assert set(_family().critical_conditions).issubset(descriptions)

    replaced = {
        **candidate,
        "handling_prerequisites": (
            {
                "prerequisite_id": "HANDLE-FAM-SYNTHETIC-A-1",
                "description": "Model replacement of canonical requirement.",
                "status": "cleared",
            },
        ),
    }
    with pytest.raises(DiagnosticDesignError, match="cannot replace canonical"):
        _plan(proposal=_proposal(replaced))


def test_readiness_factory_requires_every_canonical_handling_prerequisite():
    family = _family()
    candidate = ProposedRepresentativeState.model_validate(
        _candidate("STATE-A", "synthetic state alpha")
    )
    inventory = _inventory(candidate, family=family)
    with pytest.raises(DiagnosticDesignError, match="exact candidate prerequisites"):
        record_representative_readiness(
            family,
            candidate,
            ReadinessVerificationInput(
                verification_id="VERIFY-INCOMPLETE",
                family_id=family.family_id,
                state_id=candidate.state_id,
                availability_verified=True,
                cleared_prerequisite_ids=("HANDLE-STATE-A",),
                inventory_artifact_digest="c" * 64,
                handling_artifact_digest="d" * 64,
                ),
                inventory,
            )


def test_readiness_factory_requires_exact_inventory_artifact():
    family = _family()
    candidate = ProposedRepresentativeState.model_validate(
        _candidate("STATE-A", "synthetic state alpha")
    )
    inventory = _inventory(candidate, family=family)

    with pytest.raises(DiagnosticDesignError, match="inventory artifact"):
        record_representative_readiness(
            family,
            candidate,
            ReadinessVerificationInput(
                verification_id="VERIFY-WRONG-INVENTORY",
                family_id=family.family_id,
                state_id=candidate.state_id,
                availability_verified=True,
                cleared_prerequisite_ids=(
                    "HANDLE-FAM-SYNTHETIC-A-1",
                    "HANDLE-FAM-SYNTHETIC-A-2",
                    "HANDLE-STATE-A",
                ),
                inventory_artifact_digest="f" * 64,
                handling_artifact_digest="d" * 64,
            ),
            inventory,
        )


def test_readiness_record_cannot_be_directly_constructed():
    with pytest.raises(DiagnosticDesignError, match="readiness.*attestation"):
        RepresentativeReadinessRecord(
            record_id="READINESS-FORGED",
            family_id="FAM-SYNTHETIC-A",
            state_id="STATE-A",
            candidate_identity_digest="a" * 64,
            inventory_artifact_digest="b" * 64,
            handling_artifact_digest="c" * 64,
            cleared_prerequisite_ids=("HANDLE-STATE-A",),
            content_digest="d" * 64,
        )


def test_copied_or_candidate_mismatched_readiness_record_is_rejected():
    candidate_a = _candidate("STATE-A", "synthetic state alpha")
    candidate_b = _candidate("STATE-B", "synthetic state beta")
    readiness = _readiness(candidate_a)
    copied = readiness.model_copy(update={"inventory_artifact_digest": "f" * 64})

    with pytest.raises(DiagnosticDesignError, match="readiness.*attestation"):
        _plan(proposal=_proposal(candidate_a), readiness=(copied,))
    with pytest.raises(DiagnosticDesignError, match="unknown proposed state"):
        _plan(proposal=_proposal(candidate_b), readiness=(readiness,))


def test_readiness_content_identity_changes_plan_core_and_blocks_cross_success():
    candidate = _candidate("STATE-A", "synthetic state alpha")
    inventory = _inventory(candidate)
    readiness_a = _readiness(
        candidate,
        inventory=inventory,
        verification_id="VERIFY-SHARED",
        handling_artifact_digest="d" * 64,
    )
    readiness_b = _readiness(
        candidate,
        inventory=inventory,
        verification_id="VERIFY-SHARED",
        handling_artifact_digest="e" * 64,
    )

    assert readiness_a.record_id != readiness_b.record_id
    assert readiness_a.verification_id == readiness_b.verification_id
    assert readiness_a.record_id == f"READINESS-{readiness_a.content_digest}"
    assert readiness_b.record_id == f"READINESS-{readiness_b.content_digest}"

    plan_a = _plan(
        proposal=_proposal(candidate),
        inventory=(inventory,),
        readiness=(readiness_a,),
    )
    plan_b = _plan(
        proposal=_proposal(candidate),
        inventory=(inventory,),
        readiness=(readiness_b,),
    )

    assert plan_a.plan_digest != plan_b.plan_digest
    representative_a = plan_a.representatives[0]
    assert representative_a.readiness_record_id == readiness_a.record_id
    assert representative_a.readiness_content_digest == readiness_a.content_digest
    assert (
        representative_a.readiness_inventory_artifact_digest
        == readiness_a.inventory_artifact_digest
    )
    assert (
        representative_a.readiness_handling_artifact_digest
        == readiness_a.handling_artifact_digest
    )

    success = record_diagnostic_result(plan_a, _result(plan_a))
    with pytest.raises(DiagnosticDesignError, match="success.*plan link"):
        _plan(
            proposal=_proposal(candidate),
            inventory=(inventory,),
            readiness=(readiness_b,),
            records=(success,),
        )


def test_verification_id_is_provenance_not_readiness_identity():
    candidate = _candidate("STATE-A", "synthetic state alpha")
    inventory = _inventory(candidate)
    readiness_a = _readiness(
        candidate,
        inventory=inventory,
        verification_id="VERIFY-PROVENANCE-A",
    )
    readiness_b = _readiness(
        candidate,
        inventory=inventory,
        verification_id="VERIFY-PROVENANCE-B",
    )

    assert readiness_a.verification_id != readiness_b.verification_id
    assert readiness_a.content_digest == readiness_b.content_digest
    assert readiness_a.record_id == readiness_b.record_id


def test_differing_readiness_records_cannot_share_indexed_verification_id():
    candidate_a = _candidate("STATE-A", "synthetic state alpha")
    candidate_b = _candidate("STATE-B", "synthetic state beta")
    inventory_a = _inventory(candidate_a)
    inventory_b = _inventory(candidate_b)
    readiness_a = _readiness(
        candidate_a,
        inventory=inventory_a,
        verification_id="VERIFY-COLLISION",
        handling_artifact_digest="d" * 64,
    )
    readiness_b = _readiness(
        candidate_b,
        inventory=inventory_b,
        verification_id="VERIFY-COLLISION",
        handling_artifact_digest="e" * 64,
    )

    with pytest.raises(DiagnosticDesignError, match="verification ID collision"):
        _plan(
            proposal=_proposal(candidate_a, candidate_b),
            inventory=(inventory_a, inventory_b),
            readiness=(readiness_a, readiness_b),
        )


def test_readiness_verification_id_collision_is_global_across_families():
    family_a = _family("FAM-A", family_evidence_ids=("EV-FAMILY-A",))
    family_b = _family("FAM-B", family_evidence_ids=("EV-FAMILY-B",))
    candidate_a = _candidate("STATE-A", "synthetic state alpha")
    candidate_b = _candidate("STATE-B", "synthetic state beta")
    inventory_a = _inventory(candidate_a, family=family_a)
    inventory_b = _inventory(candidate_b, family=family_b)
    readiness_a = _readiness(
        candidate_a,
        family=family_a,
        inventory=inventory_a,
        verification_id="VERIFY-GLOBAL-COLLISION",
        handling_artifact_digest="d" * 64,
    )
    readiness_b = _readiness(
        candidate_b,
        family=family_b,
        inventory=inventory_b,
        verification_id="VERIFY-GLOBAL-COLLISION",
        handling_artifact_digest="e" * 64,
    )
    evaluation_a = _scored_evaluation(
        "FAM-A",
        judgment_evidence_id="EV-J-A",
        family_evidence_id="EV-FAMILY-A",
    )
    evaluation_b = _scored_evaluation(
        "FAM-B",
        region="priority_b",
        judgment_evidence_id="EV-J-B",
        family_evidence_id="EV-FAMILY-B",
    )

    with pytest.raises(DiagnosticDesignError, match="verification ID collision"):
        design_family_diagnostics(
            (family_a, family_b),
            (evaluation_a, evaluation_b),
            (_principle(),),
            _evidence("EV-FAMILY-A", "EV-FAMILY-B", "EV-J-A", "EV-J-B"),
            _ranking(evaluation_a, evaluation_b),
            proposals=(
                _proposal(candidate_a, family_id=family_a.family_id),
                _proposal(candidate_b, family_id=family_b.family_id),
            ),
            inventory_records=(inventory_a, inventory_b),
            readiness_records=(readiness_a, readiness_b),
        )


def test_tampered_excluded_readiness_is_verified_before_global_collision_index():
    priority_family = _family(
        "FAM-PRIORITY", family_evidence_ids=("EV-FAMILY-PRIORITY",)
    )
    excluded_family = _family(
        "FAM-EXCLUDED", family_evidence_ids=("EV-FAMILY-EXCLUDED",)
    )
    priority_candidate = _candidate("STATE-PRIORITY", "synthetic state alpha")
    excluded_candidate = _candidate("STATE-EXCLUDED", "synthetic state beta")
    priority_inventory = _inventory(priority_candidate, family=priority_family)
    excluded_inventory = _inventory(excluded_candidate, family=excluded_family)
    priority_readiness = _readiness(
        priority_candidate,
        family=priority_family,
        inventory=priority_inventory,
        verification_id="VERIFY-MIXED-COLLISION",
    )
    excluded_readiness = _readiness(
        excluded_candidate,
        family=excluded_family,
        inventory=excluded_inventory,
        verification_id="VERIFY-MIXED-COLLISION",
        handling_artifact_digest="e" * 64,
    )
    forged_excluded_readiness = excluded_readiness.model_copy(
        update={"content_digest": priority_readiness.content_digest}
    )
    priority_evaluation = _scored_evaluation(
        "FAM-PRIORITY",
        judgment_evidence_id="EV-J-PRIORITY",
        family_evidence_id="EV-FAMILY-PRIORITY",
    )
    excluded_evaluation = _scored_evaluation(
        "FAM-EXCLUDED",
        region="excluded",
        judgment_evidence_id="EV-J-EXCLUDED",
        family_evidence_id="EV-FAMILY-EXCLUDED",
    )

    with pytest.raises(DiagnosticDesignError, match="readiness.*attestation"):
        design_family_diagnostics(
            (priority_family, excluded_family),
            (priority_evaluation, excluded_evaluation),
            (_principle(),),
            _evidence(
                "EV-FAMILY-PRIORITY",
                "EV-FAMILY-EXCLUDED",
                "EV-J-PRIORITY",
                "EV-J-EXCLUDED",
                "EV-BLOCKER",
            ),
            _ranking(priority_evaluation, excluded_evaluation),
            proposals=(
                _proposal(
                    priority_candidate,
                    family_id=priority_family.family_id,
                ),
            ),
            inventory_records=(priority_inventory,),
            readiness_records=(priority_readiness, forged_excluded_readiness),
        )


def test_unavailable_candidate_is_not_selected_when_verified_option_covers_scope():
    unavailable = _candidate(
        "STATE-A", "synthetic state alpha", availability="unavailable"
    )
    available = _candidate("STATE-B", "synthetic state beta")
    plan = _plan(
        proposal=_proposal(unavailable, available),
        readiness=(_readiness(available),),
    )

    assert tuple(item.state_id for item in plan.representatives) == ("STATE-B",)
    assert plan.executable is True
    assert plan.representatives[0].readiness_record_id


def test_uncleared_handling_prerequisite_blocks_execution():
    plan = _plan(
        proposal=_proposal(
            _candidate(
                "STATE-A",
                "synthetic state alpha",
                handling_status="uncleared",
            )
        )
    )

    assert plan.executable is False
    assert {action.action_type for action in plan.operational_actions} == {
        "verify_availability",
        "clear_handling_prerequisite",
    }


def test_default_candidates_require_operational_availability_verification():
    plan = _plan()

    assert plan.chemistry_planned is True
    assert plan.executable is False
    assert all(
        item.availability_state == "needs_verification"
        for item in plan.representatives
    )


def test_arbitrary_principle_content_cannot_drive_conditions():
    evaluation = _scored_evaluation()
    altered = _principle(catalyst_requirements=["arbitrary catalyst state"])

    with pytest.raises(DiagnosticDesignError, match="Principle content digest"):
        design_family_diagnostics(
            (_family(),),
            (evaluation,),
            (altered,),
            _evidence(),
            _ranking(evaluation),
        )


@pytest.mark.parametrize(
    "tamper", ("source", "links", "dimensions", "class", "locator", "provenance")
)
def test_supplied_evidence_must_match_attested_evaluation_provenance(tamper: str):
    evaluation = _scored_evaluation()
    judgment = _evidence_record("EV-JUDGMENT")
    if tamper == "source":
        judgment = judgment.model_copy(update={"source_path": "papers/other.pdf"})
    elif tamper == "links":
        judgment = judgment.model_copy(update={"reviewed_principle_links": ()})
    elif tamper == "dimensions":
        judgment = judgment.model_copy(
            update={"admissible_dimensions": ("elementary_step_match",)}
        )
    elif tamper == "class":
        judgment = judgment.model_copy(update={"evidence_class": "seed"})
    elif tamper == "locator":
        judgment = judgment.model_copy(update={"locator": "page 99, replaced"})
    else:
        judgment = judgment.model_copy(
            update={"provenance_path": "derived/replaced.json"}
        )

    with pytest.raises(DiagnosticDesignError, match="evidence.*attested"):
        design_family_diagnostics(
            (_family(),),
            (evaluation,),
            (_principle(),),
            (_evidence_record("EV-FAMILY"), judgment),
            _ranking(evaluation),
        )


def test_family_evidence_must_have_exact_scored_content_attestation():
    evaluation = _scored_evaluation()
    replaced = _evidence_record("EV-FAMILY").model_copy(
        update={"locator": "page 77, replaced family evidence"}
    )
    with pytest.raises(DiagnosticDesignError, match="evidence.*attested"):
        design_family_diagnostics(
            (_family(),),
            (evaluation,),
            (_principle(),),
            (replaced, _evidence_record("EV-JUDGMENT")),
            _ranking(evaluation),
        )


def test_unbound_family_evidence_cannot_enter_diagnostic_plan():
    evaluation = _scored_evaluation()
    family = _family(family_evidence_ids=("EV-UNBOUND",))
    with pytest.raises(DiagnosticDesignError, match="lacks scored content attestation"):
        design_family_diagnostics(
            (family,),
            (evaluation,),
            (_principle(),),
            _evidence("EV-UNBOUND", "EV-FAMILY", "EV-JUDGMENT"),
            _ranking(evaluation),
        )


def test_plan_evidence_is_exact_union_with_per_principle_links():
    evaluation = _scored_evaluation(counterevidence_id="EV-COUNTER")
    family = _family()
    plan = design_family_diagnostics(
        (family,),
        (evaluation,),
        (_principle(),),
        _evidence("EV-FAMILY", "EV-JUDGMENT", "EV-COUNTER"),
        _ranking(evaluation),
        inventory_records=_inventories_for_family(family),
    )[0]

    assert plan.evidence_ids == ("EV-COUNTER", "EV-FAMILY", "EV-JUDGMENT")
    assert plan.principle_evidence_links == {
        _PRINCIPLE_ID: ("EV-COUNTER", "EV-FAMILY", "EV-JUDGMENT")
    }


def test_fluoride_release_alone_cannot_define_plan_success():
    analytics = _plan().analytics
    assert analytics is not None
    payload = analytics.model_dump(mode="python")
    payload["required_target_analyte"] = ""
    payload["target_product_methods"] = ()
    payload["fluoride_release_analytics"] = (
        "Synthetic fluoride-release signal.",
    )

    with pytest.raises((DiagnosticDesignError, ValidationError), match="target product"):
        DiagnosticAnalytics.model_validate(payload)


def test_family_plan_requires_factory_attestation_and_full_content_verification():
    plan = _plan()
    payload = plan.model_dump(mode="python")

    with pytest.raises(DiagnosticDesignError, match="plan.*attestation"):
        FamilyDiagnosticPlan.model_validate(payload)
    forged = FamilyDiagnosticPlan.model_construct(**payload)
    with pytest.raises(DiagnosticDesignError, match="plan.*attestation"):
        verify_family_diagnostic_plan(forged)
    copied = plan.model_copy()
    with pytest.raises(DiagnosticDesignError, match="plan.*attestation"):
        verify_family_diagnostic_plan(copied)

    assert plan.analytics is not None
    object.__setattr__(
        plan.analytics,
        "required_target_analyte",
        "tampered target product",
    )
    with pytest.raises(DiagnosticDesignError, match="plan.*attestation|content"):
        verify_family_diagnostic_plan(plan)


def test_zero_digest_and_executable_flipped_plan_cannot_record_result():
    plan = _plan()
    forged = plan.model_copy(update={"plan_digest": "0" * 64, "executable": True})
    result = _result(forged)

    with pytest.raises(DiagnosticDesignError, match="plan.*attestation"):
        record_diagnostic_result(forged, result)


def _executable_plan(region: str = "priority_a") -> FamilyDiagnosticPlan:
    candidate = _candidate("STATE-A", "synthetic state alpha")
    return _plan(
        region=region,
        proposal=_proposal(candidate),
        readiness=(_readiness(candidate),),
    )


def _result(
    plan: FamilyDiagnosticPlan,
    *,
    target_confirmed: bool = True,
    target_analyte: str | None = None,
    plan_digest: str | None = None,
) -> ExecutionResultInput:
    assert plan.analytics is not None
    return ExecutionResultInput(
        result_id="RESULT-SYNTHETIC",
        family_id=plan.family_id,
        plan_digest=plan_digest or plan.plan_digest,
        representative_id=plan.representatives[0].representative_id,
        condition_id=plan.conditions[0].state_id,
        target_product_confirmed=target_confirmed,
        target_analyte=target_analyte or plan.analytics.required_target_analyte,
        target_product_method=plan.analytics.target_product_methods[0],
        target_product_readout="Synthetic calibrated target-product readout.",
        fluoride_release_readout="Synthetic supporting fluoride readout.",
        mass_balance_readout="Synthetic mass balance closed.",
        competing_product_readouts={
            measurement.measurement_id: "Synthetic competing product quantified."
            for measurement in plan.analytics.competing_product_measurements
        },
        falsification_observations_checked=plan.analytics.falsifying_observations,
        run_artifact_digest="a" * 64,
        result_artifact_digest="b" * 64,
    )


def test_direct_success_construction_cannot_authorize_optimization():
    with pytest.raises(DiagnosticDesignError, match="attestation"):
        DiagnosticSuccessRecord(
            record_id="SUCCESS-FORGED",
            family_id="FAM-SYNTHETIC-A",
            plan_digest="a" * 64,
            representative_id="STATE-A",
            condition_id="COND-SYNTHETIC-BASE",
            target_analyte="synthetic target product",
            target_product_method="synthetic calibrated assay",
            target_product_readout="forged readout",
            mass_balance_readout="forged mass balance",
            competing_product_readouts={"COMPETING-1": "forged competitor"},
            falsification_observations_checked=("forged observation",),
            run_artifact_digest="b" * 64,
            result_artifact_digest="c" * 64,
            content_digest="d" * 64,
        )


def test_factory_attested_success_enables_optimization_only_for_exact_plan():
    candidate = _candidate("STATE-A", "synthetic state alpha")
    readiness = _readiness(candidate)
    plan = _plan(proposal=_proposal(candidate), readiness=(readiness,))
    success = record_diagnostic_result(plan, _result(plan))
    assert isinstance(success, DiagnosticSuccessRecord)

    optimized = _plan(
        proposal=_proposal(candidate),
        records=(success,),
        readiness=(readiness,),
    )

    assert optimized.optimization_plans[0].diagnostic_success_record_id == (
        success.record_id
    )


def test_success_cannot_be_consumed_by_a_different_executable_core_plan():
    candidate_a = _candidate("STATE-A", "synthetic state alpha")
    plan_a = _plan(
        proposal=_proposal(candidate_a),
        readiness=(_readiness(candidate_a),),
    )
    success = record_diagnostic_result(plan_a, _result(plan_a))
    assert isinstance(success, DiagnosticSuccessRecord)

    candidate_b = _candidate("STATE-B", "synthetic state beta")
    with pytest.raises(DiagnosticDesignError, match="success.*plan link"):
        _plan(
            proposal=_proposal(candidate_b),
            records=(success,),
            readiness=(_readiness(candidate_b),),
        )


@pytest.mark.parametrize("mismatch", ("plan", "representative", "condition"))
def test_execution_result_must_match_exact_plan(mismatch: str):
    plan = _executable_plan()
    payload = _result(plan).model_dump(mode="python")
    if mismatch == "plan":
        payload["plan_digest"] = "f" * 64
    elif mismatch == "representative":
        payload["representative_id"] = "REP-OTHER"
    else:
        payload["condition_id"] = "COND-OTHER"

    with pytest.raises(DiagnosticDesignError, match="plan|representative|condition"):
        record_diagnostic_result(plan, ExecutionResultInput.model_validate(payload))


@pytest.mark.parametrize("target_analyte", ("", "synthetic fluoride signal"))
def test_blank_or_fluoride_only_result_cannot_create_success(target_analyte: str):
    plan = _executable_plan()
    payload = _result(plan).model_dump(mode="python")
    payload["target_analyte"] = target_analyte

    with pytest.raises((DiagnosticDesignError, ValidationError), match="target product"):
        result = ExecutionResultInput.model_validate(payload)
        record_diagnostic_result(plan, result)


@pytest.mark.parametrize("tamper", ("missing", "extra", "blank"))
def test_competing_product_results_must_exactly_match_planned_measurement_ids(
    tamper: str,
):
    plan = _executable_plan()
    assert plan.analytics is not None
    measurement_ids = tuple(
        measurement.measurement_id
        for measurement in plan.analytics.competing_product_measurements
    )
    readouts = {
        measurement_id: f"Synthetic result for {measurement_id}."
        for measurement_id in measurement_ids
    }
    if tamper == "missing":
        readouts.pop(measurement_ids[0])
    elif tamper == "extra":
        readouts["COMPETING-EXTRA"] = "Synthetic extra result."
    else:
        readouts[measurement_ids[0]] = "  "
    payload = _result(plan).model_dump(mode="python")
    payload["competing_product_readouts"] = readouts

    with pytest.raises(DiagnosticDesignError, match="competing-product"):
        result = ExecutionResultInput.model_validate(payload)
        record_diagnostic_result(plan, result)


def test_tampered_success_record_cannot_enable_optimization():
    plan = _executable_plan()
    success = record_diagnostic_result(plan, _result(plan))
    assert isinstance(success, DiagnosticSuccessRecord)
    forged = success.model_copy(update={"result_artifact_digest": "f" * 64})

    with pytest.raises(DiagnosticDesignError, match="success.*attestation"):
        _plan(
            proposal=_proposal(_candidate("STATE-A", "synthetic state alpha")),
            records=(forged,),
        )


def test_boundary_target_positive_is_falsification_and_never_optimization():
    candidate = _candidate("STATE-A", "synthetic state alpha")
    readiness = _readiness(candidate)
    plan = _plan(
        region="boundary", proposal=_proposal(candidate), readiness=(readiness,)
    )
    outcome = record_diagnostic_result(plan, _result(plan))

    assert isinstance(outcome, BoundaryFalsificationRecord)
    assert outcome.disposition == "boundary_falsified"
    followup = _plan(
        region="boundary",
        proposal=_proposal(candidate),
        records=(outcome,),
        readiness=(readiness,),
    )
    assert followup.optimization_plans == ()
    assert any(
        action.action_type == "reclassify_boundary"
        for action in followup.operational_actions
    )

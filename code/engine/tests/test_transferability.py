from pipeline.principle_models import BoundaryConstraint, MechanismEvidence, SeedMechanism
from pipeline.semantic_transfer import MechanismTransferProposal, TRANSFER_DIMENSIONS
from pipeline.transferability import adjudicate_transfer_proposal, assess_transferability
from pipeline.paper_mechanism_bundles import load_paper_mechanism_bundles
from tests.test_paper_mechanism_bundles import _write_fixture


def _seed(**updates) -> SeedMechanism:
    values = {
        "seed_reaction_id": "SRC-001",
        "reaction_center": ["trifluoroethyl carbonyl"],
        "electrophile_state": ["fluorinated alkene-like intermediate"],
        "nucleophile_state": ["activated nucleophile"],
        "bond_changes": ["form C-Nu", "break C-F"],
        "reactive_intermediates": ["fluorinated alkene-like intermediate"],
        "elementary_steps": ["nucleophilic trapping", "beta-fluoride elimination"],
        "electronic_requirements": ["soft electrophilic carbon"],
        "steric_requirements": ["accessible beta carbon"],
        "catalyst_roles": ["palladium-compatible activation"],
        "condition_window": ["moderate base", "non-oxidizing"],
        "successful_scope": ["organoboron"],
        "failed_scope": [],
        "competing_pathways": ["over-defluorination"],
        "evidence_ids": ["SEED-E001"],
        "confidence": "medium",
    }
    values.update(updates)
    return SeedMechanism(**values)


def _evidence(**updates) -> MechanismEvidence:
    values = {
        "mechanism_evidence_id": "ME-001",
        "source_paper_id": "paper-1",
        "source_evidence_ids": ("E001",),
        "evidence_type": "elementary_step",
        "elementary_step": "nucleophilic trapping",
        "starting_state": "fluorinated alkene plus nucleophile",
        "ending_state": "C-Nu bonded intermediate",
        "bond_changes": ("form C-Nu",),
        "catalyst_role": "palladium-compatible activation",
        "nucleophile_requirements": ("activated nucleophile",),
        "electrophile_requirements": ("soft electrophilic carbon",),
        "condition_requirements": ("moderate base",),
        "observed_outcome": "monofluoroalkene",
        "failure_mode": None,
        "evidence_label": "LITERATURE FACT",
        "evidence_strength": "direct",
        "quotation": "The nucleophile afforded the monofluoroalkene.",
        "pdf_page": 3,
        "confidence": "high",
    }
    values.update(updates)
    return MechanismEvidence(**values)


def _rubric() -> dict:
    return {
        "weights": {
            "shared_elementary_step": 4,
            "electrophile_match": 3,
            "nucleophile_match": 3,
            "catalyst_match": 2,
            "condition_match": 2,
        }
    }


def test_matching_shared_step_is_transferable():
    result = assess_transferability(_seed(), _evidence(), [], _rubric())

    assert result.transfer_status == "transferable"
    assert result.blocking_constraints == ()
    assert result.score_components["total"] == 14


def test_condition_window_mismatch_is_conditional():
    result = assess_transferability(
        _seed(),
        _evidence(condition_requirements=("strong oxidizing base",)),
        [],
        _rubric(),
    )

    assert result.transfer_status == "conditional"
    assert "condition window mismatch" in result.mismatched_requirements


def test_incompatible_constraint_is_a_non_transferable_hard_blocker():
    constraint = BoundaryConstraint(
        constraint_id="BC-001",
        dimension="catalyst",
        applies_to=("palladium-compatible activation",),
        direction="incompatible",
        statement="This nucleophile irreversibly poisons the palladium state.",
        quantitative_range=None,
        supporting_evidence_ids=("E002",),
        contradictory_evidence_ids=(),
        confidence="high",
    )

    result = assess_transferability(_seed(), _evidence(), [constraint], _rubric())

    assert result.transfer_status == "non_transferable"
    assert result.blocking_constraints == ("BC-001",)
    assert result.score_components["total"] > 0


def test_unknown_reactive_form_produces_unknown_assessment():
    result = assess_transferability(
        _seed(),
        _evidence(nucleophile_requirements=("UNKNOWN",)),
        [],
        _rubric(),
    )

    assert result.transfer_status == "unknown"
    assert "nucleophile reactive form is unknown" in result.uncertainty


def _semantic_rubric() -> dict:
    return {
        "weights": {dimension: index + 1 for index, dimension in enumerate(TRANSFER_DIMENSIONS)},
        "critical_unknown_dimensions": [
            "shared_elementary_step",
            "electrophile_electronic_compatibility",
            "nucleophile_reactive_form",
        ],
    }


def _semantic_proposal(bundle, judgments: dict[str, str], blockers=()):
    return MechanismTransferProposal.model_validate(
        {
            "mechanism_id": bundle.mechanisms[0].mechanism_evidence_id,
            "components": [
                {
                    "dimension": dimension,
                    "judgment": judgments.get(dimension, "match"),
                    "rationale": f"Comparison for {dimension}.",
                    "seed_evidence_ids": ["SEED-E001"],
                    "literature_evidence_ids": [bundle.mechanisms[0].source_evidence_ids[0]],
                }
                for dimension in TRANSFER_DIMENSIONS
            ],
            "hard_blocker_constraint_ids": list(blockers),
            "conditions": ["moderate base"],
            "uncertainty": [],
            "transferable_claim": "The step has bounded transfer relevance.",
            "falsifying_test": "Test the step under the Seed condition window.",
        }
    )


def test_semantic_adjudication_preserves_unknown_outside_numeric_denominator(tmp_path):
    _write_fixture(tmp_path)
    bundle = load_paper_mechanism_bundles(tmp_path)[0]
    proposal = _semantic_proposal(
        bundle, {"nucleophile_reactive_form": "unknown"}
    )

    result = adjudicate_transfer_proposal(_seed(), bundle, proposal, _semantic_rubric())

    assert result.transfer_status == "unknown"
    assert result.source_paper_id == bundle.source_path
    assert result.source_mechanism_id == bundle.mechanisms[0].mechanism_evidence_id
    assert result.score_components["nucleophile_reactive_form"] == "unknown"
    assert result.score_components["denominator"] == sum(range(1, 9)) - 3


def test_semantic_adjudication_orders_blocker_mismatch_conditional_and_match(tmp_path):
    _write_fixture(tmp_path)
    bundle = load_paper_mechanism_bundles(tmp_path)[0]
    blocker = bundle.constraints[0].constraint_id

    blocked = adjudicate_transfer_proposal(
        _seed(), bundle, _semantic_proposal(bundle, {}, blockers=[blocker]), _semantic_rubric()
    )
    mismatched = adjudicate_transfer_proposal(
        _seed(),
        bundle,
        _semantic_proposal(bundle, {"shared_elementary_step": "mismatch"}),
        _semantic_rubric(),
    )
    conditional = adjudicate_transfer_proposal(
        _seed(),
        bundle,
        _semantic_proposal(bundle, {"condition_overlap": "conditional"}),
        _semantic_rubric(),
    )
    matched = adjudicate_transfer_proposal(
        _seed(), bundle, _semantic_proposal(bundle, {}), _semantic_rubric()
    )

    assert blocked.transfer_status == "non_transferable"
    assert mismatched.transfer_status == "non_transferable"
    assert conditional.transfer_status == "conditional"
    assert matched.transfer_status == "transferable"
    assert len({blocked.assessment_id, mismatched.assessment_id, conditional.assessment_id, matched.assessment_id}) == 4

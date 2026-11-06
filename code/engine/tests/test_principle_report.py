import json

from pipeline.principle_report import build_v3_report, write_principle_report
from pipeline.principle_models import SeedPrinciple
from pipeline.candidate_ranking import rank_experiment_candidates
from tests.test_candidate_ranking import RUBRIC, _family
from tests.test_model_proposals import _seed
from tests.test_principle_induction import _principle, _transfer


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_v3_report_exposes_gate_blockers_without_family_ontology(tmp_path):
    namespace = tmp_path / "derived" / "principles_v3"
    namespace.mkdir(parents=True)
    saturate = namespace / "saturate.json"
    _write_json(saturate, {"saturation": {
        "completed_rounds": 3, "new_family_rate": 1.0,
        "material_taxonomy_change_rate": 1.0,
        "consecutive_low_new_family_rounds": 0, "lane_converged": False,
        "coordinate_combinations_stable": False, "coverage_dispositioned": False,
        "additional_evidence_batch_no_material_change": False, "saturated": False,
        "uncovered_coordinate_dispositions": {"coordinate_alpha": "unknown"},
    }})
    _write_json(namespace / "manifest.json", {"phases": {
        "saturate": {"status": "complete", "artifact": str(saturate)},
        "discover": {"status": "complete"},
    }})
    report = build_v3_report(tmp_path)
    assert report["workflow_state"]["freeze_2_allowed"] is False
    assert "独立 discovery lane 尚未收敛" in report["workflow_state"]["blockers"]
    assert "至少一个机制坐标仍为 unknown" in report["markdown"]
    assert all(term not in json.dumps(report).casefold() for term in ("indole", "naphthol", "disulfide", "thiol"))


def test_principle_report_is_provisional_complete_and_hidden_safe(tmp_path):
    root = tmp_path / "derived/principles"
    seed_principle = SeedPrinciple(
        seed_principle_id="SP-001",
        title="Matched activation and trapping",
        claim="A matched electrophile/nucleophile pair is required.",
        reaction_center=("C-F-bearing carbon",),
        reactive_intermediates=("gem-difluoroalkene",),
        electronic_requirements=("polarized electrophile",),
        nucleophile_requirements=("accessible reactive form",),
        catalyst_roles=("palladium activation",),
        condition_window=("moderate base",),
        failure_boundaries=("strong coordination can inhibit turnover",),
        supporting_seed_evidence=("SEED-E001",),
        confidence="medium",
        uncertainty=("intermediate lifetime is unknown",),
    )
    assessment = _transfer().model_copy(
        update={
            "source_paper_id": "papers/one.pdf",
            "source_mechanism_id": "abc123::ME001",
            "score_components": {
                "shared_elementary_step": 3,
                "product_stability": "unknown",
                "denominator": 3,
                "total": 3,
            },
            "uncertainty": ("product stability is unknown",),
        }
    )
    principle = _principle().model_copy(
        update={
            "applicable_electrophile_families": ["trifluoroethyl ketones"],
            "applicable_nucleophile_families": ["aryl organoboron"],
            "catalyst_requirements": ["palladium-compatible ligand environment"],
            "condition_window": ["moderate bicarbonate base"],
            "structural_inhibitors": ["strongly coordinating nucleophiles"],
        }
    )
    _write_json(root / "seed_mechanism.json", _seed().model_dump(mode="json"))
    _write_json(root / "seed_principle.json", seed_principle.model_dump(mode="json"))
    _write_json(
        root / "transfer_assessments.json",
        {
            "semantic_transfer_version": "2.0",
            "assessments": [assessment.model_dump(mode="json")],
        },
    )
    _write_json(
        root / "principle_review.json",
        {"principles": [principle.model_dump(mode="json")], "failures": {}},
    )
    _write_json(
        root / "source_revisit_registry.json",
        {
            "revisit_count": 1,
            "revisits": [
                {
                    "request_id": "abc123::SR001",
                    "source_paper_id": "papers/one.pdf",
                    "question": "Confirm the intermediate drawing.",
                    "status": "pending",
                }
            ],
        },
    )
    _write_json(
        root / "technical_exclusions.json",
        {
            "excluded_count": 1,
            "scientific_interpretation": "technical exclusion only; not negative chemical evidence",
            "excluded_queue_items": [{"source_path": "papers/excluded.pdf"}],
        },
    )
    _write_json(
        tmp_path / "reports/knowledge_transfer_audit.json",
        {
            "paper_count": 1,
            "mechanism_count": 1,
            "assessment_count": 1,
            "unique_assessment_count": 1,
            "revisit_count": 1,
            "missing_paper_count": 0,
            "missing_mechanism_count": 0,
            "provenance_violation_count": 0,
            "status_counts": {"transferable": 1},
            "component_judgment_counts": {"product_stability:unknown": 1},
        },
    )

    markdown_path, json_path = write_principle_report(
        tmp_path, max_assessments=10, max_per_paper=2
    )

    report = json.loads(json_path.read_text(encoding="utf-8"))
    markdown = markdown_path.read_text(encoding="utf-8")
    assert report["report_status"] == "provisional_unreviewed"
    assert report["review_and_freeze_state"]["hidden_outcomes_revealed"] is False
    assert report["transferred_mechanisms"][0]["score_components"]["product_stability"] == "unknown"
    assert set(report["family_boundaries"]) == {
        "nucleophile",
        "electrophile",
        "catalyst",
        "condition",
    }
    assert report["technical_exclusions"]["scientific_interpretation"].startswith(
        "technical exclusion only"
    )
    assert "papers/excluded.pdf" not in json.dumps(report["negative_boundaries"])
    for heading in (
        "Seed Principle",
        "Transferred Mechanisms",
        "Physical-Organic Rules",
        "Negative Boundaries",
        "Reaction Principle Candidates",
        "Family Boundaries",
        "Worthwhile Chemical Space",
        "Low-Value Chemical Space",
        "Diagnostic Experiments",
        "Uncertainties",
        "Source Revisits",
        "Technical Exclusions",
        "Provenance",
        "Human Review and Freeze State",
    ):
        assert f"## {heading}" in markdown
    assert "PL30.xlsx" not in markdown
    assert "新反应发现.pptx" not in markdown

    reviewed = principle.model_copy(
        update={"status": "accepted", "review_status": "accepted"}
    )
    transferable = reviewed.model_copy(
        update={
            "principle_id": "RP-SUPER-001",
            "principle_layer": "transferable_super",
            "title": "Transferable local trapping",
        }
    )
    family = _family(family_id="NU-ARYLBORON", uncertainty=("threshold unknown",))
    candidate = rank_experiment_candidates(
        [
            {
                "experiment_id": "EXP-ARYLBORON",
                "family_id": family.family_id,
                "electrophile": "trifluoroethyl ketone",
                "nucleophile": "phenylboronic acid",
                "catalyst": "Pd",
                "ligand": "unknown",
                "base": "KHCO3",
                "solvent": "DCE",
                "temperature": "80 C",
                "time": "12 h",
                "atmosphere": "sealed",
                "bonus_components": {},
                "risk_components": {},
                "predicted_failure_modes": ["over-defluorination"],
                "supporting_principle_ids": [reviewed.principle_id],
                "evidence_ids": [assessment.assessment_id],
                "minimal_diagnostic_plan": ["19F NMR time course"],
                "uncertainty": [],
            }
        ],
        {family.family_id: family},
        RUBRIC,
    )[0]
    _write_json(
        root / "principle_review.json",
        {
            "principles": [
                reviewed.model_dump(mode="json"),
                transferable.model_dump(mode="json"),
            ],
            "failures": {},
        },
    )
    _write_json(
        root / "exploration_brief.json",
        {
            "version": "2.0",
            "stage": "fixed_electrophile_nucleophile_condition",
            "fixed_role": {"role": "electrophile", "label": "Seed A"},
            "variable_role": {"role": "nucleophile", "label": "substrate B"},
            "digest": "a" * 64,
        },
    )
    _write_json(
        root / "coverage_audit.json",
        {
            "required_superclass_ids": [f"NUC-{index}" for index in range(8)],
            "covered_superclass_ids": [f"NUC-{index}" for index in range(8)],
            "missing_superclass_ids": [],
            "extra_superclass_ids": [],
            "complete": True,
        },
    )
    _write_json(
        root / "role_aware_evidence_index.json",
        {"mapped_count": 1, "unmapped_count": 0},
    )
    _write_json(
        root / "retrospective_development_registry.json",
        {
            "usage": "retrospective_development_only",
            "prospective_metric_eligible": False,
            "outcomes": [{"family": "SH/thiol"}],
        },
    )
    _write_json(
        root / "family_predictions.json",
        {"families": [family.model_dump(mode="json")]},
    )
    _write_json(
        root / "provisional_candidates.json",
        {"candidates": [candidate.model_dump(mode="json")]},
    )
    _write_json(
        tmp_path / "reports/chemistry_review.json",
        {"reviewer_type": "ai_proxy", "reviewer": "Codex", "decisions": []},
    )

    reviewed_markdown_path, reviewed_json_path = write_principle_report(tmp_path)
    reviewed_report = json.loads(reviewed_json_path.read_text(encoding="utf-8"))
    reviewed_markdown = reviewed_markdown_path.read_text(encoding="utf-8")

    assert reviewed_report["report_status"] == "provisional_ai_reviewed"
    assert reviewed_report["review_and_freeze_state"]["review_status"] == "ai_proxy_review_complete"
    assert reviewed_report["ranked_family_boundaries"][0]["family_id"] == "NU-ARYLBORON"
    assert reviewed_report["ranked_experiment_candidates"][0]["experiment_id"] == "EXP-ARYLBORON"
    assert reviewed_report["exploration"]["variable_role"]["role"] == "nucleophile"
    assert reviewed_report["principle_layers"]["transferable_super"][0]["principle_id"] == "RP-SUPER-001"
    assert reviewed_report["nucleophile_coverage"]["complete"] is True
    assert reviewed_report["retrospective_development"]["prospective_metric_eligible"] is False
    assert "cannot count as prospective prediction" in reviewed_report["validation_statement"]
    assert "## Ranked Family Boundaries" in reviewed_markdown
    assert "## User-Directed Exploration" in reviewed_markdown
    assert "cannot count as prospective prediction" in reviewed_markdown
    assert "EXP-ARYLBORON" in reviewed_markdown

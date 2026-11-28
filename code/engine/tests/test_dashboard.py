import json
from pathlib import Path

import pytest

from pipeline.dashboard import DASHBOARD_HTML, build_status


def test_dashboard_html_discloses_candidate_scope_review() -> None:
    html = DASHBOARD_HTML.read_text(encoding="utf-8")

    assert 'id="candidate-scope-review"' in html
    assert 'id="v3-saturation"' in html
    assert 'id="v3-freezes"' in html
    assert 'id="v34-families"' in html
    assert 'id="v34-novelty"' in html
    assert 'id="v34-unresolved"' in html
    assert 'id="v35-review"' in html
    assert 'id="v35-consensus"' in html
    assert 'id="v35-families"' in html
    assert 'id="v35-freeze"' in html
    assert 'id="candidate-section"' in html
    assert "candidateSection.hidden = v35.freeze_2_allowed !== true;" in html


def test_dashboard_reports_v3_4_without_overwriting_v3_3(tmp_path: Path) -> None:
    v33 = tmp_path / "runs/reaction_principle_v3_3/derived/principles_v3"
    (v33 / "rounds").mkdir(parents=True)
    (v33 / "preregistration.json").write_text(
        '{"version":"3.3"}', encoding="utf-8"
    )
    for round_id in range(1, 6):
        (v33 / f"rounds/round_{round_id}.json").write_text(
            json.dumps(
                {
                    "lane_results": [{"proposals": [{}]}],
                    "taxonomy": {"families": [{}]},
                    "platform_failures": [],
                }
            ),
            encoding="utf-8",
        )
    (v33 / "saturation.json").write_text(
        '{"saturation":{"saturated":false}}', encoding="utf-8"
    )
    v34 = tmp_path / "runs/reaction_principle_v3_4/derived/principles_v3"
    v34.mkdir(parents=True)
    (v34 / "status.json").write_text(
        json.dumps(
            {
                "version": "3.4",
                "source_version": "3.3",
                "state": "not_converged",
                "proposal_count": 213,
                "consolidated_family_count": 207,
                "unresolved_pair_count": 3084,
                "prefix_metrics": [
                    {"round_id": 5, "new_family_rate": 0.1884057971}
                ],
                "consolidation_converged": False,
                "freeze_2_allowed": False,
                "freeze_2_blockers": ["cross_round_consolidation_not_converged"],
            }
        ),
        encoding="utf-8",
    )

    status = build_status(tmp_path)

    assert status["v3_formal"]["version"] == "3.3"
    assert status["v3_4"]["source_version"] == "3.3"
    assert status["v3_4"]["proposal_count"] == 213
    assert status["v3_4"]["consolidated_family_count"] == 207


def test_dashboard_prefers_v3_4_1_over_invalidated_v3_4(tmp_path: Path) -> None:
    for version, family_count in (("3.4", 207), ("3.4.1", 205)):
        namespace = (
            tmp_path
            / f"runs/reaction_principle_v{version.replace('.', '_')}"
            / "derived/principles_v3"
        )
        namespace.mkdir(parents=True)
        (namespace / "status.json").write_text(
            json.dumps(
                {
                    "version": version,
                    "source_version": "3.3",
                    "state": "not_converged",
                    "proposal_count": 213,
                    "consolidated_family_count": family_count,
                    "unresolved_pair_count": 3082,
                    "prefix_metrics": [],
                    "consolidation_converged": False,
                    "freeze_2_allowed": False,
                    "freeze_2_blockers": ["cross_round_consolidation_not_converged"],
                }
            ),
            encoding="utf-8",
        )

    status = build_status(tmp_path)

    assert status["v3_4"]["version"] == "3.4.1"
    assert status["v3_4"]["consolidated_family_count"] == 205


def test_dashboard_reports_v3_5_without_overwriting_v3_4_1(tmp_path: Path) -> None:
    v341 = tmp_path / "runs/reaction_principle_v3_4_1/derived/principles_v3"
    v341.mkdir(parents=True)
    (v341 / "status.json").write_text(
        json.dumps(
            {
                "version": "3.4.1",
                "source_version": "3.3",
                "consolidated_family_count": 205,
            }
        ),
        encoding="utf-8",
    )
    v35 = tmp_path / "runs/reaction_principle_v3_5/derived/principles_v3"
    v35.mkdir(parents=True)
    (v35 / "status.json").write_text(
        json.dumps(
            {
                "version": "3.5",
                "source_version": "3.4.1",
                "state": "review_incomplete",
                "triage_counts": {
                    "shared_external_evidence": 252,
                    "text_compatible_evidence_gap": 16,
                    "insufficient_linkage": 2814,
                },
                "reviewed_in_both_lanes_count": 4,
                "consensus_counts": {"unresolved": 252},
                "candidate_family_count": 205,
                "remaining_unresolved_comparison_count": 3082,
                "freeze_2_allowed": False,
            }
        ),
        encoding="utf-8",
    )

    status = build_status(tmp_path)

    assert status["v3_4"]["version"] == "3.4.1"
    assert status["v3_5"]["source_version"] == "3.4.1"
    assert status["v3_5"]["triage_counts"]["shared_external_evidence"] == 252


def test_dashboard_status_reads_progress_without_calling_a_model(tmp_path: Path) -> None:
    corpus = tmp_path / "derived" / "full_corpus"
    corpus.mkdir(parents=True)
    queue = {
        "queue_digest": "q" * 64,
        "duplicate_exclusions": [{}, {}],
        "items": [
            {
                "source_path": f"Tier1/paper-{index}.pdf",
                "tier": "tier_1",
                "phase": "calibration" if index < 5 else "remaining",
            }
            for index in range(8)
        ],
    }
    (corpus / "queue.json").write_text(json.dumps(queue), encoding="utf-8")
    manifest = {
        "run_id": "run-1",
        "phase": "calibration",
        "updated_at": "2026-08-02T05:24:32+00:00",
        "paper_statuses": {
            "Tier1/paper-0.pdf": "validated",
            "Tier1/paper-1.pdf": "validation_failed",
        },
        "results": [
            {
                "source_path": "Tier1/paper-0.pdf",
                "status": "validated",
                "input_tokens": 100,
                "output_tokens": 20,
                "total_tokens": 120,
            },
            {
                "source_path": "Tier1/paper-1.pdf",
                "status": "validation_failed",
                "input_tokens": 80,
                "output_tokens": 10,
                "total_tokens": 90,
            },
        ],
    }
    (corpus / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    screening = tmp_path / "derived" / "screening"
    screening.mkdir(parents=True)
    (screening / "screening_summary.json").write_text(
        json.dumps(
            {
                "inventoried_pdf_count": 404,
                "unique_pdf_count": 397,
                "completed_count": 120,
                "included_count": 75,
                "excluded_count": 40,
                "uncertain_count": 5,
                "input_tokens": 5000,
                "output_tokens": 600,
                "total_tokens": 5600,
            }
        ),
        encoding="utf-8",
    )

    status = build_status(tmp_path)

    assert status["state"] == "running"
    assert status["calibration"] == {"completed": 2, "total": 5, "percent": 40.0}
    assert status["status_counts"] == {"validated": 1, "validation_failed": 1}
    assert status["tokens"] == {"input": 180, "output": 30, "total": 210}
    assert status["next_source"] == "Tier1/paper-2.pdf"
    assert status["corpus"] == {"inventoried": 404, "unique": 8, "remaining": 3}
    assert status["screening"] == {
        "inventoried": 404,
        "unique": 397,
        "completed": 120,
        "included": 75,
        "excluded": 40,
        "uncertain": 5,
        "tokens": 5600,
    }


def test_dashboard_reports_complete_when_summary_exists(tmp_path: Path) -> None:
    corpus = tmp_path / "derived" / "full_corpus"
    corpus.mkdir(parents=True)
    (corpus / "queue.json").write_text(
        json.dumps(
            {
                "queue_digest": "q" * 64,
                "duplicate_exclusions": [],
                "items": [
                    {
                        "source_path": "Tier1/a.pdf",
                        "tier": "tier_1",
                        "phase": "calibration",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (corpus / "manifest.json").write_text(
        json.dumps(
            {
                "phase": "calibration",
                "paper_statuses": {"Tier1/a.pdf": "validated"},
                "results": [],
            }
        ),
        encoding="utf-8",
    )
    (corpus / "calibration_summary.json").write_text("{}", encoding="utf-8")

    assert build_status(tmp_path)["state"] == "complete"


def test_dashboard_tracks_remaining_phase_after_calibration_summary(tmp_path: Path) -> None:
    corpus = tmp_path / "derived/full_corpus"
    corpus.mkdir(parents=True)
    (corpus / "queue.json").write_text(
        json.dumps(
            {
                "duplicate_exclusions": [],
                "items": [
                    {"source_path": "Tier1/cal.pdf", "tier": "tier_1", "phase": "calibration"},
                    {"source_path": "Tier1/a.pdf", "tier": "tier_1", "phase": "remaining"},
                    {"source_path": "Tier1/b.pdf", "tier": "tier_1", "phase": "remaining"},
                ],
            }
        ),
        encoding="utf-8",
    )
    (corpus / "manifest.json").write_text(
        json.dumps(
            {
                "phase": "remaining",
                "paper_statuses": {
                    "Tier1/cal.pdf": "reused",
                    "Tier1/a.pdf": "validated",
                },
                "results": [],
            }
        ),
        encoding="utf-8",
    )
    (corpus / "calibration_summary.json").write_text("{}", encoding="utf-8")

    status = build_status(tmp_path)

    assert status["state"] == "running"
    assert status["active_progress"] == {
        "label": "remaining papers recorded locally",
        "completed": 1,
        "total": 2,
        "percent": 50.0,
    }
    assert status["next_source"] == "Tier1/b.pdf"


def test_dashboard_principle_status_is_absent_without_artifacts(tmp_path: Path) -> None:
    status = build_status(tmp_path)

    assert status["principles"]["state"] == "absent"
    assert status["principles"]["hidden_answers"] == {
        "state": "locked",
        "revealed": False,
    }


def test_dashboard_reports_v3_saturation_and_three_freezes(tmp_path: Path) -> None:
    root = tmp_path / "derived/principles_v3"
    root.mkdir(parents=True)
    saturation = root / "saturation.json"
    saturation.write_text(
        json.dumps({"state": "passed", "round_count": 3, "novel_family_count": 0}),
        encoding="utf-8",
    )
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "version": 3,
                "phases": {
                    "saturate": {"status": "complete", "artifact": str(saturation)},
                    "freeze-1": {"status": "complete"},
                    "freeze-2": {"status": "complete"},
                    "freeze-3": {"status": "complete"},
                },
            }
        ),
        encoding="utf-8",
    )

    v3 = build_status(tmp_path)["v3"]

    assert v3["saturation"]["state"] == "passed"
    assert v3["freezes"] == {"freeze_1": True, "freeze_2": True, "freeze_3": True}


def test_dashboard_reports_formal_v3_2_rounds_and_platform_block(tmp_path: Path) -> None:
    root = tmp_path / "runs/reaction_principle_v3_2/derived/principles_v3"
    (root / "rounds").mkdir(parents=True)
    (root / "round_attempts").mkdir()
    (root / "preregistration.json").write_text('{"version":"3.2"}', encoding="utf-8")
    (root / "rounds/round_1.json").write_text(
        json.dumps(
            {
                "lane_results": [{"proposals": [{}, {}]}],
                "taxonomy": {"families": [{}, {}, {}]},
                "platform_failures": [],
            }
        ),
        encoding="utf-8",
    )
    (root / "round_attempts/round_2_failure.json").write_text(
        json.dumps({"platform_failures": [{"error_type": "upstream_error"}]}),
        encoding="utf-8",
    )

    status = build_status(tmp_path)["v3_2"]

    assert status["state"] == "platform_blocked"
    assert status["completed_rounds"] == 1
    assert status["family_counts"] == [3]
    assert status["proposal_counts"] == [2]


def test_dashboard_prefers_capped_v3_3_review_over_historical_v3_2(tmp_path: Path) -> None:
    root = tmp_path / "runs/reaction_principle_v3_3/derived/principles_v3"
    (root / "rounds").mkdir(parents=True)
    (root / "preregistration.json").write_text('{"version":"3.3"}', encoding="utf-8")
    for round_id in range(1, 6):
        (root / f"rounds/round_{round_id}.json").write_text(
            json.dumps(
                {
                    "lane_results": [{"proposals": [{}]}],
                    "taxonomy": {"families": [{}]},
                    "platform_failures": [],
                }
            ),
            encoding="utf-8",
        )
    (root / "saturation.json").write_text(
        json.dumps({"saturation": {"saturated": False, "new_family_rate": 0.44}}),
        encoding="utf-8",
    )
    (root / "chemical_review.json").write_text(
        json.dumps(
            {
                "freeze_2_allowed": False,
                "freeze_2_blockers": ["novelty"],
                "family_disposition_counts": {"unresolved": 20},
                "coordinate_disposition_counts": {"covered": 14, "unknown": 21},
            }
        ),
        encoding="utf-8",
    )

    status = build_status(tmp_path)["v3_formal"]

    assert status["version"] == "3.3"
    assert status["state"] == "capped_not_converged"
    assert status["completed_rounds"] == 5
    assert status["review"]["coordinate_disposition_counts"] == {
        "covered": 14,
        "unknown": 21,
    }


def test_pre_reveal_dashboard_never_contains_sealed_plaintext(tmp_path: Path) -> None:
    root = tmp_path / "derived/principles_v3"
    root.mkdir(parents=True)
    sealed = tmp_path / "sealed_validation_registry.json"
    sealed.write_text('{"secret": "SYNTHETIC_SEALED_TERM"}', encoding="utf-8")
    (root / "manifest.json").write_text(
        json.dumps({"version": 3, "phases": {"freeze-3": {"status": "complete"}}}),
        encoding="utf-8",
    )

    serialized = json.dumps(build_status(tmp_path), ensure_ascii=False)

    assert "SYNTHETIC_SEALED_TERM" not in serialized
    assert build_status(tmp_path)["v3"]["validation"]["revealed"] is False


def test_dashboard_principle_status_reports_running_failures_and_revisits(tmp_path: Path) -> None:
    root = tmp_path / "derived" / "principles"
    root.mkdir(parents=True)
    (root / "evidence_registry.json").write_text(
        json.dumps(
            {
                "queue_paper_count": 204,
                "scoped_record_count": 204,
                "missing_source_paths": [],
            }
        ),
        encoding="utf-8",
    )
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "phases": {
                    "normalize": {
                        "status": "completed_with_failures",
                        "records": {
                            "a.pdf": {"status": "validated"},
                            "b.pdf": {"status": "failed", "failure_reason": "schema"},
                        },
                    }
                },
                "source_revisits": [{"request_id": "SR-1", "status": "pending"}],
            }
        ),
        encoding="utf-8",
    )

    principles = build_status(tmp_path)["principles"]

    assert principles["state"] == "failed"
    assert principles["normalization"]["status_counts"] == {"failed": 1, "validated": 1}
    assert principles["normalization"]["pending_source_revisit_count"] == 1
    assert principles["failures"] == [{"source_path": "b.pdf", "reason": "schema"}]


def test_dashboard_reports_semantic_transfer_progress_from_local_manifest(
    tmp_path: Path,
) -> None:
    root = tmp_path / "derived/principles"
    root.mkdir(parents=True)
    (root / "transfer_manifest.json").write_text(
        json.dumps(
            {
                "status": "running",
                "paper_count": 200,
                "updated_at": "2026-08-05T09:00:00+00:00",
                "records": {
                    "a.pdf": {"status": "reused", "assessment_count": 14},
                    "b.pdf": {"status": "validated", "assessment_count": 9},
                    "c.pdf": {"status": "failed", "failure_reason": "timeout"},
                },
            }
        ),
        encoding="utf-8",
    )

    principles = build_status(tmp_path)["principles"]

    assert principles["knowledge_transfer"] == {
        "state": "running",
        "processed_count": 3,
        "successful_count": 2,
        "failed_count": 1,
        "paper_count": 200,
        "assessment_count": 23,
        "percent": 1.5,
        "updated_at": "2026-08-05T09:00:00+00:00",
    }
    assert {item["source_path"] for item in principles["failures"]} == {"c.pdf"}


def test_dashboard_principle_status_reports_review_required(tmp_path: Path) -> None:
    root = tmp_path / "derived" / "principles"
    root.mkdir(parents=True)
    (root / "principle_review.json").write_text(
        json.dumps(
            {
                "principles": [
                    {"principle_id": "RP-001", "review_status": "pending"},
                    {"principle_id": "RP-002", "review_status": "accepted"},
                ]
            }
        ),
        encoding="utf-8",
    )

    principles = build_status(tmp_path)["principles"]

    assert principles["state"] == "review_required"
    assert principles["human_review"]["pending_principle_ids"] == ["RP-001"]


def test_dashboard_labels_provisional_boundary_and_candidate_outputs(tmp_path: Path) -> None:
    root = tmp_path / "derived" / "principles"
    root.mkdir(parents=True)
    (root / "family_predictions.json").write_text(
        json.dumps(
            {
                "families": [
                    {"family_id": "NU-S", "classification": "explore"},
                    {"family_id": "NU-N", "classification": "exclude"},
                    {"family_id": "NU-O", "classification": "insufficient_evidence"},
                ]
            }
        ),
        encoding="utf-8",
    )
    (root / "provisional_candidates.json").write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "experiment_id": "EXP-001",
                        "electrophile": "E1",
                        "nucleophile": "N1",
                        "predicted_outcome": "explore",
                        "experiment_priority": 1,
                        "total_score": 17,
                        "freeze_status": "provisional",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    principles = build_status(tmp_path)["principles"]

    assert principles["family_boundaries"] == {
        "provisional": True,
        "counts": {"exclude": 1, "explore": 1, "insufficient_evidence": 1},
    }
    assert principles["top_candidates"][0]["experiment_id"] == "EXP-001"
    assert principles["top_candidates"][0]["provisional"] is True


def test_dashboard_suppresses_candidates_while_v3_5_freeze_2_is_blocked(
    tmp_path: Path,
) -> None:
    principles_root = tmp_path / "derived/principles"
    principles_root.mkdir(parents=True)
    (principles_root / "provisional_candidates.json").write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "experiment_id": "EXP-OLD",
                        "predicted_outcome": "explore",
                        "experiment_priority": 1,
                        "total_score": 17,
                        "freeze_status": "provisional",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    v35 = tmp_path / "runs/reaction_principle_v3_5/derived/principles_v3"
    v35.mkdir(parents=True)
    (v35 / "status.json").write_text(
        '{"version":"3.5","freeze_2_allowed":false}', encoding="utf-8"
    )

    status = build_status(tmp_path)

    assert status["v3_5"]["freeze_2_allowed"] is False
    assert status["principles"]["top_candidates"] == []


@pytest.mark.parametrize("v35_status", ("{}", "{malformed"))
def test_dashboard_suppresses_candidates_when_existing_v3_5_status_is_invalid(
    tmp_path: Path,
    v35_status: str,
) -> None:
    principles_root = tmp_path / "derived/principles"
    principles_root.mkdir(parents=True)
    (principles_root / "provisional_candidates.json").write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "experiment_id": "EXP-OLD",
                        "predicted_outcome": "explore",
                        "experiment_priority": 1,
                        "total_score": 17,
                        "freeze_status": "provisional",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    v35 = tmp_path / "runs/reaction_principle_v3_5/derived/principles_v3"
    v35.mkdir(parents=True)
    (v35 / "status.json").write_text(v35_status, encoding="utf-8")

    status = build_status(tmp_path)

    assert status["principles"]["top_candidates"] == []


def test_dashboard_hides_scope_rejected_candidates_from_top_table(tmp_path: Path) -> None:
    root = tmp_path / "derived" / "principles"
    root.mkdir(parents=True)
    (root / "provisional_candidates.json").write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "experiment_id": "EXP-OUT",
                        "electrophile": "isolated intermediate",
                        "nucleophile": "N1",
                        "predicted_outcome": "insufficient_evidence",
                        "experiment_priority": 1,
                        "total_score": 30,
                        "freeze_status": "provisional",
                    },
                    {
                        "experiment_id": "EXP-IN",
                        "electrophile": "SR001 substrate",
                        "nucleophile": "N2",
                        "predicted_outcome": "insufficient_evidence",
                        "experiment_priority": 2,
                        "total_score": 20,
                        "freeze_status": "provisional",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "chemistry_review.json").write_text(
        json.dumps(
            {
                "candidate_review": {
                    "reviewed_candidate_count": 2,
                    "fixed_seed_substrate_compliant_count": 1,
                    "out_of_scope_intermediate_count": 1,
                    "out_of_scope_intermediate_experiment_ids": ["EXP-OUT"],
                    "overall_decision": "accepted_with_candidate_scope_revisions",
                }
            }
        ),
        encoding="utf-8",
    )

    principles = build_status(tmp_path)["principles"]

    assert [row["experiment_id"] for row in principles["top_candidates"]] == [
        "EXP-IN"
    ]
    assert principles["candidate_scope_review"] == {
        "reviewed_count": 2,
        "stage_one_compliant_count": 1,
        "rejected_count": 1,
        "decision": "accepted_with_candidate_scope_revisions",
    }


def test_dashboard_exposes_v2_axis_layers_and_nucleophile_coverage(tmp_path: Path) -> None:
    root = tmp_path / "derived" / "principles"
    root.mkdir(parents=True)
    (root / "exploration_brief.json").write_text(
        json.dumps(
            {
                "version": "2.0",
                "stage": "fixed_electrophile_nucleophile_condition",
                "fixed_role": {"role": "electrophile", "label": "Seed A"},
                "variable_role": {"role": "nucleophile", "label": "substrate B"},
                "digest": "a" * 64,
            }
        ),
        encoding="utf-8",
    )
    (root / "coverage_audit.json").write_text(
        json.dumps(
            {
                "required_superclass_ids": [f"NUC-{index}" for index in range(8)],
                "covered_superclass_ids": [f"NUC-{index}" for index in range(8)],
                "missing_superclass_ids": [],
                "extra_superclass_ids": [],
                "complete": True,
            }
        ),
        encoding="utf-8",
    )
    (root / "role_aware_evidence_index.json").write_text(
        json.dumps({"mapped_count": 120, "unmapped_count": 30}),
        encoding="utf-8",
    )
    (root / "principle_review.json").write_text(
        json.dumps(
            {
                "principles": [
                    {
                        "principle_id": "RP-S",
                        "principle_layer": "seed_specific",
                        "review_status": "accepted",
                    },
                    {
                        "principle_id": "RP-T",
                        "principle_layer": "transferable_super",
                        "review_status": "accepted",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    (root / "retrospective_development_registry.json").write_text(
        json.dumps(
            {
                "usage": "retrospective_development_only",
                "prospective_metric_eligible": False,
                "outcomes": [{"family": "SH/thiol"}],
            }
        ),
        encoding="utf-8",
    )

    principles = build_status(tmp_path)["principles"]

    assert principles["exploration"]["fixed_role"] == "electrophile"
    assert principles["exploration"]["variable_role"] == "nucleophile"
    assert principles["principle_layers"] == {
        "seed_specific": 1,
        "transferable_super": 1,
    }
    assert principles["nucleophile_coverage"]["required_count"] == 8
    assert principles["nucleophile_coverage"]["missing_count"] == 0
    assert principles["retrospective_development"]["prospective_metric_eligible"] is False

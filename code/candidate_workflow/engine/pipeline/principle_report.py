"""Provisional Reaction Principle and chemical-boundary reporting."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from pydantic import ValidationError

from pipeline.evidence_registry import _atomic_json
from pipeline.model_proposals import select_principle_evidence
from pipeline.principle_models import (
    ExperimentCandidate,
    FamilyBoundaryPrediction,
    ReactionPrinciple,
    SeedMechanism,
    SeedPrinciple,
    TransferabilityAssessment,
)
from pipeline.transfer_audit import KnowledgeTransferAudit


class PrincipleReportError(RuntimeError):
    """Raised when provisional report inputs are incomplete or unsafe."""


_V3_REGIONS = (
    "Priority A",
    "Priority B",
    "Priority C",
    "Boundary",
    "Excluded",
    "Unknown",
)


def _v3_public_artifact(namespace: Path, record: object) -> dict[str, object]:
    if not isinstance(record, dict) or record.get("status") != "complete":
        return {}
    raw_path = record.get("artifact")
    if not isinstance(raw_path, str):
        return {}
    path = Path(raw_path)
    if not path.is_absolute():
        path = namespace / path
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(namespace.resolve())
    except (OSError, ValueError):
        return {}
    lowered = resolved.name.casefold()
    if "sealed" in lowered or "registry" in lowered:
        return {}
    value = _load(resolved, "public v3 artifact")
    return value


def _v3_family_rows(payloads: Iterable[dict[str, object]]) -> list[dict[str, object]]:
    by_id: dict[str, dict[str, object]] = {}
    for payload in payloads:
        raw_rows = payload.get("families", [])
        if not isinstance(raw_rows, list):
            continue
        for raw in raw_rows:
            if not isinstance(raw, dict):
                continue
            family_id = raw.get("family_id")
            if not isinstance(family_id, str) or not family_id:
                continue
            row = by_id.setdefault(family_id, {"family_id": family_id})
            row.update(raw)
    rows: list[dict[str, object]] = []
    for family_id in sorted(by_id):
        row = by_id[family_id]
        region = row.get("region", row.get("disposition", "Unknown"))
        if region not in _V3_REGIONS:
            region = "Unknown"
        row["region"] = region
        if region in {"Boundary", "Excluded", "Unknown"}:
            row.pop("primary_rank", None)
            row.pop("equal_weight_rank", None)
        rows.append(row)
    return rows


def _v3_workflow_state(
    manifest: dict[str, object], saturate_payload: dict[str, object]
) -> dict[str, object]:
    """Expose public gate status without interpreting chemistry beyond the gate."""

    phases = manifest.get("phases", {})
    phase_status: dict[str, str] = {}
    if isinstance(phases, dict):
        for phase in (
            "prepare", "freeze-1", "retrieve-seed", "discover",
            "retrieve-hypotheses", "saturate", "freeze-2", "evaluate",
            "diagnostics", "freeze-3",
        ):
            record = phases.get(phase)
            if isinstance(record, dict) and isinstance(record.get("status"), str):
                phase_status[phase] = str(record["status"])
    saturation = saturate_payload.get("saturation", {})
    if not isinstance(saturation, dict):
        saturation = {}
    blockers: list[str] = []
    checks = (
        ("consecutive_low_new_family_rounds", "连续低新颖度轮次要求尚未满足"),
        ("coordinate_combinations_stable", "机制坐标组合尚未稳定"),
        ("lane_converged", "独立 discovery lane 尚未收敛"),
        ("coverage_dispositioned", "至少一个机制坐标仍为 unknown"),
        ("additional_evidence_batch_no_material_change", "追加证据批次仍改变 taxonomy"),
    )
    for key, label in checks:
        value = saturation.get(key)
        if key == "consecutive_low_new_family_rounds":
            if not isinstance(value, int) or value < 2:
                blockers.append(label)
        elif value is not True:
            blockers.append(label)
    return {
        "phase_status": phase_status,
        "saturation": {
            key: saturation[key]
            for key in (
                "completed_rounds", "new_family_rate", "material_taxonomy_change_rate",
                "consecutive_low_new_family_rounds", "lane_converged",
                "coordinate_combinations_stable", "coverage_dispositioned",
                "additional_evidence_batch_no_material_change", "saturated",
                "uncovered_coordinate_dispositions",
            )
            if key in saturation
        },
        "freeze_2_allowed": saturation.get("saturated") is True,
        "blockers": blockers,
    }


def build_v3_report(output_root: Path) -> dict[str, object]:
    """Build a Chinese, pre-reveal-safe report from public v3 artifacts only."""

    namespace = output_root.resolve() / "derived" / "principles_v3"
    manifest_path = namespace / "manifest.json"
    manifest = _load(manifest_path, "v3 workflow manifest")
    phases = manifest.get("phases", {})
    if not isinstance(phases, dict):
        raise PrincipleReportError("v3 workflow manifest phases must be a mapping")
    payloads = [
        _v3_public_artifact(namespace, phases.get(phase))
        for phase in ("discover", "saturate", "evaluate", "diagnostics", "validate")
    ]
    saturate_payload = payloads[1]
    workflow_state = _v3_workflow_state(manifest, saturate_payload)
    families = _v3_family_rows(payloads)
    groups = {
        region: [row for row in families if row["region"] == region]
        for region in _V3_REGIONS
    }
    reveal = phases.get("reveal")
    revealed = isinstance(reveal, dict) and reveal.get("status") == "complete"
    lines = [
        "# 开放分类 Reaction Principle 工作流报告",
        "",
        f"揭盲状态：{'已完成' if revealed else '未揭盲'}。",
        "",
        "本文中的数值为优先级指数及稳健性诊断，不是成功率，也不构成通用适用性声明。",
        "",
        "## 当前工作流门控",
        "",
        f"Freeze 2 是否允许：{'是' if workflow_state['freeze_2_allowed'] else '否'}。",
        "",
    ]
    if workflow_state["blockers"]:
        lines.append("阻塞项：")
        lines.extend(f"- {item}" for item in workflow_state["blockers"])
    else:
        lines.append("当前没有公开门控阻塞项。")
    lines.append("")
    for region in _V3_REGIONS:
        lines.extend([f"## {region}", ""])
        for row in groups[region]:
            family_id = row["family_id"]
            family_name = row.get("family_name", row.get("name", family_id))
            lines.append(f"- `{family_id}` {family_name}")
            score = row.get("primary_score", row.get("score"))
            if score is not None and region not in {"Boundary", "Excluded", "Unknown"}:
                lines.append(f"  - 优先级指数：{score}")
            lines.append(
                f"  - 证据边界：{row.get('evidence_basis', row.get('main_support', 'unknown'))}"
            )
            lines.append(f"  - 不确定性：{row.get('uncertainty', 'unknown')}")
        if not groups[region]:
            lines.append("- 无公开记录")
        lines.append("")
    report = {
        "report_version": "v3-public-1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "revealed": revealed,
        "families": families,
        "groups": groups,
        "workflow_state": workflow_state,
        "markdown": "\n".join(lines),
        "claim_boundaries": {
            "priority_is_probability": False,
            "prospective_hit_rate_claim_available": False,
            "universal_applicability_claim_available": False,
        },
        "provenance": {"manifest_sha256": _sha256(manifest_path)},
    }
    return report


def write_v3_report(output_root: Path) -> tuple[Path, Path]:
    """Write the public Chinese v3 report without reading sealed inputs."""

    report = build_v3_report(output_root)
    report_root = output_root.resolve() / "reports"
    json_path = report_root / "reaction_principle_v3.json"
    markdown_path = report_root / "reaction_principle_v3_zh.md"
    _atomic_json(json_path, report)
    _atomic_text(markdown_path, str(report["markdown"]))
    return json_path, markdown_path


def _load(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PrincipleReportError(f"cannot read {label}: {path}") from exc
    if not isinstance(value, dict):
        raise PrincipleReportError(f"{label} must be a JSON object")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _family_boundaries(
    principles: list[ReactionPrinciple], *, review_complete: bool
) -> dict[str, list[dict]]:
    fields = {
        "nucleophile": "applicable_nucleophile_families",
        "electrophile": "applicable_electrophile_families",
        "catalyst": "catalyst_requirements",
        "condition": "condition_window",
    }
    result: dict[str, list[dict]] = {}
    for boundary_type, field in fields.items():
        rows: dict[str, dict] = {}
        for principle in principles:
            for family in getattr(principle, field):
                row = rows.setdefault(
                    family,
                    {
                        "family_or_requirement": family,
                        "classification": "provisional_worthwhile_to_test",
                        "principle_ids": [],
                        "assessment_ids": [],
                        "required_human_review": not review_complete,
                    },
                )
                row["principle_ids"].append(principle.principle_id)
                row["assessment_ids"].extend(principle.supporting_transferred_evidence)
        for row in rows.values():
            row["principle_ids"] = _unique(row["principle_ids"])
            row["assessment_ids"] = _unique(row["assessment_ids"])
        result[boundary_type] = [rows[key] for key in sorted(rows)]
    return result


def _markdown(report: dict) -> str:
    review_complete = report["review_and_freeze_state"]["review_status"] != "pending"
    lines = [
        "# Reaction Principle and Chemical Boundary Report",
        "",
        f"Status: `{report['report_status']}`. "
        + (
            "AI proxy chemistry review is complete; Principles and candidates remain unfrozen."
            if review_complete
            else "Chemistry review is required before freeze."
        ),
        "",
        "## Seed Principle",
        "",
        f"**{report['seed_principle']['title']}**",
        "",
        report["seed_principle"]["claim"],
        "",
        "## Transferred Mechanisms",
        "",
        f"Bounded selection: {len(report['transferred_mechanisms'])} assessments; "
        f"full audited corpus: {report['knowledge_transfer_audit']['assessment_count']} assessments.",
        "",
    ]
    if report.get("exploration"):
        exploration = report["exploration"]
        coverage = report.get("nucleophile_coverage", {})
        lines.extend(
            [
                "## User-Directed Exploration",
                "",
                f"Stage: `{exploration.get('stage', 'unknown')}`; fixed role: "
                f"`{exploration.get('fixed_role', {}).get('role', 'unknown')}`; "
                f"variable role: `{exploration.get('variable_role', {}).get('role', 'unknown')}`.",
                "",
                f"Nucleophile superclass coverage complete: "
                f"`{coverage.get('complete', False)}`; missing: "
                f"{', '.join(coverage.get('missing_superclass_ids', [])) or 'none'}.",
                "",
                "### Principle Layers",
                "",
            ]
        )
        for layer, rows in report.get("principle_layers", {}).items():
            lines.append(f"- `{layer}`: {len(rows)} reviewed or proposed Principles")
        lines.extend(
            [
                "",
                "### Validation Contamination",
                "",
                report["validation_statement"],
                "",
            ]
        )
    for row in report["transferred_mechanisms"]:
        lines.append(
            f"- `{row['assessment_id']}` [{row['transfer_status']}]: "
            f"{row['transferable_claim']}"
        )
    lines.extend(["", "## Physical-Organic Rules", ""])
    for row in report["physical_organic_rules"]:
        lines.append(f"- `{row['principle_id']}`: {'; '.join(row['mechanistic_basis'])}")
    lines.extend(["", "## Negative Boundaries", ""])
    for row in report["negative_boundaries"]:
        lines.append(f"- [{row['source']}] {row['statement']}")
    lines.extend(["", "## Reaction Principle Candidates", ""])
    for row in report["reaction_principle_candidates"]:
        lines.append(f"- `{row['principle_id']}` **{row['title']}**: {row['claim']}")
    lines.extend(["", "## Family Boundaries", ""])
    for boundary_type, rows in report["family_boundaries"].items():
        lines.append(f"### {boundary_type.title()}")
        lines.append("")
        for row in rows:
            lines.append(
                f"- {row['family_or_requirement']} "
                f"(`{row['classification']}`; Principles: "
                f"{', '.join(row['principle_ids'])})"
            )
        lines.append("")
    if report["ranked_family_boundaries"]:
        lines.extend(["## Ranked Family Boundaries", ""])
        for row in report["ranked_family_boundaries"]:
            lines.append(
                f"- `{row['family_id']}` [{row['family_type']}]: "
                f"`{row['classification']}`, score {row['total_score']}"
            )
        lines.append("")
    if report["ranked_experiment_candidates"]:
        lines.extend(["## Ranked Experiment Candidates", ""])
        for row in report["ranked_experiment_candidates"]:
            lines.append(
                f"- #{row['experiment_priority']} `{row['experiment_id']}` "
                f"(`{row['predicted_outcome']}`, score {row['total_score']}): "
                f"{row['electrophile']} + {row['nucleophile']}"
            )
        lines.append("")
    lines.extend(["## Worthwhile Chemical Space", ""])
    for row in report["worthwhile_chemical_space"]:
        lines.append(
            f"- [{row['boundary_type']}] {row['family_or_requirement']} "
            f"({', '.join(row['principle_ids'])})"
        )
    lines.extend(["", "## Low-Value Chemical Space", ""])
    for row in report["low_value_chemical_space"]:
        lines.append(f"- `{row['principle_id']}`: {row['reason']}")
    lines.extend(["", "## Diagnostic Experiments", ""])
    for row in report["diagnostic_experiments"]:
        lines.append(f"- `{row['principle_id']}`: {row['falsifying_experiment']}")
    lines.extend(["", "## Uncertainties", ""])
    for value in report["uncertainties"]:
        lines.append(f"- {value}")
    lines.extend(
        [
            "",
            "## Source Revisits",
            "",
            f"Pending or recorded source revisits: {len(report['source_revisits'])}.",
            "",
            "## Technical Exclusions",
            "",
            report["technical_exclusions"].get("scientific_interpretation", ""),
            "",
            "## Provenance",
            "",
        ]
    )
    for name, digest in report["provenance"]["artifact_sha256"].items():
        lines.append(f"- `{name}`: `{digest}`")
    lines.extend(
        [
            "",
            "## Human Review and Freeze State",
            "",
            (
                "AI proxy chemistry review is complete. No Principle, scoring snapshot, "
                "or candidate list has been frozen, and hidden outcomes remain locked."
                if review_complete
                else "Principles are pending chemistry review. No Principle, scoring "
                "snapshot, or candidate list has been frozen, and hidden outcomes remain locked."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(value)
        temp = Path(handle.name)
    os.replace(temp, path)


def write_principle_report(
    output_root: Path,
    *,
    max_assessments: int = 80,
    max_per_paper: int = 3,
) -> tuple[Path, Path]:
    """Write an allowlisted, hidden-safe report from audited transfer artifacts."""

    root = output_root.resolve()
    principle_root = root / "derived/principles"
    paths = {
        "seed_mechanism": principle_root / "seed_mechanism.json",
        "seed_principle": principle_root / "seed_principle.json",
        "transfer_assessments": principle_root / "transfer_assessments.json",
        "source_revisits": principle_root / "source_revisit_registry.json",
        "technical_exclusions": principle_root / "technical_exclusions.json",
        "knowledge_transfer_audit": root / "reports/knowledge_transfer_audit.json",
    }
    optional_v2_paths = {
        "exploration_brief": principle_root / "exploration_brief.json",
        "coverage_audit": principle_root / "coverage_audit.json",
        "role_aware_evidence_index": principle_root
        / "role_aware_evidence_index.json",
        "retrospective_development": principle_root
        / "retrospective_development_registry.json",
    }
    for name, path in optional_v2_paths.items():
        if path.is_file():
            paths[name] = path
    review_path = principle_root / "principle_review.json"
    proposal_path = principle_root / "principle_proposals.json"
    paths["principles"] = review_path if review_path.is_file() else proposal_path
    family_predictions_path = principle_root / "family_predictions.json"
    provisional_candidates_path = principle_root / "provisional_candidates.json"
    chemistry_review_path = root / "reports/chemistry_review.json"
    if family_predictions_path.is_file():
        paths["family_predictions"] = family_predictions_path
    if provisional_candidates_path.is_file():
        paths["provisional_candidates"] = provisional_candidates_path
    if chemistry_review_path.is_file():
        paths["chemistry_review"] = chemistry_review_path
    try:
        seed = SeedMechanism.model_validate(_load(paths["seed_mechanism"], "Seed Mechanism"))
        seed_principle = SeedPrinciple.model_validate(
            _load(paths["seed_principle"], "Seed Principle")
        )
        transfer_payload = _load(paths["transfer_assessments"], "transfer assessments")
        assessments = {
            item.assessment_id: item
            for item in (
                TransferabilityAssessment.model_validate(row)
                for row in transfer_payload.get("assessments", [])
            )
        }
        principle_payload = _load(paths["principles"], "Reaction Principle candidates")
        principles = [
            ReactionPrinciple.model_validate(row)
            for row in principle_payload.get("principles", [])
        ]
        audit = KnowledgeTransferAudit.model_validate(
            _load(paths["knowledge_transfer_audit"], "Knowledge Transfer audit")
        )
        ranked_families = (
            [
                FamilyBoundaryPrediction.model_validate(row)
                for row in _load(
                    family_predictions_path, "ranked family boundaries"
                ).get("families", [])
            ]
            if family_predictions_path.is_file()
            else []
        )
        ranked_candidates = (
            [
                ExperimentCandidate.model_validate(row)
                for row in _load(
                    provisional_candidates_path, "ranked experiment candidates"
                ).get("candidates", [])
            ]
            if provisional_candidates_path.is_file()
            else []
        )
    except (ValidationError, TypeError) as exc:
        raise PrincipleReportError(f"invalid report input: {exc}") from exc
    if not assessments or not principles:
        raise PrincipleReportError("report requires transfer assessments and Principles")
    pending_review = all(
        item.review_status == "pending" and item.status == "proposed"
        for item in principles
    )
    review_complete = all(
        item.review_status in {"accepted", "revised"}
        and item.status in {"accepted", "revised"}
        for item in principles
    )
    if not pending_review and not review_complete:
        raise PrincipleReportError(
            "report requires uniformly pending or uniformly reviewed Principles"
        )
    if audit.assessment_count != len(assessments):
        raise PrincipleReportError("audit and transfer assessment counts do not match")

    selection = select_principle_evidence(
        seed,
        assessments,
        max_assessments=max_assessments,
        max_per_paper=max_per_paper,
    )
    selected = [assessments[item] for item in selection.assessment_ids]
    chemistry_review = (
        _load(chemistry_review_path, "chemistry review")
        if chemistry_review_path.is_file()
        else {}
    )
    exploration = (
        _load(optional_v2_paths["exploration_brief"], "exploration brief")
        if optional_v2_paths["exploration_brief"].is_file()
        else None
    )
    nucleophile_coverage = (
        _load(optional_v2_paths["coverage_audit"], "coverage audit")
        if optional_v2_paths["coverage_audit"].is_file()
        else None
    )
    role_aware_evidence_index = (
        _load(optional_v2_paths["role_aware_evidence_index"], "role-aware evidence index")
        if optional_v2_paths["role_aware_evidence_index"].is_file()
        else None
    )
    retrospective_development = (
        _load(optional_v2_paths["retrospective_development"], "retrospective development registry")
        if optional_v2_paths["retrospective_development"].is_file()
        else None
    )
    ai_proxy_review = review_complete and chemistry_review.get("reviewer_type") == "ai_proxy"
    report_status = (
        "provisional_ai_reviewed"
        if ai_proxy_review
        else "provisional_reviewed"
        if review_complete
        else "provisional_unreviewed"
    )
    family_boundaries = _family_boundaries(
        principles, review_complete=review_complete
    )
    worthwhile = [
        {"boundary_type": boundary_type, **row}
        for boundary_type, rows in family_boundaries.items()
        for row in rows
    ]
    negative_boundaries = [
        {"source": "Seed Principle", "statement": statement}
        for statement in seed_principle.failure_boundaries
    ]
    negative_boundaries.extend(
        {
            "source": principle.principle_id,
            "statement": statement,
        }
        for principle in principles
        for statement in [*principle.structural_inhibitors, *principle.known_exceptions]
    )
    negative_boundaries.extend(
        {
            "source": assessment.assessment_id,
            "statement": assessment.transferable_claim,
            "blocking_constraint_ids": list(assessment.blocking_constraints),
        }
        for assessment in selected
        if assessment.transfer_status == "non_transferable"
    )
    low_value = [
        {
            "principle_id": principle.principle_id,
            "reason": reason,
            "classification": "provisional_deprioritize",
        }
        for principle in principles
        for reason in [
            *principle.structural_inhibitors,
            *principle.known_exceptions,
            *principle.predicted_failure_modes,
        ]
    ]
    uncertainties = _unique(
        [
            *seed_principle.uncertainty,
            *(value for item in principles for value in item.known_exceptions),
            *(value for item in selected for value in item.uncertainty),
        ]
    )
    revisits = _load(paths["source_revisits"], "source revisits")
    exclusions = _load(paths["technical_exclusions"], "technical exclusions")
    report = {
        "report_status": report_status,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed_principle": seed_principle.model_dump(mode="json"),
        "knowledge_transfer_audit": audit.model_dump(mode="json"),
        "evidence_selection": selection.model_dump(mode="json"),
        "transferred_mechanisms": [item.model_dump(mode="json") for item in selected],
        "physical_organic_rules": [
            {
                "principle_id": item.principle_id,
                "mechanistic_basis": item.mechanistic_basis,
                "required_reactive_form": item.required_reactive_form,
                "structural_promoters": item.structural_promoters,
                "condition_window": item.condition_window,
                "assessment_ids": item.supporting_transferred_evidence,
            }
            for item in principles
        ],
        "negative_boundaries": negative_boundaries,
        "reaction_principle_candidates": [
            item.model_dump(mode="json") for item in principles
        ],
        "exploration": exploration,
        "principle_layers": {
            layer: [
                item.model_dump(mode="json")
                for item in principles
                if item.principle_layer == layer
            ]
            for layer in ("seed_specific", "transferable_super")
        }
        if exploration is not None
        else {},
        "nucleophile_coverage": nucleophile_coverage,
        "role_aware_evidence_index": role_aware_evidence_index,
        "retrospective_development": retrospective_development,
        "validation_statement": (
            "The disclosed SH, indole, naphthol, and disulfide outcomes cannot "
            "count as prospective prediction."
            if retrospective_development is not None
            else "Hidden outcomes remain locked for prospective validation."
        ),
        "family_boundaries": family_boundaries,
        "ranked_family_boundaries": [
            item.model_dump(mode="json")
            for item in sorted(
                ranked_families,
                key=lambda row: (-row.total_score, row.family_id),
            )
        ],
        "ranked_experiment_candidates": [
            item.model_dump(mode="json")
            for item in sorted(
                ranked_candidates, key=lambda row: row.experiment_priority
            )
        ],
        "chemistry_review": chemistry_review,
        "worthwhile_chemical_space": worthwhile,
        "low_value_chemical_space": low_value,
        "diagnostic_experiments": [
            {
                "principle_id": item.principle_id,
                "experimental_consequence": item.experimental_consequence,
                "falsifying_experiment": item.falsifying_experiment,
            }
            for item in principles
        ],
        "uncertainties": uncertainties,
        "source_revisits": revisits.get("revisits", []),
        "technical_exclusions": exclusions,
        "provenance": {
            "artifact_sha256": {name: _sha256(path) for name, path in paths.items()},
            "semantic_transfer_version": transfer_payload.get(
                "semantic_transfer_version"
            ),
        },
        "review_and_freeze_state": {
            "review_status": (
                "ai_proxy_review_complete"
                if ai_proxy_review
                else "review_complete"
                if review_complete
                else "pending"
            ),
            "principle_ids": [item.principle_id for item in principles],
            "principles_frozen": False,
            "scoring_snapshot_frozen": False,
            "candidate_list_frozen": False,
            "hidden_outcomes_revealed": False,
        },
    }
    serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)
    hidden_markers = ("PL30.xlsx", "新反应发现.pptx", "KNOWN_RETROSPECTIVE_SECRET")
    if any(marker in serialized for marker in hidden_markers):
        raise PrincipleReportError("hidden-answer marker detected in report input")

    report_root = root / "reports"
    json_path = report_root / "reaction_principle_report.json"
    markdown_path = report_root / "reaction_principle_report.md"
    _atomic_json(json_path, report)
    _atomic_text(markdown_path, _markdown(report))
    return markdown_path, json_path

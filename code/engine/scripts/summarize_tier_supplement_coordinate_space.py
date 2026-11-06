"""Consolidate open proposals into traceable mechanism-coordinate regions."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from pipeline.evidence_registry import _atomic_json
from pipeline.taxonomy_discovery import MechanismCoordinateAssignment


STATUS_ORDER = ("transferable", "conditional", "non_transferable", "unknown")
STATUS_WEIGHTS = {
    "transferable": 4,
    "conditional": 2,
    "non_transferable": -3,
    "unknown": 0,
}
CLASS_ORDER = {
    "explore_high": 0,
    "explore_conditional": 1,
    "boundary": 2,
    "deprioritize": 3,
    "insufficient_evidence": 4,
}


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _region_id(coordinate: dict[str, str]) -> str:
    return "MCR-" + hashlib.sha256(_canonical(coordinate).encode("utf-8")).hexdigest()[:12]


def _unique_strings(values: Iterable[object]) -> list[str]:
    return sorted({str(value).strip() for value in values if str(value).strip()})


def _statement_evidence(
    assessments: list[dict[str, Any]], fields: tuple[str, ...]
) -> list[dict[str, Any]]:
    support: dict[tuple[str, str], set[str]] = defaultdict(set)
    for assessment in assessments:
        assessment_id = str(assessment.get("assessment_id", ""))
        for field in fields:
            values = assessment.get(field, [])
            if not isinstance(values, list):
                continue
            for value in values:
                statement = str(value).strip()
                if statement and assessment_id:
                    support[(field, statement)].add(assessment_id)
    return [
        {
            "field": field,
            "statement": statement,
            "assessment_ids": sorted(assessment_ids),
        }
        for (field, statement), assessment_ids in sorted(support.items())
    ]


def _classification(counts: dict[str, int], score: int) -> str:
    transferable = counts["transferable"]
    conditional = counts["conditional"]
    negative = counts["non_transferable"]
    if transferable and score > 0 and not negative:
        return "explore_high"
    if (transferable or conditional) and negative:
        return "boundary"
    if conditional and score > 0:
        return "explore_conditional"
    if negative and not transferable and not conditional:
        return "deprioritize"
    return "insufficient_evidence"


def summarize_coordinate_space(
    round_payloads: list[dict[str, Any]],
    assessments: list[dict[str, Any]],
    registry_records: list[dict[str, Any]],
) -> dict[str, Any]:
    assessments_by_id = {
        str(row["assessment_id"]): row
        for row in assessments
        if isinstance(row, dict) and row.get("assessment_id")
    }
    papers = {
        str(row["candidate_id"]): row
        for row in registry_records
        if isinstance(row, dict) and row.get("candidate_id")
    }
    groups: dict[str, dict[str, Any]] = {}
    for round_payload in round_payloads:
        round_id = int(round_payload["round_id"])
        for lane in round_payload.get("lane_results", []):
            lane_id = str(lane.get("lane_id", "unknown"))
            channel = str(lane.get("channel", "unknown"))
            for proposal in lane.get("proposals", []):
                raw_coordinate = proposal.get("coordinate_assignment")
                coordinate = MechanismCoordinateAssignment.model_validate(
                    raw_coordinate
                ).model_dump(mode="json")
                key = _canonical(coordinate)
                group = groups.setdefault(
                    key,
                    {
                        "coordinate": coordinate,
                        "proposals": [],
                        "assessment_ids": set(),
                        "round_ids": set(),
                        "lane_ids": set(),
                        "channels": set(),
                    },
                )
                local_id = str(proposal.get("proposal_id", "unknown"))
                group["proposals"].append(
                    {
                        "proposal_id": f"R{round_id:03d}:{local_id}",
                        "local_proposal_id": local_id,
                        "round_id": round_id,
                        "lane_id": lane_id,
                        "channel": channel,
                        "evidence_level": proposal.get("evidence_level"),
                        "evidence_ids": _unique_strings(proposal.get("evidence_ids", [])),
                        "parent_hypothesis": proposal.get("parent_hypothesis"),
                        "representative_reactive_state": proposal.get(
                            "representative_reactive_state"
                        ),
                        "critical_conditions": proposal.get(
                            "mechanistic_definition", {}
                        ).get("critical_conditions", []),
                        "dominant_failure_modes": proposal.get(
                            "mechanistic_definition", {}
                        ).get("dominant_failure_modes", []),
                        "counterarguments": proposal.get("counterarguments", []),
                        "unknowns": proposal.get("unknowns", []),
                    }
                )
                group["round_ids"].add(round_id)
                group["lane_ids"].add(lane_id)
                group["channels"].add(channel)
                group["assessment_ids"].update(
                    evidence_id
                    for evidence_id in proposal.get("evidence_ids", [])
                    if evidence_id in assessments_by_id
                )

    regions: list[dict[str, Any]] = []
    for group in groups.values():
        cited_assessments = [
            assessments_by_id[assessment_id]
            for assessment_id in sorted(group["assessment_ids"])
        ]
        status_counter = Counter(
            str(row.get("transfer_status", "unknown"))
            for row in cited_assessments
        )
        counts = {status: status_counter.get(status, 0) for status in STATUS_ORDER}
        score = sum(STATUS_WEIGHTS[status] * counts[status] for status in STATUS_ORDER)
        source_paper_ids = sorted({
            str(row["source_paper_id"])
            for row in cited_assessments
            if row.get("source_paper_id")
        })
        evidence_rows = []
        tier_counter: Counter[str] = Counter()
        for assessment in cited_assessments:
            paper_id = str(assessment.get("source_paper_id", ""))
            paper = papers.get(paper_id, {})
            tier = paper.get("primary_tier")
            if tier:
                tier_counter[str(tier)] += 1
            evidence_rows.append(
                {
                    "assessment_id": assessment["assessment_id"],
                    "transfer_status": assessment.get("transfer_status"),
                    "source_paper_id": paper_id or None,
                    "title": paper.get("title"),
                    "doi": paper.get("doi"),
                    "source_url": paper.get("source_url"),
                    "tier": tier,
                    "source_evidence_ids": assessment.get("source_evidence_ids", []),
                    "transferable_claim": assessment.get("transferable_claim"),
                    "conditions": assessment.get("conditions", []),
                    "blocking_constraints": assessment.get("blocking_constraints", []),
                    "mismatched_requirements": assessment.get(
                        "mismatched_requirements", []
                    ),
                    "uncertainty": assessment.get("uncertainty", []),
                }
            )
        proposals = sorted(group["proposals"], key=lambda row: row["proposal_id"])
        regions.append(
            {
                "region_id": _region_id(group["coordinate"]),
                "coordinate": group["coordinate"],
                "proposal_count": len(proposals),
                "proposal_ids": [row["proposal_id"] for row in proposals],
                "round_ids": sorted(group["round_ids"]),
                "lane_ids": sorted(group["lane_ids"]),
                "channels": sorted(group["channels"]),
                "assessment_status_counts": counts,
                "assessment_count": len(cited_assessments),
                "source_paper_count": len(source_paper_ids),
                "tier_counts": dict(sorted(tier_counter.items())),
                "provisional_score": score,
                "classification": _classification(counts, score),
                "priority_rank": None,
                "condition_evidence": _statement_evidence(
                    cited_assessments, ("conditions",)
                ),
                "failure_boundary_evidence": _statement_evidence(
                    cited_assessments,
                    ("blocking_constraints", "mismatched_requirements"),
                ),
                "uncertainty_evidence": _statement_evidence(
                    cited_assessments, ("uncertainty",)
                ),
                "evidence_assessments": evidence_rows,
                "candidate_hypotheses": _unique_strings(
                    row.get("parent_hypothesis") for row in proposals
                ),
                "representative_reactive_states": _unique_strings(
                    row.get("representative_reactive_state") for row in proposals
                ),
                "proposal_conditions": _unique_strings(
                    value
                    for row in proposals
                    for value in row.get("critical_conditions", [])
                ),
                "proposal_failure_modes": _unique_strings(
                    value
                    for row in proposals
                    for value in row.get("dominant_failure_modes", [])
                ),
                "proposal_unknowns": _unique_strings(
                    value
                    for row in proposals
                    for value in row.get("unknowns", [])
                ),
            }
        )

    regions.sort(
        key=lambda row: (
            CLASS_ORDER[row["classification"]],
            -row["provisional_score"],
            -row["source_paper_count"],
            row["region_id"],
        )
    )
    rank = 0
    for region in regions:
        if region["classification"] == "insufficient_evidence":
            continue
        rank += 1
        region["priority_rank"] = rank
    return {
        "version": "tier-supplement-coordinate-summary-v1",
        "region_count": len(regions),
        "proposal_count": sum(row["proposal_count"] for row in regions),
        "scoring_rule": {
            "status_weights": STATUS_WEIGHTS,
            "duplicate_assessment_policy": "count each assessment_id once per region",
            "unknown_policy": "unknown contributes zero and cannot receive a rank alone",
            "exclusion_policy": "literature transfer evidence cannot create a hard exclusion",
        },
        "answer_isolation": {
            "named_expected_families_used": False,
            "known_outcomes_used": False,
        },
        "classification_counts": dict(
            sorted(Counter(row["classification"] for row in regions).items())
        ),
        "regions": regions,
    }


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object in {path}")
    return value


def _assessment_path(source_root: Path) -> Path:
    manifest = _read_json(source_root / "derived/principles_v3/evidence_import_manifest.json")
    rows = [
        row for row in manifest.get("accepted", [])
        if isinstance(row, dict) and row.get("artifact_type") == "transfer"
    ]
    if len(rows) != 1:
        raise ValueError("discovery source must contain exactly one transfer artifact")
    return source_root / str(rows[0]["path"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--round-root",
        type=Path,
        default=Path("runs/tier_supplement_v1/discovery_run/derived/principles_v3/rounds"),
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        default=Path("runs/tier_supplement_v1/discovery_source"),
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path("runs/tier_supplement_v1/supplement_evidence_registry_v2.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("runs/tier_supplement_v1/coordinate_space_summary.json"),
    )
    args = parser.parse_args()
    round_payloads = [
        _read_json(path) for path in sorted(args.round_root.glob("round_*.json"))
    ]
    assessment_payload = _read_json(_assessment_path(args.source_root))
    registry = _read_json(args.registry)
    result = summarize_coordinate_space(
        round_payloads,
        list(assessment_payload.get("assessments", [])),
        list(registry.get("records", [])),
    )
    _atomic_json(args.output, result)
    print(json.dumps({key: result[key] for key in ("version", "region_count", "proposal_count", "classification_counts")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

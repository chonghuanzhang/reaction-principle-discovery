"""Build a deterministic, answer-blinded queue for decision-critical full text."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from pipeline.evidence_registry import _atomic_json


def build_queue(records: list[dict[str, object]]) -> list[dict[str, object]]:
    selected: list[dict[str, object]] = []
    for record in records:
        screening = record.get("abstract_screening")
        if not isinstance(screening, dict) or screening.get("decision") != "include":
            continue
        priority = screening.get("full_text_priority")
        tier = screening.get("primary_tier")
        # High priority covers principle, ranking, condition, and boundary risks.
        # Medium priority is retained only for the two reaction-manifold/boundary tiers.
        if priority != "high" and not (priority == "medium" and tier in {"tier_2", "tier_4"}):
            continue
        if not record.get("doi") and not record.get("pdf_url") and not record.get("landing_url"):
            continue
        selected.append(
            {
                "candidate_id": record.get("candidate_id"),
                "doi": record.get("doi"),
                "title": record.get("title"),
                "primary_tier": tier,
                "evidence_roles": screening.get("evidence_roles", []),
                "transferable_steps": screening.get("transferable_steps", []),
                "condition_signals": screening.get("condition_signals", []),
                "failure_boundary_signals": screening.get("failure_boundary_signals", []),
                "full_text_priority": priority,
                "full_text_reasons": screening.get("full_text_reasons", []),
                "pdf_url": record.get("pdf_url"),
                "landing_url": record.get("landing_url"),
                "access": record.get("is_open_access"),
                "abstract_screening_evidence_level": screening.get("evidence_level"),
                "download_status": "pending",
            }
        )
    tier_order = {"tier_2": 0, "tier_3": 1, "tier_4": 2}
    priority_order = {"high": 0, "medium": 1}
    return sorted(
        selected,
        key=lambda row: (
            priority_order.get(str(row["full_text_priority"]), 9),
            tier_order.get(str(row["primary_tier"]), 9),
            str(row.get("doi") or row.get("title") or ""),
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("runs/tier_supplement_v1/abstract_screening_records.json"),
    )
    parser.add_argument(
        "--output", type=Path, default=Path("runs/tier_supplement_v1")
    )
    args = parser.parse_args()
    records = json.loads(args.input.read_text(encoding="utf-8"))["records"]
    queue = build_queue(records)
    payload = {
        "version": "1.0",
        "source_digest": hashlib.sha256(args.input.read_bytes()).hexdigest(),
        "answer_isolation": {
            "known_outcome_terms_used": False,
            "selection_based_only_on_screening_priority": True,
        },
        "evidence_boundary": (
            "Queue membership is a request for full-text verification, not an "
            "evidence conclusion."
        ),
        "count": len(queue),
        "queue": queue,
    }
    _atomic_json(args.output / "fulltext_upgrade_queue.json", payload)
    print(json.dumps({"count": len(queue)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

"""Build a provenance-preserving supplement registry from validated extractions."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from pipeline.evidence_registry import _atomic_json


def build_registry(extraction_root: Path, queue_path: Path) -> dict[str, object]:
    queue = {row["candidate_id"]: row for row in json.loads(queue_path.read_text(encoding="utf-8"))["queue"]}
    records: list[dict[str, object]] = []
    for path in sorted(extraction_root.glob("*/validated.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        extraction = payload.get("extraction", {})
        candidate_id = path.parent.name
        row = queue.get(candidate_id)
        if not isinstance(row, dict):
            continue
        records.append({
            "candidate_id": candidate_id,
            "doi": row.get("doi"),
            "title": extraction.get("bibliography", {}).get("title", row.get("title")),
            "primary_tier": extraction.get("primary_tier", row.get("primary_tier")),
            "source_file": extraction.get("source_file"),
            "sha256": extraction.get("sha256"),
            "evidence_types": extraction.get("evidence_types", []),
            "reaction_summary": extraction.get("reaction_summary", {}),
            "evidence_items": extraction.get("evidence_items", []),
            "uncertainties": extraction.get("uncertainties", []),
            "contradictions": extraction.get("contradictions", []),
            "validated_path": str(path),
            "evidence_level": "full_text_grounded_validated",
        })
    records.sort(key=lambda row: str(row["candidate_id"]))
    payload = {
        "registry_version": "tier-supplement-v1-fulltext",
        "source_queue": str(queue_path),
        "source_queue_sha256": hashlib.sha256(queue_path.read_bytes()).hexdigest(),
        "record_count": len(records),
        "evidence_item_count": sum(len(row["evidence_items"]) for row in records),
        "contradiction_count": sum(len(row["contradictions"]) for row in records),
        "tier_counts": dict(sorted(Counter(row["primary_tier"] for row in records).items())),
        "answer_isolation": {
            "known_outcome_terms_used": False,
            "known_success_substrates_used": False,
            "transferability_not_claimed": True,
        },
        "decision_boundary": "Only full-text-grounded validated records are in this registry; abstract-only and unresolved records are excluded.",
        "records": records,
    }
    payload["registry_sha256"] = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extractions", type=Path, default=Path("runs/tier_supplement_v1/extractions"))
    parser.add_argument("--queue", type=Path, default=Path("runs/tier_supplement_v1/fulltext_upgrade_queue.json"))
    parser.add_argument("--output", type=Path, default=Path("runs/tier_supplement_v1/supplement_evidence_registry.json"))
    args = parser.parse_args()
    registry = build_registry(args.extractions, args.queue)
    _atomic_json(args.output, registry)
    print(json.dumps({k: registry[k] for k in ("record_count", "evidence_item_count", "contradiction_count", "tier_counts", "registry_sha256")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

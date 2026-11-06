"""Build versioned web evidence and unresolved-access registries."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pipeline.evidence_registry import _atomic_json


def _digest(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _qualify_record_evidence(record: dict[str, Any]) -> dict[str, Any]:
    qualified = json.loads(json.dumps(record, ensure_ascii=False))
    candidate_id = str(qualified["candidate_id"])
    for item in qualified.get("evidence_items", []):
        local_id = str(item.get("local_evidence_id") or item.get("evidence_id") or "UNKNOWN")
        if local_id.startswith(candidate_id + ":"):
            local_id = local_id.split(":", 1)[1]
        item["local_evidence_id"] = local_id
        item["evidence_id"] = f"{candidate_id}:{local_id}"
    return qualified


def build_web_registry(extraction_root: Path) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for path in sorted(extraction_root.glob("*/validated.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        extraction = payload["extraction"]
        records.append(_qualify_record_evidence({
            "candidate_id": extraction["candidate_id"],
            "doi": extraction.get("doi"),
            "title": extraction.get("title"),
            "primary_tier": extraction["tier"],
            "source_url": extraction["source_url"],
            "source_sha256": payload["snapshot_sha256"],
            "retrieved_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
            "paper_summary": extraction.get("paper_summary"),
            "reaction_summary": {
                key: extraction.get(key)
                for key in ("reaction_class", "electrophile_class", "partner_class", "activation_mode", "catalyst_role")
            },
            "evidence_items": extraction.get("evidence_items", []),
            "uncertainties": extraction.get("uncertainties", []),
            "contradictions": extraction.get("contradictions", []),
            "validated_path": str(path),
            "evidence_level": "web_full_text_grounded_validated",
        }))
    records.sort(key=lambda row: row["candidate_id"])
    registry: dict[str, Any] = {
        "registry_version": "tier-supplement-v2-web-fulltext",
        "record_count": len(records),
        "evidence_item_count": sum(len(row["evidence_items"]) for row in records),
        "contradiction_count": sum(len(row["contradictions"]) for row in records),
        "tier_counts": dict(sorted(Counter(row["primary_tier"] for row in records).items())),
        "answer_isolation": {
            "known_outcome_terms_used_as_search_hints": False,
            "known_success_substrates_used_as_expected_answers": False,
            "transferability_not_claimed_during_extraction": True,
        },
        "decision_boundary": "Only substantial, retrieved full text with deterministically grounded quotations is included.",
        "records": records,
    }
    registry["registry_sha256"] = _digest(registry)
    return registry


def merge_registries(existing: dict[str, Any], web: dict[str, Any]) -> dict[str, Any]:
    by_candidate: dict[str, dict[str, Any]] = {}
    for raw_record in [*existing.get("records", []), *web.get("records", [])]:
        record = _qualify_record_evidence(raw_record)
        candidate_id = str(record["candidate_id"])
        if candidate_id in by_candidate:
            raise ValueError(f"duplicate candidate across supplement registries: {candidate_id}")
        by_candidate[candidate_id] = record
    records = sorted(by_candidate.values(), key=lambda row: str(row["candidate_id"]))
    evidence_ids = [
        str(item.get("evidence_id"))
        for record in records
        for item in record.get("evidence_items", [])
    ]
    if len(evidence_ids) != len(set(evidence_ids)):
        raise ValueError("combined supplement registry contains duplicate evidence IDs")
    merged: dict[str, Any] = {
        "registry_version": "tier-supplement-v2-combined-fulltext",
        "component_registry_sha256": [existing.get("registry_sha256"), web.get("registry_sha256")],
        "record_count": len(records),
        "evidence_item_count": sum(len(row.get("evidence_items", [])) for row in records),
        "contradiction_count": sum(len(row.get("contradictions", [])) for row in records),
        "evidence_ids_unique": True,
        "tier_counts": dict(sorted(Counter(row.get("primary_tier") for row in records).items())),
        "answer_isolation": web.get("answer_isolation", {}),
        "records": records,
    }
    merged["registry_sha256"] = _digest(merged)
    return merged


def build_unresolved(access_manifest: dict[str, Any]) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for row in access_manifest["records"]:
        if row["classification"] == "full_text":
            continue
        records.append({
            "candidate_id": row["candidate_id"], "tier": row["tier"],
            "title": row.get("title"), "doi": row.get("doi"),
            "classification": row["classification"], "reason": row["reason"],
            "attempted_urls": row.get("attempted_urls", []),
        })
    records.sort(key=lambda row: (row["classification"], row["tier"], row["title"] or ""))
    return {
        "record_count": len(records),
        "classification_counts": dict(sorted(Counter(row["classification"] for row in records).items())),
        "tier_counts": dict(sorted(Counter(row["tier"] for row in records).items())),
        "records": records,
    }


def write_unresolved_files(payload: dict[str, Any], root: Path) -> None:
    _atomic_json(root / "unresolved_fulltext_bibliography.json", payload)
    with (root / "unresolved_fulltext_bibliography.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["candidate_id", "tier", "classification", "title", "doi", "reason", "attempted_urls"])
        for row in payload["records"]:
            writer.writerow([
                row["candidate_id"], row["tier"], row["classification"], row["title"], row["doi"], row["reason"],
                " | ".join(str(item.get("url", "")) for item in row["attempted_urls"]),
            ])
    labels = {
        "abstract_only": "仅能取得摘要",
        "paywall": "付费墙",
        "access_failed": "访问失败",
        "invalid_content": "内容不足或无效",
    }
    lines = ["# 未取得可验证全文的文献清单", "", f"共 {payload['record_count']} 篇。", ""]
    for classification in labels:
        rows = [row for row in payload["records"] if row["classification"] == classification]
        lines.extend([f"## {labels[classification]}（{len(rows)} 篇）", ""])
        for row in rows:
            doi = row.get("doi") or "DOI 未知"
            lines.append(f"- [{row['tier']}] {row.get('title') or '题目未知'}；DOI: {doi}；原因: {row['reason']}")
        lines.append("")
    (root / "unresolved_fulltext_bibliography.md").write_text("\n".join(lines), encoding="utf-8")




def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("runs/tier_supplement_v1"))
    args = parser.parse_args()
    web = build_web_registry(args.root / "web_extractions")
    _atomic_json(args.root / "web_evidence_registry.json", web)
    existing = json.loads((args.root / "supplement_evidence_registry.json").read_text(encoding="utf-8"))
    combined = merge_registries(existing, web)
    _atomic_json(args.root / "supplement_evidence_registry_v2.json", combined)
    access = json.loads((args.root / "web_research" / "fulltext_access_manifest.json").read_text(encoding="utf-8"))
    unresolved = build_unresolved(access)
    write_unresolved_files(unresolved, args.root / "web_research")
    print(json.dumps({
        "web_registry": {key: web[key] for key in ("record_count", "evidence_item_count", "tier_counts", "registry_sha256")},
        "combined_registry": {key: combined[key] for key in ("record_count", "evidence_item_count", "tier_counts", "registry_sha256")},
        "unresolved": {key: unresolved[key] for key in ("record_count", "classification_counts", "tier_counts")},
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

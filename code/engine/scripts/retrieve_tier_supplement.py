"""Retrieve and deduplicate OpenAlex metadata for Tier 2-4 supplementation."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import time
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

import yaml


def normalize_doi(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", value.strip(), flags=re.I)
    doi = re.sub(r"^doi:\s*", "", doi, flags=re.I).rstrip(".").casefold()
    return doi or None


def normalize_title(value: object) -> str:
    text = value if isinstance(value, str) else ""
    return " ".join(re.findall(r"[a-z0-9]+", text.casefold()))


def existing_identities(paper_index: Path) -> tuple[set[str], set[str]]:
    with paper_index.open(encoding="utf-8", newline="") as handle:
        rows = tuple(csv.DictReader(handle))
    return (
        {doi for row in rows if (doi := normalize_doi(row.get("doi")))},
        {title for row in rows if (title := normalize_title(row.get("title")))},
    )


def openalex_url(query: str, per_page: int) -> str:
    params = urllib.parse.urlencode(
        {
            "search": query,
            "per-page": per_page,
            "select": (
                "id,doi,title,publication_year,primary_location,authorships,"
                "cited_by_count,open_access,type"
            ),
        }
    )
    return f"https://api.openalex.org/works?{params}"


def retrieve(query: str, per_page: int) -> dict[str, object]:
    request = urllib.request.Request(
        openalex_url(query, per_page),
        headers={"User-Agent": "reaction-principle-tier-supplement/1.0"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def source_fields(location: object) -> tuple[str | None, str | None, str | None]:
    if not isinstance(location, dict):
        return None, None, None
    source = location.get("source")
    journal = source.get("display_name") if isinstance(source, dict) else None
    return journal, location.get("landing_page_url"), location.get("pdf_url")


def author_names(authorships: object) -> list[str]:
    if not isinstance(authorships, list):
        return []
    return [
        name
        for item in authorships
        if isinstance(item, dict)
        for author in (item.get("author"),)
        if isinstance(author, dict)
        for name in (author.get("display_name"),)
        if isinstance(name, str) and name.strip()
    ]


def candidate_row(tier: str, query_id: str, query: str, work: dict[str, object]) -> dict[str, object]:
    journal, landing_url, pdf_url = source_fields(work.get("primary_location"))
    access = work.get("open_access")
    return {
        "candidate_id": "TS-" + hashlib.sha256(
            str(work.get("id", "")).encode("utf-8")
        ).hexdigest()[:16],
        "proposed_tier": tier,
        "query_id": query_id,
        "query": query,
        "openalex_id": work.get("id"),
        "doi": normalize_doi(work.get("doi")),
        "title": work.get("title"),
        "normalized_title": normalize_title(work.get("title")),
        "year": work.get("publication_year"),
        "journal": journal,
        "authors": author_names(work.get("authorships")),
        "cited_by_count": work.get("cited_by_count", 0),
        "work_type": work.get("type"),
        "landing_url": landing_url,
        "pdf_url": pdf_url,
        "is_open_access": access.get("is_oa") if isinstance(access, dict) else None,
        "screening_status": "pending",
        "evidence_roles": [],
        "transfer_target": None,
        "transfer_strength": "unknown",
        "limitations": [],
    }


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config/tier_supplement_v1.yaml"))
    parser.add_argument("--paper-index", type=Path, default=Path("derived/synthesis/paper_index.csv"))
    parser.add_argument("--output", type=Path, default=Path("runs/tier_supplement_v1"))
    parser.add_argument("--delay", type=float, default=0.15)
    args = parser.parse_args()

    config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    existing_dois, existing_titles = existing_identities(args.paper_index)
    per_page = int(config["per_query_limit"])
    all_rows: list[dict[str, object]] = []
    queries: list[dict[str, object]] = []
    raw_root = args.output / "raw"
    for tier, tier_config in config["tiers"].items():
        for position, query in enumerate(tier_config["queries"], start=1):
            query_id = f"{tier.upper()}-Q{position:02d}"
            payload = retrieve(query, per_page)
            atomic_json(raw_root / f"{query_id}.json", payload)
            rows = [
                candidate_row(tier, query_id, query, work)
                for work in payload.get("results", [])
                if isinstance(work, dict) and normalize_title(work.get("title"))
            ]
            all_rows.extend(rows)
            queries.append(
                {
                    "query_id": query_id,
                    "tier": tier,
                    "query": query,
                    "provider_count": payload.get("meta", {}).get("count"),
                    "returned_count": len(rows),
                }
            )
            time.sleep(args.delay)

    grouped: dict[str, dict[str, object]] = {}
    for row in all_rows:
        identity = f"doi:{row['doi']}" if row["doi"] else f"title:{row['normalized_title']}"
        existing = row["doi"] in existing_dois if row["doi"] else row["normalized_title"] in existing_titles
        if existing:
            continue
        current = grouped.get(identity)
        if current is None:
            row["matched_query_ids"] = [row.pop("query_id")]
            row["matched_queries"] = [row.pop("query")]
            row["proposed_tiers"] = [row.pop("proposed_tier")]
            grouped[identity] = row
            continue
        current["matched_query_ids"] = sorted(
            set(current["matched_query_ids"]) | {row["query_id"]}
        )
        current["matched_queries"] = sorted(
            set(current["matched_queries"]) | {row["query"]}
        )
        current["proposed_tiers"] = sorted(
            set(current["proposed_tiers"]) | {row["proposed_tier"]}
        )

    candidates = sorted(
        grouped.values(),
        key=lambda row: (
            tuple(row["proposed_tiers"]),
            -int(row["cited_by_count"] or 0),
            str(row["title"]),
        ),
    )
    atomic_json(args.output / "candidates.json", {"candidates": candidates})
    atomic_json(args.output / "queries.json", {"queries": queries})
    atomic_json(
        args.output / "manifest.json",
        {
            "version": config["version"],
            "study_id": config["study_id"],
            "retrieval_date": config["retrieval_date"],
            "provider": config["provider"],
            "config_digest": hashlib.sha256(args.config.read_bytes()).hexdigest(),
            "existing_paper_count": sum(config["active_baseline"].values()),
            "existing_doi_count": len(existing_dois),
            "query_count": len(queries),
            "raw_result_count": len(all_rows),
            "deduplicated_new_candidate_count": len(candidates),
            "candidate_tier_memberships": dict(
                Counter(tier for row in candidates for tier in row["proposed_tiers"])
            ),
            "rules": config["rules"],
        },
    )


if __name__ == "__main__":
    main()

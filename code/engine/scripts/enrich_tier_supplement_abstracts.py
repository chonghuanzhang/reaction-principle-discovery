"""Prefilter supplement candidates and retrieve OpenAlex abstracts in batches."""

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path


CHEMISTRY_CONTEXT = (
    "reaction", "reactions", "synthesis", "catal", "mechanis", "kinetic",
    "reactiv", "selectiv", "nucleoph", "electroph", "fluoro", "palladium",
    "nickel", "rhodium", "copper", "organic", "alkene", "carbonyl",
)

TIER_PATTERNS = {
    "tier_2": (
        "defluorin", "hydrodefluorin", "monofluoroalkene", "difluoroalkene",
        "polyfluoroalkene", "fluoroalkene", "fluoride elimination",
        "carbon fluorine activation", "difluoro enone", "difluorovinyl",
        "fluoro michael", "fluorinated alkene",
    ),
    "tier_3": (
        "nucleophil", "electrophil", "ion pair", "ion pairing", "ambident",
        "hard soft acid base", "hsab", "fukui", "michael acceptor",
        "basicity", "bronsted", "reactivity scale", "pka",
    ),
    "tier_4": (
        "poison", "inhibit", "deactivat", "decompos", "instabil",
        "overdefluorin", "protodefluorin", "resting state", "side reaction",
        "competing pathway", "oxidation", "selectivity failure",
    ),
}


def normalized_text(value: object) -> str:
    text = value if isinstance(value, str) else ""
    return " ".join(re.findall(r"[a-z0-9]+", text.casefold()))


def tier_query_count(candidate: dict[str, object], tier: str) -> int:
    prefix = tier.upper() + "-"
    return sum(
        isinstance(query_id, str) and query_id.startswith(prefix)
        for query_id in candidate.get("matched_query_ids", [])
    )


def prefilter_reasons(candidate: dict[str, object], tier: str) -> tuple[str, ...]:
    title = normalized_text(candidate.get("title"))
    pattern_hits = tuple(pattern for pattern in TIER_PATTERNS[tier] if pattern in title)
    query_count = tier_query_count(candidate, tier)
    chemistry_hit = any(term in title for term in CHEMISTRY_CONTEXT)
    reasons: list[str] = []
    if pattern_hits:
        reasons.append("title_pattern:" + "|".join(pattern_hits))
    if query_count >= 2 and chemistry_hit:
        reasons.append(f"independent_query_hits:{query_count}")
    return tuple(reasons)


def selected_tiers(candidate: dict[str, object]) -> dict[str, tuple[str, ...]]:
    return {
        tier: reasons
        for tier in candidate.get("proposed_tiers", [])
        if isinstance(tier, str)
        for reasons in (prefilter_reasons(candidate, tier),)
        if reasons
    }


def reconstruct_abstract(index: object) -> str | None:
    if not isinstance(index, dict) or not index:
        return None
    positioned = sorted(
        (position, word)
        for word, positions in index.items()
        if isinstance(word, str) and isinstance(positions, list)
        for position in positions
        if isinstance(position, int) and position >= 0
    )
    return " ".join(word for _, word in positioned) or None


def batch_url(openalex_ids: list[str]) -> str:
    short_ids = [value.rsplit("/", 1)[-1] for value in openalex_ids]
    params = urllib.parse.urlencode(
        {
            "filter": "openalex_id:" + "|".join(short_ids),
            "per-page": 100,
            "select": "id,abstract_inverted_index",
        },
        safe="|:",
    )
    return "https://api.openalex.org/works?" + params


def retrieve_batch(openalex_ids: list[str]) -> dict[str, object]:
    request = urllib.request.Request(
        batch_url(openalex_ids),
        headers={"User-Agent": "reaction-principle-tier-supplement/1.0"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


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
    parser.add_argument("--input", type=Path, default=Path("runs/tier_supplement_v1/candidates.json"))
    parser.add_argument("--output", type=Path, default=Path("runs/tier_supplement_v1"))
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--delay", type=float, default=0.15)
    args = parser.parse_args()

    candidates = json.loads(args.input.read_text(encoding="utf-8"))["candidates"]
    selected: list[dict[str, object]] = []
    for candidate in candidates:
        tier_reasons = selected_tiers(candidate)
        if not tier_reasons:
            continue
        selected.append(
            {
                **candidate,
                "prefilter_tiers": sorted(tier_reasons),
                "prefilter_reasons": {
                    tier: list(reasons) for tier, reasons in sorted(tier_reasons.items())
                },
            }
        )

    abstracts: dict[str, str | None] = {}
    raw_root = args.output / "abstract_batches"
    for offset in range(0, len(selected), args.batch_size):
        batch = selected[offset : offset + args.batch_size]
        payload = retrieve_batch([str(item["openalex_id"]) for item in batch])
        batch_number = offset // args.batch_size + 1
        atomic_json(raw_root / f"batch-{batch_number:03d}.json", payload)
        for work in payload.get("results", []):
            if isinstance(work, dict) and isinstance(work.get("id"), str):
                abstracts[work["id"]] = reconstruct_abstract(
                    work.get("abstract_inverted_index")
                )
        time.sleep(args.delay)

    enriched = [
        {
            **candidate,
            "abstract": abstracts.get(str(candidate["openalex_id"])),
            "abstract_available": bool(abstracts.get(str(candidate["openalex_id"]))),
        }
        for candidate in selected
    ]
    atomic_json(args.output / "prefiltered_candidates.json", {"candidates": enriched})
    atomic_json(
        args.output / "prefilter_manifest.json",
        {
            "input_candidate_count": len(candidates),
            "prefiltered_candidate_count": len(enriched),
            "prefilter_tier_memberships": dict(
                Counter(tier for row in enriched for tier in row["prefilter_tiers"])
            ),
            "abstract_available_count": sum(row["abstract_available"] for row in enriched),
            "abstract_missing_count": sum(not row["abstract_available"] for row in enriched),
            "batch_count": (len(enriched) + args.batch_size - 1) // args.batch_size,
            "batch_size": args.batch_size,
            "decision_boundary": (
                "Title prefilter and abstract retrieval support screening only; "
                "they do not establish decision-grade evidence."
            ),
        },
    )


if __name__ == "__main__":
    main()

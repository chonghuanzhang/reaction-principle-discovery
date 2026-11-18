#!/usr/bin/env python3
"""Validate and export the current C-ID recommendation-to-experiment ledger."""

from collections import Counter
from pathlib import Path
import argparse
import json

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "candidates/experiment_mapping/mapping_108.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    records = json.loads(SOURCE.read_text(encoding="utf-8"))
    candidate_ids = {
        row["display_id"]
        for row in json.loads((ROOT / "candidates/data/candidates_100.json").read_text(encoding="utf-8"))
    }
    hypothesis_ids = {
        row["hypothesis_id"]
        for row in json.loads((ROOT / "candidates/data/hypotheses_103.json").read_text(encoding="utf-8"))
    }
    assert len(records) == 108
    assert Counter(row["primary_relationship_category"] for row in records) == {
        "Exact identity": 26,
        "Same scaffold, substituent or positional variation": 37,
        "Same donor family, different scaffold": 41,
        "No reasonable counterpart": 4,
    }
    for record in records:
        for link in record["candidate_links"]:
            assert link["candidate_display_id"] in candidate_ids
            assert set(link["route_compatible_hypothesis_ids"]) <= hypothesis_ids
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"experimental_pairs": 108, "status": "PASS"}, indent=2))


if __name__ == "__main__":
    main()

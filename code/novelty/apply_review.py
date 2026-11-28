#!/usr/bin/env python3
"""Validate and export the current bounded NP/NR record package."""

from collections import Counter
from pathlib import Path
import argparse
import json
import os


CODE = Path(__file__).resolve().parents[1]
ROOT = CODE.parent
SOURCE = CODE / "data/novelty/reviewed"
MAPPING_COPY = CODE / "data/mapping/novelty_actual_pairs_112_preserved.json"
FILES = (
    "novelty_candidates_100.json",
    "novelty_hypotheses_103.json",
    "novelty_product_options_103.json",
    "novelty_actual_pairs_112.json",
)
PUBLIC = {
    "novelty_candidates_100.json": ROOT / "candidates/data/candidates_100.json",
    "novelty_hypotheses_103.json": ROOT / "candidates/data/hypotheses_103.json",
    "novelty_product_options_103.json": ROOT / "candidates/product_options/product_options_103.json",
}


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def validate():
    records = {name: load(SOURCE / name) for name in FILES}
    candidates = records["novelty_candidates_100.json"]
    hypotheses = records["novelty_hypotheses_103.json"]
    options = records["novelty_product_options_103.json"]
    pairs = records["novelty_actual_pairs_112.json"]

    candidate_ids = {row["display_id"] for row in candidates}
    hypothesis_ids = {row["hypothesis_id"] for row in hypotheses}
    option_ids = {row["option_id"] for row in options}
    assert len(candidates) == len(candidate_ids) == 100
    assert candidate_ids == {f"C{i:03d}" for i in range(1, 101)}
    assert len(hypotheses) == len(hypothesis_ids) == 103
    assert len(options) == len(option_ids) == 103
    assert all(row["display_id"] in candidate_ids for row in hypotheses + options)
    assert all(row["hypothesis_id"] in hypothesis_ids for row in options)
    assert {
        option_id
        for row in hypotheses
        for option_id in row["product_option_ids"]
    } == option_ids
    assert all(
        load(SOURCE / name) == load(public_path)
        for name, public_path in PUBLIC.items()
    )

    pair_ids = {row["actual_pair_id"] for row in pairs}
    assert len(pairs) == len(pair_ids) == 112
    assert pair_ids == {f"AP{i:03d}" for i in range(1, 113)}
    assert Counter(row["route"] for row in pairs) == {
        "NH": 45,
        "OH": 44,
        "SH": 21,
        "PH": 2,
    }
    assert (SOURCE / "novelty_actual_pairs_112.json").read_bytes() == MAPPING_COPY.read_bytes()
    return {
        "candidates": 100,
        "hypotheses": 103,
        "product_options": 103,
        "experimental_pairs": 112,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    output_dir = args.output_dir
    if output_dir is None and os.environ.get("REACTION_NOVELTY_OUTPUT"):
        output_dir = Path(os.environ["REACTION_NOVELTY_OUTPUT"])

    counts = validate()
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        for name in FILES:
            (output_dir / name).write_bytes((SOURCE / name).read_bytes())
    print(json.dumps({"status": "PASS", **counts}, indent=2))


if __name__ == "__main__":
    main()

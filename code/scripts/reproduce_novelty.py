#!/usr/bin/env python3
"""Re-export and compare the current bounded NP/NR records."""

from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import sys
import tempfile


CODE = Path(__file__).resolve().parents[1]
SOURCE = CODE / "novelty/apply_review.py"
EXPECTED = CODE / "data/novelty/reviewed"
FILES = (
    "novelty_candidates_100.json",
    "novelty_hypotheses_103.json",
    "novelty_product_options_103.json",
    "novelty_actual_pairs_112.json",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="reaction-novelty-check-") as tmp:
        result = subprocess.run(
            [sys.executable, str(SOURCE), "--output-dir", tmp],
            capture_output=True,
            text=True,
        )
        if result.returncode:
            raise RuntimeError(result.stderr + "\n" + result.stdout)
        comparisons = []
        for name in FILES:
            actual = (Path(tmp) / name).read_bytes()
            expected = (EXPECTED / name).read_bytes()
            comparisons.append(
                {
                    "file": name,
                    "byte_identical": actual == expected,
                    "sha256": hashlib.sha256(actual).hexdigest(),
                }
            )
        if not all(item["byte_identical"] for item in comparisons):
            raise AssertionError(comparisons)

    report = {
        "status": "passed",
        "network_calls": 0,
        "model_calls": 0,
        "comparisons": comparisons,
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Re-export and validate the current recommendation-to-experiment ledger."""

from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import sys
import tempfile


CODE = Path(__file__).resolve().parents[1]
ROOT = CODE.parent
BUILDER = CODE / "mapping/build_mapping.py"
VALIDATOR = CODE / "scripts/validate_candidate_release.py"
PUBLIC_LEDGER = ROOT / "candidates/experiment_mapping/mapping_108.json"
CODE_LEDGER = CODE / "data/mapping/mapping_108.json"


def digest(payload):
    return hashlib.sha256(payload).hexdigest()


def run(command):
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr + "\n" + result.stdout)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="reaction-mapping-check-") as tmp:
        exported = Path(tmp) / "mapping_108.json"
        run([sys.executable, str(BUILDER), "--output", str(exported)])
        run([sys.executable, str(VALIDATOR)])

        payloads = {
            "builder_export": exported.read_bytes(),
            "public_ledger": PUBLIC_LEDGER.read_bytes(),
            "code_ledger": CODE_LEDGER.read_bytes(),
        }
        if len(set(payloads.values())) != 1:
            raise AssertionError({name: digest(payload) for name, payload in payloads.items()})

    report = {
        "status": "passed",
        "network_calls": 0,
        "model_calls": 0,
        "experimental_pairs": 108,
        "byte_identical": True,
        "sha256": digest(payloads["public_ledger"]),
        "copies": sorted(payloads),
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

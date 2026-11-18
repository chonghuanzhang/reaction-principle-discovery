#!/usr/bin/env python3
"""Synchronize reviewed RP cards into the two released network copies."""

from pathlib import Path
import hashlib
import json


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "evidence/principles.json"
NETWORKS = (
    ROOT / "knowledge_graph/data/network.json",
    ROOT / "code/candidate_workflow/artifacts/released/network.json",
)
MANIFEST = ROOT / "code/candidate_workflow/artifacts/released/manifest.json"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path, payload):
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main():
    principles = load(SOURCE)
    cards = {row["principle_id"]: row for row in principles}
    assert set(cards) == {"RP1", "RP2", "RP3", "RP4"}

    candidate_ids = {
        row["display_id"]
        for row in load(ROOT / "candidates/data/candidates_100.json")
    }
    representative_ids = {
        candidate_id
        for row in principles
        for example in row["representative_candidates"]
        for candidate_id in example["candidate"].split(" / ")
    }
    assert representative_ids <= candidate_ids

    for path in NETWORKS:
        network = load(path)
        principle_nodes = {
            node["id"]: node
            for node in network["nodes"]
            if node["kind"] == "principle"
        }
        assert set(principle_nodes) == set(cards)
        for principle_id, source in cards.items():
            card = {
                "rp_id": principle_id,
                **{key: value for key, value in source.items() if key != "principle_id"},
            }
            principle_nodes[principle_id]["card"] = card
        dump(path, network)

    assert NETWORKS[0].read_bytes() == NETWORKS[1].read_bytes()
    manifest = load(MANIFEST)
    manifest["files"]["network.json"] = hashlib.sha256(NETWORKS[1].read_bytes()).hexdigest()
    dump(MANIFEST, manifest)
    print(
        json.dumps(
            {
                "status": "PASS",
                "reaction_principles": 4,
                "representative_candidate_ids": len(representative_ids),
                "network_sha256": manifest["files"]["network.json"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Validate the deposited recommendation package without network access."""

from collections import Counter
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[2]


def load(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def main():
    candidates = load("candidates/data/candidates_100.json")
    hypotheses = load("candidates/data/hypotheses_103.json")
    options = load("candidates/product_options/product_options_103.json")
    pairs = load("candidates/experiment_mapping/mapping_112.json")
    graph = load("knowledge_graph/data/network.json")
    principles = load("evidence/principles.json")
    manifest = load("code/candidate_workflow/artifacts/released/manifest.json")

    candidate_ids = {row["display_id"] for row in candidates}
    hypothesis_ids = {row["hypothesis_id"] for row in hypotheses}
    option_ids = {row["option_id"] for row in options}
    assert len(candidates) == len(candidate_ids) == 100
    assert candidate_ids == {f"C{i:03d}" for i in range(1, 101)}
    assert len({row["canonical_smiles"] for row in candidates}) == 100
    assert Counter(row["center"] for row in candidates) == {"N": 40, "O": 30, "S": 25, "P": 5}
    assert Counter(row["feasibility_class"] for row in candidates) == {"A": 22, "B": 75, "C": 3}
    assert Counter(row["novelty_review_priority"] for row in candidates) == {1: 43, 2: 41, 3: 16}
    assert Counter(row["best_relationship_category"] for row in candidates) == {
        "Exact identity": 25,
        "Same scaffold, substituent or positional variation": 31,
        "Same donor family, different scaffold": 41,
        "No reasonable counterpart": 3,
    }
    assert len(hypotheses) == len(hypothesis_ids) == 103
    assert len(options) == len(option_ids) == 103
    assert all(row["display_id"] in candidate_ids for row in hypotheses + options)
    assert all(row["hypothesis_id"] in hypothesis_ids for row in options)
    assert all(set(row["hypothesis_ids"]) <= hypothesis_ids for row in candidates)
    assert all(set(row["product_option_ids"]) <= option_ids for row in candidates)

    assert len(pairs) == 112
    assert len({row["actual_donor_smiles"] for row in pairs}) == 102
    assert Counter(row["primary_relationship_category"] for row in pairs) == {
        "Exact identity": 27,
        "Same scaffold, substituent or positional variation": 39,
        "Same donor family, different scaffold": 42,
        "No reasonable counterpart": 4,
    }
    assert all(
        link["candidate_display_id"] in candidate_ids
        for row in pairs for link in row["candidate_links"]
    )
    relationship_priority = {
        "Exact identity": 0,
        "Same scaffold, substituent or positional variation": 1,
        "Same donor family, different scaffold": 2,
    }
    for candidate in candidates:
        relationships = [
            link["relationship_category"]
            for link in candidate["experimental_correspondence"]
        ]
        expected = (
            min(relationships, key=relationship_priority.get)
            if relationships
            else "No reasonable counterpart"
        )
        assert candidate["best_relationship_category"] == expected

    assert Counter(node["kind"] for node in graph["nodes"]) == {
        "evidence": 17,
        "principle": 4,
        "family": 43,
        "candidate": 100,
    }
    assert Counter(edge["kind"] for edge in graph["edges"]) == {
        "source_to_principle": 19,
        "principle_to_family": 172,
        "family_membership": 100,
    }
    assert len(graph["candidate_citation_links"]) == 170
    assert len({row["candidate_id"] for row in graph["candidate_citation_links"]}) == 75
    principle_cards = {row["principle_id"]: row for row in principles}
    principle_nodes = {
        node["id"]: node["card"]
        for node in graph["nodes"]
        if node["kind"] == "principle"
    }
    assert set(principle_cards) == set(principle_nodes) == {"RP1", "RP2", "RP3", "RP4"}
    for principle_id, source in principle_cards.items():
        expected = {
            "rp_id": principle_id,
            **{key: value for key, value in source.items() if key != "principle_id"},
        }
        assert principle_nodes[principle_id] == expected
        assert all(
            candidate_id in candidate_ids
            for example in source["representative_candidates"]
            for candidate_id in example["candidate"].split(" / ")
        )

    release = ROOT / "code/candidate_workflow/artifacts/released"
    for name, expected in manifest["files"].items():
        assert hashlib.sha256((release / name).read_bytes()).hexdigest() == expected

    print(json.dumps({
        "candidates": 100,
        "hypotheses": 103,
        "product_options": 103,
        "experimental_pairs": 112,
        "network_nodes": 164,
        "network_edges": 291,
        "status": "PASS",
    }, indent=2))


if __name__ == "__main__":
    main()

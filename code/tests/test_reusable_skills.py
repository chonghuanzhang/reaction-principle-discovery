import hashlib
import csv
import json
import subprocess
import sys
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

SKILL_HASHES = {
    "skills/README.md": "e132330f26945ac65a852ea8e7910260a39ad09ed4d10b24e2f21b7904ef16b9",
    "skills/recommended-nucleophiles-to-experimental-reagents/SKILL.md": "7105381d1dedc4435f27a932756ad30f9f30a5570747e18712d9939774fbe1f6",
    "skills/recommended-nucleophiles-to-experimental-reagents/references/selection-policy.md": "0e04a7973d99734eed027f13de0dae636ede2141b2a1f46273a382ad0556af26",
    "skills/recommended-nucleophiles-to-experimental-reagents/scripts/run.py": "716ef4b84e45222d1e772d96e33d9273dfc100b3f21d97a3ba19721237a63b1c",
    "skills/requirements.txt": "868cb2cdf6e4a619f617f8ef9a968e8f5d9092a0eb13b217415157fc23542418",
    "skills/rp-to-recommended-nucleophiles/SKILL.md": "2dfee6014fbd0c839fa6572aff04e10a6ea62a3be5c112f15d88fd792545af57",
    "skills/rp-to-recommended-nucleophiles/references/data-contract.md": "0d30b8a332bcc851df879cabedeffa97fa99dfa08cc7e7edd1781831e1e27298",
    "skills/rp-to-recommended-nucleophiles/scripts/run.py": "acd8eee57c5ebf4ae707f45d647f2ba3b29dd1bf6ec027dab3b01b46747a86ff",
}


def load(relative_path):
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


def run(relative_script):
    result = subprocess.run(
        [sys.executable, str(ROOT / relative_script)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise AssertionError(result.stderr + "\n" + result.stdout)
    return json.loads(result.stdout)


class CurrentReleaseContractTests(unittest.TestCase):
    def test_recommendation_package_counts_and_identifier_closure(self):
        candidates = load("candidates/data/candidates_100.json")
        hypotheses = load("candidates/data/hypotheses_103.json")
        options = load("candidates/product_options/product_options_103.json")
        candidate_ids = {row["display_id"] for row in candidates}
        hypothesis_ids = {row["hypothesis_id"] for row in hypotheses}
        option_ids = {row["option_id"] for row in options}

        self.assertEqual(candidate_ids, {f"C{i:03d}" for i in range(1, 101)})
        self.assertEqual(len(hypothesis_ids), 103)
        self.assertEqual(len(option_ids), 103)
        self.assertEqual(
            Counter(row["center"] for row in candidates),
            {"N": 40, "O": 30, "S": 25, "P": 5},
        )
        self.assertEqual(
            Counter(row["best_relationship_category"] for row in candidates),
            {
                "Exact identity": 25,
                "Same scaffold, substituent or positional variation": 31,
                "Same donor family, different scaffold": 41,
                "No reasonable counterpart": 3,
            },
        )
        self.assertTrue(all(row["display_id"] in candidate_ids for row in hypotheses + options))
        self.assertTrue(all(row["hypothesis_id"] in hypothesis_ids for row in options))
        self.assertEqual(
            {option_id for row in hypotheses for option_id in row["product_option_ids"]},
            option_ids,
        )

    def test_experimental_relationship_contract(self):
        pairs = load("candidates/experiment_mapping/mapping_108.json")
        candidates = load("candidates/data/candidates_100.json")
        candidate_ids = {row["display_id"] for row in candidates}

        self.assertEqual(len(pairs), 108)
        self.assertEqual(len({row["actual_donor_smiles"] for row in pairs}), 102)
        self.assertEqual(
            Counter(row["primary_relationship_category"] for row in pairs),
            {
                "Exact identity": 26,
                "Same scaffold, substituent or positional variation": 37,
                "Same donor family, different scaffold": 41,
                "No reasonable counterpart": 4,
            },
        )
        self.assertTrue(
            all(
                link["candidate_display_id"] in candidate_ids
                for row in pairs
                for link in row["candidate_links"]
            )
        )
        self.assertTrue(
            all(
                set(row["exact_candidate_ids"])
                | set(row["scaffold_or_substituent_candidate_ids"])
                | set(row["donor_family_candidate_ids"])
                <= candidate_ids
                for row in pairs
            )
        )

    def test_release_and_reproduction_entry_points(self):
        self.assertEqual(run("code/scripts/validate_candidate_release.py")["status"], "PASS")
        self.assertEqual(run("code/mapping/build_mapping.py")["status"], "PASS")
        self.assertEqual(run("code/novelty/apply_review.py")["status"], "PASS")
        self.assertEqual(run("code/scripts/reproduce_mapping.py")["status"], "passed")
        self.assertEqual(run("code/scripts/reproduce_novelty.py")["status"], "passed")

    def test_current_package_has_no_legacy_count_files(self):
        self.assertFalse((ROOT / "candidates/data/hypotheses_115.json").exists())
        self.assertFalse((ROOT / "candidates/product_options/product_options_124.json").exists())
        self.assertTrue((ROOT / "candidates/data/hypotheses_103.json").is_file())
        self.assertTrue((ROOT / "candidates/product_options/product_options_103.json").is_file())

    def test_public_provenance_has_no_historical_candidate_identifier_fields(self):
        forbidden = {"anchor_original_candidate_id", "original_candidate_evidence_ids"}
        for path in [
            "knowledge_graph/data/network.json",
            "code/candidate_workflow/artifacts/released/network.json",
            "code/evaluation/chemistry/pse_challenge_matrix.json",
        ]:
            stack = [load(path)]
            keys = set()
            while stack:
                value = stack.pop()
                if isinstance(value, dict):
                    keys.update(value)
                    stack.extend(value.values())
                elif isinstance(value, list):
                    stack.extend(value)
            self.assertTrue(forbidden.isdisjoint(keys), path)

        with (ROOT / "code/data/generation/candidate_citation_links.csv").open(
            encoding="utf-8-sig", newline=""
        ) as handle:
            fields = csv.DictReader(handle).fieldnames
        self.assertNotIn("anchor_original_candidate_id", fields)

        amendment = load("code/evaluation/matched_evidence/E16_protocol_amendment.json")
        self.assertFalse(any(key.startswith("old_") for key in amendment))


class PreservedSkillSnapshotTests(unittest.TestCase):
    def test_skill_files_match_the_frozen_snapshot(self):
        actual = {
            path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
            for path in SKILL_HASHES
        }
        self.assertEqual(actual, SKILL_HASHES)


if __name__ == "__main__":
    unittest.main()

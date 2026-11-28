import hashlib
import csv
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

SKILL_HASHES = {
    "skills/README.md": "e132330f26945ac65a852ea8e7910260a39ad09ed4d10b24e2f21b7904ef16b9",
    "skills/recommended-nucleophiles-to-experimental-reagents/SKILL.md": "6386da9adfdb3ece69f5e892f1ff2b32d3e6295c4392860c999baf1a541a6031",
    "skills/recommended-nucleophiles-to-experimental-reagents/references/selection-policy.md": "99d5bacfed211e16eb37014c9382c71a3de8252b2efbf57e92fa862baa95cbfc",
    "skills/recommended-nucleophiles-to-experimental-reagents/scripts/run.py": "4bdb39626e44a4004ddac6a9ddda5df073679f067e21cd90c44d57cc12d27752",
    "skills/requirements.txt": "868cb2cdf6e4a619f617f8ef9a968e8f5d9092a0eb13b217415157fc23542418",
    "skills/rp-to-recommended-nucleophiles/SKILL.md": "2dfee6014fbd0c839fa6572aff04e10a6ea62a3be5c112f15d88fd792545af57",
    "skills/rp-to-recommended-nucleophiles/references/data-contract.md": "929cbdb75fb0d9ededd0fadcaaf2349f07539d9fc489c13e7bfd3d68686e29a7",
    "skills/rp-to-recommended-nucleophiles/scripts/run.py": "ba8a3a73d688250cd640567b7ee41a67bc3e88f5d20d71f7249b7bb9561df9ef",
}


def load(relative_path):
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


def load_script(relative_path, module_name):
    spec = importlib.util.spec_from_file_location(module_name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def run_skill_cli(relative_script):
    with tempfile.TemporaryDirectory(prefix="reaction-skill-test-") as tmp:
        output = Path(tmp) / "result.json"
        result = subprocess.run(
            [sys.executable, str(ROOT / relative_script), "--output", str(output)],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        if result.returncode:
            raise AssertionError(result.stderr + "\n" + result.stdout)
        report = json.loads(output.read_text(encoding="utf-8"))
        summary = json.loads(result.stdout)
        if summary["counts"] != report["counts"]:
            raise AssertionError((summary, report["counts"]))
        return report


class CurrentReleaseContractTests(unittest.TestCase):
    def test_rp_skill_defaults_resolve_the_current_release(self):
        skill = load_script(
            "skills/rp-to-recommended-nucleophiles/scripts/run.py",
            "rp_to_recommended_nucleophiles",
        )
        expected_paths = {
            "graph": ROOT / "knowledge_graph/data/network.json",
            "candidates": ROOT / "candidates/data/candidates_100.json",
            "hypotheses": ROOT / "candidates/data/hypotheses_103.json",
            "product_options": ROOT
            / "candidates/product_options/product_options_103.json",
        }
        self.assertEqual(
            {
                "graph": skill.DEFAULT_GRAPH,
                "candidates": skill.DEFAULT_CANDIDATES,
                "hypotheses": skill.DEFAULT_HYPOTHESES,
                "product_options": skill.DEFAULT_PRODUCT_OPTIONS,
            },
            expected_paths,
        )
        self.assertTrue(all(path.is_file() for path in expected_paths.values()))

        graph = json.loads(expected_paths["graph"].read_text(encoding="utf-8"))
        self.assertEqual(
            {
                "candidate_families": sum(
                    node["kind"] == "family" for node in graph["nodes"]
                ),
                "recommended_nucleophiles": len(
                    json.loads(expected_paths["candidates"].read_text(encoding="utf-8"))
                ),
                "site_pathway_hypotheses": len(
                    json.loads(expected_paths["hypotheses"].read_text(encoding="utf-8"))
                ),
                "product_options": len(
                    json.loads(
                        expected_paths["product_options"].read_text(encoding="utf-8")
                    )
                ),
            },
            {
                "candidate_families": 43,
                "recommended_nucleophiles": 100,
                "site_pathway_hypotheses": 103,
                "product_options": 103,
            },
        )

    def test_reagent_skill_defaults_resolve_the_current_release(self):
        skill = load_script(
            "skills/recommended-nucleophiles-to-experimental-reagents/scripts/run.py",
            "recommended_nucleophiles_to_experimental_reagents",
        )
        expected_paths = {
            "candidates": ROOT / "candidates/data/candidates_100.json",
            "mapping": ROOT / "candidates/experiment_mapping/mapping_112.json",
            "hypotheses": ROOT / "candidates/data/hypotheses_103.json",
        }
        self.assertEqual(
            {
                "candidates": skill.DEFAULT_CANDIDATES,
                "mapping": skill.DEFAULT_MAPPING,
                "hypotheses": skill.DEFAULT_HYPOTHESES,
            },
            expected_paths,
        )
        self.assertTrue(all(path.is_file() for path in expected_paths.values()))
        self.assertEqual(
            {
                key: len(json.loads(path.read_text(encoding="utf-8")))
                for key, path in expected_paths.items()
            },
            {"candidates": 100, "mapping": 112, "hypotheses": 103},
        )

    @unittest.skipUnless(importlib.util.find_spec("rdkit"), "RDKit is required")
    def test_reagent_skill_default_cli_exports_current_relationship_ledger(self):
        report = run_skill_cli(
            "skills/recommended-nucleophiles-to-experimental-reagents/scripts/run.py"
        )
        self.assertEqual(report["status"], "passed")
        self.assertEqual(
            report["counts"],
            {
                "recommended_nucleophiles": 100,
                "experimental_pairs": 112,
                "distinct_experimental_donors": 102,
                "exact_identity_pairs": 27,
                "scaffold_or_substituent_pairs": 39,
                "donor_family_pairs": 42,
                "unmatched_pairs": 4,
            },
        )
        self.assertEqual(len(report["experiment_ledger"]), 112)
        self.assertEqual(
            Counter(row["relationship_category"] for row in report["experiment_ledger"]),
            {
                "Exact identity": 27,
                "Same scaffold, substituent or positional variation": 39,
                "Same donor family, different scaffold": 42,
                "No reasonable counterpart": 4,
            },
        )

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
        pairs = load("candidates/experiment_mapping/mapping_112.json")
        candidates = load("candidates/data/candidates_100.json")
        candidate_ids = {row["display_id"] for row in candidates}

        self.assertEqual(len(pairs), 112)
        self.assertEqual(len({row["actual_donor_smiles"] for row in pairs}), 102)
        self.assertEqual(
            Counter(row["primary_relationship_category"] for row in pairs),
            {
                "Exact identity": 27,
                "Same scaffold, substituent or positional variation": 39,
                "Same donor family, different scaffold": 42,
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


class PreservedSkillSnapshotTests(unittest.TestCase):
    def test_skill_files_match_the_reviewed_release_snapshot(self):
        actual = {
            path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
            for path in SKILL_HASHES
        }
        self.assertEqual(actual, SKILL_HASHES)


if __name__ == "__main__":
    unittest.main()

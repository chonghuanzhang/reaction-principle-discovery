import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def run_skill(relative_script, *args, expect_success=True):
    with tempfile.TemporaryDirectory(prefix="reaction-skill-test-") as tmp:
        output = Path(tmp) / "result.json"
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / relative_script),
                *map(str, args),
                "--output",
                str(output),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        if expect_success:
            assert result.returncode == 0, result.stderr + result.stdout
            report = json.loads(output.read_text(encoding="utf-8"))
            summary = json.loads(result.stdout)
            assert summary == {
                "status": "passed",
                "output": str(output.resolve()),
                "counts": report["counts"],
            }
            return report
        assert result.returncode != 0, result.stderr + result.stdout
        return result


class ReusableSkillTests(unittest.TestCase):
    def test_rp_to_recommended_nucleophiles_exports_complete_traceability(self):
        report = run_skill("skills/rp-to-recommended-nucleophiles/scripts/run.py")
        self.assertEqual(report["status"], "passed")
        self.assertEqual(
            report["counts"],
            {
                "evidence_nodes": 17,
                "reaction_principles": 4,
                "candidate_families": 12,
                "recommended_nucleophiles": 100,
                "site_pathway_hypotheses": 115,
                "product_options": 124,
            },
        )
        self.assertEqual(len(report["candidates"]), 100)
        self.assertTrue(all(row["family_id"] for row in report["candidates"]))
        self.assertTrue(all(row["principle_ids"] for row in report["candidates"]))
        self.assertTrue(all(row["evidence_node_ids"] for row in report["candidates"]))

    def test_rp_skill_accepts_an_explicit_reusable_input_bundle(self):
        report = run_skill(
            "skills/rp-to-recommended-nucleophiles/scripts/run.py",
            "--graph",
            ROOT / "knowledge_graph/data/network.json",
            "--candidates",
            ROOT / "candidates/data/candidates_100.json",
            "--hypotheses",
            ROOT / "candidates/data/hypotheses_115.json",
            "--product-options",
            ROOT / "candidates/product_options/product_options_124.json",
        )
        self.assertEqual(report["counts"]["recommended_nucleophiles"], 100)
        self.assertEqual(
            set(report["inputs"]),
            {"graph", "candidates", "hypotheses", "product_options"},
        )
        self.assertTrue(all(item["sha256"] for item in report["inputs"].values()))

    def test_rp_skill_rejects_an_invalid_candidate_smiles(self):
        candidates = json.loads(
            (ROOT / "candidates/data/candidates_100.json").read_text(encoding="utf-8")
        )
        candidates[0]["canonical_smiles"] = "NOT_A_SMILES"
        with tempfile.TemporaryDirectory(prefix="reaction-skill-invalid-") as tmp:
            invalid = Path(tmp) / "candidates.json"
            invalid.write_text(json.dumps(candidates), encoding="utf-8")
            result = run_skill(
                "skills/rp-to-recommended-nucleophiles/scripts/run.py",
                "--graph",
                ROOT / "knowledge_graph/data/network.json",
                "--candidates",
                invalid,
                "--hypotheses",
                ROOT / "candidates/data/hypotheses_115.json",
                expect_success=False,
            )
        self.assertIn("invalid canonical SMILES", result.stderr)

    def test_rp_skill_rejects_an_out_of_range_reactive_atom_index(self):
        hypotheses = json.loads(
            (ROOT / "candidates/data/hypotheses_115.json").read_text(encoding="utf-8")
        )
        hypotheses[0]["reactive_atom_indices"] = [999]
        with tempfile.TemporaryDirectory(prefix="reaction-skill-invalid-") as tmp:
            invalid = Path(tmp) / "hypotheses.json"
            invalid.write_text(json.dumps(hypotheses), encoding="utf-8")
            result = run_skill(
                "skills/rp-to-recommended-nucleophiles/scripts/run.py",
                "--graph",
                ROOT / "knowledge_graph/data/network.json",
                "--candidates",
                ROOT / "candidates/data/candidates_100.json",
                "--hypotheses",
                invalid,
                expect_success=False,
            )
        self.assertIn("reactive atom index", result.stderr)

    def test_rp_skill_rejects_an_unresolved_evidence_identifier(self):
        graph = json.loads(
            (ROOT / "knowledge_graph/data/network.json").read_text(encoding="utf-8")
        )
        source_edge = next(
            edge for edge in graph["edges"] if edge["kind"] == "source_to_principle"
        )
        source_edge["evidence_ids"] = ["EV-DOES-NOT-EXIST"]
        with tempfile.TemporaryDirectory(prefix="reaction-skill-invalid-") as tmp:
            invalid = Path(tmp) / "network.json"
            invalid.write_text(json.dumps(graph), encoding="utf-8")
            result = run_skill(
                "skills/rp-to-recommended-nucleophiles/scripts/run.py",
                "--graph",
                invalid,
                "--candidates",
                ROOT / "candidates/data/candidates_100.json",
                "--hypotheses",
                ROOT / "candidates/data/hypotheses_115.json",
                expect_success=False,
            )
        self.assertIn("unresolved evidence identifier", result.stderr)

    def test_rp_skill_rejects_an_incomplete_evidence_record(self):
        graph = json.loads(
            (ROOT / "knowledge_graph/data/network.json").read_text(encoding="utf-8")
        )
        evidence_node = next(
            node for node in graph["nodes"] if node["kind"] == "evidence"
        )
        evidence_node["records"][0].pop("display_claim", None)
        with tempfile.TemporaryDirectory(prefix="reaction-skill-invalid-") as tmp:
            invalid = Path(tmp) / "network.json"
            invalid.write_text(json.dumps(graph), encoding="utf-8")
            result = run_skill(
                "skills/rp-to-recommended-nucleophiles/scripts/run.py",
                "--graph",
                invalid,
                "--candidates",
                ROOT / "candidates/data/candidates_100.json",
                "--hypotheses",
                ROOT / "candidates/data/hypotheses_115.json",
                expect_success=False,
            )
        self.assertIn("incomplete evidence record", result.stderr)

    def test_rp_skill_rejects_a_missing_product_option_record(self):
        product_options = json.loads(
            (ROOT / "candidates/product_options/product_options_124.json").read_text(
                encoding="utf-8"
            )
        )
        product_options.pop(0)
        with tempfile.TemporaryDirectory(prefix="reaction-skill-invalid-") as tmp:
            invalid = Path(tmp) / "product_options.json"
            invalid.write_text(json.dumps(product_options), encoding="utf-8")
            result = run_skill(
                "skills/rp-to-recommended-nucleophiles/scripts/run.py",
                "--graph",
                ROOT / "knowledge_graph/data/network.json",
                "--candidates",
                ROOT / "candidates/data/candidates_100.json",
                "--hypotheses",
                ROOT / "candidates/data/hypotheses_115.json",
                "--product-options",
                invalid,
                expect_success=False,
            )
        self.assertIn("product-option record closure", result.stderr)

    def test_rp_skill_rejects_a_product_option_linked_to_the_wrong_hypothesis(self):
        product_options = json.loads(
            (ROOT / "candidates/product_options/product_options_124.json").read_text(
                encoding="utf-8"
            )
        )
        product_options[0]["hypothesis_id"] = product_options[1]["hypothesis_id"]
        with tempfile.TemporaryDirectory(prefix="reaction-skill-invalid-") as tmp:
            invalid = Path(tmp) / "product_options.json"
            invalid.write_text(json.dumps(product_options), encoding="utf-8")
            result = run_skill(
                "skills/rp-to-recommended-nucleophiles/scripts/run.py",
                "--graph",
                ROOT / "knowledge_graph/data/network.json",
                "--candidates",
                ROOT / "candidates/data/candidates_100.json",
                "--hypotheses",
                ROOT / "candidates/data/hypotheses_115.json",
                "--product-options",
                invalid,
                expect_success=False,
            )
        self.assertIn("product option", result.stderr)

    def test_rp_skill_requires_a_product_option_np_nr_assessment(self):
        product_options = json.loads(
            (ROOT / "candidates/product_options/product_options_124.json").read_text(
                encoding="utf-8"
            )
        )
        product_options[0].pop("NP_label", None)
        with tempfile.TemporaryDirectory(prefix="reaction-skill-invalid-") as tmp:
            invalid = Path(tmp) / "product_options.json"
            invalid.write_text(json.dumps(product_options), encoding="utf-8")
            result = run_skill(
                "skills/rp-to-recommended-nucleophiles/scripts/run.py",
                "--graph",
                ROOT / "knowledge_graph/data/network.json",
                "--candidates",
                ROOT / "candidates/data/candidates_100.json",
                "--hypotheses",
                ROOT / "candidates/data/hypotheses_115.json",
                "--product-options",
                invalid,
                expect_success=False,
            )
        self.assertIn("NP/NR assessment", result.stderr)

    def test_rp_skill_rejects_an_incomplete_product_option_closure(self):
        hypotheses = json.loads(
            (ROOT / "candidates/data/hypotheses_115.json").read_text(encoding="utf-8")
        )
        hypotheses[0]["product_option_ids"] = []
        with tempfile.TemporaryDirectory(prefix="reaction-skill-invalid-") as tmp:
            invalid = Path(tmp) / "hypotheses.json"
            invalid.write_text(json.dumps(hypotheses), encoding="utf-8")
            result = run_skill(
                "skills/rp-to-recommended-nucleophiles/scripts/run.py",
                "--graph",
                ROOT / "knowledge_graph/data/network.json",
                "--candidates",
                ROOT / "candidates/data/candidates_100.json",
                "--hypotheses",
                invalid,
                expect_success=False,
            )
        self.assertIn("product-option closure", result.stderr)

    def test_rp_skill_rejects_a_candidate_without_a_graph_membership(self):
        candidates = json.loads(
            (ROOT / "candidates/data/candidates_100.json").read_text(encoding="utf-8")
        )
        candidates[0]["display_id"] = "C999"
        with tempfile.TemporaryDirectory(prefix="reaction-skill-invalid-") as tmp:
            invalid = Path(tmp) / "candidates.json"
            invalid.write_text(json.dumps(candidates), encoding="utf-8")
            result = run_skill(
                "skills/rp-to-recommended-nucleophiles/scripts/run.py",
                "--graph",
                ROOT / "knowledge_graph/data/network.json",
                "--candidates",
                invalid,
                expect_success=False,
            )
        self.assertIn("family membership", result.stderr)

    def test_rp_skill_requires_candidate_centres_to_match_hypotheses(self):
        candidates = json.loads(
            (ROOT / "candidates/data/candidates_100.json").read_text(encoding="utf-8")
        )
        candidates[0]["centers"] = ["O"]
        with tempfile.TemporaryDirectory(prefix="reaction-skill-invalid-") as tmp:
            invalid = Path(tmp) / "candidates.json"
            invalid.write_text(json.dumps(candidates), encoding="utf-8")
            result = run_skill(
                "skills/rp-to-recommended-nucleophiles/scripts/run.py",
                "--graph",
                ROOT / "knowledge_graph/data/network.json",
                "--candidates",
                invalid,
                "--hypotheses",
                ROOT / "candidates/data/hypotheses_115.json",
                expect_success=False,
            )
        self.assertIn("reacting-centre closure", result.stderr)

    def test_recommended_nucleophiles_to_experiments_exports_decision_ledger(self):
        report = run_skill(
            "skills/recommended-nucleophiles-to-experimental-reagents/scripts/run.py"
        )
        self.assertEqual(report["status"], "passed")
        self.assertEqual(
            report["counts"],
            {
                "recommended_nucleophiles": 100,
                "experimental_pairs": 108,
                "distinct_experimental_donors": 102,
                "exact_matches": 3,
                "structural_or_family_matches": 101,
                "unmatched_inputs": 4,
                "approved_exceptions": 7,
            },
        )
        self.assertEqual(len(report["experiment_ledger"]), 108)
        self.assertTrue(
            all(row["actual_pair_id"].startswith("AP") for row in report["experiment_ledger"])
        )
        self.assertTrue(
            all(row["execution_status"] == "executed" for row in report["experiment_ledger"])
        )
        exception_ids = {
            row["actual_pair_id"]
            for row in report["experiment_ledger"]
            if row["release_gate_status"] == "exception_register"
        }
        self.assertEqual(
            exception_ids,
            {"AP002", "AP022", "AP039", "AP045", "AP049", "AP058", "AP105"},
        )

    def test_reagent_skill_accepts_an_explicit_reusable_input_bundle(self):
        report = run_skill(
            "skills/recommended-nucleophiles-to-experimental-reagents/scripts/run.py",
            "--candidates",
            ROOT / "candidates/data/candidates_100.json",
            "--mapping",
            ROOT / "candidates/experiment_mapping/mapping_108.json",
            "--hypotheses",
            ROOT / "candidates/data/hypotheses_115.json",
        )
        self.assertEqual(report["counts"]["experimental_pairs"], 108)
        self.assertEqual(
            set(report["inputs"]), {"candidates", "mapping", "hypotheses"}
        )
        self.assertTrue(all(item["sha256"] for item in report["inputs"].values()))

    def test_reagent_skill_rejects_an_unknown_candidate_link(self):
        mapping = json.loads(
            (ROOT / "candidates/experiment_mapping/mapping_108.json").read_text(
                encoding="utf-8"
            )
        )
        mapping[0]["candidate_links"][0]["candidate_display_id"] = "C999"
        with tempfile.TemporaryDirectory(prefix="reaction-skill-invalid-") as tmp:
            invalid = Path(tmp) / "mapping.json"
            invalid.write_text(json.dumps(mapping), encoding="utf-8")
            result = run_skill(
                "skills/recommended-nucleophiles-to-experimental-reagents/scripts/run.py",
                "--candidates",
                ROOT / "candidates/data/candidates_100.json",
                "--mapping",
                invalid,
                expect_success=False,
            )
        self.assertIn("unknown candidate", result.stderr)

    def test_reagent_skill_requires_a_reviewed_selection_decision(self):
        mapping = json.loads(
            (ROOT / "candidates/experiment_mapping/mapping_108.json").read_text(
                encoding="utf-8"
            )
        )
        mapping[0].pop("selection_decision", None)
        mapping[0].pop("human_review_status", None)
        with tempfile.TemporaryDirectory(prefix="reaction-skill-invalid-") as tmp:
            invalid = Path(tmp) / "mapping.json"
            invalid.write_text(json.dumps(mapping), encoding="utf-8")
            result = run_skill(
                "skills/recommended-nucleophiles-to-experimental-reagents/scripts/run.py",
                "--candidates",
                ROOT / "candidates/data/candidates_100.json",
                "--mapping",
                invalid,
                expect_success=False,
            )
        self.assertIn("reviewed selection decision", result.stderr)

    def test_reagent_skill_rejects_an_unresolved_identity_status(self):
        mapping = json.loads(
            (ROOT / "candidates/experiment_mapping/mapping_108.json").read_text(
                encoding="utf-8"
            )
        )
        mapping[0]["input_identity_status"] = "unresolved_unreviewed_identity"
        mapping[0]["input_identity_issues"] = ["identity requires resolution"]
        with tempfile.TemporaryDirectory(prefix="reaction-skill-invalid-") as tmp:
            invalid = Path(tmp) / "mapping.json"
            invalid.write_text(json.dumps(mapping), encoding="utf-8")
            result = run_skill(
                "skills/recommended-nucleophiles-to-experimental-reagents/scripts/run.py",
                "--candidates",
                ROOT / "candidates/data/candidates_100.json",
                "--mapping",
                invalid,
                expect_success=False,
            )
        self.assertIn("unresolved identity status", result.stderr)

    def test_reagent_skill_rejects_an_empty_route_compatible_hypothesis_list(self):
        mapping = json.loads(
            (ROOT / "candidates/experiment_mapping/mapping_108.json").read_text(
                encoding="utf-8"
            )
        )
        mapping[0]["candidate_links"][0][
            "route_compatible_original_hypothesis_ids"
        ] = []
        with tempfile.TemporaryDirectory(prefix="reaction-skill-invalid-") as tmp:
            invalid = Path(tmp) / "mapping.json"
            invalid.write_text(json.dumps(mapping), encoding="utf-8")
            result = run_skill(
                "skills/recommended-nucleophiles-to-experimental-reagents/scripts/run.py",
                "--candidates",
                ROOT / "candidates/data/candidates_100.json",
                "--mapping",
                invalid,
                expect_success=False,
            )
        self.assertIn("route-compatible hypothesis", result.stderr)

    def test_reagent_skill_rejects_a_route_incompatible_hypothesis(self):
        mapping = json.loads(
            (ROOT / "candidates/experiment_mapping/mapping_108.json").read_text(
                encoding="utf-8"
            )
        )
        mapping[0]["candidate_links"][0][
            "route_compatible_original_hypothesis_ids"
        ] = ["CP-15eeea50cbe27556::H01"]
        mapping[0]["candidate_links"][0]["route_center"] = "O"
        with tempfile.TemporaryDirectory(prefix="reaction-skill-invalid-") as tmp:
            invalid = Path(tmp) / "mapping.json"
            invalid.write_text(json.dumps(mapping), encoding="utf-8")
            result = run_skill(
                "skills/recommended-nucleophiles-to-experimental-reagents/scripts/run.py",
                "--candidates",
                ROOT / "candidates/data/candidates_100.json",
                "--mapping",
                invalid,
                "--hypotheses",
                ROOT / "candidates/data/hypotheses_115.json",
                expect_success=False,
            )
        self.assertIn("route center", result.stderr)

    def test_reagent_skill_rejects_a_false_exact_molecular_match(self):
        mapping = json.loads(
            (ROOT / "candidates/experiment_mapping/mapping_108.json").read_text(
                encoding="utf-8"
            )
        )
        exact_pair = next(
            pair
            for pair in mapping
            if pair["primary_mapping_class"] == "Exact Molecular Match"
        )
        exact_pair["actual_donor_smiles"] = "CCO"
        with tempfile.TemporaryDirectory(prefix="reaction-skill-invalid-") as tmp:
            invalid = Path(tmp) / "mapping.json"
            invalid.write_text(json.dumps(mapping), encoding="utf-8")
            result = run_skill(
                "skills/recommended-nucleophiles-to-experimental-reagents/scripts/run.py",
                "--candidates",
                ROOT / "candidates/data/candidates_100.json",
                "--mapping",
                invalid,
                "--hypotheses",
                ROOT / "candidates/data/hypotheses_115.json",
                expect_success=False,
            )
        self.assertIn("exact molecular match", result.stderr)

    def test_reagent_skill_requires_the_primary_class_to_match_a_link(self):
        mapping = json.loads(
            (ROOT / "candidates/experiment_mapping/mapping_108.json").read_text(
                encoding="utf-8"
            )
        )
        exact_pair = next(
            pair
            for pair in mapping
            if pair["primary_mapping_class"] == "Exact Molecular Match"
        )
        exact_link = next(
            link
            for link in exact_pair["candidate_links"]
            if link["relation"] == "Exact Molecular Match"
        )
        exact_link["relation"] = "Structural Analogue"
        with tempfile.TemporaryDirectory(prefix="reaction-skill-invalid-") as tmp:
            invalid = Path(tmp) / "mapping.json"
            invalid.write_text(json.dumps(mapping), encoding="utf-8")
            result = run_skill(
                "skills/recommended-nucleophiles-to-experimental-reagents/scripts/run.py",
                "--candidates",
                ROOT / "candidates/data/candidates_100.json",
                "--mapping",
                invalid,
                "--hypotheses",
                ROOT / "candidates/data/hypotheses_115.json",
                expect_success=False,
            )
        self.assertIn("primary mapping class", result.stderr)

    def test_reagent_skill_requires_a_route_element_in_a_matched_reagent(self):
        mapping = json.loads(
            (ROOT / "candidates/experiment_mapping/mapping_108.json").read_text(
                encoding="utf-8"
            )
        )
        mapping[0]["actual_donor_smiles"] = "CC#N"
        with tempfile.TemporaryDirectory(prefix="reaction-skill-invalid-") as tmp:
            invalid = Path(tmp) / "mapping.json"
            invalid.write_text(json.dumps(mapping), encoding="utf-8")
            result = run_skill(
                "skills/recommended-nucleophiles-to-experimental-reagents/scripts/run.py",
                "--candidates",
                ROOT / "candidates/data/candidates_100.json",
                "--mapping",
                invalid,
                "--hypotheses",
                ROOT / "candidates/data/hypotheses_115.json",
                expect_success=False,
            )
        self.assertIn("reactive route site", result.stderr)

    def test_reagent_skill_verifies_a_reactive_form_analogue_parent(self):
        mapping = json.loads(
            (ROOT / "candidates/experiment_mapping/mapping_108.json").read_text(
                encoding="utf-8"
            )
        )
        mapping[0]["primary_mapping_class"] = "Reactive-form Analogue"
        mapping[0]["candidate_links"][0]["relation"] = "Reactive-form Analogue"
        with tempfile.TemporaryDirectory(prefix="reaction-skill-invalid-") as tmp:
            invalid = Path(tmp) / "mapping.json"
            invalid.write_text(json.dumps(mapping), encoding="utf-8")
            result = run_skill(
                "skills/recommended-nucleophiles-to-experimental-reagents/scripts/run.py",
                "--candidates",
                ROOT / "candidates/data/candidates_100.json",
                "--mapping",
                invalid,
                "--hypotheses",
                ROOT / "candidates/data/hypotheses_115.json",
                expect_success=False,
            )
        self.assertIn("reactive-form analogue", result.stderr)

    def test_reagent_skill_requires_minimum_feasibility_fields(self):
        mapping = json.loads(
            (ROOT / "candidates/experiment_mapping/mapping_108.json").read_text(
                encoding="utf-8"
            )
        )
        mapping[0]["feasibility_review"].pop("availability", None)
        with tempfile.TemporaryDirectory(prefix="reaction-skill-invalid-") as tmp:
            invalid = Path(tmp) / "mapping.json"
            invalid.write_text(json.dumps(mapping), encoding="utf-8")
            result = run_skill(
                "skills/recommended-nucleophiles-to-experimental-reagents/scripts/run.py",
                "--candidates",
                ROOT / "candidates/data/candidates_100.json",
                "--mapping",
                invalid,
                expect_success=False,
            )
        self.assertIn("feasibility field availability", result.stderr)


if __name__ == "__main__":
    unittest.main()

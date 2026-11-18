"""Verify that Round 5 figure inputs are complete and repository-local."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "code/figures"))

from round5_figure_inputs import load_round5_figure_inputs


class Round5FigureInputTests(unittest.TestCase):
    def test_inputs_load_from_an_isolated_repository_copy(self):
        relative_paths = {
            "candidates": "candidates/data/candidates_100.json",
            "hypotheses": "candidates/data/hypotheses_103.json",
            "products": "candidates/product_options/product_options_103.json",
            "mappings": "candidates/experiment_mapping/mapping_108.json",
            "network": "knowledge_graph/data/network.json",
            "llm_baseline": "experiments/baselines/data/llm_records.json",
            "literature_baseline": "experiments/baselines/data/literature_baseline_records.json",
            "comparison_summary": "experiments/baselines/data/comparison_summary.json",
        }
        with tempfile.TemporaryDirectory() as directory:
            isolated_root = Path(directory)
            for relative_path in relative_paths.values():
                source = ROOT / relative_path
                destination = isolated_root / relative_path
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)

            package = load_round5_figure_inputs(isolated_root)

        self.assertEqual(package.source_paths, relative_paths)
        self.assertEqual(len(package.candidates), 100)
        self.assertEqual(len(package.hypotheses), 103)
        self.assertEqual(len(package.products), 103)
        self.assertEqual(len(package.mappings), 108)
        self.assertEqual(len(package.llm_baseline), 20)
        self.assertEqual(
            len(
                {
                    row["unique_structure_representative"]
                    for row in package.literature_baseline["records"]
                }
            ),
            20,
        )
        self.assertEqual(
            [(row["positive"], row["tested_unique_donors"]) for row in package.comparison_summary["statistics"]],
            [(35, 94), (4, 20), (3, 20)],
        )


if __name__ == "__main__":
    unittest.main()

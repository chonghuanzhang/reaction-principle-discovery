"""Load the repository-local data package used by the Round 5 figures."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Dict, List


SOURCE_PATHS = {
    "candidates": "candidates/data/candidates_100.json",
    "hypotheses": "candidates/data/hypotheses_103.json",
    "products": "candidates/product_options/product_options_103.json",
    "mappings": "candidates/experiment_mapping/mapping_108.json",
    "network": "knowledge_graph/data/network.json",
    "llm_baseline": "experiments/baselines/data/llm_records.json",
    "literature_baseline": "experiments/baselines/data/literature_baseline_records.json",
    "comparison_summary": "experiments/baselines/data/comparison_summary.json",
}


@dataclass(frozen=True)
class Round5FigureInputs:
    source_paths: Dict[str, str]
    candidates: List[Dict[str, Any]]
    hypotheses: List[Dict[str, Any]]
    products: List[Dict[str, Any]]
    mappings: List[Dict[str, Any]]
    network: Dict[str, Any]
    llm_baseline: List[Dict[str, Any]]
    literature_baseline: Dict[str, Any]
    comparison_summary: Dict[str, Any]


def _read_json(root: Path, relative_path: str) -> Any:
    path = root / relative_path
    if not path.is_file():
        raise FileNotFoundError("Missing Round 5 figure input: {}".format(relative_path))
    return json.loads(path.read_text(encoding="utf-8"))


def load_round5_figure_inputs(root: Path) -> Round5FigureInputs:
    """Load and validate every input needed to rebuild the Round 5 figures."""
    root = Path(root).resolve()
    payload = {name: _read_json(root, path) for name, path in SOURCE_PATHS.items()}

    candidates = payload["candidates"]
    hypotheses = payload["hypotheses"]
    products = payload["products"]
    mappings = payload["mappings"]
    candidate_ids = {row["display_id"] for row in candidates}
    hypothesis_ids = {row["hypothesis_id"] for row in hypotheses}

    if candidate_ids != {"C{:03d}".format(index) for index in range(1, 101)}:
        raise ValueError("Candidate identifiers must form the complete C001-C100 set")
    if len(hypotheses) != 103 or len(products) != 103 or len(mappings) != 108:
        raise ValueError("Expected 103 hypotheses, 103 product options and 108 experimental pairs")
    if Counter(row["center"] for row in candidates) != Counter({"N": 40, "O": 30, "S": 25, "P": 5}):
        raise ValueError("Unexpected reacting-centre composition")
    if len({row["family_id"] for row in candidates}) != 43:
        raise ValueError("Expected 43 candidate families")
    if not all(row["display_id"] in candidate_ids for row in hypotheses + products):
        raise ValueError("Hypothesis or product option references an unknown candidate")
    if not all(row["hypothesis_id"] in hypothesis_ids for row in products):
        raise ValueError("Product option references an unknown hypothesis")

    network_candidate_ids = {
        node["id"] for node in payload["network"]["nodes"] if node["kind"] == "candidate"
    }
    if network_candidate_ids != candidate_ids:
        raise ValueError("Knowledge-graph candidate nodes do not match the released set")
    if len(payload["llm_baseline"]) != 20:
        raise ValueError("Expected 20 direct-LLM baseline records")
    literature_records = payload["literature_baseline"]["records"]
    if sum(row["unique_structure_representative"] == row["record_id"] for row in literature_records) != 20:
        raise ValueError("Expected 20 unique literature-selection baseline structures")

    return Round5FigureInputs(
        source_paths=dict(SOURCE_PATHS),
        candidates=candidates,
        hypotheses=hypotheses,
        products=products,
        mappings=mappings,
        network=payload["network"],
        llm_baseline=payload["llm_baseline"],
        literature_baseline=payload["literature_baseline"],
        comparison_summary=payload["comparison_summary"],
    )

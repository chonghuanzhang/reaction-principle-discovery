#!/usr/bin/env python3
"""Validate and export evidence-to-RP-to-candidate traceability."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

try:
    from rdkit import Chem
except ImportError:  # Report a concise release-gate error from build_report.
    Chem = None


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_GRAPH = ROOT / "knowledge_graph/data/network.json"
DEFAULT_CANDIDATES = ROOT / "candidates/data/candidates_100.json"
DEFAULT_HYPOTHESES = ROOT / "candidates/data/hypotheses_103.json"
DEFAULT_PRODUCT_OPTIONS = ROOT / "candidates/product_options/product_options_103.json"
REQUIRED_EVIDENCE_RECORD_FIELDS = (
    "evidence_id",
    "source_id",
    "quotation",
    "display_claim",
    "display_claim_basis",
    "display_attribution",
    "display_locator",
)


def load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ValueError(f"cannot read {path}: {error}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid JSON in {path}: {error}") from error


def require(condition, message):
    if not condition:
        raise ValueError(message)


def input_record(path):
    return {
        "path": str(path.resolve()),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def parse_smiles(smiles, label):
    require(Chem is not None, "RDKit is required; install skills/requirements.txt")
    require(isinstance(smiles, str) and smiles, f"missing SMILES for {label}")
    molecule = Chem.MolFromSmiles(smiles)
    require(molecule is not None, f"invalid canonical SMILES for {label}: {smiles}")
    return molecule


def canonical_smiles(molecule):
    return Chem.MolToSmiles(molecule, isomericSmiles=True)


def build_report(
    graph_path=DEFAULT_GRAPH,
    candidates_path=DEFAULT_CANDIDATES,
    hypotheses_path=DEFAULT_HYPOTHESES,
    product_options_path=DEFAULT_PRODUCT_OPTIONS,
):
    graph_path = Path(graph_path)
    candidates_path = Path(candidates_path)
    hypotheses_path = Path(hypotheses_path)
    product_options_path = Path(product_options_path)
    graph = load_json(graph_path)
    candidates = load_json(candidates_path)
    hypotheses = load_json(hypotheses_path)
    product_options = load_json(product_options_path)

    require(isinstance(graph, dict), "graph input must be a JSON object")
    require(isinstance(graph.get("nodes"), list), "graph.nodes must be a list")
    require(isinstance(graph.get("edges"), list), "graph.edges must be a list")
    require(isinstance(candidates, list), "candidates input must be a JSON list")
    require(isinstance(hypotheses, list), "hypotheses input must be a JSON list")
    require(isinstance(product_options, list), "product options input must be a JSON list")

    node_ids = [node.get("id") for node in graph["nodes"]]
    require(all(node_ids), "every graph node must have an id")
    require(len(node_ids) == len(set(node_ids)), "graph node ids must be unique")

    nodes = {node["id"]: node for node in graph["nodes"]}
    evidence_nodes = {key: value for key, value in nodes.items() if value["kind"] == "evidence"}
    principles = {key: value for key, value in nodes.items() if value["kind"] == "principle"}
    families = {key: value for key, value in nodes.items() if value["kind"] == "family"}

    source_register = graph.get("source_register")
    require(isinstance(source_register, dict), "graph.source_register must be an object")
    evidence_ids_by_node = {}
    for evidence_node_id, evidence_node in evidence_nodes.items():
        records = evidence_node.get("records")
        require(
            isinstance(records, list) and records,
            f"evidence node {evidence_node_id} has no evidence records",
        )
        record_ids = [record.get("evidence_id") for record in records]
        require(
            all(record_ids) and len(record_ids) == len(set(record_ids)),
            f"evidence node {evidence_node_id} has invalid or duplicate evidence identifiers",
        )
        for record in records:
            missing_fields = [
                field
                for field in REQUIRED_EVIDENCE_RECORD_FIELDS
                if not record.get(field)
            ]
            require(
                not missing_fields,
                f"incomplete evidence record {record.get('evidence_id')} in "
                f"{evidence_node_id}: {missing_fields}",
            )
        declared_ids = evidence_node.get("evidence_ids")
        require(
            isinstance(declared_ids, list) and set(declared_ids) == set(record_ids),
            f"evidence record closure does not match node {evidence_node_id}",
        )
        references = evidence_node.get("references")
        require(
            isinstance(references, list) and references,
            f"evidence node {evidence_node_id} has no literature source references",
        )
        unresolved_sources = sorted(set(references) - set(source_register))
        require(
            not unresolved_sources,
            f"unresolved literature source for {evidence_node_id}: {unresolved_sources}",
        )
        admitted_source_ids = {
            source_register[source_id].get("source_id") for source_id in references
        }
        for record in records:
            require(
                record["source_id"] in admitted_source_ids,
                f"evidence record {record['evidence_id']} does not resolve to a "
                f"source registered for {evidence_node_id}",
            )
        evidence_ids_by_node[evidence_node_id] = set(record_ids)

    family_by_candidate = {}
    principles_by_family = {family_id: [] for family_id in families}
    evidence_by_principle = {principle_id: [] for principle_id in principles}

    for edge in graph["edges"]:
        require(edge.get("source") in nodes, f"unknown edge source: {edge.get('source')}")
        require(edge.get("target") in nodes, f"unknown edge target: {edge.get('target')}")
        if edge["kind"] == "family_membership":
            require(edge["source"] in families, f"family membership source is not a family: {edge['source']}")
            require(
                edge["target"] not in family_by_candidate,
                f"candidate has more than one family membership: {edge['target']}",
            )
            family_by_candidate[edge["target"]] = edge["source"]
        elif edge["kind"] == "principle_to_family":
            require(edge["source"] in principles, f"unknown principle: {edge['source']}")
            require(edge["target"] in families, f"unknown family: {edge['target']}")
            principles_by_family[edge["target"]].append(
                {"principle_id": edge["source"], "relation": edge["relation"]}
            )
        elif edge["kind"] == "source_to_principle":
            require(edge["source"] in evidence_nodes, f"unknown evidence node: {edge['source']}")
            require(edge["target"] in principles, f"unknown principle: {edge['target']}")
            edge_evidence_ids = edge.get("evidence_ids")
            require(
                isinstance(edge_evidence_ids, list)
                and edge_evidence_ids
                and len(edge_evidence_ids) == len(set(edge_evidence_ids)),
                f"invalid evidence identifiers on edge {edge.get('id')}",
            )
            unresolved_evidence_ids = sorted(
                set(edge_evidence_ids) - evidence_ids_by_node[edge["source"]]
            )
            require(
                not unresolved_evidence_ids,
                "unresolved evidence identifier on edge "
                f"{edge.get('id')}: {unresolved_evidence_ids}",
            )
            evidence_by_principle[edge["target"]].append(
                {
                    "evidence_node_id": edge["source"],
                    "evidence_ids": edge_evidence_ids,
                }
            )

    for principle_id, principle in principles.items():
        linked_evidence_ids = {
            evidence_id
            for link in evidence_by_principle[principle_id]
            for evidence_id in link["evidence_ids"]
        }
        card = principle.get("card")
        require(isinstance(card, dict), f"principle {principle_id} has no RP card")
        supporting_evidence = card.get("supporting_evidence")
        require(
            isinstance(supporting_evidence, list)
            and set(supporting_evidence) == linked_evidence_ids,
            f"supporting-evidence closure does not match principle {principle_id}",
        )

    candidate_ids = [candidate.get("display_id") for candidate in candidates]
    require(all(candidate_ids), "every candidate must have a display_id")
    require(len(candidate_ids) == len(set(candidate_ids)), "candidate display_ids must be unique")
    require(
        set(candidate_ids) == set(family_by_candidate),
        "every candidate must have exactly one family membership and no graph-only candidate may remain",
    )
    candidate_molecules = {}
    canonical_structures = []
    for candidate in candidates:
        candidate_id = candidate["display_id"]
        stored_smiles = candidate.get("canonical_smiles")
        molecule = parse_smiles(stored_smiles, f"candidate {candidate_id}")
        normalized_smiles = canonical_smiles(molecule)
        require(
            stored_smiles == normalized_smiles,
            f"non-canonical candidate SMILES for {candidate_id}: {stored_smiles}",
        )
        candidate_molecules[candidate_id] = molecule
        canonical_structures.append(normalized_smiles)
    require(
        len(canonical_structures) == len(set(canonical_structures)),
        "canonical candidate structures must be unique",
    )

    candidates_by_id = {candidate["display_id"]: candidate for candidate in candidates}
    hypothesis_ids = [hypothesis.get("hypothesis_id") for hypothesis in hypotheses]
    require(all(hypothesis_ids), "every hypothesis must have a hypothesis_id")
    require(
        len(hypothesis_ids) == len(set(hypothesis_ids)),
        "hypothesis_ids must be unique",
    )
    hypotheses_by_candidate = {candidate_id: [] for candidate_id in candidate_ids}
    all_product_option_ids = []
    hypotheses_by_id = {}
    for hypothesis in hypotheses:
        hypothesis_id = hypothesis["hypothesis_id"]
        candidate_id = hypothesis.get("display_id")
        require(
            candidate_id in candidates_by_id,
            f"hypothesis {hypothesis_id} references unknown candidate {candidate_id}",
        )
        require(
            hypothesis.get("candidate_id") == candidates_by_id[candidate_id].get("candidate_id"),
            f"hypothesis {hypothesis_id} candidate identity does not match {candidate_id}",
        )
        reactive_molecule = parse_smiles(
            hypothesis.get("reactive_atom_input_smiles"),
            f"hypothesis {hypothesis_id}",
        )
        require(
            canonical_smiles(reactive_molecule)
            == canonical_smiles(candidate_molecules[candidate_id]),
            f"hypothesis {hypothesis_id} structure does not match {candidate_id}",
        )
        center = hypothesis.get("center")
        atom_indices = hypothesis.get("reactive_atom_indices")
        require(
            isinstance(atom_indices, list)
            and atom_indices
            and len(atom_indices) == len(set(atom_indices)),
            f"hypothesis {hypothesis_id} has invalid reactive atom indices",
        )
        for atom_index in atom_indices:
            require(
                isinstance(atom_index, int)
                and not isinstance(atom_index, bool)
                and 0 <= atom_index < reactive_molecule.GetNumAtoms(),
                f"reactive atom index is out of range for hypothesis {hypothesis_id}: {atom_index}",
            )
            require(
                reactive_molecule.GetAtomWithIdx(atom_index).GetSymbol() == center,
                f"reactive atom does not match center {center} for hypothesis {hypothesis_id}",
            )
        option_ids = hypothesis.get("product_option_ids")
        require(
            isinstance(option_ids, list) and option_ids,
            f"product-option closure is empty for hypothesis {hypothesis_id}",
        )
        require(
            all(isinstance(option_id, str) and option_id for option_id in option_ids),
            f"product-option closure contains an invalid identifier for {hypothesis_id}",
        )
        require(
            len(option_ids) == len(set(option_ids)),
            f"product-option closure contains duplicates for {hypothesis_id}",
        )
        hypotheses_by_candidate[candidate_id].append(hypothesis)
        hypotheses_by_id[hypothesis_id] = hypothesis
        all_product_option_ids.extend(option_ids)
    require(
        len(all_product_option_ids) == len(set(all_product_option_ids)),
        "product-option identifiers must be unique across hypotheses",
    )

    option_record_ids = [option.get("option_id") for option in product_options]
    require(
        all(option_record_ids) and len(option_record_ids) == len(set(option_record_ids)),
        "product-option records require unique option_id values",
    )
    require(
        set(option_record_ids) == set(all_product_option_ids),
        "product-option record closure does not match hypothesis identifiers",
    )
    for option in product_options:
        option_id = option["option_id"]
        hypothesis_id = option.get("hypothesis_id")
        require(
            hypothesis_id in hypotheses_by_id,
            f"product option {option_id} references unknown hypothesis {hypothesis_id}",
        )
        hypothesis = hypotheses_by_id[hypothesis_id]
        require(
            option_id in hypothesis["product_option_ids"],
            f"product option {option_id} is not linked from hypothesis {hypothesis_id}",
        )
        require(
            option.get("display_id") == hypothesis.get("display_id"),
            f"product option {option_id} candidate does not match hypothesis {hypothesis_id}",
        )
        require(
            option.get("center") == hypothesis.get("center"),
            f"product option {option_id} center does not match hypothesis {hypothesis_id}",
        )
        require(
            "NP_label" in option
            and option["NP_label"] not in (None, "")
            and "NR_label" in option
            and option["NR_label"] not in (None, ""),
            f"product option {option_id} has no endpoint-specific NP/NR assessment",
        )
        parse_smiles(option.get("product_smiles"), f"product option {option_id}")

    rows = []
    for candidate in sorted(candidates, key=lambda item: item["display_id"]):
        candidate_id = candidate["display_id"]
        family_id = family_by_candidate[candidate_id]
        require(family_id in families, f"unknown candidate family: {family_id}")
        require(candidate.get("centers"), f"candidate {candidate_id} has no reacting centre")
        require(candidate.get("precursor_form"), f"candidate {candidate_id} has no precursor form")
        require(
            candidate.get("activation_hypothesis"),
            f"candidate {candidate_id} has no activation hypothesis",
        )
        expected_hypothesis_ids = sorted(
            hypothesis["hypothesis_id"]
            for hypothesis in hypotheses_by_candidate[candidate_id]
        )
        require(
            sorted(candidate.get("hypothesis_ids", [])) == expected_hypothesis_ids,
            f"hypothesis closure does not match candidate {candidate_id}",
        )
        expected_centres = sorted(
            {hypothesis["center"] for hypothesis in hypotheses_by_candidate[candidate_id]}
        )
        require(
            sorted(candidate["centers"]) == expected_centres,
            f"reacting-centre closure does not match candidate {candidate_id}",
        )
        expected_product_option_ids = sorted(
            option_id
            for hypothesis in hypotheses_by_candidate[candidate_id]
            for option_id in hypothesis["product_option_ids"]
        )
        require(
            sorted(candidate.get("product_option_ids", []))
            == expected_product_option_ids,
            f"product-option closure does not match candidate {candidate_id}",
        )
        family_links = sorted(
            principles_by_family[family_id], key=lambda item: item["principle_id"]
        )
        require(family_links, f"family {family_id} has no reaction-principle link")
        principle_ids = [item["principle_id"] for item in family_links]
        evidence_links = []
        for principle_id in principle_ids:
            evidence_links.extend(evidence_by_principle[principle_id])
        evidence_node_ids = sorted({item["evidence_node_id"] for item in evidence_links})
        require(evidence_node_ids, f"candidate {candidate_id} has no evidence-supported RP path")
        evidence_ids = sorted(
            {
                evidence_id
                for item in evidence_links
                for evidence_id in item["evidence_ids"]
            }
        )
        source_ids = sorted(
            {
                source_id
                for evidence_node_id in evidence_node_ids
                for source_id in evidence_nodes[evidence_node_id].get("references", [])
            }
        )
        rows.append(
            {
                "candidate_id": candidate_id,
                "name": candidate["name_en"],
                "canonical_smiles": candidate["canonical_smiles"],
                "reactive_centres": candidate["centers"],
                "precursor_form": candidate["precursor_form"],
                "activation_hypothesis": candidate["activation_hypothesis"],
                "family_id": family_id,
                "family_name": families[family_id]["label"].replace("\n", " "),
                "principle_ids": principle_ids,
                "principle_applications": family_links,
                "evidence_node_ids": evidence_node_ids,
                "evidence_ids": evidence_ids,
                "literature_source_ids": source_ids,
                "candidate_citations": [
                    item
                    for item in graph.get("candidate_citation_links", [])
                    if item["candidate_id"] == candidate_id
                ],
                "hypothesis_ids": candidate["hypothesis_ids"],
                "product_option_ids": candidate["product_option_ids"],
            }
        )

    counts = {
        "evidence_nodes": len(evidence_nodes),
        "reaction_principles": len(principles),
        "candidate_families": len(families),
        "recommended_nucleophiles": len(rows),
        "site_pathway_hypotheses": len(hypotheses),
        "product_options": len(product_options),
    }
    if (
        graph_path.resolve() == DEFAULT_GRAPH.resolve()
        and candidates_path.resolve() == DEFAULT_CANDIDATES.resolve()
        and hypotheses_path.resolve() == DEFAULT_HYPOTHESES.resolve()
        and product_options_path.resolve() == DEFAULT_PRODUCT_OPTIONS.resolve()
    ):
        require(
            counts
            == {
                "evidence_nodes": 17,
                "reaction_principles": 4,
                "candidate_families": 43,
                "recommended_nucleophiles": 100,
                "site_pathway_hypotheses": 103,
                "product_options": 103,
            },
            f"deposited-data counts changed: {counts}",
        )

    return {
        "status": "passed",
        "workflow": "literature evidence -> reaction principle -> candidate family -> recommended nucleophile",
        "inputs": {
            "graph": input_record(graph_path),
            "candidates": input_record(candidates_path),
            "hypotheses": input_record(hypotheses_path),
            "product_options": input_record(product_options_path),
        },
        "counts": counts,
        "principles": [
            {
                "principle_id": principle_id,
                "title": principle["card"]["title"],
                "candidate_generation_rules": principle["card"]["candidate_generation_rules"],
                "exceptions": principle["card"]["exceptions"],
            }
            for principle_id, principle in sorted(principles.items())
        ],
        "candidates": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, default=DEFAULT_GRAPH)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--hypotheses", type=Path, default=DEFAULT_HYPOTHESES)
    parser.add_argument("--product-options", type=Path, default=DEFAULT_PRODUCT_OPTIONS)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = build_report(
            args.graph,
            args.candidates,
            args.hypotheses,
            args.product_options,
        )
    except (KeyError, TypeError, ValueError) as error:
        print(f"validation failed: {error}", file=sys.stderr)
        return 1
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        print(
            json.dumps(
                {
                    "status": report["status"],
                    "output": str(args.output.resolve()),
                    "counts": report["counts"],
                },
                ensure_ascii=False,
            )
        )
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

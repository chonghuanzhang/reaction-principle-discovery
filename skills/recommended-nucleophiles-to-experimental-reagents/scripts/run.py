#!/usr/bin/env python3
"""Validate and export the candidate-to-experiment decision ledger."""

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

try:
    from rdkit import Chem
    from rdkit.Chem.MolStandardize import rdMolStandardize
except ImportError:  # Report a concise release-gate error from build_report.
    Chem = None
    rdMolStandardize = None


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CANDIDATES = ROOT / "candidates/data/candidates_100.json"
DEFAULT_MAPPING = ROOT / "candidates/experiment_mapping/mapping_108.json"
DEFAULT_HYPOTHESES = ROOT / "candidates/data/hypotheses_115.json"
ALLOWED_CLASSES = {
    "Exact Molecular Match",
    "Reactive-form Analogue",
    "Structural Analogue",
    "Additional Experimental Candidate",
    "Unmatched",
}
ORDINARY_IDENTITY_STATUSES = {
    "identity_confirmed",
    "workbook_structure_not_independently_verified",
}
UNRESOLVED_IDENTITY_STATUSES = {"unresolved_name_smiles_conflict"}
ROUTE_CENTERS = {"NH": "N", "OH": "O", "PH": "P", "SH": "S"}
FEASIBILITY_FIELDS = (
    "availability",
    "handling_and_safety",
    "chemical_compatibility",
)


def is_exception_record(pair):
    return (
        pair.get("primary_mapping_class")
        in {"Additional Experimental Candidate", "Unmatched"}
        or pair.get("input_identity_status") == "unresolved_name_smiles_conflict"
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
    require(molecule is not None, f"invalid SMILES for {label}: {smiles}")
    return molecule


def canonical_smiles(molecule):
    return Chem.MolToSmiles(molecule, isomericSmiles=True)


def neutral_parent_smiles(molecule):
    require(
        rdMolStandardize is not None,
        "RDKit MolStandardize is required; install skills/requirements.txt",
    )
    parent = rdMolStandardize.LargestFragmentChooser().choose(Chem.Mol(molecule))
    parent = rdMolStandardize.Uncharger().uncharge(parent)
    return canonical_smiles(parent)


def build_report(
    candidates_path=DEFAULT_CANDIDATES,
    mapping_path=DEFAULT_MAPPING,
    hypotheses_path=DEFAULT_HYPOTHESES,
):
    candidates_path = Path(candidates_path)
    mapping_path = Path(mapping_path)
    hypotheses_path = Path(hypotheses_path)
    candidates = load_json(candidates_path)
    pairs = load_json(mapping_path)
    hypotheses = load_json(hypotheses_path)
    require(isinstance(candidates, list), "candidates input must be a JSON list")
    require(isinstance(pairs, list), "mapping input must be a JSON list")
    require(isinstance(hypotheses, list), "hypotheses input must be a JSON list")
    candidate_ids = {candidate.get("display_id") for candidate in candidates}
    require(None not in candidate_ids and "" not in candidate_ids, "every candidate must have a display_id")
    require(len(candidate_ids) == len(candidates), "candidate display_ids must be unique")
    candidates_by_id = {candidate["display_id"]: candidate for candidate in candidates}
    candidate_molecules = {}
    candidate_structures = {}
    for candidate_id, candidate in candidates_by_id.items():
        candidate_molecule = parse_smiles(
            candidate.get("canonical_smiles"), f"candidate {candidate_id}"
        )
        candidate_molecules[candidate_id] = candidate_molecule
        candidate_structures[candidate_id] = canonical_smiles(candidate_molecule)

    hypothesis_ids = [hypothesis.get("hypothesis_id") for hypothesis in hypotheses]
    require(all(hypothesis_ids), "every hypothesis must have a hypothesis_id")
    require(
        len(hypothesis_ids) == len(set(hypothesis_ids)),
        "hypothesis_ids must be unique",
    )
    hypotheses_by_id = {hypothesis["hypothesis_id"]: hypothesis for hypothesis in hypotheses}
    for hypothesis_id, hypothesis in hypotheses_by_id.items():
        require(
            hypothesis.get("display_id") in candidate_ids,
            f"hypothesis {hypothesis_id} references an unknown candidate",
        )

    pair_ids = [pair.get("actual_pair_id") for pair in pairs]
    require(all(pair_ids), "every mapping record must have an actual_pair_id")
    require(len(pair_ids) == len(set(pair_ids)), "actual_pair_ids must be unique")

    for pair in pairs:
        pair_id = pair["actual_pair_id"]
        route = pair.get("route")
        require(route in ROUTE_CENTERS, f"unsupported route for {pair_id}: {route}")
        expected_route_center = ROUTE_CENTERS[route]
        actual_donor_molecule = parse_smiles(
            pair.get("actual_donor_smiles"), f"experimental reagent {pair_id}"
        )
        actual_donor_structure = canonical_smiles(actual_donor_molecule)
        parse_smiles(pair.get("electrophile_smiles"), f"electrophile {pair_id}")
        primary_mapping_class = pair.get("primary_mapping_class")
        require(primary_mapping_class in ALLOWED_CLASSES, f"invalid relation class for {pair_id}")
        links = pair.get("candidate_links")
        require(isinstance(links, list), f"candidate_links must be a list for {pair_id}")
        for link in links:
            linked_id = link.get("candidate_display_id")
            require(linked_id in candidate_ids, f"unknown candidate {linked_id} linked from {pair_id}")
            require(
                link.get("relation") in ALLOWED_CLASSES - {"Unmatched"},
                f"invalid relation for {pair_id} -> {linked_id}",
            )
            require(link.get("reason"), f"missing relation rationale for {pair_id} -> {linked_id}")
            route_center = link.get("route_center")
            require(
                route_center == expected_route_center,
                f"route center {route_center} does not match {route} for {pair_id}",
            )
            compatible_hypothesis_ids = link.get(
                "route_compatible_original_hypothesis_ids"
            )
            require(
                isinstance(compatible_hypothesis_ids, list)
                and compatible_hypothesis_ids
                and len(compatible_hypothesis_ids)
                == len(set(compatible_hypothesis_ids)),
                f"route-compatible hypothesis list is invalid for {pair_id} -> {linked_id}",
            )
            for hypothesis_id in compatible_hypothesis_ids:
                require(
                    hypothesis_id in hypotheses_by_id,
                    f"unknown route-compatible hypothesis {hypothesis_id} for {pair_id}",
                )
                hypothesis = hypotheses_by_id[hypothesis_id]
                require(
                    hypothesis.get("display_id") == linked_id,
                    f"route-compatible hypothesis {hypothesis_id} does not belong to {linked_id}",
                )
                require(
                    hypothesis.get("center") == route_center,
                    f"route center {route_center} does not match hypothesis {hypothesis_id}",
                )
            if link.get("relation") == "Exact Molecular Match":
                require(
                    actual_donor_structure == candidate_structures[linked_id],
                    f"exact molecular match is structurally false for {pair_id} -> {linked_id}",
                )
            elif link.get("relation") == "Reactive-form Analogue":
                require(
                    neutral_parent_smiles(actual_donor_molecule)
                    == neutral_parent_smiles(candidate_molecules[linked_id]),
                    f"reactive-form analogue has a different neutral covalent parent "
                    f"for {pair_id} -> {linked_id}",
                )
        if primary_mapping_class == "Unmatched":
            require(pair.get("unmatched_reason"), f"unmatched record {pair_id} requires a reason")
        else:
            require(links, f"matched record {pair_id} requires at least one candidate link")
            require(
                any(link.get("relation") == primary_mapping_class for link in links),
                f"primary mapping class {primary_mapping_class} has no matching link for {pair_id}",
            )
            require(
                any(
                    atom.GetSymbol() == expected_route_center
                    and (atom.GetTotalNumHs() > 0 or atom.GetFormalCharge() < 0)
                    for atom in actual_donor_molecule.GetAtoms()
                ),
                f"matched reagent {pair_id} has no reactive route site for {route}",
            )
        identity_status = pair.get("input_identity_status")
        require(identity_status, f"missing identity status for {pair_id}")
        require(
            identity_status
            in ORDINARY_IDENTITY_STATUSES | UNRESOLVED_IDENTITY_STATUSES,
            f"unresolved identity status is not admitted for {pair_id}: {identity_status}",
        )
        require("NP_label_preserved" in pair, f"missing NP assessment for {pair_id}")
        require("NR_preserved" in pair, f"missing NR assessment for {pair_id}")
        require(pair.get("execution_status"), f"missing execution status for {pair_id}")
        require(pair.get("source_occurrences"), f"missing source-linked execution record for {pair_id}")
        exception_record = is_exception_record(pair)
        expected_decision = (
            "approved_exploratory_exception"
            if exception_record
            else "approved_for_experimental_screening"
        )
        expected_review = "approved_exception" if exception_record else "approved"
        expected_release_gate = (
            "exception_register" if exception_record else "experiment_ready"
        )
        require(
            pair.get("selection_decision_recorded") is True
            and pair.get("selection_decision") == expected_decision
            and pair.get("human_review_status") == expected_review
            and pair.get("release_gate_status") == expected_release_gate,
            f"missing reviewed selection decision for {pair_id}",
        )
        if identity_status in UNRESOLVED_IDENTITY_STATUSES:
            require(
                pair.get("input_identity_issues"),
                f"identity exception {pair_id} requires an explicit issue record",
            )
            require(
                exception_record,
                f"identity exception {pair_id} must remain in the exception register",
            )
        feasibility = pair.get("feasibility_review")
        require(
            pair.get("selection_rationale") and isinstance(feasibility, dict),
            f"missing decision rationale or feasibility review for {pair_id}",
        )
        for field in FEASIBILITY_FIELDS:
            require(
                feasibility.get(field),
                f"missing feasibility field {field} for {pair_id}",
            )

    classes = Counter(pair["primary_mapping_class"] for pair in pairs)
    distinct_donors = {pair["actual_donor_smiles"] for pair in pairs}

    ledger = []
    for pair in sorted(pairs, key=lambda item: item["actual_pair_id"]):
        ledger.append(
            {
                "actual_pair_id": pair["actual_pair_id"],
                "route": pair["route"],
                "electrophile_smiles": pair["electrophile_smiles"],
                "experimental_reagent_smiles": pair["actual_donor_smiles"],
                "experimental_reagent_family": pair["partner_family_en"],
                "relation_class": pair["primary_mapping_class"],
                "candidate_links": [
                    {
                        "candidate_id": link["candidate_display_id"],
                        "candidate_name": link["candidate_name_en"],
                        "relation": link["relation"],
                        "reason": link["reason"],
                        "route_compatible_hypothesis_ids": link[
                            "route_compatible_original_hypothesis_ids"
                        ],
                    }
                    for link in pair["candidate_links"]
                ],
                "unmatched_reason": pair["unmatched_reason"],
                "identity_status": pair["input_identity_status"],
                "identity_issues": pair["input_identity_issues"],
                "NP_label": pair["NP_label_preserved"],
                "NR_label": pair["NR_preserved"],
                "execution_status": pair["execution_status"],
                "source_occurrences": pair["source_occurrences"],
                "sample_ids": pair["sample_ids"],
                "selection_decision_recorded": pair.get("selection_decision_recorded"),
                "selection_decision": pair.get("selection_decision"),
                "human_review_status": pair.get("human_review_status"),
                "release_gate_status": pair.get("release_gate_status"),
                "selection_rationale": pair.get("selection_rationale"),
                "feasibility_review": pair.get("feasibility_review"),
            }
        )

    counts = {
        "recommended_nucleophiles": len(candidates),
        "experimental_pairs": len(pairs),
        "distinct_experimental_donors": len(distinct_donors),
        "exact_matches": classes["Exact Molecular Match"],
        "structural_or_family_matches": classes["Structural Analogue"],
        "unmatched_inputs": classes["Unmatched"],
        "approved_exceptions": sum(is_exception_record(pair) for pair in pairs),
    }
    if (
        candidates_path.resolve() == DEFAULT_CANDIDATES.resolve()
        and mapping_path.resolve() == DEFAULT_MAPPING.resolve()
        and hypotheses_path.resolve() == DEFAULT_HYPOTHESES.resolve()
    ):
        require(
            counts
            == {
                "recommended_nucleophiles": 100,
                "experimental_pairs": 108,
                "distinct_experimental_donors": 102,
                "exact_matches": 3,
                "structural_or_family_matches": 101,
                "unmatched_inputs": 4,
                "approved_exceptions": 7,
            },
            f"deposited-data counts changed: {counts}",
        )

    return {
        "status": "passed",
        "workflow": "recommended nucleophile -> identity and relationship review -> feasibility review -> experiment-ready selection or explicit exception -> executed experiment",
        "inputs": {
            "candidates": input_record(candidates_path),
            "mapping": input_record(mapping_path),
            "hypotheses": input_record(hypotheses_path),
        },
        "counts": counts,
        "experiment_ledger": ledger,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING)
    parser.add_argument("--hypotheses", type=Path, default=DEFAULT_HYPOTHESES)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = build_report(args.candidates, args.mapping, args.hypotheses)
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

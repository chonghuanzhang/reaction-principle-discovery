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
except ImportError:  # Report a concise release-gate error from build_report.
    Chem = None


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CANDIDATES = ROOT / "candidates/data/candidates_100.json"
DEFAULT_MAPPING = ROOT / "candidates/experiment_mapping/mapping_108.json"
DEFAULT_HYPOTHESES = ROOT / "candidates/data/hypotheses_103.json"
RELATIONSHIP_CATEGORIES = {
    "Exact identity",
    "Same scaffold, substituent or positional variation",
    "Same donor family, different scaffold",
    "No reasonable counterpart",
}
LINK_RELATIONSHIP_CATEGORIES = RELATIONSHIP_CATEGORIES - {"No reasonable counterpart"}
RELATIONSHIP_ID_FIELDS = {
    "Exact identity": "exact_candidate_ids",
    "Same scaffold, substituent or positional variation": (
        "scaffold_or_substituent_candidate_ids"
    ),
    "Same donor family, different scaffold": "donor_family_candidate_ids",
}
ORDINARY_IDENTITY_STATUSES = {
    "identity_confirmed",
    "workbook_structure_not_independently_verified",
}
UNRESOLVED_IDENTITY_STATUSES = {"unresolved_name_smiles_conflict"}
ROUTE_CENTERS = {"NH": "N", "OH": "O", "PH": "P", "SH": "S"}
REQUIRED_OCCURRENCE_FIELDS = ("workbook", "sheet", "row", "experiment_id", "condition_id")


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


def validate_atom_index(molecule, atom_index, symbol, label):
    require(
        isinstance(atom_index, int)
        and not isinstance(atom_index, bool)
        and 0 <= atom_index < molecule.GetNumAtoms(),
        f"reacting atom index is out of range for {label}: {atom_index}",
    )
    atom = molecule.GetAtomWithIdx(atom_index)
    require(
        atom.GetSymbol() == symbol,
        f"reacting atom {atom_index} does not match {symbol} for {label}",
    )
    return atom


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
    candidate_id_list = [candidate.get("display_id") for candidate in candidates]
    require(all(candidate_id_list), "every candidate must have a display_id")
    require(
        len(candidate_id_list) == len(set(candidate_id_list)),
        "candidate display_ids must be unique",
    )
    candidate_ids = set(candidate_id_list)
    candidates_by_id = {candidate["display_id"]: candidate for candidate in candidates}
    candidate_molecules = {}
    candidate_structures = {}
    for candidate_id, candidate in candidates_by_id.items():
        candidate_molecule = parse_smiles(
            candidate.get("canonical_smiles"), f"candidate {candidate_id}"
        )
        normalized_structure = canonical_smiles(candidate_molecule)
        require(
            candidate["canonical_smiles"] == normalized_structure,
            f"non-canonical candidate SMILES for {candidate_id}",
        )
        candidate_molecules[candidate_id] = candidate_molecule
        candidate_structures[candidate_id] = normalized_structure
        route = candidate.get("route")
        center = candidate.get("center")
        require(route in ROUTE_CENTERS, f"unsupported route for {candidate_id}: {route}")
        require(
            center == ROUTE_CENTERS[route] and candidate.get("centers") == [center],
            f"route and reacting centre do not match for {candidate_id}",
        )
        atom_indices = candidate.get("reactive_atom_indices")
        require(
            isinstance(atom_indices, list)
            and atom_indices
            and len(atom_indices) == len(set(atom_indices)),
            f"candidate {candidate_id} has invalid reacting atom indices",
        )
        for atom_index in atom_indices:
            validate_atom_index(candidate_molecule, atom_index, center, candidate_id)

    hypothesis_ids = [hypothesis.get("hypothesis_id") for hypothesis in hypotheses]
    require(all(hypothesis_ids), "every hypothesis must have a hypothesis_id")
    require(
        len(hypothesis_ids) == len(set(hypothesis_ids)),
        "hypothesis_ids must be unique",
    )
    hypotheses_by_id = {hypothesis["hypothesis_id"]: hypothesis for hypothesis in hypotheses}
    hypotheses_by_candidate = {candidate_id: [] for candidate_id in candidate_ids}
    for hypothesis_id, hypothesis in hypotheses_by_id.items():
        candidate_id = hypothesis.get("display_id")
        require(
            candidate_id in candidate_ids,
            f"hypothesis {hypothesis_id} references an unknown candidate",
        )
        candidate = candidates_by_id[candidate_id]
        require(
            hypothesis.get("candidate_id") == candidate.get("candidate_id"),
            f"hypothesis {hypothesis_id} candidate identity does not match {candidate_id}",
        )
        hypothesis_molecule = parse_smiles(
            hypothesis.get("reactive_atom_input_smiles"), hypothesis_id
        )
        require(
            canonical_smiles(hypothesis_molecule) == candidate_structures[candidate_id],
            f"hypothesis {hypothesis_id} structure does not match {candidate_id}",
        )
        center = hypothesis.get("center")
        require(
            center == candidate.get("center"),
            f"hypothesis {hypothesis_id} centre does not match {candidate_id}",
        )
        atom_indices = hypothesis.get("reactive_atom_indices")
        require(
            isinstance(atom_indices, list)
            and atom_indices
            and len(atom_indices) == len(set(atom_indices)),
            f"hypothesis {hypothesis_id} has invalid reacting atom indices",
        )
        for atom_index in atom_indices:
            validate_atom_index(hypothesis_molecule, atom_index, center, hypothesis_id)
        option_ids = hypothesis.get("product_option_ids")
        require(
            isinstance(option_ids, list)
            and option_ids
            and len(option_ids) == len(set(option_ids)),
            f"hypothesis {hypothesis_id} has invalid product-option identifiers",
        )
        hypotheses_by_candidate[candidate_id].append(hypothesis)

    for candidate_id, candidate in candidates_by_id.items():
        linked_hypothesis_ids = {
            hypothesis["hypothesis_id"]
            for hypothesis in hypotheses_by_candidate[candidate_id]
        }
        require(
            set(candidate.get("hypothesis_ids", [])) == linked_hypothesis_ids,
            f"hypothesis closure does not match {candidate_id}",
        )
        linked_option_ids = {
            option_id
            for hypothesis in hypotheses_by_candidate[candidate_id]
            for option_id in hypothesis["product_option_ids"]
        }
        require(
            set(candidate.get("product_option_ids", [])) == linked_option_ids,
            f"product-option closure does not match {candidate_id}",
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
        primary_category = pair.get("primary_relationship_category")
        require(
            primary_category in RELATIONSHIP_CATEGORIES,
            f"invalid relationship category for {pair_id}",
        )
        links = pair.get("candidate_links")
        require(isinstance(links, list), f"candidate_links must be a list for {pair_id}")
        link_keys = [
            (link.get("candidate_display_id"), link.get("relationship_category"))
            for link in links
        ]
        require(
            len(link_keys) == len(set(link_keys)),
            f"duplicate candidate relationship for {pair_id}",
        )
        partition_ids = {category: [] for category in RELATIONSHIP_ID_FIELDS}
        for link in links:
            linked_id = link.get("candidate_display_id")
            require(linked_id in candidate_ids, f"unknown candidate {linked_id} linked from {pair_id}")
            relationship = link.get("relationship_category")
            require(
                relationship in LINK_RELATIONSHIP_CATEGORIES,
                f"invalid relationship for {pair_id} -> {linked_id}",
            )
            partition_ids[relationship].append(linked_id)
            require(link.get("reason"), f"missing relation rationale for {pair_id} -> {linked_id}")
            route_center = link.get("route_center")
            require(
                route_center == expected_route_center,
                f"route center {route_center} does not match {route} for {pair_id}",
            )
            candidate = candidates_by_id[linked_id]
            linked_molecule = parse_smiles(
                link.get("candidate_smiles"), f"linked candidate {pair_id} -> {linked_id}"
            )
            require(
                canonical_smiles(linked_molecule) == candidate_structures[linked_id],
                f"linked candidate structure does not match {linked_id} for {pair_id}",
            )
            require(
                link.get("candidate_name_en") == candidate.get("name_en"),
                f"linked candidate name does not match {linked_id} for {pair_id}",
            )
            candidate_atom_index = link.get("candidate_reacting_atom_index")
            validate_atom_index(
                candidate_molecules[linked_id],
                candidate_atom_index,
                route_center,
                f"{pair_id} -> {linked_id}",
            )
            require(
                candidate_atom_index in candidate.get("reactive_atom_indices", []),
                f"linked reacting atom is not declared by {linked_id} for {pair_id}",
            )
            actual_atom = validate_atom_index(
                actual_donor_molecule,
                link.get("actual_reacting_atom_index"),
                route_center,
                f"experimental reagent {pair_id}",
            )
            require(
                actual_atom.GetTotalNumHs() > 0 or actual_atom.GetFormalCharge() < 0,
                f"linked experimental reagent {pair_id} has no reactive {route_center} site",
            )
            compatible_hypothesis_ids = link.get("route_compatible_hypothesis_ids")
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
            require(
                any(
                    candidate_atom_index
                    in hypotheses_by_id[hypothesis_id]["reactive_atom_indices"]
                    for hypothesis_id in compatible_hypothesis_ids
                ),
                f"linked reacting atom has no compatible hypothesis for {pair_id} -> {linked_id}",
            )
            applicable_option_ids = link.get("applicable_product_option_ids")
            require(
                isinstance(applicable_option_ids, list)
                and len(applicable_option_ids) == len(set(applicable_option_ids))
                and set(applicable_option_ids)
                <= set(candidate.get("product_option_ids", [])),
                f"invalid product-option links for {pair_id} -> {linked_id}",
            )
            if relationship == "Exact identity":
                require(
                    actual_donor_structure == candidate_structures[linked_id],
                    f"exact identity is structurally false for {pair_id} -> {linked_id}",
                )

        for relationship, field in RELATIONSHIP_ID_FIELDS.items():
            require(
                pair.get(field) == partition_ids[relationship],
                f"{field} does not match candidate links for {pair_id}",
            )
        if primary_category == "No reasonable counterpart":
            require(
                not links and pair.get("unmatched_reason"),
                f"unmatched record {pair_id} requires no forced links and an explicit reason",
            )
        else:
            require(links, f"matched record {pair_id} requires at least one candidate link")
            require(
                any(
                    link.get("relationship_category") == primary_category for link in links
                ),
                f"primary relationship {primary_category} has no matching link for {pair_id}",
            )
            require(
                not pair.get("unmatched_reason"),
                f"matched record {pair_id} must not retain an unmatched reason",
            )
        identity_status = pair.get("input_identity_status")
        require(identity_status, f"missing identity status for {pair_id}")
        require(
            identity_status
            in ORDINARY_IDENTITY_STATUSES | UNRESOLVED_IDENTITY_STATUSES,
            f"unresolved identity status is not admitted for {pair_id}: {identity_status}",
        )
        identity_issues = pair.get("input_identity_issues")
        require(isinstance(identity_issues, list), f"invalid identity issue list for {pair_id}")
        if identity_status in UNRESOLVED_IDENTITY_STATUSES:
            require(identity_issues, f"identity exception {pair_id} requires an issue record")
        require(
            "NP_label" in pair and pair["NP_label"] not in (None, ""),
            f"missing NP assessment for {pair_id}",
        )
        require(
            "NR_label" in pair and pair["NR_label"] not in (None, ""),
            f"missing NR assessment for {pair_id}",
        )
        require(
            pair.get("product_identity_status")
            and pair.get("quantitative_result_status")
            and pair.get("novelty_comparison_scope"),
            f"missing interpretation status for {pair_id}",
        )
        require(pair.get("execution_status"), f"missing execution status for {pair_id}")
        occurrences = pair.get("source_occurrences")
        require(
            isinstance(occurrences, list) and occurrences,
            f"missing source-linked execution record for {pair_id}",
        )
        for occurrence in occurrences:
            missing_fields = [
                field
                for field in REQUIRED_OCCURRENCE_FIELDS
                if occurrence.get(field) in (None, "")
            ]
            require(
                not missing_fields,
                f"incomplete source occurrence for {pair_id}: {missing_fields}",
            )
            require(
                isinstance(occurrence["row"], int)
                and not isinstance(occurrence["row"], bool)
                and occurrence["row"] > 0,
                f"invalid source row for {pair_id}",
            )
        require(
            pair.get("source_occurrence_count") == len(occurrences),
            f"source occurrence count does not match {pair_id}",
        )
        require(
            pair.get("unique_condition_recipe_count")
            == len({occurrence["condition_id"] for occurrence in occurrences}),
            f"condition count does not match {pair_id}",
        )
        require(
            sorted(pair.get("sample_ids", []))
            == sorted({occurrence["experiment_id"] for occurrence in occurrences}),
            f"sample identifiers do not match source occurrences for {pair_id}",
        )

    classes = Counter(pair["primary_relationship_category"] for pair in pairs)
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
                "relationship_category": pair["primary_relationship_category"],
                "relationship_detail_zh": pair["relationship_detail_zh"],
                "candidate_links": [
                    {
                        "candidate_id": link["candidate_display_id"],
                        "candidate_name": link["candidate_name_en"],
                        "relationship_category": link["relationship_category"],
                        "reason": link["reason"],
                        "route_compatible_hypothesis_ids": link[
                            "route_compatible_hypothesis_ids"
                        ],
                        "actual_reacting_atom_index": link["actual_reacting_atom_index"],
                        "candidate_reacting_atom_index": link[
                            "candidate_reacting_atom_index"
                        ],
                    }
                    for link in pair["candidate_links"]
                ],
                "unmatched_reason": pair["unmatched_reason"],
                "identity_status": pair["input_identity_status"],
                "identity_issues": pair["input_identity_issues"],
                "product_identity_status": pair["product_identity_status"],
                "quantitative_result_status": pair["quantitative_result_status"],
                "NP_label": pair["NP_label"],
                "NR_label": pair["NR_label"],
                "execution_status": pair["execution_status"],
                "source_occurrences": pair["source_occurrences"],
                "sample_ids": pair["sample_ids"],
                "novelty_comparison_scope": pair["novelty_comparison_scope"],
            }
        )

    counts = {
        "recommended_nucleophiles": len(candidates),
        "experimental_pairs": len(pairs),
        "distinct_experimental_donors": len(distinct_donors),
        "exact_identity_pairs": classes["Exact identity"],
        "scaffold_or_substituent_pairs": classes[
            "Same scaffold, substituent or positional variation"
        ],
        "donor_family_pairs": classes["Same donor family, different scaffold"],
        "unmatched_pairs": classes["No reasonable counterpart"],
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
                "exact_identity_pairs": 26,
                "scaffold_or_substituent_pairs": 37,
                "donor_family_pairs": 41,
                "unmatched_pairs": 4,
            },
            f"deposited-data counts changed: {counts}",
        )

    return {
        "status": "passed",
        "workflow": "recommended nucleophile -> recorded structural relationship -> executed experimental pair",
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

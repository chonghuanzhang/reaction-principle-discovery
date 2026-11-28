#!/usr/bin/env python3
"""Reproduce Figure 6 counts and deposit the exact RP donor membership.

Requires openpyxl and RDKit. No network or model calls are made.
"""
from collections import Counter, defaultdict
import csv
import hashlib
import json
import math
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from rdkit import Chem

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(__file__).resolve().parent / "data"
WORKBOOK = ROOT / "optimization/raw/summary_workbook.xlsx"
CONFIGS = [
    dict(route="NH", sheet="NH-底物扩展", donor="V", cas="U", electrophile="R",
         uv=["AB"], conditions={"B": 0.025, "C": "Ag13", "G": "PPh3", "J": "NaH", "M": "DCE", "O": 16, "P": 60}),
    dict(route="OH", sheet="OH-底物扩展", donor="X", cas="W", electrophile="T",
         uv=["AD", "AE"], conditions={"B": 0.025, "C": "Ni203", "L": "DIPEA", "O": "DCE", "Q": 16, "R": 60}),
    dict(route="SH", sheet="SH底物扩展", donor="V", cas="U", electrophile="R",
         uv=["AC", "AD"], conditions={"B": 0.025, "C": "Cu9", "G": "PPh3", "J": "CsOH", "M": "DCE", "O": 16, "P": 60}),
]


def canonical(smiles):
    molecule = Chem.MolFromSmiles(smiles)
    if molecule is None:
        raise ValueError(f"Invalid SMILES: {smiles}")
    return Chem.MolToSmiles(molecule, isomericSmiles=True)


def main():
    workbook = load_workbook(WORKBOOK, data_only=True, read_only=True)
    grouped = defaultdict(list)
    excluded = []
    for cfg in CONFIGS:
        sheet = workbook[cfg["sheet"]]
        for row, cells in enumerate(sheet.iter_rows(min_row=2), 2):
            values = {get_column_letter(i): cell.value for i, cell in enumerate(cells, 1)}
            numeric = {col: values.get(col) for col in cfg["uv"]
                       if isinstance(values.get(col), (int, float)) and not isinstance(values.get(col), bool)}
            if not numeric or not all(values.get(col) == expected for col, expected in cfg["conditions"].items()):
                excluded.append({"sheet": cfg["sheet"], "row": row,
                                 "reason": "No numerical UV response" if not numeric else "Different reaction-condition block"})
                continue
            smiles = canonical(values[cfg["donor"]])
            grouped[(cfg["route"], smiles)].append({
                "sheet": cfg["sheet"], "row": row, "experiment_id": values.get("A"),
                "donor_cell": f'{cfg["donor"]}{row}', "donor_raw": values[cfg["donor"]],
                "cas_cell": f'{cfg["cas"]}{row}', "cas_raw": values.get(cfg["cas"]),
                "electrophile_smiles": canonical(values[cfg["electrophile"]]),
                "uv_cells": {f"{col}{row}": value for col, value in numeric.items()},
                "condition_cells": {f"{col}{row}": values.get(col) for col in cfg["conditions"]},
            })
    members = []
    for i, ((route, smiles), observations) in enumerate(sorted(grouped.items()), 1):
        cas_values = sorted({str(observation["cas_raw"]) for observation in observations})
        members.append({
            "analysis_donor_id": f"RP94-{i:03d}", "route": route, "canonical_smiles": smiles,
            "response_positive": any(value > 0 for observation in observations for value in observation["uv_cells"].values()),
            "source_observations": observations,
            "identity_note": "" if len(cas_values) == 1 else "Source rows encode the same canonical donor SMILES under different CAS labels; structure-based deduplication retains one donor and preserves both observations.",
        })
    rp = {member["canonical_smiles"] for member in members}
    assert len(rp) == len(members), "Donor appears in more than one route"
    llm = json.loads((DATA / "llm_records.json").read_text())
    literature = json.loads((DATA / "literature_baseline_records.json").read_text())["records"]
    llm_set = {canonical(record["canonical_smiles"]) for record in llm}
    lit_set = {canonical(record["canonical_smiles"]) for record in literature}
    llm_positive = {canonical(record["canonical_smiles"]) for record in llm if record["product_positive"]}
    lit_positive = {canonical(record["canonical_smiles"]) for record in literature if record["response_positive"]}
    assert (len(llm_positive), len(llm_set)) == (4, 20)
    assert (len(lit_positive), len(lit_set)) == (3, 20)
    intersections = Counter((s in rp, s in llm_set, s in lit_set) for s in rp | llm_set | lit_set)
    by_route = Counter(member["route"] for member in members)
    positive_by_route = Counter(member["route"] for member in members if member["response_positive"])
    assert by_route == {"NH": 38, "OH": 36, "SH": 20}, by_route
    assert positive_by_route == {"NH": 12, "OH": 11, "SH": 12}, positive_by_route
    expected = {(True, False, False): 91, (False, True, False): 18, (False, False, True): 19,
                (True, True, False): 2, (True, False, True): 1}
    assert intersections == expected, intersections
    deposit = {
        "source_workbook": str(WORKBOOK.relative_to(ROOT)),
        "source_sha256": hashlib.sha256(WORKBOOK.read_bytes()).hexdigest(),
        "selection": "Numerical UV observations from the fixed-condition N-H, O-H and S-H substrate-scope panels. O-H uses the DIPEA/DCE block; the Na3PO4/DIO block is outside this comparison.",
        "conditions": CONFIGS,
        "identity_rule": "Canonical isomeric donor SMILES; repeated observations of a donor are merged within the selected condition block.",
        "positive_rule": "At least one numerical UV response greater than zero in the selected block.",
        "total_unique_donors": len(members), "positive_donors": sum(positive_by_route.values()),
        "by_route": by_route, "positive_by_route": positive_by_route,
        "members": members, "excluded_source_rows": excluded,
    }
    (DATA / "rp_analysis_membership_94.json").write_text(json.dumps(deposit, indent=2, ensure_ascii=False) + "\n")
    with (DATA / "rp_analysis_membership_94.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["analysis_donor_id", "route", "canonical_smiles", "response_positive", "sheet", "rows", "uv_cells", "identity_note"])
        writer.writeheader()
        for member in members:
            writer.writerow({**{key: member[key] for key in ["analysis_donor_id", "route", "canonical_smiles", "response_positive", "identity_note"]},
                             "sheet": member["source_observations"][0]["sheet"],
                             "rows": ";".join(str(o["row"]) for o in member["source_observations"]),
                             "uv_cells": json.dumps({key: value for o in member["source_observations"] for key, value in o["uv_cells"].items()})})
    summary = json.loads((DATA / "comparison_summary.json").read_text())
    for stat, (positive, total) in zip(summary["statistics"], [(35, 94), (4, 20), (3, 20)], strict=True):
        assert (stat["positive"], stat["tested_unique_donors"]) == (positive, total)
        fraction, z = positive / total, 1.959963984540054
        centre = (fraction + z*z/(2*total)) / (1 + z*z/total)
        radius = z * math.sqrt(fraction*(1-fraction)/total + z*z/(4*total*total)) / (1 + z*z/total)
        assert math.isclose(stat["fraction"], fraction, abs_tol=1e-12)
        assert math.isclose(stat["wilson95_low"], centre-radius, abs_tol=1e-7)
        assert math.isclose(stat["wilson95_high"], centre+radius, abs_tol=1e-7)
    for membership in summary["reported_unique_structure_intersections"]:
        assert intersections[tuple(membership["membership"])] == membership["count"]
    summary["panel_scopes"]["panel_b"]["count_provenance"] = "Reproduced from data/rp_analysis_membership_94.json, llm_records.json and literature_baseline_records.json by reproduce_comparison.py."
    summary["collection_definitions"]["RP-guided"]["electrophile"] = "Six electrophile structures occur in the 112-pair experimental mapping."
    summary["collection_definitions"]["RP-guided"]["conditions"] = "Fixed-condition substrate-scope panels: NH Ag13/PPh3/NaH/DCE; OH Ni203/DIPEA/DCE; SH Cu9/PPh3/CsOH/DCE, all 0.025 mmol, 60 °C and 16 h."
    summary["collection_definitions"]["RP-guided"]["endpoint"] = "Nonzero numerical UV response aggregated by unique donor structure within the selected fixed-condition panel."
    summary["rp_membership_source"] = "rp_analysis_membership_94.json"
    (DATA / "comparison_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    report = {"status": "passed", "unique_donors": len(members), "positive_donors": sum(positive_by_route.values()),
              "by_route": by_route, "positive_by_route": positive_by_route,
              "intersections": [{"membership": list(key), "count": value} for key, value in expected.items()],
              "baseline_positive_counts": {"LLM": [len(llm_positive), len(llm_set)], "literature": [len(lit_positive), len(lit_set)]},
              "wilson95_intervals_verified": True, "network_calls": 0, "model_calls": 0}
    (DATA / "comparison_verification.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

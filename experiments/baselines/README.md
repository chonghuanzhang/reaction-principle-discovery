# Baseline comparison data

This directory contains the machine-readable experimental records used for the
direct-LLM and literature-selection comparisons in Figure 6.

- `data/llm_records.json` contains 20 unique direct-LLM recommendations and
  their recorded qualitative outcomes.
- `data/literature_baseline_records.json` preserves 21 source records,
  including one duplicated source structure, and identifies the 20 unique
  structures used in the comparison.
- `data/comparison_summary.json` contains the reported outcome counts, Wilson
  intervals and experimental-set intersection counts used in panels a and b.
- `data/rp_analysis_membership_94.json` and the accompanying CSV identify every
  RP donor in panels a and b, with the source worksheet, row, UV cells and
  reaction conditions. The JSON also records excluded source rows.

The RP-guided collection uses nonzero numerical UV response in the selected
fixed-condition substrate-scope panels. Both baseline collections use `有产物` and `trace` as their final
qualitative calls. `Trace` denotes a negligible UV-response outcome and is
counted as negative for the displayed fractions.

Figure 6a compares the reported collection-positive fractions: 35/94 for the
RP-guided N/O/S analysis, 4/20 for direct-LLM recommendations and 3/20 for
literature selections. The RP-guided route contributions are 12/38 N-H, 11/36
O-H and 12/20 S-H donors. The observed RP-guided positive fraction is 1.86-fold
and 2.48-fold higher than in the direct-LLM and literature-selection
collections, respectively. These fractions summarize the tested collections
under their respective electrophile and reaction-condition combinations.

Figure 6b reports exact-structure overlaps in the same analysis collections:
94 unique RP experimental donors, 20 direct-LLM structures and 20 unique
literature structures. The reported membership-pattern counts are 91, 18, 19, 2 and 1
in RP-only, LLM-only, literature-only, RP+LLM and RP+literature order.

The RP comparison is a defined subset of the 112 experimental pairs. It uses
the N–H Ag13/PPh3/NaH/DCE, O–H Ni203/DIPEA/DCE and S–H Cu9/PPh3/CsOH/DCE
panels, all at 0.025 mmol, 60 °C and 16 h. In the deposited summary workbook,
these are `NH-底物扩展` rows 2–39, `OH-底物扩展` rows 2–38 and `SH底物扩展`
rows 2–21. The O–H Na3PO4/DIO condition block is outside this comparison.
O–H rows 16 and 23 encode the same canonical donor structure under different
CAS labels and are merged as one donor; both original observations are retained.

Run `python experiments/baselines/reproduce_comparison.py` from the repository
root with `openpyxl` and `rdkit` installed. The script reads
`optimization/raw/summary_workbook.xlsx`, regenerates the donor membership and
checks 35/94, the three route contributions and all five structure intersections.
The resulting checks are recorded in `data/comparison_verification.json`.

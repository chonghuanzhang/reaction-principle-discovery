# Baseline comparison data

This directory contains the machine-readable experimental records used for the
direct-LLM and literature-selection comparisons in Figure 6.

- `data/llm_records.json` contains 20 unique direct-LLM recommendations and
  their recorded qualitative outcomes.
- `data/literature_baseline_records.json` preserves 21 source records,
  including one duplicated source structure, and identifies the 20 unique
  structures used in the comparison.
- `data/comparison_summary.json` contains the outcome counts, Wilson intervals
  and exact experimental-set intersections used to draw panels a and b.

The three collections do not share an experimental endpoint. The RP-guided
collection uses the reported nonzero numerical UV-response definition. The
direct-LLM records use the final qualitative calls `有产物` and `不反应`, displayed
as `Product` and `No product`, respectively. The literature-selection records
use `有产物` and `trace`, displayed as `Product` and `Trace`; trace is counted as
negative for the displayed fraction.

Figure 6a compares the reported collection-positive fractions: 35/94 for the
RP-guided N/O/S analysis, 4/20 for direct-LLM recommendations and 3/20 for
literature selections. The RP-guided route contributions are 12/38 N-H, 11/36
O-H and 12/20 S-H donors. The observed RP-guided positive fraction is 1.86-fold
and 2.48-fold higher than in the direct-LLM and literature-selection
collections, respectively. These fractions summarize the tested collections
under their respective electrophile and reaction-condition combinations.

Figure 6b separately compares exact structures in the complete ledgers: all
102 unique RP experimental donors in `mapping_108.json`, all 20 direct-LLM
structures and all 20 unique literature structures. Its membership-pattern
counts are 99, 18, 19, 2 and 1 in RP-only, LLM-only, literature-only, RP+LLM
and RP+literature order.

The complete Figure 6 can be rebuilt with:

```bash
python code/figures/build_round5_candidate_figures.py
```

Install `code/requirements-figures.txt` and the system program
`rsvg-convert` (librsvg) before rendering.

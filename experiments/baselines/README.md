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

`Product` is treated as a positive outcome and `Trace` as a negative outcome.
The RP-guided collection uses the nonzero numerical UV-response definition
reported in the manuscript. The direct-LLM and literature-selection records use
the final qualitative calls recorded for those experiments.

The complete Figure 6 can be rebuilt with:

```bash
python code/figures/build_round5_candidate_figures.py
```

Install `code/requirements-figures.txt` and the system program
`rsvg-convert` (librsvg) before rendering.

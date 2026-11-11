# Figure 1 replacement

`build_figure1.py` rebuilds the 3344 × 1882 pixel Figure 1 from the author-supplied `user_reference.png`. It preserves the hub-and-five-block composition, swaps block numerals 4 and 5, removes the LLM icon in block 1, retains the central LLM icon, and replaces inconsistent pale background patches by flat panel fills.

The literature count is 370. The S–H example uses the previously validated trifluoro-N-phenylpropanamide and 4-tert-butylbenzenethiol drawing (`verified_SH_reaction.png`). The six representative donor-fragment drawings are retained from the preceding accepted article figure (`candidate_graphics.png`); this avoids generated atom-label and connectivity artifacts in the supplied raster.

The condition-selection illustration uses actual deposited S–H data. The plate comprises 12 base columns and eight solvent rows from `optimization/figures/source_data/SH_PL40_full_measured_grid_seed5010.csv`. Its qualitative colour bins are UV response < 0.2, 0.2 ≤ UV response < 1.0, and UV response ≥ 1.0. These are UV area-ratio responses, not yields. The paired-seed boxplots use `SH_100_paired_budgets.csv`; boxes are quartiles, centre lines are medians, whiskers extend to the most extreme values within 1.5 interquartile ranges, and points show values beyond the whiskers. Medians are 24 Bayesian evaluations and 48 random evaluations. This is the fixed-grid S–H benchmark; the figure does not establish a prospective N–H/O–H laboratory sequence.

Run with Python and Pillow (the system Arial font paths are specified in the script):

```sh
python build_figure1.py
```

`verification.json` records dimensions, source-derived statistics, qualitative bins, and the output SHA-256 hash. Raster content is a supplied reference rather than a claim of a fully vector-authored figure.

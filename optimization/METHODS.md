# Experimental responses, Bayesian optimization and Figure 5

## Recorded experiments and counting units

`raw/summary_workbook.xlsx` preserves the original experimental summary workbook. Its SHA-256 is `836f5a17429d0ab5198f0f28038e60df0992787cf9b76ed649c4abf7c7047c16`. The larger response workbook is retained as three lossless numbered byte parts; `raw/workbooks_manifest.json` records its original name, 118,056,208-byte size and SHA-256 `46c934b69a5aa74d96c0e7ad0556b705730ddfcc6f58cb6bc0ae5e35b502d21c`. Reassembly concatenates the original bytes without rewriting a worksheet or measurement.

`benchmark/data/source_records_and_oracle.csv` contains 915 source responses with workbook checksum, worksheet, physical Excel row, response-cell address, sample identifier, catalyst and conditions. They comprise three 145-entry catalyst panels and five separate 96-condition grids (435 + 480 = 915). The four principal grids are SH_PL40, NH_PL36, OH_PL37 and OH_PL38, with 96 conditions each and 384 conditions in total. The companion SH_PL39 grid remains available in the historical benchmark.

These are different units from the paper's final 100 candidate molecules, the 108 distinct ordered electrophile–donor input records, the 124 proposed product options and the 100 paired S–H initialization seeds. Historical structure extractions may have 102 distinct donor structures; they do not redefine the author-confirmed final experimental reagent count of 100.

`scripts/check_data.py` reads the workbook's OOXML cell values and compares all 915 exported responses. The S–H condition grid occupies source rows 243–338. The maximum UV response is recorded at row 308, with separate response and matched NMR-yield cells (`AG308` and `AD308`). The NMR cell stores 0.37, displayed as 37%. The fitted-yield column is not 96 independently calibrated NMR yields.

| System | Best relevant recorded grid condition | Response and record | Interpretation |
|---|---|---|---|
| SH_PL40 | CuCl/PPh3/CsOH/2/DCE | UV 3.20446096654275; PL40-W66; matched 37% NMR | Complete measured S–H grid maximum |
| NH_PL36 | Ag2SO4/PPh3/KHCO3/MeCN | MS 0.655297435746774; PL36-W19; selected in batch 3 | Highest selected response in this trajectory |
| OH_PL37 | [Cu(MeCN)4]PF6/K3PO4/DCE | UV 1.15495867768595; PL37-W2; selected in batch 2 | Highest selected response in this trajectory |
| OH_PL38 | NiCl2·DME/DIPEA/DCE | UV 1.44247787610619; PL38-W10; initial batch | Highest selected response in this trajectory |

N–H uses an MS response; S–H and O–H use UV responses. These system-specific analytical signals are not comparable percentage yields. Only the S–H maximum has the matched 37% NMR annotation in these records. The N–H scope condition NaH/DCE differs from the highest selected grid condition KHCO3/MeCN. O–H scope records also include a phosphate/DIO extension, distinct from the grid working conditions.

The source label `CsOH/2` is unresolved: its suffix does not establish half-equivalents, hydration or a hemihydrate. Some SI display records use `CsOH`; this remains a label discrepancy. The source abbreviation `DIO` is not automatically assigned a solvent identity by exact-key matching. The explicitly identified grid solvent is 1,4-dioxane. Component-by-component chemical interpretations, quotations and literature identifiers are in `../experiments/condition_library/`; related-reaction evidence is distinguished from a present-system mechanistic result.

## Frozen Bayesian model and information boundary

Each 12 × 8 grid has 116 feature columns: 12 one-hot base/additive identities, eight one-hot solvent identities and 96 one-hot categorical pairs. Features are centred and divided by their population standard deviation over the unlabelled candidate pool; constant columns use unit scale. The standardized arrays are supplied in `benchmark/data/`. Their ordering is fixed by candidate identifiers.

The implemented finite feature kernel is `K = X X^T`. `model/bo_core.py` evaluates Bayesian linear regression with a normal–inverse-gamma prior, shape 2 and scale 1. There is no extra independent random-intercept variance. The historical protocol's intercept-variance parameter is not used in this kernel implementation. At each update, only revealed responses determine their mean and population SD; a constant observed batch uses unit scale. The posterior is transformed back to the response units. Returned uncertainty is latent-function SD, excluding future-observation noise.

For a selected index set S, the calculation solves `A = I + K_SS`, uses `alpha = A^-1 z` for standardized observed responses z, and computes latent variance from `diag(K) - K_:S A^-1 K_S:` with the conjugate variance scale. The implementation clamps small negative numerical latent variance to zero. Original tests compare this kernel calculation with an independent primal calculation and exercise constant scales and batch-budget boundaries.

The first twelve conditions are sampled uniformly without replacement. Bayesian and random policies share their initial indices for each paired seed. Subsequent Bayesian batches rank remaining conditions by posterior latent mean plus 1.96 latent SD, with seeded random tie-breaking of magnitude 1e-12. Twelve conditions are selected from a frozen posterior before any within-batch response is revealed. Random selection samples the remaining pool without replacement. These are fixed finite-pool policies, rather than a continuous chemical optimization over intermediate base or solvent values.

The offline driver owns the complete response grid and reveals only the selected labels after a batch. The `ObservablePolicy`, posterior and stopping monitor receive selected observations; they never receive the full response vector or a known global maximum. Tests change hidden labels and require the current decision and candidate scores to remain unchanged. Catalyst panels and condition grids are evaluated separately; the code does not fabricate an unmeasured cross-product or an end-to-end catalyst-to-grid transition.

## Paired S–H benchmark

The main S–H analysis uses seeds 5000–5099 on the same measured SH_PL40 grid. Its endpoint is the first completed batch containing the maximum recorded response, with a response tolerance of 1e-12. Initial conditions count toward the budget. The maximum belongs to the evaluator and is unavailable to the selection policies; this exact-hit metric is not an operational laboratory stopping rule.

Median budgets are 24 conditions for Bayesian selection and 48 for random selection. Mean budgets are 26.04 and 51.84. The paired difference is random minus Bayesian budget: its mean is 25.8 conditions, with a 95% percentile bootstrap interval of 20.88–30.72 based on 20,000 paired-seed resamples and seed 20261025. Bayesian selection is earlier in 67 pairs, tied in 30 and later in three. `SH_100_paired_budgets.csv`, `SH_hit_budget_ecdf.csv` and `SH_reanalysis_summary.json` preserve the current calculations. The pointwise discovery-curve bands use the saved paired-seed bootstrap procedure.

These resamples quantify initialization variation conditional on one fixed historical response grid. They do not estimate wet-laboratory reproducibility, prospective savings or generalization to a different chemistry. The broader historical benchmark retains an earlier 2,000-resample, seed-42 calculation for its eight pools. Its protocol and summaries should not be substituted for the current main S–H bootstrap.

Two 100-seed diagnostics use the same S–H seed range. Additive-feature UCB removes the base–solvent interaction features and gives median budget 24, mean 29.28, and 98 hits by budget 48. The full-feature posterior-mean-only policy gives median 24, mean 26.28, and 100 hits. These equal medians do not isolate a unique contribution from the UCB term or the interaction features. The diagnostic functions in `model/diagnostics.py` preserve these calculations.

Repository Table R3 in `../experiments/bo_benchmark/` provides the readable 100-pair table. `benchmark/data/` additionally retains all eight historical pools: 1,600 complete campaigns, 183,000 selected conditions, 15,800 batch-end trajectory records and complete candidate/observation records for the reference decisions. They describe computational repetition on recorded measurements.

## Selected N–H and O–H trajectories

The fixed seeds are 6000 for NH_PL36, 7000 for OH_PL37 and 8000 for OH_PL38, inherited from reference replicate zero without a seed search. Each trajectory reveals five batches of twelve responses, or 60 per system. The other 36 recorded measurements in each grid remain hidden from the policy, posterior updates and stopping calculations. Repository Table R4 in `../experiments/selected_responses/` provides the 180-row SI table; source-linked rows and stopping checks remain in `selections/`.

The stopping tolerance is fixed after the first batch as δ = 0.10 times that batch's response population SD. A check requires at least 36 selected observations, an improvement in best response over the preceding two batches no greater than δ, and a maximum remaining latent UCB no greater than best observed response plus δ. Two consecutive eligible joint passes are required; the earliest possible model stop is 48 conditions. A constant first batch disables this stopping route. If no model stop occurs, the budget limit is 60.

All three trajectories reach `BUDGET_REACHED_CRITERION_NOT_MET`. Both O–H trajectories have their first joint pass only after batch five, leaving no second consecutive pass before the cap. The factor 1.96 is a heuristic acquisition coefficient, not a calibrated coverage guarantee. δ is an operational tolerance in analytical response units, rather than validated analytical precision or a percentage-point yield difference.

`scripts/reproduce_analysis.py` reruns the saved campaign and stopping definitions, checks ordered selected indices and response values, and reconstructs the posterior after each batch from selected labels only. It compares three pools × five batches × 96 candidates = 1,440 saved posterior rows. Unknown responses remain blank in the posterior table.

The selected files identify themselves as computational plans and contain no actual laboratory batch date. Original immutable recommendation timestamps, dated physical executions, response-return timestamps and linked subsequent recommendations are not supplied by these records. Workbook order cannot establish that chronology. No matched prospective N–H/O–H random controls or calibrated per-condition yield series are included. Physical preparation, postprocessing, spectra and product characterization are described in the Supporting Information; response tables cannot replace instrument raw files or sample-linked characterization.

## Figure source data and rendering

| Main or supporting panel | Numerical inputs |
|---|---|
| Main 5a, S–H measured surface and NMR annotation | `SH_PL40_full_measured_grid_seed5010.csv`; original response and NMR cells |
| Main 5b/c, discovery curve and paired savings | `SH_100_paired_budgets.csv`, `SH_hit_budget_ecdf.csv`, `SH_reanalysis_summary.json` |
| Main 5d/e, Bayesian and random selection maps | `SH_seed5010_selection_map_annotations.csv`, `SH_PL40_paired_replay_seed5010.csv` |
| Main 5f–h, selected-response posterior surfaces | Final-batch `NH_OH_posteriors_by_round.csv` rows and `selections/*/selected_conditions.csv` |
| Supplementary Fig. 21, response/posterior/latent SD maps | The same final posterior and selected rows; `condition_key.csv` |
| Supplementary Fig. 22, uncertainty and stopping | `NH_OH_round_diagnostics.csv`; `selections/*/stopping_checks.csv` |
| Supplementary Fig. 23, grid, illustrative replay and diagnostics | Complete S–H grid, seed-5010 replay, `benchmark/data/cumulative_best_trajectories.csv`, `SH_audit_diagnostics.json` |

Table filenames without another directory are in `figures/source_data/`. The supplied artwork uses the internal file stems BO1, BO2 and BO3 for Supplementary Figures 21, 22 and 23. Main figure colours encode zero-anchored within-system relative response: raw response or posterior mean divided by the highest selected measured response. The references are 3.20446096654275, 0.655297435746774, 1.15495867768595 and 1.44247787610619. For S–H all 96 responses are available to the displayed measured surface. Raw heights and printed values retain their analytical units; relative colours do not make the systems equivalent yields. Supporting colour scales remain raw response or latent SD.

Surface smoothing is bounded tensor Hermite interpolation for display. Original categorical vertices are exact, and the interpolation is bounded by local corners. It does not imply a continuous chemical condition or meaningful chemical distance between adjacent categories. Main method colours distinguish Bayesian selection (`#1F6B59`), random selection (`#789C8E`) and ties (`#D6DEDA`). The seed-5010 selection maps are one paired illustration, with budgets 24 and 48; they do not replace the 100-pair aggregate.

`scripts/rebuild_figures.py` runs the drawing functions with relative source paths and an independent output directory. It uses an installed font, defaulting to Matplotlib DejaVu Sans; Poppler PDF previews are optional. The supplied PDF/SVG/PNG files preserve their original rendering, with no proprietary font files redistributed. Exact numerical reproduction is checked separately from artwork byte equality. Figure widths are 180 mm; heights are 265, 207, 175 and 180 mm for the main figure and three supporting figures, respectively. PNGs are 600 dpi.

## Reproduction scope

The documented commands check original response consistency, lossless workbook reassembly, policy information boundaries, posterior algebra, all current S–H campaigns, all selected N–H/O–H values, both diagnostic policies, bootstrap values and figure data. Full historical regeneration also checks all 1,600 campaigns against the saved reference results. Software versions are pinned in `requirements.txt`; the historical environment and BLAS configuration are retained in `benchmark/data/environment.json`.

The available data support these computations on the recorded analytical responses. They do not supply missing calibrated yield measurements, instrument raw files, independent wet-laboratory repeats, original prospective feedback logs or an unambiguous formulation for `CsOH/2`. Source identities, unresolved labels and missing measurements remain explicit.

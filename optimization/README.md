# Experimental responses and Bayesian condition selection

This directory contains the recorded response workbooks, frozen Bayesian model, condition-selection records and source data for Figure 5 and Repository Figures BO1–BO3 (Supplementary Figures 7–9). It is a runnable subsystem: model code, inputs, selection histories and artwork remain together.

The S–H analysis retrospectively compares Bayesian and random selection on a fixed measured 96-condition grid. One hundred paired computational initializations give median first-hit budgets of **24 and 48 conditions**. For O–H, Bayesian condition selection varies 12 catalyst–base formulations and eight solvents. The library includes Cu66/K3PO4 and Ni203/DIPEA as reference formulations, plus ten identities sampled from the other 22 Cu/Ni–base combinations with seed 20261111; every condition has a recorded experimental response. N–H and O–H response records support separate selected-label posterior analyses. The deposited numerical reproduction uses **60 selected responses in five computational batches** from the measured N–H grid and the O–H formulation–solvent library (120 labels in total) to reproduce the posterior fits and stopping diagnostics. These analysis exports are not primary laboratory execution logs. The retrospective BO/random comparison reported in the main analysis concerns S–H.

## Files to inspect

| Directory | Contents |
|---|---|
| `raw/` | Original summary workbook and three lossless byte parts of the larger response workbook, with original names, sizes and checksums |
| `benchmark/data/` | 915 cell-linked source responses; response-free candidate inputs and standardized features; 1,600 historical campaigns, all selected conditions, batch trajectories and reference decisions |
| `model/` | Bayesian posterior, observable-only campaign dependencies, batch/stopping functions, diagnostic policies and model protocol |
| `selections/` | Two analysis-specific selected-condition and stopping-check tables, fixed seeds and protocols; OH_CuNi_96 also contains its 96 candidates, features and construction manifest |
| `figures/source_data/` | Main/SI numerical plot inputs, 960 posterior rows, discovery curves, paired budgets, uncertainty and diagnostic summaries |
| `figures/figures/` | Supplied PDF, SVG and 600-dpi PNG artwork for the main figure and three supporting figures |
| `figure_code/` | Drawing functions that use the relative scientific data paths |
| `scripts/` | Response-cell checks, workbook reassembly, analysis reproduction and figure rendering |

[Figure legends and interpretation](FIGURE_GUIDE.md) provide BO1–BO3 artwork links, complete panel legends, source-data links, condition identities and response scales.

The complete benchmark and selected-response records are available as [Repository Table R3](../experiments/bo_benchmark/) and [Repository Table R4](../experiments/selected_responses/). Component explanations and citations are in [experiments/condition_library](../experiments/condition_library/). The [O–H formulation key](figures/source_data/OH_formulation_key.csv) maps F1–F12 to catalyst and base; [the candidate manifest](selections/OH_CuNi_96/candidate_manifest.json) records the two mandatory references, random sample and physical source cells.

## Reproduce the analysis

Run from `optimization/`, using Python 3.12:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
export PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1
python scripts/check_data.py --output /tmp/reaction-response-check.json
python scripts/configure_current_analysis.py
python scripts/reproduce_analysis.py --output /tmp/reaction-analysis
python benchmark/verify.py benchmark/data
python -m unittest discover -s benchmark -p test_policy.py -v
python -m unittest discover -s model -p test_bo_integrity.py -v
python scripts/rebuild_figures.py --output /tmp/reaction-optimization-figures
```

The response check reads all 915 exported values directly from the supplied workbook's physical cells, verifies the split workbook and checks the twelve artwork exports. The analysis command reruns the current 200 S–H campaigns, two 60-response trajectories, 960 posterior rows, the two diagnostic policies and the current bootstrap. `benchmark/verify.py` checks the saved complete historical dataset, including selection histories and observed-label boundaries.

For full regeneration of the historical eight-pool benchmark:

```bash
python benchmark/replay.py --source-records benchmark/data/source_records_and_oracle.csv --output /tmp/reaction-full-benchmark
python benchmark/verify.py /tmp/reaction-full-benchmark
```

This produces 1,600 campaigns and 183,000 selected rows. These counts are algorithmic repetitions across historical pools, rather than wet-laboratory replicates.

The large workbook is 118,056,208 bytes. Verify its three parts without creating a large file, or reconstruct the exact original byte stream to a new destination:

```bash
python scripts/reassemble_workbook.py
python scripts/reassemble_workbook.py --output /tmp/full_response_workbook.xlsx
```

The figure command uses Matplotlib's DejaVu Sans by default; `--font` accepts another installed family. The supplied artwork preserves its original rendering. Numerical values and categorical vertices are checked independently of typography, because fonts and software can change text placement and file bytes. See [METHODS.md](METHODS.md) for the model, experimental record boundaries and interpretation of the figures.

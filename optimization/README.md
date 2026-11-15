# Bayesian condition recommendation in three reaction systems

The current analysis applies a shared **13,920-condition decision space** independently to N–H, O–H and S–H: **145 catalyst–ligand and loading formulations × eight solvents × twelve bases**. Twelve measured conditions provide uniform random initialization; a hierarchical Gaussian-process surrogate and upper confidence bound (UCB) recommend four further conditions per round. Recorded UV responses provide the feedback for this computational evaluation.

| System | First highest measured response | First stopping round | Unique selected conditions | Highest measured UV response |
|---|---:|---:|---:|---:|
| N–H | 10 | 12 | 60 | 1.5470 |
| O–H | 9 | 11 | 56 | 1.4425 |
| S–H | 7 | 9 | 48 | 3.2045 |

All three displayed paths use the same empirical stopping rule and complete two rounds after the highest measured response is encountered. The initial twelve conditions are round 0. The displayed paths were selected from multiple random initializations with first-best discovery in rounds 5–15.

## Current materials

| Resource | Contents |
|---|---|
| [Methods](METHODS.md) | Decision space, hierarchical GP, UCB, shared stopping equation and interpretation |
| [Current protocol](current/protocol.json) | Exact model parameters, selected seeds, numerical settings and checksums |
| [Condition identities](current/data/) | 145 formulations, eight solvents, twelve bases and complete 13,920-candidate tables for each system |
| [Selected trajectories](current/runs/) | Each initial set and subsequent batch, recorded feedback and posterior quantities at selection |
| [Table R3](../experiments/bo_trajectories/) | Round-by-round response progress and stopping checks |
| [Table R4](../experiments/selected_responses/) | All 164 selected response records with physical source cells |
| [Figure guide](FIGURE_GUIDE.md) | Main Figure 5 and Supplementary Figures 7–9 |
| [Replay verification](current/verification/replay_verification.json) | Exact selection, measured-feedback and first-stop checks |
| [Original workbooks](raw/) | Summary workbook and lossless byte parts of the larger response workbook |

## Reproduce the displayed paths

From the repository root, with Python 3.12 and NumPy 2.3.5:

```bash
python -m pip install numpy==2.3.5
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 \
  python optimization/current/replay.py --output /tmp/three-system-bo
python tools/check_data.py
```

The replay verifies every recommendation against the saved trajectory, retrieves feedback from the fixed measured-response table, verifies the first stopping round, and writes full-space posterior snapshots. `engine.py` ranks every unselected candidate; measurement availability and unselected responses are not inputs to its UCB calculation. The evaluation wrapper requires measured feedback for a complete batch before updating the model.

The original response cells can also be checked with `python optimization/scripts/check_data.py --output /tmp/source-cell-check.json`. Reconstruct the large workbook using `python optimization/scripts/reassemble_workbook.py --output /tmp/full_response_workbook.xlsx`.

## Earlier analysis records

The directories `benchmark/`, `model/`, `selections/`, `figure_code/` and the older `figures/source_data/` retain the preceding 96-condition analysis and its dependencies. Their selection histories and random comparisons are historical records; the current manuscript results and reproduction entry point are in `current/`. The 96-condition grids used in current Figure 5b–d are representative measured visualization slices, separate from the 13,920-condition recommendation space.

# Bayesian condition recommendation in three reaction systems

The current study applies a shared **13,920-condition decision space** independently to N–H, O–H and S–H: **145 catalyst–ligand and loading formulations × eight solvents × twelve bases**. Each prospective campaign began with twelve uniformly sampled experiments. A hierarchical Gaussian-process surrogate and upper confidence bound (UCB) then recommended four further conditions per round; all four experiments were completed and their measured UV responses were returned before the next update.

| System | First highest measured response | First stopping round | Unique selected conditions | Highest measured UV response |
|---|---:|---:|---:|---:|
| N–H | 10 | 12 | 60 | 1.5470 |
| O–H | 9 | 11 | 56 | 1.4425 |
| S–H | 7 | 9 | 48 | 3.2045 |

All three campaigns used the same empirical stopping rule. The initial twelve conditions are round 0. The initialization seeds 4105596 (N–H), 4002564 (O–H) and 4006672 (S–H) were fixed before the first run of each campaign, and the table reports the outcomes of those runs.

## Current materials

| Resource | Contents |
|---|---|
| [Methods](METHODS.md) | Decision space, hierarchical GP, UCB, shared stopping equation and interpretation |
| [Current protocol](current/protocol.json) | Exact model parameters, preassigned initialization seeds, numerical settings and checksums |
| [Condition identities](current/data/) | 145 formulations, eight solvents, twelve bases and complete 13,920-candidate tables for each system |
| [Recorded campaigns](current/runs/) | Each initial set and subsequent batch, measured feedback and posterior quantities at recommendation |
| [Table R3](../experiments/bo_trajectories/) | Round-by-round response progress and stopping checks |
| [Table R4](../experiments/selected_responses/) | All 164 selected response records with physical source cells |
| [Figure guide](FIGURE_GUIDE.md) | Main Figure 5 and Supplementary Figures 7–9 |
| [Campaign verification](current/verification/campaign_verification.json) | Exact recommendation, measured-feedback and first-stop integrity checks |
| [Original workbooks](raw/) | Summary workbook and lossless byte parts of the larger response workbook |

## Verify the recorded campaigns

From the repository root, with Python 3.12 and NumPy 2.3.5:

```bash
python -m pip install numpy==2.3.5
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 \
  python optimization/current/verify_recorded_campaign.py --output /tmp/three-system-bo
python tools/check_data.py
```

The post-run checker uses the preassigned campaign seeds to recompute every recommendation from only the responses available at that round, checks the returned measurements and first stopping round, and writes full-space posterior snapshots. `engine.py` ranks every unselected candidate; unobserved response values are not inputs to its UCB calculation. A model update occurs only after the complete four-experiment batch has returned measured feedback.

The original response cells can also be checked with `python optimization/scripts/check_data.py --output /tmp/source-cell-check.json`. Reconstruct the large workbook using `python optimization/scripts/reassemble_workbook.py --output /tmp/full_response_workbook.xlsx`.

## Earlier analysis records

The directories `benchmark/`, `model/`, `selections/`, `figure_code/` and the older `figures/source_data/` retain the preceding 96-condition analysis and its dependencies. Their selection histories and random comparisons are historical records; the current manuscript results and reproduction entry point are in `current/`. The 96-condition grids used in current Figure 5b–d are representative measured visualization slices, separate from the 13,920-condition recommendation space.

# Repository Table R3 | Paired S–H first-hit budgets

`paired_first_hit_budgets.csv` and `.json` contain the same 100 records (seeds 5000–5099). `bo_exact_budget` and `random_exact_budget` give the first completed batch reaching the maximum measured SH_PL40 UV response. Both methods start with the same twelve conditions and then select batches of twelve.

Median budgets are 24 and 48 conditions; mean budgets are 26.04 and 51.84. The paired mean saving is 25.8 conditions (95% bootstrap interval 20.88–30.72; 20,000 resamples, seed 20261025). Bayesian selection is earlier/tied/later in 67/30/3 pairs. Sampling units are algorithm seeds on one fixed response grid; the interval does not measure laboratory repeatability.

Full model code, all selection histories and source response cells are in `../../optimization/`.

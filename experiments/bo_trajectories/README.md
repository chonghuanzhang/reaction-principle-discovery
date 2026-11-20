# Repository Table R3 | Bayesian campaigns and stopping checks

`trajectory_summary.csv` gives the recorded initialization seeds and outcomes of the N–H, O–H and S–H sequential campaign histories: first-best rounds, stopping rounds, unique condition counts and highest measured UV responses. `round_by_round_stopping.csv` gives all **35 completed-round checks**, including three initializations.

The common rule stops at the first completed round with at least 24 observations and cumulative-best improvement over the preceding two rounds (eight conditions) no larger than 10% of the population standard deviation of the initial twelve responses. The initial standard deviation must exceed 1e−12. N–H, O–H and S–H stop at rounds 12, 11 and 9, with 60, 56 and 48 unique conditions; each has completed two further rounds after first observing its highest measured response.

Each recorded seed is used throughout its reaction system's deposited history. Every saved round assigns four recommendations and four measured responses before the next saved update. [Table R4](../selected_responses/) lists each condition, and [optimization methods](../../optimization/METHODS.md) specify the model, acquisition and post-run integrity verification.

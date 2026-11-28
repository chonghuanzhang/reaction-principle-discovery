# Current three-axis Bayesian analysis

This package records and verifies the sequential N–H, O–H and S–H campaign histories in the shared 13,920-condition decision space. The complete scientific description is in [METHODS.md](../METHODS.md).

- `data/`: 145 formulation identities, eight solvents, twelve bases and complete candidate tables.
- `protocol.json`: GP/UCB parameters, initial-batch definition, shared stopping rule and file hashes.
- `engine.py`: response-conditioned posterior and full-space UCB recommendation.
- `verify_recorded_campaign.py`: validates the twelve recorded round-0 indices for each system and independently recomputes each later full-space recommendation and first stopping check from round-specific measured feedback.
- `runs/`: the recorded sequential trajectory, measured feedback and summary for each reaction system; Table R4 provides the corresponding source-cell response ledger.
- `verification/`: reproduced full-space posterior arrays and numerical verification.
- `figure5/`: current Figure 5 assets, source data and captions.
- `figures/`, `source_data/`: Supplementary Figures 7–9 and their numerical source data.

From the repository root, run `python optimization/current/verify_recorded_campaign.py --output /tmp/three-system-bo`. This post-run integrity check verifies that each recorded initialization contains twelve distinct indices in the 13,920-condition space, then checks the full-space rankings, all 164 recorded responses and the first-best/stopping rounds 10/12, 9/11 and 7/9. Install NumPy 2.3.5 for the verified numerical environment.

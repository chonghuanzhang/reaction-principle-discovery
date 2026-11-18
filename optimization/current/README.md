# Current three-axis Bayesian analysis

This package records and verifies the prospective N–H, O–H and S–H campaigns in the shared 13,920-condition decision space. The complete scientific description is in [METHODS.md](../METHODS.md).

- `data/`: 145 formulation identities, eight solvents, twelve bases, candidate tables and measured-response records.
- `protocol.json`: GP/UCB parameters, random seeds, shared stopping rule and file hashes.
- `engine.py`: response-conditioned posterior and full-space UCB recommendation.
- `verify_recorded_campaign.py`: independently reconstructs each recorded recommendation and first stopping check from the preassigned seed and round-specific measured feedback.
- `runs/`: the single fixed-seed campaign trajectory and summary for each reaction system.
- `verification/`: reproduced full-space posterior arrays and numerical verification.
- `figure5/`: current Figure 5, source data, caption and portable builder.
- `figures/`, `source_data/`, `build_supplementary.py`: Supplementary Figures 7–9 and their reconstruction.

From the repository root, run `python optimization/current/verify_recorded_campaign.py --output /tmp/three-system-bo`. This post-run integrity check verifies all 164 recorded responses and the first-best/stopping rounds 10/12, 9/11 and 7/9 using the preassigned campaign seeds. Install NumPy 2.3.5 for the verified numerical environment. The figure builders additionally use Matplotlib and Pillow.

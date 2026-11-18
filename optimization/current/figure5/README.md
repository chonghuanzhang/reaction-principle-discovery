# Figure 5 reproduction

Run `python optimization/current/figure5/verify_source_data.py` and `python optimization/current/figure5/build_figure5.py` from the repository root. No network calls, local workspace paths or model-provider access are required.

Panel a is computed from the current system trajectories, with all 164 measured responses checked against the 13,920-condition candidate tables. Bars show batch means and whiskers show the observed minimum–maximum range among distinct conditions.

Panels b–d contain 288 measured UV-response values in three representative 12 × 8 grids. Their individual colour bars normalize each grid by its own maximum. The N–H grid uses Ag₂SO₄/PPh₃ and does not contain the full-space AgF/PPh₃ maximum. `formulation_key.csv` defines all rows.

Panel e reads frozen N–H posterior snapshots that match the recorded fixed-seed campaign. The saved projection weights define a response-blind coordinate from catalyst–ligand, solvent and base identities, centered and scaled using the first 24 displayed conditions. The final set includes those 24 conditions plus the four conditions from rounds 10 and 12. Coordinate rank is fixed across all six panels. Every posterior uses all observations available at its round. Bands are ±2 latent posterior standard deviations and points sit at posterior means.

The verified rendering environment is Python 3.7.0, NumPy 1.16.2, Matplotlib 3.1.1, SciPy 1.4.1 and Pillow 7.0.0 with Arial installed. Numeric node data remain available as CSV/NPZ regardless of rendering-library versions. Figures are written under `figures/`; source and output hashes are recorded in `verification.json`.

The figure builder only renders the saved snapshots. Verifying model predictions is a separate step: run `python optimization/current/verify_recorded_campaign.py --output build/current_campaign_verification` with the current optimization environment documented in `optimization/README.md` and `code/README.md`. This check reconstructs the recorded campaign from its preassigned seed and round-specific measured feedback. The older rendering environment above is recorded for exact artwork reproduction and is not the campaign-verification dependency specification.

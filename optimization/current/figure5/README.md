# Figure 5 source data and verification

Run `python optimization/current/figure5/verify_source_data.py` from the repository root to check the finished Figure 5 assets and their numerical source data. No network calls, local workspace paths or model-provider access are required.

Panel a is computed from the current system trajectories, with all 164 measured responses checked against the 13,920-condition candidate tables. Bars show batch means and whiskers show the observed minimum–maximum range among distinct conditions.

Panels b–d contain 288 measured UV-response values in three representative 12 × 8 grids. Their individual colour bars normalize each grid by its own maximum. The N–H grid uses Ag₂SO₄/PPh₃ and does not contain the full-space AgF/PPh₃ maximum. `formulation_key.csv` defines all rows.

Panel e uses saved N–H posterior snapshots from the recorded campaign. The saved projection weights define a response-blind coordinate from catalyst–ligand, solvent and base identities, centered and scaled using the first 24 displayed conditions. The final set includes those 24 conditions plus the four conditions from rounds 10 and 12. Coordinate rank is unchanged across all six panels. Every posterior uses all observations available at its round. Bands are ±2 latent posterior standard deviations and points sit at posterior means.

Numeric node data remain available as CSV/NPZ, and finished figures are retained under `figures/`; source and output hashes are recorded in `verification.json`.

Verify the campaign calculations separately with `python optimization/current/verify_recorded_campaign.py --output /tmp/three-system-bo` using the current optimization environment documented in `optimization/README.md` and `code/README.md`. This check validates the recorded full-space initial batch and recomputes later full-space rankings from round-specific measured feedback.

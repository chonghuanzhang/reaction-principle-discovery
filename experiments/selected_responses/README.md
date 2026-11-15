# Repository Table R4 | Selected response records

`selected_responses.csv` and `.json` contain **164 unique selected conditions**: N–H 60, O–H 56 and S–H 48. Round 0 contains twelve uniformly sampled initial conditions per system; each subsequent round contains four UCB recommendations. These records supply the measured feedback for the displayed Bayesian trajectories in the shared 13,920-condition decision space.

Every row identifies the catalyst–ligand formulation and loading, solvent, base, UV response, recommendation round, posterior quantities at selection and physical source cell. The three paths first encounter their highest measured responses in rounds 10, 9 and 7, and stop in rounds 12, 11 and 9, respectively. [Table R3](../bo_trajectories/) gives every stopping check; [the current protocol](../../optimization/current/protocol.json) gives parameters and seeds.

UV signals are compared within the same substrate–product pair and analytical conditions. The author-confirmed base spelling is CsOH. Original workbooks retain their original labels; `archive_96_condition_analysis/` preserves the previous selected-response export.

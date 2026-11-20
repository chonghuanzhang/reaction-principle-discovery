# Repository Table R4 | Selected response records

`selected_responses.csv` and `.json` contain **164 unique initial or recommended conditions** from the three recorded sequential campaign histories: N–H 60, O–H 56 and S–H 48. Round 0 contains twelve uniformly sampled initial conditions per system; each subsequent round records four UCB recommendations and four responses assigned before the next saved model update. One recorded initialization seed is used throughout each system's deposited history.

Every row identifies the catalyst–ligand formulation and loading, solvent, base, UV response, recommendation round, posterior quantities at selection and physical source cell. The three paths first encounter their highest measured responses in rounds 10, 9 and 7, and stop in rounds 12, 11 and 9, respectively. [Table R3](../bo_trajectories/) gives every stopping check; [the current protocol](../../optimization/current/protocol.json) gives parameters and seeds.

UV signals are compared within the same substrate–product pair and analytical conditions. The author-confirmed base spelling is CsOH. Original workbooks retain their original labels; `archive_96_condition_analysis/` preserves the previous selected-response export.

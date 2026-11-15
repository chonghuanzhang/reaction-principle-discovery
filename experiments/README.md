# Experimental condition and response tables

These tables connect the Supporting Information to searchable condition identities, measured responses and Bayesian recommendation records.

| Resource | Contents |
|---|---|
| [Condition library](condition_library/) | 145 catalyst–ligand and loading formulations, twelve bases and eight solvents, with component evidence |
| [Table R3](bo_trajectories/) | Three-system trajectory summaries and every common stopping check |
| [Table R4](selected_responses/) | 164 selected response records with recommendation rounds and source cells |
| [Current optimization package](../optimization/current/) | Complete decision spaces, model, exact parameters and portable replay |

Each reaction system uses the same **145 × 8 × 12 = 13,920-condition decision space**. Models are fitted independently to N–H, O–H and S–H responses. Twelve initial conditions are followed by four recommendations per round. The displayed paths stop at rounds 12, 11 and 9 after 60, 56 and 48 unique conditions.

The measured 96-condition grids in Figure 5b–d are representative visualization slices with system-specific formulation keys. They are separate from the recommendation space. UV response must be compared within the same substrate–product pair under consistent analytical conditions; it is not a cross-system yield scale.

The `bo_benchmark/` directory retains the earlier S–H comparison as an archival record. Current methods and results are described in [optimization](../optimization/).

# Figure 5 and supplementary Bayesian diagnostics

The current figures use the three-system 13,920-condition analysis. The 96-condition panels are representative measured visualization grids.

## Main Figure 5

[PNG](current/figure5/figures/Figure_5_composite.png) · [PDF](current/figure5/figures/Figure_5_composite.pdf) · [Source data](current/figure5/source_data/)

Figure 5 | Bayesian condition optimization and representative experimental response landscapes.

a, Recorded optimization trajectories for the N–H, O–H and S–H systems in the shared decision space of 13,920 conditions. Each trajectory contains 12 initial conditions followed by batches of four conditions. Bars show the mean measured UV response within each batch, and whiskers span the minimum to maximum responses among its distinct conditions. Step curves show the highest response obtained up to each round; stars mark the first evaluation of the highest-response condition in each trajectory, and squares mark stopping. Round 0 denotes initialization. N–H, O–H and S–H reached their highest recorded responses in rounds 10, 9 and 7 and stopped in rounds 12, 11 and 9, after 60, 56 and 48 evaluations, respectively. UV responses are interpreted within each fixed substrate pair under consistent analytical conditions; absolute signals from different substrate/product systems are not directly comparable.

b–d, Representative 12 × 8 experimental response grids for N–H (b), O–H (c) and S–H (d), assembled from existing measured conditions within the decision space. Each grid combines 12 formulations with eight solvents. N–H and S–H use Ag₂SO₄/PPh₃ and CuCl/PPh₃, respectively, with 12 bases; O–H uses 12 Cu- or Ni-catalyst–base formulations. Surface heights give measured UV responses; colour is normalized to the maximum within each displayed grid, with a separate 0–1 colour bar in each panel. Grey points denote measured conditions, and stars identify the highest response within each grid. Smooth surfaces connect the 96 categorical values for visualization. Formulation and solvent identities are provided in the source data.

e, Evolution of the N–H Gaussian-process posterior after initialization and rounds 1, 2, 3, 10 and 12, arranged from left to right across the two rows. The same 32 conditions are displayed on a fixed, rank-scaled joint coordinate incorporating catalyst–ligand, solvent and base identities. Each posterior uses all observations assigned through that round: 12, 16, 20, 24, 52 and 60, respectively. Lines denote posterior means, shaded bands indicate ±2 latent posterior standard deviations, and dashed outlines show the band from the immediately preceding round. The bands represent latent model uncertainty, not experimental error, and are not calibrated coverage intervals over the 13,920-condition space. Blue points show posterior means at evaluated conditions; orange points identify the four conditions assigned to the indicated round. Stars identify the condition first recorded in round 10 that gave the highest N–H response. Curves connect discrete condition coordinates for display.


The N–H surface fixes Ag₂SO₄/PPh₃ and has a grid-local maximum of 1.03780376396515 at NaH/DCE. The N–H optimization trajectory instead reaches the full measured-record maximum at AgF/PPh₃/K₂CO₃/DCE (1.54697139066581). Each of panels b–d has its own colour bar; colours are normalized to the maximum of that panel’s measured grid, while surface heights retain raw UV-response units.

<a id="bo1"></a>

## Supplementary Figure 7

[PNG](current/figures/Supplementary_Figure_7.png) · [PDF](current/figures/Supplementary_Figure_7.pdf)

Supplementary Fig. 7 | Measured responses along the recorded Bayesian optimization campaign histories. a–c, N–H, O–H and S–H, respectively. Each vertical line is one initial or recommended condition and its recorded UV response; horizontal offsets within a round separate distinct conditions. Round 0 contains the 12 recorded initial conditions, and each subsequent round contains four conditions. Steps show cumulative best response, stars mark the first highest measured response and open squares mark the first stopping round. The histories contain 60, 56 and 48 unique conditions, respectively. Response magnitudes are interpreted within each substrate–product pair. The round-0 indices are retained in the deposited trajectories.

<a id="bo2"></a>

## Supplementary Figure 8

[PNG](current/figures/Supplementary_Figure_8.png) · [PDF](current/figures/Supplementary_Figure_8.pdf)

Supplementary Fig. 8 | Common empirical stopping rule in the three reaction systems. a–c, N–H, O–H and S–H, respectively. Lines show the cumulative-best UV-response gain across the last two rounds, Δr = br − br−2. Dashed horizontal lines show δ = 0.10 times the population standard deviation of the initial 12 responses. Grey shading indicates rounds before the minimum 24 observations required for stopping. Open squares identify the first eligible round with Δr ≤ δ: round 12 for N–H, round 11 for O–H and round 9 for S–H. All three have zero two-round gain at stopping. UCB is used for recommendation, not for this stopping calculation.

<a id="bo3"></a>

## Supplementary Figure 9

[PNG](current/figures/Supplementary_Figure_9.png) · [PDF](current/figures/Supplementary_Figure_9.pdf)

Supplementary Fig. 9 | Latent posterior uncertainty during sequential recommendation. a–c, N–H, O–H and S–H, respectively. Coloured lines show mean latent posterior standard deviation over the same experimentally evaluated condition identities at every round (60, 56 and 48, respectively); grey dashed lines show the mean over the full 13,920-condition decision space at every round. Vertical lines identify the round that first reaches the highest measured response. Each posterior uses only the responses available by that round. The response normalization and conjugate variance-scale update are recomputed with those observations, so uncertainty in raw response units need not decrease monotonically. These averages describe the same candidate sets at each round and exclude future-observation noise.

## Source data and verification

Run `python optimization/current/verify_recorded_campaign.py --output /tmp/three-system-bo` to verify the recorded campaigns, full-space recommendation rankings and posterior arrays. The finished figures and their numerical source tables are retained under `current/figure5/` and `current/`.

The [methods](METHODS.md), [current protocol](current/protocol.json) and [source tables](current/source_data/) identify the numerical meaning of each panel.

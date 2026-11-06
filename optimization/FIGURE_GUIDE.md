# Bayesian optimization figure legends and interpretation

The three supporting figures below accompany main Figure 5. They separate selected analytical responses, posterior estimates, uncertainty diagnostics and the retrospective sulfur benchmark. Repository Figs. BO1–BO3 correspond to Supplementary Figures 7–9, respectively, and remain stable repository figure names. Each page link opens the supplied artwork; vector PDF and SVG versions are available beside each PNG.

The N–H and O–H trajectories are computational reconstructions using 60 selected responses from each measured 96-condition grid. S–H compares selection policies on one fixed measured grid. MS and UV responses retain their original units; they do not provide comparable percentage yields across systems.

| Figure | Artwork | Numerical records |
|---|---|---|
| Supplementary Fig. 7 / Repository Fig. BO1 Selected responses, posterior landscapes and uncertainty | [PNG](figures/figures/SI_BO1_posterior_landscapes.png), [PDF](figures/figures/SI_BO1_posterior_landscapes.pdf), [SVG](figures/figures/SI_BO1_posterior_landscapes.svg) | [Posteriors by round](figures/source_data/NH_OH_posteriors_by_round.csv); [selected conditions](selections/); [condition identities](figures/source_data/condition_key.csv) |
| Supplementary Fig. 8 / Repository Fig. BO2 Latent uncertainty and stopping diagnostics | [PNG](figures/figures/SI_BO2_uncertainty_stopping.png), [PDF](figures/figures/SI_BO2_uncertainty_stopping.pdf), [SVG](figures/figures/SI_BO2_uncertainty_stopping.svg) | [Round diagnostics](figures/source_data/NH_OH_round_diagnostics.csv); [pool-specific stopping checks](selections/); [stopping protocol](selections/stopping_protocol.json) |
| Supplementary Fig. 9 / Repository Fig. BO3 Measured sulfur landscape and replay diagnostics | [PNG](figures/figures/SI_BO3_SH_replay_diagnostics.png), [PDF](figures/figures/SI_BO3_SH_replay_diagnostics.pdf), [SVG](figures/figures/SI_BO3_SH_replay_diagnostics.svg) | [Measured grid](figures/source_data/SH_PL40_full_measured_grid_seed5010.csv); [paired replay](figures/source_data/SH_PL40_paired_replay_seed5010.csv); [100 paired budgets](figures/source_data/SH_100_paired_budgets.csv); [diagnostic summaries](figures/source_data/SH_audit_diagnostics.json) |

## BO1

**Supplementary Figure 7 / Repository Figure BO1.** Selected responses, posterior landscapes and uncertainty across three reconstructed Bayesian trajectories. Rows correspond to N–H with Ag2SO4/PPh3 (a–c), O–H with [Cu(MeCN)4]PF6 (d–f) and O–H with NiCl2·DME (g–i).

a,d,g, Archived experimental responses for the 60 conditions selected in five rounds of 12; grey cells denote the other 36 conditions, whose recorded responses were withheld from the illustrated trajectory. The original screens contain measurements for all 96 combinations; selected membership describes the computational replay.

b,e,h, Final posterior mean over all 96 candidates, conditioned only on the 60 selected responses. Filled points show selected archived responses, open points show the model mean at the other candidates, and stars mark the highest selected response. N–H is plotted in MS response units; O–H is plotted in UV response units. Posterior surfaces use bounded tensor-product cubic Hermite interpolation between category vertices, preserving the saved model values at every vertex. Interpolated locations do not represent measured reactions or a continuous chemical coordinate.

c,f,i, Latent posterior standard deviation after round 5; numerals identify the selection round (1–5), while cells without numerals were not selected. Filled/open points, stars, grey withheld-response cells and round numerals are keyed in the shared legends, and each response/SD scale has its own colour bar. Latent SD describes model uncertainty and excludes future-observation noise; it is neither experimental error nor a calibrated predictive interval. Stars in these systems have no matched numerical NMR yield in the checked workbook and current SI, so no percentage yield is assigned.

## BO2

**Supplementary Figure 8 / Repository Figure BO2.** Latent uncertainty and stopping diagnostics for the archived N–H and O–H selections. Rows correspond to N–H/Ag2SO4/PPh3 (NH_PL36, seed 6000; a,b), O–H/[Cu(MeCN)4]PF6 (OH_PL37, seed 7000; c,d), and O–H/NiCl2·DME (OH_PL38, seed 8000; e,f). Each round reveals 12 selected responses, up to a budget of 60 conditions.

Left, mean latent posterior standard deviation across the same 96 candidate identities (solid purple) and across the currently unselected candidates (dashed grey). The latter subset changes after each round; its means do not describe a fixed population. Posterior uncertainty need not decrease monotonically.

Right, the largest latent upper confidence bound among unselected candidates minus the best selected response, with the fixed tolerance delta shown by the dashed line. UCB is the posterior mean plus 1.96 latent standard deviations. Gold squares mark the 60-condition budget limit.

The tolerance equals 0.10 times the first-batch response population standard deviation. The stopping test becomes eligible at 36 selected conditions and requires both a two-round improvement no greater than delta and a remaining UCB no greater than the best selected response plus delta, in two consecutive checks. A constant first batch disables this stopping route. All three plans reach the budget limit without satisfying the rule; the two O–H systems have their first joint pass only at round 5. Posterior calculations use only the 60 selected responses per system, with no unselected response labels. These are latent-function uncertainties, excluding future-observation noise; 1.96 is a heuristic acquisition coefficient, not a calibrated 95% coverage guarantee. Values retain system-specific analytical MS or UV response units and are not percentage yields. The archived computational selections are shown descriptively; dated prospective laboratory proposal, execution and feedback linkage remains to be associated.

## BO3

**Supplementary Figure 9 / Repository Figure BO3.** Measured sulfur response landscape and retrospective replay diagnostics.

a, The complete 96-condition SH_PL40 UV-response matrix, with the original twelve base/additive entries and eight solvent identities. Digits give the Bayesian selection round in the illustrative seed-5010 replay; the gold outline marks the highest recorded response, at CsOH/2 in DCE. CsOH/2 is retained as an unresolved source label. Each cell is a discrete measured condition, and no intermediate chemical conditions are implied.

b, Best measured response at each completed batch for the single paired replay with seed 5010; BO and random sampling share their first 12 conditions and then select 12 conditions per round. This one-run illustration does not replace the 100-run aggregate.

c, Mean best response across 100 paired computational runs, seeds 5000–5099, on the same measured grid. Shading gives the empirical interquartile range across algorithm seeds, not a confidence interval. Only batch-end results are shown.

d, Median first-hit budgets for the full interaction-feature UCB policy, the same model using posterior mean alone, an additive-feature UCB policy with no interaction terms, and random sampling; these are 24, 24, 24 and 48 conditions. Each diagnostic uses the same seed range; no error bars are inferred from the saved diagnostic summaries. The exact-hit endpoint is the first completed batch reaching the maximum archived response, with a response tolerance of 1e-12. The full grid maximum belongs to the evaluator and is unavailable to the selection policies; it is not an operational stopping rule. The results quantify initialization variation conditional on one fixed historical response grid and do not measure laboratory repeatability or prospective experimental savings. Response is the recorded combined two-peak UV signal, not calibrated yield. The equal diagnostic medians do not isolate a unique contribution from the UCB uncertainty term or interaction features.

## Condition identities and response scales

Condition key for main Fig. 5 and BO1–BO3: solvent S1–S8 = n-hexane, DCE, MeCN, THF, 1,4-dioxane, toluene, HFIP and DMF. Base/additive B1–B12 = K3PO4, DIPEA, KHCO3, NaHCO3, K2CO3, K2HPO4, NaOH, Na3PO4·12H2O, CsOH/2, CsF, NaH and KOtBu. CsOH/2 is retained verbatim as an unresolved source label. Adjacent categorical positions have no assumed chemical-distance interpretation.

The N–H and O–H posterior means are fitted only to the 60 selected responses in each reconstructed trajectory, while the original experimental screens each contain measurements at all 96 candidate conditions. Categorical indices identify discrete combinations; smoothing is used only to display saved category vertices and does not imply continuous chemical coordinates. For main Fig. 5, surface and matrix colours share a zero-anchored relative-response scale obtained by dividing response or posterior mean by the within-system highest selected measured response (all 96 measured responses for S–H). The reference responses are 3.20446096654275 (S–H), 0.655297435746774 (N–H), 1.15495867768595 (O–H/Cu) and 1.44247787610619 (O–H/Ni). Raw heights and numerical labels retain their original response values. Repository Figs. BO1–BO3 retain separate raw response and latent-standard-deviation colour scales.

The response normalization values are also recorded in [Main_shared_color_scale.csv](figures/source_data/Main_shared_color_scale.csv). The [methods](METHODS.md) specify the response sources, posterior, acquisition policy, stopping rule, bootstrap and rendering. The [README](README.md) gives reproduction commands.

# Three-system Bayesian condition recommendation

## Decision space and measured responses

Following the Gaussian-process-based reaction-condition recommendation approach of Gao et al. (*Chemical Science*, 2026, DOI [10.1039/d6sc05561c](https://doi.org/10.1039/d6sc05561c); [L361](../literature/sources/L361.md)), the present work applies sequential condition recommendation to N–H, O–H and S–H systems. Before experimentation, literature searches across these systems informed a shared decision space of **145 catalyst–ligand and loading formulations, eight solvents and twelve bases**, giving **13,920 candidate conditions per system**. The [formulation register](current/data/catalyst_ligand_formulations.csv), [solvent register](current/data/solvents.csv) and [base register](current/data/bases.csv) supply the identities and loadings. Related chemical evidence is in the [literature catalog](../literature/) and [component library](../experiments/condition_library/).

Catalyst–ligand formulation is one categorical factor: the recorded catalyst identity, its loading, any extra ligand and its loading jointly define an entry. Pre-coordinated ligands remain part of catalyst identity. Solvent and base are separate categorical factors. Each candidate table records the complete recipe, including the fixed temperature, time, volume and base loading. The index is `96*catalyst_index + 12*solvent_index + base_index`; each index starts at zero.

Every row in the three current 13,920-condition candidate tables and all 164 selected trajectory-condition rows records a solvent volume of **500 µL**. This is the BO and trajectory layer. The source-screen procedure uses 250 µL. The numerical scope records used for the reported N/O/S analysis are predominantly 500 µL; three legacy N-H rows, AP001–AP003, retain their original 250 µL source-screen scale. The source-screen and BO/scope volumes are therefore reported as distinct experimental layers.

The deposited files represent three independent sequential laboratory campaign histories. Source records are linked by worksheet, Excel row, response cell and sample identifier. The [source-conflict table](current/data/source_conflicts.csv) retains five distinct source records that share encoded condition keys. For deterministic BO reconstruction, complete-condition-grid measurements take precedence over catalyst-panel entries; responses are neither averaged nor chosen by magnitude. The raw workbooks remain unchanged.

The author confirmed that the N–H source heading `MS_Response` denotes **UV response**, and that the base label `CsOH/2` denotes **CsOH**. Current display labels use these corrections. UV response depends on the substrate/product pair and analytical conditions. Comparisons therefore concern conditions within the same reaction system; raw signals across N–H, O–H and S–H are not comparable yields. The separately recorded 37% NMR yield at the indicated sulfur condition remains an independent analytical measurement.

## Initialization, surrogate and batch acquisition

The deposited protocol represents each system as starting with twelve conditions sampled uniformly without replacement from the complete 13,920-condition decision space. The twelve responses initialize the surrogate. In the recorded history, four candidates are recommended simultaneously at every subsequent round and the model is updated after the complete four-response batch. This small batch size is suited to conventional-scale experiments.

For categorical factors C (catalyst–ligand formulation), S (solvent) and B (base), the kernel contains the three main effects, three pairwise interactions and an independent complete-condition effect:

```text
k(x,x′) = (1−ρ) Σ_j w_j I_j(x,x′) + 6ρ I[x=x′]
j = C, S, B, C:S, C:B, S:B;     Σ_j w_j = 6
```

`I_j` equals one when the indicated factor or pair of factors matches and zero otherwise. Thus `k(x,x)=6`. At each fit, selected UV responses are centered by their current mean and divided by their population standard deviation. If that standard deviation is at most 1e−12, the normalization scale is one.

Let z be the standardized response vector, K the observed-condition kernel matrix, and k the covariance vector between a query and the observed conditions. The hierarchical GP uses unit observation-noise variance on the standardized scale and an inverse-gamma variance-scale prior with shape 2 and scale 1. Its conjugate update is:

```text
A = I + K
a = 2 + n/2
b = 1 + 0.5 zᵀ A⁻¹ z
μ(x) = response_mean + response_SD kᵀ A⁻¹ z
s²(x) = response_SD² [b/(a−1)] [6 − kᵀ A⁻¹ k]
```

Here s is the latent posterior standard deviation. The plotted ±2s bands show model uncertainty in the latent response; they are not experimental-error bars, are not assigned a calibrated coverage probability and have not been validated as calibrated intervals over the full 13,920-condition space. Kernel equivalence classes are compressed for computation and expanded to all 13,920 candidates before acquisition; direct full-space verification gives the same posterior.

| System | Weights C,S,B,CS,CB,SB | ρ | UCB multiplier β |
|---|---|---:|---:|
| N–H | 1, 1, 1, 1, 1, 1 | 0.95 | 0.5 |
| O–H | 1.5, 0.3, 0.3, 1.8, 1.8, 0.3 | 0.90 | 1.0 |
| S–H | 1.5, 0.3, 0.3, 1.8, 1.8, 0.3 | 0.90 | 1.96 |

The UCB score is `μ(x)+βs(x)`. The four largest scores among all unselected candidates form the next batch. NumPy PCG64 draws 13,920 uniform jitter values scaled by 1e−12 for stable tie-breaking at each round. No within-batch pseudo-observations are inserted. In the deposited history and replay, the recommendation function receives only responses assigned to preceding rounds, and each batch is assimilated as four responses.

## Common stopping rule and campaign outcomes

At each completed round, let n be the number of selected unique conditions, M(n) their cumulative best measured response and s₀ the population standard deviation of the initial twelve responses. The same rule applies to all three systems:

```text
stop at the first completed round for which
n ≥ 24, s₀ > 1e−12, and M(n) − M(n−8) ≤ 0.1 s₀.
```

Eight observations correspond to two complete four-condition rounds. The threshold scales with each system's initial response dispersion; the multiplier, minimum observation count and patience are shared. UCB selects candidates and is not a stopping statistic.

The twelve round-0 indices for each system are retained in the deposited trajectory. The model parameters, initial-batch definition and numerical protocol are deposited in [protocol.json](current/protocol.json).

| System | First-best round | First stopping round | Conditions | 0.1s₀ | Highest measured-response condition | UV response |
|---|---:|---:|---:|---:|---|---:|
| N–H | 10 | 12 | 60 | 0.0472504770 | AgF/PPh₃, K₂CO₃, DCE | 1.54697139066581 |
| O–H | 9 | 11 | 56 | 0.0054109553 | NiCl₂·DME, DIPEA, DCE | 1.44247787610619 |
| S–H | 7 | 9 | 48 | 0.0187321554 | CuCl/PPh₃, CsOH, DCE | 3.20446096654275 |

These are the highest measured-response settings reached in the recorded BO histories. The Table 1/scope settings are N-H Ag₂SO₄/PPh₃/NaH/DCE, O-H NiCl₂·DME/Na₃PO₄·12H₂O/DCE and S-H CuCl/PPh₃/CsOH/DCE. Thus the N-H and O-H scope settings differ from their BO highest-response settings, whereas the S-H setting matches.

Each campaign happened to complete two further rounds after reaching its highest measured response and stopped at the first qualifying check. [Table R3](../experiments/bo_trajectories/) gives every round and stopping check; [Table R4](../experiments/selected_responses/) gives all 164 initial or recommended conditions and their source cells.

The earlier *Chemical Science* study compared Bayesian selection with random and stratified-random screening and showed enrichment of high-yield conditions. The present study focuses on transferring that optimization framework to the three heteroatom systems and therefore does not repeat a random-screening baseline. The current kernel, UCB acquisition and four-condition batch size are specified above.

## Figure 5 and supporting diagnostics

Figure 5a shows the three recorded sequential campaign histories. Figure 5b–d show representative measured 12×8 formulation–solvent grids to visualize response variation. These grids are separate from the 13,920-condition decision space. N–H fixes Ag₂SO₄/PPh₃, S–H fixes CuCl/PPh₃, and the O–H grid contains its twelve specified Cu/Ni–base formulations. The N–H grid-local maximum therefore differs from the AgF-containing highest response reached in panel a. Surface heights are measured UV responses, connected by bounded interpolation; each panel has its own colour bar for UV response normalized to that grid's maximum. Interpolation adds no measured conditions.

Figure 5e uses N–H posterior snapshots at initialization and rounds 1, 2, 3, 10 and 12. A fixed set of 32 displayed conditions is ordered by a three-factor projection. All observations available at the stated round are used in the model. Markers lie on posterior means at evaluated conditions; bands span ±2 latent posterior SD. The dashed curve is the previous actual round's posterior. Complete legends and supplementary diagnostics are in the [figure guide](FIGURE_GUIDE.md).

## Reproducibility

[verify_recorded_campaign.py](current/verify_recorded_campaign.py) performs a post-run integrity check of the recorded full-space initial batches, every later recommendation, measured feedback value, posterior and first stopping decision. It also compares compressed and direct full-space posterior calculations. The [saved verification](current/verification/campaign_verification.json) reports the results. [Raw source workbooks](raw/) and the earlier `benchmark/` and `selections/` records retain their provenance; they are not the current recommendation protocol.

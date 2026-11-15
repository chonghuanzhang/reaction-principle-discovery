# Condition-library components

The shared decision space combines **145 catalyst–ligand and loading formulations, eight solvents and twelve bases**, giving 13,920 candidate conditions for each of N–H, O–H and S–H. The [formulation register](../../optimization/current/data/catalyst_ligand_formulations.csv) identifies catalyst names, CAS identifiers, loadings and extra ligands; the [solvent](../../optimization/current/data/solvents.csv) and [base](../../optimization/current/data/bases.csv) registers give the other two factor levels. The [complete candidate tables](../../optimization/current/data/) connect measured records to source worksheet cells.

The component pages below document chemical roles and supporting references for the twelve bases and eight solvents. The [literature catalog](../../literature/) supplies the broader N/O/S reaction evidence. For display, Figure 5b–d uses separate measured 12×8 formulation–solvent grids; those system-specific formulation keys are not the full Bayesian decision space.

`components.csv` has one typed record per component: name, type, chemical role, source, evidence level and limits. `components.json` contains the same twenty records plus all 149 original scientific paragraphs, including source quotations, evidence identifiers and locators. Individual pages below provide a readable explanation.

| Component | Type | Role | Evidence level |
|---|---|---|---|
| [K3PO4 — tripotassium phosphate](components/potassium-phosphate.md) | base/additive | inorganic phosphate; basicity/counterion dimension | exact component in related literature or seed |
| [DIPEA — N,N-diisopropylethylamine](components/dipea.md) | base/additive | soluble hindered amine base | exact component in related literature or seed |
| [KHCO3 — potassium hydrogencarbonate](components/potassium-bicarbonate.md) | base/additive | mild bicarbonate base | exact component in related literature or seed |
| [NaHCO3 — sodium hydrogencarbonate](components/sodium-bicarbonate.md) | base/additive | bicarbonate/counterion contrast | exact component in related literature or seed |
| [K2CO3 — potassium carbonate](components/potassium-carbonate.md) | base/additive | carbonate base | exact component in related literature or seed |
| [K2HPO4 — dipotassium hydrogen phosphate](components/dipotassium-hydrogen-phosphate.md) | base/additive | hydrogen phosphate/acid-base buffer dimension | exact component in related literature or seed |
| [NaOH — sodium hydroxide](components/sodium-hydroxide.md) | base/additive | hydroxide donor/catalyst-speciation test | exact component in related literature or seed |
| [Na3PO4·12H2O — trisodium phosphate dodecahydrate](components/trisodium-phosphate-dodecahydrate.md) | base/additive | phosphate plus counterion/hydration dimension | family only exact dodecahydrate not established |
| [CsOH — cesium hydroxide](components/cesium-hydroxide.md) | base/additive | cesium hydroxide base | cesium hydroxide in related literature |
| [CsF — cesium fluoride](components/cesium-fluoride.md) | base/additive | fluoride activity/latent-donor activation | exact component in related literature or seed |
| [NaH — sodium hydride](components/sodium-hydride.md) | base/additive | strong deprotonation and precursor-generation dimension | exact component in related literature or seed |
| [KOtBu — potassium tert-butoxide](components/potassium-tert-butoxide.md) | base/additive | strong alkoxide base | exact component in related literature or seed |
| [n-hexane — n-hexane](components/n-hexane.md) | solvent | nonpolar hydrocarbon medium | exact component in related literature or seed |
| [DCE — 1,2-dichloroethane](components/dce.md) | solvent | weakly coordinating chlorinated medium | exact component in related literature or seed |
| [MeCN — acetonitrile](components/mecn.md) | solvent | polar aprotic medium | exact component in related literature or seed |
| [THF — tetrahydrofuran](components/thf.md) | solvent | coordinating ether medium | exact component in related literature or seed |
| [1,4-dioxane — 1,4-dioxane](components/dioxane.md) | solvent | ether/solvation contrast | exact component in related literature or seed |
| [toluene — toluene](components/toluene.md) | solvent | low-polarity aromatic medium | exact component in related literature or seed |
| [HFIP — 1,1,1,3,3,3-hexafluoropropan-2-ol](components/hfip.md) | solvent | protic, hydrogen-bond-donating medium | exact component in related literature or seed |
| [DMF — N,N-dimethylformamide](components/dmf.md) | solvent | polar coordinating amide medium | exact component in related literature or seed |

The author confirmed that the original base label `CsOH/2` is a typographical error for `CsOH`; current tables use CsOH. Original workbooks remain unchanged. The JSON and individual pages retain the chemical identities and locators of cited literature examples.

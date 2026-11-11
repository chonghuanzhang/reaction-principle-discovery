# Condition-library components

The twelve base/additive entries and eight solvents span donor availability, counterion and hydration effects, catalyst compatibility and medium properties. S–H and N–H cross all twelve base/additive identities with the eight solvents. The O–H analysis instead crosses twelve specified Cu/Ni–base formulations with the same eight solvents; [its formulation key](../../optimization/figures/source_data/OH_formulation_key.csv) and [construction manifest](../../optimization/selections/OH_CuNi_96/candidate_manifest.json) identify the actual 96 measured candidates. Catalyst identity is part of each O–H formulation, not a fixed factor. The table gives the chemical role and level of literature support for each component. Related-reaction evidence does not establish an optimum or mechanism in the present system.

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
| [CsOH — cesium hydroxide entry; formulation unresolved](components/cesium-hydroxide.md) | base/additive | cesium hydroxide family, formulation unresolved | exact formulation unresolved |
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

The source label `CsOH/2` remains unresolved in the computational data. Some SI text and display tables use `CsOH`; this records a label discrepancy, rather than verified chemical equivalence. `DIO` remains a source abbreviation where its identity was not independently resolved. The JSON retains original source locators. Reader pages link to the literature records and give publication pages or sections when supplied; unavailable publication locators are identified explicitly.

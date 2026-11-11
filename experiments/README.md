# Experimental condition and response tables

These tables provide machine-readable versions of the long scientific tables and component explanations in the Supporting Information. [optimization](../optimization/) contains the recorded workbooks, physical cell links, complete measured grids and runnable analysis.

| Directory | Contents | Scientific unit |
|---|---|---|
| `condition_library/` | Twenty component explanations with source support, quotations, locators and evidence identifiers | A base/additive or solvent entry; supporting literature may describe a related reaction rather than the present system |
| `bo_benchmark/` | One hundred paired S–H first-hit budgets | A pair of computational initialization seeds on the fixed measured 96-condition grid |
| `selected_responses/` | Numerical exports of five batches of twelve selected responses for NH_PL36 and the O–H formulation–solvent library OH_CuNi_96 | A recorded experimental response selected as a model input |

S–H, N–H and O–H use UV response. These signals retain system-specific scales and are not percentage yields. Only the S–H maximum has the matched 37% NMR yield annotation in the source workbook. O–H condition selection uses 12 Cu/Ni–base formulations × eight solvents, with two mandatory reference formulations and ten sampled identities (seed 20261111); the construction manifest and physical source-cell links are in `optimization/selections/OH_CuNi_96/`. The selected-response tables reproduce numerical selections, posterior inputs and stopping diagnostics and are not primary laboratory execution logs. The retrospective BO/random comparison concerns S–H. Different record units—100 candidate molecules, 108 input pairs, 96 grid conditions and 100 algorithm seed pairs—must be kept distinct.

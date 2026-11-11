# Selected N–H and O–H response records

`selected_responses.csv` and `.json` contain the same 120 scientific rows used for numerical reproduction: 60 each for NH_PL36 (seed 6000) and the Ni-catalysed O–H pool OH_PL38 (seed 8000), in five computational batches of twelve. The table retains the literal SI display base and solvent labels. The `archived_response` column is the recorded experimental analytical signal used in the model.

The O–H catalyst screen contains 145 entries. NiCl2·DME (Ni203) gives the largest UV response, 1.09119010819165 at PL34-W78 (AJ79). The O–H Bayesian condition-selection space therefore fixes Ni203 and varies twelve bases/additives and eight solvents. The highest selected O–H response is 1.44247787610619 for DIPEA/DCE (PL38-W10), already included in the outcome-blind initial batch; later batches update the posterior and stopping diagnostics rather than first discover that response. The seed is retained from the reference analysis without a seed search.

Each deposited grid contains 96 measured conditions; the numerical exports use only 60 labels per system for posterior updates, leaving 36 labels hidden from the policy and stopping rule. Exported seeds and batches define the numerical analysis and are not primary laboratory execution logs. Both calculations reach the 60-condition budget without meeting the two-consecutive-check stopping rule. The retrospective BO/random comparison concerns S–H.

N–H and O–H values are UV response. Responses are not calibrated yields. Source-linked selected rows and stopping checks are in `../../optimization/selections/`; the exact raw workbook label `CsOH/2` is retained there where this SI display table says `CsOH`. Immutable raw workbooks and historical benchmark tables retain their original contents.

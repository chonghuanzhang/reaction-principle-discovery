# Repository Table R4 | Selected N–H and O–H responses

`selected_responses.csv` and `.json` contain the same 180 scientific rows: 60 each for NH_PL36 (seed 6000), OH_PL37 (seed 7000) and OH_PL38 (seed 8000), in five batches of twelve. The table retains the literal SI base and solvent labels. The `archived_response` column is the recorded analytical signal revealed after computational selection.

Each original grid contains 96 measured conditions; these selections use only 60 labels per system for posterior updates, leaving the other 36 labels hidden from the policy and stopping rule. These records are computational selections rather than dated physical execution logs. All three reach the 60-condition budget without meeting the specified consecutive stopping rule.

N–H values are MS response; O–H values are UV response. They are not calibrated yields. Source-linked selected rows and stopping checks are in `../../optimization/selections/`; the exact raw workbook label `CsOH/2` is retained there where the SI display table says `CsOH`.

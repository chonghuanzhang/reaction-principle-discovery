# Selection policy

## Relation hierarchy

| Class | Deterministic requirement | Decision rule |
|---|---|---|
| Exact Molecular Match | Identical canonical isomeric structure | May proceed to feasibility review |
| Reactive-form Analogue | Same neutral covalent parent; only protonation or counterion differs | Confirm activation and handling, then review |
| Structural Analogue | Route-compatible reacting centre with a documented scaffold, substituent or donor-family relationship | Record the chemical rationale and require human approval; family-level links remain explicitly broad |
| Additional Experimental Candidate | Intentionally included without a candidate replacement claim | Route to the exploratory-exception register with a reason and human approval |
| Unmatched | No defensible route-compatible candidate relation | Record separately; do not force a link |

## Feasibility record

The deposited decision ledger requires:

- canonical donor and electrophile structures, reactive form and intended endpoint;
- availability status, handling/safety review and chemical-compatibility review;
- relation class, candidate IDs and chemical rationale;
- actual-input NP/NR assessment;
- human-review status, selection decision and unresolved issues.

For each run, also capture vendor or source, purity, amount, cost, lead time, reviewer identity and decision date when those records are available. These fields strengthen procurement reproducibility; unavailable procurement facts remain explicitly unrecorded.

## Execution record

After an experiment is run, retain the sample ID, condition ID, workbook, sheet, row, electrophile and donor structures, execution status and identity flags. The deposited validation exports 108 ordered electrophile–donor records containing 102 distinct donor structures; these are execution units and should not be silently collapsed into a molecule count.

## Stop conditions

Do not release an ordinary experiment-ready record when the reagent identity is unresolved, the proposed route lacks a compatible reacting centre, the minimum feasibility review is absent or the analogue rationale has not received human chemical approval. A researcher may retain a deliberately approved exploratory addition or an already executed unmatched record only in the explicit exception register, with the unresolved issue and chemical reason preserved; such a record is not presented as an exact or route-compatible candidate replacement.

## Reusable validation bundle

`scripts/run.py --candidates ... --mapping ... --hypotheses ...` accepts a new reviewed bundle. Candidate identifiers must be unique; each non-unmatched experiment must contain an X-H or anionic route site and resolve to at least one candidate with a canonical relation label, rationale and non-empty route-compatible hypothesis set; unmatched entries require an explicit reason; and every record must retain an admitted identity status, pair-specific NP/NR, the three minimum feasibility fields, human-review and release-gate status, execution status and source occurrences. RDKit verifies structures, exact molecular matches and neutral-parent equality for reactive-form analogues. The exporter records input paths and SHA-256 digests so a run can be tied to the exact review bundle.

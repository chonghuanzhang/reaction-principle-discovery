# Selection policy

## Relation hierarchy

| Class | Deterministic requirement | Decision rule |
|---|---|---|
| Exact identity | Identical canonical isomeric structure and a route-compatible reacting centre | Retain the exact candidate link |
| Same scaffold, substituent or positional variation | Route-compatible reacting centre with the same core scaffold and a stated substituent or positional difference | Retain the difference and rationale; do not transfer response |
| Same donor family, different scaffold | Route-compatible reacting centre and local donor type, but a different molecular scaffold | Retain the family-level rationale; do not treat the molecules as interchangeable |
| No reasonable counterpart | No defensible route-compatible recommendation | Record an explicit reason and do not force a link |

## Selection context

Researchers considered structural relationships, commercial accessibility and endpoint-specific NP/NR information together, without a universal numerical cutoff or weighted score. The deposited mapping records the final reviewed correspondence and execution records for the experimental collection.

The deposited ledger retains:

- canonical donor and electrophile structures, reactive form and intended endpoint;
- relationship category, candidate IDs, reacting-atom indices and chemical rationale;
- actual-input NP/NR assessment;
- source-linked execution records and sample identifiers.

## Execution record

After an experiment is run, retain the sample ID, condition ID, workbook, sheet, row, electrophile and donor structures and execution status. The deposited validation exports 108 ordered electrophile–donor records containing 102 distinct donor structures; these are execution units and should not be silently collapsed into a molecule count.

## Stop conditions

Do not force a candidate link when the proposed route lacks a compatible reacting centre. Retain already executed unmatched records with their explicit reason and source occurrence, but do not present them as candidate-supported selections. A non-exact relationship is a documented comparison, not evidence of equivalent reactivity.

## Reusable validation bundle

`scripts/run.py --candidates ... --mapping ... --hypotheses ...` accepts a new reviewed bundle. Candidate identifiers must be unique. Each matched experiment must retain a route-compatible reacting atom, at least one candidate link, a current relationship category, a rationale and a non-empty compatible-hypothesis set. Exact identities must be canonically identical. The three relationship-specific candidate-ID lists must reproduce the link records exactly; unmatched entries require an explicit reason and no forced link. Every record must retain pair-specific NP/NR, execution status, source occurrences and sample/condition closure. The exporter records input paths and SHA-256 digests so a run can be tied to the exact review bundle.

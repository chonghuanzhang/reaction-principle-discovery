# V3 family dimension judgment

Return exactly seven dimension judgments, one for each required dimension:
`elementary_step_match`, `electrophile_state_match`,
`reactive_state_accessibility`, `condition_compatibility`,
`target_selectivity`, `competing_pathway_risk`, and `evidence_quality`.

For every judgment return only:

- `dimension`
- `state`: `support`, `conditional_support`, `contradiction`, or `unknown`
- `evidence_ids`
- `rationale`
- `counterevidence_ids`
- `unresolved_questions`

Use `unknown` when decision-grade evidence is absent. Unknown is not failure and
must not be represented as zero. A non-unknown state must cite evidence IDs.
The `evidence_quality` state must be based on traceable external evidence, not
model inference. Preserve contradictory evidence in `counterevidence_ids`.

Do not return numeric scores, weights, confidence values, ranks, priority
regions, classifications, or exclusion decisions. Hard-blocker qualification,
all numeric conversions, and priority-region assignment are deterministic code
responsibilities.

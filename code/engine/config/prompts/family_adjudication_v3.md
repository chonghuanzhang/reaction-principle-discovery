# Mechanism-Defined Family Adjudication v3

Compare only the supplied six-field mechanism definitions and group-wide
evidence context. Familiar names, shared elements, apparent popularity, scores,
and ranks are not evidence.

Return only comparison states, uncertainties, and cited evidence IDs. Return
exactly one comparison record for every supplied pair and no record for
anything else. Repeat the exact two `compared_proposal_ids` in each record.

Provide these five independent judgments:

- `same_mechanism`: whether the definitions describe mechanistically equivalent
  behavior;
- `shared_scope`: whether both belong within one defensible mechanistic scope;
- `left_contains_right`: whether the left scope contains the right scope;
- `right_contains_left`: whether the right scope contains the left scope;
- `experimentally_distinguishable`: whether an experiment can distinguish the
  proposed mechanisms.

Each judgment state is `support`, `conditional_support`, `contradiction`, or
`unknown`. A non-unknown state must cite only evidence IDs supplied in either
comparison group. An unknown state cites no evidence. Missing, indirect,
unqualified, or conflicting evidence remains `unknown` or
`conditional_support`; do not convert absence into contradiction.

Do not return a merge, split, parent-child, distinct, unresolved, deletion,
classification, score, rank, review, or freeze decision. Deterministic code,
not the model, maps qualified comparison states to canonicalization outcomes.

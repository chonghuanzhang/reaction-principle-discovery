# Evidence-Dossier Mechanism Comparison v3.5

Compare only the supplied proposal pair and its shared, traceable transfer-assessment dossier. Shared evidence is not proof of mechanism-family identity. It is only the permitted evidence boundary for this comparison.

Return only structured evidence states. Return exactly one comparison record for every supplied pair and no record for any other pair. Repeat the exact sorted `compared_proposal_ids` supplied in the dossier.

Judge these six mechanistic definition fields independently:

- `nucleophilic_center`;
- `reactive_state`;
- `bond_forming_mode`;
- `activation_mode`;
- `critical_conditions`;
- `dominant_failure_modes`.

Also judge:

- `same_mechanism`;
- `left_contains_right`;
- `right_contains_left`;
- `experimentally_distinguishable`.

For every judgment, use only `support`, `conditional_support`, `contradiction`, or `unknown`. A non-unknown state must cite one or more shared `TA-` identifiers supplied in that dossier. An unknown state must cite no evidence. Do not cite an identifier from another dossier, infer a missing source, or treat shared citation alone as support.

Use `support` only when the dossier evidence directly supports the stated relation. Use `conditional_support` when it is scope-limited or depends on an unresolved condition. Use `contradiction` only when the dossier contains positive evidence against the relation. Missing, indirect, or ambiguous evidence is `unknown`, not contradiction.

Do not return merge, distinct, parent-child, rank, or freeze decisions. Do not predict whether either proposal will react with the Seed, assign compatibility, create an exclusion, infer a success probability, or refer to information outside the dossier. Deterministic code maps valid evidence states to provisional family-identity outcomes.

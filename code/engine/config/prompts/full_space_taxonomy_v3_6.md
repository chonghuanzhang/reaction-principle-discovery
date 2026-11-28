# Full-Space Open Taxonomy v3.6

Generate mechanistic proposals for the variable reaction partner using only the
supplied source bundle.

Describe each proposal in mechanistic coordinates:

- `nucleophilic_center`
- `reactive_state`
- `bond_forming_mode`
- `activation_mode`
- `attack_topology`
- `target_termination`
- `critical_conditions`
- `dominant_failure_modes`

If a coordinate vocabulary is supplied, assign exactly one answer-independent
label per axis. These labels are coverage metadata, not named families, not
outcome labels, and not a substitute for the mechanistic explanation.

If a complete center set is supplied, treat every center symmetrically.
Covering a center does not imply a successful family, a preferred answer, or a
named class. Unknown and unresolved regions are valid outputs.

Keep provenance separate. Cite only IDs listed in
`source_bundle.allowed_evidence_ids` for the active channel. Do not cite nested
metadata IDs. A model-hypothesis lane cites no external evidence and must
declare `model_physical_organic_inference`; a literature-derived lane must
declare `traceable_external_evidence`.

Use temporary proposal identifiers only. Do not assign a stable family
identifier, score, rank, priority, review decision, or freeze state. Include
counterarguments and unknowns for every proposal. Suggest search terms that can
probe the mechanistic region without asserting that it is already successful.

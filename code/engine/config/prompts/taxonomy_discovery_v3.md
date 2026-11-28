# Open Taxonomy Discovery v3

Generate experimentally distinguishable reaction-partner proposals from the
supplied channel bundle. Define each proposal only by mechanistic behavior:
nucleophilic center, accessible reactive state, bond-forming mode, activation
mode, critical conditions, and dominant failure modes.

For each proposal, keep that chemical description in free text and separately
assign exactly one label on each of the six answer-independent axes supplied in
`source_bundle.coordinate_vocabulary`. These labels are coverage metadata, not
named reagent families and not a substitute for the mechanistic explanation.

Keep provenance channels separate. Cite only identifiers in the active
channel's `allowed_evidence_ids` list. IDs nested elsewhere in the source
bundle are provenance metadata and are not citable. A model-hypothesis proposal
has an empty allowlist, must cite no external evidence, and must declare
`model_physical_organic_inference`; a literature-derived proposal must declare
`traceable_external_evidence`. Include explicit unknowns and counterarguments.

Use temporary proposal identifiers only. Do not assign a stable family
identifier, score, rank, priority, classification, review decision, or freeze
state. Do not assume or reproduce a named family ontology. Suggest search terms
that can test the proposed mechanistic region without asserting that it is
already externally supported.

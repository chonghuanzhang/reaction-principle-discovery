# Literature evidence, reaction principles and candidate computations

## Scientific inputs and their scope

The frozen generation bundle in `data/generation/` contains 342 source records, 3,694 downstream evidence statements, 3,816 admission-stage statements, 4,391 transfer assessments and 12 seed evidence records. These counts refer to different stages and should not be added together. Source registries and evidence identifiers provide the joins; API metadata distinguish extraction, transfer, principle proposal and candidate-generation calls.

The current source collection contains 370 literature records and 3,756 evidence statements. Its four primary tiers contain 139, 101, 88 and 42 sources. A source's tier describes its chemical contribution rather than an experimental quality score. Later source additions and applicability assessments enrich the present chemical discussion. They do not retroactively become inputs to earlier saved model calls.

Source evidence distinguishes experimental observations, author mechanistic interpretations and transferable relationships. Conditions, reaction centres, accessible donor species, product endpoints and contrary or unknown evidence constrain transfer. Metadata-only access establishes bibliographic identity or topic; it is not a negative chemical observation. A missing reported reaction or an inaccessible SI is not proof that a reaction fails.

`engine/pipeline/evidence_applicability.py` implements the saved applicability rules. `literature/merge_catalog.py` preserves established source identifiers, enriches a DOI already present, appends a verified new identity and rejects conflicting reassignment. A source with only metadata contributes no chemical evidence statement. The included tests exercise these boundaries with independent fixtures.

## Saved principle proposal and review

The seed mechanism and 4,391 transfer records are in `data/principle_calls/`. The original proposal input selected at most 120 assessments with at most one per paper. Its literal configuration and source admission functions are in `principles/proposal_admission.py`; the schema and induction logic are in `engine/pipeline/`.

The proposal prompt asks for compact, falsifiable, source-linked principles while retaining seed-specific and transferable layers. It requires supplied seed and transfer evidence identifiers, conditions, negative or unknown evidence, an experimental consequence and a falsifier. It prohibits assuming that the proposed seed mechanism is established or using later project outcomes to infer the principle set. A proposal cannot accept itself: deterministic validation checks its status and references before review.

The saved proposal and review were separate calls using the recorded model `gpt-5.6-sol`. The supplied records do not establish independence between different model families. Five working constraints passed the saved admission and review. These five constraints are retained as actual call outputs. The paper's RP1–RP4 organize the chemistry into acceptor activation, donor speciation/capture, intermediate branching and product persistence; they are a later scientific synthesis, rather than a claim that an earlier prompt originally returned four cards.

`scripts/replay_principle_review.py` rebuilds the proposal input digest, validates the saved model payload, constructs the original review prompt and checks its input digest. It then reruns the deterministic review validator and compares accepted and rejected records with the saved results. The proposal digest is `774673f8e592d76abd617c2170f8aac007153f28024374f513b00ac212fa05fe`; the review digest is `51e710298a8f1f5fcbde5a19b8c0aa444e5b9cfbd6e1dd4e3b837315b24f736d`. Both comparisons use local responses and perform no model call.

## Candidate generation and interpretation

`candidate_workflow/` contains the actual candidate inputs, configuration, retrieval records, model responses, structures and the engine snapshot that binds those calls. The primary call and compact expansion call are separate stages. Their deterministic replay checks source retrieval, input/prompt/model/core-code bindings, payload schema, chemical identity review and the saved selection. The frozen source snapshot remains separate from the general engine so that replay verifies the same code used for its binding.

The final collection contains 100 candidate molecules, 115 route or reacting-site hypotheses and 124 proposed product options. A molecule may support more than one reacting site or endpoint. Neutral donors, salts and latent donor precursors remain chemically distinct records. The 48 selected and 52 reserve entries in one candidate panel describe a computational exploration budget, not an experimentally validated success ranking. The complete collection is the 100-molecule population.

The literal candidate records include Chinese scientific explanations where that was the original output. English reader tables and explanations are provided in `../candidates/`; the original fields remain available for tracing a statement to its source. Item-level source links are incomplete: 46 original candidate entries have citations and 54 do not. This boundary should remain visible rather than being repaired by assigning later citations to an earlier call.

The final collection contains 100 molecules. Its saved generation calls, identity review and released collection remain available in `candidate_workflow/`. Source-linked [transfer-scope examples](data/transfer_scope_examples.json) separately explain the C–C, C–N and C–O connectivity and condition boundaries; these chemical interpretations do not alter the saved model inputs or scores.

## Molecular correspondence to experimental input records

`data/structures/actual_source_rows.json` contains 2,114 workbook occurrences. The extraction resolves these to 1,066 source-row groups without structure conflicts, and then 108 distinct ordered electrophile–donor pairs. These pairs contain 102 distinct recorded donor structures and five electrophiles. These are structure-record units rather than a replacement definition of the final 100-reagent study population.

`mapping/build_mapping.py` compares each experimental input with candidate structures using RDKit canonical isomeric SMILES. Exact molecular matches preserve formal charge and counterions. A reactive-form analogue requires the same neutral covalent skeleton after largest-fragment selection and protonation/counterion normalization, with a compatible original reacting-centre hypothesis. This normalization does not permit arbitrary precursor cleavage or establish the reactive population under laboratory conditions.

Structural analogues preserve an explicit local donor-family relationship and reacting-centre compatibility. They use no quantitative similarity threshold and do not require a conserved scaffold. The program retains earlier family associations while distinguishing these broad analogies from an exact molecular or pure protonation-state match. AP066 retains its distinct phenolic-O and alcohol-O product branches; an endpoint must not be silently changed to improve the correspondence. AP002, AP045, AP058 and AP105 remain unmatched under the stated policy.

The correspondence is retrospective structural interpretation. It does not recover an original procurement, replacement or selection event. The source records do not supply item-level contemporaneous inventory, toxicity, cost, delivery-time or decision-date evidence. `scripts/reproduce_mapping.py` recomputes nine saved mapping and summary tables and requires byte equality. It does not infer a causal effect of human evaluation from marginal novelty distributions.

## NP/NR classifications

The baseline novelty data, four reviewed classification tables, source references and 202 saved PubChem query responses are in `data/novelty/`. `novelty/apply_review.py` reapplies explicit source-code decisions to the baseline records. It preserves candidate/input structures, model product connectivity, source occurrences and prior scores. `scripts/reproduce_novelty.py` requires exact equality of all four resulting JSON tables.

NP concerns the proposed product within the stated identity/query scope; NR concerns the proposed reaction in its nearest-precedent comparison. They are not reagent novelty, a reaction-success probability or an exhaustive database guarantee. The saved assessment used PubChem same-connectivity responses, the project literature collection and logged Crossref, Europe PMC and OpenAlex searches at their accessible evidence level. It did not include complete SciFinder or Reaxys reaction searching or an exhaustive patent structure search.

Unresolved labels remain unresolved. Candidate 035 retains protonation states at parent-connectivity NP2 rather than treating salt-form change as a new skeleton. Candidate 086 retains unresolved NP for all three phosphorus endpoints. AP064 preserves its two O-site options separately. AP043 retains unresolved NR pending the endpoint-specific comparison. Non-applicable records remain distinct from negative results or zero scores. The reviewed label version and query dates remain in the original records, so readers can identify the evidence cutoff.

## Figure calculations

Figure 2 uses the supplied generic structural relationships for RP1–RP4. Figure 4 reads the frozen centre counts and candidate structures. RDKit draws vector molecular graphs, and the Matplotlib/PyMuPDF compositor retains vector structures in both PDF and SVG. No stereochemistry is inferred beyond the source connectivity.

Figure 3 is a projection of the frozen full-network artwork in [`knowledge_graph/figures/`](../knowledge_graph/figures/). Its reconstruction removes 33 specified presentation groups and applies the supplied crop; surviving geometry, source tags, headings and legend are checked against `Figure_3.svg` as a parsed SVG tree. The accompanying [`network.json`](../knowledge_graph/data/network.json) and [tier summary](../knowledge_graph/data/tier_summary.json) retain the full graph records. This is a reproducible figure projection, rather than a new network inference.

The scripts report the actual scope of their checks. Offline replay establishes consistency of saved inputs, rules and outputs. It does not independently validate the chemistry, reproduce inaccessible source publications, generate new model responses or supply missing experimental measurements. Optimization algorithms, analytical responses and Figure 5 are described separately in `../optimization/METHODS.md`.

## Title variants and source identity

The frozen registry points to `data/generation/bibliography_title_adjudication.json` for one accepted-article title variant, [L336](../literature/sources/L336.md), DOI 10.1002/asia.201601036. Its abbreviated SNAr/SBM/HDF title and expanded published title share the same DOI. The explanation concerns bibliographic identity; it does not establish identical chemical content between accepted and final versions. The registry itself retains its original bytes.

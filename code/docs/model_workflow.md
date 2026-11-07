# Current reaction principles and candidate generation

## Current four reaction principles

The paper's current scientific framework organizes the source evidence and candidate rationales around four conditional chemical relationships:

- [RP1 — Acceptor activation](../../evidence/principles/RP1.md): access to a fluorinated acceptor gates nucleophile transfer.
- [RP2 — Donor speciation and capture](../../evidence/principles/RP2.md): the accessible donor form and its capture competence must coincide.
- [RP3 — Intermediate pathway divergence](../../evidence/principles/RP3.md): the state formed by capture controls fluoride loss versus fluorine retention.
- [RP4 — Product persistence](../../evidence/principles/RP4.md): selective formation must outpace downstream consumption.

These four formulations are a subsequent evidence-based synthesis. The original model inputs remain in the [generation archive](#archived-generation-inputs), preserving the distinction between the completed generation and the current chemical organization.

## Successfully completed candidate generation

The archived calls completed successfully using the API model identifier `gpt-5.6-sol`: seven primary model responses and two compact-expansion responses are saved with completed status. The primary stage considered carbon π capture, carbon transfer, nitrogen, oxygen, sulfur, phosphorus and radical/other main-group transfer. Each perspective received the target specification, up to 24 relevant evidence records with no more than two per source, and the archived reviewed working constraints. The compact expansion used two perspectives, neutral ambident aromatics and precursor-state pairs, with eight evidence records and six requested candidates per perspective.

Outputs specify molecular names, SMILES, zero-based reacting-atom indices, reactive forms, citations, activation requirements, competing pathways and diagnostic observations. Schema, atom-index and cited-evidence checks reject invalid proposals. Chemical identity review separately compares the molecular graph with its name. The combined pool contained 101 distinct structures; one identity-conflicted structure was quarantined, leaving the 100 retained molecules. Four additional initial proposals were rejected during schema, evidence or atom validation.

[Literal call settings and receipts](../data/generation/llm_run_provenance.json) · [Saved candidate calls and replay instructions](../candidate_workflow/README.md) · [Released collection](../candidate_workflow/artifacts/released/panel.json) · [Coverage checks](../candidate_workflow/artifacts/released/coverage_audit.json)

## Original prompts

The complete original prompt texts are directly readable. The candidate prompts request a finite exploration panel and allow uncertain, explicitly reasoned extrapolations. They require valid structures, supplied source identifiers and unchanged quotation substrings, and prohibit invented references, fabricated dosing or probabilities of reaction success. Original explanations were requested in readable Chinese.

- [Principle proposal prompt](../data/generation/principle_proposal_prompt.txt)
- [Primary candidate prompt](../data/generation/candidate_primary_prompt.txt)
- [Compact expansion prompt](../data/generation/candidate_compact_expansion_prompt.txt)

## Archived generation inputs

The original calls used the following five reviewed working constraints. Their identifiers, wording and review status are retained here as the historical inputs. Original per-molecule citations also remain unchanged, including the 54 entries without item-level citations. Later novelty comparisons and current four-RP annotations retain their separate scope.

[Complete five-constraint records](../data/generation/frozen_principles_5.json) include condition windows, source evidence, mechanisms proposed by the authors, exceptions, experimental consequences and falsifying experiments.

### RP-SR001-SS-01 · Condition-bounded two-fluorine stopping point

Within the grounded Seed system, productive coupling is a condition-bounded net conversion that forms a C-C bond at the CF3-derived carbon while stopping after loss of two fluorines at a monofluoroalkene; stronger base or higher temperature is predicted to increase the competing fully defluorinated alkene rather than simply improve productive conversion.

Recorded confidence: low. Review status: accepted.

### RP-SR001-SS-02 · Multivariable organoboron scope boundary

Under the grounded Seed conditions, coupling-partner performance may depend jointly on electronics, coordination, steric congestion, and the organoboron reactive form. The reported limitations for highly electron-deficient heteroaryl, strongly coordinating, sterically congested, and ortho-disubstituted partners are Seed-specific risk boundaries, while a blanket alkyl-organoboron exclusion is unsupported because the supplied Seed account also reports a productive N-Boc-protected piperidinyl boronic-ester model result.

Recorded confidence: low. Review status: revised.

### RP-SR001-SS-03 · Kinetic-competence requirement for Seed intermediates

If the proposed carbonyl-bound Pd intermediate, gem-difluoroenone, Pd-H species, or sequential insertion/transmetalation/beta-fluoride-elimination sequence lies on the productive Seed pathway, the relevant intermediate must be structurally supported and kinetically competent under conditions demonstrably connected to the grounded reaction. The supplied net chemistry and inconclusive trapping do not currently establish any complete catalytic sequence.

Recorded confidence: low. Review status: revised.

### RP-SR001-TS-01 · Local beta-fluoride-elimination liability

In the supplied conditional analogies, a suitably configured beta-fluoro carbon-metal or carbanion-like addition intermediate may undergo beta-fluoride elimination to a fluorinated alkene. Transfer is limited to this local elementary-step hypothesis and requires independent demonstration of the intermediate, its elimination geometry, and its kinetic competence; it does not establish the Seed's initial activation, complete cycle, or sequential loss of two fluorines.

Recorded confidence: low. Review status: revised.

### RP-SR001-TS-02 · Partial defluorination as a conditional kinetic stopping point

Where a partially defluorinated intermediate or product remains reactive in the operative mixture, the desired fluorination state can be a kinetic stopping point rather than an intrinsic endpoint. The Seed and conditional transferred evidence justify testing temperature, base, reagent stoichiometry, fluoride activity, water content, and residence time as system-specific variables, but they do not establish a universal direction or magnitude for those effects.

Recorded confidence: low. Review status: revised.

## Separate proposal and review calls

The saved proposal and review used separate inference contexts of the same recorded model, `gpt-5.6-sol`. Deterministic validation checks source identifiers, schema and required fields; chemical review separately checks structures, endpoints and observation versus hypothesis. The supplied records preserve original response identifiers and token usage in the saved API envelopes.

[Proposal response](../data/principle_calls/proposal_response.json) · [Review response](../data/principle_calls/review.json) · [Reviewed constraints](../data/principle_calls/reviewed.json) · [Offline replay](../README.md#run-without-a-model-service)

Offline replay verifies consistency between saved inputs, source code and outputs using the archived responses. The [computational methods](../METHODS.md) state the dataset boundaries and verification scope.

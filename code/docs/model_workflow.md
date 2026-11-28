# Evidence-to-RP-to-recommendation workflow

## Current evidence and principles

The workflow begins with the target-reaction specification and source-linked evidence collection. Literature records are classified by chemical contribution; common observations and transfer limits are consolidated into [four reviewed reaction principles](../../evidence/principles/). Each RP retains evidence identifiers, applicability conditions, exceptions and candidate-generation rules.

The RP-to-recommended-nucleophiles stage uses those cards and a precursor-family ontology to propose molecular inputs, reacting atoms, activation questions, competing pathways and diagnostic observations. Molecular-graph and identifier checks precede chemical-feasibility grouping, novelty-review ordering and provenance validation. The current release contains 100 unique neutral molecules, 103 reacting-site/pathway hypotheses and 103 proposed connectivities across 43 precursor families.

The recommended-nucleophiles-to-experimental-reagents stage compares each recommendation with the recorded experimental collection using exact identity, scaffold/substituent and donor-family relationships while preserving the intended reacting atom and route. It produces a 100-row recommendation-level correspondence and a 112-row ordered experimental-pair ledger representing 102 distinct donor structures. Non-exact relationships remain explicitly labelled; no experimental response is transferred through analogy.

## Validation and export

The [release validator](../scripts/validate_candidate_release.py) checks deposited identifiers, counts, relationship distributions, network closure and manifest hashes, while the two reusable skill commands validate deposited JSON bundles and export traceability or correspondence ledgers. These commands operate on recorded data and do not perform new inference.

The authoritative package and hashes are in the [released artifact directory](../candidate_workflow/artifacts/released/). The [candidate catalog](../../candidates/), [knowledge graph](../../knowledge_graph/) and [experimental correspondence](../../candidates/experiment_mapping/) are reader-facing views of the same identifiers. Run `python code/scripts/validate_candidate_release.py` from the repository root for the offline release check.

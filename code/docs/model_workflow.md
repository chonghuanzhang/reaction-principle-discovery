# Evidence-to-RP-to-recommendation workflow

The workflow begins with the target-reaction specification and the source-linked evidence collection. Literature records are classified by chemical contribution; common observations and transfer limits are consolidated into four reviewed reaction principles. Each RP retains evidence identifiers, applicability conditions, exceptions and candidate-generation rules.

The RP-to-recommended-nucleophiles stage uses those cards and a precursor-family ontology to propose molecular inputs, reacting atoms, activation questions, competing pathways and diagnostic observations. Deterministic structure and identifier checks are followed by chemical-feasibility grouping, novelty-review ordering and provenance validation. The released result contains 100 unique molecules, 103 reacting-site/pathway hypotheses and 103 proposed connectivities across 43 precursor families.

The recommended-nucleophiles-to-experimental-reagents stage compares each recommendation with the recorded experimental collection using identity, scaffold/substituent and donor-family relations while preserving the intended reacting atom and route. It produces both a 100-row recommendation-level correspondence and a 108-row ordered experimental-pair ledger. Non-exact relations remain explicitly labelled; no response is transferred through analogy.

The current package and its hashes are in [`../candidate_workflow/artifacts/released/`](../candidate_workflow/artifacts/released/). The [candidate catalog](../../candidates/), [knowledge graph](../../knowledge_graph/) and [experimental correspondence](../../candidates/experiment_mapping/) are reader-facing views of the same identifiers.

Run `python code/scripts/validate_candidate_release.py` from the repository root for an offline closure and hash check.

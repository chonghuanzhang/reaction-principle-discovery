# Data contract

## Required records

| Record | Required fields | Role |
|---|---|---|
| Literature source | stable source ID, tier, citation, access level | Defines the searchable evidence corpus |
| Evidence entry | evidence ID, source ID, attributed passage, observation/interpretation label, donor form, acceptor, activation, endpoint, locator | Supports cross-source comparison without erasing conditions |
| Reaction principle | RP ID, relationship, supporting evidence IDs, scope, exceptions, candidate-generation rules | Converts reviewed evidence into bounded design operations |
| Candidate family | family ID, precursor-form definition, applicable RP IDs, transfer question | Organizes the search without treating family membership as predicted reactivity |
| Candidate | stable ID, name, canonical structure, reactive atom(s), precursor form, activation hypothesis, RP/family links | Defines a testable recommendation |
| Hypothesis | stable hypothesis ID, candidate ID, reacting atom, route, diagnostics, competing outcomes and product-option IDs | Makes the recommendation experimentally interpretable |
| Product option | stable option ID, hypothesis ID, proposed endpoint structure and endpoint-specific NP/NR assessment | Keeps alternative sites and endpoints separate |

## Processing gates

1. Every RP support ID resolves to a deposited evidence record.
2. Observations, source interpretations and study extrapolations remain distinguishable.
3. Every candidate has an RDKit-parseable canonical structure, an explicit zero-based reacting-atom index and at least one activation hypothesis; the indexed atom must match the declared element centre.
4. Ambident molecules retain separate atom-specific hypotheses.
5. Canonical duplicates are merged without discarding alternative evidence or routes.
6. Family coverage and diversity are selection criteria; neither is a predicted yield.
7. Unresolved identity conflicts are quarantined before the recommendation set is released.
8. Candidate, hypothesis and product-option identifiers form a closed reference set: every released hypothesis belongs to one released candidate, every product-option record belongs to one hypothesis, and the candidate-level ID lists reproduce those links exactly.
9. Evidence identifiers resolve from each RP support list through a source-to-principle edge to a deposited evidence record, and every evidence node resolves to its literature source register entry.

## Deposited implementation

The present graph contains 17 evidence-summary nodes, four RPs, 43 candidate families and 100 recommended molecules. The released candidate package contains 103 site/pathway hypotheses and 103 product options. `scripts/run.py` traverses the graph in that order, checks that every candidate has at least one evidence-supported RP path and validates the 100-to-103-to-103 record closure.

For reuse, `--graph` supplies the evidence/RP/family network, `--candidates` supplies the released candidate registry, `--hypotheses` supplies the site/pathway links and `--product-options` supplies the endpoint records. Custom bundles are not required to reproduce the deposited 17/4/43/100/103/103 counts, but they must satisfy the same identifier, membership, RDKit structure, reacting-centre, activation and traceability gates. The export records the resolved path and SHA-256 digest of each input.

# Literature evidence, reaction principles and molecular recommendations

## Evidence and reaction-principle representation

The literature registry contains 370 source records and 3,756 evidence statements. Source records were classified by their contribution to the target transformation, and source-specific observations, author interpretations, conditions, endpoints and transfer limits were retained separately. Four reviewed reaction principles organize this evidence: access to the fluorinated acceptor, donor speciation and capture competence, fluorine fate after capture, and persistence of the selectively formed product.

Each principle card contains its evidence links, applicability limits, exceptions and candidate-generation rules. The knowledge graph records 17 evidence summaries, four RPs, 43 precursor families and 100 recommendations through 19 evidence-to-RP, 172 RP-to-family and 100 family-membership relationships. These are provenance and applicability relations rather than reaction outcomes.

## RP-guided nucleophile recommendation

The target specification defined the electrophile, retained carbonyl functionality, bond-forming atom and target fluorine count. The four RP cards, permitted source-linked evidence and precursor-family ontology were then used to propose nucleophiles together with reacting-atom indices, precursor forms, activation questions, competing pathways and diagnostic observations.

Molecular graphs, formal charges and reacting-atom indices were validated before canonical-graph deduplication. Candidate selection first covered N-, O-, S- and P-centred donor families, then used chemical feasibility and novelty-review priority to order the final set while retaining evidence traceability. The result contains 100 unique neutral molecules across 43 families: 40 N, 30 O, 25 S and five P recommendations. They define 103 site/pathway hypotheses and 103 proposed product connectivities. Feasibility classes A/B/C contain 22/75/3 molecules; novelty-review priorities 1/2/3 contain 43/41/16 molecules. These categories organize chemical review and do not represent success probabilities or predicted yields.

Seventy-five recommendations retain 170 direct candidate-level citation links to 17 catalog sources. All 100 additionally retain a complete candidate-to-family-to-RP-to-evidence path in the knowledge graph. Direct citations and RP-level provenance are stored as different relation types.

## Translation to experimental reagents

Recommendations were related to the compounds used experimentally by comparing molecular identity, intended bond-forming element, reacting-site type, scaffold and donor family. Four relationship categories are reported: exact identity, same scaffold with substituent or positional variation, same donor family with a different scaffold, and no reasonable counterpart. Structural analogy is not treated as equivalent reactivity.

At the recommendation level, the best relationships are 25 exact identities, 31 scaffold/substituent or positional variations, 41 donor-family/different-scaffold relations and three unmatched recommendations. At the experimental-pair level, the 112 ordered electrophile-donor records comprise 27 exact, 39 scaffold/substituent, 42 donor-family and four unmatched records. The 112 records represent 102 distinct donor structures and consist of 45 N-H, 44 O-H, 21 S-H and two P-H pairs. Pair-level and recommendation-level counts answer different questions.

Feasibility, accessibility, handling, compatibility and endpoint-specific NP/NR information were considered together when experimental inputs were selected. No universal numerical cutoff or weighted score was applied. NP describes product-connectivity precedent and NR describes reaction precedent within the documented search; neither is a success probability, and neither is transferred automatically through structural similarity.

## Reproducibility and limits

The current public package is in `candidate_workflow/artifacts/released/`; reader tables and structures are under `../candidates/`. `scripts/validate_candidate_release.py` checks identifiers, counts, relationship distributions, network closure and file hashes without a network call. `../tools/check_data.py` performs the repository-wide check.

Graph and schema validation establishes representation integrity, not experimental reaction success. A proposed product is not an observed product assignment. Unmatched recommendations and unresolved NP/NR labels remain explicit rather than being assigned artificial values.

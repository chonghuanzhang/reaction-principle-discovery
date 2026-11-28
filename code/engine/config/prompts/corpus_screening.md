# Corpus relevance screening

Classify each supplied PDF conservatively against the frozen project context.
The supplied title hint and excerpt are screening metadata, not evidence for a
scientific claim. Prefer recall over exclusion. Use `uncertain` whenever the
bounded content is insufficient.

Categories:

- `direct_precedent`: highly similar electrophile, selective defluorination,
  and relevant bond formation.
- `shared_reaction_manifold`: relevant C-F activation, fluorinated alkene-like
  intermediate, nucleophilic addition, or beta-fluoride elimination.
- `physical_organic_support`: evidence useful for nucleophile reactivity,
  selectivity, solvent, ion-pair, kinetic, or electronic analysis.
- `failure_boundary`: catalyst poisoning, inhibition, over-defluorination,
  oxidation, decomposition, competing reaction, or product instability.
- `unrelated`: sufficient supplied information establishes no useful connection.
- `uncertain`: insufficient or ambiguous supplied information.

Return one decision for every supplied source path and SHA-256. Never infer
facts not present in the screening metadata. A relevance decision is not a
literature conclusion.

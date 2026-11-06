# Source-specific phosphorus and selenium inputs

These are the reviewed inputs for the earlier local evaluator and matched-evidence diagnostic. Their three local RP1–RP3 identifiers are distinct from the paper's current four cross-class RP1–RP4.

- [Evidence E01–E16](evidence.json) contains quotations, source locators, observations, interpretations, access levels and the corrected E16 mechanism. `local_source_path` resolves relative to this directory.
- [Challenge matrix](pse_challenge_matrix.json) and its [CSV view](pse_challenge_matrix.csv) retain 19 reviewed cases, including source observations, alternatives, unmeasured transfers and project cases. The executable evaluator uses eight of these cases.
- [Three source-specific cards](principle_cards.json) retain their premises, directional relations, exceptions, falsifiers and transfer limits. The diagnostic uses a [restricted card packet](../matched_evidence/llm_principle_cards.json) to avoid adding counterexample facts absent from the shared evidence.
- [References](references.json), [verified structures](verified_structures.json), seven text [source extracts](raw/) and the [E16 source-scope graphic](raw/Zhang2019_Fig3.jpg) retain the basis for the curated chemical descriptions. An abstract-only access level remains abstract-only; a saved record does not imply full-text access.

The E16 source reports PhSe–CH=CF2 in 66% from benzeneselenol under TFHZ-Tfs-derived coupling conditions. TFHZ-Tfs releases trifluorodiazoethane (CF3CHN2); the source authors propose metal-carbenoid formation, trapping and beta-fluoride elimination. This is an alternative difluoroalkene endpoint, not the target C(F)–Se connectivity. See the [correction record](E16_precursor_correction.json) and [diagnostic amendment](../matched_evidence/E16_protocol_amendment.json).

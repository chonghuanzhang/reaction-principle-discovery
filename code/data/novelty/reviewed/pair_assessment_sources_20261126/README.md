# Pair-specific novelty evidence

The reviewed records for AP109–AP112 assess each recorded product connectivity and transformation using the deposited literature comparisons and PubChem same-connectivity searches. `proposed_pair_records.json` preserves the review output. `evidence_manifest.json` records the input, review and source-response hashes. `assessed_inputs.json` contains the four source-register structures used for the assessment.

The `sources/` directory retains query responses, accessible primary-text extracts, current repository evidence and query logs. Failed or empty retrievals remain identifiable in the logs and do not count as negative literature evidence. A PubChem no-hit result supports only the bounded search statement, not absence from all literature or patents. Paths beginning with `sources/` in the reviewed records resolve relative to this directory.

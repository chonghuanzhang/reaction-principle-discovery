---
name: rp-to-recommended-nucleophiles
description: Use when translating literature-derived reaction principles into a traceable, chemically reviewed set of candidate nucleophiles for selective defluorinative reaction discovery.
---

# RP to Recommended Nucleophiles

## Purpose

Apply the study's evidence-to-principle logic to propose a structurally diverse nucleophile set while preserving an auditable route from each molecule to its reaction principles and source evidence.

## Inputs

- A target transformation, allowed electrophile classes and intended endpoints.
- Classified literature records and source-linked evidence entries.
- Reviewed RP cards with candidate-generation rules, scope and exceptions.
- Candidate-family definitions and any chemical-space or batch-size constraints.

Read [the data contract](references/data-contract.md) before changing inputs or producing a new recommendation set.

## Workflow

1. Verify that every reviewed RP card resolves to admitted source-linked evidence and retains its applicability limits, exceptions and candidate-generation rules.
2. Check the target-transformation contract and required precursor-family coverage against the reviewed RP design implications; preserve mismatches and unknowns as explicit constraints.
3. Translate the validated RP rules into candidate families, precursor forms, reactive atoms, activation hypotheses and alternative endpoints.
4. Expand candidates across reacting atom, precursor state, electronic delocalization, steric environment and multisite reactivity while retaining the RP and evidence path for each proposal.
5. Validate structures and reactive-atom assignments, merge canonical duplicates, then balance family coverage and structural diversity.
6. Require chemical identity review before release. Quarantine unresolved structures instead of silently repairing them.
7. Write the evidence–RP–family–candidate paths to the knowledge graph and candidate records.

## Outputs

- Recommended nucleophile registry with canonical structures and reactive sites.
- Site/pathway hypotheses and product options.
- Evidence–RP–family–candidate traceability ledger.
- Rejected, unresolved and quarantined records.

Run the deposited validation from the repository root:

```bash
python3 skills/rp-to-recommended-nucleophiles/scripts/run.py \
  --output /tmp/rp_candidate_traceability.json
```

For a new transformation, prepare the graph and candidate registry according to the data contract, then pass them explicitly:

```bash
python3 skills/rp-to-recommended-nucleophiles/scripts/run.py \
  --graph /path/to/network.json \
  --candidates /path/to/candidates.json \
  --hypotheses /path/to/hypotheses.json \
  --product-options /path/to/product_options.json \
  --output /tmp/new_target_traceability.json
```

The skill workflow governs evidence review and candidate generation. The bundled command is its deterministic release gate: it validates the evidence-record-to-RP and candidate-to-hypothesis-to-product-option closures, uses RDKit to check molecular structures and reactive-atom assignments, records input hashes and exports every candidate-to-evidence path; it does not call a model or infer reaction success.

Do not report a candidate as experimentally validated or assign a success probability unless a separate experiment supplies that evidence.

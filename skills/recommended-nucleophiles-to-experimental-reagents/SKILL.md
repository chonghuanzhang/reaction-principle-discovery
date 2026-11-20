---
name: recommended-nucleophiles-to-experimental-reagents
description: Use when converting a reviewed nucleophile recommendation set into an experiment-ready reagent list with explicit structural relationships, feasibility checks and source-linked execution records.
---

# Recommended Nucleophiles to Experimental Reagents

## Purpose

Convert a chemically broad recommendation set into a practical experimental set while keeping the relation between each recommendation, chosen reagent and executed experiment explicit.

## Inputs

- Recommended molecules, reacting sites, RP/evidence links and route hypotheses.
- Reagent identity, availability, handling and compatibility records, plus procurement details when available.
- Target electrophile, route, endpoint and experimental constraints.
- NP/NR records and any previously executed experiment records.

Read [the selection policy](references/selection-policy.md) before approving structural analogues or experimental records.

## Workflow

1. Normalize candidate and reagent identities without collapsing distinct covalent structures.
2. Classify each relationship as Exact identity, Same scaffold with substituent or positional variation, Same donor family with a different scaffold, or No reasonable counterpart; retain the reacting-site and chemical rationale for every non-exact link.
3. Check whether the proposed reacting centre, precursor form and activation mode remain compatible with the intended route.
4. Review availability, safety/handling and experimental compatibility. Record any available purity, cost and lead-time information, but do not infer missing procurement facts.
5. Reassess NP/NR for the actual reagent–electrophile–endpoint combination rather than inheriting a candidate label.
6. Require human chemical approval for analogue substitutions, identity conflicts and route mismatches.
7. Emit the experiment-ready reagent list and a separate exploratory-exception register, then preserve sample, workbook, sheet, row and condition identifiers after execution.

## Outputs

- Candidate-to-reagent relationship matrix and rationale.
- Feasibility and identity-review ledger.
- Experiment-ready reagent and condition records.
- Actual-input NP/NR assessment, unresolved records and exclusions.
- Source-linked execution ledger.

Run the deposited validation from the repository root:

```bash
python3 skills/recommended-nucleophiles-to-experimental-reagents/scripts/run.py \
  --output /tmp/experimental_reagent_ledger.json
```

To validate a new reviewed translation bundle, pass its candidate registry and candidate-to-experiment decision ledger explicitly:

```bash
python3 skills/recommended-nucleophiles-to-experimental-reagents/scripts/run.py \
  --candidates /path/to/candidates.json \
  --mapping /path/to/experiment_decisions.json \
  --hypotheses /path/to/hypotheses.json \
  --output /tmp/new_experimental_reagent_ledger.json
```

The skill workflow performs identity, feasibility, novelty and human chemical review. The bundled command validates and exports the deposited correspondence and execution ledger: it checks route sites and reacting-atom indices, route-compatible hypotheses, exact-identity structures, relationship-category partitions, identity flags, NP/NR presence and source-occurrence closure, then records input hashes. It does not reconstruct undocumented selection decisions, infer missing procurement facts or infer reaction outcomes.

An analogue relationship is a proposal for chemical review, not proof that two molecules are interchangeable.

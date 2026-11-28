# Reusable chemical-design skills

Two linked skills formalize the study workflow as reusable, auditable operations:

1. [RP to recommended nucleophiles](rp-to-recommended-nucleophiles/) converts classified, source-linked evidence and reviewed reaction principles into a chemically diverse candidate set with evidence–RP–family–molecule traceability.
2. [Recommended nucleophiles to experimental reagents](recommended-nucleophiles-to-experimental-reagents/) converts the candidate set into an experiment-ready reagent list through identity, structural-relation, feasibility, novelty and human-review gates, then preserves source-linked execution records.

The skills summarize the procedures used in the study; they do not replace the deposited scientific data or the chemical review recorded in those data. Use Python 3.12, matching the repository replay environment, and run both validations from the repository root:

```bash
python3 -m pip install -r skills/requirements.txt
python3 skills/rp-to-recommended-nucleophiles/scripts/run.py \
  --output /tmp/rp_candidate_traceability.json
python3 skills/recommended-nucleophiles-to-experimental-reagents/scripts/run.py \
  --output /tmp/experimental_reagent_ledger.json
```

The release gates use RDKit to parse structures, canonicalize exact matches and verify zero-based reactive-atom assignments. Each output records the resolved input paths and SHA-256 hashes of the validated bundle.

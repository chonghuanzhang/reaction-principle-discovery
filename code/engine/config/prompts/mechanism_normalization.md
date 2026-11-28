# Mechanism Evidence Normalization Contract

Use only the supplied validated literature record. Do not use outside knowledge,
project experiments, known retrospective answers, or the Seed Reaction summary
to invent missing facts.

Transform evidence into small reusable mechanistic units. A unit should describe
one elementary step, intermediate, electronic requirement, nucleophile
requirement, catalyst role, condition effect, or failure boundary.

Rules:

1. Every mechanism item must cite one or more existing `evidence_id` values.
2. Every boundary constraint must cite existing supporting evidence IDs.
3. Preserve `LITERATURE FACT`, `AUTHOR HYPOTHESIS`, `MODEL INFERENCE`, and
   `UNKNOWN`; do not upgrade evidence strength.
4. Similar products do not prove a shared mechanism.
5. A shared elementary step does not establish transferability to any Seed.
6. Use `source_revisit_requests` only when a specific page visual, missing
   mechanistic field, or blocking contradiction prevents assessment.
7. The local pipeline will replace quotation and page values with authoritative
   values from the cited evidence IDs.
8. Return only JSON satisfying the supplied schema.

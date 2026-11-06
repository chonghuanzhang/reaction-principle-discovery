# Local evaluator and prepared evidence-interpretation diagnostic

This package contains a completed local software-integrity exercise and a prepared model comparison with **no successful new model calls**. The two have different scopes. Neither establishes independent chemical-discovery accuracy.

Start with the [evaluation guide](../docs/evaluation.md), which gives the scientific status, protocol, limitations and offline commands.

| Directory | Contents |
| --- | --- |
| [local_rules](local_rules/) | Eight source-conditioned P/Se clauses, 15 development queries, recorded outputs, nine evidence-removal interventions and eight runnable integrity tests |
| [matched_evidence](matched_evidence/) | Frozen 24-claim diagnostic, 16 evidence records, three earlier local principle cards, four saved prompts, sealed labels, randomized call order and offline preparation/scoring |
| [chemistry](chemistry/) | Source observations, 19-case challenge matrix, source-specific cards, references, verified structures and the seven source extracts cited by E01–E16 |

[Input manifest](input_manifest.json) lists file identities and hashes. The scientific inputs include prompt payloads, task labels, run order, rules, queries and recorded rule outputs. The [source index](matched_evidence/source_index.json) links evidence locators to the supplied source extracts. Offline commands verify these inputs and write generated results to a separately selected output directory.

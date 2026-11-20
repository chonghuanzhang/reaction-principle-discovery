# Completed local rule-integrity evaluation

This package contains the completed source-conditioned P/Se rule-integrity exercise. It is a development and software check on reviewed cases, not an independent chemical-validation set or an estimate of reaction-success accuracy.

Start with the [evaluation guide](../docs/evaluation.md), which gives the scientific status, protocol, limitations and offline commands.

| Directory | Contents |
| --- | --- |
| [local_rules](local_rules/) | Eight source-conditioned P/Se clauses, 15 development queries, recorded outputs, nine evidence-removal interventions and eight runnable integrity tests |

The reviewed [chemistry inputs](chemistry/) contain the source observations, 19-case challenge matrix, source-specific cards, references, verified structures and seven source extracts cited by E01–E16. The [input manifest](input_manifest.json) records hashes for those inputs and the completed rule artifacts.

Run `python -m unittest -v test_conditional_rules.py` from `code/evaluation/local_rules/` to repeat the integrity tests. No model call is made.

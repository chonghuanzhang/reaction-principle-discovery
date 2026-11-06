# Frozen candidate-generation calls

This directory preserves the inputs, configurations, saved model responses and core source snapshot for the primary and compact-expansion calls. The complete reviewed collection contains **100 molecules**, with 48 selected and 52 reserve entries in the exploration panel. This is a computational budget selection; each molecule retains its own hypothesis and uncertainty.

From `code/`, run `python scripts/replay_candidates.py`. The wrapper makes a temporary copy and checks both saved calls without contacting a model service. The code snapshot must remain unchanged because the calls bind its core-file digests. Saved call records are scientific inputs to replay, including model, prompt, retrieval and response metadata.

The original collection file retains its literal Chinese scientific explanations. English candidate tables are in `../../candidates/`. The complete collection covers more motifs than the selected subset alone. Hypotheses and proposed products are not validated experimental outcomes or dosing instructions.

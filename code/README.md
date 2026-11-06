# Reproducing the chemical workflow

This directory contains the programs, frozen inputs, prompts and saved model responses behind the literature-to-candidate workflow. The principal scientific records are presented in [literature](../literature/), [evidence](../evidence/) and [candidates](../candidates/). Start there to inspect chemistry; use this directory to trace how records were processed and to reproduce the computations.

The candidate-generation inputs contain **342 sources and 3,694 downstream evidence statements**. The current literature collection contains **370 sources and 3,756 statements**. These are different datasets: later literature enriches the chemical interpretation, while the saved generation calls remain bound to their actual inputs. The five working constraints in the generation calls and the four reaction principles in the paper also describe different representations. The supplied records preserve both.

## Find a computation

| Scientific question | Program or data |
|---|---|
| What source evidence and prompts entered generation? | `data/generation/` contains the 342-source registry, evidence, 4,391 transfer assessments, seed evidence, prompts, evidence links and recorded API metadata. |
| Can the saved candidate calls be checked? | `scripts/replay_candidates.py` checks both saved calls against their input, prompt, model and core-code bindings in `candidate_workflow/`. |
| How were the five working constraints admitted and reviewed? | `principles/proposal_admission.py`, the original induction/review functions in `engine/`, and saved responses in `data/principle_calls/`; run `scripts/replay_principle_review.py`. |
| What limits transfer of a structural precedent? | `data/transfer_scope_examples.json` and `.csv` give three source-linked C–C/C–N/C–O examples; see [METHODS.md](METHODS.md). |
| How are source identities merged without changing earlier records? | `literature/merge_catalog.py` and `engine/pipeline/evidence_applicability.py`. |
| How do candidate and experimental structures correspond? | `mapping/build_mapping.py`; frozen structures and workbook-row occurrences in `data/structures/`; numerical reference records in `data/mapping/`. |
| How were NP/NR labels revised? | `novelty/apply_review.py`, baseline and reviewed tables in `data/novelty/`, and 202 stored PubChem responses. |
| How are Figures 2–4 drawn? | `figures/` contains vector drawing functions; `data/figures/` holds centre counts; `data/graph/` contains network records and Figure 3 geometry. |
| How is Figure 5 reproduced? | The separate, complete [optimization](../optimization/) subsystem. |

`engine/` contains the general pipeline modules, schemas, configuration files and prompt templates. `candidate_workflow/engine/` is the exact source snapshot bound to the saved candidate calls. This second copy is needed because changing a bound source file would change the replay digest. JSON data retain the original scientific fields, identifiers, wording and dates; reader tables elsewhere offer a simpler view.

## Run without a model service

Use Python 3.12. Create a local environment and install the pinned replay dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-replay.txt
export PYTHONDONTWRITEBYTECODE=1
python scripts/replay_candidates.py
python scripts/replay_principle_review.py
python scripts/reproduce_novelty.py
python scripts/reproduce_mapping.py
```

Run these commands from `code/`. They use saved responses and local inputs, make no network or model calls, and write temporary computations outside the supplied datasets. An optional `--output /path/check.json` saves the comparison result.

The two test suites use the same Python package name and should run separately:

```bash
(cd engine && python -m pytest -q tests/test_evidence_applicability.py tests/test_evidence_update_catalog.py)
(cd candidate_workflow/engine && python -m pytest -q tests/test_exploration_panel.py tests/test_panel_review.py tests/test_panel_coverage.py)
```

For vector figures, install the additional dependencies and choose a separate output directory:

```bash
python -m pip install -r requirements-figures.txt
python scripts/reproduce_figures2_4.py --output-dir /tmp/reaction-figures24
python scripts/reproduce_figure3.py --output-dir /tmp/reaction-figure3 --render
```

Figures 2 and 4 are rebuilt from chemical structures and drawing functions. The PDF check requires one page and no embedded raster image. Figure 3 is reconstructed from the complete network SVG and compared with the supplied SVG tree before export. DejaVu Sans is the default font for Figures 2 and 4; `--font-file` accepts another installed TTF. Typeface and software versions can change artwork bytes or text placement.

Replaying saved model outputs validates their recorded inputs and deterministic admission rules. It does not generate a new answer or test the reliability of a new model call. A new live run requires reviewed source inputs, a configured service and credentials, and may return different scientific hypotheses. See [METHODS.md](METHODS.md) for the assumptions and counting units.

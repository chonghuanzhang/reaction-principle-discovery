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
| How were experimental reagents selected, and how do their structures correspond to candidates? | [Selection criteria and Figure 4d](../candidates/reagent_selection.md); `mapping/build_mapping.py`; frozen structures and workbook-row occurrences in `data/structures/`; numerical reference records in `data/mapping/`. |
| How were NP/NR labels revised? | `novelty/apply_review.py`, baseline and reviewed tables in `data/novelty/`, and 202 stored PubChem responses. |
| How are Figures 2–4 reproduced? | `figures/` draws Figure 2 and composes Figure 4 from [deposited artwork](../figures/); [`knowledge_graph/`](../knowledge_graph/) contains network records, Figures G1–G9 and Figure 3 geometry. |
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

For figure reproduction, install the additional dependencies and choose a separate output directory:

Figure 3 PDF/PNG export also requires `rsvg-convert` from librsvg. Install it with `brew install librsvg` on macOS or `sudo apt-get install librsvg2-bin` on Debian/Ubuntu. This renderer preserves the dashed conditional-application edges and their transparency in the SVG; PyMuPDF then rasterizes the exported PDF.

```bash
python -m pip install -r requirements-figures.txt
python scripts/reproduce_figures2_4.py --output-dir /tmp/reaction-figures24
python scripts/reproduce_figure3.py --output-dir /tmp/reaction-figure3 --render
python -m unittest discover -s tests -v
```

Figure 2 is rebuilt from chemical structures and vector drawing functions; its PDF check requires one page and no embedded raster image. DejaVu Sans is its default font, and `--font-file` accepts another installed TTF. Typeface and software versions can change Figure 2 artwork bytes or text placement.

Figure 4 is a deterministic Pillow composition of the deposited a–c crop and panel d selection scheme, following [source metadata](../figures/source/Figure_4_composition.json). Its authoritative output is the [PNG master](../figures/main/Figure_4.png); the script checks exact reconstructed pixels and also exports JPEG and a PDF containing raster artwork. Panels a–c retain their source pixels. Figure 4 is not regenerated as an all-vector drawing, and the font option does not alter its deposited artwork. The complete novelty-distribution chart remains [Repository N1 / Supplementary Figure 5](../candidates/novelty_assessment.md).

Figure 3 is reconstructed from the complete network SVG and compared with the supplied SVG tree before export. Its PDF retains 23 dashed conditional-application paths and one dashed legend path; the rendering tests also check evidence-edge transparency.

Replaying saved model outputs validates their recorded inputs and deterministic admission rules. It does not generate a new answer or test the reliability of a new model call. A new live run requires reviewed source inputs, a configured service and credentials, and may return different scientific hypotheses. See [METHODS.md](METHODS.md) for the assumptions and counting units.

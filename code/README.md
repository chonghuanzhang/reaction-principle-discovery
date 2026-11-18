# Reproducing the evidence-to-recommendation workflow

This directory contains the processing and validation code behind the literature, reaction-principle, recommendation and recommendation-to-experiment records. The reader-facing chemistry is under [`literature/`](../literature/), [`evidence/`](../evidence/), [`candidates/`](../candidates/) and [`knowledge_graph/`](../knowledge_graph/).

The current molecular package is uniquely identified by 100 recommended nucleophiles, 103 reacting-site/pathway hypotheses, 103 proposed product connectivities and 43 precursor families. Its public JSON files and hashes are collected in [`candidate_workflow/artifacts/released/`](candidate_workflow/artifacts/released/). No separate candidate set is designated as current.

## Main resources

| Question | Resource |
| --- | --- |
| How are literature evidence and the four RPs connected? | `principles/`, `data/principle_calls/` and [`../evidence/principles/`](../evidence/principles/) |
| What is the current recommendation package? | `candidate_workflow/artifacts/released/` and [`../candidates/`](../candidates/) |
| How are recommendations related to experimental inputs? | `data/mapping/`, [`../candidates/reagent_selection.md`](../candidates/reagent_selection.md) and Table R1 |
| How are proposed endpoints and NP/NR labels represented? | `data/novelty/reviewed/` and Table R2 |
| How are the main figures reproduced? | `figures/`, [`../knowledge_graph/`](../knowledge_graph/) and [`../figures/`](../figures/) |
| How is condition optimization reproduced? | the separate [`../optimization/`](../optimization/) package |

## Offline checks

From the repository root, run:

```bash
python tools/check_data.py
python code/scripts/validate_candidate_release.py
```

The first command checks repository-wide table counts, identifier closure, network relations, figure metadata and local links. The second checks the 100/103/103 recommendation package, experimental correspondence and release hashes. Both use deposited files and make no network or model call.

Generic pipeline components remain in `engine/` and `candidate_workflow/engine/`. They document reusable processing logic; the authoritative scientific outputs are the released JSON files identified above.

See [METHODS.md](METHODS.md) for the scientific counting units and interpretation limits.

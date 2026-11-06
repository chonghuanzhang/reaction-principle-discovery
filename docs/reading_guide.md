# Reading the article, SI and repository together

Start with the scientific question in the article, use the SI for detailed methods and experimental characterization, and follow the links below to inspect the individual records behind the analyses. The same identifiers connect the three resources.

## Where to find each resource

| Article or SI topic | Repository resource | What the reader can inspect |
|---|---|---|
| Literature selection; SI S2 and S9 | [Literature catalog](../literature/) and [online bibliography](../literature/bibliography.md) | Publication identities, DOI links, numbered references and each source's contribution |
| Source-specific applicability; SI S2.6 | [Source cases](../evidence/source_cases/) | Donor, acceptor, activation, conditions, endpoint and limits of transfer |
| Reaction principles; SI S3 | [Quoted passages Q01–Q43](../evidence/quotations/) and [principle cards](../evidence/principles/) | The observations or interpretations supporting each chemical argument |
| Evidence network; main Fig. 3 and SI S5.1–S5.2 | [Network guide and Figures G1–G9](../code/docs/evidence_network.md) | Source summaries, precursor families, candidate citations and conditional applications |
| Molecular recommendations; SI S5.3–S5.4 | [Candidate catalog](../candidates/) and [structure atlas C1–C9](../candidates/structure_atlas.md) | 100 input structures, reactive sites, pathway hypotheses, citations and assessments |
| Novelty; main Fig. 4 and SI S5.6 | [Assessment guide and Figure N1](../candidates/novelty_assessment.md) | Search scope, NP/NR definitions, unresolved cases and distributions |
| Candidate–experiment association; SI S5.5 | [Table R1](../candidates/experiment_mapping/) | All 108 recorded electrophile–donor pairs and their structural relationships to recommendations |
| Proposed product connectivity; SI S5.6 | [Table R2](../candidates/product_options/) | 124 product-option records, registry comparisons and NP/NR assessments |
| Base and solvent library; SI S6.2 | [Condition library](../experiments/condition_library/) | Twelve base/additive entries and eight solvents with chemical context |
| Sulfur selection benchmark; SI S6.5 | [Table R3](../experiments/bo_benchmark/) | 100 paired seeds, first-hit budgets and paired savings |
| Nitrogen/oxygen selection; SI S6.6–S6.7 | [Table R4](../experiments/selected_responses/) | 180 selected responses, with system, batch, condition and analytical unit |
| Model operations; SI S4 | [Model workflow](../code/docs/model_workflow.md) | Exact prompts, original working constraints, validation rules and saved model responses |
| Condition-selection methods; SI S6 | [Optimization methods](../optimization/METHODS.md) | Model equations, seeds, acquisition rule, benchmark and interpretation limits |
| Response and uncertainty diagnostics; main Fig. 5 and SI S8.3 | [Figures BO1–BO3](../optimization/FIGURE_GUIDE.md) | Complete legends, condition keys, measured responses, posterior uncertainty and stopping checks |
| Method evaluation; SI S8.1 | [Evaluation protocol](../code/docs/evaluation.md) | Frozen comparison design, source-case development tests and execution status |
| Computational reproduction | [Code](../code/) and [optimization](../optimization/) | Original inputs, algorithms, environments and reproduction commands |

## Following the identifiers

**L001–L370** identify literature source records. **Q01–Q43** identify attributed passages used in the principle analysis. **RP1–RP4** identify the four chemical principles. **C001–C100** identify recommended input molecules. These identifiers retain their meaning across figures, the SI and repository pages. The numbered bibliography contains 403 references, including the 370 L records and 33 background references.

Square-bracket reference numbers in the SI point to the [online bibliography](../literature/bibliography.md). Its complete entries and the [reference correspondence](../literature/reference_correspondence.md) are provided here. The article has its own reference numbering; the correspondence table links it to the same source identities.

**Tables R1–R4** are repository tables. They are distinct from the SI's Tables 1–3, which contain experimental preparation records. The SI's **Figure 1** shows the well-position index. **Figures G1–G9**, **C1–C9**, **N1** and **BO1–BO3** identify the online network views, structure atlas, novelty distributions and optimization diagnostics, respectively. Product-option and hypothesis identifiers are finer than C identifiers: one input molecule can have more than one reacting site, pathway or proposed endpoint.

## Reading chemical evidence and scores

An evidence page distinguishes what a publication reports from the interpretation proposed by its authors and the hypothesis being transferred to this target. An unavailable full text, an unreported substrate and a reported failed reaction are different evidence states.

NP describes product-connectivity novelty and NR describes reaction novelty within the documented search. The [candidate guide](../candidates/) explains the categories and shows the assessments for each molecule. Neither label is a calibrated probability of success. Mixed, unresolved and inapplicable cases remain visible rather than being assigned an artificial zero.

For interpretation of study units, experimental responses and computational comparisons, see [How to interpret the data](interpretation.md).

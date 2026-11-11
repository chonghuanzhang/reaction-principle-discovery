# Reading the article, SI and repository together

Start with the scientific question in the article, use the SI for detailed methods and experimental characterization, and follow the links below to inspect the individual records behind the analyses. The same identifiers connect the three resources.

## Where to find each resource

| Article or SI topic | Repository resource | What the reader can inspect |
|---|---|---|
| Literature selection; SI S2 and S9 | [Literature catalog](../literature/) and [online bibliography](../literature/bibliography.md) | Publication identities, DOI links, numbered references and each source's contribution |
| Source-specific applicability; SI S2.6 | [Source cases](../evidence/source_cases/) | Donor, acceptor, activation, conditions, endpoint and limits of transfer |
| Reaction principles; SI S3 | [Quoted passages Q01–Q43](../evidence/quotations/) and [principle cards](../evidence/principles/) | The observations or interpretations supporting each chemical argument |
| Evidence network; main Fig. 3, Supplementary Figs. 1–4 and SI S5.1–S5.2 | [Network guide and Figures G1–G9](../knowledge_graph/) | Source summaries, precursor families, candidate citations and conditional applications |
| Molecular recommendations; SI S5.3–S5.4 | [Candidate catalog](../candidates/) and [structure atlas C1–C9](../candidates/structure_atlas.md) | 100 input structures, reactive sites, pathway hypotheses, citations and assessments |
| Candidate-to-reagent selection; main Fig. 4d and SI S5.5–S5.6 | [Selection guide and Figure 4d](../candidates/reagent_selection.md) | How structural relationships, commercial accessibility and separate NP/NR classifications informed researcher judgment |
| Novelty; Supplementary Fig. 5 and SI S5.6 | [Assessment guide and Figure N1](../candidates/novelty_assessment.md) | Search scope, NP/NR definitions, unresolved cases and complete distributions |
| Candidate–experiment association; SI S5.5 | [Table R1](../candidates/experiment_mapping/) | All 108 recorded electrophile–donor pairs and their structural relationships to recommendations; these associations do not independently document individual substitution decisions |
| Proposed product connectivity; SI S5.6 | [Table R2](../candidates/product_options/) | 124 product-option records, registry comparisons and NP/NR assessments |
| Base and solvent library; SI S6.2 | [Condition library](../experiments/condition_library/) | Twelve base/additive entries and eight solvents with chemical context |
| Sulfur selection benchmark; SI S6.5 | [Table R3](../experiments/bo_benchmark/) | 100 paired seeds, first-hit budgets and paired savings |
| Nitrogen/oxygen selection; SI S6.6–S6.7 | [Table R4](../experiments/selected_responses/) | 120 selected responses, with system, batch, condition and analytical unit |
| Model operations; SI S4 | [Model workflow](../code/docs/model_workflow.md) | Exact prompts, original working constraints, validation rules and saved model responses |
| Condition-selection methods; SI S6 | [Optimization methods](../optimization/METHODS.md) | Model equations, seeds, acquisition rule, benchmark and interpretation limits |
| Response and uncertainty diagnostics; main Fig. 5, Supplementary Figs. 7–9 and SI S8.3 | [Figures BO1–BO3](../optimization/FIGURE_GUIDE.md) | Complete legends, condition keys, measured responses, posterior uncertainty and stopping checks |
| Method evaluation; SI S8.1 | [Evaluation protocol](../code/docs/evaluation.md) | Frozen comparison design, source-case development tests and execution status |
| Computational reproduction | [Code](../code/) and [optimization](../optimization/) | Original inputs, algorithms, environments and reproduction commands |

## Following the identifiers

**L001–L370** identify literature source records. **Q01–Q43** identify attributed passages used in the principle analysis. **RP1–RP4** identify the four chemical principles. **C001–C100** identify recommended input molecules. These identifiers retain their meaning across figures, the SI and repository pages. The numbered bibliography contains 403 references, including the 370 L records and 33 background references.

Square-bracket reference numbers in the SI point to the [online bibliography](../literature/bibliography.md). Its complete entries and the [reference correspondence](../literature/reference_correspondence.md) are provided here. The article has its own reference numbering; the correspondence table links it to the same source identities.

**Tables R1–R4** are repository tables. The SI's **Tables 1–3** give the condition key, fixed reaction systems and stopping diagnostics; **Tables 4–6** contain experimental preparation records. **Figures G1–G9**, **C1–C9**, **N1** and **BO1–BO3** remain stable repository identifiers for the network views, structure atlas, novelty distributions and optimization diagnostics. Product-option and hypothesis identifiers are finer than C identifiers: one input molecule can have more than one reacting site, pathway or proposed endpoint.

## Supplementary figure correspondence

| SI figure | Content | Repository artwork or guide |
| --- | --- | --- |
| Supplementary Figure 1 | RP1 focus | [RP1 focus PNG](../knowledge_graph/figures/RP1_focus.png), cropped from G2 |
| Supplementary Figure 2 | RP2 focus | [RP2 focus PNG](../knowledge_graph/figures/RP2_focus.png), cropped from G3 |
| Supplementary Figure 3 | RP3 focus | [RP3 focus PNG](../knowledge_graph/figures/RP3_focus.png), cropped from G4 |
| Supplementary Figure 4 | RP4 focus | [RP4 focus PNG](../knowledge_graph/figures/RP4_focus.png), cropped from G5 |
| Supplementary Figure 5 | Complete NP and NR distributions | [N1 PNG](../candidates/figures/N1_novelty_distributions.png), [SVG](../candidates/figures/N1_novelty_distributions.svg) and [assessment guide](../candidates/novelty_assessment.md) |
| Supplementary Figure 6 | Well-position index | Plate-index schematic in the SI; [condition-library identities](../experiments/condition_library/) are provided here |
| Supplementary Figure 7 | Selected responses, posterior landscapes and uncertainty | [BO1 artwork and legend](../optimization/FIGURE_GUIDE.md#bo1) |
| Supplementary Figure 8 | Latent uncertainty and stopping diagnostics | [BO2 artwork and legend](../optimization/FIGURE_GUIDE.md#bo2) |
| Supplementary Figure 9 | Measured sulfur landscape and replay diagnostics | [BO3 artwork and legend](../optimization/FIGURE_GUIDE.md#bo3) |

The [knowledge-graph guide](../knowledge_graph/#principle-focus-views) explains the evidence and conditional relationships shown in Supplementary Figures 1–4 and provides the complete G1–G9 artwork.

## Reading chemical evidence and scores

An evidence page distinguishes what a publication reports from the interpretation proposed by its authors and the hypothesis being transferred to this target. An unavailable full text, an unreported substrate and a reported failed reaction are different evidence states.

NP describes product-connectivity novelty and NR describes reaction novelty within the documented search. The [candidate guide](../candidates/) explains the categories and shows the assessments for each molecule. Researchers considered these classifications before finalizing the experimental reagent list, alongside structural relationships and commercial accessibility, without a fixed cutoff or weighted total. Neither label is a calibrated probability of success. Actual-input classifications evaluate the donor, electrophile and proposed endpoint; they are not inherited from a structurally related candidate. Mixed, unresolved and inapplicable cases remain visible rather than being assigned an artificial zero or replaced by the highest category.

Main Figure 4d illustrates this selection process. Its [artwork sources](../figures/) and [full Figure 4 PNG](../figures/main/Figure_4.png) are supplied separately from the complete NP/NR distribution chart in Repository N1 / Supplementary Figure 5. The final 100 experimental donors, 102 archived donor structures and 108 ordered experimental pairs are distinct counting units, as explained in the [selection guide](../candidates/reagent_selection.md#selection-criteria-and-counting-units).

For interpretation of study units, experimental responses and computational comparisons, see [How to interpret the data](interpretation.md).

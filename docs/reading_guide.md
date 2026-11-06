# Reading the article, SI and repository together

Start with the scientific question in the article, use the SI for detailed methods and experimental characterization, and follow the links below to inspect the individual records behind the analyses. The same identifiers connect the three resources.

## Where to find each resource

| Article or SI topic | Repository resource | What the reader can inspect |
|---|---|---|
| Literature selection; SI S2 and S9.1 | [Literature catalog](../literature/) | Publication identities, DOI links, numbered SI references and each source's contribution |
| Source-specific applicability; SI S2.6 | [Source cases](../evidence/source_cases/) | Donor, acceptor, activation, conditions, endpoint and limits of transfer |
| Reaction principles; SI S3.5 and Table 3 | [Quoted passages Q01–Q43](../evidence/quotations/) and [principle cards](../evidence/principles/) | The observations or interpretations supporting each chemical argument |
| Molecular recommendations; SI S5.4 and Figs. 10–18 | [Candidate catalog](../candidates/) | 100 input structures, reactive sites, pathway hypotheses, citations and assessments |
| Candidate–experiment association; SI S5.5 | [Table R1](../candidates/experiment_mapping/) | All 108 recorded electrophile–donor pairs and their structural relationships to recommendations |
| Proposed product connectivity; SI S5.6 | [Table R2](../candidates/product_options/) | 124 product-option records, registry comparisons and NP/NR assessments |
| Base and solvent library; SI S6.2 | [Condition library](../experiments/condition_library/) | Twelve base/additive entries and eight solvents with chemical context |
| Sulfur selection benchmark; SI S6.5 | [Table R3](../experiments/bo_benchmark/) | 100 paired seeds, first-hit budgets and paired savings |
| Nitrogen/oxygen selection; SI S6.6–S6.7 | [Table R4](../experiments/selected_responses/) | 180 selected responses, with system, batch, condition and analytical unit |
| Computational methods | [Code](../code/) and [optimization](../optimization/) | Original inputs, saved model responses, algorithms and reproduction commands |

## Following the identifiers

**L001–L370** identify literature source records. **Q01–Q43** identify attributed passages used in the principle analysis. **RP1–RP4** identify the four chemical principles. **C001–C100** identify recommended input molecules. These identifiers retain their meaning across figures, the SI and repository pages. The numbered bibliography contains 403 references, including the 370 L records and 33 background references.

**Tables R1–R4** are repository tables. They are distinct from the SI's Tables 1–11. The SI's Figures 1–23 retain their own numbering. Product-option and hypothesis identifiers are finer than C identifiers: one input molecule can have more than one reacting site, pathway or proposed endpoint.

## Reading chemical evidence and scores

An evidence page distinguishes what a publication reports from the interpretation proposed by its authors and the hypothesis being transferred to this target. An unavailable full text, an unreported substrate and a reported failed reaction are different evidence states.

NP describes product-connectivity novelty and NR describes reaction novelty within the documented search. The [candidate guide](../candidates/) explains the categories and shows the assessments for each molecule. Neither label is a calibrated probability of success. Mixed, unresolved and inapplicable cases remain visible rather than being assigned an artificial zero.

For interpretation of study units, experimental responses and computational comparisons, see [How to interpret the data](interpretation.md).

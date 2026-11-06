# Reaction principle guided selective defluorinative reaction discovery

Research materials accompanying **Large Language Model-Driven Knowledge Transfer Enables Selective Defluorinative Reaction Discovery**.

This study asks how published chemical knowledge can guide the choice of reaction partners for selective defluorinative functionalization of trifluoroethyl carbonyl compounds. This repository lets readers examine the supporting literature, follow the reasoning behind **100 recommended molecules**, inspect their novelty assessments, and reproduce the computational analyses of measured reaction screens.

The article presents the scientific argument. The Supplementary Information (SI) provides detailed methods, experimental procedures, characterization and spectra. This repository provides searchable reference materials, molecular records, numerical data and code cited by the article and SI.

## Explore the research

| What would you like to examine? | Start here |
|---|---|
| Which publications informed the study? | [Literature catalog and bibliography](literature/) — 370 source records and 403 online references |
| What did those publications actually report? | [Chemical evidence](evidence/) — source passages, conditions, endpoints and limits of applying them to this target |
| How are evidence, principles and candidate families connected? | [Knowledge graph · Figures G1–G9](knowledge_graph/) — all network views, Supplementary Figures 1–4, linked evidence, graph data and vector artwork |
| Why were particular molecules recommended? | [100 recommended molecules](candidates/) — structures, chemical rationale, proposed pathways, references and novelty assessments |
| How were candidates used to choose experimental reagents? | [Selection criteria and Figure 4d](candidates/reagent_selection.md), with [candidate–experiment associations · Table R1](candidates/experiment_mapping/) |
| Which products were proposed, and how was novelty assessed? | [Product options · Table R2](candidates/product_options/) and [NP/NR distributions · Supplementary Figure 5](candidates/novelty_assessment.md) |
| Which bases and solvents were considered? | [Condition library](experiments/condition_library/) |
| What responses were measured and how were conditions selected? | [Reaction screens and Bayesian selection](optimization/), [paired benchmark · Table R3](experiments/bo_benchmark/) and [selected responses · Table R4](experiments/selected_responses/) |
| How can I run the computational workflow? | [Code and installation instructions](code/) |

No programming is needed to read the catalogs. Each molecule and literature source has its own page; CSV and JSON files support further analysis. [Reading the article, SI and repository together](docs/reading_guide.md) explains the identifiers and cross-references, including the correspondence between Supplementary Figures 1–9 and repository artwork.

## From chemical evidence to candidate reactions

The target transformation retains the carbonyl group while replacing two C–F bonds of a trifluoroethyl carbonyl substrate to give a monofluoroalkene of the form **RCOCH=C(F)–Nu**. Evidence is organized around four chemical questions: how the acceptor is activated, which donor form can react, which pathways are available to the intermediate, and whether the proposed product can persist under the reaction conditions. Ketone and amide acceptors and alternative donor activation states remain distinguishable.

The [evidence pages](evidence/) connect these questions to reported observations and mechanistic interpretations. A successful reaction with a different substrate, donor form or endpoint can motivate a hypothesis, but does not by itself demonstrate the proposed target reaction. The pages therefore show both the useful precedent and its scope.

The [candidate collection](candidates/) contains **100 molecules**, with **115 site- or pathway-level hypotheses** and **124 proposed product-option records**. Individual entries retain alternative reactive sites and competing outcomes. The product-novelty (NP) and reaction-novelty (NR) assessments describe different questions within the documented literature search. They are ordinal categories, not predicted yields or probabilities of success; they should not be added or averaged into an overall score.

Researchers used structural relationships, commercial accessibility and NP/NR classifications when choosing experimental reagents from the candidates and related analogues. Final choices relied on researcher judgment without a fixed threshold or weighted total. The [reagent-selection guide](candidates/reagent_selection.md) explains this process, Figure 4d and the distinction between the final 100 experimental donors and the archived 102 donor structures / 108 electrophile–donor pairs.

## Reaction screening and condition selection

Four principal screens each contain measured responses for **96 base/additive–solvent combinations**. The sulfur benchmark compares Bayesian selection with random sampling on the same measured response grid, using 100 paired starting seeds. The median numbers of conditions required to encounter the highest recorded response are **24 and 48**, respectively. The mean paired saving is 25.8 conditions; the 95% paired-bootstrap interval is 20.88–30.72.

The three nitrogen/oxygen trajectories reconstruct selection in five batches of 12 from existing 96-condition screens. Their selected responses, posterior estimates and stopping diagnostics are supplied alongside the full measurements. MS and UV responses retain their original analytical units. The separately measured **37% NMR yield** belongs to the indicated sulfur maximum; response magnitudes in other cells are not percentage yields. See [optimization methods](optimization/METHODS.md) for the model, benchmark and interpretation.

## Using the files

```bash
git clone https://github.com/chonghuanzhang/reaction-principle-discovery.git
cd reaction-principle-discovery
python tools/check_data.py
```

The last command checks table sizes, identifiers and local links using the Python standard library. To replay candidate generation from saved model responses or rebuild the molecular analyses, follow [code/README.md](code/README.md). To reproduce Bayesian selection and Figure 5, follow [optimization/README.md](optimization/README.md). Each package specifies its environment and commands. The supplied inputs and saved responses allow offline reproduction; making new language-model calls requires separate provider access.

[Figure artwork](figures/) and the computational packages provide the corresponding image sources. The larger experimental workbook is stored in consecutive parts because of GitHub's file-size limit; the optimization package includes a command to reconstruct the complete workbook and verify it.

## Citation and reuse

Please cite the accompanying article when using these materials; repository citation metadata are in [CITATION.cff](CITATION.cff). Author-created code and materials are released under the [MIT License](LICENSE). Attributed quotations, bibliographic metadata and other third-party materials retain their original rights. Full publications can be accessed through the links in the literature catalog.

For questions or corrections, identify the relevant source, candidate, product option or experimental sample as described in [CONTRIBUTING.md](CONTRIBUTING.md).

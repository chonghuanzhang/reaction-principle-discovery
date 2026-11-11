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

Each S–H, N–H and O–H condition library contains **96 measured formulation–solvent combinations** (12 formulations × eight solvents). A formulation comprises the catalyst, ligand where present, and base/additive. S–H and N–H keep CuCl/PPh3 and Ag2SO4/PPh3 fixed, respectively, while varying the base/additive; O–H formulations include the specified Cu or Ni catalyst and base. The models use formulation and solvent identities and their interactions. Figure axes use the common label **Formulation** and system-specific F1–F12 keys; an F number does not denote the same chemical formulation across systems. The retrospective sulfur benchmark compares Bayesian selection with random sampling on the same measured response grid, using 100 paired starting seeds. The median numbers of conditions required to encounter the highest recorded response are **24 and 48**, respectively. The mean paired saving is 25.8 conditions; the 95% paired-bootstrap interval is 20.88–30.72.

Bayesian condition selection is reported for **one nitrogen and one oxygen system**. The O–H library includes the Cu/K3PO4 and Ni/DIPEA reference formulations containing the known highest-response Cu and Ni recipes, plus ten formulation identities sampled from the other 22 with seed 20261111. The [formulation manifest](optimization/selections/OH_CuNi_96/candidate_manifest.json) gives the construction rule and source-cell linkage; formulation identity and solvent are the two optimized factors. The accompanying posterior analysis uses **60 selected responses per system**, organized into five computational batches of 12, for **120 model-input records**. The O–H library maximum is NiCl₂·DME/DIPEA/DCE (UV response 1.4425; PL38-W10), already present in the initial batch. Numerical batch order and seeds identify the reproducible response-selection calculation separately from laboratory execution records. UV responses are analytical signals, not percentage yields. The separately measured **37% NMR yield** belongs to the indicated sulfur maximum. See [optimization methods](optimization/METHODS.md) for the model, benchmark and interpretation.

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

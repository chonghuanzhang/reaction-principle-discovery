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
| How can the two design transitions be reused? | [Executable skills](skills/) — RP-to-nucleophile recommendation and nucleophile-to-experimental-reagent selection |
| Why were particular molecules recommended? | [100 recommended molecules](candidates/) — structures, chemical rationale, proposed pathways, references and novelty assessments |
| How were candidates used to choose experimental reagents? | [Selection criteria and Figure 4d](candidates/reagent_selection.md), with [candidate–experiment associations · Table R1](candidates/experiment_mapping/) |
| Which products were proposed, and how was novelty assessed? | [Product options · Table R2](candidates/product_options/) and [NP/NR distributions · Supplementary Figure 5](candidates/novelty_assessment.md) |
| How are the 40 products, 35 positive donors, 102 experimental donors and 108 pairs counted? | [Product and experiment counting units](docs/product_scope.md) |
| Which bases and solvents were considered? | [Condition library](experiments/condition_library/) |
| What responses were measured and how were conditions selected? | [Reaction screens and Bayesian selection](optimization/), [trajectories and stopping · Table R3](experiments/bo_trajectories/) and [selected responses · Table R4](experiments/selected_responses/) |
| How can I run the computational workflow? | [Code and installation instructions](code/) |

No programming is needed to read the catalogs. Each molecule and literature source has its own page; CSV and JSON files support further analysis. [Reading the article, SI and repository together](docs/reading_guide.md) explains the identifiers and cross-references, including the correspondence between Supplementary Figures 1–9 and repository artwork.

## From chemical evidence to candidate reactions

The target transformation retains the carbonyl group while replacing two C–F bonds of a trifluoroethyl carbonyl substrate to give a monofluoroalkene of the form **RCOCH=C(F)–Nu**. Evidence is organized around four chemical questions: how the acceptor is activated, which donor form can react, which pathways are available to the intermediate, and whether the proposed product can persist under the reaction conditions. Ketone and amide acceptors and alternative donor activation states remain distinguishable.

The [evidence pages](evidence/) connect these questions to reported observations and mechanistic interpretations. A successful reaction with a different substrate, donor form or endpoint can motivate a hypothesis, but does not by itself demonstrate the proposed target reaction. The pages therefore show both the useful precedent and its scope.

The [candidate collection](candidates/) contains **100 molecules**, with **103 site- or pathway-level hypotheses** and **103 proposed product-option records**. Individual entries retain alternative reactive sites and competing outcomes. The product-novelty (NP) and reaction-novelty (NR) assessments describe different questions within the documented literature search. They are ordinal categories, not predicted yields or probabilities of success; they should not be added or averaged into an overall score.

Researchers used structural relationships, commercial accessibility and NP/NR classifications when choosing experimental reagents from the recommendations and related analogues. Final choices relied on researcher judgment without a fixed threshold or weighted total. The [reagent-selection guide](candidates/reagent_selection.md) explains this process, Figure 4d and the distinction among **100 recommended molecules, 102 unique experimental donor structures and 108 ordered electrophile–donor pairs**. These are different counting units; the recommendation and experimental collections are related through explicit identity, scaffold and donor-family links rather than a one-to-one assignment.

The two transitions are also packaged as [reusable skills](skills/). The first skill preserves the route from classified literature evidence through the four reaction principles and candidate families to each recommended nucleophile. The second applies identity, structural-relation, feasibility, novelty and human-review gates to convert recommendations into experiment-ready reagents and source-linked execution records.

## Reaction screening and condition selection

The N–H, O–H and S–H systems share a **13,920-condition decision space** comprising **145 catalyst–ligand and loading formulations, eight solvents and twelve bases**, informed by literature searches across the three systems. Each system was evaluated in a recorded laboratory campaign with a hierarchical Gaussian-process surrogate and UCB acquisition. Twelve uniformly sampled experiments initialized each model; four conditions were recommended per subsequent round, and the recorded UV responses were used in the next model update.

The deposited trajectories retain the twelve round-0 indices for each recorded initial batch. N–H, O–H and S–H first reached their highest measured responses in rounds **10, 9 and 7** and satisfied the common empirical stopping rule in rounds **12, 11 and 9**, respectively, after **60, 56 and 48 unique conditions**. The highest measured-response conditions are AgF/PPh₃/K₂CO₃/DCE (1.5470), NiCl₂·DME/DIPEA/DCE (1.4425) and CuCl/PPh₃/CsOH/DCE (3.2045). UV responses are compared within the same substrate–product pair and analytical conditions, not across systems as yields.

The earlier *Chemical Science* study demonstrated enrichment of high-yield conditions relative to random screening. This work transfers that optimization framework to three heteroatom reaction systems, so a random-screening baseline is not repeated. [Optimization methods](optimization/METHODS.md) give the current kernel, UCB parameters, shared stopping equation and exact reproduction commands. The measured 96-condition surfaces in Figure 5b–d are representative visualization grids, separate from the full recommendation space.

## Using the files

```bash
git clone https://github.com/chonghuanzhang/reaction-principle-discovery.git
cd reaction-principle-discovery
python tools/check_data.py
```

The last command checks table sizes, identifiers and local links using the Python standard library. To validate the deposited recommendation package or inspect the processing code, follow [code/README.md](code/README.md). The [optimization package](optimization/) provides the recorded Bayesian-selection data, methods and numerical verification commands.

[Figure artwork](figures/) and the computational packages provide the corresponding image sources. The larger experimental workbook is stored in consecutive parts because of GitHub's file-size limit; the optimization package includes a command to reconstruct the complete workbook and verify it.

## Citation and reuse

Please cite the accompanying article when using these materials; repository citation metadata are in [CITATION.cff](CITATION.cff). Author-created code and materials are released under the [MIT License](LICENSE). Attributed quotations, bibliographic metadata and other third-party materials retain their original rights. Full publications can be accessed through the links in the literature catalog.

For questions or corrections, identify the relevant source, candidate, product option or experimental sample as described in [CONTRIBUTING.md](CONTRIBUTING.md).

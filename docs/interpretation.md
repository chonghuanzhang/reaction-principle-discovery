# How to interpret the data

The materials connect literature knowledge, proposed chemistry and measured screening responses through the current four-RP framework: acceptor activation, donor speciation and capture, intermediate pathway divergence, and product persistence. The [principle cards](../evidence/principles/) provide their chemical scope. This guide explains distinctions that matter when comparing records or reusing the data.

## Literature and molecular records

The literature registry contains **370 source records and 3,756 entries**. The access and relevance review selected **342 source records and 3,694 extracted statements** for the candidate-generation evidence package. The full registry and selected model-input package are supplied separately so that the deposited calculation can be reproduced. L055 and L343 are preprint and published versions of one study; two source records therefore need not represent two independent studies. Metadata-only records identify publications but do not support a chemical observation.

The focused applicability review contains **25 records**, comprising **23 substantive observations or interpretations** and **two metadata-only records**. The [source coverage](../evidence/source_coverage.md) distinguishes primary literature tiers, current RP-supporting sources and original candidate citations.

The RP-guided workflow produced one released set of **100 recommended molecules**, associated with **103 site/pathway hypotheses** and **103 product-option records**. A product option is a proposed endpoint; it is neither an independently validated product nor necessarily a unique structure. All 100 candidates are traceable through precursor-family and RP links to source evidence; 75 additionally retain direct candidate-level citations.

The experimental structure dataset contains **112 ordered electrophile–donor pairs**, representing 102 unique donor structures and six electrophile structures, conditional on the recorded identities. These records are distinct from the 100 recommended molecules and are not joined one-to-one. Researchers considered structural relationships, commercial accessibility and NP/NR when selecting practical experimental inputs, using judgment without a fixed cutoff or weighted total. The [selection guide and Figure 4d](../candidates/reagent_selection.md) explain that process. The candidate-to-experiment ledger reports exact identity, scaffold/substituent variation, donor-family/different-scaffold relations and unmatched records separately in [Table R1](../candidates/experiment_mapping/).

The 112 pairs comprise **45 nitrogen, 44 oxygen, 21 sulfur and two phosphorus pairs**. Their primary candidate associations are **27 exact identities, 39 same-scaffold/substituent relations, 42 donor-family/different-scaffold relations and four unmatched pairs**. The screening workbooks contain **2,114 row occurrences** and **1,057 sample identifiers**, grouped into **1,066 sample-row groups**. The product structure register supplies four source rows with product identifiers and structures; it does not encode sample or condition identifiers. There are **1,064 recorded condition recipes** within the experimental-pair combinations. Repeated rows and reused identifiers must therefore be interpreted at the stated counting level, rather than counted as new molecules or independent experiments.

## Reported chemistry and proposed transfer

The [source cases](../evidence/source_cases/) retain the donor form, substrate, activation conditions and endpoint of each precedent. A phosphorus transformation with a positive 37% first-stage result is not a failed target-system reaction. Negative observations must be read within their own conditions and endpoint. Metadata-only references and missing substrate combinations cannot establish chemical failure.

The current four RP cards organize the source evidence, candidate rationales and applicability conditions. The [model workflow](../code/docs/model_workflow.md) describes their relationship to the released 43-family, 100-molecule package and its offline validation commands.

## Measurements and computational selection

N–H, O–H and S–H independently use the shared **13,920-condition decision space**, defined by 145 catalyst–ligand and loading formulations, eight solvents and twelve bases. Each deposited history begins with twelve conditions sampled uniformly without replacement from the complete space and then records simultaneous four-condition UCB recommendations from a hierarchical GP, followed by four-response updates. The twelve recorded round-0 indices, exact configurations, measured feedback and every stopping check are deposited in [the current package](../optimization/current/).

The same empirical stopping rule is used in all systems: after at least 24 observations, cumulative-best improvement across the last two rounds must be no larger than 10% of the initial population standard deviation. The displayed paths first reach their highest measured responses at rounds 10/9/7 and stop at rounds 12/11/9 for N–H/O–H/S–H, giving 60/56/48 unique selected conditions.

UV response depends on the substrate–product pair and analytical conditions. It supports condition comparisons within a system; raw signals across the three different systems are not comparable yields. Only the indicated sulfur condition has a separately documented 37% NMR yield. The author confirmed the display corrections `MS_Response` → `UV response` for the nitrogen source heading and `CsOH/2` → `CsOH` for the base name. Original raw workbook bytes are preserved.

The twelve-by-eight measured grids in Figure 5b–d are representative visualization slices. Their formulation keys and local maxima are distinct from the shared decision-space coordinates and trajectory-wide maxima. The BO histories reach their highest measured responses at AgF/PPh₃/K₂CO₃/DCE (N-H), NiCl₂·DME/DIPEA/DCE (O-H) and CuCl/PPh₃/CsOH/DCE (S-H). Table 1/scope uses Ag₂SO₄/PPh₃/NaH/DCE for N-H, NiCl₂·DME/Na₃PO₄·12H₂O/DCE for O-H and CuCl/PPh₃/CsOH/DCE for S-H, so N-H and O-H differ while S-H matches. The scope settings must not be described collectively as the BO maxima. Surface interpolation connects measured nodes; panel-e curves are GP predictions and their bands are ±2 latent posterior standard deviations. Those bands represent latent model uncertainty, not experimental error, and are not validated as calibrated coverage intervals over the full decision space.

The current study transfers the earlier *Chemical Science* optimization framework to the heteroatom systems and does not repeat a random-screening baseline. [Optimization methods](../optimization/METHODS.md) describe the current model and reproduction.

## Experimental scale and record scope

Experimental procedures are provided in SI S7. Selected products from the high-throughput screen were isolated and characterized by NMR spectroscopy (SI Sections S7.5 and S7.6). The [counting-unit guide](product_scope.md) distinguishes the 12 selected NMR characterization entries from the 44 Table 1 product assignments.

The source-screen procedure uses 250 μL, whereas the current 13,920-condition BO candidate tables, all 164 selected trajectory rows and the numerical scope records use 500 μL. The three legacy N-H records AP001–AP003 retain their original 250 μL scale. These volumes describe distinct experimental layers and should be interpreted with the corresponding source-screen, BO or scope record.

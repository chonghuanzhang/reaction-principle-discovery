# How to interpret the data

The materials connect literature knowledge, proposed chemistry and measured screening responses through the current four-RP framework: acceptor activation, donor speciation and capture, intermediate pathway divergence, and product persistence. The [principle cards](../evidence/principles/) provide their chemical scope. This guide explains distinctions that matter when comparing records or reusing the data.

## Literature and molecular records

The current literature catalog contains **370 source records and 3,756 entries**. The archived candidate-generation input contains **342 source records and 3,694 extracted statements**. The generation inputs and later additions are supplied separately so that the original calculation can be reproduced. L055 and L343 are preprint and published versions of one study; two source records therefore need not represent two independent studies. Metadata-only records identify publications but do not support a chemical observation.

The focused applicability review contains **25 records**, comprising **23 substantive observations or interpretations** and **two metadata-only records**. The [source coverage](../evidence/source_coverage.md) distinguishes primary literature tiers, current RP-supporting sources and original candidate citations.

The archived generation completed successfully with seven primary and two compact-expansion model responses. Molecular validation and chemical identity review produced **100 recommended molecules**, associated with **115 site/pathway hypotheses** and **124 product-option records**. A product option is a proposed endpoint; it is neither an independently validated product nor necessarily a unique structure. The original working/reserve allocation contains 48 and 52 members of the same 100-molecule collection. Forty-six molecules have citations in the original generation records; 54 do not. Subsequent literature analysis is distinguishable from those original citations.

The experimental structure dataset contains **108 ordered electrophile–donor pairs**. Its canonical structure count is 102 donor structures and five electrophile structures, conditional on the recorded identities. This dataset and the author's final collection of 100 experimental donors have different definitions. Researchers considered structural relationships, commercial accessibility and NP/NR before finalizing the experimental list, using judgment without a fixed cutoff or weighted total. The [selection guide and Figure 4d](../candidates/reagent_selection.md) explain that overall process. Item-specific procurement and replacement records are not supplied, so a structural match alone does not establish the reason for an individual choice. Exact matches, reactive-form relations, family analogies and unmatched pairs are shown separately in [Table R1](../candidates/experiment_mapping/).

The 108 pairs comprise **44 nitrogen, 42 oxygen, 20 sulfur and two phosphorus pairs**. Their primary candidate associations are **three exact matches, 101 donor-family or structural analogies and four unmatched pairs**. The source workbooks contain **2,114 row occurrences** and **1,057 sample identifiers**; these are distinct from the **1,066 groups** obtained using the documented workbook/row grouping key. There are **1,064 recorded condition recipes** within the experimental-pair combinations. Repeated rows and reused identifiers must therefore be interpreted at the stated counting level, rather than counted as new molecules or independent experiments.

## Reported chemistry and proposed transfer

The [source cases](../evidence/source_cases/) retain the donor form, substrate, activation conditions and endpoint of each precedent. A phosphorus transformation with a positive 37% first-stage result is not a failed target-system reaction. Negative observations must be read within their own conditions and endpoint. Metadata-only references and missing substrate combinations cannot establish chemical failure.

The current four RP cards organize the source evidence, candidate rationales and applicability conditions. The reviewed working constraints and saved calculation records are retained in the [model workflow](../code/docs/model_workflow.md#archived-generation-inputs). Saved proposal and review responses preserve separate inference contexts of the same model. Offline replay checks the calculation made from those saved responses.

## Measurements and computational selection

N–H, O–H and S–H independently use the shared **13,920-condition decision space**, defined by 145 catalyst–ligand and loading formulations, eight solvents and twelve bases. Uniformly sampled twelve-condition initializations are followed by simultaneous four-condition UCB batches from a hierarchical GP. Recorded UV responses provide feedback for the computational evaluation. Displayed paths were selected from multiple initializations with first highest measured response in rounds 5–15; the exact configurations, seeds and every stopping check are deposited in [the current package](../optimization/current/).

The same empirical stopping rule is used in all systems: after at least 24 observations, cumulative-best improvement across the last two rounds must be no larger than 10% of the initial population standard deviation. The displayed paths first reach their highest measured responses at rounds 10/9/7 and stop at rounds 12/11/9 for N–H/O–H/S–H, giving 60/56/48 unique selected conditions.

UV response depends on the substrate–product pair and analytical conditions. It supports condition comparisons within a system; raw signals across the three different systems are not comparable yields. Only the indicated sulfur condition has a separately documented 37% NMR yield. The author confirmed the display corrections `MS_Response` → `UV response` for the nitrogen source heading and `CsOH/2` → `CsOH` for the base name. Original raw workbook bytes are preserved.

The twelve-by-eight measured grids in Figure 5b–d are representative visualization slices. Their formulation keys and local maxima are distinct from the shared decision-space coordinates and trajectory-wide maxima. In particular, the N–H slice fixes Ag₂SO₄/PPh₃, whereas the highest measured response reached by the N–H trajectory uses AgF/PPh₃. Surface interpolation connects measured nodes; panel-e curves are GP predictions and their bands are ±2 latent posterior standard deviations.

The current study transfers the earlier *Chemical Science* optimization framework to the heteroatom systems and does not repeat a random-screening baseline. Older 96-condition and random-selection calculations remain archived with their original inputs. [Optimization methods](../optimization/METHODS.md) describe the current model and reproduction.

## Experimental details needed for further reuse

Experimental procedures, characterization and spectra are in SI S7. The supplied general procedure uses 250 μL, whereas some recorded grid entries use 500 μL; the association between these preparation records is not fully resolved at plate level. The repeat-acceptance protocol refers to at least 90% of conditions within a 15% difference, but the relative-versus-percentage-point definition and plate-specific acceptance records are not supplied. The protocol alone is not a measured repeatability distribution.

The available files do not provide complete original instrument files, product-specific calibrated yields for every screening cell, uniform sample-level product confirmation, or a dated component-by-component library-design log. These limits should be considered before treating a model ranking as a validated chemical optimum or using the screens to train a general reaction-success predictor.

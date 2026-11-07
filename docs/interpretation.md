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

The current four RP cards organize the source evidence, candidate rationales and applicability conditions. They were synthesized after the archived generation, whose original reviewed working constraints are retained in the [model workflow](../code/docs/model_workflow.md#archived-generation-inputs). Saved proposal and review responses preserve separate inference contexts of the same model. Offline replay checks the calculation made from those saved responses.

## Measurements and computational selection

Each principal SH/NH/OH screen contains measurements for **96 conditions**. Each reconstructed NH/OH trajectory selects **60** of those conditions as model inputs. Its computational batch order cannot establish the original laboratory sequence without dated recommendations, execution records and returned responses. Those complete timestamped records are not supplied.

MS and UV responses are analytical signals. They require product-specific calibration before interpretation as yields, and their magnitudes cannot be compared across systems as percentages. Only the indicated sulfur maximum has a separately documented **37% NMR yield**. The source label `CsOH/2` is retained as recorded; its suffix does not establish a formulation or stoichiometry. Scope-reaction recipes and screening maxima are distinct records.

The sulfur benchmark uses **100 paired algorithm seeds on one response landscape**. Its bootstrap interval describes seed-to-seed variation conditional on that landscape; it is not an interval over independent chemical experiments. Other supplied simulations use eight measured pools and 1,600 computational campaigns. These do not represent 1,600 new experiments. See [optimization methods](../optimization/METHODS.md) for the selection rule and uncertainty calculation.

## Experimental details needed for further reuse

Experimental procedures, characterization and spectra are in SI S7. The supplied general procedure uses 250 μL, whereas some recorded grid entries use 500 μL; the association between these preparation records is not fully resolved at plate level. The repeat-acceptance protocol refers to at least 90% of conditions within a 15% difference, but the relative-versus-percentage-point definition and plate-specific acceptance records are not supplied. The protocol alone is not a measured repeatability distribution.

The available files do not provide complete original instrument files, product-specific calibrated yields for every screening cell, uniform sample-level product confirmation, or a dated component-by-component library-design log. These limits should be considered before treating a model ranking as a validated chemical optimum or using the screens to train a general reaction-success predictor.

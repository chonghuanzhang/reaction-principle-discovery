# How to interpret the data

The materials connect literature knowledge, proposed chemistry and measured screening responses. These represent different kinds of evidence. This guide explains distinctions that matter when comparing records or reusing the data.

## Literature and molecular records

The original candidate-generation input contains **342 source records and 3,694 extracted statements**. The catalog used for the later chemical analysis contains **370 source records and 3,756 entries**. The generation inputs and later additions are supplied separately so that the original calculation can be reproduced. L055 and L343 are preprint and published versions of one study; two source records therefore need not represent two independent studies. Metadata-only records identify publications but do not support a chemical observation.

The focused applicability review contains **25 records**, comprising **23 substantive observations or interpretations** and **two metadata-only records**. The [source coverage](../evidence/source_coverage.md) distinguishes primary literature tiers, current RP-supporting sources and original candidate citations.

There are **100 recommended molecules**, **115 site/pathway hypotheses** and **124 product-option records**. A product option is a proposed endpoint; it is neither an independently validated product nor necessarily a unique structure. The original working/reserve allocation contains 48 and 52 members of the same 100-molecule collection. Forty-six molecules have citations in the original generation records; 54 do not. Subsequent literature analysis is distinguishable from those original citations.

The experimental structure dataset contains **108 ordered electrophile–donor pairs**. Its canonical structure count is 102 donor structures and five electrophile structures, conditional on the recorded identities. This dataset and the final 100-molecule study population have different definitions. A fully documented sequence of procurement and replacement decisions is not available, so a structural match does not establish why an experimental input was selected. Exact matches, reactive-form relations, family analogies and unmatched pairs are shown separately in [Table R1](../candidates/experiment_mapping/).

The 108 pairs comprise **44 nitrogen, 42 oxygen, 20 sulfur and two phosphorus pairs**. Their primary candidate associations are **three exact matches, 101 donor-family or structural analogies and four unmatched pairs**. The source workbooks contain **2,114 row occurrences** and **1,057 sample identifiers**; these are distinct from the **1,066 groups** obtained using the documented workbook/row grouping key. There are **1,064 recorded condition recipes** within the experimental-pair combinations. Repeated rows and reused identifiers must therefore be interpreted at the stated counting level, rather than counted as new molecules or independent experiments.

## Reported chemistry and proposed transfer

The [source cases](../evidence/source_cases/) retain the donor form, substrate, activation conditions and endpoint of each precedent. A phosphorus transformation with a positive 37% first-stage result is not a failed target-system reaction. Negative observations must be read within their own conditions and endpoint. Metadata-only references and missing substrate combinations cannot establish chemical failure.

The four explanatory RP cards are a later chemical synthesis of the evidence. Candidate generation used five reviewed working constraints. Saved proposal and review calls allow the original inputs and responses to be inspected; separate call contexts do not establish statistical independence or external chemical accuracy. Offline replay checks the calculation made from those responses. It does not constitute a new language-model experiment.

## Measurements and computational selection

Each principal SH/NH/OH screen contains measurements for **96 conditions**. Each reconstructed NH/OH trajectory selects **60** of those conditions as model inputs. Its computational batch order cannot establish the original laboratory sequence without dated recommendations, execution records and returned responses. Those complete timestamped records are not supplied.

MS and UV responses are analytical signals. They require product-specific calibration before interpretation as yields, and their magnitudes cannot be compared across systems as percentages. Only the indicated sulfur maximum has a separately documented **37% NMR yield**. The source label `CsOH/2` is retained as recorded; its suffix does not establish a formulation or stoichiometry. Scope-reaction recipes and screening maxima are distinct records.

The sulfur benchmark uses **100 paired algorithm seeds on one response landscape**. Its bootstrap interval describes seed-to-seed variation conditional on that landscape; it is not an interval over independent chemical experiments. Other supplied simulations use eight measured pools and 1,600 computational campaigns. These do not represent 1,600 new experiments. See [optimization methods](../optimization/METHODS.md) for the selection rule and uncertainty calculation.

## Experimental details needed for further reuse

Experimental procedures, characterization and spectra are in SI S7. The supplied general procedure uses 250 μL, whereas some recorded grid entries use 500 μL; the association between these preparation records is not fully resolved at plate level. The repeat-acceptance protocol refers to at least 90% of conditions within a 15% difference, but the relative-versus-percentage-point definition and plate-specific acceptance records are not supplied. The protocol alone is not a measured repeatability distribution.

The available files do not provide complete original instrument files, product-specific calibrated yields for every screening cell, uniform sample-level product confirmation, or a dated component-by-component library-design log. These limits should be considered before treating a model ranking as a validated chemical optimum or using the screens to train a general reaction-success predictor.

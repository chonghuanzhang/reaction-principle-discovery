# Figure artwork

The main-figure overview and molecular artwork are in [main/](main/). The editable sources for [Figure 1](source/current/Figure_1_editable.pptx) and [Figure 2](source/current/Figure_2_editable.pptx) retain native text, shapes and embedded chemical drawings.

## Main Figures 1 and 2

The current overview figures show the shared decision space and the workflow with twelve initial conditions and four recommendations per round.

- [Figure 1 PNG](main/Figure_1.png), [PDF](main/Figure_1.pdf), [SVG](main/Figure_1.svg) and [JPEG](main/Figure_1.jpeg).
- [Figure 2 PNG](main/Figure_2.png), [PDF](main/Figure_2.pdf), [SVG](main/Figure_2.svg) and [JPEG](main/Figure_2.jpeg).
- Current PNG masters and editable slide sources are in [source/current/](source/current/). Each editable deck contains its current figure as the sole slide: Figure 1 and Figure 2 are both on slide 1 in their respective decks. Figure 1 reports 370 literature sources and 112 substrate–partner combinations; Figure 2 reports the same 112 input pairs.

The Figure 1 and 2 PDF/SVG files contain the approved raster composites. Their slide sources retain editable objects. Outer white margins have been cropped without changing the artwork.

## Main Figures 3 and 4

Figure 3 is the evidence-to-principle-to-candidate provenance network. It contains 17 evidence nodes, four reaction principles, 43 precursor families and 100 recommended molecules. Filled and open candidate nodes distinguish records with and without a direct candidate-level citation link. The same graph records generate the four RP-focused views used as Supplementary Figures 1–4.

Figure 4 combines reacting-centre composition, representative recommendations, molecule/hypothesis/product-option accounting, recommended-to-experimental relationships and the feasibility/novelty-priority distributions. The [selection guide](../candidates/reagent_selection.md) links the examples to their candidate and experimental-pair records.

- [Figure 3 PNG](main/Figure_3.png), [PDF](main/Figure_3.pdf) and [SVG](main/Figure_3.svg).
- [Figure 4 PNG master](main/Figure_4.png) — 2096 × 2148 pixels at 300 dpi.
- [Vector PDF](main/Figure_4.pdf) and [SVG](main/Figure_4.svg).
- [Figure 4 JPEG](main/Figure_4.jpeg) — publication/export derivative.
- [Figure data and structure associations](source/round5_figure4/figure_data.json), [caption](source/round5_figure4/caption.txt) and [composition metadata](source/Figure_4_composition.json).

Panel d shows C002 indoline → AP044 indoline (exact identity), C042 2-naphthol → AP048 1-naphthol (same scaffold/positional variation), and C004 2-naphthalenethiol → AP096 4-methoxythiophenol (same donor family/different scaffold). Across the 100 recommendations, the best relationships are 25 exact identities, 31 scaffold/substituent relationships, 41 donor-family relationships and three unmatched recommendations. Panel e shows feasibility classes A/B/C (22/75/3) and novelty review priorities 1/2/3 (43/41/16); these organize review and are not reaction-success probabilities.

## Main Figure 6

The [Figure 6 PNG](main/Figure_6.png), [PDF](main/Figure_6.pdf) and [SVG](main/Figure_6.svg) compare the RP-guided, direct-LLM and literature-selection experimental collections. Panel a reports collection-positive statistics of 35/94, 4/20 and 3/20, corresponding to observed positive fractions of 37.2%, 20.0% and 15.0%. The RP-guided fraction is 1.86-fold and 2.48-fold higher than in the direct-LLM and literature-selection collections, respectively. These fractions summarize the tested collections under their respective electrophile and reaction-condition combinations. Panel b uses the same fixed-condition analysis collections: 94 unique RP experimental donors, 20 direct-LLM structures and 20 unique literature-selection structures, with reported membership-pattern counts of 91/18/19/2/1. Negligible-response negative outcomes in both baseline collections are displayed as `Trace`. Solid blue outlines mark exact matches to donors in the RP experimental collection. Dashed orange outlines mark exact matches to the released recommendation set: two direct-LLM structures and five literature-selected structures. The 94 RP donor memberships and source cells are deposited in [the analysis membership](../experiments/baselines/data/rp_analysis_membership_94.json) and reproduced by [the comparison script](../experiments/baselines/reproduce_comparison.py); O–H uses the DIPEA/DCE condition block. Source panels and exact public candidate identifiers are in [source/round5_figure6/](source/round5_figure6/); the machine-readable baseline inputs are in [experiments/baselines/data](../experiments/baselines/data/).

## Main Figure 5

The current [Figure 5 PNG](main/Figure_5.png), [PDF](main/Figure_5.pdf), [SVG](main/Figure_5.svg) and [JPEG](main/Figure_5.jpeg) combine the three optimization trajectories, representative measured 12 × 8 grids and six N–H posterior snapshots. Panels b, c and d each have an individual relative-response colour bar. The [caption](../optimization/current/figure5/captions/Figure_5_caption_EN.txt) defines the marks and distinguishes the full decision space from the illustrative grids.

The deposited [source data](../optimization/current/figure5/source_data/) and [numerical verification](../optimization/current/figure5/verification.json) record the values used in the approved artwork. Text and line elements remain vector in the PDF/SVG; the dense surfaces are rasterized. Plot interpolation connects measured or modelled categorical nodes and does not add measurements.

## Related artwork

The [knowledge graph](../knowledge_graph/) collects the overall evidence network, RP1–RP4 focus images used in Supplementary Figures 1–4, N/O/S/P centre-focus repository views, graph records and main Figure 3 vector artwork.

The complete [NP/NR distribution chart](../candidates/novelty_assessment.md) is Repository Figure N1 and Supplementary Figure 5. Supplementary Figure 6 is the well-position index in the SI. The [reading guide](../docs/reading_guide.md#supplementary-figure-correspondence) gives the full figure correspondence.

Computational source data are documented in [code/](../code/) for the evidence and molecular analyses, and [optimization/](../optimization/) for Figure 5 and Supplementary Figures 7–9. These data should be used when quantitative values are needed; graphical coordinates and surface interpolation do not represent additional measurements.

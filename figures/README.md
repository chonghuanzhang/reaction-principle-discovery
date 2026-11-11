# Figure artwork

The main-figure overview and molecular artwork are in [main/](main/). The editable chemical schemes are supplied in [author_chemical_schemes.pptx](source/author_chemical_schemes.pptx).

## Main Figure 4

The current Figure 4 combines candidate diversity, donor-form examples, the molecule/hypothesis/endpoint counts, N/O/S model-donor associations and separate NP/NR distributions. Panel a follows the author-supplied radial count layout with the same sans-serif font and blue–teal palette as the remaining panels. The [selection guide](../candidates/reagent_selection.md#main-figure-4d) links the examples to their candidate and experimental-pair records.

- [Figure 4 PNG master](main/Figure_4.png) — 4252 × 4961 pixels, rendered at 600 dpi from the vector PDF; 180 × 210 mm.
- [Vector PDF](main/Figure_4.pdf) and [SVG](main/Figure_4.svg) — editable text, paths and molecular depictions.
- [Figure 4 JPEG](main/Figure_4.jpeg) — publication/export derivative.
- [Panels a–c crop](source/Figure_4_panels_abc.png) and [panel d crop](source/Figure_4d_candidate_selection.png) — views of the current master.
- [Figure data and structure associations](source/round4_figure4/figure_data.json), [panel e data](source/round4_figure4/novelty_panel_e.csv), [caption](source/round4_figure4/caption.txt) and [composition metadata](source/Figure_4_composition.json).

Run `code/scripts/reproduce_figures2_4.py` as described in the [code guide](../code/README.md) to reproduce vector Figures 2 and 4. The Figure 4 builder is `code/figures/build_figure4_round4.py`. It reads the deposited candidate collection, experimental-input mapping and novelty summary, draws the scientific content, and verifies the vector PDF before exporting its PNG. The reproduction check compares PNG pixels with the master. It makes no network or model calls.

Panel d shows C048 aniline → AP039 indoline (also AP044 in the mapping), C051 phenol → AP048 1-naphthol, and C082 benzenethiol → AP090 4-tert-butylbenzenethiol. All three are structural analogues. Arrows describe associations, not chemical transformations or independently recovered replacement decisions. Panel e uses fractions within two different record populations: 100 candidate molecules and 108 ordered experimental pairs. NP and NR remain separate ordinal classifications; neither is a success probability or a measure of novelty retention.

## Related artwork

The [knowledge graph](../knowledge_graph/) collects the overall evidence network, all nine original G1–G9 views, the RP1–RP4 focus images used in Supplementary Figures 1–4, graph records and main Figure 3 vector artwork.

The complete [NP/NR distribution chart](../candidates/novelty_assessment.md) is Repository Figure N1 and Supplementary Figure 5. Supplementary Figure 6 is the well-position index in the SI. The [reading guide](../docs/reading_guide.md#supplementary-figure-correspondence) gives the full figure correspondence.

Computational source data and figure-generation commands are documented in [code/](../code/) for the evidence and molecular analyses, and [optimization/](../optimization/) for Figure 5 and Supplementary Figures 7–9. These data should be used when quantitative values are needed; graphical coordinates and surface interpolation do not represent additional measurements.

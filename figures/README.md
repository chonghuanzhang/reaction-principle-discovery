# Figure artwork

The main-figure overview and molecular artwork are in [main/](main/). The editable chemical schemes are supplied in [author_chemical_schemes.pptx](source/author_chemical_schemes.pptx).

## Main Figure 4

The current Figure 4 contains the candidate-to-reagent selection scheme in panel d. Researchers considered structural relationships, commercial accessibility and separate NP/NR classifications before finalizing the experimental list, without a fixed cutoff or weighted total. The [selection guide](../candidates/reagent_selection.md#main-figure-4d) provides the panel caption and links its illustrative structural associations to the underlying candidate and experimental-pair records.

- [Figure 4 PNG master](main/Figure_4.png) — authoritative lossless artwork, 3200 × 3700 pixels.
- [Figure 4 JPEG](main/Figure_4.jpeg) — publication/export copy; JPEG compression changes pixel values.
- [Panels a–c source crop](source/Figure_4_panels_abc.png) — preserved at its original pixel dimensions and placement.
- [Panel d source artwork](source/Figure_4d_candidate_selection.png) — the full selection scheme.
- [Composition metadata](source/Figure_4_composition.json) — source checksums, canvas dimensions, placement, resampling and resolution.

Run `code/scripts/reproduce_figures2_4.py` as described in the [code guide](../code/README.md) to reproduce vector Figure 2 and compose the current Figure 4. Figure 4 PNG, JPEG and PDF outputs are composed deterministically with Pillow from the deposited artwork; the PDF contains raster artwork. Exact reconstructed PNG pixels and the unchanged a–c source region are checked against the deposited master.

## Related artwork

The [knowledge graph](../knowledge_graph/) collects the overall evidence network, all nine original G1–G9 views, the RP1–RP4 focus images used in Supplementary Figures 1–4, graph records and main Figure 3 vector artwork.

The complete [NP/NR distribution chart](../candidates/novelty_assessment.md) is Repository Figure N1 and Supplementary Figure 5. Supplementary Figure 6 is the well-position index in the SI. The [reading guide](../docs/reading_guide.md#supplementary-figure-correspondence) gives the full figure correspondence.

Computational source data and figure-generation commands are documented in [code/](../code/) for the evidence and molecular analyses, and [optimization/](../optimization/) for Figure 5 and Supplementary Figures 7–9. These data should be used when quantitative values are needed; graphical coordinates and surface interpolation do not represent additional measurements.

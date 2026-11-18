# Evidence-to-recommendation knowledge graph

The graph provides a traversable account of the complete workflow: **17 evidence summaries -> four reaction principles -> 43 precursor families -> 100 recommended nucleophiles**. It contains 19 evidence-to-RP edges, 172 RP-to-family applications and 100 family-membership edges.

Seventy-five candidates retain direct candidate-level citation links (170 links from 17 catalog sources); all 100 retain an RP-family-evidence provenance path. Candidate-level citation links and RP-level support are different evidence relations and are stored separately.

## Data and views

- [Network JSON](data/network.json)
- [Tier summary](data/tier_summary.json)
- [Figure captions](data/figure_captions.json)
- [Main Figure 3](figures/Figure_3.svg) and [full network](figures/network_full.svg)
- Repository views G1-G9 and RP1-RP4 focus views in [`figures/`](figures/)

An edge records a documented provenance or applicability relationship, not a measured reaction outcome or a universal mechanism.

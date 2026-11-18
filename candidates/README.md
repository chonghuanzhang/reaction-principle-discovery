# 100 RP-guided nucleophile recommendations

This catalog is the molecular output of the evidence-to-RP-to-recommendation workflow. The **100 unique neutral molecules** comprise **40 N-, 30 O-, 25 S- and 5 P-centred donors** distributed across 43 precursor families. The records retain **103 site/pathway hypotheses** and **103 proposed product connectivities**.

Recommendations were first grouped by chemical feasibility (A 22, B 75, C 3) and then ordered for review by novelty priority (1: 43, 2: 41, 3: 16), while preserving RP and literature provenance. These labels organize experimental review; they are not probabilities of reaction success or predicted yields.

## From recommendations to experimental reagents

Every recommendation was compared with the 108 recorded ordered substrate-partner pairs and the qualitative supplemental phosphorus records. The best candidate-level relationships are **25 exact identities, 31 same-scaffold/substituent or positional variations, 41 same-family/different-scaffold relationships and 3 recommendations without a reasonable counterpart**. Thus, 97 recommendations have a defensible exact, scaffold-level or donor-family correspondence to the experimental collection; the remaining three are retained as explicit unmatched recommendations.

The experimental-pair view is a different counting unit: the 108 ordered pairs comprise **26 exact, 37 scaffold/substituent, 41 donor-family and 4 unmatched records**. Structural correspondence explains how the RP-derived chemical space was translated into practical experiments; it does not transfer a measured response from one molecule to another.

## Reader guides and data

[Structure atlas C1-C9](structure_atlas.md) · [Recommendation-to-experiment relationships](reagent_selection.md) · [All 108 experimental pairs](experiment_mapping/) · [Product options](product_options/) · [NP/NR assessment](novelty_assessment.md)

- [100 candidates: JSON](data/candidates_100.json) · [CSV](data/candidates_100.csv)
- [103 hypotheses: JSON](data/hypotheses_103.json) · [CSV](data/hypotheses_103.csv)
- [103 product options: JSON](product_options/product_options_103.json) · [CSV](product_options/product_options_103.csv)
- [108 experimental pairs](experiment_mapping/mapping_108.json) and [209 selected candidate-pair relations](experiment_mapping/relations.csv)

## Molecule index

| Molecule | Structure and name | Centre | Family | Feasibility | Novelty priority | Best experimental correspondence |
| --- | --- | --- | --- | --- | --- | --- |
| [C001](C001.md) | <img src="structures/C001.svg" width="150" alt="N-Methylaniline"><br>N-Methylaniline | N | arylamine | A | 1 | Same donor family, different scaffold |
| [C002](C002.md) | <img src="structures/C002.svg" width="150" alt="Indoline"><br>Indoline | N | fused_secondary_amine | A | 1 | Exact identity |
| [C003](C003.md) | <img src="structures/C003.svg" width="150" alt="Benzimidazole"><br>Benzimidazole | N | fused_azole | A | 1 | Same scaffold, substituent or positional variation |
| [C004](C004.md) | <img src="structures/C004.svg" width="150" alt="Naphthalene-2-thiol"><br>Naphthalene-2-thiol | S | fused_aryl_thiol | A | 1 | Same donor family, different scaffold |
| [C005](C005.md) | <img src="structures/C005.svg" width="150" alt="Phenylmethanethiol"><br>Phenylmethanethiol | S | benzylic_thiol | A | 1 | Same scaffold, substituent or positional variation |
| [C006](C006.md) | <img src="structures/C006.svg" width="150" alt="4-Methylbenzenethiol"><br>4-Methylbenzenethiol | S | aryl_thiol | A | 2 | Exact identity |
| [C007](C007.md) | <img src="structures/C007.svg" width="150" alt="4-Methoxybenzenethiol"><br>4-Methoxybenzenethiol | S | aryl_thiol | A | 2 | Exact identity |
| [C008](C008.md) | <img src="structures/C008.svg" width="150" alt="4-Fluorobenzenethiol"><br>4-Fluorobenzenethiol | S | aryl_thiol | A | 2 | Same scaffold, substituent or positional variation |
| [C009](C009.md) | <img src="structures/C009.svg" width="150" alt="4-Chlorobenzenethiol"><br>4-Chlorobenzenethiol | S | aryl_thiol | A | 2 | Same scaffold, substituent or positional variation |
| [C010](C010.md) | <img src="structures/C010.svg" width="150" alt="4-Bromobenzenethiol"><br>4-Bromobenzenethiol | S | aryl_thiol | A | 2 | Same scaffold, substituent or positional variation |
| [C011](C011.md) | <img src="structures/C011.svg" width="150" alt="2-Methylbenzenethiol"><br>2-Methylbenzenethiol | S | aryl_thiol | A | 2 | Same scaffold, substituent or positional variation |
| [C012](C012.md) | <img src="structures/C012.svg" width="150" alt="3-Methylbenzenethiol"><br>3-Methylbenzenethiol | S | aryl_thiol | A | 2 | Same scaffold, substituent or positional variation |
| [C013](C013.md) | <img src="structures/C013.svg" width="150" alt="Propane-1-thiol"><br>Propane-1-thiol | S | primary_alkyl_thiol | A | 2 | Same donor family, different scaffold |
| [C014](C014.md) | <img src="structures/C014.svg" width="150" alt="2-Phenylethane-1-thiol"><br>2-Phenylethane-1-thiol | S | arylalkyl_thiol | A | 2 | Same donor family, different scaffold |
| [C015](C015.md) | <img src="structures/C015.svg" width="150" alt="Imidazole"><br>Imidazole | N | azole | A | 3 | Same scaffold, substituent or positional variation |
| [C016](C016.md) | <img src="structures/C016.svg" width="150" alt="Pyrazole"><br>Pyrazole | N | azole | A | 3 | Same donor family, different scaffold |
| [C017](C017.md) | <img src="structures/C017.svg" width="150" alt="Indole"><br>Indole | N | pyrrolic_nh | A | 3 | Same scaffold, substituent or positional variation |
| [C018](C018.md) | <img src="structures/C018.svg" width="150" alt="Phenol"><br>Phenol | O | phenol | A | 3 | Exact identity |
| [C019](C019.md) | <img src="structures/C019.svg" width="150" alt="Methanol"><br>Methanol | O | primary_alcohol | A | 3 | Same donor family, different scaffold |
| [C020](C020.md) | <img src="structures/C020.svg" width="150" alt="Ethanol"><br>Ethanol | O | primary_alcohol | A | 3 | Same donor family, different scaffold |
| [C021](C021.md) | <img src="structures/C021.svg" width="150" alt="Benzenethiol"><br>Benzenethiol | S | aryl_thiol | A | 3 | Same scaffold, substituent or positional variation |
| [C022](C022.md) | <img src="structures/C022.svg" width="150" alt="Ethanethiol"><br>Ethanethiol | S | primary_alkyl_thiol | A | 3 | Same donor family, different scaffold |
| [C023](C023.md) | <img src="structures/C023.svg" width="150" alt="Diphenylamine"><br>Diphenylamine | N | diarylamine | B | 1 | Exact identity |
| [C024](C024.md) | <img src="structures/C024.svg" width="150" alt="Pyrrolidine"><br>Pyrrolidine | N | cyclic_secondary_amine | B | 1 | Same donor family, different scaffold |
| [C025](C025.md) | <img src="structures/C025.svg" width="150" alt="Thiomorpholine"><br>Thiomorpholine | N | cyclic_secondary_amine | B | 1 | Same donor family, different scaffold |
| [C026](C026.md) | <img src="structures/C026.svg" width="150" alt="Azepane"><br>Azepane | N | cyclic_secondary_amine | B | 1 | Same donor family, different scaffold |
| [C027](C027.md) | <img src="structures/C027.svg" width="150" alt="1,2,3,4-Tetrahydroisoquinoline"><br>1,2,3,4-Tetrahydroisoquinoline | N | fused_secondary_amine | B | 1 | Same donor family, different scaffold |
| [C028](C028.md) | <img src="structures/C028.svg" width="150" alt="1-Methylpiperazine"><br>1-Methylpiperazine | N | cyclic_secondary_amine | B | 1 | Same scaffold, substituent or positional variation |
| [C029](C029.md) | <img src="structures/C029.svg" width="150" alt="Indazole"><br>Indazole | N | fused_azole | B | 1 | Same donor family, different scaffold |
| [C030](C030.md) | <img src="structures/C030.svg" width="150" alt="1,2,4-Triazole"><br>1,2,4-Triazole | N | azole | B | 1 | Same donor family, different scaffold |
| [C031](C031.md) | <img src="structures/C031.svg" width="150" alt="1H-Benzotriazole"><br>1H-Benzotriazole | N | fused_azole | B | 1 | Same donor family, different scaffold |
| [C032](C032.md) | <img src="structures/C032.svg" width="150" alt="Carbazole"><br>Carbazole | N | pyrrolic_nh | B | 1 | Same scaffold, substituent or positional variation |
| [C033](C033.md) | <img src="structures/C033.svg" width="150" alt="7-Azaindole"><br>7-Azaindole | N | pyrrolic_nh | B | 1 | Same scaffold, substituent or positional variation |
| [C034](C034.md) | <img src="structures/C034.svg" width="150" alt="Acetanilide"><br>Acetanilide | N | amide | B | 1 | Exact identity |
| [C035](C035.md) | <img src="structures/C035.svg" width="150" alt="Pyrrolidin-2-one"><br>Pyrrolidin-2-one | N | lactam | B | 1 | Same donor family, different scaffold |
| [C036](C036.md) | <img src="structures/C036.svg" width="150" alt="Phthalimide"><br>Phthalimide | N | imide | B | 1 | Same donor family, different scaffold |
| [C037](C037.md) | <img src="structures/C037.svg" width="150" alt="4-Methylbenzenesulfonamide"><br>4-Methylbenzenesulfonamide | N | sulfonamide | B | 1 | No reasonable counterpart |
| [C038](C038.md) | <img src="structures/C038.svg" width="150" alt="Saccharin"><br>Saccharin | N | sulfonimide | B | 1 | Same donor family, different scaffold |
| [C039](C039.md) | <img src="structures/C039.svg" width="150" alt="1,3-Oxazolidin-2-one"><br>1,3-Oxazolidin-2-one | N | cyclic_carbamate | B | 1 | Same donor family, different scaffold |
| [C040](C040.md) | <img src="structures/C040.svg" width="150" alt="1,3-Dimethylurea"><br>1,3-Dimethylurea | N | urea | B | 1 | Same donor family, different scaffold |
| [C041](C041.md) | <img src="structures/C041.svg" width="150" alt="Naphthalen-1-ol"><br>Naphthalen-1-ol | O | naphthol | B | 1 | Exact identity |
| [C042](C042.md) | <img src="structures/C042.svg" width="150" alt="Naphthalen-2-ol"><br>Naphthalen-2-ol | O | naphthol | B | 1 | Same scaffold, substituent or positional variation |
| [C043](C043.md) | <img src="structures/C043.svg" width="150" alt="Propan-2-ol"><br>Propan-2-ol | O | secondary_alcohol | B | 1 | Same donor family, different scaffold |
| [C044](C044.md) | <img src="structures/C044.svg" width="150" alt="Cyclohexanol"><br>Cyclohexanol | O | secondary_alcohol | B | 1 | Same donor family, different scaffold |
| [C045](C045.md) | <img src="structures/C045.svg" width="150" alt="Benzyl alcohol"><br>Benzyl alcohol | O | benzylic_alcohol | B | 1 | Exact identity |
| [C046](C046.md) | <img src="structures/C046.svg" width="150" alt="Pyridin-3-ylmethanol"><br>Pyridin-3-ylmethanol | O | heteroaryl_alcohol | B | 1 | Exact identity |
| [C047](C047.md) | <img src="structures/C047.svg" width="150" alt="(E)-3-Phenylprop-2-en-1-ol"><br>(E)-3-Phenylprop-2-en-1-ol | O | allylic_alcohol | B | 1 | Same donor family, different scaffold |
| [C048](C048.md) | <img src="structures/C048.svg" width="150" alt="Prop-2-yn-1-ol"><br>Prop-2-yn-1-ol | O | propargylic_alcohol | B | 1 | Same donor family, different scaffold |
| [C049](C049.md) | <img src="structures/C049.svg" width="150" alt="2-Methoxyethan-1-ol"><br>2-Methoxyethan-1-ol | O | ether_alcohol | B | 1 | Same donor family, different scaffold |
| [C050](C050.md) | <img src="structures/C050.svg" width="150" alt="Oxan-4-ol"><br>Oxan-4-ol | O | cyclic_ether_alcohol | B | 1 | Same donor family, different scaffold |
| [C051](C051.md) | <img src="structures/C051.svg" width="150" alt="Naphthalene-1-thiol"><br>Naphthalene-1-thiol | S | fused_aryl_thiol | B | 1 | Same donor family, different scaffold |
| [C052](C052.md) | <img src="structures/C052.svg" width="150" alt="Pyridine-3-thiol"><br>Pyridine-3-thiol | S | heteroaryl_thiol | B | 1 | Same donor family, different scaffold |
| [C053](C053.md) | <img src="structures/C053.svg" width="150" alt="Furan-2-ylmethanethiol"><br>Furan-2-ylmethanethiol | S | heteroarylmethyl_thiol | B | 1 | Same donor family, different scaffold |
| [C054](C054.md) | <img src="structures/C054.svg" width="150" alt="Thiophen-2-ylmethanethiol"><br>Thiophen-2-ylmethanethiol | S | heteroarylmethyl_thiol | B | 1 | Same donor family, different scaffold |
| [C055](C055.md) | <img src="structures/C055.svg" width="150" alt="Propane-2-thiol"><br>Propane-2-thiol | S | secondary_alkyl_thiol | B | 1 | Same donor family, different scaffold |
| [C056](C056.md) | <img src="structures/C056.svg" width="150" alt="2-Methylpropane-2-thiol"><br>2-Methylpropane-2-thiol | S | tertiary_alkyl_thiol | B | 1 | Same donor family, different scaffold |
| [C057](C057.md) | <img src="structures/C057.svg" width="150" alt="Cyclohexanethiol"><br>Cyclohexanethiol | S | cyclic_alkyl_thiol | B | 1 | Same donor family, different scaffold |
| [C058](C058.md) | <img src="structures/C058.svg" width="150" alt="2-Mercaptoethanol"><br>2-Mercaptoethanol | S | hydroxyalkyl_thiol | B | 1 | Same donor family, different scaffold |
| [C059](C059.md) | <img src="structures/C059.svg" width="150" alt="Dicyclohexylphosphine"><br>Dicyclohexylphosphine | P | secondary_alkyl_phosphine | B | 1 | Same donor family, different scaffold |
| [C060](C060.md) | <img src="structures/C060.svg" width="150" alt="4-Methoxy-N-phenylaniline"><br>4-Methoxy-N-phenylaniline | N | diarylamine | B | 2 | Same scaffold, substituent or positional variation |
| [C061](C061.md) | <img src="structures/C061.svg" width="150" alt="N-Methylpyridin-4-amine"><br>N-Methylpyridin-4-amine | N | arylamine | B | 2 | Exact identity |
| [C062](C062.md) | <img src="structures/C062.svg" width="150" alt="N-Ethylpyridin-4-amine"><br>N-Ethylpyridin-4-amine | N | arylamine | B | 2 | Same scaffold, substituent or positional variation |
| [C063](C063.md) | <img src="structures/C063.svg" width="150" alt="2-Methyl-N-phenylaniline"><br>2-Methyl-N-phenylaniline | N | diarylamine | B | 2 | Same scaffold, substituent or positional variation |
| [C064](C064.md) | <img src="structures/C064.svg" width="150" alt="N-Methylnaphthalen-1-amine"><br>N-Methylnaphthalen-1-amine | N | arylamine | B | 2 | Same scaffold, substituent or positional variation |
| [C065](C065.md) | <img src="structures/C065.svg" width="150" alt="1-Ethylpiperazine"><br>1-Ethylpiperazine | N | cyclic_secondary_amine | B | 2 | Same scaffold, substituent or positional variation |
| [C066](C066.md) | <img src="structures/C066.svg" width="150" alt="N-Methylbenzylamine"><br>N-Methylbenzylamine | N | secondary_alkylamine | B | 2 | Exact identity |
| [C067](C067.md) | <img src="structures/C067.svg" width="150" alt="4-Phenylpiperidine"><br>4-Phenylpiperidine | N | cyclic_secondary_amine | B | 2 | Exact identity |
| [C068](C068.md) | <img src="structures/C068.svg" width="150" alt="N-Ethylbenzamide"><br>N-Ethylbenzamide | N | amide | B | 2 | Same scaffold, substituent or positional variation |
| [C069](C069.md) | <img src="structures/C069.svg" width="150" alt="N-Methylbenzamide"><br>N-Methylbenzamide | N | amide | B | 2 | Exact identity |
| [C070](C070.md) | <img src="structures/C070.svg" width="150" alt="N,4-Dimethylbenzenesulfonamide"><br>N,4-Dimethylbenzenesulfonamide | N | sulfonamide | B | 2 | No reasonable counterpart |
| [C071](C071.md) | <img src="structures/C071.svg" width="150" alt="N-Phenylpropanamide"><br>N-Phenylpropanamide | N | amide | B | 2 | Same scaffold, substituent or positional variation |
| [C072](C072.md) | <img src="structures/C072.svg" width="150" alt="4-Methylphenol"><br>4-Methylphenol | O | phenol | B | 2 | Same scaffold, substituent or positional variation |
| [C073](C073.md) | <img src="structures/C073.svg" width="150" alt="4-Methoxyphenol"><br>4-Methoxyphenol | O | phenol | B | 2 | Same scaffold, substituent or positional variation |
| [C074](C074.md) | <img src="structures/C074.svg" width="150" alt="4-Fluorophenol"><br>4-Fluorophenol | O | phenol | B | 2 | Same scaffold, substituent or positional variation |
| [C075](C075.md) | <img src="structures/C075.svg" width="150" alt="4-Bromophenol"><br>4-Bromophenol | O | phenol | B | 2 | Same scaffold, substituent or positional variation |
| [C076](C076.md) | <img src="structures/C076.svg" width="150" alt="4-(Trifluoromethyl)phenol"><br>4-(Trifluoromethyl)phenol | O | phenol | B | 2 | Same scaffold, substituent or positional variation |
| [C077](C077.md) | <img src="structures/C077.svg" width="150" alt="4-Hydroxybenzonitrile"><br>4-Hydroxybenzonitrile | O | phenol | B | 2 | Exact identity |
| [C078](C078.md) | <img src="structures/C078.svg" width="150" alt="4-Phenylphenol"><br>4-Phenylphenol | O | phenol | B | 2 | Exact identity |
| [C079](C079.md) | <img src="structures/C079.svg" width="150" alt="3,5-Dimethoxyphenol"><br>3,5-Dimethoxyphenol | O | phenol | B | 2 | Exact identity |
| [C080](C080.md) | <img src="structures/C080.svg" width="150" alt="Pentan-1-ol"><br>Pentan-1-ol | O | primary_alcohol | B | 2 | Exact identity |
| [C081](C081.md) | <img src="structures/C081.svg" width="150" alt="2-Phenylethan-1-ol"><br>2-Phenylethan-1-ol | O | primary_alcohol | B | 2 | Same scaffold, substituent or positional variation |
| [C082](C082.md) | <img src="structures/C082.svg" width="150" alt="(4-Methoxyphenyl)methanol"><br>(4-Methoxyphenyl)methanol | O | benzylic_alcohol | B | 2 | Same scaffold, substituent or positional variation |
| [C083](C083.md) | <img src="structures/C083.svg" width="150" alt="(4-(Trifluoromethyl)phenyl)methanol"><br>(4-(Trifluoromethyl)phenyl)methanol | O | benzylic_alcohol | B | 2 | Same scaffold, substituent or positional variation |
| [C084](C084.md) | <img src="structures/C084.svg" width="150" alt="2,2,2-Trifluoroethan-1-ol"><br>2,2,2-Trifluoroethan-1-ol | O | fluoroalcohol | B | 2 | Same donor family, different scaffold |
| [C085](C085.md) | <img src="structures/C085.svg" width="150" alt="4-(Trifluoromethyl)benzenethiol"><br>4-(Trifluoromethyl)benzenethiol | S | aryl_thiol | B | 2 | Exact identity |
| [C086](C086.md) | <img src="structures/C086.svg" width="150" alt="4-Mercaptobenzonitrile"><br>4-Mercaptobenzonitrile | S | aryl_thiol | B | 2 | Same scaffold, substituent or positional variation |
| [C087](C087.md) | <img src="structures/C087.svg" width="150" alt="2-Methoxybenzenethiol"><br>2-Methoxybenzenethiol | S | aryl_thiol | B | 2 | Same scaffold, substituent or positional variation |
| [C088](C088.md) | <img src="structures/C088.svg" width="150" alt="2,6-Dimethylbenzenethiol"><br>2,6-Dimethylbenzenethiol | S | aryl_thiol | B | 2 | Exact identity |
| [C089](C089.md) | <img src="structures/C089.svg" width="150" alt="Dimethyl phosphite"><br>Dimethyl phosphite | P | dialkyl_phosphite | B | 2 | Exact identity |
| [C090](C090.md) | <img src="structures/C090.svg" width="150" alt="Diethyl phosphite"><br>Diethyl phosphite | P | dialkyl_phosphite | B | 2 | Exact identity |
| [C091](C091.md) | <img src="structures/C091.svg" width="150" alt="Piperidine"><br>Piperidine | N | cyclic_secondary_amine | B | 3 | Same donor family, different scaffold |
| [C092](C092.md) | <img src="structures/C092.svg" width="150" alt="Morpholine"><br>Morpholine | N | cyclic_secondary_amine | B | 3 | Same donor family, different scaffold |
| [C093](C093.md) | <img src="structures/C093.svg" width="150" alt="Pyrrole"><br>Pyrrole | N | pyrrolic_nh | B | 3 | Same donor family, different scaffold |
| [C094](C094.md) | <img src="structures/C094.svg" width="150" alt="Methanesulfonamide"><br>Methanesulfonamide | N | sulfonamide | B | 3 | No reasonable counterpart |
| [C095](C095.md) | <img src="structures/C095.svg" width="150" alt="Prop-2-en-1-ol"><br>Prop-2-en-1-ol | O | allylic_alcohol | B | 3 | Same donor family, different scaffold |
| [C096](C096.md) | <img src="structures/C096.svg" width="150" alt="Diphenylphosphine"><br>Diphenylphosphine | P | secondary_aryl_phosphine | B | 3 | Exact identity |
| [C097](C097.md) | <img src="structures/C097.svg" width="150" alt="Diphenylphosphine oxide"><br>Diphenylphosphine oxide | P | secondary_phosphine_oxide | B | 3 | Exact identity |
| [C098](C098.md) | <img src="structures/C098.svg" width="150" alt="Quinolin-8-ol"><br>Quinolin-8-ol | O | heteroaryl_phenol | C | 1 | Exact identity |
| [C099](C099.md) | <img src="structures/C099.svg" width="150" alt="2,6-Dimethylphenol"><br>2,6-Dimethylphenol | O | phenol | C | 2 | Exact identity |
| [C100](C100.md) | <img src="structures/C100.svg" width="150" alt="tert-Butanol"><br>tert-Butanol | O | tertiary_alcohol | C | 3 | Same donor family, different scaffold |

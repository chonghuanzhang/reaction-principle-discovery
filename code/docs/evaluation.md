# Candidate-workflow evaluation and checks

The released recommendation package was evaluated at four distinct levels:

1. Molecular representation: all 100 canonical structures are unique and every reacting-atom index lies within its stated molecular graph.
2. Identifier closure: 103 hypotheses and 103 product options resolve to the 100 candidate identifiers, and all product options resolve to a hypothesis.
3. Evidence provenance: all 100 recommendations have a family-RP-evidence path; 75 additionally retain direct candidate-level citations.
4. Experimental correspondence: every recommendation was assessed against the experimental collection, yielding 97 exact/scaffold/family correspondences and three explicit unmatched recommendations. The separate 108-pair ledger contains 26/37/41/4 records in the four relationship categories.

These checks establish data integrity and transparent translation between recommendations and experimental reagents. They do not establish that every recommendation reacts, that related molecules have equal response, or that a proposed connectivity was experimentally observed.

Run `python code/scripts/validate_candidate_release.py` for the package-level check and `python tools/check_data.py` for the repository-wide check.

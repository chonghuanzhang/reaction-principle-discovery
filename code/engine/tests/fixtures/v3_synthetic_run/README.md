# V3 synthetic end-to-end fixture

This offline fixture uses recorded, synthetic Task 2-12 inputs only. It contains no SR001
sealed plaintext and performs no network or model call.

The batch contains four independent synthetic cases. Each case runs two independent
taxonomy lanes over three rounds, deterministic canonicalization and saturation, all three
immutable freezes, chain verification, and one post-freeze synthetic success reveal. The
batch audit therefore has four unique disclosed-success units.

The recorded scenario inventory includes a merge relation, a distinct-family relation, an
unknown mechanism coordinate, a qualified external blocker, and a model-only risk. Unknown
and model-only states are retained as non-numeric/non-exclusion audit states.

Run with:

```bash
.venv/bin/python -m pytest tests/test_v3_end_to_end.py -q
```

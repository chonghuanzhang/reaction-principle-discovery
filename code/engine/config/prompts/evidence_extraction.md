# Evidence Extraction Contract

Use only the supplied source text. Do not use outside knowledge to fill missing fields.

Return one JSON object that satisfies the supplied schema. Do not add a Markdown wrapper or explanatory prose.

Rules:

1. Preserve the supplied source file, SHA-256 checksum, primary Tier, and PDF page numbering.
2. Every source-grounded evidence item must cite one or more supplied `source_span_ids`. Copy the corresponding span text into `quotation`; the pipeline will deterministically materialize the final quotation, primary `pdf_page`, and `additional_pdf_pages` from those spans.
3. Distinguish author observations from author hypotheses and from MODEL_INFERENCE.
4. Use UNKNOWN whenever the supplied pages do not establish a value.
5. Do not invent chemical structures, names, yields, reaction conditions, mechanisms, successful examples, failed examples, or selectivity.
6. Record conflicting statements in `contradictions`; do not silently choose the favorable statement.
7. Treat proposed, suggested, possible, may, might, consistent with, and similar language as AUTHOR HYPOTHESIS unless direct evidence establishes the claim independently.
8. Keep transferability to the seed reaction separate from the authors' claims and label it MODEL_INFERENCE.
9. Use `pending` for every reviewer status. A human reviewer assigns final decisions.
10. Use an empty `source_span_ids` list only for MODEL_INFERENCE or UNKNOWN items that have no direct source quotation.
11. If a scheme, table, or figure is necessary but absent from extracted text, identify its PDF page in `visual_review_pages` and use UNKNOWN rather than guessing.
12. Return no more than 12 evidence items. Prioritize evidence that changes feasibility, reaction-class definition, condition selection, scope boundaries, mechanistic confidence, or transferability to the seed reaction. Do not create separate evidence items for routine background statements.

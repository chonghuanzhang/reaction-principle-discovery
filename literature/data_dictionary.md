# Literature data dictionary

The bibliography identifies references; the source catalog explains their chemical contribution; the statement data retain the underlying attributed claims. The tables use different counting units. The original data key `reference_number` retains the numbering previously used for the complete SI reference list; its values now resolve to the same entries in the online bibliography. JSON and CSV field names and numeric values remain unchanged.

| Field | Meaning |
|---|---|
| `reference_number` | Stable number 1–403 in the online repository bibliography. It is independent of the L identifier. |
| `source_id` | Stable literature identifier L001–L370. Preprint and published versions may have separate identifiers while representing one study. |
| `tier` | Primary chemical-relevance category 1–4, not a journal-quality or source-access ranking. |
| `legacy_reference_code` | Earlier V-style reference code, where one exists, for joining candidate citations to literature sources. |
| `contribution` | English account of the source information used in the chemical argument. |
| `evidence_role_and_access` | Source relevance and available evidence level, including full text, abstract or metadata-only access. |
| `limitations` | Missing bibliographic details, scope restrictions or limits on transfer. |
| `reported_evidence_record_count` | Count stated in the source-contribution description. Its evidence subset can differ from the complete statement table. |
| `statement_count` | Number of rows for that source in the complete 3,756-statement collection. |
| `statement_id` | Source-specific statement identifier, such as L088-S001. It is stable within these data and links to the corresponding source page. |
| `claim_original` | The original extracted claim, retaining its recorded language. |
| `claim_english` | An available English claim or translation. An empty field means that no English version is assigned, not that the source statement is absent. |
| `claim_language` | Language of the original claim: `en` or `zh`. |
| `evidence_label` | Attribution category. `LITERATURE FACT` denotes a source-reported observation; it does not mean experimental verification in the present target system. `AUTHOR HYPOTHESIS` retains the source authors’ mechanistic interpretation. |
| `page` and `location` | Source page and descriptive section, figure or table locator. Physical PDF pages and publisher pagination remain distinguishable where supplied. |
| `quotation_excerpt` | Extracted passage excerpt. It may be shorter than the full source passage; the 43 quotation records supply the complete passages selected for the main evidence argument. |
| `quotation_id` | Q01–Q43, where the statement has a corresponding attributed quotation page. |
| `scope` | Chemical use of a statement, such as candidate-generation evidence, reaction/product precedent or P/Se applicability. It does not imply that every statement was supplied to the candidate generator. |

The 3,694 candidate-generation statements and the broader 3,756-statement collection are distinct evidence sets. The latter includes 673 original Chinese claims without an assigned English translation. Reader-facing chemical summaries are provided in English.

CSV downloads omit nonprinting NUL characters that occur in 42 positions in the extracted passage data. The JSON statement file retains those characters as escaped `\u0000` values. This display normalization removes no words, numbers or chemical claims. The complete quotation passages and other scientific fields are retained in the accompanying JSON data.

See the [evidence attribution guide](../evidence/attribution.md) before treating a statement as a reaction result or transferring it to a different donor, acceptor, activation regime or endpoint.

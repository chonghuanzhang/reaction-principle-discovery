# Evaluation protocol, offline checks and scientific status

The repository separates representation checks, source-evidence interpretation, search analysis and reaction-outcome validation. The local P/Se evaluator is executable and its eight existing integrity tests pass. The matched-evidence model comparison is prepared with **no successful new calls**; its performance and incremental-effect fields remain null. No independent chemical-discovery benchmark has been completed.

## Computational and analytical evaluation status

| Analysis | Status | What it establishes |
| --- | --- | --- |
| [100 molecule audit](../../candidates/README.md) | Completed | Graph parseability and uniqueness, not synthetic success |
| [Four RP cards / 43 attributed passages](../../evidence/README.md) | Completed | Source-linked chemical interpretation with applicability limits |
| [100 candidate-to-RP associations](evidence_network.md) | Completed | Transparent explanatory mapping, not historical generator replacement |
| [Eight local evaluator integrity tests](../evaluation/local_rules/test_conditional_rules.py) | Completed and runnable | Implementation consistency on development cases |
| [SH 100 paired runs](../../optimization/METHODS.md) | Completed | Search-budget differences on one measured response surface |
| [NH/OH selected trajectories](../../optimization/README.md) | Descriptive analysis | 180 selected responses; no whole-pool optimum or blind-test claim |
| [Matched model comparison](../evaluation/matched_evidence/llm_frozen_protocol.json) | Prepared, no successful new calls | No model superiority result |
| Independent chemical discovery benchmark | Not completed | Requires reaction-series outcomes withheld from development |

The 43 attributed passages belong to the current four-card synthesis. They are distinct from the 16 E-coded source-excerpt records used in the earlier diagnostic below. The current four cards are also distinct from the [five reviewed working constraints used in the original candidate calls](model_workflow.md).

## Local P/Se evaluator

The [interpreter](../evaluation/local_rules/conditional_rules.py) implements eight source-conditioned clauses using the [reviewed chemistry inputs](../evaluation/chemistry/README.md). All cases were available during construction. There is no fitted model, independent test split or calibrated reaction-success probability.

The earlier local identifiers describe three source-specific relationships: activation-dependent fluoride loss versus CF2-retaining P(O)H addition; donor-dependent acid response and subsequent HF addition of fluorovinyl products; and compatible selenium donors and nucleophilic-selenium interception in NiH chemistry. Their local RP1–RP3 numbering is **not** the paper's current four cross-class RP numbering.

Each clause retains the exact curated substrate, donor, activation and recorded condition descriptors, source observations, source yield basis and applicability boundary. An incomplete structure uses a source identifier instead of an invented SMILES. Matching a curated descriptor is a match to a reported source context, not a demonstration of prospective reactivity.

Premises are satisfied, not satisfied or unknown. Missing core inputs, source evidence or required conditions leave the query unresolved. Unsupported transfers are unknown rather than failed reactions. Explicit target non-observation remains local to its matched source system. A reported alternative endpoint does not establish the requested target. Opposing matched observations of the same endpoint cause abstention, regardless of duplicate rules or citation counts. Source conditions, local chemical relations, evidence access and uncertainty remain separate in the output.

The [15 queries](../evaluation/local_rules/rule_queries.json) comprise eight source cases, a changed target for P05, a P(O)H-to-Ph2PH donor swap, four project queries (AP087, AP088, SE_PROJECT and P_O_PROJECT), and SE03 with its BnBr condition unrecorded. The four project queries are unknown. [Recorded outputs](../evaluation/local_rules/rule_outputs.json), a [decision summary](../evaluation/local_rules/rule_decision_summary.csv) and [nine evidence-deletion interventions](../evaluation/local_rules/rule_evidence_interventions.csv) preserve the results. Evidence deletion is a software dependency check, not a model ablation result.

The eight existing tests check missing core features, removing all evidence, unseen substrates, exclusion of removed evidence, permutation/duplication invariance, conflict abstention, absence of success probabilities or unknown zero yields, and preservation of donor/condition specificity. The conflict fixture is synthetic software test data, never a literature observation. These tests establish implementation consistency on development cases, not external chemical accuracy or performance of the current four-principle architecture.

Run from the repository root with Python 3; this part uses only the standard library:

```sh
cd code/evaluation/local_rules
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v test_conditional_rules.py
cd ../../..
python3 code/evaluation/local_rules/build_rule_artifacts.py --output-dir /tmp/reaction-evaluation/rules
python3 code/evaluation/local_rules/conditional_rules.py code/evaluation/local_rules/rule_queries.json --output /tmp/reaction-evaluation/query_decisions.json
```

The build command regenerates the eight clauses, 15 queries, detailed outputs and nine interventions under the [integrity protocol](../evaluation/local_rules/rule_integrity_protocol.json). The standalone interpreter emits decisions/audits; the build command also adds source measurement and missing-information fields.

## Prepared matched-evidence comparison

The active [frozen protocol](../evaluation/matched_evidence/llm_frozen_protocol.json) is `20261025_evidence_interpretation_diagnostic_v2_E16_correction`. It contains [24 author-constructed claims](../evaluation/matched_evidence/llm_tasks.json) from [16 quotation-plus-curated-observation records](../evaluation/matched_evidence/llm_evidence.json) in six source families. The three labels are supported, contradicted and insufficient; the [sealed answer file](../evaluation/matched_evidence/llm_answers_sealed_from_prompts.json) contains nine, seven and eight labels, respectively. It is used only by scoring and is excluded from every prompt.

| Arm | Supplied information and procedure |
| --- | --- |
| `RP_explicit` | Shared evidence plus three source-derived conditional cards and an explicit premise/scope-checking procedure |
| `same_evidence_direct` | Identical evidence and claims, with direct reasoning and no fixed card representation |
| `no_retrieval` | Identical claims without supplied source evidence or cards; unresolved source-specific claims should remain insufficient |
| `RP_boundary_ablation` | Shared evidence with the local cards after removing applicability-boundary fields |

The actual ablation removes `preconditions`, `project_transfer` and `prediction_uncertainty`; other optional boundary fields named in the code were absent from this restricted card packet. Extra counterexamples absent from the shared evidence were excluded when the packet was prepared. The [four saved prompts](../evaluation/matched_evidence/llm_inputs/) are directly inspectable.

Five generation calls per arm were planned, for 20 calls in a [fixed randomized order](../evaluation/matched_evidence/llm_run_order.json), shuffled with seed 20261025. The recorded model identifier is `gpt-5.6-sol`. The shared schema requires a claim ID, three-way label, evidence-ID list and rationale, with rationales requested to remain under 45 words. The protocol specifies an 8,000-token output ceiling, no tools, no retries, no stored response, no specified temperature and no model-generation seed. The evidence arms share evidence order, claims, model setting, permissions, schema and output ceiling; the card representation adds input text, so exact input-token equality is not claimed. Actual input/output tokens and elapsed time must be reported. Monetary cost is unknown without an applicable rate or bill.

The primary contrast is source-family-balanced label agreement for `RP_explicit` minus `same_evidence_direct`. Removing retrieval changes information access and is a separate comparison. Source interpretation, molecular validity and reaction outcomes require separate metrics. The [deterministic structural-coverage reference](../evaluation/matched_evidence/deterministic_coverage_top12.csv) selects 12 candidates and is separate from the model arms; it has no reaction labels and is not scored for chemical success.

The [offline scorer](../evaluation/matched_evidence/score_llm_diagnostic.py) records exact label agreement, identifier membership and acceptance of an insufficiently supported claim. Its citation check tests only whether returned IDs belong to the evidence packet; an empty list passes this membership check. It establishes neither citation coverage nor entailment. Evidence-ID scoring is omitted for `no_retrieval`. Rationale quality and source entailment need a separate blinded human review.

With all five complete paired repeats, the planned interval uses 10,000 paired resamples over generation repeats and source families with NumPy's random generator seed 20261025. Fewer paired repeats leave the primary difference and interval null. This is a descriptive two-way bootstrap over six curated families and five generation repeats, not a population-wide chemical-accuracy interval. Repeated generations measure model variation; they do not add independent chemical tasks.

The protocol is not a historical preregistration. All sources were known during authoring; questions and labels were written by the authors. There is no independent chemical holdout, and public documents may have been present in model pretraining. A withheld answer file prevents direct prompt leakage but does not establish benchmark independence. Questions, labels, rules, limits and scoring must not be adjusted in response to model outputs; an amendment requires a new protocol version and separately reported results.

### E16 source correction

The [pre-inference amendment](../evaluation/matched_evidence/E16_protocol_amendment.json) corrects the precursor mechanism without changing task labels or the analysis plan. TFHZ-Tfs releases trifluorodiazoethane, CF3CHN2. The source authors propose metal-carbenoid formation, substrate trapping and beta-fluoride elimination; it is not a difluorocarbene-derived route. Benzeneselenol affords PhSe–CH=CF2 in 66%, retaining two fluorines with Se on the other vinyl carbon. This is an alternative endpoint, not target C(F)–Se connectivity. The scope locator is the paragraph beginning “Having established” and Figure 3, product 25; the proposed mechanism is in primary-text Par14 (body paragraph 17), Figure 6, with controls in Par13 (body paragraph 15), Figure 5. E16 contributes no executable clause to the eight-rule evaluator.

### Offline verification and scoring

The offline preparation script verifies input hashes, checks all seven source-extract hashes, and rebuilds prompts byte-for-byte against the four frozen files. It makes no model call and never reads the sealed answers into a prompt:

```sh
python3 code/evaluation/matched_evidence/run_llm_diagnostic.py --output-dir /tmp/reaction-evaluation/prompts
python3 code/evaluation/matched_evidence/score_llm_diagnostic.py --input-dir /tmp/reaction-evaluation/completed_calls --output-dir /tmp/reaction-evaluation/scores
```

Preparation and empty-result scoring use only Python's standard library. NumPy is required only when calculating the complete paired bootstrap. The scorer expects the completed-response envelope: `status`, `arm`, `replicate`, `elapsed_seconds`, and `result` containing `parsed_output.judgments` and token `usage`. It reads completed records only. With no completed records it writes zero successful calls and null performance/effect fields. This is the current [evaluation status](../evaluation/matched_evidence/llm_results_status.json).

## Reuse and remaining method test

The [input manifest](../evaluation/input_manifest.json) lists the scientific inputs and software with their hashes. Available materials include five frozen diagnostic input JSONs, four saved prompts, local rules, development queries, recorded outputs, the deterministic 12-candidate reference, source quotations and their interpretations. The [source index](../evaluation/matched_evidence/source_index.json) resolves the source locators in the prompt payloads. The commands above check input consistency, reproduce rule decisions and prepare the model prompts; they do not execute model inference or create reaction outcomes.

Future method evaluation should withhold source families and reaction series from development, preserve uncertain and unmeasured outcomes, and report uncertainty clustered by source. A working authorized inference connection is needed to execute the frozen model comparison; independent reaction-task outcomes are additionally required for a discovery-advantage claim. Offline consistency and archived-output reuse remain separate from new inference. Unmeasured conditions are never filled with synthetic yields or model-invented reaction outcomes.

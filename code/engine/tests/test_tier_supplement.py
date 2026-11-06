from pathlib import Path
from types import SimpleNamespace

from scripts.enrich_tier_supplement_abstracts import (
    prefilter_reasons,
    reconstruct_abstract,
    selected_tiers,
)
from scripts.retrieve_tier_supplement import normalize_doi, normalize_title
from scripts.screen_tier_supplement_abstracts import (
    AbstractDecision,
    AbstractDecisionBatch,
    build_batch_prompt,
    request_validated_batch,
    validate_batch_decisions,
)
from scripts.build_tier_supplement_fulltext_queue import build_queue
from scripts.build_tier_supplement_registry import build_registry
from scripts.resolve_tier_supplement_web_sources import deduplicate_sources
from scripts.fetch_tier_supplement_web_fulltext import (
    classify_document,
    parse_structured_document,
    rank_sources,
)
from scripts.extract_tier_supplement_web_evidence import (
    build_extraction_prompt,
    build_web_spans,
    ground_web_extraction,
)
from scripts.build_tier_supplement_web_registry import merge_registries
from scripts.transfer_tier_supplement_evidence import (
    build_transfer_prompt,
    materialize_assessments,
)
from scripts.synthesize_tier_supplement_principles import build_review_prompt
from scripts.assemble_tier_supplement_discovery_source import (
    assemble_discovery_source,
)
from scripts.summarize_tier_supplement_coordinate_space import (
    summarize_coordinate_space,
)
from scripts.run_v3_2_discovery import select_stratified_assessments


def _candidate(title: str, tiers: list[str], query_ids: list[str]) -> dict[str, object]:
    return {
        "title": title,
        "proposed_tiers": tiers,
        "matched_query_ids": query_ids,
    }


def test_identity_normalization_supports_doi_and_title_deduplication() -> None:
    assert normalize_doi("https://doi.org/10.1000/ABC.") == "10.1000/abc"
    assert normalize_title("C-F Activation: A Study") == "c f activation a study"


def test_tier_2_prefilter_accepts_defluorinative_mechanism_title() -> None:
    candidate = _candidate(
        "Selective Defluorinative Coupling of gem-Difluoroalkenes",
        ["tier_2"],
        ["TIER_2-Q01"],
    )
    assert prefilter_reasons(candidate, "tier_2")


def test_prefilter_rejects_single_broad_query_materials_noise() -> None:
    candidate = _candidate(
        "Modeling the Solid Electrolyte Interphase in Batteries",
        ["tier_2"],
        ["TIER_2-Q08"],
    )
    assert selected_tiers(candidate) == {}


def test_multiple_independent_queries_preserve_recall_for_chemistry_title() -> None:
    candidate = _candidate(
        "Mechanistic Study of a Catalytic Organic Reaction",
        ["tier_4"],
        ["TIER_4-Q01", "TIER_4-Q02"],
    )
    assert "tier_4" in selected_tiers(candidate)


def test_reconstruct_openalex_abstract_order() -> None:
    index = {"selective": [2], "A": [0], "reaction": [3], "fluorinated": [1]}
    assert reconstruct_abstract(index) == "A fluorinated selective reaction"


def test_screening_prompt_uses_only_blinded_tier_definitions() -> None:
    candidate = {
        "candidate_id": "TS-example",
        "doi": "10.1000/example",
        "title": "Selective carbon fluorine activation",
        "abstract": "A selective defluorination mechanism is reported.",
        "prefilter_tiers": ["tier_2"],
        "prefilter_reasons": {"tier_2": ["title_pattern:defluorin"]},
    }
    prompt = build_batch_prompt([candidate]).casefold()
    for forbidden in ("indole", "naphthol", "disulfide", "mercaptan"):
        assert forbidden not in prompt
    assert "unknown must remain unknown" in prompt


def test_validate_batch_decisions_requires_exact_candidate_coverage() -> None:
    candidates = [
        {"candidate_id": "TS-a", "prefilter_tiers": ["tier_2"]},
        {"candidate_id": "TS-b", "prefilter_tiers": ["tier_3"]},
    ]
    decisions = [
        AbstractDecision(
            candidate_id="TS-a",
            decision="include",
            primary_tier="tier_2",
            confidence="high",
            evidence_roles=["shared_reaction_manifold"],
            transferable_steps=["selective carbon-fluorine cleavage"],
            condition_signals=[],
            failure_boundary_signals=[],
            rationale="The abstract reports selective defluorination.",
            limitations=["Abstract only."],
            evidence_level="abstract_screening",
            full_text_priority="medium",
            full_text_reasons=["mechanism verification"],
        )
    ]
    try:
        validate_batch_decisions(candidates, decisions)
    except ValueError as exc:
        assert "exactly cover" in str(exc)
    else:
        raise AssertionError("missing candidate decision was accepted")


def test_abstract_decision_cannot_claim_decision_grade_failure_boundary() -> None:
    try:
        AbstractDecision(
            candidate_id="TS-a",
            decision="include",
            primary_tier="tier_4",
            confidence="high",
            evidence_roles=["failure_boundary"],
            transferable_steps=[],
            condition_signals=[],
            failure_boundary_signals=["Palladium is categorically incompatible."],
            rationale="The abstract mentions inhibition.",
            limitations=[],
            evidence_level="decision_grade",
            full_text_priority="high",
            full_text_reasons=["negative boundary verification"],
        )
    except ValueError as exc:
        assert "screening" in str(exc).casefold()
    else:
        raise AssertionError("abstract decision established a hard boundary")


def test_gateway_schema_requires_every_decision_property() -> None:
    schema = AbstractDecisionBatch.model_json_schema()
    decision_schema = schema["$defs"]["AbstractDecision"]
    assert set(decision_schema["required"]) == set(decision_schema["properties"])


def test_batch_request_retries_incomplete_candidate_coverage() -> None:
    candidate = {"candidate_id": "TS-a", "prefilter_tiers": ["tier_2"]}
    valid = {
        "candidate_id": "TS-a",
        "decision": "include",
        "primary_tier": "tier_2",
        "confidence": "high",
        "evidence_roles": ["shared_reaction_manifold"],
        "transferable_steps": ["selective carbon-fluorine cleavage"],
        "condition_signals": [],
        "failure_boundary_signals": [],
        "rationale": "Relevant selective defluorination is reported.",
        "limitations": ["Abstract only."],
        "evidence_level": "abstract_screening",
        "full_text_priority": "medium",
        "full_text_reasons": ["mechanism verification"],
    }

    class Client:
        calls = 0

        def create_structured(self, *args, **kwargs):
            del args, kwargs
            self.calls += 1
            payload = {"decisions": []} if self.calls == 1 else {"decisions": [valid]}
            return SimpleNamespace(parsed_output=payload)

    client = Client()
    parsed, _ = request_validated_batch(client, [candidate], "model", max_attempts=2)
    assert [item.candidate_id for item in parsed.decisions] == ["TS-a"]
    assert client.calls == 2


def test_batch_request_retries_transient_transport_timeout() -> None:
    candidate = {"candidate_id": "TS-a", "prefilter_tiers": ["tier_2"]}
    valid = {
        "candidate_id": "TS-a", "decision": "include", "primary_tier": "tier_2",
        "confidence": "high", "evidence_roles": [], "transferable_steps": [],
        "condition_signals": [], "failure_boundary_signals": [],
        "rationale": "Relevant abstract.", "limitations": [],
        "evidence_level": "abstract_screening", "full_text_priority": "low",
        "full_text_reasons": [],
    }

    class Client:
        calls = 0

        def create_structured(self, *args, **kwargs):
            del args, kwargs
            self.calls += 1
            if self.calls == 1:
                raise TimeoutError("transient timeout")
            return SimpleNamespace(parsed_output={"decisions": [valid]})

    client = Client()
    parsed, _ = request_validated_batch(client, [candidate], "model", max_attempts=2)
    assert parsed.decisions[0].candidate_id == "TS-a"
    assert client.calls == 2


def test_fulltext_queue_prioritizes_decision_critical_records_without_answer_terms() -> None:
    records = [
        {
            "candidate_id": "TS-high",
            "doi": "10.1000/high",
            "pdf_url": "https://example.org/high.pdf",
            "title": "Selective fluorinated alkene transformation",
            "abstract_screening": {
                "decision": "include", "primary_tier": "tier_2",
                "full_text_priority": "high", "full_text_reasons": ["mechanism"],
            },
        },
        {
            "candidate_id": "TS-low",
            "doi": "10.1000/low",
            "pdf_url": "https://example.org/low.pdf",
            "title": "General chemistry",
            "abstract_screening": {
                "decision": "include", "primary_tier": "tier_3",
                "full_text_priority": "low", "full_text_reasons": [],
            },
        },
    ]
    queue = build_queue(records)
    assert [row["candidate_id"] for row in queue] == ["TS-high"]
    assert "indole" not in str(queue).casefold()


def test_registry_uses_authoritative_candidate_directory_id(tmp_path) -> None:
    extraction_root = tmp_path / "extractions"
    paper_root = extraction_root / "TS-authoritative"
    paper_root.mkdir(parents=True)
    (paper_root / "validated.json").write_text(
        '{"extraction":{"paper_id":"model-invented","primary_tier":"tier_2",'
        '"bibliography":{"title":"Paper"},"source_file":"source.pdf","sha256":"abc",'
        '"evidence_types":[],"reaction_summary":{},"evidence_items":[],"uncertainties":[],'
        '"contradictions":[]}}', encoding="utf-8"
    )
    queue = tmp_path / "queue.json"
    queue.write_text(
        '{"queue":[{"candidate_id":"TS-authoritative","doi":"10.1000/x",'
        '"title":"Paper","primary_tier":"tier_2"}]}', encoding="utf-8"
    )
    registry = build_registry(extraction_root, queue)
    assert registry["records"][0]["candidate_id"] == "TS-authoritative"


def test_web_source_resolution_deduplicates_urls_and_prefers_fulltext_hints() -> None:
    sources = deduplicate_sources([
        {"provider": "openalex", "url": "https://example.org/a", "format": "landing"},
        {"provider": "crossref", "url": "https://example.org/a", "format": "html"},
        {"provider": "europe_pmc", "url": "https://example.org/full.xml", "format": "xml"},
    ])
    assert [source["url"] for source in sources] == [
        "https://example.org/full.xml", "https://example.org/a"
    ]


def test_xml_full_text_preserves_section_and_paragraph_locators() -> None:
    body = " ".join(["Mechanistic observation under catalytic conditions."] * 60)
    xml = f"""
    <article><front><article-meta><abstract><p>Short abstract.</p></abstract></article-meta></front>
      <body><sec id="s1"><title>Results and discussion</title>
        <p id="p1">{body}</p><p id="p2">A competing pathway gave decomposition.</p>
      </sec></body></article>
    """.encode()
    parsed = parse_structured_document(xml, "application/xml", "https://example.org/full.xml")
    assert parsed["body_character_count"] > 2000
    assert parsed["paragraphs"][0]["locator"] == "section:s1:Results and discussion; paragraph:p1"
    assert parsed["paragraphs"][1]["text"] == "A competing pathway gave decomposition."
    assert classify_document(200, {}, xml, parsed) == "full_text"


def test_abstract_without_article_body_is_never_classified_as_full_text() -> None:
    abstract = " ".join(["Selective transformation is described."] * 30)
    xml = f"<article><front><article-meta><abstract><p>{abstract}</p></abstract></article-meta></front></article>".encode()
    parsed = parse_structured_document(xml, "application/xml", "https://example.org/abstract.xml")
    assert parsed["body_character_count"] == 0
    assert classify_document(200, {}, xml, parsed) == "abstract_only"


def test_subscription_page_is_classified_as_paywall_not_full_text() -> None:
    html = b"<html><body><h1>Purchase access</h1><p>Sign in through your institution to read this article.</p></body></html>"
    parsed = parse_structured_document(html, "text/html", "https://publisher.example/article")
    assert classify_document(403, {"content-type": "text/html"}, html, parsed) == "paywall"


def test_source_ranking_prefers_exact_xml_then_repository_pdf() -> None:
    sources = [
        {"url": "https://doi.org/10.1/x", "format": "landing", "provider": "doi"},
        {"url": "https://repo.example/paper.pdf", "format": "pdf", "provider": "openalex", "version": "acceptedVersion"},
        {"url": "https://europepmc.example/full.xml", "format": "xml", "provider": "europe_pmc"},
    ]
    ranked = rank_sources(sources)
    assert [row["url"] for row in ranked] == [
        "https://europepmc.example/full.xml",
        "https://repo.example/paper.pdf",
        "https://doi.org/10.1/x",
    ]


def test_web_spans_keep_stable_section_paragraph_and_sentence_locator() -> None:
    parsed = {"paragraphs": [{
        "locator": "section:s2:Mechanism; paragraph:p4",
        "section": "Mechanism",
        "text": "The intermediate was observed. Decomposition occurred above 80 C.",
    }]}
    spans = build_web_spans(parsed)
    assert spans == [
        {"span_id": "W00001", "locator": "section:s2:Mechanism; paragraph:p4; sentence:s001", "section": "Mechanism", "text": "The intermediate was observed."},
        {"span_id": "W00002", "locator": "section:s2:Mechanism; paragraph:p4; sentence:s002", "section": "Mechanism", "text": "Decomposition occurred above 80 C."},
    ]


def test_ground_web_extraction_materializes_exact_source_quote_and_provenance() -> None:
    spans = [{"span_id": "W00001", "locator": "section:s1:Results; paragraph:p2; sentence:s001", "section": "Results", "text": "No product formed without base."}]
    raw = {"evidence_items": [{"evidence_id": "E1", "claim": "Base is required.", "source_span_ids": ["W00001"], "transferable_step": "base-enabled activation", "conditions": ["base present"], "failure_boundaries": ["no conversion without base"], "evidence_strength": "direct", "attribution": "author_observation"}]}
    grounded = ground_web_extraction(raw, spans, candidate_id="TS-x", doi="10.1/x", title="Paper", tier="tier_4", source_url="https://example.org/full")
    item = grounded["evidence_items"][0]
    assert item["quotation"] == "No product formed without base."
    assert item["locators"] == ["section:s1:Results; paragraph:p2; sentence:s001"]
    assert grounded["source_url"] == "https://example.org/full"


def test_ground_web_extraction_repairs_only_unambiguous_missing_zero_padding() -> None:
    spans = [{"span_id": "W00014", "locator": "section:s1; paragraph:p1; sentence:s001", "section": "Results", "text": "Observed text."}]
    raw = {"evidence_items": [{"evidence_id": "E1", "claim": "Observed.", "source_span_ids": ["W0014"], "transferable_step": "UNKNOWN", "conditions": [], "failure_boundaries": [], "evidence_strength": "direct", "attribution": "author_observation"}]}
    grounded = ground_web_extraction(raw, spans, candidate_id="TS-x", doi=None, title="Paper", tier="tier_3", source_url="https://example.org/full")
    assert grounded["evidence_items"][0]["source_span_ids"] == ["W00014"]
    assert grounded["evidence_items"][0]["quotation"] == "Observed text."


def test_web_extraction_prompt_is_blinded_to_known_outcomes() -> None:
    prompt = build_extraction_prompt(
        {"candidate_id": "TS-x", "doi": "10.1/x", "title": "Generic paper", "tier": "tier_3"},
        [{"span_id": "W00001", "locator": "section:s1:Results; paragraph:p1; sentence:s001", "section": "Results", "text": "A generic nucleophile reacts."}],
    ).casefold()
    for forbidden in ("indole", "naphthol", "disulfide", "mercaptan"):
        assert forbidden not in prompt
    assert "do not infer transferability" in prompt


def test_merge_web_registry_preserves_existing_records_without_duplicates() -> None:
    existing = {"records": [{"candidate_id": "TS-old", "evidence_items": [{"evidence_id": "E-old"}], "contradictions": []}]}
    web = {"records": [{"candidate_id": "TS-new", "evidence_items": [{"evidence_id": "E-new"}], "contradictions": ["conflict"]}]}
    merged = merge_registries(existing, web)
    assert [row["candidate_id"] for row in merged["records"]] == ["TS-new", "TS-old"]
    assert merged["record_count"] == 2
    assert merged["evidence_item_count"] == 2
    assert merged["contradiction_count"] == 1
    evidence_ids = [item["evidence_id"] for row in merged["records"] for item in row["evidence_items"]]
    assert evidence_ids == ["TS-new:E-new", "TS-old:E-old"]
    assert merged["evidence_ids_unique"] is True


def test_supplement_transfer_prompt_excludes_seed_success_scope_and_known_outcomes() -> None:
    seed = {"reaction_center": ["activated carbon"], "elementary_steps": ["elimination"], "successful_scope": ["SEALED SUCCESS"], "evidence_ids": ["SE-1"]}
    record = {"candidate_id": "TS-x", "title": "Generic", "doi": "10.1/x", "primary_tier": "tier_2", "evidence_items": [{"evidence_id": "TS-x:E1", "claim": "Generic trapping occurs.", "quotation": "Generic trapping occurs.", "locators": ["section:s1"], "transferable_step": "trapping", "conditions": [], "failure_boundaries": [], "evidence_strength": "direct"}]}
    prompt = build_transfer_prompt(seed, record).casefold()
    assert "sealed success" not in prompt
    for forbidden in ("indole", "naphthol", "disulfide", "mercaptan"):
        assert forbidden not in prompt


def test_materialize_supplement_transfer_uses_authoritative_ids_and_deterministic_score() -> None:
    seed = {"evidence_ids": ["SE-1"]}
    record = {"candidate_id": "TS-x", "evidence_items": [{"evidence_id": "TS-x:E1", "evidence_strength": "direct"}]}
    raw = {"assessments": [{"source_evidence_ids": ["TS-x:E1"], "seed_feature_ids": ["SE-1"], "shared_elementary_step": "nucleophilic trapping", "matched_requirements": ["electrophile state"], "mismatched_requirements": [], "blocking_constraints": [], "transfer_status": "conditional", "transferable_claim": "The local trapping step is conditionally analogous.", "conditions": ["base"], "uncertainty": ["catalyst compatibility"], "falsifying_test": "No trapping under matched conditions."}]}
    assessments = materialize_assessments(raw, seed, record)
    assert assessments[0].source_paper_id == "TS-x"
    assert assessments[0].source_evidence_ids == ("TS-x:E1",)
    assert assessments[0].assessment_id.startswith("KT2-")
    assert assessments[0].score_components["total"] == 7


def test_principle_review_prompt_excludes_seed_success_scope() -> None:
    prompt = build_review_prompt(
        {"reaction_center": ["center"], "successful_scope": ["SEALED SUCCESS"], "evidence_ids": ["SE-1"]},
        [{"principle_id": "RP-1", "supporting_transferred_evidence": ["KT-1"]}],
        {"KT-1": {"assessment_id": "KT-1", "transfer_status": "conditional"}},
    ).casefold()
    assert "sealed success" not in prompt
    assert "independent evidence review" in prompt


def test_discovery_assessment_selection_preserves_positive_negative_and_unknown_strata() -> None:
    rows = []
    for status, count in (("transferable", 4), ("conditional", 40), ("non_transferable", 25), ("unknown", 15)):
        for index in range(count):
            rows.append(SimpleNamespace(assessment_id=f"{status}-{index}", transfer_status=status, score_components={"total": count - index}, source_paper_id=f"{status}-paper-{index}"))
    selected = select_stratified_assessments(tuple(rows), limit=40)
    statuses = {item.transfer_status for item in selected}
    assert statuses == {"transferable", "conditional", "non_transferable", "unknown"}
    assert len(selected) == 40


def test_assemble_discovery_source_combines_baseline_and_supplement(tmp_path) -> None:
    root = tmp_path / "source"
    baseline_rel = "derived/principles_v3/clean_inputs/original/derived/principles/transfer_assessments.json"
    baseline_path = root / baseline_rel
    baseline_path.parent.mkdir(parents=True)
    assessment = {
        "assessment_id": "KT-baseline",
        "source_paper_id": "P-baseline",
        "source_mechanism_id": "M-baseline",
        "source_evidence_ids": ["E-baseline"],
        "seed_feature_ids": ["SE-1"],
        "shared_elementary_step": "local trapping",
        "matched_requirements": [],
        "mismatched_requirements": [],
        "blocking_constraints": [],
        "transfer_status": "conditional",
        "transferable_claim": "A local step may transfer.",
        "conditions": [],
        "uncertainty": ["system compatibility"],
        "falsifying_test": "No target under matched conditions.",
        "score_components": {"total": 1},
    }
    baseline_path.write_text(
        __import__("json").dumps({"assessments": [assessment]}), encoding="utf-8"
    )
    manifest_path = root / "derived/principles_v3/evidence_import_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        __import__("json").dumps({
            "manifest_digest": "a" * 64,
            "accepted": [{"artifact_type": "transfer", "path": baseline_rel}],
        }),
        encoding="utf-8",
    )
    supplement = tmp_path / "supplement.json"
    supplement_row = {**assessment, "assessment_id": "KT-supplement", "source_paper_id": "P-supplement"}
    supplement.write_text(
        __import__("json").dumps({"assessments": [supplement_row]}), encoding="utf-8"
    )
    registry = tmp_path / "registry.json"
    registry.write_text(
        __import__("json").dumps({"registry_sha256": "b" * 64}), encoding="utf-8"
    )
    frozen = Path("runs/tier_supplement_v1/workflow_rerun/frozen_principles.json")
    output = tmp_path / "assembled"

    summary = assemble_discovery_source(root, supplement, registry, frozen, output)

    assert summary["assessment_count"] == 2
    assert summary["paper_count"] == 2
    assembled_manifest = __import__("json").loads(
        (output / "derived/principles_v3/evidence_import_manifest.json").read_text(encoding="utf-8")
    )
    combined_path = output / assembled_manifest["accepted"][0]["path"]
    combined = __import__("json").loads(combined_path.read_text(encoding="utf-8"))
    assert [row["assessment_id"] for row in combined["assessments"]] == [
        "KT-baseline", "KT-supplement"
    ]
    assert (output / "derived/principles_v3/frozen_principles.json").is_file()


def test_coordinate_summary_merges_rounds_and_preserves_unknown_without_rank() -> None:
    coordinate_a = {
        "nucleophilic_center": "sulfur_center",
        "reactive_state": "anionic_state",
        "bond_forming_mode": "polar_addition_elimination",
        "activation_mode": "base_activation",
        "attack_topology": "fluorinated_alkene_carbon",
        "target_termination": "protonation_then_selective_fluoride_elimination",
    }
    coordinate_b = {**coordinate_a, "nucleophilic_center": "phosphorus_center"}

    def proposal(proposal_id: str, coordinate: dict, evidence_ids: list[str]) -> dict:
        return {
            "proposal_id": proposal_id,
            "coordinate_assignment": coordinate,
            "source_channel": "literature_derived",
            "evidence_level": "traceable_external_evidence",
            "evidence_ids": evidence_ids,
            "parent_hypothesis": f"hypothesis {proposal_id}",
            "representative_reactive_state": f"state {proposal_id}",
            "mechanistic_definition": {
                "critical_conditions": [f"condition {proposal_id}"],
                "dominant_failure_modes": [f"failure {proposal_id}"],
            },
            "counterarguments": [],
            "unknowns": [],
        }

    rounds = [
        {"round_id": 1, "lane_results": [{"lane_id": "A", "channel": "literature_derived", "proposals": [proposal("P1", coordinate_a, ["KT-1"]), proposal("P2", coordinate_b, ["KT-U"])]}]},
        {"round_id": 2, "lane_results": [{"lane_id": "B", "channel": "literature_derived", "proposals": [proposal("P1", coordinate_a, ["KT-1", "KT-2"])]}]},
    ]
    assessments = [
        {"assessment_id": "KT-1", "source_paper_id": "Paper-1", "transfer_status": "conditional", "conditions": ["mild base"], "blocking_constraints": [], "mismatched_requirements": [], "uncertainty": [], "transferable_claim": "Local capture may transfer."},
        {"assessment_id": "KT-2", "source_paper_id": "Paper-2", "transfer_status": "transferable", "conditions": ["low temperature"], "blocking_constraints": ["oxidation"], "mismatched_requirements": [], "uncertainty": [], "transferable_claim": "The local step transfers."},
        {"assessment_id": "KT-U", "source_paper_id": "Paper-3", "transfer_status": "unknown", "conditions": [], "blocking_constraints": [], "mismatched_requirements": [], "uncertainty": ["not tested"], "transferable_claim": "Unknown."},
    ]

    result = summarize_coordinate_space(rounds, assessments, [])
    sulfur = next(row for row in result["regions"] if row["coordinate"]["nucleophilic_center"] == "sulfur_center")
    phosphorus = next(row for row in result["regions"] if row["coordinate"]["nucleophilic_center"] == "phosphorus_center")

    assert sulfur["proposal_count"] == 2
    assert sulfur["assessment_status_counts"] == {"transferable": 1, "conditional": 1, "non_transferable": 0, "unknown": 0}
    assert sulfur["provisional_score"] == 6
    assert sulfur["classification"] == "explore_high"
    assert sulfur["priority_rank"] == 1
    assert sulfur["condition_evidence"][0]["assessment_ids"]
    assert phosphorus["classification"] == "insufficient_evidence"
    assert phosphorus["priority_rank"] is None

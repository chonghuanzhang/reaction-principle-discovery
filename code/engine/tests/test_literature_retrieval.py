from __future__ import annotations

import pytest

from pipeline.literature_retrieval import (
    EvidenceDecision,
    LiteratureRetrievalError,
    SearchQuery,
    SearchRecord,
    build_hypothesis_queries,
    build_seed_queries,
    normalize_search_results,
    query_inputs_for_audit,
    select_full_text_requests,
)
from pipeline.principle_models import PrincipleProvenance, ReactionPrinciple, SeedMechanism
from pipeline.v3_models import FamilyDefinition


def _seed() -> SeedMechanism:
    return SeedMechanism(
        seed_reaction_id="SR-TEST-001",
        reaction_center=["activated C-X center"],
        electrophile_state=["polarized electrophile"],
        nucleophile_state=["reactive partner state"],
        bond_changes=["form C-Nu"],
        reactive_intermediates=["addition intermediate"],
        elementary_steps=["local addition"],
        electronic_requirements=["electron-poor center"],
        steric_requirements=[],
        catalyst_roles=["Lewis-acid activation"],
        condition_window=["low water activity"],
        successful_scope=["seed substrate"],
        failed_scope=[],
        competing_pathways=["premature protonation"],
        evidence_ids=["SE-001"],
        confidence="high",
    )


def _principles() -> tuple[ReactionPrinciple, ...]:
    return (
        ReactionPrinciple(
            principle_id="RP-001",
            title="Synthetic sealed family label",
            status="accepted",
            claim="A local addition mechanism is relevant.",
            mechanistic_basis=["local addition"],
            applicable_electrophile_families=["Synthetic sealed family label"],
            applicable_nucleophile_families=["Synthetic sealed family label"],
            required_reactive_form="activated reactive partner state",
            catalyst_requirements=["Lewis-acid activation"],
            condition_window=["low water activity"],
            structural_promoters=[],
            structural_inhibitors=[],
            supporting_seed_evidence=["SE-001"],
            supporting_transferred_evidence=[],
            contradictory_evidence=[],
            known_exceptions=[],
            predicted_failure_modes=["premature protonation"],
            confidence="medium",
            experimental_consequence="Probe the local addition under controlled conditions.",
            falsifying_experiment="Measure whether local addition occurs.",
            review_status="accepted",
            provenance=PrincipleProvenance(run_id="test-run"),
            freeze_version=None,
        ),
    )


def _family() -> FamilyDefinition:
    return FamilyDefinition(
        family_id="FAM-TEST-001",
        nucleophilic_center="heteroatom center",
        reactive_state="deprotonated reactive state",
        bond_forming_mode="polar addition",
        activation_mode="base enabled",
        critical_conditions=("controlled proton source",),
        dominant_failure_modes=("competitive termination",),
    )


def _synthetic_sealed_term() -> str:
    return "Synthetic sealed family label"


def test_seed_queries_use_mechanism_features_not_family_names() -> None:
    queries = build_seed_queries(_seed(), _principles())

    assert all(query.origin_type == "seed_mechanism" for query in queries)
    assert all(query.origin_ids for query in queries)
    assert not any(_synthetic_sealed_term() in query.text for query in queries)


def test_hypothesis_query_records_family_origin() -> None:
    query = build_hypothesis_queries([_family()])[0]

    assert query.origin_type == "taxonomy_hypothesis"
    assert query.origin_ids == (_family().family_id,)
    assert _family().family_id not in query.text


def test_normalize_results_preserves_provider_query_and_metadata_evidence() -> None:
    query = SearchQuery(
        query_id="Q-SEED-001",
        text="activated C-X center local addition",
        origin_type="seed_mechanism",
        origin_ids=("SR-TEST-001", "RP-001"),
    )
    records = normalize_search_results(
        query,
        [
            {
                "provider": "OpenAlex",
                "retrieved_at": "2026-08-13",
                "hit_count": 12,
                "doi": "https://doi.org/10.1000/EXAMPLE",
                "title": "A recorded mechanism paper",
                "abstract": "Abstract fixture.",
                "access_level": "abstract",
                "screening_decision": "pending",
            }
        ],
    )

    assert records[0].provider == "openalex"
    assert records[0].query_id == query.query_id
    assert records[0].origin_ids == query.origin_ids
    assert records[0].abstract_available is True
    assert records[0].evidence_location == "abstract"
    assert records[0].deduplication_key == "doi:10.1000/example"


def test_normalize_results_deduplicates_by_doi_across_recorded_providers() -> None:
    query = SearchQuery(
        query_id="Q-SEED-002",
        text="local addition electronic requirement",
        origin_type="seed_mechanism",
        origin_ids=("SR-TEST-001",),
    )
    records = normalize_search_results(
        query,
        [
            {
                "provider": "crossref",
                "retrieved_at": "2026-08-13",
                "hit_count": 2,
                "doi": "10.1000/example",
                "title": "A recorded mechanism paper",
                "access_level": "metadata",
            },
            {
                "provider": "publisher",
                "retrieved_at": "2026-08-13",
                "hit_count": 2,
                "doi": "doi:10.1000/EXAMPLE",
                "title": "A recorded mechanism paper",
                "abstract": "Publisher fixture abstract.",
                "access_level": "abstract",
            },
        ],
    )

    assert len(records) == 1
    assert records[0].provider == "publisher"
    assert records[0].abstract_available is True


def test_query_inputs_for_audit_records_exact_query_ids_and_text() -> None:
    queries = build_seed_queries(_seed(), _principles())

    assert tuple(item.query_id for item in query_inputs_for_audit(queries)) == tuple(
        query.query_id for query in queries
    )
    assert tuple(item.text for item in query_inputs_for_audit(queries)) == tuple(
        query.text for query in queries
    )


def test_query_inputs_for_audit_preserves_all_search_query_fields() -> None:
    query = SearchQuery(
        query_id="Q-HYP-AUDIT",
        text="heteroatom deprotonated",
        origin_type="taxonomy_hypothesis",
        origin_ids=("FAM-TEST-001",),
        candidate_family_terms=("heteroatom", "deprotonated"),
        generation_basis="frozen_open_taxonomy",
    )

    audit_input = query_inputs_for_audit((query,))[0]

    assert audit_input.model_dump(mode="json") == query.model_dump(mode="json")


def _records() -> tuple[SearchRecord, ...]:
    query = SearchQuery(
        query_id="Q-HYP-001",
        text="deprotonated reactive state polar addition",
        origin_type="taxonomy_hypothesis",
        origin_ids=("FAM-TEST-001",),
    )
    return normalize_search_results(
        query,
        [
            {
                "provider": "semantic_scholar",
                "retrieved_at": "2026-08-13",
                "hit_count": 2,
                "doi": "10.1000/blocker",
                "title": "Abstract-level blocker evidence",
                "abstract": "A relevant abstract.",
                "access_level": "abstract",
            },
            {
                "provider": "semantic_scholar",
                "retrieved_at": "2026-08-13",
                "hit_count": 2,
                "doi": "10.1000/background",
                "title": "Background evidence",
                "access_level": "metadata",
            },
        ],
    )


def _decisions() -> tuple[EvidenceDecision, ...]:
    return (
        EvidenceDecision(
            decision_id="D-BLOCKER",
            record_id="SR-doi-10.1000-blocker",
            claim="The asserted incompatibility requires source verification.",
            material_effect="hard_blocker",
            evidence_location="abstract",
        ),
        EvidenceDecision(
            decision_id="D-BACKGROUND",
            record_id="SR-doi-10.1000-background",
            claim="Background discovery only.",
            material_effect="screening",
            evidence_location="metadata",
        ),
    )


def test_full_text_requested_only_for_decision_critical_claim() -> None:
    requests = select_full_text_requests(_records(), _decisions())

    assert [request.reason for request in requests] == ["hard_blocker_verification"]


def test_abstract_evidence_cannot_establish_hard_blocker() -> None:
    try:
        EvidenceDecision(
            decision_id="D-INVALID",
            record_id="SR-doi-10.1000-blocker",
            claim="An abstract cannot establish a hard blocker.",
            material_effect="hard_blocker",
            evidence_location="abstract",
            establishes_decision=True,
        )
    except ValueError as exc:
        assert "located full text or supporting information" in str(exc)
    else:
        raise AssertionError("abstract evidence established a decision-critical hard blocker")


def test_abstract_record_rejects_forged_full_text_hard_blocker() -> None:
    forged = EvidenceDecision(
        decision_id="D-FORGED",
        record_id="SR-doi-10.1000-blocker",
        claim="A forged location cannot establish a blocker.",
        material_effect="hard_blocker",
        evidence_location="full_text",
        establishes_decision=True,
    )

    with pytest.raises(LiteratureRetrievalError, match="contradicts.*abstract"):
        select_full_text_requests(_records(), (forged,))


def test_rejects_decision_for_unknown_record() -> None:
    unknown = EvidenceDecision(
        decision_id="D-UNKNOWN",
        record_id="SR-unknown",
        claim="An unresolved record cannot support a decision.",
        material_effect="screening",
        evidence_location="metadata",
    )

    with pytest.raises(LiteratureRetrievalError, match="unknown search record"):
        select_full_text_requests(_records(), (unknown,))


@pytest.mark.parametrize("evidence_location", ("full_text", "supporting_information"))
def test_located_record_can_establish_decision_critical_claim(
    evidence_location: str,
) -> None:
    query = SearchQuery(
        query_id=f"Q-LOCATED-{evidence_location}",
        text="recorded local evidence",
        origin_type="taxonomy_hypothesis",
        origin_ids=("FAM-TEST-001",),
    )
    records = normalize_search_results(
        query,
        [
            {
                "provider": "publisher",
                "retrieved_at": "2026-08-13",
                "hit_count": 1,
                "doi": f"10.1000/{evidence_location}",
                "title": f"Located {evidence_location} evidence",
                "access_level": "restricted",
                "evidence_location": evidence_location,
            }
        ],
    )
    decision = EvidenceDecision(
        decision_id=f"D-{evidence_location}",
        record_id=records[0].record_id,
        claim="Located source evidence resolves the material claim.",
        material_effect="hard_blocker",
        evidence_location=evidence_location,
        establishes_decision=True,
    )

    assert select_full_text_requests(records, (decision,)) == ()


@pytest.mark.parametrize("evidence_location", ("metadata", "abstract"))
def test_noncritical_screening_can_use_metadata_or_abstract(
    evidence_location: str,
) -> None:
    query = SearchQuery(
        query_id=f"Q-SCREEN-{evidence_location}",
        text="recorded discovery evidence",
        origin_type="seed_mechanism",
        origin_ids=("SR-TEST-001",),
    )
    raw: dict[str, object] = {
        "provider": "crossref",
        "retrieved_at": "2026-08-13",
        "hit_count": 1,
        "doi": f"10.1000/screen-{evidence_location}",
        "title": f"Screening {evidence_location} evidence",
        "access_level": evidence_location,
    }
    if evidence_location == "abstract":
        raw["abstract"] = "Recorded screening abstract."
    records = normalize_search_results(query, [raw])
    decision = EvidenceDecision(
        decision_id=f"D-SCREEN-{evidence_location}",
        record_id=records[0].record_id,
        claim="The record is relevant for screening.",
        material_effect="screening",
        evidence_location=evidence_location,
        establishes_decision=True,
    )

    assert select_full_text_requests(records, (decision,)) == ()

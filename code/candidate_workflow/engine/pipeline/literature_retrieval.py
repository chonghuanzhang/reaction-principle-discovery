"""Database-neutral, provenance-tracked contracts for v3 literature retrieval.

This module only builds queries and normalizes recorded connector results.  It
does not perform network I/O; callers provide recorded provider fixtures and
must place :func:`query_inputs_for_audit` output in the active leakage policy
before scanning any retrieved material.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from typing import Literal

from pydantic import Field, model_validator

from pipeline.leakage_audit import QueryInput
from pipeline.principle_models import FrozenStrictModel, ReactionPrinciple, SeedMechanism
from pipeline.v3_models import FamilyDefinition


QueryOrigin = Literal["seed_mechanism", "taxonomy_hypothesis"]
Provider = Literal["crossref", "openalex", "semantic_scholar", "publisher"]
EvidenceLocation = Literal["metadata", "abstract", "full_text", "supporting_information"]
AccessLevel = Literal["metadata", "abstract", "open", "restricted", "unknown"]
ScreeningDecision = Literal["pending", "include", "exclude", "uncertain"]
MaterialEffect = Literal[
    "screening", "top_rank", "hard_blocker", "negative_boundary", "critical_condition"
]
FullTextReason = Literal[
    "top_rank_verification",
    "hard_blocker_verification",
    "negative_boundary_verification",
    "critical_condition_verification",
]


class LiteratureRetrievalError(ValueError):
    """Raised when a connector fixture cannot satisfy the retrieval contract."""


class SearchQuery(FrozenStrictModel):
    """One query whose origin is available to the active leakage audit."""

    query_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    origin_type: QueryOrigin
    origin_ids: tuple[str, ...] = Field(min_length=1)
    candidate_family_terms: tuple[str, ...] = ()
    generation_basis: str = "legacy"


class SearchRecord(FrozenStrictModel):
    """A normalized, deduplicated provider result and its screening status."""

    record_id: str = Field(min_length=1)
    provider: Provider
    query_id: str = Field(min_length=1)
    query_text: str = Field(min_length=1)
    query_origin_type: QueryOrigin
    origin_ids: tuple[str, ...] = Field(min_length=1)
    retrieved_at: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    hit_count: int = Field(ge=0)
    doi: str | None = None
    title: str = Field(min_length=1)
    abstract: str | None = None
    abstract_available: bool
    access_level: AccessLevel
    evidence_location: EvidenceLocation
    deduplication_key: str = Field(min_length=1)
    screening_decision: ScreeningDecision = "pending"

    @model_validator(mode="after")
    def require_abstract_when_available(self) -> "SearchRecord":
        if self.abstract_available != bool(self.abstract and self.abstract.strip()):
            raise ValueError("abstract availability must match the recorded abstract")
        if self.evidence_location == "abstract" and not self.abstract_available:
            raise ValueError("abstract evidence location requires a recorded abstract")
        if (
            self.evidence_location in {"full_text", "supporting_information"}
            and self.access_level in {"metadata", "abstract"}
        ):
            raise ValueError(
                "located evidence cannot have metadata-only or abstract-only access"
            )
        return self


class EvidenceDecision(FrozenStrictModel):
    """A proposed use of one record, before or after decision-grade evidence exists."""

    decision_id: str = Field(min_length=1)
    record_id: str = Field(min_length=1)
    claim: str = Field(min_length=1)
    material_effect: MaterialEffect
    evidence_location: EvidenceLocation
    establishes_decision: bool = False

    @model_validator(mode="after")
    def restrict_decision_critical_evidence(self) -> "EvidenceDecision":
        critical_effects = {
            "top_rank",
            "hard_blocker",
            "negative_boundary",
            "critical_condition",
        }
        if (
            self.establishes_decision
            and self.material_effect in critical_effects
            and self.evidence_location not in {"full_text", "supporting_information"}
        ):
            raise ValueError(
                "decision-critical claims require located full text or supporting information"
            )
        return self


class FullTextRequest(FrozenStrictModel):
    """A narrowly scoped request to upgrade unresolved, material evidence."""

    request_id: str = Field(min_length=1)
    record_id: str = Field(min_length=1)
    deduplication_key: str = Field(min_length=1)
    title: str = Field(min_length=1)
    doi: str | None = None
    reason: FullTextReason
    decision_ids: tuple[str, ...] = Field(min_length=1)


_PROVIDER_ALIASES = {
    "crossref": "crossref",
    "openalex": "openalex",
    "semantic scholar": "semantic_scholar",
    "semantic_scholar": "semantic_scholar",
    "semanticscholar": "semantic_scholar",
    "publisher": "publisher",
}
_LOCATION_RANK = {
    "metadata": 0,
    "abstract": 1,
    "full_text": 2,
    "supporting_information": 3,
}
_REQUEST_REASON = {
    "top_rank": "top_rank_verification",
    "hard_blocker": "hard_blocker_verification",
    "negative_boundary": "negative_boundary_verification",
    "critical_condition": "critical_condition_verification",
}
_REQUEST_PRIORITY = {
    "hard_blocker": 0,
    "negative_boundary": 1,
    "critical_condition": 2,
    "top_rank": 3,
}
_DECISION_CRITICAL_EFFECTS = frozenset(
    {"top_rank", "hard_blocker", "negative_boundary", "critical_condition"}
)
_LOCATED_EVIDENCE = frozenset({"full_text", "supporting_information"})


def _query_id(prefix: str, origin_ids: tuple[str, ...], text: str) -> str:
    material = "\x1f".join((prefix, *origin_ids, text))
    return f"Q-{prefix.upper()}-{hashlib.sha256(material.encode('utf-8')).hexdigest()[:16]}"


def _mechanism_terms(seed: SeedMechanism) -> tuple[str, ...]:
    """Return only the Seed fields permitted in pre-taxonomy search text."""

    groups = (
        seed.reaction_center,
        seed.electrophile_state,
        seed.nucleophile_state,
        seed.elementary_steps,
        seed.electronic_requirements,
        seed.competing_pathways,
        seed.catalyst_roles,
    )
    seen: set[str] = set()
    return tuple(
        term.strip()
        for group in groups
        for term in group
        if term.strip() and not (term.strip().casefold() in seen or seen.add(term.strip().casefold()))
    )


def build_seed_queries(
    seed: SeedMechanism, principles: Sequence[ReactionPrinciple]
) -> tuple[SearchQuery, ...]:
    """Build a Seed-driven query without copying candidate-family fields.

    Principle identifiers remain provenance only.  Their names, scopes, claims,
    and family fields are intentionally excluded from pre-taxonomy query text.
    """

    text = " ".join(_mechanism_terms(seed))
    if not text:
        raise LiteratureRetrievalError("Seed mechanism has no permitted retrieval features")
    origin_ids = (seed.seed_reaction_id, *tuple(principle.principle_id for principle in principles))
    return (
        SearchQuery(
            query_id=_query_id("seed", origin_ids, text),
            text=text,
            origin_type="seed_mechanism",
            origin_ids=origin_ids,
        ),
    )


def build_hypothesis_queries(families: Sequence[FamilyDefinition]) -> tuple[SearchQuery, ...]:
    """Build one post-taxonomy query per generated family definition."""

    queries: list[SearchQuery] = []
    for family in families:
        terms = (
            family.nucleophilic_center,
            family.reactive_state,
            family.bond_forming_mode,
            family.activation_mode,
            *family.critical_conditions,
            *family.dominant_failure_modes,
        )
        text = " ".join(term.strip() for term in terms if term.strip())
        queries.append(
            SearchQuery(
                query_id=_query_id("hypothesis", (family.family_id,), text),
                text=text,
                origin_type="taxonomy_hypothesis",
                origin_ids=(family.family_id,),
            )
        )
    return tuple(queries)


def query_inputs_for_audit(queries: Sequence[SearchQuery]) -> tuple[QueryInput, ...]:
    """Return every query field required by ``LeakagePolicy.query_inputs``."""

    query_ids = tuple(query.query_id for query in queries)
    if len(query_ids) != len(set(query_ids)):
        raise LiteratureRetrievalError("retrieval queries must have unique query IDs")
    return tuple(QueryInput(**query.model_dump()) for query in queries)


def _value(record: Mapping[str, object], key: str, *, required: bool = False) -> object | None:
    value = record.get(key)
    if required and value is None:
        raise LiteratureRetrievalError(f"record requires {key}")
    return value


def _string(record: Mapping[str, object], key: str, *, required: bool = False) -> str | None:
    value = _value(record, key, required=required)
    if value is None:
        return None
    if not isinstance(value, str):
        raise LiteratureRetrievalError(f"record {key} must be a string")
    return value.strip()


def _provider(record: Mapping[str, object]) -> Provider:
    raw = _string(record, "provider", required=True)
    assert raw is not None
    provider = _PROVIDER_ALIASES.get(raw.casefold().replace("-", " "))
    if provider is None:
        raise LiteratureRetrievalError("record provider is not supported")
    return provider  # type: ignore[return-value]


def _location(record: Mapping[str, object], abstract_available: bool) -> EvidenceLocation:
    raw = _string(record, "evidence_location") or _string(record, "access_level") or ""
    normalized = raw.casefold().replace(" ", "_")
    if normalized in _LOCATION_RANK:
        return normalized  # type: ignore[return-value]
    if normalized in {"open", "restricted", "unknown"}:
        return "abstract" if abstract_available else "metadata"
    if not raw:
        return "abstract" if abstract_available else "metadata"
    raise LiteratureRetrievalError("record evidence_location is not supported")


def _access_level(record: Mapping[str, object], location: EvidenceLocation) -> AccessLevel:
    raw = _string(record, "access_level")
    normalized = raw.casefold().replace(" ", "_") if raw else ""
    if normalized in {"metadata", "abstract", "open", "restricted", "unknown"}:
        return normalized  # type: ignore[return-value]
    if location in {"full_text", "supporting_information"}:
        return "open" if raw == "open" else "unknown"
    return location


def _normalized_doi(doi: str | None) -> str | None:
    if doi is None:
        return None
    normalized = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi.strip(), flags=re.I)
    normalized = re.sub(r"^doi:\s*", "", normalized, flags=re.I).rstrip(".").casefold()
    return normalized or None


def _deduplication_key(doi: str | None, title: str) -> str:
    if doi:
        return f"doi:{doi}"
    normalized_title = " ".join(re.findall(r"[a-z0-9]+", title.casefold()))
    if not normalized_title:
        raise LiteratureRetrievalError("record title cannot produce a deduplication key")
    return f"title:{normalized_title}"


def _record_id(deduplication_key: str) -> str:
    return "SR-" + deduplication_key.replace(":", "-").replace("/", "-")


def _normalize_one(query: SearchQuery, record: Mapping[str, object]) -> SearchRecord:
    abstract = _string(record, "abstract")
    abstract_available = bool(abstract)
    location = _location(record, abstract_available)
    doi = _normalized_doi(_string(record, "doi"))
    title = _string(record, "title", required=True)
    retrieved_at = _string(record, "retrieved_at", required=True)
    hit_count = _value(record, "hit_count", required=True)
    screening = _string(record, "screening_decision") or "pending"
    if not isinstance(hit_count, int) or isinstance(hit_count, bool) or hit_count < 0:
        raise LiteratureRetrievalError("record hit_count must be a non-negative integer")
    if screening not in {"pending", "include", "exclude", "uncertain"}:
        raise LiteratureRetrievalError("record screening_decision is not supported")
    assert title is not None and retrieved_at is not None
    deduplication_key = _deduplication_key(doi, title)
    return SearchRecord(
        record_id=_record_id(deduplication_key),
        provider=_provider(record),
        query_id=query.query_id,
        query_text=query.text,
        query_origin_type=query.origin_type,
        origin_ids=query.origin_ids,
        retrieved_at=retrieved_at,
        hit_count=hit_count,
        doi=doi,
        title=title,
        abstract=abstract,
        abstract_available=abstract_available,
        access_level=_access_level(record, location),
        evidence_location=location,
        deduplication_key=deduplication_key,
        screening_decision=screening,  # type: ignore[arg-type]
    )


def normalize_search_results(
    query: SearchQuery, records: Sequence[Mapping[str, object]]
) -> tuple[SearchRecord, ...]:
    """Normalize recorded provider fixtures and retain the strongest duplicate."""

    chosen: dict[str, SearchRecord] = {}
    for raw in records:
        normalized = _normalize_one(query, raw)
        existing = chosen.get(normalized.deduplication_key)
        if existing is None or _LOCATION_RANK[normalized.evidence_location] > _LOCATION_RANK[
            existing.evidence_location
        ]:
            chosen[normalized.deduplication_key] = normalized
    return tuple(chosen[key] for key in sorted(chosen))


def validate_evidence_decisions(
    records: Sequence[SearchRecord], decisions: Sequence[EvidenceDecision]
) -> dict[str, SearchRecord]:
    """Resolve decision evidence against the normalized record that contains it.

    ``EvidenceDecision.evidence_location`` is provenance supplied by a caller,
    not authority to establish a claim.  A decision can become decision-grade
    only when its referenced normalized record contains located text or SI.
    """

    records_by_id = {record.record_id: record for record in records}
    if len(records_by_id) != len(records):
        raise LiteratureRetrievalError("search records must have unique record IDs")
    for decision in decisions:
        record = records_by_id.get(decision.record_id)
        if record is None:
            raise LiteratureRetrievalError("evidence decision references an unknown search record")
        if decision.evidence_location != record.evidence_location:
            raise LiteratureRetrievalError(
                "decision evidence location contradicts normalized record "
                f"{record.evidence_location} evidence"
            )
        if (
            decision.establishes_decision
            and decision.material_effect in _DECISION_CRITICAL_EFFECTS
            and record.evidence_location not in _LOCATED_EVIDENCE
        ):
            raise LiteratureRetrievalError(
                "decision-critical claim requires a record with located full text "
                "or supporting information"
            )
    return records_by_id


def select_full_text_requests(
    records: Sequence[SearchRecord], decisions: Sequence[EvidenceDecision]
) -> tuple[FullTextRequest, ...]:
    """Request text only where it could upgrade a decision-critical claim."""

    records_by_id = validate_evidence_decisions(records, decisions)
    decisions_by_record: dict[str, list[EvidenceDecision]] = {}
    for decision in decisions:
        if decision.material_effect == "screening":
            continue
        decisions_by_record.setdefault(decision.record_id, []).append(decision)

    requests: list[FullTextRequest] = []
    for record in records:
        material_decisions = decisions_by_record.get(record.record_id, [])
        if not material_decisions or record.evidence_location in _LOCATED_EVIDENCE:
            continue
        material_decisions.sort(key=lambda decision: _REQUEST_PRIORITY[decision.material_effect])
        leading = material_decisions[0]
        reason = _REQUEST_REASON[leading.material_effect]
        request_material = "\x1f".join(
            (record.record_id, reason, *sorted(decision.decision_id for decision in material_decisions))
        )
        requests.append(
            FullTextRequest(
                request_id="FTR-" + hashlib.sha256(request_material.encode("utf-8")).hexdigest()[:16],
                record_id=record.record_id,
                deduplication_key=record.deduplication_key,
                title=record.title,
                doi=record.doi,
                reason=reason,  # type: ignore[arg-type]
                decision_ids=tuple(sorted(decision.decision_id for decision in material_decisions)),
            )
        )
    return tuple(requests)

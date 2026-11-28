"""Post-Freeze-3 reveal, mapping, and validation readiness for v3."""

from __future__ import annotations

import hashlib
import json
import math
import unicodedata
import weakref
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

from pydantic import Field, field_serializer, model_validator

import pipeline.v3_freeze as freeze_module
from pipeline.diagnostic_design import FamilyDiagnosticPlan, MechanisticConditionState
from pipeline.family_canonicalization import CanonicalTaxonomy
from pipeline.leakage_audit import LeakagePolicy, StructureFingerprintFactory
from pipeline.principle_models import FrozenStrictModel
from pipeline.ranking_robustness import RankingAnalysis
from pipeline.sealed_registry import (
    RevealGateError,
    RevealedConditionState,
    RevealedMechanisticDefinition,
    authorize_registry_reveal,
    reveal_registry,
)
from pipeline.validation_study import (
    MetricAvailability,
    MetricValue,
    ProspectiveBoundaryStratum,
    ValidationGateError,
    ValidationReadiness,
)


_CONDITION_FIELDS = (
    "protonation_state",
    "catalyst_state",
    "medium_state",
    "temperature_state",
    "concentration_state",
    "atmosphere_state",
    "time_state",
)
_MATRIX_STRATA = (
    "priority_a",
    "priority_b",
    "priority_c",
    "boundary",
    "negative_control",
)


def _stable_digest(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _normalized(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


class RevealedSuccessRecord(FrozenStrictModel):
    record_id: str = Field(min_length=1)
    structure_hashes: tuple[str, ...] = Field(min_length=1)
    mechanistic_definition: RevealedMechanisticDefinition
    conditions: RevealedConditionState | None
    evidence_ids: tuple[str, ...] = Field(min_length=1)


class FrozenFamilyReference(FrozenStrictModel):
    family_id: str = Field(min_length=1)
    structure_hashes: tuple[str, ...]
    mechanistic_definition: RevealedMechanisticDefinition
    conditions: tuple[RevealedConditionState, ...]
    primary_rank: int | None = Field(default=None, ge=1)
    testability: Literal["testable", "non_testable"] = "testable"
    structure_fingerprint_factory_id: str | None = None
    structure_canonicalizer_id: str | None = None
    structure_canonicalizer_spec: str | None = None
    structure_canonicalizer_version: str | None = None
    structure_engine_version: str | None = None
    structure_dependency_identity: str | None = None
    structure_canonicalization_parameter_digest: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    structure_factory_implementation_digest: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    structure_factory_key_commitment: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )

    @model_validator(mode="after")
    def require_complete_structure_factory_identity(self) -> "FrozenFamilyReference":
        identity = (
            self.structure_fingerprint_factory_id,
            self.structure_canonicalizer_id,
            self.structure_canonicalizer_spec,
            self.structure_canonicalizer_version,
            self.structure_engine_version,
            self.structure_dependency_identity,
            self.structure_canonicalization_parameter_digest,
            self.structure_factory_implementation_digest,
            self.structure_factory_key_commitment,
        )
        if any(value is not None for value in identity) and any(
            value is None for value in identity
        ):
            raise ValueError("frozen family structure factory identity is incomplete")
        if self.testability == "testable" and not self.structure_hashes:
            raise ValueError("testable frozen family requires a structural reference")
        if self.testability == "non_testable" and self.structure_hashes:
            raise ValueError("non-testable frozen family cannot claim structural references")
        if self.testability == "non_testable" and self.primary_rank is not None:
            raise ValueError("non-testable frozen family cannot claim a primary rank")
        return self


class FamilyMappingAdjudication(FrozenStrictModel):
    record_id: str
    record_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["matched", "unmapped", "mechanistic_mismatch"]
    mapped_family_id: str | None
    structure_candidate_ids: tuple[str, ...]
    mechanism_candidate_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    rationale: str


class AvailabilityMean(FrozenStrictModel):
    total_revealed: int = Field(ge=0)
    available_count: int = Field(ge=0)
    values: tuple[float, ...]
    value: float | None

    @model_validator(mode="after")
    def validate_availability(self) -> "AvailabilityMean":
        if self.available_count != len(self.values):
            raise ValueError("available count must match metric values")
        if self.available_count > self.total_revealed:
            raise ValueError("available count cannot exceed revealed count")
        if (self.available_count == 0) != (self.value is None):
            raise ValueError("unavailable aggregate must have a null value")
        return self


class RetrospectiveValidationV3(FrozenStrictModel):
    revealed_registry_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    trusted_freeze_three_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    family_recall: MetricValue
    top_k_recall: Mapping[str, MetricValue]
    normalized_rank: AvailabilityMean
    mechanistic_match: MetricValue
    mechanistic_match_adjudications: tuple[FamilyMappingAdjudication, ...]
    condition_proximity: AvailabilityMean
    metric_unit: Literal[
        "unique_canonical_structure_mechanism_outcome"
    ] = "unique_canonical_structure_mechanism_outcome"
    final_leakage_status: Literal["passed"]
    failure_discrimination_metrics: MetricAvailability
    fixed_scope: Literal["SR001_nucleophile_condition"] = "SR001_nucleophile_condition"
    electrophile_expansion_blocked: bool = True

    @model_validator(mode="after")
    def freeze_top_k(self) -> "RetrospectiveValidationV3":
        required = {"top_5", "top_10", "top_20_percent"}
        if set(self.top_k_recall) != required:
            raise ValueError("top-k recall requires the preregistered thresholds")
        object.__setattr__(self, "top_k_recall", MappingProxyType(dict(self.top_k_recall)))
        return self

    @field_serializer("top_k_recall")
    def serialize_top_k(self, value: Mapping[str, MetricValue]) -> dict[str, object]:
        return {key: metric.model_dump(mode="json") for key, metric in value.items()}


class HistoricalNegativeEvidence(FrozenStrictModel):
    evidence_id: str = Field(min_length=1)
    record_id: str = Field(min_length=1)
    matrix_stratum: Literal[
        "priority_a",
        "priority_b",
        "priority_c",
        "boundary",
        "negative_control",
    ]
    subject_chemistry_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    outcome: Literal["confirmed_failure", "off_target"]
    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_locator: str = Field(min_length=1)


class HistoricalNegativeEvidenceBinding(FrozenStrictModel):
    evidence_id: str = Field(min_length=1)
    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_locator: str = Field(min_length=1)


class HistoricalNegativeResolutionReceipt(FrozenStrictModel):
    record_id: str = Field(min_length=1)
    matrix_stratum: Literal[
        "priority_a",
        "priority_b",
        "priority_c",
        "boundary",
        "negative_control",
    ]
    subject_chemistry_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    outcome: Literal["confirmed_failure", "off_target"]
    resolver_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_bindings: tuple[HistoricalNegativeEvidenceBinding, ...] = Field(
        min_length=1
    )
    receipt_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


_NEGATIVE_RESOLVER_TOKEN = object()
_NEGATIVE_RESOLVER_ATTESTATIONS: dict[
    int, tuple[weakref.ReferenceType[object], str, str]
] = {}


class HistoricalNegativeEvidenceResolver(FrozenStrictModel):
    evidence: tuple[HistoricalNegativeEvidence, ...] = Field(min_length=1)
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    def __init__(self, **data: Any) -> None:
        token = data.pop("_builder_token", None)
        if token is not _NEGATIVE_RESOLVER_TOKEN:
            raise ValueError(
                "historical negative evidence resolver requires factory attestation"
            )
        super().__init__(**data)


def _negative_resolver_digest(
    evidence: Sequence[HistoricalNegativeEvidence],
) -> str:
    return _stable_digest(
        [
            item.model_dump(mode="json")
            for item in sorted(evidence, key=lambda row: row.evidence_id)
        ]
    )


def build_historical_negative_evidence_resolver(
    evidence: Sequence[HistoricalNegativeEvidence],
) -> HistoricalNegativeEvidenceResolver:
    """Attest the authoritative evidence set used to resolve negative claims."""

    rows = tuple(sorted(evidence, key=lambda row: row.evidence_id))
    if len({row.evidence_id for row in rows}) != len(rows):
        raise ValueError("duplicate historical negative evidence ID")
    source_identities = {
        (row.source_digest, row.source_locator)
        for row in rows
    }
    if len(source_identities) != len(rows):
        raise ValueError("duplicate authoritative source identity")
    resolver = HistoricalNegativeEvidenceResolver(
        _builder_token=_NEGATIVE_RESOLVER_TOKEN,
        evidence=rows,
        content_digest=_negative_resolver_digest(rows),
    )
    resolver_id = id(resolver)

    def discard(_: weakref.ReferenceType[object]) -> None:
        _NEGATIVE_RESOLVER_ATTESTATIONS.pop(resolver_id, None)

    _NEGATIVE_RESOLVER_ATTESTATIONS[resolver_id] = (
        weakref.ref(resolver, discard),
        resolver.content_digest,
        _negative_resolver_digest(resolver.evidence),
    )
    return resolver


def _verify_negative_evidence_resolver(
    resolver: HistoricalNegativeEvidenceResolver,
) -> HistoricalNegativeEvidenceResolver:
    attestation = _NEGATIVE_RESOLVER_ATTESTATIONS.get(id(resolver))
    digest = _negative_resolver_digest(resolver.evidence)
    if (
        type(resolver) is not HistoricalNegativeEvidenceResolver
        or attestation is None
        or attestation[0]() is not resolver
        or attestation[1] != resolver.content_digest
        or attestation[2] != digest
        or resolver.content_digest != digest
        or len({item.evidence_id for item in resolver.evidence})
        != len(resolver.evidence)
    ):
        raise ValueError("historical negative evidence resolver attestation failed")
    return resolver


class HistoricalNegativeRecord(FrozenStrictModel):
    record_id: str = Field(min_length=1)
    matrix_stratum: Literal[
        "priority_a",
        "priority_b",
        "priority_c",
        "boundary",
        "negative_control",
    ]
    outcome: Literal["confirmed_failure", "off_target", "unknown"]
    subject_chemistry_digest: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    evidence_ids: tuple[str, ...]
    evidence_basis: Literal[
        "traceable_experiment", "traceable_literature", "model_inference"
    ]
    resolution_receipt: HistoricalNegativeResolutionReceipt | None = None

    @model_validator(mode="after")
    def reject_inferred_or_unsupported_negatives(self) -> "HistoricalNegativeRecord":
        if self.evidence_basis == "model_inference" and self.outcome != "unknown":
            raise ValueError("model inference cannot establish a negative outcome")
        if self.outcome != "unknown" and not self.evidence_ids:
            raise ValueError("negative outcome requires traceable evidence")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("negative evidence IDs must be unique")
        return self


def _negative_resolution_receipt(
    record: HistoricalNegativeRecord,
    resolver: HistoricalNegativeEvidenceResolver,
) -> HistoricalNegativeResolutionReceipt:
    evidence_by_id = {item.evidence_id: item for item in resolver.evidence}
    try:
        evidence = tuple(evidence_by_id[item] for item in sorted(record.evidence_ids))
    except KeyError as exc:
        raise ValueError("historical negative evidence ID is unresolved") from exc
    if record.outcome == "unknown" or any(
        item.outcome != record.outcome for item in evidence
    ):
        raise ValueError("historical negative outcome disagrees with source evidence")
    if record.subject_chemistry_digest is None:
        raise ValueError("resolved historical negative requires subject chemistry")
    if any(item.record_id != record.record_id for item in evidence):
        raise ValueError("historical negative evidence record subject mismatch")
    if any(item.matrix_stratum != record.matrix_stratum for item in evidence):
        raise ValueError("historical negative evidence matrix stratum mismatch")
    if any(
        item.subject_chemistry_digest != record.subject_chemistry_digest
        for item in evidence
    ):
        raise ValueError("historical negative evidence subject chemistry mismatch")
    bindings = tuple(
        HistoricalNegativeEvidenceBinding(
            evidence_id=item.evidence_id,
            source_digest=item.source_digest,
            source_locator=item.source_locator,
        )
        for item in evidence
    )
    material = {
        "record_id": record.record_id,
        "matrix_stratum": record.matrix_stratum,
        "subject_chemistry_digest": record.subject_chemistry_digest,
        "outcome": record.outcome,
        "resolver_digest": resolver.content_digest,
        "evidence_bindings": [item.model_dump(mode="json") for item in bindings],
    }
    return HistoricalNegativeResolutionReceipt(
        **material,
        receipt_digest=_stable_digest(material),
    )


def resolve_historical_negative_record(
    record: HistoricalNegativeRecord,
    resolver: HistoricalNegativeEvidenceResolver,
) -> HistoricalNegativeRecord:
    """Attach a source-bound receipt from an attested authoritative resolver."""

    _verify_negative_evidence_resolver(resolver)
    if record.evidence_basis == "model_inference":
        raise ValueError("model inference cannot establish a negative outcome")
    receipt = _negative_resolution_receipt(record, resolver)
    return record.model_copy(update={"resolution_receipt": receipt})


def _verify_negative_resolution(
    record: HistoricalNegativeRecord,
    resolver: HistoricalNegativeEvidenceResolver,
) -> bool:
    receipt = record.resolution_receipt
    if receipt is None:
        return False
    try:
        expected = _negative_resolution_receipt(
            record.model_copy(update={"resolution_receipt": None}), resolver
        )
    except ValueError as exc:
        raise ValidationGateError(
            "historical negative resolution receipt is invalid"
        ) from exc
    if receipt != expected:
        raise ValidationGateError(
            "historical negative resolution receipt is invalid"
        )
    return True


def historical_negative_registry_digest(
    records: Sequence[HistoricalNegativeRecord],
) -> str:
    rows = tuple(records)
    if len({row.record_id for row in rows}) != len(rows):
        raise ValidationGateError("duplicate historical negative record ID")
    return _stable_digest(
        [row.model_dump(mode="json") for row in sorted(rows, key=lambda item: item.record_id)]
    )


def _mechanism_key(definition: RevealedMechanisticDefinition) -> tuple[str, ...]:
    return (
        _normalized(definition.nucleophilic_center),
        _normalized(definition.reactive_state),
        _normalized(definition.bond_forming_mode),
        _normalized(definition.activation_mode),
    )


def map_revealed_successes(
    records: Sequence[RevealedSuccessRecord],
    families: Sequence[FrozenFamilyReference],
) -> tuple[FamilyMappingAdjudication, ...]:
    """Map by structural fingerprint and exact mechanism, never by registry terms."""

    family_rows = tuple(families)
    if len({row.family_id for row in family_rows}) != len(family_rows):
        raise ValidationGateError("duplicate frozen family reference")
    adjudications: list[FamilyMappingAdjudication] = []
    for record in records:
        structures = set(record.structure_hashes)
        structure_candidates = tuple(
            family for family in family_rows if structures.intersection(family.structure_hashes)
        )
        mechanism_candidates = tuple(
            family
            for family in family_rows
            if _mechanism_key(record.mechanistic_definition)
            == _mechanism_key(family.mechanistic_definition)
        )
        matched = tuple(
            family for family in structure_candidates if family in mechanism_candidates
        )
        if len(matched) > 1:
            raise ValidationGateError(
                f"ambiguous structure mapping for revealed record {record.record_id}"
            )
        if len(matched) == 1:
            status = "matched"
            mapped_family_id = matched[0].family_id
            rationale = "Structure fingerprint and frozen mechanistic definition agree."
        elif structure_candidates:
            status = "mechanistic_mismatch"
            mapped_family_id = None
            rationale = "Structure evidence does not agree with the frozen mechanism."
        else:
            status = "unmapped"
            mapped_family_id = None
            rationale = "No frozen structural fingerprint matches the revealed record."
        adjudications.append(
            FamilyMappingAdjudication(
                record_id=record.record_id,
                record_digest=_stable_digest(record.model_dump(mode="json")),
                status=status,
                mapped_family_id=mapped_family_id,
                structure_candidate_ids=tuple(
                    sorted(family.family_id for family in structure_candidates)
                ),
                mechanism_candidate_ids=tuple(
                    sorted(family.family_id for family in mechanism_candidates)
                ),
                evidence_ids=record.evidence_ids,
                rationale=rationale,
            )
        )
    return tuple(adjudications)


def _condition_from_plan(condition: MechanisticConditionState) -> RevealedConditionState:
    return RevealedConditionState(
        **{field: getattr(condition, field) for field in _CONDITION_FIELDS}
    )


def _frozen_family_references(
    taxonomy: CanonicalTaxonomy,
    ranking: RankingAnalysis,
    diagnostics: Sequence[FamilyDiagnosticPlan],
    structure_factory: StructureFingerprintFactory,
) -> tuple[FrozenFamilyReference, ...]:
    plans = tuple(diagnostics)
    taxonomy_ids = tuple(family.family_id for family in taxonomy.families)
    rank_by_family = {record.family_id: record for record in ranking.records}
    plan_by_family = {plan.family_id: plan for plan in plans}
    if len(rank_by_family) != len(ranking.records) or set(rank_by_family) != set(taxonomy_ids):
        raise ValidationGateError("frozen taxonomy/ranking family mismatch")
    if len(plan_by_family) != len(plans) or set(plan_by_family) != set(taxonomy_ids):
        raise ValidationGateError("frozen taxonomy/diagnostic family mismatch")
    references: list[FrozenFamilyReference] = []
    for family in taxonomy.families:
        plan = plan_by_family[family.family_id]
        ranking_record = rank_by_family[family.family_id]
        structures = tuple(sorted({item.structural_fingerprint for item in plan.representatives}))
        if not structures and ranking_record.priority_region not in {
            "excluded",
            "unknown",
        }:
            raise ValidationGateError(
                f"frozen family {family.family_id} has no structural reference"
            )
        references.append(
            FrozenFamilyReference(
                family_id=family.family_id,
                structure_hashes=structures,
                mechanistic_definition=RevealedMechanisticDefinition(
                    nucleophilic_center=family.nucleophilic_center,
                    reactive_state=family.reactive_state,
                    bond_forming_mode=family.bond_forming_mode,
                    activation_mode=family.activation_mode,
                ),
                conditions=tuple(_condition_from_plan(item) for item in plan.conditions),
                primary_rank=ranking_record.primary_rank,
                testability="testable" if structures else "non_testable",
                structure_fingerprint_factory_id=structure_factory.factory_id,
                structure_canonicalizer_id=structure_factory.canonicalizer_id,
                structure_canonicalizer_spec=structure_factory.canonicalizer_spec,
                structure_canonicalizer_version=(
                    structure_factory.canonicalizer_version
                ),
                structure_engine_version=structure_factory.engine_version,
                structure_dependency_identity=structure_factory.dependency_identity,
                structure_canonicalization_parameter_digest=(
                    structure_factory.canonicalization_parameter_digest
                ),
                structure_factory_implementation_digest=(
                    structure_factory.implementation_digest
                ),
                structure_factory_key_commitment=structure_factory.key_commitment,
            )
        )
    return tuple(references)


def _require_frozen_artifacts(
    root: Path,
    trusted_digest: str,
    taxonomy: CanonicalTaxonomy,
    ranking: RankingAnalysis,
    diagnostics: Sequence[FamilyDiagnosticPlan],
) -> None:
    try:
        _, roles, _ = freeze_module._verify_prefix(root, 3, trusted_digest)
        frozen_taxonomy = freeze_module._json_from_snapshot(
            roles["Freeze 2"]["taxonomy"], "Freeze 2 taxonomy"
        )
        frozen_ranking = freeze_module._json_from_snapshot(
            roles["Freeze 3"]["ranking"], "Freeze 3 ranking"
        )
        frozen_diagnostics = freeze_module._json_array_from_snapshot(
            roles["Freeze 3"]["diagnostics"], "Freeze 3 diagnostics"
        )
    except (freeze_module.V3FreezeError, ValueError, TypeError) as exc:
        raise ValidationGateError("trusted Freeze 3 artifacts are unavailable") from exc
    if type(taxonomy) is not CanonicalTaxonomy or taxonomy.model_dump(mode="json") != frozen_taxonomy:
        raise ValidationGateError("taxonomy does not match the frozen artifact")
    if type(ranking) is not RankingAnalysis or ranking.model_dump(mode="json") != frozen_ranking:
        raise ValidationGateError("ranking does not match the frozen artifact")
    if any(type(plan) is not FamilyDiagnosticPlan for plan in diagnostics) or [
        plan.model_dump(mode="json") for plan in diagnostics
    ] != list(frozen_diagnostics):
        raise ValidationGateError("diagnostics do not match the frozen artifact")


def _metric(numerator: int, denominator: int) -> MetricValue:
    return MetricValue(
        numerator=float(numerator),
        denominator=float(denominator),
        value=numerator / denominator if denominator else None,
    )


def _availability_mean(values: Sequence[float], total: int) -> AvailabilityMean:
    rows = tuple(values)
    return AvailabilityMean(
        total_revealed=total,
        available_count=len(rows),
        values=rows,
        value=sum(rows) / len(rows) if rows else None,
    )


def _condition_proximity(
    disclosed: RevealedConditionState | None,
    frozen: Sequence[RevealedConditionState],
) -> float | None:
    if disclosed is None or not frozen:
        return None
    return max(
        sum(
            _normalized(getattr(disclosed, field))
            == _normalized(getattr(candidate, field))
            for field in _CONDITION_FIELDS
        )
        / len(_CONDITION_FIELDS)
        for candidate in frozen
    )


def _require_unique_chemistry_units(
    records: Sequence[RevealedSuccessRecord],
) -> tuple[RevealedSuccessRecord, ...]:
    rows = tuple(records)
    if any(len(record.structure_hashes) != 1 for record in rows):
        raise ValidationGateError(
            "each disclosed metric record requires exactly one canonical structure; "
            "duplicate canonical chemistry units are not admissible"
        )
    units: dict[tuple[str, tuple[str, ...], str], str] = {}
    for record in rows:
        mechanism = _mechanism_key(record.mechanistic_definition)
        for structure_hash in set(record.structure_hashes):
            unit = (structure_hash, mechanism, "disclosed_success")
            previous = units.get(unit)
            if previous is not None and previous != record.record_id:
                raise ValidationGateError(
                    "duplicate canonical chemistry metric unit across distinct record IDs"
                )
            units[unit] = record.record_id
    return rows


def evaluate_retrospective_reveal(
    root: Path,
    registry_path: Path,
    taxonomy: CanonicalTaxonomy,
    ranking: RankingAnalysis,
    diagnostics: Sequence[FamilyDiagnosticPlan],
    *,
    trusted_freeze_three_digest: str,
    leakage_policy: LeakagePolicy,
    registry_salt: bytes,
    reveal_decision: Literal["reveal"] | None,
    expected_structure_factory: StructureFingerprintFactory | None = None,
) -> RetrospectiveValidationV3:
    """Reveal committed successes and compute only retrospective v3 metrics."""

    try:
        authorization = authorize_registry_reveal(
            root,
            trusted_freeze_three_digest,
            leakage_policy,
            registry_salt,
            reveal_decision,
            expected_structure_factory,
        )
        registry = reveal_registry(registry_path, authorization)
    except RevealGateError as exc:
        raise ValidationGateError(str(exc)) from exc
    _require_frozen_artifacts(root, trusted_freeze_three_digest, taxonomy, ranking, diagnostics)
    if expected_structure_factory is None:
        raise ValidationGateError("trusted structure fingerprint factory is unavailable")
    references = _frozen_family_references(
        taxonomy, ranking, diagnostics, expected_structure_factory
    )
    declared_successes = tuple(
        record for record in registry.records if record.outcome == "disclosed_success"
    )
    disclosed = _require_unique_chemistry_units(tuple(
        RevealedSuccessRecord(
            record_id=record.record_id,
            structure_hashes=record.structure_hashes,
            mechanistic_definition=record.mechanistic_definition,
            conditions=record.conditions,
            evidence_ids=record.evidence_ids,
        )
        for record in declared_successes
        if record.mechanistic_definition is not None and record.structure_hashes
    ))
    if len(disclosed) != len(declared_successes):
        raise ValidationGateError("disclosed success requires structures and a mechanistic definition")
    if not disclosed:
        raise ValidationGateError("revealed registry contains no disclosed successes")
    adjudications = map_revealed_successes(disclosed, references)
    reference_by_id = {reference.family_id: reference for reference in references}
    total = len(disclosed)
    matched = tuple(item for item in adjudications if item.status == "matched")
    ranked_family_count = sum(reference.primary_rank is not None for reference in references)
    top_20_cutoff = max(1, math.ceil(ranked_family_count * 0.2))

    def top_count(cutoff: int) -> int:
        return sum(
            reference_by_id[item.mapped_family_id].primary_rank is not None
            and reference_by_id[item.mapped_family_id].primary_rank <= cutoff
            for item in matched
            if item.mapped_family_id is not None
        )

    normalized_ranks = tuple(
        reference.primary_rank / ranked_family_count
        for item in matched
        if item.mapped_family_id is not None
        and (reference := reference_by_id[item.mapped_family_id]).primary_rank is not None
        and ranked_family_count
    )
    record_by_id = {record.record_id: record for record in disclosed}
    proximities = tuple(
        proximity
        for item in matched
        if item.mapped_family_id is not None
        and (
            proximity := _condition_proximity(
                record_by_id[item.record_id].conditions,
                reference_by_id[item.mapped_family_id].conditions,
            )
        ) is not None
    )
    return RetrospectiveValidationV3(
        revealed_registry_digest=_stable_digest(registry.model_dump(mode="json")),
        trusted_freeze_three_digest=trusted_freeze_three_digest,
        family_recall=_metric(len(matched), total),
        top_k_recall={
            "top_5": _metric(top_count(5), total),
            "top_10": _metric(top_count(10), total),
            "top_20_percent": _metric(top_count(top_20_cutoff), total),
        },
        normalized_rank=_availability_mean(normalized_ranks, total),
        mechanistic_match=_metric(len(matched), total),
        mechanistic_match_adjudications=adjudications,
        condition_proximity=_availability_mean(proximities, total),
        final_leakage_status="passed",
        failure_discrimination_metrics=MetricAvailability(
            status="unavailable",
            value=None,
            reason="Retrospective disclosed-success metrics exclude failure discrimination.",
        ),
    )


def _verify_readiness_freeze(root: Path, trusted_digest: str, policy: LeakagePolicy) -> None:
    verification = freeze_module.verify_freeze_chain(root, trusted_digest, policy)
    if (
        not verification.valid
        or verification.verified_stages != ("Freeze 1", "Freeze 2", "Freeze 3")
        or verification.manifest_digests.get("Freeze 3") != trusted_digest
    ):
        raise ValidationGateError("trusted Freeze 3 chain verification failed")


def build_validation_readiness(
    root: Path,
    *,
    historical_negatives: Sequence[HistoricalNegativeRecord],
    trusted_freeze_three_digest: str,
    leakage_policy: LeakagePolicy,
    trusted_historical_negative_digest: str | None = None,
    negative_evidence_resolver: HistoricalNegativeEvidenceResolver | None = None,
    trusted_negative_evidence_resolver_digest: str | None = None,
) -> ValidationReadiness:
    """Report negative-history availability without blocking construction or reveal."""

    _verify_readiness_freeze(root, trusted_freeze_three_digest, leakage_policy)
    negatives = tuple(historical_negatives)
    digest = None
    if negatives:
        digest = historical_negative_registry_digest(negatives)
        if digest != trusted_historical_negative_digest:
            raise ValidationGateError("historical negative registry does not match its trusted digest")
    if (negative_evidence_resolver is None) != (
        trusted_negative_evidence_resolver_digest is None
    ):
        raise ValidationGateError(
            "historical negative evidence resolver requires an independent trusted digest"
        )
    resolved = ()
    if negative_evidence_resolver is not None:
        try:
            resolver = _verify_negative_evidence_resolver(negative_evidence_resolver)
        except ValueError as exc:
            raise ValidationGateError(str(exc)) from exc
        if resolver.content_digest != trusted_negative_evidence_resolver_digest:
            raise ValidationGateError(
                "historical negative evidence resolver does not match its trusted digest"
            )
        resolved = tuple(
            record
            for record in negatives
            if _verify_negative_resolution(record, resolver)
        )
    confirmed_strata = {
        record.matrix_stratum
        for record in resolved
        if record.outcome in {"confirmed_failure", "off_target"}
        and record.evidence_basis != "model_inference"
    }
    if not negatives:
        status = "missing"
        reason = "Historical negative records are absent; failure discrimination is unknown."
    elif confirmed_strata != set(_MATRIX_STRATA):
        status = "insufficient"
        reason = (
            "Historical negatives do not cover every preregistered boundary stratum; "
            "failure discrimination is unknown."
        )
    else:
        status = "sufficient"
        reason = None
    unavailable = status != "sufficient"
    return ValidationReadiness(
        historical_negative_status=status,
        historical_negative_record_count=len(negatives),
        resolved_negative_record_count=len(resolved),
        historical_negative_digest=digest,
        failure_discrimination_metrics=MetricAvailability(
            status="unavailable" if unavailable else "available",
            value=None,
            reason=reason,
        ),
        prospective_boundary_matrix_required=unavailable,
        prospective_boundary_matrix=tuple(
            ProspectiveBoundaryStratum(stratum=stratum) for stratum in _MATRIX_STRATA
        ),
        negative_record_reminder=(
            reason
            or "Traceable historical negatives cover the preregistered strata; "
            "compute failure metrics separately from disclosed-success metrics."
        ),
    )

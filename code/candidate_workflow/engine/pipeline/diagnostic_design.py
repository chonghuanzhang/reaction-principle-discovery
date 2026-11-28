"""Attested family-level representative and diagnostic experiment design."""

from __future__ import annotations

import hashlib
import json
import weakref
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any, Literal

from pydantic import Field, field_serializer, model_validator

from pipeline.family_canonicalization import CanonicalFamily
from pipeline.family_evaluation import (
    EvaluationRubric,
    EvidenceQualificationError,
    QualifiedEvidenceRecord,
    ReviewedPrincipleLink,
    ScoredFamilyEvaluation,
    load_evaluation_rubric,
    verify_scored_family_evaluation,
)
from pipeline.principle_models import FrozenStrictModel, ReactionPrinciple
from pipeline.leakage_audit import (
    StructureFingerprintFactory,
    StructureFingerprintReceipt,
    derive_structure_fingerprint_receipt,
    verify_structure_fingerprint_receipt,
)
from pipeline.ranking_robustness import (
    RankingAnalysis,
    RankingAnalysisError,
    RobustnessRankingRecord,
    verify_ranking_analysis,
)
from pipeline.v3_models import PriorityRegion


PlanRole = Literal["diagnostic", "negative_control", "no_experiment", "evidence_first"]
AvailabilityState = Literal[
    "verified_available", "needs_verification", "unavailable"
]
HandlingStatus = Literal["cleared", "uncleared"]
ExpectedOutcome = Literal[
    "target_product_present", "target_product_absent", "not_applicable", "unresolved"
]
OperationalActionType = Literal[
    "verify_availability",
    "replace_unavailable",
    "clear_handling_prerequisite",
    "reclassify_boundary",
]
PreChemistryActionType = Literal["evidence_acquisition", "source_revisit"]
_MECHANISTIC_COORDINATES = (
    "nucleophilic_center",
    "reactive_state",
    "bond_forming_mode",
    "activation_mode",
)


class DiagnosticDesignError(RuntimeError):
    """Raised when a diagnostic design violates a trusted v3 contract."""


def _stable_digest(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _principle_digest(principle: ReactionPrinciple) -> str:
    return _stable_digest(principle.model_dump(mode="json"))


def _state_fingerprint(reactive_state: str) -> str:
    return hashlib.sha256(reactive_state.strip().casefold().encode()).hexdigest()


class HandlingPrerequisite(FrozenStrictModel):
    prerequisite_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    status: HandlingStatus


class ProposedRepresentativeState(FrozenStrictModel):
    """Qualitative model proposal; deterministic code validates and selects it."""

    state_id: str = Field(min_length=1)
    reactive_state: str = Field(min_length=1)
    mechanistic_coordinate_coverage: tuple[str, ...] = Field(min_length=1)
    diagnostic_contrasts: tuple[str, ...] = Field(min_length=1)
    structural_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    cluster_key: str = Field(min_length=1)
    availability_state: AvailabilityState
    handling_prerequisites: tuple[HandlingPrerequisite, ...] = Field(min_length=1)
    inventory_record_id: str | None = None
    inventory_content_digest: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )

    @model_validator(mode="after")
    def normalize_metric_sets(self) -> "ProposedRepresentativeState":
        if len(set(self.mechanistic_coordinate_coverage)) != len(
            self.mechanistic_coordinate_coverage
        ):
            raise ValueError("mechanistic coordinate coverage must be unique")
        if len(set(self.diagnostic_contrasts)) != len(self.diagnostic_contrasts):
            raise ValueError("diagnostic contrasts must be unique")
        return self


class MechanisticConditionState(FrozenStrictModel):
    state_id: str = Field(min_length=1)
    protonation_state: str = Field(min_length=1)
    catalyst_state: str = Field(min_length=1)
    medium_state: str = Field(min_length=1)
    temperature_state: str = Field(min_length=1)
    concentration_state: str = Field(min_length=1)
    atmosphere_state: str = Field(min_length=1)
    time_state: str = Field(min_length=1)


class DiagnosticDesignProposal(FrozenStrictModel):
    """Allowlisted model output with no classification, rank, score, or freeze."""

    family_id: str = Field(min_length=1)
    representative_states: tuple[ProposedRepresentativeState, ...] = Field(
        min_length=1, max_length=12
    )
    condition_states: tuple[MechanisticConditionState, ...] = Field(max_length=2)


class RepresentativeReagent(FrozenStrictModel):
    representative_id: str = Field(min_length=1)
    state_id: str = Field(min_length=1)
    reactive_state: str = Field(min_length=1)
    mechanistic_coordinate_coverage: tuple[str, ...] = Field(min_length=1)
    diagnostic_contrasts: tuple[str, ...] = Field(min_length=1)
    structural_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    cluster_key: str = Field(min_length=1)
    availability_state: AvailabilityState
    handling_prerequisites: tuple[HandlingPrerequisite, ...] = Field(min_length=1)
    readiness_record_id: str | None = None
    readiness_content_digest: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    readiness_inventory_artifact_digest: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    readiness_handling_artifact_digest: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    inventory_record_id: str = Field(min_length=1)
    inventory_content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    mechanistic_representativeness: str = Field(min_length=1)
    diagnostic_value: str = Field(min_length=1)
    evidence_ids: tuple[str, ...]

    @model_validator(mode="after")
    def require_exact_readiness_commitment(self) -> "RepresentativeReagent":
        commitments = (
            self.readiness_record_id,
            self.readiness_content_digest,
            self.readiness_inventory_artifact_digest,
            self.readiness_handling_artifact_digest,
        )
        if (self.availability_state == "verified_available") != all(commitments):
            raise DiagnosticDesignError(
                "verified representative requires an exact readiness commitment"
            )
        if any(commitments) and not all(commitments):
            raise DiagnosticDesignError(
                "representative readiness commitment must be complete"
            )
        return self


_CONDITION_FACTOR_FIELDS = (
    "protonation_state",
    "catalyst_state",
    "medium_state",
    "temperature_state",
    "concentration_state",
    "atmosphere_state",
    "time_state",
)


def _single_changed_factor(
    baseline: MechanisticConditionState,
    comparison: MechanisticConditionState,
) -> tuple[str]:
    changed = tuple(
        field
        for field in _CONDITION_FACTOR_FIELDS
        if getattr(baseline, field) != getattr(comparison, field)
    )
    if len(changed) != 1:
        raise DiagnosticDesignError(
            "paired control must prove exactly one mechanistic factor changed"
        )
    return (changed[0],)


class PairedControl(FrozenStrictModel):
    control_id: str = Field(min_length=1)
    baseline: MechanisticConditionState
    comparison: MechanisticConditionState
    changed_fields: tuple[str, ...] = Field(min_length=1, max_length=1)
    mechanistic_question: str = Field(min_length=1)

    @model_validator(mode="after")
    def prove_exactly_one_factor_changed(self) -> "PairedControl":
        if self.changed_fields != _single_changed_factor(
            self.baseline, self.comparison
        ):
            raise DiagnosticDesignError(
                "paired control must prove exactly one mechanistic factor changed"
            )
        return self


class DiagnosticAnalytics(FrozenStrictModel):
    required_target_analyte: str
    target_product_methods: tuple[str, ...]
    target_product_analytics: tuple[str, ...]
    fluoride_release_analytics: tuple[str, ...] = ()
    mass_balance_measurements: tuple[str, ...] = Field(min_length=1)
    competing_product_measurements: tuple["CompetingProductMeasurement", ...] = Field(
        min_length=1
    )
    falsifying_observations: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def require_target_product_success_criterion(self) -> "DiagnosticAnalytics":
        target = self.required_target_analyte.strip().casefold()
        if (
            not target
            or "fluoride" in target
            or not self.target_product_methods
            or not self.target_product_analytics
        ):
            raise DiagnosticDesignError(
                "diagnostic success requires target product analytics; fluoride release alone is insufficient"
            )
        measurement_ids = tuple(
            measurement.measurement_id
            for measurement in self.competing_product_measurements
        )
        if len(set(measurement_ids)) != len(measurement_ids):
            raise DiagnosticDesignError(
                "competing-product measurement IDs must be unique"
            )
        return self


class CompetingProductMeasurement(FrozenStrictModel):
    measurement_id: str = Field(min_length=1)
    description: str = Field(min_length=1)


class PreChemistryAction(FrozenStrictModel):
    action_id: str = Field(min_length=1)
    action_type: PreChemistryActionType
    question: str = Field(min_length=1)
    evidence_ids: tuple[str, ...] = ()


class OperationalAction(FrozenStrictModel):
    action_id: str = Field(min_length=1)
    action_type: OperationalActionType
    representative_id: str | None = None
    prerequisite_id: str | None = None
    rationale: str = Field(min_length=1)


class RankingBasis(FrozenStrictModel):
    family_id: str = Field(min_length=1)
    priority_region: PriorityRegion
    primary_rank: int | None = Field(default=None, ge=1)
    evaluation_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    analysis_content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    rationale: str = Field(min_length=1)


class RepresentativeInventoryInput(FrozenStrictModel):
    inventory_id: str = Field(min_length=1)
    family_id: str = Field(min_length=1)
    state_id: str = Field(min_length=1)
    reactive_state: str = Field(min_length=1)
    structure_input: str = Field(min_length=1)
    mechanistic_coordinate_coverage: tuple[str, ...] = Field(min_length=1)
    diagnostic_contrasts: tuple[str, ...] = Field(min_length=1)
    availability_state: Literal["needs_verification", "unavailable"]
    evidence_ids: tuple[str, ...] = Field(min_length=1)
    inventory_artifact_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


_INVENTORY_BUILDER_TOKEN = object()
_INVENTORY_ATTESTATIONS: dict[
    int,
    tuple[
        weakref.ReferenceType[object],
        str,
        str,
        StructureFingerprintFactory,
    ],
] = {}


class RepresentativeInventoryRecord(FrozenStrictModel):
    record_id: str = Field(min_length=1)
    family_id: str = Field(min_length=1)
    state_id: str = Field(min_length=1)
    reactive_state: str = Field(min_length=1)
    mechanistic_coordinate_coverage: tuple[str, ...] = Field(min_length=1)
    diagnostic_contrasts: tuple[str, ...] = Field(min_length=1)
    availability_state: Literal["needs_verification", "unavailable"]
    structural_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    structure_fingerprint_receipt: StructureFingerprintReceipt
    cluster_key: str = Field(min_length=1)
    evidence_ids: tuple[str, ...] = Field(min_length=1)
    inventory_artifact_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    def __init__(self, **data: Any) -> None:
        token = data.pop("_builder_token", None)
        if token is not _INVENTORY_BUILDER_TOKEN:
            raise DiagnosticDesignError(
                "representative inventory requires factory attestation"
            )
        super().__init__(**data)


def _inventory_content_digest(record: RepresentativeInventoryRecord) -> str:
    return _stable_digest(
        record.model_dump(mode="json", exclude={"content_digest"})
    )


def record_representative_inventory(
    family: CanonicalFamily,
    inventory: RepresentativeInventoryInput,
    structure_factory: StructureFingerprintFactory,
) -> RepresentativeInventoryRecord:
    """Attest canonical structure and per-candidate mechanistic inventory data."""

    canonical_states = {
        state.strip().casefold(): state.strip()
        for state in family.representative_reactive_state_candidates
    }
    key = inventory.reactive_state.strip().casefold()
    if inventory.family_id != family.family_id or key not in canonical_states:
        raise DiagnosticDesignError(
            "representative inventory family or reactive state mismatch"
        )
    if not set(inventory.mechanistic_coordinate_coverage).issubset(
        _MECHANISTIC_COORDINATES
    ) or not set(inventory.diagnostic_contrasts).issubset(
        family.dominant_failure_modes
    ):
        raise DiagnosticDesignError(
            "representative inventory uses noncanonical mechanistic metadata"
        )
    subject_id = f"INVENTORY-{inventory.inventory_id}"
    try:
        fingerprint_receipt = derive_structure_fingerprint_receipt(
            structure_factory, subject_id, inventory.structure_input
        )
    except ValueError as exc:
        raise DiagnosticDesignError(str(exc)) from exc
    structural_fingerprint = fingerprint_receipt.fingerprint
    data = dict(
        record_id=f"INVENTORY-{inventory.inventory_id}",
        family_id=family.family_id,
        state_id=inventory.state_id,
        reactive_state=canonical_states[key],
        mechanistic_coordinate_coverage=tuple(
            coordinate
            for coordinate in _MECHANISTIC_COORDINATES
            if coordinate in inventory.mechanistic_coordinate_coverage
        ),
        diagnostic_contrasts=tuple(
            contrast
            for contrast in family.dominant_failure_modes
            if contrast in inventory.diagnostic_contrasts
        ),
        availability_state=inventory.availability_state,
        structural_fingerprint=structural_fingerprint,
        structure_fingerprint_receipt=fingerprint_receipt,
        cluster_key=f"cluster-{structural_fingerprint[:16]}",
        evidence_ids=tuple(sorted(set(inventory.evidence_ids))),
        inventory_artifact_digest=inventory.inventory_artifact_digest,
    )
    provisional = RepresentativeInventoryRecord(
        _builder_token=_INVENTORY_BUILDER_TOKEN,
        content_digest="0" * 64,
        **data,
    )
    record = RepresentativeInventoryRecord(
        _builder_token=_INVENTORY_BUILDER_TOKEN,
        content_digest=_inventory_content_digest(provisional),
        **data,
    )
    record_id = id(record)

    def discard(_: weakref.ReferenceType[object]) -> None:
        _INVENTORY_ATTESTATIONS.pop(record_id, None)

    _INVENTORY_ATTESTATIONS[record_id] = (
        weakref.ref(record, discard),
        record.content_digest,
        record.structural_fingerprint,
        structure_factory,
    )
    return record


def _verify_inventory_record(record: RepresentativeInventoryRecord) -> None:
    attestation = _INVENTORY_ATTESTATIONS.get(id(record))
    if (
        attestation is None
        or attestation[0]() is not record
        or attestation[1] != record.content_digest
        or attestation[2] != record.structural_fingerprint
        or _inventory_content_digest(record) != record.content_digest
    ):
        raise DiagnosticDesignError(
            "representative inventory attestation or content verification failed"
        )
    try:
        verify_structure_fingerprint_receipt(
            attestation[3],
            record.record_id,
            record.structure_fingerprint_receipt,
        )
    except ValueError as exc:
        raise DiagnosticDesignError(str(exc)) from exc
    if record.structure_fingerprint_receipt.fingerprint != record.structural_fingerprint:
        raise DiagnosticDesignError("representative fingerprint receipt mismatch")


def restore_representative_inventory_record(
    payload: Mapping[str, Any],
    structure_factory: StructureFingerprintFactory,
) -> RepresentativeInventoryRecord:
    """Restore a persisted inventory record after checking its content address."""

    record = RepresentativeInventoryRecord(
        _builder_token=_INVENTORY_BUILDER_TOKEN,
        **dict(payload),
    )
    if _inventory_content_digest(record) != record.content_digest:
        raise DiagnosticDesignError(
            "persisted representative inventory content digest mismatch"
        )
    try:
        verify_structure_fingerprint_receipt(
            structure_factory,
            record.record_id,
            record.structure_fingerprint_receipt,
        )
    except ValueError as exc:
        raise DiagnosticDesignError(str(exc)) from exc
    if record.structure_fingerprint_receipt.fingerprint != record.structural_fingerprint:
        raise DiagnosticDesignError("persisted representative fingerprint receipt mismatch")
    record_id = id(record)

    def discard(_: weakref.ReferenceType[object]) -> None:
        _INVENTORY_ATTESTATIONS.pop(record_id, None)

    _INVENTORY_ATTESTATIONS[record_id] = (
        weakref.ref(record, discard),
        record.content_digest,
        record.structural_fingerprint,
        structure_factory,
    )
    return record


class ReadinessVerificationInput(FrozenStrictModel):
    verification_id: str = Field(min_length=1)
    family_id: str = Field(min_length=1)
    state_id: str = Field(min_length=1)
    availability_verified: Literal[True]
    cleared_prerequisite_ids: tuple[str, ...] = Field(min_length=1)
    inventory_artifact_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    handling_artifact_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


_READINESS_BUILDER_TOKEN = object()
_READINESS_ATTESTATIONS: dict[
    int, tuple[weakref.ReferenceType[object], str, str, str, str]
] = {}


class RepresentativeReadinessRecord(FrozenStrictModel):
    record_id: str = Field(min_length=1)
    verification_id: str = Field(min_length=1)
    family_id: str = Field(min_length=1)
    state_id: str = Field(min_length=1)
    candidate_identity_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    inventory_artifact_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    handling_artifact_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    cleared_prerequisite_ids: tuple[str, ...] = Field(min_length=1)
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    def __init__(self, **data: Any) -> None:
        token = data.pop("_builder_token", None)
        if token is not _READINESS_BUILDER_TOKEN:
            raise DiagnosticDesignError(
                "representative readiness requires factory attestation"
            )
        super().__init__(**data)


def _candidate_identity_digest(candidate: ProposedRepresentativeState) -> str:
    return _stable_digest(
        {
            "state_id": candidate.state_id,
            "reactive_state": candidate.reactive_state.strip(),
            "mechanistic_coordinate_coverage": list(
                candidate.mechanistic_coordinate_coverage
            ),
            "diagnostic_contrasts": list(candidate.diagnostic_contrasts),
            "structural_fingerprint": candidate.structural_fingerprint,
            "cluster_key": candidate.cluster_key,
            "inventory_record_id": candidate.inventory_record_id,
            "inventory_content_digest": candidate.inventory_content_digest,
            "handling_prerequisites": [
                {
                    "prerequisite_id": prerequisite.prerequisite_id,
                    "description": prerequisite.description,
                }
                for prerequisite in candidate.handling_prerequisites
            ],
        }
    )


def _readiness_content_digest(record: RepresentativeReadinessRecord) -> str:
    return _stable_digest(
        record.model_dump(
            mode="json",
            exclude={"record_id", "verification_id", "content_digest"},
        )
    )


def record_representative_readiness(
    family: CanonicalFamily,
    candidate: ProposedRepresentativeState,
    verification: ReadinessVerificationInput,
    inventory_record: RepresentativeInventoryRecord,
) -> RepresentativeReadinessRecord:
    """Factory-attest independent availability and handling verification."""

    if verification.family_id != family.family_id:
        raise DiagnosticDesignError("readiness verification family mismatch")
    validated = _validated_candidates(
        family,
        DiagnosticDesignProposal(
            family_id=family.family_id,
            representative_states=(candidate,),
            condition_states=(),
        ),
        (inventory_record,),
    )[0]
    prerequisite_ids = tuple(
        prerequisite.prerequisite_id
        for prerequisite in validated.handling_prerequisites
    )
    if (
        verification.state_id != validated.state_id
        or set(verification.cleared_prerequisite_ids) != set(prerequisite_ids)
    ):
        raise DiagnosticDesignError(
            "readiness verification must clear the exact candidate prerequisites"
        )
    if (
        verification.inventory_artifact_digest
        != inventory_record.inventory_artifact_digest
    ):
        raise DiagnosticDesignError(
            "readiness verification inventory artifact mismatch"
        )
    content = dict(
        family_id=family.family_id,
        state_id=validated.state_id,
        candidate_identity_digest=_candidate_identity_digest(validated),
        inventory_artifact_digest=verification.inventory_artifact_digest,
        handling_artifact_digest=verification.handling_artifact_digest,
        cleared_prerequisite_ids=tuple(sorted(prerequisite_ids)),
    )
    provisional = RepresentativeReadinessRecord(
        _builder_token=_READINESS_BUILDER_TOKEN,
        record_id=f"READINESS-{'0' * 64}",
        verification_id=verification.verification_id,
        content_digest="0" * 64,
        **content,
    )
    content_digest = _readiness_content_digest(provisional)
    record = RepresentativeReadinessRecord(
        _builder_token=_READINESS_BUILDER_TOKEN,
        record_id=f"READINESS-{content_digest}",
        verification_id=verification.verification_id,
        content_digest=content_digest,
        **content,
    )
    record_id = id(record)

    def discard(_: weakref.ReferenceType[object]) -> None:
        _READINESS_ATTESTATIONS.pop(record_id, None)

    _READINESS_ATTESTATIONS[record_id] = (
        weakref.ref(record, discard),
        record.content_digest,
        record.candidate_identity_digest,
        record.verification_id,
        record.record_id,
    )
    return record


def _verify_readiness_attestation(record: RepresentativeReadinessRecord) -> None:
    attestation = _READINESS_ATTESTATIONS.get(id(record))
    if (
        attestation is None
        or attestation[0]() is not record
        or attestation[1] != record.content_digest
        or attestation[2] != record.candidate_identity_digest
        or attestation[3] != record.verification_id
        or attestation[4] != record.record_id
        or _readiness_content_digest(record) != record.content_digest
        or record.record_id != f"READINESS-{record.content_digest}"
    ):
        raise DiagnosticDesignError(
            "representative readiness attestation or content address failed"
        )


def restore_representative_readiness_record(
    payload: Mapping[str, Any],
) -> RepresentativeReadinessRecord:
    """Restore a persisted readiness record after checking its content address."""

    record = RepresentativeReadinessRecord(
        _builder_token=_READINESS_BUILDER_TOKEN,
        **dict(payload),
    )
    if (
        _readiness_content_digest(record) != record.content_digest
        or record.record_id != f"READINESS-{record.content_digest}"
    ):
        raise DiagnosticDesignError(
            "persisted representative readiness content digest mismatch"
        )
    record_id = id(record)

    def discard(_: weakref.ReferenceType[object]) -> None:
        _READINESS_ATTESTATIONS.pop(record_id, None)

    _READINESS_ATTESTATIONS[record_id] = (
        weakref.ref(record, discard),
        record.content_digest,
        record.candidate_identity_digest,
        record.verification_id,
        record.record_id,
    )
    return record


def _verify_readiness_record(
    record: RepresentativeReadinessRecord,
    candidate: ProposedRepresentativeState,
) -> None:
    _verify_readiness_attestation(record)
    if (
        record.candidate_identity_digest != _candidate_identity_digest(candidate)
        or record.state_id != candidate.state_id
        or set(record.cleared_prerequisite_ids)
        != {
            prerequisite.prerequisite_id
            for prerequisite in candidate.handling_prerequisites
        }
    ):
        raise DiagnosticDesignError(
            "representative readiness attestation or candidate link failed"
        )


class ExecutionResultInput(FrozenStrictModel):
    result_id: str = Field(min_length=1)
    family_id: str = Field(min_length=1)
    plan_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    representative_id: str = Field(min_length=1)
    condition_id: str = Field(min_length=1)
    target_product_confirmed: bool
    target_analyte: str
    target_product_method: str
    target_product_readout: str
    fluoride_release_readout: str | None = None
    mass_balance_readout: str
    competing_product_readouts: Mapping[str, str]
    falsification_observations_checked: tuple[str, ...]
    run_artifact_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    result_artifact_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def freeze_competing_product_readouts(self) -> "ExecutionResultInput":
        object.__setattr__(
            self,
            "competing_product_readouts",
            MappingProxyType(dict(sorted(self.competing_product_readouts.items()))),
        )
        return self

    @field_serializer("competing_product_readouts")
    def serialize_competing_product_readouts(
        self, value: Mapping[str, str]
    ) -> dict[str, str]:
        return dict(value)


_RESULT_BUILDER_TOKEN = object()
_RESULT_ATTESTATIONS: dict[
    int, tuple[weakref.ReferenceType[object], str, str]
] = {}


class _ExecutionRecord(FrozenStrictModel):
    record_id: str = Field(min_length=1)
    family_id: str = Field(min_length=1)
    plan_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    representative_id: str = Field(min_length=1)
    condition_id: str = Field(min_length=1)
    target_analyte: str = Field(min_length=1)
    target_product_method: str = Field(min_length=1)
    target_product_readout: str = Field(min_length=1)
    mass_balance_readout: str = Field(min_length=1)
    competing_product_readouts: Mapping[str, str]
    falsification_observations_checked: tuple[str, ...] = Field(min_length=1)
    run_artifact_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    result_artifact_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    def __init__(self, **data: Any) -> None:
        token = data.pop("_builder_token", None)
        if token is not _RESULT_BUILDER_TOKEN:
            raise DiagnosticDesignError(
                "diagnostic execution record requires factory attestation"
            )
        super().__init__(**data)

    @model_validator(mode="after")
    def freeze_competing_product_readouts(self) -> "_ExecutionRecord":
        object.__setattr__(
            self,
            "competing_product_readouts",
            MappingProxyType(dict(sorted(self.competing_product_readouts.items()))),
        )
        return self

    @field_serializer("competing_product_readouts")
    def serialize_competing_product_readouts(
        self, value: Mapping[str, str]
    ) -> dict[str, str]:
        return dict(value)


class DiagnosticSuccessRecord(_ExecutionRecord):
    disposition: Literal["diagnostic_success"] = "diagnostic_success"


class DiagnosticFailureRecord(_ExecutionRecord):
    disposition: Literal["diagnostic_failure"] = "diagnostic_failure"


class BoundaryFalsificationRecord(_ExecutionRecord):
    disposition: Literal["boundary_falsified"] = "boundary_falsified"


DiagnosticRecord = (
    DiagnosticSuccessRecord | DiagnosticFailureRecord | BoundaryFalsificationRecord
)


def _record_content_digest(record: _ExecutionRecord) -> str:
    return _stable_digest(
        record.model_dump(mode="json", exclude={"content_digest"})
    )


def _build_record(
    record_type: type[_ExecutionRecord], **data: Any
) -> _ExecutionRecord:
    provisional = record_type(
        _builder_token=_RESULT_BUILDER_TOKEN,
        content_digest="0" * 64,
        **data,
    )
    record = record_type(
        _builder_token=_RESULT_BUILDER_TOKEN,
        content_digest=_record_content_digest(provisional),
        **data,
    )
    record_id = id(record)

    def discard(_: weakref.ReferenceType[object]) -> None:
        _RESULT_ATTESTATIONS.pop(record_id, None)

    _RESULT_ATTESTATIONS[record_id] = (
        weakref.ref(record, discard),
        record.content_digest,
        record.plan_digest,
    )
    return record


def restore_diagnostic_record(payload: Mapping[str, Any]) -> DiagnosticRecord:
    """Restore a persisted execution record after checking its content address."""

    data = dict(payload)
    supplied_digest = data.pop("content_digest", None)
    record_types: Mapping[str, type[_ExecutionRecord]] = {
        "diagnostic_success": DiagnosticSuccessRecord,
        "diagnostic_failure": DiagnosticFailureRecord,
        "boundary_falsified": BoundaryFalsificationRecord,
    }
    record_type = record_types.get(str(data.get("disposition")))
    if record_type is None:
        raise DiagnosticDesignError("persisted diagnostic record disposition is invalid")
    record = _build_record(record_type, **data)
    if record.content_digest != supplied_digest:
        raise DiagnosticDesignError("persisted diagnostic record content digest mismatch")
    return record


def _verify_record(record: DiagnosticRecord, plan_digest: str) -> None:
    if not isinstance(
        record,
        (DiagnosticSuccessRecord, DiagnosticFailureRecord, BoundaryFalsificationRecord),
    ):
        raise DiagnosticDesignError("diagnostic success attestation failed")
    attestation = _RESULT_ATTESTATIONS.get(id(record))
    if (
        attestation is None
        or attestation[0]() is not record
        or attestation[1] != record.content_digest
        or attestation[2] != record.plan_digest
        or _record_content_digest(record) != record.content_digest
        or record.plan_digest != plan_digest
    ):
        raise DiagnosticDesignError("diagnostic success attestation or plan link failed")


class OptimizationPlan(FrozenStrictModel):
    optimization_id: str = Field(min_length=1)
    family_id: str = Field(min_length=1)
    diagnostic_success_record_id: str = Field(min_length=1)
    plan_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    objective: str = Field(min_length=1)
    variables: tuple[str, ...] = Field(min_length=1)


_PLAN_BUILDER_TOKEN = object()
_PLAN_ATTESTATIONS: dict[
    int, tuple[weakref.ReferenceType[object], str, str]
] = {}


class FamilyDiagnosticPlan(FrozenStrictModel):
    family_id: str = Field(min_length=1)
    priority_region: PriorityRegion
    plan_role: PlanRole
    expected_outcome: ExpectedOutcome
    chemistry_planned: bool
    executable: bool
    representatives: tuple[RepresentativeReagent, ...] = Field(max_length=3)
    conditions: tuple[MechanisticConditionState, ...]
    paired_controls: tuple[PairedControl, ...]
    analytics: DiagnosticAnalytics | None
    pre_chemistry_actions: tuple[PreChemistryAction, ...]
    operational_actions: tuple[OperationalAction, ...]
    negative_control_label: str | None
    no_experiment_rationale: str | None
    supporting_principle_ids: tuple[str, ...]
    principle_evidence_links: Mapping[str, tuple[str, ...]]
    evidence_ids: tuple[str, ...]
    ranking_basis: RankingBasis | None
    diagnostic_records: tuple[DiagnosticRecord, ...] = ()
    optimization_plans: tuple[OptimizationPlan, ...] = ()
    plan_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    def __init__(self, **data: Any) -> None:
        token = data.pop("_builder_token", None)
        if token is not _PLAN_BUILDER_TOKEN:
            raise DiagnosticDesignError(
                "family diagnostic plan requires factory attestation"
            )
        super().__init__(**data)

    @model_validator(mode="after")
    def validate_staged_design(self) -> "FamilyDiagnosticPlan":
        object.__setattr__(
            self,
            "principle_evidence_links",
            MappingProxyType(
                {
                    principle_id: tuple(evidence_ids)
                    for principle_id, evidence_ids in sorted(
                        self.principle_evidence_links.items()
                    )
                }
            ),
        )
        chemistry_present = bool(
            self.representatives
            or self.conditions
            or self.paired_controls
            or self.analytics is not None
        )
        if self.priority_region in {"priority_a", "priority_b", "priority_c"}:
            if (
                not self.chemistry_planned
                or self.plan_role != "diagnostic"
                or self.expected_outcome != "target_product_present"
                or not 1 <= len(self.representatives) <= 3
                or not self.conditions
                or not self.paired_controls
                or self.analytics is None
                or self.ranking_basis is None
            ):
                raise DiagnosticDesignError("testable family requires a complete diagnostic")
        elif self.priority_region == "boundary":
            if (
                not self.chemistry_planned
                or self.plan_role != "negative_control"
                or self.expected_outcome != "target_product_absent"
                or not self.negative_control_label
                or not 1 <= len(self.representatives) <= 3
                or self.analytics is None
                or self.ranking_basis is None
                or self.optimization_plans
            ):
                raise DiagnosticDesignError(
                    "boundary family requires a negative-control plan with no optimization"
                )
        elif self.priority_region == "excluded":
            if (
                self.chemistry_planned
                or self.executable
                or self.plan_role != "no_experiment"
                or self.expected_outcome != "not_applicable"
                or chemistry_present
                or not self.no_experiment_rationale
                or self.diagnostic_records
                or self.optimization_plans
            ):
                raise DiagnosticDesignError("excluded family must receive no experiment")
        elif (
            self.chemistry_planned
            or self.executable
            or self.plan_role != "evidence_first"
            or self.expected_outcome != "unresolved"
            or chemistry_present
            or not self.pre_chemistry_actions
            or self.diagnostic_records
            or self.optimization_plans
        ):
            raise DiagnosticDesignError(
                "unknown family requires evidence acquisition before chemistry"
            )
        if any(
            control.baseline not in self.conditions
            or control.comparison not in self.conditions
            for control in self.paired_controls
        ):
            raise DiagnosticDesignError(
                "paired-control endpoints must be declared plan conditions"
            )
        operationally_ready = all(
            representative.availability_state == "verified_available"
            and all(
                prerequisite.status == "cleared"
                for prerequisite in representative.handling_prerequisites
            )
            for representative in self.representatives
        )
        blocking_actions = any(
            action.action_type
            in {
                "verify_availability",
                "replace_unavailable",
                "clear_handling_prerequisite",
            }
            for action in self.operational_actions
        )
        if self.chemistry_planned and self.executable != (
            operationally_ready and not blocking_actions
        ):
            raise DiagnosticDesignError(
                "executable requires verified availability and cleared handling"
            )
        return self

    @field_serializer("principle_evidence_links")
    def serialize_principle_evidence_links(
        self, value: Mapping[str, tuple[str, ...]]
    ) -> dict[str, tuple[str, ...]]:
        return dict(value)


def _plan_digest(plan: FamilyDiagnosticPlan) -> str:
    return _stable_digest(
        plan.model_dump(
            mode="json",
            exclude={
                "plan_digest",
                "content_digest",
                "diagnostic_records",
                "optimization_plans",
                "operational_actions",
            },
        )
    )


def _plan_content_digest(plan: FamilyDiagnosticPlan) -> str:
    return _stable_digest(
        plan.model_dump(mode="json", exclude={"content_digest"})
    )


def _build_plan(**data: Any) -> FamilyDiagnosticPlan:
    provisional = FamilyDiagnosticPlan(
        _builder_token=_PLAN_BUILDER_TOKEN,
        plan_digest="0" * 64,
        content_digest="0" * 64,
        **data,
    )
    plan_digest = _plan_digest(provisional)
    content_provisional = FamilyDiagnosticPlan(
        _builder_token=_PLAN_BUILDER_TOKEN,
        plan_digest=plan_digest,
        content_digest="0" * 64,
        **data,
    )
    plan = FamilyDiagnosticPlan(
        _builder_token=_PLAN_BUILDER_TOKEN,
        plan_digest=plan_digest,
        content_digest=_plan_content_digest(content_provisional),
        **data,
    )
    plan_id = id(plan)

    def discard(_: weakref.ReferenceType[object]) -> None:
        _PLAN_ATTESTATIONS.pop(plan_id, None)

    _PLAN_ATTESTATIONS[plan_id] = (
        weakref.ref(plan, discard),
        plan.plan_digest,
        plan.content_digest,
    )
    return plan


def verify_family_diagnostic_plan(
    plan: FamilyDiagnosticPlan,
) -> FamilyDiagnosticPlan:
    """Verify factory identity and both execution-plan and full-content digests."""

    if not isinstance(plan, FamilyDiagnosticPlan):
        raise DiagnosticDesignError("family diagnostic plan attestation failed")
    attestation = _PLAN_ATTESTATIONS.get(id(plan))
    if (
        attestation is None
        or attestation[0]() is not plan
        or attestation[1] != plan.plan_digest
        or attestation[2] != plan.content_digest
        or _plan_digest(plan) != plan.plan_digest
        or _plan_content_digest(plan) != plan.content_digest
    ):
        raise DiagnosticDesignError(
            "family diagnostic plan attestation or content verification failed"
        )
    return plan


def _unique_by_id(
    items: Sequence[object], attribute: str, label: str
) -> dict[str, object]:
    indexed: dict[str, object] = {}
    for item in items:
        identifier = getattr(item, attribute, None)
        if not isinstance(identifier, str) or not identifier:
            raise DiagnosticDesignError(f"{label} must use canonical {attribute}")
        if identifier in indexed:
            raise DiagnosticDesignError(f"duplicate {label} ID: {identifier}")
        indexed[identifier] = item
    return indexed


def _ranking_basis(
    record: RobustnessRankingRecord, analysis: RankingAnalysis
) -> RankingBasis:
    return RankingBasis(
        family_id=record.family_id,
        priority_region=record.priority_region,
        primary_rank=record.primary_rank,
        evaluation_digest=record.evaluation_digest,
        analysis_content_digest=analysis.content_digest,
        rationale=record.rationale,
    )


def _verify_trust_chain(
    evaluations: Sequence[ScoredFamilyEvaluation],
    ranking_analysis: RankingAnalysis | None,
    rubric: EvaluationRubric,
) -> tuple[
    dict[str, PriorityRegion],
    dict[str, RankingBasis],
    tuple[ScoredFamilyEvaluation, ...],
]:
    scored: list[ScoredFamilyEvaluation] = []
    regions: dict[str, PriorityRegion] = {}
    for evaluation in evaluations:
        if not isinstance(evaluation, ScoredFamilyEvaluation):
            raise DiagnosticDesignError(
                "diagnostic design requires an attested scored evaluation"
            )
        try:
            verify_scored_family_evaluation(evaluation, rubric)
        except EvidenceQualificationError as exc:
            raise DiagnosticDesignError(
                f"evaluation attestation failed: {exc}"
            ) from exc
        scored.append(evaluation)
        regions[evaluation.family_id] = evaluation.priority_region
    chemistry_ids = {
        family_id
        for family_id, region in regions.items()
        if region in {"priority_a", "priority_b", "priority_c", "boundary"}
    }
    if chemistry_ids and ranking_analysis is None:
        raise DiagnosticDesignError(
            "all chemistry plans require canonical ranking analysis"
        )
    bases: dict[str, RankingBasis] = {}
    if ranking_analysis is not None:
        try:
            verified_analysis = verify_ranking_analysis(
                ranking_analysis, tuple(scored), rubric
            )
        except RankingAnalysisError as exc:
            raise DiagnosticDesignError(
                f"ranking analysis attestation or evaluation digest failed: {exc}"
            ) from exc
        bases = {
            record.family_id: _ranking_basis(record, verified_analysis)
            for record in verified_analysis.records
        }
        if chemistry_ids.difference(bases):
            raise DiagnosticDesignError("ranking analysis omits a chemistry family")
    return regions, bases, tuple(scored)


def _validated_candidates(
    family: CanonicalFamily,
    proposal: DiagnosticDesignProposal | None,
    inventory_records: Sequence[RepresentativeInventoryRecord],
) -> tuple[ProposedRepresentativeState, ...]:
    canonical = {
        state.strip().casefold(): state.strip()
        for state in family.representative_reactive_state_candidates
    }
    inventory_by_state: dict[str, RepresentativeInventoryRecord] = {}
    for record in inventory_records:
        _verify_inventory_record(record)
        if record.family_id != family.family_id:
            raise DiagnosticDesignError("representative inventory family mismatch")
        if record.state_id in inventory_by_state:
            raise DiagnosticDesignError("duplicate representative inventory state ID")
        if record.reactive_state.strip().casefold() not in canonical:
            raise DiagnosticDesignError(
                "representative inventory state is not canonical"
            )
        inventory_by_state[record.state_id] = record
    if not inventory_by_state:
        raise DiagnosticDesignError(
            "chemistry planning requires attested representative inventory"
        )
    proposed_by_state = (
        {candidate.state_id: candidate for candidate in proposal.representative_states}
        if proposal is not None
        else {}
    )
    if proposal is not None and len(proposed_by_state) != len(
        proposal.representative_states
    ):
        raise DiagnosticDesignError("representative state IDs must be unique")
    if proposal is not None and not set(proposed_by_state).issubset(inventory_by_state):
        raise DiagnosticDesignError(
            "model state lacks attested representative inventory"
        )
    selected_records = tuple(
        inventory_by_state[state_id]
        for state_id in sorted(proposed_by_state or inventory_by_state)
    )
    validated: list[ProposedRepresentativeState] = []
    for record in selected_records:
        candidate = proposed_by_state.get(record.state_id)
        if candidate is not None and (
            candidate.reactive_state.strip().casefold()
            != record.reactive_state.strip().casefold()
        ):
            raise DiagnosticDesignError(
                "model state does not match attested representative inventory"
            )
        canonical_prerequisites = tuple(
            HandlingPrerequisite(
                prerequisite_id=f"HANDLE-{family.family_id}-{condition_index}",
                description=condition,
                status="uncleared",
            )
            for condition_index, condition in enumerate(
                family.critical_conditions, start=1
            )
        )
        proposed_prerequisites = {
            prerequisite.prerequisite_id: prerequisite
            for prerequisite in (
                candidate.handling_prerequisites if candidate is not None else ()
            )
        }
        if candidate is not None and len(proposed_prerequisites) != len(
            candidate.handling_prerequisites
        ):
            raise DiagnosticDesignError(
                "representative handling prerequisite IDs must be unique"
            )
        canonical_by_id = {
            prerequisite.prerequisite_id: prerequisite
            for prerequisite in canonical_prerequisites
        }
        if any(
            proposed_prerequisites[prerequisite_id].description
            != canonical_by_id[prerequisite_id].description
            for prerequisite_id in set(proposed_prerequisites).intersection(
                canonical_by_id
            )
        ):
            raise DiagnosticDesignError(
                "model handling prerequisites cannot replace canonical requirements"
            )
        additional_prerequisites = tuple(
            proposed_prerequisites[prerequisite_id].model_copy(
                update={"status": "uncleared"}
            )
            for prerequisite_id in sorted(
                set(proposed_prerequisites).difference(canonical_by_id)
            )
        )
        validated.append(
            ProposedRepresentativeState(
                state_id=record.state_id,
                reactive_state=record.reactive_state,
                mechanistic_coordinate_coverage=(
                    record.mechanistic_coordinate_coverage
                ),
                diagnostic_contrasts=record.diagnostic_contrasts,
                structural_fingerprint=record.structural_fingerprint,
                cluster_key=record.cluster_key,
                availability_state=record.availability_state,
                handling_prerequisites=(
                    canonical_prerequisites + additional_prerequisites
                ),
                inventory_record_id=record.record_id,
                inventory_content_digest=record.content_digest,
            )
        )
    return tuple(validated)


def _candidate_tokens(candidate: ProposedRepresentativeState) -> set[str]:
    return set(candidate.mechanistic_coordinate_coverage).union(
        f"failure:{value}" for value in candidate.diagnostic_contrasts
    )


def _select_candidates(
    family: CanonicalFamily,
    candidates: Sequence[ProposedRepresentativeState],
) -> tuple[ProposedRepresentativeState, ...]:
    universe = set(_MECHANISTIC_COORDINATES).union(
        f"failure:{value}" for value in family.dominant_failure_modes
    )
    available = tuple(
        candidate
        for candidate in candidates
        if candidate.availability_state != "unavailable"
    )
    raw_pool = available or tuple(candidates)
    pool_by_structure: dict[str, ProposedRepresentativeState] = {}
    for candidate in sorted(
        raw_pool,
        key=lambda item: (
            -len(_candidate_tokens(item)),
            0 if item.availability_state == "verified_available" else 1,
            item.state_id,
        ),
    ):
        pool_by_structure.setdefault(candidate.structural_fingerprint, candidate)
    pool = tuple(pool_by_structure.values())
    selected: list[ProposedRepresentativeState] = []
    uncovered = set(universe)
    covered_clusters: set[str] = set()
    remaining = list(pool)
    while uncovered and remaining and len(selected) < 3:
        ordered = sorted(
            remaining,
            key=lambda candidate: (
                -len(_candidate_tokens(candidate).intersection(uncovered)),
                -(candidate.cluster_key not in covered_clusters),
                0
                if candidate.availability_state == "verified_available"
                else 1,
                candidate.state_id,
            ),
        )
        chosen = ordered[0]
        if not _candidate_tokens(chosen).intersection(uncovered):
            break
        selected.append(chosen)
        uncovered.difference_update(_candidate_tokens(chosen))
        covered_clusters.add(chosen.cluster_key)
        remaining.remove(chosen)
    if uncovered:
        raise DiagnosticDesignError(
            "one to three representatives cannot cover required mechanistic coordinates"
        )
    return tuple(selected)


def _apply_readiness(
    family: CanonicalFamily,
    candidates: Sequence[ProposedRepresentativeState],
    records: Sequence[RepresentativeReadinessRecord],
) -> tuple[
    tuple[ProposedRepresentativeState, ...],
    Mapping[str, RepresentativeReadinessRecord],
]:
    candidate_by_state = {candidate.state_id: candidate for candidate in candidates}
    record_by_state: dict[str, RepresentativeReadinessRecord] = {}
    content_by_verification_id: dict[str, str] = {}
    for record in records:
        if record.family_id != family.family_id:
            raise DiagnosticDesignError("representative readiness family mismatch")
        candidate = candidate_by_state.get(record.state_id)
        if candidate is None:
            raise DiagnosticDesignError(
                "representative readiness cites an unknown proposed state"
            )
        _verify_readiness_record(record, candidate)
        existing_content = content_by_verification_id.get(record.verification_id)
        if (
            existing_content is not None
            and existing_content != record.content_digest
        ):
            raise DiagnosticDesignError(
                "representative readiness verification ID collision"
            )
        content_by_verification_id[record.verification_id] = record.content_digest
        if record.state_id in record_by_state:
            raise DiagnosticDesignError(
                "duplicate representative readiness state verification"
            )
        record_by_state[record.state_id] = record
    ready_candidates = tuple(
        candidate.model_copy(
            update={
                "availability_state": "verified_available",
                "handling_prerequisites": tuple(
                    prerequisite.model_copy(update={"status": "cleared"})
                    for prerequisite in candidate.handling_prerequisites
                ),
            }
        )
        if candidate.state_id in record_by_state
        else candidate
        for candidate in candidates
    )
    return ready_candidates, MappingProxyType(record_by_state)


def _representatives(
    family: CanonicalFamily,
    evidence_ids: tuple[str, ...],
    proposal: DiagnosticDesignProposal | None,
    inventory_records: Sequence[RepresentativeInventoryRecord],
    readiness_records: Sequence[RepresentativeReadinessRecord],
) -> tuple[RepresentativeReagent, ...]:
    validated_candidates = _validated_candidates(
        family, proposal, inventory_records
    )
    trusted_evidence_ids = set(evidence_ids)
    if any(
        not set(record.evidence_ids).issubset(trusted_evidence_ids)
        for record in inventory_records
    ):
        raise DiagnosticDesignError(
            "representative inventory evidence is not part of the attested evaluation"
        )
    inventory_by_state = {
        record.state_id: record for record in inventory_records
    }
    candidates, readiness_by_state = _apply_readiness(
        family,
        validated_candidates,
        readiness_records,
    )
    selected = _select_candidates(family, candidates)
    return tuple(
        RepresentativeReagent(
            representative_id=f"REP-{family.family_id}-{candidate.state_id}",
            state_id=candidate.state_id,
            reactive_state=candidate.reactive_state,
            mechanistic_coordinate_coverage=candidate.mechanistic_coordinate_coverage,
            diagnostic_contrasts=candidate.diagnostic_contrasts,
            structural_fingerprint=candidate.structural_fingerprint,
            cluster_key=candidate.cluster_key,
            availability_state=candidate.availability_state,
            handling_prerequisites=candidate.handling_prerequisites,
            readiness_record_id=(
                readiness_by_state[candidate.state_id].record_id
                if candidate.state_id in readiness_by_state
                else None
            ),
            readiness_content_digest=(
                readiness_by_state[candidate.state_id].content_digest
                if candidate.state_id in readiness_by_state
                else None
            ),
            readiness_inventory_artifact_digest=(
                readiness_by_state[candidate.state_id].inventory_artifact_digest
                if candidate.state_id in readiness_by_state
                else None
            ),
            readiness_handling_artifact_digest=(
                readiness_by_state[candidate.state_id].handling_artifact_digest
                if candidate.state_id in readiness_by_state
                else None
            ),
            inventory_record_id=candidate.inventory_record_id or "",
            inventory_content_digest=candidate.inventory_content_digest or "",
            mechanistic_representativeness=(
                "Covers canonical coordinates: "
                + ", ".join(candidate.mechanistic_coordinate_coverage)
            ),
            diagnostic_value=(
                "Contrasts canonical failure modes: "
                + ", ".join(candidate.diagnostic_contrasts)
            ),
            evidence_ids=inventory_by_state[candidate.state_id].evidence_ids,
        )
        for candidate in selected
    )


def _conditions(
    family: CanonicalFamily,
    principles: Sequence[ReactionPrinciple],
    principle_dimensions: Mapping[str, tuple[str, ...]],
    proposal: DiagnosticDesignProposal | None,
) -> tuple[MechanisticConditionState, MechanisticConditionState]:
    if proposal is not None and proposal.condition_states:
        raise DiagnosticDesignError(
            "model-proposed condition values are not allowed"
        )
    catalyst_state = "; ".join(
        requirement
        for principle in principles
        if "condition_compatibility"
        in principle_dimensions.get(principle.principle_id, ())
        for requirement in principle.catalyst_requirements
    ) or "No additional synthetic catalyst constraint"
    condition_windows = tuple(
        window
        for principle in principles
        if "condition_compatibility"
        in principle_dimensions.get(principle.principle_id, ())
        for window in principle.condition_window
    )
    baseline = MechanisticConditionState(
        state_id=f"COND-{family.family_id}-BASELINE",
        protonation_state=family.reactive_state,
        catalyst_state=catalyst_state,
        medium_state="; ".join((*family.critical_conditions, *condition_windows)),
        temperature_state="Synthetic diagnostic temperature held constant",
        concentration_state="Synthetic diagnostic concentration held constant",
        atmosphere_state="Synthetic diagnostic atmosphere held constant",
        time_state="Synthetic diagnostic sampling time held constant",
    )
    comparison = baseline.model_copy(
        update={
            "state_id": f"COND-{family.family_id}-PROTONATION-CONTROL",
            "protonation_state": f"Contrasting control for {family.reactive_state}",
        }
    )
    return baseline, comparison


def _analytics(family: CanonicalFamily) -> DiagnosticAnalytics:
    return DiagnosticAnalytics(
        required_target_analyte="synthetic target product",
        target_product_methods=("synthetic calibrated assay",),
        target_product_analytics=(
            "Quantify and confirm the synthetic target product with an orthogonal assay.",
        ),
        fluoride_release_analytics=(
            "Measure synthetic fluoride release only as a supporting signal.",
        ),
        mass_balance_measurements=(
            "Close mass balance across substrate, target, and byproducts.",
        ),
        competing_product_measurements=tuple(
            CompetingProductMeasurement(
                measurement_id=f"COMPETING-{index}",
                description=(
                    f"Quantify competing product associated with {failure_mode}."
                ),
            )
            for index, failure_mode in enumerate(
                family.dominant_failure_modes, start=1
            )
        ),
        falsifying_observations=(
            "Target product remains absent while supporting signal is present.",
            "The one-factor pair does not change target-product formation as predicted.",
        ),
    )


def _pre_chemistry_actions(
    family: CanonicalFamily, evaluation: ScoredFamilyEvaluation
) -> tuple[PreChemistryAction, ...]:
    actions = tuple(
        PreChemistryAction(
            action_id=f"ACTION-{family.family_id}-{index}",
            action_type="evidence_acquisition",
            question=f"Resolve critical unknown: {unknown}.",
        )
        for index, unknown in enumerate(evaluation.critical_unknowns, start=1)
    )
    return actions or (
        PreChemistryAction(
            action_id=f"ACTION-{family.family_id}-1",
            action_type="source_revisit",
            question="Revisit canonical source support before chemistry.",
            evidence_ids=family.evidence_ids,
        ),
    )


def _operational_actions(
    representatives: Sequence[RepresentativeReagent],
    records: Sequence[DiagnosticRecord],
) -> tuple[OperationalAction, ...]:
    actions: list[OperationalAction] = []
    for representative in representatives:
        if representative.availability_state == "needs_verification":
            actions.append(
                OperationalAction(
                    action_id=f"VERIFY-{representative.representative_id}",
                    action_type="verify_availability",
                    representative_id=representative.representative_id,
                    rationale="Physical availability must be verified before execution.",
                )
            )
        elif representative.availability_state == "unavailable":
            actions.append(
                OperationalAction(
                    action_id=f"REPLACE-{representative.representative_id}",
                    action_type="replace_unavailable",
                    representative_id=representative.representative_id,
                    rationale="Unavailable representative must be replaced before execution.",
                )
            )
        for prerequisite in representative.handling_prerequisites:
            if prerequisite.status == "uncleared":
                actions.append(
                    OperationalAction(
                        action_id=f"CLEAR-{prerequisite.prerequisite_id}",
                        action_type="clear_handling_prerequisite",
                        representative_id=representative.representative_id,
                        prerequisite_id=prerequisite.prerequisite_id,
                        rationale="Handling prerequisite must be cleared before execution.",
                    )
                )
    if any(isinstance(record, BoundaryFalsificationRecord) for record in records):
        actions.append(
            OperationalAction(
                action_id="RECLASSIFY-BOUNDARY",
                action_type="reclassify_boundary",
                rationale="Target-product-positive boundary result requires reclassification.",
            )
        )
    return tuple(actions)


def _evaluation_provenance(
    family: CanonicalFamily,
    evaluation: ScoredFamilyEvaluation,
    evidence_by_id: Mapping[str, object],
    principle_by_id: Mapping[str, object],
    *,
    require_principles: bool = True,
) -> tuple[
    tuple[ReactionPrinciple, ...],
    tuple[str, ...],
    dict[str, tuple[str, ...]],
    dict[str, tuple[str, ...]],
]:
    judgment_usage = {
        (judgment.dimension, evidence_id, False)
        for judgment in evaluation.judgments
        for evidence_id in judgment.evidence_ids
    }.union(
        {
            (judgment.dimension, evidence_id, True)
            for judgment in evaluation.judgments
            for evidence_id in judgment.counterevidence_ids
        }
    )
    contribution_usage = {
        (contribution.dimension, contribution.evidence_id, contribution.is_counterevidence)
        for contribution in evaluation.evidence_contributions
    }
    if judgment_usage != contribution_usage:
        raise DiagnosticDesignError(
            "evaluation evidence contributions do not match attested judgments"
        )
    blocker_usage = {
        (blocker.dimension, evidence_id)
        for blocker in evaluation.qualified_blockers
        for evidence_id in (*blocker.evidence_ids, *blocker.counterevidence_ids)
    }
    referenced_ids = {item[1] for item in judgment_usage}.union(
        evidence_id for _, evidence_id in blocker_usage
    )
    if set(evaluation.evidence_principle_links) != referenced_ids:
        raise DiagnosticDesignError(
            "evaluation Principle links do not match attested evidence"
        )
    evidence_dimensions = {
        (dimension, evidence_id) for dimension, evidence_id, _ in judgment_usage
    }.union(blocker_usage)
    for dimension, evidence_id in evidence_dimensions:
        record = evidence_by_id.get(evidence_id)
        if not isinstance(record, QualifiedEvidenceRecord):
            raise DiagnosticDesignError(
                f"unknown exact evidence ID in diagnostic inputs: {evidence_id}"
            )
        if (
            _stable_digest(record.model_dump(mode="json"))
            != evaluation.evidence_record_digests[evidence_id]
            or dimension not in record.admissible_dimensions
        ):
            raise DiagnosticDesignError(
                f"evidence does not match attested evaluation provenance: {evidence_id}"
            )
    principles: list[ReactionPrinciple] = []
    for principle_id in (
        evaluation.reviewed_principle_ids if require_principles else ()
    ):
        principle = principle_by_id.get(principle_id)
        if not isinstance(principle, ReactionPrinciple):
            raise DiagnosticDesignError(
                f"family cites unknown reviewed Principle: {principle_id}"
            )
        if _principle_digest(principle) != evaluation.reviewed_principle_digests[
            principle_id
        ]:
            raise DiagnosticDesignError(
                f"Principle content digest mismatch: {principle_id}"
            )
        principles.append(principle)
    principle_links = {
        principle_id: tuple(
            sorted(
                {
                    link.evidence_id
                    for link in evaluation.dimension_principle_links
                    if link.principle_id == principle_id
                }
            )
        )
        for principle_id in evaluation.reviewed_principle_ids
    }
    principle_dimensions = {
        principle_id: tuple(
            sorted(
                {
                    link.dimension
                    for link in evaluation.dimension_principle_links
                    if link.principle_id == principle_id
                }
            )
        )
        for principle_id in evaluation.reviewed_principle_ids
    }
    unbound_family_evidence = set(family.evidence_ids).difference(referenced_ids)
    if unbound_family_evidence:
        raise DiagnosticDesignError(
            "canonical family evidence lacks scored content attestation: "
            + ", ".join(sorted(unbound_family_evidence))
        )
    evidence_ids = tuple(sorted(referenced_ids))
    return tuple(principles), evidence_ids, principle_links, principle_dimensions


def _optimization_plans(
    family_id: str,
    plan_digest: str,
    records: Sequence[DiagnosticRecord],
) -> tuple[OptimizationPlan, ...]:
    return tuple(
        OptimizationPlan(
            optimization_id=f"OPT-{family_id}-{index}",
            family_id=family_id,
            diagnostic_success_record_id=record.record_id,
            plan_digest=plan_digest,
            objective="Improve confirmed target-product yield without changing identity.",
            variables=("temperature_state", "concentration_state", "time_state"),
        )
        for index, record in enumerate(records, start=1)
        if isinstance(record, DiagnosticSuccessRecord)
    )


def record_diagnostic_result(
    plan: FamilyDiagnosticPlan,
    result: ExecutionResultInput,
) -> DiagnosticRecord:
    """Validate one execution result and return an attested diagnostic record."""

    verify_family_diagnostic_plan(plan)
    if not plan.chemistry_planned or not plan.executable:
        raise DiagnosticDesignError("diagnostic result requires an executable plan")
    if result.family_id != plan.family_id or result.plan_digest != plan.plan_digest:
        raise DiagnosticDesignError("execution result does not match exact plan digest")
    if result.representative_id not in {
        representative.representative_id for representative in plan.representatives
    }:
        raise DiagnosticDesignError("execution result cites an unknown representative")
    if result.condition_id not in {condition.state_id for condition in plan.conditions}:
        raise DiagnosticDesignError("execution result cites an unknown condition")
    assert plan.analytics is not None
    target = result.target_analyte.strip().casefold()
    if (
        not target
        or "fluoride" in target
        or target != plan.analytics.required_target_analyte.casefold()
        or result.target_product_method not in plan.analytics.target_product_methods
        or not result.target_product_readout.strip()
    ):
        raise DiagnosticDesignError(
            "target product identity, method, and readout are required; fluoride alone is insufficient"
        )
    if (
        not result.mass_balance_readout.strip()
        or set(result.falsification_observations_checked)
        != set(plan.analytics.falsifying_observations)
    ):
        raise DiagnosticDesignError(
            "result requires mass balance, competing products, and falsification observations"
        )
    planned_competing_ids = {
        measurement.measurement_id
        for measurement in plan.analytics.competing_product_measurements
    }
    if (
        set(result.competing_product_readouts) != planned_competing_ids
        or any(
            not readout.strip()
            for readout in result.competing_product_readouts.values()
        )
    ):
        raise DiagnosticDesignError(
            "competing-product readouts must exactly match planned measurement IDs"
        )
    if plan.plan_role == "negative_control" and result.target_product_confirmed:
        record_type: type[_ExecutionRecord] = BoundaryFalsificationRecord
        prefix = "BOUNDARY-FALSIFICATION"
    elif result.target_product_confirmed and plan.plan_role == "diagnostic":
        record_type = DiagnosticSuccessRecord
        prefix = "SUCCESS"
    else:
        record_type = DiagnosticFailureRecord
        prefix = "FAILURE"
    record = _build_record(
        record_type,
        record_id=f"{prefix}-{result.result_id}",
        family_id=result.family_id,
        plan_digest=result.plan_digest,
        representative_id=result.representative_id,
        condition_id=result.condition_id,
        target_analyte=result.target_analyte,
        target_product_method=result.target_product_method,
        target_product_readout=result.target_product_readout,
        mass_balance_readout=result.mass_balance_readout,
        competing_product_readouts=result.competing_product_readouts,
        falsification_observations_checked=result.falsification_observations_checked,
        run_artifact_digest=result.run_artifact_digest,
        result_artifact_digest=result.result_artifact_digest,
    )
    assert isinstance(
        record,
        (DiagnosticSuccessRecord, DiagnosticFailureRecord, BoundaryFalsificationRecord),
    )
    return record


def design_family_diagnostics(
    families: Sequence[CanonicalFamily],
    evaluations: Sequence[ScoredFamilyEvaluation],
    principles: Sequence[ReactionPrinciple],
    evidence: Sequence[QualifiedEvidenceRecord],
    ranking_analysis: RankingAnalysis | None = None,
    *,
    proposals: Sequence[DiagnosticDesignProposal] = (),
    diagnostic_records: Sequence[DiagnosticRecord] = (),
    diagnostic_success_records: Sequence[DiagnosticSuccessRecord] = (),
    inventory_records: Sequence[RepresentativeInventoryRecord] = (),
    readiness_records: Sequence[RepresentativeReadinessRecord] = (),
    rubric: EvaluationRubric | None = None,
) -> tuple[FamilyDiagnosticPlan, ...]:
    """Design family diagnostics from exact attested v3 inputs."""

    if diagnostic_records and diagnostic_success_records:
        raise DiagnosticDesignError("provide diagnostic records through one input")
    supplied_records: tuple[DiagnosticRecord, ...] = tuple(
        diagnostic_records or diagnostic_success_records
    )
    family_by_id = _unique_by_id(families, "family_id", "canonical family")
    evaluation_by_id = _unique_by_id(evaluations, "family_id", "evaluation")
    if set(family_by_id) != set(evaluation_by_id):
        raise DiagnosticDesignError(
            "evaluation family IDs must exactly match canonical family IDs"
        )
    if any(not isinstance(family, CanonicalFamily) for family in families):
        raise DiagnosticDesignError("diagnostic design requires CanonicalFamily inputs")
    if any(not isinstance(principle, ReactionPrinciple) for principle in principles):
        raise DiagnosticDesignError("diagnostic design requires ReactionPrinciple inputs")
    if any(
        principle.status not in {"accepted", "revised"}
        or principle.review_status not in {"accepted", "revised"}
        for principle in principles
    ):
        raise DiagnosticDesignError("diagnostic design requires reviewed Principles")
    if any(not isinstance(item, QualifiedEvidenceRecord) for item in evidence):
        raise DiagnosticDesignError("diagnostic design requires qualified evidence")
    if any(not isinstance(item, DiagnosticDesignProposal) for item in proposals):
        raise DiagnosticDesignError("diagnostic proposal contract is required")
    if any(
        not isinstance(item, RepresentativeInventoryRecord)
        for item in inventory_records
    ):
        raise DiagnosticDesignError(
            "representative inventory requires factory-attested records"
        )
    if any(
        not isinstance(item, RepresentativeReadinessRecord)
        for item in readiness_records
    ):
        raise DiagnosticDesignError(
            "representative readiness requires factory-attested records"
        )
    readiness_content_by_verification_id: dict[str, str] = {}
    for record in readiness_records:
        _verify_readiness_attestation(record)
        existing_content = readiness_content_by_verification_id.get(
            record.verification_id
        )
        if (
            existing_content is not None
            and existing_content != record.content_digest
        ):
            raise DiagnosticDesignError(
                "representative readiness verification ID collision"
            )
        readiness_content_by_verification_id[record.verification_id] = (
            record.content_digest
        )
    trusted_rubric = rubric or load_evaluation_rubric()
    regions, ranking_bases, _ = _verify_trust_chain(
        evaluations, ranking_analysis, trusted_rubric
    )
    evidence_by_id = _unique_by_id(evidence, "evidence_id", "evidence")
    principle_by_id = _unique_by_id(principles, "principle_id", "Principle")
    proposal_by_id = _unique_by_id(proposals, "family_id", "diagnostic proposal")
    if not set(proposal_by_id).issubset(family_by_id):
        raise DiagnosticDesignError("diagnostic proposal cites an unknown family")
    records_by_family = {
        family_id: tuple(
            record for record in supplied_records if record.family_id == family_id
        )
        for family_id in family_by_id
    }
    if sum(len(items) for items in records_by_family.values()) != len(supplied_records):
        raise DiagnosticDesignError("diagnostic record cites an unknown family")
    readiness_by_family = {
        family_id: tuple(
            record for record in readiness_records if record.family_id == family_id
        )
        for family_id in family_by_id
    }
    if sum(len(items) for items in readiness_by_family.values()) != len(
        readiness_records
    ):
        raise DiagnosticDesignError("readiness record cites an unknown family")
    inventory_by_family = {
        family_id: tuple(
            record for record in inventory_records if record.family_id == family_id
        )
        for family_id in family_by_id
    }
    if sum(len(items) for items in inventory_by_family.values()) != len(
        inventory_records
    ):
        raise DiagnosticDesignError("inventory record cites an unknown family")
    ordered_ids = sorted(
        family_by_id,
        key=lambda family_id: (
            ranking_bases.get(family_id) is None,
            (
                ranking_bases[family_id].primary_rank
                if ranking_bases.get(family_id)
                and ranking_bases[family_id].primary_rank is not None
                else 10**9
            ),
            family_id,
        ),
    )
    plans: list[FamilyDiagnosticPlan] = []
    for family_id in ordered_ids:
        family = family_by_id[family_id]
        evaluation = evaluation_by_id[family_id]
        assert isinstance(family, CanonicalFamily)
        assert isinstance(evaluation, ScoredFamilyEvaluation)
        region = regions[family_id]
        if region in {"excluded", "unknown"}:
            _, evidence_ids, principle_links, _ = _evaluation_provenance(
                family,
                evaluation,
                evidence_by_id,
                principle_by_id,
                require_principles=False,
            )
            common = dict(
                family_id=family_id,
                priority_region=region,
                chemistry_planned=False,
                executable=False,
                representatives=(),
                conditions=(),
                paired_controls=(),
                analytics=None,
                operational_actions=(),
                negative_control_label=None,
                supporting_principle_ids=evaluation.reviewed_principle_ids,
                principle_evidence_links=principle_links,
                evidence_ids=evidence_ids,
                ranking_basis=None,
                diagnostic_records=(),
                optimization_plans=(),
            )
            if region == "excluded":
                plans.append(
                    _build_plan(
                        **common,
                        plan_role="no_experiment",
                        expected_outcome="not_applicable",
                        pre_chemistry_actions=(),
                        no_experiment_rationale=(
                            "Qualified blocker excludes chemistry execution: "
                            + ", ".join(evaluation.qualified_blocker_ids)
                        ),
                    )
                )
            else:
                plans.append(
                    _build_plan(
                        **common,
                        plan_role="evidence_first",
                        expected_outcome="unresolved",
                        pre_chemistry_actions=_pre_chemistry_actions(family, evaluation),
                        no_experiment_rationale=(
                            "Chemistry is gated until critical unknowns are resolved."
                        ),
                    )
                )
            continue
        (
            family_principles,
            evidence_ids,
            principle_links,
            principle_dimensions,
        ) = _evaluation_provenance(
            family, evaluation, evidence_by_id, principle_by_id
        )
        proposal = proposal_by_id.get(family_id)
        assert proposal is None or isinstance(proposal, DiagnosticDesignProposal)
        representatives = _representatives(
            family,
            evidence_ids,
            proposal,
            inventory_by_family[family_id],
            readiness_by_family[family_id],
        )
        conditions = _conditions(
            family, family_principles, principle_dimensions, proposal
        )
        changed_fields = _single_changed_factor(conditions[0], conditions[1])
        paired = PairedControl(
            control_id=f"PAIR-{family_id}-{changed_fields[0].upper()}",
            baseline=conditions[0],
            comparison=conditions[1],
            changed_fields=changed_fields,
            mechanistic_question=(
                f"Does changing only {changed_fields[0]} alter target-product formation?"
            ),
        )
        records = records_by_family[family_id]
        base_actions = _operational_actions(representatives, ())
        executable = not base_actions
        base_data = dict(
            family_id=family_id,
            priority_region=region,
            plan_role="negative_control" if region == "boundary" else "diagnostic",
            expected_outcome=(
                "target_product_absent"
                if region == "boundary"
                else "target_product_present"
            ),
            chemistry_planned=True,
            executable=executable,
            representatives=representatives,
            conditions=conditions,
            paired_controls=(paired,),
            analytics=_analytics(family),
            pre_chemistry_actions=(),
            operational_actions=base_actions,
            negative_control_label=(
                "Boundary-family negative control; target product is expected absent."
                if region == "boundary"
                else None
            ),
            no_experiment_rationale=None,
            supporting_principle_ids=tuple(
                principle.principle_id for principle in family_principles
            ),
            principle_evidence_links=principle_links,
            evidence_ids=evidence_ids,
            ranking_basis=ranking_bases[family_id],
            diagnostic_records=(),
            optimization_plans=(),
        )
        core_plan = _build_plan(**base_data)
        for record in records:
            _verify_record(record, core_plan.plan_digest)
            if record.family_id != family_id:
                raise DiagnosticDesignError("diagnostic record family mismatch")
            if region == "boundary" and isinstance(record, DiagnosticSuccessRecord):
                raise DiagnosticDesignError(
                    "boundary family cannot follow positive optimization path"
                )
            if region != "boundary" and isinstance(
                record, BoundaryFalsificationRecord
            ):
                raise DiagnosticDesignError("boundary falsification family mismatch")
        final_actions = _operational_actions(representatives, records)
        optimizations = (
            ()
            if region == "boundary"
            else _optimization_plans(family_id, core_plan.plan_digest, records)
        )
        plans.append(
            _build_plan(
                **{
                    **base_data,
                    "operational_actions": final_actions,
                    "diagnostic_records": records,
                    "optimization_plans": optimizations,
                }
            )
        )
    return tuple(plans)

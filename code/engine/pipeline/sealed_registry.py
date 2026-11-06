"""Sealed validation registry access gated by Task 11 chain verification."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, ValidationError, field_validator, model_validator

from pipeline.leakage_audit import (
    LeakageAuditError,
    LeakagePolicy,
    StructureFingerprintFactory,
    StructureFingerprintReceipt,
    derive_structure_fingerprint_receipt,
    verify_policy_structure_factory,
    verify_structure_fingerprint_receipt,
)
from pipeline.principle_models import FrozenStrictModel
from pipeline.v3_freeze import verify_freeze_chain


class RevealGateError(RuntimeError):
    """Raised when a caller attempts to access unavailable sealed outcomes."""


class RegistryCommitment(FrozenStrictModel):
    """Public, non-revealing metadata for a hidden registry."""

    version: str = Field(min_length=1)
    record_count: int = Field(ge=1)
    commitment: str = Field(pattern=r"^[0-9a-f]{64}$")
    registry_locator: str | None = None
    created_at: str | None = None

    @field_validator("commitment")
    @classmethod
    def reject_uninitialized_commitment(cls, value: str) -> str:
        if value == "0" * 64:
            raise ValueError("uninitialized registry commitment is forbidden")
        return value


class RevealAuthorization(FrozenStrictModel):
    """Inputs that are reverified immediately before registry plaintext is read."""

    root: Path | None = None
    trusted_freeze_three_digest: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    leakage_policy: LeakagePolicy | None = None
    registry_salt: bytes | None = None
    reveal_decision: Literal["reveal"] | None = None
    expected_structure_factory: StructureFingerprintFactory | None = Field(
        default=None, exclude=True
    )


class RevealedMechanisticDefinition(FrozenStrictModel):
    nucleophilic_center: str = Field(min_length=1)
    reactive_state: str = Field(min_length=1)
    bond_forming_mode: str = Field(min_length=1)
    activation_mode: str = Field(min_length=1)


class RevealedConditionState(FrozenStrictModel):
    protonation_state: str = Field(min_length=1)
    catalyst_state: str = Field(min_length=1)
    medium_state: str = Field(min_length=1)
    temperature_state: str = Field(min_length=1)
    concentration_state: str = Field(min_length=1)
    atmosphere_state: str = Field(min_length=1)
    time_state: str = Field(min_length=1)


class SealedValidationRecordInput(FrozenStrictModel):
    """Plaintext-bearing input accepted only by the sealed registry factory."""

    record_id: str = Field(min_length=1)
    terms: tuple[str, ...] = Field(min_length=1)
    structure_inputs: tuple[str, ...] = Field(min_length=1)
    mechanistic_definition: RevealedMechanisticDefinition
    conditions: RevealedConditionState | None = None
    outcome: Literal["disclosed_success", "confirmed_failure", "unknown"]
    evidence_ids: tuple[str, ...] = Field(min_length=1)
    evidence_basis: Literal[
        "traceable_experiment", "traceable_literature", "model_inference", "unknown"
    ]
    observed_failure_modes: tuple[str, ...] = ()


class SealedValidationRecord(FrozenStrictModel):
    record_id: str = Field(min_length=1)
    terms: tuple[str, ...] = Field(min_length=1)
    structure_hashes: tuple[str, ...] = ()
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
    structure_fingerprint_receipts: tuple[StructureFingerprintReceipt, ...] = ()
    mechanistic_definition: RevealedMechanisticDefinition | None = None
    conditions: RevealedConditionState | None = None
    outcome: Literal["disclosed_success", "confirmed_failure", "unknown"] = "unknown"
    evidence_ids: tuple[str, ...] = ()
    evidence_basis: Literal[
        "traceable_experiment", "traceable_literature", "model_inference", "unknown"
    ] = "unknown"
    observed_failure_modes: tuple[str, ...] = ()

    @field_validator("structure_hashes")
    @classmethod
    def validate_structure_hashes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("structure hashes must be unique")
        if any(
            len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
            for value in values
        ):
            raise ValueError("structure hashes must be SHA-256 hex strings")
        return values

    @model_validator(mode="after")
    def require_evidence_for_disclosed_outcomes(self) -> "SealedValidationRecord":
        if self.outcome != "unknown" and not self.evidence_ids:
            raise ValueError("disclosed outcome requires traceable evidence IDs")
        if self.outcome != "unknown" and self.evidence_basis not in {
            "traceable_experiment",
            "traceable_literature",
        }:
            raise ValueError("model inference cannot establish a disclosed outcome")
        if self.structure_hashes:
            if not self.structure_fingerprint_receipts:
                raise ValueError("structure fingerprint receipt is required")
            if tuple(
                receipt.fingerprint for receipt in self.structure_fingerprint_receipts
            ) != self.structure_hashes:
                raise ValueError("structure hashes must match fingerprint receipts")
            identities = {
                (
                    receipt.factory_id,
                    receipt.canonicalizer_id,
                    receipt.canonicalizer_spec,
                    receipt.canonicalizer_version,
                    receipt.engine_version,
                    receipt.dependency_identity,
                    receipt.canonicalization_parameter_digest,
                    receipt.implementation_digest,
                    receipt.key_commitment,
                )
                for receipt in self.structure_fingerprint_receipts
            }
            expected = (
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
            if identities != {expected}:
                raise ValueError("structure fingerprint factory identity mismatch")
        return self


class SealedValidationRegistry(FrozenStrictModel):
    version: str = Field(min_length=1)
    records: tuple[SealedValidationRecord, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def require_unique_records(self) -> "SealedValidationRegistry":
        record_ids = tuple(record.record_id for record in self.records)
        if len(record_ids) != len(set(record_ids)):
            raise ValueError("duplicate revealed registry record ID")
        return self


def _record_count(registry_bytes: bytes) -> int:
    try:
        raw = yaml.safe_load(registry_bytes)
    except yaml.YAMLError:
        return 1
    if isinstance(raw, Mapping) and isinstance(raw.get("records"), list):
        return max(1, len(raw["records"]))
    return 1


def create_registry_commitment(registry_bytes: bytes, salt: bytes) -> RegistryCommitment:
    """Return a salted SHA-256 commitment without exposing registry contents."""

    if not salt:
        raise ValueError("registry commitment requires a non-empty salt")
    return RegistryCommitment(
        version="1.0",
        record_count=_record_count(registry_bytes),
        commitment=hashlib.sha256(salt + registry_bytes).hexdigest(),
    )


def create_sealed_validation_registry(
    version: str,
    records: tuple[SealedValidationRecordInput, ...],
    structure_factory: StructureFingerprintFactory,
) -> SealedValidationRegistry:
    """Derive persisted hashes and receipts without retaining structure plaintext."""

    sealed: list[SealedValidationRecord] = []
    for item in records:
        receipts = tuple(
            derive_structure_fingerprint_receipt(
                structure_factory, item.record_id, structure_input
            )
            for structure_input in item.structure_inputs
        )
        sealed.append(
            SealedValidationRecord(
                record_id=item.record_id,
                terms=item.terms,
                structure_hashes=tuple(receipt.fingerprint for receipt in receipts),
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
                structure_fingerprint_receipts=receipts,
                mechanistic_definition=item.mechanistic_definition,
                conditions=item.conditions,
                outcome=item.outcome,
                evidence_ids=item.evidence_ids,
                evidence_basis=item.evidence_basis,
                observed_failure_modes=item.observed_failure_modes,
            )
        )
    return SealedValidationRegistry(version=version, records=tuple(sealed))


def load_public_commitment(path: Path) -> RegistryCommitment:
    """Load public metadata while rejecting embedded sealed content or placeholders."""

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise RevealGateError("unable to load public registry commitment") from exc
    if not isinstance(raw, Mapping):
        raise RevealGateError("public registry commitment must be a mapping")
    forbidden = {"records", "terms", "synonyms", "structures", "outcomes", "conditions"}
    if forbidden & set(raw):
        raise RevealGateError("public registry commitment contains sealed content fields")
    try:
        return RegistryCommitment.model_validate(raw)
    except ValidationError as exc:
        if "uninitialized registry commitment" in str(exc):
            raise RevealGateError("uninitialized registry commitment is forbidden") from exc
        raise RevealGateError("invalid public registry commitment") from exc


def build_public_commitment(
    registry_path: Path,
    destination: Path,
    *,
    salt: bytes,
    registry_locator: str,
    created_at: str,
) -> RegistryCommitment:
    """Locally derive public metadata from private registry bytes only."""

    try:
        registry_bytes = registry_path.read_bytes()
    except OSError as exc:
        raise RevealGateError("sealed registry cannot be read") from exc
    commitment = create_registry_commitment(registry_bytes, salt).model_copy(
        update={"registry_locator": registry_locator, "created_at": created_at}
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            yaml.safe_dump(
                commitment.model_dump(mode="json"), sort_keys=True, allow_unicode=False
            ),
            encoding="utf-8",
        )
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return commitment


def authorize_registry_reveal(
    root: Path,
    trusted_freeze_three_digest: str,
    leakage_policy: LeakagePolicy,
    registry_salt: bytes,
    reveal_decision: Literal["reveal"] | None,
    expected_structure_factory: StructureFingerprintFactory | None = None,
) -> RevealAuthorization:
    """Create reveal inputs only after Task 11 verifies an external Freeze 3 anchor."""

    if reveal_decision != "reveal":
        raise RevealGateError("a separate explicit reveal decision is required")
    if not registry_salt:
        raise RevealGateError("registry commitment salt is required after Freeze 3")
    try:
        verify_policy_structure_factory(leakage_policy, expected_structure_factory)
    except LeakageAuditError as exc:
        raise RevealGateError(str(exc)) from exc
    verification = verify_freeze_chain(root, trusted_freeze_three_digest, leakage_policy)
    if (
        not verification.valid
        or verification.verified_stages != ("Freeze 1", "Freeze 2", "Freeze 3")
        or verification.manifest_digests.get("Freeze 3")
        != trusted_freeze_three_digest
    ):
        raise RevealGateError("trusted Freeze 3 chain verification failed")
    return RevealAuthorization(
        root=root,
        trusted_freeze_three_digest=trusted_freeze_three_digest,
        leakage_policy=leakage_policy,
        registry_salt=registry_salt,
        reveal_decision="reveal",
        expected_structure_factory=expected_structure_factory,
    )


def reveal_registry(path: Path, authorization: RevealAuthorization) -> SealedValidationRegistry:
    """Reveal a commitment-matched registry after rechecking the trusted chain."""

    if (
        type(authorization) is not RevealAuthorization
        or authorization.root is None
        or authorization.trusted_freeze_three_digest is None
        or authorization.leakage_policy is None
        or authorization.registry_salt is None
        or authorization.reveal_decision != "reveal"
        or authorization.expected_structure_factory is None
    ):
        raise RevealGateError("trusted Freeze 3 chain verification unavailable")
    verified = authorize_registry_reveal(
        authorization.root,
        authorization.trusted_freeze_three_digest,
        authorization.leakage_policy,
        authorization.registry_salt,
        authorization.reveal_decision,
        authorization.expected_structure_factory,
    )
    try:
        from pipeline.v3_freeze import _read_manifest

        manifest, snapshot = _read_manifest(verified.root, "Freeze 3")
    except (OSError, ValueError, TypeError) as exc:
        raise RevealGateError("trusted Freeze 3 manifest cannot be read") from exc
    if snapshot.digest != verified.trusted_freeze_three_digest:
        raise RevealGateError("trusted Freeze 3 digest mismatch")
    try:
        registry_bytes = path.read_bytes()
    except OSError as exc:
        raise RevealGateError("sealed registry cannot be read") from exc
    commitment = create_registry_commitment(registry_bytes, verified.registry_salt)
    if commitment.commitment != manifest.hidden_registry_commitment:
        raise RevealGateError("sealed registry commitment does not match Freeze 3 manifest")
    try:
        raw = yaml.safe_load(registry_bytes)
        registry = SealedValidationRegistry.model_validate(raw)
    except (ValidationError, yaml.YAMLError) as exc:
        if "duplicate revealed registry record ID" in str(exc):
            raise RevealGateError("duplicate revealed registry record ID") from exc
        if "fingerprint receipt" in str(exc):
            raise RevealGateError("structure fingerprint receipt is invalid") from exc
        raise RevealGateError("sealed registry has invalid content") from exc
    factory = authorization.expected_structure_factory
    for record in registry.records:
        record_factory_identity = (
            record.structure_fingerprint_factory_id,
            record.structure_canonicalizer_id,
            record.structure_canonicalizer_spec,
            record.structure_canonicalizer_version,
            record.structure_engine_version,
            record.structure_dependency_identity,
            record.structure_canonicalization_parameter_digest,
            record.structure_factory_implementation_digest,
            record.structure_factory_key_commitment,
        )
        expected_factory_identity = (
            factory.factory_id,
            factory.canonicalizer_id,
            factory.canonicalizer_spec,
            factory.canonicalizer_version,
            factory.engine_version,
            factory.dependency_identity,
            factory.canonicalization_parameter_digest,
            factory.implementation_digest,
            factory.key_commitment,
        )
        if record_factory_identity != expected_factory_identity:
            raise RevealGateError("sealed registry fingerprint factory mismatch")
        try:
            for receipt in record.structure_fingerprint_receipts:
                verify_structure_fingerprint_receipt(
                    factory, record.record_id, receipt
                )
        except ValueError as exc:
            raise RevealGateError("structure fingerprint receipt is invalid") from exc
    return registry

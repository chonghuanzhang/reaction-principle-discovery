"""Versioned normalization contract for imported Seed evidence claim types."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, ValidationError, field_serializer, model_validator

from pipeline.models import ReviewerStatus
from pipeline.principle_models import EvidenceRef, FrozenStrictModel, SeedEvidence


ControlledSeedClaimType = Literal[
    "reaction_center",
    "reactive_intermediate",
    "electronic_requirement",
    "nucleophile_requirement",
    "catalyst_role",
    "condition_window",
    "selectivity",
    "failure_boundary",
]

DEFAULT_SEED_CLAIM_TYPE_CONFIG_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "seed_claim_types_v3.yaml"
)
SEED_CLAIM_TYPE_CONTRACT_PATH = "config/seed_claim_types_v3.yaml"
SEED_CLAIM_TYPE_CONTRACT_ARTIFACT_KEY = "seed_claim_type_contract"
SEED_EVIDENCE_PROJECTION_PATH = (
    "derived/principles_v3/seed_evidence_projection.json"
)


class SeedClaimTypeError(ValueError):
    """Raised when the Seed claim normalization contract cannot be applied."""


class SeedClaimTypeContract(FrozenStrictModel):
    version: Literal["1.1"]
    raw_type_hash_mapping: Mapping[str, ControlledSeedClaimType]

    @model_validator(mode="after")
    def validate_mapping(self) -> "SeedClaimTypeContract":
        if not self.raw_type_hash_mapping or any(
            len(raw_type_hash) != 64
            or set(raw_type_hash) - set("0123456789abcdef")
            for raw_type_hash in self.raw_type_hash_mapping
        ):
            raise ValueError("raw Seed claim type keys must be SHA-256 digests")
        return self

    @field_serializer("raw_type_hash_mapping")
    def serialize_mapping(
        self, value: Mapping[str, ControlledSeedClaimType]
    ) -> dict[str, ControlledSeedClaimType]:
        return dict(sorted(value.items()))


class SeedEvidenceProjectionProvenance(FrozenStrictModel):
    raw_evidence_type: str = Field(min_length=1)


class NormalizedSeedEvidence(FrozenStrictModel):
    evidence: EvidenceRef
    claim: str = Field(min_length=1)
    normalized_claim_type: ControlledSeedClaimType
    reviewer_status: ReviewerStatus
    provenance: SeedEvidenceProjectionProvenance


class SeedEvidenceProjection(FrozenStrictModel):
    version: Literal["3.0"]
    claim_type_contract_version: Literal["1.1"]
    claim_type_contract_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_path: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    seed_evidence: tuple[NormalizedSeedEvidence, ...] = Field(min_length=1)


def seed_claim_type_contract_digest(contract: SeedClaimTypeContract) -> str:
    encoded = json.dumps(
        contract.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def raw_seed_claim_type_digest(value: str) -> str:
    normalized = " ".join(
        unicodedata.normalize("NFKC", value).casefold().split()
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def load_seed_claim_type_contract(
    path: Path | None = None,
) -> SeedClaimTypeContract:
    source = path or DEFAULT_SEED_CLAIM_TYPE_CONFIG_PATH
    try:
        raw = source.read_bytes()
    except OSError as exc:
        raise SeedClaimTypeError(
            f"cannot load Seed claim type contract: {source}"
        ) from exc
    return parse_seed_claim_type_contract(raw)


def parse_seed_claim_type_contract(raw: bytes) -> SeedClaimTypeContract:
    try:
        payload = yaml.safe_load(raw.decode("utf-8"))
        return SeedClaimTypeContract.model_validate(payload)
    except (UnicodeDecodeError, ValidationError, yaml.YAMLError) as exc:
        raise SeedClaimTypeError("invalid Seed claim type contract") from exc


def project_seed_evidence(
    seeds: Sequence[SeedEvidence],
    *,
    source_path: str,
    source_sha256: str,
    contract: SeedClaimTypeContract,
) -> SeedEvidenceProjection:
    normalized: list[NormalizedSeedEvidence] = []
    for seed in seeds:
        raw_type_digest = raw_seed_claim_type_digest(seed.evidence_type)
        claim_type = contract.raw_type_hash_mapping.get(raw_type_digest)
        if claim_type is None:
            raise SeedClaimTypeError(
                f"unknown Seed claim type digest: {raw_type_digest}"
            )
        normalized.append(
            NormalizedSeedEvidence(
                evidence=seed.evidence,
                claim=seed.claim,
                normalized_claim_type=claim_type,
                reviewer_status=seed.reviewer_status,
                provenance=SeedEvidenceProjectionProvenance(
                    raw_evidence_type=seed.evidence_type
                ),
            )
        )
    return SeedEvidenceProjection(
        version="3.0",
        claim_type_contract_version=contract.version,
        claim_type_contract_digest=seed_claim_type_contract_digest(contract),
        source_path=source_path,
        source_sha256=source_sha256,
        seed_evidence=tuple(normalized),
    )

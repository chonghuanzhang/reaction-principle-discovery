"""Strict one-paper semantic Knowledge Transfer model stage."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from pipeline.api_client import ApiResult
from pipeline.evidence_registry import _atomic_json
from pipeline.paper_mechanism_bundles import PaperMechanismBundle
from pipeline.principle_models import SeedMechanism


TransferDimension = Literal[
    "shared_elementary_step",
    "electrophile_electronic_compatibility",
    "nucleophile_reactive_form",
    "catalyst_ligand_compatibility",
    "condition_overlap",
    "selective_defluorination",
    "product_stability",
    "competing_pathways",
]
TransferJudgment = Literal["match", "mismatch", "conditional", "unknown"]

TRANSFER_DIMENSIONS: tuple[TransferDimension, ...] = (
    "shared_elementary_step",
    "electrophile_electronic_compatibility",
    "nucleophile_reactive_form",
    "catalyst_ligand_compatibility",
    "condition_overlap",
    "selective_defluorination",
    "product_stability",
    "competing_pathways",
)


class StructuredClient(Protocol):
    def create_structured(
        self, model: str, input_text: str, schema: dict, schema_name: str
    ) -> ApiResult: ...


class ModelSemanticTransferError(RuntimeError):
    """Raised when a semantic transfer proposal is invalid or ungrounded."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TransferComponentProposal(StrictModel):
    dimension: TransferDimension
    judgment: TransferJudgment
    rationale: str = Field(min_length=1)
    seed_evidence_ids: tuple[str, ...]
    literature_evidence_ids: tuple[str, ...]


class MechanismTransferProposal(StrictModel):
    mechanism_id: str = Field(min_length=1)
    components: tuple[TransferComponentProposal, ...] = Field(min_length=8, max_length=8)
    hard_blocker_constraint_ids: tuple[str, ...]
    conditions: tuple[str, ...]
    uncertainty: tuple[str, ...]
    transferable_claim: str = Field(min_length=1)
    falsifying_test: str = Field(min_length=1)


class PaperTransferProposal(StrictModel):
    mechanisms: tuple[MechanismTransferProposal, ...]


class PaperTransferResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["validated", "reused"]
    cache_key: str
    namespace: str
    source_path: str
    proposals: tuple[MechanismTransferProposal, ...]
    usage: dict[str, int | None]


def _require_all_properties(node: object) -> None:
    if isinstance(node, dict):
        properties = node.get("properties")
        if isinstance(properties, dict):
            node["required"] = list(properties)
            node["additionalProperties"] = False
        for value in node.values():
            _require_all_properties(value)
    elif isinstance(node, list):
        for value in node:
            _require_all_properties(value)


def semantic_transfer_schema() -> dict:
    schema = PaperTransferProposal.model_json_schema()
    _require_all_properties(schema)
    return schema


def build_semantic_transfer_input(
    seed: SeedMechanism, bundle: PaperMechanismBundle, prompt_text: str
) -> str:
    """Build an allowlisted Seed-plus-one-paper transfer prompt."""

    contract = {
        "dimensions": list(TRANSFER_DIMENSIONS),
        "judgments": ["match", "mismatch", "conditional", "unknown"],
        "rules": [
            "Assess every mechanism exactly once.",
            "Use only supplied Seed and same-paper qualified evidence IDs.",
            "A hard blocker must cite an explicit same-paper incompatible constraint.",
            "Preserve unknowns and distinguish condition-specific failure from intrinsic incompatibility.",
            "Do not assign final transfer status, numeric score, review state, or freeze state.",
        ],
    }
    bundle_payload = {
        "namespace": bundle.namespace,
        "source_path": bundle.source_path,
        "mechanisms": [item.model_dump(mode="json") for item in bundle.mechanisms],
        "constraints": [item.model_dump(mode="json") for item in bundle.constraints],
        "evidence_ids": list(bundle.evidence_ids),
    }
    return (
        f"{prompt_text.strip()}\n\n"
        "BEGIN_TRANSFER_CONTRACT\n"
        f"{json.dumps(contract, ensure_ascii=False, sort_keys=True)}\n"
        "END_TRANSFER_CONTRACT\n\n"
        "BEGIN_SEED_MECHANISM\n"
        f"{seed.model_dump_json()}\n"
        "END_SEED_MECHANISM\n\n"
        "BEGIN_ONE_PAPER_MECHANISM_BUNDLE\n"
        f"{json.dumps(bundle_payload, ensure_ascii=False, sort_keys=True)}\n"
        "END_ONE_PAPER_MECHANISM_BUNDLE\n"
    )


def _cache_key(seed: SeedMechanism, bundle: PaperMechanismBundle, config: dict) -> str:
    material = {
        "seed": seed.model_dump(mode="json"),
        "bundle_digest": bundle.bundle_digest,
        "model": config.get("model"),
        "prompt_version": config.get("prompt_version"),
        "rubric_version": config.get("rubric_version"),
        "prompt_text": config.get("prompt_text"),
        "schema": semantic_transfer_schema(),
    }
    encoded = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _validate_proposal(
    payload: PaperTransferProposal,
    seed: SeedMechanism,
    bundle: PaperMechanismBundle,
) -> PaperTransferProposal:
    expected_mechanisms = {item.mechanism_evidence_id for item in bundle.mechanisms}
    observed_mechanisms = [item.mechanism_id for item in payload.mechanisms]
    if len(observed_mechanisms) != len(set(observed_mechanisms)) or set(observed_mechanisms) != expected_mechanisms:
        raise ModelSemanticTransferError("mechanism coverage mismatch")
    known_seed = set(seed.evidence_ids)
    known_literature = set(bundle.evidence_ids)
    constraints = {item.constraint_id: item for item in bundle.constraints}
    required_dimensions = set(TRANSFER_DIMENSIONS)
    validated_proposals: list[MechanismTransferProposal] = []
    for proposal in payload.mechanisms:
        dimensions = [item.dimension for item in proposal.components]
        if len(dimensions) != len(set(dimensions)) or set(dimensions) != required_dimensions:
            raise ModelSemanticTransferError(
                f"component coverage mismatch for {proposal.mechanism_id}"
            )
        for component in proposal.components:
            unknown_seed = set(component.seed_evidence_ids) - known_seed
            unknown_literature = set(component.literature_evidence_ids) - known_literature
            if unknown_seed:
                raise ModelSemanticTransferError(
                    "unknown Seed evidence ID(s): " + ", ".join(sorted(unknown_seed))
                )
            if unknown_literature:
                raise ModelSemanticTransferError(
                    "unknown same-paper evidence ID(s): "
                    + ", ".join(sorted(unknown_literature))
                )
        hard_blockers: list[str] = []
        conditional_concerns: list[str] = []
        for blocker_id in proposal.hard_blocker_constraint_ids:
            constraint = constraints.get(blocker_id)
            if constraint is None:
                raise ModelSemanticTransferError(
                    f"unknown same-paper constraint: {blocker_id}"
                )
            if constraint.direction == "incompatible":
                hard_blockers.append(blocker_id)
            else:
                conditional_concerns.append(
                    "model-nominated non-incompatible constraint retained as a "
                    f"conditional concern: {blocker_id} ({constraint.direction})"
                )
        validated_proposals.append(
            proposal.model_copy(
                update={
                    "hard_blocker_constraint_ids": tuple(hard_blockers),
                    "uncertainty": tuple(
                        dict.fromkeys([*proposal.uncertainty, *conditional_concerns])
                    ),
                }
            )
        )
    return payload.model_copy(update={"mechanisms": tuple(validated_proposals)})


def _load_cached(
    path: Path,
    key: str,
    seed: SeedMechanism,
    bundle: PaperMechanismBundle,
) -> PaperTransferResult | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("cache_key") != key:
            return None
        payload = _validate_proposal(
            PaperTransferProposal.model_validate(value.get("proposal")), seed, bundle
        )
    except (OSError, json.JSONDecodeError, ValidationError, ModelSemanticTransferError):
        return None
    return PaperTransferResult(
        status="reused",
        cache_key=key,
        namespace=bundle.namespace,
        source_path=bundle.source_path,
        proposals=payload.mechanisms,
        usage={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
    )


def propose_paper_transfer(
    seed: SeedMechanism,
    bundle: PaperMechanismBundle,
    client: StructuredClient,
    config: dict,
    cache_root: Path,
) -> PaperTransferResult:
    """Propose and validate semantic transfer judgments for one paper."""

    key = _cache_key(seed, bundle, config)
    paper_root = cache_root.resolve() / bundle.namespace
    validated_path = paper_root / "validated_proposal.json"
    cached = _load_cached(validated_path, key, seed, bundle)
    if cached is not None:
        return cached
    api_result = client.create_structured(
        str(config.get("model", "")),
        build_semantic_transfer_input(seed, bundle, str(config.get("prompt_text", ""))),
        semantic_transfer_schema(),
        "paper_semantic_transfer",
    )
    _atomic_json(
        paper_root / "raw.json",
        {
            "cache_key": key,
            "namespace": bundle.namespace,
            "source_path": bundle.source_path,
            "api": {
                "response_id": api_result.response_id,
                "returned_model": api_result.returned_model,
                "status": api_result.status,
                "usage": asdict(api_result.usage),
            },
            "proposal": api_result.parsed_output,
        },
    )
    try:
        parsed = PaperTransferProposal.model_validate(api_result.parsed_output)
    except ValidationError as exc:
        raise ModelSemanticTransferError(f"invalid semantic transfer schema: {exc}") from exc
    validated = _validate_proposal(parsed, seed, bundle)
    usage = asdict(api_result.usage)
    _atomic_json(
        validated_path,
        {
            "cache_key": key,
            "namespace": bundle.namespace,
            "source_path": bundle.source_path,
            "bundle_digest": bundle.bundle_digest,
            "proposal": validated.model_dump(mode="json"),
            "usage": usage,
        },
    )
    return PaperTransferResult(
        status="validated",
        cache_key=key,
        namespace=bundle.namespace,
        source_path=bundle.source_path,
        proposals=validated.mechanisms,
        usage=usage,
    )

"""Two-stage, provenance-tracked retrieval manifests for full-space discovery."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import Literal

from pydantic import Field, model_validator

from pipeline.literature_retrieval import (
    SearchQuery,
    build_hypothesis_queries,
    build_seed_queries,
)
from pipeline.principle_models import FrozenStrictModel, ReactionPrinciple, SeedMechanism
from pipeline.v3_models import FamilyDefinition


class FullSpaceRetrievalError(ValueError):
    """Raised when staged retrieval provenance or ordering is invalid."""


class RetrievalStageManifest(FrozenStrictModel):
    stage: Literal["seed_mechanism", "taxonomy_hypothesis"]
    predecessor_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    taxonomy_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    queries: tuple[SearchQuery, ...] = Field(min_length=1)
    query_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_stage_metadata(self) -> "RetrievalStageManifest":
        if self.stage == "seed_mechanism" and (self.predecessor_digest or self.taxonomy_digest):
            raise ValueError("seed retrieval cannot have a predecessor or taxonomy")
        if self.stage == "taxonomy_hypothesis" and (not self.predecessor_digest or not self.taxonomy_digest):
            raise ValueError("hypothesis retrieval requires predecessor and frozen taxonomy")
        for query in self.queries:
            if self.stage == "seed_mechanism":
                if query.origin_type != "seed_mechanism" or query.candidate_family_terms:
                    raise ValueError("seed retrieval cannot contain candidate family terms")
            elif (
                query.origin_type != "taxonomy_hypothesis"
                or query.generation_basis != "frozen_open_taxonomy"
                or not query.candidate_family_terms
                or any(term not in query.text for term in query.candidate_family_terms)
            ):
                raise ValueError("hypothesis query must contain frozen taxonomy mechanism terms")
        return self


def _digest(queries: Sequence[SearchQuery]) -> str:
    payload = [query.model_dump(mode="json") for query in queries]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _manifest(
    stage: Literal["seed_mechanism", "taxonomy_hypothesis"],
    queries: tuple[SearchQuery, ...],
    predecessor_digest: str | None = None,
    taxonomy_digest: str | None = None,
) -> RetrievalStageManifest:
    if any(not query.candidate_family_terms for query in queries) != (stage == "seed_mechanism"):
        raise FullSpaceRetrievalError("retrieval query family-term provenance is invalid")
    return RetrievalStageManifest(
        stage=stage,
        predecessor_digest=predecessor_digest,
        taxonomy_digest=taxonomy_digest,
        queries=queries,
        query_digest=_digest(queries),
    )


def build_seed_stage_manifest(
    seed: SeedMechanism, principles: Sequence[ReactionPrinciple]
) -> RetrievalStageManifest:
    queries = tuple(
        query.model_copy(update={"candidate_family_terms": (), "generation_basis": "seed_mechanism"})
        for query in build_seed_queries(seed, principles)
    )
    return _manifest("seed_mechanism", queries)


def build_hypothesis_stage_manifest(
    families: Sequence[FamilyDefinition],
    taxonomy_digest: str | None,
    prior_seed_manifest: RetrievalStageManifest,
) -> RetrievalStageManifest:
    if not families or taxonomy_digest is None:
        raise FullSpaceRetrievalError("hypothesis retrieval requires frozen open taxonomy")
    if prior_seed_manifest.stage != "seed_mechanism":
        raise FullSpaceRetrievalError("hypothesis retrieval requires a seed predecessor")
    if _digest(prior_seed_manifest.queries) != prior_seed_manifest.query_digest:
        raise FullSpaceRetrievalError("seed predecessor digest does not match queries")
    queries = tuple(
        query.model_copy(
            update={
                "candidate_family_terms": (
                    family.nucleophilic_center,
                    family.reactive_state,
                    family.bond_forming_mode,
                    family.activation_mode,
                    *family.critical_conditions,
                    *family.dominant_failure_modes,
                ),
                "generation_basis": "frozen_open_taxonomy",
            }
        )
        for query, family in zip(build_hypothesis_queries(families), families)
    )
    return _manifest(
        "taxonomy_hypothesis", queries, prior_seed_manifest.query_digest, taxonomy_digest
    )


def validate_retrieval_sequence(
    seed_manifest: RetrievalStageManifest | Sequence[RetrievalStageManifest],
    hypothesis_manifest: RetrievalStageManifest | None = None,
) -> None:
    """Validate that hypothesis retrieval follows the exact seed manifest."""
    if hypothesis_manifest is None:
        manifests = tuple(seed_manifest) if not isinstance(seed_manifest, RetrievalStageManifest) else ()
        if len(manifests) != 2:
            raise FullSpaceRetrievalError("retrieval sequence requires seed and hypothesis stages")
        seed_manifest, hypothesis_manifest = manifests
    if not isinstance(seed_manifest, RetrievalStageManifest) or not isinstance(
        hypothesis_manifest, RetrievalStageManifest
    ):
        raise FullSpaceRetrievalError("retrieval sequence contains an invalid manifest")
    if seed_manifest.stage != "seed_mechanism":
        raise FullSpaceRetrievalError("retrieval sequence must start with seed mechanism")
    if hypothesis_manifest.stage != "taxonomy_hypothesis":
        raise FullSpaceRetrievalError("retrieval sequence must end with taxonomy hypothesis")
    if _digest(seed_manifest.queries) != seed_manifest.query_digest:
        raise FullSpaceRetrievalError("seed query digest does not match queries")
    if _digest(hypothesis_manifest.queries) != hypothesis_manifest.query_digest:
        raise FullSpaceRetrievalError("hypothesis query digest does not match queries")
    if hypothesis_manifest.predecessor_digest != seed_manifest.query_digest:
        raise FullSpaceRetrievalError("hypothesis predecessor digest does not match seed digest")

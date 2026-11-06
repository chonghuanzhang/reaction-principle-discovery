"""Strict contracts for answer-isolated full-space v3.6 workflow control."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field

from pipeline.principle_models import FrozenStrictModel


class AnswerIsolationError(RuntimeError):
    """Raised when a model-visible path would expose excluded material."""


class DevelopmentUseMetadata(FrozenStrictModel):
    development_use: Literal["answer_isolated_retrieval"]
    prospective_metric_eligible: Literal[False]
    validation_type: Literal["blinded_reanalysis"]
    target_results_supplied_to_model: Literal[False]


class AnswerIsolationManifest(FrozenStrictModel):
    hidden_registry_commitment: str = Field(pattern=r"^[0-9a-f]{64}$")
    hidden_record_count: int = Field(ge=1)
    excluded_paths: tuple[str, ...] = Field(min_length=1)
    model_visible_input_digests: dict[str, str] = Field(min_length=1)
    metadata: DevelopmentUseMetadata


class FullSpacePhaseState(FrozenStrictModel):
    phase: str = Field(min_length=1)
    predecessor_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    completed_at: str = Field(min_length=1)


def validate_model_visible_paths(
    manifest: AnswerIsolationManifest, paths: tuple[Path, ...] | list[Path]
) -> tuple[Path, ...]:
    excluded = tuple(Path(item).resolve() for item in manifest.excluded_paths)
    resolved = tuple(Path(path).resolve() for path in paths)
    for path in resolved:
        if any(path == root or root in path.parents or path in root.parents for root in excluded):
            raise AnswerIsolationError(f"model-visible path is excluded: {path}")
    return resolved

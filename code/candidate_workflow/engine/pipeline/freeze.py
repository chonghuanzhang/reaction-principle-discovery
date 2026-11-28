"""Immutable human-reviewed Reaction Principle freeze artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Sequence
from pathlib import Path

from pipeline.candidate_ranking import candidate_list_digest
from pipeline.principle_models import (
    ExperimentCandidate,
    FrozenReactionPrincipleSet,
    ReactionPrinciple,
)


class FreezeError(RuntimeError):
    """Raised when a scientific freeze would be incomplete or mutable."""


def freeze_principles(
    principles: list[ReactionPrinciple],
    *,
    source_digest: str,
    scoring_digest: str,
    freeze_version: str,
    destination: Path,
    created_at: str,
) -> FrozenReactionPrincipleSet:
    """Write a new freeze exactly once after explicit human review."""

    if destination.exists():
        raise FreezeError(f"freeze destination already exists: {destination}")
    if not principles:
        raise FreezeError("cannot freeze an empty Principle set")
    not_reviewed = [
        principle.principle_id
        for principle in principles
        if principle.review_status not in {"accepted", "revised"}
        or principle.status not in {"accepted", "revised"}
    ]
    if not_reviewed:
        raise FreezeError(
            "human review is required before freeze: " + ", ".join(sorted(not_reviewed))
        )
    frozen_principles = tuple(
        principle.model_copy(update={"freeze_version": freeze_version}, deep=True)
        for principle in sorted(principles, key=lambda value: value.principle_id)
    )
    frozen = FrozenReactionPrincipleSet(
        freeze_version=freeze_version,
        created_at=created_at,
        source_digest=source_digest,
        scoring_digest=scoring_digest,
        hidden_answers_revealed=False,
        principles=frozen_principles,
    )
    _exclusive_json(destination, frozen.model_dump(mode="json"))
    return frozen


def freeze_candidate_list(
    candidates: Sequence[ExperimentCandidate],
    *,
    frozen_principles: FrozenReactionPrincipleSet,
    frozen_principle_path: Path,
    destination: Path,
) -> tuple[ExperimentCandidate, ...]:
    """Bind a candidate list to immutable Principle and scoring provenance."""

    if destination.exists():
        raise FreezeError(f"candidate freeze destination already exists: {destination}")
    if not candidates:
        raise FreezeError("cannot freeze an empty candidate list")
    if any(candidate.freeze_status != "provisional" for candidate in candidates):
        raise FreezeError("candidate list must be provisional before its first freeze")
    if not frozen_principle_path.is_file():
        raise FreezeError(f"frozen Principle artifact is missing: {frozen_principle_path}")
    stored = FrozenReactionPrincipleSet.model_validate_json(
        frozen_principle_path.read_text(encoding="utf-8")
    )
    if stored != frozen_principles:
        raise FreezeError("frozen Principle artifact does not match supplied Principle set")

    principle_digest = hashlib.sha256(frozen_principle_path.read_bytes()).hexdigest()
    list_digest = candidate_list_digest(candidates)
    frozen = tuple(
        ExperimentCandidate.model_validate(
            {
                **candidate.model_dump(mode="json"),
                "freeze_status": "frozen",
                "freeze_version": frozen_principles.freeze_version,
                "principle_digest": principle_digest,
                "scoring_digest": frozen_principles.scoring_digest,
                "candidate_list_digest": list_digest,
            }
        )
        for candidate in candidates
    )
    payload = {
        "freeze_version": frozen_principles.freeze_version,
        "principle_digest": principle_digest,
        "scoring_digest": frozen_principles.scoring_digest,
        "candidate_list_digest": list_digest,
        "hidden_answers_revealed": False,
        "candidates": [candidate.model_dump(mode="json") for candidate in frozen],
    }
    _exclusive_json(destination, payload)
    return frozen


def _exclusive_json(path: Path, payload: object) -> None:
    """Publish a complete JSON file exactly once, without replacement races."""

    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    _exclusive_text(path, encoded)


def _exclusive_text(path: Path, encoded: str) -> None:
    """Publish complete text exactly once, without replacement races."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
            os.fchmod(handle.fileno(), 0o644)
        try:
            os.link(temporary_path, path)
        except FileExistsError as exc:
            raise FreezeError(f"freeze destination already exists: {path}") from exc
    finally:
        temporary_path.unlink(missing_ok=True)

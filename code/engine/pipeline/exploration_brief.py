"""Validated user intent for staged chemical-space exploration."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


REQUIRED_STUDY_SUPERCLASSES = frozenset(
    {
        "NUC-ORGANOMETALLIC-C",
        "NUC-SOFT-ANIONIC-S",
        "NUC-NEUTRAL-PI-C",
        "NUC-O-C-AMBIDENT",
        "NUC-SULFUR-TRANSFER",
        "NUC-ANIONIC-C",
        "NUC-O",
        "NUC-N",
    }
)


class ExplorationBriefError(ValueError):
    """Raised when the requested chemical-space axis is ambiguous or incomplete."""


class FrozenStrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RoleSpec(FrozenStrictModel):
    role: Literal["electrophile", "nucleophile"]
    label: str = Field(min_length=1)
    seed_reaction_id: str | None = None


class TargetTransformation(FrozenStrictModel):
    product_class: Literal["monofluoroalkene"]
    required_features: tuple[str, ...] = Field(min_length=1)


class SeedInstance(FrozenStrictModel):
    family_id: str = Field(min_length=1)
    role: Literal["nucleophile"]
    status: Literal["observed_seed_instance"]


class NucleophileSuperclass(FrozenStrictModel):
    superclass_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    reactive_form_question: str = Field(min_length=1)
    mapping_terms: tuple[str, ...] = Field(min_length=1)


class ExplorationBrief(FrozenStrictModel):
    version: Literal["2.0"]
    ontology_version: Literal["2.0"]
    stage: Literal[
        "fixed_electrophile_nucleophile_condition",
        "electrophile_family_expansion",
    ]
    fixed_role: RoleSpec
    variable_role: RoleSpec
    target_transformation: TargetTransformation
    seed_instances: tuple[SeedInstance, ...] = Field(min_length=1)
    required_superclasses: tuple[NucleophileSuperclass, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_stage_one_roles(self) -> "ExplorationBrief":
        if self.stage == "fixed_electrophile_nucleophile_condition":
            if (
                self.fixed_role.role != "electrophile"
                or self.variable_role.role != "nucleophile"
            ):
                raise ValueError("Stage 1 must fix electrophile and vary nucleophile")
            if "organoboron" in self.variable_role.label.casefold():
                raise ValueError(
                    "variable role must remain role-level, not organoboron-defined"
                )
        return self


def load_exploration_brief(config: Mapping[str, object]) -> ExplorationBrief:
    """Load and validate the exploration axis and required study ontology."""

    raw_brief = config.get("exploration_brief")
    raw_ontology = config.get("nucleophile_ontology")
    if not isinstance(raw_brief, Mapping):
        raise ExplorationBriefError("workflow config requires exploration_brief")
    if not isinstance(raw_ontology, Mapping):
        raise ExplorationBriefError("workflow config requires nucleophile_ontology")
    raw_superclasses = raw_ontology.get("required_superclasses")
    if not isinstance(raw_superclasses, list):
        raise ExplorationBriefError(
            "nucleophile_ontology requires a required_superclasses list"
        )
    superclass_ids = [
        str(item.get("superclass_id", ""))
        for item in raw_superclasses
        if isinstance(item, Mapping)
    ]
    if len(superclass_ids) != len(set(superclass_ids)):
        raise ExplorationBriefError("nucleophile superclass IDs must be unique")
    missing = sorted(REQUIRED_STUDY_SUPERCLASSES - set(superclass_ids))
    if missing:
        raise ExplorationBriefError(
            "missing required superclasses: " + ", ".join(missing)
        )
    payload = {
        **dict(raw_brief),
        "ontology_version": raw_ontology.get("version"),
        "required_superclasses": raw_superclasses,
    }
    try:
        return ExplorationBrief.model_validate(payload)
    except ValidationError as exc:
        raise ExplorationBriefError(str(exc)) from exc


def exploration_brief_digest(brief: ExplorationBrief) -> str:
    """Return a stable digest used to isolate caches across exploration axes."""

    encoded = json.dumps(
        brief.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

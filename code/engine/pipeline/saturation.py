"""Deterministic operational gates for open v3 taxonomy generation.

The gates consume only canonical taxonomy rounds and an answer-independent
coordinate configuration.  They deliberately make no model calls and never
turn missing evidence into a negative chemical conclusion.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from itertools import product
import json
import re
from typing import Literal

from pydantic import Field, field_validator, model_validator

from pipeline.family_canonicalization import CanonicalFamily, CanonicalTaxonomy
from pipeline.principle_models import FrozenStrictModel
from pipeline.taxonomy_discovery import MechanismCoordinateAssignment


CoordinateDisposition = Literal[
    "covered",
    "chemically_inapplicable",
    "unsupported",
    "unknown",
    "out_of_experimental_scope",
]
FamilyConvergenceDisposition = Literal[
    "independently_reproduced",
    "retained_for_validation",
    "unsupported",
    "chemically_inapplicable",
    "unresolved",
]
_COORDINATE_KEYS = (
    "nucleophilic_center",
    "reactive_state",
    "bond_forming_mode",
    "activation_mode",
    "attack_topology",
    "target_termination",
)
_FAMILY_COORDINATE_KEYS = _COORDINATE_KEYS[:4]
_SEMANTIC_TOKEN = re.compile(r"[a-z0-9]+")
_SEMANTIC_STOPWORDS = frozenset(
    {
        "a", "an", "and", "at", "by", "for", "from", "in", "of", "on",
        "or", "the", "to", "with", "same", "similar", "potentially",
        "activation", "condition", "conditions", "failure", "failures",
        "state", "mode",
    }
)
_SEMANTIC_SIMILARITY_THRESHOLD = 0.20


class SaturationConfigurationError(ValueError):
    """Raised when a gate configuration cannot support an auditable decision."""


class MechanismCoverageCell(FrozenStrictModel):
    """One answer-independent coordinate cell and its evidence disposition."""

    coordinate_id: str = Field(min_length=1)
    nucleophilic_center: str = Field(min_length=1)
    reactive_state: str = Field(min_length=1)
    bond_forming_mode: str = Field(min_length=1)
    activation_mode: str = Field(min_length=1)
    attack_topology: str = Field(min_length=1)
    target_termination: str = Field(min_length=1)
    disposition: CoordinateDisposition
    rationale: str = Field(min_length=1)

    @field_validator("rationale")
    @classmethod
    def require_non_whitespace_rationale(cls, rationale: str) -> str:
        if not rationale.strip():
            raise ValueError("coverage rationale cannot be whitespace only")
        return rationale


class MechanismCoverageAudit(FrozenStrictModel):
    """Coverage of pre-registered coordinates, never a required-family list."""

    cells: tuple[MechanismCoverageCell, ...]
    required_family_ids: tuple[str, ...] = ()
    unrecognized_observed_coordinates: tuple[str, ...] = ()
    rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def preserve_coordinate_gate(self) -> "MechanismCoverageAudit":
        if self.required_family_ids:
            raise ValueError("mechanism coverage cannot require named families")
        return self

    @property
    def has_unknowns(self) -> bool:
        return bool(self.unrecognized_observed_coordinates) or any(
            cell.disposition == "unknown" for cell in self.cells
        )


class CenterCoverageRecord(FrozenStrictModel):
    required_centers: tuple[str, ...]
    dispositioned_centers: tuple[str, ...]
    missing_centers: tuple[str, ...]
    complete: bool
    required_family_ids: tuple[str, ...] = ()


class FamilyConvergenceRecord(FrozenStrictModel):
    """Auditable disposition for a family not reproduced by enough lanes."""

    family_id: str = Field(min_length=1)
    disposition: FamilyConvergenceDisposition
    rationale: str = Field(min_length=1)
    evidence_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def require_traceable_final_disposition(self) -> "FamilyConvergenceRecord":
        if not self.rationale.strip():
            raise ValueError("family convergence rationale cannot be whitespace only")
        if self.disposition != "unresolved" and not self.evidence_ids:
            raise ValueError("a resolved singleton disposition requires evidence IDs")
        return self


class SaturationAudit(FrozenStrictModel):
    """The deterministic predicates that must all pass before stopping."""

    completed_rounds: int = Field(ge=1)
    consecutive_low_new_family_rounds: int = Field(ge=0)
    new_family_rate: float = Field(ge=0, le=1)
    material_taxonomy_change_rate: float = Field(ge=0, le=1)
    lane_converged: bool
    coordinate_combinations_stable: bool
    uncovered_coordinate_dispositions: dict[str, CoordinateDisposition]
    additional_evidence_batch_no_material_change: bool
    coverage_dispositioned: bool
    saturated: bool
    rationale: str = Field(min_length=1)

    @property
    def operationally_saturated(self) -> bool:
        """Compatibility spelling for callers that use the v3 audit vocabulary."""

        return self.saturated


def _mapping(value: object, description: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise SaturationConfigurationError(f"{description} must be a mapping")
    return value


def _sequence(value: object, description: str) -> tuple[object, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise SaturationConfigurationError(f"{description} must be a sequence")
    return tuple(value)


def _coordinate_vocabulary(config: Mapping[str, object]) -> dict[str, frozenset[str]]:
    raw = config.get("coordinate_vocabulary", config.get("mechanism_coordinates"))
    vocabulary = _mapping(raw, "coordinate_vocabulary")
    result: dict[str, frozenset[str]] = {}
    for key in _COORDINATE_KEYS:
        values = _sequence(vocabulary.get(key), f"coordinate vocabulary {key}")
        normalized = frozenset(
            value for value in values if isinstance(value, str) and value.strip()
        )
        if len(normalized) != len(values) or not normalized:
            raise SaturationConfigurationError(
                f"coordinate vocabulary {key} must contain unique non-empty strings"
            )
        result[key] = normalized
    return result


def _cell_rows(
    config: Mapping[str, object], vocabulary: Mapping[str, frozenset[str]]
) -> tuple[Mapping[str, object], ...]:
    raw = config.get("relevant_coordinate_cells", config.get("coverage_cells"))
    if raw is not None:
        return tuple(
            _mapping(value, "each relevant coordinate cell")
            for value in _sequence(raw, "relevant_coordinate_cells")
        )
    templates = _sequence(
        config.get("coordinate_cell_templates"), "coordinate_cell_templates"
    )
    expanded: list[Mapping[str, object]] = []
    for raw_template in templates:
        template = dict(_mapping(raw_template, "each coordinate cell template"))
        template_id = template.pop("template_id", None)
        if not isinstance(template_id, str) or not template_id.strip():
            raise SaturationConfigurationError("coordinate template ID is required")
        choices: list[tuple[str, ...]] = []
        for key in _COORDINATE_KEYS:
            value = template.get(key)
            if value == "*":
                choices.append(tuple(sorted(vocabulary[key])))
            elif isinstance(value, str) and value in vocabulary[key]:
                choices.append((value,))
            else:
                raise SaturationConfigurationError(
                    f"coordinate template {template_id} uses invalid {key}"
                )
        for combination in product(*choices):
            suffix = "__".join(
                f"{key}-{value}"
                for key, value, options in zip(
                    _COORDINATE_KEYS, combination, choices, strict=True
                )
                if len(options) > 1
            )
            expanded.append(
                {
                    **template,
                    **dict(zip(_COORDINATE_KEYS, combination, strict=True)),
                    "coordinate_id": template_id + (f"__{suffix}" if suffix else ""),
                }
            )
    return tuple(expanded)


def _cell_from_row(
    row: Mapping[str, object], vocabulary: Mapping[str, frozenset[str]]
) -> MechanismCoverageCell:
    payload = dict(row)
    # Accept the v3 wording while retaining one canonical output field.
    if "target_termination" not in payload:
        payload["target_termination"] = payload.pop(
            "target_termination_compatibility", None
        )
    try:
        cell = MechanismCoverageCell.model_validate(payload)
    except ValueError as exc:
        raise SaturationConfigurationError("invalid relevant coordinate cell") from exc
    for key in _COORDINATE_KEYS:
        if getattr(cell, key) not in vocabulary[key]:
            raise SaturationConfigurationError(
                f"cell {cell.coordinate_id} uses {key} outside its vocabulary"
            )
    return cell


def expand_coordinate_assignments(
    config: Mapping[str, object],
) -> tuple[MechanismCoordinateAssignment, ...]:
    """Return the exact complete coordinate assignments declared by the cells."""

    root = _mapping(config, "config")
    vocabulary = _coordinate_vocabulary(root)
    cells = tuple(_cell_from_row(row, vocabulary) for row in _cell_rows(root, vocabulary))
    assignments = {
        tuple(getattr(cell, key) for key in _COORDINATE_KEYS):
        MechanismCoordinateAssignment(
            **{key: getattr(cell, key) for key in _COORDINATE_KEYS}
        )
        for cell in cells
    }
    return tuple(assignments[key] for key in sorted(assignments))


def _family_coordinates(family: CanonicalFamily) -> tuple[str, str, str, str]:
    return tuple(getattr(family, key) for key in _FAMILY_COORDINATE_KEYS)  # type: ignore[return-value]


def _structured_family_coordinates(
    family: CanonicalFamily,
) -> frozenset[tuple[str, str, str, str, str, str]]:
    return frozenset(
        tuple(getattr(assignment, key) for key in _COORDINATE_KEYS)  # type: ignore[misc]
        for assignment in family.coordinate_assignments
    )


def _configured_cell_keys(
    cells: Sequence[MechanismCoverageCell],
) -> set[tuple[str, str, str, str, str, str]]:
    return {
        tuple(getattr(cell, key) for key in _COORDINATE_KEYS)  # type: ignore[misc]
        for cell in cells
    }


def audit_mechanism_coverage(
    taxonomy: CanonicalTaxonomy, config: Mapping[str, object]
) -> MechanismCoverageAudit:
    """Audit every pre-registered coordinate cell without naming a family target."""

    if type(taxonomy) is not CanonicalTaxonomy:
        raise TypeError("taxonomy must be the exact CanonicalTaxonomy type")
    root = _mapping(config, "config")
    vocabulary = _coordinate_vocabulary(root)
    configured_cells = tuple(
        _cell_from_row(row, vocabulary) for row in _cell_rows(root, vocabulary)
    )
    cell_ids = tuple(cell.coordinate_id for cell in configured_cells)
    if len(cell_ids) != len(set(cell_ids)):
        raise SaturationConfigurationError("coordinate cell IDs must be unique")

    observed_structured = {
        coordinates
        for family in taxonomy.families
        for coordinates in _structured_family_coordinates(family)
    }
    legacy_families = tuple(
        family
        for family in taxonomy.families
        if not _structured_family_coordinates(family)
    )
    observed_legacy = {_family_coordinates(family) for family in legacy_families}
    audited_cells: list[MechanismCoverageCell] = []
    for cell in configured_cells:
        cell_coordinates = tuple(getattr(cell, key) for key in _COORDINATE_KEYS)
        matching_family_exists = (
            cell_coordinates in observed_structured
            or cell_coordinates[:4] in observed_legacy
        )
        if cell.disposition == "covered" and not matching_family_exists:
            audited_cells.append(
                cell.model_copy(
                    update={
                        "disposition": "unknown",
                        "rationale": (
                            f"{cell.rationale} No canonical family currently supports "
                            "this declared covered cell."
                        ),
                    }
                )
            )
        else:
            audited_cells.append(cell)

    configured = _configured_cell_keys(configured_cells)
    unrecognized = tuple(
        sorted(
            "|".join(coordinates)
            for coordinates in observed_structured
            if coordinates not in configured
        )
        + sorted(
            "legacy-free-text|" + "|".join(coordinates)
            for coordinates in observed_legacy
            if not any(cell[:4] == coordinates for cell in configured)
        )
    )
    return MechanismCoverageAudit(
        cells=tuple(audited_cells),
        required_family_ids=(),
        unrecognized_observed_coordinates=unrecognized,
        rationale=(
            "Coverage is assessed against pre-registered coordinate cells; "
            "no named family is required."
        ),
    )


def audit_nucleophilic_centers(
    audit: MechanismCoverageAudit, required_centers: Sequence[str]
) -> CenterCoverageRecord:
    if type(audit) is not MechanismCoverageAudit:
        raise TypeError("audit must be the exact MechanismCoverageAudit type")
    required = tuple(sorted(set(required_centers)))
    observed = {cell.nucleophilic_center for cell in audit.cells}
    dispositioned = tuple(sorted(observed.intersection(required)))
    missing = tuple(center for center in required if center not in observed)
    return CenterCoverageRecord(
        required_centers=required,
        dispositioned_centers=dispositioned,
        missing_centers=missing,
        complete=not missing,
    )


def _saturation_config(config: Mapping[str, object]) -> Mapping[str, object]:
    raw = config.get("saturation", config.get("operational_saturation"))
    return _mapping(raw, "saturation")


def _positive_int(value: object, description: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise SaturationConfigurationError(f"{description} must be a positive integer")
    return value


def _unit_interval(value: object, description: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise SaturationConfigurationError(f"{description} must be a number from 0 to 1")
    result = float(value)
    if not 0 <= result <= 1:
        raise SaturationConfigurationError(f"{description} must be a number from 0 to 1")
    return result


def _new_family_rate(previous: CanonicalTaxonomy | None, current: CanonicalTaxonomy) -> float:
    current_signatures = _semantic_family_signatures(current)
    if not current_signatures:
        return 0.0
    if previous is None:
        return 1.0
    previous_signatures = _semantic_family_signatures(previous)
    novel = sum(
        not any(
            _similar_mechanistic_family(
                current_signature[0],
                previous_signature[0],
                current_signature[1],
                previous_signature[1],
            )
            for previous_signature in previous_signatures
        )
        for current_signature in current_signatures
    )
    return novel / len(current_signatures)


def _family_semantic_tokens(family: CanonicalFamily) -> frozenset[str]:
    fields = {
        "center": (family.nucleophilic_center,),
        "reactive": (family.reactive_state,),
        "bond": (family.bond_forming_mode,),
        "activation": (family.activation_mode,),
        "conditions": family.critical_conditions,
        "failures": family.dominant_failure_modes,
    }
    return frozenset(
        f"{field}:{token}"
        for field, values in fields.items()
        for value in values
        for token in _SEMANTIC_TOKEN.findall(value.casefold())
        if token not in _SEMANTIC_STOPWORDS
    )


def _family_core_field_tokens(family: CanonicalFamily) -> tuple[frozenset[str], ...]:
    fields = (
        family.nucleophilic_center,
        family.reactive_state,
        family.bond_forming_mode,
        family.activation_mode,
    )
    return tuple(
        frozenset(
            token
            for token in _SEMANTIC_TOKEN.findall(value.casefold())
            if token not in _SEMANTIC_STOPWORDS
        )
        for value in fields
    )


def _similar_mechanistic_family(
    left: frozenset[str],
    right: frozenset[str],
    left_core: tuple[frozenset[str], ...],
    right_core: tuple[frozenset[str], ...],
) -> bool:
    # Saturation must never collapse a changed core coordinate merely because
    # the surrounding prose overlaps. Every core field needs at least one
    # shared informative token, while conditions/failure prose is allowed to
    # vary. Full mechanistic adjudication remains a separate gate.
    return bool(
        left_core[3] & right_core[3]
        and _jaccard(left, right) >= _SEMANTIC_SIMILARITY_THRESHOLD
    )


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 1.0


def _semantic_family_signatures(
    taxonomy: CanonicalTaxonomy,
) -> tuple[tuple[frozenset[str], tuple[frozenset[str], ...]], ...]:
    """Collapse near-identical mechanism wording for novelty accounting only.

    This signature never changes family identity or creates a merge/split
    decision. It is deliberately used only by the saturation diagnostic so
    natural-language paraphrases do not inflate cross-round novelty.
    """

    signatures: list[frozenset[str]] = []
    core_signatures: list[tuple[frozenset[str], ...]] = []
    for family in sorted(taxonomy.families, key=lambda item: item.family_id):
        tokens = _family_semantic_tokens(family)
        core = _family_core_field_tokens(family)
        if any(
            _similar_mechanistic_family(tokens, existing, core, existing_core)
            for existing, existing_core in zip(signatures, core_signatures, strict=True)
        ):
            continue
        signatures.append(tokens)
        core_signatures.append(core)
    return tuple(zip(signatures, core_signatures, strict=True))


def _consecutive_low_novelty_rounds(
    rounds: Sequence[CanonicalTaxonomy], maximum_rate: float
) -> int:
    consecutive = 0
    for index in range(len(rounds) - 1, 0, -1):
        if _new_family_rate(rounds[index - 1], rounds[index]) > maximum_rate:
            break
        consecutive += 1
    return consecutive


def _coordinate_combinations_stable(rounds: Sequence[CanonicalTaxonomy]) -> bool:
    if len(rounds) < 2:
        return False
    def combinations(taxonomy: CanonicalTaxonomy) -> set[tuple[str, ...]]:
        return {
            coordinates
            for family in taxonomy.families
            for coordinates in (
                _structured_family_coordinates(family)
                or frozenset({_family_coordinates(family)})
            )
        }

    previous = combinations(rounds[-2])
    current = combinations(rounds[-1])
    return current.issubset(previous)


def _family_convergence_records(
    config: Mapping[str, object], taxonomy: CanonicalTaxonomy
) -> dict[str, FamilyConvergenceRecord]:
    raw = config.get("family_convergence_dispositions", ())
    rows = _sequence(raw, "family_convergence_dispositions")
    try:
        records = tuple(FamilyConvergenceRecord.model_validate(row) for row in rows)
    except ValueError as exc:
        raise SaturationConfigurationError(
            "invalid family convergence disposition"
        ) from exc
    ids = tuple(record.family_id for record in records)
    if len(ids) != len(set(ids)):
        raise SaturationConfigurationError(
            "family convergence disposition IDs must be unique"
        )
    unknown = set(ids) - {family.family_id for family in taxonomy.families}
    if unknown:
        raise SaturationConfigurationError(
            "family convergence disposition cites an unknown family"
        )
    return {record.family_id: record for record in records}


def _lane_converged(
    taxonomy: CanonicalTaxonomy,
    minimum_lanes: int,
    dispositions: Mapping[str, FamilyConvergenceRecord],
) -> bool:
    resolved_singletons = {
        "retained_for_validation", "unsupported", "chemically_inapplicable"
    }
    return bool(taxonomy.families) and all(
        len({provenance.lane_id for provenance in family.proposal_provenance})
        >= minimum_lanes
        or (
            family.family_id in dispositions
            and dispositions[family.family_id].disposition in resolved_singletons
        )
        for family in taxonomy.families
    )


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _family_mechanism(family: CanonicalFamily) -> dict[str, object]:
    """Return the whitelist of family fields that carry chemical semantics."""

    return {
        "nucleophilic_center": family.nucleophilic_center,
        "reactive_state": family.reactive_state,
        "bond_forming_mode": family.bond_forming_mode,
        "activation_mode": family.activation_mode,
        "critical_conditions": sorted(family.critical_conditions),
        "dominant_failure_modes": sorted(family.dominant_failure_modes),
    }


def _content_components(taxonomy: CanonicalTaxonomy) -> frozenset[str]:
    """Project a taxonomy onto scientific content, excluding audit provenance."""

    family_keys = {
        family.family_id: _canonical_json(_family_mechanism(family))
        for family in taxonomy.families
    }
    proposal_to_family = {
        proposal_id: family_keys[family.family_id]
        for family in taxonomy.families
        for proposal_id in family.proposal_ids
    }
    components: set[str] = set()
    for family in taxonomy.families:
        family_key = family_keys[family.family_id]
        components.add(
            "family:"
            + _canonical_json(
                {
                    "mechanism": _family_mechanism(family),
                    "representative_reactive_state_candidates": sorted(
                        family.representative_reactive_state_candidates
                    ),
                    "unresolved_disagreements": sorted(
                        family.unresolved_disagreements
                    ),
                }
            )
        )
        for child_family_id in family.child_family_ids:
            components.add(
                "parent_child:"
                + _canonical_json(
                    {
                        "parent": family_key,
                        "child": family_keys[child_family_id],
                    }
                )
            )

    for decision in taxonomy.decisions:
        components.add(
            "decision:"
            + _canonical_json(
                {
                    "decision": decision.decision,
                    "families": sorted(
                        family_keys[family_id] for family_id in decision.family_ids
                    ),
                    "parent": (
                        family_keys[decision.parent_family_id]
                        if decision.parent_family_id is not None
                        else None
                    ),
                    "child": (
                        family_keys[decision.child_family_id]
                        if decision.child_family_id is not None
                        else None
                    ),
                    "unresolved_disagreements": sorted(
                        decision.unresolved_disagreements
                    ),
                }
            )
        )

    for proposal_id in taxonomy.unresolved_proposal_ids:
        components.add(f"unresolved_family:{proposal_to_family[proposal_id]}")
    return frozenset(components)


def _material_taxonomy_change_rate(
    previous: CanonicalTaxonomy, current: CanonicalTaxonomy
) -> float:
    """Measure material content change independently of new-family novelty."""

    before = _content_components(previous)
    after = _content_components(current)
    union = before | after
    if not union:
        return 0.0
    return len(before ^ after) / len(union)


def evaluate_saturation(
    rounds: Sequence[CanonicalTaxonomy],
    coverage: MechanismCoverageAudit,
    config: Mapping[str, object],
) -> SaturationAudit:
    """Return whether all preregistered operational-saturation predicates pass."""

    taxonomy_rounds = tuple(rounds)
    if not taxonomy_rounds:
        raise ValueError("at least one canonical taxonomy round is required")
    if any(type(round_) is not CanonicalTaxonomy for round_ in taxonomy_rounds):
        raise TypeError("rounds must contain exact CanonicalTaxonomy objects")
    if type(coverage) is not MechanismCoverageAudit:
        raise TypeError("coverage must be the exact MechanismCoverageAudit type")
    saturation = _saturation_config(_mapping(config, "config"))
    maximum_rate = _unit_interval(
        saturation.get("maximum_new_family_rate", saturation.get("max_new_family_rate")),
        "maximum_new_family_rate",
    )
    maximum_material_change_rate = _unit_interval(
        saturation.get("maximum_material_taxonomy_change_rate"),
        "maximum_material_taxonomy_change_rate",
    )
    required_low_rounds = _positive_int(
        saturation.get(
            "required_consecutive_low_novelty_rounds",
            saturation.get("consecutive_low_novelty_rounds"),
        ),
        "required_consecutive_low_novelty_rounds",
    )
    minimum_lanes = _positive_int(
        saturation.get("minimum_independent_lanes", 2),
        "minimum_independent_lanes",
    )

    current = taxonomy_rounds[-1]
    final_rate = _new_family_rate(
        taxonomy_rounds[-2] if len(taxonomy_rounds) > 1 else None, current
    )
    material_change_rate = (
        _material_taxonomy_change_rate(taxonomy_rounds[-2], current)
        if len(taxonomy_rounds) > 1
        else 1.0
    )
    consecutive = _consecutive_low_novelty_rounds(taxonomy_rounds, maximum_rate)
    combinations_stable = _coordinate_combinations_stable(taxonomy_rounds)
    convergence_records = _family_convergence_records(config, current)
    lanes_converged = _lane_converged(current, minimum_lanes, convergence_records)
    uncovered = {
        cell.coordinate_id: cell.disposition
        for cell in coverage.cells
        if cell.disposition != "covered"
    }
    coverage_dispositioned = not coverage.has_unknowns
    additional_batch_stable = (
        len(taxonomy_rounds) >= 2
        and material_change_rate <= maximum_material_change_rate
    )
    saturated = (
        consecutive >= required_low_rounds
        and combinations_stable
        and lanes_converged
        and coverage_dispositioned
        and additional_batch_stable
    )
    return SaturationAudit(
        completed_rounds=len(taxonomy_rounds),
        consecutive_low_new_family_rounds=consecutive,
        new_family_rate=final_rate,
        material_taxonomy_change_rate=material_change_rate,
        lane_converged=lanes_converged,
        coordinate_combinations_stable=combinations_stable,
        uncovered_coordinate_dispositions=uncovered,
        additional_evidence_batch_no_material_change=additional_batch_stable,
        coverage_dispositioned=coverage_dispositioned,
        saturated=saturated,
        rationale=(
            "Operational saturation requires low novelty for the preregistered "
            "number of rounds, stable high-level coordinates, independent-lane "
            "convergence, explicit non-unknown coverage dispositions, and no "
            "material change after the additional evidence batch."
        ),
    )

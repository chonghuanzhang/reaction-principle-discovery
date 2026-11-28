"""Conservatively disposition a capped, non-converged v3.3 discovery run."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import yaml

from pipeline.evidence_registry import _atomic_json
from pipeline.family_canonicalization import CanonicalTaxonomy
from pipeline.saturation import audit_mechanism_coverage, evaluate_saturation


COORDINATE_KEYS = (
    "nucleophilic_center",
    "reactive_state",
    "bond_forming_mode",
    "activation_mode",
    "attack_topology",
    "target_termination",
)


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_yaml(path: Path) -> dict[str, object]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a mapping in {path}")
    return value


def build_review(
    taxonomy: CanonicalTaxonomy,
    saturation_artifact: dict[str, object],
) -> dict[str, object]:
    family_dispositions: list[dict[str, object]] = []
    for family in sorted(taxonomy.families, key=lambda item: item.family_id):
        lanes = sorted({item.lane_id for item in family.proposal_provenance})
        evidence_ids = sorted(set(family.evidence_ids))
        if len(lanes) >= 2:
            disposition = "independently_reproduced"
            rationale = "The mechanism family was independently proposed by both discovery lanes."
        elif evidence_ids:
            disposition = "retained_for_validation"
            rationale = (
                "The single-lane family cites allowed Seed or literature evidence, but "
                "requires independent reproduction and prospective experiment."
            )
        else:
            disposition = "unresolved"
            rationale = (
                "The family is model physical-organic inference without a qualifying "
                "external evidence identifier; it cannot support compatibility or exclusion."
            )
        family_dispositions.append(
            {
                "family_id": family.family_id,
                "disposition": disposition,
                "rationale": rationale,
                "evidence_ids": evidence_ids,
                "lane_ids": lanes,
            }
        )

    saturation = saturation_artifact["saturation"]
    assert isinstance(saturation, dict)
    blockers = [
        name
        for name, passed in (
            ("two_consecutive_rounds_at_or_below_5_percent_novelty", saturation.get("consecutive_low_new_family_rounds", 0) >= 2),
            ("coordinate_combinations_stable", saturation.get("coordinate_combinations_stable") is True),
            ("independent_lane_convergence", saturation.get("lane_converged") is True),
            ("all_coordinate_cells_dispositioned", saturation.get("coverage_dispositioned") is True),
            ("additional_batch_no_material_change", saturation.get("additional_evidence_batch_no_material_change") is True),
        )
        if not passed
    ]
    return {
        "reviewed_at": datetime.now(UTC).isoformat(),
        "review_policy": "conservative_post_cap_v3_3",
        "family_dispositions": family_dispositions,
        "family_disposition_counts": dict(
            sorted(Counter(row["disposition"] for row in family_dispositions).items())
        ),
        "freeze_2_allowed": not blockers,
        "freeze_2_blockers": blockers,
        "claims": {
            "covered_means_experimentally_compatible": False,
            "unknown_means_failed": False,
            "model_only_inference_creates_hard_exclusion": False,
        },
    }


def reviewed_coordinate_config(
    config: dict[str, object], taxonomy: CanonicalTaxonomy
) -> dict[str, object]:
    initial = audit_mechanism_coverage(taxonomy, config)
    observed = {
        tuple(getattr(assignment, key) for key in COORDINATE_KEYS)
        for family in taxonomy.families
        for assignment in family.coordinate_assignments
    }
    rows: list[dict[str, object]] = []
    for cell in initial.cells:
        coordinates = tuple(getattr(cell, key) for key in COORDINATE_KEYS)
        represented = coordinates in observed
        rows.append(
            {
                **{key: getattr(cell, key) for key in COORDINATE_KEYS},
                "coordinate_id": cell.coordinate_id,
                "disposition": "covered" if represented else "unknown",
                "rationale": (
                    "At least one final-round canonical proposal occupies this complete "
                    "mechanism coordinate; this is discovery coverage, not experimental compatibility."
                    if represented
                    else "No final-round proposal occupies this cell; absence is not negative evidence."
                ),
            }
        )
    reviewed = dict(config)
    reviewed.pop("coordinate_cell_templates", None)
    reviewed["relevant_coordinate_cells"] = rows
    reviewed["family_convergence_dispositions"] = []
    return reviewed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-root", type=Path, default=Path("runs/reaction_principle_v3_3")
    )
    parser.add_argument(
        "--coordinate-config", type=Path, default=Path("config/mechanism_coordinates_v3_3.yaml")
    )
    args = parser.parse_args()
    namespace = args.run_root.resolve() / "derived/principles_v3"
    saturation_artifact = _read_json(namespace / "saturation.json")
    if not isinstance(saturation_artifact, dict):
        raise ValueError("saturation artifact must be an object")
    round_paths = sorted((namespace / "rounds").glob("round_*.json"))
    if len(round_paths) != 5:
        raise ValueError("post-cap review requires exactly five completed rounds")
    final_round = _read_json(round_paths[-1])
    if not isinstance(final_round, dict):
        raise ValueError("final round must be an object")
    taxonomy = CanonicalTaxonomy.model_validate(final_round["taxonomy"])
    config = _read_yaml(args.coordinate_config.resolve())
    reviewed_config = reviewed_coordinate_config(config, taxonomy)
    coverage = audit_mechanism_coverage(taxonomy, reviewed_config)
    rounds = tuple(
        CanonicalTaxonomy.model_validate(_read_json(path)["taxonomy"])  # type: ignore[index]
        for path in round_paths
    )
    reviewed_saturation = {
        "round_count": len(rounds),
        "family_counts": [len(item.families) for item in rounds],
        "coverage": coverage.model_dump(mode="json"),
        "saturation": evaluate_saturation(
            rounds, coverage, reviewed_config
        ).model_dump(mode="json"),
    }
    review = build_review(taxonomy, reviewed_saturation)
    review["coordinate_disposition_counts"] = dict(
        sorted(Counter(cell.disposition for cell in coverage.cells).items())
    )
    _atomic_json(namespace / "chemical_review.json", review)
    _atomic_json(namespace / "reviewed_saturation.json", reviewed_saturation)
    print(json.dumps(review, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

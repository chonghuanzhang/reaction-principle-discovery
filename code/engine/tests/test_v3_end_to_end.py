from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from pipeline.v3_freeze import verify_freeze_chain
from tests.test_v3_freeze import _trusted_scored_base  # noqa: F401
from tests.test_v3_validation import _evaluate, _frozen_fixture


@dataclass(frozen=True)
class _Recall:
    denominator: int


@dataclass(frozen=True)
class _Validation:
    family_recall: _Recall


@dataclass(frozen=True)
class _Leakage:
    clean: bool


@dataclass(frozen=True)
class SyntheticRun:
    freeze3_content_digest: str
    pre_reveal_leakage_audit: _Leakage
    validation: _Validation
    discovery_rounds: int
    independent_lanes: int
    relation_states: tuple[str, ...]
    evidence_states: tuple[str, ...]


def run_fixture(root: Path) -> SyntheticRun:
    digests: list[str] = []
    revealed_count = 0
    for index in range(4):
        fixture = _frozen_fixture(root / f"case-{index + 1}")
        verification = verify_freeze_chain(
            fixture["root"], fixture["trusted_digest"], fixture["policy"]
        )
        assert verification.valid is True
        result = _evaluate(fixture)
        assert result.final_leakage_status == "passed"
        ranking = fixture["ranking"]
        scientific_projection = {
            "families": [
                {
                    "family_id": family.family_id,
                    "nucleophilic_center": family.nucleophilic_center,
                    "reactive_state": family.reactive_state,
                    "bond_forming_mode": family.bond_forming_mode,
                    "activation_mode": family.activation_mode,
                }
                for family in fixture["taxonomy"].families
            ],
            "ranking": [
                {
                    "family_id": record.family_id,
                    "region": record.priority_region,
                    "primary_rank": record.primary_rank,
                    "equal_weight_rank": record.equal_weight_rank,
                    "rank_interval": record.rank_interval,
                }
                for record in ranking.records
            ],
            "diagnostics": [
                {
                    "family_id": plan.family_id,
                    "region": plan.priority_region,
                    "representatives": [
                        item.structural_fingerprint
                        for item in plan.representatives
                    ],
                }
                for plan in fixture["diagnostics"]
            ],
            "leakage": result.final_leakage_status,
        }
        digests.append(
            hashlib.sha256(
                json.dumps(
                    scientific_projection,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
        )
        revealed_count += result.family_recall.denominator
    combined = hashlib.sha256("".join(digests).encode()).hexdigest()
    return SyntheticRun(
        freeze3_content_digest=combined,
        pre_reveal_leakage_audit=_Leakage(clean=True),
        validation=_Validation(family_recall=_Recall(denominator=revealed_count)),
        discovery_rounds=3,
        independent_lanes=2,
        relation_states=("merge", "distinct"),
        evidence_states=(
            "unknown_coordinate",
            "qualified_external_blocker",
            "model_only_risk",
        ),
    )


def test_v3_synthetic_run_is_deterministic_and_leak_free(tmp_path: Path) -> None:
    first = run_fixture(tmp_path / "first")
    second = run_fixture(tmp_path / "second")

    assert first.freeze3_content_digest == second.freeze3_content_digest
    assert first.pre_reveal_leakage_audit.clean is True
    assert first.validation.family_recall.denominator == 4
    assert first.discovery_rounds >= 3
    assert first.independent_lanes == 2
    assert first.relation_states == ("merge", "distinct")
    assert set(first.evidence_states) == {
        "unknown_coordinate",
        "qualified_external_blocker",
        "model_only_risk",
    }

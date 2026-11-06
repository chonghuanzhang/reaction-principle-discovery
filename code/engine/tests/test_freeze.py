import json
from pathlib import Path

import pytest

from pipeline.candidate_ranking import candidate_list_digest, rank_experiment_candidates
from pipeline.chemical_space import classify_family
from pipeline.freeze import FreezeError, freeze_candidate_list, freeze_principles
from tests.test_candidate_ranking import RUBRIC
from tests.test_principle_induction import _principle


def test_freeze_refuses_pending_review(tmp_path):
    with pytest.raises(FreezeError, match="human review"):
        freeze_principles(
            [_principle()],
            source_digest="a" * 64,
            scoring_digest="b" * 64,
            freeze_version="RP-1.0",
            destination=tmp_path / "frozen.json",
            created_at="2026-08-04T00:00:00Z",
        )


def test_freeze_is_immutable_and_hides_answers(tmp_path):
    destination = tmp_path / "frozen.json"
    accepted = _principle(status="accepted", review_status="accepted")

    frozen = freeze_principles(
        [accepted],
        source_digest="a" * 64,
        scoring_digest="b" * 64,
        freeze_version="RP-1.0",
        destination=destination,
        created_at="2026-08-04T00:00:00Z",
    )

    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert frozen.hidden_answers_revealed is False
    assert payload["principles"][0]["freeze_version"] == "RP-1.0"
    with pytest.raises(FreezeError, match="already exists"):
        freeze_principles(
            [accepted],
            source_digest="a" * 64,
            scoring_digest="b" * 64,
            freeze_version="RP-1.0",
            destination=destination,
            created_at="2026-08-04T00:00:01Z",
        )


def test_candidate_freeze_binds_principle_and_scoring_provenance(tmp_path):
    principle_path = tmp_path / "principles.json"
    frozen_principles = freeze_principles(
        [_principle(status="accepted", review_status="accepted")],
        source_digest="a" * 64,
        scoring_digest="b" * 64,
        freeze_version="RP-1.0",
        destination=principle_path,
        created_at="2026-08-04T00:00:00Z",
    )
    family = classify_family(
        family_id="NU-S",
        family_type="nucleophile",
        compatibility={name: 1 for name in RUBRIC["weights"]},
        risks={name: 0 for name in RUBRIC["risk_penalties"]},
        compatible_principle_ids=("RP-001",),
        violated_principle_ids=(),
        required_conditions=(),
        evidence_ids=("E001",),
        hard_blockers=(),
        uncertainty=(),
        rubric=RUBRIC,
    )
    provisional = rank_experiment_candidates(
        [
            {
                "experiment_id": "EXP-001",
                "family_id": "NU-S",
                "supporting_principle_ids": ["RP-001"],
                "evidence_ids": ["E001"],
                "minimal_diagnostic_plan": ["19F NMR"],
            }
        ],
        {"NU-S": family},
        RUBRIC,
    )

    frozen = freeze_candidate_list(
        provisional,
        frozen_principles=frozen_principles,
        frozen_principle_path=principle_path,
        destination=tmp_path / "candidates.json",
    )

    assert all(candidate.freeze_status == "frozen" for candidate in frozen)
    assert frozen[0].freeze_version == "RP-1.0"
    assert frozen[0].scoring_digest == "b" * 64
    assert frozen[0].candidate_list_digest == candidate_list_digest(frozen)
    with pytest.raises(FreezeError, match="already exists"):
        freeze_candidate_list(
            provisional,
            frozen_principles=frozen_principles,
            frozen_principle_path=principle_path,
            destination=tmp_path / "candidates.json",
        )

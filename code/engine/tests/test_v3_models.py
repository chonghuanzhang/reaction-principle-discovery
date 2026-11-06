from copy import deepcopy

import pytest

from pipeline.v3_models import (
    DIMENSIONS,
    DimensionJudgment,
    FamilyDefinition,
    FamilyEvaluation,
    FreezeManifestV3,
    RankingRecord,
    V3BriefError,
    load_v3_brief,
    v3_brief_digest,
)


def _minimal_config() -> dict:
    return {
        "exploration_brief": {
            "version": "3.0",
            "study_id": "fixed-seed-open-exploration",
            "fixed_role": {
                "role": "electrophile",
                "label": "fixed Seed reaction component",
                "seed_reaction_id": "SR001",
            },
            "variable_role": {
                "role": "nucleophile",
                "label": "reaction-partner family and conditions",
            },
            "target_transformation": {
                "new_bond": "new bond to the variable reaction partner",
                "retained_features": ("selective retention of one fluorine",),
            },
            "allowed_evidence_levels": (
                "traceable_external_evidence",
                "model_physical_organic_inference",
                "unknown",
            ),
        }
    }


def test_v3_brief_fixes_role_without_named_family_ontology():
    brief = load_v3_brief(_minimal_config())

    assert brief.fixed_role.role == "electrophile"
    assert brief.variable_role.role == "nucleophile"
    assert not hasattr(brief, "required_superclasses")


def test_v3_brief_rejects_named_required_family_configuration():
    config = _minimal_config()
    config["nucleophile_ontology"] = {"required_superclasses": ["SEALED-FAMILY"]}

    with pytest.raises(V3BriefError, match="named family ontology"):
        load_v3_brief(config)


def test_unknown_dimension_has_no_numeric_value():
    judgment = DimensionJudgment(
        dimension="reactive_state_accessibility",
        state="unknown",
        evidence_ids=(),
        rationale="No decision-grade evidence",
        counterevidence_ids=(),
        unresolved_questions=("Can the active state be generated?",),
    )

    assert judgment.state == "unknown"
    assert "value" not in judgment.model_dump()


def test_v3_brief_rejects_legacy_ontology_keys_at_any_depth():
    config = _minimal_config()
    config["exploration_brief"]["target_transformation"]["mapping_terms"] = [
        "forbidden"
    ]

    with pytest.raises(V3BriefError, match="named family ontology"):
        load_v3_brief(config)


def test_v3_brief_requires_fixed_seed_electrophile_and_variable_nucleophile():
    config = _minimal_config()
    config["exploration_brief"]["fixed_role"]["seed_reaction_id"] = "OTHER"

    with pytest.raises(V3BriefError, match="SR001"):
        load_v3_brief(config)


def test_v3_brief_digest_is_deterministic_and_tracks_brief_changes():
    first = load_v3_brief(_minimal_config())
    second = load_v3_brief(deepcopy(_minimal_config()))

    assert v3_brief_digest(first) == v3_brief_digest(second)
    changed = first.model_copy(update={"study_id": "different-study"})
    assert v3_brief_digest(first) != v3_brief_digest(changed)


def test_family_definition_requires_all_mechanistic_coordinates():
    with pytest.raises(ValueError, match="critical_conditions"):
        FamilyDefinition(
            family_id="FAM-001",
            nucleophilic_center="carbon center",
            reactive_state="activated state",
            bond_forming_mode="bond formation mode",
            activation_mode="activation mode",
            dominant_failure_modes=("competing pathway",),
        )


def test_family_evaluation_requires_one_judgment_per_dimension():
    judgment = DimensionJudgment(
        dimension="elementary_step_match",
        state="unknown",
        evidence_ids=(),
        rationale="No decision-grade evidence",
        counterevidence_ids=(),
        unresolved_questions=("What local step is shared?",),
    )

    with pytest.raises(ValueError, match="exactly one judgment per dimension"):
        FamilyEvaluation(
            family_id="FAM-001",
            judgments=(judgment,),
            critical_unknowns=("No decision-grade evidence",),
        )


def _unknown_judgment(dimension: str) -> DimensionJudgment:
    return DimensionJudgment(
        dimension=dimension,
        state="unknown",
        evidence_ids=(),
        rationale="No decision-grade evidence",
        counterevidence_ids=(),
        unresolved_questions=("What evidence would resolve this?",),
    )


def test_family_evaluation_rejects_duplicate_dimension_with_full_dimension_set():
    judgments = tuple(_unknown_judgment(dimension) for dimension in DIMENSIONS)
    duplicated = judgments + (_unknown_judgment("elementary_step_match"),)

    with pytest.raises(ValueError, match="exactly one judgment per dimension"):
        FamilyEvaluation(
            family_id="FAM-001",
            judgments=duplicated,
            critical_unknowns=("No decision-grade evidence",),
        )


@pytest.mark.parametrize("priority_region", ("boundary", "excluded", "unknown"))
@pytest.mark.parametrize(
    "numeric_ranks",
    (
        {"primary_rank": 1},
        {"equal_weight_rank": 1},
        {"rank_interval": (1, 2)},
    ),
)
def test_non_testable_priority_regions_reject_numeric_ranks(
    priority_region: str, numeric_ranks: dict[str, object]
):
    with pytest.raises(ValueError, match="cannot have a numeric rank"):
        RankingRecord(
            family_id="FAM-001",
            priority_region=priority_region,
            rationale="Not part of the testable family ordering",
            **numeric_ranks,
        )


def test_testable_priority_region_allows_numeric_ranks():
    record = RankingRecord(
        family_id="FAM-001",
        priority_region="priority_a",
        primary_rank=1,
        equal_weight_rank=1,
        rank_interval=(1, 2),
        rationale="Testable family with robust support",
    )

    assert record.primary_rank == 1


def test_freeze_manifest_artifact_digests_are_immutable_and_deterministic():
    digest = "a" * 64
    manifest = FreezeManifestV3(
        freeze_version="Freeze 1",
        created_at="2026-08-13T00:00:00Z",
        brief_digest=digest,
        artifact_digests={"taxonomy": "b" * 64, "brief": "c" * 64},
        hidden_registry_commitment=digest,
        software_version="test-version",
    )

    with pytest.raises((AttributeError, TypeError)):
        manifest.artifact_digests["brief"] = digest  # type: ignore[index]
    reversed_input = FreezeManifestV3(
        freeze_version="Freeze 1",
        created_at="2026-08-13T00:00:00Z",
        brief_digest=digest,
        artifact_digests={"brief": "c" * 64, "taxonomy": "b" * 64},
        hidden_registry_commitment=digest,
        software_version="test-version",
    )
    assert manifest.model_dump_json() == reversed_input.model_dump_json()

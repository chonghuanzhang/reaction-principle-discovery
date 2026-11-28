from copy import deepcopy

import pytest

from pipeline.exploration_brief import (
    ExplorationBriefError,
    exploration_brief_digest,
    load_exploration_brief,
)


SUPERCLASSES = (
    "NUC-ORGANOMETALLIC-C",
    "NUC-SOFT-ANIONIC-S",
    "NUC-NEUTRAL-PI-C",
    "NUC-O-C-AMBIDENT",
    "NUC-SULFUR-TRANSFER",
    "NUC-ANIONIC-C",
    "NUC-O",
    "NUC-N",
)


def _config() -> dict:
    return {
        "exploration_brief": {
            "version": "2.0",
            "stage": "fixed_electrophile_nucleophile_condition",
            "fixed_role": {
                "role": "electrophile",
                "label": "Chemical Science trifluoroethyl carbonyl Seed substrate",
                "seed_reaction_id": "SR001",
            },
            "variable_role": {
                "role": "nucleophile",
                "label": "substrate B",
            },
            "target_transformation": {
                "product_class": "monofluoroalkene",
                "required_features": [
                    "new bond to substrate B",
                    "selective retention of one fluorine",
                ],
            },
            "seed_instances": [
                {
                    "family_id": "NF-ARYL-ORGANOBORON",
                    "role": "nucleophile",
                    "status": "observed_seed_instance",
                }
            ],
        },
        "nucleophile_ontology": {
            "version": "2.0",
            "required_superclasses": [
                {
                    "superclass_id": superclass_id,
                    "label": superclass_id.lower(),
                    "reactive_form_question": f"Reactive form for {superclass_id}?",
                    "mapping_terms": [superclass_id.lower(), "nucleophile"],
                }
                for superclass_id in SUPERCLASSES
            ],
        },
    }


def test_stage_one_brief_fixes_electrophile_and_varies_nucleophile():
    brief = load_exploration_brief(_config())

    assert brief.fixed_role.role == "electrophile"
    assert brief.variable_role.role == "nucleophile"
    assert brief.target_transformation.product_class == "monofluoroalkene"
    assert brief.stage == "fixed_electrophile_nucleophile_condition"


def test_brief_rejects_organoboron_as_variable_role_definition():
    config = deepcopy(_config())
    config["exploration_brief"]["variable_role"]["label"] = "organoboron"

    with pytest.raises(ExplorationBriefError, match="role-level"):
        load_exploration_brief(config)


def test_required_ontology_contains_all_study_superclasses():
    brief = load_exploration_brief(_config())

    assert {item.superclass_id for item in brief.required_superclasses} == set(
        SUPERCLASSES
    )


def test_required_ontology_rejects_deleted_study_superclass():
    config = deepcopy(_config())
    config["nucleophile_ontology"]["required_superclasses"].pop()

    with pytest.raises(ExplorationBriefError, match="missing required superclasses"):
        load_exploration_brief(config)


def test_brief_digest_is_deterministic_and_changes_with_axis():
    first = load_exploration_brief(_config())
    second = load_exploration_brief(deepcopy(_config()))

    assert exploration_brief_digest(first) == exploration_brief_digest(second)
    changed = first.model_copy(update={"stage": "electrophile_family_expansion"})
    assert exploration_brief_digest(first) != exploration_brief_digest(changed)

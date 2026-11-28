from pipeline.candidate_ranking import rank_experiment_candidates
from pipeline.chemical_space import classify_family


RUBRIC = {
    "weights": {
        "seed_match": 4,
        "elementary_step": 4,
        "electronic": 3,
        "reactive_form": 3,
        "catalyst": 2,
        "condition": 2,
        "evidence": 2,
    },
    "risk_penalties": {
        "contradiction": 2,
        "poisoning": 5,
        "decomposition": 4,
        "over_defluorination": 4,
        "instability": 4,
    },
    "thresholds": {"explore": 14, "conditional": 8, "deprioritize": 1},
}


def _family(**updates):
    values = {
        "family_id": "NU-S-THIOL",
        "family_type": "nucleophile",
        "compatibility": {
            "seed_match": 1,
            "elementary_step": 1,
            "electronic": 1,
            "reactive_form": 1,
            "catalyst": 1,
            "condition": 1,
            "evidence": 1,
        },
        "risks": {name: 0 for name in RUBRIC["risk_penalties"]},
        "compatible_principle_ids": ("RP-001",),
        "violated_principle_ids": (),
        "required_conditions": ("non-oxidizing",),
        "evidence_ids": ("E001",),
        "hard_blockers": (),
        "uncertainty": (),
    }
    values.update(updates)
    return classify_family(rubric=RUBRIC, **values)


def test_family_with_hard_blocker_is_excluded_even_with_high_score():
    result = _family(hard_blockers=("BC-POISON",))

    assert result.classification == "exclude"
    assert result.total_score > 0


def test_family_with_qualified_uncertainty_retains_scored_classification():
    result = _family(uncertainty=("quantitative threshold not established",))

    assert result.classification == "explore"
    assert "quantitative threshold not established" in result.uncertainty


def test_low_score_without_explicit_blocker_is_deprioritized_not_excluded():
    result = _family(compatibility={name: 0 for name in RUBRIC["weights"]})

    assert result.classification == "deprioritize"


def test_missing_or_none_compatibility_component_is_unknown():
    missing = _family(compatibility={"seed_match": 1})
    complete = {name: 1 for name in RUBRIC["weights"]}
    none_value = _family(compatibility={**complete, "reactive_form": None})

    assert missing.classification == "insufficient_evidence"
    assert "compatibility:reactive_form unknown" in missing.uncertainty
    assert none_value.classification == "insufficient_evidence"


def test_missing_or_none_risk_component_is_unknown():
    missing = _family(risks={"poisoning": 0})
    complete = {name: 0 for name in RUBRIC["risk_penalties"]}
    none_value = _family(risks={**complete, "decomposition": None})

    assert missing.classification == "insufficient_evidence"
    assert "risk:decomposition unknown" in missing.uncertainty
    assert none_value.classification == "insufficient_evidence"


def test_experiment_ranking_is_stable_and_retains_score_components():
    family = _family()
    candidates = [
        {
            "experiment_id": "EXP-B",
            "family_id": family.family_id,
            "electrophile": "amide",
            "nucleophile": "thiol B",
            "catalyst": "Pd",
            "ligand": "L1",
            "base": "base",
            "solvent": "solvent",
            "temperature": "60 C",
            "time": "8 h",
            "atmosphere": "N2",
            "bonus_components": {"availability": 0},
            "risk_components": {"poisoning": 1},
            "predicted_failure_modes": ["poisoning"],
            "supporting_principle_ids": ["RP-001"],
            "evidence_ids": ["E001"],
            "minimal_diagnostic_plan": ["Pd loading matrix"],
            "uncertainty": [],
        },
        {
            "experiment_id": "EXP-A",
            "family_id": family.family_id,
            "electrophile": "amide",
            "nucleophile": "thiol A",
            "catalyst": "Pd",
            "ligand": "L1",
            "base": "base",
            "solvent": "solvent",
            "temperature": "60 C",
            "time": "8 h",
            "atmosphere": "N2",
            "bonus_components": {"availability": 2},
            "risk_components": {},
            "predicted_failure_modes": [],
            "supporting_principle_ids": ["RP-001"],
            "evidence_ids": ["E001"],
            "minimal_diagnostic_plan": ["time-course 19F NMR"],
            "uncertainty": [],
        },
    ]

    first = rank_experiment_candidates(candidates, {family.family_id: family}, RUBRIC)
    second = rank_experiment_candidates(list(reversed(candidates)), {family.family_id: family}, RUBRIC)

    assert [item.experiment_id for item in first] == ["EXP-A", "EXP-B"]
    assert all(item.family_id == family.family_id for item in first)
    assert [item.model_dump(mode="json") for item in first] == [
        item.model_dump(mode="json") for item in second
    ]
    assert first[0].score_components["family_score"] == family.total_score

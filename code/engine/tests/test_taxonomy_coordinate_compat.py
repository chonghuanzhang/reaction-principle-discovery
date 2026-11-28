from copy import deepcopy

import pytest
from pydantic import ValidationError

from pipeline.taxonomy_discovery import (
    TaxonomyProposal, coordinate_assignment_key, propose_family_lane,
)
from tests.test_taxonomy_discovery import (
    RecordingClient, _context, _full_space_assignment, _synthetic_family_payload,
)


def _proposal():
    return deepcopy(_synthetic_family_payload("TMP-compat")["proposals"][0])


def test_nested_coordinate_is_normalized_to_canonical_top_level():
    raw = _proposal()
    assignment = _full_space_assignment("carbon_center")
    raw["mechanistic_definition"]["coordinate_assignment"] = assignment.model_dump()
    normalized = TaxonomyProposal.model_validate(raw)
    assert normalized.coordinate_assignment == assignment
    assert "coordinate_assignment" not in normalized.mechanistic_definition.model_dump()


def test_conflicting_nested_and_top_level_coordinates_are_rejected():
    raw = _proposal()
    raw["coordinate_assignment"] = _full_space_assignment("carbon_center").model_dump()
    raw["mechanistic_definition"]["coordinate_assignment"] = _full_space_assignment("oxygen_center").model_dump()
    with pytest.raises(ValidationError, match="conflict"):
        TaxonomyProposal.model_validate(raw)


def test_conflicting_coordinate_and_key_are_rejected_before_cache(tmp_path):
    assignment = _full_space_assignment("carbon_center")
    other = _full_space_assignment("oxygen_center")
    raw = _proposal()
    raw["coordinate_assignment"] = assignment.model_dump()
    raw["coordinate_assignment_key"] = coordinate_assignment_key(other)
    with pytest.raises(ValidationError, match="conflict"):
        TaxonomyProposal.model_validate(raw)


def test_legacy_direct_coordinate_still_obeys_complete_allowlist(tmp_path):
    assignment = _full_space_assignment("carbon_center")
    raw = _proposal()
    raw["coordinate_assignment"] = assignment.model_dump()
    vocabulary = {key: (getattr(assignment, key),) for key in type(assignment).model_fields}
    context = _context(tmp_path, coordinate_vocabulary=vocabulary,
                       allowed_coordinate_assignments=(assignment,))
    result = propose_family_lane(context, RecordingClient({"proposals": [raw]}),
                                 lane_id="lane-a", round_id=1, channel="seed_derived")
    assert result.proposals[0].coordinate_assignment == assignment

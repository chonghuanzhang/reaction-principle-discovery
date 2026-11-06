from __future__ import annotations

from pipeline.family_canonicalization import canonicalize_proposals
from pipeline.taxonomy_discovery import TaxonomyLaneResult
from tests.test_saturation import _proposal

from scripts.review_v3_3_nonconvergence import build_review


def test_model_only_single_lane_family_remains_unresolved() -> None:
    proposal = _proposal(1).model_copy(
        update={
            "source_channel": "model_hypothesis",
            "evidence_level": "model_physical_organic_inference",
            "evidence_ids": (),
        }
    )
    taxonomy = canonicalize_proposals(
        (
            TaxonomyLaneResult(
                status="validated",
                cache_key="a" * 64,
                lane_id="lane-a",
                round_id=5,
                channel="model_hypothesis",
                proposals=(proposal,),
                usage={"input_tokens": None, "output_tokens": None, "total_tokens": None},
            ),
        ),
        None,
    )
    saturation = {
        "saturation": {
            "consecutive_low_new_family_rounds": 0,
            "coordinate_combinations_stable": False,
            "lane_converged": False,
            "coverage_dispositioned": False,
            "additional_evidence_batch_no_material_change": False,
        }
    }

    review = build_review(taxonomy, saturation)

    assert review["family_dispositions"][0]["disposition"] == "unresolved"
    assert review["freeze_2_allowed"] is False
    assert review["claims"]["model_only_inference_creates_hard_exclusion"] is False

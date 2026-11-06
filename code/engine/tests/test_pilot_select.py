from pathlib import Path

import yaml

from pipeline.models import CandidateRecord
from pipeline.pilot_select import select_pilot, write_selection_audit


CONFIG = {
    "searchable_character_minimum": 100,
    "searchable_text_bonus": 3,
    "manageable_page_maximum": 20,
    "manageable_page_bonus": 2,
    "visual_evidence_bonus": 1,
    "keyword_weight": 4,
    "tier_keywords": {
        "tier_1": ["direct"],
        "tier_2": ["manifold"],
        "tier_3": ["nucleophilicity"],
        "tier_4": ["poisoning"],
    },
}


def candidate(
    path: str,
    tier: str,
    sha256: str,
    text: str,
    *,
    page_count: int = 10,
    visual_page_count: int = 0,
) -> CandidateRecord:
    return CandidateRecord(
        source_path=path,
        tier=tier,
        sha256=sha256,
        page_count=page_count,
        searchable_character_count=len(text),
        searchable_text=text,
        visual_page_count=visual_page_count,
    )


def test_selection_returns_one_paper_per_tier() -> None:
    candidates = [
        candidate("Tier1/direct.pdf", "tier_1", "1" * 64, "direct " * 30),
        candidate("Tier2/manifold.pdf", "tier_2", "2" * 64, "manifold " * 30),
        candidate(
            "Tier3/nucleophilicity.pdf",
            "tier_3",
            "3" * 64,
            "nucleophilicity " * 20,
        ),
        candidate("Tier4/poisoning.pdf", "tier_4", "4" * 64, "poisoning " * 30),
    ]

    audit = select_pilot(candidates, CONFIG)

    assert [item.tier for item in audit.selected] == [
        "tier_1",
        "tier_2",
        "tier_3",
        "tier_4",
    ]


def test_identical_sha256_is_excluded() -> None:
    candidates = [
        candidate("Tier1/a.pdf", "tier_1", "a" * 64, "direct " * 30),
        candidate("Tier1/b.pdf", "tier_1", "a" * 64, "direct " * 40),
    ]

    audit = select_pilot(candidates, CONFIG)

    assert len(audit.duplicate_exclusions) == 1
    assert audit.duplicate_exclusions[0].excluded_path == "Tier1/b.pdf"
    assert audit.duplicate_exclusions[0].reason == "identical_sha256"


def test_tie_breaker_uses_relative_path() -> None:
    candidates = [
        candidate("Tier1/b-paper.pdf", "tier_1", "b" * 64, "direct " * 30),
        candidate("Tier1/a-paper.pdf", "tier_1", "c" * 64, "direct " * 30),
    ]

    audit = select_pilot(candidates, CONFIG)

    assert audit.selected[0].source_path == "Tier1/a-paper.pdf"


def test_score_audit_preserves_component_evidence() -> None:
    paper = candidate(
        "Tier4/sulfur-poisoning.pdf",
        "tier_4",
        "d" * 64,
        "Catalyst poisoning was observed. " * 10,
        visual_page_count=2,
    )

    selected = select_pilot([paper], CONFIG).selected[0]

    assert selected.matched_keywords == ("poisoning",)
    assert selected.score_components == {
        "keyword_relevance": 4,
        "manageable_length": 2,
        "searchable_text": 3,
        "visual_evidence": 1,
    }
    assert selected.total_score == 10


def test_selection_audit_json_is_byte_stable(tmp_path) -> None:
    paper = candidate("Tier1/direct.pdf", "tier_1", "e" * 64, "direct " * 30)
    audit = select_pilot([paper], CONFIG)
    output = tmp_path / "selection.json"

    write_selection_audit(audit, output)
    first = output.read_bytes()
    write_selection_audit(audit, output)

    assert output.read_bytes() == first
    assert first.endswith(b"\n")


def test_tier_1_direct_substrate_and_bond_formation_outrank_incidental_terms() -> None:
    config = yaml.safe_load(Path("config/pilot.yaml").read_text(encoding="utf-8"))[
        "selection"
    ]
    candidates = [
        candidate(
            "Tier1/incidental.pdf",
            "tier_1",
            "f" * 64,
            "A carbonyl review cites a trifluoroethyl example.",
        ),
        candidate(
            "Tier1/direct.pdf",
            "tier_1",
            "0" * 64,
            "Morpholine 3,3,3-trifluoropropanamide reacts with Grignard reagents "
            "to form beta-fluoro unsaturated amides.",
        ),
    ]

    audit = select_pilot(candidates, config)

    assert audit.selected[0].source_path == "Tier1/direct.pdf"

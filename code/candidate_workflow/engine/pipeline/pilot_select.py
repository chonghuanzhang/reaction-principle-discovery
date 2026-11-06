"""Deterministic, auditable selection of one pilot paper per Tier."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path

from pipeline.models import (
    CandidateRecord,
    DuplicateExclusion,
    ScoredCandidate,
    SelectionAudit,
)


def score_candidate(
    candidate: CandidateRecord,
    tier: str,
    config: Mapping[str, object],
) -> ScoredCandidate:
    """Score one candidate using only explicit local evidence and weights."""

    keywords_by_tier = config["tier_keywords"]
    if not isinstance(keywords_by_tier, Mapping):
        raise ValueError("selection tier_keywords must be a mapping")
    keywords = keywords_by_tier.get(tier, [])
    if not isinstance(keywords, list):
        raise ValueError(f"keywords for {tier} must be a list")
    haystack = f"{candidate.source_path}\n{candidate.searchable_text}".casefold()
    matched = tuple(
        sorted({str(keyword) for keyword in keywords if str(keyword).casefold() in haystack})
    )
    components = {
        "keyword_relevance": len(matched) * int(config["keyword_weight"]),
        "manageable_length": (
            int(config["manageable_page_bonus"])
            if candidate.page_count <= int(config["manageable_page_maximum"])
            else 0
        ),
        "searchable_text": (
            int(config["searchable_text_bonus"])
            if candidate.searchable_character_count
            >= int(config["searchable_character_minimum"])
            else 0
        ),
        "visual_evidence": (
            int(config["visual_evidence_bonus"])
            if candidate.visual_page_count > 0
            else 0
        ),
    }
    total = sum(components.values())
    reason = (
        f"Selected by deterministic Tier scoring: total={total}; "
        f"matched_keywords={', '.join(matched) if matched else 'none'}."
    )
    return ScoredCandidate(
        source_path=candidate.source_path,
        tier=candidate.tier,
        sha256=candidate.sha256,
        page_count=candidate.page_count,
        total_score=total,
        score_components=components,
        matched_keywords=matched,
        selection_reason=reason,
    )


def select_pilot(
    candidates: list[CandidateRecord],
    config: Mapping[str, object],
) -> SelectionAudit:
    """Deduplicate, score, rank, and select one paper for every present Tier."""

    retained_by_sha: dict[str, CandidateRecord] = {}
    exclusions: list[DuplicateExclusion] = []
    for candidate in sorted(candidates, key=lambda item: item.source_path):
        retained = retained_by_sha.get(candidate.sha256)
        if retained is None:
            retained_by_sha[candidate.sha256] = candidate
            continue
        exclusions.append(
            DuplicateExclusion(
                excluded_path=candidate.source_path,
                retained_path=retained.source_path,
                sha256=candidate.sha256,
            )
        )

    scored = [
        score_candidate(candidate, candidate.tier, config)
        for candidate in retained_by_sha.values()
    ]
    ranked = sorted(
        scored,
        key=lambda item: (item.tier, -item.total_score, item.source_path),
    )
    selected: list[ScoredCandidate] = []
    for tier in sorted({item.tier for item in ranked}):
        selected.append(next(item for item in ranked if item.tier == tier))
    return SelectionAudit(
        selected=tuple(selected),
        ranked_candidates=tuple(ranked),
        duplicate_exclusions=tuple(exclusions),
        weights=dict(config),
    )


def write_selection_audit(audit: SelectionAudit, output: Path) -> None:
    """Write a selection audit deterministically and atomically."""

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    encoded = (
        json.dumps(
            audit.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    try:
        with temporary.open("wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)

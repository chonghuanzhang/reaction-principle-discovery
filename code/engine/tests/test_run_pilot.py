from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from pipeline.api_client import ApiResult, ApiUsage
from pipeline.run_pilot import (
    PilotRunError,
    revalidate_cached_raw,
    run_pilot,
    verify_sources,
)
from tests.fixtures.make_fixture_pdf import create_fixture_pdf


class SourceAwareClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.call_count = 0
        self.fail = fail

    def create_structured(self, model, input_text, schema, schema_name):
        self.call_count += 1
        if self.fail:
            raise RuntimeError("controlled client failure")
        metadata_text = input_text.split("SOURCE_METADATA\n", 1)[1].split(
            "\n\nSOURCE_TEXT", 1
        )[0]
        metadata = json.loads(metadata_text)
        tier = metadata["primary_tier"]
        return ApiResult(
            response_id=f"resp-{self.call_count}",
            returned_model=model,
            status="completed",
            parsed_output={
                "paper_id": f"{tier}-fixture",
                "source_file": metadata["source_file"],
                "sha256": metadata["sha256"],
                "bibliography": {
                    "title": "Fixture paper",
                    "authors": ["A. Author"],
                    "journal": "Fixture Journal",
                    "year": 2024,
                    "doi": None,
                },
                "primary_tier": tier,
                "secondary_tiers": [],
                "evidence_types": ["fixture_evidence"],
                "reaction_summary": {
                    "reaction_class": "UNKNOWN",
                    "electrophile": "UNKNOWN",
                    "nucleophile_or_partner": "UNKNOWN",
                    "nu_atom": "UNKNOWN",
                    "nu_subclass": "UNKNOWN",
                    "new_bond": "UNKNOWN",
                    "catalyst": "UNKNOWN",
                    "ligand": "UNKNOWN",
                    "base": "UNKNOWN",
                    "solvent": "UNKNOWN",
                    "temperature": "UNKNOWN",
                    "product_type": "UNKNOWN",
                    "selectivity": "UNKNOWN",
                    "proposed_intermediate": "UNKNOWN",
                    "activation_mode": "UNKNOWN",
                    "successful_scope": [],
                    "failed_scope": [],
                    "side_reactions": [],
                    "relevance_to_seed_reaction": "UNKNOWN",
                    "transferability_assessment": "UNKNOWN",
                },
                "evidence_items": [
                    {
                        "evidence_id": "E1",
                        "claim": "The fixture reports an 82% yield.",
                        "evidence_label": "LITERATURE FACT",
                        "quotation": "Experimental yield was 82%.",
                        "source_span_ids": ["P001-S001"],
                        "pdf_page": 1,
                        "additional_pdf_pages": [],
                        "section_context": "Fixture text",
                        "attribution": "author_observation",
                        "evidence_strength": "direct",
                        "visual_review_reference": None,
                        "reviewer_status": "pending",
                    }
                ],
                "uncertainties": [],
                "contradictions": [],
                "visual_review_pages": [2],
                "review_status": "pending",
            },
            usage=ApiUsage(input_tokens=100, output_tokens=50, total_tokens=150),
        )


class UnknownSpanClient(SourceAwareClient):
    def create_structured(self, model, input_text, schema, schema_name):
        result = super().create_structured(model, input_text, schema, schema_name)
        result.parsed_output["evidence_items"][0]["source_span_ids"] = ["P999-S999"]
        return result


def write_test_config(tmp_path: Path, source_root: Path) -> Path:
    seed_path = tmp_path / "seed_reaction.yaml"
    seed_path.write_text(
        yaml.safe_dump(
            {"freeze_version": "test-1", "seed_reaction_id": "SRC-CC-001"}
        ),
        encoding="utf-8",
    )
    config = {
        "version": "test",
        "source_directories": {
            "tier_1": "Tier1",
            "tier_2": "Tier2",
            "tier_3": "Tier3",
            "tier_4": "Tier4",
        },
        "model": "gpt-5.6-sol",
        "schema_version": "1.0",
        "prompt_version": "1.0",
        "max_chunk_characters": 10000,
        "schema_path": str(Path("config/extraction_schema.json").resolve()),
        "prompt_path": str(Path("config/prompts/evidence_extraction.md").resolve()),
        "seed_context_path": str(seed_path),
        "selection": {
            "searchable_character_minimum": 1,
            "searchable_text_bonus": 3,
            "manageable_page_maximum": 20,
            "manageable_page_bonus": 2,
            "visual_evidence_bonus": 1,
            "keyword_weight": 4,
            "tier_keywords": {
                "tier_1": ["experimental"],
                "tier_2": ["experimental"],
                "tier_3": ["experimental"],
                "tier_4": ["experimental"],
            },
        },
    }
    config_path = tmp_path / "pilot.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return config_path


@pytest.fixture
def source_root(tmp_path: Path) -> Path:
    root = tmp_path / "sources"
    for tier in ("Tier1", "Tier2", "Tier3", "Tier4"):
        directory = root / tier
        directory.mkdir(parents=True)
        create_fixture_pdf(directory / "paper.pdf")
    return root


def test_resume_skips_completed_validated_papers(tmp_path: Path, source_root: Path) -> None:
    config = write_test_config(tmp_path, source_root)
    output_root = tmp_path / "output"
    client = SourceAwareClient()

    first = run_pilot(config, source_root, output_root, client=client, resume=True)
    second = run_pilot(config, source_root, output_root, client=client, resume=True)

    assert client.call_count == 4
    assert first.api_call_count == 4
    assert second.api_call_count == 0
    assert second.reused_paper_count == 4


def test_seed_context_change_invalidates_cached_pilot_records(
    tmp_path: Path, source_root: Path
) -> None:
    config = write_test_config(tmp_path, source_root)
    output_root = tmp_path / "output"
    client = SourceAwareClient()
    run_pilot(config, source_root, output_root, client=client, resume=True)
    seed_path = tmp_path / "seed_reaction.yaml"
    seed_path.write_text(
        yaml.safe_dump(
            {"freeze_version": "test-2", "seed_reaction_id": "SRC-CC-001"}
        ),
        encoding="utf-8",
    )

    second = run_pilot(config, source_root, output_root, client=client, resume=True)

    assert client.call_count == 8
    assert second.api_call_count == 4


def test_failed_run_does_not_replace_validated_record(
    tmp_path: Path, source_root: Path
) -> None:
    config = write_test_config(tmp_path, source_root)
    output_root = tmp_path / "output"
    run_pilot(config, source_root, output_root, client=SourceAwareClient())
    validated = sorted((output_root / "derived" / "pilot").glob("*/validated.json"))[0]
    before = validated.read_bytes()

    with pytest.raises(PilotRunError):
        run_pilot(
            config,
            source_root,
            output_root,
            client=SourceAwareClient(fail=True),
            resume=False,
        )

    assert validated.read_bytes() == before


def test_requested_tier_subset_avoids_recalling_completed_other_tiers(
    tmp_path: Path, source_root: Path
) -> None:
    config = write_test_config(tmp_path, source_root)
    client = SourceAwareClient()

    manifest = run_pilot(
        config,
        source_root,
        tmp_path / "output",
        client=client,
        tiers={"tier_2"},
    )

    assert client.call_count == 1
    assert manifest.api_call_count == 1
    assert manifest.paper_statuses["Tier1/paper.pdf"] == "not_requested"
    assert manifest.paper_statuses["Tier2/paper.pdf"] == "validated"


def test_cached_raw_can_be_revalidated_without_api_call(
    tmp_path: Path, source_root: Path
) -> None:
    config = write_test_config(tmp_path, source_root)
    output_root = tmp_path / "output"
    client = SourceAwareClient()
    run_pilot(config, source_root, output_root, client=client, tiers={"tier_2"})
    validated = next((output_root / "derived" / "pilot").glob("tier_2-*/validated.json"))
    validated.unlink()

    statuses = revalidate_cached_raw(
        config, source_root, output_root, tiers={"tier_2"}
    )

    assert client.call_count == 1
    assert validated.is_file()
    assert statuses == {"Tier2/paper.pdf": "revalidated"}


def test_raw_response_is_preserved_before_grounding_failure(
    tmp_path: Path, source_root: Path
) -> None:
    config = write_test_config(tmp_path, source_root)
    output_root = tmp_path / "output"

    with pytest.raises(PilotRunError):
        run_pilot(
            config,
            source_root,
            output_root,
            client=UnknownSpanClient(),
            tiers={"tier_3"},
        )

    raw_files = list((output_root / "derived" / "pilot").glob("tier_3-*/raw.json"))
    assert len(raw_files) == 1
    raw = json.loads(raw_files[0].read_text(encoding="utf-8"))
    assert raw["extraction"]["evidence_items"][0]["source_span_ids"] == [
        "P999-S999"
    ]


def test_verify_sources_uses_same_pdf_scope_as_pilot_inventory(
    tmp_path: Path, source_root: Path
) -> None:
    config = write_test_config(tmp_path, source_root)
    output_root = tmp_path / "output"
    run_pilot(config, source_root, output_root, client=SourceAwareClient())
    (source_root / "Tier1" / "notes.zip").write_bytes(b"not part of PDF pilot")

    verify_sources(config, source_root, output_root)

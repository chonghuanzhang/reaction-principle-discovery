from pathlib import Path

import pytest

from pipeline.seed_inputs import (
    SeedInputError,
    assert_principle_building_safe,
    inventory_seed_inputs,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_seed_inventory_separates_principle_inputs_from_hidden_answers(tmp_path):
    _write(tmp_path / "manuscript.docx", "public seed manuscript")
    _write(tmp_path / "si.docx", "public seed supporting information")
    _write(tmp_path / "results.xlsx", "hidden outcomes")
    config = {
        "sources": [
            {"path": "manuscript.docx", "role": "manuscript", "access_class": "principle_building"},
            {"path": "si.docx", "role": "supporting_information", "access_class": "principle_building"},
            {"path": "results.xlsx", "role": "experimental_results", "access_class": "hidden_answer"},
        ]
    }

    inventory = inventory_seed_inputs(tmp_path, config)
    assert_principle_building_safe(inventory)

    assert [item.path for item in inventory.principle_building_files] == [
        "manuscript.docx",
        "si.docx",
    ]
    assert [item.path for item in inventory.hidden_answer_files] == ["results.xlsx"]
    assert inventory.hidden_answers_revealed is False


def test_seed_inventory_rejects_same_path_in_both_access_classes(tmp_path):
    _write(tmp_path / "results.xlsx", "hidden outcomes")
    config = {
        "sources": [
            {"path": "results.xlsx", "role": "seed_data", "access_class": "principle_building"},
            {"path": "results.xlsx", "role": "experimental_results", "access_class": "hidden_answer"},
        ]
    }

    with pytest.raises(SeedInputError, match="multiple access classes"):
        inventory_seed_inputs(tmp_path, config)


def test_seed_inventory_rejects_hidden_content_copied_into_build_inputs(tmp_path):
    _write(tmp_path / "public-copy.docx", "same secret result bytes")
    _write(tmp_path / "results.xlsx", "same secret result bytes")
    config = {
        "sources": [
            {"path": "public-copy.docx", "role": "manuscript", "access_class": "principle_building"},
            {"path": "results.xlsx", "role": "experimental_results", "access_class": "hidden_answer"},
        ]
    }

    with pytest.raises(SeedInputError, match="same file content"):
        inventory_seed_inputs(tmp_path, config)


def test_seed_inventory_fails_closed_when_configured_file_is_missing(tmp_path):
    config = {
        "sources": [
            {"path": "missing.docx", "role": "manuscript", "access_class": "principle_building"}
        ]
    }

    with pytest.raises(SeedInputError, match="missing configured seed input"):
        inventory_seed_inputs(tmp_path, config)

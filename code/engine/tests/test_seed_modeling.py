import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from pipeline.api_client import ApiResult, ApiUsage
from pipeline.seed_inputs import SeedInputInventory
from pipeline.seed_modeling import SeedModelingError, build_seed_input, model_seed_reaction


def _docx(path: Path, paragraphs: list[str]) -> None:
    body = "".join(
        f'<w:p><w:r><w:t>{text}</w:t></w:r></w:p>' for text in paragraphs
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", xml)


def _inventory(tmp_path: Path) -> SeedInputInventory:
    manuscript = tmp_path / "manuscript.docx"
    hidden = tmp_path / "results.xlsx"
    _docx(
        manuscript,
        [
            "The palladium catalyst affords selective monodefluorinative coupling.",
            "The organoboron partner forms the new carbon-carbon bond.",
        ],
    )
    hidden.write_text("SECRET_SH_OUTCOME", encoding="utf-8")
    return SeedInputInventory(
        source_root=str(tmp_path),
        files=(
            {
                "path": "manuscript.docx",
                "role": "manuscript",
                "access_class": "principle_building",
                "sha256": "a" * 64,
                "byte_size": manuscript.stat().st_size,
            },
            {
                "path": "results.xlsx",
                "role": "experimental_results",
                "access_class": "hidden_answer",
                "sha256": "b" * 64,
                "byte_size": hidden.stat().st_size,
            },
        ),
        principle_building_digest="c" * 64,
        hidden_answer_digest="d" * 64,
    )


def _payload(quotation: str | None = None) -> dict:
    quote = quotation or "The palladium catalyst affords selective monodefluorinative coupling."
    return {
        "seed_evidence": [
            {
                "evidence": {
                    "evidence_id": "SEED-E001",
                    "source_type": "seed",
                    "source_id": "manuscript.docx",
                    "evidence_label": "EXPERIMENTAL FACT",
                    "quotation": quote,
                    "locator": "paragraph:0001",
                },
                "claim": "Selective monodefluorinative coupling is observed.",
                "evidence_type": "selectivity boundary",
                "reviewer_status": "pending",
            }
        ],
        "seed_mechanism": {
            "seed_reaction_id": "SEED-001",
            "reaction_center": ["trifluoroethyl carbonyl carbon"],
            "electrophile_state": ["palladium-activated substrate"],
            "nucleophile_state": ["organoboron-derived carbon"],
            "bond_changes": ["C-C formation", "C-F cleavage"],
            "reactive_intermediates": ["fluorinated alkene-like intermediate"],
            "elementary_steps": ["activation", "trapping"],
            "electronic_requirements": ["selective C-F activation"],
            "steric_requirements": [],
            "catalyst_roles": ["palladium-mediated activation"],
            "condition_window": ["base-compatible"],
            "successful_scope": ["organoboron"],
            "failed_scope": [],
            "competing_pathways": ["over-defluorination"],
            "evidence_ids": ["SEED-E001"],
            "confidence": "medium",
        },
        "seed_principle": {
            "seed_principle_id": "SP-001",
            "title": "Selective activation and trapping",
            "claim": "Selective activation permits trapping before further defluorination.",
            "reaction_center": ["trifluoroethyl carbonyl carbon"],
            "reactive_intermediates": ["fluorinated alkene-like intermediate"],
            "electronic_requirements": ["selective C-F activation"],
            "nucleophile_requirements": ["accessible reactive form"],
            "catalyst_roles": ["activation"],
            "condition_window": ["base-compatible"],
            "failure_boundaries": ["over-defluorination"],
            "supporting_seed_evidence": ["SEED-E001"],
            "confidence": "medium",
            "uncertainty": ["intermediate is inferred"],
        },
    }


class FakeClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls = 0

    def create_structured(self, model, input_text, schema, schema_name):
        self.calls += 1
        return ApiResult(
            response_id="seed-response",
            returned_model=model,
            status="completed",
            parsed_output=self.payload,
            usage=ApiUsage(input_tokens=10, output_tokens=5, total_tokens=15),
        )


def test_seed_input_contains_only_allowlisted_principle_building_sources(tmp_path):
    prompt = build_seed_input(_inventory(tmp_path), "Extract seed mechanism evidence.")

    assert "manuscript.docx" in prompt
    assert "selective monodefluorinative coupling" in prompt
    assert "results.xlsx" not in prompt
    assert "SECRET_SH_OUTCOME" not in prompt


def test_seed_modeling_grounds_quotes_and_reuses_cache(tmp_path):
    inventory = _inventory(tmp_path)
    client = FakeClient(_payload())
    config = {"model": "fixture", "prompt_text": "Extract.", "prompt_version": "1"}

    first = model_seed_reaction(inventory, client, config, tmp_path / "cache")
    second = model_seed_reaction(inventory, client, config, tmp_path / "cache")

    assert first.status == "validated"
    assert second.status == "reused"
    assert client.calls == 1
    saved = json.loads((tmp_path / "cache" / first.cache_key / "validated.json").read_text())
    assert saved["seed_mechanism"]["evidence_ids"] == ["SEED-E001"]


def test_seed_modeling_rejects_quotation_not_found_at_locator(tmp_path):
    client = FakeClient(_payload("A quotation that is not in the source."))

    with pytest.raises(SeedModelingError, match="quotation"):
        model_seed_reaction(
            _inventory(tmp_path),
            client,
            {"model": "fixture", "prompt_text": "Extract.", "prompt_version": "1"},
            tmp_path / "cache",
        )

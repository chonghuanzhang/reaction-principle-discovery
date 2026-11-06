from pathlib import Path

import pytest

from pipeline.api_client import ApiResult, ApiUsage
from pipeline.mechanism_normalization import (
    MechanismNormalizationError,
    build_normalization_input,
    normalize_record,
    normalization_schema,
)


class FakeClient:
    def __init__(self, output: dict):
        self.output = output
        self.calls = 0

    def create_structured(self, model, input_text, schema, schema_name):
        self.calls += 1
        return ApiResult(
            response_id="resp-1",
            returned_model=model,
            status="completed",
            parsed_output=self.output,
            usage=ApiUsage(input_tokens=100, output_tokens=50, total_tokens=150),
        )


def _record() -> dict:
    return {
        "cache_key": "literature-cache",
        "hidden_answer": "KNOWN_RETROSPECTIVE_SECRET",
        "extraction": {
            "paper_id": "paper-1",
            "source_file": "papers/one.pdf",
            "sha256": "a" * 64,
            "primary_tier": "tier_2",
            "secondary_tiers": [],
            "evidence_types": ["shared_reaction_manifold"],
            "reaction_summary": {
                "reaction_class": "nucleophilic trapping",
                "electrophile": "gem-difluoroalkene",
                "nucleophile_or_partner": "thiophenol",
                "nu_atom": "S",
                "nu_subclass": "aryl thiol",
                "new_bond": "C-S",
                "catalyst": "none",
                "ligand": "none",
                "base": "base",
                "solvent": "polar solvent",
                "temperature": "ambient",
                "product_type": "monofluoroalkene",
                "selectivity": "monodefluorinative",
                "proposed_intermediate": "carbanion",
                "activation_mode": "addition-elimination",
                "successful_scope": ["aryl thiol"],
                "failed_scope": [],
                "side_reactions": ["oxidation"],
                "relevance_to_seed_reaction": "shared fluorinated alkene manifold",
                "transferability_assessment": "conditional",
            },
            "evidence_items": [
                {
                    "evidence_id": "E001",
                    "claim": "Thiophenol traps the fluorinated alkene.",
                    "evidence_label": "LITERATURE FACT",
                    "quotation": "Thiophenol afforded the monofluoroalkene product.",
                    "source_span_ids": ["P003-S004"],
                    "pdf_page": 3,
                    "additional_pdf_pages": [],
                    "section_context": "Results",
                    "attribution": "author_observation",
                    "evidence_strength": "direct",
                    "visual_review_reference": None,
                    "reviewer_status": "pending",
                }
            ],
            "uncertainties": [],
            "contradictions": [],
            "visual_review_pages": [],
            "review_status": "pending",
        },
    }


def _model_output(source_evidence_id: str = "E001") -> dict:
    return {
        "mechanism_evidence": [
            {
                "mechanism_evidence_id": "ME-001",
                "source_paper_id": "paper-1",
                "source_evidence_ids": [source_evidence_id],
                "evidence_type": "elementary_step",
                "elementary_step": "nucleophilic trapping",
                "starting_state": "fluorinated alkene plus thiol",
                "ending_state": "C-S bonded intermediate",
                "bond_changes": ["form C-S"],
                "catalyst_role": "none established",
                "nucleophile_requirements": ["sulfur nucleophile"],
                "electrophile_requirements": ["fluorinated alkene"],
                "condition_requirements": ["base-compatible"],
                "observed_outcome": "monofluoroalkene product",
                "failure_mode": None,
                "evidence_label": "LITERATURE FACT",
                "evidence_strength": "direct",
                "quotation": "MODEL MUST NOT CONTROL THIS",
                "pdf_page": 999,
                "confidence": "high",
            }
        ],
        "boundary_constraints": [],
        "source_revisit_requests": [],
    }


def _config() -> dict:
    return {
        "model": "test-model",
        "prompt_version": "1.0",
        "schema_version": "1.0",
        "prompt_text": "Normalize mechanism evidence without outside knowledge.",
    }


def test_normalization_input_uses_allowlisted_literature_fields_only():
    text = build_normalization_input(_record(), _config()["prompt_text"])

    assert "Thiophenol traps the fluorinated alkene" in text
    assert "KNOWN_RETROSPECTIVE_SECRET" not in text


def test_normalization_materializes_authoritative_quote_and_page(tmp_path):
    client = FakeClient(_model_output())

    result = normalize_record(_record(), client, _config(), tmp_path)

    item = result.mechanism_evidence[0]
    assert item.quotation == "Thiophenol afforded the monofluoroalkene product."
    assert item.pdf_page == 3
    assert result.status == "validated"


def test_normalization_rejects_unknown_source_evidence_id(tmp_path):
    client = FakeClient(_model_output("E999"))

    with pytest.raises(MechanismNormalizationError, match="unknown source evidence ID"):
        normalize_record(_record(), client, _config(), tmp_path)


def test_normalization_resolves_constraint_mechanism_ids_to_source_evidence(tmp_path):
    output = _model_output()
    output["boundary_constraints"] = [
        {
            "constraint_id": "BC-001",
            "dimension": "electronic",
            "applies_to": ["fluorinated alkene"],
            "direction": "promotes",
            "statement": "Sulfur trapping is observed for this electrophile.",
            "quantitative_range": None,
            "supporting_evidence_ids": ["ME-001"],
            "contradictory_evidence_ids": [],
            "confidence": "high",
        }
    ]

    result = normalize_record(_record(), FakeClient(output), _config(), tmp_path)

    assert result.boundary_constraints[0].supporting_evidence_ids == ("E001",)


def test_normalization_accepts_source_spans_grounded_in_record_contradictions(tmp_path):
    record = _record()
    record["extraction"]["contradictions"] = [
        "The table and procedure report different yields (P007-S014)."
    ]
    output = _model_output()
    output["boundary_constraints"] = [
        {
            "constraint_id": "BC-001",
            "dimension": "condition",
            "applies_to": ["reported yield"],
            "direction": "threshold",
            "statement": "The exact reported yield requires reconciliation.",
            "quantitative_range": None,
            "supporting_evidence_ids": ["ME-001"],
            "contradictory_evidence_ids": ["P007-S014"],
            "confidence": "medium",
        }
    ]

    result = normalize_record(record, FakeClient(output), _config(), tmp_path)

    assert result.boundary_constraints[0].contradictory_evidence_ids == ("P007-S014",)


def test_normalization_reuses_matching_validated_cache(tmp_path):
    client = FakeClient(_model_output())

    first = normalize_record(_record(), client, _config(), tmp_path)
    second = normalize_record(_record(), client, _config(), tmp_path)

    assert first.status == "validated"
    assert second.status == "reused"
    assert client.calls == 1


def test_normalization_schema_requires_every_object_property():
    schema = normalization_schema()
    objects = [schema, *schema.get("$defs", {}).values()]

    for definition in objects:
        if definition.get("type") != "object":
            continue
        assert set(definition.get("required", [])) == set(definition.get("properties", {}))

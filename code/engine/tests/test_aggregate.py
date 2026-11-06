from __future__ import annotations

import json
from pathlib import Path

from pipeline.aggregate import aggregate_validated_records, write_calibration_summary
from tests.test_validate import valid_record


def _write_record(root: Path, tier: int, suffix: str, token_base: int) -> None:
    record = valid_record()
    record["paper_id"] = f"tier-{tier}-{suffix}"
    record["source_file"] = f"Tier{tier}/{suffix}.pdf"
    record["primary_tier"] = f"tier_{tier}"
    record["sha256"] = str(tier) * 64
    record["bibliography"]["title"] = f"Paper {suffix}"
    record["reaction_summary"].update(
        {
            "electrophile": "Trifluoroethyl amide",
            "nucleophile_or_partner": "Thiolate",
            "nu_atom": "S",
            "nu_subclass": "thiolate",
            "new_bond": "C-S",
            "catalyst": "Pd",
            "ligand": "L1",
            "base": "carbonate",
            "solvent": "THF",
            "temperature": "40 C",
            "product_type": "monofluoroalkene",
            "activation_mode": "beta-fluoride elimination",
            "successful_scope": ["aryl thiolate"],
            "failed_scope": ["alkyl thiolate"],
            "side_reactions": ["catalyst poisoning"],
            "relevance_to_seed_reaction": "shared_reaction_manifold",
            "transferability_assessment": "Possible with catalyst-risk controls.",
        }
    )
    record["evidence_items"][0]["evidence_id"] = f"E-{suffix}"
    record["contradictions"] = [f"Contradiction {suffix}"]
    output = root / f"tier_{tier}-{suffix}" / "validated.json"
    output.parent.mkdir(parents=True)
    output.write_text(
        json.dumps(
            {
                "cache_key": suffix,
                "api": {
                    "response_id": f"resp-{suffix}",
                    "returned_model": "gpt-5.6-sol",
                    "status": "completed",
                    "usage": {
                        "input_tokens": token_base,
                        "output_tokens": token_base // 2,
                        "total_tokens": token_base + token_base // 2,
                    },
                },
                "validation": {"is_valid": True, "errors": [], "warnings": []},
                "extraction": record,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_aggregation_writes_deterministic_evidence_tables(tmp_path: Path) -> None:
    corpus_root = tmp_path / "papers"
    _write_record(corpus_root, 2, "b", 200)
    _write_record(corpus_root, 1, "a", 100)
    output_root = tmp_path / "synthesis"

    summary = aggregate_validated_records(corpus_root, output_root)
    first = {path.name: path.read_bytes() for path in sorted(output_root.iterdir())}
    second_summary = aggregate_validated_records(corpus_root, output_root)
    second = {path.name: path.read_bytes() for path in sorted(output_root.iterdir())}

    assert summary == second_summary
    assert first == second
    assert summary.paper_count == 2
    assert summary.evidence_item_count == 2
    assert summary.total_tokens == 450
    assert set(first) == {
        "api_usage_summary.json",
        "catalyst_compatibility_matrix.csv",
        "condition_matrix.csv",
        "contradiction_log.csv",
        "evidence_ledger.jsonl",
        "nucleophile_matrix.csv",
        "paper_index.csv",
        "reaction_evidence_matrix.csv",
        "scope_and_failure_matrix.csv",
    }
    assert first["paper_index.csv"].decode().splitlines()[1].startswith(
        "tier_1,Tier1/a.pdf"
    )
    assert "E-a" in first["evidence_ledger.jsonl"].decode()
    assert "catalyst poisoning" in first["scope_and_failure_matrix.csv"].decode()


def test_calibration_summary_reports_failures_and_review_burden(tmp_path: Path) -> None:
    output = tmp_path / "calibration_summary.json"
    aggregation = {
        "paper_count": 2,
        "evidence_item_count": 2,
        "visual_review_page_count": 5,
        "contradiction_count": 2,
        "input_tokens": 300,
        "output_tokens": 150,
        "total_tokens": 450,
    }
    manifest = {
        "paper_statuses": {
            "Tier1/a.pdf": "validated",
            "Tier2/b.pdf": "validation_failed",
        },
        "results": [
            {"source_path": "Tier1/a.pdf", "status": "validated"},
            {
                "source_path": "Tier2/b.pdf",
                "status": "validation_failed",
                "failure_reason": "quotation_not_found",
            },
        ],
    }

    write_calibration_summary(manifest, aggregation, output)
    payload = json.loads(output.read_text())

    assert payload["completed_paper_count"] == 1
    assert payload["failed_paper_count"] == 1
    assert payload["visual_review_page_count"] == 5
    assert payload["failures"] == [
        {
            "failure_reason": "quotation_not_found",
            "source_path": "Tier2/b.pdf",
            "status": "validation_failed",
        }
    ]


def test_aggregation_counts_locally_flagged_visual_pages(tmp_path: Path) -> None:
    corpus_root = tmp_path / "papers"
    _write_record(corpus_root, 1, "a", 100)
    queue_path = corpus_root / "tier_1-a" / "visual_review_queue.json"
    queue_path.write_text(
        json.dumps(
            {
                "source_file": "Tier1/a.pdf",
                "sha256": "1" * 64,
                "pdf_pages": [1, 2],
                "status": "pending",
            }
        ),
        encoding="utf-8",
    )

    summary = aggregate_validated_records(corpus_root, tmp_path / "synthesis")

    assert summary.visual_review_page_count == 2


def test_aggregation_can_be_scoped_to_current_queue(tmp_path: Path) -> None:
    corpus_root = tmp_path / "papers"
    _write_record(corpus_root, 1, "current", 100)
    _write_record(corpus_root, 2, "historical", 900)
    (corpus_root / "tier_2-historical" / "visual_review_queue.json").write_text(
        json.dumps(
            {
                "source_file": "Tier2/historical.pdf",
                "sha256": "2" * 64,
                "pdf_pages": [1, 2, 3],
                "status": "pending",
            }
        ),
        encoding="utf-8",
    )

    summary = aggregate_validated_records(
        corpus_root,
        tmp_path / "synthesis",
        source_paths={"Tier1/current.pdf"},
    )

    assert summary.paper_count == 1
    assert summary.total_tokens == 150
    assert summary.visual_review_page_count == 0
    assert "historical" not in (tmp_path / "synthesis/paper_index.csv").read_text()

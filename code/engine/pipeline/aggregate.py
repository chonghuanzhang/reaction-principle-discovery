"""Deterministic, model-free aggregation of validated literature evidence."""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from pipeline.run_pilot import _atomic_json


@dataclass(frozen=True)
class AggregationSummary:
    paper_count: int
    evidence_item_count: int
    visual_review_page_count: int
    contradiction_count: int
    input_tokens: int
    output_tokens: int
    total_tokens: int


def _atomic_text(output: Path, text: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


def _write_csv(output: Path, fieldnames: list[str], rows: list[dict]) -> None:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row.get(field, "") for field in fieldnames})
    _atomic_text(output, stream.getvalue())


def _joined(value: object) -> str:
    if isinstance(value, list):
        return " | ".join(str(item) for item in value)
    return "" if value is None else str(value)


def aggregate_validated_records(
    corpus_root: Path,
    output_root: Path,
    source_paths: set[str] | None = None,
) -> AggregationSummary:
    """Aggregate validated records without reading raw response artifacts."""

    records: list[dict] = []
    for path in sorted(corpus_root.glob("*/validated.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not payload.get("validation", {}).get("is_valid"):
            continue
        if (
            source_paths is not None
            and payload.get("extraction", {}).get("source_file") not in source_paths
        ):
            continue
        records.append(payload)
    records.sort(
        key=lambda payload: (
            payload["extraction"]["primary_tier"],
            payload["extraction"]["source_file"],
        )
    )

    paper_rows: list[dict] = []
    evidence_rows: list[dict] = []
    reaction_rows: list[dict] = []
    nucleophile_rows: list[dict] = []
    condition_rows: list[dict] = []
    scope_rows: list[dict] = []
    catalyst_rows: list[dict] = []
    contradiction_rows: list[dict] = []
    model_counts: dict[str, int] = {}
    input_tokens = output_tokens = total_tokens = 0
    visual_review_pages: set[tuple[str, int]] = set()
    for queue_path in sorted(corpus_root.glob("*/visual_review_queue.json")):
        queue = json.loads(queue_path.read_text(encoding="utf-8"))
        source_file = str(queue.get("source_file", ""))
        if source_paths is not None and source_file not in source_paths:
            continue
        for page in queue.get("pdf_pages", []):
            visual_review_pages.add((source_file, int(page)))

    for payload in records:
        extraction = payload["extraction"]
        bibliography = extraction["bibliography"]
        summary = extraction["reaction_summary"]
        api = payload.get("api", {})
        usage = api.get("usage", {})
        model = str(api.get("returned_model", ""))
        if model:
            model_counts[model] = model_counts.get(model, 0) + 1
        input_tokens += int(usage.get("input_tokens") or 0)
        output_tokens += int(usage.get("output_tokens") or 0)
        total_tokens += int(usage.get("total_tokens") or 0)
        source_file = extraction["source_file"]
        for page in extraction.get("visual_review_pages", []):
            visual_review_pages.add((source_file, int(page)))

        paper_rows.append(
            {
                "primary_tier": extraction["primary_tier"],
                "source_file": source_file,
                "paper_id": extraction["paper_id"],
                "sha256": extraction["sha256"],
                "title": bibliography["title"],
                "authors": _joined(bibliography["authors"]),
                "journal": bibliography["journal"],
                "year": bibliography["year"],
                "doi": bibliography["doi"],
                "evidence_item_count": len(extraction["evidence_items"]),
                "contradiction_count": len(extraction["contradictions"]),
                "review_status": extraction["review_status"],
                "returned_model": model,
            }
        )
        nucleophile_rows.append(
            {
                "primary_tier": extraction["primary_tier"],
                "source_file": source_file,
                "nucleophile_or_partner": summary["nucleophile_or_partner"],
                "nu_atom": summary["nu_atom"],
                "nu_subclass": summary["nu_subclass"],
                "new_bond": summary["new_bond"],
                "relevance_to_seed_reaction": summary["relevance_to_seed_reaction"],
                "transferability_assessment": summary["transferability_assessment"],
            }
        )
        condition_rows.append(
            {
                "primary_tier": extraction["primary_tier"],
                "source_file": source_file,
                "catalyst": summary["catalyst"],
                "ligand": summary["ligand"],
                "base": summary["base"],
                "solvent": summary["solvent"],
                "temperature": summary["temperature"],
                "activation_mode": summary["activation_mode"],
            }
        )
        catalyst_rows.append(
            {
                "primary_tier": extraction["primary_tier"],
                "source_file": source_file,
                "catalyst": summary["catalyst"],
                "ligand": summary["ligand"],
                "failed_scope": _joined(summary["failed_scope"]),
                "side_reactions": _joined(summary["side_reactions"]),
            }
        )
        for category, entries in (
            ("successful_scope", summary["successful_scope"]),
            ("failed_scope", summary["failed_scope"]),
            ("side_reaction", summary["side_reactions"]),
        ):
            for entry in entries:
                scope_rows.append(
                    {
                        "primary_tier": extraction["primary_tier"],
                        "source_file": source_file,
                        "category": category,
                        "statement": entry,
                    }
                )
        for contradiction in extraction["contradictions"]:
            contradiction_rows.append(
                {
                    "primary_tier": extraction["primary_tier"],
                    "source_file": source_file,
                    "contradiction": contradiction,
                }
            )
        for evidence in sorted(
            extraction["evidence_items"], key=lambda item: item["evidence_id"]
        ):
            base = {
                "primary_tier": extraction["primary_tier"],
                "source_file": source_file,
                "paper_id": extraction["paper_id"],
                "evidence_id": evidence["evidence_id"],
                "claim": evidence["claim"],
                "evidence_label": evidence["evidence_label"],
                "attribution": evidence["attribution"],
                "evidence_strength": evidence["evidence_strength"],
                "pdf_page": evidence["pdf_page"],
                "additional_pdf_pages": evidence["additional_pdf_pages"],
                "source_span_ids": evidence["source_span_ids"],
                "quotation": evidence["quotation"],
                "visual_review_reference": evidence["visual_review_reference"],
            }
            evidence_rows.append(base)
            reaction_rows.append(
                {
                    **{key: base[key] for key in (
                        "primary_tier",
                        "source_file",
                        "evidence_id",
                        "claim",
                        "evidence_label",
                        "pdf_page",
                        "source_span_ids",
                    )},
                    "electrophile": summary["electrophile"],
                    "nucleophile_or_partner": summary["nucleophile_or_partner"],
                    "nu_atom": summary["nu_atom"],
                    "nu_subclass": summary["nu_subclass"],
                    "new_bond": summary["new_bond"],
                    "product_type": summary["product_type"],
                    "activation_mode": summary["activation_mode"],
                }
            )

    output_root.mkdir(parents=True, exist_ok=True)
    _write_csv(
        output_root / "paper_index.csv",
        [
            "primary_tier", "source_file", "paper_id", "sha256", "title",
            "authors", "journal", "year", "doi", "evidence_item_count",
            "contradiction_count", "review_status", "returned_model",
        ],
        paper_rows,
    )
    evidence_text = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
        for row in evidence_rows
    )
    _atomic_text(output_root / "evidence_ledger.jsonl", evidence_text)
    _write_csv(
        output_root / "reaction_evidence_matrix.csv",
        [
            "primary_tier", "source_file", "evidence_id", "electrophile",
            "nucleophile_or_partner", "nu_atom", "nu_subclass", "new_bond",
            "product_type", "activation_mode", "claim", "evidence_label",
            "pdf_page", "source_span_ids",
        ],
        [
            {**row, "source_span_ids": _joined(row["source_span_ids"])}
            for row in reaction_rows
        ],
    )
    _write_csv(
        output_root / "nucleophile_matrix.csv",
        [
            "primary_tier", "source_file", "nucleophile_or_partner", "nu_atom",
            "nu_subclass", "new_bond", "relevance_to_seed_reaction",
            "transferability_assessment",
        ],
        nucleophile_rows,
    )
    _write_csv(
        output_root / "condition_matrix.csv",
        [
            "primary_tier", "source_file", "catalyst", "ligand", "base",
            "solvent", "temperature", "activation_mode",
        ],
        condition_rows,
    )
    _write_csv(
        output_root / "scope_and_failure_matrix.csv",
        ["primary_tier", "source_file", "category", "statement"],
        scope_rows,
    )
    _write_csv(
        output_root / "catalyst_compatibility_matrix.csv",
        [
            "primary_tier", "source_file", "catalyst", "ligand",
            "failed_scope", "side_reactions",
        ],
        catalyst_rows,
    )
    _write_csv(
        output_root / "contradiction_log.csv",
        ["primary_tier", "source_file", "contradiction"],
        contradiction_rows,
    )
    summary = AggregationSummary(
        paper_count=len(records),
        evidence_item_count=len(evidence_rows),
        visual_review_page_count=len(visual_review_pages),
        contradiction_count=len(contradiction_rows),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
    )
    _atomic_json(
        output_root / "api_usage_summary.json",
        {**asdict(summary), "returned_model_counts": dict(sorted(model_counts.items()))},
    )
    return summary


def write_calibration_summary(
    manifest: dict,
    aggregation: AggregationSummary | dict,
    output: Path,
) -> None:
    """Write a compact, model-free calibration checkpoint."""

    metrics = asdict(aggregation) if isinstance(aggregation, AggregationSummary) else dict(aggregation)
    results = sorted(manifest.get("results", []), key=lambda row: row["source_path"])
    completed = [row for row in results if row.get("status") in {"validated", "reused"}]
    failures = [
        {
            "source_path": row["source_path"],
            "status": row["status"],
            "failure_reason": row.get("failure_reason"),
        }
        for row in results
        if row.get("status") not in {"validated", "reused"}
    ]
    _atomic_json(
        output,
        {
            **metrics,
            "completed_paper_count": len(completed),
            "failed_paper_count": len(failures),
            "failures": failures,
            "queue_digest": manifest.get("queue_digest"),
            "seed_context_digest": manifest.get("seed_context_digest"),
            "prompt_digest": manifest.get("prompt_digest"),
            "schema_digest": manifest.get("schema_digest"),
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--calibration-summary", type=Path)
    args = parser.parse_args()
    summary = aggregate_validated_records(args.corpus_root, args.output_root)
    if args.manifest and args.calibration_summary:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        write_calibration_summary(manifest, summary, args.calibration_summary)
    print(json.dumps(asdict(summary), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

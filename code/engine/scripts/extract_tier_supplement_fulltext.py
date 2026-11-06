"""Extract and ground evidence from downloaded Tier supplement PDFs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from pipeline.api_client import ChatCompletionsStructuredClient, read_keychain_secret
from pipeline.evidence_registry import _atomic_json
from pipeline.grounding import build_source_spans, ground_extraction
from pipeline.models import SourceRecord
from pipeline.pdf_extract import extract_pages
from pipeline.validate import validate_extraction
from pipeline.prompt_builder import build_extraction_input, build_page_chunks


PROMPT = """
Extract only evidence stated in the supplied PDF pages. This is a blinded
literature evidence task. Do not use outside knowledge, project outcomes, named
target substrates, or expected answers. Return one object matching the supplied
schema. Preserve source metadata and primary Tier. Every author-observation or
source-metadata evidence item must cite supplied source_span_ids and quote only
those spans. Use UNKNOWN for missing information. Distinguish author hypotheses
from direct observations. Record conditions, mechanistic steps, nucleophile or
partner class, fluorine-loss behavior, and explicit failure or incompatibility
signals when present. Do not infer transferability to any other reaction. Use
empty transfer fields or UNKNOWN when absent. No more than 12 evidence items.
""".strip()


def client() -> ChatCompletionsStructuredClient:
    return ChatCompletionsStructuredClient(
        "https://cs.jaspervault.pro/v1",
        lambda: read_keychain_secret("reaction-principle-jaspervault", os.environ["USER"]),
        read_timeout_seconds=1200,
        max_retries=3,
    )


def process(row: dict[str, object], pdf_root: Path, output_root: Path) -> dict[str, object]:
    candidate_id = str(row["candidate_id"])
    pdf = pdf_root / f"{candidate_id}.pdf"
    paper_dir = output_root / candidate_id
    validated = paper_dir / "validated.json"
    if validated.is_file():
        return {"candidate_id": candidate_id, "status": "cached", "tier": row["primary_tier"]}
    pages = extract_pages(pdf)
    source = SourceRecord(
        source_path=f"supplement_pdf/{candidate_id}.pdf",
        tier=str(row["primary_tier"]),
        byte_size=pdf.stat().st_size,
        sha256=hashlib.sha256(pdf.read_bytes()).hexdigest(),
        page_count=len(pages),
        parser_version="pypdf-page-v1",
    )
    schema = json.loads(Path("config/extraction_schema.json").read_text(encoding="utf-8"))
    chunks = build_page_chunks(pages, 60000)
    chunk = chunks[0]
    extraction_input = build_extraction_input(source, chunk, PROMPT, seed_context=None)
    result = client().create_structured("gpt-5.6-sol", extraction_input, schema, "paper_evidence_extraction")
    grounded, changes = ground_extraction(result.parsed_output, build_source_spans(chunk.pages), source)
    validation = validate_extraction(grounded, list(chunk.pages), source, schema)
    payload = {
        "cache_key": hashlib.sha256(extraction_input.encode("utf-8")).hexdigest(),
        "api": {"response_id": result.response_id, "returned_model": result.returned_model, "transport": result.transport, "usage": result.usage.__dict__},
        "extraction": grounded,
        "validation": validation.model_dump(mode="json"),
        "grounding": {"changes": changes, "chunk_count": len(chunks)},
        "source_row": row,
    }
    _atomic_json(paper_dir / ("validated.json" if validation.is_valid else "validation_failed.json"), payload)
    return {"candidate_id": candidate_id, "status": "validated" if validation.is_valid else "validation_failed", "page_count": len(pages), "evidence_count": len(grounded.get("evidence_items", [])), "tier": row["primary_tier"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, default=Path("runs/tier_supplement_v1/fulltext_upgrade_queue.json"))
    parser.add_argument("--downloads", type=Path, default=Path("runs/tier_supplement_v1/fulltext"))
    parser.add_argument("--output", type=Path, default=Path("runs/tier_supplement_v1/extractions"))
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    manifest = json.loads((args.downloads / "download_manifest.json").read_text(encoding="utf-8"))
    downloaded = {row["candidate_id"] for row in manifest["records"] if row["status"] == "downloaded"}
    queue = [row for row in json.loads(args.queue.read_text(encoding="utf-8"))["queue"] if row["candidate_id"] in downloaded]
    results: list[dict[str, object]] = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(process, row, args.downloads, args.output) for row in queue]
        for index, future in enumerate(as_completed(futures), start=1):
            try:
                result = future.result()
            except Exception as exc:
                result = {"candidate_id": "unknown", "status": "failed", "error": type(exc).__name__}
            results.append(result)
            print(f"completed {index}/{len(futures)} {result.get('candidate_id')} {result.get('status')}", flush=True)
    results.sort(key=lambda row: str(row.get("candidate_id")))
    _atomic_json(args.output / "manifest.json", {"count": len(results), "validated": sum(row.get("status") == "validated" for row in results), "results": results, "answer_isolation": {"known_outcome_terms_provided": False, "transferability_in_prompt": False}})


if __name__ == "__main__":
    main()

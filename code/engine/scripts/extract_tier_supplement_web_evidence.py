"""Extract locator-grounded evidence from confirmed public web full text."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from pipeline.api_client import ChatCompletionsStructuredClient, read_keychain_secret
from pipeline.evidence_registry import _atomic_json


MAX_PROMPT_CHARACTERS = 90000
GENERIC_EVIDENCE_TERMS = (
    "mechanis", "intermediate", "transition state", "activation", "elimination",
    "oxidative addition", "reductive elimination", "carbon-fluorine", "c-f", "defluorin",
    "nucleoph", "electroph", "catal", "ligand", "base", "solvent", "temperature",
    "yield", "selectiv", "scope", "failed", "failure", "no reaction", "trace",
    "decompos", "inhibit", "poison", "oxid", "competition", "side reaction",
)


class RawWebEvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(min_length=1)
    claim: str = Field(min_length=1)
    source_span_ids: list[str] = Field(min_length=1)
    transferable_step: str
    conditions: list[str]
    failure_boundaries: list[str]
    evidence_strength: Literal["direct", "indirect", "hypothesis", "unknown"]
    attribution: Literal["author_observation", "author_hypothesis", "source_metadata"]


class RawWebExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paper_summary: str
    reaction_class: str
    electrophile_class: str
    partner_class: str
    activation_mode: str
    catalyst_role: str
    evidence_items: list[RawWebEvidenceItem] = Field(max_length=12)
    uncertainties: list[str]
    contradictions: list[str]


def _space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _bounded_sentences(text: str, maximum: int = 800) -> list[str]:
    sentences = [
        part.strip()
        for part in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9(αβγ])", _space(text))
        if part.strip()
    ]
    bounded: list[str] = []
    for sentence in sentences:
        remaining = sentence
        while len(remaining) > maximum:
            boundary = remaining.rfind(" ", 0, maximum + 1)
            if boundary < 1:
                boundary = maximum
            bounded.append(remaining[:boundary])
            remaining = remaining[boundary:].lstrip()
        if remaining:
            bounded.append(remaining)
    return bounded


def build_web_spans(parsed: dict[str, Any]) -> list[dict[str, str]]:
    spans: list[dict[str, str]] = []
    for paragraph in parsed.get("paragraphs", []):
        locator = str(paragraph.get("locator", "unknown paragraph"))
        section = str(paragraph.get("section", "untitled"))
        for sentence_index, text in enumerate(_bounded_sentences(str(paragraph.get("text", ""))), start=1):
            spans.append({
                "span_id": f"W{len(spans) + 1:05d}",
                "locator": f"{locator}; sentence:s{sentence_index:03d}",
                "section": section,
                "text": text,
            })
    return spans


def select_evidence_spans(spans: list[dict[str, str]], maximum: int = MAX_PROMPT_CHARACTERS) -> list[dict[str, str]]:
    def rendered_length(row: dict[str, str]) -> int:
        return len(row["span_id"]) + len(row["locator"]) + len(row["text"]) + 10

    if sum(rendered_length(row) for row in spans) <= maximum:
        return spans
    selected_indices = set(range(min(30, len(spans))))
    selected_indices.update(range(max(0, len(spans) - 10), len(spans)))
    scored: list[tuple[int, int]] = []
    for index, row in enumerate(spans):
        haystack = (row["section"] + " " + row["text"]).casefold()
        score = sum(1 for term in GENERIC_EVIDENCE_TERMS if term in haystack)
        scored.append((score, index))
    for score, index in sorted(scored, key=lambda item: (-item[0], item[1])):
        if score == 0:
            break
        selected_indices.update({candidate for candidate in (index - 1, index, index + 1) if 0 <= candidate < len(spans)})
    selected: list[dict[str, str]] = []
    used = 0
    for index in sorted(selected_indices):
        row = spans[index]
        size = rendered_length(row)
        if used + size > maximum:
            continue
        selected.append(row)
        used += size
    return selected


def build_extraction_prompt(record: dict[str, Any], spans: list[dict[str, str]]) -> str:
    source = "\n".join(
        f"[[{row['span_id']} | {row['locator']}]] {row['text']}" for row in spans
    )
    return f"""
This is a blinded literature-evidence extraction for a reusable reaction-principle workflow.
Use only the supplied full-text spans. Do not use outside knowledge, project outcomes,
named target substrates, or expected answers. Do not infer transferability to the seed
reaction; record only a mechanistic or operational step that the cited paper itself supports.
Unknown information must remain unknown. Distinguish observations from author hypotheses.

For every evidence item, cite one or more supplied span IDs. Do not write quotations: the
program will materialize exact source text from those IDs. Capture reported reaction class,
electrophile and partner classes, activation mode, catalyst role, conditions, explicit failed
scope, decomposition, inhibition, competing paths, and other incompatibility boundaries.
No more than 12 evidence items. A transferable_step is a source-supported operation such as
bond activation, elimination, trapping, catalyst turnover, or condition control; it is not a
claim that the step transfers to another reaction.

Candidate ID: {record.get('candidate_id')}
DOI: {record.get('doi') or 'UNKNOWN'}
Title: {record.get('title') or 'UNKNOWN'}
Tier: {record.get('tier')}

FULL-TEXT SPANS:
{source}
""".strip()


def ground_web_extraction(
    raw: dict[str, Any], spans: list[dict[str, str]], *, candidate_id: str,
    doi: str | None, title: str, tier: str, source_url: str,
) -> dict[str, Any]:
    by_id = {row["span_id"]: row for row in spans}
    grounded = dict(raw)
    grounded.update({
        "candidate_id": candidate_id, "doi": doi, "title": title, "tier": tier,
        "source_url": source_url, "evidence_level": "web_full_text_grounded_validated",
    })
    evidence_items: list[dict[str, Any]] = []
    for item in raw.get("evidence_items", []):
        source_ids: list[str] = []
        for source_id in item.get("source_span_ids", []):
            normalized_id = source_id
            match = re.fullmatch(r"W(\d+)", str(source_id))
            if source_id not in by_id and match:
                candidate = f"W{int(match.group(1)):05d}"
                if candidate in by_id:
                    normalized_id = candidate
            source_ids.append(normalized_id)
        unknown = [source_id for source_id in source_ids if source_id not in by_id]
        if unknown:
            raise ValueError(f"unknown source span IDs: {unknown}")
        selected = [by_id[source_id] for source_id in source_ids]
        evidence_items.append({
            **item,
            "source_span_ids": source_ids,
            "quotation": "\n".join(row["text"] for row in selected),
            "locators": [row["locator"] for row in selected],
            "section_context": "; ".join(dict.fromkeys(row["section"] for row in selected)),
        })
    grounded["evidence_items"] = evidence_items
    return grounded


def client() -> ChatCompletionsStructuredClient:
    return ChatCompletionsStructuredClient(
        "https://cs.jaspervault.pro/v1",
        lambda: read_keychain_secret("reaction-principle-jaspervault", os.environ["USER"]),
        read_timeout_seconds=1200,
        max_retries=3,
    )


def process(record: dict[str, Any], web_root: Path, output_root: Path, api: Any) -> dict[str, Any]:
    candidate_id = str(record["candidate_id"])
    paper_root = output_root / candidate_id
    validated_path = paper_root / "validated.json"
    if validated_path.is_file():
        cached = json.loads(validated_path.read_text(encoding="utf-8"))
        return {"candidate_id": candidate_id, "tier": record["tier"], "status": "cached", "evidence_count": len(cached["extraction"].get("evidence_items", []))}
    structured = json.loads((web_root / "structured" / f"{candidate_id}.json").read_text(encoding="utf-8"))
    all_spans = build_web_spans(structured)
    selected_spans = select_evidence_spans(all_spans)
    prompt = build_extraction_prompt(record, selected_spans)
    schema = RawWebExtraction.model_json_schema()
    try:
        response = api.create_structured("gpt-5.6-sol", prompt, schema, "web_literature_evidence")
        parsed = RawWebExtraction.model_validate(response.parsed_output).model_dump(mode="json")
        source_url = str(record["selected_source"]["final_url"])
        grounded = ground_web_extraction(
            parsed, selected_spans, candidate_id=candidate_id, doi=record.get("doi"),
            title=str(record.get("title") or "UNKNOWN"), tier=str(record["tier"]),
            source_url=source_url,
        )
        payload = {
            "extraction": grounded,
            "source": record["selected_source"],
            "snapshot_sha256": record["selected_source"]["sha256"],
            "retrieval_classification": record["classification"],
            "span_counts": {"full_text": len(all_spans), "supplied_to_model": len(selected_spans)},
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "api": {"response_id": response.response_id, "returned_model": response.returned_model, "transport": response.transport, "usage": response.usage.__dict__},
            "validation": {"is_valid": True, "grounding": "all quotations materialized from selected source spans"},
        }
        _atomic_json(validated_path, payload)
        return {"candidate_id": candidate_id, "tier": record["tier"], "status": "validated", "evidence_count": len(grounded["evidence_items"])}
    except Exception as exc:
        failure = {"candidate_id": candidate_id, "tier": record["tier"], "status": "failed", "error_type": type(exc).__name__, "safe_error": str(exc)[:500]}
        _atomic_json(paper_root / "failure.json", failure)
        return failure


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--web-root", type=Path, default=Path("runs/tier_supplement_v1/web_research"))
    parser.add_argument("--output", type=Path, default=Path("runs/tier_supplement_v1/web_extractions"))
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    records = [
        row for row in json.loads((args.web_root / "fulltext_access_manifest.json").read_text(encoding="utf-8"))["records"]
        if row["classification"] == "full_text"
    ]
    if args.limit is not None:
        records = records[:args.limit]
    api = client()
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(process, row, args.web_root, args.output, api) for row in records]
        for index, future in enumerate(as_completed(futures), start=1):
            result = future.result()
            results.append(result)
            print(f"extracted {index}/{len(futures)} {result['candidate_id']} {result['status']}", flush=True)
    results.sort(key=lambda row: row["candidate_id"])
    manifest = {
        "record_count": len(results),
        "status_counts": dict(sorted(Counter(row["status"] for row in results).items())),
        "validated_or_cached": sum(row["status"] in {"validated", "cached"} for row in results),
        "evidence_item_count": sum(row.get("evidence_count", 0) for row in results),
        "answer_isolation": {"known_outcome_terms_provided": False, "expected_answers_provided": False},
        "results": results,
    }
    _atomic_json(args.output / "manifest.json", manifest)
    print(json.dumps({key: manifest[key] for key in ("record_count", "status_counts", "validated_or_cached", "evidence_item_count")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

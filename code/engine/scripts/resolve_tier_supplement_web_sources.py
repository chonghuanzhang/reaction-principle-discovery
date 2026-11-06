"""Resolve legal web full-text locations for unsummarized supplement records."""

from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from pipeline.evidence_registry import _atomic_json


FORMAT_RANK = {"xml": 0, "pdf": 1, "html": 2, "repository": 3, "landing": 4}


def deduplicate_sources(sources: list[dict[str, object]]) -> list[dict[str, object]]:
    by_url: dict[str, dict[str, object]] = {}
    for source in sources:
        url = source.get("url")
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            continue
        current = by_url.get(url)
        if current is None or FORMAT_RANK.get(str(source.get("format")), 9) < FORMAT_RANK.get(str(current.get("format")), 9):
            by_url[url] = source
    return sorted(by_url.values(), key=lambda row: (FORMAT_RANK.get(str(row.get("format")), 9), str(row["url"])))


def get_json(url: str) -> dict[str, object]:
    request = urllib.request.Request(url, headers={"User-Agent": "reaction-principle-web-fulltext/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        value = json.load(response)
    return value if isinstance(value, dict) else {}


def openalex_sources(openalex_id: str) -> list[dict[str, object]]:
    short = openalex_id.rsplit("/", 1)[-1]
    url = f"https://api.openalex.org/works/{short}?select=id,doi,title,locations,best_oa_location,open_access"
    payload = get_json(url)
    sources: list[dict[str, object]] = []
    for location in payload.get("locations", []):
        if not isinstance(location, dict):
            continue
        source = location.get("source") if isinstance(location.get("source"), dict) else {}
        for key, fmt in (("pdf_url", "pdf"), ("landing_page_url", "repository" if source.get("type") == "repository" else "landing")):
            if location.get(key):
                sources.append({"provider": "openalex", "url": location[key], "format": fmt, "is_oa": location.get("is_oa"), "version": location.get("version"), "source_name": source.get("display_name")})
    return sources


def europe_pmc_sources(doi: str) -> list[dict[str, object]]:
    query = urllib.parse.quote(f"DOI:{doi}")
    payload = get_json(f"https://www.ebi.ac.uk/europepmc/webservices/rest/search?query={query}&format=json")
    results = payload.get("resultList", {}).get("result", []) if isinstance(payload.get("resultList"), dict) else []
    sources: list[dict[str, object]] = []
    for result in results:
        if not isinstance(result, dict):
            continue
        result_doi = str(result.get("doi") or "").casefold().strip()
        if result_doi != doi.casefold().strip():
            continue
        pmcid = result.get("pmcid")
        if pmcid:
            sources.append({"provider": "europe_pmc", "url": f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML", "format": "xml", "pmcid": pmcid})
            sources.append({"provider": "europe_pmc", "url": f"https://europepmc.org/articles/{pmcid}", "format": "html", "pmcid": pmcid})
    return sources


def crossref_sources(doi: str) -> list[dict[str, object]]:
    payload = get_json("https://api.crossref.org/works/" + urllib.parse.quote(doi, safe=""))
    message = payload.get("message") if isinstance(payload.get("message"), dict) else {}
    sources: list[dict[str, object]] = []
    for link in message.get("link", []):
        if not isinstance(link, dict) or not link.get("URL"):
            continue
        content_type = str(link.get("content-type", ""))
        fmt = "pdf" if "pdf" in content_type else "xml" if "xml" in content_type else "html"
        sources.append({"provider": "crossref", "url": link["URL"], "format": fmt, "content_type": content_type, "intended_application": link.get("intended-application")})
    resource = message.get("resource") if isinstance(message.get("resource"), dict) else {}
    primary = resource.get("primary") if isinstance(resource.get("primary"), dict) else {}
    if primary.get("URL"):
        sources.append({"provider": "crossref", "url": primary["URL"], "format": "landing"})
    sources.append({"provider": "doi", "url": "https://doi.org/" + doi, "format": "landing"})
    return sources


def resolve(candidate: dict[str, object]) -> dict[str, object]:
    sources: list[dict[str, object]] = []
    errors: list[dict[str, str]] = []
    try:
        sources.extend(openalex_sources(str(candidate["openalex_id"])))
    except Exception as exc:
        errors.append({"provider": "openalex", "error": type(exc).__name__})
    doi = candidate.get("doi")
    if isinstance(doi, str) and doi:
        for provider, function in (("europe_pmc", europe_pmc_sources), ("crossref", crossref_sources)):
            try:
                sources.extend(function(doi))
            except Exception as exc:
                errors.append({"provider": provider, "error": type(exc).__name__})
    return {
        "candidate_id": candidate["candidate_id"], "doi": doi,
        "title": candidate.get("title"), "tier": candidate["abstract_screening"]["primary_tier"],
        "openalex_id": candidate.get("openalex_id"), "sources": deduplicate_sources(sources), "errors": errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("runs/tier_supplement_v1"))
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    all_records = json.loads((args.root / "abstract_screening_records.json").read_text(encoding="utf-8"))["records"]
    summarized = {row["candidate_id"] for row in json.loads((args.root / "supplement_evidence_registry.json").read_text(encoding="utf-8"))["records"]}
    pending = [row for row in all_records if row["abstract_screening"]["decision"] == "include" and row["candidate_id"] not in summarized]
    _atomic_json(args.root / "web_research" / "pending_records.json", {"count": len(pending), "records": pending})
    results: list[dict[str, object]] = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(resolve, row) for row in pending]
        for index, future in enumerate(as_completed(futures), start=1):
            result = future.result()
            results.append(result)
            _atomic_json(args.root / "web_research" / "resolution" / f"{result['candidate_id']}.json", result)
            if index % 25 == 0 or index == len(futures):
                print(f"resolved {index}/{len(futures)}", flush=True)
    results.sort(key=lambda row: str(row["candidate_id"]))
    manifest = {
        "pending_count": len(pending), "resolved_count": len(results),
        "tier_counts": dict(sorted(Counter(row["tier"] for row in results).items())),
        "records_with_sources": sum(bool(row["sources"]) for row in results),
        "source_count": sum(len(row["sources"]) for row in results),
        "provider_counts": dict(sorted(Counter(source["provider"] for row in results for source in row["sources"]).items())),
        "format_counts": dict(sorted(Counter(source["format"] for row in results for source in row["sources"]).items())),
        "records": results,
    }
    _atomic_json(args.root / "web_research" / "source_resolution_manifest.json", manifest)
    print(json.dumps({key: manifest[key] for key in ("pending_count", "records_with_sources", "source_count", "provider_counts", "format_counts")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

"""Fetch and classify legal public full text for unresolved Tier supplements."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from pipeline.evidence_registry import _atomic_json


USER_AGENT = "reaction-principle-fulltext-audit/1.0 (academic evidence retrieval)"
PAYWALL_MARKERS = (
    "purchase access", "buy article", "subscribe to read", "subscription required",
    "sign in through your institution", "institutional access", "rent this article",
)
ABSTRACT_MARKERS = ("abstract", "summary")
FULL_TEXT_MINIMUM_CHARACTERS = 2000


def _space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold()


def _element_text(element: ET.Element) -> str:
    return _space(" ".join(element.itertext()))


def _xml_paragraphs(root: ET.Element) -> tuple[list[dict[str, str]], str]:
    body = next((node for node in root.iter() if _local_name(node.tag) == "body"), None)
    if body is None:
        return [], ""
    paragraphs: list[dict[str, str]] = []
    section_counter = 0
    paragraph_counter = 0
    for section in body.iter():
        if _local_name(section.tag) != "sec":
            continue
        section_counter += 1
        section_id = section.attrib.get("id") or f"s{section_counter}"
        title_node = next(
            (child for child in section if _local_name(child.tag) == "title"), None
        )
        section_title = _element_text(title_node) if title_node is not None else "untitled"
        nested_sections = {
            id(node) for node in section.iter() if node is not section and _local_name(node.tag) == "sec"
        }
        for paragraph in section.iter():
            if _local_name(paragraph.tag) != "p":
                continue
            if any(id(ancestor) in nested_sections for ancestor in []):
                continue
            text = _element_text(paragraph)
            if not text:
                continue
            paragraph_counter += 1
            paragraph_id = paragraph.attrib.get("id") or f"p{paragraph_counter}"
            paragraphs.append({
                "locator": f"section:{section_id}:{section_title}; paragraph:{paragraph_id}",
                "section": section_title,
                "text": text,
            })
    if not paragraphs:
        for paragraph in body.iter():
            if _local_name(paragraph.tag) != "p":
                continue
            text = _element_text(paragraph)
            if text:
                paragraph_counter += 1
                paragraph_id = paragraph.attrib.get("id") or f"p{paragraph_counter}"
                paragraphs.append({
                    "locator": f"section:body:untitled; paragraph:{paragraph_id}",
                    "section": "untitled",
                    "text": text,
                })
    return paragraphs, _space(" ".join(row["text"] for row in paragraphs))


def _xml_abstract(root: ET.Element) -> str:
    abstracts = [
        _element_text(node) for node in root.iter() if _local_name(node.tag) == "abstract"
    ]
    return _space(" ".join(value for value in abstracts if value))


class _ArticleHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, dict[str, str]]] = []
        self.current: list[str] | None = None
        self.current_meta: tuple[bool, str] | None = None
        self.paragraphs: list[dict[str, str]] = []
        self.abstract_parts: list[str] = []
        self.heading = "untitled"
        self._heading_buffer: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key.casefold(): value or "" for key, value in attrs}
        tag = tag.casefold()
        self.stack.append((tag, attr))
        if tag in {"h1", "h2", "h3", "h4"}:
            self._heading_buffer = []
        if tag == "p":
            in_article = any(
                parent in {"article", "main"}
                or any(marker in values.get("class", "").casefold() for marker in ("article-body", "fulltext", "full-text", "bodymatter"))
                for parent, values in self.stack
            )
            in_abstract = any(
                any(marker in (values.get("class", "") + " " + values.get("id", "")).casefold() for marker in ABSTRACT_MARKERS)
                for _, values in self.stack
            )
            self.current = []
            self.current_meta = (in_article and not in_abstract, "abstract" if in_abstract else "")

    def handle_data(self, data: str) -> None:
        if self.current is not None:
            self.current.append(data)
        if self._heading_buffer is not None:
            self._heading_buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag == "p" and self.current is not None and self.current_meta is not None:
            text = _space(" ".join(self.current))
            if text:
                is_body, kind = self.current_meta
                if is_body:
                    index = len(self.paragraphs) + 1
                    self.paragraphs.append({
                        "locator": f"section:html:{self.heading}; paragraph:p{index}",
                        "section": self.heading,
                        "text": text,
                    })
                elif kind == "abstract":
                    self.abstract_parts.append(text)
            self.current = None
            self.current_meta = None
        if tag in {"h1", "h2", "h3", "h4"} and self._heading_buffer is not None:
            value = _space(" ".join(self._heading_buffer))
            if value:
                self.heading = value
            self._heading_buffer = None
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break


def _parse_pdf(content: bytes) -> dict[str, Any]:
    paragraphs: list[dict[str, str]] = []
    try:
        reader = PdfReader(io.BytesIO(content))
        for page_number, page in enumerate(reader.pages, start=1):
            text = _space(page.extract_text() or "")
            if text:
                paragraphs.append({
                    "locator": f"PDF page {page_number}",
                    "section": f"page {page_number}",
                    "text": text,
                })
    except Exception:
        return {"format": "pdf", "paragraphs": [], "body_text": "", "body_character_count": 0, "abstract_text": ""}
    body = _space(" ".join(row["text"] for row in paragraphs))
    return {"format": "pdf", "paragraphs": paragraphs, "body_text": body, "body_character_count": len(body), "abstract_text": ""}


def parse_structured_document(content: bytes, content_type: str, url: str) -> dict[str, Any]:
    """Return traceable body paragraphs without promoting abstract metadata."""

    lowered_type = content_type.casefold()
    if content.startswith(b"%PDF") or "pdf" in lowered_type:
        return _parse_pdf(content)
    text = content.decode("utf-8", "replace")
    if "xml" in lowered_type or url.casefold().endswith(".xml") or text.lstrip().startswith("<?xml"):
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            return {"format": "xml", "paragraphs": [], "body_text": "", "body_character_count": 0, "abstract_text": ""}
        paragraphs, body = _xml_paragraphs(root)
        return {"format": "xml", "paragraphs": paragraphs, "body_text": body, "body_character_count": len(body), "abstract_text": _xml_abstract(root)}
    parser = _ArticleHTMLParser()
    try:
        parser.feed(text)
    except Exception:
        pass
    body = _space(" ".join(row["text"] for row in parser.paragraphs))
    return {
        "format": "html", "paragraphs": parser.paragraphs, "body_text": body,
        "body_character_count": len(body), "abstract_text": _space(" ".join(parser.abstract_parts)),
    }


def classify_document(
    status: int, headers: dict[str, str], content: bytes, parsed: dict[str, Any]
) -> str:
    """Classify access separately from relevance; only substantial article bodies pass."""

    del headers
    visible = content[:250000].decode("utf-8", "replace").casefold()
    if any(marker in visible for marker in PAYWALL_MARKERS):
        return "paywall"
    if status in {401, 402}:
        return "paywall"
    if status == 403:
        return "access_failed"
    if status >= 400:
        return "access_failed"
    if int(parsed.get("body_character_count", 0)) >= FULL_TEXT_MINIMUM_CHARACTERS and len(parsed.get("paragraphs", [])) >= 1:
        return "full_text"
    if len(str(parsed.get("abstract_text", ""))) >= 200:
        return "abstract_only"
    return "invalid_content"


def _source_rank(source: dict[str, Any]) -> tuple[int, str]:
    provider = str(source.get("provider", ""))
    fmt = str(source.get("format", ""))
    url = str(source.get("url", ""))
    version = str(source.get("version", ""))
    if provider == "europe_pmc" and fmt == "xml":
        rank = 0
    elif fmt == "pdf" and version in {"acceptedVersion", "submittedVersion"}:
        rank = 1
    elif fmt == "pdf":
        rank = 2
    elif provider == "europe_pmc" and fmt == "html":
        rank = 3
    elif fmt == "html":
        rank = 4
    elif fmt == "repository":
        rank = 5
    else:
        rank = 9
    return rank, url


def rank_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(sources, key=_source_rank)


def _fetch(url: str, timeout: int) -> tuple[int, dict[str, str], bytes, str]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/xml,text/html,application/pdf;q=0.9,*/*;q=0.1"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content = response.read(60_000_001)
            if len(content) > 60_000_000:
                raise ValueError("response_too_large")
            return response.status, {key.casefold(): value for key, value in response.headers.items()}, content, response.geturl()
    except urllib.error.HTTPError as exc:
        content = exc.read(500000)
        return exc.code, {key.casefold(): value for key, value in exc.headers.items()}, content, exc.geturl()


def _snapshot_suffix(parsed: dict[str, Any]) -> str:
    return {"pdf": ".pdf", "xml": ".xml", "html": ".html"}.get(str(parsed.get("format")), ".bin")


def fetch_record(record: dict[str, Any], output_root: Path, timeout: int) -> dict[str, Any]:
    candidate_id = str(record["candidate_id"])
    result_path = output_root / "classification" / f"{candidate_id}.json"
    if result_path.is_file():
        return json.loads(result_path.read_text(encoding="utf-8"))
    attempts: list[dict[str, Any]] = []
    selected: dict[str, Any] | None = None
    for source in rank_sources(record.get("sources", [])):
        url = str(source.get("url", ""))
        if not url.startswith(("http://", "https://")):
            continue
        try:
            status, headers, content, final_url = _fetch(url, timeout)
            content_type = headers.get("content-type", "").split(";", 1)[0]
            parsed = parse_structured_document(content, content_type, final_url)
            classification = classify_document(status, headers, content, parsed)
            attempt = {
                "url": url, "final_url": final_url, "provider": source.get("provider"),
                "source_format": source.get("format"), "http_status": status,
                "content_type": content_type, "classification": classification,
                "body_character_count": parsed.get("body_character_count", 0),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
            attempts.append(attempt)
            if classification == "full_text":
                snapshot_path = output_root / "snapshots" / f"{candidate_id}{_snapshot_suffix(parsed)}"
                snapshot_path.parent.mkdir(parents=True, exist_ok=True)
                snapshot_path.write_bytes(content)
                structured_path = output_root / "structured" / f"{candidate_id}.json"
                _atomic_json(structured_path, parsed)
                selected = {**attempt, "snapshot_path": str(snapshot_path), "structured_path": str(structured_path)}
                break
        except Exception as exc:
            attempts.append({
                "url": url, "provider": source.get("provider"), "source_format": source.get("format"),
                "classification": "access_failed", "reason": type(exc).__name__,
            })
    if selected is not None:
        final_classification = "full_text"
        reason = "substantial structured article body retrieved"
    else:
        statuses = [str(row.get("classification")) for row in attempts]
        for possible in ("abstract_only", "paywall", "access_failed", "invalid_content"):
            if possible in statuses:
                final_classification = possible
                break
        else:
            final_classification = "access_failed"
        reason = {
            "abstract_only": "only abstract-level content was retrievable",
            "paywall": "full text requires subscription or purchase",
            "access_failed": "all candidate locations failed or denied automated access",
            "invalid_content": "retrieved pages did not contain a substantial article body",
        }[final_classification]
    result = {
        "candidate_id": candidate_id, "doi": record.get("doi"), "title": record.get("title"),
        "tier": record.get("tier"), "classification": final_classification, "reason": reason,
        "selected_source": selected, "attempted_urls": attempts,
    }
    _atomic_json(result_path, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("runs/tier_supplement_v1/web_research/source_resolution_manifest.json"))
    parser.add_argument("--output", type=Path, default=Path("runs/tier_supplement_v1/web_research"))
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--timeout", type=int, default=90)
    args = parser.parse_args()
    records = json.loads(args.input.read_text(encoding="utf-8"))["records"]
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(fetch_record, row, args.output, args.timeout) for row in records]
        for index, future in enumerate(as_completed(futures), start=1):
            result = future.result()
            results.append(result)
            if index % 10 == 0 or index == len(futures):
                counts = Counter(row["classification"] for row in results)
                print(f"classified {index}/{len(futures)} {dict(counts)}", flush=True)
    results.sort(key=lambda row: row["candidate_id"])
    manifest = {
        "record_count": len(results),
        "classification_counts": dict(sorted(Counter(row["classification"] for row in results).items())),
        "tier_full_text_counts": dict(sorted(Counter(row["tier"] for row in results if row["classification"] == "full_text").items())),
        "records": results,
    }
    _atomic_json(args.output / "fulltext_access_manifest.json", manifest)
    print(json.dumps({key: manifest[key] for key in ("record_count", "classification_counts", "tier_full_text_counts")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

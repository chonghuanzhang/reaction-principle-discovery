"""Download available supplement PDFs with resumable, auditable status."""

from __future__ import annotations

import argparse
import json
import re
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from pipeline.evidence_registry import _atomic_json


def safe_name(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", value)[:140]


def download(row: dict[str, object], destination: Path) -> dict[str, object]:
    candidate_id = str(row.get("candidate_id"))
    url = row.get("pdf_url") or row.get("landing_url")
    result = {"candidate_id": candidate_id, "doi": row.get("doi"), "url": url}
    if not isinstance(url, str) or not url:
        result.update({"status": "unresolved", "reason": "no URL"})
        return result
    path = destination / f"{safe_name(candidate_id)}.pdf"
    if path.is_file() and path.stat().st_size > 1000:
        result.update({"status": "downloaded", "path": str(path), "bytes": path.stat().st_size})
        return result
    request = urllib.request.Request(url, headers={"User-Agent": "reaction-principle-tier-supplement/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            content = response.read()
        if not content.startswith(b"%PDF"):
            result.update({"status": "unresolved", "reason": "response is not PDF"})
            return result
        path.write_bytes(content)
        result.update({"status": "downloaded", "path": str(path), "bytes": len(content)})
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        result.update({"status": "unresolved", "reason": type(exc).__name__})
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("runs/tier_supplement_v1/fulltext_upgrade_queue.json"))
    parser.add_argument("--output", type=Path, default=Path("runs/tier_supplement_v1/fulltext"))
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    queue = json.loads(args.input.read_text(encoding="utf-8"))["queue"]
    args.output.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(download, row, args.output) for row in queue]
        for index, future in enumerate(as_completed(futures), start=1):
            row = future.result()
            rows.append(row)
            if index % 20 == 0 or index == len(futures):
                print(f"completed {index}/{len(futures)}", flush=True)
    rows.sort(key=lambda row: str(row["candidate_id"]))
    _atomic_json(args.output / "download_manifest.json", {
        "queue_source": str(args.input), "count": len(rows),
        "downloaded": sum(row["status"] == "downloaded" for row in rows),
        "unresolved": sum(row["status"] == "unresolved" for row in rows),
        "records": rows,
    })


if __name__ == "__main__":
    main()

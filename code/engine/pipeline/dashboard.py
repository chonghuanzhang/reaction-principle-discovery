"""Local, read-only dashboard for full-corpus execution status."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


DASHBOARD_HTML = Path(__file__).resolve().parent.parent / "dashboard" / "index.html"


def _read_json(path: Path, default: object) -> object:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _public_v3_artifact(namespace: Path, record: object) -> dict[str, object]:
    if not isinstance(record, dict) or record.get("status") != "complete":
        return {}
    raw_path = record.get("artifact")
    if not isinstance(raw_path, str):
        return {}
    path = Path(raw_path)
    if not path.is_absolute():
        path = namespace / path
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(namespace.resolve())
    except (OSError, ValueError):
        return {}
    lowered = resolved.name.casefold()
    if "sealed" in lowered or "registry" in lowered:
        return {}
    value = _read_json(resolved, {})
    return value if isinstance(value, dict) else {}


def _v3_status(output_root: Path) -> dict[str, object]:
    namespace = output_root / "derived" / "principles_v3"
    manifest = _read_json(namespace / "manifest.json", {})
    if not isinstance(manifest, dict):
        manifest = {}
    phases = manifest.get("phases", {})
    if not isinstance(phases, dict):
        phases = {}

    def artifact(phase: str) -> dict[str, object]:
        return _public_v3_artifact(namespace, phases.get(phase))

    validation = artifact("validate")
    reveal = phases.get("reveal")
    return {
        "state": "active" if phases else "absent",
        "v3_brief": artifact("prepare"),
        "leakage": artifact("freeze-1").get("leakage", {}),
        "evidence": artifact("retrieve-seed"),
        "taxonomy": artifact("discover"),
        "saturation": artifact("saturate"),
        "evaluation": artifact("evaluate"),
        "ranking": artifact("evaluate").get("ranking", artifact("evaluate")),
        "freezes": {
            "freeze_1": isinstance(phases.get("freeze-1"), dict)
            and phases["freeze-1"].get("status") == "complete",
            "freeze_2": isinstance(phases.get("freeze-2"), dict)
            and phases["freeze-2"].get("status") == "complete",
            "freeze_3": isinstance(phases.get("freeze-3"), dict)
            and phases["freeze-3"].get("status") == "complete",
        },
        "validation": {
            **validation,
            "revealed": isinstance(reveal, dict)
            and reveal.get("status") == "complete",
        },
    }


def _formal_v3_status(output_root: Path, version: str) -> dict[str, object]:
    namespace = (
        output_root
        / "runs"
        / f"reaction_principle_v{version.replace('.', '_')}"
        / "derived"
        / "principles_v3"
    )
    preregistration = _read_json(namespace / "preregistration.json", {})
    preregistered = isinstance(preregistration, dict) and bool(preregistration)
    round_paths = sorted((namespace / "rounds").glob("round_*.json"))
    rounds = [_read_json(path, {}) for path in round_paths]
    valid_rounds = [row for row in rounds if isinstance(row, dict)]
    attempts = sorted((namespace / "round_attempts").glob("round_*_failure.json"))
    saturation = _read_json(namespace / "saturation.json", {})
    if not isinstance(saturation, dict):
        saturation = {}
    audit = saturation.get("saturation", {})
    if not isinstance(audit, dict):
        audit = {}
    platform_blocked = bool(attempts) and (
        not round_paths
        or attempts[-1].stat().st_mtime > round_paths[-1].stat().st_mtime
    )
    review = _read_json(namespace / "chemical_review.json", {})
    if not isinstance(review, dict):
        review = {}
    capped = version == "3.3" and len(valid_rounds) >= 5 and audit.get("saturated") is not True
    state = (
        "saturated"
        if audit.get("saturated") is True
        else "capped_not_converged"
        if capped
        else "platform_blocked"
        if platform_blocked
        else "running"
        if preregistered
        else "absent"
    )
    return {
        "version": str(preregistration.get("version", version)) if isinstance(preregistration, dict) else version,
        "state": state,
        "preregistered": preregistered,
        "completed_rounds": len(valid_rounds),
        "family_counts": [
            len(row.get("taxonomy", {}).get("families", []))
            for row in valid_rounds
        ],
        "proposal_counts": [
            sum(len(item.get("proposals", [])) for item in row.get("lane_results", []))
            for row in valid_rounds
        ],
        "platform_failure_count": sum(
            len(row.get("platform_failures", [])) for row in valid_rounds
        ),
        "saturation": audit,
        "review": review,
        "freeze_2_allowed": audit.get("saturated") is True and review.get("freeze_2_allowed", True) is True,
    }


def _v3_2_status(output_root: Path) -> dict[str, object]:
    return _formal_v3_status(output_root, "3.2")


def _v3_4_status(output_root: Path) -> dict[str, object]:
    run_root = output_root / "runs"
    status = _read_json(
        run_root
        / "reaction_principle_v3_4_1"
        / "derived"
        / "principles_v3"
        / "status.json",
        None,
    )
    if not isinstance(status, dict):
        status = _read_json(
            run_root
            / "reaction_principle_v3_4"
            / "derived"
            / "principles_v3"
            / "status.json",
            {},
        )
    if not isinstance(status, dict):
        return {}
    return {
        key: status[key]
        for key in (
            "version",
            "source_version",
            "state",
            "proposal_count",
            "consolidated_family_count",
            "unresolved_pair_count",
            "prefix_metrics",
            "consolidation_converged",
            "freeze_2_allowed",
            "freeze_2_blockers",
        )
        if key in status
    }


def _v3_5_status(output_root: Path) -> dict[str, object]:
    status = _read_json(
        output_root
        / "runs"
        / "reaction_principle_v3_5"
        / "derived"
        / "principles_v3"
        / "status.json",
        {},
    )
    if not isinstance(status, dict):
        return {}
    return {
        key: status[key]
        for key in (
            "version",
            "source_version",
            "state",
            "triage_counts",
            "dossier_count",
            "reviewed_in_both_lanes_count",
            "consensus_counts",
            "candidate_family_count",
            "remaining_unresolved_comparison_count",
            "consolidation_converged",
            "freeze_2_allowed",
            "freeze_2_blockers",
        )
        if key in status
    }


def build_status(output_root: Path) -> dict[str, object]:
    """Return a compact snapshot derived only from local artifacts."""

    corpus_root = output_root / "derived" / "full_corpus"
    screening_root = output_root / "derived" / "screening"
    queue = _read_json(corpus_root / "queue.json", {})
    manifest = _read_json(corpus_root / "manifest.json", {})
    screening_summary = _read_json(screening_root / "screening_summary.json", {})
    summary_exists = (corpus_root / "calibration_summary.json").is_file()
    if not isinstance(queue, dict):
        queue = {}
    if not isinstance(manifest, dict):
        manifest = {}
    if not isinstance(screening_summary, dict):
        screening_summary = {}
    items = queue.get("items", []) if isinstance(queue.get("items", []), list) else []
    calibration_items = [item for item in items if item.get("phase") == "calibration"]
    remaining_items = [item for item in items if item.get("phase") == "remaining"]
    statuses = (
        manifest.get("paper_statuses", {})
        if isinstance(manifest.get("paper_statuses", {}), dict)
        else {}
    )
    results = manifest.get("results", []) if isinstance(manifest.get("results", []), list) else []
    completed_paths = {
        item["source_path"] for item in calibration_items if item.get("source_path") in statuses
    }
    calibration_total = len(calibration_items)
    calibration_completed = len(completed_paths)
    percent = (
        round(calibration_completed * 100 / calibration_total, 1)
        if calibration_total
        else 0.0
    )
    active_items = (
        remaining_items if manifest.get("phase") == "remaining" else calibration_items
    )
    active_completed = sum(
        item.get("source_path") in statuses for item in active_items
    )
    active_total = len(active_items)
    active_percent = (
        round(active_completed * 100 / active_total, 1) if active_total else 0.0
    )
    token_totals = {
        "input": sum(int(row.get("input_tokens", 0) or 0) for row in results),
        "output": sum(int(row.get("output_tokens", 0) or 0) for row in results),
        "total": sum(int(row.get("total_tokens", 0) or 0) for row in results),
    }
    next_source = next(
        (
            item.get("source_path")
            for item in active_items
            if item.get("source_path") not in statuses
        ),
        None,
    )
    tier_progress: dict[str, dict[str, int]] = {}
    for tier in ("tier_1", "tier_2", "tier_3", "tier_4"):
        tier_items = [item for item in active_items if item.get("tier") == tier]
        tier_progress[tier] = {
            "completed": sum(item.get("source_path") in statuses for item in tier_items),
            "total": len(tier_items),
        }
    duplicate_count = len(queue.get("duplicate_exclusions", []))
    if manifest.get("phase") == "remaining":
        state = "complete" if active_completed == active_total else "running"
    else:
        state = "complete" if summary_exists else "running" if manifest else "queued" if queue else "not_started"
    from pipeline.principle_workflow import build_principle_status

    principles = build_principle_status(output_root)
    v3_5_status_path = (
        output_root
        / "runs"
        / "reaction_principle_v3_5"
        / "derived"
        / "principles_v3"
        / "status.json"
    )
    v3_5 = _v3_5_status(output_root)
    if v3_5_status_path.is_file() and v3_5.get("freeze_2_allowed") is not True:
        principles = {**principles, "top_candidates": []}

    return {
        "state": state,
        "phase": manifest.get("phase", "calibration" if queue else None),
        "run_id": manifest.get("run_id"),
        "updated_at": manifest.get("updated_at"),
        "calibration": {
            "completed": calibration_completed,
            "total": calibration_total,
            "percent": percent,
        },
        "active_progress": {
            "label": (
                "remaining papers recorded locally"
                if manifest.get("phase") == "remaining"
                else "calibration papers recorded locally"
            ),
            "completed": active_completed,
            "total": active_total,
            "percent": active_percent,
        },
        "corpus": {
            "inventoried": int(
                screening_summary.get(
                    "inventoried_pdf_count", len(items) + duplicate_count
                )
                or len(items) + duplicate_count
            ),
            "unique": len(items),
            "remaining": len(items) - calibration_total,
        },
        "screening": {
            "inventoried": int(screening_summary.get("inventoried_pdf_count", 0) or 0),
            "unique": int(screening_summary.get("unique_pdf_count", 0) or 0),
            "completed": int(screening_summary.get("completed_count", 0) or 0),
            "included": int(screening_summary.get("included_count", 0) or 0),
            "excluded": int(screening_summary.get("excluded_count", 0) or 0),
            "uncertain": int(screening_summary.get("uncertain_count", 0) or 0),
            "tokens": int(screening_summary.get("total_tokens", 0) or 0),
        },
        "status_counts": dict(sorted(Counter(statuses.values()).items())),
        "tokens": token_totals,
        "next_source": next_source,
        "tier_progress": tier_progress,
        "queue_digest": queue.get("queue_digest"),
        "summary_ready": summary_exists,
        "principles": principles,
        "v3": _v3_status(output_root),
        "v3_2": _v3_2_status(output_root),
        "v3_formal": (
            _formal_v3_status(output_root, "3.3")
            if (output_root / "runs/reaction_principle_v3_3/derived/principles_v3/preregistration.json").is_file()
            else _v3_2_status(output_root)
        ),
        "v3_4": _v3_4_status(output_root),
        "v3_5": v3_5,
        "data_source": "Local JSON only; no model or external API call.",
    }


def make_handler(output_root: Path) -> type[BaseHTTPRequestHandler]:
    """Create a loopback HTTP handler bound to one output root."""

    class DashboardHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            path = urlparse(self.path).path
            if path == "/api/status":
                encoded = (
                    json.dumps(build_status(output_root), ensure_ascii=False, sort_keys=True)
                    + "\n"
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)
                return
            if path in {"/", "/index.html"}:
                encoded = DASHBOARD_HTML.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)
                return
            self.send_error(404)

        def log_message(self, format: str, *args: object) -> None:
            del format, args

    return DashboardHandler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=Path.cwd())
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer(
        (args.host, args.port), make_handler(args.output_root.resolve())
    )
    print(f"Dashboard: http://{args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()

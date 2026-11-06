"""Assemble supplement-informed inputs for the existing v3 discovery workflow."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from pipeline.evidence_registry import _atomic_json
from pipeline.principle_models import (
    FrozenReactionPrincipleSet,
    TransferabilityAssessment,
)


NAMESPACE = Path("derived/principles_v3")


def _read_mapping(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object in {path}")
    return value


def _digest(value: object) -> str:
    canonical = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _baseline_transfer_path(root: Path, manifest: dict[str, Any]) -> Path:
    rows = [
        row for row in manifest.get("accepted", [])
        if isinstance(row, dict) and row.get("artifact_type") == "transfer"
    ]
    if len(rows) != 1:
        raise ValueError("expected exactly one accepted baseline transfer artifact")
    return root / str(rows[0]["path"])


def _validated_assessments(path: Path) -> list[TransferabilityAssessment]:
    payload = _read_mapping(path)
    rows = payload.get("assessments")
    if not isinstance(rows, list):
        raise ValueError(f"assessment list is missing from {path}")
    return [TransferabilityAssessment.model_validate(row) for row in rows]


def assemble_discovery_source(
    root: Path,
    supplement_path: Path,
    registry_path: Path,
    frozen_path: Path,
    output_root: Path,
) -> dict[str, Any]:
    root = root.resolve()
    supplement_path = supplement_path.resolve()
    registry_path = registry_path.resolve()
    frozen_path = frozen_path.resolve()
    output_root = output_root.resolve()

    baseline_manifest_path = root / NAMESPACE / "evidence_import_manifest.json"
    baseline_manifest = _read_mapping(baseline_manifest_path)
    baseline_path = _baseline_transfer_path(root, baseline_manifest)
    assessments = [
        *_validated_assessments(baseline_path),
        *_validated_assessments(supplement_path),
    ]
    assessment_ids = [item.assessment_id for item in assessments]
    if len(assessment_ids) != len(set(assessment_ids)):
        raise ValueError("baseline and supplement contain duplicate assessment IDs")

    registry = _read_mapping(registry_path)
    registry_digest = str(registry.get("registry_sha256", ""))
    if len(registry_digest) != 64:
        raise ValueError("supplement registry has no valid registry_sha256")
    frozen = FrozenReactionPrincipleSet.model_validate(_read_mapping(frozen_path))

    input_fingerprint = {
        "baseline_evidence_import_digest": str(baseline_manifest["manifest_digest"]),
        "baseline_transfer_sha256": _sha256(baseline_path),
        "supplement_transfer_sha256": _sha256(supplement_path),
        "supplement_registry_sha256": registry_digest,
        "frozen_principles_sha256": _sha256(frozen_path),
    }
    source_digest = _digest(input_fingerprint)
    relative_transfer = (
        NAMESPACE
        / "clean_inputs"
        / source_digest
        / "derived/principles/transfer_assessments.json"
    )
    combined_path = output_root / relative_transfer
    paper_ids = sorted({
        item.source_paper_id for item in assessments if item.source_paper_id
    })
    combined_payload = {
        "assessment_count": len(assessments),
        "assessments": [item.model_dump(mode="json") for item in assessments],
        "paper_count": len(paper_ids),
        "paper_ids": paper_ids,
        "semantic_transfer_version": "tier-supplement-v2-combined",
        "source_digest": source_digest,
    }
    _atomic_json(combined_path, combined_payload)

    namespace = output_root / NAMESPACE
    _atomic_json(
        namespace / "frozen_principles.json", frozen.model_dump(mode="json")
    )
    accepted = [{
        "artifact_type": "transfer",
        "evidence_digest": _digest(combined_payload["assessments"]),
        "path": str(relative_transfer),
        "schema_version": "pipeline.principle_models.transfer-v1",
        "sha256": _sha256(combined_path),
    }]
    evidence_manifest = {
        "version": "tier-supplement-discovery-source-v1",
        "accepted": accepted,
        "input_fingerprint": input_fingerprint,
        "source_digest": source_digest,
    }
    evidence_manifest["manifest_digest"] = _digest(evidence_manifest)
    _atomic_json(namespace / "evidence_import_manifest.json", evidence_manifest)

    summary = {
        "assessment_count": len(assessments),
        "paper_count": len(paper_ids),
        "principle_count": len(frozen.principles),
        "source_digest": source_digest,
        "evidence_import_manifest_digest": evidence_manifest["manifest_digest"],
        "combined_transfer_path": str(combined_path),
        "answer_isolation": {
            "known_success_families_used": False,
            "sealed_validation_registry_read": False,
        },
    }
    _atomic_json(output_root / "source_summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--supplement",
        type=Path,
        default=Path("runs/tier_supplement_v1/knowledge_transfer/transfer_assessments.json"),
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path("runs/tier_supplement_v1/supplement_evidence_registry_v2.json"),
    )
    parser.add_argument(
        "--frozen",
        type=Path,
        default=Path("runs/tier_supplement_v1/workflow_rerun/frozen_principles.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("runs/tier_supplement_v1/discovery_source"),
    )
    args = parser.parse_args()
    summary = assemble_discovery_source(
        args.root, args.supplement, args.registry, args.frozen, args.output
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

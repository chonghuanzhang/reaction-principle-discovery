from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

import pytest

from pipeline.api_client import ApiClientError
from scripts import run_v3_5_adjudication as adjudication
from scripts.run_v3_5_adjudication import (
    TRANSFER_PATH,
    V35IntegrityError,
    comparison_review_schema,
    consensus,
    prepare,
    review,
    scan_answer_isolation,
    triage,
)


ROOT = Path(__file__).resolve().parents[1]


def test_default_transfer_registry_is_allowlisted_clean_input() -> None:
    manifest = json.loads(
        (ROOT / "derived/principles_v3/evidence_import_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    transfer_path = TRANSFER_PATH.as_posix()
    accepted = {
        row["path"]
        for row in manifest["accepted"]
        if row.get("artifact_type") == "transfer"
    }

    assert transfer_path in accepted
    assert transfer_path not in manifest["rejected_paths"]
    registry = json.loads((ROOT / TRANSFER_PATH).read_text(encoding="utf-8"))
    assert registry["assessment_count"] == len(registry["assessments"]) == 276


def test_allowlisted_transfer_registry_rejects_content_digest_change(
    tmp_path: Path,
) -> None:
    assert hasattr(adjudication, "_validate_allowlisted_transfer_registry")
    repository_root = tmp_path / "repo"
    transfer_path = repository_root / "clean/transfer_assessments.json"
    transfer_path.parent.mkdir(parents=True)
    transfer_path.write_text('{"assessments": []}', encoding="utf-8")
    manifest_path = repository_root / "evidence_import_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "accepted": [
                    {
                        "artifact_type": "transfer",
                        "path": "clean/transfer_assessments.json",
                        "sha256": "0" * 64,
                    }
                ],
                "rejected_paths": [],
                "rejection_reasons": {},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(V35IntegrityError, match="digest does not match"):
        adjudication._validate_allowlisted_transfer_registry(
            transfer_path,
            manifest_path,
            repository_root,
        )


def test_allowlist_rejects_manifest_content_change_before_trusting_path(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repo"
    source_manifest = json.loads(
        (ROOT / adjudication.EVIDENCE_IMPORT_MANIFEST_PATH).read_text(
            encoding="utf-8"
        )
    )
    expected_digest = source_manifest["manifest_digest"]
    transfer_row = next(
        row
        for row in source_manifest["accepted"]
        if row["artifact_type"] == "transfer"
    )
    transfer_path = repository_root / transfer_row["path"]
    transfer_path.parent.mkdir(parents=True)
    shutil.copy2(ROOT / transfer_row["path"], transfer_path)
    source_manifest["accepted"][0]["schema_version"] += "-tampered"
    manifest_path = repository_root / adjudication.EVIDENCE_IMPORT_MANIFEST_PATH
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(source_manifest), encoding="utf-8")

    with pytest.raises(V35IntegrityError, match="content digest changed"):
        adjudication._validate_allowlisted_transfer_registry(
            transfer_path,
            manifest_path,
            repository_root,
            expected_digest,
        )


def test_raw_provenance_manifest_marks_legacy_metadata_unavailable(
    tmp_path: Path,
) -> None:
    assert hasattr(adjudication, "_write_raw_provenance_manifest")
    namespace = tmp_path / "derived/principles_v3"
    raw_path = namespace / "review/raw/REVIEW-V35-A/cache-key.json"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_text(
        json.dumps(
            {
                "cache_key": "cache-key",
                "lane_id": "REVIEW-V35-A",
                "response_id": "response-id",
                "returned_model": "model-id",
                "status": "completed",
                "usage": {},
                "parsed_output": {},
            }
        ),
        encoding="utf-8",
    )

    manifest_path = adjudication._write_raw_provenance_manifest(namespace)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["record_count"] == 1
    assert manifest["legacy_record_count"] == 1
    assert manifest["recorded_provenance_count"] == 0
    assert manifest["legacy_fields_not_reconstructed"] == [
        "created_at",
        "request_digest",
        "client_type",
        "request_endpoint",
    ]
    assert manifest["records"][0]["provenance_status"] == (
        "legacy_metadata_unavailable"
    )
    assert "created_at" not in manifest["records"][0]
    assert "request_endpoint" not in manifest["records"][0]


def _fixture_paths(tmp_path: Path) -> dict[str, Path]:
    v341_root = tmp_path / "v341"
    v33_root = tmp_path / "v33"
    shutil.copytree(
        ROOT / "runs/reaction_principle_v3_4_1/derived/principles_v3",
        v341_root,
    )
    shutil.copytree(
        ROOT / "runs/reaction_principle_v3_3/derived/principles_v3",
        v33_root,
    )
    transfer_path = ROOT / TRANSFER_PATH
    config_path = tmp_path / "config.yaml"
    shutil.copy2(ROOT / "config/comparison_adjudication_v3_5.yaml", config_path)
    prompt_path = tmp_path / "prompt.md"
    shutil.copy2(
        ROOT / "config/prompts/comparison_adjudication_v3_5.md", prompt_path
    )
    return {
        "run_root": tmp_path / "run",
        "v341_root": v341_root,
        "v33_root": v33_root,
        "transfer_path": transfer_path,
        "config_path": config_path,
        "prompt_path": prompt_path,
    }


def test_prepare_records_all_answer_isolated_source_digests(tmp_path: Path) -> None:
    path = prepare(**_fixture_paths(tmp_path))
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["version"] == "3.5"
    assert payload["source_version"] == "3.4.1"
    assert payload["unresolved_pair_count"] == 3082
    assert len(payload["source_digest"]) == 64
    assert len(payload["policy_digest"]) == 64
    assert len(payload["prompt_digest"]) == 64
    assert payload["answer_isolation"] == {
        "sealed_registry_read": False,
        "named_family_targets_used": False,
        "withheld_results_used": False,
    }


def test_prepare_rejects_non_allowlisted_transfer_registry(tmp_path: Path) -> None:
    paths = _fixture_paths(tmp_path)
    paths["transfer_path"] = ROOT / "derived/principles/transfer_assessments.json"

    with pytest.raises(V35IntegrityError, match="explicitly rejected"):
        prepare(**paths)


def test_triage_rejects_changed_v341_source_after_prepare(tmp_path: Path) -> None:
    paths = _fixture_paths(tmp_path)
    prepare(**paths)
    status_path = paths["v341_root"] / "status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    status["state"] = "changed-after-prepare"
    status_path.write_text(json.dumps(status), encoding="utf-8")

    with pytest.raises(V35IntegrityError, match="source digest changed"):
        triage(**paths)


def test_formal_fixture_triage_builds_expected_dossiers(tmp_path: Path) -> None:
    paths = _fixture_paths(tmp_path)
    prepare(**paths)
    triage_path = triage(**paths)
    payload = json.loads(triage_path.read_text(encoding="utf-8"))
    dossiers = json.loads(
        (triage_path.parent / "evidence_dossiers.json").read_text(encoding="utf-8")
    )

    assert payload["counts"] == {
        "shared_external_evidence": 252,
        "text_compatible_evidence_gap": 16,
        "insufficient_linkage": 2814,
    }
    assert len(payload["records"]) == 3082
    assert len(dossiers["dossiers"]) == 252


def test_answer_isolation_scanner_rejects_injected_term(tmp_path: Path) -> None:
    clean = tmp_path / "clean.md"
    dirty = tmp_path / "dirty.md"
    clean.write_text("answer-isolated comparison policy", encoding="utf-8")
    dirty.write_text("contains forbidden-fixture-token", encoding="utf-8")

    assert scan_answer_isolation((clean,), ("forbidden-fixture-token",)) == ()
    assert scan_answer_isolation((dirty,), ("forbidden-fixture-token",)) == (
        dirty,
    )


def test_review_schema_has_gateway_compatible_tuple_items() -> None:
    schema = comparison_review_schema()
    properties = schema["$defs"]["ComparisonReview"]["properties"]
    pair = properties["compared_proposal_ids"]
    fields = properties["field_judgments"]

    assert pair["items"] == {"type": "string"}
    assert pair["minItems"] == pair["maxItems"] == 2
    assert "propertyNames" not in fields
    assert set(fields["properties"]) == {
        "nucleophilic_center",
        "reactive_state",
        "bond_forming_mode",
        "activation_mode",
        "critical_conditions",
        "dominant_failure_modes",
    }
    assert set(fields["required"]) == set(fields["properties"])
    assert fields["additionalProperties"] is False


class _FakeReviewClient:
    def create_structured(self, model, input_text, schema, schema_name):
        del model, schema, schema_name
        dossiers = json.loads(input_text.split("\nDOSSIERS_JSON\n", 1)[1])
        fields = (
            "nucleophilic_center",
            "reactive_state",
            "bond_forming_mode",
            "activation_mode",
            "critical_conditions",
            "dominant_failure_modes",
        )
        comparisons = []
        for dossier in dossiers:
            unknown = {"state": "unknown", "evidence_ids": []}
            comparisons.append(
                {
                    "compared_proposal_ids": dossier["compared_proposal_ids"],
                    "field_judgments": {field: unknown for field in fields},
                    "same_mechanism": unknown,
                    "left_contains_right": unknown,
                    "right_contains_left": unknown,
                    "experimentally_distinguishable": unknown,
                    "uncertainties": ["Evidence does not resolve identity."],
                }
            )
        return type(
            "Result",
            (),
            {
                "parsed_output": {"comparisons": comparisons},
                "response_id": "response-fixture",
                "returned_model": "model-fixture",
                "status": "completed",
                "usage": type(
                    "Usage",
                    (),
                    {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
                )(),
            },
        )()


class _FailingReviewClient:
    def create_structured(self, model, input_text, schema, schema_name):
        del model, input_text, schema, schema_name
        raise ApiClientError(502, "upstream_error", None, "fixture failure")


def _prepared_fixture(tmp_path: Path) -> dict[str, Path]:
    paths = _fixture_paths(tmp_path)
    prepare(**paths)
    triage(**paths)
    return paths


def test_review_preserves_raw_and_validated_lane_batches(tmp_path: Path) -> None:
    paths = _prepared_fixture(tmp_path)

    review(
        **paths,
        client_factory=lambda lane_id: _FakeReviewClient(),
        max_batches=1,
    )

    namespace = paths["run_root"] / "derived/principles_v3/review"
    for lane_id in ("REVIEW-V35-A", "REVIEW-V35-B"):
        raw_paths = tuple((namespace / "raw" / lane_id).glob("*.json"))
        assert raw_paths
        raw = json.loads(raw_paths[0].read_text(encoding="utf-8"))
        assert raw["created_at"]
        assert len(raw["request_digest"]) == 64
        assert raw["client_type"] == "_FakeReviewClient"
        assert tuple((namespace / "validated" / lane_id).glob("*.json"))


def test_review_rejects_rehashed_dossier_changed_after_triage(tmp_path: Path) -> None:
    paths = _prepared_fixture(tmp_path)
    dossier_path = paths["run_root"] / "derived/principles_v3/evidence_dossiers.json"
    payload = json.loads(dossier_path.read_text(encoding="utf-8"))
    dossier = payload["dossiers"][0]
    dossier["caution"] = "tampered but self-consistent"
    digest_payload = {key: value for key, value in dossier.items() if key != "dossier_digest"}
    dossier["dossier_digest"] = hashlib.sha256(
        json.dumps(
            digest_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    dossier_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(V35IntegrityError, match="offline artifacts differ"):
        review(**paths, client_factory=lambda lane_id: _FakeReviewClient())


def test_review_records_platform_failure_without_imputing_decision(
    tmp_path: Path,
) -> None:
    paths = _prepared_fixture(tmp_path)

    review(
        **paths,
        client_factory=lambda lane_id: _FailingReviewClient(),
        max_batches=1,
    )

    namespace = paths["run_root"] / "derived/principles_v3"
    failures = json.loads(
        (namespace / "review_failures.json").read_text(encoding="utf-8")
    )
    assert failures["failure_count"] == 2
    assert not tuple((namespace / "review/validated").glob("*/*.json"))


def test_consensus_preserves_unknown_reviews_without_merging(tmp_path: Path) -> None:
    paths = _prepared_fixture(tmp_path)
    review(**paths, client_factory=lambda lane_id: _FakeReviewClient())

    status_path = consensus(**paths)
    status = json.loads(status_path.read_text(encoding="utf-8"))
    candidate = json.loads(
        (status_path.parent / "candidate_consolidation.json").read_text(
            encoding="utf-8"
        )
    )

    assert status["consensus_counts"]["unresolved"] == 252
    assert status["remaining_unresolved_comparison_count"] == 3082
    assert status["candidate_family_count"] == 205
    assert status["freeze_2_allowed"] is False
    assert candidate["candidate_family_count"] == 205


def test_consensus_rejects_validated_cache_with_unexpected_key(tmp_path: Path) -> None:
    paths = _prepared_fixture(tmp_path)
    review(
        **paths,
        client_factory=lambda lane_id: _FakeReviewClient(),
        max_batches=1,
    )
    validated_root = (
        paths["run_root"]
        / "derived/principles_v3/review/validated/REVIEW-V35-A"
    )
    original = next(validated_root.glob("*.json"))
    payload = json.loads(original.read_text(encoding="utf-8"))
    stale_key = "f" * 64
    payload["cache_key"] = stale_key
    original.unlink()
    (validated_root / f"{stale_key}.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )

    with pytest.raises(V35IntegrityError, match="unexpected validated review cache"):
        consensus(**paths)

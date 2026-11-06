from types import SimpleNamespace

import pytest
import yaml

from scripts import run_v3_2_discovery as runner


def _row(identity, status, paper, score):
    return SimpleNamespace(assessment_id=identity, transfer_status=status,
                           source_paper_id=paper, score_components={"total": score})


def test_selection_is_order_independent_and_preserves_four_strata():
    rows = [_row("a", "transferable", "p1", 3),
            _row("b", "conditional", "p2", 2),
            _row("c", "non_transferable", "p3", -1),
            _row("d", "unknown", "p4", 0),
            _row("e", "conditional", "p2", 99)]
    selected = runner.select_stratified_assessments(rows, limit=4)
    assert {item.transfer_status for item in selected} == {
        "transferable", "conditional", "non_transferable", "unknown"}
    assert [item.assessment_id for item in selected] == [
        item.assessment_id for item in runner.select_stratified_assessments(rows[::-1], limit=4)]


def test_selection_rejects_duplicate_evidence_ids_and_invalid_limit():
    row = _row("a", "conditional", "p", 1)
    with pytest.raises(ValueError):
        runner.select_stratified_assessments([row, row], limit=2)
    with pytest.raises(ValueError):
        runner.select_stratified_assessments([row], limit=0)


def test_v33_contract_requires_all_35_assignments():
    from pathlib import Path
    config = yaml.safe_load(Path("config/mechanism_coordinates_v3_3.yaml").read_text())
    contract = runner.coordinate_preregistration(config, version="3.3")
    assert contract["allowed_coordinate_assignment_count"] == 35
    config["coordinate_cell_templates"].pop()
    with pytest.raises(ValueError, match="35"):
        runner.coordinate_preregistration(config, version="3.3")


def test_saturation_still_requires_two_completed_rounds(tmp_path):
    from pathlib import Path
    with pytest.raises(ValueError, match="at least two"):
        runner.saturation(tmp_path, Path("config/mechanism_coordinates_v3_3.yaml"))


def test_prepare_binds_actual_source_bytes_and_preserves_coordinate_contract(tmp_path):
    import json
    from pathlib import Path
    from pipeline.principle_models import FrozenReactionPrincipleSet
    from tests.test_taxonomy_discovery import _principle
    namespace = tmp_path / "source" / "derived/principles_v3"
    relative = "derived/principles_v3/clean_inputs/test/derived/principles/transfer_assessments.json"
    transfer = tmp_path / "source" / relative
    transfer.parent.mkdir(parents=True)
    transfer.write_text(json.dumps({"assessments": []}))
    (namespace / "evidence_import_manifest.json").write_text(json.dumps({
        "manifest_digest": "a" * 64,
        "accepted": [{"artifact_type": "transfer", "path": relative,
                      "sha256": runner.previous._sha256(transfer)}]}))
    frozen = FrozenReactionPrincipleSet(
        freeze_version="test", created_at="2026-09-06T00:00:00Z",
        source_digest="b" * 64, scoring_digest="c" * 64,
        principles=(_principle(),))
    (namespace / "frozen_principles.json").write_text(frozen.model_dump_json())
    args = (tmp_path / "source", tmp_path / "run",
            Path("config/principle_workflow_v3_3.yaml"),
            Path("config/mechanism_coordinates_v3_3.yaml"))
    first = runner.prepare(*args)
    assert first["inputs"]["allowed_coordinate_assignment_count"] == 35
    assert runner.prepare(*args) == first
    transfer.write_text(json.dumps({"assessments": [], "changed": True}))
    with pytest.raises(ValueError, match="changed"):
        runner.prepare(*args)


def test_transfer_resolution_uses_typed_manifest_entry_not_first_path(tmp_path):
    import hashlib
    import json
    path = tmp_path / "derived/principles/transfer_assessments.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"assessments": []}))
    manifest = {"accepted": [
        {"artifact_type": "seed", "path": "derived/principles/seed_mechanism.json"},
        {"artifact_type": "transfer", "path": "derived/principles/transfer_assessments.json",
         "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}]}
    assert runner._transfer_path(tmp_path, manifest) == path
    path.write_text("changed")
    with pytest.raises(ValueError, match="SHA"):
        runner._transfer_path(tmp_path, manifest)


def test_transfer_resolution_rejects_ambiguous_or_outside_manifest_entry(tmp_path):
    row = {"artifact_type": "transfer", "path": "../outside.json", "sha256": "a" * 64}
    with pytest.raises(ValueError, match="exactly one"):
        runner._transfer_path(tmp_path, {"accepted": [row, row]})
    with pytest.raises(ValueError, match="canonical"):
        runner._transfer_path(tmp_path, {"accepted": [row]})

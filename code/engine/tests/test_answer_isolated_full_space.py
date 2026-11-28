from pathlib import Path

import pytest

from pipeline.answer_isolated_full_space import (
    AnswerIsolationError,
    AnswerIsolationManifest,
    DevelopmentUseMetadata,
    FullSpacePhaseState,
    validate_model_visible_paths,
)


def _manifest(tmp_path: Path) -> AnswerIsolationManifest:
    return AnswerIsolationManifest(
        hidden_registry_commitment="a" * 64,
        hidden_record_count=1,
        excluded_paths=(str(tmp_path / "config"),),
        model_visible_input_digests={"seed_stage": "b" * 64},
        metadata=DevelopmentUseMetadata(
            development_use="answer_isolated_retrieval",
            prospective_metric_eligible=False,
            validation_type="blinded_reanalysis",
            target_results_supplied_to_model=False,
        ),
    )


def test_v36_metadata_cannot_claim_prospective_eligibility():
    with pytest.raises(ValueError):
        DevelopmentUseMetadata(
            development_use="answer_isolated_retrieval",
            prospective_metric_eligible=True,
            validation_type="blinded_reanalysis",
            target_results_supplied_to_model=False,
        )


def test_model_visible_paths_reject_hidden_paths(tmp_path: Path):
    manifest = _manifest(tmp_path)

    with pytest.raises(AnswerIsolationError, match="excluded"):
        validate_model_visible_paths(
            manifest, [tmp_path / "config/sealed_validation_registry.yaml"]
        )


def test_full_space_phase_state_records_a_completion_without_hidden_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    manifest = _manifest(tmp_path)
    hidden_registry = tmp_path / "config/sealed_validation_registry.yaml"
    hidden_registry.parent.mkdir(parents=True, exist_ok=True)
    hidden_registry.write_text("sealed", encoding="utf-8")

    original_read_bytes = Path.read_bytes

    def guarded_read_bytes(self: Path) -> bytes:
        if self.resolve() == hidden_registry.resolve():
            raise AssertionError("hidden registry was read")
        return original_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", guarded_read_bytes)

    visible_registry = tmp_path / "visible_registry.yaml"
    resolved = validate_model_visible_paths(manifest, [visible_registry])
    state = FullSpacePhaseState(
        phase="prepare",
        predecessor_digest=None,
        input_digest="c" * 64,
        output_digest="d" * 64,
        completed_at="2026-08-28T00:00:00Z",
    )

    assert resolved == (visible_registry.resolve(),)
    assert state.phase == "prepare"

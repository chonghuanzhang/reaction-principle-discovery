from pathlib import Path

import pytest
import yaml

from pipeline.sealed_registry import (
    RevealAuthorization,
    RevealGateError,
    build_public_commitment,
    create_registry_commitment,
    load_public_commitment,
    reveal_registry,
)


def _fixture_registry(tmp_path: Path) -> Path:
    registry = tmp_path / "private-registry.yaml"
    registry.write_text(
        yaml.safe_dump(
            {
                "version": "1.0",
                "records": [
                    {
                        "record_id": "synthetic-001",
                        "terms": ["SEALED_TERM_A", "SEALED_TERM_B"],
                        "structure_hashes": ["a" * 64],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return registry


def test_public_commitment_contains_no_plaintext_answers(tmp_path):
    commitment = create_registry_commitment(b"sealed fixture payload", b"fixed-test-salt")

    dumped = commitment.model_dump_json()

    assert "sealed fixture payload" not in dumped
    assert commitment.record_count == 1


def test_load_public_commitment_reads_only_public_fields(tmp_path):
    path = tmp_path / "public.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "version": "1.0",
                "record_count": 1,
                "commitment": "a" * 64,
                "registry_locator": "../private/registry.yaml",
                "created_at": "2026-08-13T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    commitment = load_public_commitment(path)

    assert commitment.commitment == "a" * 64
    assert commitment.registry_locator == "../private/registry.yaml"


def test_load_public_commitment_rejects_uninitialized_placeholder(tmp_path):
    path = tmp_path / "public.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "version": "1.0",
                "record_count": 1,
                "commitment": "0" * 64,
                "registry_locator": "config/seed_sources.yaml#hidden_answer",
                "created_at": "2026-08-14T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RevealGateError, match="uninitialized"):
        load_public_commitment(path)


def test_local_builder_writes_a_public_commitment_without_registry_plaintext(tmp_path):
    registry = _fixture_registry(tmp_path)
    destination = tmp_path / "public.yaml"

    built = build_public_commitment(
        registry,
        destination,
        salt=b"fixed-test-salt",
        registry_locator="config/seed_sources.yaml#hidden_answer",
        created_at="2026-08-13T00:00:00Z",
    )

    public_text = destination.read_text(encoding="utf-8")
    assert load_public_commitment(destination) == built
    assert "SEALED_TERM_A" not in public_text


def test_reveal_remains_unavailable_without_trusted_freeze_chain_verifier(tmp_path):
    with pytest.raises(
        RevealGateError, match="trusted Freeze 3 chain verification unavailable"
    ):
        reveal_registry(_fixture_registry(tmp_path), RevealAuthorization())

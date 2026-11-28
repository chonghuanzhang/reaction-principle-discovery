from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pipeline.inventory import inventory_sources, write_inventory
from pipeline.models import SourceRecord


def fixture_source_record() -> SourceRecord:
    return SourceRecord(
        source_path="Tier1/paper.pdf",
        tier="tier_1",
        byte_size=16,
        sha256=hashlib.sha256(b"immutable source").hexdigest(),
        page_count=None,
        parser_version="pypdf-test",
    )


def test_inventory_hashes_without_modifying_source(tmp_path: Path) -> None:
    source = tmp_path / "Tier1" / "paper.pdf"
    source.parent.mkdir()
    source.write_bytes(b"immutable source")
    before = source.stat()

    records = inventory_sources(tmp_path, {"tier_1": Path("Tier1")})

    after = source.stat()
    assert records[0].sha256 == hashlib.sha256(b"immutable source").hexdigest()
    assert (before.st_size, before.st_mtime_ns) == (
        after.st_size,
        after.st_mtime_ns,
    )


def test_write_inventory_is_stable_and_atomic(tmp_path: Path) -> None:
    output = tmp_path / "derived" / "inventory" / "sources.json"

    write_inventory([fixture_source_record()], output)
    first = output.read_bytes()
    write_inventory([fixture_source_record()], output)

    assert output.read_bytes() == first
    assert not output.with_suffix(".json.tmp").exists()
    assert json.loads(first)[0]["source_path"] == "Tier1/paper.pdf"


def test_inventory_rejects_symlink_that_escapes_root(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-paper.pdf"
    outside.write_bytes(b"outside")
    tier = tmp_path / "Tier1"
    tier.mkdir()
    (tier / "escape.pdf").symlink_to(outside)

    try:
        try:
            inventory_sources(tmp_path, {"tier_1": Path("Tier1")})
        except ValueError as exc:
            assert "escapes project root" in str(exc)
        else:
            raise AssertionError("escaping symlink was accepted")
    finally:
        outside.unlink()

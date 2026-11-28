"""Seed input inventory with fail-closed hidden-answer isolation."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, computed_field

from pipeline.inventory import sha256_file


class SeedInputError(RuntimeError):
    """Raised when seed inputs cannot be isolated safely."""


class SeedInputFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    role: str
    access_class: Literal["principle_building", "hidden_answer"]
    sha256: str
    byte_size: int


class SeedInputInventory(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_root: str
    files: tuple[SeedInputFile, ...]
    principle_building_digest: str
    hidden_answer_digest: str
    hidden_answers_revealed: Literal[False] = False

    @computed_field
    @property
    def principle_building_files(self) -> tuple[SeedInputFile, ...]:
        return tuple(item for item in self.files if item.access_class == "principle_building")

    @computed_field
    @property
    def hidden_answer_files(self) -> tuple[SeedInputFile, ...]:
        return tuple(item for item in self.files if item.access_class == "hidden_answer")


def _digest_files(files: list[SeedInputFile]) -> str:
    rows = [
        {"path": item.path, "role": item.role, "sha256": item.sha256}
        for item in sorted(files, key=lambda value: (value.path, value.role))
    ]
    encoded = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def inventory_seed_inputs(
    source_root: Path, config: Mapping[str, object]
) -> SeedInputInventory:
    """Inventory configured seed inputs without reading their scientific content."""

    source_root = source_root.resolve()
    sources = config.get("sources")
    if not isinstance(sources, list):
        raise SeedInputError("seed source config requires a sources list")

    seen_access: dict[str, str] = {}
    entries: list[SeedInputFile] = []
    for source in sources:
        if not isinstance(source, dict):
            raise SeedInputError("every seed source must be a mapping")
        relative = source.get("path")
        role = source.get("role")
        access = source.get("access_class")
        if not isinstance(relative, str) or not isinstance(role, str):
            raise SeedInputError("every seed source requires path and role")
        if access not in {"principle_building", "hidden_answer"}:
            raise SeedInputError(f"invalid seed access class for {relative}")
        resolved = (source_root / relative).resolve()
        try:
            resolved.relative_to(source_root)
        except ValueError as exc:
            raise SeedInputError(f"seed input escapes source root: {relative}") from exc
        if not resolved.is_file():
            raise SeedInputError(f"missing configured seed input: {relative}")
        prior_access = seen_access.get(relative)
        if prior_access is not None and prior_access != access:
            raise SeedInputError(f"seed input assigned to multiple access classes: {relative}")
        seen_access[relative] = str(access)
        entries.append(
            SeedInputFile(
                path=relative,
                role=role,
                access_class=access,
                sha256=sha256_file(resolved),
                byte_size=resolved.stat().st_size,
            )
        )

    build_hashes = {item.sha256 for item in entries if item.access_class == "principle_building"}
    hidden_hashes = {item.sha256 for item in entries if item.access_class == "hidden_answer"}
    if build_hashes & hidden_hashes:
        raise SeedInputError("same file content appears in principle-building and hidden-answer inputs")

    ordered = sorted(entries, key=lambda item: (item.access_class, item.path, item.role))
    build_entries = [item for item in ordered if item.access_class == "principle_building"]
    hidden_entries = [item for item in ordered if item.access_class == "hidden_answer"]
    return SeedInputInventory(
        source_root=str(source_root),
        files=tuple(ordered),
        principle_building_digest=_digest_files(build_entries),
        hidden_answer_digest=_digest_files(hidden_entries),
    )


def assert_principle_building_safe(inventory: SeedInputInventory) -> None:
    """Reject an inventory that reveals or aliases hidden answer content."""

    if inventory.hidden_answers_revealed:
        raise SeedInputError("hidden answers were revealed before freeze")
    build_hashes = {item.sha256 for item in inventory.principle_building_files}
    hidden_hashes = {item.sha256 for item in inventory.hidden_answer_files}
    if build_hashes & hidden_hashes:
        raise SeedInputError("same file content appears in both access classes")


def _atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def write_seed_input_inventory(
    source_root: Path, output_root: Path, config: Mapping[str, object]
) -> Path:
    inventory = inventory_seed_inputs(source_root, config)
    assert_principle_building_safe(inventory)
    destination = output_root.resolve() / "derived" / "principles" / "seed_input_inventory.json"
    _atomic_json(destination, inventory.model_dump(mode="json"))
    return destination

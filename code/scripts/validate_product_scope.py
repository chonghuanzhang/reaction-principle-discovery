#!/usr/bin/env python3
"""Check Table 1 source assets, displayed counts and curated pair links."""

from __future__ import annotations

import hashlib
import json
import re
import struct
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCOPE = ROOT / "experiments/product_scope"


def emf_texts(path: Path) -> list[str]:
    """Read Unicode text from the deposited EMF's EMR_EXTTEXTOUTW records."""
    data = path.read_bytes()
    texts = []
    position = 0
    while position < len(data):
        kind, size = struct.unpack_from("<II", data, position)
        assert size >= 8 and position + size <= len(data), "Invalid EMF record"
        if kind == 84:
            count, offset = struct.unpack_from("<II", data, position + 44)
            assert offset + count * 2 <= size, "Truncated EMF text"
            start = position + offset
            texts.append(data[start : start + count * 2].decode("utf-16-le"))
        position += size
    return texts


def main() -> None:
    manifest = json.loads((SCOPE / "source_manifest.json").read_text())
    for asset in manifest["assets"]:
        data = (ROOT / asset["path"]).read_bytes()
        assert len(data) == asset["bytes"], asset["path"]
        assert hashlib.sha256(data).hexdigest() == asset["sha256"], asset["path"]

    preview = manifest["preview"]
    data = (ROOT / preview["path"]).read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "Invalid preview PNG"
    assert len(data) == preview["bytes"], preview["path"]
    assert hashlib.sha256(data).hexdigest() == preview["sha256"], preview["path"]
    dimensions = struct.unpack_from(">II", data, 16)
    assert dimensions == (preview["width_pixels"], preview["height_pixels"])
    crop = preview["derivation"]["crop_pixels"]
    assert dimensions == (crop[2] - crop[0], crop[3] - crop[1])
    source_emf = ROOT / preview["derivation"]["source_emf_path"]
    assert hashlib.sha256(source_emf.read_bytes()).hexdigest() == preview["derivation"]["source_emf_sha256"]

    texts = emf_texts(SCOPE / "table1.emf")
    displayed = {}
    for index, value in enumerate(texts):
        if re.fullmatch(r"3[a-z]{1,2}", value):
            assert value not in displayed, f"Duplicate product label: {value}"
            assert texts[index + 1] == ", ", value
            yield_text = texts[index + 2]
            assert re.fullmatch(r"\d+%", yield_text), value
            displayed[value] = int(yield_text[:-1])

    expected_ids = [f"3{chr(n)}" for n in range(ord("a"), ord("z") + 1)]
    expected_ids += [f"3a{chr(n)}" for n in range(ord("a"), ord("r") + 1)]
    assert set(displayed) == set(expected_ids), "Table 1 product range differs"
    summary = manifest["table_summary"]
    assert len(displayed) == summary["displayed_product_assignment_count"] == 44
    assert summary["product_id_range"] == [expected_ids[0], expected_ids[-1]]
    assert summary["N_functionalized_count"] == len(expected_ids[:11]) == 11
    assert summary["S_functionalized_count"] == len(expected_ids[11:24]) == 13
    assert summary["O_functionalized_count"] == len(expected_ids[24:]) == 20

    pairs = {
        row["actual_pair_id"]: row
        for row in json.loads((ROOT / "code/data/structures/actual_pairs.json").read_text())
    }
    assessments = {
        row["actual_pair_id"]: row
        for row in json.loads(
            (ROOT / "code/data/novelty/reviewed/novelty_actual_pairs_112.json").read_text()
        )
    }
    package = json.loads((ROOT / manifest["curated_record_file"]).read_text())
    records = package["records"]
    assert package["source_id"] == manifest["source_id"]
    assert {row["product_id"] for row in records} == set(manifest["curated_record_scope"])
    assert len(records) == len(manifest["curated_record_scope"])
    for row in records:
        product_id = row["product_id"]
        pair = pairs[row["actual_pair_id"]]
        assert row["yield_percent"] == displayed[product_id], product_id
        assert row["electrophile_smiles"] == pair["electrophile_smiles"], product_id
        assert row["donor_smiles"] == pair["actual_donor_smiles"], product_id
        options = assessments[row["actual_pair_id"]]["options"]
        option = next(x for x in options if x["option_id"] == row["existing_assessed_option_id"])
        assert row["product_connectivity_smiles"] == option["product_smiles"], product_id
        assert row["source_id"] == manifest["source_id"], product_id
        assert (ROOT / row["source_manifest"]).is_file(), product_id

    print(json.dumps({
        "status": "passed",
        "displayed_products": len(displayed),
        "curated_product_yields": {row["product_id"]: row["yield_percent"] for row in records},
        "linked_existing_pairs": [row["actual_pair_id"] for row in records],
        "source_assets_verified": len(manifest["assets"]),
        "preview_verified": preview["path"],
    }, indent=2))


if __name__ == "__main__":
    main()

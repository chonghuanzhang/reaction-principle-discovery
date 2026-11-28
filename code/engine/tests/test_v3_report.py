import json
from pathlib import Path

from pipeline.principle_report import build_v3_report, write_v3_report


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def test_report_calls_indices_priorities_not_probabilities(tmp_path: Path) -> None:
    root = tmp_path / "derived/principles_v3"
    ranking = root / "ranking.json"
    _write(
        ranking,
        {
            "families": [
                {
                    "family_id": "F-1",
                    "family_name": "synthetic family",
                    "region": "Priority A",
                    "primary_score": 0.81,
                    "evidence_basis": ["E-1"],
                    "uncertainty": "limited negative evidence",
                }
            ]
        },
    )
    _write(
        root / "manifest.json",
        {
            "version": 3,
            "phases": {
                "evaluate": {
                    "status": "complete",
                    "artifact": str(ranking),
                }
            },
        },
    )

    report = build_v3_report(tmp_path)

    assert "优先级指数" in report["markdown"]
    assert "成功概率" not in report["markdown"]
    assert report["families"][0]["family_id"] == "F-1"


def test_report_groups_every_family_once_and_preserves_unknown(tmp_path: Path) -> None:
    root = tmp_path / "derived/principles_v3"
    artifact = root / "evaluation.json"
    _write(
        artifact,
        {
            "families": [
                {"family_id": "A", "region": "Priority A", "score": 1.0},
                {"family_id": "U", "region": "Unknown", "score": None},
            ]
        },
    )
    _write(
        root / "manifest.json",
        {"version": 3, "phases": {"evaluate": {"status": "complete", "artifact": str(artifact)}}},
    )

    report = build_v3_report(tmp_path)

    assert [row["family_id"] for row in report["families"]] == ["A", "U"]
    assert report["groups"]["Unknown"][0]["family_id"] == "U"
    assert "通用成功" not in report["markdown"]

    json_path, markdown_path = write_v3_report(tmp_path)
    assert json.loads(json_path.read_text(encoding="utf-8"))["families"] == report["families"]
    assert "优先级指数" in markdown_path.read_text(encoding="utf-8")

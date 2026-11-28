"""Run v3.3 discovery with an exact 35-assignment coordinate contract."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import yaml

from pipeline.saturation import expand_coordinate_assignments
if __package__:
    from scripts.run_v3_2_discovery import discover_round, prepare, saturation, status
else:
    from run_v3_2_discovery import discover_round, prepare, saturation, status


RUN_NAMESPACE = Path("runs/reaction_principle_v3_3")
MAX_COMPLETED_ROUNDS = 5


def coordinate_preregistration(config: dict[str, object]) -> dict[str, object]:
    assignments = [
        item.model_dump(mode="json") for item in expand_coordinate_assignments(config)
    ]
    encoded = json.dumps(
        assignments, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return {
        "allowed_coordinate_assignment_count": len(assignments),
        "allowed_coordinate_assignments": assignments,
        "allowed_coordinate_assignment_digest": hashlib.sha256(encoded).hexdigest(),
    }


def _load_yaml(path: Path) -> dict[str, object]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a mapping in {path}")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("prepare", "discover", "saturate", "status"), required=True)
    parser.add_argument("--round", type=int)
    parser.add_argument("--adjudicate", action="store_true")
    parser.add_argument("--source-root", type=Path, default=Path.cwd())
    parser.add_argument("--run-root", type=Path, default=Path.cwd() / RUN_NAMESPACE)
    parser.add_argument("--workflow-config", type=Path, default=Path("config/principle_workflow_v3_3.yaml"))
    parser.add_argument("--coordinate-config", type=Path, default=Path("config/mechanism_coordinates_v3_3.yaml"))
    args = parser.parse_args()
    source_root = args.source_root.resolve()
    run_root = args.run_root.resolve()
    workflow_config = args.workflow_config.resolve()
    coordinate_config = args.coordinate_config.resolve()
    if args.phase == "prepare":
        result = prepare(source_root, run_root, workflow_config, coordinate_config)
    elif args.phase == "discover":
        if args.round is None or not 1 <= args.round <= MAX_COMPLETED_ROUNDS:
            parser.error(f"--round must be from 1 to {MAX_COMPLETED_ROUNDS} for discover")
        result = discover_round(
            source_root, run_root, workflow_config, coordinate_config,
            args.round, adjudicate=args.adjudicate,
        )
    elif args.phase == "saturate":
        result = saturation(run_root, coordinate_config)
    else:
        result = status(run_root)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

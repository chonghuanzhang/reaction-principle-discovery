from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import yaml

from pipeline.api_client import ApiClientError, ApiResult, ApiUsage
from pipeline.sealed_registry import load_public_commitment
from scripts import run_v3_2_discovery


def test_v3_2_client_uses_chat_protocol_for_responses_upstream_failure(monkeypatch) -> None:
    calls: list[str] = []

    class Primary:
        def __init__(self, *args, **kwargs):
            pass

        def create_structured(self, model, input_text, schema, schema_name):
            calls.append("responses")
            raise ApiClientError(400, "upstream_error", None, "upstream failed")

    class Fallback:
        def __init__(self, *args, **kwargs):
            pass

        def create_structured(self, model, input_text, schema, schema_name):
            calls.append("chat_completions")
            return ApiResult(
                response_id="chat-1",
                returned_model=model,
                status="completed",
                parsed_output={"ok": True},
                usage=ApiUsage(1, 1, 2),
                transport="chat_completions",
            )

    monkeypatch.setattr(run_v3_2_discovery, "ResponsesClient", Primary)
    monkeypatch.setattr(run_v3_2_discovery, "ChatCompletionsStructuredClient", Fallback)

    result = run_v3_2_discovery._client().create_structured(
        "gpt-test",
        "input",
        {"type": "object"},
        "probe",
    )

    assert result.transport == "chat_completions"
    assert calls == ["responses", "chat_completions"]


def test_v3_client_can_select_chat_transport_without_calling_responses(monkeypatch) -> None:
    calls: list[str] = []

    class Primary:
        def __init__(self, *args, **kwargs):
            calls.append("responses_constructed")

    class Chat:
        def __init__(self, *args, **kwargs):
            calls.append("chat_constructed")

        def create_structured(self, model, input_text, schema, schema_name):
            return ApiResult(
                response_id="chat-1",
                returned_model=model,
                status="completed",
                parsed_output={"ok": True},
                usage=ApiUsage(1, 1, 2),
                transport="chat_completions",
            )

    monkeypatch.setenv("JASPER_API_TRANSPORT", "chat_completions")
    monkeypatch.setattr(run_v3_2_discovery, "ResponsesClient", Primary)
    monkeypatch.setattr(run_v3_2_discovery, "ChatCompletionsStructuredClient", Chat)

    result = run_v3_2_discovery._client().create_structured(
        "gpt-test", "input", {"type": "object"}, "probe"
    )

    assert result.transport == "chat_completions"
    assert calls == ["chat_constructed"]


def test_production_public_commitment_is_initialized() -> None:
    path = Path("config/sealed_validation_registry.yaml")

    commitment = load_public_commitment(path)

    assert commitment.record_count == 4
    assert commitment.registry_locator
    assert Path(commitment.registry_locator).is_absolute()
    public = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert set(public) == {
        "version",
        "record_count",
        "commitment",
        "registry_locator",
        "created_at",
    }


def test_v3_3_preregisters_exact_coordinate_set_and_round_cap() -> None:
    from scripts import run_v3_3_discovery

    coordinate_config = yaml.safe_load(
        Path("config/mechanism_coordinates_v3_3.yaml").read_text(encoding="utf-8")
    )
    record = run_v3_3_discovery.coordinate_preregistration(coordinate_config)

    assert run_v3_3_discovery.RUN_NAMESPACE == Path("runs/reaction_principle_v3_3")
    assert run_v3_3_discovery.MAX_COMPLETED_ROUNDS == 5
    assert record["allowed_coordinate_assignment_count"] == 35
    assert len(record["allowed_coordinate_assignments"]) == 35
    assert len(record["allowed_coordinate_assignment_digest"]) == 64


def test_v3_3_runner_can_be_executed_as_a_script(tmp_path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run_v3_3_discovery.py",
            "--phase",
            "status",
            "--run-root",
            str(tmp_path),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert '"completed_rounds": []' in completed.stdout

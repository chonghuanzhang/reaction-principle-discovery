from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request

import pytest

import pipeline.api_client as api_client

from pipeline.api_client import (
    ApiClientError,
    ApiResult,
    ApiUsage,
    HttpResponse,
    ResponsesClient,
    UpstreamFallbackStructuredClient,
    classify_retry,
    read_keychain_secret,
)


def test_structured_client_falls_back_only_for_upstream_gateway_failure() -> None:
    calls: list[str] = []

    class Primary:
        def create_structured(self, model, input_text, schema, schema_name):
            calls.append("responses")
            raise ApiClientError(400, "upstream_error", None, "upstream failed")

    class Fallback:
        def create_structured(self, model, input_text, schema, schema_name):
            calls.append("chat_completions")
            return ApiResult(
                response_id="chat-1",
                returned_model=model,
                status="completed",
                parsed_output={"status": "ok"},
                usage=ApiUsage(10, 2, 12),
                transport="chat_completions",
            )

    result = UpstreamFallbackStructuredClient(Primary(), Fallback()).create_structured(
        MODEL, "input", schema(), "paper_evidence"
    )

    assert result.parsed_output == {"status": "ok"}
    assert result.transport == "chat_completions"
    assert calls == ["responses", "chat_completions"]


def test_structured_client_does_not_fall_back_for_authentication_failure() -> None:
    class Primary:
        def create_structured(self, model, input_text, schema, schema_name):
            raise ApiClientError(401, "authentication_error", None, "bad key")

    class Fallback:
        def create_structured(self, model, input_text, schema, schema_name):
            raise AssertionError("authentication failures must not use fallback")

    with pytest.raises(ApiClientError, match="authentication_error"):
        UpstreamFallbackStructuredClient(Primary(), Fallback()).create_structured(
            MODEL, "input", schema(), "paper_evidence"
        )


def test_codex_structured_client_uses_output_schema_and_returns_json(tmp_path):
    from subprocess import CompletedProcess

    from pipeline.api_client import CodexStructuredClient

    calls = []

    def runner(args, **kwargs):
        calls.append((args, kwargs))
        output = Path(args[args.index("--output-last-message") + 1])
        output.write_text('{"ok":true}', encoding="utf-8")
        return CompletedProcess(args, 0, stdout="", stderr="")

    client = CodexStructuredClient(runner=runner, temporary_root=tmp_path)
    result = client.create_structured(
        "gpt-test",
        "Return ok.",
        {
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
            "additionalProperties": False,
        },
        "probe",
    )

    assert result.parsed_output == {"ok": True}
    assert "--output-schema" in calls[0][0]
    assert calls[0][1]["input"] == "Return ok."


def test_chat_completions_client_parses_schema_constrained_message():
    from pipeline.api_client import ChatCompletionsStructuredClient

    seen = []

    def transport(request):
        seen.append(json.loads(request.data))
        return api_client.HttpResponse(
            status=200,
            body={
                "id": "chat-1",
                "model": "gpt-test",
                "choices": [{"message": {"content": '{"ok":true}'}}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
            },
        )

    client = ChatCompletionsStructuredClient(
        "https://example.test/v1", lambda: "secret", transport=transport
    )
    result = client.create_structured(
        "gpt-test",
        "Return ok.",
        {
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
            "additionalProperties": False,
        },
        "probe",
    )

    assert result.parsed_output == {"ok": True}
    assert seen[0]["response_format"]["type"] == "json_schema"


def test_chat_completions_client_retries_transient_gateway_failure():
    from pipeline.api_client import ChatCompletionsStructuredClient

    responses = iter(
        [
            api_client.HttpResponse(502, {"error": {"type": "upstream_error"}}),
            api_client.HttpResponse(
                200,
                {
                    "id": "chat-2",
                    "model": "gpt-test",
                    "choices": [{"message": {"content": '{"ok":true}'}}],
                },
            ),
        ]
    )
    sleeps = []
    client = ChatCompletionsStructuredClient(
        "https://example.test/v1",
        lambda: "secret",
        transport=lambda request: next(responses),
        sleep=sleeps.append,
    )

    result = client.create_structured(
        "gpt-test",
        "Return ok.",
        {"type": "object", "properties": {}, "additionalProperties": False},
        "probe",
    )

    assert result.parsed_output == {"ok": True}
    assert sleeps == [1.0]

BASE = "https://cs.jaspervault.pro/v1"
MODEL = "gpt-5.6-sol"


def schema() -> dict:
    return {
        "type": "object",
        "properties": {"status": {"type": "string", "enum": ["ok"]}},
        "required": ["status"],
        "additionalProperties": False,
    }


def success_response() -> HttpResponse:
    return HttpResponse(
        status=200,
        body={
            "id": "resp_test",
            "model": MODEL,
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": '{"status":"ok"}'}
                    ],
                }
            ],
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        },
    )


@dataclass
class CapturingTransport:
    response: HttpResponse
    calls: int = 0
    authorization: str | None = None
    json_body: dict | None = None

    def __call__(self, request: Request) -> HttpResponse:
        self.calls += 1
        self.authorization = request.get_header("Authorization")
        self.json_body = json.loads(request.data.decode("utf-8"))
        return self.response


def test_secret_is_used_but_never_returned() -> None:
    transport = CapturingTransport(success_response())
    client = ResponsesClient(BASE, lambda: "secret-value", transport)

    result = client.create_structured(MODEL, "input", schema(), "paper_evidence")

    assert result.parsed_output == {"status": "ok"}
    assert transport.authorization == "Bearer secret-value"
    assert "secret-value" not in repr(result)


@pytest.mark.parametrize(
    ("status", "expected"),
    [(408, True), (429, True), (500, True), (401, False), (403, False), (400, False)],
)
def test_retry_classification(status: int, expected: bool) -> None:
    assert classify_retry(status, None) is expected


def test_request_disables_storage_and_uses_strict_schema() -> None:
    transport = CapturingTransport(success_response())
    client = ResponsesClient(BASE, lambda: "secret", transport)

    result = client.create_structured(MODEL, "input", schema(), "paper_evidence")

    assert result.status == "completed"
    assert transport.json_body is not None
    assert transport.json_body["store"] is False
    assert transport.json_body["text"]["format"]["strict"] is True
    assert transport.json_body["text"]["format"]["schema"] == schema()


def test_transient_failure_retries_but_authentication_failure_does_not() -> None:
    responses = [
        HttpResponse(status=429, body={"error": {"type": "rate_limit", "message": "slow"}}),
        success_response(),
    ]

    def transient_transport(request: Request) -> HttpResponse:
        return responses.pop(0)

    client = ResponsesClient(BASE, lambda: "secret", transient_transport, sleep=lambda _: None)
    assert client.create_structured(MODEL, "input", schema(), "paper_evidence").status == "completed"
    assert responses == []

    auth_transport = CapturingTransport(
        HttpResponse(status=401, body={"error": {"type": "authentication_error", "message": "bad key"}})
    )
    with pytest.raises(Exception) as caught:
        ResponsesClient(BASE, lambda: "secret", auth_transport).create_structured(
            MODEL, "input", schema(), "paper_evidence"
        )
    assert auth_transport.calls == 1
    assert "secret" not in str(caught.value)


def test_gateway_upstream_error_retries_even_when_wrapped_as_http_400() -> None:
    responses = [
        HttpResponse(
            status=400,
            body={"error": {"type": "upstream_error", "message": "upstream failed"}},
        ),
        success_response(),
    ]

    def transport(request: Request) -> HttpResponse:
        return responses.pop(0)

    client = ResponsesClient(BASE, lambda: "secret", transport, sleep=lambda _: None)

    assert client.create_structured(MODEL, "input", schema(), "paper_evidence").status == "completed"
    assert responses == []


def test_ambiguous_read_timeout_is_not_retried_for_paid_post() -> None:
    calls = 0

    def timeout_transport(request: Request) -> HttpResponse:
        nonlocal calls
        calls += 1
        raise TimeoutError("read timed out after request submission")

    client = ResponsesClient(BASE, lambda: "secret", timeout_transport, sleep=lambda _: None)

    with pytest.raises(Exception):
        client.create_structured(MODEL, "input", schema(), "paper_evidence")

    assert calls == 1


def test_request_caps_structured_output_tokens() -> None:
    transport = CapturingTransport(success_response())

    ResponsesClient(BASE, lambda: "secret", transport).create_structured(
        MODEL, "input", schema(), "paper_evidence"
    )

    assert transport.json_body is not None
    assert transport.json_body["max_output_tokens"] == 8000


def test_default_transport_uses_configured_read_timeout(monkeypatch) -> None:
    observed: dict[str, int] = {}

    def configured_transport(request: Request, timeout_seconds: int) -> HttpResponse:
        observed["timeout_seconds"] = timeout_seconds
        return success_response()

    monkeypatch.setattr(api_client, "_default_transport", configured_transport)
    client = ResponsesClient(
        BASE,
        lambda: "secret",
        read_timeout_seconds=1200,
    )

    assert client.create_structured(MODEL, "input", schema(), "paper_evidence").status == "completed"
    assert observed == {"timeout_seconds": 1200}


@pytest.mark.skipif(os.environ.get("RUN_LIVE_API_TEST") != "1", reason="opt-in live API test")
def test_live_structured_response() -> None:
    secret_provider = lambda: read_keychain_secret(
        "reaction-principle-jaspervault", os.environ["USER"]
    )
    result = ResponsesClient(BASE, secret_provider).create_structured(
        MODEL,
        "Return the required object with status ok.",
        schema(),
        "live_smoke_test",
    )
    assert result.status == "completed"
    assert result.parsed_output == {"status": "ok"}

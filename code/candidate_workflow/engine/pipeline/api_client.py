"""Secure OpenAI-compatible Responses API client for JasperVault."""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from pathlib import Path

DEFAULT_READ_TIMEOUT_SECONDS = 600

@dataclass(frozen=True)
class HttpResponse:
    """Sanitized transport result."""

    status: int
    body: dict[str, Any]


@dataclass(frozen=True)
class ApiUsage:
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None


@dataclass(frozen=True)
class ApiResult:
    response_id: str
    returned_model: str
    status: str
    parsed_output: dict[str, Any]
    usage: ApiUsage
    transport: str = "unknown"


class ApiClientError(RuntimeError):
    """Credential-free gateway failure safe for logs and reports."""

    def __init__(
        self,
        status: int | None,
        error_type: str | None,
        error_code: str | None,
        message: str,
    ) -> None:
        self.status = status
        self.error_type = error_type
        self.error_code = error_code
        self.safe_message = message[:500]
        super().__init__(
            f"Responses API failure status={status} type={error_type} "
            f"code={error_code}: {self.safe_message}"
        )


def read_keychain_secret(service: str, account: str) -> str:
    """Read a generic password from macOS Keychain without shell expansion."""

    completed = subprocess.run(
        [
            "/usr/bin/security",
            "find-generic-password",
            "-a",
            account,
            "-s",
            service,
            "-w",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    secret = completed.stdout.strip()
    if not secret:
        raise ApiClientError(None, "credential_error", None, "Keychain returned an empty credential.")
    return secret


def classify_retry(status: int | None, error: Exception | None) -> bool:
    """Return whether a failure is transient under the bounded retry policy."""

    if status in {408, 409, 425, 429} or (status is not None and 500 <= status <= 599):
        return True
    del error
    return False


def _default_transport(
    request: urllib.request.Request,
    timeout_seconds: int = DEFAULT_READ_TIMEOUT_SECONDS,
) -> HttpResponse:
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return HttpResponse(
                status=response.status,
                body=json.loads(response.read().decode("utf-8")),
            )
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = {"error": {"type": "http_error", "message": raw[:500]}}
        return HttpResponse(status=exc.code, body=body)


def _output_text(body: dict[str, Any]) -> str:
    direct = body.get("output_text")
    if isinstance(direct, str):
        return direct
    chunks: list[str] = []
    for item in body.get("output", []):
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []):
            if isinstance(content, dict) and isinstance(content.get("text"), str):
                chunks.append(content["text"])
    return "".join(chunks)


class ResponsesClient:
    """Minimal schema-constrained Responses client with dependency injection."""

    def __init__(
        self,
        base_url: str,
        secret_provider: Callable[[], str],
        transport: Callable[[urllib.request.Request], HttpResponse] | None = None,
        *,
        max_retries: int = 2,
        sleep: Callable[[float], None] = time.sleep,
        read_timeout_seconds: int = DEFAULT_READ_TIMEOUT_SECONDS,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._secret_provider = secret_provider
        self._transport = transport or (
            lambda request: _default_transport(request, read_timeout_seconds)
        )
        self._max_retries = max_retries
        self._sleep = sleep

    def create_structured(
        self,
        model: str,
        input_text: str,
        schema: dict[str, Any],
        schema_name: str,
    ) -> ApiResult:
        """Create one strict structured response without server-side storage."""

        secret = self._secret_provider()
        payload = {
            "model": model,
            "input": input_text,
            "store": False,
            "max_output_tokens": 8000,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "strict": True,
                    "schema": schema,
                }
            },
        }
        request = urllib.request.Request(
            f"{self._base_url}/responses",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {secret}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        response: HttpResponse | None = None
        for attempt in range(self._max_retries + 1):
            try:
                response = self._transport(request)
            except Exception as exc:
                if attempt < self._max_retries and classify_retry(None, exc):
                    self._sleep(float(attempt + 1))
                    continue
                message = str(exc).replace(secret, "[REDACTED]")
                raise ApiClientError(None, type(exc).__name__, None, message) from exc
            if response.status == 200:
                break
            response_error = response.body.get("error", {})
            upstream_error = (
                isinstance(response_error, dict)
                and response_error.get("type") == "upstream_error"
            )
            if attempt < self._max_retries and (
                classify_retry(response.status, None) or upstream_error
            ):
                self._sleep(float(attempt + 1))
                continue
            error = response_error
            if not isinstance(error, dict):
                error = {"message": str(error)}
            message = str(error.get("message", "Unknown gateway error")).replace(
                secret, "[REDACTED]"
            )
            raise ApiClientError(
                response.status,
                str(error.get("type")) if error.get("type") is not None else None,
                str(error.get("code")) if error.get("code") is not None else None,
                message,
            )
        if response is None or response.status != 200:
            raise ApiClientError(None, "transport_error", None, "No successful response.")
        try:
            parsed_output = json.loads(_output_text(response.body))
        except json.JSONDecodeError as exc:
            raise ApiClientError(
                response.status,
                "invalid_structured_output",
                None,
                "Response output was not valid JSON.",
            ) from exc
        usage = response.body.get("usage", {})
        if not isinstance(usage, dict):
            usage = {}
        return ApiResult(
            response_id=str(response.body.get("id", "")),
            returned_model=str(response.body.get("model", "")),
            status=str(response.body.get("status", "")),
            parsed_output=parsed_output,
            usage=ApiUsage(
                input_tokens=usage.get("input_tokens"),
                output_tokens=usage.get("output_tokens"),
                total_tokens=usage.get("total_tokens"),
            ),
            transport="responses",
        )


class CodexStructuredClient:
    """Schema-constrained local Codex CLI fallback for gateway outages."""

    def __init__(
        self,
        *,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        temporary_root: Path | None = None,
        working_directory: Path | None = None,
        timeout_seconds: int = DEFAULT_READ_TIMEOUT_SECONDS,
    ) -> None:
        self._runner = runner
        self._temporary_root = temporary_root
        self._working_directory = (working_directory or Path.cwd()).resolve()
        self._timeout_seconds = timeout_seconds

    def create_structured(
        self,
        model: str,
        input_text: str,
        schema: dict[str, Any],
        schema_name: str,
    ) -> ApiResult:
        del schema_name
        with tempfile.TemporaryDirectory(
            dir=self._temporary_root, prefix="codex-structured-"
        ) as directory:
            temporary = Path(directory)
            schema_path = temporary / "schema.json"
            output_path = temporary / "output.json"
            schema_path.write_text(
                json.dumps(schema, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
            args = [
                "codex",
                "exec",
                "--ephemeral",
                "--sandbox",
                "read-only",
                "--skip-git-repo-check",
                "--model",
                model,
                "--cd",
                str(self._working_directory),
                "--output-schema",
                str(schema_path),
                "--output-last-message",
                str(output_path),
                "-",
            ]
            completed = self._runner(
                args,
                input=input_text,
                text=True,
                capture_output=True,
                timeout=self._timeout_seconds,
                check=False,
            )
            if completed.returncode != 0:
                raise ApiClientError(
                    None,
                    "codex_cli_error",
                    str(completed.returncode),
                    (completed.stderr or "Codex CLI structured call failed.")[-500:],
                )
            try:
                raw = output_path.read_text(encoding="utf-8")
                parsed = json.loads(raw)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ApiClientError(
                    None,
                    "invalid_structured_output",
                    None,
                    "Codex CLI output was not valid JSON.",
                ) from exc
            if not isinstance(parsed, dict):
                raise ApiClientError(
                    None,
                    "invalid_structured_output",
                    None,
                    "Codex CLI output must be a JSON object.",
                )
            response_id = hashlib.sha256(raw.encode("utf-8")).hexdigest()
            return ApiResult(
                response_id=f"codex-cli-{response_id[:16]}",
                returned_model=model,
                status="completed",
                parsed_output=parsed,
                usage=ApiUsage(None, None, None),
                transport="codex_cli",
            )


class ChatCompletionsStructuredClient:
    """OpenAI-compatible schema-constrained Chat Completions client."""

    def __init__(
        self,
        base_url: str,
        secret_provider: Callable[[], str],
        transport: Callable[[urllib.request.Request], HttpResponse] | None = None,
        *,
        read_timeout_seconds: int = DEFAULT_READ_TIMEOUT_SECONDS,
        max_retries: int = 2,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._secret_provider = secret_provider
        self._transport = transport or (
            lambda request: _default_transport(request, read_timeout_seconds)
        )
        self._max_retries = max_retries
        self._sleep = sleep

    def create_structured(
        self,
        model: str,
        input_text: str,
        schema: dict[str, Any],
        schema_name: str,
    ) -> ApiResult:
        secret = self._secret_provider()
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": input_text}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": schema,
                },
            },
        }
        request = urllib.request.Request(
            f"{self._base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {secret}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        response: HttpResponse | None = None
        for attempt in range(self._max_retries + 1):
            response = self._transport(request)
            if response.status == 200:
                break
            if attempt < self._max_retries and classify_retry(response.status, None):
                self._sleep(float(attempt + 1))
                continue
            break
        assert response is not None
        if response.status != 200:
            error = response.body.get("error", {})
            if not isinstance(error, dict):
                error = {"message": str(error)}
            raise ApiClientError(
                response.status,
                str(error.get("type")) if error.get("type") is not None else None,
                str(error.get("code")) if error.get("code") is not None else None,
                str(error.get("message", "Unknown gateway error")).replace(
                    secret, "[REDACTED]"
                ),
            )
        try:
            content = response.body["choices"][0]["message"]["content"]
            parsed = json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ApiClientError(
                response.status,
                "invalid_structured_output",
                None,
                "Chat completion output was not valid structured JSON.",
            ) from exc
        usage = response.body.get("usage", {})
        if not isinstance(usage, dict):
            usage = {}
        return ApiResult(
            response_id=str(response.body.get("id", "")),
            returned_model=str(response.body.get("model", model)),
            status="completed",
            parsed_output=parsed,
            usage=ApiUsage(
                input_tokens=usage.get("prompt_tokens"),
                output_tokens=usage.get("completion_tokens"),
                total_tokens=usage.get("total_tokens"),
            ),
            transport="chat_completions",
        )


class UpstreamFallbackStructuredClient:
    """Use a secondary protocol only when the primary gateway route fails upstream."""

    def __init__(self, primary: Any, fallback: Any) -> None:
        self._primary = primary
        self._fallback = fallback

    def create_structured(
        self,
        model: str,
        input_text: str,
        schema: dict[str, Any],
        schema_name: str,
    ) -> ApiResult:
        try:
            return self._primary.create_structured(
                model, input_text, schema, schema_name
            )
        except ApiClientError as exc:
            if exc.error_type != "upstream_error":
                raise
            return self._fallback.create_structured(
                model, input_text, schema, schema_name
            )

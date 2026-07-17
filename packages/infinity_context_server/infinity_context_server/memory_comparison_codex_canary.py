"""Secret-safe Codex subscription-runtime canary for memory comparison LLMs."""

from __future__ import annotations

import argparse
import json
import os
import shlex
from collections.abc import Sequence
from pathlib import Path

from infinity_context_server.memory_comparison_codex_llm import (
    CodexCliAnswerer,
    CodexCommandRunner,
)
from infinity_context_server.memory_comparison_models import RetrievedMemory
from infinity_context_server.public_benchmark_models import PublicBenchmarkCase

SUITE = "infinity-context-memory-comparison-codex-canary"
SCHEMA_VERSION = "memory-comparison-codex-canary.v1"
DEFAULT_MODEL = "gpt-5.5"
DEFAULT_TIMEOUT_SECONDS = 180.0
EXPECTED_TERM = "blue"


def run_codex_answerer_canary(
    *,
    model: str = DEFAULT_MODEL,
    codex_command: str = "codex",
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    command_runner: CodexCommandRunner | None = None,
    cwd: Path | None = None,
) -> dict[str, object]:
    """Invoke the Codex answerer on a tiny synthetic fixture and return safe JSON."""

    answerer = CodexCliAnswerer(
        model=model,
        codex_command=codex_command,
        timeout_seconds=timeout_seconds,
        command_runner=command_runner,
        cwd=cwd,
    )
    try:
        result = answerer.answer(
            _canary_case(),
            _canary_memories(),
            backend_name="sandbox-fixture",
            cutoff=1,
        )
    except Exception as exc:  # noqa: BLE001 - canary reports sanitized blockers.
        return _blocked_report(
            exc,
            model=model,
            codex_command=codex_command,
            timeout_seconds=timeout_seconds,
        )

    answer_contains_expected = EXPECTED_TERM in _normalize(result.answer)
    return {
        "schema_version": SCHEMA_VERSION,
        "suite": SUITE,
        "ok": answer_contains_expected,
        "failure_code": None if answer_contains_expected else "unexpected_answer",
        "failure_reason": (
            None
            if answer_contains_expected
            else "Codex returned an answer that did not contain the expected fixture term."
        ),
        "provider": "codex-cli",
        "provider_kind": "subscription-runtime",
        "model": result.model,
        "codex_command": _command_label(codex_command),
        "sandbox_fixture": "memory-comparison-answerer-blue-marker",
        "answer_contains_expected_term": answer_contains_expected,
        "answer_preview": _safe_answer_preview(result.answer),
        "latency_ms": result.latency_ms,
        "token_usage": {
            "prompt_tokens": result.token_usage.prompt_tokens,
            "completion_tokens": result.token_usage.completion_tokens,
            "total_tokens": result.token_usage.total_tokens,
        },
        "timeout_seconds": timeout_seconds,
    }


def _canary_case() -> PublicBenchmarkCase:
    return PublicBenchmarkCase(
        benchmark="sandbox-canary",
        case_id="subscription-runtime-codex-canary-1",
        question="What color is the sandbox marker?",
        expected_terms=(EXPECTED_TERM,),
    )


def _canary_memories() -> tuple[RetrievedMemory, ...]:
    return (
        RetrievedMemory(
            text="Sandbox fixture evidence: the sandbox marker color is blue.",
            rank=1,
            source_refs=("fixture:1",),
        ),
    )


def _blocked_report(
    exc: Exception,
    *,
    model: str,
    codex_command: str,
    timeout_seconds: float,
) -> dict[str, object]:
    failure_code = _failure_code(exc)
    return {
        "schema_version": SCHEMA_VERSION,
        "suite": SUITE,
        "ok": False,
        "failure_code": failure_code,
        "failure_reason": _failure_reason(failure_code),
        "diagnostics": _failure_diagnostics(failure_code, exc),
        "provider": "codex-cli",
        "provider_kind": "subscription-runtime",
        "model": model,
        "codex_command": _command_label(codex_command),
        "sandbox_fixture": "memory-comparison-answerer-blue-marker",
        "answer_contains_expected_term": False,
        "answer_preview": None,
        "timeout_seconds": timeout_seconds,
    }


def _failure_code(exc: Exception) -> str:
    text = str(exc).casefold()
    if "command not found" in text or "no such file or directory" in text:
        return "codex_command_not_found"
    if "timed out" in text:
        return "codex_cli_timeout"
    if "operation not permitted" in text and (
        "api.openai.com" in text or "responses" in text
    ):
        return "provider_network_blocked"
    if "read-only file system" in text:
        return "codex_runtime_not_writable"
    if "empty output" in text:
        return "codex_cli_empty_output"
    return "codex_cli_failed"


def _failure_reason(failure_code: str) -> str:
    if failure_code == "codex_command_not_found":
        return "Codex CLI was not executable from the configured bridge command."
    if failure_code == "codex_cli_timeout":
        return "Codex CLI did not return before the canary timeout."
    if failure_code == "provider_network_blocked":
        return "Codex CLI reached the provider path, but outbound provider access was blocked."
    if failure_code == "codex_runtime_not_writable":
        return "Codex CLI could not initialize because its runtime filesystem was not writable."
    if failure_code == "codex_cli_empty_output":
        return "Codex CLI completed without a usable answer."
    return "Codex CLI failed before returning a usable answer."


def _failure_diagnostics(failure_code: str, exc: Exception) -> dict[str, object]:
    text = str(exc).casefold()
    if failure_code == "provider_network_blocked":
        transports: list[str] = []
        if "websocket" in text or "wss://api.openai.com" in text:
            transports.append("websocket")
        if "https transport" in text or "https://api.openai.com" in text:
            transports.append("https")
        if not transports:
            transports.append("provider")
        return {
            "blocker_scope": "external_provider_egress",
            "operator_action": "allow_subscription_runtime_provider_egress",
            "provider_endpoint": (
                "api.openai.com" if "api.openai.com" in text else "provider_endpoint_redacted"
            ),
            "provider_transports": transports,
            "os_error": (
                "operation_not_permitted"
                if "operation not permitted" in text
                else "provider_request_failed"
            ),
            "repo_invocation_sandbox": "read-only",
            "repo_invocation_approval_policy": "never",
        }
    if failure_code == "codex_runtime_not_writable":
        return {"blocker_scope": "local_codex_runtime_filesystem"}
    if failure_code == "codex_command_not_found":
        return {"blocker_scope": "local_codex_cli"}
    if failure_code == "codex_cli_timeout":
        return {"blocker_scope": "codex_cli_timeout"}
    return {"blocker_scope": "codex_cli"}


def _command_label(command: str) -> str:
    text = str(command or "").strip()
    if not text:
        return ""
    try:
        parts = shlex.split(text)
    except ValueError:
        parts = text.split()
    executable = parts[0] if parts else text
    return Path(executable).name


def _safe_answer_preview(answer: str) -> str:
    return " ".join(str(answer or "").split())[:160]


def _normalize(text: str) -> str:
    return " ".join(str(text or "").casefold().split())


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        default=os.getenv("MEMORY_COMPARISON_CODEX_MODEL", DEFAULT_MODEL),
        help="Codex model name for the canary.",
    )
    parser.add_argument(
        "--codex-command",
        default=(
            os.getenv("MEMORY_COMPARISON_CODEX_COMMAND")
            or os.getenv("MEMORY_LLM_PROVIDER_BRIDGE_COMMAND")
            or os.getenv("MEMORY_CODEX_COMMAND")
            or "codex"
        ),
        help="Codex CLI bridge command.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=float(
            os.getenv(
                "MEMORY_COMPARISON_CODEX_TIMEOUT_SECONDS",
                str(DEFAULT_TIMEOUT_SECONDS),
            )
        ),
        help="Per-call timeout for the Codex CLI bridge.",
    )
    args = parser.parse_args(argv)
    report = run_codex_answerer_canary(
        model=str(args.model),
        codex_command=str(args.codex_command),
        timeout_seconds=float(args.timeout_seconds),
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["ok"] is True else 1


if __name__ == "__main__":
    raise SystemExit(main())

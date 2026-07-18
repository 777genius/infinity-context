"""CLI helpers for memory-comparison eval commands."""

from __future__ import annotations

import argparse
import os
from math import isfinite

_DEFAULT_LOCOMO_FAST_RUNTIME_TIMEOUT_SECONDS = 180.0
_DEFAULT_CHAT_COMPLETIONS_TIMEOUT_SECONDS = 600.0
_DEFAULT_CHAT_COMPLETIONS_MAX_RETRIES = 2
_OPENAI_TRANSPORTS = frozenset({"responses", "chat-completions"})


def _memory_comparison_llms_from_args(args: argparse.Namespace):
    answerer_provider = str(args.answerer_provider)
    judge_provider = str(args.judge_provider)
    if answerer_provider == "deterministic" and judge_provider == "deterministic":
        return None, None
    uses_openai = answerer_provider == "openai" or judge_provider == "openai"
    openai_transport = (
        _memory_comparison_openai_transport_from_args(args) if uses_openai else "responses"
    )
    if uses_openai and not args.allow_paid_llm:
        raise SystemExit(
            "OpenAI memory comparison LLMs are paid/manual only; pass --allow-paid-llm"
        )
    api_key = ""
    if uses_openai:
        api_key = (
            os.getenv(str(args.openai_api_key_env)) or os.getenv("OPENAI_API_KEY") or ""
        ).strip()
    if uses_openai and openai_transport == "responses" and not api_key:
        raise SystemExit(
            f"{args.openai_api_key_env} or OPENAI_API_KEY is required for paid LLM runs"
        )

    from infinity_context_server.memory_comparison_llm import (
        CodexCliAnswerer,
        CodexCliJudge,
        EvidenceOnlyAnswerer,
        ExpectedTermsJudge,
        OpenAIResponsesAnswerer,
        OpenAIResponsesJudge,
    )

    if answerer_provider == "openai":
        answerer_model = _memory_comparison_model_from_args(
            args.answerer_model,
            env_name="MEMORY_COMPARISON_ANSWERER_MODEL",
            label="answerer",
        )
        if openai_transport == "chat-completions":
            from infinity_context_server.memory_comparison_chat_completions import (
                ChatCompletionsAnswerer,
            )

            answerer = ChatCompletionsAnswerer(
                transport=_chat_completions_transport_from_args(args, api_key=api_key),
                model=answerer_model,
            )
        else:
            answerer = OpenAIResponsesAnswerer(
                api_key=api_key,
                model=answerer_model,
            )
    elif answerer_provider == "codex":
        answerer = CodexCliAnswerer(
            model=_memory_comparison_codex_model_from_args(
                args.answerer_model,
                env_name="MEMORY_COMPARISON_ANSWERER_MODEL",
                label="answerer",
            ),
            codex_command=str(args.codex_command),
            timeout_seconds=float(args.codex_timeout_seconds),
        )
    else:
        answerer = EvidenceOnlyAnswerer()

    if judge_provider == "openai":
        judge_model = _memory_comparison_model_from_args(
            args.judge_model,
            env_name="MEMORY_COMPARISON_JUDGE_MODEL",
            label="judge",
        )
        if openai_transport == "chat-completions":
            from infinity_context_server.memory_comparison_chat_completions import (
                ChatCompletionsJudge,
            )

            judge = ChatCompletionsJudge(
                transport=_chat_completions_transport_from_args(args, api_key=api_key),
                model=judge_model,
            )
        else:
            judge = OpenAIResponsesJudge(
                api_key=api_key,
                model=judge_model,
            )
    elif judge_provider == "codex":
        judge = CodexCliJudge(
            model=_memory_comparison_codex_model_from_args(
                args.judge_model,
                env_name="MEMORY_COMPARISON_JUDGE_MODEL",
                label="judge",
            ),
            codex_command=str(args.codex_command),
            timeout_seconds=float(args.codex_timeout_seconds),
        )
    else:
        judge = ExpectedTermsJudge()
    return answerer, judge


def _memory_comparison_openai_transport_from_args(args: argparse.Namespace) -> str:
    transport = str(
        getattr(args, "openai_transport", None)
        or os.getenv("MEMORY_COMPARISON_OPENAI_TRANSPORT")
        or "responses"
    ).strip()
    if transport not in _OPENAI_TRANSPORTS:
        raise SystemExit("--openai-transport must be responses or chat-completions")
    return transport


def _chat_completions_transport_from_args(
    args: argparse.Namespace,
    *,
    api_key: str | None,
):
    from infinity_context_server.memory_comparison_chat_completions import (
        OpenAICompatibleChatCompletionsTransport,
    )

    base_url = str(
        getattr(args, "openai_base_url", None)
        or os.getenv("MEMORY_COMPARISON_OPENAI_BASE_URL")
        or ""
    ).strip()
    if not base_url:
        raise SystemExit(
            "--openai-base-url or MEMORY_COMPARISON_OPENAI_BASE_URL is required "
            "for chat-completions"
        )
    timeout_seconds = _chat_completions_float_setting(
        getattr(args, "chat_completions_timeout_seconds", None),
        env_name="MEMORY_COMPARISON_CHAT_COMPLETIONS_TIMEOUT_SECONDS",
        fallback=_DEFAULT_CHAT_COMPLETIONS_TIMEOUT_SECONDS,
    )
    if not isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise SystemExit("chat-completions timeout must be positive")
    max_retries = _chat_completions_int_setting(
        getattr(args, "chat_completions_max_retries", None),
        env_name="MEMORY_COMPARISON_CHAT_COMPLETIONS_MAX_RETRIES",
        fallback=_DEFAULT_CHAT_COMPLETIONS_MAX_RETRIES,
    )
    if not 0 <= max_retries <= 10:
        raise SystemExit("chat-completions max retries must be between 0 and 10")
    return OpenAICompatibleChatCompletionsTransport(
        api_key=api_key,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
    )


def _chat_completions_float_setting(
    value: float | None,
    *,
    env_name: str,
    fallback: float,
) -> float:
    if value is not None:
        return float(value)
    raw_value = os.getenv(env_name)
    if raw_value is None or not raw_value.strip():
        return fallback
    try:
        return float(raw_value)
    except ValueError as exc:
        raise SystemExit(f"{env_name} must be a number") from exc


def _chat_completions_int_setting(
    value: int | None,
    *,
    env_name: str,
    fallback: int,
) -> int:
    if value is not None:
        return int(value)
    raw_value = os.getenv(env_name)
    if raw_value is None or not raw_value.strip():
        return fallback
    try:
        return int(raw_value)
    except ValueError as exc:
        raise SystemExit(f"{env_name} must be an integer") from exc


def _memory_comparison_codex_model_from_args(
    value: str | None,
    *,
    env_name: str,
    label: str,
) -> str:
    model = (
        value or os.getenv(env_name) or os.getenv("MEMORY_COMPARISON_CODEX_MODEL") or "gpt-5.5"
    ).strip()
    if not model:
        raise SystemExit(f"pass --{label}-model or set {env_name}")
    return model


def _memory_comparison_model_from_args(
    value: str | None,
    *,
    env_name: str,
    label: str,
) -> str:
    model = (value or os.getenv(env_name) or "").strip()
    if not model:
        raise SystemExit(f"pass --{label}-model or set {env_name}")
    return model


def _memory_comparison_float_env_default(env_name: str, fallback: float) -> float:
    raw_value = os.getenv(env_name)
    if raw_value is None:
        return fallback
    try:
        return float(raw_value)
    except ValueError as exc:
        raise SystemExit(f"{env_name} must be a float") from exc


def _memory_comparison_runtime_timeout_from_args(args: argparse.Namespace) -> float | None:
    value = args.runtime_timeout_seconds
    if value is None:
        raw_value = os.getenv("MEMORY_COMPARISON_RUNTIME_TIMEOUT_SECONDS")
        if raw_value is not None and raw_value.strip():
            try:
                value = float(raw_value)
            except ValueError as exc:
                raise SystemExit(
                    "MEMORY_COMPARISON_RUNTIME_TIMEOUT_SECONDS must be a float"
                ) from exc
    if value is None and str(args.case_set).startswith("locomo-fast"):
        value = _DEFAULT_LOCOMO_FAST_RUNTIME_TIMEOUT_SECONDS
    if value is None:
        return None
    timeout_seconds = float(value)
    if not isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise SystemExit("--runtime-timeout-seconds must be positive")
    return timeout_seconds


def _memory_comparison_token_cost_rate_from_args(
    *,
    input_value: float | None,
    output_value: float | None,
    input_env_name: str,
    output_env_name: str,
):
    from infinity_context_server.memory_comparison_models import TokenCostRate

    return TokenCostRate(
        input_usd_per_1m=_memory_comparison_float_setting(
            input_value,
            env_name=input_env_name,
        ),
        output_usd_per_1m=_memory_comparison_float_setting(
            output_value,
            env_name=output_env_name,
        ),
    )


def _memory_comparison_float_setting(value: float | None, *, env_name: str) -> float:
    if value is not None:
        return value
    raw = os.getenv(env_name)
    if raw is None or not raw.strip():
        return 0.0
    try:
        return float(raw)
    except ValueError as exc:
        raise SystemExit(f"{env_name} must be a number") from exc


def _close_memory_comparison_clients(*clients: object | None) -> None:
    for client in clients:
        close = getattr(client, "close", None)
        if callable(close):
            close()

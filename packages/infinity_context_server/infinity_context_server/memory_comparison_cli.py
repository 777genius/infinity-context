"""CLI helpers for memory-comparison eval commands."""

from __future__ import annotations

import argparse
import os
from math import isfinite

_DEFAULT_LOCOMO_FAST_RUNTIME_TIMEOUT_SECONDS = 180.0


def _memory_comparison_llms_from_args(args: argparse.Namespace):
    answerer_provider = str(args.answerer_provider)
    judge_provider = str(args.judge_provider)
    if answerer_provider == "deterministic" and judge_provider == "deterministic":
        return None, None
    uses_openai = answerer_provider == "openai" or judge_provider == "openai"
    if uses_openai and not args.allow_paid_llm:
        raise SystemExit(
            "OpenAI memory comparison LLMs are paid/manual only; pass --allow-paid-llm"
        )
    api_key = ""
    if uses_openai:
        api_key = (
            os.getenv(str(args.openai_api_key_env)) or os.getenv("OPENAI_API_KEY") or ""
        )
    if uses_openai and not api_key:
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
        answerer = OpenAIResponsesAnswerer(
            api_key=api_key,
            model=_memory_comparison_model_from_args(
                args.answerer_model,
                env_name="MEMORY_COMPARISON_ANSWERER_MODEL",
                label="answerer",
            ),
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
        judge = OpenAIResponsesJudge(
            api_key=api_key,
            model=_memory_comparison_model_from_args(
                args.judge_model,
                env_name="MEMORY_COMPARISON_JUDGE_MODEL",
                label="judge",
            ),
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


def _memory_comparison_codex_model_from_args(
    value: str | None,
    *,
    env_name: str,
    label: str,
) -> str:
    model = (
        value
        or os.getenv(env_name)
        or os.getenv("MEMORY_COMPARISON_CODEX_MODEL")
        or "gpt-5.5"
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

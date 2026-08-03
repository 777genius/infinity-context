"""Pinned Mem0 evaluators and fixed-origin official OpenAI transport."""

from __future__ import annotations

import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import replace
from math import isfinite

from infinity_context_server.memory_comparison_llm import approximate_token_count
from infinity_context_server.memory_comparison_mem0_official_prompt_renderer import (
    MEM0_BENCHMARK_UPSTREAM_COMMIT,
    MEM0_OFFICIAL_MODEL,
    MEM0_OFFICIAL_PROMPT_FILE_SHA256,
    MEM0_OFFICIAL_PROMPT_POLICY,
    normalize_mem0_official_answer,
    parse_mem0_official_judge_response,
    render_mem0_official_answer_prompt,
    render_mem0_official_judge_prompt,
)
from infinity_context_server.memory_comparison_models import (
    AnswerResult,
    JudgeResult,
    RetrievedMemory,
    TokenUsage,
)
from infinity_context_server.memory_comparison_openai_official_transport import (
    APPROVED_OPENAI_ENDPOINT_PATH,
    APPROVED_OPENAI_ORIGIN,
    OFFICIAL_OPENAI_ROUTE_POLICY,
    OFFICIAL_OPENAI_ROUTE_POLICY_ID,
    TRUST_DIAGNOSTIC_UNTRUSTED,
    TRUST_OFFICIAL_OPENAI,
    OfficialOpenAICancelledError,
    OfficialOpenAIDeadlineError,
    OfficialOpenAIHTTPError,
    OfficialOpenAIHTTPTransport,
    OfficialOpenAIMalformedResponseError,
    OfficialOpenAIRequestError,
    OfficialOpenAIRequestTooLargeError,
    OfficialOpenAIResponseTooLargeError,
    OfficialOpenAIRoutePolicy,
    OfficialOpenAITransportError,
    OfficialOpenAIUnsafeEncodingError,
    diagnostic_openai_route,
    validate_official_chat_completion,
)
from infinity_context_server.memory_comparison_provider_provenance import (
    ProviderCallProvenance,
    ProviderChatCompletion,
    ProviderChatCompletionsPort,
    canonical_request_sha256,
)
from infinity_context_server.public_benchmark_models import PublicBenchmarkCase

_MAX_OUTPUT_TOKENS = 4096
_MAX_PROMPT_FIELD_BYTES = 786_432
_CONTEXT_SELECTION = "raw_retrieval_slice"
_MEMORY_ORDER = "chronological_ascending"
_JUDGE_EVIDENCE_MODE = "none"


Mem0OfficialChatError = OfficialOpenAITransportError
Mem0OfficialChatRequestError = OfficialOpenAIRequestError
Mem0OfficialChatDeadlineError = OfficialOpenAIDeadlineError
Mem0OfficialChatCancelledError = OfficialOpenAICancelledError
Mem0OfficialChatHTTPError = OfficialOpenAIHTTPError
Mem0OfficialChatMalformedResponseError = OfficialOpenAIMalformedResponseError
Mem0OfficialChatResponseTooLargeError = OfficialOpenAIResponseTooLargeError
Mem0OfficialChatUnsafeEncodingError = OfficialOpenAIUnsafeEncodingError
Mem0OfficialChatRequestTooLargeError = OfficialOpenAIRequestTooLargeError


class OfficialOpenAIChatCompletionsTransport:
    """Map fixed-origin OpenAI HTTP responses into provider-neutral completions."""

    def __init__(
        self,
        *,
        api_key: str,
        credential_binding_id: str,
        timeout_seconds: float = 120.0,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.25,
    ) -> None:
        self._http = OfficialOpenAIHTTPTransport(
            api_key=api_key,
            credential_binding_id=credential_binding_id,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            retry_backoff_seconds=retry_backoff_seconds,
        )
        self._diagnostic_injection = False

    @classmethod
    def for_diagnostics(
        cls,
        *,
        http_transport: OfficialOpenAIHTTPTransport,
    ) -> OfficialOpenAIChatCompletionsTransport:
        """Build an explicitly non-publishable transport for tests/diagnostics."""

        instance = cls.__new__(cls)
        instance._http = http_transport
        instance._diagnostic_injection = True
        return instance

    def complete(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int,
        temperature: float | None = None,
        response_format: Mapping[str, object] | None = None,
    ) -> ProviderChatCompletion:
        normalized_model = _model(model)
        token_limit = _bounded_int(
            max_output_tokens,
            label="max output tokens",
            maximum=32768,
            minimum=1,
        )
        if temperature is not None:
            _bounded_positive_float(
                temperature,
                label="temperature",
                maximum=2.0,
                allow_zero=True,
            )
        messages: list[dict[str, str]] = []
        normalized_system = _bounded_prompt_text(system_prompt, label="system prompt")
        normalized_user = _bounded_prompt_text(user_prompt, label="user prompt")
        if normalized_system:
            messages.append({"role": "system", "content": normalized_system})
        messages.append({"role": "user", "content": normalized_user})
        payload: dict[str, object] = {
            "model": normalized_model,
            "messages": messages,
            "max_completion_tokens": token_limit,
        }
        if response_format is not None:
            normalized_format = dict(response_format)
            if normalized_format != {"type": "json_object"}:
                raise ValueError("official OpenAI response format is not approved")
            payload["response_format"] = normalized_format
        request_body = _bounded_request_body(payload)
        raw = self._http.post(request_body)
        if raw.status_code != 200:
            raise Mem0OfficialChatHTTPError(raw.status_code)
        try:
            decoded = json.loads(raw.body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise Mem0OfficialChatMalformedResponseError(
                "official OpenAI response was not valid JSON"
            ) from None
        validate_official_chat_completion(decoded, configured_model=normalized_model)
        completion = _parse_completion(decoded)
        return replace(
            completion,
            provenance=ProviderCallProvenance(
                route=(
                    diagnostic_openai_route(raw.route)
                    if self._diagnostic_injection
                    else raw.route
                ),
                requested_model=normalized_model,
                observed_model=_provider_text(decoded, "model"),
                response_id=_provider_text(decoded, "id"),
                system_fingerprint=_provider_text(decoded, "system_fingerprint"),
                request_sha256=canonical_request_sha256(
                    endpoint_path=APPROVED_OPENAI_ENDPOINT_PATH,
                    payload=payload,
                ),
            ),
        )

    def close(self) -> None:
        self._http.close()


class Mem0OfficialChatCompletionsAnswerer:
    """Answer with exact prompts and request defaults from the pinned suite."""

    prompt_policy_id = MEM0_OFFICIAL_PROMPT_POLICY
    prompt_source_commit = MEM0_BENCHMARK_UPSTREAM_COMMIT
    benchmark_prompt_hashes = MEM0_OFFICIAL_PROMPT_FILE_SHA256
    context_selection = _CONTEXT_SELECTION

    def __init__(
        self,
        *,
        transport: ProviderChatCompletionsPort,
        model: str,
    ) -> None:
        self.model = _model(model)
        self._transport = transport

    def answer(
        self,
        case: PublicBenchmarkCase,
        memories: Sequence[RetrievedMemory],
        *,
        backend_name: str,
        cutoff: int,
    ) -> AnswerResult:
        started = time.perf_counter()
        prompt = render_mem0_official_answer_prompt(case, memories)
        completion = self._transport.complete(
            model=self.model,
            system_prompt=prompt.system,
            user_prompt=prompt.user,
            max_output_tokens=_MAX_OUTPUT_TOKENS,
            temperature=0,
        )
        result = AnswerResult(
            answer=completion.text,
            model=self.model,
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
            token_usage=_token_usage(
                completion,
                prompt=_combined_prompt(prompt.system, prompt.user),
            ),
            metadata={
                **_stage_metadata(case, stage="answerer"),
                **_completion_provider_metadata(completion),
                "backend_name": backend_name,
                "cutoff": cutoff,
                "answer_postprocess": _answer_postprocess(case),
            },
        )
        return normalize_mem0_official_answer(case, result)

    def close(self) -> None:
        self._transport.close()


class Mem0OfficialChatCompletionsJudge:
    """Judge without retrieval evidence, matching the pinned published lane."""

    prompt_policy_id = MEM0_OFFICIAL_PROMPT_POLICY
    prompt_source_commit = MEM0_BENCHMARK_UPSTREAM_COMMIT
    benchmark_prompt_hashes = MEM0_OFFICIAL_PROMPT_FILE_SHA256
    context_selection = _CONTEXT_SELECTION
    judge_evidence_mode = _JUDGE_EVIDENCE_MODE

    def __init__(
        self,
        *,
        transport: ProviderChatCompletionsPort,
        model: str,
    ) -> None:
        self.model = _model(model)
        self._transport = transport

    def judge(
        self,
        case: PublicBenchmarkCase,
        answer: AnswerResult,
        memories: Sequence[RetrievedMemory],
        *,
        backend_name: str,
        cutoff: int,
    ) -> JudgeResult:
        del memories
        started = time.perf_counter()
        normalized_answer = normalize_mem0_official_answer(case, answer)
        prompt = render_mem0_official_judge_prompt(case, normalized_answer)
        completion = self._transport.complete(
            model=self.model,
            system_prompt=prompt.system,
            user_prompt=prompt.user,
            max_output_tokens=_MAX_OUTPUT_TOKENS,
            temperature=0,
            response_format=({"type": "json_object"} if _benchmark(case) == "locomo" else None),
        )
        decision = parse_mem0_official_judge_response(case, completion.text)
        return JudgeResult(
            verdict="correct" if decision.correct else "incorrect",
            score=1.0 if decision.correct else 0.0,
            reason=f"official_{decision.verdict.casefold()}",
            model=self.model,
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
            token_usage=_token_usage(
                completion,
                prompt=_combined_prompt(prompt.system, prompt.user),
            ),
            metadata={
                **_stage_metadata(case, stage="judge"),
                **_completion_provider_metadata(completion),
                "backend_name": backend_name,
                "cutoff": cutoff,
                "judge_evidence_mode": _JUDGE_EVIDENCE_MODE,
                "judge_parser": (
                    "json_correct_wrong" if _benchmark(case) == "locomo" else "final_yes_no"
                ),
            },
        )

    def close(self) -> None:
        self._transport.close()


def _bounded_request_body(payload: Mapping[str, object]) -> bytes:
    return json.dumps(
        dict(payload),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def _bounded_prompt_text(value: object, *, label: str) -> str:
    normalized = str(value or "")
    if len(normalized.encode()) > _MAX_PROMPT_FIELD_BYTES:
        raise Mem0OfficialChatRequestTooLargeError(
            f"official OpenAI {label} exceeded the field limit"
        )
    return normalized


def _parse_completion(payload: object) -> ProviderChatCompletion:
    if not isinstance(payload, Mapping):
        raise _malformed_response()
    choices = payload.get("choices")
    if not isinstance(choices, Sequence) or isinstance(choices, str | bytes) or not choices:
        raise _malformed_response()
    first = choices[0]
    if not isinstance(first, Mapping):
        raise _malformed_response()
    message = first.get("message")
    content = message.get("content") if isinstance(message, Mapping) else None
    text = _content_text(content)
    if not text:
        raise _malformed_response()
    usage = payload.get("usage")
    prompt_tokens, prompt_observed = _provider_usage_int(usage, "prompt_tokens")
    completion_tokens, completion_observed = _provider_usage_int(usage, "completion_tokens")
    finish_reason = _provider_text(first, "finish_reason").casefold()
    return ProviderChatCompletion(
        text=text,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        token_usage_source=("provider_observed" if prompt_observed and completion_observed else ""),
        finish_reason=finish_reason,
        finish_reason_source="provider_observed" if finish_reason else "",
    )


def _content_text(content: object) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, Sequence) or isinstance(content, str | bytes):
        return ""
    parts = [
        str(part.get("text") or "").strip()
        for part in content
        if isinstance(part, Mapping) and str(part.get("text") or "").strip()
    ]
    return "\n".join(parts)


def _provider_usage_int(usage: object, name: str) -> tuple[int, bool]:
    if not isinstance(usage, Mapping) or name not in usage:
        return 0, False
    value = usage[name]
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return 0, False
    return value, True


def _provider_text(payload: object, key: str) -> str:
    if not isinstance(payload, Mapping):
        return ""
    value = payload.get(key)
    return value.strip() if isinstance(value, str) else ""


def _token_usage(completion: ProviderChatCompletion, *, prompt: str) -> TokenUsage:
    return TokenUsage(
        prompt_tokens=completion.prompt_tokens or approximate_token_count(prompt),
        completion_tokens=(
            completion.completion_tokens or approximate_token_count(completion.text)
        ),
    )


def _completion_provider_metadata(completion: ProviderChatCompletion) -> dict[str, object]:
    observed_usage = (
        completion.token_usage_source == "provider_observed"
        and completion.prompt_tokens > 0
        and completion.completion_tokens > 0
    )
    metadata: dict[str, object] = {
        "token_usage_source": (
            "provider_observed" if observed_usage else "fallback_approximation"
        ),
        "finish_reason": completion.finish_reason,
        "finish_reason_source": completion.finish_reason_source,
    }
    if completion.provenance is not None:
        metadata["provider_provenance"] = completion.provenance.public_payload()
    return metadata


def _stage_metadata(case: PublicBenchmarkCase, *, stage: str) -> dict[str, object]:
    benchmark = _benchmark(case)
    return {
        "provider": "openai",
        "transport": "official-chat-completions",
        "stage": stage,
        "prompt_policy_id": MEM0_OFFICIAL_PROMPT_POLICY,
        "prompt_source_commit": MEM0_BENCHMARK_UPSTREAM_COMMIT,
        "prompt_file_sha256": MEM0_OFFICIAL_PROMPT_FILE_SHA256[benchmark],
        "prompt_template": benchmark,
        "context_selection": _CONTEXT_SELECTION,
        "memory_order": _MEMORY_ORDER,
        "temperature_policy": "reasoning_model_default",
        "max_completion_tokens": _MAX_OUTPUT_TOKENS,
    }


def _answer_postprocess(case: PublicBenchmarkCase) -> str:
    if _benchmark(case) == "longmemeval":
        return "strip_mem_thinking_then_last_answer_marker"
    return "last_answer_marker"


def _benchmark(case: PublicBenchmarkCase) -> str:
    benchmark = case.benchmark.strip().casefold()
    if benchmark not in MEM0_OFFICIAL_PROMPT_FILE_SHA256:
        raise ValueError(f"unsupported official mem0 benchmark: {case.benchmark}")
    return benchmark


def _model(value: str) -> str:
    model = str(value or "").strip()
    if model != MEM0_OFFICIAL_MODEL:
        raise ValueError(f"official mem0 evaluator requires {MEM0_OFFICIAL_MODEL}")
    return model


def _combined_prompt(system: str, user: str) -> str:
    return "\n".join(part for part in (system, user) if part)


def _bounded_int(
    value: int,
    *,
    label: str,
    maximum: int,
    minimum: int = 0,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"official OpenAI {label} must be between {minimum} and {maximum}")
    return value


def _bounded_positive_float(
    value: float,
    *,
    label: str,
    maximum: float,
    allow_zero: bool = False,
) -> float:
    if isinstance(value, bool):
        raise ValueError(f"official OpenAI {label} must be numeric")
    normalized = float(value)
    minimum_ok = normalized >= 0 if allow_zero else normalized > 0
    if not isfinite(normalized) or not minimum_ok or normalized > maximum:
        comparator = "non-negative" if allow_zero else "positive"
        raise ValueError(f"official OpenAI {label} must be {comparator} and at most {maximum:g}")
    return normalized


def _malformed_response() -> Mem0OfficialChatMalformedResponseError:
    return Mem0OfficialChatMalformedResponseError(
        "official OpenAI response did not include assistant text"
    )


__all__ = (
    "APPROVED_OPENAI_ENDPOINT_PATH",
    "APPROVED_OPENAI_ORIGIN",
    "Mem0OfficialChatCancelledError",
    "Mem0OfficialChatCompletionsAnswerer",
    "Mem0OfficialChatCompletionsJudge",
    "Mem0OfficialChatDeadlineError",
    "Mem0OfficialChatError",
    "Mem0OfficialChatHTTPError",
    "Mem0OfficialChatMalformedResponseError",
    "Mem0OfficialChatRequestError",
    "Mem0OfficialChatRequestTooLargeError",
    "Mem0OfficialChatResponseTooLargeError",
    "Mem0OfficialChatUnsafeEncodingError",
    "OFFICIAL_OPENAI_ROUTE_POLICY",
    "OFFICIAL_OPENAI_ROUTE_POLICY_ID",
    "OfficialOpenAIChatCompletionsTransport",
    "OfficialOpenAIRoutePolicy",
    "TRUST_DIAGNOSTIC_UNTRUSTED",
    "TRUST_OFFICIAL_OPENAI",
)

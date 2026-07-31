from __future__ import annotations

import asyncio
import inspect
import json
import threading
import time
from collections.abc import Mapping

import httpx
import pytest
from infinity_context_server.memory_comparison_mem0_official_chat import (
    APPROVED_OPENAI_ENDPOINT_PATH,
    APPROVED_OPENAI_ORIGIN,
    OFFICIAL_OPENAI_ROUTE_POLICY,
    Mem0OfficialChatCancelledError,
    Mem0OfficialChatCompletionsAnswerer,
    Mem0OfficialChatCompletionsJudge,
    Mem0OfficialChatDeadlineError,
    Mem0OfficialChatHTTPError,
    Mem0OfficialChatMalformedResponseError,
    Mem0OfficialChatRequestTooLargeError,
    Mem0OfficialChatResponseTooLargeError,
    Mem0OfficialChatUnsafeEncodingError,
    OfficialOpenAIChatCompletionsTransport,
)
from infinity_context_server.memory_comparison_mem0_official_prompt_renderer import (
    MEM0_OFFICIAL_PROMPT_FILE_SHA256,
    MEM0_OFFICIAL_PROMPT_POLICY,
)
from infinity_context_server.memory_comparison_models import AnswerResult, RetrievedMemory
from infinity_context_server.memory_comparison_openai_official_transport import (
    OfficialOpenAIHTTPResponse,
    OfficialOpenAIHTTPTransport,
)
from infinity_context_server.memory_comparison_provider_provenance import (
    ProviderChatCompletion,
    ProviderRouteAttestation,
    canonical_request_sha256,
    provider_provenance_contract,
)
from infinity_context_server.public_benchmark_models import PublicBenchmarkCase

_TEST_KEY = "sk-proj-" + "a" * 32


class _Transport:
    def __init__(self, *responses: str) -> None:
        self.responses = list(responses)
        self.requests: list[dict[str, object]] = []
        self.closed = False

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
        self.requests.append(
            {
                "model": model,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "max_output_tokens": max_output_tokens,
                "temperature": temperature,
                "response_format": response_format,
            }
        )
        return ProviderChatCompletion(
            text=self.responses.pop(0),
            prompt_tokens=10,
            completion_tokens=5,
            token_usage_source="provider_observed",
            finish_reason="stop",
            finish_reason_source="provider_observed",
        )

    def close(self) -> None:
        self.closed = True


class _AsyncChunks(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes], *, stall_seconds: float = 0) -> None:
        self._chunks = chunks
        self._stall_seconds = stall_seconds
        self.started = threading.Event()
        self.closed = False

    async def __aiter__(self):
        for index, chunk in enumerate(self._chunks):
            self.started.set()
            if index or self._stall_seconds:
                await asyncio.sleep(self._stall_seconds)
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


def test_diagnostic_transport_has_fixed_route_and_gpt5_request_semantics() -> None:
    seen: list[tuple[str, dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == f"Bearer {_TEST_KEY}"
        assert request.headers["Accept-Encoding"] == "identity"
        payload = json.loads(request.content)
        seen.append((str(request.url), payload))
        return _response(response_id="chatcmpl-answer123")

    transport = _diagnostic(httpx.MockTransport(handler))
    try:
        completion = transport.complete(
            model="gpt-5",
            system_prompt="",
            user_prompt="question",
            max_output_tokens=4096,
            temperature=0,
        )
    finally:
        transport.close()

    assert seen[0][0] == f"{APPROVED_OPENAI_ORIGIN}{APPROVED_OPENAI_ENDPOINT_PATH}"
    assert seen[0][1] == {
        "model": "gpt-5",
        "messages": [{"role": "user", "content": "question"}],
        "max_completion_tokens": 4096,
    }
    assert completion.token_usage_source == "provider_observed"
    assert completion.finish_reason == "stop"
    assert completion.provenance is not None
    provenance = completion.provenance.public_payload()
    assert provenance["trust"] == "diagnostic_untrusted"
    assert provenance["transport_evidence"] == "injected-diagnostic-transport"
    assert provenance["observed_model"] == "gpt-5"
    assert provenance["response_id"] == "chatcmpl-answer123"
    assert provenance["request_sha256"] == canonical_request_sha256(
        endpoint_path=APPROVED_OPENAI_ENDPOINT_PATH,
        payload=seen[0][1],
    )
    rendered = json.dumps(provenance)
    assert _TEST_KEY not in rendered
    assert "run-binding" not in rendered


def test_injected_local_transport_can_never_be_publishable() -> None:
    call_index = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal call_index
        call_index += 1
        return _response(response_id=f"chatcmpl-local{call_index:08d}")

    transport = _diagnostic(httpx.MockTransport(handler))
    try:
        first = transport.complete(
            model="gpt-5",
            system_prompt="",
            user_prompt="answer",
            max_output_tokens=20,
        )
        second = transport.complete(
            model="gpt-5",
            system_prompt="",
            user_prompt="judge",
            max_output_tokens=20,
        )
    finally:
        transport.close()
    assert first.provenance is not None
    assert second.provenance is not None
    evaluation = {
        "generation": {
            "metadata": {"provider_provenance": first.provenance.public_payload()}
        },
        "judgment": {
            "metadata": {"provider_provenance": second.provenance.public_payload()}
        },
    }

    contract = provider_provenance_contract(
        (evaluation,),
        required_model="gpt-5",
        route_policy=OFFICIAL_OPENAI_ROUTE_POLICY,
    )

    assert contract["matches"] is False
    assert contract["issues"]["answerer_route"] == 1
    assert contract["issues"]["judge_route"] == 1


def test_high_level_diagnostic_injection_overrides_forged_official_route() -> None:
    class ForgedHTTPTransport:
        def post(self, _: bytes) -> OfficialOpenAIHTTPResponse:
            route = ProviderRouteAttestation(
                trust="official_openai",
                origin=APPROVED_OPENAI_ORIGIN,
                endpoint_path=APPROVED_OPENAI_ENDPOINT_PATH,
                route_sha256="a" * 64,
                transport_evidence="httpx-direct-tls-no-env-v1",
                credential_binding_id=f"sha256:{'b' * 64}",
                response_status=200,
            )
            return OfficialOpenAIHTTPResponse(
                200,
                json.dumps(
                    {
                        "id": "chatcmpl-forged123",
                        "object": "chat.completion",
                        "model": "gpt-5",
                        "system_fingerprint": "fp_abcdef1234",
                        "choices": [
                            {
                                "message": {
                                    "role": "assistant",
                                    "content": "answer",
                                },
                                "index": 0,
                                "finish_reason": "stop",
                            }
                        ],
                    }
                ).encode(),
                route,
            )

        def close(self) -> None:
            return None

    transport = OfficialOpenAIChatCompletionsTransport.for_diagnostics(
        http_transport=ForgedHTTPTransport()  # type: ignore[arg-type]
    )

    completion = transport.complete(
        model="gpt-5",
        system_prompt="",
        user_prompt="question",
        max_output_tokens=20,
    )

    assert completion.provenance is not None
    provenance = completion.provenance.public_payload()
    assert provenance["trust"] == "diagnostic_untrusted"
    assert provenance["origin"] == "[redacted]"


def test_official_transport_exposes_no_custom_client_or_route() -> None:
    parameters = inspect.signature(OfficialOpenAIChatCompletionsTransport).parameters

    assert {"base_url", "transport", "client", "sleep", "clock"}.isdisjoint(parameters)
    assert "http_transport" in inspect.signature(
        OfficialOpenAIChatCompletionsTransport.for_diagnostics
    ).parameters


@pytest.mark.parametrize("api_key", ("", "key", "fake-key", "sk-proj-short"))
def test_official_transport_rejects_fake_api_key(api_key: str) -> None:
    with pytest.raises(ValueError, match="valid official API key"):
        OfficialOpenAIChatCompletionsTransport(
            api_key=api_key,
            credential_binding_id="binding",
        )


def test_official_transport_errors_redact_body_key_and_route_details() -> None:
    private_body = f"provider body {_TEST_KEY}"
    transport = _diagnostic(
        httpx.MockTransport(lambda _: httpx.Response(401, text=private_body))
    )

    try:
        with pytest.raises(Mem0OfficialChatHTTPError) as exc_info:
            transport.complete(
                model="gpt-5",
                system_prompt="",
                user_prompt="question",
                max_output_tokens=20,
            )
    finally:
        transport.close()

    rendered = str(exc_info.value)
    assert rendered == "official OpenAI request failed with HTTP 401"
    assert _TEST_KEY not in rendered
    assert private_body not in rendered
    assert APPROVED_OPENAI_ORIGIN not in rendered


@pytest.mark.parametrize("timeout", (0, -1, float("inf"), 601))
def test_official_transport_rejects_invalid_timeouts(timeout: float) -> None:
    with pytest.raises(ValueError, match="timeout"):
        OfficialOpenAIChatCompletionsTransport(
            api_key=_TEST_KEY,
            credential_binding_id="binding",
            timeout_seconds=timeout,
        )


def test_official_transport_rejects_malformed_output_without_body_echo() -> None:
    transport = _diagnostic(
        httpx.MockTransport(
            lambda _: _raw_json_response({"private": "raw-provider-body"})
        )
    )
    try:
        with pytest.raises(Mem0OfficialChatMalformedResponseError) as exc_info:
            transport.complete(
                model="gpt-5",
                system_prompt="",
                user_prompt="question",
                max_output_tokens=20,
            )
    finally:
        transport.close()
    assert "raw-provider-body" not in str(exc_info.value)


def test_response_stream_has_hard_cap_and_is_closed() -> None:
    stream = _AsyncChunks([b"x" * 262_144 for _ in range(20)])
    transport = _diagnostic(
        httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                stream=stream,
            )
        )
    )
    try:
        with pytest.raises(Mem0OfficialChatResponseTooLargeError):
            transport.complete(
                model="gpt-5",
                system_prompt="",
                user_prompt="question",
                max_output_tokens=20,
            )
    finally:
        transport.close()
    assert stream.closed is True


def test_stalled_stream_hits_total_deadline_and_is_closed() -> None:
    stream = _AsyncChunks([b'{"partial":', b'"never"}'], stall_seconds=1.0)
    transport = _diagnostic(
        httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                stream=stream,
            )
        ),
        timeout_seconds=0.03,
    )
    started = time.monotonic()
    try:
        with pytest.raises(Mem0OfficialChatDeadlineError):
            transport.complete(
                model="gpt-5",
                system_prompt="",
                user_prompt="question",
                max_output_tokens=20,
            )
    finally:
        transport.close()
    assert time.monotonic() - started < 0.5
    assert stream.closed is True


def test_connect_stall_is_cancelled_by_total_deadline() -> None:
    cancelled = threading.Event()

    async def handler(_: httpx.Request) -> httpx.Response:
        try:
            await asyncio.sleep(1)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return _response(response_id="chatcmpl-tooLate123")

    transport = _diagnostic(
        httpx.MockTransport(handler),
        timeout_seconds=0.03,
    )
    try:
        with pytest.raises(Mem0OfficialChatDeadlineError):
            transport.complete(
                model="gpt-5",
                system_prompt="",
                user_prompt="question",
                max_output_tokens=20,
            )
    finally:
        transport.close()
    assert cancelled.is_set()


def test_retry_backoff_is_inside_total_deadline() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503)

    transport = _diagnostic(
        httpx.MockTransport(handler),
        timeout_seconds=0.03,
        max_retries=5,
        retry_backoff_seconds=1.0,
    )
    try:
        with pytest.raises(Mem0OfficialChatDeadlineError):
            transport.complete(
                model="gpt-5",
                system_prompt="",
                user_prompt="question",
                max_output_tokens=20,
            )
    finally:
        transport.close()
    assert calls == 1


def test_close_cancels_stalled_stream_and_closes_response() -> None:
    stream = _AsyncChunks([b'{"partial":', b'"never"}'], stall_seconds=10.0)
    transport = _diagnostic(
        httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                stream=stream,
            )
        ),
        timeout_seconds=30.0,
    )
    errors: list[BaseException] = []

    def invoke() -> None:
        try:
            transport.complete(
                model="gpt-5",
                system_prompt="",
                user_prompt="question",
                max_output_tokens=20,
            )
        except BaseException as exc:  # pragma: no cover - asserted by caller
            errors.append(exc)

    thread = threading.Thread(target=invoke)
    thread.start()
    assert stream.started.wait(timeout=1)
    transport.close()
    thread.join(timeout=1)

    assert not thread.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], Mem0OfficialChatCancelledError)
    assert stream.closed is True


def test_unsafe_content_encoding_is_rejected_before_read() -> None:
    stream = _AsyncChunks([b"compressed-private-body"])
    transport = _diagnostic(
        httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                headers={"Content-Encoding": "gzip"},
                stream=stream,
            )
        )
    )
    try:
        with pytest.raises(Mem0OfficialChatUnsafeEncodingError):
            transport.complete(
                model="gpt-5",
                system_prompt="",
                user_prompt="question",
                max_output_tokens=20,
            )
    finally:
        transport.close()
    assert stream.closed is True


@pytest.mark.parametrize("status", (200, 429, 500))
def test_compressed_success_and_retryable_errors_fail_without_retry(status: int) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            status,
            headers={"Content-Encoding": "gzip"},
            stream=_AsyncChunks([b"compressed"]),
        )

    transport = _diagnostic(httpx.MockTransport(handler), max_retries=2)
    try:
        with pytest.raises(Mem0OfficialChatUnsafeEncodingError):
            transport.complete(
                model="gpt-5",
                system_prompt="",
                user_prompt="question",
                max_output_tokens=20,
            )
    finally:
        transport.close()
    assert calls == 1


@pytest.mark.parametrize(
    "content_type",
    ("text/json", "application/json; charset=latin-1", "application/json; profile=x"),
)
def test_success_requires_application_json_utf8(content_type: str) -> None:
    payload = _valid_payload(response_id="chatcmpl-content123")
    response = httpx.Response(
        200,
        headers={"Content-Type": content_type},
        stream=_AsyncChunks([json.dumps(payload).encode()]),
    )
    transport = _diagnostic(httpx.MockTransport(lambda _: response))
    try:
        with pytest.raises(Mem0OfficialChatMalformedResponseError):
            transport.complete(
                model="gpt-5",
                system_prompt="",
                user_prompt="question",
                max_output_tokens=20,
            )
    finally:
        transport.close()


def test_arbitrary_2xx_is_not_success() -> None:
    response = _raw_json_response(_valid_payload(response_id="chatcmpl-status123"))
    response.status_code = 201
    transport = _diagnostic(httpx.MockTransport(lambda _: response))
    try:
        with pytest.raises(Mem0OfficialChatHTTPError) as exc_info:
            transport.complete(
                model="gpt-5",
                system_prompt="",
                user_prompt="question",
                max_output_tokens=20,
            )
    finally:
        transport.close()
    assert exc_info.value.status_code == 201


@pytest.mark.parametrize(
    ("path", "value"),
    (
        ("object", "chat.completion.chunk"),
        ("model", "gpt-5-fake"),
        ("id", "fake-id"),
        ("system_fingerprint", "fp_test"),
        ("choice_index", 1),
        ("choice_index", False),
        ("choice_count", 2),
        ("message_role", "user"),
    ),
)
def test_completion_envelope_is_strict(path: str, value: object) -> None:
    payload = _valid_payload(response_id="chatcmpl-strict123")
    if path == "choice_index":
        payload["choices"][0]["index"] = value
    elif path == "choice_count":
        payload["choices"].append(dict(payload["choices"][0]))
    elif path == "message_role":
        payload["choices"][0]["message"]["role"] = value
    else:
        payload[path] = value
    transport = _diagnostic(
        httpx.MockTransport(lambda _: _raw_json_response(payload))
    )
    try:
        with pytest.raises(Mem0OfficialChatMalformedResponseError):
            transport.complete(
                model="gpt-5",
                system_prompt="",
                user_prompt="question",
                max_output_tokens=20,
            )
    finally:
        transport.close()


def test_oversized_prompt_fails_before_zero_http_calls() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _response(response_id="chatcmpl-unexpected1")

    transport = _diagnostic(httpx.MockTransport(handler))
    try:
        with pytest.raises(Mem0OfficialChatRequestTooLargeError):
            transport.complete(
                model="gpt-5",
                system_prompt="",
                user_prompt="x" * 800_000,
                max_output_tokens=20,
            )
    finally:
        transport.close()
    assert calls == 0


def test_combined_canonical_request_body_cap_fails_before_http() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _response(response_id="chatcmpl-unexpected2")

    transport = _diagnostic(httpx.MockTransport(handler))
    try:
        with pytest.raises(Mem0OfficialChatRequestTooLargeError):
            transport.complete(
                model="gpt-5",
                system_prompt="s" * 600_000,
                user_prompt="u" * 600_000,
                max_output_tokens=20,
            )
    finally:
        transport.close()
    assert calls == 0


def test_official_locomo_answer_and_judge_use_pinned_request_contract() -> None:
    answer_transport = _Transport("thinking\nANSWER: Postgres")
    judge_transport = _Transport('{"reasoning":"same fact","label":"CORRECT"}')
    answerer = Mem0OfficialChatCompletionsAnswerer(
        transport=answer_transport,
        model="gpt-5",
    )
    judge = Mem0OfficialChatCompletionsJudge(
        transport=judge_transport,
        model="gpt-5",
    )
    case = _locomo_case()
    memories = (
        RetrievedMemory(
            text="Alex uses Postgres.",
            rank=1,
            created_at="2024-01-01T00:00:00",
        ),
    )

    answer = answerer.answer(case, memories, backend_name="infinity-context", cutoff=200)
    decision = judge.judge(
        case,
        answer,
        memories,
        backend_name="infinity-context",
        cutoff=200,
    )

    assert answer.answer == "Postgres"
    assert answer.token_usage.total_tokens == 15
    assert answer.metadata["prompt_policy_id"] == MEM0_OFFICIAL_PROMPT_POLICY
    assert answer.metadata["prompt_file_sha256"] == MEM0_OFFICIAL_PROMPT_FILE_SHA256["locomo"]
    assert answer.metadata["context_selection"] == "raw_retrieval_slice"
    assert answer.metadata["provider"] == "openai"
    assert answer.metadata["transport"] == "official-chat-completions"
    assert answer.metadata["token_usage_source"] == "provider_observed"
    assert answer.metadata["finish_reason"] == "stop"
    assert decision.verdict == "correct"
    assert decision.metadata["judge_evidence_mode"] == "none"

    assert answer_transport.requests[0]["max_output_tokens"] == 4096
    assert answer_transport.requests[0]["temperature"] == 0
    judge_request = judge_transport.requests[0]
    assert judge_request["response_format"] == {"type": "json_object"}
    assert "## Evidence" not in str(judge_request["user_prompt"])
    assert "Postgres full rubric" in str(judge_request["user_prompt"])


def test_official_longmemeval_judge_uses_final_yes_no_without_json_mode() -> None:
    transport = _Transport("<judge_thinking>matches</judge_thinking>\nyes")
    judge = Mem0OfficialChatCompletionsJudge(transport=transport, model="gpt-5")
    case = PublicBenchmarkCase(
        benchmark="longmemeval",
        case_id="lme-1",
        question="Which database?",
        expected_terms=("Postgres",),
        metadata={
            "question_type": "knowledge-update",
            "question_date": "2024/01/04 (Thu) 09:30",
            "_evaluator_ground_truth": "Postgres",
        },
    )

    decision = judge.judge(
        case,
        AnswerResult(answer="<mem_thinking>hidden</mem_thinking>\nANSWER: Postgres"),
        (),
        backend_name="infinity-context",
        cutoff=50,
    )

    assert decision.verdict == "correct"
    assert decision.metadata["judge_parser"] == "final_yes_no"
    assert transport.requests[0]["response_format"] is None
    prompt_text = str(transport.requests[0]["user_prompt"])
    assert "<mem_thinking>hidden" not in prompt_text
    assert "Model Response: Postgres" in prompt_text


def test_official_adapter_rejects_unpinned_model_before_requests() -> None:
    transport = _Transport("answer")

    with pytest.raises(ValueError, match="official mem0 evaluator requires gpt-5"):
        Mem0OfficialChatCompletionsAnswerer(transport=transport, model="gpt-4.1")
    with pytest.raises(ValueError, match="official mem0 evaluator requires gpt-5"):
        Mem0OfficialChatCompletionsJudge(transport=transport, model="")
    assert transport.requests == []


def _diagnostic(
    transport: httpx.AsyncBaseTransport,
    *,
    timeout_seconds: float = 120.0,
    max_retries: int = 0,
    retry_backoff_seconds: float = 0.25,
) -> OfficialOpenAIChatCompletionsTransport:
    raw_transport = OfficialOpenAIHTTPTransport.for_diagnostics(
        api_key=_TEST_KEY,
        credential_binding_id="run-binding",
        transport=transport,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        retry_backoff_seconds=retry_backoff_seconds,
    )
    return OfficialOpenAIChatCompletionsTransport.for_diagnostics(
        http_transport=raw_transport
    )


def _response(*, response_id: str) -> httpx.Response:
    return _raw_json_response(_valid_payload(response_id=response_id))


def _valid_payload(*, response_id: str) -> dict[str, object]:
    return {
        "id": response_id,
        "object": "chat.completion",
        "model": "gpt-5",
        "system_fingerprint": "fp_abcdef1234",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "answer"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7},
    }


def _raw_json_response(payload: Mapping[str, object]) -> httpx.Response:
    return httpx.Response(
        200,
        headers={"Content-Type": "application/json"},
        stream=_AsyncChunks([json.dumps(dict(payload)).encode()]),
    )


def _locomo_case() -> PublicBenchmarkCase:
    return PublicBenchmarkCase(
        benchmark="locomo",
        case_id="locomo-1",
        question="Which database?",
        expected_terms=("Postgres",),
        metadata={
            "category": 4,
            "reference_date": "January 04, 2024",
            "_evaluator_ground_truth": "Postgres full rubric",
        },
    )

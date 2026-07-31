from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

import httpx
import pytest
from infinity_context_server.memory_comparison_benchmark_identity import (
    mem0_benchmark_user_id,
)
from infinity_context_server.memory_comparison_http import Mem0HttpComparisonBackend
from infinity_context_server.memory_comparison_locomo_transport import (
    RunScopedLocomoTransportEvidenceKey,
    locomo_timestamp_evidence_payload_is_exact,
    public_locomo_timestamp_transport_evidence,
)
from infinity_context_server.memory_comparison_mem0_http_observation import (
    MEM0_HTTP_OBSERVATION_BOUNDARY,
    MEM0_HTTP_OBSERVED_REPRESENTATION,
    Mem0HttpObservationRecorder,
    expected_official_locomo_turn_for_group,
    observe_mem0_add_request,
)
from infinity_context_server.public_benchmark_models import (
    BenchmarkMemoryInput,
    PublicBenchmarkCase,
)

_RUN_ID = "Run_X"
_CORPUS_KEY = "corpus-a"
_TIMESTAMP = 1_683_554_160


def _official_case() -> PublicBenchmarkCase:
    return PublicBenchmarkCase(
        benchmark="locomo",
        case_id="corpus-a:qa:1",
        question="What did Caroline remember?",
        expected_terms=("blue notebook",),
        memories=(
            BenchmarkMemoryInput(
                text=(
                    "session_1 date: 1:56 pm on 8 May, 2023\n"
                    "D1:1 Caroline: The checklist is in the blue notebook."
                ),
                source_external_id="locomo:corpus-a:session_1:D1:1:turn",
                metadata={
                    "role": "user",
                    "timestamp": _TIMESTAMP,
                    "session_key": "session_1",
                    "session_date": "1:56 pm on 8 May, 2023",
                    "dia_id": "D1:1",
                    "speaker": "Caroline",
                },
            ),
        ),
        metadata={"locomo_ingest_mode": "official-turns"},
    )


def _expected_turn():
    expected_turn = expected_official_locomo_turn_for_group(
        _official_case(),
        group_index=1,
        run_id=_RUN_ID,
        corpus_key=_CORPUS_KEY,
    )
    assert expected_turn is not None
    return expected_turn


def _official_http_request(*, speaker: str = "Caroline") -> httpx.Request:
    case = _official_case()
    source_id = "locomo:corpus-a:session_1:D1:1:turn"
    return httpx.Request(
        "POST",
        "http://mem0.test/memories",
        headers={"Idempotency-Key": source_id},
        json={
            "messages": [{"role": "user", "content": case.memories[0].text}],
            "user_id": mem0_benchmark_user_id(_RUN_ID),
            "run_id": _RUN_ID,
            "metadata": {
                "benchmark": "locomo",
                "case_id": case.case_id,
                "corpus_key": _CORPUS_KEY,
                "source_external_id": source_id,
                "source_id": source_id,
                "session_key": "session_1",
                "session_date": "1:56 pm on 8 May, 2023",
                "dia_id": "D1:1",
                "role": "user",
                "speaker": speaker,
                "locomo_evidence_ref": "D1:1",
                "source_timestamp": _TIMESTAMP,
            },
            "timestamp": _TIMESTAMP,
        },
    )


def test_runtime_observes_exact_official_turn_at_wrapper_http_transport_seam() -> None:
    observed_requests: list[tuple[dict[str, str], dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed_requests.append((dict(request.headers), json.loads(request.content)))
        return httpx.Response(200, json={"results": [{"id": "memory-1"}]})

    backend = Mem0HttpComparisonBackend(
        base_url="http://mem0.test",
        reset_user_on_start=False,
        send_timestamps=True,
        transport=httpx.MockTransport(handler),
    )
    try:
        result = backend.ingest(
            _official_case(),
            run_id=_RUN_ID,
            corpus_key=_CORPUS_KEY,
        )
        verifier = backend.locomo_timestamp_transport_verifier(run_id=_RUN_ID)
        evidence = backend.locomo_timestamp_transport_evidence(run_id=_RUN_ID)
    finally:
        backend.close()

    assert len(observed_requests) == 1
    headers, payload = observed_requests[0]
    assert headers["idempotency-key"] == "locomo:corpus-a:session_1:D1:1:turn"
    assert payload["user_id"] == mem0_benchmark_user_id(_RUN_ID)
    assert payload["user_id"] != "memo-stack-comparison-run-x"
    assert payload["timestamp"] == _TIMESTAMP
    assert payload["metadata"]["source_timestamp"] == _TIMESTAMP
    assert verifier is not None
    assert len(evidence) == 1

    receipt = public_locomo_timestamp_transport_evidence(
        evidence[0],
        verifier=verifier,
        expected_run_id=_RUN_ID,
        expected_corpus_key=_CORPUS_KEY,
    )
    assert locomo_timestamp_evidence_payload_is_exact(receipt)
    assert result.metadata["locomo_http_request_observation"] == {
        "required": True,
        "evidence_count": 1,
        "boundary": MEM0_HTTP_OBSERVATION_BOUNDARY,
        "observed_representation": MEM0_HTTP_OBSERVED_REPRESENTATION,
        "downstream_provider_sdk_wire_bytes_observed": False,
    }


def test_runtime_preserves_source_timestamp_without_claiming_unsent_timestamp() -> None:
    observed_payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed_payloads.append(json.loads(request.content))
        return httpx.Response(200, json={"results": [{"id": "memory-1"}]})

    backend = Mem0HttpComparisonBackend(
        base_url="http://mem0.test",
        reset_user_on_start=False,
        send_timestamps=False,
        transport=httpx.MockTransport(handler),
    )
    try:
        result = backend.ingest(
            _official_case(),
            run_id=_RUN_ID,
            corpus_key=_CORPUS_KEY,
        )
        verifier = backend.locomo_timestamp_transport_verifier(run_id=_RUN_ID)
        evidence = backend.locomo_timestamp_transport_evidence(run_id=_RUN_ID)
    finally:
        backend.close()

    assert "timestamp" not in observed_payloads[0]
    assert observed_payloads[0]["metadata"]["source_timestamp"] == _TIMESTAMP
    assert verifier is None
    assert evidence == ()
    observation = result.metadata["locomo_http_request_observation"]
    assert observation["required"] is True
    assert observation["evidence_count"] == 0
    assert observation["downstream_provider_sdk_wire_bytes_observed"] is False


def test_http_observer_rejects_request_projection_changed_after_loader_projection() -> None:
    verifier = RunScopedLocomoTransportEvidenceKey.generate(run_id=_RUN_ID)

    with pytest.raises(ValueError, match="differs from expected"):
        observe_mem0_add_request(
            _official_http_request(speaker="Mallory"),
            expected_turn=_expected_turn(),
            verifier=verifier,
        )


def test_recorder_uses_one_verifier_for_two_barrier_released_threads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = Mem0HttpObservationRecorder()
    expected_turn = _expected_turn()
    start_barrier = Barrier(2)
    factory_entered = Event()
    release_factory = Event()
    factory_calls: list[str] = []
    original_generate = RunScopedLocomoTransportEvidenceKey.generate

    def controlled_generate(*, run_id: str) -> RunScopedLocomoTransportEvidenceKey:
        factory_calls.append(run_id)
        factory_entered.set()
        if not release_factory.wait(timeout=5):
            raise TimeoutError("verifier factory release timed out")
        return original_generate(run_id=run_id)

    monkeypatch.setattr(
        RunScopedLocomoTransportEvidenceKey,
        "generate",
        staticmethod(controlled_generate),
    )

    def record_one() -> None:
        request = _official_http_request()
        start_barrier.wait(timeout=3)
        recorder.prepare_request(
            request,
            run_id=_RUN_ID,
            expected_turn=expected_turn,
        )
        recorder.observe_at_transport_boundary(request)
        recorder.record_completed_request(request, run_id=_RUN_ID)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(record_one) for _ in range(2)]
        assert factory_entered.wait(timeout=5)
        release_factory.set()
        for future in futures:
            future.result(timeout=5)

    assert factory_calls == [_RUN_ID]
    verifier = recorder.verifier(run_id=_RUN_ID)
    evidence = recorder.evidence(run_id=_RUN_ID)
    assert verifier is not None
    assert len(evidence) == 2
    assert all(
        verifier.verify(
            item,
            expected_run_id=_RUN_ID,
            expected_corpus_key=_CORPUS_KEY,
        )
        for item in evidence
    )


def test_recorder_rejects_completion_from_generation_reset_while_in_flight() -> None:
    recorder = Mem0HttpObservationRecorder()
    observed = Event()
    release_completion = Event()

    def record_after_release() -> None:
        request = _official_http_request()
        recorder.prepare_request(
            request,
            run_id=_RUN_ID,
            expected_turn=_expected_turn(),
        )
        recorder.observe_at_transport_boundary(request)
        observed.set()
        if not release_completion.wait(timeout=5):
            raise TimeoutError("completion release timed out")
        recorder.record_completed_request(request, run_id=_RUN_ID)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(record_after_release)
        assert observed.wait(timeout=5)
        recorder.reset(run_id=_RUN_ID)
        release_completion.set()
        with pytest.raises(ValueError, match="stale mem0 HTTP transport completion"):
            future.result(timeout=5)

    assert recorder.verifier(run_id=_RUN_ID) is None
    assert recorder.evidence(run_id=_RUN_ID) == ()
    assert recorder.evidence_count(run_id=_RUN_ID) == 0


def test_transport_exception_does_not_record_pretransport_evidence() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("transport failed", request=request)

    backend = Mem0HttpComparisonBackend(
        base_url="http://mem0.test",
        reset_user_on_start=False,
        send_timestamps=True,
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(httpx.ConnectError, match="transport failed"):
            backend.ingest(
                _official_case(),
                run_id=_RUN_ID,
                corpus_key=_CORPUS_KEY,
            )
        assert backend.locomo_timestamp_transport_evidence(run_id=_RUN_ID) == ()
    finally:
        backend.close()

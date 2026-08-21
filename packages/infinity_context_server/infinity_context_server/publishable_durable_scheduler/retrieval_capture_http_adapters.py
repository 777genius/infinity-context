"""Exact scheduler retrieval adapters over the existing benchmark HTTP clients."""

from __future__ import annotations

from typing import final

from infinity_context_server.memory_comparison_http import (
    InfinityContextHttpComparisonBackend,
    Mem0HttpComparisonBackend,
)
from infinity_context_server.memory_comparison_managed_preflight import (
    managed_backend_target_identity_sha256,
)
from infinity_context_server.memory_comparison_models import BackendSearchResult
from infinity_context_server.memory_comparison_retrieval_policy import (
    NEUTRAL_COMPARISON_RETRIEVAL_POLICY,
)
from infinity_context_server.public_benchmark_models import PublicBenchmarkCase
from infinity_context_server.publishable_durable_scheduler.retrieval_capture_contracts import (
    SchedulerBackendRetrievalRequest,
    SchedulerBackendRetrievalResult,
    SchedulerRetrievalCaptureError,
)


@final
class InfinityContextSchedulerRetrievalAdapter:
    """Gold-blind exact retrieval through ``InfinityContextHttpComparisonBackend``."""

    __slots__ = ("_backend", "_target")

    def __init__(self, backend: InfinityContextHttpComparisonBackend) -> None:
        if type(backend) is not InfinityContextHttpComparisonBackend:
            _fail("scheduler_infinity_retrieval_adapter_invalid")
        try:
            valid_policy = (
                backend._retrieval_policy is NEUTRAL_COMPARISON_RETRIEVAL_POLICY
                and backend._use_benchmark_search is True
                and backend._mirror_memories_as_documents is False
            )
            target = _client_target(backend, role="infinity-context")
        except Exception:
            _fail("scheduler_infinity_retrieval_adapter_invalid")
        if not valid_policy:
            _fail("scheduler_infinity_retrieval_adapter_invalid")
        self._backend = backend
        self._target = target

    @property
    def backend_role(self) -> str:
        return "infinity-context"

    @property
    def target_identity_sha256(self) -> str:
        self._verify_binding()
        return self._target

    def retrieve_exact(
        self, *, request: SchedulerBackendRetrievalRequest
    ) -> SchedulerBackendRetrievalResult:
        self._require_request(request, backend_index=0)
        case = gold_blind_retrieval_case(request)
        try:
            result = self._backend.search(
                case,
                run_id=request.case_key.run_id,
                top_k=request.retrieval_limit,
            )
        except Exception:
            _fail("scheduler_infinity_retrieval_failed")
        return _bound_result(result, request)

    def _require_request(self, request: object, *, backend_index: int) -> None:
        self._verify_binding()
        if (
            type(request) is not SchedulerBackendRetrievalRequest
            or request.backend_index != backend_index
            or request.backend_role != self.backend_role
            or request.target_identity_sha256 != self._target
        ):
            _fail("scheduler_infinity_retrieval_request_invalid")

    def _verify_binding(self) -> None:
        try:
            valid = (
                type(self._backend) is InfinityContextHttpComparisonBackend
                and self._backend._retrieval_policy is NEUTRAL_COMPARISON_RETRIEVAL_POLICY
                and self._backend._use_benchmark_search is True
                and self._backend._mirror_memories_as_documents is False
                and _client_target(self._backend, role=self.backend_role) == self._target
            )
        except Exception:
            valid = False
        if not valid:
            _fail("scheduler_infinity_retrieval_adapter_cross_wire")

    def __repr__(self) -> str:
        return "InfinityContextSchedulerRetrievalAdapter(<target-bound>)"


@final
class Mem0SchedulerRetrievalAdapter:
    """Gold-blind exact retrieval through ``Mem0HttpComparisonBackend``."""

    __slots__ = ("_backend", "_target")

    def __init__(self, backend: Mem0HttpComparisonBackend) -> None:
        if type(backend) is not Mem0HttpComparisonBackend:
            _fail("scheduler_mem0_retrieval_adapter_invalid")
        try:
            target = _client_target(backend, role="mem0")
        except Exception:
            _fail("scheduler_mem0_retrieval_adapter_invalid")
        self._backend = backend
        self._target = target

    @property
    def backend_role(self) -> str:
        return "mem0"

    @property
    def target_identity_sha256(self) -> str:
        self._verify_binding()
        return self._target

    def retrieve_exact(
        self, *, request: SchedulerBackendRetrievalRequest
    ) -> SchedulerBackendRetrievalResult:
        self._require_request(request, backend_index=1)
        case = gold_blind_retrieval_case(request)
        try:
            result = self._backend.search(
                case,
                run_id=request.case_key.run_id,
                top_k=request.retrieval_limit,
            )
        except Exception:
            _fail("scheduler_mem0_retrieval_failed")
        return _bound_result(result, request)

    def _require_request(self, request: object, *, backend_index: int) -> None:
        self._verify_binding()
        if (
            type(request) is not SchedulerBackendRetrievalRequest
            or request.backend_index != backend_index
            or request.backend_role != self.backend_role
            or request.target_identity_sha256 != self._target
        ):
            _fail("scheduler_mem0_retrieval_request_invalid")

    def _verify_binding(self) -> None:
        try:
            valid = (
                type(self._backend) is Mem0HttpComparisonBackend
                and _client_target(self._backend, role=self.backend_role) == self._target
            )
        except Exception:
            valid = False
        if not valid:
            _fail("scheduler_mem0_retrieval_adapter_cross_wire")

    def __repr__(self) -> str:
        return "Mem0SchedulerRetrievalAdapter(<target-bound>)"


def gold_blind_retrieval_case(
    request: SchedulerBackendRetrievalRequest,
) -> PublicBenchmarkCase:
    """Project only fields required by the two existing exact search calls."""

    if type(request) is not SchedulerBackendRetrievalRequest:
        _fail("scheduler_backend_retrieval_request_invalid")
    return PublicBenchmarkCase(
        benchmark=request.case_key.benchmark.value,
        case_id=request.case_key.case_id,
        question=request.question,
        expected_terms=(),
        forbidden_terms=(),
        memory_scope_external_ref=request.memory_scope_external_ref,
        thread_external_ref=request.thread_external_ref,
        metadata={},
    )


def _bound_result(
    result: object,
    request: SchedulerBackendRetrievalRequest,
) -> SchedulerBackendRetrievalResult:
    if (
        type(result) is not BackendSearchResult
        or result.query != request.question
        or type(result.memories) is not tuple
        or len(result.memories) > request.retrieval_limit
    ):
        _fail("scheduler_backend_retrieval_response_invalid")
    try:
        return SchedulerBackendRetrievalResult.bind(
            request=request,
            memories=result.memories,
        )
    except SchedulerRetrievalCaptureError:
        raise
    except Exception:
        _fail("scheduler_backend_retrieval_response_invalid")


def _client_target(
    backend: InfinityContextHttpComparisonBackend | Mem0HttpComparisonBackend,
    *,
    role: str,
) -> str:
    client = backend._client
    return managed_backend_target_identity_sha256(
        backend_role=role,
        base_url=str(client.base_url),
    )


def _fail(code: str) -> None:
    raise SchedulerRetrievalCaptureError(code)


__all__ = (
    "InfinityContextSchedulerRetrievalAdapter",
    "Mem0SchedulerRetrievalAdapter",
    "gold_blind_retrieval_case",
)

"""Infinity-only managed HTTP execution and retrieval delegate."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import final

import httpx

from infinity_context_server.memory_comparison_full_profiles import INFINITY_COMPARISON_BACKEND
from infinity_context_server.memory_comparison_gold_blind_answer_contract import (
    GoldBlindEvidence,
    gold_blind_evidence_identity,
)
from infinity_context_server.memory_comparison_http import InfinityContextHttpComparisonBackend
from infinity_context_server.memory_comparison_managed_corpus_projection import (
    _reconstruct_managed_corpus_case,
)
from infinity_context_server.memory_comparison_managed_preflight import (
    managed_backend_target_identity_sha256,
)
from infinity_context_server.memory_comparison_managed_retrieval_port import (
    ManagedRetrievalAuthority,
    ManagedRetrievalResult,
    _issue_managed_retrieval_authority,
    _validate_managed_retrieval_authority,
)
from infinity_context_server.memory_comparison_managed_run_contract import (
    ManagedAnswerCase,
    ManagedRunCase,
)
from infinity_context_server.memory_comparison_managed_runner_binding import (
    ManagedRunnerCompositionBinding,
)
from infinity_context_server.memory_comparison_models import (
    BackendIngestResult,
    BackendSearchResult,
    RetrievedMemory,
)
from infinity_context_server.memory_comparison_retrieval_policy import (
    NEUTRAL_COMPARISON_RETRIEVAL_POLICY,
)
from infinity_context_server.public_benchmark_models import PublicBenchmarkCase

MANAGED_INFINITY_HTTP_EXECUTION_ADAPTER_ID = "managed-infinity-http-neutral-v1"
_INGEST_QUESTION = "managed-ingest-gold-blind-projection"


class ManagedInfinityHttpExecutionError(RuntimeError):
    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@final
@dataclass(frozen=True, slots=True)
class ManagedInfinityHttpRuntimeConfig:
    target_identity_sha256: str
    base_url: str
    auth_token: str = field(repr=False)
    timeout_seconds: float = 60.0
    transport: httpx.BaseTransport | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        try:
            expected = managed_backend_target_identity_sha256(
                backend_role=INFINITY_COMPARISON_BACKEND,
                base_url=self.base_url,
            )
        except Exception:
            _fail("managed_infinity_http_config_invalid")
        if (
            expected != self.target_identity_sha256
            or type(self.auth_token) is not str
            or not self.auth_token
            or type(self.timeout_seconds) not in {int, float}
            or not math.isfinite(float(self.timeout_seconds))
            or float(self.timeout_seconds) <= 0
            or (self.transport is not None and not isinstance(self.transport, httpx.BaseTransport))
        ):
            _fail("managed_infinity_http_config_invalid")


@final
class ManagedInfinityHttpExecutionAdapter:
    """Own only Infinity ingest/retrieval I/O; construction performs no request."""

    __slots__ = ("_backend", "_binding", "_clock", "_closed", "_target")

    def __init__(
        self,
        *,
        composition_binding: ManagedRunnerCompositionBinding,
        config: ManagedInfinityHttpRuntimeConfig,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if (
            type(composition_binding) is not ManagedRunnerCompositionBinding
            or type(config) is not ManagedInfinityHttpRuntimeConfig
            or not callable(clock)
        ):
            _fail("managed_infinity_http_composition_invalid")
        targets = tuple(
            item.target_identity_sha256
            for item in composition_binding.backend_targets
            if item.backend_role == INFINITY_COMPARISON_BACKEND
        )
        if len(targets) != 1 or targets[0] != config.target_identity_sha256:
            _fail("managed_infinity_http_composition_invalid")
        self._binding = composition_binding
        self._target = targets[0]
        self._clock = clock
        self._closed = False
        self._backend = InfinityContextHttpComparisonBackend(
            base_url=config.base_url,
            auth_token=config.auth_token,
            timeout_seconds=float(config.timeout_seconds),
            retrieval_policy=NEUTRAL_COMPARISON_RETRIEVAL_POLICY,
            mirror_memories_as_documents=False,
            transport=config.transport,
        )

    @property
    def composition_binding(self) -> ManagedRunnerCompositionBinding:
        self._ensure_live()
        return self._binding

    @property
    def adapter_id(self) -> str:
        return MANAGED_INFINITY_HTTP_EXECUTION_ADAPTER_ID

    @property
    def implementation_sha256(self) -> str:
        return managed_infinity_http_execution_implementation_sha256()

    def ingest(self, *, case: ManagedRunCase) -> BackendIngestResult:
        self._ensure_live()
        if type(case) is not ManagedRunCase:
            _fail("managed_infinity_http_ingest_invalid")
        rebuilt = _reconstruct_managed_corpus_case(
            case.record, case_id=case.case_id, question=_INGEST_QUESTION, temporal_context={}
        )
        _validate_gold_free(rebuilt, self._binding.profile.benchmark, _INGEST_QUESTION)
        try:
            result = self._backend.ingest(
                rebuilt, run_id=self._binding.run_id, corpus_key=case.corpus_id
            )
        except Exception:
            _fail("managed_infinity_http_ingest_failed")
        if type(result) is not BackendIngestResult:
            _fail("managed_infinity_http_ingest_result_invalid")
        return result

    def authority_for(
        self, *, backend_role: str, target_identity_sha256: str
    ) -> ManagedRetrievalAuthority:
        self._ensure_live()
        self._require_target(backend_role, target_identity_sha256)
        return _issue_managed_retrieval_authority(
            self._binding,
            backend_role=backend_role,
            target_identity_sha256=target_identity_sha256,
        )

    def retrieve(
        self,
        *,
        authority: ManagedRetrievalAuthority,
        case: ManagedRunCase,
        query: ManagedAnswerCase,
    ) -> ManagedRetrievalResult:
        self._ensure_live()
        try:
            pair = _validate_managed_retrieval_authority(
                authority, composition_binding=self._binding
            )
        except Exception:
            _fail("managed_infinity_http_retrieval_authority_invalid")
        self._require_target(*pair)
        if (
            type(case) is not ManagedRunCase
            or type(query) is not ManagedAnswerCase
            or case.case_id != query.case_id
        ):
            _fail("managed_infinity_http_retrieval_request_invalid")
        rebuilt = _reconstruct_managed_corpus_case(case.record, query)
        _validate_gold_free(rebuilt, self._binding.profile.benchmark, query.question)
        try:
            result = self._backend.search(
                rebuilt,
                run_id=self._binding.run_id,
                top_k=self._binding.retrieval_top_k,
            )
        except Exception:
            _fail("managed_infinity_http_retrieval_failed")
        if type(result) is not BackendSearchResult:
            _fail("managed_infinity_http_retrieval_result_invalid")
        evidence = _gold_blind(result.memories, cutoff=self._binding.answer_cutoff)
        return ManagedRetrievalResult(
            evidence=evidence,
            retrieval_identity=gold_blind_evidence_identity(evidence),
            metadata={
                "adapter_id": self.adapter_id,
                "implementation_sha256": self.implementation_sha256,
                "backend_role": INFINITY_COMPARISON_BACKEND,
                "target_identity_sha256": self._target,
                "retrieval_top_k": self._binding.retrieval_top_k,
                "answer_cutoff": self._binding.answer_cutoff,
                "retrieval_policy": NEUTRAL_COMPARISON_RETRIEVAL_POLICY.telemetry(),
                "gold_fields_forwarded": False,
                "retries": 0,
                "latency_ms": result.latency_ms,
                "total_results": result.total_results,
                "context_token_count": result.context_token_count,
            },
        )

    def close(self) -> None:
        self._ensure_live()
        self._closed = True
        try:
            self._backend.close()
        except Exception:
            _fail("managed_infinity_http_close_failed")

    def _require_target(self, backend_role: object, target: object) -> None:
        if backend_role != INFINITY_COMPARISON_BACKEND or target != self._target:
            _fail("managed_infinity_http_target_invalid")

    def _ensure_live(self) -> None:
        if self._closed:
            _fail("managed_infinity_http_closed")
        try:
            now = self._clock()
        except Exception:
            _fail("managed_infinity_http_clock_invalid")
        if (
            type(now) is not datetime
            or now.tzinfo is None
            or now.utcoffset() is None
            or now >= self._binding.deadline
        ):
            _fail("managed_infinity_http_deadline_expired")


def _gold_blind(
    memories: tuple[RetrievedMemory, ...], *, cutoff: int
) -> tuple[GoldBlindEvidence, ...]:
    if type(memories) is not tuple or any(type(item) is not RetrievedMemory for item in memories):
        _fail("managed_infinity_http_retrieval_result_invalid")
    return tuple(
        GoldBlindEvidence(
            item_id=item.item_id or f"retrieved-item-{rank:04d}",
            text=item.text,
            rank=rank,
            created_at=item.created_at,
        )
        for rank, item in enumerate(memories[:cutoff], start=1)
    )


def _validate_gold_free(case: PublicBenchmarkCase, benchmark: str, question: str) -> None:
    if (
        type(case) is not PublicBenchmarkCase
        or case.benchmark != benchmark
        or case.question != question
        or case.expected_terms != ()
        or case.forbidden_terms != ()
        or "_evaluator_ground_truth" in case.metadata
    ):
        _fail("managed_infinity_http_projection_invalid")


def managed_infinity_http_execution_implementation_sha256() -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "adapter_id": MANAGED_INFINITY_HTTP_EXECUTION_ADAPTER_ID,
                "backend": INFINITY_COMPARISON_BACKEND,
                "constructor_io": False,
                "fallback": False,
                "retrieval_policy": NEUTRAL_COMPARISON_RETRIEVAL_POLICY.policy_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _fail(code: str) -> None:
    raise ManagedInfinityHttpExecutionError(code)


__all__ = (
    "MANAGED_INFINITY_HTTP_EXECUTION_ADAPTER_ID",
    "ManagedInfinityHttpExecutionAdapter",
    "ManagedInfinityHttpExecutionError",
    "ManagedInfinityHttpRuntimeConfig",
    "managed_infinity_http_execution_implementation_sha256",
)

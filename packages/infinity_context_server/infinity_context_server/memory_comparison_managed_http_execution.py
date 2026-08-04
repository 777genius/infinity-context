"""Deadline-bound neutral HTTP ingest and retrieval for managed comparisons."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from types import MappingProxyType
from typing import final

import httpx

from infinity_context_server.memory_comparison_backend_target import (
    FullComparisonBackendTarget,
)
from infinity_context_server.memory_comparison_full_profiles import (
    INFINITY_COMPARISON_BACKEND,
    REQUIRED_FULL_COMPARISON_BACKENDS,
    frozen_full_comparison_profile,
)
from infinity_context_server.memory_comparison_gold_blind_answer_contract import (
    GoldBlindEvidence,
    gold_blind_evidence_identity,
)
from infinity_context_server.memory_comparison_http import (
    InfinityContextHttpComparisonBackend,
    Mem0HttpComparisonBackend,
)
from infinity_context_server.memory_comparison_locomo_transport import (
    LocomoTimestampTransportEvidence,
    RunScopedLocomoTransportEvidenceKey,
)
from infinity_context_server.memory_comparison_managed_corpus_projection import (
    _reconstruct_managed_corpus_case,
)
from infinity_context_server.memory_comparison_managed_mem0_auth import (
    MANAGED_MEM0_DATA_PLANE_AUTH_API_KEY,
    MANAGED_MEM0_DATA_PLANE_AUTH_NONE,
    managed_mem0_data_plane_auth_mode,
)
from infinity_context_server.memory_comparison_managed_preflight import (
    ManagedPreflightRequest,
    managed_backend_target_identity_sha256,
    validate_managed_preflight,
)
from infinity_context_server.memory_comparison_managed_run_contract import (
    ManagedAnswerCase,
    ManagedRunCase,
)
from infinity_context_server.memory_comparison_models import (
    BackendIngestResult,
    BackendSearchResult,
    RetrievedMemory,
)
from infinity_context_server.memory_comparison_retrieval_policy import (
    NEUTRAL_COMPARISON_RETRIEVAL_POLICY,
    ComparisonRetrievalPolicy,
)
from infinity_context_server.public_benchmark_models import PublicBenchmarkCase

MANAGED_HTTP_EXECUTION_ADAPTER_ID = "managed-comparison-http-neutral-v1"
_MANAGED_INGEST_QUESTION = "managed-ingest-gold-blind-projection"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")


class ManagedHttpExecutionError(RuntimeError):
    """Raised before unsafe or out-of-contract managed HTTP I/O."""


@dataclass(frozen=True, slots=True)
class ManagedInfinityHttpConfig:
    target_identity_sha256: str
    base_url: str
    auth_token: str = field(repr=False)
    timeout_seconds: float
    transport: httpx.BaseTransport | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        _validate_config(
            backend_role=INFINITY_COMPARISON_BACKEND,
            target_identity_sha256=self.target_identity_sha256,
            base_url=self.base_url,
            credential=self.auth_token,
            timeout_seconds=self.timeout_seconds,
            transport=self.transport,
        )


@dataclass(frozen=True, slots=True)
class ManagedMem0HttpConfig:
    target_identity_sha256: str
    base_url: str
    api_key: str | None = field(default=None, repr=False)
    ingress_api_key: str | None = field(default=None, repr=False)
    data_plane_auth_mode: str = MANAGED_MEM0_DATA_PLANE_AUTH_API_KEY
    timeout_seconds: float = 60.0
    send_timestamps: bool = False
    transport: httpx.BaseTransport | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        try:
            auth_mode = managed_mem0_data_plane_auth_mode(self.data_plane_auth_mode)
        except ValueError:
            raise ManagedHttpExecutionError(
                "managed HTTP Mem0 data-plane auth mode is invalid"
            ) from None
        if auth_mode == MANAGED_MEM0_DATA_PLANE_AUTH_NONE:
            if self.api_key is not None:
                raise ManagedHttpExecutionError(
                    "managed HTTP keyless Mem0 config must not carry a provider API key"
                )
        elif self.ingress_api_key is not None:
            raise ManagedHttpExecutionError(
                "managed HTTP Platform Mem0 config must not carry an OSS ingress key"
            )
        effective_credential = (
            self.api_key
            if auth_mode == MANAGED_MEM0_DATA_PLANE_AUTH_API_KEY
            else self.ingress_api_key
        )
        _validate_config(
            backend_role="mem0",
            target_identity_sha256=self.target_identity_sha256,
            base_url=self.base_url,
            credential=effective_credential,
            timeout_seconds=self.timeout_seconds,
            transport=self.transport,
            credential_optional=auth_mode == MANAGED_MEM0_DATA_PLANE_AUTH_NONE,
        )
        if type(self.send_timestamps) is not bool:
            raise ManagedHttpExecutionError("Mem0 timestamp mode must be an exact boolean")


@final
@dataclass(frozen=True, slots=True)
class ManagedHttpRetrievalResult:
    evidence: tuple[GoldBlindEvidence, ...]
    retrieval_identity: str
    metadata: Mapping[str, object]

    def __post_init__(self) -> None:
        if type(self.evidence) is not tuple or any(
            type(item) is not GoldBlindEvidence for item in self.evidence
        ):
            raise ManagedHttpExecutionError("retrieval evidence must be an exact typed tuple")
        if (
            type(self.retrieval_identity) is not str
            or _SHA256.fullmatch(self.retrieval_identity) is None
            or self.retrieval_identity != gold_blind_evidence_identity(self.evidence)
        ):
            raise ManagedHttpExecutionError("retrieval identity differs from the evidence")
        if type(self.metadata) not in {dict, MappingProxyType}:
            raise ManagedHttpExecutionError("retrieval metadata must be an exact frozen mapping")
        object.__setattr__(self, "metadata", _freeze_json(dict(self.metadata)))

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedHttpRetrievalResult is final")


@final
class ManagedComparisonHttpExecutionAdapter:
    """Own exact admitted HTTP targets, without answer, judge, or delete authority."""

    def __init__(
        self,
        *,
        preflight_request: ManagedPreflightRequest,
        run_id: str,
        deadline: datetime,
        credential_material: object,
        retrieval_policy: ComparisonRetrievalPolicy,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if type(preflight_request) is not ManagedPreflightRequest:
            raise ManagedHttpExecutionError("managed HTTP preflight request type is invalid")
        try:
            preflight = validate_managed_preflight(preflight_request)
            trusted_profile = frozen_full_comparison_profile(preflight_request.profile)
        except Exception:
            raise ManagedHttpExecutionError("managed HTTP preflight request is invalid") from None
        trusted_run_id = _identifier(run_id, "managed HTTP admitted run_id")
        _validate_neutral_policy(retrieval_policy)
        if not callable(clock):
            raise ManagedHttpExecutionError("managed HTTP clock must be callable")
        trusted_deadline = _aware_instant(deadline, "managed HTTP deadline")
        now = _aware_instant(clock(), "managed HTTP current time")
        if now >= trusted_deadline:
            raise ManagedHttpExecutionError("managed HTTP deadline is expired")

        admitted_targets = tuple(item.target for item in preflight.backend_endpoints)
        target_map = _admitted_target_map(admitted_targets)
        from infinity_context_server import (  # noqa: PLC0415
            memory_comparison_managed_runtime_credentials_capability as credential_capability,
        )

        if type(credential_material) is not credential_capability.ManagedBackendCredentialMaterial:
            raise ManagedHttpExecutionError(
                "managed HTTP credential material must use the exact sealed type"
            )
        try:
            infinity, mem0 = credential_material.consume_for_http_execution(
                expected_request=preflight_request,
                run_id=trusted_run_id,
                deadline=trusted_deadline,
            )
        except (TypeError, ValueError):
            raise ManagedHttpExecutionError("managed HTTP credential continuity failed") from None
        if (
            type(infinity) is not ManagedInfinityHttpConfig
            or type(mem0) is not ManagedMem0HttpConfig
        ):
            raise ManagedHttpExecutionError("managed HTTP credential configs are invalid")
        if mem0.data_plane_auth_mode != preflight.mem0_data_plane_auth_mode:
            raise ManagedHttpExecutionError(
                "managed HTTP Mem0 data-plane auth differs from preflight"
            )
        configured = {
            INFINITY_COMPARISON_BACKEND: infinity.target_identity_sha256,
            "mem0": mem0.target_identity_sha256,
        }
        if target_map != configured:
            raise ManagedHttpExecutionError("HTTP configs differ from exact admitted targets")
        provided_transports = tuple(
            item for item in (infinity.transport, mem0.transport) if item is not None
        )
        if len({id(item) for item in provided_transports}) != len(provided_transports):
            raise ManagedHttpExecutionError("HTTP targets cannot share transport ownership")

        self._deadline = trusted_deadline
        self._clock = clock
        self._profile = trusted_profile
        self._run_id = trusted_run_id
        self._targets = target_map
        self._closed = False
        infinity_transport = _deadline_transport(
            infinity.transport,
            configured_timeout_seconds=infinity.timeout_seconds,
            deadline=trusted_deadline,
            clock=clock,
        )
        mem0_transport = _deadline_transport(
            mem0.transport,
            configured_timeout_seconds=mem0.timeout_seconds,
            deadline=trusted_deadline,
            clock=clock,
        )
        self._backends: dict[str, object] = {
            INFINITY_COMPARISON_BACKEND: InfinityContextHttpComparisonBackend(
                base_url=infinity.base_url,
                auth_token=infinity.auth_token,
                timeout_seconds=infinity.timeout_seconds,
                retrieval_policy=NEUTRAL_COMPARISON_RETRIEVAL_POLICY,
                mirror_memories_as_documents=False,
                transport=infinity_transport,
            ),
            "mem0": Mem0HttpComparisonBackend(
                base_url=mem0.base_url,
                api_key=(
                    mem0.api_key
                    if mem0.data_plane_auth_mode == MANAGED_MEM0_DATA_PLANE_AUTH_API_KEY
                    else mem0.ingress_api_key
                ),
                timeout_seconds=mem0.timeout_seconds,
                reset_user_on_start=False,
                send_timestamps=mem0.send_timestamps,
                transport=mem0_transport,
            ),
        }
        for backend in self._backends.values():
            backend.reset(run_id=trusted_run_id)  # type: ignore[attr-defined]

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedComparisonHttpExecutionAdapter is final")

    @property
    def retrieval_top_k(self) -> int:
        return self._profile.retrieval_top_k

    @property
    def answer_cutoff(self) -> int:
        return self._profile.answer_cutoff

    def ingest(
        self,
        *,
        run_id: str,
        backend_role: str,
        target_identity_sha256: str,
        case: ManagedRunCase,
    ) -> BackendIngestResult:
        self._validate_run_id(run_id)
        backend = self._select_backend(
            backend_role=backend_role,
            target_identity_sha256=target_identity_sha256,
        )
        if type(case) is not ManagedRunCase:
            raise ManagedHttpExecutionError("managed ingest case type is invalid")
        rebuilt = _reconstruct_managed_corpus_case(
            case.record,
            case_id=case.case_id,
            question=_MANAGED_INGEST_QUESTION,
            temporal_context={},
        )
        _validate_gold_free_case(
            rebuilt,
            expected_benchmark=self._profile.benchmark,
            expected_question=_MANAGED_INGEST_QUESTION,
        )
        result = backend.ingest(rebuilt, run_id=run_id, corpus_key=case.corpus_id)  # type: ignore[attr-defined]
        if type(result) is not BackendIngestResult:
            raise ManagedHttpExecutionError("managed HTTP ingest result type is invalid")
        return replace(
            result,
            metadata={
                **dict(result.metadata),
                "managed_http_execution": {
                    "adapter_id": MANAGED_HTTP_EXECUTION_ADAPTER_ID,
                    "composition_blockers": [],
                    "credential_continuity_proven": True,
                    "question_forwarded": False,
                    "gold_fields_forwarded": False,
                    "retries": 0,
                },
            },
        )

    def retrieve(
        self,
        *,
        run_id: str,
        backend_role: str,
        target_identity_sha256: str,
        case: ManagedRunCase,
        query: ManagedAnswerCase,
    ) -> ManagedHttpRetrievalResult:
        self._validate_run_id(run_id)
        backend = self._select_backend(
            backend_role=backend_role,
            target_identity_sha256=target_identity_sha256,
        )
        if type(case) is not ManagedRunCase or type(query) is not ManagedAnswerCase:
            raise ManagedHttpExecutionError("managed retrieval case types are invalid")
        if case.case_id != query.case_id:
            raise ManagedHttpExecutionError("managed retrieval case binding differs")
        rebuilt = _reconstruct_managed_corpus_case(case.record, query)
        _validate_gold_free_case(
            rebuilt,
            expected_benchmark=self._profile.benchmark,
            expected_question=query.question,
        )
        search = backend.search(  # type: ignore[attr-defined]
            rebuilt,
            run_id=run_id,
            top_k=self._profile.retrieval_top_k,
        )
        if type(search) is not BackendSearchResult:
            raise ManagedHttpExecutionError("managed HTTP search result type is invalid")
        evidence = _gold_blind_evidence(
            search.memories,
            cutoff=self._profile.answer_cutoff,
        )
        metadata = {
            "adapter_id": MANAGED_HTTP_EXECUTION_ADAPTER_ID,
            "composition_blockers": [],
            "credential_continuity_proven": True,
            "backend_role": backend_role,
            "target_identity_sha256": target_identity_sha256,
            "retrieval_top_k": self._profile.retrieval_top_k,
            "answer_cutoff": self._profile.answer_cutoff,
            "retrieval_policy": NEUTRAL_COMPARISON_RETRIEVAL_POLICY.telemetry(),
            "question_forwarded_only_to_retrieval": True,
            "gold_fields_forwarded": False,
            "retries": 0,
            "latency_ms": search.latency_ms,
            "total_results": search.total_results,
            "context_token_count": search.context_token_count,
            "backend": dict(search.metadata),
        }
        identity = gold_blind_evidence_identity(evidence)
        return ManagedHttpRetrievalResult(evidence, identity, metadata)

    def locomo_timestamp_transport_verifier(
        self,
        *,
        run_id: str,
        target_identity_sha256: str,
    ) -> RunScopedLocomoTransportEvidenceKey | None:
        self._validate_run_id(run_id)
        backend = self._select_backend(
            backend_role="mem0",
            target_identity_sha256=target_identity_sha256,
        )
        verifier = backend.locomo_timestamp_transport_verifier(run_id=run_id)  # type: ignore[attr-defined]
        if verifier is not None and type(verifier) is not RunScopedLocomoTransportEvidenceKey:
            raise ManagedHttpExecutionError("managed Mem0 verifier type is invalid")
        return verifier

    def locomo_timestamp_transport_evidence(
        self,
        *,
        run_id: str,
        target_identity_sha256: str,
    ) -> tuple[LocomoTimestampTransportEvidence, ...]:
        self._validate_run_id(run_id)
        backend = self._select_backend(
            backend_role="mem0",
            target_identity_sha256=target_identity_sha256,
        )
        evidence = backend.locomo_timestamp_transport_evidence(  # type: ignore[attr-defined]
            run_id=run_id
        )
        if type(evidence) is not tuple or any(
            type(item) is not LocomoTimestampTransportEvidence for item in evidence
        ):
            raise ManagedHttpExecutionError("managed Mem0 transport evidence type is invalid")
        return evidence

    def close(self) -> None:
        if self._closed:
            raise ManagedHttpExecutionError("managed HTTP execution is already closed")
        self._closed = True
        errors: list[BaseException] = []
        for role in REQUIRED_FULL_COMPARISON_BACKENDS:
            try:
                self._backends[role].close()  # type: ignore[attr-defined]
            except BaseException as exc:
                errors.append(exc)
        if errors:
            raise ManagedHttpExecutionError("managed HTTP terminal close failed") from errors[0]

    def _validate_run_id(self, run_id: object) -> None:
        trusted = _identifier(run_id, "managed HTTP run_id")
        if trusted != self._run_id:
            raise ManagedHttpExecutionError("managed HTTP run differs from exact admission")

    def _select_backend(self, *, backend_role: str, target_identity_sha256: str) -> object:
        self._ensure_live()
        _identifier(backend_role, "managed HTTP backend role")
        _digest(target_identity_sha256, "managed HTTP target identity")
        admitted = self._targets.get(backend_role)
        if admitted is None or admitted != target_identity_sha256:
            raise ManagedHttpExecutionError("managed HTTP target is not exactly admitted")
        return self._backends[backend_role]

    def _ensure_live(self) -> None:
        if self._closed:
            raise ManagedHttpExecutionError("managed HTTP execution is closed")
        _validate_neutral_policy(NEUTRAL_COMPARISON_RETRIEVAL_POLICY)
        now = _aware_instant(self._clock(), "managed HTTP current time")
        if now >= self._deadline:
            raise ManagedHttpExecutionError("managed HTTP deadline is expired")


class _DeadlineBoundTransport(httpx.BaseTransport):
    def __init__(
        self,
        inner: httpx.BaseTransport,
        *,
        configured_timeout_seconds: float,
        deadline: datetime,
        clock: Callable[[], datetime],
    ) -> None:
        self._inner = inner
        self._configured_timeout_seconds = configured_timeout_seconds
        self._deadline = deadline
        self._clock = clock
        self._closed = False

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if self._closed:
            raise ManagedHttpExecutionError("managed HTTP transport is closed")
        now = _aware_instant(self._clock(), "managed HTTP I/O current time")
        remaining = (self._deadline - now).total_seconds()
        if not math.isfinite(remaining) or remaining <= 0:
            raise ManagedHttpExecutionError("managed HTTP deadline expired before I/O")
        timeout = min(self._configured_timeout_seconds, remaining)
        request.extensions["timeout"] = {
            "connect": timeout,
            "read": timeout,
            "write": timeout,
            "pool": timeout,
        }
        return self._inner.handle_request(request)

    def close(self) -> None:
        if self._closed:
            raise ManagedHttpExecutionError("managed HTTP transport closed more than once")
        self._closed = True
        self._inner.close()


def _validate_neutral_policy(policy: object) -> None:
    if (
        type(policy) is not ComparisonRetrievalPolicy
        or policy is not NEUTRAL_COMPARISON_RETRIEVAL_POLICY
        or policy.policy_id != "neutral-retrieval-v1"
        or policy.single_pass_retrieval is not True
        or policy.mirror_memories_as_documents is not False
        or policy.apply_candidate_fusion is not False
        or policy.apply_temporal_rerank is not False
        or policy.apply_benchmark_rerank is not False
        or policy.publication_lane != "neutral_head_to_head"
    ):
        raise ManagedHttpExecutionError("managed HTTP execution requires neutral-retrieval-v1")


def _deadline_transport(
    transport: httpx.BaseTransport | None,
    *,
    configured_timeout_seconds: float,
    deadline: datetime,
    clock: Callable[[], datetime],
) -> _DeadlineBoundTransport:
    inner = transport or httpx.HTTPTransport(retries=0, trust_env=False)
    return _DeadlineBoundTransport(
        inner,
        configured_timeout_seconds=configured_timeout_seconds,
        deadline=deadline,
        clock=clock,
    )


def _gold_blind_evidence(
    memories: tuple[RetrievedMemory, ...],
    *,
    cutoff: int,
) -> tuple[GoldBlindEvidence, ...]:
    if type(memories) is not tuple or any(type(item) is not RetrievedMemory for item in memories):
        raise ManagedHttpExecutionError("retrieved memories must be an exact typed tuple")
    evidence: list[GoldBlindEvidence] = []
    for rank, memory in enumerate(memories[:cutoff], start=1):
        item_id = memory.item_id or f"retrieved-item-{rank:04d}"
        evidence.append(
            GoldBlindEvidence(
                item_id=item_id,
                text=memory.text,
                rank=rank,
                created_at=memory.created_at,
            )
        )
    return tuple(evidence)


def _validate_gold_free_case(
    case: PublicBenchmarkCase,
    *,
    expected_benchmark: str,
    expected_question: str,
) -> None:
    if (
        type(case) is not PublicBenchmarkCase
        or case.benchmark != expected_benchmark
        or case.question != expected_question
        or case.expected_terms != ()
        or case.forbidden_terms != ()
        or "_evaluator_ground_truth" in case.metadata
    ):
        raise ManagedHttpExecutionError("managed HTTP reconstruction is not gold-free")


def _admitted_target_map(
    targets: tuple[FullComparisonBackendTarget, ...],
) -> dict[str, str]:
    if tuple(item.backend_role for item in targets) != REQUIRED_FULL_COMPARISON_BACKENDS:
        raise ManagedHttpExecutionError("managed HTTP admitted backend order is invalid")
    result = {item.backend_role: item.target_identity_sha256 for item in targets}
    if len(result) != len(REQUIRED_FULL_COMPARISON_BACKENDS):
        raise ManagedHttpExecutionError("managed HTTP admitted backend targets are duplicated")
    return result


def _validate_config(
    *,
    backend_role: str,
    target_identity_sha256: object,
    base_url: object,
    credential: object,
    timeout_seconds: object,
    transport: object,
    credential_optional: bool = False,
) -> None:
    _digest(target_identity_sha256, "managed HTTP config target identity")
    if type(base_url) is not str or not base_url or base_url != base_url.strip():
        raise ManagedHttpExecutionError("managed HTTP base URL is invalid")
    try:
        expected_target = managed_backend_target_identity_sha256(
            backend_role=backend_role,
            base_url=base_url,
        )
    except Exception:
        raise ManagedHttpExecutionError("managed HTTP base URL is invalid") from None
    if expected_target != target_identity_sha256:
        raise ManagedHttpExecutionError("managed HTTP target identity differs from base URL")
    if not credential_optional and (type(credential) is not str or not credential):
        raise ManagedHttpExecutionError("managed HTTP credential is invalid")
    if (
        credential_optional
        and credential is not None
        and (type(credential) is not str or not credential)
    ):
        raise ManagedHttpExecutionError("managed HTTP credential is invalid")
    if (
        type(timeout_seconds) not in {int, float}
        or isinstance(timeout_seconds, bool)
        or not math.isfinite(float(timeout_seconds))
        or float(timeout_seconds) <= 0
    ):
        raise ManagedHttpExecutionError("managed HTTP timeout is invalid")
    if transport is not None and type(transport) is not httpx.MockTransport:
        raise ManagedHttpExecutionError("only exact MockTransport is accepted as a test seam")


def _identifier(value: object, name: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise ManagedHttpExecutionError(f"{name} is invalid")
    return value


def _digest(value: object, name: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise ManagedHttpExecutionError(f"{name} is invalid")
    return value


def _aware_instant(value: object, name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ManagedHttpExecutionError(f"{name} must be an aware datetime")
    return value


def _freeze_json(value: object, *, depth: int = 0) -> object:
    if depth > 12:
        raise ManagedHttpExecutionError("retrieval metadata nesting is invalid")
    if value is None or type(value) in {str, bool, int}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ManagedHttpExecutionError("retrieval metadata number is invalid")
        return value
    if type(value) is list or type(value) is tuple:
        return tuple(_freeze_json(item, depth=depth + 1) for item in value)
    if type(value) in {dict, MappingProxyType}:
        if any(type(key) is not str for key in value):
            raise ManagedHttpExecutionError("retrieval metadata key is invalid")
        return MappingProxyType(
            {key: _freeze_json(item, depth=depth + 1) for key, item in value.items()}
        )
    raise ManagedHttpExecutionError("retrieval metadata must be exact JSON")


def managed_http_execution_implementation_sha256() -> str:
    """Stable semantic adapter identity without credentials or target details."""

    material = {
        "adapter_id": MANAGED_HTTP_EXECUTION_ADAPTER_ID,
        "answer_cutoff_source": "frozen_full_comparison_profile",
        "deadline_policy": "min-configured-and-remaining-per-io",
        "credential_continuity": "opaque-authority-consumed-before-http-io",
        "retries": 0,
        "retrieval_policy": NEUTRAL_COMPARISON_RETRIEVAL_POLICY.policy_id,
        "retrieval_top_k_source": "frozen_full_comparison_profile",
    }
    return hashlib.sha256(
        json.dumps(material, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


__all__ = (
    "MANAGED_HTTP_EXECUTION_ADAPTER_ID",
    "ManagedComparisonHttpExecutionAdapter",
    "ManagedHttpExecutionError",
    "ManagedHttpRetrievalResult",
    "ManagedInfinityHttpConfig",
    "ManagedMem0HttpConfig",
    "managed_http_execution_implementation_sha256",
)

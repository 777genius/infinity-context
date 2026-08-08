"""Infinity-only reset/ingest lifecycle for managed v5 cutover components."""

from __future__ import annotations

import hashlib
import json
import secrets
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import NoReturn, final

import httpx

from infinity_context_server.memory_comparison_clean_state import clean_state_identity_sha256
from infinity_context_server.memory_comparison_full_execution_evidence_variants import (
    issue_infinity_di_full_execution_clean_state_evidence,
)
from infinity_context_server.memory_comparison_full_execution_validation_slots import (
    FullExecutionCleanScope,
)
from infinity_context_server.memory_comparison_full_profiles import INFINITY_COMPARISON_BACKEND
from infinity_context_server.memory_comparison_http import _safe_slug
from infinity_context_server.memory_comparison_managed_benchmark_registry_contracts import (
    ManagedBenchmarkRunRegistration,
)
from infinity_context_server.memory_comparison_managed_http_lifecycle_registration import (
    infinity_clean_state_proofs,
    validate_benchmark_registration,
)
from infinity_context_server.memory_comparison_managed_infinity_clean_state_source import (
    ManagedInfinityCleanStateEvidencePublisher,
    record_managed_infinity_clean_state_ingest,
    record_managed_infinity_clean_state_reset_evidence,
)
from infinity_context_server.memory_comparison_managed_infinity_http_execution import (
    ManagedInfinityHttpExecutionAdapter,
    ManagedInfinityHttpRuntimeConfig,
)
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunCase
from infinity_context_server.memory_comparison_managed_runner_binding import (
    ManagedRunnerCompositionBinding,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import is_sha256
from infinity_context_server.memory_comparison_models import BackendIngestResult

MANAGED_INFINITY_HTTP_LIFECYCLE_ADAPTER_ID = "managed-infinity-http-lifecycle-v1"
_TOKEN = object()


class ManagedInfinityHttpLifecycleError(RuntimeError):
    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@final
class ManagedInfinityHttpIngestReceipt:
    __slots__ = ()

    def __init__(self, *, _token: object) -> None:
        if _token is not _TOKEN:
            _fail("managed_infinity_ingest_receipt_forged")

    def __repr__(self) -> str:
        return "ManagedInfinityHttpIngestReceipt(<opaque>)"

    def __reduce__(self) -> object:
        raise TypeError("managed Infinity ingest receipt is nonserializable")


@final
@dataclass(frozen=True, slots=True)
class ManagedInfinityHttpIngestEvidence:
    """Owner-authenticated Infinity ingest result for one unique corpus."""

    case_id: str
    corpus_id: str
    target_identity_sha256: str
    ingest_result: BackendIngestResult

    def __post_init__(self) -> None:
        if (
            type(self.case_id) is not str
            or not self.case_id
            or type(self.corpus_id) is not str
            or not self.corpus_id
            or not is_sha256(self.target_identity_sha256)
            or type(self.ingest_result) is not BackendIngestResult
        ):
            _fail("managed_infinity_ingest_evidence_invalid")


@final
class ManagedInfinityHttpLifecycleAdapter:
    """Publish Infinity clean evidence only after real reset and ordered ingest."""

    __slots__ = (
        "_binding",
        "_cases",
        "_clock",
        "_config",
        "_execution",
        "_evidence",
        "_evidence_consumed",
        "_lock",
        "_next",
        "_phase",
        "_publisher",
        "_receipts",
        "_registration",
    )

    def __init__(
        self,
        *,
        composition_binding: ManagedRunnerCompositionBinding,
        cases: tuple[ManagedRunCase, ...],
        execution: ManagedInfinityHttpExecutionAdapter,
        config: ManagedInfinityHttpRuntimeConfig,
        clean_state_publisher: ManagedInfinityCleanStateEvidencePublisher,
        benchmark_registration: ManagedBenchmarkRunRegistration | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        corpora = _unique_corpora(cases)
        if (
            type(composition_binding) is not ManagedRunnerCompositionBinding
            or type(execution) is not ManagedInfinityHttpExecutionAdapter
            or execution.composition_binding is not composition_binding
            or type(config) is not ManagedInfinityHttpRuntimeConfig
            or type(clean_state_publisher) is not ManagedInfinityCleanStateEvidencePublisher
            or not callable(clock)
        ):
            _fail("managed_infinity_lifecycle_composition_invalid")
        targets = tuple(
            item.target_identity_sha256
            for item in composition_binding.backend_targets
            if item.backend_role == INFINITY_COMPARISON_BACKEND
        )
        if len(targets) != 1 or targets[0] != config.target_identity_sha256:
            _fail("managed_infinity_lifecycle_composition_invalid")
        pairs = tuple(
            (item.backend_role, item.target_identity_sha256)
            for item in composition_binding.backend_targets
        )
        try:
            registration = validate_benchmark_registration(
                benchmark_registration,
                run_id=composition_binding.run_id,
                binding_commitment_sha256=composition_binding.binding_commitment_sha256,
                target_pairs=pairs,
                space_slug=self_space_slug(composition_binding.run_id),
            )
        except Exception:
            _fail("managed_infinity_lifecycle_registration_invalid")
        self._binding = composition_binding
        self._cases = corpora
        self._execution = execution
        self._config = config
        self._publisher = clean_state_publisher
        self._registration = registration
        self._clock = clock
        self._lock = threading.RLock()
        self._phase = "new"
        self._next = 0
        self._receipts: tuple[ManagedInfinityHttpIngestReceipt, ...] = ()
        self._evidence: tuple[ManagedInfinityHttpIngestEvidence, ...] = ()
        self._evidence_consumed = False

    @property
    def adapter_id(self) -> str:
        return MANAGED_INFINITY_HTTP_LIFECYCLE_ADAPTER_ID

    @property
    def implementation_sha256(self) -> str:
        return managed_infinity_http_lifecycle_implementation_sha256()

    @property
    def composition_binding(self) -> ManagedRunnerCompositionBinding:
        return self._binding

    def reset(
        self,
        *,
        run_id: str,
        binding_commitment_sha256: str,
        backend_targets: tuple[tuple[str, str], ...],
    ) -> None:
        with self._lock:
            if self._phase != "new":
                self._phase = "terminal"
                _fail("managed_infinity_lifecycle_reset_replay")
            if (
                run_id != self._binding.run_id
                or binding_commitment_sha256 != self._binding.binding_commitment_sha256
                or backend_targets != _target_pairs(self._binding)
            ):
                self._phase = "terminal"
                _fail("managed_infinity_lifecycle_reset_binding_invalid")
            self._phase = "resetting"
        try:
            self._ensure_deadline()
            corpus_ids = tuple(item.corpus_id for item in self._cases)
            corpus_hashes = tuple(clean_state_identity_sha256(item) for item in corpus_ids)
            key = secrets.token_bytes(32)
            proofs = infinity_clean_state_proofs(
                registration=self._registration,
                run_id=self._binding.run_id,
                slug=self_space_slug(self._binding.run_id),
                corpus_hashes=corpus_hashes,
                expected_scope_count=len(corpus_ids),
                attestation_key=key,
                client_factory=self._reset_client,
            )
            scopes = tuple(
                FullExecutionCleanScope(
                    INFINITY_COMPARISON_BACKEND,
                    corpus_hash,
                    clean_state_identity_sha256(self_space_slug(self._binding.run_id)),
                )
                for corpus_hash in corpus_hashes
            )
            evidence = issue_infinity_di_full_execution_clean_state_evidence(
                corpus_ids=corpus_ids,
                proofs=proofs,
                scopes=scopes,
                attestation_key=key,
            )
            record_managed_infinity_clean_state_reset_evidence(
                self._publisher,
                composition_binding=self._binding,
                corpus_ids=corpus_ids,
                producer_implementation_sha256=self.implementation_sha256,
                evidence=evidence,
            )
        except Exception:
            with self._lock:
                self._phase = "terminal"
            _fail("managed_infinity_lifecycle_reset_failed")
        with self._lock:
            if self._phase != "resetting":
                self._phase = "terminal"
                _fail("managed_infinity_lifecycle_reset_concurrent")
            self._phase = "ready"

    def ingest(
        self,
        *,
        run_id: str,
        backend_role: str,
        target_identity_sha256: str,
        record: Mapping[str, object],
    ) -> ManagedInfinityHttpIngestReceipt:
        with self._lock:
            ordinal = self._next
            if self._phase != "ready" or ordinal >= len(self._cases):
                self._phase = "terminal"
                _fail("managed_infinity_lifecycle_ingest_phase_invalid")
            case = self._cases[ordinal]
            if (
                run_id != self._binding.run_id
                or backend_role != INFINITY_COMPARISON_BACKEND
                or target_identity_sha256 != self._config.target_identity_sha256
                or not isinstance(record, Mapping)
                or _canonical(record) != _canonical(case.record)
            ):
                self._phase = "terminal"
                _fail("managed_infinity_lifecycle_ingest_binding_invalid")
            self._phase = "ingesting"
        try:
            self._ensure_deadline()
            result = self._execution.ingest(case=case)
            if result.items_processed < 1 or result.items_failed != 0:
                raise TypeError
            record_managed_infinity_clean_state_ingest(
                self._publisher,
                composition_binding=self._binding,
                target_identity_sha256=target_identity_sha256,
                corpus_id=case.corpus_id,
                producer_implementation_sha256=self.implementation_sha256,
            )
            receipt = ManagedInfinityHttpIngestReceipt(_token=_TOKEN)
        except Exception:
            with self._lock:
                self._phase = "terminal"
            _fail("managed_infinity_lifecycle_ingest_failed")
        with self._lock:
            if self._phase != "ingesting" or self._next != ordinal:
                self._phase = "terminal"
                _fail("managed_infinity_lifecycle_ingest_concurrent")
            self._next += 1
            self._receipts = (*self._receipts, receipt)
            self._evidence = (
                *self._evidence,
                ManagedInfinityHttpIngestEvidence(
                    case.case_id,
                    case.corpus_id,
                    target_identity_sha256,
                    result,
                ),
            )
            self._phase = "complete" if self._next == len(self._cases) else "ready"
        return receipt

    def consume_exact_ingest_receipts(
        self,
        *,
        receipts: tuple[ManagedInfinityHttpIngestReceipt, ...],
        cases: tuple[ManagedRunCase, ...],
    ) -> tuple[ManagedInfinityHttpIngestEvidence, ...]:
        """Atomically authenticate and consume the exact lifecycle-owned tuple."""

        with self._lock:
            exact_cases = (
                type(cases) is tuple
                and len(cases) == len(self._cases)
                and all(
                    candidate is expected
                    for candidate, expected in zip(cases, self._cases, strict=True)
                )
            )
            if (
                self._phase != "complete"
                or self._evidence_consumed
                or type(receipts) is not tuple
                or receipts != self._receipts
                or not exact_cases
                or len(self._evidence) != len(self._cases)
            ):
                self._phase = "terminal"
                _fail("managed_infinity_ingest_evidence_consume_invalid")
            self._evidence_consumed = True
            self._phase = "evidence"
            return self._evidence

    def _reset_client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self._config.base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {self._config.auth_token}"},
            timeout=float(self._config.timeout_seconds),
            transport=self._config.transport,
        )

    def _ensure_deadline(self) -> None:
        now = self._clock()
        if type(now) is not datetime or now.tzinfo is None or now >= self._binding.deadline:
            _fail("managed_infinity_lifecycle_deadline_expired")


def _unique_corpora(cases: object) -> tuple[ManagedRunCase, ...]:
    if (
        type(cases) is not tuple
        or not cases
        or any(type(item) is not ManagedRunCase for item in cases)
    ):
        _fail("managed_infinity_lifecycle_cases_invalid")
    seen: dict[str, ManagedRunCase] = {}
    for case in cases:
        current = seen.get(case.corpus_id)
        if current is None:
            seen[case.corpus_id] = case
        elif _canonical(current.record) != _canonical(case.record):
            _fail("managed_infinity_lifecycle_cases_invalid")
    return tuple(seen.values())


def _target_pairs(binding: ManagedRunnerCompositionBinding) -> tuple[tuple[str, str], ...]:
    return tuple(
        (item.backend_role, item.target_identity_sha256) for item in binding.backend_targets
    )


def _canonical(value: object) -> bytes:
    return json.dumps(
        _plain_json(value), allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode()


def _plain_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain_json(item) for key, item in value.items()}
    if type(value) in {tuple, list}:
        return [_plain_json(item) for item in value]
    return value


def self_space_slug(run_id: str) -> str:
    return f"memory-comparison-{_safe_slug(run_id)}"


def managed_infinity_http_lifecycle_implementation_sha256() -> str:
    return hashlib.sha256(
        b"managed-infinity-http-lifecycle-v1\0infinity-only\0ordered-real-reset-ingest"
    ).hexdigest()


def _fail(code: str) -> NoReturn:
    raise ManagedInfinityHttpLifecycleError(code)


__all__ = (
    "MANAGED_INFINITY_HTTP_LIFECYCLE_ADAPTER_ID",
    "ManagedInfinityHttpIngestEvidence",
    "ManagedInfinityHttpIngestReceipt",
    "ManagedInfinityHttpLifecycleAdapter",
    "ManagedInfinityHttpLifecycleError",
    "managed_infinity_http_lifecycle_implementation_sha256",
)

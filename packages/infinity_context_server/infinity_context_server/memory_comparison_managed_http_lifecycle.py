"""One-shot reset and ingest lifecycle for admitted managed HTTP targets."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import secrets
import threading
import weakref
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import final

import httpx

from infinity_context_server.memory_comparison_backend_target import FullComparisonBackendTarget
from infinity_context_server.memory_comparison_benchmark_identity import mem0_benchmark_user_id
from infinity_context_server.memory_comparison_clean_state import (
    VerifiedCleanStateValidation,
    clean_state_identity_sha256,
    fresh_namespace_clean_state_proof,
    public_clean_state_validation,
    validate_typed_clean_state_proofs,
)
from infinity_context_server.memory_comparison_clean_state_http import (
    InfinityCleanStateSession,
    Mem0CleanStateSession,
)
from infinity_context_server.memory_comparison_full_execution_validation_slots import (
    FullExecutionCleanScope,
)
from infinity_context_server.memory_comparison_full_profiles import (
    INFINITY_COMPARISON_BACKEND,
    REQUIRED_FULL_COMPARISON_BACKENDS,
)
from infinity_context_server.memory_comparison_http import _safe_slug
from infinity_context_server.memory_comparison_locomo_transport import (
    LocomoTimestampTransportEvidence,
    RunScopedLocomoTransportEvidenceKey,
)
from infinity_context_server.memory_comparison_managed_http_execution import (
    ManagedComparisonHttpExecutionAdapter,
    ManagedInfinityHttpConfig,
    ManagedMem0HttpConfig,
)
from infinity_context_server.memory_comparison_managed_http_lifecycle_credentials import (
    ManagedHttpLifecycleCredentialError,
    consume_managed_http_lifecycle_credentials,
)
from infinity_context_server.memory_comparison_managed_http_lifecycle_evidence import (
    ManagedHttpExecutionEvidenceCapability,
    _advance_execution_evidence,
    _new_execution_evidence,
    terminalize_managed_http_execution_evidence,
)
from infinity_context_server.memory_comparison_managed_http_lifecycle_evidence import (
    ManagedHttpExecutionEvidenceError as ManagedHttpExecutionEvidenceError,
)
from infinity_context_server.memory_comparison_managed_http_lifecycle_evidence import (
    ManagedHttpExecutionEvidenceView as ManagedHttpExecutionEvidenceView,
)
from infinity_context_server.memory_comparison_managed_http_lifecycle_evidence import (
    consume_managed_http_execution_evidence as consume_managed_http_execution_evidence,
)
from infinity_context_server.memory_comparison_managed_preflight import (
    ManagedPreflightRequest,
)
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunCase
from infinity_context_server.memory_comparison_models import BackendIngestResult

MANAGED_HTTP_LIFECYCLE_ADAPTER_ID = "managed-comparison-http-reset-ingest-v1"
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TOKEN = object()
_RECEIPT_LOCK = threading.RLock()


class ManagedHttpLifecycleError(RuntimeError):
    """Fixed-code error without credentials, endpoints, or provider payloads."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@final
class ManagedHttpIngestReceipt:
    """Opaque one-use receipt for downstream policy composition."""

    __slots__ = ("__weakref__",)

    def __init__(self, *, _token: object) -> None:
        if _token is not _TOKEN:
            raise ManagedHttpLifecycleError("managed_http_ingest_receipt_forged")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedHttpIngestReceipt is final")

    def __repr__(self) -> str:
        return "ManagedHttpIngestReceipt(<opaque>)"

    def __reduce__(self) -> object:
        raise TypeError("ManagedHttpIngestReceipt is nonserializable")


@final
@dataclass(frozen=True, slots=True, repr=False)
class ManagedHttpIngestEvidenceView:
    """Live typed evidence released after exact receipt coverage validation."""

    backend_role: str
    target_identity_sha256: str
    case_id: str
    corpus_id: str
    clean_state_validation: VerifiedCleanStateValidation
    ingest_result: BackendIngestResult
    locomo_timestamp_verifier: RunScopedLocomoTransportEvidenceKey | None
    locomo_timestamp_evidence: tuple[LocomoTimestampTransportEvidence, ...]

    def __repr__(self) -> str:
        return "ManagedHttpIngestEvidenceView(<redacted>)"

    def __reduce__(self) -> object:
        raise TypeError("ManagedHttpIngestEvidenceView is nonserializable")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedHttpIngestEvidenceView is final")


@dataclass(slots=True)
class _ReceiptState:
    owner: object
    secret: bytes
    ordinal: int
    run_id: str
    binding: str
    role: str
    target: str
    case: ManagedRunCase
    clean: VerifiedCleanStateValidation
    result: BackendIngestResult
    verifier: RunScopedLocomoTransportEvidenceKey | None
    evidence: tuple[LocomoTimestampTransportEvidence, ...]
    snapshot: str
    commitment: str
    phase: str


_RECEIPTS: weakref.WeakKeyDictionary[ManagedHttpIngestReceipt, _ReceiptState] = (
    weakref.WeakKeyDictionary()
)


@final
class ManagedComparisonHttpLifecycleAdapter:
    """Bind one run to reset, then target-major corpus ingestion exactly once."""

    def __init__(
        self,
        *,
        run_id: str,
        binding_commitment_sha256: str,
        admitted_targets: tuple[FullComparisonBackendTarget, ...],
        cases: tuple[ManagedRunCase, ...],
        deadline: datetime,
        execution: ManagedComparisonHttpExecutionAdapter,
        preflight_request: ManagedPreflightRequest,
        credential_material: object,
        infinity_reset_transport: httpx.BaseTransport | None = None,
        mem0_reset_transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        _identifier(run_id, "managed_http_lifecycle_run_invalid")
        _digest(binding_commitment_sha256, "managed_http_lifecycle_binding_invalid")
        _targets(admitted_targets)
        corpora = _corpora(cases)
        if type(execution) is not ManagedComparisonHttpExecutionAdapter:
            raise ManagedHttpLifecycleError("managed_http_lifecycle_execution_invalid")
        reset_transports = (infinity_reset_transport, mem0_reset_transport)
        if any(
            item is not None and type(item) is not httpx.MockTransport for item in reset_transports
        ):
            raise ManagedHttpLifecycleError("managed_http_lifecycle_reset_transport_invalid")
        if not callable(clock):
            raise ManagedHttpLifecycleError("managed_http_lifecycle_clock_invalid")
        trusted_deadline = _aware(deadline, "managed_http_lifecycle_deadline_invalid")
        if _aware(clock(), "managed_http_lifecycle_clock_invalid") >= trusted_deadline:
            raise ManagedHttpLifecycleError("managed_http_lifecycle_deadline_expired")
        try:
            infinity, mem0 = consume_managed_http_lifecycle_credentials(
                preflight_request=preflight_request,
                credential_material=credential_material,
                run_id=run_id,
                deadline=trusted_deadline,
                admitted_targets=admitted_targets,
            )
        except ManagedHttpLifecycleCredentialError as exc:
            raise ManagedHttpLifecycleError(exc.code) from None
        owned = tuple(
            item
            for item in (*reset_transports, infinity.transport, mem0.transport)
            if item is not None
        )
        if len({id(item) for item in owned}) != len(owned):
            raise ManagedHttpLifecycleError("managed_http_lifecycle_transport_alias")
        if (
            any(case.record.get("benchmark") == "locomo" for case in cases)
            and mem0.send_timestamps is not True
        ):
            raise ManagedHttpLifecycleError("managed_http_lifecycle_locomo_timestamp_disabled")

        self._run_id = run_id
        self._binding = binding_commitment_sha256
        self._target_pairs = tuple(
            (item.backend_role, item.target_identity_sha256) for item in admitted_targets
        )
        self._corpora = corpora
        self._deadline = trusted_deadline
        self._clock = clock
        self._execution = execution
        self._infinity = infinity
        self._infinity_reset_transport = infinity_reset_transport
        self._mem0 = mem0
        self._mem0_reset_transport = mem0_reset_transport
        self._lock = threading.RLock()
        self._phase = "new"
        self._next = 0
        self._clean: VerifiedCleanStateValidation | None = None
        self._owner = object()
        self._secret = secrets.token_bytes(32)
        self._execution_evidence: ManagedHttpExecutionEvidenceCapability | None = None
        self._execution_evidence_delivered = False
        self._receipts: list[ManagedHttpIngestReceipt] = []
        self._locomo_verifier: RunScopedLocomoTransportEvidenceKey | None = None
        self._locomo_evidence: tuple[LocomoTimestampTransportEvidence, ...] = ()

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedComparisonHttpLifecycleAdapter is final")

    def __repr__(self) -> str:
        return "ManagedComparisonHttpLifecycleAdapter(<redacted>)"

    def __reduce__(self) -> object:
        raise TypeError("ManagedComparisonHttpLifecycleAdapter is nonserializable")

    @property
    def adapter_id(self) -> str:
        return MANAGED_HTTP_LIFECYCLE_ADAPTER_ID

    @property
    def implementation_sha256(self) -> str:
        return managed_http_lifecycle_implementation_sha256()

    def execution_evidence_capability(self) -> ManagedHttpExecutionEvidenceCapability:
        """Release the disjoint one-use execution evidence authority after full ingest."""

        with self._lock:
            capability = self._execution_evidence
            if (
                self._phase != "complete"
                or self._next != len(self._expected_ingests())
                or type(capability) is not ManagedHttpExecutionEvidenceCapability
                or self._execution_evidence_delivered
            ):
                raise ManagedHttpLifecycleError("managed_http_execution_evidence_not_complete")
            self._execution_evidence_delivered = True
            return capability

    def reset(
        self,
        *,
        run_id: str,
        binding_commitment_sha256: str,
        backend_targets: tuple[tuple[str, str], ...],
    ) -> None:
        with self._lock:
            if self._phase != "new":
                self._terminal_locked()
                raise ManagedHttpLifecycleError("managed_http_lifecycle_reset_replay")
            self._phase = "resetting"
        try:
            if (
                run_id != self._run_id
                or binding_commitment_sha256 != self._binding
                or type(backend_targets) is not tuple
                or backend_targets != self._target_pairs
            ):
                raise ManagedHttpLifecycleError("managed_http_lifecycle_reset_binding_mismatch")
            self._ensure_deadline()
            clean, key, scopes, provenance = self._perform_reset()
            if public_clean_state_validation(clean).get("eligible") is not True:
                raise ManagedHttpLifecycleError("managed_http_lifecycle_reset_proof_invalid")
        except ManagedHttpLifecycleError:
            self._terminal()
            raise
        except BaseException:
            self._terminal()
            raise ManagedHttpLifecycleError("managed_http_lifecycle_reset_failed") from None
        with self._lock:
            if self._phase != "resetting":
                self._terminal_locked()
                raise ManagedHttpLifecycleError("managed_http_lifecycle_reset_concurrent")
            self._clean = clean
            self._execution_evidence = _new_execution_evidence(
                owner=self._owner,
                secret=self._secret,
                run_id=self._run_id,
                binding=self._binding,
                target_pairs=self._target_pairs,
                case_bindings=tuple((case.case_id, case.corpus_id) for case in self._corpora),
                validation=clean,
                scopes=scopes,
                provenance=provenance,
                attestation_key=key,
                expected_ingest_count=len(self._expected_ingests()),
            )
            self._phase = "ready"

    def ingest(
        self,
        *,
        run_id: str,
        backend_role: str,
        target_identity_sha256: str,
        record: Mapping[str, object],
    ) -> ManagedHttpIngestReceipt:
        expected = self._expected_ingests()
        with self._lock:
            if self._phase == "ingesting":
                self._terminal_locked()
                raise ManagedHttpLifecycleError("managed_http_lifecycle_ingest_concurrent")
            if self._phase != "ready" or self._next >= len(expected):
                self._terminal_locked()
                raise ManagedHttpLifecycleError("managed_http_lifecycle_ingest_phase_invalid")
            ordinal = self._next
            role, target, case = expected[ordinal]
            self._phase = "ingesting"
        try:
            if (
                run_id != self._run_id
                or backend_role != role
                or target_identity_sha256 != target
                or type(record) is not dict
                or _json(record) != _json(case.record)
            ):
                raise ManagedHttpLifecycleError("managed_http_lifecycle_ingest_binding_mismatch")
            self._ensure_deadline()
            result = self._execution.ingest(
                run_id=run_id,
                backend_role=backend_role,
                target_identity_sha256=target_identity_sha256,
                case=case,
            )
            if (
                type(result) is not BackendIngestResult
                or result.items_processed < 1
                or result.items_failed != 0
            ):
                raise ManagedHttpLifecycleError("managed_http_lifecycle_ingest_result_invalid")
            verifier, evidence = self._timestamp_delta(backend_role, target_identity_sha256, case)
            with self._lock:
                if self._phase != "ingesting":
                    raise ManagedHttpLifecycleError("managed_http_lifecycle_ingest_concurrent")
            _advance_execution_evidence(self._execution_evidence, verifier, evidence)
            clean = self._clean
            if type(clean) is not VerifiedCleanStateValidation:
                raise ManagedHttpLifecycleError("managed_http_lifecycle_reset_proof_missing")
            receipt = self._issue_receipt(
                ordinal,
                backend_role,
                target_identity_sha256,
                case,
                clean,
                result,
                verifier,
                evidence,
            )
        except ManagedHttpLifecycleError:
            self._terminal()
            raise
        except ManagedHttpExecutionEvidenceError as exc:
            self._terminal()
            raise ManagedHttpLifecycleError(exc.code) from None
        except BaseException:
            self._terminal()
            raise ManagedHttpLifecycleError("managed_http_lifecycle_ingest_failed") from None
        with self._lock:
            if self._phase != "ingesting" or self._next != ordinal:
                self._terminal_locked()
                _discard(receipt)
                raise ManagedHttpLifecycleError("managed_http_lifecycle_ingest_concurrent")
            self._receipts.append(receipt)
            self._next += 1
            self._phase = "complete" if self._next == len(expected) else "ready"
        return receipt

    def _perform_reset(
        self,
    ) -> tuple[
        VerifiedCleanStateValidation,
        bytes,
        tuple[FullExecutionCleanScope, ...],
        MappingProxyType[str, object],
    ]:
        count = len(self._corpora)
        slug = f"memory-comparison-{_safe_slug(self._run_id)}"
        user_id = mem0_benchmark_user_id(self._run_id)
        corpus_hashes = tuple(clean_state_identity_sha256(case.corpus_id) for case in self._corpora)
        key = secrets.token_bytes(32)
        infinity_session = InfinityCleanStateSession(backend=INFINITY_COMPARISON_BACKEND)
        mem0_session = Mem0CleanStateSession(reset_enabled=True)
        infinity_client = self._client(self._infinity, self._infinity_reset_transport)
        mem0_client = self._client(self._mem0, self._mem0_reset_transport)
        try:
            first = infinity_session.reset(
                infinity_client,
                run_id=self._run_id,
                slug=slug,
                corpus_identity_sha256=corpus_hashes[0],
                expected_scope_count=count,
                attestation_key=key,
            )
            infinity_proofs = [first]
            infinity_proofs.extend(
                fresh_namespace_clean_state_proof(
                    backend=INFINITY_COMPARISON_BACKEND,
                    run_id=self._run_id,
                    expected_slug=slug,
                    corpus_identity_sha256=corpus_hash,
                    expected_scope_count=count,
                    status_code=201,
                    payload={"data": {"slug": slug}},
                    attestation_key=key,
                )
                for corpus_hash in corpus_hashes[1:]
            )
            for corpus_hash in corpus_hashes:
                self._ensure_deadline()
                mem0_session.reset_scope(
                    mem0_client,
                    user_id=user_id,
                    run_id=self._run_id,
                    corpus_identity_sha256=corpus_hash,
                    expected_scope_count=count,
                    attestation_key=key,
                    record=True,
                )
        finally:
            infinity_client.close()
            mem0_client.close()
        expected = {
            INFINITY_COMPARISON_BACKEND: {
                item: clean_state_identity_sha256(slug) for item in corpus_hashes
            },
            "mem0": {item: clean_state_identity_sha256(user_id) for item in corpus_hashes},
        }
        validation = validate_typed_clean_state_proofs(
            {
                INFINITY_COMPARISON_BACKEND: tuple(infinity_proofs),
                "mem0": mem0_session.proofs(),
            },
            expected_run_id_sha256=clean_state_identity_sha256(self._run_id),
            expected_scopes_by_backend=expected,
            attestation_key=key,
        )
        scopes = tuple(
            FullExecutionCleanScope(role, corpus_hash, expected[role][corpus_hash])
            for role in REQUIRED_FULL_COMPARISON_BACKENDS
            for corpus_hash in corpus_hashes
        )
        provenance = MappingProxyType(
            {
                "infinity_namespace_http_observation_count": 1,
                "infinity_corpus_proof_count": count,
                "infinity_derived_corpus_proof_count": count - 1,
                "mem0_delete_readback_http_observation_count": count,
            }
        )
        return validation, key, scopes, provenance

    def _client(
        self,
        config: ManagedInfinityHttpConfig | ManagedMem0HttpConfig,
        reset_transport: httpx.BaseTransport | None,
    ) -> httpx.Client:
        headers = (
            {"Authorization": f"Bearer {config.auth_token}"}
            if type(config) is ManagedInfinityHttpConfig
            else ({"X-API-Key": config.api_key} if config.api_key else None)
        )
        inner = reset_transport or httpx.HTTPTransport(retries=0, trust_env=False)
        return httpx.Client(
            base_url=config.base_url.rstrip("/"),
            headers=headers,
            timeout=float(config.timeout_seconds),
            transport=_DeadlineTransport(
                inner,
                configured_timeout=float(config.timeout_seconds),
                deadline=self._deadline,
                clock=self._clock,
            ),
        )

    def _timestamp_delta(
        self, role: str, target: str, case: ManagedRunCase
    ) -> tuple[
        RunScopedLocomoTransportEvidenceKey | None,
        tuple[LocomoTimestampTransportEvidence, ...],
    ]:
        if role != "mem0":
            return None, ()
        verifier = self._execution.locomo_timestamp_transport_verifier(
            run_id=self._run_id, target_identity_sha256=target
        )
        current = self._execution.locomo_timestamp_transport_evidence(
            run_id=self._run_id, target_identity_sha256=target
        )
        previous = self._locomo_evidence
        if current[: len(previous)] != previous:
            raise ManagedHttpLifecycleError("managed_http_lifecycle_timestamp_history_changed")
        delta = current[len(previous) :]
        official = case.record.get("benchmark") == "locomo"
        expected_count = len(case.record.get("memories", ())) if official else 0
        if official and (
            type(verifier) is not RunScopedLocomoTransportEvidenceKey
            or len(delta) != expected_count
            or any(type(item) is not LocomoTimestampTransportEvidence for item in delta)
        ):
            raise ManagedHttpLifecycleError("managed_http_lifecycle_timestamp_evidence_invalid")
        if not official and delta:
            raise ManagedHttpLifecycleError("managed_http_lifecycle_timestamp_evidence_unexpected")
        if self._locomo_verifier is not None and verifier is not self._locomo_verifier:
            raise ManagedHttpLifecycleError("managed_http_lifecycle_timestamp_verifier_changed")
        if verifier is not None:
            self._locomo_verifier = verifier
        self._locomo_evidence = current
        return verifier, delta

    def _issue_receipt(
        self,
        ordinal: int,
        role: str,
        target: str,
        case: ManagedRunCase,
        clean: VerifiedCleanStateValidation,
        result: BackendIngestResult,
        verifier: RunScopedLocomoTransportEvidenceKey | None,
        evidence: tuple[LocomoTimestampTransportEvidence, ...],
    ) -> ManagedHttpIngestReceipt:
        snapshot = _snapshot(clean, result, verifier, evidence)
        commitment = _commitment(
            self._secret, ordinal, self._run_id, self._binding, role, target, case, snapshot
        )
        receipt = ManagedHttpIngestReceipt(_token=_TOKEN)
        state = _ReceiptState(
            self._owner,
            self._secret,
            ordinal,
            self._run_id,
            self._binding,
            role,
            target,
            case,
            clean,
            result,
            verifier,
            evidence,
            snapshot,
            commitment,
            "live",
        )
        with _RECEIPT_LOCK:
            _RECEIPTS[receipt] = state
        return receipt

    def _expected_ingests(self) -> tuple[tuple[str, str, ManagedRunCase], ...]:
        return tuple(
            (role, target, case) for role, target in self._target_pairs for case in self._corpora
        )

    def _ensure_deadline(self) -> None:
        if _aware(self._clock(), "managed_http_lifecycle_clock_invalid") >= self._deadline:
            raise ManagedHttpLifecycleError("managed_http_lifecycle_deadline_expired")

    def _terminal(self) -> None:
        with self._lock:
            self._terminal_locked()

    def _terminal_locked(self) -> None:
        self._phase = "terminal"
        terminalize_managed_http_execution_evidence(self._execution_evidence)
        with _RECEIPT_LOCK:
            for receipt in self._receipts:
                state = _RECEIPTS.get(receipt)
                if state is not None:
                    state.phase = "terminal"


class _DeadlineTransport(httpx.BaseTransport):
    def __init__(
        self,
        inner: httpx.BaseTransport,
        *,
        configured_timeout: float,
        deadline: datetime,
        clock: Callable[[], datetime],
    ) -> None:
        self._inner = inner
        self._configured_timeout = configured_timeout
        self._deadline = deadline
        self._clock = clock

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        remaining = (
            self._deadline - _aware(self._clock(), "managed_http_lifecycle_clock_invalid")
        ).total_seconds()
        if not math.isfinite(remaining) or remaining <= 0:
            raise ManagedHttpLifecycleError("managed_http_lifecycle_deadline_expired")
        timeout = min(self._configured_timeout, remaining)
        request.extensions["timeout"] = dict.fromkeys(("connect", "read", "write", "pool"), timeout)
        return self._inner.handle_request(request)

    def close(self) -> None:
        self._inner.close()


def consume_managed_http_ingest_receipts(
    receipts: tuple[object, ...],
    *,
    run_id: str,
    binding_commitment_sha256: str,
    backend_targets: tuple[FullComparisonBackendTarget, ...],
    cases: tuple[ManagedRunCase, ...],
) -> tuple[ManagedHttpIngestEvidenceView, ...]:
    """Atomically consume an exact complete target-major receipt set."""

    _identifier(run_id, "managed_http_receipt_run_invalid")
    _digest(binding_commitment_sha256, "managed_http_receipt_binding_invalid")
    targets = _targets(backend_targets)
    expected = tuple(
        (role, targets[role], case)
        for role in REQUIRED_FULL_COMPARISON_BACKENDS
        for case in _corpora(cases)
    )
    if type(receipts) is not tuple or len(receipts) != len(expected):
        raise ManagedHttpLifecycleError("managed_http_receipt_coverage_invalid")
    with _RECEIPT_LOCK:
        states = tuple(_state(item) for item in receipts)
        if len({id(state.owner) for state in states}) != 1:
            raise ManagedHttpLifecycleError("managed_http_receipt_owner_mismatch")
        for ordinal, (state, (role, target, case)) in enumerate(zip(states, expected, strict=True)):
            snapshot = _snapshot(state.clean, state.result, state.verifier, state.evidence)
            commitment = _commitment(
                state.secret,
                ordinal,
                run_id,
                binding_commitment_sha256,
                role,
                target,
                case,
                snapshot,
            )
            if (
                state.phase != "live"
                or state.ordinal != ordinal
                or state.run_id != run_id
                or state.binding != binding_commitment_sha256
                or state.role != role
                or state.target != target
                or state.case is not case
                or state.snapshot != snapshot
                or not hmac.compare_digest(state.commitment, commitment)
            ):
                for item in states:
                    item.phase = "terminal"
                raise ManagedHttpLifecycleError("managed_http_receipt_binding_invalid")
        for state in states:
            state.phase = "consumed"
    return tuple(
        ManagedHttpIngestEvidenceView(
            state.role,
            state.target,
            state.case.case_id,
            state.case.corpus_id,
            state.clean,
            state.result,
            state.verifier,
            state.evidence,
        )
        for state in states
    )


def _targets(value: object) -> dict[str, str]:
    if (
        type(value) is not tuple
        or any(type(item) is not FullComparisonBackendTarget for item in value)
        or tuple(item.backend_role for item in value) != REQUIRED_FULL_COMPARISON_BACKENDS
    ):
        raise ManagedHttpLifecycleError("managed_http_lifecycle_targets_invalid")
    result = {item.backend_role: item.target_identity_sha256 for item in value}
    if len(result) != len(REQUIRED_FULL_COMPARISON_BACKENDS):
        raise ManagedHttpLifecycleError("managed_http_lifecycle_targets_invalid")
    return result


def _corpora(value: object) -> tuple[ManagedRunCase, ...]:
    if (
        type(value) is not tuple
        or not value
        or any(type(item) is not ManagedRunCase for item in value)
    ):
        raise ManagedHttpLifecycleError("managed_http_lifecycle_cases_invalid")
    records: dict[str, ManagedRunCase] = {}
    for case in value:
        current = records.get(case.corpus_id)
        if current is None:
            records[case.corpus_id] = case
        elif current.record != case.record:
            raise ManagedHttpLifecycleError("managed_http_lifecycle_corpus_conflict")
    return tuple(records.values())


def _state(value: object) -> _ReceiptState:
    if type(value) is not ManagedHttpIngestReceipt:
        raise ManagedHttpLifecycleError("managed_http_receipt_type_invalid")
    state = _RECEIPTS.get(value)
    if state is None:
        raise ManagedHttpLifecycleError("managed_http_receipt_unknown")
    return state


def _discard(value: ManagedHttpIngestReceipt) -> None:
    with _RECEIPT_LOCK:
        _RECEIPTS.pop(value, None)


def _snapshot(
    clean: VerifiedCleanStateValidation,
    result: BackendIngestResult,
    verifier: RunScopedLocomoTransportEvidenceKey | None,
    evidence: tuple[LocomoTimestampTransportEvidence, ...],
) -> str:
    if type(clean) is not VerifiedCleanStateValidation or type(result) is not BackendIngestResult:
        raise ManagedHttpLifecycleError("managed_http_receipt_evidence_invalid")
    if verifier is not None and type(verifier) is not RunScopedLocomoTransportEvidenceKey:
        raise ManagedHttpLifecycleError("managed_http_receipt_evidence_invalid")
    if type(evidence) is not tuple or any(
        type(item) is not LocomoTimestampTransportEvidence for item in evidence
    ):
        raise ManagedHttpLifecycleError("managed_http_receipt_evidence_invalid")
    material = {
        "clean": public_clean_state_validation(clean),
        "result": _result_material(result),
        "verifier_identity": id(verifier) if verifier is not None else None,
        "evidence_identities": [id(item) for item in evidence],
    }
    return hashlib.sha256(_canonical(material)).hexdigest()


def _result_material(result: BackendIngestResult) -> dict[str, object]:
    return {
        "items_processed": result.items_processed,
        "items_failed": result.items_failed,
        "total_memories_created": result.total_memories_created,
        "latency_ms": result.latency_ms,
        "reused": result.reused,
        "operations": [
            {
                "step": item.step,
                "operation_type": item.operation_type,
                "success": item.success,
                "latency_ms": item.latency_ms,
                "memory": item.memory,
                "item_id": item.item_id,
                "metadata": _json(item.metadata),
            }
            for item in result.operations
        ],
        "metadata": _json(result.metadata),
    }


def _json(value: object, *, depth: int = 0) -> object:
    if depth > 16:
        raise ManagedHttpLifecycleError("managed_http_receipt_json_invalid")
    if value is None or type(value) in {str, bool, int}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ManagedHttpLifecycleError("managed_http_receipt_json_invalid")
        return value
    if type(value) in {dict, MappingProxyType}:
        if any(type(key) is not str for key in value):
            raise ManagedHttpLifecycleError("managed_http_receipt_json_invalid")
        return {key: _json(item, depth=depth + 1) for key, item in sorted(value.items())}
    if type(value) in {list, tuple}:
        return [_json(item, depth=depth + 1) for item in value]
    raise ManagedHttpLifecycleError("managed_http_receipt_json_invalid")


def _commitment(
    secret: bytes,
    ordinal: int,
    run_id: str,
    binding: str,
    role: str,
    target: str,
    case: ManagedRunCase,
    snapshot: str,
) -> str:
    material = {
        "ordinal": ordinal,
        "run_id": run_id,
        "binding": binding,
        "role": role,
        "target": target,
        "case_id": case.case_id,
        "corpus_id": case.corpus_id,
        "record": _json(case.record),
        "snapshot": snapshot,
    }
    return hmac.new(secret, _canonical(material), hashlib.sha256).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(value, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()


def _identifier(value: object, code: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise ManagedHttpLifecycleError(code)
    return value


def _digest(value: object, code: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise ManagedHttpLifecycleError(code)
    return value


def _aware(value: object, code: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ManagedHttpLifecycleError(code)
    return value


def managed_http_lifecycle_implementation_sha256() -> str:
    material = {
        "adapter_id": MANAGED_HTTP_LIFECYCLE_ADAPTER_ID,
        "backend_order": list(REQUIRED_FULL_COMPARISON_BACKENDS),
        "clean_state": "fresh-infinity-namespace-and-mem0-delete-readback",
        "infinity_proof_provenance": "one-http-ack-plus-bound-corpus-derivations",
        "deadline": "min-configured-and-remaining-per-io",
        "ingest": "shared-managed-neutral-http-execution",
        "receipt": "opaque-hmac-live-one-use-complete-coverage",
        "retries": 0,
        "timestamp": "exact-locomo-transport-verifier-and-evidence-identities",
    }
    return hashlib.sha256(_canonical(material)).hexdigest()


__all__ = (
    "MANAGED_HTTP_LIFECYCLE_ADAPTER_ID",
    "ManagedComparisonHttpLifecycleAdapter",
    "ManagedHttpExecutionEvidenceCapability",
    "ManagedHttpExecutionEvidenceError",
    "ManagedHttpExecutionEvidenceView",
    "ManagedHttpIngestEvidenceView",
    "ManagedHttpIngestReceipt",
    "ManagedHttpLifecycleError",
    "consume_managed_http_execution_evidence",
    "consume_managed_http_ingest_receipts",
    "managed_http_lifecycle_implementation_sha256",
)

"""Fail-closed production HTTP policy lifecycle for managed comparisons.

Legacy backend APIs can perform part of cleanup, but cannot prove exact
canonical/source/derived identity for every corpus.  This adapter consumes the
real managed receipts and owns two cleanup passes without ever elevating an
incomplete HTTP response into a policy capability.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import threading
import weakref
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import final

import httpx

from infinity_context_server.memory_comparison_benchmark_identity import (
    mem0_benchmark_user_id,
)
from infinity_context_server.memory_comparison_full_run_evidence import (
    FullComparisonRunBindings,
)
from infinity_context_server.memory_comparison_managed_attestation import (
    VerifiedManagedCompositionAttestation,
)
from infinity_context_server.memory_comparison_managed_corpus_projection import (
    _reconstruct_managed_corpus_case,
)
from infinity_context_server.memory_comparison_managed_http_execution import (
    ManagedInfinityHttpConfig,
    ManagedMem0HttpConfig,
)
from infinity_context_server.memory_comparison_managed_http_lifecycle import (
    ManagedHttpIngestEvidenceView,
    consume_managed_http_ingest_receipts,
)
from infinity_context_server.memory_comparison_managed_preflight import (
    ManagedPreflightRequest,
)
from infinity_context_server.memory_comparison_managed_run_contract import (
    ManagedExecutionArtifacts,
    ManagedRunCase,
)

MANAGED_HTTP_POLICY_ADAPTER_ID = "managed-comparison-http-policy-fail-closed-v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TOKEN = object()
_RECEIPT_LOCK = threading.RLock()


class ManagedHttpPolicyLifecycleError(RuntimeError):
    """Stable machine-readable and secret-free blocker/error code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@final
class ManagedHttpPolicyDeleteReceipt:
    """Opaque record of one real legacy cleanup/readback pass."""

    __slots__ = ("__weakref__",)

    def __init__(self, *, _token: object) -> None:
        if _token is not _TOKEN:
            raise ManagedHttpPolicyLifecycleError("managed_http_policy_delete_receipt_forged")

    def __repr__(self) -> str:
        return "ManagedHttpPolicyDeleteReceipt(<opaque>)"

    def __reduce__(self) -> object:
        raise TypeError("ManagedHttpPolicyDeleteReceipt is nonserializable")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedHttpPolicyDeleteReceipt is final")


@dataclass(slots=True)
class _LegacyDeleteState:
    owner: object
    backend_role: str
    target_identity_sha256: str
    pass_index: int
    source_scope_count: int
    deleted_count: int
    canonical_absent: bool
    backend_verified_absent: bool
    phase: str


_DELETE_RECEIPTS: weakref.WeakKeyDictionary[
    ManagedHttpPolicyDeleteReceipt, _LegacyDeleteState
] = weakref.WeakKeyDictionary()


@final
class ManagedComparisonHttpPolicyLifecycleAdapter:
    """Exact ManagedPolicyLifecyclePort backed by owned HTTP cleanup clients.

    The constructor accepts transports only to provide transport ownership and
    offline testing.  It accepts no evidence callbacks or caller-provided ports.
    Each non-null transport must be distinct and is closed once by its pass.
    """

    def __init__(
        self,
        *,
        bindings: FullComparisonRunBindings,
        cases: tuple[ManagedRunCase, ...],
        preflight_request: ManagedPreflightRequest,
        credential_material: object,
        deadline: datetime,
        infinity_delete_transports: tuple[httpx.BaseTransport | None, ...] = (None, None),
        mem0_delete_transports: tuple[httpx.BaseTransport | None, ...] = (None, None),
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if type(bindings) is not FullComparisonRunBindings:
            raise ManagedHttpPolicyLifecycleError("managed_http_policy_bindings_invalid")
        if (
            type(cases) is not tuple
            or not cases
            or any(type(case) is not ManagedRunCase for case in cases)
        ):
            raise ManagedHttpPolicyLifecycleError("managed_http_policy_cases_invalid")
        if type(preflight_request) is not ManagedPreflightRequest:
            raise ManagedHttpPolicyLifecycleError(
                "managed_http_policy_preflight_request_invalid"
            )
        _two_transports(infinity_delete_transports)
        _two_transports(mem0_delete_transports)
        provided = tuple(
            item
            for item in (*infinity_delete_transports, *mem0_delete_transports)
            if item is not None
        )
        if len({id(item) for item in provided}) != len(provided):
            raise ManagedHttpPolicyLifecycleError("managed_http_policy_transport_ownership_invalid")
        if not callable(clock):
            raise ManagedHttpPolicyLifecycleError("managed_http_policy_clock_invalid")
        checked_deadline = _aware(deadline, "managed_http_policy_deadline_invalid")
        if _aware(clock(), "managed_http_policy_clock_invalid") >= checked_deadline:
            raise ManagedHttpPolicyLifecycleError("managed_http_policy_deadline_expired")
        try:
            from infinity_context_server import (
                memory_comparison_managed_runtime_credentials_capability as credential_capability,
            )

            if (
                type(credential_material)
                is not credential_capability.ManagedBackendCredentialMaterial
            ):
                raise ManagedHttpPolicyLifecycleError(
                    "managed_http_policy_credential_material_invalid"
                )
            infinity, mem0 = credential_material.consume_for_http_policy(
                expected_request=preflight_request,
                run_id=bindings.run_id,
                deadline=checked_deadline,
            )
        except ManagedHttpPolicyLifecycleError:
            raise
        except BaseException:
            raise ManagedHttpPolicyLifecycleError(
                "managed_http_policy_credential_continuity_failed"
            ) from None
        if (
            type(infinity) is not ManagedInfinityHttpConfig
            or type(mem0) is not ManagedMem0HttpConfig
            or infinity.transport is not None
            or mem0.transport is not None
        ):
            raise ManagedHttpPolicyLifecycleError(
                "managed_http_policy_credential_material_invalid"
            )
        targets = {
            item.backend_role: item.target_identity_sha256
            for item in bindings.backend_targets
        }
        if targets != {
            "infinity-context": infinity.target_identity_sha256,
            "mem0": mem0.target_identity_sha256,
        }:
            raise ManagedHttpPolicyLifecycleError(
                "managed_http_policy_target_binding_invalid"
            )
        self._bindings = bindings
        self._binding_snapshot = _binding_snapshot(bindings)
        self._cases = cases
        self._preflight_request = preflight_request
        self._deadline = checked_deadline
        self._infinity = infinity
        self._mem0 = mem0
        self._delete_transports = {
            "infinity-context": infinity_delete_transports,
            "mem0": mem0_delete_transports,
        }
        self._clock = clock
        self._phase = "open"
        self._next_delete = 0
        self._lock = threading.RLock()

    @property
    def adapter_id(self) -> str:
        return MANAGED_HTTP_POLICY_ADAPTER_ID

    @property
    def implementation_sha256(self) -> str:
        return managed_http_policy_lifecycle_implementation_sha256()

    def seal_canonical_source(
        self,
        *,
        bindings: FullComparisonRunBindings,
        cases: tuple[ManagedRunCase, ...],
        managed_attestation: VerifiedManagedCompositionAttestation,
        managed_attestation_commitment_sha256: str,
        ingest_receipts: tuple[object, ...],
        execution: ManagedExecutionArtifacts,
    ) -> tuple[object, ...]:
        """Consume exact receipt coverage, then reject incomplete observations."""

        self._validate_call(bindings, cases)
        _attestation(managed_attestation, managed_attestation_commitment_sha256)
        if type(execution) is not ManagedExecutionArtifacts:
            raise ManagedHttpPolicyLifecycleError("managed_http_policy_execution_invalid")
        with self._lock:
            if self._phase != "open":
                raise ManagedHttpPolicyLifecycleError("managed_http_policy_canonical_source_replay")
            self._phase = "consuming-ingest-evidence"
        try:
            views = consume_managed_http_ingest_receipts(
                ingest_receipts,
                run_id=bindings.run_id,
                binding_commitment_sha256=bindings.binding_commitment_sha256,
                backend_targets=bindings.backend_targets,
                cases=cases,
            )
            _validate_ingest_evidence(views)
            blocker = _canonical_source_blocker(cases)
        except ManagedHttpPolicyLifecycleError:
            with self._lock:
                self._phase = "terminal"
            raise
        except BaseException:
            with self._lock:
                self._phase = "terminal"
            raise ManagedHttpPolicyLifecycleError(
                "managed_http_policy_ingest_evidence_consumption_failed"
            ) from None
        with self._lock:
            self._phase = "canonical-source-blocked"
        raise ManagedHttpPolicyLifecycleError(blocker)

    def terminal_delete(
        self,
        *,
        bindings: FullComparisonRunBindings,
        backend_role: str,
        target_identity_sha256: str,
        pass_index: int,
    ) -> object:
        """Run exactly one admitted legacy cleanup pass and readback."""

        self._validate_binding(bindings)
        expected = tuple(
            (role, self._target(role), attempt)
            for attempt in (1, 2)
            for role in ("infinity-context", "mem0")
        )
        with self._lock:
            if self._next_delete >= len(expected):
                raise ManagedHttpPolicyLifecycleError("managed_http_policy_delete_replay")
            if (backend_role, target_identity_sha256, pass_index) != expected[self._next_delete]:
                raise ManagedHttpPolicyLifecycleError("managed_http_policy_delete_order_invalid")
            self._next_delete += 1
        client = self._client(
            backend_role,
            self._delete_transports[backend_role][pass_index - 1],
        )
        try:
            state = (
                self._delete_infinity(client, target_identity_sha256, pass_index)
                if backend_role == "infinity-context"
                else self._delete_mem0(client, target_identity_sha256, pass_index)
            )
        except ManagedHttpPolicyLifecycleError:
            raise
        except BaseException:
            raise ManagedHttpPolicyLifecycleError(
                f"managed_http_policy_{backend_role.replace('-', '_')}_delete_failed"
            ) from None
        finally:
            client.close()
        receipt = ManagedHttpPolicyDeleteReceipt(_token=_TOKEN)
        with _RECEIPT_LOCK:
            _DELETE_RECEIPTS[receipt] = state
        return receipt

    def seal_terminal_delete(
        self,
        *,
        bindings: FullComparisonRunBindings,
        managed_attestation: VerifiedManagedCompositionAttestation,
        managed_attestation_commitment_sha256: str,
        receipts: tuple[object, ...],
    ) -> object:
        """Consume four cleanup receipts and reject missing derived evidence."""

        self._validate_binding(bindings)
        _attestation(managed_attestation, managed_attestation_commitment_sha256)
        if type(receipts) is not tuple or len(receipts) != 4:
            raise ManagedHttpPolicyLifecycleError("managed_http_policy_delete_coverage_invalid")
        expected = (
            ("infinity-context", 1),
            ("mem0", 1),
            ("infinity-context", 2),
            ("mem0", 2),
        )
        with _RECEIPT_LOCK:
            states = tuple(_delete_state(receipt) for receipt in receipts)
            if any(state.owner is not self for state in states):
                raise ManagedHttpPolicyLifecycleError("managed_http_policy_delete_owner_invalid")
            if tuple((state.backend_role, state.pass_index) for state in states) != expected:
                raise ManagedHttpPolicyLifecycleError("managed_http_policy_delete_coverage_invalid")
            if any(state.phase != "live" for state in states):
                raise ManagedHttpPolicyLifecycleError("managed_http_policy_delete_receipt_replay")
            for state in states:
                state.phase = "consumed"
        if not all(
            state.canonical_absent
            for state in states
            if state.backend_role == "infinity-context"
        ):
            raise ManagedHttpPolicyLifecycleError(
                "managed_http_policy_infinity_canonical_absence_failed"
            )
        if not all(
            state.backend_verified_absent
            for state in states
            if state.backend_role == "mem0"
        ):
            raise ManagedHttpPolicyLifecycleError("managed_http_policy_mem0_absence_failed")
        raise ManagedHttpPolicyLifecycleError(
            "managed_http_policy_infinity_derived_absence_unprovable"
        )

    def aggregate_policy(
        self,
        *,
        bindings: FullComparisonRunBindings,
        managed_attestation: VerifiedManagedCompositionAttestation,
        managed_attestation_commitment_sha256: str,
        canonical_source: tuple[object, ...],
        terminal_delete: object,
    ) -> object:
        del canonical_source, terminal_delete
        self._validate_binding(bindings)
        _attestation(managed_attestation, managed_attestation_commitment_sha256)
        raise ManagedHttpPolicyLifecycleError(
            "managed_http_policy_evidence_capabilities_unavailable"
        )

    def _delete_infinity(
        self,
        client: httpx.Client,
        target: str,
        pass_index: int,
    ) -> _LegacyDeleteState:
        unique = _unique_cases(self._cases)
        if any(case.record.get("benchmark") != "locomo" for case in unique):
            raise ManagedHttpPolicyLifecycleError(
                "managed_http_policy_infinity_document_delete_unprovable"
            )
        deleted = 0
        for case in unique:
            public = _public_case(case)
            for fact in _list_facts(client, self._bindings.run_id, public):
                fact_id = _text(
                    fact.get("id"),
                    "managed_http_policy_infinity_fact_id_invalid",
                )
                if client.delete(f"/v1/facts/{fact_id}").status_code != 200:
                    raise ManagedHttpPolicyLifecycleError(
                        "managed_http_policy_infinity_delete_ack_invalid"
                    )
                deleted += 1
            if _list_facts(client, self._bindings.run_id, public):
                raise ManagedHttpPolicyLifecycleError(
                    "managed_http_policy_infinity_canonical_absence_failed"
                )
        return _LegacyDeleteState(
            self,
            "infinity-context",
            target,
            pass_index,
            len(unique),
            deleted,
            True,
            False,
            "live",
        )

    def _delete_mem0(
        self,
        client: httpx.Client,
        target: str,
        pass_index: int,
    ) -> _LegacyDeleteState:
        response = client.delete(
            "/memories",
            params={
                "user_id": mem0_benchmark_user_id(self._bindings.run_id),
                "run_id": self._bindings.run_id,
            },
        )
        payload = _object_response(response, "managed_http_policy_mem0_delete_ack_invalid")
        if set(payload) != {"deleted", "verified_absent"} or any(
            payload.get(key) is not True for key in ("deleted", "verified_absent")
        ):
            raise ManagedHttpPolicyLifecycleError(
                "managed_http_policy_mem0_delete_ack_invalid"
            )
        return _LegacyDeleteState(
            self,
            "mem0",
            target,
            pass_index,
            len(_unique_cases(self._cases)),
            1 if pass_index == 1 else 0,
            False,
            True,
            "live",
        )

    def _client(self, role: str, transport: httpx.BaseTransport | None) -> httpx.Client:
        self._ensure_deadline()
        config = self._infinity if role == "infinity-context" else self._mem0
        headers = (
            {"Authorization": f"Bearer {config.auth_token}"}
            if type(config) is ManagedInfinityHttpConfig
            else ({"X-API-Key": config.api_key} if config.api_key else None)
        )
        return httpx.Client(
            base_url=config.base_url.rstrip("/"),
            headers=headers,
            timeout=float(config.timeout_seconds),
            transport=_DeadlineTransport(
                transport or httpx.HTTPTransport(retries=0, trust_env=False),
                configured_timeout=float(config.timeout_seconds),
                deadline=self._deadline,
                clock=self._clock,
            ),
        )

    def _validate_call(
        self,
        bindings: FullComparisonRunBindings,
        cases: tuple[ManagedRunCase, ...],
    ) -> None:
        self._validate_binding(bindings)
        if type(cases) is not tuple or len(cases) != len(self._cases) or any(
            actual is not expected
            for actual, expected in zip(cases, self._cases, strict=True)
        ):
            raise ManagedHttpPolicyLifecycleError(
                "managed_http_policy_case_binding_invalid"
            )

    def _validate_binding(self, bindings: FullComparisonRunBindings) -> None:
        self._ensure_deadline()
        if bindings is not self._bindings or _binding_snapshot(bindings) != self._binding_snapshot:
            raise ManagedHttpPolicyLifecycleError("managed_http_policy_binding_changed")

    def _ensure_deadline(self) -> None:
        if _aware(self._clock(), "managed_http_policy_clock_invalid") >= self._deadline:
            raise ManagedHttpPolicyLifecycleError("managed_http_policy_deadline_expired")

    def _target(self, role: str) -> str:
        matches = tuple(
            target.target_identity_sha256
            for target in self._bindings.backend_targets
            if target.backend_role == role
        )
        if len(matches) != 1:
            raise ManagedHttpPolicyLifecycleError(
                "managed_http_policy_target_binding_invalid"
            )
        return matches[0]


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
        self._closed = False

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if self._closed:
            raise ManagedHttpPolicyLifecycleError(
                "managed_http_policy_transport_closed"
            )
        remaining = (
            self._deadline
            - _aware(self._clock(), "managed_http_policy_clock_invalid")
        ).total_seconds()
        if not math.isfinite(remaining) or remaining <= 0:
            raise ManagedHttpPolicyLifecycleError("managed_http_policy_deadline_expired")
        timeout = min(self._configured_timeout, remaining)
        request.extensions["timeout"] = {
            "connect": timeout,
            "read": timeout,
            "write": timeout,
            "pool": timeout,
        }
        return self._inner.handle_request(request)

    def close(self) -> None:
        if self._closed:
            raise ManagedHttpPolicyLifecycleError(
                "managed_http_policy_transport_double_close"
            )
        self._closed = True
        self._inner.close()


def _validate_ingest_evidence(views: object) -> None:
    if type(views) is not tuple or not views or any(
        type(view) is not ManagedHttpIngestEvidenceView for view in views
    ):
        raise ManagedHttpPolicyLifecycleError(
            "managed_http_policy_ingest_evidence_invalid"
        )
    for view in views:
        metadata = view.ingest_result.metadata
        managed = (
            metadata.get("managed_http_execution")
            if isinstance(metadata, Mapping)
            else None
        )
        if not isinstance(managed, Mapping):
            raise ManagedHttpPolicyLifecycleError(
                "managed_http_policy_ingest_provenance_missing"
            )
        blockers = managed.get("composition_blockers")
        if managed.get("credential_continuity_proven") is not True or blockers not in ([], ()):
            raise ManagedHttpPolicyLifecycleError(
                "managed_http_policy_credential_continuity_unproven"
            )


def _canonical_source_blocker(cases: tuple[ManagedRunCase, ...]) -> str:
    del cases
    return "managed_http_policy_infinity_document_chunk_identity_unavailable"


def managed_http_policy_production_blockers(
    cases: tuple[ManagedRunCase, ...],
) -> tuple[str, ...]:
    """Return stable blockers before any preparation, credential, or backend I/O."""

    if (
        type(cases) is not tuple
        or not cases
        or any(type(case) is not ManagedRunCase for case in cases)
    ):
        raise ManagedHttpPolicyLifecycleError("managed_http_policy_cases_invalid")
    blockers: list[str] = []
    blockers.append(
        "managed_http_policy_infinity_document_chunk_identity_unavailable"
    )
    if any(case.record.get("benchmark") == "locomo" for case in cases):
        blockers.append("managed_http_policy_infinity_fact_source_hash_unavailable")
    blockers.extend(
        (
            "managed_http_policy_mem0_exact_source_identity_unavailable",
            "managed_http_policy_exact_derived_identity_manifest_unavailable",
            "managed_http_policy_terminal_manifest_binding_unavailable",
        )
    )
    return tuple(blockers)


def _list_facts(client: httpx.Client, run_id: str, public: object) -> list[dict[str, object]]:
    response = client.get(
        "/v1/facts",
        params={
            "space_slug": f"memory-comparison-{_safe_slug(run_id)}",
            "memory_scope_external_ref": public.memory_scope_external_ref,
            "thread_external_ref": public.thread_external_ref,
            "status": "active",
            "limit": 500,
        },
    )
    payload = _object_response(
        response,
        "managed_http_policy_infinity_facts_readback_invalid",
    )
    data = payload.get("data")
    if not isinstance(data, list) or any(not isinstance(item, Mapping) for item in data):
        raise ManagedHttpPolicyLifecycleError(
            "managed_http_policy_infinity_facts_readback_invalid"
        )
    return [dict(item) for item in data]


def _object_response(response: httpx.Response, code: str) -> dict[str, object]:
    if response.status_code != 200:
        raise ManagedHttpPolicyLifecycleError(code)
    try:
        payload = response.json()
    except ValueError:
        raise ManagedHttpPolicyLifecycleError(code) from None
    if not isinstance(payload, Mapping):
        raise ManagedHttpPolicyLifecycleError(code)
    return dict(payload)


def _public_case(case: ManagedRunCase) -> object:
    return _reconstruct_managed_corpus_case(
        case.record,
        case_id=case.case_id,
        question="managed-policy-cleanup",
        temporal_context={},
    )


def _unique_cases(cases: tuple[ManagedRunCase, ...]) -> tuple[ManagedRunCase, ...]:
    result: list[ManagedRunCase] = []
    seen: set[str] = set()
    for case in cases:
        if case.corpus_id not in seen:
            seen.add(case.corpus_id)
            result.append(case)
    return tuple(result)


def _delete_state(value: object) -> _LegacyDeleteState:
    if type(value) is not ManagedHttpPolicyDeleteReceipt:
        raise ManagedHttpPolicyLifecycleError(
            "managed_http_policy_delete_receipt_type_invalid"
        )
    state = _DELETE_RECEIPTS.get(value)
    if state is None:
        raise ManagedHttpPolicyLifecycleError(
            "managed_http_policy_delete_receipt_unknown"
        )
    return state


def _attestation(value: object, commitment: object) -> None:
    if type(value) is not VerifiedManagedCompositionAttestation:
        raise ManagedHttpPolicyLifecycleError("managed_http_policy_attestation_invalid")
    _digest(commitment, "managed_http_policy_attestation_commitment_invalid")


def _two_transports(value: object) -> None:
    if type(value) is not tuple or len(value) != 2 or any(
        item is not None and type(item) is not httpx.MockTransport for item in value
    ):
        raise ManagedHttpPolicyLifecycleError(
            "managed_http_policy_delete_transports_invalid"
        )


def _binding_snapshot(bindings: FullComparisonRunBindings) -> str:
    payload = {
        "run_id": bindings.run_id,
        "profile_id": bindings.profile_id,
        "scope": bindings.scope,
        "binding": bindings.binding_commitment_sha256,
        "targets": [
            [target.backend_role, target.target_identity_sha256]
            for target in bindings.backend_targets
        ],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _text(value: object, code: str) -> str:
    if type(value) is not str or not value or value != value.strip() or len(value) > 500:
        raise ManagedHttpPolicyLifecycleError(code)
    return value


def _digest(value: object, code: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise ManagedHttpPolicyLifecycleError(code)
    return value


def _aware(value: object, code: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ManagedHttpPolicyLifecycleError(code)
    return value


def _safe_slug(value: str) -> str:
    return "".join(
        char if char.isalnum() or char == "-" else "-" for char in value.lower()
    )[:80]


def managed_http_policy_lifecycle_implementation_sha256() -> str:
    payload = {
        "schema": "managed-comparison-http-policy-fail-closed.v1",
        "ingest": "exact-target-major-one-use",
        "canonical_source": "no-telemetry-elevation",
        "delete": "two-pass-distinct-owned-transport",
        "retries": 0,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


__all__ = (
    "MANAGED_HTTP_POLICY_ADAPTER_ID",
    "ManagedComparisonHttpPolicyLifecycleAdapter",
    "ManagedHttpPolicyDeleteReceipt",
    "ManagedHttpPolicyLifecycleError",
    "managed_http_policy_production_blockers",
    "managed_http_policy_lifecycle_implementation_sha256",
)

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
from infinity_context_server.memory_comparison_managed_http_derived_evidence import (
    ManagedDerivedEvidenceHttpClient,
)
from infinity_context_server.memory_comparison_managed_http_exact_cleanup import (
    ManagedExactCleanupObservation,
    ManagedInfinityExactCleanupCoordinator,
)
from infinity_context_server.memory_comparison_managed_http_execution import (
    ManagedInfinityHttpConfig,
    ManagedMem0HttpConfig,
)
from infinity_context_server.memory_comparison_managed_http_lifecycle import (
    ManagedHttpIngestEvidenceView,
    consume_managed_http_ingest_receipts,
)
from infinity_context_server.memory_comparison_managed_http_policy_requirements import (
    ManagedDerivedPresenceObservation,
    managed_ingest_identity_manifest_sha256,
)
from infinity_context_server.memory_comparison_managed_ingest_manifest import (
    ManagedCorpusIngestIdentity,
    parse_managed_ingest_identity_manifests,
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


@final
class ManagedHttpPolicyCanonicalSourceReceipt:
    """Opaque per-case handle over one immutable corpus evidence bundle."""

    __slots__ = ("__weakref__",)

    def __init__(self, *, _token: object) -> None:
        if _token is not _TOKEN:
            raise ManagedHttpPolicyLifecycleError("managed_http_policy_canonical_receipt_forged")

    def __repr__(self) -> str:
        return "ManagedHttpPolicyCanonicalSourceReceipt(<opaque>)"

    def __reduce__(self) -> object:
        raise TypeError("ManagedHttpPolicyCanonicalSourceReceipt is nonserializable")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedHttpPolicyCanonicalSourceReceipt is final")


@dataclass(frozen=True, slots=True)
class _CorpusEvidence:
    bundle: ManagedCorpusIngestIdentity
    presence: ManagedDerivedPresenceObservation


@dataclass(slots=True)
class _CanonicalReceiptState:
    owner: object
    ordinal: int
    case_id: str
    corpus_id: str
    run_id: str
    binding_commitment_sha256: str
    infinity_target_identity_sha256: str
    mem0_target_identity_sha256: str
    ingest_manifest_sha256: str
    mem0_created_memory_ids: tuple[str, ...]
    source_pairs: tuple[tuple[str, str], ...]
    phase: str


@dataclass(slots=True)
class _LegacyDeleteState:
    owner: object
    run_id: str
    binding_commitment_sha256: str
    backend_role: str
    target_identity_sha256: str
    pass_index: int
    source_scope_count: int
    deleted_count: int
    canonical_absent: bool
    backend_verified_absent: bool
    corpus_manifest_sha256: tuple[str, ...]
    mem0_created_memory_ids: tuple[str, ...]
    source_pairs: tuple[tuple[str, str], ...]
    phase: str


_DELETE_RECEIPTS: weakref.WeakKeyDictionary[ManagedHttpPolicyDeleteReceipt, _LegacyDeleteState] = (
    weakref.WeakKeyDictionary()
)
_CANONICAL_RECEIPTS: weakref.WeakKeyDictionary[
    ManagedHttpPolicyCanonicalSourceReceipt, _CanonicalReceiptState
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
        infinity_derived_transport_factory: Callable[[], httpx.BaseTransport] | None = None,
        infinity_cleanup_transport_factory: Callable[[], httpx.BaseTransport] | None = None,
        mem0_delete_transport_factory: Callable[[], httpx.BaseTransport] | None = None,
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
            raise ManagedHttpPolicyLifecycleError("managed_http_policy_preflight_request_invalid")
        transport_factories = {
            "infinity-derived": infinity_derived_transport_factory,
            "infinity-cleanup": infinity_cleanup_transport_factory,
            "mem0-delete": mem0_delete_transport_factory,
        }
        if any(
            factory is not None and not callable(factory)
            for factory in transport_factories.values()
        ):
            raise ManagedHttpPolicyLifecycleError("managed_http_policy_transport_factory_invalid")
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
            raise ManagedHttpPolicyLifecycleError("managed_http_policy_credential_material_invalid")
        targets = {
            item.backend_role: item.target_identity_sha256 for item in bindings.backend_targets
        }
        if targets != {
            "infinity-context": infinity.target_identity_sha256,
            "mem0": mem0.target_identity_sha256,
        }:
            raise ManagedHttpPolicyLifecycleError("managed_http_policy_target_binding_invalid")
        self._bindings = bindings
        self._binding_snapshot = _binding_snapshot(bindings)
        self._cases = cases
        self._preflight_request = preflight_request
        self._deadline = checked_deadline
        self._infinity = infinity
        self._mem0 = mem0
        self._transport_factories = transport_factories
        self._owned_transports: list[httpx.BaseTransport] = []
        self._clock = clock
        self._derived_evidence = ManagedDerivedEvidenceHttpClient(
            config=infinity,
            transport_factory=lambda: self._new_transport("infinity-derived"),
        )
        self._exact_cleanup = ManagedInfinityExactCleanupCoordinator(
            config=infinity,
            derived_evidence=self._derived_evidence,
            transport_factory=lambda: self._new_transport("infinity-cleanup"),
        )
        self._corpora: tuple[_CorpusEvidence, ...] = ()
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
        """Seal immutable exact corpus evidence and return one receipt per case."""

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
            bundles = parse_managed_ingest_identity_manifests(views)
            evidence = self._observe_corpora(bundles)
            by_corpus = {item.bundle.corpus_id: item for item in evidence}
            if set(by_corpus) != {case.corpus_id for case in cases}:
                raise ManagedHttpPolicyLifecycleError("managed_http_policy_corpus_coverage_invalid")
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
        receipts: list[object] = []
        with self._lock:
            self._corpora = evidence
            for ordinal, case in enumerate(cases):
                corpus = by_corpus[case.corpus_id]
                manifest = corpus.bundle.manifest
                receipt = ManagedHttpPolicyCanonicalSourceReceipt(_token=_TOKEN)
                state = _CanonicalReceiptState(
                    owner=self,
                    ordinal=ordinal,
                    case_id=case.case_id,
                    corpus_id=case.corpus_id,
                    run_id=bindings.run_id,
                    binding_commitment_sha256=bindings.binding_commitment_sha256,
                    infinity_target_identity_sha256=(corpus.bundle.infinity_target_identity_sha256),
                    mem0_target_identity_sha256=(corpus.bundle.mem0_target_identity_sha256),
                    ingest_manifest_sha256=managed_ingest_identity_manifest_sha256(
                        manifest, corpus.bundle.scope
                    ),
                    mem0_created_memory_ids=manifest.mem0_created_memory_ids,
                    source_pairs=tuple(
                        zip(
                            manifest.mem0_source_ids,
                            manifest.mem0_source_sha256,
                            strict=True,
                        )
                    ),
                    phase="live",
                )
                with _RECEIPT_LOCK:
                    _CANONICAL_RECEIPTS[receipt] = state
                receipts.append(receipt)
            self._phase = "canonical-source-sealed"
        return tuple(receipts)

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
        client = None
        try:
            if backend_role == "infinity-context":
                state = self._delete_infinity(target_identity_sha256, pass_index)
            else:
                client = self._client(backend_role)
                state = self._delete_mem0(client, target_identity_sha256, pass_index)
        except ManagedHttpPolicyLifecycleError:
            raise
        except BaseException:
            raise ManagedHttpPolicyLifecycleError(
                f"managed_http_policy_{backend_role.replace('-', '_')}_delete_failed"
            ) from None
        finally:
            if client is not None:
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
        """Consume four receipts only after exact two-pass coverage validation."""

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
            manifests = self._corpus_manifest_sha256()
            mem0_ids = self._mem0_created_memory_ids()
            source_pairs = self._source_pairs()
            if any(
                state.target_identity_sha256 != self._target(state.backend_role)
                or state.run_id != self._bindings.run_id
                or state.binding_commitment_sha256 != self._bindings.binding_commitment_sha256
                or state.source_scope_count != len(self._corpora)
                or state.corpus_manifest_sha256 != manifests
                or state.mem0_created_memory_ids != mem0_ids
                or state.source_pairs != source_pairs
                for state in states
            ):
                raise ManagedHttpPolicyLifecycleError(
                    "managed_http_policy_terminal_manifest_binding_invalid"
                )
            infinity_states = tuple(
                state for state in states if state.backend_role == "infinity-context"
            )
            mem0_states = tuple(state for state in states if state.backend_role == "mem0")
            if not all(
                state.canonical_absent and state.backend_verified_absent
                for state in infinity_states
            ):
                raise ManagedHttpPolicyLifecycleError(
                    "managed_http_policy_infinity_exact_absence_failed"
                )
            if not all(state.backend_verified_absent for state in mem0_states):
                raise ManagedHttpPolicyLifecycleError("managed_http_policy_mem0_absence_failed")
            for state in states:
                state.phase = "consumed"
        return object()

    def aggregate_policy(
        self,
        *,
        bindings: FullComparisonRunBindings,
        managed_attestation: VerifiedManagedCompositionAttestation,
        managed_attestation_commitment_sha256: str,
        canonical_source: tuple[object, ...],
        terminal_delete: object,
    ) -> object:
        self._validate_binding(bindings)
        _attestation(managed_attestation, managed_attestation_commitment_sha256)
        del canonical_source, terminal_delete
        raise ManagedHttpPolicyLifecycleError(
            "managed_http_policy_evidence_capabilities_unavailable"
        )

    def _delete_infinity(
        self,
        target: str,
        pass_index: int,
    ) -> _LegacyDeleteState:
        if not self._corpora:
            raise ManagedHttpPolicyLifecycleError(
                "managed_http_policy_exact_cleanup_state_unavailable"
            )
        observations = tuple(
            self._exact_cleanup.cleanup(
                scope=corpus.bundle.scope,
                manifest=corpus.bundle.manifest,
                presence=corpus.presence,
                pass_index=pass_index,
            )
            for corpus in self._corpora
        )
        if any(
            type(item) is not ManagedExactCleanupObservation
            or item.lifecycle_target_identity_sha256 != target
            or item.corpus_id != corpus.bundle.corpus_id
            or item.pass_index != pass_index
            or not item.verified_absent
            for item, corpus in zip(observations, self._corpora, strict=True)
        ):
            raise ManagedHttpPolicyLifecycleError(
                "managed_http_policy_infinity_exact_cleanup_invalid"
            )
        return _LegacyDeleteState(
            self,
            self._bindings.run_id,
            self._bindings.binding_commitment_sha256,
            "infinity-context",
            target,
            pass_index,
            len(self._corpora),
            sum(len(item.canonical) for item in observations),
            True,
            all(
                (item.qdrant is None or item.qdrant.verified_absent)
                and (item.graphiti is None or item.graphiti.verified_absent)
                for item in observations
            ),
            self._corpus_manifest_sha256(),
            self._mem0_created_memory_ids(),
            self._source_pairs(),
            "live",
        )

    def _delete_mem0(
        self,
        client: httpx.Client,
        target: str,
        pass_index: int,
    ) -> _LegacyDeleteState:
        if not self._corpora:
            raise ManagedHttpPolicyLifecycleError(
                "managed_http_policy_exact_cleanup_state_unavailable"
            )
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
            raise ManagedHttpPolicyLifecycleError("managed_http_policy_mem0_delete_ack_invalid")
        return _LegacyDeleteState(
            self,
            self._bindings.run_id,
            self._bindings.binding_commitment_sha256,
            "mem0",
            target,
            pass_index,
            len(self._corpora),
            len(self._mem0_created_memory_ids()) if pass_index == 1 else 0,
            False,
            True,
            self._corpus_manifest_sha256(),
            self._mem0_created_memory_ids(),
            self._source_pairs(),
            "live",
        )

    def _client(self, role: str) -> httpx.Client:
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
                self._new_transport("mem0-delete"),
                configured_timeout=float(config.timeout_seconds),
                deadline=self._deadline,
                clock=self._clock,
            ),
        )

    def _observe_corpora(
        self,
        bundles: tuple[ManagedCorpusIngestIdentity, ...],
    ) -> tuple[_CorpusEvidence, ...]:
        if not bundles or any(
            bundle.infinity_target_identity_sha256 != self._infinity.target_identity_sha256
            or bundle.mem0_target_identity_sha256 != self._mem0.target_identity_sha256
            for bundle in bundles
        ):
            raise ManagedHttpPolicyLifecycleError(
                "managed_http_policy_ingest_target_binding_invalid"
            )
        return tuple(
            _CorpusEvidence(
                bundle=bundle,
                presence=self._derived_evidence.observe_presence(
                    scope=bundle.scope,
                    manifest=bundle.manifest,
                ),
            )
            for bundle in bundles
        )

    def _corpus_manifest_sha256(self) -> tuple[str, ...]:
        return tuple(
            managed_ingest_identity_manifest_sha256(
                corpus.bundle.manifest,
                corpus.bundle.scope,
            )
            for corpus in self._corpora
        )

    def _mem0_created_memory_ids(self) -> tuple[str, ...]:
        identities = tuple(
            identity
            for corpus in self._corpora
            for identity in corpus.bundle.manifest.mem0_created_memory_ids
        )
        if not identities or len(set(identities)) != len(identities):
            raise ManagedHttpPolicyLifecycleError(
                "managed_http_policy_mem0_identity_binding_invalid"
            )
        return identities

    def _source_pairs(self) -> tuple[tuple[str, str], ...]:
        pairs = tuple(
            pair
            for corpus in self._corpora
            for pair in zip(
                corpus.bundle.manifest.mem0_source_ids,
                corpus.bundle.manifest.mem0_source_sha256,
                strict=True,
            )
        )
        if not pairs:
            raise ManagedHttpPolicyLifecycleError("managed_http_policy_mem0_source_binding_invalid")
        return pairs

    def _new_transport(self, role: str) -> httpx.BaseTransport:
        factory = self._transport_factories[role]
        try:
            transport = (
                httpx.HTTPTransport(retries=0, trust_env=False) if factory is None else factory()
            )
        except BaseException:
            raise ManagedHttpPolicyLifecycleError(
                "managed_http_policy_transport_factory_failed"
            ) from None
        if not isinstance(transport, httpx.BaseTransport):
            raise ManagedHttpPolicyLifecycleError("managed_http_policy_transport_factory_invalid")
        with self._lock:
            if any(item is transport for item in self._owned_transports):
                raise ManagedHttpPolicyLifecycleError(
                    "managed_http_policy_transport_ownership_invalid"
                )
            self._owned_transports.append(transport)
        return transport

    def _validate_call(
        self,
        bindings: FullComparisonRunBindings,
        cases: tuple[ManagedRunCase, ...],
    ) -> None:
        self._validate_binding(bindings)
        if (
            type(cases) is not tuple
            or len(cases) != len(self._cases)
            or any(
                actual is not expected for actual, expected in zip(cases, self._cases, strict=True)
            )
        ):
            raise ManagedHttpPolicyLifecycleError("managed_http_policy_case_binding_invalid")

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
            raise ManagedHttpPolicyLifecycleError("managed_http_policy_target_binding_invalid")
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
            raise ManagedHttpPolicyLifecycleError("managed_http_policy_transport_closed")
        remaining = (
            self._deadline - _aware(self._clock(), "managed_http_policy_clock_invalid")
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
            raise ManagedHttpPolicyLifecycleError("managed_http_policy_transport_double_close")
        self._closed = True
        self._inner.close()


def _validate_ingest_evidence(views: object) -> None:
    if (
        type(views) is not tuple
        or not views
        or any(type(view) is not ManagedHttpIngestEvidenceView for view in views)
    ):
        raise ManagedHttpPolicyLifecycleError("managed_http_policy_ingest_evidence_invalid")
    for view in views:
        metadata = view.ingest_result.metadata
        managed = metadata.get("managed_http_execution") if isinstance(metadata, Mapping) else None
        if not isinstance(managed, Mapping):
            raise ManagedHttpPolicyLifecycleError("managed_http_policy_ingest_provenance_missing")
        blockers = managed.get("composition_blockers")
        if managed.get("credential_continuity_proven") is not True or blockers not in ([], ()):
            raise ManagedHttpPolicyLifecycleError(
                "managed_http_policy_credential_continuity_unproven"
            )


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
    return (
        "managed_http_policy_mem0_exact_source_identity_unavailable",
        "managed_http_policy_evidence_capabilities_unavailable",
    )


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


def _delete_state(value: object) -> _LegacyDeleteState:
    if type(value) is not ManagedHttpPolicyDeleteReceipt:
        raise ManagedHttpPolicyLifecycleError("managed_http_policy_delete_receipt_type_invalid")
    state = _DELETE_RECEIPTS.get(value)
    if state is None:
        raise ManagedHttpPolicyLifecycleError("managed_http_policy_delete_receipt_unknown")
    return state


def _attestation(value: object, commitment: object) -> None:
    if type(value) is not VerifiedManagedCompositionAttestation:
        raise ManagedHttpPolicyLifecycleError("managed_http_policy_attestation_invalid")
    _digest(commitment, "managed_http_policy_attestation_commitment_invalid")


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


def _digest(value: object, code: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise ManagedHttpPolicyLifecycleError(code)
    return value


def _aware(value: object, code: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ManagedHttpPolicyLifecycleError(code)
    return value


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

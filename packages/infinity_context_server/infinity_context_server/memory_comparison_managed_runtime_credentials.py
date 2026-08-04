"""One-run credential continuity for managed comparison composition.

Backend bindings are authority-keyed HMAC commitments, so public preflight
material cannot be used for offline credential guessing. The existing
subscription and Mem0 probe adapters expose deterministic SHA-256 bindings;
those exact values are retained as loopback bearer continuity until those
adapter contracts accept opaque HMAC bindings.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import re
import secrets
import threading
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import final

import httpx

from infinity_context_server.memory_comparison_managed_http_execution import (
    ManagedInfinityHttpConfig,
    ManagedMem0HttpConfig,
)
from infinity_context_server.memory_comparison_managed_mem0_auth import (
    MANAGED_MEM0_DATA_PLANE_AUTH_API_KEY,
    MANAGED_MEM0_DATA_PLANE_AUTH_NONE,
    managed_mem0_data_plane_auth_mode,
)
from infinity_context_server.memory_comparison_managed_preflight import (
    MANAGED_PREFLIGHT_PROVIDER_SUBSCRIPTION_RUNTIME,
    ManagedBackendEndpoint,
    ManagedCredentialBinding,
    ManagedPreflightRequest,
    validate_managed_preflight,
)
from infinity_context_server.memory_comparison_managed_runtime_credentials_capability import (
    ManagedBackendCredentialMaterial,
    _issue_backend_credential_material,
)
from infinity_context_server.memory_comparison_managed_runtime_credentials_integrity import (
    adapter_credential_binding,
    hmac_sha256,
    managed_preflight_request_snapshot,
    runtime_authority_integrity,
    secret_commitments,
    validate_mock_transport,
)
from infinity_context_server.memory_comparison_managed_runtime_credentials_models import (
    ManagedCredentialPreflightMaterial,
    ManagedRuntimeCredentialError,
)
from infinity_context_server.memory_comparison_managed_runtime_credentials_targets import (
    _normalized_backend,
)
from infinity_context_server.memory_comparison_provider_provenance import (
    ProviderRouteAttestation,
)
from infinity_context_server.memory_comparison_subscription_chat import (
    SUBSCRIPTION_CHAT_ENDPOINT_PATH,
    SUBSCRIPTION_RUNTIME_TRANSPORT_EVIDENCE,
    SUBSCRIPTION_RUNTIME_TRUST,
    SubscriptionRuntimeChatCompletions,
    _validated_loopback_origin,
)
from infinity_context_server.memory_comparison_subscription_live_probe import (
    run_subscription_runtime_live_probe,
)
from infinity_context_server.memory_comparison_subscription_probe import (
    SubscriptionRuntimeProbeObservation,
    VerifiedSubscriptionRuntimeProbe,
    inspect_verified_subscription_runtime_probe,
)

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_MAX_SECRET_BYTES = 16_384
_TOKEN = object()


@dataclass(slots=True)
class _AuthorityState:
    run_id: str
    issued_at: datetime
    deadline: datetime
    request_timeout_seconds: float
    infinity_origin: str
    mem0_origin: str
    subscription_origin: str
    infinity_secret: str = field(repr=False)
    mem0_secret: str | None = field(repr=False)
    mem0_data_plane_auth_mode: str
    probe_secret: str = field(repr=False)
    subscription_secret: str = field(repr=False)
    binding_key: bytes = field(repr=False)
    secret_commitments: tuple[str, str, str, str] = field(repr=False)
    material: ManagedCredentialPreflightMaterial
    integrity: str = field(repr=False)
    preflight_request: ManagedPreflightRequest | None = field(default=None, repr=False)
    preflight_snapshot: bytes | None = field(default=None, repr=False)
    preflight_commitment: str | None = field(default=None, repr=False)
    bound_request_identity: int | None = None
    root_phase: str = "pending"
    readiness_phase: str = "pending"
    execution_phase: str = "pending"
    backend_phase: str = "pending"
    readiness_claim: ManagedSubscriptionReadinessClaim | None = field(
        default=None, repr=False
    )


@final
class ManagedSubscriptionReadinessClaim:
    """Opaque owner of the sole retry-free readiness adapter and attempt."""

    __slots__ = (
        "__adapter",
        "__authority_state",
        "__lock",
        "__phase",
        "__proof",
        "__proof_observation",
    )

    def __init__(
        self,
        *,
        adapter: SubscriptionRuntimeChatCompletions,
        authority_state: _AuthorityState,
        _token: object,
    ) -> None:
        if _token is not _TOKEN or type(adapter) is not SubscriptionRuntimeChatCompletions:
            _fail("managed_credentials_configuration_invalid")
        self.__adapter = adapter
        self.__authority_state = authority_state
        self.__lock = threading.Lock()
        self.__phase = "pending"
        self.__proof: VerifiedSubscriptionRuntimeProbe | None = None
        self.__proof_observation: SubscriptionRuntimeProbeObservation | None = None

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedSubscriptionReadinessClaim is final")

    def __repr__(self) -> str:
        return "ManagedSubscriptionReadinessClaim(<sealed-one-shot>)"

    @property
    def route_attestation(self) -> ProviderRouteAttestation:
        return self.__adapter.route_attestation

    def run(
        self,
        *,
        model: str,
        clock: Callable[[], datetime],
    ) -> VerifiedSubscriptionRuntimeProbe:
        """Perform exactly one readiness attempt and retain its opaque proof."""

        with self.__lock:
            if (
                self.__phase != "pending"
                or self.__authority_state.readiness_phase != "issued"
            ):
                self.__phase = "terminal"
                self.__authority_state.readiness_phase = "terminal"
                _fail("managed_credentials_terminal")
            self.__phase = "active"
            self.__authority_state.readiness_phase = "active"
        try:
            state = self.__authority_state
            now = _aware(clock(), "managed_credentials_readiness_failed")
            request = state.preflight_request
            if now < state.issued_at or now >= state.deadline:
                _fail("managed_credentials_expired")
            if (
                request is None
                or model != request.answerer_model
                or model != request.judge_model
                or self.__adapter.request_timeout_seconds
                != state.request_timeout_seconds
                or self.__adapter.route_attestation != state.material.provider_route
            ):
                _fail("managed_credentials_context_mismatch")
            proof = run_subscription_runtime_live_probe(
                self.__adapter,
                expected_route=state.material.provider_route,
                model=model,
                clock=clock,
            )
            if type(proof) is not VerifiedSubscriptionRuntimeProbe:
                _fail("managed_credentials_readiness_failed")
            observation = inspect_verified_subscription_runtime_probe(
                proof,
                now=_aware(clock(), "managed_credentials_readiness_failed"),
            )
            if (
                type(observation) is not SubscriptionRuntimeProbeObservation
                or observation.model != model
                or observation.route != self.__adapter.route_attestation
                or observation.checked_at < state.issued_at
                or observation.checked_at >= state.deadline
            ):
                _fail("managed_credentials_readiness_failed")
        except BaseException as exc:
            with self.__lock:
                self.__phase = "terminal"
                self.__authority_state.readiness_phase = "terminal"
            with suppress(Exception):
                self.__adapter.close()
            if isinstance(exc, ManagedRuntimeCredentialError):
                raise
            raise ManagedRuntimeCredentialError(
                "managed_credentials_readiness_failed"
            ) from None
        with self.__lock:
            if (
                self.__phase != "active"
                or self.__authority_state.readiness_phase != "active"
            ):
                self.__phase = "terminal"
                self.__authority_state.readiness_phase = "terminal"
                _fail("managed_credentials_terminal")
            self.__phase = "completed"
            self.__authority_state.readiness_phase = "completed"
            self.__proof = proof
            self.__proof_observation = observation
            return proof

    def _is_completed_for(self, state: _AuthorityState) -> bool:
        with self.__lock:
            return self._is_completed_for_unlocked(state)

    def _completed_probe_for(
        self,
        state: _AuthorityState,
    ) -> tuple[VerifiedSubscriptionRuntimeProbe, SubscriptionRuntimeProbeObservation] | None:
        with self.__lock:
            if not self._is_completed_for_unlocked(state):
                return None
            proof = self.__proof
            observation = self.__proof_observation
            if (
                type(proof) is not VerifiedSubscriptionRuntimeProbe
                or type(observation) is not SubscriptionRuntimeProbeObservation
            ):
                return None
            return proof, observation

    def _is_completed_for_unlocked(self, state: _AuthorityState) -> bool:
        return (
            self.__authority_state is state
            and self.__phase == "completed"
            and state.readiness_phase == "completed"
        )

    def __copy__(self) -> object:
        raise TypeError("managed subscription readiness claim is noncopyable")

    def __deepcopy__(self, memo: object) -> object:
        del memo
        raise TypeError("managed subscription readiness claim is noncopyable")

    def __reduce__(self) -> object:
        raise TypeError("managed subscription readiness claim is nonserializable")

    def __reduce_ex__(self, protocol: int) -> object:
        del protocol
        raise TypeError("managed subscription readiness claim is nonserializable")

    def __getstate__(self) -> object:
        raise TypeError("managed subscription readiness claim is nonserializable")


@final
class ManagedRuntimeCredentialAuthority:
    """Final one-run authority binding admission facts to concrete credentials."""

    __slots__ = ("__lock", "__state")

    def __init__(self, *, state: _AuthorityState, _token: object) -> None:
        if _token is not _TOKEN or type(state) is not _AuthorityState:
            _fail("managed_credentials_configuration_invalid")
        self.__state = state
        self.__lock = threading.RLock()

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedRuntimeCredentialAuthority is final")

    def __repr__(self) -> str:
        return "ManagedRuntimeCredentialAuthority(<sealed-one-run>)"

    def _inspect_completed_context(
        self,
        **context: object,
    ) -> str:
        from infinity_context_server.memory_comparison_managed_runtime_credentials_context import (  # noqa: PLC0415
            _inspect_completed_context_for_authority,
        )

        with self.__lock:
            self._require_integrity_locked()
            state = self.__state
            self._require_static_context_locked(
                expected_request=context["expected_request"],
                run_id=context["run_id"],
                subscription_origin=state.subscription_origin,
                deadline=context["deadline"],
            )
            self._require_bound_request_locked(context["expected_request"])
            return _inspect_completed_context_for_authority(
                self,
                state,
                readiness_claim=context["readiness_claim"],
                expected_request=context["expected_request"],
                expected_probe=context["expected_probe"],
            )

    def preflight_material(self) -> ManagedCredentialPreflightMaterial:
        """Return the same immutable public material without consuming a lane."""

        with self.__lock:
            self._require_integrity_locked()
            if self.__state.root_phase == "terminal":
                _fail("managed_credentials_terminal")
            return self.__state.material

    def bind_preflight_request(
        self,
        request: ManagedPreflightRequest,
        *,
        run_id: str,
        deadline: datetime,
    ) -> None:
        """Bind the exact request assembled from this authority's public objects."""

        with self.__lock:
            try:
                self._require_integrity_locked()
                state = self.__state
                if state.root_phase != "pending":
                    _fail("managed_credentials_terminal")
                state.root_phase = "active"
                self._require_static_context_locked(
                    expected_request=request,
                    run_id=run_id,
                    subscription_origin=state.subscription_origin,
                    deadline=deadline,
                )
                result = validate_managed_preflight(request)
                if result.ready is not True:
                    _fail("managed_credentials_preflight_invalid")
                snapshot = managed_preflight_request_snapshot(request, result)
                state.preflight_request = request
                state.preflight_snapshot = snapshot
                state.preflight_commitment = hmac_sha256(state.binding_key, snapshot)
                state.bound_request_identity = id(request)
                state.root_phase = "bound"
                state.integrity = runtime_authority_integrity(state)
            except BaseException as exc:
                self._terminal_all_locked()
                if isinstance(exc, ManagedRuntimeCredentialError):
                    raise
                raise ManagedRuntimeCredentialError(
                    "managed_credentials_preflight_invalid"
                ) from None

    def issue_subscription_readiness_claim(
        self,
        *,
        expected_request: ManagedPreflightRequest,
        run_id: str,
        subscription_origin: str,
        deadline: datetime,
        now: datetime,
        transport: httpx.BaseTransport | None = None,
    ) -> ManagedSubscriptionReadinessClaim:
        """Issue one pristine adapter-owned readiness claim."""

        self._reserve_lane("readiness")
        adapter: SubscriptionRuntimeChatCompletions | None = None
        try:
            with self.__lock:
                self._require_context_locked(
                    expected_request=expected_request,
                    run_id=run_id,
                    subscription_origin=subscription_origin,
                    deadline=deadline,
                    now=now,
                )
                state = self.__state
                validate_mock_transport(transport)
                adapter = SubscriptionRuntimeChatCompletions(
                    origin=state.subscription_origin,
                    bearer_token=state.subscription_secret,
                    timeout_seconds=state.request_timeout_seconds,
                    max_retries=0,
                    transport=transport,
                )
                if adapter.route_attestation != state.material.provider_route:
                    _fail("managed_credentials_integrity_failed")
                claim = ManagedSubscriptionReadinessClaim(
                    adapter=adapter,
                    authority_state=state,
                    _token=_TOKEN,
                )
                if state.readiness_phase != "active":
                    _fail("managed_credentials_terminal")
                state.readiness_claim = claim
                state.readiness_phase = "issued"
                return claim
        except BaseException as exc:
            if adapter is not None:
                with suppress(Exception):
                    adapter.close()
            self._terminal_lane("readiness")
            if isinstance(exc, ManagedRuntimeCredentialError):
                raise
            raise ManagedRuntimeCredentialError(
                "managed_credentials_configuration_invalid"
            ) from None

    def issue_subscription_execution_adapter(
        self,
        *,
        readiness_claim: ManagedSubscriptionReadinessClaim,
        expected_request: ManagedPreflightRequest,
        run_id: str,
        subscription_origin: str,
        deadline: datetime,
        now: datetime,
        transport: httpx.BaseTransport | None = None,
    ) -> SubscriptionRuntimeChatCompletions:
        """Issue the distinct retry-free adapter used by ordinary execution."""

        self._reserve_lane("execution")
        adapter: SubscriptionRuntimeChatCompletions | None = None
        try:
            with self.__lock:
                trusted_now = self._require_context_locked(
                    expected_request=expected_request,
                    run_id=run_id,
                    subscription_origin=subscription_origin,
                    deadline=deadline,
                    now=now,
                )
                state = self.__state
                if (
                    type(readiness_claim) is not ManagedSubscriptionReadinessClaim
                    or readiness_claim is not state.readiness_claim
                    or not readiness_claim._is_completed_for(state)
                ):
                    _fail("managed_credentials_context_mismatch")
                validate_mock_transport(transport)
                adapter = SubscriptionRuntimeChatCompletions(
                    origin=state.subscription_origin,
                    bearer_token=state.subscription_secret,
                    timeout_seconds=_remaining_execution_timeout_seconds(
                        configured_timeout_seconds=state.request_timeout_seconds,
                        deadline=state.deadline,
                        now=trusted_now,
                    ),
                    max_retries=0,
                    transport=transport,
                )
                if adapter.route_attestation != state.material.provider_route:
                    _fail("managed_credentials_integrity_failed")
                if state.execution_phase != "active":
                    _fail("managed_credentials_terminal")
                state.execution_phase = "issued"
                return adapter
        except BaseException as exc:
            if adapter is not None:
                with suppress(Exception):
                    adapter.close()
            self._terminal_lane("execution")
            if isinstance(exc, ManagedRuntimeCredentialError):
                raise
            raise ManagedRuntimeCredentialError(
                "managed_credentials_configuration_invalid"
            ) from None

    def issue_backend_credential_material(
        self,
        *,
        expected_request: ManagedPreflightRequest,
        run_id: str,
        infinity_origin: str,
        mem0_origin: str,
        deadline: datetime,
        now: datetime,
        infinity_transport: httpx.BaseTransport | None = None,
        mem0_transport: httpx.BaseTransport | None = None,
        mem0_send_timestamps: bool = False,
    ) -> ManagedBackendCredentialMaterial:
        """Issue exact HTTP configs and private Mem0 probe material once."""

        self._reserve_lane("backend")
        try:
            with self.__lock:
                state = self.__state
                self._require_context_locked(
                    expected_request=expected_request,
                    run_id=run_id,
                    subscription_origin=state.subscription_origin,
                    deadline=deadline,
                    now=now,
                )
                if (
                    _normalized_backend("infinity-context", infinity_origin)[0]
                    != state.infinity_origin
                    or _normalized_backend("mem0", mem0_origin)[0] != state.mem0_origin
                ):
                    _fail("managed_credentials_context_mismatch")
                validate_mock_transport(infinity_transport)
                validate_mock_transport(mem0_transport)
                if (
                    infinity_transport is not None
                    and mem0_transport is not None
                    and infinity_transport is mem0_transport
                ):
                    _fail("managed_credentials_configuration_invalid")
                if type(mem0_send_timestamps) is not bool:
                    _fail("managed_credentials_configuration_invalid")
                self._require_secret_continuity_locked()
                infinity_target, mem0_target = (
                    item.target for item in state.material.backend_endpoints
                )
                infinity = ManagedInfinityHttpConfig(
                    target_identity_sha256=infinity_target.target_identity_sha256,
                    base_url=state.infinity_origin,
                    auth_token=state.infinity_secret,
                    timeout_seconds=state.request_timeout_seconds,
                    transport=infinity_transport,
                )
                mem0 = ManagedMem0HttpConfig(
                    target_identity_sha256=mem0_target.target_identity_sha256,
                    base_url=state.mem0_origin,
                    api_key=state.mem0_secret,
                    data_plane_auth_mode=state.mem0_data_plane_auth_mode,
                    timeout_seconds=state.request_timeout_seconds,
                    send_timestamps=mem0_send_timestamps,
                    transport=mem0_transport,
                )
                if state.backend_phase != "active":
                    _fail("managed_credentials_terminal")
                if (
                    type(state.preflight_snapshot) is not bytes
                    or type(state.preflight_commitment) is not str
                ):
                    _fail("managed_credentials_integrity_failed")
                result = _issue_backend_credential_material(
                    infinity=infinity,
                    mem0=mem0,
                    probe_token=state.probe_secret,
                    request=expected_request,
                    preflight_snapshot=state.preflight_snapshot,
                    preflight_commitment=state.preflight_commitment,
                    run_id=state.run_id,
                    deadline=state.deadline,
                )
                state.backend_phase = "issued"
                return result
        except BaseException as exc:
            self._terminal_lane("backend")
            if isinstance(exc, ManagedRuntimeCredentialError):
                raise
            raise ManagedRuntimeCredentialError(
                "managed_credentials_configuration_invalid"
            ) from None

    def _reserve_lane(self, name: str) -> None:
        with self.__lock:
            self._require_integrity_locked()
            state = self.__state
            attribute = f"{name}_phase"
            if state.root_phase != "bound" or getattr(state, attribute) != "pending":
                setattr(state, attribute, "terminal")
                _fail("managed_credentials_terminal")
            setattr(state, attribute, "active")

    def _terminal_lane(self, name: str) -> None:
        with self.__lock:
            setattr(self.__state, f"{name}_phase", "terminal")

    def _require_context_locked(
        self,
        *,
        expected_request: ManagedPreflightRequest,
        run_id: str,
        subscription_origin: str,
        deadline: datetime,
        now: datetime,
    ) -> datetime:
        self._require_integrity_locked()
        self._require_static_context_locked(
            expected_request=expected_request,
            run_id=run_id,
            subscription_origin=subscription_origin,
            deadline=deadline,
        )
        state = self.__state
        if expected_request is not state.preflight_request:
            _fail("managed_credentials_context_mismatch")
        self._require_bound_request_locked(expected_request)
        trusted_now = _aware(now, "managed_credentials_context_mismatch")
        if trusted_now < state.issued_at or trusted_now >= state.deadline:
            _fail("managed_credentials_expired")
        return trusted_now

    def _require_static_context_locked(
        self,
        *,
        expected_request: ManagedPreflightRequest,
        run_id: str,
        subscription_origin: str,
        deadline: datetime,
    ) -> None:
        state = self.__state
        material = state.material
        if (
            type(expected_request) is not ManagedPreflightRequest
            or run_id != state.run_id
            or _aware(deadline, "managed_credentials_context_mismatch") != state.deadline
            or _validated_subscription_origin(subscription_origin)
            != state.subscription_origin
            or expected_request.provider_kind
            != MANAGED_PREFLIGHT_PROVIDER_SUBSCRIPTION_RUNTIME
            or expected_request.provider_route is not material.provider_route
            or expected_request.openai_credential is not material.provider_credential
            or expected_request.backend_endpoints is not material.backend_endpoints
            or expected_request.mem0_data_plane_auth_mode
            != state.mem0_data_plane_auth_mode
            or material.mem0_data_plane_auth_mode != state.mem0_data_plane_auth_mode
            or expected_request.timeouts.request_seconds != state.request_timeout_seconds
            or (state.deadline - state.issued_at).total_seconds()
            > expected_request.timeouts.run_seconds
        ):
            _fail("managed_credentials_context_mismatch")

    def _require_bound_request_locked(
        self,
        request: ManagedPreflightRequest,
    ) -> None:
        state = self.__state
        try:
            result = validate_managed_preflight(request)
            snapshot = managed_preflight_request_snapshot(request, result)
            commitment = hmac_sha256(state.binding_key, snapshot)
        except Exception:
            _fail("managed_credentials_preflight_invalid")
        if (
            state.bound_request_identity != id(request)
            or type(state.preflight_snapshot) is not bytes
            or type(state.preflight_commitment) is not str
            or not hmac.compare_digest(snapshot, state.preflight_snapshot)
            or not hmac.compare_digest(commitment, state.preflight_commitment)
        ):
            _fail("managed_credentials_integrity_failed")

    def _require_integrity_locked(self) -> None:
        state = self.__state
        try:
            self._require_secret_continuity_locked()
            expected = runtime_authority_integrity(state)
        except Exception:
            self._terminal_all_locked()
            _fail("managed_credentials_integrity_failed")
        if not hmac.compare_digest(expected, state.integrity):
            self._terminal_all_locked()
            _fail("managed_credentials_integrity_failed")

    def _require_secret_continuity_locked(self) -> None:
        state = self.__state
        observed = secret_commitments(
            state.binding_key,
            run_id=state.run_id,
            infinity_origin=state.infinity_origin,
            mem0_origin=state.mem0_origin,
            subscription_origin=state.subscription_origin,
            infinity_secret=state.infinity_secret,
            mem0_secret=state.mem0_secret,
            probe_secret=state.probe_secret,
            subscription_secret=state.subscription_secret,
            mem0_data_plane_auth_mode=state.mem0_data_plane_auth_mode,
        )
        if not all(
            hmac.compare_digest(left, right)
            for left, right in zip(observed, state.secret_commitments, strict=True)
        ):
            _fail("managed_credentials_integrity_failed")

    def _terminal_all_locked(self) -> None:
        state = self.__state
        state.root_phase = "terminal"
        state.readiness_phase = "terminal"
        state.execution_phase = "terminal"
        state.backend_phase = "terminal"

    def __copy__(self) -> object:
        raise TypeError("managed runtime credential authority is noncopyable")

    def __deepcopy__(self, memo: object) -> object:
        del memo
        raise TypeError("managed runtime credential authority is noncopyable")

    def __reduce__(self) -> object:
        raise TypeError("managed runtime credential authority is nonserializable")

    def __reduce_ex__(self, protocol: int) -> object:
        del protocol
        raise TypeError("managed runtime credential authority is nonserializable")

    def __getstate__(self) -> object:
        raise TypeError("managed runtime credential authority is nonserializable")


def issue_managed_runtime_credential_authority(
    *,
    run_id: str,
    infinity_origin: str,
    infinity_auth_token: str,
    mem0_origin: str,
    mem0_api_key: str | None,
    mem0_probe_token: str | None,
    subscription_origin: str,
    subscription_bearer_token: str,
    request_timeout_seconds: float,
    issued_at: datetime,
    deadline: datetime,
    mem0_data_plane_auth_mode: str = MANAGED_MEM0_DATA_PLANE_AUTH_API_KEY,
) -> ManagedRuntimeCredentialAuthority:
    """Issue an authority before preflight from exact composition-root values."""

    try:
        trusted_run_id = _identifier(run_id)
        trusted_issued_at = _aware(issued_at, "managed_credentials_configuration_invalid")
        trusted_deadline = _aware(deadline, "managed_credentials_configuration_invalid")
        if trusted_issued_at >= trusted_deadline:
            _fail("managed_credentials_configuration_invalid")
        timeout = _timeout(request_timeout_seconds)
        infinity_secret = _secret(infinity_auth_token)
        auth_mode = managed_mem0_data_plane_auth_mode(mem0_data_plane_auth_mode)
        if auth_mode == MANAGED_MEM0_DATA_PLANE_AUTH_NONE:
            if mem0_api_key is not None or mem0_probe_token is None:
                _fail("managed_credentials_configuration_invalid")
            mem0_secret = None
            probe_secret = _secret(mem0_probe_token)
        elif auth_mode == MANAGED_MEM0_DATA_PLANE_AUTH_API_KEY:
            mem0_secret = _secret(mem0_api_key)
            probe_secret = (
                mem0_secret if mem0_probe_token is None else _secret(mem0_probe_token)
            )
        else:  # pragma: no cover - sealed validator above
            _fail("managed_credentials_configuration_invalid")
        subscription_secret = _secret(subscription_bearer_token)
        normalized_infinity, infinity_target = _normalized_backend(
            "infinity-context", infinity_origin
        )
        normalized_mem0, mem0_target = _normalized_backend("mem0", mem0_origin)
        normalized_subscription = _validated_subscription_origin(subscription_origin)
        key = secrets.token_bytes(32)
        commitments = secret_commitments(
            key,
            run_id=trusted_run_id,
            infinity_origin=normalized_infinity,
            mem0_origin=normalized_mem0,
            subscription_origin=normalized_subscription,
            infinity_secret=infinity_secret,
            mem0_secret=mem0_secret,
            probe_secret=probe_secret,
            subscription_secret=subscription_secret,
            mem0_data_plane_auth_mode=auth_mode,
        )
        provider_credential = ManagedCredentialBinding(
            "subscription-runtime", True, adapter_credential_binding(subscription_secret)
        )
        infinity_binding = ManagedCredentialBinding(
            "infinity-context", True, "sha256:" + commitments[0]
        )
        mem0_binding = ManagedCredentialBinding(
            "mem0",
            auth_mode == MANAGED_MEM0_DATA_PLANE_AUTH_API_KEY,
            (
                "sha256:" + commitments[1]
                if auth_mode == MANAGED_MEM0_DATA_PLANE_AUTH_API_KEY
                else None
            ),
        )
        probe_credential = ManagedCredentialBinding(
            "mem0-probe", True, adapter_credential_binding(probe_secret)
        )
        endpoints = (
            ManagedBackendEndpoint(infinity_target, normalized_infinity, infinity_binding),
            ManagedBackendEndpoint(mem0_target, normalized_mem0, mem0_binding),
        )
        endpoint = f"{normalized_subscription}{SUBSCRIPTION_CHAT_ENDPOINT_PATH}"
        route = ProviderRouteAttestation(
            trust=SUBSCRIPTION_RUNTIME_TRUST,
            origin=normalized_subscription,
            endpoint_path=SUBSCRIPTION_CHAT_ENDPOINT_PATH,
            route_sha256=hashlib.sha256(endpoint.encode()).hexdigest(),
            transport_evidence=SUBSCRIPTION_RUNTIME_TRANSPORT_EVIDENCE,
            credential_binding_id=provider_credential.binding_id,
            request_method="POST",
            response_status=0,
        )
        material = ManagedCredentialPreflightMaterial(
            provider_credential=provider_credential,
            backend_endpoints=endpoints,
            provider_route=route,
            mem0_probe_credential=probe_credential,
            mem0_data_plane_auth_mode=auth_mode,
        )
        state = _AuthorityState(
            run_id=trusted_run_id,
            issued_at=trusted_issued_at,
            deadline=trusted_deadline,
            request_timeout_seconds=timeout,
            infinity_origin=normalized_infinity,
            mem0_origin=normalized_mem0,
            subscription_origin=normalized_subscription,
            infinity_secret=infinity_secret,
            mem0_secret=mem0_secret,
            mem0_data_plane_auth_mode=auth_mode,
            probe_secret=probe_secret,
            subscription_secret=subscription_secret,
            binding_key=key,
            secret_commitments=commitments,
            material=material,
            integrity="",
        )
        state.integrity = runtime_authority_integrity(state)
        return ManagedRuntimeCredentialAuthority(state=state, _token=_TOKEN)
    except ManagedRuntimeCredentialError:
        raise
    except Exception:
        _fail("managed_credentials_configuration_invalid")


def _validated_subscription_origin(origin: object) -> str:
    if type(origin) is not str or origin != origin.strip():
        _fail("managed_credentials_configuration_invalid")
    try:
        return _validated_loopback_origin(origin)
    except Exception:
        _fail("managed_credentials_configuration_invalid")


def _secret(value: object) -> str:
    if type(value) is not str or not value or value != value.strip():
        _fail("managed_credentials_configuration_invalid")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeEncodeError:
        _fail("managed_credentials_configuration_invalid")
    if size > _MAX_SECRET_BYTES:
        _fail("managed_credentials_configuration_invalid")
    return value


def _identifier(value: object) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        _fail("managed_credentials_configuration_invalid")
    return value


def _timeout(value: object) -> float:
    if (
        type(value) not in {int, float}
        or not math.isfinite(value)
        or value <= 0
        or value > 180
    ):
        _fail("managed_credentials_configuration_invalid")
    return float(value)


def _remaining_execution_timeout_seconds(
    *,
    configured_timeout_seconds: float,
    deadline: datetime,
    now: datetime,
) -> float:
    remaining = (deadline - now).total_seconds()
    if not math.isfinite(remaining) or remaining <= 0:
        _fail("managed_credentials_expired")
    return min(configured_timeout_seconds, remaining)


def _aware(value: object, code: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        _fail(code)
    try:
        return value.astimezone(UTC)
    except Exception:
        _fail(code)


def _fail(code: str) -> None:
    raise ManagedRuntimeCredentialError(code)


__all__ = (
    "ManagedBackendCredentialMaterial",
    "ManagedCredentialPreflightMaterial",
    "ManagedRuntimeCredentialAuthority",
    "ManagedRuntimeCredentialError",
    "ManagedSubscriptionReadinessClaim",
    "issue_managed_runtime_credential_authority",
)

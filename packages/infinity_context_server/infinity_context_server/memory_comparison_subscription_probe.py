"""Pure opaque evidence for one subscription-runtime readiness call.

This module owns route policy, integrity, freshness and one-admission reservation
for a synthetic subscription-runtime probe. It performs no I/O.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import re
import secrets
import threading
import weakref
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import final
from urllib.parse import urlsplit

from infinity_context_server.memory_comparison_provider_provenance import (
    ProviderRouteAttestation,
)

SUBSCRIPTION_RUNTIME_TRUST = "codex_subscription_runtime"
SUBSCRIPTION_RUNTIME_ORIGIN = "local://codex-cli"
SUBSCRIPTION_RUNTIME_ENDPOINT_PATH = "/exec"
SUBSCRIPTION_RUNTIME_TRANSPORT = "codex-cli-ephemeral-read-only-no-rules-v1"
SUBSCRIPTION_RUNTIME_ROUTE_SHA256 = hashlib.sha256(
    f"{SUBSCRIPTION_RUNTIME_ORIGIN}{SUBSCRIPTION_RUNTIME_ENDPOINT_PATH}".encode()
).hexdigest()
SUBSCRIPTION_BRIDGE_ENDPOINT_PATH = "/v1/chat/completions"
SUBSCRIPTION_BRIDGE_TRANSPORT = "subscription-runtime-openai-codex-bridge.v1"
SUBSCRIPTION_RUNTIME_PROBE_MAX_AGE_SECONDS = 120
SUBSCRIPTION_RUNTIME_USAGE_ESTIMATE_SOURCES = frozenset(
    {"estimated_by_subscription_adapter", "estimated_by_subscription_runtime"}
)

_TOKEN = object()
_LOCK = threading.RLock()
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_BINDING = re.compile(r"^sha256:[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_MAX_CLOCK_SKEW_SECONDS = 1.0


class SubscriptionRuntimeProbeError(ValueError):
    """Secret-safe rejection of subscription-runtime probe evidence."""


@final
class VerifiedSubscriptionRuntimeProbe:
    """Opaque proof that one synthetic subscription-runtime call completed."""

    __slots__ = ("__commitment", "__weakref__")

    def __init__(self, *, commitment: str, _token: object) -> None:
        if _token is not _TOKEN:
            _fail("subscription runtime probe must be issued authoritatively")
        self.__commitment = commitment

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("VerifiedSubscriptionRuntimeProbe is final")

    def __repr__(self) -> str:
        return "VerifiedSubscriptionRuntimeProbe(<sealed>)"

    def __copy__(self) -> object:
        raise TypeError("subscription runtime probe is noncopyable")

    def __deepcopy__(self, memo: object) -> object:
        del memo
        raise TypeError("subscription runtime probe is noncopyable")

    def __reduce__(self) -> object:
        raise TypeError("subscription runtime probe is nonserializable")

    def __reduce_ex__(self, protocol: int) -> object:
        del protocol
        raise TypeError("subscription runtime probe is nonserializable")

    def __getstate__(self) -> object:
        raise TypeError("subscription runtime probe is nonserializable")


@final
@dataclass(frozen=True, slots=True)
class SubscriptionRuntimeProbeObservation:
    """Validated non-secret fields needed by managed live admission."""

    route: ProviderRouteAttestation
    model: str
    total_tokens: int
    usage_source: str
    request_evidence_sha256: str
    response_evidence_sha256: str
    checked_at: datetime

    def public_payload(self) -> dict[str, object]:
        return {
            "route": self.route.public_payload(),
            "model": self.model,
            "provider_call_count": 1,
            "total_tokens": self.total_tokens,
            "usage_source": self.usage_source,
            "request_evidence_sha256": self.request_evidence_sha256,
            "response_evidence_sha256": self.response_evidence_sha256,
            "checked_at": _instant_text(self.checked_at),
        }

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("SubscriptionRuntimeProbeObservation is final")


@dataclass(frozen=True, slots=True)
class _SubscriptionRuntimeProbeState:
    observation: SubscriptionRuntimeProbeObservation
    secret: bytes = field(repr=False)
    commitment: str = field(repr=False)


_PROBES: weakref.WeakKeyDictionary[
    VerifiedSubscriptionRuntimeProbe, _SubscriptionRuntimeProbeState
] = weakref.WeakKeyDictionary()
_RESERVED_PROBES: weakref.WeakSet[VerifiedSubscriptionRuntimeProbe] = weakref.WeakSet()


def _build_subscription_runtime_probe_issuer() -> Callable[..., VerifiedSubscriptionRuntimeProbe]:
    """Create the private sealing seam used only by the concrete live probe."""

    def seal(
        *,
        route: ProviderRouteAttestation,
        model: str,
        provider_call_count: int,
        total_tokens: int,
        usage_source: str,
        request_evidence_sha256: str,
        response_evidence_sha256: str,
        checked_at: datetime,
    ) -> VerifiedSubscriptionRuntimeProbe:
        trusted_route = _validate_subscription_route(route)
        trusted_model = _identifier(model, "subscription probe model")
        if (
            type(provider_call_count) is not int
            or provider_call_count != 1
            or type(total_tokens) is not int
            or not 1 <= total_tokens <= 100_000
        ):
            _fail("subscription runtime probe usage evidence is invalid")
        if (
            type(usage_source) is not str
            or usage_source not in SUBSCRIPTION_RUNTIME_USAGE_ESTIMATE_SOURCES
        ):
            _fail("subscription runtime probe usage source is invalid")
        observation = SubscriptionRuntimeProbeObservation(
            route=trusted_route,
            model=trusted_model,
            total_tokens=total_tokens,
            usage_source=usage_source,
            request_evidence_sha256=_digest(
                request_evidence_sha256,
                "subscription request evidence",
            ),
            response_evidence_sha256=_digest(
                response_evidence_sha256,
                "subscription response evidence",
            ),
            checked_at=_aware_instant(checked_at, "subscription checked_at"),
        )
        secret = secrets.token_bytes(32)
        commitment = hmac.new(
            secret,
            _canonical_json(observation.public_payload()),
            hashlib.sha256,
        ).hexdigest()
        probe = VerifiedSubscriptionRuntimeProbe(commitment=commitment, _token=_TOKEN)
        with _LOCK:
            _PROBES[probe] = _SubscriptionRuntimeProbeState(
                observation=observation,
                secret=secret,
                commitment=commitment,
            )
        return probe

    return seal


_subscription_runtime_probe_issuer = _build_subscription_runtime_probe_issuer()
del _build_subscription_runtime_probe_issuer


def inspect_verified_subscription_runtime_probe(
    probe: VerifiedSubscriptionRuntimeProbe,
    *,
    now: datetime,
) -> SubscriptionRuntimeProbeObservation:
    """Validate integrity and freshness without reserving the probe."""

    trusted_now = _aware_instant(now, "subscription probe now")
    with _LOCK:
        state = _validated_state(probe)
        _require_current(state.observation.checked_at, now=trusted_now)
        return state.observation


def reserve_verified_subscription_runtime_probe(
    probe: VerifiedSubscriptionRuntimeProbe,
    *,
    now: datetime,
) -> SubscriptionRuntimeProbeObservation:
    """Atomically reserve a fresh probe for exactly one managed admission."""

    trusted_now = _aware_instant(now, "subscription probe now")
    with _LOCK:
        state = _validated_state(probe)
        _require_current(state.observation.checked_at, now=trusted_now)
        if probe in _RESERVED_PROBES:
            _fail("subscription runtime validation was already reserved")
        _RESERVED_PROBES.add(probe)
        return state.observation


def _validated_state(
    probe: VerifiedSubscriptionRuntimeProbe,
) -> _SubscriptionRuntimeProbeState:
    if type(probe) is not VerifiedSubscriptionRuntimeProbe:
        _fail("subscription runtime validation type is invalid")
    state = _PROBES.get(probe)
    if state is None:
        _fail("subscription runtime validation was not issued")
    expected = hmac.new(
        state.secret,
        _canonical_json(state.observation.public_payload()),
        hashlib.sha256,
    ).hexdigest()
    try:
        observed = probe._VerifiedSubscriptionRuntimeProbe__commitment
    except (AttributeError, TypeError):
        _fail("subscription runtime validation integrity failed")
    if (
        type(observed) is not str
        or not hmac.compare_digest(observed, state.commitment)
        or not hmac.compare_digest(expected, state.commitment)
    ):
        _fail("subscription runtime validation integrity failed")
    return state


def _validate_subscription_route(route: object) -> ProviderRouteAttestation:
    if (
        type(route) is not ProviderRouteAttestation
        or route.trust != SUBSCRIPTION_RUNTIME_TRUST
        or not (_local_subscription_route(route) or _loopback_subscription_route(route))
    ):
        _fail("subscription runtime route is invalid")
    return route


def _local_subscription_route(route: ProviderRouteAttestation) -> bool:
    return bool(
        route.origin == SUBSCRIPTION_RUNTIME_ORIGIN
        and route.endpoint_path == SUBSCRIPTION_RUNTIME_ENDPOINT_PATH
        and route.route_sha256 == SUBSCRIPTION_RUNTIME_ROUTE_SHA256
        and route.transport_evidence == SUBSCRIPTION_RUNTIME_TRANSPORT
        and route.credential_binding_id is None
        and route.request_method == "EXEC"
        and route.response_status == 0
    )


def _loopback_subscription_route(route: ProviderRouteAttestation) -> bool:
    try:
        parsed = urlsplit(route.origin)
        address = ipaddress.ip_address(parsed.hostname or "")
        port = parsed.port
    except ValueError:
        return False
    credential = route.credential_binding_id
    return bool(
        parsed.scheme in {"http", "https"}
        and address.is_loopback
        and getattr(address, "ipv4_mapped", None) is None
        and port is not None
        and parsed.username is None
        and parsed.password is None
        and parsed.path == ""
        and not parsed.query
        and not parsed.fragment
        and route.endpoint_path == SUBSCRIPTION_BRIDGE_ENDPOINT_PATH
        and route.route_sha256
        == hashlib.sha256(f"{route.origin}{route.endpoint_path}".encode()).hexdigest()
        and route.transport_evidence == SUBSCRIPTION_BRIDGE_TRANSPORT
        and (
            credential is None
            or (type(credential) is str and _BINDING.fullmatch(credential) is not None)
        )
        and route.request_method == "POST"
        and type(route.response_status) is int
        and 200 <= route.response_status < 300
    )


def _identifier(value: object, field_name: str) -> str:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        _fail(f"{field_name} is invalid")
    return value


def _digest(value: object, field_name: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        _fail(f"{field_name} is invalid")
    return value


def _aware_instant(value: object, field_name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None:
        _fail(f"{field_name} must be timezone-aware")
    normalized = value.astimezone(UTC)
    if not 1970 <= normalized.year <= 2100:
        _fail(f"{field_name} is outside the supported range")
    return normalized


def _require_current(instant: datetime, *, now: datetime) -> None:
    age = (now - instant).total_seconds()
    if age < -_MAX_CLOCK_SKEW_SECONDS or max(0.0, age) > SUBSCRIPTION_RUNTIME_PROBE_MAX_AGE_SECONDS:
        _fail("subscription runtime validation is stale or from the future")


def _instant_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def _fail(message: str) -> None:
    raise SubscriptionRuntimeProbeError(message)


__all__ = (
    "SUBSCRIPTION_BRIDGE_ENDPOINT_PATH",
    "SUBSCRIPTION_BRIDGE_TRANSPORT",
    "SUBSCRIPTION_RUNTIME_ENDPOINT_PATH",
    "SUBSCRIPTION_RUNTIME_ORIGIN",
    "SUBSCRIPTION_RUNTIME_PROBE_MAX_AGE_SECONDS",
    "SUBSCRIPTION_RUNTIME_ROUTE_SHA256",
    "SUBSCRIPTION_RUNTIME_TRANSPORT",
    "SUBSCRIPTION_RUNTIME_TRUST",
    "SUBSCRIPTION_RUNTIME_USAGE_ESTIMATE_SOURCES",
    "SubscriptionRuntimeProbeError",
    "SubscriptionRuntimeProbeObservation",
    "VerifiedSubscriptionRuntimeProbe",
    "inspect_verified_subscription_runtime_probe",
    "reserve_verified_subscription_runtime_probe",
)

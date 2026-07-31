"""Sealed managed-composition attestation for full comparison runs.

Only exact nominal runtime/provider capabilities and composition-owned live ports
can be admitted. Public mappings are component-only projections, never evidence.
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
import re
import secrets
import threading
import weakref
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, final

from infinity_context_server.memory_comparison_full_profiles import (
    resolve_full_comparison_profile,
)
from infinity_context_server.memory_comparison_full_run_evidence import (
    FullComparisonRunBindings,
    _validate_bindings,
)
from infinity_context_server.memory_comparison_mem0_runtime_attestation import (
    VerifiedMem0RuntimeAttestationValidation,
    mem0_runtime_attestation_validation_is_publishable,
    public_mem0_runtime_attestation_validation,
)
from infinity_context_server.memory_comparison_provider_provenance import (
    ProviderRouteAttestation,
)

if TYPE_CHECKING:
    from infinity_context_server.memory_comparison_managed_run_ports import (
        ManagedAttestationPort,
        ManagedClockPort,
        ManagedIngestPort,
        ManagedResetPort,
    )


MANAGED_COMPOSITION_ATTESTATION_SCHEMA_VERSION = (
    "memory-comparison-managed-composition-attestation.v1"
)
_MAX_CLOCK_SKEW_SECONDS = 1.0
_MAX_TEXT = 16_384
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_TOKEN = object()
_LOCK = threading.RLock()


class ManagedCompositionAttestationError(ValueError):
    """Raised when managed composition evidence is forged, stale, or replayed."""


@final
class VerifiedManagedCompositionAttestation:
    """Opaque component capability bound to one exact live composition."""

    __slots__ = ("__commitment", "__nonce", "__weakref__")

    def __init__(self, *, commitment: str, nonce: str, _token: object) -> None:
        if _token is not _TOKEN:
            raise ManagedCompositionAttestationError(
                "managed composition attestations must be composition-root issued"
            )
        self.__commitment = commitment
        self.__nonce = nonce

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("VerifiedManagedCompositionAttestation is final")

    def __repr__(self) -> str:
        return "VerifiedManagedCompositionAttestation(<opaque>)"

    def __copy__(self) -> object:
        raise TypeError("managed composition attestations are noncopyable")

    def __deepcopy__(self, memo: object) -> object:
        del memo
        raise TypeError("managed composition attestations are noncopyable")

    def __reduce__(self) -> object:
        raise TypeError("managed composition attestations are nonserializable")

    def __reduce_ex__(self, protocol: int) -> object:
        del protocol
        raise TypeError("managed composition attestations are nonserializable")

    def __getstate__(self) -> object:
        raise TypeError("managed composition attestations are nonserializable")


@dataclass(frozen=True, slots=True)
class _PortSnapshot:
    port_role: str
    adapter_id: str
    implementation_sha256: str
    operation_identity: int


@dataclass(frozen=True, slots=True)
class _RuntimeSnapshot:
    runtime_mode: str
    run_id_sha256: str
    probe_nonce_sha256: str
    target_identity_sha256: str
    validation_sha256: str
    attestation_sha256: str
    validated_at: str
    checked_at: str
    max_age_seconds: int


@dataclass(frozen=True, slots=True)
class _ProviderSnapshot:
    trust: str
    origin: str
    endpoint_path: str
    route_sha256: str
    transport_evidence: str
    credential_binding_id: str
    request_method: str
    response_status: int
    payload_sha256: str


@dataclass(frozen=True, slots=True)
class _CompositionSnapshot:
    binding_commitment_sha256: str
    run_id_sha256: str
    backend_targets: tuple[tuple[str, str], ...]
    ports: tuple[_PortSnapshot, ...]
    runtime: _RuntimeSnapshot
    provider: _ProviderSnapshot
    checked_at: str
    max_age_seconds: int


@dataclass(slots=True)
class _AttestationState:
    bindings: FullComparisonRunBindings
    ports: tuple[object, ...]
    runtime_validation: VerifiedMem0RuntimeAttestationValidation
    provider_route: ProviderRouteAttestation
    snapshot: _CompositionSnapshot
    secret: bytes
    commitment: str
    nonce: str
    consumed: bool = False


def _build_managed_attestation_api():
    states: weakref.WeakKeyDictionary[VerifiedManagedCompositionAttestation, _AttestationState] = (
        weakref.WeakKeyDictionary()
    )
    reservations: list[
        tuple[VerifiedMem0RuntimeAttestationValidation, ProviderRouteAttestation]
    ] = []

    def issue(
        *,
        bindings: FullComparisonRunBindings,
        reset_port: ManagedResetPort,
        attestation_port: ManagedAttestationPort,
        ingest_port: ManagedIngestPort,
        clock: ManagedClockPort,
        runtime_validation: VerifiedMem0RuntimeAttestationValidation,
        provider_route: ProviderRouteAttestation,
    ) -> VerifiedManagedCompositionAttestation:
        trusted = _trusted_bindings(bindings)
        ports: tuple[object, ...] = (
            reset_port,
            attestation_port,
            ingest_port,
            clock,
        )
        _validate_distinct_ports(ports)
        port_snapshots = _port_snapshots(ports)
        now = _clock_now(clock)
        runtime = _runtime_snapshot(trusted, runtime_validation, now)
        provider = _provider_snapshot(provider_route)
        max_age = runtime.max_age_seconds
        checked_at = _instant_text(now)
        snapshot = _CompositionSnapshot(
            binding_commitment_sha256=trusted.binding_commitment_sha256,
            run_id_sha256=hashlib.sha256(trusted.run_id.encode()).hexdigest(),
            backend_targets=tuple(
                (target.backend_role, target.target_identity_sha256)
                for target in trusted.backend_targets
            ),
            ports=port_snapshots,
            runtime=runtime,
            provider=provider,
            checked_at=checked_at,
            max_age_seconds=max_age,
        )
        secret = secrets.token_bytes(32)
        nonce = secrets.token_hex(32)
        commitment = _state_commitment(
            secret,
            snapshot,
            ports=ports,
            bindings=trusted,
            runtime_validation=runtime_validation,
            provider_route=provider_route,
            nonce=nonce,
        )
        attestation = VerifiedManagedCompositionAttestation(
            commitment=commitment,
            nonce=nonce,
            _token=_TOKEN,
        )
        with _LOCK:
            if any(
                runtime_validation is reserved_runtime or provider_route is reserved_provider
                for reserved_runtime, reserved_provider in reservations
            ):
                raise ManagedCompositionAttestationError(
                    "managed runtime/provider capability was already reserved"
                )
            reservations.append((runtime_validation, provider_route))
            states[attestation] = _AttestationState(
                bindings=trusted,
                ports=ports,
                runtime_validation=runtime_validation,
                provider_route=provider_route,
                snapshot=snapshot,
                secret=secret,
                commitment=commitment,
                nonce=nonce,
            )
        return attestation

    def inspect(
        attestation: VerifiedManagedCompositionAttestation,
        *,
        bindings: FullComparisonRunBindings,
        reset_port: ManagedResetPort,
        attestation_port: ManagedAttestationPort,
        ingest_port: ManagedIngestPort,
        clock: ManagedClockPort,
        consume: bool,
    ) -> dict[str, object]:
        if type(attestation) is not VerifiedManagedCompositionAttestation:
            raise ManagedCompositionAttestationError(
                "managed composition attestation type must be exact"
            )
        with _LOCK:
            state = states.get(attestation)
            if state is None:
                raise ManagedCompositionAttestationError(
                    "managed composition attestation was not issued"
                )
            if state.consumed:
                raise ManagedCompositionAttestationError(
                    "managed composition attestation was already consumed"
                )

        trusted = _trusted_bindings(bindings)
        ports: tuple[object, ...] = (
            reset_port,
            attestation_port,
            ingest_port,
            clock,
        )
        if state.bindings is not trusted:
            raise ManagedCompositionAttestationError("managed composition binding object differs")
        if not _same_objects(state.ports, ports):
            raise ManagedCompositionAttestationError("managed composition port identity differs")
        current_ports = _port_snapshots(ports)
        now = _clock_now(clock)
        current_runtime = _runtime_snapshot(
            trusted,
            state.runtime_validation,
            now,
        )
        current_provider = _provider_snapshot(state.provider_route)
        if (
            current_ports != state.snapshot.ports
            or current_runtime != state.snapshot.runtime
            or current_provider != state.snapshot.provider
        ):
            raise ManagedCompositionAttestationError("managed composition live capability changed")
        _require_current(
            state.snapshot.checked_at,
            max_age_seconds=state.snapshot.max_age_seconds,
            now=now,
            field_name="managed composition checked_at",
        )
        expected = _state_commitment(
            state.secret,
            state.snapshot,
            ports=ports,
            bindings=trusted,
            runtime_validation=state.runtime_validation,
            provider_route=state.provider_route,
            nonce=state.nonce,
        )
        _validate_opaque(attestation, state)
        if not hmac.compare_digest(expected, state.commitment):
            raise ManagedCompositionAttestationError(
                "managed composition attestation integrity failed"
            )

        if consume:
            with _LOCK:
                current_state = states.get(attestation)
                if current_state is not state or state.consumed:
                    raise ManagedCompositionAttestationError(
                        "managed composition attestation was already consumed"
                    )
                state.consumed = True
        return _public_report(state)

    return issue, inspect


(
    _issue_verified_managed_composition_attestation_for_composition_root,
    _inspect_verified_managed_composition_attestation,
) = _build_managed_attestation_api()


def public_managed_composition_attestation(
    attestation: VerifiedManagedCompositionAttestation,
    *,
    bindings: FullComparisonRunBindings,
    reset_port: ManagedResetPort,
    attestation_port: ManagedAttestationPort,
    ingest_port: ManagedIngestPort,
    clock: ManagedClockPort,
) -> dict[str, object]:
    """Project a fresh component-only report after live identity revalidation."""

    return copy.deepcopy(
        _inspect_verified_managed_composition_attestation(
            attestation,
            bindings=bindings,
            reset_port=reset_port,
            attestation_port=attestation_port,
            ingest_port=ingest_port,
            clock=clock,
            consume=False,
        )
    )


def _consume_verified_managed_composition_attestation_for_composite(
    attestation: VerifiedManagedCompositionAttestation,
    *,
    bindings: FullComparisonRunBindings,
    reset_port: ManagedResetPort,
    attestation_port: ManagedAttestationPort,
    ingest_port: ManagedIngestPort,
    clock: ManagedClockPort,
) -> dict[str, object]:
    """Private one-shot seam reserved for the future composite component."""

    return _inspect_verified_managed_composition_attestation(
        attestation,
        bindings=bindings,
        reset_port=reset_port,
        attestation_port=attestation_port,
        ingest_port=ingest_port,
        clock=clock,
        consume=True,
    )


def _trusted_bindings(bindings: FullComparisonRunBindings) -> FullComparisonRunBindings:
    try:
        return _validate_bindings(bindings)
    except Exception:
        raise ManagedCompositionAttestationError("full comparison binding is invalid") from None


def _validate_distinct_ports(ports: tuple[object, ...]) -> None:
    if len(ports) != 4 or any(port is None for port in ports):
        raise ManagedCompositionAttestationError("all managed composition ports must be concrete")
    if any(left is right for index, left in enumerate(ports) for right in ports[index + 1 :]):
        raise ManagedCompositionAttestationError(
            "managed composition ports must be distinct objects"
        )


def _port_snapshots(ports: tuple[object, ...]) -> tuple[_PortSnapshot, ...]:
    roles = ("reset", "attestation", "ingest", "clock")
    methods = ("reset", "attest", "ingest", "now")
    snapshots: list[_PortSnapshot] = []
    for role, method, port in zip(roles, methods, ports, strict=True):
        try:
            adapter_id = port.adapter_id
            implementation_sha256 = port.implementation_sha256
            operation = getattr(port, method)
        except Exception:
            raise ManagedCompositionAttestationError(
                f"managed {role} port provenance is unavailable"
            ) from None
        if type(adapter_id) is not str or _ID_RE.fullmatch(adapter_id) is None:
            raise ManagedCompositionAttestationError(f"managed {role} adapter_id is invalid")
        _digest(
            implementation_sha256,
            field_name=f"managed {role} implementation_sha256",
        )
        if not callable(operation):
            raise ManagedCompositionAttestationError(
                f"managed {role} port operation is unavailable"
            )
        operation_target = getattr(operation, "__func__", operation)
        snapshots.append(
            _PortSnapshot(
                port_role=role,
                adapter_id=adapter_id,
                implementation_sha256=implementation_sha256,
                operation_identity=id(operation_target),
            )
        )
    return tuple(snapshots)


def _clock_now(clock: ManagedClockPort) -> datetime:
    try:
        value = clock.now()
    except Exception:
        raise ManagedCompositionAttestationError("managed composition clock failed") from None
    if type(value) is not datetime or value.tzinfo is None:
        raise ManagedCompositionAttestationError("managed composition clock must be timezone-aware")
    return value.astimezone(UTC)


def _runtime_snapshot(
    bindings: FullComparisonRunBindings,
    validation: VerifiedMem0RuntimeAttestationValidation,
    now: datetime,
) -> _RuntimeSnapshot:
    if type(validation) is not VerifiedMem0RuntimeAttestationValidation:
        raise ManagedCompositionAttestationError("managed runtime capability type must be exact")
    profile = resolve_full_comparison_profile(bindings.profile_id)
    if profile is None:
        raise ManagedCompositionAttestationError("managed runtime profile is unavailable")
    public = public_mem0_runtime_attestation_validation(validation)
    if not mem0_runtime_attestation_validation_is_publishable(
        validation,
        required_runtime_mode=profile.required_mem0_runtime_mode,
    ):
        raise ManagedCompositionAttestationError("managed runtime capability is not publishable")
    attestation = public.get("attestation")
    if type(attestation) is not dict:
        raise ManagedCompositionAttestationError("managed runtime attestation is invalid")
    mem0_targets = tuple(
        target.target_identity_sha256
        for target in bindings.backend_targets
        if target.backend_role == "mem0"
    )
    expected_run = hashlib.sha256(bindings.run_id.encode()).hexdigest()
    if (
        len(mem0_targets) != 1
        or attestation.get("run_id_sha256") != expected_run
        or attestation.get("probe_nonce_sha256") != bindings.runtime_probe_nonce_sha256
        or attestation.get("target_identity_sha256") != mem0_targets[0]
        or attestation.get("runtime_mode") != profile.required_mem0_runtime_mode
    ):
        raise ManagedCompositionAttestationError(
            "managed runtime binding differs from full comparison"
        )
    max_age = public.get("max_age_seconds")
    validated_at = public.get("validated_at")
    checked_at = attestation.get("checked_at")
    if type(max_age) is not int or not 0 < max_age <= 3_600:
        raise ManagedCompositionAttestationError("managed runtime max_age_seconds is invalid")
    _require_current(
        validated_at,
        max_age_seconds=max_age,
        now=now,
        field_name="managed runtime validated_at",
    )
    _require_current(
        checked_at,
        max_age_seconds=max_age,
        now=now,
        field_name="managed runtime checked_at",
    )
    for field in (
        "age_seconds",
        "timestamp_attestation_age_seconds",
        "refresh_age_seconds",
    ):
        age = public.get(field)
        if (
            type(age) not in {int, float}
            or float(age) < -_MAX_CLOCK_SKEW_SECONDS
            or max(0.0, float(age))
            + max(
                0.0,
                (now - _parse_instant(validated_at, field_name="validated_at")).total_seconds(),
            )
            > max_age
        ):
            raise ManagedCompositionAttestationError(f"managed runtime {field} is stale or invalid")
    return _RuntimeSnapshot(
        runtime_mode=str(attestation["runtime_mode"]),
        run_id_sha256=expected_run,
        probe_nonce_sha256=bindings.runtime_probe_nonce_sha256,
        target_identity_sha256=mem0_targets[0],
        validation_sha256=_json_sha256(public),
        attestation_sha256=str(attestation.get("attestation_fingerprint_sha256")),
        validated_at=str(validated_at),
        checked_at=str(checked_at),
        max_age_seconds=max_age,
    )


def _provider_snapshot(route: ProviderRouteAttestation) -> _ProviderSnapshot:
    if type(route) is not ProviderRouteAttestation:
        raise ManagedCompositionAttestationError("provider route capability type must be exact")
    public = route.public_payload()
    raw_text = {
        "trust": route.trust,
        "origin": route.origin,
        "endpoint_path": route.endpoint_path,
        "transport_evidence": route.transport_evidence,
        "request_method": route.request_method,
    }
    if any(
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > _MAX_TEXT
        or public.get(field) != value
        for field, value in raw_text.items()
    ):
        raise ManagedCompositionAttestationError("provider route fields are invalid")
    _digest(route.route_sha256, field_name="provider route_sha256")
    credential = route.credential_binding_id
    if (
        type(credential) is not str
        or not credential.startswith("sha256:")
        or _SHA256_RE.fullmatch(credential[7:]) is None
        or public.get("credential_bound") is not True
        or public.get("credential_binding_id") != credential
    ):
        raise ManagedCompositionAttestationError("provider credential binding is invalid")
    if (
        route.request_method != "POST"
        or type(route.response_status) is not int
        or not 200 <= route.response_status < 300
    ):
        raise ManagedCompositionAttestationError("provider route did not attest a successful POST")
    return _ProviderSnapshot(
        trust=route.trust,
        origin=route.origin,
        endpoint_path=route.endpoint_path,
        route_sha256=route.route_sha256,
        transport_evidence=route.transport_evidence,
        credential_binding_id=credential,
        request_method=route.request_method,
        response_status=route.response_status,
        payload_sha256=_json_sha256(public),
    )


def _require_current(
    value: object,
    *,
    max_age_seconds: int,
    now: datetime,
    field_name: str,
) -> None:
    instant = _parse_instant(value, field_name=field_name)
    delta = (now - instant).total_seconds()
    if delta < -_MAX_CLOCK_SKEW_SECONDS:
        raise ManagedCompositionAttestationError(f"{field_name} is from the future")
    if max(0.0, delta) > max_age_seconds:
        raise ManagedCompositionAttestationError(f"{field_name} is stale")


def _parse_instant(value: object, *, field_name: str) -> datetime:
    if type(value) is not str or not value.endswith("Z"):
        raise ManagedCompositionAttestationError(f"{field_name} must be an exact UTC instant")
    try:
        parsed = datetime.fromisoformat(f"{value[:-1]}+00:00")
    except ValueError:
        raise ManagedCompositionAttestationError(
            f"{field_name} must be an exact UTC instant"
        ) from None
    if parsed.tzinfo is None:
        raise ManagedCompositionAttestationError(f"{field_name} must be timezone-aware")
    return parsed.astimezone(UTC)


def _validate_opaque(
    attestation: VerifiedManagedCompositionAttestation,
    state: _AttestationState,
) -> None:
    try:
        commitment = attestation._VerifiedManagedCompositionAttestation__commitment
        nonce = attestation._VerifiedManagedCompositionAttestation__nonce
    except (AttributeError, TypeError):
        raise ManagedCompositionAttestationError(
            "managed composition attestation integrity failed"
        ) from None
    if (
        type(commitment) is not str
        or type(nonce) is not str
        or not hmac.compare_digest(commitment, state.commitment)
        or not hmac.compare_digest(nonce, state.nonce)
    ):
        raise ManagedCompositionAttestationError("managed composition attestation integrity failed")


def _state_commitment(
    secret: bytes,
    snapshot: _CompositionSnapshot,
    *,
    ports: tuple[object, ...],
    bindings: FullComparisonRunBindings,
    runtime_validation: VerifiedMem0RuntimeAttestationValidation,
    provider_route: ProviderRouteAttestation,
    nonce: str,
) -> str:
    payload = {
        "snapshot": _snapshot_payload(snapshot),
        "binding_object_identity": id(bindings),
        "port_object_identities": [id(port) for port in ports],
        "port_operation_identities": [port.operation_identity for port in snapshot.ports],
        "runtime_capability_identity": id(runtime_validation),
        "provider_capability_identity": id(provider_route),
        "nonce": nonce,
    }
    return hmac.new(
        secret,
        _canonical_json(payload),
        hashlib.sha256,
    ).hexdigest()


def _snapshot_payload(snapshot: _CompositionSnapshot) -> dict[str, object]:
    return {
        "schema_version": MANAGED_COMPOSITION_ATTESTATION_SCHEMA_VERSION,
        "binding_commitment_sha256": snapshot.binding_commitment_sha256,
        "run_id_sha256": snapshot.run_id_sha256,
        "backend_targets": [
            {
                "backend_role": role,
                "target_identity_sha256": target,
            }
            for role, target in snapshot.backend_targets
        ],
        "ports": [
            {
                "port_role": port.port_role,
                "adapter_id": port.adapter_id,
                "implementation_sha256": port.implementation_sha256,
            }
            for port in snapshot.ports
        ],
        "runtime": {
            field: getattr(snapshot.runtime, field)
            for field in snapshot.runtime.__dataclass_fields__
        },
        "provider_route": {
            field: getattr(snapshot.provider, field)
            for field in snapshot.provider.__dataclass_fields__
        },
        "checked_at": snapshot.checked_at,
        "max_age_seconds": snapshot.max_age_seconds,
    }


def _public_report(state: _AttestationState) -> dict[str, object]:
    return {
        **_snapshot_payload(state.snapshot),
        "composition_attestation_sha256": state.commitment,
        "evidence_role": "component_only",
        "component_only": True,
        "composite_consume_required": True,
        "externally_authentic": False,
    }


def _same_objects(left: tuple[object, ...], right: tuple[object, ...]) -> bool:
    return len(left) == len(right) and all(
        left_item is right_item for left_item, right_item in zip(left, right, strict=True)
    )


def _digest(value: object, *, field_name: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise ManagedCompositionAttestationError(f"{field_name} must be lowercase sha256")
    return value


def _instant_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _json_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


__all__ = (
    "MANAGED_COMPOSITION_ATTESTATION_SCHEMA_VERSION",
    "ManagedCompositionAttestationError",
    "VerifiedManagedCompositionAttestation",
    "public_managed_composition_attestation",
)

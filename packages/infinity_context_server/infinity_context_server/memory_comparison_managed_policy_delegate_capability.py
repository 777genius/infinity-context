"""Explicit one-shot authority for a trusted managed policy delegate."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import weakref
from dataclasses import dataclass, replace
from typing import NoReturn, final

from infinity_context_server.memory_comparison_full_run_evidence import (
    FullComparisonRunBindings,
)
from infinity_context_server.memory_comparison_managed_http_policy_lifecycle import (
    MANAGED_HTTP_POLICY_ADAPTER_ID,
    ManagedComparisonHttpPolicyLifecycleAdapter,
    managed_http_policy_lifecycle_implementation_sha256,
)
from infinity_context_server.memory_comparison_managed_http_policy_material_projection import (
    binding_snapshot,
)
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunCase

_TOKEN = object()
_LOCK = threading.RLock()
_SECRET = secrets.token_bytes(32)


class ManagedPolicyDelegateCapabilityError(RuntimeError):
    """Stable secret-free trusted-delegate authority failure."""

    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@final
class ManagedPolicyDelegateCapability:
    """Opaque non-transferable one-use delegate authority."""

    __slots__ = ("__weakref__",)

    def __init__(self, *, _token: object) -> None:
        if _token is not _TOKEN:
            _fail("managed_policy_delegate_capability_forged")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedPolicyDelegateCapability is final")

    def __repr__(self) -> str:
        return "ManagedPolicyDelegateCapability(<opaque>)"

    def __copy__(self) -> object:
        raise TypeError("ManagedPolicyDelegateCapability is noncopyable")

    def __deepcopy__(self, memo: object) -> object:
        del memo
        raise TypeError("ManagedPolicyDelegateCapability is noncopyable")

    def __reduce__(self) -> object:
        raise TypeError("ManagedPolicyDelegateCapability is nonserializable")

    def __reduce_ex__(self, protocol: int) -> object:
        del protocol
        raise TypeError("ManagedPolicyDelegateCapability is nonserializable")

    def __getstate__(self) -> object:
        raise TypeError("ManagedPolicyDelegateCapability is nonserializable")


@final
class ManagedPolicyDelegatePort:
    """Exact nominal forwarding port exposed after capability consumption."""

    __slots__ = ("__weakref__",)

    def __init__(self, *, _token: object) -> None:
        if _token is not _TOKEN:
            _fail("managed_policy_delegate_port_forged")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedPolicyDelegatePort is final")

    def __repr__(self) -> str:
        return "ManagedPolicyDelegatePort(<opaque>)"

    def __copy__(self) -> object:
        raise TypeError("ManagedPolicyDelegatePort is noncopyable")

    def __deepcopy__(self, memo: object) -> object:
        del memo
        raise TypeError("ManagedPolicyDelegatePort is noncopyable")

    def __reduce__(self) -> object:
        raise TypeError("ManagedPolicyDelegatePort is nonserializable")

    def __reduce_ex__(self, protocol: int) -> object:
        del protocol
        raise TypeError("ManagedPolicyDelegatePort is nonserializable")

    def __getstate__(self) -> object:
        raise TypeError("ManagedPolicyDelegatePort is nonserializable")

    @property
    def exact_projection_evidence(self) -> object:
        return _trusted_port_delegate(self).exact_projection_evidence

    @property
    def mem0_terminal_observation(self) -> object:
        return _trusted_port_delegate(self).mem0_terminal_observation

    def seal_canonical_source(self, **kwargs: object) -> tuple[object, ...]:
        return _trusted_port_delegate(self).seal_canonical_source(**kwargs)

    def terminal_delete(self, **kwargs: object) -> object:
        return _trusted_port_delegate(self).terminal_delete(**kwargs)

    def seal_terminal_delete(self, **kwargs: object) -> object:
        return _trusted_port_delegate(self).seal_terminal_delete(**kwargs)

    def bind_registry_completion_evidence(self, **kwargs: object) -> None:
        _trusted_port_delegate(self).bind_registry_completion_evidence(**kwargs)

    def aggregate_policy(self, **kwargs: object) -> object:
        return _trusted_port_delegate(self).aggregate_policy(**kwargs)


@dataclass(frozen=True, slots=True)
class _CapabilityState:
    delegate: object
    bindings: FullComparisonRunBindings
    binding_snapshot: tuple[object, ...]
    target_pairs: tuple[tuple[str, str], ...]
    corpus_ids: tuple[str, ...]
    cases: tuple[ManagedRunCase, ...]
    implementation_sha256: str
    phase: str
    integrity_mac: bytes


_CAPABILITIES: weakref.WeakKeyDictionary[ManagedPolicyDelegateCapability, _CapabilityState]


@dataclass(frozen=True, slots=True)
class _PortState:
    delegate: object
    implementation_sha256: str
    integrity_mac: bytes


_PORTS: weakref.WeakKeyDictionary[ManagedPolicyDelegatePort, _PortState]


def _issue_legacy_managed_policy_delegate_capability(
    *,
    delegate: ManagedComparisonHttpPolicyLifecycleAdapter,
    bindings: FullComparisonRunBindings,
    cases: tuple[ManagedRunCase, ...],
) -> ManagedPolicyDelegateCapability:
    """Explicitly admit the exact legacy delegate into the trusted port."""

    implementation = authenticate_trusted_managed_policy_delegate(delegate)
    return _issue_exact_capability(
        delegate=delegate,
        bindings=bindings,
        cases=cases,
        implementation=implementation,
    )


def _issue_managed_v5_policy_delegate_capability(
    *,
    delegate: object,
    bindings: FullComparisonRunBindings,
    cases: tuple[ManagedRunCase, ...],
) -> ManagedPolicyDelegateCapability:
    """Explicitly admit only the exact nominal Infinity+v5 delegate."""

    implementation = _authenticate_trusted_managed_v5_policy_delegate(delegate)
    return _issue_exact_capability(
        delegate=delegate,
        bindings=bindings,
        cases=cases,
        implementation=implementation,
    )


def _issue_exact_capability(
    *,
    delegate: object,
    bindings: FullComparisonRunBindings,
    cases: tuple[ManagedRunCase, ...],
    implementation: str,
) -> ManagedPolicyDelegateCapability:
    snapshot, targets = _binding_material(bindings)
    corpus_ids = _corpus_ids(cases)
    try:
        (
            delegate_bindings,
            delegate_snapshot,
            delegate_cases,
            delegate_phase,
        ) = delegate._registry_delegate_composition_for_capability()
        composition_valid = (
            delegate_bindings is bindings
            and delegate_snapshot == binding_snapshot(bindings)
            and delegate_cases is cases
            and len(delegate_cases) == len(cases)
            and all(
                actual is expected for actual, expected in zip(delegate_cases, cases, strict=True)
            )
            and delegate_phase == "open"
        )
    except Exception:
        composition_valid = False
    if not composition_valid:
        _fail("managed_policy_delegate_capability_binding_invalid")
    capability = ManagedPolicyDelegateCapability(_token=_TOKEN)
    _store(
        capability,
        _CapabilityState(
            delegate,
            bindings,
            snapshot,
            targets,
            corpus_ids,
            cases,
            implementation,
            "issued",
            b"",
        ),
    )
    return capability


def consume_managed_policy_delegate_capability(
    capability: object,
    *,
    bindings: FullComparisonRunBindings,
    cases: tuple[ManagedRunCase, ...],
) -> tuple[ManagedPolicyDelegatePort, str]:
    """Atomically consume an authority for the exact bound registry composition."""

    with _LOCK:
        state = _state_locked(capability)
        try:
            snapshot, targets = _binding_material(bindings)
            corpora = _corpus_ids(cases)
            current = _authenticate_exact_delegate(state.delegate)
            valid = (
                state.phase == "issued"
                and bindings is state.bindings
                and snapshot == state.binding_snapshot
                and targets == state.target_pairs
                and corpora == state.corpus_ids
                and len(cases) == len(state.cases)
                and all(
                    actual is expected for actual, expected in zip(cases, state.cases, strict=True)
                )
                and hmac.compare_digest(current, state.implementation_sha256)
            )
        except ManagedPolicyDelegateCapabilityError:
            raise
        except Exception:
            valid = False
        if not valid:
            code = (
                "managed_policy_delegate_capability_replay"
                if state.phase == "consumed"
                else "managed_policy_delegate_capability_binding_invalid"
            )
            _fail(code)
        _store_locked(
            capability,
            replace(state, phase="consumed", integrity_mac=b""),
        )
        port = ManagedPolicyDelegatePort(_token=_TOKEN)
        _store_port_locked(
            port,
            _PortState(state.delegate, state.implementation_sha256, b""),
        )
        return port, state.implementation_sha256


def authenticate_trusted_managed_policy_delegate(delegate: object) -> str:
    """Revalidate the one currently admitted exact legacy implementation."""

    if type(delegate) is not ManagedComparisonHttpPolicyLifecycleAdapter:
        _fail("managed_policy_delegate_capability_delegate_invalid")
    implementation = managed_http_policy_lifecycle_implementation_sha256()
    if delegate.adapter_id != MANAGED_HTTP_POLICY_ADAPTER_ID or not hmac.compare_digest(
        delegate.implementation_sha256,
        implementation,
    ):
        _fail("managed_policy_delegate_capability_delegate_changed")
    return implementation


def _authenticate_trusted_managed_v5_policy_delegate(delegate: object) -> str:
    from infinity_context_server.memory_comparison_managed_v5_policy_lifecycle import (
        MANAGED_V5_POLICY_ADAPTER_ID,
        ManagedInfinityV5PolicyLifecycleAdapter,
        managed_v5_policy_lifecycle_implementation_sha256,
    )

    if type(delegate) is not ManagedInfinityV5PolicyLifecycleAdapter:
        _fail("managed_policy_delegate_capability_delegate_invalid")
    implementation = managed_v5_policy_lifecycle_implementation_sha256()
    if delegate.adapter_id != MANAGED_V5_POLICY_ADAPTER_ID or not hmac.compare_digest(
        delegate.implementation_sha256,
        implementation,
    ):
        _fail("managed_policy_delegate_capability_delegate_changed")
    return implementation


def _authenticate_exact_delegate(delegate: object) -> str:
    if type(delegate) is ManagedComparisonHttpPolicyLifecycleAdapter:
        return authenticate_trusted_managed_policy_delegate(delegate)
    return _authenticate_trusted_managed_v5_policy_delegate(delegate)


def authenticate_managed_policy_delegate_port(port: object) -> str:
    """Authenticate a live exact forwarding port without exposing its delegate."""

    with _LOCK:
        return _port_state_locked(port).implementation_sha256


def _trusted_port_delegate(
    port: ManagedPolicyDelegatePort,
) -> object:
    with _LOCK:
        state = _port_state_locked(port)
        current = _authenticate_exact_delegate(state.delegate)
        if not hmac.compare_digest(current, state.implementation_sha256):
            _fail("managed_policy_delegate_port_changed")
        return state.delegate


def _binding_material(
    bindings: object,
) -> tuple[tuple[object, ...], tuple[tuple[str, str], ...]]:
    if type(bindings) is not FullComparisonRunBindings:
        _fail("managed_policy_delegate_capability_binding_invalid")
    try:
        targets = tuple(
            (item.backend_role, item.target_identity_sha256) for item in bindings.backend_targets
        )
        snapshot = (
            bindings.run_id,
            bindings.profile_id,
            bindings.binding_commitment_sha256,
            bindings.backend_targets,
        )
    except Exception:
        _fail("managed_policy_delegate_capability_binding_invalid")
    if not targets or len(set(targets)) != len(targets):
        _fail("managed_policy_delegate_capability_binding_invalid")
    return snapshot, targets


def _corpus_ids(cases: object) -> tuple[str, ...]:
    if (
        type(cases) is not tuple
        or not cases
        or any(type(item) is not ManagedRunCase for item in cases)
    ):
        _fail("managed_policy_delegate_capability_corpora_invalid")
    corpus_ids = tuple(dict.fromkeys(item.corpus_id for item in cases))
    if any(not item or item != item.strip() for item in corpus_ids):
        _fail("managed_policy_delegate_capability_corpora_invalid")
    return corpus_ids


def _state_locked(value: object) -> _CapabilityState:
    if type(value) is not ManagedPolicyDelegateCapability:
        _fail("managed_policy_delegate_capability_invalid")
    state = _CAPABILITIES.get(value)
    if state is None:
        _fail("managed_policy_delegate_capability_unknown")
    if not hmac.compare_digest(
        state.integrity_mac,
        _mac(value, replace(state, integrity_mac=b"")),
    ):
        _fail("managed_policy_delegate_capability_changed")
    return state


def _store(capability: ManagedPolicyDelegateCapability, state: _CapabilityState) -> None:
    with _LOCK:
        _store_locked(capability, state)


def _store_locked(
    capability: ManagedPolicyDelegateCapability,
    state: _CapabilityState,
) -> None:
    _CAPABILITIES[capability] = replace(
        state,
        integrity_mac=_mac(capability, replace(state, integrity_mac=b"")),
    )


def _port_state_locked(value: object) -> _PortState:
    if type(value) is not ManagedPolicyDelegatePort:
        _fail("managed_policy_delegate_port_invalid")
    state = _PORTS.get(value)
    if state is None:
        _fail("managed_policy_delegate_port_unknown")
    if not hmac.compare_digest(
        state.integrity_mac,
        _port_mac(value, replace(state, integrity_mac=b"")),
    ):
        _fail("managed_policy_delegate_port_changed")
    return state


def _store_port_locked(port: ManagedPolicyDelegatePort, state: _PortState) -> None:
    _PORTS[port] = replace(
        state,
        integrity_mac=_port_mac(port, replace(state, integrity_mac=b"")),
    )


def _mac(capability: ManagedPolicyDelegateCapability, state: _CapabilityState) -> bytes:
    payload = {
        "capability_identity": id(capability),
        "delegate_identity": id(state.delegate),
        "bindings_identity": id(state.bindings),
        "binding_snapshot": tuple(str(item) for item in state.binding_snapshot),
        "targets": state.target_pairs,
        "corpora": state.corpus_ids,
        "cases": tuple((id(item), item.case_id, item.corpus_id) for item in state.cases),
        "implementation": state.implementation_sha256,
        "phase": state.phase,
    }
    return hmac.new(
        _SECRET,
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(),
        hashlib.sha256,
    ).digest()


def _port_mac(port: ManagedPolicyDelegatePort, state: _PortState) -> bytes:
    payload = {
        "port_identity": id(port),
        "delegate_identity": id(state.delegate),
        "implementation": state.implementation_sha256,
    }
    return hmac.new(
        _SECRET,
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(),
        hashlib.sha256,
    ).digest()


def _fail(code: str) -> NoReturn:
    raise ManagedPolicyDelegateCapabilityError(code)


_CAPABILITIES = weakref.WeakKeyDictionary()
_PORTS = weakref.WeakKeyDictionary()


__all__ = (
    "ManagedPolicyDelegateCapability",
    "ManagedPolicyDelegateCapabilityError",
    "ManagedPolicyDelegatePort",
    "authenticate_managed_policy_delegate_port",
    "authenticate_trusted_managed_policy_delegate",
    "consume_managed_policy_delegate_capability",
)

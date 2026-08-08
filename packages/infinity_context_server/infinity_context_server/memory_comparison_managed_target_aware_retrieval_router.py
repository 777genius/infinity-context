"""Target-aware provider-neutral routing for managed retrieval delegates."""

from __future__ import annotations

import hashlib
import json
import re
import threading
import weakref
from collections.abc import Mapping
from dataclasses import dataclass
from typing import final

from infinity_context_server.memory_comparison_gold_blind_answer_contract import (
    gold_blind_evidence_identity,
)
from infinity_context_server.memory_comparison_managed_retrieval_port import (
    ManagedRetrievalAuthority,
    ManagedRetrievalPort,
    ManagedRetrievalResult,
    _validate_managed_retrieval_authority,
)
from infinity_context_server.memory_comparison_managed_run_contract import (
    ManagedAnswerCase,
    ManagedRunCase,
)
from infinity_context_server.memory_comparison_managed_runner_binding import (
    ManagedRunnerCompositionBinding,
)
from infinity_context_server.memory_comparison_retrieval_policy import (
    NEUTRAL_COMPARISON_RETRIEVAL_POLICY,
)

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ADAPTER_ID = "managed-target-aware-retrieval-router.v1"


def _semantic_implementation_sha256() -> str:
    material = {
        "adapter_id": _ADAPTER_ID,
        "authority_policy": "delegate-issued-router-registered",
        "delegate_implementation_policy": "exact-if-reported-otherwise-frozen-route",
        "fallback": False,
        "result_policy": "exact-neutral-metadata-and-evidence-identity",
        "route_policy": "ordered-exact-composition-targets",
    }
    return hashlib.sha256(
        json.dumps(material, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


_IMPLEMENTATION_SHA256 = _semantic_implementation_sha256()
_LOCK = threading.RLock()


class ManagedTargetAwareRetrievalRouterError(RuntimeError):
    pass


@final
@dataclass(frozen=True, slots=True)
class ManagedTargetAwareRetrievalRoute:
    backend_role: str
    target_identity_sha256: str
    delegate: ManagedRetrievalPort
    adapter_id: str
    implementation_sha256: str

    def __post_init__(self) -> None:
        if (
            type(self.backend_role) is not str
            or _ID.fullmatch(self.backend_role) is None
            or type(self.target_identity_sha256) is not str
            or _SHA256.fullmatch(self.target_identity_sha256) is None
            or self.delegate is None
            or type(self.adapter_id) is not str
            or _ID.fullmatch(self.adapter_id) is None
            or type(self.implementation_sha256) is not str
            or _SHA256.fullmatch(self.implementation_sha256) is None
        ):
            raise ManagedTargetAwareRetrievalRouterError(
                "managed_target_retrieval_route_graph_invalid"
            )


@dataclass(frozen=True, slots=True)
class _RouteState:
    descriptor: ManagedTargetAwareRetrievalRoute
    backend_role: str
    target_identity_sha256: str
    delegate: ManagedRetrievalPort
    adapter_id: str
    implementation_sha256: str


@dataclass(frozen=True, slots=True)
class _RouterState:
    binding: ManagedRunnerCompositionBinding
    routes: tuple[_RouteState, ...]
    route_graph_commitment_sha256: str


@dataclass(frozen=True, slots=True)
class _IssuedAuthorityState:
    router: ManagedTargetAwareRetrievalRouter
    route: _RouteState


_ROUTERS: weakref.WeakKeyDictionary[ManagedTargetAwareRetrievalRouter, _RouterState]
_ISSUED_AUTHORITIES: weakref.WeakKeyDictionary[ManagedRetrievalAuthority, _IssuedAuthorityState]


@final
class ManagedTargetAwareRetrievalRouter:
    """Route an exact bound target to one delegate without fallback."""

    __slots__ = ("__weakref__",)

    def __init__(
        self,
        *,
        composition_binding: ManagedRunnerCompositionBinding,
        routes: tuple[ManagedTargetAwareRetrievalRoute, ...],
    ) -> None:
        if type(composition_binding) is not ManagedRunnerCompositionBinding:
            raise ManagedTargetAwareRetrievalRouterError(
                "managed_target_retrieval_composition_invalid"
            )
        route_states = _validate_and_snapshot_routes(composition_binding, routes)
        state = _RouterState(
            binding=composition_binding,
            routes=route_states,
            route_graph_commitment_sha256=_route_graph_commitment(route_states),
        )
        with _LOCK:
            _ROUTERS[self] = state

    @property
    def composition_binding(self) -> ManagedRunnerCompositionBinding:
        return _router_state(self).binding

    @property
    def adapter_id(self) -> str:
        _router_state(self)
        return _ADAPTER_ID

    @property
    def implementation_sha256(self) -> str:
        _router_state(self)
        return _IMPLEMENTATION_SHA256

    def authority_for(
        self, *, backend_role: str, target_identity_sha256: str
    ) -> ManagedRetrievalAuthority:
        state = _router_state(self)
        route = _select_route(state, backend_role, target_identity_sha256)
        try:
            authority = route.delegate.authority_for(
                backend_role=backend_role,
                target_identity_sha256=target_identity_sha256,
            )
            issued_pair = _validate_managed_retrieval_authority(
                authority,
                composition_binding=state.binding,
            )
        except Exception:
            raise ManagedTargetAwareRetrievalRouterError(
                "managed_target_retrieval_authority_invalid"
            ) from None
        if issued_pair != (route.backend_role, route.target_identity_sha256):
            raise ManagedTargetAwareRetrievalRouterError(
                "managed_target_retrieval_authority_invalid"
            )
        with _LOCK:
            if authority in _ISSUED_AUTHORITIES:
                raise ManagedTargetAwareRetrievalRouterError(
                    "managed_target_retrieval_authority_invalid"
                )
            _ISSUED_AUTHORITIES[authority] = _IssuedAuthorityState(self, route)
        return authority

    def retrieve(
        self,
        *,
        authority: ManagedRetrievalAuthority,
        case: ManagedRunCase,
        query: ManagedAnswerCase,
    ) -> ManagedRetrievalResult:
        state = _router_state(self)
        route = _issued_route(authority, router=self, state=state)
        if (
            type(case) is not ManagedRunCase
            or type(query) is not ManagedAnswerCase
            or case.case_id != query.case_id
        ):
            raise ManagedTargetAwareRetrievalRouterError("managed_target_retrieval_request_invalid")
        try:
            result = route.delegate.retrieve(authority=authority, case=case, query=query)
        except Exception:
            raise ManagedTargetAwareRetrievalRouterError(
                "managed_target_retrieval_failed"
            ) from None
        _validate_delegate_result(result, route)
        metadata = dict(result.metadata)
        metadata.update(
            {
                "adapter_id": _ADAPTER_ID,
                "implementation_sha256": _IMPLEMENTATION_SHA256,
                "delegate_adapter_id": route.adapter_id,
                "delegate_implementation_sha256": route.implementation_sha256,
                "route_graph_commitment_sha256": state.route_graph_commitment_sha256,
                "backend_role": route.backend_role,
                "target_identity_sha256": route.target_identity_sha256,
                "retrieval_policy": NEUTRAL_COMPARISON_RETRIEVAL_POLICY.telemetry(),
                "gold_fields_forwarded": False,
                "retries": 0,
            }
        )
        try:
            return ManagedRetrievalResult(
                evidence=result.evidence,
                retrieval_identity=result.retrieval_identity,
                metadata=metadata,
            )
        except Exception:
            raise ManagedTargetAwareRetrievalRouterError(
                "managed_target_retrieval_result_invalid"
            ) from None

    def __repr__(self) -> str:
        return "ManagedTargetAwareRetrievalRouter(<redacted>)"


def _validate_and_snapshot_routes(
    binding: ManagedRunnerCompositionBinding,
    routes: object,
) -> tuple[_RouteState, ...]:
    if (
        type(routes) is not tuple
        or not routes
        or any(type(route) is not ManagedTargetAwareRetrievalRoute for route in routes)
    ):
        raise ManagedTargetAwareRetrievalRouterError("managed_target_retrieval_route_graph_invalid")
    expected = tuple(
        (target.backend_role, target.target_identity_sha256) for target in binding.backend_targets
    )
    actual = tuple((route.backend_role, route.target_identity_sha256) for route in routes)
    if actual != expected:
        raise ManagedTargetAwareRetrievalRouterError("managed_target_retrieval_route_graph_invalid")
    states: list[_RouteState] = []
    for route in routes:
        try:
            delegate_binding = route.delegate.composition_binding
            authority_for = route.delegate.authority_for
            retrieve = route.delegate.retrieve
        except Exception:
            raise ManagedTargetAwareRetrievalRouterError(
                "managed_target_retrieval_route_graph_invalid"
            ) from None
        if delegate_binding is not binding or not callable(authority_for) or not callable(retrieve):
            raise ManagedTargetAwareRetrievalRouterError(
                "managed_target_retrieval_route_graph_invalid"
            )
        states.append(
            _RouteState(
                route,
                route.backend_role,
                route.target_identity_sha256,
                route.delegate,
                route.adapter_id,
                route.implementation_sha256,
            )
        )
    return tuple(states)


def _router_state(value: object) -> _RouterState:
    if type(value) is not ManagedTargetAwareRetrievalRouter:
        raise ManagedTargetAwareRetrievalRouterError("managed_target_retrieval_composition_invalid")
    with _LOCK:
        state = _ROUTERS.get(value)
    if state is None:
        raise ManagedTargetAwareRetrievalRouterError("managed_target_retrieval_composition_invalid")
    current = _validate_and_snapshot_routes(
        state.binding, tuple(route.descriptor for route in state.routes)
    )
    if (
        current != state.routes
        or _route_graph_commitment(current) != state.route_graph_commitment_sha256
    ):
        raise ManagedTargetAwareRetrievalRouterError("managed_target_retrieval_route_graph_invalid")
    return state


def _select_route(
    state: _RouterState,
    backend_role: object,
    target_identity_sha256: object,
) -> _RouteState:
    matches = tuple(
        route
        for route in state.routes
        if route.backend_role == backend_role
        and route.target_identity_sha256 == target_identity_sha256
    )
    if len(matches) != 1:
        raise ManagedTargetAwareRetrievalRouterError("managed_target_retrieval_authority_invalid")
    return matches[0]


def _issued_route(
    authority: object,
    *,
    router: ManagedTargetAwareRetrievalRouter,
    state: _RouterState,
) -> _RouteState:
    try:
        pair = _validate_managed_retrieval_authority(
            authority,
            composition_binding=state.binding,
        )
    except Exception:
        raise ManagedTargetAwareRetrievalRouterError(
            "managed_target_retrieval_authority_invalid"
        ) from None
    with _LOCK:
        issued = _ISSUED_AUTHORITIES.get(authority)
    if (
        issued is None
        or issued.router is not router
        or issued.route not in state.routes
        or pair != (issued.route.backend_role, issued.route.target_identity_sha256)
    ):
        raise ManagedTargetAwareRetrievalRouterError("managed_target_retrieval_authority_invalid")
    return issued.route


def _validate_delegate_result(result: object, route: _RouteState) -> None:
    if type(result) is not ManagedRetrievalResult:
        raise ManagedTargetAwareRetrievalRouterError("managed_target_retrieval_result_invalid")
    metadata = result.metadata
    try:
        valid = (
            result.retrieval_identity == gold_blind_evidence_identity(result.evidence)
            and metadata["adapter_id"] == route.adapter_id
            and (
                "implementation_sha256" not in metadata
                or metadata["implementation_sha256"] == route.implementation_sha256
            )
            and metadata["backend_role"] == route.backend_role
            and metadata["target_identity_sha256"] == route.target_identity_sha256
            and _plain_json(metadata["retrieval_policy"])
            == _plain_json(NEUTRAL_COMPARISON_RETRIEVAL_POLICY.telemetry())
            and type(metadata["gold_fields_forwarded"]) is bool
            and metadata["gold_fields_forwarded"] is False
            and type(metadata["retries"]) is int
            and metadata["retries"] == 0
        )
    except Exception:
        valid = False
    if not valid:
        raise ManagedTargetAwareRetrievalRouterError("managed_target_retrieval_result_invalid")


def _plain_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _plain_json(item) for key, item in value.items()}
    if type(value) in {tuple, list}:
        return [_plain_json(item) for item in value]
    return value


def _route_graph_commitment(routes: tuple[_RouteState, ...]) -> str:
    material = json.dumps(
        [
            {
                "backend_role": route.backend_role,
                "target_identity_sha256": route.target_identity_sha256,
                "adapter_id": route.adapter_id,
                "implementation_sha256": route.implementation_sha256,
            }
            for route in routes
        ],
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(material).hexdigest()


def managed_target_aware_retrieval_router_implementation_sha256() -> str:
    return _IMPLEMENTATION_SHA256


_ROUTERS = weakref.WeakKeyDictionary()
_ISSUED_AUTHORITIES = weakref.WeakKeyDictionary()


__all__ = (
    "ManagedTargetAwareRetrievalRoute",
    "ManagedTargetAwareRetrievalRouter",
    "ManagedTargetAwareRetrievalRouterError",
    "managed_target_aware_retrieval_router_implementation_sha256",
)

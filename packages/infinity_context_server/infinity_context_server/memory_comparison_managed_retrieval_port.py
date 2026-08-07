"""Provider-neutral managed retrieval authority, result, and port."""

from __future__ import annotations

import math
import re
import threading
import weakref
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol, final

from infinity_context_server.memory_comparison_gold_blind_answer_contract import (
    GoldBlindEvidence,
    gold_blind_evidence_identity,
)
from infinity_context_server.memory_comparison_managed_run_contract import (
    ManagedAnswerCase,
    ManagedRunCase,
)
from infinity_context_server.memory_comparison_managed_runner_binding import (
    ManagedRunnerCompositionBinding,
)

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_AUTHORITY_TOKEN = object()
_AUTHORITY_LOCK = threading.RLock()


class ManagedRetrievalPortError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class _AuthorityState:
    binding: ManagedRunnerCompositionBinding
    backend_role: str
    target_identity_sha256: str


_AUTHORITIES: weakref.WeakKeyDictionary[ManagedRetrievalAuthority, _AuthorityState]


@final
class ManagedRetrievalAuthority:
    __slots__ = ("__weakref__", "_backend_role", "_binding", "_target_identity")

    def __init__(
        self,
        *,
        composition_binding: ManagedRunnerCompositionBinding,
        backend_role: str,
        target_identity_sha256: str,
        _token: object,
    ) -> None:
        if type(composition_binding) is not ManagedRunnerCompositionBinding:
            raise ManagedRetrievalPortError("managed_retrieval_authority_invalid")
        expected = tuple(
            (item.backend_role, item.target_identity_sha256)
            for item in composition_binding.backend_targets
        )
        if (
            _token is not _AUTHORITY_TOKEN
            or type(backend_role) is not str
            or _ID.fullmatch(backend_role) is None
            or type(target_identity_sha256) is not str
            or _SHA256.fullmatch(target_identity_sha256) is None
            or (backend_role, target_identity_sha256) not in expected
        ):
            raise ManagedRetrievalPortError("managed_retrieval_authority_invalid")
        self._binding = composition_binding
        self._backend_role = backend_role
        self._target_identity = target_identity_sha256
        with _AUTHORITY_LOCK:
            _AUTHORITIES[self] = _AuthorityState(
                composition_binding,
                backend_role,
                target_identity_sha256,
            )

    @property
    def composition_binding(self) -> ManagedRunnerCompositionBinding:
        return _authority_state(self).binding

    @property
    def backend_role(self) -> str:
        return _authority_state(self).backend_role

    @property
    def target_identity_sha256(self) -> str:
        return _authority_state(self).target_identity_sha256

    def __repr__(self) -> str:
        return "ManagedRetrievalAuthority(<redacted>)"

    def __reduce__(self) -> object:
        raise TypeError("ManagedRetrievalAuthority is nonserializable")

    def __reduce_ex__(self, protocol: int) -> object:
        del protocol
        raise TypeError("ManagedRetrievalAuthority is nonserializable")


def _issue_managed_retrieval_authority(
    binding: ManagedRunnerCompositionBinding,
    *,
    backend_role: str,
    target_identity_sha256: str,
) -> ManagedRetrievalAuthority:
    return ManagedRetrievalAuthority(
        composition_binding=binding,
        backend_role=backend_role,
        target_identity_sha256=target_identity_sha256,
        _token=_AUTHORITY_TOKEN,
    )


def _validate_managed_retrieval_authority(
    value: object,
    *,
    composition_binding: ManagedRunnerCompositionBinding,
) -> tuple[str, str]:
    state = _authority_state(value)
    if state.binding is not composition_binding:
        raise ManagedRetrievalPortError("managed_retrieval_authority_invalid")
    return state.backend_role, state.target_identity_sha256


def _authority_state(value: object) -> _AuthorityState:
    if type(value) is not ManagedRetrievalAuthority:
        raise ManagedRetrievalPortError("managed_retrieval_authority_invalid")
    with _AUTHORITY_LOCK:
        state = _AUTHORITIES.get(value)
    if (
        state is None
        or value._binding is not state.binding
        or value._backend_role != state.backend_role
        or value._target_identity != state.target_identity_sha256
    ):
        raise ManagedRetrievalPortError("managed_retrieval_authority_invalid")
    return state


@final
@dataclass(frozen=True, slots=True)
class ManagedRetrievalResult:
    evidence: tuple[GoldBlindEvidence, ...]
    retrieval_identity: str
    metadata: Mapping[str, object]

    def __post_init__(self) -> None:
        if (
            type(self.evidence) is not tuple
            or any(type(item) is not GoldBlindEvidence for item in self.evidence)
            or type(self.retrieval_identity) is not str
            or _SHA256.fullmatch(self.retrieval_identity) is None
            or self.retrieval_identity != gold_blind_evidence_identity(self.evidence)
            or type(self.metadata) not in {dict, MappingProxyType}
        ):
            raise ManagedRetrievalPortError("managed_retrieval_result_invalid")
        object.__setattr__(self, "metadata", _freeze_json(dict(self.metadata)))


class ManagedRetrievalPort(Protocol):
    @property
    def composition_binding(self) -> ManagedRunnerCompositionBinding: ...

    def authority_for(
        self, *, backend_role: str, target_identity_sha256: str
    ) -> ManagedRetrievalAuthority: ...

    def retrieve(
        self,
        *,
        authority: ManagedRetrievalAuthority,
        case: ManagedRunCase,
        query: ManagedAnswerCase,
    ) -> ManagedRetrievalResult: ...


def _freeze_json(value: object, *, depth: int = 0) -> object:
    if depth > 12:
        raise ManagedRetrievalPortError("managed_retrieval_metadata_invalid")
    if value is None or type(value) in {str, bool, int}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ManagedRetrievalPortError("managed_retrieval_metadata_invalid")
        return value
    if type(value) in {list, tuple}:
        return tuple(_freeze_json(item, depth=depth + 1) for item in value)
    if type(value) in {dict, MappingProxyType} and all(type(key) is str for key in value):
        return MappingProxyType(
            {key: _freeze_json(item, depth=depth + 1) for key, item in value.items()}
        )
    raise ManagedRetrievalPortError("managed_retrieval_metadata_invalid")


_AUTHORITIES = weakref.WeakKeyDictionary()


__all__ = (
    "ManagedRetrievalAuthority",
    "ManagedRetrievalPort",
    "ManagedRetrievalPortError",
    "ManagedRetrievalResult",
)

"""In-memory repository and unit-of-work seam for memory_scopes adapters."""

from __future__ import annotations

from collections.abc import Iterable
from types import TracebackType
from typing import ClassVar

from infinity_context_core.features.memory_scopes.public import (
    FEATURE_ID,
    MemoryScopeIdentity,
    MemoryScopeRepositoryPort,
    MemoryScopeSnapshot,
    MemoryScopeUnitOfWorkFactoryPort,
)

_ScopeKey = tuple[str, str]
_ExternalRefKey = tuple[str, str]


class _InMemoryMemoryScopeState:
    def __init__(self, scopes: Iterable[MemoryScopeSnapshot] = ()) -> None:
        self._scopes: dict[_ScopeKey, MemoryScopeSnapshot] = {}
        for scope in scopes:
            self._put(scope, allow_existing=False)

    def snapshot(self) -> dict[_ScopeKey, MemoryScopeSnapshot]:
        return dict(self._scopes)

    def replace(self, scopes: dict[_ScopeKey, MemoryScopeSnapshot]) -> None:
        self._scopes = dict(scopes)

    def _put(
        self,
        scope: MemoryScopeSnapshot,
        *,
        allow_existing: bool,
    ) -> None:
        key = _scope_key(scope.identity)
        if not allow_existing and key in self._scopes:
            raise ValueError("memory_scope_already_exists")
        _ensure_external_ref_is_unique(scope, self._scopes, current_key=key)
        self._scopes[key] = scope


class InMemoryMemoryScopeRepository:
    """Stdlib-only MemoryScopeRepositoryPort implementation."""

    adapter_name: ClassVar[str] = "in_memory"
    feature_id: ClassVar[str] = FEATURE_ID

    def __init__(self, scopes: dict[_ScopeKey, MemoryScopeSnapshot] | None = None) -> None:
        self._scopes = scopes if scopes is not None else {}

    async def create(self, scope: MemoryScopeSnapshot) -> MemoryScopeSnapshot:
        key = _scope_key(scope.identity)
        if key in self._scopes:
            raise ValueError("memory_scope_already_exists")
        _ensure_external_ref_is_unique(scope, self._scopes, current_key=key)
        self._scopes[key] = scope
        return scope

    async def get(
        self,
        identity: MemoryScopeIdentity,
    ) -> MemoryScopeSnapshot | None:
        return self._scopes.get(_scope_key(identity))

    async def get_for_update(
        self,
        identity: MemoryScopeIdentity,
    ) -> MemoryScopeSnapshot | None:
        return await self.get(identity)

    async def get_by_external_ref(
        self,
        space_id: str,
        external_ref: str,
    ) -> MemoryScopeSnapshot | None:
        key = (space_id, external_ref)
        for scope in self._scopes.values():
            if _external_ref_key(scope) == key:
                return scope
        return None

    async def save(self, scope: MemoryScopeSnapshot) -> MemoryScopeSnapshot:
        key = _scope_key(scope.identity)
        if key not in self._scopes:
            raise KeyError("memory_scope_not_found")
        _ensure_external_ref_is_unique(scope, self._scopes, current_key=key)
        self._scopes[key] = scope
        return scope


class InMemoryMemoryScopeUnitOfWork:
    """Transactional unit-of-work seam backed by in-memory snapshots."""

    adapter_name: ClassVar[str] = "in_memory"
    feature_id: ClassVar[str] = FEATURE_ID

    def __init__(self, state: _InMemoryMemoryScopeState | None = None) -> None:
        self._state = state or _InMemoryMemoryScopeState()
        self._working_scopes = self._state.snapshot()
        self.memory_scopes = InMemoryMemoryScopeRepository(self._working_scopes)
        self._committed = False

    async def __aenter__(self) -> InMemoryMemoryScopeUnitOfWork:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _tb: TracebackType | None,
    ) -> None:
        if exc_type is not None or not self._committed:
            await self.rollback()

    async def commit(self) -> None:
        self._state.replace(self._working_scopes)
        self._committed = True

    async def rollback(self) -> None:
        self._working_scopes = self._state.snapshot()
        self.memory_scopes = InMemoryMemoryScopeRepository(self._working_scopes)
        self._committed = False


class InMemoryMemoryScopeUnitOfWorkFactory:
    """Factory that shares one in-memory canonical state across UoWs."""

    adapter_name: ClassVar[str] = "in_memory"
    feature_id: ClassVar[str] = FEATURE_ID

    def __init__(self, scopes: Iterable[MemoryScopeSnapshot] = ()) -> None:
        self._state = _InMemoryMemoryScopeState(scopes)

    def __call__(self) -> InMemoryMemoryScopeUnitOfWork:
        return InMemoryMemoryScopeUnitOfWork(self._state)


def create_in_memory_memory_scope_store(
    scopes: Iterable[MemoryScopeSnapshot] = (),
) -> MemoryScopeRepositoryPort:
    """Create a standalone in-memory memory scope repository."""

    return InMemoryMemoryScopeRepository(_InMemoryMemoryScopeState(scopes).snapshot())


def create_in_memory_memory_scope_unit_of_work_factory(
    scopes: Iterable[MemoryScopeSnapshot] = (),
) -> MemoryScopeUnitOfWorkFactoryPort:
    """Create an in-memory memory scope unit-of-work factory."""

    return InMemoryMemoryScopeUnitOfWorkFactory(scopes)


def _scope_key(identity: MemoryScopeIdentity) -> _ScopeKey:
    return (identity.space_id, identity.memory_scope_id)


def _external_ref_key(scope: MemoryScopeSnapshot) -> _ExternalRefKey | None:
    if scope.external_ref is None:
        return None
    return (scope.identity.space_id, scope.external_ref)


def _ensure_external_ref_is_unique(
    scope: MemoryScopeSnapshot,
    scopes: dict[_ScopeKey, MemoryScopeSnapshot],
    *,
    current_key: _ScopeKey,
) -> None:
    external_ref_key = _external_ref_key(scope)
    if external_ref_key is None:
        return

    for key, existing in scopes.items():
        if key != current_key and _external_ref_key(existing) == external_ref_key:
            raise ValueError("memory_scope_external_ref_already_exists")


__all__ = (
    "InMemoryMemoryScopeRepository",
    "InMemoryMemoryScopeUnitOfWork",
    "InMemoryMemoryScopeUnitOfWorkFactory",
    "create_in_memory_memory_scope_store",
    "create_in_memory_memory_scope_unit_of_work_factory",
)

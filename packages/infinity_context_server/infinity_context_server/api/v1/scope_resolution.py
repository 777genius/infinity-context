"""HTTP DTO scope resolution helpers for v1 routes."""

from __future__ import annotations

from dataclasses import dataclass

from infinity_context_core.application import EnsureScopeCommand
from infinity_context_core.domain.entities import MemoryScopeId, SpaceId, ThreadId
from infinity_context_core.domain.errors import MemoryValidationError
from infinity_context_core.ports.auth import MemoryWriteScope, ReadScope

from infinity_context_server.auth_scope import (
    canonical_scope_matches,
    resolve_existing_external_scope,
)
from infinity_context_server.composition import Container


@dataclass(frozen=True)
class SingleResolvedScope:
    space_id: SpaceId
    memory_scope_id: MemoryScopeId
    thread_id: ThreadId | None
    tenant_id: str | None = None
    workspace_id: str | None = None

    def __post_init__(self) -> None:
        self.to_memory_scope()

    def to_memory_scope(self) -> MemoryWriteScope:
        return MemoryWriteScope(
            space_id=str(self.space_id),
            memory_scope_id=str(self.memory_scope_id),
            thread_id=str(self.thread_id) if self.thread_id else None,
            tenant_id=self.tenant_id,
            workspace_id=self.workspace_id,
        )


@dataclass(frozen=True)
class ContextResolvedScope:
    space_id: SpaceId
    memory_scope_ids: tuple[MemoryScopeId, ...]
    thread_id: ThreadId | None
    tenant_id: str | None = None
    workspace_id: str | None = None

    def __post_init__(self) -> None:
        self.to_read_scope()

    def to_read_scope(self) -> ReadScope:
        return ReadScope(
            space_id=str(self.space_id),
            memory_scope_ids=tuple(
                str(memory_scope_id) for memory_scope_id in self.memory_scope_ids
            ),
            thread_id=str(self.thread_id) if self.thread_id else None,
            tenant_id=self.tenant_id,
            workspace_id=self.workspace_id,
        )


async def resolve_single_scope(
    container: Container,
    *,
    space_id: str | None,
    memory_scope_id: str | None,
    thread_id: str | None,
    space_slug: str | None,
    memory_scope_external_ref: str | None,
    thread_external_ref: str | None,
    thread_required: bool,
) -> SingleResolvedScope:
    """Resolve either canonical IDs or human/external refs into a single scope."""

    scope = await _resolve_single_scope(
        container,
        space_id=space_id,
        memory_scope_id=memory_scope_id,
        thread_id=thread_id,
        space_slug=space_slug,
        memory_scope_external_ref=memory_scope_external_ref,
        thread_external_ref=thread_external_ref,
        thread_required=thread_required,
        create_missing_external_scope=True,
    )
    if scope is None:
        raise MemoryValidationError("External scope refs do not exist")
    return scope


async def resolve_existing_single_scope(
    container: Container,
    *,
    space_id: str | None,
    memory_scope_id: str | None,
    thread_id: str | None,
    space_slug: str | None,
    memory_scope_external_ref: str | None,
    thread_external_ref: str | None,
    thread_required: bool,
) -> SingleResolvedScope | None:
    """Resolve scope for read paths without creating missing external refs."""

    return await _resolve_single_scope(
        container,
        space_id=space_id,
        memory_scope_id=memory_scope_id,
        thread_id=thread_id,
        space_slug=space_slug,
        memory_scope_external_ref=memory_scope_external_ref,
        thread_external_ref=thread_external_ref,
        thread_required=thread_required,
        create_missing_external_scope=False,
    )


async def _resolve_single_scope(
    container: Container,
    *,
    space_id: str | None,
    memory_scope_id: str | None,
    thread_id: str | None,
    space_slug: str | None,
    memory_scope_external_ref: str | None,
    thread_external_ref: str | None,
    thread_required: bool,
    create_missing_external_scope: bool,
) -> SingleResolvedScope | None:
    using_ids = bool(space_id or memory_scope_id or thread_id)
    using_external_refs = bool(space_slug or memory_scope_external_ref or thread_external_ref)

    if using_ids and using_external_refs:
        raise MemoryValidationError("Use either canonical ids or external scope refs, not both")

    if using_ids:
        return await _resolve_canonical_single_scope(
            container,
            space_id=space_id,
            memory_scope_id=memory_scope_id,
            thread_id=thread_id,
            thread_required=thread_required,
        )

    if thread_required and not thread_external_ref:
        raise MemoryValidationError("thread_external_ref is required for this operation")

    if create_missing_external_scope:
        scope = await container.ensure_scope.execute(
            EnsureScopeCommand(
                space_slug=space_slug or container.settings.default_space_slug,
                memory_scope_external_ref=(
                    memory_scope_external_ref
                    or container.settings.default_memory_scope_external_ref
                ),
                thread_external_ref=thread_external_ref,
            )
        )
        if thread_required and scope.thread_id is None:
            raise MemoryValidationError("thread scope could not be resolved")
        return SingleResolvedScope(
            space_id=scope.space_id,
            memory_scope_id=scope.memory_scope_id,
            thread_id=scope.thread_id,
        )

    existing = await resolve_existing_external_scope(
        container,
        space_slug=space_slug,
        memory_scope_external_ref=memory_scope_external_ref,
        thread_external_ref=thread_external_ref,
    )
    if existing is None:
        return None
    return SingleResolvedScope(
        space_id=SpaceId(existing.space_id),
        memory_scope_id=MemoryScopeId(existing.memory_scope_id),
        thread_id=ThreadId(existing.thread_id) if existing.thread_id else None,
    )


async def _resolve_canonical_single_scope(
    container: Container,
    *,
    space_id: str | None,
    memory_scope_id: str | None,
    thread_id: str | None,
    thread_required: bool,
) -> SingleResolvedScope:
    if not space_id or not memory_scope_id:
        raise MemoryValidationError(
            "space_id and memory_scope_id are required with canonical scope"
        )
    if thread_required and not thread_id:
        raise MemoryValidationError("thread_id is required for this operation")
    if not await canonical_scope_matches(
        container,
        space_id=space_id,
        memory_scope_ids=(memory_scope_id,),
        thread_id=thread_id,
    ):
        raise MemoryValidationError("Canonical scope ids do not belong together")
    return SingleResolvedScope(
        space_id=SpaceId(space_id),
        memory_scope_id=MemoryScopeId(memory_scope_id),
        thread_id=ThreadId(thread_id) if thread_id else None,
    )


async def resolve_context_scope(
    container: Container,
    *,
    space_id: str | None,
    memory_scope_ids: list[str] | None,
    thread_id: str | None,
    space_slug: str | None,
    memory_scope_external_ref: str | None,
    memory_scope_external_refs: list[str] | None,
    thread_external_ref: str | None,
) -> ContextResolvedScope:
    """Resolve context scope while preserving the existing ID-based contract."""

    scope = await _resolve_context_scope(
        container,
        space_id=space_id,
        memory_scope_ids=memory_scope_ids,
        thread_id=thread_id,
        space_slug=space_slug,
        memory_scope_external_ref=memory_scope_external_ref,
        memory_scope_external_refs=memory_scope_external_refs,
        thread_external_ref=thread_external_ref,
        create_missing_external_scope=True,
    )
    if scope is None:
        raise MemoryValidationError("External scope refs do not exist")
    return scope


async def resolve_existing_context_scope(
    container: Container,
    *,
    space_id: str | None,
    memory_scope_ids: list[str] | None,
    thread_id: str | None,
    space_slug: str | None,
    memory_scope_external_ref: str | None,
    memory_scope_external_refs: list[str] | None,
    thread_external_ref: str | None,
) -> ContextResolvedScope | None:
    """Resolve context scope for read paths without creating missing external refs."""

    return await _resolve_context_scope(
        container,
        space_id=space_id,
        memory_scope_ids=memory_scope_ids,
        thread_id=thread_id,
        space_slug=space_slug,
        memory_scope_external_ref=memory_scope_external_ref,
        memory_scope_external_refs=memory_scope_external_refs,
        thread_external_ref=thread_external_ref,
        create_missing_external_scope=False,
    )


async def _resolve_context_scope(
    container: Container,
    *,
    space_id: str | None,
    memory_scope_ids: list[str] | None,
    thread_id: str | None,
    space_slug: str | None,
    memory_scope_external_ref: str | None,
    memory_scope_external_refs: list[str] | None,
    thread_external_ref: str | None,
    create_missing_external_scope: bool,
) -> ContextResolvedScope | None:
    using_id_memory_scopes = bool(memory_scope_ids)
    using_external_scope = bool(
        space_slug or memory_scope_external_ref or memory_scope_external_refs
    )

    if using_id_memory_scopes and (using_external_scope or thread_external_ref):
        raise MemoryValidationError(
            "Use memory_scope_ids/thread_id or external memory_scope "
            "refs/thread_external_ref, not both"
        )
    if using_id_memory_scopes:
        return await _resolve_canonical_context_scope(
            container,
            space_id=space_id,
            memory_scope_ids=tuple(memory_scope_ids or []),
            thread_id=thread_id,
        )
    if space_id or thread_id:
        raise MemoryValidationError(
            "Canonical space_id/thread_id requires memory_scope_ids; external scope uses space_slug"
        )

    refs = _context_memory_scope_refs(
        container,
        memory_scope_external_ref=memory_scope_external_ref,
        memory_scope_external_refs=memory_scope_external_refs,
        thread_external_ref=thread_external_ref,
    )
    resolved: list[SingleResolvedScope] = []
    for ref in refs:
        scope = await _resolve_single_scope(
            container,
            space_id=None,
            memory_scope_id=None,
            thread_id=None,
            space_slug=space_slug,
            memory_scope_external_ref=ref,
            thread_external_ref=thread_external_ref,
            thread_required=False,
            create_missing_external_scope=create_missing_external_scope,
        )
        if scope is None and thread_external_ref and not create_missing_external_scope:
            scope = await _resolve_single_scope(
                container,
                space_id=None,
                memory_scope_id=None,
                thread_id=None,
                space_slug=space_slug,
                memory_scope_external_ref=ref,
                thread_external_ref=None,
                thread_required=False,
                create_missing_external_scope=False,
            )
        if scope is None:
            return None
        resolved.append(scope)

    space_ids = {scope.space_id for scope in resolved}
    if len(space_ids) != 1:
        raise MemoryValidationError("Resolved memory_scopes must belong to one space")
    return ContextResolvedScope(
        space_id=resolved[0].space_id,
        memory_scope_ids=tuple(scope.memory_scope_id for scope in resolved),
        thread_id=resolved[0].thread_id,
    )


async def _resolve_canonical_context_scope(
    container: Container,
    *,
    space_id: str | None,
    memory_scope_ids: tuple[str, ...],
    thread_id: str | None,
) -> ContextResolvedScope:
    if not space_id:
        raise MemoryValidationError("space_id is required with memory_scope_ids")
    if len(set(memory_scope_ids)) != len(memory_scope_ids):
        raise MemoryValidationError("memory_scope_ids cannot contain duplicates")
    if not await canonical_scope_matches(
        container,
        space_id=space_id,
        memory_scope_ids=memory_scope_ids,
        thread_id=thread_id,
    ):
        raise MemoryValidationError("Canonical scope ids do not belong together")
    return ContextResolvedScope(
        space_id=SpaceId(space_id),
        memory_scope_ids=tuple(
            MemoryScopeId(memory_scope_id) for memory_scope_id in memory_scope_ids
        ),
        thread_id=ThreadId(thread_id) if thread_id else None,
    )


def _context_memory_scope_refs(
    container: Container,
    *,
    memory_scope_external_ref: str | None,
    memory_scope_external_refs: list[str] | None,
    thread_external_ref: str | None,
) -> tuple[str, ...]:
    refs = tuple(memory_scope_external_refs or [])
    if memory_scope_external_ref:
        refs = (memory_scope_external_ref, *refs)
    if not refs:
        refs = (container.settings.default_memory_scope_external_ref,)
    if len(set(refs)) != len(refs):
        raise MemoryValidationError("memory_scope_external_refs must be unique")
    if len(refs) > 1 and thread_external_ref:
        raise MemoryValidationError(
            "thread_external_ref supports a single memory_scope for context"
        )
    return refs

"""Thin optional Graphiti adapter.

Graphiti is treated as a derived temporal graph. The adapter returns candidate
canonical ids only; application use cases hydrate through Postgres.
"""

from __future__ import annotations

import inspect
import re
from datetime import datetime
from typing import Any

from memo_stack_core.ports.adapters import (
    AdapterCapabilities,
    GraphCandidate,
    GraphSearchResult,
    PortDiagnostic,
    VectorWriteResult,
)
from memo_stack_core.ports.capabilities import (
    CapabilityDescriptor,
    CapabilityDiagnostic,
    CapabilityMode,
    CapabilityRecallCandidate,
    CapabilityRecallQuery,
    CapabilityRecallResult,
    CapabilityStatus,
    EngineHealthSnapshot,
    FactProjectionWrite,
    MemoryCapability,
    ProjectionForgetRequest,
    ProjectionForgetResult,
    ProjectionWriteResult,
)


class GraphitiGraphMemoryAdapter:
    def __init__(
        self,
        *,
        client: object | None = None,
        neo4j_uri: str | None = None,
        neo4j_user: str | None = None,
        neo4j_password: str | None = None,
        build_indices: bool = False,
        group_id_prefix: str = "memory",
    ) -> None:
        self._client = client
        self._neo4j_uri = neo4j_uri
        self._neo4j_user = neo4j_user
        self._neo4j_password = neo4j_password
        self._build_indices = build_indices
        self._indices_built = not build_indices
        self._group_id_prefix = group_id_prefix

    async def aclose(self) -> None:
        client = self._client
        self._client = None
        self._indices_built = not self._build_indices
        if client is None:
            return
        closed = await _close_if_present(client)
        if closed:
            return
        driver = getattr(client, "driver", None)
        driver_closed = await _close_if_present(driver)
        if driver_closed:
            return
        await _close_if_present(getattr(driver, "client", None))

    async def capabilities(self) -> AdapterCapabilities:
        try:
            client = await self._client_or_none()
        except Exception:
            client = None
        if client is None:
            configured = self._is_configured()
            return AdapterCapabilities(
                name="graphiti",
                enabled=False,
                healthy=not configured,
                supports_upsert=False,
                supports_delete=False,
                supports_search=False,
                supports_filters=False,
                supports_temporal_queries=True,
                degraded_reason="graphiti_unavailable" if configured else "disabled",
            )
        supports_upsert = getattr(client, "add_episode", None) is not None
        supports_delete = _supports_delete_episode(client)
        supports_search = getattr(client, "search", None) is not None
        if not supports_search:
            return AdapterCapabilities(
                name="graphiti",
                enabled=True,
                healthy=False,
                supports_upsert=supports_upsert,
                supports_delete=supports_delete,
                supports_search=False,
                supports_filters=False,
                supports_temporal_queries=True,
                degraded_reason="graphiti.capability_mismatch",
            )
        return AdapterCapabilities(
            name="graphiti",
            enabled=True,
            healthy=True,
            supports_upsert=supports_upsert,
            supports_delete=supports_delete,
            supports_search=supports_search,
            supports_filters=True,
            supports_temporal_queries=True,
        )

    async def capability_descriptors(self) -> tuple[CapabilityDescriptor, ...]:
        capabilities = await self.capabilities()
        return (
            _capability_descriptor(
                capabilities,
                MemoryCapability.TEMPORAL_FACT_GRAPH,
                supported=capabilities.supports_search and capabilities.supports_temporal_queries,
                supports_update=capabilities.supports_upsert,
                supports_delete=capabilities.supports_delete,
            ),
            _capability_descriptor(
                capabilities,
                MemoryCapability.FACT_PROJECTION,
                supported=capabilities.supports_upsert,
                supports_update=capabilities.supports_upsert,
            ),
            _capability_descriptor(
                capabilities,
                MemoryCapability.PROJECTION_FORGET,
                supported=capabilities.supports_delete,
                supports_delete=capabilities.supports_delete,
            ),
        )

    async def health(self) -> EngineHealthSnapshot:
        descriptors = await self.capability_descriptors()
        status = _overall_status(descriptors)
        return EngineHealthSnapshot(
            adapter_name="graphiti",
            status=status,
            capabilities=descriptors,
        )

    async def upsert_fact(
        self,
        fact_id: str,
        text: str,
        metadata: dict[str, str],
    ) -> VectorWriteResult:
        try:
            client = await self._client_or_none()
            if client is None:
                return self._unavailable_write_result()
            add_episode = getattr(client, "add_episode", None)
            if add_episode is None:
                return VectorWriteResult.degraded("graph.missing_add_episode", retryable=False)
            await _remove_existing_episode_if_supported(client, fact_id)
            kwargs = {
                "name": f"fact:{fact_id}",
                "episode_body": text,
                "group_id": self._group_id(
                    metadata.get("space_id", ""),
                    metadata.get("profile_id", ""),
                ),
                "source_description": "canonical_memory_fact",
                "reference_time": _reference_time(metadata.get("updated_at")),
            }
            episode_type = _episode_type_text()
            if episode_type is not None:
                kwargs["source"] = episode_type
            await add_episode(**kwargs)
            return VectorWriteResult.ok(1)
        except Exception:
            return VectorWriteResult.degraded("graph.upsert_failed", retryable=True)

    async def upsert_fact_projection(self, command: FactProjectionWrite) -> ProjectionWriteResult:
        result = await self.upsert_fact(
            command.fact_id,
            command.text,
            {
                "space_id": command.space_id,
                "profile_id": command.profile_id,
                **command.metadata,
                **({"updated_at": command.valid_at.isoformat()} if command.valid_at else {}),
            },
        )
        return _projection_write_result(result, affected_ids=(command.fact_id,))

    async def delete_fact(self, fact_id: str) -> VectorWriteResult:
        try:
            client = await self._client_or_none()
            if client is None:
                return self._unavailable_write_result()
            if not _supports_delete_episode(client):
                return VectorWriteResult.degraded("graph.missing_delete_episode", retryable=False)
            await _call_delete_episode(client, fact_id)
            return VectorWriteResult.ok(1)
        except Exception:
            return VectorWriteResult.degraded("graph.delete_failed", retryable=True)

    async def forget_projection(self, command: ProjectionForgetRequest) -> ProjectionForgetResult:
        forgotten: list[str] = []
        diagnostics: list[CapabilityDiagnostic] = []
        status = CapabilityStatus.OK
        for canonical_id in command.canonical_ids:
            result = await self.delete_fact(canonical_id)
            if result.status.value != "ok":
                status = CapabilityStatus.DEGRADED
                diagnostics.extend(_diagnostics(result.diagnostics))
            else:
                forgotten.append(canonical_id)
        return ProjectionForgetResult(
            status=status,
            forgotten_ids=tuple(forgotten),
            diagnostics=tuple(diagnostics),
        )

    async def search(
        self,
        *,
        space_id: str,
        profile_ids: tuple[str, ...],
        thread_id: str | None = None,
        query: str,
        limit: int,
    ) -> GraphSearchResult:
        if limit <= 0:
            return GraphSearchResult.ok(())
        try:
            client = await self._client_or_none()
            if client is None:
                if self._is_configured():
                    return GraphSearchResult.degraded("graph.unavailable", retryable=True)
                return GraphSearchResult.degraded("graph.disabled", retryable=False)
            search = getattr(client, "search", None)
            if search is None:
                return GraphSearchResult.degraded("graph.missing_search", retryable=False)
            candidates: list[GraphCandidate] = []
            effective_limit = _search_limit(limit, thread_id=thread_id)
            for profile_id in profile_ids:
                results = await _call_search(
                    search,
                    query=query,
                    group_id=self._group_id(space_id, profile_id),
                    limit=effective_limit,
                )
                for result in results:
                    fact_id = await _canonical_fact_id(client, result)
                    if fact_id:
                        candidates.append(
                            GraphCandidate(
                                source_fact_ids=(fact_id,),
                                source_chunk_ids=(),
                                relation_label="graphiti_candidate",
                                score=float(getattr(result, "score", 0.5)),
                                diagnostics={"provider": "graphiti"},
                            )
                        )
            return GraphSearchResult.ok(candidates[:effective_limit])
        except Exception:
            return GraphSearchResult.degraded("graph.search_failed", retryable=True)

    async def search_facts(self, query: CapabilityRecallQuery) -> CapabilityRecallResult:
        result = await self.search(
            space_id=query.scope.space_id,
            profile_ids=query.scope.profile_ids,
            thread_id=query.scope.thread_id,
            query=query.query,
            limit=query.limit,
        )
        status = CapabilityStatus.OK if result.status.value == "ok" else CapabilityStatus.DEGRADED
        candidates = tuple(
            CapabilityRecallCandidate(
                item_id=fact_id,
                item_type="fact",
                text=fact_id,
                score=candidate.score,
                source_refs=(),
                capability=MemoryCapability.TEMPORAL_FACT_GRAPH,
                adapter_name="graphiti",
                metadata={"hydration_required": "true"},
            )
            for candidate in result.items
            for fact_id in candidate.source_fact_ids
        )
        return CapabilityRecallResult(
            status=status,
            items=candidates[: query.limit],
            diagnostics=tuple(_diagnostics(result.diagnostics)),
        )

    def _group_id(self, space_id: str, profile_id: str) -> str:
        return "__".join(
            (
                _safe_group_id_part(self._group_id_prefix),
                _safe_group_id_part(space_id),
                _safe_group_id_part(profile_id),
            )
        )

    def _is_configured(self) -> bool:
        return self._client is not None or bool(
            self._neo4j_uri and self._neo4j_user and self._neo4j_password
        )

    def _unavailable_write_result(self) -> VectorWriteResult:
        if self._is_configured():
            return VectorWriteResult.degraded("graph.unavailable", retryable=True)
        return VectorWriteResult.degraded("graph.disabled", retryable=False)

    async def _client_or_none(self) -> object | None:
        if self._client is not None:
            await self._build_indices_once(self._client)
            return self._client
        if not self._neo4j_uri or not self._neo4j_user or not self._neo4j_password:
            return None
        try:
            from graphiti_core import Graphiti
        except Exception:
            return None
        self._client = Graphiti(self._neo4j_uri, self._neo4j_user, self._neo4j_password)
        await self._build_indices_once(self._client)
        return self._client

    async def _build_indices_once(self, client: object) -> None:
        if self._indices_built:
            return
        build = getattr(client, "build_indices_and_constraints", None)
        if build is not None:
            await build()
        self._indices_built = True


async def _canonical_fact_id(client: object, result: object) -> str | None:
    for attr in ("episodes", "episode_uuids"):
        value = getattr(result, attr, None)
        if isinstance(value, list | tuple):
            for item in value:
                fact_id = _extract_fact_id(item)
                if fact_id:
                    return fact_id
                if isinstance(item, str):
                    episode_name = await _episode_name_by_uuid(client, item)
                    fact_id = _extract_fact_id(episode_name)
                    if fact_id:
                        return fact_id
    for attr in ("fact_id", "source_fact_id", "uuid", "id", "name", "episode_name"):
        value = getattr(result, attr, None)
        fact_id = _extract_fact_id(value)
        if fact_id:
            return fact_id
    return None


async def _close_if_present(resource: object | None) -> bool:
    if resource is None:
        return False
    close = getattr(resource, "close", None)
    if not callable(close):
        return False
    result = close()
    if inspect.isawaitable(result):
        await result
    return True


def _capability_descriptor(
    capabilities: AdapterCapabilities,
    capability: MemoryCapability,
    *,
    supported: bool,
    supports_update: bool = False,
    supports_delete: bool = False,
) -> CapabilityDescriptor:
    status = _capability_status(capabilities, supported=supported)
    return CapabilityDescriptor(
        capability=capability,
        adapter_name="graphiti",
        mode=(
            CapabilityMode.DISABLED
            if status == CapabilityStatus.DISABLED
            else CapabilityMode.PRIMARY
        ),
        status=status,
        enabled=capabilities.enabled and supported,
        supports_scope_filter=capabilities.supports_filters,
        supports_source_refs=False,
        supports_update=supports_update,
        supports_delete=supports_delete,
        degraded_reason=_capability_degraded_reason(
            capabilities,
            status=status,
            supported=supported,
        ),
    )


def _capability_status(
    capabilities: AdapterCapabilities,
    *,
    supported: bool,
) -> CapabilityStatus:
    if not capabilities.enabled:
        return CapabilityStatus.DISABLED
    if not capabilities.healthy:
        return CapabilityStatus.UNAVAILABLE
    if not supported:
        return CapabilityStatus.DEGRADED
    return CapabilityStatus.OK


def _capability_degraded_reason(
    capabilities: AdapterCapabilities,
    *,
    status: CapabilityStatus,
    supported: bool,
) -> str | None:
    if status == CapabilityStatus.OK:
        return None
    if status == CapabilityStatus.DISABLED:
        return capabilities.degraded_reason or "disabled"
    if capabilities.degraded_reason:
        return capabilities.degraded_reason
    if not supported:
        return "unsupported_by_adapter"
    return capabilities.degraded_reason or "graphiti_unavailable"


def _overall_status(descriptors: tuple[CapabilityDescriptor, ...]) -> CapabilityStatus:
    statuses = {descriptor.status for descriptor in descriptors}
    if CapabilityStatus.OK in statuses:
        return CapabilityStatus.OK
    if CapabilityStatus.DEGRADED in statuses:
        return CapabilityStatus.DEGRADED
    if CapabilityStatus.UNAVAILABLE in statuses:
        return CapabilityStatus.UNAVAILABLE
    return CapabilityStatus.DISABLED


def _projection_write_result(
    result: VectorWriteResult,
    *,
    affected_ids: tuple[str, ...],
) -> ProjectionWriteResult:
    status = CapabilityStatus.OK if result.status.value == "ok" else CapabilityStatus.DEGRADED
    return ProjectionWriteResult(
        status=status,
        affected_ids=affected_ids if status == CapabilityStatus.OK else (),
        diagnostics=tuple(_diagnostics(result.diagnostics)),
    )


def _diagnostics(diagnostics: tuple[PortDiagnostic, ...]) -> list[CapabilityDiagnostic]:
    return [
        CapabilityDiagnostic(
            code=diagnostic.code,
            safe_message=diagnostic.safe_message,
            retryable=diagnostic.retryable,
            details=diagnostic.details,
        )
        for diagnostic in diagnostics
    ]


def _extract_fact_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    if value.startswith("fact:"):
        return value.removeprefix("fact:")
    if value.startswith("fact_"):
        return value
    return None


def _episode_type_text() -> object | None:
    try:
        from graphiti_core.nodes import EpisodeType
    except Exception:
        return None
    return EpisodeType.text


def _reference_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


async def _call_delete_episode(client: Any, fact_id: str) -> None:
    legacy_delete = getattr(client, "delete_episode", None)
    if legacy_delete is not None:
        try:
            await legacy_delete(name=f"fact:{fact_id}")
        except TypeError:
            await legacy_delete(f"fact:{fact_id}")
        return
    remove_episode = getattr(client, "remove_episode", None)
    if remove_episode is not None:
        removed = False
        for episode_uuid in await _episode_uuids_by_name(client, f"fact:{fact_id}"):
            try:
                await remove_episode(episode_uuid)
                removed = True
            except Exception as exc:
                if exc.__class__.__name__ != "NodeNotFoundError":
                    raise
        if removed:
            return
        try:
            await remove_episode(fact_id)
        except Exception as exc:
            if exc.__class__.__name__ != "NodeNotFoundError":
                raise


def _search_limit(limit: int, *, thread_id: str | None) -> int:
    if thread_id is None:
        return limit
    # Graphiti is grouped by space/profile; Postgres hydration enforces thread visibility.
    return min(max(limit * 4, limit), 100)


async def _call_search(search: Any, *, query: str, group_id: str, limit: int) -> list[object]:
    try:
        return list(await search(query=query, group_ids=[group_id], num_results=limit))
    except TypeError:
        try:
            return list(await search(query=query, group_id=group_id, num_results=limit))
        except TypeError:
            return list(await search(query, num_results=limit))


def _safe_group_id_part(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "_", value.strip())
    cleaned = cleaned.strip("_")
    return cleaned or "default"


def _supports_delete_episode(client: object) -> bool:
    return (
        getattr(client, "delete_episode", None) is not None
        or getattr(client, "remove_episode", None) is not None
    )


async def _remove_existing_episode_if_supported(client: object, fact_id: str) -> None:
    remove_episode = getattr(client, "remove_episode", None)
    if remove_episode is None:
        return
    removed = False
    for episode_uuid in await _episode_uuids_by_name(client, f"fact:{fact_id}"):
        try:
            await remove_episode(episode_uuid)
            removed = True
        except Exception as exc:
            if exc.__class__.__name__ != "NodeNotFoundError":
                raise
    if removed:
        return
    try:
        await remove_episode(fact_id)
    except Exception as exc:
        if exc.__class__.__name__ != "NodeNotFoundError":
            raise


async def _episode_uuids_by_name(client: object, name: str) -> tuple[str, ...]:
    driver = getattr(client, "driver", None)
    execute_query = getattr(driver, "execute_query", None)
    if execute_query is None:
        return ()
    try:
        records, *_ = await execute_query(
            "MATCH (e:Episodic {name: $name}) RETURN e.uuid AS uuid",
            name=name,
            routing_="r",
        )
    except Exception:
        return ()
    return tuple(str(record["uuid"]) for record in records if record.get("uuid"))


async def _episode_name_by_uuid(client: object, episode_uuid: str) -> str | None:
    driver = getattr(client, "driver", None)
    execute_query = getattr(driver, "execute_query", None)
    if execute_query is None:
        return None
    try:
        records, *_ = await execute_query(
            "MATCH (e:Episodic {uuid: $uuid}) RETURN e.name AS name",
            uuid=episode_uuid,
            routing_="r",
        )
    except Exception:
        return None
    for record in records:
        name = record.get("name")
        if isinstance(name, str):
            return name
    return None

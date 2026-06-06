"""Disabled-by-default Cognee memory adapter.

The adapter does not import Cognee or send memory text unless it is explicitly
enabled and configured. Recalled text is treated as derived evidence; prompt
rendering must hydrate it through canonical chunks first.
"""

from __future__ import annotations

import hashlib
import re

from memo_stack_core.domain.entities import SourceRef
from memo_stack_core.ports.adapters import AdapterCapabilities
from memo_stack_core.ports.capabilities import (
    CapabilityDescriptor,
    CapabilityDiagnostic,
    CapabilityMode,
    CapabilityRecallCandidate,
    CapabilityRecallQuery,
    CapabilityRecallResult,
    CapabilityStatus,
    DocumentMemoryWrite,
    EngineHealthSnapshot,
    MemoryCapability,
    ProjectionForgetRequest,
    ProjectionForgetResult,
    ProjectionWriteResult,
)


class CogneeMemoryAdapter:
    def __init__(
        self,
        *,
        enabled: bool = False,
        configured: bool = False,
        client: object | None = None,
        dataset_prefix: str = "memory",
    ) -> None:
        self._enabled = enabled
        self._configured = configured or client is not None
        self._client = client
        self._dataset_prefix = dataset_prefix

    async def capabilities(self) -> AdapterCapabilities:
        if not self._enabled:
            return AdapterCapabilities(
                name="cognee",
                enabled=False,
                healthy=True,
                supports_upsert=False,
                supports_delete=False,
                supports_search=False,
                supports_filters=False,
                degraded_reason="disabled",
            )
        client = await self._client_or_none()
        if client is not None:
            return AdapterCapabilities(
                name="cognee",
                enabled=True,
                healthy=True,
                supports_upsert=True,
                supports_delete=False,
                supports_search=True,
                supports_filters=True,
            )
        return AdapterCapabilities(
            name="cognee",
            enabled=False,
            healthy=False,
            supports_upsert=False,
            supports_delete=False,
            supports_search=False,
            supports_filters=False,
            degraded_reason=(
                "cognee_sdk_missing" if self._configured else "cognee_not_configured"
            ),
        )

    async def capability_descriptors(self) -> tuple[CapabilityDescriptor, ...]:
        capabilities = await self.capabilities()
        return (
            _descriptor(capabilities, MemoryCapability.DOCUMENT_MEMORY),
            _descriptor(capabilities, MemoryCapability.RAG_RECALL),
        )

    async def health(self) -> EngineHealthSnapshot:
        descriptors = await self.capability_descriptors()
        status = (
            CapabilityStatus.OK
            if any(descriptor.status == CapabilityStatus.OK for descriptor in descriptors)
            else descriptors[0].status
        )
        return EngineHealthSnapshot(
            adapter_name="cognee",
            status=status,
            capabilities=descriptors,
        )

    async def ingest_document(self, command: DocumentMemoryWrite) -> ProjectionWriteResult:
        client = await self._client_or_none()
        if client is None:
            return self._disabled_write_result()
        remember = getattr(client, "remember", None)
        if remember is None:
            return ProjectionWriteResult(
                status=CapabilityStatus.DEGRADED,
                affected_ids=(),
                diagnostics=(_diagnostic("cognee.missing_remember"),),
            )
        dataset_name = self._dataset_name(command.space_id, command.profile_id)
        try:
            await remember(
                f"{command.title}\n\n{command.text}",
                dataset_name=dataset_name,
                node_set=list(command.chunk_ids or (command.document_id,)),
                self_improvement=True,
                run_in_background=False,
            )
        except Exception:
            return ProjectionWriteResult(
                status=CapabilityStatus.DEGRADED,
                affected_ids=(),
                diagnostics=(_diagnostic("cognee.remember_failed", retryable=True),),
            )
        return ProjectionWriteResult(
            status=CapabilityStatus.OK,
            affected_ids=(command.document_id,),
        )

    async def forget_document(
        self,
        _command: ProjectionForgetRequest,
    ) -> ProjectionForgetResult:
        return ProjectionForgetResult(
            status=CapabilityStatus.DISABLED,
            forgotten_ids=(),
            diagnostics=(_disabled_diagnostic(),),
        )

    async def recall(self, _query: CapabilityRecallQuery) -> CapabilityRecallResult:
        query = _query
        client = await self._client_or_none()
        if client is None:
            return CapabilityRecallResult(
                status=CapabilityStatus.DISABLED,
                items=(),
                diagnostics=(_disabled_diagnostic(),),
            )
        recall = getattr(client, "recall", None)
        if recall is None:
            return CapabilityRecallResult(
                status=CapabilityStatus.DEGRADED,
                items=(),
                diagnostics=(_diagnostic("cognee.missing_recall"),),
            )
        datasets = [
            self._dataset_name(query.scope.space_id, profile_id)
            for profile_id in query.scope.profile_ids
        ]
        try:
            results = await recall(
                query.query,
                datasets=datasets,
                top_k=query.limit,
                auto_route=True,
                only_context=True,
            )
        except Exception:
            return CapabilityRecallResult(
                status=CapabilityStatus.DEGRADED,
                items=(),
                diagnostics=(_diagnostic("cognee.recall_failed", retryable=True),),
            )
        return CapabilityRecallResult(
            status=CapabilityStatus.OK,
            items=tuple(
                _candidate(result, adapter_name="cognee", index=index)
                for index, result in enumerate(results)
                if _result_text(result)
            ),
        )

    async def _client_or_none(self) -> object | None:
        if self._client is not None:
            return self._client
        if not self._enabled or not self._configured:
            return None
        try:
            import cognee
        except Exception:
            return None
        self._client = cognee
        return self._client

    def _dataset_name(self, space_id: str, profile_id: str) -> str:
        return "__".join(
            (
                _safe_dataset_part(self._dataset_prefix),
                _safe_dataset_part(space_id),
                _safe_dataset_part(profile_id),
            )
        )

    def _disabled_write_result(self) -> ProjectionWriteResult:
        return ProjectionWriteResult(
            status=CapabilityStatus.DISABLED,
            affected_ids=(),
            diagnostics=(_disabled_diagnostic(),),
        )


def _descriptor(
    capabilities: AdapterCapabilities,
    capability: MemoryCapability,
) -> CapabilityDescriptor:
    status = CapabilityStatus.OK if capabilities.enabled else CapabilityStatus.DISABLED
    return CapabilityDescriptor(
        capability=capability,
        adapter_name="cognee",
        mode=CapabilityMode.PRIMARY if capabilities.enabled else CapabilityMode.DISABLED,
        status=status,
        enabled=capabilities.enabled,
        supports_scope_filter=capabilities.supports_filters,
        supports_source_refs=capabilities.enabled,
        supports_update=capabilities.supports_upsert,
        supports_delete=capabilities.supports_delete,
        degraded_reason=capabilities.degraded_reason,
    )


def _candidate(result: object, *, adapter_name: str, index: int) -> CapabilityRecallCandidate:
    text = _result_text(result) or ""
    return CapabilityRecallCandidate(
        item_id=_result_id(result, index=index),
        item_type="chunk",
        text=text,
        score=_result_score(result),
        source_refs=(_source_ref(result, index=index),),
        capability=MemoryCapability.RAG_RECALL,
        adapter_name=adapter_name,
        metadata={"provider": "cognee"},
    )


def _result_text(result: object) -> str | None:
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        for key in ("text", "content", "chunk_text", "body", "summary"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return value
    for attr in ("text", "content", "chunk_text", "body", "summary"):
        value = getattr(result, attr, None)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _result_id(result: object, *, index: int) -> str:
    for attr in ("id", "data_id", "chunk_id"):
        value = getattr(result, attr, None)
        if isinstance(value, str) and value.strip():
            return value
    if isinstance(result, dict):
        for key in ("id", "data_id", "chunk_id"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return value
    digest = hashlib.sha256(str(result).encode("utf-8")).hexdigest()[:16]
    return f"cognee_{index}_{digest}"


def _result_score(result: object) -> float:
    value = result.get("score") if isinstance(result, dict) else getattr(result, "score", None)
    if isinstance(value, int | float):
        return max(0.0, min(1.0, float(value)))
    return 0.5


def _source_ref(result: object, *, index: int) -> SourceRef:
    chunk_id = _result_str_field(result, "chunk_id")
    if chunk_id:
        return SourceRef(
            source_type="chunk",
            source_id=chunk_id,
            chunk_id=chunk_id,
        )
    document_id = _result_str_field(result, "document_id")
    if document_id:
        return SourceRef(source_type="document", source_id=document_id)
    return SourceRef(
        source_type="cognee",
        source_id=_result_id(result, index=index),
    )


def _result_str_field(result: object, field_name: str) -> str | None:
    if isinstance(result, dict):
        value = result.get(field_name)
    else:
        value = getattr(result, field_name, None)
    if isinstance(value, str) and value.strip():
        return value
    return None


def _safe_dataset_part(value: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "_", value.strip())
    return safe.strip("_") or "default"


def _diagnostic(code: str, *, retryable: bool = False) -> CapabilityDiagnostic:
    return CapabilityDiagnostic(
        code=code,
        safe_message="Cognee memory adapter degraded",
        retryable=retryable,
    )


def _disabled_diagnostic() -> CapabilityDiagnostic:
    return CapabilityDiagnostic(
        code="cognee.disabled",
        safe_message="Cognee memory adapter is disabled",
        retryable=False,
    )

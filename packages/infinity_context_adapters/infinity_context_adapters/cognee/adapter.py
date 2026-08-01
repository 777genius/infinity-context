"""Disabled-by-default Cognee memory adapter.

The adapter does not import Cognee or send memory text unless it is explicitly
enabled and configured. Recalled text is treated as derived evidence; prompt
rendering must hydrate it through canonical chunks first.
"""

from __future__ import annotations

import hashlib
import re

from infinity_context_core.domain.entities import SourceRef
from infinity_context_core.ports.adapters import AdapterCapabilities
from infinity_context_core.ports.capabilities import (
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
            supports_recall = callable(getattr(client, "recall", None))
            return AdapterCapabilities(
                name="cognee",
                enabled=True,
                healthy=supports_recall,
                supports_upsert=False,
                supports_delete=False,
                supports_search=supports_recall,
                supports_filters=False,
                degraded_reason=None if supports_recall else "cognee_recall_unavailable",
            )
        return AdapterCapabilities(
            name="cognee",
            enabled=False,
            healthy=False,
            supports_upsert=False,
            supports_delete=False,
            supports_search=False,
            supports_filters=False,
            degraded_reason=("cognee_sdk_missing" if self._configured else "cognee_not_configured"),
        )

    async def capability_descriptors(self) -> tuple[CapabilityDescriptor, ...]:
        capabilities = await self.capabilities()
        return (
            _document_memory_descriptor(capabilities),
            _rag_recall_descriptor(capabilities),
        )

    async def health(self) -> EngineHealthSnapshot:
        descriptors = await self.capability_descriptors()
        status = next(
            (
                candidate
                for candidate in (
                    CapabilityStatus.OK,
                    CapabilityStatus.DEGRADED,
                    CapabilityStatus.UNAVAILABLE,
                    CapabilityStatus.DISABLED,
                )
                if any(descriptor.status == candidate for descriptor in descriptors)
            ),
            CapabilityStatus.DISABLED,
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
        return ProjectionWriteResult(
            status=CapabilityStatus.DISABLED,
            affected_ids=(),
            diagnostics=(_document_memory_disabled_diagnostic(),),
        )

    async def forget_document(
        self,
        _command: ProjectionForgetRequest,
    ) -> ProjectionForgetResult:
        if not self._enabled:
            return ProjectionForgetResult(
                status=CapabilityStatus.DISABLED,
                forgotten_ids=(),
                diagnostics=(_disabled_diagnostic(),),
            )
        client = await self._client_or_none()
        if client is None:
            return ProjectionForgetResult(
                status=CapabilityStatus.DEGRADED,
                forgotten_ids=(),
                diagnostics=(_diagnostic("cognee.runtime_unavailable", retryable=True),),
            )
        return ProjectionForgetResult(
            status=CapabilityStatus.DEGRADED,
            forgotten_ids=(),
            diagnostics=(_document_memory_disabled_diagnostic(),),
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
            self._dataset_name(query.scope.space_id, memory_scope_id)
            for memory_scope_id in query.scope.memory_scope_ids
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
        if not self._enabled:
            return None
        if self._client is not None:
            return self._client
        if not self._configured:
            return None
        try:
            import cognee
        except Exception:
            return None
        self._client = cognee
        return self._client

    def _dataset_name(self, space_id: str, memory_scope_id: str) -> str:
        return "__".join(
            (
                _safe_dataset_part(self._dataset_prefix),
                _safe_dataset_part(space_id),
                _safe_dataset_part(memory_scope_id),
            )
        )

    def _disabled_write_result(self) -> ProjectionWriteResult:
        return ProjectionWriteResult(
            status=CapabilityStatus.DISABLED,
            affected_ids=(),
            diagnostics=(_disabled_diagnostic(),),
        )


def _document_memory_descriptor(
    capabilities: AdapterCapabilities,
) -> CapabilityDescriptor:
    return CapabilityDescriptor(
        capability=MemoryCapability.DOCUMENT_MEMORY,
        adapter_name="cognee",
        mode=CapabilityMode.DISABLED,
        status=CapabilityStatus.DISABLED,
        enabled=False,
        supports_scope_filter=False,
        supports_source_refs=False,
        supports_update=False,
        supports_delete=False,
        degraded_reason=(
            capabilities.degraded_reason
            if not capabilities.enabled
            else "cognee_exact_delete_readback_unavailable"
        ),
    )


def _rag_recall_descriptor(capabilities: AdapterCapabilities) -> CapabilityDescriptor:
    if not capabilities.enabled:
        status = CapabilityStatus.DISABLED
        mode = CapabilityMode.DISABLED
        enabled = False
    else:
        status = CapabilityStatus.OK if capabilities.supports_search else CapabilityStatus.DEGRADED
        mode = CapabilityMode.PRIMARY
        enabled = True
    return CapabilityDescriptor(
        capability=MemoryCapability.RAG_RECALL,
        adapter_name="cognee",
        mode=mode,
        status=status,
        enabled=enabled,
        supports_scope_filter=capabilities.supports_filters,
        supports_source_refs=capabilities.supports_search,
        supports_update=False,
        supports_delete=False,
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


def _document_memory_disabled_diagnostic() -> CapabilityDiagnostic:
    return CapabilityDiagnostic(
        code="cognee.exact_delete_readback_unavailable",
        safe_message="Cognee document memory lifecycle is unavailable",
        retryable=False,
    )

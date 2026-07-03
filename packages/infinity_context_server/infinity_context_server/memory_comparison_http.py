"""HTTP adapters for manual memory comparison benchmark runs."""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence

import httpx
from infinity_context_core.application.sensitive_text import redact_sensitive_text

from infinity_context_server.memory_comparison_candidate_fusion import (
    fuse_query_results,
)
from infinity_context_server.memory_comparison_llm import approximate_token_count
from infinity_context_server.memory_comparison_models import (
    BackendIngestResult,
    BackendSearchResult,
    IngestionOperation,
    RetrievedMemory,
)
from infinity_context_server.memory_comparison_rerank import (
    benchmark_rerank_memories,
    decomposed_search_queries,
    temporal_rerank_memories,
)
from infinity_context_server.public_benchmark_checkpoint import safe_identifier
from infinity_context_server.public_benchmark_models import (
    BenchmarkDocumentInput,
    BenchmarkMemoryInput,
    PublicBenchmarkCase,
)

_INFINITY_CONTEXT_PUBLIC_MAX_FACTS = 100
_INFINITY_CONTEXT_PUBLIC_MAX_CHUNKS = 200
_INFINITY_CONTEXT_PUBLIC_MAX_TOKEN_BUDGET = 16_000
_INFINITY_CONTEXT_BENCHMARK_MAX_FACTS = 1_000
_INFINITY_CONTEXT_BENCHMARK_MAX_CHUNKS = 2_000
_INFINITY_CONTEXT_BENCHMARK_MAX_TOKEN_BUDGET = 64_000
class InfinityContextHttpComparisonBackend:
    """Benchmark backend for Infinity Context's public HTTP API."""

    name = "memo-stack"

    def __init__(
        self,
        *,
        base_url: str,
        auth_token: str,
        space_slug_prefix: str = "memory-comparison",
        timeout_seconds: float = 60.0,
        use_benchmark_search: bool = True,
        mirror_memories_as_documents: bool = True,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            headers={"Authorization": f"Bearer {auth_token}"},
            transport=transport,
        )
        self._space_slug_prefix = space_slug_prefix
        self._use_benchmark_search = use_benchmark_search
        self._mirror_memories_as_documents = mirror_memories_as_documents

    def reset(self, *, run_id: str) -> None:
        # Isolation is by run-specific space slug; no destructive reset needed.
        self._run_space_slug(run_id)

    def close(self) -> None:
        self._client.close()

    def ingest(
        self,
        case: PublicBenchmarkCase,
        *,
        run_id: str,
        corpus_key: str,
    ) -> BackendIngestResult:
        started = time.perf_counter()
        operations: list[IngestionOperation] = []
        for index, memory in enumerate(case.memories, start=1):
            operations.append(
                self._post_fact(case, memory, run_id=run_id, step=index)
            )
        offset = len(operations)
        mirrored_documents = (
            _mirrored_memory_documents(case) if self._mirror_memories_as_documents else ()
        )
        for index, document in enumerate(mirrored_documents, start=1):
            operations.append(
                self._post_document(case, document, run_id=run_id, step=offset + index)
            )
        offset = len(operations)
        for index, document in enumerate(case.documents, start=1):
            operations.append(
                self._post_document(case, document, run_id=run_id, step=offset + index)
            )
        failed = sum(1 for operation in operations if not operation.success)
        return BackendIngestResult(
            items_processed=len(operations),
            items_failed=failed,
            total_memories_created=len(operations) - failed,
            latency_ms=_elapsed_ms(started),
            operations=tuple(operations),
            metadata={
                "corpus_key": corpus_key,
                "mirrored_memory_documents_created": len(mirrored_documents),
                "hybrid_raw_turn_documents_enabled": self._mirror_memories_as_documents,
            },
        )

    def search(
        self,
        case: PublicBenchmarkCase,
        *,
        run_id: str,
        top_k: int,
    ) -> BackendSearchResult:
        started = time.perf_counter()
        requested_token_budget = max(2048, top_k * 128)
        max_facts_limit = (
            _INFINITY_CONTEXT_BENCHMARK_MAX_FACTS
            if self._use_benchmark_search
            else _INFINITY_CONTEXT_PUBLIC_MAX_FACTS
        )
        max_chunks_limit = (
            _INFINITY_CONTEXT_BENCHMARK_MAX_CHUNKS
            if self._use_benchmark_search
            else _INFINITY_CONTEXT_PUBLIC_MAX_CHUNKS
        )
        token_budget_limit = (
            _INFINITY_CONTEXT_BENCHMARK_MAX_TOKEN_BUDGET
            if self._use_benchmark_search
            else _INFINITY_CONTEXT_PUBLIC_MAX_TOKEN_BUDGET
        )
        token_budget = min(requested_token_budget, token_budget_limit)
        max_facts = min(top_k, max_facts_limit)
        max_chunks = min(top_k, max_chunks_limit)
        search_queries, query_decomposition = decomposed_search_queries(case)
        search_path = (
            "/v1/context/benchmark-search"
            if self._use_benchmark_search
            else "/v1/context"
        )
        query_results: list[tuple[str, list[RetrievedMemory]]] = []
        for query in search_queries:
            response = self._client.post(
                search_path,
                json={
                    "space_slug": self._run_space_slug(run_id),
                    "memory_scope_external_ref": _memory_scope_ref(case),
                    "thread_external_ref": _thread_ref(case),
                    "query": query,
                    "token_budget": token_budget,
                    "max_facts": max_facts,
                    "max_chunks": max_chunks,
                },
            )
            response.raise_for_status()
            data = _response_data(response.json())
            query_results.append((query, _infinity_context_memories(data.get("items", ()))))
        query_roles = _query_roles_from_decomposition(
            query_decomposition,
            search_queries,
        )
        memories, multi_query_merge = fuse_query_results(
            query_results,
            query_roles=query_roles,
        )
        memories, temporal_rerank = temporal_rerank_memories(case, memories)
        memories, benchmark_rerank = benchmark_rerank_memories(case, memories)
        return BackendSearchResult(
            query=case.question,
            memories=tuple(memories[:top_k]),
            latency_ms=_elapsed_ms(started),
            total_results=len(memories),
            context_token_count=sum(approximate_token_count(memory.text) for memory in memories),
            metadata={
                "transport": "infinity_context_http",
                "search_path": search_path,
                "benchmark_search": self._use_benchmark_search,
                "requested_top_k": top_k,
                "applied_max_facts": max_facts,
                "applied_max_chunks": max_chunks,
                "retrieval_source_counts": _retrieval_source_counts(memories),
                "query_expansion": query_decomposition,
                "query_decomposition": query_decomposition,
                "query_roles": list(query_roles),
                "multi_query_merge": multi_query_merge,
                "temporal_rerank": temporal_rerank,
                "benchmark_rerank": benchmark_rerank,
                "requested_token_budget": requested_token_budget,
                "applied_token_budget": token_budget,
                "limited_by_http_api_caps": (
                    max_facts < top_k
                    or max_chunks < top_k
                    or token_budget < requested_token_budget
                ),
            },
        )

    def _post_fact(
        self,
        case: PublicBenchmarkCase,
        memory: BenchmarkMemoryInput,
        *,
        run_id: str,
        step: int,
    ) -> IngestionOperation:
        started = time.perf_counter()
        source_id = safe_identifier(
            memory.source_external_id or f"{case.case_id}:memory:{step}",
            max_chars=160,
        )
        response = self._client.post(
            "/v1/facts",
            json={
                "space_slug": self._run_space_slug(run_id),
                "memory_scope_external_ref": _memory_scope_ref(case),
                "thread_external_ref": _thread_ref(case),
                "text": memory.text,
                "kind": memory.kind,
                "classification": "internal",
                "source_refs": [
                    _source_ref_payload(
                        source_type="memory_comparison_benchmark",
                        source_id=source_id,
                        quote_preview=memory.text[:240],
                    )
                ],
            },
            headers={"Idempotency-Key": source_id},
        )
        return IngestionOperation(
            step=step,
            operation_type="fact",
            success=response.status_code < 400,
            latency_ms=_elapsed_ms(started),
            memory=memory.text[:240],
            item_id=source_id,
            metadata={
                **_response_metadata(response),
                **_source_temporal_metadata(memory.metadata),
            },
        )

    def _post_document(
        self,
        case: PublicBenchmarkCase,
        document: BenchmarkDocumentInput,
        *,
        run_id: str,
        step: int,
    ) -> IngestionOperation:
        started = time.perf_counter()
        source_id = safe_identifier(
            document.source_external_id or f"{case.case_id}:document:{step}",
            max_chars=240,
        )
        response = self._client.post(
            "/v1/documents",
            json={
                "space_slug": self._run_space_slug(run_id),
                "memory_scope_external_ref": _memory_scope_ref(case),
                "thread_external_ref": _thread_ref(case),
                "title": document.title,
                "text": document.text,
                "source_type": document.source_type,
                "source_external_id": source_id,
                "classification": document.classification,
                "source_refs": [dict(ref) for ref in document.source_refs],
            },
            headers={"Idempotency-Key": source_id},
        )
        return IngestionOperation(
            step=step,
            operation_type="document",
            success=response.status_code < 400,
            latency_ms=_elapsed_ms(started),
            memory=document.text[:240],
            item_id=source_id,
            metadata=_response_metadata(response),
        )

    def _run_space_slug(self, run_id: str) -> str:
        return f"{self._space_slug_prefix}-{_safe_slug(run_id)}"


class Mem0HttpComparisonBackend:
    """Benchmark backend for the mem0 OSS REST wrapper used by memory-benchmarks."""

    name = "mem0"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None = None,
        timeout_seconds: float = 60.0,
        reset_user_on_start: bool = True,
        send_timestamps: bool = False,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            headers={"X-API-Key": api_key} if api_key else None,
            transport=transport,
        )
        self._reset_user_on_start = reset_user_on_start
        self._send_timestamps = send_timestamps

    def reset(self, *, run_id: str) -> None:
        if not self._reset_user_on_start:
            return
        response = self._client.delete(
            "/memories",
            params={"user_id": self._user_id(run_id), "run_id": run_id},
        )
        if response.status_code not in {200, 204, 404}:
            response.raise_for_status()

    def close(self) -> None:
        self._client.close()

    def ingest(
        self,
        case: PublicBenchmarkCase,
        *,
        run_id: str,
        corpus_key: str,
    ) -> BackendIngestResult:
        started = time.perf_counter()
        operations: list[IngestionOperation] = []
        total_memories_created = 0
        for step, group in enumerate(_case_message_groups(case), start=1):
            messages, timestamp, source_metadata = group
            op_started = time.perf_counter()
            payload: dict[str, object] = {
                "messages": messages,
                "user_id": self._user_id(run_id),
                "run_id": run_id,
                "metadata": {
                    "benchmark": case.benchmark,
                    "case_id": case.case_id,
                    "corpus_key": corpus_key,
                    **source_metadata,
                },
            }
            if self._send_timestamps and timestamp is not None:
                payload["timestamp"] = timestamp
            response = self._client.post(
                "/memories",
                json=payload,
            )
            metadata = _response_metadata(response)
            created_count = (
                _mem0_created_memory_count(response) if response.status_code < 400 else 0
            )
            if response.status_code < 400:
                total_memories_created += created_count
                metadata["created_memory_count"] = created_count
            operations.append(
                IngestionOperation(
                    step=step,
                    operation_type="messages",
                    success=response.status_code < 400,
                    latency_ms=_elapsed_ms(op_started),
                    memory=_messages_preview(messages),
                    metadata=metadata,
                )
            )
        failed = sum(1 for operation in operations if not operation.success)
        return BackendIngestResult(
            items_processed=len(operations),
            items_failed=failed,
            total_memories_created=total_memories_created,
            latency_ms=_elapsed_ms(started),
            operations=tuple(operations),
            metadata={
                "corpus_key": corpus_key,
                "timestamps_sent": self._send_timestamps,
            },
        )

    def search(
        self,
        case: PublicBenchmarkCase,
        *,
        run_id: str,
        top_k: int,
    ) -> BackendSearchResult:
        started = time.perf_counter()
        response = self._client.post(
            "/search",
            json={
                "query": case.question,
                "filters": {"user_id": self._user_id(run_id), "run_id": run_id},
                "limit": top_k,
                "top_k": top_k,
            },
        )
        response.raise_for_status()
        memories = _mem0_memories(response.json())
        return BackendSearchResult(
            query=case.question,
            memories=tuple(memories[:top_k]),
            latency_ms=_elapsed_ms(started),
            total_results=len(memories),
            context_token_count=sum(approximate_token_count(memory.text) for memory in memories),
            metadata={"transport": "mem0_http"},
        )

    def _user_id(self, run_id: str) -> str:
        return f"memo-stack-comparison-{_safe_slug(run_id)}"


def _infinity_context_memories(raw_items: object) -> list[RetrievedMemory]:
    memories: list[RetrievedMemory] = []
    if not isinstance(raw_items, Sequence) or isinstance(raw_items, str | bytes):
        return memories
    for rank, item in enumerate(raw_items, start=1):
        if not isinstance(item, Mapping):
            continue
        source_ref_payloads = _source_ref_payloads(item)
        refs = tuple(
            dict.fromkeys(
                source_id
                for ref in source_ref_payloads
                if (source_id := _source_ref_source_id(ref)) is not None
            )
        )
        time_start_ms = tuple(
            timestamp
            for ref in source_ref_payloads
            if (timestamp := _source_ref_time_start_ms(ref)) is not None
        )
        item_metadata = (
            item.get("metadata") if isinstance(item.get("metadata"), Mapping) else {}
        )
        temporal_metadata = _source_temporal_metadata(item_metadata)
        memories.append(
            RetrievedMemory(
                text=str(item.get("text") or ""),
                rank=rank,
                score=_float_value(item.get("score")),
                item_id=str(item.get("item_id") or "") or None,
                source_refs=refs,
                metadata={
                    **temporal_metadata,
                    "item_type": item.get("item_type"),
                    "diagnostics": _item_diagnostics(item),
                    "source_ref_time_start_ms": list(time_start_ms),
                    "has_temporal_source_ref": bool(
                        time_start_ms or temporal_metadata
                    ),
                },
            )
        )
    return memories


def _source_ref_payloads(item: Mapping[str, object]) -> tuple[object, ...]:
    source_refs = item.get("source_refs") or ()
    if isinstance(source_refs, str) and source_refs.strip():
        return (source_refs.strip(),)
    if not isinstance(source_refs, Sequence) or isinstance(source_refs, str | bytes):
        return ()
    return tuple(source_refs)


def _source_ref_source_id(ref: object) -> str | None:
    if isinstance(ref, str):
        stripped = ref.strip()
        return stripped or None
    if not isinstance(ref, Mapping):
        return None
    for key in ("source_id", "source_external_id", "id"):
        value = ref.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _source_ref_time_start_ms(ref: object) -> int | None:
    if not isinstance(ref, Mapping):
        return None
    return _optional_int(ref.get("time_start_ms"))


def _item_diagnostics(item: Mapping[str, object]) -> dict[str, object]:
    metadata = item.get("metadata")
    nested_diagnostics = (
        metadata.get("diagnostics") if isinstance(metadata, Mapping) else None
    )
    diagnostics: dict[str, object] = {}
    if isinstance(nested_diagnostics, Mapping):
        diagnostics.update(dict(nested_diagnostics))
    top_level_diagnostics = item.get("diagnostics")
    if isinstance(top_level_diagnostics, Mapping):
        diagnostics.update(dict(top_level_diagnostics))
    return diagnostics


def _mirrored_memory_documents(
    case: PublicBenchmarkCase,
) -> tuple[BenchmarkDocumentInput, ...]:
    if case.documents:
        return ()
    documents: list[BenchmarkDocumentInput] = []
    for index, memory in enumerate(case.memories, start=1):
        source_external_id = memory.source_external_id or f"{case.case_id}:memory:{index}"
        documents.append(
            BenchmarkDocumentInput(
                title=f"Raw memory turn {index}",
                text=memory.text,
                source_type="memory_comparison_raw_turn",
                classification="internal",
                source_external_id=f"{source_external_id}:raw-turn-document",
                source_refs=(
                    _source_ref_payload(
                        source_type="memory_comparison_benchmark",
                        source_id=safe_identifier(source_external_id, max_chars=160),
                        quote_preview=memory.text[:240],
                    ),
                ),
            )
        )
    return tuple(documents)


def _source_ref_payload(
    *,
    source_type: str,
    source_id: str,
    quote_preview: str,
) -> dict[str, object]:
    return {
        "source_type": source_type,
        "source_id": source_id,
        "quote_preview": quote_preview,
    }


def _source_temporal_metadata(metadata: Mapping[str, object]) -> dict[str, object]:
    timestamp = _optional_int(metadata.get("source_timestamp"))
    if timestamp is None:
        timestamp = _optional_int(metadata.get("timestamp"))
    result: dict[str, object] = {}
    if timestamp is not None:
        result["source_timestamp"] = timestamp
    for key in ("session_key", "session_date", "dia_id", "role"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            result[key] = value
    return result



def _retrieval_source_counts(memories: Sequence[RetrievedMemory]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for memory in memories:
        sources = _memory_retrieval_sources(memory)
        if not sources:
            counts["unknown"] = counts.get("unknown", 0) + 1
            continue
        for source in sources:
            counts[source] = counts.get(source, 0) + 1
    return dict(sorted(counts.items()))


def _memory_retrieval_sources(memory: RetrievedMemory) -> tuple[str, ...]:
    diagnostics = memory.metadata.get("diagnostics")
    if not isinstance(diagnostics, Mapping):
        return ()
    values: list[str] = []
    sources = diagnostics.get("retrieval_sources")
    if isinstance(sources, Sequence) and not isinstance(sources, str | bytes):
        values.extend(str(source) for source in sources if str(source).strip())
    retrieval_source = diagnostics.get("retrieval_source")
    if isinstance(retrieval_source, str) and retrieval_source.strip():
        values.append(retrieval_source)
    fusion = diagnostics.get("benchmark_candidate_fusion")
    if isinstance(fusion, Mapping):
        fusion_sources = fusion.get("retrieval_sources")
        if isinstance(fusion_sources, Sequence) and not isinstance(
            fusion_sources,
            str | bytes,
        ):
            values.extend(
                str(source) for source in fusion_sources if str(source).strip()
            )
    return tuple(dict.fromkeys(values))


def _query_roles_from_decomposition(
    query_decomposition: Mapping[str, object],
    search_queries: Sequence[str],
) -> tuple[str, ...]:
    query_plan = _mapping(query_decomposition.get("query_plan"))
    selected = _sequence(query_plan.get("selected"))
    roles: list[str] = []
    for index, query in enumerate(search_queries):
        selected_payload = _mapping(selected[index] if index < len(selected) else None)
        selected_query = str(selected_payload.get("query") or "")
        role = str(selected_payload.get("role") or "").strip()
        roles.append(role if selected_query == query else "")
    return tuple(roles)


def _mem0_memories(payload: object) -> list[RetrievedMemory]:
    raw_items = payload.get("results", payload) if isinstance(payload, Mapping) else payload
    memories: list[RetrievedMemory] = []
    if not isinstance(raw_items, Sequence) or isinstance(raw_items, str | bytes):
        return memories
    for rank, item in enumerate(raw_items, start=1):
        if not isinstance(item, Mapping):
            continue
        memory_text = item.get("memory") or item.get("text") or item.get("content") or ""
        metadata = _mem0_metadata(item)
        memories.append(
            RetrievedMemory(
                text=str(memory_text),
                rank=rank,
                score=_float_value(item.get("score")),
                item_id=str(item.get("id") or "") or None,
                created_at=str(item.get("created_at") or "") or None,
                source_refs=_mem0_source_refs(item, metadata),
                metadata={
                    "raw_event": item.get("event"),
                    "metadata": metadata,
                },
            )
        )
    return memories


def _mem0_created_memory_count(response: httpx.Response) -> int:
    try:
        payload = response.json()
    except ValueError:
        return 0
    if not isinstance(payload, Mapping):
        return 0
    results = payload.get("results")
    if isinstance(results, Sequence) and not isinstance(results, str | bytes):
        return len(results)
    return 0


def _mem0_metadata(item: Mapping[str, object]) -> dict[str, object]:
    metadata = item.get("metadata")
    return dict(metadata) if isinstance(metadata, Mapping) else {}


def _mem0_source_refs(
    item: Mapping[str, object],
    metadata: Mapping[str, object],
) -> tuple[str, ...]:
    refs: list[str] = []
    raw_source_refs = item.get("source_refs")
    if isinstance(raw_source_refs, Sequence) and not isinstance(raw_source_refs, str | bytes):
        for ref in raw_source_refs:
            if isinstance(ref, Mapping) and ref.get("source_id"):
                refs.append(str(ref["source_id"]))
            elif isinstance(ref, str) and ref.strip():
                refs.append(ref.strip())
    metadata_source_refs = metadata.get("source_refs")
    if isinstance(metadata_source_refs, Sequence) and not isinstance(
        metadata_source_refs,
        str | bytes,
    ):
        for ref in metadata_source_refs:
            if isinstance(ref, str) and ref.strip():
                refs.append(ref.strip())
    for key in (
        "source_id",
        "source_external_id",
        "locomo_evidence_ref",
        "dia_id",
    ):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            refs.append(value.strip())
    return tuple(dict.fromkeys(refs))


def _mem0_source_metadata(memory: BenchmarkMemoryInput) -> dict[str, object]:
    metadata: dict[str, object] = {}
    if memory.source_external_id:
        metadata["source_external_id"] = memory.source_external_id
        metadata["source_id"] = safe_identifier(memory.source_external_id, max_chars=160)
    for key in ("session_key", "session_date", "dia_id", "role", "speaker"):
        value = memory.metadata.get(key)
        if isinstance(value, str) and value.strip():
            metadata[key] = value.strip()
    dia_id = metadata.get("dia_id")
    if isinstance(dia_id, str) and dia_id.strip():
        metadata["locomo_evidence_ref"] = dia_id.strip()
    return metadata


def _mem0_document_metadata(document: BenchmarkDocumentInput) -> dict[str, object]:
    metadata: dict[str, object] = {}
    if document.source_external_id:
        metadata["source_external_id"] = document.source_external_id
        metadata["source_id"] = safe_identifier(document.source_external_id, max_chars=160)
    source_ids = tuple(
        str(ref.get("source_id"))
        for ref in document.source_refs
        if isinstance(ref, Mapping) and ref.get("source_id")
    )
    if source_ids:
        metadata["source_refs"] = list(source_ids)
    return metadata


def _case_message_groups(
    case: PublicBenchmarkCase,
) -> tuple[tuple[tuple[dict[str, str], ...], int | None, dict[str, object]], ...]:
    groups: list[tuple[tuple[dict[str, str], ...], int | None, dict[str, object]]] = []
    for memory in case.memories:
        groups.append(
            (
                (
                    {
                        "role": _message_role(memory.metadata.get("role")),
                        "content": memory.text,
                    },
                ),
                _optional_int(memory.metadata.get("timestamp")),
                _mem0_source_metadata(memory),
            )
        )
    for document in case.documents:
        groups.append(
            (
                ({"role": "user", "content": document.text},),
                None,
                _mem0_document_metadata(document),
            )
        )
    return tuple(groups)


def _message_role(value: object) -> str:
    role = str(value or "user").strip().lower()
    return role if role in {"user", "assistant", "system"} else "user"


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _messages_preview(messages: Sequence[Mapping[str, str]]) -> str:
    return " ".join(str(message.get("content", "")) for message in messages)[:240]


def _response_data(payload: object) -> Mapping[str, object]:
    if isinstance(payload, Mapping) and isinstance(payload.get("data"), Mapping):
        return payload["data"]
    return payload if isinstance(payload, Mapping) else {}


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> tuple[object, ...]:
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return tuple(value)
    return ()


def _response_metadata(response: httpx.Response) -> dict[str, object]:
    metadata: dict[str, object] = {"status_code": response.status_code}
    if response.reason_phrase:
        metadata["reason_phrase"] = response.reason_phrase
    if response.status_code >= 400:
        preview = redact_sensitive_text(response.text.strip())[:500]
        if preview:
            metadata["error_preview"] = preview
    return metadata


def _memory_scope_ref(case: PublicBenchmarkCase) -> str:
    return case.memory_scope_external_ref or f"{case.benchmark}-{case.case_id}"


def _thread_ref(case: PublicBenchmarkCase) -> str:
    return case.thread_external_ref or f"{case.benchmark}-{case.case_id}"


def _safe_slug(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch == "-" else "-" for ch in value.lower())[:80]


def _float_value(value: object) -> float:
    if isinstance(value, bool):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)

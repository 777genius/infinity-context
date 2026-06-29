"""HTTP adapters for manual memory comparison benchmark runs."""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence

import httpx
from infinity_context_core.application.sensitive_text import redact_sensitive_text

from infinity_context_server.memory_comparison_llm import approximate_token_count
from infinity_context_server.memory_comparison_models import (
    BackendIngestResult,
    BackendSearchResult,
    IngestionOperation,
    RetrievedMemory,
)
from infinity_context_server.public_benchmark_models import (
    BenchmarkDocumentInput,
    BenchmarkMemoryInput,
    PublicBenchmarkCase,
)


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
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            headers={"Authorization": f"Bearer {auth_token}"},
            transport=transport,
        )
        self._space_slug_prefix = space_slug_prefix

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
            metadata={"corpus_key": corpus_key},
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
            "/v1/context",
            json={
                "space_slug": self._run_space_slug(run_id),
                "memory_scope_external_ref": _memory_scope_ref(case),
                "thread_external_ref": _thread_ref(case),
                "query": case.question,
                "token_budget": max(2048, top_k * 128),
                "max_facts": top_k,
                "max_chunks": top_k,
            },
        )
        response.raise_for_status()
        data = _response_data(response.json())
        memories = _infinity_context_memories(data.get("items", ()))
        return BackendSearchResult(
            query=case.question,
            memories=tuple(memories[:top_k]),
            latency_ms=_elapsed_ms(started),
            total_results=len(memories),
            context_token_count=sum(approximate_token_count(memory.text) for memory in memories),
            metadata={"transport": "infinity_context_http"},
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
        source_id = memory.source_external_id or f"{case.case_id}:memory:{step}"
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
                    {
                        "source_type": "memory_comparison_benchmark",
                        "source_id": source_id,
                        "quote_preview": memory.text[:240],
                    }
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
            metadata=_response_metadata(response),
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
        source_id = document.source_external_id or f"{case.case_id}:document:{step}"
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
        timeout_seconds: float = 60.0,
        reset_user_on_start: bool = True,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            transport=transport,
        )
        self._reset_user_on_start = reset_user_on_start

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
        for step, messages in enumerate(_case_messages(case), start=1):
            op_started = time.perf_counter()
            response = self._client.post(
                "/memories",
                json={
                    "messages": messages,
                    "user_id": self._user_id(run_id),
                    "run_id": run_id,
                    "metadata": {
                        "benchmark": case.benchmark,
                        "case_id": case.case_id,
                        "corpus_key": corpus_key,
                    },
                },
            )
            operations.append(
                IngestionOperation(
                    step=step,
                    operation_type="messages",
                    success=response.status_code < 400,
                    latency_ms=_elapsed_ms(op_started),
                    memory=_messages_preview(messages),
                    metadata=_response_metadata(response),
                )
            )
        failed = sum(1 for operation in operations if not operation.success)
        return BackendIngestResult(
            items_processed=len(operations),
            items_failed=failed,
            total_memories_created=len(operations) - failed,
            latency_ms=_elapsed_ms(started),
            operations=tuple(operations),
            metadata={"corpus_key": corpus_key},
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
        refs = tuple(
            str(ref.get("source_id"))
            for ref in item.get("source_refs") or ()
            if isinstance(ref, Mapping) and ref.get("source_id")
        )
        memories.append(
            RetrievedMemory(
                text=str(item.get("text") or ""),
                rank=rank,
                score=_float_value(item.get("score")),
                item_id=str(item.get("item_id") or "") or None,
                source_refs=refs,
                metadata={
                    "item_type": item.get("item_type"),
                    "diagnostics": item.get("diagnostics"),
                },
            )
        )
    return memories


def _mem0_memories(payload: object) -> list[RetrievedMemory]:
    raw_items = payload.get("results", payload) if isinstance(payload, Mapping) else payload
    memories: list[RetrievedMemory] = []
    if not isinstance(raw_items, Sequence) or isinstance(raw_items, str | bytes):
        return memories
    for rank, item in enumerate(raw_items, start=1):
        if not isinstance(item, Mapping):
            continue
        memory_text = item.get("memory") or item.get("text") or item.get("content") or ""
        memories.append(
            RetrievedMemory(
                text=str(memory_text),
                rank=rank,
                score=_float_value(item.get("score")),
                item_id=str(item.get("id") or "") or None,
                created_at=str(item.get("created_at") or "") or None,
                metadata={"raw_event": item.get("event")},
            )
        )
    return memories


def _case_messages(case: PublicBenchmarkCase) -> tuple[tuple[dict[str, str], ...], ...]:
    messages: list[tuple[dict[str, str], ...]] = []
    for memory in case.memories:
        messages.append(({"role": "user", "content": memory.text},))
    for document in case.documents:
        messages.append(({"role": "user", "content": document.text},))
    return tuple(messages)


def _messages_preview(messages: Sequence[Mapping[str, str]]) -> str:
    return " ".join(str(message.get("content", "")) for message in messages)[:240]


def _response_data(payload: object) -> Mapping[str, object]:
    if isinstance(payload, Mapping) and isinstance(payload.get("data"), Mapping):
        return payload["data"]
    return payload if isinstance(payload, Mapping) else {}


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

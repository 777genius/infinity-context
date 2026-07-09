"""Models and ports for side-by-side memory benchmark runs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from math import isfinite
from typing import Any, Literal, Protocol

from infinity_context_server.memory_comparison_source_identity import (
    looks_like_raw_source_ref as _looks_like_raw_source_ref,
)
from infinity_context_server.memory_comparison_source_identity import (
    safe_item_id_for_output as _safe_item_id_for_output,
)
from infinity_context_server.memory_comparison_source_identity import (
    safe_source_refs_for_output as _safe_source_refs_for_output,
)
from infinity_context_server.memory_comparison_source_identity import (
    source_identity_refs_from_dedupe_key as _source_identity_refs_from_dedupe_key,
)
from infinity_context_server.public_benchmark_models import PublicBenchmarkCase

Verdict = Literal["correct", "incorrect", "error"]
_REDACTED_OUTPUT_TEXT = "[redacted]"
_RAW_PROVIDER_PAYLOAD_KEYS = frozenset(
    {
        "payload",
        "provider_payload",
        "raw_payload",
        "raw_provider",
        "raw_provider_payload",
    }
)
_SOURCE_REF_KEYS = frozenset(
    {
        "raw_source_ref",
        "raw_source_refs",
        "source_ref",
        "source_refs",
    }
)
_DEDUPE_KEY_KEYS = frozenset({"dedupe_key", "source_ref_dedupe_key"})


@dataclass(frozen=True)
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass(frozen=True)
class TokenCostRate:
    input_usd_per_1m: float = 0.0
    output_usd_per_1m: float = 0.0

    def __post_init__(self) -> None:
        for label, value in (
            ("input_usd_per_1m", self.input_usd_per_1m),
            ("output_usd_per_1m", self.output_usd_per_1m),
        ):
            if not isfinite(value) or value < 0:
                raise ValueError(f"{label} must be a non-negative finite number")

    @property
    def is_configured(self) -> bool:
        return self.input_usd_per_1m > 0 or self.output_usd_per_1m > 0


@dataclass(frozen=True)
class RetrievedMemory:
    text: str
    rank: int
    score: float = 0.0
    item_id: str | None = None
    created_at: str | None = None
    source_refs: tuple[str, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class IngestionOperation:
    step: int
    operation_type: str
    success: bool
    latency_ms: float = 0.0
    memory: str | None = None
    item_id: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class BackendIngestResult:
    items_processed: int
    items_failed: int = 0
    total_memories_created: int | None = None
    latency_ms: float = 0.0
    reused: bool = False
    operations: tuple[IngestionOperation, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class BackendSearchResult:
    query: str
    memories: tuple[RetrievedMemory, ...]
    latency_ms: float = 0.0
    total_results: int | None = None
    context_token_count: int | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class AnswerResult:
    answer: str
    model: str = "deterministic"
    latency_ms: float = 0.0
    token_usage: TokenUsage = field(default_factory=TokenUsage)
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class JudgeResult:
    verdict: Verdict
    score: float
    reason: str = ""
    model: str = "deterministic"
    latency_ms: float = 0.0
    token_usage: TokenUsage = field(default_factory=TokenUsage)
    metadata: Mapping[str, object] = field(default_factory=dict)


class MemoryComparisonBackendPort(Protocol):
    name: str

    def reset(self, *, run_id: str) -> None:
        """Prepare isolated benchmark state for this run."""

    def ingest(
        self,
        case: PublicBenchmarkCase,
        *,
        run_id: str,
        corpus_key: str,
    ) -> BackendIngestResult:
        """Ingest one reusable conversation/corpus for subsequent searches."""

    def search(
        self,
        case: PublicBenchmarkCase,
        *,
        run_id: str,
        top_k: int,
    ) -> BackendSearchResult:
        """Retrieve memories for a benchmark question."""


class MemoryComparisonAnswererPort(Protocol):
    model: str

    def answer(
        self,
        case: PublicBenchmarkCase,
        memories: Sequence[RetrievedMemory],
        *,
        backend_name: str,
        cutoff: int,
    ) -> AnswerResult:
        """Generate an answer from retrieved memories."""


class MemoryComparisonJudgePort(Protocol):
    model: str

    def judge(
        self,
        case: PublicBenchmarkCase,
        answer: AnswerResult,
        memories: Sequence[RetrievedMemory],
        *,
        backend_name: str,
        cutoff: int,
    ) -> JudgeResult:
        """Judge generated answer against the benchmark ground truth."""


def token_usage_payload(usage: TokenUsage) -> dict[str, int]:
    return {
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "total_tokens": usage.total_tokens,
    }


def token_cost_rate_payload(rate: TokenCostRate) -> dict[str, float]:
    return {
        "input_usd_per_1m": rate.input_usd_per_1m,
        "output_usd_per_1m": rate.output_usd_per_1m,
    }


def token_cost_payload(usage: TokenUsage, rate: TokenCostRate) -> dict[str, object]:
    input_usd = usage.prompt_tokens * rate.input_usd_per_1m / 1_000_000
    output_usd = usage.completion_tokens * rate.output_usd_per_1m / 1_000_000
    return {
        "configured": rate.is_configured,
        "currency": "USD",
        "input_usd": round(input_usd, 8),
        "output_usd": round(output_usd, 8),
        "total_usd": round(input_usd + output_usd, 8),
        "rates_per_1m_tokens": token_cost_rate_payload(rate),
    }


def retrieved_memory_payload(memory: RetrievedMemory) -> dict[str, object]:
    payload: dict[str, object] = {
        "rank": memory.rank,
        "memory": memory.text,
        "score": memory.score,
    }
    if memory.item_id:
        item_id = _safe_output_item_id(memory.item_id)
        if item_id:
            payload["id"] = item_id
    if memory.created_at:
        payload["created_at"] = memory.created_at
    if memory.source_refs:
        source_refs = _safe_source_refs_for_output(memory.source_refs)
        if source_refs:
            payload["source_refs"] = list(source_refs)
    if memory.metadata:
        metadata = _safe_output_metadata(memory.metadata)
        if metadata:
            payload["metadata"] = metadata
    return payload


def ingestion_payload(result: BackendIngestResult) -> dict[str, object]:
    payload: dict[str, object] = {
        "items_processed": result.items_processed,
        "items_failed": result.items_failed,
        "latency_ms": result.latency_ms,
        "reused": result.reused,
    }
    if result.total_memories_created is not None:
        payload["total_memories_created"] = result.total_memories_created
    if result.operations:
        payload["operations"] = [
            {
                "step": operation.step,
                "type": operation.operation_type,
                "success": operation.success,
                "latency_ms": operation.latency_ms,
                **({"memory": operation.memory} if operation.memory else {}),
                **(
                    {"id": item_id}
                    if operation.item_id
                    and (item_id := _safe_output_item_id(operation.item_id))
                    else {}
                ),
                **(
                    {"metadata": metadata}
                    if operation.metadata
                    and (metadata := _safe_output_metadata(operation.metadata))
                    else {}
                ),
            }
            for operation in result.operations
        ]
    if result.metadata:
        metadata = _safe_output_metadata(result.metadata)
        if metadata:
            payload["metadata"] = metadata
    return payload


def search_payload(result: BackendSearchResult) -> dict[str, object]:
    payload: dict[str, object] = {
        "query": result.query,
        "latency_ms": result.latency_ms,
        "results": [retrieved_memory_payload(memory) for memory in result.memories],
        "total_results": result.total_results
        if result.total_results is not None
        else len(result.memories),
    }
    if result.context_token_count is not None:
        payload["context_token_count"] = result.context_token_count
    if result.metadata:
        metadata = _safe_output_metadata(result.metadata)
        if metadata:
            payload["metadata"] = metadata
    return payload


def _safe_output_metadata(value: Mapping[str, object]) -> dict[str, object]:
    metadata: dict[str, object] = {}
    for key, raw_value in value.items():
        safe_value = _safe_output_value(
            raw_value,
            key=str(key).strip().casefold(),
        )
        if safe_value is not None:
            metadata[str(key)] = safe_value
    return metadata


def _safe_output_value(value: object, *, key: str = "") -> object | None:
    if key in _RAW_PROVIDER_PAYLOAD_KEYS or key.endswith("_payload"):
        return None
    if key in _SOURCE_REF_KEYS or key.endswith(("_source_ref", "_source_refs")):
        refs = _safe_source_refs_for_output(value)
        if refs:
            return list(refs) if key.endswith("s") else refs[0]
        return None
    if key in _DEDUPE_KEY_KEYS:
        return _safe_output_dedupe_key(value)
    if key == "id" or key == "item_id" or key.endswith("_item_id"):
        return _safe_output_item_id(value)
    if isinstance(value, Mapping):
        nested: dict[str, object] = {}
        for nested_key, raw_value in value.items():
            safe_value = _safe_output_value(
                raw_value,
                key=str(nested_key).strip().casefold(),
            )
            if safe_value is not None:
                nested[str(nested_key)] = safe_value
        return nested or None
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        nested_values = [
            safe_value
            for item in value
            if (safe_value := _safe_output_value(item)) is not None
        ]
        return nested_values
    if isinstance(value, str) and _looks_like_raw_source_ref(value):
        return _REDACTED_OUTPUT_TEXT
    return value


def _safe_output_item_id(value: object) -> str | None:
    item_id = _safe_item_id_for_output(value)
    if item_id:
        return item_id
    refs = _safe_source_refs_for_output((value,))
    return refs[0] if refs else None


def _safe_output_dedupe_key(value: object) -> str | None:
    raw_key = str(value or "").strip()
    if not raw_key:
        return None
    identity_refs = _source_identity_refs_from_dedupe_key(raw_key)
    if identity_refs:
        return "source_identity:" + "|".join(identity_refs)
    refs = _safe_source_refs_for_output((raw_key,))
    if refs:
        return "source_identity:" + "|".join(refs)
    item_id = _safe_item_id_for_output(raw_key)
    return item_id or None


def answer_payload(result: AnswerResult) -> dict[str, object]:
    payload: dict[str, object] = {
        "model": result.model,
        "answer": result.answer,
        "latency_ms": result.latency_ms,
        "token_usage": token_usage_payload(result.token_usage),
    }
    if result.metadata:
        metadata = _safe_output_metadata(result.metadata)
        if metadata:
            payload["metadata"] = metadata
    return payload


def judge_payload(result: JudgeResult) -> dict[str, object]:
    payload: dict[str, object] = {
        "model": result.model,
        "verdict": result.verdict,
        "score": result.score,
        "reason": result.reason,
        "latency_ms": result.latency_ms,
        "token_usage": token_usage_payload(result.token_usage),
    }
    if result.metadata:
        metadata = _safe_output_metadata(result.metadata)
        if metadata:
            payload["metadata"] = metadata
    return payload


def as_public_mapping(value: Any) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}

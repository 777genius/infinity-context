"""Search and prompt-context API."""

from __future__ import annotations

import re
from time import perf_counter
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from infinity_context_core.application import BuildContextQuery, ConsistencyMode
from infinity_context_core.application.context_diagnostics import (
    normalize_context_bundle_diagnostics,
)
from pydantic import BaseModel, ConfigDict, Field

from infinity_context_server.api.auth import require_service_token
from infinity_context_server.api.dependencies import get_container
from infinity_context_server.api.policy import should_retrieve
from infinity_context_server.api.public_payload import safe_public_text
from infinity_context_server.api.v1.scope_resolution import (
    resolve_existing_context_scope,
)
from infinity_context_server.api.v1.source_refs import source_ref_to_response
from infinity_context_server.composition import Container

router = APIRouter(tags=["context"], dependencies=[Depends(require_service_token)])

_MAX_PUBLIC_CONTEXT_SOURCE_REFS = 20


class ContextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    space_id: str | None = Field(default=None, min_length=1, max_length=80)
    memory_scope_ids: list[str] | None = Field(default=None, min_length=1, max_length=20)
    thread_id: str | None = Field(default=None, max_length=80)
    space_slug: str | None = Field(default=None, min_length=1, max_length=160)
    memory_scope_external_ref: str | None = Field(default=None, min_length=1, max_length=200)
    memory_scope_external_refs: list[str] | None = Field(default=None, min_length=1, max_length=20)
    thread_external_ref: str | None = Field(default=None, min_length=1, max_length=200)
    query: str = Field(min_length=1, max_length=12000)
    consistency_mode: ConsistencyMode = Field(default=ConsistencyMode.BEST_EFFORT)
    token_budget: int = Field(default=1800, ge=64, le=16000)
    max_facts: int = Field(default=20, ge=0, le=100)
    max_chunks: int = Field(default=30, ge=0, le=200)
    max_evidence_items: int = Field(default=12, ge=0, le=100)
    max_conflicting_suggestions: int = Field(default=5, ge=0, le=20)
    include_superseded: bool = False
    include_stale: bool = False
    category: str | None = Field(default=None, max_length=80)
    tags_any: list[str] = Field(default_factory=list, max_length=10)
    tags_all: list[str] = Field(default_factory=list, max_length=10)
    tags_none: list[str] = Field(default_factory=list, max_length=10)


def context_item_to_response(item) -> dict[str, Any]:
    diagnostics = dict(item.diagnostics or {})
    source_refs = tuple(item.source_refs)
    public_source_refs = source_refs[:_MAX_PUBLIC_CONTEXT_SOURCE_REFS]
    citations = [
        _source_ref_to_citation(
            ref,
            item_id=str(item.item_id),
            item_type=str(item.item_type),
            index=index,
            diagnostics=diagnostics,
        )
        for index, ref in enumerate(public_source_refs)
    ]
    diagnostics["source_refs_total"] = len(source_refs)
    diagnostics["source_refs_returned"] = len(public_source_refs)
    diagnostics["source_refs_truncated"] = len(source_refs) > len(public_source_refs)
    diagnostics["citations_total"] = len(source_refs)
    diagnostics["citations_returned"] = len(citations)
    diagnostics["citations_truncated"] = len(source_refs) > len(citations)
    return {
        "item_id": item.item_id,
        "item_type": item.item_type,
        "memory_scope_id": diagnostics.get("memory_scope_id"),
        "text": item.text,
        "score": item.score,
        "source_refs": [source_ref_to_response(ref) for ref in public_source_refs],
        "citations": citations,
        "is_instruction": item.is_instruction,
        "diagnostics": diagnostics,
    }


def _source_ref_to_citation(
    ref: object,
    *,
    item_id: str,
    item_type: str,
    index: int,
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    source = source_ref_to_response(ref)
    citation_id = _citation_id(
        item_id=item_id,
        item_type=item_type,
        index=index,
    )
    evidence = _citation_evidence_context(diagnostics)
    char_range = _range_payload(source.get("char_start"), source.get("char_end"))
    time_range_ms = _range_payload(source.get("time_start_ms"), source.get("time_end_ms"))
    return {
        "citation_id": citation_id,
        "label": _citation_label(source, index=index, evidence=evidence),
        "source_type": source["source_type"],
        "source_id": source["source_id"],
        "chunk_id": source["chunk_id"],
        "quote_preview": source["quote_preview"],
        "char_range": char_range,
        "page_number": source["page_number"],
        "time_range_ms": time_range_ms,
        "bbox": source["bbox"],
        "evidence_kind": evidence["evidence_kind"],
        "evidence_modality": evidence["evidence_modality"],
        "evidence_confidence": evidence["evidence_confidence"],
        "retrieval_source": evidence["retrieval_source"],
        "ranking_reason": evidence["ranking_reason"],
    }


def _citation_id(*, item_id: str, item_type: str, index: int) -> str:
    safe_item_type = re.sub(r"[^a-zA-Z0-9_.:-]+", "_", item_type)[:80] or "item"
    safe_item_id = re.sub(r"[^a-zA-Z0-9_.:-]+", "_", item_id)[:120] or "unknown"
    return f"{safe_item_type}:{safe_item_id}:citation:{index + 1}"


def _citation_label(
    source: dict[str, Any],
    *,
    index: int,
    evidence: dict[str, Any],
) -> str:
    parts = [f"[{index + 1}]"]
    if evidence.get("evidence_kind"):
        parts.append(str(evidence["evidence_kind"]))
    if evidence.get("evidence_modality"):
        parts.append(str(evidence["evidence_modality"]))
    parts.append(str(source.get("source_type") or "source"))
    source_id = str(source.get("source_id") or "")
    if source_id:
        parts.append(source_id)
    if source.get("page_number") is not None:
        parts.append(f"p.{source['page_number']}")
    if source.get("time_start_ms") is not None or source.get("time_end_ms") is not None:
        parts.append(
            f"{source.get('time_start_ms') or 0}-{source.get('time_end_ms') or 0}ms"
        )
    if source.get("bbox") is not None:
        parts.append("bbox")
    return safe_public_text(" ".join(parts))[:240]


def _citation_evidence_context(diagnostics: dict[str, Any]) -> dict[str, Any]:
    provenance = diagnostics.get("provenance")
    if not isinstance(provenance, dict):
        provenance = {}
    return {
        "evidence_kind": _optional_safe_text(
            diagnostics.get("evidence_kind") or provenance.get("evidence_kind")
        ),
        "evidence_modality": _optional_safe_text(
            diagnostics.get("evidence_modality") or provenance.get("evidence_modality")
        ),
        "evidence_confidence": _optional_float(
            diagnostics.get("evidence_confidence") or provenance.get("evidence_confidence")
        ),
        "retrieval_source": _optional_safe_text(diagnostics.get("retrieval_source")),
        "ranking_reason": _optional_safe_text(diagnostics.get("ranking_reason")),
    }


def _optional_safe_text(value: object) -> str | None:
    if value is None:
        return None
    text = safe_public_text(str(value)).strip()
    return text[:240] if text else None


def _optional_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _range_payload(start: object, end: object) -> dict[str, int | None] | None:
    if start is None and end is None:
        return None
    return {
        "start": int(start) if isinstance(start, int) else None,
        "end": int(end) if isinstance(end, int) else None,
    }


def _context_diagnostics_to_response(
    diagnostics: dict[str, Any],
    *,
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    response = dict(diagnostics)
    item_diagnostics = [
        item.get("diagnostics")
        for item in items
        if isinstance(item.get("diagnostics"), dict)
    ]
    source_refs_total = sum(
        _non_negative_int(item.get("source_refs_total")) for item in item_diagnostics
    )
    source_refs_returned = sum(
        _non_negative_int(item.get("source_refs_returned")) for item in item_diagnostics
    )
    citations_total = sum(
        _non_negative_int(item.get("citations_total")) for item in item_diagnostics
    )
    citations_returned = sum(len(item.get("citations") or []) for item in items)
    response.update(
        {
            "source_refs_total": source_refs_total,
            "source_refs_returned": source_refs_returned,
            "source_refs_truncated": source_refs_total > source_refs_returned,
            "citations_total": citations_total,
            "citations_returned": citations_returned,
            "citations_truncated": citations_total > citations_returned,
            "items_with_citations": sum(1 for item in items if item.get("citations")),
        }
    )
    return response


def _non_negative_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)


@router.post("/context")
async def build_context(
    request: ContextRequest,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    started = perf_counter()
    request_id = container.ids.new_id("req")
    if not should_retrieve(container):
        response = _empty_context_response(
            policy_mode=container.settings.policy_mode.value,
            request_id=request_id,
            consistency_mode=request.consistency_mode.value,
        )
        container.runtime_metrics.record_context(
            latency_ms=_elapsed_ms(started),
            diagnostics=response["data"]["diagnostics"],
            request_id=request_id,
            use_case="build_context",
        )
        return response
    scope = await resolve_existing_context_scope(
        container,
        space_id=request.space_id,
        memory_scope_ids=request.memory_scope_ids,
        thread_id=request.thread_id,
        space_slug=request.space_slug,
        memory_scope_external_ref=request.memory_scope_external_ref,
        memory_scope_external_refs=request.memory_scope_external_refs,
        thread_external_ref=request.thread_external_ref,
    )
    if scope is None:
        response = _empty_context_response(
            policy_mode=container.settings.policy_mode.value,
            request_id=request_id,
            consistency_mode=request.consistency_mode.value,
            scope_not_found=True,
        )
        container.runtime_metrics.record_context(
            latency_ms=_elapsed_ms(started),
            diagnostics=response["data"]["diagnostics"],
            request_id=request_id,
            use_case="build_context",
        )
        return response
    bundle = await container.build_context.execute(
        BuildContextQuery(
            space_id=scope.space_id,
            memory_scope_ids=scope.memory_scope_ids,
            thread_id=scope.thread_id,
            query=request.query,
            consistency_mode=request.consistency_mode,
            token_budget=request.token_budget,
            max_rendered_chars=container.settings.max_context_chars,
            max_facts=request.max_facts,
            max_chunks=request.max_chunks,
            max_evidence_items=request.max_evidence_items,
            max_conflicting_suggestions=request.max_conflicting_suggestions,
            include_superseded=request.include_superseded,
            include_stale=request.include_stale,
            category=_normalize_label(request.category),
            tags_any=_normalize_tags(request.tags_any),
            tags_all=_normalize_tags(request.tags_all),
            tags_none=_normalize_tags(request.tags_none),
        )
    )
    response_items = [context_item_to_response(item) for item in bundle.items]
    response_diagnostics = _context_diagnostics_to_response(
        bundle.diagnostics,
        items=response_items,
    )
    response = {
        "meta": {"request_id": request_id},
        "data": {
            "bundle_id": bundle.bundle_id,
            "rendered_text": bundle.rendered_text,
            "items": response_items,
            "diagnostics": response_diagnostics,
        },
    }
    container.runtime_metrics.record_context(
        latency_ms=_elapsed_ms(started),
        diagnostics=response_diagnostics,
        request_id=request_id,
        use_case="build_context",
        scope=_trace_scope(scope),
    )
    return response


@router.post("/search")
async def search_memory(
    request: ContextRequest,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    started = perf_counter()
    request_id = container.ids.new_id("req")
    if not should_retrieve(container):
        response = {
            "meta": {"request_id": request_id},
            "data": {
                "items": [],
                "next_cursor": None,
                "diagnostics": _empty_context_diagnostics(
                    policy_mode=container.settings.policy_mode.value,
                    consistency_mode=request.consistency_mode.value,
                    retrieval_disabled=True,
                ),
            },
        }
        container.runtime_metrics.record_context(
            latency_ms=_elapsed_ms(started),
            diagnostics=response["data"]["diagnostics"],
            request_id=request_id,
            use_case="search_memory",
        )
        return response
    scope = await resolve_existing_context_scope(
        container,
        space_id=request.space_id,
        memory_scope_ids=request.memory_scope_ids,
        thread_id=request.thread_id,
        space_slug=request.space_slug,
        memory_scope_external_ref=request.memory_scope_external_ref,
        memory_scope_external_refs=request.memory_scope_external_refs,
        thread_external_ref=request.thread_external_ref,
    )
    if scope is None:
        response = _empty_search_response(
            policy_mode=container.settings.policy_mode.value,
            request_id=request_id,
            consistency_mode=request.consistency_mode.value,
            scope_not_found=True,
        )
        container.runtime_metrics.record_context(
            latency_ms=_elapsed_ms(started),
            diagnostics=response["data"]["diagnostics"],
            request_id=request_id,
            use_case="search_memory",
        )
        return response
    bundle = await container.build_context.execute(
        BuildContextQuery(
            space_id=scope.space_id,
            memory_scope_ids=scope.memory_scope_ids,
            thread_id=scope.thread_id,
            query=request.query,
            consistency_mode=request.consistency_mode,
            token_budget=request.token_budget,
            max_rendered_chars=container.settings.max_context_chars,
            max_facts=request.max_facts,
            max_chunks=request.max_chunks,
            max_evidence_items=request.max_evidence_items,
            max_conflicting_suggestions=request.max_conflicting_suggestions,
            include_superseded=request.include_superseded,
            include_stale=request.include_stale,
            category=_normalize_label(request.category),
            tags_any=_normalize_tags(request.tags_any),
            tags_all=_normalize_tags(request.tags_all),
            tags_none=_normalize_tags(request.tags_none),
        )
    )
    response_items = [context_item_to_response(item) for item in bundle.items]
    response_diagnostics = _context_diagnostics_to_response(
        bundle.diagnostics,
        items=response_items,
    )
    response = {
        "meta": {"request_id": request_id},
        "data": {
            "items": response_items,
            "next_cursor": None,
            "diagnostics": response_diagnostics,
        },
    }
    container.runtime_metrics.record_context(
        latency_ms=_elapsed_ms(started),
        diagnostics=response_diagnostics,
        request_id=request_id,
        use_case="search_memory",
        scope=_trace_scope(scope),
    )
    return response


def _empty_context_response(
    *,
    policy_mode: str,
    request_id: str,
    consistency_mode: str,
    scope_not_found: bool = False,
) -> dict[str, Any]:
    return {
        "meta": {"request_id": request_id},
        "data": {
            "bundle_id": "ctx_disabled",
            "rendered_text": "",
            "items": [],
            "diagnostics": _empty_context_diagnostics(
                policy_mode=policy_mode,
                consistency_mode=consistency_mode,
                retrieval_disabled=not scope_not_found,
                scope_not_found=scope_not_found,
            ),
        },
    }


def _empty_search_response(
    *,
    policy_mode: str,
    request_id: str,
    consistency_mode: str,
    scope_not_found: bool = False,
) -> dict[str, Any]:
    return {
        "meta": {"request_id": request_id},
        "data": {
            "items": [],
            "next_cursor": None,
            "diagnostics": _empty_context_diagnostics(
                policy_mode=policy_mode,
                consistency_mode=consistency_mode,
                retrieval_disabled=not scope_not_found,
                scope_not_found=scope_not_found,
            ),
        },
    }


def _empty_context_diagnostics(
    *,
    policy_mode: str,
    consistency_mode: str,
    retrieval_disabled: bool,
    scope_not_found: bool = False,
) -> dict[str, object]:
    reason = "scope_not_found" if scope_not_found else "retrieval_disabled"
    return normalize_context_bundle_diagnostics(
        {
            "context_assembly_version": "context-v2-hybrid-explainable",
            "consistency_mode": consistency_mode,
            "policy_mode": policy_mode,
            "retrieval_disabled": retrieval_disabled,
            "scope_not_found": scope_not_found,
            "vector_status": "skipped",
            "vector_skip_reason": reason,
            "graph_status": "skipped",
            "graph_skip_reason": reason,
            "rag_status": "skipped",
            "rag_skip_reason": reason,
        },
        items=(),
    )


def _elapsed_ms(started: float) -> float:
    return (perf_counter() - started) * 1000


_LABEL_RE = re.compile(r"[^a-z0-9_-]+")


def _normalize_label(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = _LABEL_RE.sub("_", value.strip().lower()).strip("_-")
    return normalized or None


def _normalize_tags(values: list[str]) -> tuple[str, ...]:
    tags: list[str] = []
    for value in values:
        normalized = _normalize_label(value)
        if normalized and normalized not in tags:
            tags.append(normalized[:48].rstrip("_-"))
    return tuple(tag for tag in tags if tag)


def _trace_scope(scope) -> dict[str, object]:
    return {
        "space_id": str(scope.space_id),
        "memory_scope_ids": tuple(
            str(memory_scope_id) for memory_scope_id in scope.memory_scope_ids
        ),
        "thread_id": str(scope.thread_id) if scope.thread_id else None,
    }

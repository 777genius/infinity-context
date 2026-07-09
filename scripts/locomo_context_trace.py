"""Trace a targeted LoCoMo benchmark case through context retrieval."""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from infinity_context_adapters.postgres.models import (
    MemoryChunkRow,
    MemoryDocumentRow,
    MemoryScopeRow,
    MemorySpaceRow,
    MemoryThreadRow,
)
from infinity_context_core.application import BuildContextQuery
from infinity_context_core.application.context_collectors import (
    _bounded_derived_retrieval_queries,
    _keyword_candidate_pool_limit,
    _keyword_query_search_limit,
    _keyword_search_chunks,
)
from infinity_context_core.application.context_query_expansion import (
    build_query_expansion_plan,
)
from infinity_context_core.application.context_relevance import (
    has_project_identity_mismatch,
    is_chunk_candidate_relevance_sufficient,
)
from infinity_context_core.application.context_source_siblings import (
    source_group_seed_turns,
)
from infinity_context_core.application.document_text import (
    document_chunk_retrieval_text,
)
from infinity_context_core.application.use_cases.build_context import (
    _best_query_relevance_cached,
    _prioritize_source_sibling_answer_evidence_seed_chunks,
)
from infinity_context_server.config import DeployProfile, Settings
from infinity_context_server.main import create_app
from infinity_context_server.public_benchmark import (
    _case_capability,
    _dataset_hash,
    _load_cases,
    _run_case,
)
from infinity_context_server.public_benchmark_checkpoint import BenchmarkSeedStats
from infinity_context_server.public_benchmark_http import auth_headers
from infinity_context_server.public_benchmark_models import TestClientBenchmarkAdapter
from sqlalchemy import select


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path(".e2e-artifacts/locomo10.json"))
    parser.add_argument("--case-id", default="conv-26:qa:14")
    args = parser.parse_args()
    trace = _trace_case(dataset_path=args.dataset, case_id=args.case_id)
    print(json.dumps(trace, indent=2, ensure_ascii=False, sort_keys=True))


def _trace_case(*, dataset_path: Path, case_id: str) -> dict[str, Any]:
    cases = [case for case in _load_cases(dataset_path) if case.case_id == case_id]
    if len(cases) != 1:
        raise SystemExit(f"expected exactly one case for {case_id!r}, found {len(cases)}")
    case = cases[0]
    token = "test-token"
    dataset_hash = _dataset_hash(dataset_path)
    scope_slug = f"public-benchmark-{dataset_hash[:16]}"
    memory_scope_ref = case.memory_scope_external_ref or f"{case.benchmark}-{case.case_id}"
    thread_ref = case.thread_external_ref or f"{case.benchmark}-{case.case_id}"
    with tempfile.TemporaryDirectory(prefix="memo-locomo-trace-") as tmp_dir:
        app = create_app(
            Settings(
                deploy_profile=DeployProfile.TEST,
                database_url=f"sqlite+aiosqlite:///{Path(tmp_dir) / 'memory.db'}",
                auto_create_schema=True,
                service_token=token,
                qdrant_enabled=False,
                graphiti_enabled=False,
                embeddings_enabled=False,
            )
        )
        with TestClient(app) as test_client:
            adapter = TestClientBenchmarkAdapter(test_client)
            result = _run_case(
                adapter=adapter,
                headers=auth_headers(token),
                scope_slug=scope_slug,
                dataset_hash=dataset_hash,
                case=case,
                seeded_source_keys=set(),
                seeded_corpus_identities=set(),
                seed_corpus_metadata_cache={},
                seed_stats=BenchmarkSeedStats(),
            )
            context_response = test_client.post(
                "/v1/context",
                headers=auth_headers(token),
                json={
                    "space_slug": scope_slug,
                    "memory_scope_external_ref": memory_scope_ref,
                    "thread_external_ref": thread_ref,
                    "query": case.question,
                    "token_budget": 4000,
                    "max_facts": 20,
                    "max_chunks": 50,
                },
            )
            context_response.raise_for_status()
            context_data = context_response.json()["data"]
            source_trace = asyncio.run(
                _source_trace(
                    app.state.container.engine,
                    refs=tuple(result.evidence_refs),
                )
            )
            core_context = asyncio.run(
                _core_context_trace(
                    app.state.container,
                    scope_slug=scope_slug,
                    memory_scope_ref=memory_scope_ref,
                    thread_ref=thread_ref,
                    question=case.question,
                )
            )
            keyword_trace = asyncio.run(
                _keyword_rank_trace(
                    app.state.container,
                    scope_slug=scope_slug,
                    memory_scope_ref=memory_scope_ref,
                    thread_ref=thread_ref,
                    question=case.question,
                    refs=tuple(result.evidence_refs),
                    max_chunks=50,
                )
            )
    return {
        "case_id": case.case_id,
        "capability": _case_capability(case),
        "question": case.question,
        "evidence_refs": list(result.evidence_refs),
        "covered_evidence_refs": list(result.covered_evidence_refs),
        "missing_evidence_refs": list(result.missing_evidence_refs),
        "source_trace": source_trace,
        "keyword_trace": keyword_trace,
        "core_context": core_context,
        "pre_pack": _pre_pack_summary(context_data.get("diagnostics", {})),
        "selected_items": _selected_items(context_data),
        "rendered_contains": {
            ref: ref in str(context_data.get("rendered_text") or "")
            for ref in result.evidence_refs
        },
    }


async def _keyword_rank_trace(
    container: Any,
    *,
    scope_slug: str,
    memory_scope_ref: str,
    thread_ref: str,
    question: str,
    refs: tuple[str, ...],
    max_chunks: int,
) -> dict[str, Any]:
    async with container.engine.connect() as conn:
        row = (
            await conn.execute(
                select(MemorySpaceRow.id, MemoryScopeRow.id, MemoryThreadRow.id)
                .join(MemoryScopeRow, MemoryScopeRow.space_id == MemorySpaceRow.id)
                .join(MemoryThreadRow, MemoryThreadRow.memory_scope_id == MemoryScopeRow.id)
                .where(
                    MemorySpaceRow.slug == scope_slug,
                    MemoryScopeRow.external_ref == memory_scope_ref,
                    MemoryThreadRow.external_ref == thread_ref,
                )
                .limit(1)
            )
        ).first()
    if row is None:
        return {"error": "scope_not_found"}
    plan = build_query_expansion_plan(question)
    retrieval_queries = _bounded_derived_retrieval_queries(plan, fallback=question)
    candidate_limit = _keyword_candidate_pool_limit(max_chunks)
    search_limit = _keyword_query_search_limit(
        total_limit=max_chunks,
        candidate_limit=candidate_limit,
    )
    traces: list[dict[str, Any]] = []
    canonical_chunks = []
    prioritized_seed_chunks = ()
    used_keyword_chunks = []
    keyword_decisions: list[dict[str, Any]] = []
    async with container.uow_factory() as uow:
        canonical_chunks = list(
            await _keyword_search_chunks(
                uow,
                space_id=str(row[0]),
                memory_scope_ids=(str(row[1]),),
                thread_id=str(row[2]),
                retrieval_queries=retrieval_queries,
                limit=max_chunks,
            )
        )
        prioritized_seed_chunks = _prioritize_source_sibling_answer_evidence_seed_chunks(
            seed_chunks=tuple(canonical_chunks),
            query_plan=plan,
            query_relevance_cache={},
        )
        relevance_cache: dict[str, tuple[str, str, Any]] = {}
        for rank, chunk in enumerate(canonical_chunks, start=1):
            chunk_text = document_chunk_retrieval_text(
                text=chunk.text,
                metadata=chunk.metadata,
            )
            expansion_query, expansion_reason, relevance = _best_query_relevance_cached(
                plan,
                text=chunk_text,
                cache=relevance_cache,
            )
            mismatch = has_project_identity_mismatch(
                query=question,
                text=chunk_text,
            )
            sufficient = is_chunk_candidate_relevance_sufficient(
                query=expansion_query,
                text=chunk_text,
                relevance=relevance,
            )
            if not mismatch and sufficient:
                used_keyword_chunks.append(chunk)
            if "session_27" in str(chunk.source_external_id) or "D27:" in chunk.text:
                keyword_decisions.append(
                    {
                        "rank": rank,
                        "source_external_id": str(chunk.source_external_id),
                        "expansion_reason": expansion_reason,
                        "distinctive_hits": relevance.distinctive_term_hits,
                        "unique_hits": relevance.unique_term_hits,
                        "hit_ratio": relevance.hit_ratio,
                        "identity_mismatch": mismatch,
                        "relevance_sufficient": sufficient,
                        "used": not mismatch and sufficient,
                        "text_preview": _preview(chunk_text, ref="D27"),
                    }
                )
        for index, retrieval_query in enumerate(retrieval_queries):
            chunks = await uow.chunks.keyword_search(
                space_id=str(row[0]),
                memory_scope_ids=(str(row[1]),),
                thread_id=str(row[2]),
                query=retrieval_query.query,
                limit=search_limit,
            )
            traces.append(
                {
                    "index": index,
                    "reason": retrieval_query.reason,
                    "query": retrieval_query.query,
                    "rank_hits": {
                        ref: [
                            _keyword_hit_summary(rank=rank, chunk=chunk, ref=ref)
                            for rank, chunk in enumerate(chunks, start=1)
                            if _chunk_contains_ref(chunk, ref)
                        ][:5]
                        for ref in refs
                    },
                    "session_27_hits": [
                        _keyword_hit_summary(rank=rank, chunk=chunk, ref="D27")
                        for rank, chunk in enumerate(chunks, start=1)
                        if "session_27" in str(chunk.source_external_id)
                        or "D27:" in chunk.text
                    ][:10],
                    "top_sources": [
                        str(chunk.source_external_id)
                        for chunk in chunks[:20]
                    ],
                }
            )
    return {
        "query_count": len(retrieval_queries),
        "candidate_limit": candidate_limit,
        "search_limit": search_limit,
        "canonical_keyword_source_ids_sample": [
            str(chunk.source_external_id) for chunk in canonical_chunks[:80]
        ],
        "canonical_keyword_d27_hits": [
            _keyword_hit_summary(rank=rank, chunk=chunk, ref="D27")
            for rank, chunk in enumerate(canonical_chunks, start=1)
            if "session_27" in str(chunk.source_external_id)
            or "D27:" in chunk.text
        ][:20],
        "prioritized_seed_source_ids_sample": [
            str(chunk.source_external_id) for chunk in prioritized_seed_chunks[:80]
        ],
        "prioritized_seed_d27_hits": [
            _keyword_hit_summary(rank=rank, chunk=chunk, ref="D27")
            for rank, chunk in enumerate(prioritized_seed_chunks, start=1)
            if "session_27" in str(chunk.source_external_id)
            or "D27:" in chunk.text
        ][:20],
        "used_keyword_d27_decisions": keyword_decisions[:20],
        "used_keyword_d27_hits": [
            _keyword_hit_summary(rank=rank, chunk=chunk, ref="D27")
            for rank, chunk in enumerate(used_keyword_chunks, start=1)
            if "session_27" in str(chunk.source_external_id)
            or "D27:" in chunk.text
        ][:20],
        "prioritized_seed_groups_sample": list(
            source_group_seed_turns(prioritized_seed_chunks).keys()
        )[:40],
        "queries": traces,
    }


def _chunk_contains_ref(chunk: Any, ref: str) -> bool:
    metadata = getattr(chunk, "metadata", None) or {}
    return (
        ref in str(chunk.source_external_id)
        or ref in chunk.text
        or ref in json.dumps(metadata, ensure_ascii=False)
    )


def _keyword_hit_summary(*, rank: int, chunk: Any, ref: str) -> dict[str, Any]:
    return {
        "rank": rank,
        "source_external_id": str(chunk.source_external_id),
        "text_preview": _preview(chunk.text, ref=ref),
    }


async def _core_context_trace(
    container: Any,
    *,
    scope_slug: str,
    memory_scope_ref: str,
    thread_ref: str,
    question: str,
) -> dict[str, Any]:
    async with container.engine.connect() as conn:
        row = (
            await conn.execute(
                select(MemorySpaceRow.id, MemoryScopeRow.id, MemoryThreadRow.id)
                .join(MemoryScopeRow, MemoryScopeRow.space_id == MemorySpaceRow.id)
                .join(MemoryThreadRow, MemoryThreadRow.memory_scope_id == MemoryScopeRow.id)
                .where(
                    MemorySpaceRow.slug == scope_slug,
                    MemoryScopeRow.external_ref == memory_scope_ref,
                    MemoryThreadRow.external_ref == thread_ref,
                )
                .limit(1)
            )
        ).first()
    if row is None:
        return {"error": "scope_not_found"}
    bundle = await container.build_context.execute(
        BuildContextQuery(
            space_id=str(row[0]),
            memory_scope_ids=(str(row[1]),),
            thread_id=str(row[2]),
            query=question,
            token_budget=4000,
            max_facts=20,
            max_chunks=50,
        )
    )
    return {
        "diagnostics": {
            key: value
            for key, value in bundle.diagnostics.items()
            if key.startswith("pre_pack")
            or key.startswith("answer_support")
            or key.startswith("dropped_by")
            or key in {"items_considered", "items_used"}
            or key.startswith("keyword_source_sibling")
            or key.startswith("keyword_aggregation")
            or "source_sibling_answer_evidence" in key
            or key.startswith("post_dedupe_hydrate_source_sibling")
            or key.startswith("final_source_source_sibling")
            or key.startswith("final_candidate_source_sibling")
            or key.startswith("guarded_source_sibling")
            or key.startswith("exact_source_sibling_answer_evidence_repair")
            or key in {"final_rank_candidate_item_count", "final_rank_source_item_count"}
        },
        "items": [
            {
                "item_id": item.item_id,
                "item_type": item.item_type,
                "score": item.score,
                "source_ids": [ref.source_id for ref in item.source_refs],
                "retrieval_source": (item.diagnostics or {}).get("retrieval_source"),
                "ranking_reason": (item.diagnostics or {}).get("ranking_reason"),
                "query_expansion_reason": (item.diagnostics or {}).get("query_expansion_reason"),
                "score_signals": (item.diagnostics or {}).get("score_signals"),
                "text_preview": item.text[:240],
            }
            for item in bundle.items
        ],
    }


async def _source_trace(engine: Any, *, refs: tuple[str, ...]) -> dict[str, Any]:
    async with engine.connect() as conn:
        document_rows = (
            await conn.execute(
                select(
                    MemoryDocumentRow.id,
                    MemoryDocumentRow.source_external_id,
                    MemoryDocumentRow.title,
                )
            )
        ).all()
        chunk_rows = (
            await conn.execute(
                select(
                    MemoryChunkRow.id,
                    MemoryChunkRow.source_external_id,
                    MemoryChunkRow.sequence,
                    MemoryChunkRow.text,
                    MemoryChunkRow.metadata_json,
                )
            )
        ).all()
    return {
        "document_count": len(document_rows),
        "chunk_count": len(chunk_rows),
        "refs": {
            ref: {
                "documents_containing_ref": [
                    {
                        "id": str(row.id),
                        "source_external_id": str(row.source_external_id),
                        "title": str(row.title),
                    }
                    for row in document_rows
                    if ref in str(row.source_external_id) or ref in str(row.title)
                ],
                "chunks_containing_ref": [
                    {
                        "id": str(row.id),
                        "source_external_id": str(row.source_external_id),
                        "sequence": int(row.sequence),
                        "text_preview": _preview(str(row.text), ref=ref),
                        "metadata_source_refs": (row.metadata_json or {}).get("source_refs"),
                    }
                    for row in chunk_rows
                    if ref in str(row.source_external_id)
                    or ref in str(row.text)
                    or ref in json.dumps(row.metadata_json or {}, ensure_ascii=False)
                ],
            }
            for ref in refs
        },
    }


def _pre_pack_summary(diagnostics: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidate_item_count": diagnostics.get("pre_pack_candidate_item_count"),
        "items_with_source_refs": diagnostics.get("pre_pack_items_with_source_refs"),
        "source_ref_ids_sample": diagnostics.get("pre_pack_source_ref_ids_sample"),
        "dialogue_markers_sample": diagnostics.get("pre_pack_dialogue_markers_sample"),
    }


def _selected_items(context_data: dict[str, Any]) -> list[dict[str, Any]]:
    items = context_data.get("items")
    if not isinstance(items, list):
        return []
    selected: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        refs = [
            str(ref.get("source_id"))
            for ref in item.get("source_refs") or []
            if isinstance(ref, dict)
        ]
        selected.append(
            {
                "item_id": item.get("item_id"),
                "item_type": item.get("item_type"),
                "score": item.get("score"),
                "retrieval_source": (item.get("diagnostics") or {}).get("retrieval_source"),
                "ranking_reason": (item.get("diagnostics") or {}).get("ranking_reason"),
                "source_ids": refs,
                "text_preview": str(item.get("text") or "")[:240],
            }
        )
    return selected


def _preview(text: str, *, ref: str) -> str:
    index = text.find(ref)
    if index < 0:
        return text[:240]
    start = max(0, index - 120)
    end = min(len(text), index + 240)
    return text[start:end]


if __name__ == "__main__":
    started = time.perf_counter()
    main()
    _ = started

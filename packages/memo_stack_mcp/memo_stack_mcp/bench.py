"""Small benchmark for the Memo Stack MCP adapter path."""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
import uuid
from dataclasses import dataclass, field, replace
from typing import Any

from memo_stack_mcp.adapters.http_gateway import HttpMemoryGateway
from memo_stack_mcp.application.service import MemoryToolService
from memo_stack_mcp.config import MemoryMcpSettings, load_settings
from memo_stack_mcp.domain.policy import (
    MemoryMcpDeleteMode,
    MemoryMcpIngestMode,
    MemoryMcpWriteMode,
)


@dataclass
class Latencies:
    values_ms: list[float] = field(default_factory=list)

    def add(self, elapsed_ms: float) -> None:
        self.values_ms.append(elapsed_ms)

    def summary(self) -> dict[str, float]:
        if not self.values_ms:
            return {"count": 0, "p50_ms": 0.0, "p95_ms": 0.0, "max_ms": 0.0}
        ordered = sorted(self.values_ms)
        p95_index = min(len(ordered) - 1, int(round((len(ordered) - 1) * 0.95)))
        return {
            "count": float(len(ordered)),
            "p50_ms": round(float(statistics.median(ordered)), 2),
            "p95_ms": round(float(ordered[p95_index]), 2),
            "max_ms": round(float(max(ordered)), 2),
        }


async def run_benchmark(
    *,
    settings: MemoryMcpSettings,
    iterations: int,
    space_slug: str,
    profile_external_ref: str,
) -> dict[str, Any]:
    gateway = HttpMemoryGateway(
        base_url=settings.api_url,
        auth_token=settings.auth_token,
        timeout_seconds=settings.request_timeout_seconds,
    )
    lifecycle_settings = replace(
        settings,
        write_mode=MemoryMcpWriteMode.DIRECT,
        delete_mode=MemoryMcpDeleteMode.EXPLICIT,
        ingest_mode=MemoryMcpIngestMode.ALLOWED,
    )
    service = MemoryToolService(gateway=gateway, settings=lifecycle_settings)
    run_id = uuid.uuid4().hex[:10]
    latencies = {
        "remember": Latencies(),
        "proposal_suggest": Latencies(),
        "search_after_remember": Latencies(),
        "update": Latencies(),
        "search_after_update": Latencies(),
        "search_stale_after_update": Latencies(),
        "forget": Latencies(),
        "search_after_forget": Latencies(),
    }
    counters = {
        "remember_success": 0,
        "proposal_suggestion_success": 0,
        "retrieved_after_remember": 0,
        "update_success": 0,
        "retrieved_after_update": 0,
        "stale_hidden_after_update": 0,
        "forget_success": 0,
        "hidden_after_forget": 0,
    }

    for index in range(iterations):
        marker = f"MCP_BENCH_{run_id}_{index}"
        old_text = f"{marker}: Graph memory should use canonical facts before derived indexes."
        new_text = (
            f"{marker}: Graph memory should use updated canonical facts before derived indexes."
        )
        proposal_service = MemoryToolService(
            gateway=gateway,
            settings=replace(settings, write_mode=MemoryMcpWriteMode.SUGGEST),
        )
        proposal = await _timed(
            latencies["proposal_suggest"],
            proposal_service.propose_updates(
                candidates=[
                    {
                        "text": f"{marker}: Proposal path should create review suggestions.",
                        "kind": "note",
                        "operation": "remember",
                    }
                ],
                space_slug=space_slug,
                profile_external_ref=profile_external_ref,
                source_type="manual",
                source_id=f"bench-proposal-{run_id}-{index}",
            ),
        )
        if proposal.get("ok") and proposal.get("data", {}).get("accepted_suggestions"):
            counters["proposal_suggestion_success"] += 1

        remembered = await _timed(
            latencies["remember"],
            service.remember_fact(
                text=old_text,
                kind="architecture_decision",
                space_slug=space_slug,
                profile_external_ref=profile_external_ref,
                source_type="manual",
                source_id=f"bench-{run_id}-{index}",
                classification="internal",
            ),
        )
        if not remembered.get("ok"):
            continue
        counters["remember_success"] += 1
        fact = remembered["data"]
        fact_id = fact["id"]

        search_old = await _timed(
            latencies["search_after_remember"],
            service.search(
                query=marker,
                space_slug=space_slug,
                profile_external_ref=profile_external_ref,
                max_facts=5,
                max_chunks=0,
            ),
        )
        if _contains(search_old, old_text):
            counters["retrieved_after_remember"] += 1

        updated = await _timed(
            latencies["update"],
            service.update_fact(
                fact_id=fact_id,
                expected_version=fact["version"],
                text=new_text,
                reason="benchmark update lifecycle check",
                source_type="manual",
                source_id=f"bench-update-{run_id}-{index}",
            ),
        )
        if not updated.get("ok"):
            continue
        counters["update_success"] += 1

        search_new = await _timed(
            latencies["search_after_update"],
            service.search(
                query=marker,
                space_slug=space_slug,
                profile_external_ref=profile_external_ref,
                max_facts=5,
                max_chunks=0,
            ),
        )
        if _contains(search_new, new_text):
            counters["retrieved_after_update"] += 1

        search_stale = await _timed(
            latencies["search_stale_after_update"],
            service.search(
                query=old_text,
                space_slug=space_slug,
                profile_external_ref=profile_external_ref,
                max_facts=5,
                max_chunks=0,
            ),
        )
        if not _contains(search_stale, old_text):
            counters["stale_hidden_after_update"] += 1

        forgotten = await _timed(latencies["forget"], service.forget_fact(fact_id=fact_id))
        if not forgotten.get("ok"):
            continue
        counters["forget_success"] += 1

        search_deleted = await _timed(
            latencies["search_after_forget"],
            service.search(
                query=marker,
                space_slug=space_slug,
                profile_external_ref=profile_external_ref,
                max_facts=5,
                max_chunks=0,
            ),
        )
        if not _contains(search_deleted, new_text):
            counters["hidden_after_forget"] += 1

    return {
        "run_id": run_id,
        "iterations": iterations,
        "scope": {
            "space_slug": space_slug,
            "profile_external_ref": profile_external_ref,
        },
        "rates": _rates(counters, iterations),
        "counters": counters,
        "latency": {name: stats.summary() for name, stats in latencies.items()},
    }


async def _timed(latencies: Latencies, awaitable) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        return await awaitable
    finally:
        latencies.add((time.perf_counter() - started) * 1000)


def _contains(payload: dict[str, Any], text: str) -> bool:
    return text in json.dumps(payload, ensure_ascii=False)


def _rates(counters: dict[str, int], iterations: int) -> dict[str, float]:
    denominator = max(iterations, 1)
    return {f"{key}_rate": round(value / denominator, 4) for key, value in counters.items()}


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark Memo Stack MCP adapter CRUD/retrieval.")
    parser.add_argument("--iterations", type=int, default=10)
    parser.add_argument("--api-url", default=None)
    parser.add_argument("--space-slug", default=None)
    parser.add_argument("--profile-ref", default=None)
    args = parser.parse_args()

    base = load_settings()
    settings = MemoryMcpSettings(
        api_url=args.api_url or base.api_url,
        auth_token=base.auth_token,
        default_space_slug=args.space_slug or base.default_space_slug,
        default_profile_external_ref=args.profile_ref or base.default_profile_external_ref,
        default_thread_external_ref=base.default_thread_external_ref,
        agent_name=base.agent_name,
        source_type=base.source_type,
        request_timeout_seconds=base.request_timeout_seconds,
        max_tool_text_chars=base.max_tool_text_chars,
        min_token_budget=base.min_token_budget,
        max_token_budget=base.max_token_budget,
        max_search_items=base.max_search_items,
        allow_writes=base.allow_writes,
        allow_deletes=base.allow_deletes,
        write_mode=base.write_mode,
        delete_mode=base.delete_mode,
        ingest_mode=base.ingest_mode,
        small_doc_max_chars=base.small_doc_max_chars,
        transport=base.transport,
    )
    result = asyncio.run(
        run_benchmark(
            settings=settings,
            iterations=args.iterations,
            space_slug=settings.default_space_slug,
            profile_external_ref=settings.default_profile_external_ref,
        )
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

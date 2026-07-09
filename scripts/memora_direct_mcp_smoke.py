"""Run a disposable direct MCP smoke against agentic-box/memora.

The script uses a temporary SQLite database and does not write Memora data to the
user's default home directory. It is meant for competitor evidence, not as a
runtime dependency of Infinity Context.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from infinity_context_core.reporting import with_report_provenance
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

MEMORA_UVX_ARGS = (
    "--from",
    "git+https://github.com/agentic-box/memora.git",
    "memora-server",
    "--no-graph",
)

REALISTIC_SCENARIOS: tuple[dict[str, str], ...] = (
    {
        "id": "architecture_decision_remember",
        "goal": "Remember a durable coding architecture decision with project metadata.",
    },
    {
        "id": "architecture_decision_update",
        "goal": "Update the decision and ensure retrieval prefers the current version.",
    },
    {
        "id": "cross_project_scope_filter",
        "goal": "Keep another project's API fact out of Atlas-scoped recall.",
    },
    {
        "id": "adr_document_fragment_recall",
        "goal": "Store an ADR-style markdown document and recall risk/plan fragments.",
    },
    {
        "id": "source_backed_digest",
        "goal": "Build a digest that mentions current architecture and source evidence.",
    },
    {
        "id": "explicit_delete",
        "goal": "Delete the mutable fact and ensure it is not returned by search.",
    },
    {
        "id": "portable_export",
        "goal": "Export memory state for backup or sync workflows.",
    },
)


def _extract_jsonish(result: Any) -> Any:
    texts: list[str] = []
    for item in getattr(result, "content", []) or []:
        text = getattr(item, "text", None)
        if text is not None:
            texts.append(text)
    joined = "\n".join(texts)
    try:
        return json.loads(joined)
    except json.JSONDecodeError:
        return joined


def _contains(value: Any, needle: str) -> bool:
    return needle.lower() in json.dumps(value, ensure_ascii=False).lower()


def _first_int_id(value: Any) -> int:
    if isinstance(value, dict):
        for key in ("id", "memory_id", "root_id"):
            if isinstance(value.get(key), int):
                return value[key]
        memory = value.get("memory")
        if isinstance(memory, dict) and isinstance(memory.get("id"), int):
            return memory["id"]
        for nested in value.values():
            try:
                return _first_int_id(nested)
            except ValueError:
                continue
    if isinstance(value, list):
        for item in value:
            try:
                return _first_int_id(item)
            except ValueError:
                continue
    raise ValueError("Memora response did not include a memory id")


async def run_memora_direct_mcp_smoke() -> dict[str, Any]:
    report: dict[str, Any] = {
        "system": "agentic-box/memora",
        "mode": "direct_mcp_stdio",
        "scenario_set": "prod_realistic_coding_agent_memory_v1",
        "scenarios": list(REALISTIC_SCENARIOS),
        "embedding_model": "tfidf",
        "llm_enabled": False,
        "checks": {},
    }
    with tempfile.TemporaryDirectory(prefix="memora-direct-bench-") as tmp_dir:
        env = os.environ.copy()
        env.update(
            {
                "MEMORA_DB_PATH": str(Path(tmp_dir) / "memora.db"),
                "MEMORA_EMBEDDING_MODEL": "tfidf",
                "MEMORA_LLM_ENABLED": "false",
                "MEMORA_ALLOW_ANY_TAG": "1",
            }
        )
        params = StdioServerParameters(command="uvx", args=list(MEMORA_UVX_ARGS), env=env)
        async with (
            stdio_client(params) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            tools = (await session.list_tools()).tools
            tool_names = {tool.name for tool in tools}
            report["tool_count"] = len(tool_names)
            report["checks"]["has_core_tools"] = all(
                tool in tool_names
                for tool in (
                    "memory_create",
                    "memory_update",
                    "memory_delete",
                    "memory_hybrid_search",
                    "memory_digest",
                    "memory_store_document",
                )
            )

            created = _extract_jsonish(
                await session.call_tool(
                    "memory_create",
                    {
                        "content": (
                            "Project Atlas uses FastAPI for the memory HTTP API. "
                            "This is a durable architecture decision."
                        ),
                        "tags": ["project/atlas", "kind/architecture_decision"],
                        "metadata": {
                            "project": "atlas",
                            "kind": "architecture_decision",
                        },
                        "suggest_similar": False,
                    },
                )
            )
            fact_id = _first_int_id(created)

            search = _extract_jsonish(
                await session.call_tool(
                    "memory_hybrid_search",
                    {
                        "query": "Atlas memory API framework",
                        "top_k": 5,
                        "content_mode": "full",
                        "metadata_filters": {"project": "atlas"},
                    },
                )
            )
            report["checks"]["create_and_filtered_search"] = _contains(
                search,
                "FastAPI",
            ) and _contains(search, "Atlas")

            await session.call_tool(
                "memory_update",
                {
                    "memory_id": fact_id,
                    "content": (
                        "Project Atlas uses FastAPI for the memory HTTP API, "
                        "but background jobs are isolated in a worker process. "
                        "This supersedes the earlier API-only architecture note."
                    ),
                    "tags": ["project/atlas", "kind/architecture_decision"],
                    "metadata": {
                        "project": "atlas",
                        "kind": "architecture_decision",
                        "version": "2",
                    },
                },
            )
            search_new = _extract_jsonish(
                await session.call_tool(
                    "memory_hybrid_search",
                    {
                        "query": "Atlas worker process background jobs",
                        "top_k": 5,
                        "content_mode": "full",
                        "metadata_filters": {"project": "atlas"},
                    },
                )
            )
            report["checks"]["update_searches_new_fact"] = _contains(
                search_new,
                "worker process",
            ) and _contains(search_new, "supersedes")

            search_old = _extract_jsonish(
                await session.call_tool(
                    "memory_hybrid_search",
                    {
                        "query": "API-only architecture note",
                        "top_k": 5,
                        "content_mode": "full",
                        "metadata_filters": {"project": "atlas"},
                    },
                )
            )
            report["checks"]["old_text_not_primary_after_update"] = not _contains(
                search_old,
                "durable architecture decision",
            )

            await session.call_tool(
                "memory_create",
                {
                    "content": "Project Boreal uses Express for its API.",
                    "tags": ["project/boreal"],
                    "metadata": {"project": "boreal"},
                    "suggest_similar": False,
                },
            )
            scoped_search = _extract_jsonish(
                await session.call_tool(
                    "memory_hybrid_search",
                    {
                        "query": "API framework",
                        "top_k": 10,
                        "content_mode": "full",
                        "metadata_filters": {"project": "atlas"},
                    },
                )
            )
            report["checks"]["metadata_scope_filter_excludes_other_project"] = not _contains(
                scoped_search,
                "Boreal",
            )

            document_content = (
                "# Atlas ADR\n\n"
                "## Decision\n"
                "Use FastAPI for HTTP and isolate background jobs in a worker process.\n\n"
                "## Risks\n"
                "- Do not run Graphiti projections in the request path.\n"
                "- Keep Qdrant document recall separate from temporal facts.\n\n"
                "## Plan\n"
                "1. Keep canonical facts in Postgres.\n"
                "2. Project to graph/vector engines asynchronously.\n"
            )
            document = _extract_jsonish(
                await session.call_tool(
                    "memory_store_document",
                    {
                        "document_key": "atlas/adr-memory-runtime",
                        "content": document_content,
                        "tags": ["project/atlas", "kind/document"],
                        "metadata": {"project": "atlas"},
                    },
                )
            )
            if isinstance(document, dict):
                report["document_fragment_count"] = document.get("fragment_count")

            document_search = _extract_jsonish(
                await session.call_tool(
                    "memory_hybrid_search",
                    {
                        "query": "Graphiti projections request path Qdrant temporal facts",
                        "top_k": 10,
                        "content_mode": "full",
                        "metadata_filters": {"project": "atlas"},
                    },
                )
            )
            report["checks"]["document_fragment_recall"] = _contains(
                document_search,
                "Graphiti projections",
            ) and _contains(document_search, "Qdrant")

            digest = _extract_jsonish(
                await session.call_tool(
                    "memory_digest",
                    {
                        "topic": "Atlas memory architecture",
                        "k": 10,
                        "tags_any": ["project/atlas"],
                        "debug": True,
                    },
                )
            )
            report["checks"]["digest_returns_source_backed_context"] = any(
                _contains(digest, needle)
                for needle in ("source", "source_ids", "source_memory_ids")
            )
            report["checks"]["digest_mentions_updated_architecture"] = _contains(
                digest,
                "worker process",
            ) and _contains(digest, "FastAPI")

            await session.call_tool("memory_delete", {"memory_id": fact_id})
            deleted_search = _extract_jsonish(
                await session.call_tool(
                    "memory_hybrid_search",
                    {
                        "query": "worker process background jobs",
                        "top_k": 5,
                        "content_mode": "full",
                        "metadata_filters": {"project": "atlas"},
                    },
                )
            )
            report["checks"]["delete_removes_fact_from_search"] = not _contains(
                deleted_search,
                "worker process background jobs",
            )

            exported = _extract_jsonish(await session.call_tool("memory_export", {}))
            report["checks"]["export_available"] = isinstance(exported, list) or _contains(
                exported,
                "content",
            )

    report["ok"] = all(report["checks"].values())
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report-out",
        type=Path,
        default=None,
        help="Optional path where the sanitized JSON report should be written.",
    )
    args = parser.parse_args(argv)

    report = asyncio.run(run_memora_direct_mcp_smoke())
    report = with_report_provenance(
        report,
        generated_by="scripts/memora_direct_mcp_smoke.py",
        suite="memora-direct-mcp-smoke",
        run_id=str(report.get("scenario_set") or "unknown"),
        project="infinity-context-competitor-evidence",
        cwd=Path(__file__).resolve().parents[1],
    )
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.report_out is not None:
        args.report_out.parent.mkdir(parents=True, exist_ok=True)
        args.report_out.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

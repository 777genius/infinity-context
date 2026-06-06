"""Run a live MCP client smoke against a running Memo Stack server."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class McpSmokeFailure(RuntimeError):
    """Raised when the MCP adapter works at transport level but fails behavior checks."""


async def run_smoke() -> dict[str, Any]:
    marker = f"MCP_AGENT_SMOKE_{time.time_ns()}"
    old_fact = f"{marker}: MCP agents should search before writing memory."
    new_fact = f"{marker}: MCP agents should update existing memory instead of duplicating it."
    env = os.environ.copy()
    env.setdefault("MEMORY_MCP_API_URL", os.getenv("MEMORY_SMOKE_API_URL", "http://127.0.0.1:7788"))
    env.setdefault(
        "MEMORY_MCP_AUTH_TOKEN",
        os.getenv("MEMORY_SMOKE_AUTH_TOKEN", os.getenv("MEMORY_SERVICE_TOKEN", "local-dev-token")),
    )
    env.setdefault("MEMORY_MCP_DEFAULT_SPACE_SLUG", "mcp-live-smoke")
    env.setdefault("MEMORY_MCP_DEFAULT_PROFILE_EXTERNAL_REF", "default")
    env.setdefault("MEMORY_MCP_AGENT_NAME", "mcp-live-smoke-agent")
    env.setdefault("MEMORY_MCP_TRANSPORT", "stdio")

    params = StdioServerParameters(command=sys.executable, args=["-m", "memo_stack_mcp"], env=env)
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()
        tool_names = {tool.name for tool in tools.tools}
        required_tools = {
            "memory_status",
            "memory_search",
            "memory_remember_fact",
            "memory_update_fact",
            "memory_forget_fact",
            "memory_ingest_document",
            "memory_suggest_fact",
        }
        if not required_tools.issubset(tool_names):
            raise McpSmokeFailure(f"Missing MCP tools: {sorted(required_tools - tool_names)}")

        status = await _call(session, "memory_status", {})
        _assert_ok(status, "status")

        empty_search = await _call(session, "memory_search", {"query": marker, "max_chunks": 0})
        _assert_ok(empty_search, "empty_search")
        if old_fact in _dump(empty_search):
            raise McpSmokeFailure("Fresh MCP search unexpectedly found the new marker")

        remembered = await _call(
            session,
            "memory_remember_fact",
            {
                "text": old_fact,
                "kind": "constraint",
                "source_type": "manual",
                "source_id": f"{marker}:remember",
                "idempotency_key": f"{marker}:remember",
            },
        )
        _assert_ok(remembered, "remember")
        fact = remembered["data"]

        search_old = await _call(session, "memory_search", {"query": marker, "max_chunks": 0})
        _assert_ok(search_old, "search_old")
        if old_fact not in _dump(search_old):
            raise McpSmokeFailure("Remembered fact was not found through MCP search")

        updated = await _call(
            session,
            "memory_update_fact",
            {
                "fact_id": fact["id"],
                "expected_version": fact["version"],
                "text": new_fact,
                "reason": "mcp live smoke update",
                "source_type": "manual",
                "source_id": f"{marker}:update",
            },
        )
        _assert_ok(updated, "update")
        if updated["data"]["version"] != 2:
            raise McpSmokeFailure("MCP update did not increment fact version")

        search_new = await _call(session, "memory_search", {"query": marker, "max_chunks": 0})
        _assert_ok(search_new, "search_new")
        dumped_new = _dump(search_new)
        if new_fact not in dumped_new or old_fact in dumped_new:
            raise McpSmokeFailure("MCP search did not reflect the updated fact lifecycle")

        forgotten = await _call(session, "memory_forget_fact", {"fact_id": fact["id"]})
        _assert_ok(forgotten, "forget")
        if forgotten["data"]["status"] != "deleted":
            raise McpSmokeFailure("MCP forget did not mark fact deleted")

        search_deleted = await _call(session, "memory_search", {"query": marker, "max_chunks": 0})
        _assert_ok(search_deleted, "search_deleted")
        if new_fact in _dump(search_deleted):
            raise McpSmokeFailure("Deleted fact leaked back through MCP search")

        return {
            "ok": True,
            "api_url": env["MEMORY_MCP_API_URL"],
            "space_slug": env["MEMORY_MCP_DEFAULT_SPACE_SLUG"],
            "profile_external_ref": env["MEMORY_MCP_DEFAULT_PROFILE_EXTERNAL_REF"],
            "fact_id": fact["id"],
            "tool_count": len(tool_names),
        }


async def _call(
    session: ClientSession,
    name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    result = await session.call_tool(name, arguments)
    if result.isError:
        raise McpSmokeFailure(f"{name} returned MCP error: {result}")
    if result.structuredContent is not None:
        return result.structuredContent
    return json.loads(result.content[0].text)


def _assert_ok(payload: dict[str, Any], operation: str) -> None:
    if payload.get("ok") is not True:
        raise McpSmokeFailure(f"{operation} failed: {payload}")


def _dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def main() -> int:
    try:
        result = asyncio.run(run_smoke())
    except Exception as exc:
        print(
            json.dumps(
                {"ok": False, "error": exc.__class__.__name__, "message": str(exc)},
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Run a clean full-provider Memo Stack smoke test.

The script starts a fresh Docker Compose project with isolated Postgres,
Qdrant and Neo4j volumes, runs migrations and seed data, starts the local
FastAPI server, then verifies canonical facts, Graphiti projection, Qdrant
chunk recall, update and delete behavior. By default it also starts a real
stdio MCP client against the same isolated server and verifies the MCP path
over Graphiti, Qdrant and OpenAI embeddings.

Secrets are read from the process environment only. Nothing is written to .env.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, TextIO

import httpx
from memo_stack_adapters.provider_errors import classify_provider_exception
from neo4j import GraphDatabase

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
FULL_PROVIDER_CANARY_SUITE = "memo-stack-full-provider-canary"
SENSITIVE_ENV_KEYS = (
    "MEMORY_AGENT_BENCH_OPENAI_API_KEY",
    "MEMORY_MCP_AUTH_TOKEN",
    "MEMORY_SERVICE_TOKEN",
    "MEMORY_OPENAI_API_KEY",
    "OPENAI_API_KEY",
    "MEMORY_CLEAN_SMOKE_TOKEN",
    "MEMORY_DATABASE_URL",
    "MEMORY_GRAPHITI_NEO4J_PASSWORD",
)
SENSITIVE_KEY_SUFFIXES = (
    "_TOKEN",
    "_KEY",
    "_SECRET",
    "_PASSWORD",
    "_CREDENTIAL",
    "_DATABASE_URL",
    "_DB_URL",
    "_DSN",
)
SENSITIVE_HEADER_KEYS = {
    "authorization",
    "idempotency-key",
}
SENSITIVE_KEY_NAMES = {
    "api_key",
    "apikey",
    "auth",
    "auth_token",
    "authorization",
    "credential",
    "credentials",
    "connection_string",
    "database_url",
    "db_url",
    "dsn",
    "idempotency_key",
    "idempotency-key",
    "passwd",
    "password",
    "secret",
    "token",
}
SAFE_REPORT_KEY_NAMES = {
    "mcp_text_fallback_does_not_leak_token",
    "secret_redaction",
}
SENSITIVE_TEXT_PATTERNS = (
    re.compile(r"Authorization\s*:\s*Bearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{12,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{12,}\b"),
    re.compile(r"\bbench-secret-[A-Za-z0-9_.:-]+\b", re.IGNORECASE),
    re.compile(
        r"(?i)\b(api[_-]?key|secret|token|password|passwd|credential)\s*[:=]\s*['\"]?"
        r"[A-Za-z0-9_./+=-]{8,}"
    ),
)
SAFE_MCP_INHERITED_ENV_KEYS = (
    "HOME",
    "LANG",
    "LC_ALL",
    "PATH",
    "PYTHONPATH",
    "REQUESTS_CA_BUNDLE",
    "SSL_CERT_FILE",
    "VIRTUAL_ENV",
)
DEFAULT_MCP_HTTP_TIMEOUT_SECONDS = "90"
DEFAULT_MCP_TOOL_TIMEOUT_SECONDS = 180.0


class CleanSmokeFailure(RuntimeError):
    """Raised when the full-provider smoke violates an expected invariant."""


class ServerHandle:
    def __init__(self, *, process: subprocess.Popen[str], output: TextIO) -> None:
        self.process = process
        self.output = output


def main() -> int:
    started = time.perf_counter()
    run_id = str(time.time_ns())
    project_name = os.getenv("MEMORY_CLEAN_SMOKE_PROJECT", f"memo-stack-clean-{run_id[-8:]}")
    token = os.getenv("MEMORY_CLEAN_SMOKE_TOKEN", "clean-smoke-token")
    os.environ.setdefault("MEMORY_CLEAN_SMOKE_TOKEN", token)
    ports = _ports()
    compose_env = _compose_env(ports)
    server_env: dict[str, str] | None = None
    keep_stack = _bool(os.getenv("MEMORY_CLEAN_SMOKE_KEEP_STACK", "false"))
    skip_mcp = _bool(os.getenv("MEMORY_CLEAN_SMOKE_SKIP_MCP", "false"))
    run_agent_bench = _bool(os.getenv("MEMORY_CLEAN_SMOKE_AGENT_BENCH", "false"))
    run_prod_load = _bool(os.getenv("MEMORY_CLEAN_SMOKE_PROD_LOAD", "false"))
    server: ServerHandle | None = None

    try:
        if run_prod_load and skip_mcp:
            raise CleanSmokeFailure("Prod load canary requires MCP checks")
        server_env = _server_env(ports=ports, token=token, run_id=run_id)
        if _bool(os.getenv("MEMORY_CLEAN_SMOKE_OPENAI_PREFLIGHT", "true")):
            asyncio.run(_run_openai_provider_preflight(server_env))
        _compose(project_name, compose_env, "down", "-v", "--remove-orphans", check=False)
        _compose(
            project_name,
            compose_env,
            "--profile",
            "full",
            "up",
            "-d",
            "memo_stack_postgres",
            "memo_stack_qdrant",
            "memo_stack_neo4j",
        )
        _wait_for_postgres(project_name, compose_env)
        _wait_for_http(f"http://127.0.0.1:{ports['qdrant']}/")
        _wait_for_neo4j(ports["neo4j_bolt"])

        _run_python(server_env, "-m", "memo_stack_server.db", "upgrade")
        _run_python(server_env, "-m", "memo_stack_server.admin", "seed-defaults")

        server = _start_server(server_env)
        base_url = f"http://127.0.0.1:{ports['server']}"
        _wait_for_http(f"{base_url}/v1/health", token=token)

        def restart_server_for_canary() -> None:
            nonlocal server
            if server is not None:
                _stop_server(server)
                server = None
            server = _start_server(server_env)
            _wait_for_http(f"{base_url}/v1/health", token=token)

        def restart_providers_for_canary() -> None:
            _compose(project_name, compose_env, "restart", "memo_stack_qdrant", "memo_stack_neo4j")
            _wait_for_http(f"http://127.0.0.1:{ports['qdrant']}/")
            _wait_for_neo4j(ports["neo4j_bolt"])

        def stop_providers_for_canary() -> None:
            _compose(project_name, compose_env, "stop", "memo_stack_qdrant", "memo_stack_neo4j")

        result = _run_lifecycle(base_url=base_url, token=token, env=server_env, run_id=run_id)
        if skip_mcp:
            result["mcp"] = {"skipped": True, "reason": "MEMORY_CLEAN_SMOKE_SKIP_MCP=true"}
        else:
            mcp_result = asyncio.run(
                _run_mcp_lifecycle(
                    base_url=base_url,
                    token=token,
                    env=server_env,
                    run_id=run_id,
                )
            )
            result["mcp"] = mcp_result
            result["checks"].update(mcp_result["checks"])
        if run_prod_load:
            prod_load_result = asyncio.run(
                _run_prod_load_canary(
                    base_url=base_url,
                    token=token,
                    env=server_env,
                    run_id=run_id,
                    restart_server=restart_server_for_canary,
                    restart_providers=restart_providers_for_canary,
                    stop_providers=stop_providers_for_canary,
                )
            )
            result["prod_load"] = prod_load_result
            result["checks"].update(prod_load_result["checks"])
        if run_agent_bench:
            agent_result = asyncio.run(
                _run_agent_behavior_benchmark(
                    base_url=base_url,
                    token=token,
                    env=server_env,
                    run_id=run_id,
                )
            )
            result["agent_behavior"] = agent_result
            result["checks"]["agent_behavior_ok"] = agent_result.get("ok") is True
            if agent_result.get("ok") is not True:
                raise CleanSmokeFailure(
                    "Agent behavior benchmark failed: "
                    + _redact_text(
                        json.dumps(
                            _agent_behavior_failure_summary(agent_result),
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        env=server_env,
                    )
                )
        result["suite"] = FULL_PROVIDER_CANARY_SUITE
        result["project"] = project_name
        result["elapsed_seconds"] = round(time.perf_counter() - started, 3)
        print(
            json.dumps(
                _redact_payload(result, env=server_env),
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    except Exception as exc:
        details: dict[str, Any] = {
            "suite": FULL_PROVIDER_CANARY_SUITE,
            "ok": False,
            "error": exc.__class__.__name__,
            "message": _redact_text(str(exc), env=server_env),
            "project": project_name,
        }
        if server is not None:
            details["server_output_tail"] = _redact_text(_stop_server(server), env=server_env)
            server = None
        print(
            json.dumps(
                _redact_payload(details, env=server_env),
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    finally:
        if server is not None:
            _stop_server(server)
        if not keep_stack:
            _compose(project_name, compose_env, "down", "-v", "--remove-orphans", check=False)


def _ports() -> dict[str, int]:
    return {
        "postgres": _free_port(),
        "qdrant": _free_port(),
        "neo4j_http": _free_port(),
        "neo4j_bolt": _free_port(),
        "server": _free_port(),
    }


def _compose_env(ports: Mapping[str, int]) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "MEMORY_POSTGRES_PORT": str(ports["postgres"]),
            "MEMORY_QDRANT_PORT": str(ports["qdrant"]),
            "MEMORY_NEO4J_HTTP_PORT": str(ports["neo4j_http"]),
            "MEMORY_NEO4J_BOLT_PORT": str(ports["neo4j_bolt"]),
            "MEMORY_SERVER_PORT": str(ports["server"]),
        }
    )
    return env


def _server_env(*, ports: Mapping[str, int], token: str, run_id: str) -> dict[str, str]:
    openai_key = os.getenv("MEMORY_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not openai_key:
        raise CleanSmokeFailure("Set a Memo Stack OpenAI API key in the environment")

    env = os.environ.copy()
    env.update(
        {
            "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY") or openai_key,
            "MEMORY_OPENAI_API_KEY": openai_key,
            "MEMORY_DEPLOY_PROFILE": "local",
            "MEMORY_DATABASE_URL": (
                f"postgresql+asyncpg://memo_stack:memo_stack@127.0.0.1:{ports['postgres']}/memo_stack"
            ),
            "MEMORY_AUTO_CREATE_SCHEMA": "true",
            "MEMORY_HOST": "127.0.0.1",
            "MEMORY_PORT": str(ports["server"]),
            "MEMORY_SERVICE_TOKEN": token,
            "MEMORY_POLICY_MODE": "active_context",
            "MEMORY_QDRANT_ENABLED": "true",
            "MEMORY_QDRANT_URL": f"http://127.0.0.1:{ports['qdrant']}",
            "MEMORY_QDRANT_COLLECTION": f"memory_clean_smoke_{run_id}",
            "MEMORY_EMBEDDINGS_ENABLED": "true",
            "MEMORY_EMBEDDINGS_PROVIDER": "openai",
            "MEMORY_EMBEDDINGS_MODEL": os.getenv(
                "MEMORY_EMBEDDINGS_MODEL",
                "text-embedding-3-small",
            ),
            "MEMORY_EMBEDDINGS_DIMENSIONS": os.getenv("MEMORY_EMBEDDINGS_DIMENSIONS", "1536"),
            "MEMORY_GRAPHITI_ENABLED": "true",
            "MEMORY_GRAPHITI_NEO4J_URI": f"bolt://127.0.0.1:{ports['neo4j_bolt']}",
            "MEMORY_GRAPHITI_NEO4J_USER": "neo4j",
            "MEMORY_GRAPHITI_NEO4J_PASSWORD": "memostackgraph",
            "MEMORY_GRAPHITI_BUILD_INDICES": "true",
            "MEMORY_PROVIDER_CIRCUIT_FAILURE_THRESHOLD": "2",
            "MEMORY_PROVIDER_CIRCUIT_RESET_AFTER_SECONDS": "30",
            "MEMORY_LEGACY_CLIENT_ENABLED": "false",
        }
    )
    return env


async def _run_openai_provider_preflight(env: Mapping[str, str]) -> None:
    try:
        from openai import AsyncOpenAI
    except Exception as exc:
        raise CleanSmokeFailure("OpenAI provider preflight failed: openai.sdk_missing") from exc

    client = AsyncOpenAI(api_key=env["MEMORY_OPENAI_API_KEY"])
    try:
        await client.embeddings.create(
            model=env["MEMORY_EMBEDDINGS_MODEL"],
            input=["memo stack provider preflight"],
            dimensions=int(env["MEMORY_EMBEDDINGS_DIMENSIONS"]),
        )
    except Exception as exc:
        code, _retryable = classify_provider_exception(
            exc,
            prefix="openai",
            default_code="openai.provider_error",
        )
        raise CleanSmokeFailure(f"OpenAI provider preflight failed: {code}") from exc
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            result = close()
            if inspect.isawaitable(result):
                await result


def _run_lifecycle(
    *,
    base_url: str,
    token: str,
    env: Mapping[str, str],
    run_id: str,
) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {token}"}
    marker = f"CLEAN_FULL_{run_id}"
    space_slug = "clean-full-smoke"
    profile_ref = "default"
    old_text = f"{marker}: Graphiti connects canonical facts to clean architecture memory."
    new_text = f"{marker}: Graphiti and Qdrant should recall updated memory."
    initial_graph_query = "Graphiti connects canonical facts to clean architecture memory"
    updated_graph_query = "Graphiti Qdrant recall updated memory"
    doc_text = (
        f"{marker}: Qdrant vector recall should retrieve this document chunk. "
        "The architecture keeps Postgres canonical and providers derived."
    )

    fact = _request(
        base_url,
        headers,
        "POST",
        "/v1/facts",
        expected=201,
        json={
            "space_slug": space_slug,
            "profile_external_ref": profile_ref,
            "text": old_text,
            "kind": "architecture_decision",
            "classification": "internal",
            "source_refs": [{"source_type": "clean_smoke", "source_id": f"{marker}:fact"}],
        },
    )
    _worker_once(env)
    initial_context = _context(base_url, headers, space_slug, profile_ref, initial_graph_query)
    initial_graph = _graph_episode(env, fact["id"])

    updated = _request(
        base_url,
        headers,
        "PATCH",
        f"/v1/facts/{fact['id']}",
        expected=200,
        json={
            "expected_version": fact["version"],
            "text": new_text,
            "reason": "clean full smoke update",
            "source_refs": [{"source_type": "clean_smoke", "source_id": f"{marker}:update"}],
        },
    )
    _worker_once(env)
    updated_context = _context(base_url, headers, space_slug, profile_ref, updated_graph_query)
    updated_graph = _graph_episode(env, fact["id"])

    document = _request(
        base_url,
        headers,
        "POST",
        "/v1/documents",
        expected=201,
        json={
            "space_slug": space_slug,
            "profile_external_ref": profile_ref,
            "title": f"{marker} document",
            "text": doc_text,
            "source_type": "clean_smoke",
            "source_external_id": f"{marker}:document",
            "classification": "internal",
        },
    )
    _worker_once(env)
    doc_context = _context(
        base_url,
        headers,
        space_slug,
        profile_ref,
        "Qdrant vector recall Postgres canonical providers derived",
    )

    forgotten = _request(
        base_url,
        headers,
        "DELETE",
        f"/v1/facts/{fact['id']}",
        expected=200,
    )
    _worker_once(env)
    forgotten_context = _context(base_url, headers, space_slug, profile_ref, marker)
    forgotten_graph = _graph_episode(env, fact["id"])
    metrics = _request(base_url, headers, "GET", "/v1/diagnostics/metrics", expected=200)
    outbox = _request(base_url, headers, "GET", "/v1/diagnostics/outbox", expected=200)

    checks = {
        "initial_context_has_old_fact": old_text in initial_context["rendered_text"],
        "initial_graph_has_episode": initial_graph["count"] == 1,
        "initial_context_graph_hydrated": _context_diagnostic_int(
            initial_context,
            "graph_hydrated_count",
        )
        >= 1,
        "updated_context_has_new_fact": new_text in updated_context["rendered_text"],
        "updated_context_hides_old_fact": old_text not in updated_context["rendered_text"],
        "updated_graph_replaced_episode": updated_graph["count"] == 1
        and new_text in " ".join(updated_graph["contents"]),
        "updated_context_graph_hydrated": _context_diagnostic_int(
            updated_context,
            "graph_hydrated_count",
        )
        >= 1,
        "document_context_has_chunk": doc_text in doc_context["rendered_text"],
        "document_context_has_chunk_item": any(
            str(item.get("item_id", "")).startswith("chunk_") for item in doc_context["items"]
        ),
        "document_context_vector_hydrated": _context_diagnostic_int(
            doc_context,
            "vector_hydrated_count",
        )
        >= 1,
        "forgotten_fact_deleted": forgotten["status"] == "deleted",
        "forgotten_context_hides_new_fact": new_text not in forgotten_context["rendered_text"],
        "forgotten_graph_removed_episode": forgotten_graph["count"] == 0,
        "outbox_has_no_pending_or_dead": outbox["counts"].get("dead", 0) == 0
        and set(outbox["counts"]) <= {"done"},
        "providers_are_healthy": all(
            metrics["adapters"][name]["status"] == "ok"
            for name in ("qdrant", "graphiti", "embeddings")
        ),
        "context_provider_status_ok": doc_context["diagnostics"].get("vector_status") == "ok"
        and doc_context["diagnostics"].get("graph_status") == "ok",
    }
    if not all(checks.values()):
        raise CleanSmokeFailure(f"Clean full smoke checks failed: {checks}")

    return {
        "ok": True,
        "marker": marker,
        "fact_id": fact["id"],
        "updated_version": updated["version"],
        "document_id": document["id"],
        "checks": checks,
        "outbox_counts": outbox["counts"],
        "adapters": {
            name: metrics["adapters"][name]["status"]
            for name in ("qdrant", "graphiti", "embeddings", "cognee")
        },
        "context_diagnostics": doc_context["diagnostics"],
    }


async def _run_mcp_lifecycle(
    *,
    base_url: str,
    token: str,
    env: Mapping[str, str],
    run_id: str,
) -> dict[str, Any]:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    headers = {"Authorization": f"Bearer {token}"}
    marker = f"CLEAN_FULL_MCP_{run_id}"
    space_slug = "clean-full-smoke"
    profile_ref = "default"
    old_text = f"{marker}: MCP connects canonical facts to Graphiti provider projections."
    new_text = f"{marker}: MCP updates canonical facts and Graphiti recalls provider projections."
    old_graph_query = "MCP connects canonical facts Graphiti provider projections"
    updated_graph_query = "MCP updates canonical facts Graphiti provider projections"
    doc_text = (
        f"{marker}: MCP Qdrant vector recall should retrieve this document chunk. "
        "Real-stack canary proves Graphiti, Qdrant and embeddings are wired."
    )
    mcp_env = _mcp_process_env(
        base_url=base_url,
        token=token,
        space_slug=space_slug,
        profile_ref=profile_ref,
    )
    params = StdioServerParameters(command=PYTHON, args=["-m", "memo_stack_mcp"], env=mcp_env)

    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await _await_mcp(session.initialize(), "memo_stack_mcp.initialize", env=mcp_env)
        tools = await _await_mcp(session.list_tools(), "memo_stack_mcp.list_tools", env=mcp_env)
        tool_names = {tool.name for tool in tools.tools}
        required_tools = {
            "memory_status",
            "memory_search",
            "memory_remember_fact",
            "memory_update_fact",
            "memory_ingest_document",
            "memory_forget_fact",
        }
        if not required_tools.issubset(tool_names):
            raise CleanSmokeFailure(
                f"MCP clean full smoke missing tools: {sorted(required_tools - tool_names)}"
            )

        status_result = await _call_mcp_result(session, "memory_status", {}, env=mcp_env)
        _structured_mcp(status_result, "memory_status", env=mcp_env)
        remembered_result = await _call_mcp_result(
            session,
            "memory_remember_fact",
            {
                "text": old_text,
                "kind": "architecture_decision",
                "source_type": "manual",
                "source_id": f"{marker}:remember",
                "classification": "internal",
                "idempotency_key": f"{marker}:remember",
            },
            env=mcp_env,
        )
        remembered = _structured_mcp(remembered_result, "memory_remember_fact", env=mcp_env)
        fact = remembered["data"]
        fact_id = str(fact["id"])
        _worker_once(env)
        search_old_result = await _call_mcp_result(
            session,
            "memory_search",
            {"query": old_graph_query, "max_facts": 10, "max_chunks": 0},
            env=mcp_env,
        )
        search_old = _structured_mcp(search_old_result, "memory_search old", env=mcp_env)
        initial_graph = _graph_episode(env, fact_id)

        updated_result = await _call_mcp_result(
            session,
            "memory_update_fact",
            {
                "fact_id": fact_id,
                "expected_version": fact["version"],
                "text": new_text,
                "reason": "clean full MCP smoke update",
                "source_type": "manual",
                "source_id": f"{marker}:update",
            },
            env=mcp_env,
        )
        updated = _structured_mcp(updated_result, "memory_update_fact", env=mcp_env)
        _worker_once(env)
        search_new_result = await _call_mcp_result(
            session,
            "memory_search",
            {"query": updated_graph_query, "max_facts": 10, "max_chunks": 0},
            env=mcp_env,
        )
        search_new = _structured_mcp(search_new_result, "memory_search updated", env=mcp_env)
        updated_graph = _graph_episode(env, fact_id)

        ingested_result = await _call_mcp_result(
            session,
            "memory_ingest_document",
            {
                "title": f"{marker} MCP real-stack document",
                "text": doc_text,
                "source_type": "document",
                "source_external_id": f"{marker}:document",
                "classification": "internal",
                "idempotency_key": f"{marker}:document",
            },
            env=mcp_env,
        )
        ingested = _structured_mcp(ingested_result, "memory_ingest_document", env=mcp_env)
        _worker_once(env)
        search_doc_result = await _call_mcp_result(
            session,
            "memory_search",
            {
                "query": "MCP Qdrant vector recall Graphiti embeddings wired",
                "max_facts": 0,
                "max_chunks": 10,
            },
            env=mcp_env,
        )
        search_doc = _structured_mcp(search_doc_result, "memory_search document", env=mcp_env)

        forgotten_result = await _call_mcp_result(
            session,
            "memory_forget_fact",
            {"fact_id": fact_id},
            env=mcp_env,
        )
        forgotten = _structured_mcp(forgotten_result, "memory_forget_fact", env=mcp_env)
        _worker_once(env)
        search_deleted_result = await _call_mcp_result(
            session,
            "memory_search",
            {"query": updated_graph_query, "max_facts": 10, "max_chunks": 10},
            env=mcp_env,
        )
        search_deleted = _structured_mcp(
            search_deleted_result,
            "memory_search deleted",
            env=mcp_env,
        )
        forgotten_graph = _graph_episode(env, fact_id)
        final_status_result = await _call_mcp_result(session, "memory_status", {}, env=mcp_env)
        final_status = _structured_mcp(
            final_status_result,
            "memory_status final",
            env=mcp_env,
        )

    metrics = _request(base_url, headers, "GET", "/v1/diagnostics/metrics", expected=200)
    outbox = _request(base_url, headers, "GET", "/v1/diagnostics/outbox", expected=200)
    providers_ok = all(
        metrics["adapters"][name]["status"] == "ok" for name in ("qdrant", "graphiti", "embeddings")
    )
    status_providers_ok = _required_mcp_adapters_ready(
        final_status,
        ("qdrant", "graphiti", "embeddings"),
    )
    search_doc_dump = _dump(search_doc)
    search_new_dump = _dump(search_new)
    search_deleted_dump = _dump(search_deleted)
    checks = {
        "mcp_status_projection_ready": bool(final_status["data"]["readiness"].get("read_ready"))
        and _required_mcp_adapters_ready(final_status, ("qdrant", "graphiti", "embeddings")),
        "mcp_search_has_graphiti_fact_after_worker": old_text in _dump(search_old)
        and initial_graph["count"] == 1
        and _search_diagnostic_status(search_old, "graph_status") == "ok"
        and _search_diagnostic_int(search_old, "graph_hydrated_count") >= 1,
        "mcp_search_has_qdrant_document_chunk_after_worker": marker in search_doc_dump
        and _search_has_chunk_item(search_doc)
        and ingested["data"].get("chunks", 0) >= 1
        and _search_diagnostic_status(search_doc, "vector_status") == "ok"
        and _search_diagnostic_int(search_doc, "vector_hydrated_count") >= 1,
        "mcp_search_hides_old_fact_after_update": new_text in search_new_dump
        and old_text not in search_new_dump
        and updated["data"]["version"] == 2
        and updated_graph["count"] == 1
        and new_text in " ".join(updated_graph["contents"])
        and _search_diagnostic_status(search_new, "graph_status") == "ok"
        and _search_diagnostic_int(search_new, "graph_hydrated_count") >= 1,
        "mcp_search_hides_deleted_fact": new_text not in search_deleted_dump
        and forgotten["data"]["status"] == "deleted"
        and forgotten_graph["count"] == 0,
        "mcp_text_fallback_does_not_leak_token": _mcp_text_has_no_secrets(
            status_result,
            remembered_result,
            search_old_result,
            updated_result,
            search_new_result,
            ingested_result,
            search_doc_result,
            forgotten_result,
            search_deleted_result,
            final_status_result,
            env=mcp_env,
        ),
        "mcp_outbox_has_no_pending_or_dead": outbox["counts"].get("dead", 0) == 0
        and set(outbox["counts"]) <= {"done"},
        "mcp_provider_diagnostics_ok": providers_ok and status_providers_ok,
    }
    if not all(checks.values()):
        diagnostics = {
            "search_old": _safe_search_diagnostics(search_old),
            "search_new": _safe_search_diagnostics(search_new),
            "search_doc": _safe_search_diagnostics(search_doc),
            "search_deleted": _safe_search_diagnostics(search_deleted),
            "final_readiness": _safe_status_readiness(final_status),
            "final_adapters": _safe_status_adapters(final_status),
            "outbox_counts": outbox["counts"],
        }
        raise CleanSmokeFailure(
            f"MCP clean full smoke checks failed: {checks}; diagnostics={diagnostics}"
        )

    return {
        "ok": True,
        "marker": marker,
        "fact_id": fact_id,
        "document_chunks": ingested["data"].get("chunks"),
        "checks": checks,
        "outbox_counts": outbox["counts"],
        "adapters": {
            name: metrics["adapters"][name]["status"]
            for name in ("qdrant", "graphiti", "embeddings")
        },
    }


async def _run_prod_load_canary(
    *,
    base_url: str,
    token: str,
    env: Mapping[str, str],
    run_id: str,
    restart_server: Callable[[], None] | None = None,
    restart_providers: Callable[[], None] | None = None,
    stop_providers: Callable[[], None] | None = None,
) -> dict[str, Any]:
    from mcp import StdioServerParameters

    headers = {"Authorization": f"Bearer {token}"}
    settings = _prod_load_settings()
    marker = f"PROD_LOAD_{run_id}"
    space_slug = "prod-load-canary"
    profiles = tuple(f"project-{index}" for index in range(settings["profiles"]))
    alpha = profiles[0]
    beta = profiles[1]
    old_text = f"{marker}: PROD_ALPHA_CURRENT_DECISION uses provider-backed recall."
    new_text = f"{marker}: PROD_ALPHA_CURRENT_DECISION uses drained projection recall."
    beta_text = f"{marker}: PROD_BETA_ISOLATION_SENTINEL belongs only to beta."
    restricted_text = f"{marker}: PROD_RESTRICTED_PAYLOAD must stay hidden from context."
    duplicate_text = f"{marker}: PROD_DUPLICATE_RETRY should converge under concurrent writes."
    thread_current = "prod-thread-current"
    thread_neighbor = "prod-thread-neighbor"
    thread_current_text = f"{marker}: PROD_THREAD_CURRENT_SENTINEL belongs to current thread."
    thread_neighbor_text = f"{marker}: PROD_THREAD_NEIGHBOR_SENTINEL belongs to neighbor thread."
    large_doc_tail = f"{marker}: PROD_LARGE_DOC_TAIL_SENTINEL survives multi-chunk recall."
    outage_fact_text = f"{marker}: PROD_PROVIDER_OUTAGE_FACT recovers after retrying Graphiti."
    outage_doc_text = f"{marker}: PROD_PROVIDER_OUTAGE_DOC recovers after retrying Qdrant."

    fact_requests: list[dict[str, Any]] = []
    for profile in profiles:
        for index in range(settings["facts_per_profile"]):
            text = (
                f"{marker}: {profile} production load fact {index:02d} "
                "tracks durable coding-agent memory with scope isolation."
            )
            classification = "internal"
            label = f"fact:{profile}:{index}"
            if profile == alpha and index == 0:
                text = old_text
                label = "target_fact"
            elif profile == beta and index == 0:
                text = beta_text
                label = "beta_sentinel"
            elif profile == alpha and index == 1:
                text = restricted_text
                classification = "restricted"
                label = "restricted_fact"
            fact_requests.append(
                {
                    "label": label,
                    "path": "/v1/facts",
                    "json": {
                        "space_slug": space_slug,
                        "profile_external_ref": profile,
                        "text": text,
                        "kind": "architecture_decision",
                        "classification": classification,
                        "source_refs": [
                            {
                                "source_type": "prod_load",
                                "source_id": f"{marker}:{profile}:{index}",
                            }
                        ],
                    },
                    "idempotency_key": f"{marker}:{profile}:{index}",
                }
            )

    create_results = _parallel_post_json(
        base_url=base_url,
        token=token,
        requests=fact_requests,
        concurrency=settings["concurrency"],
    )
    duplicate_results = _parallel_post_json(
        base_url=base_url,
        token=token,
        requests=[
            {
                "label": f"duplicate:{index}",
                "path": "/v1/facts",
                "json": {
                    "space_slug": space_slug,
                    "profile_external_ref": alpha,
                    "text": duplicate_text,
                    "kind": "note",
                    "classification": "internal",
                    "source_refs": [
                        {
                            "source_type": "prod_load",
                            "source_id": f"{marker}:duplicate-retry",
                        }
                    ],
                },
                "idempotency_key": f"{marker}:duplicate-retry",
            }
            for index in range(settings["concurrency"] * 2)
        ],
        concurrency=settings["concurrency"],
    )
    target_fact = _single_result_data(create_results, "target_fact")
    duplicate_ids = _successful_result_ids(duplicate_results)
    _request(
        base_url,
        headers,
        "POST",
        "/v1/facts",
        expected=201,
        json={
            "space_slug": space_slug,
            "profile_external_ref": alpha,
            "thread_external_ref": thread_current,
            "text": thread_current_text,
            "kind": "note",
            "classification": "internal",
            "source_refs": [{"source_type": "prod_load", "source_id": f"{marker}:thread-current"}],
        },
        extra_headers={"Idempotency-Key": f"{marker}:thread-current"},
    )
    _request(
        base_url,
        headers,
        "POST",
        "/v1/facts",
        expected=201,
        json={
            "space_slug": space_slug,
            "profile_external_ref": alpha,
            "thread_external_ref": thread_neighbor,
            "text": thread_neighbor_text,
            "kind": "note",
            "classification": "internal",
            "source_refs": [{"source_type": "prod_load", "source_id": f"{marker}:thread-neighbor"}],
        },
        extra_headers={"Idempotency-Key": f"{marker}:thread-neighbor"},
    )
    chaos = _run_prod_chaos_flood(
        base_url=base_url,
        token=token,
        marker=marker,
        requests=settings["chaos_requests"],
    )

    documents: list[dict[str, Any]] = []
    doc_texts: list[str] = []
    for index in range(settings["documents"]):
        doc_text = (
            f"{marker}: PROD_DOC_SENTINEL_{index} Qdrant vector recall should find "
            "production-like project notes after provider worker drain. "
            f"Section {index} repeats durable architecture constraints and source citations. "
            "The memo stack must treat retrieved document text as evidence only."
        )
        doc_texts.append(doc_text)
        documents.append(
            _request(
                base_url,
                headers,
                "POST",
                "/v1/documents",
                expected=201,
                json={
                    "space_slug": space_slug,
                    "profile_external_ref": alpha,
                    "title": f"{marker} prod document {index}",
                    "text": doc_text,
                    "source_type": "prod_load",
                    "source_external_id": f"{marker}:doc:{index}",
                    "classification": "internal",
                },
                extra_headers={"Idempotency-Key": f"{marker}:doc:{index}"},
            )
        )
    restricted_document = _request(
        base_url,
        headers,
        "POST",
        "/v1/documents",
        expected=201,
        json={
            "space_slug": space_slug,
            "profile_external_ref": alpha,
            "title": f"{marker} restricted prod document",
            "text": restricted_text,
            "source_type": "prod_load",
            "source_external_id": f"{marker}:restricted-doc",
            "classification": "restricted",
        },
        extra_headers={"Idempotency-Key": f"{marker}:restricted-doc"},
    )
    large_document_text = _large_prod_document_text(
        marker=marker,
        tail_sentinel=large_doc_tail,
        sections=int(settings["large_doc_sections"]),
    )
    large_document = _request(
        base_url,
        headers,
        "POST",
        "/v1/documents",
        expected=201,
        json={
            "space_slug": space_slug,
            "profile_external_ref": alpha,
            "title": f"{marker} large prod runbook",
            "text": large_document_text,
            "source_type": "prod_load",
            "source_external_id": f"{marker}:large-doc",
            "classification": "internal",
        },
        extra_headers={"Idempotency-Key": f"{marker}:large-doc"},
    )

    first_drain = _worker_until_drained(
        env=env,
        base_url=base_url,
        headers=headers,
        max_rounds=settings["worker_rounds"],
    )
    api_fact_context = _context(
        base_url,
        headers,
        space_slug,
        alpha,
        "PROD_ALPHA_CURRENT_DECISION provider-backed recall",
    )
    api_doc_context = _context(
        base_url,
        headers,
        space_slug,
        alpha,
        "PROD_DOC_SENTINEL_0 Qdrant vector recall production-like project notes",
    )
    api_beta_probe = _context(
        base_url,
        headers,
        space_slug,
        alpha,
        "PROD_BETA_ISOLATION_SENTINEL beta",
    )
    api_thread_current = _context_scoped(
        base_url,
        headers,
        space_slug=space_slug,
        profile_ref=alpha,
        query="PROD_THREAD_CURRENT_SENTINEL PROD_THREAD_NEIGHBOR_SENTINEL",
        thread_ref=thread_current,
        max_facts=10,
        max_chunks=0,
    )
    api_large_doc = _context(
        base_url,
        headers,
        space_slug,
        alpha,
        "PROD_LARGE_DOC_TAIL_SENTINEL multi-chunk recall",
    )
    latency = _run_context_latency_probe(
        base_url=base_url,
        headers=headers,
        space_slug=space_slug,
        profile_ref=alpha,
        marker=marker,
        requests=settings["context_requests"],
    )
    restart_result = {"enabled": False, "elapsed_ms": 0.0}
    post_restart_context = api_fact_context
    if bool(settings["restart_server"]) and restart_server is not None:
        restart_started = time.perf_counter()
        restart_server()
        restart_result = {
            "enabled": True,
            "elapsed_ms": round((time.perf_counter() - restart_started) * 1000, 2),
        }
        post_restart_context = _context(
            base_url,
            headers,
            space_slug,
            alpha,
            "PROD_ALPHA_CURRENT_DECISION provider-backed recall",
        )
    provider_restart_result = {"enabled": False, "elapsed_ms": 0.0}
    provider_restart_fact_context = post_restart_context
    provider_restart_doc_context = api_doc_context
    if bool(settings["restart_providers"]) and restart_providers is not None:
        provider_restart_started = time.perf_counter()
        restart_providers()
        provider_restart_result = {
            "enabled": True,
            "elapsed_ms": round((time.perf_counter() - provider_restart_started) * 1000, 2),
        }
        provider_restart_fact_context = _context(
            base_url,
            headers,
            space_slug,
            alpha,
            "PROD_ALPHA_CURRENT_DECISION provider-backed recall",
        )
        provider_restart_doc_context = _context(
            base_url,
            headers,
            space_slug,
            alpha,
            "PROD_DOC_SENTINEL_0 Qdrant vector recall",
        )

    provider_outage_result = {"enabled": False, "elapsed_ms": 0.0}
    provider_outage_retry = {"retrying": False, "rounds": 0, "counts": {}}
    provider_outage_drain = {"done": True, "rounds": 0, "counts": {}}
    provider_outage_fact_context: dict[str, Any] = {}
    provider_outage_doc_context: dict[str, Any] = {}
    if (
        bool(settings["provider_outage"])
        and stop_providers is not None
        and restart_providers is not None
    ):
        provider_outage_started = time.perf_counter()
        stop_providers()
        try:
            outage_fact = _request(
                base_url,
                headers,
                "POST",
                "/v1/facts",
                expected=201,
                json={
                    "space_slug": space_slug,
                    "profile_external_ref": alpha,
                    "text": outage_fact_text,
                    "kind": "architecture_decision",
                    "classification": "internal",
                    "source_refs": [
                        {
                            "source_type": "prod_load",
                            "source_id": f"{marker}:provider-outage-fact",
                        }
                    ],
                },
                extra_headers={"Idempotency-Key": f"{marker}:provider-outage-fact"},
            )
            outage_document = _request(
                base_url,
                headers,
                "POST",
                "/v1/documents",
                expected=201,
                json={
                    "space_slug": space_slug,
                    "profile_external_ref": alpha,
                    "title": f"{marker} provider outage document",
                    "text": outage_doc_text,
                    "source_type": "manual",
                    "source_external_id": f"{marker}:provider-outage-doc",
                    "classification": "internal",
                },
                extra_headers={"Idempotency-Key": f"{marker}:provider-outage-doc"},
            )
            provider_outage_retry = _worker_until_retry_pending(
                env=env,
                base_url=base_url,
                headers=headers,
                max_rounds=settings["worker_rounds"],
            )
        finally:
            restart_providers()
        provider_outage_drain = _worker_until_drained_after_retry(
            env=env,
            base_url=base_url,
            headers=headers,
            max_rounds=settings["worker_rounds"],
        )
        provider_outage_fact_context = _context(
            base_url,
            headers,
            space_slug,
            alpha,
            "PROD_PROVIDER_OUTAGE_FACT retrying Graphiti recovery",
        )
        provider_outage_doc_context = _context(
            base_url,
            headers,
            space_slug,
            alpha,
            "PROD_PROVIDER_OUTAGE_DOC retrying Qdrant recovery",
        )
        provider_outage_result = {
            "enabled": True,
            "elapsed_ms": round((time.perf_counter() - provider_outage_started) * 1000, 2),
            "fact_id": outage_fact["id"],
            "document_id": outage_document["id"],
            "document_chunks": outage_document.get("chunks"),
        }

    mcp_env = _mcp_process_env(
        base_url=base_url,
        token=token,
        space_slug=space_slug,
        profile_ref=alpha,
    )
    params = StdioServerParameters(command=PYTHON, args=["-m", "memo_stack_mcp"], env=mcp_env)

    async def read_probe_phase(session: Any) -> dict[str, dict[str, Any]]:
        status_result = await _call_mcp_result(session, "memory_status", {}, env=mcp_env)
        status = _structured_mcp(status_result, "prod_load.memory_status", env=mcp_env)
        mcp_fact = _structured_mcp(
            await _call_mcp_result(
                session,
                "memory_search",
                {
                    "query": "PROD_ALPHA_CURRENT_DECISION provider-backed recall",
                    "max_facts": 20,
                    "max_chunks": 0,
                },
                env=mcp_env,
            ),
            "prod_load.memory_search fact",
            env=mcp_env,
        )
        mcp_doc = _structured_mcp(
            await _call_mcp_result(
                session,
                "memory_search",
                {
                    "query": "PROD_DOC_SENTINEL_0 Qdrant vector recall",
                    "max_facts": 0,
                    "max_chunks": 20,
                },
                env=mcp_env,
            ),
            "prod_load.memory_search document",
            env=mcp_env,
        )
        mcp_thread_current = _structured_mcp(
            await _call_mcp_result(
                session,
                "memory_search",
                {
                    "query": "PROD_THREAD_CURRENT_SENTINEL PROD_THREAD_NEIGHBOR_SENTINEL",
                    "thread_external_ref": thread_current,
                    "max_facts": 10,
                    "max_chunks": 0,
                },
                env=mcp_env,
            ),
            "prod_load.memory_search thread",
            env=mcp_env,
        )
        mcp_large_doc = _structured_mcp(
            await _call_mcp_result(
                session,
                "memory_search",
                {
                    "query": "PROD_LARGE_DOC_TAIL_SENTINEL multi-chunk recall",
                    "max_facts": 0,
                    "max_chunks": 20,
                },
                env=mcp_env,
            ),
            "prod_load.memory_search large_document",
            env=mcp_env,
        )
        mcp_outage_fact: dict[str, Any] = {"data": {"items": [], "diagnostics": {}}}
        mcp_outage_doc: dict[str, Any] = {"data": {"items": [], "diagnostics": {}}}
        if bool(settings["provider_outage"]):
            mcp_outage_fact = _structured_mcp(
                await _call_mcp_result(
                    session,
                    "memory_search",
                    {
                        "query": "PROD_PROVIDER_OUTAGE_FACT retrying Graphiti recovery",
                        "max_facts": 20,
                        "max_chunks": 0,
                    },
                    env=mcp_env,
                ),
                "prod_load.memory_search provider_outage_fact",
                env=mcp_env,
            )
            mcp_outage_doc = _structured_mcp(
                await _call_mcp_result(
                    session,
                    "memory_search",
                    {
                        "query": "PROD_PROVIDER_OUTAGE_DOC retrying Qdrant recovery",
                        "max_facts": 0,
                        "max_chunks": 20,
                    },
                    env=mcp_env,
                ),
                "prod_load.memory_search provider_outage_doc",
                env=mcp_env,
            )
        return {
            "status": status,
            "mcp_fact": mcp_fact,
            "mcp_doc": mcp_doc,
            "mcp_thread_current": mcp_thread_current,
            "mcp_large_doc": mcp_large_doc,
            "mcp_outage_fact": mcp_outage_fact,
            "mcp_outage_doc": mcp_outage_doc,
        }

    mcp_read_phase = await _run_mcp_session(
        params,
        operation="prod_load.read_probes",
        env=mcp_env,
        attempts=2,
        callback=read_probe_phase,
    )
    status = mcp_read_phase["status"]
    mcp_fact = mcp_read_phase["mcp_fact"]
    mcp_doc = mcp_read_phase["mcp_doc"]
    mcp_thread_current = mcp_read_phase["mcp_thread_current"]
    mcp_large_doc = mcp_read_phase["mcp_large_doc"]
    mcp_outage_fact = mcp_read_phase["mcp_outage_fact"]
    mcp_outage_doc = mcp_read_phase["mcp_outage_doc"]

    async def mutating_phase(session: Any) -> dict[str, Any]:
        updated = _structured_mcp(
            await _call_mcp_result(
                session,
                "memory_update_fact",
                {
                    "fact_id": target_fact["id"],
                    "expected_version": target_fact["version"],
                    "text": new_text,
                    "reason": "prod load canary update",
                    "source_type": "manual",
                    "source_id": f"{marker}:update",
                },
                env=mcp_env,
            ),
            "prod_load.memory_update_fact",
            env=mcp_env,
        )
        update_drain = _worker_until_drained(
            env=env,
            base_url=base_url,
            headers=headers,
            max_rounds=settings["worker_rounds"],
        )
        mcp_updated = _structured_mcp(
            await _call_mcp_result(
                session,
                "memory_search",
                {
                    "query": "PROD_ALPHA_CURRENT_DECISION drained projection recall",
                    "max_facts": 20,
                    "max_chunks": 0,
                },
                env=mcp_env,
            ),
            "prod_load.memory_search updated",
            env=mcp_env,
        )
        forgotten = _structured_mcp(
            await _call_mcp_result(
                session,
                "memory_forget_fact",
                {"fact_id": target_fact["id"]},
                env=mcp_env,
            ),
            "prod_load.memory_forget_fact",
            env=mcp_env,
        )
        delete_drain = _worker_until_drained(
            env=env,
            base_url=base_url,
            headers=headers,
            max_rounds=settings["worker_rounds"],
        )
        mcp_deleted = _structured_mcp(
            await _call_mcp_result(
                session,
                "memory_search",
                {
                    "query": "PROD_ALPHA_CURRENT_DECISION drained projection recall",
                    "max_facts": 20,
                    "max_chunks": 20,
                },
                env=mcp_env,
            ),
            "prod_load.memory_search deleted",
            env=mcp_env,
        )
        return {
            "updated": updated,
            "update_drain": update_drain,
            "mcp_updated": mcp_updated,
            "forgotten": forgotten,
            "delete_drain": delete_drain,
            "mcp_deleted": mcp_deleted,
        }

    mcp_mutating_phase = await _run_mcp_session(
        params,
        operation="prod_load.mutating_lifecycle",
        env=mcp_env,
        attempts=1,
        callback=mutating_phase,
    )
    updated = mcp_mutating_phase["updated"]
    update_drain = mcp_mutating_phase["update_drain"]
    mcp_updated = mcp_mutating_phase["mcp_updated"]
    forgotten = mcp_mutating_phase["forgotten"]
    delete_drain = mcp_mutating_phase["delete_drain"]
    mcp_deleted = mcp_mutating_phase["mcp_deleted"]

    deleted_document = _request(
        base_url,
        headers,
        "DELETE",
        f"/v1/documents/{documents[0]['id']}",
        expected=200,
    )
    deleted_restricted_document = _request(
        base_url,
        headers,
        "DELETE",
        f"/v1/documents/{restricted_document['id']}",
        expected=200,
    )
    document_delete_drain = _worker_until_drained(
        env=env,
        base_url=base_url,
        headers=headers,
        max_rounds=settings["worker_rounds"],
    )
    after_doc_delete = _context(
        base_url,
        headers,
        space_slug,
        alpha,
        "PROD_DOC_SENTINEL_0 Qdrant vector recall",
    )
    metrics = _request(base_url, headers, "GET", "/v1/diagnostics/metrics", expected=200)
    outbox = _request(base_url, headers, "GET", "/v1/diagnostics/outbox", expected=200)

    api_fact_dump = _dump(api_fact_context)
    api_doc_dump = _dump(api_doc_context)
    mcp_fact_dump = _dump(mcp_fact)
    mcp_doc_dump = _dump(mcp_doc)
    mcp_thread_dump = _dump(mcp_thread_current)
    mcp_large_doc_dump = _dump(mcp_large_doc)
    mcp_outage_fact_dump = _dump(mcp_outage_fact)
    mcp_outage_doc_dump = _dump(mcp_outage_doc)
    mcp_updated_dump = _dump(mcp_updated)
    mcp_deleted_dump = _dump(mcp_deleted)
    after_doc_delete_dump = _dump(after_doc_delete)
    checks = {
        "prod_load_parallel_writes_ok": all(
            item["status"] in {200, 201} for item in create_results
        ),
        "prod_load_duplicate_retry_converges": all(
            item["status"] in {200, 201} for item in duplicate_results
        )
        and len(duplicate_ids) == 1,
        "prod_load_chaos_no_5xx": chaos["server_error_count"] == 0
        and chaos["unauthorized_count"] == settings["chaos_requests"]
        and chaos["validation_count"] == settings["chaos_requests"]
        and chaos["not_found_count"] == settings["chaos_requests"],
        "prod_load_worker_drain_ok": all(
            drain["done"]
            for drain in (
                first_drain,
                provider_outage_drain,
                update_drain,
                delete_drain,
                document_delete_drain,
            )
        ),
        "prod_load_api_graph_recall_ok": old_text in api_fact_dump
        and _context_diagnostic_int(api_fact_context, "graph_hydrated_count") >= 1
        and api_fact_context["diagnostics"].get("graph_status") == "ok",
        "prod_load_api_vector_recall_ok": doc_texts[0] in api_doc_dump
        and _context_diagnostic_int(api_doc_context, "vector_hydrated_count") >= 1
        and api_doc_context["diagnostics"].get("vector_status") == "ok",
        "prod_load_scope_isolation_ok": beta_text not in _dump(api_beta_probe),
        "prod_load_thread_isolation_ok": thread_current_text in _dump(api_thread_current)
        and thread_neighbor_text not in _dump(api_thread_current)
        and thread_current_text in mcp_thread_dump
        and thread_neighbor_text not in mcp_thread_dump,
        "prod_load_restricted_hidden": restricted_text not in api_fact_dump
        and restricted_text not in api_doc_dump,
        "prod_load_large_document_recall_ok": large_document["chunks"] > 1
        and large_doc_tail in _dump(api_large_doc)
        and large_doc_tail in mcp_large_doc_dump
        and _context_diagnostic_int(api_large_doc, "vector_hydrated_count") >= 1
        and _search_diagnostic_int(mcp_large_doc, "vector_hydrated_count") >= 1,
        "prod_load_server_restart_preserves_recall": (
            not bool(settings["restart_server"])
            or bool(restart_result["enabled"])
            and old_text in _dump(post_restart_context)
            and post_restart_context["diagnostics"].get("graph_status") == "ok"
        ),
        "prod_load_provider_restart_preserves_api_recall": (
            not bool(settings["restart_providers"])
            or bool(provider_restart_result["enabled"])
            and old_text in _dump(provider_restart_fact_context)
            and doc_texts[0] in _dump(provider_restart_doc_context)
            and provider_restart_fact_context["diagnostics"].get("graph_status") == "ok"
            and provider_restart_doc_context["diagnostics"].get("vector_status") == "ok"
        ),
        "prod_load_mcp_status_ready": bool(status["data"]["readiness"].get("read_ready"))
        and _required_mcp_adapters_ready(status, ("qdrant", "graphiti", "embeddings")),
        "prod_load_mcp_graph_recall_ok": old_text in mcp_fact_dump
        and _search_diagnostic_int(mcp_fact, "graph_hydrated_count") >= 1,
        "prod_load_mcp_vector_recall_ok": doc_texts[0] in mcp_doc_dump
        and _search_has_chunk_item(mcp_doc)
        and _search_diagnostic_int(mcp_doc, "vector_hydrated_count") >= 1,
        "prod_load_provider_restart_preserves_mcp_recall": (
            not bool(settings["restart_providers"])
            or bool(provider_restart_result["enabled"])
            and old_text in mcp_fact_dump
            and doc_texts[0] in mcp_doc_dump
            and _search_diagnostic_status(mcp_fact, "graph_status") == "ok"
            and _search_diagnostic_status(mcp_doc, "vector_status") == "ok"
        ),
        "prod_load_provider_outage_retry_pending": (
            not bool(settings["provider_outage"])
            or bool(provider_outage_result["enabled"])
            and bool(provider_outage_retry["retrying"])
            and int(provider_outage_retry["counts"].get("retry_pending", 0) or 0) >= 1
            and int(provider_outage_retry["counts"].get("dead", 0) or 0) == 0
        ),
        "prod_load_provider_outage_recovery_drains": (
            not bool(settings["provider_outage"])
            or bool(provider_outage_result["enabled"])
            and bool(provider_outage_drain["done"])
        ),
        "prod_load_provider_outage_api_recall_ok": (
            not bool(settings["provider_outage"])
            or bool(provider_outage_result["enabled"])
            and outage_fact_text in _dump(provider_outage_fact_context)
            and outage_doc_text in _dump(provider_outage_doc_context)
            and _context_diagnostic_int(provider_outage_fact_context, "graph_hydrated_count") >= 1
            and _context_diagnostic_int(provider_outage_doc_context, "vector_hydrated_count") >= 1
            and provider_outage_fact_context["diagnostics"].get("graph_status") == "ok"
            and provider_outage_doc_context["diagnostics"].get("vector_status") == "ok"
        ),
        "prod_load_provider_outage_mcp_recall_ok": (
            not bool(settings["provider_outage"])
            or bool(provider_outage_result["enabled"])
            and outage_fact_text in mcp_outage_fact_dump
            and outage_doc_text in mcp_outage_doc_dump
            and _search_diagnostic_int(mcp_outage_fact, "graph_hydrated_count") >= 1
            and _search_diagnostic_int(mcp_outage_doc, "vector_hydrated_count") >= 1
            and _search_diagnostic_status(mcp_outage_fact, "graph_status") == "ok"
            and _search_diagnostic_status(mcp_outage_doc, "vector_status") == "ok"
        ),
        "prod_load_mcp_update_hides_old": updated["data"]["version"] == 2
        and new_text in mcp_updated_dump
        and old_text not in mcp_updated_dump,
        "prod_load_mcp_delete_hides_current": forgotten["data"]["status"] == "deleted"
        and new_text not in mcp_deleted_dump,
        "prod_load_document_delete_hides_chunk": deleted_document["deleted_chunks"] >= 1
        and doc_texts[0] not in after_doc_delete_dump
        and deleted_restricted_document["deleted_chunks"] >= 1,
        "prod_load_latency_p95_under_threshold": latency["p95_ms"] <= settings["max_p95_ms"],
        "prod_load_outbox_drained": outbox["counts"].get("dead", 0) == 0
        and not _active_outbox_counts(outbox["counts"]),
        "prod_load_provider_diagnostics_ok": all(
            metrics["adapters"][name]["status"] == "ok"
            for name in ("qdrant", "graphiti", "embeddings")
        ),
    }
    if not all(checks.values()):
        diagnostics = {
            "checks": checks,
            "latency": latency,
            "first_drain": first_drain,
            "update_drain": update_drain,
            "delete_drain": delete_drain,
            "document_delete_drain": document_delete_drain,
            "api_fact": _safe_context_diagnostics(api_fact_context),
            "api_doc": _safe_context_diagnostics(api_doc_context),
            "api_large_doc": _safe_context_diagnostics(api_large_doc),
            "api_thread_current": _safe_context_diagnostics(api_thread_current),
            "post_restart": _safe_context_diagnostics(post_restart_context),
            "provider_restart": provider_restart_result,
            "provider_restart_fact": _safe_context_diagnostics(provider_restart_fact_context),
            "provider_restart_doc": _safe_context_diagnostics(provider_restart_doc_context),
            "provider_outage": provider_outage_result,
            "provider_outage_retry": provider_outage_retry,
            "provider_outage_drain": provider_outage_drain,
            "provider_outage_fact": _safe_context_diagnostics(provider_outage_fact_context),
            "provider_outage_doc": _safe_context_diagnostics(provider_outage_doc_context),
            "mcp_fact": _safe_search_diagnostics(mcp_fact),
            "mcp_doc": _safe_search_diagnostics(mcp_doc),
            "mcp_large_doc": _safe_search_diagnostics(mcp_large_doc),
            "mcp_outage_fact": _safe_search_diagnostics(mcp_outage_fact),
            "mcp_outage_doc": _safe_search_diagnostics(mcp_outage_doc),
            "mcp_thread": _safe_search_diagnostics(mcp_thread_current),
            "mcp_updated": _safe_search_diagnostics(mcp_updated),
            "mcp_deleted": _safe_search_diagnostics(mcp_deleted),
            "restart": restart_result,
            "outbox_counts": outbox["counts"],
        }
        raise CleanSmokeFailure(f"Prod load canary checks failed: {diagnostics}")

    return {
        "ok": True,
        "marker": marker,
        "settings": settings,
        "checks": checks,
        "latency": latency,
        "chaos": chaos,
        "worker_drains": {
            "initial": first_drain,
            "provider_outage": provider_outage_drain,
            "update": update_drain,
            "delete": delete_drain,
            "document_delete": document_delete_drain,
        },
        "restart": restart_result,
        "provider_restart": provider_restart_result,
        "provider_outage": {
            "result": provider_outage_result,
            "retry": provider_outage_retry,
        },
        "counts": {
            "facts": len(create_results),
            "duplicate_attempts": len(duplicate_results),
            "documents": len(documents),
            "large_document_chunks": large_document["chunks"],
            "profiles": len(profiles),
        },
        "outbox_counts": outbox["counts"],
        "adapters": {
            name: metrics["adapters"][name]["status"]
            for name in ("qdrant", "graphiti", "embeddings")
        },
    }


async def _run_agent_behavior_benchmark(
    *,
    base_url: str,
    token: str,
    env: Mapping[str, str],
    run_id: str,
) -> dict[str, Any]:
    from memo_stack_mcp.agent_behavior_bench import run_agent_behavior_benchmark

    model = os.getenv("MEMORY_AGENT_BENCH_MODEL", "").strip()
    if not model:
        raise CleanSmokeFailure("Set MEMORY_AGENT_BENCH_MODEL before agent behavior benchmark")
    mcp_env = _mcp_process_env(
        base_url=base_url,
        token=token,
        space_slug="agent-bench",
        profile_ref="default",
    )
    return await run_agent_behavior_benchmark(
        base_url=base_url,
        auth_token=token,
        model=model,
        run_id=run_id,
        mcp_env=mcp_env,
        after_mutating_tool=lambda: _worker_once(env),
        space_slug_prefix="agent-bench",
        profile_external_ref="default",
        python_executable=PYTHON,
    )


def _agent_behavior_failure_summary(result: Mapping[str, Any]) -> dict[str, Any]:
    scenarios = result.get("scenarios", [])
    failed: list[dict[str, Any]] = []
    if isinstance(scenarios, list):
        for scenario in scenarios:
            if not isinstance(scenario, Mapping) or scenario.get("status") == "passed":
                continue
            failures = scenario.get("failures", [])
            checks = scenario.get("memory_checks", [])
            failed.append(
                {
                    "id": scenario.get("id"),
                    "category": scenario.get("category"),
                    "critical": scenario.get("critical"),
                    "failures": failures if isinstance(failures, list) else [],
                    "failed_checks": [
                        check
                        for check in checks
                        if isinstance(check, Mapping) and check.get("passed") is not True
                    ],
                    "tool_names": [
                        call.get("name")
                        for call in scenario.get("tool_calls", [])
                        if isinstance(call, Mapping)
                    ],
                    "tool_calls": _agent_tool_call_summary(scenario.get("tool_calls", [])),
                }
            )
    return {
        "ok": result.get("ok"),
        "suite": result.get("suite"),
        "model": result.get("model"),
        "run_id": result.get("run_id"),
        "elapsed_seconds": result.get("elapsed_seconds"),
        "metrics": result.get("metrics"),
        "metric_failures": result.get("metric_failures"),
        "gates": result.get("gates"),
        "failed_scenarios": failed,
    }


def _agent_tool_call_summary(tool_calls: Any) -> list[dict[str, Any]]:
    if not isinstance(tool_calls, list):
        return []
    summarized: list[dict[str, Any]] = []
    for call in tool_calls:
        if not isinstance(call, Mapping):
            continue
        summarized.append(
            {
                "name": call.get("name"),
                "is_error": call.get("is_error"),
                "side_effects": call.get("side_effects"),
                "arguments": _truncate_json_value(call.get("arguments"), max_chars=900),
                "output_preview": _truncate_text(str(call.get("output_preview") or ""), 900),
            }
        )
    return summarized


def _truncate_json_value(value: Any, *, max_chars: int) -> Any:
    text = json.dumps(_redact_payload(value), ensure_ascii=False, sort_keys=True)
    if len(text) <= max_chars:
        return _redact_payload(value)
    return {"truncated_json": _truncate_text(text, max_chars)}


def _truncate_text(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 15] + "...<truncated>"


def _request(
    base_url: str,
    headers: Mapping[str, str],
    method: str,
    path: str,
    *,
    expected: int,
    json: dict[str, Any] | None = None,
    extra_headers: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    request_headers = dict(headers)
    if extra_headers:
        request_headers.update(extra_headers)
    with httpx.Client(base_url=base_url, headers=request_headers, timeout=90) as client:
        response = client.request(method, path, json=json)
    if response.status_code != expected:
        raise CleanSmokeFailure(
            f"{method} {path} expected {expected}, got {response.status_code}: {response.text}"
        )
    payload = response.json()
    data = payload.get("data")
    if not isinstance(data, dict):
        raise CleanSmokeFailure(f"{method} {path} returned non-object data")
    return data


def _context(
    base_url: str,
    headers: Mapping[str, str],
    space_slug: str,
    profile_ref: str,
    query: str,
) -> dict[str, Any]:
    return _context_scoped(
        base_url,
        headers,
        space_slug=space_slug,
        profile_ref=profile_ref,
        query=query,
        thread_ref=None,
        max_facts=10,
        max_chunks=10,
    )


def _context_scoped(
    base_url: str,
    headers: Mapping[str, str],
    *,
    space_slug: str,
    profile_ref: str,
    query: str,
    thread_ref: str | None,
    max_facts: int,
    max_chunks: int,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "space_slug": space_slug,
        "profile_external_ref": profile_ref,
        "query": query,
        "max_facts": max_facts,
        "max_chunks": max_chunks,
        "token_budget": 1600,
    }
    if thread_ref:
        body["thread_external_ref"] = thread_ref
    return _request(
        base_url,
        headers,
        "POST",
        "/v1/context",
        expected=200,
        json=body,
    )


def _context_diagnostic_int(context: Mapping[str, Any], key: str) -> int:
    diagnostics = context.get("diagnostics", {})
    if not isinstance(diagnostics, Mapping):
        return 0
    value = diagnostics.get(key)
    return value if isinstance(value, int) else 0


def _prod_load_settings() -> dict[str, int | float | bool]:
    return {
        "profiles": _bounded_int_env(
            "MEMORY_CLEAN_SMOKE_LOAD_PROFILES",
            default=3,
            minimum=2,
            maximum=12,
        ),
        "facts_per_profile": _bounded_int_env(
            "MEMORY_CLEAN_SMOKE_LOAD_FACTS_PER_PROFILE",
            default=8,
            minimum=3,
            maximum=100,
        ),
        "documents": _bounded_int_env(
            "MEMORY_CLEAN_SMOKE_LOAD_DOCUMENTS",
            default=3,
            minimum=1,
            maximum=30,
        ),
        "large_doc_sections": _bounded_int_env(
            "MEMORY_CLEAN_SMOKE_LOAD_LARGE_DOC_SECTIONS",
            default=18,
            minimum=3,
            maximum=80,
        ),
        "concurrency": _bounded_int_env(
            "MEMORY_CLEAN_SMOKE_LOAD_CONCURRENCY",
            default=6,
            minimum=1,
            maximum=24,
        ),
        "chaos_requests": _bounded_int_env(
            "MEMORY_CLEAN_SMOKE_LOAD_CHAOS_REQUESTS",
            default=16,
            minimum=1,
            maximum=200,
        ),
        "context_requests": _bounded_int_env(
            "MEMORY_CLEAN_SMOKE_LOAD_CONTEXT_REQUESTS",
            default=10,
            minimum=1,
            maximum=200,
        ),
        "worker_rounds": _bounded_int_env(
            "MEMORY_CLEAN_SMOKE_LOAD_WORKER_ROUNDS",
            default=40,
            minimum=1,
            maximum=300,
        ),
        "max_p95_ms": _bounded_float_env(
            "MEMORY_CLEAN_SMOKE_LOAD_MAX_P95_MS",
            default=15_000.0,
            minimum=1_000.0,
            maximum=120_000.0,
        ),
        "restart_server": _bool(os.getenv("MEMORY_CLEAN_SMOKE_LOAD_RESTART_SERVER", "true")),
        "restart_providers": _bool(os.getenv("MEMORY_CLEAN_SMOKE_LOAD_RESTART_PROVIDERS", "true")),
        "provider_outage": _bool(os.getenv("MEMORY_CLEAN_SMOKE_LOAD_PROVIDER_OUTAGE", "true")),
    }


def _bounded_int_env(name: str, *, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise CleanSmokeFailure(f"{name} must be an integer") from exc
    if value < minimum or value > maximum:
        raise CleanSmokeFailure(f"{name} must be between {minimum} and {maximum}")
    return value


def _bounded_float_env(name: str, *, default: float, minimum: float, maximum: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise CleanSmokeFailure(f"{name} must be numeric") from exc
    if value < minimum or value > maximum:
        raise CleanSmokeFailure(f"{name} must be between {minimum:g} and {maximum:g}")
    return value


def _parallel_post_json(
    *,
    base_url: str,
    token: str,
    requests: list[dict[str, Any]],
    concurrency: int,
) -> list[dict[str, Any]]:
    def run_one(request: dict[str, Any]) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {token}"}
        idempotency_key = request.get("idempotency_key")
        if isinstance(idempotency_key, str) and idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        with httpx.Client(base_url=base_url, headers=headers, timeout=90) as client:
            response = client.post(str(request["path"]), json=request["json"])
        try:
            payload: Any = response.json()
        except ValueError:
            payload = {"text": response.text}
        return {
            "label": request.get("label"),
            "status": response.status_code,
            "data": payload.get("data") if isinstance(payload, Mapping) else None,
            "error": payload.get("error") if isinstance(payload, Mapping) else None,
        }

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(run_one, request) for request in requests]
        return [future.result() for future in as_completed(futures)]


def _single_result_data(results: list[dict[str, Any]], label: str) -> dict[str, Any]:
    matches = [
        item["data"]
        for item in results
        if item.get("label") == label
        and item.get("status") in {200, 201}
        and isinstance(item.get("data"), Mapping)
    ]
    if len(matches) != 1:
        raise CleanSmokeFailure(f"Expected one successful result for {label}, got {len(matches)}")
    return dict(matches[0])


def _successful_result_ids(results: list[dict[str, Any]]) -> set[str]:
    ids: set[str] = set()
    for item in results:
        data = item.get("data")
        if item.get("status") in {200, 201} and isinstance(data, Mapping):
            item_id = data.get("id")
            if isinstance(item_id, str):
                ids.add(item_id)
    return ids


def _large_prod_document_text(*, marker: str, tail_sentinel: str, sections: int) -> str:
    paragraphs = [
        (
            f"{marker}: PROD_LARGE_DOC_SECTION_{index:02d} contains production runbook "
            "notes about memory worker recovery, provider lag, projection freshness, "
            "source citations, scoped retrieval, prompt-injection resistance, and "
            "coding-agent memory continuity after restarts. "
            "This paragraph is intentionally verbose so the document produces several "
            "chunks and exercises Qdrant recall beyond a tiny happy-path note."
        )
        for index in range(sections)
    ]
    paragraphs.append(tail_sentinel)
    return "\n\n".join(paragraphs)


def _run_prod_chaos_flood(
    *,
    base_url: str,
    token: str,
    marker: str,
    requests: int,
) -> dict[str, int]:
    server_error_count = 0
    unauthorized_count = 0
    validation_count = 0
    not_found_count = 0
    with (
        httpx.Client(
            base_url=base_url,
            headers={"Authorization": "Bearer prod-load-wrong-token"},
            timeout=10,
        ) as wrong_client,
        httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        ) as client,
    ):
        for index in range(requests):
            unauthorized = wrong_client.post(
                "/v1/facts",
                json={
                    "space_slug": "prod-load-chaos",
                    "profile_external_ref": "wrong-token",
                    "text": f"{marker}: unauthorized chaos request {index}",
                    "kind": "note",
                    "source_refs": [{"source_type": "prod_load", "source_id": f"unauth:{index}"}],
                },
            )
            invalid = client.post(
                "/v1/context",
                json={
                    "space_slug": "prod-load-chaos",
                    "profile_external_ref": "invalid-context",
                    "query": "",
                },
            )
            missing = client.patch(
                f"/v1/facts/missing-{marker}-{index}",
                json={
                    "expected_version": 1,
                    "text": f"{marker}: missing update",
                    "reason": "prod load chaos missing fact",
                    "source_refs": [{"source_type": "prod_load", "source_id": f"missing:{index}"}],
                },
            )
            for response in (unauthorized, invalid, missing):
                if response.status_code >= 500:
                    server_error_count += 1
            if unauthorized.status_code == 401:
                unauthorized_count += 1
            if invalid.status_code == 400:
                validation_count += 1
            if missing.status_code == 404:
                not_found_count += 1
    return {
        "requests": requests * 3,
        "unauthorized_count": unauthorized_count,
        "validation_count": validation_count,
        "not_found_count": not_found_count,
        "server_error_count": server_error_count,
    }


def _worker_until_drained(
    *,
    env: Mapping[str, str],
    base_url: str,
    headers: Mapping[str, str],
    max_rounds: int,
) -> dict[str, Any]:
    last_outbox: dict[str, Any] | None = None
    for round_index in range(1, max_rounds + 1):
        _worker_once(env)
        outbox = _request(base_url, headers, "GET", "/v1/diagnostics/outbox", expected=200)
        last_outbox = outbox
        counts = outbox.get("counts", {})
        if not isinstance(counts, Mapping):
            raise CleanSmokeFailure("Outbox diagnostics returned invalid counts")
        if int(counts.get("dead", 0) or 0) > 0:
            raise CleanSmokeFailure(f"Outbox has dead jobs: {counts}")
        active = _active_outbox_counts(counts)
        if not active:
            return {"done": True, "rounds": round_index, "counts": dict(counts)}
    return {
        "done": False,
        "rounds": max_rounds,
        "counts": dict(last_outbox.get("counts", {}) if last_outbox else {}),
    }


def _worker_until_retry_pending(
    *,
    env: Mapping[str, str],
    base_url: str,
    headers: Mapping[str, str],
    max_rounds: int,
) -> dict[str, Any]:
    last_outbox: dict[str, Any] | None = None
    for round_index in range(1, max_rounds + 1):
        _worker_once(env)
        outbox = _request(base_url, headers, "GET", "/v1/diagnostics/outbox", expected=200)
        last_outbox = outbox
        counts = outbox.get("counts", {})
        if not isinstance(counts, Mapping):
            raise CleanSmokeFailure("Outbox diagnostics returned invalid counts")
        if int(counts.get("dead", 0) or 0) > 0:
            raise CleanSmokeFailure(f"Outbox has dead jobs during provider outage: {counts}")
        if int(counts.get("retry_pending", 0) or 0) > 0:
            return {"retrying": True, "rounds": round_index, "counts": dict(counts)}
        time.sleep(0.25)
    return {
        "retrying": False,
        "rounds": max_rounds,
        "counts": dict(last_outbox.get("counts", {}) if last_outbox else {}),
    }


def _worker_until_drained_after_retry(
    *,
    env: Mapping[str, str],
    base_url: str,
    headers: Mapping[str, str],
    max_rounds: int,
) -> dict[str, Any]:
    last_outbox: dict[str, Any] | None = None
    for round_index in range(1, max_rounds + 1):
        _worker_once(env)
        outbox = _request(base_url, headers, "GET", "/v1/diagnostics/outbox", expected=200)
        last_outbox = outbox
        counts = outbox.get("counts", {})
        if not isinstance(counts, Mapping):
            raise CleanSmokeFailure("Outbox diagnostics returned invalid counts")
        if int(counts.get("dead", 0) or 0) > 0:
            raise CleanSmokeFailure(f"Outbox has dead jobs after provider recovery: {counts}")
        active = _active_outbox_counts(counts)
        if not active:
            return {"done": True, "rounds": round_index, "counts": dict(counts)}
        time.sleep(0.5)
    return {
        "done": False,
        "rounds": max_rounds,
        "counts": dict(last_outbox.get("counts", {}) if last_outbox else {}),
    }


def _active_outbox_counts(counts: Mapping[str, Any]) -> dict[str, int]:
    return {
        str(key): int(value)
        for key, value in counts.items()
        if key != "done" and isinstance(value, int) and value > 0
    }


def _run_context_latency_probe(
    *,
    base_url: str,
    headers: Mapping[str, str],
    space_slug: str,
    profile_ref: str,
    marker: str,
    requests: int,
) -> dict[str, Any]:
    timings_ms: list[float] = []
    queries = (
        "PROD_ALPHA_CURRENT_DECISION provider-backed recall",
        "PROD_DOC_SENTINEL_0 Qdrant vector recall",
        f"{marker} production load fact scope isolation",
    )
    for index in range(requests):
        started = time.perf_counter()
        _context(base_url, headers, space_slug, profile_ref, queries[index % len(queries)])
        timings_ms.append((time.perf_counter() - started) * 1000)
    return {
        "request_count": len(timings_ms),
        "p50_ms": round(_percentile(timings_ms, 0.50), 2),
        "p95_ms": round(_percentile(timings_ms, 0.95), 2),
        "max_ms": round(max(timings_ms), 2) if timings_ms else 0.0,
    }


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round((len(ordered) - 1) * percentile)))
    return float(ordered[index])


def _safe_context_diagnostics(context: Mapping[str, Any]) -> dict[str, Any]:
    diagnostics = context.get("diagnostics", {})
    if not isinstance(diagnostics, Mapping):
        return {}
    allowed_keys = {
        "facts_considered",
        "graph_candidate_count",
        "graph_hydrated_count",
        "graph_status",
        "items_considered",
        "items_used",
        "keyword_chunks_considered",
        "rag_status",
        "stale_graph_drop_count",
        "stale_vector_drop_count",
        "vector_candidate_count",
        "vector_hydrated_count",
        "vector_status",
    }
    return {key: diagnostics[key] for key in allowed_keys if key in diagnostics}


async def _call_mcp_result(
    session: Any,
    name: str,
    arguments: dict[str, Any],
    *,
    env: Mapping[str, str],
) -> Any:
    result = await _await_mcp(session.call_tool(name, arguments), name, env=env)
    if result.isError:
        raise CleanSmokeFailure(f"{name} returned MCP error: {_redact_text(str(result), env=env)}")
    return result


async def _run_mcp_session(
    params: Any,
    *,
    operation: str,
    env: Mapping[str, str],
    callback: Callable[[Any], Any],
    attempts: int,
) -> Any:
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client

    last_exception: Exception | None = None
    for attempt in range(1, max(attempts, 1) + 1):
        try:
            async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
                await _await_mcp(session.initialize(), f"{operation}.initialize", env=env)
                return await callback(session)
        except Exception as exc:
            last_exception = exc
            if attempt < attempts and _mcp_session_retryable(exc):
                time.sleep(min(2.0, 0.5 * attempt))
                continue
            raise CleanSmokeFailure(
                f"{operation} MCP session failed: {_exception_summary(exc, env=env)}"
            ) from exc
    raise CleanSmokeFailure(
        f"{operation} MCP session failed: "
        f"{_exception_summary(last_exception, env=env) if last_exception else 'unknown error'}"
    )


def _mcp_session_retryable(exc: Exception) -> bool:
    if isinstance(exc, BaseExceptionGroup):
        return True
    message = str(exc).lower()
    return any(
        marker in message
        for marker in (
            "broken pipe",
            "closedresource",
            "connection reset",
            "defunct connection",
            "no data",
            "taskgroup",
        )
    )


def _exception_summary(exc: BaseException | None, *, env: Mapping[str, str]) -> str:
    if exc is None:
        return "unknown error"
    if isinstance(exc, BaseExceptionGroup):
        children = [
            _exception_summary(child, env=env)
            for child in exc.exceptions[:3]
        ]
        suffix = "" if len(exc.exceptions) <= 3 else f"; +{len(exc.exceptions) - 3} more"
        return _redact_text(
            f"{exc.__class__.__name__}({len(exc.exceptions)}): "
            + "; ".join(children)
            + suffix,
            env=env,
        )
    message = str(exc) or exc.__class__.__name__
    return _redact_text(f"{exc.__class__.__name__}: {message}", env=env)


async def _await_mcp(awaitable: Any, operation: str, *, env: Mapping[str, str]) -> Any:
    timeout = _mcp_tool_timeout_seconds()
    try:
        return await asyncio.wait_for(awaitable, timeout=timeout)
    except TimeoutError as exc:
        raise CleanSmokeFailure(f"{operation} timed out after {timeout:g}s") from exc


def _structured_mcp(
    result: Any,
    operation: str,
    *,
    env: Mapping[str, str],
) -> dict[str, Any]:
    if result.structuredContent is not None:
        payload = result.structuredContent
    else:
        payload = json.loads(result.content[0].text)
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise CleanSmokeFailure(f"{operation} failed: {_redact_text(str(payload), env=env)}")
    return payload


def _mcp_text_has_no_secrets(*results: Any, env: Mapping[str, str]) -> bool:
    for result in results:
        for item in getattr(result, "content", []) or []:
            text = str(getattr(item, "text", "") or "")
            if _redact_text(text, env=env) != text:
                return False
    return True


def _dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _search_has_chunk_item(search: Mapping[str, Any]) -> bool:
    data = search.get("data", {})
    if not isinstance(data, Mapping):
        return False
    items = data.get("items", [])
    if not isinstance(items, list):
        return False
    for item in items:
        if not isinstance(item, Mapping):
            continue
        if item.get("item_type") == "chunk" or str(item.get("item_id") or "").startswith("chunk_"):
            return True
        source_refs = item.get("source_refs", [])
        if isinstance(source_refs, list) and any(
            isinstance(ref, Mapping) and bool(ref.get("chunk_id")) for ref in source_refs
        ):
            return True
    return False


def _search_diagnostic_status(search: Mapping[str, Any], key: str) -> str:
    data = search.get("data", {})
    if not isinstance(data, Mapping):
        return ""
    diagnostics = data.get("diagnostics", {})
    if not isinstance(diagnostics, Mapping):
        return ""
    return str(diagnostics.get(key) or "")


def _search_diagnostic_int(search: Mapping[str, Any], key: str) -> int:
    data = search.get("data", {})
    if not isinstance(data, Mapping):
        return 0
    diagnostics = data.get("diagnostics", {})
    if not isinstance(diagnostics, Mapping):
        return 0
    value = diagnostics.get(key)
    return value if isinstance(value, int) else 0


def _safe_search_diagnostics(search: Mapping[str, Any]) -> dict[str, Any]:
    data = search.get("data", {})
    if not isinstance(data, Mapping):
        return {}
    diagnostics = data.get("diagnostics", {})
    if not isinstance(diagnostics, Mapping):
        return {}
    allowed_keys = {
        "facts_considered",
        "graph_candidate_count",
        "graph_hydrated_count",
        "graph_status",
        "keyword_chunks_considered",
        "rag_status",
        "stale_graph_drop_count",
        "stale_vector_drop_count",
        "vector_candidate_count",
        "vector_hydrated_count",
        "vector_status",
    }
    return {key: diagnostics[key] for key in allowed_keys if key in diagnostics}


def _safe_status_readiness(status: Mapping[str, Any]) -> dict[str, Any]:
    data = status.get("data", {})
    if not isinstance(data, Mapping):
        return {}
    readiness = data.get("readiness", {})
    if not isinstance(readiness, Mapping):
        return {}
    allowed_keys = {
        "api_reachable",
        "delete_ready",
        "projection_ready",
        "read_ready",
        "write_ready",
    }
    safe = {key: readiness[key] for key in allowed_keys if key in readiness}
    degraded_reasons = readiness.get("degraded_reasons")
    if isinstance(degraded_reasons, list):
        safe["degraded_reasons"] = [
            str(reason) for reason in degraded_reasons if isinstance(reason, str)
        ][:20]
    return safe


def _safe_status_adapters(status: Mapping[str, Any]) -> dict[str, Any]:
    capabilities = _mcp_status_capabilities(status)
    if not isinstance(capabilities, Mapping):
        return {}
    adapters = capabilities.get("adapters", {})
    result = _adapter_map_status(adapters) if isinstance(adapters, Mapping) else {}
    capability_items = capabilities.get("capabilities", [])
    if isinstance(capability_items, list):
        for item in capability_items:
            if not isinstance(item, Mapping):
                continue
            name = item.get("adapter_name")
            if not isinstance(name, str) or name in result:
                continue
            result[name] = {
                key: item[key] for key in ("enabled", "healthy", "status") if key in item
            }
    return result


def _required_mcp_adapters_ready(status: Mapping[str, Any], names: tuple[str, ...]) -> bool:
    return all(_mcp_adapter_ready(status, name) for name in names)


def _mcp_adapter_ready(status: Mapping[str, Any], name: str) -> bool:
    capabilities = _mcp_status_capabilities(status)
    if not isinstance(capabilities, Mapping):
        return False
    adapters = capabilities.get("adapters", {})
    if isinstance(adapters, Mapping):
        adapter = adapters.get(name)
        if isinstance(adapter, Mapping):
            return _adapter_status_ready(adapter)
    capability_items = capabilities.get("capabilities", [])
    if not isinstance(capability_items, list):
        return False
    return any(
        _adapter_status_ready(item)
        for item in capability_items
        if isinstance(item, Mapping) and item.get("adapter_name") == name
    )


def _mcp_status_capabilities(status: Mapping[str, Any]) -> Mapping[str, Any] | None:
    data = status.get("data", {})
    if not isinstance(data, Mapping):
        return None
    capabilities = data.get("capabilities", {})
    if not isinstance(capabilities, Mapping):
        return None
    return capabilities


def _adapter_map_status(adapters: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, adapter in adapters.items():
        if isinstance(adapter, Mapping):
            result[str(name)] = {
                key: adapter[key] for key in ("enabled", "healthy", "status") if key in adapter
            }
    return result


def _adapter_status_ready(adapter: Mapping[str, Any]) -> bool:
    status = str(adapter.get("status") or "")
    healthy = bool(adapter.get("healthy", status in {"ok", "healthy"}))
    return adapter.get("enabled") is True and healthy and status in {"", "ok", "healthy"}


def _mcp_process_env(
    *,
    base_url: str,
    token: str,
    space_slug: str,
    profile_ref: str,
) -> dict[str, str]:
    env = {key: value for key in SAFE_MCP_INHERITED_ENV_KEYS if (value := os.getenv(key))}
    env["PYTHONPATH"] = _repo_pythonpath(env.get("PYTHONPATH"))
    env.update(
        {
            "MEMORY_MCP_API_URL": base_url,
            "MEMORY_MCP_AUTH_TOKEN": token,
            "MEMORY_MCP_DEFAULT_SPACE_SLUG": space_slug,
            "MEMORY_MCP_DEFAULT_PROFILE_EXTERNAL_REF": profile_ref,
            "MEMORY_MCP_AGENT_NAME": "clean-full-mcp-smoke-agent",
            "MEMORY_MCP_TRANSPORT": "stdio",
            "MEMORY_MCP_WRITE_MODE": "direct",
            "MEMORY_MCP_DELETE_MODE": "explicit",
            "MEMORY_MCP_INGEST_MODE": "allowed",
            "MEMORY_MCP_REQUEST_TIMEOUT_SECONDS": os.getenv(
                "MEMORY_MCP_REQUEST_TIMEOUT_SECONDS",
                DEFAULT_MCP_HTTP_TIMEOUT_SECONDS,
            ),
        }
    )
    return env


def _repo_pythonpath(existing: str | None) -> str:
    package_paths = [
        str(PROJECT_ROOT / "packages" / name)
        for name in (
            "memo_stack_adapters",
            "memo_stack_core",
            "memo_stack_mcp",
            "memo_stack_sdk",
            "memo_stack_server",
        )
    ]
    if existing:
        package_paths.append(existing)
    return os.pathsep.join(package_paths)


def _mcp_tool_timeout_seconds() -> float:
    raw = os.getenv(
        "MEMORY_CLEAN_SMOKE_MCP_CALL_TIMEOUT_SECONDS",
        str(DEFAULT_MCP_TOOL_TIMEOUT_SECONDS),
    )
    try:
        timeout = float(raw)
    except ValueError as exc:
        raise CleanSmokeFailure(
            "MEMORY_CLEAN_SMOKE_MCP_CALL_TIMEOUT_SECONDS must be numeric"
        ) from exc
    if timeout <= 0:
        raise CleanSmokeFailure("MEMORY_CLEAN_SMOKE_MCP_CALL_TIMEOUT_SECONDS must be positive")
    return timeout


def _worker_once(env: Mapping[str, str]) -> None:
    _run_python(
        env,
        "-m",
        "memo_stack_server.worker",
        "--once",
        "--limit",
        "20",
        timeout=_worker_timeout_seconds(),
    )


def _worker_timeout_seconds() -> float:
    raw = os.getenv("MEMORY_CLEAN_SMOKE_WORKER_TIMEOUT_SECONDS", "240")
    try:
        timeout = float(raw)
    except ValueError as exc:
        raise CleanSmokeFailure(
            "MEMORY_CLEAN_SMOKE_WORKER_TIMEOUT_SECONDS must be numeric"
        ) from exc
    if timeout <= 0:
        raise CleanSmokeFailure("MEMORY_CLEAN_SMOKE_WORKER_TIMEOUT_SECONDS must be positive")
    return timeout


def _graph_episode(env: Mapping[str, str], fact_id: str) -> dict[str, Any]:
    driver = GraphDatabase.driver(
        env["MEMORY_GRAPHITI_NEO4J_URI"],
        auth=(env["MEMORY_GRAPHITI_NEO4J_USER"], env["MEMORY_GRAPHITI_NEO4J_PASSWORD"]),
    )
    try:
        records, _, _ = driver.execute_query(
            (
                "MATCH (e:Episodic {name: $name}) "
                "RETURN e.uuid AS uuid, e.content AS content ORDER BY e.created_at"
            ),
            name=f"fact:{fact_id}",
            database_="neo4j",
        )
    finally:
        driver.close()
    return {
        "count": len(records),
        "contents": [str(record.get("content") or "") for record in records],
    }


def _compose(project_name: str, env: Mapping[str, str], *args: str, check: bool = True) -> None:
    completed = subprocess.run(
        ["docker", "compose", "-p", project_name, *args],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=240,
    )
    if check and completed.returncode != 0:
        raise CleanSmokeFailure(
            "docker compose failed: " + completed.stdout[-2000:] + completed.stderr[-2000:]
        )


def _run_python(env: Mapping[str, str], *args: str, timeout: float = 240) -> None:
    completed = subprocess.run(
        [PYTHON, *args],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )
    if completed.returncode != 0:
        raise CleanSmokeFailure(
            f"python {' '.join(args)} failed: "
            + completed.stdout[-2000:]
            + completed.stderr[-2000:]
        )


def _start_server(env: Mapping[str, str]) -> ServerHandle:
    output = tempfile.TemporaryFile(mode="w+", encoding="utf-8")  # noqa: SIM115
    try:
        process = subprocess.Popen(
            [PYTHON, "-m", "memo_stack_server.main"],
            cwd=PROJECT_ROOT,
            env=env,
            stdout=output,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except Exception:
        output.close()
        raise
    return ServerHandle(process=process, output=output)


def _wait_for_postgres(project_name: str, env: Mapping[str, str]) -> None:
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        completed = subprocess.run(
            [
                "docker",
                "compose",
                "-p",
                project_name,
                "exec",
                "-T",
                "memo_stack_postgres",
                "pg_isready",
                "-U",
                "memory",
                "-d",
                "memory",
            ],
            cwd=PROJECT_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        if completed.returncode == 0:
            return
        time.sleep(1)
    raise CleanSmokeFailure("Postgres did not become ready")


def _wait_for_http(url: str, *, token: str | None = None) -> None:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    deadline = time.monotonic() + 120
    last_error = ""
    while time.monotonic() < deadline:
        try:
            with httpx.Client(timeout=5) as client:
                response = client.get(url, headers=headers)
            if response.status_code < 500:
                return
            last_error = response.text[:500]
        except Exception as exc:
            last_error = str(exc)
        time.sleep(1)
    raise CleanSmokeFailure(f"HTTP endpoint did not become ready: {url}: {last_error}")


def _wait_for_neo4j(port: int) -> None:
    deadline = time.monotonic() + 120
    last_error = ""
    while time.monotonic() < deadline:
        driver = GraphDatabase.driver(
            f"bolt://127.0.0.1:{port}",
            auth=("neo4j", "memostackgraph"),
        )
        try:
            driver.verify_connectivity()
            return
        except Exception as exc:
            last_error = str(exc)
        finally:
            driver.close()
        time.sleep(1)
    raise CleanSmokeFailure(f"Neo4j did not become ready: {last_error}")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _process_tail(server: ServerHandle) -> str:
    try:
        server.output.flush()
        server.output.seek(0)
        return server.output.read()[-2000:]
    except Exception:
        return ""


def _stop_server(server: ServerHandle) -> str:
    try:
        _terminate_process(server.process)
        return _process_tail(server)
    finally:
        server.output.close()


def _terminate_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def _bool(value: str) -> bool:
    return value.lower() in {"1", "true", "yes", "on"}


def _redact_payload(value: Any, *, env: Mapping[str, str] | None = None) -> Any:
    if isinstance(value, str):
        return _redact_text(value, env=env)
    if isinstance(value, dict):
        redacted: dict[Any, Any] = {}
        for key, item in value.items():
            redacted_key = _redact_key(key, env=env)
            if isinstance(key, str) and _is_sensitive_key_name(key):
                redacted_item: Any = "<redacted>"
            else:
                redacted_item = _redact_payload(item, env=env)
            redacted[_dedupe_key(redacted, redacted_key)] = redacted_item
        return redacted
    if isinstance(value, list):
        return [_redact_payload(item, env=env) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_payload(item, env=env) for item in value)
    return value


def _redact_text(text: str, *, env: Mapping[str, str] | None = None) -> str:
    redacted = text
    for value in _sensitive_values(env):
        redacted = redacted.replace(value, "<redacted>")
    for key in SENSITIVE_ENV_KEYS:
        redacted = redacted.replace(key, "<redacted-env>")
    for pattern in SENSITIVE_TEXT_PATTERNS:
        redacted = pattern.sub("<redacted>", redacted)
    return redacted


def _redact_key(key: Any, *, env: Mapping[str, str] | None = None) -> Any:
    if not isinstance(key, str):
        return key
    if _is_sensitive_key_name(key):
        return "<redacted-key>"
    redacted = _redact_text(key, env=env)
    return "<redacted-key>" if redacted != key else key


def _dedupe_key(mapping: Mapping[Any, Any], key: Any) -> Any:
    if key not in mapping:
        return key
    if not isinstance(key, str):
        return key
    index = 2
    while f"{key}-{index}" in mapping:
        index += 1
    return f"{key}-{index}"


def _is_sensitive_key_name(key: str) -> bool:
    normalized = key.strip()
    lowered = normalized.lower()
    if lowered in SAFE_REPORT_KEY_NAMES:
        return False
    if lowered in SENSITIVE_HEADER_KEYS or lowered in SENSITIVE_KEY_NAMES:
        return True
    upper = normalized.upper()
    if upper in SENSITIVE_ENV_KEYS or upper.endswith(SENSITIVE_KEY_SUFFIXES):
        return True
    compact = re.sub(r"[^a-z0-9]+", "", lowered)
    if not compact:
        return False
    if compact.endswith(("count", "countzero", "rate", "ratemin080", "ratemin090")):
        return False
    sensitive_compact = {
        re.sub(r"[^a-z0-9]+", "", item) for item in (*SENSITIVE_HEADER_KEYS, *SENSITIVE_KEY_NAMES)
    }
    if compact in sensitive_compact:
        return True
    if compact.endswith("apikey") or compact.endswith("privatekey"):
        return True
    if compact.endswith("token") and not compact.endswith("budget"):
        return True
    return any(
        marker in compact
        for marker in (
            "authorization",
            "credential",
            "connectionstring",
            "databaseurl",
            "password",
            "passwd",
            "secret",
        )
    )


def _sensitive_values(env: Mapping[str, str] | None = None) -> list[str]:
    envs = [os.environ]
    if env is not None:
        envs.append(env)
    values = set()
    for item in envs:
        values.update(
            str(item.get(key) or "").strip()
            for key in SENSITIVE_ENV_KEYS
            if str(item.get(key) or "").strip()
        )
        values.update(
            str(value).strip()
            for key, value in item.items()
            if isinstance(key, str) and _is_sensitive_key_name(key) and len(str(value).strip()) >= 8
        )
    return sorted(values, key=len, reverse=True)


if __name__ == "__main__":
    raise SystemExit(main())

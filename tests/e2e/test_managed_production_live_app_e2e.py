from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import subprocess
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import infinity_context_server.memory_comparison_managed_mem0_runtime_http as mem0_runtime_http
import pytest
from infinity_context_server import memory_comparison_managed_live_cli as managed_live_cli
from infinity_context_server.memory_comparison_full_profiles import (
    PROFILE_LONGMEMEVAL_TOP_50,
)
from infinity_context_server.memory_comparison_mem0_contract import (
    MEM0_BENCHMARK_CAPABILITIES_SCHEMA_VERSION_V2,
)
from infinity_context_server_harness import PROJECT_ROOT, run_infinity_context_server
from sqlalchemy.engine import make_url

_MODEL = managed_live_cli.MANAGED_LIVE_CLI_MODEL
_CASE_ID = "852ce960"
_ANSWER = "$400,000"
_E2E_MANAGED_MAX_TOTAL_TOKENS = 250_000
_MANAGED_LIVE_CLI = PROJECT_ROOT / ".venv" / "bin" / "infinity-context-managed-live-canary"
_STDIO_TAIL_LIMIT = 8_000


def _controlled_cli_env(
    *,
    infinity_token: str,
    mem0_probe_token: str,
    subscription_token: str,
) -> dict[str, str]:
    return {
        "PATH": os.defpath,
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONIOENCODING": "utf-8",
        "MEMORY_EVAL_AUTH_TOKEN": infinity_token,
        "MEM0_BENCHMARK_PROBE_TOKEN": mem0_probe_token,
        "SUBSCRIPTION_RUNTIME_BRIDGE_BEARER_TOKEN": subscription_token,
    }


def _stdio_tail(value: str) -> str:
    return value[-_STDIO_TAIL_LIMIT:]


class _BridgeState:
    def __init__(self, *, subscription_token: str, mem0_token: str, probe_token: str) -> None:
        self.subscription_token = subscription_token
        self.mem0_token = mem0_token
        self.probe_token = probe_token
        self.subscription_calls: list[str] = []
        self.mem0_calls: list[str] = []
        self.requests: list[str] = []
        self.memories: dict[str, dict[str, Any]] = {}
        self.lock = threading.Lock()

    def has_valid_mem0_api_key(self, headers: dict[str, str]) -> bool:
        api_key = headers.get("x-api-key")
        return api_key == self.mem0_token or (
            isinstance(api_key, str) and api_key.startswith("local-auth-disabled-")
        )

    def dispatch(
        self,
        method: str,
        path: str,
        headers: dict[str, str],
        payload: object,
    ) -> tuple[int, object]:
        with self.lock:
            self.requests.append(f"{method} {path}")
        if path == "/v1/chat/completions" and method == "POST":
            assert headers.get("authorization") == f"Bearer {self.subscription_token}"
            assert isinstance(payload, dict)
            messages = payload.get("messages")
            assert isinstance(messages, list) and len(messages) == 2
            system = str(messages[0].get("content", ""))
            user = str(messages[1].get("content", ""))
            prompt = f"{system}\n{user}".casefold()
            if "Reply with exactly READY" in system:
                kind, content = "readiness", "READY"
            elif (
                "final verdict as exactly" in prompt
                and "model response:" in prompt
            ):
                kind, content = "judge", "yes"
            else:
                kind, content = "answer", _ANSWER
            with self.lock:
                self.subscription_calls.append(kind)
                call_number = len(self.subscription_calls)
            return 200, {
                "id": f"chatcmpl-sandbox-{call_number}",
                "object": "chat.completion",
                "model": _MODEL,
                "system_fingerprint": "sandbox-loopback-v1",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ],
            }

        if path == "/openapi.json" and method == "GET":
            return 200, _mem0_openapi()
        if path == "/benchmark/attest-timestamp" and method == "POST":
            assert headers.get("x-benchmark-probe-token") == self.probe_token
            assert isinstance(payload, dict)
            return 200, _witnessed_manifest(
                run_id=str(payload["run_id"]),
                probe_nonce=str(payload["probe_nonce"]),
                target_identity_sha256=str(payload["target_identity_sha256"]),
                probe_token=self.probe_token,
            )
        if path == "/memories" and method == "POST":
            assert self.has_valid_mem0_api_key(headers)
            assert isinstance(payload, dict)
            metadata = dict(payload.get("metadata") or {})
            messages = payload.get("messages")
            assert isinstance(messages, list)
            payload_sha = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
            memory_id = f"mem-{payload_sha[:24]}"
            text = "\n".join(str(item.get("content", "")) for item in messages)
            item = {
                "id": memory_id,
                "event": "ADD",
                "memory": text,
                "metadata": metadata,
            }
            with self.lock:
                self.memories[memory_id] = item
                self.mem0_calls.append("ingest")
            return 200, {"request_id": f"req-{memory_id}", "results": [item]}
        if path == "/search" and method == "POST":
            assert self.has_valid_mem0_api_key(headers)
            with self.lock:
                self.mem0_calls.append("search")
                results = list(self.memories.values())
            return 200, {"results": results}
        if path == "/memories" and method == "DELETE":
            assert self.has_valid_mem0_api_key(headers)
            with self.lock:
                self.mem0_calls.append("delete")
                self.memories.clear()
            return 200, {"deleted": True, "verified_absent": True}
        raise AssertionError(f"unexpected loopback call: {method} {path}")


def test_loopback_bridge_classifies_official_longmemeval_judge_prompt() -> None:
    state = _BridgeState(
        subscription_token="subscription-token",
        mem0_token="mem0-token",
        probe_token="probe-token",
    )

    status, response = state.dispatch(
        "POST",
        "/v1/chat/completions",
        {"authorization": "Bearer subscription-token"},
        {
            "messages": [
                {"role": "system", "content": ""},
                {
                    "role": "user",
                    "content": (
                        "Correct Answer: $400,000\n"
                        "Model Response: $400,000\n"
                        'Give your final verdict as exactly "yes" or "no".'
                    ),
                },
            ]
        },
    )

    assert status == 200
    assert state.subscription_calls == ["judge"]
    assert response["choices"][0]["message"]["content"] == "yes"


@contextmanager
def _loopback_bridge(state: _BridgeState) -> Iterator[str]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            self._dispatch()

        def do_POST(self) -> None:
            self._dispatch()

        def do_DELETE(self) -> None:
            self._dispatch()

        def _dispatch(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length)) if length else None
            parsed = urlsplit(self.path)
            try:
                status, response = state.dispatch(
                    self.command,
                    parsed.path,
                    {key.casefold(): value for key, value in self.headers.items()},
                    payload,
                )
            except BaseException as exc:
                status, response = 500, {"error": type(exc).__name__, "detail": str(exc)}
            raw = json.dumps(response, separators=(",", ":")).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *_: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_verified_managed_production_runs_through_live_subprocess_and_postgres16(
    tmp_path: Path,
) -> None:
    dataset_path = _official_longmemeval_dataset_path()
    run_id = f"sandbox-managed-production-{uuid.uuid4().hex}"
    infinity_token = "sandbox-infinity-admin-token"
    subscription_token = "sandbox-subscription-token"
    mem0_token = "sandbox-mem0-token"
    probe_token = "sandbox-mem0-probe-token"
    state = _BridgeState(
        subscription_token=subscription_token,
        mem0_token=mem0_token,
        probe_token=probe_token,
    )

    assert _MANAGED_LIVE_CLI.is_file(), _MANAGED_LIVE_CLI
    with (
        _isolated_postgres16_database() as database_url,
        _loopback_bridge(state) as bridge_origin,
        run_infinity_context_server(
            tmp_path,
            token=infinity_token,
            extra_env={"MEMORY_DATABASE_URL": database_url},
            projection_worker=True,
        ) as infinity,
    ):
        implementation_sha256 = hashlib.sha256(
            Path(mem0_runtime_http.__file__).read_bytes()
        ).hexdigest()
        completed = subprocess.run(
            [
                str(_MANAGED_LIVE_CLI),
                "--dataset",
                str(dataset_path),
                "--profile",
                PROFILE_LONGMEMEVAL_TOP_50,
                "--case-id",
                _CASE_ID,
                "--run-id",
                run_id,
                "--infinity-api-url",
                infinity.base_url,
                "--mem0-api-url",
                bridge_origin,
                "--subscription-runtime-url",
                bridge_origin,
                "--max-total-tokens",
                str(_E2E_MANAGED_MAX_TOTAL_TOKENS),
                "--mem0-runtime-implementation-sha256",
                implementation_sha256,
                "--allow-live",
                "--allow-paid-llm",
                "--operator-notified",
                "--mem0-local-auth-disabled-managed",
                "--allow-mem0-host",
                "127.0.0.1",
                "--connect-timeout-seconds",
                "2",
                "--request-timeout-seconds",
                "15",
                "--run-timeout-seconds",
                "180",
            ],
            cwd=PROJECT_ROOT,
            env=_controlled_cli_env(
                infinity_token=infinity_token,
                mem0_probe_token=probe_token,
                subscription_token=subscription_token,
            ),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=200,
            check=False,
        )

        assert completed.returncode == 0, (
            f"exit_code={completed.returncode}; stdout_tail={_stdio_tail(completed.stdout)!r}; "
            f"stderr_tail={_stdio_tail(completed.stderr)!r}; "
            f"subscription_calls={state.subscription_calls}; mem0_calls={state.mem0_calls}; "
            f"bridge_requests={state.requests}"
        )
        try:
            report = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            pytest.fail(
                f"CLI stdout was not one JSON report: {_stdio_tail(completed.stdout)!r}; "
                f"stderr_tail={_stdio_tail(completed.stderr)!r}; error={exc}"
            )
        assert type(report) is dict
        assert report["ok"] is True
        assert report["scope"] == "canary"
        assert report["selected_case_count"] == 1
        result = report["result"]
        assert isinstance(result, dict)
        assert result["managed_run"]["case_count"] == 1
        assert result["managed_run"]["terminal_delete_complete"] is True
        assert state.subscription_calls == ["readiness", "answer", "judge", "answer", "judge"]
        assert state.mem0_calls.count("search") == 1
        assert state.mem0_calls.count("delete") >= 3
        assert state.memories == {}

        run_sha = hashlib.sha256(run_id.encode()).hexdigest()
        registry = httpx.get(
            f"{infinity.base_url}/v1/internal/memory-comparison/runs/{run_sha}/cleanup",
            headers={"Authorization": f"Bearer {infinity_token}"},
            timeout=10,
        )
        assert registry.status_code == 200, registry.text
        registry_data = registry.json()["data"]
        assert registry_data["state"] == "cleanup_complete"
        assert registry_data["completion_receipt"] is not None


@contextmanager
def _isolated_postgres16_database() -> Iterator[str]:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncpg = pytest.importorskip("asyncpg")
    parsed = make_url(database_url)
    if not parsed.drivername.startswith("postgresql"):
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not PostgreSQL")
    database_name = f"managed_production_e2e_{uuid.uuid4().hex}"
    admin_dsn = parsed.set(drivername="postgresql").render_as_string(hide_password=False)
    app_url = parsed.set(
        drivername="postgresql+asyncpg",
        database=database_name,
    ).render_as_string(hide_password=False)

    async def create_database() -> None:
        connection = await asyncpg.connect(admin_dsn)
        try:
            version = await connection.fetchval("SHOW server_version")
            if not str(version).startswith("16."):
                pytest.skip(f"PostgreSQL 16 required, found {version}")
            await connection.execute(f'CREATE DATABASE "{database_name}"')
        finally:
            await connection.close()

    async def drop_database() -> None:
        connection = await asyncpg.connect(admin_dsn)
        try:
            await connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = $1 AND pid <> pg_backend_pid()",
                database_name,
            )
            await connection.execute(f'DROP DATABASE IF EXISTS "{database_name}"')
        finally:
            await connection.close()

    asyncio.run(create_database())
    try:
        yield app_url
    finally:
        asyncio.run(drop_database())


def _official_longmemeval_dataset_path() -> Path:
    path_value = os.getenv("INFINITY_CONTEXT_TEST_LONGMEMEVAL_DATASET")
    if not path_value:
        pytest.skip("INFINITY_CONTEXT_TEST_LONGMEMEVAL_DATASET is not configured")
    path = Path(path_value)
    if not path.is_file():
        pytest.skip("INFINITY_CONTEXT_TEST_LONGMEMEVAL_DATASET is unavailable")
    return path


def _mem0_openapi() -> dict[str, object]:
    return {
        "paths": {
            "/health": {"get": {"responses": {"200": {}}}},
            "/memories": {
                "post": {
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/AddRequest"}
                            }
                        }
                    },
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/AddResponse"}
                                }
                            }
                        }
                    },
                },
                "delete": {
                    "parameters": [
                        {
                            "name": "user_id",
                            "in": "query",
                            "required": True,
                            "schema": {"type": "string"},
                        },
                        {
                            "name": "run_id",
                            "in": "query",
                            "required": True,
                            "schema": {"type": "string"},
                        },
                    ],
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "additionalProperties": False,
                                        "properties": {
                                            "deleted": {"type": "boolean"},
                                            "verified_absent": {"type": "boolean"},
                                        },
                                        "required": ["deleted", "verified_absent"],
                                    }
                                }
                            }
                        }
                    },
                },
            },
            "/search": {
                "post": {
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/SearchRequest"}
                            }
                        }
                    },
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/SearchResponse"}
                                }
                            }
                        }
                    },
                }
            },
            "/benchmark/capabilities": {"get": {"responses": {"200": {}}}},
            "/benchmark/attest-timestamp": {"post": {}},
        },
        "components": {
            "schemas": {
                "AddRequest": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "messages": {"type": "array"},
                        "user_id": {"type": ["string", "null"]},
                        "run_id": {"type": ["string", "null"]},
                        "metadata": {"type": ["object", "null"]},
                        "timestamp": {"type": "integer"},
                    },
                    "required": ["messages", "timestamp"],
                },
                "SearchRequest": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "query": {"type": "string"},
                        "filters": {"type": "object"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["query", "filters", "limit"],
                },
                "AddResponse": {
                    "type": "object",
                    "properties": {"results": {"type": "array", "items": {}}},
                    "required": ["results"],
                },
                "SearchResponse": {
                    "type": "object",
                    "properties": {"results": {"type": "array", "items": {}}},
                    "required": ["results"],
                },
            }
        },
    }


def _witnessed_manifest(
    *, run_id: str, probe_nonce: str, target_identity_sha256: str, probe_token: str
) -> dict[str, object]:
    checked_at = datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    artifact = "9c567df69af794278bc051400829d1a2d4f8aa659cae6cd019d88ec66dbf4f3f"
    manifest: dict[str, object] = {
        "schema_version": MEM0_BENCHMARK_CAPABILITIES_SCHEMA_VERSION_V2,
        "runtime_mode": "managed_platform",
        "wrapper_source_sha256": "a" * 64,
        "wrapper_source_revision": "b" * 40,
        "config_fingerprint_sha256": "c" * 64,
        "sdk": {
            "distribution": "mem0ai",
            "version": "2.0.14",
            "source_revision": "b357a5a1b03c299ec8229c268e63cfac0f7c6566",
            "artifact_sha256": artifact,
            "verification": {
                "method": "direct_url_archive_info_sha256",
                "observed_sha256": artifact,
                "passed": True,
            },
        },
        "platform": {
            "api_origin": "https://api.mem0.ai",
            "api_generation": "v3",
            "add_path": "/v3/memories/add/",
            "search_path": "/v3/memories/search/",
            "event_path_template": "/v1/event/{event_id}/",
            "server_source_revision": None,
            "server_revision_attestable": False,
        },
        "persisted_source_identity": {
            "request_metadata_required": True,
            "source_filtered_readback_supported": True,
            "source_id_roundtrip_attested": True,
            "source_sha256_roundtrip_attested": True,
            "sanitized_identity_response": True,
        },
        "timestamp": {
            "request_supported": True,
            "sdk_forwarding_supported": True,
            "event_completion_supported": True,
            "readback_supported": True,
            "attestation": {
                "status": "passed",
                "checked_at": checked_at,
                "probe_mode": "live_sentinel",
                "input_epoch_seconds": 1672531200,
                "expected_created_at": "2023-01-01T00:00:00Z",
                "event_terminal_status": "SUCCEEDED",
                "readback_result_count": 1,
                "persisted_created_at": "2023-01-01T00:00:00Z",
                "delta_seconds": 0.0,
                "cleanup_succeeded": True,
                "failure_code": None,
            },
        },
        "refresh_binding": {
            "status": "passed",
            "run_id_sha256": hashlib.sha256(run_id.encode()).hexdigest(),
            "probe_nonce_sha256": hashlib.sha256(probe_nonce.encode()).hexdigest(),
            "target_identity_sha256": target_identity_sha256,
            "refreshed_at": checked_at,
        },
    }
    fingerprint = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    binding = manifest["refresh_binding"]
    assert isinstance(binding, dict)
    message = "\n".join(
        (
            "mem0-benchmark-runtime-witness.v1",
            str(binding["run_id_sha256"]),
            str(binding["probe_nonce_sha256"]),
            str(binding["target_identity_sha256"]),
            str(binding["refreshed_at"]),
            fingerprint,
        )
    ).encode()
    manifest["refresh_witness"] = {
        "algorithm": "hmac-sha256",
        "manifest_fingerprint_sha256": fingerprint,
        "signature": hmac.new(probe_token.encode(), message, hashlib.sha256).hexdigest(),
    }
    return manifest

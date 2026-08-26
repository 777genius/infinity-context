"""Deterministic custom-loopback process recovery proof.

This is not the PR35 actual Mem0 adapter. The paired E2E test separately executes
the pinned actual-adapter provider-free gate and records its provenance.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import signal
import sqlite3
import sys
import time
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

ROOT = Path(__file__).resolve().parents[2]
PHASE_C_ROOT = ROOT / "benchmarks" / "phase-c-canary"
for path in (PHASE_C_ROOT,):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from infinity_context_server.memory_comparison_managed_mem0_v5_composition import (  # noqa: E402
    ManagedMem0V5StatePaths,
    compose_managed_mem0_v5,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_credentials import (  # noqa: E402
    ManagedMem0V5CredentialPaths,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_lane import (  # noqa: E402
    ManagedMem0V5BudgetPolicy,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (  # noqa: E402
    ManagedMem0V5ManifestProjector,
)
from infinity_context_server.memory_comparison_managed_run_contract import (  # noqa: E402
    ManagedRunCase,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (  # noqa: E402
    Mem0OssAdmissionRequest,
    Mem0OssFullRunAdmission,
    canonical_sha256,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_http import (  # noqa: E402
    Mem0V5OperationReceiptAuthority,
    Mem0V5ReceiptAuthority,
)
from phase_c_canary.runtime_binding import RuntimeBindingComposition  # noqa: E402
from phase_c_canary.runtime_receipt_v2 import RuntimeReceiptV2Boundary  # noqa: E402

EVIDENCE_KEY_DOMAIN = b"mem0-oss-adapter-v5/evidence-key/v1"
SECRETS = {
    "bearer": b"custom-loopback-bearer-token-value-32-bytes",
    "evidence": b"custom-loopback-evidence-key-value-32-bytes",
    "receipt": b"custom-loopback-receipt-secret-value-32-bytes",
    "signing": b"custom-loopback-checkpoint-signing-key-32-bytes",
    "head": b"custom-loopback-checkpoint-head-key-32-bytes",
}


class LoopbackServiceError(RuntimeError):
    def __init__(self, code: str, status_code: int = 409) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__(code)


def _sha(value: str | bytes) -> str:
    raw = value if isinstance(value, bytes) else value.encode()
    return hashlib.sha256(raw).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode()


def _private_write(path: Path, value: bytes, mode: int = 0o600) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        os.write(descriptor, value)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def cases() -> tuple[ManagedRunCase, ...]:
    corpus_id = f"locomo-corpus-{'a' * 64}"
    record = {
        "schema_version": "memory-comparison-managed-corpus.v2",
        "benchmark": "locomo",
        "corpus_id": corpus_id,
        "thread_id": f"locomo-thread-{'b' * 64}",
        "memories": [
            {
                "kind": "fact",
                "role": "user",
                "session_alias": "session-0001",
                "source_alias": "memory-000001",
                "speaker": "Alice",
                "session_date": "2024-03-10",
                "text": "Alice likes durable tea.",
                "timestamp": 1,
            },
            {
                "kind": "fact",
                "role": "user",
                "session_alias": "session-0001",
                "source_alias": "memory-000002",
                "speaker": "Bob",
                "session_date": "2024-03-10",
                "text": "ZERO_MEMORY_SENTINEL",
                "timestamp": 2,
            },
        ],
        "documents": [],
        "conversations": [],
    }
    return (ManagedRunCase("case-custom-loopback-process-recovery", corpus_id, record),)


def prepare_environment(root: Path, port: int) -> dict[str, object]:
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    state = root / "state"
    secrets = root / "secrets"
    results = root / "results"
    barriers = root / "barriers"
    for directory in (state, secrets, results, barriers):
        directory.mkdir(mode=0o700)
    secret_paths: dict[str, str] = {}
    for name, value in SECRETS.items():
        path = secrets / name
        _private_write(path, value)
        secret_paths[name] = str(path)

    current_date = "2026-08-07"
    authority = ManagedMem0V5ManifestProjector().project(cases(), current_date=current_date)
    binding = RuntimeBindingComposition.compose_phase_c_canary().issue()
    request_hashes = [_sha(f"provider-free-request-{index}") for index in range(2)]
    output_hashes = [_sha(f"provider-free-output-{index}") for index in range(2)]
    request = Mem0OssAdmissionRequest(
        run_id="managed-v5-custom-loopback-process-recovery",
        route_sha256=binding.route_binding_sha256,
        credential_binding_sha256=_sha(SECRETS["evidence"]),
        model="gpt-5.6-sol",
        reasoning_effort="medium",
        service_tier="priority",
        runtime_source_revision="custom-loopback-process-recovery-r1",
        runtime_source_sha256=binding.runtime_source_sha256,
        runtime_base_sha256=_sha("custom-loopback-process-recovery-runtime-base"),
        expected_operation_count=authority.operation_count,
    )
    admission = Mem0OssFullRunAdmission(
        request=request,
        ingestion_manifest_sha256=authority.ingestion_manifest_sha256,
        ingestion_root_sha256=authority.ingestion_root_sha256,
        ingestion_unit_count=authority.operation_count,
    )
    units: list[dict[str, object]] = []
    operations: list[dict[str, object]] = []
    for index, unit in enumerate(authority.units):
        operation_id = canonical_sha256(
            {
                "admission_commitment_sha256": admission.commitment_sha256,
                "unit_index": index,
                "unit_identity_sha256": unit.unit_identity_sha256,
            }
        )
        units.append(
            {
                "sequence": index,
                "operation_id_sha256": operation_id,
                "unit_identity_sha256": unit.unit_identity_sha256,
                "unit_sha256": unit.unit_sha256,
                "scope_sha256": unit.scope_sha256,
                "source_id": unit.source_id,
                "source_sha256": unit.source_sha256,
                "corpus_id": unit.corpus_id,
                "observation_date": unit.observation_date,
                "observation_date_commitment_sha256": canonical_sha256(
                    {"observation_date": unit.observation_date}
                ),
                "request_body_sha256": request_hashes[index],
                "output_text_sha256": output_hashes[index],
                "zero_memory": index == 1,
            }
        )
        operations.append(
            {
                "sequence": index,
                "operation_id_sha256": operation_id,
                "thread_id": f"thread-{index}",
                "turn_id": f"turn-{index}",
                "request_body_sha256": request_hashes[index],
                "output_text_sha256": output_hashes[index],
            }
        )
    config = {
        "proof_kind": "custom_loopback_process_recovery",
        "origin": f"http://127.0.0.1:{port}",
        "current_date": current_date,
        "state_dir": str(state),
        "results_dir": str(results),
        "barriers_dir": str(barriers),
        "audit_db": str(root / "adapter-audit.sqlite3"),
        "secret_paths": secret_paths,
        "request": asdict(request),
        "admission_commitment_sha256": admission.commitment_sha256,
        "authority": {
            "ingestion_manifest_sha256": authority.ingestion_manifest_sha256,
            "ingestion_root_sha256": authority.ingestion_root_sha256,
            "current_date_commitment_sha256": canonical_sha256({"current_date": current_date}),
        },
        "runtime": {
            "base_instructions_sha256": _sha("base-instructions"),
            "account_binding_hmac_sha256": _sha("account-binding"),
            "response_format_sha256": _sha("response-format"),
            "response_schema_sha256": _sha("response-schema"),
            "requested_output_tokens": 4096,
        },
        "units": units,
        "operations": operations,
    }
    config_path = root / "config.json"
    _private_write(config_path, _canonical(config))
    return config


def _load_config(root: Path) -> dict[str, Any]:
    value = json.loads((root / "config.json").read_text())
    if type(value) is not dict:
        raise RuntimeError("custom_loopback_process_recovery_config_invalid")
    return value


class _PythonReceiptHmacVerifier:
    def verify(self, *, receipt: dict[str, object], secret: str) -> None:
        raw = json.loads(json.dumps(receipt))
        metadata = raw["metadata"]
        presented = metadata.pop("receipt_hmac_sha256")
        expected = hmac.new(secret.encode(), _canonical(raw), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(presented, expected):
            raise ValueError("receipt_hmac_invalid")


def _credential_paths(config: dict[str, Any]) -> ManagedMem0V5CredentialPaths:
    values = config["secret_paths"]
    return ManagedMem0V5CredentialPaths(
        bearer_token=Path(values["bearer"]),
        evidence_key=Path(values["evidence"]),
        receipt_secret=Path(values["receipt"]),
        checkpoint_signing_key=Path(values["signing"]),
        checkpoint_head_key=Path(values["head"]),
    )


def _request(config: dict[str, Any]) -> Mem0OssAdmissionRequest:
    return Mem0OssAdmissionRequest(**config["request"])


def _receipt_authority(config: dict[str, Any]) -> Mem0V5ReceiptAuthority:
    request = _request(config)
    runtime = config["runtime"]
    return Mem0V5ReceiptAuthority(
        model=request.model,
        reasoning_effort=request.reasoning_effort,
        service_tier=request.service_tier,
        base_instructions_sha256=runtime["base_instructions_sha256"],
        runtime_source_sha256=request.runtime_source_sha256,
        route_binding_sha256=request.route_sha256,
        account_binding_hmac_sha256=runtime["account_binding_hmac_sha256"],
        response_format_type="json_schema",
        response_format_sha256=runtime["response_format_sha256"],
        response_schema_sha256=runtime["response_schema_sha256"],
        requested_output_tokens=runtime["requested_output_tokens"],
        operations=tuple(Mem0V5OperationReceiptAuthority(**item) for item in config["operations"]),
    )


def compose(root: Path):
    config = _load_config(root)
    request = _request(config)
    binding = RuntimeBindingComposition.compose_phase_c_canary().issue()
    return compose_managed_mem0_v5(
        cases=cases(),
        current_date=config["current_date"],
        request=request,
        origin=config["origin"],
        timeout_seconds=30.0,
        state_paths=ManagedMem0V5StatePaths(
            checkpoint=Path(config["state_dir"]) / "checkpoint.json",
            local_checkpoint_head=Path(config["state_dir"]) / "checkpoint-head.sqlite3",
        ),
        credential_paths=_credential_paths(config),
        runtime_receipt_boundary=RuntimeReceiptV2Boundary(_PythonReceiptHmacVerifier()),
        trusted_runtime_binding=binding,
        receipt_authority=_receipt_authority(config),
    )


class DurableLoopbackService:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.config = _load_config(root)
        self.db = Path(self.config["audit_db"])
        self._initialize()

    def _connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db, timeout=10, isolation_level=None)
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, path TEXT NOT NULL, kind TEXT NOT NULL,
                    pid INTEGER NOT NULL, detail TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS operations (
                    operation_id TEXT PRIMARY KEY, sequence INTEGER NOT NULL,
                    receipt_json TEXT NOT NULL, records_json TEXT NOT NULL,
                    dispatch_commit_count INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS cleanup (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1), receipt_json TEXT NOT NULL,
                    commit_count INTEGER NOT NULL
                );
                """
            )

    def audit(self, path: str, kind: str = "http", detail: str = "") -> None:
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO events(path,kind,pid,detail) VALUES(?,?,?,?)",
                (path, kind, os.getpid(), detail),
            )

    def _unit(self, operation_id: str) -> dict[str, Any]:
        for unit in self.config["units"]:
            if unit["operation_id_sha256"] == operation_id:
                return unit
        raise LoopbackServiceError("operation_not_found", 404)

    def admit(self, request, *, idempotency_key: str) -> dict[str, object]:
        del idempotency_key
        if request.admission_commitment_sha256 != self.config["admission_commitment_sha256"]:
            raise LoopbackServiceError("admission_invalid", 400)
        return {
            "admission_commitment_sha256": request.admission_commitment_sha256,
            "runtime_binding_commitment_sha256": _sha("adapter-runtime-binding"),
            "accepted": True,
        }

    def request_binding(self, request, *, idempotency_key: str) -> dict[str, object]:
        del idempotency_key
        unit = self._unit(request.operation_id_sha256)
        evidence = {
            "schema_version": "mem0-oss-adapter-v5.request-binding.v2",
            "admission_commitment_sha256": request.admission_commitment_sha256,
            "operation_id_sha256": request.operation_id_sha256,
            "unit_identity_sha256": unit["unit_identity_sha256"],
            "unit_sha256": unit["unit_sha256"],
            "corpus_id": unit["corpus_id"],
            "source_id": unit["source_id"],
            "source_sha256": unit["source_sha256"],
            "observation_date": unit["observation_date"],
            "observation_date_commitment_sha256": unit["observation_date_commitment_sha256"],
            "request_body_sha256": unit["request_body_sha256"],
        }
        unsigned = {
            **evidence,
            "request_binding_evidence_sha256": canonical_sha256(evidence),
        }
        return {
            **unsigned,
            "request_binding_hmac_sha256": self._evidence_hmac(unsigned, b"request-binding/v2"),
        }

    def dispatch(self, request, *, idempotency_key: str) -> dict[str, object]:
        del idempotency_key
        self.audit("internal", "dispatch_call", request.operation_id_sha256)
        unit = self._unit(request.operation_id_sha256)
        if request.request_body_sha256 != unit["request_body_sha256"]:
            raise LoopbackServiceError("request_binding_invalid", 400)
        receipt = self._runtime_receipt(unit)
        records = [] if unit["zero_memory"] else [self._record(unit)]
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT receipt_json FROM operations WHERE operation_id=?",
                (request.operation_id_sha256,),
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO operations VALUES(?,?,?,?,1)",
                    (
                        request.operation_id_sha256,
                        unit["sequence"],
                        json.dumps(receipt, sort_keys=True),
                        json.dumps(records, sort_keys=True),
                    ),
                )
                connection.execute(
                    "INSERT INTO events(path,kind,pid,detail) "
                    "VALUES('internal','dispatch_commit',?,?)",
                    (os.getpid(), request.operation_id_sha256),
                )
            connection.execute("COMMIT")
        if unit["sequence"] == 0 and not (self.root / "barriers" / "dispatch-released").exists():
            (self.root / "barriers" / "dispatch-committed").touch()
            self._wait_for(self.root / "barriers" / "dispatch-released")
        return {
            "admission_commitment_sha256": request.admission_commitment_sha256,
            "operation_id_sha256": request.operation_id_sha256,
            "runtime_receipt": receipt,
        }

    def status(self, request, *, idempotency_key: str) -> dict[str, object]:
        del idempotency_key
        self.audit("internal", "status_call", request.operation_id_sha256)
        with self._connection() as connection:
            row = connection.execute(
                "SELECT receipt_json FROM operations WHERE operation_id=?",
                (request.operation_id_sha256,),
            ).fetchone()
        if row is None:
            raise LoopbackServiceError("status_unavailable", 503)
        return {
            "admission_commitment_sha256": request.admission_commitment_sha256,
            "operation_id_sha256": request.operation_id_sha256,
            "runtime_receipt": json.loads(row[0]),
        }

    def storage_observation(self, request, *, idempotency_key: str) -> dict[str, object]:
        del idempotency_key
        unit = self._unit(request.operation_id_sha256)
        with self._connection() as connection:
            row = connection.execute(
                "SELECT records_json FROM operations WHERE operation_id=?",
                (request.operation_id_sha256,),
            ).fetchone()
        if row is None:
            raise LoopbackServiceError("run_state_invalid", 503)
        records = json.loads(row[0])
        unsigned = {
            "schema_version": "mem0-oss-adapter-v5.storage-observation.v1",
            "admission_commitment_sha256": request.admission_commitment_sha256,
            "operation_id_sha256": request.operation_id_sha256,
            "scope_sha256": unit["scope_sha256"],
            "source_id": unit["source_id"],
            "source_sha256": unit["source_sha256"],
            "storage_commitment_sha256": canonical_sha256({"records": records}),
            "record_count": len(records),
            "record_root_sha256": canonical_sha256({"records": records}),
            "records": records,
        }
        return {
            **unsigned,
            "observation_hmac_sha256": self._evidence_hmac(unsigned, b"storage-observation/v1"),
        }

    def scoped_search(self, request, *, idempotency_key: str) -> dict[str, object]:
        del idempotency_key
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT records_json FROM operations ORDER BY sequence"
            ).fetchall()
        stored = [record for row in rows for record in json.loads(row[0])]
        units = {unit["source_id"]: unit for unit in self.config["units"]}
        results = []
        for rank, record in enumerate(stored[: request.limit]):
            unit = units[record["source_id"]]
            memory = "Alice likes durable tea."
            results.append(
                {
                    "rank": rank,
                    "record_id": record["record_id"],
                    "memory": memory,
                    "memory_sha256": _sha(memory),
                    "source_id": unit["source_id"],
                    "source_sha256": unit["source_sha256"],
                    "score": 1.0,
                }
            )
        unsigned = {
            "schema_version": "mem0-oss-adapter-v5.scoped-search.v1",
            "admission_commitment_sha256": request.admission_commitment_sha256,
            "corpus_id": request.corpus_id,
            "query_commitment_sha256": canonical_sha256({"query": request.query}),
            "limit": request.limit,
            "result_count": len(results),
            "result_root_sha256": canonical_sha256({"results": results}),
            "results": results,
        }
        return {
            **unsigned,
            "search_hmac_sha256": self._evidence_hmac(unsigned, b"scoped-search/v1"),
        }

    def cleanup(self, request, *, idempotency_key: str) -> dict[str, object]:
        del idempotency_key
        self.audit("internal", "cleanup_call", request.admission_commitment_sha256)
        payload = {
            "admission_commitment_sha256": request.admission_commitment_sha256,
            "seal_commitment_sha256": request.seal_commitment_sha256,
            "operation_root_sha256": request.operation_root_sha256,
            "operation_inventory_root_sha256": request.operation_inventory_root_sha256,
            "deleted_operation_count": request.expected_operation_count,
            "residual_record_count": 0,
            "residual_root_sha256": hashlib.sha256(b"").hexdigest(),
        }
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT receipt_json FROM cleanup WHERE singleton=1"
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO cleanup VALUES(1,?,1)",
                    (json.dumps(payload, sort_keys=True),),
                )
                connection.execute(
                    "INSERT INTO events(path,kind,pid,detail) "
                    "VALUES('internal','cleanup_commit',?,'once')",
                    (os.getpid(),),
                )
            elif json.loads(row[0]) != payload:
                raise LoopbackServiceError("cleanup_conflict")
            connection.execute("COMMIT")
        barrier = self.root / "barriers"
        if not (barrier / "cleanup-released").exists():
            (barrier / "cleanup-committed").touch()
            self._wait_for(barrier / "cleanup-released")
        return payload

    def _runtime_receipt(self, unit: dict[str, Any]) -> dict[str, object]:
        runtime = self.config["runtime"]
        operation = self.config["operations"][unit["sequence"]]
        raw = {
            "metadata": {
                "schema_version": 2,
                "attestation_level": "provider_receipt",
                "usage_source": "codex_thread_token_usage_updated",
                "runtime_selection": {
                    "account_binding_hmac_sha256": runtime["account_binding_hmac_sha256"],
                    "thread_id": operation["thread_id"],
                    "turn_id": operation["turn_id"],
                    "model": "gpt-5.6-sol",
                    "model_provider": "openai",
                    "reasoning_effort": "medium",
                    "service_tier": "priority",
                    "execution_profile": "stateless-completion",
                    "base_instructions_sha256": runtime["base_instructions_sha256"],
                },
                "request_identity": {
                    "public_model": "gpt-5.6-sol",
                    "client_requested_model": "gpt-5.6-sol",
                    "configured_codex_model": "gpt-5.6-sol",
                    "requested_codex_model": "gpt-5.6-sol",
                    "request_body_sha256": unit["request_body_sha256"],
                    "response_format_type": "json_schema",
                    "response_format_sha256": runtime["response_format_sha256"],
                    "response_schema_sha256": runtime["response_schema_sha256"],
                },
                "output_identity": {
                    "output_text_sha256": unit["output_text_sha256"],
                    "terminal_status": "completed",
                },
                "output_token_limit": {
                    "requested_tokens": runtime["requested_output_tokens"],
                    "enforced": False,
                },
            },
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        }
        signature = hmac.new(SECRETS["receipt"], _canonical(raw), hashlib.sha256).hexdigest()
        raw["metadata"]["receipt_hmac_sha256"] = signature
        return raw

    @staticmethod
    def _record(unit: dict[str, Any]) -> dict[str, object]:
        memory = "Alice likes durable tea."
        return {
            "record_id": f"record-{unit['sequence']}",
            "extraction_memory_id": "0",
            "source_id": unit["source_id"],
            "source_sha256": unit["source_sha256"],
            "memory_sha256": _sha(memory),
        }

    @staticmethod
    def _wait_for(path: Path) -> None:
        deadline = time.monotonic() + 30
        while not path.exists():
            if time.monotonic() >= deadline:
                raise RuntimeError("custom_loopback_process_recovery_barrier_timeout")
            time.sleep(0.02)

    @staticmethod
    def _evidence_hmac(payload: dict[str, object], domain: bytes) -> str:
        root = hmac.new(SECRETS["evidence"], EVIDENCE_KEY_DOMAIN, hashlib.sha256).digest()
        key = hmac.new(root, domain, hashlib.sha256).digest()
        return hmac.new(key, _canonical(payload), hashlib.sha256).hexdigest()


def adapter_main(root: Path, port: int) -> None:
    import uvicorn

    service = DurableLoopbackService(root)
    app = FastAPI()

    @app.exception_handler(LoopbackServiceError)
    async def loopback_error(_request: Request, exc: LoopbackServiceError):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.code})

    @app.middleware("http")
    async def audit_http(request, call_next):
        service.audit(request.url.path)
        response = await call_next(request)
        service.audit("internal", "http_response", f"{request.url.path}:{response.status_code}")
        return response

    @app.get("/health")
    async def health():
        return {
            "ok": True,
            "service": "managed-v5-test-loopback",
            "provider_calls": "dispatch_only",
        }

    handlers = {
        "/v5/runs/admit": service.admit,
        "/v5/operations/request-binding": service.request_binding,
        "/v5/operations/dispatch": service.dispatch,
        "/v5/operations/status": service.status,
        "/v5/operations/storage-observation": service.storage_observation,
        "/v5/runs/search": service.scoped_search,
        "/v5/runs/cleanup": service.cleanup,
    }

    async def invoke(path: str, request: Request):
        body = await request.json()
        expected_bearer = "Bearer " + SECRETS["bearer"].decode()
        if request.headers.get("authorization") != expected_bearer:
            return JSONResponse(status_code=401, content={"detail": "invalid_authentication"})
        commitment = request.headers.get("x-request-commitment-sha256")
        if commitment != hashlib.sha256(_canonical(body)).hexdigest():
            return JSONResponse(
                status_code=400,
                content={"detail": "request_commitment_invalid"},
            )
        result = handlers[path](
            SimpleNamespace(**body),
            idempotency_key=str(request.headers.get("idempotency-key")),
        )
        return JSONResponse(content=result)

    def route_for(endpoint: str):
        async def route(request: Request):
            return await invoke(endpoint, request)

        return route

    for endpoint in handlers:
        app.add_api_route(endpoint, route_for(endpoint), methods=["POST"])

    uvicorn.run(app, host="127.0.0.1", port=port, access_log=False, log_level="warning")


def _write_result(root: Path, name: str, payload: object) -> None:
    target = root / "results" / f"custom-loopback-{name}"
    target.write_bytes(_canonical(payload))
    os.chmod(target, 0o600)


def runner_main(root: Path, mode: str) -> None:
    _write_result(root, f"pid-{mode}.json", {"pid": os.getpid()})
    bundle = compose(root)
    policy = ManagedMem0V5BudgetPolicy(100)
    coordinator = bundle.coordinator
    if mode == "dispatch-a":
        coordinator.admit(authority=bundle.authority, request=bundle.request, budget_policy=policy)
        coordinator.dispatch_pending()
        raise AssertionError("dispatch response was expected to remain withheld")
    checkpoint = coordinator.restore(
        authority=bundle.authority,
        request=bundle.request,
        budget_policy=policy,
    )
    if mode == "finish":
        seal = coordinator.dispatch_pending()
        lane = coordinator._lane
        search = lane.search(
            admission=coordinator._service.admission,
            corpus_id=bundle.authority.units[0].corpus_id,
            query="durable tea",
            limit=5,
        )
        _write_result(root, "seal.json", seal.payload())
        _write_result(
            root,
            "search.json",
            {
                "count": len(search.records),
                "source_ids": [item.source_id for item in search.records],
                "record_ids": [item.record_id for item in search.records],
            },
        )
    elif mode == "cleanup-a":
        if checkpoint.run_phase.value != "sealed":
            raise AssertionError("sealed checkpoint required")
        coordinator.cleanup()
        raise AssertionError("cleanup response was expected to remain withheld")
    elif mode in {"cleanup-b", "terminal-c"}:
        terminal = coordinator.terminal_evidence
        _write_result(root, f"terminal-{mode}.json", terminal.public_payload())
    else:
        raise ValueError("custom_loopback_process_recovery_mode_invalid")


def _main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("role", choices=("adapter", "runner"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--port", type=int)
    parser.add_argument("--mode")
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    if args.role == "adapter":
        adapter_main(args.root, int(args.port))
    else:
        runner_main(args.root, str(args.mode))


if __name__ == "__main__":
    _main()

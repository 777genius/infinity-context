from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from mem0.memory.storage import SQLiteManager

from mem0_oss_adapter_v5.app import create_app
from mem0_oss_adapter_v5.clean_state import verify_clean_state_response
from mem0_oss_adapter_v5.composition import V5AdapterService
from mem0_oss_adapter_v5.domain import canonical_sha256
from mem0_oss_adapter_v5.http_models import CleanStateResponse
from mem0_oss_adapter_v5.mem0_storage import (
    Mem0StorageAdapter,
    PinnedMem0Backend,
    StorageMemory,
    StorageScope,
    independent_snapshot,
)
from mem0_oss_adapter_v5.sealed_manifest import SealedInputManifest
from mem0_oss_adapter_v5.source_authority import _issue_verified_source_authority
from mem0_oss_adapter_v5.state_sqlite import SqliteOperationState
from mem0_oss_adapter_v5.subscription_runtime import (
    SUBSCRIPTION_RUNTIME_ROUTE_SHA256,
    SUBSCRIPTION_RUNTIME_TRANSPORT_ORIGIN_SHA256,
)

_TOKEN = "t" * 32
_KEY = b"clean-state-result-key" * 2
_RUNTIME_SOURCE = hashlib.sha256(b"runtime-source").hexdigest()
_EMPTY = hashlib.sha256(b"").hexdigest()


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _headers(body: dict[str, object], *, request_id: str = "clean-request") -> dict[str, str]:
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return {
        "Authorization": "Bearer " + _TOKEN,
        "Idempotency-Key": _sha(request_id),
        "X-Request-Commitment-SHA256": hashlib.sha256(encoded).hexdigest(),
    }


class _NoProviderRuntime:
    calls = 0

    def extract(self, *_args: object, **_kwargs: object) -> object:
        self.calls += 1
        raise AssertionError("provider call is forbidden")


class _UnusedReceiptAuthority:
    def verify(self, **_kwargs: object) -> str:
        raise AssertionError("receipt verification is forbidden")


class _ReadbackBackend:
    def __init__(self) -> None:
        self.vectors: list[dict[str, object]] = []
        self.list_calls: list[dict[str, str]] = []
        self.write_calls = 0

    def add_raw(self, *, scope: StorageScope, memory: StorageMemory) -> str:
        self.write_calls += 1
        raise AssertionError("provider write is forbidden")

    def list_vectors(self, *, filters, limit: int):
        assert limit == 10_000
        exact = dict(filters)
        self.list_calls.append(exact)
        return [
            row
            for row in self.vectors
            if all(row["payload"].get(key) == value for key, value in exact.items())
        ]

    def history_memory_ids(self, *, provider_memory_ids):
        return tuple(sorted(provider_memory_ids))

    def isolated_history_record_count(self) -> int:
        return 0

    def message_ids(self, *, scope: StorageScope):
        return ()

    def entity_links(self, *, scope: StorageScope):
        return ()

    def delete_memory(self, provider_memory_id: str) -> None:
        raise AssertionError("provider delete is forbidden")

    def delete_history(self, provider_memory_ids) -> None:
        raise AssertionError("provider delete is forbidden")

    def delete_messages(self, *, scope: StorageScope) -> None:
        raise AssertionError("provider delete is forbidden")

    def delete_entity_links(self, *, scope: StorageScope) -> None:
        raise AssertionError("provider delete is forbidden")


class _EmptyPinnedStore:
    def list(self, **_kwargs: object) -> tuple[list[object], None]:
        return [], None


class _PinnedReadbackMemory:
    def __init__(self, db: SQLiteManager) -> None:
        self.db = db
        self.vector_store = _EmptyPinnedStore()
        self.entity_store = _EmptyPinnedStore()

    def add(self) -> None:
        raise AssertionError("provider write is forbidden")

    def delete(self) -> None:
        raise AssertionError("provider delete is forbidden")


def _manifest(
    tmp_path: Path,
) -> tuple[SealedInputManifest, dict[str, object], list[dict[str, object]]]:
    units = []
    for sequence, (corpus_id, source_id) in enumerate(
        (("corpus-a", "source-1"), ("corpus-a", "source-2"), ("corpus-b", "source-3"))
    ):
        messages = [{"role": "user", "content": f"private source content {sequence}"}]
        unit_sha = canonical_sha256({"source_messages": messages})
        source_sha = _sha(f"canonical-source-{sequence}")
        scope_sha = canonical_sha256(
            {
                "corpus_id": corpus_id,
                "source_id": source_id,
                "source_sha256": source_sha,
                "unit_sha256": unit_sha,
            }
        )
        units.append(
            {
                "sequence": sequence,
                "unit_identity_sha256": canonical_sha256(
                    {
                        "sequence": sequence,
                        "scope_sha256": scope_sha,
                        "unit_sha256": unit_sha,
                    }
                ),
                "unit_sha256": unit_sha,
                "source_sha256": source_sha,
                "scope_sha256": scope_sha,
                "corpus_id": corpus_id,
                "source_id": source_id,
                "observation_date": "2026-08-06",
                "source_messages": messages,
            }
        )
    root = canonical_sha256(
        {
            "units": [
                {
                    "unit_identity_sha256": item["unit_identity_sha256"],
                    "unit_sha256": item["unit_sha256"],
                    "scope_sha256": item["scope_sha256"],
                }
                for item in units
            ]
        }
    )
    current_date = "2026-08-07"
    manifest_sha = canonical_sha256({"current_date": current_date, "ingestion_root_sha256": root})
    unsigned = {
        "schema_version": "mem0-oss-adapter-v5.sealed-input.v2",
        "ingestion_manifest_sha256": manifest_sha,
        "ingestion_root_sha256": root,
        "current_date": current_date,
        "units": units,
    }
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps({**unsigned, "sealed_payload_sha256": canonical_sha256(unsigned)}),
        encoding="utf-8",
    )
    path.chmod(0o400)
    return SealedInputManifest(path), unsigned, units


def _scopes(admission: str, units: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[str, list[dict[str, object]]] = {}
    for unit in units:
        grouped.setdefault(str(unit["corpus_id"]), []).append(unit)
    result = []
    for corpus_id, corpus_units in grouped.items():
        source_root = canonical_sha256(
            {
                "source_scopes": [
                    {
                        "source_id": item["source_id"],
                        "source_sha256": item["source_sha256"],
                    }
                    for item in corpus_units
                ]
            }
        )
        result.append(
            {
                "corpus_identity_sha256": canonical_sha256({"corpus_id": corpus_id}),
                "scope_identity_sha256": canonical_sha256(
                    {
                        "admission_commitment_sha256": admission,
                        "corpus_id": corpus_id,
                        "source_scope_root_sha256": source_root,
                    }
                ),
                "source_scope_count": len(corpus_units),
                "residual_record_count": 0,
                "residual_root_sha256": _EMPTY,
            }
        )
    return result


def _rig(tmp_path: Path, *, backend: object | None = None):
    manifest, unsigned, units = _manifest(tmp_path)
    backend = backend or _ReadbackBackend()
    state = SqliteOperationState(tmp_path / "state.sqlite3", hmac_key=b"s" * 32)
    runtime = _NoProviderRuntime()
    source_authority = _issue_verified_source_authority(
        source_commit_sha1="1" * 40,
        source_tree_sha1="2" * 40,
        manifest_sha256=_sha("source-manifest"),
        closure_sha256=_sha("source-closure"),
        phase_c_infinity_commit_sha1="3" * 40,
        phase_c_infinity_tree_sha1="4" * 40,
        phase_c_release_manifest_sha256=_sha("phase-release"),
    )
    runtime_binding = _sha("runtime-binding")
    runtime_route = _sha("runtime-route")
    service = V5AdapterService(
        manifest=manifest,
        state=state,
        runtime=runtime,
        receipt_authority=_UnusedReceiptAuthority(),
        expected_account_binding_hmac_sha256=_sha("account"),
        expected_base_instructions_sha256=_sha("base-instructions"),
        storage=Mem0StorageAdapter(backend),
        receipt_directory=tmp_path / "receipts",
        result_hmac_key=_KEY,
        source_authority=source_authority,
        runtime_binding_commitment_sha256=runtime_binding,
        runtime_source_sha256=_RUNTIME_SOURCE,
        runtime_route_binding_sha256=runtime_route,
        runtime_transport_origin_sha256=SUBSCRIPTION_RUNTIME_TRANSPORT_ORIGIN_SHA256,
    )
    implementation_runtime = source_authority.binding_commitment(
        route_sha256=SUBSCRIPTION_RUNTIME_ROUTE_SHA256,
        runtime_binding_commitment_sha256=runtime_binding,
        runtime_source_sha256=_RUNTIME_SOURCE,
        runtime_route_binding_sha256=runtime_route,
        runtime_transport_origin_sha256=SUBSCRIPTION_RUNTIME_TRANSPORT_ORIGIN_SHA256,
    )
    identity = {
        "run_id_sha256": _sha("run-1"),
        "credential_binding_sha256": _sha("credential"),
        "runtime_source_revision": "revision-1",
        "runtime_source_sha256": _RUNTIME_SOURCE,
        "runtime_base_sha256": _sha("runtime-base"),
    }
    admission_public = {
        "schema_version": "mem0-benchmark-full-run.v5",
        "run_id_sha256": identity["run_id_sha256"],
        "ingestion_manifest_sha256": unsigned["ingestion_manifest_sha256"],
        "ingestion_root_sha256": unsigned["ingestion_root_sha256"],
        "ingestion_unit_count": len(units),
        "route_sha256": SUBSCRIPTION_RUNTIME_ROUTE_SHA256,
        "credential_binding_sha256": identity["credential_binding_sha256"],
        "model": "gpt-5.6-sol",
        "reasoning_effort": "high",
        "service_tier": "default",
        "runtime_source_revision": identity["runtime_source_revision"],
        "runtime_source_sha256": identity["runtime_source_sha256"],
        "runtime_base_sha256": identity["runtime_base_sha256"],
        "expected_operation_count": len(units),
        "retries": 0,
        "extraction_calls_per_unit": 1,
    }
    admission = canonical_sha256(admission_public)
    authority = canonical_sha256(
        {
            "schema_version": "managed-mem0-v5-manifest.v1",
            "case_count": 3,
            "corpus_count": 2,
            "operation_count": len(units),
            "ingestion_manifest_sha256": unsigned["ingestion_manifest_sha256"],
            "ingestion_root_sha256": unsigned["ingestion_root_sha256"],
            "sealed_payload_sha256": canonical_sha256(unsigned),
        }
    )
    clean = {
        "schema_version": "mem0-oss-adapter-v5.clean-state-request.v1",
        "admission_commitment_sha256": admission,
        **identity,
        "authority_commitment_sha256": authority,
        "manifest_case_count": 3,
        "runtime_binding_commitment_sha256": implementation_runtime,
        "scopes": _scopes(admission, units),
    }
    client = TestClient(create_app(service=service, bearer_token=_TOKEN))
    admit = {
        "admission_commitment_sha256": admission,
        "ingestion_manifest_sha256": unsigned["ingestion_manifest_sha256"],
        "ingestion_root_sha256": unsigned["ingestion_root_sha256"],
        "expected_operation_count": len(units),
        "route_sha256": SUBSCRIPTION_RUNTIME_ROUTE_SHA256,
    }
    assert client.post("/v5/runs/admit", json=admit, headers=_headers(admit)).status_code == 200
    return client, service, state, backend, runtime, clean, units


def test_clean_state_http_reads_every_exact_scope_and_signs_ordered_zero_inventory(
    tmp_path: Path,
) -> None:
    client, _service, state, backend, runtime, body, units = _rig(tmp_path)
    headers = _headers(body)
    response = client.post("/v5/runs/clean-state", json=body, headers=headers)

    assert response.status_code == 200
    payload = response.json()
    witness = CleanStateResponse.model_validate(payload)
    assert verify_clean_state_response(witness, hmac_key=_KEY)
    assert not verify_clean_state_response(
        witness.model_copy(update={"run_id_sha256": _sha("tampered-run")}),
        hmac_key=_KEY,
    )
    assert not verify_clean_state_response(
        witness.model_copy(update={"scopes": tuple(reversed(witness.scopes))}),
        hmac_key=_KEY,
    )
    assert payload["scopes"] == body["scopes"]
    assert payload["scope_count"] == 2
    assert payload["request_commitment_sha256"] == headers["X-Request-Commitment-SHA256"]
    assert payload["request_id_sha256"] == headers["Idempotency-Key"]
    assert backend.list_calls == [
        {
            "user_id": item["corpus_id"],
            "run_id": body["admission_commitment_sha256"],
            "source_id": item["source_id"],
            "source_sha256": item["source_sha256"],
        }
        for item in units
    ]
    assert runtime.calls == backend.write_calls == 0
    durable = (tmp_path / "receipts" / "clean-state.json").read_text(encoding="utf-8")
    assert "private source content" not in durable
    assert _TOKEN not in durable
    state.close()


@pytest.mark.parametrize(
    ("mutation", "status"),
    (
        (lambda body: body.update(run_id_sha256=_sha("wrong-run")), 400),
        (lambda body: body.update(admission_commitment_sha256=_sha("wrong-admission")), 404),
        (lambda body: body.update(authority_commitment_sha256=_sha("wrong-authority")), 400),
        (lambda body: body.update(runtime_binding_commitment_sha256=_sha("wrong-runtime")), 400),
        (lambda body: body.update(credential_binding_sha256=_sha("wrong-credential")), 400),
        (lambda body: body.update(scopes=body["scopes"][:-1]), 400),
        (lambda body: body.update(scopes=list(reversed(body["scopes"]))), 400),
    ),
)
def test_clean_state_rejects_wrong_bindings_and_incomplete_or_reordered_scopes(
    tmp_path: Path, mutation, status: int
) -> None:
    client, _service, state, backend, runtime, body, _units = _rig(tmp_path)
    mutation(body)
    response = client.post("/v5/runs/clean-state", json=body, headers=_headers(body))
    assert response.status_code == status
    assert backend.list_calls == []
    assert runtime.calls == 0
    state.close()


def test_clean_state_rejects_duplicate_scopes_and_wrong_http_request_binding(
    tmp_path: Path,
) -> None:
    client, _service, state, backend, _runtime, body, _units = _rig(tmp_path)
    duplicate = {**body, "scopes": [body["scopes"][0], body["scopes"][0]]}
    assert (
        client.post("/v5/runs/clean-state", json=duplicate, headers=_headers(duplicate)).status_code
        == 422
    )
    headers = _headers(body)
    headers["X-Request-Commitment-SHA256"] = _sha("wrong-request")
    assert client.post("/v5/runs/clean-state", json=body, headers=headers).status_code == 400
    assert backend.list_calls == []
    state.close()


def test_clean_state_is_one_shot_and_never_replays_cached_pass1_evidence(tmp_path: Path) -> None:
    client, _service, state, backend, runtime, body, units = _rig(tmp_path)
    assert (
        client.post(
            "/v5/runs/clean-state", json=body, headers=_headers(body, request_id="pass-1")
        ).status_code
        == 200
    )
    first_calls = len(backend.list_calls)
    replay = client.post(
        "/v5/runs/clean-state", json=body, headers=_headers(body, request_id="pass-2")
    )
    assert replay.status_code == 409
    assert replay.json() == {"detail": "clean_state_conflict"}
    assert first_calls == len(units) == len(backend.list_calls)
    assert runtime.calls == 0
    state.close()


def test_managed_runner_client_crosses_real_fastapi_service_and_sqlite_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository_root = Path(__file__).resolve().parents[3]
    monkeypatch.syspath_prepend(str(repository_root / "packages" / "infinity_context_core"))
    monkeypatch.syspath_prepend(str(repository_root / "packages" / "infinity_context_server"))
    from infinity_context_server.memory_comparison_bounded_httpx_transport import (
        BoundedHttpResponse,
    )
    from infinity_context_server.memory_comparison_managed_mem0_v5_http_lane import (
        HmacSha256ManagedMem0V5EvidenceVerifier,
    )
    from infinity_context_server.memory_comparison_managed_mem0_v5_storage_witness import (
        create_managed_mem0_v5_storage_witness_authority,
    )
    from infinity_context_server.memory_comparison_mem0_oss_v5_http import (
        Mem0V5CleanStateRequest,
        Mem0V5CleanStateScope,
        Mem0V5HttpError,
        Mem0V5HttpPort,
    )

    client, service, state, backend, runtime, body, units = _rig(tmp_path)
    scopes = tuple(Mem0V5CleanStateScope(**item) for item in body["scopes"])
    request = Mem0V5CleanStateRequest(
        body["admission_commitment_sha256"],
        body["run_id_sha256"],
        body["authority_commitment_sha256"],
        body["manifest_case_count"],
        body["credential_binding_sha256"],
        body["runtime_source_revision"],
        body["runtime_source_sha256"],
        body["runtime_base_sha256"],
        body["runtime_binding_commitment_sha256"],
        scopes,
        canonical_sha256({"kind": "clean-state", "binding": body["admission_commitment_sha256"]}),
    )

    class Transport:
        def request(self, method: str, url: str, **values: object):
            assert method == "POST"
            response = client.post(
                url.removeprefix("http://127.0.0.1:19091"),
                content=values["content"],
                headers=values["headers"],
            )
            return BoundedHttpResponse(response.status_code, response.content)

    class EvidenceKey:
        def validate(self) -> None:
            return None

        def consume(self) -> bytes:
            return _KEY

    storage_issuer, _storage_verifier = create_managed_mem0_v5_storage_witness_authority()
    evidence_verifier = HmacSha256ManagedMem0V5EvidenceVerifier(
        key_capability=EvidenceKey(),
        storage_witness_issuer=storage_issuer,
    )
    port = Mem0V5HttpPort(
        origin="http://127.0.0.1:19091",
        bearer_token=_TOKEN,
        timeout_seconds=1,
        transport=Transport(),
    )
    receipt = port.clean_state(request)
    verified = evidence_verifier.verify_clean_state(
        receipt=receipt,
        request=request,
        ingestion_manifest_sha256=service._manifest.ingestion_manifest_sha256,
        ingestion_root_sha256=service._manifest.ingestion_root_sha256,
    )

    assert verified == scopes
    first_readbacks = len(backend.list_calls)

    with pytest.raises(Mem0V5HttpError, match="remote_failed"):
        port.clean_state(request)

    assert first_readbacks == len(units) == len(backend.list_calls)
    assert runtime.calls == 0
    state.close()


def test_clean_state_rejects_post_dispatch_state_without_readback(tmp_path: Path) -> None:
    client, _service, state, backend, runtime, body, units = _rig(tmp_path)
    state.reserve(str(units[0]["unit_identity_sha256"]))
    response = client.post("/v5/runs/clean-state", json=body, headers=_headers(body))
    assert response.status_code == 409
    assert response.json() == {"detail": "clean_state_conflict"}
    assert backend.list_calls == []
    assert runtime.calls == 0
    state.close()


def test_clean_state_rejects_any_real_storage_residual(tmp_path: Path) -> None:
    client, _service, state, backend, runtime, body, units = _rig(tmp_path)
    first = units[0]
    backend.vectors.append(
        {
            "id": "residual-provider-id",
            "payload": {
                "user_id": first["corpus_id"],
                "run_id": body["admission_commitment_sha256"],
                "source_id": first["source_id"],
                "source_sha256": first["source_sha256"],
                "extraction_memory_id": "residual-extraction-id",
                "memory": "private residual memory",
                "attributed_to": "user",
                "linked_memory_ids": [],
            },
        }
    )
    response = client.post("/v5/runs/clean-state", json=body, headers=_headers(body))
    assert response.status_code == 409
    assert response.json() == {"detail": "clean_state_not_empty"}
    assert "private residual memory" not in response.text
    assert runtime.calls == backend.write_calls == 0
    state.close()


def test_clean_state_rejects_orphan_real_sqlite_history_without_vectors(tmp_path: Path) -> None:
    manager = SQLiteManager(str(tmp_path / "mem0-history.sqlite"))
    backend = PinnedMem0Backend(_PinnedReadbackMemory(manager))
    manager.add_history("orphan-provider-id", None, "private orphan history", "ADD")
    client, _service, state, _backend, runtime, body, units = _rig(
        tmp_path,
        backend=backend,
    )
    first = units[0]
    scope = StorageScope(
        user_id=str(first["corpus_id"]),
        run_id=str(body["admission_commitment_sha256"]),
        source_id=str(first["source_id"]),
        source_sha256=str(first["source_sha256"]),
    )
    try:
        assert independent_snapshot(backend, scope=scope).empty
        assert backend.isolated_history_record_count() == 1

        response = client.post("/v5/runs/clean-state", json=body, headers=_headers(body))

        assert response.status_code == 409
        assert response.json() == {"detail": "clean_state_not_empty"}
        assert "private orphan history" not in response.text
        assert not (tmp_path / "receipts" / "clean-state.json").exists()
        assert runtime.calls == 0
    finally:
        state.close()
        manager.close()

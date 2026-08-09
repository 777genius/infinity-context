from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from functools import partial
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from infinity_context_adapters.qdrant.identity_evidence import (
    qdrant_target_commitment_sha256,
)
from infinity_context_core.ports.adapters import VectorWriteResult
from infinity_context_core.ports.benchmark_cleanup_plan import (
    CLEANUP_PLAN_LIMITS_POLICY_SHA256,
    CLEANUP_PLAN_SCHEMA_VERSION,
    COGNEE_NOT_PROJECTED_POLICY_SHA256,
    INFINITY_NAMESPACE_POLICY_SHA256,
    ManagedBenchmarkCleanupPlan,
    ManagedBenchmarkCleanupTargetAuthority,
    managed_benchmark_cleanup_plan_material_sha256,
    validate_managed_benchmark_cleanup_plan,
    validate_managed_benchmark_cleanup_target_authority,
)
from infinity_context_core.ports.benchmark_managed_ingest import (
    managed_benchmark_fact_operation_material,
    managed_benchmark_fact_source_ref_descriptor,
    managed_benchmark_infinity_operation_sha256,
    managed_benchmark_text_sha256,
)
from infinity_context_core.ports.benchmark_unsealed_projection import (
    BenchmarkProjectionPassReceipt,
)
from infinity_context_server import derived_provider_composition
from infinity_context_server.config import DeployProfile, Settings
from infinity_context_server.derived_identity_target import (
    graphiti_target_commitment_sha256,
)
from infinity_context_server.main import create_app
from infinity_context_server.worker import OutboxWorker, OutboxWorkerFilter
from infinity_context_server_harness import PROJECT_ROOT
from sqlalchemy.engine import make_url

RUN = "a" * 64
BINDING = "b" * 64
TARGET = "c" * 64
SPACE_SLUG = "memory-comparison-app-sqlite-abort"
REGISTER_KEY = "sandbox-register-idempotency"
CLEANUP_KEY = "sandbox-cleanup-idempotency"
ABORT_KEY = "sandbox-abort-idempotency"
SCOPE_REF = "e2e-corpus"
THREAD_REF = "e2e-thread"
FACT_SOURCE = "e2e-fact-source"
FACT_TEXT = "The benchmark abort fixture binds one exact fact."


def test_app_postgres_registry_abort_recovers_and_replays_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _isolated_postgres_database() as database_url:
        token = "sandbox-postgres-admin-token"
        with _provider_free_test_client(
            monkeypatch,
            database_url=database_url,
            token=token,
        ) as client:
            authority_response = client.post(
                "/v1/internal/memory-comparison/runs/cleanup-target-authority",
                json={
                    "schema_version": ("memory-comparison-cleanup-target-authority-request.v1"),
                    "infinity_target_identity_sha256": TARGET,
                },
            )
            assert authority_response.status_code == 200, authority_response.text
            target_authority = validate_managed_benchmark_cleanup_target_authority(
                authority_response.json()["data"],
                infinity_target_identity_sha256=TARGET,
            )
            cleanup_plan = _cleanup_plan(TARGET, target_authority)
            registered = client.post(
                "/v1/internal/memory-comparison/runs",
                json={
                    "schema_version": "memory-comparison-run-registration.v2",
                    "run_id_sha256": RUN,
                    "binding_commitment_sha256": BINDING,
                    "infinity_target_identity_sha256": TARGET,
                    "space_slug": SPACE_SLUG,
                    "cleanup_plan": cleanup_plan.value,
                    "cleanup_plan_sha256": cleanup_plan.sha256,
                },
                headers={"Idempotency-Key": REGISTER_KEY},
            )
            assert registered.status_code == 201, registered.text
            registration = registered.json()["data"]
            assert registration["created"] is True
            assert registration["cleanup_plan_state"] == "sealed"

            fact = client.post(
                "/v1/facts",
                json={
                    "space_slug": SPACE_SLUG,
                    "memory_scope_external_ref": SCOPE_REF,
                    "thread_external_ref": THREAD_REF,
                    "text": FACT_TEXT,
                    "kind": "requirement",
                    "source_refs": [
                        {
                            "source_type": "memory_comparison_benchmark",
                            "source_id": FACT_SOURCE,
                            "quote_preview": FACT_TEXT,
                        }
                    ],
                },
            )
            assert fact.status_code == 201, fact.text

            cleanup = client.request(
                "DELETE",
                f"/v1/internal/memory-comparison/runs/{RUN}",
                json={
                    "schema_version": "memory-comparison-run-cleanup.v2",
                    "binding_commitment_sha256": BINDING,
                    "infinity_target_identity_sha256": TARGET,
                    "space_id": registration["space_id"],
                    "space_slug": SPACE_SLUG,
                    "cleanup_plan_sha256": cleanup_plan.sha256,
                },
                headers={"Idempotency-Key": CLEANUP_KEY},
            )
            assert cleanup.status_code == 200, cleanup.text
            initiation = cleanup.json()["data"]
            assert initiation["projection_cleanup"] == "blocked"
            worker = OutboxWorker(
                client.app.state.container,
                worker_filter=OutboxWorkerFilter(workload_classes=("projection",)),
            )
            processed = [client.portal.call(partial(worker.run_once, limit=10)) for _ in range(3)]
            assert processed[0] >= 1

            abort_payload = {
                "schema_version": "memory-comparison-run-abort-finalize.v2",
                "binding_commitment_sha256": BINDING,
                "infinity_target_identity_sha256": TARGET,
                "space_id": registration["space_id"],
                "space_slug": SPACE_SLUG,
                "receipt_sha256": initiation["receipt_sha256"],
                "cleanup_plan_sha256": cleanup_plan.sha256,
            }
            aborted = client.post(
                f"/v1/internal/memory-comparison/runs/{RUN}/cleanup/abort/finalize",
                json=abort_payload,
                headers={"Idempotency-Key": ABORT_KEY},
            )
            assert aborted.status_code == 200, aborted.text
            terminal = aborted.json()["data"]
            assert terminal["state"] == "cleanup_aborted"
            assert terminal["replayed"] is False

            lifecycle_response = client.get(f"/v1/internal/memory-comparison/runs/{RUN}/cleanup")
            assert lifecycle_response.status_code == 200, lifecycle_response.text
            lifecycle = lifecycle_response.json()["data"]
            assert lifecycle["state"] == "cleanup_aborted"
            assert lifecycle["projection_cleanup_state"] == "unsealed_abort_complete"
            assert lifecycle["cleanup_plan_sha256"] == cleanup_plan.sha256
            assert lifecycle["completion_receipt"]["receipt_sha256"] == terminal["receipt_sha256"]

            replay = client.post(
                f"/v1/internal/memory-comparison/runs/{RUN}/cleanup/abort/finalize",
                json=abort_payload,
                headers={"Idempotency-Key": ABORT_KEY},
            )
            assert replay.status_code == 200, replay.text
            replayed = replay.json()["data"]
            assert replayed["replayed"] is True
            assert replayed["receipt_sha256"] == terminal["receipt_sha256"]


def test_app_sqlite_registry_unsealed_abort_persists_and_replays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_name = "benchmark-registry-abort.db"
    token = "sandbox-admin-token"

    with (
        _sqlite_test_client(
            monkeypatch,
            tmp_path,
            token=token,
            database_name=database_name,
        ) as client,
    ):
        authority_response = client.post(
            "/v1/internal/memory-comparison/runs/cleanup-target-authority",
            json={
                "schema_version": ("memory-comparison-cleanup-target-authority-request.v1"),
                "infinity_target_identity_sha256": TARGET,
            },
        )
        assert authority_response.status_code == 200, authority_response.text
        target_authority = validate_managed_benchmark_cleanup_target_authority(
            authority_response.json()["data"],
            infinity_target_identity_sha256=TARGET,
        )
        cleanup_plan = _cleanup_plan(TARGET, target_authority)
        registration_payload = {
            "schema_version": "memory-comparison-run-registration.v2",
            "run_id_sha256": RUN,
            "binding_commitment_sha256": BINDING,
            "infinity_target_identity_sha256": TARGET,
            "space_slug": SPACE_SLUG,
            "cleanup_plan": cleanup_plan.value,
            "cleanup_plan_sha256": cleanup_plan.sha256,
        }
        registered = client.post(
            "/v1/internal/memory-comparison/runs",
            json=registration_payload,
            headers={"Idempotency-Key": REGISTER_KEY},
        )
        assert registered.status_code == 201, registered.text
        registration = registered.json()["data"]
        assert registration["created"] is True
        assert registration["state"] == "active"
        assert registration["run_id_sha256"] == RUN
        assert registration["binding_commitment_sha256"] == BINDING
        assert registration["infinity_target_identity_sha256"] == TARGET
        assert registration["cleanup_plan_sha256"] == cleanup_plan.sha256
        assert registration["cleanup_plan_state"] == "sealed"

        space_id = registration["space_id"]
        fact = client.post(
            "/v1/facts",
            json={
                "space_slug": SPACE_SLUG,
                "memory_scope_external_ref": SCOPE_REF,
                "thread_external_ref": THREAD_REF,
                "text": FACT_TEXT,
                "kind": "requirement",
                "source_refs": [
                    {
                        "source_type": "memory_comparison_benchmark",
                        "source_id": FACT_SOURCE,
                        "quote_preview": FACT_TEXT,
                    }
                ],
            },
        )
        assert fact.status_code == 201, fact.text
        cleanup = client.request(
            "DELETE",
            f"/v1/internal/memory-comparison/runs/{RUN}",
            json={
                "schema_version": "memory-comparison-run-cleanup.v2",
                "binding_commitment_sha256": BINDING,
                "infinity_target_identity_sha256": TARGET,
                "space_id": space_id,
                "space_slug": SPACE_SLUG,
                "cleanup_plan_sha256": cleanup_plan.sha256,
            },
            headers={"Idempotency-Key": CLEANUP_KEY},
        )
        assert cleanup.status_code == 200, cleanup.text
        initiation = cleanup.json()["data"]
        assert initiation["state"] == "cleanup_pending"
        assert initiation["projection_cleanup"] == "blocked"
        assert initiation["counts"]["memory_scopes"] == 1
        assert initiation["counts"]["threads"] == 1
        assert initiation["counts"]["facts"] == 1
        assert initiation["vector_delete_outbox_ids"] == []
        assert len(initiation["graph_delete_outbox_ids"]) == 1
        assert initiation["cognee_delete_outbox_ids"] == []
        worker = OutboxWorker(
            client.app.state.container,
            worker_filter=OutboxWorkerFilter(workload_classes=("projection",)),
        )
        processed = [asyncio.run(worker.run_once(limit=10)) for _ in range(3)]
        assert processed[0] >= 1

        abort_payload = {
            "schema_version": "memory-comparison-run-abort-finalize.v2",
            "binding_commitment_sha256": BINDING,
            "infinity_target_identity_sha256": TARGET,
            "space_id": space_id,
            "space_slug": SPACE_SLUG,
            "receipt_sha256": initiation["receipt_sha256"],
            "cleanup_plan_sha256": cleanup_plan.sha256,
        }
        aborted = client.post(
            f"/v1/internal/memory-comparison/runs/{RUN}/cleanup/abort/finalize",
            json=abort_payload,
            headers={"Idempotency-Key": ABORT_KEY},
        )
        assert aborted.status_code == 200, aborted.text
        terminal = aborted.json()["data"]
        assert terminal["state"] == "cleanup_aborted"
        assert terminal["disposition"] == "abort_complete"
        assert terminal["projection_cleanup"] == "unsealed_abort_complete"
        assert terminal["binding_commitment_sha256"] == BINDING
        assert terminal["infinity_target_identity_sha256"] == TARGET
        assert terminal["cleanup_initiation_receipt_sha256"] == initiation["receipt_sha256"]
        assert terminal["cleanup_plan_sha256"] == cleanup_plan.sha256
        assert terminal["replayed"] is False

    with (
        _sqlite_test_client(
            monkeypatch,
            tmp_path,
            token=token,
            database_name=database_name,
        ) as client,
    ):
        lifecycle_response = client.get(f"/v1/internal/memory-comparison/runs/{RUN}/cleanup")
        assert lifecycle_response.status_code == 200, lifecycle_response.text
        lifecycle = lifecycle_response.json()["data"]
        assert lifecycle["schema_version"] == "memory-comparison-run-lifecycle-response.v2"
        assert lifecycle["state"] == "cleanup_aborted"
        assert lifecycle["cleanup_plan_sha256"] == cleanup_plan.sha256
        assert lifecycle["cleanup_plan_state"] == "sealed"
        assert lifecycle["projection_cleanup_state"] == "unsealed_abort_complete"
        assert lifecycle["projection_manifest_sha256"] is None
        assert lifecycle["cleanup_receipt"]["receipt_sha256"] == initiation["receipt_sha256"]
        assert lifecycle["completion_receipt"]["receipt_sha256"] == terminal["receipt_sha256"]

        replay = client.post(
            f"/v1/internal/memory-comparison/runs/{RUN}/cleanup/abort/finalize",
            json=abort_payload,
            headers={"Idempotency-Key": ABORT_KEY},
        )
        assert replay.status_code == 200, replay.text
        replayed = replay.json()["data"]
        assert replayed["replayed"] is True
        assert replayed["receipt_sha256"] == terminal["receipt_sha256"]
        assert replayed["completed_at"] == terminal["completed_at"]


def _cleanup_plan(
    target: str,
    authority: ManagedBenchmarkCleanupTargetAuthority,
) -> ManagedBenchmarkCleanupPlan:
    def digest(character: str) -> str:
        return character * 64

    source_sha256 = managed_benchmark_text_sha256(FACT_SOURCE)
    content_sha256 = managed_benchmark_text_sha256(FACT_TEXT)
    source_ref = managed_benchmark_fact_source_ref_descriptor(
        source_type="memory_comparison_benchmark",
        source_id=FACT_SOURCE,
        quote_preview=FACT_TEXT,
    )
    operation_sha256 = managed_benchmark_infinity_operation_sha256(
        managed_benchmark_fact_operation_material(
            source_external_id_sha256=source_sha256,
            content_sha256=content_sha256,
            kind="requirement",
            classification="internal",
            source_refs=(source_ref,),
        )
    )
    value: dict[str, object] = {
        "schema_version": CLEANUP_PLAN_SCHEMA_VERSION,
        "run_id_sha256": RUN,
        "binding_commitment_sha256": BINDING,
        "infinity_target_identity_sha256": target,
        "space_id": f"benchmark-space-{RUN[:48]}",
        "space_slug": SPACE_SLUG,
        "profile_id": "e2e-unsealed-abort",
        "ordered_case_sha256": [digest("1")],
        "corpora": [
            {
                "ordinal": 0,
                "corpus_id_sha256": digest("2"),
                "managed_corpus_projection_sha256": digest("3"),
                "memory_scope_external_ref_sha256": managed_benchmark_text_sha256(SCOPE_REF),
                "thread_external_ref_sha256": managed_benchmark_text_sha256(THREAD_REF),
                "infinity_lane": "fact",
                "ordered_infinity_operation_sha256": [operation_sha256],
                "ordered_infinity_source_external_id_sha256": [source_sha256],
                "ordered_infinity_content_sha256": [content_sha256],
                "ordered_document_fragment_count": [],
                "expected_fact_count": 1,
                "expected_document_count": 0,
                "expected_chunk_count": 0,
                "mem0_corpus_identity_sha256": digest("6"),
                "ordered_mem0_source_id_sha256": [digest("5")],
                "ordered_mem0_unit_identity_sha256": [digest("7")],
                "expected_ingest_unit_count": 1,
            }
        ],
        "mem0": {
            "admission_commitment_sha256": digest("8"),
            "ingestion_manifest_sha256": digest("9"),
            "ingestion_root_sha256": digest("d"),
            "expected_operation_count": 1,
        },
        "infinity_namespace_policy_sha256": INFINITY_NAMESPACE_POLICY_SHA256,
        "qdrant": {},
        "graphiti": {},
        "cognee": {
            "disposition": "not_projected",
            "policy_sha256": COGNEE_NOT_PROJECTED_POLICY_SHA256,
        },
        "cardinality": {
            "case_count": 1,
            "corpus_count": 1,
            "mem0_source_identity_count": 1,
            "expected_ingest_unit_count": 1,
            "infinity_operation_count": 1,
            "expected_fact_count": 1,
            "expected_document_count": 0,
            "expected_chunk_count": 0,
        },
        "limits_policy_sha256": CLEANUP_PLAN_LIMITS_POLICY_SHA256,
    }
    for lane in ("qdrant", "graphiti", "cognee"):
        value[lane] = authority.value[lane]
    digest = managed_benchmark_cleanup_plan_material_sha256(value)
    return validate_managed_benchmark_cleanup_plan(
        value,
        digest,
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        infinity_target_identity_sha256=target,
        space_slug=SPACE_SLUG,
    )


class _AbsentProjectionEvidence:
    def __init__(self, lane: str, target: str) -> None:
        self._lane = lane
        self._target = target

    async def delete_benchmark_space_two_pass(
        self, **_: object
    ) -> tuple[BenchmarkProjectionPassReceipt, BenchmarkProjectionPassReceipt]:
        return tuple(
            BenchmarkProjectionPassReceipt(
                lane=self._lane,
                target_commitment_sha256=self._target,
                pass_index=pass_index,
                observed_count=0,
                absent=True,
                receipt_sha256=str(pass_index) * 64,
            )
            for pass_index in (1, 2)
        )


class _SuccessfulDeleteGraph:
    def __init__(self, delegate: object) -> None:
        self._delegate = delegate

    def __getattr__(self, name: str) -> object:
        return getattr(self._delegate, name)

    async def delete_fact(self, *_args: object, **_kwargs: object) -> VectorWriteResult:
        return VectorWriteResult.ok(1)


@contextmanager
def _sqlite_test_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    token: str,
    database_name: str,
) -> Iterator[TestClient]:
    with _provider_free_test_client(
        monkeypatch,
        database_url=f"sqlite+aiosqlite:///{tmp_path / database_name}",
        token=token,
    ) as client:
        yield client


@contextmanager
def _provider_free_test_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    database_url: str,
    token: str,
) -> Iterator[TestClient]:
    original = derived_provider_composition.build_derived_provider_bundle

    def provider_free_bundle(*, engine: object, settings: Settings) -> object:
        disabled = settings.model_copy(
            update={
                "qdrant_enabled": False,
                "graphiti_enabled": False,
                "embeddings_enabled": False,
            }
        )
        bundle = original(engine=engine, settings=disabled)
        qdrant_target = qdrant_target_commitment_sha256(
            settings.qdrant_url, settings.qdrant_collection
        )
        graphiti_target = graphiti_target_commitment_sha256(neo4j_uri=settings.graphiti_neo4j_uri)
        return replace(
            bundle,
            raw_graph=_SuccessfulDeleteGraph(bundle.raw_graph),
            vector_evidence=_AbsentProjectionEvidence("qdrant", qdrant_target),
            graph_evidence=_AbsentProjectionEvidence("graphiti", graphiti_target),
            qdrant_target_commitment_sha256=qdrant_target,
            graphiti_target_commitment_sha256=graphiti_target,
        )

    monkeypatch.setattr(
        derived_provider_composition,
        "build_derived_provider_bundle",
        provider_free_bundle,
    )
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.LOCAL,
            database_url=database_url,
            auto_create_schema=True,
            service_token=token,
            qdrant_enabled=True,
            graphiti_enabled=True,
            graphiti_neo4j_password="sandbox-graph-password",
            embeddings_enabled=True,
            embeddings_provider="openai",
            openai_api_key="sandbox-openai-key",
        )
    )
    with TestClient(app, headers={"Authorization": f"Bearer {token}"}) as client:
        yield client


def test_postgres_unsealed_abort_migration_contract_is_explicit() -> None:
    migration = (
        PROJECT_ROOT
        / "packages"
        / "infinity_context_adapters"
        / "infinity_context_adapters"
        / "postgres"
        / "migrations"
        / "0021_benchmark_unsealed_abort.sql"
    ).read_text()

    assert (
        "state IN ('active', 'cleanup_pending', 'cleanup_complete', 'cleanup_aborted')" in migration
    )
    assert "projection_cleanup_state = 'unsealed_abort_complete'" in migration
    assert "projection_manifest_json IS NULL" in migration
    assert migration.count(") NOT VALID") == 4
    assert migration.count("VALIDATE CONSTRAINT") == 4


@contextmanager
def _isolated_postgres_database() -> Iterator[str]:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncpg = pytest.importorskip("asyncpg")
    parsed = make_url(database_url)
    if not parsed.drivername.startswith("postgresql"):
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not PostgreSQL")
    database_name = f"abort_e2e_{uuid.uuid4().hex}"
    admin_dsn = parsed.set(drivername="postgresql").render_as_string(hide_password=False)
    app_url = parsed.set(
        drivername="postgresql+asyncpg",
        database=database_name,
    ).render_as_string(hide_password=False)

    async def create_database() -> None:
        connection = await asyncpg.connect(admin_dsn)
        try:
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

"""Crash, tamper, order, and concurrency contracts for Infinity ingestion."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

import httpx
import pytest
from infinity_context_server.memory_comparison_infinity_ingestion_contracts import (
    InfinityIngestionError,
)
from infinity_context_server.memory_comparison_infinity_ingestion_http import (
    InfinityEpisodeHttpAdapter,
)
from infinity_context_server.memory_comparison_infinity_ingestion_journal import (
    HmacInfinityOperationReceiptVerifier,
    JournaledInfinityIngestionConsumer,
    make_infinity_ingestion_operation_manifest,
)
from infinity_context_server.memory_comparison_infinity_ingestion_result_sqlite import (
    SQLiteInfinityIngestionResultStore,
)
from infinity_context_server.memory_comparison_ingestion_contracts import (
    IngestionMessage,
    IngestionUnitMetadata,
    make_ingestion_unit,
    opaque_ingestion_corpus_id,
    opaque_ingestion_source_id,
)
from infinity_context_server.resumable_operation_journal import (
    HmacSha256OperationJournalSigner,
    NullOperationNotification,
    OperationJournalError,
    OperationRunIdentity,
    ResumableOperationJournalService,
)
from infinity_context_server.resumable_operation_journal.domain import sha256_commitment
from infinity_context_server.resumable_operation_journal.service import (
    AllowAllOperationManifestPolicy,
)
from infinity_context_server.resumable_operation_journal.sqlite import (
    SQLiteOperationJournal,
)

RUN_ID = "run-infinity-journal-r1"
INGESTION_MANIFEST_SHA256 = "a" * 64
SECRET = b"infinity-journal-test-secret-at-least-32-bytes"


def _units(count: int = 1):
    corpus_id = opaque_ingestion_corpus_id(corpus_identity={"sample": "one"})
    return tuple(
        make_ingestion_unit(
            ordinal=ordinal,
            corpus_id=corpus_id,
            message=IngestionMessage(role="user", content=f"Neutral content {ordinal}"),
            metadata=IngestionUnitMetadata(
                source_id=opaque_ingestion_source_id(source_identity={"turn": ordinal}),
                timestamp=1_700_000_000 + ordinal,
            ),
        )
        for ordinal in range(count)
    )


def _response(*, ordinal: int, replay: bool = False) -> dict[str, object]:
    return {
        "data": {
            "chunk_ids": [f"chunk_{ordinal}"],
            "created_suggestions": 0,
            "duplicate_chunks": 1 if replay else 0,
            "durability": "durable",
            "episode_id": f"episode_{ordinal}",
            "memory_scope_id": "scope_1",
            "space_id": "space_1",
            "stored_chunks": 0 if replay else 1,
            "suggestion_ids": [],
            "thread_id": "thread_1",
        }
    }


def _stack(tmp_path: Path, units, handler):
    private = tmp_path / "private"
    journal = SQLiteOperationJournal(private / "operations.sqlite3", private_directory=private)
    signer = HmacSha256OperationJournalSigner(key_id="signer-v1", secret=SECRET)
    manifest = make_infinity_ingestion_operation_manifest(
        units,
        run_id=RUN_ID,
        ingestion_manifest_sha256=INGESTION_MANIFEST_SHA256,
    )
    service = ResumableOperationJournalService(
        journal=journal,
        signer=signer,
        manifest_policy=AllowAllOperationManifestPolicy(),
        receipt_verifier=HmacInfinityOperationReceiptVerifier(signer),
        notifications=NullOperationNotification(),
    )
    service.initialize(
        OperationRunIdentity(
            run_id=RUN_ID,
            operation_namespace="infinity_ingestion",
            manifest_commitment_sha256=manifest.commitment_sha256,
            policy_commitment_sha256=sha256_commitment(
                {"policy": "manifest_ordered_idempotent_replay"}
            ),
            signer_key_id=signer.key_id,
            expected_operation_count=len(units),
        ),
        manifest,
    )
    results = SQLiteInfinityIngestionResultStore(
        private / "results.sqlite3",
        signer=signer,
        private_directory=private,
    )
    adapter = InfinityEpisodeHttpAdapter(
        origin="http://127.0.0.1:8080",
        service_token="test-token",
        transport=httpx.MockTransport(handler),
    )
    consumer = JournaledInfinityIngestionConsumer(
        adapter=adapter,
        journal=service,
        operation_manifest=manifest,
        results=results,
        signer=signer,
        ingestion_manifest_sha256=INGESTION_MANIFEST_SHA256,
    )
    return consumer, service, results, signer, manifest, private


def test_lost_response_is_resumed_with_idempotent_replay(tmp_path: Path) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ReadTimeout("accepted but response lost", request=request)
        return httpx.Response(200, json=_response(ordinal=0, replay=True))

    unit = _units()[0]
    consumer, service, _, _, _, _ = _stack(tmp_path, (unit,), handler)
    with pytest.raises(InfinityIngestionError, match="transport failed"):
        consumer.consume_with_receipt(
            unit,
            run_id=RUN_ID,
            manifest_sha256=INGESTION_MANIFEST_SHA256,
        )

    consumer.resume()
    receipt = consumer.consume_with_receipt(
        unit,
        run_id=RUN_ID,
        manifest_sha256=INGESTION_MANIFEST_SHA256,
    )

    assert calls == 2
    assert receipt.episode_id == "episode_0"
    assert service.snapshot(RUN_ID).committed_count == 1


class _FailCommitOnce:
    def __init__(self, service: ResumableOperationJournalService) -> None:
        self.service = service
        self.failed = False

    def __getattr__(self, name: str):
        return getattr(self.service, name)

    def commit(self, identity, receipt):
        if not self.failed:
            self.failed = True
            raise OperationJournalError("simulated_post_save_crash")
        return self.service.commit(identity, receipt)


class _ConnectionProbe:
    def __init__(self, connection, *, fail_execute: bool = False) -> None:
        self.connection = connection
        self.fail_execute = fail_execute
        self.closed = False

    def execute(self, *args, **kwargs):
        if self.fail_execute:
            raise sqlite3.OperationalError("private sqlite detail")
        return self.connection.execute(*args, **kwargs)

    def close(self) -> None:
        self.closed = True
        self.connection.close()


def test_post_save_crash_reuses_authenticated_result_without_http(tmp_path: Path) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_response(ordinal=0))

    units = _units()
    consumer, service, results, signer, manifest, _ = _stack(tmp_path, units, handler)
    crashing = JournaledInfinityIngestionConsumer(
        adapter=consumer._adapter,
        journal=_FailCommitOnce(service),
        operation_manifest=manifest,
        results=results,
        signer=signer,
        ingestion_manifest_sha256=INGESTION_MANIFEST_SHA256,
    )
    with pytest.raises(InfinityIngestionError, match="commit failed"):
        crashing.consume_with_receipt(
            units[0], run_id=RUN_ID, manifest_sha256=INGESTION_MANIFEST_SHA256
        )

    recovered = JournaledInfinityIngestionConsumer(
        adapter=consumer._adapter,
        journal=service,
        operation_manifest=manifest,
        results=results,
        signer=signer,
        ingestion_manifest_sha256=INGESTION_MANIFEST_SHA256,
    )
    recovered.resume()
    receipt = recovered.consume_with_receipt(
        units[0], run_id=RUN_ID, manifest_sha256=INGESTION_MANIFEST_SHA256
    )

    assert calls == 1
    assert receipt.episode_id == "episode_0"
    assert service.snapshot(RUN_ID).committed_count == 1


def test_manifest_order_violation_fails_before_http(tmp_path: Path) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_response(ordinal=1))

    units = _units(2)
    consumer, _, _, _, _, _ = _stack(tmp_path, units, handler)
    with pytest.raises(InfinityIngestionError, match="manifest order"):
        consumer.consume_with_receipt(
            units[1], run_id=RUN_ID, manifest_sha256=INGESTION_MANIFEST_SHA256
        )
    assert calls == 0


def test_result_store_tampering_fails_closed(tmp_path: Path) -> None:
    unit = _units()[0]
    consumer, _, _, _, manifest, private = _stack(
        tmp_path,
        (unit,),
        lambda _: httpx.Response(200, json=_response(ordinal=0)),
    )
    consumer.consume_with_receipt(
        unit, run_id=RUN_ID, manifest_sha256=INGESTION_MANIFEST_SHA256
    )
    operation_id = manifest.operations[0].logical_operation_id
    connection = sqlite3.connect(private / "results.sqlite3")
    row = connection.execute(
        "SELECT result_json FROM infinity_ingestion_results WHERE logical_operation_id = ?",
        (operation_id,),
    ).fetchone()
    payload = json.loads(row[0])
    payload["episode_id"] = "episode_tampered"
    connection.execute(
        "UPDATE infinity_ingestion_results SET result_json = ? WHERE logical_operation_id = ?",
        (json.dumps(payload, separators=(",", ":"), sort_keys=True), operation_id),
    )
    connection.commit()
    connection.close()

    with pytest.raises(InfinityIngestionError, match="authentication failed"):
        consumer.consume_with_receipt(
            unit, run_id=RUN_ID, manifest_sha256=INGESTION_MANIFEST_SHA256
        )


def test_result_store_rejects_unsafe_sidecar_before_open(tmp_path: Path) -> None:
    _, _, results, _, _, private = _stack(
        tmp_path,
        _units(),
        lambda _: httpx.Response(200, json=_response(ordinal=0)),
    )
    sidecar = Path(f"{private / 'results.sqlite3'}-wal")
    sidecar.symlink_to(private / "outside")

    with pytest.raises(InfinityIngestionError, match="private file is unsafe"):
        results.load("0" * 64)


def test_result_store_deleted_database_fails_closed_without_sqlite_leak(
    tmp_path: Path,
) -> None:
    _, _, results, _, _, private = _stack(
        tmp_path,
        _units(),
        lambda _: httpx.Response(200, json=_response(ordinal=0)),
    )
    (private / "results.sqlite3").unlink()

    with pytest.raises(InfinityIngestionError, match="storage is unavailable") as error:
        results.load("0" * 64)
    assert error.value.__cause__ is None
    assert "no such table" not in str(error.value)


def test_result_store_schema_tamper_fails_closed_on_reopen(tmp_path: Path) -> None:
    _, _, _, signer, _, private = _stack(
        tmp_path,
        _units(),
        lambda _: httpx.Response(200, json=_response(ordinal=0)),
    )
    path = private / "results.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute("DROP TABLE infinity_ingestion_schema")
    connection.execute("CREATE TABLE infinity_ingestion_schema (wrong TEXT NOT NULL)")
    connection.commit()
    connection.close()

    with pytest.raises(InfinityIngestionError, match="storage is unavailable") as error:
        SQLiteInfinityIngestionResultStore(path, signer=signer, private_directory=private)
    assert error.value.__cause__ is None
    assert "no column named" not in str(error.value)


def test_result_store_closes_connection_when_pragma_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, results, _, _, _ = _stack(
        tmp_path,
        _units(),
        lambda _: httpx.Response(200, json=_response(ordinal=0)),
    )
    real_connect = sqlite3.connect
    probe = _ConnectionProbe(real_connect(":memory:"), fail_execute=True)
    monkeypatch.setattr(sqlite3, "connect", lambda *args, **kwargs: probe)

    with pytest.raises(InfinityIngestionError, match="storage is unavailable") as error:
        results.load("0" * 64)
    assert error.value.__cause__ is None
    assert probe.closed


def test_result_store_closes_connection_when_post_open_security_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, results, _, _, _ = _stack(
        tmp_path,
        _units(),
        lambda _: httpx.Response(200, json=_response(ordinal=0)),
    )
    real_connect = sqlite3.connect
    probe = _ConnectionProbe(real_connect(":memory:"))
    monkeypatch.setattr(sqlite3, "connect", lambda *args, **kwargs: probe)

    def fail_secure() -> None:
        raise InfinityIngestionError("post-open security failure")

    monkeypatch.setattr(results, "_secure_files", fail_secure)
    with pytest.raises(InfinityIngestionError, match="post-open security failure"):
        results.load("0" * 64)
    assert probe.closed


def test_concurrent_duplicate_dispatches_http_once(tmp_path: Path) -> None:
    calls = 0
    calls_lock = threading.Lock()

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        with calls_lock:
            calls += 1
        time.sleep(0.05)
        return httpx.Response(200, json=_response(ordinal=0))

    unit = _units()[0]
    consumer, service, _, _, _, _ = _stack(tmp_path, (unit,), handler)
    receipts = []
    failures = []

    def consume() -> None:
        try:
            receipts.append(
                consumer.consume_with_receipt(
                    unit,
                    run_id=RUN_ID,
                    manifest_sha256=INGESTION_MANIFEST_SHA256,
                )
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            failures.append(exc)

    threads = [threading.Thread(target=consume) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert not failures
    assert all(not thread.is_alive() for thread in threads)
    assert len(receipts) == 2
    assert receipts[0] == receipts[1]
    assert calls == 1
    assert service.snapshot(RUN_ID).committed_count == 1

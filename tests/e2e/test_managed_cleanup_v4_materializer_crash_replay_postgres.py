"""Fresh-Postgres crash/replay proof for the strict-v4 inventory materializer."""

from __future__ import annotations

import asyncio
import os
import time
import traceback
from pathlib import Path

import pytest
from infinity_context_core.ports.managed_cleanup_v3_contracts import ManagedCleanupV3Error


class _ExitAfterSidecarFinalize:
    """Emulate process death after durable sidecar finalization but before PG commit."""

    def __init__(self, delegate) -> None:
        self._delegate = delegate

    async def begin_verification(self, terminal, session) -> None:
        await self._delegate.begin_verification(terminal, session)

    async def begin_new_verification(self, terminal, session) -> None:
        await self._delegate.begin_new_verification(terminal, session)

    async def prepare_receipts(self, connection, context, terminal, session) -> None:
        await self._delegate.prepare_receipts(connection, context, terminal, session)

    async def __call__(self, connection, context, terminal, session, kind, row) -> None:
        await self._delegate(connection, context, terminal, session, kind, row)

    async def flush_verification_page(self, terminal, session) -> None:
        await self._delegate.flush_verification_page(terminal, session)

    async def finalize_verification(self, terminal, session) -> None:
        await self._delegate.finalize_verification(terminal, session)
        os._exit(86)

    async def abort_verification(self, terminal, session) -> None:
        await self._delegate.abort_verification(terminal, session)


def test_hard_death_resets_finalized_sidecar_then_exact_replay_is_read_only(
    tmp_path: Path,
) -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    from managed_cleanup_v3_full_postgres_support import (
        create_full_postgres_harness,
    )

    harness = asyncio.run(create_full_postgres_harness(database_url, tmp_path))
    original_authenticator = harness.materializer._authenticate
    hard_death_started = time.monotonic()
    try:
        child = os.fork()
        if child == 0:
            harness.materializer._authenticate = _ExitAfterSidecarFinalize(original_authenticator)
            try:
                asyncio.run(_materialize(harness))
            except BaseException:
                (tmp_path / "child-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
                os._exit(87)
            os._exit(88)
        _pid, status = os.waitpid(child, 0)
        child_error = tmp_path / "child-error.txt"
        assert os.WIFEXITED(status) and os.WEXITSTATUS(status) == 86, (
            child_error.read_text(encoding="utf-8") if child_error.exists() else status
        )
        assert time.monotonic() - hard_death_started < 180

        assert asyncio.run(_materialization_count(harness)) == 0
        assert _sidecar_state(harness)[0] == "finalized"

        recovery_started = time.monotonic()
        harness.materializer._authenticate = original_authenticator
        asyncio.run(_materialize(harness))
        complete_count = asyncio.run(_materialization_count(harness))
        assert complete_count == 15
        successful_sidecar = _sidecar_state(harness)

        asyncio.run(_materialize(harness))
        assert asyncio.run(_materialization_count(harness)) == complete_count
        assert _sidecar_state(harness) == successful_sidecar

        asyncio.run(_assert_partial_replay_does_not_reset(harness, successful_sidecar))
        asyncio.run(_assert_tampered_replay_does_not_reset(harness, successful_sidecar))
        assert time.monotonic() - recovery_started < 180
    finally:
        harness.materializer._authenticate = original_authenticator
        asyncio.run(harness.close())


async def _materialize(harness) -> None:
    await harness.materializer.materialize(
        context=harness.context,
        authority_terminal_sha256=harness.authority.terminal_commitment_sha256,
        cleanup_receipt_sha256=harness.cleanup_receipt_sha256,
    )


async def _materialization_count(harness) -> int:
    connection = await harness.database.connect()
    try:
        return int(
            await connection.fetchval(
                "SELECT count(*) FROM memory_cleanup_inventory_materializations "
                "WHERE run_id_sha256=$1 AND context_sha256=$2 "
                "AND cleanup_receipt_sha256=$3 AND complete IS TRUE",
                harness.context.run_id_sha256,
                harness.context.context_sha256,
                harness.cleanup_receipt_sha256,
            )
        )
    finally:
        await connection.close()


def _sidecar_state(harness) -> tuple[object, ...]:
    return tuple(
        harness.expected_rows._claim_db.execute(
            "SELECT state, session_sha, terminal_sha, session_mac FROM verification_session"
        ).fetchone()
    )


async def _assert_partial_replay_does_not_reset(harness, sidecar_state) -> None:
    connection = await harness.database.connect()
    row = await connection.fetchrow(
        "DELETE FROM memory_cleanup_inventory_materializations "
        "WHERE run_id_sha256=$1 AND context_sha256=$2 AND cleanup_receipt_sha256=$3 "
        "AND kind='unsupported_rows' RETURNING *",
        harness.context.run_id_sha256,
        harness.context.context_sha256,
        harness.cleanup_receipt_sha256,
    )
    assert row is not None
    try:
        with pytest.raises(ManagedCleanupV3Error):
            await _materialize(harness)
        assert _sidecar_state(harness) == sidecar_state
    finally:
        columns = tuple(row.keys())
        placeholders = ",".join("$" + str(index) for index in range(1, len(columns) + 1))
        await connection.execute(
            f"INSERT INTO memory_cleanup_inventory_materializations "
            f"({','.join(columns)}) VALUES ({placeholders})",
            *tuple(row.values()),
        )
        await connection.close()


async def _assert_tampered_replay_does_not_reset(harness, sidecar_state) -> None:
    connection = await harness.database.connect()
    row = await connection.fetchrow(
        "SELECT run_id_sha256,context_sha256,cleanup_receipt_sha256,kind,"
        "canonical_key_sha256,row_mac_sha256 FROM memory_cleanup_inventory_keys "
        "WHERE run_id_sha256=$1 AND context_sha256=$2 AND cleanup_receipt_sha256=$3 "
        "ORDER BY kind,canonical_key_sha256 LIMIT 1",
        harness.context.run_id_sha256,
        harness.context.context_sha256,
        harness.cleanup_receipt_sha256,
    )
    assert row is not None
    key = tuple(
        row[name]
        for name in (
            "run_id_sha256",
            "context_sha256",
            "cleanup_receipt_sha256",
            "kind",
            "canonical_key_sha256",
        )
    )
    await _set_key_mac(connection, key, "0" * 64)
    try:
        with pytest.raises(ManagedCleanupV3Error):
            await _materialize(harness)
        assert _sidecar_state(harness) == sidecar_state
    finally:
        await _set_key_mac(connection, key, row["row_mac_sha256"])
        await connection.close()


async def _set_key_mac(connection, key, value) -> None:
    await connection.execute(
        "UPDATE memory_cleanup_inventory_keys SET row_mac_sha256=$1 "
        "WHERE run_id_sha256=$2 AND context_sha256=$3 AND cleanup_receipt_sha256=$4 "
        "AND kind=$5 AND canonical_key_sha256=$6",
        value,
        *key,
    )

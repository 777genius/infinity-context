from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

import pytest
from infinity_context_adapters.postgres.benchmark_writer_fence import (
    BENCHMARK_WRITER_FENCE_FUNCTION,
    BENCHMARK_WRITER_FENCE_TABLES,
)
from infinity_context_adapters.postgres.managed_cleanup_v4_context_registration import (
    StrictV4PreExecutionRegistrationPolicy,
    _registration_from_row,
)
from infinity_context_core.features.projection_receipts import (
    ProjectionReceiptAuthenticator,
    ProjectionReceiptError,
    context_authority_registration_sha256,
)
from test_projection_result_receipts import V3_AUTHORITY, V3_CONTEXT

WHEN = datetime(2026, 8, 9, tzinfo=UTC)
AUTHENTICATOR = ProjectionReceiptAuthenticator(b"v" * 32)


def _row(*, context_json=None, authority_json=None, mac=None):
    registration = context_authority_registration_sha256(V3_CONTEXT, V3_AUTHORITY)
    return {
        "run_id_sha256": V3_CONTEXT.run_id_sha256,
        "context_sha256": V3_CONTEXT.context_sha256,
        "authority_terminal_sha256": V3_AUTHORITY.terminal_commitment_sha256,
        "context_json": context_json or json.dumps(V3_CONTEXT.payload()),
        "authority_json": authority_json or json.dumps(V3_AUTHORITY.payload()),
        "registration_sha256": registration,
        "registration_mac_sha256": mac
        or AUTHENTICATOR.sign("projection-context-authority", registration),
        "registered_at": WHEN,
    }


def test_raw_asyncpg_json_text_is_strictly_decoded() -> None:
    registration = _registration_from_row(_row(), created=True)
    assert registration.context == V3_CONTEXT
    assert registration.authority == V3_AUTHORITY
    assert registration.created is True


@pytest.mark.parametrize(
    "field",
    ("context_json", "authority_json"),
)
def test_raw_asyncpg_duplicate_json_keys_fail_closed(field: str) -> None:
    row = _row()
    row[field] = '{"schema_version":"duplicate","schema_version":"again"}'
    with pytest.raises(ProjectionReceiptError, match="context_authority_invalid"):
        _registration_from_row(row, created=False)


def _locked_run(**changes):
    row = {
        "run_id_sha256": V3_CONTEXT.run_id_sha256,
        "binding_commitment_sha256": V3_CONTEXT.binding_commitment_sha256,
        "infinity_target_identity_sha256": V3_CONTEXT.infinity_target_identity_sha256,
        "space_id": V3_CONTEXT.space_id,
        "space_slug": V3_CONTEXT.space_slug,
        "state": "active",
        "cleanup_plan_json": None,
        "cleanup_plan_sha256": None,
        "cleanup_plan_state": "recovery_blocked",
        "projection_cleanup_state": "unsealed",
        "projection_manifest_json": None,
        "projection_manifest_sha256": None,
        "cleanup_fingerprint_sha256": None,
        "cleanup_receipt_json": None,
        "finalization_fingerprint_sha256": None,
        "completion_receipt_json": None,
        "completed_at": None,
    }
    row.update(changes)
    return row


class _FenceConnection:
    def __init__(self, *, missing: str | None = None, absent: bool = True) -> None:
        self._missing = missing
        self._absent = absent

    async def fetch(self, _sql, _tables):
        return [
            {
                "table_name": table,
                "trigger_name": f"trg_{table}_benchmark_writer_fence",
                "trigger_enabled": "O",
                "function_name": BENCHMARK_WRITER_FENCE_FUNCTION,
            }
            for table, _columns in BENCHMARK_WRITER_FENCE_TABLES
            if table != self._missing
        ]

    async def fetchval(self, _sql, _space_id, _run_id):
        return self._absent


def test_default_phase_policy_requires_schema_fence_and_pristine_rows() -> None:
    async def scenario() -> None:
        policy = StrictV4PreExecutionRegistrationPolicy()
        await policy.assert_registration_binding(
            _FenceConnection(), context=V3_CONTEXT, locked_run=_locked_run()
        )
        await policy.assert_first_registration_allowed(
            _FenceConnection(), context=V3_CONTEXT, locked_run=_locked_run()
        )
        with pytest.raises(ProjectionReceiptError, match="writer_fence_invalid"):
            await policy.assert_registration_binding(
                _FenceConnection(missing="memory_facts"),
                context=V3_CONTEXT,
                locked_run=_locked_run(),
            )
        with pytest.raises(ProjectionReceiptError, match="context_not_pristine"):
            await policy.assert_first_registration_allowed(
                _FenceConnection(absent=False),
                context=V3_CONTEXT,
                locked_run=_locked_run(),
            )
        with pytest.raises(ProjectionReceiptError, match="context_pre_execution_invalid"):
            await policy.assert_first_registration_allowed(
                _FenceConnection(),
                context=V3_CONTEXT,
                locked_run=_locked_run(projection_cleanup_state="pending"),
            )
        with pytest.raises(ProjectionReceiptError, match="context_pre_execution_invalid"):
            await policy.assert_first_registration_allowed(
                _FenceConnection(),
                context=V3_CONTEXT,
                locked_run=_locked_run(
                    cleanup_plan_json={"legacy": True},
                    cleanup_plan_sha256="f" * 64,
                    cleanup_plan_state="sealed",
                ),
            )

    asyncio.run(scenario())

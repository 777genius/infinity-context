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
from infinity_context_adapters.postgres.strict_v4_writer_fence_topology import (
    _WRITER_POLICY_BODY_0036,
    _assert_strict_v4_writer_fence_topology_0036_compat,
    assert_strict_v4_writer_fence_topology,
)
from infinity_context_core.features.projection_receipts import (
    ProjectionReceiptAuthenticator,
    ProjectionReceiptError,
    context_authority_registration_sha256,
)

from tests.adapters.managed_cleanup_v4_test_support import V3_AUTHORITY, V3_CONTEXT

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
    def __init__(
        self,
        *,
        missing: str | None = None,
        absent: bool = True,
        tamper: tuple[str, object] | None = None,
    ) -> None:
        self._missing = missing
        self._absent = absent
        self._tamper = tamper

    async def fetch(
        self,
        _sql,
        _tables,
        _roles,
        _safe_path,
        _lock_body,
        _policy_body,
        _checker_body,
        _checker_path,
        _checker_roles,
        _sentinel_names,
        _sentinel_functions,
        _sentinel_types,
        _document_policy_body,
        _requires_document_policy,
    ):
        rows = []
        for table, _columns in BENCHMARK_WRITER_FENCE_TABLES:
            if table == self._missing:
                continue
            for lock_stage in (True, False):
                row = {
                    "table_name": table,
                    "trigger_name": (
                        f"trg_00_{table}_benchmark_writer_lock"
                        if lock_stage
                        else f"trg_{table}_benchmark_writer_fence"
                    ),
                    "trigger_enabled": "O",
                    "trigger_type": 31,
                    "has_no_when_clause": True,
                    "has_no_update_column_filter": True,
                    "has_no_trigger_arguments": True,
                    "function_name": (
                        "memory_comparison_lock_benchmark_writer_target"
                        if lock_stage
                        else BENCHMARK_WRITER_FENCE_FUNCTION
                    ),
                    "security_definer": lock_stage,
                    "function_kind": "f",
                    "function_has_exact_kind": True,
                    "returns_trigger": True,
                    "has_no_arguments": True,
                    "has_safe_search_path": True,
                    "has_exact_body": True,
                    "checker_has_exact_kind": True,
                    "checker_has_safe_search_path": True,
                    "checker_has_exact_body": True,
                    "checker_has_safe_owner": True,
                    "checker_has_exact_acl": True,
                    "sentinel_has_exact_before_insert_triggers": True,
                    "document_policy_is_exact": True,
                    "function_has_safe_owner": True,
                    "function_has_exact_acl": True,
                }
                if self._tamper is not None and table == "memory_spaces" and lock_stage:
                    row[self._tamper[0]] = self._tamper[1]
                rows.append(row)
        return rows

    async def fetchval(self, _sql, _space_id, _run_id):
        return self._absent


def test_topology_and_default_phase_policy_fail_closed() -> None:
    async def scenario() -> None:
        policy = StrictV4PreExecutionRegistrationPolicy()
        await assert_strict_v4_writer_fence_topology(_FenceConnection())
        await policy.assert_registration_binding(
            _FenceConnection(), context=V3_CONTEXT, locked_run=_locked_run()
        )
        await policy.assert_first_registration_allowed(
            _FenceConnection(), context=V3_CONTEXT, locked_run=_locked_run()
        )
        with pytest.raises(ProjectionReceiptError, match="writer_fence_invalid"):
            await assert_strict_v4_writer_fence_topology(_FenceConnection(missing="memory_facts"))
        for field, value in (
            ("trigger_enabled", "D"),
            ("trigger_type", 7),
            ("has_no_when_clause", False),
            ("has_no_update_column_filter", False),
            ("has_no_trigger_arguments", False),
            ("security_definer", False),
            ("has_safe_search_path", False),
            ("has_exact_body", False),
            ("checker_has_exact_kind", False),
            ("checker_has_safe_search_path", False),
            ("checker_has_exact_body", False),
            ("checker_has_safe_owner", False),
            ("checker_has_exact_acl", False),
            ("sentinel_has_exact_before_insert_triggers", False),
            ("document_policy_is_exact", False),
            ("function_has_exact_kind", False),
            ("function_has_safe_owner", False),
            ("function_has_exact_acl", False),
        ):
            with pytest.raises(ProjectionReceiptError, match="writer_fence_invalid"):
                await assert_strict_v4_writer_fence_topology(
                    _FenceConnection(tamper=(field, value))
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


def test_topology_query_pins_final_profile_without_auto_downgrade() -> None:
    class CapturingConnection(_FenceConnection):
        async def fetch(self, sql, *parameters):
            assert "JOIN canonical_checker ON canonical_checker.prosrc=expected.body" in sql
            assert "pg_catalog.cardinality(expected.execute_roles)" in sql
            assert "pg_catalog.array_agg(function.oid" in sql
            assert "pg_catalog.array_agg(candidate.tgname" in sql
            assert "to_regprocedure('public.' || name || '()')" in sql
            assert sql.count("function_schema.nspname='public'") == 1
            assert "procedure.provolatile='v'" in sql
            assert "language.lanname='plpgsql'" in sql
            assert "function.provolatile='v'" in sql
            assert "function_language.lanname='plpgsql'" in sql
            assert "acl.grantee<>procedure.proowner" in sql
            assert "acl.grantee=procedure.proowner" in sql
            assert "acl.grantee<>function.proowner" in sql
            assert "benchmark_writer_target' THEN $4" in sql
            assert "ELSE $5" in sql
            assert parameters[2] == "search_path=pg_catalog, public, pg_temp"
            assert parameters[1] == [
                "infinity_context_canonical_writer",
                "infinity_context_strict_v4_registrar",
                "infinity_context_strict_v4_sealer",
            ]
            assert "infinity_context_strict_v4_fact_writer" not in parameters[5]
            assert "infinity_context_strict_v4_document_writer" not in parameters[5]
            assert parameters[6] == "search_path=pg_catalog, public"
            assert parameters[7] == ["infinity_context_canonical_writer"]
            assert parameters[8][-2] == ("trg_memory_idempotency_benchmark_document_policy")
            assert parameters[9][-2] == ("memory_comparison_enforce_benchmark_document_idempotency")
            return await super().fetch(sql, *parameters)

    asyncio.run(assert_strict_v4_writer_fence_topology(CapturingConnection()))


def test_0036_profile_requires_explicit_selection() -> None:
    class CapturingConnection(_FenceConnection):
        async def fetch(self, sql, *parameters):
            assert "infinity_context_strict_v4_fact_writer" not in parameters[5]
            assert parameters[4] == _WRITER_POLICY_BODY_0036
            assert parameters[6] == "search_path=pg_catalog, public, pg_temp"
            assert parameters[7] == ["infinity_context_canonical_writer"]
            return await super().fetch(sql, *parameters)

    asyncio.run(_assert_strict_v4_writer_fence_topology_0036_compat(CapturingConnection()))

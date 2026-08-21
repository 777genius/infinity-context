"""PostgreSQL 18 proof for the strict-v4 0036 role and ACL boundary."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from dataclasses import replace

import pytest
from infinity_context_adapters.postgres.benchmark_writer_fence import (
    BENCHMARK_WRITER_FENCE_CONSTRAINT,
)
from infinity_context_adapters.postgres.strict_v4_database_roles import (
    STRICT_V4_CANONICAL_WRITER_ROLE,
    STRICT_V4_CAPABILITY_ROLES,
    STRICT_V4_PROTECTED_RELATIONS,
    STRICT_V4_REGISTRAR_ROLE,
    STRICT_V4_SEALER_ROLE,
    assert_strict_v4_runtime_capability,
)
from infinity_context_core.features.projection_receipts import ProjectionReceiptError
from postgres_test_database import PostgresTestDatabase
from sqlalchemy.engine import make_url
from strict_v4_0036_security_support import (
    PROTECTED_SEQUENCES,
    PROVISIONING_SQL,
    apply_0036,
    apply_0037_0038,
    assert_capability_roles_are_safe,
    assert_exact_0036_acls,
    assert_ordered_writer_triggers,
    assert_postgres_18,
    quote_identifier,
    role_list,
)
from strict_v4_adapter_replay_support import assert_adapter_seal_replay
from strict_v4_runtime_drift_support import assert_runtime_login_drift_rejected
from test_postgres_schema_upgrade_e2e import _install_versioned_schema_through

_POSTGRES_URL = "INFINITY_CONTEXT_TEST_POSTGRES_URL"
_PASSWORD = "strict-v4-0036-postgres18-only"
_ROLE_ERROR = "strict-v4-0036-role-rejected"


def test_0036_fresh_topology_on_postgres18_when_configured() -> None:
    database_url = os.getenv(_POSTGRES_URL)
    if not database_url:
        pytest.skip(f"{_POSTGRES_URL} is not configured")
    asyncio.run(_fresh_scenario(database_url))


def test_0036_hostile_upgrade_and_runtime_roles_on_postgres18_when_configured() -> None:
    database_url = os.getenv(_POSTGRES_URL)
    if not database_url:
        pytest.skip(f"{_POSTGRES_URL} is not configured")
    asyncio.run(_hostile_scenario(database_url))


async def _fresh_scenario(database_url: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(database_url, prefix="sv4_36_f", asyncpg=asyncpg)
    await database.recreate()
    try:
        connection = await database.connect()
        try:
            await assert_postgres_18(connection)
        finally:
            await connection.close()
        await _install_versioned_schema_through(database, "0035_")
        connection = await database.connect()
        try:
            await apply_0036(connection)
            await assert_capability_roles_are_safe(connection)
            await assert_exact_0036_acls(connection)
            await assert_ordered_writer_triggers(connection)
            assert await connection.fetchval(
                "SELECT pg_catalog.to_regclass("
                "'public.memory_comparison_strict_v4_preparations') IS NOT NULL"
            )
        finally:
            await connection.close()
    finally:
        await database.drop()


async def _hostile_scenario(database_url: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(database_url, prefix="sv4_36_h", asyncpg=asyncpg)
    migrator = f"{database.database_name}_migrator"
    bridge = f"{database.database_name}_bridge"
    runtime_roles: tuple[str, ...] = ()
    runtime_connections: dict[str, object] = {}
    await database.recreate()
    try:
        await _create_migrator(database, migrator=migrator, bridge=bridge)
        migrator_database = _database_as_role(database, role=migrator, password=_PASSWORD)
        await _install_versioned_schema_through(migrator_database, "0035_")
        canonical = await database.create_runtime_role(
            capability_role=STRICT_V4_CANONICAL_WRITER_ROLE,
            suffix="canonical",
        )
        registrar = await database.create_runtime_role(
            capability_role=STRICT_V4_REGISTRAR_ROLE,
            suffix="registrar",
        )
        sealer = await database.create_runtime_role(
            capability_role=STRICT_V4_SEALER_ROLE,
            suffix="sealer",
        )
        runtime_roles = (canonical, registrar, sealer)
        role_capabilities = (
            (canonical, STRICT_V4_CANONICAL_WRITER_ROLE),
            (registrar, STRICT_V4_REGISTRAR_ROLE),
            (sealer, STRICT_V4_SEALER_ROLE),
        )

        admin = await database.connect()
        migrator_connection = await migrator_database.connect()
        try:
            await assert_postgres_18(admin)
            await _assert_non_schema_owner_table_owner(
                admin,
                migrator=migrator,
            )
            await _assert_unsafe_capability_role_rejected(
                asyncpg,
                admin=admin,
                migrator_connection=migrator_connection,
            )
            await _assert_capability_owned_objects_rejected(
                asyncpg,
                admin=admin,
                migrator_connection=migrator_connection,
                migrator=migrator,
            )
            await _assert_schema_acl_drift_rejected(
                asyncpg,
                admin=admin,
                migrator_connection=migrator_connection,
            )
            await _seed_hostile_acls(
                admin=admin,
                owner=migrator_connection,
                runtime_roles=runtime_roles,
            )
            await _install_same_session_shadows(migrator_connection)
            await apply_0036(migrator_connection)
            await _assert_shadows_untouched(migrator_connection)
            await _assert_non_schema_owner_table_owner(
                admin,
                migrator=migrator,
                preparation_expected=True,
            )
            await assert_capability_roles_are_safe(admin)
            await assert_exact_0036_acls(admin)
            await assert_ordered_writer_triggers(admin)

            for runtime_role, capability in role_capabilities:
                connection = await database.connect_as_runtime_role(runtime_role)
                runtime_connections[runtime_role] = connection
                await _install_runtime_temp_shadows(connection)
                assert await connection.fetchval("SELECT current_user") == runtime_role
                with pytest.raises(ProjectionReceiptError, match=_ROLE_ERROR):
                    await assert_strict_v4_runtime_capability(
                        connection,
                        capability_role=capability,
                        error_code=_ROLE_ERROR,
                    )

            await _revoke_direct_login_acls(admin, runtime_roles=runtime_roles)

            async def registrar_connect():
                connection = await database.connect_as_runtime_role(registrar)
                await _install_runtime_temp_shadows(connection)
                return connection

            async def sealer_connect():
                connection = await database.connect_as_runtime_role(sealer)
                await _install_runtime_temp_shadows(connection)
                return connection

            await assert_adapter_seal_replay(
                asyncpg=asyncpg,
                owner=migrator_connection,
                canonical=runtime_connections[canonical],
                registrar_connect=registrar_connect,
                sealer_connect=sealer_connect,
            )
            await _assert_writer_authority_fence(
                asyncpg,
                owner=migrator_connection,
                canonical=runtime_connections[canonical],
                registrar=runtime_connections[registrar],
                sealer=runtime_connections[sealer],
            )

            await apply_0037_0038(migrator_connection)
            for runtime_role, capability in role_capabilities:
                await assert_strict_v4_runtime_capability(
                    runtime_connections[runtime_role],
                    capability_role=capability,
                    error_code=_ROLE_ERROR,
                )
            await assert_runtime_login_drift_rejected(
                admin=admin,
                connection=runtime_connections[registrar],
                login=registrar,
                capability=STRICT_V4_REGISTRAR_ROLE,
                migrator=migrator,
                error_code=_ROLE_ERROR,
            )
            await _assert_public_acl_drift_rejected(
                admin=admin,
                role_capabilities=role_capabilities,
                connections=runtime_connections,
            )
            await _assert_wrong_capability_privilege_rejected(
                admin=admin,
                registrar_connection=runtime_connections[registrar],
            )
            await _assert_set_role_rejected(
                role_capabilities=role_capabilities,
                connections=runtime_connections,
            )
            await _assert_multicap_rejected(
                admin=admin,
                canonical_login=canonical,
                canonical_connection=runtime_connections[canonical],
            )
            await _assert_transitive_membership_rejected(
                admin=admin,
                bridge=bridge,
                registrar_login=registrar,
                registrar_connection=runtime_connections[registrar],
            )

        finally:
            for connection in runtime_connections.values():
                await connection.close()
            await migrator_connection.close()
            await admin.close()
    finally:
        await database.drop()
        cleanup_roles = (*runtime_roles, bridge, migrator)
        await database.drop_runtime_roles(*cleanup_roles)


async def _create_migrator(database, *, migrator: str, bridge: str) -> None:
    admin = await database.connect()
    try:
        await admin.execute(
            f"CREATE ROLE {quote_identifier(migrator)} LOGIN PASSWORD '{_PASSWORD}' "
            "NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
        )
        await admin.execute(
            f"CREATE ROLE {quote_identifier(bridge)} NOLOGIN NOSUPERUSER NOCREATEDB "
            "NOCREATEROLE NOREPLICATION NOBYPASSRLS"
        )
        await admin.execute(
            f"GRANT CREATE ON DATABASE {quote_identifier(database.database_name)} "
            f"TO {quote_identifier(migrator)}"
        )
        await admin.execute(f"GRANT CREATE ON SCHEMA public TO {quote_identifier(migrator)}")
        await admin.execute(f"CREATE SCHEMA hostile AUTHORIZATION {quote_identifier(migrator)}")
        await admin.execute("GRANT USAGE ON SCHEMA hostile TO PUBLIC")
    finally:
        await admin.close()


def _database_as_role(database, *, role: str, password: str):
    raw_url = make_url(database.raw_dsn).set(username=role, password=password)
    return replace(database, raw_dsn=raw_url.render_as_string(hide_password=False))


async def _expect_0036_rejected(asyncpg, connection) -> None:
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await apply_0036(connection)


async def _assert_unsafe_capability_role_rejected(
    asyncpg,
    *,
    admin,
    migrator_connection,
) -> None:
    capability = quote_identifier(STRICT_V4_CANONICAL_WRITER_ROLE)
    await admin.execute(f"ALTER ROLE {capability} LOGIN")
    try:
        await _expect_0036_rejected(asyncpg, migrator_connection)
    finally:
        await admin.execute(f"ALTER ROLE {capability} NOLOGIN")


async def _assert_non_schema_owner_table_owner(
    admin,
    *,
    migrator: str,
    preparation_expected: bool = False,
) -> None:
    schema_owner = await admin.fetchval(
        """
        SELECT owner.rolname
        FROM pg_catalog.pg_namespace AS namespace
        JOIN pg_catalog.pg_roles AS owner ON owner.oid=namespace.nspowner
        WHERE namespace.nspname='public'
        """
    )
    assert schema_owner != migrator
    assert not await admin.fetchval(
        "SELECT rolcreaterole FROM pg_catalog.pg_roles WHERE rolname=$1",
        migrator,
    )
    table = (
        "memory_comparison_strict_v4_preparations"
        if preparation_expected
        else "memory_idempotency_records"
    )
    assert (
        await admin.fetchval(
            """
        SELECT owner.rolname
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid=relation.relnamespace
        JOIN pg_catalog.pg_roles AS owner ON owner.oid=relation.relowner
        WHERE namespace.nspname='public' AND relation.relname=$1
        """,
            table,
        )
        == migrator
    )


async def _assert_capability_owned_objects_rejected(
    asyncpg,
    *,
    admin,
    migrator_connection,
    migrator: str,
) -> None:
    capability = quote_identifier(STRICT_V4_CANONICAL_WRITER_ROLE)
    owner = quote_identifier(migrator)
    await admin.execute(f"ALTER TABLE public.memory_idempotency_records OWNER TO {capability}")
    try:
        await _expect_0036_rejected(asyncpg, migrator_connection)
    finally:
        await admin.execute(f"ALTER TABLE public.memory_idempotency_records OWNER TO {owner}")

    await admin.execute(
        "ALTER FUNCTION public.memory_comparison_enforce_benchmark_writer_fence() "
        f"OWNER TO {capability}"
    )
    try:
        await _expect_0036_rejected(asyncpg, migrator_connection)
    finally:
        await admin.execute(
            "ALTER FUNCTION public.memory_comparison_enforce_benchmark_writer_fence() "
            f"OWNER TO {owner}"
        )

    schema_owner = await admin.fetchval(
        """
        SELECT owner.rolname
        FROM pg_catalog.pg_namespace AS namespace
        JOIN pg_catalog.pg_roles AS owner ON owner.oid=namespace.nspowner
        WHERE namespace.nspname='public'
        """
    )
    await admin.execute(f"ALTER SCHEMA public OWNER TO {capability}")
    try:
        await _expect_0036_rejected(asyncpg, migrator_connection)
    finally:
        await admin.execute(f"ALTER SCHEMA public OWNER TO {quote_identifier(str(schema_owner))}")


async def _assert_schema_acl_drift_rejected(asyncpg, *, admin, migrator_connection) -> None:
    capabilities = role_list(tuple(STRICT_V4_CAPABILITY_ROLES))
    await admin.execute("GRANT CREATE ON SCHEMA public TO PUBLIC")
    await admin.execute(f"GRANT CREATE ON SCHEMA public TO {capabilities} WITH GRANT OPTION")
    await _expect_0036_rejected(asyncpg, migrator_connection)
    await admin.execute(PROVISIONING_SQL)


async def _seed_hostile_acls(*, admin, owner, runtime_roles: tuple[str, ...]) -> None:
    capabilities = role_list(tuple(STRICT_V4_CAPABILITY_ROLES))
    logins = role_list(runtime_roles)
    table_rows = await owner.fetch(
        """
        SELECT relation.relname
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid=relation.relnamespace
        WHERE namespace.nspname='public'
          AND relation.relkind <> 'S'
          AND relation.relname=ANY($1::pg_catalog.text[])
        ORDER BY relation.relname
        """,
        list(STRICT_V4_PROTECTED_RELATIONS),
    )
    for row in table_rows:
        table = quote_identifier(row["relname"])
        await owner.execute(f"GRANT ALL PRIVILEGES ON TABLE public.{table} TO PUBLIC")
        await owner.execute(
            f"GRANT ALL PRIVILEGES ON TABLE public.{table} TO {capabilities} WITH GRANT OPTION"
        )
        await owner.execute(f"GRANT ALL PRIVILEGES ON TABLE public.{table} TO {logins}")

    column_grant = (
        "SELECT (key), INSERT (key), UPDATE (key), REFERENCES (key) "
        "ON TABLE public.memory_idempotency_records"
    )
    await owner.execute(f"GRANT {column_grant} TO PUBLIC")
    await owner.execute(f"GRANT {column_grant} TO {capabilities} WITH GRANT OPTION")
    await owner.execute(f"GRANT {column_grant} TO {logins}")

    for sequence in PROTECTED_SEQUENCES:
        sequence_name = quote_identifier(sequence)
        await owner.execute(f"GRANT ALL PRIVILEGES ON SEQUENCE public.{sequence_name} TO PUBLIC")
        await owner.execute(
            f"GRANT ALL PRIVILEGES ON SEQUENCE public.{sequence_name} "
            f"TO {capabilities} WITH GRANT OPTION"
        )
        await owner.execute(f"GRANT ALL PRIVILEGES ON SEQUENCE public.{sequence_name} TO {logins}")

    function = "public.memory_comparison_enforce_benchmark_writer_fence()"
    await owner.execute(f"GRANT ALL PRIVILEGES ON FUNCTION {function} TO PUBLIC")
    await owner.execute(
        f"GRANT ALL PRIVILEGES ON FUNCTION {function} TO {capabilities} WITH GRANT OPTION"
    )
    await owner.execute(f"GRANT ALL PRIVILEGES ON FUNCTION {function} TO {logins}")
    await owner.execute(
        "DROP TRIGGER trg_memory_spaces_benchmark_writer_fence ON public.memory_spaces"
    )
    await owner.execute(
        "CREATE TRIGGER trg_memory_spaces_benchmark_writer_fence "
        "BEFORE INSERT OR UPDATE OR DELETE ON public.memory_spaces "
        "FOR EACH ROW WHEN (FALSE) EXECUTE FUNCTION "
        "public.memory_comparison_enforce_benchmark_writer_fence()"
    )
    await admin.execute(f"GRANT USAGE ON SCHEMA public TO {logins}")


async def _install_same_session_shadows(connection) -> None:
    await connection.execute(
        "CREATE TABLE hostile.memory_comparison_strict_v4_preparations(shadow text)"
    )
    await connection.execute(
        "INSERT INTO hostile.memory_comparison_strict_v4_preparations VALUES('persistent')"
    )
    await connection.execute(
        """
        CREATE FUNCTION hostile.memory_comparison_is_strict_v4_canonical_writer()
        RETURNS boolean LANGUAGE sql IMMUTABLE AS 'SELECT false'
        """
    )
    await connection.execute("SET search_path=pg_temp, hostile, public")
    for table in (
        "memory_comparison_benchmark_runs",
        "memory_cleanup_v3_context_authorities",
        "memory_comparison_strict_v4_preparations",
        "memory_idempotency_records",
    ):
        await connection.execute(f"CREATE TEMP TABLE {table}(shadow text)")
        await connection.execute(f"INSERT INTO pg_temp.{table} VALUES('temporary')")
    await connection.execute(
        """
        CREATE FUNCTION pg_temp.pg_has_role(name, text, text)
        RETURNS boolean LANGUAGE sql IMMUTABLE AS 'SELECT true'
        """
    )
    await connection.execute(
        """
        CREATE FUNCTION pg_temp.memory_comparison_is_strict_v4_canonical_writer()
        RETURNS boolean LANGUAGE sql IMMUTABLE AS 'SELECT false'
        """
    )


async def _assert_shadows_untouched(connection) -> None:
    assert (
        await connection.fetchval(
            "SELECT shadow FROM pg_temp.memory_comparison_strict_v4_preparations"
        )
        == "temporary"
    )
    assert (
        await connection.fetchval(
            "SELECT shadow FROM hostile.memory_comparison_strict_v4_preparations"
        )
        == "persistent"
    )
    assert not await connection.fetchval(
        "SELECT hostile.memory_comparison_is_strict_v4_canonical_writer()"
    )
    assert not await connection.fetchval(
        "SELECT pg_temp.memory_comparison_is_strict_v4_canonical_writer()"
    )
    assert await connection.fetchval(
        "SELECT pg_temp.pg_has_role('shadow'::pg_catalog.name, 'shadow', 'MEMBER')"
    )
    assert await connection.fetchval(
        """
        SELECT pg_catalog.count(*) > 10
        FROM pg_catalog.pg_attribute AS attribute
        JOIN pg_catalog.pg_class AS relation ON relation.oid=attribute.attrelid
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid=relation.relnamespace
        WHERE namespace.nspname='public'
          AND relation.relname='memory_comparison_strict_v4_preparations'
          AND attribute.attnum > 0
          AND NOT attribute.attisdropped
        """
    )


async def _install_runtime_temp_shadows(connection) -> None:
    await connection.execute("SET search_path=pg_temp, hostile, public")
    for table in (
        "memory_comparison_benchmark_runs",
        "memory_cleanup_v3_context_authorities",
        "memory_comparison_strict_v4_preparations",
    ):
        await connection.execute(f"CREATE TEMP TABLE {table}(shadow text)")
    await connection.execute(
        """
        CREATE FUNCTION pg_temp.pg_has_role(name, text, text)
        RETURNS boolean LANGUAGE sql IMMUTABLE AS 'SELECT true'
        """
    )


async def _revoke_direct_login_acls(admin, *, runtime_roles: tuple[str, ...]) -> None:
    logins = role_list(runtime_roles)
    await admin.execute(f"REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM {logins}")
    await admin.execute(
        "REVOKE SELECT (key), INSERT (key), UPDATE (key), REFERENCES (key) "
        f"ON TABLE public.memory_idempotency_records FROM {logins}"
    )
    await admin.execute(f"REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM {logins}")
    await admin.execute(f"REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public FROM {logins}")
    await admin.execute(f"REVOKE ALL PRIVILEGES ON SCHEMA public FROM {logins}")


async def _assert_public_acl_drift_rejected(
    *,
    admin,
    role_capabilities,
    connections,
) -> None:
    await admin.execute("GRANT SELECT ON public.memory_spaces TO PUBLIC")
    try:
        for runtime_role, capability in role_capabilities:
            with pytest.raises(ProjectionReceiptError, match=_ROLE_ERROR):
                await assert_strict_v4_runtime_capability(
                    connections[runtime_role],
                    capability_role=capability,
                    error_code=_ROLE_ERROR,
                )
    finally:
        await admin.execute("REVOKE SELECT ON public.memory_spaces FROM PUBLIC")
    for runtime_role, capability in role_capabilities:
        await assert_strict_v4_runtime_capability(
            connections[runtime_role],
            capability_role=capability,
            error_code=_ROLE_ERROR,
        )


async def _assert_wrong_capability_privilege_rejected(
    *,
    admin,
    registrar_connection,
) -> None:
    await admin.execute(
        f"GRANT UPDATE ON public.memory_comparison_benchmark_runs TO {STRICT_V4_REGISTRAR_ROLE}"
    )
    try:
        with pytest.raises(ProjectionReceiptError, match=_ROLE_ERROR):
            await assert_strict_v4_runtime_capability(
                registrar_connection,
                capability_role=STRICT_V4_REGISTRAR_ROLE,
                error_code=_ROLE_ERROR,
            )
    finally:
        await admin.execute(
            "REVOKE UPDATE ON public.memory_comparison_benchmark_runs "
            f"FROM {STRICT_V4_REGISTRAR_ROLE}"
        )
    await assert_strict_v4_runtime_capability(
        registrar_connection,
        capability_role=STRICT_V4_REGISTRAR_ROLE,
        error_code=_ROLE_ERROR,
    )


async def _assert_set_role_rejected(*, role_capabilities, connections) -> None:
    for runtime_role, capability in role_capabilities:
        connection = connections[runtime_role]
        with pytest.raises(pytest.importorskip("asyncpg").InsufficientPrivilegeError):
            await connection.execute(f"SET ROLE {quote_identifier(capability)}")


async def _assert_multicap_rejected(
    *,
    admin,
    canonical_login: str,
    canonical_connection,
) -> None:
    login = quote_identifier(canonical_login)
    await admin.execute(f"GRANT {STRICT_V4_REGISTRAR_ROLE} TO {login}")
    try:
        with pytest.raises(ProjectionReceiptError, match=_ROLE_ERROR):
            await assert_strict_v4_runtime_capability(
                canonical_connection,
                capability_role=STRICT_V4_CANONICAL_WRITER_ROLE,
                error_code=_ROLE_ERROR,
            )
    finally:
        await admin.execute(f"REVOKE {STRICT_V4_REGISTRAR_ROLE} FROM {login}")
    await assert_strict_v4_runtime_capability(
        canonical_connection,
        capability_role=STRICT_V4_CANONICAL_WRITER_ROLE,
        error_code=_ROLE_ERROR,
    )


async def _assert_transitive_membership_rejected(
    *,
    admin,
    bridge: str,
    registrar_login: str,
    registrar_connection,
) -> None:
    login = quote_identifier(registrar_login)
    bridge_role = quote_identifier(bridge)
    await admin.execute(f"REVOKE {STRICT_V4_REGISTRAR_ROLE} FROM {login}")
    await admin.execute(f"GRANT {STRICT_V4_REGISTRAR_ROLE} TO {bridge_role}")
    await admin.execute(f"GRANT {bridge_role} TO {login}")
    try:
        with pytest.raises(ProjectionReceiptError, match=_ROLE_ERROR):
            await assert_strict_v4_runtime_capability(
                registrar_connection,
                capability_role=STRICT_V4_REGISTRAR_ROLE,
                error_code=_ROLE_ERROR,
            )
    finally:
        await admin.execute(f"REVOKE {bridge_role} FROM {login}")
        await admin.execute(f"REVOKE {STRICT_V4_REGISTRAR_ROLE} FROM {bridge_role}")
        await admin.execute(f"GRANT {STRICT_V4_REGISTRAR_ROLE} TO {login}")
    await assert_strict_v4_runtime_capability(
        registrar_connection,
        capability_role=STRICT_V4_REGISTRAR_ROLE,
        error_code=_ROLE_ERROR,
    )


def _digest(suffix: str, field: str) -> str:
    return hashlib.sha256(f"0036:{suffix}:{field}".encode()).hexdigest()


async def _seed_fence_run(owner, *, suffix: str, legacy: bool) -> None:
    run_id = _digest(suffix, "run")
    space_id = f"strict-v4-0036-{suffix}"
    await owner.execute(
        """
        INSERT INTO public.memory_spaces(id,slug,name,status,created_at,updated_at)
        VALUES($1,$1,$1,'active',pg_catalog.clock_timestamp(),
               pg_catalog.clock_timestamp())
        """,
        space_id,
    )
    await owner.execute(
        """
        INSERT INTO public.memory_comparison_benchmark_runs(
          run_id_sha256,binding_commitment_sha256,infinity_target_identity_sha256,
          space_id,space_slug,idempotency_key_sha256,registration_fingerprint_sha256,
          state,cleanup_plan_json,cleanup_plan_sha256,cleanup_plan_state,
          created_at,updated_at)
        VALUES($1,$2,$3,$4,$4,$5,$6,'active',$7::pg_catalog.jsonb,$8,$9,
               pg_catalog.clock_timestamp(),pg_catalog.clock_timestamp())
        """,
        run_id,
        _digest(suffix, "binding"),
        _digest(suffix, "target"),
        space_id,
        _digest(suffix, "idempotency"),
        _digest(suffix, "registration"),
        "{}" if legacy else None,
        _digest(suffix, "plan") if legacy else None,
        "sealed" if legacy else "recovery_blocked",
    )


async def _seed_fence_context(owner, *, suffix: str) -> None:
    await owner.execute(
        """
        INSERT INTO public.memory_cleanup_v3_context_authorities(
          run_id_sha256,context_sha256,authority_terminal_sha256,
          context_json,authority_json,registration_sha256,
          registration_mac_sha256,registered_at)
        VALUES($1,$2,$3,'{}'::pg_catalog.jsonb,'{}'::pg_catalog.jsonb,$4,$5,
               pg_catalog.clock_timestamp())
        """,
        _digest(suffix, "run"),
        _digest(suffix, "context"),
        _digest(suffix, "terminal"),
        _digest(suffix, "registration-sha"),
        _digest(suffix, "registration-mac"),
    )


async def _seed_fence_seal(sealer, *, suffix: str) -> None:
    run_id = _digest(suffix, "run")
    context = _digest(suffix, "context")
    terminal = _digest(suffix, "terminal")
    receipt_sha = _digest(suffix, "receipt")
    receipt_mac = _digest(suffix, "receipt-mac")
    registration_sha = _digest(suffix, "registration-sha")
    registration_mac = _digest(suffix, "registration-mac")
    writer_sha = _digest(suffix, "writer")
    writer_mac = _digest(suffix, "writer-mac")
    sealed_at = await sealer.fetchval("SELECT pg_catalog.clock_timestamp()")
    sealed_at_text = sealed_at.isoformat()
    receipt = {
        "schema_version": "memory-comparison-strict-v4-full-preparation.v1",
        "run_id_sha256": run_id,
        "a2_context": {"context_sha256": context},
        "a2_authority": {"terminal_commitment_sha256": terminal},
        "receipt_sha256": receipt_sha,
        "receipt_mac_sha256": receipt_mac,
        "registration_sha256": registration_sha,
        "registration_mac_sha256": registration_mac,
        "provider_calls": 0,
        "paid_go_ready": False,
        "prepared_at": sealed_at_text,
        "registered_at": sealed_at_text,
    }
    authority = {
        "schema_version": "memory-comparison-strict-v4-writer-authority.v1",
        "run_id_sha256": run_id,
        "context_sha256": context,
        "authority_terminal_sha256": terminal,
        "preparation_receipt_sha256": receipt_sha,
        "preparation_receipt_mac_sha256": receipt_mac,
        "registration_sha256": registration_sha,
        "registration_mac_sha256": registration_mac,
        "a2_terminal_commitment_sha256": terminal,
        "expected_index_terminal_sha256": terminal,
        "provider_calls": 0,
        "paid_go_ready": False,
        "writer_authority_sha256": writer_sha,
        "writer_authority_mac_sha256": writer_mac,
        "sealed_at": sealed_at_text,
    }
    await sealer.execute(
        """
        INSERT INTO public.memory_comparison_strict_v4_preparations(
          run_id_sha256,context_sha256,authority_terminal_sha256,
          preparation_receipt_json,preparation_receipt_sha256,
          preparation_receipt_mac_sha256,writer_authority_json,
          writer_authority_sha256,writer_authority_mac_sha256,
          registration_sha256,registration_mac_sha256,
          provider_calls,paid_go_ready,state,sealed_at)
        VALUES($1,$2,$3,$4::pg_catalog.jsonb,$5,$6,$7::pg_catalog.jsonb,$8,$9,
               $10,$11,0,FALSE,'sealed',$12)
        """,
        run_id,
        context,
        terminal,
        json.dumps(receipt),
        receipt_sha,
        receipt_mac,
        json.dumps(authority),
        writer_sha,
        writer_mac,
        registration_sha,
        registration_mac,
        sealed_at,
    )


async def _insert_sentinel(connection, *, suffix: str, key: str) -> None:
    await connection.execute(
        """
        INSERT INTO public.memory_idempotency_records(
          space_id,key,fingerprint,result_type,result_id,created_at)
        VALUES($1,$2,$2,'strict-v4',$2,pg_catalog.clock_timestamp())
        """,
        f"strict-v4-0036-{suffix}",
        key,
    )


async def _assert_sentinel_fenced(asyncpg, connection, *, suffix: str, key: str) -> None:
    with pytest.raises(asyncpg.CheckViolationError) as rejected:
        await _insert_sentinel(connection, suffix=suffix, key=key)
    assert rejected.value.constraint_name == BENCHMARK_WRITER_FENCE_CONSTRAINT


async def _assert_writer_authority_fence(
    asyncpg,
    *,
    owner,
    canonical,
    registrar,
    sealer,
) -> None:
    await _seed_fence_run(owner, suffix="strict", legacy=False)
    await _assert_sentinel_fenced(
        asyncpg, canonical, suffix="strict", key="strict-neither-canonical"
    )
    await _assert_sentinel_fenced(asyncpg, owner, suffix="strict", key="strict-neither-legacy")

    await _seed_fence_context(registrar, suffix="strict")
    await _assert_sentinel_fenced(
        asyncpg, canonical, suffix="strict", key="registration-only-canonical"
    )
    await _assert_sentinel_fenced(asyncpg, owner, suffix="strict", key="registration-only-legacy")
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await _insert_sentinel(registrar, suffix="strict", key="registrar-cannot-write")

    await _seed_fence_seal(sealer, suffix="strict")
    before = await sealer.fetchrow(
        "SELECT * FROM public.memory_comparison_strict_v4_preparations WHERE run_id_sha256=$1",
        _digest("strict", "run"),
    )
    canonical_login = quote_identifier(await canonical.fetchval("SELECT current_user"))
    for label, grantee in (
        ("public", "PUBLIC"),
        ("capability", STRICT_V4_CANONICAL_WRITER_ROLE),
        ("direct", canonical_login),
    ):
        await owner.execute("GRANT UPDATE (key) ON public.memory_idempotency_records TO " + grantee)
        try:
            await _assert_sentinel_fenced(
                asyncpg, canonical, suffix="strict", key=f"column-drift-{label}"
            )
        finally:
            await owner.execute(
                "REVOKE UPDATE (key) ON public.memory_idempotency_records FROM " + grantee
            )
    await owner.execute(
        "GRANT EXECUTE ON FUNCTION "
        "public.memory_comparison_lock_strict_v4_seal_targets("
        "pg_catalog.bpchar,pg_catalog.bpchar) "
        f"TO {STRICT_V4_CANONICAL_WRITER_ROLE}"
    )
    try:
        await _assert_sentinel_fenced(asyncpg, canonical, suffix="strict", key="function-drift")
    finally:
        await owner.execute(
            "REVOKE EXECUTE ON FUNCTION "
            "public.memory_comparison_lock_strict_v4_seal_targets("
            "pg_catalog.bpchar,pg_catalog.bpchar) "
            f"FROM {STRICT_V4_CANONICAL_WRITER_ROLE}"
        )
    await _insert_sentinel(canonical, suffix="strict", key="strict-sentinel")
    after = await sealer.fetchrow(
        "SELECT * FROM public.memory_comparison_strict_v4_preparations WHERE run_id_sha256=$1",
        _digest("strict", "run"),
    )
    assert before == after
    await _assert_sentinel_fenced(asyncpg, owner, suffix="strict", key="strict-owner-rejected")
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await canonical.execute(
            "INSERT INTO public.memory_facts(space_id) VALUES($1)",
            "strict-v4-0036-strict",
        )

    with pytest.raises(asyncpg.CheckViolationError):
        await owner.execute(
            "UPDATE public.memory_cleanup_v3_context_authorities "
            "SET registration_mac_sha256=$2 WHERE run_id_sha256=$1",
            _digest("strict", "run"),
            "f" * 64,
        )
    with pytest.raises(asyncpg.CheckViolationError):
        await owner.execute(
            "UPDATE public.memory_comparison_strict_v4_preparations "
            "SET writer_authority_mac_sha256=$2 WHERE run_id_sha256=$1",
            _digest("strict", "run"),
            "e" * 64,
        )

    await owner.execute(
        """
        UPDATE public.memory_comparison_benchmark_runs
        SET cleanup_plan_json='{}'::pg_catalog.jsonb,
            cleanup_plan_sha256=$2, cleanup_plan_state='sealed'
        WHERE run_id_sha256=$1
        """,
        _digest("strict", "run"),
        _digest("strict", "legacy-plan"),
    )
    await _assert_sentinel_fenced(
        asyncpg, canonical, suffix="strict", key="both-canonical-rejected"
    )
    await _assert_sentinel_fenced(asyncpg, owner, suffix="strict", key="both-legacy-rejected")

    await _seed_fence_run(owner, suffix="legacy", legacy=True)
    await _insert_sentinel(owner, suffix="legacy", key="legacy-only-accepted")
    await _assert_sentinel_fenced(
        asyncpg, canonical, suffix="legacy", key="legacy-canonical-rejected"
    )

    await _seed_fence_run(owner, suffix="neither", legacy=False)
    await _assert_sentinel_fenced(
        asyncpg, canonical, suffix="neither", key="neither-canonical-rejected"
    )
    await _assert_sentinel_fenced(asyncpg, owner, suffix="neither", key="neither-legacy-rejected")

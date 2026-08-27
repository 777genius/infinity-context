"""Fresh PostgreSQL 18 proof for the self-host identity bootstrap boundary."""

from __future__ import annotations

import asyncio
import os
import subprocess
from contextlib import suppress

import pytest
from infinity_context_adapters.postgres.migration_runner import upgrade_schema
from infinity_context_adapters.postgres.runtime_acl import reconcile_runtime_acl
from infinity_context_adapters.postgres.selfhost_login_provisioning import (
    SELFHOST_CANONICAL_WRITER_LOGIN_ROLE,
    SELFHOST_MIGRATOR_ROLE,
    SELFHOST_REGISTRAR_LOGIN_ROLE,
    SELFHOST_RUNTIME_ROLE,
    SELFHOST_SEALER_LOGIN_ROLE,
    SelfHostLoginPasswords,
    provision_selfhost_login_identities,
    rotate_selfhost_login_passwords,
)
from infinity_context_adapters.postgres.unit_of_work import build_async_engine
from sqlalchemy.engine import make_url

_POSTGRES_URL = "INFINITY_CONTEXT_SELFHOST_TEST_POSTGRES_URL"
_POSTGRES16_URL = "INFINITY_CONTEXT_SELFHOST_TEST_POSTGRES16_URL"
_PG_DUMP_IMAGE = "INFINITY_CONTEXT_SELFHOST_TEST_PG_DUMP_IMAGE"
_ROLES = (
    SELFHOST_MIGRATOR_ROLE,
    SELFHOST_RUNTIME_ROLE,
    SELFHOST_CANONICAL_WRITER_LOGIN_ROLE,
    SELFHOST_REGISTRAR_LOGIN_ROLE,
    SELFHOST_SEALER_LOGIN_ROLE,
)
_PASSWORDS = SelfHostLoginPasswords(
    migrator="selfhost-e2e-migrator-v1",
    runtime="selfhost-e2e-runtime-v1",
    canonical_writer="selfhost-e2e-canonical-v1",
    registrar="selfhost-e2e-registrar-v1",
    sealer="selfhost-e2e-sealer-v1",
)
_ROTATED_PASSWORDS = SelfHostLoginPasswords(
    migrator="selfhost-e2e-migrator-v2",
    runtime="selfhost-e2e-runtime-v2",
    canonical_writer="selfhost-e2e-canonical-v2",
    registrar="selfhost-e2e-registrar-v2",
    sealer="selfhost-e2e-sealer-v2",
)


def test_fresh_selfhost_identity_bootstrap_is_idempotent_and_rotatable() -> None:
    asyncio.run(_run_fresh_selfhost_identity_bootstrap())


def test_pg16_logical_restore_transfers_application_ownership() -> None:
    asyncio.run(_run_pg16_logical_restore_upgrade())


async def _run_fresh_selfhost_identity_bootstrap() -> None:
    database_url = os.getenv(_POSTGRES_URL)
    if not database_url:
        pytest.skip(f"{_POSTGRES_URL} is not configured")
    asyncpg = pytest.importorskip("asyncpg")
    admin_dsn, database_name = _database_target(database_url)
    admin_engine = build_async_engine(_async_url(admin_dsn))
    target_admin_engine = None
    migrator_engine = None
    try:
        await _drop_test_state(asyncpg, admin_dsn, database_name)
        await _create_admin_owned_database(asyncpg, admin_dsn, database_name)
        target_admin_engine = build_async_engine(
            _async_url(_admin_database_url(admin_dsn, database_name))
        )
        await provision_selfhost_login_identities(target_admin_engine, _PASSWORDS)
        await provision_selfhost_login_identities(target_admin_engine, _PASSWORDS)
        await _assert_hostile_capability_grantee_is_rejected(
            asyncpg, admin_dsn, target_admin_engine
        )
        await _assert_admin_ownership_and_migrator_acl(asyncpg, admin_dsn, database_name)

        migrator_url = _login_url(
            admin_dsn, database_name, SELFHOST_MIGRATOR_ROLE, _PASSWORDS.migrator
        )
        migrator_engine = build_async_engine(_async_url(migrator_url))
        first = await upgrade_schema(migrator_engine)
        assert first.applied
        assert (await upgrade_schema(migrator_engine)).applied == ()
        await _assert_migrator_object_ownership(asyncpg, admin_dsn, database_name)
        await reconcile_runtime_acl(migrator_engine)
        await reconcile_runtime_acl(migrator_engine)

        await _assert_role_contract(asyncpg, admin_dsn)
        await _assert_runtime_boundary(asyncpg, admin_dsn, database_name)

        await rotate_selfhost_login_passwords(target_admin_engine, _ROTATED_PASSWORDS)
        for role, old, new in zip(
            _ROLES, _PASSWORDS.values(), _ROTATED_PASSWORDS.values(), strict=True
        ):
            with pytest.raises(asyncpg.InvalidPasswordError):
                await asyncpg.connect(_login_url(admin_dsn, database_name, role, old))
            connection = await asyncpg.connect(_login_url(admin_dsn, database_name, role, new))
            await connection.close()
    finally:
        if migrator_engine is not None:
            await migrator_engine.dispose()
        if target_admin_engine is not None:
            await target_admin_engine.dispose()
        await admin_engine.dispose()
        await _drop_test_state(asyncpg, admin_dsn, database_name)


async def _run_pg16_logical_restore_upgrade() -> None:
    target_url = os.getenv(_POSTGRES_URL)
    source_url = os.getenv(_POSTGRES16_URL)
    client_image = os.getenv(_PG_DUMP_IMAGE)
    if not target_url or not source_url or not client_image:
        pytest.skip(
            f"{_POSTGRES_URL}, {_POSTGRES16_URL}, and {_PG_DUMP_IMAGE} are required"
        )
    asyncpg = pytest.importorskip("asyncpg")
    admin_dsn, database_name = _database_target(target_url)
    target_admin_engine = None
    migrator_engine = None
    try:
        await _drop_test_state(asyncpg, admin_dsn, database_name)
        await _prepare_pg16_restore_source(asyncpg, source_url)
        await _create_admin_owned_database(asyncpg, admin_dsn, database_name)
        await asyncio.to_thread(
            _logical_dump_restore,
            source_url,
            _admin_database_url(admin_dsn, database_name),
            client_image,
        )

        target_admin_engine = build_async_engine(
            _async_url(_admin_database_url(admin_dsn, database_name))
        )
        await provision_selfhost_login_identities(target_admin_engine, _PASSWORDS)
        await _assert_restored_probe(asyncpg, admin_dsn, database_name)

        migrator_url = _login_url(
            admin_dsn, database_name, SELFHOST_MIGRATOR_ROLE, _PASSWORDS.migrator
        )
        migrator_engine = build_async_engine(_async_url(migrator_url))
        target_upgrade = await upgrade_schema(migrator_engine)
        assert not target_upgrade.applied
        assert not target_upgrade.legacy_baseline
        await reconcile_runtime_acl(migrator_engine)
        await _assert_migrator_object_ownership(asyncpg, admin_dsn, database_name)
        await _assert_runtime_boundary(asyncpg, admin_dsn, database_name)
    finally:
        if migrator_engine is not None:
            await migrator_engine.dispose()
        if target_admin_engine is not None:
            await target_admin_engine.dispose()
        await _drop_test_state(asyncpg, admin_dsn, database_name)


async def _prepare_pg16_restore_source(asyncpg, source_url: str) -> None:
    source_engine = build_async_engine(_async_url(source_url))
    try:
        await provision_selfhost_login_identities(source_engine, _PASSWORDS)
        source_upgrade = await upgrade_schema(source_engine)
        assert source_upgrade.applied
    finally:
        await source_engine.dispose()

    source = await asyncpg.connect(source_url)
    try:
        await source.execute(
            """
            DROP FUNCTION IF EXISTS public.selfhost_restore_probe_count();
            DROP TABLE IF EXISTS public.selfhost_restore_probe;
            CREATE TABLE public.selfhost_restore_probe (
                id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                payload text NOT NULL
            );
            INSERT INTO public.selfhost_restore_probe (payload)
            VALUES ('preserved-from-postgres-16');
            CREATE FUNCTION public.selfhost_restore_probe_count()
            RETURNS bigint
            LANGUAGE sql
            STABLE
            AS 'SELECT count(*) FROM public.selfhost_restore_probe';
            """
        )
    finally:
        await source.close()


def _logical_dump_restore(source_url: str, target_url: str, image: str) -> None:
    dump = subprocess.run(
        _postgres_client_command(image, source_url, "pg_dump")
        + ["--format=custom", "--no-owner", "--no-acl"],
        check=True,
        capture_output=True,
        env=_postgres_password_environment(source_url),
    ).stdout
    subprocess.run(
        _postgres_client_command(image, target_url, "pg_restore")
        + ["--exit-on-error", "--no-owner", "--no-acl"],
        check=True,
        capture_output=True,
        env=_postgres_password_environment(target_url),
        input=dump,
    )


def _postgres_client_command(image: str, url: str, program: str) -> list[str]:
    parsed = make_url(url)
    if not parsed.host or not parsed.port or not parsed.username or not parsed.database:
        raise RuntimeError("self-host restore E2E PostgreSQL URL is incomplete")
    return [
        "docker",
        "run",
        "--rm",
        "--interactive",
        "--network",
        "host",
        "-e",
        "PGPASSWORD",
        image,
        program,
        "--host",
        parsed.host,
        "--port",
        str(parsed.port),
        "--username",
        parsed.username,
        "--dbname",
        parsed.database,
    ]


def _postgres_password_environment(url: str) -> dict[str, str]:
    password = make_url(url).password
    if password is None:
        raise RuntimeError("self-host restore E2E PostgreSQL password is required")
    return {**os.environ, "PGPASSWORD": password}


async def _assert_restored_probe(asyncpg, admin_dsn: str, database: str) -> None:
    admin = await asyncpg.connect(_admin_database_url(admin_dsn, database))
    try:
        assert await admin.fetchval(
            "SELECT payload FROM public.selfhost_restore_probe"
        ) == "preserved-from-postgres-16"
        assert await admin.fetchval(
            "SELECT public.selfhost_restore_probe_count()"
        ) == 1
        assert await admin.fetchval(
            """
            SELECT owner_role.rolname
            FROM pg_catalog.pg_class AS relation
            JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
            JOIN pg_catalog.pg_roles AS owner_role ON owner_role.oid = relation.relowner
            WHERE namespace.nspname = 'public'
              AND relation.relname = 'selfhost_restore_probe'
            """
        ) == SELFHOST_MIGRATOR_ROLE
        assert await admin.fetchval(
            """
            SELECT owner_role.rolname
            FROM pg_catalog.pg_proc AS routine
            JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = routine.pronamespace
            JOIN pg_catalog.pg_roles AS owner_role ON owner_role.oid = routine.proowner
            WHERE namespace.nspname = 'public'
              AND routine.proname = 'selfhost_restore_probe_count'
            """
        ) == SELFHOST_MIGRATOR_ROLE
    finally:
        await admin.close()


def _database_target(database_url: str) -> tuple[str, str]:
    parsed = make_url(database_url)
    if not parsed.drivername.startswith("postgresql"):
        pytest.skip(f"{_POSTGRES_URL} is not PostgreSQL")
    database_name = "infinity_context_selfhost_identity_e2e"
    admin = parsed.set(drivername="postgresql", database=parsed.database or "postgres")
    return admin.render_as_string(hide_password=False), database_name


def _async_url(url: str) -> str:
    return make_url(url).set(drivername="postgresql+asyncpg").render_as_string(hide_password=False)


def _login_url(admin_dsn: str, database: str, role: str, password: str) -> str:
    return (
        make_url(admin_dsn)
        .set(drivername="postgresql", database=database, username=role, password=password)
        .render_as_string(hide_password=False)
    )


def _admin_database_url(admin_dsn: str, database: str) -> str:
    return make_url(admin_dsn).set(database=database).render_as_string(hide_password=False)


async def _create_admin_owned_database(asyncpg, admin_dsn: str, database: str) -> None:
    admin = await asyncpg.connect(admin_dsn)
    try:
        await admin.execute(f'CREATE DATABASE "{database}"')
    finally:
        await admin.close()


async def _assert_admin_ownership_and_migrator_acl(
    asyncpg, admin_dsn: str, database: str
) -> None:
    admin = await asyncpg.connect(_admin_database_url(admin_dsn, database))
    try:
        admin_role = make_url(admin_dsn).username
        assert await admin.fetchval(
            """
            SELECT owner_role.rolname
            FROM pg_catalog.pg_database AS database
            JOIN pg_catalog.pg_roles AS owner_role ON owner_role.oid = database.datdba
            WHERE database.datname = current_database()
            """
        ) == admin_role
        assert await admin.fetchval(
            """
            SELECT owner_role.rolname
            FROM pg_catalog.pg_namespace AS namespace
            JOIN pg_catalog.pg_roles AS owner_role ON owner_role.oid = namespace.nspowner
            WHERE namespace.nspname = 'public'
            """
        ) in {admin_role, "pg_database_owner"}
        assert await admin.fetchval(
            "SELECT has_database_privilege($1, current_database(), 'CONNECT, CREATE, TEMPORARY')",
            SELFHOST_MIGRATOR_ROLE,
        )
        assert await admin.fetchval(
            "SELECT has_schema_privilege($1, 'public', 'USAGE, CREATE')",
            SELFHOST_MIGRATOR_ROLE,
        )
    finally:
        await admin.close()


async def _assert_migrator_object_ownership(asyncpg, admin_dsn: str, database: str) -> None:
    admin = await asyncpg.connect(_admin_database_url(admin_dsn, database))
    try:
        wrong_relations = await admin.fetchval(
            """
            SELECT count(*)
            FROM pg_catalog.pg_class AS relation
            JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
            JOIN pg_catalog.pg_roles AS owner_role ON owner_role.oid = relation.relowner
            WHERE namespace.nspname = 'public'
              AND relation.relkind IN ('r', 'p', 'S', 'v', 'm')
              AND owner_role.rolname <> $1
            """,
            SELFHOST_MIGRATOR_ROLE,
        )
        assert wrong_relations == 0
        wrong_functions = await admin.fetchval(
            """
            SELECT count(*)
            FROM pg_catalog.pg_proc AS function
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = function.pronamespace
            JOIN pg_catalog.pg_roles AS owner_role ON owner_role.oid = function.proowner
            WHERE namespace.nspname = 'public'
              AND NOT EXISTS (
                  SELECT 1
                  FROM pg_catalog.pg_depend AS dependency
                  WHERE dependency.classid = 'pg_catalog.pg_proc'::pg_catalog.regclass
                    AND dependency.objid = function.oid
                    AND dependency.deptype = 'e'
              )
              AND owner_role.rolname <> $1
            """,
            SELFHOST_MIGRATOR_ROLE,
        )
        assert wrong_functions == 0
        assert await admin.fetchval(
            """
            SELECT owner_role.rolname
            FROM pg_catalog.pg_class AS relation
            JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
            JOIN pg_catalog.pg_roles AS owner_role ON owner_role.oid = relation.relowner
            WHERE namespace.nspname = 'public'
              AND relation.relname = 'infinity_context_schema_migrations'
            """
        ) == SELFHOST_MIGRATOR_ROLE
    finally:
        await admin.close()


async def _assert_hostile_capability_grantee_is_rejected(
    asyncpg, admin_dsn: str, target_admin_engine
) -> None:
    hostile_role = "infinity_context_selfhost_hostile_login"
    admin = await asyncpg.connect(admin_dsn)
    try:
        await admin.execute(f'CREATE ROLE "{hostile_role}" LOGIN')
        await admin.execute(
            f'GRANT "infinity_context_canonical_writer" TO "{hostile_role}" '
            "WITH INHERIT TRUE, SET FALSE, ADMIN FALSE"
        )
        with pytest.raises(RuntimeError, match="self-host identity provisioning failed"):
            await provision_selfhost_login_identities(target_admin_engine, _PASSWORDS)
        await admin.execute(
            f'REVOKE "infinity_context_canonical_writer" FROM "{hostile_role}"'
        )
        await admin.execute(f'DROP ROLE "{hostile_role}"')
    finally:
        await admin.close()


async def _drop_test_state(asyncpg, admin_dsn: str, database: str) -> None:
    admin = None
    try:
        admin = await asyncpg.connect(admin_dsn)
        with suppress(Exception):
            await admin.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = $1 AND pid <> pg_backend_pid()",
                database,
            )
            await admin.execute(f'DROP DATABASE IF EXISTS "{database}"')
        for role in reversed(_ROLES):
            with suppress(Exception):
                await admin.execute(f'DROP ROLE IF EXISTS "{role}"')
    finally:
        if admin is not None:
            await admin.close()


async def _assert_role_contract(asyncpg, admin_dsn: str) -> None:
    admin = await asyncpg.connect(admin_dsn)
    try:
        rows = await admin.fetch(
            """
            SELECT role.rolname, role.rolcanlogin, role.rolsuper, role.rolinherit,
                   role.rolcreatedb,
                   role.rolcreaterole, role.rolreplication, role.rolbypassrls
            FROM pg_catalog.pg_roles AS role WHERE role.rolname = ANY($1::text[])
            ORDER BY role.rolname
            """,
            list(_ROLES),
        )
        assert len(rows) == len(_ROLES)
        assert all(row["rolcanlogin"] for row in rows)
        assert {row["rolname"]: row["rolinherit"] for row in rows} == {
            SELFHOST_MIGRATOR_ROLE: False,
            SELFHOST_RUNTIME_ROLE: False,
            SELFHOST_CANONICAL_WRITER_LOGIN_ROLE: True,
            SELFHOST_REGISTRAR_LOGIN_ROLE: True,
            SELFHOST_SEALER_LOGIN_ROLE: True,
        }
        assert all(
            not row[field]
            for row in rows
            for field in (
                "rolsuper",
                "rolcreatedb",
                "rolcreaterole",
                "rolreplication",
                "rolbypassrls",
            )
        )
        memberships = await admin.fetch(
            """
            SELECT member.rolname AS member, granted.rolname AS granted,
                   membership.inherit_option, membership.set_option,
                   membership.admin_option
            FROM pg_catalog.pg_auth_members AS membership
            JOIN pg_catalog.pg_roles AS member ON member.oid = membership.member
            JOIN pg_catalog.pg_roles AS granted ON granted.oid = membership.roleid
            WHERE member.rolname = ANY($1::text[]) ORDER BY member.rolname
            """,
            list(_ROLES),
        )
        assert {(row["member"], row["granted"]) for row in memberships} == {
            (SELFHOST_CANONICAL_WRITER_LOGIN_ROLE, "infinity_context_canonical_writer"),
            (SELFHOST_REGISTRAR_LOGIN_ROLE, "infinity_context_strict_v4_registrar"),
            (SELFHOST_SEALER_LOGIN_ROLE, "infinity_context_strict_v4_sealer"),
        }
        assert all(row["inherit_option"] for row in memberships)
        assert all(not row["set_option"] and not row["admin_option"] for row in memberships)
    finally:
        await admin.close()


async def _assert_runtime_boundary(asyncpg, admin_dsn: str, database: str) -> None:
    runtime = await asyncpg.connect(
        _login_url(admin_dsn, database, SELFHOST_RUNTIME_ROLE, _PASSWORDS.runtime)
    )
    try:
        assert await runtime.fetchval("SELECT count(*) FROM public.memory_spaces") == 0
        assert (
            await runtime.fetchval(
                "SELECT count(*) FROM public.memory_locator_profile_tombstone_replays"
            )
            == 0
        )
        await runtime.execute(
            "INSERT INTO public.memory_spaces "
            "(id, slug, name, status, created_at, updated_at) VALUES "
            "('selfhost-e2e-space', 'selfhost-e2e', 'Selfhost E2E', "
            "'active', now(), now())"
        )
        assert (
            await runtime.fetchval(
                "SELECT count(*) FROM public.memory_spaces WHERE slug='selfhost-e2e'"
            )
            == 1
        )
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await runtime.execute("CREATE TABLE public.selfhost_acl_escape(id integer)")
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await runtime.execute(
                "INSERT INTO public.memory_cleanup_v3_context_authorities "
                "(run_id_sha256, context_sha256, authority_terminal_sha256, "
                "context_json, authority_json, registration_sha256, "
                "registration_mac_sha256, registered_at) VALUES "
                "(repeat('a', 64), repeat('b', 64), repeat('c', 64), "
                "'{}'::jsonb, '{}'::jsonb, repeat('d', 64), repeat('e', 64), now())"
            )
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await runtime.execute(
                "UPDATE public.infinity_context_schema_migrations SET checksum = checksum"
            )
    finally:
        await runtime.close()

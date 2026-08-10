"""Real strict-v4 preparation recovery through the PostgreSQL writer adapter."""

from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path

import pytest
from infinity_context_adapters.postgres import build_async_engine, upgrade_schema
from infinity_context_adapters.postgres.managed_cleanup_v4_context_registration import (
    AsyncPostgresCleanupV4ContextAuthorityRegistry,
)
from infinity_context_adapters.postgres.managed_strict_v4_preparation_receipt import (
    SQLiteStrictV4PreparationReceiptStore,
)
from infinity_context_adapters.postgres.strict_v4_database_roles import (
    STRICT_V4_CANONICAL_WRITER_ROLE,
    STRICT_V4_FACT_WRITER_ROLE,
    STRICT_V4_REGISTRAR_ROLE,
    STRICT_V4_SEALER_ROLE,
    assert_strict_v4_runtime_capability,
)
from infinity_context_adapters.postgres.strict_v4_writer_authority import (
    AsyncPostgresStrictV4WriterAuthority,
)
from infinity_context_core.features.projection_receipts import (
    ProjectionReceiptAuthenticator,
    ProjectionReceiptError,
)
from infinity_context_core.features.projection_receipts.strict_v4_writer_authority import (
    build_strict_v4_writer_authority,
)
from infinity_context_core.ports.managed_cleanup_v3_contracts import commitment
from infinity_context_server.memory_comparison_backend_target import (
    FullComparisonBackendTarget,
)
from infinity_context_server.memory_comparison_full_profiles import (
    resolve_full_comparison_profile,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestProjector,
)
from infinity_context_server.memory_comparison_managed_plan_builder import (
    build_managed_public_run_projection,
)
from infinity_context_server.memory_comparison_managed_v5_cleanup_v4_projector import (
    ManagedV5CleanupV4OperationProjector,
)
from infinity_context_server.memory_comparison_managed_v5_strict_v4_fact_execution import (
    recover_strict_v4_fact_authority,
)
from infinity_context_server.memory_comparison_managed_v5_strict_v4_fact_ingest import (
    StrictV4FactIngestRuntime,
    authenticate_strict_v4_fact_ingest_receipt,
)
from infinity_context_server.memory_comparison_managed_v5_strict_v4_preparation import (
    StrictV4FullPreparationInputs,
    prepare_strict_v4_full_run,
)
from infinity_context_server.memory_comparison_managed_v5_strict_v4_writer_authority import (
    recover_and_seal_strict_v4_writer_authority,
)
from postgres_test_database import (
    STRICT_V4_TEST_ROLE_PASSWORD,
    PostgresTestDatabase,
)
from sqlalchemy.engine import make_url
from strict_v4_authority_acl_test_support import (
    STRICT_V4_0035_AUTHORITY_TABLES,
    assert_upgrade_normalizes_all_authority_acls,
)

KEY = b"strict-v4-real-adapter-artifact-key" * 2
AUTH = ProjectionReceiptAuthenticator(b"strict-v4-real-adapter-receipt-key" * 2)
SPACE_ID = f"benchmark-space-{'2' * 48}"


class _Keys:
    def resolve(self, *, purpose: str, key_id: str) -> bytes:
        expected = {
            "a1": "a1-key",
            "a2": "a2-key",
            "expected-index": "index-key",
        }
        if expected.get(purpose) != key_id:
            raise ValueError("unexpected strict-v4 key binding")
        return KEY


def test_real_recovery_seals_postgres_writer_authority_when_configured(tmp_path: Path) -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    dataset = Path("/tmp/locomo10.ingestion-manifest-r1.json")
    if not database_url or not dataset.is_file():
        pytest.skip("PostgreSQL or the staged official LoCoMo fixture is unavailable")
    asyncio.run(_assert_real_adapter(database_url, dataset, tmp_path))


def test_strict_v4_upgrade_normalizes_all_authority_acls_when_configured() -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(assert_upgrade_normalizes_all_authority_acls(database_url))


async def _assert_real_adapter(database_url: str, dataset: Path, tmp_path: Path) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(
        database_url, prefix="strict_v4_adapter", asyncpg=asyncpg
    )
    await database.recreate()
    canonical_role = ""
    fact_writer_role = ""
    registrar_role = ""
    sealer_role = ""
    try:
        engine = build_async_engine(database.app_url)
        try:
            await upgrade_schema(engine)
        finally:
            await engine.dispose()
        canonical_role = await database.create_runtime_role(
            capability_role="infinity_context_canonical_writer",
            suffix="canonical",
        )
        fact_writer_role = await database.create_runtime_role(
            capability_role=STRICT_V4_FACT_WRITER_ROLE,
            suffix="fact_writer",
        )
        registrar_role = await database.create_runtime_role(
            capability_role="infinity_context_strict_v4_registrar",
            suffix="registrar",
        )
        sealer_role = await database.create_runtime_role(
            capability_role="infinity_context_strict_v4_sealer",
            suffix="sealer",
        )

        profile = resolve_full_comparison_profile("mem0-locomo-top50-v1")
        assert profile is not None
        projection = build_managed_public_run_projection(
            run_id="strict-v4-real-adapter",
            run_nonce_commitment_sha256="9" * 64,
            runtime_probe_nonce_sha256="e" * 64,
            profile=profile,
            dataset_bytes=dataset.read_bytes(),
            backend_targets=(
                FullComparisonBackendTarget("infinity-context", "a" * 64),
                FullComparisonBackendTarget("mem0", "b" * 64),
            ),
            scope="full",
        )
        manifest = ManagedMem0V5ManifestProjector().project(
            projection.cases, current_date="2026-08-09"
        )
        projector = ManagedV5CleanupV4OperationProjector(
            projection=projection,
            manifest_authority=manifest,
            admission_commitment_sha256="f" * 64,
            profile_id="mem0-locomo-top50-v1",
        )
        run_id = hashlib.sha256(projection.bindings.run_id.encode()).hexdigest()
        inputs = _inputs(tmp_path, projection, manifest, run_id)
        connection = await database.connect()
        try:
            await connection.execute(
                """
                INSERT INTO memory_spaces(id,slug,name,status,created_at,updated_at)
                VALUES($1,$2,'strict-v4 adapter','active',clock_timestamp(),clock_timestamp())
                """,
                inputs.space_id,
                inputs.space_slug,
            )
            await connection.execute(
                """
                INSERT INTO memory_comparison_benchmark_runs(
                  run_id_sha256,binding_commitment_sha256,
                  infinity_target_identity_sha256,space_id,space_slug,
                  idempotency_key_sha256,registration_fingerprint_sha256,state,
                  cleanup_plan_json,cleanup_plan_sha256,cleanup_plan_state,
                  created_at,updated_at)
                VALUES($1,$2,$3,$4,$5,$6,$7,'active',NULL,NULL,'recovery_blocked',
                       clock_timestamp(),clock_timestamp())
                """,
                run_id,
                projection.bindings.binding_commitment_sha256,
                inputs.infinity_target_identity_sha256,
                inputs.space_id,
                inputs.space_slug,
                "c" * 64,
                "d" * 64,
            )
            prepared_at = await connection.fetchval("SELECT clock_timestamp()")
        finally:
            await connection.close()

        async def raw_registrar_connect():
            return await database.connect_as_runtime_role(registrar_role)

        async def raw_seal_connect():
            return await database.connect_as_runtime_role(sealer_role)

        async def canonical_connect():
            return await database.connect_as_runtime_role(canonical_role)

        async def fact_writer_connect():
            return await database.connect_as_runtime_role(fact_writer_role)

        await _assert_direct_login_acls_rejected(
            database,
            role_capabilities=(
                (
                    canonical_role,
                    STRICT_V4_CANONICAL_WRITER_ROLE,
                    canonical_connect,
                    "canonical-direct-acl",
                ),
                (
                    fact_writer_role,
                    STRICT_V4_FACT_WRITER_ROLE,
                    fact_writer_connect,
                    "fact-writer-direct-acl",
                ),
                (
                    registrar_role,
                    STRICT_V4_REGISTRAR_ROLE,
                    raw_registrar_connect,
                    "registrar-direct-acl",
                ),
                (
                    sealer_role,
                    STRICT_V4_SEALER_ROLE,
                    raw_seal_connect,
                    "sealer-direct-acl",
                ),
            ),
        )

        await _assert_role_separation(
            asyncpg,
            database,
            registrar_connect=raw_registrar_connect,
            seal_connect=raw_seal_connect,
            canonical_connect=canonical_connect,
            space_id=inputs.space_id,
        )
        await _assert_late_authority_acl_drift_rejected(
            database,
            role_capabilities=(
                (canonical_role, STRICT_V4_CANONICAL_WRITER_ROLE, canonical_connect),
                (fact_writer_role, STRICT_V4_FACT_WRITER_ROLE, fact_writer_connect),
                (registrar_role, STRICT_V4_REGISTRAR_ROLE, raw_registrar_connect),
                (sealer_role, STRICT_V4_SEALER_ROLE, raw_seal_connect),
            ),
        )

        async def registrar_connect():
            connection = await raw_registrar_connect()
            await _install_hostile_temp_shadows(connection)
            return connection

        async def seal_connect():
            connection = await raw_seal_connect()
            await _install_hostile_temp_shadows(connection)
            return connection

        registry = AsyncPostgresCleanupV4ContextAuthorityRegistry(
            connect=registrar_connect, authenticator=AUTH
        )
        store = SQLiteStrictV4PreparationReceiptStore.create(tmp_path / "receipt.sqlite3")
        try:
            receipt = await prepare_strict_v4_full_run(
                projector=projector,
                inputs=inputs,
                registration_port=registry,
                receipt_store=store,
                key_identity_authority=_Keys(),
                authenticator=AUTH,
                registered_at=prepared_at,
                prepared_at=prepared_at,
            )
        finally:
            store.close()

        canonical = await canonical_connect()
        try:
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await canonical.execute(
                    "INSERT INTO memory_comparison_strict_v4_preparations DEFAULT VALUES"
                )
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await canonical.execute(
                    """
                    UPDATE memory_cleanup_v3_context_authorities
                    SET registered_at=clock_timestamp()
                    WHERE run_id_sha256=$1
                    """,
                    run_id,
                )
        finally:
            await canonical.close()

        clock = await database.connect()
        try:
            sealed_at = await clock.fetchval("SELECT clock_timestamp()")
        finally:
            await clock.close()
        store = SQLiteStrictV4PreparationReceiptStore.open(tmp_path / "receipt.sqlite3")
        try:
            authority = await recover_and_seal_strict_v4_writer_authority(
                receipt_store=store,
                registration_port=registry,
                writer_authority_port=AsyncPostgresStrictV4WriterAuthority(
                    connect=seal_connect, authenticator=AUTH
                ),
                authenticator=AUTH,
                key_identity_authority=_Keys(),
                sealed_at=sealed_at,
            )
        finally:
            store.close()
        assert authority.preparation_receipt_sha256 == receipt.receipt_sha256
        assert authority.provider_calls == 0
        assert authority.paid_go_ready is False
        connection = await canonical_connect()
        try:
            await connection.execute(
                """
                INSERT INTO memory_idempotency_records(
                  space_id,key,fingerprint,result_type,result_id,created_at)
                VALUES($1,'real-adapter','real-adapter','strict-v4','real-adapter',
                       clock_timestamp())
                """,
                inputs.space_id,
            )
        finally:
            await connection.close()

        fact_writer_url = make_url(database.app_url).set(
            username=fact_writer_role,
            password=STRICT_V4_TEST_ROLE_PASSWORD,
        )
        store = SQLiteStrictV4PreparationReceiptStore.open(tmp_path / "receipt.sqlite3")
        fact_authority = None
        runtime = None
        try:
            fact_authority = await recover_strict_v4_fact_authority(
                receipt_store=store,
                registration_port=registry,
                authenticator=AUTH,
                key_identity_authority=_Keys(),
                expected_projector=projector,
            )
            runtime = StrictV4FactIngestRuntime(
                database_url=fact_writer_url.render_as_string(hide_password=False),
                authority=fact_authority,
            )
            first_ingest = await runtime.execute(
                projector=projector,
                space_slug=inputs.space_slug,
                preparation_receipt=fact_authority.receipt,
                authenticator=AUTH,
            )
            replay_ingest = await runtime.execute(
                projector=projector,
                space_slug=inputs.space_slug,
                preparation_receipt=fact_authority.receipt,
                authenticator=AUTH,
            )
            authenticate_strict_v4_fact_ingest_receipt(first_ingest, authenticator=AUTH)
            authenticate_strict_v4_fact_ingest_receipt(replay_ingest, authenticator=AUTH)
            assert first_ingest.corpus_count == 10
            assert first_ingest.operation_count == 5_882
            assert first_ingest.replayed_count == 0
            assert replay_ingest.replayed_count == 5_882
            assert (
                replay_ingest.ordered_result_root_sha256 == first_ingest.ordered_result_root_sha256
            )
            assert first_ingest.preparation_receipt_sha256 == receipt.receipt_sha256
            assert first_ingest.provider_calls == replay_ingest.provider_calls == 0
        finally:
            if runtime is not None:
                await runtime.close()
            if fact_authority is not None:
                fact_authority.close()
            store.close()

        connection = await database.connect()
        try:
            counts = await connection.fetchrow(
                """
                SELECT
                  (SELECT count(*) FROM memory_scopes) AS scopes,
                  (SELECT count(*) FROM memory_threads) AS threads,
                  (SELECT count(*) FROM memory_facts) AS facts,
                  (SELECT count(*) FROM memory_fact_versions) AS versions,
                  (SELECT count(*) FROM memory_source_refs) AS source_refs,
                  (SELECT count(*) FROM memory_outbox) AS outbox,
                  (SELECT count(*) FROM memory_fact_operation_receipts) AS receipts
                """
            )
        finally:
            await connection.close()
        assert tuple(counts.values()) == (10, 10, 5_882, 5_882, 5_882, 5_882, 5_882)
        await _assert_multirole_canonical_rejected(
            asyncpg,
            database,
            canonical_role=canonical_role,
            canonical_connect=canonical_connect,
            space_id=inputs.space_id,
        )

        store = SQLiteStrictV4PreparationReceiptStore.open(tmp_path / "receipt.sqlite3")
        try:
            replayed = await recover_and_seal_strict_v4_writer_authority(
                receipt_store=store,
                registration_port=registry,
                writer_authority_port=AsyncPostgresStrictV4WriterAuthority(
                    connect=seal_connect, authenticator=AUTH
                ),
                authenticator=AUTH,
                key_identity_authority=_Keys(),
                sealed_at=sealed_at,
            )
        finally:
            store.close()
        assert replayed == authority

        clock = await database.connect()
        try:
            divergent_at = await clock.fetchval("SELECT clock_timestamp()")
        finally:
            await clock.close()
        divergent = build_strict_v4_writer_authority(
            receipt=receipt,
            authenticator=AUTH,
            sealed_at=divergent_at,
        )
        with pytest.raises(
            ProjectionReceiptError,
            match="projection_receipt.writer_authority_divergent",
        ):
            await AsyncPostgresStrictV4WriterAuthority(
                connect=seal_connect,
                authenticator=AUTH,
            ).seal_and_readback(receipt=receipt, authority=divergent)
    finally:
        await database.drop()
        roles = tuple(
            role for role in (canonical_role, fact_writer_role, registrar_role, sealer_role) if role
        )
        await database.drop_runtime_roles(*roles)


async def _assert_role_separation(
    asyncpg,
    database,
    *,
    registrar_connect,
    seal_connect,
    canonical_connect,
    space_id: str,
) -> None:
    admin = await database.connect()
    try:
        owner = await admin.fetchval(
            """
            SELECT tableowner
            FROM pg_catalog.pg_tables
            WHERE schemaname='public'
              AND tablename='memory_comparison_strict_v4_preparations'
            """
        )
    finally:
        await admin.close()

    connections = {
        "registrar": await registrar_connect(),
        "sealer": await seal_connect(),
        "canonical": await canonical_connect(),
    }
    try:
        for connection in connections.values():
            assert await connection.fetchval("SELECT current_user") != owner
        for role_name in ("sealer", "canonical"):
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await connections[role_name].execute(
                    "INSERT INTO memory_cleanup_v3_context_authorities DEFAULT VALUES"
                )
        for role_name in ("registrar", "canonical"):
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await connections[role_name].execute(
                    "INSERT INTO memory_comparison_strict_v4_preparations DEFAULT VALUES"
                )
        for role_name in ("registrar", "sealer"):
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await connections[role_name].execute(
                    """
                    INSERT INTO memory_idempotency_records(
                      space_id,key,fingerprint,result_type,result_id,created_at)
                    VALUES($1,'forbidden','forbidden',
                           'strict-v4','forbidden',clock_timestamp())
                    """,
                    space_id,
                )
        for table in STRICT_V4_0035_AUTHORITY_TABLES:
            for connection in connections.values():
                with pytest.raises(asyncpg.InsufficientPrivilegeError):
                    await connection.execute(f"INSERT INTO public.{table} DEFAULT VALUES")
        assert await connections["canonical"].fetchval(
            "SELECT pg_catalog.pg_has_role(current_user, $1, 'USAGE')",
            STRICT_V4_CANONICAL_WRITER_ROLE,
        )
        assert await connections["canonical"].fetchval(
            """
            SELECT pg_catalog.has_table_privilege(
                current_user,
                'public.memory_comparison_benchmark_runs',
                'SELECT'
            )
            """
        )
        await _install_hostile_temp_shadows(connections["canonical"])
        assert await connections["canonical"].fetchval(
            """
            SELECT pg_catalog.has_table_privilege(
                current_user,
                'public.memory_comparison_benchmark_runs',
                'SELECT'
            )
            """
        )
        with pytest.raises(asyncpg.CheckViolationError):
            await connections["canonical"].execute(
                """
                INSERT INTO memory_idempotency_records(
                  space_id,key,fingerprint,result_type,result_id,created_at)
                VALUES($1,'pre-seal','pre-seal',
                       'strict-v4','pre-seal',clock_timestamp())
                """,
                space_id,
            )
    finally:
        for connection in connections.values():
            await connection.close()


async def _install_hostile_temp_shadows(connection) -> None:
    await connection.execute("SET search_path=pg_temp, public")
    await connection.execute(
        "CREATE TEMP TABLE memory_comparison_benchmark_runs(run_id_sha256 text)"
    )
    await connection.execute(
        "CREATE TEMP TABLE memory_cleanup_v3_context_authorities(context_sha256 text)"
    )
    await connection.execute(
        "CREATE TEMP TABLE memory_comparison_strict_v4_preparations(run_id_sha256 text)"
    )
    await connection.execute(
        """
        CREATE FUNCTION pg_temp.pg_has_role(name, text, text)
        RETURNS boolean LANGUAGE sql IMMUTABLE AS 'SELECT true'
        """
    )


async def _assert_direct_login_acls_rejected(
    database,
    *,
    role_capabilities,
) -> None:
    for login_role, capability_role, connect, error_code in role_capabilities:
        admin = await database.connect()
        try:
            await admin.execute(
                f'GRANT SELECT ON public.memory_comparison_benchmark_runs TO "{login_role}"'
            )
        finally:
            await admin.close()
        try:
            connection = await connect()
            try:
                with pytest.raises(ProjectionReceiptError, match=error_code):
                    await assert_strict_v4_runtime_capability(
                        connection,
                        capability_role=capability_role,
                        error_code=error_code,
                    )
            finally:
                await connection.close()
        finally:
            admin = await database.connect()
            try:
                await admin.execute(
                    f'REVOKE SELECT ON public.memory_comparison_benchmark_runs FROM "{login_role}"'
                )
            finally:
                await admin.close()


async def _assert_late_authority_acl_drift_rejected(
    database,
    *,
    role_capabilities,
) -> None:
    protected_tables = (
        "memory_comparison_strict_v4_preparations",
        "memory_cleanup_v3_context_authorities",
        "memory_comparison_benchmark_runs",
        *STRICT_V4_0035_AUTHORITY_TABLES,
    )
    for _, capability_role, connect in role_capabilities:
        for table in protected_tables:
            privilege = _wrong_capability_privilege(
                table=table,
                capability_role=capability_role,
            )
            admin = await database.connect()
            try:
                await admin.execute(f'GRANT {privilege} ON public.{table} TO "{capability_role}"')
            finally:
                await admin.close()
            try:
                connection = await connect()
                try:
                    with pytest.raises(
                        ProjectionReceiptError,
                        match="late-authority-acl-drift",
                    ):
                        await assert_strict_v4_runtime_capability(
                            connection,
                            capability_role=capability_role,
                            error_code="late-authority-acl-drift",
                        )
                finally:
                    await connection.close()
            finally:
                admin = await database.connect()
                try:
                    await admin.execute(
                        f'REVOKE {privilege} ON public.{table} FROM "{capability_role}"'
                    )
                finally:
                    await admin.close()

    for table in protected_tables:
        admin = await database.connect()
        try:
            await admin.execute(f"GRANT INSERT ON public.{table} TO PUBLIC")
        finally:
            await admin.close()
        try:
            for _, capability_role, connect in role_capabilities:
                connection = await connect()
                try:
                    with pytest.raises(
                        ProjectionReceiptError,
                        match="late-public-acl-drift",
                    ):
                        await assert_strict_v4_runtime_capability(
                            connection,
                            capability_role=capability_role,
                            error_code="late-public-acl-drift",
                        )
                finally:
                    await connection.close()
        finally:
            admin = await database.connect()
            try:
                await admin.execute(f"REVOKE INSERT ON public.{table} FROM PUBLIC")
            finally:
                await admin.close()


def _wrong_capability_privilege(*, table: str, capability_role: str) -> str:
    if (
        table == "memory_comparison_strict_v4_preparations"
        and capability_role == STRICT_V4_SEALER_ROLE
    ):
        return "UPDATE"
    if (
        table == "memory_cleanup_v3_context_authorities"
        and capability_role == STRICT_V4_REGISTRAR_ROLE
    ):
        return "UPDATE"
    return "INSERT"


async def _assert_multirole_canonical_rejected(
    asyncpg,
    database,
    *,
    canonical_role: str,
    canonical_connect,
    space_id: str,
) -> None:
    admin = await database.connect()
    try:
        await admin.execute(f'GRANT infinity_context_strict_v4_registrar TO "{canonical_role}"')
    finally:
        await admin.close()
    try:
        await _assert_canonical_insert_fenced(
            asyncpg,
            canonical_connect=canonical_connect,
            space_id=space_id,
            key="multi-role",
        )
    finally:
        admin = await database.connect()
        try:
            await admin.execute(
                f'REVOKE infinity_context_strict_v4_registrar FROM "{canonical_role}"'
            )
        finally:
            await admin.close()

    admin = await database.connect()
    try:
        await admin.execute(f'GRANT pg_write_all_data TO "{canonical_role}"')
    finally:
        await admin.close()
    try:
        await _assert_canonical_insert_fenced(
            asyncpg,
            canonical_connect=canonical_connect,
            space_id=space_id,
            key="powerful-group",
        )
    finally:
        admin = await database.connect()
        try:
            await admin.execute(f'REVOKE pg_write_all_data FROM "{canonical_role}"')
        finally:
            await admin.close()

    admin = await database.connect()
    try:
        await admin.execute(
            f'GRANT SELECT ON public.memory_comparison_benchmark_runs TO "{canonical_role}"'
        )
    finally:
        await admin.close()
    try:
        await _assert_canonical_insert_fenced(
            asyncpg,
            canonical_connect=canonical_connect,
            space_id=space_id,
            key="direct-acl",
        )
    finally:
        admin = await database.connect()
        try:
            await admin.execute(
                f'REVOKE SELECT ON public.memory_comparison_benchmark_runs FROM "{canonical_role}"'
            )
        finally:
            await admin.close()

    admin = await database.connect()
    try:
        await admin.execute(f'ALTER ROLE "{canonical_role}" CREATEROLE')
    finally:
        await admin.close()
    try:
        await _assert_canonical_insert_fenced(
            asyncpg,
            canonical_connect=canonical_connect,
            space_id=space_id,
            key="create-role",
        )
    finally:
        admin = await database.connect()
        try:
            await admin.execute(f'ALTER ROLE "{canonical_role}" NOCREATEROLE')
        finally:
            await admin.close()

    admin = await database.connect()
    try:
        original_owner = await admin.fetchval(
            """
            SELECT tableowner FROM pg_catalog.pg_tables
            WHERE schemaname='public' AND tablename='memory_idempotency_records'
            """
        )
        await admin.execute(
            f'ALTER TABLE public.memory_idempotency_records OWNER TO "{canonical_role}"'
        )
    finally:
        await admin.close()
    try:
        await _assert_canonical_insert_fenced(
            asyncpg,
            canonical_connect=canonical_connect,
            space_id=space_id,
            key="protected-owner",
        )
    finally:
        admin = await database.connect()
        try:
            escaped_owner = str(original_owner).replace('"', '""')
            await admin.execute(
                f'ALTER TABLE public.memory_idempotency_records OWNER TO "{escaped_owner}"'
            )
        finally:
            await admin.close()

    ownership_cases = (
        (
            "protected-capability-owner",
            """
            SELECT tableowner FROM pg_catalog.pg_tables
            WHERE schemaname='public' AND tablename='memory_idempotency_records'
            """,
            "ALTER TABLE public.memory_idempotency_records OWNER TO",
        ),
        (
            "schema-capability-owner",
            """
            SELECT owner.rolname
            FROM pg_catalog.pg_namespace AS namespace
            JOIN pg_catalog.pg_roles AS owner ON owner.oid=namespace.nspowner
            WHERE namespace.nspname='public'
            """,
            "ALTER SCHEMA public OWNER TO",
        ),
        (
            "function-capability-owner",
            """
            SELECT owner.rolname
            FROM pg_catalog.pg_proc AS function
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid=function.pronamespace
            JOIN pg_catalog.pg_roles AS owner ON owner.oid=function.proowner
            WHERE namespace.nspname='public'
              AND function.proname='memory_comparison_is_strict_v4_canonical_writer'
            """,
            "ALTER FUNCTION public.memory_comparison_is_strict_v4_canonical_writer() OWNER TO",
        ),
    )
    for key, owner_query, alter_prefix in ownership_cases:
        admin = await database.connect()
        try:
            original_owner = await admin.fetchval(owner_query)
            await admin.execute(f'{alter_prefix} "{STRICT_V4_CANONICAL_WRITER_ROLE}"')
        finally:
            await admin.close()
        try:
            await _assert_canonical_insert_fenced(
                asyncpg,
                canonical_connect=canonical_connect,
                space_id=space_id,
                key=key,
            )
        finally:
            admin = await database.connect()
            try:
                escaped_owner = str(original_owner).replace('"', '""')
                await admin.execute(f'{alter_prefix} "{escaped_owner}"')
                if alter_prefix.startswith("ALTER TABLE"):
                    await admin.execute(
                        "GRANT SELECT, INSERT ON "
                        "public.memory_idempotency_records TO "
                        "infinity_context_canonical_writer"
                    )
            finally:
                await admin.close()


async def _assert_canonical_insert_fenced(
    asyncpg,
    *,
    canonical_connect,
    space_id: str,
    key: str,
) -> None:
    connection = await canonical_connect()
    try:
        with pytest.raises(asyncpg.CheckViolationError):
            await connection.execute(
                """
                INSERT INTO memory_idempotency_records(
                  id,space_id,key,fingerprint,result_type,result_id,created_at)
                VALUES($3,$1,$2,$2,'strict-v4',$2,clock_timestamp())
                """,
                space_id,
                key,
                -(int.from_bytes(hashlib.sha256(key.encode()).digest()[:3], "big") + 1),
            )
    finally:
        await connection.close()


def _inputs(tmp_path, projection, manifest, run_id: str) -> StrictV4FullPreparationInputs:
    q_target, q_policy = "a" * 64, "b" * 64
    g_target, g_policy = "c" * 64, "d" * 64
    return StrictV4FullPreparationInputs(
        run_id_sha256=run_id,
        publishable_profile_commitment_sha256=(projection.publishable_profile_commitment_sha256),
        ingestion_root_sha256=manifest.ingestion_root_sha256,
        case_manifest_sha256=projection.case_manifest_sha256,
        infinity_target_identity_sha256="a" * 64,
        space_id=SPACE_ID,
        space_slug="strict-v4-real-adapter",
        cleanup_target_authority_sha256="6" * 64,
        qdrant_authority_sha256=commitment(
            "lane-authority/v4",
            {
                "lane": "qdrant",
                "target_commitment_sha256": q_target,
                "policy_commitment_sha256": q_policy,
            },
        ),
        qdrant_target_commitment_sha256=q_target,
        qdrant_policy_commitment_sha256=q_policy,
        graphiti_authority_sha256=commitment(
            "lane-authority/v4",
            {
                "lane": "graphiti",
                "target_commitment_sha256": g_target,
                "policy_commitment_sha256": g_policy,
            },
        ),
        graphiti_target_commitment_sha256=g_target,
        graphiti_policy_commitment_sha256=g_policy,
        cognee_policy_sha256="7" * 64,
        namespace_policy_sha256="8" * 64,
        original_pair_path=None,
        original_pair_key_id=None,
        a1_path=str(tmp_path / "a1.sqlite3"),
        a1_key_id="a1-key",
        a2_path=str(tmp_path / "a2.sqlite3"),
        a2_key_id="a2-key",
        expected_index_path=str(tmp_path / "index.sqlite3"),
        expected_index_key_id="index-key",
    )

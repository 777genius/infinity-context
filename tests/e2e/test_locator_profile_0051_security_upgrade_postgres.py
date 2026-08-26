"""Old-0050 PostgreSQL proof for locator ACL and hostile search-path repair."""

from __future__ import annotations

import asyncio
import os

import pytest
from infinity_context_adapters.postgres import build_async_engine, upgrade_schema
from postgres_test_database import PostgresTestDatabase
from test_postgres_schema_upgrade_e2e import _install_versioned_schema_through

ROLES = (
    "infinity_context_canonical_writer",
    "infinity_context_strict_v4_registrar",
    "infinity_context_strict_v4_sealer",
)


def test_old_0050_acl_and_hostile_search_path_are_repaired_when_configured() -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_scenario(database_url))


async def _scenario(database_url: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(
        database_url, prefix="locator_0051_security", asyncpg=asyncpg
    )
    await database.recreate()
    try:
        await _install_versioned_schema_through(database, "0050_")
        raw = await database.connect()
        try:
            # Reproduce the staged 0040 objects omitted by the direct-prefix fixture,
            # then poison every runtime ACL as an old deployment could have done.
            await raw.execute(
                """
                CREATE SEQUENCE public.memory_locator_commit_watermark_seq START 100;
                ALTER TABLE public.memory_chunks
                  ADD COLUMN retrieval_commit_watermark BIGINT NOT NULL
                  DEFAULT pg_catalog.nextval('public.memory_locator_commit_watermark_seq');
                SELECT pg_catalog.setval(
                  'public.memory_locator_commit_watermark_seq', 100, true);
                GRANT ALL PRIVILEGES ON SEQUENCE
                  public.memory_locator_commit_watermark_seq TO PUBLIC;
                GRANT ALL PRIVILEGES ON SEQUENCE
                  public.memory_locator_commit_watermark_seq
                  TO infinity_context_canonical_writer,
                     infinity_context_strict_v4_registrar,
                     infinity_context_strict_v4_sealer;
                """
            )
        finally:
            await raw.close()

        engine = build_async_engine(database.app_url)
        try:
            result = await upgrade_schema(engine)
            assert result.applied == ("0051_locator_profile_acl_search_path_hardening",)
        finally:
            await engine.dispose()

        raw = await database.connect()
        try:
            await _assert_exact_sequence_acl(raw)
            assert await raw.fetchval(
                """
                SELECT pg_catalog.array_to_string(proconfig, ',')
                FROM pg_catalog.pg_proc
                WHERE oid='public.memory_chunk_locator_watermark_v2()'::regprocedure
                """
            ) == "search_path=pg_catalog, public, pg_temp"
            assert await raw.fetchval(
                """
                SELECT pg_catalog.array_to_string(proconfig, ',')
                FROM pg_catalog.pg_proc
                WHERE oid='public.memory_chunk_locator_projection_events_v2()'::regprocedure
                """
            ) == "search_path=pg_catalog, public, pg_temp"
            assert await raw.fetchval(
                """
                SELECT pg_catalog.array_to_string(proconfig, ',')
                FROM pg_catalog.pg_proc
                WHERE oid='public.memory_chunk_locator_profile_events_v2()'::regprocedure
                """
            ) == "search_path=pg_catalog, public, pg_temp"

            await raw.execute(
                """
                INSERT INTO public.memory_spaces
                  (id,slug,name,status,created_at,updated_at)
                VALUES ('space-0051','space-0051','Space','active',now(),now());
                INSERT INTO public.memory_scopes
                  (id,space_id,external_ref,name,status,created_at,updated_at)
                VALUES ('scope-0051','space-0051','scope-0051','Scope','active',now(),now());
                INSERT INTO public.memory_documents
                  (id,space_id,memory_scope_id,thread_id,title,source_type,
                   source_external_id,content_hash,classification,status,created_at,updated_at)
                VALUES ('document-0051','space-0051','scope-0051',NULL,'Document','file',
                        'document-0051',repeat('a',64),'internal','active',now(),now());
                INSERT INTO public.memory_locator_profiles
                  (profile_id,generation,profile_digest,collection_name,state,created_at)
                VALUES ('profile-0051','generation-0051',repeat('b',64),
                        'collection-0051','building',now());

                CREATE TEMP SEQUENCE memory_locator_commit_watermark_seq START 9000;
                CREATE TEMP TABLE memory_locator_profiles(profile_id text, state text);
                CREATE TEMP TABLE memory_locator_profile_tombstones(
                    profile_id text, chunk_id text, canonical_version bigint
                );
                CREATE TEMP TABLE memory_outbox(
                    message_key text, event_type text, aggregate_type text,
                    aggregate_id text, aggregate_version bigint,
                    workload_class text, fairness_key text, payload_json jsonb,
                    status text, attempt_count integer,
                    next_attempt_at timestamptz, created_at timestamptz,
                    updated_at timestamptz
                );
                CREATE UNIQUE INDEX ON memory_outbox(message_key)
                  WHERE message_key IS NOT NULL;
                SET search_path = pg_temp, public, pg_catalog;

                INSERT INTO public.memory_chunks
                  (id,space_id,memory_scope_id,thread_id,document_id,episode_id,
                   source_type,source_external_id,source_hash,kind,text,normalized_text,
                   status,sequence,char_start,char_end,token_estimate,classification,
                   created_at,updated_at,metadata_json,retrieval_locator,
                   retrieval_source_key,retrieval_projection_generation,
                   retrieval_sequence_ordinal,retrieval_kind,retrieval_category)
                VALUES ('chunk-0051','space-0051','scope-0051',NULL,'document-0051',NULL,
                        'file','document-0051',repeat('c',64),'paragraph','Text','text',
                        'active',0,0,4,1,'internal',now(),now(),'{}'::jsonb,
                        'locator-0051','source-0051','projection-0051',0,'paragraph','test');
                """
            )
            assert await raw.fetchval(
                "SELECT retrieval_commit_watermark FROM public.memory_chunks "
                "WHERE id='chunk-0051'"
            ) == 102
            assert await raw.fetchval(
                "SELECT last_value FROM public.memory_locator_commit_watermark_seq"
            ) == 102
            assert await raw.fetchval(
                "SELECT last_value FROM pg_temp.memory_locator_commit_watermark_seq"
            ) == 9000
            assert not await raw.fetchval(
                "SELECT is_called FROM pg_temp.memory_locator_commit_watermark_seq"
            )
            assert await raw.fetchval(
                "SELECT count(*) FROM public.memory_outbox "
                "WHERE event_type='vector.upsert_locator_profile' "
                "AND aggregate_id='chunk-0051'"
            ) == 1
            assert await raw.fetchval("SELECT count(*) FROM pg_temp.memory_outbox") == 0
        finally:
            await raw.close()
    finally:
        await database.drop()


async def _assert_exact_sequence_acl(connection) -> None:
    expected = {
        "infinity_context_canonical_writer": {"USAGE"},
        "infinity_context_strict_v4_registrar": set(),
        "infinity_context_strict_v4_sealer": set(),
    }
    public_rows = await connection.fetch(
        """
        SELECT privilege_type FROM information_schema.usage_privileges
        WHERE object_schema='public'
          AND object_name='memory_locator_commit_watermark_seq'
          AND grantee='PUBLIC'
        """
    )
    assert {row["privilege_type"] for row in public_rows} == set()
    for role in ROLES:
        observed = {
            privilege
            for privilege in ("USAGE", "SELECT", "UPDATE")
            if await connection.fetchval(
                "SELECT pg_catalog.has_sequence_privilege($1,$2,$3)",
                role,
                "public.memory_locator_commit_watermark_seq",
                privilege,
            )
        }
        assert observed == expected[role]

"""Old-0050 PostgreSQL proof for locator ACL and hostile search-path repair."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
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
            # Poison every runtime ACL as an old deployment could have done.
            await raw.execute(
                """
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

        raw = await database.connect()
        try:
            migration = Path(__file__).resolve().parents[2] / (
                "packages/infinity_context_adapters/infinity_context_adapters/postgres/"
                "migrations/0051_locator_profile_acl_search_path_hardening.sql"
            )
            async with raw.transaction():
                await raw.execute(migration.read_text())
        finally:
            await raw.close()

        raw = await database.connect()
        try:
            await _assert_exact_sequence_acl(raw)
            assert (
                await raw.fetchval(
                    """
                SELECT pg_catalog.array_to_string(proconfig, ',')
                FROM pg_catalog.pg_proc
                WHERE oid='public.memory_chunk_locator_watermark_v2()'::regprocedure
                """
                )
                == "search_path=pg_catalog, public, pg_temp"
            )
            assert (
                await raw.fetchval(
                    """
                SELECT pg_catalog.array_to_string(proconfig, ',')
                FROM pg_catalog.pg_proc
                WHERE oid='public.memory_chunk_locator_projection_events_v2()'::regprocedure
                """
                )
                == "search_path=pg_catalog, public, pg_temp"
            )
            assert (
                await raw.fetchval(
                    """
                SELECT pg_catalog.array_to_string(proconfig, ',')
                FROM pg_catalog.pg_proc
                WHERE oid='public.memory_chunk_locator_profile_events_v2()'::regprocedure
                """
                )
                == "search_path=pg_catalog, public, pg_temp"
            )

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
                CREATE TEMP TABLE memory_locator_projection_tombstones(
                    chunk_id text PRIMARY KEY, canonical_version bigint,
                    legacy_deleted_at timestamptz, locator_deleted_at timestamptz,
                    created_at timestamptz, updated_at timestamptz
                );
                CREATE TEMP TABLE memory_locator_profile_tombstones(
                    profile_id text, chunk_id text, canonical_version bigint,
                    completed_at timestamptz, created_at timestamptz,
                    updated_at timestamptz, PRIMARY KEY (profile_id, chunk_id)
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
            assert (
                await raw.fetchval(
                    "SELECT retrieval_commit_watermark FROM public.memory_chunks "
                    "WHERE id='chunk-0051'"
                )
                == 102
            )
            assert (
                await raw.fetchval(
                    "SELECT last_value FROM public.memory_locator_commit_watermark_seq"
                )
                == 102
            )
            assert (
                await raw.fetchval(
                    "SELECT last_value FROM pg_temp.memory_locator_commit_watermark_seq"
                )
                == 9000
            )
            assert not await raw.fetchval(
                "SELECT is_called FROM pg_temp.memory_locator_commit_watermark_seq"
            )
            assert (
                await raw.fetchval(
                    "SELECT count(*) FROM public.memory_outbox "
                    "WHERE event_type='vector.upsert_locator_profile' "
                    "AND aggregate_id='chunk-0051' AND aggregate_version=1"
                )
                == 1
            )

            inserted_watermark = await raw.fetchval(
                "SELECT retrieval_commit_watermark FROM public.memory_chunks WHERE id='chunk-0051'"
            )
            await raw.execute(
                "UPDATE public.memory_chunks SET status='archived', updated_at=now() "
                "WHERE id='chunk-0051'"
            )
            ineligible = await raw.fetchrow(
                "SELECT retrieval_version, retrieval_commit_watermark "
                "FROM public.memory_chunks WHERE id='chunk-0051'"
            )
            assert tuple(ineligible) == (2, inserted_watermark + 1)
            assert (
                await raw.fetchval(
                    "SELECT last_value FROM public.memory_locator_commit_watermark_seq"
                )
                == ineligible["retrieval_commit_watermark"]
            )
            assert tuple(
                await raw.fetchrow(
                    "SELECT canonical_version, legacy_deleted_at IS NULL, "
                    "locator_deleted_at IS NULL "
                    "FROM public.memory_locator_projection_tombstones "
                    "WHERE chunk_id='chunk-0051'"
                )
            ) == (2, True, True)
            assert (
                await raw.fetchval(
                    "SELECT canonical_version "
                    "FROM public.memory_locator_profile_tombstones "
                    "WHERE profile_id='profile-0051' AND chunk_id='chunk-0051'"
                )
                == 2
            )
            assert {
                tuple(row)
                for row in await raw.fetch(
                    "SELECT event_type, aggregate_version FROM public.memory_outbox "
                    "WHERE aggregate_id='chunk-0051' "
                    "AND event_type IN "
                    "('vector.delete_chunks','vector.delete_locator_profile')"
                )
            } == {
                ("vector.delete_chunks", 2),
                ("vector.delete_locator_profile", 2),
            }

            await raw.execute(
                "UPDATE public.memory_chunks SET status='active', updated_at=now() "
                "WHERE id='chunk-0051'"
            )
            reactivated = await raw.fetchrow(
                "SELECT retrieval_version, retrieval_commit_watermark "
                "FROM public.memory_chunks WHERE id='chunk-0051'"
            )
            assert tuple(reactivated) == (
                ineligible["retrieval_version"] + 1,
                ineligible["retrieval_commit_watermark"] + 1,
            )
            assert (
                await raw.fetchval(
                    "SELECT last_value FROM public.memory_locator_commit_watermark_seq"
                )
                == reactivated["retrieval_commit_watermark"]
            )
            assert (
                await raw.fetchval(
                    "SELECT count(*) FROM public.memory_locator_profile_tombstones "
                    "WHERE profile_id='profile-0051' AND chunk_id='chunk-0051'"
                )
                == 0
            )

            deleted_version = reactivated["retrieval_version"]
            await raw.execute("DELETE FROM public.memory_chunks WHERE id='chunk-0051'")
            assert (
                await raw.fetchval(
                    "SELECT canonical_version "
                    "FROM public.memory_locator_profile_tombstones "
                    "WHERE profile_id='profile-0051' AND chunk_id='chunk-0051'"
                )
                == deleted_version
            )
            assert (
                await raw.fetchval(
                    "SELECT count(*) FROM public.memory_outbox "
                    "WHERE aggregate_id='chunk-0051' "
                    "AND aggregate_version=$1 "
                    "AND event_type='vector.delete_locator_profile'",
                    deleted_version,
                )
                == 1
            )
            assert (
                await raw.fetchval(
                    "SELECT last_value FROM public.memory_locator_commit_watermark_seq"
                )
                == reactivated["retrieval_commit_watermark"]
            )
            assert {
                tuple(row)
                for row in await raw.fetch(
                    "SELECT event_type, aggregate_version FROM public.memory_outbox "
                    "WHERE aggregate_id='chunk-0051' "
                    "AND event_type IN "
                    "('vector.upsert_chunk','vector.delete_chunks',"
                    "'vector.upsert_locator_profile','vector.delete_locator_profile')"
                )
            } == {
                ("vector.upsert_chunk", 1),
                ("vector.delete_chunks", 2),
                ("vector.upsert_chunk", 3),
                ("vector.upsert_locator_profile", 1),
                ("vector.delete_locator_profile", 2),
                ("vector.upsert_locator_profile", 3),
                ("vector.delete_locator_profile", 3),
            }
            assert tuple(
                await raw.fetchrow(
                    "SELECT canonical_version, legacy_deleted_at IS NOT NULL, "
                    "locator_deleted_at IS NOT NULL "
                    "FROM public.memory_locator_projection_tombstones "
                    "WHERE chunk_id='chunk-0051'"
                )
            ) == (2, True, True)
            for shadow in (
                "memory_locator_profiles",
                "memory_locator_projection_tombstones",
                "memory_locator_profile_tombstones",
                "memory_outbox",
            ):
                assert await raw.fetchval(f"SELECT count(*) FROM pg_temp.{shadow}") == 0
            assert (
                await raw.fetchval(
                    "SELECT last_value FROM pg_temp.memory_locator_commit_watermark_seq"
                )
                == 9000
            )
            assert not await raw.fetchval(
                "SELECT is_called FROM pg_temp.memory_locator_commit_watermark_seq"
            )
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

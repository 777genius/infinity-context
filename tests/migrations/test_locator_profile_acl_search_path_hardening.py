"""Static contract for append-only locator ACL and search-path repair."""

import re
from pathlib import Path

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "packages/infinity_context_adapters/infinity_context_adapters/postgres/migrations"
    / "0051_locator_profile_acl_search_path_hardening.sql"
)


def _function(sql: str, name: str) -> str:
    return sql.split(f"CREATE OR REPLACE FUNCTION public.{name}()", 1)[1].split(
        "$$;", 1
    )[0]


def test_0051_repairs_sequence_acl_only_when_the_sequence_exists() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "to_regclass('public.memory_locator_commit_watermark_seq') IS NOT NULL" in sql
    assert "REVOKE ALL PRIVILEGES ON SEQUENCE public.memory_locator_commit_watermark_seq" in sql
    assert "FROM PUBLIC," in sql
    assert "infinity_context_canonical_writer," in sql
    assert "infinity_context_strict_v4_registrar," in sql
    assert "infinity_context_strict_v4_sealer;" in sql
    assert "GRANT USAGE ON SEQUENCE public.memory_locator_commit_watermark_seq" in sql
    assert "TO infinity_context_canonical_writer;" in sql


def test_0051_pins_and_qualifies_the_published_locator_trigger_functions() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    watermark = _function(sql, "memory_chunk_locator_watermark_v2")
    projection_events = _function(sql, "memory_chunk_locator_projection_events_v2")
    profile_events = _function(sql, "memory_chunk_locator_profile_events_v2")

    for function in (watermark, projection_events, profile_events):
        assert "RETURNS trigger" in function
        assert "SET search_path = pg_catalog, public, pg_temp" in function
    assert "pg_catalog.nextval('public.memory_locator_commit_watermark_seq')" in watermark
    for relation in ("memory_locator_projection_tombstones", "memory_outbox"):
        assert f"public.{relation}" in projection_events
    assert (
        "INSERT INTO public.memory_locator_projection_tombstones AS tombstones"
        in projection_events
    )
    assert "WHERE tombstones.canonical_version < EXCLUDED.canonical_version" in (
        projection_events
    )
    assert "UPDATE public.memory_locator_projection_tombstones SET" in projection_events
    for relation in (
        "memory_locator_profiles",
        "memory_locator_profile_tombstones",
        "memory_outbox",
    ):
        assert f"public.{relation}" in profile_events
    for function in (projection_events, profile_events):
        assert "pg_catalog.jsonb_build_object(" in function
    assert "pg_catalog.jsonb_build_array(" in projection_events
    assert "pg_catalog.md5(" in profile_events

    relation_names = (
        "memory_locator_profiles",
        "memory_locator_projection_tombstones",
        "memory_locator_profile_tombstones",
        "memory_outbox",
    )
    trigger_functions = f"{projection_events}\n{profile_events}"
    for statement in ("DELETE FROM", "INSERT INTO", "UPDATE"):
        for relation in relation_names:
            assert not re.search(
                rf"\b{statement}\s+{relation}\b", trigger_functions, re.IGNORECASE
            )

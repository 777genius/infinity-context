from infinity_context_adapters.postgres import locator_catalog_attestation as catalog
from infinity_context_adapters.postgres import locator_catalog_specification as specification


def test_catalog_char_normalizes_asyncpg_internal_empty_char() -> None:
    assert catalog._catalog_char(b"\x00") == ""
    assert catalog._catalog_char("\x00") == ""


def test_catalog_char_preserves_nonempty_asyncpg_bytes_and_strings() -> None:
    assert catalog._catalog_char(b"f") == "f"
    assert catalog._catalog_char("v") == "v"
    assert catalog._catalog_char(b"") == ""
    assert catalog._catalog_char("") == ""
    assert catalog._catalog_char(b"\x00f") == "\x00f"


def test_0059_function_attestation_uses_packaged_trusted_bodies() -> None:
    expected = {
        "memory_locator_require_parent_capability_v1": False,
        "memory_chunk_retrieval_fence_v2": False,
        "memory_chunk_require_locator_parent_v1": False,
        "memory_document_lock_locator_parent_v1": False,
        "memory_chunk_locator_profile_events_v2": False,
        "memory_document_invalidate_locator_children_v1": True,
    }

    assert {
        name: spec.security_definer for name, spec in specification._FUNCTIONS.items()
    } == expected
    for name, spec in specification._FUNCTIONS.items():
        assert spec.body == specification._trusted_function_body(name)
        assert spec.body.strip().startswith(("BEGIN", "DECLARE"))
        assert spec.public_execute is not spec.security_definer


def test_parent_lifecycle_catalog_inventory_is_complete_and_exact() -> None:
    expected_columns = {
        "memory_locator_runtime_incarnations.locator_parent_capability": (
            specification._ColumnSpec("memory_locator_runtime_incarnations", "bigint", False, "0")
        ),
        "memory_chunks.retrieval_parent_version": specification._ColumnSpec(
            "memory_chunks", "bigint", False, "1"
        ),
    }
    assert expected_columns == specification._COLUMNS
    expected_trigger_types = {
        "trg_memory_chunk_retrieval_fence_v2": 23,
        "trg_00_memory_chunk_require_locator_parent": 23,
        "trg_00_locator_runtime_parent_capability": 23,
        "trg_00_memory_chunks_benchmark_document_child_lock": 31,
        "trg_memory_chunks_benchmark_document_child_fence": 31,
        "trg_memory_chunk_locator_profile_events_v2": 29,
        "trg_00_document_locator_profile_evidence_insert": 7,
        "trg_00_document_locator_profile_evidence_update": 19,
        "trg_00_document_locator_profile_evidence_delete": 11,
        "trg_01_document_locator_parent_lock_insert": 7,
        "trg_01_document_locator_parent_lock_update": 19,
        "trg_01_document_locator_parent_lock_delete": 11,
        "trg_document_invalidate_locator_children_insert": 5,
        "trg_document_invalidate_locator_children_update": 17,
        "trg_document_invalidate_locator_children_delete": 9,
    }
    assert {
        name: spec.trigger_type for name, spec in specification._TRIGGERS.items()
    } == expected_trigger_types


def test_function_catalog_query_attests_security_owner_path_body_and_effective_acl() -> None:
    sql = specification._FUNCTION_CATALOG_SQL

    for catalog_field in (
        "prosecdef",
        "proconfig",
        "prosrc",
        "proowner",
        "aclexplode",
        "acldefault",
    ):
        assert catalog_field in sql
    assert "procedure.pronargs=0" in sql


def test_trusted_trigger_descriptors_match_postgres_canonical_deparse() -> None:
    event_trigger = specification._TRIGGERS["trg_memory_chunk_locator_profile_events_v2"]
    assert "AFTER INSERT OR DELETE OR UPDATE" in event_trigger.definition
    assert "AFTER INSERT OR UPDATE OR DELETE" not in event_trigger.definition

    evidence = catalog._trigger_signature(
        specification._TRIGGERS["trg_00_document_locator_profile_evidence_update"].definition
    )
    parent_lock = catalog._trigger_signature(
        specification._TRIGGERS["trg_01_document_locator_parent_lock_update"].definition
    )
    invalidation = catalog._trigger_signature(
        specification._TRIGGERS["trg_document_invalidate_locator_children_update"].definition
    )

    for definition in (evidence, parent_lock, invalidation):
        for column in (
            "status",
            "classification",
            "space_id",
            "memory_scope_id",
            "thread_id",
            "source_type",
            "source_external_id",
        ):
            assert f"old.{column}::text is distinct from new.{column}::text" in definition
        assert "old.retrieval_projected is distinct from new.retrieval_projected" in definition
        assert "retrieval_projected::text" not in definition
        assert "row(" not in definition

    guard = "(old.retrieval_projected or new.retrieval_projected)and("
    assert guard in evidence
    assert guard in parent_lock
    assert guard not in invalidation
    assert "old.id::text is distinct from new.id::text" not in evidence
    assert "old.id::text is distinct from new.id::text" in parent_lock
    assert "old.id::text is distinct from new.id::text" in invalidation


def test_canonical_trigger_descriptors_do_not_weaken_observed_drift() -> None:
    expected = catalog._trigger_signature(
        specification._TRIGGERS["trg_00_document_locator_profile_evidence_update"].definition
    )

    assert catalog._trigger_signature(expected.replace("::text", "", 1)) != expected
    assert (
        catalog._trigger_signature(
            expected.replace(
                "old.retrieval_projected is distinct from new.retrieval_projected or ",
                "",
            )
        )
        != expected
    )
    assert catalog._trigger_signature(expected.replace("before update", "after update")) != expected
    assert catalog._trigger_signature(expected.replace(" or ", " and ", 1)) != expected

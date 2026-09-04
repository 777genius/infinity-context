from pathlib import Path

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "packages/infinity_context_adapters/infinity_context_adapters/postgres/migrations"
    / "0059_locator_parent_lifecycle.sql"
)


def test_parent_retraction_exception_is_narrow_and_identity_preserving() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    function = sql[
        sql.index("CREATE OR REPLACE FUNCTION public.memory_chunk_require_locator_parent_v1()") :
        sql.index(
            "DROP TRIGGER IF EXISTS trg_00_memory_chunk_require_locator_parent",
        )
    ]

    assert "identity_preserving_retraction BOOLEAN := FALSE" in function
    assert "OLD.status IS DISTINCT FROM 'deleted'" in function
    assert "NEW.status = 'deleted'" in function
    assert "OLD.retrieval_locator IS NOT NULL" in function
    assert "locator chunk retraction must preserve canonical parent identity" in function
    for identity in (
        "id",
        "space_id",
        "memory_scope_id",
        "thread_id",
        "document_id",
        "source_type",
        "source_external_id",
        "source_hash",
        "classification",
        "retrieval_locator",
        "retrieval_source_key",
        "retrieval_projection_generation",
        "retrieval_sequence_ordinal",
        "retrieval_kind",
        "retrieval_category",
    ):
        assert f"OLD.{identity}" in function
        assert f"NEW.{identity}" in function

    # Retractions require the extant parent but no admission eligibility, then
    # return before the admission-only lifecycle/classification predicates.
    egress = function.index("IF identity_preserving_retraction")
    egress_return = function.index("RETURN NEW;", egress)
    strict_parent = function.index(
        "parent.classification IS DISTINCT FROM NEW.classification"
    )
    egress_branch = function[egress:egress_return]
    assert function.index("IF NOT FOUND", egress) < egress_return
    assert "IF NOT FOUND THEN" in egress_branch
    for mutable_parent_coordinate in (
        "parent.space_id IS DISTINCT",
        "parent.memory_scope_id IS DISTINCT",
        "parent.thread_id IS DISTINCT",
        "parent.source_type IS DISTINCT",
        "parent.source_external_id IS DISTINCT",
    ):
        assert mutable_parent_coordinate not in egress_branch
    assert egress_return < strict_parent
    assert "parent.classification IS DISTINCT" not in egress_branch
    assert "parent.status IS DISTINCT" not in egress_branch
    assert "parent.retrieval_projected IS DISTINCT" not in egress_branch
    assert function.index("parent.status IS DISTINCT FROM 'active'") > strict_parent
    assert function.index("parent.retrieval_projected IS DISTINCT FROM TRUE") > strict_parent
    assert "ERRCODE = '23503'" in function


def test_parent_retraction_does_not_relax_benchmark_triggers() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    prefix = sql[: sql.index("-- The advisory identity also exists")]

    assert "trg_00_memory_chunks_benchmark_document_child_lock" in prefix
    assert "trg_memory_chunks_benchmark_document_child_fence" in prefix
    for protected_column in (
        "space_id",
        "document_id",
        "source_external_id",
        "text",
        "status",
        "classification",
        "retrieval_locator",
    ):
        assert prefix.count(protected_column) >= 2


def test_classification_tightening_exception_is_narrow_and_one_way() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    function = sql[
        sql.index("CREATE OR REPLACE FUNCTION public.memory_chunk_require_locator_parent_v1()") :
        sql.index(
            "DROP TRIGGER IF EXISTS trg_00_memory_chunk_require_locator_parent",
        )
    ]
    tightening = function[
        function.index(
            "    IF TG_OP = 'UPDATE'\n"
            "       AND OLD.retrieval_locator IS NOT NULL\n"
            "       AND OLD.status = 'active'"
        ) : function.index("    IF NEW.retrieval_locator IS NULL")
    ]

    assert "identity_preserving_classification_tightening BOOLEAN := FALSE" in function
    assert "OLD.status = 'active'" in tightening
    assert "NEW.status = 'active'" in tightening
    assert "OLD.classification IN ('public', 'internal')" in tightening
    assert "NEW.classification = 'restricted'" in tightening
    assert "classification tightening must preserve canonical parent identity" in tightening
    for identity in (
        "id",
        "space_id",
        "memory_scope_id",
        "thread_id",
        "document_id",
        "source_type",
        "source_external_id",
        "source_hash",
        "status",
        "retrieval_locator",
        "retrieval_source_key",
        "retrieval_projection_generation",
        "retrieval_sequence_ordinal",
        "retrieval_kind",
        "retrieval_category",
    ):
        assert f"OLD.{identity}" in tightening
        assert f"NEW.{identity}" in tightening

    # Tightening shares the monotonic egress branch. A restricted-to-internal
    # restoration is not marked and must satisfy the exact active parent path.
    egress = function.index("IF identity_preserving_retraction")
    egress_return = function.index("RETURN NEW;", egress)
    strict_parent = function.index(
        "parent.classification IS DISTINCT FROM NEW.classification"
    )
    assert egress < egress_return < strict_parent
    assert function.index("parent.status IS DISTINCT FROM 'active'") > strict_parent
    assert function.index("parent.retrieval_projected IS DISTINCT FROM TRUE") > strict_parent
    assert "ERRCODE = '23503'" in function

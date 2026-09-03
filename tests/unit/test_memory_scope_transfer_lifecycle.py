from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from infinity_context_core.domain.errors import MemoryConflictError
from infinity_context_server import memory_scope_transfer_lifecycle as lifecycle


def test_referenced_thread_ids_collects_every_canonical_child_type() -> None:
    skipped = {
        "facts": set(),
        "documents": set(),
        "episodes": {"episode-skipped"},
        "chunks": set(),
        "assets": set(),
        "asset_extraction_jobs": set(),
        "captures": set(),
    }

    assert lifecycle.referenced_thread_ids(
        facts=[{"id": "fact", "thread_id": "thread-fact"}],
        documents=[{"id": "document", "thread_id": "thread-document"}],
        episodes=[
            {"id": "episode-implicit"},
            {"id": "episode-skipped", "thread_id": "thread-skipped"},
        ],
        chunks=[{"id": "chunk", "thread_id": "thread-chunk"}],
        assets=[{"id": "asset", "thread_id": "thread-asset"}],
        asset_extraction_jobs=[{"id": "job", "thread_id": "thread-job"}],
        captures=[{"id": "capture", "thread_id": "thread-capture"}],
        skipped=skipped,
    ) == {
        "thread-fact",
        "thread-document",
        "episode-implicit",
        "thread-chunk",
        "thread-asset",
        "thread-job",
        "thread-capture",
    }


def test_create_new_scope_plans_remapped_threads_for_all_child_types() -> None:
    skipped = {
        "threads": set(),
        "facts": set(),
        "documents": set(),
        "episodes": set(),
        "chunks": set(),
        "assets": set(),
        "asset_extraction_jobs": set(),
        "captures": set(),
    }

    target_ids, creatable_ids, implicit_map = lifecycle.plan_snapshot_thread_fences(
        threads=[],
        facts=[{"id": "fact", "thread_id": "thread-fact"}],
        documents=[{"id": "document", "thread_id": "thread-document"}],
        episodes=[],
        chunks=[],
        assets=[{"id": "asset", "thread_id": "thread-asset"}],
        asset_extraction_jobs=[],
        captures=[{"id": "capture", "thread_id": "thread-capture"}],
        skipped=skipped,
        thread_id_map={
            "thread-fact": "mapped-fact",
            "thread-document": "mapped-document",
            "thread-asset": "mapped-asset",
            "thread-capture": "mapped-capture",
        },
        create_new_memory_scope=True,
    )

    assert target_ids == creatable_ids == {
        "mapped-fact",
        "mapped-document",
        "mapped-asset",
        "mapped-capture",
    }
    assert set(implicit_map.values()) == target_ids


def test_snapshot_fences_global_before_sorted_exact_and_rejects_deleted(monkeypatch) -> None:
    calls: list[str] = []

    async def lock_global(*_args, **_kwargs) -> None:
        calls.append("global")

    async def lock_exact(*_args, thread_id: str, **_kwargs) -> None:
        calls.append(thread_id)

    class Result:
        def scalars(self):
            return iter(
                (
                    SimpleNamespace(
                        id="thread-a",
                        space_id="space",
                        memory_scope_id="scope",
                        status="active",
                    ),
                    SimpleNamespace(
                        id="thread-b",
                        space_id="space",
                        memory_scope_id="scope",
                        status="deleted",
                    ),
                )
            )

    class Session:
        async def execute(self, _statement):
            return Result()

    monkeypatch.setattr(lifecycle, "lock_global_fact_lifecycle", lock_global)
    monkeypatch.setattr(lifecycle, "lock_exact_thread_lifecycle", lock_exact)

    with pytest.raises(MemoryConflictError, match="neither active nor created"):
        asyncio.run(
            lifecycle.fence_snapshot_import_threads(
                Session(),
                space_id="space",
                memory_scope_id="scope",
                thread_ids={"thread-b", "thread-a"},
                creatable_thread_ids=set(),
            )
        )

    assert calls == ["global", "thread-a", "thread-b"]


def test_snapshot_fences_drop_missing_legacy_thread_and_admit_explicit_creation(
    monkeypatch,
) -> None:
    calls: list[str] = []

    async def lock_global(*_args, **_kwargs) -> None:
        calls.append("global")

    async def lock_exact(*_args, thread_id: str, **_kwargs) -> None:
        calls.append(thread_id)

    class Result:
        def scalars(self):
            return iter(
                (
                    SimpleNamespace(
                        id="thread-active",
                        space_id="space",
                        memory_scope_id="scope",
                        status="active",
                    ),
                )
            )

    class Session:
        async def execute(self, _statement):
            return Result()

    monkeypatch.setattr(lifecycle, "lock_global_fact_lifecycle", lock_global)
    monkeypatch.setattr(lifecycle, "lock_exact_thread_lifecycle", lock_exact)

    admitted = asyncio.run(
        lifecycle.fence_snapshot_import_threads(
            Session(),
            space_id="space",
            memory_scope_id="scope",
            thread_ids={"thread-active", "thread-created", "thread-legacy-missing"},
            creatable_thread_ids={"thread-created"},
        )
    )

    assert admitted == {"thread-active", "thread-created"}
    assert calls == [
        "global",
        "thread-active",
        "thread-created",
        "thread-legacy-missing",
    ]

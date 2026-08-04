from __future__ import annotations

import os
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from mem0.configs.base import MemoryConfig
from mem0.utils.factory import LlmFactory

from mem0_oss_adapter.models import AddRequest
from mem0_oss_adapter.residue import prepare_scope_ledger, record_scope_memory_ids
from mem0_oss_adapter.sdk_oss import (
    Mem0OssSdkPort,
    OssRuntimeSettings,
    _patched_mem0_factories,
    pinned_memory_config,
)
from mem0_oss_adapter.service import AdapterError, OssCompatibilityService
from mem0_oss_adapter.subscription_llm import SubscriptionOpenAICompatibleLlm, UsageLedger


@dataclass
class _Record:
    id: str
    user_id: str
    run_id: str
    source_id: str = "source-1"
    source_sha256: str = "a" * 64
    payload: dict[str, object] | None = None


class _ScopedStore:
    def __init__(self) -> None:
        self.rows: list[_Record] = []

    def list(self, *, filters: dict[str, str], top_k: int) -> tuple[list[_Record], None]:
        assert top_k == 10_000
        return [
            row
            for row in self.rows
            if all(getattr(row, key) == value for key, value in filters.items())
        ], None

    def delete(self, *, vector_id: str) -> None:
        self.rows = [row for row in self.rows if row.id != vector_id]


class _FakeMem0Sqlite:
    def __init__(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self._lock = threading.Lock()
        self.connection.executescript(
            """
            CREATE TABLE history (
                id TEXT PRIMARY KEY,
                memory_id TEXT,
                old_memory TEXT,
                new_memory TEXT,
                event TEXT,
                created_at DATETIME,
                updated_at DATETIME,
                is_deleted INTEGER,
                actor_id TEXT,
                role TEXT
            );
            CREATE TABLE messages (
                id TEXT PRIMARY KEY,
                session_scope TEXT,
                role TEXT,
                content TEXT,
                name TEXT,
                created_at DATETIME
            );
            """
        )


class FakeMemory:
    def __init__(self) -> None:
        self.add_kwargs: dict[str, Any] | None = None
        self.add_calls = 0
        self.delete_kwargs: dict[str, Any] | None = None
        self.fail_after_history = False
        self.fail_after_message = False
        self.fail_after_untagged_vector = False
        self.invalid_result = False
        self.vector_store = _ScopedStore()
        self.entity_store = _ScopedStore()
        self.db = _FakeMem0Sqlite()

    def add(self, messages: list[dict[str, str]], **kwargs: Any) -> dict[str, object]:
        self.add_calls += 1
        self.add_kwargs = {"messages": messages, **kwargs}
        if self.fail_after_message:
            self.db.connection.execute(
                "INSERT INTO messages (id, session_scope, content) VALUES (?, ?, ?)",
                (
                    "failed-message",
                    f"run_id={kwargs['run_id']}&user_id={kwargs['user_id']}",
                    messages[-1]["content"],
                ),
            )
            self.db.connection.commit()
            raise RuntimeError("provider failed after saving messages")
        if self.fail_after_untagged_vector:
            self.vector_store.rows.append(
                _Record("untagged-memory", kwargs["user_id"], kwargs["run_id"], "", "")
            )
            raise RuntimeError("provider failed after saving an untagged vector")
        memory_id = "orphan-memory" if self.fail_after_history else f"memory-{self.add_calls}"
        if not self.fail_after_history:
            metadata = kwargs["metadata"]
            self.vector_store.rows.append(
                _Record(
                    memory_id,
                    kwargs["user_id"],
                    kwargs["run_id"],
                    metadata["source_id"],
                    metadata["source_sha256"],
                )
            )
        self.db.connection.execute(
            "INSERT INTO history (id, memory_id, new_memory) VALUES (?, ?, ?)",
            (f"history-{memory_id}", memory_id, messages[-1]["content"]),
        )
        self.db.connection.commit()
        if self.fail_after_history:
            raise RuntimeError("provider failed after saving orphan history")
        if self.invalid_result:
            return {"id": memory_id, "results": "invalid"}
        return {"id": memory_id, "results": [{"id": memory_id}]}

    def get_all(self, **_kwargs: Any) -> dict[str, object]:
        return {"results": []}

    def delete_all(self, **kwargs: Any) -> None:
        self.delete_kwargs = kwargs
        self.vector_store.rows = [
            row
            for row in self.vector_store.rows
            if row.user_id != kwargs["user_id"] or row.run_id != kwargs["run_id"]
        ]

    def delete(self, memory_id: str) -> None:
        self.vector_store.delete(vector_id=memory_id)

    def _remove_memory_from_entity_store(
        self,
        memory_id: str,
        filters: dict[str, str],
    ) -> None:
        for row in list(self.entity_store.rows):
            if row.user_id != filters["user_id"] or row.run_id != filters["run_id"]:
                continue
            payload = row.payload or {}
            linked = payload.get("linked_memory_ids", [])
            if not isinstance(linked, list) or memory_id not in linked:
                continue
            remaining = [item for item in linked if item != memory_id]
            if remaining:
                row.payload = {**payload, "linked_memory_ids": remaining}
            else:
                self.entity_store.delete(vector_id=row.id)


def _settings(
    tmp_path: Path,
    *,
    extraction_mode: str = "raw_passthrough",
) -> OssRuntimeSettings:
    return OssRuntimeSettings(
        qdrant_host="127.0.0.1",
        qdrant_port=6333,
        collection_name="unit_collection",
        state_dir=tmp_path / "state",
        model_dir=tmp_path / "model",
        extraction_mode=extraction_mode,
        bridge_url=("http://127.0.0.1:19090/v1" if extraction_mode == "subscription_llm" else None),
        bearer_token=("explicit-token" if extraction_mode == "subscription_llm" else None),
    )


def test_sdk_uses_wrapper_metadata_and_never_forwards_native_timestamp(tmp_path: Path) -> None:
    memory = FakeMemory()
    port = Mem0OssSdkPort(settings=_settings(tmp_path), memory_factory=lambda: memory)

    result = port.add(
        messages=[{"role": "user", "content": "raw fact"}],
        user_id="user-1",
        agent_id=None,
        run_id="run-1",
        metadata={"source_id": "source-1", "source_sha256": "a" * 64},
        timestamp=1_672_531_200,
    )

    assert result["id"] == "memory-1"
    assert memory.add_kwargs is not None
    assert memory.add_kwargs["timestamp"] is None
    assert memory.add_kwargs["infer"] is False
    assert memory.add_kwargs["metadata"]["created_at"] == "2023-01-01T00:00:00Z"
    assert port.last_sdk_timestamp is None
    assert port.usage_ledger.entries[-1].extraction_calls == 0


def test_sdk_ignores_ambient_openai_and_mem0_keys(tmp_path: Path, monkeypatch) -> None:
    for key in ("OPENAI_API_KEY", "MEM0_API_KEY", "OPENAI_BASE_URL"):
        monkeypatch.setenv(key, "ambient-secret")
    memory = FakeMemory()
    port = Mem0OssSdkPort(settings=_settings(tmp_path), memory_factory=lambda: memory)

    port.add(
        messages=[{"role": "user", "content": "raw fact"}],
        user_id="user-1",
        agent_id=None,
        run_id="run-1",
        metadata={"source_id": "source-1", "source_sha256": "a" * 64},
        timestamp=1,
    )

    keys = ("OPENAI_API_KEY", "MEM0_API_KEY", "OPENAI_BASE_URL")
    assert all(key not in os.environ for key in keys)
    assert os.environ["MEM0_TELEMETRY"] == "false"


def test_sdk_delete_purges_all_adapter_owned_scope_residue(tmp_path: Path) -> None:
    memory = FakeMemory()
    prepare_scope_ledger(memory.db)
    record_scope_memory_ids(
        memory.db,
        memory_ids=("memory-1", "non-live-memory"),
        user_id="user-1",
        run_id="run-1",
        source_id="source-1",
        source_sha256="a" * 64,
    )
    record_scope_memory_ids(
        memory.db,
        memory_ids=("other-memory",),
        user_id="user-2",
        run_id="run-2",
        source_id="other-source",
        source_sha256="b" * 64,
    )
    memory.vector_store.rows = [
        _Record("memory-1", "user-1", "run-1"),
        _Record("other-memory", "user-2", "run-2", "other-source", "b" * 64),
    ]
    memory.entity_store.rows = [
        _Record("entity-1", "user-1", "run-1"),
        _Record("other-entity", "user-2", "run-2"),
    ]
    memory.db.connection.executemany(
        "INSERT INTO history (id, memory_id, old_memory, new_memory) VALUES (?, ?, ?, ?)",
        [
            ("history-1", "memory-1", "private", None),
            ("history-2", "non-live-memory", "private removed vector", None),
            ("history-3", "other-memory", "keep", None),
        ],
    )
    memory.db.connection.executemany(
        "INSERT INTO messages (id, session_scope, content) VALUES (?, ?, ?)",
        [
            ("message-1", "run_id=run-1&user_id=user-1", "private"),
            ("message-2", "run_id=run-2&user_id=user-2", "keep"),
        ],
    )
    memory.db.connection.commit()
    port = Mem0OssSdkPort(settings=_settings(tmp_path), memory_factory=lambda: memory)

    assert port.delete_memories(user_id="user-1", run_id="run-1") is True

    assert memory.delete_kwargs == {"user_id": "user-1", "run_id": "run-1"}
    assert [row.id for row in memory.vector_store.rows] == ["other-memory"]
    assert [row.id for row in memory.entity_store.rows] == ["other-entity"]
    assert memory.db.connection.execute("SELECT memory_id FROM history").fetchall() == [
        ("other-memory",)
    ]
    assert memory.db.connection.execute("SELECT session_scope FROM messages").fetchall() == [
        ("run_id=run-2&user_id=user-2",)
    ]
    assert memory.db.connection.execute(
        "SELECT memory_id FROM infinity_context_scope_ledger"
    ).fetchall() == [("other-memory",)]


def test_sdk_source_cleanup_preserves_other_source_in_the_same_run(tmp_path: Path) -> None:
    memory = FakeMemory()
    prepare_scope_ledger(memory.db)
    record_scope_memory_ids(
        memory.db,
        memory_ids=("target-memory",),
        user_id="user-1",
        run_id="run-1",
        source_id="target-source",
        source_sha256="a" * 64,
    )
    record_scope_memory_ids(
        memory.db,
        memory_ids=("prior-memory",),
        user_id="user-1",
        run_id="run-1",
        source_id="prior-source",
        source_sha256="b" * 64,
    )
    memory.vector_store.rows = [
        _Record("target-memory", "user-1", "run-1", "target-source", "a" * 64),
        _Record("prior-memory", "user-1", "run-1", "prior-source", "b" * 64),
    ]
    memory.entity_store.rows = [
        _Record(
            "shared-entity",
            "user-1",
            "run-1",
            payload={"linked_memory_ids": ["target-memory", "prior-memory"]},
        )
    ]
    memory.db.connection.executemany(
        "INSERT INTO history (id, memory_id, old_memory) VALUES (?, ?, ?)",
        [
            ("history-target", "target-memory", "private target"),
            ("history-prior", "prior-memory", "keep prior"),
        ],
    )
    memory.db.connection.commit()
    port = Mem0OssSdkPort(settings=_settings(tmp_path), memory_factory=lambda: memory)

    assert port.delete_source_memories(
        user_id="user-1",
        run_id="run-1",
        source_id="target-source",
        source_sha256="a" * 64,
    )

    assert [row.id for row in memory.vector_store.rows] == ["prior-memory"]
    assert memory.entity_store.rows[0].payload == {"linked_memory_ids": ["prior-memory"]}
    assert memory.db.connection.execute("SELECT memory_id FROM history").fetchall() == [
        ("prior-memory",)
    ]
    assert memory.db.connection.execute(
        "SELECT memory_id, source_id FROM infinity_context_scope_ledger"
    ).fetchall() == [("prior-memory", "prior-source")]


def test_subscription_mode_rejects_a_second_add_before_the_model_call(tmp_path: Path) -> None:
    memory = FakeMemory()
    port = Mem0OssSdkPort(
        settings=_settings(tmp_path, extraction_mode="subscription_llm"),
        memory_factory=lambda: memory,
    )
    kwargs = {
        "messages": [{"role": "user", "content": "subscription smoke"}],
        "user_id": "user-1",
        "agent_id": None,
        "run_id": "run-1",
        "metadata": {"source_id": "source-1", "source_sha256": "a" * 64},
        "timestamp": 1,
    }

    port.add(**kwargs)
    with pytest.raises(RuntimeError, match="fresh isolated scope"):
        port.add(**kwargs)

    assert memory.add_calls == 1
    assert len(port.usage_ledger.entries) == 1


def test_failed_subscription_add_purges_its_messages_and_preserves_other_scope(
    tmp_path: Path,
) -> None:
    memory = FakeMemory()
    prepare_scope_ledger(memory.db)
    memory.db.connection.execute(
        "INSERT INTO messages (id, session_scope, content) VALUES (?, ?, ?)",
        ("other-message", "run_id=run-2&user_id=user-2", "keep"),
    )
    memory.db.connection.commit()
    memory.fail_after_message = True
    port = Mem0OssSdkPort(
        settings=_settings(tmp_path, extraction_mode="subscription_llm"),
        memory_factory=lambda: memory,
    )
    service = OssCompatibilityService(port)

    with pytest.raises(AdapterError, match="add or source readback"):
        service.add(
            AddRequest(
                messages=[{"role": "user", "content": "failed subscription source"}],
                user_id="user-1",
                run_id="run-1",
                metadata={"source_id": "source-1", "source_sha256": "a" * 64},
                timestamp=1,
            )
        )

    assert memory.db.connection.execute(
        "SELECT id, session_scope, content FROM messages"
    ).fetchall() == [("other-message", "run_id=run-2&user_id=user-2", "keep")]


def test_provider_exception_ledgers_and_purges_orphan_history_without_live_vector(
    tmp_path: Path,
) -> None:
    memory = FakeMemory()
    memory.fail_after_history = True
    port = Mem0OssSdkPort(settings=_settings(tmp_path), memory_factory=lambda: memory)
    service = OssCompatibilityService(port)

    with pytest.raises(AdapterError, match="add or source readback"):
        service.add(
            AddRequest(
                messages=[{"role": "user", "content": "orphaned history"}],
                user_id="user-1",
                run_id="run-1",
                metadata={"source_id": "source-1", "source_sha256": "a" * 64},
                timestamp=1,
            )
        )

    assert memory.vector_store.rows == []
    assert memory.db.connection.execute("SELECT memory_id FROM history").fetchall() == []
    assert (
        memory.db.connection.execute(
            "SELECT memory_id FROM infinity_context_scope_ledger"
        ).fetchall()
        == []
    )


def test_provider_exception_ledgers_and_purges_untagged_live_vector(tmp_path: Path) -> None:
    memory = FakeMemory()
    memory.fail_after_untagged_vector = True
    port = Mem0OssSdkPort(settings=_settings(tmp_path), memory_factory=lambda: memory)
    service = OssCompatibilityService(port)

    with pytest.raises(AdapterError, match="add or source readback"):
        service.add(
            AddRequest(
                messages=[{"role": "user", "content": "untagged vector"}],
                user_id="user-1",
                run_id="run-1",
                metadata={"source_id": "source-1", "source_sha256": "a" * 64},
                timestamp=1,
            )
        )

    assert memory.vector_store.rows == []
    assert memory.db.connection.execute("SELECT memory_id FROM history").fetchall() == []
    assert (
        memory.db.connection.execute(
            "SELECT memory_id FROM infinity_context_scope_ledger"
        ).fetchall()
        == []
    )


def test_invalid_provider_result_is_ledgered_before_exact_compensation(tmp_path: Path) -> None:
    memory = FakeMemory()
    memory.invalid_result = True
    port = Mem0OssSdkPort(settings=_settings(tmp_path), memory_factory=lambda: memory)
    service = OssCompatibilityService(port)

    with pytest.raises(AdapterError, match="add or source readback"):
        service.add(
            AddRequest(
                messages=[{"role": "user", "content": "invalid result"}],
                user_id="user-1",
                run_id="run-1",
                metadata={"source_id": "source-1", "source_sha256": "a" * 64},
                timestamp=1,
            )
        )

    assert memory.vector_store.rows == []
    assert memory.db.connection.execute("SELECT memory_id FROM history").fetchall() == []
    assert (
        memory.db.connection.execute(
            "SELECT memory_id FROM infinity_context_scope_ledger"
        ).fetchall()
        == []
    )


def test_real_mem0_factory_constructs_the_narrow_subscription_llm_without_a_call() -> None:
    ledger = UsageLedger()
    with _patched_mem0_factories():
        llm = LlmFactory.create(
            "openai",
            config={
                "bridge_url": "http://127.0.0.1:19090/v1",
                "bearer_token": "explicit-token",
                "mode": "subscription_llm",
                "usage_ledger": ledger,
                "request_max_bytes": 1024,
                "response_max_bytes": 1024,
                "model": "gpt-5.6-sol",
            },
        )
    try:
        assert isinstance(llm, SubscriptionOpenAICompatibleLlm)
    finally:
        llm.close()


def test_pinned_configuration_is_accepted_by_real_mem0_without_provider_construction(
    tmp_path: Path,
) -> None:
    config = pinned_memory_config(_settings(tmp_path), usage_ledger=UsageLedger())

    parsed = MemoryConfig(**config)

    assert parsed.version == "v1.1"
    assert parsed.llm.provider == "openai"
    assert parsed.embedder.provider == "fastembed"
    assert parsed.vector_store.provider == "qdrant"

"""Independent global Qdrant and Mem0 SQLite exact-state verification."""

from __future__ import annotations

import hashlib
import http.client
import json
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .canonical import E2EVerificationError, canonical_bytes, canonical_sha256, exact_object

_MAX_GLOBAL_POINTS = 10_000
_PINNED_VECTOR_PAYLOAD_KEYS = {
    "user_id",
    "run_id",
    "source_id",
    "source_sha256",
    "extraction_memory_id",
    "attributed_to",
    "linked_memory_ids",
    "role",
    "data",
    "hash",
    "created_at",
    "updated_at",
    "text_lemmatized",
}
_MEM0_TABLE_COLUMNS = {
    "history": {
        "id",
        "memory_id",
        "old_memory",
        "new_memory",
        "event",
        "created_at",
        "updated_at",
        "is_deleted",
        "actor_id",
        "role",
    },
    "messages": {"id", "session_scope", "role", "content", "name", "created_at"},
    "infinity_context_scope_ledger": {
        "memory_id",
        "user_id",
        "run_id",
        "source_id",
        "source_sha256",
    },
}


@dataclass(frozen=True, slots=True)
class StorageScope:
    user_id: str
    run_id: str
    source_id: str
    source_sha256: str

    @property
    def filters(self) -> dict[str, str]:
        return {
            "user_id": self.user_id,
            "run_id": self.run_id,
            "source_id": self.source_id,
            "source_sha256": self.source_sha256,
        }


@dataclass(frozen=True, slots=True)
class StorageAudit:
    provider_memory_ids: tuple[str, ...]
    commitment_sha256: str


class QdrantInventory(Protocol):
    collection: str
    entity_collection: str

    def scroll_all(self, collection: str) -> list[dict[str, object]]: ...


class QdrantHttp:
    def __init__(self, *, port: int = 6334, collection: str = "mem0_oss_v5") -> None:
        self._port = port
        self.collection = collection
        self.entity_collection = f"{collection}_entities"

    def scroll_all(self, collection: str) -> list[dict[str, object]]:
        if collection not in {self.collection, self.entity_collection}:
            raise E2EVerificationError("e2e_qdrant_collection_invalid")
        points: list[dict[str, object]] = []
        offset: object | None = None
        while True:
            body: dict[str, object] = {
                "limit": 256,
                "with_payload": True,
                "with_vector": False,
            }
            if offset is not None:
                body["offset"] = offset
            value = self._request("POST", f"/collections/{collection}/points/scroll", body)
            result = exact_object(
                value.get("result"),
                {"points", "next_page_offset"},
                "e2e_qdrant_response_invalid",
            )
            page = result["points"]
            if not isinstance(page, list) or any(not isinstance(point, dict) for point in page):
                raise E2EVerificationError("e2e_qdrant_response_invalid")
            points.extend(page)  # type: ignore[arg-type]
            if len(points) > _MAX_GLOBAL_POINTS:
                raise E2EVerificationError("e2e_qdrant_inventory_unbounded")
            next_offset = result["next_page_offset"]
            if next_offset is None:
                return points
            if not page or next_offset == offset:
                raise E2EVerificationError("e2e_qdrant_response_invalid")
            offset = next_offset

    def inject_residue(self, scope: StorageScope) -> str:
        point_id = str(uuid.uuid4())
        payload = {
            **scope.filters,
            "extraction_memory_id": "forged-residue",
            "memory": "forged synthetic residue",
            "attributed_to": "user",
            "linked_memory_ids": [],
        }
        self._request(
            "PUT",
            f"/collections/{self.collection}/points?wait=true",
            {"points": [{"id": point_id, "vector": [0.0] * 384, "payload": payload}]},
        )
        return point_id

    def delete_point(self, point_id: str) -> None:
        self._request(
            "POST",
            f"/collections/{self.collection}/points/delete?wait=true",
            {"points": [point_id]},
        )

    def _request(self, method: str, path: str, body: object) -> dict[str, object]:
        connection = http.client.HTTPConnection("127.0.0.1", self._port, timeout=15)
        try:
            connection.request(
                method,
                path,
                body=canonical_bytes(body),
                headers={"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            content = response.read(2_000_001)
        except Exception:
            raise E2EVerificationError("e2e_qdrant_transport_failed") from None
        finally:
            connection.close()
        if response.status != 200 or not 1 <= len(content) <= 2_000_000:
            raise E2EVerificationError("e2e_qdrant_request_failed")
        try:
            value = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise E2EVerificationError("e2e_qdrant_response_invalid") from None
        if not isinstance(value, dict) or value.get("status") != "ok":
            raise E2EVerificationError("e2e_qdrant_response_invalid")
        return value


@dataclass(frozen=True, slots=True)
class _SqliteInventory:
    history: tuple[tuple[object, ...], ...]
    messages: tuple[tuple[object, ...], ...]
    ledger: tuple[tuple[object, ...], ...] | None


class IndependentStorageAuditor:
    def __init__(self, *, qdrant: QdrantInventory, history_db: Path) -> None:
        if not history_db.is_absolute():
            raise ValueError("e2e_storage_auditor_invalid")
        self._qdrant = qdrant
        self._history_db = history_db

    def verify_exact(
        self,
        *,
        scope: StorageScope,
        expected_text: str,
        expected_extraction_id: str = "0",
    ) -> StorageAudit:
        points = self._qdrant.scroll_all(self._qdrant.collection)
        if len(points) != 1 or self._qdrant.scroll_all(self._qdrant.entity_collection):
            raise E2EVerificationError("e2e_storage_inventory_invalid")
        vector = self._vector(points[0], scope, expected_text=expected_text)
        if (
            vector["extraction_memory_id"] != expected_extraction_id
            or vector["text"] != expected_text
            or vector["attributed_to"] != "user"
            or vector["linked_memory_ids"] != []
        ):
            raise E2EVerificationError("e2e_storage_payload_invalid")
        provider_ids = (str(vector["provider_memory_id"]),)
        inventory = self._sqlite_inventory()
        self._verify_sqlite_exact(
            inventory,
            scope=scope,
            provider_memory_id=provider_ids[0],
            expected_text=expected_text,
        )
        snapshot = {
            "vectors": [vector],
            "history_memory_ids": list(provider_ids),
            "message_ids": [],
            "entity_links": [],
        }
        return StorageAudit(provider_ids, canonical_sha256(snapshot))

    def verify_absent(self, *, scope: StorageScope, sealed_provider_ids: tuple[str, ...]) -> None:
        del scope, sealed_provider_ids
        if self._qdrant.scroll_all(self._qdrant.collection) or self._qdrant.scroll_all(
            self._qdrant.entity_collection
        ):
            raise E2EVerificationError("e2e_storage_residue_detected")
        inventory = self._sqlite_inventory()
        if inventory.history or inventory.messages or inventory.ledger:
            raise E2EVerificationError("e2e_storage_residue_detected")

    @staticmethod
    def _vector(
        point: dict[str, object], scope: StorageScope, *, expected_text: str
    ) -> dict[str, object]:
        if set(point) - {"id", "version", "score", "payload", "vector", "shard_key", "order_value"}:
            raise E2EVerificationError("e2e_storage_payload_invalid")
        payload = point.get("payload")
        if (
            not isinstance(payload, dict)
            or set(payload) != _PINNED_VECTOR_PAYLOAD_KEYS
            or any(payload.get(key) != value for key, value in scope.filters.items())
        ):
            raise E2EVerificationError("e2e_storage_provenance_invalid")
        provider_id = point.get("id")
        extraction_id = payload.get("extraction_memory_id")
        text = payload.get("data")
        attributed = payload.get("attributed_to")
        links = payload.get("linked_memory_ids")
        created_at = payload.get("created_at")
        if (
            provider_id is None
            or not isinstance(extraction_id, str)
            or not isinstance(text, str)
            or (attributed is not None and not isinstance(attributed, str))
            or not isinstance(links, list)
            or any(not isinstance(item, str) for item in links)
            or payload.get("role") != "assistant"
            or payload.get("hash")
            != hashlib.md5(expected_text.encode(), usedforsecurity=False).hexdigest()
            or not isinstance(created_at, str)
            or not created_at
            or payload.get("updated_at") != created_at
            or payload.get("text_lemmatized") != expected_text
        ):
            raise E2EVerificationError("e2e_storage_payload_invalid")
        return {
            "provider_memory_id": str(provider_id),
            "extraction_memory_id": extraction_id,
            "text": text,
            "attributed_to": attributed,
            "linked_memory_ids": sorted(links),
        }

    def _sqlite_inventory(self) -> _SqliteInventory:
        if self._history_db.is_symlink() or not self._history_db.is_file():
            raise E2EVerificationError("e2e_storage_sqlite_invalid")
        connection = sqlite3.connect(f"file:{self._history_db}?mode=ro", uri=True, timeout=10)
        try:
            tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            }
            required_tables = {"history", "messages"}
            allowed_tables = required_tables | {"infinity_context_scope_ledger"}
            if not required_tables.issubset(tables) or not tables.issubset(allowed_tables):
                raise E2EVerificationError("e2e_storage_sqlite_invalid")
            for table in tables:
                expected = _MEM0_TABLE_COLUMNS[table]
                columns = {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}
                if columns != expected:
                    raise E2EVerificationError("e2e_storage_sqlite_invalid")
            history = tuple(
                connection.execute(
                    """SELECT id, memory_id, old_memory, new_memory, event, created_at,
                              updated_at, is_deleted, actor_id, role
                       FROM history ORDER BY id"""
                ).fetchall()
            )
            messages = tuple(
                connection.execute(
                    """SELECT id, session_scope, role, content, name, created_at
                       FROM messages ORDER BY id"""
                ).fetchall()
            )
            ledger = (
                tuple(
                    connection.execute(
                        """SELECT memory_id, user_id, run_id, source_id, source_sha256
                           FROM infinity_context_scope_ledger ORDER BY memory_id"""
                    ).fetchall()
                )
                if "infinity_context_scope_ledger" in tables
                else None
            )
        except E2EVerificationError:
            raise
        except sqlite3.Error:
            raise E2EVerificationError("e2e_storage_sqlite_invalid") from None
        finally:
            connection.close()
        return _SqliteInventory(history, messages, ledger)

    @staticmethod
    def _verify_sqlite_exact(
        inventory: _SqliteInventory,
        *,
        scope: StorageScope,
        provider_memory_id: str,
        expected_text: str,
    ) -> None:
        expected_ledger = (
            (
                provider_memory_id,
                scope.user_id,
                scope.run_id,
                scope.source_id,
                scope.source_sha256,
            ),
        )
        if (
            inventory.messages
            or inventory.ledger not in {None, expected_ledger}
            or len(inventory.history) != 1
        ):
            raise E2EVerificationError("e2e_storage_sqlite_invalid")
        row = inventory.history[0]
        if (
            len(row) != 10
            or not isinstance(row[0], str)
            or not row[0]
            or row[1] != provider_memory_id
            or row[2] is not None
            or row[3] != expected_text
            or row[4] != "ADD"
            or not isinstance(row[5], str)
            or not row[5]
            or row[6] != row[5]
            or row[7] != 0
            or row[8] is not None
            or row[9] != "assistant"
        ):
            raise E2EVerificationError("e2e_storage_sqlite_invalid")

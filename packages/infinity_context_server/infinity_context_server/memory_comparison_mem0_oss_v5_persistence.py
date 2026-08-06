"""Authenticated, rollback-resistant SQLite projection for Mem0 OSS v5 evidence."""

from __future__ import annotations

import base64
import fcntl
import hashlib
import hmac
import json
import os
import sqlite3
import stat
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from functools import cache, wraps
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Protocol, final

from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    MEM0_OSS_EMPTY_ROOT_SHA256,
    Mem0OssFullRunAdmission,
    Mem0OssManifestUnit,
    Mem0OssOperationState,
    Mem0OssReceiptDisposition,
    RuntimeReceiptVerificationResult,
    StorageVerificationResult,
    canonical_sha256,
    is_sha256,
    manifest_root_sha256,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_run import (
    Mem0OssFailedReceiptEvidence,
    Mem0OssRunSeal,
    Mem0OssTerminalCleanupEvidence,
)

_STORE_SCHEMA_VERSION = "mem0-v5-evidence-store.v2"
_CHECKPOINT_SCHEMA_VERSION = "mem0-v5-evidence-checkpoint.v1"
_MAX_ROWS = 30_010
_MAX_PAYLOAD_BYTES = 64_000
_MANIFEST_PAGE_SIZE = 64
_CREATE_TOKEN = object()
_TERMINAL_QUERY = "SELECT 1 FROM evidence WHERE kind='cleanup' LIMIT 1"
_EvidenceRow = tuple[str, str, Mapping[str, object]]
_SCHEMA = (
    "CREATE TABLE store_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    """CREATE TABLE evidence (
        sequence INTEGER PRIMARY KEY,
        kind TEXT NOT NULL,
        subject_sha256 TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        predecessor_sha256 TEXT NOT NULL,
        row_sha256 TEXT NOT NULL UNIQUE,
        row_mac_sha256 TEXT NOT NULL,
        UNIQUE(kind, subject_sha256)
    )""",
)


def _serialized(method: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(method)
    def guarded(self: SQLiteMem0V5EvidenceStore, *args: object, **kwargs: object) -> object:
        with self._guard():
            return method(self, *args, **kwargs)

    return guarded


class Mem0V5EvidenceStoreError(RuntimeError):
    _SAFE = frozenset(
        {
            "mem0_v5_evidence_store_busy",
            "mem0_v5_evidence_store_configuration_invalid",
            "mem0_v5_evidence_store_corrupt",
            "mem0_v5_evidence_store_duplicate",
            "mem0_v5_evidence_store_order_invalid",
            "mem0_v5_evidence_store_payload_invalid",
            "mem0_v5_evidence_store_terminal_invalid",
        }
    )

    def __init__(self, code: str) -> None:
        safe = code if code in self._SAFE else "mem0_v5_evidence_store_corrupt"
        self.code = safe
        super().__init__(safe)


@final
@dataclass(frozen=True, slots=True)
class Mem0V5StoreCheckpoint:
    token: str

    def __post_init__(self) -> None:
        if type(self.token) is not str or not 80 <= len(self.token) <= 2_048:
            raise Mem0V5EvidenceStoreError("mem0_v5_evidence_store_configuration_invalid")

    def __repr__(self) -> str:
        return "Mem0V5StoreCheckpoint(<authenticated>)"


class Mem0V5EvidenceStorePort(Protocol):
    def put_admission(
        self, admission: Mem0OssFullRunAdmission, *, units: tuple[Mem0OssManifestUnit, ...]
    ) -> str: ...

    def put_receipt(self, *, unit_index: int, receipt: RuntimeReceiptVerificationResult) -> str: ...

    def put_storage(self, *, unit_index: int, storage: StorageVerificationResult) -> str: ...

    def put_seal(self, seal: Mem0OssRunSeal) -> str: ...

    def put_cleanup(self, cleanup: Mem0OssTerminalCleanupEvidence) -> str: ...

    def issue_checkpoint(self, *, checkpoint_key: bytes) -> Mem0V5StoreCheckpoint: ...


@final
class SQLiteMem0V5EvidenceStore(Mem0V5EvidenceStorePort):
    """Single-owner append-only projection; lifecycle state remains in the journal."""

    __slots__ = (
        "_connection",
        "_admission_payload",
        "_admission_subject",
        "_key",
        "_lock_file",
        "_manifest_operations",
        "_mutex",
        "_path",
        "_receipts",
        "_store_id_sha256",
        "_storage",
    )

    def __init__(
        self,
        *,
        path: Path,
        authentication_key: bytes,
        checkpoint: Mem0V5StoreCheckpoint | None,
        checkpoint_key: bytes | None,
        _token: object,
    ) -> None:
        if (
            _token is not _CREATE_TOKEN
            or not isinstance(path, Path)
            or not _valid_key(authentication_key)
            or (checkpoint is None) != (checkpoint_key is None)
            or (checkpoint is not None and type(checkpoint) is not Mem0V5StoreCheckpoint)
            or (checkpoint_key is not None and not _valid_key(checkpoint_key))
        ):
            raise Mem0V5EvidenceStoreError("mem0_v5_evidence_store_configuration_invalid")
        self._path = path
        self._key = authentication_key
        self._mutex = threading.RLock()
        self._admission_payload: dict[str, object] | None = None
        self._admission_subject: str | None = None
        self._manifest_operations: tuple[dict[str, object], ...] = ()
        self._receipts: dict[str, dict[str, object]] = {}
        self._storage: dict[str, dict[str, object]] = {}
        self._lock_file = None
        self._connection = None
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        existed = path.exists()
        if (checkpoint is None and existed) or (checkpoint is not None and not existed):
            raise Mem0V5EvidenceStoreError("mem0_v5_evidence_store_corrupt")
        try:
            lock_path = path.with_suffix(path.suffix + ".owner.lock")
            lock_file = lock_path.open("a+b")
            os.chmod(lock_path, stat.S_IRUSR | stat.S_IWUSR)
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                lock_file.close()
                raise Mem0V5EvidenceStoreError("mem0_v5_evidence_store_busy") from None
            self._lock_file = lock_file
            connection = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA trusted_schema = OFF")
            connection.execute("PRAGMA busy_timeout = 5000")
            connection.execute("PRAGMA journal_mode = WAL")
            self._connection = connection
            if checkpoint is None:
                self._store_id_sha256 = hashlib.sha256(os.urandom(32)).hexdigest()
                self._initialize()
            else:
                checkpoint_payload = _decode_checkpoint(checkpoint, checkpoint_key)
                self._store_id_sha256 = str(checkpoint_payload["store_id_sha256"])
                self._validate_checkpoint(checkpoint_payload)
                self.validate()
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        except Exception as error:
            self._close_resources()
            if isinstance(error, Mem0V5EvidenceStoreError):
                raise
            raise Mem0V5EvidenceStoreError("mem0_v5_evidence_store_corrupt") from None

    @classmethod
    def create(cls, *, path: Path, authentication_key: bytes) -> SQLiteMem0V5EvidenceStore:
        return cls(
            path=path,
            authentication_key=authentication_key,
            checkpoint=None,
            checkpoint_key=None,
            _token=_CREATE_TOKEN,
        )

    @classmethod
    def reopen(
        cls,
        *,
        path: Path,
        authentication_key: bytes,
        checkpoint: Mem0V5StoreCheckpoint,
        checkpoint_key: bytes,
    ) -> SQLiteMem0V5EvidenceStore:
        return cls(
            path=path,
            authentication_key=authentication_key,
            checkpoint=checkpoint,
            checkpoint_key=checkpoint_key,
            _token=_CREATE_TOKEN,
        )

    def close(self) -> None:
        with self._mutex:
            try:
                self._close_resources()
            except (OSError, sqlite3.Error):
                raise Mem0V5EvidenceStoreError("mem0_v5_evidence_store_corrupt") from None

    @_serialized
    def put_admission(
        self, admission: Mem0OssFullRunAdmission, *, units: tuple[Mem0OssManifestUnit, ...]
    ) -> str:
        if (
            type(admission) is not Mem0OssFullRunAdmission
            or type(units) is not tuple
            or len(units) != admission.ingestion_unit_count
            or any(type(unit) is not Mem0OssManifestUnit for unit in units)
            or manifest_root_sha256(units) != admission.ingestion_root_sha256
        ):
            self._fail_payload()
        operations = tuple(
            {
                "unit_index": index,
                "operation_id_sha256": _operation_id(admission, index, unit),
                **unit.payload(),
            }
            for index, unit in enumerate(units)
        )
        page_count = (len(operations) + _MANIFEST_PAGE_SIZE - 1) // _MANIFEST_PAGE_SIZE
        rows: list[_EvidenceRow] = [
            ("admission", admission.commitment_sha256, admission.public_payload())
        ]
        for page_index in range(page_count):
            start = page_index * _MANIFEST_PAGE_SIZE
            items = operations[start : start + _MANIFEST_PAGE_SIZE]
            page: dict[str, object] = {
                "admission_commitment_sha256": admission.commitment_sha256,
                "page_index": page_index,
                "page_count": page_count,
                "start_unit_index": start,
                "end_unit_index_exclusive": start + len(items),
                "operations": list(items),
            }
            rows.append(("manifest_page", canonical_sha256(page), page))
        with self._transaction():
            self._validate_incremental_head()
            hashes = self._append_rows(rows)
        self._admission_payload = admission.public_payload()
        self._admission_subject = admission.commitment_sha256
        self._manifest_operations = operations
        return hashes[0]

    @_serialized
    def put_receipt(self, *, unit_index: int, receipt: RuntimeReceiptVerificationResult) -> str:
        if type(receipt) is not RuntimeReceiptVerificationResult or not _index(unit_index):
            self._fail_payload()
        operation = self._manifest_operation(unit_index)
        _require_operation_binding(
            receipt,
            operation,
            self._admission_commitment(),
            self._admission_route_sha256(),
        )
        payload: dict[str, object] = {
            "unit_index": unit_index,
            "admission_commitment_sha256": receipt.admission_commitment_sha256,
            "operation_id_sha256": receipt.operation_id_sha256,
            "unit_identity_sha256": receipt.unit_identity_sha256,
            "unit_sha256": receipt.unit_sha256,
            "route_sha256": receipt.route_sha256,
            "scope_sha256": receipt.scope_sha256,
            "provider_receipt_sha256": receipt.provider_receipt_sha256,
            "disposition": receipt.disposition.value,
            "extraction_calls": receipt.extraction_calls,
            "retry_count": receipt.retry_count,
            "request_tokens": receipt.request_tokens,
            "response_tokens": receipt.response_tokens,
        }
        row_sha = self._append("receipt", receipt.operation_id_sha256, payload)
        self._receipts[receipt.operation_id_sha256] = payload
        return row_sha

    @_serialized
    def put_storage(self, *, unit_index: int, storage: StorageVerificationResult) -> str:
        if type(storage) is not StorageVerificationResult or not _index(unit_index):
            self._fail_payload()
        operation = self._manifest_operation(unit_index)
        _require_operation_binding(
            storage,
            operation,
            self._admission_commitment(),
            self._admission_route_sha256(),
        )
        receipt = self._receipts.get(storage.operation_id_sha256)
        if receipt is None or receipt["disposition"] != Mem0OssReceiptDisposition.COMPLETED.value:
            self._fail_order()
        for field in (
            "admission_commitment_sha256",
            "operation_id_sha256",
            "unit_identity_sha256",
            "unit_sha256",
            "route_sha256",
            "scope_sha256",
            "provider_receipt_sha256",
        ):
            if getattr(storage, field) != receipt[field]:
                self._fail_payload()
        payload: dict[str, object] = {
            "unit_index": unit_index,
            "admission_commitment_sha256": storage.admission_commitment_sha256,
            "operation_id_sha256": storage.operation_id_sha256,
            "unit_identity_sha256": storage.unit_identity_sha256,
            "unit_sha256": storage.unit_sha256,
            "route_sha256": storage.route_sha256,
            "scope_sha256": storage.scope_sha256,
            "provider_receipt_sha256": storage.provider_receipt_sha256,
            "stored_identity_sha256": storage.stored_identity_sha256,
            "stored_record_count": storage.stored_record_count,
        }
        row_sha = self._append("storage", storage.operation_id_sha256, payload)
        self._storage[storage.operation_id_sha256] = payload
        return row_sha

    @_serialized
    def put_seal(self, seal: Mem0OssRunSeal) -> str:
        if type(seal) is not Mem0OssRunSeal:
            self._fail_payload()
        self.validate()
        computed = self._computed_snapshot(require_complete=True)
        if seal.payload() != computed["seal_payload"]:
            self._fail_terminal()
        return self._append("seal", seal.commitment_sha256, seal.payload())

    @_serialized
    def put_cleanup(self, cleanup: Mem0OssTerminalCleanupEvidence) -> str:
        if type(cleanup) is not Mem0OssTerminalCleanupEvidence:
            self._fail_payload()
        self.validate()
        computed = self._computed_snapshot(require_complete=False)
        payload = cleanup.public_payload()
        seal = self._single_payload("seal")
        expected_failed = computed["failed_receipts"]
        if (
            payload["admission_commitment_sha256"] != self._admission_commitment()
            or payload["operation_inventory_root_sha256"] != computed["inventory_root_sha256"]
            or payload["provider_observed_extraction_calls"] != computed["extraction_calls"]
            or payload["provider_observed_request_tokens"] != computed["request_tokens"]
            or payload["provider_observed_response_tokens"] != computed["response_tokens"]
            or payload["failed_receipts"] != expected_failed
            or payload["residual_record_count"] != 0
            or payload["residual_root_sha256"] != MEM0_OSS_EMPTY_ROOT_SHA256
            or (seal is None and payload["seal_commitment_sha256"] is not None)
            or (seal is None and payload["operation_root_sha256"] is not None)
            or (seal is None and payload["terminal_state"] != "aborted")
            or (seal is None and payload["deleted_operation_count"] > computed["operation_count"])
            or (seal is not None and payload["terminal_state"] != "deleted")
            or (
                seal is not None
                and (
                    payload["seal_commitment_sha256"] != canonical_sha256(seal)
                    or payload["operation_root_sha256"] != seal["operation_root_sha256"]
                    or payload["deleted_operation_count"] != seal["operation_count"]
                )
            )
        ):
            self._fail_terminal()
        return self._append("cleanup", cleanup.commitment_sha256, payload)

    @_serialized
    def issue_checkpoint(self, *, checkpoint_key: bytes) -> Mem0V5StoreCheckpoint:
        if not _valid_key(checkpoint_key):
            raise Mem0V5EvidenceStoreError("mem0_v5_evidence_store_configuration_invalid")
        with self._guard():
            self.validate()
            meta = self._meta()
            payload: dict[str, object] = {
                "schema_version": _CHECKPOINT_SCHEMA_VERSION,
                "store_id_sha256": self._store_id_sha256,
                "row_count": int(meta["row_count"]),
                "head_sha256": meta["head_sha256"],
            }
            encoded = base64.urlsafe_b64encode(_canonical_json(payload).encode()).decode()
            return Mem0V5StoreCheckpoint(
                token=encoded + "." + _mac(checkpoint_key, "checkpoint", encoded)
            )

    def validate(self) -> str:
        with self._guard():
            connection = self._require_connection()
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                self._fail_corrupt()
            if _schema_fingerprint(connection) != _expected_schema_fingerprint():
                self._fail_corrupt()
            meta = self._meta()
            if (
                set(meta)
                != {
                    "schema_version",
                    "store_id_sha256",
                    "row_count",
                    "head_sha256",
                    "head_mac_sha256",
                }
                or meta["schema_version"] != _STORE_SCHEMA_VERSION
            ):
                self._fail_corrupt()
            if meta["store_id_sha256"] != self._store_id_sha256:
                self._fail_corrupt()
            count = int(meta["row_count"])
            previous = MEM0_OSS_EMPTY_ROOT_SHA256
            rows = list(connection.execute("SELECT * FROM evidence ORDER BY sequence"))
            if count != len(rows) or not 0 <= count <= _MAX_ROWS:
                self._fail_corrupt()
            for sequence, row in enumerate(rows, 1):
                if row["sequence"] != sequence or row["predecessor_sha256"] != previous:
                    self._fail_corrupt()
                expected = canonical_sha256(_row_commitment_payload(row))
                if expected != row["row_sha256"] or not hmac.compare_digest(
                    row["row_mac_sha256"], _mac(self._key, "row", expected)
                ):
                    self._fail_corrupt()
                _parse_payload(row["payload_json"])
                previous = expected
            if previous != meta["head_sha256"] or not hmac.compare_digest(
                meta["head_mac_sha256"], self._head_mac(count, previous)
            ):
                self._fail_corrupt()
            self._validate_semantics()
            return previous

    def iter_public_evidence(self) -> Iterator[Mapping[str, object]]:
        with self._guard():
            self.validate()
            rows = list(
                self._require_connection().execute(
                    "SELECT sequence, kind, subject_sha256, payload_json, row_sha256 "
                    "FROM evidence ORDER BY sequence"
                )
            )
        for row in rows:
            yield {
                "sequence": row["sequence"],
                "kind": row["kind"],
                "subject_sha256": row["subject_sha256"],
                "payload": _parse_payload(row["payload_json"]),
                "row_sha256": row["row_sha256"],
            }

    def _computed_snapshot(self, *, require_complete: bool) -> dict[str, object]:
        admission = self._admission_payload
        if admission is None:
            self._fail_order()
        commitments: list[str] = []
        inventory: list[dict[str, object]] = []
        failed: list[dict[str, object]] = []
        usage = {"extraction_calls": 0, "request_tokens": 0, "response_tokens": 0}
        for operation in self._manifest_operations:
            operation_id = operation["operation_id_sha256"]
            receipt = self._receipts.get(operation_id)
            storage = self._storage.get(operation_id)
            base = {
                "operation_id_sha256": operation_id,
                "unit_index": operation["unit_index"],
                "unit_identity_sha256": operation["unit_identity_sha256"],
                "unit_sha256": operation["unit_sha256"],
                "scope_sha256": operation["scope_sha256"],
                "provider_receipt_sha256": receipt["provider_receipt_sha256"] if receipt else None,
                "disposition": receipt["disposition"] if receipt else None,
                "extraction_calls": receipt["extraction_calls"] if receipt else 0,
                "retry_count": receipt["retry_count"] if receipt else 0,
                "request_tokens": receipt["request_tokens"] if receipt else 0,
                "response_tokens": receipt["response_tokens"] if receipt else 0,
                "stored_identity_sha256": storage["stored_identity_sha256"] if storage else None,
                "stored_record_count": storage["stored_record_count"] if storage else 0,
            }
            if receipt:
                for field in usage:
                    usage[field] += receipt[field]
            if receipt and receipt["disposition"] != Mem0OssReceiptDisposition.COMPLETED.value:
                if storage is not None:
                    self._fail_corrupt()
                state = Mem0OssOperationState.FAILED.value
                commitment = None
                failed.append(
                    Mem0OssFailedReceiptEvidence(
                        operation_id_sha256=operation_id,
                        unit_index=operation["unit_index"],
                        disposition=receipt["disposition"],
                        provider_receipt_sha256=receipt["provider_receipt_sha256"],
                        extraction_calls=receipt["extraction_calls"],
                        request_tokens=receipt["request_tokens"],
                        response_tokens=receipt["response_tokens"],
                    ).public_payload()
                )
            elif receipt and storage:
                state = Mem0OssOperationState.COMMITTED.value
                commitment = canonical_sha256(base)
                commitments.append(commitment)
            elif receipt:
                state = Mem0OssOperationState.RECEIPT_VERIFIED.value
                commitment = None
            else:
                state = Mem0OssOperationState.RESERVED.value
                commitment = None
            inventory.append({**base, "state": state, "commitment_sha256": commitment})
        complete = len(commitments) == len(inventory)
        if require_complete and not complete:
            self._fail_terminal()
        operation_root = canonical_sha256({"operation_commitments": commitments})
        return {
            **usage,
            "failed_receipts": failed,
            "operation_count": len(inventory),
            "inventory_root_sha256": canonical_sha256({"operations": inventory}),
            "seal_payload": {
                "admission_commitment_sha256": self._admission_commitment(),
                "operation_count": len(inventory),
                "ingestion_root_sha256": admission["ingestion_root_sha256"],
                "operation_root_sha256": operation_root,
                "provider_observed_extraction_calls": usage["extraction_calls"],
                "provider_observed_request_tokens": usage["request_tokens"],
                "provider_observed_response_tokens": usage["response_tokens"],
            },
        }

    def _validate_semantics(self) -> None:
        kinds = [
            row[0]
            for row in self._require_connection().execute(
                "SELECT kind FROM evidence ORDER BY sequence"
            )
        ]
        if kinds and kinds[0] != "admission":
            self._fail_order()
        manifest_page_count = kinds.count("manifest_page")
        if kinds[1 : 1 + manifest_page_count] != ["manifest_page"] * manifest_page_count:
            self._fail_order()
        if any(kinds.count(kind) > 1 for kind in ("admission", "seal", "cleanup")):
            self._fail_order()
        if "cleanup" in kinds and kinds[-1] != "cleanup":
            self._fail_order()
        if "seal" in kinds and any(
            kind in {"receipt", "storage"} for kind in kinds[kinds.index("seal") + 1 :]
        ):
            self._fail_order()
        if "admission" not in kinds:
            return
        admission = self._single_payload("admission")
        admission_row = (
            self._require_connection()
            .execute("SELECT subject_sha256 FROM evidence WHERE kind='admission'")
            .fetchone()
        )
        if admission is None or admission_row is None:
            self._fail_corrupt()
        self._admission_payload = admission
        self._admission_subject = admission_row[0]
        page_rows = self._require_connection().execute(
            "SELECT subject_sha256, payload_json FROM evidence "
            "WHERE kind='manifest_page' ORDER BY sequence"
        )
        pages = []
        for subject_sha256, payload_json in page_rows:
            page = _parse_payload(payload_json)
            if subject_sha256 != canonical_sha256(page):
                self._fail_corrupt()
            pages.append(page)
        operations: list[dict[str, object]] = []
        for page_index, page in enumerate(pages):
            items = page.get("operations")
            if (
                type(items) is not list
                or not 1 <= len(items) <= _MANIFEST_PAGE_SIZE
                or page.get("admission_commitment_sha256") != self._admission_commitment()
                or page.get("page_index") != page_index
                or page.get("page_count") != len(pages)
                or page.get("start_unit_index") != len(operations)
                or page.get("end_unit_index_exclusive") != len(operations) + len(items)
            ):
                self._fail_corrupt()
            operations.extend(items)
        if len(operations) != admission["expected_operation_count"]:
            self._fail_corrupt()
        units: list[Mem0OssManifestUnit] = []
        for index, operation in enumerate(operations):
            if type(operation) is not dict or operation.get("unit_index") != index:
                self._fail_corrupt()
            unit = Mem0OssManifestUnit(
                unit_identity_sha256=operation["unit_identity_sha256"],
                unit_sha256=operation["unit_sha256"],
                scope_sha256=operation["scope_sha256"],
            )
            if operation["operation_id_sha256"] != _operation_id_from_payload(
                self._admission_commitment(), index, unit
            ):
                self._fail_corrupt()
            units.append(unit)
        if manifest_root_sha256(tuple(units)) != admission["ingestion_root_sha256"]:
            self._fail_corrupt()
        self._manifest_operations = tuple(operations)
        self._receipts = self._load_kind_map("receipt")
        self._storage = self._load_kind_map("storage")
        operation_ids = {item["operation_id_sha256"] for item in self._manifest_operations}
        if not set(self._receipts) <= operation_ids or not set(self._storage) <= operation_ids:
            self._fail_corrupt()
        for operation in self._manifest_operations:
            operation_id = operation["operation_id_sha256"]
            receipt = self._receipts.get(operation_id)
            storage = self._storage.get(operation_id)
            if receipt is not None:
                _require_operation_binding(
                    SimpleNamespace(**receipt),
                    operation,
                    self._admission_commitment(),
                    self._admission_route_sha256(),
                )
            if storage is not None:
                _require_operation_binding(
                    SimpleNamespace(**storage),
                    operation,
                    self._admission_commitment(),
                    self._admission_route_sha256(),
                )
                if receipt is None or any(
                    storage[field] != receipt[field]
                    for field in (
                        "provider_receipt_sha256",
                        "unit_sha256",
                        "scope_sha256",
                    )
                ):
                    self._fail_corrupt()
        computed = self._computed_snapshot(require_complete="seal" in kinds)
        seal = self._single_payload("seal")
        if seal is not None and seal != computed["seal_payload"]:
            self._fail_corrupt()

    def _initialize(self) -> None:
        connection = self._require_connection()
        with self._transaction():
            for statement in _SCHEMA:
                connection.execute(statement)
            head = MEM0_OSS_EMPTY_ROOT_SHA256
            connection.executemany(
                "INSERT INTO store_meta VALUES (?, ?)",
                (
                    ("schema_version", _STORE_SCHEMA_VERSION),
                    ("store_id_sha256", self._store_id_sha256),
                    ("row_count", "0"),
                    ("head_sha256", head),
                    ("head_mac_sha256", self._head_mac(0, head)),
                ),
            )

    def _append(self, kind: str, subject: str, payload: Mapping[str, object]) -> str:
        with self._guard(), self._transaction():
            self._validate_incremental_head()
            return self._append_rows(((kind, subject, payload),))[0]

    def _append_rows(self, rows: tuple[_EvidenceRow, ...] | list[_EvidenceRow]) -> tuple[str, ...]:
        if self._require_connection().execute(_TERMINAL_QUERY).fetchone():
            self._fail_terminal()
        meta = self._meta()
        sequence = int(meta["row_count"])
        if rows[0][0] == "admission" and sequence != 0:
            self._fail_order()
        previous = meta["head_sha256"]
        hashes: list[str] = []
        for kind, subject, payload in rows:
            if kind not in {
                "admission",
                "manifest_page",
                "receipt",
                "storage",
                "seal",
                "cleanup",
            } or not is_sha256(subject):
                self._fail_payload()
            payload_json = _canonical_json(payload)
            if len(payload_json.encode()) > _MAX_PAYLOAD_BYTES:
                self._fail_payload()
            sequence += 1
            if sequence > _MAX_ROWS:
                self._fail_payload()
            row_payload = {
                "sequence": sequence,
                "kind": kind,
                "subject_sha256": subject,
                "payload_json": payload_json,
                "predecessor_sha256": previous,
            }
            row_sha = canonical_sha256(row_payload)
            try:
                self._require_connection().execute(
                    "INSERT INTO evidence VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        sequence,
                        kind,
                        subject,
                        payload_json,
                        previous,
                        row_sha,
                        _mac(self._key, "row", row_sha),
                    ),
                )
            except sqlite3.IntegrityError:
                raise Mem0V5EvidenceStoreError("mem0_v5_evidence_store_duplicate") from None
            hashes.append(row_sha)
            previous = row_sha
        self._require_connection().executemany(
            "UPDATE store_meta SET value = ? WHERE key = ?",
            (
                (str(sequence), "row_count"),
                (previous, "head_sha256"),
                (self._head_mac(sequence, previous), "head_mac_sha256"),
            ),
        )
        return tuple(hashes)

    def _validate_incremental_head(self) -> None:
        meta = self._meta()
        try:
            row_count = int(meta.get("row_count", ""))
        except ValueError:
            self._fail_corrupt()
        if (
            set(meta)
            != {
                "schema_version",
                "store_id_sha256",
                "row_count",
                "head_sha256",
                "head_mac_sha256",
            }
            or meta["schema_version"] != _STORE_SCHEMA_VERSION
            or meta["store_id_sha256"] != self._store_id_sha256
            or not hmac.compare_digest(
                meta["head_mac_sha256"],
                self._head_mac(row_count, meta["head_sha256"]),
            )
        ):
            self._fail_corrupt()

    def _validate_checkpoint(self, checkpoint: Mapping[str, object]) -> None:
        meta = self._meta()
        if (
            meta.get("store_id_sha256") != checkpoint["store_id_sha256"]
            or int(meta.get("row_count", "-1")) != checkpoint["row_count"]
            or meta.get("head_sha256") != checkpoint["head_sha256"]
        ):
            self._fail_corrupt()

    def _manifest_operation(self, unit_index: int) -> dict[str, object]:
        if unit_index >= len(self._manifest_operations):
            self._fail_order()
        return self._manifest_operations[unit_index]

    def _admission_commitment(self) -> str:
        if self._admission_subject is None:
            self._fail_order()
        return self._admission_subject

    def _admission_route_sha256(self) -> str:
        admission = self._admission_payload
        if admission is None or not is_sha256(admission.get("route_sha256")):
            self._fail_order()
        return admission["route_sha256"]

    def _load_kind_map(self, kind: str) -> dict[str, dict[str, object]]:
        return {
            row[0]: _parse_payload(row[1])
            for row in self._require_connection().execute(
                "SELECT subject_sha256, payload_json FROM evidence WHERE kind=?",
                (kind,),
            )
        }

    def _single_payload(self, kind: str) -> dict[str, object] | None:
        row = (
            self._require_connection()
            .execute("SELECT payload_json FROM evidence WHERE kind=?", (kind,))
            .fetchone()
        )
        return _parse_payload(row[0]) if row is not None else None

    def _meta(self) -> dict[str, str]:
        return dict(self._require_connection().execute("SELECT key, value FROM store_meta"))

    def _head_mac(self, count: int, head: str) -> str:
        return _mac(self._key, "head", f"{self._store_id_sha256}:{count}:{head}")

    @contextmanager
    def _guard(self) -> Iterator[None]:
        with self._mutex:
            try:
                yield
            except Mem0V5EvidenceStoreError:
                raise
            except sqlite3.Error:
                raise Mem0V5EvidenceStoreError("mem0_v5_evidence_store_corrupt") from None

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        connection = self._require_connection()
        connection.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        else:
            connection.execute("COMMIT")

    def _require_connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise Mem0V5EvidenceStoreError("mem0_v5_evidence_store_corrupt")
        return self._connection

    def _close_resources(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None
        if self._lock_file is not None:
            fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_UN)
            self._lock_file.close()
            self._lock_file = None

    @staticmethod
    def _fail_payload() -> None:
        raise Mem0V5EvidenceStoreError("mem0_v5_evidence_store_payload_invalid")

    @staticmethod
    def _fail_corrupt() -> None:
        raise Mem0V5EvidenceStoreError("mem0_v5_evidence_store_corrupt")

    @staticmethod
    def _fail_order() -> None:
        raise Mem0V5EvidenceStoreError("mem0_v5_evidence_store_order_invalid")

    @staticmethod
    def _fail_terminal() -> None:
        raise Mem0V5EvidenceStoreError("mem0_v5_evidence_store_terminal_invalid")


def _operation_id(
    admission: Mem0OssFullRunAdmission, unit_index: int, unit: Mem0OssManifestUnit
) -> str:
    return _operation_id_from_payload(admission.commitment_sha256, unit_index, unit)


def _operation_id_from_payload(
    admission_commitment_sha256: str, unit_index: int, unit: Mem0OssManifestUnit
) -> str:
    return canonical_sha256(
        {
            "admission_commitment_sha256": admission_commitment_sha256,
            "unit_index": unit_index,
            "unit_identity_sha256": unit.unit_identity_sha256,
        }
    )


def _require_operation_binding(
    evidence: object,
    operation: Mapping[str, object],
    admission_commitment: str,
    route_sha256: str,
) -> None:
    expected = {
        "admission_commitment_sha256": admission_commitment,
        "operation_id_sha256": operation["operation_id_sha256"],
        "unit_identity_sha256": operation["unit_identity_sha256"],
        "unit_sha256": operation["unit_sha256"],
        "scope_sha256": operation["scope_sha256"],
        "route_sha256": route_sha256,
    }
    if any(getattr(evidence, field, None) != value for field, value in expected.items()):
        raise Mem0V5EvidenceStoreError("mem0_v5_evidence_store_payload_invalid")


def _valid_key(value: object) -> bool:
    return type(value) is bytes and 32 <= len(value) <= 128


def _index(value: object) -> bool:
    return type(value) is int and 0 <= value <= 10_000


def _mac(key: bytes, domain: str, value: str) -> str:
    return hmac.new(key, f"{domain}:{value}".encode(), hashlib.sha256).hexdigest()


def _decode_checkpoint(
    checkpoint: Mem0V5StoreCheckpoint, checkpoint_key: bytes | None
) -> dict[str, object]:
    if checkpoint_key is None:
        raise Mem0V5EvidenceStoreError("mem0_v5_evidence_store_corrupt")
    try:
        encoded, provided_mac = checkpoint.token.split(".", 1)
        if not hmac.compare_digest(provided_mac, _mac(checkpoint_key, "checkpoint", encoded)):
            raise ValueError
        decoded = base64.b64decode(encoded, altchars=b"-_", validate=True).decode()
        payload = json.loads(decoded)
        if (
            type(payload) is not dict
            or set(payload) != {"schema_version", "store_id_sha256", "row_count", "head_sha256"}
            or payload["schema_version"] != _CHECKPOINT_SCHEMA_VERSION
            or not is_sha256(payload["store_id_sha256"])
            or type(payload["row_count"]) is not int
            or not 0 <= payload["row_count"] <= _MAX_ROWS
            or not is_sha256(payload["head_sha256"])
            or _canonical_json(payload) != decoded
        ):
            raise ValueError
        return payload
    except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        raise Mem0V5EvidenceStoreError("mem0_v5_evidence_store_corrupt") from None


def _canonical_json(value: Mapping[str, object]) -> str:
    try:
        return json.dumps(
            value, allow_nan=False, ensure_ascii=True, separators=(",", ":"), sort_keys=True
        )
    except (TypeError, ValueError):
        raise Mem0V5EvidenceStoreError("mem0_v5_evidence_store_payload_invalid") from None


def _parse_payload(value: str) -> dict[str, object]:
    parsed = json.loads(value)
    if type(parsed) is not dict or _canonical_json(parsed) != value:
        raise Mem0V5EvidenceStoreError("mem0_v5_evidence_store_corrupt")
    return parsed


def _row_commitment_payload(row: sqlite3.Row) -> dict[str, object]:
    return {
        "sequence": row["sequence"],
        "kind": row["kind"],
        "subject_sha256": row["subject_sha256"],
        "payload_json": row["payload_json"],
        "predecessor_sha256": row["predecessor_sha256"],
    }


def _schema_fingerprint(connection: sqlite3.Connection) -> tuple[tuple[object, ...], ...]:
    return tuple(
        tuple(row)
        for row in connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        )
    )


@cache
def _expected_schema_fingerprint() -> tuple[tuple[object, ...], ...]:
    connection = sqlite3.connect(":memory:")
    try:
        for statement in _SCHEMA:
            connection.execute(statement)
        return _schema_fingerprint(connection)
    finally:
        connection.close()


__all__ = (
    "Mem0V5EvidenceStoreError",
    "Mem0V5EvidenceStorePort",
    "Mem0V5StoreCheckpoint",
    "SQLiteMem0V5EvidenceStore",
)

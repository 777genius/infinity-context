"""Durable hash-only authority for official LongMemEval original pair slots."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, final

from infinity_context_core.ports.benchmark_managed_ingest import (
    managed_benchmark_text_sha256,
)
from infinity_context_core.ports.managed_cleanup_v3_contracts import (
    LONGMEMEVAL_PROFILE,
    PROFILE_ORACLES,
    canonical_bytes,
    commitment,
    merkle_root,
)
from infinity_context_core.ports.original_pair_identity_authority import (
    LONGMEMEVAL_OMITTED_ORIGINAL_PAIR_IDENTITY_ROOT_SHA256,
)

from infinity_context_server.longmemeval_session_identity import (
    build_longmemeval_session_identity,
)
from infinity_context_server.memory_comparison_longmemeval_cases import (
    _chronology_key,
    _normalize_session,
    official_longmemeval_pair_case,
)
from infinity_context_server.memory_comparison_managed_corpus_projection import (
    _managed_corpus_identity,
)
from infinity_context_server.original_pair_identity_authority_files import (
    OriginalPairIdentityAuthorityError,
    create_secure_sqlite,
    discard_secure_file,
    open_secure_sqlite,
    publish_secure_sqlite,
    recover_secure_sqlite_publish,
    unlink_bound,
    verify_bound,
)

_SCHEMA: Final = "longmemeval-original-pair-identity-authority.v1"
_MAC_DOMAIN: Final = b"longmemeval-original-pair-identity-authority/v1\0"
_ROW_KEY_DOMAIN: Final = b"longmemeval-original-pair-row-key/v1\0"
_ROW_MAC_DOMAIN: Final = b"longmemeval-original-pair-row/v1\0"
_PAGE_SIZE: Final = 512
_SHA = frozenset("0123456789abcdef")


@dataclass(frozen=True, slots=True)
class _AuthorityPolicy:
    profile_id: str
    dataset_sha256: str
    operation_count: int
    original_pair_slot_count: int
    omitted_source_identity_count: int
    omitted_source_identity_root_sha256: str
    omitted_original_pair_identity_root_sha256: str


_ORACLE = PROFILE_ORACLES[LONGMEMEVAL_PROFILE]
_OFFICIAL_POLICY = _AuthorityPolicy(
    profile_id=LONGMEMEVAL_PROFILE,
    dataset_sha256=str(_ORACLE["dataset_sha256"]),
    operation_count=int(_ORACLE["operation_count"]),
    original_pair_slot_count=int(_ORACLE["original_pair_slot_count"]),
    omitted_source_identity_count=int(_ORACLE["omitted_source_identity_count"]),
    omitted_source_identity_root_sha256=str(_ORACLE["omitted_source_identity_root_sha256"]),
    omitted_original_pair_identity_root_sha256=(
        LONGMEMEVAL_OMITTED_ORIGINAL_PAIR_IDENTITY_ROOT_SHA256
    ),
)


@final
class SQLiteOriginalPairIdentityAuthority:
    """Authenticated SQLite mapping derived before invalid pair slots are omitted."""

    def __init__(
        self,
        db: sqlite3.Connection,
        metadata: Mapping[str, object],
        target: Path,
        descriptor: int,
        row_authentication_key: bytes,
    ) -> None:
        self._db = db
        self._metadata = dict(metadata)
        self._target = target
        self._descriptor: int | None = descriptor
        self._row_authentication_key = row_authentication_key

    @classmethod
    def create(
        cls,
        path: str | os.PathLike[str],
        *,
        dataset_bytes: bytes,
        authentication_key: bytes,
    ) -> SQLiteOriginalPairIdentityAuthority:
        return cls._create(path, dataset_bytes, authentication_key, _OFFICIAL_POLICY)

    @classmethod
    def create_or_open(
        cls,
        path: str | os.PathLike[str],
        *,
        dataset_bytes: bytes,
        authentication_key: bytes,
    ) -> SQLiteOriginalPairIdentityAuthority:
        """Create once or authenticate the exact official authority on replay."""

        return cls._create_or_open(path, dataset_bytes, authentication_key, _OFFICIAL_POLICY)

    @classmethod
    def _create_or_open(
        cls,
        path: str | os.PathLike[str],
        dataset_bytes: bytes,
        authentication_key: bytes,
        policy: _AuthorityPolicy,
    ) -> SQLiteOriginalPairIdentityAuthority:
        _key(authentication_key)
        _validate_dataset_bytes(dataset_bytes, policy)
        target = Path(path)
        staging = _staging_path(target)
        if _path_present(target):
            recover_secure_sqlite_publish(staging, target)
            return cls._open(target, authentication_key, policy)

        if _path_present(staging):
            try:
                staged = cls._open(staging, authentication_key, policy)
            except Exception:
                _discard_crash_partial(staging)
            else:
                staged.close()
        if not _path_present(staging):
            staged = cls._create(staging, dataset_bytes, authentication_key, policy)
            staged.close()
        try:
            publish_secure_sqlite(staging, target)
        except FileExistsError:
            existing = cls._open(target, authentication_key, policy)
            try:
                _discard_crash_partial(staging)
            except BaseException:
                existing.close()
                raise
            return existing
        return cls._open(target, authentication_key, policy)

    @classmethod
    def _create(
        cls,
        path: str | os.PathLike[str],
        dataset_bytes: bytes,
        authentication_key: bytes,
        policy: _AuthorityPolicy,
    ) -> SQLiteOriginalPairIdentityAuthority:
        key = _key(authentication_key)
        dataset_sha = _validate_dataset_bytes(dataset_bytes, policy)
        target = Path(path)
        db, descriptor = create_secure_sqlite(target)
        try:
            _configure(db)
            _schema(db)
            _ingest(db, dataset_bytes=dataset_bytes, dataset_sha256=dataset_sha)
            metadata = _metadata(db, policy)
            row_key = _row_key(key)
            _authenticate_mapping_rows(db, key=row_key, metadata=metadata)
            tag = hmac.new(key, _MAC_DOMAIN + canonical_bytes(metadata), hashlib.sha256).hexdigest()
            db.execute(
                "INSERT INTO authority_metadata(singleton,payload_json,authentication_tag) "
                "VALUES(1,?,?)",
                (canonical_bytes(metadata).decode("ascii"), tag),
            )
            db.commit()
            db.execute("PRAGMA query_only=ON")
            verify_bound(target, descriptor)
            return cls(db, metadata, target, descriptor, row_key)
        except BaseException:
            db.close()
            unlink_bound(target, descriptor)
            os.close(descriptor)
            raise

    @classmethod
    def open(
        cls,
        path: str | os.PathLike[str],
        *,
        authentication_key: bytes,
    ) -> SQLiteOriginalPairIdentityAuthority:
        return cls._open(path, authentication_key, _OFFICIAL_POLICY)

    @classmethod
    def _open(
        cls,
        path: str | os.PathLike[str],
        authentication_key: bytes,
        policy: _AuthorityPolicy,
    ) -> SQLiteOriginalPairIdentityAuthority:
        key = _key(authentication_key)
        target = Path(path)
        try:
            db, descriptor = open_secure_sqlite(target)
        except OriginalPairIdentityAuthorityError:
            raise
        except (OSError, sqlite3.Error) as exc:
            raise OriginalPairIdentityAuthorityError("original_pair_store_missing") from exc
        try:
            _configure(db, readonly=True)
            row = db.execute(
                "SELECT payload_json,authentication_tag FROM authority_metadata WHERE singleton=1"
            ).fetchone()
            if row is None:
                _fail("authentication_invalid")
            metadata = json.loads(row[0])
            if type(metadata) is not dict:
                _fail("authentication_invalid")
            expected = _metadata(db, policy)
            if canonical_bytes(metadata) != canonical_bytes(expected) or not hmac.compare_digest(
                str(row[1]),
                hmac.new(key, _MAC_DOMAIN + canonical_bytes(expected), hashlib.sha256).hexdigest(),
            ):
                _fail("authentication_invalid")
            row_key = _row_key(key)
            _verify_mapping_row_authentication(db, key=row_key, metadata=expected)
            verify_bound(target, descriptor)
        except BaseException:
            db.close()
            os.close(descriptor)
            raise
        db.execute("PRAGMA query_only=ON")
        return cls(db, metadata, target, descriptor, row_key)

    def close(self) -> None:
        descriptor = self._descriptor
        if descriptor is None:
            return
        self._descriptor = None
        binding_error: BaseException | None = None
        try:
            try:
                verify_bound(self._target, descriptor)
            except BaseException as exc:
                binding_error = exc
            self._db.close()
            try:
                verify_bound(self._target, descriptor)
            except BaseException as exc:
                binding_error = binding_error or exc
        finally:
            os.close(descriptor)
        if binding_error is not None:
            raise binding_error

    def _metadata_value(self, name: str, expected_type: type[str] | type[int]) -> str | int:
        descriptor = self._descriptor
        if descriptor is None:
            _fail("store_closed")
        verify_bound(self._target, descriptor)
        value = self._metadata[name]
        verify_bound(self._target, descriptor)
        if type(value) is not expected_type:
            _fail("authentication_invalid")
        return value

    @property
    def profile_id(self) -> str:
        return self._metadata_value("profile_id", str)  # type: ignore[return-value]

    @property
    def dataset_sha256(self) -> str:
        return self._metadata_value("dataset_sha256", str)  # type: ignore[return-value]

    @property
    def operation_count(self) -> int:
        return self._metadata_value("operation_count", int)  # type: ignore[return-value]

    @property
    def original_pair_slot_count(self) -> int:
        return self._metadata_value("original_pair_slot_count", int)  # type: ignore[return-value]

    @property
    def omitted_source_identity_count(self) -> int:
        return self._metadata_value("omitted_source_identity_count", int)  # type: ignore[return-value]

    @property
    def omitted_source_identity_root_sha256(self) -> str:
        return self._metadata_value(  # type: ignore[return-value]
            "omitted_source_identity_root_sha256", str
        )

    @property
    def omitted_original_pair_identity_root_sha256(self) -> str:
        return self._metadata_value(  # type: ignore[return-value]
            "omitted_original_pair_identity_root_sha256", str
        )

    @property
    def original_pair_slot_root_sha256(self) -> str:
        return self._metadata_value(  # type: ignore[return-value]
            "original_pair_slot_root_sha256", str
        )

    @property
    def ordered_mapping_root_sha256(self) -> str:
        return self._metadata_value(  # type: ignore[return-value]
            "ordered_mapping_root_sha256", str
        )

    @property
    def terminal_commitment_sha256(self) -> str:
        return self._metadata_value(  # type: ignore[return-value]
            "terminal_commitment_sha256", str
        )

    def lookup(
        self,
        *,
        sequence: int,
        corpus_id: str,
        normalized_source_id: str,
    ) -> str | None:
        if (
            type(sequence) is not int
            or sequence < 0
            or type(corpus_id) is not str
            or not corpus_id
            or type(normalized_source_id) is not str
            or not normalized_source_id
        ):
            _fail("lookup_invalid")
        descriptor = self._descriptor
        if descriptor is None:
            _fail("store_closed")
        verify_bound(self._target, descriptor)
        corpus_sha = managed_benchmark_text_sha256(corpus_id)
        source_sha = managed_benchmark_text_sha256(normalized_source_id)
        try:
            row = self._db.execute(
                "SELECT sequence,corpus_id_sha256,normalized_source_id_sha256,"
                "original_pair_identity_sha256,mapping_identity_sha256,authentication_tag "
                "FROM admitted_mapping "
                "WHERE sequence=? AND corpus_id_sha256=? AND normalized_source_id_sha256=?",
                (sequence, corpus_sha, source_sha),
            ).fetchone()
        except sqlite3.Error as exc:
            raise OriginalPairIdentityAuthorityError(
                "original_pair_lookup_content_invalid"
            ) from exc
        verify_bound(self._target, descriptor)
        if row is None:
            return None
        payload = _mapping_row_payload(row)
        if (
            payload["sequence"] != sequence
            or payload["corpus_id_sha256"] != corpus_sha
            or payload["normalized_source_id_sha256"] != source_sha
        ):
            _fail("lookup_content_invalid")
        observed_tag = row[5]
        expected_tag = _mapping_row_tag(
            key=self._row_authentication_key,
            metadata=self._metadata,
            payload=payload,
        )
        if type(observed_tag) is not str or not hmac.compare_digest(observed_tag, expected_tag):
            _fail("lookup_authentication_invalid")
        pair_identity = payload["original_pair_identity_sha256"]
        if type(pair_identity) is not str:
            _fail("lookup_content_invalid")
        return pair_identity


def _ingest(db: sqlite3.Connection, *, dataset_bytes: bytes, dataset_sha256: str) -> None:
    slot_sequence = admitted_sequence = case_index = 0
    with db:
        for raw in _json_array_items(dataset_bytes):
            case = official_longmemeval_pair_case(raw)
            managed_corpus_id, admitted = _admitted_sources(case)
            sessions = raw.get("haystack_sessions")
            if not isinstance(sessions, Sequence) or isinstance(sessions, str | bytes):
                _fail("dataset_invalid")
            identity = build_longmemeval_session_identity(
                raw.get("haystack_session_ids"), session_count=len(sessions)
            )
            normalized_sessions = sorted(
                (
                    session
                    for index, value in enumerate(sessions)
                    if (
                        session := _normalize_session(
                            raw,
                            value,
                            original_index=index,
                            session_identity=identity,
                        )
                    )
                    is not None
                ),
                key=_chronology_key,
            )
            case_identity = commitment(
                "original-case-identity/v1",
                {
                    "dataset_sha256": dataset_sha256,
                    "case_index": case_index,
                    "case_id": case.case_id,
                    "raw_case_sha256": hashlib.sha256(canonical_bytes(raw)).hexdigest(),
                },
            )
            for session in normalized_sessions:
                session_identity = commitment(
                    "original-session-identity/v1",
                    {
                        "case_identity_sha256": case_identity,
                        "original_index": session.original_index,
                        "raw_session_id": _sequence_item(
                            raw.get("haystack_session_ids"), session.original_index
                        ),
                        "raw_date": _sequence_item(
                            raw.get("haystack_dates"), session.original_index
                        ),
                    },
                )
                for offset in range(0, len(session.messages), 2):
                    pair_index = offset // 2
                    raw_pair = list(session.messages[offset : offset + 2])
                    pair_identity = commitment(
                        "original-pair-identity/v1",
                        {
                            "case_identity_sha256": case_identity,
                            "session_identity_sha256": session_identity,
                            "pair_index": pair_index,
                            "raw_pair_sha256": hashlib.sha256(
                                canonical_bytes(raw_pair)
                            ).hexdigest(),
                        },
                    )
                    source_id = admitted.pop((session.original_index, pair_index), None)
                    mapped_sequence: int | None = None
                    if source_id is not None:
                        mapped_sequence = admitted_sequence
                        corpus_sha = managed_benchmark_text_sha256(managed_corpus_id)
                        source_sha = managed_benchmark_text_sha256(source_id)
                        mapping_identity = commitment(
                            "original-pair-mapping/v1",
                            {
                                "sequence": admitted_sequence,
                                "corpus_id_sha256": corpus_sha,
                                "normalized_source_id_sha256": source_sha,
                                "original_pair_identity_sha256": pair_identity,
                            },
                        )
                        db.execute(
                            "INSERT INTO admitted_mapping VALUES(?,?,?,?,?,?)",
                            (
                                admitted_sequence,
                                corpus_sha,
                                source_sha,
                                pair_identity,
                                mapping_identity,
                                "",
                            ),
                        )
                        admitted_sequence += 1
                    db.execute(
                        "INSERT INTO original_slots VALUES(?,?,?)",
                        (slot_sequence, pair_identity, mapped_sequence),
                    )
                    slot_sequence += 1
            if admitted:
                _fail("normalized_mapping_incomplete")
            case_index += 1


def _admitted_sources(case: object) -> tuple[str, dict[tuple[int, int], str]]:
    conversations = getattr(case, "conversations", None)
    if type(conversations) is not tuple:
        _fail("normalized_mapping_invalid")
    managed_corpus_id = _managed_corpus_identity(case)[0]  # type: ignore[arg-type]
    result: dict[tuple[int, int], str] = {}
    for ordinal, conversation in enumerate(conversations, start=1):
        metadata = getattr(conversation, "metadata", None)
        if (
            not isinstance(metadata, Mapping)
            or type(metadata.get("session_original_index")) is not int
            or type(metadata.get("pair_index")) is not int
        ):
            _fail("normalized_mapping_invalid")
        key = (int(metadata["session_original_index"]), int(metadata["pair_index"]))
        if key in result:
            _fail("normalized_mapping_duplicate")
        result[key] = f"{managed_corpus_id}:conversation-{ordinal:04d}"
    return managed_corpus_id, result


def _metadata(db: sqlite3.Connection, policy: _AuthorityPolicy) -> dict[str, object]:
    slot_count = int(db.execute("SELECT count(*) FROM original_slots").fetchone()[0])
    operation_count = int(db.execute("SELECT count(*) FROM admitted_mapping").fetchone()[0])
    omitted_row = db.execute(
        "SELECT count(*) FROM original_slots WHERE admitted_sequence IS NULL"
    ).fetchone()
    omitted = int(omitted_row[0])
    if (
        slot_count != policy.original_pair_slot_count
        or operation_count != policy.operation_count
        or omitted != policy.omitted_source_identity_count
        or slot_count != operation_count + omitted
    ):
        _fail("oracle_count_mismatch")
    content_root, slot_root, mapping_root = _content_roots(db)
    omitted_original_pair_root = _paged_root(
        "omitted-original-pair-page/v1",
        (
            str(row[0])
            for row in db.execute(
                "SELECT original_pair_identity_sha256 FROM original_slots "
                "WHERE admitted_sequence IS NULL ORDER BY slot_sequence"
            )
        ),
    )
    if omitted_original_pair_root != policy.omitted_original_pair_identity_root_sha256:
        _fail("omitted_original_pair_root_mismatch")
    body: dict[str, object] = {
        "schema_version": _SCHEMA,
        "profile_id": policy.profile_id,
        "dataset_sha256": policy.dataset_sha256,
        "operation_count": operation_count,
        "original_pair_slot_count": slot_count,
        "omitted_source_identity_count": omitted,
        "omitted_source_identity_root_sha256": policy.omitted_source_identity_root_sha256,
        "omitted_original_pair_identity_root_sha256": omitted_original_pair_root,
        "original_pair_slot_root_sha256": slot_root,
        "ordered_mapping_root_sha256": mapping_root,
        "content_root_sha256": content_root,
    }
    return {
        **body,
        "terminal_commitment_sha256": commitment("original-pair-authority-terminal/v1", body),
    }


def _content_roots(db: sqlite3.Connection) -> tuple[str, str, str]:
    slot_pages = _paged_root(
        "original-pair-slot-page/v1",
        (
            commitment(
                "original-pair-slot-row/v1",
                {
                    "slot_sequence": int(row[0]),
                    "original_pair_identity_sha256": str(row[1]),
                    "admitted_sequence": row[2],
                },
            )
            for row in db.execute(
                "SELECT slot_sequence,original_pair_identity_sha256,admitted_sequence "
                "FROM original_slots ORDER BY slot_sequence"
            )
        ),
    )
    mapping_pages = _paged_root(
        "original-pair-mapping-page/v1",
        _mapping_identities(db),
    )
    return (
        commitment(
            "original-pair-content-root/v1",
            {
                "original_pair_slot_root_sha256": slot_pages,
                "ordered_mapping_root_sha256": mapping_pages,
            },
        ),
        slot_pages,
        mapping_pages,
    )


def _mapping_identities(db: sqlite3.Connection) -> Iterator[str]:
    for row in db.execute(
        "SELECT sequence,corpus_id_sha256,normalized_source_id_sha256,"
        "original_pair_identity_sha256,mapping_identity_sha256 "
        "FROM admitted_mapping ORDER BY sequence"
    ):
        observed = commitment(
            "original-pair-mapping/v1",
            {
                "sequence": int(row[0]),
                "corpus_id_sha256": str(row[1]),
                "normalized_source_id_sha256": str(row[2]),
                "original_pair_identity_sha256": str(row[3]),
            },
        )
        if observed != row[4]:
            _fail("content_invalid")
        yield observed


def _authenticate_mapping_rows(
    db: sqlite3.Connection,
    *,
    key: bytes,
    metadata: Mapping[str, object],
) -> None:
    cursor = db.execute(
        "SELECT sequence,corpus_id_sha256,normalized_source_id_sha256,"
        "original_pair_identity_sha256,mapping_identity_sha256,authentication_tag "
        "FROM admitted_mapping ORDER BY sequence"
    )
    while rows := cursor.fetchmany(_PAGE_SIZE):
        authenticated: list[tuple[str, int]] = []
        for row in rows:
            payload = _mapping_row_payload(row)
            sequence = payload["sequence"]
            if type(sequence) is not int:
                _fail("content_invalid")
            authenticated.append(
                (_mapping_row_tag(key=key, metadata=metadata, payload=payload), sequence)
            )
        db.executemany(
            "UPDATE admitted_mapping SET authentication_tag=? WHERE sequence=?",
            authenticated,
        )


def _verify_mapping_row_authentication(
    db: sqlite3.Connection,
    *,
    key: bytes,
    metadata: Mapping[str, object],
) -> None:
    cursor = db.execute(
        "SELECT sequence,corpus_id_sha256,normalized_source_id_sha256,"
        "original_pair_identity_sha256,mapping_identity_sha256,authentication_tag "
        "FROM admitted_mapping ORDER BY sequence"
    )
    while rows := cursor.fetchmany(_PAGE_SIZE):
        for row in rows:
            observed = row[5]
            expected = _mapping_row_tag(
                key=key,
                metadata=metadata,
                payload=_mapping_row_payload(row),
            )
            if type(observed) is not str or not hmac.compare_digest(observed, expected):
                _fail("authentication_invalid")


def _mapping_row_payload(row: Sequence[object]) -> dict[str, object]:
    if (
        len(row) != 6
        or type(row[0]) is not int
        or row[0] < 0
        or not all(_digest(row[index]) for index in range(1, 5))
    ):
        _fail("lookup_content_invalid")
    payload: dict[str, object] = {
        "sequence": row[0],
        "corpus_id_sha256": row[1],
        "normalized_source_id_sha256": row[2],
        "original_pair_identity_sha256": row[3],
        "mapping_identity_sha256": row[4],
    }
    observed_mapping = commitment(
        "original-pair-mapping/v1",
        {
            "sequence": row[0],
            "corpus_id_sha256": row[1],
            "normalized_source_id_sha256": row[2],
            "original_pair_identity_sha256": row[3],
        },
    )
    if observed_mapping != row[4]:
        _fail("lookup_content_invalid")
    return payload


def _mapping_row_tag(
    *,
    key: bytes,
    metadata: Mapping[str, object],
    payload: Mapping[str, object],
) -> str:
    context = {
        "schema_version": metadata.get("schema_version"),
        "profile_id": metadata.get("profile_id"),
        "dataset_sha256": metadata.get("dataset_sha256"),
        "original_pair_slot_root_sha256": metadata.get("original_pair_slot_root_sha256"),
        "ordered_mapping_root_sha256": metadata.get("ordered_mapping_root_sha256"),
        "terminal_commitment_sha256": metadata.get("terminal_commitment_sha256"),
    }
    if (
        type(context["schema_version"]) is not str
        or context["schema_version"] != _SCHEMA
        or type(context["profile_id"]) is not str
        or not context["profile_id"]
        or not all(
            _digest(context[name])
            for name in (
                "dataset_sha256",
                "original_pair_slot_root_sha256",
                "ordered_mapping_root_sha256",
                "terminal_commitment_sha256",
            )
        )
    ):
        _fail("lookup_context_invalid")
    return hmac.new(
        key,
        _ROW_MAC_DOMAIN + canonical_bytes({"authority": context, "mapping": dict(payload)}),
        hashlib.sha256,
    ).hexdigest()


def _row_key(key: bytes) -> bytes:
    return hmac.new(key, _ROW_KEY_DOMAIN, hashlib.sha256).digest()


def _paged_root(label: str, values: Iterator[str]) -> str:
    pages: list[str] = []
    current: list[str] = []
    for value in values:
        if not _digest(value):
            _fail("content_invalid")
        current.append(value)
        if len(current) == _PAGE_SIZE:
            pages.append(commitment(label, {"page_index": len(pages), "items": current}))
            current = []
    if current:
        pages.append(commitment(label, {"page_index": len(pages), "items": current}))
    if not pages:
        _fail("content_empty")
    return merkle_root(tuple(pages))


def _json_array_items(value: bytes) -> Iterator[dict[str, object]]:
    try:
        text = value.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise OriginalPairIdentityAuthorityError("original_pair_dataset_invalid") from exc
    decoder = json.JSONDecoder()
    index = _whitespace(text, 0)
    if index >= len(text) or text[index] != "[":
        _fail("dataset_invalid")
    index = _whitespace(text, index + 1)
    if index < len(text) and text[index] == "]":
        _fail("dataset_empty")
    while True:
        try:
            item, index = decoder.raw_decode(text, index)
        except (TypeError, ValueError) as exc:
            raise OriginalPairIdentityAuthorityError("original_pair_dataset_invalid") from exc
        if type(item) is not dict:
            _fail("dataset_invalid")
        yield item
        index = _whitespace(text, index)
        if index >= len(text):
            _fail("dataset_invalid")
        if text[index] == "]":
            index = _whitespace(text, index + 1)
            if index != len(text):
                _fail("dataset_invalid")
            return
        if text[index] != ",":
            _fail("dataset_invalid")
        index = _whitespace(text, index + 1)


def _whitespace(value: str, index: int) -> int:
    while index < len(value) and value[index] in " \t\r\n":
        index += 1
    return index


def _sequence_item(value: object, index: int) -> object:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes) or index >= len(value):
        return None
    return value[index]


def _configure(db: sqlite3.Connection, *, readonly: bool = False) -> None:
    db.execute("PRAGMA trusted_schema=OFF")
    db.execute("PRAGMA foreign_keys=ON")
    if not readonly:
        db.execute("PRAGMA journal_mode=DELETE")
        db.execute("PRAGMA synchronous=FULL")


def _schema(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE original_slots(
          slot_sequence INTEGER PRIMARY KEY,
          original_pair_identity_sha256 TEXT NOT NULL UNIQUE,
          admitted_sequence INTEGER UNIQUE
        ) STRICT;
        CREATE TABLE admitted_mapping(
          sequence INTEGER PRIMARY KEY,
          corpus_id_sha256 TEXT NOT NULL,
          normalized_source_id_sha256 TEXT NOT NULL,
          original_pair_identity_sha256 TEXT NOT NULL UNIQUE,
          mapping_identity_sha256 TEXT NOT NULL UNIQUE,
          authentication_tag TEXT NOT NULL,
          UNIQUE(sequence,corpus_id_sha256,normalized_source_id_sha256),
          FOREIGN KEY(original_pair_identity_sha256)
            REFERENCES original_slots(original_pair_identity_sha256) DEFERRABLE INITIALLY DEFERRED
        ) STRICT;
        CREATE TABLE authority_metadata(
          singleton INTEGER PRIMARY KEY CHECK(singleton=1),
          payload_json TEXT NOT NULL,
          authentication_tag TEXT NOT NULL
        ) STRICT;
        """
    )


def _key(value: object) -> bytes:
    if type(value) is not bytes or len(value) < 32:
        _fail("authentication_key_invalid")
    return value


def _validate_dataset_bytes(dataset_bytes: object, policy: _AuthorityPolicy) -> str:
    if type(dataset_bytes) is not bytes:
        _fail("dataset_invalid")
    dataset_sha = hashlib.sha256(dataset_bytes).hexdigest()
    if dataset_sha != policy.dataset_sha256:
        _fail("dataset_sha256_mismatch")
    return dataset_sha


def _staging_path(target: Path) -> Path:
    identity = hashlib.sha256(os.fsencode(target.name)).hexdigest()[:24]
    return target.with_name(f".original-pair-{identity}.partial")


def _path_present(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise OriginalPairIdentityAuthorityError("original_pair_store_path_invalid") from exc
    return True


def _discard_crash_partial(staging: Path) -> None:
    for suffix in ("-journal", "-wal", "-shm"):
        sidecar = Path(f"{staging}{suffix}")
        if _path_present(sidecar):
            discard_secure_file(sidecar)
    if _path_present(staging):
        discard_secure_file(staging)


def _digest(value: object) -> bool:
    return type(value) is str and len(value) == 64 and set(value) <= _SHA


def _fail(suffix: str) -> None:
    raise OriginalPairIdentityAuthorityError(f"original_pair_{suffix}")


__all__ = (
    "OriginalPairIdentityAuthorityError",
    "SQLiteOriginalPairIdentityAuthority",
)

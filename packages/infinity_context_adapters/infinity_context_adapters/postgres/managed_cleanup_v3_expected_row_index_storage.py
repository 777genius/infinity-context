"""SQLite storage and full-coverage checks for cleanup-v3 expected rows."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable
from typing import Final

from infinity_context_core.ports.managed_cleanup_v3_contracts import (
    ManagedCleanupV3Authority,
    ManagedCleanupV3Context,
    ManagedCleanupV3Error,
    ManagedCleanupV3Operation,
    ManagedCleanupV3Page,
    commitment,
    merkle_root,
)

from infinity_context_adapters.postgres.managed_cleanup_v3_expected_row_authentication import (
    expected_index_row_tag,
)

_SCHEMA: Final = "managed-cleanup-v4-expected-row-index.v1"


def validate_authority_binding(
    context: ManagedCleanupV3Context, authority: ManagedCleanupV3Authority
) -> None:
    if (
        type(context) is not ManagedCleanupV3Context
        or type(authority) is not ManagedCleanupV3Authority
    ):
        _fail("binding_invalid")
    context.__post_init__()
    authority.__post_init__()
    if (
        authority.profile_id != context.profile_id
        or authority.context_sha256 != context.context_sha256
        or authority.a1_terminal_commitment_sha256 != context.a1_terminal_commitment_sha256
        or authority.cleanup_operation_stream_root_sha256
        != context.cleanup_operation_stream_root_sha256
        or authority.omitted_source_identity_root_sha256
        != context.omitted_source_identity_root_sha256
    ):
        _fail("binding_invalid")


def ingest_authority_pages(
    db: sqlite3.Connection,
    context: ManagedCleanupV3Context,
    authority: ManagedCleanupV3Authority,
    pages: Iterable[ManagedCleanupV3Page],
    authentication_key: bytes,
) -> None:
    expected_sequence = valid_messages = fragments = page_count = 0
    page_hashes: list[str] = []
    stream_items: list[str] = []
    stream_pages: list[str] = []
    corpus_thread_identities: list[str] = []
    document_source_ref_items: list[str] = []
    document_source_ref_pages: list[str] = []
    document_source_ref_count = 0
    closed_corpora: set[str] = set()
    current_corpus: str | None = None
    current_lane: str | None = None
    current_scope: str | None = None
    current_thread: str | None = None
    try:
        iterator = iter(pages)
    except TypeError as exc:
        raise ManagedCleanupV3Error("managed_cleanup_v3_expected_index_pages_invalid") from exc
    with db:
        for page in iterator:
            if type(page) is not ManagedCleanupV3Page:
                _fail("page_invalid")
            page.__post_init__()
            if (
                page_count >= authority.page_count
                or page.context_sha256 != context.context_sha256
                or page.page_index != page_count
                or page.start_sequence != expected_sequence
                or page.page_sha256 != authority.ordered_page_sha256[page_count]
            ):
                _fail("page_invalid")
            for operation in page.operations:
                if operation.sequence != expected_sequence:
                    _fail("coverage_invalid")
                corpus = operation.corpus_identity_sha256
                if current_corpus != corpus:
                    if corpus in closed_corpora:
                        _fail("corpus_duplicate")
                    if current_corpus is not None:
                        closed_corpora.add(current_corpus)
                    current_corpus = corpus
                    current_lane = operation.lane
                    current_scope = operation.memory_scope_external_ref_sha256
                    current_thread = operation.thread_external_ref_sha256
                    corpus_thread_identities.append(
                        commitment(
                            "corpus-scope-thread-identity/v4",
                            {
                                "lane": operation.lane,
                                "corpus_identity_sha256": corpus,
                                "memory_scope_external_ref_sha256": (
                                    operation.memory_scope_external_ref_sha256
                                ),
                                "thread_external_ref_sha256": (
                                    operation.thread_external_ref_sha256
                                ),
                            },
                        )
                    )
                    corpus_values = (corpus, expected_sequence)
                    db.execute(
                        "INSERT INTO corpora VALUES(?,?,?)",
                        (
                            *corpus_values,
                            _row_tag(
                                context, authority, authentication_key, "corpora", corpus_values
                            ),
                        ),
                    )
                elif (
                    operation.lane != current_lane
                    or operation.memory_scope_external_ref_sha256 != current_scope
                    or operation.thread_external_ref_sha256 != current_thread
                ):
                    _fail("corpus_binding_invalid")
                _insert_operation(db, context, authority, authentication_key, operation)
                if operation.lane == "document":
                    document_source_ref_count += len(operation.ordered_source_ref_descriptor_sha256)
                    document_source_ref_items.append(
                        commitment(
                            "document-source-ref-identity/v4",
                            {
                                "source_identity_sha256": operation.source_identity_sha256,
                                "source_ref_count": len(
                                    operation.ordered_source_ref_descriptor_sha256
                                ),
                                "source_refs_sha256": operation.source_refs_sha256,
                            },
                        )
                    )
                    if len(document_source_ref_items) == 512:
                        _flush_document_source_ref_page(
                            document_source_ref_pages, document_source_ref_items
                        )
                expected_sequence += 1
                valid_messages += operation.valid_message_count
                fragments += len(operation.ordered_fragment_descriptor_sha256)
                stream_items.append(operation.operation_sha256)
                if len(stream_items) == 512:
                    _flush_stream_page(stream_pages, stream_items)
            page_hashes.append(page.page_sha256)
            page_count += 1
    if (
        page_count != authority.page_count
        or expected_sequence != authority.operation_count
        or tuple(page_hashes) != authority.ordered_page_sha256
        or merkle_root(tuple(page_hashes)) != authority.pages_merkle_root_sha256
        or valid_messages != authority.valid_message_count
        or fragments != authority.fragment_count
        or len(corpus_thread_identities) != authority.corpus_thread_identity_count
        or commitment("corpus-scope-thread-identity-root/v4", corpus_thread_identities)
        != authority.corpus_thread_identity_root_sha256
        or document_source_ref_count != authority.document_source_ref_count
        or _document_source_ref_root(document_source_ref_pages, document_source_ref_items)
        != authority.document_source_ref_root_sha256
        or _finish_stream_root(stream_pages, stream_items)
        != authority.cleanup_operation_stream_root_sha256
    ):
        _fail("coverage_invalid")


def _flush_stream_page(pages: list[str], items: list[str]) -> None:
    pages.append(
        commitment(
            "operation-stream-page/v4",
            {"page_index": len(pages), "ordered_operation_sha256": items},
        )
    )
    items.clear()


def _finish_stream_root(pages: list[str], items: list[str]) -> str:
    if items:
        _flush_stream_page(pages, items)
    if len(pages) > 257:
        _fail("stream_page_bound_invalid")
    return merkle_root(tuple(pages))


def _flush_document_source_ref_page(pages: list[str], items: list[str]) -> None:
    pages.append(
        commitment(
            "document-source-ref-page/v4",
            {"page_index": len(pages), "ordered_identity_sha256": items},
        )
    )
    items.clear()


def _document_source_ref_root(pages: list[str], items: list[str]) -> str:
    if items:
        _flush_document_source_ref_page(pages, items)
    return merkle_root(tuple(pages)) if pages else commitment("document-source-ref-empty/v4", [])


def _insert_operation(
    db: sqlite3.Connection,
    context: ManagedCleanupV3Context,
    authority: ManagedCleanupV3Authority,
    key: bytes,
    operation: ManagedCleanupV3Operation,
) -> None:
    operation_values = (
        operation.sequence,
        operation.lane,
        operation.corpus_identity_sha256,
        operation.memory_scope_external_ref_sha256,
        operation.thread_external_ref_sha256,
        operation.source_identity_sha256,
        operation.source_content_sha256,
        operation.operation_commitment_sha256,
        operation.operation_sha256,
        operation.source_refs_sha256,
        operation.source_ref_root_sha256,
        len(operation.ordered_source_ref_descriptor_sha256),
        operation.fragments_sha256,
        operation.fragment_root_sha256,
        len(operation.ordered_fragment_descriptor_sha256),
    )
    try:
        db.execute(
            "INSERT INTO operations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                *operation_values,
                _row_tag(context, authority, key, "operations", operation_values),
            ),
        )
        db.executemany(
            "INSERT INTO source_refs VALUES(?,?,?,?)",
            (
                _descriptor_values(
                    context, authority, key, "source_refs", operation.sequence, ordinal, descriptor
                )
                for ordinal, descriptor in enumerate(operation.ordered_source_ref_descriptor_sha256)
            ),
        )
        db.executemany(
            "INSERT INTO fragments VALUES(?,?,?,?)",
            (
                _descriptor_values(
                    context, authority, key, "fragments", operation.sequence, ordinal, descriptor
                )
                for ordinal, descriptor in enumerate(operation.ordered_fragment_descriptor_sha256)
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise ManagedCleanupV3Error("managed_cleanup_v3_expected_index_duplicate") from exc


def configure_index(db: sqlite3.Connection, *, readonly: bool = False) -> None:
    db.execute("PRAGMA trusted_schema=OFF")
    db.execute("PRAGMA foreign_keys=ON")
    if not readonly:
        db.execute("PRAGMA journal_mode=DELETE")
        db.execute("PRAGMA synchronous=FULL")


def create_index_schema(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE metadata(
            singleton INTEGER PRIMARY KEY CHECK(singleton=1),
            payload_json TEXT NOT NULL,
            authentication_tag TEXT NOT NULL
        ) STRICT;
        CREATE TABLE corpora(
            corpus_sha TEXT PRIMARY KEY,
            first_sequence INTEGER NOT NULL UNIQUE,
            authentication_tag TEXT NOT NULL
        ) STRICT;
        CREATE TABLE operations(
            sequence INTEGER PRIMARY KEY,
            lane TEXT NOT NULL CHECK(lane IN ('fact','document')),
            corpus_sha TEXT NOT NULL REFERENCES corpora(corpus_sha),
            scope_sha TEXT NOT NULL,
            thread_sha TEXT NOT NULL,
            source_sha TEXT NOT NULL UNIQUE,
            content_sha TEXT NOT NULL,
            commitment_sha TEXT NOT NULL UNIQUE,
            operation_sha TEXT NOT NULL UNIQUE,
            source_refs_sha TEXT NOT NULL,
            source_ref_root_sha TEXT NOT NULL,
            source_ref_count INTEGER NOT NULL,
            fragments_sha TEXT NOT NULL,
            fragment_root_sha TEXT NOT NULL,
            fragment_count INTEGER NOT NULL,
            authentication_tag TEXT NOT NULL
        ) STRICT;
        CREATE INDEX operations_corpus_sequence
            ON operations(corpus_sha, sequence);
        CREATE INDEX operations_content ON operations(lane, content_sha);
        CREATE TABLE source_refs(
            sequence INTEGER NOT NULL REFERENCES operations(sequence),
            ordinal INTEGER NOT NULL,
            descriptor_sha TEXT NOT NULL,
            authentication_tag TEXT NOT NULL,
            PRIMARY KEY(sequence, ordinal)
        ) STRICT;
        CREATE INDEX source_refs_descriptor ON source_refs(descriptor_sha);
        CREATE TABLE fragments(
            sequence INTEGER NOT NULL REFERENCES operations(sequence),
            ordinal INTEGER NOT NULL,
            descriptor_sha TEXT NOT NULL,
            authentication_tag TEXT NOT NULL,
            PRIMARY KEY(sequence, ordinal)
        ) STRICT;
        CREATE INDEX fragments_descriptor ON fragments(descriptor_sha);
        """
    )


def content_root(db: sqlite3.Connection) -> str:
    state = hashlib.sha256(b"managed-cleanup-v4-index-content/v1\0")
    for table, columns, order in (
        ("corpora", "corpus_sha,first_sequence,authentication_tag", "first_sequence"),
        (
            "operations",
            (
                "sequence,lane,corpus_sha,scope_sha,thread_sha,source_sha,content_sha,"
                "commitment_sha,operation_sha,source_refs_sha,source_ref_root_sha,"
                "source_ref_count,fragments_sha,fragment_root_sha,fragment_count,authentication_tag"
            ),
            "sequence",
        ),
        (
            "source_refs",
            "sequence,ordinal,descriptor_sha,authentication_tag",
            "sequence,ordinal",
        ),
        (
            "fragments",
            "descriptor_sha,sequence,ordinal,authentication_tag",
            "sequence,ordinal",
        ),
    ):
        for row in db.execute(f"SELECT {columns} FROM {table} ORDER BY {order}"):
            state.update(_json([table, *row]))
    return state.hexdigest()


def index_metadata(
    context: ManagedCleanupV3Context,
    authority: ManagedCleanupV3Authority,
    content_root_sha256: str,
) -> dict[str, object]:
    return {
        "schema_version": _SCHEMA,
        "profile_id": context.profile_id,
        "context_sha256": context.context_sha256,
        "a1_terminal_commitment_sha256": context.a1_terminal_commitment_sha256,
        "authority_terminal_sha256": authority.terminal_commitment_sha256,
        "pages_merkle_root_sha256": authority.pages_merkle_root_sha256,
        "cleanup_operation_stream_root_sha256": authority.cleanup_operation_stream_root_sha256,
        "operation_count": authority.operation_count,
        "page_count": authority.page_count,
        "fragment_count": authority.fragment_count,
        "corpus_thread_identity_count": authority.corpus_thread_identity_count,
        "corpus_thread_identity_root_sha256": authority.corpus_thread_identity_root_sha256,
        "document_source_ref_count": authority.document_source_ref_count,
        "document_source_ref_root_sha256": authority.document_source_ref_root_sha256,
        "content_root_sha256": content_root_sha256,
    }


def _json(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("ascii")


def _row_tag(
    context: ManagedCleanupV3Context,
    authority: ManagedCleanupV3Authority,
    key: bytes,
    table: str,
    values: tuple[object, ...],
) -> str:
    return expected_index_row_tag(
        key,
        context_sha256=context.context_sha256,
        authority_terminal_sha256=authority.terminal_commitment_sha256,
        table=table,
        values=values,
    )


def _descriptor_values(
    context: ManagedCleanupV3Context,
    authority: ManagedCleanupV3Authority,
    key: bytes,
    table: str,
    sequence: int,
    ordinal: int,
    descriptor: str,
) -> tuple[object, ...]:
    values = (sequence, ordinal, descriptor)
    return *values, _row_tag(context, authority, key, table, values)


def _fail(suffix: str) -> None:
    raise ManagedCleanupV3Error(f"managed_cleanup_v3_expected_index_{suffix}")


__all__ = (
    "configure_index",
    "content_root",
    "create_index_schema",
    "index_metadata",
    "ingest_authority_pages",
    "validate_authority_binding",
)

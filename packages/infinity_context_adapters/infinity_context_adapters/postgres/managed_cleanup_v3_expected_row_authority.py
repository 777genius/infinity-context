from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
from collections.abc import Iterable, Mapping
from contextlib import suppress
from pathlib import Path
from typing import Final, final

from infinity_context_core.ports.managed_cleanup_v3_contracts import (
    ManagedCleanupV3Authority,
    ManagedCleanupV3Context,
    ManagedCleanupV3Error,
    ManagedCleanupV3Page,
)

from infinity_context_adapters.postgres.managed_cleanup_v3_expected_row_bootstrap import (
    open_or_create_repairable_bootstrap,
)
from infinity_context_adapters.postgres.managed_cleanup_v3_expected_row_claims import (
    DurableExpectedRowClaims,
)
from infinity_context_adapters.postgres.managed_cleanup_v3_expected_row_files import (
    close_secure_sqlite,
    create_secure_sqlite,
    open_secure_sqlite,
    secure_file_identity,
    unlink_secure_file,
    verify_secure_path,
)
from infinity_context_adapters.postgres.managed_cleanup_v3_expected_row_index_storage import (
    configure_index as _configure,
)
from infinity_context_adapters.postgres.managed_cleanup_v3_expected_row_index_storage import (
    content_root as _content_root,
)
from infinity_context_adapters.postgres.managed_cleanup_v3_expected_row_index_storage import (
    create_index_schema as _create_schema,
)
from infinity_context_adapters.postgres.managed_cleanup_v3_expected_row_index_storage import (
    index_metadata as _metadata,
)
from infinity_context_adapters.postgres.managed_cleanup_v3_expected_row_index_storage import (
    ingest_authority_pages as _ingest,
)
from infinity_context_adapters.postgres.managed_cleanup_v3_expected_row_index_storage import (
    validate_authority_binding as _validate_binding,
)
from infinity_context_adapters.postgres.managed_cleanup_v3_expected_row_lookup import (
    AuthenticatedExpectedRowLookup,
    ExpectedCleanupV3Operation,
)
from infinity_context_adapters.postgres.managed_cleanup_v3_expected_row_sidecar import (
    create_claim_sidecar,
    open_claim_sidecar,
    repair_missing_claim_sidecar,
)
from infinity_context_adapters.postgres.managed_cleanup_v3_expected_row_verifier import (
    verify_expected_row as verify_stateless_expected_row,
)

_MAC_DOMAIN: Final = b"managed-cleanup-v4-expected-row-index/v1\0"


@final
class SQLiteManagedCleanupV3ExpectedRowAuthority:
    def __init__(
        self,
        connection: sqlite3.Connection,
        connection_fd: int,
        claim_connection: sqlite3.Connection,
        claim_connection_fd: int,
        *,
        index_path: Path,
        context_sha256: str,
        authority_terminal_sha256: str,
        authentication_key: bytes,
    ) -> None:
        self._db = connection
        self._db_fd = connection_fd
        self._claim_db = claim_connection
        self._claim_db_fd = claim_connection_fd
        self._index_path = index_path
        self._context_sha256 = context_sha256
        self._authority_terminal_sha256 = authority_terminal_sha256
        self._main_file_identity = secure_file_identity(connection_fd)
        self._closed = False
        self._claims = DurableExpectedRowClaims(
            connection,
            claim_connection,
            authentication_key,
            authority_terminal_sha256,
        )
        self._lookup = AuthenticatedExpectedRowLookup(connection, self._claims, context_sha256)

    @classmethod
    def create(
        cls,
        path: str | os.PathLike[str],
        *,
        context: ManagedCleanupV3Context,
        authority: ManagedCleanupV3Authority,
        pages: Iterable[ManagedCleanupV3Page],
        authentication_key: bytes,
    ) -> SQLiteManagedCleanupV3ExpectedRowAuthority:
        _validate_binding(context, authority)
        key = _key(authentication_key)
        target = Path(path)
        claim_target = _claim_path(target)
        if claim_target.exists() or claim_target.is_symlink():
            _fail("index_exists")
        db, db_fd = create_secure_sqlite(target)
        db_open = True
        claim_db: sqlite3.Connection | None = None
        claim_db_fd: int | None = None
        try:
            _configure(db)
            _create_schema(db)
            _ingest(db, context, authority, pages, key)
            content_root = _content_root(db)
            metadata = _metadata(context, authority, content_root)
            tag = hmac.new(key, _MAC_DOMAIN + _json(metadata), hashlib.sha256).hexdigest()
            db.execute(
                "INSERT INTO metadata(singleton, payload_json, authentication_tag) VALUES(1, ?, ?)",
                (_json(metadata).decode("ascii"), tag),
            )
            db.commit()
            claim_db, claim_db_fd = create_claim_sidecar(
                claim_target,
                context_sha256=context.context_sha256,
                authority_terminal_sha256=authority.terminal_commitment_sha256,
                authentication_key=key,
            )
            sealed_claim_db, sealed_claim_db_fd = claim_db, claim_db_fd
            claim_db = None
            claim_db_fd = None
            db_open = False
            try:
                close_secure_sqlite(sealed_claim_db, sealed_claim_db_fd)
            finally:
                close_secure_sqlite(db, db_fd)
            opened = cls.open(
                target,
                context=context,
                authority=authority,
                authentication_key=key,
            )
            try:
                opened._require_open()
            except BaseException:
                with suppress(BaseException):
                    opened.close()
                raise
            return opened
        except BaseException:
            if db_open:
                with suppress(ManagedCleanupV3Error, FileNotFoundError):
                    unlink_secure_file(target, db_fd)
                if claim_db is not None and claim_db_fd is not None:
                    with suppress(ManagedCleanupV3Error, FileNotFoundError):
                        unlink_secure_file(claim_target, claim_db_fd)
                _close_pair(db, db_fd, claim_db, claim_db_fd)
            raise

    @classmethod
    def open(
        cls,
        path: str | os.PathLike[str],
        *,
        context: ManagedCleanupV3Context,
        authority: ManagedCleanupV3Authority,
        authentication_key: bytes,
    ) -> SQLiteManagedCleanupV3ExpectedRowAuthority:
        _validate_binding(context, authority)
        key = _key(authentication_key)
        target = Path(path)
        claim_target = _claim_path(target)
        db, db_fd = _open_authenticated_main(target, context, authority, key)
        claim_db: sqlite3.Connection | None = None
        claim_db_fd: int | None = None
        opened: SQLiteManagedCleanupV3ExpectedRowAuthority | None = None
        try:
            claim_db, claim_db_fd = open_claim_sidecar(
                claim_target,
                context_sha256=context.context_sha256,
                authority_terminal_sha256=authority.terminal_commitment_sha256,
                authentication_key=key,
            )
            opened = cls(
                db,
                db_fd,
                claim_db,
                claim_db_fd,
                index_path=target,
                context_sha256=context.context_sha256,
                authority_terminal_sha256=authority.terminal_commitment_sha256,
                authentication_key=key,
            )
            opened._require_open()
            return opened
        except BaseException:
            if opened is not None:
                opened._claims.close()
            _close_pair(db, db_fd, claim_db, claim_db_fd)
            raise

    @classmethod
    def open_or_repair_claims(
        cls,
        path: str | os.PathLike[str],
        *,
        context: ManagedCleanupV3Context,
        authority: ManagedCleanupV3Authority,
        authentication_key: bytes,
    ) -> SQLiteManagedCleanupV3ExpectedRowAuthority:
        _validate_binding(context, authority)
        key = _key(authentication_key)
        target = Path(path)
        claim_target = _claim_path(target)
        db, db_fd = _open_authenticated_main(target, context, authority, key)
        claim_db: sqlite3.Connection | None = None
        claim_db_fd: int | None = None
        opened: SQLiteManagedCleanupV3ExpectedRowAuthority | None = None
        binding = {
            "context_sha256": context.context_sha256,
            "authority_terminal_sha256": authority.terminal_commitment_sha256,
            "authentication_key": key,
        }
        try:
            try:
                claim_target.lstat()
            except FileNotFoundError:
                claim_db, claim_db_fd = repair_missing_claim_sidecar(claim_target, **binding)
            else:
                claim_db, claim_db_fd = open_claim_sidecar(claim_target, **binding)
            opened = cls(
                db,
                db_fd,
                claim_db,
                claim_db_fd,
                index_path=target,
                context_sha256=context.context_sha256,
                authority_terminal_sha256=authority.terminal_commitment_sha256,
                authentication_key=key,
            )
            opened._require_open()
            return opened
        except BaseException:
            if opened is not None:
                opened._claims.close()
            _close_pair(db, db_fd, claim_db, claim_db_fd)
            raise

    @classmethod
    def create_or_open_repairable_bootstrap(
        cls,
        path: str | os.PathLike[str],
        *,
        context: ManagedCleanupV3Context,
        authority: ManagedCleanupV3Authority,
        pages: Iterable[ManagedCleanupV3Page],
        authentication_key: bytes,
    ) -> SQLiteManagedCleanupV3ExpectedRowAuthority:
        _validate_binding(context, authority)
        key = _key(authentication_key)
        target = Path(path)
        opened = open_or_create_repairable_bootstrap(
            target,
            claim_path=_claim_path(target),
            open_existing=lambda: cls.open_or_repair_claims(
                target, context=context, authority=authority, authentication_key=key
            ),
            create_new=lambda: cls.create(
                target,
                context=context,
                authority=authority,
                pages=pages,
                authentication_key=key,
            ),
        )
        try:
            opened._require_open()
        except BaseException:
            with suppress(BaseException):
                opened.close()
            raise
        return opened

    def close(self) -> None:
        if self._closed:
            return
        path_error: BaseException | None = None
        try:
            self._require_open()
        except BaseException as exc:
            path_error = exc
        self._closed = True
        self._claims.close()
        try:
            close_secure_sqlite(self._claim_db, self._claim_db_fd)
        finally:
            close_secure_sqlite(self._db, self._db_fd)
        if path_error is not None:
            raise path_error

    @property
    def authority_terminal_sha256(self) -> str:
        self._require_open()
        result = self._authority_terminal_sha256
        self._require_open()
        return result

    def begin_verification(
        self, authority_terminal_sha256: str, verification_session_sha256: str
    ) -> None:
        self._require_terminal(authority_terminal_sha256)
        self._claims.begin(verification_session_sha256)
        self._require_open()

    def begin_new_verification(
        self, authority_terminal_sha256: str, verification_session_sha256: str
    ) -> None:
        self._require_terminal(authority_terminal_sha256)
        self._claims.begin(verification_session_sha256, reset_authorized=True)
        self._require_open()

    def finalize_verification(
        self, authority_terminal_sha256: str, verification_session_sha256: str
    ) -> None:
        self._require_terminal(authority_terminal_sha256)
        self._claims.finalize(verification_session_sha256)
        self._require_open()

    def flush_verification_page(
        self, authority_terminal_sha256: str, verification_session_sha256: str
    ) -> None:
        self._require_terminal(authority_terminal_sha256)
        self._claims.flush_verification_page(verification_session_sha256)
        self._require_open()

    def abort_verification(
        self, authority_terminal_sha256: str, verification_session_sha256: str
    ) -> None:
        self._require_terminal(authority_terminal_sha256)
        self._claims.abort(verification_session_sha256)
        self._require_open()

    def _require_terminal(self, authority_terminal_sha256: str) -> None:
        self._require_open()
        if authority_terminal_sha256 != self._authority_terminal_sha256:
            _fail("authority_terminal_invalid")

    def _require_open(self) -> None:
        if self._closed:
            _fail("closed")
        verify_secure_path(self._index_path, self._db_fd)
        verify_secure_path(_claim_path(self._index_path), self._claim_db_fd)
        if secure_file_identity(self._db_fd) != self._main_file_identity:
            _fail("content_changed")

    def lookup_sequence(self, sequence: int) -> ExpectedCleanupV3Operation | None:
        self._require_open()
        result = self._lookup.lookup_sequence(sequence)
        self._require_open()
        return result

    def lookup_source(self, source_identity_sha256: str) -> ExpectedCleanupV3Operation | None:
        self._require_open()
        result = self._lookup.lookup_source(source_identity_sha256)
        self._require_open()
        return result

    def has_corpus(self, corpus_identity_sha256: str) -> bool:
        self._require_open()
        result = self._lookup.has_corpus(corpus_identity_sha256)
        self._require_open()
        return result

    def lookup_fragment(
        self, *, sequence: int, ordinal: int, descriptor_sha256: str
    ) -> tuple[ExpectedCleanupV3Operation, int] | None:
        self._require_open()
        result = self._lookup.lookup_fragment(
            sequence=sequence, ordinal=ordinal, descriptor_sha256=descriptor_sha256
        )
        self._require_open()
        return result

    def lookup_source_ref_descriptors(self, sequence: int) -> tuple[str, ...]:
        self._require_open()
        result = self._lookup.lookup_source_ref_descriptors(sequence)
        self._require_open()
        return result

    def lookup_fragment_descriptors(self, sequence: int) -> tuple[str, ...]:
        self._require_open()
        result = self._lookup.lookup_fragment_descriptors(sequence)
        self._require_open()
        return result

    async def verify_expected_row(
        self,
        *,
        context: ManagedCleanupV3Context,
        authority_terminal_sha256: str,
        verification_session_sha256: str,
        kind: str,
        locator_json: Mapping[str, object],
        row_json: Mapping[str, object],
    ) -> None:
        self._require_terminal(authority_terminal_sha256)
        if context.context_sha256 != self._context_sha256:
            _fail("row_binding_invalid")
        claim_kind, authority_item, locator = verify_stateless_expected_row(
            index=self,
            context=context,
            kind=kind,
            locator_json=locator_json,
            row_json=row_json,
        )
        self._claims.claim(verification_session_sha256, claim_kind, authority_item, locator)
        self._require_open()


def _key(value: bytes) -> bytes:
    if type(value) is not bytes or len(value) < 32:
        _fail("authentication_key_invalid")
    return value


def _claim_path(index_path: Path) -> Path:
    return index_path.with_name(f"{index_path.name}.claims")


def _open_authenticated_main(
    path: Path,
    context: ManagedCleanupV3Context,
    authority: ManagedCleanupV3Authority,
    key: bytes,
) -> tuple[sqlite3.Connection, int]:
    db, descriptor = open_secure_sqlite(path, readonly=True)
    try:
        _configure(db, readonly=True)
        db.execute("BEGIN")
        row = db.execute(
            "SELECT payload_json,authentication_tag FROM metadata WHERE singleton=1"
        ).fetchone()
        expected = _metadata(context, authority, _content_root(db))
        if (
            row is None
            or json.loads(row[0]) != expected
            or not hmac.compare_digest(
                str(row[1]),
                hmac.new(key, _MAC_DOMAIN + _json(expected), hashlib.sha256).hexdigest(),
            )
        ):
            _fail("authentication_invalid")
        return db, descriptor
    except BaseException:
        close_secure_sqlite(db, descriptor)
        raise


def _close_pair(
    db: sqlite3.Connection,
    descriptor: int,
    claim_db: sqlite3.Connection | None,
    claim_descriptor: int | None,
) -> None:
    try:
        if claim_db is not None and claim_descriptor is not None:
            close_secure_sqlite(claim_db, claim_descriptor)
    finally:
        close_secure_sqlite(db, descriptor)


def _json(value: object) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ManagedCleanupV3Error("managed_cleanup_v3_expected_index_json_invalid") from exc


def _fail(suffix: str) -> None:
    raise ManagedCleanupV3Error(f"managed_cleanup_v3_expected_index_{suffix}")


__all__ = (
    "ExpectedCleanupV3Operation",
    "SQLiteManagedCleanupV3ExpectedRowAuthority",
)

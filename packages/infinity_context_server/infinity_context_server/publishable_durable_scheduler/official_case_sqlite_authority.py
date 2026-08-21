"""Streaming HMAC-sealed SQLite authority for exact official scheduler cases."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Final, final

from infinity_context_server.publishable_durable_scheduler.manifest import (
    SchedulerCaseAuthority,
    case_manifest_sha256,
)
from infinity_context_server.publishable_durable_scheduler.official_authority_codec import (
    official_case_from_json,
    official_case_json,
)
from infinity_context_server.publishable_durable_scheduler.official_authority_contracts import (
    SCHEDULER_OFFICIAL_AUTHORITY_PAGE_BYTES_LIMIT,
    SCHEDULER_OFFICIAL_AUTHORITY_SCHEMA_VERSION,
    SchedulerOfficialAuthorityError,
    SchedulerOfficialCaseAuthorityPage,
    SchedulerOfficialCaseAuthorityTerminal,
    SchedulerOfficialCaseRunScope,
    validate_case_run_scopes,
)
from infinity_context_server.publishable_durable_scheduler.official_authority_integrity import (
    SchedulerOfficialAuthorityAuthenticator,
    authority_digest,
    canonical_mapping,
    canonical_text,
    create_schema,
    immediate_transaction,
    ordered_root,
    require_digest,
    require_exact_keys,
    require_int,
    schema_fingerprint,
    validate_schema,
)
from infinity_context_server.publishable_durable_scheduler.official_authority_scope_codec import (
    case_run_scopes_from_material,
    case_run_scopes_material,
)
from infinity_context_server.publishable_durable_scheduler.official_authority_sqlite_files import (
    SecureOfficialAuthoritySQLite,
    create_secure_authority_sqlite,
    open_secure_authority_sqlite,
    unlink_created_authority,
)
from infinity_context_server.publishable_durable_scheduler.official_case_sqlite_rows import (
    case_count as _case_count,
)
from infinity_context_server.publishable_durable_scheduler.official_case_sqlite_rows import (
    ingest_material as _ingest_material,
)
from infinity_context_server.publishable_durable_scheduler.official_case_sqlite_rows import (
    page_count as _page_count,
)
from infinity_context_server.publishable_durable_scheduler.official_case_sqlite_rows import (
    page_mac_material as _page_mac_material,
)
from infinity_context_server.publishable_durable_scheduler.official_case_sqlite_rows import (
    sealed_row_material as _sealed_row_material,
)
from infinity_context_server.publishable_durable_scheduler.official_case_sqlite_rows import (
    verify_page_row as _verify_page_row,
)
from infinity_context_server.publishable_durable_scheduler.runner_request_composition import (
    SchedulerAuthenticatedOfficialCase,
    SchedulerOfficialCaseKey,
    official_case_material_sha256,
)

_KIND: Final = "official-case"
_DUMMY_ROOT: Final = "0" * 64
_CONFIG_KEYS: Final = frozenset({"authority_kind", "run_scopes", "schema_version"})
_TERMINAL_BODY_KEYS: Final = frozenset(
    {
        "authority_kind",
        "case_count",
        "configuration_sha256",
        "page_count",
        "pages_root_sha256",
        "rows_root_sha256",
        "schema_fingerprint_sha256",
        "schema_version",
    }
)
_TERMINAL_KEYS: Final = _TERMINAL_BODY_KEYS | {
    "authority_root_sha256",
    "terminal_commitment_sha256",
    "terminal_hmac_sha256",
}

_SCHEMA: Final = (
    """CREATE TABLE authority_meta(
        singleton INTEGER PRIMARY KEY CHECK(singleton=1),
        schema_version TEXT NOT NULL,
        schema_fingerprint_sha256 TEXT NOT NULL,
        configuration_sha256 TEXT NOT NULL,
        configuration_json TEXT NOT NULL,
        configuration_mac TEXT NOT NULL,
        terminal_json TEXT,
        terminal_mac TEXT
    ) STRICT""",
    """CREATE TABLE authority_pages(
        page_index INTEGER PRIMARY KEY CHECK(page_index>=0),
        start_sequence INTEGER NOT NULL UNIQUE CHECK(start_sequence>=0),
        row_count INTEGER NOT NULL CHECK(row_count>0 AND row_count<=256),
        page_sha256 TEXT NOT NULL UNIQUE,
        page_mac TEXT NOT NULL
    ) STRICT""",
    """CREATE TABLE official_cases(
        sequence INTEGER PRIMARY KEY CHECK(sequence>=0),
        page_index INTEGER NOT NULL REFERENCES authority_pages(page_index),
        run_id TEXT NOT NULL,
        case_index INTEGER NOT NULL CHECK(case_index>=0),
        case_id TEXT NOT NULL,
        case_alias TEXT NOT NULL,
        unrooted_key_json TEXT NOT NULL,
        case_json TEXT NOT NULL,
        row_commitment_sha256 TEXT NOT NULL UNIQUE,
        ingest_mac TEXT NOT NULL,
        material_sha256 TEXT,
        sealed_mac TEXT,
        UNIQUE(run_id,case_index),
        UNIQUE(run_id,case_id),
        UNIQUE(run_id,case_alias)
    ) STRICT""",
    """CREATE UNIQUE INDEX official_cases_exact_lookup
        ON official_cases(run_id,case_index,case_id,case_alias)""",
    """CREATE INDEX official_cases_page_sequence
        ON official_cases(page_index,sequence)""",
)


@final
class SQLiteSchedulerOfficialCaseAuthorityBuilder:
    """Incrementally write bounded case pages, then atomically seal once."""

    __slots__ = ("_auth", "_configuration", "_configuration_sha256", "_handle", "_scopes")

    def __init__(
        self,
        handle: SecureOfficialAuthoritySQLite,
        auth: SchedulerOfficialAuthorityAuthenticator,
        scopes: tuple[SchedulerOfficialCaseRunScope, ...],
    ) -> None:
        self._handle = handle
        self._auth = auth
        self._scopes = scopes
        self._configuration = _configuration(scopes)
        self._configuration_sha256 = authority_digest("case/configuration", self._configuration)

    @classmethod
    def create(
        cls,
        path: str | os.PathLike[str],
        *,
        run_scopes: tuple[SchedulerOfficialCaseRunScope, ...],
        authentication_key: bytes,
    ) -> SQLiteSchedulerOfficialCaseAuthorityBuilder:
        scopes = validate_case_run_scopes(run_scopes)
        auth = SchedulerOfficialAuthorityAuthenticator(authentication_key, kind=_KIND)
        handle = create_secure_authority_sqlite(Path(path))
        builder = cls(handle, auth, scopes)
        try:
            with immediate_transaction(handle.connection):
                create_schema(handle.connection, _SCHEMA)
                values = builder._meta_values()
                handle.connection.execute(
                    "INSERT INTO authority_meta VALUES(?,?,?,?,?,?,NULL,NULL)",
                    (*values, auth.sign("case/configuration", values)),
                )
            handle.verify_bound()
            builder._verify_meta()
            return builder
        except BaseException:
            unlink_created_authority(handle)
            raise

    @classmethod
    def open(
        cls,
        path: str | os.PathLike[str],
        *,
        run_scopes: tuple[SchedulerOfficialCaseRunScope, ...],
        authentication_key: bytes,
    ) -> SQLiteSchedulerOfficialCaseAuthorityBuilder:
        scopes = validate_case_run_scopes(run_scopes)
        auth = SchedulerOfficialAuthorityAuthenticator(authentication_key, kind=_KIND)
        handle = open_secure_authority_sqlite(Path(path), readonly=False)
        builder = cls(handle, auth, scopes)
        try:
            validate_schema(handle.connection, _SCHEMA)
            terminal = builder._verify_meta()
            _verify_case_state(
                builder,
                require_complete=terminal is not None,
                terminal=terminal,
            )
            handle.verify_bound()
            return builder
        except BaseException:
            handle.close(validate=False)
            raise

    @property
    def next_sequence(self) -> int:
        with self._handle.serialized():
            self._handle.verify_bound()
            value = _case_count(self._handle.connection)
            self._handle.verify_bound()
            return value

    def append_page(self, page: SchedulerOfficialCaseAuthorityPage) -> None:
        if type(page) is not SchedulerOfficialCaseAuthorityPage:
            _fail("scheduler_official_case_authority_page_invalid")
        page.__post_init__()
        with self._handle.serialized():
            self._handle.verify_bound()
            connection = self._handle.connection
            with immediate_transaction(connection):
                terminal = self._verify_meta()
                existing = connection.execute(
                    "SELECT * FROM authority_pages WHERE page_index=?", (page.page_index,)
                ).fetchone()
                start = _case_count(connection) if existing is None else existing["start_sequence"]
                prepared = self._prepare_page(page, start_sequence=start)
                if existing is not None:
                    _verify_page_row(existing, prepared[0], self._auth, self._configuration_sha256)
                    return
                if terminal is not None:
                    _fail("scheduler_official_case_authority_sealed")
                expected_page = _page_count(connection)
                if page.page_index != expected_page or start != _case_count(connection):
                    _fail("scheduler_official_case_authority_page_coverage_invalid")
                page_values = prepared[0]
                connection.execute(
                    "INSERT INTO authority_pages VALUES(?,?,?,?,?)",
                    (
                        *page_values,
                        self._auth.sign(
                            "case/page",
                            _page_mac_material(self._configuration_sha256, page_values),
                        ),
                    ),
                )
                for values in prepared[1]:
                    connection.execute(
                        "INSERT INTO official_cases VALUES(?,?,?,?,?,?,?,?,?,?,NULL,NULL)",
                        (
                            *values,
                            self._auth.sign(
                                "case/ingest-row",
                                _ingest_material(self._configuration_sha256, values),
                            ),
                        ),
                    )
            self._handle.verify_bound()

    def finalize(self) -> SchedulerOfficialCaseAuthorityTerminal:
        with self._handle.serialized():
            self._handle.verify_bound()
            connection = self._handle.connection
            with immediate_transaction(connection):
                existing = self._verify_meta()
                if existing is not None:
                    _verify_case_state(self, require_complete=True, terminal=existing)
                    return existing
                state = _verify_case_state(self, require_complete=True)
                terminal = _build_terminal(self._auth, self._configuration_sha256, state)
                _seal_case_rows(self, terminal.authority_root_sha256)
                terminal_json = canonical_text(_terminal_payload(terminal))
                terminal_mac = self._auth.sign(
                    "case/meta-terminal",
                    {
                        "configuration_sha256": self._configuration_sha256,
                        "terminal": _terminal_payload(terminal),
                    },
                )
                cursor = connection.execute(
                    """UPDATE authority_meta SET terminal_json=?,terminal_mac=?
                       WHERE singleton=1 AND terminal_json IS NULL AND terminal_mac IS NULL""",
                    (terminal_json, terminal_mac),
                )
                if cursor.rowcount != 1:
                    _fail("scheduler_official_case_authority_seal_race")
                _verify_case_state(self, require_complete=True, terminal=terminal)
            self._handle.verify_bound()
            return terminal

    def close(self) -> None:
        self._handle.close()

    def __enter__(self) -> SQLiteSchedulerOfficialCaseAuthorityBuilder:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _meta_values(self) -> tuple[object, ...]:
        return (
            1,
            SCHEDULER_OFFICIAL_AUTHORITY_SCHEMA_VERSION,
            schema_fingerprint(_SCHEMA),
            self._configuration_sha256,
            canonical_text(self._configuration),
        )

    def _verify_meta(self) -> SchedulerOfficialCaseAuthorityTerminal | None:
        row = self._handle.connection.execute(
            "SELECT * FROM authority_meta WHERE singleton=1"
        ).fetchone()
        if row is None:
            _fail("scheduler_official_case_authority_meta_missing")
        values = tuple(
            row[name]
            for name in (
                "singleton",
                "schema_version",
                "schema_fingerprint_sha256",
                "configuration_sha256",
                "configuration_json",
            )
        )
        if values != self._meta_values() or not self._auth.verify(
            "case/configuration", values, row["configuration_mac"]
        ):
            _fail("scheduler_official_case_authority_authentication_invalid")
        return _terminal_from_meta(
            row["terminal_json"],
            row["terminal_mac"],
            auth=self._auth,
            configuration_sha256=self._configuration_sha256,
        )

    def _prepare_page(
        self, page: SchedulerOfficialCaseAuthorityPage, *, start_sequence: object
    ) -> tuple[tuple[object, ...], tuple[tuple[object, ...], ...]]:
        start = require_int(
            start_sequence,
            code="scheduler_official_case_authority_page_coverage_invalid",
        )
        rows: list[tuple[object, ...]] = []
        commitments: list[str] = []
        encoded_bytes = 0
        for offset, supplied in enumerate(page.rows):
            sequence = start + offset
            scope, expected_index = _scope_for_sequence(self._scopes, sequence)
            if supplied.run_id != scope.run_id or supplied.case_index != expected_index:
                _fail("scheduler_official_case_authority_row_coverage_invalid")
            key = scope.case_key(
                case_index=supplied.case_index,
                case_id=supplied.case_id,
                case_alias=supplied.case_alias,
                authority_root_sha256=_DUMMY_ROOT,
            )
            official_case_material_sha256(key, supplied.case)
            unrooted = _unrooted_key(key)
            unrooted_json = canonical_text(unrooted)
            case_json = official_case_json(supplied.case)
            encoded_bytes += len(unrooted_json.encode()) + len(case_json.encode())
            commitment = authority_digest(
                "case/unsealed-row",
                {
                    "case": canonical_mapping(
                        case_json,
                        code="scheduler_official_case_authority_case_json_invalid",
                    ),
                    "key": unrooted,
                    "sequence": sequence,
                },
            )
            commitments.append(commitment)
            rows.append(
                (
                    sequence,
                    page.page_index,
                    supplied.run_id,
                    supplied.case_index,
                    supplied.case_id,
                    supplied.case_alias,
                    unrooted_json,
                    case_json,
                    commitment,
                )
            )
        if encoded_bytes > SCHEDULER_OFFICIAL_AUTHORITY_PAGE_BYTES_LIMIT:
            _fail("scheduler_official_case_authority_page_too_large")
        page_sha = authority_digest(
            "case/page",
            {
                "ordered_row_commitments": commitments,
                "page_index": page.page_index,
                "start_sequence": start,
            },
        )
        return (page.page_index, start, len(rows), page_sha), tuple(rows)


@final
class SQLiteSchedulerOfficialCaseReader:
    """Read-only concrete SchedulerOfficialCaseReaderPort implementation."""

    __slots__ = (
        "_auth",
        "_configuration_sha256",
        "_handle",
        "_root",
        "_scopes",
        "_terminal",
    )

    def __init__(
        self,
        handle: SecureOfficialAuthoritySQLite,
        auth: SchedulerOfficialAuthorityAuthenticator,
        scopes: tuple[SchedulerOfficialCaseRunScope, ...],
        configuration_sha256: str,
        terminal: SchedulerOfficialCaseAuthorityTerminal,
    ) -> None:
        self._handle = handle
        self._auth = auth
        self._scopes = scopes
        self._configuration_sha256 = configuration_sha256
        self._terminal = terminal
        self._root = terminal.authority_root_sha256

    @classmethod
    def open(
        cls,
        path: str | os.PathLike[str],
        *,
        authentication_key: bytes,
        authority_root_sha256: str,
    ) -> SQLiteSchedulerOfficialCaseReader:
        expected_root = require_digest(
            authority_root_sha256,
            code="scheduler_official_case_authority_root_invalid",
        )
        auth = SchedulerOfficialAuthorityAuthenticator(authentication_key, kind=_KIND)
        handle = open_secure_authority_sqlite(Path(path), readonly=True)
        try:
            validate_schema(handle.connection, _SCHEMA)
            configuration, configuration_sha, terminal = _read_sealed_meta(handle, auth)
            scopes = _scopes_from_configuration(configuration)
            if terminal.authority_root_sha256 != expected_root:
                _fail("scheduler_official_case_authority_root_mismatch")
            reader = cls(handle, auth, scopes, configuration_sha, terminal)
            _verify_case_state(reader, require_complete=True, terminal=terminal)
            handle.freeze_identity()
            return reader
        except BaseException:
            handle.close(validate=False)
            raise

    @property
    def authority_root_sha256(self) -> str:
        self._handle.verify_stable()
        return self._root

    def read_exact(self, *, key: SchedulerOfficialCaseKey) -> SchedulerAuthenticatedOfficialCase:
        if type(key) is not SchedulerOfficialCaseKey:
            _fail("scheduler_official_case_authority_lookup_invalid")
        key.__post_init__()
        if key.authority_root_sha256 != self._root:
            _fail("scheduler_official_case_authority_lookup_cross_wire")
        with self._handle.serialized():
            self._handle.verify_stable()
            try:
                row = self._handle.connection.execute(
                    """SELECT * FROM official_cases
                       WHERE run_id=? AND case_index=? AND case_id=? AND case_alias=?""",
                    (key.run_id, key.case_index, key.case_id, key.case_alias),
                ).fetchone()
            except sqlite3.DatabaseError as error:
                raise SchedulerOfficialAuthorityError(
                    "scheduler_official_case_authority_read_invalid"
                ) from error
            if row is None:
                _fail("scheduler_official_case_authority_case_missing")
            result = _verified_case_result(
                row,
                key=key,
                auth=self._auth,
                configuration_sha256=self._configuration_sha256,
            )
            self._handle.verify_stable()
            return result

    def close(self) -> None:
        self._handle.close()

    def __enter__(self) -> SQLiteSchedulerOfficialCaseReader:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


SQLiteSchedulerOfficialCaseAuthorityReader = SQLiteSchedulerOfficialCaseReader


def _configuration(scopes: tuple[SchedulerOfficialCaseRunScope, ...]) -> dict[str, object]:
    return {
        "authority_kind": _KIND,
        "run_scopes": case_run_scopes_material(scopes),
        "schema_version": SCHEDULER_OFFICIAL_AUTHORITY_SCHEMA_VERSION,
    }


def _scopes_from_configuration(
    value: dict[str, object],
) -> tuple[SchedulerOfficialCaseRunScope, ...]:
    require_exact_keys(value, _CONFIG_KEYS, code="scheduler_official_case_authority_config_invalid")
    if (
        value.get("authority_kind") != _KIND
        or value.get("schema_version") != SCHEDULER_OFFICIAL_AUTHORITY_SCHEMA_VERSION
        or type(value.get("run_scopes")) is not list
    ):
        _fail("scheduler_official_case_authority_config_invalid")
    return case_run_scopes_from_material(value["run_scopes"])


def _read_sealed_meta(
    handle: SecureOfficialAuthoritySQLite,
    auth: SchedulerOfficialAuthorityAuthenticator,
) -> tuple[dict[str, object], str, SchedulerOfficialCaseAuthorityTerminal]:
    row = handle.connection.execute("SELECT * FROM authority_meta WHERE singleton=1").fetchone()
    if row is None:
        _fail("scheduler_official_case_authority_meta_missing")
    configuration = canonical_mapping(
        row["configuration_json"], code="scheduler_official_case_authority_config_invalid"
    )
    configuration_sha = authority_digest("case/configuration", configuration)
    values = (
        row["singleton"],
        row["schema_version"],
        row["schema_fingerprint_sha256"],
        row["configuration_sha256"],
        row["configuration_json"],
    )
    expected = (
        1,
        SCHEDULER_OFFICIAL_AUTHORITY_SCHEMA_VERSION,
        schema_fingerprint(_SCHEMA),
        configuration_sha,
        canonical_text(configuration),
    )
    if values != expected or not auth.verify(
        "case/configuration", values, row["configuration_mac"]
    ):
        _fail("scheduler_official_case_authority_authentication_invalid")
    terminal = _terminal_from_meta(
        row["terminal_json"],
        row["terminal_mac"],
        auth=auth,
        configuration_sha256=configuration_sha,
    )
    if terminal is None:
        _fail("scheduler_official_case_authority_unsealed")
    return configuration, configuration_sha, terminal


def _terminal_from_meta(
    terminal_json: object,
    terminal_mac: object,
    *,
    auth: SchedulerOfficialAuthorityAuthenticator,
    configuration_sha256: str,
) -> SchedulerOfficialCaseAuthorityTerminal | None:
    if terminal_json is None and terminal_mac is None:
        return None
    payload = canonical_mapping(
        terminal_json, code="scheduler_official_case_authority_terminal_invalid"
    )
    require_exact_keys(
        payload, _TERMINAL_KEYS, code="scheduler_official_case_authority_terminal_invalid"
    )
    terminal = _terminal_from_payload(payload)
    expected_mac_material = {
        "configuration_sha256": configuration_sha256,
        "terminal": payload,
    }
    if not auth.verify("case/meta-terminal", expected_mac_material, terminal_mac):
        _fail("scheduler_official_case_authority_authentication_invalid")
    _verify_terminal_auth(auth, terminal)
    return terminal


def _terminal_from_payload(payload: dict[str, object]) -> SchedulerOfficialCaseAuthorityTerminal:
    if (
        payload.get("authority_kind") != _KIND
        or payload.get("schema_version") != SCHEDULER_OFFICIAL_AUTHORITY_SCHEMA_VERSION
    ):
        _fail("scheduler_official_case_authority_terminal_invalid")
    return SchedulerOfficialCaseAuthorityTerminal(
        schema_fingerprint_sha256=payload["schema_fingerprint_sha256"],
        configuration_sha256=payload["configuration_sha256"],
        case_count=payload["case_count"],
        page_count=payload["page_count"],
        pages_root_sha256=payload["pages_root_sha256"],
        rows_root_sha256=payload["rows_root_sha256"],
        terminal_commitment_sha256=payload["terminal_commitment_sha256"],
        terminal_hmac_sha256=payload["terminal_hmac_sha256"],
        authority_root_sha256=payload["authority_root_sha256"],
    )


def _terminal_payload(terminal: SchedulerOfficialCaseAuthorityTerminal) -> dict[str, object]:
    return {
        **_terminal_body(terminal),
        "authority_root_sha256": terminal.authority_root_sha256,
        "terminal_commitment_sha256": terminal.terminal_commitment_sha256,
        "terminal_hmac_sha256": terminal.terminal_hmac_sha256,
    }


def _terminal_body(terminal: SchedulerOfficialCaseAuthorityTerminal) -> dict[str, object]:
    return {
        "authority_kind": _KIND,
        "case_count": terminal.case_count,
        "configuration_sha256": terminal.configuration_sha256,
        "page_count": terminal.page_count,
        "pages_root_sha256": terminal.pages_root_sha256,
        "rows_root_sha256": terminal.rows_root_sha256,
        "schema_fingerprint_sha256": terminal.schema_fingerprint_sha256,
        "schema_version": SCHEDULER_OFFICIAL_AUTHORITY_SCHEMA_VERSION,
    }


def _build_terminal(
    auth: SchedulerOfficialAuthorityAuthenticator,
    configuration_sha256: str,
    state: tuple[int, int, str, str],
) -> SchedulerOfficialCaseAuthorityTerminal:
    case_count, page_count, pages_root, rows_root = state
    body = {
        "authority_kind": _KIND,
        "case_count": case_count,
        "configuration_sha256": configuration_sha256,
        "page_count": page_count,
        "pages_root_sha256": pages_root,
        "rows_root_sha256": rows_root,
        "schema_fingerprint_sha256": schema_fingerprint(_SCHEMA),
        "schema_version": SCHEDULER_OFFICIAL_AUTHORITY_SCHEMA_VERSION,
    }
    commitment = authority_digest("case/terminal", body)
    terminal_hmac = auth.sign("case/terminal", {"body": body, "commitment": commitment})
    root = auth.sign(
        "case/root",
        {"body": body, "commitment": commitment, "terminal_hmac": terminal_hmac},
    )
    return SchedulerOfficialCaseAuthorityTerminal(
        schema_fingerprint_sha256=body["schema_fingerprint_sha256"],
        configuration_sha256=configuration_sha256,
        case_count=case_count,
        page_count=page_count,
        pages_root_sha256=pages_root,
        rows_root_sha256=rows_root,
        terminal_commitment_sha256=commitment,
        terminal_hmac_sha256=terminal_hmac,
        authority_root_sha256=root,
    )


def _verify_terminal_auth(
    auth: SchedulerOfficialAuthorityAuthenticator,
    terminal: SchedulerOfficialCaseAuthorityTerminal,
) -> None:
    body = _terminal_body(terminal)
    commitment = authority_digest("case/terminal", body)
    if (
        terminal.schema_fingerprint_sha256 != schema_fingerprint(_SCHEMA)
        or terminal.terminal_commitment_sha256 != commitment
        or not auth.verify(
            "case/terminal",
            {"body": body, "commitment": commitment},
            terminal.terminal_hmac_sha256,
        )
        or not auth.verify(
            "case/root",
            {
                "body": body,
                "commitment": commitment,
                "terminal_hmac": terminal.terminal_hmac_sha256,
            },
            terminal.authority_root_sha256,
        )
    ):
        _fail("scheduler_official_case_authority_terminal_authentication_invalid")


def _verify_case_state(
    owner: object,
    *,
    require_complete: bool,
    terminal: SchedulerOfficialCaseAuthorityTerminal | None = None,
) -> tuple[int, int, str, str]:
    connection = owner._handle.connection
    scopes = owner._scopes
    auth = owner._auth
    configuration_sha = owner._configuration_sha256
    validate_schema(connection, _SCHEMA)
    pages_root, page_count = ordered_root(
        "case/pages-root",
        _verified_pages(connection, auth, configuration_sha),
    )
    root = terminal.authority_root_sha256 if terminal is not None else None
    rows_root, case_count = ordered_root(
        "case/rows-root",
        _verified_case_commitments(
            connection, scopes, auth, configuration_sha, authority_root=root
        ),
    )
    expected_count = sum(scope.case_count for scope in scopes)
    if case_count > expected_count or require_complete and case_count != expected_count:
        _fail("scheduler_official_case_authority_coverage_invalid")
    if require_complete:
        _verify_case_manifests(connection, scopes)
    if page_count != _page_count(connection) or case_count != _case_count(connection):
        _fail("scheduler_official_case_authority_coverage_invalid")
    state = (case_count, page_count, pages_root, rows_root)
    if terminal is not None:
        expected = _build_terminal(auth, configuration_sha, state)
        if expected != terminal:
            _fail("scheduler_official_case_authority_root_invalid")
    return state


def _verify_case_manifests(
    connection: sqlite3.Connection,
    scopes: tuple[SchedulerOfficialCaseRunScope, ...],
) -> None:
    for scope in scopes:
        identities = tuple(
            SchedulerCaseAuthority(case_id=row[0], case_alias=row[1])
            for row in connection.execute(
                """SELECT case_id,case_alias FROM official_cases
                   WHERE run_id=? ORDER BY case_index""",
                (scope.run_id,),
            )
        )
        if (
            len(identities) != scope.case_count
            or case_manifest_sha256(identities) != scope.case_manifest_sha256
        ):
            _fail("scheduler_official_case_authority_manifest_coverage_invalid")


def _verified_pages(
    connection: sqlite3.Connection,
    auth: SchedulerOfficialAuthorityAuthenticator,
    configuration_sha: str,
):
    expected_start = 0
    rows = connection.execute("SELECT * FROM authority_pages ORDER BY page_index")
    for expected_page, row in enumerate(rows):
        values = (row["page_index"], row["start_sequence"], row["row_count"], row["page_sha256"])
        _verify_page_row(row, values, auth, configuration_sha)
        if row["page_index"] != expected_page or row["start_sequence"] != expected_start:
            _fail("scheduler_official_case_authority_page_coverage_invalid")
        case_rows = connection.execute(
            """SELECT sequence,row_commitment_sha256 FROM official_cases
               WHERE page_index=? ORDER BY sequence""",
            (expected_page,),
        ).fetchall()
        commitments = [item["row_commitment_sha256"] for item in case_rows]
        observed_sha = authority_digest(
            "case/page",
            {
                "ordered_row_commitments": commitments,
                "page_index": expected_page,
                "start_sequence": expected_start,
            },
        )
        if (
            len(case_rows) != row["row_count"]
            or any(
                item["sequence"] != expected_start + offset for offset, item in enumerate(case_rows)
            )
            or observed_sha != row["page_sha256"]
        ):
            _fail("scheduler_official_case_authority_page_coverage_invalid")
        yield {
            "page_index": expected_page,
            "page_sha256": row["page_sha256"],
            "row_count": row["row_count"],
            "start_sequence": expected_start,
        }
        expected_start += row["row_count"]


def _verified_case_commitments(
    connection: sqlite3.Connection,
    scopes: tuple[SchedulerOfficialCaseRunScope, ...],
    auth: SchedulerOfficialAuthorityAuthenticator,
    configuration_sha: str,
    *,
    authority_root: str | None,
):
    cursor = connection.execute("SELECT * FROM official_cases ORDER BY sequence")
    expected_sequence = 0
    while batch := cursor.fetchmany(256):
        for row in batch:
            if row["sequence"] != expected_sequence:
                _fail("scheduler_official_case_authority_row_coverage_invalid")
            scope, expected_index = _scope_for_sequence(scopes, expected_sequence)
            key = scope.case_key(
                case_index=row["case_index"],
                case_id=row["case_id"],
                case_alias=row["case_alias"],
                authority_root_sha256=authority_root or _DUMMY_ROOT,
            )
            if row["case_index"] != expected_index or row["run_id"] != scope.run_id:
                _fail("scheduler_official_case_authority_row_coverage_invalid")
            _verify_case_storage_row(
                row,
                key=key,
                auth=auth,
                configuration_sha256=configuration_sha,
                sealed=authority_root is not None,
            )
            yield {
                "row_commitment_sha256": row["row_commitment_sha256"],
                "sequence": expected_sequence,
            }
            expected_sequence += 1


def _verified_case_result(
    row: sqlite3.Row,
    *,
    key: SchedulerOfficialCaseKey,
    auth: SchedulerOfficialAuthorityAuthenticator,
    configuration_sha256: str,
) -> SchedulerAuthenticatedOfficialCase:
    case, material = _verify_case_storage_row(
        row, key=key, auth=auth, configuration_sha256=configuration_sha256, sealed=True
    )
    return SchedulerAuthenticatedOfficialCase(key=key, material_sha256=material, case=case)


def _verify_case_storage_row(
    row: sqlite3.Row,
    *,
    key: SchedulerOfficialCaseKey,
    auth: SchedulerOfficialAuthorityAuthenticator,
    configuration_sha256: str,
    sealed: bool,
):
    unrooted = canonical_mapping(
        row["unrooted_key_json"], code="scheduler_official_case_authority_row_invalid"
    )
    case = official_case_from_json(row["case_json"])
    if unrooted != _unrooted_key(key):
        _fail("scheduler_official_case_authority_row_cross_wire")
    commitment = authority_digest(
        "case/unsealed-row",
        {
            "case": canonical_mapping(
                row["case_json"], code="scheduler_official_case_authority_case_json_invalid"
            ),
            "key": unrooted,
            "sequence": row["sequence"],
        },
    )
    values = (
        row["sequence"],
        row["page_index"],
        row["run_id"],
        row["case_index"],
        row["case_id"],
        row["case_alias"],
        row["unrooted_key_json"],
        row["case_json"],
        row["row_commitment_sha256"],
    )
    if (
        row["run_id"] != key.run_id
        or row["case_index"] != key.case_index
        or row["case_id"] != key.case_id
        or row["case_alias"] != key.case_alias
        or row["row_commitment_sha256"] != commitment
        or not auth.verify(
            "case/ingest-row", _ingest_material(configuration_sha256, values), row["ingest_mac"]
        )
    ):
        _fail("scheduler_official_case_authority_row_authentication_invalid")
    official_case_material_sha256(key, case)
    material = official_case_material_sha256(key, case)
    if sealed:
        sealed_material = _sealed_row_material(configuration_sha256, values, material, key)
        if row["material_sha256"] != material or not auth.verify(
            "case/sealed-row", sealed_material, row["sealed_mac"]
        ):
            _fail("scheduler_official_case_authority_row_authentication_invalid")
    elif row["material_sha256"] is not None or row["sealed_mac"] is not None:
        _fail("scheduler_official_case_authority_partial_seal_invalid")
    return case, material


def _seal_case_rows(
    builder: SQLiteSchedulerOfficialCaseAuthorityBuilder, authority_root: str
) -> None:
    connection = builder._handle.connection
    cursor = connection.execute("SELECT * FROM official_cases ORDER BY sequence")
    while batch := cursor.fetchmany(256):
        updates: list[tuple[str, str, int]] = []
        for row in batch:
            scope, _ = _scope_for_sequence(builder._scopes, row["sequence"])
            key = scope.case_key(
                case_index=row["case_index"],
                case_id=row["case_id"],
                case_alias=row["case_alias"],
                authority_root_sha256=authority_root,
            )
            case = official_case_from_json(row["case_json"])
            material = official_case_material_sha256(key, case)
            values = tuple(
                row[name]
                for name in (
                    "sequence",
                    "page_index",
                    "run_id",
                    "case_index",
                    "case_id",
                    "case_alias",
                    "unrooted_key_json",
                    "case_json",
                    "row_commitment_sha256",
                )
            )
            sealed_mac = builder._auth.sign(
                "case/sealed-row",
                _sealed_row_material(builder._configuration_sha256, values, material, key),
            )
            updates.append((material, sealed_mac, row["sequence"]))
        connection.executemany(
            "UPDATE official_cases SET material_sha256=?,sealed_mac=? WHERE sequence=?",
            updates,
        )


def _unrooted_key(key: SchedulerOfficialCaseKey) -> dict[str, object]:
    value = key.material()
    del value["authority_root_sha256"]
    return value


def _scope_for_sequence(
    scopes: tuple[SchedulerOfficialCaseRunScope, ...], sequence: int
) -> tuple[SchedulerOfficialCaseRunScope, int]:
    start = 0
    for scope in scopes:
        if sequence < start + scope.case_count:
            return scope, sequence - start
        start += scope.case_count
    _fail("scheduler_official_case_authority_row_coverage_invalid")


def _fail(code: str) -> None:
    raise SchedulerOfficialAuthorityError(code)


__all__ = (
    "SQLiteSchedulerOfficialCaseAuthorityBuilder",
    "SQLiteSchedulerOfficialCaseAuthorityReader",
    "SQLiteSchedulerOfficialCaseReader",
)

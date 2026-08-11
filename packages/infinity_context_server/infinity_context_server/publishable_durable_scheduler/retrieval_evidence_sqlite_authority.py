"""Streaming HMAC-sealed SQLite authority for exact ranked retrieval evidence."""

from __future__ import annotations

import hmac
import os
import sqlite3
from pathlib import Path
from typing import final

from infinity_context_server.publishable_durable_scheduler.manifest import (
    SchedulerCaseAuthority,
    case_manifest_sha256,
)
from infinity_context_server.publishable_durable_scheduler.official_authority_codec import (
    retrieved_memory_from_json,
    retrieved_memory_json,
)
from infinity_context_server.publishable_durable_scheduler.official_authority_contracts import (
    SCHEDULER_OFFICIAL_AUTHORITY_PAGE_BYTES_LIMIT,
    SchedulerOfficialAuthorityError,
    SchedulerRetrievalEvidenceAuthorityPage,
    SchedulerRetrievalEvidenceAuthorityTerminal,
    SchedulerRetrievalRunScope,
    validate_retrieval_run_scopes,
)
from infinity_context_server.publishable_durable_scheduler.official_authority_integrity import (
    OrderedAuthorityRoot,
    SchedulerOfficialAuthorityAuthenticator,
    authority_digest,
    canonical_mapping,
    canonical_text,
    create_schema,
    immediate_transaction,
    ordered_root,
    require_digest,
    require_int,
    validate_schema,
)
from infinity_context_server.publishable_durable_scheduler.official_authority_sqlite_files import (
    SecureOfficialAuthoritySQLite,
    create_secure_authority_sqlite,
    open_secure_authority_sqlite,
    unlink_created_authority,
)
from infinity_context_server.publishable_durable_scheduler.retrieval_evidence_sqlite_rows import (
    group_count as _group_count,
)
from infinity_context_server.publishable_durable_scheduler.retrieval_evidence_sqlite_rows import (
    group_ingest_material as _group_ingest_material,
)
from infinity_context_server.publishable_durable_scheduler.retrieval_evidence_sqlite_rows import (
    group_sealed_material as _group_sealed_material,
)
from infinity_context_server.publishable_durable_scheduler.retrieval_evidence_sqlite_rows import (
    group_values as _group_values,
)
from infinity_context_server.publishable_durable_scheduler.retrieval_evidence_sqlite_rows import (
    page_count as _page_count,
)
from infinity_context_server.publishable_durable_scheduler.retrieval_evidence_sqlite_rows import (
    page_mac_material as _page_mac_material,
)
from infinity_context_server.publishable_durable_scheduler.retrieval_evidence_sqlite_rows import (
    result_count as _result_count,
)
from infinity_context_server.publishable_durable_scheduler.retrieval_evidence_sqlite_rows import (
    result_ingest_material as _result_ingest_material,
)
from infinity_context_server.publishable_durable_scheduler.retrieval_evidence_sqlite_rows import (
    result_sealed_material as _result_sealed_material,
)
from infinity_context_server.publishable_durable_scheduler.retrieval_evidence_sqlite_rows import (
    result_values as _result_values,
)
from infinity_context_server.publishable_durable_scheduler.retrieval_evidence_sqlite_rows import (
    verify_page_row as _verify_page_row,
)
from infinity_context_server.publishable_durable_scheduler.retrieval_evidence_sqlite_schema import (
    KIND,
    SCHEMA,
    build_terminal,
    configuration,
    meta_values,
    scopes_from_configuration,
    terminal_payload,
    verify_meta,
)
from infinity_context_server.publishable_durable_scheduler.runner_request_composition import (
    SchedulerAuthenticatedRetrievalEvidence,
    SchedulerRetrievalEvidenceKey,
    retrieval_evidence_material_sha256,
)

_DUMMY_ROOT = "0" * 64


@final
class SQLiteSchedulerRetrievalEvidenceAuthorityBuilder:
    """Incrementally write bounded result-group pages, then atomically seal once."""

    __slots__ = (
        "_auth",
        "_case_root",
        "_configuration",
        "_configuration_sha256",
        "_handle",
        "_scopes",
    )

    def __init__(
        self,
        handle: SecureOfficialAuthoritySQLite,
        auth: SchedulerOfficialAuthorityAuthenticator,
        scopes: tuple[SchedulerRetrievalRunScope, ...],
        case_authority_root_sha256: str,
    ) -> None:
        self._handle = handle
        self._auth = auth
        self._scopes = scopes
        self._case_root = case_authority_root_sha256
        self._configuration = configuration(scopes, case_authority_root_sha256)
        self._configuration_sha256 = authority_digest(
            "retrieval/configuration", self._configuration
        )

    @classmethod
    def create(
        cls,
        path: str | os.PathLike[str],
        *,
        run_scopes: tuple[SchedulerRetrievalRunScope, ...],
        case_authority_root_sha256: str,
        authentication_key: bytes,
    ) -> SQLiteSchedulerRetrievalEvidenceAuthorityBuilder:
        scopes = validate_retrieval_run_scopes(run_scopes)
        case_root = require_digest(
            case_authority_root_sha256,
            code="scheduler_retrieval_evidence_authority_case_root_invalid",
        )
        auth = SchedulerOfficialAuthorityAuthenticator(authentication_key, kind=KIND)
        handle = create_secure_authority_sqlite(Path(path))
        builder = cls(handle, auth, scopes, case_root)
        try:
            with immediate_transaction(handle.connection):
                create_schema(handle.connection, SCHEMA)
                values = meta_values(builder._configuration)
                handle.connection.execute(
                    "INSERT INTO authority_meta VALUES(?,?,?,?,?,?,NULL,NULL)",
                    (*values, auth.sign("retrieval/configuration", values)),
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
        run_scopes: tuple[SchedulerRetrievalRunScope, ...],
        case_authority_root_sha256: str,
        authentication_key: bytes,
    ) -> SQLiteSchedulerRetrievalEvidenceAuthorityBuilder:
        scopes = validate_retrieval_run_scopes(run_scopes)
        case_root = require_digest(
            case_authority_root_sha256,
            code="scheduler_retrieval_evidence_authority_case_root_invalid",
        )
        auth = SchedulerOfficialAuthorityAuthenticator(authentication_key, kind=KIND)
        handle = open_secure_authority_sqlite(Path(path), readonly=False)
        builder = cls(handle, auth, scopes, case_root)
        try:
            validate_schema(handle.connection, SCHEMA)
            terminal = builder._verify_meta()
            _verify_retrieval_state(
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
            value = _group_count(self._handle.connection)
            self._handle.verify_bound()
            return value

    def append_page(self, page: SchedulerRetrievalEvidenceAuthorityPage) -> None:
        if type(page) is not SchedulerRetrievalEvidenceAuthorityPage:
            _fail("scheduler_retrieval_evidence_authority_page_invalid")
        page.__post_init__()
        with self._handle.serialized():
            self._handle.verify_bound()
            connection = self._handle.connection
            with immediate_transaction(connection):
                terminal = self._verify_meta()
                existing = connection.execute(
                    "SELECT * FROM authority_pages WHERE page_index=?", (page.page_index,)
                ).fetchone()
                start = _group_count(connection) if existing is None else existing["start_sequence"]
                prepared = self._prepare_page(page, start_sequence=start)
                if existing is not None:
                    _verify_page_row(existing, prepared[0], self._auth, self._configuration_sha256)
                    return
                if terminal is not None:
                    _fail("scheduler_retrieval_evidence_authority_sealed")
                if page.page_index != _page_count(connection) or start != _group_count(connection):
                    _fail("scheduler_retrieval_evidence_authority_page_coverage_invalid")
                page_values, groups = prepared
                connection.execute(
                    "INSERT INTO authority_pages VALUES(?,?,?,?,?,?)",
                    (
                        *page_values,
                        self._auth.sign(
                            "retrieval/page",
                            _page_mac_material(self._configuration_sha256, page_values),
                        ),
                    ),
                )
                for group_values, result_rows in groups:
                    connection.execute(
                        "INSERT INTO retrieval_groups "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,NULL)",
                        (
                            *group_values,
                            self._auth.sign(
                                "retrieval/ingest-group",
                                _group_ingest_material(self._configuration_sha256, group_values),
                            ),
                        ),
                    )
                    connection.executemany(
                        "INSERT INTO retrieval_rows VALUES(?,?,?,?,?,NULL)",
                        (
                            (
                                *row_values,
                                self._auth.sign(
                                    "retrieval/ingest-result-row",
                                    _result_ingest_material(
                                        self._configuration_sha256,
                                        group_values[-1],
                                        row_values,
                                    ),
                                ),
                            )
                            for row_values in result_rows
                        ),
                    )
            self._handle.verify_bound()

    def finalize(
        self, *, expected_authority_root_sha256: str | None = None
    ) -> SchedulerRetrievalEvidenceAuthorityTerminal:
        expected_root = (
            None
            if expected_authority_root_sha256 is None
            else require_digest(
                expected_authority_root_sha256,
                code="scheduler_retrieval_evidence_authority_root_invalid",
            )
        )
        with self._handle.serialized():
            self._handle.verify_bound()
            connection = self._handle.connection
            with immediate_transaction(connection):
                existing = self._verify_meta()
                if existing is not None:
                    _verify_retrieval_state(self, require_complete=True, terminal=existing)
                    if expected_root is not None and not hmac.compare_digest(
                        existing.authority_root_sha256,
                        expected_root,
                    ):
                        _fail("scheduler_retrieval_evidence_authority_root_mismatch")
                    return existing
                state = _verify_retrieval_state(self, require_complete=True)
                terminal = build_terminal(self._auth, self._configuration_sha256, state)
                if expected_root is not None and not hmac.compare_digest(
                    terminal.authority_root_sha256,
                    expected_root,
                ):
                    _fail("scheduler_retrieval_evidence_authority_root_mismatch")
                _seal_groups(self, terminal.authority_root_sha256)
                payload = terminal_payload(terminal)
                terminal_json = canonical_text(payload)
                terminal_mac = self._auth.sign(
                    "retrieval/meta-terminal",
                    {"configuration_sha256": self._configuration_sha256, "terminal": payload},
                )
                cursor = connection.execute(
                    """UPDATE authority_meta SET terminal_json=?,terminal_mac=?
                       WHERE singleton=1 AND terminal_json IS NULL AND terminal_mac IS NULL""",
                    (terminal_json, terminal_mac),
                )
                if cursor.rowcount != 1:
                    _fail("scheduler_retrieval_evidence_authority_seal_race")
                _verify_retrieval_state(self, require_complete=True, terminal=terminal)
            self._handle.verify_bound()
            return terminal

    def close(self) -> None:
        self._handle.close()

    def __enter__(self) -> SQLiteSchedulerRetrievalEvidenceAuthorityBuilder:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _verify_meta(self) -> SchedulerRetrievalEvidenceAuthorityTerminal | None:
        _, configuration_sha, terminal = verify_meta(
            self._handle.connection,
            self._auth,
            expected_configuration=self._configuration,
        )
        if configuration_sha != self._configuration_sha256:
            _fail("scheduler_retrieval_evidence_authority_config_cross_wire")
        return terminal

    def _prepare_page(
        self,
        page: SchedulerRetrievalEvidenceAuthorityPage,
        *,
        start_sequence: object,
    ) -> tuple[
        tuple[object, ...],
        tuple[tuple[tuple[object, ...], tuple[tuple[object, ...], ...]], ...],
    ]:
        start = require_int(
            start_sequence,
            code="scheduler_retrieval_evidence_authority_page_coverage_invalid",
        )
        groups: list[tuple[tuple[object, ...], tuple[tuple[object, ...], ...]]] = []
        commitments: list[str] = []
        encoded_bytes = result_count = 0
        prior_binding = _prior_case_binding(self._handle.connection, start)
        for offset, supplied in enumerate(page.rows):
            sequence = start + offset
            scope, expected_case_index, backend_index = _scope_for_sequence(self._scopes, sequence)
            if supplied.backend_index != backend_index:
                _fail("scheduler_retrieval_evidence_authority_group_coverage_invalid")
            backend = scope.backends[backend_index]
            expected_case_key = scope.case_scope.case_key(
                case_index=expected_case_index,
                case_id=supplied.case_key.case_id,
                case_alias=supplied.case_key.case_alias,
                authority_root_sha256=self._case_root,
            )
            if supplied.case_key != expected_case_key:
                _fail("scheduler_retrieval_evidence_authority_case_cross_wire")
            binding = (canonical_text(supplied.case_key.material()), supplied.case_material_sha256)
            if backend_index == 1 and binding != prior_binding:
                _fail("scheduler_retrieval_evidence_authority_case_pair_invalid")
            prior_binding = binding if backend_index == 0 else None
            dummy_key = SchedulerRetrievalEvidenceKey(
                case_key=supplied.case_key,
                case_material_sha256=supplied.case_material_sha256,
                backend_index=backend_index,
                backend_role=backend.backend_role,
                target_identity_sha256=backend.target_identity_sha256,
                cutoff=scope.cutoff,
                authority_root_sha256=_DUMMY_ROOT,
            )
            retrieval_evidence_material_sha256(dummy_key, supplied.memories)
            unrooted = _unrooted_key(dummy_key)
            result_rows, result_root, byte_count = _prepare_result_rows(sequence, supplied.memories)
            encoded_bytes += len(binding[0].encode()) + len(canonical_text(unrooted).encode())
            encoded_bytes += byte_count
            result_count += len(result_rows)
            group_commitment = authority_digest(
                "retrieval/unsealed-group",
                {
                    "case_key": supplied.case_key.material(),
                    "case_material_sha256": supplied.case_material_sha256,
                    "key": unrooted,
                    "result_count": len(result_rows),
                    "result_rows_root_sha256": result_root,
                    "sequence": sequence,
                },
            )
            group_values = (
                sequence,
                page.page_index,
                supplied.case_key.run_id,
                supplied.case_key.case_index,
                supplied.case_key.case_id,
                supplied.case_key.case_alias,
                backend_index,
                binding[0],
                supplied.case_material_sha256,
                canonical_text(unrooted),
                len(result_rows),
                result_root,
                group_commitment,
            )
            groups.append((group_values, result_rows))
            commitments.append(group_commitment)
        if encoded_bytes > SCHEDULER_OFFICIAL_AUTHORITY_PAGE_BYTES_LIMIT:
            _fail("scheduler_retrieval_evidence_authority_page_too_large")
        page_sha = authority_digest(
            "retrieval/page",
            {
                "ordered_group_commitments": commitments,
                "page_index": page.page_index,
                "start_sequence": start,
            },
        )
        return (page.page_index, start, len(groups), result_count, page_sha), tuple(groups)


@final
class SQLiteSchedulerRetrievalEvidenceReader:
    """Read-only concrete SchedulerRetrievalEvidenceReaderPort implementation."""

    __slots__ = (
        "_auth",
        "_case_root",
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
        scopes: tuple[SchedulerRetrievalRunScope, ...],
        case_root: str,
        configuration_sha256: str,
        terminal: SchedulerRetrievalEvidenceAuthorityTerminal,
    ) -> None:
        self._handle = handle
        self._auth = auth
        self._scopes = scopes
        self._case_root = case_root
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
        case_authority_root_sha256: str,
    ) -> SQLiteSchedulerRetrievalEvidenceReader:
        expected_root = require_digest(
            authority_root_sha256,
            code="scheduler_retrieval_evidence_authority_root_invalid",
        )
        expected_case_root = require_digest(
            case_authority_root_sha256,
            code="scheduler_retrieval_evidence_authority_case_root_invalid",
        )
        auth = SchedulerOfficialAuthorityAuthenticator(authentication_key, kind=KIND)
        handle = open_secure_authority_sqlite(Path(path), readonly=True)
        try:
            validate_schema(handle.connection, SCHEMA)
            raw_config, configuration_sha, terminal = verify_meta(
                handle.connection, auth, expected_configuration=None
            )
            if terminal is None:
                _fail("scheduler_retrieval_evidence_authority_unsealed")
            scopes, case_root = scopes_from_configuration(raw_config)
            if terminal.authority_root_sha256 != expected_root or case_root != expected_case_root:
                _fail("scheduler_retrieval_evidence_authority_root_mismatch")
            reader = cls(handle, auth, scopes, case_root, configuration_sha, terminal)
            _verify_retrieval_state(reader, require_complete=True, terminal=terminal)
            handle.freeze_identity()
            return reader
        except BaseException:
            handle.close(validate=False)
            raise

    @property
    def authority_root_sha256(self) -> str:
        self._handle.verify_stable()
        return self._root

    def read_exact(
        self, *, key: SchedulerRetrievalEvidenceKey
    ) -> SchedulerAuthenticatedRetrievalEvidence:
        if type(key) is not SchedulerRetrievalEvidenceKey:
            _fail("scheduler_retrieval_evidence_authority_lookup_invalid")
        key.__post_init__()
        if (
            key.authority_root_sha256 != self._root
            or key.case_key.authority_root_sha256 != self._case_root
        ):
            _fail("scheduler_retrieval_evidence_authority_lookup_cross_wire")
        with self._handle.serialized():
            self._handle.verify_stable()
            try:
                row = self._handle.connection.execute(
                    """SELECT * FROM retrieval_groups
                       WHERE run_id=? AND case_index=? AND case_id=?
                         AND case_alias=? AND backend_index=?""",
                    (
                        key.case_key.run_id,
                        key.case_key.case_index,
                        key.case_key.case_id,
                        key.case_key.case_alias,
                        key.backend_index,
                    ),
                ).fetchone()
            except sqlite3.DatabaseError as error:
                raise SchedulerOfficialAuthorityError(
                    "scheduler_retrieval_evidence_authority_read_invalid"
                ) from error
            if row is None:
                _fail("scheduler_retrieval_evidence_authority_group_missing")
            _, memories, material = _verify_group_storage(
                self,
                row,
                authority_root=self._root,
                exact_key=key,
            )
            self._handle.verify_stable()
            return SchedulerAuthenticatedRetrievalEvidence(
                key=key, material_sha256=material, memories=memories
            )

    def close(self) -> None:
        self._handle.close()

    def __enter__(self) -> SQLiteSchedulerRetrievalEvidenceReader:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


SQLiteSchedulerRetrievalEvidenceAuthorityReader = SQLiteSchedulerRetrievalEvidenceReader


def _prepare_result_rows(
    group_sequence: int, memories: tuple[object, ...]
) -> tuple[tuple[tuple[object, ...], ...], str, int]:
    rows: list[tuple[object, ...]] = []
    root = OrderedAuthorityRoot("retrieval/group-result-rows")
    byte_count = 0
    for expected_rank, memory in enumerate(memories, start=1):
        memory_json = retrieved_memory_json(memory)
        memory_payload = canonical_mapping(
            memory_json,
            code="scheduler_retrieval_evidence_authority_memory_json_invalid",
        )
        if memory_payload.get("rank") != expected_rank:
            _fail("scheduler_retrieval_evidence_authority_rank_invalid")
        commitment = authority_digest(
            "retrieval/result-row",
            {
                "group_sequence": group_sequence,
                "memory": memory_payload,
                "rank": expected_rank,
            },
        )
        row = (group_sequence, expected_rank, memory_json, commitment)
        rows.append(row)
        root.add({"rank": expected_rank, "row_commitment_sha256": commitment})
        byte_count += len(memory_json.encode())
    return tuple(rows), root.finish(), byte_count


def _verify_retrieval_state(
    owner: object,
    *,
    require_complete: bool,
    terminal: SchedulerRetrievalEvidenceAuthorityTerminal | None = None,
) -> tuple[int, int, int, str, str, str]:
    connection = owner._handle.connection
    validate_schema(connection, SCHEMA)
    pages_root, page_count = ordered_root(
        "retrieval/pages-root",
        _verified_pages(connection, owner._auth, owner._configuration_sha256),
    )
    groups_root = OrderedAuthorityRoot("retrieval/groups-root")
    rows_root = OrderedAuthorityRoot("retrieval/result-rows-root")
    authority_root = terminal.authority_root_sha256 if terminal is not None else None
    prior_binding: tuple[str, str] | None = None
    cursor = connection.execute("SELECT * FROM retrieval_groups ORDER BY sequence")
    expected_sequence = 0
    while batch := cursor.fetchmany(64):
        for row in batch:
            if row["sequence"] != expected_sequence:
                _fail("scheduler_retrieval_evidence_authority_group_coverage_invalid")
            scope, case_index, backend_index = _scope_for_sequence(owner._scopes, expected_sequence)
            if row["case_index"] != case_index or row["backend_index"] != backend_index:
                _fail("scheduler_retrieval_evidence_authority_group_coverage_invalid")
            key, _memories, _material = _verify_group_storage(
                owner, row, authority_root=authority_root
            )
            binding = (canonical_text(key.case_key.material()), key.case_material_sha256)
            if backend_index == 1 and binding != prior_binding:
                _fail("scheduler_retrieval_evidence_authority_case_pair_invalid")
            prior_binding = binding if backend_index == 0 else None
            groups_root.add(
                {
                    "group_commitment_sha256": row["group_commitment_sha256"],
                    "sequence": expected_sequence,
                }
            )
            for result in connection.execute(
                """SELECT rank,row_commitment_sha256 FROM retrieval_rows
                   WHERE group_sequence=? ORDER BY rank""",
                (expected_sequence,),
            ):
                rows_root.add(
                    {
                        "group_sequence": expected_sequence,
                        "rank": result["rank"],
                        "row_commitment_sha256": result["row_commitment_sha256"],
                    }
                )
            expected_sequence += 1
    expected_groups = sum(scope.case_scope.case_count * 2 for scope in owner._scopes)
    if (
        expected_sequence > expected_groups
        or require_complete
        and expected_sequence != expected_groups
        or expected_sequence != _group_count(connection)
        or rows_root.count != _result_count(connection)
        or page_count != _page_count(connection)
    ):
        _fail("scheduler_retrieval_evidence_authority_coverage_invalid")
    if require_complete:
        _verify_case_manifests(connection, owner._scopes)
    state = (
        expected_sequence,
        rows_root.count,
        page_count,
        pages_root,
        groups_root.finish(),
        rows_root.finish(),
    )
    if (
        terminal is not None
        and build_terminal(owner._auth, owner._configuration_sha256, state) != terminal
    ):
        _fail("scheduler_retrieval_evidence_authority_root_invalid")
    return state


def _verify_case_manifests(
    connection: sqlite3.Connection,
    scopes: tuple[SchedulerRetrievalRunScope, ...],
) -> None:
    for scope in scopes:
        identities = tuple(
            SchedulerCaseAuthority(case_id=row[0], case_alias=row[1])
            for row in connection.execute(
                """SELECT case_id,case_alias FROM retrieval_groups
                   WHERE run_id=? AND backend_index=0 ORDER BY case_index""",
                (scope.case_scope.run_id,),
            )
        )
        if (
            len(identities) != scope.case_scope.case_count
            or case_manifest_sha256(identities) != scope.case_scope.case_manifest_sha256
        ):
            _fail("scheduler_retrieval_evidence_authority_manifest_coverage_invalid")


def _verified_pages(
    connection: sqlite3.Connection,
    auth: SchedulerOfficialAuthorityAuthenticator,
    configuration_sha: str,
):
    expected_start = 0
    pages = connection.execute("SELECT * FROM authority_pages ORDER BY page_index")
    for expected_page, row in enumerate(pages):
        values = tuple(
            row[name]
            for name in (
                "page_index",
                "start_sequence",
                "group_count",
                "result_row_count",
                "page_sha256",
            )
        )
        _verify_page_row(row, values, auth, configuration_sha)
        if row["page_index"] != expected_page or row["start_sequence"] != expected_start:
            _fail("scheduler_retrieval_evidence_authority_page_coverage_invalid")
        groups = connection.execute(
            """SELECT sequence,group_commitment_sha256,result_count
               FROM retrieval_groups WHERE page_index=? ORDER BY sequence""",
            (expected_page,),
        ).fetchall()
        commitments = [item["group_commitment_sha256"] for item in groups]
        observed_sha = authority_digest(
            "retrieval/page",
            {
                "ordered_group_commitments": commitments,
                "page_index": expected_page,
                "start_sequence": expected_start,
            },
        )
        if (
            len(groups) != row["group_count"]
            or sum(item["result_count"] for item in groups) != row["result_row_count"]
            or any(
                item["sequence"] != expected_start + offset for offset, item in enumerate(groups)
            )
            or observed_sha != row["page_sha256"]
        ):
            _fail("scheduler_retrieval_evidence_authority_page_coverage_invalid")
        yield {
            "group_count": row["group_count"],
            "page_index": expected_page,
            "page_sha256": row["page_sha256"],
            "result_row_count": row["result_row_count"],
            "start_sequence": expected_start,
        }
        expected_start += row["group_count"]


def _verify_group_storage(
    owner: object,
    row: sqlite3.Row,
    *,
    authority_root: str | None,
    exact_key: SchedulerRetrievalEvidenceKey | None = None,
):
    scope, expected_case_index, expected_backend = _scope_for_sequence(
        owner._scopes, row["sequence"]
    )
    backend = scope.backends[expected_backend]
    case_key = scope.case_scope.case_key(
        case_index=expected_case_index,
        case_id=row["case_id"],
        case_alias=row["case_alias"],
        authority_root_sha256=owner._case_root,
    )
    key = SchedulerRetrievalEvidenceKey(
        case_key=case_key,
        case_material_sha256=row["case_material_sha256"],
        backend_index=expected_backend,
        backend_role=backend.backend_role,
        target_identity_sha256=backend.target_identity_sha256,
        cutoff=scope.cutoff,
        authority_root_sha256=authority_root or _DUMMY_ROOT,
    )
    if exact_key is not None and key != exact_key:
        _fail("scheduler_retrieval_evidence_authority_group_cross_wire")
    case_material = canonical_mapping(
        row["case_key_json"],
        code="scheduler_retrieval_evidence_authority_case_key_invalid",
    )
    unrooted = canonical_mapping(
        row["unrooted_key_json"],
        code="scheduler_retrieval_evidence_authority_key_invalid",
    )
    if case_material != case_key.material() or unrooted != _unrooted_key(key):
        _fail("scheduler_retrieval_evidence_authority_group_cross_wire")
    memories, result_root = _verified_result_rows(owner, row, key, authority_root is not None)
    group_commitment = authority_digest(
        "retrieval/unsealed-group",
        {
            "case_key": case_key.material(),
            "case_material_sha256": key.case_material_sha256,
            "key": unrooted,
            "result_count": len(memories),
            "result_rows_root_sha256": result_root,
            "sequence": row["sequence"],
        },
    )
    values = _group_values(row)
    if (
        row["run_id"] != case_key.run_id
        or row["case_index"] != case_key.case_index
        or row["backend_index"] != expected_backend
        or row["result_count"] != len(memories)
        or row["result_rows_root_sha256"] != result_root
        or row["group_commitment_sha256"] != group_commitment
        or not owner._auth.verify(
            "retrieval/ingest-group",
            _group_ingest_material(owner._configuration_sha256, values),
            row["ingest_mac"],
        )
    ):
        _fail("scheduler_retrieval_evidence_authority_group_authentication_invalid")
    material = retrieval_evidence_material_sha256(key, memories)
    if authority_root is not None:
        if row["material_sha256"] != material or not owner._auth.verify(
            "retrieval/sealed-group",
            _group_sealed_material(owner._configuration_sha256, values, material, key),
            row["sealed_mac"],
        ):
            _fail("scheduler_retrieval_evidence_authority_group_authentication_invalid")
    elif row["material_sha256"] is not None or row["sealed_mac"] is not None:
        _fail("scheduler_retrieval_evidence_authority_partial_seal_invalid")
    return key, memories, material


def _verified_result_rows(owner: object, group: sqlite3.Row, key, sealed: bool):
    rows = owner._handle.connection.execute(
        "SELECT * FROM retrieval_rows WHERE group_sequence=? ORDER BY rank",
        (group["sequence"],),
    ).fetchall()
    if len(rows) > key.cutoff:
        _fail("scheduler_retrieval_evidence_authority_result_count_invalid")
    memories = []
    root = OrderedAuthorityRoot("retrieval/group-result-rows")
    for expected_rank, row in enumerate(rows, start=1):
        memory = retrieved_memory_from_json(row["memory_json"])
        commitment = authority_digest(
            "retrieval/result-row",
            {
                "group_sequence": group["sequence"],
                "memory": canonical_mapping(
                    row["memory_json"],
                    code="scheduler_retrieval_evidence_authority_memory_json_invalid",
                ),
                "rank": expected_rank,
            },
        )
        values = _result_values(row)
        if (
            row["rank"] != expected_rank
            or memory.rank != expected_rank
            or row["row_commitment_sha256"] != commitment
            or not owner._auth.verify(
                "retrieval/ingest-result-row",
                _result_ingest_material(
                    owner._configuration_sha256,
                    group["group_commitment_sha256"],
                    values,
                ),
                row["ingest_mac"],
            )
        ):
            _fail("scheduler_retrieval_evidence_authority_result_authentication_invalid")
        if sealed and not owner._auth.verify(
            "retrieval/sealed-result-row",
            _result_sealed_material(
                owner._configuration_sha256,
                group["group_commitment_sha256"],
                group["material_sha256"],
                values,
                key,
            ),
            row["sealed_mac"],
        ):
            _fail("scheduler_retrieval_evidence_authority_result_authentication_invalid")
        if not sealed and row["sealed_mac"] is not None:
            _fail("scheduler_retrieval_evidence_authority_partial_seal_invalid")
        memories.append(memory)
        root.add({"rank": expected_rank, "row_commitment_sha256": commitment})
    return tuple(memories), root.finish()


def _seal_groups(
    builder: SQLiteSchedulerRetrievalEvidenceAuthorityBuilder, authority_root: str
) -> None:
    connection = builder._handle.connection
    cursor = connection.execute("SELECT * FROM retrieval_groups ORDER BY sequence")
    while batch := cursor.fetchmany(64):
        for group in batch:
            key, memories, material = _verify_group_storage(builder, group, authority_root=None)
            rooted_key = SchedulerRetrievalEvidenceKey(
                case_key=key.case_key,
                case_material_sha256=key.case_material_sha256,
                backend_index=key.backend_index,
                backend_role=key.backend_role,
                target_identity_sha256=key.target_identity_sha256,
                cutoff=key.cutoff,
                authority_root_sha256=authority_root,
            )
            material = retrieval_evidence_material_sha256(rooted_key, memories)
            values = _group_values(group)
            group_mac = builder._auth.sign(
                "retrieval/sealed-group",
                _group_sealed_material(builder._configuration_sha256, values, material, rooted_key),
            )
            connection.execute(
                "UPDATE retrieval_groups SET material_sha256=?,sealed_mac=? WHERE sequence=?",
                (material, group_mac, group["sequence"]),
            )
            rows = connection.execute(
                "SELECT * FROM retrieval_rows WHERE group_sequence=? ORDER BY rank",
                (group["sequence"],),
            ).fetchall()
            updates = [
                (
                    builder._auth.sign(
                        "retrieval/sealed-result-row",
                        _result_sealed_material(
                            builder._configuration_sha256,
                            group["group_commitment_sha256"],
                            material,
                            _result_values(row),
                            rooted_key,
                        ),
                    ),
                    group["sequence"],
                    row["rank"],
                )
                for row in rows
            ]
            connection.executemany(
                """UPDATE retrieval_rows SET sealed_mac=?
                   WHERE group_sequence=? AND rank=?""",
                updates,
            )


def _scope_for_sequence(
    scopes: tuple[SchedulerRetrievalRunScope, ...], sequence: int
) -> tuple[SchedulerRetrievalRunScope, int, int]:
    start = 0
    for scope in scopes:
        count = scope.case_scope.case_count * 2
        if sequence < start + count:
            relative = sequence - start
            return scope, relative // 2, relative % 2
        start += count
    _fail("scheduler_retrieval_evidence_authority_group_coverage_invalid")


def _prior_case_binding(connection: sqlite3.Connection, start: int) -> tuple[str, str] | None:
    if start == 0:
        return None
    row = connection.execute(
        """SELECT backend_index,case_key_json,case_material_sha256
           FROM retrieval_groups WHERE sequence=?""",
        (start - 1,),
    ).fetchone()
    if row is None:
        _fail("scheduler_retrieval_evidence_authority_group_coverage_invalid")
    if row["backend_index"] == 0:
        return row["case_key_json"], row["case_material_sha256"]
    return None


def _unrooted_key(key: SchedulerRetrievalEvidenceKey) -> dict[str, object]:
    value = key.material()
    del value["authority_root_sha256"]
    return value


def _fail(code: str) -> None:
    raise SchedulerOfficialAuthorityError(code)


__all__ = (
    "SQLiteSchedulerRetrievalEvidenceAuthorityBuilder",
    "SQLiteSchedulerRetrievalEvidenceAuthorityReader",
    "SQLiteSchedulerRetrievalEvidenceReader",
)

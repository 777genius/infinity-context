"""HMAC-authenticated SQLite ledger for the exact fresh-chain five-call plan."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import stat
from collections.abc import Iterator, Mapping
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Final, final

from .ledger_head_anchor import FreshChainLedgerHeadAnchor
from .ledger_models import (
    FreshChainFailureDisposition,
    FreshChainLedgerError,
    FreshChainPlan,
    FreshChainSnapshot,
    FreshChainStage,
    TokenUsage,
    canonical_json,
    canonical_sha256,
    fresh_chain_dispatch_started_sha256,
    fresh_chain_failed_terminal_outcome_sha256,
    normalize_commitments,
    require_failure_disposition,
    require_identifier,
    require_sha256,
    require_stage,
)
from .ledger_policy import FreshChainLedgerPolicy, FreshChainProjection

_SCHEMA_VERSION: Final = "infinity-context-fresh-chain-ledger-sqlite.v1"
_GENESIS_DOMAIN: Final = "infinity-context-fresh-chain-ledger-genesis/v1"
_EVENT_DOMAIN: Final = "infinity-context-fresh-chain-ledger-event/v1"
_HEAD_DOMAIN: Final = "infinity-context-fresh-chain-ledger-head/v1"
_META_DOMAIN: Final = "infinity-context-fresh-chain-ledger-meta/v1"
_SCHEMA_DOMAIN: Final = "infinity-context-fresh-chain-ledger-schema/v1"

_CREATE_META = """CREATE TABLE fresh_chain_meta (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    schema_version TEXT NOT NULL,
    structural_fingerprint_sha256 TEXT NOT NULL,
    schema_hmac_sha256 TEXT NOT NULL,
    plan_json TEXT NOT NULL,
    plan_commitment_sha256 TEXT NOT NULL,
    row_hmac_sha256 TEXT NOT NULL
)"""
_CREATE_EVENTS = """CREATE TABLE fresh_chain_events (
    sequence INTEGER PRIMARY KEY CHECK (sequence > 0),
    event_kind TEXT NOT NULL,
    stage TEXT,
    payload_json TEXT NOT NULL,
    previous_event_hmac TEXT NOT NULL,
    event_hmac TEXT NOT NULL
)"""
_CREATE_HEAD = """CREATE TABLE fresh_chain_head (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    event_count INTEGER NOT NULL CHECK (event_count >= 0),
    event_head_hmac TEXT NOT NULL,
    state_sha256 TEXT NOT NULL,
    row_hmac_sha256 TEXT NOT NULL
)"""
_CREATE_STATEMENTS: Final = (_CREATE_META, _CREATE_EVENTS, _CREATE_HEAD)


def _normalize_sql(value: str) -> str:
    return " ".join(value.split())


_EXPECTED_TABLES: Final = {
    "fresh_chain_events": _normalize_sql(_CREATE_EVENTS),
    "fresh_chain_head": _normalize_sql(_CREATE_HEAD),
    "fresh_chain_meta": _normalize_sql(_CREATE_META),
}
_STRUCTURAL_FINGERPRINT: Final = hashlib.sha256(
    canonical_json(_EXPECTED_TABLES).encode("ascii")
).hexdigest()


@final
class FreshChainCanaryLedger:
    """One private append-only ledger sealed with an operator-local HMAC key."""

    __slots__ = ("_anchor", "_authentication_secret", "_identity", "_path", "_plan", "_policy")

    def __init__(
        self,
        path: Path,
        *,
        authentication_secret: bytes,
        plan: FreshChainPlan,
        require_existing: bool = False,
    ) -> None:
        if (
            not isinstance(path, Path)
            or not path.is_absolute()
            or path.name in {"", ".", ".."}
            or type(authentication_secret) is not bytes
            or len(authentication_secret) < 32
            or type(plan) is not FreshChainPlan
            or type(require_existing) is not bool
        ):
            _fail("fresh_chain_ledger_input_invalid")
        self._path = path
        self._authentication_secret = bytes(authentication_secret)
        self._plan = plan
        self._policy = FreshChainLedgerPolicy(plan)
        newly_created, self._identity = self._prepare_private_storage(
            require_existing=require_existing
        )
        self._anchor = FreshChainLedgerHeadAnchor(
            path,
            key=self._authentication_secret,
            identity=self._identity,
        )
        try:
            with self._connection() as connection:
                if newly_created:
                    self._initialize(connection)
                    projection, count, head = self._load_verified(connection)
                else:
                    connection.execute("BEGIN")
                    try:
                        projection, count, head = self._load_verified(connection)
                    except BaseException:
                        _rollback(connection)
                        raise
                    else:
                        connection.execute("COMMIT")
                self._anchor.synchronize(connection, count=count, head=head)
        except FreshChainLedgerError:
            raise
        except (OSError, sqlite3.Error):
            _fail("fresh_chain_ledger_unavailable")

    @classmethod
    def open(
        cls,
        path: Path,
        *,
        authentication_secret: bytes,
        plan: FreshChainPlan,
        require_existing: bool = False,
    ) -> FreshChainCanaryLedger:
        return cls(
            path,
            authentication_secret=authentication_secret,
            plan=plan,
            require_existing=require_existing,
        )

    @property
    def path(self) -> Path:
        return self._path

    @property
    def plan(self) -> FreshChainPlan:
        return self._plan

    def read_snapshot(self) -> FreshChainSnapshot:
        try:
            with self._connection() as connection:
                connection.execute("BEGIN")
                try:
                    projection, count, head = self._load_verified(connection)
                except BaseException:
                    _rollback(connection)
                    raise
                else:
                    connection.execute("COMMIT")
            return self._snapshot(projection, count, head)
        except FreshChainLedgerError:
            raise
        except (OSError, sqlite3.Error):
            _fail("fresh_chain_ledger_unavailable")

    def verify(self) -> None:
        self.read_snapshot()

    def record_source_projection_bound(
        self,
        *,
        source_projection_commitment_sha256: str,
    ) -> FreshChainSnapshot:
        """Bind the concrete extracted source projection before any call intent."""

        return self._append(
            "source_projection_bound",
            None,
            {
                "namespace_commitment_sha256": (self._plan.namespace_commitment_sha256),
                "source_commitment_sha256": self._plan.source_commitment_sha256,
                "source_projection_commitment_sha256": require_sha256(
                    source_projection_commitment_sha256
                ),
                "publishable": False,
            },
        )

    def record_intent(
        self,
        stage: FreshChainStage | str,
        *,
        intent_sha256: str,
        request_sha256: str,
        input_authority_sha256: str,
        commitments: Mapping[str, str] | tuple[tuple[str, str], ...] = (),
    ) -> FreshChainSnapshot:
        return self._append(
            "intent",
            require_stage(stage),
            {
                "stage": require_stage(stage),
                "intent_sha256": require_sha256(intent_sha256),
                "request_sha256": require_sha256(request_sha256),
                "input_authority_sha256": require_sha256(input_authority_sha256),
                "commitments": dict(normalize_commitments(commitments)),
                "publishable": False,
            },
        )

    def record_authenticated_pre_call_absence(
        self,
        stage: FreshChainStage | str,
        *,
        intent_sha256: str,
        absence_sha256: str,
    ) -> FreshChainSnapshot:
        """Bind authenticated absence; only this immediate caller may then dispatch."""

        return self._append(
            "authenticated_pre_call_absence",
            require_stage(stage),
            {
                "stage": require_stage(stage),
                "intent_sha256": require_sha256(intent_sha256),
                "absence_sha256": require_sha256(absence_sha256),
            },
        )

    def record_ambiguous_outcome(
        self,
        stage: FreshChainStage | str,
        *,
        intent_sha256: str,
        ambiguity_sha256: str,
    ) -> FreshChainSnapshot:
        return self._append(
            "ambiguous_outcome",
            require_stage(stage),
            {
                "stage": require_stage(stage),
                "intent_sha256": require_sha256(intent_sha256),
                "ambiguity_sha256": require_sha256(ambiguity_sha256),
            },
        )

    def record_dispatch_started(
        self,
        stage: FreshChainStage | str,
        *,
        intent_sha256: str,
        authenticated_absence_sha256: str,
    ) -> FreshChainSnapshot:
        """Durably cross the boundary after which dispatch may only be recovered."""

        selected = require_stage(stage)
        intent = require_sha256(intent_sha256)
        absence = require_sha256(authenticated_absence_sha256)
        dispatch_started = fresh_chain_dispatch_started_sha256(
            stage=selected,
            intent_sha256=intent,
            authenticated_absence_sha256=absence,
        )
        return self._append(
            "dispatch_started",
            selected,
            {
                "stage": selected,
                "intent_sha256": intent,
                "authenticated_absence_sha256": absence,
                "dispatch_started_sha256": dispatch_started,
            },
        )

    def record_success(
        self,
        stage: FreshChainStage | str,
        *,
        intent_sha256: str,
        result_sha256: str,
        receipt_id: str,
        receipt_sha256: str,
        token_usage: TokenUsage,
        commitments: Mapping[str, str] | tuple[tuple[str, str], ...] = (),
    ) -> FreshChainSnapshot:
        return self._record_result(
            "success",
            stage,
            intent_sha256=intent_sha256,
            result_sha256=result_sha256,
            receipt_id=receipt_id,
            receipt_sha256=receipt_sha256,
            token_usage=token_usage,
            commitments=commitments,
        )

    def record_failure(
        self,
        stage: FreshChainStage | str,
        *,
        intent_sha256: str,
        failure_sha256: str,
        receipt_id: str,
        receipt_sha256: str,
        token_usage: TokenUsage,
        provider_disposition: FreshChainFailureDisposition | str,
        commitments: Mapping[str, str] | tuple[tuple[str, str], ...] = (),
    ) -> FreshChainSnapshot:
        return self._record_result(
            "failure",
            stage,
            intent_sha256=intent_sha256,
            result_sha256=failure_sha256,
            receipt_id=receipt_id,
            receipt_sha256=receipt_sha256,
            token_usage=token_usage,
            provider_disposition=provider_disposition,
            commitments=commitments,
        )

    def record_retrieval_handoff(
        self,
        *,
        extraction_result_sha256: str,
        extraction_receipt_sha256: str,
        namespace_commitment_sha256: str,
        memory_authority_sha256: str,
        retrieval_authority_sha256: str,
        memory_count: int,
        commitments: Mapping[str, str] | tuple[tuple[str, str], ...] = (),
    ) -> FreshChainSnapshot:
        return self._append(
            "retrieval_handoff",
            None,
            {
                "extraction_result_sha256": require_sha256(extraction_result_sha256),
                "extraction_receipt_sha256": require_sha256(extraction_receipt_sha256),
                "namespace_commitment_sha256": require_sha256(namespace_commitment_sha256),
                "memory_authority_sha256": require_sha256(memory_authority_sha256),
                "retrieval_authority_sha256": require_sha256(retrieval_authority_sha256),
                "memory_count": memory_count,
                "commitments": dict(normalize_commitments(commitments)),
                "publishable": False,
            },
        )

    def record_cleanup(
        self,
        *,
        namespace_commitment_sha256: str,
        cleanup_authority_sha256: str,
        receipt_id: str,
        receipt_sha256: str,
        outcome_sha256: str,
        deleted: bool,
        operation_count: int,
        residual_count: int,
    ) -> FreshChainSnapshot:
        return self._append(
            "cleanup",
            None,
            {
                "namespace_commitment_sha256": require_sha256(namespace_commitment_sha256),
                "cleanup_authority_sha256": require_sha256(cleanup_authority_sha256),
                "receipt_id": require_identifier(receipt_id),
                "receipt_sha256": require_sha256(receipt_sha256),
                "outcome_sha256": require_sha256(outcome_sha256),
                "deleted": deleted,
                "operation_count": operation_count,
                "residual_count": residual_count,
                "publishable": False,
            },
        )

    def record_local_abort(self, *, reason_sha256: str) -> FreshChainSnapshot:
        return self._append(
            "local_abort",
            None,
            {"reason_sha256": require_sha256(reason_sha256), "publishable": False},
        )

    def complete(self, *, outcome_sha256: str) -> FreshChainSnapshot:
        return self._terminal("succeeded", outcome_sha256)

    def terminate_failed(self, *, outcome_sha256: str | None = None) -> FreshChainSnapshot:
        snapshot = self.read_snapshot()
        if snapshot.cleanup is None:
            _fail("fresh_chain_failed_terminal_invalid")
        expected = fresh_chain_failed_terminal_outcome_sha256(
            plan=snapshot.plan,
            source_projection_commitment_sha256=require_sha256(
                snapshot.source_projection_commitment_sha256
            ),
            stages=snapshot.stages,
            retrieval_handoff=snapshot.retrieval_handoff,
            abort_reason_sha256=snapshot.abort_reason_sha256,
            cleanup=snapshot.cleanup,
        )
        selected = expected if outcome_sha256 is None else require_sha256(outcome_sha256)
        return self._terminal("failed", selected)

    def _terminal(self, status: str, outcome_sha256: str) -> FreshChainSnapshot:
        return self._append(
            "terminal_outcome",
            None,
            {
                "status": status,
                "outcome_sha256": require_sha256(outcome_sha256),
                "activation_evidence_only": True,
                "publishable": False,
            },
        )

    def _record_result(
        self,
        kind: str,
        stage: FreshChainStage | str,
        *,
        intent_sha256: str,
        result_sha256: str,
        receipt_id: str,
        receipt_sha256: str,
        token_usage: TokenUsage,
        commitments: Mapping[str, str] | tuple[tuple[str, str], ...],
        provider_disposition: FreshChainFailureDisposition | str | None = None,
    ) -> FreshChainSnapshot:
        if type(token_usage) is not TokenUsage:
            _fail("fresh_chain_token_usage_invalid")
        selected = require_stage(stage)
        payload: dict[str, object] = {
            "stage": selected,
            "intent_sha256": require_sha256(intent_sha256),
            "result_sha256" if kind == "success" else "failure_sha256": require_sha256(
                result_sha256
            ),
            "receipt_id": require_identifier(receipt_id),
            "receipt_sha256": require_sha256(receipt_sha256),
            "token_usage": token_usage.material(),
            "commitments": dict(normalize_commitments(commitments)),
            "result_publishable": False,
            "receipt_publishable": False,
        }
        if kind == "failure":
            payload["provider_disposition"] = require_failure_disposition(
                provider_disposition
            ).value
        elif kind != "success" or provider_disposition is not None:
            _fail("fresh_chain_result_kind_invalid")
        return self._append(kind, selected, payload)

    def _append(
        self,
        event_kind: str,
        stage: FreshChainStage | None,
        payload: dict[str, object],
    ) -> FreshChainSnapshot:
        try:
            with self._connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    projection, count, head = self._load_verified(connection)
                    next_projection = projection.copy()
                    self._policy.apply_event(next_projection, event_kind, stage, payload)
                    sequence = count + 1
                    payload_json = canonical_json(payload)
                    event_hmac = self._event_hmac(sequence, event_kind, stage, payload_json, head)
                    connection.execute(
                        """INSERT INTO fresh_chain_events
                           (sequence, event_kind, stage, payload_json,
                            previous_event_hmac, event_hmac)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (sequence, event_kind, stage, payload_json, head, event_hmac),
                    )
                    state_sha256 = self._state_sha256(next_projection)
                    row_hmac = self._head_hmac(sequence, event_hmac, state_sha256)
                    changed = connection.execute(
                        """UPDATE fresh_chain_head
                           SET event_count = ?, event_head_hmac = ?, state_sha256 = ?,
                               row_hmac_sha256 = ? WHERE singleton = 1""",
                        (sequence, event_hmac, state_sha256, row_hmac),
                    ).rowcount
                    if changed != 1:
                        _fail("fresh_chain_ledger_corrupt")
                    self._load_verified(connection)
                except BaseException:
                    connection.execute("ROLLBACK")
                    raise
                else:
                    connection.execute("COMMIT")
            self._anchor.write(count=sequence, head=event_hmac)
            return self._snapshot(next_projection, sequence, event_hmac)
        except FreshChainLedgerError:
            raise
        except (OSError, sqlite3.Error):
            _fail("fresh_chain_ledger_unavailable")

    def _initialize(self, connection: sqlite3.Connection) -> None:
        connection.execute("BEGIN IMMEDIATE")
        try:
            for statement in _CREATE_STATEMENTS:
                connection.execute(statement)
            plan_json = canonical_json(self._plan.material())
            schema_hmac = self._schema_hmac()
            connection.execute(
                """INSERT INTO fresh_chain_meta
                   (singleton, schema_version, structural_fingerprint_sha256,
                    schema_hmac_sha256, plan_json, plan_commitment_sha256,
                    row_hmac_sha256) VALUES (1, ?, ?, ?, ?, ?, ?)""",
                (
                    _SCHEMA_VERSION,
                    _STRUCTURAL_FINGERPRINT,
                    schema_hmac,
                    plan_json,
                    self._plan.commitment_sha256,
                    self._meta_hmac(plan_json, self._plan.commitment_sha256, schema_hmac),
                ),
            )
            projection = FreshChainProjection.initial()
            genesis = self._genesis_hmac()
            state_sha256 = self._state_sha256(projection)
            connection.execute(
                """INSERT INTO fresh_chain_head
                   (singleton, event_count, event_head_hmac, state_sha256, row_hmac_sha256)
                   VALUES (1, 0, ?, ?, ?)""",
                (genesis, state_sha256, self._head_hmac(0, genesis, state_sha256)),
            )
            self._load_verified(connection)
        except BaseException:
            _rollback(connection)
            raise
        else:
            connection.execute("COMMIT")

    def _load_verified(
        self, connection: sqlite3.Connection
    ) -> tuple[FreshChainProjection, int, str]:
        try:
            self._verify_schema(connection)
            self._verify_meta(connection)
            projection = FreshChainProjection.initial()
            previous = self._genesis_hmac()
            rows = connection.execute(
                """SELECT sequence, event_kind, stage, payload_json,
                          previous_event_hmac, event_hmac
                   FROM fresh_chain_events ORDER BY sequence"""
            ).fetchall()
            for expected_sequence, row in enumerate(rows, start=1):
                if (
                    len(row) != 6
                    or type(row[0]) is not int
                    or row[0] != expected_sequence
                    or type(row[1]) is not str
                    or (row[2] is not None and type(row[2]) is not str)
                    or type(row[3]) is not str
                    or type(row[4]) is not str
                    or type(row[5]) is not str
                    or row[4] != previous
                    or not hmac.compare_digest(
                        row[5], self._event_hmac(row[0], row[1], row[2], row[3], row[4])
                    )
                ):
                    _fail("fresh_chain_ledger_corrupt")
                try:
                    payload = json.loads(row[3])
                except (TypeError, ValueError):
                    _fail("fresh_chain_ledger_corrupt")
                if type(payload) is not dict or canonical_json(payload) != row[3]:
                    _fail("fresh_chain_ledger_corrupt")
                self._policy.apply_event(projection, row[1], row[2], payload)
                previous = row[5]
            head_rows = connection.execute(
                """SELECT event_count, event_head_hmac, state_sha256, row_hmac_sha256
                   FROM fresh_chain_head WHERE singleton = 1"""
            ).fetchall()
            if len(head_rows) != 1:
                _fail("fresh_chain_ledger_corrupt")
            event_count, event_head, state_sha256, row_hmac = head_rows[0]
            if (
                type(event_count) is not int
                or event_count != len(rows)
                or type(event_head) is not str
                or event_head != previous
                or type(state_sha256) is not str
                or state_sha256 != self._state_sha256(projection)
                or type(row_hmac) is not str
                or not hmac.compare_digest(
                    row_hmac, self._head_hmac(event_count, event_head, state_sha256)
                )
            ):
                _fail("fresh_chain_ledger_corrupt")
            return projection, event_count, event_head
        except FreshChainLedgerError as error:
            if error.code == "fresh_chain_ledger_replay_conflict":
                raise
            _fail("fresh_chain_ledger_corrupt")
        except (KeyError, TypeError, ValueError, sqlite3.Error):
            _fail("fresh_chain_ledger_corrupt")

    def _verify_schema(self, connection: sqlite3.Connection) -> None:
        rows = connection.execute(
            "SELECT type, name, sql FROM sqlite_master ORDER BY type, name"
        ).fetchall()
        tables = {
            name: _normalize_sql(str(sql))
            for kind, name, sql in rows
            if kind == "table" and not str(name).startswith("sqlite_")
        }
        unexpected = [
            (kind, name)
            for kind, name, sql in rows
            if kind in {"trigger", "view"} or (kind == "index" and sql is not None)
        ]
        if tables != _EXPECTED_TABLES or unexpected:
            _fail("fresh_chain_ledger_corrupt")

    def _verify_meta(self, connection: sqlite3.Connection) -> None:
        rows = connection.execute(
            """SELECT schema_version, structural_fingerprint_sha256,
                      schema_hmac_sha256, plan_json, plan_commitment_sha256,
                      row_hmac_sha256 FROM fresh_chain_meta WHERE singleton = 1"""
        ).fetchall()
        if len(rows) != 1 or len(rows[0]) != 6 or any(type(value) is not str for value in rows[0]):
            _fail("fresh_chain_ledger_corrupt")
        schema_version, fingerprint, schema_hmac, plan_json, plan_sha256, row_hmac = rows[0]
        expected_schema_hmac = self._schema_hmac()
        try:
            decoded_plan = json.loads(plan_json)
        except (TypeError, ValueError):
            _fail("fresh_chain_ledger_corrupt")
        if (
            schema_version != _SCHEMA_VERSION
            or fingerprint != _STRUCTURAL_FINGERPRINT
            or not hmac.compare_digest(schema_hmac, expected_schema_hmac)
            or canonical_json(decoded_plan) != plan_json
            or canonical_sha256(decoded_plan) != plan_sha256
            or not hmac.compare_digest(
                row_hmac, self._meta_hmac(plan_json, plan_sha256, schema_hmac)
            )
        ):
            _fail("fresh_chain_ledger_corrupt")
        if (
            plan_json != canonical_json(self._plan.material())
            or plan_sha256 != self._plan.commitment_sha256
        ):
            _fail("fresh_chain_ledger_replay_conflict")

    def _snapshot(
        self, projection: FreshChainProjection, event_count: int, event_head: str
    ) -> FreshChainSnapshot:
        return FreshChainSnapshot(
            plan=self._plan,
            source_projection_commitment_sha256=(projection.source_projection_commitment_sha256),
            stages=tuple(projection.stages),
            retrieval_handoff=projection.retrieval_handoff,
            abort_reason_sha256=projection.abort_reason_sha256,
            cleanup=projection.cleanup,
            terminal_outcome=projection.terminal_outcome,
            event_count=event_count,
            event_head_hmac=event_head,
        )

    def _state_sha256(self, projection: FreshChainProjection) -> str:
        return canonical_sha256(
            {
                "plan_commitment_sha256": self._plan.commitment_sha256,
                "source_projection_commitment_sha256": (
                    projection.source_projection_commitment_sha256
                ),
                "stages": [record.material() for record in projection.stages],
                "retrieval_handoff": (
                    None
                    if projection.retrieval_handoff is None
                    else projection.retrieval_handoff.material()
                ),
                "abort_reason_sha256": projection.abort_reason_sha256,
                "cleanup": None if projection.cleanup is None else projection.cleanup.material(),
                "terminal_outcome": (
                    None
                    if projection.terminal_outcome is None
                    else projection.terminal_outcome.material()
                ),
            }
        )

    def _schema_hmac(self) -> str:
        return self._mac(
            {
                "domain": _SCHEMA_DOMAIN,
                "schema_version": _SCHEMA_VERSION,
                "structural_fingerprint_sha256": _STRUCTURAL_FINGERPRINT,
            }
        )

    def _meta_hmac(self, plan_json: str, plan_sha256: str, schema_hmac: str) -> str:
        return self._mac(
            {
                "domain": _META_DOMAIN,
                "plan_json": plan_json,
                "plan_commitment_sha256": plan_sha256,
                "schema_hmac_sha256": schema_hmac,
                "schema_version": _SCHEMA_VERSION,
                "structural_fingerprint_sha256": _STRUCTURAL_FINGERPRINT,
            }
        )

    def _genesis_hmac(self) -> str:
        return self._mac(
            {"domain": _GENESIS_DOMAIN, "plan_commitment_sha256": self._plan.commitment_sha256}
        )

    def _event_hmac(
        self,
        sequence: int,
        event_kind: str,
        stage: str | None,
        payload_json: str,
        previous_event_hmac: str,
    ) -> str:
        return self._mac(
            {
                "domain": _EVENT_DOMAIN,
                "plan_commitment_sha256": self._plan.commitment_sha256,
                "sequence": sequence,
                "event_kind": event_kind,
                "stage": stage,
                "payload_json": payload_json,
                "previous_event_hmac": previous_event_hmac,
            }
        )

    def _head_hmac(self, count: int, event_head: str, state_sha256: str) -> str:
        return self._mac(
            {
                "domain": _HEAD_DOMAIN,
                "plan_commitment_sha256": self._plan.commitment_sha256,
                "event_count": count,
                "event_head_hmac": event_head,
                "state_sha256": state_sha256,
            }
        )

    def _mac(self, payload: dict[str, object]) -> str:
        return hmac.new(
            self._authentication_secret,
            canonical_json(payload).encode("ascii"),
            hashlib.sha256,
        ).hexdigest()

    def _prepare_private_storage(self, *, require_existing: bool) -> tuple[bool, tuple[int, int]]:
        directory = self._path.parent
        try:
            if not os.path.lexists(directory):
                if require_existing:
                    _fail("fresh_chain_ledger_missing")
                directory.mkdir(mode=0o700, parents=True)
            _require_private_directory(directory)
            self._assert_surfaces()
            newly_created = not os.path.lexists(self._path)
            if newly_created:
                if require_existing:
                    _fail("fresh_chain_ledger_missing")
                directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                try:
                    descriptor = os.open(
                        self._path.name,
                        os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                        0o600,
                        dir_fd=directory_fd,
                    )
                    os.close(descriptor)
                finally:
                    os.close(directory_fd)
            identity = _open_verified_identity(self._path)
            return newly_created, identity
        except FreshChainLedgerError:
            raise
        except OSError:
            _fail("fresh_chain_ledger_unavailable")

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        _require_private_directory(self._path.parent)
        self._assert_surfaces()
        _require_private_file(self._path, expected_identity=self._identity)
        connection: sqlite3.Connection | None = None
        descriptor: int | None = None
        try:
            descriptor = os.open(
                self._path,
                os.O_RDWR | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
            )
            opened = os.fstat(descriptor)
            if (opened.st_dev, opened.st_ino) != self._identity:
                _fail("fresh_chain_ledger_private_storage_invalid")
            connection = sqlite3.connect(
                f"file:/proc/self/fd/{descriptor}?mode=rw",
                uri=True,
                isolation_level=None,
                timeout=10.0,
                check_same_thread=False,
            )
            _require_private_file(self._path, expected_identity=self._identity)
            connection.execute("PRAGMA trusted_schema = OFF")
            mode = connection.execute("PRAGMA journal_mode = DELETE").fetchone()
            if mode is None or str(mode[0]).lower() != "delete":
                _fail("fresh_chain_ledger_unavailable")
            connection.execute("PRAGMA synchronous = FULL")
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 10000")
            yield connection
        finally:
            if connection is not None:
                connection.close()
            if descriptor is not None:
                os.close(descriptor)
            _require_private_file(self._path, expected_identity=self._identity)
            self._assert_surfaces()

    def _assert_surfaces(self) -> None:
        for surface in (
            self._path,
            Path(f"{self._path}-journal"),
            Path(f"{self._path}-wal"),
            Path(f"{self._path}-shm"),
        ):
            if os.path.lexists(surface):
                _require_private_file(surface)


def _require_private_directory(path: Path) -> None:
    try:
        information = os.lstat(path)
    except OSError:
        _fail("fresh_chain_ledger_unavailable")
    if (
        stat.S_ISLNK(information.st_mode)
        or not stat.S_ISDIR(information.st_mode)
        or information.st_uid != os.geteuid()
        or stat.S_IMODE(information.st_mode) != 0o700
    ):
        _fail("fresh_chain_ledger_private_storage_invalid")


def _require_private_file(path: Path, *, expected_identity: tuple[int, int] | None = None) -> None:
    try:
        information = os.lstat(path)
    except OSError:
        _fail("fresh_chain_ledger_unavailable")
    if (
        stat.S_ISLNK(information.st_mode)
        or not stat.S_ISREG(information.st_mode)
        or information.st_uid != os.geteuid()
        or stat.S_IMODE(information.st_mode) != 0o600
        or information.st_nlink != 1
        or (
            expected_identity is not None
            and (information.st_dev, information.st_ino) != expected_identity
        )
    ):
        _fail("fresh_chain_ledger_private_storage_invalid")


def _open_verified_identity(path: Path) -> tuple[int, int]:
    descriptor: int | None = None
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
        )
        opened = os.fstat(descriptor)
        _require_private_file(path)
        named = os.lstat(path)
        if (
            (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
            or opened.st_nlink != 1
            or not stat.S_ISREG(opened.st_mode)
        ):
            _fail("fresh_chain_ledger_private_storage_invalid")
        return opened.st_dev, opened.st_ino
    except FreshChainLedgerError:
        raise
    except OSError:
        _fail("fresh_chain_ledger_unavailable")
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _rollback(connection: sqlite3.Connection) -> None:
    """Close-time rollback remains mandatory even if explicit rollback faults."""

    with suppress(sqlite3.Error):
        connection.rollback()


def _fail(code: str) -> None:
    raise FreshChainLedgerError(code) from None


__all__ = ("FreshChainCanaryLedger",)

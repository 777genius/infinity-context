"""Bounded receipt preflight and authenticated cleanup-v3 scratch state."""

from __future__ import annotations

import hashlib
import hmac
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from infinity_context_core.features.projection_receipts import (
    ProjectionReceiptAuthenticator,
)
from infinity_context_core.ports.managed_cleanup_v3_contracts import (
    ManagedCleanupV3Context,
    ManagedCleanupV3Error,
    canonical_bytes,
    digest,
)

from infinity_context_adapters.postgres.managed_cleanup_v3_expected_row_files import (
    close_secure_sqlite,
    create_secure_sqlite,
    open_secure_sqlite,
)
from infinity_context_adapters.postgres.managed_cleanup_v3_projection_evidence import receipt_sha256
from infinity_context_adapters.postgres.managed_cleanup_v3_receipt_page_stream import (
    GlobalLinkStream as _GlobalLinkStream,
)
from infinity_context_adapters.postgres.managed_cleanup_v3_receipt_page_stream import (
    GlobalPayloadStream as _GlobalPayloadStream,
)
from infinity_context_adapters.postgres.managed_cleanup_v3_receipt_page_stream import (
    ReceiptPreflightMetrics,
)
from infinity_context_adapters.postgres.managed_cleanup_v3_receipt_scratch_sql import (
    LINK_PAGE_SQL,
    PAYLOAD_PAGE_SQL,
    RECEIPT_PAGE_SIZE,
    RECEIPT_PAGE_SQL,
    create_receipt_scratch_schema,
)
from infinity_context_adapters.postgres.managed_cleanup_v3_receipt_stream_verifier import (
    array_event as _array_event,
)
from infinity_context_adapters.postgres.managed_cleanup_v3_receipt_stream_verifier import (
    event_prefix as _event_prefix,
)
from infinity_context_adapters.postgres.managed_cleanup_v3_receipt_stream_verifier import (
    fail as _fail,
)
from infinity_context_adapters.postgres.managed_cleanup_v3_receipt_stream_verifier import (
    finish_array_event as _finish_grouped_event,
)
from infinity_context_adapters.postgres.managed_cleanup_v3_receipt_stream_verifier import (
    integer_value as _integer,
)
from infinity_context_adapters.postgres.managed_cleanup_v3_receipt_stream_verifier import (
    inventory_uses as _inventory_uses,
)
from infinity_context_adapters.postgres.managed_cleanup_v3_receipt_stream_verifier import (
    link_evidence as _link_evidence,
)
from infinity_context_adapters.postgres.managed_cleanup_v3_receipt_stream_verifier import (
    object_value as _object,
)
from infinity_context_adapters.postgres.managed_cleanup_v3_receipt_stream_verifier import (
    row_header as _row_header,
)
from infinity_context_adapters.postgres.managed_cleanup_v3_receipt_stream_verifier import (
    sha256_value as _sha,
)
from infinity_context_adapters.postgres.managed_cleanup_v3_receipt_stream_verifier import (
    small_event as _small_event,
)
from infinity_context_adapters.postgres.managed_cleanup_v3_receipt_stream_verifier import (
    validate_event_binding as _validate_event_binding,
)
from infinity_context_adapters.postgres.managed_cleanup_v3_receipt_stream_verifier import (
    verify_identity as _verify_identity,
)


class ManagedCleanupV3ReceiptProofScratch:
    """Authenticate each receipt once, then authorize O(1) logical-row uses."""

    def __init__(
        self,
        db: sqlite3.Connection,
        key: bytes,
        authenticator: ProjectionReceiptAuthenticator,
        *,
        metrics: ReceiptPreflightMetrics | None = None,
        descriptor: int | None = None,
    ) -> None:
        if not isinstance(db, sqlite3.Connection) or type(key) is not bytes or len(key) < 32:
            _fail("scratch_configuration_invalid")
        if type(authenticator) is not ProjectionReceiptAuthenticator:
            _fail("scratch_configuration_invalid")
        self._db = db
        self._key = bytes(key)
        self._authenticator = authenticator
        self.metrics = metrics or ReceiptPreflightMetrics()
        self._descriptor = descriptor
        self._pending_mutations = 0

    @classmethod
    def create(
        cls,
        path: Path,
        key: bytes,
        authenticator: ProjectionReceiptAuthenticator,
        *,
        metrics: ReceiptPreflightMetrics | None = None,
    ) -> ManagedCleanupV3ReceiptProofScratch:
        """Create a distinct 0600 stable-fd SQLite scratch file."""
        db, descriptor = create_secure_sqlite(path)
        try:
            create_receipt_scratch_schema(db)
            return cls(db, key, authenticator, metrics=metrics, descriptor=descriptor)
        except BaseException:
            close_secure_sqlite(db, descriptor)
            raise

    def close(self) -> None:
        if self._descriptor is not None:
            descriptor, self._descriptor = self._descriptor, None
            close_secure_sqlite(self._db, descriptor)

    @classmethod
    def open(
        cls,
        path: Path,
        key: bytes,
        authenticator: ProjectionReceiptAuthenticator,
        *,
        metrics: ReceiptPreflightMetrics | None = None,
    ) -> ManagedCleanupV3ReceiptProofScratch:
        """Reopen an existing secure scratch file for authorized reset/abort."""
        db, descriptor = open_secure_sqlite(path, readonly=False)
        try:
            return cls(db, key, authenticator, metrics=metrics, descriptor=descriptor)
        except BaseException:
            close_secure_sqlite(db, descriptor)
            raise

    def begin_new(self, terminal: str, session: str) -> None:
        terminal, session = digest(terminal), digest(session)
        with self._db:
            self._db.execute("DELETE FROM verified_links")
            self._db.execute("DELETE FROM verified_receipt_sources")
            self._db.execute("DELETE FROM verified_receipts")
            self._db.execute("DELETE FROM receipt_session")
            self._db.execute(
                "INSERT INTO receipt_session VALUES(1,'active',?,?,?)",
                (terminal, session, self._mac("session", terminal, session, "active")),
            )
        self._pending_mutations = 0

    async def prepare_receipts(
        self,
        connection: Any,
        context: ManagedCleanupV3Context,
        terminal: str,
        session: str,
    ) -> None:
        self._require_session(terminal, session, "active")
        links = _GlobalLinkStream(connection, context, self.metrics)
        payloads = _GlobalPayloadStream(connection, context, self.metrics)
        after = -1
        while True:
            rows = await connection.fetch(
                RECEIPT_PAGE_SQL,
                context.run_id_sha256,
                context.context_sha256,
                context.space_id,
                after,
                RECEIPT_PAGE_SIZE,
            )
            self.metrics.receipt_pages += 1
            self.metrics.max_receipt_page = max(self.metrics.max_receipt_page, len(rows))
            if len(rows) > RECEIPT_PAGE_SIZE:
                _fail("receipt_page_invalid")
            for raw in rows:
                receipt = _object(raw["receipt"])
                outbox = _object(raw["outbox"])
                outbox_id = _integer(raw["outbox_id"])
                if outbox_id <= after or receipt.get("outbox_id") != outbox_id:
                    _fail("receipt_order_invalid")
                await self._prepare_one(
                    context, terminal, session, outbox, receipt, links, payloads
                )
                after = outbox_id
            if len(rows) < RECEIPT_PAGE_SIZE:
                break
        if await links.peek() is not None:
            _fail("receipt_order_invalid")
        if await payloads.peek() is not None:
            _fail("payload_order_invalid")
        self._checkpoint()

    async def _prepare_one(
        self,
        context: ManagedCleanupV3Context,
        terminal: str,
        session: str,
        outbox: dict[str, object],
        receipt: dict[str, object],
        links: _GlobalLinkStream,
        payloads: _GlobalPayloadStream,
    ) -> None:
        outbox_id = _integer(receipt.get("outbox_id"))
        operation = str(receipt.get("operation"))
        payload_count = outbox.get("payload_identity_count")
        array_event = _array_event(outbox.get("event_type"), payload_count)
        expected_authority = {
            "qdrant": context.qdrant_authority_sha256,
            "graphiti": context.graphiti_authority_sha256,
        }.get(str(receipt.get("lane")))
        if (
            outbox.get("id") != outbox_id
            or outbox.get("status") != "done"
            or receipt.get("run_id_sha256") != context.run_id_sha256
            or receipt.get("context_sha256") != context.context_sha256
            or receipt.get("space_id") != context.space_id
            or receipt.get("worker_authority_sha256") != self._authenticator.authority_sha256
            or expected_authority is None
            or receipt.get("target_authority_sha256") != expected_authority
            or receipt.get("result_state") != ("present" if operation == "upsert" else "absent")
            or (array_event and payload_count != receipt.get("identity_count"))
            or receipt.get("aggregate_type") != outbox.get("aggregate_type")
            or receipt.get("aggregate_id") != outbox.get("aggregate_id")
            or receipt.get("aggregate_version") != outbox.get("aggregate_version")
        ):
            _fail("receipt_binding_invalid")
        root_hash = hashlib.sha256()
        root_hash.update(b"[")
        event_payload_hash = _event_prefix(outbox) if array_event else None
        if array_event:
            await self._prepare_payload_sources(
                terminal, session, outbox_id, event_payload_hash, payloads
            )
        ordinal = -1
        count = 0
        identity_kinds: dict[str, int] = {}
        common_source_id: str | None = None
        while True:
            raw = await links.peek()
            if raw is None:
                break
            link_outbox_id = _integer(raw["outbox_id"])
            if link_outbox_id < outbox_id:
                _fail("link_order_invalid")
            if link_outbox_id > outbox_id:
                break
            link, identity = _object(raw["link"]), _object(raw["identity"])
            ordinal += 1
            if raw["ordinal"] != ordinal or link.get("ordinal") != ordinal:
                _fail("link_ordinal_invalid")
            _verify_identity(self._authenticator, receipt, link, identity)
            identity_kind = str(identity.get("kind"))
            identity_kinds[identity_kind] = identity_kinds.get(identity_kind, 0) + 1
            source_id = str(identity.get("canonical_source_id"))
            if common_source_id is None:
                common_source_id = source_id
            elif receipt.get("lane") == "graphiti" and common_source_id != source_id:
                _fail("graphiti_composition_invalid")
            proof_item = {
                "identity_commitment_sha256": identity.get("identity_commitment_sha256"),
                "identity_sha256": identity.get("identity_sha256"),
                "kind": identity.get("kind"),
                "ordinal": ordinal,
            }
            if count:
                root_hash.update(b",")
            root_hash.update(canonical_bytes(proof_item))
            if array_event:
                self._claim_payload_source(
                    terminal,
                    session,
                    outbox_id,
                    str(identity.get("canonical_source_id")),
                )
            self._insert_uses(terminal, session, receipt, link, identity, outbox)
            count += 1
            links.advance()
        root_hash.update(b"]")
        root = root_hash.hexdigest()
        if count != receipt.get("identity_count") or root != receipt.get(
            "ordered_identity_root_sha256"
        ):
            _fail("identity_root_invalid")
        if receipt.get("lane") == "qdrant":
            if identity_kinds != {"qdrant_point_id": count}:
                _fail("qdrant_composition_invalid")
        elif identity_kinds != {"graphiti_episode_name": 1, "graphiti_episode_uuid": 1}:
            _fail("graphiti_composition_invalid")
        if (
            array_event
            and self._db.execute(
                "SELECT 1 FROM verified_receipt_sources WHERE outbox_id=? AND claimed<>1 LIMIT 1",
                (outbox_id,),
            ).fetchone()
        ):
            _fail("outbox_payload_invalid")
        _validate_event_binding(context, receipt, outbox, common_source_id, count)
        event_sha = (
            _finish_grouped_event(event_payload_hash, outbox)
            if array_event
            else _small_event(outbox)
        )
        if event_sha != receipt.get("outbox_event_commitment_sha256"):
            _fail("outbox_commitment_invalid")
        computed = receipt_sha256(receipt, root)
        if receipt.get("receipt_sha256") != computed or not self._authenticator.verify(
            "projection-receipt", computed, str(receipt.get("receipt_mac_sha256"))
        ):
            _fail("receipt_invalid")
        header_sha = _sha(_row_header(outbox, receipt))
        self._before_mutations(1)
        self._db.execute(
            "INSERT INTO verified_receipts VALUES(?,?,?,0,?)",
            (
                outbox_id,
                header_sha,
                computed,
                self._mac("receipt", terminal, session, outbox_id, header_sha, computed, 0),
            ),
        )
        self._record_mutations(1)

    async def _prepare_payload_sources(
        self, terminal, session, outbox_id, event_hash, payloads: _GlobalPayloadStream
    ) -> None:
        after = -1
        while True:
            raw = await payloads.peek()
            if raw is None:
                break
            payload_outbox_id = _integer(raw["outbox_id"])
            if payload_outbox_id < outbox_id:
                _fail("payload_order_invalid")
            if payload_outbox_id > outbox_id:
                break
            ordinal = _integer(raw["ordinal"])
            source_id = str(raw["source_id"])
            if ordinal != after + 1:
                _fail("payload_order_invalid")
            if ordinal:
                event_hash.update(b",")
            event_hash.update(canonical_bytes(source_id))
            mac = self._mac("source", terminal, session, outbox_id, ordinal, source_id, 0)
            try:
                self._before_mutations(1)
                self._db.execute(
                    "INSERT INTO verified_receipt_sources VALUES(?,?,?,0,?)",
                    (outbox_id, ordinal, source_id, mac),
                )
                self._record_mutations(1)
            except sqlite3.IntegrityError as exc:
                raise ManagedCleanupV3Error("managed_cleanup_v3_receipt_payload_duplicate") from exc
            after = ordinal
            payloads.advance()

    def _claim_payload_source(self, terminal, session, outbox_id, source_id) -> None:
        row = self._db.execute(
            "SELECT ordinal,claimed,row_mac FROM verified_receipt_sources "
            "WHERE outbox_id=? AND source_id=?",
            (outbox_id, source_id),
        ).fetchone()
        if row is None:
            _fail("outbox_payload_invalid")
        ordinal, claimed, mac = int(row[0]), int(row[1]), str(row[2])
        if claimed != 0 or not hmac.compare_digest(
            mac, self._mac("source", terminal, session, outbox_id, ordinal, source_id, 0)
        ):
            _fail("outbox_payload_invalid")
        self._before_mutations(1)
        self._db.execute(
            "UPDATE verified_receipt_sources SET claimed=1,row_mac=? "
            "WHERE outbox_id=? AND source_id=? AND claimed=0",
            (
                self._mac("source", terminal, session, outbox_id, ordinal, source_id, 1),
                outbox_id,
                source_id,
            ),
        )
        self._record_mutations(1)

    def _insert_uses(self, terminal, session, receipt, link, identity, outbox) -> None:
        evidence_sha = _sha(_link_evidence(link, identity))
        for inventory_kind in _inventory_uses(receipt, identity):
            values = (
                _integer(receipt.get("outbox_id")),
                _integer(link.get("ordinal")),
                inventory_kind,
                str(identity.get("kind")),
                str(identity.get("identity_sha256")),
                str(identity.get("identity_commitment_sha256")),
                evidence_sha,
            )
            mac = self._mac("link", terminal, session, *values, 0)
            try:
                self._before_mutations(1)
                self._db.execute(
                    "INSERT INTO verified_links"
                    "(outbox_id,ordinal,inventory_kind,identity_kind,identity_sha,"
                    "identity_commitment,evidence_sha,consumed,row_mac) VALUES(?,?,?,?,?,?,?,0,?)",
                    (*values, mac),
                )
                self._record_mutations(1)
            except sqlite3.IntegrityError as exc:
                raise ManagedCleanupV3Error("managed_cleanup_v3_receipt_scratch_duplicate") from exc

    def consume(
        self,
        terminal: str,
        session: str,
        inventory_kind: str,
        outbox: Mapping[str, object],
        receipt: Mapping[str, object],
        link: Mapping[str, object],
        identity: Mapping[str, object],
    ) -> None:
        terminal, session = digest(terminal), digest(session)
        self._require_session(terminal, session, "active")
        outbox_id, ordinal = _integer(receipt.get("outbox_id")), _integer(link.get("ordinal"))
        receipt_row = self._db.execute(
            "SELECT header_sha,receipt_sha,used,row_mac FROM verified_receipts WHERE outbox_id=?",
            (outbox_id,),
        ).fetchone()
        link_row = self._db.execute(
            "SELECT identity_kind,identity_sha,identity_commitment,evidence_sha,consumed,row_mac "
            "FROM verified_links WHERE outbox_id=? AND ordinal=? AND inventory_kind=?",
            (outbox_id, ordinal, inventory_kind),
        ).fetchone()
        if receipt_row is None or link_row is None:
            _fail("unknown_use")
        header_sha, receipt_sha = map(str, receipt_row[:2])
        receipt_used, receipt_mac = int(receipt_row[2]), str(receipt_row[3])
        if (
            not hmac.compare_digest(
                receipt_mac,
                self._mac(
                    "receipt",
                    terminal,
                    session,
                    outbox_id,
                    header_sha,
                    receipt_sha,
                    receipt_used,
                ),
            )
            or header_sha != _sha(_row_header(dict(outbox), dict(receipt)))
            or receipt_sha != receipt.get("receipt_sha256")
        ):
            _fail("receipt_scratch_authentication_invalid")
        identity_kind, identity_sha, identity_commitment, evidence_sha = map(str, link_row[:4])
        consumed = int(link_row[4])
        expected_mac = self._mac(
            "link",
            terminal,
            session,
            outbox_id,
            ordinal,
            inventory_kind,
            identity_kind,
            identity_sha,
            identity_commitment,
            evidence_sha,
            consumed,
        )
        if (
            not hmac.compare_digest(str(link_row[5]), expected_mac)
            or consumed != 0
            or identity_kind != identity.get("kind")
            or identity_sha != identity.get("identity_sha256")
            or identity_commitment != identity.get("identity_commitment_sha256")
            or evidence_sha != _sha(_link_evidence(dict(link), dict(identity)))
        ):
            _fail("link_scratch_authentication_invalid")
        new_mac = self._mac(
            "link",
            terminal,
            session,
            outbox_id,
            ordinal,
            inventory_kind,
            identity_kind,
            identity_sha,
            identity_commitment,
            evidence_sha,
            1,
        )
        # One bounded logical consume may atomically update both its link and receipt marker.
        mutation_count = 1
        self._before_mutations(mutation_count)
        try:
            changed = self._db.execute(
                "UPDATE verified_links SET consumed=1,row_mac=? "
                "WHERE outbox_id=? AND ordinal=? AND inventory_kind=? AND consumed=0",
                (new_mac, outbox_id, ordinal, inventory_kind),
            ).rowcount
            if changed != 1:
                _fail("double_use")
            if receipt_used == 0:
                self._db.execute(
                    "UPDATE verified_receipts SET used=1,row_mac=? WHERE outbox_id=? AND used=0",
                    (
                        self._mac(
                            "receipt",
                            terminal,
                            session,
                            outbox_id,
                            header_sha,
                            receipt_sha,
                            1,
                        ),
                        outbox_id,
                    ),
                )
            self._record_mutations(mutation_count)
        except BaseException:
            self._db.rollback()
            self._pending_mutations = 0
            raise

    def finalize(self, terminal: str, session: str) -> None:
        terminal, session = digest(terminal), digest(session)
        self._require_session(terminal, session, "active")
        if self._pending_mutations:
            _fail("unflushed_page")
        after_outbox = -1
        while True:
            rows = self._db.execute(
                "SELECT outbox_id,header_sha,receipt_sha,used,row_mac "
                "FROM verified_receipts WHERE outbox_id>? ORDER BY outbox_id LIMIT ?",
                (after_outbox, RECEIPT_PAGE_SIZE),
            ).fetchall()
            for row in rows:
                values = tuple(row[:4])
                if int(row[3]) != 1 or not hmac.compare_digest(
                    str(row[4]), self._mac("receipt", terminal, session, *values)
                ):
                    _fail("coverage_invalid")
            if len(rows) < RECEIPT_PAGE_SIZE:
                break
            after_outbox = int(rows[-1][0])
        after_link: tuple[int, int, str] = (-1, -1, "")
        while True:
            rows = self._db.execute(
                "SELECT outbox_id,ordinal,inventory_kind,identity_kind,identity_sha,"
                "identity_commitment,evidence_sha,consumed,row_mac FROM verified_links "
                "WHERE (outbox_id,ordinal,inventory_kind)>(?,?,?) "
                "ORDER BY outbox_id,ordinal,inventory_kind LIMIT ?",
                (*after_link, RECEIPT_PAGE_SIZE),
            ).fetchall()
            for row in rows:
                values = tuple(row[:8])
                if int(row[7]) != 1 or not hmac.compare_digest(
                    str(row[8]), self._mac("link", terminal, session, *values)
                ):
                    _fail("coverage_invalid")
            if len(rows) < RECEIPT_PAGE_SIZE:
                break
            after_link = (int(rows[-1][0]), int(rows[-1][1]), str(rows[-1][2]))
        after_source: tuple[int, int] = (-1, -1)
        while True:
            rows = self._db.execute(
                "SELECT outbox_id,ordinal,source_id,claimed,row_mac "
                "FROM verified_receipt_sources WHERE (outbox_id,ordinal)>(?,?) "
                "ORDER BY outbox_id,ordinal LIMIT ?",
                (*after_source, RECEIPT_PAGE_SIZE),
            ).fetchall()
            for row in rows:
                values = tuple(row[:4])
                if int(row[3]) != 1 or not hmac.compare_digest(
                    str(row[4]), self._mac("source", terminal, session, *values)
                ):
                    _fail("coverage_invalid")
            if len(rows) < RECEIPT_PAGE_SIZE:
                break
            after_source = (int(rows[-1][0]), int(rows[-1][1]))
        with self._db:
            self._db.execute(
                "UPDATE receipt_session SET state='finalized',row_mac=? WHERE singleton=1",
                (self._mac("session", terminal, session, "finalized"),),
            )
        self._pending_mutations = 0

    def flush_verification_page(self, terminal: str, session: str) -> None:
        self._require_session(terminal, session, "active")
        if self._pending_mutations > RECEIPT_PAGE_SIZE:
            _fail("page_mutation_overflow")
        self._checkpoint()

    def abort(self, terminal: str, session: str) -> None:
        self._require_session(terminal, session, None)
        with self._db:
            self._db.execute("DELETE FROM verified_links")
            self._db.execute("DELETE FROM verified_receipt_sources")
            self._db.execute("DELETE FROM verified_receipts")
            self._db.execute("DELETE FROM receipt_session")
        self._pending_mutations = 0

    def _before_mutations(self, count: int) -> None:
        if self._pending_mutations and self._pending_mutations + count > RECEIPT_PAGE_SIZE:
            self._checkpoint()

    def _record_mutations(self, count: int) -> None:
        self._pending_mutations += count
        self.metrics.max_pending_mutations = max(
            self.metrics.max_pending_mutations, self._pending_mutations
        )
        if self._pending_mutations == RECEIPT_PAGE_SIZE:
            self._checkpoint()

    def _checkpoint(self) -> None:
        if self._pending_mutations:
            self._db.commit()
            self.metrics.scratch_checkpoints += 1
            self._pending_mutations = 0

    def _require_session(self, terminal: str, session: str, state: str | None) -> None:
        terminal, session = digest(terminal), digest(session)
        row = self._db.execute(
            "SELECT state,terminal_sha,session_sha,row_mac FROM receipt_session WHERE singleton=1"
        ).fetchone()
        if (
            row is None
            or (state is not None and row[0] != state)
            or row[1:3]
            != (
                terminal,
                session,
            )
            or not hmac.compare_digest(
                str(row[3]), self._mac("session", terminal, session, str(row[0]))
            )
        ):
            _fail("session_invalid")

    def _mac(self, domain: str, *values: object) -> str:
        return hmac.new(
            self._key,
            b"managed-cleanup-v4/receipt-scratch/"
            + domain.encode()
            + b"\0"
            + canonical_bytes(values),
            hashlib.sha256,
        ).hexdigest()


__all__ = (
    "LINK_PAGE_SQL",
    "ManagedCleanupV3ReceiptProofScratch",
    "PAYLOAD_PAGE_SQL",
    "RECEIPT_PAGE_SIZE",
    "RECEIPT_PAGE_SQL",
    "ReceiptPreflightMetrics",
    "create_receipt_scratch_schema",
)

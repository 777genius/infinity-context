"""Provider-free materialization of cleanup inventory under the writer fence."""

from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from infinity_context_core.features.projection_receipts import ProjectionReceiptAuthenticator
from infinity_context_core.ports.managed_cleanup_v3_contracts import (
    ManagedCleanupV3Context,
    ManagedCleanupV3Error,
    canonical_bytes,
    commitment,
    digest,
    profile_oracle,
)
from infinity_context_core.ports.managed_cleanup_v3_recovery import (
    INVENTORY_KINDS,
    INVENTORY_PAGE_SIZE,
)

from infinity_context_adapters.postgres.managed_cleanup_v3_inventory_codec import (
    authenticate_rows,
    authenticate_summaries,
    inventory_mac,
    materialized_row_sha,
    normalize_locator_json,
    page_root,
)
from infinity_context_adapters.postgres.managed_cleanup_v3_registered_authority import (
    authenticate_registered_authority,
)

INSERT_KEY_SQL = """
INSERT INTO memory_cleanup_inventory_keys (
  run_id_sha256, context_sha256, cleanup_receipt_sha256, kind,
  canonical_key_sha256, locator_json, locator_sha256, row_sha256, row_mac_sha256
) VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7,$8,$9)
"""
INSERT_PENDING_SQL = """
INSERT INTO memory_cleanup_inventory_materializations (
  run_id_sha256, context_sha256, cleanup_receipt_sha256, kind,
  authority_terminal_sha256, expected_count, ordered_rows_root_sha256,
  complete, sealed_at, row_mac_sha256
) VALUES ($1,$2,$3,$4,$5,0,$6,FALSE,transaction_timestamp(),$7)
"""
SEAL_SUMMARY_SQL = """
UPDATE memory_cleanup_inventory_materializations
SET expected_count=$6, ordered_rows_root_sha256=$7, complete=TRUE,
    sealed_at=transaction_timestamp(), row_mac_sha256=$8
WHERE run_id_sha256=$1 AND context_sha256=$2
  AND cleanup_receipt_sha256=$3 AND kind=$4
  AND authority_terminal_sha256=$5 AND complete IS FALSE
"""
SCAN_KEYS_SQL = """
SELECT canonical_key_sha256, row_sha256
FROM memory_cleanup_inventory_keys
WHERE run_id_sha256=$1 AND context_sha256=$2
  AND cleanup_receipt_sha256=$3 AND kind=$4
  AND canonical_key_sha256 > $5
ORDER BY canonical_key_sha256
LIMIT $6
"""
LOCK_SQL = """
SELECT state, projection_cleanup_state
FROM memory_comparison_benchmark_runs
WHERE run_id_sha256=$1
FOR UPDATE
"""
SNAPSHOT_SQL = "SELECT pg_current_snapshot()::text"
REPLAY_SUMMARIES_SQL = """
SELECT kind, authority_terminal_sha256, expected_count,
       ordered_rows_root_sha256, complete, row_mac_sha256
FROM memory_cleanup_inventory_materializations
WHERE run_id_sha256=$1 AND context_sha256=$2 AND cleanup_receipt_sha256=$3
ORDER BY kind
"""
REPLAY_KEYS_SQL = """
SELECT canonical_key_sha256, locator_json, locator_sha256, row_sha256, row_mac_sha256
FROM memory_cleanup_inventory_keys
WHERE run_id_sha256=$1 AND context_sha256=$2
  AND cleanup_receipt_sha256=$3 AND kind=$4
  AND canonical_key_sha256 > $5
ORDER BY canonical_key_sha256
LIMIT $6
"""


@dataclass(frozen=True, slots=True)
class InventorySourceRow:
    """Canonical evidence plus an indexed source-side continuation token."""

    locator_json: Mapping[str, object]
    row_json: Mapping[str, object]
    source_cursor: object


@dataclass(frozen=True, slots=True)
class InventorySourcePage:
    rows: tuple[InventorySourceRow, ...]
    exhausted: bool


class CanonicalInventorySource(Protocol):
    async def read_page(
        self,
        connection: Any,
        *,
        context: ManagedCleanupV3Context,
        kind: str,
        expected: int,
        after: object | None,
        limit: int,
    ) -> InventorySourcePage: ...


WriterFenceCheck = Callable[[Any, ManagedCleanupV3Context], Awaitable[None]]


class EvidenceAuthenticator(Protocol):
    async def __call__(
        self,
        connection: Any,
        context: ManagedCleanupV3Context,
        authority_terminal_sha256: str,
        verification_session_sha256: str,
        kind: str,
        source_row: InventorySourceRow,
    ) -> None: ...

    async def begin_verification(
        self, authority_terminal_sha256: str, verification_session_sha256: str
    ) -> None: ...

    async def begin_new_verification(
        self, authority_terminal_sha256: str, verification_session_sha256: str
    ) -> None: ...

    async def prepare_receipts(
        self,
        connection: Any,
        context: ManagedCleanupV3Context,
        authority_terminal_sha256: str,
        verification_session_sha256: str,
    ) -> None: ...

    async def flush_verification_page(
        self, authority_terminal_sha256: str, verification_session_sha256: str
    ) -> None: ...

    async def finalize_verification(
        self, authority_terminal_sha256: str, verification_session_sha256: str
    ) -> None: ...

    async def abort_verification(
        self, authority_terminal_sha256: str, verification_session_sha256: str
    ) -> None: ...


class AsyncPostgresManagedCleanupV3InventoryMaterializer:
    """Build immutable SHA-keyed inventory from authenticated canonical evidence."""

    def __init__(
        self,
        *,
        connect: Callable[[], Awaitable[Any]],
        source: CanonicalInventorySource,
        authenticate_evidence: EvidenceAuthenticator,
        assert_writer_fenced: WriterFenceCheck,
        hmac_key: bytes,
        projection_authenticator: ProjectionReceiptAuthenticator,
    ) -> None:
        if type(hmac_key) is not bytes or len(hmac_key) < 32:
            raise ValueError("inventory HMAC key must contain at least 32 bytes")
        self._connect = connect
        self._source = source
        if authenticate_evidence is None:
            raise ValueError("evidence authenticator is required")
        self._authenticate = authenticate_evidence
        self._writer_fence = assert_writer_fenced
        self._key = bytes(hmac_key)
        if type(projection_authenticator) is not ProjectionReceiptAuthenticator:
            raise ValueError("projection receipt authenticator is required")
        self._projection_authenticator = projection_authenticator

    async def materialize(
        self,
        *,
        context: ManagedCleanupV3Context,
        authority_terminal_sha256: str,
        cleanup_receipt_sha256: str,
    ) -> None:
        context.__post_init__()
        terminal = digest(authority_terminal_sha256)
        cleanup = digest(cleanup_receipt_sha256)
        connection = await self._connect()
        transaction = connection.transaction(isolation="repeatable_read")
        verification_session: str | None = None
        verification_begun = False
        try:
            await transaction.start()
            state = await connection.fetchrow(LOCK_SQL, context.run_id_sha256)
            if (
                state is None
                or state["state"] != "cleanup_pending"
                or state["projection_cleanup_state"] != "pending"
            ):
                raise ManagedCleanupV3Error("managed_cleanup_v3_materialization_state_invalid")
            await self._authenticate_registered_authority(connection, context, terminal)
            await self._writer_fence(connection, context)
            if await self._authenticate_complete_materialization(
                connection, context, terminal, cleanup
            ):
                await transaction.commit()
                await connection.close()
                return
            snapshot = await connection.fetchval(SNAPSHOT_SQL)
            if type(snapshot) is not str or not snapshot:
                raise ManagedCleanupV3Error("managed_cleanup_v3_materialization_snapshot_invalid")
            verification_session = commitment(
                "inventory-materialization-verification-session/v4",
                {
                    "run_id_sha256": context.run_id_sha256,
                    "context_sha256": context.context_sha256,
                    "authority_terminal_sha256": terminal,
                    "cleanup_receipt_sha256": cleanup,
                    "pg_snapshot": snapshot,
                    "attempt_nonce": secrets.token_hex(32),
                },
            )
            await self._authenticate.begin_new_verification(terminal, verification_session)
            verification_begun = True
            await self._authenticate.prepare_receipts(
                connection, context, terminal, verification_session
            )
            await connection.execute(
                """
                DELETE FROM memory_cleanup_inventory_keys
                WHERE run_id_sha256=$1 AND context_sha256=$2
                  AND cleanup_receipt_sha256=$3
                """,
                context.run_id_sha256,
                context.context_sha256,
                cleanup,
            )
            await connection.execute(
                """
                DELETE FROM memory_cleanup_inventory_materializations
                WHERE run_id_sha256=$1 AND context_sha256=$2
                  AND cleanup_receipt_sha256=$3
                """,
                context.run_id_sha256,
                context.context_sha256,
                cleanup,
            )
            for kind, expected in zip(INVENTORY_KINDS, _expected_counts(context), strict=True):
                count = await self._materialize_kind(
                    connection,
                    context,
                    terminal,
                    verification_session,
                    cleanup,
                    kind,
                    expected,
                )
                if count != expected:
                    raise ManagedCleanupV3Error("managed_cleanup_v3_materialization_count_invalid")
            await self._authenticate.finalize_verification(terminal, verification_session)
            await transaction.commit()
        except BaseException as exc:
            if verification_begun and verification_session is not None:
                try:
                    await self._authenticate.abort_verification(terminal, verification_session)
                except BaseException as abort_error:
                    exc.add_note(
                        "managed cleanup v4 verification abort failed: "
                        f"{type(abort_error).__name__}"
                    )
            try:
                await transaction.rollback()
            finally:
                await connection.close()
            raise
        await connection.close()

    async def _authenticate_complete_materialization(
        self,
        connection: Any,
        context: ManagedCleanupV3Context,
        terminal: str,
        cleanup: str,
    ) -> bool:
        rows = await connection.fetch(
            REPLAY_SUMMARIES_SQL,
            context.run_id_sha256,
            context.context_sha256,
            cleanup,
        )
        if not rows:
            return False
        if any(
            row["complete"] is not True or str(row["authority_terminal_sha256"]) != terminal
            for row in rows
        ):
            raise ManagedCleanupV3Error("managed_cleanup_v3_materialization_replay_invalid")
        summaries = authenticate_summaries(
            rows,
            self._key,
            context.run_id_sha256,
            context.context_sha256,
            cleanup,
            terminal,
        )
        expected_by_kind = dict(zip(INVENTORY_KINDS, _expected_counts(context), strict=True))
        for summary in summaries:
            if summary.count != expected_by_kind[summary.kind]:
                raise ManagedCleanupV3Error("managed_cleanup_v3_materialization_replay_invalid")
            await self._authenticate_replay_kind(
                connection, context, cleanup, summary.kind, summary.count, summary.root
            )
        return True

    async def _authenticate_replay_kind(
        self,
        connection: Any,
        context: ManagedCleanupV3Context,
        cleanup: str,
        kind: str,
        expected_count: int,
        expected_root: str,
    ) -> None:
        last = "0" * 64
        count = 0
        roots: list[str] = []
        while True:
            rows = await connection.fetch(
                REPLAY_KEYS_SQL,
                context.run_id_sha256,
                context.context_sha256,
                cleanup,
                kind,
                last,
                INVENTORY_PAGE_SIZE,
            )
            keys, hashes = authenticate_rows(
                rows,
                self._key,
                context.run_id_sha256,
                context.context_sha256,
                cleanup,
                kind,
                None if last == "0" * 64 else last,
            )
            for row, key in zip(rows, keys, strict=True):
                locator = normalize_locator_json(row["locator_json"])
                if (
                    canonical_locator(kind, locator) != locator
                    or commitment("inventory-locator/v4", {"kind": kind, "locator": locator})
                    != str(row["locator_sha256"])
                    or commitment(
                        "inventory-canonical-key/v4",
                        {"kind": kind, "locator": locator},
                    )
                    != key
                ):
                    raise ManagedCleanupV3Error("managed_cleanup_v3_materialization_replay_invalid")
            if rows or not roots:
                roots.append(commitment("inventory-row-page/v4", list(hashes)))
            count += len(rows)
            if len(rows) < INVENTORY_PAGE_SIZE:
                break
            last = keys[-1]
        if count != expected_count or page_root("inventory-empty-rows/v4", roots) != expected_root:
            raise ManagedCleanupV3Error("managed_cleanup_v3_materialization_replay_invalid")

    async def _authenticate_registered_authority(
        self,
        connection: Any,
        context: ManagedCleanupV3Context,
        authority_terminal_sha256: str,
    ) -> None:
        await authenticate_registered_authority(
            connection,
            context,
            authority_terminal_sha256,
            self._projection_authenticator,
        )

    async def _materialize_kind(
        self,
        connection: Any,
        context: ManagedCleanupV3Context,
        authority: str,
        verification_session: str,
        cleanup: str,
        kind: str,
        expected: int,
    ) -> int:
        empty_root = commitment("inventory-empty-pending/v4", [])
        await connection.execute(
            INSERT_PENDING_SQL,
            context.run_id_sha256,
            context.context_sha256,
            cleanup,
            kind,
            authority,
            empty_root,
            "0" * 64,
        )
        after: object | None = None
        count = 0
        while True:
            page = await self._source.read_page(
                connection,
                context=context,
                kind=kind,
                expected=expected,
                after=after,
                limit=INVENTORY_PAGE_SIZE,
            )
            if type(page) is not InventorySourcePage or len(page.rows) > INVENTORY_PAGE_SIZE:
                raise ManagedCleanupV3Error("managed_cleanup_v3_materialization_page_invalid")
            if not page.exhausted and len(page.rows) != INVENTORY_PAGE_SIZE:
                raise ManagedCleanupV3Error("managed_cleanup_v3_materialization_page_invalid")
            next_count = count + len(page.rows)
            if next_count > expected or (next_count == expected and not page.exhausted):
                raise ManagedCleanupV3Error("managed_cleanup_v3_materialization_count_invalid")
            records = []
            previous = after
            for source_row in page.rows:
                if (
                    type(source_row) is not InventorySourceRow
                    or source_row.source_cursor == previous
                ):
                    raise ManagedCleanupV3Error("managed_cleanup_v3_materialization_page_invalid")
                await self._authenticate(
                    connection,
                    context,
                    authority,
                    verification_session,
                    kind,
                    source_row,
                )
                supplied_locator = dict(source_row.locator_json)
                locator = canonical_locator(kind, supplied_locator)
                if supplied_locator != locator:
                    raise ManagedCleanupV3Error(
                        "managed_cleanup_v3_materialization_locator_invalid"
                    )
                row = dict(source_row.row_json)
                if kind == "unsupported_rows":
                    row.pop("__unsupported_pk", None)
                locator_sha = commitment("inventory-locator/v4", {"kind": kind, "locator": locator})
                canonical_key = commitment(
                    "inventory-canonical-key/v4", {"kind": kind, "locator": locator}
                )
                row_sha = materialized_row_sha(kind, canonical_key, locator_sha, row)
                payload = {
                    "run_id_sha256": context.run_id_sha256,
                    "context_sha256": context.context_sha256,
                    "cleanup_receipt_sha256": cleanup,
                    "kind": kind,
                    "canonical_key_sha256": canonical_key,
                    "locator_json": locator,
                    "locator_sha256": locator_sha,
                    "row_sha256": row_sha,
                }
                records.append(
                    (
                        context.run_id_sha256,
                        context.context_sha256,
                        cleanup,
                        kind,
                        canonical_key,
                        canonical_bytes(locator).decode("ascii"),
                        locator_sha,
                        row_sha,
                        inventory_mac(
                            self._key,
                            "managed-cleanup-v4/inventory-key",
                            payload,
                        ),
                    )
                )
                previous = source_row.source_cursor
            if records:
                await connection.executemany(INSERT_KEY_SQL, records)
                count += len(records)
                after = page.rows[-1].source_cursor
            await self._authenticate.flush_verification_page(authority, verification_session)
            if page.exhausted:
                break
        root = await _ordered_root(connection, context, cleanup, kind)
        summary_payload = {
            "run_id_sha256": context.run_id_sha256,
            "context_sha256": context.context_sha256,
            "cleanup_receipt_sha256": cleanup,
            "kind": kind,
            "authority_terminal_sha256": authority,
            "expected_count": count,
            "ordered_rows_root_sha256": root,
            "complete": True,
        }
        sealed = await connection.execute(
            SEAL_SUMMARY_SQL,
            context.run_id_sha256,
            context.context_sha256,
            cleanup,
            kind,
            authority,
            count,
            root,
            inventory_mac(
                self._key,
                "managed-cleanup-v4/inventory-summary",
                summary_payload,
            ),
        )
        if sealed != "UPDATE 1":
            raise ManagedCleanupV3Error("managed_cleanup_v3_materialization_seal_invalid")
        return count


async def _ordered_root(
    connection: Any,
    context: ManagedCleanupV3Context,
    cleanup: str,
    kind: str,
) -> str:
    last = "0" * 64
    page_roots: list[str] = []
    while True:
        rows = await connection.fetch(
            SCAN_KEYS_SQL,
            context.run_id_sha256,
            context.context_sha256,
            cleanup,
            kind,
            last,
            INVENTORY_PAGE_SIZE,
        )
        hashes = [str(row["row_sha256"]) for row in rows]
        if rows or not page_roots:
            page_roots.append(commitment("inventory-row-page/v4", hashes))
        if len(rows) < INVENTORY_PAGE_SIZE:
            break
        last = str(rows[-1]["canonical_key_sha256"])
    return page_root("inventory-empty-rows/v4", page_roots)


def _expected_counts(context: ManagedCleanupV3Context) -> tuple[int, ...]:
    oracle = profile_oracle(context.profile_id)
    facts = int(oracle["operation_count"]) if oracle["lane"] == "fact" else 0
    documents = int(oracle["operation_count"]) if oracle["lane"] == "document" else 0
    chunks = int(oracle["fragment_count"])
    corpus = int(oracle["corpus_count"])
    return (
        corpus,
        corpus,
        facts,
        facts,
        documents,
        chunks,
        chunks,
        facts,
        facts,
        chunks,
        chunks,
        facts,
        facts,
        chunks + facts,
        0,
    )


LOCATOR_FIELDS = {
    "memory_scopes": ("id",),
    "memory_threads": ("id",),
    "facts": ("id",),
    "fact_source_refs": ("id", "fact_id", "fact_version"),
    "documents": ("id",),
    "chunks": ("id",),
    "qdrant_target_identities": (
        "kind",
        "identity_sha256",
        "identity_commitment_sha256",
        "lineage_root_sha256",
        "target_authority_sha256",
    ),
    "graphiti_target_names": (
        "kind",
        "identity_sha256",
        "identity_commitment_sha256",
        "lineage_root_sha256",
        "target_authority_sha256",
    ),
    "graphiti_target_uuids": (
        "kind",
        "identity_sha256",
        "identity_commitment_sha256",
        "lineage_root_sha256",
        "target_authority_sha256",
    ),
    "qdrant_upsert_jobs": (
        "physical_outbox_id",
        "logical_target_identity_sha256",
    ),
    "qdrant_delete_jobs": (
        "physical_outbox_id",
        "logical_target_identity_sha256",
    ),
    "graphiti_upsert_jobs": (
        "physical_outbox_id",
        "logical_target_identity_sha256",
    ),
    "graphiti_delete_jobs": (
        "physical_outbox_id",
        "logical_target_identity_sha256",
    ),
    "cleanup_outbox_receipts": (
        "physical_outbox_id",
        "logical_target_identity_sha256",
    ),
    "unsupported_rows": ("source_table", "source_pk"),
}


def canonical_locator(kind: str, row: Mapping[str, object]) -> dict[str, object]:
    try:
        fields: Sequence[str] = LOCATOR_FIELDS[kind]
        locator = {field: row[field] for field in fields}
    except (KeyError, TypeError) as exc:
        raise ManagedCleanupV3Error("managed_cleanup_v3_materialization_locator_invalid") from exc
    if any(value is None for value in locator.values()):
        raise ManagedCleanupV3Error("managed_cleanup_v3_materialization_locator_invalid")
    return locator


__all__ = (
    "AsyncPostgresManagedCleanupV3InventoryMaterializer",
    "CanonicalInventorySource",
    "InventorySourcePage",
    "InventorySourceRow",
    "LOCATOR_FIELDS",
    "canonical_locator",
)

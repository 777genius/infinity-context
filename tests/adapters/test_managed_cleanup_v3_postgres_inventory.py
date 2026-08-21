from __future__ import annotations

import hashlib

import pytest
from infinity_context_adapters.postgres.managed_cleanup_v3_inventory import (
    PAGE_SQL,
    SUMMARY_SQL,
    AsyncPostgresManagedCleanupV3Inventory,
    AsyncPostgresManagedCleanupV3Snapshot,
)
from infinity_context_adapters.postgres.managed_cleanup_v3_inventory_codec import (
    InventorySummary,
    authenticate_rows,
    build_core_page,
    inventory_mac,
    materialized_row_sha,
)
from infinity_context_adapters.postgres.managed_cleanup_v3_inventory_materializer import (
    LOCATOR_FIELDS,
    canonical_locator,
)
from infinity_context_core.ports.managed_cleanup_v3_contracts import (
    LOCOMO_PROFILE,
    LONGMEMEVAL_PROFILE,
    PROFILE_ORACLES,
    ManagedCleanupV3Error,
    build_context,
    commitment,
)
from infinity_context_core.ports.managed_cleanup_v3_recovery import (
    INVENTORY_KINDS,
    ManagedCleanupV3InventoryCursor,
    ManagedCleanupV3InventoryKindReceipt,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_legacy_v3_inventory_cursor_is_rejected_even_when_rehashed():
    snapshot = _sha("legacy-snapshot")
    last = _sha("legacy-last")
    body = {
        "schema_version": "memory-comparison-paged-cleanup-inventory-cursor.v3",
        "snapshot_sha256": snapshot,
        "kind": "facts",
        "last_canonical_key_sha256": last,
        "page_index": 1,
    }
    with pytest.raises(ManagedCleanupV3Error, match="inventory_cursor_invalid"):
        ManagedCleanupV3InventoryCursor(
            snapshot,
            "facts",
            last,
            1,
            commitment("inventory-cursor/v3", body),
            schema_version=body["schema_version"],
        )


def _sha(value: object) -> str:
    return hashlib.sha256(repr(value).encode()).hexdigest()


def _context(profile_id: str = LOCOMO_PROFILE):
    q_target, q_policy = _sha("qt"), _sha("qp")
    g_target, g_policy = _sha("gt"), _sha("gp")
    return build_context(
        profile_id=profile_id,
        manifest_context_sha256=_sha("manifest"),
        a1_terminal_commitment_sha256=_sha("a1"),
        run_id_sha256=_sha("run"),
        binding_commitment_sha256=_sha("binding"),
        publishable_profile_commitment_sha256=_sha("profile"),
        methodology_commitment_sha256=_sha("method"),
        dataset_sha256=str(PROFILE_ORACLES[profile_id]["dataset_sha256"]),
        admission_commitment_sha256=_sha("admit"),
        ingestion_root_sha256=_sha("ingest"),
        case_manifest_sha256=_sha("cases"),
        infinity_target_identity_sha256=_sha("target"),
        space_id="inventory-space",
        space_slug="inventory-space",
        cleanup_target_authority_sha256=_sha("cleanup-target"),
        qdrant_authority_sha256=commitment(
            "lane-authority/v4",
            {
                "lane": "qdrant",
                "target_commitment_sha256": q_target,
                "policy_commitment_sha256": q_policy,
            },
        ),
        qdrant_target_commitment_sha256=q_target,
        qdrant_policy_commitment_sha256=q_policy,
        graphiti_authority_sha256=commitment(
            "lane-authority/v4",
            {
                "lane": "graphiti",
                "target_commitment_sha256": g_target,
                "policy_commitment_sha256": g_policy,
            },
        ),
        graphiti_target_commitment_sha256=g_target,
        graphiti_policy_commitment_sha256=g_policy,
        cognee_policy_sha256=_sha("cognee"),
        namespace_policy_sha256=_sha("namespace"),
        cleanup_operation_stream_root_sha256=_sha("operations"),
        omitted_source_identity_root_sha256=str(
            PROFILE_ORACLES[profile_id]["omitted_source_identity_root_sha256"]
        ),
    )


def _counts(profile_id: str = LOCOMO_PROFILE) -> tuple[int, ...]:
    oracle = PROFILE_ORACLES[profile_id]
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


def _summaries(key: bytes, context, cleanup: str, authority: str):
    rows = []
    for kind, count in zip(INVENTORY_KINDS, _counts(context.profile_id), strict=True):
        root = _sha(("root", kind))
        payload = {
            "run_id_sha256": context.run_id_sha256,
            "context_sha256": context.context_sha256,
            "cleanup_receipt_sha256": cleanup,
            "kind": kind,
            "authority_terminal_sha256": authority,
            "expected_count": count,
            "ordered_rows_root_sha256": root,
            "complete": True,
        }
        rows.append(
            {
                "kind": kind,
                "expected_count": count,
                "ordered_rows_root_sha256": root,
                "row_mac_sha256": inventory_mac(
                    key, "managed-cleanup-v4/inventory-summary", payload
                ),
            }
        )
    return rows


class _Transaction:
    def __init__(self) -> None:
        self.started = self.rolled_back = self.committed = False

    async def start(self) -> None:
        self.started = True

    async def rollback(self) -> None:
        self.rolled_back = True

    async def commit(self) -> None:
        self.committed = True


class _Connection:
    def __init__(self, summaries, page_rows=()) -> None:
        self.summaries = summaries
        self.page_rows = page_rows
        self.tx = _Transaction()
        self.closed = False
        self.transaction_args = None
        self.fetch_calls = []
        self.execute_calls = []

    def transaction(self, **kwargs):
        self.transaction_args = kwargs
        return self.tx

    async def execute(self, sql, *args):
        self.execute_calls.append((sql, args))

    async def fetchrow(self, sql, *args):
        return ("snapshot-1", "10:20:")

    async def fetch(self, sql, *args):
        self.fetch_calls.append((sql, args))
        if sql == SUMMARY_SQL:
            return self.summaries
        return self.page_rows

    async def close(self):
        self.closed = True


@pytest.mark.anyio
async def test_snapshot_uses_one_rr_read_only_connection_and_session_bound_commitment():
    key, context = b"k" * 32, _context()
    cleanup, authority = _sha("cleanup"), _sha("authority")
    connection = _Connection(_summaries(key, context, cleanup, authority))

    async def connect():
        return connection

    snapshot = await AsyncPostgresManagedCleanupV3Inventory(
        connect=connect,
        hmac_key=key,
        statement_timeout_ms=123,
        idle_timeout_ms=456,
    ).begin_repeatable_read(
        context=context,
        authority_terminal_sha256=authority,
        cleanup_receipt_sha256=cleanup,
    )

    assert connection.transaction_args == {
        "isolation": "repeatable_read",
        "readonly": True,
    }
    assert connection.execute_calls[0][1] == ("123ms", "456ms")
    assert len(snapshot.snapshot_sha256) == 64
    await snapshot.abort()
    assert connection.tx.rolled_back and connection.closed


@pytest.mark.anyio
async def test_expected_count_plus_one_fails_closed_and_closes_snapshot():
    key, context = b"k" * 32, _context()
    cleanup, authority = _sha("cleanup"), _sha("authority")
    connection = _Connection(
        _summaries(key, context, cleanup, authority),
        page_rows=[{} for _ in range(11)],
    )

    async def connect():
        return connection

    snapshot = await AsyncPostgresManagedCleanupV3Inventory(
        connect=connect, hmac_key=key
    ).begin_repeatable_read(
        context=context,
        authority_terminal_sha256=authority,
        cleanup_receipt_sha256=cleanup,
    )
    with pytest.raises(ManagedCleanupV3Error):
        await snapshot.first(kind="memory_scopes", limit=512)
    assert connection.fetch_calls[-1][1][-1] == 11
    assert connection.tx.rolled_back and connection.closed


def test_row_mac_binds_kind_locator_and_exact_emitted_key():
    key = b"m" * 32
    canonical_key, locator_sha, row_sha = _sha("key"), _sha("locator"), _sha("row")
    payload = {
        "run_id_sha256": _sha("run"),
        "context_sha256": _sha("context"),
        "cleanup_receipt_sha256": _sha("cleanup"),
        "kind": "facts",
        "canonical_key_sha256": canonical_key,
        "locator_json": {"id": "fact-1"},
        "locator_sha256": locator_sha,
        "row_sha256": row_sha,
    }
    row = {
        **{
            name: payload[name]
            for name in ("canonical_key_sha256", "locator_json", "locator_sha256", "row_sha256")
        },
        "row_mac_sha256": inventory_mac(key, "managed-cleanup-v4/inventory-key", payload),
    }
    keys, hashes = authenticate_rows(
        [row],
        key,
        payload["run_id_sha256"],
        payload["context_sha256"],
        payload["cleanup_receipt_sha256"],
        "facts",
        None,
    )
    assert keys == (canonical_key,) and hashes == (row_sha,)
    json_row = replace_dict(row, locator_json='{"id":"fact-1"}')
    assert authenticate_rows(
        [json_row],
        key,
        payload["run_id_sha256"],
        payload["context_sha256"],
        payload["cleanup_receipt_sha256"],
        "facts",
        None,
    ) == ((canonical_key,), (row_sha,))
    with pytest.raises(ManagedCleanupV3Error):
        authenticate_rows(
            [replace_dict(row, row_mac_sha256="0" * 64)],
            key,
            payload["run_id_sha256"],
            payload["context_sha256"],
            payload["cleanup_receipt_sha256"],
            "facts",
            None,
        )


def replace_dict(value: dict[str, object], **changes: object) -> dict[str, object]:
    return {**value, **changes}


def test_queries_are_exact_keyset_without_offset_or_digest_sort():
    normalized = " ".join(PAGE_SQL.lower().split())
    assert "canonical_key_sha256 > $5" in normalized
    assert "order by canonical_key_sha256 limit $6" in normalized
    assert "offset" not in normalized and "digest(" not in normalized
    assert "complete is true" in " ".join(SUMMARY_SQL.lower().split())


def test_all_kinds_have_explicit_non_null_locator_schema():
    assert tuple(LOCATOR_FIELDS) == INVENTORY_KINDS
    assert canonical_locator(
        "fact_source_refs", {"id": 7, "fact_id": "fact-1", "fact_version": 1}
    ) == {"id": 7, "fact_id": "fact-1", "fact_version": 1}
    with pytest.raises(ManagedCleanupV3Error):
        canonical_locator(
            "qdrant_target_identities", {"kind": "qdrant_point", "identity_sha256": None}
        )


@pytest.mark.anyio
async def test_ordered_root_does_not_add_empty_page_after_exact_512():
    from infinity_context_adapters.postgres.managed_cleanup_v3_inventory_materializer import (
        _ordered_root,
    )

    context = _context()
    rows = [
        {"canonical_key_sha256": f"{index:064x}", "row_sha256": _sha(("row", index))}
        for index in range(1, 513)
    ]

    class Connection:
        calls = 0

        async def fetch(self, _sql, *_args):
            self.calls += 1
            return rows if self.calls == 1 else []

    connection = Connection()
    root = await _ordered_root(connection, context, _sha("cleanup"), "chunks")
    expected_page = commitment("inventory-row-page/v4", [row["row_sha256"] for row in rows])
    from infinity_context_adapters.postgres.managed_cleanup_v3_inventory_codec import (
        page_root,
    )

    assert root == page_root("inventory-empty-rows/v4", [expected_page])
    assert connection.calls == 2


@pytest.mark.anyio
async def test_query_cancellation_rolls_back_and_closes_connection():
    import asyncio

    key, context = b"k" * 32, _context()
    cleanup, authority = _sha("cleanup"), _sha("authority")

    class Connection(_Connection):
        async def fetch(self, sql, *args):
            if sql == SUMMARY_SQL:
                return self.summaries
            raise asyncio.CancelledError

    connection = Connection(_summaries(key, context, cleanup, authority))

    async def connect():
        return connection

    snapshot = await AsyncPostgresManagedCleanupV3Inventory(
        connect=connect, hmac_key=key
    ).begin_repeatable_read(
        context=context,
        authority_terminal_sha256=authority,
        cleanup_receipt_sha256=cleanup,
    )
    with pytest.raises(asyncio.CancelledError):
        await snapshot.first(kind="memory_scopes", limit=512)
    assert connection.tx.rolled_back and connection.closed


@pytest.mark.parametrize(
    "kind",
    (
        "qdrant_target_identities",
        "graphiti_target_names",
        "graphiti_target_uuids",
    ),
)
def test_non_empty_target_page_uses_exact_emitted_key_as_row_sha(kind):
    key = _sha(("target", kind))
    assert materialized_row_sha(kind, key, _sha("locator"), {"evidence": "bound"}) == key
    page = build_core_page(
        _sha("authority"),
        _sha("snapshot"),
        kind,
        0,
        None,
        None,
        (key,),
        (key,),
        True,
    )
    page.__post_init__()
    with pytest.raises(ManagedCleanupV3Error):
        build_core_page(
            _sha("authority"),
            _sha("snapshot"),
            kind,
            0,
            None,
            None,
            (key,),
            (_sha("different-row"),),
            True,
        )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("profile_id", "non_empty_targets"),
    (
        (LONGMEMEVAL_PROFILE, ("qdrant",)),
        (LOCOMO_PROFILE, ("graphiti_name", "graphiti_uuid")),
    ),
)
async def test_finalize_accepts_profile_non_empty_target_identity_roots(
    profile_id, non_empty_targets
):
    context = _context(profile_id)
    counts = _counts(profile_id)
    snapshot = object.__new__(AsyncPostgresManagedCleanupV3Snapshot)
    snapshot._context = context
    snapshot._authority = _sha(("authority", profile_id))
    snapshot._cleanup = _sha(("cleanup", profile_id))
    snapshot._snapshot = _sha(("snapshot", profile_id))
    snapshot._kind_index = len(INVENTORY_KINDS)
    snapshot._issued = None
    snapshot._closed = False
    snapshot._summaries = tuple(
        InventorySummary(kind, count, _sha(("summary", kind)), _sha(("mac", kind)))
        for kind, count in zip(INVENTORY_KINDS, counts, strict=True)
    )
    snapshot._receipts = [
        ManagedCleanupV3InventoryKindReceipt(
            kind, count, max(1, (count + 511) // 512), _sha(("rows", kind))
        )
        for kind, count in zip(INVENTORY_KINDS, counts, strict=True)
    ]
    snapshot._targets = {
        "qdrant": _sha(("target-root", "qdrant", profile_id)),
        "graphiti_name": _sha(("target-root", "graphiti-name", profile_id)),
        "graphiti_uuid": _sha(("target-root", "graphiti-uuid", profile_id)),
    }

    class Verifier:
        terminal = None

        def finalize(self, terminal):
            self.terminal = terminal
            return terminal

    class Transaction:
        committed = False

        async def commit(self):
            self.committed = True

    class Connection:
        closed = False

        async def close(self):
            self.closed = True

    snapshot._verifier = Verifier()
    snapshot._transaction = Transaction()
    snapshot._connection = Connection()

    terminal = await snapshot.finalize()

    for name in non_empty_targets:
        assert snapshot._targets[name] != commitment(
            f"inventory-empty-{name.replace('_', '-')}/v4", []
        )
    assert terminal.expected_qdrant_identity_count == counts[6]
    assert terminal.expected_graphiti_identity_count == counts[7]
    assert snapshot._transaction.committed and snapshot._connection.closed

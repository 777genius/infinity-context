from __future__ import annotations

from types import SimpleNamespace

import pytest
from infinity_context_adapters.postgres.managed_cleanup_v3_inventory_materializer import (
    INSERT_PENDING_SQL,
    LOCK_SQL,
    SEAL_SUMMARY_SQL,
    SNAPSHOT_SQL,
    AsyncPostgresManagedCleanupV3InventoryMaterializer,
    InventorySourcePage,
    InventorySourceRow,
)
from infinity_context_core.features.projection_receipts import ProjectionReceiptAuthenticator
from infinity_context_core.ports.managed_cleanup_v3_contracts import (
    ManagedCleanupV3Error,
    commitment,
)


class _Source:
    def __init__(self, page: InventorySourcePage) -> None:
        self.page = page
        self.calls = 0

    async def read_page(self, *_args, **_kwargs) -> InventorySourcePage:
        self.calls += 1
        return self.page


class _Connection:
    def __init__(self) -> None:
        self.execute_calls = []
        self.records = []
        self.executemany_calls = 0

    async def execute(self, sql, *args):
        self.execute_calls.append((sql, args))
        return "UPDATE 1"

    async def executemany(self, _sql, records):
        self.executemany_calls += 1
        self.records.extend(records)

    async def fetch(self, _sql, *_args):
        return [
            {
                "canonical_key_sha256": record[4],
                "row_sha256": record[7],
            }
            for record in sorted(self.records, key=lambda value: value[4])
        ]


class _Authenticator:
    def __init__(self, authenticated=None) -> None:
        self.authenticated = [] if authenticated is None else authenticated
        self.calls = []

    async def __call__(self, _connection, _context, terminal, session, kind, row):
        self.authenticated.append((terminal, session, kind, row.source_cursor))

    async def begin_verification(self, terminal, session):
        self.calls.append(("begin", terminal, session))

    async def begin_new_verification(self, terminal, session):
        self.calls.append(("begin_new", terminal, session))

    async def prepare_receipts(self, _connection, _context, terminal, session):
        self.calls.append(("prepare", terminal, session))

    async def flush_verification_page(self, terminal, session):
        self.calls.append(("flush", terminal, session))

    async def finalize_verification(self, terminal, session):
        self.calls.append(("finalize", terminal, session))

    async def abort_verification(self, terminal, session):
        self.calls.append(("abort", terminal, session))


def _context():
    return SimpleNamespace(
        run_id_sha256="1" * 64,
        context_sha256="2" * 64,
        __post_init__=lambda: None,
    )


def _row(locator: dict[str, object], cursor: object) -> InventorySourceRow:
    return InventorySourceRow(
        locator_json=locator,
        row_json={"canonical": "evidence"},
        source_cursor=cursor,
    )


def _materializer(source, authenticated):
    async def unused_connect():
        raise AssertionError("not used")

    async def writer_fence(_connection, _context):
        return None

    return AsyncPostgresManagedCleanupV3InventoryMaterializer(
        connect=unused_connect,
        source=source,
        authenticate_evidence=_Authenticator(authenticated),
        assert_writer_fenced=writer_fence,
        hmac_key=b"k" * 32,
        projection_authenticator=ProjectionReceiptAuthenticator(b"r" * 32),
    )


@pytest.mark.anyio
async def test_kind_lifecycle_inserts_pending_before_keys_then_seals():
    authenticated = []
    source = _Source(InventorySourcePage((_row({"id": "scope-1"}, "scope-1"),), True))
    materializer = _materializer(source, authenticated)
    connection = _Connection()

    count = await materializer._materialize_kind(
        connection,
        _context(),
        "3" * 64,
        "9" * 64,
        "4" * 64,
        "memory_scopes",
        1,
    )

    assert count == 1
    assert connection.execute_calls[0][0] == INSERT_PENDING_SQL
    assert connection.executemany_calls == 1
    assert connection.execute_calls[-1][0] == SEAL_SUMMARY_SQL
    assert authenticated == [("3" * 64, "9" * 64, "memory_scopes", "scope-1")]
    assert materializer._authenticate.calls == [("flush", "3" * 64, "9" * 64)]
    assert connection.records[0][5] == '{"id":"scope-1"}'


@pytest.mark.anyio
async def test_missing_or_extra_locator_fields_fail_before_key_insert():
    for locator in ({"wrong": "scope-1"}, {"id": "scope-1", "extra": "not-canonical"}):
        authenticated = []
        source = _Source(InventorySourcePage((_row(locator, "scope-1"),), True))
        materializer = _materializer(source, authenticated)
        connection = _Connection()

        with pytest.raises(
            ManagedCleanupV3Error,
            match="managed_cleanup_v3_materialization_locator_invalid",
        ):
            await materializer._materialize_kind(
                connection,
                _context(),
                "3" * 64,
                "9" * 64,
                "4" * 64,
                "memory_scopes",
                1,
            )

        assert connection.executemany_calls == 0
        assert all(sql != SEAL_SUMMARY_SQL for sql, _args in connection.execute_calls)


@pytest.mark.anyio
async def test_source_above_oracle_bound_fails_before_authentication_or_insert():
    authenticated = []
    source = _Source(
        InventorySourcePage(
            (
                _row({"id": "scope-1"}, "scope-1"),
                _row({"id": "scope-2"}, "scope-2"),
            ),
            True,
        )
    )
    materializer = _materializer(source, authenticated)
    connection = _Connection()

    with pytest.raises(
        ManagedCleanupV3Error,
        match="managed_cleanup_v3_materialization_count_invalid",
    ):
        await materializer._materialize_kind(
            connection,
            _context(),
            "3" * 64,
            "9" * 64,
            "4" * 64,
            "memory_scopes",
            1,
        )

    assert authenticated == []
    assert connection.executemany_calls == 0
    assert source.calls == 1


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_full_materialization_rolls_back_and_closes_on_oracle_overflow():
    class Context:
        profile_id = "mem0-locomo-top50-v1"
        run_id_sha256 = "1" * 64
        context_sha256 = "2" * 64

        def __post_init__(self):
            return None

    class Transaction:
        rolled_back = committed = False

        async def start(self):
            return None

        async def rollback(self):
            self.rolled_back = True

        async def commit(self):
            self.committed = True

    class Connection(_Connection):
        def __init__(self):
            super().__init__()
            self.tx = Transaction()
            self.closed = False

        def transaction(self, **kwargs):
            assert kwargs == {"isolation": "repeatable_read"}
            return self.tx

        async def fetchrow(self, _sql, *_args):
            return {"state": "cleanup_pending", "projection_cleanup_state": "pending"}

        async def fetchval(self, sql, *_args):
            return "10:20:" if sql == SNAPSHOT_SQL else 0

        async def close(self):
            self.closed = True

    rows = tuple(_row({"id": f"scope-{index}"}, index) for index in range(11))
    source = _Source(InventorySourcePage(rows, True))
    authenticated = []
    materializer = _materializer(source, authenticated)
    connection = Connection()

    async def connect():
        return connection

    materializer._connect = connect

    async def registered(*_args):
        return None

    materializer._authenticate_registered_authority = registered
    with pytest.raises(
        ManagedCleanupV3Error,
        match="managed_cleanup_v3_materialization_count_invalid",
    ):
        await materializer.materialize(
            context=Context(),
            authority_terminal_sha256="3" * 64,
            cleanup_receipt_sha256="4" * 64,
        )

    assert connection.tx.rolled_back and not connection.tx.committed
    assert connection.closed
    assert connection.executemany_calls == 0
    assert [call[0] for call in materializer._authenticate.calls] == [
        "begin_new",
        "prepare",
        "abort",
    ]
    assert materializer._authenticate.calls[0][2] == materializer._authenticate.calls[1][2]


@pytest.mark.anyio
@pytest.mark.parametrize("commit_fails", [False, True])
async def test_full_materialization_finalizes_expected_rows_before_commit(
    monkeypatch, commit_fails
):
    import infinity_context_adapters.postgres.managed_cleanup_v3_inventory_materializer as module

    class Context:
        profile_id = "mem0-locomo-top50-v1"
        run_id_sha256 = "1" * 64
        context_sha256 = "2" * 64

        def __post_init__(self):
            return None

    authenticator = _Authenticator()

    class Transaction:
        committed = False
        rolled_back = False

        async def start(self):
            return None

        async def rollback(self):
            self.rolled_back = True

        async def commit(self):
            assert authenticator.calls[-1][0:2] == ("finalize", "3" * 64)
            if commit_fails:
                raise RuntimeError("synthetic commit failure")
            self.committed = True

    class Connection(_Connection):
        def __init__(self):
            super().__init__()
            self.tx = Transaction()

        def transaction(self, **_kwargs):
            return self.tx

        async def fetchrow(self, _sql, *_args):
            return {"state": "cleanup_pending", "projection_cleanup_state": "pending"}

        async def fetchval(self, sql, *_args):
            return "10:20:" if sql == SNAPSHOT_SQL else 0

        async def close(self):
            return None

    source = _Source(InventorySourcePage((), True))
    materializer = _materializer(source, [])
    materializer._authenticate = authenticator
    connection = Connection()

    async def connect():
        return connection

    async def registered(*_args):
        return None

    async def materialize_kind(
        _connection, _context, _authority, _session, _cleanup, _kind, expected
    ):
        return expected

    materializer._connect = connect
    materializer._authenticate_registered_authority = registered
    materializer._materialize_kind = materialize_kind
    monkeypatch.setattr(module.secrets, "token_hex", lambda size: "a" * (size * 2))
    operation = materializer.materialize(
        context=Context(), authority_terminal_sha256="3" * 64, cleanup_receipt_sha256="4" * 64
    )
    if commit_fails:
        with pytest.raises(RuntimeError, match="synthetic commit failure"):
            await operation
    else:
        await operation

    expected_session = commitment(
        "inventory-materialization-verification-session/v4",
        {
            "run_id_sha256": "1" * 64,
            "context_sha256": "2" * 64,
            "authority_terminal_sha256": "3" * 64,
            "cleanup_receipt_sha256": "4" * 64,
            "pg_snapshot": "10:20:",
            "attempt_nonce": "a" * 64,
        },
    )
    expected_lifecycle = [
        "begin_new",
        "prepare",
        "finalize",
        *(["abort"] if commit_fails else []),
    ]
    assert [call[0] for call in authenticator.calls] == expected_lifecycle
    assert all(call[2] == expected_session for call in authenticator.calls)
    assert connection.tx.committed is not commit_fails
    assert connection.tx.rolled_back is commit_fails
    assert source.calls == 0


@pytest.mark.anyio
async def test_missing_registered_authority_fails_before_source_or_writes():
    class Transaction:
        async def start(self):
            return None

        async def rollback(self):
            return None

    class Connection(_Connection):
        def transaction(self, **_kwargs):
            return Transaction()

        async def fetchrow(self, sql, *_args):
            if sql == LOCK_SQL:
                return {"state": "cleanup_pending", "projection_cleanup_state": "pending"}
            return None

        async def close(self):
            return None

    source = _Source(InventorySourcePage((), True))
    materializer = _materializer(source, [])
    connection = Connection()

    async def connect():
        return connection

    materializer._connect = connect
    with pytest.raises(
        ManagedCleanupV3Error,
        match="managed_cleanup_v3_context_authority_missing",
    ):
        await materializer.materialize(
            context=_context(),
            authority_terminal_sha256="3" * 64,
            cleanup_receipt_sha256="4" * 64,
        )

    assert source.calls == 0
    assert connection.execute_calls == []
    assert materializer._authenticate.calls == []


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("passed_terminal", "tamper_mac"),
    [("3" * 64, False), ("8" * 64, True)],
    ids=("wrong-terminal", "tampered-mac"),
)
async def test_drifted_registered_authority_fails_before_source_or_writes(
    monkeypatch, passed_terminal, tamper_mac
):
    from infinity_context_adapters.postgres import (
        managed_cleanup_v3_registered_authority as authority_module,
    )

    class RegisteredContext:
        def __init__(self, **values):
            self._values = values
            for key, value in values.items():
                setattr(self, key, value)

        def __post_init__(self):
            return None

        def payload(self):
            return dict(self._values)

    class RegisteredAuthority(RegisteredContext):
        pass

    class Context(RegisteredContext):
        profile_id = "profile"
        run_id_sha256 = "1" * 64
        context_sha256 = "2" * 64
        a1_terminal_commitment_sha256 = "5" * 64
        cleanup_operation_stream_root_sha256 = "6" * 64
        omitted_source_identity_root_sha256 = "7" * 64

        def __init__(self):
            super().__init__(
                profile_id=self.profile_id,
                run_id_sha256=self.run_id_sha256,
                context_sha256=self.context_sha256,
                a1_terminal_commitment_sha256=self.a1_terminal_commitment_sha256,
                cleanup_operation_stream_root_sha256=(self.cleanup_operation_stream_root_sha256),
                omitted_source_identity_root_sha256=(self.omitted_source_identity_root_sha256),
            )

    context = Context()
    authority_json = {
        "profile_id": context.profile_id,
        "context_sha256": context.context_sha256,
        "a1_terminal_commitment_sha256": context.a1_terminal_commitment_sha256,
        "cleanup_operation_stream_root_sha256": (context.cleanup_operation_stream_root_sha256),
        "omitted_source_identity_root_sha256": (context.omitted_source_identity_root_sha256),
        "ordered_page_sha256": [],
        "terminal_commitment_sha256": "8" * 64,
    }
    registration = commitment(
        "projection-receipt-context-registration/v1",
        {
            "run_id_sha256": context.run_id_sha256,
            "context_sha256": context.context_sha256,
            "authority_terminal_sha256": "8" * 64,
            "context": context.payload(),
            "authority": RegisteredAuthority(**authority_json).payload(),
        },
    )
    registration_mac = ProjectionReceiptAuthenticator(b"r" * 32).sign(
        "projection-context-authority", registration
    )

    class Transaction:
        async def start(self):
            return None

        async def rollback(self):
            return None

    class Connection(_Connection):
        def transaction(self, **_kwargs):
            return Transaction()

        async def fetchrow(self, sql, *_args):
            if sql == LOCK_SQL:
                return {"state": "cleanup_pending", "projection_cleanup_state": "pending"}
            return {
                "run_id_sha256": context.run_id_sha256,
                "context_sha256": context.context_sha256,
                "authority_terminal_sha256": "8" * 64,
                "context_json": context.payload(),
                "authority_json": authority_json,
                "registration_sha256": registration,
                "registration_mac_sha256": "a" * 64 if tamper_mac else registration_mac,
            }

        async def close(self):
            return None

    monkeypatch.setattr(authority_module, "ManagedCleanupV3Context", RegisteredContext)
    monkeypatch.setattr(authority_module, "ManagedCleanupV3Authority", RegisteredAuthority)
    source = _Source(InventorySourcePage((), True))
    materializer = _materializer(source, [])
    connection = Connection()

    async def connect():
        return connection

    materializer._connect = connect
    with pytest.raises(
        ManagedCleanupV3Error,
        match="managed_cleanup_v3_context_authority_invalid",
    ):
        await materializer.materialize(
            context=context,
            authority_terminal_sha256=passed_terminal,
            cleanup_receipt_sha256="4" * 64,
        )

    assert source.calls == 0
    assert connection.execute_calls == []
    assert materializer._authenticate.calls == []


def _replay_evidence(module, *, tamper_key_mac=False, partial=False):
    terminal, cleanup = "3" * 64, "4" * 64
    locator = {"id": "scope-1"}
    locator_sha = commitment("inventory-locator/v4", {"kind": "memory_scopes", "locator": locator})
    canonical_key = commitment(
        "inventory-canonical-key/v4", {"kind": "memory_scopes", "locator": locator}
    )
    row_sha = "d" * 64
    key_payload = {
        "run_id_sha256": "1" * 64,
        "context_sha256": "2" * 64,
        "cleanup_receipt_sha256": cleanup,
        "kind": "memory_scopes",
        "canonical_key_sha256": canonical_key,
        "locator_json": locator,
        "locator_sha256": locator_sha,
        "row_sha256": row_sha,
    }
    key_row = {
        **key_payload,
        "row_mac_sha256": (
            "0" * 64
            if tamper_key_mac
            else module.inventory_mac(b"k" * 32, "managed-cleanup-v4/inventory-key", key_payload)
        ),
    }
    empty_page = commitment("inventory-row-page/v4", [])
    one_page = commitment("inventory-row-page/v4", [row_sha])
    summaries = []
    for index, kind in enumerate(module.INVENTORY_KINDS):
        count = 1 if index == 0 else 0
        root = module.page_root("inventory-empty-rows/v4", [one_page if count else empty_page])
        payload = {
            "run_id_sha256": "1" * 64,
            "context_sha256": "2" * 64,
            "cleanup_receipt_sha256": cleanup,
            "kind": kind,
            "authority_terminal_sha256": terminal,
            "expected_count": count,
            "ordered_rows_root_sha256": root,
            "complete": True,
        }
        summaries.append(
            {
                **payload,
                "row_mac_sha256": module.inventory_mac(
                    b"k" * 32, "managed-cleanup-v4/inventory-summary", payload
                ),
            }
        )
    return summaries[:-1] if partial else summaries, key_row


@pytest.mark.anyio
async def test_exact_complete_pg_replay_authenticates_and_bypasses_claims(monkeypatch):
    import infinity_context_adapters.postgres.managed_cleanup_v3_inventory_materializer as module

    summaries, key_row = _replay_evidence(module)

    class Transaction:
        committed = False

        async def start(self):
            return None

        async def commit(self):
            self.committed = True

        async def rollback(self):
            raise AssertionError("exact replay must not roll back")

    class Connection(_Connection):
        def __init__(self):
            super().__init__()
            self.tx = Transaction()
            self.closed = False

        def transaction(self, **_kwargs):
            return self.tx

        async def fetchrow(self, _sql, *_args):
            return {"state": "cleanup_pending", "projection_cleanup_state": "pending"}

        async def fetch(self, sql, *args):
            if sql == module.REPLAY_SUMMARIES_SQL:
                return summaries
            if sql == module.REPLAY_KEYS_SQL and args[3] == "memory_scopes":
                return [key_row]
            return []

        async def fetchval(self, *_args):
            raise AssertionError("exact replay must not create a new verification session")

        async def close(self):
            self.closed = True

    monkeypatch.setattr(module, "_expected_counts", lambda _context: (1,) + (0,) * 14)
    source = _Source(InventorySourcePage((), True))
    materializer = _materializer(source, [])
    connection = Connection()

    async def registered(*_args):
        return None

    async def connect():
        return connection

    materializer._authenticate_registered_authority = registered
    materializer._connect = connect
    await materializer.materialize(
        context=_context(),
        authority_terminal_sha256="3" * 64,
        cleanup_receipt_sha256="4" * 64,
    )

    assert connection.tx.committed and connection.closed
    assert connection.execute_calls == []
    assert materializer._authenticate.calls == []
    assert source.calls == 0


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["partial", "tampered-key-mac"])
async def test_ambiguous_or_tampered_pg_replay_never_resets_claims(monkeypatch, mode):
    import infinity_context_adapters.postgres.managed_cleanup_v3_inventory_materializer as module

    summaries, key_row = _replay_evidence(
        module, partial=mode == "partial", tamper_key_mac=mode == "tampered-key-mac"
    )

    class Connection(_Connection):
        async def fetch(self, sql, *args):
            if sql == module.REPLAY_SUMMARIES_SQL:
                return summaries
            if sql == module.REPLAY_KEYS_SQL and args[3] == "memory_scopes":
                return [key_row]
            return []

    monkeypatch.setattr(module, "_expected_counts", lambda _context: (1,) + (0,) * 14)
    materializer = _materializer(_Source(InventorySourcePage((), True)), [])

    with pytest.raises(ManagedCleanupV3Error):
        await materializer._authenticate_complete_materialization(
            Connection(), _context(), "3" * 64, "4" * 64
        )

    assert materializer._authenticate.calls == []

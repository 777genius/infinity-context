"""Fail-closed authentication for cleanup v3 canonical source evidence."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from infinity_context_core.features.projection_receipts import (
    ProjectionReceiptAuthenticator,
)
from infinity_context_core.ports.managed_cleanup_v3_contracts import (
    ManagedCleanupV3Context,
    ManagedCleanupV3Error,
)

from infinity_context_adapters.postgres.managed_cleanup_v3_inventory_materializer import (
    InventorySourceRow,
)
from infinity_context_adapters.postgres.managed_cleanup_v3_projection_evidence import (
    verify_projection_locator,
)

_CANONICAL_KINDS = {
    "memory_scopes",
    "memory_threads",
    "facts",
    "fact_source_refs",
    "documents",
    "chunks",
}
_TARGET_KINDS = {
    "qdrant_target_identities",
    "graphiti_target_names",
    "graphiti_target_uuids",
}
_JOB_KINDS = {
    "qdrant_upsert_jobs",
    "qdrant_delete_jobs",
    "graphiti_upsert_jobs",
    "graphiti_delete_jobs",
    "cleanup_outbox_receipts",
}


class CleanupV3ExpectedRowAuthorityPort(Protocol):
    """Bounded A2-authority lookup required to authenticate canonical row contents."""

    async def verify_expected_row(
        self,
        *,
        context: ManagedCleanupV3Context,
        authority_terminal_sha256: str,
        verification_session_sha256: str,
        kind: str,
        locator_json: Mapping[str, object],
        row_json: Mapping[str, object],
    ) -> None: ...

    def begin_verification(
        self, authority_terminal_sha256: str, verification_session_sha256: str
    ) -> None: ...

    def begin_new_verification(
        self, authority_terminal_sha256: str, verification_session_sha256: str
    ) -> None: ...

    def finalize_verification(
        self, authority_terminal_sha256: str, verification_session_sha256: str
    ) -> None: ...

    def flush_verification_page(
        self, authority_terminal_sha256: str, verification_session_sha256: str
    ) -> None: ...

    def abort_verification(
        self, authority_terminal_sha256: str, verification_session_sha256: str
    ) -> None: ...


class CleanupV3ReceiptProofScratchPort(Protocol):
    """Session-bound receipt preflight and exact logical-row consumption."""

    def begin_new(
        self, authority_terminal_sha256: str, verification_session_sha256: str
    ) -> None: ...

    async def prepare_receipts(
        self,
        connection: Any,
        context: ManagedCleanupV3Context,
        authority_terminal_sha256: str,
        verification_session_sha256: str,
    ) -> None: ...

    def consume(
        self,
        authority_terminal_sha256: str,
        verification_session_sha256: str,
        inventory_kind: str,
        outbox: Mapping[str, object],
        receipt: Mapping[str, object],
        link: Mapping[str, object],
        identity: Mapping[str, object],
    ) -> None: ...

    def finalize(
        self, authority_terminal_sha256: str, verification_session_sha256: str
    ) -> None: ...

    def flush_verification_page(
        self, authority_terminal_sha256: str, verification_session_sha256: str
    ) -> None: ...

    def abort(self, authority_terminal_sha256: str, verification_session_sha256: str) -> None: ...


class ManagedCleanupV3SourceEvidenceAuthenticator:
    """Verify joined canonical/receipt evidence without provider access."""

    def __init__(
        self,
        authenticator: ProjectionReceiptAuthenticator,
        expected_rows: CleanupV3ExpectedRowAuthorityPort,
        receipt_scratch: CleanupV3ReceiptProofScratchPort,
    ) -> None:
        if type(authenticator) is not ProjectionReceiptAuthenticator:
            raise ValueError("projection receipt authenticator is required")
        self._authenticator = authenticator
        if expected_rows is None:
            raise ValueError("cleanup v3 expected-row authority is required")
        self._expected_rows = expected_rows
        if receipt_scratch is None:
            raise ValueError("cleanup v3 receipt scratch is required")
        self._receipt_scratch = receipt_scratch

    async def begin_verification(
        self, authority_terminal_sha256: str, verification_session_sha256: str
    ) -> None:
        self._expected_rows.begin_verification(
            authority_terminal_sha256, verification_session_sha256
        )

    async def begin_new_verification(
        self, authority_terminal_sha256: str, verification_session_sha256: str
    ) -> None:
        self._expected_rows.begin_new_verification(
            authority_terminal_sha256, verification_session_sha256
        )
        try:
            self._receipt_scratch.begin_new(authority_terminal_sha256, verification_session_sha256)
        except BaseException:
            self._expected_rows.abort_verification(
                authority_terminal_sha256, verification_session_sha256
            )
            raise

    async def prepare_receipts(
        self,
        connection: Any,
        context: ManagedCleanupV3Context,
        authority_terminal_sha256: str,
        verification_session_sha256: str,
    ) -> None:
        await self._receipt_scratch.prepare_receipts(
            connection,
            context,
            authority_terminal_sha256,
            verification_session_sha256,
        )

    async def flush_verification_page(
        self, authority_terminal_sha256: str, verification_session_sha256: str
    ) -> None:
        try:
            self._expected_rows.flush_verification_page(
                authority_terminal_sha256, verification_session_sha256
            )
            self._receipt_scratch.flush_verification_page(
                authority_terminal_sha256, verification_session_sha256
            )
        except BaseException as exc:
            try:
                await self.abort_verification(
                    authority_terminal_sha256, verification_session_sha256
                )
            except BaseException as abort_error:
                exc.add_note(f"verification page abort failed: {type(abort_error).__name__}")
            raise

    async def finalize_verification(
        self, authority_terminal_sha256: str, verification_session_sha256: str
    ) -> None:
        self._expected_rows.finalize_verification(
            authority_terminal_sha256, verification_session_sha256
        )
        try:
            self._receipt_scratch.finalize(authority_terminal_sha256, verification_session_sha256)
        except BaseException as exc:
            try:
                self._expected_rows.abort_verification(
                    authority_terminal_sha256, verification_session_sha256
                )
            except BaseException as abort_error:
                exc.add_note(f"expected-row abort failed: {type(abort_error).__name__}")
            raise

    async def abort_verification(
        self, authority_terminal_sha256: str, verification_session_sha256: str
    ) -> None:
        failure: BaseException | None = None
        try:
            self._expected_rows.abort_verification(
                authority_terminal_sha256, verification_session_sha256
            )
        except BaseException as exc:
            failure = exc
        try:
            self._receipt_scratch.abort(authority_terminal_sha256, verification_session_sha256)
        except BaseException as exc:
            if failure is None:
                failure = exc
            else:
                failure.add_note(f"receipt scratch abort failed: {type(exc).__name__}")
        if failure is not None:
            raise failure

    async def __call__(
        self,
        _connection: Any,
        context: ManagedCleanupV3Context,
        authority_terminal_sha256: str,
        verification_session_sha256: str,
        kind: str,
        source_row: InventorySourceRow,
    ) -> None:
        context.__post_init__()
        if type(source_row) is not InventorySourceRow:
            _fail("row_invalid")
        locator = dict(source_row.locator_json)
        row = dict(source_row.row_json)
        if kind in _CANONICAL_KINDS:
            _verify_canonical(context, kind, locator, row)
            await self._expected_rows.verify_expected_row(
                context=context,
                authority_terminal_sha256=authority_terminal_sha256,
                verification_session_sha256=verification_session_sha256,
                kind=kind,
                locator_json=locator,
                row_json=row,
            )
            return
        if kind == "unsupported_rows":
            _verify_unsupported(locator, row)
            return
        if kind not in _TARGET_KINDS | _JOB_KINDS:
            _fail("kind_invalid")
        await self._verify_projection(
            context,
            authority_terminal_sha256,
            verification_session_sha256,
            kind,
            locator,
            row,
        )

    async def _verify_projection(
        self,
        context: ManagedCleanupV3Context,
        authority_terminal_sha256: str,
        verification_session_sha256: str,
        kind: str,
        locator: dict[str, object],
        evidence: dict[str, object],
    ) -> None:
        outbox = _mapping(evidence, "outbox")
        receipt = _mapping(evidence, "receipt")
        link = _mapping(evidence, "link")
        identity = _mapping(evidence, "identity")
        canonical = _mapping(evidence, "canonical_source")
        if set(evidence) != {"outbox", "receipt", "link", "identity", "canonical_source"}:
            _fail("evidence_shape_invalid")
        lane = str(receipt.get("lane"))
        operation = str(receipt.get("operation"))
        expected_authority = {
            "qdrant": context.qdrant_authority_sha256,
            "graphiti": context.graphiti_authority_sha256,
        }.get(lane)
        if (
            expected_authority is None
            or receipt.get("run_id_sha256") != context.run_id_sha256
            or receipt.get("context_sha256") != context.context_sha256
            or receipt.get("space_id") != context.space_id
            or receipt.get("target_authority_sha256") != expected_authority
            or receipt.get("worker_authority_sha256") != self._authenticator.authority_sha256
            or receipt.get("result_state") != ("present" if operation == "upsert" else "absent")
            or outbox.get("id") != receipt.get("outbox_id")
            or outbox.get("status") != "done"
            or canonical.get("id") != identity.get("canonical_source_id")
            or canonical.get("space_id") != context.space_id
            or canonical.get("memory_scope_id") != receipt.get("memory_scope_id")
            or canonical.get("thread_id") != receipt.get("thread_id")
            or canonical.get("status") != "deleted"
            or (
                lane == "graphiti"
                and operation == "upsert"
                and (
                    canonical.get("version") != receipt.get("aggregate_version")
                    or canonical.get("version") != outbox.get("aggregate_version")
                )
            )
        ):
            _fail("binding_invalid")
        await self._expected_rows.verify_expected_row(
            context=context,
            authority_terminal_sha256=authority_terminal_sha256,
            verification_session_sha256=verification_session_sha256,
            kind="chunks" if lane == "qdrant" else "facts",
            locator_json={"id": canonical.get("id")},
            row_json=canonical,
        )
        self._receipt_scratch.consume(
            authority_terminal_sha256,
            verification_session_sha256,
            kind,
            outbox,
            receipt,
            link,
            identity,
        )
        verify_projection_locator(kind, locator, outbox, identity, _TARGET_KINDS)


def _verify_canonical(
    context: ManagedCleanupV3Context,
    kind: str,
    locator: dict[str, object],
    row: dict[str, object],
) -> None:
    if kind == "fact_source_refs":
        if any(locator.get(name) != row.get(name) for name in ("id", "fact_id", "fact_version")):
            _fail("canonical_invalid")
        return
    if locator != {"id": row.get("id")} or row.get("space_id") != context.space_id:
        _fail("canonical_invalid")
    if row.get("status") != "deleted":
        _fail("canonical_lifecycle_invalid")


def _verify_unsupported(locator: dict[str, object], row: dict[str, object]) -> None:
    table = locator.get("source_table")
    source_pk = locator.get("source_pk")
    marker = row.pop("__unsupported_pk", None)
    if (
        type(table) is not str
        or not table
        or type(source_pk) is not str
        or not source_pk
        or marker != source_pk
    ):
        _fail("unsupported_invalid")


def _mapping(value: Mapping[str, object], name: str) -> Mapping[str, object]:
    item = value.get(name)
    if not isinstance(item, Mapping):
        _fail("evidence_shape_invalid")
    return item


def _fail(suffix: str):
    raise ManagedCleanupV3Error(f"managed_cleanup_v3_source_authentication_{suffix}")


__all__ = (
    "CleanupV3ExpectedRowAuthorityPort",
    "CleanupV3ReceiptProofScratchPort",
    "ManagedCleanupV3SourceEvidenceAuthenticator",
)

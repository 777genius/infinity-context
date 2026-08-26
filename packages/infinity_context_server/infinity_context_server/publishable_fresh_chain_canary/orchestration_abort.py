"""Durable orchestration abort after authenticated runtime extraction."""

from __future__ import annotations

from contextlib import suppress

from .contracts import FreshChainCanaryError, FreshChainCleanupResult, canonical_sha256
from .ledger import FreshChainCanaryLedger
from .ledger_models import FreshChainSnapshot


def abort_after_post_extraction_failure(
    *,
    session: object,
    ledger: FreshChainCanaryLedger,
    namespace_commitment_sha256: str,
    error: BaseException,
) -> None:
    """Best-effort durable abort plus mandatory namespace cleanup."""

    try:
        snapshot = ledger.read_snapshot()
    except BaseException:
        with suppress(BaseException):
            session.abort_after_extraction()
        return
    if snapshot.completed or snapshot.cleanup is not None:
        return
    extraction = snapshot.stages[0]
    if extraction.status != "succeeded":
        authenticated = getattr(
            session,
            "has_authenticated_runtime_extraction_evidence",
            None,
        )
        try:
            if not callable(authenticated) or authenticated() is not True:
                return
            cleanup = session.abort_after_extraction()
        except BaseException:
            return
        if (
            type(cleanup) is not FreshChainCleanupResult
            or cleanup.namespace_commitment_sha256 != namespace_commitment_sha256
        ):
            return
    if snapshot.abort_reason_sha256 is None:
        reason = canonical_sha256(
            {
                "error_code": getattr(error, "code", type(error).__name__),
                "failure_domain": "fresh-chain-post-extraction-local-abort/v1",
                "stage_statuses": [record.status for record in snapshot.stages],
            }
        )
        try:
            snapshot = ledger.record_local_abort(reason_sha256=reason)
        except BaseException:
            with suppress(BaseException):
                session.abort_after_extraction()
            return
    try:
        finish_local_abort(
            session=session,
            ledger=ledger,
            snapshot=snapshot,
            namespace_commitment_sha256=namespace_commitment_sha256,
        )
    except BaseException:
        # The durable abort event makes the next invocation clean up before
        # retrieval or another dispatch.
        return


def finish_local_abort(
    *,
    session: object,
    ledger: FreshChainCanaryLedger,
    snapshot: FreshChainSnapshot,
    namespace_commitment_sha256: str,
) -> FreshChainSnapshot:
    if snapshot.abort_reason_sha256 is None:
        _fail("fresh_chain_local_abort_missing")
    if snapshot.cleanup is None:
        cleanup = session.abort_after_extraction()
        if (
            type(cleanup) is not FreshChainCleanupResult
            or cleanup.namespace_commitment_sha256 != namespace_commitment_sha256
        ):
            _fail("fresh_chain_cleanup_binding_invalid")
        snapshot = ledger.record_cleanup(
            namespace_commitment_sha256=cleanup.namespace_commitment_sha256,
            cleanup_authority_sha256=cleanup.cleanup_authority_sha256,
            receipt_id=cleanup.receipt_id,
            receipt_sha256=cleanup.receipt_sha256,
            outcome_sha256=cleanup.outcome_sha256,
            deleted=cleanup.deleted,
            operation_count=cleanup.operation_count,
            residual_count=cleanup.residual_count,
        )
    return ledger.terminate_failed()


def _fail(code: str) -> None:
    raise FreshChainCanaryError(code) from None


__all__ = ("abort_after_post_extraction_failure", "finish_local_abort")

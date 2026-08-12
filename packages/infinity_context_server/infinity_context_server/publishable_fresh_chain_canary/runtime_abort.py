"""Post-extraction abort path kept separate from the five-stage runtime."""

from __future__ import annotations

from .contracts import (
    FreshChainCanaryError,
    FreshChainCleanupResult,
    FreshChainLookupDisposition,
)


def abort_after_extraction(session: object) -> FreshChainCleanupResult:
    """Recover local extraction evidence and durably delete without retrieval."""

    with session._lock:
        session._require_open()
        if session._cleanup_result is not None:
            return session._cleanup_result
        extraction = session._results.get(0)
        if extraction is None:
            intent = session.prepare_call(
                stage="mem0_extraction",
                prior_results=(),
                retrieval_handoff=None,
            )
            observed = session.lookup(intent)
            if observed.disposition is not FreshChainLookupDisposition.TERMINAL:
                observed = session.recover(intent)
            if observed.disposition is FreshChainLookupDisposition.TERMINAL:
                extraction = observed.result
        if extraction is None or extraction.stage != "mem0_extraction":
            _fail("fresh_chain_abort_before_extraction")
        try:
            result = session._cleanup_port.abort_after_extraction(
                extraction=extraction,
                namespace_id=session._namespace_id,
                namespace_commitment_sha256=session._namespace_commitment_sha256,
            )
        except Exception:
            _fail("fresh_chain_cleanup_failed")
        if (
            type(result) is not FreshChainCleanupResult
            or result.namespace_commitment_sha256 != session._namespace_commitment_sha256
            or result.deleted is not True
            or result.operation_count != 1
            or result.residual_count != 0
        ):
            _fail("fresh_chain_cleanup_invalid")
        session._cleanup_result = result
        return result


def _fail(code: str) -> None:
    raise FreshChainCanaryError(code) from None


__all__ = ("abort_after_extraction",)

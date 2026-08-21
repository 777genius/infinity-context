"""Failure, cleanup, and failed-replay contracts for the fresh-chain canary."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from infinity_context_server.publishable_fresh_chain_canary.authorization import (
    FRESH_CHAIN_ONE_PLUS_FOUR_AUTHORIZATION,
)
from infinity_context_server.publishable_fresh_chain_canary.contracts import (
    FreshChainCallFailure,
    FreshChainCallIntent,
    FreshChainCallResult,
    FreshChainCanaryError,
    FreshChainCleanupResult,
    FreshChainLookup,
    FreshChainLookupDisposition,
    FreshChainUsage,
)
from infinity_context_server.publishable_fresh_chain_canary.ledger_models import (
    FreshChainFailureDisposition,
    FreshChainLedgerError,
    provider_disposition_sha256,
)
from infinity_context_server.publishable_fresh_chain_canary.orchestrator import (
    FreshChainCanaryOrchestrator,
)
from test_publishable_fresh_chain_canary_orchestrator import (
    _Factory,
    _prepared,
    _Session,
    _sha,
)


class _DuplicateSession(_Session):
    def dispatch(self, intent: FreshChainCallIntent) -> FreshChainCallResult:
        result = super().dispatch(intent)
        extraction = self.results.get("mem0_extraction")
        if intent.stage == "infinity_answer" and extraction is not None:
            result = replace(
                result,
                receipt_id=extraction.receipt_id,
                physical_receipt_sha256=extraction.physical_receipt_sha256,
            )
            self.results[intent.stage] = result
        return result


class _DuplicateFactory(_Factory):
    def open_fresh_chain_session(self, **arguments: object) -> _Session:
        self.open_count += 1
        session = _DuplicateSession(
            namespace_id=arguments["namespace_id"],
            namespace_commitment_sha256=arguments["namespace_commitment_sha256"],
            source_commitment_sha256=arguments["source_commitment_sha256"],
        )
        self.sessions.append(session)
        return session


class _PostExtractionFailureSession(_Session):
    def __init__(self, *, failure_phase: str, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.failure_phase = failure_phase

    def prepare_call(self, **kwargs: object) -> FreshChainCallIntent:
        if self.failure_phase == "render" and kwargs["stage"] == "infinity_answer":
            raise FreshChainCanaryError("simulated_render_failure")
        return super().prepare_call(**kwargs)

    def capture_retrieval(self, result: FreshChainCallResult):
        if self.failure_phase == "retrieval":
            raise FreshChainCanaryError("simulated_retrieval_failure")
        return super().capture_retrieval(result)


class _PostExtractionFailureFactory(_Factory):
    def __init__(self, failure_phase: str) -> None:
        super().__init__()
        self.failure_phase = failure_phase

    def open_fresh_chain_session(self, **arguments: object) -> _Session:
        self.open_count += 1
        session = _PostExtractionFailureSession(
            failure_phase=self.failure_phase,
            namespace_id=arguments["namespace_id"],
            namespace_commitment_sha256=arguments["namespace_commitment_sha256"],
            source_commitment_sha256=arguments["source_commitment_sha256"],
        )
        self.sessions.append(session)
        return session


class _KnownFailureSession(_Session):
    def __init__(self, *, known_failure: FreshChainCallFailure | None = None, **kwargs: object):
        super().__init__(**kwargs)
        self.failure = known_failure
        self.physical_dispatch_count = 0
        self.fail_cleanup_once = False

    def dispatch(
        self,
        intent: FreshChainCallIntent,
    ) -> FreshChainCallResult | FreshChainCallFailure:
        assert intent.stage == "mem0_extraction"
        self.events.append("dispatch:mem0_extraction")
        self.physical_dispatch_count += 1
        disposition = FreshChainFailureDisposition.PROVIDER_FAILED
        self.failure = FreshChainCallFailure(
            stage=intent.stage,
            ordinal=intent.ordinal,
            intent_sha256=intent.intent_sha256,
            physical_receipt_sha256=_sha("known failure receipt"),
            receipt_id="known-failure:0",
            usage=FreshChainUsage(4, 2, 6),
            provider_disposition=disposition,
            transport_dispatched=True,
            commitments={
                "admission_commitment_sha256": _sha("failure admission"),
                "operation_id_sha256": _sha("failure operation"),
                "output_text_sha256": _sha("failure output"),
                "provider_disposition_sha256": provider_disposition_sha256(disposition),
                "request_body_sha256": intent.request_sha256,
                "run_identity_commitment_sha256": _sha("failure run identity"),
                "runtime_binding_commitment_sha256": _sha("failure runtime binding"),
                "scope_sha256": _sha("failure scope"),
                "source_projection_commitment_sha256": (intent.source_projection_commitment_sha256),
                "unit_identity_sha256": _sha("failure unit identity"),
                "unit_sha256": _sha("failure unit"),
            },
        )
        return self.failure

    def recover(self, intent: FreshChainCallIntent) -> FreshChainLookup:
        self.events.append(f"recover:{intent.stage}")
        assert self.failure is not None
        return FreshChainLookup(
            FreshChainLookupDisposition.FAILED,
            intent.intent_sha256,
            failure=replace(
                self.failure,
                intent_sha256=intent.intent_sha256,
                transport_dispatched=False,
            ),
        )

    def cleanup(
        self,
        failure: FreshChainCallFailure | None = None,
    ) -> FreshChainCleanupResult:
        assert failure is not None
        self.events.append("cleanup")
        self.cleanup_count += 1
        if self.fail_cleanup_once:
            self.fail_cleanup_once = False
            raise FreshChainCanaryError("simulated_cleanup_interruption")
        return FreshChainCleanupResult(
            namespace_commitment_sha256=self.namespace_commitment_sha256,
            cleanup_authority_sha256=_sha("failed cleanup authority"),
            receipt_id="failed-cleanup:0",
            receipt_sha256=_sha("failed cleanup receipt"),
            outcome_sha256=_sha("failed cleanup outcome"),
            deleted=True,
            operation_count=1,
            residual_count=0,
        )

    def abort_after_extraction(self) -> FreshChainCleanupResult:
        raise AssertionError("provider failure cleanup must use the failure-bound path")


class _KnownFailureFactory(_Factory):
    def __init__(self, *, known_failure: FreshChainCallFailure | None = None) -> None:
        super().__init__()
        self.known_failure = known_failure
        self.fail_cleanup_once = False

    def open_fresh_chain_session(self, **arguments: object) -> _KnownFailureSession:
        self.open_count += 1
        session = _KnownFailureSession(
            namespace_id=arguments["namespace_id"],
            namespace_commitment_sha256=arguments["namespace_commitment_sha256"],
            source_commitment_sha256=arguments["source_commitment_sha256"],
            known_failure=self.known_failure,
        )
        session.fail_cleanup_once = self.fail_cleanup_once
        self.sessions.append(session)
        return session


def test_duplicate_physical_receipt_stops_before_remaining_calls(tmp_path: Path) -> None:
    files = _prepared(tmp_path)
    factory = _DuplicateFactory()

    with pytest.raises(FreshChainLedgerError, match="fresh_chain_receipt_duplicate"):
        FreshChainCanaryOrchestrator(factory).run(
            config=files.config,
            secrets=files.secrets,
            authorization=FRESH_CHAIN_ONE_PLUS_FOUR_AUTHORIZATION,
        )

    dispatches = [event for event in factory.sessions[0].events if event.startswith("dispatch:")]
    assert dispatches == ["dispatch:mem0_extraction", "dispatch:infinity_answer"]
    assert factory.sessions[0].cleanup_count == 1

    replay = _DuplicateFactory()
    with pytest.raises(FreshChainCanaryError, match="fresh_chain_prior_terminal_failed"):
        FreshChainCanaryOrchestrator(replay).run(
            config=files.config,
            secrets=files.secrets,
            authorization=FRESH_CHAIN_ONE_PLUS_FOUR_AUTHORIZATION,
        )
    assert replay.open_count == 0


@pytest.mark.parametrize("phase", ("render", "retrieval"))
def test_post_extraction_local_failure_cleans_and_terminal_replay_is_zero_call(
    tmp_path: Path,
    phase: str,
) -> None:
    files = _prepared(tmp_path)
    factory = _PostExtractionFailureFactory(phase)
    with pytest.raises(FreshChainCanaryError, match=f"simulated_{phase}_failure"):
        FreshChainCanaryOrchestrator(factory).run(
            config=files.config,
            secrets=files.secrets,
            authorization=FRESH_CHAIN_ONE_PLUS_FOUR_AUTHORIZATION,
        )
    assert factory.sessions[0].cleanup_count == 1

    replay = _PostExtractionFailureFactory(phase)
    with pytest.raises(FreshChainCanaryError, match="fresh_chain_prior_terminal_failed"):
        FreshChainCanaryOrchestrator(replay).run(
            config=files.config,
            secrets=files.secrets,
            authorization=FRESH_CHAIN_ONE_PLUS_FOUR_AUTHORIZATION,
        )
    assert replay.open_count == 0


def test_known_failure_restart_recovers_cleanup_and_terminal_without_redispatch(
    tmp_path: Path,
) -> None:
    files = _prepared(tmp_path)
    interrupted = _KnownFailureFactory()
    interrupted.fail_cleanup_once = True
    with pytest.raises(FreshChainCanaryError, match="simulated_cleanup_interruption"):
        FreshChainCanaryOrchestrator(interrupted).run(
            config=files.config,
            secrets=files.secrets,
            authorization=FRESH_CHAIN_ONE_PLUS_FOUR_AUTHORIZATION,
        )
    failure = interrupted.sessions[0].failure
    assert failure is not None
    assert interrupted.sessions[0].physical_dispatch_count == 1

    recovery = _KnownFailureFactory(known_failure=failure)
    with pytest.raises(FreshChainCanaryError, match="fresh_chain_known_provider_failure"):
        FreshChainCanaryOrchestrator(recovery).run(
            config=files.config,
            secrets=files.secrets,
            authorization=FRESH_CHAIN_ONE_PLUS_FOUR_AUTHORIZATION,
        )

    assert recovery.sessions[0].events == ["recover:mem0_extraction", "cleanup"]
    assert recovery.sessions[0].physical_dispatch_count == 0
    terminal_replay = _KnownFailureFactory(known_failure=failure)
    with pytest.raises(FreshChainCanaryError, match="fresh_chain_prior_terminal_failed"):
        FreshChainCanaryOrchestrator(terminal_replay).run(
            config=files.config,
            secrets=files.secrets,
            authorization=FRESH_CHAIN_ONE_PLUS_FOUR_AUTHORIZATION,
        )
    assert terminal_replay.open_count == 0

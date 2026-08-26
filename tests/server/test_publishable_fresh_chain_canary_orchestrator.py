"""Provider-free contract tests for the exact fresh-chain five-call lifecycle."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pytest
from infinity_context_server.publishable_durable_scheduler.publishable_run_contracts import (
    PublishableRunConfig,
    PublishableRunSecrets,
)
from infinity_context_server.publishable_fresh_chain_canary.authority import (
    fresh_chain_static_authority_payload,
)
from infinity_context_server.publishable_fresh_chain_canary.authorization import (
    FRESH_CHAIN_ONE_PLUS_FOUR_AUTHORIZATION,
)
from infinity_context_server.publishable_fresh_chain_canary.contracts import (
    FRESH_CHAIN_STAGES,
    FreshChainCallIntent,
    FreshChainCallResult,
    FreshChainCanaryError,
    FreshChainCleanupResult,
    FreshChainLookup,
    FreshChainLookupDisposition,
    FreshChainRetrievalHandoff,
    FreshChainUsage,
    canonical_sha256,
)
from infinity_context_server.publishable_fresh_chain_canary.layout import (
    open_fresh_chain_layout,
)
from infinity_context_server.publishable_fresh_chain_canary.ledger import (
    FreshChainCanaryLedger,
)
from infinity_context_server.publishable_fresh_chain_canary.ledger_models import (
    FreshChainLedgerError,
)
from infinity_context_server.publishable_fresh_chain_canary.orchestrator import (
    FreshChainCanaryOrchestrator,
)

_SOURCE_PROJECTION_SHA = hashlib.sha256(b"provider source projection").hexdigest()


@dataclass(frozen=True, slots=True)
class _Files:
    config: PublishableRunConfig
    secrets: PublishableRunSecrets


def _common_policy_sha256() -> str:
    evaluation = fresh_chain_static_authority_payload()["evaluation"]
    assert type(evaluation) is dict
    common = evaluation["common_condition"]
    assert type(common) is dict
    return canonical_sha256(common)


def _private_run_files(tmp_path: Path) -> _Files:
    root = tmp_path / "private"
    state = root / "state"
    root.mkdir(mode=0o700)
    state.mkdir(mode=0o700)
    config = PublishableRunConfig(
        dependency_provider="tests.provider-free",
        official_case_authority_path=state / "official.sqlite3",
        scheduler_database_paths=(state / "locomo.sqlite3", state / "longmem.sqlite3"),
        suite_seal_database_path=state / "suite.sqlite3",
        publication_receipt_path=state / "publication.json",
        publication_key_id="operator-local-key",
        max_dispatches_per_batch=5,
        adapter_config_json=json.dumps({"provider": "fake"}).encode(),
    )
    secrets = PublishableRunSecrets(
        official_case_authentication_key=bytes([1]) * 32,
        scheduler_authentication_keys=(bytes([2]) * 32, bytes([3]) * 32),
        suite_seal_authentication_key=bytes([4]) * 32,
        publication_receipt_authentication_key=bytes([5]) * 32,
        adapter_secrets_json=json.dumps({"secret": "fake"}).encode(),
    )
    return _Files(config, secrets)


class _Factory:
    def __init__(self, *, existing_results: dict[str, FreshChainCallResult] | None = None) -> None:
        self.open_count = 0
        self.sessions: list[_Session] = []
        self.existing_results = existing_results or {}

    def open_fresh_chain_session(self, **arguments: object) -> _Session:
        self.open_count += 1
        session = _Session(
            namespace_id=arguments["namespace_id"],
            namespace_commitment_sha256=arguments["namespace_commitment_sha256"],
            source_commitment_sha256=arguments["source_commitment_sha256"],
        )
        session.results.update(self.existing_results)
        self.sessions.append(session)
        return session


class _Session:
    def __init__(
        self,
        *,
        namespace_id: object,
        namespace_commitment_sha256: object,
        source_commitment_sha256: object,
    ) -> None:
        assert type(namespace_id) is str
        assert type(namespace_commitment_sha256) is str
        assert type(source_commitment_sha256) is str
        self.namespace_id = namespace_id
        self.namespace_commitment_sha256 = namespace_commitment_sha256
        self.source_commitment_sha256 = source_commitment_sha256
        self.source_projection_commitment_sha256 = _SOURCE_PROJECTION_SHA
        self.common_condition_policy_sha256 = _common_policy_sha256()
        self.events: list[str] = []
        self.results: dict[str, FreshChainCallResult] = {}
        self.handoff: FreshChainRetrievalHandoff | None = None
        self.cleanup_count = 0
        self.closed = False

    def prepare_call(
        self,
        *,
        stage: str,
        prior_results: tuple[FreshChainCallResult, ...],
        retrieval_handoff: FreshChainRetrievalHandoff | None,
    ) -> FreshChainCallIntent:
        ordinal = FRESH_CHAIN_STAGES.index(stage)
        assert len(prior_results) == ordinal
        if stage == "mem0_extraction":
            input_authority = self.source_projection_commitment_sha256
        elif stage == "infinity_judge":
            input_authority = prior_results[1].result_sha256
        elif stage == "mem0_answer":
            assert retrieval_handoff is self.handoff
            input_authority = retrieval_handoff.retrieval_authority_sha256
        elif stage == "mem0_judge":
            input_authority = prior_results[3].result_sha256
        else:
            input_authority = self.source_commitment_sha256
        return FreshChainCallIntent(
            stage=stage,
            ordinal=ordinal,
            namespace_id=self.namespace_id,
            namespace_commitment_sha256=self.namespace_commitment_sha256,
            source_commitment_sha256=self.source_commitment_sha256,
            source_projection_commitment_sha256=(self.source_projection_commitment_sha256),
            input_authority_sha256=input_authority,
            canonical_request_body=(f'{{"stage":"{stage}"}}').encode(),
            retrieval_handoff_sha256=(
                retrieval_handoff.handoff_sha256 if stage == "mem0_answer" else None
            ),
        )

    def lookup(self, intent: FreshChainCallIntent) -> FreshChainLookup:
        self.events.append(f"lookup:{intent.stage}")
        result = self.results.get(intent.stage)
        if result is not None:
            return FreshChainLookup(
                FreshChainLookupDisposition.TERMINAL,
                intent.intent_sha256,
                result=_recovered(result),
            )
        return FreshChainLookup(
            FreshChainLookupDisposition.AUTHENTICATED_ABSENT,
            intent.intent_sha256,
            authenticated_absence_sha256=_sha(f"absence:{intent.stage}"),
        )

    def dispatch(self, intent: FreshChainCallIntent) -> FreshChainCallResult:
        self.events.append(f"dispatch:{intent.stage}")
        if intent.stage == "mem0_extraction":
            commitments = {
                key: _sha(f"{intent.stage}:{key}")
                for key in (
                    "admission_commitment_sha256",
                    "operation_id_sha256",
                    "output_text_sha256",
                    "run_identity_commitment_sha256",
                    "runtime_binding_commitment_sha256",
                    "scope_sha256",
                    "source_projection_commitment_sha256",
                    "unit_identity_sha256",
                    "unit_sha256",
                )
            }
        else:
            commitments = {
                key: _sha(f"{intent.stage}:{key}")
                for key in (
                    "bridge_intent_sha256",
                    "encrypted_output_sha256",
                    "output_text_sha256",
                    "response_body_sha256",
                )
            }
        commitments["request_body_sha256"] = intent.request_sha256
        if intent.stage == "mem0_extraction":
            commitments["source_projection_commitment_sha256"] = (
                intent.source_projection_commitment_sha256
            )
        result = FreshChainCallResult(
            stage=intent.stage,
            ordinal=intent.ordinal,
            intent_sha256=intent.intent_sha256,
            result_sha256=_sha(f"result:{intent.stage}"),
            physical_receipt_sha256=_sha(f"receipt:{intent.stage}"),
            receipt_id=f"receipt:{intent.ordinal}",
            usage=FreshChainUsage(intent.ordinal + 1, 1, intent.ordinal + 2),
            transport_dispatched=True,
            output_text=f"private-output:{intent.stage}",
            commitments=commitments,
        )
        self.results[intent.stage] = result
        return result

    def recover(self, intent: FreshChainCallIntent) -> FreshChainLookup:
        self.events.append(f"recover:{intent.stage}")
        result = self.results.get(intent.stage)
        if result is None:
            return FreshChainLookup(
                FreshChainLookupDisposition.AMBIGUOUS,
                intent.intent_sha256,
                ambiguity_sha256=_sha(f"ambiguous:{intent.stage}"),
            )
        return FreshChainLookup(
            FreshChainLookupDisposition.TERMINAL,
            intent.intent_sha256,
            result=_recovered(result),
        )

    def capture_retrieval(
        self,
        extraction: FreshChainCallResult,
    ) -> FreshChainRetrievalHandoff:
        self.events.append("capture_retrieval")
        self.handoff = FreshChainRetrievalHandoff(
            extraction_intent_sha256=extraction.intent_sha256,
            extraction_result_sha256=extraction.result_sha256,
            extraction_receipt_sha256=extraction.physical_receipt_sha256,
            namespace_commitment_sha256=self.namespace_commitment_sha256,
            source_commitment_sha256=self.source_commitment_sha256,
            source_projection_commitment_sha256=(self.source_projection_commitment_sha256),
            memory_authority_sha256=_sha("fresh-memory-authority"),
            retrieval_authority_sha256=_sha("fresh-retrieval-authority"),
            retrieval_material_sha256=_sha("fresh-retrieval-material"),
            memory_count=3,
        )
        return self.handoff

    def cleanup(self, failure: object | None = None) -> FreshChainCleanupResult:
        assert failure is None
        self.events.append("cleanup")
        self.cleanup_count += 1
        return FreshChainCleanupResult(
            namespace_commitment_sha256=self.namespace_commitment_sha256,
            cleanup_authority_sha256=_sha("cleanup-authority"),
            receipt_id="cleanup:0",
            receipt_sha256=_sha("cleanup-receipt"),
            outcome_sha256=_sha("cleanup-outcome"),
            deleted=True,
            operation_count=1,
            residual_count=0,
        )

    def abort_after_extraction(self) -> FreshChainCleanupResult:
        self.events.append("abort_after_extraction")
        self.cleanup_count += 1
        return FreshChainCleanupResult(
            namespace_commitment_sha256=self.namespace_commitment_sha256,
            cleanup_authority_sha256=_sha("abort-cleanup-authority"),
            receipt_id="abort-cleanup:0",
            receipt_sha256=_sha("abort-cleanup-receipt"),
            outcome_sha256=_sha("abort-cleanup-outcome"),
            deleted=True,
            operation_count=1,
            residual_count=0,
        )

    def close(self) -> None:
        self.closed = True


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _recovered(result: FreshChainCallResult) -> FreshChainCallResult:
    return FreshChainCallResult(
        stage=result.stage,
        ordinal=result.ordinal,
        intent_sha256=result.intent_sha256,
        result_sha256=result.result_sha256,
        physical_receipt_sha256=result.physical_receipt_sha256,
        receipt_id=result.receipt_id,
        usage=result.usage,
        transport_dispatched=False,
        output_text=result.output_text,
        commitments=result.commitments,
    )


def _prepared(tmp_path: Path):
    files = _private_run_files(tmp_path)
    files.config.official_case_authority_path.touch(mode=0o600)
    return files


def _bind_projection(ledger: FreshChainCanaryLedger) -> None:
    if ledger.read_snapshot().source_projection_commitment_sha256 is None:
        ledger.record_source_projection_bound(
            source_projection_commitment_sha256=_SOURCE_PROJECTION_SHA
        )


def test_exact_fresh_extraction_then_four_ordered_evaluations_and_cleanup(
    tmp_path: Path,
) -> None:
    files = _prepared(tmp_path)
    factory = _Factory()

    evidence = FreshChainCanaryOrchestrator(factory).run(
        config=files.config,
        secrets=files.secrets,
        authorization=FRESH_CHAIN_ONE_PLUS_FOUR_AUTHORIZATION,
    )

    session = factory.sessions[0]
    assert session.events == [
        "lookup:mem0_extraction",
        "dispatch:mem0_extraction",
        "capture_retrieval",
        "lookup:infinity_answer",
        "dispatch:infinity_answer",
        "lookup:infinity_judge",
        "dispatch:infinity_judge",
        "lookup:mem0_answer",
        "dispatch:mem0_answer",
        "lookup:mem0_judge",
        "dispatch:mem0_judge",
        "cleanup",
    ]
    assert tuple(session.results) == FRESH_CHAIN_STAGES
    assert session.cleanup_count == 1
    assert session.closed is True
    payload = evidence.payload()
    assert payload["case_id"] == "conv-26:qa:1"
    assert payload["measured_physical_attempt_count"] == 5
    assert payload["publishable"] is False
    assert payload["receipt"]["publishable"] is False


def test_mem0_answer_is_bound_to_extraction_derived_retrieval(tmp_path: Path) -> None:
    files = _prepared(tmp_path)
    factory = _Factory()

    FreshChainCanaryOrchestrator(factory).run(
        config=files.config,
        secrets=files.secrets,
        authorization=FRESH_CHAIN_ONE_PLUS_FOUR_AUTHORIZATION,
    )

    session = factory.sessions[0]
    handoff = session.handoff
    assert handoff is not None
    mem0_result = session.results["mem0_answer"]
    layout = open_fresh_chain_layout(files.config, files.secrets)
    # The durable stage input is the same retrieval authority captured from the
    # fresh extraction, not a prior micro-canary/report commitment.
    from infinity_context_server.publishable_fresh_chain_canary.authority import (
        FreshChainCanaryAuthority,
    )
    from infinity_context_server.publishable_fresh_chain_canary.orchestrator import _plan

    authority = FreshChainCanaryAuthority(
        layout.namespace_commitment_sha256,
        layout.source_commitment_sha256,
    )
    ledger = FreshChainCanaryLedger.open(
        layout.ledger_path,
        authentication_secret=layout.ledger_authentication_key,
        plan=_plan(layout, authority),
        require_existing=True,
    )
    snapshot = ledger.read_snapshot()
    assert snapshot.stages[3].input_authority_sha256 == handoff.retrieval_authority_sha256
    assert snapshot.stages[3].result_sha256 == mem0_result.result_sha256
    assert dict(snapshot.stages[3].intent_commitments)["retrieval_handoff_sha256"] == (
        handoff.handoff_sha256
    )


def test_authenticated_terminal_replay_opens_no_session_and_makes_zero_calls(
    tmp_path: Path,
) -> None:
    files = _prepared(tmp_path)
    first = _Factory()
    expected = FreshChainCanaryOrchestrator(first).run(
        config=files.config,
        secrets=files.secrets,
        authorization=FRESH_CHAIN_ONE_PLUS_FOUR_AUTHORIZATION,
    )
    replay = _Factory()

    observed = FreshChainCanaryOrchestrator(replay).run(
        config=files.config,
        secrets=files.secrets,
        authorization=FRESH_CHAIN_ONE_PLUS_FOUR_AUTHORIZATION,
    )

    assert observed == expected
    assert replay.open_count == 0
    assert replay.sessions == []


def test_exact_authorization_is_required_before_state_or_provider_open(
    tmp_path: Path,
) -> None:
    files = _private_run_files(tmp_path)
    factory = _Factory()

    with pytest.raises(
        FreshChainCanaryError,
        match="fresh_chain_live_1_plus_4_authorization_required",
    ):
        FreshChainCanaryOrchestrator(factory).run(
            config=files.config,
            secrets=files.secrets,
        )

    assert factory.open_count == 0
    assert not (files.config.publication_receipt_path.parent / "fresh-chain-canary-v1").exists()


def test_authenticated_cleanup_restart_completes_without_provider_open(
    tmp_path: Path,
) -> None:
    files = _prepared(tmp_path)
    layout = open_fresh_chain_layout(files.config, files.secrets)
    from infinity_context_server.publishable_fresh_chain_canary.authority import (
        FreshChainCanaryAuthority,
    )
    from infinity_context_server.publishable_fresh_chain_canary.orchestrator import _plan

    authority = FreshChainCanaryAuthority(
        layout.namespace_commitment_sha256,
        layout.source_commitment_sha256,
    )
    ledger = FreshChainCanaryLedger.open(
        layout.ledger_path,
        authentication_secret=layout.ledger_authentication_key,
        plan=_plan(layout, authority),
    )
    _bind_projection(ledger)
    initial_factory = _Factory()
    session = initial_factory.open_fresh_chain_session(
        namespace_id=layout.namespace_id,
        namespace_commitment_sha256=layout.namespace_commitment_sha256,
        source_commitment_sha256=layout.source_commitment_sha256,
    )
    orchestrator = FreshChainCanaryOrchestrator(initial_factory)
    snapshot = orchestrator._execute_calls(
        session=session,
        ledger=ledger,
        initial=ledger.read_snapshot(),
        layout=layout,
    )
    cleanup = session.cleanup()
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
    session.close()
    assert snapshot.cleanup is not None
    assert snapshot.terminal_outcome is None

    replay_factory = _Factory()
    evidence = FreshChainCanaryOrchestrator(replay_factory).run(
        config=files.config,
        secrets=files.secrets,
        authorization=FRESH_CHAIN_ONE_PLUS_FOUR_AUTHORIZATION,
    )

    assert replay_factory.open_count == 0
    assert replay_factory.sessions == []
    assert evidence.payload()["measured_physical_attempt_count"] == 5
    assert ledger.read_snapshot().succeeded is True


def test_common_condition_policy_mismatch_fails_before_any_physical_call(
    tmp_path: Path,
) -> None:
    files = _prepared(tmp_path)

    class _WrongPolicyFactory(_Factory):
        def open_fresh_chain_session(self, **arguments: object) -> _Session:
            session = super().open_fresh_chain_session(**arguments)
            session.common_condition_policy_sha256 = _sha("wrong common condition")
            return session

    factory = _WrongPolicyFactory()
    with pytest.raises(FreshChainCanaryError, match="fresh_chain_runtime_session_invalid"):
        FreshChainCanaryOrchestrator(factory).run(
            config=files.config,
            secrets=files.secrets,
            authorization=FRESH_CHAIN_ONE_PLUS_FOUR_AUTHORIZATION,
        )

    assert factory.open_count == 1
    assert factory.sessions[0].events == []
    assert factory.sessions[0].closed is True


def test_pending_intent_recovers_and_never_blindly_redispatches(tmp_path: Path) -> None:
    files = _prepared(tmp_path)
    factory = _Factory()
    layout = open_fresh_chain_layout(files.config, files.secrets)
    from infinity_context_server.publishable_fresh_chain_canary.authority import (
        FreshChainCanaryAuthority,
    )
    from infinity_context_server.publishable_fresh_chain_canary.orchestrator import _plan

    authority = FreshChainCanaryAuthority(
        layout.namespace_commitment_sha256,
        layout.source_commitment_sha256,
    )
    ledger = FreshChainCanaryLedger.open(
        layout.ledger_path,
        authentication_secret=layout.ledger_authentication_key,
        plan=_plan(layout, authority),
    )
    _bind_projection(ledger)
    session = factory.open_fresh_chain_session(
        namespace_id=layout.namespace_id,
        namespace_commitment_sha256=layout.namespace_commitment_sha256,
        source_commitment_sha256=layout.source_commitment_sha256,
    )
    intent = session.prepare_call(
        stage="mem0_extraction",
        prior_results=(),
        retrieval_handoff=None,
    )
    ledger.record_intent(
        intent.stage,
        intent_sha256=intent.intent_sha256,
        request_sha256=intent.request_sha256,
        input_authority_sha256=intent.input_authority_sha256,
        commitments={
            "namespace_commitment_sha256": intent.namespace_commitment_sha256,
            "source_commitment_sha256": intent.source_commitment_sha256,
            "source_projection_commitment_sha256": (intent.source_projection_commitment_sha256),
        },
    )
    absence = session.lookup(intent)
    assert absence.authenticated_absence_sha256 is not None
    ledger.record_authenticated_pre_call_absence(
        intent.stage,
        intent_sha256=intent.intent_sha256,
        absence_sha256=absence.authenticated_absence_sha256,
    )
    ledger.record_dispatch_started(
        intent.stage,
        intent_sha256=intent.intent_sha256,
        authenticated_absence_sha256=absence.authenticated_absence_sha256,
    )
    result = session.dispatch(intent)
    session.close()
    recovery = _Factory(existing_results={"mem0_extraction": result})
    FreshChainCanaryOrchestrator(recovery).run(
        config=files.config,
        secrets=files.secrets,
        authorization=FRESH_CHAIN_ONE_PLUS_FOUR_AUTHORIZATION,
    )

    events = recovery.sessions[0].events
    assert "recover:mem0_extraction" in events
    assert "dispatch:mem0_extraction" not in events
    assert sum(item.startswith("dispatch:") for item in events) == 4


@pytest.mark.parametrize("persisted_absence", (False, True))
def test_pre_dispatch_restart_safely_dispatches_after_authenticated_absence(
    tmp_path: Path,
    persisted_absence: bool,
) -> None:
    files = _prepared(tmp_path)
    layout = open_fresh_chain_layout(files.config, files.secrets)
    from infinity_context_server.publishable_fresh_chain_canary.authority import (
        FreshChainCanaryAuthority,
    )
    from infinity_context_server.publishable_fresh_chain_canary.orchestrator import _plan

    authority = FreshChainCanaryAuthority(
        layout.namespace_commitment_sha256,
        layout.source_commitment_sha256,
    )
    ledger = FreshChainCanaryLedger.open(
        layout.ledger_path,
        authentication_secret=layout.ledger_authentication_key,
        plan=_plan(layout, authority),
    )
    _bind_projection(ledger)
    preparation_factory = _Factory()
    session = preparation_factory.open_fresh_chain_session(
        namespace_id=layout.namespace_id,
        namespace_commitment_sha256=layout.namespace_commitment_sha256,
        source_commitment_sha256=layout.source_commitment_sha256,
    )
    intent = session.prepare_call(
        stage="mem0_extraction",
        prior_results=(),
        retrieval_handoff=None,
    )
    ledger.record_intent(
        intent.stage,
        intent_sha256=intent.intent_sha256,
        request_sha256=intent.request_sha256,
        input_authority_sha256=intent.input_authority_sha256,
        commitments={
            "namespace_commitment_sha256": intent.namespace_commitment_sha256,
            "source_commitment_sha256": intent.source_commitment_sha256,
            "source_projection_commitment_sha256": (intent.source_projection_commitment_sha256),
        },
    )
    if persisted_absence:
        lookup = session.lookup(intent)
        assert lookup.authenticated_absence_sha256 is not None
        ledger.record_authenticated_pre_call_absence(
            intent.stage,
            intent_sha256=intent.intent_sha256,
            absence_sha256=lookup.authenticated_absence_sha256,
        )
    session.close()

    recovery = _Factory()
    evidence = FreshChainCanaryOrchestrator(recovery).run(
        config=files.config,
        secrets=files.secrets,
        authorization=FRESH_CHAIN_ONE_PLUS_FOUR_AUTHORIZATION,
    )

    events = recovery.sessions[0].events
    assert events[:2] == ["lookup:mem0_extraction", "dispatch:mem0_extraction"]
    assert not any(event.startswith("recover:") for event in events)
    assert sum(event.startswith("dispatch:") for event in events) == 5
    assert evidence.payload()["measured_physical_attempt_count"] == 5
    snapshot = ledger.read_snapshot()
    assert all(record.dispatch_started_sha256 is not None for record in snapshot.stages)


def test_post_dispatch_start_restart_recovers_only_and_never_dispatches(
    tmp_path: Path,
) -> None:
    files = _prepared(tmp_path)
    layout = open_fresh_chain_layout(files.config, files.secrets)
    from infinity_context_server.publishable_fresh_chain_canary.authority import (
        FreshChainCanaryAuthority,
    )
    from infinity_context_server.publishable_fresh_chain_canary.orchestrator import _plan

    authority = FreshChainCanaryAuthority(
        layout.namespace_commitment_sha256,
        layout.source_commitment_sha256,
    )
    ledger = FreshChainCanaryLedger.open(
        layout.ledger_path,
        authentication_secret=layout.ledger_authentication_key,
        plan=_plan(layout, authority),
    )
    _bind_projection(ledger)
    preparation_factory = _Factory()
    session = preparation_factory.open_fresh_chain_session(
        namespace_id=layout.namespace_id,
        namespace_commitment_sha256=layout.namespace_commitment_sha256,
        source_commitment_sha256=layout.source_commitment_sha256,
    )
    intent = session.prepare_call(
        stage="mem0_extraction",
        prior_results=(),
        retrieval_handoff=None,
    )
    ledger.record_intent(
        intent.stage,
        intent_sha256=intent.intent_sha256,
        request_sha256=intent.request_sha256,
        input_authority_sha256=intent.input_authority_sha256,
        commitments={
            "namespace_commitment_sha256": intent.namespace_commitment_sha256,
            "source_commitment_sha256": intent.source_commitment_sha256,
            "source_projection_commitment_sha256": (intent.source_projection_commitment_sha256),
        },
    )
    lookup = session.lookup(intent)
    assert lookup.authenticated_absence_sha256 is not None
    ledger.record_authenticated_pre_call_absence(
        intent.stage,
        intent_sha256=intent.intent_sha256,
        absence_sha256=lookup.authenticated_absence_sha256,
    )
    ledger.record_dispatch_started(
        intent.stage,
        intent_sha256=intent.intent_sha256,
        authenticated_absence_sha256=lookup.authenticated_absence_sha256,
    )
    session.close()

    recovery = _Factory()
    with pytest.raises(
        FreshChainCanaryError,
        match="fresh_chain_recovery_still_ambiguous",
    ):
        FreshChainCanaryOrchestrator(recovery).run(
            config=files.config,
            secrets=files.secrets,
            authorization=FRESH_CHAIN_ONE_PLUS_FOUR_AUTHORIZATION,
        )

    assert recovery.sessions[0].events == ["recover:mem0_extraction"]
    snapshot = ledger.read_snapshot()
    assert snapshot.pending_intent is not None
    assert snapshot.pending_intent.dispatch_started_sha256 is not None
    assert snapshot.pending_intent.ambiguity_sha256 is not None


def test_post_dispatch_marker_with_authenticated_pre_claim_absence_dispatches_once(
    tmp_path: Path,
) -> None:
    """A crash before the genuine seam claim is safely dispatchable once."""

    files = _prepared(tmp_path)
    layout = open_fresh_chain_layout(files.config, files.secrets)
    from infinity_context_server.publishable_fresh_chain_canary.authority import (
        FreshChainCanaryAuthority,
    )
    from infinity_context_server.publishable_fresh_chain_canary.orchestrator import _plan

    ledger = FreshChainCanaryLedger.open(
        layout.ledger_path,
        authentication_secret=layout.ledger_authentication_key,
        plan=_plan(
            layout,
            FreshChainCanaryAuthority(
                layout.namespace_commitment_sha256,
                layout.source_commitment_sha256,
            ),
        ),
    )
    _bind_projection(ledger)
    preparation = _Factory()
    session = preparation.open_fresh_chain_session(
        namespace_id=layout.namespace_id,
        namespace_commitment_sha256=layout.namespace_commitment_sha256,
        source_commitment_sha256=layout.source_commitment_sha256,
    )
    intent = session.prepare_call(
        stage="mem0_extraction",
        prior_results=(),
        retrieval_handoff=None,
    )
    ledger.record_intent(
        intent.stage,
        intent_sha256=intent.intent_sha256,
        request_sha256=intent.request_sha256,
        input_authority_sha256=intent.input_authority_sha256,
        commitments={
            "namespace_commitment_sha256": intent.namespace_commitment_sha256,
            "source_commitment_sha256": intent.source_commitment_sha256,
            "source_projection_commitment_sha256": (intent.source_projection_commitment_sha256),
        },
    )
    lookup = session.lookup(intent)
    assert lookup.authenticated_absence_sha256 is not None
    ledger.record_authenticated_pre_call_absence(
        intent.stage,
        intent_sha256=intent.intent_sha256,
        absence_sha256=lookup.authenticated_absence_sha256,
    )
    ledger.record_dispatch_started(
        intent.stage,
        intent_sha256=intent.intent_sha256,
        authenticated_absence_sha256=lookup.authenticated_absence_sha256,
    )
    session.close()

    class _PreClaimRecoverySession(_Session):
        def recover(self, intent: FreshChainCallIntent) -> FreshChainLookup:
            self.events.append(f"recover:{intent.stage}")
            return FreshChainLookup(
                FreshChainLookupDisposition.AUTHENTICATED_ABSENT,
                intent.intent_sha256,
                authenticated_absence_sha256=_sha(f"absence:{intent.stage}"),
            )

    class _PreClaimRecoveryFactory(_Factory):
        def open_fresh_chain_session(self, **arguments: object) -> _Session:
            self.open_count += 1
            opened = _PreClaimRecoverySession(
                namespace_id=arguments["namespace_id"],
                namespace_commitment_sha256=arguments["namespace_commitment_sha256"],
                source_commitment_sha256=arguments["source_commitment_sha256"],
            )
            self.sessions.append(opened)
            return opened

    recovery = _PreClaimRecoveryFactory()
    evidence = FreshChainCanaryOrchestrator(recovery).run(
        config=files.config,
        secrets=files.secrets,
        authorization=FRESH_CHAIN_ONE_PLUS_FOUR_AUTHORIZATION,
    )

    events = recovery.sessions[0].events
    assert events[:2] == ["recover:mem0_extraction", "dispatch:mem0_extraction"]
    assert sum(event.startswith("dispatch:") for event in events) == 5
    assert evidence.payload()["measured_physical_attempt_count"] == 5


def test_tampered_ledger_fails_before_provider_open(tmp_path: Path) -> None:
    files = _prepared(tmp_path)
    first = _Factory()
    FreshChainCanaryOrchestrator(first).run(
        config=files.config,
        secrets=files.secrets,
        authorization=FRESH_CHAIN_ONE_PLUS_FOUR_AUTHORIZATION,
    )
    layout = open_fresh_chain_layout(files.config, files.secrets)
    with sqlite3.connect(layout.ledger_path) as connection:
        connection.execute(
            "UPDATE fresh_chain_events SET payload_json = ? WHERE sequence = 1",
            ('{"tampered":true}',),
        )
        connection.commit()
    replay = _Factory()

    with pytest.raises(FreshChainLedgerError, match="fresh_chain_ledger_corrupt"):
        FreshChainCanaryOrchestrator(replay).run(
            config=files.config,
            secrets=files.secrets,
            authorization=FRESH_CHAIN_ONE_PLUS_FOUR_AUTHORIZATION,
        )

    assert replay.open_count == 0


def test_unknown_pre_dispatch_state_fails_without_dispatch(tmp_path: Path) -> None:
    files = _prepared(tmp_path)

    class _UnknownSession(_Session):
        def lookup(self, intent: FreshChainCallIntent) -> FreshChainLookup:
            self.events.append(f"lookup:{intent.stage}")
            return FreshChainLookup(
                FreshChainLookupDisposition.AMBIGUOUS,
                intent.intent_sha256,
                ambiguity_sha256=_sha("unknown"),
            )

    class _UnknownFactory(_Factory):
        def open_fresh_chain_session(self, **arguments: object) -> _Session:
            self.open_count += 1
            session = _UnknownSession(
                namespace_id=arguments["namespace_id"],
                namespace_commitment_sha256=arguments["namespace_commitment_sha256"],
                source_commitment_sha256=arguments["source_commitment_sha256"],
            )
            self.sessions.append(session)
            return session

    factory = _UnknownFactory()
    with pytest.raises(FreshChainCanaryError, match="fresh_chain_pre_dispatch_state_not_absent"):
        FreshChainCanaryOrchestrator(factory).run(
            config=files.config,
            secrets=files.secrets,
            authorization=FRESH_CHAIN_ONE_PLUS_FOUR_AUTHORIZATION,
        )

    assert not any(event.startswith("dispatch:") for event in factory.sessions[0].events)
    assert factory.sessions[0].closed is True


def test_malformed_failed_pre_dispatch_state_fails_without_dispatch(
    tmp_path: Path,
) -> None:
    files = _prepared(tmp_path)

    class _FailedSession(_Session):
        def lookup(self, intent: FreshChainCallIntent) -> FreshChainLookup:
            self.events.append(f"lookup:{intent.stage}")
            return FreshChainLookup(
                FreshChainLookupDisposition.FAILED,
                intent.intent_sha256,
            )

    class _FailedFactory(_Factory):
        def open_fresh_chain_session(self, **arguments: object) -> _Session:
            self.open_count += 1
            session = _FailedSession(
                namespace_id=arguments["namespace_id"],
                namespace_commitment_sha256=arguments["namespace_commitment_sha256"],
                source_commitment_sha256=arguments["source_commitment_sha256"],
            )
            self.sessions.append(session)
            return session

    factory = _FailedFactory()
    with pytest.raises(FreshChainCanaryError, match="fresh_chain_lookup_invalid"):
        FreshChainCanaryOrchestrator(factory).run(
            config=files.config,
            secrets=files.secrets,
            authorization=FRESH_CHAIN_ONE_PLUS_FOUR_AUTHORIZATION,
        )

    assert factory.sessions[0].events == ["lookup:mem0_extraction"]
    assert factory.sessions[0].closed is True


def test_malformed_dispatched_result_stops_with_recovery_marker(tmp_path: Path) -> None:
    files = _prepared(tmp_path)

    class _MalformedSession(_Session):
        def dispatch(self, intent: FreshChainCallIntent) -> FreshChainCallResult:
            self.events.append(f"dispatch:{intent.stage}")
            return object()  # type: ignore[return-value]

    class _MalformedFactory(_Factory):
        def open_fresh_chain_session(self, **arguments: object) -> _Session:
            self.open_count += 1
            session = _MalformedSession(
                namespace_id=arguments["namespace_id"],
                namespace_commitment_sha256=arguments["namespace_commitment_sha256"],
                source_commitment_sha256=arguments["source_commitment_sha256"],
            )
            self.sessions.append(session)
            return session

    factory = _MalformedFactory()
    with pytest.raises(FreshChainCanaryError, match="fresh_chain_result_binding_invalid"):
        FreshChainCanaryOrchestrator(factory).run(
            config=files.config,
            secrets=files.secrets,
            authorization=FRESH_CHAIN_ONE_PLUS_FOUR_AUTHORIZATION,
        )

    layout = open_fresh_chain_layout(files.config, files.secrets)
    with sqlite3.connect(layout.ledger_path) as connection:
        kinds = [row[0] for row in connection.execute("SELECT event_kind FROM fresh_chain_events")]
    assert kinds == [
        "source_projection_bound",
        "intent",
        "authenticated_pre_call_absence",
        "dispatch_started",
    ]
    assert factory.sessions[0].closed is True

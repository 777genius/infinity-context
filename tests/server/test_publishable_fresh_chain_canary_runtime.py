from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from infinity_context_runtime_bridge import (
    BridgeJournal,
    HmacJournalIntegrity,
    SubscriptionRuntimeBridgeAdapter,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    Mem0OssReceiptDisposition,
    RuntimeReceiptVerificationContext,
    RuntimeReceiptVerificationResult,
)
from infinity_context_server.processes.publishable_full_extraction_contracts import (
    PublishableExtractionCommand,
)
from infinity_context_server.publishable_fresh_chain_canary.contracts import (
    FRESH_CHAIN_STAGES,
    FreshChainCallFailure,
    FreshChainCallResult,
    FreshChainCanaryError,
    FreshChainCleanupResult,
    FreshChainLookupDisposition,
    FreshChainRetrievalHandoff,
    canonical_sha256,
)
from infinity_context_server.publishable_fresh_chain_canary.runtime import (
    FreshChainCanaryRuntimeSession,
)
from subscription_runtime_bridge_test_support import (
    JOURNAL_KEY,
    AttestedFakeTransport,
    FakeSecrets,
    TestAuthenticatedCipher,
    make_pool,
    make_request,
)

_NAMESPACE_ID = "fresh-chain-runtime-test"
_NAMESPACE_SHA = hashlib.sha256(b"fresh namespace").hexdigest()
_SOURCE_SHA = hashlib.sha256(b"official source").hexdigest()
_SOURCE_PROJECTION_SHA = hashlib.sha256(b"official source projection").hexdigest()
_POLICY_SHA = hashlib.sha256(b"common condition").hexdigest()


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


@dataclass(frozen=True)
class _Absent:
    proof_sha256: str = field(default_factory=lambda: _sha("authenticated absence"))


@dataclass(frozen=True)
class _ExtractionPayload:
    marker: str = "authenticated extraction receipt"


@dataclass
class _ExtractionBoundary:
    events: list[str]
    payload: object = field(default_factory=_Absent)
    dispatch_calls: int = 0
    lookup_calls: int = 0
    recovery_calls: int = 0
    lose_dispatch_response: bool = False

    def lookup_outcome(self, *, command: PublishableExtractionCommand) -> object:
        assert command.ordinal == 0
        self.lookup_calls += 1
        return self.payload

    def dispatch_once(self, *, command: PublishableExtractionCommand) -> object:
        assert command.ordinal == 0
        self.dispatch_calls += 1
        self.events.append("mem0_extraction")
        self.payload = _ExtractionPayload()
        if self.lose_dispatch_response:
            raise RuntimeError("simulated extraction response loss")
        return self.payload

    def recover_once(self, *, command: PublishableExtractionCommand) -> object:
        assert command.ordinal == 0
        self.recovery_calls += 1
        return self.payload


class _ExtractionAbsence:
    def authenticate_pre_dispatch_absence(
        self,
        *,
        payload: object,
        command: PublishableExtractionCommand,
        namespace_id: str,
        namespace_commitment_sha256: str,
    ) -> str | None:
        assert command.ordinal == 0
        assert namespace_id == _NAMESPACE_ID
        assert namespace_commitment_sha256 == _NAMESPACE_SHA
        return payload.proof_sha256 if type(payload) is _Absent else None


@dataclass
class _ExtractionVerifier:
    unknown: bool = False
    disposition: Mem0OssReceiptDisposition = Mem0OssReceiptDisposition.COMPLETED

    def mark_outcome_unknown(
        self,
        *,
        context: RuntimeReceiptVerificationContext,
    ) -> None:
        assert context.readback_only is False
        self.unknown = True

    def verify_dispatch_receipt(
        self,
        *,
        payload: object,
        context: RuntimeReceiptVerificationContext,
    ) -> RuntimeReceiptVerificationResult:
        assert context.readback_only is False
        return self._verify(payload, context)

    def verify_status_readback(
        self,
        *,
        payload: object,
        context: RuntimeReceiptVerificationContext,
    ) -> RuntimeReceiptVerificationResult:
        assert context.readback_only is True
        assert self.unknown is True
        return self._verify(payload, context)

    def _verify(
        self,
        payload: object,
        context: RuntimeReceiptVerificationContext,
    ) -> RuntimeReceiptVerificationResult:
        if type(payload) is not _ExtractionPayload:
            raise ValueError("malformed extraction payload")
        return RuntimeReceiptVerificationResult(
            admission_commitment_sha256=context.admission_commitment_sha256,
            operation_id_sha256=context.operation_id_sha256,
            unit_identity_sha256=context.unit_identity_sha256,
            unit_sha256=context.unit_sha256,
            route_sha256=context.route_sha256,
            scope_sha256=context.scope_sha256,
            provider_receipt_sha256=_sha("extraction physical receipt"),
            sequence=0,
            request_body_sha256=_EXTRACTION_BODY_SHA,
            output_text_sha256=_sha("extracted memory output"),
            runtime_binding_commitment_sha256=_sha("mem0 runtime binding"),
            disposition=self.disposition,
            extraction_calls=1,
            retry_count=0,
            request_tokens=7,
            response_tokens=3,
        )


@dataclass
class _Renderer:
    extraction_body: bytes
    rendered: list[tuple[str, bytes]] = field(default_factory=list)
    common_condition_policy_sha256: str = _POLICY_SHA

    def render(
        self,
        *,
        stage: str,
        prior_results: tuple[FreshChainCallResult, ...],
        retrieval_handoff: FreshChainRetrievalHandoff | None,
    ) -> bytes:
        if stage == "mem0_extraction":
            body = self.extraction_body
        else:
            dependency = ""
            if stage.endswith("judge"):
                dependency = prior_results[-1].output_text
            handoff = ""
            if stage == "mem0_answer":
                assert retrieval_handoff is not None
                handoff = retrieval_handoff.handoff_sha256
            prompt = f"stage={stage};dependency={dependency};retrieval_handoff={handoff}"
            body = make_request(prompt=prompt, identity_nonce=_sha(prompt))
        self.rendered.append((stage, body))
        return body


@dataclass
class _Retrieval:
    calls: int = 0

    def capture(
        self,
        *,
        extraction: FreshChainCallResult,
        namespace_id: str,
        namespace_commitment_sha256: str,
        source_commitment_sha256: str,
        source_projection_commitment_sha256: str,
    ) -> FreshChainRetrievalHandoff:
        assert namespace_id == _NAMESPACE_ID
        self.calls += 1
        return FreshChainRetrievalHandoff(
            extraction_intent_sha256=extraction.intent_sha256,
            extraction_result_sha256=extraction.result_sha256,
            extraction_receipt_sha256=extraction.physical_receipt_sha256,
            namespace_commitment_sha256=namespace_commitment_sha256,
            source_commitment_sha256=source_commitment_sha256,
            source_projection_commitment_sha256=source_projection_commitment_sha256,
            memory_authority_sha256=_sha("fresh memory authority"),
            retrieval_authority_sha256=_sha("fresh retrieval authority"),
            retrieval_material_sha256=_sha("fresh retrieval material"),
            memory_count=2,
        )


@dataclass
class _Cleanup:
    calls: int = 0

    def cleanup(
        self,
        *,
        namespace_id: str,
        namespace_commitment_sha256: str,
        failure: object | None = None,
    ) -> FreshChainCleanupResult:
        assert namespace_id == _NAMESPACE_ID
        self.calls += 1
        return FreshChainCleanupResult(
            namespace_commitment_sha256=namespace_commitment_sha256,
            cleanup_authority_sha256=_sha("cleanup authority"),
            receipt_id="fresh-cleanup-receipt",
            receipt_sha256=_sha("cleanup receipt"),
            outcome_sha256=_sha("cleanup outcome"),
            deleted=True,
            operation_count=1,
            residual_count=0,
        )

    def abort_after_extraction(
        self,
        *,
        extraction: FreshChainCallResult,
        namespace_id: str,
        namespace_commitment_sha256: str,
    ) -> FreshChainCleanupResult:
        assert extraction.stage == "mem0_extraction"
        return self.cleanup(
            namespace_id=namespace_id,
            namespace_commitment_sha256=namespace_commitment_sha256,
        )


class _OrderedTransport:
    def __init__(self, delegate: AttestedFakeTransport, events: list[str]) -> None:
        self.delegate = delegate
        self.events = events

    @property
    def calls(self):
        return self.delegate.calls

    def post_once(self, **kwargs):
        request = kwargs["request_body"]
        stage = next(name for name in FRESH_CHAIN_STAGES[1:] if f"stage={name}".encode() in request)
        self.events.append(stage)
        return self.delegate.post_once(**kwargs)


_EXTRACTION_BODY = make_request(
    prompt="one fresh authenticated Mem0 extraction",
    identity_nonce=_sha("fresh extraction request"),
)
_EXTRACTION_BODY_SHA = hashlib.sha256(_EXTRACTION_BODY).hexdigest()


def _command() -> PublishableExtractionCommand:
    admission = _sha("admission")
    return PublishableExtractionCommand(
        run_id=_NAMESPACE_ID,
        run_identity_commitment_sha256=canonical_sha256(
            {
                "admission_commitment_sha256": admission,
                "namespace_commitment_sha256": _NAMESPACE_SHA,
                "namespace_id": _NAMESPACE_ID,
                "source_projection_commitment_sha256": _SOURCE_PROJECTION_SHA,
            }
        ),
        logical_operation_id=canonical_sha256(
            {
                "namespace_commitment_sha256": _NAMESPACE_SHA,
                "source_projection_commitment_sha256": _SOURCE_PROJECTION_SHA,
                "stage": "mem0_extraction",
            }
        ),
        ordinal=0,
        admission_commitment_sha256=admission,
        operation_id_sha256=_sha("operation"),
        unit_identity_sha256=_sha("unit identity"),
        unit_sha256=_sha("unit"),
        route_sha256=_sha("route"),
        scope_sha256=_sha("scope"),
        request_body_sha256=_EXTRACTION_BODY_SHA,
    )


def _session(
    tmp_path: Path,
    *,
    boundary: _ExtractionBoundary | None = None,
    events: list[str] | None = None,
    extraction_token_ceiling: int = 16_384,
    total_token_ceiling: int = 131_072,
    extraction_verifier: _ExtractionVerifier | None = None,
):
    events = [] if events is None else events
    boundary = boundary or _ExtractionBoundary(events)
    pool = make_pool()
    secrets = FakeSecrets(pool)
    delegate = AttestedFakeTransport(pool, secrets)
    transport = _OrderedTransport(delegate, events)
    journal = BridgeJournal.create(
        tmp_path / "private" / "bridge.sqlite3",
        integrity=HmacJournalIntegrity(JOURNAL_KEY),
    )
    bridge = SubscriptionRuntimeBridgeAdapter(
        pool=pool,
        secrets=secrets,
        transport=transport,
        journal=journal,
        output_cipher=TestAuthenticatedCipher(),
        maximum_request_bytes=256 * 1024,
        maximum_response_bytes=256 * 1024,
    )
    renderer = _Renderer(_EXTRACTION_BODY)
    retrieval = _Retrieval()
    cleanup = _Cleanup()
    session = FreshChainCanaryRuntimeSession(
        namespace_id=_NAMESPACE_ID,
        namespace_commitment_sha256=_NAMESPACE_SHA,
        source_commitment_sha256=_SOURCE_SHA,
        source_projection_commitment_sha256=_SOURCE_PROJECTION_SHA,
        extraction_boundary=boundary,
        extraction_command=_command(),
        extraction_receipt_verifier=extraction_verifier or _ExtractionVerifier(),
        extraction_absence=_ExtractionAbsence(),
        bridge=bridge,
        renderer=renderer,
        retrieval=retrieval,
        cleanup=cleanup,
        extraction_token_ceiling=extraction_token_ceiling,
        total_token_ceiling=total_token_ceiling,
    )
    return session, boundary, transport, journal, renderer, retrieval, cleanup


def _run(session: FreshChainCanaryRuntimeSession):
    results: list[FreshChainCallResult] = []
    handoff = None
    intents = []
    for stage in FRESH_CHAIN_STAGES:
        intent = session.prepare_call(
            stage=stage,
            prior_results=tuple(results),
            retrieval_handoff=handoff,
        )
        intents.append(intent)
        assert session.lookup(intent).disposition is (
            FreshChainLookupDisposition.AUTHENTICATED_ABSENT
        )
        result = session.dispatch(intent)
        results.append(result)
        if stage == "mem0_extraction":
            handoff = session.capture_retrieval(result)
    assert handoff is not None
    return tuple(intents), tuple(results), handoff


def test_exact_real_bridge_order_count_retrieval_binding_and_cleanup(tmp_path: Path) -> None:
    events: list[str] = []
    session, boundary, transport, journal, renderer, retrieval, cleanup = _session(
        tmp_path,
        events=events,
    )

    intents, results, handoff = _run(session)
    cleaned = session.cleanup()

    assert events == list(FRESH_CHAIN_STAGES)
    assert boundary.dispatch_calls == 1
    assert boundary.recovery_calls == 0
    assert len(transport.calls) == 4
    assert sum(result.transport_dispatched for result in results) == 5
    assert len({result.physical_receipt_sha256 for result in results}) == 5
    assert [intent.stage for intent in intents] == list(FRESH_CHAIN_STAGES)
    mem0_intent = intents[3]
    assert mem0_intent.retrieval_handoff_sha256 == handoff.handoff_sha256
    assert handoff.handoff_sha256.encode() in mem0_intent.canonical_request_body
    assert renderer.common_condition_policy_sha256 == _POLICY_SHA
    assert retrieval.calls == 1
    assert cleaned.deleted is True
    assert cleaned.operation_count == 1
    assert cleaned.residual_count == 0
    assert cleanup.calls == 1
    assert session.cleanup() == cleaned
    assert cleanup.calls == 1
    journal.close()


def test_extraction_ambiguity_uses_recover_once_without_second_dispatch(tmp_path: Path) -> None:
    events: list[str] = []
    boundary = _ExtractionBoundary(events, lose_dispatch_response=True)
    session, boundary, transport, journal, *_ = _session(
        tmp_path,
        boundary=boundary,
        events=events,
    )
    intent = session.prepare_call(
        stage="mem0_extraction",
        prior_results=(),
        retrieval_handoff=None,
    )

    with pytest.raises(FreshChainCanaryError, match="extraction_dispatch_ambiguous"):
        session.dispatch(intent)
    recovered = session.recover(intent)

    assert recovered.disposition is FreshChainLookupDisposition.TERMINAL
    assert recovered.result is not None
    assert recovered.result.transport_dispatched is False
    assert boundary.dispatch_calls == 1
    assert boundary.recovery_calls == 1
    assert transport.calls == []
    journal.close()


@pytest.mark.parametrize(
    "disposition",
    (
        Mem0OssReceiptDisposition.PROVIDER_FAILED,
        Mem0OssReceiptDisposition.REJECTED,
    ),
)
def test_authenticated_extraction_failure_is_terminal_and_cleanup_bound(
    tmp_path: Path,
    disposition: Mem0OssReceiptDisposition,
) -> None:
    session, boundary, transport, journal, *_rest, cleanup = _session(
        tmp_path,
        extraction_verifier=_ExtractionVerifier(disposition=disposition),
    )
    intent = session.prepare_call(
        stage="mem0_extraction",
        prior_results=(),
        retrieval_handoff=None,
    )

    failure = session.dispatch(intent)
    assert type(failure) is FreshChainCallFailure
    assert failure.provider_disposition.value == disposition.value
    assert failure.transport_dispatched is True
    lookup = session.lookup(intent)
    assert lookup.disposition is FreshChainLookupDisposition.FAILED
    assert lookup.failure == failure
    cleaned = session.cleanup(failure)

    assert cleaned.deleted is True
    assert boundary.dispatch_calls == 1
    assert transport.calls == []
    assert cleanup.calls == 1
    journal.close()


def test_out_of_order_missing_handoff_and_malformed_lookup_fail_closed(
    tmp_path: Path,
) -> None:
    session, boundary, _transport, journal, *_ = _session(tmp_path)

    with pytest.raises(FreshChainCanaryError, match="stage_out_of_order"):
        session.prepare_call(
            stage="infinity_answer",
            prior_results=(),
            retrieval_handoff=None,
        )
    intent = session.prepare_call(
        stage="mem0_extraction",
        prior_results=(),
        retrieval_handoff=None,
    )
    boundary.payload = object()
    with pytest.raises(FreshChainCanaryError, match="extraction_lookup_invalid"):
        session.lookup(intent)
    assert boundary.dispatch_calls == 0
    journal.close()


def test_caller_cannot_seed_runtime_with_unverified_prior_result(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    target_root = tmp_path / "target"
    source_root.mkdir(mode=0o700)
    target_root.mkdir(mode=0o700)
    source, _boundary, _transport, source_journal, *_ = _session(source_root)
    extraction_intent = source.prepare_call(
        stage="mem0_extraction",
        prior_results=(),
        retrieval_handoff=None,
    )
    extraction = source.dispatch(extraction_intent)
    handoff = source.capture_retrieval(extraction)

    target, target_boundary, target_transport, target_journal, *_ = _session(target_root)
    with pytest.raises(FreshChainCanaryError, match="prior_result_unverified"):
        target.prepare_call(
            stage="infinity_answer",
            prior_results=(extraction,),
            retrieval_handoff=handoff,
        )

    assert target_boundary.dispatch_calls == 0
    assert target_transport.calls == []
    source_journal.close()
    target_journal.close()


def test_caller_cannot_install_uncaptured_retrieval_handoff(tmp_path: Path) -> None:
    session, _boundary, transport, journal, _renderer, retrieval, _cleanup = _session(tmp_path)
    extraction_intent = session.prepare_call(
        stage="mem0_extraction",
        prior_results=(),
        retrieval_handoff=None,
    )
    extraction = session.dispatch(extraction_intent)
    forged = FreshChainRetrievalHandoff(
        extraction_intent_sha256=extraction.intent_sha256,
        extraction_result_sha256=extraction.result_sha256,
        extraction_receipt_sha256=extraction.physical_receipt_sha256,
        namespace_commitment_sha256=_NAMESPACE_SHA,
        source_commitment_sha256=_SOURCE_SHA,
        source_projection_commitment_sha256=_SOURCE_PROJECTION_SHA,
        memory_authority_sha256=_sha("forged memory authority"),
        retrieval_authority_sha256=_sha("forged retrieval authority"),
        retrieval_material_sha256=_sha("forged retrieval material"),
        memory_count=1,
    )

    with pytest.raises(FreshChainCanaryError, match="handoff_not_captured"):
        session.prepare_call(
            stage="infinity_answer",
            prior_results=(extraction,),
            retrieval_handoff=forged,
        )

    assert retrieval.calls == 0
    assert transport.calls == []
    journal.close()


def test_authenticated_lookup_then_capture_preserves_restart_sequence(tmp_path: Path) -> None:
    boundary = _ExtractionBoundary([], payload=_ExtractionPayload())
    session, boundary, transport, journal, *_ = _session(tmp_path, boundary=boundary)
    extraction_intent = session.prepare_call(
        stage="mem0_extraction",
        prior_results=(),
        retrieval_handoff=None,
    )

    lookup = session.lookup(extraction_intent)
    assert lookup.disposition is FreshChainLookupDisposition.TERMINAL
    assert lookup.result is not None
    handoff = session.capture_retrieval(lookup.result)
    infinity_intent = session.prepare_call(
        stage="infinity_answer",
        prior_results=(lookup.result,),
        retrieval_handoff=handoff,
    )

    assert infinity_intent.stage == "infinity_answer"
    assert boundary.dispatch_calls == 0
    assert transport.calls == []
    journal.close()


def test_recovery_returns_authenticated_pre_claim_absence_without_dispatch(
    tmp_path: Path,
) -> None:
    session, boundary, transport, journal, *_ = _session(tmp_path)
    extraction_intent = session.prepare_call(
        stage="mem0_extraction",
        prior_results=(),
        retrieval_handoff=None,
    )

    extraction_absence = session.recover(extraction_intent)

    assert extraction_absence.disposition is (FreshChainLookupDisposition.AUTHENTICATED_ABSENT)
    assert extraction_absence.authenticated_absence_sha256 is not None
    assert boundary.dispatch_calls == 0
    assert boundary.recovery_calls == 0

    extraction = session.dispatch(extraction_intent)
    handoff = session.capture_retrieval(extraction)
    infinity_intent = session.prepare_call(
        stage="infinity_answer",
        prior_results=(extraction,),
        retrieval_handoff=handoff,
    )

    evaluation_absence = session.recover(infinity_intent)

    assert evaluation_absence.disposition is (FreshChainLookupDisposition.AUTHENTICATED_ABSENT)
    assert evaluation_absence.authenticated_absence_sha256 is not None
    assert transport.calls == []
    session.dispatch(infinity_intent)
    assert len(transport.calls) == 1
    journal.close()


@pytest.mark.parametrize(
    ("extraction_ceiling", "total_ceiling"),
    ((4_095, 20_479), (4_096, 20_479)),
)
def test_operator_token_reservations_fail_before_any_receipt(
    tmp_path: Path,
    extraction_ceiling: int,
    total_ceiling: int,
) -> None:
    with pytest.raises(FreshChainCanaryError, match="runtime_composition_invalid"):
        _session(
            tmp_path,
            extraction_token_ceiling=extraction_ceiling,
            total_token_ceiling=total_ceiling,
        )

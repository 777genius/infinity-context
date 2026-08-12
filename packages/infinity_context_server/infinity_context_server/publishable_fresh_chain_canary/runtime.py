"""Provider-ready runtime composition for the exact fresh-chain 1+4 canary.

This module deliberately composes the existing managed-Mem0 one-shot boundary
and the concrete subscription-runtime bridge.  It is not a hosted-job adapter:
the only provider-bearing methods used here are ``dispatch_once`` for the
single extraction and ``SubscriptionRuntimeBridgeAdapter.execute`` for the
four evaluation calls.
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Callable
from contextlib import suppress
from typing import Protocol, final

from infinity_context_server.features.subscription_runtime_bridge import (
    AuthenticatedPreDispatchAbsence,
    BridgeIntent,
    NotFound,
    OutcomeUnknown,
    SubscriptionRuntimeBridgeAdapter,
    TerminalBridgeCall,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    Mem0OssReceiptDisposition,
    RuntimeReceiptVerificationPort,
    RuntimeReceiptVerificationResult,
)
from infinity_context_server.processes.publishable_full_extraction_contracts import (
    PublishableExtractionCommand,
    PublishableExtractionOneShotPort,
)
from infinity_context_server.publishable_durable_scheduler.runner_official_request_renderer import (
    SCHEDULER_OFFICIAL_REQUEST_MAX_OUTPUT_TOKENS,
)

from .contracts import (
    FRESH_CHAIN_STAGES,
    FreshChainCallFailure,
    FreshChainCallIntent,
    FreshChainCallResult,
    FreshChainCanaryError,
    FreshChainCleanupResult,
    FreshChainLookup,
    FreshChainLookupDisposition,
    FreshChainRetrievalHandoff,
    FreshChainStage,
    FreshChainUsage,
    call_intent_sha256,
    canonical_sha256,
)
from .ledger_models import (
    FreshChainFailureDisposition,
    provider_disposition_sha256,
)
from .runtime_identity import (
    require_failure as _require_failure,
)
from .runtime_identity import (
    require_projection_bound_command,
)
from .runtime_identity import (
    require_result as _require_result,
)
from .runtime_identity import (
    same_failure as _same_failure,
)
from .runtime_identity import (
    same_result as _same_result,
)
from .runtime_lookups import (
    ambiguous_lookup as _ambiguous_lookup,
)
from .runtime_lookups import (
    bridge_binding as _bridge_binding,
)
from .runtime_lookups import (
    extraction_context as _extraction_context,
)
from .runtime_lookups import (
    failed_lookup as _failed_lookup,
)
from .runtime_lookups import (
    terminal_lookup as _terminal_lookup,
)


class FreshChainRequestRendererPort(Protocol):
    """Render the pinned common-condition request for one exact stage."""

    @property
    def common_condition_policy_sha256(self) -> str: ...

    def render(
        self,
        *,
        stage: FreshChainStage,
        prior_results: tuple[FreshChainCallResult, ...],
        retrieval_handoff: FreshChainRetrievalHandoff | None,
    ) -> bytes: ...


class FreshChainExtractionAbsencePort(Protocol):
    """Authenticate a provider-specific pre-dispatch absence payload."""

    def authenticate_pre_dispatch_absence(
        self,
        *,
        payload: object,
        command: PublishableExtractionCommand,
        namespace_id: str,
        namespace_commitment_sha256: str,
    ) -> str | None: ...


class FreshChainRetrievalPort(Protocol):
    """Capture retrieval authority from the just-completed extraction."""

    def capture(
        self,
        *,
        extraction: FreshChainCallResult,
        namespace_id: str,
        namespace_commitment_sha256: str,
        source_commitment_sha256: str,
        source_projection_commitment_sha256: str,
    ) -> FreshChainRetrievalHandoff: ...


class FreshChainCleanupPort(Protocol):
    """Delete the exact fresh namespace and return authenticated evidence."""

    def cleanup(
        self,
        *,
        namespace_id: str,
        namespace_commitment_sha256: str,
        failure: FreshChainCallFailure | None = None,
    ) -> FreshChainCleanupResult: ...


@final
class FreshChainCanaryRuntimeSession:
    """Strict five-stage session over the genuine extraction and bridge seams."""

    __slots__ = (
        "_absence",
        "_bridge",
        "_cleanup_port",
        "_cleanup_result",
        "_close_callbacks",
        "_closed",
        "_extraction",
        "_extraction_command",
        "_extraction_verifier",
        "_failures",
        "_lock",
        "_namespace_commitment_sha256",
        "_namespace_id",
        "_prepared",
        "_renderer",
        "_results",
        "_retrieval",
        "_retrieval_handoff",
        "_source_commitment_sha256",
        "_source_projection_commitment_sha256",
    )

    def __init__(
        self,
        *,
        namespace_id: str,
        namespace_commitment_sha256: str,
        source_commitment_sha256: str,
        source_projection_commitment_sha256: str,
        extraction_boundary: PublishableExtractionOneShotPort,
        extraction_command: PublishableExtractionCommand,
        extraction_receipt_verifier: RuntimeReceiptVerificationPort,
        extraction_absence: FreshChainExtractionAbsencePort,
        bridge: SubscriptionRuntimeBridgeAdapter,
        renderer: FreshChainRequestRendererPort,
        retrieval: FreshChainRetrievalPort,
        cleanup: FreshChainCleanupPort,
        extraction_token_ceiling: int = 16_384,
        total_token_ceiling: int = 131_072,
        close_callbacks: tuple[Callable[[], None], ...] = (),
    ) -> None:
        if (
            not _identifier(namespace_id)
            or not _sha(namespace_commitment_sha256)
            or not _sha(source_commitment_sha256)
            or not _sha(source_projection_commitment_sha256)
            or type(extraction_command) is not PublishableExtractionCommand
            or extraction_command.ordinal != 0
            or not _methods(
                extraction_boundary,
                ("dispatch_once", "lookup_outcome", "recover_once"),
            )
            or not _methods(
                extraction_receipt_verifier,
                (
                    "mark_outcome_unknown",
                    "verify_dispatch_receipt",
                    "verify_status_readback",
                ),
            )
            or not _methods(extraction_absence, ("authenticate_pre_dispatch_absence",))
            or type(bridge) is not SubscriptionRuntimeBridgeAdapter
            or not _methods(renderer, ("render",))
            or not _sha(getattr(renderer, "common_condition_policy_sha256", None))
            or not _methods(retrieval, ("capture",))
            or not _methods(cleanup, ("cleanup",))
            or type(extraction_token_ceiling) is not int
            or not SCHEDULER_OFFICIAL_REQUEST_MAX_OUTPUT_TOKENS
            <= extraction_token_ceiling
            <= 10_000_000
            or type(total_token_ceiling) is not int
            or not extraction_token_ceiling
            + len(FRESH_CHAIN_STAGES[1:]) * SCHEDULER_OFFICIAL_REQUEST_MAX_OUTPUT_TOKENS
            <= total_token_ceiling
            <= 50_000_000
            or type(close_callbacks) is not tuple
            or any(not callable(callback) for callback in close_callbacks)
        ):
            _fail("fresh_chain_runtime_composition_invalid")
        self._namespace_id = namespace_id
        self._namespace_commitment_sha256 = namespace_commitment_sha256
        self._source_commitment_sha256 = source_commitment_sha256
        self._source_projection_commitment_sha256 = source_projection_commitment_sha256
        require_projection_bound_command(
            extraction_command,
            namespace_id=namespace_id,
            namespace_commitment_sha256=namespace_commitment_sha256,
            source_projection_commitment_sha256=source_projection_commitment_sha256,
        )
        self._extraction = extraction_boundary
        self._extraction_command = extraction_command
        self._extraction_verifier = extraction_receipt_verifier
        self._absence = extraction_absence
        self._bridge = bridge
        self._renderer = renderer
        self._retrieval = retrieval
        self._cleanup_port = cleanup
        self._close_callbacks = close_callbacks
        self._prepared: dict[str, FreshChainCallIntent] = {}
        self._results: dict[int, FreshChainCallResult] = {}
        self._failures: dict[int, FreshChainCallFailure] = {}
        self._retrieval_handoff: FreshChainRetrievalHandoff | None = None
        self._cleanup_result: FreshChainCleanupResult | None = None
        self._closed = False
        self._lock = threading.RLock()

    @property
    def namespace_id(self) -> str:
        return self._namespace_id

    @property
    def namespace_commitment_sha256(self) -> str:
        return self._namespace_commitment_sha256

    @property
    def source_commitment_sha256(self) -> str:
        return self._source_commitment_sha256

    @property
    def source_projection_commitment_sha256(self) -> str:
        return self._source_projection_commitment_sha256

    @property
    def common_condition_policy_sha256(self) -> str:
        return self._renderer.common_condition_policy_sha256

    def prepare_call(
        self,
        *,
        stage: FreshChainStage,
        prior_results: tuple[FreshChainCallResult, ...],
        retrieval_handoff: FreshChainRetrievalHandoff | None,
    ) -> FreshChainCallIntent:
        """Render only the next exact stage and bind its authoritative input."""

        with self._lock:
            self._require_open()
            ordinal = self._require_prefix(stage, prior_results)
            handoff = self._require_handoff(ordinal, prior_results, retrieval_handoff)
            try:
                body = self._renderer.render(
                    stage=stage,
                    prior_results=prior_results,
                    retrieval_handoff=handoff,
                )
            except Exception:
                _fail("fresh_chain_request_render_failed")
            if type(body) is not bytes or not body:
                _fail("fresh_chain_request_render_invalid")
            if ordinal == 0 and hashlib.sha256(body).hexdigest() != (
                self._extraction_command.request_body_sha256
            ):
                _fail("fresh_chain_extraction_request_crosswire")
            input_authority = self._input_authority(
                stage=stage,
                prior_results=prior_results,
                handoff=handoff,
            )
            intent = FreshChainCallIntent(
                stage=stage,
                ordinal=ordinal,
                namespace_id=self._namespace_id,
                namespace_commitment_sha256=self._namespace_commitment_sha256,
                source_commitment_sha256=self._source_commitment_sha256,
                source_projection_commitment_sha256=(self._source_projection_commitment_sha256),
                input_authority_sha256=input_authority,
                canonical_request_body=body,
                retrieval_handoff_sha256=(
                    handoff.handoff_sha256 if stage == "mem0_answer" else None
                ),
            )
            current = self._prepared.get(stage)
            if current is not None and current != intent:
                _fail("fresh_chain_intent_replay_conflict")
            self._prepared[stage] = intent
            return intent

    def lookup(self, intent: FreshChainCallIntent) -> FreshChainLookup:
        """Read authenticated state only; this method has no dispatch path."""

        with self._lock:
            self._require_open()
            self._require_intent(intent)
            cached = self._results.get(intent.ordinal)
            if cached is not None:
                _require_result(intent, cached)
                return _terminal_lookup(cached)
            failed = self._failures.get(intent.ordinal)
            if failed is not None:
                _require_failure(intent, failed)
                return _failed_lookup(failed)
            if intent.ordinal == 0:
                return self._lookup_extraction(intent)
            return self._lookup_evaluation(intent)

    def dispatch(
        self,
        intent: FreshChainCallIntent,
    ) -> FreshChainCallResult | FreshChainCallFailure:
        """Dispatch only after a fresh authenticated absence for this intent."""

        with self._lock:
            self._require_open()
            self._require_intent(intent)
            self._require_dispatch_order(intent)
            preflight = self.lookup(intent)
            if preflight.disposition is not FreshChainLookupDisposition.AUTHENTICATED_ABSENT:
                _fail("fresh_chain_dispatch_precondition_rejected")
            if intent.ordinal == 0:
                result = self._dispatch_extraction(intent)
            else:
                result = self._dispatch_evaluation(intent)
            if type(result) is FreshChainCallFailure:
                self._accept_failure(intent, result)
            else:
                self._accept_result(intent, result)
            return result

    def recover(self, intent: FreshChainCallIntent) -> FreshChainLookup:
        """Recover by authenticated readback, including proven pre-call absence."""

        with self._lock:
            self._require_open()
            self._require_intent(intent)
            cached = self._results.get(intent.ordinal)
            if cached is not None:
                return _terminal_lookup(cached)
            failed = self._failures.get(intent.ordinal)
            if failed is not None:
                return _failed_lookup(failed)
            if intent.ordinal != 0:
                observed = self._lookup_evaluation(intent)
                if observed.disposition is FreshChainLookupDisposition.TERMINAL:
                    assert observed.result is not None
                    self._accept_result(intent, observed.result)
                return observed
            try:
                # First distinguish the crash-before-claim window without
                # touching provider transport.  Once claimed, the established
                # one-shot recovery seam performs status readback only.
                observed = self._extraction.lookup_outcome(command=self._extraction_command)
                absence = self._authenticate_extraction_absence(observed)
                if absence is not None:
                    return FreshChainLookup(
                        disposition=FreshChainLookupDisposition.AUTHENTICATED_ABSENT,
                        intent_sha256=intent.intent_sha256,
                        authenticated_absence_sha256=absence,
                    )
                self._mark_extraction_unknown()
                payload = self._extraction.recover_once(command=self._extraction_command)
                result = self._translate_extraction(
                    intent=intent,
                    payload=payload,
                    readback=True,
                    transport_dispatched=False,
                )
                if type(result) is FreshChainCallFailure:
                    self._accept_failure(intent, result)
                    return _failed_lookup(result)
                self._accept_result(intent, result)
                return _terminal_lookup(result)
            except BaseException:
                return _ambiguous_lookup(intent, {"kind": "extraction_recovery_failed"})

    def capture_retrieval(
        self,
        extraction: FreshChainCallResult,
    ) -> FreshChainRetrievalHandoff:
        """Capture the sole authority allowed to feed the Mem0 answer."""

        with self._lock:
            self._require_open()
            if type(extraction) is not FreshChainCallResult or extraction.ordinal != 0:
                _fail("fresh_chain_retrieval_extraction_invalid")
            known = self._results.get(0)
            if known is None or not _same_result(known, extraction):
                _fail("fresh_chain_retrieval_extraction_crosswire")
            if self._retrieval_handoff is not None:
                return self._retrieval_handoff
            try:
                handoff = self._retrieval.capture(
                    extraction=extraction,
                    namespace_id=self._namespace_id,
                    namespace_commitment_sha256=self._namespace_commitment_sha256,
                    source_commitment_sha256=self._source_commitment_sha256,
                    source_projection_commitment_sha256=(self._source_projection_commitment_sha256),
                )
            except Exception:
                _fail("fresh_chain_retrieval_capture_failed")
            self._validate_handoff(handoff, extraction)
            self._retrieval_handoff = handoff
            return handoff

    def cleanup(
        self,
        failure: FreshChainCallFailure | None = None,
    ) -> FreshChainCleanupResult:
        """Delete the exact fresh namespace after success or a known failure."""

        with self._lock:
            self._require_open()
            if self._cleanup_result is not None:
                return self._cleanup_result
            if failure is None:
                if self._failures or tuple(self._results) != tuple(range(len(FRESH_CHAIN_STAGES))):
                    _fail("fresh_chain_cleanup_before_completion")
            else:
                self._require_failure_for_cleanup(failure)
            try:
                result = self._cleanup_port.cleanup(
                    namespace_id=self._namespace_id,
                    namespace_commitment_sha256=self._namespace_commitment_sha256,
                    failure=failure,
                )
            except Exception:
                _fail("fresh_chain_cleanup_failed")
            if (
                type(result) is not FreshChainCleanupResult
                or result.namespace_commitment_sha256 != self._namespace_commitment_sha256
                or result.deleted is not True
                or result.operation_count != 1
                or result.residual_count != 0
            ):
                _fail("fresh_chain_cleanup_invalid")
            self._cleanup_result = result
            return result

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            first: BaseException | None = None
            for callback in self._close_callbacks:
                try:
                    callback()
                except BaseException as error:
                    if first is None:
                        first = error
            if first is not None:
                raise first

    def _lookup_extraction(self, intent: FreshChainCallIntent) -> FreshChainLookup:
        try:
            payload = self._extraction.lookup_outcome(command=self._extraction_command)
        except BaseException:
            return _ambiguous_lookup(intent, {"kind": "extraction_lookup_failed"})
        absence = self._authenticate_extraction_absence(payload)
        if absence is not None:
            return FreshChainLookup(
                disposition=FreshChainLookupDisposition.AUTHENTICATED_ABSENT,
                intent_sha256=intent.intent_sha256,
                authenticated_absence_sha256=absence,
            )
        self._mark_extraction_unknown()
        try:
            result = self._translate_extraction(
                intent=intent,
                payload=payload,
                readback=True,
                transport_dispatched=False,
            )
        except BaseException:
            _fail("fresh_chain_extraction_lookup_invalid")
        if type(result) is FreshChainCallFailure:
            self._accept_failure(intent, result)
            return _failed_lookup(result)
        self._accept_result(intent, result)
        return _terminal_lookup(result)

    def _lookup_evaluation(self, intent: FreshChainCallIntent) -> FreshChainLookup:
        binding = _bridge_binding(intent)
        try:
            outcome = self._bridge.lookup_pre_dispatch(binding)
        except Exception:
            _fail("fresh_chain_bridge_lookup_invalid")
        if type(outcome) is TerminalBridgeCall:
            result = self._translate_bridge(intent, outcome, transport_dispatched=False)
            self._accept_result(intent, result)
            return _terminal_lookup(result)
        if type(outcome) is AuthenticatedPreDispatchAbsence:
            if outcome.binding != binding or not self._bridge.authenticate_pre_dispatch_absence(
                outcome
            ):
                _fail("fresh_chain_bridge_absence_unauthenticated")
            return FreshChainLookup(
                disposition=FreshChainLookupDisposition.AUTHENTICATED_ABSENT,
                intent_sha256=intent.intent_sha256,
                authenticated_absence_sha256=canonical_sha256(outcome.public_payload()),
            )
        if type(outcome) is OutcomeUnknown:
            self._require_bridge_intent(intent, outcome.intent)
            return _ambiguous_lookup(
                intent,
                {"bridge_intent": outcome.intent.public_payload(), "kind": "outcome_unknown"},
            )
        if type(outcome) is NotFound:
            _fail("fresh_chain_bridge_lookup_invalid")
        _fail("fresh_chain_bridge_lookup_invalid")

    def _dispatch_extraction(
        self,
        intent: FreshChainCallIntent,
    ) -> FreshChainCallResult | FreshChainCallFailure:
        try:
            payload = self._extraction.dispatch_once(command=self._extraction_command)
        except BaseException:
            self._mark_extraction_unknown()
            _fail("fresh_chain_extraction_dispatch_ambiguous")
        try:
            return self._translate_extraction(
                intent=intent,
                payload=payload,
                readback=False,
                transport_dispatched=True,
            )
        except FreshChainCanaryError:
            raise
        except BaseException:
            self._mark_extraction_unknown()
            _fail("fresh_chain_extraction_receipt_invalid")

    def _dispatch_evaluation(self, intent: FreshChainCallIntent) -> FreshChainCallResult:
        try:
            outcome = self._bridge.execute(
                binding=_bridge_binding(intent),
                canonical_request_body=intent.canonical_request_body,
            )
        except BaseException:
            _fail("fresh_chain_evaluation_dispatch_ambiguous")
        if type(outcome) is OutcomeUnknown:
            self._require_bridge_intent(intent, outcome.intent)
            _fail("fresh_chain_evaluation_dispatch_ambiguous")
        if type(outcome) is not TerminalBridgeCall:
            _fail("fresh_chain_evaluation_dispatch_invalid")
        if outcome.transport_dispatched is not True:
            _fail("fresh_chain_evaluation_dispatch_duplicate")
        return self._translate_bridge(intent, outcome, transport_dispatched=True)

    def _translate_extraction(
        self,
        *,
        intent: FreshChainCallIntent,
        payload: object,
        readback: bool,
        transport_dispatched: bool,
    ) -> FreshChainCallResult | FreshChainCallFailure:
        context = _extraction_context(self._extraction_command, readback=readback)
        if readback:
            verified = self._extraction_verifier.verify_status_readback(
                payload=payload,
                context=context,
            )
        else:
            verified = self._extraction_verifier.verify_dispatch_receipt(
                payload=payload,
                context=context,
            )
        command = self._extraction_command
        if (
            type(verified) is not RuntimeReceiptVerificationResult
            or verified.sequence != command.ordinal
            or verified.admission_commitment_sha256 != command.admission_commitment_sha256
            or verified.operation_id_sha256 != command.operation_id_sha256
            or verified.unit_identity_sha256 != command.unit_identity_sha256
            or verified.unit_sha256 != command.unit_sha256
            or verified.route_sha256 != command.route_sha256
            or verified.scope_sha256 != command.scope_sha256
            or verified.request_body_sha256 != command.request_body_sha256
            or verified.extraction_calls != 1
            or verified.retry_count != 0
        ):
            _fail("fresh_chain_extraction_receipt_crosswire")
        usage = FreshChainUsage(
            prompt_tokens=verified.request_tokens,
            completion_tokens=verified.response_tokens,
            total_tokens=verified.request_tokens + verified.response_tokens,
        )
        commitments = {
            "admission_commitment_sha256": verified.admission_commitment_sha256,
            "operation_id_sha256": verified.operation_id_sha256,
            "output_text_sha256": verified.output_text_sha256,
            "request_body_sha256": verified.request_body_sha256,
            "run_identity_commitment_sha256": command.run_identity_commitment_sha256,
            "runtime_binding_commitment_sha256": (verified.runtime_binding_commitment_sha256),
            "source_projection_commitment_sha256": (self._source_projection_commitment_sha256),
            "scope_sha256": verified.scope_sha256,
            "unit_identity_sha256": verified.unit_identity_sha256,
            "unit_sha256": verified.unit_sha256,
        }
        if verified.disposition is not Mem0OssReceiptDisposition.COMPLETED:
            try:
                disposition = FreshChainFailureDisposition(verified.disposition.value)
            except (AttributeError, ValueError):
                _fail("fresh_chain_extraction_receipt_crosswire")
            failure_commitments = {
                **commitments,
                "provider_disposition_sha256": provider_disposition_sha256(disposition),
            }
            return FreshChainCallFailure(
                stage="mem0_extraction",
                ordinal=0,
                intent_sha256=intent.intent_sha256,
                physical_receipt_sha256=verified.provider_receipt_sha256,
                receipt_id=f"mem0-extraction:{verified.provider_receipt_sha256}",
                usage=usage,
                provider_disposition=disposition,
                transport_dispatched=transport_dispatched,
                commitments=failure_commitments,
            )
        result_material = {
            "admission_commitment_sha256": verified.admission_commitment_sha256,
            "operation_id_sha256": verified.operation_id_sha256,
            "output_text_sha256": verified.output_text_sha256,
            "provider_receipt_sha256": verified.provider_receipt_sha256,
            "request_body_sha256": verified.request_body_sha256,
            "run_identity_commitment_sha256": (command.run_identity_commitment_sha256),
            "runtime_binding_commitment_sha256": (verified.runtime_binding_commitment_sha256),
            "scope_sha256": verified.scope_sha256,
            "sequence": verified.sequence,
            "unit_identity_sha256": verified.unit_identity_sha256,
            "unit_sha256": verified.unit_sha256,
        }
        return FreshChainCallResult(
            stage="mem0_extraction",
            ordinal=0,
            intent_sha256=intent.intent_sha256,
            result_sha256=canonical_sha256(result_material),
            physical_receipt_sha256=verified.provider_receipt_sha256,
            receipt_id=f"mem0-extraction:{verified.provider_receipt_sha256}",
            usage=usage,
            transport_dispatched=transport_dispatched,
            commitments=commitments,
        )

    def _translate_bridge(
        self,
        intent: FreshChainCallIntent,
        terminal: TerminalBridgeCall,
        *,
        transport_dispatched: bool,
    ) -> FreshChainCallResult:
        if type(terminal) is not TerminalBridgeCall:
            _fail("fresh_chain_bridge_terminal_invalid")
        self._require_bridge_intent(intent, terminal.readback.intent)
        result = terminal.readback.result
        try:
            result.__post_init__()
            output = terminal.private_output.render_for_judge()
        except Exception:
            _fail("fresh_chain_bridge_terminal_invalid")
        if (
            type(output) is not str
            or hashlib.sha256(output.encode()).hexdigest() != result.output_text_sha256
            or terminal.transport_dispatched is not transport_dispatched
        ):
            _fail("fresh_chain_bridge_terminal_crosswire")
        bridge_intent_sha256 = canonical_sha256(terminal.readback.intent.public_payload())
        encrypted_output_sha256 = hashlib.sha256(result.encrypted_output).hexdigest()
        result_sha256 = canonical_sha256(
            {
                "bridge_intent_sha256": bridge_intent_sha256,
                "bridge_result": result.public_payload(include_ciphertext=False),
                "encrypted_output_sha256": encrypted_output_sha256,
            }
        )
        return FreshChainCallResult(
            stage=intent.stage,
            ordinal=intent.ordinal,
            intent_sha256=intent.intent_sha256,
            result_sha256=result_sha256,
            physical_receipt_sha256=result.physical_receipt_sha256,
            receipt_id=f"subscription-runtime:{result.physical_receipt_sha256}",
            usage=FreshChainUsage(
                prompt_tokens=result.usage.prompt_tokens,
                completion_tokens=result.usage.completion_tokens,
                total_tokens=result.usage.total_tokens,
            ),
            transport_dispatched=transport_dispatched,
            output_text=output,
            commitments={
                "bridge_intent_sha256": bridge_intent_sha256,
                "encrypted_output_sha256": encrypted_output_sha256,
                "output_text_sha256": result.output_text_sha256,
                "request_body_sha256": intent.request_sha256,
                "response_body_sha256": result.response_body_sha256,
            },
        )

    def _require_bridge_intent(
        self,
        intent: FreshChainCallIntent,
        bridge_intent: object,
    ) -> None:
        if (
            type(bridge_intent) is not BridgeIntent
            or bridge_intent.binding != _bridge_binding(intent)
            or bridge_intent.request_body_sha256 != intent.request_sha256
        ):
            _fail("fresh_chain_bridge_intent_crosswire")

    def _authenticate_extraction_absence(self, payload: object) -> str | None:
        try:
            proof = self._absence.authenticate_pre_dispatch_absence(
                payload=payload,
                command=self._extraction_command,
                namespace_id=self._namespace_id,
                namespace_commitment_sha256=self._namespace_commitment_sha256,
            )
        except Exception:
            _fail("fresh_chain_extraction_absence_invalid")
        if proof is not None and not _sha(proof):
            _fail("fresh_chain_extraction_absence_invalid")
        return proof

    def _mark_extraction_unknown(self) -> None:
        with suppress(BaseException):
            self._extraction_verifier.mark_outcome_unknown(
                context=_extraction_context(self._extraction_command, readback=False)
            )

    def _require_prefix(
        self,
        stage: object,
        prior_results: object,
    ) -> int:
        if type(stage) is not str or stage not in FRESH_CHAIN_STAGES:
            _fail("fresh_chain_stage_unknown")
        ordinal = FRESH_CHAIN_STAGES.index(stage)
        if type(prior_results) is not tuple or len(prior_results) != ordinal:
            _fail("fresh_chain_stage_out_of_order")
        if any(
            type(result) is not FreshChainCallResult
            or result.ordinal != index
            or result.stage != FRESH_CHAIN_STAGES[index]
            for index, result in enumerate(prior_results)
        ):
            _fail("fresh_chain_stage_out_of_order")
        if len({result.intent_sha256 for result in prior_results}) != len(prior_results) or len(
            {result.physical_receipt_sha256 for result in prior_results}
        ) != len(prior_results):
            _fail("fresh_chain_result_duplicate")
        for result in prior_results:
            current = self._results.get(result.ordinal)
            if current is None:
                _fail("fresh_chain_prior_result_unverified")
            if not _same_result(current, result):
                _fail("fresh_chain_result_replay_conflict")
        return ordinal

    def _require_handoff(
        self,
        ordinal: int,
        prior_results: tuple[FreshChainCallResult, ...],
        handoff: FreshChainRetrievalHandoff | None,
    ) -> FreshChainRetrievalHandoff | None:
        if ordinal == 0:
            if handoff is not None:
                _fail("fresh_chain_retrieval_handoff_out_of_order")
            return None
        if type(handoff) is not FreshChainRetrievalHandoff:
            _fail("fresh_chain_retrieval_handoff_missing")
        self._validate_handoff(handoff, prior_results[0])
        if self._retrieval_handoff is None:
            _fail("fresh_chain_retrieval_handoff_not_captured")
        if self._retrieval_handoff != handoff:
            _fail("fresh_chain_retrieval_handoff_replay_conflict")
        return handoff

    def _validate_handoff(
        self,
        handoff: object,
        extraction: FreshChainCallResult,
    ) -> None:
        if (
            type(handoff) is not FreshChainRetrievalHandoff
            or handoff.extraction_intent_sha256 != extraction.intent_sha256
            or handoff.extraction_result_sha256 != extraction.result_sha256
            or handoff.extraction_receipt_sha256 != extraction.physical_receipt_sha256
            or handoff.namespace_commitment_sha256 != self._namespace_commitment_sha256
            or handoff.source_commitment_sha256 != self._source_commitment_sha256
            or handoff.source_projection_commitment_sha256
            != self._source_projection_commitment_sha256
            or handoff.memory_count < 1
        ):
            _fail("fresh_chain_retrieval_handoff_crosswire")

    def _input_authority(
        self,
        *,
        stage: FreshChainStage,
        prior_results: tuple[FreshChainCallResult, ...],
        handoff: FreshChainRetrievalHandoff | None,
    ) -> str:
        if stage == "mem0_extraction":
            return self._source_projection_commitment_sha256
        if stage == "infinity_answer":
            return self._source_commitment_sha256
        elif stage == "infinity_judge":
            return prior_results[1].result_sha256
        elif stage == "mem0_answer":
            assert handoff is not None
            return handoff.retrieval_authority_sha256
        elif stage == "mem0_judge":
            return prior_results[3].result_sha256
        else:  # pragma: no cover - guarded by the fixed stage tuple
            _fail("fresh_chain_stage_unknown")

    def _require_intent(self, intent: object) -> None:
        if (
            type(intent) is not FreshChainCallIntent
            or intent.namespace_id != self._namespace_id
            or intent.namespace_commitment_sha256 != self._namespace_commitment_sha256
            or intent.source_commitment_sha256 != self._source_commitment_sha256
            or intent.source_projection_commitment_sha256
            != self._source_projection_commitment_sha256
            or intent.request_sha256 != hashlib.sha256(intent.canonical_request_body).hexdigest()
            or intent.intent_sha256 != call_intent_sha256(intent)
            or self._prepared.get(intent.stage) != intent
        ):
            _fail("fresh_chain_intent_crosswire")

    def _require_dispatch_order(self, intent: FreshChainCallIntent) -> None:
        if self._failures or tuple(sorted(self._results)) != tuple(range(intent.ordinal)):
            _fail("fresh_chain_dispatch_out_of_order")
        if intent.ordinal > 0 and self._retrieval_handoff is None:
            _fail("fresh_chain_retrieval_handoff_missing")

    def _accept_result(
        self,
        intent: FreshChainCallIntent,
        result: FreshChainCallResult,
    ) -> None:
        _require_result(intent, result)
        if any(
            other.ordinal != result.ordinal
            and (
                other.intent_sha256 == result.intent_sha256
                or other.physical_receipt_sha256 == result.physical_receipt_sha256
            )
            for other in self._results.values()
        ) or any(
            other.physical_receipt_sha256 == result.physical_receipt_sha256
            for other in self._failures.values()
        ):
            _fail("fresh_chain_result_duplicate")
        current = self._results.get(result.ordinal)
        if current is not None and not _same_result(current, result):
            _fail("fresh_chain_result_replay_conflict")
        if current is None:
            self._results[result.ordinal] = result

    def _accept_failure(
        self,
        intent: FreshChainCallIntent,
        failure: FreshChainCallFailure,
    ) -> None:
        _require_failure(intent, failure)
        current = self._failures.get(failure.ordinal)
        if current is not None:
            if not _same_failure(current, failure):
                _fail("fresh_chain_failure_replay_conflict")
            return
        prior_receipts = {item.physical_receipt_sha256 for item in self._results.values()} | {
            item.physical_receipt_sha256 for item in self._failures.values()
        }
        if failure.physical_receipt_sha256 in prior_receipts:
            _fail("fresh_chain_result_duplicate")
        if tuple(sorted(self._results)) != tuple(range(failure.ordinal)):
            _fail("fresh_chain_failure_out_of_order")
        self._failures[failure.ordinal] = failure

    def _require_failure_for_cleanup(self, failure: FreshChainCallFailure) -> None:
        if type(failure) is not FreshChainCallFailure:
            _fail("fresh_chain_cleanup_failure_invalid")
        known = self._failures.get(failure.ordinal)
        if known is None or not _same_failure(known, failure):
            _fail("fresh_chain_cleanup_failure_invalid")
        if tuple(sorted(self._results)) != tuple(range(failure.ordinal)):
            _fail("fresh_chain_cleanup_failure_invalid")

    def _require_open(self) -> None:
        if self._closed:
            _fail("fresh_chain_runtime_closed")


def _methods(value: object, names: tuple[str, ...]) -> bool:
    return all(callable(getattr(value, name, None)) for name in names)


def _identifier(value: object) -> bool:
    return (
        type(value) is str
        and 0 < len(value) <= 512
        and value == value.strip()
        and all(character.isalnum() or character in "._:-" for character in value)
    )


def _sha(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _fail(code: str) -> None:
    raise FreshChainCanaryError(code) from None


__all__ = (
    "FreshChainCanaryRuntimeSession",
    "FreshChainCleanupPort",
    "FreshChainExtractionAbsencePort",
    "FreshChainRequestRendererPort",
    "FreshChainRetrievalPort",
)

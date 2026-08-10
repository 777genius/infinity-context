"""Resumable two-run composition over the authenticated SQLite scheduler."""

from __future__ import annotations

import hashlib
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import final

from infinity_context_server.publishable_durable_scheduler.contracts import (
    SchedulerCallStage,
    SchedulerRunAuthority,
    SchedulerSuiteAuthority,
    commitment,
)
from infinity_context_server.publishable_durable_scheduler.manifest import (
    BuiltSchedulerManifest,
    SchedulerLogicalCall,
)
from infinity_context_server.publishable_durable_scheduler.runner_contracts import (
    NO_EXTRACTION_TERMINAL_READ_POLICY_SHA256,
    NO_OUTCOME_READBACK_POLICY_SHA256,
    PUBLISHABLE_SUITE_CASE_COUNT,
    PUBLISHABLE_SUITE_EVALUATION_CALL_COUNT,
    PUBLISHABLE_SUITE_EXTRACTION_OPERATION_COUNT,
    RUNNER_ATTESTATION_BYTES_CAP,
    RUNNER_PAGE_SIZE,
    SCHEDULER_PRODUCTION_BRIDGE_ADAPTER_READY,
    SCHEDULER_RUNNER_PAID_GO_READY,
    SCHEDULER_RUNNER_PUBLISHABLE,
    SCHEDULER_RUNNER_READINESS_BLOCKERS,
    SUITE_SEAL_READBACK_POLICY_SHA256,
    SchedulerDispatchEnvelope,
    SchedulerDispatchOutcome,
    SchedulerDispatchReceipt,
    SchedulerDispatchReconciliationPort,
    SchedulerExtractionTerminalReadPort,
    SchedulerOneShotDispatchPort,
    SchedulerPrivateAnswerReadCapability,
    SchedulerReceiptVerifierPort,
    SchedulerRenderedRequest,
    SchedulerRequestContext,
    SchedulerRequestRendererPort,
    SchedulerRunnerError,
    SchedulerRunStoreSpec,
    SchedulerStepDisposition,
    SchedulerStepResult,
    SchedulerSuiteSeal,
    SchedulerSuiteSealStoreSpec,
    bound_request_sha256,
    dispatch_intent_sha256,
    is_sha256,
)
from infinity_context_server.publishable_durable_scheduler.runner_recovery import (
    reconcile_expired_intent,
)
from infinity_context_server.publishable_durable_scheduler.runner_sealing import (
    SchedulerSuiteSealBindingPort,
    bind_suite_seal,
    evaluation_summary,
    read_authenticated_extraction_terminals,
    validate_suite_seal_binding,
)
from infinity_context_server.publishable_durable_scheduler.runner_suite_binding import (
    read_bound_suite_seal,
    require_exact_suite,
)
from infinity_context_server.publishable_durable_scheduler.sqlite_contracts import (
    ANSWER_CIPHERTEXT_BYTES_CAP,
    SchedulerSQLiteError,
    ciphertext_material,
)
from infinity_context_server.publishable_durable_scheduler.sqlite_store import (
    SQLiteDurableSchedulerStore,
)
from infinity_context_server.publishable_durable_scheduler.state_models import (
    SchedulerCallPhase,
    SchedulerCallState,
    SchedulerRunPhase,
)
from infinity_context_server.publishable_durable_scheduler.suite_seal_store import (
    SQLiteSchedulerSuiteSealStore,
)

_DEFAULT_LEASE_DURATION_MS = 60_000


@final
@dataclass(frozen=True, slots=True)
class _RunEntry:
    run: SchedulerRunAuthority
    manifest: BuiltSchedulerManifest
    store: SQLiteDurableSchedulerStore
    authentication_secret: bytes


@final
class PublishableResumableEvaluationRunner:
    """Fail-closed coordinator for one exact frozen two-benchmark suite."""

    paid_go_ready = SCHEDULER_RUNNER_PAID_GO_READY
    publishable = SCHEDULER_RUNNER_PUBLISHABLE
    production_bridge_adapter_ready = SCHEDULER_PRODUCTION_BRIDGE_ADAPTER_READY
    readiness_blockers = SCHEDULER_RUNNER_READINESS_BLOCKERS

    __slots__ = (
        "_after_ordinals",
        "_boundary",
        "_clock",
        "_entries",
        "_extraction_read_policy_sha256",
        "_extraction_terminal_reader",
        "_lease_duration_ms",
        "_lease_id_factory",
        "_outcome_readback_policy_sha256",
        "_private_answer_policy_sha256",
        "_reconciliation",
        "_receipt_verifier",
        "_renderer_policy_sha256",
        "_request_renderer",
        "_seal_store",
        "_suite",
        "_suite_authority_sha256",
        "_suite_seal_binding",
        "_suite_seal_binding_policy_sha256",
    )

    def __init__(
        self,
        *,
        suite: SchedulerSuiteAuthority,
        run_stores: tuple[SchedulerRunStoreSpec, SchedulerRunStoreSpec],
        request_renderer: SchedulerRequestRendererPort,
        boundary: SchedulerOneShotDispatchPort,
        receipt_verifier: SchedulerReceiptVerifierPort,
        extraction_terminal_reader: SchedulerExtractionTerminalReadPort | None = None,
        reconciliation: SchedulerDispatchReconciliationPort | None = None,
        suite_seal_store: SchedulerSuiteSealStoreSpec | None = None,
        suite_seal_binding: SchedulerSuiteSealBindingPort | None = None,
        clock: Callable[[], int] = lambda: time.time_ns() // 1_000_000,
        lease_id_factory: Callable[[], str] = lambda: secrets.token_hex(32),
        lease_duration_ms: int = _DEFAULT_LEASE_DURATION_MS,
    ) -> None:
        if (
            type(suite) is not SchedulerSuiteAuthority
            or type(run_stores) is not tuple
            or len(run_stores) != 2
            or any(type(item) is not SchedulerRunStoreSpec for item in run_stores)
            or not callable(getattr(request_renderer, "render", None))
            or not callable(getattr(boundary, "preflight", None))
            or not callable(getattr(boundary, "invoke_once", None))
            or not callable(getattr(receipt_verifier, "verify", None))
            or extraction_terminal_reader is not None
            and not callable(getattr(extraction_terminal_reader, "read_terminal", None))
            or reconciliation is not None
            and any(
                not callable(getattr(reconciliation, name, None))
                for name in ("lookup", "authenticate")
            )
            or suite_seal_store is not None
            and type(suite_seal_store) is not SchedulerSuiteSealStoreSpec
            or suite_seal_binding is not None
            and any(
                not callable(getattr(suite_seal_binding, name, None))
                for name in ("bind", "validate")
            )
            or not callable(clock)
            or not callable(lease_id_factory)
            or type(lease_duration_ms) is not int
            or lease_duration_ms < 1
        ):
            _fail("scheduler_runner_composition_invalid")
        require_exact_suite(suite, run_stores)
        self._suite = suite
        self._suite_authority_sha256 = suite.commitment_sha256
        self._request_renderer = request_renderer
        self._boundary = boundary
        self._receipt_verifier = receipt_verifier
        self._extraction_terminal_reader = extraction_terminal_reader
        self._reconciliation = reconciliation
        self._suite_seal_binding = suite_seal_binding
        self._clock = clock
        self._lease_id_factory = lease_id_factory
        self._lease_duration_ms = lease_duration_ms
        self._renderer_policy_sha256 = _port_digest(
            request_renderer,
            "renderer_policy_sha256",
        )
        self._private_answer_policy_sha256 = _port_digest(
            request_renderer,
            "private_answer_policy_sha256",
        )
        self._outcome_readback_policy_sha256 = (
            NO_OUTCOME_READBACK_POLICY_SHA256
            if reconciliation is None
            else _port_digest(reconciliation, "readback_policy_sha256")
        )
        self._extraction_read_policy_sha256 = (
            NO_EXTRACTION_TERMINAL_READ_POLICY_SHA256
            if extraction_terminal_reader is None
            else _port_digest(extraction_terminal_reader, "read_policy_sha256")
        )
        self._suite_seal_binding_policy_sha256 = (
            None
            if suite_seal_binding is None
            else _port_digest(suite_seal_binding, "policy_sha256")
        )
        self._require_composition_binding()
        entries: list[_RunEntry] = []
        for spec in run_stores:
            store = SQLiteDurableSchedulerStore(
                spec.database_path,
                private_directory=spec.private_directory,
                authentication_secret=spec.authentication_secret,
                suite=suite,
                run=spec.run,
                manifest=spec.manifest,
            )
            store.verify()
            entries.append(
                _RunEntry(
                    spec.run,
                    spec.manifest,
                    store,
                    spec.authentication_secret,
                )
            )
        self._entries = tuple(entries)
        selected_seal_store = suite_seal_store or SchedulerSuiteSealStoreSpec(
            database_path=run_stores[0].private_directory / "suite-seal.sqlite3",
            private_directory=run_stores[0].private_directory,
            authentication_secret=run_stores[0].authentication_secret,
        )
        self._seal_store = SQLiteSchedulerSuiteSealStore(
            selected_seal_store.database_path,
            private_directory=selected_seal_store.private_directory,
            authentication_secret=selected_seal_store.authentication_secret,
            suite_authority_sha256=suite.commitment_sha256,
        )
        if self._seal_store.readback_policy_sha256 != SUITE_SEAL_READBACK_POLICY_SHA256:
            _fail("scheduler_runner_composition_binding_invalid")
        self._after_ordinals = [-1, -1]
        self._read_bound_suite_seal()
        self._recover_all_inflight()

    @classmethod
    def open(
        cls,
        *,
        suite: SchedulerSuiteAuthority,
        run_stores: tuple[SchedulerRunStoreSpec, SchedulerRunStoreSpec],
        request_renderer: SchedulerRequestRendererPort,
        boundary: SchedulerOneShotDispatchPort,
        receipt_verifier: SchedulerReceiptVerifierPort,
        extraction_terminal_reader: SchedulerExtractionTerminalReadPort | None = None,
        reconciliation: SchedulerDispatchReconciliationPort | None = None,
        suite_seal_store: SchedulerSuiteSealStoreSpec | None = None,
        suite_seal_binding: SchedulerSuiteSealBindingPort | None = None,
        clock: Callable[[], int] = lambda: time.time_ns() // 1_000_000,
        lease_id_factory: Callable[[], str] = lambda: secrets.token_hex(32),
        lease_duration_ms: int = _DEFAULT_LEASE_DURATION_MS,
    ) -> PublishableResumableEvaluationRunner:
        """Open or create both exact stores and reconcile interrupted attempts."""

        return cls(
            suite=suite,
            run_stores=run_stores,
            request_renderer=request_renderer,
            boundary=boundary,
            receipt_verifier=receipt_verifier,
            extraction_terminal_reader=extraction_terminal_reader,
            reconciliation=reconciliation,
            suite_seal_store=suite_seal_store,
            suite_seal_binding=suite_seal_binding,
            clock=clock,
            lease_id_factory=lease_id_factory,
            lease_duration_ms=lease_duration_ms,
        )

    @property
    def case_count(self) -> int:
        return PUBLISHABLE_SUITE_CASE_COUNT

    @property
    def evaluation_call_count(self) -> int:
        return PUBLISHABLE_SUITE_EVALUATION_CALL_COUNT

    def run_next(self) -> SchedulerStepResult:
        """Dispatch at most one provider call, or report a durable stop state."""

        self._require_composition_binding()
        self._read_bound_suite_seal()
        now = self._now()
        for entry in self._entries:
            self._recover_inflight(entry, now=now)
        terminal = self._terminal_step()
        if terminal is not None:
            return terminal

        all_complete = True
        for index, entry in enumerate(self._entries):
            run_state = entry.store.read_run()
            if run_state.phase is SchedulerRunPhase.SEALED:
                continue
            call, blocked = self._next_planned(index, entry)
            if blocked:
                return SchedulerStepResult(
                    SchedulerStepDisposition.BLOCKED,
                    entry.run.binding.run_id,
                    run_state.inflight_logical_call_id,
                    0,
                )
            if call is None:
                continue
            all_complete = False
            now = self._now()
            if now >= run_state.dispatch_deadline_unix_ms:
                entry.store.exhaust_deadline(now_unix_ms=now)
                return SchedulerStepResult(
                    SchedulerStepDisposition.DEADLINE_EXHAUSTED,
                    entry.run.binding.run_id,
                    None,
                    0,
                )
            return self._dispatch(index, entry, call, now=now)
        if all_complete:
            return SchedulerStepResult(
                SchedulerStepDisposition.EVALUATION_COMPLETE,
                None,
                None,
                0,
            )
        _fail("scheduler_runner_selection_invalid")

    def run_bounded(self, *, max_dispatches: int) -> SchedulerStepResult:
        """Make bounded progress; callers retain explicit control of paid attempts."""

        if (
            type(max_dispatches) is not int
            or not 1 <= max_dispatches <= PUBLISHABLE_SUITE_EVALUATION_CALL_COUNT
        ):
            _fail("scheduler_runner_dispatch_bound_invalid")
        dispatched = 0
        while dispatched < max_dispatches:
            result = self.run_next()
            dispatched += result.provider_dispatches
            if result.disposition is not SchedulerStepDisposition.COMMITTED:
                return result
        return result

    def committed_call_count(self) -> int:
        """Count committed calls using only bounded authenticated pages."""

        count = 0
        for entry in self._entries:
            after = -1
            while page := entry.store.read_calls(
                after_ordinal=after,
                limit=RUNNER_PAGE_SIZE,
            ):
                count += sum(item.phase is SchedulerCallPhase.COMMITTED for item in page)
                after = page[-1].ordinal
                if len(page) < RUNNER_PAGE_SIZE:
                    break
        return count

    def seal(self) -> SchedulerSuiteSeal:
        """Persist one exact seal from complete evaluation and authenticated reads."""

        self._require_composition_binding()
        existing = self._read_bound_suite_seal()
        if existing is not None:
            return existing
        roots: list[str] = []
        charged_tokens = 0
        for entry in self._entries:
            root, consumed = evaluation_summary(run=entry.run, store=entry.store)
            roots.append(root)
            charged_tokens += consumed
        terminals = read_authenticated_extraction_terminals(
            suite=self._suite,
            runs=tuple(entry.run for entry in self._entries),
            authentication_secrets=tuple(entry.authentication_secret for entry in self._entries),
            reader=self._extraction_terminal_reader,
            read_policy_sha256=self._extraction_read_policy_sha256,
        )
        seal = SchedulerSuiteSeal(
            suite_authority_sha256=self._suite.commitment_sha256,
            runtime_provenance_sha256=self._suite.runtime_provenance_sha256,
            ordered_run_authority_sha256=tuple(
                entry.run.commitment_sha256 for entry in self._entries
            ),
            ordered_evaluation_receipt_root_sha256=tuple(roots),
            ordered_extraction_terminal_sha256=tuple(
                item.evidence.terminal.terminal_commitment_sha256 for item in terminals
            ),
            ordered_authenticated_extraction_terminal_sha256=tuple(
                item.commitment_sha256 for item in terminals
            ),
            renderer_policy_sha256=self._renderer_policy_sha256,
            private_answer_policy_sha256=self._private_answer_policy_sha256,
            receipt_verifier_policy_sha256=self._suite.bridge_boot.receipt_verifier_policy_sha256,
            outcome_readback_policy_sha256=self._outcome_readback_policy_sha256,
            extraction_terminal_read_policy_sha256=self._extraction_read_policy_sha256,
            seal_readback_policy_sha256=SUITE_SEAL_READBACK_POLICY_SHA256,
            case_count=PUBLISHABLE_SUITE_CASE_COUNT,
            evaluation_call_count=PUBLISHABLE_SUITE_EVALUATION_CALL_COUNT,
            extraction_operation_count=PUBLISHABLE_SUITE_EXTRACTION_OPERATION_COUNT,
            charged_tokens=charged_tokens,
        )
        seal = bind_suite_seal(seal, binding=self._suite_seal_binding)
        existing = self._read_bound_suite_seal()
        if existing is not None and existing != seal:
            _fail("scheduler_runner_suite_seal_divergent")
        if existing is not None:
            return existing
        for entry in self._entries:
            entry.store.seal_run(suite_seal_sha256=seal.commitment_sha256)
        return self._seal_store.persist_exact(seal)

    def _dispatch(
        self,
        entry_index: int,
        entry: _RunEntry,
        call: SchedulerLogicalCall,
        *,
        now: int,
    ) -> SchedulerStepResult:
        rendered = self._render_request(entry, call)
        payload = rendered.payload
        if self._boundary.preflight(payload=payload, token_ceiling=call.token_ceiling) is not None:
            _fail("scheduler_runner_dispatch_preflight_invalid")
        request_sha256 = bound_request_sha256(
            suite_authority_sha256=self._suite.commitment_sha256,
            run_authority_sha256=entry.run.commitment_sha256,
            bridge_boot_authority_sha256=self._suite.bridge_boot.commitment_sha256,
            renderer_policy_sha256=rendered.renderer_policy_sha256,
            private_answer_policy_sha256=rendered.private_answer_policy_sha256,
            dependency_answer_ciphertext_sha256=(rendered.dependency_answer_ciphertext_sha256),
            call=call,
            payload=payload,
        )
        lease_id = self._lease_id()
        deadline = entry.run.binding.limits.dispatch_deadline_unix_ms
        lease_expires = min(deadline, now + self._lease_duration_ms)
        leased = entry.store.acquire_lease(
            call.logical_call_id,
            now_unix_ms=now,
            lease_id=lease_id,
            lease_expires_unix_ms=lease_expires,
        )
        entry.store.bind_request(
            call.logical_call_id,
            lease_id=lease_id,
            request_sha256=request_sha256,
        )
        intent_now = self._now()
        if intent_now < now:
            _fail("scheduler_runner_clock_invalid")
        if intent_now >= lease_expires:
            entry.store.reclaim_expired_no_intent_lease(
                call.logical_call_id,
                now_unix_ms=intent_now,
                lease_id=lease_id,
            )
            if intent_now >= deadline:
                entry.store.exhaust_deadline(now_unix_ms=intent_now)
                return SchedulerStepResult(
                    SchedulerStepDisposition.DEADLINE_EXHAUSTED,
                    entry.run.binding.run_id,
                    None,
                    0,
                )
            return SchedulerStepResult(
                SchedulerStepDisposition.BLOCKED,
                entry.run.binding.run_id,
                call.logical_call_id,
                0,
            )
        intent_sha256 = dispatch_intent_sha256(
            envelope_binding={
                "attempt_count": leased.attempt_count,
                "bridge_boot_authority_sha256": (self._suite.bridge_boot.commitment_sha256),
                "dispatch_deadline_unix_ms": deadline,
                "dependency_answer_ciphertext_sha256": (
                    rendered.dependency_answer_ciphertext_sha256
                ),
                "lease_id": lease_id,
                "logical_call_id": call.logical_call_id,
                "private_answer_policy_sha256": rendered.private_answer_policy_sha256,
                "renderer_policy_sha256": rendered.renderer_policy_sha256,
                "request_sha256": request_sha256,
                "run_authority_sha256": entry.run.commitment_sha256,
                "suite_authority_sha256": self._suite.commitment_sha256,
                "token_ceiling": call.token_ceiling,
            }
        )
        entry.store.record_dispatch_intent(
            call.logical_call_id,
            lease_id=lease_id,
            now_unix_ms=intent_now,
            bridge_boot_authority_sha256=(self._suite.bridge_boot.commitment_sha256),
            intent_sha256=intent_sha256,
        )
        try:
            post_intent_now = self._now()
            predipatch_failure = post_intent_now < intent_now or post_intent_now >= lease_expires
            predisptach_code = "scheduler_runner_predispatch_deadline_exhausted"
        except SchedulerRunnerError as error:
            predipatch_failure = True
            predisptach_code = error.code
        if predipatch_failure:
            failed = entry.store.record_known_failure(
                call.logical_call_id,
                intent_sha256=intent_sha256,
                failure_sha256=commitment(
                    "runner-predispatch-known-failure",
                    {
                        "failure_code": predisptach_code,
                        "intent_sha256": intent_sha256,
                        "logical_call_id": call.logical_call_id,
                        "run_authority_sha256": entry.run.commitment_sha256,
                        "suite_authority_sha256": self._suite.commitment_sha256,
                    },
                ),
                charged_tokens=0,
            )
            if failed.phase is not SchedulerCallPhase.FAILED_KNOWN:
                _fail("scheduler_runner_predispatch_failure_invalid")
            return SchedulerStepResult(
                SchedulerStepDisposition.FAILED_KNOWN,
                entry.run.binding.run_id,
                call.logical_call_id,
                0,
            )
        envelope = SchedulerDispatchEnvelope(
            suite_authority_sha256=self._suite.commitment_sha256,
            run_authority_sha256=entry.run.commitment_sha256,
            bridge_boot_authority_sha256=self._suite.bridge_boot.commitment_sha256,
            logical_call_id=call.logical_call_id,
            stage=call.stage,
            ordinal=call.ordinal,
            renderer_policy_sha256=rendered.renderer_policy_sha256,
            private_answer_policy_sha256=rendered.private_answer_policy_sha256,
            dependency_answer_ciphertext_sha256=(rendered.dependency_answer_ciphertext_sha256),
            request_sha256=request_sha256,
            intent_sha256=intent_sha256,
            token_ceiling=call.token_ceiling,
            dispatch_deadline_unix_ms=deadline,
            payload=payload,
        )
        receipt_sha256: str | None = None
        try:
            outcome = self._boundary.invoke_once(envelope)
            self._require_outcome(outcome, envelope=envelope, call=call)
            receipt_sha256 = outcome.receipt.commitment_sha256
            committed = entry.store.commit_outcome(
                call.logical_call_id,
                intent_sha256=intent_sha256,
                receipt_sha256=receipt_sha256,
                completion_tokens=outcome.receipt.completion_tokens,
                charged_tokens=outcome.receipt.charged_tokens,
                answer_ciphertext=outcome.private_output_ciphertext,
            )
        except BaseException as primary:
            resolved = self._resolve_ambiguous_dispatch(
                entry,
                logical_call_id=call.logical_call_id,
                intent_sha256=intent_sha256,
                failure_code=_failure_code(primary),
            )
            if resolved.phase is SchedulerCallPhase.COMMITTED:
                self._after_ordinals[entry_index] = call.ordinal
                return SchedulerStepResult(
                    SchedulerStepDisposition.COMMITTED,
                    entry.run.binding.run_id,
                    call.logical_call_id,
                    0,
                    resolved.terminal_evidence_sha256,
                )
            if isinstance(primary, SchedulerRunnerError):
                raise primary from None
            if not isinstance(primary, Exception):
                raise
            _fail("scheduler_runner_dispatch_outcome_unknown")
        if committed.phase is not SchedulerCallPhase.COMMITTED:
            _fail("scheduler_runner_commit_invalid")
        self._after_ordinals[entry_index] = call.ordinal
        return SchedulerStepResult(
            SchedulerStepDisposition.COMMITTED,
            entry.run.binding.run_id,
            call.logical_call_id,
            outcome.provider_dispatches,
            receipt_sha256,
        )

    def _require_outcome(
        self,
        outcome: object,
        *,
        envelope: SchedulerDispatchEnvelope,
        call: SchedulerLogicalCall,
    ) -> None:
        if type(outcome) is not SchedulerDispatchOutcome:
            _fail("scheduler_runner_dispatch_outcome_invalid")
        receipt = outcome.receipt
        try:
            attestation_sha256 = hashlib.sha256(receipt.attestation).hexdigest()
            receipt_commitment_sha256 = commitment("runner-dispatch-receipt", receipt.material())
        except Exception:
            _fail("scheduler_runner_dispatch_receipt_invalid")
        if (
            type(receipt) is not SchedulerDispatchReceipt
            or type(outcome.provider_dispatches) is not int
            or outcome.provider_dispatches not in (0, 1)
            or type(receipt.attestation) is not bytes
            or not 1 <= len(receipt.attestation) <= RUNNER_ATTESTATION_BYTES_CAP
            or receipt.attestation_sha256 != attestation_sha256
            or receipt.commitment_sha256 != receipt_commitment_sha256
            or type(receipt.completion_tokens) is not int
            or not 0 <= receipt.completion_tokens <= call.token_ceiling
            or type(receipt.charged_tokens) is not int
            or receipt.charged_tokens < receipt.completion_tokens
            or receipt.suite_authority_sha256 != envelope.suite_authority_sha256
            or receipt.run_authority_sha256 != envelope.run_authority_sha256
            or receipt.bridge_boot_authority_sha256 != envelope.bridge_boot_authority_sha256
            or receipt.logical_call_id != envelope.logical_call_id
            or receipt.stage is not envelope.stage
            or receipt.renderer_policy_sha256 != envelope.renderer_policy_sha256
            or receipt.private_answer_policy_sha256 != envelope.private_answer_policy_sha256
            or receipt.dependency_answer_ciphertext_sha256
            != envelope.dependency_answer_ciphertext_sha256
            or receipt.request_sha256 != envelope.request_sha256
            or receipt.intent_sha256 != envelope.intent_sha256
        ):
            _fail("scheduler_runner_receipt_binding_invalid")
        ciphertext = outcome.private_output_ciphertext
        if call.stage is SchedulerCallStage.ANSWER:
            try:
                ciphertext_sha256, _ = ciphertext_material(ciphertext)
            except SchedulerSQLiteError:
                _fail("scheduler_runner_private_output_invalid")
            if (
                ciphertext is None
                or len(ciphertext) > ANSWER_CIPHERTEXT_BYTES_CAP
                or receipt.private_output_ciphertext_sha256 != ciphertext_sha256
            ):
                _fail("scheduler_runner_private_output_invalid")
        elif ciphertext is not None or receipt.private_output_ciphertext_sha256 is not None:
            _fail("scheduler_runner_private_output_invalid")
        try:
            verified = self._receipt_verifier.verify(receipt=receipt, envelope=envelope)
        except Exception:
            _fail("scheduler_runner_receipt_verification_failed")
        if verified is not True:
            _fail("scheduler_runner_receipt_verification_failed")

    def _resolve_ambiguous_dispatch(
        self,
        entry: _RunEntry,
        *,
        logical_call_id: str,
        intent_sha256: str,
        failure_code: str,
    ) -> SchedulerCallState:
        try:
            current = entry.store.read_call(logical_call_id)
            if current.phase in (
                SchedulerCallPhase.COMMITTED,
                SchedulerCallPhase.OUTCOME_UNKNOWN,
            ):
                return current
            if (
                current.phase is not SchedulerCallPhase.DISPATCH_INTENT
                or current.intent_sha256 != intent_sha256
            ):
                _fail("scheduler_runner_dispatch_recovery_invalid")
            ambiguity_sha256 = commitment(
                "runner-ambiguous-outcome",
                {
                    "failure_code": failure_code,
                    "intent_sha256": intent_sha256,
                    "logical_call_id": logical_call_id,
                    "run_authority_sha256": entry.run.commitment_sha256,
                    "suite_authority_sha256": self._suite.commitment_sha256,
                },
            )
            return entry.store.record_ambiguous_outcome(
                logical_call_id,
                intent_sha256=intent_sha256,
                ambiguity_sha256=ambiguity_sha256,
            )
        except SchedulerRunnerError:
            raise
        except BaseException:
            try:
                current = entry.store.read_call(logical_call_id)
            except BaseException:
                _fail("scheduler_runner_dispatch_recovery_required")
            if current.phase in (
                SchedulerCallPhase.COMMITTED,
                SchedulerCallPhase.OUTCOME_UNKNOWN,
            ):
                return current
            _fail("scheduler_runner_dispatch_recovery_required")

    def _render_request(
        self,
        entry: _RunEntry,
        call: SchedulerLogicalCall,
    ) -> SchedulerRenderedRequest:
        capability = None
        expected_dependency_sha256 = None
        if call.stage is SchedulerCallStage.JUDGE:
            if call.depends_on_logical_call_id is None:
                _fail("scheduler_runner_judge_dependency_invalid")
            dependency_ciphertext = entry.store.read_private_answer_ciphertext(
                call.depends_on_logical_call_id
            )
            expected_dependency_sha256 = hashlib.sha256(dependency_ciphertext).hexdigest()
            capability = SchedulerPrivateAnswerReadCapability(dependency_ciphertext)
        context = SchedulerRequestContext(
            suite=self._suite,
            run=entry.run,
            call=call,
            dependency_answer_capability=capability,
        )
        try:
            rendered = self._request_renderer.render(context)
        except SchedulerRunnerError:
            raise
        except Exception:
            _fail("scheduler_runner_request_render_failed")
        if type(rendered) is not SchedulerRenderedRequest:
            _fail("scheduler_runner_request_material_invalid")
        SchedulerRenderedRequest.__post_init__(rendered)
        if (
            rendered.renderer_policy_sha256 != self._renderer_policy_sha256
            or rendered.private_answer_policy_sha256 != self._private_answer_policy_sha256
            or rendered.dependency_answer_ciphertext_sha256 != expected_dependency_sha256
            or capability is not None
            and not capability.was_read
        ):
            _fail("scheduler_runner_request_policy_binding_invalid")
        return rendered

    def _next_planned(
        self,
        entry_index: int,
        entry: _RunEntry,
    ) -> tuple[SchedulerLogicalCall | None, bool]:
        after = self._after_ordinals[entry_index]
        while True:
            page = entry.store.read_calls(after_ordinal=after, limit=RUNNER_PAGE_SIZE)
            if not page:
                self._after_ordinals[entry_index] = after
                return None, False
            for state in page:
                if state.phase is SchedulerCallPhase.COMMITTED:
                    after = state.ordinal
                    continue
                if state.phase is SchedulerCallPhase.PLANNED:
                    call = _manifest_call(entry.manifest, state.ordinal)
                    if call.logical_call_id != state.logical_call_id:
                        _fail("scheduler_runner_manifest_state_drift")
                    if call.stage is SchedulerCallStage.JUDGE:
                        dependency = entry.store.read_call(call.depends_on_logical_call_id or "")
                        if dependency.phase is not SchedulerCallPhase.COMMITTED:
                            self._after_ordinals[entry_index] = state.ordinal - 1
                            return None, True
                    self._after_ordinals[entry_index] = state.ordinal - 1
                    return call, False
                if state.phase in (
                    SchedulerCallPhase.LEASED,
                    SchedulerCallPhase.REQUEST_BOUND,
                    SchedulerCallPhase.DISPATCH_INTENT,
                ):
                    self._after_ordinals[entry_index] = state.ordinal - 1
                    return None, True
                _fail("scheduler_runner_terminal_call_in_active_run")
            self._after_ordinals[entry_index] = after
            if len(page) < RUNNER_PAGE_SIZE:
                return None, False

    def _recover_all_inflight(self) -> None:
        now = self._now()
        for entry in self._entries:
            self._recover_inflight(entry, now=now)

    def _recover_inflight(self, entry: _RunEntry, *, now: int) -> None:
        run = entry.store.read_run()
        logical_call_id = run.inflight_logical_call_id
        if run.phase is not SchedulerRunPhase.ACTIVE or logical_call_id is None:
            return
        call = entry.store.read_call(logical_call_id)
        if call.phase is SchedulerCallPhase.DISPATCH_INTENT:
            if call.intent_sha256 is None or call.lease_expires_unix_ms is None:
                _fail("scheduler_runner_recovery_state_invalid")
            if now < call.lease_expires_unix_ms:
                return
            reconcile_expired_intent(
                suite=self._suite,
                run=entry.run,
                manifest=entry.manifest,
                store=entry.store,
                call=call,
                now_unix_ms=now,
                reconciliation=self._reconciliation,
                readback_policy_sha256=self._outcome_readback_policy_sha256,
                render_request=lambda manifest_call: self._render_request(
                    entry,
                    manifest_call,
                ),
                require_outcome=self._require_outcome,
            )
            return
        if call.phase not in (
            SchedulerCallPhase.LEASED,
            SchedulerCallPhase.REQUEST_BOUND,
        ):
            _fail("scheduler_runner_recovery_state_invalid")
        expires = call.lease_expires_unix_ms
        if expires is None:
            _fail("scheduler_runner_recovery_state_invalid")
        if now >= expires:
            entry.store.reclaim_expired_no_intent_lease(
                logical_call_id,
                now_unix_ms=now,
                lease_id=call.lease_id or "",
            )

    def _terminal_step(self) -> SchedulerStepResult | None:
        phases = tuple(entry.store.read_run().phase for entry in self._entries)
        for entry, phase in zip(self._entries, phases, strict=True):
            disposition = {
                SchedulerRunPhase.FROZEN_OUTCOME_UNKNOWN: (
                    SchedulerStepDisposition.FROZEN_OUTCOME_UNKNOWN
                ),
                SchedulerRunPhase.FAILED_KNOWN: SchedulerStepDisposition.FAILED_KNOWN,
                SchedulerRunPhase.DEADLINE_EXHAUSTED: (SchedulerStepDisposition.DEADLINE_EXHAUSTED),
            }.get(phase)
            if disposition is not None:
                return SchedulerStepResult(
                    disposition,
                    entry.run.binding.run_id,
                    None,
                    0,
                )
        if all(phase is SchedulerRunPhase.SEALED for phase in phases):
            if self._read_bound_suite_seal() is None:
                return SchedulerStepResult(
                    SchedulerStepDisposition.EVALUATION_COMPLETE,
                    None,
                    None,
                    0,
                )
            return SchedulerStepResult(SchedulerStepDisposition.SEALED, None, None, 0)
        return None

    def _read_bound_suite_seal(self) -> SchedulerSuiteSeal | None:
        seal = read_bound_suite_seal(
            suite=self._suite,
            runs=tuple(entry.run for entry in self._entries),
            stores=tuple(entry.store for entry in self._entries),
            seal_store=self._seal_store,
        )
        if seal is not None:
            validate_suite_seal_binding(seal, binding=self._suite_seal_binding)
        return seal

    def _require_composition_binding(self) -> None:
        try:
            bridge = self._boundary.bridge_boot_authority_sha256
            policy = self._receipt_verifier.policy_sha256
            renderer_policy = self._request_renderer.renderer_policy_sha256
            private_answer_policy = self._request_renderer.private_answer_policy_sha256
            readback_policy = (
                NO_OUTCOME_READBACK_POLICY_SHA256
                if self._reconciliation is None
                else self._reconciliation.readback_policy_sha256
            )
            extraction_policy = (
                NO_EXTRACTION_TERMINAL_READ_POLICY_SHA256
                if self._extraction_terminal_reader is None
                else self._extraction_terminal_reader.read_policy_sha256
            )
            seal_binding_policy = (
                None if self._suite_seal_binding is None else self._suite_seal_binding.policy_sha256
            )
        except Exception:
            _fail("scheduler_runner_composition_binding_invalid")
        if (
            self._suite.commitment_sha256 != self._suite_authority_sha256
            or commitment("suite", self._suite.material()) != self._suite_authority_sha256
            or commitment("bridge-boot", self._suite.bridge_boot.material())
            != self._suite.bridge_boot.commitment_sha256
            or bridge != self._suite.bridge_boot.commitment_sha256
            or policy != self._suite.bridge_boot.receipt_verifier_policy_sha256
            or renderer_policy != self._renderer_policy_sha256
            or private_answer_policy != self._private_answer_policy_sha256
            or readback_policy != self._outcome_readback_policy_sha256
            or extraction_policy != self._extraction_read_policy_sha256
            or seal_binding_policy != self._suite_seal_binding_policy_sha256
            or not is_sha256(bridge)
            or not is_sha256(policy)
            or not is_sha256(renderer_policy)
            or not is_sha256(private_answer_policy)
            or not is_sha256(readback_policy)
            or not is_sha256(extraction_policy)
        ):
            _fail("scheduler_runner_composition_binding_invalid")

    def _now(self) -> int:
        try:
            value = self._clock()
        except Exception:
            _fail("scheduler_runner_clock_invalid")
        if type(value) is not int or value < 0:
            _fail("scheduler_runner_clock_invalid")
        return value

    def _lease_id(self) -> str:
        try:
            value = self._lease_id_factory()
        except Exception:
            _fail("scheduler_runner_lease_id_invalid")
        if (
            type(value) is not str
            or not 1 <= len(value) <= 200
            or not value.isascii()
            or not value.isprintable()
        ):
            _fail("scheduler_runner_lease_id_invalid")
        return value


def _manifest_call(manifest: BuiltSchedulerManifest, ordinal: int) -> SchedulerLogicalCall:
    try:
        shard = manifest.shards[ordinal // 256]
        call = shard.calls[ordinal - shard.start_ordinal]
    except (IndexError, TypeError):
        _fail("scheduler_runner_manifest_call_missing")
    return call


def _failure_code(error: BaseException) -> str:
    if isinstance(error, SchedulerRunnerError):
        return error.code
    return "scheduler_runner_dispatch_boundary_failed"


def _port_digest(port: object, name: str) -> str:
    try:
        value = getattr(port, name)
    except Exception:
        _fail("scheduler_runner_composition_binding_invalid")
    if not is_sha256(value):
        _fail("scheduler_runner_composition_binding_invalid")
    return value


def _fail(code: str) -> None:
    raise SchedulerRunnerError(code)


__all__ = ("PublishableResumableEvaluationRunner",)

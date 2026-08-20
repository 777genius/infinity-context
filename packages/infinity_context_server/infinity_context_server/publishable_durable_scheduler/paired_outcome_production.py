"""Production adapter deriving paired outcomes from committed scheduler evidence."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from typing import final

from infinity_context_runtime_bridge import (
    SubscriptionRuntimeBridgeAdapter,
    TerminalBridgeCall,
)

from infinity_context_server.memory_comparison_full_methodology import longmemeval_type
from infinity_context_server.memory_comparison_paired_superiority_policy import (
    PAIRED_SUPERIORITY_POLICY_SHA256,
)
from infinity_context_server.memory_comparison_publishable_methodology import (
    PUBLISHABLE_PRIORITY_METHODOLOGY_V4_COMMITMENT_SHA256,
)
from infinity_context_server.memory_comparison_publishable_profile import (
    PUBLISHABLE_PRIORITY_PROFILE_V4_COMMITMENT_SHA256,
    PUBLISHABLE_PRIORITY_PROFILE_V4_ID,
)
from infinity_context_server.publishable_durable_scheduler.contracts import (
    SCHEDULER_ORDERED_BACKEND_ROLES,
    SCHEDULER_SHARD_CALL_LIMIT,
    SchedulerBenchmark,
    SchedulerCallStage,
    SchedulerSuiteAuthority,
    canonical_json,
    commitment,
)
from infinity_context_server.publishable_durable_scheduler.manifest import (
    SchedulerLogicalCall,
)
from infinity_context_server.publishable_durable_scheduler.paired_outcome_authentication import (
    AuthenticatedJudgeOutput,
    PairedOutcomeContractError,
    authenticate_judge_output,
)
from infinity_context_server.publishable_durable_scheduler.paired_outcome_authority import (
    PAIRED_AUTHORITY_MAPPING_SHA256,
    PAIRED_JUDGE_NORMALIZATION_POLICY_SHA256,
)
from infinity_context_server.publishable_durable_scheduler.paired_outcome_contracts import (
    EXPECTED_PAIRED_OUTCOME_COUNT,
    PairedOutcomeDatasetBinding,
    bind_paired_outcome_terminal_to_suite_seal,
    build_paired_outcome_terminal,
)
from infinity_context_server.publishable_durable_scheduler.runner_contracts import (
    RUNNER_PAGE_SIZE,
    RUNNER_SCHEMA_VERSION,
    SchedulerDispatchReceipt,
    SchedulerRunnerError,
    SchedulerRunStoreSpec,
    SchedulerSuiteSeal,
    is_sha256,
)
from infinity_context_server.publishable_durable_scheduler.runner_request_composition import (
    SchedulerAuthenticatedOfficialCase,
    SchedulerOfficialCaseKey,
    SchedulerOfficialCaseReaderPort,
)
from infinity_context_server.publishable_durable_scheduler.runner_suite_binding import (
    require_exact_suite,
)
from infinity_context_server.publishable_durable_scheduler.sqlite_store import (
    SQLiteDurableSchedulerStore,
)
from infinity_context_server.publishable_durable_scheduler.state_models import (
    SchedulerCallPhase,
    SchedulerCallState,
)

from .scheduler_subscription_bridge_adapter import (
    SCHEDULER_SUBSCRIPTION_BRIDGE_ADAPTER_SCHEMA_VERSION,
    SCHEDULER_SUBSCRIPTION_BRIDGE_RECEIPT_POLICY_SHA256,
)

PUBLISHABLE_PAIRED_JUDGE_OUTPUT_READ_POLICY_SHA256 = commitment(
    "publishable-paired-judge-output-read-policy",
    {
        "authenticated_source": "subscription-bridge-terminal-logical-call-readback",
        "case_reads_per_pair": 1,
        "judge_ciphertext_persisted_to_scheduler": False,
        "ordered_backend_roles": list(SCHEDULER_ORDERED_BACKEND_ROLES),
        "page_size": RUNNER_PAGE_SIZE,
        "plaintext_retention": "one-pair-in-memory-only",
        "scheduler_receipt_policy_sha256": (SCHEDULER_SUBSCRIPTION_BRIDGE_RECEIPT_POLICY_SHA256),
        "schema_version": "memory-comparison-publishable-paired-judge-read.v1",
    },
)
PUBLISHABLE_PAIRED_OUTCOME_SEALING_POLICY_SHA256 = commitment(
    "publishable-paired-outcome-sealing-policy",
    {
        "authority_mapping_sha256": PAIRED_AUTHORITY_MAPPING_SHA256,
        "judge_normalization_policy_sha256": PAIRED_JUDGE_NORMALIZATION_POLICY_SHA256,
        "judge_output_read_policy_sha256": (PUBLISHABLE_PAIRED_JUDGE_OUTPUT_READ_POLICY_SHA256),
        "pair_count": EXPECTED_PAIRED_OUTCOME_COUNT,
        "paired_superiority_policy_sha256": PAIRED_SUPERIORITY_POLICY_SHA256,
        "schema_version": "memory-comparison-publishable-paired-outcome-sealing.v1",
    },
)

_LOCOMO_CATEGORIES = {
    1: "multi-hop",
    2: "temporal",
    3: "open-domain",
    4: "single-hop",
}
_LONGMEMEVAL_CATEGORIES = frozenset(
    (
        "knowledge-update",
        "multi-session",
        "single-session-assistant",
        "single-session-preference",
        "single-session-user",
        "temporal",
    )
)


@final
class PublishablePairedOutcomeSealBinder:
    """Build the exact authenticated 2,040-pair terminal during suite sealing."""

    __slots__ = (
        "_bridge",
        "_case_authority_root_sha256",
        "_case_reader",
        "_run_stores",
        "_suite",
        "_suite_authority_sha256",
        "_terminal_authentication_secret",
    )

    policy_sha256 = PUBLISHABLE_PAIRED_OUTCOME_SEALING_POLICY_SHA256

    def __init__(
        self,
        *,
        suite: SchedulerSuiteAuthority,
        run_stores: tuple[SchedulerRunStoreSpec, SchedulerRunStoreSpec],
        case_reader: SchedulerOfficialCaseReaderPort,
        bridge: SubscriptionRuntimeBridgeAdapter,
        terminal_authentication_secret: bytes,
    ) -> None:
        if (
            type(suite) is not SchedulerSuiteAuthority
            or type(run_stores) is not tuple
            or len(run_stores) != 2
            or any(type(item) is not SchedulerRunStoreSpec for item in run_stores)
            or not callable(getattr(case_reader, "read_exact", None))
            or type(bridge) is not SubscriptionRuntimeBridgeAdapter
            or type(terminal_authentication_secret) is not bytes
            or not 32 <= len(terminal_authentication_secret) <= 1024
        ):
            _fail("paired_outcome_production_composition_invalid")
        try:
            case_root = case_reader.authority_root_sha256
        except Exception:
            _fail("paired_outcome_production_composition_invalid")
        if not is_sha256(case_root):
            _fail("paired_outcome_production_composition_invalid")
        require_exact_suite(suite, run_stores)
        self._suite = suite
        self._suite_authority_sha256 = suite.commitment_sha256
        self._run_stores = run_stores
        self._case_reader = case_reader
        self._case_authority_root_sha256 = case_root
        self._bridge = bridge
        self._terminal_authentication_secret = terminal_authentication_secret

    def bind(self, seal: SchedulerSuiteSeal) -> SchedulerSuiteSeal:
        """Stream real normalized judge results into the computed policy terminal."""

        self._require_base_seal(seal)
        if seal.paired_outcome is not None:
            _fail("paired_outcome_production_base_seal_invalid")
        bindings = tuple(
            PairedOutcomeDatasetBinding(
                benchmark=spec.run.binding.profile.benchmark.value,
                run_authority_sha256=spec.run.commitment_sha256,
                binding_commitment_sha256=spec.run.binding.binding_commitment_sha256,
                case_manifest_sha256=spec.run.binding.case_manifest_sha256,
                terminal_report_sha256=seal.ordered_extraction_terminal_sha256[index],
                terminal_receipt_sha256=(
                    seal.ordered_authenticated_extraction_terminal_sha256[index]
                ),
            )
            for index, spec in enumerate(self._run_stores)
        )
        try:
            terminal = build_paired_outcome_terminal(
                dataset_bindings=bindings,
                authenticated_judge_outputs=self._authenticated_judge_outputs(seal),
                judge_output_authentication_secrets=tuple(
                    spec.authentication_secret for spec in self._run_stores
                ),
                terminal_authentication_secret=self._terminal_authentication_secret,
            )
            return bind_paired_outcome_terminal_to_suite_seal(
                seal,
                terminal=terminal,
                terminal_authentication_secret=self._terminal_authentication_secret,
            )
        except PairedOutcomeContractError as error:
            _fail(error.code)

    def validate(self, seal: SchedulerSuiteSeal) -> None:
        """Validate the durable public binding without replaying private results."""

        self._require_base_seal(seal)
        binding = seal.paired_outcome
        if (
            binding is None
            or binding.pair_count != EXPECTED_PAIRED_OUTCOME_COUNT
            or binding.judge_normalization_policy_sha256 != PAIRED_JUDGE_NORMALIZATION_POLICY_SHA256
            or binding.authority_mapping_sha256 != PAIRED_AUTHORITY_MAPPING_SHA256
            or binding.paired_superiority_policy_sha256 != PAIRED_SUPERIORITY_POLICY_SHA256
        ):
            _fail("paired_outcome_production_seal_invalid")

    def _authenticated_judge_outputs(
        self,
        seal: SchedulerSuiteSeal,
    ) -> Iterator[AuthenticatedJudgeOutput]:
        observed_pairs = 0
        for spec in self._run_stores:
            store = SQLiteDurableSchedulerStore(
                spec.database_path,
                private_directory=spec.private_directory,
                authentication_secret=spec.authentication_secret,
                suite=self._suite,
                run=spec.run,
                manifest=spec.manifest,
            )
            after = -1
            ordinal = 0
            current_case: SchedulerAuthenticatedOfficialCase | None = None
            while True:
                page = store.read_calls(after_ordinal=after, limit=RUNNER_PAGE_SIZE)
                for state in page:
                    call = _manifest_call(spec, ordinal)
                    self._require_committed_state(spec, state, call, ordinal=ordinal)
                    ordinal += 1
                    if call.stage is SchedulerCallStage.ANSWER:
                        continue
                    if call.backend_index == 0:
                        current_case = self._read_case(spec, call)
                    elif (
                        current_case is None
                        or current_case.key.case_index != call.case_index
                        or current_case.key.case_id != call.case_id
                        or current_case.key.case_alias != call.case_alias
                    ):
                        _fail("paired_outcome_production_case_crosswire")
                    category = _case_category(spec, current_case)
                    yield self._judge_output(
                        spec=spec,
                        store=store,
                        state=state,
                        call=call,
                        category=category,
                        seal=seal,
                    )
                    if call.backend_index == 1:
                        observed_pairs += 1
                        current_case = None
                if len(page) < RUNNER_PAGE_SIZE:
                    break
                after = page[-1].ordinal
            if ordinal != spec.run.binding.profile.call_count or current_case is not None:
                _fail("paired_outcome_production_coverage_invalid")
        if observed_pairs != EXPECTED_PAIRED_OUTCOME_COUNT:
            _fail("paired_outcome_production_coverage_invalid")

    def _judge_output(
        self,
        *,
        spec: SchedulerRunStoreSpec,
        store: SQLiteDurableSchedulerStore,
        state: SchedulerCallState,
        call: SchedulerLogicalCall,
        category: str,
        seal: SchedulerSuiteSeal,
    ) -> AuthenticatedJudgeOutput:
        try:
            terminal = self._bridge.lookup_logical_call(call.logical_call_id)
        except Exception:
            _fail("paired_outcome_production_judge_read_failed")
        if type(terminal) is not TerminalBridgeCall or terminal.transport_dispatched is not False:
            _fail("paired_outcome_production_judge_missing")
        intent = terminal.readback.intent
        try:
            dependency = store.read_private_answer_ciphertext(call.depends_on_logical_call_id or "")
        except Exception:
            _fail("paired_outcome_production_answer_dependency_invalid")
        expected_operation = f"scheduler-judge:{hashlib.sha256(dependency).hexdigest()}"
        if (
            intent.binding.logical_call_id != call.logical_call_id
            or intent.binding.intent_id != state.intent_sha256
            or intent.binding.logical_operation != expected_operation
        ):
            _fail("paired_outcome_production_judge_crosswire")
        receipt = _reconstructed_judge_receipt(
            suite=self._suite,
            spec=spec,
            state=state,
            call=call,
            terminal=terminal,
            renderer_policy_sha256=seal.renderer_policy_sha256,
            private_answer_policy_sha256=seal.private_answer_policy_sha256,
            dependency_answer_ciphertext_sha256=hashlib.sha256(dependency).hexdigest(),
        )
        if receipt.commitment_sha256 != state.terminal_evidence_sha256:
            _fail("paired_outcome_production_judge_receipt_crosswire")
        try:
            raw_output = terminal.private_output.render_for_judge().encode("utf-8")
        except Exception:
            _fail("paired_outcome_production_judge_read_failed")
        if hashlib.sha256(raw_output).hexdigest() != terminal.readback.result.output_text_sha256:
            _fail("paired_outcome_production_judge_plaintext_crosswire")
        try:
            return authenticate_judge_output(
                suite_authority_sha256=self._suite.commitment_sha256,
                run_authority_sha256=spec.run.commitment_sha256,
                binding_commitment_sha256=spec.run.binding.binding_commitment_sha256,
                case_manifest_sha256=spec.run.binding.case_manifest_sha256,
                benchmark=spec.run.binding.profile.benchmark.value,
                category=category,
                case_index=call.case_index,
                case_id=call.case_id,
                case_alias=call.case_alias,
                backend_role=call.backend_role,
                logical_call_id=call.logical_call_id,
                receipt_sha256=receipt.commitment_sha256,
                read_policy_sha256=PUBLISHABLE_PAIRED_JUDGE_OUTPUT_READ_POLICY_SHA256,
                raw_output=raw_output,
                authentication_secret=spec.authentication_secret,
            )
        except PairedOutcomeContractError:
            raise
        except Exception:
            _fail("paired_outcome_production_judge_read_failed")

    def _read_case(
        self,
        spec: SchedulerRunStoreSpec,
        call: SchedulerLogicalCall,
    ) -> SchedulerAuthenticatedOfficialCase:
        key = SchedulerOfficialCaseKey(
            suite_authority_sha256=self._suite.commitment_sha256,
            run_authority_sha256=spec.run.commitment_sha256,
            run_binding_commitment_sha256=spec.run.binding.binding_commitment_sha256,
            run_id=spec.run.binding.run_id,
            benchmark=spec.run.binding.profile.benchmark,
            scheduler_profile_id=spec.run.binding.profile.profile_id,
            publishable_profile_id=PUBLISHABLE_PRIORITY_PROFILE_V4_ID,
            publishable_profile_sha256=PUBLISHABLE_PRIORITY_PROFILE_V4_COMMITMENT_SHA256,
            methodology_sha256=PUBLISHABLE_PRIORITY_METHODOLOGY_V4_COMMITMENT_SHA256,
            dataset_sha256=spec.run.binding.dataset_sha256,
            case_manifest_sha256=spec.run.binding.case_manifest_sha256,
            case_index=call.case_index,
            case_id=call.case_id,
            case_alias=call.case_alias,
            authority_root_sha256=self._case_authority_root_sha256,
        )
        try:
            result = self._case_reader.read_exact(key=key)
        except Exception:
            _fail("paired_outcome_production_case_read_failed")
        if type(result) is not SchedulerAuthenticatedOfficialCase or result.key != key:
            _fail("paired_outcome_production_case_crosswire")
        try:
            result.__post_init__()
        except Exception:
            _fail("paired_outcome_production_case_unauthenticated")
        if result.case.benchmark != key.benchmark.value or result.case.case_id != key.case_id:
            _fail("paired_outcome_production_case_crosswire")
        return result

    def _require_base_seal(self, seal: object) -> None:
        if type(seal) is not SchedulerSuiteSeal:
            _fail("paired_outcome_production_base_seal_invalid")
        try:
            SchedulerSuiteSeal.__post_init__(seal)
        except Exception:
            _fail("paired_outcome_production_base_seal_invalid")
        try:
            current_case_root = self._case_reader.authority_root_sha256
        except Exception:
            _fail("paired_outcome_production_case_authority_drift")
        if current_case_root != self._case_authority_root_sha256:
            _fail("paired_outcome_production_case_authority_drift")
        if (
            self._suite.commitment_sha256 != self._suite_authority_sha256
            or commitment("suite", self._suite.material()) != self._suite_authority_sha256
            or seal.suite_authority_sha256 != self._suite_authority_sha256
            or seal.runtime_provenance_sha256 != self._suite.runtime_provenance_sha256
            or seal.ordered_run_authority_sha256
            != tuple(spec.run.commitment_sha256 for spec in self._run_stores)
        ):
            _fail("paired_outcome_production_base_seal_invalid")

    @staticmethod
    def _require_committed_state(
        spec: SchedulerRunStoreSpec,
        state: object,
        call: SchedulerLogicalCall,
        *,
        ordinal: int,
    ) -> None:
        if (
            type(state) is not SchedulerCallState
            or state.phase is not SchedulerCallPhase.COMMITTED
            or state.ordinal != ordinal
            or state.logical_call_id != call.logical_call_id
            or state.run_authority_sha256 != spec.run.commitment_sha256
            or state.stage is not call.stage
            or state.depends_on_logical_call_id != call.depends_on_logical_call_id
        ):
            _fail("paired_outcome_production_evaluation_incomplete")


def _manifest_call(spec: SchedulerRunStoreSpec, ordinal: int) -> SchedulerLogicalCall:
    try:
        shard = spec.manifest.shards[ordinal // SCHEDULER_SHARD_CALL_LIMIT]
        call = shard.calls[ordinal - shard.start_ordinal]
    except (IndexError, TypeError):
        _fail("paired_outcome_production_manifest_call_missing")
    return call


def _reconstructed_judge_receipt(
    *,
    suite: SchedulerSuiteAuthority,
    spec: SchedulerRunStoreSpec,
    state: SchedulerCallState,
    call: SchedulerLogicalCall,
    terminal: TerminalBridgeCall,
    renderer_policy_sha256: str,
    private_answer_policy_sha256: str,
    dependency_answer_ciphertext_sha256: str,
) -> SchedulerDispatchReceipt:
    """Rebuild the adapter-owned receipt and bind plaintext to durable evidence."""

    intent = terminal.readback.intent
    result = terminal.readback.result
    result.__post_init__()
    ciphertext_sha256 = hashlib.sha256(result.encrypted_output).hexdigest()
    envelope = {
        "bridge_boot_authority_sha256": suite.bridge_boot.commitment_sha256,
        "dependency_answer_ciphertext_sha256": dependency_answer_ciphertext_sha256,
        "dispatch_deadline_unix_ms": spec.run.binding.limits.dispatch_deadline_unix_ms,
        "intent_sha256": state.intent_sha256,
        "logical_call_id": call.logical_call_id,
        "ordinal": call.ordinal,
        "payload_sha256": intent.request_body_sha256,
        "private_answer_policy_sha256": private_answer_policy_sha256,
        "renderer_policy_sha256": renderer_policy_sha256,
        "request_sha256": state.request_sha256,
        "run_authority_sha256": spec.run.commitment_sha256,
        "runner_schema_version": RUNNER_SCHEMA_VERSION,
        "stage": call.stage.value,
        "suite_authority_sha256": suite.commitment_sha256,
        "token_ceiling": call.token_ceiling,
    }
    attestation = canonical_json(
        {
            "bridge_intent": intent.public_payload(),
            "bridge_result": {
                **result.public_payload(include_ciphertext=False),
                "encrypted_output_sha256": ciphertext_sha256,
            },
            "envelope": envelope,
            "schema_version": SCHEDULER_SUBSCRIPTION_BRIDGE_ADAPTER_SCHEMA_VERSION,
            "translation": {
                "charged_tokens": "usage.total_tokens",
                "completion_tokens": "usage.completion_tokens",
                "judge_ciphertext": "committed-in-attestation-only",
                "request_bytes": "verbatim",
            },
        }
    )
    return SchedulerDispatchReceipt(
        suite_authority_sha256=suite.commitment_sha256,
        run_authority_sha256=spec.run.commitment_sha256,
        bridge_boot_authority_sha256=suite.bridge_boot.commitment_sha256,
        logical_call_id=call.logical_call_id,
        stage=call.stage,
        renderer_policy_sha256=renderer_policy_sha256,
        private_answer_policy_sha256=private_answer_policy_sha256,
        dependency_answer_ciphertext_sha256=dependency_answer_ciphertext_sha256,
        request_sha256=state.request_sha256 or "",
        intent_sha256=state.intent_sha256 or "",
        private_output_ciphertext_sha256=None,
        completion_tokens=result.usage.completion_tokens,
        charged_tokens=result.usage.total_tokens,
        attestation=attestation,
    )


def _case_category(
    spec: SchedulerRunStoreSpec,
    value: SchedulerAuthenticatedOfficialCase,
) -> str:
    metadata = value.case.metadata
    if spec.run.binding.profile.benchmark is SchedulerBenchmark.LOCOMO:
        raw = metadata.get("category")
        category = _LOCOMO_CATEGORIES.get(raw) if type(raw) is int else None
    else:
        category = longmemeval_type(metadata.get("question_type"))
        if category not in _LONGMEMEVAL_CATEGORIES:
            category = None
    if category is None:
        _fail("paired_outcome_production_category_invalid")
    return category


def _fail(code: str) -> None:
    raise SchedulerRunnerError(code) from None


__all__ = (
    "PUBLISHABLE_PAIRED_JUDGE_OUTPUT_READ_POLICY_SHA256",
    "PUBLISHABLE_PAIRED_OUTCOME_SEALING_POLICY_SHA256",
    "PublishablePairedOutcomeSealBinder",
)

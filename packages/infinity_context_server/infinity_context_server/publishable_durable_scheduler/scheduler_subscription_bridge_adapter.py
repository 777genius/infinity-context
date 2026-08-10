"""Exact scheduler ports over the attested subscription-runtime bridge."""

from __future__ import annotations

import hashlib
import hmac
from typing import final

from infinity_context_server.features.subscription_runtime_bridge import (
    BridgeAuthority,
    BridgeCallBinding,
    BridgeIntent,
    BridgePoolAuthority,
    BridgeSecretCapability,
    NotFound,
    OutcomeUnknown,
    SubscriptionRuntimeBridgeAdapter,
    TerminalBridgeCall,
)
from infinity_context_server.features.subscription_runtime_bridge.process_contracts import (
    BridgeFleetReadinessReceipt,
)
from infinity_context_server.features.subscription_runtime_bridge.request_contract import (
    derive_bridge_intent,
)
from infinity_context_server.memory_comparison_publishable_methodology import (
    SUBSCRIPTION_RUNTIME_BASE_INSTRUCTIONS_SHA256,
)
from infinity_context_server.publishable_durable_scheduler.contracts import (
    SchedulerBridgeBootAuthority,
    SchedulerCallStage,
    SchedulerSuiteAuthority,
    canonical_json,
    commitment,
    run_authority_from_suite,
)
from infinity_context_server.publishable_durable_scheduler.runner_contracts import (
    RUNNER_SCHEMA_VERSION,
    SchedulerDispatchEnvelope,
    SchedulerDispatchOutcome,
    SchedulerDispatchReadback,
    SchedulerDispatchReadbackDisposition,
    SchedulerDispatchReceipt,
    SchedulerRunnerError,
    is_sha256,
)

SCHEDULER_SUBSCRIPTION_BRIDGE_ADAPTER_SCHEMA_VERSION = (
    "memory-comparison-scheduler-subscription-bridge.v2"
)
SCHEDULER_SUBSCRIPTION_BRIDGE_IMPLEMENTATION_SHA256 = commitment(
    "subscription-runtime-scheduler-bridge-implementation",
    {
        "binding": "scheduler-intent-logical-call-stage-and-answer-ciphertext",
        "canonical_request_bytes": "passed-verbatim",
        "dispatch": "subscription-runtime-bridge-execute",
        "pre_dispatch_validation": (
            "hmac-launch-receipts-and-canonical-request-runtime-completion-limit"
        ),
        "readback": "subscription-runtime-bridge-lookup-outcome",
        "runtime_provenance": "hmac-verified-exact-fleet-readiness-derived-pool-and-boot",
        "schema_version": SCHEDULER_SUBSCRIPTION_BRIDGE_ADAPTER_SCHEMA_VERSION,
        "state_revalidation": "suite-and-pool-authorities-on-every-operation",
        "terminal_tokens": "completion-ceiling-and-observed-total-accounting",
    },
)
SCHEDULER_SUBSCRIPTION_BRIDGE_RECEIPT_POLICY_SHA256 = commitment(
    "subscription-runtime-scheduler-bridge-receipt-policy",
    {
        "authentication": "authenticated-bridge-journal-terminal-reread",
        "ciphertext": "answer-only-with-all-terminal-ciphertext-committed",
        "implementation_sha256": SCHEDULER_SUBSCRIPTION_BRIDGE_IMPLEMENTATION_SHA256,
        "schema_version": SCHEDULER_SUBSCRIPTION_BRIDGE_ADAPTER_SCHEMA_VERSION,
    },
)
SCHEDULER_SUBSCRIPTION_BRIDGE_READBACK_POLICY_SHA256 = commitment(
    "subscription-runtime-scheduler-bridge-readback-policy",
    {
        "ambiguous": "durable-intent-without-terminal-result",
        "authentication": "exact-current-bridge-journal-reread",
        "found": "authenticated-terminal-result",
        "schema_version": SCHEDULER_SUBSCRIPTION_BRIDGE_ADAPTER_SCHEMA_VERSION,
        "not_found": "ambiguous-journal-generation-or-intent-unknown",
        "transport_calls": 0,
    },
)
_PREFLIGHT_BINDING = BridgeCallBinding(
    intent_id="scheduler-preflight-intent",
    logical_operation="scheduler-preflight",
    logical_call_id="scheduler-preflight-call",
)


def build_subscription_runtime_scheduler_bridge_boot_authority(
    *,
    pool: BridgePoolAuthority,
    boot_nonce_sha256: str,
) -> SchedulerBridgeBootAuthority:
    """Build the exact scheduler authority expected by this bridge seam."""

    if not is_sha256(boot_nonce_sha256):
        _fail("scheduler_subscription_bridge_boot_authority_invalid")
    _require_official_runtime_pool(pool)
    return SchedulerBridgeBootAuthority(
        bridge_id=pool.pool_id,
        implementation_sha256=SCHEDULER_SUBSCRIPTION_BRIDGE_IMPLEMENTATION_SHA256,
        runtime_authority_sha256=pool.commitment_sha256,
        boot_nonce_sha256=boot_nonce_sha256,
        receipt_verifier_policy_sha256=(SCHEDULER_SUBSCRIPTION_BRIDGE_RECEIPT_POLICY_SHA256),
    )


def bridge_pool_authority_from_fleet_readiness(
    readiness: BridgeFleetReadinessReceipt,
) -> BridgePoolAuthority:
    """Adapt one exact launched-fleet receipt to its ordered pool authority."""

    if type(readiness) is not BridgeFleetReadinessReceipt:
        _fail("scheduler_subscription_bridge_fleet_readiness_invalid")
    try:
        BridgeFleetReadinessReceipt.__post_init__(readiness)
        for launch in readiness.launches:
            launch.pending.__post_init__()
            launch.health.__post_init__()
            launch.__post_init__()
        if (
            len({launch.pending.account_name for launch in readiness.launches}) != 3
            or len({launch.runtime_authority_sha256 for launch in readiness.launches}) != 3
            or len({bridge.origin for bridge in readiness.pool.bridges}) != 3
            or len({bridge.account_binding_hmac_sha256 for bridge in readiness.pool.bridges}) != 3
        ):
            raise ValueError
    except Exception:
        _fail("scheduler_subscription_bridge_fleet_readiness_invalid")
    _require_official_runtime_pool(readiness.pool)
    return readiness.pool


def verify_fleet_launch_receipts(
    readiness: BridgeFleetReadinessReceipt,
    keys: BridgeSecretCapability,
) -> BridgePoolAuthority:
    """Verify every ordered launch HMAC and its exact runtime authority binding."""

    pool = bridge_pool_authority_from_fleet_readiness(readiness)
    try:
        key_reader = keys.launcher_receipt_key
        if not callable(key_reader):
            raise TypeError
        for bridge, launch in zip(pool.bridges, readiness.launches, strict=True):
            key = key_reader(bridge.bridge_id)
            if type(key) is not bytes or not 32 <= len(key) <= 4096:
                raise ValueError
            launch.verify(key)
            if launch.bridge_authority_sha256 != bridge.commitment_sha256:
                raise ValueError
    except Exception:
        _fail("scheduler_subscription_bridge_launch_receipt_unauthenticated")
    return pool


def build_subscription_runtime_scheduler_bridge_boot_authority_from_fleet_readiness(
    readiness: BridgeFleetReadinessReceipt,
) -> SchedulerBridgeBootAuthority:
    """Derive pool and boot nonce only from an independent fleet readiness receipt."""

    pool = bridge_pool_authority_from_fleet_readiness(readiness)
    return build_subscription_runtime_scheduler_bridge_boot_authority(
        pool=pool,
        boot_nonce_sha256=readiness.commitment_sha256,
    )


def scheduler_bridge_boot_authority_from_fleet_readiness(
    readiness: BridgeFleetReadinessReceipt,
) -> SchedulerBridgeBootAuthority:
    """Short public alias for the fleet-readiness-to-scheduler adapter."""

    return build_subscription_runtime_scheduler_bridge_boot_authority_from_fleet_readiness(
        readiness
    )


def bridge_call_binding(envelope: SchedulerDispatchEnvelope) -> BridgeCallBinding:
    """Map durable scheduler identities without deriving a replacement intent."""

    if type(envelope) is not SchedulerDispatchEnvelope:
        _fail("scheduler_subscription_bridge_envelope_invalid")
    SchedulerDispatchEnvelope.__post_init__(envelope)
    dependency = envelope.dependency_answer_ciphertext_sha256
    operation = (
        "scheduler-answer:no-dependency"
        if envelope.stage is SchedulerCallStage.ANSWER
        else f"scheduler-judge:{dependency}"
    )
    return BridgeCallBinding(
        intent_id=envelope.intent_sha256,
        logical_operation=operation,
        logical_call_id=envelope.logical_call_id,
    )


@final
class SchedulerSubscriptionBridgeAdapter:
    """Atomic dispatch, verifier, and reconciliation ports for the runner."""

    __slots__ = (
        "_bridge",
        "_fleet_readiness",
        "_fleet_readiness_snapshot",
        "_keys",
        "_pool",
        "_pool_snapshot",
        "_run_authorities",
        "_suite",
        "_suite_snapshot",
    )

    def __init__(
        self,
        *,
        suite: SchedulerSuiteAuthority,
        fleet_readiness: BridgeFleetReadinessReceipt,
        bridge: SubscriptionRuntimeBridgeAdapter,
        keys: BridgeSecretCapability,
    ) -> None:
        if (
            type(suite) is not SchedulerSuiteAuthority
            or type(fleet_readiness) is not BridgeFleetReadinessReceipt
            or type(bridge) is not SubscriptionRuntimeBridgeAdapter
        ):
            _fail("scheduler_subscription_bridge_composition_invalid")
        pool = verify_fleet_launch_receipts(fleet_readiness, keys)
        expected_boot = (
            build_subscription_runtime_scheduler_bridge_boot_authority_from_fleet_readiness(
                fleet_readiness
            )
        )
        if suite.bridge_boot != expected_boot:
            _fail("scheduler_subscription_bridge_authority_mismatch")
        self._suite = suite
        self._suite_snapshot = canonical_json(suite.material())
        self._run_authorities = tuple(
            run_authority_from_suite(suite, run_index=index).commitment_sha256 for index in (0, 1)
        )
        self._fleet_readiness = fleet_readiness
        self._fleet_readiness_snapshot = canonical_json(fleet_readiness.public_payload())
        self._pool = pool
        self._pool_snapshot = canonical_json(pool.public_payload())
        self._bridge = bridge
        self._keys = keys

    @property
    def bridge_boot_authority_sha256(self) -> str:
        return self._suite.bridge_boot.commitment_sha256

    @property
    def suite_authority_sha256(self) -> str:
        return self._suite.commitment_sha256

    @property
    def fleet_readiness_sha256(self) -> str:
        return self._fleet_readiness.commitment_sha256

    @property
    def pool_authority_sha256(self) -> str:
        return self._pool.commitment_sha256

    @property
    def scheduler_runtime_provenance_sha256(self) -> str:
        return self._suite.runtime_provenance_sha256

    @property
    def policy_sha256(self) -> str:
        return SCHEDULER_SUBSCRIPTION_BRIDGE_RECEIPT_POLICY_SHA256

    @property
    def readback_policy_sha256(self) -> str:
        return SCHEDULER_SUBSCRIPTION_BRIDGE_READBACK_POLICY_SHA256

    def __repr__(self) -> str:
        return (
            "SchedulerSubscriptionBridgeAdapter("
            f"bridge_boot_authority_sha256={self.bridge_boot_authority_sha256!r}, "
            f"fleet_readiness_sha256={self.fleet_readiness_sha256!r}, "
            f"pool_authority_sha256={self._pool.commitment_sha256!r}, "
            "private_capabilities=<bound>)"
        )

    def invoke_once(self, envelope: SchedulerDispatchEnvelope) -> SchedulerDispatchOutcome:
        """Spend the exact scheduler intent through ``execute`` at most once."""

        self._require_envelope(envelope)
        self._require_bridge_intent(envelope, self._preflight_intent(envelope))
        outcome = self._bridge.execute(
            binding=bridge_call_binding(envelope),
            canonical_request_body=envelope.payload,
        )
        if isinstance(outcome, TerminalBridgeCall):
            return self._terminal_outcome(envelope, outcome)
        if isinstance(outcome, OutcomeUnknown):
            self._require_bridge_intent(envelope, outcome.intent)
            _fail("scheduler_subscription_bridge_outcome_unknown")
        if isinstance(outcome, NotFound):
            _fail("scheduler_subscription_bridge_execute_not_found")
        _fail("scheduler_subscription_bridge_outcome_invalid")

    def preflight(self, *, payload: bytes, token_ceiling: int) -> None:
        """Validate request selectors before the runner creates a dispatch intent."""

        self._require_runtime_binding()
        if type(payload) is not bytes or not payload or type(token_ceiling) is not int:
            _fail("scheduler_subscription_bridge_request_invalid")
        try:
            _, intent = derive_bridge_intent(
                pool=self._pool,
                binding=_PREFLIGHT_BINDING,
                request_body=payload,
                maximum_request_bytes=len(payload),
            )
        except SchedulerRunnerError:
            raise
        except Exception:
            _fail("scheduler_subscription_bridge_request_invalid")
        if intent.output_token_limit != token_ceiling:
            _fail("scheduler_subscription_bridge_intent_crosswire")

    def verify(
        self,
        *,
        receipt: SchedulerDispatchReceipt,
        envelope: SchedulerDispatchEnvelope,
    ) -> bool:
        """Verify against an authenticated current terminal journal read."""

        try:
            self._require_envelope(envelope)
            current = self._bridge.lookup_outcome(envelope.intent_sha256)
            if not isinstance(current, TerminalBridgeCall):
                return False
            expected = self._terminal_outcome(envelope, current).receipt
            return expected == receipt and hmac.compare_digest(
                expected.commitment_sha256,
                receipt.commitment_sha256,
            )
        except Exception:
            return False

    def lookup(self, envelope: SchedulerDispatchEnvelope) -> SchedulerDispatchReadback:
        """Translate ``lookup_outcome`` without exposing a transport path."""

        self._require_envelope(envelope)
        return self._current_readback(envelope)

    def authenticate(
        self,
        *,
        readback: SchedulerDispatchReadback,
        envelope: SchedulerDispatchEnvelope,
    ) -> bool:
        """Authenticate all dispositions by exact current journal reread."""

        try:
            self._require_envelope(envelope)
            expected = self._current_readback(envelope)
            return expected == readback and hmac.compare_digest(
                expected.commitment_sha256,
                readback.commitment_sha256,
            )
        except Exception:
            return False

    def _current_readback(
        self,
        envelope: SchedulerDispatchEnvelope,
    ) -> SchedulerDispatchReadback:
        bridge_outcome = self._bridge.lookup_outcome(envelope.intent_sha256)
        outcome: SchedulerDispatchOutcome | None = None
        if isinstance(bridge_outcome, TerminalBridgeCall):
            disposition = SchedulerDispatchReadbackDisposition.FOUND
            outcome = self._terminal_outcome(envelope, bridge_outcome)
            bridge_state = {
                "kind": "terminal",
                "receipt_sha256": outcome.receipt.commitment_sha256,
            }
        elif isinstance(bridge_outcome, OutcomeUnknown):
            self._require_bridge_intent(envelope, bridge_outcome.intent)
            disposition = SchedulerDispatchReadbackDisposition.AMBIGUOUS
            bridge_state = {
                "intent_sha256": hashlib.sha256(
                    canonical_json(bridge_outcome.intent.public_payload())
                ).hexdigest(),
                "kind": "outcome_unknown",
            }
        elif isinstance(bridge_outcome, NotFound):
            if bridge_outcome.intent_id != envelope.intent_sha256:
                _fail("scheduler_subscription_bridge_readback_crosswire")
            disposition = SchedulerDispatchReadbackDisposition.AMBIGUOUS
            bridge_state = {"kind": "journal_generation_or_intent_unknown"}
        else:
            _fail("scheduler_subscription_bridge_readback_invalid")
        attestation = canonical_json(
            {
                "bridge_state": bridge_state,
                "disposition": disposition.value,
                "envelope": _envelope_material(envelope),
                "pool_authority_sha256": self._pool.commitment_sha256,
                "readback_policy_sha256": self.readback_policy_sha256,
                "schema_version": SCHEDULER_SUBSCRIPTION_BRIDGE_ADAPTER_SCHEMA_VERSION,
            }
        )
        return SchedulerDispatchReadback(
            disposition=disposition,
            readback_policy_sha256=self.readback_policy_sha256,
            request_sha256=envelope.request_sha256,
            intent_sha256=envelope.intent_sha256,
            outcome=outcome,
            attestation=attestation,
        )

    def _terminal_outcome(
        self,
        envelope: SchedulerDispatchEnvelope,
        terminal: TerminalBridgeCall,
    ) -> SchedulerDispatchOutcome:
        self._require_bridge_intent(envelope, terminal.readback.intent)
        result = terminal.readback.result
        result.__post_init__()
        encrypted_output = result.encrypted_output
        ciphertext_sha256 = hashlib.sha256(encrypted_output).hexdigest()
        scheduler_ciphertext = (
            encrypted_output if envelope.stage is SchedulerCallStage.ANSWER else None
        )
        attestation = canonical_json(
            {
                "bridge_intent": terminal.readback.intent.public_payload(),
                "bridge_result": {
                    **result.public_payload(include_ciphertext=False),
                    "encrypted_output_sha256": ciphertext_sha256,
                },
                "envelope": _envelope_material(envelope),
                "schema_version": SCHEDULER_SUBSCRIPTION_BRIDGE_ADAPTER_SCHEMA_VERSION,
                "translation": {
                    "charged_tokens": "usage.total_tokens",
                    "completion_tokens": "usage.completion_tokens",
                    "judge_ciphertext": "committed-in-attestation-only",
                    "request_bytes": "verbatim",
                },
            }
        )
        receipt = SchedulerDispatchReceipt(
            suite_authority_sha256=envelope.suite_authority_sha256,
            run_authority_sha256=envelope.run_authority_sha256,
            bridge_boot_authority_sha256=envelope.bridge_boot_authority_sha256,
            logical_call_id=envelope.logical_call_id,
            stage=envelope.stage,
            renderer_policy_sha256=envelope.renderer_policy_sha256,
            private_answer_policy_sha256=envelope.private_answer_policy_sha256,
            dependency_answer_ciphertext_sha256=(envelope.dependency_answer_ciphertext_sha256),
            request_sha256=envelope.request_sha256,
            intent_sha256=envelope.intent_sha256,
            private_output_ciphertext_sha256=(
                ciphertext_sha256 if envelope.stage is SchedulerCallStage.ANSWER else None
            ),
            completion_tokens=result.usage.completion_tokens,
            charged_tokens=result.usage.total_tokens,
            attestation=attestation,
        )
        return SchedulerDispatchOutcome(
            receipt=receipt,
            private_output_ciphertext=scheduler_ciphertext,
            provider_dispatches=int(terminal.transport_dispatched),
        )

    def _require_envelope(self, envelope: object) -> None:
        if type(envelope) is not SchedulerDispatchEnvelope:
            _fail("scheduler_subscription_bridge_envelope_invalid")
        SchedulerDispatchEnvelope.__post_init__(envelope)
        self._require_runtime_binding()
        if (
            envelope.suite_authority_sha256 != self._suite.commitment_sha256
            or envelope.run_authority_sha256 not in self._run_authorities
            or envelope.bridge_boot_authority_sha256 != self._suite.bridge_boot.commitment_sha256
        ):
            _fail("scheduler_subscription_bridge_envelope_crosswire")

    def _require_runtime_binding(self) -> None:
        current_pool = verify_fleet_launch_receipts(self._fleet_readiness, self._keys)
        current_boot = (
            build_subscription_runtime_scheduler_bridge_boot_authority_from_fleet_readiness(
                self._fleet_readiness
            )
        )
        if (
            canonical_json(self._suite.material()) != self._suite_snapshot
            or self._suite.commitment_sha256 != commitment("suite", self._suite.material())
            or canonical_json(self._fleet_readiness.public_payload())
            != self._fleet_readiness_snapshot
            or current_pool != self._pool
            or current_boot != self._suite.bridge_boot
            or canonical_json(self._pool.public_payload()) != self._pool_snapshot
            or self._pool.commitment_sha256 != self._suite.bridge_boot.runtime_authority_sha256
        ):
            _fail("scheduler_subscription_bridge_envelope_crosswire")

    def _preflight_intent(self, envelope: SchedulerDispatchEnvelope) -> BridgeIntent:
        """Validate request/model/token binding before any durable claim or transport."""

        try:
            _, intent = derive_bridge_intent(
                pool=self._pool,
                binding=bridge_call_binding(envelope),
                request_body=envelope.payload,
                maximum_request_bytes=len(envelope.payload),
            )
        except SchedulerRunnerError:
            raise
        except Exception:
            _fail("scheduler_subscription_bridge_request_invalid")
        return intent

    def _require_bridge_intent(
        self,
        envelope: SchedulerDispatchEnvelope,
        intent: object,
    ) -> None:
        if type(intent) is not BridgeIntent:
            _fail("scheduler_subscription_bridge_intent_invalid")
        expected_binding = bridge_call_binding(envelope)
        selected = self._pool.select(expected_binding)
        if (
            intent.binding != expected_binding
            or intent.pool_id != self._pool.pool_id
            or intent.pool_authority_sha256 != self._pool.commitment_sha256
            or intent.bridge_id != selected.bridge_id
            or intent.bridge_authority_sha256 != selected.commitment_sha256
            or intent.request_body_sha256 != hashlib.sha256(envelope.payload).hexdigest()
            or intent.output_token_limit != envelope.token_ceiling
        ):
            _fail("scheduler_subscription_bridge_intent_crosswire")


def _envelope_material(envelope: SchedulerDispatchEnvelope) -> dict[str, object]:
    return {
        "bridge_boot_authority_sha256": envelope.bridge_boot_authority_sha256,
        "dependency_answer_ciphertext_sha256": (envelope.dependency_answer_ciphertext_sha256),
        "dispatch_deadline_unix_ms": envelope.dispatch_deadline_unix_ms,
        "intent_sha256": envelope.intent_sha256,
        "logical_call_id": envelope.logical_call_id,
        "ordinal": envelope.ordinal,
        "payload_sha256": envelope.payload_sha256,
        "private_answer_policy_sha256": envelope.private_answer_policy_sha256,
        "renderer_policy_sha256": envelope.renderer_policy_sha256,
        "request_sha256": envelope.request_sha256,
        "run_authority_sha256": envelope.run_authority_sha256,
        "runner_schema_version": RUNNER_SCHEMA_VERSION,
        "stage": envelope.stage.value,
        "suite_authority_sha256": envelope.suite_authority_sha256,
        "token_ceiling": envelope.token_ceiling,
    }


def _require_official_runtime_pool(pool: object) -> BridgePoolAuthority:
    try:
        if type(pool) is not BridgePoolAuthority:
            raise ValueError
        BridgePoolAuthority.__post_init__(pool)
        if len(pool.bridges) != 3:
            raise ValueError
        for bridge in pool.bridges:
            if (
                type(bridge) is not BridgeAuthority
                or bridge.public_model != BridgeAuthority.CODEX_MODEL
                or bridge.CODEX_MODEL != "gpt-5.6-sol"
                or bridge.REASONING_EFFORT != "high"
                or bridge.SERVICE_TIER != "priority"
                or bridge.MODEL_PROVIDER != "openai"
                or bridge.EXECUTION_PROFILE != "stateless-completion"
                or bridge.base_instructions_sha256 != SUBSCRIPTION_RUNTIME_BASE_INSTRUCTIONS_SHA256
            ):
                raise ValueError
    except Exception:
        _fail("scheduler_subscription_bridge_runtime_authority_invalid")
    return pool


def _fail(code: str) -> None:
    raise SchedulerRunnerError(code)


__all__ = (
    "SCHEDULER_SUBSCRIPTION_BRIDGE_ADAPTER_SCHEMA_VERSION",
    "SCHEDULER_SUBSCRIPTION_BRIDGE_IMPLEMENTATION_SHA256",
    "SCHEDULER_SUBSCRIPTION_BRIDGE_READBACK_POLICY_SHA256",
    "SCHEDULER_SUBSCRIPTION_BRIDGE_RECEIPT_POLICY_SHA256",
    "SchedulerSubscriptionBridgeAdapter",
    "bridge_pool_authority_from_fleet_readiness",
    "bridge_call_binding",
    "build_subscription_runtime_scheduler_bridge_boot_authority",
    "build_subscription_runtime_scheduler_bridge_boot_authority_from_fleet_readiness",
    "scheduler_bridge_boot_authority_from_fleet_readiness",
    "verify_fleet_launch_receipts",
)

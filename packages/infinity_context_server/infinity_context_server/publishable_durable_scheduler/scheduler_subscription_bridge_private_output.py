"""Journal-backed private answer recovery for the official judge renderer."""

from __future__ import annotations

import hashlib
from typing import final

from infinity_context_runtime_bridge import (
    SubscriptionRuntimeBridgeAdapter,
    TerminalBridgeCall,
)

from infinity_context_server.publishable_durable_scheduler.contracts import (
    SchedulerSuiteAuthority,
    commitment,
    run_authority_from_suite,
)
from infinity_context_server.publishable_durable_scheduler.runner_contracts import (
    SchedulerRunnerError,
)
from infinity_context_server.publishable_durable_scheduler.runner_request_composition import (
    SchedulerDecryptedPrivateAnswer,
    SchedulerPrivateAnswerDecryptContext,
)

SCHEDULER_SUBSCRIPTION_BRIDGE_PRIVATE_OUTPUT_SCHEMA = (
    "memory-comparison-scheduler-subscription-private-output.v1"
)
SCHEDULER_SUBSCRIPTION_BRIDGE_PRIVATE_OUTPUT_IMPLEMENTATION_SHA256 = commitment(
    "subscription-runtime-scheduler-private-output-implementation",
    {
        "authentication": "current-terminal-journal-reread",
        "ciphertext_binding": "exact-bytes-and-sha256",
        "decryption": "terminal-bound-private-output-capability",
        "lookup": "unique-logical-call-id",
        "schema_version": SCHEDULER_SUBSCRIPTION_BRIDGE_PRIVATE_OUTPUT_SCHEMA,
        "transport_calls": 0,
    },
)


@final
class SchedulerSubscriptionBridgePrivateOutputDecryptor:
    """Recover AES-GCM AAD through the authenticated terminal bridge outcome."""

    __slots__ = ("_bridge", "_policy_sha256", "_run_authorities", "_suite_sha256")

    def __init__(
        self,
        *,
        suite: SchedulerSuiteAuthority,
        bridge: SubscriptionRuntimeBridgeAdapter,
    ) -> None:
        if (
            type(suite) is not SchedulerSuiteAuthority
            or type(bridge) is not SubscriptionRuntimeBridgeAdapter
        ):
            _fail("scheduler_subscription_private_output_composition_invalid")
        self._bridge = bridge
        self._suite_sha256 = suite.commitment_sha256
        self._run_authorities = tuple(
            run_authority_from_suite(suite, run_index=index).commitment_sha256 for index in (0, 1)
        )
        self._policy_sha256 = commitment(
            "subscription-runtime-scheduler-private-output-policy",
            {
                "implementation_sha256": (
                    SCHEDULER_SUBSCRIPTION_BRIDGE_PRIVATE_OUTPUT_IMPLEMENTATION_SHA256
                ),
                "ordered_run_authority_sha256": list(self._run_authorities),
                "schema_version": SCHEDULER_SUBSCRIPTION_BRIDGE_PRIVATE_OUTPUT_SCHEMA,
                "suite_authority_sha256": self._suite_sha256,
            },
        )

    @property
    def policy_sha256(self) -> str:
        return self._policy_sha256

    def decrypt_exact(
        self,
        ciphertext: bytes,
        *,
        context: SchedulerPrivateAnswerDecryptContext,
    ) -> SchedulerDecryptedPrivateAnswer:
        if type(context) is not SchedulerPrivateAnswerDecryptContext:
            _fail("scheduler_subscription_private_output_context_invalid")
        context.__post_init__()
        if (
            context.decrypt_policy_sha256 != self._policy_sha256
            or context.case_key.suite_authority_sha256 != self._suite_sha256
            or context.case_key.run_authority_sha256 not in self._run_authorities
            or type(ciphertext) is not bytes
            or not ciphertext
            or hashlib.sha256(ciphertext).hexdigest() != context.ciphertext_sha256
        ):
            _fail("scheduler_subscription_private_output_binding_invalid")
        try:
            terminal = self._bridge.lookup_logical_call(context.answer_logical_call_id)
        except Exception:
            _fail("scheduler_subscription_private_output_read_failed")
        if type(terminal) is not TerminalBridgeCall:
            _fail("scheduler_subscription_private_output_terminal_missing")
        intent = terminal.readback.intent
        result = terminal.readback.result
        if (
            terminal.transport_dispatched is not False
            or intent.binding.logical_call_id != context.answer_logical_call_id
            or intent.binding.logical_operation != "scheduler-answer:no-dependency"
            or result.encrypted_output != ciphertext
            or hashlib.sha256(result.encrypted_output).hexdigest() != context.ciphertext_sha256
        ):
            _fail("scheduler_subscription_private_output_binding_invalid")
        try:
            answer = terminal.private_output.render_for_judge()
        except Exception:
            _fail("scheduler_subscription_private_output_decryption_failed")
        return SchedulerDecryptedPrivateAnswer(context=context, answer=answer)

    def __repr__(self) -> str:
        return (
            "SchedulerSubscriptionBridgePrivateOutputDecryptor("
            f"policy_sha256={self._policy_sha256!r}, private_capabilities=<bound>)"
        )


def _fail(code: str) -> None:
    raise SchedulerRunnerError(code)


__all__ = (
    "SCHEDULER_SUBSCRIPTION_BRIDGE_PRIVATE_OUTPUT_IMPLEMENTATION_SHA256",
    "SCHEDULER_SUBSCRIPTION_BRIDGE_PRIVATE_OUTPUT_SCHEMA",
    "SchedulerSubscriptionBridgePrivateOutputDecryptor",
)

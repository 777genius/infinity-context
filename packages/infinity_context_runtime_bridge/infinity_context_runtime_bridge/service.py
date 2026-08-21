"""One-shot orchestration across durable intent, transport, receipt, and private output."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .attestation import (
    output_associated_data,
    verify_reconstructed_runtime_receipt,
    verify_runtime_response,
)
from .contracts import (
    AuthenticatedPreDispatchAbsence,
    BridgeAuthority,
    BridgeCallBinding,
    BridgeIntent,
    BridgeJournalError,
    BridgeOutcome,
    BridgePoolAuthority,
    BridgeSecretCapability,
    BridgeTransportPort,
    NotFound,
    OutcomeUnknown,
    OutputCipherPort,
    PrivateOutputError,
    TerminalOutcome,
)
from .journal import BridgeJournal
from .request_contract import derive_bridge_intent


@dataclass(frozen=True, slots=True)
class TerminalBridgeCall:
    """Exact authenticated journal readback plus a narrowly bound output capability."""

    readback: TerminalOutcome
    private_output: BoundPrivateOutput
    transport_dispatched: bool

    def __post_init__(self) -> None:
        if (
            not isinstance(self.readback, TerminalOutcome)
            or type(self.private_output) is not BoundPrivateOutput
            or type(self.transport_dispatched) is not bool
        ):
            raise BridgeJournalError("bridge_terminal_call_invalid")


BridgeAdapterOutcome = (
    AuthenticatedPreDispatchAbsence | NotFound | OutcomeUnknown | TerminalBridgeCall
)


class BoundPrivateOutput:
    """Decrypt only one exact authenticated outcome for private judge rendering."""

    __slots__ = ("_cipher", "_expected", "_journal")

    def __init__(
        self,
        *,
        journal: BridgeJournal,
        cipher: OutputCipherPort,
        expected: TerminalOutcome,
    ) -> None:
        self._journal = journal
        self._cipher = cipher
        self._expected = expected

    def render_for_judge(self) -> str:
        current = self._journal.lookup_outcome(self._expected.intent.binding.intent_id)
        if not isinstance(current, TerminalOutcome) or current != self._expected:
            raise PrivateOutputError("bridge_private_output_binding_changed")
        associated_data = output_associated_data(current.intent, current.result)
        try:
            plaintext = self._cipher.open(
                current.result.encrypted_output,
                associated_data=associated_data,
            )
        except Exception as exc:
            raise PrivateOutputError("bridge_private_output_decryption_failed") from exc
        if type(plaintext) is not bytes:
            raise PrivateOutputError("bridge_private_output_plaintext_invalid")
        if hashlib.sha256(plaintext).hexdigest() != current.result.output_text_sha256:
            raise PrivateOutputError("bridge_private_output_identity_invalid")
        try:
            return plaintext.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise PrivateOutputError("bridge_private_output_utf8_invalid") from exc


class SubscriptionRuntimeBridgeAdapter:
    """Low-level provider-free boundary; only a newly claimed intent may dispatch."""

    __slots__ = (
        "_cipher",
        "_journal",
        "_maximum_request_bytes",
        "_maximum_response_bytes",
        "_pool",
        "_secrets",
        "_transport",
    )

    def __init__(
        self,
        *,
        pool: BridgePoolAuthority,
        secrets: BridgeSecretCapability,
        transport: BridgeTransportPort,
        journal: BridgeJournal,
        output_cipher: OutputCipherPort,
        maximum_request_bytes: int,
        maximum_response_bytes: int,
    ) -> None:
        for value, label in (
            (maximum_request_bytes, "request"),
            (maximum_response_bytes, "response"),
        ):
            if type(value) is not int or not 1 <= value <= 64 * 1024 * 1024:
                raise ValueError(f"bridge_{label}_byte_limit_invalid")
        self._pool = pool
        self._secrets = secrets
        self._transport = transport
        self._journal = journal
        self._cipher = output_cipher
        self._maximum_request_bytes = maximum_request_bytes
        self._maximum_response_bytes = maximum_response_bytes

    def execute(
        self,
        *,
        binding: BridgeCallBinding,
        canonical_request_body: bytes,
    ) -> BridgeAdapterOutcome:
        bridge, intent = derive_bridge_intent(
            pool=self._pool,
            binding=binding,
            request_body=canonical_request_body,
            maximum_request_bytes=self._maximum_request_bytes,
        )
        claim = self._journal.record_intent(intent)
        if not claim.dispatch_granted:
            return self._expose(claim.outcome, transport_dispatched=False)

        response_body = self._transport.post_once(
            origin=bridge.origin,
            route=bridge.route,
            bearer_token=self._secrets.authorization_bearer(bridge.bridge_id),
            request_body=canonical_request_body,
            maximum_response_bytes=self._maximum_response_bytes,
        )
        verified = verify_runtime_response(
            response_body=response_body,
            maximum_response_bytes=self._maximum_response_bytes,
            authority=bridge,
            intent=intent,
            attestation_secret=self._secrets.attestation_secret(bridge.bridge_id),
        )
        associated_data = output_associated_data(intent, verified)
        encrypted = self._cipher.seal(
            verified.output_text.encode("utf-8"),
            associated_data=associated_data,
        )
        if (
            type(encrypted) is not bytes
            or not encrypted
            or len(encrypted) > self._maximum_response_bytes
        ):
            raise PrivateOutputError("bridge_private_output_ciphertext_invalid")
        result = verified.with_encrypted_output(encrypted)
        terminal = self._journal.record_result(intent, result)
        exact_readback = self._journal.lookup_outcome(binding.intent_id)
        if exact_readback != terminal:
            raise BridgeJournalError("bridge_journal_terminal_readback_invalid")
        return self._expose(terminal, transport_dispatched=True)

    @property
    def journal_generation_sha256(self) -> str:
        return self._journal.generation_sha256

    def lookup_outcome(self, intent_id: str) -> BridgeAdapterOutcome:
        """Read authenticated state only; this method has no transport path."""

        return self._expose(
            self._journal.lookup_outcome(intent_id),
            transport_dispatched=False,
        )

    def lookup_logical_call(self, logical_call_id: str) -> BridgeAdapterOutcome | None:
        """Read one authenticated logical call for bound private-output recovery."""

        outcome = self._journal.lookup_logical_call(logical_call_id)
        if outcome is None:
            return None
        return self._expose(outcome, transport_dispatched=False)

    def lookup_pre_dispatch(self, binding: BridgeCallBinding) -> BridgeAdapterOutcome:
        """Read an exact call or return authenticated same-generation absence."""

        return self._expose(
            self._journal.lookup_pre_dispatch(binding),
            transport_dispatched=False,
        )

    def authenticate_pre_dispatch_absence(
        self,
        proof: AuthenticatedPreDispatchAbsence,
    ) -> bool:
        return self._journal.authenticate_pre_dispatch_absence(proof)

    def _expose(
        self,
        outcome: BridgeOutcome,
        *,
        transport_dispatched: bool,
    ) -> BridgeAdapterOutcome:
        if isinstance(outcome, NotFound):
            return outcome
        if isinstance(outcome, AuthenticatedPreDispatchAbsence):
            if not self._journal.authenticate_pre_dispatch_absence(outcome):
                raise BridgeJournalError("bridge_pre_dispatch_absence_unauthenticated")
            return outcome
        selected = self._assert_pool_binding(outcome.intent)
        if isinstance(outcome, OutcomeUnknown):
            return outcome
        verify_reconstructed_runtime_receipt(
            authority=selected,
            intent=outcome.intent,
            result=outcome.result,
            attestation_secret=self._secrets.attestation_secret(selected.bridge_id),
        )
        return TerminalBridgeCall(
            readback=outcome,
            private_output=BoundPrivateOutput(
                journal=self._journal,
                cipher=self._cipher,
                expected=outcome,
            ),
            transport_dispatched=transport_dispatched,
        )

    def _assert_pool_binding(self, intent: BridgeIntent) -> BridgeAuthority:
        selected = self._pool.select(intent.binding)
        if (
            intent.pool_id != self._pool.pool_id
            or intent.pool_authority_sha256 != self._pool.commitment_sha256
            or intent.bridge_id != selected.bridge_id
            or intent.bridge_authority_sha256 != selected.commitment_sha256
        ):
            raise BridgeJournalError("bridge_journal_pool_authority_mismatch")
        return selected


__all__ = (
    "BoundPrivateOutput",
    "BridgeAdapterOutcome",
    "SubscriptionRuntimeBridgeAdapter",
    "TerminalBridgeCall",
)

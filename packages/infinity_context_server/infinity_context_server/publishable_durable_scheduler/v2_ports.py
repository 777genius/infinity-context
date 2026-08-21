"""Narrow provider-free scheduler-v2 ports implemented by outer adapters."""

from __future__ import annotations

from typing import Protocol

from infinity_context_server.publishable_durable_scheduler.v2_contracts import AttemptReceipt
from infinity_context_server.publishable_durable_scheduler.v2_evidence import (
    DatabasePredicateEvidence,
    DispatchBoundaryObservation,
    ProviderCompletionAttestation,
)


class DatabaseClockPort(Protocol):
    def observe(self, *, predicate_sha256: str) -> DatabasePredicateEvidence: ...


class DurableIntentPort(Protocol):
    def persist_intent(self, receipt: AttemptReceipt) -> str: ...


class DispatchStartedFsyncPort(Protocol):
    def fsync_dispatch_started(self, receipt: AttemptReceipt) -> None: ...


class DispatchBoundaryPort(Protocol):
    def invoke_once(self, payload: bytes) -> DispatchBoundaryObservation: ...


class CompletionAttestationVerifierPort(Protocol):
    def verify(self, attestation: ProviderCompletionAttestation) -> bool: ...


__all__ = (
    "CompletionAttestationVerifierPort",
    "DatabaseClockPort",
    "DispatchBoundaryPort",
    "DispatchStartedFsyncPort",
    "DurableIntentPort",
)

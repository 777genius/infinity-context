"""Minimal structural views consumed by the live Mem0 v5 micro-canary."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol


class SealView(Protocol):
    admission_commitment_sha256: str
    commitment_sha256: str
    operation_root_sha256: str
    provider_observed_extraction_calls: int
    provider_observed_request_tokens: int
    provider_observed_response_tokens: int


class SearchView(Protocol):
    records: tuple[object, ...]
    result_root_sha256: str
    evidence_commitment_sha256: str


class TerminalView(Protocol):
    terminal_state: str
    commitment_sha256: str
    provider_observed_extraction_calls: int
    provider_observed_request_tokens: int
    provider_observed_response_tokens: int


class CoordinatorView(Protocol):
    @property
    def budget(self) -> object: ...

    @property
    def storage_observations(self) -> tuple[object, ...]: ...

    @property
    def terminal_evidence(self) -> TerminalView: ...

    def admit(self, *, authority: object, request: object, budget_policy: object) -> None: ...

    def dispatch_pending(self) -> SealView: ...

    def restore(self, *, authority: object, request: object, budget_policy: object) -> object: ...

    def seal_restored_completed(self) -> SealView: ...

    def search_evidence(self, *, corpus_id: str, query: str, limit: int) -> SearchView: ...

    def cleanup(self) -> TerminalView: ...

    def abort(self) -> TerminalView: ...


class CompositionView(Protocol):
    authority: object
    request: object
    coordinator: CoordinatorView


CompositionFactory = Callable[[], CompositionView]


__all__ = (
    "CompositionFactory",
    "CompositionView",
    "CoordinatorView",
    "SearchView",
    "SealView",
    "TerminalView",
)

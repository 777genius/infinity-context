"""Opaque single-owner receipts for the managed HTTP policy lifecycle."""

from __future__ import annotations

import threading
import weakref
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import final

from infinity_context_server.memory_comparison_managed_http_policy_validation import (
    ManagedHttpPolicyCleanupPassMaterial,
    ManagedHttpPolicyCorpusMaterial,
)

_TOKEN = object()
_RECEIPT_LOCK = threading.RLock()


class ManagedHttpPolicyReceiptError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class _OpaqueReceipt:
    __slots__ = ()

    def __reduce__(self) -> object:
        raise TypeError("managed HTTP policy receipts are nonserializable")


@final
class ManagedHttpPolicyDeleteReceipt(_OpaqueReceipt):
    """Opaque record of one exact cleanup/readback pass."""

    __slots__ = ("__weakref__",)

    def __init__(self, *, _token: object) -> None:
        if _token is not _TOKEN:
            raise ManagedHttpPolicyReceiptError("managed_http_policy_delete_receipt_forged")

    def __repr__(self) -> str:
        return "ManagedHttpPolicyDeleteReceipt(<opaque>)"

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedHttpPolicyDeleteReceipt is final")


@final
class ManagedHttpPolicyCanonicalSourceReceipt(_OpaqueReceipt):
    """Opaque per-case handle over one immutable corpus evidence bundle."""

    __slots__ = ("__weakref__",)

    def __init__(self, *, _token: object) -> None:
        if _token is not _TOKEN:
            raise ManagedHttpPolicyReceiptError("managed_http_policy_canonical_receipt_forged")

    def __repr__(self) -> str:
        return "ManagedHttpPolicyCanonicalSourceReceipt(<opaque>)"

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedHttpPolicyCanonicalSourceReceipt is final")


@final
class ManagedHttpPolicyTerminalDeleteReceipt(_OpaqueReceipt):
    """Opaque handle over exact ordered two-pass cleanup evidence."""

    __slots__ = ("__weakref__",)

    def __init__(self, *, _token: object) -> None:
        if _token is not _TOKEN:
            raise ManagedHttpPolicyReceiptError("managed_http_policy_terminal_receipt_forged")

    def __repr__(self) -> str:
        return "ManagedHttpPolicyTerminalDeleteReceipt(<opaque>)"

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedHttpPolicyTerminalDeleteReceipt is final")


@dataclass(slots=True)
class ManagedHttpPolicyCanonicalReceiptState:
    owner: object
    ordinal: int
    case_id: str
    corpus_id: str
    run_id: str
    binding_commitment_sha256: str
    managed_attestation_commitment_sha256: str
    execution_case_manifest_sha256: str
    corpus: ManagedHttpPolicyCorpusMaterial
    phase: str


@dataclass(slots=True)
class ManagedHttpPolicyDeleteReceiptState:
    owner: object
    run_id: str
    binding_commitment_sha256: str
    backend_role: str
    target_identity_sha256: str
    pass_index: int
    source_scope_count: int
    deleted_count: int
    canonical_absent: bool
    backend_verified_absent: bool
    corpus_manifest_sha256: tuple[str, ...]
    mem0_created_memory_ids: tuple[str, ...]
    source_pairs: tuple[tuple[str, str], ...]
    cleanup_commitment_sha256: str
    corpus_absence_commitments: tuple[tuple[str, str], ...]
    exact_absence_commitment_sha256: str
    phase: str


@dataclass(slots=True)
class ManagedHttpPolicyTerminalReceiptState:
    owner: object
    run_id: str
    binding_commitment_sha256: str
    managed_attestation_commitment_sha256: str
    execution_case_manifest_sha256: str
    cleanup_passes: tuple[ManagedHttpPolicyCleanupPassMaterial, ...]
    phase: str


_DELETE: weakref.WeakKeyDictionary[
    ManagedHttpPolicyDeleteReceipt, ManagedHttpPolicyDeleteReceiptState
] = weakref.WeakKeyDictionary()
_CANONICAL: weakref.WeakKeyDictionary[
    ManagedHttpPolicyCanonicalSourceReceipt, ManagedHttpPolicyCanonicalReceiptState
] = weakref.WeakKeyDictionary()
_TERMINAL: weakref.WeakKeyDictionary[
    ManagedHttpPolicyTerminalDeleteReceipt, ManagedHttpPolicyTerminalReceiptState
] = weakref.WeakKeyDictionary()


def issue_delete_receipt(
    state: ManagedHttpPolicyDeleteReceiptState,
) -> ManagedHttpPolicyDeleteReceipt:
    receipt = ManagedHttpPolicyDeleteReceipt(_token=_TOKEN)
    with _RECEIPT_LOCK:
        _DELETE[receipt] = state
    return receipt


def issue_canonical_receipt(
    state: ManagedHttpPolicyCanonicalReceiptState,
) -> ManagedHttpPolicyCanonicalSourceReceipt:
    receipt = ManagedHttpPolicyCanonicalSourceReceipt(_token=_TOKEN)
    with _RECEIPT_LOCK:
        _CANONICAL[receipt] = state
    return receipt


def issue_terminal_receipt(
    state: ManagedHttpPolicyTerminalReceiptState,
) -> ManagedHttpPolicyTerminalDeleteReceipt:
    receipt = ManagedHttpPolicyTerminalDeleteReceipt(_token=_TOKEN)
    with _RECEIPT_LOCK:
        _TERMINAL[receipt] = state
    return receipt


@contextmanager
def receipt_registry_transaction() -> Iterator[None]:
    """Serialize a multi-receipt validation and state transition."""

    with _RECEIPT_LOCK:
        yield


def delete_receipt_state(value: object) -> ManagedHttpPolicyDeleteReceiptState:
    with _RECEIPT_LOCK:
        return _state(value, ManagedHttpPolicyDeleteReceipt, _DELETE, "delete")


def canonical_receipt_state(value: object) -> ManagedHttpPolicyCanonicalReceiptState:
    with _RECEIPT_LOCK:
        return _state(value, ManagedHttpPolicyCanonicalSourceReceipt, _CANONICAL, "canonical")


def terminal_receipt_state(value: object) -> ManagedHttpPolicyTerminalReceiptState:
    with _RECEIPT_LOCK:
        return _state(value, ManagedHttpPolicyTerminalDeleteReceipt, _TERMINAL, "terminal")


def _state(value: object, expected: type, registry: weakref.WeakKeyDictionary, name: str):
    if type(value) is not expected:
        raise ManagedHttpPolicyReceiptError(f"managed_http_policy_{name}_receipt_type_invalid")
    state = registry.get(value)
    if state is None:
        raise ManagedHttpPolicyReceiptError(f"managed_http_policy_{name}_receipt_unknown")
    return state


__all__ = (
    "ManagedHttpPolicyCanonicalReceiptState",
    "ManagedHttpPolicyCanonicalSourceReceipt",
    "ManagedHttpPolicyDeleteReceipt",
    "ManagedHttpPolicyDeleteReceiptState",
    "ManagedHttpPolicyReceiptError",
    "ManagedHttpPolicyTerminalDeleteReceipt",
    "ManagedHttpPolicyTerminalReceiptState",
    "canonical_receipt_state",
    "delete_receipt_state",
    "issue_canonical_receipt",
    "issue_delete_receipt",
    "issue_terminal_receipt",
    "receipt_registry_transaction",
    "terminal_receipt_state",
)

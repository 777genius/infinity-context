"""Deferred exact receipt handles for target-major managed-run callbacks."""

from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass
from typing import final

from infinity_context_server.memory_comparison_managed_mem0_v5_ingest_receipts import (
    ManagedMem0V5CorpusIngestReceipt,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_production_lifecycle import (
    ManagedMem0V5IngestSnapshot,
    ManagedMem0V5ProductionLifecycleAdapter,
)


class ManagedMem0V5PendingReceiptError(RuntimeError):
    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@final
class ManagedMem0V5PendingIngestReceipt:
    __slots__ = ("__weakref__",)

    def __init__(self, *, _token: object) -> None:
        if _token is not _TOKEN:
            _fail("pending_receipt_forged")

    def __repr__(self) -> str:
        return "ManagedMem0V5PendingIngestReceipt(<opaque>)"

    def __reduce__(self) -> object:
        raise TypeError("managed Mem0 v5 pending receipt is nonserializable")


@dataclass(slots=True)
class _Entry:
    handle: ManagedMem0V5PendingIngestReceipt
    corpus_id: str
    receipt: ManagedMem0V5CorpusIngestReceipt | None = None


_TOKEN = object()


@final
class ManagedMem0V5PendingReceiptSet:
    """Reserve before I/O and atomically bind the exact ordered v5 receipts."""

    __slots__ = (
        "_consumed",
        "_corpus_ids",
        "_entries",
        "_lifecycle",
        "_lock",
        "_phase",
    )

    def __init__(
        self,
        *,
        corpus_ids: tuple[str, ...],
        production_lifecycle: ManagedMem0V5ProductionLifecycleAdapter,
    ) -> None:
        if (
            type(corpus_ids) is not tuple
            or not corpus_ids
            or any(type(item) is not str or not item for item in corpus_ids)
            or len(set(corpus_ids)) != len(corpus_ids)
            or type(production_lifecycle) is not ManagedMem0V5ProductionLifecycleAdapter
        ):
            _fail("pending_receipt_set_invalid")
        self._corpus_ids = corpus_ids
        self._lifecycle = production_lifecycle
        self._entries: list[_Entry] = []
        self._phase = "open"
        self._consumed = False
        self._lock = threading.RLock()

    @property
    def complete(self) -> bool:
        with self._lock:
            return len(self._entries) == len(self._corpus_ids)

    def reserved_handles(self) -> tuple[ManagedMem0V5PendingIngestReceipt, ...]:
        with self._lock:
            return tuple(item.handle for item in self._entries)

    def reserve(self, *, corpus_id: str) -> ManagedMem0V5PendingIngestReceipt:
        with self._lock:
            ordinal = len(self._entries)
            if (
                self._phase != "open"
                or ordinal >= len(self._corpus_ids)
                or corpus_id != self._corpus_ids[ordinal]
            ):
                self._phase = "terminal"
                _fail("pending_receipt_reserve_invalid")
            handle = ManagedMem0V5PendingIngestReceipt(_token=_TOKEN)
            self._entries.append(_Entry(handle, corpus_id))
            return handle

    def bind_exact_ordered(
        self,
        *,
        handles: tuple[ManagedMem0V5PendingIngestReceipt, ...],
        receipts: tuple[ManagedMem0V5CorpusIngestReceipt, ...],
    ) -> None:
        with self._lock:
            expected = tuple(item.handle for item in self._entries)
            if (
                self._phase != "open"
                or len(self._entries) != len(self._corpus_ids)
                or type(handles) is not tuple
                or handles != expected
                or type(receipts) is not tuple
                or len(receipts) != len(expected)
                or any(type(item) is not ManagedMem0V5CorpusIngestReceipt for item in receipts)
                or len({id(item) for item in receipts}) != len(receipts)
            ):
                self._phase = "terminal"
                _fail("pending_receipt_bind_invalid")
            self._phase = "binding"
        try:
            snapshot = self._lifecycle.authenticate_exact_receipts(receipts)
            valid_snapshot = (
                type(snapshot) is ManagedMem0V5IngestSnapshot
                and snapshot.receipt_count == len(self._corpus_ids)
                and snapshot.ordered_corpus_id_sha256
                == tuple(hashlib.sha256(item.encode()).hexdigest() for item in self._corpus_ids)
            )
        except Exception:
            valid_snapshot = False
        with self._lock:
            if (
                not valid_snapshot
                or self._phase != "binding"
                or tuple(item.handle for item in self._entries) != expected
            ):
                self._phase = "terminal"
                _fail("pending_receipt_bind_invalid")
            for entry, receipt in zip(self._entries, receipts, strict=True):
                entry.receipt = receipt
            self._phase = "bound"

    def consume_exact_ordered(
        self, handles: tuple[ManagedMem0V5PendingIngestReceipt, ...]
    ) -> tuple[ManagedMem0V5CorpusIngestReceipt, ...]:
        with self._lock:
            expected = tuple(item.handle for item in self._entries)
            receipts = tuple(item.receipt for item in self._entries)
            if (
                self._phase != "bound"
                or self._consumed
                or type(handles) is not tuple
                or handles != expected
                or any(item is None for item in receipts)
            ):
                _fail("pending_receipt_consume_invalid")
            self._consumed = True
            self._phase = "consumed"
            return receipts  # type: ignore[return-value]

    def terminalize(self) -> None:
        with self._lock:
            self._phase = "terminal"


def _fail(code: str) -> None:
    raise ManagedMem0V5PendingReceiptError(code)


__all__ = (
    "ManagedMem0V5PendingIngestReceipt",
    "ManagedMem0V5PendingReceiptError",
    "ManagedMem0V5PendingReceiptSet",
)

"""Process-local collector for authenticated managed-v5 transport observations."""

from __future__ import annotations

import threading
from typing import final

from infinity_context_server.memory_comparison_managed_mem0_v5_request_binding import (
    ManagedMem0V5AuthenticatedRequestBindingV2Witness,
    authenticate_managed_mem0_v5_request_binding_v2_witness,
)
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunError


@final
class ManagedMem0V5TransportObservationCollector:
    __slots__ = ("_by_operation_id", "_items", "_lock")

    def __init__(self) -> None:
        self._items: list[ManagedMem0V5AuthenticatedRequestBindingV2Witness] = []
        self._by_operation_id: dict[
            str, ManagedMem0V5AuthenticatedRequestBindingV2Witness
        ] = {}
        self._lock = threading.Lock()

    def record(self, value: object) -> None:
        try:
            witness = authenticate_managed_mem0_v5_request_binding_v2_witness(value)
            operation_id = witness.operation_id_sha256
        except Exception:
            raise ManagedRunError("managed transport observation is unauthenticated") from None
        with self._lock:
            if operation_id in self._by_operation_id:
                raise ManagedRunError("managed transport observation is duplicated")
            self._items.append(witness)
            self._by_operation_id[operation_id] = witness

    def record_idempotent(self, value: object) -> None:
        """Record authenticated crash readback, accepting only an exact replay."""

        try:
            witness = authenticate_managed_mem0_v5_request_binding_v2_witness(value)
            operation_id = witness.operation_id_sha256
        except Exception:
            raise ManagedRunError("managed transport observation is unauthenticated") from None
        with self._lock:
            existing = self._by_operation_id.get(operation_id)
            if existing is None:
                self._items.append(witness)
                self._by_operation_id[operation_id] = witness
                return
            try:
                authenticated_existing = (
                    authenticate_managed_mem0_v5_request_binding_v2_witness(existing)
                )
                if authenticated_existing.receipt != witness.receipt:
                    raise ManagedRunError("managed transport observation readback differs")
            except ManagedRunError:
                raise
            except Exception:
                raise ManagedRunError(
                    "managed transport observation is unauthenticated"
                ) from None

    def snapshot(self) -> tuple[ManagedMem0V5AuthenticatedRequestBindingV2Witness, ...]:
        with self._lock:
            return tuple(self._items)


__all__ = ("ManagedMem0V5TransportObservationCollector",)

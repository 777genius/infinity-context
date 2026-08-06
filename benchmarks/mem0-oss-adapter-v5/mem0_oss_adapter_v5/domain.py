"""Immutable, provider-neutral contracts for the Mem0 v5 benchmark adapter."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from weakref import ReferenceType, ref

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_ISSUED: dict[int, tuple[ReferenceType[object], str, type[object]]] = {}
_RECEIPT_ISSUER_SEAL = object()


class AdapterContractError(ValueError):
    """A stable, data-free contract error."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def canonical_json_bytes(value: Mapping[str, object] | Sequence[object]) -> bytes:
    """Return the sole canonical JSON encoding used by adapter commitments."""

    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise AdapterContractError("mem0_v5_canonical_json_invalid") from None


def canonical_sha256(value: Mapping[str, object] | Sequence[object]) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def sha256_bytes(value: bytes) -> str:
    if type(value) is not bytes:
        raise AdapterContractError("mem0_v5_digest_input_invalid")
    return hashlib.sha256(value).hexdigest()


def require_sha256(value: object, code: str = "mem0_v5_sha256_invalid") -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise AdapterContractError(code)
    return value


def require_safe_id(value: object, code: str = "mem0_v5_identifier_invalid") -> str:
    if type(value) is not str or _SAFE_ID.fullmatch(value) is None:
        raise AdapterContractError(code)
    return value


class RuntimeCallDisposition(StrEnum):
    NOT_DISPATCHED = "not_dispatched"
    RECEIPT_DURABLE = "receipt_durable"
    OUTCOME_UNKNOWN = "outcome_unknown"


@dataclass(frozen=True, slots=True, weakref_slot=True)
class OperationDispatchIntent:
    """Public hashes that bind one and only one provider attempt."""

    admission_commitment_sha256: str
    operation_id_sha256: str
    unit_identity_sha256: str
    unit_sha256: str
    scope_sha256: str
    request_body_sha256: str
    sequence: int

    def __post_init__(self) -> None:
        for value in (
            self.admission_commitment_sha256,
            self.operation_id_sha256,
            self.unit_identity_sha256,
            self.unit_sha256,
            self.scope_sha256,
            self.request_body_sha256,
        ):
            require_sha256(value, "mem0_v5_dispatch_intent_invalid")
        if type(self.sequence) is not int or not 0 <= self.sequence <= 1_000_000:
            raise AdapterContractError("mem0_v5_dispatch_intent_invalid")
        _register(self, canonical_sha256(self.commitment_payload()))

    def commitment_payload(self) -> dict[str, object]:
        return {
            "admission_commitment_sha256": self.admission_commitment_sha256,
            "operation_id_sha256": self.operation_id_sha256,
            "request_body_sha256": self.request_body_sha256,
            "scope_sha256": self.scope_sha256,
            "sequence": self.sequence,
            "unit_identity_sha256": self.unit_identity_sha256,
            "unit_sha256": self.unit_sha256,
        }


@dataclass(frozen=True, slots=True, weakref_slot=True)
class RuntimeCallOutcome:
    """Crash policy: an attempted call is never eligible for blind redispatch."""

    intent: OperationDispatchIntent
    disposition: RuntimeCallDisposition
    runtime_receipt_sha256: str | None = None

    def __post_init__(self) -> None:
        if type(self.intent) is not OperationDispatchIntent:
            raise AdapterContractError("mem0_v5_runtime_outcome_invalid")
        if type(self.disposition) is not RuntimeCallDisposition:
            raise AdapterContractError("mem0_v5_runtime_outcome_invalid")
        if self.disposition is RuntimeCallDisposition.RECEIPT_DURABLE:
            require_sha256(self.runtime_receipt_sha256, "mem0_v5_runtime_outcome_invalid")
        elif self.runtime_receipt_sha256 is not None:
            raise AdapterContractError("mem0_v5_runtime_outcome_invalid")
        require_authentic_dispatch_intent(self.intent)
        _register(self, _outcome_snapshot(self))

    @property
    def redispatch_allowed(self) -> bool:
        require_authentic_runtime_outcome(self)
        return self.disposition is RuntimeCallDisposition.NOT_DISPATCHED


@dataclass(frozen=True, slots=True, repr=False, weakref_slot=True)
class ExtractionMemory:
    id: str
    text: str = field(repr=False)
    attributed_to: str
    linked_memory_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            type(self.id) is not str
            or not self.id.isascii()
            or not self.id.isdigit()
            or type(self.text) is not str
            or not self.text
            or type(self.attributed_to) is not str
            or self.attributed_to not in {"user", "assistant"}
            or type(self.linked_memory_ids) is not tuple
            or any(type(item) is not str for item in self.linked_memory_ids)
        ):
            raise AdapterContractError("mem0_v5_extracted_memory_invalid")
        _register(self, _memory_snapshot(self))

    @property
    def text_sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()

    def commitment_payload(self) -> dict[str, object]:
        return {
            "attributed_to": self.attributed_to,
            "id": self.id,
            "linked_memory_ids": list(self.linked_memory_ids),
            "text_sha256": self.text_sha256,
        }

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(id={self.id!r}, attributed_to={self.attributed_to!r}, "
            f"linked_count={len(self.linked_memory_ids)}, text_sha256={self.text_sha256!r})"
        )


def _freeze(value: object) -> object:
    if type(value) is dict:
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if type(value) is list:
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if type(value) is tuple:
        return [_thaw(item) for item in value]
    return value


@dataclass(frozen=True, slots=True, repr=False, init=False, weakref_slot=True)
class SanitizedRuntimeReceipt:
    """Exact receipt-v2 allowlist; it cannot retain prompt or completion text."""

    _payload: Mapping[str, object] = field(repr=False)
    receipt_sha256: str

    def __init__(
        self,
        payload: Mapping[str, object],
        *,
        verified_receipt_sha256: str,
        _seal: object | None = None,
    ) -> None:
        if _seal is not _RECEIPT_ISSUER_SEAL:
            raise AdapterContractError("mem0_v5_runtime_receipt_unverified")
        if type(payload) is not dict:
            raise AdapterContractError("mem0_v5_runtime_receipt_invalid")
        copied = _thaw(_freeze(payload))
        if type(copied) is not dict:
            raise AdapterContractError("mem0_v5_runtime_receipt_invalid")
        frozen = _freeze(copied)
        assert isinstance(frozen, Mapping)
        receipt_sha256 = canonical_sha256(copied)
        if receipt_sha256 != require_sha256(
            verified_receipt_sha256,
            "mem0_v5_runtime_receipt_unverified",
        ):
            raise AdapterContractError("mem0_v5_runtime_receipt_unverified")
        object.__setattr__(self, "_payload", frozen)
        object.__setattr__(self, "receipt_sha256", receipt_sha256)
        _register(self, receipt_sha256)

    def public_payload(self) -> dict[str, object]:
        payload = _thaw(self._payload)
        assert type(payload) is dict
        return payload

    def __repr__(self) -> str:
        return f"{type(self).__name__}(receipt_sha256={self.receipt_sha256!r})"


@dataclass(frozen=True, slots=True, repr=False, weakref_slot=True)
class RuntimeExtractionResult:
    intent: OperationDispatchIntent
    memories: tuple[ExtractionMemory, ...] = field(repr=False)
    receipt: SanitizedRuntimeReceipt = field(repr=False)
    output_text_sha256: str

    def __post_init__(self) -> None:
        if (
            type(self.intent) is not OperationDispatchIntent
            or type(self.memories) is not tuple
            or any(type(item) is not ExtractionMemory for item in self.memories)
            or type(self.receipt) is not SanitizedRuntimeReceipt
        ):
            raise AdapterContractError("mem0_v5_runtime_result_invalid")
        require_sha256(self.output_text_sha256, "mem0_v5_runtime_result_invalid")
        require_authentic_dispatch_intent(self.intent)
        for memory in self.memories:
            require_authentic_extraction_memory(memory)
        require_authentic_runtime_receipt(self.receipt)
        _register(self, _result_snapshot(self))

    @property
    def commitment_sha256(self) -> str:
        return canonical_sha256(
            {
                "intent": self.intent.commitment_payload(),
                "memories": [item.commitment_payload() for item in self.memories],
                "output_text_sha256": self.output_text_sha256,
                "runtime_receipt_sha256": self.receipt.receipt_sha256,
            }
        )

    @property
    def outcome(self) -> RuntimeCallOutcome:
        return RuntimeCallOutcome(
            intent=self.intent,
            disposition=RuntimeCallDisposition.RECEIPT_DURABLE,
            runtime_receipt_sha256=self.receipt.receipt_sha256,
        )

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(operation_id_sha256={self.intent.operation_id_sha256!r}, "
            f"memory_count={len(self.memories)}, commitment_sha256={self.commitment_sha256!r})"
        )


def _issue_sanitized_runtime_receipt(
    payload: dict[str, object],
    *,
    verified_receipt_sha256: str,
) -> SanitizedRuntimeReceipt:
    """Issue a receipt only after the established v2 authority has verified it."""

    return SanitizedRuntimeReceipt(
        payload,
        verified_receipt_sha256=verified_receipt_sha256,
        _seal=_RECEIPT_ISSUER_SEAL,
    )


def require_authentic_dispatch_intent(value: object) -> OperationDispatchIntent:
    if type(value) is not OperationDispatchIntent:
        raise AdapterContractError("mem0_v5_dispatch_intent_unauthentic")
    try:
        snapshot = canonical_sha256(value.commitment_payload())
    except (AttributeError, TypeError, ValueError, AdapterContractError):
        raise AdapterContractError("mem0_v5_dispatch_intent_unauthentic") from None
    _require_registered(value, snapshot, "mem0_v5_dispatch_intent_unauthentic")
    return value


def snapshot_authentic_dispatch_intent(value: object) -> OperationDispatchIntent:
    """Copy exact primitives and prove they match the originally issued snapshot."""

    if type(value) is not OperationDispatchIntent:
        raise AdapterContractError("mem0_v5_dispatch_intent_unauthentic")
    try:
        copied = OperationDispatchIntent(
            admission_commitment_sha256=value.admission_commitment_sha256,
            operation_id_sha256=value.operation_id_sha256,
            unit_identity_sha256=value.unit_identity_sha256,
            unit_sha256=value.unit_sha256,
            scope_sha256=value.scope_sha256,
            request_body_sha256=value.request_body_sha256,
            sequence=value.sequence,
        )
        copied_snapshot = canonical_sha256(copied.commitment_payload())
    except (AttributeError, TypeError, ValueError, AdapterContractError):
        raise AdapterContractError("mem0_v5_dispatch_intent_unauthentic") from None
    registered = _ISSUED.get(id(value))
    if (
        registered is None
        or registered[0]() is not value
        or registered[1] != copied_snapshot
        or registered[2] is not OperationDispatchIntent
    ):
        raise AdapterContractError("mem0_v5_dispatch_intent_unauthentic")
    return copied


def require_authentic_runtime_outcome(value: object) -> RuntimeCallOutcome:
    if type(value) is not RuntimeCallOutcome:
        raise AdapterContractError("mem0_v5_runtime_outcome_unauthentic")
    try:
        require_authentic_dispatch_intent(value.intent)
        snapshot = _outcome_snapshot(value)
    except (AttributeError, TypeError, ValueError, AdapterContractError):
        raise AdapterContractError("mem0_v5_runtime_outcome_unauthentic") from None
    _require_registered(value, snapshot, "mem0_v5_runtime_outcome_unauthentic")
    return value


def require_authentic_extraction_memory(value: object) -> ExtractionMemory:
    if type(value) is not ExtractionMemory:
        raise AdapterContractError("mem0_v5_extracted_memory_unauthentic")
    try:
        snapshot = _memory_snapshot(value)
    except (AttributeError, TypeError, ValueError, AdapterContractError):
        raise AdapterContractError("mem0_v5_extracted_memory_unauthentic") from None
    _require_registered(value, snapshot, "mem0_v5_extracted_memory_unauthentic")
    return value


def require_authentic_runtime_receipt(value: object) -> SanitizedRuntimeReceipt:
    if type(value) is not SanitizedRuntimeReceipt:
        raise AdapterContractError("mem0_v5_runtime_receipt_unauthentic")
    try:
        payload = value.public_payload()
        snapshot = canonical_sha256(payload)
    except (AttributeError, TypeError, ValueError, AdapterContractError):
        raise AdapterContractError("mem0_v5_runtime_receipt_unauthentic") from None
    if snapshot != value.receipt_sha256:
        raise AdapterContractError("mem0_v5_runtime_receipt_unauthentic")
    _require_registered(value, snapshot, "mem0_v5_runtime_receipt_unauthentic")
    return value


def require_authentic_runtime_result(value: object) -> RuntimeExtractionResult:
    if type(value) is not RuntimeExtractionResult:
        raise AdapterContractError("mem0_v5_runtime_result_unauthentic")
    require_authentic_dispatch_intent(value.intent)
    for memory in value.memories:
        require_authentic_extraction_memory(memory)
    require_authentic_runtime_receipt(value.receipt)
    _require_registered(
        value,
        _result_snapshot(value),
        "mem0_v5_runtime_result_unauthentic",
    )
    return value


def _memory_snapshot(value: ExtractionMemory) -> str:
    return canonical_sha256(value.commitment_payload())


def _outcome_snapshot(value: RuntimeCallOutcome) -> str:
    return canonical_sha256(
        {
            "disposition": value.disposition.value,
            "intent": value.intent.commitment_payload(),
            "runtime_receipt_sha256": value.runtime_receipt_sha256,
        }
    )


def _result_snapshot(value: RuntimeExtractionResult) -> str:
    return value.commitment_sha256


def _register(value: object, snapshot: str) -> None:
    identity = id(value)

    def discard(reference: ReferenceType[object]) -> None:
        current = _ISSUED.get(identity)
        if current is not None and current[0] is reference:
            _ISSUED.pop(identity, None)

    reference = ref(value, discard)
    _ISSUED[identity] = (reference, snapshot, type(value))


def _require_registered(value: object, snapshot: str, code: str) -> None:
    registered = _ISSUED.get(id(value))
    if (
        registered is None
        or registered[0]() is not value
        or registered[1] != snapshot
        or registered[2] is not type(value)
    ):
        raise AdapterContractError(code)


__all__ = [
    "AdapterContractError",
    "ExtractionMemory",
    "OperationDispatchIntent",
    "RuntimeCallDisposition",
    "RuntimeCallOutcome",
    "RuntimeExtractionResult",
    "SanitizedRuntimeReceipt",
    "canonical_json_bytes",
    "canonical_sha256",
    "require_authentic_dispatch_intent",
    "require_authentic_extraction_memory",
    "require_authentic_runtime_outcome",
    "require_authentic_runtime_receipt",
    "require_authentic_runtime_result",
    "require_safe_id",
    "require_sha256",
    "sha256_bytes",
    "snapshot_authentic_dispatch_intent",
]

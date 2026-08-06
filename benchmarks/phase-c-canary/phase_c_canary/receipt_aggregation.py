from __future__ import annotations

from dataclasses import dataclass
from weakref import ReferenceType, ref

from .hashing import canonical_json_bytes, sha256_bytes
from .receipt import ReceiptVerificationError
from .runtime_receipt_v2 import (
    ProviderObservedUsage,
    SafeRuntimeReceipt,
    require_verified_safe_receipt,
)


@dataclass(frozen=True, slots=True)
class ReceiptEvidencePage:
    page_number: int
    first_sequence: int
    last_sequence: int
    receipt_count: int
    receipt_commitments: tuple[str, ...]
    page_root_sha256: str


@dataclass(frozen=True, slots=True)
class ReceiptAggregation:
    receipt_count: int
    provider_call_count: int
    usage: ProviderObservedUsage
    runtime_binding_commitment_sha256: str
    receipts_root_sha256: str
    evidence_pages: tuple[ReceiptEvidencePage, ...]


class RuntimeReceiptAggregator:
    def __init__(self, *, max_receipts: int, evidence_page_size: int = 64) -> None:
        _validate_aggregation_config(max_receipts, evidence_page_size)
        self._max_receipts = max_receipts
        self._page_size = evidence_page_size
        self._receipts: dict[int, SafeRuntimeReceipt] = {}
        self._receipt_hashes: set[str] = set()
        self._operation_hashes: set[str] = set()
        self._identity_hashes: set[str] = set()
        self._binding_commitment: str | None = None
        _remember_receipt_log(self)

    def add(self, receipt: SafeRuntimeReceipt) -> None:
        _require_authentic_receipt_log(self)
        require_verified_safe_receipt(receipt)
        ordered, binding_commitment = _derive_receipts(
            self._receipts,
            require_nonempty=False,
            require_contiguous=False,
        )
        if len(ordered) >= self._max_receipts:
            raise ReceiptVerificationError("runtime receipt aggregation limit exceeded")
        receipt_hashes = {item.receipt_sha256 for item in ordered}
        operation_hashes = {item.operation_id_sha256 for item in ordered}
        identity_hashes = {item.identity_sha256 for item in ordered}
        if receipt.sequence in {item.sequence for item in ordered}:
            raise ReceiptVerificationError("runtime receipt sequence is duplicated")
        if receipt.receipt_sha256 in receipt_hashes:
            raise ReceiptVerificationError("runtime receipt is duplicated")
        if receipt.operation_id_sha256 in operation_hashes:
            raise ReceiptVerificationError("runtime receipt operation identity is duplicated")
        if receipt.identity_sha256 in identity_hashes:
            raise ReceiptVerificationError("runtime account/thread/turn identity is duplicated")
        if (
            binding_commitment is not None
            and receipt.runtime_binding_commitment_sha256 != binding_commitment
        ):
            raise ReceiptVerificationError("runtime binding differs within aggregation")
        self._receipts[receipt.sequence] = receipt
        self._receipt_hashes.add(receipt.receipt_sha256)
        self._operation_hashes.add(receipt.operation_id_sha256)
        self._identity_hashes.add(receipt.identity_sha256)
        self._binding_commitment = receipt.runtime_binding_commitment_sha256
        _remember_receipt_log(self)

    def snapshot(self) -> ReceiptAggregation:
        _require_authentic_receipt_log(self)
        ordered, binding_commitment = _derive_receipts(
            self._receipts,
            require_nonempty=True,
            require_contiguous=True,
        )
        assert binding_commitment is not None
        commitments = tuple(
            sha256_bytes(canonical_json_bytes(item.commitment_payload())) for item in ordered
        )
        pages = tuple(
            self._page(
                index // self._page_size,
                ordered[index : index + self._page_size],
                commitments[index : index + self._page_size],
            )
            for index in range(0, len(ordered), self._page_size)
        )
        usage = _sum_usage(ordered)
        root = sha256_bytes(
            canonical_json_bytes(
                {
                    "schema_version": 1,
                    "receipt_count": len(ordered),
                    "provider_call_count": len(ordered),
                    "runtime_binding_commitment_sha256": binding_commitment,
                    "receipt_commitments": list(commitments),
                    "usage": usage.commitment_payload(),
                }
            )
        )
        return ReceiptAggregation(
            len(ordered),
            len(ordered),
            usage,
            binding_commitment,
            root,
            pages,
        )

    @staticmethod
    def _page(
        page_number: int,
        receipts: list[SafeRuntimeReceipt],
        commitments: tuple[str, ...],
    ) -> ReceiptEvidencePage:
        payload = {
            "schema_version": 1,
            "page_number": page_number,
            "first_sequence": receipts[0].sequence,
            "last_sequence": receipts[-1].sequence,
            "receipt_commitments": list(commitments),
        }
        return ReceiptEvidencePage(
            page_number=page_number,
            first_sequence=receipts[0].sequence,
            last_sequence=receipts[-1].sequence,
            receipt_count=len(receipts),
            receipt_commitments=commitments,
            page_root_sha256=sha256_bytes(canonical_json_bytes(payload)),
        )


def _sum_usage(receipts: list[SafeRuntimeReceipt]) -> ProviderObservedUsage:
    def optional_sum(name: str) -> int | None:
        values = [getattr(item.usage, name) for item in receipts]
        if not values or not all(value is not None for value in values):
            return None
        return sum(value for value in values if value is not None)

    return ProviderObservedUsage(
        prompt_tokens=sum(item.usage.prompt_tokens for item in receipts),
        completion_tokens=sum(item.usage.completion_tokens for item in receipts),
        total_tokens=sum(item.usage.total_tokens for item in receipts),
        cached_tokens=optional_sum("cached_tokens"),
        cache_write_tokens=optional_sum("cache_write_tokens"),
        reasoning_tokens=optional_sum("reasoning_tokens"),
    )


_LOG_SNAPSHOTS: dict[int, tuple[ReferenceType[RuntimeReceiptAggregator], str]] = {}


def _derive_receipts(
    receipts: dict[int, SafeRuntimeReceipt],
    *,
    require_nonempty: bool,
    require_contiguous: bool,
) -> tuple[list[SafeRuntimeReceipt], str | None]:
    ordered = [receipts[key] for key in sorted(receipts)]
    if require_nonempty and not ordered:
        raise ReceiptVerificationError(
            "publishable aggregation requires a trusted runtime-bound receipt"
        )
    for receipt in ordered:
        require_verified_safe_receipt(receipt)
    if require_contiguous and [item.sequence for item in ordered] != list(range(len(ordered))):
        raise ReceiptVerificationError("runtime receipt sequence must be contiguous from zero")
    _require_unique(ordered, "receipt_sha256", "runtime receipt is duplicated")
    _require_unique(
        ordered,
        "operation_id_sha256",
        "runtime receipt operation identity is duplicated",
    )
    _require_unique(
        ordered,
        "identity_sha256",
        "runtime account/thread/turn identity is duplicated",
    )
    bindings = {item.runtime_binding_commitment_sha256 for item in ordered}
    if len(bindings) > 1:
        raise ReceiptVerificationError("runtime binding differs within aggregation")
    return ordered, next(iter(bindings), None)


def _require_unique(receipts: list[SafeRuntimeReceipt], name: str, message: str) -> None:
    values = [getattr(receipt, name) for receipt in receipts]
    if len(set(values)) != len(values):
        raise ReceiptVerificationError(message)


def _remember_receipt_log(aggregator: RuntimeReceiptAggregator) -> None:
    identity = id(aggregator)

    def discard(reference: ReferenceType[RuntimeReceiptAggregator]) -> None:
        if (registered := _LOG_SNAPSHOTS.get(identity)) is not None and registered[0] is reference:
            _LOG_SNAPSHOTS.pop(identity, None)

    reference = ref(aggregator, discard)
    _LOG_SNAPSHOTS[identity] = (reference, _receipt_log_snapshot(aggregator))


def _require_authentic_receipt_log(aggregator: RuntimeReceiptAggregator) -> None:
    _validate_aggregation_config(aggregator._max_receipts, aggregator._page_size)
    registered = _LOG_SNAPSHOTS.get(id(aggregator))
    if (
        registered is None
        or registered[0]() is not aggregator
        or registered[1] != _receipt_log_snapshot(aggregator)
    ):
        raise ReceiptVerificationError("runtime receipt configuration or primary log was mutated")


def _receipt_log_snapshot(aggregator: RuntimeReceiptAggregator) -> str:
    try:
        payload = {
            "max_receipts": aggregator._max_receipts,
            "evidence_page_size": aggregator._page_size,
            "receipts": [
                {"sequence": sequence, "receipt_capability_identity": id(receipt)}
                for sequence, receipt in sorted(aggregator._receipts.items())
            ],
        }
        return sha256_bytes(canonical_json_bytes(payload))
    except (AttributeError, TypeError, ValueError):
        return "invalid"


def _validate_aggregation_config(max_receipts: object, evidence_page_size: object) -> None:
    if type(max_receipts) is not int or not 0 < max_receipts <= 100_000:
        raise ValueError("max_receipts must be within 1..100000")
    if type(evidence_page_size) is not int or not 0 < evidence_page_size <= 256:
        raise ValueError("evidence_page_size must be within 1..256")

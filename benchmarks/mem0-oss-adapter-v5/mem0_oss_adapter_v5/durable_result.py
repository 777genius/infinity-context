"""Authenticated codec for exact extraction results kept across process death."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Protocol

from mem0_oss_adapter_v5.app import AdapterServiceError
from mem0_oss_adapter_v5.domain import (
    ExtractionMemory,
    OperationDispatchIntent,
    RuntimeExtractionResult,
    canonical_json_bytes,
    canonical_sha256,
)
from mem0_oss_adapter_v5.http_models import DispatchRequest, RuntimeReceiptV2


class ReceiptAuthority(Protocol):
    def verify(self, **kwargs: object) -> str: ...


@dataclass(frozen=True, slots=True)
class DurableReceipt:
    model: RuntimeReceiptV2
    receipt_sha256: str

    def public_payload(self) -> dict[str, object]:
        return self.model.model_dump(mode="json", exclude_none=True)


@dataclass(frozen=True, slots=True)
class DurableResult:
    intent: OperationDispatchIntent
    memories: tuple[ExtractionMemory, ...]
    receipt: DurableReceipt
    output_text_sha256: str
    commitment_sha256: str


def encode_result(result: RuntimeExtractionResult, *, hmac_key: bytes) -> bytes:
    payload = result_payload(result)
    signature = hmac.new(
        hmac_key,
        canonical_json_bytes(payload),
        hashlib.sha256,
    ).hexdigest()
    return canonical_json_bytes({**payload, "result_file_hmac_sha256": signature})


def result_payload(result: RuntimeExtractionResult) -> dict[str, object]:
    receipt = RuntimeReceiptV2.model_validate(result.receipt.public_payload())
    return {
        "schema_version": "mem0-oss-adapter-v5.durable-result.v1",
        "intent": result.intent.commitment_payload(),
        "memories": [
            {
                "id": item.id,
                "text": item.text,
                "attributed_to": item.attributed_to,
                "linked_memory_ids": list(item.linked_memory_ids),
            }
            for item in result.memories
        ],
        "runtime_receipt": receipt.model_dump(mode="json", exclude_none=True),
        "output_text_sha256": result.output_text_sha256,
        "result_commitment_sha256": result.commitment_sha256,
    }


def parse_result(
    value: object,
    *,
    hmac_key: bytes,
    receipt_authority: ReceiptAuthority,
    request: object,
    expected_account_binding_hmac_sha256: str,
    expected_base_instructions_sha256: str,
) -> DurableResult:
    root = _exact_object(
        value,
        {
            "schema_version",
            "intent",
            "memories",
            "runtime_receipt",
            "output_text_sha256",
            "result_commitment_sha256",
            "result_file_hmac_sha256",
        },
    )
    signature = digest(root["result_file_hmac_sha256"])
    unsigned = {key: item for key, item in root.items() if key != "result_file_hmac_sha256"}
    expected_signature = hmac.new(
        hmac_key,
        canonical_json_bytes(unsigned),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected_signature):
        _unavailable()
    if root["schema_version"] != "mem0-oss-adapter-v5.durable-result.v1":
        _unavailable()
    intent = OperationDispatchIntent(
        **_exact_object(root["intent"], set(DispatchRequest.model_fields))
    )
    memories_raw = root["memories"]
    if type(memories_raw) is not list:
        _unavailable()
    memories = tuple(
        ExtractionMemory(
            id=_safe_text(item["id"]),
            text=_safe_text(item["text"], maximum=16_384),
            attributed_to=_safe_text(item["attributed_to"]),
            linked_memory_ids=tuple(item["linked_memory_ids"]),
        )
        for raw in memories_raw
        for item in (_exact_object(raw, {"id", "text", "attributed_to", "linked_memory_ids"}),)
    )
    try:
        receipt_model = RuntimeReceiptV2.model_validate(root["runtime_receipt"])
        receipt_payload = receipt_model.model_dump(mode="json", exclude_none=True)
    except Exception:
        _unavailable()
    try:
        verified_receipt_sha256 = receipt_authority.verify(
            receipt=receipt_payload,
            intent=intent,
            request=request,
            expected_account_binding_hmac_sha256=expected_account_binding_hmac_sha256,
            expected_base_instructions_sha256=expected_base_instructions_sha256,
            reasoning_effort="high",
            service_tier="default",
        )
    except Exception:
        _unavailable()
    receipt_sha256 = canonical_sha256(receipt_payload)
    if verified_receipt_sha256 != receipt_sha256:
        _unavailable()
    output_text_sha256 = digest(root["output_text_sha256"])
    if receipt_model.metadata.output_identity.output_text_sha256 != output_text_sha256:
        _unavailable()
    commitment = canonical_sha256(
        {
            "intent": intent.commitment_payload(),
            "memories": [item.commitment_payload() for item in memories],
            "output_text_sha256": output_text_sha256,
            "runtime_receipt_sha256": receipt_sha256,
        }
    )
    result = DurableResult(
        intent=intent,
        memories=memories,
        receipt=DurableReceipt(receipt_model, receipt_sha256),
        output_text_sha256=output_text_sha256,
        commitment_sha256=commitment,
    )
    if result.commitment_sha256 != root["result_commitment_sha256"]:
        _unavailable()
    return result


def digest(value: object) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError("digest_invalid")
    return value


def _exact_object(value: object, keys: set[str]) -> dict[str, object]:
    if type(value) is not dict or set(value) != keys:
        raise ValueError("exact_object_invalid")
    return value


def _safe_text(value: object, *, maximum: int = 512) -> str:
    if type(value) is not str or not value or value != value.strip() or len(value) > maximum:
        raise ValueError("text_invalid")
    return value


def _unavailable() -> None:
    raise AdapterServiceError("status_unavailable", status_code=503)


__all__ = (
    "DurableResult",
    "ReceiptAuthority",
    "digest",
    "encode_result",
    "parse_result",
)

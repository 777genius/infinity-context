"""Sealed contracts for the Infinity benchmark ingestion boundary."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, fields
from typing import Protocol

from infinity_context_server.memory_comparison_ingestion_contracts import IngestionUnit

SCHEMA_VERSION = "infinity-ingestion-receipt.v1"
_SHA256 = re.compile(r"[0-9a-f]{64}")
_IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,239}")


class InfinityIngestionError(RuntimeError):
    """The sealed ingestion boundary failed closed."""


class InfinityIngestionResultStorePort(Protocol):
    """Durable authenticated storage for normalized Infinity results."""

    def load(self, logical_operation_id: str) -> InfinityIngestionReceipt | None: ...

    def save(self, logical_operation_id: str, receipt: InfinityIngestionReceipt) -> None: ...


@dataclass(frozen=True, slots=True)
class InfinityIngestionReceipt:
    """Content-free evidence that one public ingestion unit was accepted."""

    run_id: str
    manifest_sha256: str
    ordinal: int
    corpus_id: str
    source_id: str
    payload_sha256: str
    metadata_sha256: str
    unit_input_sha256: str
    unit_sha256: str
    episode_id: str
    chunk_ids: tuple[str, ...]
    space_id: str
    memory_scope_id: str
    thread_id: str
    request_sha256: str
    response_sha256: str
    receipt_sha256: str
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        self.validate()

    @property
    def operation_id(self) -> str:
        return infinity_ingestion_operation_id(
            run_id=self.run_id,
            manifest_sha256=self.manifest_sha256,
            unit_sha256=self.unit_sha256,
        )

    def validate(self) -> None:
        if (
            self.schema_version != SCHEMA_VERSION
            or type(self.ordinal) is not int
            or self.ordinal < 0
        ):
            raise InfinityIngestionError("receipt authority is invalid")
        if type(self.run_id) is not str or not self.run_id.strip():
            raise InfinityIngestionError("receipt run_id is invalid")
        for name in (
            "manifest_sha256",
            "payload_sha256",
            "metadata_sha256",
            "unit_input_sha256",
            "unit_sha256",
            "request_sha256",
            "response_sha256",
        ):
            value = getattr(self, name)
            if type(value) is not str or _SHA256.fullmatch(value) is None:
                raise InfinityIngestionError(f"receipt {name} is invalid")
        for name in (
            "corpus_id",
            "source_id",
            "episode_id",
            "space_id",
            "memory_scope_id",
            "thread_id",
        ):
            value = getattr(self, name)
            if type(value) is not str or _IDENTITY.fullmatch(value) is None:
                raise InfinityIngestionError(f"receipt {name} is invalid")
        if (
            type(self.chunk_ids) is not tuple
            or not self.chunk_ids
            or len(set(self.chunk_ids)) != len(self.chunk_ids)
        ):
            raise InfinityIngestionError("receipt chunk_ids are invalid")
        if any(
            type(value) is not str or _IDENTITY.fullmatch(value) is None for value in self.chunk_ids
        ):
            raise InfinityIngestionError("receipt chunk_ids are invalid")
        if self.receipt_sha256 != infinity_ingestion_receipt_sha256(self):
            raise InfinityIngestionError("receipt commitment is invalid")

    def payload(self) -> dict[str, object]:
        payload = {field.name: getattr(self, field.name) for field in fields(self)}
        payload["chunk_ids"] = list(self.chunk_ids)
        return payload


def make_infinity_ingestion_receipt(
    *,
    unit: IngestionUnit,
    run_id: str,
    manifest_sha256: str,
    episode_id: str,
    chunk_ids: tuple[str, ...],
    space_id: str,
    memory_scope_id: str,
    thread_id: str,
    request_sha256: str,
    response_sha256: str,
) -> InfinityIngestionReceipt:
    values = dict(
        run_id=run_id,
        manifest_sha256=manifest_sha256,
        ordinal=unit.ordinal,
        corpus_id=unit.corpus_id,
        source_id=unit.metadata.source_id,
        payload_sha256=unit.payload_sha256,
        metadata_sha256=unit.metadata_sha256,
        unit_input_sha256=unit.unit_input_sha256,
        unit_sha256=unit.unit_sha256,
        episode_id=episode_id,
        chunk_ids=chunk_ids,
        space_id=space_id,
        memory_scope_id=memory_scope_id,
        thread_id=thread_id,
        request_sha256=request_sha256,
        response_sha256=response_sha256,
    )
    return InfinityIngestionReceipt(
        **values,
        receipt_sha256=_canonical_sha256(
            {**values, "chunk_ids": list(chunk_ids), "schema_version": SCHEMA_VERSION}
        ),
    )


def infinity_ingestion_operation_id(*, run_id: str, manifest_sha256: str, unit_sha256: str) -> str:
    return "infinity-ingest:" + _canonical_sha256(
        {"manifest_sha256": manifest_sha256, "run_id": run_id, "unit_sha256": unit_sha256}
    )


def infinity_ingestion_receipt_sha256(receipt: InfinityIngestionReceipt) -> str:
    payload = {
        field.name: getattr(receipt, field.name)
        for field in fields(receipt)
        if field.name != "receipt_sha256"
    }
    payload["chunk_ids"] = list(receipt.chunk_ids)
    return _canonical_sha256(payload)


def infinity_ingestion_result_commitment(
    receipt: InfinityIngestionReceipt,
) -> str:
    """Commit normalized canonical IDs, independent of HTTP JSON serialization."""

    receipt.validate()
    return _canonical_sha256(
        {
            "chunk_ids": list(receipt.chunk_ids),
            "corpus_id": receipt.corpus_id,
            "episode_id": receipt.episode_id,
            "manifest_sha256": receipt.manifest_sha256,
            "memory_scope_id": receipt.memory_scope_id,
            "ordinal": receipt.ordinal,
            "run_id": receipt.run_id,
            "source_id": receipt.source_id,
            "space_id": receipt.space_id,
            "thread_id": receipt.thread_id,
            "unit_sha256": receipt.unit_sha256,
        }
    )


def infinity_ingestion_receipt_from_payload(
    value: object,
) -> InfinityIngestionReceipt:
    if type(value) is not dict:
        raise InfinityIngestionError("stored Infinity result is not an exact object")
    expected = {field.name for field in fields(InfinityIngestionReceipt)}
    if set(value) != expected or type(value.get("chunk_ids")) is not list:
        raise InfinityIngestionError("stored Infinity result schema is invalid")
    return InfinityIngestionReceipt(
        **{**value, "chunk_ids": tuple(value["chunk_ids"])}  # type: ignore[arg-type]
    )


def _canonical_sha256(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


__all__ = [
    "InfinityIngestionError",
    "InfinityIngestionReceipt",
    "InfinityIngestionResultStorePort",
    "infinity_ingestion_operation_id",
    "infinity_ingestion_receipt_sha256",
    "infinity_ingestion_receipt_from_payload",
    "infinity_ingestion_result_commitment",
    "make_infinity_ingestion_receipt",
]

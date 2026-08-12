"""Typed, content-bound authority for the Mem0 retrieval handed to evaluation."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import final

from infinity_context_server.memory_comparison_models import RetrievedMemory
from infinity_context_server.publishable_durable_scheduler.retrieval_capture_contracts import (
    SCHEDULER_OFFICIAL_RETRIEVAL_LIMIT,
)
from infinity_context_server.publishable_durable_scheduler.runner_request_composition import (
    SCHEDULER_OFFICIAL_ANSWER_CUTOFF,
)

from .contracts import FreshChainCanaryError


@final
@dataclass(frozen=True, slots=True)
class FreshChainMem0RetrievalRecord:
    rank: int
    record_id: str
    memory: str
    memory_sha256: str
    source_id: str
    source_sha256: str
    score: float

    def __post_init__(self) -> None:
        if (
            type(self.rank) is not int
            or self.rank < 0
            or not _identifier(self.record_id)
            or type(self.memory) is not str
            or not self.memory
            or len(self.memory.encode()) > 16_384
            or hashlib.sha256(self.memory.encode()).hexdigest() != self.memory_sha256
            or not _identifier(self.source_id)
            or not _sha(self.source_sha256)
            or type(self.score) is not float
            or not math.isfinite(self.score)
            or not 0.0 <= self.score <= 1.0
        ):
            _fail("fresh_chain_mem0_retrieval_material_invalid")

    def payload(self) -> dict[str, object]:
        return {
            "memory": self.memory,
            "memory_sha256": self.memory_sha256,
            "rank": self.rank,
            "record_id": self.record_id,
            "score": self.score,
            "source_id": self.source_id,
            "source_sha256": self.source_sha256,
        }

    def memory_item(self) -> RetrievedMemory:
        return RetrievedMemory(
            text=self.memory,
            rank=self.rank,
            score=self.score,
            item_id=self.record_id,
            source_refs=(self.source_id,),
            metadata={
                "memory_sha256": self.memory_sha256,
                "source_sha256": self.source_sha256,
            },
        )


@final
@dataclass(frozen=True, slots=True)
class FreshChainMem0RetrievalMaterial:
    admission_commitment_sha256: str
    answer_cutoff: int
    evidence_commitment_sha256: str
    limit: int
    query_commitment_sha256: str
    records: tuple[FreshChainMem0RetrievalRecord, ...]
    result_count: int
    result_root_sha256: str

    def __post_init__(self) -> None:
        if (
            not all(
                _sha(value)
                for value in (
                    self.admission_commitment_sha256,
                    self.evidence_commitment_sha256,
                    self.query_commitment_sha256,
                    self.result_root_sha256,
                )
            )
            or type(self.answer_cutoff) is not int
            or self.answer_cutoff != SCHEDULER_OFFICIAL_ANSWER_CUTOFF
            or type(self.limit) is not int
            or self.limit != SCHEDULER_OFFICIAL_RETRIEVAL_LIMIT
            or type(self.records) is not tuple
            or not self.records
            or len(self.records) > self.answer_cutoff
            or type(self.result_count) is not int
            or not len(self.records) <= self.result_count <= self.limit
            or any(type(item) is not FreshChainMem0RetrievalRecord for item in self.records)
            or tuple(item.rank for item in self.records) != tuple(range(len(self.records)))
            or len({item.record_id for item in self.records}) != len(self.records)
        ):
            _fail("fresh_chain_mem0_retrieval_material_invalid")

    @classmethod
    def from_payload(cls, value: object) -> FreshChainMem0RetrievalMaterial:
        if type(value) is not dict or set(value) != {
            "admission_commitment_sha256",
            "answer_cutoff",
            "evidence_commitment_sha256",
            "limit",
            "query_commitment_sha256",
            "records",
            "result_count",
            "result_root_sha256",
        }:
            _fail("fresh_chain_mem0_retrieval_material_invalid")
        records = value["records"]
        if type(records) is not list:
            _fail("fresh_chain_mem0_retrieval_material_invalid")
        try:
            parsed = tuple(_record(item) for item in records)
            return cls(
                admission_commitment_sha256=value["admission_commitment_sha256"],
                answer_cutoff=value["answer_cutoff"],
                evidence_commitment_sha256=value["evidence_commitment_sha256"],
                limit=value["limit"],
                query_commitment_sha256=value["query_commitment_sha256"],
                records=parsed,
                result_count=value["result_count"],
                result_root_sha256=value["result_root_sha256"],
            )
        except FreshChainCanaryError:
            raise
        except (KeyError, TypeError, ValueError):
            _fail("fresh_chain_mem0_retrieval_material_invalid")

    def payload(self) -> dict[str, object]:
        return {
            "admission_commitment_sha256": self.admission_commitment_sha256,
            "answer_cutoff": self.answer_cutoff,
            "evidence_commitment_sha256": self.evidence_commitment_sha256,
            "limit": self.limit,
            "query_commitment_sha256": self.query_commitment_sha256,
            "records": [item.payload() for item in self.records],
            "result_count": self.result_count,
            "result_root_sha256": self.result_root_sha256,
        }

    def memories(self) -> tuple[RetrievedMemory, ...]:
        return tuple(item.memory_item() for item in self.records)


def _record(value: object) -> FreshChainMem0RetrievalRecord:
    if type(value) is not dict or set(value) != {
        "memory",
        "memory_sha256",
        "rank",
        "record_id",
        "score",
        "source_id",
        "source_sha256",
    }:
        _fail("fresh_chain_mem0_retrieval_material_invalid")
    try:
        return FreshChainMem0RetrievalRecord(**value)
    except (TypeError, ValueError):
        _fail("fresh_chain_mem0_retrieval_material_invalid")


def _identifier(value: object) -> bool:
    return bool(
        type(value) is str
        and 0 < len(value) <= 512
        and value == value.strip()
        and all(character.isalnum() or character in "._:-" for character in value)
    )


def _sha(value: object) -> bool:
    return bool(
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _fail(code: str) -> None:
    raise FreshChainCanaryError(code) from None


__all__ = (
    "FreshChainMem0RetrievalMaterial",
    "FreshChainMem0RetrievalRecord",
)

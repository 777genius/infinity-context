"""Provider-neutral authenticated evidence contracts for adapter v5."""

from __future__ import annotations

import hashlib
import hmac
import math
from dataclasses import dataclass

from mem0_oss_adapter_v5.domain import canonical_json_bytes, canonical_sha256, require_sha256

_SCHEMA_OBSERVATION = "mem0-oss-adapter-v5.storage-observation.v1"
_SCHEMA_SEARCH = "mem0-oss-adapter-v5.scoped-search.v1"
_KEY_DOMAIN = b"mem0-oss-adapter-v5/evidence-key/v1"
_OBSERVATION_DOMAIN = b"storage-observation/v1"
_SEARCH_DOMAIN = b"scoped-search/v1"
_MAX_MEMORY_CHARS = 16_384


@dataclass(frozen=True, slots=True)
class ExpectedMemoryCommitment:
    extraction_memory_id: str
    memory_sha256: str

    def __post_init__(self) -> None:
        _text(self.extraction_memory_id, maximum=512, code="mem0_v5_evidence_context_invalid")
        require_sha256(self.memory_sha256, "mem0_v5_evidence_context_invalid")


@dataclass(frozen=True, slots=True)
class EvidenceOperation:
    admission_commitment_sha256: str
    operation_id_sha256: str
    scope_sha256: str
    corpus_id: str
    source_id: str
    source_sha256: str
    expected_memories: tuple[ExpectedMemoryCommitment, ...]
    storage_commitment_sha256: str

    def __post_init__(self) -> None:
        for value in (
            self.admission_commitment_sha256,
            self.operation_id_sha256,
            self.scope_sha256,
            self.source_sha256,
            self.storage_commitment_sha256,
        ):
            require_sha256(value, "mem0_v5_evidence_context_invalid")
        for value in (self.corpus_id, self.source_id):
            _text(value, maximum=512, code="mem0_v5_evidence_context_invalid")
        if type(self.expected_memories) is not tuple or any(
            type(item) is not ExpectedMemoryCommitment for item in self.expected_memories
        ):
            raise ValueError("mem0_v5_evidence_context_invalid")
        ids = tuple(item.extraction_memory_id for item in self.expected_memories)
        if len(set(ids)) != len(ids):
            raise ValueError("mem0_v5_evidence_context_invalid")

    @property
    def expected_memory_sha256_by_id(self) -> dict[str, str]:
        return {item.extraction_memory_id: item.memory_sha256 for item in self.expected_memories}


@dataclass(frozen=True, slots=True)
class ObservedRecord:
    record_id: str
    extraction_memory_id: str
    source_id: str
    source_sha256: str
    memory_sha256: str

    def __post_init__(self) -> None:
        for value in (self.record_id, self.extraction_memory_id, self.source_id):
            _text(value, maximum=512, code="mem0_v5_storage_observation_invalid")
        require_sha256(self.source_sha256, "mem0_v5_storage_observation_invalid")
        require_sha256(self.memory_sha256, "mem0_v5_storage_observation_invalid")

    def public_payload(self) -> dict[str, object]:
        return {
            "record_id": self.record_id,
            "extraction_memory_id": self.extraction_memory_id,
            "source_id": self.source_id,
            "source_sha256": self.source_sha256,
            "memory_sha256": self.memory_sha256,
        }


@dataclass(frozen=True, slots=True)
class ObservedStorage:
    records: tuple[ObservedRecord, ...]
    storage_commitment_sha256: str

    def __post_init__(self) -> None:
        if type(self.records) is not tuple or any(
            type(item) is not ObservedRecord for item in self.records
        ):
            raise ValueError("mem0_v5_storage_observation_invalid")
        require_sha256(self.storage_commitment_sha256, "mem0_v5_storage_observation_invalid")


@dataclass(frozen=True, slots=True, repr=False)
class SearchRecord:
    record_id: str
    memory: str
    source_id: str
    source_sha256: str
    score: float

    def __post_init__(self) -> None:
        _text(self.record_id, maximum=512, code="mem0_v5_search_result_invalid")
        _text(self.memory, maximum=_MAX_MEMORY_CHARS, code="mem0_v5_search_result_invalid")
        _text(self.source_id, maximum=512, code="mem0_v5_search_result_invalid")
        require_sha256(self.source_sha256, "mem0_v5_search_result_invalid")
        if (
            type(self.score) is not float
            or not math.isfinite(self.score)
            or not 0.0 <= self.score <= 1.0
        ):
            raise ValueError("mem0_v5_search_result_invalid")

    @property
    def memory_sha256(self) -> str:
        return hashlib.sha256(self.memory.encode()).hexdigest()

    def public_payload(self, *, rank: int) -> dict[str, object]:
        if type(rank) is not int or rank < 0:
            raise ValueError("mem0_v5_search_result_invalid")
        return {
            "rank": rank,
            "record_id": self.record_id,
            "memory": self.memory,
            "memory_sha256": self.memory_sha256,
            "source_id": self.source_id,
            "source_sha256": self.source_sha256,
            "score": self.score,
        }

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(record_id={self.record_id!r}, "
            f"source_id={self.source_id!r}, memory_sha256={self.memory_sha256!r}, "
            f"score={self.score!r})"
        )


class EvidenceSigner:
    """Domain-separated HMAC authority for sanitized public evidence."""

    def __init__(self, master_key: bytes) -> None:
        if type(master_key) is not bytes or len(master_key) < 32:
            raise ValueError("adapter_configuration_invalid")
        root = hmac.new(master_key, _KEY_DOMAIN, hashlib.sha256).digest()
        self._observation_key = hmac.new(root, _OBSERVATION_DOMAIN, hashlib.sha256).digest()
        self._search_key = hmac.new(root, _SEARCH_DOMAIN, hashlib.sha256).digest()

    def storage_observation(
        self,
        *,
        operation: EvidenceOperation,
        observation: ObservedStorage,
    ) -> dict[str, object]:
        ordered = tuple(sorted(observation.records, key=lambda item: item.record_id))
        if len({item.record_id for item in ordered}) != len(ordered):
            raise ValueError("mem0_v5_storage_observation_invalid")
        actual = {item.extraction_memory_id: item.memory_sha256 for item in ordered}
        if (
            len(actual) != len(ordered)
            or actual != operation.expected_memory_sha256_by_id
            or observation.storage_commitment_sha256 != operation.storage_commitment_sha256
        ):
            raise ValueError("mem0_v5_storage_observation_invalid")
        for item in ordered:
            if (
                item.source_id != operation.source_id
                or item.source_sha256 != operation.source_sha256
            ):
                raise ValueError("mem0_v5_storage_observation_invalid")
        public_records = tuple(item.public_payload() for item in ordered)
        unsigned = {
            "schema_version": _SCHEMA_OBSERVATION,
            "admission_commitment_sha256": operation.admission_commitment_sha256,
            "operation_id_sha256": operation.operation_id_sha256,
            "scope_sha256": operation.scope_sha256,
            "source_id": operation.source_id,
            "source_sha256": operation.source_sha256,
            "storage_commitment_sha256": observation.storage_commitment_sha256,
            "record_count": len(public_records),
            "record_root_sha256": canonical_sha256({"records": public_records}),
            "records": public_records,
        }
        return {**unsigned, "observation_hmac_sha256": _signature(self._observation_key, unsigned)}

    def scoped_search(
        self,
        *,
        admission_commitment_sha256: str,
        corpus_id: str,
        query: str,
        limit: int,
        results: tuple[SearchRecord, ...],
    ) -> dict[str, object]:
        require_sha256(admission_commitment_sha256, "mem0_v5_search_result_invalid")
        _text(corpus_id, maximum=512, code="mem0_v5_search_result_invalid")
        _text(query, maximum=_MAX_MEMORY_CHARS, code="mem0_v5_search_request_invalid")
        if type(limit) is not int or not 1 <= limit <= 200 or len(results) > limit:
            raise ValueError("mem0_v5_search_result_invalid")
        ordered = tuple(sorted(results, key=lambda item: (-item.score, item.record_id)))
        if len({item.record_id for item in ordered}) != len(ordered):
            raise ValueError("mem0_v5_search_result_invalid")
        public_results = tuple(item.public_payload(rank=rank) for rank, item in enumerate(ordered))
        unsigned = {
            "schema_version": _SCHEMA_SEARCH,
            "admission_commitment_sha256": admission_commitment_sha256,
            "corpus_id": corpus_id,
            "query_commitment_sha256": canonical_sha256({"query": query}),
            "limit": limit,
            "result_count": len(public_results),
            "result_root_sha256": canonical_sha256({"results": public_results}),
            "results": public_results,
        }
        return {**unsigned, "search_hmac_sha256": _signature(self._search_key, unsigned)}


def _signature(key: bytes, payload: dict[str, object]) -> str:
    return hmac.new(key, canonical_json_bytes(payload), hashlib.sha256).hexdigest()


def _text(value: object, *, maximum: int, code: str) -> str:
    if type(value) is not str or not value or value != value.strip() or len(value) > maximum:
        raise ValueError(code)
    return value


__all__ = (
    "EvidenceOperation",
    "EvidenceSigner",
    "ExpectedMemoryCommitment",
    "ObservedRecord",
    "ObservedStorage",
    "SearchRecord",
)

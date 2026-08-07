from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import replace

import pytest
from pydantic import ValidationError

from mem0_oss_adapter_v5.app import AdapterServiceError
from mem0_oss_adapter_v5.domain import canonical_sha256
from mem0_oss_adapter_v5.evidence_contracts import EvidenceOperation, ExpectedMemoryCommitment
from mem0_oss_adapter_v5.evidence_service import AuthenticatedEvidenceService
from mem0_oss_adapter_v5.http_models import (
    ScopedSearchRequest,
    StorageObservationRequest,
)
from mem0_oss_adapter_v5.mem0_storage import (
    Mem0EvidenceStorage,
    PinnedMem0Backend,
    StorageMemory,
    StorageScope,
    independent_snapshot,
)

_ADMISSION = hashlib.sha256(b"admission").hexdigest()
_OPERATION = hashlib.sha256(b"operation").hexdigest()
_SCOPE = hashlib.sha256(b"scope").hexdigest()
_SOURCE_SHA = hashlib.sha256(b"source").hexdigest()
_KEY = b"evidence-test-key" * 4


class FakeEvidenceBackend:
    def __init__(self) -> None:
        self.vectors: list[dict[str, object]] = []
        self.search_rows: list[dict[str, object]] = []
        self.search_calls: list[tuple[str, dict[str, str], int]] = []
        self.list_calls: list[dict[str, str]] = []

    def add_raw(self, *, scope: StorageScope, memory: StorageMemory) -> str:
        raise AssertionError("provider write is forbidden in evidence tests")

    def list_vectors(self, *, filters, limit: int):
        assert limit == 10_000
        self.list_calls.append(dict(filters))
        return [
            row
            for row in self.vectors
            if all(row["payload"].get(key) == value for key, value in filters.items())
        ]

    def history_memory_ids(self, *, provider_memory_ids):
        return tuple(sorted(provider_memory_ids))

    def message_ids(self, *, scope: StorageScope):
        return ()

    def entity_links(self, *, scope: StorageScope):
        return ()

    def delete_memory(self, provider_memory_id: str) -> None:
        self.vectors = [row for row in self.vectors if row["id"] != provider_memory_id]

    def delete_history(self, provider_memory_ids) -> None:
        pass

    def delete_messages(self, *, scope: StorageScope) -> None:
        pass

    def delete_entity_links(self, *, scope: StorageScope) -> None:
        pass

    def search_vectors(self, *, query: str, filters, limit: int):
        exact = dict(filters)
        self.search_calls.append((query, exact, limit))
        return self.search_rows[:limit]


class FakeContext:
    def __init__(self, operations: tuple[EvidenceOperation, ...]) -> None:
        self.operations = operations
        self.cleaned = False

    def committed_operation(
        self, *, admission_commitment_sha256: str, operation_id_sha256: str
    ) -> EvidenceOperation:
        if self.cleaned:
            raise AdapterServiceError("operation_cleaned", status_code=410)
        if admission_commitment_sha256 != _ADMISSION:
            raise AdapterServiceError("run_not_found", status_code=404)
        for operation in self.operations:
            if operation.operation_id_sha256 == operation_id_sha256:
                return operation
        raise AdapterServiceError("operation_not_found", status_code=404)

    def committed_corpus(
        self, *, admission_commitment_sha256: str, corpus_id: str
    ) -> tuple[EvidenceOperation, ...]:
        if self.cleaned:
            raise AdapterServiceError("operation_cleaned", status_code=410)
        if admission_commitment_sha256 != _ADMISSION:
            raise AdapterServiceError("run_not_found", status_code=404)
        values = tuple(item for item in self.operations if item.corpus_id == corpus_id)
        if not values:
            raise AdapterServiceError("corpus_not_found", status_code=404)
        return values


class _PinnedSearchMemory:
    def __init__(self) -> None:
        self.vector_store = object()
        self.entity_store = object()
        self.db = object()
        self.calls: list[tuple[str, dict[str, object]]] = []

    def add(self):
        raise AssertionError("not used")

    def delete(self):
        raise AssertionError("not used")

    def search(self, query: str, **kwargs):
        self.calls.append((query, kwargs))
        return {"results": []}


def _operation(*, memory_ids: tuple[str, ...] = ("0", "1")) -> EvidenceOperation:
    return EvidenceOperation(
        admission_commitment_sha256=_ADMISSION,
        operation_id_sha256=_OPERATION,
        scope_sha256=_SCOPE,
        corpus_id="corpus-1",
        source_id="source-1",
        source_sha256=_SOURCE_SHA,
        expected_memories=tuple(
            ExpectedMemoryCommitment(
                extraction_memory_id=value,
                memory_sha256=hashlib.sha256(f"memory {value}".encode()).hexdigest(),
            )
            for value in memory_ids
        ),
        storage_commitment_sha256=hashlib.sha256(b"unbound-storage").hexdigest(),
    )


def _vector(record_id: str, extraction_id: str) -> dict[str, object]:
    return {
        "id": record_id,
        "payload": {
            "user_id": "corpus-1",
            "run_id": _ADMISSION,
            "source_id": "source-1",
            "source_sha256": _SOURCE_SHA,
            "extraction_memory_id": extraction_id,
            "memory": "memory " + extraction_id,
            "attributed_to": "user",
            "linked_memory_ids": [],
        },
    }


def _operation_for(index: int) -> EvidenceOperation:
    return EvidenceOperation(
        admission_commitment_sha256=_ADMISSION,
        operation_id_sha256=hashlib.sha256(f"operation-{index}".encode()).hexdigest(),
        scope_sha256=hashlib.sha256(f"scope-{index}".encode()).hexdigest(),
        corpus_id="corpus-1",
        source_id=f"source-{index}",
        source_sha256=hashlib.sha256(f"source-{index}".encode()).hexdigest(),
        expected_memories=(
            ExpectedMemoryCommitment(
                extraction_memory_id=str(index),
                memory_sha256=hashlib.sha256(f"memory {index}".encode()).hexdigest(),
            ),
        ),
        storage_commitment_sha256=hashlib.sha256(b"unbound-storage").hexdigest(),
    )


def _vector_for(operation: EvidenceOperation, index: int) -> dict[str, object]:
    return {
        "id": f"provider-{index}",
        "payload": {
            "user_id": operation.corpus_id,
            "run_id": operation.admission_commitment_sha256,
            "source_id": operation.source_id,
            "source_sha256": operation.source_sha256,
            "extraction_memory_id": str(index),
            "memory": f"memory {index}",
            "attributed_to": "user",
            "linked_memory_ids": [],
        },
    }


def _search_row(
    record_id: str,
    *,
    score: object = 0.75,
    run_id: str = _ADMISSION,
    source_id: str = "source-1",
    memory: str = "memory 0",
) -> dict[str, object]:
    return {
        "id": record_id,
        "memory": memory,
        "score": score,
        "user_id": "corpus-1",
        "run_id": run_id,
        "metadata": {
            "source_id": source_id,
            "source_sha256": _SOURCE_SHA,
        },
    }


def _bind_storage(backend: FakeEvidenceBackend, operation: EvidenceOperation) -> EvidenceOperation:
    snapshot = independent_snapshot(
        backend,
        scope=StorageScope(
            user_id=operation.corpus_id,
            run_id=operation.admission_commitment_sha256,
            source_id=operation.source_id,
            source_sha256=operation.source_sha256,
        ),
    )
    return replace(operation, storage_commitment_sha256=snapshot.commitment_sha256)


def _service(
    backend: FakeEvidenceBackend,
    operation: EvidenceOperation,
) -> tuple[AuthenticatedEvidenceService, FakeContext]:
    context = FakeContext((_bind_storage(backend, operation),))
    backend.list_calls.clear()
    return (
        AuthenticatedEvidenceService(
            context=context,
            storage=Mem0EvidenceStorage(backend),
            hmac_key=_KEY,
        ),
        context,
    )


def _valid_hmac(payload: dict[str, object], *, domain: bytes, field: str) -> bool:
    root = hmac.new(_KEY, b"mem0-oss-adapter-v5/evidence-key/v1", hashlib.sha256).digest()
    key = hmac.new(root, domain, hashlib.sha256).digest()
    signature = payload.pop(field)
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hmac.compare_digest(str(signature), hmac.new(key, encoded, hashlib.sha256).hexdigest())


def test_storage_observation_maps_exact_provider_ids_and_authenticates_ordered_inventory() -> None:
    backend = FakeEvidenceBackend()
    backend.vectors = [_vector("provider-b", "1"), _vector("provider-a", "0")]
    service, _ = _service(backend, _operation())

    response = service.storage_observation(
        StorageObservationRequest(
            admission_commitment_sha256=_ADMISSION,
            operation_id_sha256=_OPERATION,
        ),
        idempotency_key=hashlib.sha256(b"idem").hexdigest(),
    )

    payload = response.model_dump(mode="json")
    records = payload["records"]
    assert [item["record_id"] for item in records] == ["provider-a", "provider-b"]
    assert all(
        item["source_id"] == "source-1" and item["source_sha256"] == _SOURCE_SHA for item in records
    )
    assert payload["record_root_sha256"] == canonical_sha256({"records": records})
    assert _valid_hmac(
        payload,
        domain=b"storage-observation/v1",
        field="observation_hmac_sha256",
    )


@pytest.mark.parametrize("field", ["record_count", "record_root_sha256", "source_sha256"])
def test_storage_observation_hmac_rejects_count_root_and_source_tamper(field: str) -> None:
    backend = FakeEvidenceBackend()
    backend.vectors = [_vector("provider-a", "0")]
    service, _ = _service(backend, _operation(memory_ids=("0",)))
    payload = service.storage_observation(
        StorageObservationRequest(
            admission_commitment_sha256=_ADMISSION,
            operation_id_sha256=_OPERATION,
        ),
        idempotency_key=hashlib.sha256(b"idem").hexdigest(),
    ).model_dump(mode="json")
    payload[field] = 99 if field == "record_count" else hashlib.sha256(b"tamper").hexdigest()
    assert not _valid_hmac(
        payload,
        domain=b"storage-observation/v1",
        field="observation_hmac_sha256",
    )


def test_zero_extraction_observation_has_no_synthetic_record_identity() -> None:
    backend = FakeEvidenceBackend()
    service, _ = _service(backend, _operation(memory_ids=()))
    response = service.storage_observation(
        StorageObservationRequest(
            admission_commitment_sha256=_ADMISSION,
            operation_id_sha256=_OPERATION,
        ),
        idempotency_key=hashlib.sha256(b"idem").hexdigest(),
    )
    assert response.record_count == 0
    assert response.records == ()
    assert response.record_root_sha256 == canonical_sha256({"records": []})


def test_scoped_search_binds_exact_run_corpus_ranking_query_and_source_inventory() -> None:
    backend = FakeEvidenceBackend()
    backend.vectors = [_vector("provider-a", "0"), _vector("provider-b", "1")]
    backend.search_rows = [
        _search_row("provider-b", score=0.9, memory="memory 1"),
        _search_row("provider-a", score=0.5),
    ]
    service, _ = _service(backend, _operation())
    query = "private benchmark query"

    response = service.scoped_search(
        ScopedSearchRequest(
            admission_commitment_sha256=_ADMISSION,
            corpus_id="corpus-1",
            query=query,
            limit=2,
        ),
        idempotency_key=hashlib.sha256(b"idem").hexdigest(),
    )

    payload = response.model_dump(mode="json")
    assert query not in json.dumps(payload)
    assert backend.search_calls == [(query, {"user_id": "corpus-1", "run_id": _ADMISSION}, 2)]
    assert [item["record_id"] for item in payload["results"]] == [
        "provider-b",
        "provider-a",
    ]
    assert [item["rank"] for item in payload["results"]] == [0, 1]
    assert payload["query_commitment_sha256"] == canonical_sha256({"query": query})
    assert payload["result_root_sha256"] == canonical_sha256({"results": payload["results"]})
    assert _valid_hmac(payload, domain=b"scoped-search/v1", field="search_hmac_sha256")


def test_empty_search_is_valid_and_has_canonical_ordered_root() -> None:
    backend = FakeEvidenceBackend()
    service, _ = _service(backend, _operation(memory_ids=()))
    response = service.scoped_search(
        ScopedSearchRequest(
            admission_commitment_sha256=_ADMISSION,
            corpus_id="corpus-1",
            query="query",
            limit=1,
        ),
        idempotency_key=hashlib.sha256(b"idem").hexdigest(),
    )
    assert response.result_count == 0
    assert response.results == ()
    assert response.result_root_sha256 == canonical_sha256({"results": []})


@pytest.mark.parametrize(
    "row",
    [
        _search_row("unknown"),
        _search_row("provider-a", run_id=hashlib.sha256(b"other-run").hexdigest()),
        _search_row("provider-a", source_id="other-source"),
        _search_row("provider-a", score=float("nan")),
        _search_row("provider-a", score=True),
        _search_row("provider-a", score=1.01),
        _search_row("provider-a", memory="altered memory"),
    ],
)
def test_search_fails_closed_for_unknown_cross_scope_or_invalid_score(row) -> None:
    backend = FakeEvidenceBackend()
    backend.vectors = [_vector("provider-a", "0")]
    backend.search_rows = [row]
    service, _ = _service(backend, _operation(memory_ids=("0",)))
    with pytest.raises(AdapterServiceError, match="storage_verification_failed"):
        service.scoped_search(
            ScopedSearchRequest(
                admission_commitment_sha256=_ADMISSION,
                corpus_id="corpus-1",
                query="query",
                limit=1,
            ),
            idempotency_key=hashlib.sha256(b"idem").hexdigest(),
        )


def test_search_request_bounds_and_strict_types() -> None:
    base = {
        "admission_commitment_sha256": _ADMISSION,
        "corpus_id": "corpus-1",
        "query": "query",
        "limit": 1,
    }
    for invalid in (
        {**base, "limit": 0},
        {**base, "limit": 201},
        {**base, "limit": True},
        {**base, "query": " query"},
        {**base, "query": "x" * 16_385},
        {**base, "corpus_id": " corpus-1"},
    ):
        with pytest.raises(ValidationError):
            ScopedSearchRequest.model_validate(invalid)


def test_cleaned_context_blocks_readback_and_search_even_if_storage_resurrects() -> None:
    backend = FakeEvidenceBackend()
    backend.vectors = [_vector("provider-a", "0")]
    backend.search_rows = [_search_row("provider-a")]
    service, context = _service(backend, _operation(memory_ids=("0",)))
    context.cleaned = True
    with pytest.raises(AdapterServiceError, match="operation_cleaned") as observation:
        service.storage_observation(
            StorageObservationRequest(
                admission_commitment_sha256=_ADMISSION,
                operation_id_sha256=_OPERATION,
            ),
            idempotency_key=hashlib.sha256(b"idem").hexdigest(),
        )
    assert observation.value.status_code == 410
    with pytest.raises(AdapterServiceError, match="operation_cleaned"):
        service.scoped_search(
            ScopedSearchRequest(
                admission_commitment_sha256=_ADMISSION,
                corpus_id="corpus-1",
                query="query",
                limit=1,
            ),
            idempotency_key=hashlib.sha256(b"idem").hexdigest(),
        )
    assert backend.search_calls == []


def test_many_unit_corpus_uses_one_inventory_read_and_one_search() -> None:
    operations = tuple(_operation_for(index) for index in range(64))
    backend = FakeEvidenceBackend()
    backend.vectors = [_vector_for(operation, index) for index, operation in enumerate(operations)]
    operations = tuple(_bind_storage(backend, operation) for operation in operations)
    backend.list_calls.clear()
    backend.search_rows = [
        {
            "id": "provider-63",
            "memory": "memory 63",
            "score": 0.9,
            "user_id": "corpus-1",
            "run_id": _ADMISSION,
            "metadata": {
                "source_id": "source-63",
                "source_sha256": operations[63].source_sha256,
            },
        }
    ]
    service = AuthenticatedEvidenceService(
        context=FakeContext(operations),
        storage=Mem0EvidenceStorage(backend),
        hmac_key=_KEY,
    )

    response = service.scoped_search(
        ScopedSearchRequest(
            admission_commitment_sha256=_ADMISSION,
            corpus_id="corpus-1",
            query="query",
            limit=10,
        ),
        idempotency_key=hashlib.sha256(b"idem").hexdigest(),
    )

    assert response.result_count == 1
    assert backend.list_calls == [{"user_id": "corpus-1", "run_id": _ADMISSION}]
    assert len(backend.search_calls) == 1


def test_pinned_mem0_search_uses_v2015_exact_filter_and_bound_surface() -> None:
    memory = _PinnedSearchMemory()
    backend = PinnedMem0Backend(memory)

    assert (
        backend.search_vectors(
            query="query",
            filters={"user_id": "corpus-1", "run_id": _ADMISSION},
            limit=17,
        )
        == []
    )
    assert memory.calls == [
        (
            "query",
            {
                "top_k": 17,
                "filters": {"user_id": "corpus-1", "run_id": _ADMISSION},
                "threshold": 0.0,
                "rerank": False,
                "explain": False,
            },
        )
    ]


def test_storage_observation_rejects_post_commit_memory_mutation() -> None:
    backend = FakeEvidenceBackend()
    backend.vectors = [_vector("provider-a", "0")]
    service, _ = _service(backend, _operation(memory_ids=("0",)))
    backend.vectors[0]["payload"]["memory"] = "mutated memory"
    with pytest.raises(AdapterServiceError, match="storage_verification_failed"):
        service.storage_observation(
            StorageObservationRequest(
                admission_commitment_sha256=_ADMISSION,
                operation_id_sha256=_OPERATION,
            ),
            idempotency_key=hashlib.sha256(b"mutation").hexdigest(),
        )


def test_corpus_batch_rejects_mutated_memory_before_search() -> None:
    backend = FakeEvidenceBackend()
    backend.vectors = [_vector("provider-a", "0")]
    backend.search_rows = [_search_row("provider-a", memory="mutated memory")]
    service, _ = _service(backend, _operation(memory_ids=("0",)))
    backend.vectors[0]["payload"]["memory"] = "mutated memory"
    with pytest.raises(AdapterServiceError, match="storage_verification_failed"):
        service.scoped_search(
            ScopedSearchRequest(
                admission_commitment_sha256=_ADMISSION,
                corpus_id="corpus-1",
                query="query",
                limit=1,
            ),
            idempotency_key=hashlib.sha256(b"mutation-search").hexdigest(),
        )
    assert backend.search_calls == []


def test_search_equal_scores_are_ordered_by_record_id_within_returned_set() -> None:
    backend = FakeEvidenceBackend()
    backend.vectors = [_vector("provider-b", "1"), _vector("provider-a", "0")]
    backend.search_rows = [
        _search_row("provider-b", score=0.75, memory="memory 1"),
        _search_row("provider-a", score=0.75, memory="memory 0"),
    ]
    service, _ = _service(backend, _operation())
    response = service.scoped_search(
        ScopedSearchRequest(
            admission_commitment_sha256=_ADMISSION,
            corpus_id="corpus-1",
            query="query",
            limit=2,
        ),
        idempotency_key=hashlib.sha256(b"ties").hexdigest(),
    )
    assert [item.record_id for item in response.results] == ["provider-a", "provider-b"]
    assert [item.rank for item in response.results] == [0, 1]


def test_storage_public_hmac_binds_memory_and_storage_commitments() -> None:
    backend = FakeEvidenceBackend()
    backend.vectors = [_vector("provider-a", "0")]
    service, _ = _service(backend, _operation(memory_ids=("0",)))
    payload = service.storage_observation(
        StorageObservationRequest(
            admission_commitment_sha256=_ADMISSION,
            operation_id_sha256=_OPERATION,
        ),
        idempotency_key=hashlib.sha256(b"public-bindings").hexdigest(),
    ).model_dump(mode="json")
    assert payload["records"][0]["memory_sha256"] == hashlib.sha256(b"memory 0").hexdigest()
    assert payload["storage_commitment_sha256"]
    tampered = dict(payload)
    tampered["storage_commitment_sha256"] = hashlib.sha256(b"tamper").hexdigest()
    assert not _valid_hmac(
        tampered,
        domain=b"storage-observation/v1",
        field="observation_hmac_sha256",
    )

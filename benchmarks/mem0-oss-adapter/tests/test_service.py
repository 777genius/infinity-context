from __future__ import annotations

import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from mem0_oss_adapter.models import AddRequest, SearchRequest
from mem0_oss_adapter.service import AdapterError, OssCompatibilityService

from .conftest import FakeOssPort


def _add_request(
    *,
    source_id: str = "source-1",
    source_sha256: str = "a" * 64,
    content: str = "remember this exact source",
) -> AddRequest:
    return AddRequest(
        messages=[{"role": "user", "content": content}],
        user_id="user-1",
        run_id="run-1",
        metadata={"source_id": source_id, "source_sha256": source_sha256},
        timestamp=1_672_531_200,
    )


def test_add_proves_source_identity_and_wrapper_created_at() -> None:
    port = FakeOssPort()
    service = OssCompatibilityService(port)

    proof = service.add(_add_request())

    assert proof.request_id == "memory-1"
    assert [(item.memory_id, item.source_id, item.source_sha256) for item in proof.results] == [
        ("memory-1", "source-1", "a" * 64)
    ]
    assert port.add_calls[0]["mode_override"] is None


def test_add_rejects_missing_or_mutated_persisted_source_identity() -> None:
    class MutatingPort(FakeOssPort):
        def get_all(self, **kwargs: object):
            payload = super().get_all(**kwargs)
            if payload["results"]:
                row = payload["results"][0]
                payload["results"][0] = {**row, "metadata": dict(row["metadata"])}
                payload["results"][0]["metadata"]["source_sha256"] = "b" * 64
            return payload

    with pytest.raises(AdapterError, match="source identity"):
        OssCompatibilityService(MutatingPort()).add(_add_request())


def test_delete_requires_verified_absence() -> None:
    port = FakeOssPort()
    service = OssCompatibilityService(port)
    service.add(_add_request())

    proof = service.delete(user_id="user-1", run_id="run-1")

    assert proof.deleted is True
    assert proof.verified_absent is True


def test_search_returns_only_bounded_public_fields() -> None:
    port = FakeOssPort()
    service = OssCompatibilityService(port)
    service.add(_add_request())
    port.rows[0]["api_key"] = "secret"
    port.rows[0]["metadata"]["secret"] = "secret"

    result = service.search(
        SearchRequest(
            query="source",
            filters={"user_id": "user-1", "run_id": "run-1"},
            limit=10,
            top_k=10,
        )
    )

    assert result == [
        {
            "id": "memory-1",
            "memory": "remember this exact source",
            "created_at": "2023-01-01T00:00:00Z",
            "metadata": {
                "source_id": "source-1",
                "source_sha256": "a" * 64,
            },
        }
    ]


def test_timestamp_attestation_is_raw_and_cleans_up() -> None:
    port = FakeOssPort()
    service = OssCompatibilityService(port, token_factory=lambda: "a" * 24)

    attestation = service.attest_timestamp()

    assert attestation.status == "passed"
    assert attestation.metadata_created_at_roundtrip_attested is True
    assert attestation.cleanup_succeeded is True
    assert port.add_calls[0]["mode_override"] == "raw_passthrough"
    assert port.rows == []


def test_unconfigured_service_is_a_sanitized_503() -> None:
    with pytest.raises(AdapterError) as raised:
        OssCompatibilityService(FakeOssPort(configured=False)).add(_add_request())

    assert raised.value.status_code == 503
    assert raised.value.code == "missing_mem0_oss_runtime_configuration"


def test_request_rejects_client_supplied_manifest_field() -> None:
    payload = _add_request().model_dump()
    payload["manifest"] = {"quality_score": 1}

    with pytest.raises(ValueError):
        AddRequest.model_validate(payload)


@pytest.mark.parametrize(
    "filters",
    (
        {"user_id": "user-1"},
        {"run_id": "run-1"},
        {"AND": [{"user_id": "user-1"}, {"run_id": "run-1"}]},
        {"user_id": "user-1", "run_id": "run-1", "OR": []},
    ),
)
def test_search_rejects_any_scope_that_is_not_exactly_bound_to_one_run(
    filters: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        SearchRequest(query="source", filters=filters, limit=10, top_k=10)


def test_add_rejects_a_reused_source_before_writing_another_memory() -> None:
    port = FakeOssPort()
    service = OssCompatibilityService(port)
    service.add(_add_request())

    with pytest.raises(AdapterError, match="already present"):
        service.add(_add_request())

    assert len(port.add_calls) == 1
    assert len(port.rows) == 1


def test_partial_readback_is_rejected_and_the_exact_source_is_compensated() -> None:
    class TruncatingPort(FakeOssPort):
        def add(self, **kwargs: object):
            payload = super().add(**kwargs)
            second = {
                **self.rows[-1],
                "id": "memory-2",
                "metadata": dict(self.rows[-1]["metadata"]),
            }
            self.rows.append(second)
            return {"id": payload["id"], "results": [{"id": "memory-1"}, {"id": "memory-2"}]}

        def get_all(self, **kwargs: object):
            payload = super().get_all(**kwargs)
            filters = kwargs["filters"]
            if "source_id" in filters and len(payload["results"]) > 1:
                payload["results"] = payload["results"][:1]
            return payload

    request = _add_request().model_copy(
        update={
            "messages": [
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": "second"},
            ]
        }
    )
    port = TruncatingPort()

    with pytest.raises(AdapterError, match="source readback"):
        OssCompatibilityService(port).add(request)

    assert port.rows == []


def test_failed_compensation_fails_closed() -> None:
    class NonDeletingPort(FakeOssPort):
        def get_all(self, **kwargs: object):
            payload = super().get_all(**kwargs)
            if "source_id" in kwargs["filters"] and payload["results"]:
                row = payload["results"][0]
                payload["results"][0] = {**row, "metadata": dict(row["metadata"])}
                payload["results"][0]["metadata"]["source_sha256"] = "b" * 64
            return payload

        def delete_source_memories(self, **kwargs: object) -> bool:
            del kwargs
            return True

    port = NonDeletingPort()

    with pytest.raises(AdapterError, match="post-write rollback"):
        OssCompatibilityService(port).add(_add_request())

    assert len(port.rows) == 1


def test_provider_exception_compensates_partial_source_and_preserves_prior_source() -> None:
    class PartialFailurePort(FakeOssPort):
        fail_after_write = False

        def add(self, **kwargs: object):
            payload = super().add(**kwargs)
            if self.fail_after_write:
                raise RuntimeError("provider failed after persistence")
            return payload

    port = PartialFailurePort()
    service = OssCompatibilityService(port)
    service.add(_add_request())
    port.fail_after_write = True

    with pytest.raises(AdapterError, match="add or source readback"):
        service.add(
            _add_request(
                source_id="source-2",
                source_sha256="b" * 64,
                content="partially persisted source",
            )
        )

    assert [(row["id"], row["metadata"]["source_id"]) for row in port.rows] == [
        ("memory-1", "source-1")
    ]


def test_proof_failure_compensates_only_target_source_and_preserves_prior_source() -> None:
    class ProofFailurePort(FakeOssPort):
        corrupt_source_id: str | None = None

        def get_all(self, **kwargs: object):
            payload = super().get_all(**kwargs)
            filters = kwargs["filters"]
            if filters.get("source_id") == self.corrupt_source_id and payload["results"]:
                row = payload["results"][0]
                payload["results"][0] = {**row, "metadata": dict(row["metadata"])}
                payload["results"][0]["metadata"]["source_sha256"] = "c" * 64
            return payload

    port = ProofFailurePort()
    service = OssCompatibilityService(port)
    service.add(_add_request())
    port.corrupt_source_id = "source-2"

    with pytest.raises(AdapterError, match="source identity"):
        service.add(
            _add_request(
                source_id="source-2",
                source_sha256="b" * 64,
                content="bad proof source",
            )
        )

    assert [(row["id"], row["metadata"]["source_id"]) for row in port.rows] == [
        ("memory-1", "source-1")
    ]


def test_concurrent_same_source_retry_is_serialized_and_preserves_success() -> None:
    first_add_entered = threading.Event()
    release_first_add = threading.Event()
    second_attempt_started = threading.Event()
    second_preflight_seen = threading.Event()

    class BlockingPort(FakeOssPort):
        preflight_calls = 0

        def get_all(self, **kwargs: object):
            if "source_id" in kwargs["filters"]:
                self.preflight_calls += 1
                if self.preflight_calls == 2:
                    second_preflight_seen.set()
            return super().get_all(**kwargs)

        def add(self, **kwargs: object):
            first_add_entered.set()
            if not release_first_add.wait(timeout=2):
                raise RuntimeError("test did not release the first add")
            return super().add(**kwargs)

    port = BlockingPort()
    service = OssCompatibilityService(port)

    def retry() -> object:
        second_attempt_started.set()
        return service.add(_add_request())

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(service.add, _add_request())
        assert first_add_entered.wait(timeout=1)
        second = executor.submit(retry)
        assert second_attempt_started.wait(timeout=1)
        assert not second_preflight_seen.wait(timeout=0.1)
        release_first_add.set()

        assert first.result(timeout=2).request_id == "memory-1"
        with pytest.raises(AdapterError, match="already present"):
            second.result(timeout=2)

    assert len(port.add_calls) == 1
    assert [(row["id"], row["metadata"]["source_id"]) for row in port.rows] == [
        ("memory-1", "source-1")
    ]


def test_source_hash_fixture_is_not_the_attestation_sentinel_hash() -> None:
    assert hashlib.sha256(b"Mem0 OSS timestamp attestation sentinel.").hexdigest() != "a" * 64

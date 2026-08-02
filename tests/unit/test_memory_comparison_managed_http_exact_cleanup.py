from __future__ import annotations

import copy
from dataclasses import replace

import httpx
import pytest
from infinity_context_core.ports.derived_projection_policy import (
    DerivedProjectionLaneDisposition,
    derived_not_projected_policy_sha256,
)
from infinity_context_server.memory_comparison_managed_http_derived_evidence import (
    ManagedDerivedEvidenceHttpClient,
)
from infinity_context_server.memory_comparison_managed_http_exact_cleanup import (
    ManagedExactCleanupError,
    ManagedInfinityExactCleanupCoordinator,
)
from infinity_context_server.memory_comparison_managed_http_execution import (
    ManagedInfinityHttpConfig,
)
from infinity_context_server.memory_comparison_managed_http_policy_requirements import (
    ManagedCanonicalProjectionScope,
    ManagedDerivedPresenceObservation,
    ManagedGraphitiIdentitySnapshot,
    ManagedGraphitiPresenceObservation,
    ManagedIngestIdentityManifest,
    ManagedProjectionOutboxObservation,
    ManagedQdrantPointIdentity,
    ManagedQdrantPresenceObservation,
    managed_ingest_identity_manifest_sha256,
)
from infinity_context_server.memory_comparison_managed_preflight import (
    managed_backend_target_identity_sha256,
)

_BASE_URL = "https://infinity.example/api"
_TARGET = managed_backend_target_identity_sha256(
    backend_role="infinity-context",
    base_url=_BASE_URL,
)
_TOKEN = "cleanup-secret-must-never-leak"
_QDRANT_TARGET = "1" * 64
_QDRANT_BINDING = "2" * 64
_GRAPH_TARGET = "3" * 64
_GRAPH_BINDING = "4" * 64


class _TrackingTransport(httpx.MockTransport):
    def __init__(self, handler) -> None:
        super().__init__(handler)
        self.closed = False

    def close(self) -> None:
        self.closed = True
        super().close()


def _scope() -> ManagedCanonicalProjectionScope:
    return ManagedCanonicalProjectionScope("space-1", "scope-1", "thread-1")


def _manifest(
    *,
    facts: tuple[str, ...] = ("fact-1",),
    documents: tuple[str, ...] = ("document-1",),
    chunks: tuple[str, ...] = ("chunk-1",),
) -> ManagedIngestIdentityManifest:
    return ManagedIngestIdentityManifest(
        corpus_id="corpus-1",
        infinity_fact_ids=facts,
        infinity_document_ids=documents,
        infinity_chunk_ids=chunks,
        infinity_source_ids=("source-1",),
        infinity_source_sha256=("5" * 64,),
        mem0_created_memory_ids=("memory-1",),
        mem0_source_ids=("mem0-source-1",),
        mem0_source_sha256=("6" * 64,),
        operation_count=2,
        complete=True,
        issues=(),
    )


def _graph_snapshot() -> ManagedGraphitiIdentitySnapshot:
    return ManagedGraphitiIdentitySnapshot(("episode-1",), (), (), ())


def _presence(
    manifest: ManagedIngestIdentityManifest,
    *,
    target: str = _TARGET,
) -> ManagedDerivedPresenceObservation:
    point = ManagedQdrantPointIdentity("chunk-1", "point-1")
    qdrant = (
        ManagedQdrantPresenceObservation(
            "v1",
            _QDRANT_TARGET,
            _QDRANT_BINDING,
            (point,),
            (point,),
            ("point-1",),
            1,
            True,
        )
        if manifest.infinity_chunk_ids
        else None
    )
    graphiti = (
        ManagedGraphitiPresenceObservation(
            _scope(),
            _GRAPH_TARGET,
            _GRAPH_BINDING,
            _graph_snapshot(),
            1,
            True,
        )
        if manifest.infinity_fact_ids
        else None
    )
    return ManagedDerivedPresenceObservation(
        target,
        managed_ingest_identity_manifest_sha256(manifest, _scope()),
        _scope(),
        ManagedProjectionOutboxObservation(
            manifest.infinity_chunk_ids,
            manifest.infinity_fact_ids,
            len(manifest.infinity_chunk_ids) + len(manifest.infinity_fact_ids),
            True,
        ),
        qdrant,
        graphiti,
    )


def _snapshot_json(value: ManagedGraphitiIdentitySnapshot) -> dict[str, object]:
    return {
        "episode_ids": list(value.episode_ids),
        "entity_ids": list(value.entity_ids),
        "mentions_edge_ids": list(value.mentions_edge_ids),
        "relates_to_edge_ids": list(value.relates_to_edge_ids),
    }


def _qdrant_delete_data() -> dict[str, object]:
    point = {"chunk_id": "chunk-1", "point_id": "point-1"}
    return {
        "lane": "qdrant",
        "target_commitment_sha256": _QDRANT_TARGET,
        "manifest_binding_sha256": _QDRANT_BINDING,
        "verified_absent": True,
        "passes": [
            {
                "pass_index": 1,
                "target_commitment_sha256": _QDRANT_TARGET,
                "expected": [point],
                "present_before": [point],
                "remaining": [],
                "scoped_point_ids_after": [],
                "exact_scoped_count_after": 0,
                "delete_completed": True,
                "verified_absent": True,
                "issues": [],
            },
            {
                "pass_index": 2,
                "target_commitment_sha256": _QDRANT_TARGET,
                "expected": [point],
                "present_before": [],
                "remaining": [],
                "scoped_point_ids_after": [],
                "exact_scoped_count_after": 0,
                "delete_completed": True,
                "verified_absent": True,
                "issues": [],
            },
        ],
    }


def _graph_delete_data(*, replay: bool = False) -> dict[str, object]:
    expected = _snapshot_json(_graph_snapshot())
    empty = _snapshot_json(ManagedGraphitiIdentitySnapshot((), (), (), ()))
    first = empty if replay else expected
    return {
        "lane": "graphiti",
        "target_commitment_sha256": _GRAPH_TARGET,
        "manifest_binding_sha256": _GRAPH_BINDING,
        "verified_absent": True,
        "bound_expected": expected,
        "delete_expected": first,
        "passes": [
            {
                "pass_index": 1,
                "before": first,
                "deleted": first,
                "group_readback": empty,
                "global_readback": empty,
                "verified_absent": True,
            },
            {
                "pass_index": 2,
                "before": empty,
                "deleted": empty,
                "group_readback": empty,
                "global_readback": empty,
                "verified_absent": True,
            },
        ],
    }


def _config() -> ManagedInfinityHttpConfig:
    return ManagedInfinityHttpConfig(
        target_identity_sha256=_TARGET,
        base_url=_BASE_URL,
        auth_token=_TOKEN,
        timeout_seconds=5.0,
    )


def _factory(handler, transports: list[_TrackingTransport]):
    def create() -> httpx.BaseTransport:
        transport = _TrackingTransport(handler)
        transports.append(transport)
        return transport

    return create


def test_two_external_passes_are_exact_authenticated_and_replay_safe() -> None:
    derived_requests: list[httpx.Request] = []
    derived_transports: list[_TrackingTransport] = []
    graph_calls = 0

    def derived_handler(request: httpx.Request) -> httpx.Response:
        nonlocal graph_calls
        derived_requests.append(request)
        if request.url.path.endswith("/qdrant/delete"):
            return httpx.Response(200, json={"data": _qdrant_delete_data()})
        graph_calls += 1
        return httpx.Response(
            200,
            json={"data": _graph_delete_data(replay=graph_calls == 2)},
        )

    derived = ManagedDerivedEvidenceHttpClient(
        config=_config(),
        transport_factory=_factory(derived_handler, derived_transports),
    )
    canonical_requests: list[httpx.Request] = []
    canonical_transports: list[_TrackingTransport] = []
    delete_counts: dict[str, int] = {}

    def canonical_handler(request: httpx.Request) -> httpx.Response:
        canonical_requests.append(request)
        identity = request.url.path.rsplit("/", 1)[-1]
        kind = "fact" if "/facts/" in request.url.path else "document"
        if request.method == "DELETE":
            assert request.content == b""
            delete_counts[identity] = delete_counts.get(identity, 0) + 1
            indexing_status = "pending" if delete_counts[identity] == 1 else "already_deleted"
        else:
            indexing_status = None
        data: dict[str, object] = {
            "id": identity,
            "space_id": "space-1",
            "memory_scope_id": "scope-1",
            "thread_id": "thread-1",
            "status": "deleted",
            "kind": kind,
        }
        if indexing_status is not None:
            data["indexing_status"] = indexing_status
        return httpx.Response(200, json={"data": data})

    coordinator = ManagedInfinityExactCleanupCoordinator(
        config=_config(),
        derived_evidence=derived,
        transport_factory=_factory(canonical_handler, canonical_transports),
    )
    manifest = _manifest()
    presence = _presence(manifest)

    first = coordinator.cleanup(
        scope=_scope(),
        manifest=manifest,
        presence=presence,
        pass_index=1,
    )
    second = coordinator.cleanup(
        scope=_scope(),
        manifest=manifest,
        presence=presence,
        pass_index=2,
    )

    assert [item.disposition for item in first.canonical] == ["deleted", "deleted"]
    assert [item.disposition for item in second.canonical] == [
        "already_absent",
        "already_absent",
    ]
    assert first.qdrant is not None and first.qdrant.verified_absent
    assert first.graphiti is not None and first.graphiti.verified_absent
    assert second.verified_absent
    assert len(canonical_requests) == 8
    assert all(
        request.headers["authorization"] == f"Bearer {_TOKEN}"
        for request in (*canonical_requests, *derived_requests)
    )
    assert len(canonical_transports) == 8
    assert len({id(item) for item in canonical_transports}) == 8
    assert all(item.closed for item in (*canonical_transports, *derived_transports))


def test_absent_derived_lane_is_skipped() -> None:
    manifest = _manifest(facts=(), documents=("document-1",), chunks=("chunk-1",))
    derived_paths: list[str] = []

    def derived_handler(request: httpx.Request) -> httpx.Response:
        derived_paths.append(request.url.path)
        return httpx.Response(200, json={"data": _qdrant_delete_data()})

    derived = ManagedDerivedEvidenceHttpClient(
        config=_config(),
        transport_factory=lambda: httpx.MockTransport(derived_handler),
    )

    def canonical_handler(request: httpx.Request) -> httpx.Response:
        data = {
            "id": "document-1",
            "space_id": "space-1",
            "memory_scope_id": "scope-1",
            "thread_id": "thread-1",
            "status": "deleted",
        }
        if request.method == "DELETE":
            data["indexing_status"] = "pending"
        return httpx.Response(200, json={"data": data})

    coordinator = ManagedInfinityExactCleanupCoordinator(
        config=_config(),
        derived_evidence=derived,
        transport_factory=lambda: httpx.MockTransport(canonical_handler),
    )
    result = coordinator.cleanup(
        scope=_scope(),
        manifest=manifest,
        presence=_presence(manifest),
        pass_index=1,
    )

    assert result.graphiti is None
    assert result.qdrant is not None
    assert derived_paths == ["/api/v1/diagnostics/derived-evidence/qdrant/delete"]


def test_bound_not_projected_lanes_skip_only_derived_cleanup() -> None:
    manifest = _manifest()
    presence = replace(
        _presence(manifest),
        qdrant=DerivedProjectionLaneDisposition(
            "qdrant",
            "not_projected",
            derived_not_projected_policy_sha256("qdrant"),
        ),
        graphiti=DerivedProjectionLaneDisposition(
            "graphiti",
            "not_projected",
            derived_not_projected_policy_sha256("graphiti"),
        ),
    )
    derived_calls: list[str] = []

    def derived_handler(request: httpx.Request) -> httpx.Response:
        derived_calls.append(request.url.path)
        return httpx.Response(500)

    canonical_calls: list[str] = []

    def canonical_handler(request: httpx.Request) -> httpx.Response:
        canonical_calls.append(f"{request.method} {request.url.path}")
        identity = request.url.path.rsplit("/", 1)[-1]
        data: dict[str, object] = {
            "id": identity,
            "space_id": "space-1",
            "memory_scope_id": "scope-1",
            "thread_id": "thread-1",
            "status": "deleted",
        }
        if request.method == "DELETE":
            data["indexing_status"] = "pending"
        return httpx.Response(200, json={"data": data})

    coordinator = ManagedInfinityExactCleanupCoordinator(
        config=_config(),
        derived_evidence=ManagedDerivedEvidenceHttpClient(
            config=_config(),
            transport_factory=lambda: httpx.MockTransport(derived_handler),
        ),
        transport_factory=lambda: httpx.MockTransport(canonical_handler),
    )

    result = coordinator.cleanup(
        scope=_scope(),
        manifest=manifest,
        presence=presence,
        pass_index=1,
    )

    assert result.qdrant is None
    assert result.graphiti is None
    assert derived_calls == []
    assert canonical_calls == [
        "DELETE /api/v1/facts/fact-1",
        "GET /api/v1/facts/fact-1",
        "DELETE /api/v1/documents/document-1",
        "GET /api/v1/documents/document-1",
    ]


def test_binding_mismatch_fails_before_any_io() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    derived = ManagedDerivedEvidenceHttpClient(
        config=_config(),
        transport_factory=lambda: httpx.MockTransport(handler),
    )
    coordinator = ManagedInfinityExactCleanupCoordinator(
        config=_config(),
        derived_evidence=derived,
        transport_factory=lambda: httpx.MockTransport(handler),
    )
    manifest = _manifest()
    presence = copy.copy(_presence(manifest))
    object.__setattr__(presence, "ingest_manifest_sha256", "9" * 64)

    with pytest.raises(ManagedExactCleanupError) as raised:
        coordinator.cleanup(
            scope=_scope(),
            manifest=manifest,
            presence=presence,
            pass_index=1,
        )

    assert raised.value.code == "managed_exact_cleanup_binding_mismatch"
    assert calls == 0


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ({"status": "active"}, "managed_exact_cleanup_readback_mismatch"),
        ({"space_id": "other"}, "managed_exact_cleanup_readback_mismatch"),
        ({"indexing_status": "unknown"}, "managed_exact_cleanup_ack_invalid"),
    ],
)
def test_canonical_ack_and_scope_readback_are_fail_closed(
    mutation: dict[str, object],
    code: str,
) -> None:
    manifest = _manifest(facts=(), documents=("document-1",), chunks=("chunk-1",))

    def derived_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": _qdrant_delete_data()})

    derived = ManagedDerivedEvidenceHttpClient(
        config=_config(),
        transport_factory=lambda: httpx.MockTransport(derived_handler),
    )

    def canonical_handler(request: httpx.Request) -> httpx.Response:
        data: dict[str, object] = {
            "id": "document-1",
            "space_id": "space-1",
            "memory_scope_id": "scope-1",
            "thread_id": "thread-1",
            "status": "deleted",
            "indexing_status": "pending",
        }
        data.update(mutation)
        return httpx.Response(200, json={"data": data})

    coordinator = ManagedInfinityExactCleanupCoordinator(
        config=_config(),
        derived_evidence=derived,
        transport_factory=lambda: httpx.MockTransport(canonical_handler),
    )

    with pytest.raises(ManagedExactCleanupError) as raised:
        coordinator.cleanup(
            scope=_scope(),
            manifest=manifest,
            presence=_presence(manifest),
            pass_index=1,
        )

    assert raised.value.code == code
    assert _TOKEN not in str(raised.value)


def test_transport_reuse_and_error_text_are_secret_free() -> None:
    manifest = _manifest(facts=(), documents=("document-1",), chunks=("chunk-1",))

    def derived_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": _qdrant_delete_data()})

    derived = ManagedDerivedEvidenceHttpClient(
        config=_config(),
        transport_factory=lambda: httpx.MockTransport(derived_handler),
    )
    reused = httpx.MockTransport(lambda request: httpx.Response(500))
    coordinator = ManagedInfinityExactCleanupCoordinator(
        config=_config(),
        derived_evidence=derived,
        transport_factory=lambda: reused,
    )

    with pytest.raises(ManagedExactCleanupError) as raised:
        coordinator.cleanup(
            scope=_scope(),
            manifest=manifest,
            presence=_presence(manifest),
            pass_index=1,
        )

    assert raised.value.code == "managed_exact_cleanup_request_rejected"
    assert _TOKEN not in repr(coordinator)
    assert _TOKEN not in str(raised.value)

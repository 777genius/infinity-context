from __future__ import annotations

import copy
import json

import httpx
import pytest
from infinity_context_core.ports.derived_projection_policy import (
    DerivedProjectionLaneDisposition,
    derived_not_projected_policy_sha256,
)
from infinity_context_server.memory_comparison_managed_http_derived_evidence import (
    ManagedDerivedEvidenceHttpClient,
    ManagedDerivedEvidenceHttpError,
)
from infinity_context_server.memory_comparison_managed_http_execution import (
    ManagedInfinityHttpConfig,
)
from infinity_context_server.memory_comparison_managed_http_policy_requirements import (
    ManagedCanonicalProjectionScope,
    ManagedGraphitiIdentitySnapshot,
    ManagedIngestIdentityManifest,
    managed_ingest_identity_manifest_sha256,
)
from infinity_context_server.memory_comparison_managed_preflight import (
    managed_backend_target_identity_sha256,
)

_BASE_URL = "https://infinity.example/api"
_LIFECYCLE_TARGET = managed_backend_target_identity_sha256(
    backend_role="infinity-context",
    base_url=_BASE_URL,
)
_QDRANT_TARGET = "2" * 64
_QDRANT_BINDING = "3" * 64
_GRAPHITI_TARGET = "4" * 64
_GRAPHITI_BINDING = "5" * 64
_TOKEN = "do-not-echo-token"


class _TrackingTransport(httpx.MockTransport):
    def __init__(self, handler) -> None:
        super().__init__(handler)
        self.closed = False

    def close(self) -> None:
        self.closed = True
        super().close()


def _scope(*, thread_id: str | None = "thread-1") -> ManagedCanonicalProjectionScope:
    return ManagedCanonicalProjectionScope("space-1", "scope-1", thread_id)


def _manifest() -> ManagedIngestIdentityManifest:
    return ManagedIngestIdentityManifest(
        corpus_id="corpus-1",
        infinity_fact_ids=("fact-1",),
        infinity_document_ids=("document-1",),
        infinity_chunk_ids=("chunk-1",),
        infinity_source_ids=("source-1",),
        infinity_source_sha256=("6" * 64,),
        mem0_created_memory_ids=("memory-1",),
        mem0_source_ids=("mem0-source-1",),
        mem0_source_sha256=("7" * 64,),
        operation_count=2,
        complete=True,
        issues=(),
    )


def _graph_manifest() -> ManagedGraphitiIdentitySnapshot:
    return ManagedGraphitiIdentitySnapshot(
        episode_ids=("episode-1",),
        entity_ids=(),
        mentions_edge_ids=(),
        relates_to_edge_ids=(),
    )


def _presence_data() -> dict[str, object]:
    point = {"chunk_id": "chunk-1", "point_id": "point-1"}
    return {
        "scope": {
            "space_id": "space-1",
            "memory_scope_id": "scope-1",
            "thread_id": "thread-1",
        },
        "outbox": {
            "complete": True,
            "done_chunk_ids": ["chunk-1"],
            "done_fact_ids": ["fact-1"],
            "done_event_count": 2,
        },
        "lanes": {
            "qdrant": {
                "disposition": "projected",
                "projection_version": "v1",
                "target_commitment_sha256": _QDRANT_TARGET,
                "manifest_binding_sha256": _QDRANT_BINDING,
                "expected": [point],
                "observed": [point],
                "scoped_point_ids": ["point-1"],
                "exact_scoped_count": 1,
                "complete": True,
            },
            "graphiti": {
                "disposition": "projected",
                "target_commitment_sha256": _GRAPHITI_TARGET,
                "manifest_binding_sha256": _GRAPHITI_BINDING,
                "identity_manifest": _snapshot_json(_graph_manifest()),
                "exact_identity_count": 1,
                "complete": True,
            },
        },
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


def _graphiti_delete_data() -> dict[str, object]:
    expected = _snapshot_json(_graph_manifest())
    empty = _snapshot_json(ManagedGraphitiIdentitySnapshot((), (), (), ()))
    return {
        "lane": "graphiti",
        "target_commitment_sha256": _GRAPHITI_TARGET,
        "manifest_binding_sha256": _GRAPHITI_BINDING,
        "verified_absent": True,
        "bound_expected": expected,
        "delete_expected": expected,
        "passes": [
            {
                "pass_index": 1,
                "before": expected,
                "deleted": expected,
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


def _snapshot_json(value: ManagedGraphitiIdentitySnapshot) -> dict[str, object]:
    return {
        "episode_ids": list(value.episode_ids),
        "entity_ids": list(value.entity_ids),
        "mentions_edge_ids": list(value.mentions_edge_ids),
        "relates_to_edge_ids": list(value.relates_to_edge_ids),
    }


def _client(handler):
    transports: list[_TrackingTransport] = []

    def factory() -> httpx.BaseTransport:
        transport = _TrackingTransport(handler)
        transports.append(transport)
        return transport

    config = ManagedInfinityHttpConfig(
        target_identity_sha256=_LIFECYCLE_TARGET,
        base_url=_BASE_URL,
        auth_token=_TOKEN,
        timeout_seconds=5.0,
    )
    return ManagedDerivedEvidenceHttpClient(
        config=config,
        transport_factory=factory,
    ), transports


def test_presence_is_strict_identity_only_and_bound_to_manifest_scope() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"data": _presence_data()})

    client, transports = _client(handler)
    observation = client.observe_presence(scope=_scope(), manifest=_manifest())

    assert observation.lifecycle_target_identity_sha256 == _LIFECYCLE_TARGET
    assert observation.ingest_manifest_sha256 == managed_ingest_identity_manifest_sha256(
        _manifest(), _scope()
    )
    assert observation.qdrant is not None
    assert observation.graphiti is not None
    assert observation.graphiti.group_scope == _scope()
    assert observation.graphiti.identity_manifest.entity_ids == ()
    assert client.retries == 0
    assert len(requests) == len(transports) == 1
    assert transports[0].closed is True
    request_payload = json.loads(requests[0].content)
    assert requests[0].headers["Authorization"] == f"Bearer {_TOKEN}"
    assert requests[0].url.path == "/api/v1/diagnostics/derived-evidence/presence"
    assert request_payload == {
        "space_id": "space-1",
        "memory_scope_id": "scope-1",
        "thread_id": "thread-1",
        "expected_chunk_ids": ["chunk-1"],
        "expected_fact_ids": ["fact-1"],
    }
    assert _LIFECYCLE_TARGET not in requests[0].content.decode()


def test_presence_accepts_only_bound_not_projected_dispositions() -> None:
    data = _presence_data()
    lanes = data["lanes"]
    assert type(lanes) is dict
    lanes["qdrant"] = {
        "disposition": "not_projected",
        "policy_sha256": derived_not_projected_policy_sha256("qdrant"),
    }
    lanes["graphiti"] = {
        "disposition": "not_projected",
        "policy_sha256": derived_not_projected_policy_sha256("graphiti"),
    }

    client, _ = _client(lambda _: httpx.Response(200, json={"data": data}))
    observation = client.observe_presence(scope=_scope(), manifest=_manifest())

    assert type(observation.qdrant) is DerivedProjectionLaneDisposition
    assert observation.qdrant.lane == "qdrant"
    assert observation.qdrant.is_not_projected
    assert type(observation.graphiti) is DerivedProjectionLaneDisposition
    assert observation.graphiti.lane == "graphiti"
    assert observation.graphiti.is_not_projected


def test_each_delete_owns_a_fresh_transport_and_checks_echoed_bindings() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/qdrant/delete"):
            return httpx.Response(200, json={"data": _qdrant_delete_data()})
        if request.url.path.endswith("/graphiti/delete"):
            return httpx.Response(200, json={"data": _graphiti_delete_data()})
        raise AssertionError("unexpected request")

    client, transports = _client(handler)
    qdrant = client.delete_qdrant(
        scope=_scope(),
        manifest=_manifest(),
        target_commitment_sha256=_QDRANT_TARGET,
        manifest_binding_sha256=_QDRANT_BINDING,
    )
    graphiti = client.delete_graphiti(
        scope=_scope(),
        manifest=_manifest(),
        identity_manifest=_graph_manifest(),
        target_commitment_sha256=_GRAPHITI_TARGET,
        manifest_binding_sha256=_GRAPHITI_BINDING,
    )

    assert qdrant.verified_absent is True
    assert tuple(item.pass_index for item in qdrant.passes) == (1, 2)
    assert graphiti.verified_absent is True
    assert graphiti.expected.entity_ids == ()
    assert len(transports) == 2
    assert len({id(item) for item in transports}) == 2
    assert all(item.closed for item in transports)


def test_qdrant_external_delete_replay_accepts_original_bound_expected() -> None:
    call_count = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal call_count
        data = _qdrant_delete_data()
        if call_count == 1:
            data["passes"][0]["present_before"] = []  # type: ignore[index]
        call_count += 1
        return httpx.Response(200, json={"data": data})

    client, transports = _client(handler)
    arguments = {
        "scope": _scope(),
        "manifest": _manifest(),
        "target_commitment_sha256": _QDRANT_TARGET,
        "manifest_binding_sha256": _QDRANT_BINDING,
    }
    first = client.delete_qdrant(**arguments)
    replay = client.delete_qdrant(**arguments)

    assert first.passes[0].present_before == first.passes[0].expected
    assert replay.passes[0].present_before == ()
    assert replay.passes[0].expected == first.passes[0].expected
    assert replay.manifest_binding_sha256 == _QDRANT_BINDING
    assert len(transports) == 2
    assert all(item.closed for item in transports)


def test_graphiti_external_delete_replay_accepts_original_bound_expected() -> None:
    call_count = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal call_count
        data = _graphiti_delete_data()
        if call_count == 1:
            empty = _snapshot_json(ManagedGraphitiIdentitySnapshot((), (), (), ()))
            data["delete_expected"] = empty
            data["passes"][0]["before"] = empty  # type: ignore[index]
            data["passes"][0]["deleted"] = empty  # type: ignore[index]
        call_count += 1
        return httpx.Response(200, json={"data": data})

    client, transports = _client(handler)
    arguments = {
        "scope": _scope(),
        "manifest": _manifest(),
        "identity_manifest": _graph_manifest(),
        "target_commitment_sha256": _GRAPHITI_TARGET,
        "manifest_binding_sha256": _GRAPHITI_BINDING,
    }
    first = client.delete_graphiti(**arguments)
    replay = client.delete_graphiti(**arguments)

    assert first.passes[0].before == first.expected
    assert replay.passes[0].before.empty is True
    assert replay.expected == first.expected
    assert replay.manifest_binding_sha256 == _GRAPHITI_BINDING
    assert len(transports) == 2
    assert all(item.closed for item in transports)


def test_qdrant_delete_rejects_nonempty_second_pass_present_before() -> None:
    data = _qdrant_delete_data()
    data["passes"][1]["present_before"] = [  # type: ignore[index]
        {"chunk_id": "chunk-1", "point_id": "point-1"}
    ]

    client, _ = _client(lambda _: httpx.Response(200, json={"data": data}))
    with pytest.raises(
        ManagedDerivedEvidenceHttpError,
        match="^managed_derived_evidence_qdrant_delete_invalid$",
    ):
        client.delete_qdrant(
            scope=_scope(),
            manifest=_manifest(),
            target_commitment_sha256=_QDRANT_TARGET,
            manifest_binding_sha256=_QDRANT_BINDING,
        )


def test_graphiti_delete_rejects_delete_expected_drift() -> None:
    data = _graphiti_delete_data()
    data["delete_expected"] = _snapshot_json(ManagedGraphitiIdentitySnapshot((), (), (), ()))

    client, _ = _client(lambda _: httpx.Response(200, json={"data": data}))
    with pytest.raises(
        ManagedDerivedEvidenceHttpError,
        match="^managed_derived_evidence_graphiti_delete_invalid$",
    ):
        client.delete_graphiti(
            scope=_scope(),
            manifest=_manifest(),
            identity_manifest=_graph_manifest(),
            target_commitment_sha256=_GRAPHITI_TARGET,
            manifest_binding_sha256=_GRAPHITI_BINDING,
        )


@pytest.mark.parametrize("lane", ("qdrant", "graphiti"))
def test_delete_rejects_stale_binding_or_partial_first_pass(lane: str) -> None:
    qdrant_data = _qdrant_delete_data()
    qdrant_data["manifest_binding_sha256"] = "8" * 64
    graphiti_data = copy.deepcopy(_graphiti_delete_data())
    empty = _snapshot_json(ManagedGraphitiIdentitySnapshot((), (), (), ()))
    graphiti_data["passes"][0]["deleted"] = empty  # type: ignore[index]

    def handler(_: httpx.Request) -> httpx.Response:
        data = qdrant_data if lane == "qdrant" else graphiti_data
        return httpx.Response(200, json={"data": data})

    client, _ = _client(handler)
    if lane == "qdrant":
        with pytest.raises(
            ManagedDerivedEvidenceHttpError,
            match="^managed_derived_evidence_qdrant_delete_invalid$",
        ):
            client.delete_qdrant(
                scope=_scope(),
                manifest=_manifest(),
                target_commitment_sha256=_QDRANT_TARGET,
                manifest_binding_sha256=_QDRANT_BINDING,
            )
    else:
        with pytest.raises(
            ManagedDerivedEvidenceHttpError,
            match="^managed_derived_evidence_graphiti_delete_invalid$",
        ):
            client.delete_graphiti(
                scope=_scope(),
                manifest=_manifest(),
                identity_manifest=_graph_manifest(),
                target_commitment_sha256=_GRAPHITI_TARGET,
                manifest_binding_sha256=_GRAPHITI_BINDING,
            )


@pytest.mark.parametrize(
    "mutate",
    (
        lambda data: data.update({"content": "provider-content"}),
        lambda data: data["lanes"]["qdrant"].update(  # type: ignore[index,union-attr]
            {"observed": [{"chunk_id": "chunk-1", "point_id": "point-other"}]}
        ),
        lambda data: data["outbox"].update(  # type: ignore[union-attr]
            {"done_chunk_ids": []}
        ),
        lambda data: data["lanes"]["qdrant"].pop("disposition"),  # type: ignore[index,union-attr]
    ),
)
def test_presence_rejects_extra_content_or_identity_mismatch(mutate) -> None:
    data = _presence_data()
    mutate(data)

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": data})

    client, _ = _client(handler)
    with pytest.raises(
        ManagedDerivedEvidenceHttpError,
        match="^managed_derived_evidence_presence_invalid$",
    ):
        client.observe_presence(scope=_scope(), manifest=_manifest())


def test_transport_errors_and_oversized_bodies_never_echo_remote_data() -> None:
    remote_secret = "remote-secret-error-body"

    def rejected(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text=remote_secret)

    client, _ = _client(rejected)
    with pytest.raises(ManagedDerivedEvidenceHttpError) as captured:
        client.observe_presence(scope=_scope(), manifest=_manifest())
    assert captured.value.code == "managed_derived_evidence_request_rejected"
    assert remote_secret not in str(captured.value)
    assert _TOKEN not in str(captured.value)

    def oversized(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=b"x" * 2_000_001,
        )

    oversized_client, _ = _client(oversized)
    with pytest.raises(
        ManagedDerivedEvidenceHttpError,
        match="^managed_derived_evidence_response_too_large$",
    ):
        oversized_client.observe_presence(scope=_scope(), manifest=_manifest())


def test_manifest_binding_includes_every_canonical_scope_component() -> None:
    manifest = _manifest()
    base = managed_ingest_identity_manifest_sha256(manifest, _scope())
    assert base != managed_ingest_identity_manifest_sha256(
        manifest,
        ManagedCanonicalProjectionScope("space-2", "scope-1", "thread-1"),
    )
    assert base != managed_ingest_identity_manifest_sha256(
        manifest,
        ManagedCanonicalProjectionScope("space-1", "scope-2", "thread-1"),
    )
    assert base != managed_ingest_identity_manifest_sha256(
        manifest,
        ManagedCanonicalProjectionScope("space-1", "scope-1", None),
    )


def test_reused_custom_transport_is_rejected_before_second_request() -> None:
    transport = _TrackingTransport(lambda _: httpx.Response(200, json={"data": _presence_data()}))
    config = ManagedInfinityHttpConfig(
        target_identity_sha256=_LIFECYCLE_TARGET,
        base_url=_BASE_URL,
        auth_token=_TOKEN,
        timeout_seconds=5.0,
    )
    client = ManagedDerivedEvidenceHttpClient(
        config=config,
        transport_factory=lambda: transport,
    )
    client.observe_presence(scope=_scope(), manifest=_manifest())
    with pytest.raises(
        ManagedDerivedEvidenceHttpError,
        match="^managed_derived_evidence_transport_reused$",
    ):
        client.observe_presence(scope=_scope(), manifest=_manifest())

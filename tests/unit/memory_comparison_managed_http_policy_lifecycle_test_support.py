from __future__ import annotations

from datetime import datetime

import httpx
from infinity_context_server import memory_comparison_managed_http_policy_lifecycle as policy
from infinity_context_server.memory_comparison_full_run_evidence import (
    create_full_comparison_run_bindings,
)
from infinity_context_server.memory_comparison_managed_http_lifecycle import (
    ManagedHttpIngestEvidenceView,
)
from infinity_context_server.memory_comparison_managed_http_policy_lifecycle import (
    ManagedComparisonHttpPolicyLifecycleAdapter,
)
from infinity_context_server.memory_comparison_managed_preflight import (
    managed_backend_target_identity_sha256,
)
from infinity_context_server.memory_comparison_managed_run_contract import (
    ManagedRunCase,
)
from infinity_context_server.memory_comparison_models import BackendIngestResult
from test_memory_comparison_managed_http_derived_evidence import (
    _GRAPHITI_BINDING,
    _GRAPHITI_TARGET,
    _graph_manifest,
    _graphiti_delete_data,
    _snapshot_json,
)
from test_memory_comparison_managed_http_lifecycle import (
    _locomo_case,
)
from test_memory_comparison_managed_http_lifecycle import (
    _longmem_case as _longmem_case,
)
from test_memory_comparison_managed_http_lifecycle import (
    _thaw as _thaw,
)
from test_memory_comparison_managed_ingest_manifest import (
    _infinity_fact,
    _mem0,
)
from test_memory_comparison_managed_ingest_manifest import (
    _view as _manifest_view,
)
from test_memory_comparison_managed_runtime_credentials import (
    _DEADLINE as _CREDENTIAL_DEADLINE,
)
from test_memory_comparison_managed_runtime_credentials import (
    _INFINITY_ORIGIN as _INFINITY_URL,
)
from test_memory_comparison_managed_runtime_credentials import (
    _INFINITY_SECRET,
    _MEM0_SECRET,
    _authority,
    _bind,
)
from test_memory_comparison_managed_runtime_credentials import (
    _MEM0_ORIGIN as _MEM0_URL,
)
from test_memory_comparison_managed_runtime_credentials import (
    _NOW as _CREDENTIAL_NOW,
)
from test_memory_comparison_managed_runtime_credentials import (
    _RUN_ID as _RUN,
)

_SECRET_INFINITY = _INFINITY_SECRET
_SECRET_MEM0 = _MEM0_SECRET
_INFINITY_TARGET = managed_backend_target_identity_sha256(
    backend_role="infinity-context", base_url=_INFINITY_URL
)
_MEM0_TARGET = managed_backend_target_identity_sha256(backend_role="mem0", base_url=_MEM0_URL)
_ATTESTATION = object()


class _Clock:
    value = _CREDENTIAL_NOW

    def __call__(self) -> datetime:
        return self.value


class _TrackingTransport(httpx.MockTransport):
    def __init__(self, handler) -> None:
        super().__init__(handler)
        self.closed = False

    def close(self) -> None:
        self.closed = True
        super().close()


def _factory(handler, created: list[_TrackingTransport]):
    def create() -> httpx.BaseTransport:
        transport = _TrackingTransport(handler)
        created.append(transport)
        return transport

    return create


def _credential_context():
    authority = _authority()
    request = _bind(authority)
    material = authority.issue_backend_credential_material(
        expected_request=request,
        run_id=_RUN,
        infinity_origin=_INFINITY_URL,
        mem0_origin=_MEM0_URL,
        deadline=_CREDENTIAL_DEADLINE,
        now=_CREDENTIAL_NOW,
    )
    return request, material


def _bindings(request):
    return create_full_comparison_run_bindings(
        run_id=_RUN,
        run_nonce_commitment_sha256="1" * 64,
        runtime_probe_nonce_sha256="2" * 64,
        profile=request.profile,
        methodology=request.methodology,
        dataset_sha256=request.dataset.dataset_sha256,
        selection_fingerprint_sha256="3" * 64,
        backend_targets=tuple(endpoint.target for endpoint in request.backend_endpoints),
        scope="canary",
    )


def _adapter(
    *,
    cases: tuple[ManagedRunCase, ...],
    derived_factory=None,
    cleanup_factory=None,
    mem0_factory=None,
):
    request, material = _credential_context()
    bindings = _bindings(request)
    return (
        ManagedComparisonHttpPolicyLifecycleAdapter(
            bindings=bindings,
            cases=cases,
            preflight_request=request,
            credential_material=material,
            deadline=_CREDENTIAL_DEADLINE,
            infinity_derived_transport_factory=derived_factory,
            infinity_cleanup_transport_factory=cleanup_factory,
            mem0_delete_transport_factory=mem0_factory,
            clock=_Clock(),
        ),
        bindings,
    )


def _managed_view(view: ManagedHttpIngestEvidenceView) -> ManagedHttpIngestEvidenceView:
    metadata = dict(view.ingest_result.metadata)
    metadata["managed_http_execution"] = {
        "credential_continuity_proven": True,
        "composition_blockers": [],
    }
    result = BackendIngestResult(
        items_processed=view.ingest_result.items_processed,
        items_failed=view.ingest_result.items_failed,
        operations=view.ingest_result.operations,
        metadata=metadata,
    )
    return ManagedHttpIngestEvidenceView(
        view.backend_role,
        view.target_identity_sha256,
        view.case_id,
        view.corpus_id,
        view.clean_state_validation,
        result,
        view.locomo_timestamp_verifier,
        view.locomo_timestamp_evidence,
    )


def _views(case: ManagedRunCase) -> tuple[ManagedHttpIngestEvidenceView, ...]:
    return (
        _managed_view(
            _manifest_view(
                "infinity-context",
                _infinity_fact(),
                case_id=case.case_id,
                corpus_id=case.corpus_id,
                target=_INFINITY_TARGET,
            )
        ),
        _managed_view(
            _manifest_view(
                "mem0",
                _mem0(),
                case_id=case.case_id,
                corpus_id=case.corpus_id,
                target=_MEM0_TARGET,
            )
        ),
    )


def _presence_data() -> dict[str, object]:
    snapshot = _graph_manifest()
    return {
        "scope": {
            "space_id": "space-1",
            "memory_scope_id": "scope-1",
            "thread_id": "thread-1",
        },
        "outbox": {
            "complete": True,
            "done_chunk_ids": [],
            "done_fact_ids": ["fact-1"],
            "done_event_count": 1,
        },
        "lanes": {
            "qdrant": None,
            "graphiti": {
                "disposition": "projected",
                "target_commitment_sha256": _GRAPHITI_TARGET,
                "manifest_binding_sha256": _GRAPHITI_BINDING,
                "identity_manifest": _snapshot_json(snapshot),
                "exact_identity_count": snapshot.exact_identity_count,
                "complete": True,
            },
        },
    }


def _seal(adapter, bindings, cases, views, monkeypatch):
    monkeypatch.setattr(policy, "_attestation", lambda *args: None)
    monkeypatch.setattr(
        policy,
        "consume_managed_http_ingest_receipts",
        lambda *args, **kwargs: views,
    )
    return adapter.seal_canonical_source(
        bindings=bindings,
        cases=cases,
        managed_attestation=_ATTESTATION,
        managed_attestation_commitment_sha256="6" * 64,
        ingest_receipts=(object(),),
        case_manifest_sha256="4" * 64,
    )


def _cleanup_ready_lifecycle(monkeypatch, cases=None):
    selected = (_locomo_case(),) if cases is None else cases
    graph_delete_count = 0

    def derived(request: httpx.Request) -> httpx.Response:
        nonlocal graph_delete_count
        if request.url.path.endswith("/presence"):
            return httpx.Response(200, json={"data": _presence_data()})
        data = _graphiti_delete_data()
        if graph_delete_count == 1:
            empty = {key: [] for key in _snapshot_json(_graph_manifest())}
            data["delete_expected"] = empty
            data["passes"][0]["before"] = empty  # type: ignore[index]
            data["passes"][0]["deleted"] = empty  # type: ignore[index]
        graph_delete_count += 1
        return httpx.Response(200, json={"data": data})

    delete_count = 0

    def canonical(request: httpx.Request) -> httpx.Response:
        nonlocal delete_count
        data: dict[str, object] = {
            "id": "fact-1",
            "space_id": "space-1",
            "memory_scope_id": "scope-1",
            "thread_id": "thread-1",
            "status": "deleted",
        }
        if request.method == "DELETE":
            delete_count += 1
            data["indexing_status"] = "pending" if delete_count == 1 else "already_deleted"
        return httpx.Response(200, json={"data": data})

    def mem0(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"deleted": True, "verified_absent": True})

    adapter, bindings = _adapter(
        cases=selected,
        derived_factory=lambda: httpx.MockTransport(derived),
        cleanup_factory=lambda: httpx.MockTransport(canonical),
        mem0_factory=lambda: httpx.MockTransport(mem0),
    )
    canonical_receipts = _seal(
        adapter,
        bindings,
        selected,
        _views(selected[0]),
        monkeypatch,
    )
    return adapter, bindings, canonical_receipts


def _complete_lifecycle(monkeypatch, cases=None):
    adapter, bindings, canonical_receipts = _cleanup_ready_lifecycle(monkeypatch, cases)
    delete_receipts = tuple(
        adapter.terminal_delete(
            bindings=bindings,
            backend_role=target.backend_role,
            target_identity_sha256=target.target_identity_sha256,
            pass_index=pass_index,
        )
        for pass_index in (1, 2)
        for target in bindings.backend_targets
    )
    terminal = adapter.seal_terminal_delete(
        bindings=bindings,
        managed_attestation=_ATTESTATION,
        managed_attestation_commitment_sha256="6" * 64,
        receipts=delete_receipts,
    )
    return adapter, bindings, canonical_receipts, terminal, delete_receipts

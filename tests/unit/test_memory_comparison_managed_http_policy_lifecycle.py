from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import httpx
import pytest
from infinity_context_server import memory_comparison_managed_http_policy_lifecycle as policy
from infinity_context_server.memory_comparison_full_run_evidence import (
    create_full_comparison_run_bindings,
)
from infinity_context_server.memory_comparison_managed_http_lifecycle import (
    ManagedHttpIngestEvidenceView,
)
from infinity_context_server.memory_comparison_managed_http_policy_lifecycle import (
    ManagedComparisonHttpPolicyLifecycleAdapter,
    ManagedHttpPolicyDeleteReceipt,
    ManagedHttpPolicyLifecycleError,
    managed_http_policy_production_blockers,
)
from infinity_context_server.memory_comparison_managed_http_policy_requirements import (
    ManagedCanonicalSourceObservation,
    ManagedDeleteIdentityLane,
    ManagedExactPresenceLane,
    ManagedIngestIdentityManifest,
    ManagedPolicyObservationContractError,
    ManagedTerminalDeleteObservation,
)
from infinity_context_server.memory_comparison_managed_preflight import (
    managed_backend_target_identity_sha256,
)
from infinity_context_server.memory_comparison_managed_run_contract import (
    ManagedExecutionArtifacts,
)
from infinity_context_server.memory_comparison_models import BackendIngestResult
from test_memory_comparison_managed_http_lifecycle import _locomo_case, _longmem_case
from test_memory_comparison_managed_runtime_credentials import (
    _DEADLINE as _CREDENTIAL_DEADLINE,
)
from test_memory_comparison_managed_runtime_credentials import (
    _INFINITY_ORIGIN as _CREDENTIAL_INFINITY_ORIGIN,
)
from test_memory_comparison_managed_runtime_credentials import (
    _INFINITY_SECRET as _CREDENTIAL_INFINITY_SECRET,
)
from test_memory_comparison_managed_runtime_credentials import (
    _MEM0_ORIGIN as _CREDENTIAL_MEM0_ORIGIN,
)
from test_memory_comparison_managed_runtime_credentials import (
    _MEM0_SECRET as _CREDENTIAL_MEM0_SECRET,
)
from test_memory_comparison_managed_runtime_credentials import (
    _NOW as _CREDENTIAL_NOW,
)
from test_memory_comparison_managed_runtime_credentials import (
    _RUN_ID as _CREDENTIAL_RUN_ID,
)
from test_memory_comparison_managed_runtime_credentials import _authority, _bind

_RUN = _CREDENTIAL_RUN_ID
_INFINITY_URL = _CREDENTIAL_INFINITY_ORIGIN
_MEM0_URL = _CREDENTIAL_MEM0_ORIGIN
_INFINITY_TARGET = managed_backend_target_identity_sha256(
    backend_role="infinity-context",
    base_url=_INFINITY_URL,
)
_MEM0_TARGET = managed_backend_target_identity_sha256(
    backend_role="mem0",
    base_url=_MEM0_URL,
)
_SECRET_INFINITY = _CREDENTIAL_INFINITY_SECRET
_SECRET_MEM0 = _CREDENTIAL_MEM0_SECRET


class _Clock:
    def __init__(self) -> None:
        self.value = _CREDENTIAL_NOW

    def __call__(self) -> datetime:
        return self.value


def _bindings(request):
    profile = request.profile
    return create_full_comparison_run_bindings(
        run_id=_RUN,
        run_nonce_commitment_sha256="1" * 64,
        runtime_probe_nonce_sha256="2" * 64,
        profile=profile,
        methodology=request.methodology,
        dataset_sha256=request.dataset.dataset_sha256,
        selection_fingerprint_sha256="3" * 64,
        backend_targets=(
            *(endpoint.target for endpoint in request.backend_endpoints),
        ),
        scope="canary",
    )


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


def _adapter(
    *,
    case=None,
    infinity_transports=(None, None),
    mem0_transports=(None, None),
    request=None,
    material=None,
    deadline=_CREDENTIAL_DEADLINE,
):
    if request is None or material is None:
        request, material = _credential_context()
    bindings = _bindings(request)
    active_case = case or _locomo_case()
    clock = _Clock()
    adapter = ManagedComparisonHttpPolicyLifecycleAdapter(
        bindings=bindings,
        cases=(active_case,),
        preflight_request=request,
        credential_material=material,
        deadline=deadline,
        infinity_delete_transports=infinity_transports,
        mem0_delete_transports=mem0_transports,
        clock=clock,
    )
    return adapter, bindings, active_case


def _execution() -> ManagedExecutionArtifacts:
    return ManagedExecutionArtifacts(
        object(),
        object(),
        "4" * 64,
        (("case-alias", "5" * 64),),
    )


def _view(*, continuity: bool, blockers: object) -> ManagedHttpIngestEvidenceView:
    return ManagedHttpIngestEvidenceView(
        "infinity-context",
        _INFINITY_TARGET,
        "case",
        "corpus",
        object(),
        BackendIngestResult(
            items_processed=1,
            metadata={
                "managed_http_execution": {
                    "credential_continuity_proven": continuity,
                    "composition_blockers": blockers,
                }
            },
        ),
        None,
        (),
    )


def _seal_args(bindings, case):
    return {
        "bindings": bindings,
        "cases": (case,),
        "managed_attestation": object(),
        "managed_attestation_commitment_sha256": "6" * 64,
        "ingest_receipts": (object(),),
        "execution": _execution(),
    }


def test_current_legacy_ingest_receipt_is_rejected_before_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, bindings, case = _adapter()
    monkeypatch.setattr(policy, "_attestation", lambda *args: None)
    monkeypatch.setattr(
        policy,
        "consume_managed_http_ingest_receipts",
        lambda *args, **kwargs: (
            _view(
                continuity=False,
                blockers=["credential_authority_not_bound"],
            ),
        ),
    )

    with pytest.raises(
        ManagedHttpPolicyLifecycleError,
        match="^managed_http_policy_credential_continuity_unproven$",
    ):
        adapter.seal_canonical_source(**_seal_args(bindings, case))


def test_pure_blockers_are_available_before_credentials_or_io() -> None:
    assert managed_http_policy_production_blockers((_locomo_case(),)) == (
        "managed_http_policy_infinity_document_chunk_identity_unavailable",
        "managed_http_policy_infinity_fact_source_hash_unavailable",
        "managed_http_policy_mem0_exact_source_identity_unavailable",
        "managed_http_policy_exact_derived_identity_manifest_unavailable",
        "managed_http_policy_terminal_manifest_binding_unavailable",
    )
    assert managed_http_policy_production_blockers((_longmem_case(),)) == (
        "managed_http_policy_infinity_document_chunk_identity_unavailable",
        "managed_http_policy_mem0_exact_source_identity_unavailable",
        "managed_http_policy_exact_derived_identity_manifest_unavailable",
        "managed_http_policy_terminal_manifest_binding_unavailable",
    )


def test_policy_credential_lane_replay_and_wrong_context_fail_before_io() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(500)

    request, material = _credential_context()
    transports = (httpx.MockTransport(handler), httpx.MockTransport(handler))
    _adapter(
        request=request,
        material=material,
        infinity_transports=transports,
    )
    with pytest.raises(
        ManagedHttpPolicyLifecycleError,
        match="^managed_http_policy_credential_continuity_failed$",
    ):
        _adapter(
            request=request,
            material=material,
            infinity_transports=(
                httpx.MockTransport(handler),
                httpx.MockTransport(handler),
            ),
        )

    first_request, first_material = _credential_context()
    second_authority = _authority()
    wrong_request = _bind(second_authority)
    with pytest.raises(
        ManagedHttpPolicyLifecycleError,
        match="^managed_http_policy_credential_continuity_failed$",
    ):
        _adapter(
            request=wrong_request,
            material=first_material,
            infinity_transports=(
                httpx.MockTransport(handler),
                httpx.MockTransport(handler),
            ),
        )
    assert first_request is not wrong_request
    assert calls == []


@pytest.mark.parametrize(
    ("case_factory", "blocker"),
    (
        (
            _locomo_case,
            "managed_http_policy_infinity_document_chunk_identity_unavailable",
        ),
        (
            _longmem_case,
            "managed_http_policy_infinity_document_chunk_identity_unavailable",
        ),
    ),
)
def test_even_credential_bound_legacy_shape_fails_at_exact_identity_gap(
    monkeypatch: pytest.MonkeyPatch,
    case_factory,
    blocker: str,
) -> None:
    adapter, bindings, case = _adapter(case=case_factory())
    monkeypatch.setattr(policy, "_attestation", lambda *args: None)
    monkeypatch.setattr(
        policy,
        "consume_managed_http_ingest_receipts",
        lambda *args, **kwargs: (_view(continuity=True, blockers=[]),),
    )

    with pytest.raises(ManagedHttpPolicyLifecycleError, match=f"^{blocker}$"):
        adapter.seal_canonical_source(**_seal_args(bindings, case))


def test_typed_future_observation_contract_rejects_partial_or_inconsistent_data() -> None:
    manifest = ManagedIngestIdentityManifest(
        corpus_id="corpus-1",
        infinity_fact_ids=("fact-1",),
        infinity_document_ids=(),
        infinity_chunk_ids=("chunk-1",),
        infinity_source_ids=("source-1",),
        infinity_source_sha256=("7" * 64,),
        mem0_created_memory_ids=("memory-1",),
        mem0_source_ids=("source-1",),
        mem0_source_sha256=("7" * 64,),
        operation_count=2,
        complete=True,
        issues=(),
    )
    canonical = ManagedCanonicalSourceObservation(
        _INFINITY_TARGET,
        _MEM0_TARGET,
        manifest,
        ManagedExactPresenceLane("infinity_fact", ("fact-1",), ("fact-1",)),
        ManagedExactPresenceLane("infinity_source", ("source-1",), ("source-1",)),
        ManagedExactPresenceLane("mem0_source", ("source-1",), ("source-1",)),
        ManagedExactPresenceLane("qdrant_point", ("qdrant-1",), ("qdrant-1",)),
        ManagedExactPresenceLane("graphiti_entity", ("graphiti-1",), ("graphiti-1",)),
        1,
        "7" * 64,
        False,
        ("authenticated_derived_identity_manifest_unavailable",),
    )
    assert canonical.expected_count == canonical.observed_count == 5
    with pytest.raises(ManagedPolicyObservationContractError, match="completeness"):
        ManagedCanonicalSourceObservation(
            _INFINITY_TARGET,
            _MEM0_TARGET,
            manifest,
            ManagedExactPresenceLane("infinity_fact", ("fact-1",), ()),
            canonical.infinity_source,
            canonical.mem0_source,
            canonical.qdrant,
            canonical.graphiti,
            1,
            "7" * 64,
            False,
            (),
        )
    with pytest.raises(ManagedPolicyObservationContractError, match="lane roles"):
        ManagedCanonicalSourceObservation(
            _INFINITY_TARGET,
            _MEM0_TARGET,
            manifest,
            canonical.canonical,
            canonical.mem0_source,
            canonical.infinity_source,
            canonical.qdrant,
            canonical.graphiti,
            1,
            "7" * 64,
            False,
            ("authenticated_derived_identity_manifest_unavailable",),
        )
    assert ManagedExactPresenceLane("qdrant_point", (), ()).complete is False
    with pytest.raises(
        ManagedPolicyObservationContractError,
        match="authenticated derived identity manifest",
    ):
        ManagedCanonicalSourceObservation(
            _INFINITY_TARGET,
            _MEM0_TARGET,
            manifest,
            canonical.canonical,
            canonical.infinity_source,
            canonical.mem0_source,
            canonical.qdrant,
            canonical.graphiti,
            1,
            "7" * 64,
            True,
            (),
        )
    with pytest.raises(ManagedPolicyObservationContractError, match="identity tuple"):
        ManagedIngestIdentityManifest(
            corpus_id="corpus-1",
            infinity_fact_ids=("fact-1", "fact-1"),
            infinity_document_ids=(),
            infinity_chunk_ids=(),
            infinity_source_ids=("source-1",),
            infinity_source_sha256=("7" * 64,),
            mem0_created_memory_ids=("memory-1",),
            mem0_source_ids=("source-1",),
            mem0_source_sha256=("7" * 64,),
            operation_count=2,
            complete=True,
            issues=(),
        )
    with pytest.raises(ManagedPolicyObservationContractError, match="deleted identity order"):
        ManagedDeleteIdentityLane(
            "infinity_fact",
            ("fact-1", "fact-2"),
            ("fact-2", "fact-1"),
            (),
        )

    lane = ManagedDeleteIdentityLane(
        "infinity_fact",
        ("fact-1", "fact-2", "fact-3"),
        ("fact-1", "fact-3"),
        ("fact-2",),
    )
    terminal = ManagedTerminalDeleteObservation(
        _INFINITY_TARGET,
        "corpus-1",
        1,
        "8" * 64,
        (lane,),
        False,
        False,
        ("terminal_manifest_binding_unavailable",),
    )
    assert terminal.deleted_count == 2
    assert terminal.remaining_count == 1
    with pytest.raises(ManagedPolicyObservationContractError, match="deleted identity order"):
        ManagedDeleteIdentityLane(
            "infinity_fact",
            ("fact-1", "fact-2", "fact-3"),
            ("fact-3", "fact-1"),
            ("fact-2",),
        )
    absent_lane = ManagedDeleteIdentityLane(
        "infinity_fact",
        ("fact-1",),
        ("fact-1",),
        (),
    )
    with pytest.raises(
        ManagedPolicyObservationContractError,
        match="terminal manifest binding",
    ):
        ManagedTerminalDeleteObservation(
            _INFINITY_TARGET,
            "corpus-1",
            1,
            "8" * 64,
            (absent_lane,),
            True,
            True,
            (),
        )


def _cleanup_handlers():
    facts_present = True
    lock = threading.Lock()
    events: list[tuple[str, str]] = []

    def infinity(request: httpx.Request) -> httpx.Response:
        nonlocal facts_present
        assert request.headers["Authorization"] == f"Bearer {_SECRET_INFINITY}"
        path = request.url.path.removeprefix("/api")
        with lock:
            events.append(("infinity", request.method + " " + path))
            if request.method == "GET" and path == "/v1/facts":
                data = [{"id": "fact-1"}] if facts_present else []
                return httpx.Response(200, json={"data": data, "next_cursor": None})
            if request.method == "DELETE" and path == "/v1/facts/fact-1":
                facts_present = False
                return httpx.Response(200, json={"data": {"id": "fact-1", "status": "deleted"}})
        return httpx.Response(404)

    def mem0(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-API-Key"] == _SECRET_MEM0
        with lock:
            events.append(("mem0", request.method + " " + request.url.path))
        return httpx.Response(200, json={"deleted": True, "verified_absent": True})

    return infinity, mem0, events


def _cleanup_adapter():
    infinity, mem0, events = _cleanup_handlers()
    infinity_transports = (
        httpx.MockTransport(infinity),
        httpx.MockTransport(infinity),
    )
    mem0_transports = (
        httpx.MockTransport(mem0),
        httpx.MockTransport(mem0),
    )
    adapter, bindings, case = _adapter(
        infinity_transports=infinity_transports,
        mem0_transports=mem0_transports,
    )
    return adapter, bindings, case, events


def _four_deletes(adapter, bindings):
    receipts = []
    for pass_index in (1, 2):
        for target in bindings.backend_targets:
            receipts.append(
                adapter.terminal_delete(
                    bindings=bindings,
                    backend_role=target.backend_role,
                    target_identity_sha256=target.target_identity_sha256,
                    pass_index=pass_index,
                )
            )
    return tuple(receipts)


def test_two_real_cleanup_passes_are_distinct_then_derived_gap_blocks_seal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, bindings, _, events = _cleanup_adapter()
    receipts = _four_deletes(adapter, bindings)
    assert all(type(receipt) is ManagedHttpPolicyDeleteReceipt for receipt in receipts)
    assert len({id(receipt) for receipt in receipts}) == 4
    assert events == [
        ("infinity", "GET /v1/facts"),
        ("infinity", "DELETE /v1/facts/fact-1"),
        ("infinity", "GET /v1/facts"),
        ("mem0", "DELETE /memories"),
        ("infinity", "GET /v1/facts"),
        ("infinity", "GET /v1/facts"),
        ("mem0", "DELETE /memories"),
    ]
    monkeypatch.setattr(policy, "_attestation", lambda *args: None)
    with pytest.raises(
        ManagedHttpPolicyLifecycleError,
        match="^managed_http_policy_infinity_derived_absence_unprovable$",
    ):
        adapter.seal_terminal_delete(
            bindings=bindings,
            managed_attestation=object(),
            managed_attestation_commitment_sha256="6" * 64,
            receipts=receipts,
        )
    with pytest.raises(ManagedHttpPolicyLifecycleError, match="receipt_replay"):
        adapter.seal_terminal_delete(
            bindings=bindings,
            managed_attestation=object(),
            managed_attestation_commitment_sha256="6" * 64,
            receipts=receipts,
        )


def test_partial_delete_evidence_and_extra_mem0_fields_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, bindings, _, _ = _cleanup_adapter()
    receipts = _four_deletes(adapter, bindings)
    monkeypatch.setattr(policy, "_attestation", lambda *args: None)
    with pytest.raises(ManagedHttpPolicyLifecycleError, match="coverage_invalid"):
        adapter.seal_terminal_delete(
            bindings=bindings,
            managed_attestation=object(),
            managed_attestation_commitment_sha256="6" * 64,
            receipts=receipts[:3],
        )

    def infinity(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [], "next_cursor": None})

    def bad_mem0(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"deleted": True, "verified_absent": True, "trace": "not allowed"},
        )

    bad, bad_bindings, _ = _adapter(
        infinity_transports=(httpx.MockTransport(infinity), httpx.MockTransport(infinity)),
        mem0_transports=(httpx.MockTransport(bad_mem0), httpx.MockTransport(bad_mem0)),
    )
    first_target, second_target = bad_bindings.backend_targets
    bad.terminal_delete(
        bindings=bad_bindings,
        backend_role=first_target.backend_role,
        target_identity_sha256=first_target.target_identity_sha256,
        pass_index=1,
    )
    with pytest.raises(ManagedHttpPolicyLifecycleError, match="mem0_delete_ack_invalid"):
        bad.terminal_delete(
            bindings=bad_bindings,
            backend_role=second_target.backend_role,
            target_identity_sha256=second_target.target_identity_sha256,
            pass_index=1,
        )


def test_concurrent_same_delete_lane_has_exactly_one_http_winner() -> None:
    infinity, mem0, events = _cleanup_handlers()
    adapter, bindings, _ = _adapter(
        infinity_transports=(httpx.MockTransport(infinity), httpx.MockTransport(infinity)),
        mem0_transports=(httpx.MockTransport(mem0), httpx.MockTransport(mem0)),
    )
    target = bindings.backend_targets[0]

    def attempt() -> object:
        try:
            return adapter.terminal_delete(
                bindings=bindings,
                backend_role=target.backend_role,
                target_identity_sha256=target.target_identity_sha256,
                pass_index=1,
            )
        except ManagedHttpPolicyLifecycleError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(lambda _: attempt(), range(2)))
    assert sum(type(result) is ManagedHttpPolicyDeleteReceipt for result in results) == 1
    assert sum(result == "managed_http_policy_delete_order_invalid" for result in results) == 1
    assert sum(event == ("infinity", "DELETE /v1/facts/fact-1") for event in events) == 1


def test_document_cleanup_and_secret_bearing_transport_failure_are_sanitized() -> None:
    longmem, long_bindings, _ = _adapter(
        case=_longmem_case(),
        infinity_transports=(httpx.MockTransport(lambda request: httpx.Response(500)), None),
    )
    target = long_bindings.backend_targets[0]
    with pytest.raises(
        ManagedHttpPolicyLifecycleError,
        match="^managed_http_policy_infinity_document_delete_unprovable$",
    ):
        longmem.terminal_delete(
            bindings=long_bindings,
            backend_role=target.backend_role,
            target_identity_sha256=target.target_identity_sha256,
            pass_index=1,
        )

    def explode(request: httpx.Request) -> httpx.Response:
        raise RuntimeError(_SECRET_INFINITY + _SECRET_MEM0)

    adapter, bindings, _ = _adapter(
        infinity_transports=(httpx.MockTransport(explode), None),
    )
    target = bindings.backend_targets[0]
    with pytest.raises(ManagedHttpPolicyLifecycleError) as caught:
        adapter.terminal_delete(
            bindings=bindings,
            backend_role=target.backend_role,
            target_identity_sha256=target.target_identity_sha256,
            pass_index=1,
        )
    assert str(caught.value) == "managed_http_policy_infinity_context_delete_failed"
    assert _SECRET_INFINITY not in str(caught.value)
    assert _SECRET_MEM0 not in str(caught.value)


def test_transport_reuse_and_binding_tamper_are_rejected() -> None:
    shared = httpx.MockTransport(lambda request: httpx.Response(200, json={"data": []}))
    with pytest.raises(ManagedHttpPolicyLifecycleError, match="transport_ownership_invalid"):
        _adapter(infinity_transports=(shared, shared))

    adapter, bindings, _ = _adapter()
    object.__setattr__(bindings, "run_id", "substituted-run")
    with pytest.raises(ManagedHttpPolicyLifecycleError, match="binding_changed"):
        adapter.terminal_delete(
            bindings=bindings,
            backend_role="infinity-context",
            target_identity_sha256=_INFINITY_TARGET,
            pass_index=1,
        )

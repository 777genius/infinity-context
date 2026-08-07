from __future__ import annotations

import pytest
from infinity_context_server.memory_comparison_managed_mem0_v5_http_lane import (
    ManagedMem0V5HttpLane,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestProjector,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_request_binding import (
    ManagedMem0V5RequestBindingV2Context,
)
from infinity_context_server.memory_comparison_managed_run_contract import (
    ManagedRunCase,
    ManagedRunError,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    Mem0OssAdmissionRequest,
    Mem0OssFullRunAdmission,
    canonical_sha256,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_http import Mem0V5HttpError
from test_memory_comparison_managed_mem0_v5_http_checkpoint import (
    _Bearer,
    _Binding,
    _Response,
    _signed,
    _verifier,
)


def _request_binding_v2(
    context: ManagedMem0V5RequestBindingV2Context,
    *,
    request_body_sha256: str = "9" * 64,
) -> dict[str, object]:
    evidence = {**context.evidence_payload(), "request_body_sha256": request_body_sha256}
    unsigned = {
        **evidence,
        "request_binding_evidence_sha256": canonical_sha256(evidence),
    }
    return _signed(unsigned, b"request-binding/v2", "request_binding_hmac_sha256")


class _SequenceTransport:
    def __init__(self, payloads: list[dict[str, object]]) -> None:
        self.payloads = payloads
        self.calls: list[str] = []

    def request(self, _method: str, url: str, **_kwargs: object) -> _Response:
        self.calls.append(url)
        return _Response(self.payloads.pop(0))


class _DispatchGuard:
    def __init__(self, transport: _SequenceTransport, *, fail: bool = False) -> None:
        self.transport = transport
        self.fail = fail
        self.claims: list[dict[str, str]] = []

    def claim(self, **kwargs: str) -> None:
        assert len(self.transport.calls) == 1
        assert self.transport.calls[0].endswith("/v5/operations/request-binding")
        self.claims.append(kwargs)
        if self.fail:
            raise ManagedRunError("dispatch already claimed")


def _dispatch_authority() -> tuple[object, object, str]:
    corpus_id = "locomo-corpus-" + "a" * 64
    record = {
        "schema_version": "memory-comparison-managed-corpus.v2",
        "benchmark": "locomo",
        "corpus_id": corpus_id,
        "thread_id": "locomo-thread-" + "b" * 64,
        "memories": [
            {
                "kind": "fact",
                "role": "user",
                "session_alias": "session-0001",
                "source_alias": "memory-000001",
                "speaker": "Alice",
                "session_date": "2024-03-10",
                "text": "Alice likes tea.",
                "timestamp": 1,
            }
        ],
        "documents": [],
        "conversations": [],
    }
    authority = ManagedMem0V5ManifestProjector().project(
        (ManagedRunCase("case-1", corpus_id, record),),
        current_date="2026-08-07",
    )
    request = Mem0OssAdmissionRequest(
        run_id="dispatch-guard",
        route_sha256="3" * 64,
        credential_binding_sha256="4" * 64,
        model="gpt-5.6-sol",
        reasoning_effort="medium",
        service_tier="priority",
        runtime_source_revision="revision-1",
        runtime_source_sha256="5" * 64,
        runtime_base_sha256="6" * 64,
        expected_operation_count=1,
    )
    admission = Mem0OssFullRunAdmission(
        request=request,
        ingestion_manifest_sha256=authority.ingestion_manifest_sha256,
        ingestion_root_sha256=authority.ingestion_root_sha256,
        ingestion_unit_count=1,
    )
    operation_id = canonical_sha256(
        {
            "admission_commitment_sha256": admission.commitment_sha256,
            "unit_index": 0,
            "unit_identity_sha256": authority.units[0].unit_identity_sha256,
        }
    )
    return authority, admission, operation_id


@pytest.mark.parametrize("mode", ("guard", "no-guard", "guard-fails"))
def test_dispatch_collects_authenticated_v2_binding_only_after_success(mode: str) -> None:
    authority, admission, operation_id = _dispatch_authority()
    context = ManagedMem0V5RequestBindingV2Context.from_authority(
        authority=authority,
        unit=authority.units[0],
        operation_id_sha256=operation_id,
        admission=admission,
    )
    transport = _SequenceTransport(
        [
            _request_binding_v2(context),
            {
                "admission_commitment_sha256": admission.commitment_sha256,
                "operation_id_sha256": operation_id,
                "runtime_receipt": {},
            },
        ]
    )
    guard = None if mode == "no-guard" else _DispatchGuard(transport, fail=mode == "guard-fails")
    lane = ManagedMem0V5HttpLane(
        origin="http://127.0.0.1:19091",
        bearer_capability=_Bearer(),
        timeout_seconds=1,
        evidence_verifier=_verifier(),
        dispatch_binding=_verifier(),
        cleanup_binding=_Binding(),
        dispatch_guard=guard,
        transport=transport,
    )
    values = {
        "authority": authority,
        "unit": authority.units[0],
        "operation_id_sha256": operation_id,
        "admission": admission,
    }
    if mode == "guard-fails":
        with pytest.raises(ManagedRunError, match="already claimed"):
            lane.dispatch(**values)
        assert len(transport.calls) == 1
        assert lane.transport_observations == ()
    else:
        lane.dispatch(**values)
        assert len(transport.calls) == 2
        assert transport.calls[1].endswith("/v5/operations/dispatch")
        assert len(lane.transport_observations) == 1
    if guard is not None:
        assert guard.claims[0]["request_body_sha256"] == "9" * 64


def test_status_rebuilds_transport_observation_idempotently_and_rejects_drift() -> None:
    authority, admission, operation_id = _dispatch_authority()
    context = ManagedMem0V5RequestBindingV2Context.from_authority(
        authority=authority,
        unit=authority.units[0],
        operation_id_sha256=operation_id,
        admission=admission,
    )
    transport = _SequenceTransport(
        [
            _request_binding_v2(context),
            _request_binding_v2(context),
            _request_binding_v2(context, request_body_sha256="8" * 64),
        ]
    )
    lane = ManagedMem0V5HttpLane(
        origin="http://127.0.0.1:19091",
        bearer_capability=_Bearer(),
        timeout_seconds=1,
        evidence_verifier=_verifier(),
        dispatch_binding=_verifier(),
        cleanup_binding=_Binding(),
        transport=transport,
    )

    class Control:
        calls = 0

        def status(self, _request: object) -> object:
            self.calls += 1
            return {"receipt": "status"}

    control = Control()
    object.__setattr__(lane, "_control", control)
    values = {
        "authority": authority,
        "unit": authority.units[0],
        "operation_id_sha256": operation_id,
        "admission": admission,
    }
    assert lane.status(**values) == {"receipt": "status"}
    assert lane.status(**values) == {"receipt": "status"}
    assert len(lane.transport_observations) == 1
    with pytest.raises(ManagedRunError, match="readback differs"):
        lane.status(**values)
    assert control.calls == 3

    missing_lane = ManagedMem0V5HttpLane(
        origin="http://127.0.0.1:19091",
        bearer_capability=_Bearer(),
        timeout_seconds=1,
        evidence_verifier=_verifier(),
        dispatch_binding=_verifier(),
        cleanup_binding=_Binding(),
        transport=_SequenceTransport([{}]),
    )
    object.__setattr__(missing_lane, "_control", Control())
    with pytest.raises(Mem0V5HttpError):
        missing_lane.status(**values)

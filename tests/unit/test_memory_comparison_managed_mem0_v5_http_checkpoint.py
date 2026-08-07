from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import replace
from pathlib import Path

import infinity_context_server.memory_comparison_managed_mem0_v5_http_lane as http_lane_module
import pytest
from infinity_context_server.memory_comparison_managed_mem0_v5_checkpoint import (
    AtomicJsonManagedMem0V5CheckpointStore,
    HmacSha256ManagedMem0V5CheckpointSigner,
    ManagedMem0V5Checkpoint,
    ManagedMem0V5CheckpointError,
    ManagedMem0V5CheckpointPhase,
    ManagedMem0V5CheckpointUnit,
    ManagedMem0V5RecoveryAction,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_http_lane import (
    HmacSha256ManagedMem0V5EvidenceVerifier,
    ManagedMem0V5HttpLane,
    ManagedMem0V5SearchVerificationContext,
    ManagedMem0V5StorageVerificationContext,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestProjector,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_request_binding import (
    ManagedMem0V5RequestBindingContext,
    ManagedMem0V5RequestBindingReceipt,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_storage_witness import (
    create_managed_mem0_v5_storage_witness_authority,
)
from infinity_context_server.memory_comparison_managed_run_contract import (
    ManagedRunCase,
    ManagedRunError,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    CleanupVerificationContext,
    Mem0OssAdmissionRequest,
    Mem0OssFullRunAdmission,
    canonical_sha256,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_http import Mem0V5HttpError

KEY = b"k" * 32
AUTHORITY = "a" * 64
ADMISSION = "b" * 64
OPERATION = "c" * 64
UNIT = "d" * 64
SCOPE = "e" * 64
SOURCE_SHA = "f" * 64
RECEIPT = "1" * 64
OBSERVATION = "2" * 64


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _evidence_key(domain: bytes) -> bytes:
    root = hmac.new(KEY, b"mem0-oss-adapter-v5/evidence-key/v1", hashlib.sha256).digest()
    return hmac.new(root, domain, hashlib.sha256).digest()


def _signed(payload: dict[str, object], domain: bytes, field: str) -> dict[str, object]:
    return {
        **payload,
        field: hmac.new(_evidence_key(domain), _canonical(payload), hashlib.sha256).hexdigest(),
    }


class _EvidenceKey:
    def __init__(self) -> None:
        self.calls = 0

    def consume(self) -> bytes:
        self.calls += 1
        if self.calls != 1:
            raise AssertionError("evidence key consumed more than once")
        return KEY


_DESCRIPTOR_SECRET = "descriptor-secret-must-not-leak"


class _RaisingDescriptor:
    def __get__(self, instance: object, owner: type[object]) -> object:
        raise RuntimeError(_DESCRIPTOR_SECRET)


class _RaisingConsumeCapability:
    consume = _RaisingDescriptor()

    def __init__(self) -> None:
        self.calls = 0


def _noop(*_args: object, **_kwargs: object) -> None:
    return None


def _raising_collaborator(attribute: str, *, before: tuple[str, ...] = ()) -> object:
    attributes: dict[str, object] = {name: _noop for name in before}
    attributes[attribute] = _RaisingDescriptor()
    return type("_RaisingCollaborator", (), attributes)()


def test_evidence_key_raising_consume_descriptor_is_safe() -> None:
    capability = _RaisingConsumeCapability()
    issuer, _ = create_managed_mem0_v5_storage_witness_authority()
    with pytest.raises(Mem0V5HttpError) as raised:
        HmacSha256ManagedMem0V5EvidenceVerifier(
            key_capability=capability,
            storage_witness_issuer=issuer,
        )
    assert raised.value.code == "mem0_v5_http_configuration_invalid"
    assert str(raised.value) == "mem0_v5_http_configuration_invalid"
    assert capability.calls == 0


def test_invalid_storage_witness_issuer_does_not_consume_evidence_key() -> None:
    capability = _EvidenceKey()
    with pytest.raises(Mem0V5HttpError, match="configuration_invalid"):
        HmacSha256ManagedMem0V5EvidenceVerifier(
            key_capability=capability,
            storage_witness_issuer=object(),
        )
    assert capability.calls == 0


def _verifier() -> HmacSha256ManagedMem0V5EvidenceVerifier:
    issuer, _ = create_managed_mem0_v5_storage_witness_authority()
    return HmacSha256ManagedMem0V5EvidenceVerifier(
        key_capability=_EvidenceKey(), storage_witness_issuer=issuer
    )


def _observation(records: list[dict[str, object]]) -> dict[str, object]:
    unsigned = {
        "schema_version": "mem0-oss-adapter-v5.storage-observation.v1",
        "admission_commitment_sha256": ADMISSION,
        "operation_id_sha256": OPERATION,
        "scope_sha256": SCOPE,
        "source_id": "source-1",
        "source_sha256": SOURCE_SHA,
        "storage_commitment_sha256": OBSERVATION,
        "record_count": len(records),
        "record_root_sha256": canonical_sha256({"records": records}),
        "records": records,
    }
    return _signed(unsigned, b"storage-observation/v1", "observation_hmac_sha256")


def _search(query: str, results: list[dict[str, object]]) -> dict[str, object]:
    unsigned = {
        "schema_version": "mem0-oss-adapter-v5.scoped-search.v1",
        "admission_commitment_sha256": ADMISSION,
        "corpus_id": "corpus-1",
        "query_commitment_sha256": canonical_sha256({"query": query}),
        "limit": 5,
        "result_count": len(results),
        "result_root_sha256": canonical_sha256({"results": results}),
        "results": results,
    }
    return _signed(unsigned, b"scoped-search/v1", "search_hmac_sha256")


def _admission() -> Mem0OssFullRunAdmission:
    request = Mem0OssAdmissionRequest(
        run_id="run-1",
        route_sha256="3" * 64,
        credential_binding_sha256="4" * 64,
        model="gpt-5.6-sol",
        reasoning_effort="high",
        service_tier="default",
        runtime_source_revision="revision-1",
        runtime_source_sha256="5" * 64,
        runtime_base_sha256="6" * 64,
        expected_operation_count=1,
    )
    value = Mem0OssFullRunAdmission(
        request=request,
        ingestion_manifest_sha256="7" * 64,
        ingestion_root_sha256="8" * 64,
        ingestion_unit_count=1,
    )
    assert value.commitment_sha256 != ADMISSION
    return value


def test_storage_hmac_accepts_zero_records_and_binds_trusted_unit() -> None:
    verifier = _verifier()
    result = verifier.verify_storage(
        payload=_observation([]),
        context=ManagedMem0V5StorageVerificationContext(
            ADMISSION, OPERATION, UNIT, SCOPE, "source-1", SOURCE_SHA
        ),
    )
    assert result.created_record_ids == ()
    assert result.unit_identity_sha256 == UNIT
    assert result.source_pairs[0][0] == "source-1"


@pytest.mark.parametrize("field", ["scope_sha256", "record_count", "observation_hmac_sha256"])
def test_storage_hmac_or_shape_tamper_fails(field: str) -> None:
    payload = _observation([])
    payload[field] = 1 if field == "record_count" else "0" * 64
    with pytest.raises(Mem0V5HttpError):
        _verifier().verify_storage(
            payload=payload,
            context=ManagedMem0V5StorageVerificationContext(
                ADMISSION, OPERATION, UNIT, SCOPE, "source-1", SOURCE_SHA
            ),
        )


def test_search_receipt_is_authenticated_and_repr_hides_query_and_memory() -> None:
    query = "private exact query"
    memory = "private retrieved memory"
    results = [
        {
            "rank": 0,
            "record_id": "record-1",
            "memory": memory,
            "memory_sha256": hashlib.sha256(memory.encode()).hexdigest(),
            "source_id": "source-1",
            "source_sha256": SOURCE_SHA,
            "score": 0.75,
        }
    ]
    context = ManagedMem0V5SearchVerificationContext(ADMISSION, "corpus-1", query, 5)
    receipt = _verifier().verify_search(payload=_search(query, results), context=context)
    assert receipt.records[0].memory == memory
    assert query not in repr(context)
    assert memory not in repr(receipt.records[0])
    assert "query" not in receipt.__dataclass_fields__


def test_search_query_binding_and_hmac_tamper_fail() -> None:
    payload = _search("q1", [])
    context = ManagedMem0V5SearchVerificationContext(ADMISSION, "corpus-1", "q2", 5)
    with pytest.raises(Mem0V5HttpError):
        _verifier().verify_search(payload=payload, context=context)
    payload["result_count"] = 1
    with pytest.raises(Mem0V5HttpError):
        _verifier().verify_search(
            payload=payload,
            context=ManagedMem0V5SearchVerificationContext(ADMISSION, "corpus-1", "q1", 5),
        )


class _Bearer:
    def __init__(self) -> None:
        self.calls = 0

    def consume(self) -> str:
        self.calls += 1
        if self.calls > 1:
            raise AssertionError("bearer consumed twice")
        return "s" * 32


class _Binding:
    def verify_request_binding(self, **_kwargs: object) -> ManagedMem0V5RequestBindingReceipt:
        return ManagedMem0V5RequestBindingReceipt("9" * 64, "8" * 64, "7" * 64)

    def cleanup_context(self, **kwargs: object) -> CleanupVerificationContext:
        admission = kwargs["admission"]
        seal = kwargs["seal"]
        aborting = kwargs["aborting"]
        return CleanupVerificationContext(
            admission.commitment_sha256,
            None if seal is None else seal.commitment_sha256,
            None if seal is None else seal.operation_root_sha256,
            "0" * 64,
            admission.request.expected_operation_count,
            aborting,
        )


@pytest.mark.parametrize(
    ("argument", "attribute", "before"),
    (
        ("evidence_verifier", "verify_storage", ()),
        ("evidence_verifier", "verify_search", ("verify_storage",)),
        ("dispatch_binding", "verify_request_binding", ()),
        ("cleanup_binding", "cleanup_context", ()),
        ("transport", "request", ()),
    ),
)
def test_http_lane_raising_collaborator_descriptor_is_safe_before_consume(
    argument: str, attribute: str, before: tuple[str, ...]
) -> None:
    bearer = _Bearer()
    kwargs = {
        "origin": "http://127.0.0.1:19091",
        "bearer_capability": bearer,
        "timeout_seconds": 1,
        "evidence_verifier": _verifier(),
        "dispatch_binding": _Binding(),
        "cleanup_binding": _Binding(),
        "transport": _Transport({}),
    }
    kwargs[argument] = _raising_collaborator(attribute, before=before)
    with pytest.raises(Mem0V5HttpError) as raised:
        ManagedMem0V5HttpLane(**kwargs)
    assert raised.value.code == "mem0_v5_http_configuration_invalid"
    assert str(raised.value) == "mem0_v5_http_configuration_invalid"
    assert _DESCRIPTOR_SECRET not in str(raised.value)
    assert bearer.calls == 0


def test_http_lane_raising_bearer_consume_descriptor_is_safe() -> None:
    bearer = _RaisingConsumeCapability()
    with pytest.raises(Mem0V5HttpError) as raised:
        ManagedMem0V5HttpLane(
            origin="http://127.0.0.1:19091",
            bearer_capability=bearer,
            timeout_seconds=1,
            evidence_verifier=_verifier(),
            dispatch_binding=_Binding(),
            cleanup_binding=_Binding(),
            transport=_Transport({}),
        )
    assert raised.value.code == "mem0_v5_http_configuration_invalid"
    assert _DESCRIPTOR_SECRET not in str(raised.value)
    assert bearer.calls == 0


def test_http_lane_raising_default_transport_constructor_is_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _RaisingDefaultTransport:
        def __init__(self) -> None:
            raise RuntimeError(_DESCRIPTOR_SECRET)

    bearer = _Bearer()
    monkeypatch.setattr(http_lane_module, "_HttpxTransport", _RaisingDefaultTransport)
    with pytest.raises(Mem0V5HttpError) as raised:
        ManagedMem0V5HttpLane(
            origin="http://127.0.0.1:19091",
            bearer_capability=bearer,
            timeout_seconds=1,
            evidence_verifier=_verifier(),
            dispatch_binding=_Binding(),
            cleanup_binding=_Binding(),
        )
    assert raised.value.code == "mem0_v5_http_configuration_invalid"
    assert _DESCRIPTOR_SECRET not in str(raised.value)
    assert bearer.calls == 0


class _InvalidBearerWithRaisingClose:
    close = _RaisingDescriptor()

    def __init__(self) -> None:
        self.calls = 0

    def consume(self) -> str:
        self.calls += 1
        return "short"


def test_http_lane_raising_close_does_not_mask_post_consume_primary_error() -> None:
    bearer = _InvalidBearerWithRaisingClose()
    with pytest.raises(Mem0V5HttpError) as raised:
        ManagedMem0V5HttpLane(
            origin="http://127.0.0.1:19091",
            bearer_capability=bearer,
            timeout_seconds=1,
            evidence_verifier=_verifier(),
            dispatch_binding=_Binding(),
            cleanup_binding=_Binding(),
            transport=_Transport({}),
        )
    assert raised.value.code == "mem0_v5_http_configuration_invalid"
    assert _DESCRIPTOR_SECRET not in str(raised.value)
    assert bearer.calls == 1


@pytest.mark.parametrize(
    "invalid",
    ("origin", "timeout", "evidence", "dispatch", "cleanup", "transport"),
)
def test_http_lane_invalid_non_secret_configuration_does_not_consume_bearer(
    invalid: str,
) -> None:
    bearer = _Bearer()
    kwargs = {
        "origin": "http://127.0.0.1:19091",
        "bearer_capability": bearer,
        "timeout_seconds": 1,
        "evidence_verifier": _verifier(),
        "dispatch_binding": _Binding(),
        "cleanup_binding": _Binding(),
        "transport": _Transport({}),
    }
    replacements = {
        "origin": ("origin", "https://example.test"),
        "timeout": ("timeout_seconds", 0),
        "evidence": ("evidence_verifier", object()),
        "dispatch": ("dispatch_binding", object()),
        "cleanup": ("cleanup_binding", object()),
        "transport": ("transport", object()),
    }
    name, value = replacements[invalid]
    kwargs[name] = value
    with pytest.raises(Mem0V5HttpError, match="configuration_invalid"):
        ManagedMem0V5HttpLane(**kwargs)
    assert bearer.calls == 0


def test_http_lane_default_transport_prevalidates_and_consumes_bearer_once() -> None:
    bearer = _Bearer()
    ManagedMem0V5HttpLane(
        origin="http://127.0.0.1:19091",
        bearer_capability=bearer,
        timeout_seconds=1,
        evidence_verifier=_verifier(),
        dispatch_binding=_Binding(),
        cleanup_binding=_Binding(),
    )
    assert bearer.calls == 1


class _Response:
    status_code = 200

    def __init__(self, payload: dict[str, object]) -> None:
        self.content = _canonical(payload)

    def read_bounded(self, maximum_bytes: int) -> bytes:
        if len(self.content) > maximum_bytes:
            raise ValueError("oversized")
        return self.content


class _Transport:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.calls: list[tuple[str, dict[str, object]]] = []

    def request(self, _method: str, url: str, **kwargs: object) -> _Response:
        self.calls.append((url, kwargs))
        return _Response(self.payload)


def test_http_search_consumes_bearer_once_and_binds_request_commitment() -> None:
    admission = _admission()
    query = "query"
    payload = _search(query, [])
    payload["admission_commitment_sha256"] = admission.commitment_sha256
    unsigned = {k: v for k, v in payload.items() if k != "search_hmac_sha256"}
    payload["search_hmac_sha256"] = hmac.new(
        _evidence_key(b"scoped-search/v1"), _canonical(unsigned), hashlib.sha256
    ).hexdigest()
    bearer = _Bearer()
    transport = _Transport(payload)
    lane = ManagedMem0V5HttpLane(
        origin="http://127.0.0.1:19091",
        bearer_capability=bearer,
        timeout_seconds=1,
        evidence_verifier=_verifier(),
        dispatch_binding=_Binding(),
        cleanup_binding=_Binding(),
        transport=transport,
    )
    receipt = lane.search(admission=admission, corpus_id="corpus-1", query=query, limit=5)
    assert receipt.records == ()
    assert bearer.calls == 1
    url, kwargs = transport.calls[0]
    assert url.endswith("/v5/runs/search")
    assert kwargs["headers"]["Authorization"] == "Bearer " + "s" * 32
    assert (
        kwargs["headers"]["X-Request-Commitment-SHA256"]
        == hashlib.sha256(kwargs["content"]).hexdigest()
    )
    assert "s" * 32 not in repr(lane)


def _request_binding(context: ManagedMem0V5RequestBindingContext) -> dict[str, object]:
    unsigned = {
        "schema_version": "mem0-oss-adapter-v5.request-binding.v1",
        "admission_commitment_sha256": context.admission_commitment_sha256,
        "ingestion_manifest_sha256": context.ingestion_manifest_sha256,
        "ingestion_root_sha256": context.ingestion_root_sha256,
        "current_date_commitment_sha256": context.current_date_commitment_sha256,
        "operation_id_sha256": context.operation_id_sha256,
        "unit_identity_sha256": context.unit_identity_sha256,
        "unit_sha256": context.unit_sha256,
        "scope_sha256": context.scope_sha256,
        "source_id": context.source_id,
        "source_sha256": context.source_sha256,
        "sequence": context.sequence,
        "request_body_sha256": "9" * 64,
        "response_format_sha256": "8" * 64,
    }
    return _signed(unsigned, b"request-binding/v1", "request_binding_hmac_sha256")


def test_request_binding_hmac_binds_exact_local_authority_tuple() -> None:
    context = ManagedMem0V5RequestBindingContext(
        ADMISSION,
        "7" * 64,
        "8" * 64,
        "9" * 64,
        OPERATION,
        UNIT,
        "3" * 64,
        SCOPE,
        "source-1",
        SOURCE_SHA,
        0,
    )
    receipt = _verifier().verify_request_binding(
        payload=_request_binding(context),
        context=context,
    )
    assert receipt.request_body_sha256 == "9" * 64
    assert receipt.response_format_sha256 == "8" * 64

    tampered = _request_binding(context)
    tampered["unit_sha256"] = "0" * 64
    with pytest.raises(Mem0V5HttpError):
        _verifier().verify_request_binding(payload=tampered, context=context)


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
def test_dispatch_guard_claims_authenticated_binding_before_post_and_is_optional(
    mode: str,
) -> None:
    authority, admission, operation_id = _dispatch_authority()
    context = ManagedMem0V5RequestBindingContext.from_authority(
        authority=authority,
        unit=authority.units[0],
        operation_id_sha256=operation_id,
        admission=admission,
    )
    transport = _SequenceTransport(
        [
            _request_binding(context),
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
    if mode == "guard-fails":
        with pytest.raises(ManagedRunError, match="already claimed"):
            lane.dispatch(
                authority=authority,
                unit=authority.units[0],
                operation_id_sha256=operation_id,
                admission=admission,
            )
        assert len(transport.calls) == 1
    else:
        lane.dispatch(
            authority=authority,
            unit=authority.units[0],
            operation_id_sha256=operation_id,
            admission=admission,
        )
        assert len(transport.calls) == 2
        assert transport.calls[1].endswith("/v5/operations/dispatch")
    if guard is not None:
        assert guard.claims == [
            {
                "admission_commitment_sha256": admission.commitment_sha256,
                "operation_id_sha256": operation_id,
                "request_body_sha256": "9" * 64,
            }
        ]


def _unit(phase: ManagedMem0V5CheckpointPhase) -> ManagedMem0V5CheckpointUnit:
    if phase in {
        ManagedMem0V5CheckpointPhase.RESERVED,
        ManagedMem0V5CheckpointPhase.DISPATCH_ATTEMPTED,
        ManagedMem0V5CheckpointPhase.OUTCOME_UNKNOWN,
    }:
        return ManagedMem0V5CheckpointUnit(0, OPERATION, phase)
    if phase is ManagedMem0V5CheckpointPhase.RECEIPT_VERIFIED:
        return ManagedMem0V5CheckpointUnit(0, OPERATION, phase, RECEIPT)
    return ManagedMem0V5CheckpointUnit(0, OPERATION, phase, RECEIPT, OBSERVATION, ())


def _checkpoint(
    signer: HmacSha256ManagedMem0V5CheckpointSigner,
    phase: ManagedMem0V5CheckpointPhase,
    *,
    generation: int = 0,
    previous: str | None = None,
) -> ManagedMem0V5Checkpoint:
    return ManagedMem0V5Checkpoint.create(
        authority_commitment_sha256=AUTHORITY,
        admission_commitment_sha256=ADMISSION,
        generation=generation,
        previous_checkpoint_commitment_sha256=previous,
        units=(_unit(phase),),
        signer=signer,
    )


def test_restart_plan_never_blindly_redispatches_attempted_work() -> None:
    signer = HmacSha256ManagedMem0V5CheckpointSigner(key=KEY)
    phases = tuple(ManagedMem0V5CheckpointPhase)
    actions = tuple(_checkpoint(signer, phase).recovery_plan()[0] for phase in phases)
    assert actions == (
        ManagedMem0V5RecoveryAction.DISPATCH,
        ManagedMem0V5RecoveryAction.STATUS,
        ManagedMem0V5RecoveryAction.STATUS,
        ManagedMem0V5RecoveryAction.STORAGE,
        ManagedMem0V5RecoveryAction.COMMIT_LOCAL,
        ManagedMem0V5RecoveryAction.NONE,
    )


def test_checkpoint_atomic_roundtrip_stale_writer_and_external_head(tmp_path: Path) -> None:
    signer = HmacSha256ManagedMem0V5CheckpointSigner(key=KEY)
    store = AtomicJsonManagedMem0V5CheckpointStore(path=tmp_path / "state.json", signer=signer)
    first = _checkpoint(signer, ManagedMem0V5CheckpointPhase.RESERVED)
    store.save(first, expected_previous_commitment_sha256=None)
    second = _checkpoint(
        signer,
        ManagedMem0V5CheckpointPhase.DISPATCH_ATTEMPTED,
        generation=1,
        previous=first.checkpoint_commitment_sha256,
    )
    store.save(second, expected_previous_commitment_sha256=first.checkpoint_commitment_sha256)
    stale = _checkpoint(
        signer,
        ManagedMem0V5CheckpointPhase.OUTCOME_UNKNOWN,
        generation=1,
        previous=first.checkpoint_commitment_sha256,
    )
    competing_store = AtomicJsonManagedMem0V5CheckpointStore(
        path=tmp_path / "state.json", signer=signer
    )
    with pytest.raises(ManagedMem0V5CheckpointError, match="conflict"):
        competing_store.save(
            stale, expected_previous_commitment_sha256=first.checkpoint_commitment_sha256
        )
    assert (
        store.load(
            expected_authority_commitment_sha256=AUTHORITY,
            expected_admission_commitment_sha256=ADMISSION,
            expected_checkpoint_commitment_sha256=second.checkpoint_commitment_sha256,
        )
        == second
    )
    with pytest.raises(ManagedMem0V5CheckpointError, match="rollback_detected"):
        store.load(
            expected_authority_commitment_sha256=AUTHORITY,
            expected_admission_commitment_sha256=ADMISSION,
            expected_checkpoint_commitment_sha256=first.checkpoint_commitment_sha256,
        )
    assert (tmp_path / "state.json.lock").stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("mutation", ["truncate", "tamper"])
def test_checkpoint_corruption_fails_closed(tmp_path: Path, mutation: str) -> None:
    signer = HmacSha256ManagedMem0V5CheckpointSigner(key=KEY)
    path = tmp_path / "state.json"
    store = AtomicJsonManagedMem0V5CheckpointStore(path=path, signer=signer)
    first = _checkpoint(signer, ManagedMem0V5CheckpointPhase.RESERVED)
    store.save(first, expected_previous_commitment_sha256=None)
    if mutation == "truncate":
        path.write_text("{", encoding="utf-8")
    else:
        payload = json.loads(path.read_text())
        payload["generation"] = 8
        path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ManagedMem0V5CheckpointError):
        store.load(
            expected_authority_commitment_sha256=AUTHORITY,
            expected_admission_commitment_sha256=ADMISSION,
        )


def test_checkpoint_rejects_symlink_and_contains_no_private_fields(tmp_path: Path) -> None:
    signer = HmacSha256ManagedMem0V5CheckpointSigner(key=KEY)
    target = tmp_path / "target"
    target.write_text("{}", encoding="utf-8")
    path = tmp_path / "state.json"
    swapped_store = AtomicJsonManagedMem0V5CheckpointStore(path=path, signer=signer)
    os.symlink(target, path)
    with pytest.raises(ManagedMem0V5CheckpointError, match="path_invalid"):
        swapped_store.load(
            expected_authority_commitment_sha256=AUTHORITY,
            expected_admission_commitment_sha256=ADMISSION,
        )

    lock_target = tmp_path / "lock-target"
    lock_target.write_text("", encoding="utf-8")
    clean_path = tmp_path / "clean.json"
    lock_path = clean_path.with_name(clean_path.name + ".lock")
    clean_store = AtomicJsonManagedMem0V5CheckpointStore(path=clean_path, signer=signer)
    os.symlink(lock_target, lock_path)
    with pytest.raises(ManagedMem0V5CheckpointError, match="lock_failed"):
        clean_store.load(
            expected_authority_commitment_sha256=AUTHORITY,
            expected_admission_commitment_sha256=ADMISSION,
        )

    payload = _checkpoint(signer, ManagedMem0V5CheckpointPhase.RESERVED).payload()
    rendered = json.dumps(payload)
    for forbidden in ("query", "memory", "bearer", "source_messages", "gold"):
        assert forbidden not in rendered


def test_checkpoint_detects_lock_inode_replacement_while_held(tmp_path: Path) -> None:
    signer = HmacSha256ManagedMem0V5CheckpointSigner(key=KEY)
    path = tmp_path / "state.json"
    store = AtomicJsonManagedMem0V5CheckpointStore(path=path, signer=signer)
    lock_path = path.with_name(path.name + ".lock")
    with (
        pytest.raises(ManagedMem0V5CheckpointError, match="lock_replaced"),
        store._locked(),  # noqa: SLF001 - adversarial inode replacement test
    ):
        lock_path.unlink()
        lock_path.write_text("", encoding="utf-8")


def test_zero_record_observation_inventory_is_sticky(tmp_path: Path) -> None:
    signer = HmacSha256ManagedMem0V5CheckpointSigner(key=KEY)
    store = AtomicJsonManagedMem0V5CheckpointStore(path=tmp_path / "state.json", signer=signer)
    first = _checkpoint(signer, ManagedMem0V5CheckpointPhase.STORAGE_VERIFIED)
    store.save(first, expected_previous_commitment_sha256=None)
    changed_unit = replace(first.units[0], record_ids=("late-record",))
    changed = ManagedMem0V5Checkpoint.create(
        authority_commitment_sha256=AUTHORITY,
        admission_commitment_sha256=ADMISSION,
        generation=1,
        previous_checkpoint_commitment_sha256=first.checkpoint_commitment_sha256,
        units=(changed_unit,),
        signer=signer,
    )
    with pytest.raises(ManagedMem0V5CheckpointError, match="regression"):
        store.save(
            changed,
            expected_previous_commitment_sha256=first.checkpoint_commitment_sha256,
        )


def test_checkpoint_hmac_tamper_and_phase_regression_fail(tmp_path: Path) -> None:
    signer = HmacSha256ManagedMem0V5CheckpointSigner(key=KEY)
    first = _checkpoint(signer, ManagedMem0V5CheckpointPhase.DISPATCH_ATTEMPTED)
    forged = replace(first, checkpoint_hmac_sha256="0" * 64)
    store = AtomicJsonManagedMem0V5CheckpointStore(path=tmp_path / "state.json", signer=signer)
    with pytest.raises(ManagedMem0V5CheckpointError, match="unauthenticated"):
        store.save(forged, expected_previous_commitment_sha256=None)
    store.save(first, expected_previous_commitment_sha256=None)
    backward = _checkpoint(
        signer,
        ManagedMem0V5CheckpointPhase.RESERVED,
        generation=1,
        previous=first.checkpoint_commitment_sha256,
    )
    with pytest.raises(ManagedMem0V5CheckpointError, match="regression"):
        store.save(backward, expected_previous_commitment_sha256=first.checkpoint_commitment_sha256)


def test_server_storage_verifier_binds_memory_and_storage_commitments() -> None:
    memory_sha = hashlib.sha256(b"memory").hexdigest()
    records = [
        {
            "record_id": "record-1",
            "extraction_memory_id": "memory-1",
            "source_id": "source-1",
            "source_sha256": SOURCE_SHA,
            "memory_sha256": memory_sha,
        }
    ]
    payload = _observation(records)
    result = _verifier().verify_storage(
        payload=payload,
        context=ManagedMem0V5StorageVerificationContext(
            ADMISSION, OPERATION, UNIT, SCOPE, "source-1", SOURCE_SHA
        ),
    )
    assert result.created_record_ids == ("record-1",)
    assert result.storage_commitment_sha256 == OBSERVATION
    payload["records"][0]["memory_sha256"] = "0" * 64
    with pytest.raises(Mem0V5HttpError):
        _verifier().verify_storage(
            payload=payload,
            context=ManagedMem0V5StorageVerificationContext(
                ADMISSION, OPERATION, UNIT, SCOPE, "source-1", SOURCE_SHA
            ),
        )


def test_evidence_key_capability_is_consumed_once_and_exposes_only_commitment() -> None:
    capability = _EvidenceKey()
    issuer, _ = create_managed_mem0_v5_storage_witness_authority()
    verifier = HmacSha256ManagedMem0V5EvidenceVerifier(
        key_capability=capability, storage_witness_issuer=issuer
    )
    assert capability.calls == 1
    assert verifier.key_commitment_sha256 == hashlib.sha256(KEY).hexdigest()
    assert KEY.hex() not in repr(verifier)


class _OversizedBoundedResponse:
    status_code = 200

    @property
    def content(self) -> bytes:
        raise AssertionError("unbounded content access is forbidden")

    def read_bounded(self, maximum_bytes: int) -> bytes:
        chunks = (b"x" * 100_000, b"y" * 100_000, b"z" * 100_000)
        collected = bytearray()
        for chunk in chunks:
            if len(collected) + len(chunk) > maximum_bytes:
                raise ValueError("oversized chunked response")
            collected.extend(chunk)
        return bytes(collected)


class _OversizedTransport:
    def request(self, *_args: object, **_kwargs: object) -> _OversizedBoundedResponse:
        return _OversizedBoundedResponse()


def test_http_lane_rejects_oversized_chunked_response_without_content_buffering() -> None:
    bearer = _Bearer()
    lane = ManagedMem0V5HttpLane(
        origin="http://127.0.0.1:19091",
        bearer_capability=bearer,
        timeout_seconds=1,
        evidence_verifier=_verifier(),
        dispatch_binding=_Binding(),
        cleanup_binding=_Binding(),
        transport=_OversizedTransport(),
    )
    with pytest.raises(Mem0V5HttpError, match="remote_failed"):
        lane.search(
            admission=_admission(),
            corpus_id="corpus-1",
            query="query",
            limit=5,
        )
    assert bearer.calls == 1

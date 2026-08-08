from __future__ import annotations

# ruff: noqa: E402 - the external Phase C package is an explicit test-only path.
import hashlib
import hmac
import json
import os
import sys
from dataclasses import fields, replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PHASE_C_ROOT = ROOT / "benchmarks" / "phase-c-canary"
sys.path.insert(0, str(PHASE_C_ROOT))

import phase_c_canary.runtime_binding as runtime_binding_module
from infinity_context_server import memory_comparison_managed_mem0_v5_composition as subject
from infinity_context_server.memory_comparison_bounded_httpx_transport import (
    BoundedHttpResponse,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_checkpoint import (
    ManagedMem0V5RunPhase,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_clean_state_http import (
    ManagedMem0V5HmacDurableCleanStateFactory,
    ManagedMem0V5HttpCleanStateSnapshotFactory,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_credentials import (
    ManagedMem0V5CredentialPaths,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_dispatch_guard import (
    AtomicJournalManagedMem0V5SingleDispatchGuard,
    create_managed_mem0_v5_single_dispatch_guard,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_lane import (
    ManagedMem0V5BudgetPolicy,
    ManagedMem0V5LaneCoordinator,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestProjector,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_request_binding import (
    REQUEST_BINDING_V2_DOMAIN,
    ManagedMem0V5RequestBindingV2Context,
    verify_request_binding_v2_payload,
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
from infinity_context_server.memory_comparison_mem0_oss_v5_http import (
    Mem0V5HttpError,
    Mem0V5OperationReceiptAuthority,
    Mem0V5ReceiptAuthority,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_observed_receipt import (
    Mem0V5ObservedExtractionOperationAuthority,
    Mem0V5ObservedExtractionReceiptAuthority,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_run import Mem0OssFullRunService
from phase_c_canary.runtime_receipt_v2 import RuntimeReceiptV2Boundary
from test_memory_comparison_managed_mem0_v5_recovery import (
    _CleanupPort,
    _ReceiptPort,
    _StoragePort,
)


def _sha(value: str | bytes) -> str:
    raw = value if type(value) is bytes else value.encode()  # noqa: E721
    return hashlib.sha256(raw).hexdigest()


class _UnusedReceiptHmacVerifier:
    def __init__(self) -> None:
        self.calls = 0

    def verify(self, **kwargs) -> None:
        self.calls += 1
        raise AssertionError(kwargs)


class _Transport:
    def __init__(self, evidence_key: bytes, authority: object) -> None:
        self.calls: list[str] = []
        self.evidence_key = evidence_key
        self.authority = authority

    def request(self, method, url, **kwargs):
        assert method == "POST"
        body = json.loads(kwargs["content"])
        self.calls.append(url)
        if url.endswith("/v5/runs/admit"):
            payload = {
                "admission_commitment_sha256": body["admission_commitment_sha256"],
                "runtime_binding_commitment_sha256": _sha("runtime-binding"),
                "accepted": True,
            }
        else:
            assert url.endswith("/v5/runs/clean-state")
            base = {
                "schema_version": "mem0-oss-adapter-v5.clean-state.v1",
                "admission_commitment_sha256": body["admission_commitment_sha256"],
                "run_id_sha256": body["run_id_sha256"],
                "authority_commitment_sha256": body["authority_commitment_sha256"],
                "ingestion_manifest_sha256": self.authority.ingestion_manifest_sha256,
                "ingestion_root_sha256": self.authority.ingestion_root_sha256,
                "runtime_binding_commitment_sha256": _sha("runtime-binding"),
                "request_commitment_sha256": canonical_sha256(body),
                "request_id_sha256": kwargs["headers"]["Idempotency-Key"],
                "scope_count": len(body["scopes"]),
                "scope_inventory_root_sha256": canonical_sha256({"scopes": body["scopes"]}),
                "scopes": body["scopes"],
            }
            unsigned = {**base, "evidence_commitment_sha256": canonical_sha256(base)}
            root = hmac.new(
                self.evidence_key,
                b"mem0-oss-adapter-v5/evidence-key/v1",
                hashlib.sha256,
            ).digest()
            signing_key = hmac.new(root, b"clean-state/v1", hashlib.sha256).digest()
            payload = {
                **unsigned,
                "clean_state_hmac_sha256": hmac.new(
                    signing_key,
                    json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode(),
                    hashlib.sha256,
                ).hexdigest(),
            }
        return BoundedHttpResponse(200, json.dumps(payload).encode())


def _cases() -> tuple[ManagedRunCase, ...]:
    corpus_id = f"locomo-corpus-{'a' * 64}"
    record = {
        "schema_version": "memory-comparison-managed-corpus.v2",
        "benchmark": "locomo",
        "corpus_id": corpus_id,
        "thread_id": f"locomo-thread-{'b' * 64}",
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
    return (ManagedRunCase("case-1", corpus_id, record),)


def _private_file(path: Path, value: bytes) -> None:
    path.write_bytes(value)
    os.chmod(path, 0o600)


def _credential_paths(root: Path) -> tuple[ManagedMem0V5CredentialPaths, dict[str, bytes]]:
    secret_root = root / "secrets"
    secret_root.mkdir(mode=0o700)
    values = {
        "bearer": b"bearer-token-value-that-is-at-least-32-bytes",
        "evidence": b"evidence-key-value-that-is-at-least-32-bytes",
        "receipt": b"receipt-secret-value-that-is-at-least-32-bytes",
        "signing": b"checkpoint-signing-value-at-least-32-bytes",
        "head": b"checkpoint-head-value-that-is-at-least-32-bytes",
    }
    paths = ManagedMem0V5CredentialPaths(
        bearer_token=secret_root / "bearer",
        evidence_key=secret_root / "evidence",
        receipt_secret=secret_root / "receipt",
        checkpoint_signing_key=secret_root / "signing",
        checkpoint_head_key=secret_root / "head",
    )
    for path, value in zip(paths.values(), values.values(), strict=True):
        _private_file(path, value)
    return paths, values


def _trusted_runtime_binding(root: Path):
    artifact = root / "runtime-artifact.json"
    artifact.write_bytes(b'{"runtime":"hermetic-composition-test"}')
    os.chmod(artifact, 0o600)
    artifact_sha256 = hashlib.sha256(artifact.read_bytes()).hexdigest()
    route = "http://127.0.0.1:8890/v1"
    authority = runtime_binding_module._PinnedRuntimeBindingAuthority(
        runtime_artifact=artifact,
        runtime_artifact_sha256=artifact_sha256,
        runtime_source_sha256=_sha("hermetic-runtime-source"),
        transport_route=route,
        _seal=runtime_binding_module._AUTHORITY_SEAL,
    )
    observer = runtime_binding_module._ConfiguredTransportObserver(
        runtime_artifact=artifact,
        transport_route=route,
        _seal=runtime_binding_module._OBSERVER_SEAL,
    )
    return runtime_binding_module.PinnedRuntimeBindingService(
        authority=authority,
        observer=observer,
        _seal=runtime_binding_module._COMPOSITION_SEAL,
    ).issue()


def _inputs(
    tmp_path: Path,
    *,
    credential_binding: str | None = None,
) -> tuple[dict[str, object], dict[str, bytes]]:
    state_root = tmp_path / "state"
    state_root.mkdir(mode=0o700)
    credential_paths, values = _credential_paths(tmp_path)
    cases = _cases()
    current_date = "2026-08-07"
    authority = ManagedMem0V5ManifestProjector().project(cases, current_date=current_date)
    binding = _trusted_runtime_binding(tmp_path)
    route = binding.route_binding_sha256
    source = binding.runtime_source_sha256
    request = Mem0OssAdmissionRequest(
        run_id="managed-v5-composition",
        route_sha256=route,
        credential_binding_sha256=credential_binding or _sha(values["evidence"]),
        model="gpt-5.6-sol",
        reasoning_effort="medium",
        service_tier="priority",
        runtime_source_revision="source-r1",
        runtime_source_sha256=source,
        runtime_base_sha256=_sha("runtime-base"),
        expected_operation_count=authority.operation_count,
    )
    admission = Mem0OssFullRunAdmission(
        request=request,
        ingestion_manifest_sha256=authority.ingestion_manifest_sha256,
        ingestion_root_sha256=authority.ingestion_root_sha256,
        ingestion_unit_count=authority.operation_count,
    )
    operations = tuple(
        Mem0V5OperationReceiptAuthority(
            operation_id_sha256=canonical_sha256(
                {
                    "admission_commitment_sha256": admission.commitment_sha256,
                    "unit_index": index,
                    "unit_identity_sha256": unit.unit_identity_sha256,
                }
            ),
            sequence=index,
            thread_id=f"thread-{index}",
            turn_id=f"turn-{index}",
            request_body_sha256=_sha(f"request-{index}"),
            output_text_sha256=_sha(f"output-{index}"),
        )
        for index, unit in enumerate(authority.units)
    )
    receipt_authority = Mem0V5ReceiptAuthority(
        model=request.model,
        reasoning_effort=request.reasoning_effort,
        service_tier=request.service_tier,
        base_instructions_sha256=_sha("base-instructions"),
        runtime_source_sha256=source,
        route_binding_sha256=route,
        account_binding_hmac_sha256=_sha("account"),
        response_format_type="json_schema",
        response_format_sha256=_sha("response-format"),
        response_schema_sha256=_sha("response-schema"),
        requested_output_tokens=4096,
        operations=operations,
    )
    return {
        "cases": cases,
        "current_date": current_date,
        "request": request,
        "origin": "http://127.0.0.1:8891",
        "timeout_seconds": 5.0,
        "state_paths": subject.ManagedMem0V5StatePaths(
            checkpoint=state_root / "checkpoint.json",
            local_checkpoint_head=state_root / "checkpoint-head.sqlite3",
        ),
        "credential_paths": credential_paths,
        "runtime_receipt_boundary": RuntimeReceiptV2Boundary(_UnusedReceiptHmacVerifier()),
        "trusted_runtime_binding": binding,
        "receipt_authority": receipt_authority,
        "transport": _Transport(values["evidence"], authority),
    }, values


def _observed_authority(
    inputs: dict[str, object],
) -> Mem0V5ObservedExtractionReceiptAuthority:
    old = inputs["receipt_authority"]
    assert type(old) is Mem0V5ReceiptAuthority
    cases = inputs["cases"]
    current_date = inputs["current_date"]
    request = inputs["request"]
    assert type(cases) is tuple
    assert type(current_date) is str  # noqa: E721 - exact fixture contract required
    assert type(request) is Mem0OssAdmissionRequest
    authority = ManagedMem0V5ManifestProjector().project(cases, current_date=current_date)
    admission = Mem0OssFullRunAdmission(
        request=request,
        ingestion_manifest_sha256=authority.ingestion_manifest_sha256,
        ingestion_root_sha256=authority.ingestion_root_sha256,
        ingestion_unit_count=authority.operation_count,
    )
    operation = old.operations[0]
    unit = authority.units[0]
    return Mem0V5ObservedExtractionReceiptAuthority(
        admission_commitment_sha256=admission.commitment_sha256,
        model=old.model,
        reasoning_effort=old.reasoning_effort,
        service_tier=old.service_tier,
        base_instructions_sha256=old.base_instructions_sha256,
        runtime_source_sha256=old.runtime_source_sha256,
        route_binding_sha256=old.route_binding_sha256,
        account_binding_hmac_sha256=old.account_binding_hmac_sha256,
        response_format_type=old.response_format_type,
        response_format_sha256=old.response_format_sha256,
        response_schema_sha256=old.response_schema_sha256,
        node_executable_path="/usr/local/bin/node",
        node_executable_sha256=("b2959781cc5a74c357ffa02367efa8a0330cbb1c9cb347732fdfaaaca381cbcd"),
        requested_output_tokens=old.requested_output_tokens,
        operations=(
            Mem0V5ObservedExtractionOperationAuthority(
                operation.operation_id_sha256,
                unit.unit_identity_sha256,
                unit.unit_sha256,
                unit.scope_sha256,
                0,
                operation.request_body_sha256,
            ),
        ),
    )


def test_exported_preflight_is_no_secret_no_write_no_network_and_compose_has_parity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable_reviewed_authority() -> object:
        raise FileNotFoundError("hosting reviewed authority is unavailable")

    monkeypatch.setattr(
        runtime_binding_module,
        "immutable_authority",
        unavailable_reviewed_authority,
    )
    inputs, _ = _inputs(tmp_path)
    state = inputs["state_paths"]
    transport = inputs["transport"]
    assert type(state) is subject.ManagedMem0V5StatePaths
    assert type(transport) is _Transport

    preflight = subject.preflight_managed_mem0_v5(**inputs)

    assert type(preflight) is subject.ManagedMem0V5Preflight
    assert preflight.admission.request == inputs["request"]
    assert preflight.authority.operation_count == 1
    assert repr(preflight) == "ManagedMem0V5Preflight(<opaque>)"
    assert not state.checkpoint.exists()
    assert not state.local_checkpoint_head.exists()
    assert transport.calls == []

    composed = subject.compose_managed_mem0_v5(**inputs)
    assert composed.authority == preflight.authority
    assert composed.request == preflight.admission.request
    assert transport.calls == []
    with pytest.raises(ManagedRunError, match="authority differs"):
        composed.issue_transport_coverage(benchmark="locomo")


def test_invalid_authentic_binding_snapshot_fails_before_credentials_are_loaded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs, _ = _inputs(tmp_path)
    binding = inputs["trusted_runtime_binding"]
    object.__setattr__(binding, "_runtime_source_sha256", "0" * 64)
    loads = 0

    def record_load(_paths: object) -> None:
        nonlocal loads
        loads += 1
        raise AssertionError("credentials loaded before runtime binding preflight")

    monkeypatch.setattr(subject, "load_managed_mem0_v5_credentials", record_load)
    with pytest.raises(ManagedRunError, match="runtime authority is invalid"):
        subject.compose_managed_mem0_v5(**inputs)
    assert loads == 0


def test_observed_public_binding_mismatch_fails_before_trust_helper_and_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs, _ = _inputs(tmp_path)
    observed = _observed_authority(inputs)
    object.__setattr__(observed, "admission_commitment_sha256", "0" * 64)
    inputs["receipt_authority"] = observed
    helper_calls = 0
    loads = 0

    def record_helper(**_kwargs: object) -> None:
        nonlocal helper_calls
        helper_calls += 1

    def record_load(_paths: object) -> None:
        nonlocal loads
        loads += 1
        raise AssertionError("credentials loaded before observed public binding preflight")

    monkeypatch.setattr(
        subject,
        "require_mem0_v5_observed_extraction_receipt_boundary",
        record_helper,
    )
    monkeypatch.setattr(subject, "load_managed_mem0_v5_credentials", record_load)
    with pytest.raises(ManagedRunError, match="observed receipt binding differs"):
        subject.compose_managed_mem0_v5(**inputs)
    assert helper_calls == 0
    assert loads == 0


def test_public_preflight_rejects_receipt_drift_before_credentials_are_loaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs, _ = _inputs(tmp_path)
    authority = inputs["receipt_authority"]
    assert type(authority) is Mem0V5ReceiptAuthority
    bad_operation = replace(authority.operations[0], operation_id_sha256="0" * 64)
    inputs["receipt_authority"] = replace(authority, operations=(bad_operation,))
    calls = 0

    def fail_if_loaded(_paths):
        nonlocal calls
        calls += 1
        raise AssertionError("credentials loaded before public preflight")

    monkeypatch.setattr(subject, "load_managed_mem0_v5_credentials", fail_if_loaded)
    with pytest.raises(ManagedRunError, match="receipt operations differ"):
        subject.compose_managed_mem0_v5(**inputs)
    assert calls == 0


def test_runtime_boundary_and_transport_fail_before_credentials_are_loaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs, _ = _inputs(tmp_path)
    loaded = False

    def record_load(_paths):
        nonlocal loaded
        loaded = True
        raise AssertionError("credentials must remain unopened")

    monkeypatch.setattr(subject, "load_managed_mem0_v5_credentials", record_load)
    inputs["runtime_receipt_boundary"] = RuntimeReceiptV2Boundary(object())
    with pytest.raises(ManagedRunError, match="runtime authority is invalid"):
        subject.compose_managed_mem0_v5(**inputs)
    assert not loaded

    transport_root = tmp_path / "transport"
    transport_root.mkdir()
    inputs, _ = _inputs(transport_root)
    inputs["transport"] = object()
    with pytest.raises(ManagedRunError, match="runtime authority is invalid"):
        subject.compose_managed_mem0_v5(**inputs)
    assert not loaded


def test_evidence_credential_binding_mismatch_fails_closed(tmp_path: Path) -> None:
    inputs, _ = _inputs(tmp_path, credential_binding="0" * 64)
    with pytest.raises(ManagedRunError, match="credential binding differs"):
        subject.compose_managed_mem0_v5(**inputs)
    state = inputs["state_paths"]
    assert type(state) is subject.ManagedMem0V5StatePaths
    assert not state.checkpoint.exists()
    assert not state.local_checkpoint_head.exists()


def test_observed_receipt_noop_boundary_rejected_before_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs, _ = _inputs(tmp_path)
    inputs["receipt_authority"] = _observed_authority(inputs)
    loads = 0

    def record_load(_paths: object) -> None:
        nonlocal loads
        loads += 1
        raise AssertionError("credentials loaded before observed trust preflight")

    monkeypatch.setattr(subject, "load_managed_mem0_v5_credentials", record_load)
    with pytest.raises(Mem0V5HttpError, match="configuration_invalid"):
        subject.compose_managed_mem0_v5(**inputs)
    assert loads == 0


def test_observed_receipt_union_selects_public_verifier_after_no_secret_preflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs, _ = _inputs(tmp_path)
    observed = _observed_authority(inputs)
    inputs["receipt_authority"] = observed
    events: list[str] = []
    real_load = subject.load_managed_mem0_v5_credentials

    def preflight(**kwargs: object) -> None:
        assert kwargs["authority"] is observed
        events.append("preflight")

    def load(paths: object) -> object:
        events.append("load")
        return real_load(paths)

    class _ObservedVerifier:
        @classmethod
        def _for_preflighted_composition(cls, **kwargs: object) -> _ObservedVerifier:
            return cls(**kwargs)

        def __init__(self, **kwargs: object) -> None:
            assert kwargs["authority"] is observed
            assert type(kwargs["receipt_secret"]) is str  # noqa: E721
            events.append("verifier")

        def mark_outcome_unknown(self, **_kwargs: object) -> None:
            return None

        def verify_dispatch_receipt(self, **_kwargs: object) -> None:
            return None

        def verify_status_readback(self, **_kwargs: object) -> None:
            return None

    monkeypatch.setattr(
        subject,
        "require_mem0_v5_observed_extraction_receipt_boundary",
        preflight,
    )
    monkeypatch.setattr(subject, "load_managed_mem0_v5_credentials", load)
    monkeypatch.setattr(subject, "Mem0V5ObservedExtractionReceiptVerifier", _ObservedVerifier)
    result = subject.compose_managed_mem0_v5(**inputs)
    assert type(result.coordinator) is ManagedMem0V5LaneCoordinator
    assert events == ["preflight", "load", "verifier"]


def test_composition_accepts_only_exact_optional_guard_and_distinct_guard_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs, _ = _inputs(tmp_path)
    state = inputs["state_paths"]
    assert type(state) is subject.ManagedMem0V5StatePaths
    guard = create_managed_mem0_v5_single_dispatch_guard(
        state.checkpoint.parent / "single-dispatch.json"
    )
    assert type(guard) is AtomicJournalManagedMem0V5SingleDispatchGuard
    inputs["dispatch_guard"] = guard
    result = subject.compose_managed_mem0_v5(**inputs)
    assert type(result.coordinator) is ManagedMem0V5LaneCoordinator
    assert not guard.path.exists()

    bad_root = tmp_path / "bad-guard"
    bad_root.mkdir()
    bad_inputs, _ = _inputs(bad_root)
    bad_inputs["dispatch_guard"] = object()
    loads = 0

    def record_load(_paths: object) -> None:
        nonlocal loads
        loads += 1
        raise AssertionError("credentials loaded for invalid guard")

    monkeypatch.setattr(subject, "load_managed_mem0_v5_credentials", record_load)
    with pytest.raises(ManagedRunError, match="composition input is invalid"):
        subject.compose_managed_mem0_v5(**bad_inputs)
    assert loads == 0

    collision_root = tmp_path / "collision"
    collision_root.mkdir()
    collision_inputs, _ = _inputs(collision_root)
    collision_state = collision_inputs["state_paths"]
    assert type(collision_state) is subject.ManagedMem0V5StatePaths
    collision_inputs["dispatch_guard"] = create_managed_mem0_v5_single_dispatch_guard(
        collision_state.checkpoint
    )
    with pytest.raises(ManagedRunError, match="paths are not distinct"):
        subject.compose_managed_mem0_v5(**collision_inputs)
    assert loads == 0


class _Capability:
    def __init__(self, value: str | bytes) -> None:
        self.value = value
        self.closed = False

    def consume(self):
        value = self.value
        self.value = b"" if type(value) is bytes else ""  # noqa: E721
        return value

    def validate(self) -> None:
        value = self.value
        encoded = value if type(value) is bytes else value.encode()  # noqa: E721
        assert 32 <= len(encoded) <= 4_096

    def close(self) -> None:
        self.closed = True
        self.value = b"" if type(self.value) is bytes else ""  # noqa: E721


class _Capabilities:
    def __init__(self, values: dict[str, bytes]) -> None:
        self.bearer_token = _Capability(values["bearer"].decode())
        self.evidence_key = _Capability(values["evidence"])
        self.receipt_secret = _Capability(values["receipt"].decode())
        self.checkpoint_signing_key = _Capability(values["signing"])
        self.checkpoint_head_key = _Capability(values["head"])
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        self.close()

    def close(self) -> None:
        self.closed = True
        for name in (
            "bearer_token",
            "evidence_key",
            "receipt_secret",
            "checkpoint_signing_key",
            "checkpoint_head_key",
        ):
            getattr(self, name).close()


def test_partial_composition_closes_every_credential_capability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs, values = _inputs(tmp_path)
    capabilities = _Capabilities(values)
    monkeypatch.setattr(subject, "load_managed_mem0_v5_credentials", lambda _paths: capabilities)

    class _BrokenReceiptVerifier:
        def __init__(self, **_kwargs) -> None:
            raise RuntimeError("receipt composition failed")

    monkeypatch.setattr(subject, "Mem0V5RuntimeReceiptVerifier", _BrokenReceiptVerifier)
    with pytest.raises(RuntimeError, match="receipt composition failed"):
        subject.compose_managed_mem0_v5(**inputs)
    assert capabilities.closed
    assert all(
        getattr(capabilities, name).closed
        for name in (
            "bearer_token",
            "evidence_key",
            "receipt_secret",
            "checkpoint_signing_key",
            "checkpoint_head_key",
        )
    )


def test_fresh_process_composition_rebuilds_equivalent_public_bundle_without_secret_repr(
    tmp_path: Path,
) -> None:
    inputs, values = _inputs(tmp_path)

    first = subject.compose_managed_mem0_v5(**inputs)
    first.coordinator.admit(
        authority=first.authority,
        request=first.request,
        budget_policy=ManagedMem0V5BudgetPolicy(5),
    )
    second = subject.compose_managed_mem0_v5(**inputs)
    restored = second.coordinator.restore(
        authority=second.authority,
        request=second.request,
        budget_policy=ManagedMem0V5BudgetPolicy(5),
    )

    assert first.authority == second.authority
    assert first.request == second.request
    assert first.coordinator is not second.coordinator
    assert type(first.coordinator) is ManagedMem0V5LaneCoordinator
    assert tuple(field.name for field in fields(first)) == ("authority", "request", "coordinator")
    rendered = repr(first)
    assert rendered == "ManagedMem0V5Composition(<opaque>)"
    assert all(value.decode() not in rendered for value in values.values())
    state = inputs["state_paths"]
    assert type(state) is subject.ManagedMem0V5StatePaths
    assert state.local_checkpoint_head.exists()
    assert state.local_checkpoint_head.stat().st_mode & 0o777 == 0o600
    assert restored.run_phase is ManagedMem0V5RunPhase.ACTIVE
    transport = inputs["transport"]
    assert type(transport) is _Transport
    assert len(transport.calls) == 2
    boundary = inputs["runtime_receipt_boundary"]
    assert type(boundary) is RuntimeReceiptV2Boundary
    assert boundary.hmac_verifier.calls == 0


def test_production_clean_state_factories_issue_one_opaque_paired_runtime(
    tmp_path: Path,
) -> None:
    inputs, _values = _inputs(tmp_path)
    transport = inputs["transport"]
    composition = subject.compose_managed_mem0_v5(**inputs)

    class Capability:
        def __init__(self, value: bytes) -> None:
            self.value = value
            self.calls = 0

        def validate(self) -> None:
            assert 32 <= len(self.value) <= 4_096

        def consume(self) -> bytes:
            self.calls += 1
            return self.value

    durable = Capability(b"durable-clean-state-key-value!!" * 2)
    snapshot_factory = ManagedMem0V5HttpCleanStateSnapshotFactory()
    durable_factory = ManagedMem0V5HmacDurableCleanStateFactory(
        path=tmp_path / "clean-state.json",
        hmac_key_capability=durable,
    )
    bundle = composition.issue_paired_runtime(
        budget_policy=ManagedMem0V5BudgetPolicy(5),
        clean_state_snapshot_factory=snapshot_factory,
        durable_clean_state_factory=durable_factory,
    )

    bundle.paired_run.admit()
    evidence = bundle.issue_ready_clean_state_evidence()

    assert repr(bundle) == "ManagedMem0V5PairedRuntimeBundle(<opaque>)"
    assert repr(evidence) == "FullExecutionCleanStateEvidence(<opaque>)"
    assert durable.calls == 1
    assert type(transport) is _Transport
    assert sum(path.endswith("/v5/runs/clean-state") for path in transport.calls) == 1
    with pytest.raises(ManagedRunError, match="paired runtime is already issued"):
        composition.issue_paired_runtime(
            budget_policy=ManagedMem0V5BudgetPolicy(5),
            clean_state_snapshot_factory=snapshot_factory,
            durable_clean_state_factory=durable_factory,
        )
    with pytest.raises(ManagedRunError, match="ready clean-state evidence is unavailable"):
        bundle.issue_ready_clean_state_evidence()
    paired_run = bundle.paired_run
    object.__setattr__(paired_run, "_clean_state_snapshot", object())
    with pytest.raises(ManagedRunError, match="paired run binding differs"):
        _ = bundle.paired_run


def test_oversized_clean_state_inventory_fails_before_credentials_or_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs, _values = _inputs(tmp_path)
    cases = []
    for index in range(500):
        identity = _sha(f"oversized-corpus-{index}")
        corpus_id = f"locomo-corpus-{identity}"
        cases.append(
            ManagedRunCase(
                f"case-{index:04d}",
                corpus_id,
                {
                    "schema_version": "memory-comparison-managed-corpus.v2",
                    "benchmark": "locomo",
                    "corpus_id": corpus_id,
                    "thread_id": f"locomo-thread-{_sha(f'thread-{index}')}",
                    "memories": [
                        {
                            "kind": "fact",
                            "role": "user",
                            "session_alias": "session-0001",
                            "source_alias": "memory-000001",
                            "speaker": "Alice",
                            "session_date": "2024-03-10",
                            "text": f"Bounded fact {index}.",
                            "timestamp": 1,
                        }
                    ],
                    "documents": [],
                    "conversations": [],
                },
            )
        )
    inputs["cases"] = tuple(cases)
    request = inputs["request"]
    assert type(request) is Mem0OssAdmissionRequest
    request = replace(request, expected_operation_count=500)
    inputs["request"] = request
    authority = ManagedMem0V5ManifestProjector().project(
        tuple(cases),
        current_date=inputs["current_date"],
    )
    admission = Mem0OssFullRunAdmission(
        request=request,
        ingestion_manifest_sha256=authority.ingestion_manifest_sha256,
        ingestion_root_sha256=authority.ingestion_root_sha256,
        ingestion_unit_count=authority.operation_count,
    )
    receipt_authority = inputs["receipt_authority"]
    assert type(receipt_authority) is Mem0V5ReceiptAuthority
    inputs["receipt_authority"] = replace(
        receipt_authority,
        operations=tuple(
            Mem0V5OperationReceiptAuthority(
                operation_id_sha256=canonical_sha256(
                    {
                        "admission_commitment_sha256": admission.commitment_sha256,
                        "unit_index": index,
                        "unit_identity_sha256": unit.unit_identity_sha256,
                    }
                ),
                sequence=index,
                thread_id=f"thread-{index}",
                turn_id=f"turn-{index}",
                request_body_sha256=_sha(f"request-{index}"),
                output_text_sha256=_sha(f"output-{index}"),
            )
            for index, unit in enumerate(authority.units)
        ),
    )
    credential_loads = 0

    def reject_credential_load(*_args: object, **_kwargs: object) -> object:
        nonlocal credential_loads
        credential_loads += 1
        raise AssertionError("oversized request reached credential loading")

    monkeypatch.setattr(subject, "load_managed_mem0_v5_credentials", reject_credential_load)
    transport = inputs["transport"]
    assert type(transport) is _Transport

    with pytest.raises(ManagedRunError, match="clean-state HTTP evidence is invalid"):
        subject.compose_managed_mem0_v5(**inputs)

    assert credential_loads == 0
    assert transport.calls == []


class _CoverageRecoveryLane:
    def __init__(self, *, collector: object, evidence_key: bytes) -> None:
        self._collector = collector
        root = hmac.new(
            evidence_key,
            b"mem0-oss-adapter-v5/evidence-key/v1",
            hashlib.sha256,
        ).digest()
        self._binding_key = hmac.new(root, REQUEST_BINDING_V2_DOMAIN, hashlib.sha256).digest()
        self._storage_issuer = subject.create_managed_mem0_v5_storage_witness_authority()[0]
        self.dispatch_calls = 0
        self.status_calls = 0

    def admit(self, **_values: object) -> None:
        return None

    def _binding(self, **values: object):
        context = ManagedMem0V5RequestBindingV2Context.from_authority(
            authority=values["authority"],
            unit=values["unit"],
            operation_id_sha256=values["operation_id_sha256"],
            admission=values["admission"],
        )
        evidence = {**context.evidence_payload(), "request_body_sha256": _sha("request-0")}
        unsigned = {
            **evidence,
            "request_binding_evidence_sha256": canonical_sha256(evidence),
        }
        signature = hmac.new(
            self._binding_key,
            json.dumps(
                unsigned,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode(),
            hashlib.sha256,
        ).hexdigest()
        return verify_request_binding_v2_payload(
            payload={**unsigned, "request_binding_hmac_sha256": signature},
            context=context,
            hmac_key=self._binding_key,
        )

    def dispatch(self, **values: object) -> object:
        self.dispatch_calls += 1
        self._collector.record(self._binding(**values))
        return {"receipt": "dispatch"}

    def status(self, **values: object) -> object:
        self.status_calls += 1
        self._collector.record_idempotent(self._binding(**values))
        return {"receipt": "status"}

    def inspect_storage(self, **values: object):
        unit = values["unit"]
        return self._storage_issuer.issue_authenticated_storage(
            operation_id_sha256=values["operation_id_sha256"],
            unit_identity_sha256=unit.unit_identity_sha256,
            storage_commitment_sha256=_sha("storage"),
            created_record_ids=("record-1",),
            source_pairs=((unit.source_id, unit.source_sha256),),
        )


def _replace_composed_runtime_for_recovery(
    composed: subject.ManagedMem0V5Composition,
    *,
    evidence_key: bytes,
) -> _CoverageRecoveryLane:
    _admission_value, http_lane = subject._composition_runtime(composed)
    lane = _CoverageRecoveryLane(
        collector=http_lane._transport_collector,
        evidence_key=evidence_key,
    )
    service = Mem0OssFullRunService(
        manifest_port=ManagedMem0V5ManifestProjector(),
        receipt_port=_ReceiptPort(),
        storage_port=_StoragePort(),
        cleanup_port=_CleanupPort(),
    )
    object.__setattr__(composed.coordinator, "_service", service)
    object.__setattr__(composed.coordinator, "_lane", lane)
    return lane


def test_fresh_composition_restore_rebuilds_exact_transport_coverage_without_dispatch(
    tmp_path: Path,
) -> None:
    inputs, values = _inputs(tmp_path)
    first = subject.compose_managed_mem0_v5(**inputs)
    first_lane = _replace_composed_runtime_for_recovery(
        first,
        evidence_key=values["evidence"],
    )
    first.coordinator.admit(
        authority=first.authority,
        request=first.request,
        budget_policy=ManagedMem0V5BudgetPolicy(5),
    )
    first.coordinator.dispatch_pending()
    assert first_lane.dispatch_calls == 1

    restored = subject.compose_managed_mem0_v5(**inputs)
    restored_lane = _replace_composed_runtime_for_recovery(
        restored,
        evidence_key=values["evidence"],
    )
    checkpoint = restored.coordinator.restore(
        authority=restored.authority,
        request=restored.request,
        budget_policy=ManagedMem0V5BudgetPolicy(5),
    )
    capability = restored.issue_transport_coverage(benchmark="locomo")
    storage = restored.coordinator.storage_observations
    coverage = capability.consume_complete_transport_coverage(
        expected_admission_commitment_sha256=checkpoint.admission_commitment_sha256,
        expected_operation_ids=tuple(item.operation_id_sha256 for item in storage),
    )

    assert restored_lane.dispatch_calls == 0
    assert restored_lane.status_calls == restored.authority.operation_count
    assert coverage.operation_count == restored.authority.operation_count
    assert coverage.admission_commitment_sha256 == checkpoint.admission_commitment_sha256
    assert coverage.authority_commitment_sha256 == restored.authority.authority_commitment_sha256


def test_state_paths_are_absolute_and_distinct(tmp_path: Path) -> None:
    absolute = tmp_path / "state"
    with pytest.raises(ManagedRunError, match="state paths are invalid"):
        subject.ManagedMem0V5StatePaths(Path("relative.json"), absolute)
    with pytest.raises(ManagedRunError, match="state paths are invalid"):
        subject.ManagedMem0V5StatePaths(absolute, absolute)

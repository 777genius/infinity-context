from __future__ import annotations

# ruff: noqa: E402 - the external Phase C package is an explicit test-only path.
import hashlib
import json
import os
import sys
from dataclasses import fields, replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PHASE_C_ROOT = ROOT / "benchmarks" / "phase-c-canary"
sys.path.insert(0, str(PHASE_C_ROOT))

from infinity_context_server import memory_comparison_managed_mem0_v5_composition as subject
from infinity_context_server.memory_comparison_managed_mem0_v5_checkpoint import (
    ManagedMem0V5RunPhase,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_credentials import (
    ManagedMem0V5CredentialPaths,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_lane import (
    ManagedMem0V5BudgetPolicy,
    ManagedMem0V5LaneCoordinator,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestProjector,
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
    Mem0V5OperationReceiptAuthority,
    Mem0V5ReceiptAuthority,
)
from phase_c_canary.runtime_binding import RuntimeBindingComposition
from phase_c_canary.runtime_receipt_v2 import RuntimeReceiptV2Boundary


def _sha(value: str | bytes) -> str:
    raw = value if type(value) is bytes else value.encode()
    return hashlib.sha256(raw).hexdigest()


class _UnusedReceiptHmacVerifier:
    def __init__(self) -> None:
        self.calls = 0

    def verify(self, **kwargs) -> None:
        self.calls += 1
        raise AssertionError(kwargs)


class _Transport:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def request(self, method, url, **kwargs):
        assert method == "POST"
        assert url.endswith("/v5/runs/admit")
        body = json.loads(kwargs["content"])
        self.calls.append(url)
        payload = {
            "admission_commitment_sha256": body["admission_commitment_sha256"],
            "runtime_binding_commitment_sha256": _sha("runtime-binding"),
            "accepted": True,
        }
        return type("Response", (), {"status_code": 200, "content": json.dumps(payload).encode()})()


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
    binding = RuntimeBindingComposition.compose_phase_c_canary().issue()
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
        "transport": _Transport(),
    }, values


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


class _Capability:
    def __init__(self, value: str | bytes) -> None:
        self.value = value
        self.closed = False

    def consume(self):
        value = self.value
        self.value = b"" if type(value) is bytes else ""
        return value

    def close(self) -> None:
        self.closed = True
        self.value = b"" if type(self.value) is bytes else ""


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


def test_state_paths_are_absolute_and_distinct(tmp_path: Path) -> None:
    absolute = tmp_path / "state"
    with pytest.raises(ManagedRunError, match="state paths are invalid"):
        subject.ManagedMem0V5StatePaths(Path("relative.json"), absolute)
    with pytest.raises(ManagedRunError, match="state paths are invalid"):
        subject.ManagedMem0V5StatePaths(absolute, absolute)

from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
from infinity_context_server import (
    memory_comparison_managed_mem0_v5_cleanup_readback as subject,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_cleanup_readback import (
    ManagedMem0V5CleanupPassTwoAdapter,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_verifiers import (
    ManagedMem0V5CleanupBridgeVerifier,
)
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunError
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    MEM0_OSS_EMPTY_ROOT_SHA256,
    Mem0OssFullRunState,
    canonical_sha256,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_evidence import (
    Mem0OssTerminalCleanupEvidence,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_http import (
    Mem0V5CleanupReceipt,
    Mem0V5CleanupRequest,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _request(*, aborting: bool = False) -> Mem0V5CleanupRequest:
    admission = _sha("admission")
    seal = None if aborting else _sha("seal")
    operation = None if aborting else _sha("operation")
    inventory = _sha("inventory")
    body = {
        "admission_commitment_sha256": admission,
        "seal_commitment_sha256": seal,
        "operation_root_sha256": operation,
        "operation_inventory_root_sha256": inventory,
        "expected_operation_count": 2,
        "aborting": aborting,
    }
    binding = canonical_sha256(body)
    return Mem0V5CleanupRequest(
        admission,
        seal,
        operation,
        inventory,
        2,
        aborting,
        canonical_sha256({"kind": "cleanup", "binding": binding}),
    )


def _terminal(
    request: Mem0V5CleanupRequest, *, state: str = Mem0OssFullRunState.DELETED.value
) -> Mem0OssTerminalCleanupEvidence:
    return Mem0OssTerminalCleanupEvidence(
        terminal_state=state,
        admission_commitment_sha256=request.admission_commitment_sha256,
        seal_commitment_sha256=request.seal_commitment_sha256,
        operation_root_sha256=request.operation_root_sha256,
        operation_inventory_root_sha256=request.operation_inventory_root_sha256,
        deleted_operation_count=request.expected_operation_count,
        residual_record_count=0,
        residual_root_sha256=MEM0_OSS_EMPTY_ROOT_SHA256,
        provider_observed_extraction_calls=2,
        provider_observed_request_tokens=10,
        provider_observed_response_tokens=5,
        failed_receipts=(),
    )


def _receipt(request: Mem0V5CleanupRequest) -> Mem0V5CleanupReceipt:
    return Mem0V5CleanupReceipt(
        request.admission_commitment_sha256,
        request.seal_commitment_sha256,
        request.operation_root_sha256,
        request.operation_inventory_root_sha256,
        request.expected_operation_count,
        0,
        MEM0_OSS_EMPTY_ROOT_SHA256,
    )


class _Cleanup:
    def __init__(self, receipt: object) -> None:
        self.receipt = receipt
        self.calls: list[Mem0V5CleanupRequest] = []

    def cleanup(self, request: Mem0V5CleanupRequest) -> object:
        self.calls.append(request)
        return self.receipt


class _TransientCleanup(_Cleanup):
    def __init__(self, receipt: object) -> None:
        super().__init__(receipt)
        self.failures = 1

    def cleanup(self, request: Mem0V5CleanupRequest) -> object:
        self.calls.append(request)
        if self.failures:
            self.failures -= 1
            raise RuntimeError("transient")
        return self.receipt


def _adapter(cleanup: _Cleanup) -> ManagedMem0V5CleanupPassTwoAdapter:
    return ManagedMem0V5CleanupPassTwoAdapter(
        cleanup_port=cleanup,
        verification_port=ManagedMem0V5CleanupBridgeVerifier(),
    )


def test_pass_two_performs_fresh_bound_call_and_issues_exact_witness() -> None:
    request = _request()
    terminal = _terminal(request)
    cleanup = _Cleanup(_receipt(request))
    adapter = _adapter(cleanup)

    witness = adapter.readback(pass_index=2, request=request, terminal=terminal)

    assert cleanup.calls == [request]
    assert witness.pass_index == 2
    assert witness.terminal_commitment_sha256 == terminal.commitment_sha256
    assert witness.deleted_operation_count == request.expected_operation_count
    assert witness.residual_root_sha256 == MEM0_OSS_EMPTY_ROOT_SHA256
    assert witness.public_payload()["evidence_commitment_sha256"] == (
        witness.evidence_commitment_sha256
    )
    assert "opaque" in repr(witness)
    with pytest.raises(ManagedRunError, match="replayed"):
        adapter.readback(pass_index=2, request=request, terminal=terminal)
    assert cleanup.calls == [request]


def test_pass_two_io_failure_retains_exact_retry_authority() -> None:
    request = _request()
    terminal = _terminal(request)
    cleanup = _TransientCleanup(_receipt(request))
    adapter = _adapter(cleanup)

    with pytest.raises(ManagedRunError, match="call failed"):
        adapter.readback(pass_index=2, request=request, terminal=terminal)
    witness = adapter.readback(pass_index=2, request=request, terminal=terminal)

    assert witness.terminal_commitment_sha256 == terminal.commitment_sha256
    assert cleanup.calls == [request, request]
    with pytest.raises(ManagedRunError, match="replayed"):
        adapter.readback(pass_index=2, request=request, terminal=terminal)


def test_witness_construction_failure_clears_in_flight_and_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request()
    terminal = _terminal(request)
    cleanup = _Cleanup(_receipt(request))
    adapter = _adapter(cleanup)
    original = subject.ManagedMem0V5CleanupReadbackWitness
    attempts = 0

    def flaky_witness(**values: object) -> object:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ValueError("constructor fault")
        return original(**values)

    monkeypatch.setattr(subject, "ManagedMem0V5CleanupReadbackWitness", flaky_witness)

    with pytest.raises(ManagedRunError, match="witness construction failed"):
        adapter.readback(pass_index=2, request=request, terminal=terminal)
    witness = adapter.readback(pass_index=2, request=request, terminal=terminal)

    assert witness.terminal_commitment_sha256 == terminal.commitment_sha256
    assert cleanup.calls == [request, request]


def test_invalid_authority_does_not_consume_and_corrected_request_succeeds() -> None:
    request = _request()
    terminal = _terminal(request)
    cleanup = _Cleanup(_receipt(request))
    adapter = _adapter(cleanup)

    with pytest.raises(ManagedRunError, match="authority differs"):
        adapter.readback(
            pass_index=2,
            request=replace(request, idempotency_key=_sha("wrong")),
            terminal=terminal,
        )
    witness = adapter.readback(pass_index=2, request=request, terminal=terminal)

    assert witness.terminal_commitment_sha256 == terminal.commitment_sha256
    assert cleanup.calls == [request]


def test_concurrent_correct_requests_have_exactly_one_io_winner() -> None:
    request = _request()
    terminal = _terminal(request)
    cleanup = _Cleanup(_receipt(request))
    adapter = _adapter(cleanup)

    def invoke() -> object:
        try:
            return adapter.readback(pass_index=2, request=request, terminal=terminal)
        except ManagedRunError as error:
            return error

    with ThreadPoolExecutor(max_workers=8) as executor:
        outcomes = tuple(executor.map(lambda _index: invoke(), range(8)))

    assert sum(not isinstance(item, ManagedRunError) for item in outcomes) == 1
    assert cleanup.calls == [request]


def test_wrong_pass_is_rejected_without_calling_transport() -> None:
    request = _request()
    cleanup = _Cleanup(_receipt(request))
    adapter = _adapter(cleanup)
    with pytest.raises(ManagedRunError, match="pass differs"):
        adapter.readback(pass_index=1, request=request, terminal=_terminal(request))
    assert cleanup.calls == []


@pytest.mark.parametrize(
    "cleanup_request,terminal",
    (
        (_request(aborting=True), _terminal(_request(aborting=True), state="aborted")),
        (
            _request(),
            replace(_terminal(_request()), operation_inventory_root_sha256=_sha("other")),
        ),
        (
            replace(_request(), idempotency_key=_sha("wrong")),
            _terminal(_request()),
        ),
    ),
)
def test_aborted_divergent_or_non_idempotent_authority_is_rejected(
    cleanup_request: Mem0V5CleanupRequest, terminal: Mem0OssTerminalCleanupEvidence
) -> None:
    cleanup = _Cleanup(_receipt(cleanup_request))
    with pytest.raises(ManagedRunError, match="authority differs"):
        _adapter(cleanup).readback(pass_index=2, request=cleanup_request, terminal=terminal)
    assert cleanup.calls == []


def test_wrong_dto_or_divergent_result_is_rejected_after_fresh_call() -> None:
    request = _request()
    terminal = _terminal(request)
    wrong_dto = _Cleanup(object())
    with pytest.raises(ManagedRunError, match="DTO differs"):
        _adapter(wrong_dto).readback(pass_index=2, request=request, terminal=terminal)
    assert len(wrong_dto.calls) == 1

    divergent = _Cleanup(replace(_receipt(request), deleted_operation_count=1))
    with pytest.raises(ManagedRunError, match="verification failed"):
        _adapter(divergent).readback(pass_index=2, request=request, terminal=terminal)
    assert len(divergent.calls) == 1


def test_witness_mutation_is_detected() -> None:
    request = _request()
    witness = _adapter(_Cleanup(_receipt(request))).readback(
        pass_index=2, request=request, terminal=_terminal(request)
    )
    object.__setattr__(witness, "deleted_operation_count", 1)
    object.__setattr__(
        witness,
        "evidence_commitment_sha256",
        canonical_sha256(witness.commitment_payload()),
    )
    with pytest.raises(ManagedRunError, match="witness is invalid"):
        witness.public_payload()

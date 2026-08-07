from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import infinity_context_server.memory_comparison_mem0_oss_v5_contracts as contracts
import pytest
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    MEM0_OSS_EMPTY_ROOT_SHA256,
    CleanupVerificationContext,
    CleanupVerificationResult,
    ManifestAuthorityResult,
    Mem0OssAdmissionRequest,
    Mem0OssFullRunError,
    Mem0OssFullRunState,
    Mem0OssManifestUnit,
    Mem0OssReceiptDisposition,
    RuntimeReceiptVerificationContext,
    RuntimeReceiptVerificationResult,
    StorageVerificationContext,
    StorageVerificationResult,
    canonical_sha256,
    manifest_root_sha256,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_run import (
    Mem0OssEvidencePage,
    Mem0OssFullRunService,
    verify_mem0_oss_sealed_evidence_pages,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _units(count: int) -> tuple[Mem0OssManifestUnit, ...]:
    return tuple(
        Mem0OssManifestUnit(
            unit_identity_sha256=_sha(f"identity-{index}"),
            unit_sha256=_sha(f"unit-{index}"),
            scope_sha256=_sha(f"scope-{index // 2}"),
        )
        for index in range(count)
    )


class _ManifestPort:
    def __init__(self, units: tuple[Mem0OssManifestUnit, ...]) -> None:
        self.units = units
        self.root_override: str | None = None
        self.return_impostor = False
        self.raise_secret = False

    def verify(self, *, payload: object) -> ManifestAuthorityResult:
        if self.raise_secret:
            raise RuntimeError("secret-manifest-adapter-message")
        assert payload == {"authority": "verified"}
        if self.return_impostor:
            return object()  # type: ignore[return-value]
        return ManifestAuthorityResult(
            ingestion_manifest_sha256=_sha("manifest"),
            ingestion_root_sha256=self.root_override or manifest_root_sha256(self.units),
            units=self.units,
        )


class _ReceiptPort:
    def __init__(self) -> None:
        self.contexts: list[RuntimeReceiptVerificationContext] = []
        self.tamper_field: str | None = None
        self.disposition = Mem0OssReceiptDisposition.COMPLETED
        self.raise_secret = False

    def verify_dispatch_receipt(
        self, *, payload: object, context: RuntimeReceiptVerificationContext
    ) -> RuntimeReceiptVerificationResult:
        assert context.readback_only is False
        return self._result(payload, context)

    def verify_status_readback(
        self, *, payload: object, context: RuntimeReceiptVerificationContext
    ) -> RuntimeReceiptVerificationResult:
        assert context.readback_only is True
        return self._result(payload, context)

    def _result(
        self, payload: object, context: RuntimeReceiptVerificationContext
    ) -> RuntimeReceiptVerificationResult:
        if self.raise_secret:
            raise RuntimeError("secret-runtime-receipt-message")
        self.contexts.append(context)
        assert payload == {"receipt": "safe"}
        values = {
            "admission_commitment_sha256": context.admission_commitment_sha256,
            "operation_id_sha256": context.operation_id_sha256,
            "unit_identity_sha256": context.unit_identity_sha256,
            "unit_sha256": context.unit_sha256,
            "route_sha256": context.route_sha256,
            "scope_sha256": context.scope_sha256,
            "provider_receipt_sha256": _sha(f"receipt-{context.operation_id_sha256}"),
            "disposition": self.disposition,
            "extraction_calls": 1,
            "retry_count": 0,
            "request_tokens": 100,
            "response_tokens": 20,
        }
        if self.tamper_field is not None:
            values[self.tamper_field] = _sha("tampered")
        return RuntimeReceiptVerificationResult(**values)  # type: ignore[arg-type]


class _StoragePort:
    def __init__(self) -> None:
        self.tamper_field: str | None = None
        self.raise_secret = False

    def verify(
        self, *, payload: object, context: StorageVerificationContext
    ) -> StorageVerificationResult:
        if self.raise_secret:
            raise RuntimeError("secret-storage-adapter-message")
        assert payload == {"storage": "safe"}
        values = {
            "admission_commitment_sha256": context.admission_commitment_sha256,
            "operation_id_sha256": context.operation_id_sha256,
            "unit_identity_sha256": context.unit_identity_sha256,
            "unit_sha256": context.unit_sha256,
            "route_sha256": context.route_sha256,
            "scope_sha256": context.scope_sha256,
            "provider_receipt_sha256": context.provider_receipt_sha256,
            "stored_identity_sha256": _sha(f"stored-{context.operation_id_sha256}"),
            "stored_record_count": 1,
        }
        if self.tamper_field is not None:
            values[self.tamper_field] = _sha("tampered")
        return StorageVerificationResult(**values)  # type: ignore[arg-type]


class _CleanupPort:
    def __init__(self) -> None:
        self.residual_count = 0
        self.tamper_binding = False
        self.forced_result: CleanupVerificationResult | None = None
        self.last_result: CleanupVerificationResult | None = None
        self.raise_secret = False

    def verify(
        self, *, payload: object, context: CleanupVerificationContext
    ) -> CleanupVerificationResult:
        if self.raise_secret:
            raise RuntimeError("secret-cleanup-adapter-message")
        assert payload == {"cleanup": "safe"}
        if self.forced_result is not None:
            return self.forced_result
        self.last_result = CleanupVerificationResult(
            admission_commitment_sha256=(
                _sha("tampered") if self.tamper_binding else context.admission_commitment_sha256
            ),
            seal_commitment_sha256=context.seal_commitment_sha256,
            operation_root_sha256=context.operation_root_sha256,
            operation_inventory_root_sha256=context.operation_inventory_root_sha256,
            deleted_operation_count=context.expected_operation_count if not context.aborting else 0,
            residual_record_count=self.residual_count,
            residual_root_sha256=(
                MEM0_OSS_EMPTY_ROOT_SHA256 if self.residual_count == 0 else _sha("residue")
            ),
        )
        return self.last_result


def _request(count: int) -> Mem0OssAdmissionRequest:
    return Mem0OssAdmissionRequest(
        run_id="run-v5",
        route_sha256=_sha("route"),
        credential_binding_sha256=_sha("credential-reference"),
        model="gpt-5.6-sol",
        reasoning_effort="medium",
        service_tier="priority",
        runtime_source_revision="620644a8",
        runtime_source_sha256=_sha("runtime-source"),
        runtime_base_sha256=_sha("runtime-base"),
        expected_operation_count=count,
    )


def _service(
    count: int,
) -> tuple[Mem0OssFullRunService, _ManifestPort, _ReceiptPort, _StoragePort, _CleanupPort]:
    manifest = _ManifestPort(_units(count))
    receipt = _ReceiptPort()
    storage = _StoragePort()
    cleanup = _CleanupPort()
    service = Mem0OssFullRunService(
        manifest_port=manifest,
        receipt_port=receipt,
        storage_port=storage,
        cleanup_port=cleanup,
    )
    return service, manifest, receipt, storage, cleanup


def _active(
    count: int,
) -> tuple[Mem0OssFullRunService, _ManifestPort, _ReceiptPort, _StoragePort, _CleanupPort]:
    service, manifest, receipt, storage, cleanup = _service(count)
    service.admit(_request(count), manifest_authority_payload={"authority": "verified"})
    service.activate(admission_commitment_sha256=service.admission.commitment_sha256)
    return service, manifest, receipt, storage, cleanup


def _complete(service: Mem0OssFullRunService, unit_index: int) -> None:
    service.reserve(unit_index=unit_index)
    service.record_dispatched(unit_index=unit_index)
    service.verify_dispatch_receipt(unit_index=unit_index, receipt_payload={"receipt": "safe"})
    service.verify_storage(unit_index=unit_index, storage_payload={"storage": "safe"})
    service.commit(unit_index=unit_index)


def _sealed(
    count: int,
) -> tuple[Mem0OssFullRunService, _ManifestPort, _ReceiptPort, _StoragePort, _CleanupPort]:
    service, manifest, receipt, storage, cleanup = _active(count)
    for index in range(count):
        _complete(service, index)
    service.seal()
    return service, manifest, receipt, storage, cleanup


def _rechain(pages: tuple[Mem0OssEvidencePage, ...]) -> tuple[Mem0OssEvidencePage, ...]:
    rechained: list[Mem0OssEvidencePage] = []
    previous = MEM0_OSS_EMPTY_ROOT_SHA256
    for page in pages:
        base = replace(page, previous_page_commitment_sha256=previous)
        rebuilt = replace(
            base,
            page_commitment_sha256=canonical_sha256(base.payload_without_commitment()),
        )
        rechained.append(rebuilt)
        previous = rebuilt.page_commitment_sha256
    return tuple(rechained)


def test_exact_run_uses_verified_ports_seals_page_chain_and_deletes() -> None:
    service, _, receipt, _, _ = _sealed(3)
    pages = service.sealed_evidence_pages(page_size=2)

    verify_mem0_oss_sealed_evidence_pages(pages, seal=service.seal_evidence)
    assert service.seal_evidence.provider_observed_extraction_calls == 3
    assert service.seal_evidence.provider_observed_request_tokens == 300
    assert service.seal_evidence.provider_observed_response_tokens == 60
    assert [context.readback_only for context in receipt.contexts] == [False, False, False]
    service.begin_delete()
    service.finish_delete(cleanup_payload={"cleanup": "safe"})
    assert service.state is Mem0OssFullRunState.DELETED
    terminal = service.terminal_cleanup_evidence
    assert terminal.terminal_state == Mem0OssFullRunState.DELETED.value
    assert terminal.admission_commitment_sha256 == service.admission.commitment_sha256
    assert terminal.seal_commitment_sha256 == service.seal_evidence.commitment_sha256
    assert terminal.operation_root_sha256 == service.seal_evidence.operation_root_sha256
    assert terminal.residual_record_count == 0
    assert terminal.provider_observed_extraction_calls == 3
    assert terminal.provider_observed_request_tokens == 300
    assert terminal.provider_observed_response_tokens == 60
    assert terminal.failed_receipts == ()
    assert service.terminal_cleanup_commitment_sha256 == terminal.commitment_sha256
    with pytest.raises((AttributeError, TypeError)):
        terminal.deleted_operation_count = 0  # type: ignore[misc]


def test_no_public_dto_to_verified_factory_exists() -> None:
    public_names = set(contracts.__all__)
    assert not {name for name in public_names if "Verified" in name or "accept" in name.lower()}
    assert not hasattr(contracts, "VerifiedRuntimeReceipt")
    assert not hasattr(contracts, "accept_receipt_from_verification_port")


def _assert_fixed_port_error(error: pytest.ExceptionInfo[Mem0OssFullRunError], code: str) -> None:
    assert error.value.code == code
    assert str(error.value) == code
    assert "secret" not in str(error.value)
    assert error.value.__cause__ is None
    assert error.value.__suppress_context__ is True


def test_every_external_port_error_is_translated_without_secret_message() -> None:
    service, manifest, _, _, _ = _service(1)
    manifest.raise_secret = True
    with pytest.raises(Mem0OssFullRunError) as error:
        service.admit(_request(1), manifest_authority_payload={"authority": "verified"})
    _assert_fixed_port_error(error, "mem0_v5_manifest_verification_failed")

    service, _, receipt, _, _ = _active(1)
    service.reserve(unit_index=0)
    service.record_dispatched(unit_index=0)
    receipt.raise_secret = True
    with pytest.raises(Mem0OssFullRunError) as error:
        service.verify_dispatch_receipt(unit_index=0, receipt_payload={"receipt": "safe"})
    _assert_fixed_port_error(error, "mem0_v5_receipt_verification_failed")

    service, _, receipt, _, _ = _active(1)
    service.reserve(unit_index=0)
    service.record_dispatched(unit_index=0)
    service.recover_after_crash()
    receipt.raise_secret = True
    with pytest.raises(Mem0OssFullRunError) as error:
        service.reconcile_receipt_readback(
            unit_index=0,
            receipt_payload={"receipt": "safe"},
        )
    _assert_fixed_port_error(error, "mem0_v5_receipt_readback_failed")

    service, _, _, storage, _ = _active(1)
    service.reserve(unit_index=0)
    service.record_dispatched(unit_index=0)
    service.verify_dispatch_receipt(unit_index=0, receipt_payload={"receipt": "safe"})
    storage.raise_secret = True
    with pytest.raises(Mem0OssFullRunError) as error:
        service.verify_storage(unit_index=0, storage_payload={"storage": "safe"})
    _assert_fixed_port_error(error, "mem0_v5_storage_verification_failed")

    service, _, _, _, cleanup = _sealed(1)
    service.begin_delete()
    cleanup.raise_secret = True
    with pytest.raises(Mem0OssFullRunError) as error:
        service.finish_delete(cleanup_payload={"cleanup": "safe"})
    _assert_fixed_port_error(error, "mem0_v5_cleanup_verification_failed")


def test_failed_receipt_disposition_cannot_reach_storage_or_seal() -> None:
    service, _, receipt, _, _ = _active(1)
    service.reserve(unit_index=0)
    service.record_dispatched(unit_index=0)
    receipt.disposition = Mem0OssReceiptDisposition.PROVIDER_FAILED
    with pytest.raises(
        Mem0OssFullRunError,
        match="mem0_v5_receipt_disposition_not_successful",
    ):
        service.verify_dispatch_receipt(unit_index=0, receipt_payload={"receipt": "safe"})
    assert service.state is Mem0OssFullRunState.FAILED

    receipt.disposition = Mem0OssReceiptDisposition.COMPLETED
    with pytest.raises(Mem0OssFullRunError, match="mem0_v5_run_not_active"):
        service.verify_dispatch_receipt(unit_index=0, receipt_payload={"receipt": "safe"})
    assert len(receipt.contexts) == 1
    with pytest.raises(Mem0OssFullRunError, match="mem0_v5_run_not_active"):
        service.verify_storage(unit_index=0, storage_payload={"storage": "safe"})
    with pytest.raises(Mem0OssFullRunError, match="mem0_v5_run_not_active"):
        service.seal()

    service.begin_abort()
    service.finish_abort(cleanup_payload={"cleanup": "safe"})
    terminal = service.terminal_cleanup_evidence
    assert terminal.provider_observed_extraction_calls == 1
    assert terminal.provider_observed_request_tokens == 100
    assert terminal.provider_observed_response_tokens == 20
    assert len(terminal.failed_receipts) == 1
    failed = terminal.failed_receipts[0]
    assert failed.disposition == Mem0OssReceiptDisposition.PROVIDER_FAILED.value
    assert failed.extraction_calls == 1
    assert failed.request_tokens == 100
    assert failed.response_tokens == 20


def test_manifest_authority_rejects_duplicate_identity_but_allows_repeated_content() -> None:
    service, manifest, _, _, _ = _service(2)
    duplicate_identity = replace(
        manifest.units[1], unit_identity_sha256=manifest.units[0].unit_identity_sha256
    )
    manifest.units = (manifest.units[0], duplicate_identity)
    with pytest.raises(Mem0OssFullRunError, match="mem0_v5_manifest_duplicate_unit_identity"):
        service.admit(_request(2), manifest_authority_payload={"authority": "verified"})

    service, manifest, _, _, _ = _service(2)
    duplicate_hash = replace(manifest.units[1], unit_sha256=manifest.units[0].unit_sha256)
    manifest.units = (manifest.units[0], duplicate_hash)
    manifest.root_override = manifest_root_sha256(manifest.units)
    service.admit(_request(2), manifest_authority_payload={"authority": "verified"})
    assert service.admission.ingestion_unit_count == 2


def test_manifest_root_count_and_type_impostor_fail_closed() -> None:
    service, manifest, _, _, _ = _service(2)
    manifest.root_override = _sha("wrong-root")
    with pytest.raises(Mem0OssFullRunError, match="mem0_v5_manifest_root_mismatch"):
        service.admit(_request(2), manifest_authority_payload={"authority": "verified"})

    service, _, _, _, _ = _service(2)
    with pytest.raises(Mem0OssFullRunError, match="mem0_v5_manifest_count_mismatch"):
        service.admit(_request(1), manifest_authority_payload={"authority": "verified"})

    service, manifest, _, _, _ = _service(1)
    manifest.return_impostor = True
    with pytest.raises(Mem0OssFullRunError, match="mem0_v5_manifest_authority_result_invalid"):
        service.admit(_request(1), manifest_authority_payload={"authority": "verified"})


@pytest.mark.parametrize(
    "field",
    [
        "admission_commitment_sha256",
        "operation_id_sha256",
        "unit_identity_sha256",
        "unit_sha256",
        "route_sha256",
        "scope_sha256",
    ],
)
def test_forged_receipt_binding_is_rejected(field: str) -> None:
    service, _, receipt, _, _ = _active(1)
    service.reserve(unit_index=0)
    service.record_dispatched(unit_index=0)
    receipt.tamper_field = field
    with pytest.raises(Mem0OssFullRunError, match="mem0_v5_receipt_binding_mismatch"):
        service.verify_dispatch_receipt(unit_index=0, receipt_payload={"receipt": "safe"})


def test_forged_storage_and_cleanup_proofs_are_rejected() -> None:
    service, _, _, storage, _ = _active(1)
    service.reserve(unit_index=0)
    service.record_dispatched(unit_index=0)
    service.verify_dispatch_receipt(unit_index=0, receipt_payload={"receipt": "safe"})
    storage.tamper_field = "scope_sha256"
    with pytest.raises(Mem0OssFullRunError, match="mem0_v5_storage_binding_mismatch"):
        service.verify_storage(unit_index=0, storage_payload={"storage": "safe"})

    service, _, _, _, cleanup = _sealed(1)
    service.begin_delete()
    cleanup.tamper_binding = True
    with pytest.raises(Mem0OssFullRunError, match="mem0_v5_cleanup_binding_mismatch"):
        service.finish_delete(cleanup_payload={"cleanup": "safe"})
    with pytest.raises(Mem0OssFullRunError, match="mem0_v5_terminal_cleanup_not_available"):
        _ = service.terminal_cleanup_evidence


def test_crash_after_dispatch_requires_readback_and_never_redispatches() -> None:
    service, _, receipt, _, _ = _active(2)
    service.reserve(unit_index=0)
    service.record_dispatched(unit_index=0)
    service.reserve(unit_index=1)

    assert service.recover_after_crash() == (1,)
    assert service.state is Mem0OssFullRunState.RECONCILIATION_REQUIRED
    with pytest.raises(Mem0OssFullRunError, match="mem0_v5_run_not_active"):
        service.record_dispatched(unit_index=0)

    service.reconcile_receipt_readback(unit_index=0, receipt_payload={"receipt": "safe"})
    assert receipt.contexts[-1].readback_only is True
    assert service.state is Mem0OssFullRunState.ACTIVE
    service.verify_storage(unit_index=0, storage_payload={"storage": "safe"})
    service.commit(unit_index=0)
    service.record_dispatched(unit_index=1)


def test_crash_unknown_can_abort_with_exact_zero_residue_cleanup() -> None:
    service, _, _, _, _ = _active(1)
    service.reserve(unit_index=0)
    service.record_dispatched(unit_index=0)
    service.recover_after_crash()
    service.begin_abort()
    service.finish_abort(cleanup_payload={"cleanup": "safe"})
    assert service.state is Mem0OssFullRunState.ABORTED
    terminal = service.terminal_cleanup_evidence
    assert terminal.terminal_state == Mem0OssFullRunState.ABORTED.value
    assert terminal.seal_commitment_sha256 is None
    assert terminal.operation_root_sha256 is None
    assert terminal.admission_commitment_sha256 == service.admission.commitment_sha256


def test_abort_rejects_residue_and_does_not_wedge() -> None:
    service, _, _, _, cleanup = _active(1)
    service.reserve(unit_index=0)
    service.record_dispatched(unit_index=0)
    service.recover_after_crash()
    service.begin_abort()
    cleanup.residual_count = 1
    with pytest.raises(Mem0OssFullRunError, match="mem0_v5_cleanup_residue_detected"):
        service.finish_abort(cleanup_payload={"cleanup": "safe"})
    assert service.state is Mem0OssFullRunState.ABORTING


def test_abort_cleanup_rejects_proof_captured_before_dispatch() -> None:
    before, _, _, _, cleanup = _active(1)
    before.begin_abort()
    before.finish_abort(cleanup_payload={"cleanup": "safe"})
    captured = cleanup.last_result
    assert captured is not None

    after, _, _, _, cleanup_after = _active(1)
    after.reserve(unit_index=0)
    after.record_dispatched(unit_index=0)
    after.recover_after_crash()
    after.begin_abort()
    cleanup_after.forced_result = captured
    with pytest.raises(Mem0OssFullRunError, match="mem0_v5_cleanup_binding_mismatch"):
        after.finish_abort(cleanup_payload={"cleanup": "safe"})


def test_evidence_is_sealed_only_and_snapshot_is_immutable() -> None:
    service, _, _, _, _ = _active(1)
    with pytest.raises(Mem0OssFullRunError, match="mem0_v5_evidence_requires_sealed_snapshot"):
        service.sealed_evidence_pages(page_size=1)
    _complete(service, 0)
    service.seal()
    pages = service.sealed_evidence_pages(page_size=1)
    with pytest.raises((AttributeError, TypeError)):
        pages[0].items[0].unit_index = 7  # type: ignore[misc]


@pytest.mark.parametrize("attack", ["reorder", "omit", "duplicate"])
def test_whole_sequence_verifier_rejects_reorder_omit_and_duplicate(attack: str) -> None:
    service, _, _, _, _ = _sealed(5)
    pages = service.sealed_evidence_pages(page_size=2)
    attacked = {
        "reorder": (pages[1], pages[0], pages[2]),
        "omit": pages[:-1],
        "duplicate": (pages[0], pages[1], pages[1], pages[2]),
    }[attack]
    with pytest.raises(Mem0OssFullRunError):
        verify_mem0_oss_sealed_evidence_pages(attacked, seal=service.seal_evidence)


def test_page_chain_rejects_forged_item_commitment_and_noncontiguous_index() -> None:
    service, _, _, _, _ = _sealed(3)
    pages = service.sealed_evidence_pages(page_size=2)
    forged_item = replace(pages[0].items[0], commitment_sha256=_sha("forged"))
    forged_page = replace(pages[0], items=(forged_item, pages[0].items[1]))
    forged_chain = _rechain((forged_page, pages[1]))
    with pytest.raises(Mem0OssFullRunError, match="mem0_v5_evidence_coverage_invalid"):
        verify_mem0_oss_sealed_evidence_pages(forged_chain, seal=service.seal_evidence)

    duplicate_index = replace(pages[0].items[1], unit_index=0)
    base = replace(pages[0], items=(pages[0].items[0], duplicate_index))
    recomputed = _rechain((base, pages[1]))
    with pytest.raises(Mem0OssFullRunError, match="mem0_v5_evidence_coverage_invalid"):
        verify_mem0_oss_sealed_evidence_pages(recomputed, seal=service.seal_evidence)


def test_evidence_rejects_type_impostors_and_forged_seal_usage_totals() -> None:
    service, _, _, _, _ = _sealed(2)
    pages = service.sealed_evidence_pages(page_size=1)
    with pytest.raises(Mem0OssFullRunError, match="mem0_v5_evidence_page_invalid"):
        replace(pages[0], page_index=False)
    with pytest.raises(Mem0OssFullRunError, match="mem0_v5_operation_evidence_invalid"):
        replace(pages[0].items[0], unit_index=False)

    forged_seal = replace(
        service.seal_evidence,
        provider_observed_request_tokens=(
            service.seal_evidence.provider_observed_request_tokens + 1
        ),
    )
    rebound = tuple(
        replace(page, seal_commitment_sha256=forged_seal.commitment_sha256) for page in pages
    )
    with pytest.raises(Mem0OssFullRunError, match="mem0_v5_evidence_coverage_invalid"):
        verify_mem0_oss_sealed_evidence_pages(_rechain(rebound), seal=forged_seal)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("expected_operation_count", True),
        ("route_sha256", "not-a-digest"),
        ("credential_binding_sha256", "account@example.com"),
        ("model", ""),
    ],
)
def test_admission_request_rejects_type_impostors_and_unsafe_values(
    field: str, value: object
) -> None:
    values = {
        "run_id": "run-v5",
        "route_sha256": _sha("route"),
        "credential_binding_sha256": _sha("credential"),
        "model": "gpt-5.6-sol",
        "reasoning_effort": "medium",
        "service_tier": "priority",
        "runtime_source_revision": "620644a8",
        "runtime_source_sha256": _sha("source"),
        "runtime_base_sha256": _sha("base"),
        "expected_operation_count": 1,
    }
    values[field] = value
    with pytest.raises(Mem0OssFullRunError, match="mem0_v5_admission_request_invalid"):
        Mem0OssAdmissionRequest(**values)  # type: ignore[arg-type]


def test_v5_addition_leaves_frozen_v3_v4_sources_and_fixtures_byte_exact() -> None:
    root = Path(__file__).resolve().parents[2]
    expected = {
        "packages/infinity_context_server/infinity_context_server/"
        "memory_comparison_mem0_oss_contract.py": (
            "105200d25bf548c975afe351e9d28df3ec1e0ffd73ff3195be161dd845d3ee2e"
        ),
        "packages/infinity_context_server/infinity_context_server/"
        "memory_comparison_mem0_oss_manifest.py": (
            "9d592a51127f31e28ba981d7cbd2036a5d09f206cd8ff62d4b67152305311afe"
        ),
        "tests/unit/test_memory_comparison_mem0_oss_contract.py": (
            "2f29f70df3bf6fa2bab6a2dcef9b2fac1c20172938cccbb8a4f71d89d197872a"
        ),
        "packages/infinity_context_server/infinity_context_server/"
        "memory_comparison_mem0_oss_v4_contract.py": (
            "6ed0c4905950b872298f7fe32cfe71cd17c7beea482575b8ffe5a65c865720e2"
        ),
        "packages/infinity_context_server/infinity_context_server/"
        "memory_comparison_mem0_oss_v4_manifest.py": (
            "1ade2e2e281a2a719fdbc64c91cd6d9e94dcd661f762b4ec30000d44cd263db9"
        ),
        "tests/unit/test_memory_comparison_mem0_oss_v4_contract.py": (
            "75b8d9e7afe5d04191fdda2e2254907ef94fb91504f7c0fa175bd0348332b93e"
        ),
    }
    assert {
        relative: hashlib.sha256((root / relative).read_bytes()).hexdigest()
        for relative in expected
    } == expected

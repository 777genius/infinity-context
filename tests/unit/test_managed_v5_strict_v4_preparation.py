from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from infinity_context_adapters.postgres.managed_cleanup_v3_expected_row_authority import (
    SQLiteManagedCleanupV3ExpectedRowAuthority,
)
from infinity_context_adapters.postgres.managed_cleanup_v3_sqlite_preparation import (
    SQLiteManagedCleanupV3PreparationStore,
)
from infinity_context_adapters.postgres.managed_mem0_v6_sqlite_preparation import (
    SQLiteManagedMem0V6PreparationStore,
)
from infinity_context_adapters.postgres.managed_strict_v4_preparation_receipt import (
    SQLiteStrictV4PreparationReceiptStore,
)
from infinity_context_core.features.projection_receipts import (
    ContextAuthorityRegistration,
    ProjectionReceiptAuthenticator,
    ProjectionReceiptError,
)
from infinity_context_core.features.projection_receipts.strict_v4_preparation import (
    authenticate_strict_v4_preparation_receipt,
)
from infinity_context_core.ports.managed_cleanup_v3_contracts import commitment
from infinity_context_server.memory_comparison_full_profiles import (
    resolve_full_comparison_profile,
)
from infinity_context_server.memory_comparison_full_run_evidence import (
    FullComparisonBackendTarget,
)
from infinity_context_server.memory_comparison_managed_full_run_extraction_ledger import (
    build_managed_full_run_extraction_context,
    recover_managed_full_run_extraction_ledger,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestProjector,
)
from infinity_context_server.memory_comparison_managed_plan_builder import (
    build_managed_public_run_projection,
)
from infinity_context_server.memory_comparison_managed_v5_cleanup_v4_projector import (
    ManagedV5CleanupV4OperationProjector,
)
from infinity_context_server.memory_comparison_managed_v5_strict_v4_preparation import (
    StrictV4FullPreparationInputs,
    _a1_store,
    _a2_store,
    _assert_registration_matches,
    _open_or_create_expected_index,
    _validate_artifact_paths,
    _verify_original_pair_binding,
    prepare_strict_v4_full_run,
    recover_strict_v4_full_run,
)
from infinity_context_server.original_pair_identity_authority import (
    SQLiteOriginalPairIdentityAuthority,
)

KEY = b"strict-v4-full-preparation-test-key" * 2
AUTH = ProjectionReceiptAuthenticator(b"strict-v4-full-preparation-receipt" * 2)
WHEN = datetime(2026, 8, 9, tzinfo=UTC)


class _Keys:
    def __init__(self, *, a2: bytes = KEY) -> None:
        self._values = {
            ("a1", "a1-test-key"): KEY,
            ("a2", "a2-test-key"): a2,
            ("expected-index", "expected-test-key"): KEY,
        }

    def resolve(self, *, purpose: str, key_id: str) -> bytes:
        return self._values[(purpose, key_id)]


class _Registry:
    def __init__(self) -> None:
        self.value: ContextAuthorityRegistration | None = None
        self.provider_calls = 0

    async def register_and_readback(self, **values: object) -> ContextAuthorityRegistration:
        candidate = ContextAuthorityRegistration(
            context=values["context"],
            authority=values["authority"],
            registration_sha256=values["registration_sha256"],
            registration_mac_sha256=values["registration_mac_sha256"],
            registered_at=values["registered_at"],
            created=self.value is None,
        )
        if self.value is None:
            self.value = candidate
        else:
            candidate = ContextAuthorityRegistration(
                context=self.value.context,
                authority=self.value.authority,
                registration_sha256=self.value.registration_sha256,
                registration_mac_sha256=self.value.registration_mac_sha256,
                registered_at=self.value.registered_at,
                created=False,
            )
        return candidate


class _NeverReceiptVerifier:
    def mark_outcome_unknown(self, *, context: object) -> None:
        del context
        raise AssertionError("receipt verifier must remain unused during composition")

    def verify_dispatch_receipt(self, *, payload: object, context: object) -> object:
        del payload, context
        raise AssertionError("receipt verifier must remain unused during composition")

    def verify_status_readback(self, *, payload: object, context: object) -> object:
        del payload, context
        raise AssertionError("receipt verifier must remain unused during composition")


def _inputs(
    tmp_path: Path,
    *,
    ingestion_root_sha256: str,
    run_id_sha256: str,
    case_manifest_sha256: str,
    publishable_profile_commitment_sha256: str = "2" * 64,
) -> StrictV4FullPreparationInputs:
    q_target, q_policy = "a" * 64, "b" * 64
    g_target, g_policy = "c" * 64, "d" * 64
    return StrictV4FullPreparationInputs(
        run_id_sha256=run_id_sha256,
        publishable_profile_commitment_sha256=publishable_profile_commitment_sha256,
        ingestion_root_sha256=ingestion_root_sha256,
        case_manifest_sha256=case_manifest_sha256,
        infinity_target_identity_sha256="a" * 64,
        space_id=f"benchmark-space-{'1' * 48}",
        space_slug="strict-v4-test",
        cleanup_target_authority_sha256="6" * 64,
        qdrant_authority_sha256=commitment(
            "lane-authority/v4",
            {
                "lane": "qdrant",
                "target_commitment_sha256": q_target,
                "policy_commitment_sha256": q_policy,
            },
        ),
        qdrant_target_commitment_sha256=q_target,
        qdrant_policy_commitment_sha256=q_policy,
        graphiti_authority_sha256=commitment(
            "lane-authority/v4",
            {
                "lane": "graphiti",
                "target_commitment_sha256": g_target,
                "policy_commitment_sha256": g_policy,
            },
        ),
        graphiti_target_commitment_sha256=g_target,
        graphiti_policy_commitment_sha256=g_policy,
        cognee_policy_sha256="7" * 64,
        namespace_policy_sha256="8" * 64,
        original_pair_path=None,
        original_pair_key_id=None,
        a1_path=str(tmp_path / "a1.sqlite3"),
        a1_key_id="a1-test-key",
        a2_path=str(tmp_path / "a2.sqlite3"),
        a2_key_id="a2-test-key",
        expected_index_path=str(tmp_path / "expected.sqlite3"),
        expected_index_key_id="expected-test-key",
    )


@pytest.mark.anyio
async def test_full_locomo_prepares_and_recovers_without_reprojection(tmp_path: Path) -> None:
    dataset_path = Path("/tmp/locomo10.ingestion-manifest-r1.json")
    if not dataset_path.is_file():
        pytest.skip("official LoCoMo dataset is not staged")
    profile = resolve_full_comparison_profile("mem0-locomo-top50-v1")
    assert profile is not None
    projection = build_managed_public_run_projection(
        run_id="strict-v4-full-preparation-test",
        run_nonce_commitment_sha256="9" * 64,
        runtime_probe_nonce_sha256="e" * 64,
        profile=profile,
        dataset_bytes=dataset_path.read_bytes(),
        backend_targets=(
            FullComparisonBackendTarget("infinity-context", "a" * 64),
            FullComparisonBackendTarget("mem0", "b" * 64),
        ),
        scope="full",
    )
    manifest = ManagedMem0V5ManifestProjector().project(projection.cases, current_date="2026-08-09")
    projector = ManagedV5CleanupV4OperationProjector(
        projection=projection,
        manifest_authority=manifest,
        admission_commitment_sha256="f" * 64,
        profile_id="mem0-locomo-top50-v1",
    )
    receipt_store = SQLiteStrictV4PreparationReceiptStore.create(tmp_path / "receipt.sqlite3")
    registry = _Registry()
    inputs = _inputs(
        tmp_path,
        ingestion_root_sha256=manifest.ingestion_root_sha256,
        run_id_sha256=hashlib.sha256(projection.bindings.run_id.encode()).hexdigest(),
        case_manifest_sha256=projection.case_manifest_sha256,
        publishable_profile_commitment_sha256=(projection.publishable_profile_commitment_sha256),
    )
    with pytest.raises(ProjectionReceiptError, match="ingestion_root_invalid"):
        await prepare_strict_v4_full_run(
            projector=projector,
            inputs=replace(inputs, ingestion_root_sha256="0" * 64),
            registration_port=registry,
            receipt_store=receipt_store,
            key_identity_authority=_Keys(),
            authenticator=AUTH,
            registered_at=WHEN,
            prepared_at=WHEN,
        )
    assert not Path(inputs.a1_path).exists()
    assert not Path(inputs.a2_path).exists()
    assert registry.value is None
    with pytest.raises(ProjectionReceiptError, match="run_id_invalid"):
        await prepare_strict_v4_full_run(
            projector=projector,
            inputs=replace(inputs, run_id_sha256="0" * 64),
            registration_port=registry,
            receipt_store=receipt_store,
            key_identity_authority=_Keys(),
            authenticator=AUTH,
            registered_at=WHEN,
            prepared_at=WHEN,
        )
    assert not Path(inputs.a1_path).exists()
    assert registry.value is None
    with pytest.raises(ProjectionReceiptError, match="profile_invalid"):
        await prepare_strict_v4_full_run(
            projector=projector,
            inputs=replace(inputs, publishable_profile_commitment_sha256="0" * 64),
            registration_port=registry,
            receipt_store=receipt_store,
            key_identity_authority=_Keys(),
            authenticator=AUTH,
            registered_at=WHEN,
            prepared_at=WHEN,
        )
    assert not Path(inputs.a1_path).exists()
    assert registry.value is None
    with pytest.raises(ProjectionReceiptError, match="case_manifest_invalid"):
        await prepare_strict_v4_full_run(
            projector=projector,
            inputs=replace(inputs, case_manifest_sha256="0" * 64),
            registration_port=registry,
            receipt_store=receipt_store,
            key_identity_authority=_Keys(),
            authenticator=AUTH,
            registered_at=WHEN,
            prepared_at=WHEN,
        )
    assert not Path(inputs.a1_path).exists()
    assert registry.value is None
    with pytest.raises(ProjectionReceiptError, match="target_invalid"):
        await prepare_strict_v4_full_run(
            projector=projector,
            inputs=replace(inputs, infinity_target_identity_sha256="0" * 64),
            registration_port=registry,
            receipt_store=receipt_store,
            key_identity_authority=_Keys(),
            authenticator=AUTH,
            registered_at=WHEN,
            prepared_at=WHEN,
        )
    assert not Path(inputs.a1_path).exists()
    assert registry.value is None
    with pytest.raises(ProjectionReceiptError, match="space_invalid"):
        await prepare_strict_v4_full_run(
            projector=projector,
            inputs=replace(inputs, space_id="strict-v4-test"),
            registration_port=registry,
            receipt_store=receipt_store,
            key_identity_authority=_Keys(),
            authenticator=AUTH,
            registered_at=WHEN,
            prepared_at=WHEN,
        )
    assert not Path(inputs.a1_path).exists()
    assert registry.value is None
    receipt = await prepare_strict_v4_full_run(
        projector=projector,
        inputs=inputs,
        registration_port=registry,
        receipt_store=receipt_store,
        key_identity_authority=_Keys(),
        authenticator=AUTH,
        registered_at=WHEN,
        prepared_at=WHEN,
    )
    assert receipt.a2_authority.operation_count == 5_882
    extraction_context = build_managed_full_run_extraction_context(
        preparation_receipt=receipt,
        preparation_authenticator=AUTH,
        runtime_binding_commitment_sha256="8" * 64,
    )
    assert extraction_context.expected_receipt_count == 5_882
    assert extraction_context.a1_terminal_commitment_sha256 == (
        receipt.a1_authority.terminal_commitment_sha256
    )
    assert extraction_context.a1_manifest_context_sha256 == (
        receipt.a1_context.manifest_context_sha256
    )
    assert extraction_context.admission_commitment_sha256 == receipt.admission_commitment_sha256
    extraction = await recover_managed_full_run_extraction_ledger(
        receipt_store=receipt_store,
        registration_port=registry,
        preparation_authenticator=AUTH,
        key_identity_authority=_Keys(),
        ledger_path=tmp_path / "extraction-ledger.sqlite3",
        ledger_authentication_key=b"extraction-ledger-test-key-32bytes!",
        runtime_binding_commitment_sha256="8" * 64,
        receipt_verifier=_NeverReceiptVerifier(),  # type: ignore[arg-type]
    )
    assert extraction.readback() is None
    extraction.close()
    assert receipt.provider_calls == registry.provider_calls == 0
    assert receipt.paid_go_ready is False
    assert receipt.a1_key_commitment_sha256 != receipt.a2_key_commitment_sha256
    assert receipt.receipt_key_commitment_sha256
    with pytest.raises(ProjectionReceiptError, match="preparation_invalid"):
        authenticate_strict_v4_preparation_receipt(
            replace(receipt, prepared_at=receipt.registered_at - timedelta(seconds=1)),
            authenticator=AUTH,
        )
    assert receipt.a1_context.manifest_context_sha256 == receipt.a2_context.manifest_context_sha256
    assert (
        receipt.a1_authority.terminal_commitment_sha256
        == receipt.a1_store_receipt.authority_terminal_commitment_sha256
        == receipt.a2_context.a1_terminal_commitment_sha256
    )
    assert (
        receipt.a2_authority.terminal_commitment_sha256
        == receipt.a2_store_receipt.terminal_commitment_sha256
        == receipt.expected_index_terminal_sha256
    )
    receipt_store.close()
    receipt_store = SQLiteStrictV4PreparationReceiptStore.open(tmp_path / "receipt.sqlite3")
    with pytest.raises(ProjectionReceiptError, match="key_binding_invalid"):
        await recover_strict_v4_full_run(
            receipt_store=receipt_store,
            registration_port=registry,
            authenticator=AUTH,
            key_identity_authority=_Keys(a2=b"crosswired-a2-key-is-invalid!" * 2),
        )
    recovered = await recover_strict_v4_full_run(
        receipt_store=receipt_store,
        registration_port=registry,
        authenticator=AUTH,
        key_identity_authority=_Keys(),
    )
    assert recovered == receipt
    receipt_store.close()


@pytest.mark.anyio
async def test_recovery_rejects_tampered_receipt(tmp_path: Path) -> None:
    path = tmp_path / "receipt.sqlite3"
    store = SQLiteStrictV4PreparationReceiptStore.create(path)
    store.close()
    # A receipt-less or partially written journal is never treated as recoverable authority.
    reopened = SQLiteStrictV4PreparationReceiptStore.open(path)
    with pytest.raises(ProjectionReceiptError, match="preparation_missing"):
        await recover_strict_v4_full_run(
            receipt_store=reopened,
            registration_port=_Registry(),
            authenticator=AUTH,
            key_identity_authority=_Keys(),
        )
    reopened.close()


def test_original_pair_path_must_authenticate_and_match_projector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fields = {
        "profile_id": "mem0-longmemeval-top50-v1",
        "dataset_sha256": "1" * 64,
        "operation_count": 124_344,
        "original_pair_slot_count": 124_345,
        "omitted_source_identity_count": 1,
        "omitted_source_identity_root_sha256": "2" * 64,
        "omitted_original_pair_identity_root_sha256": "3" * 64,
        "original_pair_slot_root_sha256": "4" * 64,
        "ordered_mapping_root_sha256": "5" * 64,
        "terminal_commitment_sha256": "6" * 64,
    }
    expected = SimpleNamespace(**fields)
    observed = SimpleNamespace(**{**fields, "terminal_commitment_sha256": "7" * 64})
    observed.close = lambda: None
    monkeypatch.setattr(
        SQLiteOriginalPairIdentityAuthority,
        "open",
        lambda path, *, authentication_key: observed,
    )
    with pytest.raises(ProjectionReceiptError, match="pair_invalid"):
        _verify_original_pair_binding(
            SimpleNamespace(original_pair_authority=expected),
            "/private/strict-v4-pairs.sqlite3",
            b"pair-authentication-key" * 2,
        )


def test_registration_timestamp_drift_is_rejected() -> None:
    receipt = SimpleNamespace(
        registration_sha256="1" * 64,
        registration_mac_sha256="2" * 64,
        registered_at=WHEN,
    )
    with pytest.raises(ProjectionReceiptError, match="registration_invalid"):
        _assert_registration_matches(
            receipt,
            SimpleNamespace(
                registration_sha256=receipt.registration_sha256,
                registration_mac_sha256=receipt.registration_mac_sha256,
                registered_at=datetime(2026, 8, 9, 0, 0, 1, tzinfo=UTC),
            ),
        )


def test_pre_final_retry_uses_authenticated_index_bootstrap_repair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _inputs(
        tmp_path,
        ingestion_root_sha256="1" * 64,
        run_id_sha256="2" * 64,
        case_manifest_sha256="3" * 64,
    )
    Path(inputs.expected_index_path).touch(mode=0o600)
    sentinel = object()
    observed: dict[str, object] = {}

    def repair(cls: object, path: Path, **values: object) -> object:
        observed.update(path=path, **values)
        return sentinel

    monkeypatch.setattr(
        SQLiteManagedCleanupV3ExpectedRowAuthority,
        "create_or_open_repairable_bootstrap",
        classmethod(repair),
    )
    context = SimpleNamespace(context_sha256="3" * 64)
    authority = SimpleNamespace(terminal_commitment_sha256="4" * 64)
    result = _open_or_create_expected_index(
        inputs=inputs,
        context=context,
        authority=authority,
        a2_authentication_key=KEY,
        index_authentication_key=KEY,
    )
    assert result is sentinel
    assert observed["path"] == Path(inputs.expected_index_path)
    assert observed["authentication_key"] == KEY


def test_preparation_uses_crash_safe_open_or_create_for_a1_and_a2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _inputs(
        tmp_path,
        ingestion_root_sha256="1" * 64,
        run_id_sha256="2" * 64,
        case_manifest_sha256="3" * 64,
    )
    calls: list[tuple[str, str, bytes]] = []
    a1_result, a2_result = object(), object()
    monkeypatch.setattr(
        SQLiteManagedMem0V6PreparationStore,
        "open_or_create",
        classmethod(
            lambda cls, path, *, authentication_key: (
                calls.append(("a1", str(path), authentication_key)) or a1_result
            )
        ),
    )
    monkeypatch.setattr(
        SQLiteManagedCleanupV3PreparationStore,
        "open_or_create",
        classmethod(
            lambda cls, path, *, authentication_key: (
                calls.append(("a2", str(path), authentication_key)) or a2_result
            )
        ),
    )
    assert _a1_store(inputs, KEY) is a1_result
    assert _a2_store(inputs, KEY) is a2_result
    assert calls == [
        ("a1", inputs.a1_path, KEY),
        ("a2", inputs.a2_path, KEY),
    ]


def test_artifact_paths_are_absolute_distinct_and_cwd_independent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _inputs(
        tmp_path,
        ingestion_root_sha256="1" * 64,
        run_id_sha256="2" * 64,
        case_manifest_sha256="3" * 64,
    )
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(other)
    _validate_artifact_paths(inputs)
    with pytest.raises(ProjectionReceiptError, match="path_invalid"):
        _validate_artifact_paths(replace(inputs, a1_path="relative/a1.sqlite3"))
    with pytest.raises(ProjectionReceiptError, match="path_collision"):
        _validate_artifact_paths(replace(inputs, a2_path=inputs.a1_path))
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    with pytest.raises(ProjectionReceiptError, match="path_invalid"):
        _validate_artifact_paths(replace(inputs, a1_path=str(linked_parent / "a1.sqlite3")))

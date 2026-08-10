"""Provider-free full preparation for the future strict-v4 managed path."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from infinity_context_adapters.postgres.managed_cleanup_v3_expected_row_authority import (
    SQLiteManagedCleanupV3ExpectedRowAuthority,
)
from infinity_context_adapters.postgres.managed_cleanup_v3_sqlite_preparation import (
    SQLiteManagedCleanupV3PreparationStore,
    iter_committed_pages,
)
from infinity_context_adapters.postgres.managed_mem0_v6_sqlite_preparation import (
    SQLiteManagedMem0V6PreparationStore,
)
from infinity_context_core.features.projection_receipts import (
    ContextAuthorityRegistrationPort,
    ProjectionReceiptAuthenticator,
    ProjectionReceiptError,
    register_context_authority_and_readback,
)
from infinity_context_core.features.projection_receipts.strict_v4_preparation import (
    StrictV4PreparationKeyIdentityPort,
    StrictV4PreparationReceipt,
    StrictV4PreparationReceiptPort,
    authenticate_strict_v4_preparation_receipt,
    build_strict_v4_preparation_receipt,
    strict_v4_preparation_key_commitment,
    strict_v4_receipt_key_commitment,
)
from infinity_context_core.ports.benchmark_runs import is_managed_benchmark_space_id
from infinity_context_core.ports.managed_cleanup_v3_contracts import (
    LONGMEMEVAL_PROFILE,
    PROFILE_ORACLES,
    ManagedCleanupV3Authority,
    ManagedCleanupV3Context,
    build_context,
)
from infinity_context_core.ports.managed_cleanup_v3_paged_authority import (
    build_managed_cleanup_v3_authority,
    cleanup_operation_stream_root,
)
from infinity_context_core.ports.managed_mem0_v6_manifest_contracts import (
    build_managed_mem0_v6_manifest_context,
)
from infinity_context_core.ports.managed_mem0_v6_paged_manifest import (
    build_managed_mem0_v6_paged_manifest,
)

from infinity_context_server.memory_comparison_managed_v5_cleanup_v4_projector import (
    ManagedV5CleanupV4OperationProjector,
)


@dataclass(frozen=True, slots=True)
class StrictV4FullPreparationInputs:
    run_id_sha256: str
    publishable_profile_commitment_sha256: str
    ingestion_root_sha256: str
    case_manifest_sha256: str
    infinity_target_identity_sha256: str
    space_id: str
    space_slug: str
    cleanup_target_authority_sha256: str
    qdrant_authority_sha256: str
    qdrant_target_commitment_sha256: str
    qdrant_policy_commitment_sha256: str
    graphiti_authority_sha256: str
    graphiti_target_commitment_sha256: str
    graphiti_policy_commitment_sha256: str
    cognee_policy_sha256: str
    namespace_policy_sha256: str
    original_pair_path: str | None
    original_pair_key_id: str | None
    a1_path: str
    a1_key_id: str
    a2_path: str
    a2_key_id: str
    expected_index_path: str
    expected_index_key_id: str


async def prepare_strict_v4_full_run(
    *,
    projector: ManagedV5CleanupV4OperationProjector,
    inputs: StrictV4FullPreparationInputs,
    registration_port: ContextAuthorityRegistrationPort,
    receipt_store: StrictV4PreparationReceiptPort,
    key_identity_authority: StrictV4PreparationKeyIdentityPort,
    authenticator: ProjectionReceiptAuthenticator,
    registered_at: datetime,
    prepared_at: datetime,
) -> StrictV4PreparationReceipt:
    """Prepare both paged authorities, the expected index, and PG registration."""

    _validate_artifact_paths(inputs)
    bindings = projector.projection.bindings
    if inputs.run_id_sha256 != hashlib.sha256(bindings.run_id.encode()).hexdigest():
        raise ProjectionReceiptError("projection_receipt.preparation_run_id_invalid")
    if inputs.case_manifest_sha256 != projector.projection.case_manifest_sha256:
        raise ProjectionReceiptError("projection_receipt.preparation_case_manifest_invalid")
    if (
        inputs.publishable_profile_commitment_sha256
        != projector.projection.publishable_profile_commitment_sha256
    ):
        raise ProjectionReceiptError("projection_receipt.preparation_profile_invalid")
    if inputs.ingestion_root_sha256 != projector.manifest_authority.ingestion_root_sha256:
        raise ProjectionReceiptError("projection_receipt.preparation_ingestion_root_invalid")
    if not is_managed_benchmark_space_id(inputs.space_id):
        raise ProjectionReceiptError("projection_receipt.preparation_space_invalid")
    infinity_targets = tuple(
        item.target_identity_sha256
        for item in bindings.backend_targets
        if item.backend_role == "infinity-context"
    )
    if len(infinity_targets) != 1 or inputs.infinity_target_identity_sha256 != infinity_targets[0]:
        raise ProjectionReceiptError("projection_receipt.preparation_target_invalid")
    oracle = PROFILE_ORACLES[projector.profile_id]
    pair = projector.original_pair_authority
    a1_key = _resolve_key(key_identity_authority, "a1", inputs.a1_key_id)
    a2_key = _resolve_key(key_identity_authority, "a2", inputs.a2_key_id)
    index_key = _resolve_key(key_identity_authority, "expected-index", inputs.expected_index_key_id)
    pair_key: bytes | None = None
    pair_key_commitment: str | None = None
    if projector.profile_id == LONGMEMEVAL_PROFILE:
        if pair is None or inputs.original_pair_path is None or inputs.original_pair_key_id is None:
            raise ProjectionReceiptError("projection_receipt.preparation_pair_missing")
        pair_key = _resolve_key(
            key_identity_authority, "original-pair", inputs.original_pair_key_id
        )
        _verify_original_pair_binding(projector, inputs.original_pair_path, pair_key)
        pair_terminal = pair.terminal_commitment_sha256
        pair_key_commitment = _key_commitment(
            pair_key,
            "original-pair",
            inputs.original_pair_key_id,
            inputs.run_id_sha256,
            inputs.original_pair_path,
        )
    else:
        if (
            pair is not None
            or inputs.original_pair_path is not None
            or inputs.original_pair_key_id is not None
        ):
            raise ProjectionReceiptError("projection_receipt.preparation_pair_invalid")
        pair_terminal = None

    a1_context = build_managed_mem0_v6_manifest_context(
        profile_id=projector.profile_id,
        run_id_sha256=inputs.run_id_sha256,
        binding_commitment_sha256=bindings.binding_commitment_sha256,
        publishable_profile_commitment_sha256=inputs.publishable_profile_commitment_sha256,
        methodology_commitment_sha256=bindings.methodology_commitment_sha256,
        dataset_sha256=bindings.dataset_sha256,
        admission_commitment_sha256=projector.admission_commitment_sha256,
        ingestion_root_sha256=inputs.ingestion_root_sha256,
    )
    a1_store = _a1_store(inputs, a1_key)
    try:
        a1 = build_managed_mem0_v6_paged_manifest(
            context=a1_context,
            operation_sha256=projector.iter_a1_operation_sha256(),
            page_store=a1_store,
            uniqueness_factory=a1_store,
        )
    finally:
        a1_store.close()

    cleanup_root = cleanup_operation_stream_root(
        profile_id=projector.profile_id,
        operation_sha256=(item.operation_sha256 for item in projector.iter_operations()),
    )
    a2_context = build_context(
        profile_id=projector.profile_id,
        manifest_context_sha256=a1_context.manifest_context_sha256,
        a1_terminal_commitment_sha256=a1.authority.terminal_commitment_sha256,
        run_id_sha256=inputs.run_id_sha256,
        binding_commitment_sha256=bindings.binding_commitment_sha256,
        publishable_profile_commitment_sha256=inputs.publishable_profile_commitment_sha256,
        methodology_commitment_sha256=bindings.methodology_commitment_sha256,
        dataset_sha256=bindings.dataset_sha256,
        admission_commitment_sha256=projector.admission_commitment_sha256,
        ingestion_root_sha256=inputs.ingestion_root_sha256,
        case_manifest_sha256=inputs.case_manifest_sha256,
        infinity_target_identity_sha256=inputs.infinity_target_identity_sha256,
        space_id=inputs.space_id,
        space_slug=inputs.space_slug,
        cleanup_target_authority_sha256=inputs.cleanup_target_authority_sha256,
        qdrant_authority_sha256=inputs.qdrant_authority_sha256,
        qdrant_target_commitment_sha256=inputs.qdrant_target_commitment_sha256,
        qdrant_policy_commitment_sha256=inputs.qdrant_policy_commitment_sha256,
        graphiti_authority_sha256=inputs.graphiti_authority_sha256,
        graphiti_target_commitment_sha256=inputs.graphiti_target_commitment_sha256,
        graphiti_policy_commitment_sha256=inputs.graphiti_policy_commitment_sha256,
        cognee_policy_sha256=inputs.cognee_policy_sha256,
        namespace_policy_sha256=inputs.namespace_policy_sha256,
        cleanup_operation_stream_root_sha256=cleanup_root,
        omitted_source_identity_root_sha256=str(oracle["omitted_source_identity_root_sha256"]),
    )
    a2_store = _a2_store(inputs, a2_key)
    try:
        a2_authority, a2_receipt = build_managed_cleanup_v3_authority(
            context=a2_context,
            operations=projector.iter_operations(),
            a1_authority=a1.authority,
            store=a2_store,
        )
    finally:
        a2_store.close()
    expected_index = _open_or_create_expected_index(
        inputs=inputs,
        context=a2_context,
        authority=a2_authority,
        a2_authentication_key=a2_key,
        index_authentication_key=index_key,
    )
    expected_index.close()

    registration = await register_context_authority_and_readback(
        registration_port,
        context=a2_context,
        authority=a2_authority,
        authenticator=authenticator,
        registered_at=registered_at,
    )
    receipt = build_strict_v4_preparation_receipt(
        authenticator=authenticator,
        registration=registration,
        prepared_at=prepared_at,
        profile_id=projector.profile_id,
        dataset_sha256=bindings.dataset_sha256,
        run_id_sha256=inputs.run_id_sha256,
        binding_commitment_sha256=bindings.binding_commitment_sha256,
        methodology_commitment_sha256=bindings.methodology_commitment_sha256,
        admission_commitment_sha256=projector.admission_commitment_sha256,
        ingestion_root_sha256=inputs.ingestion_root_sha256,
        original_pair_path=(
            None
            if inputs.original_pair_path is None
            else str(Path(inputs.original_pair_path).resolve())
        ),
        original_pair_terminal_sha256=pair_terminal,
        original_pair_key_id=inputs.original_pair_key_id,
        original_pair_key_commitment_sha256=pair_key_commitment,
        a1_path=str(Path(inputs.a1_path).resolve()),
        a1_key_id=inputs.a1_key_id,
        a1_key_commitment_sha256=_key_commitment(
            a1_key, "a1", inputs.a1_key_id, inputs.run_id_sha256, inputs.a1_path
        ),
        a1_context=a1_context,
        a1_authority=a1.authority,
        a1_store_receipt=a1.store_receipt,
        a2_path=str(Path(inputs.a2_path).resolve()),
        a2_key_id=inputs.a2_key_id,
        a2_key_commitment_sha256=_key_commitment(
            a2_key, "a2", inputs.a2_key_id, inputs.run_id_sha256, inputs.a2_path
        ),
        a2_context=a2_context,
        a2_authority=a2_authority,
        a2_store_receipt=a2_receipt,
        expected_index_path=str(Path(inputs.expected_index_path).resolve()),
        expected_index_key_id=inputs.expected_index_key_id,
        expected_index_key_commitment_sha256=_key_commitment(
            index_key,
            "expected-index",
            inputs.expected_index_key_id,
            inputs.run_id_sha256,
            inputs.expected_index_path,
        ),
        expected_index_terminal_sha256=a2_authority.terminal_commitment_sha256,
        receipt_key_commitment_sha256=strict_v4_receipt_key_commitment(
            authenticator,
            artifact_context=(f"{inputs.run_id_sha256}:{registration.registration_sha256}"),
        ),
    )
    receipt_store.write(receipt)
    authenticate_strict_v4_preparation_receipt(receipt, authenticator=authenticator)
    return receipt


def _a1_store(
    inputs: StrictV4FullPreparationInputs, authentication_key: bytes
) -> SQLiteManagedMem0V6PreparationStore:
    return SQLiteManagedMem0V6PreparationStore.open_or_create(
        inputs.a1_path, authentication_key=authentication_key
    )


def _a2_store(
    inputs: StrictV4FullPreparationInputs, authentication_key: bytes
) -> SQLiteManagedCleanupV3PreparationStore:
    return SQLiteManagedCleanupV3PreparationStore.open_or_create(
        inputs.a2_path, authentication_key=authentication_key
    )


def _open_or_create_expected_index(
    *,
    inputs: StrictV4FullPreparationInputs,
    context: ManagedCleanupV3Context,
    authority: ManagedCleanupV3Authority,
    a2_authentication_key: bytes,
    index_authentication_key: bytes,
) -> SQLiteManagedCleanupV3ExpectedRowAuthority:
    index_path = Path(inputs.expected_index_path)
    return SQLiteManagedCleanupV3ExpectedRowAuthority.create_or_open_repairable_bootstrap(
        index_path,
        context=context,
        authority=authority,
        pages=iter_committed_pages(
            inputs.a2_path,
            context_sha256=context.context_sha256,
            terminal_commitment_sha256=authority.terminal_commitment_sha256,
            authentication_key=a2_authentication_key,
        ),
        authentication_key=index_authentication_key,
    )


def _verify_original_pair_binding(
    projector: ManagedV5CleanupV4OperationProjector,
    path: str,
    authentication_key: bytes,
) -> None:
    from infinity_context_server.original_pair_identity_authority import (
        SQLiteOriginalPairIdentityAuthority,
    )

    expected = projector.original_pair_authority
    if expected is None:
        raise ProjectionReceiptError("projection_receipt.preparation_pair_missing")
    observed = SQLiteOriginalPairIdentityAuthority.open(path, authentication_key=authentication_key)
    try:
        fields = (
            "profile_id",
            "dataset_sha256",
            "operation_count",
            "original_pair_slot_count",
            "omitted_source_identity_count",
            "omitted_source_identity_root_sha256",
            "omitted_original_pair_identity_root_sha256",
            "original_pair_slot_root_sha256",
            "ordered_mapping_root_sha256",
            "terminal_commitment_sha256",
        )
        if any(getattr(observed, name) != getattr(expected, name) for name in fields):
            raise ProjectionReceiptError("projection_receipt.preparation_pair_invalid")
    finally:
        observed.close()


async def recover_strict_v4_full_run(
    *,
    receipt_store: StrictV4PreparationReceiptPort,
    registration_port: ContextAuthorityRegistrationPort,
    authenticator: ProjectionReceiptAuthenticator,
    key_identity_authority: StrictV4PreparationKeyIdentityPort,
) -> StrictV4PreparationReceipt:
    """Verify every committed artifact; never invoke a projector or legacy plan."""

    receipt = receipt_store.read()
    authenticate_strict_v4_preparation_receipt(receipt, authenticator=authenticator)
    a1_key = _resolve_key(key_identity_authority, "a1", receipt.a1_key_id)
    a2_key = _resolve_key(key_identity_authority, "a2", receipt.a2_key_id)
    index_key = _resolve_key(
        key_identity_authority, "expected-index", receipt.expected_index_key_id
    )
    _verify_key_commitment(
        a1_key,
        "a1",
        receipt.a1_key_id,
        receipt.run_id_sha256,
        receipt.a1_path,
        receipt.a1_key_commitment_sha256,
    )
    _verify_key_commitment(
        a2_key,
        "a2",
        receipt.a2_key_id,
        receipt.run_id_sha256,
        receipt.a2_path,
        receipt.a2_key_commitment_sha256,
    )
    _verify_key_commitment(
        index_key,
        "expected-index",
        receipt.expected_index_key_id,
        receipt.run_id_sha256,
        receipt.expected_index_path,
        receipt.expected_index_key_commitment_sha256,
    )
    if receipt.receipt_key_commitment_sha256 != strict_v4_receipt_key_commitment(
        authenticator,
        artifact_context=f"{receipt.run_id_sha256}:{receipt.registration_sha256}",
    ):
        raise ProjectionReceiptError("projection_receipt.preparation_key_binding_invalid")
    if receipt.original_pair_path is not None:
        if receipt.original_pair_key_id is None:
            raise ProjectionReceiptError("projection_receipt.preparation_pair_key_missing")
        pair_key = _resolve_key(
            key_identity_authority, "original-pair", receipt.original_pair_key_id
        )
        if receipt.original_pair_key_commitment_sha256 is None:
            raise ProjectionReceiptError("projection_receipt.preparation_pair_key_missing")
        _verify_key_commitment(
            pair_key,
            "original-pair",
            receipt.original_pair_key_id,
            receipt.run_id_sha256,
            receipt.original_pair_path,
            receipt.original_pair_key_commitment_sha256,
        )
        from infinity_context_server.original_pair_identity_authority import (
            SQLiteOriginalPairIdentityAuthority,
        )

        pair = SQLiteOriginalPairIdentityAuthority.open(
            receipt.original_pair_path, authentication_key=pair_key
        )
        try:
            if pair.terminal_commitment_sha256 != receipt.original_pair_terminal_sha256:
                raise ProjectionReceiptError("projection_receipt.preparation_pair_invalid")
        finally:
            pair.close()
    a1 = SQLiteManagedMem0V6PreparationStore.open(receipt.a1_path, authentication_key=a1_key)
    try:
        observed_a1 = a1.begin(
            manifest_context_sha256=receipt.a1_context.manifest_context_sha256,
            expected_operation_count=receipt.a1_authority.operation_count,
        ).readback()
        if observed_a1 != receipt.a1_store_receipt:
            raise ProjectionReceiptError("projection_receipt.preparation_a1_invalid")
    finally:
        a1.close()
    a2 = SQLiteManagedCleanupV3PreparationStore.open(receipt.a2_path, authentication_key=a2_key)
    try:
        observed_a2 = a2.begin(
            context_sha256=receipt.a2_context.context_sha256,
            expected_operation_count=receipt.a2_authority.operation_count,
        ).readback()
        if observed_a2 != receipt.a2_store_receipt:
            raise ProjectionReceiptError("projection_receipt.preparation_a2_invalid")
    finally:
        a2.close()
    index = SQLiteManagedCleanupV3ExpectedRowAuthority.open(
        receipt.expected_index_path,
        context=receipt.a2_context,
        authority=receipt.a2_authority,
        authentication_key=index_key,
    )
    index.close()
    registration = await register_context_authority_and_readback(
        registration_port,
        context=receipt.a2_context,
        authority=receipt.a2_authority,
        authenticator=authenticator,
        registered_at=receipt.registered_at,
    )
    _assert_registration_matches(receipt, registration)
    return receipt


def _resolve_key(authority: StrictV4PreparationKeyIdentityPort, purpose: str, key_id: str) -> bytes:
    if not callable(getattr(authority, "resolve", None)):
        raise ProjectionReceiptError("projection_receipt.preparation_key_authority_invalid")
    value = authority.resolve(purpose=purpose, key_id=key_id)
    if type(value) is not bytes or len(value) < 32:
        raise ProjectionReceiptError("projection_receipt.preparation_key_binding_invalid")
    return value


def _key_commitment(
    key: bytes, purpose: str, key_id: str, run_id_sha256: str, path: str | Path
) -> str:
    return strict_v4_preparation_key_commitment(
        key,
        purpose=purpose,
        key_id=key_id,
        artifact_context=f"{run_id_sha256}:{Path(path)}",
    )


def _verify_key_commitment(
    key: bytes,
    purpose: str,
    key_id: str,
    run_id_sha256: str,
    path: str | Path,
    expected: str,
) -> None:
    observed = _key_commitment(key, purpose, key_id, run_id_sha256, path)
    if not hmac.compare_digest(observed, expected):
        raise ProjectionReceiptError("projection_receipt.preparation_key_binding_invalid")


def _validate_artifact_paths(inputs: StrictV4FullPreparationInputs) -> None:
    values = [inputs.a1_path, inputs.a2_path, inputs.expected_index_path]
    if inputs.original_pair_path is not None:
        values.append(inputs.original_pair_path)
    normalized: list[str] = []
    for value in values:
        path = Path(value)
        if not path.is_absolute() or ".." in path.parts or path != path.resolve(strict=False):
            raise ProjectionReceiptError("projection_receipt.preparation_path_invalid")
        normalized.append(str(path))
    if len(set(normalized)) != len(normalized):
        raise ProjectionReceiptError("projection_receipt.preparation_path_collision")


def _assert_registration_matches(receipt: object, registration: object) -> None:
    if (
        getattr(registration, "registration_sha256", None)
        != getattr(receipt, "registration_sha256", None)
        or getattr(registration, "registration_mac_sha256", None)
        != getattr(receipt, "registration_mac_sha256", None)
        or getattr(registration, "registered_at", None) != getattr(receipt, "registered_at", None)
    ):
        raise ProjectionReceiptError("projection_receipt.preparation_registration_invalid")


__all__ = (
    "StrictV4FullPreparationInputs",
    "prepare_strict_v4_full_run",
    "recover_strict_v4_full_run",
)

from __future__ import annotations

import copy
import hashlib
import inspect
import pickle
from pathlib import Path
from types import SimpleNamespace

import pytest
from infinity_context_adapters.postgres.managed_strict_v4_preparation_receipt import (
    SQLiteStrictV4PreparationReceiptStore,
)
from infinity_context_adapters.postgres.managed_strict_v4_sqlite_files import (
    StrictV4SQLiteFileError,
)
from infinity_context_core.features.projection_receipts import (
    ProjectionReceiptAuthenticator,
    ProjectionReceiptError,
)
from infinity_context_core.features.projection_receipts.strict_v4_preparation import (
    StrictV4PreparationReceipt,
)
from infinity_context_server import (
    memory_comparison_managed_v5_strict_v4_prepared_authority as prepared,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestAuthority,
)
from infinity_context_server.memory_comparison_managed_plan_builder import (
    ManagedPublicRunProjection,
)


class _Keys:
    def resolve(self, *, purpose: str, key_id: str) -> bytes:
        del purpose, key_id
        return b"artifact-key" * 4


class _Registration:
    async def register_and_readback(self, **values: object) -> object:
        del values
        raise AssertionError("the fake recovery owns registration readback")


def _nominal_material() -> tuple[object, StrictV4PreparationReceipt]:
    run_id = "strict-v4-prepared-authority-test"
    dataset = "1" * 64
    binding = "2" * 64
    methodology = "3" * 64
    admission = "4" * 64
    ingestion = "5" * 64
    cases = "6" * 64
    profile = "mem0-locomo-top50-v1"
    operation_count = 5_882

    projection = object.__new__(ManagedPublicRunProjection)
    object.__setattr__(
        projection,
        "bindings",
        SimpleNamespace(
            run_id=run_id,
            dataset_sha256=dataset,
            binding_commitment_sha256=binding,
            methodology_commitment_sha256=methodology,
        ),
    )
    object.__setattr__(projection, "case_manifest_sha256", cases)

    manifest = object.__new__(ManagedMem0V5ManifestAuthority)
    object.__setattr__(manifest, "ingestion_root_sha256", ingestion)
    object.__setattr__(manifest, "units", tuple(object() for _ in range(operation_count)))

    receipt = object.__new__(StrictV4PreparationReceipt)
    for name, value in {
        "profile_id": profile,
        "dataset_sha256": dataset,
        "run_id_sha256": hashlib.sha256(run_id.encode()).hexdigest(),
        "binding_commitment_sha256": binding,
        "methodology_commitment_sha256": methodology,
        "admission_commitment_sha256": admission,
        "ingestion_root_sha256": ingestion,
        "a2_context": SimpleNamespace(case_manifest_sha256=cases),
        "a1_authority": SimpleNamespace(operation_count=operation_count),
    }.items():
        object.__setattr__(receipt, name, value)

    return (
        SimpleNamespace(
            request={"admission_commitment_sha256": admission},
            keys=_Keys(),
            preparation={},
            profile_id=profile,
            projection=projection,
            manifest=manifest,
        ),
        receipt,
    )


def _paths(tmp_path: Path) -> dict[str, Path]:
    return {
        "request_path": tmp_path / "request.json",
        "dataset_path": tmp_path / "dataset.json",
        "receipt_path": tmp_path / "receipt.sqlite3",
        "keyring_path": tmp_path / "keyring.json",
        "receipt_key_path": tmp_path / "receipt.key",
        "registration_postgres_dsn_path": tmp_path / "registration.dsn",
    }


def _patch_inputs(
    monkeypatch: pytest.MonkeyPatch,
    *,
    material: object,
    store: SQLiteStrictV4PreparationReceiptStore,
) -> _Registration:
    registration = _Registration()
    monkeypatch.setattr(prepared, "load_strict_v4_run_material", lambda **_values: material)
    monkeypatch.setattr(prepared, "read_strict_v4_receipt_key", lambda _path: b"r" * 32)
    monkeypatch.setattr(
        prepared,
        "read_strict_v4_postgres_dsn",
        lambda _path: "postgresql://registrar-capability",
    )
    monkeypatch.setattr(
        prepared,
        "build_strict_v4_registration_port",
        lambda dsn, authenticator: registration,
    )
    monkeypatch.setattr(
        prepared,
        "open_strict_v4_preparation_receipt_store",
        lambda _path: store,
    )
    monkeypatch.setattr(
        prepared,
        "validate_strict_v4_execution_material",
        lambda candidate, receipt: "space",
    )
    return registration


@pytest.mark.anyio
async def test_open_authenticates_exact_material_and_owns_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    material, receipt = _nominal_material()
    store = SQLiteStrictV4PreparationReceiptStore.create(tmp_path / "actual-receipt.sqlite3")
    registration = _patch_inputs(monkeypatch, material=material, store=store)
    observed: dict[str, object] = {}

    async def recover(**values: object) -> StrictV4PreparationReceipt:
        observed.update(values)
        return receipt

    monkeypatch.setattr(prepared, "recover_strict_v4_full_run", recover)

    authority = await prepared.open_strict_v4_prepared_run_authority(**_paths(tmp_path))

    assert authority.receipt is receipt
    assert authority.projection is material.projection
    assert authority.manifest is material.manifest
    assert authority.receipt_store is store
    assert authority.registration_port is registration
    assert authority.key_identity_authority is material.keys
    assert type(authority.authenticator) is ProjectionReceiptAuthenticator
    assert observed == {
        "receipt_store": store,
        "registration_port": registration,
        "authenticator": authority.authenticator,
        "key_identity_authority": material.keys,
    }
    assert repr(authority) == "StrictV4PreparedRunAuthority(private_capabilities=<bound>)"
    with pytest.raises(TypeError, match="noncopyable"):
        copy.copy(authority)
    with pytest.raises(TypeError, match="nonserializable"):
        pickle.dumps(authority)

    authority.close()
    authority.close()
    with pytest.raises(prepared.StrictV4PreparedRunAuthorityError) as error:
        _ = authority.receipt
    assert error.value.code == "strict_v4_prepared_authority_closed"
    with pytest.raises(ProjectionReceiptError, match="store_closed"):
        store.read()


@pytest.mark.anyio
async def test_crosswired_public_material_closes_the_receipt_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    material, receipt = _nominal_material()
    object.__setattr__(receipt, "dataset_sha256", "0" * 64)
    store = SQLiteStrictV4PreparationReceiptStore.create(tmp_path / "actual-receipt.sqlite3")
    _patch_inputs(monkeypatch, material=material, store=store)

    async def recover(**_values: object) -> StrictV4PreparationReceipt:
        return receipt

    monkeypatch.setattr(prepared, "recover_strict_v4_full_run", recover)
    with pytest.raises(prepared.StrictV4PreparedRunAuthorityError) as error:
        await prepared.open_strict_v4_prepared_run_authority(**_paths(tmp_path))
    assert error.value.code == "strict_v4_prepared_authority_cross_wire"
    with pytest.raises(ProjectionReceiptError, match="store_closed"):
        store.read()


@pytest.mark.anyio
async def test_tampered_recovery_closes_the_receipt_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    material, _receipt = _nominal_material()
    store = SQLiteStrictV4PreparationReceiptStore.create(tmp_path / "actual-receipt.sqlite3")
    _patch_inputs(monkeypatch, material=material, store=store)

    async def recover(**_values: object) -> StrictV4PreparationReceipt:
        raise ProjectionReceiptError("projection_receipt.preparation_invalid")

    monkeypatch.setattr(prepared, "recover_strict_v4_full_run", recover)
    with pytest.raises(ProjectionReceiptError, match="preparation_invalid"):
        await prepared.open_strict_v4_prepared_run_authority(**_paths(tmp_path))
    with pytest.raises(ProjectionReceiptError, match="store_closed"):
        store.read()


@pytest.mark.anyio
async def test_missing_receipt_is_not_created(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    material, _receipt = _nominal_material()
    paths = _paths(tmp_path)
    monkeypatch.setattr(prepared, "load_strict_v4_run_material", lambda **_values: material)
    monkeypatch.setattr(prepared, "read_strict_v4_receipt_key", lambda _path: b"r" * 32)
    monkeypatch.setattr(
        prepared,
        "read_strict_v4_postgres_dsn",
        lambda _path: "postgresql://registrar-capability",
    )
    monkeypatch.setattr(
        prepared,
        "build_strict_v4_registration_port",
        lambda dsn, authenticator: _Registration(),
    )

    with pytest.raises(StrictV4SQLiteFileError, match="strict_v4_sqlite_open_failed"):
        await prepared.open_strict_v4_prepared_run_authority(**paths)
    assert not paths["receipt_path"].exists()


@pytest.mark.anyio
async def test_paths_fail_closed_before_material_or_network_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def accessed(**_values: object) -> object:
        nonlocal calls
        calls += 1
        raise AssertionError("material must not be accessed")

    monkeypatch.setattr(prepared, "load_strict_v4_run_material", accessed)
    paths = _paths(tmp_path)
    paths["dataset_path"] = paths["request_path"]
    with pytest.raises(prepared.StrictV4PreparedRunAuthorityError) as error:
        await prepared.open_strict_v4_prepared_run_authority(**paths)
    assert error.value.code == "strict_v4_prepared_path_cross_wire"
    assert calls == 0

    paths = _paths(tmp_path)
    paths["request_path"] = Path("relative-request.json")
    with pytest.raises(prepared.StrictV4PreparedRunAuthorityError) as error:
        await prepared.open_strict_v4_prepared_run_authority(**paths)
    assert error.value.code == "strict_v4_prepared_path_invalid"
    assert calls == 0


def test_public_seam_has_no_provider_dispatch_parameter_or_dependency() -> None:
    signature = inspect.signature(prepared.open_strict_v4_prepared_run_authority)
    assert tuple(signature.parameters) == (
        "request_path",
        "dataset_path",
        "receipt_path",
        "keyring_path",
        "receipt_key_path",
        "registration_postgres_dsn_path",
    )
    source = inspect.getsource(prepared)
    for forbidden in ("OPENAI_API_KEY", "MEM0_API_KEY", "provider_api_key", "httpx"):
        assert forbidden not in source

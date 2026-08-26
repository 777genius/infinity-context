"""Open one authenticated strict-v4 run from explicit operator-owned material."""

from __future__ import annotations

import hashlib
import threading
from pathlib import Path
from typing import final

from infinity_context_adapters.postgres.managed_strict_v4_preparation_receipt import (
    SQLiteStrictV4PreparationReceiptStore,
)
from infinity_context_core.features.projection_receipts import (
    ContextAuthorityRegistrationPort,
    ProjectionReceiptAuthenticator,
)
from infinity_context_core.features.projection_receipts.strict_v4_preparation import (
    StrictV4PreparationKeyIdentityPort,
    StrictV4PreparationReceipt,
)

from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestAuthority,
)
from infinity_context_server.memory_comparison_managed_plan_builder import (
    ManagedPublicRunProjection,
)
from infinity_context_server.memory_comparison_managed_v5_strict_v4_cli import (
    StrictV4RunMaterial,
    build_strict_v4_registration_port,
    canonical_strict_v4_path,
    load_strict_v4_run_material,
    open_strict_v4_preparation_receipt_store,
    read_strict_v4_postgres_dsn,
    read_strict_v4_receipt_key,
    validate_strict_v4_execution_material,
)
from infinity_context_server.memory_comparison_managed_v5_strict_v4_preparation import (
    recover_strict_v4_full_run,
)


class StrictV4PreparedRunAuthorityError(RuntimeError):
    """Stable failure from the prepared-run composition boundary."""

    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@final
class StrictV4PreparedRunAuthority:
    """Own the open receipt store and its authenticated public run authority."""

    __slots__ = (
        "_authenticator",
        "_closed",
        "_key_identity_authority",
        "_lock",
        "_manifest",
        "_projection",
        "_receipt",
        "_receipt_store",
        "_registration_port",
    )

    def __init__(
        self,
        *,
        receipt: StrictV4PreparationReceipt,
        projection: ManagedPublicRunProjection,
        manifest: ManagedMem0V5ManifestAuthority,
        receipt_store: SQLiteStrictV4PreparationReceiptStore,
        registration_port: ContextAuthorityRegistrationPort,
        authenticator: ProjectionReceiptAuthenticator,
        key_identity_authority: StrictV4PreparationKeyIdentityPort,
    ) -> None:
        if (
            type(receipt) is not StrictV4PreparationReceipt
            or type(projection) is not ManagedPublicRunProjection
            or type(manifest) is not ManagedMem0V5ManifestAuthority
            or type(receipt_store) is not SQLiteStrictV4PreparationReceiptStore
            or not callable(getattr(registration_port, "register_and_readback", None))
            or type(authenticator) is not ProjectionReceiptAuthenticator
            or not callable(getattr(key_identity_authority, "resolve", None))
        ):
            _fail("strict_v4_prepared_authority_invalid")
        self._receipt = receipt
        self._projection = projection
        self._manifest = manifest
        self._receipt_store = receipt_store
        self._registration_port = registration_port
        self._authenticator = authenticator
        self._key_identity_authority = key_identity_authority
        self._closed = False
        self._lock = threading.RLock()

    @property
    def receipt(self) -> StrictV4PreparationReceipt:
        self._require_open()
        return self._receipt

    @property
    def projection(self) -> ManagedPublicRunProjection:
        self._require_open()
        return self._projection

    @property
    def manifest(self) -> ManagedMem0V5ManifestAuthority:
        self._require_open()
        return self._manifest

    @property
    def receipt_store(self) -> SQLiteStrictV4PreparationReceiptStore:
        self._require_open()
        return self._receipt_store

    @property
    def registration_port(self) -> ContextAuthorityRegistrationPort:
        self._require_open()
        return self._registration_port

    @property
    def authenticator(self) -> ProjectionReceiptAuthenticator:
        self._require_open()
        return self._authenticator

    @property
    def key_identity_authority(self) -> StrictV4PreparationKeyIdentityPort:
        self._require_open()
        return self._key_identity_authority

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._receipt_store.close()

    def _require_open(self) -> None:
        with self._lock:
            if self._closed:
                _fail("strict_v4_prepared_authority_closed")

    def __enter__(self) -> StrictV4PreparedRunAuthority:
        self._require_open()
        return self

    def __exit__(self, *_error: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return "StrictV4PreparedRunAuthority(private_capabilities=<bound>)"

    def __copy__(self) -> object:
        raise TypeError("strict-v4 prepared authorities are noncopyable")

    def __deepcopy__(self, _memo: object) -> object:
        raise TypeError("strict-v4 prepared authorities are noncopyable")

    def __reduce_ex__(self, _protocol: int) -> object:
        raise TypeError("strict-v4 prepared authorities are nonserializable")


async def open_strict_v4_prepared_run_authority(
    *,
    request_path: Path,
    dataset_path: Path,
    receipt_path: Path,
    keyring_path: Path,
    receipt_key_path: Path,
    registration_postgres_dsn_path: Path,
) -> StrictV4PreparedRunAuthority:
    """Rebuild public inputs and authenticate every prepared artifact.

    The seam performs only local file reads and canonical Postgres registration
    readback.  It neither constructs nor dispatches a model-provider client.
    """

    paths = _canonical_distinct_paths(
        request_path=request_path,
        dataset_path=dataset_path,
        receipt_path=receipt_path,
        keyring_path=keyring_path,
        receipt_key_path=receipt_key_path,
        registration_postgres_dsn_path=registration_postgres_dsn_path,
    )
    material = load_strict_v4_run_material(
        request_path=paths[0],
        dataset_path=paths[1],
        keyring_path=paths[3],
    )
    authenticator = ProjectionReceiptAuthenticator(read_strict_v4_receipt_key(paths[4]))
    registration_port = build_strict_v4_registration_port(
        read_strict_v4_postgres_dsn(paths[5]),
        authenticator,
    )
    receipt_store = open_strict_v4_preparation_receipt_store(paths[2])
    try:
        receipt = await recover_strict_v4_full_run(
            receipt_store=receipt_store,
            registration_port=registration_port,
            authenticator=authenticator,
            key_identity_authority=material.keys,
        )
        _require_exact_material_binding(material, receipt)
        return StrictV4PreparedRunAuthority(
            receipt=receipt,
            projection=material.projection,
            manifest=material.manifest,
            receipt_store=receipt_store,
            registration_port=registration_port,
            authenticator=authenticator,
            key_identity_authority=material.keys,
        )
    except BaseException:
        receipt_store.close()
        raise


def _canonical_distinct_paths(
    *,
    request_path: Path,
    dataset_path: Path,
    receipt_path: Path,
    keyring_path: Path,
    receipt_key_path: Path,
    registration_postgres_dsn_path: Path,
) -> tuple[Path, Path, Path, Path, Path, Path]:
    raw = (
        request_path,
        dataset_path,
        receipt_path,
        keyring_path,
        receipt_key_path,
        registration_postgres_dsn_path,
    )
    if any(not isinstance(path, Path) for path in raw):
        _fail("strict_v4_prepared_path_invalid")
    try:
        paths = tuple(canonical_strict_v4_path(path) for path in raw)
    except (OSError, ValueError):
        _fail("strict_v4_prepared_path_invalid")
    if len(set(paths)) != len(paths):
        _fail("strict_v4_prepared_path_cross_wire")
    return (paths[0], paths[1], paths[2], paths[3], paths[4], paths[5])


def _require_exact_material_binding(
    material: StrictV4RunMaterial,
    receipt: StrictV4PreparationReceipt,
) -> None:
    try:
        validate_strict_v4_execution_material(material, receipt)
        bindings = material.projection.bindings
        admission = material.request.get("admission_commitment_sha256")
        if (
            type(admission) is not str
            or receipt.profile_id != material.profile_id
            or receipt.dataset_sha256 != bindings.dataset_sha256
            or receipt.run_id_sha256 != hashlib.sha256(bindings.run_id.encode("utf-8")).hexdigest()
            or receipt.binding_commitment_sha256 != bindings.binding_commitment_sha256
            or receipt.methodology_commitment_sha256 != bindings.methodology_commitment_sha256
            or receipt.admission_commitment_sha256 != admission
            or receipt.ingestion_root_sha256 != material.manifest.ingestion_root_sha256
            or receipt.a2_context.case_manifest_sha256 != material.projection.case_manifest_sha256
            or receipt.a1_authority.operation_count != material.manifest.operation_count
        ):
            _fail("strict_v4_prepared_authority_cross_wire")
    except StrictV4PreparedRunAuthorityError:
        raise
    except Exception:
        _fail("strict_v4_prepared_authority_cross_wire")


def _fail(code: str) -> None:
    raise StrictV4PreparedRunAuthorityError(code) from None


__all__ = (
    "StrictV4PreparedRunAuthority",
    "StrictV4PreparedRunAuthorityError",
    "open_strict_v4_prepared_run_authority",
)

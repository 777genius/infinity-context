"""Provider-free production CLI for strict-v4 preparation and canonical execution."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import stat
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from infinity_context_adapters.postgres.managed_cleanup_v4_context_registration import (
    AsyncPostgresCleanupV4ContextAuthorityRegistry,
)
from infinity_context_adapters.postgres.managed_strict_v4_preparation_receipt import (
    SQLiteStrictV4PreparationReceiptStore,
)
from infinity_context_adapters.postgres.strict_v4_writer_authority import (
    AsyncPostgresStrictV4WriterAuthority,
)
from infinity_context_core.features.projection_receipts import ProjectionReceiptAuthenticator
from infinity_context_core.features.projection_receipts.strict_v4_preparation import (
    StrictV4PreparationKeyIdentityPort,
    StrictV4PreparationReceipt,
)
from infinity_context_core.ports.managed_cleanup_v3_contracts import (
    LOCOMO_PROFILE,
    LONGMEMEVAL_PROFILE,
    commitment,
)

from infinity_context_server.memory_comparison_backend_target import (
    FullComparisonBackendTarget,
)
from infinity_context_server.memory_comparison_full_profiles import (
    resolve_full_comparison_profile,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestAuthority,
    ManagedMem0V5ManifestProjector,
)
from infinity_context_server.memory_comparison_managed_plan_builder import (
    ManagedPublicRunProjection,
    build_managed_public_run_projection,
)
from infinity_context_server.memory_comparison_managed_v5_cleanup_v4_projector import (
    ManagedV5CleanupV4OperationProjector,
)
from infinity_context_server.memory_comparison_managed_v5_strict_v4_document_execution import (
    RecoveredStrictV4DocumentAuthority,
    recover_strict_v4_document_authority,
)
from infinity_context_server.memory_comparison_managed_v5_strict_v4_document_ingest import (
    StrictV4DocumentIngestRuntime,
)
from infinity_context_server.memory_comparison_managed_v5_strict_v4_fact_execution import (
    RecoveredStrictV4FactAuthority,
    recover_strict_v4_fact_authority,
)
from infinity_context_server.memory_comparison_managed_v5_strict_v4_fact_ingest import (
    StrictV4FactIngestRuntime,
)
from infinity_context_server.memory_comparison_managed_v5_strict_v4_preparation import (
    StrictV4FullPreparationInputs,
    prepare_strict_v4_full_run,
    recover_strict_v4_full_run,
)
from infinity_context_server.memory_comparison_managed_v5_strict_v4_writer_authority import (
    recover_and_seal_strict_v4_writer_authority,
)
from infinity_context_server.original_pair_identity_authority import (
    SQLiteOriginalPairIdentityAuthority,
)

_ORIGINAL_PAIR_ACTION_SCHEMA = "memory-comparison-strict-v4-original-pair-action.v1"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="infinity-context-managed-strict-v4-prepare",
        description=(
            "Prepare or recover authenticated strict-v4 artifacts. "
            "This command never constructs or calls a paid/live provider."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)
    original_pair = commands.add_parser(
        "create-original-pair-authority",
        help="Create or authenticate/reopen the official LongMemEval pair authority.",
        description=(
            "Create the authenticated original-pair authority directly from the bounded "
            "official LongMemEval bytes. Exact replays reopen it without provider calls."
        ),
    )
    original_pair.add_argument("--request", required=True, type=Path)
    original_pair.add_argument("--dataset", required=True, type=Path)
    original_pair.add_argument("--keyring", required=True, type=Path)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--request", required=True, type=Path)
    prepare.add_argument("--dataset", required=True, type=Path)
    _common(prepare)
    recover = commands.add_parser("recover")
    _common(recover)
    seal = commands.add_parser("seal")
    _common(seal)
    seal.add_argument("--seal-postgres-dsn-file", required=True, type=Path)
    seal.add_argument("--sealed-at", required=True)
    execute_facts = commands.add_parser("execute-facts")
    execute_facts.add_argument("--request", required=True, type=Path)
    execute_facts.add_argument("--dataset", required=True, type=Path)
    _common(execute_facts)
    execute_facts.add_argument("--fact-writer-postgres-dsn-file", required=True, type=Path)
    execute_documents = commands.add_parser(
        "execute-documents",
        help="Ingest the sealed official LongMemEval corpus through canonical handlers.",
        description=(
            "Recover the exact sealed LongMemEval authority and idempotently ingest its "
            "124,344 official documents with a separate strict-v4 document-writer capability."
        ),
    )
    execute_documents.add_argument("--request", required=True, type=Path)
    execute_documents.add_argument("--dataset", required=True, type=Path)
    _common(execute_documents)
    execute_documents.add_argument("--document-writer-postgres-dsn-file", required=True, type=Path)
    return parser


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--postgres-dsn-file", required=True, type=Path)
    parser.add_argument("--receipt-key-file", required=True, type=Path)
    parser.add_argument("--keyring", required=True, type=Path)


async def _connect_factory(dsn: str) -> Any:
    import asyncpg

    return await asyncpg.connect(dsn)


def _registry(
    dsn: str, authenticator: ProjectionReceiptAuthenticator
) -> AsyncPostgresCleanupV4ContextAuthorityRegistry:
    async def connect() -> Any:
        return await _connect_factory(dsn)

    return AsyncPostgresCleanupV4ContextAuthorityRegistry(
        connect=connect,
        authenticator=authenticator,
    )


def _secret(path: Path, *, min_bytes: int = 32, max_bytes: int = 1 << 20) -> bytes:
    path = _absolute(path)
    _private_parent(path.parent)
    before = path.lstat()
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    value = bytearray()
    try:
        actual = os.fstat(fd)
        if (
            stat.S_ISLNK(before.st_mode)
            or not stat.S_ISREG(actual.st_mode)
            or actual.st_uid != os.getuid()
            or actual.st_nlink != 1
            or stat.S_IMODE(actual.st_mode) != 0o600
            or (before.st_dev, before.st_ino) != (actual.st_dev, actual.st_ino)
        ):
            raise ValueError("strict-v4 secret file is unsafe")
        if actual.st_size < min_bytes or actual.st_size > max_bytes:
            raise ValueError("strict-v4 secret file size is invalid")
        while chunk := os.read(fd, 4096):
            value.extend(chunk)
            if len(value) > max_bytes:
                raise ValueError("strict-v4 secret file size is invalid")
        if len(value) != actual.st_size:
            raise ValueError("strict-v4 secret file changed while reading")
        final = os.fstat(fd)
        after = path.lstat()
        if (after.st_dev, after.st_ino) != (actual.st_dev, actual.st_ino) or (
            final.st_size,
            final.st_mtime_ns,
            final.st_ctime_ns,
        ) != (actual.st_size, actual.st_mtime_ns, actual.st_ctime_ns):
            raise ValueError("strict-v4 secret file was replaced")
        while value.endswith((b"\r", b"\n")):
            value.pop()
        if len(value) < min_bytes:
            raise ValueError("strict-v4 secret file size is invalid")
        return bytes(value)
    finally:
        for index in range(len(value)):
            value[index] = 0
        os.close(fd)


def _private_parent(path: Path) -> None:
    value = path.lstat()
    if (
        not stat.S_ISDIR(value.st_mode)
        or stat.S_ISLNK(value.st_mode)
        or value.st_uid != os.getuid()
        or stat.S_IMODE(value.st_mode) & 0o077
    ):
        raise ValueError("strict-v4 secret parent is unsafe")


def _postgres_dsn(path: Path) -> str:
    try:
        value = _secret(path, min_bytes=1, max_bytes=8192).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("strict-v4 PostgreSQL capability is invalid") from exc
    if not value or "\x00" in value or "\r" in value or "\n" in value:
        raise ValueError("strict-v4 PostgreSQL capability is invalid")
    return value


def _bound_input(path: Path, *, max_bytes: int) -> bytes:
    path = _absolute(path)
    before = path.lstat()
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    value = bytearray()
    try:
        actual = os.fstat(fd)
        if (
            not stat.S_ISREG(actual.st_mode)
            or actual.st_uid != os.getuid()
            or actual.st_nlink != 1
            or (before.st_dev, before.st_ino) != (actual.st_dev, actual.st_ino)
            or actual.st_size < 1
            or actual.st_size > max_bytes
        ):
            raise ValueError("strict-v4 input file is unsafe")
        while chunk := os.read(fd, 1 << 20):
            value.extend(chunk)
            if len(value) > max_bytes:
                raise ValueError("strict-v4 input file is too large")
        after = path.lstat()
        final = os.fstat(fd)
        if (
            len(value) != actual.st_size
            or (after.st_dev, after.st_ino) != (actual.st_dev, actual.st_ino)
            or (final.st_dev, final.st_ino, final.st_size)
            != (actual.st_dev, actual.st_ino, actual.st_size)
            or (final.st_mtime_ns, final.st_ctime_ns) != (actual.st_mtime_ns, actual.st_ctime_ns)
        ):
            raise ValueError("strict-v4 input file changed while reading")
        return bytes(value)
    finally:
        for index in range(len(value)):
            value[index] = 0
        os.close(fd)


def _strict_json(raw: str | bytes) -> dict[str, Any]:
    def object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("strict-v4 JSON contains a duplicate key")
            value[key] = item
        return value

    def reject_constant(token: str) -> object:
        raise ValueError(f"strict-v4 JSON constant {token} is invalid")

    value = json.loads(
        raw,
        object_pairs_hook=object_pairs,
        parse_constant=reject_constant,
    )
    if type(value) is not dict:
        raise ValueError("strict-v4 JSON must be one object")
    return value


def _request(path: Path) -> dict[str, Any]:
    return _strict_json(_bound_input(path, max_bytes=1 << 20))


class _FileKeyIdentityAuthority(StrictV4PreparationKeyIdentityPort):
    """Resolve purpose-bound key IDs from a separate operator-owned keyring."""

    def __init__(self, path: Path) -> None:
        self._path = _absolute(path)
        self._bindings = _strict_json(_secret(self._path, min_bytes=2, max_bytes=1 << 20))

    def resolve(self, *, purpose: str, key_id: str) -> bytes:
        binding = self._bindings.get(key_id)
        if type(binding) is not dict or binding.get("purpose") != purpose:
            raise ValueError("strict-v4 key identity is not authorized for this purpose")
        path = binding.get("key_file")
        if type(path) is not str:
            raise ValueError("strict-v4 key identity has no key file")
        return _secret(_absolute(Path(path)))


def _absolute(path: Path) -> Path:
    if not path.is_absolute() or ".." in path.parts or path != path.resolve(strict=False):
        raise ValueError("strict-v4 path must be canonical and absolute")
    return path


def _targets(raw: object) -> tuple[FullComparisonBackendTarget, ...]:
    if type(raw) is not list or any(not isinstance(item, Mapping) for item in raw):
        raise ValueError("strict-v4 backend_targets must be a JSON array")
    return tuple(
        FullComparisonBackendTarget(
            backend_role=_text(item, "backend_role"),
            target_identity_sha256=_text(item, "target_identity_sha256"),
        )
        for item in raw
    )


def _text(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    if type(item) is not str:
        raise ValueError(f"strict-v4 request field {key} is invalid")
    return item


def _receipt_store(path: Path) -> SQLiteStrictV4PreparationReceiptStore:
    return SQLiteStrictV4PreparationReceiptStore.open_or_create(_absolute(path))


@dataclass(frozen=True, slots=True)
class _ProjectorMaterial:
    request: dict[str, Any]
    keys: _FileKeyIdentityAuthority
    preparation: dict[str, Any]
    projector: ManagedV5CleanupV4OperationProjector
    pair: SQLiteOriginalPairIdentityAuthority | None

    def close(self) -> None:
        if self.pair is not None:
            self.pair.close()


@dataclass(frozen=True, slots=True)
class _RunMaterial:
    request: dict[str, Any]
    keys: _FileKeyIdentityAuthority
    preparation: dict[str, Any]
    profile_id: str
    projection: ManagedPublicRunProjection
    manifest: ManagedMem0V5ManifestAuthority
    dataset_bytes: bytes


def _run_material(args: argparse.Namespace) -> _RunMaterial:
    request = _request(args.request)
    profile_id = _text(request, "profile_id")
    profile = resolve_full_comparison_profile(profile_id)
    if profile is None:
        raise ValueError("strict-v4 profile is invalid")
    dataset = _bound_input(args.dataset, max_bytes=512 << 20)
    projection = build_managed_public_run_projection(
        run_id=_text(request, "projection_run_id"),
        run_nonce_commitment_sha256=_text(request, "run_nonce_commitment_sha256"),
        runtime_probe_nonce_sha256=_text(request, "runtime_probe_nonce_sha256"),
        profile=profile,
        dataset_bytes=dataset,
        backend_targets=_targets(request.get("backend_targets")),
        scope="full",
    )
    manifest = ManagedMem0V5ManifestProjector().project(
        projection.cases,
        current_date=_text(request, "current_date"),
    )
    keys = _FileKeyIdentityAuthority(args.keyring)
    public_inputs = request.get("preparation")
    if type(public_inputs) is not dict:
        raise ValueError("strict-v4 preparation binding is invalid")
    if public_inputs.get("case_manifest_sha256") != projection.case_manifest_sha256:
        raise ValueError("strict-v4 case manifest binding is invalid")
    return _RunMaterial(
        request=request,
        keys=keys,
        preparation=public_inputs,
        profile_id=profile_id,
        projection=projection,
        manifest=manifest,
        dataset_bytes=dataset,
    )


def _pair_binding(material: _RunMaterial) -> tuple[Path, str, bytes]:
    pair_path = material.preparation.get("original_pair_path")
    pair_key_id = material.preparation.get("original_pair_key_id")
    if type(pair_path) is not str or type(pair_key_id) is not str:
        raise ValueError("strict-v4 original pair authority is required")
    return (
        _absolute(Path(pair_path)),
        pair_key_id,
        material.keys.resolve(purpose="original-pair", key_id=pair_key_id),
    )


def _projector_material(args: argparse.Namespace) -> _ProjectorMaterial:
    material = _run_material(args)
    pair = None
    if material.profile_id == LONGMEMEVAL_PROFILE:
        pair_path, _pair_key_id, pair_key = _pair_binding(material)
        pair = SQLiteOriginalPairIdentityAuthority.open(pair_path, authentication_key=pair_key)
    try:
        projector = ManagedV5CleanupV4OperationProjector(
            projection=material.projection,
            manifest_authority=material.manifest,
            admission_commitment_sha256=_text(material.request, "admission_commitment_sha256"),
            profile_id=material.profile_id,
            original_pair_authority=pair,
        )
        return _ProjectorMaterial(
            request=material.request,
            keys=material.keys,
            preparation=material.preparation,
            projector=projector,
            pair=pair,
        )
    except BaseException:
        if pair is not None:
            pair.close()
        raise


async def _create_original_pair_authority(args: argparse.Namespace) -> dict[str, object]:
    material = _run_material(args)
    if material.profile_id != LONGMEMEVAL_PROFILE:
        raise ValueError("strict-v4 original pair profile is invalid")
    pair_path, pair_key_id, pair_key = _pair_binding(material)
    pair = SQLiteOriginalPairIdentityAuthority.create_or_open(
        pair_path,
        dataset_bytes=material.dataset_bytes,
        authentication_key=pair_key,
    )
    try:
        # Constructing the projector proves the official dataset, profile, manifest,
        # and pair authority are one admissible production composition.
        ManagedV5CleanupV4OperationProjector(
            projection=material.projection,
            manifest_authority=material.manifest,
            admission_commitment_sha256=_text(material.request, "admission_commitment_sha256"),
            profile_id=material.profile_id,
            original_pair_authority=pair,
        )
        body: dict[str, object] = {
            "schema_version": _ORIGINAL_PAIR_ACTION_SCHEMA,
            "profile_id": pair.profile_id,
            "dataset_sha256": pair.dataset_sha256,
            "case_manifest_sha256": material.projection.case_manifest_sha256,
            "original_pair_path": str(pair_path),
            "original_pair_key_id": pair_key_id,
            "original_pair_terminal_sha256": pair.terminal_commitment_sha256,
            "operation_count": pair.operation_count,
            "original_pair_slot_count": pair.original_pair_slot_count,
            "provider_calls": 0,
        }
        binding = commitment("strict-v4-original-pair-action/v1", body)
        return {
            **body,
            "binding_commitment_sha256": binding,
            "binding_mac_sha256": ProjectionReceiptAuthenticator(pair_key).sign(
                "strict-v4-original-pair-action", binding
            ),
        }
    finally:
        pair.close()


async def _prepare(args: argparse.Namespace) -> dict[str, object]:
    material = _projector_material(args)
    try:
        inputs = StrictV4FullPreparationInputs(
            **material.preparation,
        )
        authenticator = ProjectionReceiptAuthenticator(_secret(args.receipt_key_file))
        store = _receipt_store(args.receipt)
        try:
            registered_at = datetime.fromisoformat(_text(material.request, "registered_at"))
            prepared_at = datetime.fromisoformat(_text(material.request, "prepared_at"))
            receipt = await prepare_strict_v4_full_run(
                projector=material.projector,
                inputs=inputs,
                registration_port=_registry(_postgres_dsn(args.postgres_dsn_file), authenticator),
                receipt_store=store,
                key_identity_authority=material.keys,
                authenticator=authenticator,
                registered_at=registered_at,
                prepared_at=prepared_at,
            )
            return receipt.payload()
        finally:
            store.close()
    finally:
        material.close()


async def _recover(args: argparse.Namespace) -> dict[str, object]:
    authenticator = ProjectionReceiptAuthenticator(_secret(args.receipt_key_file))
    keys = _FileKeyIdentityAuthority(args.keyring)
    store = SQLiteStrictV4PreparationReceiptStore.open(_absolute(args.receipt))
    try:
        receipt = await recover_strict_v4_full_run(
            receipt_store=store,
            registration_port=_registry(_postgres_dsn(args.postgres_dsn_file), authenticator),
            authenticator=authenticator,
            key_identity_authority=keys,
        )
        return receipt.payload()
    finally:
        store.close()


async def _seal(args: argparse.Namespace) -> dict[str, object]:
    authenticator = ProjectionReceiptAuthenticator(_secret(args.receipt_key_file))
    keys = _FileKeyIdentityAuthority(args.keyring)
    registration_dsn = _postgres_dsn(args.postgres_dsn_file)
    seal_dsn = _postgres_dsn(args.seal_postgres_dsn_file)
    store = SQLiteStrictV4PreparationReceiptStore.open(_absolute(args.receipt))

    async def connect() -> Any:
        return await _connect_factory(seal_dsn)

    try:
        authority = await recover_and_seal_strict_v4_writer_authority(
            receipt_store=store,
            registration_port=_registry(registration_dsn, authenticator),
            writer_authority_port=AsyncPostgresStrictV4WriterAuthority(
                connect=connect,
                authenticator=authenticator,
            ),
            authenticator=authenticator,
            key_identity_authority=keys,
            sealed_at=datetime.fromisoformat(args.sealed_at),
        )
        return authority.payload()
    finally:
        store.close()


def _validate_execution_material(
    material: _ProjectorMaterial,
    receipt: StrictV4PreparationReceipt,
) -> str:
    inputs = StrictV4FullPreparationInputs(**material.preparation)
    context = receipt.a2_context
    if (
        inputs.run_id_sha256 != receipt.run_id_sha256
        or inputs.publishable_profile_commitment_sha256
        != context.publishable_profile_commitment_sha256
        or inputs.ingestion_root_sha256 != receipt.ingestion_root_sha256
        or inputs.case_manifest_sha256 != context.case_manifest_sha256
        or inputs.infinity_target_identity_sha256 != context.infinity_target_identity_sha256
        or inputs.space_id != context.space_id
        or inputs.space_slug != context.space_slug
        or inputs.cleanup_target_authority_sha256 != context.cleanup_target_authority_sha256
        or inputs.qdrant_authority_sha256 != context.qdrant_authority_sha256
        or inputs.qdrant_target_commitment_sha256 != context.qdrant_target_commitment_sha256
        or inputs.qdrant_policy_commitment_sha256 != context.qdrant_policy_commitment_sha256
        or inputs.graphiti_authority_sha256 != context.graphiti_authority_sha256
        or inputs.graphiti_target_commitment_sha256 != context.graphiti_target_commitment_sha256
        or inputs.graphiti_policy_commitment_sha256 != context.graphiti_policy_commitment_sha256
        or inputs.cognee_policy_sha256 != context.cognee_policy_sha256
        or inputs.namespace_policy_sha256 != context.namespace_policy_sha256
        or inputs.original_pair_path != receipt.original_pair_path
        or inputs.original_pair_key_id != receipt.original_pair_key_id
        or inputs.a1_path != receipt.a1_path
        or inputs.a1_key_id != receipt.a1_key_id
        or inputs.a2_path != receipt.a2_path
        or inputs.a2_key_id != receipt.a2_key_id
        or inputs.expected_index_path != receipt.expected_index_path
        or inputs.expected_index_key_id != receipt.expected_index_key_id
    ):
        raise ValueError("strict-v4 execution binding is invalid")
    return inputs.space_slug


async def _execute_facts(args: argparse.Namespace) -> dict[str, object]:
    material = _projector_material(args)
    if material.projector.profile_id != LOCOMO_PROFILE:
        material.close()
        raise ValueError("strict-v4 fact execution profile is invalid")
    authenticator = ProjectionReceiptAuthenticator(_secret(args.receipt_key_file))
    store = SQLiteStrictV4PreparationReceiptStore.open(_absolute(args.receipt))
    authority: RecoveredStrictV4FactAuthority | None = None
    runtime: StrictV4FactIngestRuntime | None = None
    try:
        authority = await recover_strict_v4_fact_authority(
            receipt_store=store,
            registration_port=_registry(_postgres_dsn(args.postgres_dsn_file), authenticator),
            authenticator=authenticator,
            key_identity_authority=material.keys,
            expected_projector=material.projector,
        )
        space_slug = _validate_execution_material(material, authority.receipt)
        runtime = StrictV4FactIngestRuntime(
            database_url=_postgres_dsn(args.fact_writer_postgres_dsn_file),
            authority=authority,
        )
        receipt = await runtime.execute(
            projector=material.projector,
            space_slug=space_slug,
            preparation_receipt=authority.receipt,
            authenticator=authenticator,
        )
        return receipt.payload()
    finally:
        if runtime is not None:
            await runtime.close()
        if authority is not None:
            authority.close()
        store.close()
        material.close()


async def _execute_documents(args: argparse.Namespace) -> dict[str, object]:
    material = _projector_material(args)
    if material.projector.profile_id != LONGMEMEVAL_PROFILE:
        material.close()
        raise ValueError("strict-v4 document execution profile is invalid")
    store: SQLiteStrictV4PreparationReceiptStore | None = None
    authority: RecoveredStrictV4DocumentAuthority | None = None
    runtime: StrictV4DocumentIngestRuntime | None = None
    try:
        authenticator = ProjectionReceiptAuthenticator(_secret(args.receipt_key_file))
        store = SQLiteStrictV4PreparationReceiptStore.open(_absolute(args.receipt))
        authority = await recover_strict_v4_document_authority(
            receipt_store=store,
            registration_port=_registry(_postgres_dsn(args.postgres_dsn_file), authenticator),
            authenticator=authenticator,
            key_identity_authority=material.keys,
            expected_projector=material.projector,
        )
        space_slug = _validate_execution_material(material, authority.receipt)
        runtime = StrictV4DocumentIngestRuntime(
            database_url=_postgres_dsn(args.document_writer_postgres_dsn_file),
            authority=authority,
        )
        receipt = await runtime.execute(
            projector=material.projector,
            space_slug=space_slug,
            preparation_receipt=authority.receipt,
            authenticator=authenticator,
        )
        return receipt.payload()
    finally:
        if runtime is not None:
            await runtime.close()
        if authority is not None:
            authority.close()
        if store is not None:
            store.close()
        material.close()


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        action = {
            "create-original-pair-authority": _create_original_pair_authority,
            "prepare": _prepare,
            "recover": _recover,
            "seal": _seal,
            "execute-facts": _execute_facts,
            "execute-documents": _execute_documents,
        }[args.command]
        payload = asyncio.run(action(args))
    except Exception:  # CLI boundary never echoes paths, DSNs, credentials, or provider text.
        print("strict-v4 preparation failed", file=sys.stderr)
        return 2
    print(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True))
    return 0


__all__ = ("main",)

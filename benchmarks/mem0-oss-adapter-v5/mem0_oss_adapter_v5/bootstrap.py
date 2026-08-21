"""Environment-owned production bootstrap for the v5 adapter."""

from __future__ import annotations

import hashlib
import hmac
import os
import stat
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from .app import create_app
from .composition import V5AdapterService
from .mem0_storage import Mem0StorageAdapter, PinnedMem0Backend
from .runtime_attestation import V5RuntimeAttestationAuthority, V5RuntimeAuthorityProjection
from .sealed_manifest import SealedInputManifest
from .source_authority import VerifiedSourceAuthority, verify_source_authority
from .state_sqlite import SqliteOperationState
from .subscription_runtime import (
    SUBSCRIPTION_RUNTIME_TRANSPORT_ORIGIN_SHA256,
    EstablishedReceiptV2Authority,
    SubscriptionRuntimeClient,
)

_PHASE_C_RUNTIME_BINDING_COMMITMENT_SHA256 = (
    "9636a031655ad158b5864217ca400ee6d6d294fdd799757296f38f7c926786fa"
)


@dataclass(frozen=True, slots=True)
class _ContainerAuthorityBinding:
    infinity_source_root: Path
    runtime_root: Path


@dataclass(frozen=True, slots=True)
class _ReceiptAuthorityBundle:
    authority: EstablishedReceiptV2Authority
    binding_commitment_sha256: str
    runtime_source_sha256: str
    route_binding_sha256: str


def build_app_from_environment():
    manifest = SealedInputManifest(Path(_required_environment("MEM0_V5_INPUT_MANIFEST_FILE")))
    state_path = Path(_required_environment("MEM0_V5_STATE_DB_FILE"))
    state_secret = _read_secret_file("MEM0_V5_STATE_HMAC_FILE")
    result_hmac_secret = _read_secret_file("MEM0_V5_RESULT_HMAC_FILE")
    state_key = state_secret.encode()
    result_hmac_key = result_hmac_secret.encode()
    if hmac.compare_digest(state_key, result_hmac_key):
        raise ValueError("adapter_configuration_invalid")
    ingress = _read_secret_file("MEM0_V5_INGRESS_BEARER_FILE")
    attestation_secret = _read_secret_file("MEM0_V5_RUNTIME_ATTESTATION_SECRET_FILE")
    runtime_bearer = _read_secret_file("MEM0_V5_RUNTIME_BEARER_FILE")
    receipt_secret = _read_secret_file("MEM0_V5_RECEIPT_SECRET_FILE")
    transport_origin = _read_secret_file("MEM0_V5_RUNTIME_TRANSPORT_ORIGIN_FILE")
    account_binding = _read_secret_file("MEM0_V5_ACCOUNT_BINDING_HMAC_FILE")
    base_instructions = _read_secret_file("MEM0_V5_BASE_INSTRUCTIONS_SHA256_FILE")
    phase_c_authority_root = Path(_required_environment("MEM0_V5_PHASE_C_AUTHORITY_DIR"))
    runtime_authority_root = Path(_required_environment("MEM0_V5_RUNTIME_AUTHORITY_DIR"))
    runtime_repo = Path(_required_environment("MEM0_V5_RUNTIME_REPO"))
    source_authority = verify_source_authority(
        manifest_path=Path(_required_environment("MEM0_V5_SOURCE_AUTHORITY_MANIFEST_FILE")),
        expected_manifest_sha256=_read_pinned_digest_file(
            "MEM0_V5_SOURCE_AUTHORITY_MANIFEST_SHA256_FILE"
        ),
        installed_root=Path(__file__).resolve().parents[1],
        phase_c_authority_root=phase_c_authority_root,
    )
    authority_binding = _ContainerAuthorityBinding(
        infinity_source_root=phase_c_authority_root,
        runtime_root=runtime_authority_root,
    )
    _require_distinct_secrets(
        ingress,
        attestation_secret,
        runtime_bearer,
        receipt_secret,
        state_secret,
        result_hmac_secret,
    )
    receipt_bundle = _receipt_authority(
        receipt_secret,
        authority_binding=authority_binding,
        runtime_repo=runtime_repo,
        source_authority=source_authority,
    )
    runtime_authority = V5RuntimeAuthorityProjection.issue(
        source_authority=source_authority,
        subscription_runtime_binding_commitment_sha256=(receipt_bundle.binding_commitment_sha256),
        runtime_source_sha256=receipt_bundle.runtime_source_sha256,
        runtime_route_binding_sha256=receipt_bundle.route_binding_sha256,
        runtime_transport_origin_sha256=SUBSCRIPTION_RUNTIME_TRANSPORT_ORIGIN_SHA256,
        expected_account_binding_hmac_sha256=account_binding,
        expected_base_instructions_sha256=base_instructions,
    )
    runtime = SubscriptionRuntimeClient(
        transport_origin=transport_origin,
        bearer_token=runtime_bearer,
        expected_account_binding_hmac_sha256=account_binding,
        expected_base_instructions_sha256=base_instructions,
        receipt_authority=receipt_bundle.authority,
    )
    state = SqliteOperationState(state_path, hmac_key=state_key)
    storage = Mem0StorageAdapter(PinnedMem0Backend(_build_pinned_memory(state_path.parent)))
    service = V5AdapterService(
        manifest=manifest,
        state=state,
        runtime=runtime,
        receipt_authority=receipt_bundle.authority,
        storage=storage,
        receipt_directory=state_path.parent / "receipts",
        result_hmac_key=result_hmac_key,
        runtime_authority=runtime_authority,
    )
    runtime_attestation = V5RuntimeAttestationAuthority(
        projection=runtime_authority,
        root_secret=attestation_secret.encode(),
    )
    return create_app(
        service=service,
        bearer_token=ingress,
        runtime_attestation_authority=runtime_attestation,
    )


def _receipt_authority(
    receipt_secret: str,
    *,
    authority_binding: _ContainerAuthorityBinding,
    runtime_repo: Path,
    source_authority: VerifiedSourceAuthority,
) -> _ReceiptAuthorityBundle:
    from phase_c_canary.attestation import verify_immutable_authority
    from phase_c_canary.authority import immutable_authority
    from phase_c_canary.receipt import NodePublicReceiptVerifier
    from phase_c_canary.runtime_binding import RuntimeBindingComposition
    from phase_c_canary.runtime_receipt_v2 import RuntimeReceiptV2Boundary

    reviewed = immutable_authority(authority_binding=authority_binding)
    _verify_phase_c_source_binding(reviewed, source_authority)
    verify_immutable_authority(reviewed)
    _verify_runtime_repo_binding(runtime_repo, reviewed.runtime_root)
    node_executable = Path(_required_environment("MEM0_V5_NODE_EXECUTABLE"))
    _verify_node_executable(node_executable)
    trusted_binding = RuntimeBindingComposition.compose_phase_c_canary(
        authority_binding=authority_binding
    ).issue()
    if not hmac.compare_digest(
        trusted_binding.commitment_sha256,
        _PHASE_C_RUNTIME_BINDING_COMMITMENT_SHA256,
    ):
        raise ValueError("adapter_configuration_invalid")
    return _ReceiptAuthorityBundle(
        authority=EstablishedReceiptV2Authority(
            boundary=RuntimeReceiptV2Boundary(
                NodePublicReceiptVerifier(runtime_repo, node_executable=node_executable)
            ),
            runtime_binding=trusted_binding,
            receipt_secret=receipt_secret,
            runtime_source_sha256=trusted_binding.runtime_source_sha256,
        ),
        binding_commitment_sha256=trusted_binding.commitment_sha256,
        runtime_source_sha256=trusted_binding.runtime_source_sha256,
        route_binding_sha256=trusted_binding.route_binding_sha256,
    )


def _verify_phase_c_source_binding(
    reviewed: object,
    source_authority: VerifiedSourceAuthority,
) -> None:
    infinity_commit = getattr(reviewed, "infinity_commit", None)
    release_manifest = getattr(reviewed, "infinity_release_manifest", None)
    release_sha256 = getattr(release_manifest, "sha256", None)
    if not (
        isinstance(infinity_commit, str)
        and isinstance(release_sha256, str)
        and hmac.compare_digest(
            infinity_commit,
            source_authority.phase_c_infinity_commit_sha1,
        )
        and hmac.compare_digest(
            release_sha256,
            source_authority.phase_c_release_manifest_sha256,
        )
    ):
        raise ValueError("adapter_configuration_invalid")


def _verify_runtime_repo_binding(runtime_repo: Path, runtime_root: Path) -> None:
    expected = runtime_root / "repo"
    try:
        metadata = runtime_repo.lstat()
        canonical = runtime_repo.resolve(strict=True)
    except OSError:
        raise ValueError("adapter_configuration_invalid") from None
    if (
        runtime_repo != expected
        or canonical != runtime_repo
        or stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
    ):
        raise ValueError("adapter_configuration_invalid")


def _build_pinned_memory(state_directory: Path):
    from mem0 import Memory
    from mem0_oss_adapter.sdk_oss import (
        OssRuntimeSettings,
        _patched_mem0_factories,
        pinned_memory_config,
    )
    from mem0_oss_adapter.subscription_llm import UsageLedger

    if _required_environment("MEM0_V5_QDRANT_ORIGIN") != "http://127.0.0.1:6334":
        raise ValueError("adapter_configuration_invalid")
    memory_state_directory = _prepare_memory_state_directory(state_directory)
    settings = OssRuntimeSettings(
        qdrant_host="127.0.0.1",
        qdrant_port=6334,
        collection_name="mem0_oss_v5",
        state_dir=memory_state_directory,
        model_dir=Path("/opt/models/bge-small-en-v1.5"),
        extraction_mode="raw_passthrough",
        bridge_url=None,
        bearer_token=None,
    )
    config = pinned_memory_config(settings, usage_ledger=UsageLedger())
    with _patched_mem0_factories():
        return Memory.from_config(config)


def _prepare_memory_state_directory(state_directory: Path) -> Path:
    """Create or revalidate the private restart-persistent Mem0 state root."""

    memory_state_directory = state_directory / "mem0"
    descriptor = None
    try:
        parent = os.lstat(state_directory)
        if (
            not state_directory.is_absolute()
            or not stat.S_ISDIR(parent.st_mode)
            or (parent.st_uid, parent.st_gid) != (os.geteuid(), os.getegid())
            or stat.S_IMODE(parent.st_mode) != 0o700
        ):
            raise ValueError
        with suppress(FileExistsError):
            os.mkdir(memory_state_directory, mode=0o700)
        descriptor = os.open(
            memory_state_directory,
            os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | getattr(os, "O_DIRECTORY", 0),
        )
        opened = os.fstat(descriptor)
        current = os.lstat(memory_state_directory)
        if (
            not stat.S_ISDIR(opened.st_mode)
            or (opened.st_uid, opened.st_gid) != (os.geteuid(), os.getegid())
            or stat.S_IMODE(opened.st_mode) != 0o700
            or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
        ):
            raise ValueError
    except (OSError, ValueError):
        raise ValueError("adapter_configuration_invalid") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return memory_state_directory


def _read_secret_file(environment_name: str) -> str:
    path = Path(_required_environment(environment_name))
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ValueError("adapter_configuration_invalid")
    mode = path.stat().st_mode
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise ValueError("adapter_configuration_invalid")
    raw = path.read_bytes()
    if not 1 <= len(raw) <= 8192:
        raise ValueError("adapter_configuration_invalid")
    value = raw.decode("utf-8")
    if not value or value != value.strip():
        raise ValueError("adapter_configuration_invalid")
    return value


def _read_pinned_digest_file(environment_name: str) -> str:
    """Read a public root-owned immutable SHA-256 pin, not a private secret."""

    path = Path(_required_environment(environment_name))
    descriptor = None
    try:
        if not path.is_absolute():
            raise ValueError
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        opened = os.fstat(descriptor)
        current = os.lstat(path)
        identity = (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
        if (
            not stat.S_ISREG(opened.st_mode)
            or stat.S_IMODE(opened.st_mode) != 0o444
            or (opened.st_uid, opened.st_gid) not in {(0, 0), (65534, 65534)}
            or opened.st_nlink != 1
            or identity != (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns)
        ):
            raise ValueError
        raw = os.read(descriptor, 65)
    except (OSError, ValueError):
        raise ValueError("adapter_configuration_invalid") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if len(raw) != 64 or any(byte not in b"0123456789abcdef" for byte in raw):
        raise ValueError("adapter_configuration_invalid")
    return raw.decode("ascii")


def _require_distinct_secrets(*values: str) -> None:
    for index, value in enumerate(values):
        if any(hmac.compare_digest(value.encode(), item.encode()) for item in values[index + 1 :]):
            raise ValueError("adapter_configuration_invalid")


def _required_environment(name: str) -> str:
    value = os.environ.get(name)
    if not value or value != value.strip():
        raise ValueError("adapter_configuration_invalid")
    return value


def _verify_node_executable(path: Path) -> None:
    expected = "b2959781cc5a74c357ffa02367efa8a0330cbb1c9cb347732fdfaaaca381cbcd"
    if (
        not path.is_absolute()
        or path.is_symlink()
        or not path.is_file()
        or hashlib.sha256(path.read_bytes()).hexdigest() != expected
    ):
        raise ValueError("adapter_configuration_invalid")


__all__ = ("build_app_from_environment",)

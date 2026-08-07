"""Environment-owned production bootstrap for the v5 adapter."""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from .app import create_app
from .composition import V5AdapterService
from .mem0_storage import Mem0StorageAdapter, PinnedMem0Backend
from .sealed_manifest import SealedInputManifest
from .source_authority import verify_source_authority
from .state_sqlite import SqliteOperationState
from .subscription_runtime import (
    SUBSCRIPTION_RUNTIME_TRANSPORT_ORIGIN_SHA256,
    EstablishedReceiptV2Authority,
    SubscriptionRuntimeClient,
)


@dataclass(frozen=True, slots=True)
class _ReceiptAuthorityBundle:
    authority: EstablishedReceiptV2Authority
    binding_commitment_sha256: str
    runtime_source_sha256: str
    route_binding_sha256: str


def build_app_from_environment():
    manifest = SealedInputManifest(Path(_required_environment("MEM0_V5_INPUT_MANIFEST_FILE")))
    state_path = Path(_required_environment("MEM0_V5_STATE_DB_FILE"))
    state_key = _read_secret_file("MEM0_V5_STATE_HMAC_FILE").encode()
    ingress = _read_secret_file("MEM0_V5_INGRESS_BEARER_FILE")
    runtime_bearer = _read_secret_file("MEM0_V5_RUNTIME_BEARER_FILE")
    receipt_secret = _read_secret_file("MEM0_V5_RECEIPT_SECRET_FILE")
    transport_origin = _read_secret_file("MEM0_V5_RUNTIME_TRANSPORT_ORIGIN_FILE")
    account_binding = _read_secret_file("MEM0_V5_ACCOUNT_BINDING_HMAC_FILE")
    base_instructions = _read_secret_file("MEM0_V5_BASE_INSTRUCTIONS_SHA256_FILE")
    source_authority = verify_source_authority(
        manifest_path=Path(_required_environment("MEM0_V5_SOURCE_AUTHORITY_MANIFEST_FILE")),
        expected_manifest_sha256=_read_pinned_digest_file(
            "MEM0_V5_SOURCE_AUTHORITY_MANIFEST_SHA256_FILE"
        ),
        installed_root=Path(__file__).resolve().parents[1],
        phase_c_authority_root=Path(_required_environment("MEM0_V5_PHASE_C_AUTHORITY_DIR")),
    )
    receipt_bundle = _receipt_authority(receipt_secret)
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
        expected_account_binding_hmac_sha256=account_binding,
        expected_base_instructions_sha256=base_instructions,
        storage=storage,
        receipt_directory=state_path.parent / "receipts",
        result_hmac_key=state_key,
        source_authority=source_authority,
        runtime_binding_commitment_sha256=receipt_bundle.binding_commitment_sha256,
        runtime_source_sha256=receipt_bundle.runtime_source_sha256,
        runtime_route_binding_sha256=receipt_bundle.route_binding_sha256,
        runtime_transport_origin_sha256=SUBSCRIPTION_RUNTIME_TRANSPORT_ORIGIN_SHA256,
    )
    return create_app(service=service, bearer_token=ingress)


def _receipt_authority(receipt_secret: str) -> _ReceiptAuthorityBundle:
    from phase_c_canary.attestation import verify_immutable_authority
    from phase_c_canary.authority import immutable_authority
    from phase_c_canary.receipt import NodePublicReceiptVerifier
    from phase_c_canary.runtime_binding import RuntimeBindingComposition
    from phase_c_canary.runtime_receipt_v2 import RuntimeReceiptV2Boundary

    verify_immutable_authority(immutable_authority())
    runtime_repo = Path(_required_environment("MEM0_V5_RUNTIME_REPO"))
    node_executable = Path(_required_environment("MEM0_V5_NODE_EXECUTABLE"))
    _verify_node_executable(node_executable)
    trusted_binding = RuntimeBindingComposition.compose_phase_c_canary().issue()
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


def _build_pinned_memory(state_directory: Path):
    from mem0 import Memory
    from mem0_oss_adapter.sdk_oss import (
        OssRuntimeSettings,
        _patched_mem0_factories,
        pinned_memory_config,
    )
    from mem0_oss_adapter.usage import UsageLedger

    if _required_environment("MEM0_V5_QDRANT_ORIGIN") != "http://127.0.0.1:6334":
        raise ValueError("adapter_configuration_invalid")
    settings = OssRuntimeSettings(
        qdrant_host="127.0.0.1",
        qdrant_port=6334,
        collection_name="mem0_oss_v5",
        state_dir=state_directory / "mem0",
        model_dir=Path("/opt/models/bge-small-en-v1.5"),
        extraction_mode="raw_passthrough",
        bridge_url=None,
        bearer_token=None,
    )
    config = pinned_memory_config(settings, usage_ledger=UsageLedger())
    with _patched_mem0_factories():
        return Memory.from_config(config)


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

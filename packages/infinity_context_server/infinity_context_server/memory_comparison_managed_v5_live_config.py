"""Provider-free, fail-closed configuration for the managed-v5 live CLI."""

from __future__ import annotations

import hashlib
import importlib.machinery
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import final

from infinity_context_server.memory_comparison_managed_mem0_v5_extraction_projection import (
    MEM0_V5_EXTRACTION_SYSTEM_PROMPT_SHA256,
)
from infinity_context_server.memory_comparison_publishable_methodology import (
    SUBSCRIPTION_RUNTIME_BASE_INSTRUCTIONS_SHA256,
)

_AUTHORITY_SCHEMA = "managed-mem0-v5-live-runtime-authority.v2"
_MAX_AUTHORITY_BYTES = 64 * 1024
_MAX_PUBLIC_IMMUTABLE_BYTES = 32 * 1024 * 1024
_MEM0_ADAPTER_ORIGIN = "http://127.0.0.1:19091"
_REVIEWED_NODE_SHA256 = "b2959781cc5a74c357ffa02367efa8a0330cbb1c9cb347732fdfaaaca381cbcd"
_REVIEWED_NODE_SIZE_BYTES = 123_438_592
_SHA256_CHARS = frozenset("0123456789abcdef")
_PRIVATE_FILE_MODE = 0o600
_PRIVATE_ROOT_MODE = 0o700
_PUBLIC_DIRECTORY_MODES = frozenset({0o500, 0o550, 0o555, 0o700, 0o750, 0o755})
_PUBLIC_FILE_MODES = frozenset({0o400, 0o440, 0o444})
_PUBLIC_EXECUTABLE_MODES = frozenset({0o500, 0o550, 0o555, 0o700, 0o750, 0o755})
_PUBLIC_PYTHON_FILE_MODES = frozenset({0o400, 0o440, 0o444, 0o600, 0o640, 0o644})
_PYTHON_IMPORT_SUFFIXES = tuple(importlib.machinery.all_suffixes())
_REVIEWED_PHASE_C_PYTHON_TREE_SHA256 = (
    "4a113dc4d6308da0ebf8d61cadc01a8b59afb2edbb5e9c8982b009738764d8ad"
)
_REVIEWED_PHASE_C_PYTHON_FILES = (
    ("__init__.py", "efbde36910ac6e64f630ce91401b723ac966949ca380ba6b0275a3fb0a81e53b"),
    ("attestation.py", "dcf4b326a637f227a1fb52e8cd724009827d28021f17258d2d053c589578fcb3"),
    ("authority.py", "2b86b4735e4abe23c3ee32c645de233ec097bac3ac3cd0df5298c3365d32c571"),
    ("bundle.py", "27c2fc7075c5b2b8f48eadd2d9d3576c3d1592a2f3988baafb3e59ce7d391411"),
    ("cli.py", "a1b880005a2f516c51871c6fe1ec337afbc601a9119cc42a273e68b9ac4de595"),
    ("environment.py", "a5e67c287b4eaf3b2df680a6da3be35880413fc6458f2564805328322a8af8d8"),
    ("hashing.py", "38c85ad1b21d65f038b902db9253b20200e4ce7a14a03a8d089df9ae63e696d4"),
    ("http_adapter.py", "1a9111db1d0c66a768142c64b1858c8eb07f26431d61f7182643504975a26b9e"),
    ("journal.py", "8fb95eb0740caf2f86604ec6e6aaafd758ce982fded1d858f5465db7659ca281"),
    ("orchestrator.py", "25fc601401b6347560c8d36d6ac0fcaef51c805e044fc6694918328bb206b27f"),
    ("processes.py", "6d58dbdea7e7d6967efecfbc94097e2b15293b708be144c3fc88921074fe0746"),
    ("publication.py", "2695381860eb9f3de105b4b550c4c2d77dbae89efbb2ff341b995893b3eae409"),
    ("python_closure.py", "68ba328791479885c96951ed48003b11ac1172c0dfe687ed73f8a539c3455913"),
    ("readiness.py", "7ac29fa558a7dde984275035cce804b9d0190086a51b308631ac2e312d04815c"),
    ("receipt.py", "bdaeb7f1323d9cd1c38a46954ee325063f301b7f58d5cf726744b90e4374dd6f"),
    ("receipt_aggregation.py", "b5119397a008a9f48b66b51b2723b88087b72703d73fa40250e960136abb926c"),
    ("runtime_binding.py", "62174e6d4b35095656fd6e39a01b5e3dd9f2b4573729f106f27c6704ca657797"),
    ("runtime_receipt_v2.py", "48fd63c6b2ec65de508d65795d827714eb77720c50ecafb426a5c80b5e8bf62f"),
    ("strict_schema.py", "d630a26047861bedeea7643eb3b3265260233a6414792cf79e6871b4fb26bceb"),
)


class ManagedV5LiveConfigError(ValueError):
    """Stable fail-closed configuration error."""

    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class _DuplicateJsonKey(ValueError):
    pass


@final
@dataclass(frozen=True, slots=True)
class ManagedV5LiveRuntimeAuthority:
    """Public fields that bind a reviewed runtime to requests and receipts."""

    model: str
    reasoning_effort: str
    service_tier: str
    runtime_source_revision: str
    runtime_source_sha256: str
    runtime_base_sha256: str
    route_binding_sha256: str
    base_instructions_sha256: str
    extraction_system_prompt_sha256: str
    account_binding_hmac_sha256: str
    response_format_type: str
    response_format_sha256: str
    response_schema_sha256: str
    requested_output_tokens: int

    def __post_init__(self) -> None:
        text = (
            self.model,
            self.reasoning_effort,
            self.service_tier,
            self.runtime_source_revision,
            self.response_format_type,
        )
        digests = (
            self.runtime_source_sha256,
            self.runtime_base_sha256,
            self.route_binding_sha256,
            self.base_instructions_sha256,
            self.extraction_system_prompt_sha256,
            self.account_binding_hmac_sha256,
            self.response_format_sha256,
            self.response_schema_sha256,
        )
        if (
            any(
                type(value) is not str or not value or value != value.strip() or len(value) > 512
                for value in text
            )
            or any(not _is_sha256(value) for value in digests)
            or self.base_instructions_sha256 != SUBSCRIPTION_RUNTIME_BASE_INSTRUCTIONS_SHA256
            or self.extraction_system_prompt_sha256 != MEM0_V5_EXTRACTION_SYSTEM_PROMPT_SHA256
            or type(self.requested_output_tokens) is not int
            or self.requested_output_tokens != 4096
        ):
            raise ManagedV5LiveConfigError("managed_v5_live_runtime_authority_invalid")


@final
@dataclass(frozen=True, slots=True)
class ManagedV5LiveFilesystemConfig:
    """All filesystem authority required before a live runtime can be built."""

    state_root: Path
    secret_root: Path
    report_root: Path
    report_file: Path
    dispatch_journal: Path
    operation_journal: Path
    durable_clean_state: Path
    recovery_journal: Path
    ingress_bearer_file: Path
    evidence_key_file: Path
    evidence_key_sha256: str
    receipt_secret_file: Path
    checkpoint_signing_key_file: Path
    checkpoint_head_key_file: Path
    operation_journal_signer_secret_file: Path
    durable_clean_state_hmac_secret_file: Path
    runtime_attestation_secret_file: Path
    recovery_hmac_secret_file: Path
    runtime_attestation_secret_sha256: str
    runtime_authority_file: Path
    runtime_authority_sha256: str
    phase_c_package_root: Path
    runtime_repo: Path
    runtime_artifact_manifest: Path
    runtime_artifact_manifest_sha256: str
    node_executable: Path
    node_executable_sha256: str
    adapter_runtime_pin_file: Path
    adapter_runtime_pin_sha256: str
    recovery_report_file: Path
    phase_c_python_tree_sha256: str = _REVIEWED_PHASE_C_PYTHON_TREE_SHA256

    def __post_init__(self) -> None:
        paths = (
            self.state_root,
            self.secret_root,
            self.report_root,
            self.report_file,
            self.dispatch_journal,
            self.operation_journal,
            self.durable_clean_state,
            self.recovery_journal,
            self.ingress_bearer_file,
            self.evidence_key_file,
            self.receipt_secret_file,
            self.checkpoint_signing_key_file,
            self.checkpoint_head_key_file,
            self.operation_journal_signer_secret_file,
            self.durable_clean_state_hmac_secret_file,
            self.runtime_attestation_secret_file,
            self.recovery_hmac_secret_file,
            self.runtime_authority_file,
            self.phase_c_package_root,
            self.runtime_repo,
            self.runtime_artifact_manifest,
            self.node_executable,
            self.adapter_runtime_pin_file,
            self.recovery_report_file,
        )
        digests = (
            self.evidence_key_sha256,
            self.runtime_authority_sha256,
            self.runtime_artifact_manifest_sha256,
            self.node_executable_sha256,
            self.runtime_attestation_secret_sha256,
            self.adapter_runtime_pin_sha256,
            self.phase_c_python_tree_sha256,
        )
        if (
            any(not isinstance(value, Path) for value in paths)
            or any(not _is_sha256(value) for value in digests)
            or self.phase_c_python_tree_sha256 != _REVIEWED_PHASE_C_PYTHON_TREE_SHA256
        ):
            raise ManagedV5LiveConfigError("managed_v5_live_filesystem_config_invalid")


@final
@dataclass(frozen=True, slots=True)
class ManagedV5LiveRuntimeConfig:
    """Pinned network-free runtime routing configuration."""

    mem0_adapter_origin: str

    def __post_init__(self) -> None:
        if (
            type(self.mem0_adapter_origin) is not str
            or self.mem0_adapter_origin != _MEM0_ADAPTER_ORIGIN
        ):
            raise ManagedV5LiveConfigError("managed_v5_live_mem0_adapter_origin_invalid")


@final
@dataclass(frozen=True, slots=True)
class ManagedV5LiveConfig:
    filesystem: ManagedV5LiveFilesystemConfig
    runtime: ManagedV5LiveRuntimeConfig

    def __post_init__(self) -> None:
        if (
            type(self.filesystem) is not ManagedV5LiveFilesystemConfig
            or type(self.runtime) is not ManagedV5LiveRuntimeConfig
        ):
            raise ManagedV5LiveConfigError("managed_v5_live_config_invalid")


def parse_managed_v5_live_runtime_authority(
    raw: bytes,
) -> ManagedV5LiveRuntimeAuthority:
    """Parse the exact public authority schema without importing any provider."""

    if type(raw) is not bytes or not 1 <= len(raw) <= _MAX_AUTHORITY_BYTES:
        raise ManagedV5LiveConfigError("managed_v5_live_runtime_authority_invalid")
    try:
        payload = json.loads(raw, object_pairs_hook=_unique_json_object)
    except (UnicodeDecodeError, json.JSONDecodeError, _DuplicateJsonKey):
        raise ManagedV5LiveConfigError("managed_v5_live_runtime_authority_invalid") from None
    keys = {
        "schema_version",
        "model",
        "reasoning_effort",
        "service_tier",
        "runtime_source_revision",
        "runtime_source_sha256",
        "runtime_base_sha256",
        "route_binding_sha256",
        "base_instructions_sha256",
        "extraction_system_prompt_sha256",
        "account_binding_hmac_sha256",
        "response_format_type",
        "response_format_sha256",
        "response_schema_sha256",
        "requested_output_tokens",
    }
    if type(payload) is not dict or set(payload) != keys:
        raise ManagedV5LiveConfigError("managed_v5_live_runtime_authority_invalid")
    if payload.pop("schema_version") != _AUTHORITY_SCHEMA:
        raise ManagedV5LiveConfigError("managed_v5_live_runtime_authority_invalid")
    try:
        return ManagedV5LiveRuntimeAuthority(**payload)
    except TypeError:
        raise ManagedV5LiveConfigError("managed_v5_live_runtime_authority_invalid") from None


def validate_managed_v5_live_public_config(
    config: ManagedV5LiveConfig,
) -> ManagedV5LiveRuntimeAuthority:
    """Validate public authority and secret metadata, never secret file contents."""

    if type(config) is not ManagedV5LiveConfig:
        raise ManagedV5LiveConfigError("managed_v5_live_config_invalid")
    filesystem = config.filesystem
    roots = (filesystem.state_root, filesystem.secret_root, filesystem.report_root)
    for root in roots:
        _require_private_directory(root)
    _require_disjoint_roots(roots)

    private_files = (
        filesystem.ingress_bearer_file,
        filesystem.evidence_key_file,
        filesystem.receipt_secret_file,
        filesystem.checkpoint_signing_key_file,
        filesystem.checkpoint_head_key_file,
        filesystem.operation_journal_signer_secret_file,
        filesystem.durable_clean_state_hmac_secret_file,
        filesystem.runtime_attestation_secret_file,
        filesystem.recovery_hmac_secret_file,
    )
    if len(set(private_files)) != len(private_files):
        raise ManagedV5LiveConfigError("managed_v5_live_credential_paths_invalid")
    for path in private_files:
        _require_private_file_metadata(path, parent=filesystem.secret_root)
    _require_optional_private_file(
        filesystem.dispatch_journal,
        parent=filesystem.state_root,
        code="managed_v5_live_dispatch_journal_invalid",
    )
    state_files = (
        filesystem.dispatch_journal,
        filesystem.operation_journal,
        filesystem.durable_clean_state,
        filesystem.recovery_journal,
    )
    if len(set(state_files)) != len(state_files):
        raise ManagedV5LiveConfigError("managed_v5_live_state_paths_invalid")
    _require_optional_private_file(
        filesystem.operation_journal,
        parent=filesystem.state_root,
        code="managed_v5_live_operation_journal_invalid",
    )
    _require_optional_private_file(
        filesystem.durable_clean_state,
        parent=filesystem.state_root,
        code="managed_v5_live_durable_clean_state_invalid",
    )
    _require_optional_private_file(
        filesystem.recovery_journal,
        parent=filesystem.state_root,
        code="managed_v5_live_recovery_journal_invalid",
    )
    _require_optional_private_file(
        filesystem.report_file,
        parent=filesystem.report_root,
        code="managed_v5_live_report_file_invalid",
    )
    report_files = (filesystem.report_file, filesystem.recovery_report_file)
    if len(set(report_files)) != len(report_files):
        raise ManagedV5LiveConfigError("managed_v5_live_report_paths_invalid")
    _require_optional_private_file(
        filesystem.recovery_report_file,
        parent=filesystem.report_root,
        code="managed_v5_live_recovery_report_file_invalid",
    )

    _require_public_directory(filesystem.phase_c_package_root)
    _validate_reviewed_phase_c_python_tree(
        filesystem.phase_c_package_root,
        filesystem.phase_c_python_tree_sha256,
    )
    _require_public_directory(filesystem.runtime_repo)
    if filesystem.runtime_artifact_manifest != (
        filesystem.runtime_repo.parent / "artifact-manifest.json"
    ):
        raise ManagedV5LiveConfigError("managed_v5_live_runtime_artifact_path_invalid")
    public_paths = (
        filesystem.runtime_authority_file,
        filesystem.phase_c_package_root,
        filesystem.runtime_repo,
        filesystem.runtime_artifact_manifest,
        filesystem.node_executable,
        filesystem.adapter_runtime_pin_file,
    )
    if any(_paths_overlap(path, root) for path in public_paths for root in roots):
        raise ManagedV5LiveConfigError("managed_v5_live_public_private_paths_overlap")

    authority_raw = _read_public_immutable(
        filesystem.runtime_authority_file,
        filesystem.runtime_authority_sha256,
        maximum_bytes=_MAX_AUTHORITY_BYTES,
        executable=False,
        code="managed_v5_live_runtime_authority_file_invalid",
    )
    _read_public_immutable(
        filesystem.runtime_artifact_manifest,
        filesystem.runtime_artifact_manifest_sha256,
        maximum_bytes=_MAX_PUBLIC_IMMUTABLE_BYTES,
        executable=False,
        code="managed_v5_live_runtime_artifact_invalid",
    )
    _read_public_immutable(
        filesystem.adapter_runtime_pin_file,
        filesystem.adapter_runtime_pin_sha256,
        maximum_bytes=_MAX_AUTHORITY_BYTES,
        executable=False,
        code="managed_v5_live_adapter_runtime_pin_invalid",
    )
    _verify_reviewed_node(filesystem.node_executable, filesystem.node_executable_sha256)
    return parse_managed_v5_live_runtime_authority(authority_raw)


def _require_private_directory(path: Path) -> None:
    try:
        metadata = path.lstat()
        canonical = path.resolve(strict=True)
    except OSError:
        raise ManagedV5LiveConfigError("managed_v5_live_private_root_invalid") from None
    if (
        not path.is_absolute()
        or canonical != path
        or path.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != _PRIVATE_ROOT_MODE
    ):
        raise ManagedV5LiveConfigError("managed_v5_live_private_root_invalid")


def _require_disjoint_roots(roots: tuple[Path, Path, Path]) -> None:
    if any(
        _paths_overlap(left, right)
        for index, left in enumerate(roots)
        for right in roots[index + 1 :]
    ):
        raise ManagedV5LiveConfigError("managed_v5_live_private_roots_overlap")


def _require_private_file_metadata(path: Path, *, parent: Path) -> None:
    _require_direct_child(path, parent, "managed_v5_live_credential_paths_invalid")
    try:
        metadata = path.lstat()
        canonical = path.resolve(strict=True)
    except OSError:
        raise ManagedV5LiveConfigError("managed_v5_live_credential_paths_invalid") from None
    if (
        canonical != path
        or path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_nlink != 1
        or stat.S_IMODE(metadata.st_mode) != _PRIVATE_FILE_MODE
    ):
        raise ManagedV5LiveConfigError("managed_v5_live_credential_paths_invalid")


def _require_optional_private_file(path: Path, *, parent: Path, code: str) -> None:
    _require_direct_child(path, parent, code)
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return
    except OSError:
        raise ManagedV5LiveConfigError(code) from None
    try:
        canonical = path.resolve(strict=True)
    except OSError:
        raise ManagedV5LiveConfigError(code) from None
    if (
        canonical != path
        or path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_nlink != 1
        or stat.S_IMODE(metadata.st_mode) != _PRIVATE_FILE_MODE
    ):
        raise ManagedV5LiveConfigError(code)


def _require_direct_child(path: Path, parent: Path, code: str) -> None:
    try:
        valid = (
            path.is_absolute()
            and path.name not in {"", ".", ".."}
            and path.parent.resolve(strict=True) == parent.resolve(strict=True)
        )
    except OSError:
        valid = False
    if not valid:
        raise ManagedV5LiveConfigError(code)


def _require_public_directory(path: Path) -> None:
    try:
        metadata = path.lstat()
        canonical = path.resolve(strict=True)
    except OSError:
        raise ManagedV5LiveConfigError("managed_v5_live_runtime_path_invalid") from None
    if (
        not path.is_absolute()
        or canonical != path
        or path.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid not in {0, os.geteuid()}
        or stat.S_IMODE(metadata.st_mode) not in _PUBLIC_DIRECTORY_MODES
    ):
        raise ManagedV5LiveConfigError("managed_v5_live_runtime_path_invalid")


def _read_public_immutable(
    path: Path,
    expected_sha256: str,
    *,
    maximum_bytes: int,
    executable: bool,
    code: str,
) -> bytes:
    if not path.is_absolute() or not _is_sha256(expected_sha256):
        raise ManagedV5LiveConfigError(code)
    allowed_modes = _PUBLIC_EXECUTABLE_MODES if executable else _PUBLIC_FILE_MODES
    descriptor: int | None = None
    try:
        if path.resolve(strict=True) != path:
            raise ValueError
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0))
        opened = os.fstat(descriptor)
        current = os.lstat(path)
        identity = (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_uid not in {0, os.geteuid()}
            or stat.S_IMODE(opened.st_mode) not in allowed_modes
            or opened.st_nlink != 1
            or not 1 <= opened.st_size <= maximum_bytes
            or identity != (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns)
        ):
            raise ValueError
        chunks: list[bytes] = []
        size = 0
        while True:
            chunk = os.read(descriptor, min(65_536, maximum_bytes + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > maximum_bytes:
                raise ValueError
        final = os.fstat(descriptor)
        if identity != (final.st_dev, final.st_ino, final.st_size, final.st_mtime_ns):
            raise ValueError
        raw = b"".join(chunks)
        if hashlib.sha256(raw).hexdigest() != expected_sha256:
            raise ValueError
        return raw
    except (OSError, ValueError):
        raise ManagedV5LiveConfigError(code) from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _verify_reviewed_node(path: Path, expected_sha256: str) -> None:
    if expected_sha256 != _REVIEWED_NODE_SHA256:
        raise ManagedV5LiveConfigError("managed_v5_live_node_authority_invalid")
    try:
        metadata = path.stat()
        if metadata.st_size != _REVIEWED_NODE_SIZE_BYTES:
            raise ValueError
        _read_public_immutable(
            path,
            expected_sha256,
            maximum_bytes=_REVIEWED_NODE_SIZE_BYTES,
            executable=True,
            code="managed_v5_live_node_authority_invalid",
        )
    except (OSError, ValueError, ManagedV5LiveConfigError):
        raise ManagedV5LiveConfigError("managed_v5_live_node_authority_invalid") from None


def _validate_reviewed_phase_c_python_tree(
    root: Path,
    expected_tree_sha256: str,
) -> tuple[tuple[object, ...], ...]:
    """Hash the complete reviewed Python tree before any package import."""

    if expected_tree_sha256 != _REVIEWED_PHASE_C_PYTHON_TREE_SHA256:
        raise ManagedV5LiveConfigError("managed_v5_live_phase_c_tree_invalid")
    package = root / "phase_c_canary"
    try:
        if package.resolve(strict=True) != package or package.is_symlink() or not package.is_dir():
            raise ValueError
        observed_paths: set[str] = set()
        for current, directory_names, file_names in os.walk(package, followlinks=False):
            current_path = Path(current)
            _require_public_python_directory(current_path)
            for name in (*directory_names, *file_names):
                if (current_path / name).is_symlink():
                    raise ValueError
            for name in file_names:
                path = current_path / name
                metadata = path.lstat()
                if not stat.S_ISREG(metadata.st_mode):
                    raise ValueError
                if path.suffix == ".py":
                    observed_paths.add(path.relative_to(package).as_posix())
                elif _is_unreviewed_executable_or_importable(path, metadata.st_mode):
                    raise ValueError
        expected = dict(_REVIEWED_PHASE_C_PYTHON_FILES)
        if observed_paths != set(expected):
            raise ValueError
        files = []
        snapshots: list[tuple[object, ...]] = []
        for relative, reviewed_sha256 in _REVIEWED_PHASE_C_PYTHON_FILES:
            path = package / relative
            observed_sha256, identity = _read_stable_public_python_sha256(path)
            if observed_sha256 != reviewed_sha256:
                raise ValueError
            files.append({"path": relative, "sha256": observed_sha256})
            snapshots.append((relative, *identity, observed_sha256))
        payload = {
            "schema_version": "phase-c-canary-python-tree.v1",
            "files": files,
        }
        tree_sha256 = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if tree_sha256 != expected_tree_sha256:
            raise ValueError
        return tuple(snapshots)
    except (OSError, ValueError):
        raise ManagedV5LiveConfigError("managed_v5_live_phase_c_tree_invalid") from None


def _is_unreviewed_executable_or_importable(path: Path, mode: int) -> bool:
    return bool(stat.S_IMODE(mode) & 0o111) or path.name.endswith(_PYTHON_IMPORT_SUFFIXES)


def _require_public_python_directory(path: Path) -> None:
    metadata = path.lstat()
    if (
        path.resolve(strict=True) != path
        or path.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid not in {0, os.geteuid()}
        or stat.S_IMODE(metadata.st_mode) not in _PUBLIC_DIRECTORY_MODES
    ):
        raise ValueError


def _read_stable_public_python_sha256(
    path: Path,
) -> tuple[str, tuple[int, int, int, int, int, int, int]]:
    descriptor: int | None = None
    try:
        if path.resolve(strict=True) != path or path.is_symlink():
            raise ValueError
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        )
        opened = os.fstat(descriptor)
        current = os.lstat(path)
        identity = (
            opened.st_dev,
            opened.st_ino,
            opened.st_uid,
            opened.st_gid,
            opened.st_mode,
            opened.st_size,
            opened.st_mtime_ns,
        )
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_uid not in {0, os.geteuid()}
            or stat.S_IMODE(opened.st_mode) not in _PUBLIC_PYTHON_FILE_MODES
            or opened.st_nlink != 1
            or not 1 <= opened.st_size <= 1_048_576
            or identity
            != (
                current.st_dev,
                current.st_ino,
                current.st_uid,
                current.st_gid,
                current.st_mode,
                current.st_size,
                current.st_mtime_ns,
            )
        ):
            raise ValueError
        digest = hashlib.sha256()
        while chunk := os.read(descriptor, 65_536):
            digest.update(chunk)
        final = os.fstat(descriptor)
        if identity != (
            final.st_dev,
            final.st_ino,
            final.st_uid,
            final.st_gid,
            final.st_mode,
            final.st_size,
            final.st_mtime_ns,
        ):
            raise ValueError
        return digest.hexdigest(), identity
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _paths_overlap(left: Path, right: Path) -> bool:
    try:
        left_canonical = left.resolve(strict=True)
        right_canonical = right.resolve(strict=True)
    except OSError:
        left_canonical = left.resolve(strict=False)
        right_canonical = right.resolve(strict=False)
    return (
        left_canonical == right_canonical
        or left_canonical.is_relative_to(right_canonical)
        or right_canonical.is_relative_to(left_canonical)
    )


def _is_sha256(value: object) -> bool:
    return type(value) is str and len(value) == 64 and set(value) <= _SHA256_CHARS


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKey
        result[key] = value
    return result


__all__ = (
    "ManagedV5LiveConfig",
    "ManagedV5LiveConfigError",
    "ManagedV5LiveFilesystemConfig",
    "ManagedV5LiveRuntimeAuthority",
    "ManagedV5LiveRuntimeConfig",
    "parse_managed_v5_live_runtime_authority",
    "validate_managed_v5_live_public_config",
)

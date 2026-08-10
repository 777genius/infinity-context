"""Root-only lifecycle broker for the provider-free namespace runner."""

from __future__ import annotations

import hashlib
import json
import os
import re
import selectors
import socket
import stat
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

PINNED_DOCKER_HOST = "unix:///run/infinity-locomo-docker/docker.sock"
PINNED_DOCKER = "/usr/bin/docker"
PINNED_NODE = Path(
    "/mnt/volume_ams3_1784742570542/infinity-locomo-benchmark/"
    "e2e-runtime-authorities/node-b2959781/node"
)
PINNED_NODE_SHA256 = "b2959781cc5a74c357ffa02367efa8a0330cbb1c9cb347732fdfaaaca381cbcd"
REQUEST = b"restart-v1\n"
SUCCESS = b"ok-v1\n"
FAILURE = b"error-v1\n"
_PROJECT = re.compile(r"^mem0-v5-e2e-[0-9a-f]{8,40}-r[0-9]+$")
PUBLIC_RESULT_KEYS = frozenset(
    {
        "verdict",
        "admission_commitment_sha256",
        "operation_id_sha256",
        "runtime_receipt_sha256",
        "storage_commitment_sha256",
        "seal_commitment_sha256",
        "cleanup_receipt_sha256",
        "fake_provider_calls",
    }
)
SHA_KEYS = PUBLIC_RESULT_KEYS - {"verdict", "fake_provider_calls"}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PATH_ENVIRONMENT = (
    "MEM0_V5_INPUT_DIR",
    "MEM0_V5_STATE_DIR",
    "MEM0_V5_SECRET_DIR",
    "MEM0_V5_FAKE_RUNTIME_STATE_DIR",
    "MEM0_V5_RUNTIME_AUTHORITY_DIR",
    "MEM0_V5_SOURCE_AUTHORITY_DIR",
    "MEM0_V5_SOURCE_AUTHORITY_PIN_DIR",
    "MEM0_V5_SOURCE_AUTHORITY_PIN_SHA256_FILE",
    "MEM0_V5_NODE_EXECUTABLE_SOURCE",
)


def build_mount_policy(
    environment: Mapping[str, str],
) -> dict[str, dict[str, tuple[str, bool]]]:
    secret = Path(environment["MEM0_V5_SECRET_DIR"])
    runtime_target = (
        "/mnt/volume_ams3_1784742570542/infinity-context/runtimes/subscription-runtime/e904ec95"
    )
    source_target = "/mnt/volume_ams3_1784742570542/infinity-context/sources/9499b9c2"
    node_source = environment["MEM0_V5_NODE_EXECUTABLE_SOURCE"]
    return {
        "e2e-network-anchor": {},
        "mem0-oss-v5-qdrant": {},
        "mem0-oss-v5-fake-runtime": {
            "/run/fake-runtime-secrets/runtime-bearer": (
                str(secret / "runtime-bearer"),
                False,
            ),
            "/run/fake-runtime-secrets/runtime-receipt-secret": (
                str(secret / "runtime-receipt-secret"),
                False,
            ),
            "/run/fake-runtime-secrets/account-binding-hmac-sha256": (
                str(secret / "account-binding-hmac-sha256"),
                False,
            ),
            "/run/fake-runtime-secrets/base-instructions-sha256": (
                str(secret / "base-instructions-sha256"),
                False,
            ),
            "/run/fake-runtime": (environment["MEM0_V5_FAKE_RUNTIME_STATE_DIR"], True),
            runtime_target: (environment["MEM0_V5_RUNTIME_AUTHORITY_DIR"], False),
            "/usr/local/bin/node": (node_source, False),
        },
        "mem0-oss-adapter-v5": {
            "/run/mem0-v5-input": (environment["MEM0_V5_INPUT_DIR"], False),
            "/run/mem0-v5-state": (environment["MEM0_V5_STATE_DIR"], True),
            "/run/secrets": (environment["MEM0_V5_SECRET_DIR"], False),
            runtime_target: (environment["MEM0_V5_RUNTIME_AUTHORITY_DIR"], False),
            source_target: (environment["MEM0_V5_SOURCE_AUTHORITY_DIR"], False),
            "/run/source-authority": (
                environment["MEM0_V5_SOURCE_AUTHORITY_PIN_DIR"],
                False,
            ),
            "/run/source-authority-pin/manifest.sha256": (
                environment["MEM0_V5_SOURCE_AUTHORITY_PIN_SHA256_FILE"],
                False,
            ),
            "/usr/local/bin/node": (node_source, False),
        },
    }


def validate_public_result(raw: bytes, error_type: type[Exception]) -> Mapping[str, Any]:
    try:
        text = raw.decode("utf-8")
        value = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise error_type("e2e_public_result_invalid") from None
    if not isinstance(value, dict) or set(value) != PUBLIC_RESULT_KEYS:
        raise error_type("e2e_public_result_invalid")
    if (
        value.get("verdict") != "PASS"
        or value.get("fake_provider_calls") != 1
        or any(
            not isinstance(value.get(key), str) or not _SHA256.fullmatch(value[key])
            for key in SHA_KEYS
        )
    ):
        raise error_type("e2e_public_result_invalid")
    if text != json.dumps(value, sort_keys=True) + "\n":
        raise error_type("e2e_public_result_noncanonical")
    return value


def attest_service_process(config: Mapping[str, Any], service: str) -> None:
    expected_commands = {
        "e2e-network-anchor": (["python", "-m", "e2e.anchor"], None),
        "mem0-oss-v5-fake-runtime": (
            [
                "python",
                "-m",
                "e2e.fake_runtime",
                "--runtime-repo",
                "/mnt/volume_ams3_1784742570542/infinity-context/"
                "runtimes/subscription-runtime/e904ec95/repo",
                "--node",
                "/usr/local/bin/node",
                "--counter",
                "/run/fake-runtime/counter.json",
            ],
            None,
        ),
        "mem0-oss-v5-qdrant": (["./entrypoint.sh"], None),
        "mem0-oss-adapter-v5": (
            [
                "uvicorn",
                "mem0_oss_adapter_v5.composition:build_app_from_environment",
                "--factory",
                "--host",
                "127.0.0.1",
                "--port",
                "19091",
                "--no-access-log",
                "--no-proxy-headers",
            ],
            None,
        ),
    }
    expected_cmd, expected_entrypoint = expected_commands[service]
    if config.get("Cmd") != expected_cmd or config.get("Entrypoint") != expected_entrypoint:
        raise ValueError("e2e_service_command_invalid")
    environment = config.get("Env")
    if not isinstance(environment, list) or any(
        not isinstance(item, str) or "=" not in item for item in environment
    ):
        raise ValueError("e2e_service_environment_invalid")
    pairs = [item.split("=", 1) for item in environment]
    values = dict(pairs)
    if len(values) != len(pairs):
        raise ValueError("e2e_service_environment_invalid")
    python_base = {
        "PATH": "/usr/local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "LANG": "C.UTF-8",
        "GPG_KEY": "A035C8C19219BA821ECEA86B64E628F8D684696D",
        "PYTHON_VERSION": "3.11.15",
        "PYTHON_SHA256": "272179ddd9a2e41a0fc8e42e33dfbdca0b3711aa5abf372d3f2d51543d09b625",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
    }
    expected = {
        "e2e-network-anchor": python_base,
        "mem0-oss-v5-fake-runtime": {
            **python_base,
            "MEM0_V5_E2E_SECRET_DIR": "/run/fake-runtime-secrets",
        },
        "mem0-oss-v5-qdrant": {
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "DIR": "",
            "TZ": "Etc/UTC",
            "RUN_MODE": "production",
            "QDRANT__SERVICE__HOST": "127.0.0.1",
            "QDRANT__SERVICE__HTTP_PORT": "6334",
            "QDRANT__STORAGE__STORAGE_PATH": "/qdrant/storage",
            "QDRANT__STORAGE__SNAPSHOTS_PATH": "/qdrant/storage/snapshots",
            "QDRANT__TELEMETRY_DISABLED": "true",
        },
        "mem0-oss-adapter-v5": {
            **python_base,
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_NO_CACHE_DIR": "1",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "MEM0_TELEMETRY": "false",
            "MEM0_TELEMETRY_SAMPLE_RATE": "0",
            "MEM0_OSS_FASTEMBED_MODEL_DIR": "/opt/models/bge-small-en-v1.5",
            "MEM0_V5_INPUT_MANIFEST_FILE": "/run/mem0-v5-input/manifest.json",
            "MEM0_V5_STATE_DB_FILE": "/run/mem0-v5-state/operations.sqlite3",
            "MEM0_V5_INGRESS_BEARER_FILE": "/run/secrets/ingress-bearer",
            "MEM0_V5_STATE_HMAC_FILE": "/run/secrets/state-hmac",
            "MEM0_V5_RESULT_HMAC_FILE": "/run/secrets/result-hmac",
            "MEM0_V5_RUNTIME_ATTESTATION_SECRET_FILE": ("/run/secrets/runtime-attestation-secret"),
            "MEM0_V5_RUNTIME_BEARER_FILE": "/run/secrets/runtime-bearer",
            "MEM0_V5_RECEIPT_SECRET_FILE": "/run/secrets/runtime-receipt-secret",
            "MEM0_V5_RUNTIME_TRANSPORT_ORIGIN_FILE": "/run/secrets/runtime-transport-origin",
            "MEM0_V5_ACCOUNT_BINDING_HMAC_FILE": "/run/secrets/account-binding-hmac-sha256",
            "MEM0_V5_BASE_INSTRUCTIONS_SHA256_FILE": "/run/secrets/base-instructions-sha256",
            "MEM0_V5_QDRANT_ORIGIN": "http://127.0.0.1:6334",
            "MEM0_V5_RUNTIME_AUTHORITY_DIR": (
                "/mnt/volume_ams3_1784742570542/infinity-context/"
                "runtimes/subscription-runtime/e904ec95"
            ),
            "MEM0_V5_RUNTIME_REPO": (
                "/mnt/volume_ams3_1784742570542/infinity-context/"
                "runtimes/subscription-runtime/e904ec95/repo"
            ),
            "MEM0_V5_NODE_EXECUTABLE": "/usr/local/bin/node",
            "MEM0_V5_SOURCE_AUTHORITY_MANIFEST_FILE": "/run/source-authority/manifest.json",
            "MEM0_V5_SOURCE_AUTHORITY_MANIFEST_SHA256_FILE": (
                "/run/source-authority-pin/manifest.sha256"
            ),
            "MEM0_V5_PHASE_C_AUTHORITY_DIR": (
                "/mnt/volume_ams3_1784742570542/infinity-context/sources/9499b9c2"
            ),
            "HOME": "/run/mem0-v5-state",
            "XDG_CACHE_HOME": "/run/mem0-v5-state/cache",
            "XDG_CONFIG_HOME": "/run/mem0-v5-state/config",
            "XDG_DATA_HOME": "/run/mem0-v5-state/data",
            "XDG_STATE_HOME": "/run/mem0-v5-state/state",
        },
    }[service]
    if values != expected:
        raise ValueError("e2e_service_environment_invalid")
    healthcheck = config.get("Healthcheck")
    if service == "e2e-network-anchor":
        expected_healthcheck = {
            "Test": ["CMD", "python", "-m", "e2e.readiness", "--once"],
            "Interval": 1_000_000_000,
            "Timeout": 2_000_000_000,
            "Retries": 60,
            "StartPeriod": 1_000_000_000,
        }
        if healthcheck != expected_healthcheck:
            raise ValueError("e2e_service_healthcheck_invalid")
    elif healthcheck not in (None, {}):
        raise ValueError("e2e_service_healthcheck_invalid")


def attest_tmpfs(host: Mapping[str, Any], expected: Mapping[str, tuple[int, str]]) -> None:
    tmpfs = host.get("Tmpfs")
    if not isinstance(tmpfs, Mapping) or set(tmpfs) != set(expected):
        raise ValueError("e2e_service_tmpfs_invalid")
    for target, (size, mode) in expected.items():
        options = tmpfs.get(target)
        if not isinstance(options, str):
            raise ValueError("e2e_service_tmpfs_invalid")
        pairs = [token.split("=", 1) for token in options.split(",")]
        if any(len(pair) != 2 for pair in pairs):
            raise ValueError("e2e_service_tmpfs_invalid")
        values = dict(pairs)
        if (
            len(values) != len(pairs)
            or set(values) != {"size", "mode", "uid", "gid"}
            or _binary_size(values["size"]) != size
            or values["mode"] not in {mode, mode.lstrip("0")}
            or values["uid"] != "65532"
            or values["gid"] != "65532"
        ):
            raise ValueError("e2e_service_tmpfs_invalid")


def _binary_size(value: str) -> int | None:
    match = re.fullmatch(r"([1-9][0-9]*)([kmg]?)", value)
    if match is None:
        return None
    multiplier = {"": 1, "k": 1024, "m": 1024**2, "g": 1024**3}[match.group(2)]
    return int(match.group(1)) * multiplier


class PinnedExecutableAttestor:
    def __init__(
        self,
        *,
        path: Path,
        expected_sha256: str,
        error_type: type[Exception],
        expected_uid: int = 0,
        expected_gid: int = 0,
        allowed_chain_owners: frozenset[tuple[int, int]] = frozenset({(0, 0)}),
        chain_anchor: Path = Path("/"),
    ) -> None:
        self._path = path
        self._expected_sha256 = expected_sha256
        self._error = error_type
        self._owner = (expected_uid, expected_gid)
        self._chain_owners = allowed_chain_owners
        self._chain_anchor = chain_anchor

    def open(self) -> tuple[int, tuple[int, ...]]:
        descriptor = None
        try:
            descriptor = os.open(self._path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
            _attest_immutable_chain(
                self._path.parent,
                leaf_mode=0o555,
                owners=self._chain_owners,
                anchor=self._chain_anchor,
            )
            metadata = os.fstat(descriptor)
            identity = _executable_identity(metadata, self._error, owner=self._owner)
            if _sha256_descriptor(descriptor) != self._expected_sha256:
                raise self._error("e2e_node_executable_invalid")
            return descriptor, identity
        except Exception as error:
            if descriptor is not None:
                os.close(descriptor)
            if isinstance(error, self._error):
                raise
            raise self._error("e2e_node_executable_invalid") from None

    def reattest(self, descriptor: int, identity: tuple[int, ...]) -> None:
        try:
            _attest_immutable_chain(
                self._path.parent,
                leaf_mode=0o555,
                owners=self._chain_owners,
                anchor=self._chain_anchor,
            )
            path_metadata = os.lstat(self._path)
            held_metadata = os.fstat(descriptor)
            if (
                _executable_identity(path_metadata, self._error, owner=self._owner) != identity
                or _executable_identity(held_metadata, self._error, owner=self._owner) != identity
                or _sha256_descriptor(descriptor) != self._expected_sha256
            ):
                raise self._error("e2e_node_executable_changed")
        except Exception as error:
            if isinstance(error, self._error):
                raise
            raise self._error("e2e_node_executable_changed") from None


class NodeAttestingExecutor:
    def __init__(self, *, delegate: Any, node_path: Path, error_type: type[Exception]) -> None:
        if node_path != PINNED_NODE:
            raise error_type("e2e_node_path_invalid")
        self._delegate = delegate
        self._attestor = PinnedExecutableAttestor(
            path=node_path,
            expected_sha256=PINNED_NODE_SHA256,
            error_type=error_type,
        )

    def execute(self, *arguments: Any) -> Mapping[str, Any]:
        descriptor, identity = self._attestor.open()
        try:
            self._attestor.reattest(descriptor, identity)
            try:
                return self._delegate.execute(*arguments)
            finally:
                self._attestor.reattest(descriptor, identity)
        finally:
            os.close(descriptor)


class SourcePinAttestor:
    """Hold and re-attest the immutable external source manifest binding."""

    def __init__(
        self,
        *,
        manifest_path: Path,
        digest_path: Path,
        error_type: type[Exception],
        expected_uid: int = 0,
        expected_gid: int = 0,
        allowed_chain_owners: frozenset[tuple[int, int]] = frozenset({(0, 0)}),
        chain_anchor: Path = Path("/"),
    ) -> None:
        if (
            manifest_path.name != "manifest.json"
            or digest_path.name != "manifest.sha256"
            or manifest_path.parent != digest_path.parent
        ):
            raise error_type("e2e_source_pin_path_invalid")
        self._manifest = manifest_path
        self._digest = digest_path
        self._error = error_type
        self._owner = (expected_uid, expected_gid)
        self._chain_owners = allowed_chain_owners
        self._chain_anchor = chain_anchor

    def open(self) -> tuple[tuple[int, int], tuple[tuple[int, ...], tuple[int, ...]], str]:
        descriptors: list[int] = []
        try:
            _attest_immutable_chain(
                self._manifest.parent,
                leaf_mode=0o555,
                owners=self._chain_owners,
                anchor=self._chain_anchor,
            )
            for path in (self._manifest, self._digest):
                descriptors.append(os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW))
            manifest_fd, digest_fd = descriptors
            manifest_identity = _immutable_file_identity(
                os.fstat(manifest_fd), maximum=8 << 20, owner=self._owner
            )
            digest_identity = _immutable_file_identity(
                os.fstat(digest_fd), maximum=65, owner=self._owner
            )
            digest = _canonical_digest(digest_fd, self._error)
            if _sha256_descriptor(manifest_fd) != digest:
                raise self._error("e2e_source_pin_binding_invalid")
            return (manifest_fd, digest_fd), (manifest_identity, digest_identity), digest
        except Exception as error:
            for descriptor in descriptors:
                os.close(descriptor)
            if isinstance(error, self._error):
                raise
            raise self._error("e2e_source_pin_invalid") from None

    def reattest(
        self,
        descriptors: tuple[int, int],
        identities: tuple[tuple[int, ...], tuple[int, ...]],
        digest: str,
    ) -> None:
        try:
            _attest_immutable_chain(
                self._manifest.parent,
                leaf_mode=0o555,
                owners=self._chain_owners,
                anchor=self._chain_anchor,
            )
            for path, descriptor, identity, maximum in zip(
                (self._manifest, self._digest),
                descriptors,
                identities,
                (8 << 20, 65),
                strict=True,
            ):
                if (
                    _immutable_file_identity(os.lstat(path), maximum=maximum, owner=self._owner)
                    != identity
                    or _immutable_file_identity(
                        os.fstat(descriptor), maximum=maximum, owner=self._owner
                    )
                    != identity
                ):
                    raise self._error("e2e_source_pin_changed")
            if _canonical_digest(descriptors[1], self._error) != digest:
                raise self._error("e2e_source_pin_changed")
            if _sha256_descriptor(descriptors[0]) != digest:
                raise self._error("e2e_source_pin_changed")
        except Exception as error:
            if isinstance(error, self._error):
                raise
            raise self._error("e2e_source_pin_changed") from None


class SourcePinAttestingExecutor:
    def __init__(
        self,
        *,
        delegate: Any,
        manifest_path: Path,
        digest_path: Path,
        error_type: type[Exception],
        expected_uid: int = 0,
        expected_gid: int = 0,
        allowed_chain_owners: frozenset[tuple[int, int]] = frozenset({(0, 0)}),
        chain_anchor: Path = Path("/"),
    ) -> None:
        self._delegate = delegate
        self._attestor = SourcePinAttestor(
            manifest_path=manifest_path,
            digest_path=digest_path,
            error_type=error_type,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
            allowed_chain_owners=allowed_chain_owners,
            chain_anchor=chain_anchor,
        )

    def execute(self, *arguments: Any) -> Mapping[str, Any]:
        descriptors, identities, digest = self._attestor.open()
        try:
            self._attestor.reattest(descriptors, identities, digest)
            try:
                return self._delegate.execute(*arguments)
            finally:
                self._attestor.reattest(descriptors, identities, digest)
        finally:
            for descriptor in descriptors:
                os.close(descriptor)


class PrivateDirectoryAttestor:
    """Bind one prepare-owned mutable directory without trusting environment input."""

    def __init__(
        self,
        *,
        run_root: Path,
        path: Path,
        expected_uid: int,
        expected_gid: int,
        error_type: type[Exception],
    ) -> None:
        parent = run_root / "state"
        if path != parent / "e2e-mem0-config":
            raise error_type("e2e_child_mem0_dir_invalid")
        self._parent = parent
        self._path = path
        self._owner = (expected_uid, expected_gid)
        self._error = error_type

    def open(self) -> tuple[tuple[int, int], tuple[tuple[int, ...], tuple[int, ...]]]:
        descriptors: list[int] = []
        try:
            parent_fd = os.open(
                self._parent,
                os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_DIRECTORY,
            )
            descriptors.append(parent_fd)
            parent_identity = _private_directory_identity(os.fstat(parent_fd), self._owner)
            child_fd = os.open(
                "e2e-mem0-config",
                os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_DIRECTORY,
                dir_fd=parent_fd,
            )
            descriptors.append(child_fd)
            child_identity = _private_directory_identity(os.fstat(child_fd), self._owner)
            self.reattest((parent_fd, child_fd), (parent_identity, child_identity))
            return (parent_fd, child_fd), (parent_identity, child_identity)
        except Exception as error:
            for descriptor in descriptors:
                os.close(descriptor)
            if isinstance(error, self._error):
                raise
            raise self._error("e2e_child_mem0_dir_invalid") from None

    def reattest(
        self,
        descriptors: tuple[int, int],
        identities: tuple[tuple[int, ...], tuple[int, ...]],
    ) -> None:
        parent_fd, child_fd = descriptors
        parent_identity, child_identity = identities
        try:
            live_parent = os.lstat(self._parent)
            live_child = os.stat("e2e-mem0-config", dir_fd=parent_fd, follow_symlinks=False)
            if (
                _private_directory_identity(live_parent, self._owner) != parent_identity
                or _private_directory_identity(os.fstat(parent_fd), self._owner) != parent_identity
                or _private_directory_identity(live_child, self._owner) != child_identity
                or _private_directory_identity(os.fstat(child_fd), self._owner) != child_identity
            ):
                raise self._error("e2e_child_mem0_dir_changed")
        except Exception as error:
            if isinstance(error, self._error):
                raise
            raise self._error("e2e_child_mem0_dir_changed") from None


class PrivateDirectoryAttestingExecutor:
    def __init__(self, *, delegate: Any, attestor: PrivateDirectoryAttestor) -> None:
        self._delegate = delegate
        self._attestor = attestor

    def execute(self, *arguments: Any) -> Mapping[str, Any]:
        descriptors, identities = self._attestor.open()
        try:
            self._attestor.reattest(descriptors, identities)
            try:
                return self._delegate.execute(*arguments)
            finally:
                self._attestor.reattest(descriptors, identities)
        finally:
            for descriptor in descriptors:
                os.close(descriptor)


def build_e2e_attesting_executor(
    *,
    delegate: Any,
    node_path: Path,
    manifest_path: Path,
    digest_path: Path,
    run_root: Path,
    expected_uid: int,
    expected_gid: int,
    error_type: type[Exception],
) -> PrivateDirectoryAttestingExecutor:
    immutable = SourcePinAttestingExecutor(
        delegate=NodeAttestingExecutor(
            delegate=delegate, node_path=node_path, error_type=error_type
        ),
        manifest_path=manifest_path,
        digest_path=digest_path,
        error_type=error_type,
    )
    return PrivateDirectoryAttestingExecutor(
        delegate=immutable,
        attestor=PrivateDirectoryAttestor(
            run_root=run_root,
            path=run_root / "state" / "e2e-mem0-config",
            expected_uid=expected_uid,
            expected_gid=expected_gid,
            error_type=error_type,
        ),
    )


def _private_directory_identity(
    metadata: os.stat_result, owner: tuple[int, int]
) -> tuple[int, ...]:
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or (metadata.st_uid, metadata.st_gid) != owner
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise ValueError("private_directory_invalid")
    return metadata.st_dev, metadata.st_ino, metadata.st_uid, metadata.st_gid, 0o700


def _immutable_file_identity(
    metadata: os.stat_result, *, maximum: int, owner: tuple[int, int] = (0, 0)
) -> tuple[int, ...]:
    if (
        not stat.S_ISREG(metadata.st_mode)
        or (metadata.st_uid, metadata.st_gid) != owner
        or stat.S_IMODE(metadata.st_mode) != 0o444
        or metadata.st_nlink != 1
        or not 1 <= metadata.st_size <= maximum
    ):
        raise ValueError("immutable_file_invalid")
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
        metadata.st_uid,
        metadata.st_gid,
        stat.S_IMODE(metadata.st_mode),
        metadata.st_nlink,
    )


def _canonical_digest(descriptor: int, error_type: type[Exception]) -> str:
    os.lseek(descriptor, 0, os.SEEK_SET)
    raw = os.read(descriptor, 65)
    try:
        value = raw.decode("ascii")
    except UnicodeDecodeError:
        raise error_type("e2e_source_pin_digest_invalid") from None
    if len(raw) != 64 or _SHA256.fullmatch(value) is None:
        raise error_type("e2e_source_pin_digest_invalid")
    return value


def _attest_immutable_chain(
    path: Path,
    *,
    leaf_mode: int,
    owners: frozenset[tuple[int, int]],
    anchor: Path,
) -> None:
    if not path.is_absolute() or not anchor.is_absolute():
        raise ValueError("immutable_path_invalid")
    try:
        relative = path.relative_to(anchor)
    except ValueError:
        raise ValueError("immutable_path_invalid") from None
    current = anchor
    for part in ("", *relative.parts):
        if part:
            current /= part
        metadata = os.lstat(current)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or (metadata.st_uid, metadata.st_gid) not in owners
            or stat.S_IMODE(metadata.st_mode) & 0o022
        ):
            raise ValueError("immutable_path_invalid")
    if stat.S_IMODE(os.lstat(path).st_mode) != leaf_mode:
        raise ValueError("immutable_path_invalid")


def _executable_identity(
    metadata: os.stat_result,
    error_type: type[Exception],
    *,
    owner: tuple[int, int] = (0, 0),
) -> tuple[int, ...]:
    if (
        not stat.S_ISREG(metadata.st_mode)
        or (metadata.st_uid, metadata.st_gid) != owner
        or stat.S_IMODE(metadata.st_mode) != 0o555
        or metadata.st_nlink != 1
    ):
        raise error_type("e2e_node_executable_invalid")
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
        metadata.st_uid,
        metadata.st_gid,
        stat.S_IMODE(metadata.st_mode),
        metadata.st_nlink,
    )


def _sha256_descriptor(descriptor: int) -> str:
    digest = hashlib.sha256()
    os.lseek(descriptor, 0, os.SEEK_SET)
    while chunk := os.read(descriptor, 1024 * 1024):
        digest.update(chunk)
    return digest.hexdigest()


class RootDockerLifecycleHelper:
    """Serve exactly one non-parameterized restart request."""

    def __init__(
        self,
        *,
        channel: socket.socket,
        compose_file: Path,
        project_name: str,
        environment: Mapping[str, str],
        trust_attestor: Callable[[], None],
        run_process: Callable[..., Any] = subprocess.run,
    ) -> None:
        if (
            not compose_file.is_absolute()
            or compose_file.is_symlink()
            or not compose_file.is_file()
            or _PROJECT.fullmatch(project_name) is None
        ):
            raise ValueError("e2e_root_lifecycle_configuration_invalid")
        self._channel = channel
        self._compose = compose_file
        self._project = project_name
        self._environment = _docker_environment(environment)
        self._attest_trust = trust_attestor
        self._run = run_process

    def serve_once(self) -> bool:
        try:
            self._channel.settimeout(75)
            request = _read_one_request(self._channel)
            if request != REQUEST:
                self._reply(FAILURE)
                return False
            base = [
                PINNED_DOCKER,
                "compose",
                "-p",
                self._project,
                "-f",
                str(self._compose),
            ]
            self._command([*base, "kill", "--signal", "KILL", "mem0-oss-adapter-v5"])
            self._command([*base, "start", "mem0-oss-adapter-v5"])
            self._reply(SUCCESS)
            return True
        except Exception:
            self._reply(FAILURE)
            return False
        finally:
            self._channel.close()

    def _command(self, command: list[str]) -> None:
        self._attest_trust()
        self._run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=60,
            check=True,
            env=self._environment,
        )

    def _reply(self, value: bytes) -> None:
        try:
            self._channel.sendall(value)
            self._channel.shutdown(socket.SHUT_WR)
        except OSError:
            pass


class ProcessNamespaceAttestor:
    def __init__(
        self,
        *,
        error_type: type[Exception],
        proc_root: Path = Path("/proc"),
        pidfd_opener: Any = None,
    ) -> None:
        self._error = error_type
        self._proc_root = proc_root
        self._pidfd_opener = pidfd_opener or getattr(os, "pidfd_open", None)

    def open(self, anchor: Any) -> tuple[int, int, tuple[int, str, int, int]]:
        pidfd = None
        netfd = None
        try:
            if self._pidfd_opener is None:
                raise self._error("e2e_pidfd_unavailable")
            pidfd = self._pidfd_opener(anchor.pid, 0)
            process_root = self._proc_root / str(anchor.pid)
            starttime = _proc_starttime(process_root, self._error)
            if anchor.container_id not in (process_root / "cgroup").read_text():
                raise self._error("e2e_anchor_cgroup_invalid")
            netfd = os.open(process_root / "ns" / "net", os.O_RDONLY | os.O_CLOEXEC)
            metadata = os.fstat(netfd)
            identity = (anchor.pid, starttime, metadata.st_dev, metadata.st_ino)
            self.reattest(pidfd, netfd, identity, anchor.container_id)
            return pidfd, netfd, identity
        except Exception as error:
            if netfd is not None:
                os.close(netfd)
            if pidfd is not None:
                os.close(pidfd)
            if isinstance(error, self._error):
                raise
            raise self._error("e2e_anchor_process_invalid") from None

    def reattest(
        self,
        pidfd: int,
        netfd: int,
        identity: tuple[int, str, int, int],
        container_id: str,
    ) -> None:
        pid, starttime, device, inode = identity
        poller = selectors.PollSelector()
        try:
            poller.register(pidfd, selectors.EVENT_READ)
            if poller.select(0):
                raise self._error("e2e_anchor_process_exited")
        finally:
            poller.close()
        try:
            process_root = self._proc_root / str(pid)
            live = os.stat(process_root / "ns" / "net")
            held = os.fstat(netfd)
            cgroup = (process_root / "cgroup").read_text()
        except Exception:
            raise self._error("e2e_anchor_process_invalid") from None
        if (
            _proc_starttime(process_root, self._error) != starttime
            or container_id not in cgroup
            or (live.st_dev, live.st_ino) != (device, inode)
            or (held.st_dev, held.st_ino) != (device, inode)
        ):
            raise self._error("e2e_anchor_process_changed")


def _proc_starttime(process_root: Path, error_type: type[Exception]) -> str:
    try:
        value = (process_root / "stat").read_text()
        return value[value.rfind(")") + 2 :].split()[19]
    except Exception:
        raise error_type("e2e_anchor_process_invalid") from None


def _read_one_request(channel: socket.socket) -> bytes:
    value = bytearray()
    while len(value) <= len(REQUEST):
        chunk = channel.recv(len(REQUEST) + 1 - len(value))
        if not chunk:
            break
        value.extend(chunk)
        if b"\n" in value:
            extra = channel.recv(1)
            if extra:
                value.extend(extra)
            break
    return bytes(value)


def _docker_environment(source: Mapping[str, str]) -> dict[str, str]:
    result = {
        "DOCKER_HOST": PINNED_DOCKER_HOST,
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
    }
    for name in _PATH_ENVIRONMENT:
        value = source.get(name)
        if value is None or not Path(value).is_absolute() or "\x00" in value or "\n" in value:
            raise ValueError("e2e_root_lifecycle_environment_invalid")
        result[name] = value
    return result

"""Strict immutable readback of host-side runtime attestations."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import stat
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from .docker_cli import SERVICES
from .immutable_evidence import (
    ImmutableJsonEvidence,
    read_immutable_json,
    require_immutable_json_unchanged,
)
from .runtime_attestation import (
    ATTESTATION_FILE_PREFIX,
    ATTESTATION_HMAC_DOMAIN,
    ATTESTATION_SCHEMA,
)

_RUNTIME_ATTESTATION_SECRET_NAME: Final = "runtime-attestation-secret"
_MIN_AUTHENTICATION_KEY_BYTES: Final = 32
_MAX_AUTHENTICATION_KEY_BYTES: Final = 4096

_TOP_LEVEL_KEYS = {
    "account_i_fence_commitment_sha256",
    "adapter_image_id",
    "attestation_hmac_sha256",
    "anchor_container_inventory_sha256",
    "anchor_netns",
    "anchor_pidns",
    "bridge_ports",
    "compose_sha256",
    "deployment_inputs_sha256",
    "fleet",
    "host_exposure",
    "observed_at_unix_ns",
    "project_name",
    "qdrant_image_id",
    "qdrant_ports",
    "relay_reachability_sha256",
    "schema_version",
    "secret_cross_wire_sha256",
    "services",
    "socket_bindings_sha256",
}
_FLEET_KEYS = {
    "bridges",
    "fleet_readiness_sha256",
    "pool_authority_sha256",
    "requested_mode",
}
_BRIDGE_KEYS = {
    "account_name",
    "bridge_id",
    "controller_pid",
    "generation",
    "launch_mode",
    "process",
    "readiness_receipt_sha256",
    "runtime_authority_sha256",
}


class AcceptanceAttestationError(RuntimeError):
    """Stable failure for invalid lifecycle attestation evidence."""


@dataclass(frozen=True, slots=True)
class BridgeLifecycleEvidence:
    account_name: str
    bridge_id: str
    generation: int
    launch_mode: str
    runtime_authority_sha256: str

    def stable_identity(self) -> tuple[str, str, str]:
        return (
            self.account_name,
            self.bridge_id,
            self.runtime_authority_sha256,
        )


@dataclass(frozen=True, slots=True)
class RuntimeAttestationReadback:
    immutable: ImmutableJsonEvidence
    project_name: str
    fleet_mode: str
    deployment_inputs_sha256: str
    bind_mounts: tuple[tuple[str, str], ...]
    bridges: tuple[BridgeLifecycleEvidence, BridgeLifecycleEvidence, BridgeLifecycleEvidence]

    @property
    def commitment_sha256(self) -> str:
        return self.immutable.commitment_sha256

    @property
    def path(self) -> Path:
        return self.immutable.path


def read_runtime_attestation(
    *,
    path: Path,
    directory: Path,
    authentication_key_file: Path,
    expected_project: str,
    expected_mode: str,
    expected_commitment: str,
    expected_uid: int,
    expected_gid: int,
) -> RuntimeAttestationReadback:
    """Authenticate canonical bytes plus the exact project and lifecycle mode."""

    if (
        expected_mode not in {"create", "reopen"}
        or not _sha256(expected_commitment)
        or type(expected_uid) is not int
        or expected_uid < 0
        or type(expected_gid) is not int
        or expected_gid < 0
    ):
        _fail("publishable_acceptance_attestation_input_invalid")
    immutable = read_immutable_json(
        path=path,
        directory=directory,
        prefix=ATTESTATION_FILE_PREFIX,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    if immutable.commitment_sha256 != expected_commitment:
        _fail("publishable_acceptance_attestation_commitment_mismatch")
    payload = immutable.payload
    if (
        set(payload) != _TOP_LEVEL_KEYS
        or payload.get("schema_version") != ATTESTATION_SCHEMA
        or payload.get("project_name") != expected_project
        or not all(
            _sha256(payload.get(key))
            for key in (
                "attestation_hmac_sha256",
                "deployment_inputs_sha256",
                "relay_reachability_sha256",
                "socket_bindings_sha256",
            )
        )
    ):
        _fail("publishable_acceptance_attestation_invalid")
    _authenticate_payload(
        payload,
        authentication_key_file=authentication_key_file,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    services = payload.get("services")
    if type(services) is not dict or set(services) != set(SERVICES):
        _fail("publishable_acceptance_attestation_services_invalid")
    bind_mounts: list[tuple[str, str]] = []
    for service in SERVICES:
        item = services.get(service)
        if type(item) is not dict or set(item) != {
            "bind_mounts_sha256",
            "container_id",
            "image_id",
            "pid",
        }:
            _fail("publishable_acceptance_attestation_services_invalid")
        binding = item.get("bind_mounts_sha256")
        if not _sha256(binding):
            _fail("publishable_acceptance_attestation_services_invalid")
        bind_mounts.append((service, binding))
    fleet = payload.get("fleet")
    if (
        type(fleet) is not dict
        or set(fleet) != _FLEET_KEYS
        or fleet.get("requested_mode") != expected_mode
    ):
        _fail("publishable_acceptance_attestation_fleet_invalid")
    raw_bridges = fleet.get("bridges")
    if type(raw_bridges) is not list or len(raw_bridges) != 3:
        _fail("publishable_acceptance_attestation_fleet_invalid")
    bridges = tuple(_bridge(item, expected_mode=expected_mode) for item in raw_bridges)
    if (
        len({item.account_name for item in bridges}) != 3
        or len({item.bridge_id for item in bridges}) != 3
    ):
        _fail("publishable_acceptance_attestation_fleet_invalid")
    return RuntimeAttestationReadback(
        immutable=immutable,
        project_name=expected_project,
        fleet_mode=expected_mode,
        deployment_inputs_sha256=payload["deployment_inputs_sha256"],  # type: ignore[arg-type]
        bind_mounts=tuple(bind_mounts),
        bridges=bridges,  # type: ignore[arg-type]
    )


def require_runtime_attestation_unchanged(
    evidence: RuntimeAttestationReadback,
    *,
    directory: Path,
    authentication_key_file: Path,
    expected_uid: int,
    expected_gid: int,
) -> RuntimeAttestationReadback:
    """Re-read a prior runtime attestation and reject replacement or mutation."""

    if type(evidence) is not RuntimeAttestationReadback:
        _fail("publishable_acceptance_attestation_input_invalid")
    require_immutable_json_unchanged(
        evidence.immutable,
        directory=directory,
        prefix=ATTESTATION_FILE_PREFIX,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    observed = read_runtime_attestation(
        path=evidence.path,
        directory=directory,
        authentication_key_file=authentication_key_file,
        expected_project=evidence.project_name,
        expected_mode=evidence.fleet_mode,
        expected_commitment=evidence.commitment_sha256,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    if observed != evidence:
        _fail("publishable_acceptance_attestation_changed")
    return observed


def _bridge(value: object, *, expected_mode: str) -> BridgeLifecycleEvidence:
    if type(value) is not dict or set(value) != _BRIDGE_KEYS:
        _fail("publishable_acceptance_attestation_bridge_invalid")
    account_name = value.get("account_name")
    bridge_id = value.get("bridge_id")
    generation = value.get("generation")
    launch_mode = value.get("launch_mode")
    authority = value.get("runtime_authority_sha256")
    if (
        not isinstance(account_name, str)
        or not account_name
        or not isinstance(bridge_id, str)
        or not bridge_id
        or type(generation) is not int
        or generation < 1
        or launch_mode != expected_mode
        or not _sha256(authority)
    ):
        _fail("publishable_acceptance_attestation_bridge_invalid")
    return BridgeLifecycleEvidence(
        account_name=account_name,
        bridge_id=bridge_id,
        generation=generation,
        launch_mode=launch_mode,
        runtime_authority_sha256=authority,
    )


def _authenticate_payload(
    payload: dict[str, object],
    *,
    authentication_key_file: Path,
    expected_uid: int,
    expected_gid: int,
) -> None:
    signed = dict(payload)
    presented = signed.pop("attestation_hmac_sha256")
    key = _read_runtime_authentication_key(
        authentication_key_file,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    try:
        expected = hmac.new(
            key,
            ATTESTATION_HMAC_DOMAIN + _canonical_json(signed),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, presented):
            _fail("publishable_acceptance_attestation_authentication_invalid")
    finally:
        _wipe(key)


def _read_runtime_authentication_key(
    path: Path,
    *,
    expected_uid: int,
    expected_gid: int,
) -> bytearray:
    if (
        not isinstance(path, Path)
        or not path.is_absolute()
        or Path(os.path.normpath(path)) != path
        or path.name != _RUNTIME_ATTESTATION_SECRET_NAME
    ):
        _fail("publishable_acceptance_attestation_key_path_invalid")
    directory = path.parent
    directory_descriptor: int | None = None
    key_descriptor: int | None = None
    key = bytearray()
    verification = bytearray()
    completed = False
    try:
        nofollow = getattr(os, "O_NOFOLLOW", None)
        directory_flag = getattr(os, "O_DIRECTORY", None)
        cloexec = getattr(os, "O_CLOEXEC", None)
        nonblock = getattr(os, "O_NONBLOCK", None)
        if None in {nofollow, directory_flag, cloexec, nonblock}:
            _fail("publishable_acceptance_attestation_key_unavailable")
        if directory.resolve(strict=True) != directory or path.resolve(strict=True) != path:
            _fail("publishable_acceptance_attestation_key_unsafe")
        directory_before = directory.lstat()
        directory_descriptor = os.open(
            directory,
            os.O_RDONLY | directory_flag | cloexec | nofollow,
        )
        directory_opened = os.fstat(directory_descriptor)
        directory_after_open = directory.lstat()
        directory_identity = _directory_identity(directory_opened)
        if (
            _directory_identity(directory_before) != directory_identity
            or _directory_identity(directory_after_open) != directory_identity
            or not _private_directory(
                directory_opened,
                expected_uid=expected_uid,
                expected_gid=expected_gid,
            )
        ):
            _fail("publishable_acceptance_attestation_key_directory_unsafe")

        before = os.stat(path.name, dir_fd=directory_descriptor, follow_symlinks=False)
        key_descriptor = os.open(
            path.name,
            os.O_RDONLY | cloexec | nonblock | nofollow,
            dir_fd=directory_descriptor,
        )
        opened = os.fstat(key_descriptor)
        after_open = os.stat(path.name, dir_fd=directory_descriptor, follow_symlinks=False)
        snapshot = _file_identity(opened)
        if (
            _file_identity(before) != snapshot
            or _file_identity(after_open) != snapshot
            or not _private_file(opened, expected_uid=expected_uid, expected_gid=expected_gid)
            or not _MIN_AUTHENTICATION_KEY_BYTES <= opened.st_size <= _MAX_AUTHENTICATION_KEY_BYTES
        ):
            _fail("publishable_acceptance_attestation_key_unsafe")

        _read_bounded(key_descriptor, key)
        first_final = os.fstat(key_descriptor)
        os.lseek(key_descriptor, 0, os.SEEK_SET)
        _read_bounded(key_descriptor, verification)
        final = os.fstat(key_descriptor)
        after = os.stat(path.name, dir_fd=directory_descriptor, follow_symlinks=False)
        directory_final = os.fstat(directory_descriptor)
        directory_current = directory.lstat()
        if (
            len(key) != opened.st_size
            or _file_identity(first_final) != snapshot
            or _file_identity(final) != snapshot
            or _file_identity(after) != snapshot
            or not hmac.compare_digest(key, verification)
            or _directory_identity(directory_final) != directory_identity
            or _directory_identity(directory_current) != directory_identity
            or directory.resolve(strict=True) != directory
            or path.resolve(strict=True) != path
        ):
            _fail("publishable_acceptance_attestation_key_changed")
        try:
            text = key.decode("utf-8")
        except UnicodeDecodeError:
            _fail("publishable_acceptance_attestation_key_invalid")
        if not text or text != text.strip():
            _fail("publishable_acceptance_attestation_key_invalid")
        completed = True
        return key
    except AcceptanceAttestationError:
        raise
    except OSError as exc:
        raise AcceptanceAttestationError(
            "publishable_acceptance_attestation_key_unavailable"
        ) from exc
    finally:
        _wipe(verification)
        if not completed:
            _wipe(key)
        if key_descriptor is not None:
            with suppress(OSError):
                os.close(key_descriptor)
        if directory_descriptor is not None:
            with suppress(OSError):
                os.close(directory_descriptor)


def _read_bounded(descriptor: int, target: bytearray) -> None:
    while len(target) <= _MAX_AUTHENTICATION_KEY_BYTES:
        chunk = os.read(
            descriptor,
            min(4096, _MAX_AUTHENTICATION_KEY_BYTES + 1 - len(target)),
        )
        if not chunk:
            return
        target.extend(chunk)
    _fail("publishable_acceptance_attestation_key_changed")


def _private_directory(
    value: os.stat_result,
    *,
    expected_uid: int,
    expected_gid: int,
) -> bool:
    return (
        stat.S_ISDIR(value.st_mode)
        and (value.st_uid, value.st_gid) == (expected_uid, expected_gid)
        and stat.S_IMODE(value.st_mode) == 0o700
    )


def _private_file(
    value: os.stat_result,
    *,
    expected_uid: int,
    expected_gid: int,
) -> bool:
    return (
        stat.S_ISREG(value.st_mode)
        and value.st_nlink == 1
        and (value.st_uid, value.st_gid) == (expected_uid, expected_gid)
        and stat.S_IMODE(value.st_mode) == 0o600
    )


def _directory_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_uid,
        value.st_gid,
        value.st_nlink,
    )


def _file_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_uid,
        value.st_gid,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")


def _wipe(value: bytearray) -> None:
    value[:] = b"\0" * len(value)


def _sha256(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _fail(code: str) -> None:
    raise AcceptanceAttestationError(code)


__all__ = (
    "AcceptanceAttestationError",
    "BridgeLifecycleEvidence",
    "RuntimeAttestationReadback",
    "read_runtime_attestation",
    "require_runtime_attestation_unchanged",
)

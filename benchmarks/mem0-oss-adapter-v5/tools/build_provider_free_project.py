"""Build exactly one acceptance-only provider-free project lane config."""

from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from publishable_mem0_v5.config import (
    PINNED_DOCKER_HOST,
    PROTECTED_ACCOUNT_I_AUTH_ROOT,
    PROTECTED_R16_ROOT,
    BindMountAuthorityConfig,
    BridgeAccountConfig,
    LanePaths,
    ProjectIsolationAuthority,
    PublishableLaneConfig,
    RuntimeAuthorityConfig,
)


class ProviderFreeProjectBuildError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProviderFreeProjectInputs:
    adapter_image_id: str
    host_adapter_port: int
    bridge_bindings: tuple[str, str, str]
    config_hmac_sha256: str
    deployment_closure_sha256: str
    deployment_closure_hmac_sha256: str
    server_closure_sha256: str
    server_closure_hmac_sha256: str
    codex_executable_sha256: str
    occupied_host_ports: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class ProviderFreeProjectBundle:
    config_path: Path
    acceptance: tuple[str, ...]

    def payload(self) -> MappingProxyType:
        return MappingProxyType({
            "acceptance": " ".join(self.acceptance),
            "config_path": str(self.config_path),
            "status": "STAGED_PROVIDER_FREE_ACCEPTANCE_ONLY",
        })


def build_provider_free_project_bundle(
    *, project_name: str, output_root: Path, authority_root: Path,
    inputs: ProviderFreeProjectInputs,
) -> ProviderFreeProjectBundle:
    if re.fullmatch(r"mem0-v5-publishable-[a-z0-9][a-z0-9-]{5,63}", project_name) is None:
        raise ProviderFreeProjectBuildError("provider_free_project_name_invalid")
    if (
        not output_root.is_absolute()
        or not authority_root.is_absolute()
        or Path(os.path.normpath(output_root)) != output_root
        or Path(os.path.normpath(authority_root)) != authority_root
    ):
        raise ProviderFreeProjectBuildError("provider_free_project_path_invalid")
    _validate_inputs(inputs)
    if _overlap(output_root, authority_root) or any(
        _overlap(item, protected) for item in (output_root, authority_root)
        for protected in (PROTECTED_ACCOUNT_I_AUTH_ROOT, PROTECTED_R16_ROOT)
    ):
        raise ProviderFreeProjectBuildError("provider_free_project_path_collision")
    _require_safe_prospective_directory(output_root)
    if output_root.exists() or output_root.is_symlink():
        raise ProviderFreeProjectBuildError("provider_free_project_output_exists")
    _require_safe_existing_directory(authority_root)
    if inputs.host_adapter_port in inputs.occupied_host_ports:
        raise ProviderFreeProjectBuildError("provider_free_project_port_collision")
    lane_root = output_root / project_name
    private = {name: lane_root / name for name in (
        "input", "adapter-state", "qdrant-state", "adapter-secrets",
        "fleet-state", "fleet-auth", "attestation",
    )}
    paths = LanePaths(
        run_root=lane_root, input_dir=private["input"],
        adapter_state_dir=private["adapter-state"], qdrant_state_dir=private["qdrant-state"],
        adapter_secret_dir=private["adapter-secrets"], fleet_state_dir=private["fleet-state"],
        fleet_auth_dir=private["fleet-auth"], attestation_dir=private["attestation"],
        phase_c_authority_dir=authority_root / "phase-c",
        source_authority_dir=authority_root / "source",
        source_authority_pin_dir=authority_root / "source-pin",
        source_authority_pin_sha256_file=authority_root / "source-pin/manifest.sha256",
        server_package_dir=authority_root / "server", deployment_dir=authority_root / "deployment",
    )
    runtime = RuntimeAuthorityConfig(
        runtime_root=authority_root / "runtime",
        runtime_artifact_manifest_sha256="789018b5b15a1299252895babdc550c3d5322c54a1d9c82656f93d31423a0850",
        runtime_entrypoint_sha256="83db85671ec5da675706c903e5b8ed1ae0cb307014d7c10a10be34f1700762fd",
        node_executable=authority_root / "bin/node",
        node_executable_sha256="b2959781cc5a74c357ffa02367efa8a0330cbb1c9cb347732fdfaaaca381cbcd",
        codex_executable=authority_root / "bin/codex",
        codex_executable_sha256=inputs.codex_executable_sha256,
    )
    config = PublishableLaneConfig(
        project_name=project_name, adapter_image_id=inputs.adapter_image_id,
        host_adapter_port=inputs.host_adapter_port, docker_host=PINNED_DOCKER_HOST,
        source_manifest_sha256="4293c131829fc9bdf56b5bf77459c0ec528f99ebb898ba27553f718301788d79",
        bind_mount_authority=BindMountAuthorityConfig(
            config_hmac_sha256=inputs.config_hmac_sha256,
            deployment_closure_sha256=inputs.deployment_closure_sha256,
            deployment_closure_hmac_sha256=inputs.deployment_closure_hmac_sha256,
            server_closure_sha256=inputs.server_closure_sha256,
            server_closure_hmac_sha256=inputs.server_closure_hmac_sha256,
        ), paths=paths, runtime=runtime,
        bridges=tuple(BridgeAccountConfig(
            account_name=f"provider-free-{letter}", bridge_id=f"{project_name}-bridge-{letter}",
            account_binding_hmac_sha256=binding,
        ) for letter, binding in zip("abc", inputs.bridge_bindings, strict=True)),
        project_isolation_authority=ProjectIsolationAuthority(
            inventory_scope="project", project_name=project_name, docker_host=PINNED_DOCKER_HOST,
            pid_mode="private", daemon_global_observation=False, host_process_observation=False,
        ),
    )
    for directory in (output_root, lane_root, *private.values()):
        _ensure_private_directory(directory)
    path = output_root / "provider-free-project.json"
    _write_once(path, config.public_payload())
    command = ("infinity-context-publishable-mem0-v5", "acceptance", "--config", str(path),
               "--inventory-scope", "project", "--project-name", project_name,
               "--docker-host", PINNED_DOCKER_HOST)
    return ProviderFreeProjectBundle(config_path=path, acceptance=command)


def _ensure_private_directory(path: Path) -> None:
    try:
        if path.exists():
            value = path.lstat()
            if stat.S_ISLNK(value.st_mode) or not stat.S_ISDIR(value.st_mode):
                raise ProviderFreeProjectBuildError("provider_free_project_directory_unsafe")
        else:
            path.mkdir(mode=0o700)
        path.chmod(0o700)
    except OSError as exc:
        raise ProviderFreeProjectBuildError("provider_free_project_directory_unavailable") from exc


def _write_once(path: Path, value: object) -> None:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(descriptor, "wb") as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
    except OSError as exc:
        raise ProviderFreeProjectBuildError("provider_free_project_output_collision") from exc


def _overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def _require_safe_existing_directory(path: Path) -> None:
    try:
        current = path
        while True:
            value = current.lstat()
            if stat.S_ISLNK(value.st_mode):
                raise ProviderFreeProjectBuildError("provider_free_project_authority_unsafe")
            if current == current.parent:
                break
            current = current.parent
        if not path.is_dir() or path.resolve(strict=True) != path:
            raise ProviderFreeProjectBuildError("provider_free_project_authority_unsafe")
    except OSError as exc:
        raise ProviderFreeProjectBuildError("provider_free_project_authority_unavailable") from exc


def _require_safe_prospective_directory(path: Path) -> None:
    parent = path.parent
    _require_safe_existing_directory(parent)
    resolved = parent.resolve(strict=True) / path.name
    if resolved != path or any(
        _overlap(resolved, protected)
        for protected in (PROTECTED_ACCOUNT_I_AUTH_ROOT, PROTECTED_R16_ROOT)
    ):
        raise ProviderFreeProjectBuildError("provider_free_project_output_unsafe")


def _validate_inputs(inputs: ProviderFreeProjectInputs) -> None:
    if type(inputs) is not ProviderFreeProjectInputs:
        raise ProviderFreeProjectBuildError("provider_free_project_inputs_invalid")
    sha = re.compile(r"[0-9a-f]{64}\Z")
    if re.fullmatch(r"sha256:[0-9a-f]{64}", inputs.adapter_image_id) is None:
        raise ProviderFreeProjectBuildError("provider_free_project_image_invalid")
    if (
        type(inputs.host_adapter_port) is not int
        or not 1024 <= inputs.host_adapter_port <= 65535
        or inputs.host_adapter_port in {6334, 6335, 8891, 8892, 8893, 19091, 19191}
        or type(inputs.bridge_bindings) is not tuple
        or len(inputs.bridge_bindings) != 3
        or len(set(inputs.bridge_bindings)) != 3
    ):
        raise ProviderFreeProjectBuildError("provider_free_project_inputs_invalid")
    values = (
        *inputs.bridge_bindings,
        inputs.config_hmac_sha256,
        inputs.deployment_closure_sha256,
        inputs.deployment_closure_hmac_sha256,
        inputs.server_closure_sha256,
        inputs.server_closure_hmac_sha256,
        inputs.codex_executable_sha256,
    )
    if any(type(value) is not str or sha.fullmatch(value) is None for value in values):
        raise ProviderFreeProjectBuildError("provider_free_project_digest_invalid")
    if (
        type(inputs.occupied_host_ports) is not tuple
        or len(set(inputs.occupied_host_ports)) != len(inputs.occupied_host_ports)
        or any(
            type(port) is not int or not 1024 <= port <= 65535
            for port in inputs.occupied_host_ports
        )
    ):
        raise ProviderFreeProjectBuildError("provider_free_project_occupied_ports_invalid")


__all__ = (
    "ProviderFreeProjectBuildError",
    "ProviderFreeProjectBundle",
    "ProviderFreeProjectInputs",
    "build_provider_free_project_bundle",
)

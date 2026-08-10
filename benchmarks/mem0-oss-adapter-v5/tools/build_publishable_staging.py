"""Build secret-free operator staging configs without opening a live runtime.

The builder owns only public configuration material. It does not import the
deployment or publishable-run production roots, inspect /proc, read either
protected account-i/r16 root, create a secrets file, or execute a command.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shlex
import stat
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

if __package__:
    from . import publishable_staging_template as staging_contracts
else:
    import publishable_staging_template as staging_contracts

LANE_CONFIG_SCHEMA = "publishable-mem0-v5-isolated-lane.v2"
RUN_CONFIG_SCHEMA = "memory-comparison-publishable-run-config.v1"
EXPECTED_CASE_COUNT = staging_contracts.EXPECTED_CASE_COUNT
EXPECTED_EVALUATION_CALL_COUNT = staging_contracts.EXPECTED_EVALUATION_CALL_COUNT
EXPECTED_EXTRACTION_OPERATION_COUNT = staging_contracts.EXPECTED_EXTRACTION_OPERATION_COUNT
EXPECTED_TOTAL_CALL_COUNT = staging_contracts.EXPECTED_TOTAL_CALL_COUNT
INTERNAL_LANE_PORTS = staging_contracts.INTERNAL_LANE_PORTS
PROTECTED_ACCOUNT_I_AUTH_ROOT = staging_contracts.PROTECTED_ACCOUNT_I_AUTH_ROOT
PROTECTED_R16_ROOT = staging_contracts.PROTECTED_R16_ROOT
_STATE_FILE_KEYS = staging_contracts.STATE_FILE_KEYS
OperatorStagingError = staging_contracts.OperatorStagingError
StagingPublicInputs = staging_contracts.StagingPublicInputs
StagingTemplate = staging_contracts.StagingTemplate
_require_absolute_path = staging_contracts.require_absolute_path
load_staging_template = staging_contracts.load_staging_template


@dataclass(frozen=True, slots=True)
class StagingCommands:
    start_create: tuple[str, ...]
    attest_create: tuple[str, ...]
    run_2040: tuple[str, ...]
    start_reopen: tuple[str, ...]
    attest_reopen: tuple[str, ...]

    def payload(self) -> dict[str, str]:
        return {
            "attest_create": shlex.join(self.attest_create),
            "attest_reopen": shlex.join(self.attest_reopen),
            "run_2040": shlex.join(self.run_2040),
            "start_create": shlex.join(self.start_create),
            "start_reopen": shlex.join(self.start_reopen),
        }


@dataclass(frozen=True, slots=True)
class StagingBundle:
    output_root: Path
    lane_config_path: Path
    run_private_root: Path
    run_config_path: Path
    secrets_path: Path
    commands: StagingCommands

    def payload(self) -> dict[str, object]:
        return {
            "commands": self.commands.payload(),
            "lane_config_path": str(self.lane_config_path),
            "run_2040_config_path": str(self.run_config_path),
            "run_2040_private_root": str(self.run_private_root),
            "secrets_path_not_created": str(self.secrets_path),
            "status": "STAGED_SECRET_FREE",
        }


def build_staging_bundle(
    *,
    template: StagingTemplate,
    output_root: Path,
    authority_root: Path,
    public_inputs: StagingPublicInputs,
) -> StagingBundle:
    """Create two private-permission public configs and no credential material."""

    if type(template) is not StagingTemplate or type(public_inputs) is not StagingPublicInputs:
        _fail("operator_staging_build_input_invalid")
    _require_absolute_path(output_root, "output_root")
    _require_absolute_path(authority_root, "authority_root")
    if _paths_overlap(output_root, authority_root):
        _fail("operator_staging_authority_path_collision")
    protected = (PROTECTED_ACCOUNT_I_AUTH_ROOT, PROTECTED_R16_ROOT)
    if any(
        _paths_overlap(candidate, protected_path)
        for candidate in (output_root, authority_root)
        for protected_path in protected
    ):
        _fail("operator_staging_protected_path_collision")

    required_ports = set(template.required_protected_host_ports)
    protected_ports = set(public_inputs.account_i_protected_host_ports)
    if not required_ports.issubset(protected_ports):
        _fail("operator_staging_r16_ports_incomplete")
    forbidden_ports = {
        *INTERNAL_LANE_PORTS,
        *protected_ports,
        *public_inputs.occupied_host_ports,
        public_inputs.account_i_port,
    }
    if template.host_adapter_port in forbidden_ports:
        _fail("operator_staging_host_port_collision")

    lane_root = output_root / template.project_name
    run_root = output_root / template.run_private_root_name
    lane_config_path = output_root / template.lane_config_file_name
    run_config_path = run_root / template.run_config_file_name
    secrets_path = run_root / template.run_secrets_file_name
    private_paths = {
        key: lane_root / name for key, name in template.private_directory_names.items()
    }
    run_state_root = run_root / template.run_state_directory_name
    run_state_paths = {
        key: run_state_root / name for key, name in template.run_state_file_names.items()
    }
    authority_paths = {key: authority_root / name for key, name in template.authority_names.items()}
    source_pin_file = authority_paths["source_authority_pin_dir"] / "manifest.sha256"

    all_named_paths = (
        lane_root,
        run_root,
        lane_config_path,
        run_config_path,
        secrets_path,
        *private_paths.values(),
        run_state_root,
        *run_state_paths.values(),
        *authority_paths.values(),
        source_pin_file,
    )
    if len(set(all_named_paths)) != len(all_named_paths):
        _fail("operator_staging_path_collision")
    if any(
        _paths_overlap(private, authority)
        for private in (output_root, *private_paths.values(), run_root, run_state_root)
        for authority in authority_paths.values()
    ):
        _fail("operator_staging_authority_path_collision")

    lane_payload = _lane_payload(
        template=template,
        public_inputs=public_inputs,
        lane_root=lane_root,
        private_paths=private_paths,
        authority_paths=authority_paths,
        source_pin_file=source_pin_file,
    )
    run_payload = _run_payload(
        template=template,
        lane_root=lane_root,
        run_state_paths=run_state_paths,
    )
    _validate_lane_payload(lane_payload, template=template, public_inputs=public_inputs)
    _validate_run_payload(run_payload, run_root=run_root)

    private_directories = (
        output_root,
        lane_root,
        *private_paths.values(),
        run_root,
        run_state_root,
    )
    _preflight_private_directories(private_directories)
    _reject_existing_paths((lane_config_path, run_config_path, secrets_path))
    for directory in private_directories:
        _ensure_private_directory(directory)
    _write_private_json(lane_config_path, lane_payload)
    _write_private_json(run_config_path, run_payload)

    commands = _commands(
        lane_config_path=lane_config_path,
        run_root=run_root,
        run_config_path=run_config_path,
        secrets_path=secrets_path,
    )
    return StagingBundle(
        output_root=output_root,
        lane_config_path=lane_config_path,
        run_private_root=run_root,
        run_config_path=run_config_path,
        secrets_path=secrets_path,
        commands=commands,
    )


def _lane_payload(
    *,
    template: StagingTemplate,
    public_inputs: StagingPublicInputs,
    lane_root: Path,
    private_paths: dict[str, Path],
    authority_paths: dict[str, Path],
    source_pin_file: Path,
) -> dict[str, object]:
    return {
        "account_i_r16_fence": {
            "auth_root": str(template.fence_auth_root),
            "boot_id": public_inputs.account_i_boot_id,
            "container_ids": list(public_inputs.account_i_container_ids),
            "netns_inode": public_inputs.account_i_netns_inode,
            "pid": public_inputs.account_i_pid,
            "port": public_inputs.account_i_port,
            "protected_host_ports": list(public_inputs.account_i_protected_host_ports),
            "start_ticks": public_inputs.account_i_start_ticks,
            "state_root": str(template.fence_state_root),
        },
        "adapter_image_id": public_inputs.adapter_image_id,
        "bind_mount_authority": {
            "config_hmac_sha256": public_inputs.config_hmac_sha256,
            "deployment_closure_hmac_sha256": (public_inputs.deployment_closure_hmac_sha256),
            "deployment_closure_sha256": public_inputs.deployment_closure_sha256,
            "server_closure_hmac_sha256": public_inputs.server_closure_hmac_sha256,
            "server_closure_sha256": public_inputs.server_closure_sha256,
        },
        "bridges": [
            {
                "account_binding_hmac_sha256": binding,
                "account_name": bridge.account_name,
                "bridge_id": bridge.bridge_id,
            }
            for bridge, binding in zip(
                template.bridges,
                public_inputs.bridge_account_binding_sha256,
                strict=True,
            )
        ],
        "docker_host": template.docker_host,
        "host_adapter_port": template.host_adapter_port,
        "paths": {
            **{key: str(path) for key, path in private_paths.items()},
            "deployment_dir": str(authority_paths["deployment_dir"]),
            "phase_c_authority_dir": str(authority_paths["phase_c_authority_dir"]),
            "run_root": str(lane_root),
            "server_package_dir": str(authority_paths["server_package_dir"]),
            "source_authority_dir": str(authority_paths["source_authority_dir"]),
            "source_authority_pin_dir": str(authority_paths["source_authority_pin_dir"]),
            "source_authority_pin_sha256_file": str(source_pin_file),
        },
        "project_name": template.project_name,
        "runtime": {
            "codex_executable": str(authority_paths["codex_executable"]),
            "codex_executable_sha256": public_inputs.codex_executable_sha256,
            "node_executable": str(authority_paths["node_executable"]),
            "node_executable_sha256": template.authority_digests["node_executable_sha256"],
            "runtime_artifact_manifest_sha256": template.authority_digests[
                "runtime_artifact_manifest_sha256"
            ],
            "runtime_entrypoint_sha256": template.authority_digests["runtime_entrypoint_sha256"],
            "runtime_root": str(authority_paths["runtime_root"]),
        },
        "schema_version": LANE_CONFIG_SCHEMA,
        "source_manifest_sha256": template.authority_digests["source_manifest_sha256"],
    }


def _run_payload(
    *,
    template: StagingTemplate,
    lane_root: Path,
    run_state_paths: dict[str, Path],
) -> dict[str, object]:
    return {
        "adapter": {
            "expected_case_count": EXPECTED_CASE_COUNT,
            "expected_evaluation_call_count": EXPECTED_EVALUATION_CALL_COUNT,
            "expected_extraction_operation_count": EXPECTED_EXTRACTION_OPERATION_COUNT,
            "expected_total_call_count": EXPECTED_TOTAL_CALL_COUNT,
            "lane_project_name": template.project_name,
            "public_endpoint": f"http://127.0.0.1:{template.host_adapter_port}",
            "runtime_attestation_directory": str(
                lane_root / template.private_directory_names["attestation_dir"]
            ),
        },
        "dependency_provider": template.dependency_provider,
        "max_dispatches_per_batch": template.max_dispatches_per_batch,
        "publication_key_id": template.publication_key_id,
        "schema_version": RUN_CONFIG_SCHEMA,
        "state": {key: str(path) for key, path in run_state_paths.items()},
    }


def _commands(
    *,
    lane_config_path: Path,
    run_root: Path,
    run_config_path: Path,
    secrets_path: Path,
) -> StagingCommands:
    def lane(command: str, mode: str) -> tuple[str, ...]:
        return (
            "infinity-context-publishable-mem0-v5",
            command,
            "--config",
            str(lane_config_path),
            "--fleet-mode",
            mode,
        )

    return StagingCommands(
        start_create=lane("start", "create"),
        attest_create=lane("attest", "create"),
        run_2040=(
            "infinity-context-publishable-run",
            "--private-root",
            str(run_root),
            "--config",
            str(run_config_path),
            "--secrets",
            str(secrets_path),
            "--allow-live",
        ),
        start_reopen=lane("start", "reopen"),
        attest_reopen=lane("attest", "reopen"),
    )


def _validate_lane_payload(
    value: dict[str, object],
    *,
    template: StagingTemplate,
    public_inputs: StagingPublicInputs,
) -> None:
    expected = {
        "account_i_r16_fence",
        "adapter_image_id",
        "bind_mount_authority",
        "bridges",
        "docker_host",
        "host_adapter_port",
        "paths",
        "project_name",
        "runtime",
        "schema_version",
        "source_manifest_sha256",
    }
    if set(value) != expected or value["schema_version"] != LANE_CONFIG_SCHEMA:
        _fail("operator_staging_lane_payload_invalid")
    if value["host_adapter_port"] != template.host_adapter_port:
        _fail("operator_staging_lane_payload_invalid")
    fence = value["account_i_r16_fence"]
    if type(fence) is not dict or fence.get("pid") != public_inputs.account_i_pid:
        _fail("operator_staging_lane_fence_invalid")
    encoded = _canonical_json(value)
    if b'"secrets"' in encoded or b'"credentials"' in encoded:
        _fail("operator_staging_lane_contains_secret_material")


def _validate_run_payload(value: dict[str, object], *, run_root: Path) -> None:
    if (
        set(value)
        != {
            "adapter",
            "dependency_provider",
            "max_dispatches_per_batch",
            "publication_key_id",
            "schema_version",
            "state",
        }
        or value["schema_version"] != RUN_CONFIG_SCHEMA
    ):
        _fail("operator_staging_run_payload_invalid")
    adapter = value["adapter"]
    if type(adapter) is not dict:
        _fail("operator_staging_run_adapter_invalid")
    prohibited = ("api_key", "bearer", "credential", "password", "private_key", "secret", "token")
    if any(marker in key.casefold().replace("-", "_") for key in adapter for marker in prohibited):
        _fail("operator_staging_run_contains_secret_material")
    state_paths = value["state"]
    if type(state_paths) is not dict or set(state_paths) != _STATE_FILE_KEYS:
        _fail("operator_staging_run_state_invalid")
    paths = tuple(Path(path) for path in state_paths.values())
    if len(set(paths)) != len(paths) or any(run_root not in path.parents for path in paths):
        _fail("operator_staging_run_state_path_collision")


def _preflight_private_directories(paths: tuple[Path, ...]) -> None:
    if len(set(paths)) != len(paths):
        _fail("operator_staging_private_path_collision")
    root = paths[0]
    try:
        resolved_parent = root.parent.resolve(strict=True)
    except OSError:
        _fail("operator_staging_output_parent_invalid")
    if resolved_parent != root.parent:
        _fail("operator_staging_output_parent_invalid")
    for path in paths:
        try:
            value = path.lstat()
        except FileNotFoundError:
            continue
        except OSError:
            _fail("operator_staging_private_directory_invalid")
        if (
            stat.S_ISLNK(value.st_mode)
            or not stat.S_ISDIR(value.st_mode)
            or value.st_uid != os.geteuid()
            or stat.S_IMODE(value.st_mode) != 0o700
            or path.resolve(strict=True) != path
        ):
            _fail("operator_staging_private_directory_invalid")


def _ensure_private_directory(path: Path) -> None:
    try:
        os.mkdir(path, 0o700)
    except FileExistsError:
        pass
    except OSError:
        _fail("operator_staging_private_directory_unavailable")
    try:
        value = path.lstat()
        if (
            stat.S_ISLNK(value.st_mode)
            or not stat.S_ISDIR(value.st_mode)
            or value.st_uid != os.geteuid()
        ):
            _fail("operator_staging_private_directory_invalid")
        os.chmod(path, 0o700, follow_symlinks=False)
    except OperatorStagingError:
        raise
    except OSError:
        _fail("operator_staging_private_directory_unavailable")


def _reject_existing_paths(paths: tuple[Path, ...]) -> None:
    for path in paths:
        try:
            path.lstat()
        except FileNotFoundError:
            continue
        except OSError:
            _fail("operator_staging_output_collision")
        _fail("operator_staging_output_collision")


def _write_private_json(path: Path, value: dict[str, object]) -> None:
    raw = _canonical_json(value) + b"\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError:
        _fail("operator_staging_output_collision")
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=True) as output:
            descriptor = -1
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
    except OSError:
        if descriptor >= 0:
            os.close(descriptor)
        with contextlib.suppress(OSError):
            path.unlink()
        _fail("operator_staging_output_write_failed")


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def _fail(code: str) -> None:
    raise OperatorStagingError(code)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="build-publishable-staging",
        description="Create secret-free isolated-lane and exact 2,040-run staging configs.",
    )
    parser.add_argument("--template", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--authority-root", required=True, type=Path)
    parser.add_argument("--adapter-image-id", required=True)
    parser.add_argument("--codex-executable-sha256", required=True)
    parser.add_argument("--bridge-binding-sha256", required=True, action="append")
    parser.add_argument("--config-hmac-sha256", required=True)
    parser.add_argument("--deployment-closure-sha256", required=True)
    parser.add_argument("--deployment-closure-hmac-sha256", required=True)
    parser.add_argument("--server-closure-sha256", required=True)
    parser.add_argument("--server-closure-hmac-sha256", required=True)
    parser.add_argument("--account-i-pid", required=True, type=int)
    parser.add_argument("--account-i-start-ticks", required=True, type=int)
    parser.add_argument("--account-i-boot-id", required=True)
    parser.add_argument("--account-i-netns-inode", required=True, type=int)
    parser.add_argument("--account-i-port", required=True, type=int)
    parser.add_argument("--account-i-protected-host-port", required=True, action="append", type=int)
    parser.add_argument("--account-i-container-id", required=True, action="append")
    parser.add_argument("--occupied-host-port", action="append", type=int, default=[])
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        arguments = _parser().parse_args(argv)
        template = load_staging_template(arguments.template)
        public_inputs = StagingPublicInputs(
            adapter_image_id=arguments.adapter_image_id,
            codex_executable_sha256=arguments.codex_executable_sha256,
            bridge_account_binding_sha256=tuple(arguments.bridge_binding_sha256),
            config_hmac_sha256=arguments.config_hmac_sha256,
            deployment_closure_sha256=arguments.deployment_closure_sha256,
            deployment_closure_hmac_sha256=arguments.deployment_closure_hmac_sha256,
            server_closure_sha256=arguments.server_closure_sha256,
            server_closure_hmac_sha256=arguments.server_closure_hmac_sha256,
            account_i_pid=arguments.account_i_pid,
            account_i_start_ticks=arguments.account_i_start_ticks,
            account_i_boot_id=arguments.account_i_boot_id,
            account_i_netns_inode=arguments.account_i_netns_inode,
            account_i_port=arguments.account_i_port,
            account_i_protected_host_ports=tuple(arguments.account_i_protected_host_port),
            account_i_container_ids=tuple(arguments.account_i_container_id),
            occupied_host_ports=tuple(arguments.occupied_host_port),
        )
        bundle = build_staging_bundle(
            template=template,
            output_root=arguments.output_root,
            authority_root=arguments.authority_root,
            public_inputs=public_inputs,
        )
    except OperatorStagingError as exc:
        print(exc.code, file=sys.stderr)
        return 2
    print(_canonical_json(bundle.payload()).decode("ascii"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = (
    "OperatorStagingError",
    "StagingBundle",
    "StagingCommands",
    "StagingPublicInputs",
    "StagingTemplate",
    "build_staging_bundle",
    "load_staging_template",
    "main",
)

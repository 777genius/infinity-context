"""Reusable fixtures for the isolated publishable deployment tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from publishable_mem0_v5 import runtime_attestation
from publishable_mem0_v5.config import (
    BASE_INSTRUCTIONS_SHA256,
    NODE_EXECUTABLE_SHA256,
    PROTECTED_ACCOUNT_I_AUTH_ROOT,
    PROTECTED_R16_ROOT,
    RUNTIME_ENTRYPOINT_SHA256,
    RUNTIME_MANIFEST_SHA256,
    SOURCE_MANIFEST_SHA256,
    AccountIR16Fence,
    BindMountAuthorityConfig,
    BridgeAccountConfig,
    LanePaths,
    PublishableLaneConfig,
    RuntimeAuthorityConfig,
)
from publishable_mem0_v5.docker_cli import QDRANT_IMAGE, SERVICES
from publishable_mem0_v5.preflight import (
    DeploymentInputEvidence,
    FileClosureEvidence,
    PathIdentityEvidence,
)
from publishable_mem0_v5.runtime_integrity import (
    BridgeRuntimeIdentity,
    FleetRuntimeEvidence,
)
from pytest import MonkeyPatch

_QDRANT_ID = "sha256:" + "d" * 64


def runtime_inventory(
    config: PublishableLaneConfig,
    config_file: Path,
    proc_root: Path,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    ids = {name: f"{index:x}" * 64 for index, name in enumerate(SERVICES, start=1)}
    pids = {name: 201 + index for index, name in enumerate(ids)}
    anchor_net = proc_root / str(pids["publishable-relay-anchor"]) / "ns/net"
    anchor_pid = proc_root / str(pids["publishable-relay-anchor"]) / "ns/pid"
    anchor_net.parent.mkdir(parents=True)
    anchor_net.write_text("lane-netns")
    anchor_pid.write_text("lane-pidns")
    for name, pid in pids.items():
        namespace = proc_root / str(pid) / "ns"
        namespace.mkdir(parents=True, exist_ok=True)
        if name != "publishable-relay-anchor":
            os.link(anchor_net, namespace / "net")
            (namespace / "pid").write_text(name)
    paths = config.paths
    mounts = {
        "publishable-relay-anchor": {
            "/opt/publishable/deployment": (paths.deployment_dir, False),
        },
        "publishable-qdrant": {"/qdrant/storage": (paths.qdrant_state_dir, True)},
        "publishable-adapter": {
            "/run/mem0-v5-input": (paths.input_dir, False),
            "/run/mem0-v5-state": (paths.adapter_state_dir, True),
            "/run/secrets": (paths.adapter_secret_dir, False),
            "/opt/publishable/runtime": (config.runtime.runtime_root, False),
            "/opt/publishable/source/phase-c": (paths.phase_c_authority_dir, False),
            "/run/source-authority": (paths.source_authority_dir, False),
            "/run/source-authority-pin": (paths.source_authority_pin_dir, False),
            "/run/source-authority-pin/manifest.sha256": (
                paths.source_authority_pin_sha256_file,
                False,
            ),
            "/opt/publishable/bin/node": (config.runtime.node_executable, False),
        },
    }
    for service, account in zip(SERVICES[2:5], config.bridges, strict=True):
        mounts[service] = {
            "/run/publishable-config/config.json": (config_file, False),
            "/run/publishable-bridge-state": (
                paths.fleet_state_dir / account.account_name,
                True,
            ),
            "/run/publishable-bridge-auth": (
                paths.fleet_auth_dir / account.account_name,
                False,
            ),
            "/opt/publishable/runtime": (config.runtime.runtime_root, False),
            "/opt/publishable/bin/node": (config.runtime.node_executable, False),
            "/opt/publishable/bin/codex": (config.runtime.codex_executable, False),
            "/opt/publishable/server": (paths.server_package_dir, False),
            "/opt/publishable/deployment": (paths.deployment_dir, False),
        }
    network_name = f"{config.project_name}_publishable-runtime"
    commands = {
        "publishable-relay-anchor": [
            "python",
            "-m",
            "publishable_mem0_v5.relay",
            "serve",
        ],
        "publishable-qdrant": ["./entrypoint.sh"],
        "publishable-adapter": [
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
    }
    for index, service in enumerate(SERVICES[2:5]):
        commands[service] = [
            "python",
            "-m",
            "publishable_mem0_v5.fleet_controller",
            "serve",
            "--mode",
            "reopen",
            "--account-index",
            str(index),
        ]
    environments = {
        "publishable-relay-anchor": ["PYTHONPATH=/opt/publishable/deployment"],
        "publishable-qdrant": [
            "QDRANT__SERVICE__HOST=127.0.0.1",
            "QDRANT__SERVICE__HTTP_PORT=6334",
            "QDRANT__SERVICE__GRPC_PORT=6335",
        ],
        "publishable-adapter": [
            "MEM0_V5_PHASE_C_AUTHORITY_DIR=/opt/publishable/source/phase-c",
            "MEM0_V5_QDRANT_ORIGIN=http://127.0.0.1:6334",
            "MEM0_V5_RUNTIME_AUTHORITY_DIR=/opt/publishable/runtime",
            "MEM0_V5_RUNTIME_REPO=/opt/publishable/runtime/repo",
            "MEM0_V5_RUNTIME_TRANSPORT_ORIGIN_FILE=/run/secrets/runtime-transport-origin",
            "HF_HUB_OFFLINE=1",
            "TRANSFORMERS_OFFLINE=1",
        ],
    }
    for service in SERVICES[2:5]:
        environments[service] = [
            "PYTHONPATH=/opt/publishable/deployment:/opt/publishable/server",
            "HOME=/run/publishable-bridge-state/current",
            "XDG_CACHE_HOME=/run/publishable-bridge-state/current/cache",
            "XDG_CONFIG_HOME=/run/publishable-bridge-state/current/config",
            "XDG_DATA_HOME=/run/publishable-bridge-state/current/data",
            "XDG_STATE_HOME=/run/publishable-bridge-state/current/xdg-state",
        ]
    binding = {"19191/tcp": [{"HostIp": "127.0.0.1", "HostPort": str(config.host_adapter_port)}]}
    containers: dict[str, dict[str, Any]] = {}
    anchor = ids["publishable-relay-anchor"]
    for name in ids:
        containers[name] = {
            "Id": ids[name],
            "Image": _QDRANT_ID if name == "publishable-qdrant" else config.adapter_image_id,
            "Config": {
                "Image": QDRANT_IMAGE if name == "publishable-qdrant" else config.adapter_image_id,
                "User": "65532:65532",
                "Cmd": commands[name],
                "Env": environments[name],
                "Labels": {
                    "com.docker.compose.project": config.project_name,
                    "com.docker.compose.service": name,
                    "com.docker.compose.container-number": "1",
                },
            },
            "State": {
                "Running": True,
                "Status": "running",
                "Pid": pids[name],
                "Health": {"Status": "healthy"},
            },
            "HostConfig": {
                "ReadonlyRootfs": True,
                "Privileged": False,
                "CapAdd": None,
                "CapDrop": ["ALL"],
                "SecurityOpt": ["no-new-privileges:true"],
                "PublishAllPorts": False,
                "NetworkMode": (
                    network_name if name == "publishable-relay-anchor" else f"container:{anchor}"
                ),
                "PidMode": "",
                "PortBindings": binding if name == "publishable-relay-anchor" else {},
            },
            "NetworkSettings": {
                "Networks": {network_name: {}} if name == "publishable-relay-anchor" else {},
                "Ports": binding if name == "publishable-relay-anchor" else {},
            },
            "Mounts": [
                {
                    "Type": "bind",
                    "Source": str(source),
                    "Destination": target,
                    "RW": writable,
                }
                for target, (source, writable) in mounts[name].items()
            ],
        }
    network = {
        "Name": network_name,
        "Driver": "bridge",
        "Scope": "local",
        "Internal": False,
        "Attachable": False,
        "Ingress": False,
        "ConfigOnly": False,
        "Labels": {
            "com.docker.compose.project": config.project_name,
            "com.docker.compose.network": "publishable-runtime",
        },
        "Containers": {anchor: {}},
    }
    return containers, network


def deployment_evidence(
    config: PublishableLaneConfig,
    config_file: Path,
) -> DeploymentInputEvidence:
    def identity(path: Path, inode: int) -> PathIdentityEvidence:
        return PathIdentityEvidence(
            path=str(path),
            resolved_path=str(path),
            device=1,
            inode=inode,
            mode=0o100400,
            size=1,
            mtime_ns=1,
            parent_chain_sha256=f"{inode:x}".rjust(64, "0"),
        )

    return DeploymentInputEvidence(
        config_file=identity(config_file, 1),
        config_sha256="1" * 64,
        config_hmac_sha256="2" * 64,
        deployment_closure=FileClosureEvidence(
            label="deployment",
            root=identity(config.paths.deployment_dir, 2),
            file_count=1,
            total_bytes=1,
            closure_sha256="3" * 64,
            closure_hmac_sha256="4" * 64,
        ),
        server_closure=FileClosureEvidence(
            label="server",
            root=identity(config.paths.server_package_dir, 3),
            file_count=1,
            total_bytes=1,
            closure_sha256="5" * 64,
            closure_hmac_sha256="6" * 64,
        ),
        runtime_root=identity(config.runtime.runtime_root, 4),
        node_executable=identity(config.runtime.node_executable, 5),
        codex_executable=identity(config.runtime.codex_executable, 6),
        host_relay_port=config.host_adapter_port,
    )


def stub_runtime_dependencies(
    monkeypatch: MonkeyPatch,
    config: PublishableLaneConfig,
    deployment_before: DeploymentInputEvidence,
) -> None:
    bridges = tuple(
        BridgeRuntimeIdentity(
            account_name=account.account_name,
            bridge_id=account.bridge_id,
            controller_pid=10 + index,
            generation=1,
            launch_mode="reopen",
            process={"pid": 20 + index},
            runtime_authority_sha256=f"{index + 1:x}" * 64,
            readiness_receipt_sha256=f"{index + 4:x}" * 64,
        )
        for index, account in enumerate(config.bridges)
    )
    fleet = FleetRuntimeEvidence(
        requested_mode="reopen",
        pool_authority_sha256="7" * 64,
        fleet_readiness_sha256="8" * 64,
        bridges=bridges,  # type: ignore[arg-type]
    )
    monkeypatch.setattr(
        runtime_attestation,
        "attest_deployment_inputs",
        lambda *_args, **_kwargs: deployment_before,
    )
    monkeypatch.setattr(
        runtime_attestation,
        "_attest_anchor_container_inventory",
        lambda *_args, **_kwargs: "9" * 64,
    )
    monkeypatch.setattr(
        runtime_attestation,
        "_attest_loopback_bindings",
        lambda *_args, **_kwargs: "a" * 64,
    )
    monkeypatch.setattr(
        runtime_attestation,
        "_attest_fleet_readiness",
        lambda *_args, **_kwargs: fleet,
    )


class BridgeFactory:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def create_new(self, spec: object) -> str:
        del spec
        self.calls.append("create")
        return "fresh-bridge"

    def reopen(self, spec: object) -> str:
        del spec
        self.calls.append("reopen")
        return "reopened-bridge"


class RecordingRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], dict[str, str]]] = []

    def run(self, arguments: tuple[str, ...], *, environment: Any) -> bytes:
        self.calls.append((arguments, dict(environment)))
        if arguments[3:5] == ("image", "inspect"):
            reference = arguments[5]
            if reference == QDRANT_IMAGE:
                digest = QDRANT_IMAGE.split("@", 1)[1]
                return json_bytes([{"Id": _QDRANT_ID, "RepoDigests": [f"qdrant/qdrant@{digest}"]}])
            return json_bytes([{"Id": reference, "RepoDigests": []}])
        if arguments[3] == "compose" and "ps" in arguments:
            index = SERVICES.index(arguments[-1]) + 1
            return f"{index:064x}\n".encode()
        return b""


class RuntimeRunner(RecordingRunner):
    def __init__(
        self,
        config: PublishableLaneConfig,
        containers: dict[str, dict[str, Any]],
        network: dict[str, Any],
    ) -> None:
        super().__init__()
        self.config = config
        self.containers = containers
        self.network = network

    def run(self, arguments: tuple[str, ...], *, environment: Any) -> bytes:
        self.calls.append((arguments, dict(environment)))
        if arguments[3:5] == ("image", "inspect"):
            reference = arguments[5]
            if reference == QDRANT_IMAGE:
                digest = QDRANT_IMAGE.split("@", 1)[1]
                return json_bytes([{"Id": _QDRANT_ID, "RepoDigests": [f"qdrant/qdrant@{digest}"]}])
            return json_bytes([{"Id": reference, "RepoDigests": []}])
        if arguments[3] == "compose" and "ps" in arguments:
            return (self.containers[arguments[-1]]["Id"] + "\n").encode()
        if arguments[3:7] == ("container", "ls", "--quiet", "--no-trunc"):
            return ("\n".join(item["Id"] for item in self.containers.values()) + "\n").encode()
        if arguments[3] == "inspect":
            by_id = {item["Id"]: item for item in self.containers.values()}
            return json_bytes([by_id[item] for item in arguments[4:]])
        if arguments[3:5] == ("network", "inspect"):
            return json_bytes([self.network])
        if arguments[3] == "exec":
            return b""
        raise AssertionError(arguments)


def build_config(
    tmp_path: Path,
    *,
    deployment_dir: Path | None = None,
) -> tuple[PublishableLaneConfig, Path]:
    project = "mem0-v5-publishable-testlane"
    run_root = tmp_path / project
    for name in (
        "input",
        "adapter-state",
        "qdrant-state",
        "adapter-secrets",
        "fleet-state",
        "fleet-auth",
        "attestation",
    ):
        private_directory(run_root / name)
    public = tmp_path / "public"
    public.mkdir()
    pin = public / "source-pin"
    pin.mkdir()
    proc_root = tmp_path / "proc"
    pid = 99101
    boot_id = "11111111-1111-1111-1111-111111111111"
    ticks = 123456
    (proc_root / "sys/kernel/random").mkdir(parents=True)
    (proc_root / "sys/kernel/random/boot_id").write_text(boot_id + "\n")
    process = proc_root / str(pid)
    (process / "ns").mkdir(parents=True)
    (process / "stat").write_text(_proc_stat(pid, ticks))
    (process / "ns/net").write_text("protected-netns")
    fence = AccountIR16Fence(
        pid=pid,
        start_ticks=ticks,
        boot_id=boot_id,
        netns_inode=(process / "ns/net").stat().st_ino,
        port=28891,
        state_root=PROTECTED_R16_ROOT,
        auth_root=PROTECTED_ACCOUNT_I_AUTH_ROOT,
        protected_host_ports=(6334, 8891, 8892, 19091),
        container_ids=("9" * 64,),
    )
    paths = LanePaths(
        run_root=run_root,
        input_dir=run_root / "input",
        adapter_state_dir=run_root / "adapter-state",
        qdrant_state_dir=run_root / "qdrant-state",
        adapter_secret_dir=run_root / "adapter-secrets",
        fleet_state_dir=run_root / "fleet-state",
        fleet_auth_dir=run_root / "fleet-auth",
        attestation_dir=run_root / "attestation",
        phase_c_authority_dir=public / "phase-c",
        source_authority_dir=public / "source",
        source_authority_pin_dir=pin,
        source_authority_pin_sha256_file=pin / "manifest.sha256",
        server_package_dir=public / "server",
        deployment_dir=deployment_dir or public / "deployment",
    )
    runtime = RuntimeAuthorityConfig(
        runtime_root=public / "runtime",
        runtime_artifact_manifest_sha256=RUNTIME_MANIFEST_SHA256,
        runtime_entrypoint_sha256=RUNTIME_ENTRYPOINT_SHA256,
        node_executable=public / "node",
        node_executable_sha256=NODE_EXECUTABLE_SHA256,
        codex_executable=public / "codex",
        codex_executable_sha256="c" * 64,
    )
    bridges = tuple(
        BridgeAccountConfig(
            account_name=f"account-{letter}",
            bridge_id=f"publishable-bridge-{letter}",
            account_binding_hmac_sha256=letter * 64,
        )
        for letter in "abc"
    )
    config = PublishableLaneConfig(
        project_name=project,
        adapter_image_id="sha256:" + "a" * 64,
        host_adapter_port=29191,
        docker_host="unix:///run/publishable-test/docker.sock",
        source_manifest_sha256=SOURCE_MANIFEST_SHA256,
        bind_mount_authority=BindMountAuthorityConfig(
            config_hmac_sha256="1" * 64,
            deployment_closure_sha256="2" * 64,
            deployment_closure_hmac_sha256="3" * 64,
            server_closure_sha256="4" * 64,
            server_closure_hmac_sha256="5" * 64,
        ),
        paths=paths,
        runtime=runtime,
        bridges=bridges,
        account_i_r16_fence=fence,
    )
    _namespace_fixture(proc_root)
    return config, proc_root


def write_cross_wire(config: PublishableLaneConfig) -> None:
    adapter = config.paths.adapter_secret_dir
    adapter_values = {
        "runtime-bearer": b"runtime-bearer-" * 4,
        "runtime-receipt-secret": b"runtime-receipt-" * 4,
        "runtime-attestation-secret": b"runtime-attestation-root-" * 2,
        "account-binding-hmac-sha256": config.bridges[0].account_binding_hmac_sha256.encode(),
        "base-instructions-sha256": BASE_INSTRUCTIONS_SHA256.encode(),
        "runtime-transport-origin": b"http://127.0.0.1:8891",
    }
    for name, raw in adapter_values.items():
        private_file(adapter / name, raw)
    for index, account in enumerate(config.bridges):
        auth_root = config.paths.fleet_auth_dir / account.account_name
        private_directory(auth_root)
        private_file(
            auth_root / "ingress-api-key.secret",
            adapter_values["runtime-bearer"] if index == 0 else f"api-{index}-".encode() * 8,
        )
        private_file(
            auth_root / "attestation-hmac.secret",
            (
                adapter_values["runtime-receipt-secret"]
                if index == 0
                else f"attestation-{index}-".encode() * 4
            ),
        )
        private_file(auth_root / "launcher-receipt.key", f"launcher-{index}-".encode() * 4)
        private_file(
            auth_root / "account-binding-hmac-sha256",
            account.account_binding_hmac_sha256.encode(),
        )
        private_file(auth_root / "base-instructions-sha256", BASE_INSTRUCTIONS_SHA256.encode())
        if index == 0:
            private_file(
                auth_root / "runtime-transport-origin",
                adapter_values["runtime-transport-origin"],
            )


def private_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path, 0o700)


def private_file(path: Path, raw: bytes) -> None:
    path.write_bytes(raw)
    os.chmod(path, 0o600)


def json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _proc_stat(pid: int, ticks: int) -> str:
    fields = ["S", *("1" for _ in range(49))]
    fields[19] = str(ticks)
    return f"{pid} (account i) {' '.join(fields)}\n"


def _namespace_fixture(proc_root: Path) -> None:
    self_ns = proc_root / "self/ns"
    init_ns = proc_root / "1/ns"
    self_ns.mkdir(parents=True)
    init_ns.mkdir(parents=True)
    (self_ns / "net").write_text("anchor-net")
    os.link(self_ns / "net", init_ns / "net")
    (self_ns / "pid").write_text("anchor-pid")
    os.link(self_ns / "pid", init_ns / "pid")


__all__ = (
    "BridgeFactory",
    "RecordingRunner",
    "RuntimeRunner",
    "build_config",
    "deployment_evidence",
    "json_bytes",
    "private_directory",
    "private_file",
    "runtime_inventory",
    "stub_runtime_dependencies",
    "write_cross_wire",
)

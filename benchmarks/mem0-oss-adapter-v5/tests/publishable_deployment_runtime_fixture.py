"""Docker-inspect fixture for the isolated publishable deployment tests."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from publishable_mem0_v5.config import PublishableLaneConfig
from publishable_mem0_v5.docker_cli import QDRANT_IMAGE, SERVICES

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


__all__ = ("runtime_inventory",)

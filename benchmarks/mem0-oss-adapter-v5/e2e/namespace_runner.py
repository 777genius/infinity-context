"""Privileged, stdlib-only boundary for the provider-free E2E network namespace."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import selectors
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
import types
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

PINNED_DOCKER_HOST = "unix:///run/infinity-locomo-docker/docker.sock"
PINNED_DOCKER_SOCKET = Path("/run/infinity-locomo-docker/docker.sock")
PINNED_DOCKER = Path("/usr/bin/docker")
PINNED_NSENTER = Path("/usr/bin/nsenter")
PINNED_SETPRIV = Path("/usr/bin/setpriv")
PINNED_ROOT_PYTHON = Path("/usr/bin/python3.12")
PINNED_BENCHMARK_ROOT = Path(
    "/mnt/volume_ams3_1784742570542/infinity-context/worktrees/"
    "mem0-oss-adapter-v5-r1/benchmarks/mem0-oss-adapter-v5"
)
PINNED_HOSTING_ROOT = Path("/mnt/volume_ams3_1784742570542/infinity-locomo-benchmark")
PINNED_RUN_PARENT = PINNED_HOSTING_ROOT / "e2e-runs/host296603"
PINNED_HOST_PYTHON = PINNED_RUN_PARENT / "e2e-venv/bin/python"
PINNED_RUNTIME_MIRROR = PINNED_HOSTING_ROOT / "e2e-runtime-authorities/e904ec95-uid65532-host296603"
PINNED_PHASE_C = Path("/mnt/volume_ams3_1784742570542/infinity-context/sources/9499b9c2")
PINNED_NODE = PINNED_HOSTING_ROOT / "e2e-runtime-authorities/node-b2959781/node"
PINNED_DOCKER_DATA_ROOT = PINNED_HOSTING_ROOT / "docker"
PINNED_DOCKER_EXEC_ROOT = PINNED_HOSTING_ROOT / "exec"
PINNED_DOCKER_PIDFILE = PINNED_HOSTING_ROOT / "state/dockerd.pid"
EXPECTED_DAEMON_UID = 994
EXPECTED_DAEMON_GID = 985
TRUSTED_SOCKET_GID = 232058
MAPPED_RUNTIME_UID = 296603
MAPPED_RUNTIME_GID = 296603
ANCHOR_SERVICE = "e2e-network-anchor"
NETWORK_KEY = "provider-free-internal"
QDRANT_IMAGE = (
    "qdrant/qdrant:v1.18.3@sha256:ecc81d662bb9bb734db879b94461eb44be38604fc259491d478ad7e673238a0d"
)
SERVICES = (
    ANCHOR_SERVICE,
    "mem0-oss-v5-fake-runtime",
    "mem0-oss-v5-qdrant",
    "mem0-oss-adapter-v5",
)
COMPOSE_PATH_ENVIRONMENT = (
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
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PROJECT = re.compile(r"^mem0-v5-e2e-([0-9a-f]{8,40})-r[0-9]+$")
_MAX_OUTPUT = 16_384
_CHILD_TIMEOUT_SECONDS = 900.0


class NamespaceRunnerError(RuntimeError): ...


class DockerInspector(Protocol):
    def daemon_info(self) -> Mapping[str, Any]: ...

    def service_ids(self, project_name: str, service: str) -> Sequence[str]: ...

    def inspect_container(self, container_id: str) -> Mapping[str, Any]: ...

    def inspect_network(self, network_name: str) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class AnchorIdentity:
    container_id: str
    image_id: str
    pid: int
    started_at: str
    network_name: str


@dataclass(frozen=True)
class ServiceIdentity:
    service: str
    container_id: str
    image_id: str
    config_hash: str
    started_at: str | None


@dataclass(frozen=True)
class StackIdentity:
    anchor: AnchorIdentity
    services: tuple[ServiceIdentity, ...]


@dataclass(frozen=True)
class E2ERunArguments:
    run_root: Path
    runtime_authority_mirror: Path
    node: Path
    compose_file: Path
    project_name: str
    host_python: Path
    adapter_port: int = 19091
    qdrant_port: int = 6334

    def validate(self) -> None:
        for path in (
            self.run_root,
            self.runtime_authority_mirror,
            self.node,
            self.compose_file,
            self.host_python,
        ):
            if not path.is_absolute() or "\x00" in str(path):
                raise NamespaceRunnerError("e2e_runner_path_invalid")
        expected_compose = PINNED_BENCHMARK_ROOT / "compose.provider-free-e2e.yaml"
        if (
            self.compose_file != expected_compose
            or self.compose_file.is_symlink()
            or self.compose_file.resolve() != self.compose_file
        ):
            raise NamespaceRunnerError("e2e_compose_path_invalid")
        if (
            not self.run_root.is_dir()
            or not self.runtime_authority_mirror.is_dir()
            or not self.node.is_file()
            or not self.compose_file.is_file()
            or not self.host_python.is_file()
            or not os.access(self.host_python, os.X_OK)
        ):
            raise NamespaceRunnerError("e2e_runner_path_invalid")
        project = _PROJECT.fullmatch(self.project_name)
        if project is None:
            raise NamespaceRunnerError("e2e_project_name_invalid")
        if (
            self.run_root.parent != PINNED_RUN_PARENT
            or self.run_root.name != self.project_name
            or self.runtime_authority_mirror != PINNED_RUNTIME_MIRROR
            or self.node != PINNED_NODE
            or self.host_python != PINNED_HOST_PYTHON
        ):
            raise NamespaceRunnerError("e2e_runner_path_correlation_invalid")
        _validate_mapped_path(self.run_root, directory=True)
        if project.group(1) == "00000000":
            raise NamespaceRunnerError("e2e_project_name_invalid")
        if not (1 <= self.adapter_port <= 65535 and 1 <= self.qdrant_port <= 65535):
            raise NamespaceRunnerError("e2e_runner_port_invalid")

    def child_argv(self, lifecycle_fd: int) -> list[str]:
        return [
            str(self.host_python),
            "-m",
            "e2e.run",
            "--run-root",
            str(self.run_root),
            "--runtime-authority-mirror",
            str(self.runtime_authority_mirror),
            "--node",
            str(self.node),
            "--compose-file",
            str(self.compose_file),
            "--project-name",
            self.project_name,
            "--lifecycle-fd",
            str(lifecycle_fd),
            "--adapter-port",
            str(self.adapter_port),
            "--qdrant-port",
            str(self.qdrant_port),
        ]


class PinnedHostTrust:
    """Attest the explicitly trusted UID-994 rootless Docker boundary."""

    def attest(self) -> None:
        _validate_path_chain(PINNED_DOCKER_SOCKET.parent)
        _validate_path_chain(PINNED_DOCKER_DATA_ROOT)
        _validate_path_chain(PINNED_DOCKER_EXEC_ROOT)
        _validate_path_chain(PINNED_DOCKER_PIDFILE.parent)
        _validate_socket()
        _validate_daemon_process()
        _validate_owned_directory(PINNED_DOCKER_DATA_ROOT, mode=0o710)
        _validate_owned_directory(PINNED_DOCKER_EXEC_ROOT, mode=0o700)
        _validate_owned_directory(PINNED_DOCKER_PIDFILE.parent, mode=0o700)


class DockerCliInspector:
    """Read-only CLI adapter which re-attests host trust before every call."""

    def __init__(self, trust: PinnedHostTrust) -> None:
        self._trust = trust

    def daemon_info(self) -> Mapping[str, Any]:
        return self._json(["info", "--format", "{{json .}}"])

    def service_ids(self, project_name: str, service: str) -> Sequence[str]:
        output = self._text(
            [
                "container",
                "ls",
                "--all",
                "--filter",
                f"label=com.docker.compose.project={project_name}",
                "--filter",
                f"label=com.docker.compose.service={service}",
                "--format",
                "{{.ID}}",
            ]
        )
        return tuple(line for line in output.splitlines() if line)

    def inspect_container(self, container_id: str) -> Mapping[str, Any]:
        value = self._json(["container", "inspect", container_id])
        if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
            raise NamespaceRunnerError("e2e_container_inspect_invalid")
        return value[0]

    def inspect_network(self, network_name: str) -> Mapping[str, Any]:
        value = self._json(["network", "inspect", network_name])
        if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
            raise NamespaceRunnerError("e2e_network_inspect_invalid")
        return value[0]

    def _json(self, arguments: list[str]) -> Any:
        try:
            return json.loads(self._text(arguments))
        except (json.JSONDecodeError, TypeError):
            raise NamespaceRunnerError("e2e_docker_response_invalid") from None

    def _text(self, arguments: list[str]) -> str:
        self._trust.attest()
        try:
            completed = subprocess.run(
                [str(PINNED_DOCKER), "--host", PINNED_DOCKER_HOST, *arguments],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=30,
                check=True,
                env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
            )
        except Exception:
            raise NamespaceRunnerError("e2e_docker_command_failed") from None
        if len(completed.stdout) > _MAX_OUTPUT * 16:
            raise NamespaceRunnerError("e2e_docker_response_invalid")
        return completed.stdout.strip()


class PinnedDockerAnchorLocator:
    """Attest the exact Compose stack, passive anchor and internal network."""

    def __init__(
        self,
        inspector: DockerInspector,
        mount_policy: Mapping[str, Mapping[str, tuple[str, bool]]],
        service_process_attestor: Any,
        tmpfs_attestor: Any,
    ) -> None:
        self._inspector = inspector
        self._mount_policy = mount_policy
        self._service_process_attestor = service_process_attestor
        self._tmpfs_attestor = tmpfs_attestor

    def attest_daemon(self) -> None:
        info = self._inspector.daemon_info()
        security = info.get("SecurityOptions")
        rootless = isinstance(security, list) and any(
            item == "name=rootless"
            or (isinstance(item, Mapping) and item.get("name") == "rootless")
            for item in security
        )
        if info.get("DockerRootDir") != str(PINNED_DOCKER_DATA_ROOT) or not rootless:
            raise NamespaceRunnerError("e2e_docker_daemon_invalid")

    def locate(self, *, project_name: str, compose_file: Path) -> StackIdentity:
        containers: dict[str, Mapping[str, Any]] = {}
        for service in SERVICES:
            ids = tuple(self._inspector.service_ids(project_name, service))
            if len(ids) != 1:
                raise NamespaceRunnerError("e2e_service_cardinality_invalid")
            inspected = self._inspector.inspect_container(ids[0])
            exact_id = inspected.get("Id")
            if not isinstance(exact_id, str) or not exact_id.startswith(ids[0]):
                raise NamespaceRunnerError("e2e_container_id_invalid")
            containers[service] = inspected
        anchor = self._attest_anchor(containers[ANCHOR_SERVICE], project_name, compose_file)
        identities = []
        for service in SERVICES[1:]:
            identities.append(
                self._attest_workload(
                    containers[service], service, anchor, project_name, compose_file
                )
            )
        self._attest_network(anchor, project_name)
        return StackIdentity(anchor, tuple(identities))

    def reattest(self, identity: StackIdentity, *, project_name: str, compose_file: Path) -> None:
        current = self.locate(project_name=project_name, compose_file=compose_file)
        if current != identity:
            raise NamespaceRunnerError("e2e_anchor_identity_changed")

    def _attest_anchor(
        self, value: Mapping[str, Any], project: str, compose: Path
    ) -> AnchorIdentity:
        exact_id, image_id, _config_hash, state, config, host = self._common(
            value, ANCHOR_SERVICE, project, compose
        )
        expected_image = f"{project}-{ANCHOR_SERVICE}"
        if config.get("Image") != expected_image or config.get("User") != "65532:65532":
            raise NamespaceRunnerError("e2e_anchor_config_invalid")
        command = config.get("Cmd")
        if command != ["python", "-m", "e2e.anchor"] or config.get("Entrypoint") not in (
            None,
            [],
        ):
            raise NamespaceRunnerError("e2e_anchor_command_invalid")
        self._attest_process(config, ANCHOR_SERVICE)
        expected_network = f"{project}_{NETWORK_KEY}"
        networks = _mapping(_mapping(value, "NetworkSettings"), "Networks")
        if set(networks) != {expected_network} or host.get("NetworkMode") != expected_network:
            raise NamespaceRunnerError("e2e_anchor_networks_invalid")
        self._attest_mounts(value, ANCHOR_SERVICE)
        self._tmpfs_attestor(host, {"/tmp": (8 * 1024 * 1024, "1770")})
        self._no_ports(config, host, _mapping(value, "NetworkSettings"), frozenset())
        return AnchorIdentity(
            exact_id,
            image_id,
            _positive_int(state.get("Pid"), "e2e_anchor_state_invalid"),
            _nonempty_string(state.get("StartedAt"), "e2e_anchor_state_invalid"),
            expected_network,
        )

    def _attest_workload(
        self,
        value: Mapping[str, Any],
        service: str,
        anchor: AnchorIdentity,
        project: str,
        compose: Path,
    ) -> ServiceIdentity:
        exact_id, image_id, config_hash, state, config, host = self._common(
            value, service, project, compose
        )
        if config.get("User") != "65532:65532":
            raise NamespaceRunnerError("e2e_workload_user_invalid")
        self._attest_process(config, service)
        network_mode = host.get("NetworkMode")
        if not isinstance(network_mode, str) or not network_mode.startswith("container:"):
            raise NamespaceRunnerError("e2e_workload_network_invalid")
        if network_mode.removeprefix("container:") not in {
            anchor.container_id,
            anchor.container_id[:12],
        }:
            raise NamespaceRunnerError("e2e_workload_network_invalid")
        networks = _mapping(_mapping(value, "NetworkSettings"), "Networks")
        if networks:
            raise NamespaceRunnerError("e2e_workload_network_invalid")
        expected_exposed = {
            "mem0-oss-v5-fake-runtime": frozenset(),
            "mem0-oss-v5-qdrant": frozenset({"6333/tcp", "6334/tcp"}),
            "mem0-oss-adapter-v5": frozenset({"19091/tcp"}),
        }[service]
        self._no_ports(config, host, _mapping(value, "NetworkSettings"), expected_exposed)
        if service == "mem0-oss-v5-qdrant":
            if config.get("Image") != QDRANT_IMAGE:
                raise NamespaceRunnerError("e2e_qdrant_config_invalid")
            self._attest_mounts(value, service)
            self._tmpfs_attestor(
                host,
                {
                    "/qdrant/storage": (1024 * 1024 * 1024, "0700"),
                    "/tmp": (32 * 1024 * 1024, "1770"),
                },
            )
        else:
            if config.get("Image") != f"{project}-{service}":
                raise NamespaceRunnerError("e2e_workload_image_invalid")
            labels = _mapping(config, "Labels")
            if labels.get("com.docker.compose.image") != image_id:
                raise NamespaceRunnerError("e2e_workload_image_invalid")
            self._attest_mounts(value, service)
            size = 16 if service == "mem0-oss-v5-fake-runtime" else 64
            self._tmpfs_attestor(host, {"/tmp": (size * 1024 * 1024, "1770")})
        started_at = _nonempty_string(state.get("StartedAt"), "e2e_service_state_invalid")
        return ServiceIdentity(
            service,
            exact_id,
            image_id,
            config_hash,
            None if service == "mem0-oss-adapter-v5" else started_at,
        )

    def _common(
        self, value: Mapping[str, Any], service: str, project: str, compose: Path
    ) -> tuple[str, str, str, Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]:
        config = _mapping(value, "Config")
        labels = _mapping(config, "Labels")
        required = {
            "com.docker.compose.project": project,
            "com.docker.compose.service": service,
            "com.docker.compose.container-number": "1",
            "com.docker.compose.project.config_files": str(compose),
        }
        if any(labels.get(key) != expected for key, expected in required.items()):
            raise NamespaceRunnerError("e2e_service_labels_invalid")
        config_hash = labels.get("com.docker.compose.config-hash")
        if not isinstance(config_hash, str) or not _SHA256.fullmatch(config_hash):
            raise NamespaceRunnerError("e2e_service_config_hash_invalid")
        state = _mapping(value, "State")
        if state.get("Status") != "running" or state.get("Running") is not True:
            raise NamespaceRunnerError("e2e_service_state_invalid")
        host = _mapping(value, "HostConfig")
        security = host.get("SecurityOpt")
        if (
            host.get("Privileged") is not False
            or host.get("ReadonlyRootfs") is not True
            or host.get("CapAdd") not in (None, [])
            or host.get("CapDrop") != ["ALL"]
            or not isinstance(security, list)
            or {item.removesuffix(":true") for item in security} != {"no-new-privileges"}
        ):
            raise NamespaceRunnerError("e2e_service_hardening_invalid")
        exact_id = _nonempty_string(value.get("Id"), "e2e_container_id_invalid")
        image_id = _nonempty_string(value.get("Image"), "e2e_container_image_invalid")
        if labels.get("com.docker.compose.image") != image_id:
            raise NamespaceRunnerError("e2e_container_image_invalid")
        return exact_id, image_id, config_hash, state, config, host

    @staticmethod
    def _no_ports(
        config: Mapping[str, Any],
        host: Mapping[str, Any],
        network: Mapping[str, Any],
        expected_exposed: frozenset[str],
    ) -> None:
        exposed = config.get("ExposedPorts")
        exposed_keys = (
            frozenset() if exposed in (None, {}) else frozenset(_mapping(config, "ExposedPorts"))
        )
        if (
            exposed_keys != expected_exposed
            or host.get("PortBindings") not in (None, {})
            or network.get("Ports") not in (None, {})
        ):
            raise NamespaceRunnerError("e2e_service_ports_invalid")

    def _attest_mounts(self, value: Mapping[str, Any], service: str) -> None:
        mounts = value.get("Mounts")
        if not isinstance(mounts, list):
            raise NamespaceRunnerError("e2e_workload_mounts_invalid")
        expected = self._mount_policy[service]
        observed: dict[str, tuple[str, bool]] = {}
        for mount in mounts:
            if not isinstance(mount, Mapping):
                raise NamespaceRunnerError("e2e_workload_mounts_invalid")
            if mount.get("Type") == "tmpfs":
                continue
            if mount.get("Type") != "bind":
                raise NamespaceRunnerError("e2e_workload_mounts_invalid")
            source = mount.get("Source")
            target = mount.get("Destination")
            if (
                not isinstance(source, str)
                or not Path(source).is_absolute()
                or not isinstance(target, str)
                or not isinstance(mount.get("RW"), bool)
            ):
                raise NamespaceRunnerError("e2e_workload_mounts_invalid")
            observed[target] = (source, mount["RW"])
        if observed != expected:
            raise NamespaceRunnerError("e2e_workload_mounts_invalid")

    def _attest_process(self, config: Mapping[str, Any], service: str) -> None:
        try:
            self._service_process_attestor(config, service)
        except Exception:
            raise NamespaceRunnerError("e2e_service_process_invalid") from None

    def _attest_network(self, anchor: AnchorIdentity, project: str) -> None:
        value = self._inspector.inspect_network(anchor.network_name)
        labels = _mapping(value, "Labels")
        ipam = _mapping(value, "IPAM")
        configurations = ipam.get("Config")
        if (
            value.get("Name") != anchor.network_name
            or value.get("Driver") != "bridge"
            or value.get("Scope") != "local"
            or value.get("Internal") is not True
            or value.get("Attachable") is not False
            or value.get("Ingress") is not False
            or value.get("ConfigOnly") is not False
            or value.get("Options") not in (None, {})
            or labels.get("com.docker.compose.project") != project
            or labels.get("com.docker.compose.network") != NETWORK_KEY
            or ipam.get("Driver") != "default"
            or ipam.get("Options") not in (None, {})
            or not isinstance(configurations, list)
            or len(configurations) != 1
        ):
            raise NamespaceRunnerError("e2e_internal_network_invalid")
        _validate_ipam(configurations[0])
        members = _mapping(value, "Containers")
        if set(members) != {anchor.container_id}:
            raise NamespaceRunnerError("e2e_network_membership_invalid")
        member = members[anchor.container_id]
        if not isinstance(member, Mapping) or member.get("Name") != f"{project}-{ANCHOR_SERVICE}-1":
            raise NamespaceRunnerError("e2e_network_membership_invalid")


class PinnedNetnsExecutor:
    """Drop privileges and execute only the fixed child module in netns."""

    def __init__(self, result_validator: Any) -> None:
        self._result_validator = result_validator

    def execute(
        self,
        namespace_fd: int,
        lifecycle_fd: int,
        arguments: E2ERunArguments,
        environment: Mapping[str, str],
    ) -> Mapping[str, Any]:
        command = [
            str(PINNED_NSENTER),
            f"--net=/proc/self/fd/{namespace_fd}",
            "--",
            str(PINNED_SETPRIV),
            f"--reuid={MAPPED_RUNTIME_UID}",
            f"--regid={MAPPED_RUNTIME_GID}",
            "--clear-groups",
            "--bounding-set=-all",
            "--ambient-caps=-all",
            "--inh-caps=-all",
            "--no-new-privs",
            "--",
            *arguments.child_argv(lifecycle_fd),
        ]
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=dict(environment),
                cwd=arguments.compose_file.parent,
                close_fds=True,
                pass_fds=(namespace_fd, lifecycle_fd),
                start_new_session=True,
            )
            stdout, _stderr = _bounded_communicate(process)
        except NamespaceRunnerError:
            raise
        except Exception:
            raise NamespaceRunnerError("e2e_namespace_run_failed") from None
        if process.returncode != 0:
            raise NamespaceRunnerError("e2e_namespace_run_failed")
        return self._result_validator(stdout, NamespaceRunnerError)


class NamespaceRunOrchestrator:
    def __init__(
        self,
        *,
        locator: PinnedDockerAnchorLocator,
        process_attestor: Any,
        executor: PinnedNetnsExecutor,
        lifecycle_helper_type: Any,
    ) -> None:
        self._locator = locator
        self._process = process_attestor
        self._executor = executor
        self._helper_type = lifecycle_helper_type

    def run(self, arguments: E2ERunArguments, environment: Mapping[str, str]) -> Mapping[str, Any]:
        stack = self._locator.locate(
            project_name=arguments.project_name, compose_file=arguments.compose_file
        )
        anchor = stack.anchor
        pidfd, netfd, process = self._process.open(anchor)
        parent_channel, child_channel = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        helper = self._helper_type(
            channel=parent_channel,
            compose_file=arguments.compose_file,
            project_name=arguments.project_name,
            environment=environment,
        )
        helper_result: list[bool] = []
        helper_thread = threading.Thread(
            target=lambda: helper_result.append(helper.serve_once()), daemon=True
        )
        helper_thread.start()
        try:
            self._locator.reattest(
                stack,
                project_name=arguments.project_name,
                compose_file=arguments.compose_file,
            )
            self._process.reattest(pidfd, netfd, process, anchor.container_id)
            result = self._executor.execute(netfd, child_channel.fileno(), arguments, environment)
            self._process.reattest(pidfd, netfd, process, anchor.container_id)
            self._locator.reattest(
                stack,
                project_name=arguments.project_name,
                compose_file=arguments.compose_file,
            )
            helper_thread.join(timeout=135)
            if helper_thread.is_alive() or helper_result != [True]:
                raise NamespaceRunnerError("e2e_root_lifecycle_failed")
            return result
        finally:
            child_channel.close()
            if helper_thread.is_alive():
                parent_channel.close()
                helper_thread.join(timeout=1)
            os.close(netfd)
            os.close(pidfd)


def run(arguments: E2ERunArguments) -> Mapping[str, Any]:
    if os.geteuid() != 0:
        raise NamespaceRunnerError("e2e_runner_requires_root")
    if os.environ.get("DOCKER_HOST") != PINNED_DOCKER_HOST:
        raise NamespaceRunnerError("e2e_docker_host_invalid")
    _validate_root_executable(PINNED_DOCKER)
    _validate_root_executable(PINNED_NSENTER)
    _validate_root_executable(PINNED_SETPRIV)
    _validate_root_executable(PINNED_ROOT_PYTHON)
    _validate_wrapper_source()
    arguments.validate()
    environment = _child_environment(os.environ, arguments)
    support = _load_privileged_support()
    trust = PinnedHostTrust()
    trust.attest()
    locator = PinnedDockerAnchorLocator(
        DockerCliInspector(trust),
        support.build_mount_policy(environment),
        support.attest_service_process,
        support.attest_tmpfs,
    )
    locator.attest_daemon()
    return NamespaceRunOrchestrator(
        locator=locator,
        process_attestor=support.ProcessNamespaceAttestor(error_type=NamespaceRunnerError),
        executor=support.build_e2e_attesting_executor(
            delegate=PinnedNetnsExecutor(support.validate_public_result),
            node_path=arguments.node,
            manifest_path=Path(environment["MEM0_V5_SOURCE_AUTHORITY_PIN_DIR"]) / "manifest.json",
            digest_path=Path(environment["MEM0_V5_SOURCE_AUTHORITY_PIN_SHA256_FILE"]),
            run_root=arguments.run_root,
            expected_uid=MAPPED_RUNTIME_UID,
            expected_gid=MAPPED_RUNTIME_GID,
            error_type=NamespaceRunnerError,
        ),
        lifecycle_helper_type=lambda **values: support.RootDockerLifecycleHelper(
            trust_attestor=trust.attest, **values
        ),
    ).run(arguments, environment)


def _child_environment(source: Mapping[str, str], arguments: E2ERunArguments) -> dict[str, str]:
    result = {
        "DOCKER_HOST": PINNED_DOCKER_HOST,
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "MEM0_DIR": str(arguments.run_root / "state" / "e2e-mem0-config"),
    }
    for name in COMPOSE_PATH_ENVIRONMENT:
        value = source.get(name)
        if value is None or "\x00" in value or "\n" in value or not Path(value).is_absolute():
            raise NamespaceRunnerError("e2e_child_environment_invalid")
        result[name] = value
    project = _PROJECT.fullmatch(arguments.project_name)
    assert project is not None
    pin_dir = Path(result["MEM0_V5_SOURCE_AUTHORITY_PIN_DIR"])
    pin_parent = Path(
        "/mnt/volume_ams3_1784742570542/infinity-locomo-benchmark/e2e-source-authorities"
    )
    expected = {
        "MEM0_V5_INPUT_DIR": arguments.run_root / "input",
        "MEM0_V5_STATE_DIR": arguments.run_root / "state",
        "MEM0_V5_SECRET_DIR": arguments.run_root / "secrets",
        "MEM0_V5_FAKE_RUNTIME_STATE_DIR": arguments.run_root / "fake-runtime",
        "MEM0_V5_RUNTIME_AUTHORITY_DIR": PINNED_RUNTIME_MIRROR,
        "MEM0_V5_SOURCE_AUTHORITY_DIR": PINNED_PHASE_C,
        "MEM0_V5_SOURCE_AUTHORITY_PIN_SHA256_FILE": pin_dir / "manifest.sha256",
        "MEM0_V5_NODE_EXECUTABLE_SOURCE": PINNED_NODE,
    }
    if (
        pin_dir.parent != pin_parent
        or pin_dir.name != project.group(1)
        or any(Path(result[name]) != path for name, path in expected.items())
    ):
        raise NamespaceRunnerError("e2e_child_environment_correlation_invalid")
    return result


def _load_privileged_support() -> types.ModuleType:
    path = Path(__file__).parent / "namespace_attestation.py"
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or (metadata.st_uid, metadata.st_gid) != (0, 0)
            or stat.S_IMODE(metadata.st_mode) & 0o022
            or metadata.st_size > 64 * 1024
        ):
            raise NamespaceRunnerError("e2e_privileged_support_invalid")
        source = os.read(descriptor, 64 * 1024 + 1)
    except NamespaceRunnerError:
        raise
    except Exception:
        raise NamespaceRunnerError("e2e_privileged_support_invalid") from None
    finally:
        if "descriptor" in locals():
            os.close(descriptor)
    module = types.ModuleType("e2e_namespace_attestation")
    try:
        exec(compile(source, str(path), "exec"), module.__dict__)
    except Exception:
        raise NamespaceRunnerError("e2e_privileged_support_invalid") from None
    return module


def _bounded_communicate(process: subprocess.Popen[bytes]) -> tuple[bytes, bytes]:
    selector = selectors.DefaultSelector()
    streams = (process.stdout, process.stderr)
    if any(stream is None for stream in streams):
        raise NamespaceRunnerError("e2e_namespace_run_failed")
    buffers = [bytearray(), bytearray()]
    for index, stream in enumerate(streams):
        assert stream is not None
        os.set_blocking(stream.fileno(), False)
        selector.register(stream, selectors.EVENT_READ, index)
    deadline = time.monotonic() + _CHILD_TIMEOUT_SECONDS
    try:
        while selector.get_map():
            if time.monotonic() >= deadline:
                _kill_process_group(process)
                raise NamespaceRunnerError("e2e_namespace_run_timeout")
            timeout = max(0.0, min(0.25, deadline - time.monotonic()))
            for key, _events in selector.select(timeout):
                chunk = os.read(key.fileobj.fileno(), 4096)
                if not chunk:
                    selector.unregister(key.fileobj)
                    key.fileobj.close()
                    continue
                buffer = buffers[key.data]
                buffer.extend(chunk)
                if len(buffer) > _MAX_OUTPUT:
                    _kill_process_group(process)
                    raise NamespaceRunnerError("e2e_namespace_output_invalid")
        remaining = max(0.0, deadline - time.monotonic())
        try:
            process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            _kill_process_group(process)
            raise NamespaceRunnerError("e2e_namespace_run_timeout") from None
        return bytes(buffers[0]), bytes(buffers[1])
    except NamespaceRunnerError:
        _kill_process_group(process)
        raise
    except Exception:
        _kill_process_group(process)
        raise NamespaceRunnerError("e2e_namespace_reader_failed") from None
    finally:
        selector.close()


def _kill_process_group(process: subprocess.Popen[Any]) -> None:
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)
    with suppress(Exception):
        process.wait(timeout=5)


def _validate_daemon_process(
    *, pidfile: Path = PINNED_DOCKER_PIDFILE, proc_root: Path = Path("/proc")
) -> None:
    try:
        pid_metadata = os.lstat(pidfile)
        pid_text = pidfile.read_text().strip()
        pid = int(pid_text)
        process_root = proc_root / str(pid)
        process_metadata = os.stat(process_root)
        command = (process_root / "cmdline").read_bytes().split(b"\0")
        uid_map = (process_root / "uid_map").read_text().split()
        gid_map = (process_root / "gid_map").read_text().split()
    except Exception:
        raise NamespaceRunnerError("e2e_docker_process_invalid") from None
    expected_arguments = {
        f"--host={PINNED_DOCKER_HOST}".encode(),
        f"--data-root={PINNED_DOCKER_DATA_ROOT}".encode(),
        f"--exec-root={PINNED_DOCKER_EXEC_ROOT}".encode(),
        f"--pidfile={PINNED_DOCKER_PIDFILE}".encode(),
    }
    if (
        not stat.S_ISREG(pid_metadata.st_mode)
        or (pid_metadata.st_uid, pid_metadata.st_gid) != (EXPECTED_DAEMON_UID, EXPECTED_DAEMON_GID)
        or stat.S_IMODE(pid_metadata.st_mode) & 0o022
        or (process_metadata.st_uid, process_metadata.st_gid)
        != (EXPECTED_DAEMON_UID, EXPECTED_DAEMON_GID)
        or not command
        or Path(os.fsdecode(command[0])).name != "dockerd"
        or not expected_arguments.issubset(set(command))
        or uid_map != ["0", "994", "1", "1", "231072", "65536"]
        or gid_map != ["0", "985", "1", "1", "231072", "65536"]
    ):
        raise NamespaceRunnerError("e2e_docker_process_invalid")


def _validate_socket() -> None:
    try:
        parent = os.lstat(PINNED_DOCKER_SOCKET.parent)
        metadata = os.lstat(PINNED_DOCKER_SOCKET)
    except OSError:
        raise NamespaceRunnerError("e2e_docker_socket_invalid") from None
    if (
        not stat.S_ISDIR(parent.st_mode)
        or (parent.st_uid, parent.st_gid) != (EXPECTED_DAEMON_UID, EXPECTED_DAEMON_GID)
        or stat.S_IMODE(parent.st_mode) != 0o700
        or stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISSOCK(metadata.st_mode)
        or (metadata.st_uid, metadata.st_gid) != (EXPECTED_DAEMON_UID, TRUSTED_SOCKET_GID)
        or stat.S_IMODE(metadata.st_mode) != 0o660
    ):
        raise NamespaceRunnerError("e2e_docker_socket_invalid")


def _validate_owned_directory(path: Path, *, mode: int) -> None:
    try:
        metadata = os.lstat(path)
    except OSError:
        raise NamespaceRunnerError("e2e_docker_path_invalid") from None
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or (metadata.st_uid, metadata.st_gid) != (EXPECTED_DAEMON_UID, EXPECTED_DAEMON_GID)
        or stat.S_IMODE(metadata.st_mode) != mode
    ):
        raise NamespaceRunnerError("e2e_docker_path_invalid")


def _validate_path_chain(path: Path) -> None:
    current = Path("/")
    for part in path.parts[1:]:
        current /= part
        try:
            metadata = os.lstat(current)
        except OSError:
            raise NamespaceRunnerError("e2e_docker_path_invalid") from None
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid not in {0, EXPECTED_DAEMON_UID}
            or stat.S_IMODE(metadata.st_mode) & 0o022
        ):
            raise NamespaceRunnerError("e2e_docker_path_invalid")


def _validate_mapped_path(path: Path, *, directory: bool) -> None:
    try:
        metadata = os.lstat(path)
    except OSError:
        raise NamespaceRunnerError("e2e_runner_path_invalid") from None
    expected_type = stat.S_ISDIR if directory else stat.S_ISREG
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not expected_type(metadata.st_mode)
        or (metadata.st_uid, metadata.st_gid) != (MAPPED_RUNTIME_UID, MAPPED_RUNTIME_GID)
        or stat.S_IMODE(metadata.st_mode) & 0o077
    ):
        raise NamespaceRunnerError("e2e_runner_path_invalid")


def _validate_root_executable(path: Path, *, allow_symlink: bool = False) -> None:
    try:
        metadata = os.lstat(path)
        resolved = path.resolve(strict=True)
        target = os.stat(resolved)
    except OSError:
        raise NamespaceRunnerError("e2e_host_binary_invalid") from None
    if (
        (stat.S_ISLNK(metadata.st_mode) and not allow_symlink)
        or (metadata.st_uid, metadata.st_gid) != (0, 0)
        or stat.S_IMODE(metadata.st_mode) & 0o022
        or not stat.S_ISREG(target.st_mode)
        or (target.st_uid, target.st_gid) != (0, 0)
        or stat.S_IMODE(target.st_mode) & 0o022
        or not stat.S_IMODE(target.st_mode) & 0o111
    ):
        raise NamespaceRunnerError("e2e_host_binary_invalid")


def _validate_wrapper_source() -> None:
    path = Path(__file__)
    try:
        metadata = os.lstat(path)
    except OSError:
        raise NamespaceRunnerError("e2e_wrapper_source_invalid") from None
    expected = PINNED_BENCHMARK_ROOT / "e2e" / "namespace_runner.py"
    if (
        Path.cwd() != PINNED_BENCHMARK_ROOT
        or not path.is_absolute()
        or path != expected
        or path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or (metadata.st_uid, metadata.st_gid) != (0, 0)
        or stat.S_IMODE(metadata.st_mode) & 0o022
    ):
        raise NamespaceRunnerError("e2e_wrapper_source_invalid")


def _validate_ipam(value: Any) -> None:
    if not isinstance(value, Mapping) or set(value) - {
        "Subnet",
        "Gateway",
        "IPRange",
        "AuxiliaryAddresses",
    }:
        raise NamespaceRunnerError("e2e_internal_network_invalid")
    try:
        network = ipaddress.ip_network(value["Subnet"])
        gateway = ipaddress.ip_address(value["Gateway"])
    except Exception:
        raise NamespaceRunnerError("e2e_internal_network_invalid") from None
    if gateway not in network or value.get("AuxiliaryAddresses") not in (None, {}):
        raise NamespaceRunnerError("e2e_internal_network_invalid")


def _mapping(value: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    nested = value.get(key)
    if not isinstance(nested, Mapping):
        raise NamespaceRunnerError("e2e_docker_response_invalid")
    return nested


def _positive_int(value: Any, error: str) -> int:
    if not isinstance(value, int) or value <= 0:
        raise NamespaceRunnerError(error)
    return value


def _nonempty_string(value: Any, error: str) -> str:
    if not isinstance(value, str) or not value:
        raise NamespaceRunnerError(error)
    return value


def _parse_arguments() -> E2ERunArguments:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--runtime-authority-mirror", type=Path, required=True)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--compose-file", type=Path, required=True)
    parser.add_argument("--project-name", required=True)
    parser.add_argument("--host-python", type=Path, required=True)
    parser.add_argument("--adapter-port", type=int, default=19091)
    parser.add_argument("--qdrant-port", type=int, default=6334)
    return E2ERunArguments(**vars(parser.parse_args()))


def main() -> None:
    try:
        result = run(_parse_arguments())
    except NamespaceRunnerError as error:
        raise SystemExit(str(error)) from None
    sys.stdout.write(json.dumps(result, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()

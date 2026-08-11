"""Narrow Docker CLI adapter for cached-only Compose lifecycle and inspection."""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Protocol

from .config import QDRANT_IMAGE, PublishableLaneConfig

DOCKER_BINARY: Final = Path("/usr/bin/docker")
COMPOSE_FILE_NAME: Final = "compose.publishable.yaml"
NETWORK_KEY: Final = "publishable-runtime"
SERVICES: Final = (
    "publishable-relay-anchor",
    "publishable-qdrant",
    "publishable-bridge-a",
    "publishable-bridge-b",
    "publishable-bridge-c",
    "publishable-adapter",
)

_CONTAINER_ID = re.compile(r"^[0-9a-f]{64}$")
_NETWORK_ID = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
_VOLUME_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,254}$")
_COMMAND_TIMEOUT_SECONDS = 180.0
_COMPOSE_WAIT_TIMEOUT_SECONDS = 120
_COMPOSE_STOP_TIMEOUT_SECONDS = 30
_MAX_OUTPUT_BYTES = 16 * 1024 * 1024
_MAX_RUNNING_CONTAINERS = 4096
_MAX_PROJECT_RESOURCES = 4096
_INSPECT_BATCH_SIZE = 128
_PROJECT_CONTAINER_FORMAT = (
    '{"Config":{"Cmd":{{json .Config.Cmd}},"Env":{{json .Config.Env}},'
    '"Image":{{json .Config.Image}},"Labels":{{json .Config.Labels}},'
    '"User":{{json .Config.User}}},"HostConfig":{'
    '"CapAdd":{{json .HostConfig.CapAdd}},"CapDrop":{{json .HostConfig.CapDrop}},'
    '"NetworkMode":{{json .HostConfig.NetworkMode}},"PidMode":{{json .HostConfig.PidMode}},'
    '"PortBindings":{{json .HostConfig.PortBindings}},'
    '"Privileged":{{json .HostConfig.Privileged}},'
    '"PublishAllPorts":{{json .HostConfig.PublishAllPorts}},'
    '"ReadonlyRootfs":{{json .HostConfig.ReadonlyRootfs}},'
    '"SecurityOpt":{{json .HostConfig.SecurityOpt}}},"Id":{{json .Id}},'
    '"Image":{{json .Image}},"Mounts":{{json .Mounts}},'
    '"NetworkSettings":{"Networks":{{json .NetworkSettings.Networks}},'
    '"Ports":{{json .NetworkSettings.Ports}}},"State":{'
    '"Health":{"Status":{{json .State.Health.Status}}},'
    '"Running":{{json .State.Running}},"Status":{{json .State.Status}}}}'
)
_PROJECT_CONTAINER_IDENTITY_FORMAT = (
    '{"Id":{{json .Id}},"Labels":{{json .Config.Labels}}}'
)
_PROJECT_NETWORK_FORMAT = (
    '{"Attachable":{{json .Attachable}},"ConfigOnly":{{json .ConfigOnly}},'
    '"Containers":{{json .Containers}},"Driver":{{json .Driver}},"Id":{{json .Id}},'
    '"Ingress":{{json .Ingress}},"Internal":{{json .Internal}},'
    '"Labels":{{json .Labels}},"Name":{{json .Name}},"Scope":{{json .Scope}}}'
)
_PROJECT_VOLUME_FORMAT = (
    '{"Labels":{{json .Labels}},"Name":{{json .Name}}}'
)


class DockerCliError(RuntimeError):
    """Stable, stderr-free failure at the Docker CLI boundary."""


class CommandRunner(Protocol):
    def run(
        self,
        arguments: tuple[str, ...],
        *,
        environment: Mapping[str, str],
    ) -> bytes: ...


@dataclass(frozen=True, slots=True)
class SubprocessCommandRunner:
    """Production command port with no shell and bounded captured output."""

    timeout_seconds: float = _COMMAND_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, int | float)
            or not 0.001 <= float(self.timeout_seconds) <= _COMMAND_TIMEOUT_SECONDS
        ):
            raise DockerCliError("publishable_docker_timeout_invalid")

    def run(
        self,
        arguments: tuple[str, ...],
        *,
        environment: Mapping[str, str],
    ) -> bytes:
        try:
            completed = subprocess.run(
                arguments,
                check=False,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                env=dict(environment),
                shell=False,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise DockerCliError("publishable_docker_command_timeout") from exc
        except OSError as exc:
            raise DockerCliError("publishable_docker_command_unavailable") from exc
        if completed.returncode != 0:
            raise DockerCliError("publishable_docker_command_failed")
        if len(completed.stdout) > _MAX_OUTPUT_BYTES:
            raise DockerCliError("publishable_docker_output_too_large")
        return completed.stdout


@dataclass(frozen=True, slots=True)
class CachedImages:
    adapter_image_id: str
    qdrant_image_id: str

    def __post_init__(self) -> None:
        if (
            _IMAGE_ID.fullmatch(self.adapter_image_id) is None
            or _IMAGE_ID.fullmatch(self.qdrant_image_id) is None
        ):
            raise DockerCliError("publishable_cached_image_id_invalid")


@dataclass(frozen=True, slots=True)
class ProjectResources:
    containers: tuple[str, ...]
    networks: tuple[str, ...]
    volumes: tuple[str, ...]

    @property
    def empty(self) -> bool:
        return not self.containers and not self.networks and not self.volumes

    def payload(self) -> dict[str, int]:
        return {
            "containers": len(self.containers),
            "networks": len(self.networks),
            "volumes": len(self.volumes),
        }


@dataclass(frozen=True, slots=True)
class ProjectInspection:
    """Immutable exact-project identities and their inspected Docker payloads."""

    project_name: str
    container_ids: Mapping[str, str]
    containers: Mapping[str, Mapping[str, Any]]
    network_id: str
    network: Mapping[str, Any]
    resources: ProjectResourceObservation

    def __post_init__(self) -> None:
        object.__setattr__(self, "container_ids", MappingProxyType(dict(self.container_ids)))
        object.__setattr__(self, "containers", MappingProxyType(dict(self.containers)))
        object.__setattr__(self, "network", MappingProxyType(dict(self.network)))


@dataclass(frozen=True, slots=True)
class ProjectResourceObservation:
    """One adapter-issued snapshot of only exact Compose-project resources."""

    project_name: str
    containers: tuple[str, ...]
    networks: tuple[str, ...]
    volumes: tuple[str, ...]


class DockerCli:
    """Exact cached start, controlled stop, teardown, and inspection operations."""

    def __init__(
        self,
        config: PublishableLaneConfig,
        *,
        config_file: Path,
        runner: CommandRunner | None = None,
        docker_binary: Path = DOCKER_BINARY,
    ) -> None:
        if (
            type(config) is not PublishableLaneConfig
            or not config_file.is_absolute()
            or not docker_binary.is_absolute()
        ):
            raise DockerCliError("publishable_docker_input_invalid")
        self._config = config
        self._config_file_path = config_file
        self._runner = runner or SubprocessCommandRunner()
        self._docker = str(docker_binary)
        self._project_observations: dict[int, ProjectResourceObservation] = {}
        self._environment = {
            "DOCKER_HOST": config.docker_host,
            "LANG": "C.UTF-8",
            "PATH": os.defpath,
        }

    @property
    def compose_file(self) -> Path:
        return self._config.paths.deployment_dir / COMPOSE_FILE_NAME

    @property
    def config_file(self) -> Path:
        return self._config_file_path

    @property
    def network_name(self) -> str:
        return f"{self._config.project_name}_{NETWORK_KEY}"

    def inspect_cached_images(self) -> CachedImages:
        """Resolve both required references locally; this command can never pull."""

        adapter = self._image(self._config.adapter_image_id, "adapter")
        qdrant = self._image(QDRANT_IMAGE, "qdrant")
        if adapter.get("Id") != self._config.adapter_image_id:
            raise DockerCliError("publishable_cached_adapter_image_mismatch")
        qdrant_id = qdrant.get("Id")
        if type(qdrant_id) is not str or _IMAGE_ID.fullmatch(qdrant_id) is None:
            raise DockerCliError("publishable_cached_qdrant_image_invalid")
        digest = QDRANT_IMAGE.split("@", 1)[1]
        expected_repo_digest = f"qdrant/qdrant@{digest}"
        repo_digests = qdrant.get("RepoDigests")
        if not isinstance(repo_digests, list) or expected_repo_digest not in repo_digests:
            raise DockerCliError("publishable_cached_qdrant_digest_mismatch")
        return CachedImages(
            adapter_image_id=self._config.adapter_image_id,
            qdrant_image_id=qdrant_id,
        )

    def start(self, *, mode: str) -> None:
        """Start with Compose's pull and build paths explicitly disabled."""

        self._run_compose(
            "up",
            "--detach",
            "--pull",
            "never",
            "--no-build",
            "--wait",
            "--wait-timeout",
            str(_COMPOSE_WAIT_TIMEOUT_SECONDS),
            mode=mode,
        )

    def stop(self, *, mode: str) -> None:
        """Request a bounded controlled stop while retaining bind-backed state."""

        self._run_compose(
            "stop",
            "--timeout",
            str(_COMPOSE_STOP_TIMEOUT_SECONDS),
            mode=mode,
        )

    def require_stopped(self, *, mode: str) -> None:
        """Require every exact service container to be stopped, not removed."""

        containers = self.inspect_containers(self.container_ids(mode=mode))
        for value in containers.values():
            state = value.get("State")
            if (
                not isinstance(state, Mapping)
                or state.get("Running") is not False
                or state.get("Status") != "exited"
            ):
                raise DockerCliError("publishable_compose_controlled_stop_invalid")

    def require_project_stopped(self, *, mode: str) -> None:
        """Verify exact project containers through the process-free projection."""

        containers = self.inspect_project_containers(self.container_ids(mode=mode))
        self._require_project_container_labels(containers)
        for value in containers.values():
            state = value.get("State")
            if (
                not isinstance(state, Mapping)
                or state.get("Running") is not False
                or state.get("Status") != "exited"
            ):
                raise DockerCliError("publishable_compose_controlled_stop_invalid")

    def teardown(self, *, mode: str) -> None:
        """Remove only the configured exact Compose project's Docker resources."""

        self._run_compose(
            "down",
            "--timeout",
            str(_COMPOSE_STOP_TIMEOUT_SECONDS),
            "--volumes",
            "--remove-orphans",
            mode=mode,
        )

    def project_resources(self) -> ProjectResources:
        """List only resources carrying this exact Compose project label."""

        label = f"label=com.docker.compose.project={self._config.project_name}"
        calls = (
            (
                "containers",
                ("container", "ls", "--all", "--quiet", "--no-trunc", "--filter", label),
                _CONTAINER_ID,
            ),
            (
                "networks",
                ("network", "ls", "--quiet", "--no-trunc", "--filter", label),
                _NETWORK_ID,
            ),
            (
                "volumes",
                ("volume", "ls", "--quiet", "--filter", label),
                _VOLUME_NAME,
            ),
        )
        inventories: dict[str, tuple[str, ...]] = {}
        failures: list[DockerCliError] = []
        for kind, arguments, pattern in calls:
            try:
                inventories[kind] = self._resource_names(self._run(*arguments), pattern=pattern)
            except DockerCliError as exc:
                failures.append(exc)
        if failures:
            raise DockerCliError("publishable_project_inventory_failed") from failures[0]
        return ProjectResources(
            containers=inventories["containers"],
            networks=inventories["networks"],
            volumes=inventories["volumes"],
        )

    def inspect_project(self, *, mode: str) -> ProjectInspection:
        """Inspect only the complete, unambiguous exact Compose project."""

        container_ids = self.container_ids(mode=mode)
        resources = self.observe_project_resources()
        if (
            set(resources.containers) != set(container_ids.values())
            or len(resources.networks) != 1
            or resources.volumes
        ):
            raise DockerCliError("publishable_project_runtime_inventory_invalid")

        containers = self.inspect_project_containers(container_ids)
        self._require_project_container_labels(containers)
        network_id = resources.networks[0]
        network = self._inspect_network_id(network_id)
        self._require_project_network_identity(network, network_id=network_id)
        final_resources = self.observe_project_resources()
        if final_resources != resources:
            raise DockerCliError("publishable_project_runtime_inventory_changed")
        return ProjectInspection(
            project_name=self._config.project_name,
            container_ids=container_ids,
            containers=containers,
            network_id=network_id,
            network=network,
            resources=final_resources,
        )

    def observe_project_resources(self) -> ProjectResourceObservation:
        """Bind an exact, label-scoped resource snapshot to this adapter instance."""

        first = self.project_resources()
        self._require_observed_project_labels(first)
        second = self.project_resources()
        if second != first:
            raise DockerCliError("publishable_project_inventory_changed")
        self._require_observed_project_labels(second)
        final = self.project_resources()
        if final != second:
            raise DockerCliError("publishable_project_inventory_changed")
        observation = ProjectResourceObservation(
            project_name=self._config.project_name,
            containers=final.containers,
            networks=final.networks,
            volumes=final.volumes,
        )
        self._project_observations[id(observation)] = observation
        return observation

    def require_project_absent(
        self,
        *observed: ProjectResourceObservation,
    ) -> ProjectResources:
        """Prove label-scoped zero and absence of every prior exact Docker ID."""

        if not observed or any(not self._valid_project_observation(item) for item in observed):
            raise DockerCliError("publishable_project_absence_input_invalid")
        container_ids = tuple(
            dict.fromkeys(
                identifier for observation in observed for identifier in observation.containers
            )
        )
        network_ids = tuple(
            dict.fromkeys(
                identifier for observation in observed for identifier in observation.networks
            )
        )
        volume_names = tuple(
            dict.fromkeys(name for observation in observed for name in observation.volumes)
        )

        failures: list[DockerCliError] = []
        resources: ProjectResources | None = None
        try:
            initial = self.project_resources()
            if not initial.empty:
                failures.append(DockerCliError("publishable_project_resources_remain"))
        except DockerCliError as exc:
            failures.append(exc)

        for identifier in container_ids:
            try:
                values = self._resource_names(
                    self._run(
                        "container",
                        "ls",
                        "--all",
                        "--quiet",
                        "--no-trunc",
                        "--filter",
                        f"id={identifier}",
                    ),
                    pattern=_CONTAINER_ID,
                )
                if values:
                    failures.append(DockerCliError("publishable_project_container_id_remains"))
            except DockerCliError as exc:
                failures.append(exc)
        for identifier in network_ids:
            try:
                networks = self._resource_names(
                    self._run(
                        "network",
                        "ls",
                        "--quiet",
                        "--no-trunc",
                        "--filter",
                        f"id={identifier}",
                    ),
                    pattern=_NETWORK_ID,
                )
                if networks:
                    failures.append(DockerCliError("publishable_project_network_id_remains"))
            except DockerCliError as exc:
                failures.append(exc)
        for name in volume_names:
            try:
                volumes = self._resource_names(
                    self._run(
                        "volume",
                        "ls",
                        "--quiet",
                        "--filter",
                        f"name=^{re.escape(name)}$",
                    ),
                    pattern=_VOLUME_NAME,
                )
                if volumes:
                    failures.append(DockerCliError("publishable_project_volume_name_remains"))
            except DockerCliError as exc:
                failures.append(exc)
        try:
            resources = self.project_resources()
            if not resources.empty:
                failures.append(DockerCliError("publishable_project_resources_remain"))
        except DockerCliError as exc:
            failures.append(exc)
        if failures or resources is None:
            raise DockerCliError("publishable_project_absence_failed") from failures[0]
        return resources

    def _valid_project_observation(self, observed: object) -> bool:
        return (
            type(observed) is ProjectResourceObservation
            and self._project_observations.get(id(observed)) is observed
            and observed.project_name == self._config.project_name
            and len(set(observed.containers)) == len(observed.containers)
            and len(set(observed.networks)) == len(observed.networks)
            and len(set(observed.volumes)) == len(observed.volumes)
            and all(
                _CONTAINER_ID.fullmatch(value) is not None for value in observed.containers
            )
            and all(_NETWORK_ID.fullmatch(value) is not None for value in observed.networks)
            and all(_VOLUME_NAME.fullmatch(value) is not None for value in observed.volumes)
        )

    def container_ids(self, *, mode: str) -> dict[str, str]:
        result: dict[str, str] = {}
        for service in SERVICES:
            raw = self._run_compose(
                "ps",
                "--all",
                "--quiet",
                service,
                mode=mode,
            )
            try:
                values = raw.decode("ascii", "strict").splitlines()
            except UnicodeDecodeError as exc:
                raise DockerCliError("publishable_compose_service_identity_invalid") from exc
            if len(values) != 1 or _CONTAINER_ID.fullmatch(values[0]) is None:
                raise DockerCliError("publishable_compose_service_identity_invalid")
            result[service] = values[0]
        if len(set(result.values())) != len(SERVICES):
            raise DockerCliError("publishable_compose_service_identity_duplicate")
        return result

    def inspect_containers(self, container_ids: Mapping[str, str]) -> dict[str, Mapping[str, Any]]:
        if set(container_ids) != set(SERVICES):
            raise DockerCliError("publishable_container_inventory_invalid")
        ordered = tuple(container_ids[name] for name in SERVICES)
        value = self._json(self._run("inspect", *ordered))
        if not isinstance(value, list) or len(value) != len(SERVICES):
            raise DockerCliError("publishable_container_inspect_invalid")
        by_id: dict[str, Mapping[str, Any]] = {}
        for item in value:
            if not isinstance(item, Mapping) or item.get("Id") not in ordered:
                raise DockerCliError("publishable_container_inspect_invalid")
            identifier = item["Id"]
            if identifier in by_id:
                raise DockerCliError("publishable_container_inspect_invalid")
            by_id[identifier] = item
        if set(by_id) != set(ordered):
            raise DockerCliError("publishable_container_inspect_invalid")
        return {name: by_id[container_ids[name]] for name in SERVICES}

    def inspect_project_containers(
        self,
        container_ids: Mapping[str, str],
    ) -> dict[str, Mapping[str, Any]]:
        """Read only the project fields needed for attestation, excluding process identity."""

        if set(container_ids) != set(SERVICES):
            raise DockerCliError("publishable_container_inventory_invalid")
        ordered = tuple(container_ids[name] for name in SERVICES)
        if len(set(ordered)) != len(SERVICES) or any(
            _CONTAINER_ID.fullmatch(identifier) is None for identifier in ordered
        ):
            raise DockerCliError("publishable_container_inventory_invalid")
        values = self._json_lines(
            self._run(
                "container",
                "inspect",
                "--format",
                _PROJECT_CONTAINER_FORMAT,
                *ordered,
            )
        )
        by_id = self._objects_by_identity(values, expected=ordered, key="Id")
        return {name: by_id[container_ids[name]] for name in SERVICES}

    def inspect_network(self) -> Mapping[str, Any]:
        value = self._json(self._run("network", "inspect", self.network_name))
        if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], Mapping):
            raise DockerCliError("publishable_network_inspect_invalid")
        return value[0]

    def inspect_running_containers(self) -> dict[str, Mapping[str, Any]]:
        """Inspect the daemon's exhaustive running inventory without filters."""

        raw = self._run("container", "ls", "--quiet", "--no-trunc")
        try:
            identifiers = raw.decode("ascii", "strict").splitlines()
        except UnicodeDecodeError as exc:
            raise DockerCliError("publishable_running_inventory_invalid") from exc
        if (
            not identifiers
            or len(identifiers) > _MAX_RUNNING_CONTAINERS
            or len(set(identifiers)) != len(identifiers)
            or any(_CONTAINER_ID.fullmatch(item) is None for item in identifiers)
        ):
            raise DockerCliError("publishable_running_inventory_invalid")
        result: dict[str, Mapping[str, Any]] = {}
        for offset in range(0, len(identifiers), _INSPECT_BATCH_SIZE):
            batch = identifiers[offset : offset + _INSPECT_BATCH_SIZE]
            value = self._json(self._run("inspect", *batch))
            if not isinstance(value, list) or len(value) != len(batch):
                raise DockerCliError("publishable_running_inventory_inspect_invalid")
            for item in value:
                if not isinstance(item, Mapping) or item.get("Id") not in batch:
                    raise DockerCliError("publishable_running_inventory_inspect_invalid")
                identifier = item["Id"]
                if identifier in result:
                    raise DockerCliError("publishable_running_inventory_inspect_invalid")
                result[identifier] = item
        if set(result) != set(identifiers):
            raise DockerCliError("publishable_running_inventory_inspect_invalid")
        return result

    def require_all_internal_ports(self, anchor_id: str) -> None:
        if _CONTAINER_ID.fullmatch(anchor_id) is None:
            raise DockerCliError("publishable_anchor_identity_invalid")
        self._run(
            "exec",
            anchor_id,
            "python",
            "-m",
            "publishable_mem0_v5.relay",
            "health",
            "--component",
            "all",
        )

    def _image(self, reference: str, label: str) -> Mapping[str, Any]:
        value = self._json(self._run("image", "inspect", reference))
        if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], Mapping):
            raise DockerCliError(f"publishable_cached_{label}_image_unavailable")
        return value[0]

    def _inspect_network_id(self, network_id: str) -> Mapping[str, Any]:
        if _NETWORK_ID.fullmatch(network_id) is None:
            raise DockerCliError("publishable_network_identity_invalid")
        values = self._json_lines(
            self._run("network", "inspect", "--format", _PROJECT_NETWORK_FORMAT, network_id)
        )
        if len(values) != 1 or values[0].get("Id") != network_id:
            raise DockerCliError("publishable_network_inspect_invalid")
        return values[0]

    def _require_observed_project_labels(self, resources: ProjectResources) -> None:
        if resources.containers:
            values = self._json_lines(
                self._run(
                    "container",
                    "inspect",
                    "--format",
                    _PROJECT_CONTAINER_IDENTITY_FORMAT,
                    *resources.containers,
                )
            )
            containers = self._objects_by_identity(
                values,
                expected=resources.containers,
                key="Id",
            )
            for value in containers.values():
                self._require_exact_project_label(value.get("Labels"))
        for network_id in resources.networks:
            network = self._inspect_network_id(network_id)
            self._require_exact_project_label(network.get("Labels"))
        if resources.volumes:
            values = self._json_lines(
                self._run(
                    "volume",
                    "inspect",
                    "--format",
                    _PROJECT_VOLUME_FORMAT,
                    *resources.volumes,
                )
            )
            volumes = self._objects_by_identity(
                values,
                expected=resources.volumes,
                key="Name",
            )
            for value in volumes.values():
                self._require_exact_project_label(value.get("Labels"))

    def _require_exact_project_label(self, labels: object) -> None:
        if (
            not isinstance(labels, Mapping)
            or labels.get("com.docker.compose.project") != self._config.project_name
        ):
            raise DockerCliError("publishable_project_resource_labels_invalid")

    @staticmethod
    def _objects_by_identity(
        values: tuple[Mapping[str, Any], ...],
        *,
        expected: tuple[str, ...],
        key: str,
    ) -> dict[str, Mapping[str, Any]]:
        if len(values) != len(expected):
            raise DockerCliError("publishable_project_resource_inspect_invalid")
        result: dict[str, Mapping[str, Any]] = {}
        for value in values:
            identifier = value.get(key)
            if type(identifier) is not str or identifier not in expected or identifier in result:
                raise DockerCliError("publishable_project_resource_inspect_invalid")
            result[identifier] = value
        if set(result) != set(expected):
            raise DockerCliError("publishable_project_resource_inspect_invalid")
        return result

    def _require_project_container_labels(
        self,
        containers: Mapping[str, Mapping[str, Any]],
    ) -> None:
        for service in SERVICES:
            config = containers[service].get("Config")
            if not isinstance(config, Mapping):
                raise DockerCliError("publishable_project_container_labels_invalid")
            labels = config.get("Labels")
            if (
                not isinstance(labels, Mapping)
                or labels.get("com.docker.compose.project") != self._config.project_name
                or labels.get("com.docker.compose.service") != service
                or labels.get("com.docker.compose.container-number") != "1"
            ):
                raise DockerCliError("publishable_project_container_labels_invalid")

    def _require_project_network_identity(
        self,
        network: Mapping[str, Any],
        *,
        network_id: str,
    ) -> None:
        labels = network.get("Labels")
        if (
            network.get("Id") != network_id
            or network.get("Name") != self.network_name
            or not isinstance(labels, Mapping)
            or labels.get("com.docker.compose.project") != self._config.project_name
            or labels.get("com.docker.compose.network") != NETWORK_KEY
        ):
            raise DockerCliError("publishable_project_network_identity_invalid")

    def _compose_prefix(self) -> tuple[str, ...]:
        return (
            "compose",
            "--project-name",
            self._config.project_name,
            "--project-directory",
            str(self._config.paths.deployment_dir),
            "--file",
            str(self.compose_file),
        )

    def _run_compose(self, *arguments: str, mode: str) -> bytes:
        if mode not in {"create", "reopen"}:
            raise DockerCliError("publishable_compose_mode_invalid")
        environment = {
            **self._environment,
            **self._config.compose_environment(
                config_file=self._config_file_path,
                fleet_mode=mode,
            ),
        }
        return self._run(
            *self._compose_prefix(),
            *arguments,
            environment=environment,
        )

    def _run(
        self,
        *arguments: str,
        environment: Mapping[str, str] | None = None,
    ) -> bytes:
        return self._runner.run(
            (self._docker, "--host", self._config.docker_host, *arguments),
            environment=environment or self._environment,
        )

    @staticmethod
    def _resource_names(raw: bytes, *, pattern: re.Pattern[str]) -> tuple[str, ...]:
        try:
            values = tuple(raw.decode("ascii", "strict").splitlines())
        except UnicodeDecodeError as exc:
            raise DockerCliError("publishable_project_inventory_invalid") from exc
        if (
            len(values) > _MAX_PROJECT_RESOURCES
            or len(set(values)) != len(values)
            or any(pattern.fullmatch(value) is None for value in values)
        ):
            raise DockerCliError("publishable_project_inventory_invalid")
        return tuple(sorted(values))

    @staticmethod
    def _json(raw: bytes) -> object:
        try:
            return json.loads(
                raw,
                object_pairs_hook=_unique_json_object,
                parse_constant=_reject_json_constant,
            )
        except (UnicodeDecodeError, ValueError) as exc:
            raise DockerCliError("publishable_docker_json_invalid") from exc

    @classmethod
    def _json_lines(cls, raw: bytes) -> tuple[Mapping[str, Any], ...]:
        try:
            lines = raw.decode("utf-8", "strict").splitlines()
        except UnicodeDecodeError as exc:
            raise DockerCliError("publishable_docker_json_invalid") from exc
        if not lines or len(lines) > _MAX_PROJECT_RESOURCES or any(not line for line in lines):
            raise DockerCliError("publishable_docker_json_invalid")
        result: list[Mapping[str, Any]] = []
        for line in lines:
            value = cls._json(line.encode("utf-8"))
            if not isinstance(value, Mapping):
                raise DockerCliError("publishable_docker_json_invalid")
            result.append(value)
        return tuple(result)


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate Docker JSON key")
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> None:
    raise ValueError("invalid Docker JSON constant")


__all__ = (
    "COMPOSE_FILE_NAME",
    "DOCKER_BINARY",
    "NETWORK_KEY",
    "SERVICES",
    "CachedImages",
    "CommandRunner",
    "DockerCli",
    "DockerCliError",
    "ProjectInspection",
    "ProjectResourceObservation",
    "ProjectResources",
    "SubprocessCommandRunner",
)

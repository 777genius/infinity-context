"""Narrow Docker CLI adapter for cached-only Compose lifecycle and inspection."""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
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
_IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
_COMMAND_TIMEOUT_SECONDS = 180.0
_MAX_OUTPUT_BYTES = 16 * 1024 * 1024
_MAX_RUNNING_CONTAINERS = 4096
_INSPECT_BATCH_SIZE = 128


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
        except (OSError, subprocess.TimeoutExpired) as exc:
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


class DockerCli:
    """Only the exact read/start operations admitted by this deployment."""

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

        if mode not in {"create", "reopen"}:
            raise DockerCliError("publishable_compose_mode_invalid")
        environment = {
            **self._environment,
            **self._config.compose_environment(
                config_file=self._config_file_path,
                fleet_mode=mode,
            ),
        }
        self._run(
            *self._compose_prefix(),
            "up",
            "--detach",
            "--pull",
            "never",
            "--no-build",
            "--wait",
            environment=environment,
        )

    def container_ids(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for service in SERVICES:
            raw = self._run(
                *self._compose_prefix(),
                "ps",
                "--all",
                "--quiet",
                service,
            )
            values = raw.decode("ascii", "strict").splitlines()
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
    def _json(raw: bytes) -> object:
        try:
            return json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DockerCliError("publishable_docker_json_invalid") from exc


__all__ = (
    "COMPOSE_FILE_NAME",
    "DOCKER_BINARY",
    "NETWORK_KEY",
    "SERVICES",
    "CachedImages",
    "CommandRunner",
    "DockerCli",
    "DockerCliError",
    "SubprocessCommandRunner",
)

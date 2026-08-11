from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path

import pytest
from publishable_mem0_v5.acceptance import _cleanup_exact_project
from publishable_mem0_v5.config import PINNED_DOCKER_HOST, PublishableLaneConfig
from publishable_mem0_v5.docker_cli import (
    SERVICES,
    DockerCli,
    DockerCliError,
    ProjectResourceObservation,
)
from publishable_mem0_v5.inventory_scope import PROJECT_INVENTORY_SCOPE
from test_publishable_deployment import _config

_NETWORK_ID = "e" * 64
_UNRELATED_CONTAINER_ID = "f" * 64
_UNRELATED_NETWORK_ID = "d" * 64
_MISMATCH_CONTAINER_ID = "c" * 64


class ProjectInventoryRunner:
    def __init__(self, config: PublishableLaneConfig) -> None:
        self.config = config
        self.calls: list[tuple[str, ...]] = []
        self.container_ids = {
            service: f"{index:064x}" for index, service in enumerate(SERVICES, start=1)
        }
        self.known_container_ids = set(self.container_ids.values())
        self.project_container_inventory = tuple(self.container_ids.values())
        self.project_network_inventory = (_NETWORK_ID,)
        self.project_volume_inventory: tuple[str, ...] = ()
        self.compose_overrides: dict[str, bytes] = {}
        self.container_label_overrides: dict[str, dict[str, str]] = {}
        self.project_only_container_ids: set[str] = set()
        self.network_id_in_payload = _NETWORK_ID
        self.network_name_in_payload = f"{config.project_name}_publishable-runtime"
        self.network_label_in_payload = "publishable-runtime"
        self.network_project_label_in_payload = config.project_name
        self.volume_project_label_overrides: dict[str, str] = {}
        self.torn_down = False
        self.exact_container_residue: set[str] = set()
        self.exact_network_residue: set[str] = set()
        self.exact_volume_residue: set[str] = set()
        self.container_inspect_override: bytes | None = None
        self.inventory_sequence: list[tuple[str, ...]] = []

    def run(
        self,
        arguments: tuple[str, ...],
        *,
        environment: Mapping[str, str],
    ) -> bytes:
        del environment
        assert arguments[:3] == ("/usr/bin/docker", "--host", PINNED_DOCKER_HOST)
        self.calls.append(arguments)
        command = arguments[3:]
        if command[0] == "compose":
            if "down" in command:
                self.torn_down = True
                return b""
            service = command[-1]
            assert "ps" in command
            return self.compose_overrides.get(
                service,
                f"{self.container_ids[service]}\n".encode("ascii"),
            )
        if command[:2] == ("container", "ls"):
            return self._container_list(command)
        if command[:2] == ("network", "ls"):
            return self._network_list(command)
        if command[:2] == ("volume", "ls"):
            project_filter = self._project_filter
            filters = _filters(command)
            if filters == (project_filter,):
                return _lines(() if self.torn_down else self.project_volume_inventory)
            if len(filters) == 1 and filters[0].startswith("name=^"):
                for name in self.exact_volume_residue:
                    if f"name=^{re.escape(name)}$" in filters:
                        return _lines((name,))
                return b""
            raise AssertionError(command)
        if command[:2] == ("container", "inspect"):
            assert command[2] == "--format"
            requested = command[4:]
            assert requested
            assert _UNRELATED_CONTAINER_ID not in requested
            if self.container_inspect_override is not None:
                return self.container_inspect_override
            values = [
                self._container_payload(service, identifier)
                for service, identifier in self.container_ids.items()
                if identifier in requested
            ]
            values.extend(
                {
                    "Id": identifier,
                    "Labels": {"com.docker.compose.project": self.config.project_name},
                }
                for identifier in self.project_only_container_ids
                if identifier in requested
            )
            return _json_lines(values)
        if command[:2] == ("network", "inspect"):
            assert command[2] == "--format"
            assert command[-1] == _NETWORK_ID
            return _json_lines(
                (
                    {
                        "Id": self.network_id_in_payload,
                        "Name": self.network_name_in_payload,
                        "Labels": {
                            "com.docker.compose.project": self.network_project_label_in_payload,
                            "com.docker.compose.network": self.network_label_in_payload,
                        },
                    },
                )
            )
        if command[:2] == ("volume", "inspect"):
            assert command[2] == "--format"
            return _json_lines(
                {
                    "Name": name,
                    "Labels": {
                        "com.docker.compose.project": self.volume_project_label_overrides.get(
                            name,
                            self.config.project_name,
                        )
                    },
                }
                for name in command[4:]
            )
        raise AssertionError(arguments)

    @property
    def _project_filter(self) -> str:
        return f"label=com.docker.compose.project={self.config.project_name}"

    def _container_list(self, command: tuple[str, ...]) -> bytes:
        filters = _filters(command)
        assert len(filters) == 1
        value = filters[0]
        if value == self._project_filter:
            if self.torn_down:
                return b""
            if self.inventory_sequence:
                return _lines(self.inventory_sequence.pop(0))
            return _lines(self.project_container_inventory)
        assert value.startswith("id=")
        identifier = value.removeprefix("id=")
        assert identifier in self.known_container_ids
        return _lines((identifier,)) if identifier in self.exact_container_residue else b""

    def _network_list(self, command: tuple[str, ...]) -> bytes:
        filters = _filters(command)
        assert len(filters) == 1
        value = filters[0]
        if value == self._project_filter:
            return _lines(() if self.torn_down else self.project_network_inventory)
        assert value.startswith("id=")
        identifier = value.removeprefix("id=")
        return _lines((identifier,)) if identifier in self.exact_network_residue else b""

    def _container_payload(self, service: str, identifier: str) -> dict[str, object]:
        labels = {
            "com.docker.compose.project": self.config.project_name,
            "com.docker.compose.service": service,
            "com.docker.compose.container-number": "1",
        }
        labels.update(self.container_label_overrides.get(service, {}))
        return {"Id": identifier, "Config": {"Labels": labels}, "Labels": labels}


def test_project_inspection_uses_only_filtered_inventory_and_projected_exact_ids(
    tmp_path: Path,
) -> None:
    config, _proc_root = _config(tmp_path)
    runner = ProjectInventoryRunner(config)
    docker = _docker(config, tmp_path, runner)

    observed = docker.inspect_project(mode="create")

    assert dict(observed.container_ids) == runner.container_ids
    assert observed.resources.containers == tuple(runner.container_ids.values())
    assert observed.network_id == _NETWORK_ID
    assert all("--filter" in call for call in _resource_lists(runner.calls))
    assert not [call for call in runner.calls if call[3] == "inspect"]
    container_inspects = [
        call for call in runner.calls if call[3:5] == ("container", "inspect")
    ]
    assert container_inspects
    assert all("--format" in call for call in container_inspects)
    full_runtime_formats = [call[6] for call in container_inspects if '"State":{' in call[6]]
    assert full_runtime_formats
    for call in container_inspects:
        expression = call[6]
        selectors = set(re.findall(r"\.State(?:\.[A-Za-z]+)*", expression))
        if expression in full_runtime_formats:
            assert selectors == {
                ".State.Health.Status",
                ".State.Running",
                ".State.Status",
            }
        else:
            assert not selectors
        assert re.search(r"\{\{[^{}]*\.(?=\s*\}\})", expression) is None
    assert all(_UNRELATED_CONTAINER_ID not in call for call in runner.calls)
    assert all(_UNRELATED_NETWORK_ID not in call for call in runner.calls)


def test_project_inventory_race_is_rejected_fail_closed(tmp_path: Path) -> None:
    config, _proc_root = _config(tmp_path)
    runner = ProjectInventoryRunner(config)
    runner.inventory_sequence = [
        runner.project_container_inventory,
        runner.project_container_inventory[:-1],
    ]

    with pytest.raises(DockerCliError, match="publishable_project_inventory_changed"):
        _docker(config, tmp_path, runner).inspect_project(mode="create")


def test_project_container_inspect_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    config, _proc_root = _config(tmp_path)
    runner = ProjectInventoryRunner(config)
    identifier = runner.container_ids[SERVICES[0]]
    runner.container_inspect_override = (
        f'{{"Id":"{identifier}","Id":"{identifier}","Labels":{{}}}}\n'.encode()
    )

    with pytest.raises(DockerCliError, match="publishable_docker_json_invalid"):
        _docker(config, tmp_path, runner).inspect_project(mode="create")


def test_project_inspection_rejects_duplicate_compose_service_identity(tmp_path: Path) -> None:
    config, _proc_root = _config(tmp_path)
    runner = ProjectInventoryRunner(config)
    first, second = SERVICES[:2]
    runner.container_ids[second] = runner.container_ids[first]
    runner.project_container_inventory = tuple(dict.fromkeys(runner.container_ids.values()))

    with pytest.raises(DockerCliError, match="publishable_compose_service_identity_duplicate"):
        _docker(config, tmp_path, runner).inspect_project(mode="create")


def test_project_inspection_rejects_duplicate_label_inventory_identity(tmp_path: Path) -> None:
    config, _proc_root = _config(tmp_path)
    runner = ProjectInventoryRunner(config)
    runner.project_container_inventory = (
        runner.project_container_inventory[0],
        *runner.project_container_inventory,
    )

    with pytest.raises(DockerCliError, match="publishable_project_inventory_failed"):
        _docker(config, tmp_path, runner).inspect_project(mode="create")


def test_project_inspection_rejects_compose_and_label_inventory_mismatch(tmp_path: Path) -> None:
    config, _proc_root = _config(tmp_path)
    runner = ProjectInventoryRunner(config)
    runner.project_container_inventory = (
        *runner.project_container_inventory[:-1],
        _MISMATCH_CONTAINER_ID,
    )
    runner.project_only_container_ids.add(_MISMATCH_CONTAINER_ID)

    with pytest.raises(DockerCliError, match="publishable_project_runtime_inventory_invalid"):
        _docker(config, tmp_path, runner).inspect_project(mode="create")


def test_compose_identity_non_ascii_is_a_stable_fail_closed_error(tmp_path: Path) -> None:
    config, _proc_root = _config(tmp_path)
    runner = ProjectInventoryRunner(config)
    runner.compose_overrides[SERVICES[-1]] = b"\xff\n"

    with pytest.raises(DockerCliError, match="publishable_compose_service_identity_invalid"):
        _docker(config, tmp_path, runner).inspect_project(mode="reopen")

    assert not _resource_lists(runner.calls)


def test_project_inspection_rejects_cross_project_container_label(tmp_path: Path) -> None:
    config, _proc_root = _config(tmp_path)
    runner = ProjectInventoryRunner(config)
    runner.container_label_overrides[SERVICES[-1]] = {
        "com.docker.compose.project": "mem0-v5-publishable-other-lane"
    }

    with pytest.raises(DockerCliError, match="publishable_project_resource_labels_invalid"):
        _docker(config, tmp_path, runner).inspect_project(mode="create")


@pytest.mark.parametrize("resource", ("network", "volume"))
def test_project_observation_rejects_cross_project_resource_label(
    tmp_path: Path,
    resource: str,
) -> None:
    config, _proc_root = _config(tmp_path)
    runner = ProjectInventoryRunner(config)
    if resource == "network":
        runner.network_project_label_in_payload = "mem0-v5-publishable-other-lane"
    else:
        volume = f"{config.project_name}_state"
        runner.project_volume_inventory = (volume,)
        runner.volume_project_label_overrides[volume] = "mem0-v5-publishable-other-lane"

    with pytest.raises(DockerCliError, match="publishable_project_resource_labels_invalid"):
        _docker(config, tmp_path, runner).observe_project_resources()


@pytest.mark.parametrize(
    ("label", "value"),
    (
        ("com.docker.compose.service", "publishable-wrong-service"),
        ("com.docker.compose.container-number", "2"),
    ),
)
def test_project_inspection_rejects_ambiguous_service_labels(
    tmp_path: Path,
    label: str,
    value: str,
) -> None:
    config, _proc_root = _config(tmp_path)
    runner = ProjectInventoryRunner(config)
    runner.container_label_overrides[SERVICES[-1]] = {label: value}

    with pytest.raises(DockerCliError, match="publishable_project_container_labels_invalid"):
        _docker(config, tmp_path, runner).inspect_project(mode="create")


@pytest.mark.parametrize("field", ("id", "name", "label"))
def test_project_inspection_rejects_ambiguous_network_identity(
    tmp_path: Path,
    field: str,
) -> None:
    config, _proc_root = _config(tmp_path)
    runner = ProjectInventoryRunner(config)
    if field == "id":
        runner.network_id_in_payload = _UNRELATED_NETWORK_ID
    elif field == "name":
        runner.network_name_in_payload = f"{config.project_name}_wrong-network"
    else:
        runner.network_label_in_payload = "wrong-network"

    expected = (
        "publishable_network_inspect_invalid"
        if field == "id"
        else "publishable_project_network_identity_invalid"
    )
    with pytest.raises(DockerCliError, match=expected):
        _docker(config, tmp_path, runner).inspect_project(mode="create")


def test_project_absence_rejects_fabricated_observation_without_docker_calls(
    tmp_path: Path,
) -> None:
    config, _proc_root = _config(tmp_path)
    runner = ProjectInventoryRunner(config)
    docker = _docker(config, tmp_path, runner)
    fabricated = ProjectResourceObservation(
        project_name=config.project_name,
        containers=(_UNRELATED_CONTAINER_ID,),
        networks=(),
        volumes=(),
    )

    with pytest.raises(DockerCliError, match="publishable_project_absence_input_invalid"):
        docker.require_project_absent(fabricated)

    assert runner.calls == []


def test_project_absence_proves_label_zero_and_every_observed_exact_id(
    tmp_path: Path,
) -> None:
    config, _proc_root = _config(tmp_path)
    runner = ProjectInventoryRunner(config)
    docker = _docker(config, tmp_path, runner)
    create = docker.inspect_project(mode="create").resources
    runner.container_ids = {
        service: f"{index + 16:064x}" for index, service in enumerate(SERVICES, start=1)
    }
    runner.known_container_ids.update(runner.container_ids.values())
    runner.project_container_inventory = tuple(runner.container_ids.values())
    reopen = docker.inspect_project(mode="reopen").resources
    call_offset = len(runner.calls)
    runner.torn_down = True

    resources = docker.require_project_absent(create, reopen)

    assert resources.empty
    final_calls = runner.calls[call_offset:]
    assert not [call for call in final_calls if "inspect" in call]
    id_filters = {
        value
        for call in final_calls
        for value in _filters(call[3:])
        if value.startswith("id=")
    }
    assert id_filters == {
        *(f"id={identifier}" for identifier in runner.known_container_ids),
        f"id={_NETWORK_ID}",
    }
    project_lists = [
        call for call in final_calls if runner._project_filter in _filters(call[3:])
    ]
    assert len(project_lists) == 6


@pytest.mark.parametrize("residue", ("label", "old-container", "old-network"))
def test_project_absence_rejects_label_or_exact_id_residue(
    tmp_path: Path,
    residue: str,
) -> None:
    config, _proc_root = _config(tmp_path)
    runner = ProjectInventoryRunner(config)
    docker = _docker(config, tmp_path, runner)
    observed = docker.inspect_project(mode="create").resources
    runner.torn_down = True
    if residue == "label":
        runner.torn_down = False
    elif residue == "old-container":
        runner.exact_container_residue.add(observed.containers[0])
    else:
        runner.exact_network_residue.add(observed.networks[0])

    with pytest.raises(DockerCliError, match="publishable_project_absence_failed"):
        docker.require_project_absent(observed)


def test_partial_start_cleanup_captures_every_created_id_before_down(tmp_path: Path) -> None:
    config, _proc_root = _config(tmp_path)
    runner = ProjectInventoryRunner(config)
    partial = tuple(runner.container_ids.values())[:2]
    orphan_volume = f"{config.project_name}_partial-state"
    runner.project_container_inventory = partial
    runner.project_volume_inventory = (orphan_volume,)
    docker = _docker(config, tmp_path, runner)

    failure, resources = _cleanup_exact_project(
        docker,
        mode="create",
        inventory_scope=PROJECT_INVENTORY_SCOPE,
        project_observations=(),
    )

    assert failure is None
    assert resources is not None and resources.empty
    down_index = next(
        index for index, call in enumerate(runner.calls) if call[3] == "compose" and "down" in call
    )
    exact_filters = {
        value
        for call in runner.calls[down_index + 1 :]
        for value in _filters(call[3:])
        if value.startswith("id=")
    }
    assert exact_filters == {*(f"id={identifier}" for identifier in partial), f"id={_NETWORK_ID}"}
    assert any(
        _filters(call[3:])
        == (f"name=^{re.escape(orphan_volume)}$",)
        for call in runner.calls[down_index + 1 :]
    )
    assert all(_UNRELATED_CONTAINER_ID not in call for call in runner.calls)


def test_project_absence_rejects_observed_volume_after_its_label_is_removed(
    tmp_path: Path,
) -> None:
    config, _proc_root = _config(tmp_path)
    runner = ProjectInventoryRunner(config)
    runner.project_container_inventory = ()
    runner.project_network_inventory = ()
    volume = f"{config.project_name}_orphan"
    runner.project_volume_inventory = (volume,)
    docker = _docker(config, tmp_path, runner)
    observed = docker.observe_project_resources()
    runner.torn_down = True
    runner.exact_volume_residue.add(volume)

    with pytest.raises(DockerCliError, match="publishable_project_absence_failed"):
        docker.require_project_absent(observed)

    exact_volume_calls = [
        call
        for call in runner.calls
        if call[3:5] == ("volume", "ls")
        and _filters(call[3:]) == (f"name=^{re.escape(volume)}$",)
    ]
    assert len(exact_volume_calls) == 1


def _docker(
    config: PublishableLaneConfig,
    tmp_path: Path,
    runner: ProjectInventoryRunner,
) -> DockerCli:
    return DockerCli(config, config_file=tmp_path / "lane-config.json", runner=runner)


def _filters(command: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(command[index + 1] for index, item in enumerate(command) if item == "--filter")


def _resource_lists(calls: list[tuple[str, ...]]) -> list[tuple[str, ...]]:
    return [
        call
        for call in calls
        if call[3:5] in {("container", "ls"), ("network", "ls"), ("volume", "ls")}
    ]


def _lines(values: tuple[str, ...]) -> bytes:
    return ("\n".join(values) + ("\n" if values else "")).encode("ascii")


def _json_lines(values: object) -> bytes:
    return b"".join(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii") + b"\n"
        for value in values
    )

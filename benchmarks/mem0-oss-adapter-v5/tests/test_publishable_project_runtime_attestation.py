from __future__ import annotations

import hashlib
import hmac
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from publishable_mem0_v5 import cli, deployment, project_runtime_attestation
from publishable_mem0_v5.acceptance import (
    DockerAcceptanceError,
    DockerAcceptanceOutcome,
    run_docker_acceptance,
)
from publishable_mem0_v5.config import PINNED_DOCKER_HOST, QDRANT_IMAGE
from publishable_mem0_v5.deployment import DeploymentOutcome, deploy
from publishable_mem0_v5.docker_cli import CachedImages, DockerCli, DockerCliError
from publishable_mem0_v5.immutable_evidence import write_immutable_json
from publishable_mem0_v5.project_runtime_attestation import (
    PROJECT_ATTESTATION_FILE_PREFIX,
    PROJECT_ATTESTATION_HMAC_DOMAIN,
    PROJECT_ATTESTATION_SCHEMA,
    read_project_runtime_attestation,
)
from publishable_mem0_v5.runtime_integrity import (
    ProjectBridgeRuntimeEvidence,
    ProjectFleetRuntimeEvidence,
)
from test_publishable_deployment import DEPLOYMENT, _config, _deployment_evidence
from test_publishable_docker_acceptance import (
    FakeProviderProbe,
    _fake_deployment_attestor,
)

from tests.publishable_deployment_runtime_fixture import (
    runtime_inventory,
    write_cross_wire,
)


def _acceptance_config(tmp_path: Path):
    config, proc_root = _config(tmp_path, deployment_dir=DEPLOYMENT, project_scope=True)
    key = config.paths.adapter_secret_dir / "runtime-attestation-secret"
    key.write_bytes(b"runtime-attestation-root-" * 2)
    key.chmod(0o600)
    for account in config.bridges:
        path = config.paths.fleet_state_dir / account.account_name
        path.mkdir(mode=0o700)
        path.chmod(0o700)
    config_file = tmp_path / "lane-config.json"
    config_file.write_bytes(_json(config.public_payload()))
    config_file.chmod(0o600)
    return config, proc_root, config_file

_QDRANT_ID = "sha256:" + "d" * 64
_NETWORK_ID = "e" * 64
_UNRELATED_CONTAINER_ID = "f" * 64


class ProjectRuntimeRunner:
    def __init__(
        self,
        *,
        config: object,
        containers: dict[str, dict[str, Any]],
        network: dict[str, Any],
        present: bool = True,
    ) -> None:
        self.config = config
        self.containers = containers
        self.network = {**network, "Id": _NETWORK_ID}
        self.present = present
        self.calls: list[tuple[str, ...]] = []
        self.projected_container_payloads: list[dict[str, Any]] = []
        self.project_container_inventory_sequence: list[tuple[str, ...]] = []

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
        if command[:2] == ("image", "inspect"):
            reference = command[2]
            if reference == QDRANT_IMAGE:
                digest = QDRANT_IMAGE.split("@", 1)[1]
                return _json([{"Id": _QDRANT_ID, "RepoDigests": [f"qdrant/qdrant@{digest}"]}])
            return _json([{"Id": reference, "RepoDigests": []}])
        if command[0] == "compose":
            if "up" in command:
                self.present = True
                for item in self.containers.values():
                    item["State"].update({"Running": True, "Status": "running"})
                return b""
            if "stop" in command:
                for item in self.containers.values():
                    item["State"].update({"Running": False, "Status": "exited"})
                return b""
            if "down" in command:
                self.present = False
                return b""
            if "ps" in command:
                if not self.present:
                    return b""
                return (self.containers[command[-1]]["Id"] + "\n").encode("ascii")
        if command[:2] == ("container", "ls"):
            filter_value = _filter(command)
            project_filter = f"label=com.docker.compose.project={self.config.project_name}"
            if filter_value == project_filter:
                if self.project_container_inventory_sequence:
                    return _lines(self.project_container_inventory_sequence.pop(0))
                values = tuple(item["Id"] for item in self.containers.values())
                return _lines(values if self.present else ())
            assert filter_value.startswith("id=")
            identifier = filter_value.removeprefix("id=")
            values = {str(item["Id"]) for item in self.containers.values()}
            return _lines((identifier,)) if self.present and identifier in values else b""
        if command[:2] == ("network", "ls"):
            filter_value = _filter(command)
            project_filter = f"label=com.docker.compose.project={self.config.project_name}"
            if filter_value == project_filter:
                return _lines((_NETWORK_ID,)) if self.present else b""
            assert filter_value == f"id={_NETWORK_ID}"
            return _lines((_NETWORK_ID,)) if self.present else b""
        if command[:2] == ("volume", "ls"):
            assert _filter(command) == (
                f"label=com.docker.compose.project={self.config.project_name}"
            )
            return b""
        if command[:2] == ("container", "inspect"):
            assert self.present
            assert command[2] == "--format"
            requested = command[4:]
            expected = {item["Id"] for item in self.containers.values()}
            assert set(requested).issubset(expected)
            assert _UNRELATED_CONTAINER_ID not in requested
            by_id = {item["Id"]: item for item in self.containers.values()}
            projected = [self._project_container(by_id[identifier]) for identifier in requested]
            self.projected_container_payloads.extend(projected)
            return _json_lines(projected)
        if command[:2] == ("network", "inspect"):
            assert self.present
            assert command[2] == "--format"
            assert command[-1] == _NETWORK_ID
            return _json_lines((self.network,))
        if command[0] == "exec":
            assert command[1] == self.containers["publishable-relay-anchor"]["Id"]
            return b""
        raise AssertionError(arguments)

    @staticmethod
    def _project_container(value: dict[str, Any]) -> dict[str, Any]:
        state = {
            key: item
            for key, item in value["State"].items()
            if key in {"Health", "Running", "Status"}
        }
        labels = dict(value["Config"]["Labels"])
        return {**value, "Config": dict(value["Config"]), "Labels": labels, "State": state}


def test_project_deploy_never_observes_proc_or_unrelated_daemon_containers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, _proc_fixture = _config(tmp_path, deployment_dir=DEPLOYMENT, project_scope=True)
    config_file = tmp_path / "lane-config.json"
    config_file.write_bytes(_json(config.public_payload()))
    write_cross_wire(config)
    containers, network = runtime_inventory(config, config_file, tmp_path / "unused-proc")
    runner = ProjectRuntimeRunner(config=config, containers=containers, network=network)
    deployment_before = _deployment_evidence(config, config_file)
    fleet = _fleet(config, mode="reopen")

    monkeypatch.setattr(
        deployment, "load_provider_free_project_lane_config", lambda _path: config
    )
    monkeypatch.setattr(
        deployment,
        "attest_deployment_inputs",
        lambda *_args, **_kwargs: deployment_before,
    )
    monkeypatch.setattr(
        project_runtime_attestation,
        "attest_deployment_inputs",
        lambda *_args, **_kwargs: deployment_before,
    )
    monkeypatch.setattr(
        project_runtime_attestation,
        "attest_project_fleet_evidence",
        lambda *_args, **_kwargs: fleet,
    )
    monkeypatch.setattr(
        project_runtime_attestation,
        "attest_relay_reachability",
        lambda **_kwargs: "b" * 64,
    )

    def forbidden_fence(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("project scope must not observe protected host process identity")

    monkeypatch.setattr(deployment, "attest_account_i_fence", forbidden_fence)
    outcome = deploy(
        config_file=config_file,
        fleet_mode="reopen",
        start=False,
        runner=runner,
        proc_root=tmp_path / "forbidden-proc-root",
        expected_uid=os.geteuid(),
        expected_gid=os.getegid(),
        inventory_scope="project",
    )

    assert outcome.attestation_file.name.startswith(PROJECT_ATTESTATION_FILE_PREFIX)
    readback = read_project_runtime_attestation(
        path=outcome.attestation_file,
        directory=config.paths.attestation_dir,
        authentication_key_file=config.paths.adapter_secret_dir / "runtime-attestation-secret",
        expected_project=config.project_name,
        expected_docker_host=config.docker_host,
        expected_mode="reopen",
        expected_commitment=outcome.attestation_sha256,
        expected_project_isolation_authority_sha256=(
            config.project_isolation_authority.commitment_sha256
        ),
        expected_uid=os.geteuid(),
        expected_gid=os.getegid(),
    )
    payload = readback.immutable.payload
    assert payload["inventory_scope"] == "project"
    assert payload["observation_limits"] == {
        "daemon_global_container_inventory": "NOT_OBSERVED_PROJECT_SCOPE",
        "host_process_identities": "NOT_OBSERVED_PROJECT_SCOPE",
    }
    assert all("pid" not in item for item in payload["services"].values())
    assert all("Pid" in item["State"] for item in containers.values())
    assert all("Pid" not in item["State"] for item in runner.projected_container_payloads)
    rendered_fleet = json.dumps(payload["fleet"], sort_keys=True)
    assert "controller_pid" not in rendered_fleet
    assert '"process"' not in rendered_fleet
    assert '"generation"' not in rendered_fleet
    assert '"launch_mode"' not in rendered_fleet
    assert '"fleet_evidence_sha256"' in rendered_fleet
    assert all(
        not (call[3:5] == ("container", "ls") and "--filter" not in call) for call in runner.calls
    )
    assert all(_UNRELATED_CONTAINER_ID not in call for call in runner.calls)
    assert not [call for call in runner.calls if call[3] == "inspect"]


def test_project_attestation_rejects_ambiguous_short_container_network_identity(
    tmp_path: Path,
) -> None:
    config, _proc_fixture = _config(tmp_path, deployment_dir=DEPLOYMENT)
    config_file = tmp_path / "lane-config.json"
    config_file.write_text("reviewed-config-fixture")
    containers, network = runtime_inventory(config, config_file, tmp_path / "fixture-proc")
    anchor_id = containers["publishable-relay-anchor"]["Id"]
    containers["publishable-qdrant"]["HostConfig"]["NetworkMode"] = f"container:{anchor_id[:12]}"
    runner = ProjectRuntimeRunner(config=config, containers=containers, network=network)
    docker = DockerCli(config, config_file=config_file, runner=runner)
    inspection = docker.inspect_project(mode="reopen")

    with pytest.raises(
        project_runtime_attestation.ProjectRuntimeAttestationError,
        match="publishable_project_attestation_container_invalid",
    ):
        project_runtime_attestation._attest_project_inspection(
            inspection,
            config=config,
            docker=docker,
            cached_images=CachedImages(
                adapter_image_id=config.adapter_image_id,
                qdrant_image_id=_QDRANT_ID,
            ),
            fleet_mode="reopen",
        )


def test_default_deploy_preserves_live_global_fence_preflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, proc_root = _config(tmp_path, deployment_dir=DEPLOYMENT)
    config_file = tmp_path / "lane-config.json"
    config_file.write_text("reviewed-config-fixture")
    write_cross_wire(config)
    containers, network = runtime_inventory(config, config_file, proc_root)
    runner = ProjectRuntimeRunner(config=config, containers=containers, network=network)
    deployment_before = _deployment_evidence(config, config_file)
    observed: list[Path] = []

    monkeypatch.setattr(deployment, "load_lane_config", lambda _path: config)
    monkeypatch.setattr(
        deployment,
        "attest_deployment_inputs",
        lambda *_args, **_kwargs: deployment_before,
    )

    def stop_at_global_fence(_fence: object, *, proc_root: Path) -> object:
        observed.append(proc_root)
        raise RuntimeError("strict-global-fence-observed")

    monkeypatch.setattr(deployment, "attest_account_i_fence", stop_at_global_fence)
    with pytest.raises(RuntimeError, match="strict-global-fence-observed"):
        deploy(
            config_file=config_file,
            fleet_mode="reopen",
            start=False,
            runner=runner,
            proc_root=proc_root,
            expected_uid=os.geteuid(),
            expected_gid=os.getegid(),
        )
    assert observed == [proc_root]


@pytest.mark.parametrize(
    ("project_name", "docker_host"),
    (
        (None, PINNED_DOCKER_HOST),
        ("mem0-v5-publishable-wrong-lane", PINNED_DOCKER_HOST),
        ("exact", None),
        ("exact", "unix:///var/run/docker.sock"),
    ),
)
def test_project_acceptance_requires_exact_explicit_project_and_socket_before_docker(
    tmp_path: Path,
    project_name: str | None,
    docker_host: str | None,
) -> None:
    config, proc_root, config_file = _acceptance_config(tmp_path)
    expected_project = config.project_name if project_name == "exact" else project_name
    runner = _BombRunner()

    with pytest.raises(
        DockerAcceptanceError,
        match="publishable_acceptance_project_authority_invalid",
    ):
        run_docker_acceptance(
            config_file=config_file,
            runner=runner,
            proc_root=proc_root,
            expected_uid=os.geteuid(),
            expected_gid=os.getegid(),
            inventory_scope="project",
            expected_project_name=expected_project,
            expected_docker_host=docker_host,
        )
    assert runner.calls == []


def test_project_acceptance_rejects_initial_inventory_race_before_compose_mutation(
    tmp_path: Path,
) -> None:
    config, _proc_fixture, config_file = _acceptance_config(tmp_path)
    containers, network = runtime_inventory(config, config_file, tmp_path / "fixture-proc")
    runner = ProjectRuntimeRunner(
        config=config,
        containers=containers,
        network=network,
        present=False,
    )
    runner.project_container_inventory_sequence = [
        (),
        (containers["publishable-relay-anchor"]["Id"],),
    ]
    deployer = _ProjectReceiptLaneDeployer()

    with pytest.raises(DockerCliError, match="publishable_project_inventory_changed"):
        run_docker_acceptance(
            config_file=config_file,
            runner=runner,
            proc_root=tmp_path / "forbidden-proc",
            expected_uid=os.geteuid(),
            expected_gid=os.getegid(),
            lane_deployer=deployer,
            runtime_probe=FakeProviderProbe(config),
            deployment_attestor=_fake_deployment_attestor,
            inventory_scope="project",
            expected_project_name=config.project_name,
            expected_docker_host=PINNED_DOCKER_HOST,
        )

    assert deployer.calls == []
    assert not any(call[3] == "compose" for call in runner.calls)


def test_acceptance_outcome_binds_project_scope_without_global_claims(tmp_path: Path) -> None:
    outcome = DockerAcceptanceOutcome(
        acceptance_file=tmp_path / "docker-acceptance.json",
        acceptance_sha256="1" * 64,
        project_name="mem0-v5-publishable-exact-lane",
        create_attestation_sha256="2" * 64,
        reopen_attestation_sha256="3" * 64,
        package_closure_sha256="4" * 64,
        deployment_closure_sha256="5" * 64,
        deployment_closure_hmac_sha256="6" * 64,
        deployment_inputs_sha256="7" * 64,
        adapter_source_commit_sha1="8" * 40,
        adapter_source_tree_sha1="9" * 40,
        phase_c_infinity_commit_sha1="a" * 40,
        inventory_scope="project",
        docker_host=PINNED_DOCKER_HOST,
    )

    assert outcome.payload()["docker_inventory"] == {
        "daemon_global_container_inventory": "NOT_OBSERVED_PROJECT_SCOPE",
        "docker_host": PINNED_DOCKER_HOST,
        "host_process_identities": "NOT_OBSERVED_PROJECT_SCOPE",
        "project_name": outcome.project_name,
        "scope": "project",
    }


def test_project_readback_rejects_reauthenticated_mismatched_fleet_commitment(
    tmp_path: Path,
) -> None:
    config, _proc_fixture, config_file = _acceptance_config(tmp_path)
    containers, network = runtime_inventory(config, config_file, tmp_path / "fixture-proc")
    runner = ProjectRuntimeRunner(config=config, containers=containers, network=network)
    unsigned = _project_receipt_payload(
        config,
        runner=runner,
        mode="reopen",
        generation=2,
        deployment_inputs_sha256=_deployment_evidence(
            config,
            config_file,
        ).commitment_sha256,
    )
    fleet = unsigned["fleet"]
    assert isinstance(fleet, dict)
    fleet["fleet_evidence_sha256"] = "f" * 64
    key_file = config.paths.adapter_secret_dir / "runtime-attestation-secret"
    key = key_file.read_bytes()
    authentication = hmac.new(
        key,
        PROJECT_ATTESTATION_HMAC_DOMAIN + _json(unsigned),
        hashlib.sha256,
    ).hexdigest()
    receipt = write_immutable_json(
        directory=config.paths.attestation_dir,
        prefix=PROJECT_ATTESTATION_FILE_PREFIX,
        payload={**unsigned, "attestation_hmac_sha256": authentication},
        expected_uid=os.geteuid(),
        expected_gid=os.getegid(),
    )

    with pytest.raises(
        project_runtime_attestation.ProjectRuntimeAttestationError,
        match="publishable_project_attestation_fleet_invalid",
    ):
        read_project_runtime_attestation(
            path=receipt.path,
            directory=config.paths.attestation_dir,
            authentication_key_file=key_file,
            expected_project=config.project_name,
            expected_docker_host=config.docker_host,
            expected_mode="reopen",
            expected_commitment=receipt.commitment_sha256,
            expected_project_isolation_authority_sha256=(
                config.project_isolation_authority.commitment_sha256
            ),
            expected_uid=os.geteuid(),
            expected_gid=os.getegid(),
        )


def test_project_readback_rejects_reauthenticated_wrong_isolation_authority(
    tmp_path: Path,
) -> None:
    config, _proc_fixture, config_file = _acceptance_config(tmp_path)
    containers, network = runtime_inventory(config, config_file, tmp_path / "fixture-proc")
    runner = ProjectRuntimeRunner(config=config, containers=containers, network=network)
    unsigned = _project_receipt_payload(
        config,
        runner=runner,
        mode="reopen",
        generation=2,
        deployment_inputs_sha256=_deployment_evidence(config, config_file).commitment_sha256,
    )
    unsigned["project_isolation_authority_sha256"] = "f" * 64
    key_file = config.paths.adapter_secret_dir / "runtime-attestation-secret"
    authentication = hmac.new(
        key_file.read_bytes(),
        PROJECT_ATTESTATION_HMAC_DOMAIN + _json(unsigned),
        hashlib.sha256,
    ).hexdigest()
    receipt = write_immutable_json(
        directory=config.paths.attestation_dir,
        prefix=PROJECT_ATTESTATION_FILE_PREFIX,
        payload={**unsigned, "attestation_hmac_sha256": authentication},
        expected_uid=os.geteuid(),
        expected_gid=os.getegid(),
    )
    with pytest.raises(
        project_runtime_attestation.ProjectRuntimeAttestationError,
        match="publishable_project_attestation_isolation_authority_mismatch",
    ):
        read_project_runtime_attestation(
            path=receipt.path,
            directory=config.paths.attestation_dir,
            authentication_key_file=key_file,
            expected_project=config.project_name,
            expected_docker_host=config.docker_host,
            expected_mode="reopen",
            expected_commitment=receipt.commitment_sha256,
            expected_project_isolation_authority_sha256=(
                config.project_isolation_authority.commitment_sha256
            ),
            expected_uid=os.geteuid(),
            expected_gid=os.getegid(),
        )


def test_cli_forwards_explicit_project_acceptance_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_file = tmp_path / "lane-config.json"
    config_file.write_text("{}")
    observed: dict[str, object] = {}
    outcome = DockerAcceptanceOutcome(
        acceptance_file=tmp_path / "docker-acceptance.json",
        acceptance_sha256="1" * 64,
        project_name="mem0-v5-publishable-exact-lane",
        create_attestation_sha256="2" * 64,
        reopen_attestation_sha256="3" * 64,
        package_closure_sha256="4" * 64,
        deployment_closure_sha256="5" * 64,
        deployment_closure_hmac_sha256="6" * 64,
        deployment_inputs_sha256="7" * 64,
        adapter_source_commit_sha1="8" * 40,
        adapter_source_tree_sha1="9" * 40,
        phase_c_infinity_commit_sha1="a" * 40,
        inventory_scope="project",
        docker_host=PINNED_DOCKER_HOST,
    )

    def capture(**values: object) -> DockerAcceptanceOutcome:
        observed.update(values)
        return outcome

    monkeypatch.setattr(cli, "run_docker_acceptance", capture)
    assert (
        cli.main(
            (
                "acceptance",
                "--config",
                str(config_file),
                "--inventory-scope",
                "project",
                "--project-name",
                outcome.project_name,
                "--docker-host",
                PINNED_DOCKER_HOST,
            )
        )
        == 0
    )
    assert observed == {
        "config_file": config_file,
        "expected_docker_host": PINNED_DOCKER_HOST,
        "expected_project_name": outcome.project_name,
        "inventory_scope": "project",
    }
    assert json.loads(capsys.readouterr().out) == outcome.payload()


class _ProjectReceiptLaneDeployer:
    def __init__(self, *, reuse_lifecycle_inventory: bool = False) -> None:
        self.calls: list[str] = []
        self.reuse_lifecycle_inventory = reuse_lifecycle_inventory

    def __call__(self, **values: object) -> DeploymentOutcome:
        config_file = values["config_file"]
        mode = values["fleet_mode"]
        runner = values["runner"]
        assert isinstance(config_file, Path)
        assert isinstance(mode, str)
        assert isinstance(runner, ProjectRuntimeRunner)
        assert values["inventory_scope"] == "project"
        config = runner.config
        DockerCli(config, config_file=config_file, runner=runner).start(mode=mode)
        self.calls.append(mode)
        unsigned = _project_receipt_payload(
            config,
            runner=runner,
            mode=mode,
            generation=(
                1 if mode == "create" or self.reuse_lifecycle_inventory else 2
            ),
            deployment_inputs_sha256=_deployment_evidence(
                config,
                config_file,
            ).commitment_sha256,
        )
        key = (config.paths.adapter_secret_dir / "runtime-attestation-secret").read_bytes()
        authentication = hmac.new(
            key,
            PROJECT_ATTESTATION_HMAC_DOMAIN + _json(unsigned),
            hashlib.sha256,
        ).hexdigest()
        receipt = write_immutable_json(
            directory=config.paths.attestation_dir,
            prefix=PROJECT_ATTESTATION_FILE_PREFIX,
            payload={**unsigned, "attestation_hmac_sha256": authentication},
            expected_uid=os.geteuid(),
            expected_gid=os.getegid(),
        )
        return DeploymentOutcome(
            attestation_file=receipt.path,
            attestation_sha256=receipt.commitment_sha256,
        )


def test_project_acceptance_runs_scoped_lifecycle_and_exact_id_cleanup(
    tmp_path: Path,
) -> None:
    config, _proc_fixture, config_file = _acceptance_config(tmp_path)
    containers, network = runtime_inventory(config, config_file, tmp_path / "fixture-proc")
    runner = ProjectRuntimeRunner(
        config=config,
        containers=containers,
        network=network,
        present=False,
    )
    deployer = _ProjectReceiptLaneDeployer()
    probe = FakeProviderProbe(config)

    outcome = run_docker_acceptance(
        config_file=config_file,
        runner=runner,
        proc_root=tmp_path / "nonexistent-forbidden-proc",
        expected_uid=os.geteuid(),
        expected_gid=os.getegid(),
        lane_deployer=deployer,
        runtime_probe=probe,
        deployment_attestor=_fake_deployment_attestor,
        inventory_scope="project",
        expected_project_name=config.project_name,
        expected_docker_host=PINNED_DOCKER_HOST,
    )

    assert deployer.calls == ["create", "reopen"]
    assert outcome.inventory_scope == "project"
    assert outcome.payload()["docker_inventory"]["host_process_identities"] == (
        "NOT_OBSERVED_PROJECT_SCOPE"
    )
    assert not runner.present
    assert all(
        "--filter" in call
        for call in runner.calls
        if call[3:5] in {("container", "ls"), ("network", "ls"), ("volume", "ls")}
    )
    assert not any(call[3] == "inspect" for call in runner.calls)
    assert all(_UNRELATED_CONTAINER_ID not in call for call in runner.calls)
    assert not any("prune" in call or "build" in call for call in runner.calls)
    assert all(
        call[call.index("--pull") + 1] == "never" and "--no-build" in call
        for call in runner.calls
        if call[3] == "compose" and "up" in call
    )
    exact_filters = {
        _filter(call[3:])
        for call in runner.calls
        if call[3:5] in {("container", "ls"), ("network", "ls")} and call[-1].startswith("id=")
    }
    assert exact_filters == {
        *(f"id={item['Id']}" for item in containers.values()),
        f"id={_NETWORK_ID}",
    }


def test_project_acceptance_rejects_unchanged_opaque_lifecycle_metadata(
    tmp_path: Path,
) -> None:
    config, _proc_fixture, config_file = _acceptance_config(tmp_path)
    containers, network = runtime_inventory(config, config_file, tmp_path / "fixture-proc")
    runner = ProjectRuntimeRunner(
        config=config,
        containers=containers,
        network=network,
        present=False,
    )
    deployer = _ProjectReceiptLaneDeployer(reuse_lifecycle_inventory=True)

    with pytest.raises(DockerAcceptanceError, match="publishable_acceptance_reopen_state_mismatch"):
        run_docker_acceptance(
            config_file=config_file,
            runner=runner,
            proc_root=tmp_path / "forbidden-proc",
            expected_uid=os.geteuid(),
            expected_gid=os.getegid(),
            lane_deployer=deployer,
            runtime_probe=FakeProviderProbe(config),
            deployment_attestor=_fake_deployment_attestor,
            inventory_scope="project",
            expected_project_name=config.project_name,
            expected_docker_host=PINNED_DOCKER_HOST,
        )

    assert deployer.calls == ["create", "reopen"]
    assert not runner.present


def _project_receipt_payload(
    config: object,
    *,
    runner: ProjectRuntimeRunner,
    mode: str,
    generation: int,
    deployment_inputs_sha256: str,
) -> dict[str, object]:
    services = {
        service: {
            "bind_mounts_sha256": hashlib.sha256(service.encode()).hexdigest(),
            "container_id": str(item["Id"]),
            "image_id": _QDRANT_ID if service == "publishable-qdrant" else config.adapter_image_id,
        }
        for service, item in runner.containers.items()
    }
    bridges = [
        {
            "account_name": account.account_name,
            "bridge_id": account.bridge_id,
            "lifecycle_inventory_sha256": hashlib.sha256(
                f"{index}:{generation}".encode()
            ).hexdigest(),
            "runtime_authority_sha256": f"{index + 6:x}" * 64,
        }
        for index, account in enumerate(config.bridges)
    ]
    fleet_evidence = {
        "bridges": bridges,
        "pool_authority_sha256": "a" * 64,
        "requested_mode": mode,
    }
    return {
        "adapter_image_id": config.adapter_image_id,
        "bridge_ports": [8891, 8892, 8893],
        "compose_sha256": "1" * 64,
        "project_isolation_authority_sha256": (
        config.project_isolation_authority.commitment_sha256
        ),
        "deployment_inputs_sha256": deployment_inputs_sha256,
        "docker_authority": {
            "docker_host": config.docker_host,
            "project_name": config.project_name,
        },
        "fleet": {
            **fleet_evidence,
            "fleet_evidence_sha256": hashlib.sha256(_json(fleet_evidence)).hexdigest(),
        },
        "host_exposure": {
            "container_port": 19191,
            "host_ip": "127.0.0.1",
            "host_port": config.host_adapter_port,
            "relayed_adapter_port": 19091,
        },
        "inventory_scope": "project",
        "observation_limits": {
            "daemon_global_container_inventory": "NOT_OBSERVED_PROJECT_SCOPE",
            "host_process_identities": "NOT_OBSERVED_PROJECT_SCOPE",
        },
        "observed_at_unix_ns": generation,
        "project_resources": {
            "containers": {service: str(item["Id"]) for service, item in runner.containers.items()},
            "network_id": _NETWORK_ID,
            "volumes": [],
        },
        "qdrant_image_id": _QDRANT_ID,
        "qdrant_ports": {"grpc": 6335, "http": 6334},
        "relay_reachability_sha256": "b" * 64,
        "schema_version": PROJECT_ATTESTATION_SCHEMA,
        "secret_cross_wire_sha256": "c" * 64,
        "services": services,
    }


def _fleet(config: object, *, mode: str) -> ProjectFleetRuntimeEvidence:
    bridges = tuple(
        ProjectBridgeRuntimeEvidence(
            account_name=account.account_name,
            bridge_id=account.bridge_id,
            lifecycle_inventory_sha256=f"{index + 4:x}" * 64,
            runtime_authority_sha256=f"{index + 1:x}" * 64,
        )
        for index, account in enumerate(config.bridges)
    )
    evidence = {
        "bridges": [item.payload() for item in bridges],
        "pool_authority_sha256": "7" * 64,
        "requested_mode": mode,
    }
    return ProjectFleetRuntimeEvidence(
        requested_mode=mode,
        pool_authority_sha256="7" * 64,
        fleet_evidence_sha256=hashlib.sha256(_json(evidence)).hexdigest(),
        bridges=bridges,
    )


def _filter(command: tuple[str, ...]) -> str:
    assert command.count("--filter") == 1
    index = command.index("--filter")
    assert index + 2 == len(command)
    return command[index + 1]


def _lines(values: tuple[str, ...]) -> bytes:
    return ("\n".join(values) + ("\n" if values else "")).encode("ascii")


def _json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii")


def _json_lines(values: object) -> bytes:
    return b"".join(_json(value) + b"\n" for value in values)


class _BombRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def run(
        self,
        arguments: tuple[str, ...],
        *,
        environment: Mapping[str, str],
    ) -> bytes:
        del environment
        self.calls.append(arguments)
        raise AssertionError("Docker must not run before exact project authority is accepted")

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from publishable_mem0_v5 import cli
from publishable_mem0_v5.acceptance import (
    CLEAN_STATE_STATUS,
    DockerAcceptanceError,
    DockerAcceptanceOutcome,
    run_docker_acceptance,
)
from publishable_mem0_v5.acceptance_identity import (
    AcceptanceDriverIdentityError,
    attest_acceptance_driver,
)
from publishable_mem0_v5.config import PublishableLaneConfig, load_lane_config
from publishable_mem0_v5.deployment import DeploymentOutcome
from publishable_mem0_v5.docker_cli import (
    SERVICES,
    DockerCli,
    DockerCliError,
    SubprocessCommandRunner,
)
from publishable_mem0_v5.immutable_evidence import (
    require_immutable_json_unchanged,
    write_immutable_json,
)
from publishable_mem0_v5.preflight import DeploymentInputEvidence
from publishable_mem0_v5.provider_attestation import ProviderAttestationEvidence
from publishable_mem0_v5.runtime_attestation import (
    ATTESTATION_FILE_PREFIX,
    ATTESTATION_SCHEMA,
)
from test_publishable_deployment import DEPLOYMENT, _config, _deployment_evidence

_PROJECT_NETWORK_ID = "e" * 64
_OTHER_PROJECT_CONTAINER = "f" * 64
_OTHER_PROJECT_NETWORK = "d" * 64
_OTHER_PROJECT_VOLUME = "other_project_state"


class FakeDockerRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], dict[str, str]]] = []
        self.containers: dict[str, dict[str, object]] = {
            _OTHER_PROJECT_CONTAINER: {
                "Id": _OTHER_PROJECT_CONTAINER,
                "Project": "other-project",
                "State": {"Running": True, "Status": "running"},
            }
        }
        self.networks: dict[str, str] = {_OTHER_PROJECT_NETWORK: "other-project"}
        self.volumes: dict[str, str] = {_OTHER_PROJECT_VOLUME: "other-project"}
        self.fail_up_mode: str | None = None
        self.fail_up_code = "publishable_docker_command_failed"
        self.partial_up = False
        self.fail_down = False
        self.invalid_stop = False
        self.residual_kind: str | None = None

    def run(self, arguments: tuple[str, ...], *, environment: Any) -> bytes:
        self.calls.append((arguments, dict(environment)))
        if arguments[3] == "compose":
            return self._compose(arguments, environment)
        if arguments[3] == "container" and arguments[4] == "ls":
            project = _inventory_project(arguments)
            return self._lines(
                tuple(
                    identifier
                    for identifier, value in self.containers.items()
                    if value["Project"] == project
                )
            )
        if arguments[3] == "network" and arguments[4] == "ls":
            project = _inventory_project(arguments)
            return self._lines(
                tuple(identifier for identifier, value in self.networks.items() if value == project)
            )
        if arguments[3] == "volume" and arguments[4] == "ls":
            project = _inventory_project(arguments)
            return self._lines(
                tuple(identifier for identifier, value in self.volumes.items() if value == project)
            )
        if arguments[3] == "inspect":
            return _json_bytes([self.containers[item] for item in arguments[4:]])
        raise AssertionError(arguments)

    def _compose(self, arguments: tuple[str, ...], environment: Any) -> bytes:
        mode = environment["MEM0_V5_PUBLISHABLE_FLEET_MODE"]
        project = arguments[arguments.index("--project-name") + 1]
        if "up" in arguments:
            self._create_resources(mode, project=project)
            if self.fail_up_mode == mode:
                if self.partial_up:
                    exact = [
                        item for item in self.containers.items() if item[1]["Project"] == project
                    ][:2]
                    self.containers = {
                        identifier: value
                        for identifier, value in self.containers.items()
                        if value["Project"] != project
                    }
                    self.containers.update(exact)
                raise DockerCliError(self.fail_up_code)
            return b""
        if "stop" in arguments:
            exact = [value for value in self.containers.values() if value["Project"] == project]
            for index, value in enumerate(exact):
                if not self.invalid_stop or index:
                    value["State"] = {"Running": False, "Status": "exited"}
            return b""
        if "ps" in arguments:
            service = arguments[-1]
            identifier = _container_id(service, mode)
            return f"{identifier}\n".encode("ascii")
        if "down" in arguments:
            if self.fail_down:
                raise DockerCliError("publishable_docker_command_failed")
            self.containers = {
                identifier: value
                for identifier, value in self.containers.items()
                if value["Project"] != project
            }
            self.networks = {
                identifier: value for identifier, value in self.networks.items() if value != project
            }
            self.volumes = {
                identifier: value for identifier, value in self.volumes.items() if value != project
            }
            if self.residual_kind == "container":
                identifier = "a" * 64
                self.containers[identifier] = {
                    "Id": identifier,
                    "Project": project,
                    "State": {"Running": False, "Status": "exited"},
                }
            elif self.residual_kind == "network":
                self.networks["b" * 64] = project
            elif self.residual_kind == "volume":
                self.volumes["accepted_project_residue"] = project
            return b""
        raise AssertionError(arguments)

    def _create_resources(
        self, mode: str, *, project: str = "mem0-v5-publishable-testlane"
    ) -> None:
        self.containers = {
            identifier: value
            for identifier, value in self.containers.items()
            if value["Project"] != project
        }
        self.containers.update(
            {
                _container_id(service, mode): {
                    "Id": _container_id(service, mode),
                    "Project": project,
                    "State": {"Running": True, "Status": "running"},
                }
                for service in SERVICES
            }
        )
        self.networks[_PROJECT_NETWORK_ID] = project

    @staticmethod
    def _lines(values: tuple[str, ...]) -> bytes:
        return ("\n".join(values) + ("\n" if values else "")).encode("ascii")


class FakeLaneDeployer:
    def __init__(
        self,
        *,
        failure_mode: str | None = None,
        tamper_create_on_reopen: bool = False,
        replace_state_on_create: bool = False,
        reopen_generation: int = 2,
    ) -> None:
        self.failure_mode = failure_mode
        self.tamper_create_on_reopen = tamper_create_on_reopen
        self.replace_state_on_create = replace_state_on_create
        self.reopen_generation = reopen_generation
        self.calls: list[str] = []
        self.create_path: Path | None = None

    def __call__(self, **values: object) -> DeploymentOutcome:
        config_file = values["config_file"]
        mode = values["fleet_mode"]
        runner = values["runner"]
        assert isinstance(config_file, Path)
        assert isinstance(mode, str)
        config = load_lane_config(config_file)
        deployment = _deployment_evidence(config, config_file)
        docker = DockerCli(config, config_file=config_file, runner=runner)  # type: ignore[arg-type]
        self.calls.append(mode)
        docker.start(mode=mode)
        if self.failure_mode == mode:
            raise RuntimeError(f"fake-{mode}-crash")
        if mode == "reopen" and self.tamper_create_on_reopen:
            assert self.create_path is not None
            self.create_path.write_bytes(b'{"observed_at_unix_ns":NaN}\n')
        if mode == "create" and self.replace_state_on_create:
            original = config.paths.adapter_state_dir
            original.rename(original.with_name("adapter-state-replaced"))
            original.mkdir(mode=0o700)
        immutable = write_immutable_json(
            directory=config.paths.attestation_dir,
            prefix=ATTESTATION_FILE_PREFIX,
            payload=_runtime_attestation_payload(
                config,
                mode=mode,
                deployment_inputs_sha256=deployment.commitment_sha256,
                generation=self.reopen_generation if mode == "reopen" else 1,
            ),
        )
        if mode == "create":
            self.create_path = immutable.path
        return DeploymentOutcome(
            attestation_file=immutable.path,
            attestation_sha256=immutable.commitment_sha256,
        )


class FakeProviderProbe:
    def __init__(
        self,
        config: PublishableLaneConfig,
        *,
        crash_on_create: bool = False,
        tamper_on_reopen: bool = False,
    ) -> None:
        self.config = config
        self.crash_on_create = crash_on_create
        self.tamper_on_reopen = tamper_on_reopen
        self.calls: list[tuple[str, str]] = []
        self.create_path: Path | None = None

    def attest(
        self,
        *,
        fleet_mode: str,
        runtime_attestation_sha256: str,
    ) -> ProviderAttestationEvidence:
        self.calls.append((fleet_mode, runtime_attestation_sha256))
        if fleet_mode == "create" and self.crash_on_create:
            raise RuntimeError("fake-provider-probe-crash")
        if fleet_mode == "reopen" and self.tamper_on_reopen:
            assert self.create_path is not None
            self.create_path.write_bytes(b"{}\n")
        immutable = write_immutable_json(
            directory=self.config.paths.attestation_dir,
            prefix="fake-provider-",
            payload={
                "fleet_mode": fleet_mode,
                "runtime_attestation_sha256": runtime_attestation_sha256,
            },
        )
        if fleet_mode == "create":
            self.create_path = immutable.path
        return ProviderAttestationEvidence(
            immutable=immutable,
            fleet_mode=fleet_mode,
            runtime_attestation_sha256=runtime_attestation_sha256,
            target_origin_sha256="1" * 64,
            run_id_sha256="2" * 64,
            probe_nonce_sha256=("3" if fleet_mode == "create" else "4") * 64,
            source_commit_sha1="5" * 40,
            source_tree_sha1="6" * 40,
            phase_c_infinity_commit_sha1="7" * 40,
            phase_c_infinity_tree_sha1="8" * 40,
            implementation_binding_sha256="9" * 64,
        )

    def require_unchanged(
        self,
        evidence: ProviderAttestationEvidence,
    ) -> ProviderAttestationEvidence:
        require_immutable_json_unchanged(
            evidence.immutable,
            directory=self.config.paths.attestation_dir,
            prefix="fake-provider-",
        )
        return evidence


def test_acceptance_driver_sha_binds_installed_and_deployed_package(tmp_path: Path) -> None:
    staged = tmp_path / "deployment"
    shutil.copytree(DEPLOYMENT, staged, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    config, _proc_root = _config(tmp_path / "lane", deployment_dir=staged)

    identity = attest_acceptance_driver(config)

    assert len(identity.package_closure_sha256) == 64
    assert identity.deployment_closure_sha256 == (
        config.bind_mount_authority.deployment_closure_sha256
    )
    deployed_cli = staged / "publishable_mem0_v5/cli.py"
    deployed_cli.write_bytes(deployed_cli.read_bytes() + b"\n")
    with pytest.raises(
        AcceptanceDriverIdentityError,
        match="publishable_acceptance_driver_deployment_mismatch",
    ):
        attest_acceptance_driver(config)


def test_acceptance_owns_exact_provider_free_lifecycle_and_cleans_project(
    tmp_path: Path,
) -> None:
    config, proc_root, config_file = _acceptance_config(tmp_path)
    runner = FakeDockerRunner()
    deployer = FakeLaneDeployer()
    probe = FakeProviderProbe(config)

    outcome = run_docker_acceptance(
        config_file=config_file,
        runner=runner,
        proc_root=proc_root,
        expected_uid=os.geteuid(),
        expected_gid=os.getegid(),
        lane_deployer=deployer,
        runtime_probe=probe,
        deployment_attestor=_fake_deployment_attestor,
    )

    assert outcome.payload()["outcome"] == "ACCEPTED_PROVIDER_FREE"
    assert outcome.payload()["provider_call_verification"] == {
        "acceptance_driver_provider_dispatch_operations": 0,
        "authenticated_runtime_probe_provider_calls": {"create": 0, "reopen": 0},
        "historical_or_concurrent_provider_call_counter": "NOT_AVAILABLE",
        "scope": "fixed acceptance command operations",
        "status": "VERIFIED_PROVIDER_FREE",
    }
    assert outcome.payload()["acceptance_driver"]["package_closure_sha256"]
    assert outcome.payload()["deployment_authority"]["deployment_inputs_sha256"]
    assert outcome.payload()["authenticated_empty_state"]["status"] == CLEAN_STATE_STATUS
    assert json.loads(outcome.acceptance_file.read_bytes())["cleanup"] == {
        "containers": 0,
        "networks": 0,
        "volumes": 0,
    }
    assert deployer.calls == ["create", "reopen"]
    assert [item[0] for item in probe.calls] == ["create", "reopen"]
    assert not _exact_project_resources(runner, config.project_name)
    assert _OTHER_PROJECT_CONTAINER in runner.containers
    assert _OTHER_PROJECT_NETWORK in runner.networks
    assert _OTHER_PROJECT_VOLUME in runner.volumes
    mutations = _compose_mutations(runner.calls)
    assert [item[0] for item in mutations] == ["up", "stop", "up", "down"]
    for operation, arguments in mutations:
        assert arguments[arguments.index("--project-name") + 1] == config.project_name
        assert "prune" not in arguments
        if operation == "up":
            assert (
                arguments[arguments.index("--pull")],
                arguments[arguments.index("--pull") + 1],
            ) == ("--pull", "never")
            assert "--no-build" in arguments
            assert arguments[arguments.index("--wait-timeout") + 1] == "120"
        if operation in {"stop", "down"}:
            assert arguments[arguments.index("--timeout") + 1] == "30"
    assert "--volumes" in mutations[-1][1]
    assert "--remove-orphans" in mutations[-1][1]
    inventory_calls = [
        arguments
        for arguments, _environment in runner.calls
        if len(arguments) > 5
        and arguments[3:5] in {("container", "ls"), ("network", "ls"), ("volume", "ls")}
    ]
    assert len(inventory_calls) == 6
    expected_filter = f"label=com.docker.compose.project={config.project_name}"
    assert all(arguments[-1] == expected_filter for arguments in inventory_calls)


def test_preexisting_exact_project_is_refused_without_cleanup(tmp_path: Path) -> None:
    config, proc_root, config_file = _acceptance_config(tmp_path)
    runner = FakeDockerRunner()
    runner._create_resources("create")

    with pytest.raises(DockerAcceptanceError, match="publishable_acceptance_project_not_empty"):
        run_docker_acceptance(
            config_file=config_file,
            runner=runner,
            proc_root=proc_root,
            expected_uid=os.geteuid(),
            expected_gid=os.getegid(),
            lane_deployer=FakeLaneDeployer(),
            runtime_probe=FakeProviderProbe(config),
            deployment_attestor=_fake_deployment_attestor,
        )

    assert _exact_project_resources(runner, config.project_name)
    assert not _compose_mutations(runner.calls)


@pytest.mark.parametrize(
    ("case", "expected"),
    (
        ("crash", "fake-provider-probe-crash"),
        ("timeout", "publishable_docker_command_timeout"),
        ("partial-create", "publishable_docker_command_failed"),
        ("reopen", "fake-reopen-crash"),
    ),
)
def test_every_partial_lifecycle_failure_runs_exact_cleanup(
    tmp_path: Path,
    case: str,
    expected: str,
) -> None:
    config, proc_root, config_file = _acceptance_config(tmp_path)
    runner = FakeDockerRunner()
    failure_mode = "reopen" if case == "reopen" else None
    deployer = FakeLaneDeployer(failure_mode=failure_mode)
    probe = FakeProviderProbe(config, crash_on_create=case == "crash")
    if case == "timeout":
        runner.fail_up_mode = "create"
        runner.fail_up_code = "publishable_docker_command_timeout"
    if case == "partial-create":
        runner.fail_up_mode = "create"
        runner.partial_up = True

    with pytest.raises((DockerCliError, RuntimeError), match=expected):
        run_docker_acceptance(
            config_file=config_file,
            runner=runner,
            proc_root=proc_root,
            expected_uid=os.geteuid(),
            expected_gid=os.getegid(),
            lane_deployer=deployer,
            runtime_probe=probe,
            deployment_attestor=_fake_deployment_attestor,
        )

    assert not _exact_project_resources(runner, config.project_name)
    assert _OTHER_PROJECT_CONTAINER in runner.containers
    assert _OTHER_PROJECT_NETWORK in runner.networks
    assert _OTHER_PROJECT_VOLUME in runner.volumes
    mutations = _compose_mutations(runner.calls)
    assert mutations[-1][0] == "down"
    assert mutations[-1][1][mutations[-1][1].index("--project-name") + 1] == config.project_name
    assert all("prune" not in arguments for _operation, arguments in mutations)


def test_tampered_create_attestation_fails_after_reopen_and_still_cleans(
    tmp_path: Path,
) -> None:
    config, proc_root, config_file = _acceptance_config(tmp_path)
    runner = FakeDockerRunner()

    with pytest.raises(RuntimeError, match="publishable_immutable_evidence"):
        run_docker_acceptance(
            config_file=config_file,
            runner=runner,
            proc_root=proc_root,
            expected_uid=os.geteuid(),
            expected_gid=os.getegid(),
            lane_deployer=FakeLaneDeployer(tamper_create_on_reopen=True),
            runtime_probe=FakeProviderProbe(config),
            deployment_attestor=_fake_deployment_attestor,
        )

    assert not _exact_project_resources(runner, config.project_name)
    assert _compose_mutations(runner.calls)[-1][0] == "down"


@pytest.mark.parametrize(
    ("case", "expected"),
    (
        ("controlled-stop", "publishable_compose_controlled_stop_invalid"),
        ("state-root", "publishable_acceptance_state_identity_changed"),
        ("generation", "publishable_acceptance_reopen_state_mismatch"),
        ("provider-evidence", "publishable_immutable_evidence"),
    ),
)
def test_lifecycle_identity_failures_still_run_exact_cleanup(
    tmp_path: Path,
    case: str,
    expected: str,
) -> None:
    config, proc_root, config_file = _acceptance_config(tmp_path)
    runner = FakeDockerRunner()
    runner.invalid_stop = case == "controlled-stop"
    deployer = FakeLaneDeployer(
        replace_state_on_create=case == "state-root",
        reopen_generation=1 if case == "generation" else 2,
    )
    probe = FakeProviderProbe(config, tamper_on_reopen=case == "provider-evidence")

    with pytest.raises(RuntimeError, match=expected):
        run_docker_acceptance(
            config_file=config_file,
            runner=runner,
            proc_root=proc_root,
            expected_uid=os.geteuid(),
            expected_gid=os.getegid(),
            lane_deployer=deployer,
            runtime_probe=probe,
            deployment_attestor=_fake_deployment_attestor,
        )

    assert not _exact_project_resources(runner, config.project_name)
    assert _compose_mutations(runner.calls)[-1][0] == "down"


@pytest.mark.parametrize("failure", ("down", "container", "network", "volume"))
def test_cleanup_failure_is_terminal_and_all_resource_checks_run(
    tmp_path: Path,
    failure: str,
) -> None:
    config, proc_root, config_file = _acceptance_config(tmp_path)
    runner = FakeDockerRunner()
    runner.fail_down = failure == "down"
    runner.residual_kind = None if failure == "down" else failure

    with pytest.raises(DockerAcceptanceError, match="publishable_acceptance_cleanup_failed"):
        run_docker_acceptance(
            config_file=config_file,
            runner=runner,
            proc_root=proc_root,
            expected_uid=os.geteuid(),
            expected_gid=os.getegid(),
            lane_deployer=FakeLaneDeployer(),
            runtime_probe=FakeProviderProbe(config),
            deployment_attestor=_fake_deployment_attestor,
        )

    final_calls = runner.calls[-3:]
    assert [arguments[3:5] for arguments, _environment in final_calls] == [
        ("container", "ls"),
        ("network", "ls"),
        ("volume", "ls"),
    ]
    assert _compose_mutations(runner.calls)[-1][0] == "down"


def test_subprocess_runner_reports_a_stable_bounded_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def timeout(*_args: object, **_kwargs: object) -> object:
        raise subprocess.TimeoutExpired(cmd=("/usr/bin/docker",), timeout=1)

    monkeypatch.setattr(subprocess, "run", timeout)
    runner = SubprocessCommandRunner(timeout_seconds=1)
    with pytest.raises(DockerCliError, match="publishable_docker_command_timeout"):
        runner.run(("/usr/bin/docker", "version"), environment={})
    with pytest.raises(DockerCliError, match="publishable_docker_timeout_invalid"):
        SubprocessCommandRunner(timeout_seconds=181)


def test_cli_acceptance_is_installed_shape_and_emits_secret_free_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_file = tmp_path / "config.json"
    config_file.write_text("{}")
    outcome = DockerAcceptanceOutcome(
        acceptance_file=tmp_path / "acceptance.json",
        acceptance_sha256="1" * 64,
        project_name="mem0-v5-publishable-testlane",
        create_attestation_sha256="2" * 64,
        reopen_attestation_sha256="3" * 64,
        package_closure_sha256="4" * 64,
        deployment_closure_sha256="5" * 64,
        deployment_closure_hmac_sha256="6" * 64,
        deployment_inputs_sha256="7" * 64,
        adapter_source_commit_sha1="8" * 40,
        adapter_source_tree_sha1="9" * 40,
        phase_c_infinity_commit_sha1="a" * 40,
    )
    monkeypatch.setattr(cli, "run_docker_acceptance", lambda **_values: outcome)

    assert cli.main(("acceptance", "--config", str(config_file))) == 0

    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out) == outcome.payload()
    assert "secret" not in captured.out.casefold()


def test_cli_sanitizes_acceptance_driver_identity_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_file = tmp_path / "config.json"
    config_file.write_text("{}")

    def reject(**_values: object) -> object:
        raise AcceptanceDriverIdentityError("publishable_acceptance_driver_changed")

    monkeypatch.setattr(cli, "run_docker_acceptance", reject)

    assert cli.main(("acceptance", "--config", str(config_file))) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "publishable_acceptance_driver_changed\n"


def _acceptance_config(
    tmp_path: Path,
) -> tuple[PublishableLaneConfig, Path, Path]:
    config, proc_root = _config(tmp_path, deployment_dir=DEPLOYMENT)
    for account in config.bridges:
        path = config.paths.fleet_state_dir / account.account_name
        path.mkdir(mode=0o700)
        path.chmod(0o700)
    config_file = tmp_path / "lane-config.json"
    config_file.write_bytes(_canonical_json(config.public_payload()))
    config_file.chmod(0o600)
    return config, proc_root, config_file


def _fake_deployment_attestor(
    config: PublishableLaneConfig,
    *,
    config_file: Path,
    **_values: object,
) -> DeploymentInputEvidence:
    return _deployment_evidence(config, config_file)


def _runtime_attestation_payload(
    config: PublishableLaneConfig,
    *,
    mode: str,
    deployment_inputs_sha256: str,
    generation: int,
) -> dict[str, object]:
    services = {
        service: {
            "bind_mounts_sha256": hashlib.sha256(service.encode()).hexdigest(),
            "container_id": _container_id(service, mode),
            "image_id": config.adapter_image_id,
            "pid": 10_000 + index,
        }
        for index, service in enumerate(SERVICES)
    }
    return {
        "account_i_fence_commitment_sha256": "1" * 64,
        "adapter_image_id": config.adapter_image_id,
        "anchor_container_inventory_sha256": "2" * 64,
        "anchor_netns": {"device": 1, "inode": 2},
        "anchor_pidns": {"device": 1, "inode": 3},
        "bridge_ports": [8891, 8892, 8893],
        "compose_sha256": "3" * 64,
        "deployment_inputs_sha256": deployment_inputs_sha256,
        "fleet": {
            "bridges": [
                {
                    "account_name": account.account_name,
                    "bridge_id": account.bridge_id,
                    "controller_pid": 20_000 + index,
                    "generation": generation,
                    "launch_mode": mode,
                    "process": {"pid": 30_000 + index},
                    "readiness_receipt_sha256": f"{index + 5:x}" * 64,
                    "runtime_authority_sha256": f"{index + 8:x}" * 64,
                }
                for index, account in enumerate(config.bridges)
            ],
            "fleet_readiness_sha256": "b" * 64,
            "pool_authority_sha256": "c" * 64,
            "requested_mode": mode,
        },
        "host_exposure": {
            "container_port": 19191,
            "host_ip": "127.0.0.1",
            "host_port": config.host_adapter_port,
            "relayed_adapter_port": 19091,
        },
        "loopback_bindings_sha256": "d" * 64,
        "observed_at_unix_ns": generation,
        "project_name": config.project_name,
        "qdrant_image_id": "sha256:" + "e" * 64,
        "qdrant_ports": {"grpc": 6335, "http": 6334},
        "schema_version": ATTESTATION_SCHEMA,
        "secret_cross_wire_sha256": "f" * 64,
        "services": services,
    }


def _container_id(service: str, mode: str) -> str:
    offset = SERVICES.index(service) + (1 if mode == "create" else 16)
    return f"{offset:064x}"


def _inventory_project(arguments: tuple[str, ...]) -> str:
    prefix = "label=com.docker.compose.project="
    assert arguments[-2] == "--filter"
    assert arguments[-1].startswith(prefix)
    return arguments[-1][len(prefix) :]


def _exact_project_resources(runner: FakeDockerRunner, project: str) -> tuple[str, ...]:
    containers = tuple(
        identifier for identifier, value in runner.containers.items() if value["Project"] == project
    )
    networks = tuple(
        identifier for identifier, value in runner.networks.items() if value == project
    )
    volumes = tuple(identifier for identifier, value in runner.volumes.items() if value == project)
    return containers + networks + volumes


def _compose_mutations(
    calls: list[tuple[tuple[str, ...], dict[str, str]]],
) -> list[tuple[str, tuple[str, ...]]]:
    result = []
    for arguments, _environment in calls:
        if len(arguments) <= 3 or arguments[3] != "compose":
            continue
        for operation in ("up", "stop", "down"):
            if operation in arguments:
                result.append((operation, arguments))
                break
    return result


def _json_bytes(value: object) -> bytes:
    return _canonical_json(value)


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii")

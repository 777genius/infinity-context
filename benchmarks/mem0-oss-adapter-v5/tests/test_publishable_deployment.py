from __future__ import annotations

import hashlib
import json
import os
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml
from publishable_mem0_v5 import fleet_controller, fleet_spec
from publishable_mem0_v5.config import (
    BASE_INSTRUCTIONS_SHA256,
    COMPOSE_SHA256,
    NODE_EXECUTABLE_SHA256,
    PROTECTED_ACCOUNT_I_AUTH_ROOT,
    PROTECTED_R16_ROOT,
    RUNTIME_ENTRYPOINT_SHA256,
    RUNTIME_MANIFEST_SHA256,
    SOURCE_MANIFEST_SHA256,
    AccountIR16Fence,
    BridgeAccountConfig,
    LanePaths,
    PublishableLaneConfig,
    RuntimeAuthorityConfig,
)
from publishable_mem0_v5.docker_cli import QDRANT_IMAGE, CachedImages, DockerCli
from publishable_mem0_v5.fleet_spec import FleetSpecBuildError, build_bridge_fleet_spec
from publishable_mem0_v5.preflight import (
    DeploymentPreflightError,
    attest_account_i_fence,
    attest_secret_cross_wire,
)
from publishable_mem0_v5.runtime_attestation import (
    RuntimeAttestationError,
    attest_compose_asset,
    attest_runtime_lane,
    write_runtime_attestation,
)

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = ROOT.parents[1]
DEPLOYMENT = ROOT / "deployment"
COMPOSE = DEPLOYMENT / "compose.publishable.yaml"
_QDRANT_ID = "sha256:" + "d" * 64


def test_compose_is_exact_cached_only_anchor_namespace_contract() -> None:
    compose = yaml.safe_load(COMPOSE.read_text())
    services = compose["services"]
    assert set(services) == {
        "publishable-relay-anchor",
        "publishable-qdrant",
        "publishable-bridge-fleet",
        "publishable-adapter",
    }
    assert hashlib.sha256(COMPOSE.read_bytes()).hexdigest() == COMPOSE_SHA256
    assert attest_compose_asset(COMPOSE) == COMPOSE_SHA256
    assert compose["networks"] == {
        "publishable-runtime": {
            "driver": "bridge",
            "internal": False,
            "attachable": False,
        }
    }
    assert services["publishable-relay-anchor"]["networks"] == ["publishable-runtime"]
    assert services["publishable-relay-anchor"]["ports"] == [
        "127.0.0.1:${MEM0_V5_PUBLISHABLE_HOST_ADAPTER_PORT:?set loopback host adapter port}:19191"
    ]
    assert [name for name, item in services.items() if "ports" in item] == [
        "publishable-relay-anchor"
    ]
    for name, item in services.items():
        assert item["pull_policy"] == "never", name
        assert "build" not in item
        assert item.get("network_mode") != "host"
        assert item["user"] == "65532:65532"
        assert item["read_only"] is True
        assert item["cap_drop"] == ["ALL"]
    for name in ("publishable-qdrant", "publishable-bridge-fleet", "publishable-adapter"):
        assert services[name]["network_mode"] == "service:publishable-relay-anchor"
    qdrant = services["publishable-qdrant"]
    assert qdrant["image"] == QDRANT_IMAGE
    expected_qdrant_environment = {
        "QDRANT__SERVICE__HOST": "127.0.0.1",
        "QDRANT__SERVICE__HTTP_PORT": "6334",
        "QDRANT__SERVICE__GRPC_PORT": "6335",
    }
    assert expected_qdrant_environment.items() <= qdrant["environment"].items()
    fleet = services["publishable-bridge-fleet"]
    assert fleet["pid"] == "service:publishable-relay-anchor"
    assert fleet["environment"]["MEM0_V5_PUBLISHABLE_FLEET_PORTS"] == "8891,8892,8893"
    adapter = services["publishable-adapter"]
    assert adapter["command"][adapter["command"].index("--port") + 1] == "19091"
    assert adapter["environment"]["MEM0_V5_QDRANT_ORIGIN"] == "http://127.0.0.1:6334"
    lowered = COMPOSE.read_text().lower()
    assert "ollama" not in lowered
    assert "network_mode: host" not in lowered


def test_configured_console_command_packages_the_deployment_module() -> None:
    benchmark = tomllib.loads((ROOT / "pyproject.toml").read_text())
    repository = tomllib.loads((REPOSITORY / "pyproject.toml").read_text())
    expected = "publishable_mem0_v5.cli:main"
    assert benchmark["project"]["scripts"]["infinity-context-publishable-mem0-v5"] == expected
    assert repository["project"]["scripts"]["infinity-context-publishable-mem0-v5"] == expected
    assert "deployment" in benchmark["tool"]["setuptools"]["packages"]["find"]["where"]
    assert (
        "benchmarks/mem0-oss-adapter-v5/deployment"
        in (repository["tool"]["setuptools"]["packages"]["find"]["where"])
    )


def test_secret_cross_wire_is_exact_and_cross_account_swap_fails(tmp_path: Path) -> None:
    config, _ = _config(tmp_path)
    _write_cross_wire(config)
    commitment = attest_secret_cross_wire(
        config,
        expected_uid=os.geteuid(),
        expected_gid=os.getegid(),
    )
    assert len(commitment) == 64
    wrong = config.paths.fleet_auth_dir / config.bridges[1].account_name
    _private_directory(wrong)
    _private_file(wrong / "ingress-api-key.secret", b"x" * 48)
    primary = config.paths.fleet_auth_dir / config.bridges[0].account_name
    (primary / "ingress-api-key.secret").write_bytes(b"x" * 48)
    os.chmod(primary / "ingress-api-key.secret", 0o600)
    with pytest.raises(DeploymentPreflightError, match="secret_cross_wire"):
        attest_secret_cross_wire(
            config,
            expected_uid=os.geteuid(),
            expected_gid=os.getegid(),
        )


def test_account_i_fence_rechecks_start_ticks_boot_and_netns(tmp_path: Path) -> None:
    config, proc_root = _config(tmp_path)
    evidence = attest_account_i_fence(config.account_i_r16_fence, proc_root=proc_root)
    assert evidence.pid == config.account_i_r16_fence.pid
    assert evidence.netns_inode == config.account_i_r16_fence.netns_inode
    (proc_root / "sys/kernel/random/boot_id").write_text("22222222-2222-2222-2222-222222222222\n")
    with pytest.raises(DeploymentPreflightError, match="identity_changed"):
        attest_account_i_fence(config.account_i_r16_fence, proc_root=proc_root)


def test_production_fleet_spec_has_three_cross_wired_bridges(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, proc_root = _config(tmp_path)
    state = tmp_path / "container" / "state"
    auth = tmp_path / "container" / "auth"
    _private_directory(state)
    _private_directory(auth)
    monkeypatch.setattr(fleet_spec, "CONTAINER_FLEET_STATE_ROOT", state)
    monkeypatch.setattr(fleet_spec, "CONTAINER_FLEET_AUTH_ROOT", auth)
    monkeypatch.setattr(fleet_spec, "CONTAINER_RUNTIME_ROOT", tmp_path / "runtime")
    monkeypatch.setattr(fleet_spec, "CONTAINER_NODE_EXECUTABLE", tmp_path / "bin/node")
    monkeypatch.setattr(fleet_spec, "CONTAINER_CODEX_EXECUTABLE", tmp_path / "bin/codex")
    for index, account in enumerate(config.bridges):
        state_root = state / account.account_name
        auth_root = auth / account.account_name
        _private_directory(state_root)
        _private_directory(auth_root)
        _private_directory(auth_root / account.account_name)
        _private_file(
            auth_root / "account-binding-hmac-sha256",
            account.account_binding_hmac_sha256.encode(),
        )
        _private_file(auth_root / "base-instructions-sha256", BASE_INSTRUCTIONS_SHA256.encode())
        _private_file(auth_root / "ingress-api-key.secret", f"api-{index}".encode() * 16)
        _private_file(auth_root / "attestation-hmac.secret", f"attest-{index}".encode() * 8)
        _private_file(auth_root / "launcher-receipt.key", f"launcher-{index}".encode() * 8)
        if index == 0:
            _private_file(auth_root / "runtime-transport-origin", b"http://127.0.0.1:8891")
    spec = build_bridge_fleet_spec(config, proc_root=proc_root)
    assert tuple(item.port for item in spec.processes) == (8891, 8892, 8893)
    assert tuple(item.account_name for item in spec.processes) == tuple(
        item.account_name for item in config.bridges
    )
    assert spec.account_i_fence.pid == config.account_i_r16_fence.pid
    assert spec.processes[0].authority.origin == "http://127.0.0.1:8891"
    assert all("account-i" not in repr(item).casefold() for item in spec.processes)
    _private_file(auth / config.bridges[1].account_name / "launcher-receipt.key", b"launcher-0" * 8)
    with pytest.raises(FleetSpecBuildError, match="secret_reuse"):
        build_bridge_fleet_spec(config, proc_root=proc_root)


def test_partial_reopen_archives_and_creates_a_fresh_three_root_fleet(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, proc_root = _config(tmp_path)
    state = tmp_path / "container" / "state"
    auth = tmp_path / "container" / "auth"
    _private_directory(state)
    _private_directory(auth)
    monkeypatch.setattr(fleet_spec, "CONTAINER_FLEET_STATE_ROOT", state)
    monkeypatch.setattr(fleet_spec, "CONTAINER_FLEET_AUTH_ROOT", auth)
    monkeypatch.setattr(fleet_controller, "CONTAINER_FLEET_STATE_ROOT", state)
    monkeypatch.setattr(fleet_controller, "_RECOVERY_ROOT", state / ".partial-start-recovery")
    monkeypatch.setattr(fleet_controller, "_tcp_open", lambda port: False)
    monkeypatch.setattr(fleet_controller, "_pid_exists", lambda pid: False)
    for index, account in enumerate(config.bridges):
        state_root = state / account.account_name
        auth_root = auth / account.account_name
        _private_directory(state_root)
        _private_directory(auth_root)
        _private_directory(auth_root / account.account_name)
        _private_file(
            auth_root / "account-binding-hmac-sha256",
            account.account_binding_hmac_sha256.encode(),
        )
        _private_file(auth_root / "base-instructions-sha256", BASE_INSTRUCTIONS_SHA256.encode())
        _private_file(auth_root / "ingress-api-key.secret", f"api-{index}".encode() * 16)
        _private_file(auth_root / "attestation-hmac.secret", f"attest-{index}".encode() * 8)
        _private_file(auth_root / "launcher-receipt.key", f"launcher-{index}".encode() * 8)
        if index == 0:
            _private_file(auth_root / "runtime-transport-origin", b"http://127.0.0.1:8891")
    (state / config.bridges[0].account_name / "partial.json").write_text("partial")
    spec = build_bridge_fleet_spec(config, proc_root=proc_root)
    factory = _FleetFactory()
    result = fleet_controller.open_fleet_with_partial_recovery(
        config=config,
        spec=spec,
        mode="reopen",
        factory=factory,
    )
    assert result == "fresh-fleet"
    assert factory.calls == ["create"]
    recoveries = list((state / ".partial-start-recovery").iterdir())
    assert len(recoveries) == 1
    assert (recoveries[0] / config.bridges[0].account_name / "partial.json").is_file()
    assert all(not any(item.state_root.iterdir()) for item in spec.processes)


def test_docker_start_command_is_cached_only_and_never_builds(tmp_path: Path) -> None:
    config, _ = _config(tmp_path)
    config_file = tmp_path / "config.json"
    config_file.write_text("{}")
    runner = _RecordingRunner()
    docker = DockerCli(config, config_file=config_file, runner=runner)
    cached = docker.inspect_cached_images()
    docker.start(mode="reopen")
    assert cached == CachedImages(config.adapter_image_id, _QDRANT_ID)
    start = runner.calls[-1][0]
    assert start[-6:] == (
        "up",
        "--detach",
        "--pull",
        "never",
        "--no-build",
        "--wait",
    )
    assert "build" not in start and "pull" not in start
    assert runner.calls[-1][1]["MEM0_V5_PUBLISHABLE_FLEET_MODE"] == "reopen"


def test_full_runtime_attestation_binds_image_netns_mount_user_and_port(
    tmp_path: Path,
) -> None:
    config, proc_root = _config(tmp_path, deployment_dir=DEPLOYMENT)
    config_file = tmp_path / "lane-config.json"
    config_file.write_text("fixture")
    containers, network = _runtime_inventory(config, config_file, proc_root)
    runner = _RuntimeRunner(config, containers, network)
    docker = DockerCli(config, config_file=config_file, runner=runner)
    cached = docker.inspect_cached_images()
    before = attest_account_i_fence(config.account_i_r16_fence, proc_root=proc_root)
    attestation = attest_runtime_lane(
        config=config,
        docker=docker,
        cached_images=cached,
        account_i_before=before,
        secret_cross_wire_sha256="f" * 64,
        fleet_mode="reopen",
        proc_root=proc_root,
    )
    assert attestation.anchor_netns.inode != config.account_i_r16_fence.netns_inode
    assert set(attestation.services) == set(containers)
    assert attestation.payload()["host_exposure"] == {
        "container_port": 19191,
        "host_ip": "127.0.0.1",
        "host_port": config.host_adapter_port,
        "relayed_adapter_port": 19091,
    }
    path = write_runtime_attestation(attestation, config.paths.attestation_dir)
    assert json.loads(path.read_bytes()) == attestation.payload()
    assert write_runtime_attestation(attestation, config.paths.attestation_dir) == path
    assert any("exec" in call[0] for call in runner.calls)


@pytest.mark.parametrize("difference", ["image", "netns", "mount", "user", "port"])
def test_runtime_attestation_rejects_each_runtime_difference(
    tmp_path: Path,
    difference: str,
) -> None:
    config, proc_root = _config(tmp_path, deployment_dir=DEPLOYMENT)
    config_file = tmp_path / "lane-config.json"
    config_file.write_text("fixture")
    containers, network = _runtime_inventory(config, config_file, proc_root)
    adapter = containers["publishable-adapter"]
    if difference == "image":
        adapter["Image"] = "sha256:" + "e" * 64
    elif difference == "netns":
        path = proc_root / str(adapter["State"]["Pid"]) / "ns/net"
        path.unlink()
        path.write_text("different-netns")
    elif difference == "mount":
        adapter["Mounts"][0]["Source"] = "/tmp/cross-wired-input"
    elif difference == "user":
        adapter["Config"]["User"] = "0:0"
    else:
        adapter["HostConfig"]["PortBindings"] = {
            "19091/tcp": [{"HostIp": "0.0.0.0", "HostPort": "19091"}]
        }
    runner = _RuntimeRunner(config, containers, network)
    docker = DockerCli(config, config_file=config_file, runner=runner)
    cached = docker.inspect_cached_images()
    before = attest_account_i_fence(config.account_i_r16_fence, proc_root=proc_root)
    with pytest.raises(RuntimeAttestationError):
        attest_runtime_lane(
            config=config,
            docker=docker,
            cached_images=cached,
            account_i_before=before,
            secret_cross_wire_sha256="f" * 64,
            fleet_mode="reopen",
            proc_root=proc_root,
        )


class _FleetFactory:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def create_new(self, spec: object) -> str:
        del spec
        self.calls.append("create")
        return "fresh-fleet"

    def reopen(self, spec: object) -> str:
        del spec
        self.calls.append("reopen")
        return "reopened-fleet"


class _RecordingRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], dict[str, str]]] = []

    def run(self, arguments: tuple[str, ...], *, environment: Any) -> bytes:
        self.calls.append((arguments, dict(environment)))
        if arguments[3:5] == ("image", "inspect"):
            reference = arguments[5]
            if reference == QDRANT_IMAGE:
                digest = QDRANT_IMAGE.split("@", 1)[1]
                return _json_bytes([{"Id": _QDRANT_ID, "RepoDigests": [f"qdrant/qdrant@{digest}"]}])
            return _json_bytes([{"Id": reference, "RepoDigests": []}])
        return b""


class _RuntimeRunner(_RecordingRunner):
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
                return _json_bytes([{"Id": _QDRANT_ID, "RepoDigests": [f"qdrant/qdrant@{digest}"]}])
            return _json_bytes([{"Id": reference, "RepoDigests": []}])
        if arguments[3] == "compose" and "ps" in arguments:
            return (self.containers[arguments[-1]]["Id"] + "\n").encode()
        if arguments[3] == "inspect":
            by_id = {item["Id"]: item for item in self.containers.values()}
            return _json_bytes([by_id[item] for item in arguments[4:]])
        if arguments[3:5] == ("network", "inspect"):
            return _json_bytes([self.network])
        if arguments[3] == "exec":
            return b""
        raise AssertionError(arguments)


def _config(
    tmp_path: Path,
    *,
    deployment_dir: Path | None = None,
) -> tuple[PublishableLaneConfig, Path]:
    project = "mem0-v5-publishable-testlane"
    run_root = tmp_path / project
    private_names = (
        "input",
        "adapter-state",
        "qdrant-state",
        "adapter-secrets",
        "fleet-state",
        "fleet-auth",
        "attestation",
    )
    for name in private_names:
        _private_directory(run_root / name)
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
    protected_inode = (process / "ns/net").stat().st_ino
    fence = AccountIR16Fence(
        pid=pid,
        start_ticks=ticks,
        boot_id=boot_id,
        netns_inode=protected_inode,
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
        paths=paths,
        runtime=runtime,
        bridges=bridges,
        account_i_r16_fence=fence,
    )
    _namespace_fixture(proc_root)
    return config, proc_root


def _namespace_fixture(proc_root: Path) -> None:
    self_ns = proc_root / "self/ns"
    init_ns = proc_root / "1/ns"
    self_ns.mkdir(parents=True)
    init_ns.mkdir(parents=True)
    (self_ns / "net").write_text("anchor-net")
    os.link(self_ns / "net", init_ns / "net")
    (self_ns / "pid").write_text("anchor-pid")
    os.link(self_ns / "pid", init_ns / "pid")


def _write_cross_wire(config: PublishableLaneConfig) -> None:
    adapter = config.paths.adapter_secret_dir
    primary = config.paths.fleet_auth_dir / config.bridges[0].account_name
    _private_directory(primary)
    values = {
        "runtime-bearer": b"runtime-bearer-" * 4,
        "runtime-receipt-secret": b"runtime-receipt-" * 4,
        "account-binding-hmac-sha256": config.bridges[0].account_binding_hmac_sha256.encode(),
        "base-instructions-sha256": BASE_INSTRUCTIONS_SHA256.encode(),
        "runtime-transport-origin": b"http://127.0.0.1:8891",
    }
    primary_names = {
        "runtime-bearer": "ingress-api-key.secret",
        "runtime-receipt-secret": "attestation-hmac.secret",
        "account-binding-hmac-sha256": "account-binding-hmac-sha256",
        "base-instructions-sha256": "base-instructions-sha256",
        "runtime-transport-origin": "runtime-transport-origin",
    }
    for name, raw in values.items():
        _private_file(adapter / name, raw)
        _private_file(primary / primary_names[name], raw)


def _runtime_inventory(
    config: PublishableLaneConfig,
    config_file: Path,
    proc_root: Path,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    ids = {
        "publishable-relay-anchor": "1" * 64,
        "publishable-qdrant": "2" * 64,
        "publishable-bridge-fleet": "3" * 64,
        "publishable-adapter": "4" * 64,
    }
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
            if name == "publishable-bridge-fleet":
                os.link(anchor_pid, namespace / "pid")
            else:
                (namespace / "pid").write_text(name)
    paths = config.paths
    mounts = {
        "publishable-relay-anchor": {
            "/opt/publishable/deployment": (paths.deployment_dir, False),
        },
        "publishable-qdrant": {"/qdrant/storage": (paths.qdrant_state_dir, True)},
        "publishable-bridge-fleet": {
            "/run/publishable-config/config.json": (config_file, False),
            "/run/publishable-fleet/state": (paths.fleet_state_dir, True),
            "/run/publishable-fleet/auth": (paths.fleet_auth_dir, False),
            "/run/publishable-attestation": (paths.attestation_dir, True),
            "/opt/publishable/runtime": (config.runtime.runtime_root, False),
            "/opt/publishable/source/phase-c": (paths.phase_c_authority_dir, False),
            "/run/source-authority": (paths.source_authority_dir, False),
            "/run/source-authority-pin": (paths.source_authority_pin_dir, False),
            "/opt/publishable/bin/node": (config.runtime.node_executable, False),
            "/opt/publishable/bin/codex": (config.runtime.codex_executable, False),
            "/opt/publishable/server": (paths.server_package_dir, False),
            "/opt/publishable/deployment": (paths.deployment_dir, False),
        },
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
    network_name = f"{config.project_name}_publishable-runtime"
    commands = {
        "publishable-relay-anchor": [
            "python",
            "-m",
            "publishable_mem0_v5.relay",
            "serve",
        ],
        "publishable-qdrant": ["./entrypoint.sh"],
        "publishable-bridge-fleet": [
            "python",
            "-m",
            "publishable_mem0_v5.fleet_controller",
            "serve",
            "--mode",
            "reopen",
        ],
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
    environments = {
        "publishable-relay-anchor": ["PYTHONPATH=/opt/publishable/deployment"],
        "publishable-qdrant": [
            "QDRANT__SERVICE__HOST=127.0.0.1",
            "QDRANT__SERVICE__HTTP_PORT=6334",
            "QDRANT__SERVICE__GRPC_PORT=6335",
        ],
        "publishable-bridge-fleet": [
            "MEM0_V5_PUBLISHABLE_FLEET_PORTS=8891,8892,8893",
            f"MEM0_V5_PUBLISHABLE_PRIMARY_ACCOUNT={config.bridges[0].account_name}",
        ],
        "publishable-adapter": [
            "MEM0_V5_QDRANT_ORIGIN=http://127.0.0.1:6334",
            "MEM0_V5_RUNTIME_TRANSPORT_ORIGIN_FILE=/run/secrets/runtime-transport-origin",
            "HF_HUB_OFFLINE=1",
            "TRANSFORMERS_OFFLINE=1",
        ],
    }
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
                "PidMode": f"container:{anchor}" if name == "publishable-bridge-fleet" else "",
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


def _proc_stat(pid: int, ticks: int) -> str:
    fields = ["S", *("1" for _ in range(49))]
    fields[19] = str(ticks)
    return f"{pid} (account i) {' '.join(fields)}\n"


def _private_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path, 0o700)


def _private_file(path: Path, raw: bytes) -> None:
    path.write_bytes(raw)
    os.chmod(path, 0o600)


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()

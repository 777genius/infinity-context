from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import tomllib
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
import yaml
from infinity_context_server.features.subscription_runtime_bridge.contracts import BridgeAuthority
from infinity_context_server.features.subscription_runtime_bridge.process_contracts import (
    BridgeLaunchReceipt,
    PendingLaunchMetadata,
    ProcessIdentity,
    RuntimeHealthEvidence,
)
from publishable_mem0_v5 import (
    fleet_controller,
    fleet_spec,
    runtime_attestation,
    runtime_integrity,
)
from publishable_mem0_v5.bridge_dispatch import (
    DISPATCH_PORT_HEADER,
    DISPATCH_ROUTE,
    BridgeDispatchError,
    HttpxRelayBridgeTransport,
    authenticate_dispatch,
    build_dispatch_headers,
)
from publishable_mem0_v5.config import (
    BASE_INSTRUCTIONS_SHA256,
    COMPOSE_SHA256,
    PINNED_DOCKER_HOST,
    RUNTIME_PIN_SHA256,
    SOURCE_COMMIT_SHA256,
    DeploymentConfigError,
)
from publishable_mem0_v5.docker_cli import QDRANT_IMAGE, SERVICES, CachedImages, DockerCli
from publishable_mem0_v5.fleet_spec import FleetSpecBuildError, build_isolated_bridge_spec
from publishable_mem0_v5.preflight import (
    DeploymentPreflightError,
    attest_account_i_fence,
    attest_secret_cross_wire,
    load_runtime_attestation_key,
)
from publishable_mem0_v5.runtime_attestation import (
    RuntimeAttestationError,
    attest_compose_asset,
    attest_runtime_lane,
    write_runtime_attestation,
)

from tests.publishable_deployment_runtime_fixture import (
    BridgeFactory as _BridgeFactory,
)
from tests.publishable_deployment_runtime_fixture import (
    RecordingRunner as _RecordingRunner,
)
from tests.publishable_deployment_runtime_fixture import (
    RuntimeRunner as _RuntimeRunner,
)
from tests.publishable_deployment_runtime_fixture import (
    build_config as _config,
)
from tests.publishable_deployment_runtime_fixture import (
    deployment_evidence as _deployment_evidence,
)
from tests.publishable_deployment_runtime_fixture import (
    json_bytes as _json_bytes,
)
from tests.publishable_deployment_runtime_fixture import (
    private_directory as _private_directory,
)
from tests.publishable_deployment_runtime_fixture import (
    private_file as _private_file,
)
from tests.publishable_deployment_runtime_fixture import (
    runtime_inventory as _runtime_inventory,
)
from tests.publishable_deployment_runtime_fixture import (
    stub_runtime_dependencies as _stub_runtime_dependencies,
)
from tests.publishable_deployment_runtime_fixture import (
    write_cross_wire as _write_cross_wire,
)

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = ROOT.parents[1]
DEPLOYMENT = ROOT / "deployment"
COMPOSE = DEPLOYMENT / "compose.publishable.yaml"
_QDRANT_ID = "sha256:" + "d" * 64
_STALE_RUNTIME_PIN_SHA256 = "f8f338b73d816d87981745b240026d802fb52c1a228b0e608231a4ef9ad33e46"
_STALE_SOURCE_COMMIT_SHA256 = "ed27595275c2a0a884c15c28f9891088180ef3be734ee8304a8fbeaa68e953a7"


def test_compose_is_exact_cached_only_anchor_namespace_contract() -> None:
    compose = yaml.safe_load(COMPOSE.read_text())
    services = compose["services"]
    assert tuple(services) == SERVICES
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
    anchor = services["publishable-relay-anchor"]
    assert anchor["environment"]["PYTHONPATH"] == (
        "/opt/publishable/deployment:/opt/publishable/server"
    )
    assert {
        item["target"]: (item["source"], item["read_only"])
        for item in anchor["volumes"]
    } == {
        "/opt/publishable/deployment": (
            "${MEM0_V5_PUBLISHABLE_DEPLOYMENT_DIR:?set immutable deployment directory}",
            True,
        ),
        "/opt/publishable/server": (
            "${MEM0_V5_PUBLISHABLE_SERVER_PACKAGE_DIR:?set immutable server package directory}",
            True,
        ),
    }
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
    for name in SERVICES[1:]:
        assert services[name]["network_mode"] == "service:publishable-relay-anchor"
    qdrant = services["publishable-qdrant"]
    assert qdrant["image"] == QDRANT_IMAGE
    expected_qdrant_environment = {
        "QDRANT__SERVICE__HOST": "127.0.0.1",
        "QDRANT__SERVICE__HTTP_PORT": "6334",
        "QDRANT__SERVICE__GRPC_PORT": "6335",
    }
    assert expected_qdrant_environment.items() <= qdrant["environment"].items()
    bridge_services = SERVICES[2:5]
    bridge_mount_sources: list[tuple[str, str]] = []
    for index, name in enumerate(bridge_services):
        bridge = services[name]
        assert "pid" not in bridge
        assert bridge["command"][-2:] == ["--account-index", str(index)]
        mounts = {item["target"]: item["source"] for item in bridge["volumes"]}
        bridge_mount_sources.append(
            (
                mounts["/run/publishable-bridge-state"],
                mounts["/run/publishable-bridge-auth"],
            )
        )
    assert len(set(bridge_mount_sources)) == 3
    assert all("FLEET_" not in source for pair in bridge_mount_sources for source in pair)
    adapter = services["publishable-adapter"]
    assert adapter["command"][adapter["command"].index("--port") + 1] == "19091"
    assert adapter["environment"]["MEM0_V5_QDRANT_ORIGIN"] == "http://127.0.0.1:6334"
    assert adapter["environment"]["MEM0_V5_SOURCE_AUTHORITY_MANIFEST_FILE"] == (
        "/run/source-authority-pin/manifest.json"
    )
    assert adapter["environment"]["MEM0_V5_SOURCE_AUTHORITY_MANIFEST_SHA256_FILE"] == (
        "/run/source-authority-pin/manifest.sha256"
    )
    adapter_mounts = {item["target"]: item for item in adapter["volumes"]}
    assert adapter_mounts["/run/source-authority"]["source"] == (
        "${MEM0_V5_PUBLISHABLE_SOURCE_AUTHORITY_DIR:?set immutable source authority directory}"
    )
    assert adapter_mounts["/run/source-authority-pin"]["source"] == (
        "${MEM0_V5_PUBLISHABLE_SOURCE_AUTHORITY_PIN_DIR:?set immutable source pin directory}"
    )
    assert adapter_mounts["/run/source-authority-pin/manifest.sha256"]["source"] == (
        "${MEM0_V5_PUBLISHABLE_SOURCE_AUTHORITY_PIN_SHA256_FILE:?set immutable source pin digest}"
    )
    assert all(
        adapter_mounts[target]["read_only"]
        for target in (
            "/run/source-authority",
            "/run/source-authority-pin",
            "/run/source-authority-pin/manifest.sha256",
        )
    )
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


def test_lane_config_runtime_authority_rejects_stale_and_cross_wired_tuple(
    tmp_path: Path,
) -> None:
    config, _ = _config(tmp_path)

    assert config.runtime.runtime_pin_sha256 == RUNTIME_PIN_SHA256
    assert config.runtime.source_commit_sha256 == SOURCE_COMMIT_SHA256
    with pytest.raises(DeploymentConfigError, match="publishable_lane_runtime_pin_stale"):
        replace(config.runtime, runtime_pin_sha256=_STALE_RUNTIME_PIN_SHA256)
    with pytest.raises(
        DeploymentConfigError,
        match="publishable_lane_runtime_source_cross_wire",
    ):
        replace(config.runtime, source_commit_sha256=_STALE_SOURCE_COMMIT_SHA256)


def test_single_dispatcher_authenticates_the_selected_private_bridge_port() -> None:
    body = b'{"model":"gpt-5.6-sol","messages":[]}'
    bearer = "private-bridge-bearer"
    headers = {
        **build_dispatch_headers(
            bridge_port=8891,
            bearer_token=bearer,
            request_body=body,
        ),
        "Authorization": f"Bearer {bearer}",
    }
    assert (
        authenticate_dispatch(
            method="POST",
            target="/v1/chat/completions",
            headers=headers,
            request_body=body,
        )
        == 8891
    )

    headers[DISPATCH_PORT_HEADER] = "8892"
    with pytest.raises(BridgeDispatchError, match="authentication_invalid"):
        authenticate_dispatch(
            method="POST",
            target="/v1/chat/completions",
            headers=headers,
            request_body=body,
        )


def test_secret_cross_wire_is_exact_and_cross_account_secret_reuse_fails(
    tmp_path: Path,
) -> None:
    config, _ = _config(tmp_path)
    _write_cross_wire(config)
    commitment = attest_secret_cross_wire(
        config,
        expected_uid=os.geteuid(),
        expected_gid=os.getegid(),
    )
    assert len(commitment) == 64
    assert (
        load_runtime_attestation_key(
            config,
            expected_uid=os.geteuid(),
            expected_gid=os.getegid(),
        )
        == (config.paths.adapter_secret_dir / "runtime-attestation-secret").read_bytes()
    )
    primary = config.paths.fleet_auth_dir / config.bridges[0].account_name
    wrong = config.paths.fleet_auth_dir / config.bridges[1].account_name
    _private_file(wrong / "launcher-receipt.key", (primary / "launcher-receipt.key").read_bytes())
    with pytest.raises(DeploymentPreflightError, match="bridge_secret_reuse"):
        attest_secret_cross_wire(
            config,
            expected_uid=os.geteuid(),
            expected_gid=os.getegid(),
        )
    _private_file(config.paths.adapter_secret_dir / "runtime-attestation-secret", b"short")
    with pytest.raises(DeploymentPreflightError, match="attestation_key_invalid"):
        load_runtime_attestation_key(
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


def test_production_builds_one_isolated_spec_per_bridge_account(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, proc_root = _config(tmp_path)
    monkeypatch.setattr(fleet_spec, "CONTAINER_RUNTIME_ROOT", tmp_path / "runtime")
    monkeypatch.setattr(fleet_spec, "CONTAINER_NODE_EXECUTABLE", tmp_path / "bin/node")
    monkeypatch.setattr(fleet_spec, "CONTAINER_CODEX_EXECUTABLE", tmp_path / "bin/codex")
    specs = []
    for index, account in enumerate(config.bridges):
        container = tmp_path / "container" / str(index)
        state_base = container / "state"
        state_root = state_base / "current"
        auth_root = container / "auth"
        _private_directory(state_base)
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
        monkeypatch.setattr(fleet_spec, "CONTAINER_BRIDGE_STATE_BASE", state_base)
        monkeypatch.setattr(fleet_spec, "CONTAINER_BRIDGE_STATE_ROOT", state_root)
        monkeypatch.setattr(fleet_spec, "CONTAINER_BRIDGE_AUTH_ROOT", auth_root)
        specs.append(build_isolated_bridge_spec(config, account_index=index, proc_root=proc_root))
    assert tuple(item.process.port for item in specs) == (8891, 8892, 8893)
    assert tuple(item.process.account_name for item in specs) == tuple(
        item.account_name for item in config.bridges
    )
    assert all(item.account_i_fence.pid == config.account_i_r16_fence.pid for item in specs)
    assert specs[0].process.authority.origin == "http://127.0.0.1:8891"
    assert all("account-i" not in repr(item.process).casefold() for item in specs)

    crossed_auth = tmp_path / "container" / "1" / "auth"
    _private_file(
        crossed_auth / "account-binding-hmac-sha256",
        config.bridges[0].account_binding_hmac_sha256.encode(),
    )
    monkeypatch.setattr(fleet_spec, "CONTAINER_BRIDGE_STATE_BASE", tmp_path / "container/1/state")
    monkeypatch.setattr(
        fleet_spec,
        "CONTAINER_BRIDGE_STATE_ROOT",
        tmp_path / "container/1/state/current",
    )
    monkeypatch.setattr(fleet_spec, "CONTAINER_BRIDGE_AUTH_ROOT", crossed_auth)
    with pytest.raises(FleetSpecBuildError, match="account_binding_crosswire"):
        build_isolated_bridge_spec(config, account_index=1, proc_root=proc_root)


def test_partial_reopen_archives_only_the_isolated_bridge_state_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, proc_root = _config(tmp_path)
    state = tmp_path / "container" / "state"
    current = state / "current"
    auth = tmp_path / "container" / "auth"
    _private_directory(state)
    _private_directory(current)
    _private_directory(auth)
    monkeypatch.setattr(fleet_spec, "CONTAINER_BRIDGE_STATE_BASE", state)
    monkeypatch.setattr(fleet_spec, "CONTAINER_BRIDGE_STATE_ROOT", current)
    monkeypatch.setattr(fleet_spec, "CONTAINER_BRIDGE_AUTH_ROOT", auth)
    monkeypatch.setattr(fleet_controller, "CONTAINER_BRIDGE_STATE_BASE", state)
    monkeypatch.setattr(fleet_controller, "_tcp_open", lambda port: False)
    monkeypatch.setattr(fleet_controller, "_pid_exists", lambda pid: False)
    account = config.bridges[0]
    _private_directory(auth / account.account_name)
    _private_file(
        auth / "account-binding-hmac-sha256", account.account_binding_hmac_sha256.encode()
    )
    _private_file(auth / "base-instructions-sha256", BASE_INSTRUCTIONS_SHA256.encode())
    _private_file(auth / "ingress-api-key.secret", b"api-0" * 16)
    _private_file(auth / "attestation-hmac.secret", b"attest-0" * 8)
    _private_file(auth / "launcher-receipt.key", b"launcher-0" * 8)
    _private_file(auth / "runtime-transport-origin", b"http://127.0.0.1:8891")
    (current / "partial.json").write_text("partial")
    spec = build_isolated_bridge_spec(config, account_index=0, proc_root=proc_root)
    factory = _BridgeFactory()
    result = fleet_controller.open_bridge_with_partial_recovery(
        spec=spec,
        mode="reopen",
        factory=factory,
    )
    assert result == "fresh-bridge"
    assert factory.calls == ["create"]
    recoveries = list((state / ".partial-start-recovery").iterdir())
    assert len(recoveries) == 1
    assert (recoveries[0] / "partial.json").is_file()
    assert not any(spec.process.state_root.iterdir())


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
    assert start[-8:] == (
        "up",
        "--detach",
        "--pull",
        "never",
        "--no-build",
        "--wait",
        "--wait-timeout",
        "120",
    )
    assert "build" not in start and "pull" not in start
    environment = config.compose_environment(config_file=config_file, fleet_mode="reopen")
    compose_variables = set(re.findall(r"\$\{([A-Z0-9_]+)", COMPOSE.read_text()))
    assert set(environment) == compose_variables | {"DOCKER_HOST"}
    assert environment["MEM0_V5_PUBLISHABLE_FLEET_MODE"] == "reopen"
    for label, account in zip(("A", "B", "C"), config.bridges, strict=True):
        assert environment[f"MEM0_V5_PUBLISHABLE_BRIDGE_{label}_AUTH_DIR"] == str(
            config.paths.fleet_auth_dir / account.account_name
        )
        assert environment[f"MEM0_V5_PUBLISHABLE_BRIDGE_{label}_STATE_DIR"] == str(
            config.paths.fleet_state_dir / account.account_name
        )


@pytest.mark.parametrize("mode", ("create", "reopen"))
def test_docker_start_then_inspection_uses_exact_compose_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    config, _ = _config(tmp_path)
    config_file = tmp_path / "config.json"
    config_file.write_text("{}")
    monkeypatch.setenv("HTTPS_PROXY", "http://ambient-proxy.invalid")
    monkeypatch.setenv("DOCKER_HOST", "unix:///var/run/docker.sock")
    runner = _RecordingRunner()
    docker = DockerCli(config, config_file=config_file, runner=runner)

    docker.start(mode=mode)
    container_ids = docker.container_ids(mode=mode)

    assert container_ids == {
        service: f"{index:064x}" for index, service in enumerate(SERVICES, start=1)
    }
    expected_environment = {
        "LANG": "C.UTF-8",
        "PATH": os.defpath,
        **config.compose_environment(config_file=config_file, fleet_mode=mode),
    }
    compose_calls = [call for call in runner.calls if call[0][3] == "compose"]
    assert len(compose_calls) == len(SERVICES) + 1
    assert all(environment == expected_environment for _, environment in compose_calls)
    assert all(
        arguments[:3] == ("/usr/bin/docker", "--host", PINNED_DOCKER_HOST)
        for arguments, _ in runner.calls
    )
    assert all(environment["DOCKER_HOST"] == PINNED_DOCKER_HOST for _, environment in runner.calls)


def test_run_provider_dispatches_selected_bridge_through_the_only_host_relay() -> None:
    request_body = b'{"messages":[{"role":"user","content":"bounded"}]}'
    observed: dict[str, object] = {}

    def relay(request: httpx.Request) -> httpx.Response:
        observed["url"] = str(request.url)
        observed["bridge_port"] = authenticate_dispatch(
            method=request.method,
            target=request.url.path,
            headers=dict(request.headers),
            request_body=request.content,
        )
        return httpx.Response(200, stream=httpx.ByteStream(b'{"choices":[]}'))

    transport = HttpxRelayBridgeTransport(
        relay_origin="http://127.0.0.1:29191",
        maximum_request_bytes=1024,
        transport=httpx.MockTransport(relay),
    )
    response = transport.post_once(
        origin="http://127.0.0.1:8892",
        route=DISPATCH_ROUTE,
        bearer_token="b" * 32,
        request_body=request_body,
        maximum_response_bytes=1024,
    )

    assert response == b'{"choices":[]}'
    assert observed == {
        "bridge_port": 8892,
        "url": "http://127.0.0.1:29191/v1/chat/completions",
    }


def test_full_runtime_attestation_binds_image_netns_mount_user_and_port(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, proc_root = _config(tmp_path, deployment_dir=DEPLOYMENT)
    config_file = tmp_path / "lane-config.json"
    config_file.write_text("fixture")
    containers, network = _runtime_inventory(config, config_file, proc_root)
    runner = _RuntimeRunner(config, containers, network)
    docker = DockerCli(config, config_file=config_file, runner=runner)
    cached = docker.inspect_cached_images()
    before = attest_account_i_fence(config.account_i_r16_fence, proc_root=proc_root)
    deployment_before = _deployment_evidence(config, config_file)
    _stub_runtime_dependencies(monkeypatch, config, deployment_before)
    attestation = attest_runtime_lane(
        config=config,
        docker=docker,
        cached_images=cached,
        account_i_before=before,
        deployment_before=deployment_before,
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
    assert len(attestation.payload()["relay_reachability_sha256"]) == 64
    key = b"host-runtime-attestation-key" * 2
    receipt = write_runtime_attestation(
        attestation,
        config.paths.attestation_dir,
        authentication_key=key,
        expected_uid=os.geteuid(),
        expected_gid=os.getegid(),
    )
    payload = json.loads(receipt.path.read_bytes())
    unsigned = attestation.payload()
    expected_hmac = hmac.new(
        key,
        runtime_attestation.ATTESTATION_HMAC_DOMAIN + _json_bytes(unsigned),
        hashlib.sha256,
    ).hexdigest()
    assert payload == {**unsigned, "attestation_hmac_sha256": expected_hmac}
    assert key not in receipt.path.read_bytes()
    assert receipt.sha256 == hashlib.sha256(_json_bytes(payload)).hexdigest()
    assert receipt.path.name == f"runtime-attestation-{receipt.sha256}.json"
    assert (
        write_runtime_attestation(
            attestation,
            config.paths.attestation_dir,
            authentication_key=key,
            expected_uid=os.geteuid(),
            expected_gid=os.getegid(),
        )
        == receipt
    )
    with pytest.raises(RuntimeAttestationError, match="write_input_invalid"):
        write_runtime_attestation(
            attestation,
            config.paths.attestation_dir,
            authentication_key=b"short",
            expected_uid=os.geteuid(),
            expected_gid=os.getegid(),
        )
    assert any("exec" in call[0] for call in runner.calls)


def test_runtime_attestation_rejects_fake_internal_health_when_host_relay_is_unreachable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, proc_root = _config(tmp_path, deployment_dir=DEPLOYMENT)
    config_file = tmp_path / "lane-config.json"
    config_file.write_text("fixture")
    containers, network = _runtime_inventory(config, config_file, proc_root)
    runner = _RuntimeRunner(config, containers, network)
    docker = DockerCli(config, config_file=config_file, runner=runner)
    cached = docker.inspect_cached_images()
    before = attest_account_i_fence(config.account_i_r16_fence, proc_root=proc_root)
    deployment_before = _deployment_evidence(config, config_file)
    _stub_runtime_dependencies(monkeypatch, config, deployment_before)

    def unreachable(**_kwargs: object) -> str:
        raise runtime_integrity.RuntimeIntegrityError("publishable_attestation_relay_unreachable")

    monkeypatch.setattr(runtime_attestation, "_attest_relay_reachability", unreachable)
    with pytest.raises(RuntimeAttestationError, match="relay_unreachable"):
        attest_runtime_lane(
            config=config,
            docker=docker,
            cached_images=cached,
            account_i_before=before,
            deployment_before=deployment_before,
            secret_cross_wire_sha256="f" * 64,
            fleet_mode="reopen",
            proc_root=proc_root,
        )
    assert any(call[0][3] == "exec" for call in runner.calls)


@pytest.mark.parametrize(
    "difference",
    [
        "image",
        "netns",
        "mount",
        "user",
        "port",
        "authority_environment",
        "source_authority_environment",
    ],
)
def test_runtime_attestation_rejects_each_runtime_difference(
    tmp_path: Path,
    difference: str,
    monkeypatch: pytest.MonkeyPatch,
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
    elif difference == "authority_environment":
        adapter["Config"]["Env"].remove("MEM0_V5_RUNTIME_AUTHORITY_DIR=/opt/publishable/runtime")
        adapter["Config"]["Env"].append("MEM0_V5_RUNTIME_AUTHORITY_DIR=/host/runtime")
    elif difference == "source_authority_environment":
        adapter["Config"]["Env"].remove(
            "MEM0_V5_SOURCE_AUTHORITY_MANIFEST_FILE=/run/source-authority-pin/manifest.json"
        )
        adapter["Config"]["Env"].append(
            "MEM0_V5_SOURCE_AUTHORITY_MANIFEST_FILE=/run/source-authority/manifest.json"
        )
    else:
        adapter["HostConfig"]["PortBindings"] = {
            "19091/tcp": [{"HostIp": "0.0.0.0", "HostPort": "19091"}]
        }
    runner = _RuntimeRunner(config, containers, network)
    docker = DockerCli(config, config_file=config_file, runner=runner)
    cached = docker.inspect_cached_images()
    before = attest_account_i_fence(config.account_i_r16_fence, proc_root=proc_root)
    deployment_before = _deployment_evidence(config, config_file)
    _stub_runtime_dependencies(monkeypatch, config, deployment_before)
    with pytest.raises(RuntimeAttestationError):
        attest_runtime_lane(
            config=config,
            docker=docker,
            cached_images=cached,
            account_i_before=before,
            deployment_before=deployment_before,
            secret_cross_wire_sha256="f" * 64,
            fleet_mode="reopen",
            proc_root=proc_root,
        )


def test_runtime_integrity_aggregates_three_isolated_controller_contracts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, _ = _config(tmp_path)
    anchor_netns = runtime_attestation.NamespaceIdentity(device=1, inode=100)
    bridge_pidns = tuple(
        runtime_attestation.NamespaceIdentity(device=1, inode=200 + index) for index in range(3)
    )
    keys: dict[str, bytes] = {}
    active: dict[str, dict[str, object]] = {}
    readiness: dict[str, dict[str, object]] = {}
    controls: dict[str, dict[str, object]] = {}
    for index, (account, port, pidns) in enumerate(
        zip(config.bridges, (8891, 8892, 8893), bridge_pidns, strict=True)
    ):
        authority = BridgeAuthority(
            bridge_id=account.bridge_id,
            origin=f"http://127.0.0.1:{port}",
            account_binding_hmac_sha256=account.account_binding_hmac_sha256,
            public_model="gpt-5.6-sol",
            base_instructions_sha256=BASE_INSTRUCTIONS_SHA256,
        )
        key = f"launcher-key-{index}-".encode() * 4
        keys[account.account_name] = key
        pending = PendingLaunchMetadata.issue(
            account_name=account.account_name,
            bridge_id=account.bridge_id,
            generation=1,
            launch_id=f"{index + 1:x}" * 64,
            mode="reopen",
            process=ProcessIdentity(
                pid=42,
                start_ticks=1000 + index,
                pgid=42,
                boot_id="11111111-1111-4111-8111-111111111111",
            ),
            runtime_authority_sha256=f"{index + 4:x}" * 64,
            started_at_unix_ms=1000,
            key=key,
        )
        receipt = BridgeLaunchReceipt.issue(
            pending=pending,
            health=RuntimeHealthEvidence(
                response_body_sha256=f"{index + 7:x}" * 64,
                observed_at_unix_ms=1001,
            ),
            bridge_authority_sha256=authority.commitment_sha256,
            runtime_authority_sha256=pending.runtime_authority_sha256,
            ready_at_unix_ms=1002,
            key=key,
        )
        public_readiness = receipt.public_payload()
        account_name = account.account_name
        active[account_name] = pending.public_payload()
        readiness[account_name] = public_readiness
        namespace_sha256 = hashlib.sha256(
            (
                f"net:{anchor_netns.device}:{anchor_netns.inode};pid:{pidns.device}:{pidns.inode}"
            ).encode()
        ).hexdigest()
        controls[account_name] = {
            "schema_version": "publishable-mem0-v5-bridge-controller-readiness.v2",
            "project_name": config.project_name,
            "controller_pid": 10 + index,
            "account_index": index,
            "account_name": account_name,
            "bridge_id": account.bridge_id,
            "bridge_port": port,
            "anchor_namespace_sha256": namespace_sha256,
            "bridge_readiness": public_readiness,
            "bridge_readiness_sha256": hashlib.sha256(
                json.dumps(public_readiness, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
        }

    def account_for(path: Path) -> str:
        return next(
            account.account_name for account in config.bridges if account.account_name in path.parts
        )

    def read_json(path: Path, **_kwargs: object) -> dict[str, object]:
        account_name = account_for(path)
        if path.name == "active.json":
            return active[account_name]
        if path.name == "readiness.json":
            return readiness[account_name]
        if path.name == "runtime-authority.json":
            return {}
        if path.name == ".controller-readiness.json":
            return controls[account_name]
        raise AssertionError(path)

    monkeypatch.setattr(runtime_integrity, "_require_private_directory", lambda *_args: None)
    monkeypatch.setattr(
        runtime_integrity,
        "_read_private_bytes",
        lambda path, **_kwargs: keys[account_for(path)],
    )
    monkeypatch.setattr(runtime_integrity, "_read_private_json", read_json)
    monkeypatch.setattr(
        runtime_integrity, "_attest_runtime_authority", lambda *_args, **_kwargs: None
    )

    evidence = runtime_integrity.attest_fleet_readiness(
        config,
        fleet_mode="reopen",
        anchor_netns=anchor_netns,
        bridge_pidns=bridge_pidns,  # type: ignore[arg-type]
        expected_uid=os.geteuid(),
        expected_gid=os.getegid(),
    )
    assert [item.controller_pid for item in evidence.bridges] == [10, 11, 12]
    assert [item.process["pid"] for item in evidence.bridges] == [42, 42, 42]

    controls[config.bridges[1].account_name]["account_name"] = config.bridges[0].account_name
    with pytest.raises(runtime_integrity.RuntimeIntegrityError, match="control_mismatch"):
        runtime_integrity.attest_fleet_readiness(
            config,
            fleet_mode="reopen",
            anchor_netns=anchor_netns,
            bridge_pidns=bridge_pidns,  # type: ignore[arg-type]
            expected_uid=os.geteuid(),
            expected_gid=os.getegid(),
        )

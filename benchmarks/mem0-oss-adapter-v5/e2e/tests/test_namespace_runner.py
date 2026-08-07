from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import e2e.namespace_runner as runner
from e2e.namespace_attestation import (
    SHA_KEYS,
    ProcessNamespaceAttestor,
    attest_service_process,
    attest_tmpfs,
    build_mount_policy,
    validate_public_result,
)

PROJECT = "mem0-v5-e2e-deadbeef-r1"
ANCHOR_ID = "a" * 64
IMAGE_ID = "sha256:" + "b" * 64


class FakeInspector:
    def __init__(self, compose: Path) -> None:
        self.containers = {service: _container(service, compose) for service in runner.SERVICES}
        self.ids = {service: (self.containers[service]["Id"][:12],) for service in runner.SERVICES}
        policy = build_mount_policy(_environment())
        for service, mounts in policy.items():
            self.containers[service]["Mounts"] = [
                {
                    "Type": "bind",
                    "Source": source,
                    "Destination": target,
                    "RW": writable,
                }
                for target, (source, writable) in mounts.items()
            ]
        self.info = {
            "DockerRootDir": str(runner.PINNED_DOCKER_DATA_ROOT),
            "SecurityOptions": ["name=rootless"],
        }
        self.network = _network()

    def daemon_info(self):
        return self.info

    def service_ids(self, _project: str, service: str):
        return self.ids[service]

    def inspect_container(self, container_id: str):
        for service, ids in self.ids.items():
            if container_id in ids:
                return self.containers[service]
        raise AssertionError(container_id)

    def inspect_network(self, _name: str):
        return self.network


def _container(service: str, compose: Path) -> dict:
    is_anchor = service == runner.ANCHOR_SERVICE
    is_qdrant = service == "mem0-oss-v5-qdrant"
    exact_id = {
        runner.ANCHOR_SERVICE: ANCHOR_ID,
        "mem0-oss-v5-fake-runtime": "f" * 64,
        "mem0-oss-v5-qdrant": "q" * 64,
        "mem0-oss-adapter-v5": "d" * 64,
    }[service]
    config_image = runner.QDRANT_IMAGE if is_qdrant else f"{PROJECT}-{service}"
    labels = {
        "com.docker.compose.project": PROJECT,
        "com.docker.compose.service": service,
        "com.docker.compose.container-number": "1",
        "com.docker.compose.project.config_files": str(compose),
        "com.docker.compose.image": IMAGE_ID,
        "com.docker.compose.config-hash": "c" * 64,
    }
    tmpfs = {
        "/tmp": "size=8388608,mode=1770,uid=65532,gid=65532",
    }
    if service == "mem0-oss-v5-fake-runtime":
        tmpfs["/tmp"] = "size=16777216,mode=1770,uid=65532,gid=65532"
    elif is_qdrant:
        tmpfs = {
            "/qdrant/storage": "size=1073741824,mode=0700,uid=65532,gid=65532",
            "/tmp": "size=33554432,mode=1770,uid=65532,gid=65532",
        }
    elif not is_anchor:
        tmpfs["/tmp"] = "size=67108864,mode=1770,uid=65532,gid=65532"
    return {
        "Id": exact_id,
        "Image": IMAGE_ID,
        "Config": {
            "Labels": labels,
            "Image": config_image,
            "User": "65532:65532",
            "Cmd": _command(service),
            "Entrypoint": None,
            "ExposedPorts": _exposed(service),
            "Env": _environment_for(service),
            "Healthcheck": _healthcheck(service),
        },
        "State": {
            "Status": "running",
            "Running": True,
            "Pid": 1234,
            "StartedAt": "2026-08-07T00:00:00Z",
        },
        "HostConfig": {
            "Privileged": False,
            "ReadonlyRootfs": True,
            "CapAdd": None,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges:true"],
            "Binds": None,
            "PortBindings": None,
            "NetworkMode": (
                f"{PROJECT}_{runner.NETWORK_KEY}" if is_anchor else f"container:{ANCHOR_ID}"
            ),
            "Tmpfs": tmpfs,
        },
        "NetworkSettings": {
            "Ports": {},
            "Networks": ({f"{PROJECT}_{runner.NETWORK_KEY}": {}} if is_anchor else {}),
        },
        "Mounts": [],
    }


def _network() -> dict:
    return {
        "Name": f"{PROJECT}_{runner.NETWORK_KEY}",
        "Driver": "bridge",
        "Scope": "local",
        "Internal": True,
        "Attachable": False,
        "Ingress": False,
        "ConfigOnly": False,
        "Options": {},
        "Labels": {
            "com.docker.compose.project": PROJECT,
            "com.docker.compose.network": runner.NETWORK_KEY,
        },
        "IPAM": {
            "Driver": "default",
            "Options": None,
            "Config": [{"Subnet": "10.10.0.0/24", "Gateway": "10.10.0.1"}],
        },
        "Containers": {ANCHOR_ID: {"Name": f"{PROJECT}-{runner.ANCHOR_SERVICE}-1"}},
    }


def _command(service: str):
    if service == runner.ANCHOR_SERVICE:
        return ["python", "-m", "e2e.anchor"]
    if service == "mem0-oss-v5-fake-runtime":
        return [
            "python",
            "-m",
            "e2e.fake_runtime",
            "--runtime-repo",
            "/mnt/volume_ams3_1784742570542/infinity-context/runtimes/subscription-runtime/e904ec95/repo",
            "--node",
            "/usr/local/bin/node",
            "--counter",
            "/run/fake-runtime/counter.json",
        ]
    if service == "mem0-oss-adapter-v5":
        return [
            "uvicorn",
            "mem0_oss_adapter_v5.composition:build_app_from_environment",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            "19091",
            "--no-access-log",
            "--no-proxy-headers",
        ]
    if service == "mem0-oss-v5-qdrant":
        return ["./entrypoint.sh"]
    return None


def _exposed(service: str):
    keys = {
        "mem0-oss-v5-qdrant": ("6333/tcp", "6334/tcp"),
        "mem0-oss-adapter-v5": ("19091/tcp",),
    }.get(service, ())
    return {key: {} for key in keys} or None


def _environment_for(service: str) -> list[str]:
    python_base = {
        "PATH": "/usr/local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "LANG": "C.UTF-8",
        "GPG_KEY": "A035C8C19219BA821ECEA86B64E628F8D684696D",
        "PYTHON_VERSION": "3.11.15",
        "PYTHON_SHA256": "272179ddd9a2e41a0fc8e42e33dfbdca0b3711aa5abf372d3f2d51543d09b625",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
    }
    values = {
        runner.ANCHOR_SERVICE: python_base,
        "mem0-oss-v5-fake-runtime": {
            **python_base,
            "MEM0_V5_E2E_SECRET_DIR": "/run/fake-runtime-secrets",
        },
        "mem0-oss-v5-qdrant": {
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "DIR": "",
            "TZ": "Etc/UTC",
            "RUN_MODE": "production",
            "QDRANT__SERVICE__HOST": "127.0.0.1",
            "QDRANT__SERVICE__HTTP_PORT": "6334",
            "QDRANT__STORAGE__STORAGE_PATH": "/qdrant/storage",
            "QDRANT__STORAGE__SNAPSHOTS_PATH": "/qdrant/storage/snapshots",
            "QDRANT__TELEMETRY_DISABLED": "true",
        },
        "mem0-oss-adapter-v5": {
            **python_base,
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_NO_CACHE_DIR": "1",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "MEM0_TELEMETRY": "false",
            "MEM0_TELEMETRY_SAMPLE_RATE": "0",
            "MEM0_OSS_FASTEMBED_MODEL_DIR": "/opt/models/bge-small-en-v1.5",
            "MEM0_V5_INPUT_MANIFEST_FILE": "/run/mem0-v5-input/manifest.json",
            "MEM0_V5_STATE_DB_FILE": "/run/mem0-v5-state/operations.sqlite3",
            "MEM0_V5_INGRESS_BEARER_FILE": "/run/secrets/ingress-bearer",
            "MEM0_V5_STATE_HMAC_FILE": "/run/secrets/state-hmac",
            "MEM0_V5_RUNTIME_BEARER_FILE": "/run/secrets/runtime-bearer",
            "MEM0_V5_RECEIPT_SECRET_FILE": "/run/secrets/runtime-receipt-secret",
            "MEM0_V5_RUNTIME_TRANSPORT_ORIGIN_FILE": "/run/secrets/runtime-transport-origin",
            "MEM0_V5_ACCOUNT_BINDING_HMAC_FILE": "/run/secrets/account-binding-hmac-sha256",
            "MEM0_V5_BASE_INSTRUCTIONS_SHA256_FILE": "/run/secrets/base-instructions-sha256",
            "MEM0_V5_QDRANT_ORIGIN": "http://127.0.0.1:6334",
            "MEM0_V5_RUNTIME_REPO": (
                "/mnt/volume_ams3_1784742570542/infinity-context/"
                "runtimes/subscription-runtime/e904ec95/repo"
            ),
            "MEM0_V5_NODE_EXECUTABLE": "/usr/local/bin/node",
            "MEM0_V5_SOURCE_AUTHORITY_MANIFEST_FILE": "/run/source-authority/manifest.json",
            "MEM0_V5_SOURCE_AUTHORITY_MANIFEST_SHA256_FILE": (
                "/run/source-authority-pin/manifest.sha256"
            ),
            "MEM0_V5_PHASE_C_AUTHORITY_DIR": (
                "/mnt/volume_ams3_1784742570542/infinity-context/sources/9499b9c2"
            ),
            "HOME": "/run/mem0-v5-state",
            "XDG_CACHE_HOME": "/run/mem0-v5-state/cache",
            "XDG_CONFIG_HOME": "/run/mem0-v5-state/config",
            "XDG_DATA_HOME": "/run/mem0-v5-state/data",
            "XDG_STATE_HOME": "/run/mem0-v5-state/state",
        },
    }[service]
    return [f"{key}={value}" for key, value in values.items()]


def _healthcheck(service: str):
    if service != runner.ANCHOR_SERVICE:
        return None
    return {
        "Test": ["CMD", "python", "-m", "e2e.readiness", "--once"],
        "Interval": 1_000_000_000,
        "Timeout": 2_000_000_000,
        "Retries": 60,
        "StartPeriod": 1_000_000_000,
    }


@pytest.fixture
def compose(tmp_path: Path) -> Path:
    path = tmp_path / "compose.yaml"
    path.write_text("services: {}\n")
    return path


def _locator(compose: Path) -> tuple[runner.PinnedDockerAnchorLocator, FakeInspector]:
    inspector = FakeInspector(compose)
    return runner.PinnedDockerAnchorLocator(
        inspector,
        build_mount_policy(_environment()),
        attest_service_process,
        attest_tmpfs,
    ), inspector


def test_locator_accepts_exact_four_service_stack(compose: Path) -> None:
    locator, _inspector = _locator(compose)
    identity = locator.locate(project_name=PROJECT, compose_file=compose)
    assert identity.anchor.container_id == ANCHOR_ID
    assert identity.anchor.pid == 1234


@pytest.mark.parametrize("ids", [(), ("one", "two")])
def test_locator_rejects_missing_or_duplicate_service(compose: Path, ids) -> None:
    locator, inspector = _locator(compose)
    inspector.ids[runner.ANCHOR_SERVICE] = ids
    with pytest.raises(runner.NamespaceRunnerError, match="e2e_service_cardinality_invalid"):
        locator.locate(project_name=PROJECT, compose_file=compose)


@pytest.mark.parametrize(
    ("mutate", "error"),
    [
        (
            lambda value: value["Config"]["Labels"].__setitem__(
                "com.docker.compose.container-number", "2"
            ),
            "e2e_service_labels_invalid",
        ),
        (
            lambda value: value["Config"]["Labels"].__setitem__(
                "com.docker.compose.config-hash", "not-a-sha256"
            ),
            "e2e_service_config_hash_invalid",
        ),
        (
            lambda value: value["State"].update(Status="exited", Running=False),
            "e2e_service_state_invalid",
        ),
        (
            lambda value: value["HostConfig"].update(Privileged=True),
            "e2e_service_hardening_invalid",
        ),
        (
            lambda value: value["HostConfig"].update(ReadonlyRootfs=False),
            "e2e_service_hardening_invalid",
        ),
        (
            lambda value: value["HostConfig"].update(CapDrop=[]),
            "e2e_service_hardening_invalid",
        ),
        (
            lambda value: value["HostConfig"].update(SecurityOpt=[]),
            "e2e_service_hardening_invalid",
        ),
        (
            lambda value: value["HostConfig"].update(PortBindings={"80/tcp": [{}]}),
            "e2e_service_ports_invalid",
        ),
    ],
)
def test_locator_rejects_escaped_or_weakened_service(compose: Path, mutate, error: str) -> None:
    locator, inspector = _locator(compose)
    mutate(inspector.containers["mem0-oss-adapter-v5"])
    with pytest.raises(runner.NamespaceRunnerError, match=error):
        locator.locate(project_name=PROJECT, compose_file=compose)


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("Cmd", ["python", "-m", "e2e.gateway"], "e2e_anchor_command_invalid"),
        ("User", "0:0", "e2e_anchor_config_invalid"),
        ("ExposedPorts", {"80/tcp": {}}, "e2e_service_ports_invalid"),
    ],
)
def test_locator_rejects_nonpassive_anchor(compose: Path, field: str, value, error: str) -> None:
    locator, inspector = _locator(compose)
    inspector.containers[runner.ANCHOR_SERVICE]["Config"][field] = value
    with pytest.raises(runner.NamespaceRunnerError, match=error):
        locator.locate(project_name=PROJECT, compose_file=compose)


def test_locator_rejects_workload_outside_anchor_namespace(compose: Path) -> None:
    locator, inspector = _locator(compose)
    inspector.containers["mem0-oss-v5-fake-runtime"]["HostConfig"]["NetworkMode"] = "bridge"
    with pytest.raises(runner.NamespaceRunnerError, match="e2e_workload_network_invalid"):
        locator.locate(project_name=PROJECT, compose_file=compose)


def test_locator_rejects_unpinned_qdrant_and_unknown_mount(compose: Path) -> None:
    locator, inspector = _locator(compose)
    inspector.containers["mem0-oss-v5-qdrant"]["Config"]["Image"] = "qdrant:latest"
    with pytest.raises(runner.NamespaceRunnerError, match="e2e_qdrant_config_invalid"):
        locator.locate(project_name=PROJECT, compose_file=compose)
    inspector = FakeInspector(compose)
    inspector.containers["mem0-oss-adapter-v5"]["Mounts"][0]["Destination"] = "/host"
    with pytest.raises(runner.NamespaceRunnerError, match="e2e_workload_mounts_invalid"):
        runner.PinnedDockerAnchorLocator(
            inspector,
            build_mount_policy(_environment()),
            attest_service_process,
            attest_tmpfs,
        ).locate(project_name=PROJECT, compose_file=compose)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("Internal", False),
        ("Driver", "host"),
        ("Attachable", True),
        ("Ingress", True),
        ("Options", {"com.docker.network.bridge.enable_ip_masquerade": "true"}),
        ("Containers", {}),
    ],
)
def test_locator_rejects_wrong_network_contract(compose: Path, field: str, value) -> None:
    locator, inspector = _locator(compose)
    inspector.network[field] = value
    error = (
        "e2e_network_membership_invalid"
        if field == "Containers"
        else "e2e_internal_network_invalid"
    )
    with pytest.raises(runner.NamespaceRunnerError, match=error):
        locator.locate(project_name=PROJECT, compose_file=compose)


def test_locator_rejects_wrong_anchor_endpoint_name(compose: Path) -> None:
    locator, inspector = _locator(compose)
    inspector.network["Containers"][ANCHOR_ID]["Name"] = "other-container"
    with pytest.raises(runner.NamespaceRunnerError, match="e2e_network_membership_invalid"):
        locator.locate(project_name=PROJECT, compose_file=compose)


def test_locator_rejects_anchor_replacement(compose: Path) -> None:
    locator, inspector = _locator(compose)
    identity = locator.locate(project_name=PROJECT, compose_file=compose)
    inspector.containers[runner.ANCHOR_SERVICE]["State"]["StartedAt"] = "changed"
    with pytest.raises(runner.NamespaceRunnerError, match="e2e_anchor_identity_changed"):
        locator.reattest(identity, project_name=PROJECT, compose_file=compose)


@pytest.mark.parametrize(
    ("service", "field", "value"),
    [
        ("mem0-oss-v5-fake-runtime", "Cmd", ["python", "-m", "http.server"]),
        ("mem0-oss-v5-qdrant", "Entrypoint", ["/bin/sh"]),
        ("mem0-oss-adapter-v5", "Cmd", ["uvicorn", "attacker:app"]),
    ],
)
def test_locator_rejects_workload_process_drift(
    compose: Path, service: str, field: str, value
) -> None:
    locator, inspector = _locator(compose)
    inspector.containers[service]["Config"][field] = value
    with pytest.raises(runner.NamespaceRunnerError, match="e2e_service_process_invalid"):
        locator.locate(project_name=PROJECT, compose_file=compose)


@pytest.mark.parametrize(
    "injected",
    [
        "OPENAI_API_KEY=must-not-cross-boundary",
        "UNRELATED_BENIGN_FLAG=1",
        "PYTHONPATH=/attacker",
        "LD_PRELOAD=/attacker.so",
        "NODE_OPTIONS=--require=/attacker.js",
    ],
)
def test_locator_rejects_extra_service_environment(compose: Path, injected: str) -> None:
    locator, inspector = _locator(compose)
    inspector.containers["mem0-oss-adapter-v5"]["Config"]["Env"].append(injected)
    with pytest.raises(runner.NamespaceRunnerError, match="e2e_service_process_invalid"):
        locator.locate(project_name=PROJECT, compose_file=compose)


def test_locator_rejects_service_environment_value_mutation(compose: Path) -> None:
    locator, inspector = _locator(compose)
    environment = inspector.containers["mem0-oss-v5-qdrant"]["Config"]["Env"]
    environment[environment.index("RUN_MODE=production")] = "RUN_MODE=development"
    with pytest.raises(runner.NamespaceRunnerError, match="e2e_service_process_invalid"):
        locator.locate(project_name=PROJECT, compose_file=compose)


@pytest.mark.parametrize(
    ("service", "field", "value"),
    [
        ("mem0-oss-v5-fake-runtime", "Image", "sha256:" + "9" * 64),
        ("mem0-oss-v5-qdrant", "StartedAt", "changed"),
        ("mem0-oss-adapter-v5", "Id", "9" * 64),
    ],
)
def test_locator_rejects_workload_identity_replacement(
    compose: Path, service: str, field: str, value
) -> None:
    locator, inspector = _locator(compose)
    identity = locator.locate(project_name=PROJECT, compose_file=compose)
    target = inspector.containers[service]
    if field == "StartedAt":
        target["State"][field] = value
    else:
        target[field] = value
    if field == "Image":
        target["Config"]["Labels"]["com.docker.compose.image"] = value
    elif field == "Id":
        inspector.ids[service] = (value[:12],)
    with pytest.raises(runner.NamespaceRunnerError, match="e2e_anchor_identity_changed"):
        locator.reattest(identity, project_name=PROJECT, compose_file=compose)


def test_locator_allows_only_adapter_restart_timestamp_change(compose: Path) -> None:
    locator, inspector = _locator(compose)
    identity = locator.locate(project_name=PROJECT, compose_file=compose)
    inspector.containers["mem0-oss-adapter-v5"]["State"]["StartedAt"] = "changed"
    locator.reattest(identity, project_name=PROJECT, compose_file=compose)


def test_daemon_info_requires_rootless_exact_data_root(compose: Path) -> None:
    locator, inspector = _locator(compose)
    inspector.info["DockerRootDir"] = "/var/lib/docker"
    with pytest.raises(runner.NamespaceRunnerError, match="e2e_docker_daemon_invalid"):
        locator.attest_daemon()
    inspector.info["DockerRootDir"] = str(runner.PINNED_DOCKER_DATA_ROOT)
    inspector.info["SecurityOptions"] = []
    with pytest.raises(runner.NamespaceRunnerError, match="e2e_docker_daemon_invalid"):
        locator.attest_daemon()


def _arguments(tmp_path: Path, compose: Path) -> runner.E2ERunArguments:
    run_root = tmp_path / "run"
    authority = tmp_path / "authority"
    run_root.mkdir(exist_ok=True)
    authority.mkdir(exist_ok=True)
    node = tmp_path / "node"
    python = tmp_path / "python"
    node.write_text("")
    python.write_text("")
    python.chmod(0o700)
    return runner.E2ERunArguments(
        run_root=run_root,
        runtime_authority_mirror=authority,
        node=node,
        compose_file=compose,
        project_name=PROJECT,
        host_python=python,
    )


def _environment() -> dict[str, str]:
    return {name: f"/absolute/{name.lower()}" for name in runner.COMPOSE_PATH_ENVIRONMENT}


def _correlated_environment(arguments: runner.E2ERunArguments) -> dict[str, str]:
    pin = "/mnt/volume_ams3_1784742570542/infinity-locomo-benchmark/e2e-source-authorities/deadbeef"
    return {
        "MEM0_V5_INPUT_DIR": str(arguments.run_root / "input"),
        "MEM0_V5_STATE_DIR": str(arguments.run_root / "state"),
        "MEM0_V5_SECRET_DIR": str(arguments.run_root / "secrets"),
        "MEM0_V5_FAKE_RUNTIME_STATE_DIR": str(arguments.run_root / "fake-runtime"),
        "MEM0_V5_RUNTIME_AUTHORITY_DIR": str(runner.PINNED_RUNTIME_MIRROR),
        "MEM0_V5_SOURCE_AUTHORITY_DIR": str(runner.PINNED_PHASE_C),
        "MEM0_V5_SOURCE_AUTHORITY_PIN_DIR": pin,
        "MEM0_V5_SOURCE_AUTHORITY_PIN_SHA256_FILE": f"{pin}/manifest.sha256",
        "MEM0_V5_NODE_EXECUTABLE_SOURCE": str(runner.PINNED_NODE),
    }


def test_child_environment_is_exact_allowlist_and_rejects_values(monkeypatch) -> None:
    arguments = runner.E2ERunArguments(
        run_root=runner.PINNED_RUN_PARENT / PROJECT,
        runtime_authority_mirror=runner.PINNED_RUNTIME_MIRROR,
        node=runner.PINNED_NODE,
        compose_file=runner.PINNED_BENCHMARK_ROOT / "compose.provider-free-e2e.yaml",
        project_name=PROJECT,
        host_python=runner.PINNED_HOST_PYTHON,
    )
    source = {
        **_correlated_environment(arguments),
        "DOCKER_HOST": runner.PINNED_DOCKER_HOST,
        "PYTHONPATH": "/attacker",
        "LD_PRELOAD": "/attacker.so",
        "RUNTIME_BEARER": "secret",
    }
    value = runner._child_environment(source, arguments)
    assert set(value) == {
        *runner.COMPOSE_PATH_ENVIRONMENT,
        "DOCKER_HOST",
        "PATH",
        "LANG",
        "PYTHONDONTWRITEBYTECODE",
    }
    assert "PYTHONPATH" not in value and "LD_PRELOAD" not in value
    source[runner.COMPOSE_PATH_ENVIRONMENT[0]] = "secret-not-a-path"
    with pytest.raises(runner.NamespaceRunnerError, match="e2e_child_environment_invalid"):
        runner._child_environment(source, arguments)


def _result() -> dict:
    return {
        "verdict": "PASS",
        "fake_provider_calls": 1,
        **{key: "a" * 64 for key in SHA_KEYS},
    }


def test_public_result_requires_one_exact_canonical_pass_object() -> None:
    value = _result()
    encoded = (json.dumps(value, sort_keys=True) + "\n").encode()
    assert validate_public_result(encoded, runner.NamespaceRunnerError) == value
    invalid = [
        encoded + b"extra",
        json.dumps(value).encode(),
        (json.dumps({**value, "verdict": "FAIL"}, sort_keys=True) + "\n").encode(),
        (json.dumps({**value, "extra": 1}, sort_keys=True) + "\n").encode(),
        (json.dumps({**value, "fake_provider_calls": 0}, sort_keys=True) + "\n").encode(),
    ]
    for raw in invalid:
        with pytest.raises(runner.NamespaceRunnerError):
            validate_public_result(raw, runner.NamespaceRunnerError)


class FakeProcess:
    def __init__(self, stdout: bytes, stderr: bytes = b"private stderr") -> None:
        stdout_read, stdout_write = os.pipe()
        stderr_read, stderr_write = os.pipe()
        os.write(stdout_write, stdout)
        os.write(stderr_write, stderr)
        os.close(stdout_write)
        os.close(stderr_write)
        self.stdout = os.fdopen(stdout_read, "rb", buffering=0)
        self.stderr = os.fdopen(stderr_read, "rb", buffering=0)
        self.returncode = 0
        self.pid = 99999999

    def wait(self, timeout=None):
        return self.returncode


def test_executor_uses_only_netns_setpriv_and_sanitized_environment(
    tmp_path: Path, compose: Path, monkeypatch
) -> None:
    captured = {}

    def popen(command, **kwargs):
        captured.update(command=command, kwargs=kwargs)
        return FakeProcess((json.dumps(_result(), sort_keys=True) + "\n").encode())

    monkeypatch.setattr(subprocess, "Popen", popen)
    arguments = _arguments(tmp_path, compose)
    environment = {"PATH": "/usr/bin:/bin"}
    result = runner.PinnedNetnsExecutor(validate_public_result).execute(
        41, 42, arguments, environment
    )
    command = captured["command"]
    assert command[:3] == [str(runner.PINNED_NSENTER), "--net=/proc/self/fd/41", "--"]
    assert command[3:5] == [str(runner.PINNED_SETPRIV), "--reuid=296603"]
    assert "--regid=296603" in command
    assert "--clear-groups" in command
    assert not any(item.startswith("--groups=") for item in command)
    assert "--bounding-set=-all" in command
    assert "--ambient-caps=-all" in command
    assert "--inh-caps=-all" in command
    assert "--no-new-privs" in command
    assert not any(
        item.startswith(("--mount", "--pid", "--user", "--uts", "--ipc")) for item in command
    )
    assert captured["kwargs"]["pass_fds"] == (41, 42)
    assert captured["kwargs"]["env"] == environment
    assert result == _result()


def _isolated_child(source: str) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [str(runner.PINNED_ROOT_PYTHON), "-I", "-S", "-c", source],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )


def test_bounded_communicator_kills_output_overflow() -> None:
    process = _isolated_child("import os; os.write(1, b'x' * 20000)")
    with pytest.raises(runner.NamespaceRunnerError, match="e2e_namespace_output_invalid"):
        runner._bounded_communicate(process)
    assert process.poll() is not None


def test_bounded_communicator_kills_timeout(monkeypatch) -> None:
    monkeypatch.setattr(runner, "_CHILD_TIMEOUT_SECONDS", 0.0)
    process = _isolated_child("import time; time.sleep(30)")
    with pytest.raises(runner.NamespaceRunnerError, match="e2e_namespace_run_timeout"):
        runner._bounded_communicate(process)
    assert process.poll() is not None


def test_bounded_communicator_kills_unexpected_reader_failure(monkeypatch) -> None:
    process = _isolated_child("import os, time; os.write(1, b'x'); time.sleep(30)")
    monkeypatch.setattr(runner.os, "read", lambda *_args: (_ for _ in ()).throw(OSError()))
    with pytest.raises(runner.NamespaceRunnerError, match="e2e_namespace_reader_failed"):
        runner._bounded_communicate(process)
    assert process.poll() is not None


def _proc_fixture(tmp_path: Path) -> tuple[Path, int, int]:
    process = tmp_path / "1234"
    (process / "ns").mkdir(parents=True)
    (process / "ns" / "net").write_text("namespace")
    fields = ["S", *[str(index) for index in range(1, 20)]]
    fields[19] = "777"
    (process / "stat").write_text(f"1234 (anchor) {' '.join(fields)}\n")
    (process / "cgroup").write_text(f"0::/docker/{ANCHOR_ID}\n")
    pidfd_read, pidfd_write = os.pipe()
    return tmp_path, pidfd_read, pidfd_write


def test_process_attestor_binds_pidfd_starttime_cgroup_and_netns(
    tmp_path: Path,
) -> None:
    proc_root, pidfd, pidfd_write = _proc_fixture(tmp_path)
    attestor = ProcessNamespaceAttestor(
        error_type=runner.NamespaceRunnerError,
        proc_root=proc_root,
        pidfd_opener=lambda _pid, _flags: pidfd,
    )
    anchor = runner.AnchorIdentity(ANCHOR_ID, IMAGE_ID, 1234, "start", "network")
    held_pidfd, netfd, identity = attestor.open(anchor)
    assert held_pidfd == pidfd and identity[1] == "777"
    attestor.reattest(pidfd, netfd, identity, ANCHOR_ID)
    os.write(pidfd_write, b"x")
    with pytest.raises(runner.NamespaceRunnerError, match="e2e_anchor_process_exited"):
        attestor.reattest(pidfd, netfd, identity, ANCHOR_ID)
    os.close(pidfd_write)
    os.close(netfd)
    os.close(pidfd)


def test_process_attestor_rejects_starttime_and_netns_drift(tmp_path: Path) -> None:
    proc_root, pidfd, pidfd_write = _proc_fixture(tmp_path)
    attestor = ProcessNamespaceAttestor(
        error_type=runner.NamespaceRunnerError,
        proc_root=proc_root,
        pidfd_opener=lambda _pid, _flags: pidfd,
    )
    anchor = runner.AnchorIdentity(ANCHOR_ID, IMAGE_ID, 1234, "start", "network")
    _, netfd, identity = attestor.open(anchor)
    stat_file = proc_root / "1234" / "stat"
    stat_file.write_text(stat_file.read_text().replace("777", "778"))
    with pytest.raises(runner.NamespaceRunnerError, match="e2e_anchor_process_changed"):
        attestor.reattest(pidfd, netfd, identity, ANCHOR_ID)
    os.close(pidfd_write)
    os.close(netfd)
    os.close(pidfd)


def test_socket_and_root_binary_validation(monkeypatch) -> None:
    parent = SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_uid=994, st_gid=985)
    socket_value = SimpleNamespace(st_mode=stat.S_IFSOCK | 0o660, st_uid=994, st_gid=232058)
    monkeypatch.setattr(
        os,
        "lstat",
        lambda path: parent if Path(path) == runner.PINNED_DOCKER_SOCKET.parent else socket_value,
    )
    runner._validate_socket()
    socket_value.st_mode = stat.S_IFSOCK | 0o666
    with pytest.raises(runner.NamespaceRunnerError, match="e2e_docker_socket_invalid"):
        runner._validate_socket()


def test_trust_path_chain_rejects_symlink_or_writable_parent(monkeypatch) -> None:
    safe = SimpleNamespace(st_mode=stat.S_IFDIR | 0o755, st_uid=0, st_gid=0)
    monkeypatch.setattr(os, "lstat", lambda _path: safe)
    runner._validate_path_chain(Path("/safe/root"))
    unsafe = SimpleNamespace(st_mode=stat.S_IFDIR | 0o775, st_uid=0, st_gid=0)
    monkeypatch.setattr(
        os,
        "lstat",
        lambda path: unsafe if Path(path) == Path("/safe") else safe,
    )
    with pytest.raises(runner.NamespaceRunnerError, match="e2e_docker_path_invalid"):
        runner._validate_path_chain(Path("/safe/root"))


def test_run_arguments_reject_symlinked_compose_path(tmp_path: Path, compose: Path) -> None:
    link = tmp_path / "compose-link.yaml"
    link.symlink_to(compose)
    arguments = _arguments(tmp_path, compose)
    symlinked = runner.E2ERunArguments(
        run_root=arguments.run_root,
        runtime_authority_mirror=arguments.runtime_authority_mirror,
        node=arguments.node,
        compose_file=link,
        project_name=arguments.project_name,
        host_python=arguments.host_python,
    )
    with pytest.raises(runner.NamespaceRunnerError, match="e2e_compose_path_invalid"):
        symlinked.validate()


def test_daemon_process_requires_exact_owner_maps_and_command(tmp_path: Path, monkeypatch) -> None:
    pidfile = tmp_path / "dockerd.pid"
    pidfile.write_text("42\n")
    process = tmp_path / "proc" / "42"
    process.mkdir(parents=True)
    command = [
        b"dockerd",
        f"--host={runner.PINNED_DOCKER_HOST}".encode(),
        f"--data-root={runner.PINNED_DOCKER_DATA_ROOT}".encode(),
        f"--exec-root={runner.PINNED_DOCKER_EXEC_ROOT}".encode(),
        f"--pidfile={runner.PINNED_DOCKER_PIDFILE}".encode(),
    ]
    (process / "cmdline").write_bytes(b"\0".join(command) + b"\0")
    (process / "uid_map").write_text("0 994 1\n1 231072 65536\n")
    (process / "gid_map").write_text("0 985 1\n1 231072 65536\n")
    real_lstat = os.lstat
    real_stat = os.stat

    def lstat(path):
        value = real_lstat(path)
        if Path(path) == pidfile:
            return SimpleNamespace(st_mode=value.st_mode, st_uid=994, st_gid=985)
        return value

    def stat_path(path):
        value = real_stat(path)
        if Path(path) == process:
            return SimpleNamespace(st_mode=value.st_mode, st_uid=994, st_gid=985)
        return value

    monkeypatch.setattr(os, "lstat", lstat)
    monkeypatch.setattr(os, "stat", stat_path)
    runner._validate_daemon_process(pidfile=pidfile, proc_root=tmp_path / "proc")
    (process / "uid_map").write_text("0 0 1\n")
    with pytest.raises(runner.NamespaceRunnerError, match="e2e_docker_process_invalid"):
        runner._validate_daemon_process(pidfile=pidfile, proc_root=tmp_path / "proc")


def test_top_level_rejects_nonroot_and_wrong_socket_before_host_access(
    tmp_path: Path, compose: Path, monkeypatch
) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    with pytest.raises(runner.NamespaceRunnerError, match="e2e_runner_requires_root"):
        runner.run(_arguments(tmp_path, compose))
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setenv("DOCKER_HOST", "unix:///var/run/docker.sock")
    with pytest.raises(runner.NamespaceRunnerError, match="e2e_docker_host_invalid"):
        runner.run(_arguments(tmp_path, compose))

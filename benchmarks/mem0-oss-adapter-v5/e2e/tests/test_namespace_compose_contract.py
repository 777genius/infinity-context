from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "compose.provider-free-e2e.yaml"


def test_compose_has_no_published_or_exposed_ports() -> None:
    document = yaml.safe_load(COMPOSE.read_text())
    services = document["services"]
    for service in services.values():
        assert "ports" not in service
        assert "expose" not in service


def test_all_workloads_share_only_the_passive_anchor_network_namespace() -> None:
    document = yaml.safe_load(COMPOSE.read_text())
    services = document["services"]
    assert document["networks"] == {"provider-free-internal": {"internal": True}}
    assert services["e2e-network-anchor"]["networks"] == ["provider-free-internal"]
    for name in (
        "mem0-oss-v5-fake-runtime",
        "mem0-oss-v5-qdrant",
        "mem0-oss-adapter-v5",
    ):
        assert services[name]["network_mode"] == "service:e2e-network-anchor"
        assert "networks" not in services[name]


def test_anchor_is_passive_and_has_no_network_listener_code() -> None:
    source = (ROOT / "e2e" / "anchor.py").read_text()
    tree = ast.parse(source)
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert "socket" not in imports
    assert ".bind(" not in source
    assert ".listen(" not in source
    assert "create_connection" not in source
    dockerfile = (ROOT / "e2e" / "Dockerfile").read_text()
    assert 'CMD ["python", "-m", "e2e.anchor"]' in dockerfile
    assert "e2e.gateway" not in dockerfile


def test_privileged_wrapper_is_stdlib_only_direct_script_safe() -> None:
    completed = subprocess.run(
        [
            "/usr/bin/python3.12",
            "-I",
            "-S",
            str(ROOT / "e2e" / "namespace_runner.py"),
            "--help",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    readme = (ROOT / "e2e" / "README.md").read_text()
    assert '/usr/bin/python3.12 -I -S "$PWD/e2e/namespace_runner.py"' in readme


def test_readme_hosting_flow_matches_exact_runner_path_correlation() -> None:
    readme = (ROOT / "e2e" / "README.md").read_text()
    expected = (
        'export SOURCE_PIN_HEX="ccd75535"',
        'export RUN_SEQUENCE="r7"',
        'export PROJECT_NAME="mem0-v5-e2e-${SOURCE_PIN_HEX}-${RUN_SEQUENCE}"',
        'export RUN_ROOT="$RUN_PARENT/$PROJECT_NAME"',
        'export MEM0_V5_RUNTIME_AUTHORITY_DIR="/mnt/volume_ams3_1784742570542/'
        "infinity-locomo-benchmark/e2e-runtime-authorities/"
        'e904ec95-uid65532-host296603"',
        'export MEM0_V5_SOURCE_AUTHORITY_DIR="/mnt/volume_ams3_1784742570542/'
        'infinity-context/sources/9499b9c2"',
        'export MEM0_V5_SOURCE_AUTHORITY_PIN_DIR="/mnt/volume_ams3_1784742570542/'
        'infinity-locomo-benchmark/e2e-source-authorities/$SOURCE_PIN_HEX"',
        'export MEM0_V5_NODE_EXECUTABLE_SOURCE="/usr/local/bin/node"',
    )
    assert all(line in readme for line in expected)
    assert "/absolute/path" not in readme
    assert "$(date +%s)" not in readme

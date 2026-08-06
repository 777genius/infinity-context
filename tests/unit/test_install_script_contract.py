from __future__ import annotations

import os
import subprocess
import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
INSTALL_SCRIPT = PROJECT_ROOT / "scripts" / "install.sh"


def test_install_script_dry_run_does_not_write_files(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(fake_bin / "git", "#!/usr/bin/env bash\nexit 0\n")
    _write_executable(fake_bin / "python3", "#!/usr/bin/env bash\nexit 0\n")
    prefix = tmp_path / "memo-home"
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
    }

    result = subprocess.run(
        [
            "bash",
            "scripts/install.sh",
            "--dry-run",
            "--prefix",
            str(prefix),
            "--repo",
            "https://example.invalid/infinity-context.git",
            "--no-start",
        ],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert not prefix.exists()
    assert "dry-run:" in result.stdout


def test_install_script_uses_stable_source_and_verified_agent_tool(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(
        fake_bin / "docker",
        "\n".join(
            [
                "#!/usr/bin/env bash",
                'if [ "$1" = "compose" ] && [ "$2" = "version" ]; then',
                "  exit 0",
                "fi",
                "exit 0",
                "",
            ]
        ),
    )
    _write_executable(fake_bin / "git", "#!/usr/bin/env bash\nexit 0\n")
    _write_executable(fake_bin / "python3", "#!/usr/bin/env bash\nexit 0\n")
    prefix = tmp_path / "infinity-context-home"
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
    }

    result = subprocess.run(
        [
            "bash",
            str(INSTALL_SCRIPT),
            "--dry-run",
            "--prefix",
            str(prefix),
            "--agent",
            "claude",
            "--agent",
            "codex",
            "--manual-memory",
            "--no-open-ui",
        ],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "https://github.com/777genius/infinity-context.git" in result.stdout
    assert "--branch v0.1.0" in result.stdout
    assert "python3 -m venv" in result.stdout
    assert "pip==26.2.1" in result.stdout
    assert "setuptools==83.0.0" in result.stdout
    assert "wheel==0.47.0" in result.stdout
    assert r"\[mcp\]" in result.stdout
    assert "quickstart" in result.stdout
    assert "--agent claude" in result.stdout
    assert "--agent codex" in result.stdout
    assert "--manual-memory" in result.stdout
    assert "--no-open-ui" in result.stdout
    assert "would install verified plugin-kit-ai 1.2.4" in result.stderr


def test_no_agent_tools_keeps_quickstart_from_touching_agent_configs(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(
        fake_bin / "docker",
        "#!/usr/bin/env bash\n[ \"$1\" = \"compose\" ] && [ \"$2\" = \"version\" ]\n",
    )
    _write_executable(fake_bin / "git", "#!/usr/bin/env bash\nexit 0\n")
    _write_executable(fake_bin / "python3", "#!/usr/bin/env bash\nexit 0\n")
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
    }

    result = subprocess.run(
        [
            "bash",
            str(INSTALL_SCRIPT),
            "--dry-run",
            "--prefix",
            str(tmp_path / "infinity-context-home"),
            "--no-agent-tools",
        ],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "--no-install-agents" in result.stdout
    assert "would install verified plugin-kit-ai" not in result.stderr


def test_installer_rejects_conflicting_agent_and_memory_modes() -> None:
    all_agents = subprocess.run(
        ["bash", str(INSTALL_SCRIPT), "--all-agents", "--agent", "codex"],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    memory_modes = subprocess.run(
        ["bash", str(INSTALL_SCRIPT), "--retrieve-only", "--manual-memory"],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert all_agents.returncode == 2
    assert "cannot be combined" in all_agents.stderr
    assert memory_modes.returncode == 2
    assert "cannot be combined" in memory_modes.stderr


def test_release_metadata_and_workflow_contract() -> None:
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]
    workflow = (PROJECT_ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )
    script = INSTALL_SCRIPT.read_text(encoding="utf-8")

    assert project["version"] == "0.1.0"
    assert project["license"] == "Apache-2.0"
    assert project["license-files"] == ["LICENSE"]
    assert project["urls"]["Repository"] == "https://github.com/777genius/infinity-context.git"
    assert (PROJECT_ROOT / "LICENSE").is_file()
    assert "Apache License" in (PROJECT_ROOT / "LICENSE").read_text(encoding="utf-8")
    assert 'REF="${INFINITY_CONTEXT_INSTALL_REF:-v0.1.0}"' in script
    assert "PLUGIN_KIT_AI_VERSION=\"1.2.4\"" in script
    assert "BOOTSTRAP_PIP_VERSION=\"26.2.1\"" in script
    assert "BOOTSTRAP_SETUPTOOLS_VERSION=\"83.0.0\"" in script
    assert "BOOTSTRAP_WHEEL_VERSION=\"0.47.0\"" in script
    assert "Python 3.11 or newer is required" in script
    assert "packages/infinity_context_contracts" in script
    for checksum in (
        "f914226c7ebf8930e751e14da58bc4cd23eeaad4cc7f10fc31629a8233c7c6dc",
        "6812086dec43958508efb2945afd06c1b1ec0b7eac8ba0119790e06a9fed8bb1",
        "fd06f16292ffcc34f5436923e59039930668e5bbfb07e82ef589cf9d3b39822a",
        "46dcb07cd7d7a39fcc095ab3a38270bcdb5e524dad149fbc9d381396f163815b",
    ):
        assert checksum in script
    for action in (
        "actions/checkout@v7.0.1",
        "actions/setup-python@v7.0.0",
        "actions/upload-artifact@v7.0.1",
        "actions/download-artifact@v8.0.1",
        "actions/attest-build-provenance@v4.1.1",
        "docker/setup-qemu-action@v4.2.0",
        "docker/setup-buildx-action@v4.2.0",
        "docker/login-action@v4.6.0",
        "docker/metadata-action@v6.2.0",
        "docker/build-push-action@v7.3.0",
        "pypa/gh-action-pypi-publish@release/v1",
    ):
        assert action in workflow
    assert "id-token: write" in workflow
    assert "attestations: write" in workflow
    assert "sha256sum -- *.tar.gz *.whl | sort > ../release-assets/SHA256SUMS" in workflow
    assert "packages-dir: dist" in workflow
    assert "name: infinity-context-${{ needs.prepare.outputs.tag }}-checksums" in workflow
    assert "ghcr.io/777genius/infinity-context" in workflow
    assert "platforms: linux/amd64,linux/arm64" in workflow


def _write_executable(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)

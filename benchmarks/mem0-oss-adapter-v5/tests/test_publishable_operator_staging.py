from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import stat
import subprocess
import tomllib
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from infinity_context_server.publishable_durable_scheduler import publishable_run_cli
from infinity_context_server.publishable_durable_scheduler.publishable_run_config import (
    load_publishable_run_files,
)
from infinity_context_server.publishable_durable_scheduler.publishable_run_contracts import (
    PUBLISHABLE_RUN_SECRETS_SCHEMA,
    PublishableRunProviderInputs,
)
from publishable_mem0_v5.config import (
    PINNED_DOCKER_HOST,
    RUNTIME_PIN_SHA256,
    SOURCE_COMMIT_SHA1,
    SOURCE_COMMIT_SHA256,
    SOURCE_MANIFEST_SHA256,
    DeploymentConfigError,
    load_lane_config,
)
from publishable_mem0_v5.run_provider import (
    PUBLISHABLE_MEM0_INFINITY_PROVIDER_NAME,
    Mem0InfinityPublishableRunDependencyFactory,
)
from publishable_mem0_v5.run_provider_config import (
    RUN_PROVIDER_SECRETS_SCHEMA,
    parse_run_provider_inputs,
)

from tools.build_publishable_staging import (
    OperatorStagingError,
    StagingPublicInputs,
    build_staging_bundle,
    load_staging_template,
    main,
)

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "operator" / "publishable-staging.template.json"
TRACKED_RUNTIME_PIN = ROOT / "authority" / "runtime-pin.json"
TRACKED_SOURCE_MANIFEST = ROOT / "authority" / "manifest.json"
REQUIRED_R16_PORTS = (6334, 8891, 8892, 19091)
STALE_RUNTIME_PIN_SHA256 = "f8f338b73d816d87981745b240026d802fb52c1a228b0e608231a4ef9ad33e46"
STALE_SOURCE_COMMIT_SHA256 = "ed27595275c2a0a884c15c28f9891088180ef3be734ee8304a8fbeaa68e953a7"
STALE_SOURCE_MANIFEST_SHA256 = "175ed7008e78ce958c3f9bc0195fbd81bfa3359d67f96f986dfce38360a2c62f"


def _public_inputs(
    *,
    protected_ports: tuple[int, ...] = REQUIRED_R16_PORTS,
    occupied_ports: tuple[int, ...] = (),
) -> StagingPublicInputs:
    return StagingPublicInputs(
        adapter_image_id="sha256:" + "a" * 64,
        codex_executable_sha256="d" * 64,
        bridge_account_binding_sha256=("1" * 64, "2" * 64, "3" * 64),
        config_hmac_sha256="4" * 64,
        deployment_closure_sha256="5" * 64,
        deployment_closure_hmac_sha256="6" * 64,
        server_closure_sha256="7" * 64,
        server_closure_hmac_sha256="8" * 64,
        account_i_pid=99101,
        account_i_start_ticks=812345,
        account_i_boot_id="11111111-1111-4111-8111-111111111111",
        account_i_netns_inode=4026532991,
        account_i_port=28891,
        account_i_protected_host_ports=protected_ports,
        account_i_container_ids=("9" * 64,),
        occupied_host_ports=occupied_ports,
    )


def _build(tmp_path: Path):
    return build_staging_bundle(
        template=load_staging_template(TEMPLATE),
        output_root=tmp_path / "operator-private-r17-6f2c",
        authority_root=tmp_path / "public-authorities-r17-6f2c",
        public_inputs=_public_inputs(),
    )


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.lstat().st_mode)


def test_tracked_runtime_pin_and_source_manifest_define_one_current_tuple() -> None:
    runtime_pin_raw = TRACKED_RUNTIME_PIN.read_bytes()
    manifest_raw = TRACKED_SOURCE_MANIFEST.read_bytes()
    runtime_pin = json.loads(runtime_pin_raw)
    manifest = json.loads(manifest_raw)
    source = runtime_pin["source_a"]
    template = load_staging_template(TEMPLATE)

    assert hashlib.sha256(runtime_pin_raw).hexdigest() == RUNTIME_PIN_SHA256
    assert source["commit_sha1"] == manifest["source_commit_sha1"] == SOURCE_COMMIT_SHA1
    assert hashlib.sha256(SOURCE_COMMIT_SHA1.encode("ascii")).hexdigest() == (SOURCE_COMMIT_SHA256)
    assert hashlib.sha256(manifest_raw).hexdigest() == SOURCE_MANIFEST_SHA256
    assert (ROOT / "authority" / "manifest.sha256").read_text() == SOURCE_MANIFEST_SHA256
    assert source["manifest_sha256"] == SOURCE_MANIFEST_SHA256
    assert template.provider["runtime"]["runtime_pin_sha256"] == RUNTIME_PIN_SHA256
    assert template.provider["suite"]["source_commit_sha256"] == SOURCE_COMMIT_SHA256
    assert template.authority_digests["source_manifest_sha256"] == SOURCE_MANIFEST_SHA256


def test_builds_exact_secret_free_lane_and_2040_configs_with_private_modes(
    tmp_path: Path,
) -> None:
    bundle = _build(tmp_path)
    lane = json.loads(bundle.lane_config_path.read_bytes())
    run = json.loads(bundle.run_config_path.read_bytes())
    fresh = json.loads(bundle.fresh_config_path.read_bytes())

    assert lane["schema_version"] == "publishable-mem0-v5-isolated-lane.v2"
    assert lane["bind_mount_authority"] == {
        "config_hmac_sha256": "4" * 64,
        "deployment_closure_hmac_sha256": "6" * 64,
        "deployment_closure_sha256": "5" * 64,
        "server_closure_hmac_sha256": "8" * 64,
        "server_closure_sha256": "7" * 64,
    }
    assert load_lane_config(bundle.lane_config_path).public_payload() == lane
    assert lane["project_name"] == "mem0-v5-publishable-staging-r17-6f2c"
    assert lane["host_adapter_port"] == 29192
    assert (
        lane["docker_host"]
        == PINNED_DOCKER_HOST
        == "unix:///run/infinity-locomo-docker/docker.sock"
    )
    assert [item["account_name"] for item in lane["bridges"]] == [
        "publishable-r17-6f2c-a",
        "publishable-r17-6f2c-b",
        "publishable-r17-6f2c-c",
    ]
    assert [item["account_binding_hmac_sha256"] for item in lane["bridges"]] == [
        "1" * 64,
        "2" * 64,
        "3" * 64,
    ]
    fence = lane["account_i_r16_fence"]
    assert fence == {
        "auth_root": "/var/data/codex-home/live-codex-auth/account-i",
        "boot_id": "11111111-1111-4111-8111-111111111111",
        "container_ids": ["9" * 64],
        "netns_inode": 4026532991,
        "pid": 99101,
        "port": 28891,
        "protected_host_ports": list(REQUIRED_R16_PORTS),
        "start_ticks": 812345,
        "state_root": (
            "/mnt/volume_ams3_1784742570542/infinity-context/live-canaries/"
            "mem0-v5-live-d7bf1ac4-r16"
        ),
    }
    private_lane_paths = [
        Path(value)
        for key, value in lane["paths"].items()
        if key
        in {
            "adapter_secret_dir",
            "adapter_state_dir",
            "attestation_dir",
            "fleet_auth_dir",
            "fleet_state_dir",
            "input_dir",
            "qdrant_state_dir",
        }
    ]
    assert len(set(private_lane_paths)) == 7
    assert all(path.parent == Path(lane["paths"]["run_root"]) for path in private_lane_paths)
    assert lane["runtime"]["codex_executable_sha256"] == "d" * 64
    assert lane["runtime"]["runtime_pin_sha256"] == RUNTIME_PIN_SHA256
    assert lane["runtime"]["source_commit_sha256"] == SOURCE_COMMIT_SHA256
    assert lane["source_manifest_sha256"] == SOURCE_MANIFEST_SHA256

    assert {key: value for key, value in run.items() if key != "adapter"} == {
        "dependency_provider": "mem0-infinity-production-v1",
        "max_dispatches_per_batch": 64,
        "publication_key_id": "publishable-staging-r17-6f2c-publication-2040",
        "schema_version": "memory-comparison-publishable-run-config.v1",
        "state": {
            "longmemeval_scheduler_database_path": str(
                bundle.run_private_root
                / "state-2040-r17-6f2c"
                / "longmemeval-2040-r17-6f2c.sqlite3"
            ),
            "locomo_scheduler_database_path": str(
                bundle.run_private_root / "state-2040-r17-6f2c" / "locomo-2040-r17-6f2c.sqlite3"
            ),
            "official_case_authority_path": str(
                bundle.run_private_root
                / "state-2040-r17-6f2c"
                / "official-cases-2040-r17-6f2c.sqlite3"
            ),
            "publication_receipt_path": str(
                bundle.run_private_root
                / "state-2040-r17-6f2c"
                / "publication-receipt-2040-r17-6f2c.json"
            ),
            "suite_seal_database_path": str(
                bundle.run_private_root
                / "state-2040-r17-6f2c"
                / "suite-seals-2040-r17-6f2c.sqlite3"
            ),
        },
    }
    adapter = run["adapter"]
    assert set(adapter) == {
        "extraction",
        "fleet",
        "official_cases",
        "retrieval",
        "runtime",
        "schema_version",
        "suite",
    }
    assert adapter["schema_version"] == "publishable-mem0-infinity-run-provider.v2"
    assert adapter["runtime"]["attestation"] == {
        "endpoint_timeout_seconds": 5,
        "lane_project_name": "mem0-v5-publishable-staging-r17-6f2c",
        "maximum_age_seconds": 300,
        "public_endpoint": "http://127.0.0.1:29192",
        "required_fleet_mode": "reopen",
        "runtime_attestation_directory": str(
            bundle.output_root
            / "mem0-v5-publishable-staging-r17-6f2c"
            / "runtime-attestations-r17-6f2c"
        ),
    }
    assert adapter["suite"]["mem0_base_url"] == "http://127.0.0.1:29192"
    assert adapter["runtime"]["authority"]["runtime_pin_sha256"] == RUNTIME_PIN_SHA256
    assert adapter["runtime"]["authority"]["source_manifest_sha256"] == (SOURCE_MANIFEST_SHA256)
    assert adapter["suite"]["source_commit_sha256"] == SOURCE_COMMIT_SHA256
    assert [item["account_name"] for item in adapter["fleet"]["bridges"]] == [
        "publishable-r17-6f2c-a",
        "publishable-r17-6f2c-b",
        "publishable-r17-6f2c-c",
    ]
    assert [item["origin"] for item in adapter["fleet"]["bridges"]] == [
        "http://127.0.0.1:8891",
        "http://127.0.0.1:8892",
        "http://127.0.0.1:8893",
    ]
    assert adapter["official_cases"]["locomo"]["sha256"] == (
        "79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4"
    )
    assert adapter["official_cases"]["longmemeval"]["sha256"] == (
        "d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442"
    )
    extraction_terminal_paths = tuple(Path(path) for path in adapter["extraction"].values())
    assert len(extraction_terminal_paths) == 2
    assert all(not path.exists() for path in extraction_terminal_paths)
    assert not bundle.secrets_path.exists()
    assert not bundle.fresh_secrets_path.exists()
    assert fresh["max_dispatches_per_batch"] == 5
    assert fresh["adapter"]["schema_version"] == (
        "publishable-mem0-infinity-fresh-chain-provider.v1"
    )
    assert fresh["adapter"]["fresh_chain"]["infinity_retrieval_database_path"].endswith(
        "/sealed-infinity-one-case.sqlite3"
    )
    assert "publishable" not in fresh or fresh.get("publishable") is False
    assert bundle.input_provider_config_path == (
        bundle.run_private_root / "input-provider-config.json"
    )
    assert bundle.input_provider_secrets_path == (
        bundle.run_private_root / "input-provider-secrets.json"
    )
    assert not bundle.input_provider_config_path.exists()
    assert not bundle.input_provider_secrets_path.exists()
    assert _mode(bundle.lane_config_path) == 0o600
    assert _mode(bundle.run_config_path) == 0o600
    directories = (
        bundle.output_root,
        Path(lane["paths"]["run_root"]),
        *private_lane_paths,
        bundle.run_private_root,
        bundle.run_private_root / "state-2040-r17-6f2c",
    )
    assert all(_mode(path) == 0o700 for path in directories)
    assert "publishable-run-2040.secrets.json" not in bundle.run_config_path.read_text()
    assert "credentials" not in bundle.run_config_path.read_text().casefold()


def _adapter_secrets(adapter: dict[str, object]) -> dict[str, object]:
    bridges = adapter["fleet"]["bridges"]
    return {
        "bridge_journal_authentication_key_hex": "13" * 32,
        "bridges": [
            {
                "attestation_secret_hex": f"{40 + index:02x}" * 32,
                "authorization_bearer": f"provider-free-bearer-{index}-" + "x" * 32,
                "bridge_id": bridge["bridge_id"],
                "launcher_receipt_key_hex": f"{50 + index:02x}" * 32,
            }
            for index, bridge in enumerate(bridges)
        ],
        "extraction_authentication_keys_hex": ["10" * 32, "11" * 32],
        "output_cipher_key_hex": "14" * 32,
        "retrieval_authentication_key_hex": "12" * 32,
        "runtime_attestation_root_secret_hex": "15" * 32,
        "schema_version": RUN_PROVIDER_SECRETS_SCHEMA,
    }


def test_generated_config_passes_real_outer_loader_and_production_provider_parser(
    tmp_path: Path,
) -> None:
    bundle = _build(tmp_path)
    run = json.loads(bundle.run_config_path.read_bytes())
    secrets = {
        "adapter": _adapter_secrets(run["adapter"]),
        "keys": {
            "official_case_authentication_key_hex": "01" * 32,
            "locomo_scheduler_authentication_key_hex": "02" * 32,
            "longmemeval_scheduler_authentication_key_hex": "03" * 32,
            "suite_seal_authentication_key_hex": "04" * 32,
            "publication_receipt_authentication_key_hex": "05" * 32,
        },
        "schema_version": PUBLISHABLE_RUN_SECRETS_SCHEMA,
    }
    bundle.secrets_path.write_text(json.dumps(secrets, sort_keys=True, separators=(",", ":")))
    bundle.secrets_path.chmod(0o600)

    outer_config, outer_secrets = load_publishable_run_files(
        private_root=bundle.run_private_root,
        config_path=bundle.run_config_path,
        secrets_path=bundle.secrets_path,
    )
    provider_root = bundle.run_private_root / "state-2040-r17-6f2c" / ".provider-test"
    provider_root.mkdir(mode=0o700)
    provider_config, provider_secrets = parse_run_provider_inputs(
        PublishableRunProviderInputs(
            state_root=provider_root,
            adapter_config_json=outer_config.adapter_config_json,
            adapter_secrets_json=outer_secrets.adapter_secrets_json,
        )
    )

    assert provider_config.runtime_attestation.endpoint == "http://127.0.0.1:29192"
    assert provider_config.runtime_attestation.required_fleet_mode == "reopen"
    assert provider_config.suite.mem0_base_url == provider_config.runtime_attestation.endpoint
    assert provider_config.runtime_authority.source_manifest_sha256 == SOURCE_MANIFEST_SHA256
    assert repr(provider_secrets) == "RunProviderSecrets(<redacted>)"


def test_generated_run_config_resolves_exact_installed_factory_provider_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bundle = _build(tmp_path)
    run = json.loads(bundle.run_config_path.read_bytes())
    assert (
        run["dependency_provider"]
        == PUBLISHABLE_MEM0_INFINITY_PROVIDER_NAME
        == "mem0-infinity-production-v1"
    )

    secrets = {
        "adapter": {},
        "keys": {
            "official_case_authentication_key_hex": "1" * 64,
            "locomo_scheduler_authentication_key_hex": "2" * 64,
            "longmemeval_scheduler_authentication_key_hex": "3" * 64,
            "suite_seal_authentication_key_hex": "4" * 64,
            "publication_receipt_authentication_key_hex": "5" * 64,
        },
        "schema_version": PUBLISHABLE_RUN_SECRETS_SCHEMA,
    }
    bundle.secrets_path.write_text(json.dumps(secrets))
    bundle.secrets_path.chmod(0o600)
    resolved: list[object] = []

    class ProviderFreeOrchestrator:
        def __init__(self, *, dependency_factory: object) -> None:
            resolved.append(dependency_factory)

        def run(self, **_arguments: object) -> SimpleNamespace:
            return SimpleNamespace(
                payload=lambda: {"publishable": True},
                publishable=True,
            )

    monkeypatch.setattr(publishable_run_cli, "PublishableRunOrchestrator", ProviderFreeOrchestrator)

    assert publishable_run_cli.main(bundle.commands.run_2040[1:]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out) == {"publishable": True}
    assert len(resolved) == 1
    assert type(resolved[0]) is Mem0InfinityPublishableRunDependencyFactory


def test_commands_are_exact_for_acceptance_reopen_attest_prepare_and_run(
    tmp_path: Path,
) -> None:
    bundle = _build(tmp_path)
    lane = str(bundle.lane_config_path)
    run_root = str(bundle.run_private_root)
    run_config = str(bundle.run_config_path)
    secrets = str(bundle.secrets_path)
    input_provider_config = str(bundle.input_provider_config_path)
    input_provider_secrets = str(bundle.input_provider_secrets_path)
    fresh_config = str(bundle.fresh_config_path)
    fresh_secrets = str(bundle.fresh_secrets_path)
    project = "mem0-v5-publishable-staging-r17-6f2c"
    docker_host = "unix:///run/infinity-locomo-docker/docker.sock"
    acceptance = (
        f"infinity-context-publishable-mem0-v5 acceptance --config {lane} "
        f"--inventory-scope project --project-name {project} --docker-host {docker_host}"
    )

    assert bundle.commands.acceptance == (
        "infinity-context-publishable-mem0-v5",
        "acceptance",
        "--config",
        lane,
        "--inventory-scope",
        "project",
        "--project-name",
        project,
        "--docker-host",
        docker_host,
    )
    assert bundle.commands.run_2040 == (
        "infinity-context-publishable-run",
        "--private-root",
        run_root,
        "--config",
        run_config,
        "--secrets",
        secrets,
        "--allow-live",
    )
    assert bundle.commands.prepare_inputs == (
        "infinity-context-publishable-inputs",
        "--private-root",
        run_root,
        "--config",
        run_config,
        "--secrets",
        secrets,
        "--input-provider-config",
        input_provider_config,
        "--input-provider-secrets",
        input_provider_secrets,
        "--max-extraction-steps",
        "130226",
        "--allow-subscription-dispatch",
    )
    assert "--allow-live" not in bundle.commands.prepare_inputs
    assert "--allow-subscription-dispatch" not in bundle.commands.run_2040
    assert bundle.commands.start_reopen[-2:] == ("--fleet-mode", "reopen")
    assert bundle.commands.attest_reopen[-2:] == ("--fleet-mode", "reopen")
    prepare_inputs = (
        f"infinity-context-publishable-inputs --private-root {run_root} "
        f"--config {run_config} --secrets {secrets} "
        f"--input-provider-config {input_provider_config} "
        f"--input-provider-secrets {input_provider_secrets} "
        "--max-extraction-steps 130226 --allow-subscription-dispatch"
    )
    fresh_canary = (
        f"infinity-context-publishable-fresh-chain-canary --private-root {run_root} "
        f"--config {fresh_config} --secrets {fresh_secrets} --allow-live-1-plus-4"
    )
    assert bundle.commands.fresh_canary == (
        "infinity-context-publishable-fresh-chain-canary",
        "--private-root",
        run_root,
        "--config",
        fresh_config,
        "--secrets",
        fresh_secrets,
        "--allow-live-1-plus-4",
    )
    initial_order = [
        {
            "command": acceptance,
            "name": "acceptance",
        },
        {
            "command": (
                f"infinity-context-publishable-mem0-v5 start --config {lane} --fleet-mode reopen"
            ),
            "name": "start_reopen",
        },
        {
            "command": (
                f"infinity-context-publishable-mem0-v5 attest --config {lane} --fleet-mode reopen"
            ),
            "name": "attest_reopen",
        },
        {
            "command": prepare_inputs,
            "name": "prepare_inputs",
        },
        {
            "command": (
                f"infinity-context-publishable-run --private-root {run_root} "
                f"--config {run_config} --secrets {secrets} --allow-live"
            ),
            "name": "run_2040",
        },
    ]
    assert bundle.commands.payload() == {
        "acceptance": acceptance,
        "attest_reopen": (
            f"infinity-context-publishable-mem0-v5 attest --config {lane} --fleet-mode reopen"
        ),
        "crash_reopen_resume_order": [initial_order[1], initial_order[2], initial_order[4]],
        "fresh_canary": fresh_canary,
        "initial_paid_create_order": initial_order,
        "operator_order": initial_order,
        "prepare_inputs": prepare_inputs,
        "run_2040": (
            f"infinity-context-publishable-run --private-root {run_root} "
            f"--config {run_config} --secrets {secrets} --allow-live"
        ),
        "start_reopen": (
            f"infinity-context-publishable-mem0-v5 start --config {lane} --fleet-mode reopen"
        ),
    }


def test_prepare_inputs_command_resolves_one_installed_console_entrypoint() -> None:
    expected = "infinity_context_server.publishable_input_preparation.cli:main"
    project = tomllib.loads((ROOT.parents[1] / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["scripts"]["infinity-context-publishable-inputs"] == expected

    installed = tuple(
        importlib.metadata.entry_points(
            group="console_scripts",
            name="infinity-context-publishable-inputs",
        )
    )
    assert len(installed) == 1
    assert installed[0].value == expected


def test_fresh_staging_only_emits_preparation_without_provider_or_docker_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executed: list[str] = []

    def forbidden(*_args: object, **_kwargs: object) -> None:
        executed.append("external-command")
        raise AssertionError("staging must not execute external commands")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(os, "system", forbidden)
    monkeypatch.setenv("PATH", "")
    monkeypatch.setenv("DOCKER_HOST", "unix:///untrusted/ambient-docker.sock")

    bundle = _build(tmp_path)
    run = json.loads(bundle.run_config_path.read_bytes())
    terminals = tuple(Path(path) for path in run["adapter"]["extraction"].values())
    names = [item["name"] for item in bundle.commands.payload()["operator_order"]]

    assert executed == []
    assert all(not path.exists() for path in terminals)
    assert not bundle.input_provider_config_path.exists()
    assert not bundle.input_provider_secrets_path.exists()
    assert not bundle.secrets_path.exists()
    assert names == [
        "acceptance",
        "start_reopen",
        "attest_reopen",
        "prepare_inputs",
        "run_2040",
    ]
    assert names.index("prepare_inputs") < names.index("run_2040")


@pytest.mark.parametrize("mode", (0o755, 0o750, 0o711))
def test_rejects_non_private_existing_output_root(tmp_path: Path, mode: int) -> None:
    output = tmp_path / "operator-private-r17-6f2c"
    output.mkdir(mode=mode)
    output.chmod(mode)

    with pytest.raises(
        OperatorStagingError,
        match="operator_staging_private_directory_invalid",
    ):
        build_staging_bundle(
            template=load_staging_template(TEMPLATE),
            output_root=output,
            authority_root=tmp_path / "public-authorities-r17-6f2c",
            public_inputs=_public_inputs(),
        )

    assert not any(output.iterdir())
    assert _mode(output) == mode


@pytest.mark.parametrize("source", ("protected", "occupied"))
def test_rejects_host_port_collision_before_writing(tmp_path: Path, source: str) -> None:
    protected = (*REQUIRED_R16_PORTS, 29192) if source == "protected" else REQUIRED_R16_PORTS
    occupied = (29192,) if source == "occupied" else ()
    output = tmp_path / "operator-private-r17-6f2c"

    with pytest.raises(OperatorStagingError, match="operator_staging_host_port_collision"):
        build_staging_bundle(
            template=load_staging_template(TEMPLATE),
            output_root=output,
            authority_root=tmp_path / "public-authorities-r17-6f2c",
            public_inputs=_public_inputs(
                protected_ports=protected,
                occupied_ports=occupied,
            ),
        )

    assert not output.exists()


def test_rejects_existing_output_without_overwriting_it(tmp_path: Path) -> None:
    template = load_staging_template(TEMPLATE)
    output = tmp_path / "operator-private-r17-6f2c"
    output.mkdir(mode=0o700)
    output.chmod(0o700)
    existing = output / template.lane_config_file_name
    existing.write_text("operator-owned-existing-config")
    existing.chmod(0o600)

    with pytest.raises(OperatorStagingError, match="operator_staging_output_collision"):
        build_staging_bundle(
            template=template,
            output_root=output,
            authority_root=tmp_path / "public-authorities-r17-6f2c",
            public_inputs=_public_inputs(),
        )

    assert existing.read_text() == "operator-owned-existing-config"


@pytest.mark.parametrize(
    "name",
    ("input-provider-config.json", "input-provider-secrets.json"),
)
def test_rejects_preexisting_input_provider_document_without_overwriting(
    tmp_path: Path,
    name: str,
) -> None:
    template = load_staging_template(TEMPLATE)
    output = tmp_path / "operator-private-r17-6f2c"
    run_root = output / template.run_private_root_name
    run_root.mkdir(parents=True, mode=0o700)
    output.chmod(0o700)
    run_root.chmod(0o700)
    existing = run_root / name
    existing.write_text("operator-owned-private-material")
    existing.chmod(0o600)

    with pytest.raises(OperatorStagingError, match="operator_staging_output_collision"):
        build_staging_bundle(
            template=template,
            output_root=output,
            authority_root=tmp_path / "public-authorities-r17-6f2c",
            public_inputs=_public_inputs(),
        )

    assert existing.read_text() == "operator-owned-private-material"
    assert not (output / template.lane_config_file_name).exists()


def test_rejects_template_path_and_bridge_name_collisions(tmp_path: Path) -> None:
    raw = json.loads(TEMPLATE.read_bytes())
    names = raw["lane"]["private_directory_names"]
    names["qdrant_state_dir"] = names["adapter_state_dir"]
    collision = tmp_path / "path-collision.json"
    collision.write_text(json.dumps(raw))

    with pytest.raises(OperatorStagingError, match="operator_staging_private_path_collision"):
        load_staging_template(collision)

    raw = json.loads(TEMPLATE.read_bytes())
    raw["lane"]["bridge_accounts"][2]["account_name"] = raw["lane"]["bridge_accounts"][0][
        "account_name"
    ]
    collision.write_text(json.dumps(raw))
    with pytest.raises(OperatorStagingError, match="operator_staging_bridge_name_collision"):
        load_staging_template(collision)


def test_rejects_the_exact_stale_runtime_source_generation_before_writing(
    tmp_path: Path,
) -> None:
    raw = json.loads(TEMPLATE.read_bytes())
    raw["authorities"]["source_manifest_sha256"] = STALE_SOURCE_MANIFEST_SHA256
    raw["provider"]["runtime"]["runtime_pin_sha256"] = STALE_RUNTIME_PIN_SHA256
    raw["provider"]["suite"]["source_commit_sha256"] = STALE_SOURCE_COMMIT_SHA256
    changed = tmp_path / "stale-runtime-source.json"
    changed.write_text(json.dumps(raw))

    with pytest.raises(OperatorStagingError, match="operator_staging_runtime_pin_stale"):
        load_staging_template(changed)

    template = load_staging_template(TEMPLATE)
    provider = json.loads(json.dumps(template.provider))
    provider["runtime"]["runtime_pin_sha256"] = STALE_RUNTIME_PIN_SHA256
    provider["suite"]["source_commit_sha256"] = STALE_SOURCE_COMMIT_SHA256
    stale = replace(
        template,
        authority_digests={
            **template.authority_digests,
            "source_manifest_sha256": STALE_SOURCE_MANIFEST_SHA256,
        },
        provider=provider,
    )
    output = tmp_path / "operator-private-r17-6f2c"
    with pytest.raises(OperatorStagingError, match="operator_staging_runtime_pin_stale"):
        build_staging_bundle(
            template=stale,
            output_root=output,
            authority_root=tmp_path / "public-authorities-r17-6f2c",
            public_inputs=_public_inputs(),
        )
    assert not output.exists()


def test_rejects_current_runtime_pin_cross_wired_to_stale_source_before_writing(
    tmp_path: Path,
) -> None:
    raw = json.loads(TEMPLATE.read_bytes())
    assert raw["provider"]["runtime"]["runtime_pin_sha256"] == RUNTIME_PIN_SHA256
    assert raw["authorities"]["source_manifest_sha256"] == SOURCE_MANIFEST_SHA256
    raw["provider"]["suite"]["source_commit_sha256"] = STALE_SOURCE_COMMIT_SHA256
    changed = tmp_path / "cross-wired-runtime-source.json"
    changed.write_text(json.dumps(raw))

    with pytest.raises(
        OperatorStagingError,
        match="operator_staging_runtime_source_cross_wire",
    ):
        load_staging_template(changed)

    template = load_staging_template(TEMPLATE)
    provider = json.loads(json.dumps(template.provider))
    provider["suite"]["source_commit_sha256"] = STALE_SOURCE_COMMIT_SHA256
    crossed = replace(template, provider=provider)
    output = tmp_path / "operator-private-r17-6f2c"
    with pytest.raises(
        OperatorStagingError,
        match="operator_staging_runtime_source_cross_wire",
    ):
        build_staging_bundle(
            template=crossed,
            output_root=output,
            authority_root=tmp_path / "public-authorities-r17-6f2c",
            public_inputs=_public_inputs(),
        )
    assert not output.exists()


@pytest.mark.parametrize(
    ("section", "field", "value"),
    (
        ("suite", "infinity_base_url", "http://credential@127.0.0.1:29292"),
        ("suite", "infinity_base_url", "http://127.0.0.1:29192"),
        ("runtime", "attestation_max_age_seconds", 7_201),
        ("runtime", "required_fleet_mode", "create"),
        ("runtime", "maximum_bridge_request_bytes", 1_023),
        ("runtime", "maximum_ciphertext_bytes", 1_023),
        ("runtime", "runtime_pin_name", "nested/runtime-pin.json"),
        ("retrieval", "database_name", "nested/retrieval.sqlite3"),
        ("official_cases", "locomo_dataset_name", "locomo10.json"),
        (
            "official_cases",
            "longmemeval_dataset_name",
            "foreign/longmemeval_oracle.json",
        ),
    ),
)
def test_template_rejects_provider_values_the_production_parser_would_reject(
    tmp_path: Path,
    section: str,
    field: str,
    value: object,
) -> None:
    raw = json.loads(TEMPLATE.read_bytes())
    raw["provider"][section][field] = value
    changed = tmp_path / f"invalid-{field}.json"
    changed.write_text(json.dumps(raw))

    with pytest.raises(OperatorStagingError):
        load_staging_template(changed)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("expected_case_count", 2_039),
        ("expected_evaluation_call_count", 8_159),
        ("expected_extraction_operation_count", 130_225),
        ("expected_total_call_count", 138_385),
    ),
)
def test_template_keeps_every_exact_2040_cardinality(
    tmp_path: Path,
    field: str,
    value: int,
) -> None:
    raw = json.loads(TEMPLATE.read_bytes())
    assert raw["run_2040"] == {
        **raw["run_2040"],
        "expected_case_count": 2_040,
        "expected_evaluation_call_count": 8_160,
        "expected_extraction_operation_count": 130_226,
        "expected_total_call_count": 138_386,
    }
    raw["run_2040"][field] = value
    changed = tmp_path / f"changed-{field}.json"
    changed.write_text(json.dumps(raw))

    with pytest.raises(OperatorStagingError, match="operator_staging_run_2040_cardinality_invalid"):
        load_staging_template(changed)


def test_rejects_any_account_i_r16_fence_root_change(tmp_path: Path) -> None:
    raw = json.loads(TEMPLATE.read_bytes())
    raw["account_i_r16_fence"]["auth_root"] = str(tmp_path / "lookalike-account-i")
    changed = tmp_path / "changed-fence.json"
    changed.write_text(json.dumps(raw))

    with pytest.raises(OperatorStagingError, match="operator_staging_account_i_r16_fence_invalid"):
        load_staging_template(changed)


def test_rejects_any_docker_socket_authority_change_before_writing(tmp_path: Path) -> None:
    alternate = "unix:///var/run/docker.sock"
    raw = json.loads(TEMPLATE.read_bytes())
    raw["lane"]["docker_host"] = alternate
    changed = tmp_path / "changed-docker-host.json"
    changed.write_text(json.dumps(raw))

    with pytest.raises(OperatorStagingError, match="operator_staging_docker_host_invalid"):
        load_staging_template(changed)

    output = tmp_path / "operator-private-r17-6f2c"
    with pytest.raises(OperatorStagingError, match="operator_staging_docker_host_invalid"):
        build_staging_bundle(
            template=replace(load_staging_template(TEMPLATE), docker_host=alternate),
            output_root=output,
            authority_root=tmp_path / "public-authorities-r17-6f2c",
            public_inputs=_public_inputs(),
        )
    assert not output.exists()


def test_generated_lane_config_ignores_ambient_and_rejects_unpinned_docker_socket(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DOCKER_HOST", "unix:///var/run/docker.sock")
    bundle = _build(tmp_path)
    lane = json.loads(bundle.lane_config_path.read_bytes())
    config = load_lane_config(bundle.lane_config_path)

    assert config.docker_host == PINNED_DOCKER_HOST
    assert config.authentication_payload()["config"]["docker_host"] == PINNED_DOCKER_HOST
    assert (
        config.compose_environment(config_file=bundle.lane_config_path, fleet_mode="create")[
            "DOCKER_HOST"
        ]
        == PINNED_DOCKER_HOST
    )

    lane["docker_host"] = "unix:///var/run/docker.sock"
    bundle.lane_config_path.write_text(json.dumps(lane))

    with pytest.raises(DeploymentConfigError, match="publishable_lane_docker_host_invalid"):
        load_lane_config(bundle.lane_config_path)


def test_generated_lane_config_rejects_stale_and_cross_wired_runtime_source_tuple(
    tmp_path: Path,
) -> None:
    bundle = _build(tmp_path)
    lane = json.loads(bundle.lane_config_path.read_bytes())
    lane["runtime"]["runtime_pin_sha256"] = STALE_RUNTIME_PIN_SHA256
    bundle.lane_config_path.write_text(json.dumps(lane))

    with pytest.raises(DeploymentConfigError, match="publishable_lane_runtime_pin_stale"):
        load_lane_config(bundle.lane_config_path)

    lane["runtime"]["runtime_pin_sha256"] = RUNTIME_PIN_SHA256
    lane["runtime"]["source_commit_sha256"] = STALE_SOURCE_COMMIT_SHA256
    bundle.lane_config_path.write_text(json.dumps(lane))

    with pytest.raises(
        DeploymentConfigError,
        match="publishable_lane_runtime_source_cross_wire",
    ):
        load_lane_config(bundle.lane_config_path)


def test_cli_reports_only_secret_free_paths_and_exact_commands(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "operator-private-r17-6f2c"
    authority = tmp_path / "public-authorities-r17-6f2c"
    argv = [
        "--template",
        str(TEMPLATE),
        "--output-root",
        str(output),
        "--authority-root",
        str(authority),
        "--adapter-image-id",
        "sha256:" + "a" * 64,
        "--codex-executable-sha256",
        "d" * 64,
        "--config-hmac-sha256",
        "4" * 64,
        "--deployment-closure-sha256",
        "5" * 64,
        "--deployment-closure-hmac-sha256",
        "6" * 64,
        "--server-closure-sha256",
        "7" * 64,
        "--server-closure-hmac-sha256",
        "8" * 64,
    ]
    for binding in ("1" * 64, "2" * 64, "3" * 64):
        argv.extend(("--bridge-binding-sha256", binding))
    argv.extend(
        (
            "--account-i-pid",
            "99101",
            "--account-i-start-ticks",
            "812345",
            "--account-i-boot-id",
            "11111111-1111-4111-8111-111111111111",
            "--account-i-netns-inode",
            "4026532991",
            "--account-i-port",
            "28891",
        )
    )
    for port in REQUIRED_R16_PORTS:
        argv.extend(("--account-i-protected-host-port", str(port)))
    argv.extend(("--account-i-container-id", "9" * 64))

    assert main(argv) == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert captured.err == ""
    assert payload["status"] == "STAGED_SECRET_FREE"
    assert payload["secrets_path_not_created"].endswith("/publishable-run-2040.secrets.json")
    assert payload["input_provider_config_path_not_created"].endswith("/input-provider-config.json")
    assert payload["input_provider_secrets_path_not_created"].endswith(
        "/input-provider-secrets.json"
    )
    assert payload["commands"]["prepare_inputs"].endswith(
        "/input-provider-secrets.json --max-extraction-steps 130226 --allow-subscription-dispatch"
    )
    assert payload["commands"]["run_2040"].endswith(
        "/publishable-run-2040.secrets.json --allow-live"
    )
    assert [item["name"] for item in payload["commands"]["operator_order"]] == [
        "acceptance",
        "start_reopen",
        "attest_reopen",
        "prepare_inputs",
        "run_2040",
    ]
    assert payload["commands"]["initial_paid_create_order"] == payload["commands"]["operator_order"]
    initial = payload["commands"]["operator_order"]
    assert payload["commands"]["crash_reopen_resume_order"] == [
        initial[1],
        initial[2],
        initial[4],
    ]
    assert "start_create" not in payload["commands"]
    assert "attest_create" not in payload["commands"]
    assert not Path(payload["secrets_path_not_created"]).exists()
    assert not Path(payload["input_provider_config_path_not_created"]).exists()
    assert not Path(payload["input_provider_secrets_path_not_created"]).exists()


def test_public_input_bindings_must_be_three_distinct_commitments() -> None:
    with pytest.raises(OperatorStagingError, match="operator_staging_bridge_bindings_invalid"):
        replace(
            _public_inputs(),
            bridge_account_binding_sha256=("1" * 64, "1" * 64, "3" * 64),
        )

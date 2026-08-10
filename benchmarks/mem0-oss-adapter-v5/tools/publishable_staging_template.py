"""Strict public contracts for the publishable Mem0 v5 staging template."""

from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlsplit
from uuid import UUID

TEMPLATE_SCHEMA: Final = "publishable-mem0-v5-operator-staging-template.v2"
PINNED_DOCKER_HOST: Final = "unix:///run/infinity-locomo-docker/docker.sock"
PROTECTED_ACCOUNT_I_AUTH_ROOT: Final = Path("/var/data/codex-home/live-codex-auth/account-i")
PROTECTED_R16_ROOT: Final = Path(
    "/mnt/volume_ams3_1784742570542/infinity-context/live-canaries/mem0-v5-live-d7bf1ac4-r16"
)
INTERNAL_LANE_PORTS: Final = frozenset({6334, 6335, 8891, 8892, 8893, 19091, 19191})
EXPECTED_CASE_COUNT: Final = 2_040
EXPECTED_EVALUATION_CALL_COUNT: Final = 8_160
EXPECTED_EXTRACTION_OPERATION_COUNT: Final = 130_226
EXPECTED_TOTAL_CALL_COUNT: Final = 138_386
STATE_FILE_KEYS: Final = frozenset(
    {
        "longmemeval_scheduler_database_path",
        "locomo_scheduler_database_path",
        "official_case_authority_path",
        "publication_receipt_path",
        "suite_seal_database_path",
    }
)

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
_PROJECT = re.compile(r"mem0-v5-publishable-[a-z0-9][a-z0-9-]{5,63}\Z")
_ACCOUNT = re.compile(r"[a-z][a-z0-9-]{1,31}\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}\Z")
_CONTAINER_ID = re.compile(r"[0-9a-f]{64}\Z")
_MAX_TEMPLATE_BYTES = 256 * 1024
_PRIVATE_DIRECTORY_KEYS = frozenset(
    {
        "adapter_secret_dir",
        "adapter_state_dir",
        "attestation_dir",
        "fleet_auth_dir",
        "fleet_state_dir",
        "input_dir",
        "qdrant_state_dir",
    }
)


class OperatorStagingError(RuntimeError):
    """Stable secret-free staging rejection."""

    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class BridgeTemplate:
    account_name: str
    bridge_id: str


@dataclass(frozen=True, slots=True)
class StagingTemplate:
    project_name: str
    docker_host: str
    host_adapter_port: int
    lane_config_file_name: str
    private_directory_names: dict[str, str]
    bridges: tuple[BridgeTemplate, BridgeTemplate, BridgeTemplate]
    authority_names: dict[str, str]
    authority_digests: dict[str, str]
    run_private_root_name: str
    run_state_directory_name: str
    run_config_file_name: str
    run_secrets_file_name: str
    run_state_file_names: dict[str, str]
    dependency_provider: str
    publication_key_id: str
    max_dispatches_per_batch: int
    fence_state_root: Path
    fence_auth_root: Path
    required_protected_host_ports: tuple[int, ...]
    provider: dict[str, dict[str, object]]


@dataclass(frozen=True, slots=True)
class StagingPublicInputs:
    """Reviewed public commitments and an externally captured fence observation."""

    adapter_image_id: str
    codex_executable_sha256: str
    bridge_account_binding_sha256: tuple[str, str, str]
    config_hmac_sha256: str
    deployment_closure_sha256: str
    deployment_closure_hmac_sha256: str
    server_closure_sha256: str
    server_closure_hmac_sha256: str
    account_i_pid: int
    account_i_start_ticks: int
    account_i_boot_id: str
    account_i_netns_inode: int
    account_i_port: int
    account_i_protected_host_ports: tuple[int, ...]
    account_i_container_ids: tuple[str, ...]
    occupied_host_ports: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if _IMAGE_ID.fullmatch(self.adapter_image_id) is None:
            fail("operator_staging_adapter_image_id_invalid")
        require_sha256(self.codex_executable_sha256, "codex_executable")
        bindings = self.bridge_account_binding_sha256
        if type(bindings) is not tuple or len(bindings) != 3 or len(set(bindings)) != 3:
            fail("operator_staging_bridge_bindings_invalid")
        for binding in bindings:
            require_sha256(binding, "bridge_binding")
        for value, label in (
            (self.config_hmac_sha256, "config_hmac"),
            (self.deployment_closure_sha256, "deployment_closure"),
            (self.deployment_closure_hmac_sha256, "deployment_closure_hmac"),
            (self.server_closure_sha256, "server_closure"),
            (self.server_closure_hmac_sha256, "server_closure_hmac"),
        ):
            require_sha256(value, label)
        if type(self.account_i_pid) is not int or self.account_i_pid <= 1:
            fail("operator_staging_account_i_pid_invalid")
        if type(self.account_i_start_ticks) is not int or self.account_i_start_ticks <= 0:
            fail("operator_staging_account_i_start_ticks_invalid")
        try:
            boot_id = str(UUID(self.account_i_boot_id))
        except (AttributeError, ValueError):
            boot_id = ""
        if boot_id != self.account_i_boot_id:
            fail("operator_staging_account_i_boot_id_invalid")
        if type(self.account_i_netns_inode) is not int or self.account_i_netns_inode <= 0:
            fail("operator_staging_account_i_netns_invalid")
        _require_port(self.account_i_port, "account_i")
        _require_distinct_ports(
            self.account_i_protected_host_ports,
            "account_i_protected_host_ports",
        )
        _require_distinct_ports(self.occupied_host_ports, "occupied_host_ports")
        containers = self.account_i_container_ids
        if (
            type(containers) is not tuple
            or not 1 <= len(containers) <= 16
            or len(set(containers)) != len(containers)
            or any(_CONTAINER_ID.fullmatch(item) is None for item in containers)
        ):
            fail("operator_staging_account_i_container_ids_invalid")


def load_staging_template(path: Path) -> StagingTemplate:
    """Load the exact-key public template without resolving protected paths."""

    try:
        value = path.lstat()
        if stat.S_ISLNK(value.st_mode) or not stat.S_ISREG(value.st_mode):
            fail("operator_staging_template_file_invalid")
        raw = path.read_bytes()
    except OperatorStagingError:
        raise
    except OSError:
        fail("operator_staging_template_unavailable")
    if not raw or len(raw) > _MAX_TEMPLATE_BYTES:
        fail("operator_staging_template_size_invalid")
    try:
        root = json.loads(raw, object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError, OperatorStagingError):
        fail("operator_staging_template_json_invalid")
    return _parse_template(root)


def _parse_template(value: object) -> StagingTemplate:
    root = _object(
        value,
        {
            "account_i_r16_fence",
            "authorities",
            "lane",
            "provider",
            "run_2040",
            "schema_version",
        },
        "root",
    )
    if root["schema_version"] != TEMPLATE_SCHEMA:
        fail("operator_staging_template_schema_invalid")
    lane = _object(
        root["lane"],
        {
            "bridge_accounts",
            "docker_host",
            "host_adapter_port",
            "lane_config_file_name",
            "private_directory_names",
            "project_name",
        },
        "lane",
    )
    authorities = _object(
        root["authorities"],
        {
            "codex_executable_name",
            "deployment_dir_name",
            "node_executable_name",
            "node_executable_sha256",
            "phase_c_authority_dir_name",
            "runtime_artifact_manifest_sha256",
            "runtime_entrypoint_sha256",
            "runtime_root_name",
            "server_package_dir_name",
            "source_authority_dir_name",
            "source_authority_pin_dir_name",
            "source_manifest_sha256",
        },
        "authorities",
    )
    run = _object(
        root["run_2040"],
        {
            "dependency_provider",
            "expected_case_count",
            "expected_evaluation_call_count",
            "expected_extraction_operation_count",
            "expected_total_call_count",
            "max_dispatches_per_batch",
            "private_root_name",
            "publication_key_id",
            "run_config_file_name",
            "secrets_file_name",
            "state_directory_name",
            "state_file_names",
        },
        "run_2040",
    )
    fence = _object(
        root["account_i_r16_fence"],
        {"auth_root", "required_protected_host_ports", "state_root"},
        "account_i_r16_fence",
    )
    provider = _provider(root["provider"])
    private_names = _string_map(
        lane["private_directory_names"],
        required=_PRIVATE_DIRECTORY_KEYS,
        label="private_directory_names",
    )
    state_names = _string_map(
        run["state_file_names"],
        required=STATE_FILE_KEYS,
        label="state_file_names",
    )
    for name in (*private_names.values(), *state_names.values()):
        _require_simple_name(name)
    if len(set(private_names.values())) != len(private_names):
        fail("operator_staging_private_path_collision")
    if len(set(state_names.values())) != len(state_names):
        fail("operator_staging_run_state_path_collision")

    bridges_value = lane["bridge_accounts"]
    if type(bridges_value) is not list or len(bridges_value) != 3:
        fail("operator_staging_bridge_count_invalid")
    bridges = tuple(_bridge(item) for item in bridges_value)
    if (
        len({bridge.account_name for bridge in bridges}) != 3
        or len({bridge.bridge_id for bridge in bridges}) != 3
    ):
        fail("operator_staging_bridge_name_collision")

    project_name = _string(lane["project_name"], "project_name")
    if _PROJECT.fullmatch(project_name) is None or _reserved(project_name):
        fail("operator_staging_project_name_invalid")
    docker_host = _string(lane["docker_host"], "docker_host")
    if docker_host != PINNED_DOCKER_HOST:
        fail("operator_staging_docker_host_invalid")
    require_absolute_path(Path(docker_host.removeprefix("unix://")), "docker_socket")
    host_port = _integer(lane["host_adapter_port"], "host_adapter_port")
    _require_port(host_port, "host_adapter")
    if host_port in INTERNAL_LANE_PORTS:
        fail("operator_staging_host_port_collision")
    if provider["suite"]["infinity_base_url"] == f"http://127.0.0.1:{host_port}":
        fail("operator_staging_provider_endpoint_cross_wire")

    authority_names = {
        key.removesuffix("_name"): _string(item, key)
        for key, item in authorities.items()
        if key.endswith("_name")
    }
    for name in authority_names.values():
        _require_relative_name(name)
    if len(set(authority_names.values())) != len(authority_names):
        fail("operator_staging_authority_path_collision")
    authority_digests = {
        key: _string(item, key) for key, item in authorities.items() if key.endswith("_sha256")
    }
    for key, digest in authority_digests.items():
        require_sha256(digest, key.removesuffix("_sha256"))

    exact_counts = {
        "expected_case_count": EXPECTED_CASE_COUNT,
        "expected_evaluation_call_count": EXPECTED_EVALUATION_CALL_COUNT,
        "expected_extraction_operation_count": EXPECTED_EXTRACTION_OPERATION_COUNT,
        "expected_total_call_count": EXPECTED_TOTAL_CALL_COUNT,
    }
    if any(run[key] != expected for key, expected in exact_counts.items()):
        fail("operator_staging_run_2040_cardinality_invalid")
    maximum = _integer(run["max_dispatches_per_batch"], "max_dispatches_per_batch")
    if not 1 <= maximum <= EXPECTED_EVALUATION_CALL_COUNT:
        fail("operator_staging_max_dispatches_invalid")

    state_root = Path(_string(fence["state_root"], "fence_state_root"))
    auth_root = Path(_string(fence["auth_root"], "fence_auth_root"))
    if state_root != PROTECTED_R16_ROOT or auth_root != PROTECTED_ACCOUNT_I_AUTH_ROOT:
        fail("operator_staging_account_i_r16_fence_invalid")
    ports_value = fence["required_protected_host_ports"]
    if type(ports_value) is not list:
        fail("operator_staging_required_protected_ports_invalid")
    ports = tuple(ports_value)
    _require_distinct_ports(ports, "required_protected_host_ports")
    if not {6334, 8891, 8892, 19091}.issubset(ports):
        fail("operator_staging_r16_ports_incomplete")

    file_names = (
        _string(lane["lane_config_file_name"], "lane_config_file_name"),
        _string(run["private_root_name"], "run_private_root_name"),
        _string(run["state_directory_name"], "run_state_directory_name"),
        _string(run["run_config_file_name"], "run_config_file_name"),
        _string(run["secrets_file_name"], "run_secrets_file_name"),
    )
    for name in file_names:
        _require_simple_name(name)
    if len(set(file_names)) != len(file_names):
        fail("operator_staging_path_collision")
    dependency_provider = _string(run["dependency_provider"], "dependency_provider")
    publication_key_id = _string(run["publication_key_id"], "publication_key_id")
    if (
        _IDENTIFIER.fullmatch(dependency_provider) is None
        or _IDENTIFIER.fullmatch(publication_key_id) is None
    ):
        fail("operator_staging_run_identifier_invalid")
    return StagingTemplate(
        project_name=project_name,
        docker_host=docker_host,
        host_adapter_port=host_port,
        lane_config_file_name=file_names[0],
        private_directory_names=private_names,
        bridges=bridges,
        authority_names=authority_names,
        authority_digests=authority_digests,
        run_private_root_name=file_names[1],
        run_state_directory_name=file_names[2],
        run_config_file_name=file_names[3],
        run_secrets_file_name=file_names[4],
        run_state_file_names=state_names,
        dependency_provider=dependency_provider,
        publication_key_id=publication_key_id,
        max_dispatches_per_batch=maximum,
        fence_state_root=state_root,
        fence_auth_root=auth_root,
        required_protected_host_ports=ports,
        provider=provider,
    )


def _provider(value: object) -> dict[str, dict[str, object]]:
    root = _object(
        value,
        {"extraction", "official_cases", "retrieval", "runtime", "suite"},
        "provider",
    )
    extraction = _object(
        root["extraction"],
        {"locomo_terminal_name", "longmemeval_terminal_name"},
        "provider_extraction",
    )
    official = _object(
        root["official_cases"],
        {
            "locomo_dataset_name",
            "locomo_dataset_sha256",
            "longmemeval_dataset_name",
            "longmemeval_dataset_sha256",
        },
        "provider_official_cases",
    )
    retrieval = _object(
        root["retrieval"],
        {"authority_root_sha256", "database_name"},
        "provider_retrieval",
    )
    runtime = _object(
        root["runtime"],
        {
            "attestation_max_age_seconds",
            "bridge_connect_timeout_seconds",
            "bridge_read_timeout_seconds",
            "bridge_write_timeout_seconds",
            "endpoint_attestation_timeout_seconds",
            "extraction_response_format_sha256",
            "extraction_response_schema_sha256",
            "extraction_system_prompt_sha256",
            "lease_duration_ms",
            "maximum_bridge_request_bytes",
            "maximum_ciphertext_bytes",
            "output_cipher_key_id",
            "runtime_pin_name",
            "runtime_pin_sha256",
            "runtime_route_binding_sha256",
            "runtime_source_sha256",
            "subscription_runtime_binding_commitment_sha256",
        },
        "provider_runtime",
    )
    suite = _object(
        root["suite"],
        {
            "dispatch_deadline_unix_ms",
            "dispatch_not_before_unix_ms",
            "infinity_base_url",
            "locomo_run_id",
            "longmemeval_run_id",
            "publication_bundle_sha256",
            "source_commit_sha256",
            "suite_id",
        },
        "provider_suite",
    )
    for key in extraction:
        _require_simple_name(_string(extraction[key], key))
    dataset_names = tuple(
        _string(official[key], key) for key in ("locomo_dataset_name", "longmemeval_dataset_name")
    )
    for name in dataset_names:
        _require_relative_name(name)
    dataset_paths = tuple(Path(name) for name in dataset_names)
    if (
        any(len(path.parts) != 2 for path in dataset_paths)
        or dataset_paths[0].parent != dataset_paths[1].parent
    ):
        fail("operator_staging_provider_dataset_path_invalid")
    _require_simple_name(_string(retrieval["database_name"], "retrieval_database_name"))
    _require_simple_name(_string(runtime["runtime_pin_name"], "runtime_pin_name"))
    for mapping in (official, retrieval, runtime, suite):
        for key, item in mapping.items():
            if key.endswith("_sha256"):
                require_sha256(item, key.removesuffix("_sha256"))
    maximum_safe_integer = 9_007_199_254_740_991
    attestation_age = _integer(
        runtime["attestation_max_age_seconds"],
        "attestation_max_age_seconds",
    )
    if not 1 <= attestation_age <= 7_200:
        fail("operator_staging_attestation_max_age_seconds_invalid")
    lease_duration = _integer(runtime["lease_duration_ms"], "lease_duration_ms")
    if not 1 <= lease_duration <= maximum_safe_integer:
        fail("operator_staging_lease_duration_ms_invalid")
    for key in ("maximum_bridge_request_bytes", "maximum_ciphertext_bytes"):
        if not 1_024 <= _integer(runtime[key], key) <= maximum_safe_integer:
            fail(f"operator_staging_{key}_invalid")
    for key in (
        "bridge_connect_timeout_seconds",
        "bridge_read_timeout_seconds",
        "bridge_write_timeout_seconds",
        "endpoint_attestation_timeout_seconds",
    ):
        item = runtime[key]
        if type(item) not in {int, float} or not 0 < float(item) <= 3_600:
            fail(f"operator_staging_{key}_invalid")
    before = _integer(suite["dispatch_not_before_unix_ms"], "dispatch_not_before_unix_ms")
    deadline = _integer(suite["dispatch_deadline_unix_ms"], "dispatch_deadline_unix_ms")
    if not 0 <= before <= maximum_safe_integer or not before < deadline <= maximum_safe_integer:
        fail("operator_staging_provider_dispatch_window_invalid")
    for key in ("output_cipher_key_id",):
        if _IDENTIFIER.fullmatch(_string(runtime[key], key)) is None:
            fail("operator_staging_provider_identifier_invalid")
    for key in ("locomo_run_id", "longmemeval_run_id", "suite_id"):
        if _IDENTIFIER.fullmatch(_string(suite[key], key)) is None:
            fail("operator_staging_provider_identifier_invalid")
    _loopback_origin(suite["infinity_base_url"])
    return {
        "extraction": dict(extraction),
        "official_cases": dict(official),
        "retrieval": dict(retrieval),
        "runtime": dict(runtime),
        "suite": dict(suite),
    }


def _bridge(value: object) -> BridgeTemplate:
    raw = _object(value, {"account_name", "bridge_id"}, "bridge")
    account_name = _string(raw["account_name"], "bridge_account_name")
    bridge_id = _string(raw["bridge_id"], "bridge_id")
    if _ACCOUNT.fullmatch(account_name) is None or _reserved(account_name):
        fail("operator_staging_bridge_account_invalid")
    if _IDENTIFIER.fullmatch(bridge_id) is None or _reserved(bridge_id):
        fail("operator_staging_bridge_id_invalid")
    return BridgeTemplate(account_name=account_name, bridge_id=bridge_id)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            fail("operator_staging_template_duplicate_key")
        result[key] = value
    return result


def _object(value: object, required: set[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != required:
        fail(f"operator_staging_template_{label}_fields_invalid")
    return value


def _string_map(value: object, *, required: frozenset[str], label: str) -> dict[str, str]:
    raw = _object(value, set(required), label)
    return {key: _string(item, key) for key, item in raw.items()}


def _string(value: object, label: str) -> str:
    if type(value) is not str or not value or value != value.strip() or "\x00" in value:
        fail(f"operator_staging_{label}_invalid")
    return value


def _integer(value: object, label: str) -> int:
    if type(value) is not int:
        fail(f"operator_staging_{label}_invalid")
    return value


def _loopback_origin(value: object) -> str:
    origin = _string(value, "infinity_base_url")
    try:
        parsed = urlsplit(origin)
        port = parsed.port
    except ValueError:
        fail("operator_staging_infinity_base_url_invalid")
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or type(port) is not int
        or not 1024 <= port <= 65_535
        or origin != f"http://127.0.0.1:{port}"
    ):
        fail("operator_staging_infinity_base_url_invalid")
    return origin


def require_sha256(value: object, label: str) -> None:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        fail(f"operator_staging_{label}_sha256_invalid")


def _require_port(value: object, label: str) -> None:
    if type(value) is not int or not 1024 <= value <= 65535:
        fail(f"operator_staging_{label}_port_invalid")


def _require_distinct_ports(value: object, label: str) -> None:
    if type(value) is not tuple or len(set(value)) != len(value):
        fail(f"operator_staging_{label}_invalid")
    for port in value:
        _require_port(port, label)


def require_absolute_path(value: object, label: str) -> None:
    if (
        not isinstance(value, Path)
        or not value.is_absolute()
        or Path(os.path.normpath(value)) != value
    ):
        fail(f"operator_staging_{label}_path_invalid")


def _require_simple_name(value: str) -> None:
    path = Path(value)
    if path.name != value or value in {".", ".."}:
        fail("operator_staging_path_name_invalid")


def _require_relative_name(value: str) -> None:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or Path(os.path.normpath(path)) != path:
        fail("operator_staging_authority_name_invalid")


def _reserved(value: str) -> bool:
    canonical = value.casefold().replace("_", "-")
    return "account-i" in canonical or canonical == "r16" or canonical.endswith("-r16")


def fail(code: str) -> None:
    raise OperatorStagingError(code)


__all__ = (
    "EXPECTED_CASE_COUNT",
    "EXPECTED_EVALUATION_CALL_COUNT",
    "EXPECTED_EXTRACTION_OPERATION_COUNT",
    "EXPECTED_TOTAL_CALL_COUNT",
    "INTERNAL_LANE_PORTS",
    "PINNED_DOCKER_HOST",
    "PROTECTED_ACCOUNT_I_AUTH_ROOT",
    "PROTECTED_R16_ROOT",
    "STATE_FILE_KEYS",
    "OperatorStagingError",
    "StagingPublicInputs",
    "StagingTemplate",
    "fail",
    "load_staging_template",
    "require_absolute_path",
)

"""Strict, publication-key-free configuration for the installed run provider."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import final
from urllib.parse import urlsplit

from infinity_context_server.publishable_durable_scheduler.publishable_run_contracts import (
    PublishableRunError,
    PublishableRunProviderInputs,
)

RUN_PROVIDER_CONFIG_SCHEMA = "publishable-mem0-infinity-run-provider.v2"
RUN_PROVIDER_SECRETS_SCHEMA = "publishable-mem0-infinity-run-provider-secrets.v2"

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}\Z")


@final
@dataclass(frozen=True, slots=True)
class OfficialDatasetConfig:
    path: Path
    sha256: str


@final
@dataclass(frozen=True, slots=True)
class RunSuiteConfig:
    suite_id: str
    locomo_run_id: str
    longmemeval_run_id: str
    publication_bundle_sha256: str
    source_commit_sha256: str
    infinity_base_url: str
    mem0_base_url: str
    dispatch_not_before_unix_ms: int
    dispatch_deadline_unix_ms: int


@final
@dataclass(frozen=True, slots=True)
class FleetBridgeConfig:
    account_name: str
    bridge_id: str
    origin: str
    account_binding_hmac_sha256: str
    readiness_receipt_path: Path


@final
@dataclass(frozen=True, slots=True)
class RuntimeAttestationConfig:
    directory: Path
    endpoint: str
    endpoint_timeout_seconds: float
    lane_project_name: str
    maximum_age_seconds: int


@final
@dataclass(frozen=True, slots=True)
class RuntimeAuthorityConfig:
    adapter_image_id: str
    codex_executable_sha256: str
    extraction_response_format_sha256: str
    extraction_response_schema_sha256: str
    extraction_system_prompt_sha256: str
    node_executable_sha256: str
    runtime_artifact_manifest_sha256: str
    runtime_entrypoint_sha256: str
    runtime_pin_path: Path
    runtime_pin_sha256: str
    runtime_route_binding_sha256: str
    runtime_source_sha256: str
    source_manifest_sha256: str
    subscription_runtime_binding_commitment_sha256: str


@final
@dataclass(frozen=True, slots=True)
class RunProviderConfig:
    locomo_dataset: OfficialDatasetConfig
    longmemeval_dataset: OfficialDatasetConfig
    suite: RunSuiteConfig
    extraction_terminal_paths: tuple[Path, Path]
    retrieval_database_path: Path
    retrieval_authority_root_sha256: str
    fleet_pool_id: str
    fleet_bridges: tuple[FleetBridgeConfig, FleetBridgeConfig, FleetBridgeConfig]
    runtime_attestation: RuntimeAttestationConfig
    runtime_authority: RuntimeAuthorityConfig
    output_cipher_key_id: str
    maximum_ciphertext_bytes: int
    maximum_bridge_request_bytes: int
    bridge_connect_timeout_seconds: float
    bridge_read_timeout_seconds: float
    bridge_write_timeout_seconds: float
    lease_duration_ms: int


@final
@dataclass(frozen=True, slots=True, repr=False)
class FleetBridgeSecret:
    bridge_id: str
    authorization_bearer: str = field(repr=False)
    attestation_secret: bytes = field(repr=False)
    launcher_receipt_key: bytes = field(repr=False)


@final
@dataclass(frozen=True, slots=True, repr=False)
class RunProviderSecrets:
    extraction_authentication_keys: tuple[bytes, bytes] = field(repr=False)
    retrieval_authentication_key: bytes = field(repr=False)
    bridge_journal_authentication_key: bytes = field(repr=False)
    output_cipher_key: bytes = field(repr=False)
    runtime_attestation_root_secret: bytes = field(repr=False)
    bridges: tuple[FleetBridgeSecret, FleetBridgeSecret, FleetBridgeSecret] = field(repr=False)

    def __repr__(self) -> str:
        return "RunProviderSecrets(<redacted>)"

    def __reduce_ex__(self, _protocol: int) -> object:
        raise TypeError("RunProviderSecrets contains private material")


def parse_run_provider_inputs(
    inputs: PublishableRunProviderInputs,
) -> tuple[RunProviderConfig, RunProviderSecrets]:
    """Parse the only capability object admitted at the provider boundary."""

    if type(inputs) is not PublishableRunProviderInputs:
        _fail("publishable_run_provider_inputs_invalid")
    inputs.__post_init__()
    config = _config(inputs.adapter_config())
    secrets = _secrets(inputs.adapter_secrets())
    if tuple(item.bridge_id for item in config.fleet_bridges) != tuple(
        item.bridge_id for item in secrets.bridges
    ):
        _fail("publishable_run_provider_fleet_secret_cross_wire")
    all_keys = (
        *secrets.extraction_authentication_keys,
        secrets.retrieval_authentication_key,
        secrets.bridge_journal_authentication_key,
        secrets.output_cipher_key,
        secrets.runtime_attestation_root_secret,
        *(item.attestation_secret for item in secrets.bridges),
        *(item.launcher_receipt_key for item in secrets.bridges),
        *(item.authorization_bearer.encode("utf-8") for item in secrets.bridges),
    )
    if len({bytes(item) for item in all_keys}) != len(all_keys):
        _fail("publishable_run_provider_secret_reuse")
    return config, secrets


def _config(value: dict[str, object]) -> RunProviderConfig:
    root = _object(
        value,
        {
            "extraction",
            "fleet",
            "official_cases",
            "retrieval",
            "runtime",
            "schema_version",
            "suite",
        },
        "config",
    )
    if root["schema_version"] != RUN_PROVIDER_CONFIG_SCHEMA:
        _fail("publishable_run_provider_config_invalid")
    official = _object(root["official_cases"], {"locomo", "longmemeval"}, "official_cases")
    extraction = _object(
        root["extraction"],
        {"locomo_terminal_path", "longmemeval_terminal_path"},
        "extraction",
    )
    retrieval = _object(root["retrieval"], {"authority_root_sha256", "database_path"}, "retrieval")
    fleet = _object(root["fleet"], {"bridges", "pool_id"}, "fleet")
    runtime = _object(
        root["runtime"],
        {
            "attestation",
            "authority",
            "bridge_connect_timeout_seconds",
            "bridge_read_timeout_seconds",
            "bridge_write_timeout_seconds",
            "lease_duration_ms",
            "maximum_bridge_request_bytes",
            "maximum_ciphertext_bytes",
            "output_cipher_key_id",
        },
        "runtime",
    )
    suite = _object(
        root["suite"],
        {
            "dispatch_deadline_unix_ms",
            "dispatch_not_before_unix_ms",
            "infinity_base_url",
            "locomo_run_id",
            "longmemeval_run_id",
            "mem0_base_url",
            "publication_bundle_sha256",
            "source_commit_sha256",
            "suite_id",
        },
        "suite",
    )
    bridges_value = fleet["bridges"]
    if type(bridges_value) is not list or len(bridges_value) != 3:
        _fail("publishable_run_provider_config_invalid")
    bridges = tuple(_fleet_bridge(item) for item in bridges_value)
    if len({item.bridge_id for item in bridges}) != 3:
        _fail("publishable_run_provider_config_invalid")
    before = _integer(suite["dispatch_not_before_unix_ms"], minimum=0)
    deadline = _integer(suite["dispatch_deadline_unix_ms"], minimum=1)
    if deadline <= before:
        _fail("publishable_run_provider_config_invalid")
    config = RunProviderConfig(
        locomo_dataset=_dataset(official["locomo"]),
        longmemeval_dataset=_dataset(official["longmemeval"]),
        suite=RunSuiteConfig(
            suite_id=_identifier(suite["suite_id"]),
            locomo_run_id=_identifier(suite["locomo_run_id"]),
            longmemeval_run_id=_identifier(suite["longmemeval_run_id"]),
            publication_bundle_sha256=_sha(suite["publication_bundle_sha256"]),
            source_commit_sha256=_sha(suite["source_commit_sha256"]),
            infinity_base_url=_loopback_origin(suite["infinity_base_url"]),
            mem0_base_url=_loopback_origin(suite["mem0_base_url"]),
            dispatch_not_before_unix_ms=before,
            dispatch_deadline_unix_ms=deadline,
        ),
        extraction_terminal_paths=(
            _path(extraction["locomo_terminal_path"]),
            _path(extraction["longmemeval_terminal_path"]),
        ),
        retrieval_database_path=_path(retrieval["database_path"]),
        retrieval_authority_root_sha256=_sha(retrieval["authority_root_sha256"]),
        fleet_pool_id=_identifier(fleet["pool_id"]),
        fleet_bridges=bridges,
        runtime_attestation=_runtime_attestation(runtime["attestation"]),
        runtime_authority=_runtime_authority(runtime["authority"]),
        output_cipher_key_id=_identifier(runtime["output_cipher_key_id"]),
        maximum_ciphertext_bytes=_integer(runtime["maximum_ciphertext_bytes"], minimum=1024),
        maximum_bridge_request_bytes=_integer(
            runtime["maximum_bridge_request_bytes"], minimum=1024
        ),
        bridge_connect_timeout_seconds=_seconds(runtime["bridge_connect_timeout_seconds"]),
        bridge_read_timeout_seconds=_seconds(runtime["bridge_read_timeout_seconds"]),
        bridge_write_timeout_seconds=_seconds(runtime["bridge_write_timeout_seconds"]),
        lease_duration_ms=_integer(runtime["lease_duration_ms"], minimum=1),
    )
    _validate_cross_wiring(config)
    return config


def _secrets(value: dict[str, object]) -> RunProviderSecrets:
    root = _object(
        value,
        {
            "bridge_journal_authentication_key_hex",
            "bridges",
            "extraction_authentication_keys_hex",
            "output_cipher_key_hex",
            "retrieval_authentication_key_hex",
            "runtime_attestation_root_secret_hex",
            "schema_version",
        },
        "secrets",
    )
    if root["schema_version"] != RUN_PROVIDER_SECRETS_SCHEMA:
        _fail("publishable_run_provider_secrets_invalid")
    extraction = root["extraction_authentication_keys_hex"]
    bridges_value = root["bridges"]
    if type(extraction) is not list or len(extraction) != 2:
        _fail("publishable_run_provider_secrets_invalid")
    if type(bridges_value) is not list or len(bridges_value) != 3:
        _fail("publishable_run_provider_secrets_invalid")
    return RunProviderSecrets(
        extraction_authentication_keys=tuple(_key(item) for item in extraction),
        retrieval_authentication_key=_key(root["retrieval_authentication_key_hex"]),
        bridge_journal_authentication_key=_key(root["bridge_journal_authentication_key_hex"]),
        output_cipher_key=_key(root["output_cipher_key_hex"], exact=32),
        runtime_attestation_root_secret=_runtime_attestation_key(
            root["runtime_attestation_root_secret_hex"]
        ),
        bridges=tuple(_fleet_secret(item) for item in bridges_value),
    )


def _dataset(value: object) -> OfficialDatasetConfig:
    item = _object(value, {"path", "sha256"}, "dataset")
    return OfficialDatasetConfig(path=_path(item["path"]), sha256=_sha(item["sha256"]))


def _fleet_bridge(value: object) -> FleetBridgeConfig:
    item = _object(
        value,
        {
            "account_binding_hmac_sha256",
            "account_name",
            "bridge_id",
            "origin",
            "readiness_receipt_path",
        },
        "fleet_bridge",
    )
    return FleetBridgeConfig(
        account_name=_identifier(item["account_name"]),
        bridge_id=_identifier(item["bridge_id"]),
        origin=_text(item["origin"]),
        account_binding_hmac_sha256=_sha(item["account_binding_hmac_sha256"]),
        readiness_receipt_path=_path(item["readiness_receipt_path"]),
    )


def _runtime_attestation(value: object) -> RuntimeAttestationConfig:
    item = _object(
        value,
        {
            "endpoint_timeout_seconds",
            "lane_project_name",
            "maximum_age_seconds",
            "public_endpoint",
            "runtime_attestation_directory",
        },
        "runtime_attestation",
    )
    return RuntimeAttestationConfig(
        directory=_path(item["runtime_attestation_directory"]),
        endpoint=_loopback_origin(item["public_endpoint"]),
        endpoint_timeout_seconds=_seconds(item["endpoint_timeout_seconds"]),
        lane_project_name=_identifier(item["lane_project_name"]),
        maximum_age_seconds=_integer(item["maximum_age_seconds"], minimum=1),
    )


def _runtime_authority(value: object) -> RuntimeAuthorityConfig:
    item = _object(
        value,
        {
            "adapter_image_id",
            "codex_executable_sha256",
            "extraction_response_format_sha256",
            "extraction_response_schema_sha256",
            "extraction_system_prompt_sha256",
            "node_executable_sha256",
            "runtime_artifact_manifest_sha256",
            "runtime_entrypoint_sha256",
            "runtime_pin_path",
            "runtime_pin_sha256",
            "runtime_route_binding_sha256",
            "runtime_source_sha256",
            "source_manifest_sha256",
            "subscription_runtime_binding_commitment_sha256",
        },
        "runtime_authority",
    )
    adapter_image = _text(item["adapter_image_id"])
    if re.fullmatch(r"sha256:[0-9a-f]{64}", adapter_image) is None:
        _fail("publishable_run_provider_config_invalid")
    return RuntimeAuthorityConfig(
        adapter_image_id=adapter_image,
        codex_executable_sha256=_sha(item["codex_executable_sha256"]),
        extraction_response_format_sha256=_sha(item["extraction_response_format_sha256"]),
        extraction_response_schema_sha256=_sha(item["extraction_response_schema_sha256"]),
        extraction_system_prompt_sha256=_sha(item["extraction_system_prompt_sha256"]),
        node_executable_sha256=_sha(item["node_executable_sha256"]),
        runtime_artifact_manifest_sha256=_sha(item["runtime_artifact_manifest_sha256"]),
        runtime_entrypoint_sha256=_sha(item["runtime_entrypoint_sha256"]),
        runtime_pin_path=_path(item["runtime_pin_path"]),
        runtime_pin_sha256=_sha(item["runtime_pin_sha256"]),
        runtime_route_binding_sha256=_sha(item["runtime_route_binding_sha256"]),
        runtime_source_sha256=_sha(item["runtime_source_sha256"]),
        source_manifest_sha256=_sha(item["source_manifest_sha256"]),
        subscription_runtime_binding_commitment_sha256=_sha(
            item["subscription_runtime_binding_commitment_sha256"]
        ),
    )


def _validate_cross_wiring(config: RunProviderConfig) -> None:
    attestation = config.runtime_attestation
    lane_root = attestation.directory.parent
    input_paths = (*config.extraction_terminal_paths, config.retrieval_database_path)
    authority = config.runtime_authority
    expected_origins = tuple(f"http://127.0.0.1:{port}" for port in (8891, 8892, 8893))
    readiness_paths = tuple(item.readiness_receipt_path for item in config.fleet_bridges)
    if (
        config.suite.mem0_base_url != attestation.endpoint
        or config.suite.infinity_base_url == config.suite.mem0_base_url
        or lane_root.name != attestation.lane_project_name
        or config.fleet_pool_id != f"{attestation.lane_project_name}-runtime-pool"
        or tuple(item.origin for item in config.fleet_bridges) != expected_origins
        or len({item.account_name for item in config.fleet_bridges}) != 3
        or len(set(readiness_paths)) != 3
        or any(path.name != ".controller-readiness.json" for path in readiness_paths)
        or any(
            path.parent.name != item.account_name
            for path, item in zip(readiness_paths, config.fleet_bridges, strict=True)
        )
        or any(len(path.parents) < 3 or path.parents[2] != lane_root for path in readiness_paths)
        or len({path.parent for path in input_paths}) != 1
        or input_paths[0].parent.parent != lane_root
        or config.locomo_dataset.path.parent != config.longmemeval_dataset.path.parent
        or len(config.locomo_dataset.path.parents) < 2
        or config.locomo_dataset.path.parents[1] != authority.runtime_pin_path.parent
        or config.runtime_attestation.maximum_age_seconds > 7_200
    ):
        _fail("publishable_run_provider_config_cross_wire")


def _fleet_secret(value: object) -> FleetBridgeSecret:
    item = _object(
        value,
        {
            "attestation_secret_hex",
            "authorization_bearer",
            "bridge_id",
            "launcher_receipt_key_hex",
        },
        "fleet_secret",
    )
    bearer = _text(item["authorization_bearer"])
    if "\r" in bearer or "\n" in bearer:
        _fail("publishable_run_provider_secrets_invalid")
    return FleetBridgeSecret(
        bridge_id=_identifier(item["bridge_id"]),
        authorization_bearer=bearer,
        attestation_secret=_key(item["attestation_secret_hex"]),
        launcher_receipt_key=_key(item["launcher_receipt_key_hex"]),
    )


def _object(value: object, keys: set[str], _label: str) -> dict[str, object]:
    if type(value) is not dict or set(value) != keys:
        _fail("publishable_run_provider_config_invalid")
    return value


def _path(value: object) -> Path:
    if type(value) is not str:
        _fail("publishable_run_provider_config_invalid")
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts or path == Path(path.anchor):
        _fail("publishable_run_provider_config_invalid")
    return path


def _identifier(value: object) -> str:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        _fail("publishable_run_provider_config_invalid")
    return value


def _text(value: object) -> str:
    if type(value) is not str or not value or value.strip() != value or len(value) > 4096:
        _fail("publishable_run_provider_config_invalid")
    return value


def _loopback_origin(value: object) -> str:
    origin = _text(value)
    try:
        parsed = urlsplit(origin)
        port = parsed.port
    except ValueError:
        _fail("publishable_run_provider_config_invalid")
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
        _fail("publishable_run_provider_config_invalid")
    return origin


def _sha(value: object) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        _fail("publishable_run_provider_config_invalid")
    return value


def _integer(value: object, *, minimum: int) -> int:
    if type(value) is not int or not minimum <= value <= 9_007_199_254_740_991:
        _fail("publishable_run_provider_config_invalid")
    return value


def _seconds(value: object) -> float:
    if type(value) not in {int, float} or not 0 < float(value) <= 3600:
        _fail("publishable_run_provider_config_invalid")
    return float(value)


def _key(value: object, *, exact: int | None = None) -> bytes:
    if type(value) is not str or len(value) % 2:
        _fail("publishable_run_provider_secrets_invalid")
    try:
        key = bytes.fromhex(value)
    except ValueError:
        _fail("publishable_run_provider_secrets_invalid")
    if (exact is not None and len(key) != exact) or (exact is None and not 32 <= len(key) <= 4096):
        _fail("publishable_run_provider_secrets_invalid")
    return key


def _runtime_attestation_key(value: object) -> bytes:
    key = _key(value)
    try:
        text = key.decode("utf-8")
    except UnicodeDecodeError:
        _fail("publishable_run_provider_secrets_invalid")
    if not text or text != text.strip():
        _fail("publishable_run_provider_secrets_invalid")
    return key


def _fail(code: str) -> None:
    raise PublishableRunError(code) from None


__all__ = (
    "RUN_PROVIDER_CONFIG_SCHEMA",
    "RUN_PROVIDER_SECRETS_SCHEMA",
    "FleetBridgeConfig",
    "FleetBridgeSecret",
    "OfficialDatasetConfig",
    "RunProviderConfig",
    "RunProviderSecrets",
    "RunSuiteConfig",
    "RuntimeAttestationConfig",
    "RuntimeAuthorityConfig",
    "parse_run_provider_inputs",
)

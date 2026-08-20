"""Strict private configuration for publishable input preparation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import final

from infinity_context_runtime_bridge.json_boundary import (
    strict_json_loads,
)
from infinity_context_server.publishable_input_preparation import (
    PUBLISHABLE_INPUT_PROVIDER_CONFIG_BYTES_LIMIT,
    PUBLISHABLE_INPUT_PROVIDER_SECRETS_BYTES_LIMIT,
    PublishableInputPreparationError,
    PublishableInputPreparationProviderInputs,
)

INPUT_PREPARATION_PROVIDER_CONFIG_SCHEMA = "publishable-mem0-infinity-input-preparation.v1"
INPUT_PREPARATION_PROVIDER_SECRETS_SCHEMA = "publishable-mem0-infinity-input-preparation-secrets.v1"

_RUN_NAMES = ("locomo", "longmemeval")
_KEY = re.compile(r"[0-9a-f]{64}\Z")
_RUN_CONFIG_KEYS = {
    "managed_v5_live_config_path",
    "operator_extraction_token_ceiling",
    "operator_total_token_ceiling",
    "strict_keyring_path",
    "strict_receipt_key_path",
    "strict_receipt_path",
    "strict_registration_postgres_dsn_path",
    "strict_request_path",
}
_RUN_SECRET_KEYS = {
    "journal_hmac_key_hex",
    "ledger_hmac_key_hex",
    "operation_receipt_hmac_key_hex",
}


@final
@dataclass(frozen=True, slots=True)
class PublishableInputPreparationRunConfig:
    strict_request_path: Path
    strict_receipt_path: Path
    strict_keyring_path: Path
    strict_receipt_key_path: Path
    strict_registration_postgres_dsn_path: Path
    managed_v5_live_config_path: Path
    operator_extraction_token_ceiling: int
    operator_total_token_ceiling: int

    @property
    def paths(self) -> tuple[Path, ...]:
        return (
            self.strict_request_path,
            self.strict_receipt_path,
            self.strict_keyring_path,
            self.strict_receipt_key_path,
            self.strict_registration_postgres_dsn_path,
            self.managed_v5_live_config_path,
        )


@final
@dataclass(frozen=True, slots=True)
class PublishableInputPreparationProviderConfig:
    fleet_mode: str
    request_timeout_seconds: float
    locomo: PublishableInputPreparationRunConfig
    longmemeval: PublishableInputPreparationRunConfig


@final
@dataclass(frozen=True, slots=True, repr=False)
class PublishableInputPreparationRunSecrets:
    journal_hmac_key: bytes = field(repr=False)
    operation_receipt_hmac_key: bytes = field(repr=False)
    ledger_hmac_key: bytes = field(repr=False)

    @property
    def keys(self) -> tuple[bytes, bytes, bytes]:
        return (
            self.journal_hmac_key,
            self.operation_receipt_hmac_key,
            self.ledger_hmac_key,
        )

    def __repr__(self) -> str:
        return "PublishableInputPreparationRunSecrets(<redacted>)"

    def __reduce_ex__(self, _protocol: int) -> object:
        raise TypeError("publishable input preparation secrets are nonserializable")


@final
@dataclass(frozen=True, slots=True, repr=False)
class PublishableInputPreparationProviderSecrets:
    infinity_auth_token: str = field(repr=False)
    locomo: PublishableInputPreparationRunSecrets = field(repr=False)
    longmemeval: PublishableInputPreparationRunSecrets = field(repr=False)

    def __repr__(self) -> str:
        return "PublishableInputPreparationProviderSecrets(<redacted>)"

    def __reduce_ex__(self, _protocol: int) -> object:
        raise TypeError("publishable input preparation secrets are nonserializable")


def parse_publishable_input_preparation_inputs(
    inputs: PublishableInputPreparationProviderInputs,
) -> tuple[
    PublishableInputPreparationProviderConfig,
    PublishableInputPreparationProviderSecrets,
]:
    """Parse the provider-owned documents without reflecting private material."""

    if type(inputs) is not PublishableInputPreparationProviderInputs:
        _fail("publishable_input_provider_inputs_invalid")
    inputs.__post_init__()
    try:
        config_value = strict_json_loads(
            inputs.input_config_json,
            maximum_bytes=PUBLISHABLE_INPUT_PROVIDER_CONFIG_BYTES_LIMIT,
        )
        secrets_value = strict_json_loads(
            inputs.input_secrets_json,
            maximum_bytes=PUBLISHABLE_INPUT_PROVIDER_SECRETS_BYTES_LIMIT,
        )
        config = _config(config_value)
        secrets = _secrets(secrets_value)
        _validate_paths(config)
        _validate_secret_roles(secrets)
        return config, secrets
    except PublishableInputPreparationError:
        raise
    except Exception:
        _fail("publishable_input_provider_material_invalid")


def _config(value: object) -> PublishableInputPreparationProviderConfig:
    root = _object(
        value,
        {"fleet_mode", "request_timeout_seconds", "runs", "schema_version"},
    )
    if root["schema_version"] != INPUT_PREPARATION_PROVIDER_CONFIG_SCHEMA:
        _fail("publishable_input_provider_config_invalid")
    runs = _object(root["runs"], set(_RUN_NAMES))
    mode = root["fleet_mode"]
    if mode not in {"create", "resume"}:
        _fail("publishable_input_provider_config_invalid")
    return PublishableInputPreparationProviderConfig(
        fleet_mode=mode,
        request_timeout_seconds=_seconds(root["request_timeout_seconds"]),
        locomo=_run_config(runs["locomo"]),
        longmemeval=_run_config(runs["longmemeval"]),
    )


def _run_config(value: object) -> PublishableInputPreparationRunConfig:
    item = _object(value, _RUN_CONFIG_KEYS)
    extraction_ceiling = _tokens(item["operator_extraction_token_ceiling"])
    total_ceiling = _tokens(item["operator_total_token_ceiling"])
    if total_ceiling < extraction_ceiling:
        _fail("publishable_input_provider_config_invalid")
    return PublishableInputPreparationRunConfig(
        strict_request_path=_path(item["strict_request_path"]),
        strict_receipt_path=_path(item["strict_receipt_path"]),
        strict_keyring_path=_path(item["strict_keyring_path"]),
        strict_receipt_key_path=_path(item["strict_receipt_key_path"]),
        strict_registration_postgres_dsn_path=_path(item["strict_registration_postgres_dsn_path"]),
        managed_v5_live_config_path=_path(item["managed_v5_live_config_path"]),
        operator_extraction_token_ceiling=extraction_ceiling,
        operator_total_token_ceiling=total_ceiling,
    )


def _secrets(value: object) -> PublishableInputPreparationProviderSecrets:
    root = _object(value, {"infinity_auth_token", "runs", "schema_version"})
    if root["schema_version"] != INPUT_PREPARATION_PROVIDER_SECRETS_SCHEMA:
        _fail("publishable_input_provider_secrets_invalid")
    runs = _object(root["runs"], set(_RUN_NAMES))
    return PublishableInputPreparationProviderSecrets(
        infinity_auth_token=_token(root["infinity_auth_token"]),
        locomo=_run_secrets(runs["locomo"]),
        longmemeval=_run_secrets(runs["longmemeval"]),
    )


def _run_secrets(value: object) -> PublishableInputPreparationRunSecrets:
    item = _object(value, _RUN_SECRET_KEYS)
    return PublishableInputPreparationRunSecrets(
        journal_hmac_key=_key(item["journal_hmac_key_hex"]),
        operation_receipt_hmac_key=_key(item["operation_receipt_hmac_key_hex"]),
        ledger_hmac_key=_key(item["ledger_hmac_key_hex"]),
    )


def _validate_paths(config: PublishableInputPreparationProviderConfig) -> None:
    runs = (config.locomo, config.longmemeval)
    if any(len(set(item.paths)) != len(item.paths) for item in runs):
        _fail("publishable_input_provider_path_cross_wire")
    locomo_shared = config.locomo.strict_registration_postgres_dsn_path
    longmemeval_shared = config.longmemeval.strict_registration_postgres_dsn_path
    locomo_unique = set(config.locomo.paths) - {locomo_shared}
    longmemeval_unique = set(config.longmemeval.paths) - {longmemeval_shared}
    if (
        locomo_unique & longmemeval_unique
        or locomo_shared in longmemeval_unique
        or longmemeval_shared in locomo_unique
    ):
        _fail("publishable_input_provider_path_cross_wire")


def _validate_secret_roles(secrets: PublishableInputPreparationProviderSecrets) -> None:
    values = (*secrets.locomo.keys, *secrets.longmemeval.keys)
    if len(set(values)) != len(values) or secrets.infinity_auth_token.encode("utf-8") in values:
        _fail("publishable_input_provider_secret_reuse")


def _object(value: object, keys: set[str]) -> dict[str, object]:
    if type(value) is not dict or set(value) != keys:
        _fail("publishable_input_provider_material_invalid")
    return value


def _path(value: object) -> Path:
    if type(value) is not str:
        _fail("publishable_input_provider_config_invalid")
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts or path == Path(path.anchor):
        _fail("publishable_input_provider_config_invalid")
    return path


def _seconds(value: object) -> float:
    if type(value) not in {int, float} or not 0.01 <= float(value) <= 120.0:
        _fail("publishable_input_provider_config_invalid")
    return float(value)


def _tokens(value: object) -> int:
    if type(value) is not int or not 1 <= value <= 2_000_000_000:
        _fail("publishable_input_provider_config_invalid")
    return value


def _key(value: object) -> bytes:
    if type(value) is not str or _KEY.fullmatch(value) is None:
        _fail("publishable_input_provider_secrets_invalid")
    return bytes.fromhex(value)


def _token(value: object) -> str:
    if (
        type(value) is not str
        or value.strip() != value
        or any(character in value for character in "\x00\r\n")
        or not 32 <= len(value.encode("utf-8")) <= 4096
    ):
        _fail("publishable_input_provider_secrets_invalid")
    return value


def _fail(code: str) -> None:
    raise PublishableInputPreparationError(code) from None


__all__ = (
    "INPUT_PREPARATION_PROVIDER_CONFIG_SCHEMA",
    "INPUT_PREPARATION_PROVIDER_SECRETS_SCHEMA",
    "PublishableInputPreparationProviderConfig",
    "PublishableInputPreparationProviderSecrets",
    "PublishableInputPreparationRunConfig",
    "PublishableInputPreparationRunSecrets",
    "parse_publishable_input_preparation_inputs",
)

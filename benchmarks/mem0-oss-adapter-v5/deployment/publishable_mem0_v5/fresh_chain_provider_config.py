"""Strict provider documents for the production fresh-chain canary."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import final

from infinity_context_server.publishable_durable_scheduler.publishable_run_contracts import (
    PublishableRunError,
    PublishableRunProviderInputs,
)

from .run_provider_config import (
    RunProviderConfig,
    RunProviderSecrets,
    parse_run_provider_inputs,
)

FRESH_CHAIN_PROVIDER_CONFIG_SCHEMA = "publishable-mem0-infinity-fresh-chain-provider.v1"
FRESH_CHAIN_PROVIDER_SECRETS_SCHEMA = "publishable-mem0-infinity-fresh-chain-provider-secrets.v1"

_KEY = re.compile(r"[0-9a-f]{64}\Z")


@final
@dataclass(frozen=True, slots=True)
class FreshChainProviderConfig:
    run: RunProviderConfig
    managed_v5_live_config_path: Path
    infinity_retrieval_database_path: Path
    current_date: str
    request_timeout_seconds: float
    operator_extraction_token_ceiling: int
    operator_total_token_ceiling: int


@final
@dataclass(frozen=True, slots=True, repr=False)
class FreshChainProviderSecrets:
    run: RunProviderSecrets = field(repr=False)
    one_shot_hmac_key: bytes = field(repr=False)
    infinity_auth_token: str = field(repr=False)

    def __repr__(self) -> str:
        return "FreshChainProviderSecrets(<redacted>)"

    def __reduce_ex__(self, _protocol: int) -> object:
        raise TypeError("FreshChainProviderSecrets contains private material")


def parse_fresh_chain_provider_inputs(
    inputs: PublishableRunProviderInputs,
) -> tuple[FreshChainProviderConfig, FreshChainProviderSecrets]:
    """Parse a fresh-chain envelope while reusing the reviewed run-provider parser."""

    if type(inputs) is not PublishableRunProviderInputs:
        _fail("fresh_chain_provider_inputs_invalid")
    inputs.__post_init__()
    config_root = _object(
        inputs.adapter_config(),
        {"fresh_chain", "run_provider", "schema_version"},
    )
    secrets_root = _object(
        inputs.adapter_secrets(),
        {
            "fresh_chain",
            "run_provider",
            "schema_version",
        },
    )
    if (
        config_root["schema_version"] != FRESH_CHAIN_PROVIDER_CONFIG_SCHEMA
        or secrets_root["schema_version"] != FRESH_CHAIN_PROVIDER_SECRETS_SCHEMA
    ):
        _fail("fresh_chain_provider_schema_invalid")
    run_inputs = PublishableRunProviderInputs(
        state_root=inputs.state_root,
        adapter_config_json=_canonical(config_root["run_provider"]),
        adapter_secrets_json=_canonical(secrets_root["run_provider"]),
    )
    run_config, run_secrets = parse_run_provider_inputs(run_inputs)
    fresh = _object(
        config_root["fresh_chain"],
        {
            "current_date",
            "managed_v5_live_config_path",
            "infinity_retrieval_database_path",
            "operator_extraction_ceiling",
            "operator_total_ceiling",
            "request_timeout_seconds",
        },
    )
    fresh_secrets = _object(
        secrets_root["fresh_chain"],
        {"infinity_auth_token", "one_shot_hmac_key_hex"},
    )
    # The outer publishable config loader rejects secret-looking configuration
    # field names, including the substring ``token``.  These public numeric
    # ceilings therefore use deliberately secret-neutral document names.
    extraction_ceiling = _tokens(
        fresh["operator_extraction_ceiling"], minimum=4_096, maximum=10_000_000
    )
    total_ceiling = _tokens(fresh["operator_total_ceiling"], maximum=50_000_000)
    if total_ceiling < extraction_ceiling:
        _fail("fresh_chain_provider_config_invalid")
    config = FreshChainProviderConfig(
        run=run_config,
        managed_v5_live_config_path=_path(fresh["managed_v5_live_config_path"]),
        infinity_retrieval_database_path=_path(fresh["infinity_retrieval_database_path"]),
        current_date=_date(fresh["current_date"]),
        request_timeout_seconds=_seconds(fresh["request_timeout_seconds"]),
        operator_extraction_token_ceiling=extraction_ceiling,
        operator_total_token_ceiling=total_ceiling,
    )
    secrets = FreshChainProviderSecrets(
        run=run_secrets,
        one_shot_hmac_key=_key(fresh_secrets["one_shot_hmac_key_hex"]),
        infinity_auth_token=_bearer(fresh_secrets["infinity_auth_token"]),
    )
    _validate_secret_roles(secrets)
    return config, secrets


def _validate_secret_roles(secrets: FreshChainProviderSecrets) -> None:
    run = secrets.run
    old = (
        *run.extraction_authentication_keys,
        run.retrieval_authentication_key,
        run.bridge_journal_authentication_key,
        run.output_cipher_key,
        run.runtime_attestation_root_secret,
        *(item.attestation_secret for item in run.bridges),
        *(item.launcher_receipt_key for item in run.bridges),
        *(item.authorization_bearer.encode() for item in run.bridges),
    )
    values = (*old, secrets.one_shot_hmac_key, secrets.infinity_auth_token.encode())
    if len(set(values)) != len(values):
        _fail("fresh_chain_provider_secret_reuse")


def _object(value: object, keys: set[str]) -> dict[str, object]:
    if type(value) is not dict or set(value) != keys:
        _fail("fresh_chain_provider_material_invalid")
    return value


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    except (TypeError, ValueError):
        _fail("fresh_chain_provider_material_invalid")


def _path(value: object) -> Path:
    if type(value) is not str:
        _fail("fresh_chain_provider_config_invalid")
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts or path == Path(path.anchor):
        _fail("fresh_chain_provider_config_invalid")
    return path


def _date(value: object) -> str:
    if type(value) is not str:
        _fail("fresh_chain_provider_config_invalid")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        _fail("fresh_chain_provider_config_invalid")
    if parsed.isoformat() != value:
        _fail("fresh_chain_provider_config_invalid")
    return value


def _seconds(value: object) -> float:
    if type(value) not in {int, float} or not 0.01 <= float(value) <= 120.0:
        _fail("fresh_chain_provider_config_invalid")
    return float(value)


def _tokens(value: object, *, minimum: int = 1, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _fail("fresh_chain_provider_config_invalid")
    return value


def _key(value: object) -> bytes:
    if type(value) is not str or _KEY.fullmatch(value) is None:
        _fail("fresh_chain_provider_secrets_invalid")
    return bytes.fromhex(value)


def _bearer(value: object) -> str:
    if type(value) is not str or not 16 <= len(value) <= 8192 or any(ch.isspace() for ch in value):
        _fail("fresh_chain_provider_secrets_invalid")
    return value


def _fail(code: str) -> None:
    raise PublishableRunError(code) from None


__all__ = (
    "FRESH_CHAIN_PROVIDER_CONFIG_SCHEMA",
    "FRESH_CHAIN_PROVIDER_SECRETS_SCHEMA",
    "FreshChainProviderConfig",
    "FreshChainProviderSecrets",
    "parse_fresh_chain_provider_inputs",
)

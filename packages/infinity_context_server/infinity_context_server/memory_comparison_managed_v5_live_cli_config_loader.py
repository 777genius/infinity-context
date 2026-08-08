"""Strict public JSON loader for the managed-v5 live CLI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import final

from infinity_context_server.memory_comparison_managed_v5_live_cli_composition import (
    ManagedV5LiveCliCompositionRequest,
)
from infinity_context_server.memory_comparison_managed_v5_live_config import (
    ManagedV5LiveConfig,
    ManagedV5LiveFilesystemConfig,
    ManagedV5LiveRuntimeConfig,
)

_MAX_CONFIG_BYTES = 128 * 1024
_FILESYSTEM_DIGEST_KEYS = frozenset(
    {
        "evidence_key_sha256",
        "runtime_authority_sha256",
        "runtime_artifact_manifest_sha256",
        "node_executable_sha256",
    }
)
_FILESYSTEM_KEYS = frozenset(
    {
        "state_root",
        "secret_root",
        "report_root",
        "report_file",
        "dispatch_journal",
        "operation_journal",
        "durable_clean_state",
        "ingress_bearer_file",
        "evidence_key_file",
        "evidence_key_sha256",
        "receipt_secret_file",
        "checkpoint_signing_key_file",
        "checkpoint_head_key_file",
        "operation_journal_signer_secret_file",
        "durable_clean_state_hmac_secret_file",
        "runtime_authority_file",
        "runtime_authority_sha256",
        "phase_c_package_root",
        "runtime_repo",
        "runtime_artifact_manifest",
        "runtime_artifact_manifest_sha256",
        "node_executable",
        "node_executable_sha256",
    }
)


@final
class ManagedV5LiveCliConfigLoaderError(ValueError):
    __slots__ = ()


def load_managed_v5_live_cli_config(
    path: Path,
) -> tuple[ManagedV5LiveConfig, Path, str]:
    """Load one strict public-only document without reading secret contents."""

    try:
        if not isinstance(path, Path) or not path.is_absolute() or path.is_symlink():
            raise TypeError
        with path.open("rb") as handle:
            raw = handle.read(_MAX_CONFIG_BYTES + 1)
        if not raw or len(raw) > _MAX_CONFIG_BYTES:
            raise TypeError
        payload = json.loads(raw, object_pairs_hook=_unique_object)
        if type(payload) is not dict or set(payload) != {
            "filesystem",
            "runtime",
            "extraction_contract_file",
            "extraction_contract_sha256",
        }:
            raise TypeError
        filesystem = payload["filesystem"]
        runtime = payload["runtime"]
        if type(filesystem) is not dict or set(filesystem) != _FILESYSTEM_KEYS:
            raise TypeError
        if type(runtime) is not dict or set(runtime) != {"mem0_adapter_origin"}:
            raise TypeError
        path_fields = _FILESYSTEM_KEYS - _FILESYSTEM_DIGEST_KEYS
        filesystem_config = ManagedV5LiveFilesystemConfig(
            **{
                key: Path(value) if key in path_fields and type(value) is str else value
                for key, value in filesystem.items()
            }
        )
        config = ManagedV5LiveConfig(
            filesystem=filesystem_config,
            runtime=ManagedV5LiveRuntimeConfig(**runtime),
        )
        extraction_file = Path(payload["extraction_contract_file"])
        extraction_sha256 = payload["extraction_contract_sha256"]
        if not extraction_file.is_absolute() or not _is_sha256(extraction_sha256):
            raise TypeError
        return config, extraction_file, extraction_sha256
    except Exception:
        raise ManagedV5LiveCliConfigLoaderError from None


def build_managed_v5_live_cli_composition_request(
    config: object,
) -> ManagedV5LiveCliCompositionRequest:
    """Project a validated CLI config into the narrower v5 root DTO."""

    try:
        return ManagedV5LiveCliCompositionRequest(
            dataset_path=config.dataset_path,
            profile_id=config.profile_id,
            selected_case_ids=config.selected_case_ids,
            run_id=config.run_id,
            infinity_api_url=config.infinity_api_url,
            mem0_api_url=config.mem0_api_url,
            subscription_runtime_url=config.subscription_runtime_url,
            max_extraction_tokens=config.max_extraction_tokens,
            max_total_tokens=config.max_total_tokens,
            mem0_runtime_implementation_sha256=config.mem0_runtime_implementation_sha256,
            managed_v5_config=config.managed_v5_config,
            extraction_contract_file=config.extraction_contract_file,
            extraction_contract_sha256=config.extraction_contract_sha256,
            mem0_local_auth_disabled_managed=config.mem0_local_auth_disabled_managed,
            mem0_oss_ingress_protected=config.mem0_oss_ingress_protected,
            allowed_mem0_hosts=config.allowed_mem0_hosts,
            connect_timeout_seconds=config.connect_timeout_seconds,
            request_timeout_seconds=config.request_timeout_seconds,
            run_timeout_seconds=config.run_timeout_seconds,
        )
    except (AttributeError, TypeError, ValueError):
        raise ManagedV5LiveCliConfigLoaderError from None


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _is_sha256(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


__all__ = (
    "ManagedV5LiveCliConfigLoaderError",
    "build_managed_v5_live_cli_composition_request",
    "load_managed_v5_live_cli_config",
)

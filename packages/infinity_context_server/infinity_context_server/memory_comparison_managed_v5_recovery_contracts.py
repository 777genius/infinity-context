"""Strict public contracts for managed-v5 live recovery."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import math
from dataclasses import dataclass, fields
from datetime import date, datetime
from pathlib import Path
from typing import final
from urllib.parse import urlsplit

from infinity_context_server.memory_comparison_managed_http_lifecycle import (
    managed_http_lifecycle_space_slug,
)
from infinity_context_server.memory_comparison_managed_preflight import (
    managed_backend_target_identity_sha256,
)

AUTHORITY_SCHEMA = "managed-v5-live-recovery-authority.v1"
JOURNAL_SCHEMA = "managed-v5-live-recovery-journal.v1"
_SHA = frozenset("0123456789abcdef")


class ManagedV5LiveRecoveryContractError(ValueError):
    """Stable failure which never contains authority or journal material."""


class _DuplicateKey(ValueError):
    pass


def canonical_json(value: object) -> bytes:
    """Render the sole canonical representation used by recovery contracts."""

    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError):
        _fail()


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def managed_v5_live_config_commitment_sha256(
    *,
    config: object,
    extraction_contract_file: Path,
    extraction_contract_sha256: str,
) -> str:
    """Commit the exact typed public config independently of source JSON formatting."""

    from infinity_context_server.memory_comparison_managed_v5_live_config import (
        ManagedV5LiveConfig,
    )

    if (
        type(config) is not ManagedV5LiveConfig
        or not isinstance(extraction_contract_file, Path)
        or not extraction_contract_file.is_absolute()
        or not _sha(extraction_contract_sha256)
    ):
        _fail()
    filesystem: dict[str, object] = {}
    for field in fields(config.filesystem):
        value = getattr(config.filesystem, field.name)
        filesystem[field.name] = str(value) if isinstance(value, Path) else value
    return canonical_sha256(
        {
            "schema_version": "managed-v5-live-config-commitment.v1",
            "filesystem": filesystem,
            "runtime": {"mem0_adapter_origin": config.runtime.mem0_adapter_origin},
            "extraction_contract_file": str(extraction_contract_file),
            "extraction_contract_sha256": extraction_contract_sha256,
        }
    )


def strict_json(raw: bytes) -> object:
    if type(raw) is not bytes:
        _fail()
    try:
        return json.loads(raw, object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError, _DuplicateKey):
        _fail()


@final
@dataclass(frozen=True, slots=True)
class ManagedV5LiveRecoveryAuthority:
    run_id: str
    run_id_sha256: str
    binding_commitment_sha256: str
    infinity_target_identity_sha256: str
    space_slug: str
    profile_id: str
    selected_case_ids: tuple[str, ...]
    current_date: str
    issued_at: str
    deadline: str
    run_nonce_commitment_sha256: str
    runtime_probe_nonce_sha256: str
    dataset_path: Path
    dataset_sha256: str
    managed_v5_config_commitment_sha256: str
    extraction_contract_file: Path
    extraction_contract_sha256: str
    infinity_origin: str
    mem0_origin: str
    max_extraction_tokens: int
    max_total_tokens: int
    mem0_runtime_implementation_sha256: str
    mem0_local_auth_disabled_managed: bool
    mem0_oss_ingress_protected: bool
    allowed_mem0_hosts: tuple[str, ...]
    connect_timeout_seconds: float
    request_timeout_seconds: float
    run_timeout_seconds: float
    adapter_runtime_pin_sha256: str
    state_root: Path
    checkpoint_file: Path
    checkpoint_head_file: Path
    dispatch_journal: Path
    operation_journal: Path
    durable_clean_state: Path
    schema_version: str = AUTHORITY_SCHEMA

    def __post_init__(self) -> None:
        digests = (
            self.run_id_sha256,
            self.binding_commitment_sha256,
            self.infinity_target_identity_sha256,
            self.run_nonce_commitment_sha256,
            self.runtime_probe_nonce_sha256,
            self.dataset_sha256,
            self.managed_v5_config_commitment_sha256,
            self.extraction_contract_sha256,
            self.mem0_runtime_implementation_sha256,
            self.adapter_runtime_pin_sha256,
        )
        text = (
            self.run_id,
            self.profile_id,
            self.current_date,
            self.infinity_origin,
            self.mem0_origin,
        )
        paths = (
            self.dataset_path,
            self.extraction_contract_file,
            self.state_root,
            self.checkpoint_file,
            self.checkpoint_head_file,
            self.dispatch_journal,
            self.operation_journal,
            self.durable_clean_state,
        )
        if (
            self.schema_version != AUTHORITY_SCHEMA
            or any(not _text(value) for value in text)
            or any(not _sha(value) for value in digests)
            or type(self.selected_case_ids) is not tuple
            or not self.selected_case_ids
            or any(not _text(value) for value in self.selected_case_ids)
            or len(set(self.selected_case_ids)) != len(self.selected_case_ids)
            or type(self.allowed_mem0_hosts) is not tuple
            or not self.allowed_mem0_hosts
            or any(not _text(value) for value in self.allowed_mem0_hosts)
            or len(set(self.allowed_mem0_hosts)) != len(self.allowed_mem0_hosts)
            or any(not isinstance(value, Path) or not value.is_absolute() for value in paths)
            or any(
                type(value) is not bool
                for value in (
                    self.mem0_local_auth_disabled_managed,
                    self.mem0_oss_ingress_protected,
                )
            )
            or any(
                type(value) is not int or value < 1
                for value in (self.max_extraction_tokens, self.max_total_tokens)
            )
            or self.max_total_tokens < self.max_extraction_tokens
            or any(
                not _positive_finite(value)
                for value in (
                    self.connect_timeout_seconds,
                    self.request_timeout_seconds,
                    self.run_timeout_seconds,
                )
            )
            or not _rfc3339(self.issued_at)
            or not _rfc3339(self.deadline)
            or not _iso_date(self.current_date)
            or self.current_date
            != datetime.fromisoformat(self.issued_at.replace("Z", "+00:00")).date().isoformat()
            or not _loopback_origin(self.infinity_origin)
            or not _loopback_origin(self.mem0_origin)
            or datetime.fromisoformat(self.deadline.replace("Z", "+00:00"))
            <= datetime.fromisoformat(self.issued_at.replace("Z", "+00:00"))
            or hashlib.sha256(self.run_id.encode()).hexdigest() != self.run_id_sha256
            or managed_http_lifecycle_space_slug(self.run_id) != self.space_slug
            or managed_backend_target_identity_sha256(
                backend_role="infinity-context", base_url=self.infinity_origin
            )
            != self.infinity_target_identity_sha256
            or any(
                path.parent != self.state_root
                for path in (
                    self.checkpoint_file,
                    self.checkpoint_head_file,
                    self.dispatch_journal,
                    self.operation_journal,
                    self.durable_clean_state,
                )
            )
            or len(
                {
                    self.checkpoint_file,
                    self.checkpoint_head_file,
                    self.dispatch_journal,
                    self.operation_journal,
                    self.durable_clean_state,
                }
            )
            != 5
        ):
            _fail()

    def payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "run_id_sha256": self.run_id_sha256,
            "binding_commitment_sha256": self.binding_commitment_sha256,
            "infinity_target_identity_sha256": self.infinity_target_identity_sha256,
            "space_slug": self.space_slug,
            "profile_id": self.profile_id,
            "selected_case_ids": list(self.selected_case_ids),
            "current_date": self.current_date,
            "issued_at": self.issued_at,
            "deadline": self.deadline,
            "run_nonce_commitment_sha256": self.run_nonce_commitment_sha256,
            "runtime_probe_nonce_sha256": self.runtime_probe_nonce_sha256,
            "dataset_path": str(self.dataset_path),
            "dataset_sha256": self.dataset_sha256,
            "managed_v5_config_commitment_sha256": self.managed_v5_config_commitment_sha256,
            "extraction_contract_file": str(self.extraction_contract_file),
            "extraction_contract_sha256": self.extraction_contract_sha256,
            "infinity_origin": self.infinity_origin,
            "mem0_origin": self.mem0_origin,
            "max_extraction_tokens": self.max_extraction_tokens,
            "max_total_tokens": self.max_total_tokens,
            "mem0_runtime_implementation_sha256": self.mem0_runtime_implementation_sha256,
            "mem0_local_auth_disabled_managed": self.mem0_local_auth_disabled_managed,
            "mem0_oss_ingress_protected": self.mem0_oss_ingress_protected,
            "allowed_mem0_hosts": list(self.allowed_mem0_hosts),
            "connect_timeout_seconds": self.connect_timeout_seconds,
            "request_timeout_seconds": self.request_timeout_seconds,
            "run_timeout_seconds": self.run_timeout_seconds,
            "adapter_runtime_pin_sha256": self.adapter_runtime_pin_sha256,
            "state_root": str(self.state_root),
            "checkpoint_file": str(self.checkpoint_file),
            "checkpoint_head_file": str(self.checkpoint_head_file),
            "dispatch_journal": str(self.dispatch_journal),
            "operation_journal": str(self.operation_journal),
            "durable_clean_state": str(self.durable_clean_state),
        }

    @property
    def sha256(self) -> str:
        return canonical_sha256(self.payload())


def parse_recovery_authority(value: object) -> ManagedV5LiveRecoveryAuthority:
    if type(value) is not dict or set(value) != set(_AUTHORITY_KEYS):
        _fail()
    raw = dict(value)
    raw["selected_case_ids"] = _tuple(raw["selected_case_ids"])
    raw["allowed_mem0_hosts"] = _tuple(raw["allowed_mem0_hosts"])
    for key in _PATH_KEYS:
        if type(raw[key]) is not str:
            _fail()
        raw[key] = Path(raw[key])
    try:
        return ManagedV5LiveRecoveryAuthority(**raw)
    except (TypeError, ValueError):
        _fail()


_PATH_KEYS = frozenset(
    {
        "dataset_path",
        "extraction_contract_file",
        "state_root",
        "checkpoint_file",
        "checkpoint_head_file",
        "dispatch_journal",
        "operation_journal",
        "durable_clean_state",
    }
)
_AUTHORITY_KEYS = tuple(ManagedV5LiveRecoveryAuthority.__dataclass_fields__)


def _tuple(value: object) -> tuple[str, ...]:
    if type(value) is not list:
        _fail()
    return tuple(value)


def _text(value: object) -> bool:
    return type(value) is str and bool(value) and value == value.strip() and len(value) <= 4096


def _sha(value: object) -> bool:
    return type(value) is str and len(value) == 64 and set(value) <= _SHA


def _rfc3339(value: object) -> bool:
    if type(value) is not str or not value.endswith("Z"):
        return False
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return parsed.utcoffset() is not None and parsed.isoformat().endswith("+00:00")


def _iso_date(value: object) -> bool:
    try:
        return type(value) is str and date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _loopback_origin(value: object) -> bool:
    if type(value) is not str:
        return False
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        port = parsed.port
        return (
            parsed.scheme == "http"
            and host is not None
            and ipaddress.ip_address(host).is_loopback
            and port is not None
            and 1 <= port <= 65_535
            and not parsed.path
            and not parsed.query
            and not parsed.fragment
            and parsed.username is None
            and parsed.password is None
        )
    except (TypeError, ValueError):
        return False


def _positive_finite(value: object) -> bool:
    return (
        type(value) in {int, float}
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    )


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey
        result[key] = value
    return result


def _fail() -> None:
    raise ManagedV5LiveRecoveryContractError("managed_v5_live_recovery_contract_invalid")


__all__ = (
    "AUTHORITY_SCHEMA",
    "JOURNAL_SCHEMA",
    "ManagedV5LiveRecoveryAuthority",
    "ManagedV5LiveRecoveryContractError",
    "canonical_json",
    "canonical_sha256",
    "managed_v5_live_config_commitment_sha256",
    "parse_recovery_authority",
    "strict_json",
)

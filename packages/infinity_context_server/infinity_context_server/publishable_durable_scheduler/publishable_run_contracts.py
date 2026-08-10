"""Provider-neutral inputs for the installed resumable publishable-run root."""

from __future__ import annotations

import os
import re
import stat
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, final

from infinity_context_server.features.subscription_runtime_bridge import (
    BridgeJournal,
    BridgeSecretCapability,
    BridgeTransportPort,
    OutputCipherPort,
)
from infinity_context_server.features.subscription_runtime_bridge.json_boundary import (
    canonical_json_bytes,
    strict_json_loads,
)
from infinity_context_server.features.subscription_runtime_bridge.process_contracts import (
    BridgeFleetReadinessReceipt,
)
from infinity_context_server.processes.publishable_full_extraction_suite import (
    PublishableExtractionSuiteReadback,
)
from infinity_context_server.public_benchmark_models import PublicBenchmarkCase
from infinity_context_server.publishable_durable_scheduler import (
    publishable_production_composition,
)
from infinity_context_server.publishable_durable_scheduler.contracts import (
    SchedulerRunAuthority,
    SchedulerSuiteAuthority,
)
from infinity_context_server.publishable_durable_scheduler.runner_request_composition import (
    SchedulerRetrievalEvidenceReaderPort,
)

PUBLISHABLE_RUN_CONFIG_SCHEMA = "memory-comparison-publishable-run-config.v1"
PUBLISHABLE_RUN_SECRETS_SCHEMA = "memory-comparison-publishable-run-secrets.v1"
PUBLISHABLE_RUN_DEPENDENCY_ENTRYPOINT_GROUP = "infinity_context.publishable_run_dependencies"
PUBLISHABLE_RUN_CONFIG_BYTES_LIMIT = 1024 * 1024
PUBLISHABLE_RUN_SECRETS_BYTES_LIMIT = 1024 * 1024

_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}\Z")


class PublishableRunError(RuntimeError):
    """Stable outer-boundary rejection which never includes private values."""

    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@final
@dataclass(frozen=True, slots=True, repr=False)
class PublishableRunConfig:
    """Public structure loaded from one private operator-owned config file."""

    dependency_provider: str
    official_case_authority_path: Path
    scheduler_database_paths: tuple[Path, Path]
    suite_seal_database_path: Path
    publication_receipt_path: Path
    publication_key_id: str
    max_dispatches_per_batch: int
    adapter_config_json: bytes = field(repr=False)

    def __post_init__(self) -> None:
        paths = (
            self.official_case_authority_path,
            *self.scheduler_database_paths,
            self.suite_seal_database_path,
            self.publication_receipt_path,
        )
        if (
            not _identifier(self.dependency_provider)
            or not _identifier(self.publication_key_id)
            or type(self.scheduler_database_paths) is not tuple
            or len(self.scheduler_database_paths) != 2
            or any(not isinstance(path, Path) for path in paths)
            or len(set(paths)) != len(paths)
            or type(self.max_dispatches_per_batch) is not int
            or not 1 <= self.max_dispatches_per_batch <= 8_160
            or type(self.adapter_config_json) is not bytes
        ):
            _fail("publishable_run_config_invalid")
        _decoded_object(self.adapter_config_json, code="publishable_run_adapter_config_invalid")

    def adapter_config(self) -> dict[str, Any]:
        return _decoded_object(
            self.adapter_config_json,
            code="publishable_run_adapter_config_invalid",
        )

    def __repr__(self) -> str:
        return (
            "PublishableRunConfig("
            f"dependency_provider={self.dependency_provider!r}, "
            f"publication_key_id={self.publication_key_id!r}, "
            f"max_dispatches_per_batch={self.max_dispatches_per_batch!r}, "
            "paths=<private>, adapter_config=<private>)"
        )


@final
@dataclass(frozen=True, slots=True, repr=False)
class PublishableRunSecrets:
    """Domain-separated outer keys plus opaque adapter secrets."""

    official_case_authentication_key: bytes = field(repr=False)
    scheduler_authentication_keys: tuple[bytes, bytes] = field(repr=False)
    suite_seal_authentication_key: bytes = field(repr=False)
    publication_receipt_authentication_key: bytes = field(repr=False)
    adapter_secrets_json: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if (
            type(self.scheduler_authentication_keys) is not tuple
            or len(self.scheduler_authentication_keys) != 2
        ):
            _fail("publishable_run_secrets_invalid")
        keys = (
            self.official_case_authentication_key,
            *self.scheduler_authentication_keys,
            self.suite_seal_authentication_key,
            self.publication_receipt_authentication_key,
        )
        if (
            any(type(key) is not bytes or not 32 <= len(key) <= 1024 for key in keys)
            or len(set(keys)) != len(keys)
            or type(self.adapter_secrets_json) is not bytes
        ):
            _fail("publishable_run_secrets_invalid")
        _decoded_object(self.adapter_secrets_json, code="publishable_run_adapter_secrets_invalid")

    def adapter_secrets(self) -> dict[str, Any]:
        return _decoded_object(
            self.adapter_secrets_json,
            code="publishable_run_adapter_secrets_invalid",
        )

    def __repr__(self) -> str:
        return "PublishableRunSecrets(keys=<redacted>, adapter_secrets=<redacted>)"


@final
@dataclass(frozen=True, slots=True, repr=False)
class PublishableRunProviderInputs:
    """Provider-owned state and opaque adapter material, never publication authority."""

    state_root: Path = field(repr=False)
    adapter_config_json: bytes = field(repr=False)
    adapter_secrets_json: bytes = field(repr=False)

    def __post_init__(self) -> None:
        try:
            state = self.state_root.lstat()
            resolved = self.state_root.resolve(strict=True)
        except (AttributeError, OSError):
            _fail("publishable_run_provider_inputs_invalid")
        if (
            not isinstance(self.state_root, Path)
            or not self.state_root.is_absolute()
            or ".." in self.state_root.parts
            or resolved != self.state_root
            or stat.S_ISLNK(state.st_mode)
            or not stat.S_ISDIR(state.st_mode)
            or state.st_uid != os.geteuid()
            or stat.S_IMODE(state.st_mode) != 0o700
            or type(self.adapter_config_json) is not bytes
            or type(self.adapter_secrets_json) is not bytes
        ):
            _fail("publishable_run_provider_inputs_invalid")
        _decoded_object(
            self.adapter_config_json,
            code="publishable_run_adapter_config_invalid",
        )
        _decoded_object(
            self.adapter_secrets_json,
            code="publishable_run_adapter_secrets_invalid",
        )

    def adapter_config(self) -> dict[str, Any]:
        return _decoded_object(
            self.adapter_config_json,
            code="publishable_run_adapter_config_invalid",
        )

    def adapter_secrets(self) -> dict[str, Any]:
        return _decoded_object(
            self.adapter_secrets_json,
            code="publishable_run_adapter_secrets_invalid",
        )

    def __repr__(self) -> str:
        return "PublishableRunProviderInputs(state_root=<private>, adapter_material=<private>)"

    def __reduce_ex__(self, _protocol: int) -> object:
        raise TypeError("PublishableRunProviderInputs contains private material")


@final
@dataclass(frozen=True, slots=True, repr=False)
class PublishableProjectedOfficialCase:
    """One exact projected case; evaluator material stays outside repr and receipts."""

    case_index: int
    case_id: str
    case_alias: str
    case: PublicBenchmarkCase = field(repr=False)

    def __post_init__(self) -> None:
        if (
            type(self.case_index) is not int
            or self.case_index < 0
            or not _bounded_text(self.case_id)
            or not _bounded_text(self.case_alias)
            or type(self.case) is not PublicBenchmarkCase
            or self.case.case_id != self.case_id
        ):
            _fail("publishable_run_projected_case_invalid")

    def __repr__(self) -> str:
        return f"PublishableProjectedOfficialCase(case_index={self.case_index}, case=<private>)"

    def __reduce_ex__(self, _protocol: int) -> object:
        raise TypeError("PublishableProjectedOfficialCase contains private material")


class PublishableOfficialCaseProjectionPort(Protocol):
    """Page exact official projections without requiring a full dataset in memory."""

    def read_page(
        self,
        *,
        run: SchedulerRunAuthority,
        start_case_index: int,
        limit: int,
    ) -> tuple[PublishableProjectedOfficialCase, ...]: ...


@final
@dataclass(frozen=True, slots=True, repr=False)
class PublishableRunRuntimeCapabilities:
    """Private capabilities opened by an adapter-owned production session."""

    extraction_suite: PublishableExtractionSuiteReadback = field(repr=False)
    retrieval_authority: SchedulerRetrievalEvidenceReaderPort = field(repr=False)
    output_cipher: OutputCipherPort = field(repr=False)
    bridge_keys: BridgeSecretCapability = field(repr=False)
    bridge_fleet_readiness: BridgeFleetReadinessReceipt = field(repr=False)
    bridge_transport: BridgeTransportPort = field(repr=False)
    bridge_journal: BridgeJournal = field(repr=False)
    clock: Callable[[], int] = field(repr=False)
    lease_id_factory: Callable[[], str] = field(repr=False)
    lease_duration_ms: int = 60_000

    def __post_init__(self) -> None:
        if (
            type(self.extraction_suite) is not PublishableExtractionSuiteReadback
            or not callable(getattr(self.retrieval_authority, "read_exact", None))
            or not callable(getattr(self.output_cipher, "seal", None))
            or type(self.bridge_fleet_readiness) is not BridgeFleetReadinessReceipt
            or type(self.bridge_journal) is not BridgeJournal
            or not callable(self.clock)
            or not callable(self.lease_id_factory)
            or type(self.lease_duration_ms) is not int
            or self.lease_duration_ms < 1
        ):
            _fail("publishable_run_runtime_capabilities_invalid")

    def __repr__(self) -> str:
        return "PublishableRunRuntimeCapabilities(private_capabilities=<bound>)"


class PublishableRunSessionPort(Protocol):
    """Adapter root joining projections, sealed inputs, and runtime capabilities."""

    @property
    def suite(self) -> SchedulerSuiteAuthority: ...

    @property
    def official_case_projection(self) -> PublishableOfficialCaseProjectionPort: ...

    def open_runtime(
        self,
        *,
        case_authority_root_sha256: str,
    ) -> PublishableRunRuntimeCapabilities: ...

    def close(self) -> None: ...


class PublishableRunDependencyFactoryPort(Protocol):
    """Installed adapter entry point; provider-specific imports stay behind it."""

    def open_session(
        self,
        *,
        inputs: PublishableRunProviderInputs,
        mode: publishable_production_composition.PublishableProductionOpenMode,
    ) -> PublishableRunSessionPort: ...


def canonical_adapter_json(value: object, *, secret: bool) -> bytes:
    if type(value) is not dict:
        _fail(
            "publishable_run_adapter_secrets_invalid"
            if secret
            else "publishable_run_adapter_config_invalid"
        )
    try:
        encoded = canonical_json_bytes(value)
    except Exception:
        _fail(
            "publishable_run_adapter_secrets_invalid"
            if secret
            else "publishable_run_adapter_config_invalid"
        )
    _validate_json_tree(value)
    return encoded


def _decoded_object(raw: bytes, *, code: str) -> dict[str, Any]:
    try:
        value = strict_json_loads(raw, maximum_bytes=PUBLISHABLE_RUN_SECRETS_BYTES_LIMIT)
    except Exception:
        _fail(code)
    if type(value) is not dict:
        _fail(code)
    _validate_json_tree(value)
    return value


def _validate_json_tree(value: object) -> None:
    stack: list[tuple[object, int]] = [(value, 0)]
    nodes = 0
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if nodes > 100_000 or depth > 20:
            _fail("publishable_run_adapter_json_unbounded")
        if type(current) is dict:
            if any(type(key) is not str for key in current):
                _fail("publishable_run_adapter_json_invalid")
            stack.extend((item, depth + 1) for item in current.values())
        elif type(current) is list:
            stack.extend((item, depth + 1) for item in current)
        elif current is None or type(current) in {str, int, float, bool}:
            continue
        else:
            _fail("publishable_run_adapter_json_invalid")


def _identifier(value: object) -> bool:
    return type(value) is str and _IDENTIFIER.fullmatch(value) is not None


def _bounded_text(value: object) -> bool:
    if type(value) is not str or not value:
        return False
    try:
        return len(value.encode("utf-8")) <= 200
    except UnicodeEncodeError:
        return False


def _fail(code: str) -> None:
    raise PublishableRunError(code) from None


__all__ = (
    "PUBLISHABLE_RUN_CONFIG_BYTES_LIMIT",
    "PUBLISHABLE_RUN_CONFIG_SCHEMA",
    "PUBLISHABLE_RUN_DEPENDENCY_ENTRYPOINT_GROUP",
    "PUBLISHABLE_RUN_SECRETS_BYTES_LIMIT",
    "PUBLISHABLE_RUN_SECRETS_SCHEMA",
    "PublishableOfficialCaseProjectionPort",
    "PublishableProjectedOfficialCase",
    "PublishableRunConfig",
    "PublishableRunDependencyFactoryPort",
    "PublishableRunError",
    "PublishableRunProviderInputs",
    "PublishableRunRuntimeCapabilities",
    "PublishableRunSecrets",
    "PublishableRunSessionPort",
    "canonical_adapter_json",
)

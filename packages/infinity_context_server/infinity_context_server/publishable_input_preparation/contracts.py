"""Provider-neutral contracts for producing one publishable-run input set."""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Protocol, final

from infinity_context_core.features.projection_receipts import (
    ContextAuthorityRegistrationPort,
)
from infinity_context_core.features.projection_receipts.strict_v4_preparation import (
    StrictV4PreparationReceiptPort,
)
from infinity_context_runtime_bridge.json_boundary import (
    strict_json_loads,
)

from infinity_context_server.memory_comparison_http import InfinityContextHttpComparisonBackend
from infinity_context_server.processes import (
    publishable_full_extraction_managed_mem0_v5_suite_composition as extraction_composition,
)
from infinity_context_server.processes.publishable_full_extraction_suite import (
    PUBLISHABLE_EXTRACTION_BENCHMARKS,
    PUBLISHABLE_EXTRACTION_TOTAL_OPERATION_COUNT,
    PublishableExtractionSuiteReadback,
)
from infinity_context_server.publishable_durable_scheduler.contracts import (
    LOCOMO_PROFILE,
    SchedulerSuiteAuthority,
    commitment,
)
from infinity_context_server.publishable_durable_scheduler.publishable_run_contracts import (
    PublishableOfficialCaseProjectionPort,
)
from infinity_context_server.publishable_durable_scheduler.retrieval_capture_contracts import (
    SCHEDULER_RETRIEVAL_CAPTURE_BACKENDS,
    SCHEDULER_RETRIEVAL_CAPTURE_GROUP_COUNT,
)
from infinity_context_server.publishable_durable_scheduler.runner_contracts import (
    PUBLISHABLE_SUITE_CASE_COUNT,
    is_sha256,
)

PUBLISHABLE_INPUT_PREPARATION_SCHEMA = "memory-comparison-publishable-input-preparation.v1"
PUBLISHABLE_INPUT_PROVIDER_CONFIG_BYTES_LIMIT = 1024 * 1024
PUBLISHABLE_INPUT_PROVIDER_SECRETS_BYTES_LIMIT = 1024 * 1024
PUBLISHABLE_INPUT_FIRST_RUNTIME_RETRIEVAL_GROUP_COUNT = LOCOMO_PROFILE.case_count * len(
    SCHEDULER_RETRIEVAL_CAPTURE_BACKENDS
)
PUBLISHABLE_INPUT_PREPARATION_DEPENDENCY_ENTRYPOINT_GROUP = (
    "infinity_context.publishable_input_preparation_dependencies"
)
PublishableFullExtractionSuiteConfiguration = (
    extraction_composition.PublishableFullExtractionSuiteConfiguration
)


@final
@dataclass(frozen=True, slots=True, repr=False)
class PublishableInputPreparationProviderInputs:
    """Private operator material passed only to the selected production adapter."""

    state_root: Path = field(repr=False)
    run_adapter_config_json: bytes = field(repr=False)
    run_adapter_secrets_json: bytes = field(repr=False)
    input_config_json: bytes = field(repr=False)
    input_secrets_json: bytes = field(repr=False)

    def __post_init__(self) -> None:
        try:
            value = self.state_root.lstat()
            resolved = self.state_root.resolve(strict=True)
        except (AttributeError, OSError):
            _fail("publishable_input_provider_inputs_invalid")
        materials = (
            (self.run_adapter_config_json, PUBLISHABLE_INPUT_PROVIDER_CONFIG_BYTES_LIMIT),
            (self.run_adapter_secrets_json, PUBLISHABLE_INPUT_PROVIDER_SECRETS_BYTES_LIMIT),
            (self.input_config_json, PUBLISHABLE_INPUT_PROVIDER_CONFIG_BYTES_LIMIT),
            (self.input_secrets_json, PUBLISHABLE_INPUT_PROVIDER_SECRETS_BYTES_LIMIT),
        )
        if (
            not isinstance(self.state_root, Path)
            or not self.state_root.is_absolute()
            or ".." in self.state_root.parts
            or resolved != self.state_root
            or stat.S_ISLNK(value.st_mode)
            or not stat.S_ISDIR(value.st_mode)
            or value.st_uid != os.geteuid()
            or stat.S_IMODE(value.st_mode) != 0o700
            or any(type(raw) is not bytes or not 1 <= len(raw) <= limit for raw, limit in materials)
        ):
            _fail("publishable_input_provider_inputs_invalid")
        try:
            if any(
                type(strict_json_loads(raw, maximum_bytes=limit)) is not dict
                for raw, limit in materials
            ):
                _fail("publishable_input_provider_inputs_invalid")
        except PublishableInputPreparationError:
            raise
        except Exception:
            _fail("publishable_input_provider_inputs_invalid")

    def __repr__(self) -> str:
        return "PublishableInputPreparationProviderInputs(private_material=<bound>)"

    def __reduce_ex__(self, _protocol: int) -> object:
        raise TypeError("publishable input provider inputs are nonserializable")


class PublishableInputPreparationError(RuntimeError):
    """Stable secret-safe rejection from the input-preparation boundary."""

    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class PublishableInputPreparationPhase(StrEnum):
    EXTRACTION_PENDING = "extraction_pending"
    RECONCILIATION_REQUIRED = "reconciliation_required"
    RUNTIME_SWITCH_REQUIRED = "runtime_switch_required"
    COMPLETE = "complete"


@final
@dataclass(frozen=True, slots=True, repr=False)
class PublishableStrictV4RecoveryCapabilities:
    """Ports needed to reauthenticate one already prepared strict-v4 authority."""

    receipt_store: StrictV4PreparationReceiptPort = field(repr=False)
    registration_port: ContextAuthorityRegistrationPort = field(repr=False)

    def __post_init__(self) -> None:
        if not callable(getattr(self.receipt_store, "read", None)) or not callable(
            getattr(self.registration_port, "register_and_readback", None)
        ):
            _fail("publishable_input_strict_v4_capabilities_invalid")


@final
@dataclass(frozen=True, slots=True)
class PublishableExtractionTerminalSealReceipt:
    """Commitment-only proof that both consumer handoffs were authenticated."""

    suite_readback_commitment_sha256: str
    ordered_terminal_commitment_sha256: tuple[str, str]
    ordered_authentication_hmac_sha256: tuple[str, str]
    created_file_count: int
    commitment_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        values = (
            self.suite_readback_commitment_sha256,
            *self.ordered_terminal_commitment_sha256,
            *self.ordered_authentication_hmac_sha256,
        )
        if (
            type(self.ordered_terminal_commitment_sha256) is not tuple
            or len(self.ordered_terminal_commitment_sha256) != 2
            or type(self.ordered_authentication_hmac_sha256) is not tuple
            or len(self.ordered_authentication_hmac_sha256) != 2
            or any(not is_sha256(value) for value in values)
            or type(self.created_file_count) is not int
            or not 0 <= self.created_file_count <= 2
        ):
            _fail("publishable_input_terminal_seal_receipt_invalid")
        object.__setattr__(
            self,
            "commitment_sha256",
            commitment("publishable-input-terminal-seals", self.material()),
        )

    def material(self) -> dict[str, object]:
        return {
            "ordered_authentication_hmac_sha256": list(self.ordered_authentication_hmac_sha256),
            "ordered_terminal_commitment_sha256": list(self.ordered_terminal_commitment_sha256),
            "suite_readback_commitment_sha256": self.suite_readback_commitment_sha256,
        }


class PublishableExtractionTerminalStorePort(Protocol):
    """Write once and authenticate both exact run-provider handoffs."""

    @property
    def paths(self) -> tuple[Path, Path]: ...

    @property
    def authentication_key_fingerprints(self) -> tuple[str, str]: ...

    def seal_exact(
        self, readback: PublishableExtractionSuiteReadback
    ) -> PublishableExtractionTerminalSealReceipt: ...


@final
@dataclass(frozen=True, slots=True, repr=False)
class OpenedPublishableInputPreparationSession:
    """Provider-owned capabilities opened before any subscription dispatch."""

    suite: SchedulerSuiteAuthority
    official_case_projection: PublishableOfficialCaseProjectionPort = field(repr=False)
    strict_v4_recovery: tuple[
        PublishableStrictV4RecoveryCapabilities,
        PublishableStrictV4RecoveryCapabilities,
    ] = field(repr=False)
    extraction_configuration: PublishableFullExtractionSuiteConfiguration = field(repr=False)
    extraction_terminal_store: PublishableExtractionTerminalStorePort = field(repr=False)
    process_lock_path: Path = field(repr=False)
    retrieval_database_path: Path = field(repr=False)
    retrieval_authentication_key: bytes = field(repr=False)
    expected_retrieval_authority_root_sha256: str
    infinity_backend: InfinityContextHttpComparisonBackend = field(repr=False)
    close_callbacks: tuple[Callable[[], None], ...] = field(repr=False)
    _closed: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        if (
            type(self.suite) is not SchedulerSuiteAuthority
            or not callable(getattr(self.official_case_projection, "read_page", None))
            or type(self.strict_v4_recovery) is not tuple
            or len(self.strict_v4_recovery) != 2
            or any(
                type(item) is not PublishableStrictV4RecoveryCapabilities
                for item in self.strict_v4_recovery
            )
            or type(self.extraction_configuration)
            is not PublishableFullExtractionSuiteConfiguration
            or not callable(getattr(self.extraction_terminal_store, "seal_exact", None))
            or not isinstance(self.process_lock_path, Path)
            or not self.process_lock_path.is_absolute()
            or not isinstance(self.retrieval_database_path, Path)
            or not self.retrieval_database_path.is_absolute()
            or type(self.retrieval_authentication_key) is not bytes
            or not 32 <= len(self.retrieval_authentication_key) <= 1024
            or not is_sha256(self.expected_retrieval_authority_root_sha256)
            or type(self.infinity_backend) is not InfinityContextHttpComparisonBackend
            or type(self.close_callbacks) is not tuple
            or any(not callable(callback) for callback in self.close_callbacks)
            or self._closed is not False
        ):
            _fail("publishable_input_session_invalid")
        try:
            extraction_fingerprints = self.extraction_terminal_store.authentication_key_fingerprints
        except Exception:
            _fail("publishable_input_session_invalid")
        retrieval_fingerprint = authentication_key_fingerprint(self.retrieval_authentication_key)
        if (
            type(extraction_fingerprints) is not tuple
            or len(extraction_fingerprints) != 2
            or any(not is_sha256(item) for item in extraction_fingerprints)
            or len({*extraction_fingerprints, retrieval_fingerprint}) != 3
        ):
            _fail("publishable_input_authentication_key_cross_wire")

    def close(self) -> None:
        if self._closed:
            return
        object.__setattr__(self, "_closed", True)
        first: BaseException | None = None
        for callback in self.close_callbacks:
            try:
                callback()
            except BaseException as error:
                if first is None:
                    first = error
        if first is not None:
            raise first

    def __repr__(self) -> str:
        return "OpenedPublishableInputPreparationSession(private_capabilities=<bound>)"

    def __reduce_ex__(self, _protocol: int) -> object:
        raise TypeError("publishable input preparation sessions are nonserializable")


class PublishableInputPreparationDependencyFactoryPort(Protocol):
    """Installed adapter entry point for pre-terminal production capabilities."""

    async def open_session(
        self, *, inputs: PublishableInputPreparationProviderInputs
    ) -> OpenedPublishableInputPreparationSession: ...


@final
@dataclass(frozen=True, slots=True)
class PublishableInputPreparationResult:
    """Secret-free progress or an exact authenticated two-input terminal."""

    phase: PublishableInputPreparationPhase
    suite_authority_sha256: str
    official_case_authority_root_sha256: str
    extraction_committed_receipt_count: int
    subscription_step_count: int
    extraction_suite_readback_sha256: str | None = None
    ordered_extraction_terminal_sha256: tuple[str, str] | None = None
    ordered_extraction_authentication_hmac_sha256: tuple[str, str] | None = None
    retrieval_authority_root_sha256: str | None = None
    retrieval_group_count: int = 0
    commitment_sha256: str = field(init=False)
    complete: bool = field(init=False)
    paid_go_ready: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        complete = self.phase is PublishableInputPreparationPhase.COMPLETE
        terminal_values = (
            self.extraction_suite_readback_sha256,
            self.ordered_extraction_terminal_sha256,
            self.ordered_extraction_authentication_hmac_sha256,
            self.retrieval_authority_root_sha256,
        )
        switch_required = self.phase is PublishableInputPreparationPhase.RUNTIME_SWITCH_REQUIRED
        if (
            type(self.phase) is not PublishableInputPreparationPhase
            or not is_sha256(self.suite_authority_sha256)
            or not is_sha256(self.official_case_authority_root_sha256)
            or type(self.extraction_committed_receipt_count) is not int
            or not 0
            <= self.extraction_committed_receipt_count
            <= PUBLISHABLE_EXTRACTION_TOTAL_OPERATION_COUNT
            or type(self.subscription_step_count) is not int
            or not 0 <= self.subscription_step_count <= PUBLISHABLE_EXTRACTION_TOTAL_OPERATION_COUNT
            or type(self.retrieval_group_count) is not int
            or self.paid_go_ready is not False
            or complete is not all(value is not None for value in terminal_values)
            or complete
            and (
                self.extraction_committed_receipt_count
                != PUBLISHABLE_EXTRACTION_TOTAL_OPERATION_COUNT
                or self.retrieval_group_count != SCHEDULER_RETRIEVAL_CAPTURE_GROUP_COUNT
                or not is_sha256(self.extraction_suite_readback_sha256)
                or not is_sha256(self.retrieval_authority_root_sha256)
                or not _sha_pair(self.ordered_extraction_terminal_sha256)
                or not _sha_pair(self.ordered_extraction_authentication_hmac_sha256)
            )
            or not complete
            and any(value is not None for value in terminal_values)
            or not complete
            and self.retrieval_group_count
            not in (0, PUBLISHABLE_INPUT_FIRST_RUNTIME_RETRIEVAL_GROUP_COUNT)
            or switch_required
            and self.retrieval_group_count != PUBLISHABLE_INPUT_FIRST_RUNTIME_RETRIEVAL_GROUP_COUNT
            or self.retrieval_group_count == PUBLISHABLE_INPUT_FIRST_RUNTIME_RETRIEVAL_GROUP_COUNT
            and self.extraction_committed_receipt_count < PUBLISHABLE_EXTRACTION_BENCHMARKS[0][1]
        ):
            _fail("publishable_input_result_invalid")
        object.__setattr__(self, "complete", complete)
        object.__setattr__(
            self,
            "commitment_sha256",
            commitment("publishable-input-preparation", self.artifact_material()),
        )

    def artifact_material(self) -> dict[str, object]:
        """Stable artifact identity; invocation-local work is intentionally excluded."""

        material = self.material()
        del material["subscription_step_count"]
        return material

    def material(self) -> dict[str, object]:
        return {
            "complete": self.phase is PublishableInputPreparationPhase.COMPLETE,
            "expected_case_count": PUBLISHABLE_SUITE_CASE_COUNT,
            "expected_extraction_operation_count": (PUBLISHABLE_EXTRACTION_TOTAL_OPERATION_COUNT),
            "expected_retrieval_group_count": SCHEDULER_RETRIEVAL_CAPTURE_GROUP_COUNT,
            "extraction_committed_receipt_count": self.extraction_committed_receipt_count,
            "extraction_suite_readback_sha256": self.extraction_suite_readback_sha256,
            "official_case_authority_root_sha256": (self.official_case_authority_root_sha256),
            "ordered_extraction_authentication_hmac_sha256": (
                None
                if self.ordered_extraction_authentication_hmac_sha256 is None
                else list(self.ordered_extraction_authentication_hmac_sha256)
            ),
            "ordered_extraction_expected_receipt_count": [
                count for _profile, count in PUBLISHABLE_EXTRACTION_BENCHMARKS
            ],
            "ordered_extraction_terminal_sha256": (
                None
                if self.ordered_extraction_terminal_sha256 is None
                else list(self.ordered_extraction_terminal_sha256)
            ),
            "paid_go_ready": False,
            "phase": self.phase.value,
            "retrieval_authority_root_sha256": self.retrieval_authority_root_sha256,
            "retrieval_group_count": self.retrieval_group_count,
            "schema_version": PUBLISHABLE_INPUT_PREPARATION_SCHEMA,
            "subscription_step_count": self.subscription_step_count,
            "suite_authority_sha256": self.suite_authority_sha256,
        }

    def payload(self) -> dict[str, object]:
        return {**self.material(), "commitment_sha256": self.commitment_sha256}


def _sha_pair(value: object) -> bool:
    return (
        type(value) is tuple
        and len(value) == 2
        and all(is_sha256(item) for item in value)
        and len(set(value)) == 2
    )


def authentication_key_commitment(key: bytes, *, purpose: str) -> str:
    """Compare key capabilities without exposing or retaining their bytes."""

    if (
        type(key) is not bytes
        or len(key) < 32
        or type(purpose) is not str
        or not purpose
        or len(purpose) > 200
        or not purpose.isascii()
    ):
        _fail("publishable_input_authentication_key_invalid")
    return hashlib.sha256(
        b"infinity-context/publishable-input/key/v1\0" + purpose.encode("ascii") + b"\0" + key
    ).hexdigest()


def authentication_key_fingerprint(key: bytes) -> str:
    """Return a common-domain fingerprint used only to reject key reuse."""

    if type(key) is not bytes or len(key) < 32:
        _fail("publishable_input_authentication_key_invalid")
    return hashlib.sha256(
        b"infinity-context/publishable-input/key-fingerprint/v1\0" + key
    ).hexdigest()


def _fail(code: str) -> None:
    raise PublishableInputPreparationError(code) from None


__all__ = (
    "PUBLISHABLE_INPUT_PREPARATION_DEPENDENCY_ENTRYPOINT_GROUP",
    "PUBLISHABLE_INPUT_FIRST_RUNTIME_RETRIEVAL_GROUP_COUNT",
    "PUBLISHABLE_INPUT_PREPARATION_SCHEMA",
    "PUBLISHABLE_INPUT_PROVIDER_CONFIG_BYTES_LIMIT",
    "PUBLISHABLE_INPUT_PROVIDER_SECRETS_BYTES_LIMIT",
    "OpenedPublishableInputPreparationSession",
    "PublishableExtractionTerminalSealReceipt",
    "PublishableExtractionTerminalStorePort",
    "PublishableInputPreparationDependencyFactoryPort",
    "PublishableInputPreparationError",
    "PublishableInputPreparationPhase",
    "PublishableInputPreparationProviderInputs",
    "PublishableInputPreparationResult",
    "PublishableStrictV4RecoveryCapabilities",
    "authentication_key_commitment",
    "authentication_key_fingerprint",
)

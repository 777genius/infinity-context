"""Phase-C receipt verification with narrowly observed provider identities.

The authority in this module pre-authorizes every caller-controlled receipt
field.  Only the provider-generated thread, turn, and output identities are
observed from the receipt before the immutable Phase-C boundary authenticates
the complete envelope.
"""

# ruff: noqa: E721 - exact provider DTO types are security contracts throughout

from __future__ import annotations

import hashlib
import importlib
import os
import re
import stat
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import final

from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    MEM0_OSS_FULL_RUN_MAX_OPERATIONS,
    Mem0OssFullRunError,
    Mem0OssReceiptDisposition,
    RuntimeReceiptVerificationContext,
    RuntimeReceiptVerificationPort,
    RuntimeReceiptVerificationResult,
    canonical_sha256,
    is_sha256,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_http import (
    Mem0V5HttpError,
    Mem0V5RuntimeReceiptEnvelope,
)
from infinity_context_server.memory_comparison_secret_validation import (
    is_bounded_text_secret,
)

_SAFE_TEXT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,511}$")
_REQUESTED_OUTPUT_TOKENS = 4096
_MAX_NODE_EXECUTABLE_BYTES = 256 * 1024 * 1024
_PROVIDER_FREE_TEST_SEAL = object()
_PREFLIGHTED_COMPOSITION_SEAL = object()


@dataclass(frozen=True, slots=True)
class _ReviewedNodeExecutableAuthority:
    canonical_path: Path
    sha256: str


_REVIEWED_NODE_EXECUTABLE = _ReviewedNodeExecutableAuthority(
    canonical_path=Path("/usr/local/bin/node"),
    sha256="b2959781cc5a74c357ffa02367efa8a0330cbb1c9cb347732fdfaaaca381cbcd",
)


@final
@dataclass(frozen=True, slots=True)
class Mem0V5ObservedExtractionOperationAuthority:
    """Opaque authority for one ordered observed extraction operation."""

    operation_id_sha256: str
    unit_identity_sha256: str
    unit_sha256: str
    scope_sha256: str
    sequence: int
    request_body_sha256: str

    def __post_init__(self) -> None:
        if (
            any(
                not is_sha256(value)
                for value in (
                    self.operation_id_sha256,
                    self.unit_identity_sha256,
                    self.unit_sha256,
                    self.scope_sha256,
                    self.request_body_sha256,
                )
            )
            or type(self.sequence) is not int
            or self.sequence < 0
        ):
            _fail("mem0_v5_http_configuration_invalid")

    def __repr__(self) -> str:
        return "Mem0V5ObservedExtractionOperationAuthority(<opaque>)"


@final
@dataclass(frozen=True, slots=True)
class Mem0V5ObservedExtractionReceiptAuthority:
    """Shared authority plus an ordered set of observed extraction operations."""

    admission_commitment_sha256: str
    model: str
    reasoning_effort: str
    service_tier: str
    base_instructions_sha256: str
    runtime_source_sha256: str
    route_binding_sha256: str
    account_binding_hmac_sha256: str
    node_executable_path: str
    node_executable_sha256: str
    response_format_type: str
    response_format_sha256: str
    response_schema_sha256: str
    operations: tuple[Mem0V5ObservedExtractionOperationAuthority, ...]
    requested_output_tokens: int = _REQUESTED_OUTPUT_TOKENS

    def __post_init__(self) -> None:
        digests = (
            self.admission_commitment_sha256,
            self.base_instructions_sha256,
            self.runtime_source_sha256,
            self.route_binding_sha256,
            self.account_binding_hmac_sha256,
            self.node_executable_sha256,
            self.response_format_sha256,
            self.response_schema_sha256,
        )
        text = (
            self.model,
            self.reasoning_effort,
            self.service_tier,
            self.response_format_type,
        )
        if (
            any(not is_sha256(value) for value in digests)
            or any(not _safe_text(value) for value in text)
            or not _safe_absolute_path(self.node_executable_path)
            or type(self.requested_output_tokens) is not int
            or self.requested_output_tokens != _REQUESTED_OUTPUT_TOKENS
            or type(self.operations) is not tuple
            or not 1 <= len(self.operations) <= MEM0_OSS_FULL_RUN_MAX_OPERATIONS
        ):
            _fail("mem0_v5_http_configuration_invalid")
        operation_ids: set[str] = set()
        unit_identities: set[str] = set()
        for index, operation in enumerate(self.operations):
            if type(operation) is not Mem0V5ObservedExtractionOperationAuthority:
                _fail("mem0_v5_http_configuration_invalid")
            Mem0V5ObservedExtractionOperationAuthority.__post_init__(operation)
            if (
                operation.sequence != index
                or operation.operation_id_sha256 in operation_ids
                or operation.unit_identity_sha256 in unit_identities
                or operation.operation_id_sha256
                != canonical_sha256(
                    {
                        "admission_commitment_sha256": self.admission_commitment_sha256,
                        "unit_index": index,
                        "unit_identity_sha256": operation.unit_identity_sha256,
                    }
                )
            ):
                _fail("mem0_v5_http_configuration_invalid")
            operation_ids.add(operation.operation_id_sha256)
            unit_identities.add(operation.unit_identity_sha256)

    def __repr__(self) -> str:
        return "Mem0V5ObservedExtractionReceiptAuthority(<opaque>)"


@dataclass(frozen=True, slots=True)
class _ObservedProviderIdentity:
    thread_id: str
    turn_id: str
    output_text_sha256: str


@final
class Mem0V5ObservedExtractionReceiptVerifier(RuntimeReceiptVerificationPort):
    """Authenticate one receipt while observing only provider-issued identities.

    A readback-only context is sufficient authority for status verification in
    a fresh process.  In-process unknown and consumed state still prevents a
    marked dispatch from being retried and prevents replay after acceptance.
    """

    __slots__ = (
        "_authority",
        "_authority_identity",
        "_authority_snapshot",
        "_authority_snapshot_identity",
        "_boundary",
        "_consumed",
        "_consumed_identity",
        "_lock",
        "_module",
        "_operation_index",
        "_operation_index_identity",
        "_operations",
        "_runtime_binding",
        "_secret",
        "_unknown",
        "_unknown_identity",
    )

    def __init__(
        self,
        *,
        boundary: object,
        runtime_binding: object,
        receipt_secret: str,
        authority: Mem0V5ObservedExtractionReceiptAuthority,
    ) -> None:
        self._initialize(
            boundary=boundary,
            runtime_binding=runtime_binding,
            receipt_secret=receipt_secret,
            authority=authority,
            provider_free_test_seal=None,
        )

    @classmethod
    def _for_provider_free_tests(
        cls,
        *,
        boundary: object,
        runtime_binding: object,
        receipt_secret: str,
        authority: Mem0V5ObservedExtractionReceiptAuthority,
    ) -> Mem0V5ObservedExtractionReceiptVerifier:
        """Build with a deterministic test verifier, never a live composition."""

        instance = object.__new__(cls)
        instance._initialize(
            boundary=boundary,
            runtime_binding=runtime_binding,
            receipt_secret=receipt_secret,
            authority=authority,
            provider_free_test_seal=_PROVIDER_FREE_TEST_SEAL,
        )
        return instance

    @classmethod
    def _for_preflighted_composition(
        cls,
        *,
        boundary: object,
        runtime_binding: object,
        receipt_secret: str,
        authority: Mem0V5ObservedExtractionReceiptAuthority,
    ) -> Mem0V5ObservedExtractionReceiptVerifier:
        """Build after the composition root completed the live preflight once."""

        instance = object.__new__(cls)
        instance._initialize(
            boundary=boundary,
            runtime_binding=runtime_binding,
            receipt_secret=receipt_secret,
            authority=authority,
            provider_free_test_seal=_PREFLIGHTED_COMPOSITION_SEAL,
        )
        return instance

    def _initialize(
        self,
        *,
        boundary: object,
        runtime_binding: object,
        receipt_secret: str,
        authority: Mem0V5ObservedExtractionReceiptAuthority,
        provider_free_test_seal: object | None,
    ) -> None:
        if provider_free_test_seal in (
            _PROVIDER_FREE_TEST_SEAL,
            _PREFLIGHTED_COMPOSITION_SEAL,
        ):
            module = _require_common_boundary(boundary, runtime_binding, authority)
        else:
            require_mem0_v5_observed_extraction_receipt_boundary(
                boundary=boundary,
                runtime_binding=runtime_binding,
                authority=authority,
            )
            module = importlib.import_module("phase_c_canary.runtime_receipt_v2")
        if not is_bounded_text_secret(receipt_secret):
            _fail("mem0_v5_http_configuration_invalid")
        self._module = module
        self._boundary = boundary
        self._runtime_binding = runtime_binding
        self._secret = receipt_secret
        self._authority = authority
        self._authority_identity = id(authority)
        self._authority_snapshot = _authority_snapshot(authority)
        self._authority_snapshot_identity = id(self._authority_snapshot)
        self._operations = authority.operations
        self._operation_index = {
            operation.operation_id_sha256: operation for operation in authority.operations
        }
        self._operation_index_identity = id(self._operation_index)
        self._unknown: set[str] = set()
        self._unknown_identity = id(self._unknown)
        self._consumed: set[str] = set()
        self._consumed_identity = id(self._consumed)
        self._lock = threading.Lock()

    def mark_outcome_unknown(self, *, context: RuntimeReceiptVerificationContext) -> None:
        with self._lock:
            operation = self._require_context(context, readback=False)
            operation_id = operation.operation_id_sha256
            if operation_id in self._consumed:
                _fail("mem0_v5_runtime_receipt_state_invalid")
            self._unknown.add(operation_id)

    def verify_dispatch_receipt(
        self,
        *,
        payload: object,
        context: RuntimeReceiptVerificationContext,
    ) -> RuntimeReceiptVerificationResult:
        return self._verify(payload=payload, context=context, readback=False)

    def verify_status_readback(
        self,
        *,
        payload: object,
        context: RuntimeReceiptVerificationContext,
    ) -> RuntimeReceiptVerificationResult:
        return self._verify(payload=payload, context=context, readback=True)

    def _verify(
        self,
        *,
        payload: object,
        context: RuntimeReceiptVerificationContext,
        readback: bool,
    ) -> RuntimeReceiptVerificationResult:
        with self._lock:
            operation = self._require_context(context, readback=readback)
            operation_id = operation.operation_id_sha256
            if operation_id in self._consumed:
                _fail("mem0_v5_runtime_receipt_replayed")
            if not readback and operation_id in self._unknown:
                _fail("mem0_v5_runtime_receipt_state_invalid")
            envelope = self._require_envelope(payload, operation)
            observed = _observe_provider_identity(envelope.runtime_receipt)
            expectation = self._module.RuntimeReceiptExpectation(
                model=self._authority.model,
                reasoning_effort=self._authority.reasoning_effort,
                service_tier=self._authority.service_tier,
                base_instructions_sha256=self._authority.base_instructions_sha256,
                runtime_source_sha256=self._authority.runtime_source_sha256,
                route_binding_sha256=self._authority.route_binding_sha256,
                account_binding_hmac_sha256=self._authority.account_binding_hmac_sha256,
                thread_id=observed.thread_id,
                turn_id=observed.turn_id,
                request_body_sha256=operation.request_body_sha256,
                output_text_sha256=observed.output_text_sha256,
                response_format_type=self._authority.response_format_type,
                response_format_sha256=self._authority.response_format_sha256,
                response_schema_sha256=self._authority.response_schema_sha256,
                requested_output_tokens=self._authority.requested_output_tokens,
            )
            try:
                safe = self._boundary.verify(
                    receipt=envelope.runtime_receipt,
                    secret=self._secret,
                    expectation=expectation,
                    runtime_binding=self._runtime_binding,
                    call_kind=self._module.RuntimeCallKind.EXTRACTION,
                    sequence=operation.sequence,
                    operation_id_sha256=operation.operation_id_sha256,
                )
                self._module.require_verified_safe_receipt(safe)
            except Exception:
                raise Mem0V5HttpError("mem0_v5_runtime_receipt_unauthenticated") from None
            if (
                type(safe) is not self._module.SafeRuntimeReceipt
                or safe.call_kind is not self._module.RuntimeCallKind.EXTRACTION
                or safe.sequence != operation.sequence
                or safe.operation_id_sha256 != operation.operation_id_sha256
                or safe.runtime_source_sha256 != self._authority.runtime_source_sha256
                or safe.route_binding_sha256 != self._authority.route_binding_sha256
                or safe.runtime_binding_commitment_sha256 != self._runtime_binding.commitment_sha256
                or safe.request_body_sha256 != operation.request_body_sha256
                or safe.output_text_sha256 != observed.output_text_sha256
            ):
                _fail("mem0_v5_runtime_receipt_invalid")
            self._consumed.add(operation_id)
            self._unknown.discard(operation_id)
            return RuntimeReceiptVerificationResult(
                admission_commitment_sha256=self._authority.admission_commitment_sha256,
                operation_id_sha256=operation.operation_id_sha256,
                unit_identity_sha256=operation.unit_identity_sha256,
                unit_sha256=operation.unit_sha256,
                route_sha256=self._authority.route_binding_sha256,
                scope_sha256=operation.scope_sha256,
                provider_receipt_sha256=safe.receipt_sha256,
                disposition=Mem0OssReceiptDisposition.COMPLETED,
                extraction_calls=1,
                retry_count=0,
                request_tokens=safe.usage.prompt_tokens,
                response_tokens=safe.usage.completion_tokens,
            )

    def _require_context(
        self,
        context: RuntimeReceiptVerificationContext,
        *,
        readback: bool,
    ) -> Mem0V5ObservedExtractionOperationAuthority:
        self._require_authority_state()
        authority = self._authority
        if type(context) is not RuntimeReceiptVerificationContext:
            _fail("mem0_v5_runtime_receipt_invalid")
        if context.readback_only is not readback:
            raise Mem0OssFullRunError("mem0_v5_receipt_context_invalid")
        operation = self._operation_index.get(context.operation_id_sha256)
        if (
            type(operation) is not Mem0V5ObservedExtractionOperationAuthority
            or context.admission_commitment_sha256 != authority.admission_commitment_sha256
            or context.operation_id_sha256 != operation.operation_id_sha256
            or context.unit_identity_sha256 != operation.unit_identity_sha256
            or context.unit_sha256 != operation.unit_sha256
            or context.route_sha256 != authority.route_binding_sha256
            or context.scope_sha256 != operation.scope_sha256
        ):
            _fail("mem0_v5_runtime_receipt_invalid")
        return operation

    def _require_envelope(
        self,
        payload: object,
        operation: Mem0V5ObservedExtractionOperationAuthority,
    ) -> Mem0V5RuntimeReceiptEnvelope:
        if type(payload) is not Mem0V5RuntimeReceiptEnvelope:
            _fail("mem0_v5_runtime_receipt_invalid")
        if (
            payload.admission_commitment_sha256 != self._authority.admission_commitment_sha256
            or payload.operation_id_sha256 != operation.operation_id_sha256
            or type(payload.runtime_receipt) is not dict
        ):
            _fail("mem0_v5_runtime_receipt_invalid")
        return payload

    def _require_authority_state(self) -> None:
        try:
            operations = self._authority.operations
            operation_ids = tuple(operation.operation_id_sha256 for operation in operations)
            if (
                type(self._authority) is not Mem0V5ObservedExtractionReceiptAuthority
                or id(self._authority) != self._authority_identity
                or id(self._authority_snapshot) != self._authority_snapshot_identity
                or _authority_snapshot(self._authority) != self._authority_snapshot
                or operations is not self._operations
                or id(self._operation_index) != self._operation_index_identity
                or type(self._operation_index) is not dict
                or tuple(self._operation_index) != operation_ids
                or any(
                    self._operation_index.get(operation.operation_id_sha256) is not operation
                    for operation in operations
                )
                or id(self._unknown) != self._unknown_identity
                or type(self._unknown) is not set
                or id(self._consumed) != self._consumed_identity
                or type(self._consumed) is not set
            ):
                raise ValueError
        except Exception:
            _fail("mem0_v5_runtime_receipt_state_invalid")


def _authority_snapshot(authority: Mem0V5ObservedExtractionReceiptAuthority) -> tuple[object, ...]:
    return (
        authority.admission_commitment_sha256,
        authority.model,
        authority.reasoning_effort,
        authority.service_tier,
        authority.base_instructions_sha256,
        authority.runtime_source_sha256,
        authority.route_binding_sha256,
        authority.account_binding_hmac_sha256,
        authority.node_executable_path,
        authority.node_executable_sha256,
        authority.response_format_type,
        authority.response_format_sha256,
        authority.response_schema_sha256,
        authority.requested_output_tokens,
        tuple(
            (
                type(operation),
                id(operation),
                operation.operation_id_sha256,
                operation.unit_identity_sha256,
                operation.unit_sha256,
                operation.scope_sha256,
                operation.sequence,
                operation.request_body_sha256,
            )
            for operation in authority.operations
        ),
    )


def require_mem0_v5_observed_extraction_receipt_boundary(
    *,
    boundary: object,
    runtime_binding: object,
    authority: Mem0V5ObservedExtractionReceiptAuthority,
) -> None:
    """Preflight the complete live receipt trust root without touching a secret."""

    try:
        _require_common_boundary(boundary, runtime_binding, authority)
        _preflight_live_boundary(boundary, authority)
    except Exception:
        raise Mem0V5HttpError("mem0_v5_http_configuration_invalid") from None


def _require_common_boundary(
    boundary: object,
    runtime_binding: object,
    authority: object,
) -> object:
    try:
        module = importlib.import_module("phase_c_canary.runtime_receipt_v2")
        binding_module = importlib.import_module("phase_c_canary.runtime_binding")
        if type(boundary) is not module.RuntimeReceiptV2Boundary:
            raise TypeError
        if type(runtime_binding) is not binding_module.TrustedRuntimeBinding:
            raise TypeError
        binding_module.require_trusted_runtime_binding(runtime_binding)
        if type(authority) is not Mem0V5ObservedExtractionReceiptAuthority:
            raise TypeError
        Mem0V5ObservedExtractionReceiptAuthority.__post_init__(authority)
        if (
            authority.runtime_source_sha256 != runtime_binding.runtime_source_sha256
            or authority.route_binding_sha256 != runtime_binding.route_binding_sha256
        ):
            raise TypeError
        return module
    except Exception:
        raise Mem0V5HttpError("mem0_v5_http_configuration_invalid") from None


def _preflight_live_boundary(
    boundary: object,
    authority: Mem0V5ObservedExtractionReceiptAuthority,
) -> None:
    receipt_module = importlib.import_module("phase_c_canary.receipt")
    authority_module = importlib.import_module("phase_c_canary.authority")
    verifier = boundary.hmac_verifier
    if type(verifier) is not receipt_module.NodePublicReceiptVerifier:
        raise TypeError
    reviewed = authority_module.immutable_authority()
    runtime_repo = _canonical_path(verifier.runtime_repo, directory=True)
    expected_repo = _canonical_path(reviewed.runtime_root / "repo", directory=True)
    manifest = _canonical_path(reviewed.runtime_artifact_manifest.path, directory=False)
    if (
        runtime_repo != expected_repo
        or manifest.parent != runtime_repo.parent
        or _sha256_file(manifest) != reviewed.runtime_artifact_manifest.sha256
    ):
        raise ValueError
    reviewed_node = _REVIEWED_NODE_EXECUTABLE
    if (
        authority.node_executable_path != str(reviewed_node.canonical_path)
        or authority.node_executable_sha256 != reviewed_node.sha256
    ):
        raise ValueError
    node = _canonical_path(verifier.node_executable, directory=False)
    if node != reviewed_node.canonical_path:
        raise ValueError
    _require_pinned_node_executable(node, reviewed_node.sha256)
    verifier._verified_module_url()


def _canonical_path(value: object, *, directory: bool) -> Path:
    if not isinstance(value, Path) or not value.is_absolute() or value.is_symlink():
        raise ValueError
    resolved = value.resolve(strict=True)
    if resolved != value:
        raise ValueError
    mode = os.stat(value, follow_symlinks=False).st_mode
    if (directory and not stat.S_ISDIR(mode)) or (not directory and not stat.S_ISREG(mode)):
        raise ValueError
    return resolved


def _require_pinned_node_executable(path: Path, expected_sha256: str) -> None:
    before = os.stat(path, follow_symlinks=False)
    mode = before.st_mode
    if (
        not stat.S_ISREG(mode)
        or not mode & stat.S_IRUSR
        or not mode & stat.S_IXUSR
        or mode & (stat.S_IWGRP | stat.S_IWOTH)
        or not 1 <= before.st_size <= _MAX_NODE_EXECUTABLE_BYTES
        or not os.access(path, os.X_OK)
    ):
        raise ValueError
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    descriptor = os.open(path, flags)
    try:
        observed = os.fstat(descriptor)
        stable = (
            observed.st_dev,
            observed.st_ino,
            observed.st_uid,
            observed.st_gid,
            observed.st_mode,
            observed.st_size,
        ) == (
            before.st_dev,
            before.st_ino,
            before.st_uid,
            before.st_gid,
            before.st_mode,
            before.st_size,
        )
        if not stable or not stat.S_ISREG(observed.st_mode):
            raise ValueError
        actual_sha256 = _sha256_descriptor(descriptor, observed.st_size)
    finally:
        os.close(descriptor)
    after = os.stat(path, follow_symlinks=False)
    if (after.st_dev, after.st_ino, after.st_uid, after.st_gid, after.st_mode, after.st_size) != (
        before.st_dev,
        before.st_ino,
        before.st_uid,
        before.st_gid,
        before.st_mode,
        before.st_size,
    ) or actual_sha256 != expected_sha256:
        raise ValueError


def _sha256_descriptor(descriptor: int, expected_size: int) -> str:
    digest = hashlib.sha256()
    consumed = 0
    while consumed < expected_size:
        chunk = os.read(descriptor, min(1024 * 1024, expected_size - consumed))
        if not chunk:
            raise ValueError
        consumed += len(chunk)
        digest.update(chunk)
    if os.read(descriptor, 1):
        raise ValueError
    return digest.hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _observe_provider_identity(receipt: dict[str, object]) -> _ObservedProviderIdentity:
    try:
        if type(receipt) is not dict:
            raise TypeError
        metadata = receipt["metadata"]
        if type(metadata) is not dict:
            raise TypeError
        selection = metadata["runtime_selection"]
        output = metadata["output_identity"]
        if type(selection) is not dict or type(output) is not dict:
            raise TypeError
        thread_id = selection["thread_id"]
        turn_id = selection["turn_id"]
        output_text_sha256 = output["output_text_sha256"]
    except (KeyError, TypeError):
        raise Mem0V5HttpError("mem0_v5_runtime_receipt_invalid") from None
    if not _safe_text(thread_id) or not _safe_text(turn_id) or not is_sha256(output_text_sha256):
        _fail("mem0_v5_runtime_receipt_invalid")
    return _ObservedProviderIdentity(thread_id, turn_id, output_text_sha256)


def _safe_text(value: object) -> bool:
    return type(value) is str and _SAFE_TEXT.fullmatch(value) is not None


def _safe_absolute_path(value: object) -> bool:
    if type(value) is not str or not 1 <= len(value) <= 4_096 or "\x00" in value:
        return False
    path = Path(value)
    return path.is_absolute() and path.name != "" and str(path) == value and ".." not in path.parts


def _fail(code: str) -> None:
    raise Mem0V5HttpError(code)


__all__ = (
    "Mem0V5ObservedExtractionOperationAuthority",
    "Mem0V5ObservedExtractionReceiptAuthority",
    "Mem0V5ObservedExtractionReceiptVerifier",
    "require_mem0_v5_observed_extraction_receipt_boundary",
)

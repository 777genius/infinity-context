"""Attested one-shot HTTP adapter for publishable managed-Mem0 extraction."""

from __future__ import annotations

import hashlib
import hmac
import threading
from typing import final

from infinity_context_core.ports.managed_cleanup_v3_contracts import PROFILE_ORACLES

from infinity_context_server.memory_comparison_managed_mem0_v5_extraction_projection import (
    MEM0_V5_EXTRACTION_MAX_TOKENS,
    MEM0_V5_EXTRACTION_MODEL,
    MEM0_V5_EXTRACTION_RESPONSE_FORMAT_SHA256,
    MEM0_V5_EXTRACTION_SCHEMA_SHA256,
    MEM0_V5_EXTRACTION_SYSTEM_PROMPT_SHA256,
    PinnedMem0V5ExtractionRequestProjector,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_http_lane import (
    ManagedMem0V5HttpLane,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestAuthority,
    ManagedMem0V5SourceUnit,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_runtime_attestation import (
    ManagedMem0V5ExpectedRuntimeAuthority,
    VerifiedManagedMem0V5RuntimeAttestationValidation,
    managed_mem0_v5_runtime_validation_is_publishable,
    public_managed_mem0_v5_runtime_validation,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    Mem0OssFullRunAdmission,
    canonical_sha256,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_http import Mem0V5HttpError
from infinity_context_server.memory_comparison_target_identity import (
    mem0_runtime_target_identity_sha256,
)
from infinity_context_server.processes.publishable_full_extraction_contracts import (
    PublishableExtractionCommand,
    PublishableExtractionRecoveryError,
    PublishableExtractionRunAuthority,
)
from infinity_context_server.resumable_operation_journal.domain import sha256_commitment

_ATTESTATION_STATIC_FIELDS = (
    "source_commit_sha1",
    "source_tree_sha1",
    "source_manifest_sha256",
    "source_closure_sha256",
    "phase_c_infinity_commit_sha1",
    "phase_c_infinity_tree_sha1",
    "phase_c_release_manifest_sha256",
    "runtime_binding_commitment_sha256",
    "subscription_runtime_binding_commitment_sha256",
    "runtime_source_sha256",
    "runtime_route_binding_sha256",
    "runtime_transport_origin_sha256",
    "expected_account_binding_hmac_sha256",
    "expected_base_instructions_sha256",
    "extraction_system_prompt_sha256",
    "extraction_response_format_sha256",
    "extraction_response_schema_sha256",
    "requested_output_tokens",
    "output_limit_enforced",
    "usage_attestation_required",
)


class PublishableManagedMem0V5HttpAdapterError(RuntimeError):
    """Stable failure which never reflects HTTP or secret material."""

    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@final
class PublishableManagedMem0V5HttpAdapter:
    """Bind one worker run to the v5 service's dispatch and status endpoints.

    The adapter never retries.  Dispatch and status use distinct deterministic
    idempotency keys, and status has no path to the dispatch endpoint.
    """

    __slots__ = (
        "_admission",
        "_admission_lock",
        "_admitted",
        "_authority",
        "_expected_runtime_binding_sha256",
        "_lane",
        "_manifest",
        "_projector",
        "_run_identity_commitment_sha256",
    )

    def __init__(
        self,
        *,
        authority: PublishableExtractionRunAuthority,
        manifest: ManagedMem0V5ManifestAuthority,
        admission: Mem0OssFullRunAdmission,
        lane: ManagedMem0V5HttpLane,
        expected_runtime: ManagedMem0V5ExpectedRuntimeAuthority,
        runtime_attestation: VerifiedManagedMem0V5RuntimeAttestationValidation,
        runtime_target_identity_sha256: str,
    ) -> None:
        if type(lane) is not ManagedMem0V5HttpLane:
            _fail("publishable_mem0_v5_http_lane_invalid")
        try:
            lane_target_identity = mem0_runtime_target_identity_sha256(
                object.__getattribute__(lane, "_origin")
            )
            dispatch_guard = object.__getattribute__(lane, "_dispatch_guard")
        except Exception:
            _fail("publishable_mem0_v5_http_lane_invalid")
        if dispatch_guard is not None:
            # The existing guard is a write-once micro-canary capability.  It
            # permanently rejects every claim after the first and therefore
            # cannot be composed into either official multi-operation run.
            _fail("publishable_mem0_v5_http_lane_dispatch_guard_forbidden")
        if not hmac.compare_digest(
            lane_target_identity,
            str(runtime_target_identity_sha256),
        ):
            _fail("publishable_mem0_v5_http_lane_cross_wire")
        _validate_static_binding(
            authority=authority,
            manifest=manifest,
            admission=admission,
            expected_runtime=expected_runtime,
            runtime_attestation=runtime_attestation,
            runtime_target_identity_sha256=runtime_target_identity_sha256,
        )
        self._authority = authority
        self._manifest = manifest
        self._admission = admission
        self._admission_lock = threading.RLock()
        self._admitted = False
        self._lane = lane
        self._expected_runtime_binding_sha256 = (
            expected_runtime.subscription_runtime_binding_commitment_sha256
        )
        self._projector = PinnedMem0V5ExtractionRequestProjector()
        self._run_identity_commitment_sha256 = sha256_commitment(
            authority.journal_identity.commitment_payload()
        )

    def dispatch_once(self, *, command: PublishableExtractionCommand) -> object:
        """Perform exactly one HTTP dispatch attempt."""

        unit = self._bound_unit(command)
        self._ensure_admitted()
        return self._lane.dispatch(
            authority=self._manifest,
            unit=unit,
            operation_id_sha256=command.operation_id_sha256,
            admission=self._admission,
        )

    def lookup_outcome(self, *, command: PublishableExtractionCommand) -> object:
        """Read durable status; this method cannot dispatch."""

        unit = self._bound_unit(command)
        self._ensure_admitted()
        return self._lane.status(
            authority=self._manifest,
            unit=unit,
            operation_id_sha256=command.operation_id_sha256,
            admission=self._admission,
        )

    def recover_once(self, *, command: PublishableExtractionCommand) -> object:
        """Probe the exact dispatch key; adapter HMAC state gates any provider call."""

        unit = self._bound_unit(command)
        self._ensure_admitted()
        try:
            return self._lane.dispatch(
                authority=self._manifest,
                unit=unit,
                operation_id_sha256=command.operation_id_sha256,
                admission=self._admission,
            )
        except Mem0V5HttpError as exc:
            if exc.code == "mem0_v5_dispatch_recovery_operator_action_required":
                raise PublishableExtractionRecoveryError("operator_action_required") from None
            raise

    def _ensure_admitted(self) -> None:
        with self._admission_lock:
            if self._admitted:
                return
            try:
                receipt = self._lane.admit(
                    authority=self._manifest,
                    admission=self._admission,
                )
                valid = (
                    receipt.admission_commitment_sha256 == self._admission.commitment_sha256
                    and receipt.runtime_binding_commitment_sha256
                    == self._expected_runtime_binding_sha256
                    and receipt.accepted is True
                )
            except Exception:
                _fail("publishable_mem0_v5_admission_failed")
            if not valid:
                _fail("publishable_mem0_v5_admission_cross_wire")
            self._admitted = True

    def _bound_unit(self, command: object) -> ManagedMem0V5SourceUnit:
        if type(command) is not PublishableExtractionCommand:
            _fail("publishable_mem0_v5_command_invalid")
        try:
            command.__post_init__()
            ordinal = command.ordinal
            operation = self._authority.operation_manifest.operations[ordinal]
            observed = self._authority.runtime_receipt_authority.operations[ordinal]
            unit = self._manifest.units[ordinal]
            projection = self._projector.project(
                unit,
                current_date=self._manifest.current_date,
            )
        except Exception:
            _fail("publishable_mem0_v5_command_cross_wire")
        expected = (
            self._authority.journal_identity.run_id,
            self._run_identity_commitment_sha256,
            operation.logical_operation_id,
            ordinal,
            self._admission.commitment_sha256,
            observed.operation_id_sha256,
            unit.unit_identity_sha256,
            unit.unit_sha256,
            self._admission.request.route_sha256,
            unit.scope_sha256,
            observed.request_body_sha256,
        )
        actual = (
            command.run_id,
            command.run_identity_commitment_sha256,
            command.logical_operation_id,
            command.ordinal,
            command.admission_commitment_sha256,
            command.operation_id_sha256,
            command.unit_identity_sha256,
            command.unit_sha256,
            command.route_sha256,
            command.scope_sha256,
            command.request_body_sha256,
        )
        if (
            actual != expected
            or operation.operation_key != observed.operation_id_sha256
            or operation.authority_commitment_sha256 != self._manifest.authority_commitment_sha256
            or observed.sequence != unit.sequence
            or observed.unit_identity_sha256 != unit.unit_identity_sha256
            or observed.unit_sha256 != unit.unit_sha256
            or observed.scope_sha256 != unit.scope_sha256
            or observed.request_body_sha256 != projection.request_body_sha256
            or projection.response_format_sha256 != MEM0_V5_EXTRACTION_RESPONSE_FORMAT_SHA256
            or projection.response_schema_sha256 != MEM0_V5_EXTRACTION_SCHEMA_SHA256
            or projection.requested_output_tokens != MEM0_V5_EXTRACTION_MAX_TOKENS
        ):
            _fail("publishable_mem0_v5_command_cross_wire")
        return unit


def _validate_static_binding(
    *,
    authority: object,
    manifest: object,
    admission: object,
    expected_runtime: object,
    runtime_attestation: object,
    runtime_target_identity_sha256: object,
) -> None:
    if (
        type(authority) is not PublishableExtractionRunAuthority
        or type(manifest) is not ManagedMem0V5ManifestAuthority
        or type(admission) is not Mem0OssFullRunAdmission
        or type(expected_runtime) is not ManagedMem0V5ExpectedRuntimeAuthority
        or type(runtime_attestation) is not VerifiedManagedMem0V5RuntimeAttestationValidation
        or not _sha(runtime_target_identity_sha256)
    ):
        _fail("publishable_mem0_v5_binding_invalid")
    try:
        authority.__post_init__()
        manifest.__post_init__()
        admission.__post_init__()
        expected_runtime.__post_init__()
    except Exception:
        _fail("publishable_mem0_v5_binding_invalid")
    context = authority.ledger_context
    receipt = authority.runtime_receipt_authority
    request = admission.request
    oracle = PROFILE_ORACLES.get(context.profile_id)
    if (
        oracle is None
        or authority.dataset_sha256 != oracle["dataset_sha256"]
        or manifest.case_count != oracle["case_count"]
        or manifest.corpus_count != oracle["corpus_count"]
        or manifest.operation_count != oracle["operation_count"]
        or authority.journal_identity.expected_operation_count != manifest.operation_count
        or request.expected_operation_count != manifest.operation_count
        or admission.ingestion_unit_count != manifest.operation_count
        or authority.journal_identity.run_id != request.run_id
        or context.run_id_sha256 != hashlib.sha256(request.run_id.encode()).hexdigest()
        or context.admission_commitment_sha256 != admission.commitment_sha256
        or receipt.admission_commitment_sha256 != admission.commitment_sha256
        or context.ingestion_root_sha256 != manifest.ingestion_root_sha256
        or admission.ingestion_manifest_sha256 != manifest.ingestion_manifest_sha256
        or admission.ingestion_root_sha256 != manifest.ingestion_root_sha256
        or request.route_sha256 != receipt.route_binding_sha256
        or request.runtime_source_sha256 != receipt.runtime_source_sha256
        or request.model != receipt.model
        or request.reasoning_effort != receipt.reasoning_effort
        or request.service_tier != receipt.service_tier
        or request.model != MEM0_V5_EXTRACTION_MODEL
        or receipt.response_format_type != "json_schema"
        or receipt.response_format_sha256 != MEM0_V5_EXTRACTION_RESPONSE_FORMAT_SHA256
        or receipt.response_schema_sha256 != MEM0_V5_EXTRACTION_SCHEMA_SHA256
        or receipt.requested_output_tokens != MEM0_V5_EXTRACTION_MAX_TOKENS
    ):
        _fail("publishable_mem0_v5_binding_cross_wire")
    corpus_ids: set[str] = set()
    for ordinal, (unit, observed, operation) in enumerate(
        zip(
            manifest.units,
            receipt.operations,
            authority.operation_manifest.operations,
            strict=True,
        )
    ):
        corpus_ids.add(unit.corpus_id)
        expected_operation_id = canonical_sha256(
            {
                "admission_commitment_sha256": admission.commitment_sha256,
                "unit_index": unit.sequence,
                "unit_identity_sha256": unit.unit_identity_sha256,
            }
        )
        if (
            unit.sequence != ordinal
            or observed.sequence != ordinal
            or operation.ordinal != ordinal
            or observed.operation_id_sha256 != expected_operation_id
            or operation.operation_key != expected_operation_id
            or operation.authority_commitment_sha256 != manifest.authority_commitment_sha256
            or observed.unit_identity_sha256 != unit.unit_identity_sha256
            or observed.unit_sha256 != unit.unit_sha256
            or observed.scope_sha256 != unit.scope_sha256
        ):
            _fail("publishable_mem0_v5_binding_cross_wire")
    if len(corpus_ids) != manifest.corpus_count:
        _fail("publishable_mem0_v5_binding_cross_wire")
    _validate_runtime_binding(
        authority=authority,
        expected=expected_runtime,
        validation=runtime_attestation,
        target_identity_sha256=str(runtime_target_identity_sha256),
    )


def _validate_runtime_binding(
    *,
    authority: PublishableExtractionRunAuthority,
    expected: ManagedMem0V5ExpectedRuntimeAuthority,
    validation: VerifiedManagedMem0V5RuntimeAttestationValidation,
    target_identity_sha256: str,
) -> None:
    receipt = authority.runtime_receipt_authority
    if not managed_mem0_v5_runtime_validation_is_publishable(
        validation, required_runtime_mode="oss"
    ):
        _fail("publishable_mem0_v5_runtime_attestation_invalid")
    public = public_managed_mem0_v5_runtime_validation(validation)
    attestation = public.get("attestation")
    expected_payload = expected.public_payload()
    if type(attestation) is not dict:
        _fail("publishable_mem0_v5_runtime_attestation_invalid")
    if (
        any(
            not hmac.compare_digest(str(attestation.get(name)), str(expected_payload[name]))
            for name in _ATTESTATION_STATIC_FIELDS
        )
        or attestation.get("run_id_sha256") != authority.ledger_context.run_id_sha256
        or attestation.get("target_origin_sha256") != target_identity_sha256
        or expected.subscription_runtime_binding_commitment_sha256
        != authority.ledger_context.runtime_binding_commitment_sha256
        or expected.runtime_source_sha256 != receipt.runtime_source_sha256
        or expected.runtime_route_binding_sha256 != receipt.route_binding_sha256
        or expected.expected_account_binding_hmac_sha256 != receipt.account_binding_hmac_sha256
        or expected.expected_base_instructions_sha256 != receipt.base_instructions_sha256
        or expected.extraction_system_prompt_sha256 != MEM0_V5_EXTRACTION_SYSTEM_PROMPT_SHA256
        or expected.extraction_response_format_sha256 != receipt.response_format_sha256
        or expected.extraction_response_schema_sha256 != receipt.response_schema_sha256
        or expected.requested_output_tokens != receipt.requested_output_tokens
    ):
        _fail("publishable_mem0_v5_runtime_attestation_cross_wire")


def _sha(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _fail(code: str) -> None:
    raise PublishableManagedMem0V5HttpAdapterError(code) from None


__all__ = (
    "PublishableManagedMem0V5HttpAdapter",
    "PublishableManagedMem0V5HttpAdapterError",
)

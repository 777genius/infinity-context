"""Provider-free public composition for one exact managed-v5 live run."""

from __future__ import annotations

import hashlib
import importlib
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import final

from infinity_context_server.memory_comparison_full_profiles import (
    FullComparisonProfile,
    frozen_full_comparison_profile,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_composition import (
    ManagedMem0V5StatePaths,
    preflight_managed_mem0_v5,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_credentials import (
    ManagedMem0V5CredentialPaths,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_extraction_contract_binding import (
    ManagedMem0V5ExtractionContractBinding,
    require_managed_mem0_v5_extraction_contract_binding,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_extraction_projection import (
    PinnedMem0V5ExtractionRequestProjector,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestAuthority,
    ManagedMem0V5ManifestProjector,
    ManagedMem0V5SourceUnit,
)
from infinity_context_server.memory_comparison_managed_plan_builder import (
    ManagedPublicRunProjection,
)
from infinity_context_server.memory_comparison_managed_runner_binding import (
    ManagedRunnerCompositionBinding,
)
from infinity_context_server.memory_comparison_managed_v5_extraction_budget import (
    ManagedV5ExtractionReservationUnit,
    ManagedV5ExtractionTokenBudget,
)
from infinity_context_server.memory_comparison_managed_v5_live_config import (
    ManagedV5LiveConfig,
    ManagedV5LiveRuntimeAuthority,
    _validate_reviewed_phase_c_python_tree,
    validate_managed_v5_live_public_config,
)
from infinity_context_server.memory_comparison_managed_v5_live_public_inputs import (
    ManagedV5LivePublicInputs,
)
from infinity_context_server.memory_comparison_managed_v5_phase_c_preload import (
    ReviewedPhaseCPreloadValidator,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    Mem0OssAdmissionRequest,
    Mem0OssFullRunAdmission,
    canonical_sha256,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_observed_receipt import (
    Mem0V5ObservedExtractionOperationAuthority,
    Mem0V5ObservedExtractionReceiptAuthority,
)
from infinity_context_server.memory_comparison_publishable_methodology import (
    SUBSCRIPTION_RUNTIME_BASE_INSTRUCTIONS_SHA256,
)

_PHASE_C_DOMAIN = "phase_c_canary"
_CHECKPOINT_NAME = "managed-mem0-v5-checkpoint.json"
_CHECKPOINT_HEAD_NAME = "managed-mem0-v5-checkpoint-head.sqlite3"
_LOCK = threading.RLock()


class ManagedV5LivePublicCompositionError(RuntimeError):
    """Stable fail-closed error for public-only live composition."""

    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@final
@dataclass(frozen=True, slots=True)
class ManagedV5LivePublicComposition:
    inputs: ManagedV5LivePublicInputs = field(repr=False)
    manifest_authority: ManagedMem0V5ManifestAuthority
    admission: Mem0OssFullRunAdmission
    extraction_token_budget: ManagedV5ExtractionTokenBudget

    def __post_init__(self) -> None:
        if (
            type(self.inputs) is not ManagedV5LivePublicInputs
            or type(self.manifest_authority) is not ManagedMem0V5ManifestAuthority
            or type(self.admission) is not Mem0OssFullRunAdmission
            or type(self.extraction_token_budget) is not ManagedV5ExtractionTokenBudget
            or self.inputs.extraction_token_budget != self.extraction_token_budget
            or self.inputs.request is not self.admission.request
            or self.admission.ingestion_manifest_sha256
            != self.manifest_authority.ingestion_manifest_sha256
            or self.admission.ingestion_root_sha256 != self.manifest_authority.ingestion_root_sha256
            or self.admission.ingestion_unit_count != self.manifest_authority.operation_count
        ):
            _fail("managed_v5_live_public_composition_invalid")


def compose_managed_v5_live_public_inputs(
    *,
    projection: ManagedPublicRunProjection,
    profile: FullComparisonProfile,
    deadline: datetime,
    current_date: str,
    extraction_contract_binding: ManagedMem0V5ExtractionContractBinding,
    operator_extraction_token_ceiling: int,
    operator_total_token_ceiling: int,
    runtime_authority: ManagedV5LiveRuntimeAuthority,
    config: ManagedV5LiveConfig,
    timeout_seconds: float,
) -> ManagedV5LivePublicComposition:
    """Build and cross-check every public authority without provider or secret I/O."""

    _require_factory_inputs(
        projection=projection,
        profile=profile,
        deadline=deadline,
        current_date=current_date,
        extraction_contract_binding=extraction_contract_binding,
        operator_extraction_token_ceiling=operator_extraction_token_ceiling,
        operator_total_token_ceiling=operator_total_token_ceiling,
        runtime_authority=runtime_authority,
        config=config,
        timeout_seconds=timeout_seconds,
    )
    extraction_projector = PinnedMem0V5ExtractionRequestProjector()
    _require_extraction_binding_authority(
        extraction_contract_binding,
        extraction_projector,
        runtime_authority,
    )
    try:
        validated_authority = validate_managed_v5_live_public_config(config)
    except Exception:
        _fail("managed_v5_live_public_config_invalid")
    if validated_authority != runtime_authority:
        _fail("managed_v5_live_runtime_authority_cross_wire")

    runtime_binding, receipt_boundary = _compose_phase_c_boundary(config, runtime_authority)
    manifest = ManagedMem0V5ManifestProjector().project(
        projection.cases,
        current_date=current_date,
    )
    _require_projection_manifest_parity(projection, manifest)
    request = Mem0OssAdmissionRequest(
        run_id=projection.bindings.run_id,
        route_sha256=runtime_authority.route_binding_sha256,
        credential_binding_sha256=config.filesystem.evidence_key_sha256,
        model=runtime_authority.model,
        reasoning_effort=runtime_authority.reasoning_effort,
        service_tier=runtime_authority.service_tier,
        runtime_source_revision=runtime_authority.runtime_source_revision,
        runtime_source_sha256=runtime_authority.runtime_source_sha256,
        runtime_base_sha256=runtime_authority.runtime_base_sha256,
        expected_operation_count=manifest.operation_count,
    )
    admission = Mem0OssFullRunAdmission(
        request=request,
        ingestion_manifest_sha256=manifest.ingestion_manifest_sha256,
        ingestion_root_sha256=manifest.ingestion_root_sha256,
        ingestion_unit_count=manifest.operation_count,
    )
    projected_operations = tuple(
        _operation_authority(
            unit=unit,
            index=index,
            admission=admission,
            current_date=current_date,
            extraction_contract_binding=extraction_contract_binding,
            extraction_projector=extraction_projector,
            runtime_authority=runtime_authority,
        )
        for index, unit in enumerate(manifest.units)
    )
    operations = tuple(item[0] for item in projected_operations)
    extraction_token_budget = ManagedV5ExtractionTokenBudget.reserve(
        tuple(item[1] for item in projected_operations),
        operator_extraction_token_ceiling=operator_extraction_token_ceiling,
        operator_total_token_ceiling=operator_total_token_ceiling,
    )
    receipt_authority = Mem0V5ObservedExtractionReceiptAuthority(
        admission_commitment_sha256=admission.commitment_sha256,
        model=runtime_authority.model,
        reasoning_effort=runtime_authority.reasoning_effort,
        service_tier=runtime_authority.service_tier,
        base_instructions_sha256=runtime_authority.base_instructions_sha256,
        runtime_source_sha256=runtime_authority.runtime_source_sha256,
        route_binding_sha256=runtime_authority.route_binding_sha256,
        account_binding_hmac_sha256=runtime_authority.account_binding_hmac_sha256,
        node_executable_path=str(config.filesystem.node_executable),
        node_executable_sha256=config.filesystem.node_executable_sha256,
        response_format_type=runtime_authority.response_format_type,
        response_format_sha256=runtime_authority.response_format_sha256,
        response_schema_sha256=runtime_authority.response_schema_sha256,
        operations=operations,
        requested_output_tokens=runtime_authority.requested_output_tokens,
    )
    composition_binding = ManagedRunnerCompositionBinding(
        run_id=projection.bindings.run_id,
        profile=profile,
        binding_commitment_sha256=projection.bindings.binding_commitment_sha256,
        deadline=deadline,
        backend_targets=projection.bindings.backend_targets,
        retrieval_top_k=profile.retrieval_top_k,
        answer_cutoff=profile.answer_cutoff,
    )
    filesystem = config.filesystem
    state_paths = ManagedMem0V5StatePaths(
        filesystem.state_root / _CHECKPOINT_NAME,
        filesystem.state_root / _CHECKPOINT_HEAD_NAME,
    )
    credential_paths = ManagedMem0V5CredentialPaths(
        bearer_token=filesystem.ingress_bearer_file,
        evidence_key=filesystem.evidence_key_file,
        receipt_secret=filesystem.receipt_secret_file,
        checkpoint_signing_key=filesystem.checkpoint_signing_key_file,
        checkpoint_head_key=filesystem.checkpoint_head_key_file,
    )
    inputs = ManagedV5LivePublicInputs(
        cases=projection.cases,
        current_date=current_date,
        request=request,
        composition_binding=composition_binding,
        mem0_origin=config.runtime.mem0_adapter_origin,
        timeout_seconds=float(timeout_seconds),
        state_paths=state_paths,
        credential_paths=credential_paths,
        extraction_contract_binding=extraction_contract_binding,
        extraction_token_budget=extraction_token_budget,
        runtime_receipt_boundary=receipt_boundary,
        trusted_runtime_binding=runtime_binding,
        receipt_authority=receipt_authority,
    )
    try:
        preflight = preflight_managed_mem0_v5(
            cases=inputs.cases,
            current_date=inputs.current_date,
            request=inputs.request,
            origin=inputs.mem0_origin,
            timeout_seconds=inputs.timeout_seconds,
            state_paths=inputs.state_paths,
            credential_paths=inputs.credential_paths,
            runtime_receipt_boundary=inputs.runtime_receipt_boundary,
            trusted_runtime_binding=inputs.trusted_runtime_binding,
            receipt_authority=inputs.receipt_authority,
            transport=None,
        )
    except Exception:
        _fail("managed_v5_live_public_preflight_failed")
    if preflight.authority != manifest or preflight.admission != admission:
        _fail("managed_v5_live_public_preflight_cross_wire")
    return ManagedV5LivePublicComposition(inputs, manifest, admission, extraction_token_budget)


def _operation_authority(
    *,
    unit: ManagedMem0V5SourceUnit,
    index: int,
    admission: Mem0OssFullRunAdmission,
    current_date: str,
    extraction_contract_binding: ManagedMem0V5ExtractionContractBinding,
    extraction_projector: PinnedMem0V5ExtractionRequestProjector,
    runtime_authority: ManagedV5LiveRuntimeAuthority,
) -> tuple[
    Mem0V5ObservedExtractionOperationAuthority,
    ManagedV5ExtractionReservationUnit,
]:
    projected = extraction_projector.project(unit, current_date=current_date)
    if (
        projected.response_format_sha256 != runtime_authority.response_format_sha256
        or projected.response_format_sha256 != extraction_contract_binding.response_format_sha256
        or projected.response_schema_sha256 != runtime_authority.response_schema_sha256
        or projected.response_schema_sha256 != extraction_contract_binding.response_schema_sha256
        or projected.requested_output_tokens != runtime_authority.requested_output_tokens
        or projected.requested_output_tokens != extraction_contract_binding.requested_output_tokens
    ):
        _fail("managed_v5_live_extraction_authority_cross_wire")
    return (
        Mem0V5ObservedExtractionOperationAuthority(
            operation_id_sha256=canonical_sha256(
                {
                    "admission_commitment_sha256": admission.commitment_sha256,
                    "unit_index": index,
                    "unit_identity_sha256": unit.unit_identity_sha256,
                }
            ),
            unit_identity_sha256=unit.unit_identity_sha256,
            unit_sha256=unit.unit_sha256,
            scope_sha256=unit.scope_sha256,
            sequence=index,
            request_body_sha256=projected.request_body_sha256,
        ),
        ManagedV5ExtractionReservationUnit(
            request_body_bytes=projected.request_body_bytes,
            requested_output_tokens=projected.requested_output_tokens,
        ),
    )


def _compose_phase_c_boundary(
    config: ManagedV5LiveConfig,
    runtime_authority: ManagedV5LiveRuntimeAuthority,
) -> tuple[object, object]:
    root = config.filesystem.phase_c_package_root
    package = root / _PHASE_C_DOMAIN
    try:
        tree_before = _validate_reviewed_phase_c_python_tree(
            root,
            config.filesystem.phase_c_python_tree_sha256,
        )
        if package.resolve(strict=True) != package or not package.is_dir():
            raise TypeError
        preload_validator = ReviewedPhaseCPreloadValidator()
        with _LOCK:
            preload_validator.validate(root, tree_before)
            path_entry = str(root)
            sys.path.insert(0, path_entry)
            try:
                authority_module = importlib.import_module(f"{_PHASE_C_DOMAIN}.authority")
                binding_module = importlib.import_module(f"{_PHASE_C_DOMAIN}.runtime_binding")
                receipt_module = importlib.import_module(f"{_PHASE_C_DOMAIN}.receipt")
                boundary_module = importlib.import_module(f"{_PHASE_C_DOMAIN}.runtime_receipt_v2")
                modules_after_import = preload_validator.validate(root, tree_before)
            finally:
                _remove_sys_path_entry(path_entry)
        for module in (authority_module, binding_module, receipt_module, boundary_module):
            module_path = Path(module.__file__).resolve(strict=True)
            if not module_path.is_relative_to(package):
                raise TypeError
        reviewed = authority_module.immutable_authority()
        filesystem = config.filesystem
        if (
            Path(reviewed.runtime_root).resolve(strict=True) / "repo" != filesystem.runtime_repo
            or Path(reviewed.runtime_artifact_manifest.path).resolve(strict=True)
            != filesystem.runtime_artifact_manifest
            or reviewed.runtime_artifact_manifest.sha256
            != filesystem.runtime_artifact_manifest_sha256
            or reviewed.runtime_commit != runtime_authority.runtime_source_revision
            or hashlib.sha256(reviewed.runtime_commit.encode()).hexdigest()
            != runtime_authority.runtime_source_sha256
            or reviewed.stateless_base_sha256 != runtime_authority.runtime_base_sha256
            or reviewed.model != runtime_authority.model
            or reviewed.reasoning_effort != runtime_authority.reasoning_effort
            or reviewed.service_tier != runtime_authority.service_tier
            or reviewed.response_format_type != runtime_authority.response_format_type
            or reviewed.response_format_sha256 != runtime_authority.response_format_sha256
            or reviewed.response_schema_sha256 != runtime_authority.response_schema_sha256
            or reviewed.requested_output_tokens != runtime_authority.requested_output_tokens
        ):
            raise TypeError
        service = binding_module.RuntimeBindingComposition.compose_phase_c_canary()
        binding = service.issue()
        binding_module.require_trusted_runtime_binding(binding)
        if (
            binding.runtime_source_sha256 != runtime_authority.runtime_source_sha256
            or binding.route_binding_sha256 != runtime_authority.route_binding_sha256
        ):
            raise TypeError
        verifier = receipt_module.NodePublicReceiptVerifier(
            runtime_repo=filesystem.runtime_repo,
            node_executable=filesystem.node_executable,
        )
        boundary = boundary_module.RuntimeReceiptV2Boundary(verifier)
        if (
            type(binding) is not binding_module.TrustedRuntimeBinding
            or type(verifier) is not receipt_module.NodePublicReceiptVerifier
            or type(boundary) is not boundary_module.RuntimeReceiptV2Boundary
        ):
            raise TypeError
        tree_after = _validate_reviewed_phase_c_python_tree(
            root,
            config.filesystem.phase_c_python_tree_sha256,
        )
        if tree_after != tree_before:
            raise TypeError
        with _LOCK:
            if preload_validator.validate(root, tree_after) != modules_after_import:
                raise TypeError
        return binding, boundary
    except Exception:
        _fail("managed_v5_live_phase_c_authority_invalid")


def _remove_sys_path_entry(path_entry: str) -> None:
    for index, candidate in enumerate(sys.path):
        if candidate is path_entry:
            del sys.path[index]
            return


def _require_factory_inputs(
    *,
    projection: object,
    profile: object,
    deadline: object,
    current_date: object,
    extraction_contract_binding: object,
    operator_extraction_token_ceiling: object,
    operator_total_token_ceiling: object,
    runtime_authority: object,
    config: object,
    timeout_seconds: object,
) -> None:
    try:
        trusted_profile = frozen_full_comparison_profile(profile)
        require_managed_mem0_v5_extraction_contract_binding(extraction_contract_binding)
    except Exception:
        _fail("managed_v5_live_public_composition_inputs_invalid")
    if (
        type(projection) is not ManagedPublicRunProjection
        or type(profile) is not FullComparisonProfile
        or projection.bindings.profile_id != trusted_profile.profile_id
        or type(deadline) is not datetime
        or deadline.tzinfo is None
        or deadline.utcoffset() is None
        or type(current_date) is not str
        or not current_date
        or type(runtime_authority) is not ManagedV5LiveRuntimeAuthority
        or type(extraction_contract_binding) is not ManagedMem0V5ExtractionContractBinding
        or type(operator_extraction_token_ceiling) is not int
        or operator_extraction_token_ceiling < 1
        or type(operator_total_token_ceiling) is not int
        or operator_total_token_ceiling < 1
        or type(config) is not ManagedV5LiveConfig
        or type(timeout_seconds) not in (int, float)
        or isinstance(timeout_seconds, bool)
        or not 0.01 <= float(timeout_seconds) <= 120.0
    ):
        _fail("managed_v5_live_public_composition_inputs_invalid")


def _require_extraction_binding_authority(
    binding: ManagedMem0V5ExtractionContractBinding,
    projector: PinnedMem0V5ExtractionRequestProjector,
    runtime_authority: ManagedV5LiveRuntimeAuthority,
) -> None:
    if (
        binding.implementation_domain != projector.implementation_domain
        or binding.implementation_sha256 != projector.implementation_sha256
        or binding.model != runtime_authority.model
        or runtime_authority.base_instructions_sha256
        != SUBSCRIPTION_RUNTIME_BASE_INSTRUCTIONS_SHA256
        or binding.system_prompt_sha256 != runtime_authority.extraction_system_prompt_sha256
        or binding.response_format_sha256 != runtime_authority.response_format_sha256
        or binding.response_schema_sha256 != runtime_authority.response_schema_sha256
        or binding.requested_output_tokens != runtime_authority.requested_output_tokens
    ):
        _fail("managed_v5_live_extraction_authority_cross_wire")


def _require_projection_manifest_parity(
    projection: ManagedPublicRunProjection,
    manifest: ManagedMem0V5ManifestAuthority,
) -> None:
    case_corpora = tuple(dict.fromkeys(item.corpus_id for item in projection.cases))
    manifest_corpora = tuple(dict.fromkeys(item.corpus_id for item in manifest.units))
    if (
        manifest.operation_count <= 0
        or manifest.case_count != len(projection.cases)
        or manifest.corpus_count != len(case_corpora)
        or manifest_corpora != case_corpora
    ):
        _fail("managed_v5_live_projection_manifest_cross_wire")


def _fail(code: str) -> None:
    raise ManagedV5LivePublicCompositionError(code) from None


__all__ = (
    "ManagedV5LivePublicComposition",
    "ManagedV5LivePublicCompositionError",
    "compose_managed_v5_live_public_inputs",
)

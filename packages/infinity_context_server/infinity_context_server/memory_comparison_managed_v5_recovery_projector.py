"""Provider-free reconstruction of cleanup-plan public inputs."""

from __future__ import annotations

import hashlib
import os
import stat
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from infinity_context_server.memory_comparison_backend_target import (
    FullComparisonBackendTarget,
)
from infinity_context_server.memory_comparison_full_profiles import (
    frozen_full_comparison_profile,
    resolve_full_comparison_profile,
)
from infinity_context_server.memory_comparison_full_scope import FULL_COMPARISON_SCOPE_CANARY
from infinity_context_server.memory_comparison_managed_mem0_auth import (
    MANAGED_MEM0_DATA_PLANE_AUTH_API_KEY,
    MANAGED_MEM0_DATA_PLANE_AUTH_NONE,
    expected_managed_mem0_runtime_mode,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_extraction_contract_binding import (
    ManagedMem0V5ExtractionContractBinding,
    require_managed_mem0_v5_extraction_contract_binding,
)
from infinity_context_server.memory_comparison_managed_plan_builder import (
    build_managed_public_run_projection,
)
from infinity_context_server.memory_comparison_managed_preflight import (
    managed_backend_target_identity_sha256,
)
from infinity_context_server.memory_comparison_managed_v5_cleanup_plan_builder import (
    ManagedV5CleanupPlanInputs,
)
from infinity_context_server.memory_comparison_managed_v5_live_config import (
    ManagedV5LiveConfig,
    validate_managed_v5_live_public_config,
)
from infinity_context_server.memory_comparison_managed_v5_live_public_composition import (
    ManagedV5LivePublicComposition,
    compose_managed_v5_live_public_inputs,
)
from infinity_context_server.memory_comparison_managed_v5_recovery_contracts import (
    ManagedV5LiveRecoveryAuthority,
    managed_v5_live_config_commitment_sha256,
)

_MAX_DATASET_BYTES = 402_653_184


class ManagedV5RecoveryProjectorError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ManagedV5RecoveryPublicProjection:
    cleanup_plan_inputs: ManagedV5CleanupPlanInputs
    public_composition: ManagedV5LivePublicComposition

    def __post_init__(self) -> None:
        if (
            type(self.cleanup_plan_inputs) is not ManagedV5CleanupPlanInputs
            or type(self.public_composition) is not ManagedV5LivePublicComposition
            or self.cleanup_plan_inputs.manifest_authority
            != self.public_composition.manifest_authority
            or self.cleanup_plan_inputs.admission != self.public_composition.admission
        ):
            _fail("managed_v5_recovery_projection_invalid")


def rebuild_managed_v5_cleanup_plan_inputs(
    *,
    authority: ManagedV5LiveRecoveryAuthority,
    config: ManagedV5LiveConfig,
) -> ManagedV5CleanupPlanInputs:
    """Rebuild exact public projection using only journaled authority and public files."""

    return rebuild_managed_v5_recovery_public_projection(
        authority=authority, config=config
    ).cleanup_plan_inputs


def rebuild_managed_v5_recovery_public_projection(
    *, authority: ManagedV5LiveRecoveryAuthority, config: ManagedV5LiveConfig
) -> ManagedV5RecoveryPublicProjection:
    """Rebuild the exact cleanup and Mem0 public composition without private imports."""

    if (
        type(authority) is not ManagedV5LiveRecoveryAuthority
        or type(config) is not ManagedV5LiveConfig
    ):
        _fail("managed_v5_recovery_projection_inputs_invalid")
    if (
        managed_v5_live_config_commitment_sha256(
            config=config,
            extraction_contract_file=authority.extraction_contract_file,
            extraction_contract_sha256=authority.extraction_contract_sha256,
        )
        != authority.managed_v5_config_commitment_sha256
    ):
        _fail("managed_v5_recovery_config_mismatch")
    dataset = _read_dataset(authority.dataset_path)
    if hashlib.sha256(dataset).hexdigest() != authority.dataset_sha256:
        _fail("managed_v5_recovery_dataset_mismatch")
    try:
        profile = resolve_full_comparison_profile(authority.profile_id)
        if profile is None:
            raise TypeError
        profile = frozen_full_comparison_profile(profile)
        runtime = validate_managed_v5_live_public_config(config)
        extraction = ManagedMem0V5ExtractionContractBinding(
            authority.extraction_contract_file,
            authority.extraction_contract_sha256,
        )
        require_managed_mem0_v5_extraction_contract_binding(extraction)
        mode = expected_managed_mem0_runtime_mode(
            data_plane_auth_mode=(
                MANAGED_MEM0_DATA_PLANE_AUTH_NONE
                if authority.mem0_local_auth_disabled_managed
                else MANAGED_MEM0_DATA_PLANE_AUTH_API_KEY
            ),
            profile_runtime_mode=profile.required_mem0_runtime_mode,
        )
        targets = (
            FullComparisonBackendTarget(
                "infinity-context",
                managed_backend_target_identity_sha256(
                    backend_role="infinity-context", base_url=authority.infinity_origin
                ),
            ),
            FullComparisonBackendTarget(
                "mem0",
                managed_backend_target_identity_sha256(
                    backend_role="mem0", base_url=authority.mem0_origin
                ),
            ),
        )
        projection = build_managed_public_run_projection(
            run_id=authority.run_id,
            run_nonce_commitment_sha256=authority.run_nonce_commitment_sha256,
            runtime_probe_nonce_sha256=authority.runtime_probe_nonce_sha256,
            profile=profile,
            dataset_bytes=dataset,
            backend_targets=targets,
            scope=FULL_COMPARISON_SCOPE_CANARY,
            mem0_expected_runtime_mode=mode,
            selected_case_ids=authority.selected_case_ids,
        )
        deadline = _timestamp(authority.deadline)
        composition = compose_managed_v5_live_public_inputs(
            projection=projection,
            profile=profile,
            deadline=deadline,
            current_date=authority.current_date,
            extraction_contract_binding=extraction,
            operator_extraction_token_ceiling=authority.max_extraction_tokens,
            operator_total_token_ceiling=authority.max_total_tokens,
            runtime_authority=runtime,
            config=config,
            timeout_seconds=authority.request_timeout_seconds,
        )
    except ManagedV5RecoveryProjectorError:
        raise
    except Exception:
        _fail("managed_v5_recovery_projection_invalid")
    infinity_target = next(
        target.target_identity_sha256
        for target in projection.bindings.backend_targets
        if target.backend_role == "infinity-context"
    )
    if (
        projection.bindings.run_id != authority.run_id
        or projection.bindings.binding_commitment_sha256 != authority.binding_commitment_sha256
        or infinity_target != authority.infinity_target_identity_sha256
        or composition.manifest_authority.ingestion_manifest_sha256
        != composition.admission.ingestion_manifest_sha256
    ):
        _fail("managed_v5_recovery_projection_mismatch")
    cleanup_inputs = ManagedV5CleanupPlanInputs(
        projection=projection,
        manifest_authority=composition.manifest_authority,
        admission=composition.admission,
        profile_id=profile.profile_id,
        run_id=authority.run_id,
    )
    return ManagedV5RecoveryPublicProjection(cleanup_inputs, composition)


def _read_dataset(path: Path) -> bytes:
    descriptor: int | None = None
    try:
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        if not isinstance(path, Path) or not path.is_absolute() or nofollow == 0:
            raise OSError
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK | nofollow,
        )
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or not 1 <= before.st_size <= _MAX_DATASET_BYTES
        ):
            raise OSError
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(1_048_576, remaining))
            if not chunk:
                raise OSError
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise OSError
        after = os.fstat(descriptor)
        if _dataset_snapshot(before) != _dataset_snapshot(after):
            raise OSError
        value = b"".join(chunks)
    except OSError:
        _fail("managed_v5_recovery_dataset_unreadable")
    finally:
        if descriptor is not None:
            with suppress(OSError):
                os.close(descriptor)
    if len(value) != before.st_size:
        _fail("managed_v5_recovery_dataset_unreadable")
    return value


def _dataset_snapshot(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_uid,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        _fail("managed_v5_recovery_authority_invalid")
    if parsed.tzinfo is None:
        _fail("managed_v5_recovery_authority_invalid")
    return parsed


def _fail(code: str) -> None:
    raise ManagedV5RecoveryProjectorError(code)


__all__ = (
    "ManagedV5RecoveryPublicProjection",
    "ManagedV5RecoveryProjectorError",
    "rebuild_managed_v5_cleanup_plan_inputs",
    "rebuild_managed_v5_recovery_public_projection",
)

"""Provider-free recovery journal and cleanup-plan preparation for the live CLI."""

from __future__ import annotations

import hashlib
from datetime import datetime

from infinity_context_core.ports.benchmark_cleanup_plan import ManagedBenchmarkCleanupPlan

from infinity_context_server.memory_comparison_managed_benchmark_registry_contracts import (
    ManagedBenchmarkRegistryHttpConfig,
)
from infinity_context_server.memory_comparison_managed_benchmark_registry_http import (
    ManagedBenchmarkRegistryHttpAdapter,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_credentials import (
    _read_private_secret,
    _wipe,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestAuthority,
)
from infinity_context_server.memory_comparison_managed_plan_builder import (
    ManagedPublicRunProjection,
)
from infinity_context_server.memory_comparison_managed_v5_cleanup_plan_builder import (
    ManagedV5CleanupPlanInputs,
    build_managed_v5_cleanup_plan,
)
from infinity_context_server.memory_comparison_managed_v5_live_config import (
    ManagedV5LiveFilesystemConfig,
)
from infinity_context_server.memory_comparison_managed_v5_recovery_contracts import (
    ManagedV5LiveRecoveryAuthority,
)
from infinity_context_server.memory_comparison_managed_v5_recovery_journal import (
    ManagedV5LiveRecoveryJournalStore,
    RecoveryJournalAuthenticator,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    Mem0OssFullRunAdmission,
)


class ManagedV5LiveRecoveryPrepareError(RuntimeError):
    """Stable preparation failure translated by the CLI boundary."""

    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def initialize_managed_v5_live_recovery_journal(
    *,
    filesystem: ManagedV5LiveFilesystemConfig,
    recovery_authority: ManagedV5LiveRecoveryAuthority,
) -> tuple[ManagedV5LiveRecoveryJournalStore, str]:
    """Open and authenticate the recovery journal before secret/provider work."""

    loaded = _read_private_secret(filesystem.recovery_hmac_secret_file)
    authenticator = None
    store = None
    try:
        secret = bytes(loaded.value)
        commitment = hashlib.sha256(secret).hexdigest()
        authenticator = RecoveryJournalAuthenticator(
            secret=secret,
            run_id_sha256=recovery_authority.run_id_sha256,
        )
        store = ManagedV5LiveRecoveryJournalStore(
            path=filesystem.recovery_journal,
            state_root=filesystem.state_root,
            authenticator=authenticator,
        )
        store.initialize(
            authority=recovery_authority,
            recorded_at=recovery_authority.issued_at,
            details={"authority_sha256": recovery_authority.sha256},
        )
        return store, commitment
    except Exception:
        if store is not None:
            store.close()
        if authenticator is not None:
            authenticator.close()
        raise ManagedV5LiveRecoveryPrepareError(
            "managed_v5_live_recovery_journal_initialization_failed"
        ) from None
    finally:
        _wipe(loaded.value)


def prepare_managed_v5_live_cleanup_plan(
    *,
    infinity_api_url: str,
    infinity_token: str,
    infinity_target_identity_sha256: str,
    request_timeout_seconds: float,
    benchmark_deadline: datetime,
    projection: ManagedPublicRunProjection,
    manifest_authority: ManagedMem0V5ManifestAuthority,
    admission: Mem0OssFullRunAdmission,
    profile_id: str,
    run_id: str,
    recovery_journal: object,
) -> tuple[ManagedBenchmarkCleanupPlan, str]:
    """Read target authority and build the exact cleanup plan without providers."""

    if type(recovery_journal) is not ManagedV5LiveRecoveryJournalStore:
        raise ManagedV5LiveRecoveryPrepareError("managed_v5_live_recovery_journal_invalid")
    config = ManagedBenchmarkRegistryHttpConfig(
        base_url=infinity_api_url,
        admin_bearer_token=infinity_token,
        target_identity_sha256=infinity_target_identity_sha256,
        timeout_seconds=request_timeout_seconds,
        benchmark_deadline=benchmark_deadline,
        cleanup_recovery_timeout_seconds=request_timeout_seconds,
    )
    registry = ManagedBenchmarkRegistryHttpAdapter(config)
    try:
        target = registry.prepare_cleanup_target_authority()
    finally:
        registry.close()
    plan = build_managed_v5_cleanup_plan(
        inputs=ManagedV5CleanupPlanInputs(
            projection=projection,
            manifest_authority=manifest_authority,
            admission=admission,
            profile_id=profile_id,
            run_id=run_id,
        ),
        target_authority=target,
    )
    return plan, target.authority_sha256

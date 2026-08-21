"""Legacy-v2 cleanup-plan compatibility adapter, isolated from strict-v4 imports."""

from __future__ import annotations

from typing import Protocol, final

from infinity_context_core.domain.errors import MemoryValidationError
from infinity_context_core.ports.benchmark_cleanup_plan import (
    ManagedBenchmarkCleanupPlan,
    managed_benchmark_cleanup_plan_material_sha256,
)
from infinity_context_core.ports.managed_cleanup_v3_contracts import digest
from infinity_context_core.ports.managed_cleanup_v4_authority import (
    ManagedCleanupV4Authority,
    ManagedCleanupV4AuthorityError,
    build_legacy_v2_cleanup_authority,
)


class LegacyV2CleanupPlanPort(Protocol):
    async def load_cleanup_plan(self, space_id: str) -> ManagedBenchmarkCleanupPlan | None: ...


@final
class LegacyV2CleanupAuthorityAdapter:
    """Preserve the current v2 cleanup-plan loading boundary."""

    def __init__(
        self,
        *,
        run_id_sha256: str,
        space_id: str,
        cleanup_plans: LegacyV2CleanupPlanPort,
    ) -> None:
        _digest(run_id_sha256)
        if type(space_id) is not str or not space_id:
            _fail("managed_cleanup_v4_legacy_binding_invalid")
        if not callable(getattr(cleanup_plans, "load_cleanup_plan", None)):
            _fail("managed_cleanup_v4_legacy_port_invalid")
        self._run_id_sha256 = run_id_sha256
        self._space_id = space_id
        self._cleanup_plans = cleanup_plans

    async def resolve(self) -> ManagedCleanupV4Authority:
        plan = await self._cleanup_plans.load_cleanup_plan(self._space_id)
        if type(plan) is not ManagedBenchmarkCleanupPlan:
            _fail("managed_cleanup_v4_legacy_authority_missing")
        canonical_sha256 = managed_benchmark_cleanup_plan_material_sha256(plan.value)
        if (
            canonical_sha256 != plan.sha256
            or plan.value.get("run_id_sha256") != self._run_id_sha256
        ):
            _fail("managed_cleanup_v4_legacy_binding_invalid")
        return build_legacy_v2_cleanup_authority(
            run_id_sha256=self._run_id_sha256,
            legacy_plan_sha256=canonical_sha256,
        )


def _digest(value: object) -> str:
    try:
        return digest(value)
    except MemoryValidationError as exc:
        raise ManagedCleanupV4AuthorityError("managed_cleanup_v4_digest_invalid") from exc


def _fail(code: str) -> None:
    raise ManagedCleanupV4AuthorityError(code)


__all__ = ("LegacyV2CleanupAuthorityAdapter", "LegacyV2CleanupPlanPort")

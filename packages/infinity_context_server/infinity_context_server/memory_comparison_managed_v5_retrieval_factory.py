"""Provider-free exact retrieval composition for the managed v5 cutover."""

from __future__ import annotations

from infinity_context_server.memory_comparison_full_profiles import INFINITY_COMPARISON_BACKEND
from infinity_context_server.memory_comparison_managed_infinity_http_execution import (
    ManagedInfinityHttpExecutionAdapter,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_runner_adapter import (
    ManagedMem0V5RetrievalAdapter,
)
from infinity_context_server.memory_comparison_managed_runner_binding import (
    ManagedRunnerCompositionBinding,
)
from infinity_context_server.memory_comparison_managed_target_aware_retrieval_router import (
    ManagedTargetAwareRetrievalRoute,
    ManagedTargetAwareRetrievalRouter,
)


class ManagedV5RetrievalFactoryError(RuntimeError):
    pass


def create_managed_v5_target_aware_retrieval(
    *,
    composition_binding: ManagedRunnerCompositionBinding,
    infinity: ManagedInfinityHttpExecutionAdapter,
    mem0: ManagedMem0V5RetrievalAdapter,
) -> ManagedTargetAwareRetrievalRouter:
    """Build exactly two real delegates in exact target order, with no fallback."""

    if (
        type(composition_binding) is not ManagedRunnerCompositionBinding
        or type(infinity) is not ManagedInfinityHttpExecutionAdapter
        or type(mem0) is not ManagedMem0V5RetrievalAdapter
    ):
        raise ManagedV5RetrievalFactoryError("managed_v5_retrieval_composition_invalid")
    try:
        exact_binding = (
            infinity.composition_binding is composition_binding
            and mem0.composition_binding is composition_binding
        )
    except Exception:
        exact_binding = False
    if not exact_binding:
        raise ManagedV5RetrievalFactoryError("managed_v5_retrieval_composition_invalid")
    targets = tuple(
        (item.backend_role, item.target_identity_sha256)
        for item in composition_binding.backend_targets
    )
    if tuple(role for role, _target in targets) != (INFINITY_COMPARISON_BACKEND, "mem0"):
        raise ManagedV5RetrievalFactoryError("managed_v5_retrieval_targets_invalid")
    delegates = (infinity, mem0)
    routes = tuple(
        ManagedTargetAwareRetrievalRoute(
            backend_role=role,
            target_identity_sha256=target,
            delegate=delegate,
            adapter_id=delegate.adapter_id,
            implementation_sha256=delegate.implementation_sha256,
        )
        for (role, target), delegate in zip(targets, delegates, strict=True)
    )
    try:
        return ManagedTargetAwareRetrievalRouter(
            composition_binding=composition_binding,
            routes=routes,
        )
    except Exception:
        raise ManagedV5RetrievalFactoryError("managed_v5_retrieval_router_invalid") from None


__all__ = (
    "ManagedV5RetrievalFactoryError",
    "create_managed_v5_target_aware_retrieval",
)

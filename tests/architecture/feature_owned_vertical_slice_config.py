"""Explicit non-slice classifications for the vertical-slice architecture gate."""

from __future__ import annotations

# ADR-0007 defines business feature ids mirrored across deployable packages. These
# two namespaces instead own bounded cross-feature runtime support and therefore do
# not have the domain/application/ports shape required of a core feature capsule.
# Keeping the classification root-specific prevents either name from becoming a
# blanket feature id in another package.
NON_VERTICAL_SLICE_SUPPORT_COMPONENTS_BY_ROOT = {
    "packages/infinity_context_core/infinity_context_core/features": frozenset(
        {"projection_receipts"}
    ),
    "packages/infinity_context_server/infinity_context_server/features": frozenset(
        {"subscription_runtime_bridge"}
    ),
}

# These compatibility seams adapt legacy context selection to the feature-owned
# policy. Every exception is an exact source-path/module pair.
INTERNAL_POLICY_ADAPTER_IMPORTS = frozenset(
    {
        (
            "packages/infinity_context_core/infinity_context_core/application/"
            "context_packer_selection.py",
            "infinity_context_core.features.context_building.application."
            "coverage_reservation_selector",
        ),
        (
            "packages/infinity_context_core/infinity_context_core/application/"
            "context_packer_selection.py",
            "infinity_context_core.features.context_building.domain.evidence_obligations",
        ),
        (
            "tests/unit/test_context_coverage_reservation_selector.py",
            "infinity_context_core.features.context_building.application."
            "coverage_reservation_selector",
        ),
        (
            "tests/unit/test_context_coverage_reservation_selector.py",
            "infinity_context_core.features.context_building.domain.evidence_obligations",
        ),
    }
)

# Strict-v4 canonical-write compatibility landed against the feature internals.
# Preserve that known seam without allowing any other file or internal module.
STRICT_V4_MEMORY_FACTS_TRANSITIONAL_IMPORTS = frozenset(
    {
        (
            "packages/infinity_context_core/infinity_context_core/application/"
            "benchmark_managed_write_admission.py",
            "infinity_context_core.features.memory_facts.application.commands",
        ),
        (
            "packages/infinity_context_server/infinity_context_server/"
            "memory_comparison_managed_v5_strict_v4_fact_ingest.py",
            "infinity_context_core.features.memory_facts.application.commands",
        ),
        (
            "packages/infinity_context_server/infinity_context_server/"
            "memory_comparison_managed_v5_strict_v4_fact_ingest.py",
            "infinity_context_core.features.memory_facts.domain",
        ),
        (
            "tests/e2e/test_strict_v4_writer_fence_postgres.py",
            "infinity_context_core.features.memory_facts.application.commands",
        ),
        (
            "tests/e2e/test_strict_v4_writer_fence_postgres.py",
            "infinity_context_core.features.memory_facts.domain",
        ),
        (
            "tests/unit/test_benchmark_managed_write_admission.py",
            "infinity_context_core.features.memory_facts.application.commands",
        ),
        (
            "tests/unit/test_benchmark_managed_write_admission.py",
            "infinity_context_core.features.memory_facts.domain",
        ),
        (
            "tests/unit/test_postgres_managed_fact_admission.py",
            "infinity_context_core.features.memory_facts.application.commands",
        ),
        (
            "tests/unit/test_postgres_managed_fact_admission.py",
            "infinity_context_core.features.memory_facts.application.handlers",
        ),
        (
            "tests/unit/test_postgres_managed_fact_admission.py",
            "infinity_context_core.features.memory_facts.domain",
        ),
        (
            "tests/unit/test_projection_result_receipts.py",
            "infinity_context_core.features.memory_facts.domain",
        ),
        (
            "tests/unit/test_projection_result_receipts.py",
            "infinity_context_core.features.memory_facts.ports",
        ),
    }
)

TRANSITIONAL_CORE_FEATURE_INTERNAL_IMPORTS = (
    INTERNAL_POLICY_ADAPTER_IMPORTS | STRICT_V4_MEMORY_FACTS_TRANSITIONAL_IMPORTS
)

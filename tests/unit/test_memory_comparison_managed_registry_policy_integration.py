from __future__ import annotations

import pytest
from infinity_context_server.memory_comparison_managed_benchmark_registry_contracts import (
    ManagedBenchmarkCleanupCompletionReceipt,
)
from test_memory_comparison_managed_registry_policy_lifecycle import (  # noqa: E402
    _ATTESTATION,
    _ATTESTATION_COMMITMENT,
    _delete_all,
    _seal_source,
    _seal_terminal,
    _wrapper,
)


def test_registry_policy_completes_exact_seal_cleanup_finalize_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise the real registry policy/delegate pair over fake HTTP transports."""

    for name in ("OPENAI_API_KEY", "INFINITY_CONTEXT_API_KEY", "MEM0_API_KEY"):
        monkeypatch.delenv(name, raising=False)

    wrapper, bindings, cases, registry, events = _wrapper(monkeypatch)

    canonical, _ = _seal_source(wrapper, bindings, cases)
    deletes = _delete_all(wrapper, bindings)
    terminal = _seal_terminal(wrapper, bindings, deletes)
    validation = wrapper.aggregate_policy(
        bindings=bindings,
        managed_attestation=_ATTESTATION,
        managed_attestation_commitment_sha256=_ATTESTATION_COMMITMENT,
        canonical_source=canonical,
        terminal_delete=terminal,
    )

    completion = wrapper.terminal_completion_receipt
    assert type(completion) is ManagedBenchmarkCleanupCompletionReceipt
    assert completion.state == "cleanup_complete"
    assert completion.projection_cleanup == "complete"
    assert validation is not None
    assert registry.seal_attempts == registry.begin_attempts == registry.finalize_attempts == 1
    assert registry.manifest_sha256 is not None

    registry_events = [event for event in events if event.startswith("registry.")]
    assert registry_events == [
        "registry.register",
        "registry.seal",
        "registry.begin",
        "registry.finalize",
    ]
    assert events.index("delegate.presence") < events.index("registry.seal")
    assert events.index("registry.begin") < events.index("delegate.canonical-delete")
    assert events[-1] == "registry.finalize"

from __future__ import annotations

import pytest
from infinity_context_server import memory_comparison_managed_production_ports as subject
from infinity_context_server.memory_comparison_managed_http_lifecycle import (
    ManagedComparisonHttpLifecycleAdapter,
)


def _lifecycle() -> ManagedComparisonHttpLifecycleAdapter:
    return object.__new__(ManagedComparisonHttpLifecycleAdapter)


def test_factory_exposes_distinct_operation_specific_ports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle = _lifecycle()
    calls: list[tuple[str, dict[str, object]]] = []
    receipt = object()

    def reset(_self: object, **kwargs: object) -> None:
        calls.append(("reset", kwargs))

    def ingest(_self: object, **kwargs: object) -> object:
        calls.append(("ingest", kwargs))
        return receipt

    monkeypatch.setattr(ManagedComparisonHttpLifecycleAdapter, "reset", reset)
    monkeypatch.setattr(ManagedComparisonHttpLifecycleAdapter, "ingest", ingest)

    ports = subject.create_managed_production_lifecycle_ports(lifecycle)

    assert ports.reset is not ports.ingest
    assert ports.reset.adapter_id != ports.ingest.adapter_id
    assert ports.reset.implementation_sha256 != ports.ingest.implementation_sha256

    ports.reset.reset(
        run_id="run-1",
        binding_commitment_sha256="a" * 64,
        backend_targets=(("infinity-context", "b" * 64), ("mem0", "c" * 64)),
    )
    observed = ports.ingest.ingest(
        run_id="run-1",
        backend_role="mem0",
        target_identity_sha256="c" * 64,
        record={"benchmark": "locomo"},
    )

    assert observed is receipt
    assert calls == [
        (
            "reset",
            {
                "run_id": "run-1",
                "binding_commitment_sha256": "a" * 64,
                "backend_targets": (
                    ("infinity-context", "b" * 64),
                    ("mem0", "c" * 64),
                ),
            },
        ),
        (
            "ingest",
            {
                "run_id": "run-1",
                "backend_role": "mem0",
                "target_identity_sha256": "c" * 64,
                "record": {"benchmark": "locomo"},
            },
        ),
    ]


def test_factory_rejects_non_lifecycle_object() -> None:
    with pytest.raises(
        subject.ManagedProductionPortError,
        match="managed_production_lifecycle_invalid",
    ):
        subject.create_managed_production_lifecycle_ports(object())  # type: ignore[arg-type]


def test_facade_revalidates_lifecycle_provenance_before_delegation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle = _lifecycle()
    ports = subject.create_managed_production_lifecycle_ports(lifecycle)
    monkeypatch.setattr(
        ManagedComparisonHttpLifecycleAdapter,
        "implementation_sha256",
        property(lambda _self: "f" * 64),
    )

    with pytest.raises(
        subject.ManagedProductionPortError,
        match="managed_production_lifecycle_changed",
    ):
        ports.reset.reset(
            run_id="run-1",
            binding_commitment_sha256="a" * 64,
            backend_targets=(),
        )


def test_port_types_are_final() -> None:
    with pytest.raises(TypeError):

        class _Reset(subject.ManagedProductionResetPort):
            pass

    with pytest.raises(TypeError):

        class _Ingest(subject.ManagedProductionIngestPort):
            pass

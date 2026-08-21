from __future__ import annotations

import hashlib
import json
import threading
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from infinity_context_server.memory_comparison_managed_benchmark_registry_contracts import (
    ManagedBenchmarkCleanupCompletionReceipt,
    ManagedBenchmarkRunLifecycleSnapshot,
)
from infinity_context_server.memory_comparison_managed_benchmark_registry_http import (
    ManagedBenchmarkRegistryHttpAdapter,
)
from infinity_context_server.memory_comparison_managed_projection_manifest import (
    ManagedProjectionManifest,
)
from infinity_context_server.memory_comparison_managed_registry_policy_lifecycle import (
    ManagedComparisonRegistryPolicyLifecycleAdapter,
)
from infinity_context_server.memory_comparison_managed_v5_live_recovery_observer import (
    ManagedMem0TerminalObservation,
    ManagedV5LiveRecoveryObserver,
)


class _Journal:
    def __init__(self, events: list[str], *, fail: str | None = None) -> None:
        self.events = events
        self.fail = fail
        self.calls: list[dict[str, object]] = []

    def append(self, **kwargs: object) -> None:
        kind = kwargs["kind"]
        self.events.append(f"journal.{kind}")
        if kind == self.fail:
            raise RuntimeError("fsync failed")
        self.calls.append(dict(kwargs))


class _Observer:
    def __init__(self, events: list[str], *, fail_projection: bool = False) -> None:
        self.events = events
        self.fail_projection = fail_projection

    def projection_manifest_persisted(self, value: object) -> None:
        self.events.append("journal.projection")
        if self.fail_projection:
            raise RuntimeError("fsync failed")

    def registry_seal_observed(self, value: object) -> None:
        self.events.append("journal.seal")


class _Registry:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def seal_projection_manifest(self, **kwargs: object) -> object:
        self.events.append("registry.seal")
        raise AssertionError("seal must not run after journal failure")


def _manifest() -> ManagedProjectionManifest:
    value: dict[str, object] = {}
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"))
    result = object.__new__(ManagedProjectionManifest)
    object.__setattr__(result, "canonical_json", raw)
    object.__setattr__(
        result,
        "projection_manifest_sha256",
        hashlib.sha256(raw.encode()).hexdigest(),
    )
    return result


def _observer(journal: _Journal, *, fresh: object | None = None) -> ManagedV5LiveRecoveryObserver:
    value = object.__new__(ManagedV5LiveRecoveryObserver)
    object.__setattr__(value, "_journal", journal)
    object.__setattr__(value, "_authority", object())
    object.__setattr__(
        value,
        "_registration",
        SimpleNamespace(
            run_id_sha256="1" * 64,
            binding_commitment_sha256="2" * 64,
            infinity_target_identity_sha256="3" * 64,
            space_id="benchmark-space-" + "1" * 48,
            space_slug="managed-live",
            cleanup_plan_sha256="4" * 64,
        ),
    )
    object.__setattr__(value, "_registry_factory", lambda: fresh)
    object.__setattr__(value, "_clock", lambda: datetime(2026, 8, 9, tzinfo=UTC))
    object.__setattr__(value, "_lock", threading.RLock())
    return value


def test_projection_manifest_fsync_failure_prevents_registry_put() -> None:
    events: list[str] = []
    wrapper = object.__new__(ManagedComparisonRegistryPolicyLifecycleAdapter)
    wrapper._lock = threading.RLock()
    wrapper._phase = "source-persisting"
    wrapper._recovery_observer = _Observer(events, fail_projection=True)
    wrapper._registry = _Registry(events)
    wrapper._projection_manifest = _manifest()

    with pytest.raises(RuntimeError, match="fsync failed"):
        wrapper._persist_and_seal_projection(wrapper._projection_manifest)

    assert events == ["journal.projection"]
    assert wrapper._phase == "source-persist-failed"


def test_mem0_observation_is_exact_secret_free_pass_two_material() -> None:
    events: list[str] = []
    journal = _Journal(events)
    observer = _observer(journal)
    observation = ManagedMem0TerminalObservation("deleted", "5" * 64, "6" * 64)

    observer.mem0_terminal_observed(observation)

    assert events == ["journal.mem0_terminal_observed"]
    assert journal.calls[0]["details"] == {
        "terminal_state": "deleted",
        "terminal_commitment_sha256": "5" * 64,
        "cleanup_readback_witness_sha256": "6" * 64,
    }


def test_canonical_terminal_is_appended_only_after_fresh_exact_get(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    fresh = object.__new__(ManagedBenchmarkRegistryHttpAdapter)
    snapshot = object.__new__(ManagedBenchmarkRunLifecycleSnapshot)
    for name, value in {
        "run_id_sha256": "1" * 64,
        "binding_commitment_sha256": "2" * 64,
        "infinity_target_identity_sha256": "3" * 64,
        "space_id": "benchmark-space-" + "1" * 48,
        "space_slug": "managed-live",
        "cleanup_plan_sha256": "4" * 64,
        "cleanup_plan_state": "sealed",
        "state": "cleanup_complete",
        "projection_cleanup_state": "complete",
        "cleanup_receipt": SimpleNamespace(receipt_sha256="8" * 64),
        "completion_receipt": SimpleNamespace(
            receipt_sha256="7" * 64,
            cleanup_initiation_receipt_sha256="8" * 64,
            projection_manifest_sha256="9" * 64,
            projection_absence_proof_sha256="a" * 64,
        ),
    }.items():
        object.__setattr__(snapshot, name, value)
    monkeypatch.setattr(
        ManagedBenchmarkRegistryHttpAdapter,
        "recover_lifecycle",
        lambda self, **kwargs: events.append("registry.get") or snapshot,
    )
    monkeypatch.setattr(
        ManagedBenchmarkRegistryHttpAdapter,
        "relinquish_recovery_authority",
        lambda self, **kwargs: events.append("registry.transfer"),
    )
    monkeypatch.setattr(
        ManagedBenchmarkRegistryHttpAdapter,
        "close",
        lambda self: events.append("registry.close"),
    )
    journal = _Journal(events)
    observer = _observer(journal, fresh=fresh)
    completion = object.__new__(ManagedBenchmarkCleanupCompletionReceipt)
    for name, value in {
        "receipt_sha256": "7" * 64,
        "cleanup_initiation_receipt_sha256": "8" * 64,
        "projection_manifest_sha256": "9" * 64,
        "projection_absence_proof_sha256": "a" * 64,
    }.items():
        object.__setattr__(completion, name, value)

    observer.canonical_terminal_observed(completion)

    assert events == [
        "registry.get",
        "registry.close",
        "journal.canonical_terminal_observed",
    ]

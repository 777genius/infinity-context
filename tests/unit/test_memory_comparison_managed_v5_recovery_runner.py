from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from benchmark_cleanup_plan_fixtures import cleanup_plan_pair
from infinity_context_core.ports.benchmark_cleanup_plan import (
    ManagedBenchmarkCleanupPlan,
    validate_managed_benchmark_cleanup_plan,
)
from infinity_context_server.memory_comparison_managed_benchmark_registry_contracts import (
    ManagedBenchmarkCleanupCounts,
    ManagedBenchmarkCleanupReceipt,
    ManagedBenchmarkPersistedAbortReceipt,
    ManagedBenchmarkPersistedCleanupReceipt,
    ManagedBenchmarkPersistedCompletionReceipt,
    ManagedBenchmarkRegistryHttpError,
    ManagedBenchmarkRunLifecycleSnapshot,
)
from infinity_context_server.memory_comparison_managed_benchmark_registry_http import (
    ManagedBenchmarkRegistryHttpAdapter,
)
from infinity_context_server.memory_comparison_managed_http_lifecycle import (
    managed_http_lifecycle_space_slug,
)
from infinity_context_server.memory_comparison_managed_preflight import (
    managed_backend_target_identity_sha256,
)
from infinity_context_server.memory_comparison_managed_v5_recovery_contracts import (
    ManagedV5LiveRecoveryAuthority,
    canonical_sha256,
)
from infinity_context_server.memory_comparison_managed_v5_recovery_journal import (
    ManagedV5LiveRecoveryJournalStore,
    RecoveryJournalAuthenticator,
)
from infinity_context_server.memory_comparison_managed_v5_recovery_mem0 import (
    ManagedV5RecoveryMem0Error,
)
from infinity_context_server.memory_comparison_managed_v5_recovery_registry import (
    RecoveryRegistryCoordinator,
    registration_details,
)
from infinity_context_server.memory_comparison_managed_v5_recovery_runner import (
    ManagedV5RecoveryError,
    ManagedV5RecoveryRunner,
    RecoveryMem0Readback,
    RecoveryMem0Terminal,
)
from memory_comparison_managed_benchmark_registry_test_support import (
    BINDING,
    RUN,
    SPACE_SLUG,
    _config,
    _target,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


_RUN_ID = "managed-v5-recovery-test"
_INFINITY = "http://127.0.0.1:17789"
_CLEANUP_VALUE, _CLEANUP_SHA = cleanup_plan_pair(
    run_id=_sha(_RUN_ID),
    binding=_sha("binding"),
    target=managed_backend_target_identity_sha256(
        backend_role="infinity-context", base_url=_INFINITY
    ),
    space_slug=managed_http_lifecycle_space_slug(_RUN_ID),
)


def _cleanup_plan() -> ManagedBenchmarkCleanupPlan:
    return validate_managed_benchmark_cleanup_plan(
        _CLEANUP_VALUE,
        _CLEANUP_SHA,
        run_id_sha256=_sha(_RUN_ID),
        binding_commitment_sha256=_sha("binding"),
        infinity_target_identity_sha256=managed_backend_target_identity_sha256(
            backend_role="infinity-context", base_url=_INFINITY
        ),
        space_slug=managed_http_lifecycle_space_slug(_RUN_ID),
    )


def _authority(tmp_path: Path) -> ManagedV5LiveRecoveryAuthority:
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    run_id = _RUN_ID
    infinity = _INFINITY
    return ManagedV5LiveRecoveryAuthority(
        run_id,
        _sha(run_id),
        _sha("binding"),
        managed_backend_target_identity_sha256(backend_role="infinity-context", base_url=infinity),
        managed_http_lifecycle_space_slug(run_id),
        "mem0-locomo-top50-v1",
        ("conv-26:qa:1",),
        "2026-08-09",
        "2026-08-09T00:00:00Z",
        "2026-08-09T06:00:00Z",
        _sha("nonce"),
        _sha("probe"),
        tmp_path / "dataset.json",
        _sha("dataset"),
        _sha("config"),
        tmp_path / "extraction.json",
        _sha("extraction"),
        infinity,
        "http://127.0.0.1:19091",
        17_500_000,
        17_600_000,
        _sha("implementation"),
        True,
        True,
        ("127.0.0.1",),
        5.0,
        120.0,
        21_600.0,
        _sha("pin"),
        state,
        state / "checkpoint.json",
        state / "checkpoint-head.json",
        state / "dispatch.sqlite3",
        state / "operations.sqlite3",
        state / "durable.json",
    )


def _journal(tmp_path: Path):
    authority = _authority(tmp_path)
    signer = RecoveryJournalAuthenticator(secret=b"j" * 64, run_id_sha256=authority.run_id_sha256)
    store = ManagedV5LiveRecoveryJournalStore(
        path=authority.state_root / "recovery.json",
        state_root=authority.state_root,
        authenticator=signer,
    )
    store.initialize(
        authority=authority,
        recorded_at="2026-08-09T00:00:00Z",
        details={"authority_sha256": authority.sha256},
    )
    store.append(
        expected_authority=authority,
        kind="cleanup_plan_prepared",
        recorded_at="2026-08-09T00:00:01Z",
        details={
            "cleanup_plan_sha256": _CLEANUP_SHA,
            "cleanup_target_authority_sha256": _sha("target"),
        },
        cleanup_plan=_cleanup_plan(),
    )
    return authority, store


_SPACE = "benchmark-space-" + "a" * 48
_COUNTS = ManagedBenchmarkCleanupCounts(*(0 for _ in range(10)))


def _cleanup(authority: ManagedV5LiveRecoveryAuthority, state: str):
    return ManagedBenchmarkPersistedCleanupReceipt(
        authority.run_id_sha256,
        _SPACE,
        authority.space_slug,
        "cleanup_pending",
        state,
        _COUNTS,
        (),
        (),
        (),
        _sha("receipt"),
    )


def _snapshot(
    authority: ManagedV5LiveRecoveryAuthority,
    state: str,
    projection: str,
    manifest_sha: str = _sha("manifest"),
):
    cleanup = None
    if state != "active":
        cleanup = _cleanup(
            authority,
            "blocked" if state == "cleanup_aborted" or projection == "blocked" else "pending",
        )
    completion = None
    manifest = manifest_sha if projection in {"sealed", "pending", "complete"} else None
    if state == "cleanup_aborted":
        completion = ManagedBenchmarkPersistedAbortReceipt(
            authority.run_id_sha256,
            authority.binding_commitment_sha256,
            authority.infinity_target_identity_sha256,
            _SPACE,
            authority.space_slug,
            "abort_complete",
            "unsealed_abort_complete",
            _sha("receipt"),
            _CLEANUP_SHA,
            _sha("absence"),
            "2026-08-09T00:02:00.000000Z",
            _sha("completion"),
        )
    elif state == "cleanup_complete":
        completion = ManagedBenchmarkPersistedCompletionReceipt(
            authority.run_id_sha256,
            _SPACE,
            authority.space_slug,
            "cleanup_complete",
            "complete",
            manifest_sha,
            _sha("receipt"),
            _sha("absence"),
            "2026-08-09T00:02:00.000000Z",
            _sha("completion"),
        )
    return ManagedBenchmarkRunLifecycleSnapshot(
        "memory-comparison-run-lifecycle-response.v2",
        "infinity_canonical",
        authority.run_id_sha256,
        authority.binding_commitment_sha256,
        authority.infinity_target_identity_sha256,
        _SPACE,
        authority.space_slug,
        state,
        projection,
        manifest,
        _CLEANUP_SHA,
        "sealed",
        cleanup,
        completion,
    )


class _Backend:
    def __init__(self, authority: ManagedV5LiveRecoveryAuthority, projection: str) -> None:
        self.authority = authority
        self.manifest_sha = _sha("manifest")
        self.current = _snapshot(authority, "active", projection)
        self.calls: list[str] = []
        self.fail_begin: str | None = None
        self.missing = False
        self.register_error: str | None = None
        self.recover_count = 0
        self.fail_recover_number: int | None = None
        self.fail_relinquish = False
        self.fail_close = False

    def factory(self):
        return _Adapter(self)


class _Adapter:
    def __init__(self, backend: _Backend) -> None:
        self.backend = backend

    def recover_lifecycle(self, **_kwargs: object):
        self.backend.calls.append("get")
        self.backend.recover_count += 1
        if self.backend.recover_count == self.backend.fail_recover_number:
            raise ManagedBenchmarkRegistryHttpError("managed_benchmark_registry_request_failed")
        return self.backend.current

    def recover_lifecycle_or_missing(self, **_kwargs: object):
        self.backend.calls.append("get_or_missing")
        return None if self.backend.missing else self.backend.current

    def register(self, **kwargs: object):
        self.backend.calls.append("register")
        plan = kwargs.get("cleanup_plan")
        assert type(plan) is ManagedBenchmarkCleanupPlan and plan.sha256 == _CLEANUP_SHA
        self.backend.missing = False
        if self.backend.register_error:
            raise ManagedBenchmarkRegistryHttpError(self.backend.register_error)

    def begin_cleanup(self):
        self.backend.calls.append("begin")
        projection = (
            "pending" if self.backend.current.projection_cleanup_state == "sealed" else "blocked"
        )
        self.backend.current = _snapshot(
            self.backend.authority,
            "cleanup_pending",
            projection,
            self.backend.manifest_sha,
        )
        if self.backend.fail_begin:
            raise ManagedBenchmarkRegistryHttpError(self.backend.fail_begin)
        persisted = self.backend.current.cleanup_receipt
        assert persisted is not None
        return ManagedBenchmarkCleanupReceipt(
            persisted.run_id_sha256,
            persisted.space_id,
            persisted.space_slug,
            persisted.projection_cleanup,
            persisted.counts,
            persisted.vector_delete_outbox_ids,
            persisted.graph_delete_outbox_ids,
            persisted.cognee_delete_outbox_ids,
            persisted.receipt_sha256,
            False,
        )

    def finalize_cleanup(self, **_kwargs: object):
        self.backend.calls.append("finalize_cleanup")
        self.backend.current = _snapshot(
            self.backend.authority,
            "cleanup_complete",
            "complete",
            self.backend.manifest_sha,
        )

    def finalize_unsealed_abort(self, **_kwargs: object):
        self.backend.calls.append("finalize_abort")
        self.backend.current = _snapshot(
            self.backend.authority, "cleanup_aborted", "unsealed_abort_complete"
        )

    def seal_projection_manifest(self, **kwargs: object):
        self.backend.calls.append("seal")
        manifest_sha = kwargs["projection_manifest_sha256"]
        assert manifest_sha == canonical_sha256(kwargs["projection_manifest"])
        self.backend.manifest_sha = manifest_sha
        self.backend.current = _snapshot(self.backend.authority, "active", "sealed", manifest_sha)

    def relinquish_recovery_authority(self, **kwargs: object):
        self.backend.calls.append("relinquish")
        if self.backend.fail_relinquish:
            raise ManagedBenchmarkRegistryHttpError(
                "managed_benchmark_registry_recovery_transfer_invalid"
            )
        return SimpleNamespace(**kwargs, prior_phase="cleanup_outcome_unknown")

    def close(self):
        self.backend.calls.append("close")
        if self.backend.fail_close:
            raise ManagedBenchmarkRegistryHttpError("managed_benchmark_registry_close_invalid")


class _Mem0:
    def __init__(self, commitment: str = _sha("terminal")) -> None:
        self.commitment = commitment
        self.calls: list[str] = []

    def recover(self, *, execution_started: bool):
        self.calls.append(f"recover:{execution_started}")
        return RecoveryMem0Terminal("aborted", self.commitment)

    def pass_two(self, *, terminal: RecoveryMem0Terminal):
        assert terminal.terminal_commitment_sha256 == self.commitment
        self.calls.append("pass_two")
        return RecoveryMem0Readback(_sha("witness"))


class _NotStartedMem0:
    def __init__(self, expected_started: bool = False) -> None:
        self.expected_started = expected_started

    def recover(self, *, execution_started: bool):
        assert execution_started is self.expected_started
        return RecoveryMem0Terminal("not_started", _sha("absence"), _sha("clean-state"))

    def pass_two(self, **_kwargs: object):
        pytest.fail("not-started recovery must not call cleanup pass two")


def _runner(authority, store, backend, mem0, recorded_at):
    return ManagedV5RecoveryRunner(
        authority=authority,
        cleanup_plan=_cleanup_plan(),
        journal=store,
        registry_factory=backend.factory,
        mem0=mem0,
        clock=lambda: datetime.fromisoformat(recorded_at.replace("Z", "+00:00")),
    )


def _persist_manifest(authority, store, manifest):
    snapshot = _snapshot(authority, "active", "unsealed")
    store.append(
        expected_authority=authority,
        kind="registration_observed",
        recorded_at="2026-08-09T00:00:02Z",
        details={
            "cleanup_plan_sha256": _CLEANUP_SHA,
            "cleanup_plan_state": "sealed",
            "space_id": _SPACE,
            "registration_commitment_sha256": canonical_sha256(
                {
                    "run_id_sha256": snapshot.run_id_sha256,
                    "binding_commitment_sha256": snapshot.binding_commitment_sha256,
                    "space_id": snapshot.space_id,
                    "cleanup_plan_sha256": snapshot.cleanup_plan_sha256,
                }
            ),
        },
    )
    digest = canonical_sha256(manifest)
    store.append(
        expected_authority=authority,
        kind="projection_manifest_persisted",
        recorded_at="2026-08-09T00:00:03Z",
        details={"projection_manifest_sha256": digest},
        projection_manifest=manifest,
    )
    return digest


@pytest.mark.parametrize(
    ("initial_projection", "final_call", "final_state"),
    [
        ("unsealed", "finalize_abort", "cleanup_aborted"),
        ("sealed", "finalize_cleanup", "cleanup_complete"),
    ],
)
def test_runner_uses_exact_terminal_branch_and_replays_idempotently(
    tmp_path: Path, initial_projection: str, final_call: str, final_state: str
) -> None:
    authority, store = _journal(tmp_path)
    backend = _Backend(authority, initial_projection)
    if initial_projection == "sealed":
        manifest = {"sealed": ["nominal"]}
        digest = _persist_manifest(authority, store, manifest)
        backend.manifest_sha = digest
        backend.current = _snapshot(authority, "active", "sealed", digest)
    mem0 = _Mem0()
    first = _runner(authority, store, backend, mem0, "2026-08-09T00:01:00Z").run()
    assert first.canonical_after.state == final_state
    assert final_call in backend.calls
    before = store.load(expected_authority=authority).body_sha256
    second = _runner(authority, store, backend, mem0, "2026-08-09T00:03:00Z").run()
    assert second.ok
    assert store.load(expected_authority=authority).body_sha256 == before


def test_retryable_begin_is_reconciled_by_fresh_get(tmp_path: Path) -> None:
    authority, store = _journal(tmp_path)
    backend = _Backend(authority, "unsealed")
    backend.fail_begin = "managed_benchmark_registry_request_failed"
    result = _runner(authority, store, backend, _Mem0(), "2026-08-09T00:01:00Z").run()
    assert result.ok and backend.calls.count("get") >= 3


def test_replayed_mem0_mismatch_is_blocked(tmp_path: Path) -> None:
    authority, store = _journal(tmp_path)
    backend = _Backend(authority, "unsealed")
    _runner(authority, store, backend, _Mem0(), "2026-08-09T00:01:00Z").run()
    with pytest.raises(ManagedV5RecoveryError) as captured:
        _runner(
            authority,
            store,
            backend,
            _Mem0(_sha("different")),
            "2026-08-09T00:03:00Z",
        ).run()
    assert captured.value.exit_code == 3


@pytest.mark.parametrize(
    ("phase", "retryable"),
    (("recover", True), ("recover", False), ("pass_two", True), ("pass_two", False)),
)
def test_mem0_transport_classification_preserves_latest_cleanup_event(
    tmp_path: Path, phase: str, retryable: bool
) -> None:
    authority, store = _journal(tmp_path)
    backend = _Backend(authority, "unsealed")

    class _FailingMem0:
        def recover(self, *, execution_started: bool):
            assert execution_started is False
            if phase == "recover":
                raise ManagedV5RecoveryMem0Error(
                    "managed_v5_recovery_mem0_transport", retryable=retryable
                )
            return RecoveryMem0Terminal("aborted", _sha("terminal"))

        def pass_two(self, **_kwargs: object):
            raise ManagedV5RecoveryMem0Error(
                "managed_v5_recovery_mem0_transport", retryable=retryable
            )

    with pytest.raises(ManagedV5RecoveryError) as captured:
        _runner(
            authority,
            store,
            backend,
            _FailingMem0(),
            "2026-08-09T00:01:00Z",
        ).run()

    assert captured.value.exit_code == (2 if retryable else 3)
    assert store.load(expected_authority=authority).events[-1].kind == "cleanup_observed"


def test_prepared_only_completes_without_network_or_mem0(tmp_path: Path) -> None:
    authority = _authority(tmp_path)
    store = ManagedV5LiveRecoveryJournalStore(
        path=authority.state_root / "recovery.json",
        state_root=authority.state_root,
        authenticator=RecoveryJournalAuthenticator(
            secret=b"j" * 64, run_id_sha256=authority.run_id_sha256
        ),
    )
    store.initialize(
        authority=authority,
        recorded_at="2026-08-09T00:00:00Z",
        details={"authority_sha256": authority.sha256},
    )

    class _Trap:
        def recover(self, **_kwargs: object):
            pytest.fail("Mem0 must not run")

        def pass_two(self, **_kwargs: object):
            pytest.fail("Mem0 must not run")

    result = ManagedV5RecoveryRunner(
        authority=authority,
        cleanup_plan=_cleanup_plan(),
        journal=store,
        registry_factory=lambda: pytest.fail("registry must not run"),
        mem0=_Trap(),
        clock=lambda: datetime(2026, 8, 9, 0, 1, tzinfo=UTC),
    ).run()
    assert result.reason_code == "no_registration"
    assert result.canonical_before is None and result.mem0_after is None


def test_recovery_events_use_each_clock_value_and_replay_keeps_old_times(
    tmp_path: Path,
) -> None:
    authority, store = _journal(tmp_path)
    backend = _Backend(authority, "unsealed")
    start = datetime(2026, 8, 9, 0, 1, tzinfo=UTC)
    values = iter(start + timedelta(seconds=index) for index in range(4))
    runner = ManagedV5RecoveryRunner(
        authority=authority,
        cleanup_plan=_cleanup_plan(),
        journal=store,
        registry_factory=backend.factory,
        mem0=_Mem0(),
        clock=lambda: next(values),
    )

    runner.run()

    first = store.load(expected_authority=authority)
    recovery_events = first.events[2:]
    assert [item.recorded_at for item in recovery_events] == [
        "2026-08-09T00:01:00.000000Z",
        "2026-08-09T00:01:01.000000Z",
        "2026-08-09T00:01:02.000000Z",
        "2026-08-09T00:01:03.000000Z",
    ]
    replay = ManagedV5RecoveryRunner(
        authority=authority,
        cleanup_plan=_cleanup_plan(),
        journal=store,
        registry_factory=backend.factory,
        mem0=_Mem0(),
        clock=lambda: pytest.fail("replay must not rewrite observed events"),
    )
    replay.run()
    assert store.load(expected_authority=authority).body_sha256 == first.body_sha256


def test_registered_pre_execution_not_started_uses_clean_state_witness(tmp_path: Path) -> None:
    authority, store = _journal(tmp_path)
    backend = _Backend(authority, "unsealed")
    result = _runner(authority, store, backend, _NotStartedMem0(), "2026-08-09T00:01:00Z").run()
    assert result.mem0_after is not None
    assert result.mem0_after.terminal_state == "not_started"
    assert result.mem0_after.cleanup_readback_witness_sha256 == _sha("clean-state")
    event = next(
        item
        for item in store.load(expected_authority=authority).events
        if item.kind == "mem0_terminal_observed"
    )
    assert event.details["terminal_state"] == "not_started"


def test_kill_after_execution_marker_can_prove_not_started(tmp_path: Path) -> None:
    authority, store = _journal(tmp_path)
    backend = _Backend(authority, "unsealed")
    store.append(
        expected_authority=authority,
        kind="registration_observed",
        recorded_at="2026-08-09T00:00:02Z",
        details=registration_details(backend.current),
    )
    store.append(
        expected_authority=authority,
        kind="execution_started",
        recorded_at="2026-08-09T00:00:03Z",
        details={"cleanup_plan_sha256": _CLEANUP_SHA},
    )
    result = _runner(
        authority,
        store,
        backend,
        _NotStartedMem0(expected_started=True),
        "2026-08-09T00:01:00Z",
    ).run()
    assert result.mem0_after is not None
    assert result.mem0_after.terminal_state == "not_started"


@pytest.mark.parametrize(
    "register_error",
    [None, "managed_benchmark_registry_request_failed"],
)
def test_missing_registration_replays_exact_plan_then_fresh_get(
    tmp_path: Path, register_error: str | None
) -> None:
    authority, store = _journal(tmp_path)
    backend = _Backend(authority, "unsealed")
    backend.missing = True
    backend.register_error = register_error
    result = _runner(authority, store, backend, _Mem0(), "2026-08-09T00:01:00Z").run()
    assert result.ok
    assert backend.calls[:3] == ["get_or_missing", "close", "register"]
    assert "get" in backend.calls and "close" in backend.calls


def test_rejected_registration_replay_is_blocked(tmp_path: Path) -> None:
    authority, store = _journal(tmp_path)
    backend = _Backend(authority, "unsealed")
    backend.missing = True
    backend.register_error = "managed_benchmark_registry_response_rejected"
    with pytest.raises(ManagedV5RecoveryError) as captured:
        _runner(authority, store, backend, _Mem0(), "2026-08-09T00:01:00Z").run()
    assert captured.value.exit_code == 3


def test_persisted_manifest_is_replayed_before_cleanup(tmp_path: Path) -> None:
    authority, store = _journal(tmp_path)
    digest = _persist_manifest(authority, store, {"sealed": ["exact", "bytes"]})
    backend = _Backend(authority, "unsealed")
    result = _runner(authority, store, backend, _Mem0(), "2026-08-09T00:01:00Z").run()
    assert result.ok
    assert backend.calls.index("seal") < backend.calls.index("begin")
    assert backend.manifest_sha == digest
    journal = store.load(expected_authority=authority)
    assert any(event.kind == "registry_seal_observed" for event in journal.events)


def test_lost_seal_response_is_reconciled_without_manifest_replacement(tmp_path: Path) -> None:
    authority, store = _journal(tmp_path)
    manifest = {"sealed": ["exact", "bytes"]}
    digest = _persist_manifest(authority, store, manifest)
    backend = _Backend(authority, "sealed")
    backend.manifest_sha = digest
    backend.current = _snapshot(authority, "active", "sealed", digest)
    _runner(authority, store, backend, _Mem0(), "2026-08-09T00:01:00Z").run()
    assert "seal" not in backend.calls


def test_conflicting_canonical_manifest_is_blocked(tmp_path: Path) -> None:
    authority, store = _journal(tmp_path)
    _persist_manifest(authority, store, {"sealed": ["journal"]})
    backend = _Backend(authority, "sealed")
    with pytest.raises(ManagedV5RecoveryError) as captured:
        _runner(authority, store, backend, _Mem0(), "2026-08-09T00:01:00Z").run()
    assert captured.value.exit_code == 3


def test_real_adapter_active_observer_transfers_instead_of_invalid_close() -> None:
    created: list[ManagedBenchmarkRegistryHttpAdapter] = []

    def factory():
        adapter = ManagedBenchmarkRegistryHttpAdapter(
            _config(
                httpx.MockTransport(lambda _request: httpx.Response(200, json=_actual_lifecycle()))
            )
        )
        created.append(adapter)
        return adapter

    authority = SimpleNamespace(
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        infinity_target_identity_sha256=_target(),
        space_slug=SPACE_SLUG,
    )
    snapshot = RecoveryRegistryCoordinator(
        authority=authority,
        cleanup_plan=_cleanup_plan(),
        factory=factory,
    ).recover_initial(_CLEANUP_SHA)
    assert snapshot.state == "active"
    assert len(created) == 1
    assert created[0]._phase == "recovery_authority_transferred"
    assert created[0]._client.is_closed is True


def test_real_adapter_ambiguous_get_transfers_and_closes_without_masking() -> None:
    created: list[ManagedBenchmarkRegistryHttpAdapter] = []

    def handler(request: httpx.Request):
        raise httpx.ReadTimeout("unknown", request=request)

    def factory():
        adapter = ManagedBenchmarkRegistryHttpAdapter(_config(httpx.MockTransport(handler)))
        created.append(adapter)
        return adapter

    authority = SimpleNamespace(
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        infinity_target_identity_sha256=_target(),
        space_slug=SPACE_SLUG,
    )
    coordinator = RecoveryRegistryCoordinator(
        authority=authority,
        cleanup_plan=_cleanup_plan(),
        factory=factory,
    )
    with pytest.raises(ManagedV5RecoveryError, match="registry_get_unknown"):
        coordinator.recover_initial(_CLEANUP_SHA)
    assert created[0]._phase == "recovery_authority_transferred"
    assert created[0]._client.is_closed is True


@pytest.mark.parametrize(
    ("status", "exit_code"),
    ((401, 3), (403, 3), (409, 3), (500, 2)),
)
def test_real_adapter_http_status_is_classified_and_released(status: int, exit_code: int) -> None:
    created: list[ManagedBenchmarkRegistryHttpAdapter] = []

    def factory():
        adapter = ManagedBenchmarkRegistryHttpAdapter(
            _config(httpx.MockTransport(lambda _request: httpx.Response(status)))
        )
        created.append(adapter)
        return adapter

    authority = SimpleNamespace(
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        infinity_target_identity_sha256=_target(),
        space_slug=SPACE_SLUG,
    )
    coordinator = RecoveryRegistryCoordinator(
        authority=authority,
        cleanup_plan=_cleanup_plan(),
        factory=factory,
    )
    with pytest.raises(ManagedV5RecoveryError) as caught:
        coordinator.recover_initial(_CLEANUP_SHA)
    assert caught.value.exit_code == exit_code
    assert created[0]._client.is_closed is True


def _actual_lifecycle() -> dict[str, object]:
    return {
        "data": {
            "schema_version": "memory-comparison-run-lifecycle-response.v2",
            "authority": "infinity_canonical",
            "run_id_sha256": RUN,
            "binding_commitment_sha256": BINDING,
            "infinity_target_identity_sha256": _target(),
            "space_id": f"benchmark-space-{RUN[:48]}",
            "space_slug": SPACE_SLUG,
            "state": "active",
            "cleanup_plan_sha256": _CLEANUP_SHA,
            "cleanup_plan_state": "sealed",
            "projection_cleanup_state": "unsealed",
            "projection_manifest_sha256": None,
            "cleanup_receipt": None,
            "completion_receipt": None,
        }
    }


def test_register_authority_is_relinquished_before_failing_fresh_get(tmp_path: Path) -> None:
    authority, _store = _journal(tmp_path)
    backend = _Backend(authority, "unsealed")
    backend.missing = True
    backend.fail_recover_number = 1
    coordinator = RecoveryRegistryCoordinator(
        authority=authority,
        cleanup_plan=_cleanup_plan(),
        factory=backend.factory,
    )
    with pytest.raises(ManagedV5RecoveryError, match="registry_get_unknown"):
        coordinator.recover_initial(_CLEANUP_SHA)
    assert backend.calls.index("relinquish") < backend.calls.index("get")


def test_begin_authority_is_relinquished_before_failing_fresh_get(tmp_path: Path) -> None:
    authority, _store = _journal(tmp_path)
    backend = _Backend(authority, "unsealed")
    backend.fail_recover_number = 2
    coordinator = RecoveryRegistryCoordinator(
        authority=authority,
        cleanup_plan=_cleanup_plan(),
        factory=backend.factory,
    )
    with pytest.raises(ManagedV5RecoveryError, match="registry_get_unknown"):
        coordinator.begin_cleanup(_CLEANUP_SHA)
    last_get = max(index for index, call in enumerate(backend.calls) if call == "get")
    assert backend.calls.index("relinquish") < last_get
    assert backend.calls[last_get + 1] == "relinquish"


def test_finalize_success_releases_mutation_adapter_before_fresh_get(tmp_path: Path) -> None:
    authority, _store = _journal(tmp_path)
    backend = _Backend(authority, "unsealed")
    backend.current = _snapshot(authority, "cleanup_pending", "blocked")
    backend.fail_recover_number = 3
    coordinator = RecoveryRegistryCoordinator(
        authority=authority,
        cleanup_plan=_cleanup_plan(),
        factory=backend.factory,
    )
    with pytest.raises(ManagedV5RecoveryError, match="registry_get_unknown"):
        coordinator.finalize(cleanup_plan_sha=_CLEANUP_SHA, cleanup_receipt_sha=_sha("receipt"))
    finalize_index = backend.calls.index("finalize_abort")
    release_index = backend.calls.index("relinquish", finalize_index)
    last_get = max(index for index, call in enumerate(backend.calls) if call == "get")
    assert finalize_index < release_index < last_get
    assert backend.calls[last_get + 1] == "relinquish"


def test_unknown_outcome_rejects_double_release_failure(tmp_path: Path) -> None:
    authority, _store = _journal(tmp_path)
    backend = _Backend(authority, "unsealed")
    backend.fail_recover_number = 1
    backend.fail_relinquish = True
    backend.fail_close = True
    coordinator = RecoveryRegistryCoordinator(
        authority=authority,
        cleanup_plan=_cleanup_plan(),
        factory=backend.factory,
    )
    with pytest.raises(ManagedV5RecoveryError, match="ownership_failed"):
        coordinator.fresh_get(_CLEANUP_SHA)
    assert backend.calls == ["get", "relinquish", "close"]


def test_known_authority_release_failure_is_not_suppressed(tmp_path: Path) -> None:
    authority, _store = _journal(tmp_path)
    backend = _Backend(authority, "unsealed")
    backend.fail_begin = "managed_benchmark_registry_response_rejected"
    backend.fail_relinquish = True
    coordinator = RecoveryRegistryCoordinator(
        authority=authority,
        cleanup_plan=_cleanup_plan(),
        factory=backend.factory,
    )
    with pytest.raises(ManagedV5RecoveryError, match="transfer_failed"):
        coordinator.begin_cleanup(_CLEANUP_SHA)
    assert backend.calls[-1] == "relinquish"


def test_invalid_fresh_snapshot_releases_authority(tmp_path: Path) -> None:
    authority, _store = _journal(tmp_path)
    backend = _Backend(authority, "unsealed")
    backend.current = object()
    coordinator = RecoveryRegistryCoordinator(
        authority=authority,
        cleanup_plan=_cleanup_plan(),
        factory=backend.factory,
    )
    with pytest.raises(ManagedV5RecoveryError, match="snapshot_invalid"):
        coordinator.fresh_get(_CLEANUP_SHA)
    assert backend.calls == ["get", "relinquish"]

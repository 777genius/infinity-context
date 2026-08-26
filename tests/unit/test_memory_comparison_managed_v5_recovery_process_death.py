from __future__ import annotations

import multiprocessing
from pathlib import Path

import pytest
from infinity_context_server.memory_comparison_managed_v5_recovery_journal import (
    ManagedV5LiveRecoveryJournalStore,
    RecoveryJournalAuthenticator,
)
from infinity_context_server.memory_comparison_managed_v5_recovery_registry import (
    registration_details,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import canonical_sha256
from test_memory_comparison_managed_v5_recovery_runner import (
    _authority,
    _Backend,
    _cleanup_plan,
    _Mem0,
    _NotStartedMem0,
    _runner,
    _sha,
    _snapshot,
)


def _open(authority) -> ManagedV5LiveRecoveryJournalStore:
    return ManagedV5LiveRecoveryJournalStore(
        path=authority.state_root / "recovery.json",
        state_root=authority.state_root,
        authenticator=RecoveryJournalAuthenticator(
            secret=b"j" * 64, run_id_sha256=authority.run_id_sha256
        ),
    )


def _seed_crash(authority, phase: str) -> None:
    store = _open(authority)
    store.initialize(
        authority=authority,
        recorded_at="2026-08-09T00:00:00Z",
        details={"authority_sha256": authority.sha256},
    )
    if phase == "prepared":
        store.close()
        return
    plan = _cleanup_plan()
    store.append(
        expected_authority=authority,
        kind="cleanup_plan_prepared",
        recorded_at="2026-08-09T00:00:01Z",
        details={
            "cleanup_plan_sha256": plan.sha256,
            "cleanup_target_authority_sha256": _sha("target"),
        },
        cleanup_plan=plan,
    )
    backend = _Backend(authority, "unsealed")
    store.append(
        expected_authority=authority,
        kind="registration_observed",
        recorded_at="2026-08-09T00:00:02Z",
        details=registration_details(backend.current),
    )
    if phase == "post_register":
        store.close()
        return
    if phase == "execution_started":
        store.append(
            expected_authority=authority,
            kind="execution_started",
            recorded_at="2026-08-09T00:00:03Z",
            details={"cleanup_plan_sha256": plan.sha256},
        )
        store.close()
        return
    if phase == "post_manifest":
        manifest = {"sealed": ["crash-before-response"]}
        store.append(
            expected_authority=authority,
            kind="projection_manifest_persisted",
            recorded_at="2026-08-09T00:00:03Z",
            details={"projection_manifest_sha256": canonical_sha256(manifest)},
            projection_manifest=manifest,
        )
        store.close()
        return
    store.append(
        expected_authority=authority,
        kind="cleanup_observed",
        recorded_at="2026-08-09T00:00:04Z",
        details={
            "cleanup_plan_sha256": plan.sha256,
            "cleanup_receipt_sha256": _sha("receipt"),
            "projection_cleanup_state": "blocked",
        },
    )
    if phase == "cleanup_pending":
        store.close()
        return
    store.append(
        expected_authority=authority,
        kind="mem0_terminal_observed",
        recorded_at="2026-08-09T00:00:05Z",
        details={
            "terminal_state": "aborted",
            "terminal_commitment_sha256": _sha("terminal"),
            "cleanup_readback_witness_sha256": _sha("witness"),
        },
    )
    store.close()


class _NoBackend:
    def factory(self):
        pytest.fail("registry must not run for prepared-only recovery")


@pytest.mark.parametrize(
    "phase",
    (
        "prepared",
        "post_register",
        "execution_started",
        "post_manifest",
        "cleanup_pending",
        "finalize_response_unknown",
    ),
)
def test_process_death_second_process_finishes_and_third_is_idempotent(
    tmp_path: Path, phase: str
) -> None:
    authority = _authority(tmp_path)
    process = multiprocessing.get_context("fork").Process(
        target=_seed_crash, args=(authority, phase)
    )
    process.start()
    process.join(timeout=10)
    assert process.exitcode == 0
    store = _open(authority)
    if phase == "prepared":
        trap = _NotStartedMem0()
        result = _runner(authority, store, _NoBackend(), trap, "2026-08-09T01:00:00Z").run()
        assert result.reason_code == "no_registration"
        first_body = store.load(expected_authority=authority).body_sha256
        repeated = _runner(authority, store, _NoBackend(), trap, "2026-08-09T02:00:00Z").run()
        assert repeated.reason_code == "no_registration"
        assert store.load(expected_authority=authority).body_sha256 == first_body
        store.close()
        return
    backend = _Backend(authority, "unsealed")
    if phase == "cleanup_pending":
        backend.current = _snapshot(authority, "cleanup_pending", "blocked")
    elif phase == "finalize_response_unknown":
        backend.current = _snapshot(authority, "cleanup_aborted", "unsealed_abort_complete")
    mem0 = (
        _NotStartedMem0(expected_started=phase == "execution_started")
        if phase in {"post_register", "execution_started"}
        else _Mem0()
    )
    second = _runner(authority, store, backend, mem0, "2026-08-09T01:00:00Z").run()
    assert second.ok and second.canonical_after is not None
    first_body = store.load(expected_authority=authority).body_sha256
    third = _runner(authority, store, backend, mem0, "2026-08-09T02:00:00Z").run()
    assert third.ok
    assert store.load(expected_authority=authority).body_sha256 == first_body
    assert not any("provider" in call or "subscription" in call for call in backend.calls)
    store.close()

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

import pytest
from test_mem0_v5_live_micro_canary import (
    _Composition,
    _Coordinator,
    _inputs,
    _Seal,
    _Terminal,
)

from scripts import mem0_v5_live_micro_canary_recovery as subject
from scripts.mem0_v5_live_micro_canary import execute_micro_canary
from scripts.mem0_v5_live_micro_canary_recovery import (
    LiveCanaryRecoverySession,
    publish_report,
)

_KEY = b"recovery-checkpoint-signing-key-" + b"k" * 32


@dataclass(frozen=True)
class _Phase:
    value: str


@dataclass(frozen=True)
class _Unit:
    record_ids: tuple[str, ...] = ("record-0",)


@dataclass(frozen=True)
class _Checkpoint:
    run_phase: _Phase
    seal: _Seal
    terminal_evidence: _Terminal | None
    units: tuple[_Unit, ...] = (_Unit(),)


class _RestoreCoordinator(_Coordinator):
    def __init__(
        self,
        calls: dict[str, int],
        *,
        phase: str,
        seal: _Seal | None = None,
        terminal: _Terminal | None = None,
    ) -> None:
        super().__init__(calls)
        seal = _Seal() if seal is None else seal
        terminal = _Terminal("deleted") if terminal is None else terminal
        self.checkpoint = _Checkpoint(
            _Phase(phase),
            seal,
            terminal if phase == "terminal" else None,
        )
        self._terminal = terminal

    @property
    def terminal_evidence(self) -> _Terminal:
        return self._terminal

    def restore(self, *, authority, request, budget_policy) -> _Checkpoint:
        del authority, request
        assert budget_policy.maximum_total_call_count == 5
        self.calls["restore"] = self.calls.get("restore", 0) + 1
        return self.checkpoint


class _CleanupFailsBeforeCommit(_Coordinator):
    def cleanup(self) -> _Terminal:
        self.calls["cleanup"] = self.calls.get("cleanup", 0) + 1
        raise RuntimeError("simulated process death before cleanup commit")


class _CrashBeforeReady:
    def __init__(self, delegate: LiveCanaryRecoverySession) -> None:
        self.delegate = delegate

    def load(self, **kwargs):
        return self.delegate.load(**kwargs)

    def seal_evidence(self, *args, **kwargs):
        return self.delegate.seal_evidence(*args, **kwargs)

    def mark_report_ready(self, *args, **kwargs):
        del args, kwargs
        raise RuntimeError("simulated process death after terminal checkpoint")


class _BoundaryCrash(BaseException):
    pass


def _root(tmp_path: Path, name: str) -> Path:
    root = tmp_path / name
    root.mkdir(mode=0o700)
    return root


def _session(root: Path, **kwargs) -> LiveCanaryRecoverySession:
    return LiveCanaryRecoverySession(
        state_root=root,
        checkpoint_signing_key=_KEY,
        **kwargs,
    )


def _fresh_report(root: Path, calls: dict[str, int]) -> dict[str, object]:
    with _session(root) as recovery:
        return execute_micro_canary(
            inputs=_inputs(),
            composition_factory=lambda: _Composition(_Coordinator(calls)),
            recovery=recovery,
        )


def test_terminal_replay_returns_byte_exact_go_without_provider_or_lane_calls(
    tmp_path: Path,
) -> None:
    state = _root(tmp_path, "state")
    calls: dict[str, int] = {}
    first = _fresh_report(state, calls)
    first_bytes = subject._json_bytes(first)
    assert first["outcome"] == "GO"
    assert calls == {"admit": 1, "dispatch": 1, "search": 1, "cleanup": 1}

    replay = _RestoreCoordinator(calls, phase="terminal")
    with _session(state) as recovery:
        second = execute_micro_canary(
            inputs=_inputs(restore=True),
            composition_factory=lambda: _Composition(replay),
            recovery=recovery,
        )

    assert subject._json_bytes(second) == first_bytes
    assert calls == {
        "admit": 1,
        "dispatch": 1,
        "search": 1,
        "cleanup": 1,
        "restore": 1,
    }


def test_evidence_sealed_crash_replays_without_search_or_second_dispatch(
    tmp_path: Path,
) -> None:
    state = _root(tmp_path, "state")
    calls: dict[str, int] = {}
    with _session(state) as recovery:
        failed = execute_micro_canary(
            inputs=_inputs(),
            composition_factory=lambda: _Composition(_CleanupFailsBeforeCommit(calls)),
            recovery=recovery,
        )
    assert failed["failure_code"] == "terminal_cleanup_failed"
    assert calls == {"admit": 1, "dispatch": 1, "search": 1, "cleanup": 1}

    replay = _RestoreCoordinator(calls, phase="sealed")
    with _session(state) as recovery:
        recovered = execute_micro_canary(
            inputs=_inputs(restore=True),
            composition_factory=lambda: _Composition(replay),
            recovery=recovery,
        )
    assert recovered["outcome"] == "GO"
    assert calls["dispatch"] == 1
    assert calls["search"] == 1
    assert calls["restore"] == 1
    assert calls["seal_restored"] == 1
    assert calls["cleanup"] == 2


def test_terminal_checkpoint_crash_advances_sealed_evidence_to_exact_report(
    tmp_path: Path,
) -> None:
    state = _root(tmp_path, "state")
    calls: dict[str, int] = {}
    with _session(state) as recovery:
        interrupted = execute_micro_canary(
            inputs=_inputs(),
            composition_factory=lambda: _Composition(_Coordinator(calls)),
            recovery=_CrashBeforeReady(recovery),
        )
    assert interrupted["failure_code"] == "terminal_evidence_invalid"

    replay = _RestoreCoordinator(calls, phase="terminal")
    with _session(state) as recovery:
        recovered = execute_micro_canary(
            inputs=_inputs(restore=True),
            composition_factory=lambda: _Composition(replay),
            recovery=recovery,
        )
        ready = recovery.load(expected_base=subject.base_report(_inputs(restore=True)))
    assert recovered["outcome"] == "GO"
    assert ready is not None and ready.stage == "report_ready"
    assert calls["dispatch"] == 1
    assert calls["cleanup"] == 1
    assert calls["restore"] == 1


def test_capsule_tamper_fails_before_composition_or_any_provider_call(tmp_path: Path) -> None:
    state = _root(tmp_path, "state")
    _fresh_report(state, {})
    capsule = state / subject.RECOVERY_CAPSULE_NAME
    value = json.loads(capsule.read_bytes())
    value["report"]["authenticated_search_result_count"] = 99
    capsule.write_bytes(subject._json_bytes(value))
    capsule.chmod(0o600)
    compositions = 0

    def forbidden():
        nonlocal compositions
        compositions += 1
        raise AssertionError

    with _session(state) as recovery:
        report = execute_micro_canary(
            inputs=_inputs(restore=True),
            composition_factory=forbidden,
            recovery=recovery,
        )
    assert report["outcome"] == "NO-GO"
    assert compositions == 0


def test_terminal_cross_binding_tamper_is_no_go_without_reexecution(tmp_path: Path) -> None:
    state = _root(tmp_path, "state")
    calls: dict[str, int] = {}
    _fresh_report(state, calls)
    changed_seal = _Seal(commitment_sha256="b" * 64)
    changed_terminal = _Terminal("deleted", seal_commitment_sha256="b" * 64)
    replay = _RestoreCoordinator(
        calls,
        phase="terminal",
        seal=changed_seal,
        terminal=changed_terminal,
    )
    with _session(state) as recovery:
        report = execute_micro_canary(
            inputs=_inputs(restore=True),
            composition_factory=lambda: _Composition(replay),
            recovery=recovery,
        )
    assert report["outcome"] == "NO-GO"
    assert calls["dispatch"] == 1
    assert calls["restore"] == 1


@pytest.mark.parametrize(
    "boundary",
    (
        "report_temp_fsynced",
        "report_published",
        "report_directory_fsynced",
        "report_read_back",
    ),
)
def test_report_publish_recovers_at_every_durable_boundary(tmp_path: Path, boundary: str) -> None:
    reports = _root(tmp_path, "reports")
    path = reports / "report.json"
    report = {"schema_version": "test.v1", "ok": True, "digest": "a" * 64}

    def crash(name: str) -> None:
        if name == boundary:
            raise _BoundaryCrash

    with pytest.raises(_BoundaryCrash):
        publish_report(path, reports, report, boundary_hook=crash)
    recovered = publish_report(path, reports, report)
    assert recovered == report
    assert path.read_bytes() == subject._json_bytes(report)


def test_report_replay_accepts_only_exact_safe_canonical_bytes(tmp_path: Path) -> None:
    reports = _root(tmp_path, "reports")
    path = reports / "report.json"
    report = {"schema_version": "test.v1", "ok": True}
    assert publish_report(path, reports, report) == report
    original = path.read_bytes()
    with pytest.raises(ValueError, match="report_differs"):
        publish_report(path, reports, {**report, "ok": False})
    assert path.read_bytes() == original

    path.unlink()
    path.write_bytes(b"{")
    path.chmod(0o600)
    with pytest.raises(ValueError, match="report_differs"):
        publish_report(path, reports, report)
    assert path.read_bytes() == b"{"


def test_report_rejects_symlink_and_capsule_rejects_wrong_key(tmp_path: Path) -> None:
    reports = _root(tmp_path, "reports")
    outside = tmp_path / "outside"
    outside.write_text("outside")
    path = reports / "report.json"
    path.symlink_to(outside)
    with pytest.raises(ValueError, match="report_invalid"):
        publish_report(path, reports, {"ok": True})

    state = _root(tmp_path, "state")
    _fresh_report(state, {})
    with (
        LiveCanaryRecoverySession(
            state_root=state,
            checkpoint_signing_key=b"different-key-" + b"x" * 32,
        ) as recovery,
        pytest.raises(ValueError, match="capsule_invalid"),
    ):
        recovery.load(expected_base=subject.base_report(_inputs(restore=True)))


@pytest.mark.parametrize(
    "boundary",
    ("capsule_temp_fsynced", "capsule_published", "capsule_directory_fsynced"),
)
def test_capsule_evidence_stage_recovers_at_every_atomic_boundary(
    tmp_path: Path, boundary: str
) -> None:
    state = _root(tmp_path, "state")
    base = subject.base_report(_inputs())
    report = subject._success_report(
        base,
        seal=_Seal(),
        search=type(
            "Search",
            (),
            {
                "records": (object(),),
                "result_root_sha256": "8" * 64,
                "evidence_commitment_sha256": "9" * 64,
            },
        )(),
        record_count=1,
    )

    def crash(name: str) -> None:
        if name == boundary:
            raise _BoundaryCrash

    with pytest.raises(_BoundaryCrash), _session(state, boundary_hook=crash) as recovery:
        recovery.seal_evidence(report, expected_base=base)
    with _session(state) as recovery:
        sealed = recovery.seal_evidence(report, expected_base=base)
    assert sealed.stage == "evidence_sealed"


@pytest.mark.parametrize(
    "boundary",
    ("capsule_temp_fsynced", "capsule_published", "capsule_directory_fsynced"),
)
def test_capsule_report_ready_stage_recovers_at_every_atomic_boundary(
    tmp_path: Path, boundary: str
) -> None:
    state = _root(tmp_path, "state")
    base = subject.base_report(_inputs())
    staged_report = subject._success_report(
        base,
        seal=_Seal(),
        search=type(
            "Search",
            (),
            {
                "records": (object(),),
                "result_root_sha256": "8" * 64,
                "evidence_commitment_sha256": "9" * 64,
            },
        )(),
        record_count=1,
    )
    terminal = _Terminal("deleted")
    final_report, terminal_payload = subject._finalize_report(
        staged_report,
        terminal=terminal,
    )
    with _session(state) as recovery:
        sealed = recovery.seal_evidence(staged_report, expected_base=base)

    def crash(name: str) -> None:
        if name == boundary:
            raise _BoundaryCrash

    with pytest.raises(_BoundaryCrash), _session(state, boundary_hook=crash) as recovery:
        recovery.mark_report_ready(
            sealed,
            report=final_report,
            terminal_evidence=terminal_payload,
            expected_base=base,
        )
    with _session(state) as recovery:
        durable = recovery.load(expected_base=base)
        assert durable is not None
        if durable.stage == "evidence_sealed":
            durable = recovery.mark_report_ready(
                durable,
                report=final_report,
                terminal_evidence=terminal_payload,
                expected_base=base,
            )
    assert durable.stage == "report_ready"
    assert durable.report == final_report
    assert durable.terminal_evidence == terminal_payload


def test_report_mode_tamper_is_rejected_without_replacement(tmp_path: Path) -> None:
    reports = _root(tmp_path, "reports")
    path = reports / "report.json"
    path.write_text('{"ok":true}')
    path.chmod(0o644)
    with pytest.raises(ValueError, match="report_invalid"):
        publish_report(path, reports, {"ok": True})
    assert stat_mode(path) == 0o644


def stat_mode(path: Path) -> int:
    return os.stat(path, follow_symlinks=False).st_mode & 0o777

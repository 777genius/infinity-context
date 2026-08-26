from __future__ import annotations

import errno

import locator_retrieval_v2_process_identity as process_identity
import pytest


class _IdentityState:
    def __init__(
        self,
        *,
        uid: int,
        gid: int,
        groups: list[int],
        setgroups_error: PermissionError | None = None,
    ) -> None:
        self.uid = uid
        self.gid = gid
        self.groups = groups
        self.setgroups_error = setgroups_error
        self.calls: list[tuple[str, object]] = []

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(process_identity.os, "getuid", lambda: self.uid)
        monkeypatch.setattr(process_identity.os, "geteuid", lambda: self.uid)
        monkeypatch.setattr(process_identity.os, "getgid", lambda: self.gid)
        monkeypatch.setattr(process_identity.os, "getegid", lambda: self.gid)
        monkeypatch.setattr(process_identity.os, "getgroups", lambda: list(self.groups))
        monkeypatch.setattr(process_identity.os, "setgroups", self.setgroups)
        monkeypatch.setattr(process_identity.os, "setgid", self.setgid)
        monkeypatch.setattr(process_identity.os, "setuid", self.setuid)

    def setgroups(self, groups: list[int]) -> None:
        self.calls.append(("setgroups", groups))
        if self.setgroups_error is not None:
            raise self.setgroups_error
        self.groups = list(groups)

    def setgid(self, gid: int) -> None:
        self.calls.append(("setgid", gid))
        self.gid = gid

    def setuid(self, uid: int) -> None:
        self.calls.append(("setuid", uid))
        self.uid = uid


def test_enter_runtime_identity_is_idempotent_after_restricted_transition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _IdentityState(uid=65534, gid=65534, groups=[])
    state.install(monkeypatch)

    process_identity.enter_runtime_identity(65534, 65534)

    assert state.calls == []


def test_enter_runtime_identity_clears_groups_before_dropping_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _IdentityState(uid=0, gid=0, groups=[0, 121])
    state.install(monkeypatch)

    process_identity.enter_runtime_identity(65534, 65534)

    assert state.calls == [
        ("setgroups", []),
        ("setgid", 65534),
        ("setuid", 65534),
    ]


def test_enter_runtime_identity_fails_closed_when_groups_remain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = PermissionError(errno.EPERM, "Operation not permitted")
    state = _IdentityState(uid=65534, gid=65534, groups=[121], setgroups_error=error)
    state.install(monkeypatch)

    with pytest.raises(
        RuntimeError, match="fresh_process_supplementary_groups_could_not_be_cleared"
    ):
        process_identity.enter_runtime_identity(65534, 65534)

    assert state.calls == [("setgroups", [])]


def test_enter_runtime_identity_does_not_accept_a_different_unprivileged_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _IdentityState(uid=1001, gid=121, groups=[])
    state.install(monkeypatch)
    error = PermissionError(errno.EPERM, "Operation not permitted")

    def reject_setgid(gid: int) -> None:
        state.calls.append(("setgid", gid))
        raise error

    monkeypatch.setattr(process_identity.os, "setgid", reject_setgid)

    with pytest.raises(PermissionError, match="Operation not permitted"):
        process_identity.enter_runtime_identity(65534, 65534)

    assert state.calls == [("setgid", 65534)]


def test_enter_runtime_identity_validates_result_of_id_transition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _IdentityState(uid=0, gid=0, groups=[])
    state.install(monkeypatch)
    monkeypatch.setattr(
        process_identity.os,
        "setgid",
        lambda gid: state.calls.append(("setgid", gid)),
    )

    with pytest.raises(RuntimeError, match="fresh_process_runtime_identity_mismatch"):
        process_identity.enter_runtime_identity(65534, 65534)

    assert state.calls == [("setgid", 65534), ("setuid", 65534)]


@pytest.mark.parametrize(("runtime_uid", "runtime_gid"), [(0, 65534), (65534, 0)])
def test_enter_runtime_identity_rejects_privileged_target(
    monkeypatch: pytest.MonkeyPatch, runtime_uid: int, runtime_gid: int
) -> None:
    state = _IdentityState(uid=0, gid=0, groups=[0])
    state.install(monkeypatch)

    with pytest.raises(RuntimeError, match="fresh_process_runtime_identity_must_be_unprivileged"):
        process_identity.enter_runtime_identity(runtime_uid, runtime_gid)

    assert state.calls == []

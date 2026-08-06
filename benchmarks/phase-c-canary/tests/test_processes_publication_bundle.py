from __future__ import annotations

import os
from pathlib import Path

import pytest

import phase_c_canary.publication as publication_module
from phase_c_canary.bundle import (
    REQUIRED_REPRODUCTION_FILES,
    BundleError,
    verify_reproduction_bundle,
)
from phase_c_canary.processes import (
    LinuxProcessControl,
    ProcessIdentity,
    ProcessRegistry,
    ProcessRegistryError,
)
from phase_c_canary.publication import (
    AtomicArtifactPublisher,
    LinuxRenameNoReplace,
    PublicationError,
)

BOOT_A = "00000000-0000-4000-8000-000000000001"
BOOT_B = "00000000-0000-4000-8000-000000000002"


class FakeProcessControl:
    def __init__(
        self,
        alive: set[ProcessIdentity],
        fail_pgid: int | None = None,
        current_pgid: int = 9999,
    ) -> None:
        self.alive = {item.pid: item for item in alive}
        self.fail_pgid = fail_pgid
        self._current_pgid = current_pgid
        self.terminated: list[int] = []

    def identity(self, pid: int) -> ProcessIdentity | None:
        return self.alive.get(pid)

    def terminate_group(self, pgid: int) -> None:
        if pgid == self.fail_pgid:
            raise RuntimeError("injected cleanup crash")
        self.terminated.append(pgid)

    def current_pgid(self) -> int:
        return self._current_pgid


def test_linux_process_identity_binds_pid_start_ticks_and_pgid() -> None:
    identity = LinuxProcessControl().identity(os.getpid())
    assert identity is not None
    assert identity.pid == os.getpid()
    assert identity.start_ticks > 0
    assert identity.pgid == os.getpgrp()
    assert identity.boot_id == Path("/proc/sys/kernel/random/boot_id").read_text().strip()


def test_cleanup_uses_persisted_and_discovered_union(tmp_path: Path) -> None:
    registry = ProcessRegistry(tmp_path / "processes.json")
    persisted = ProcessIdentity(101, 1001, 101, BOOT_A)
    discovered = ProcessIdentity(202, 2002, 202, BOOT_A)
    registry.store_union({persisted})
    control = FakeProcessControl({persisted, discovered})
    assert registry.cleanup({discovered}, control) == (persisted, discovered)
    assert control.terminated == [101, 202]
    assert registry.load() == {persisted, discovered}


def test_pid_reuse_does_not_kill_unrelated_process(tmp_path: Path) -> None:
    registry = ProcessRegistry(tmp_path / "processes.json")
    old = ProcessIdentity(101, 1001, 101, BOOT_A)
    reused = ProcessIdentity(101, 9999, 101, BOOT_A)
    registry.store_union({old})
    control = FakeProcessControl({reused})
    assert registry.cleanup(set(), control) == ()
    assert control.terminated == []


def test_cleanup_crash_preserves_full_union_for_recovery(tmp_path: Path) -> None:
    registry = ProcessRegistry(tmp_path / "processes.json")
    first = ProcessIdentity(101, 1001, 101, BOOT_A)
    second = ProcessIdentity(202, 2002, 202, BOOT_A)
    with pytest.raises(RuntimeError, match="cleanup crash"):
        registry.cleanup({first, second}, FakeProcessControl({first, second}, fail_pgid=202))
    assert registry.load() == {first, second}
    recovered = FakeProcessControl({first, second})
    registry.cleanup(set(), recovered)
    assert recovered.terminated == [101, 202]


def test_cleanup_rejects_non_group_leader(tmp_path: Path) -> None:
    registry = ProcessRegistry(tmp_path / "processes.json")
    non_leader = ProcessIdentity(101, 1001, 202, BOOT_A)
    with pytest.raises(ProcessRegistryError, match="group leaders"):
        registry.cleanup({non_leader}, FakeProcessControl({non_leader}))


def test_cleanup_rejects_runner_current_group(tmp_path: Path) -> None:
    registry = ProcessRegistry(tmp_path / "processes.json")
    current = ProcessIdentity(101, 1001, 101, BOOT_A)
    with pytest.raises(ProcessRegistryError, match="runner process group"):
        registry.cleanup({current}, FakeProcessControl({current}, current_pgid=101))


def test_boot_change_prevents_cleanup(tmp_path: Path) -> None:
    registry = ProcessRegistry(tmp_path / "processes.json")
    prior_boot = ProcessIdentity(101, 1001, 101, BOOT_A)
    new_boot = ProcessIdentity(101, 1001, 101, BOOT_B)
    registry.store_union({prior_boot})
    control = FakeProcessControl({new_boot})
    assert registry.cleanup(set(), control) == ()
    assert control.terminated == []


def _reproduction_files() -> dict[str, bytes]:
    return {name: f"fixture:{name}".encode() for name in REQUIRED_REPRODUCTION_FILES}


def test_publication_and_reproduction_self_verification(tmp_path: Path) -> None:
    destination = AtomicArtifactPublisher().publish(
        staging=tmp_path / ".run.staging",
        destination=tmp_path / "run",
        files=_reproduction_files(),
    )
    manifest = verify_reproduction_bundle(destination)
    assert len(manifest["files"]) == len(REQUIRED_REPRODUCTION_FILES)


@pytest.mark.parametrize("point", ["before_manifest", "after_manifest"])
def test_fault_before_publication_never_creates_authoritative_destination(
    tmp_path: Path, point: str
) -> None:
    def fault(actual: str) -> None:
        if actual == point:
            raise RuntimeError("injected publication crash")

    with pytest.raises(RuntimeError, match="publication crash"):
        AtomicArtifactPublisher().publish(
            staging=tmp_path / ".run.staging",
            destination=tmp_path / "run",
            files=_reproduction_files(),
            fault=fault,
        )
    assert not (tmp_path / "run").exists()


def test_fault_after_publication_leaves_complete_verifiable_destination(tmp_path: Path) -> None:
    def fault(point: str) -> None:
        if point == "after_publication":
            raise RuntimeError("injected caller crash")

    with pytest.raises(RuntimeError, match="caller crash"):
        AtomicArtifactPublisher().publish(
            staging=tmp_path / ".run.staging",
            destination=tmp_path / "run",
            files=_reproduction_files(),
            fault=fault,
        )
    verify_reproduction_bundle(tmp_path / "run")


def test_linux_no_replace_adapter_refuses_existing_destination(tmp_path: Path) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    destination.mkdir()
    with pytest.raises(PublicationError, match="already exists"):
        LinuxRenameNoReplace().rename(source, destination)
    assert source.is_dir()
    assert destination.is_dir()


def test_reproduction_verifier_detects_tamper(tmp_path: Path) -> None:
    destination = AtomicArtifactPublisher().publish(
        staging=tmp_path / ".run.staging",
        destination=tmp_path / "run",
        files=_reproduction_files(),
    )
    (destination / "authority.json").write_bytes(b"tampered")
    with pytest.raises(BundleError, match="identity mismatch"):
        verify_reproduction_bundle(destination)


def test_reproduction_verifier_rejects_unmanifested_file(tmp_path: Path) -> None:
    destination = AtomicArtifactPublisher().publish(
        staging=tmp_path / ".run.staging",
        destination=tmp_path / "run",
        files=_reproduction_files(),
    )
    (destination / "untracked.txt").write_text("not in manifest", encoding="utf-8")
    with pytest.raises(BundleError, match="unmanifested"):
        verify_reproduction_bundle(destination)


def test_reproduction_verifier_rejects_unmanifested_symlink(tmp_path: Path) -> None:
    destination = AtomicArtifactPublisher().publish(
        staging=tmp_path / ".run.staging",
        destination=tmp_path / "run",
        files=_reproduction_files(),
    )
    (destination / "untracked-link").symlink_to("authority.json")
    with pytest.raises(BundleError, match="symlink or special"):
        verify_reproduction_bundle(destination)


def test_reproduction_verifier_rejects_special_node(tmp_path: Path) -> None:
    destination = AtomicArtifactPublisher().publish(
        staging=tmp_path / ".run.staging",
        destination=tmp_path / "run",
        files=_reproduction_files(),
    )
    os.mkfifo(destination / "untracked-fifo")
    with pytest.raises(BundleError, match="symlink or special"):
        verify_reproduction_bundle(destination)


def test_publication_fsyncs_every_directory_deepest_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[Path] = []
    monkeypatch.setattr(publication_module, "_fsync_directory", calls.append)
    files = _reproduction_files()
    files["nested/deeper/evidence.json"] = b"{}"
    AtomicArtifactPublisher().publish(
        staging=tmp_path / ".run.staging",
        destination=tmp_path / "run",
        files=files,
    )
    assert calls[:-1] == [
        tmp_path / ".run.staging/nested/deeper",
        tmp_path / ".run.staging/nested",
        tmp_path / ".run.staging",
    ]
    assert calls[-1] == tmp_path

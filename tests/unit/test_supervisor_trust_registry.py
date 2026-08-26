from __future__ import annotations

import base64
import hashlib
import os
import pwd
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import infinity_context_adapters.postgres.supervisor_trust as trust_module
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from infinity_context_adapters.postgres.supervisor_trust import (
    SupervisorTrustRegistry,
    load_pinned_supervisor_trust,
    registry_document,
)
from infinity_context_core.features.context_building.public import (
    InstalledReleaseIdentity,
    RuntimeFenceOwner,
)


def test_pinned_registry_rejects_self_issued_and_substituted_launch_authority() -> None:
    trusted_key = Ed25519PrivateKey.generate()
    untrusted_key = Ed25519PrivateKey.generate()
    trusted = _trust("trusted-root", 8, (("supervisor-a", _public(trusted_key)),))
    owner = _owner(trusted_key, trusted, key_id="supervisor-a")
    trusted.verify_launch(owner, now=datetime.now(UTC))

    copied_key_id = _owner(untrusted_key, trusted, key_id="supervisor-a")
    with pytest.raises(RuntimeError, match="supervisor_key_untrusted"):
        trusted.verify_launch(copied_key_id, now=datetime.now(UTC))

    untrusted = _trust("substituted-root", 8, (("supervisor-a", _public(untrusted_key)),))
    substituted = _owner(untrusted_key, untrusted, key_id="supervisor-a")
    with pytest.raises(RuntimeError, match="supervisor_trust_mismatch"):
        trusted.verify_launch(substituted, now=datetime.now(UTC))

    for hostile in (
        replace(owner, trust_root_sha256="f" * 64),
        replace(owner, trust_registry_generation=7),
    ):
        with pytest.raises(RuntimeError, match="supervisor_trust_mismatch"):
            trusted.verify_launch(hostile, now=datetime.now(UTC))
    with pytest.raises(RuntimeError, match="supervisor_release_mismatch"):
        trusted.verify_launch(
            replace(owner, installed_release=InstalledReleaseIdentity(
                "f" * 40,
                owner.installed_release.source_tree_digest_sha256,
                owner.installed_release.installed_distribution_digest_sha256,
                owner.installed_release.runtime_modules_digest_sha256,
            )),
            now=datetime.now(UTC),
        )


def test_registry_rejects_stale_validity_window() -> None:
    trusted_key = Ed25519PrivateKey.generate()
    now = datetime.now(UTC)
    stale = _trust(
        "stale-root", 2, (("supervisor-a", _public(trusted_key)),),
        valid_from=now - timedelta(hours=2), valid_until=now - timedelta(hours=1)
    )
    with pytest.raises(RuntimeError, match="supervisor_trust_stale"):
        stale.verify_launch(_owner(trusted_key, stale), now=now)


def test_runtime_owned_registry_is_rejected_before_read(tmp_path) -> None:
    key = Ed25519PrivateKey.generate()
    trust = _trust("runtime-owned", 1, (("supervisor-a", _public(key)),))
    raw, _ = registry_document(
        registry_id=trust.registry_id, generation=trust.generation,
        valid_from=trust.valid_from, valid_until=trust.valid_until, keys=trust.keys,
        installed_release=trust.installed_release,
    )
    path = tmp_path / "registry.json"
    path.write_bytes(raw)
    with pytest.raises(RuntimeError, match="runtime_writable"):
        load_pinned_supervisor_trust(
            path=str(path), expected_root_sha256=trust.root_sha256,
            expected_key_id="supervisor-a", expected_generation=1,
            expected_release=trust.installed_release,
        )


def test_runtime_owned_read_only_file_and_ancestor_are_independently_rejected(
    tmp_path, monkeypatch
) -> None:
    nobody = pwd.getpwnam("nobody")
    monkeypatch.setattr(trust_module.os, "geteuid", lambda: nobody.pw_uid)
    monkeypatch.setattr(trust_module.os, "getegid", lambda: nobody.pw_gid)
    monkeypatch.setattr(trust_module.os, "getgroups", lambda: [])
    owned_file = tmp_path / "owned-0444.json"
    owned_file.write_text("{}")
    os.chown(owned_file, nobody.pw_uid, nobody.pw_gid)
    owned_file.chmod(0o444)
    with pytest.raises(RuntimeError, match="runtime_writable"):
        trust_module._assert_runtime_cannot_substitute(owned_file)

    owned_parent = tmp_path / "owned-parent"
    owned_parent.mkdir(mode=0o555)
    registry = owned_parent / "registry.json"
    registry.write_text("{}")
    registry.chmod(0o444)
    os.chown(owned_parent, nobody.pw_uid, nobody.pw_gid)
    with pytest.raises(RuntimeError, match="runtime_writable"):
        trust_module._assert_runtime_cannot_substitute(registry)


def test_runtime_owned_sticky_directory_and_symlink_replacement_are_rejected(
    tmp_path, monkeypatch
) -> None:
    nobody = pwd.getpwnam("nobody")
    monkeypatch.setattr(trust_module.os, "geteuid", lambda: nobody.pw_uid)
    monkeypatch.setattr(trust_module.os, "getegid", lambda: nobody.pw_gid)
    monkeypatch.setattr(trust_module.os, "getgroups", lambda: [])
    sticky = tmp_path / "runtime-sticky"
    sticky.mkdir(mode=0o755)
    registry = sticky / "registry.json"
    registry.write_text("{}")
    registry.chmod(0o444)
    os.chown(sticky, nobody.pw_uid, nobody.pw_gid)
    sticky.chmod(0o1777)
    with pytest.raises(RuntimeError, match="runtime_writable"):
        trust_module._assert_runtime_cannot_substitute(registry)

    target = tmp_path / "target.json"
    target.write_text("{}")
    target.chmod(0o444)
    link = tmp_path / "registry-link.json"
    link.symlink_to(target)
    with pytest.raises(RuntimeError, match="runtime_writable"):
        trust_module._assert_runtime_cannot_substitute(link)


def test_separately_owned_read_only_deployment_layout_is_accepted(
    tmp_path, monkeypatch
) -> None:
    nobody = pwd.getpwnam("nobody")
    monkeypatch.setattr(trust_module.os, "geteuid", lambda: nobody.pw_uid)
    monkeypatch.setattr(trust_module.os, "getegid", lambda: nobody.pw_gid)
    monkeypatch.setattr(trust_module.os, "getgroups", lambda: [])
    deployment = tmp_path / "deployment"
    deployment.mkdir(mode=0o755)
    registry = deployment / "registry.json"
    registry.write_text("{}")
    registry.chmod(0o444)
    trust_module._assert_runtime_cannot_substitute(registry)


def test_configured_registry_rejects_stale_generation_digest_and_malformed_document(
    tmp_path, monkeypatch
) -> None:
    key = Ed25519PrivateKey.generate()
    trust = _trust("deployment-pinned", 9, (("supervisor-a", _public(key)),))
    raw, _ = registry_document(
        registry_id=trust.registry_id, generation=trust.generation,
        valid_from=trust.valid_from, valid_until=trust.valid_until, keys=trust.keys,
        installed_release=trust.installed_release,
    )
    path = tmp_path / "registry.json"
    path.write_bytes(raw)
    monkeypatch.setattr(trust_module, "_assert_runtime_cannot_substitute", lambda _path: None)
    with pytest.raises(RuntimeError, match="generation_mismatch"):
        load_pinned_supervisor_trust(
            path=str(path), expected_root_sha256=trust.root_sha256,
            expected_key_id="supervisor-a", expected_generation=8,
            expected_release=trust.installed_release,
        )
    with pytest.raises(RuntimeError, match="digest_mismatch"):
        load_pinned_supervisor_trust(
            path=str(path), expected_root_sha256="f" * 64,
            expected_key_id="supervisor-a", expected_generation=9,
            expected_release=trust.installed_release,
        )
    path.write_text('{"schema":"hostile"}')
    with pytest.raises(RuntimeError, match="trust_malformed"):
        load_pinned_supervisor_trust(
            path=str(path), expected_root_sha256=trust.root_sha256,
            expected_key_id="supervisor-a", expected_generation=9,
            expected_release=trust.installed_release,
        )


def _trust(
    registry_id: str, generation: int, keys: tuple[tuple[str, str], ...], *,
    valid_from: datetime | None = None, valid_until: datetime | None = None
) -> SupervisorTrustRegistry:
    now = datetime.now(UTC)
    start = valid_from or now - timedelta(minutes=1)
    end = valid_until or now + timedelta(hours=1)
    _, digest = registry_document(
        registry_id=registry_id, generation=generation, valid_from=start,
        valid_until=end, keys=keys, installed_release=_release()
    )
    return SupervisorTrustRegistry(
        registry_id, generation, start, end, keys, _release(), digest
    )


def _owner(
    key: Ed25519PrivateKey, trust: SupervisorTrustRegistry, key_id: str = "supervisor-a"
) -> RuntimeFenceOwner:
    pid = os.getpid()
    with open(f"/proc/{pid}/stat", encoding="utf-8") as stream:
        stat_value = stream.read()
    birth = stat_value[stat_value.rfind(")") + 2 :].split()[19]
    executable = os.path.realpath(f"/proc/{pid}/exe")
    with open(executable, "rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    values = {
        "instance_id": "hostile-runtime",
        "generation": "hostile-generation",
        "supervisor_key_id": key_id,
        "supervisor_public_key": _public(key),
        "trust_root_sha256": trust.root_sha256,
        "trust_registry_generation": trust.generation,
        "launch_token": "hostile-live-process-launch",
        "process_pid": pid,
        "process_birth_identity": birth,
        "executable_identity": executable,
        "executable_sha256": digest,
        "installed_release": trust.installed_release,
    }
    unsigned = RuntimeFenceOwner(**values, launch_signature="")
    signature = base64.b64encode(key.sign(unsigned.launch_payload())).decode("ascii")
    return RuntimeFenceOwner(**values, launch_signature=signature)


def _public(key: Ed25519PrivateKey) -> str:
    return key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    ).hex()


def _release() -> InstalledReleaseIdentity:
    return InstalledReleaseIdentity(
        "1" * 40,
        "sha256:" + "2" * 64,
        "sha256:" + "3" * 64,
        "sha256:" + "4" * 64,
    )

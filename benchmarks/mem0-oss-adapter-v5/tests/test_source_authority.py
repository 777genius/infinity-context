from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from mem0_oss_adapter_v5.source_authority import (
    SourceAuthorityError,
    VerifiedSourceAuthority,
    verify_source_authority,
)


def _authority(tmp_path: Path) -> tuple[Path, Path, Path]:
    installed = tmp_path / "installed"
    installed.mkdir()
    (installed / "package").mkdir()
    (installed / "package/module.py").write_text("VALUE = 1\n")
    (installed / "runtime-lock.json").write_text("{}\n")
    phase = tmp_path / "phase"
    (phase / "attestation").mkdir(parents=True)
    commit, tree = "1" * 40, "2" * 40
    (phase / "attestation/commit.txt").write_text(commit + "\n")
    (phase / "attestation/tree.txt").write_text(tree + "\n")
    release = b"abc source/file.py\n"
    (phase / "attestation/release-files.sha256").write_bytes(release)
    files = []
    rows = []
    for path in sorted(value for value in installed.rglob("*") if value.is_file()):
        relative = path.relative_to(installed).as_posix()
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        files.append({"path": relative, "size": len(raw), "sha256": digest})
        rows.append(f"{relative}\0{len(raw)}\0{digest}\n")
    manifest = tmp_path / "authority" / "manifest.json"
    manifest.parent.mkdir()
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "mem0-oss-adapter-v5.source-authority.v1",
                "source_commit_sha1": "3" * 40,
                "source_tree_sha1": "4" * 40,
                "closure_algorithm": "sha256(sorted(path + NUL + size + NUL + sha256 + LF))",
                "closure_sha256": hashlib.sha256("".join(rows).encode()).hexdigest(),
                "files": files,
                "phase_c_authority": {
                    "infinity_commit_sha1": commit,
                    "infinity_tree_sha1": tree,
                    "release_manifest_sha256": hashlib.sha256(release).hexdigest(),
                },
            }
        )
    )
    return manifest, installed, phase


def _verify(manifest: Path, installed: Path, phase: Path) -> VerifiedSourceAuthority:
    return verify_source_authority(
        manifest_path=manifest,
        expected_manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
        installed_root=installed,
        phase_c_authority_root=phase,
    )


def test_external_manifest_issues_immutable_verified_capability(tmp_path: Path) -> None:
    manifest, installed, phase = _authority(tmp_path)
    result = _verify(manifest, installed, phase)
    assert type(result) is VerifiedSourceAuthority
    assert result.source_commit_sha1 == "3" * 40


def test_transport_reroute_changes_admission_runtime_binding(tmp_path: Path) -> None:
    manifest, installed, phase = _authority(tmp_path)
    authority = _verify(manifest, installed, phase)
    common = {
        "route_sha256": "1" * 64,
        "runtime_binding_commitment_sha256": "2" * 64,
        "runtime_source_sha256": "3" * 64,
        "runtime_route_binding_sha256": "4" * 64,
    }
    first = authority.binding_commitment(
        **common,
        runtime_transport_origin_sha256="5" * 64,
    )
    rerouted = authority.binding_commitment(
        **common,
        runtime_transport_origin_sha256="6" * 64,
    )
    assert first != rerouted


def test_verified_capability_rejects_public_construction() -> None:
    with pytest.raises(TypeError, match="verified issuance"):
        VerifiedSourceAuthority(
            source_commit_sha1="1" * 40,
            source_tree_sha1="2" * 40,
            manifest_sha256="3" * 64,
            closure_sha256="4" * 64,
            phase_c_infinity_commit_sha1="5" * 40,
            phase_c_infinity_tree_sha1="6" * 40,
            phase_c_release_manifest_sha256="7" * 64,
            _issuance=object(),
        )


@pytest.mark.parametrize("mutation", ["dirty", "missing", "extra"])
def test_exact_closure_rejects_dirty_missing_and_extra_files(tmp_path: Path, mutation: str) -> None:
    manifest, installed, phase = _authority(tmp_path)
    if mutation == "dirty":
        (installed / "package/module.py").write_text("VALUE = 2\n")
    elif mutation == "missing":
        (installed / "package/module.py").unlink()
    else:
        (installed / "unexpected.py").write_text("pass\n")
    with pytest.raises(SourceAuthorityError):
        _verify(manifest, installed, phase)


def test_phase_c_commit_tree_and_release_manifest_are_exact(tmp_path: Path) -> None:
    manifest, installed, phase = _authority(tmp_path)
    for relative, value in (
        ("commit.txt", "9" * 40 + "\n"),
        ("tree.txt", "8" * 40 + "\n"),
        ("release-files.sha256", "tampered\n"),
    ):
        path = phase / "attestation" / relative
        original = path.read_bytes()
        path.write_text(value)
        with pytest.raises(SourceAuthorityError, match="phase_c_authority_invalid"):
            _verify(manifest, installed, phase)
        path.write_bytes(original)


def test_phase_c_attestation_intermediate_symlink_is_rejected(tmp_path: Path) -> None:
    manifest, installed, phase = _authority(tmp_path)
    attestation = phase / "attestation"
    real = phase / "real-attestation"
    attestation.rename(real)
    attestation.symlink_to(real, target_is_directory=True)
    with pytest.raises(SourceAuthorityError, match="phase_c_authority_invalid"):
        _verify(manifest, installed, phase)


def test_manifest_inside_installed_tree_cannot_be_its_own_trust_root(tmp_path: Path) -> None:
    manifest, installed, phase = _authority(tmp_path)
    internal = installed / "manifest.json"
    internal.write_bytes(manifest.read_bytes())
    with pytest.raises(SourceAuthorityError, match="self_trust"):
        verify_source_authority(
            manifest_path=internal,
            expected_manifest_sha256=hashlib.sha256(internal.read_bytes()).hexdigest(),
            installed_root=installed,
            phase_c_authority_root=phase,
        )


def test_wrong_external_pin_rejects_valid_manifest_before_parse(tmp_path: Path) -> None:
    manifest, installed, phase = _authority(tmp_path)
    with pytest.raises(SourceAuthorityError, match="source_authority_pin_invalid"):
        verify_source_authority(
            manifest_path=manifest,
            expected_manifest_sha256="f" * 64,
            installed_root=installed,
            phase_c_authority_root=phase,
        )

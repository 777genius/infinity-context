from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from phase_c_canary.attestation import (
    AuthorityError,
    require_import_from,
    verify_immutable_authority,
)
from phase_c_canary.authority import AuthorityBindingError, immutable_authority
from phase_c_canary.environment import EnvironmentError, build_runtime_environment
from phase_c_canary.hashing import canonical_json_bytes, sha256_bytes
from phase_c_canary.strict_schema import (
    LOCOMO_JUDGE_RESPONSE_FORMAT,
    LOCOMO_RESPONSE_FORMAT_SHA256,
    LOCOMO_RESPONSE_SCHEMA_SHA256,
    StrictSchemaError,
    parse_locomo_judge,
)


def test_exact_immutable_authority_is_valid() -> None:
    verify_immutable_authority(immutable_authority())


@dataclass(frozen=True, slots=True)
class _ContainerBinding:
    infinity_source_root: Path
    runtime_root: Path


def test_container_binding_relocates_paths_without_rewriting_commitments(
    tmp_path: Path,
) -> None:
    source = tmp_path / "phase-c"
    runtime = tmp_path / "runtime"
    source.mkdir()
    runtime.mkdir()
    reviewed = immutable_authority()

    bound = immutable_authority(authority_binding=_ContainerBinding(source, runtime))

    assert bound.infinity_source_root == source
    assert bound.runtime_root == runtime
    assert bound.infinity_release_manifest.path == (source / "attestation/release-files.sha256")
    assert bound.runtime_artifact_manifest.path == runtime / "artifact-manifest.json"
    assert bound.runtime_release.path == runtime / "release.json"
    assert bound.infinity_commit == reviewed.infinity_commit
    assert bound.runtime_commit == reviewed.runtime_commit
    assert bound.infinity_release_manifest.sha256 == reviewed.infinity_release_manifest.sha256
    assert bound.runtime_artifact_manifest.sha256 == reviewed.runtime_artifact_manifest.sha256
    assert bound.runtime_release.sha256 == reviewed.runtime_release.sha256


def test_container_binding_rejects_missing_and_overlapping_roots(tmp_path: Path) -> None:
    source = tmp_path / "phase-c"
    source.mkdir()
    with pytest.raises(AuthorityBindingError, match="unavailable"):
        immutable_authority(
            authority_binding=_ContainerBinding(source, tmp_path / "missing-runtime")
        )
    with pytest.raises(AuthorityBindingError, match="overlap"):
        immutable_authority(authority_binding=_ContainerBinding(source, source))


def test_container_binding_does_not_trust_existing_wrong_authority(tmp_path: Path) -> None:
    source = tmp_path / "phase-c"
    runtime = tmp_path / "runtime"
    source.mkdir()
    runtime.mkdir()
    bound = immutable_authority(authority_binding=_ContainerBinding(source, runtime))

    with pytest.raises(AuthorityError, match="authority file is absent"):
        verify_immutable_authority(bound)


def test_import_shadowing_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    expected = tmp_path / "expected"
    shadow = tmp_path / "shadow"
    expected.mkdir()
    shadow.mkdir()
    (shadow / "authority_shadow.py").write_text("VALUE = 'shadow'\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(shadow))
    importlib.invalidate_caches()
    sys.modules.pop("authority_shadow", None)
    with pytest.raises(AuthorityError, match="shadowing"):
        require_import_from("authority_shadow", expected)


def test_strict_environment_never_reads_ambient_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_PASSWORD", "must-not-leak")
    child = build_runtime_environment(
        {"PATH": "/usr/bin:/bin", "RUNTIME_ATTESTATION_SECRET": "explicit"},
        required=frozenset({"RUNTIME_ATTESTATION_SECRET"}),
    )
    assert child == {
        "PATH": "/usr/bin:/bin",
        "RUNTIME_ATTESTATION_SECRET": "explicit",
    }
    assert "DATABASE_PASSWORD" not in child


def test_strict_environment_rejects_unexpected_key() -> None:
    with pytest.raises(EnvironmentError, match="unexpected"):
        build_runtime_environment({"DATABASE_PASSWORD": "no"}, required=frozenset())


@pytest.mark.parametrize(
    "value",
    [
        "prose",
        '```json\n{"reasoning":"ok","label":"CORRECT"}\n```',
        '{"reasoning":"ok","label":"CORRECT"}\ntrailing',
        '{"reasoning":"ok","label":"CORRECT","extra":1}',
        '{"reasoning":"ok"}',
        '{"reasoning":"ok","label":"MAYBE"}',
        '{"reasoning":3,"label":"CORRECT"}',
        '\u00a0{"reasoning":"ok","label":"CORRECT"}',
        '{"reasoning":"ok","label":"CORRECT"}\u00a0',
    ],
)
def test_strict_judge_rejects_invalid_output(value: str) -> None:
    with pytest.raises(StrictSchemaError):
        parse_locomo_judge(value)


def test_strict_judge_accepts_exact_output() -> None:
    assert parse_locomo_judge(' \n\t{"reasoning":"ok","label":"CORRECT"}\r\n ') == {
        "reasoning": "ok",
        "label": "CORRECT",
    }


def test_locomo_response_format_hashes_are_exact() -> None:
    assert sha256_bytes(canonical_json_bytes(LOCOMO_JUDGE_RESPONSE_FORMAT)) == (
        LOCOMO_RESPONSE_FORMAT_SHA256
    )
    assert (
        sha256_bytes(canonical_json_bytes(LOCOMO_JUDGE_RESPONSE_FORMAT["json_schema"]["schema"]))
        == LOCOMO_RESPONSE_SCHEMA_SHA256
    )

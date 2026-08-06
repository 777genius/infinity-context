from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

from phase_c_canary.attestation import (
    AuthorityError,
    require_import_from,
    verify_immutable_authority,
)
from phase_c_canary.authority import immutable_authority
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

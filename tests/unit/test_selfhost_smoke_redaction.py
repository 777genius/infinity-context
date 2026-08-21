from __future__ import annotations

import importlib.util
import os
import sys
import urllib.error
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest


def valid_selfhost_env(smoke: Any) -> dict[str, str]:
    values = {smoke.SERVICE_TOKEN_ENV: "service-token-distinct"}
    values.update(
        {
            key: f"selfhost-secret-{index}"
            for index, key in enumerate(smoke.SELFHOST_SECRET_ENVS, start=1)
        }
    )
    return values


def load_smoke_module() -> Any:
    path = Path(__file__).parents[2] / "scripts" / "selfhost_smoke.py"
    spec = importlib.util.spec_from_file_location("selfhost_smoke", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_selfhost_smoke_run_failure_redacts_sensitive_env_values() -> None:
    smoke = load_smoke_module()
    token = "selfhost-secret-token-1234567890"
    env = dict(os.environ)
    env["MEMORY_SERVICE_TOKEN"] = token

    with pytest.raises(smoke.SmokeFailure) as exc:
        smoke._run(
            [
                sys.executable,
                "-c",
                "import os, sys; print(os.environ['MEMORY_SERVICE_TOKEN']); sys.exit(7)",
            ],
            env=env,
            timeout=10,
        )

    message = str(exc.value)
    assert token not in message
    assert "<redacted>" in message


def test_selfhost_smoke_run_failure_redacts_identity_password() -> None:
    smoke = load_smoke_module()
    secret = "selfhost-admin-secret-1234567890"
    env = dict(os.environ)
    env[smoke.SELFHOST_SECRET_ENVS[0]] = secret

    with pytest.raises(smoke.SmokeFailure) as exc:
        smoke._run(
            [
                sys.executable,
                "-c",
                f"import sys; print({secret!r}); sys.exit(7)",
            ],
            env=env,
            timeout=10,
        )

    message = str(exc.value)
    assert secret not in message
    assert "<redacted>" in message


def test_selfhost_smoke_http_error_redacts_response_body_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    smoke = load_smoke_module()
    token = "selfhost-secret-token-abcdefghijklmnopqrstuvwxyz"

    def fail_urlopen(*_args: Any, **_kwargs: Any) -> Any:
        raise urllib.error.HTTPError(
            url="http://memory.test/v1/health",
            code=500,
            msg="failed",
            hdrs={},
            fp=BytesIO(f'{{"message":"Bearer {token}"}}'.encode()),
        )

    monkeypatch.setattr(smoke.urllib.request, "urlopen", fail_urlopen)

    with pytest.raises(smoke.SmokeFailure) as exc:
        smoke._request_json(
            "GET",
            "http://memory.test/v1/health",
            token=token,
            timeout=1,
        )

    message = str(exc.value)
    assert token not in message
    assert "<redacted>" in message


def test_selfhost_smoke_requires_all_six_identity_passwords(tmp_path: Path) -> None:
    smoke = load_smoke_module()
    values = valid_selfhost_env(smoke)
    missing = smoke.SELFHOST_SECRET_ENVS[-1]
    values.pop(missing)

    with pytest.raises(smoke.SmokeFailure) as exc:
        smoke._validate_env(tmp_path / ".env.selfhost", values)

    assert missing in str(exc.value)


def test_selfhost_smoke_rejects_placeholder_identity_password(tmp_path: Path) -> None:
    smoke = load_smoke_module()
    values = valid_selfhost_env(smoke)
    placeholder = smoke.SELFHOST_SECRET_ENVS[0]
    values[placeholder] = "change-me-admin"

    with pytest.raises(smoke.SmokeFailure) as exc:
        smoke._validate_env(tmp_path / ".env.selfhost", values)

    assert placeholder in str(exc.value)
    assert values[placeholder] not in str(exc.value)


def test_selfhost_smoke_rejects_reused_secret_without_leaking_it(
    tmp_path: Path,
) -> None:
    smoke = load_smoke_module()
    values = valid_selfhost_env(smoke)
    reused = values[smoke.SELFHOST_SECRET_ENVS[0]]
    values[smoke.SELFHOST_SECRET_ENVS[-1]] = reused

    with pytest.raises(smoke.SmokeFailure) as exc:
        smoke._validate_env(tmp_path / ".env.selfhost", values)

    assert "seven distinct values" in str(exc.value)
    assert reused not in str(exc.value)


def test_selfhost_smoke_rejects_service_token_reused_as_identity_password(
    tmp_path: Path,
) -> None:
    smoke = load_smoke_module()
    values = valid_selfhost_env(smoke)
    reused = values[smoke.SERVICE_TOKEN_ENV]
    values[smoke.SELFHOST_SECRET_ENVS[0]] = reused

    with pytest.raises(smoke.SmokeFailure) as exc:
        smoke._validate_env(tmp_path / ".env.selfhost", values)

    assert "seven distinct values" in str(exc.value)
    assert reused not in str(exc.value)


def test_selfhost_env_file_is_ignored_but_example_remains_trackable() -> None:
    gitignore = Path(__file__).parents[2] / ".gitignore"
    rules = {
        line.strip()
        for line in gitignore.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert ".env.selfhost" in rules
    assert ".env.selfhost.example" not in rules


def test_selfhost_make_targets_share_the_complete_secret_guard() -> None:
    makefile = (Path(__file__).parents[2] / "Makefile").read_text(encoding="utf-8")

    assert "MEMORY_POSTGRES_PASSWORD" not in makefile
    assert (
        makefile.count('scripts/selfhost_smoke.py --env-file "$(SELFHOST_ENV)" --validate-env-only')
        == 3
    )

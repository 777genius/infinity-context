from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import infinity_context_server.memory_comparison_codex_llm as codex_llm
from infinity_context_server.memory_comparison_codex_canary import (
    run_codex_answerer_canary,
)


def test_run_codex_cli_uses_isolated_runtime_env_and_cwd(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_run(
        args,
        *,
        input,
        text,
        capture_output,
        timeout,
        check,
        cwd,
        env,
    ):
        output_path = Path(args[args.index("-o") + 1])
        output_path.write_text("unit codex output\n", encoding="utf-8")
        env_paths = {
            name: Path(env[name])
            for name in (
                "TMPDIR",
                "TEMP",
                "TMP",
                "XDG_RUNTIME_DIR",
                "XDG_CACHE_HOME",
                "XDG_STATE_HOME",
                "XDG_DATA_HOME",
            )
        }
        captured.update(
            {
                "args": tuple(args),
                "input": input,
                "text": text,
                "capture_output": capture_output,
                "timeout": timeout,
                "check": check,
                "cwd": Path(cwd),
                "env": dict(env),
                "env_paths_exist": {name: path.is_dir() for name, path in env_paths.items()},
                "output_parent_exists": output_path.parent.is_dir(),
                "runtime_root": output_path.parents[1],
            }
        )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setenv("HOME", "/unit/home")
    monkeypatch.setenv("XDG_CONFIG_HOME", "/unit/config")
    monkeypatch.setenv("XDG_CACHE_HOME", "/read-only/cache")
    monkeypatch.setattr(codex_llm.subprocess, "run", fake_run)

    result = codex_llm._run_codex_cli(
        codex_command="unit-codex",
        model="gpt-5.5",
        prompt="Answer from the evidence only.",
        timeout_seconds=12.0,
        cwd=None,
    )

    assert result == "unit codex output"
    assert captured["input"] == "Answer from the evidence only."
    assert captured["timeout"] == 12.0
    assert captured["text"] is True
    assert captured["capture_output"] is True
    assert captured["check"] is False
    assert captured["args"][:2] == ("unit-codex", "exec")
    assert "--sandbox" in captured["args"]
    assert "read-only" in captured["args"]
    env = captured["env"]
    assert env["HOME"] == "/unit/home"
    assert env["XDG_CONFIG_HOME"] == "/unit/config"
    assert env["XDG_CACHE_HOME"] != "/read-only/cache"
    assert all(captured["env_paths_exist"].values())
    assert captured["output_parent_exists"] is True
    assert captured["runtime_root"] in captured["cwd"].parents


def test_run_codex_cli_sets_writable_home_when_missing(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(
        args,
        *,
        input,
        text,
        capture_output,
        timeout,
        check,
        cwd,
        env,
    ):
        output_path = Path(args[args.index("-o") + 1])
        output_path.write_text("unit codex output\n", encoding="utf-8")
        home = Path(env["HOME"])
        captured.update(
            {
                "home": home,
                "home_exists": home.is_dir(),
                "runtime_root": output_path.parents[1],
            }
        )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.delenv("HOME", raising=False)
    monkeypatch.setattr(codex_llm.subprocess, "run", fake_run)

    result = codex_llm._run_codex_cli(
        codex_command="unit-codex",
        model="gpt-5.5",
        prompt="Answer from the evidence only.",
        timeout_seconds=12.0,
        cwd=None,
    )

    assert result == "unit codex output"
    assert captured["home_exists"] is True
    assert captured["home"].name == "home"
    assert captured["home"].parent == captured["runtime_root"]


def test_codex_answerer_canary_returns_sanitized_success_report() -> None:
    captured: dict[str, object] = {}

    def fake_runner(args, prompt, timeout, cwd):
        captured["args"] = tuple(args)
        captured["prompt"] = prompt
        captured["timeout"] = timeout
        captured["cwd"] = cwd
        return "The sandbox marker is blue."

    report = run_codex_answerer_canary(
        model="unit-model",
        codex_command="/private/provider/codex",
        timeout_seconds=7.0,
        command_runner=fake_runner,
    )
    rendered = json.dumps(report, sort_keys=True)

    assert report["ok"] is True
    assert report["provider_kind"] == "subscription-runtime"
    assert report["codex_command"] == "codex"
    assert report["answer_contains_expected_term"] is True
    assert captured["timeout"] == 7.0
    assert "sandbox marker color is blue" in str(captured["prompt"])
    assert "/private/provider" not in rendered


def test_codex_answerer_canary_reports_sanitized_external_blocker() -> None:
    def fake_runner(args, prompt, timeout, cwd):
        raise ValueError(
            "Codex CLI exited with status 1: provider auth path "
            "/private/provider-auth-file failed: Operation not permitted "
            "for https://api.openai.com/v1/responses"
        )

    report = run_codex_answerer_canary(
        model="unit-model",
        codex_command="/private/provider/codex",
        command_runner=fake_runner,
    )
    rendered = json.dumps(report, sort_keys=True)

    assert report["ok"] is False
    assert report["failure_code"] == "provider_network_blocked"
    assert "outbound provider access was blocked" in str(report["failure_reason"])
    assert report["diagnostics"] == {
        "blocker_scope": "external_provider_egress",
        "operator_action": "allow_subscription_runtime_provider_egress",
        "provider_endpoint": "api.openai.com",
        "provider_transports": ["https"],
        "os_error": "operation_not_permitted",
        "repo_invocation_sandbox": "read-only",
        "repo_invocation_approval_policy": "never",
    }
    assert "https://api.openai.com/v1/responses" not in rendered
    assert "/private/provider-auth-file" not in rendered
    assert "/private/provider/codex" not in rendered


def test_codex_answerer_canary_reports_sanitized_auth_missing_blocker() -> None:
    def fake_runner(args, prompt, timeout, cwd):
        raise ValueError(
            "Codex CLI exited with status 1: websocket transport failed: "
            "HTTP 401 Unauthorized: Missing bearer or basic authentication, "
            "url: wss://api.openai.com/v1/responses; https transport failed: "
            "HTTP 401 Unauthorized for https://api.openai.com/v1/responses; "
            "request marker unit_request_marker; session state /unit/codex/session-state-file; "
            "raw provider body marker unit_provider_body"
        )

    report = run_codex_answerer_canary(
        model="unit-model",
        codex_command="/private/provider/codex",
        command_runner=fake_runner,
    )
    rendered = json.dumps(report, sort_keys=True)

    assert report["ok"] is False
    assert report["failure_code"] == "codex_cli_auth_missing"
    assert "authentication was missing" in str(report["failure_reason"])
    assert report["diagnostics"] == {
        "blocker_scope": "codex_cli_auth",
        "operator_action": "run_inside_subscription_runtime_or_configure_codex_auth",
        "auth_error": "missing_bearer_or_basic_authentication",
        "http_status": 401,
        "provider_endpoint": "api.openai.com",
        "provider_transports": ["websocket", "https"],
    }
    assert "provider_network_blocked" not in rendered
    assert "wss://api.openai.com/v1/responses" not in rendered
    assert "https://api.openai.com/v1/responses" not in rendered
    assert "unit_request_marker" not in rendered
    assert "/unit/codex/session-state-file" not in rendered
    assert "unit_provider_body" not in rendered
    assert "/private/provider/codex" not in rendered


def test_codex_answerer_canary_reports_not_logged_in_auth_blocker() -> None:
    def fake_runner(args, prompt, timeout, cwd):
        raise ValueError("Codex CLI is not logged in. Please log in to continue.")

    report = run_codex_answerer_canary(
        model="unit-model",
        codex_command="codex",
        command_runner=fake_runner,
    )

    assert report["failure_code"] == "codex_cli_auth_missing"
    assert report["diagnostics"] == {
        "blocker_scope": "codex_cli_auth",
        "operator_action": "run_inside_subscription_runtime_or_configure_codex_auth",
        "auth_error": "codex_cli_not_logged_in",
    }


def test_codex_stderr_preview_filters_prompt_transcript() -> None:
    preview = codex_llm._redacted_preview(
        "\n".join(
            (
                "OpenAI Codex v0.142.5",
                "user",
                "Question: where is the private fixture?",
                'Return JSON only with verdict "error" if blocked.',
                "warning: Codex could not find bubblewrap on PATH.",
                "2026-07-17T00:44:54Z ERROR endpoint: failed to connect "
                "to websocket: IO error: Operation not permitted (os error 1), "
                "url: wss://api.openai.com/v1/responses",
            )
        )
    )

    assert "private fixture" not in preview
    assert 'verdict "error"' not in preview
    assert "Codex could not find bubblewrap" in preview
    assert "Operation not permitted" in preview


def test_codex_stderr_preview_keeps_auth_diagnostics() -> None:
    preview = codex_llm._redacted_preview(
        "\n".join(
            (
                "OpenAI Codex v0.142.5",
                "user",
                "Question: where is the private fixture?",
                "HTTP 401 Unauthorized: Missing bearer or basic authentication",
            )
        )
    )

    assert "private fixture" not in preview
    assert "401 Unauthorized" in preview
    assert "Missing bearer or basic authentication" in preview


def test_memory_comparison_llm_keeps_codex_lazy_exports() -> None:
    from infinity_context_server.memory_comparison_llm import CodexCliAnswerer

    assert CodexCliAnswerer is codex_llm.CodexCliAnswerer

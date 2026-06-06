from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from memo_stack_mcp.plugin_hook import (
    HookSettings,
    MemoryHookGateway,
    MemoryPluginHookApp,
    parse_hook_event,
)

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "capture_hosts"


class RecordingGateway(MemoryHookGateway):
    def __init__(self, settings: HookSettings) -> None:
        super().__init__(settings)
        self.capture_payloads: list[dict[str, Any]] = []

    def _request_json(self, method: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        if method == "GET" and path == "/v1/capabilities":
            return {
                "captures": {
                    "enabled": True,
                    "api_version": 1,
                    "mode": "suggest",
                }
            }
        if method == "POST" and path == "/v1/captures":
            self.capture_payloads.append(payload)
            return {"data": {"id": "cap_fixture"}}
        msg = f"Unexpected request {method} {path}"
        raise AssertionError(msg)


def _settings(*, event_name: str, agent_name: str) -> HookSettings:
    return HookSettings.from_env(
        {
            "MEMORY_MCP_API_URL": "http://memory-fixture.invalid",
            "MEMORY_MCP_AUTH_TOKEN": "fixture-token",
            "MEMORY_MCP_DEFAULT_SPACE_SLUG": "fixture-space",
            "MEMORY_MCP_DEFAULT_PROFILE_EXTERNAL_REF": "fixture-profile",
            "MEMORY_MCP_AGENT_NAME": agent_name,
            "MEMORY_PLUGIN_HOOK_CONTEXT_EVENTS": "",
            "MEMORY_PLUGIN_HOOK_INGEST_EVENTS": event_name,
            "MEMORY_CAPTURE_MODE": "suggest",
        }
    )


def _load(relpath: str) -> dict[str, Any]:
    return json.loads((FIXTURE_ROOT / relpath).read_text(encoding="utf-8"))


def _event_name(payload: dict[str, Any], fallback: str) -> str:
    for key in ("hook_event_name", "event_name", "event", "hook"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return fallback


def test_host_fixtures_map_payloads_to_canonical_capture_metadata(tmp_path: Path) -> None:
    cases = [
        (
            "claude/user_prompt_submit.json",
            "claude-fixture",
            "HOST_FIXTURE_CLAUDE_USER_PROMPT",
            "user",
            "explicit_user_command",
            "high",
        ),
        (
            "codex/user_prompt_submit.json",
            "codex-fixture",
            "HOST_FIXTURE_CODEX_USER_PROMPT",
            "user",
            "explicit_user_command",
            "high",
        ),
        (
            "codex/stop.json",
            "codex-fixture",
            "HOST_FIXTURE_CODEX_STOP",
            "assistant",
            "assistant_inference",
            "low",
        ),
        (
            "gemini/user_prompt_submit.json",
            "gemini-fixture",
            "HOST_FIXTURE_GEMINI_USER_PROMPT",
            "user",
            "explicit_user_command",
            "high",
        ),
        (
            "opencode/message_event.json",
            "opencode-fixture",
            "HOST_FIXTURE_OPENCODE_MESSAGE",
            "user",
            "explicit_user_command",
            "high",
        ),
    ]
    for relpath, agent_name, marker, actor_role, authority, trust_level in cases:
        payload = _load(relpath)
        event_name = _event_name(payload, "UserPromptSubmit")
        raw_payload = json.dumps(payload)
        event = parse_hook_event(args=[event_name], stdin_text=raw_payload, cwd=str(tmp_path))
        gateway = RecordingGateway(_settings(event_name=event.name, agent_name=agent_name))
        result = MemoryPluginHookApp(settings=gateway._settings, gateway=gateway).run(event)

        assert result.exit_code == 0
        assert result.stdout == ""
        assert result.stderr == ""
        assert marker in event.query_text
        capture = gateway.capture_payloads[0]
        assert capture["source_agent"] == agent_name
        assert capture["event_type"] == event_name
        assert capture["actor_role"] == actor_role
        assert capture["source_authority"] == authority
        assert capture["trust_level"] == trust_level
        assert capture["source_event_id"].startswith(f"{agent_name}:{event_name}:")
        assert capture["idempotency_key"].startswith("hook:")
        assert marker in capture["text"]
        assert str(tmp_path) not in json.dumps(capture, sort_keys=True)
        assert "fixture-token" not in json.dumps(capture, sort_keys=True)


def test_claude_stop_fixture_reads_only_bounded_transcript_tail(tmp_path: Path) -> None:
    transcript = tmp_path / "claude-session.jsonl"
    transcript.write_text(
        "\n".join(
            [
                json.dumps({"type": "user", "message": {"role": "user", "content": "noise"}}),
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "role": "assistant",
                            "content": (
                                "Remember: HOST_FIXTURE_CLAUDE_TRANSCRIPT_TAIL should be "
                                "low-authority transcript evidence."
                            ),
                        },
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )
    payload = _load("claude/stop_with_transcript_path.json")
    payload["transcript_path"] = str(transcript)
    event_name = _event_name(payload, "Stop")
    event = parse_hook_event(args=[event_name], stdin_text=json.dumps(payload), cwd=str(tmp_path))
    settings = HookSettings.from_env(
        {
            "MEMORY_MCP_API_URL": "http://memory-fixture.invalid",
            "MEMORY_MCP_AUTH_TOKEN": "fixture-token",
            "MEMORY_MCP_DEFAULT_SPACE_SLUG": "fixture-space",
            "MEMORY_MCP_DEFAULT_PROFILE_EXTERNAL_REF": "fixture-profile",
            "MEMORY_MCP_AGENT_NAME": "claude-fixture",
            "MEMORY_PLUGIN_HOOK_CONTEXT_EVENTS": "",
            "MEMORY_PLUGIN_HOOK_INGEST_EVENTS": "Stop",
            "MEMORY_CAPTURE_MODE": "suggest",
            "MEMORY_PLUGIN_HOOK_TRANSCRIPT_TAIL_MODE": "claude",
        }
    )
    gateway = RecordingGateway(settings)
    result = MemoryPluginHookApp(settings=settings, gateway=gateway).run(event)

    assert result.exit_code == 0
    assert result.stdout == ""
    assert result.stderr == ""
    capture = gateway.capture_payloads[0]
    assert capture["source_kind"] == "transcript_tail"
    assert capture["actor_role"] == "assistant"
    assert capture["source_authority"] == "transcript_inference"
    assert capture["trust_level"] == "low"
    assert "HOST_FIXTURE_CLAUDE_TRANSCRIPT_TAIL" in capture["text"]
    assert str(transcript) not in capture["text"]


def test_cursor_fixture_documents_mcp_only_lane() -> None:
    payload = _load("cursor/mcp_tool_call.json")
    event = parse_hook_event(args=[], stdin_text=json.dumps(payload), cwd="/workspace")

    assert event.name == "mcp_tool_call"
    assert "HOST_FIXTURE_CURSOR_MCP_ONLY" in event.query_text

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "local_mcp_visual_memory_smoke.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "local_mcp_visual_memory_smoke_for_test",
        SCRIPT_PATH,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_local_visual_smoke_report_redacts_tokens(tmp_path: Path, capsys) -> None:
    module = _load_module()
    token = "unit-local-visual-secret-token"
    report = module._build_report(
        api_url="http://127.0.0.1:17788",
        space_slug="unit-local-visual",
        scope_ref="unit-scope",
        checks={
            "health": {"ok": True},
            "capabilities": {"ok": True},
            "ui": {"ok": True},
            "ui_assets": {"ok": True},
            "generated_mcp": {"ok": True, "token": token},
            "mcp_session": {"ok": True},
            "capture_created": {"ok": True},
            "visual_memory": {"ok": True},
        },
        failures=[],
        started=0.0,
        run_id="unit-run",
    )

    report_out = tmp_path / "local-visual.json"
    module._emit_report(report, report_out=str(report_out), env=module._secret_env(token))

    rendered = report_out.read_text(encoding="utf-8")
    stdout = capsys.readouterr().out
    payload = json.loads(rendered)
    assert payload["suite"] == module.SUITE
    assert payload["ok"] is True
    assert token not in rendered
    assert token not in stdout
    assert "<redacted" in rendered


def test_local_visual_smoke_required_checks_are_hard_gate() -> None:
    module = _load_module()

    assert module._failed_required_checks(
        {
            "health": {"ok": True},
            "capabilities": {"ok": True},
            "ui": {"ok": True},
            "ui_assets": {"ok": True},
            "generated_mcp": {"ok": True},
            "mcp_session": {"ok": False},
            "capture_created": {"ok": True},
            "visual_memory": {"ok": True},
        }
    ) == ["mcp_session"]


def test_local_visual_state_requires_consolidated_capture_and_pending_review() -> None:
    module = _load_module()

    class Response:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return self._payload

    class Client:
        def get(self, path, params=None):
            if path == "/v1/captures":
                return Response(
                    {
                        "data": [
                            {
                                "id": "cap_unit",
                                "consolidation_status": "consolidated",
                            }
                        ]
                    }
                )
            if path == "/v1/suggestions":
                return Response(
                    {
                        "data": [
                            {
                                "id": "sug_unit",
                                "status": "pending",
                                "created_from_capture_id": "cap_unit",
                            }
                        ]
                    }
                )
            if path == "/v1/memory-browser":
                return Response(
                    {
                        "data": {
                            "captures": [{"id": "cap_unit"}],
                            "stats": {"captures": 1},
                        }
                    }
                )
            raise AssertionError(path)

    state = module._visual_memory_state(
        Client(),
        space_slug="unit",
        scope_ref="scope",
        capture_id="cap_unit",
    )

    assert state["ok"] is True
    assert state["created_from_capture_suggestions"] == 1
    assert state["browser_capture_visible"] is True


def test_local_visual_capture_payload_uses_allowed_manual_source_kind() -> None:
    module = _load_module()
    sent_payloads = []

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {"data": {"id": "cap_unit"}}

    class Client:
        def post(self, path, json):
            sent_payloads.append((path, json))
            return Response()

    module._create_capture(
        Client(),
        space_slug="unit",
        scope_ref="scope",
        marker="MARKER",
    )

    assert sent_payloads[0][0] == "/v1/captures"
    assert sent_payloads[0][1]["source_kind"] == "manual"
    assert sent_payloads[0][1]["actor_role"] == "user"


def test_local_visual_report_redacts_openai_like_secret_marker(tmp_path: Path) -> None:
    module = _load_module()
    report_out = tmp_path / "safe.json"
    secret = "sk-unitsecret_12345678901234567890"

    module._emit_report({"leak": secret}, report_out=str(report_out), env={})

    rendered = report_out.read_text(encoding="utf-8")
    assert secret not in rendered
    assert "<redacted>" in rendered

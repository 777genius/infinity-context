from __future__ import annotations

import copy
import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from conftest import RUNTIME_REPO, SECRET, sign_receipt, unsigned_receipt

from phase_c_canary.authority import immutable_authority
from phase_c_canary.hashing import canonical_json_bytes
from phase_c_canary.http_adapter import LoopbackJsonCompletionAdapter
from phase_c_canary.journal import JournalError, ProviderUsageJournal, SlotState
from phase_c_canary.orchestrator import CanaryOrchestrator
from phase_c_canary.receipt import NodePublicReceiptVerifier, ReceiptVerificationError
from phase_c_canary.strict_schema import (
    LOCOMO_JUDGE_RESPONSE_FORMAT,
    LOCOMO_RESPONSE_FORMAT_POLICY_SHA256,
    StrictSchemaError,
)

OUTPUT = '{"reasoning":"Evidence matches.","label":"CORRECT"}'


def _request(content: str = "provider-free") -> dict[str, Any]:
    return {
        "model": "gpt-5.6-sol",
        "messages": [{"role": "user", "content": content}],
        "max_tokens": 4096,
        "temperature": 0,
        "response_format": copy.deepcopy(LOCOMO_JUDGE_RESPONSE_FORMAT),
    }


class _Handler(BaseHTTPRequestHandler):
    response: dict[str, Any]

    def do_POST(self) -> None:  # noqa: N802
        size = int(self.headers["Content-Length"])
        self.server.received_body = self.rfile.read(size)  # type: ignore[attr-defined]
        body = json.dumps(self.response, separators=(",", ":")).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


def _run(
    tmp_path: Path,
    *,
    request: dict[str, Any],
    fault_at: str | None = None,
) -> tuple[ProviderUsageJournal, ThreadingHTTPServer | None]:
    receipt = unsigned_receipt()
    receipt["metadata"]["request_identity"]["request_body_sha256"] = hashlib.sha256(
        canonical_json_bytes(request)
    ).hexdigest()
    receipt["metadata"]["output_identity"]["output_text_sha256"] = hashlib.sha256(
        OUTPUT.encode()
    ).hexdigest()
    _Handler.response = {
        "envelope": {"text": OUTPUT, "finish_reason": "stop"},
        "receipt": sign_receipt(receipt),
    }
    journal = ProviderUsageJournal(tmp_path / "usage.sqlite3")
    if fault_at == "before_dispatch":
        completion = LoopbackJsonCompletionAdapter("http://127.0.0.1:1")
        with pytest.raises(RuntimeError, match="before dispatch"):
            _orchestrator(journal).fake_completion(
                slot_id="slot-1",
                request=request,
                completion=completion,
                receipt_secret=SECRET,
                response_format_policy_sha256=LOCOMO_RESPONSE_FORMAT_POLICY_SHA256,
                fault_at=fault_at,
            )
        return journal, None
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    adapter = LoopbackJsonCompletionAdapter(f"http://127.0.0.1:{server.server_address[1]}")
    try:
        if fault_at:
            with pytest.raises(RuntimeError, match="injected"):
                _orchestrator(journal).fake_completion(
                    slot_id="slot-1",
                    request=request,
                    completion=adapter,
                    receipt_secret=SECRET,
                    response_format_policy_sha256=LOCOMO_RESPONSE_FORMAT_POLICY_SHA256,
                    fault_at=fault_at,
                )
        else:
            result = _orchestrator(journal).fake_completion(
                slot_id="slot-1",
                request=request,
                completion=adapter,
                receipt_secret=SECRET,
                response_format_policy_sha256=LOCOMO_RESPONSE_FORMAT_POLICY_SHA256,
            )
            assert result == {"slot_id": "slot-1", "status": "committed"}
            assert server.received_body == canonical_json_bytes(request)  # type: ignore[attr-defined]
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
    return journal, server


def _orchestrator(journal: ProviderUsageJournal) -> CanaryOrchestrator:
    return CanaryOrchestrator(
        authority=immutable_authority(),
        journal=journal,
        verifier=NodePublicReceiptVerifier(RUNTIME_REPO),
    )


def test_fake_loopback_http_e2e_commits_verified_result(tmp_path: Path) -> None:
    request = _request()
    journal, _ = _run(tmp_path, request=request)
    try:
        assert journal.get("slot-1").state is SlotState.COMMITTED
    finally:
        journal.close()


@pytest.mark.parametrize(
    ("fault_at", "expected"),
    [
        ("before_dispatch", SlotState.RESERVED),
        ("after_dispatch", SlotState.DISPATCHED),
        ("after_response_before_commit", SlotState.DISPATCHED),
    ],
)
def test_orchestration_fault_boundaries(tmp_path: Path, fault_at: str, expected: SlotState) -> None:
    request = _request()
    journal, _ = _run(tmp_path, request=request, fault_at=fault_at)
    try:
        assert journal.get("slot-1").state is expected
        retryable, unknown = journal.recover()
        if expected is SlotState.RESERVED:
            assert retryable == ("slot-1",)
            assert unknown == ()
        else:
            assert retryable == ()
            assert unknown == ("slot-1",)
    finally:
        journal.close()


def test_signed_receipt_cannot_be_rebound_to_other_output(tmp_path: Path) -> None:
    request = _request("binding")
    receipt = unsigned_receipt()
    receipt["metadata"]["request_identity"]["request_body_sha256"] = hashlib.sha256(
        canonical_json_bytes(request)
    ).hexdigest()
    signed = sign_receipt(receipt)

    class Completion:
        def complete(self, request: dict[str, Any]):
            return {"text": '{"reasoning":"different","label":"WRONG"}'}, copy.deepcopy(signed)

    journal = ProviderUsageJournal(tmp_path / "usage.sqlite3")
    try:
        with pytest.raises(ValueError, match="not bound"):
            _orchestrator(journal).fake_completion(
                slot_id="slot-1",
                request=request,
                completion=Completion(),
                receipt_secret=SECRET,
                response_format_policy_sha256=LOCOMO_RESPONSE_FORMAT_POLICY_SHA256,
            )
    finally:
        journal.close()


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://127.0.0.1:8000",
        "http://localhost:8000",
        "http://127.0.0.1:8000@external.invalid/path",
    ],
)
def test_fake_http_adapter_rejects_non_loopback_authority(endpoint: str) -> None:
    with pytest.raises(ValueError, match="loopback"):
        LoopbackJsonCompletionAdapter(endpoint).complete({})


@pytest.mark.parametrize("tamper", ["missing_schema", "schema", "policy"])
def test_request_authority_fails_before_reserve(tmp_path: Path, tamper: str) -> None:
    request = _request()
    policy = LOCOMO_RESPONSE_FORMAT_POLICY_SHA256
    if tamper == "missing_schema":
        del request["response_format"]
    elif tamper == "schema":
        request["response_format"]["json_schema"]["schema"]["additionalProperties"] = True
    else:
        policy = "0" * 64

    class MustNotDispatch:
        def complete(self, request: dict[str, Any]):
            raise AssertionError("invalid request reached dispatch")

    journal = ProviderUsageJournal(tmp_path / "usage.sqlite3")
    try:
        with pytest.raises(StrictSchemaError):
            _orchestrator(journal).fake_completion(
                slot_id="slot-invalid",
                request=request,
                completion=MustNotDispatch(),
                receipt_secret=SECRET,
                response_format_policy_sha256=policy,
            )
        with pytest.raises(JournalError, match="unknown provider slot"):
            journal.get("slot-invalid")
    finally:
        journal.close()


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("metadata", "runtime_selection", "model"), "gpt-drift"),
        (("metadata", "runtime_selection", "execution_profile"), "subscription-worker"),
        (("metadata", "runtime_selection", "base_instructions_sha256"), "0" * 64),
        (("metadata", "runtime_selection", "reasoning_effort"), "medium"),
        (("metadata", "runtime_selection", "service_tier"), "priority"),
        (("metadata", "request_identity", "response_format_sha256"), "0" * 64),
        (("metadata", "request_identity", "response_schema_sha256"), "0" * 64),
        (("metadata", "request_identity", "public_model"), "gpt-drift"),
        (("metadata", "request_identity", "client_requested_model"), "gpt-drift"),
        (("metadata", "request_identity", "configured_codex_model"), "gpt-drift"),
        (("metadata", "request_identity", "requested_codex_model"), "gpt-drift"),
        (("metadata", "output_identity", "terminal_status"), "failed"),
        (("metadata", "output_token_limit", "requested_tokens"), 4095),
    ],
)
def test_resigned_receipt_authority_tamper_is_rejected(
    tmp_path: Path,
    path: tuple[str, ...],
    value: object,
) -> None:
    request = _request("authority-binding")
    raw_receipt = unsigned_receipt()
    raw_receipt["metadata"]["request_identity"]["request_body_sha256"] = hashlib.sha256(
        canonical_json_bytes(request)
    ).hexdigest()
    target = raw_receipt
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    signed = sign_receipt(raw_receipt)

    class Completion:
        def complete(self, request: dict[str, Any]):
            return {"text": OUTPUT}, copy.deepcopy(signed)

    journal = ProviderUsageJournal(tmp_path / "usage.sqlite3")
    try:
        with pytest.raises((ValueError, ReceiptVerificationError)):
            _orchestrator(journal).fake_completion(
                slot_id="slot-tamper",
                request=request,
                completion=Completion(),
                receipt_secret=SECRET,
                response_format_policy_sha256=LOCOMO_RESPONSE_FORMAT_POLICY_SHA256,
            )
    finally:
        journal.close()

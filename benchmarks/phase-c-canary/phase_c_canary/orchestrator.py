from __future__ import annotations

import json
from dataclasses import asdict
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from .attestation import verify_immutable_authority
from .authority import AuthorityContract
from .hashing import canonical_json_bytes, sha256_bytes
from .journal import ProviderUsageJournal
from .receipt import RuntimeReceiptVerifierPort
from .strict_schema import parse_locomo_judge, validate_locomo_request


class RunMode(StrEnum):
    OFFLINE = "offline"
    FAKE = "fake"


class CompletionPort(Protocol):
    def complete(self, request: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]: ...


class CanaryOrchestrator:
    def __init__(
        self,
        *,
        authority: AuthorityContract,
        journal: ProviderUsageJournal,
        verifier: RuntimeReceiptVerifierPort,
    ) -> None:
        self._authority = authority
        self._journal = journal
        self._verifier = verifier

    def preflight(self, mode: RunMode = RunMode.OFFLINE) -> dict[str, object]:
        verify_immutable_authority(self._authority)
        return {
            "mode": mode.value,
            "authority_schema": self._authority.schema_version,
            "provider_usage_schema": self._authority.provider_usage_schema,
            "live_enabled": False,
        }

    def fake_completion(
        self,
        *,
        slot_id: str,
        request: dict[str, Any],
        completion: CompletionPort,
        receipt_secret: str,
        response_format_policy_sha256: str,
        fault_at: str | None = None,
    ) -> dict[str, str]:
        verify_immutable_authority(self._authority)
        validate_locomo_request(
            request,
            policy_sha256=response_format_policy_sha256,
            model=self._authority.model,
            requested_output_tokens=self._authority.requested_output_tokens,
        )
        self._journal.reserve(
            slot_id,
            {
                "wire_request": request,
                "response_format_policy_sha256": response_format_policy_sha256,
            },
        )
        if fault_at == "before_dispatch":
            raise RuntimeError("injected before dispatch")
        self._journal.mark_dispatched(slot_id)
        if fault_at == "after_dispatch":
            raise RuntimeError("injected after dispatch")
        envelope, receipt = completion.complete(request)
        self._verifier.verify(receipt=receipt, secret=receipt_secret)
        text = str(envelope["text"])
        self._require_bound_receipt(request=request, text=text, receipt=receipt)
        parse_locomo_judge(text)
        if fault_at == "after_response_before_commit":
            raise RuntimeError("injected after response before commit")
        self._journal.commit_result(slot_id, envelope, receipt)
        return {"slot_id": slot_id, "status": "committed"}

    def _require_bound_receipt(
        self,
        *,
        request: dict[str, Any],
        text: str,
        receipt: dict[str, Any],
    ) -> None:
        metadata = receipt["metadata"]
        selection = metadata["runtime_selection"]
        identity = metadata["request_identity"]
        output = metadata["output_identity"]
        expected = {
            "schema": metadata["schema_version"] == self._authority.runtime_receipt_schema,
            "profile": selection["execution_profile"] == self._authority.execution_profile,
            "base": selection["base_instructions_sha256"] == self._authority.stateless_base_sha256,
            "format": identity["response_format_type"] == self._authority.response_format_type,
            "format_sha": identity["response_format_sha256"]
            == self._authority.response_format_sha256,
            "schema_sha": identity["response_schema_sha256"]
            == self._authority.response_schema_sha256,
            "request": identity["request_body_sha256"]
            == sha256_bytes(canonical_json_bytes(request)),
            "output": output["output_text_sha256"] == sha256_bytes(text.encode()),
            "terminal": output["terminal_status"] == "completed",
            "runtime_model": selection["model"] == self._authority.model,
            "model_provider": selection["model_provider"] == "openai",
            "reasoning": selection["reasoning_effort"] == self._authority.reasoning_effort,
            "service_tier": selection["service_tier"] == self._authority.service_tier,
            "public_model": identity["public_model"] == self._authority.model,
            "client_model": identity["client_requested_model"] == self._authority.model,
            "configured_model": identity["configured_codex_model"] == self._authority.model,
            "requested_model": identity["requested_codex_model"] == self._authority.model,
            "requested_output_tokens": metadata["output_token_limit"]["requested_tokens"]
            == self._authority.requested_output_tokens,
            "output_limit_enforced": metadata["output_token_limit"]["enforced"] is False,
        }
        failed = sorted(name for name, valid in expected.items() if not valid)
        if failed:
            raise ValueError(f"runtime receipt is not bound to canary authority: {failed}")


def authority_json(authority: AuthorityContract) -> bytes:
    payload = asdict(authority)
    for key, value in list(payload.items()):
        if isinstance(value, Path):
            payload[key] = str(value)
        elif isinstance(value, dict) and isinstance(value.get("path"), Path):
            value["path"] = str(value["path"])
    return canonical_json_bytes(payload)


def render_preflight(value: dict[str, object]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))

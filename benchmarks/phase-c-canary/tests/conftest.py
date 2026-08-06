from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest

RUNTIME_REPO = Path(
    "/mnt/volume_ams3_1784742570542/infinity-context/runtimes/subscription-runtime/e904ec95/repo"
)
SECRET = "provider-free-fixture-secret-at-least-32-bytes"


def unsigned_receipt() -> dict[str, Any]:
    return {
        "metadata": {
            "schema_version": 2,
            "attestation_level": "provider_receipt",
            "usage_source": "codex_thread_token_usage_updated",
            "runtime_selection": {
                "account_binding_hmac_sha256": "4" * 64,
                "thread_id": "thread-provider-free",
                "turn_id": "turn-provider-free",
                "model": "gpt-5.6-sol",
                "model_provider": "openai",
                "reasoning_effort": "high",
                "service_tier": "default",
                "execution_profile": "stateless-completion",
                "base_instructions_sha256": (
                    "5c15d6c502d380282a933d4f20a886a06c9d04d3b5d7c918b95df0b0acf33671"
                ),
            },
            "request_identity": {
                "public_model": "gpt-5.6-sol",
                "client_requested_model": "gpt-5.6-sol",
                "configured_codex_model": "gpt-5.6-sol",
                "requested_codex_model": "gpt-5.6-sol",
                "request_body_sha256": "1" * 64,
                "response_format_type": "json_schema",
                "response_format_sha256": (
                    "812938567c7a81bac6ed3266608adf470dedc57706102e039422f695495322bf"
                ),
                "response_schema_sha256": (
                    "2461f7a465be82aa67751dc04e0717cde75c69b86e7db54bb306a2e3d1d4d8f0"
                ),
            },
            "output_identity": {
                "output_text_sha256": hashlib.sha256(
                    b'{"reasoning":"Evidence matches.","label":"CORRECT"}'
                ).hexdigest(),
                "terminal_status": "completed",
            },
            "output_token_limit": {"requested_tokens": 4096, "enforced": False},
            "receipt_hmac_sha256": "0" * 64,
        },
        "usage": {
            "prompt_tokens": 10,
            "prompt_tokens_details": {"cached_tokens": 2},
            "completion_tokens": 4,
            "completion_tokens_details": {"reasoning_tokens": 1},
            "total_tokens": 14,
        },
    }


def sign_receipt(receipt: dict[str, Any], secret: str = SECRET) -> dict[str, Any]:
    result = copy.deepcopy(receipt)
    canonical_url = (
        RUNTIME_REPO / "dist/openai-compatible-codex/chat-completions/domain/runtime-attestation.js"
    ).as_uri()
    script = r"""
import {createHmac} from "node:crypto";
let body = ""; for await (const chunk of process.stdin) body += chunk;
const {receipt, secret, canonical_url} = JSON.parse(body); const m = receipt.metadata;
const {openAiBridgeRuntimeAttestationCanonicalBytes} = await import(canonical_url);
const bytes = openAiBridgeRuntimeAttestationCanonicalBytes({
  selection:m.runtime_selection, requestIdentity:m.request_identity,
  outputIdentity:m.output_identity, usage:receipt.usage,
  requestedOutputTokenLimit:m.output_token_limit.requested_tokens ?? undefined,
});
process.stdout.write(createHmac("sha256", secret).update(bytes).digest("hex"));
"""
    completed = subprocess.run(
        ["/usr/local/bin/node", "--input-type=module", "-e", script],
        cwd=RUNTIME_REPO,
        env={"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8"},
        input=json.dumps({"receipt": result, "secret": secret, "canonical_url": canonical_url}),
        text=True,
        capture_output=True,
        check=True,
    )
    result["metadata"]["receipt_hmac_sha256"] = completed.stdout
    return result


@lru_cache(maxsize=1)
def _signed_fixture() -> dict[str, Any]:
    return sign_receipt(unsigned_receipt())


@pytest.fixture
def receipt() -> dict[str, Any]:
    return copy.deepcopy(_signed_fixture())

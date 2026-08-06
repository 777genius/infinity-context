from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
from conftest import RUNTIME_REPO, SECRET

import phase_c_canary.receipt as receipt_module
from phase_c_canary.receipt import NodePublicReceiptVerifier, ReceiptVerificationError


def verifier() -> NodePublicReceiptVerifier:
    return NodePublicReceiptVerifier(RUNTIME_REPO)


def test_public_runtime_verifier_accepts_valid_fixture(receipt: dict[str, Any]) -> None:
    verifier().verify(receipt=receipt, secret=SECRET)


def _signed_leaf_paths() -> list[tuple[str, ...]]:
    return (
        [
            ("metadata", "runtime_selection", key)
            for key in (
                "account_binding_hmac_sha256",
                "thread_id",
                "turn_id",
                "model",
                "model_provider",
                "reasoning_effort",
                "service_tier",
                "execution_profile",
                "base_instructions_sha256",
            )
        ]
        + [
            ("metadata", "request_identity", key)
            for key in (
                "public_model",
                "client_requested_model",
                "configured_codex_model",
                "requested_codex_model",
                "request_body_sha256",
                "response_format_type",
                "response_format_sha256",
                "response_schema_sha256",
            )
        ]
        + [
            ("metadata", "output_identity", "output_text_sha256"),
            ("metadata", "output_identity", "terminal_status"),
            ("metadata", "output_token_limit", "requested_tokens"),
            ("usage", "prompt_tokens"),
            ("usage", "completion_tokens"),
            ("usage", "total_tokens"),
            ("usage", "prompt_tokens_details"),
            ("usage", "completion_tokens_details"),
        ]
    )


@pytest.mark.parametrize("path", _signed_leaf_paths())
def test_tamper_every_signed_field_is_rejected(
    receipt: dict[str, Any], path: tuple[str, ...]
) -> None:
    tampered = copy.deepcopy(receipt)
    target: dict[str, Any] = tampered
    for key in path[:-1]:
        target = target[key]
    current = target[path[-1]]
    target[path[-1]] = current + 1 if isinstance(current, int) else "tampered"
    with pytest.raises(ReceiptVerificationError):
        verifier().verify(receipt=tampered, secret=SECRET)


def test_tampered_hmac_is_rejected(receipt: dict[str, Any]) -> None:
    receipt["metadata"]["receipt_hmac_sha256"] = "f" * 64
    with pytest.raises(ReceiptVerificationError):
        verifier().verify(receipt=receipt, secret=SECRET)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("schema_version", 3),
        ("attestation_level", "self_reported"),
        ("usage_source", "estimated"),
    ],
)
def test_fixed_receipt_authority_fields_are_rejected(
    receipt: dict[str, Any], key: str, value: object
) -> None:
    receipt["metadata"][key] = value
    with pytest.raises(ReceiptVerificationError):
        verifier().verify(receipt=receipt, secret=SECRET)


@pytest.mark.parametrize(
    ("container", "key"),
    [
        (("metadata",), "usage_source"),
        (("metadata", "runtime_selection"), "thread_id"),
        (("metadata", "request_identity"), "request_body_sha256"),
        (("metadata", "output_identity"), "terminal_status"),
        (("metadata", "output_token_limit"), "enforced"),
        (("usage",), "total_tokens"),
    ],
)
def test_missing_keys_are_rejected(
    receipt: dict[str, Any], container: tuple[str, ...], key: str
) -> None:
    target = receipt
    for part in container:
        target = target[part]
    del target[key]
    with pytest.raises(ReceiptVerificationError, match="keys"):
        verifier().verify(receipt=receipt, secret=SECRET)


def test_extra_key_is_rejected(receipt: dict[str, Any]) -> None:
    receipt["metadata"]["private_prompt"] = "must never be accepted"
    with pytest.raises(ReceiptVerificationError, match="keys"):
        verifier().verify(receipt=receipt, secret=SECRET)


def test_extra_nested_usage_key_is_rejected(receipt: dict[str, Any]) -> None:
    receipt["usage"]["prompt_tokens_details"]["estimated_tokens"] = 99
    with pytest.raises(ReceiptVerificationError, match="keys"):
        verifier().verify(receipt=receipt, secret=SECRET)


def test_verifier_uses_immutable_runtime_path() -> None:
    assert verifier().runtime_repo == Path(RUNTIME_REPO)


def test_verifier_imports_exact_manifest_listed_dist_url() -> None:
    resolved = verifier()._verified_module_url()
    assert (
        resolved
        == (
            RUNTIME_REPO / "dist/openai-compatible-codex/chat-completions/adapters/crypto/"
            "node-runtime-attestation-verifier.js"
        ).as_uri()
    )
    assert "@vioxen/subscription-runtime" not in receipt_module._NODE_VERIFIER

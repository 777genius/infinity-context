"""Shared outer-to-adapter secret role separation."""

from __future__ import annotations

import hmac

from .publishable_run_contracts import PublishableRunError, PublishableRunSecrets


def require_cross_layer_secret_distinctness(secrets: PublishableRunSecrets) -> None:
    """Reject adapter plaintext or hex material equal to an outer authority key."""

    if type(secrets) is not PublishableRunSecrets:
        _fail("publishable_run_orchestrator_inputs_invalid")
    outer_keys = (
        secrets.official_case_authentication_key,
        *secrets.scheduler_authentication_keys,
        secrets.suite_seal_authentication_key,
        secrets.publication_receipt_authentication_key,
    )
    stack: list[object] = [secrets.adapter_secrets()]
    while stack:
        current = stack.pop()
        if type(current) is dict:
            stack.extend(current.values())
        elif type(current) is list:
            stack.extend(current)
        elif type(current) is str and any(
            _adapter_string_matches_key(current, key) for key in outer_keys
        ):
            _fail("publishable_run_cross_layer_secret_reuse")


def _adapter_string_matches_key(value: str, key: bytes) -> bool:
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError:
        _fail("publishable_run_adapter_secrets_invalid")
    if len(encoded) == len(key) and hmac.compare_digest(encoded, key):
        return True
    return (
        len(value) == len(key) * 2
        and value.isascii()
        and all(character in "0123456789abcdefABCDEF" for character in value)
        and hmac.compare_digest(value.casefold(), key.hex())
    )


def _fail(code: str) -> None:
    raise PublishableRunError(code) from None


__all__ = ("require_cross_layer_secret_distinctness",)

"""Provider-free low-level adapter for the attested subscription-runtime bridge.

Exports are lazy so process-only deployments do not import optional cipher and
HTTP adapters merely by loading ``process_contracts`` or ``process_launcher``.
"""

from __future__ import annotations

from importlib import import_module
from typing import Final

_EXPORTS: Final = {
    "Aes256GcmOutputCipher": ("aes_gcm_output_cipher", "Aes256GcmOutputCipher"),
    "AuthenticatedBridgeResult": ("contracts", "AuthenticatedBridgeResult"),
    "BoundPrivateOutput": ("service", "BoundPrivateOutput"),
    "BridgeAuthority": ("contracts", "BridgeAuthority"),
    "BridgeAuthorityError": ("contracts", "BridgeAuthorityError"),
    "BridgeCallBinding": ("contracts", "BridgeCallBinding"),
    "BridgeDivergenceError": ("contracts", "BridgeDivergenceError"),
    "BridgeIntent": ("contracts", "BridgeIntent"),
    "BridgeIntentError": ("contracts", "BridgeIntentError"),
    "BridgeJournal": ("journal", "BridgeJournal"),
    "BridgeJournalError": ("contracts", "BridgeJournalError"),
    "BridgeJournalStatistics": ("journal", "BridgeJournalStatistics"),
    "BridgePoolAuthority": ("contracts", "BridgePoolAuthority"),
    "BridgeReceiptError": ("contracts", "BridgeReceiptError"),
    "BridgeSecretCapability": ("contracts", "BridgeSecretCapability"),
    "BridgeTransportError": ("contracts", "BridgeTransportError"),
    "BridgeTransportPort": ("contracts", "BridgeTransportPort"),
    "FileOutputCipherKeyringSpec": (
        "file_output_cipher_keyring",
        "FileOutputCipherKeyringSpec",
    ),
    "HmacJournalIntegrity": ("journal", "HmacJournalIntegrity"),
    "HttpxOneShotBridgeTransport": ("http_transport", "HttpxOneShotBridgeTransport"),
    "NotFound": ("contracts", "NotFound"),
    "OUTPUT_CIPHER_KEYRING_SCHEMA": (
        "file_output_cipher_keyring",
        "OUTPUT_CIPHER_KEYRING_SCHEMA",
    ),
    "OutcomeUnknown": ("contracts", "OutcomeUnknown"),
    "OutputCipherError": ("aes_gcm_output_cipher", "OutputCipherError"),
    "OutputCipherKey": ("aes_gcm_output_cipher", "OutputCipherKey"),
    "OutputCipherKeyResolver": ("aes_gcm_output_cipher", "OutputCipherKeyResolver"),
    "OutputCipherKeyringError": (
        "file_output_cipher_keyring",
        "OutputCipherKeyringError",
    ),
    "OutputCipherPort": ("contracts", "OutputCipherPort"),
    "PrivateFileOutputCipherKeyResolver": (
        "file_output_cipher_keyring",
        "PrivateFileOutputCipherKeyResolver",
    ),
    "PrivateOutputError": ("contracts", "PrivateOutputError"),
    "SubscriptionRuntimeBridgeAdapter": ("service", "SubscriptionRuntimeBridgeAdapter"),
    "TerminalBridgeCall": ("service", "TerminalBridgeCall"),
    "TerminalOutcome": ("contracts", "TerminalOutcome"),
    "TokenUsage": ("contracts", "TokenUsage"),
    "canonical_openai_request_body": (
        "request_contract",
        "canonical_openai_request_body",
    ),
    "output_cipher_key_commitment_sha256": (
        "file_output_cipher_keyring",
        "output_cipher_key_commitment_sha256",
    ),
    "output_cipher_keyring_commitment_sha256": (
        "file_output_cipher_keyring",
        "output_cipher_keyring_commitment_sha256",
    ),
}


def __getattr__(name: str) -> object:
    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value = getattr(import_module(f"{__name__}.{module_name}"), attribute)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted((*globals(), *_EXPORTS))


__all__ = tuple(sorted(_EXPORTS))

"""Authenticated private-output encryption for the subscription-runtime bridge.

Envelope v1 is canonical network-order binary data::

    magic[4] | version[1] | flags[1] | key_id_bytes[2] |
    plaintext_bytes[4] | nonce[12] | key_id | ciphertext | tag[16]

The version fixes AES-256-GCM, flags must be zero, and key identifiers are restricted
ASCII.  The complete header and the bridge-provided AAD are authenticated under a
module-specific domain.  Envelope overhead is therefore 41 to 168 bytes.
"""

from __future__ import annotations

import os
import re
import struct
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_MAGIC = b"ICBO"
_VERSION = 1
_FLAGS = 0
_KEY_BYTES = 32
_NONCE_BYTES = 12
_TAG_BYTES = 16
_MAX_KEY_ID_BYTES = 128
_MAX_ASSOCIATED_DATA_BYTES = 64 * 1024
_MAX_CIPHERTEXT_BYTES = 64 * 1024 * 1024
_KEY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_HEADER = struct.Struct(">4sBBHI12s")
_AAD_DOMAIN = b"infinity-context/subscription-runtime-bridge/private-output/aes-256-gcm/v1\0"


class OutputCipherError(RuntimeError):
    """Stable, non-secret failure from private-output encryption or decryption."""


@dataclass(frozen=True, slots=True)
class OutputCipherKey:
    """One exact key identity and AES-256 secret returned by a key resolver."""

    key_id: str
    secret: bytes = field(repr=False)

    def __post_init__(self) -> None:
        _encode_key_id(self.key_id)
        if type(self.secret) is not bytes or len(self.secret) != _KEY_BYTES:
            raise OutputCipherError("bridge_output_cipher_key_invalid")


class OutputCipherKeyResolver(Protocol):
    """Resolve only the active key or one exact persisted key identity."""

    def active_key(self) -> OutputCipherKey: ...

    def resolve_key(self, key_id: str, /) -> OutputCipherKey: ...


class Aes256GcmOutputCipher:
    """AES-256-GCM implementation of ``OutputCipherPort`` with a strict envelope."""

    ENVELOPE_VERSION = _VERSION
    NONCE_BYTES = _NONCE_BYTES
    MAX_ENVELOPE_OVERHEAD_BYTES = _HEADER.size + _MAX_KEY_ID_BYTES + _TAG_BYTES

    __slots__ = (
        "_key_resolver",
        "_maximum_ciphertext_bytes",
        "_nonce_lock",
        "_nonce_source",
        "_used_nonces",
    )

    def __init__(
        self,
        *,
        key_resolver: OutputCipherKeyResolver,
        maximum_ciphertext_bytes: int,
        nonce_source: Callable[[int], bytes] | None = None,
    ) -> None:
        minimum = _HEADER.size + 1 + _TAG_BYTES
        if (
            type(maximum_ciphertext_bytes) is not int
            or not minimum <= maximum_ciphertext_bytes <= _MAX_CIPHERTEXT_BYTES
        ):
            raise OutputCipherError("bridge_output_cipher_byte_limit_invalid")
        self._key_resolver = key_resolver
        self._maximum_ciphertext_bytes = maximum_ciphertext_bytes
        self._nonce_source = os.urandom if nonce_source is None else nonce_source
        self._nonce_lock = threading.Lock()
        self._used_nonces: set[bytes] = set()

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(maximum_ciphertext_bytes="
            f"{self._maximum_ciphertext_bytes}, key_resolver=<redacted>)"
        )

    @staticmethod
    def envelope_overhead(key_id: str) -> int:
        """Return exact v1 expansion for a canonical key identifier."""

        return _HEADER.size + len(_encode_key_id(key_id)) + _TAG_BYTES

    def seal(self, plaintext: bytes, *, associated_data: bytes) -> bytes:
        _require_bytes(plaintext, "plaintext")
        _require_associated_data(associated_data)
        key = self._active_key()
        key_id = _encode_key_id(key.key_id)
        envelope_bytes = _HEADER.size + len(key_id) + len(plaintext) + _TAG_BYTES
        if envelope_bytes > self._maximum_ciphertext_bytes:
            raise OutputCipherError("bridge_output_cipher_plaintext_too_large")

        nonce = self._reserve_nonce()
        prefix = _HEADER.pack(
            _MAGIC,
            _VERSION,
            _FLAGS,
            len(key_id),
            len(plaintext),
            nonce,
        )
        header = prefix + key_id
        encrypted = _encrypt(
            key.secret,
            nonce=nonce,
            plaintext=plaintext,
            associated_data=_aead_associated_data(header, associated_data),
        )
        if len(encrypted) != len(plaintext) + _TAG_BYTES:
            raise OutputCipherError("bridge_output_cipher_encryption_failed")
        return header + encrypted

    def open(self, ciphertext: bytes, *, associated_data: bytes) -> bytes:
        _require_bytes(ciphertext, "ciphertext")
        _require_associated_data(associated_data)
        header, key_id, nonce, encrypted, plaintext_bytes = self._parse(ciphertext)
        key = self._resolved_key(key_id)
        plaintext = _decrypt(
            key.secret,
            nonce=nonce,
            ciphertext=encrypted,
            associated_data=_aead_associated_data(header, associated_data),
        )
        if len(plaintext) != plaintext_bytes:
            raise OutputCipherError("bridge_output_cipher_authentication_failed")
        return plaintext

    def _active_key(self) -> OutputCipherKey:
        key: object = None
        failed = False
        try:
            key = self._key_resolver.active_key()
        except Exception:
            failed = True
        if failed or type(key) is not OutputCipherKey:
            raise OutputCipherError("bridge_output_cipher_key_resolution_failed")
        return key

    def _resolved_key(self, key_id: str) -> OutputCipherKey:
        key: object = None
        failed = False
        try:
            key = self._key_resolver.resolve_key(key_id)
        except Exception:
            failed = True
        if failed or type(key) is not OutputCipherKey or key.key_id != key_id:
            raise OutputCipherError("bridge_output_cipher_key_resolution_failed")
        return key

    def _reserve_nonce(self) -> bytes:
        nonce: object = None
        failed = False
        with self._nonce_lock:
            try:
                nonce = self._nonce_source(_NONCE_BYTES)
            except Exception:
                failed = True
            if failed or type(nonce) is not bytes or len(nonce) != _NONCE_BYTES:
                raise OutputCipherError("bridge_output_cipher_nonce_invalid")
            if nonce in self._used_nonces:
                raise OutputCipherError("bridge_output_cipher_nonce_reuse")
            self._used_nonces.add(nonce)
        return nonce

    def _parse(self, ciphertext: bytes) -> tuple[bytes, str, bytes, bytes, int]:
        minimum = _HEADER.size + 1 + _TAG_BYTES
        if not minimum <= len(ciphertext) <= self._maximum_ciphertext_bytes:
            raise OutputCipherError("bridge_output_cipher_envelope_invalid")
        try:
            magic, version, flags, key_id_bytes, plaintext_bytes, nonce = _HEADER.unpack_from(
                ciphertext
            )
        except struct.error:
            raise OutputCipherError("bridge_output_cipher_envelope_invalid") from None
        if (
            magic != _MAGIC
            or version != _VERSION
            or flags != _FLAGS
            or not 1 <= key_id_bytes <= _MAX_KEY_ID_BYTES
        ):
            raise OutputCipherError("bridge_output_cipher_envelope_invalid")
        header_bytes = _HEADER.size + key_id_bytes
        expected_bytes = header_bytes + plaintext_bytes + _TAG_BYTES
        if expected_bytes != len(ciphertext):
            raise OutputCipherError("bridge_output_cipher_envelope_invalid")
        encoded_key_id = ciphertext[_HEADER.size : header_bytes]
        key_id = _decode_key_id(encoded_key_id)
        return (
            ciphertext[:header_bytes],
            key_id,
            nonce,
            ciphertext[header_bytes:],
            plaintext_bytes,
        )


def _encode_key_id(key_id: object) -> bytes:
    if (
        type(key_id) is not str
        or not 1 <= len(key_id) <= _MAX_KEY_ID_BYTES
        or _KEY_ID.fullmatch(key_id) is None
    ):
        raise OutputCipherError("bridge_output_cipher_key_invalid")
    return key_id.encode("ascii")


def _decode_key_id(encoded: bytes) -> str:
    try:
        key_id = encoded.decode("ascii", errors="strict")
    except UnicodeDecodeError:
        raise OutputCipherError("bridge_output_cipher_envelope_invalid") from None
    if _KEY_ID.fullmatch(key_id) is None or key_id.encode("ascii") != encoded:
        raise OutputCipherError("bridge_output_cipher_envelope_invalid")
    return key_id


def _require_bytes(value: object, label: str) -> None:
    if type(value) is not bytes:
        raise OutputCipherError(f"bridge_output_cipher_{label}_invalid")


def _require_associated_data(associated_data: object) -> None:
    if type(associated_data) is not bytes or len(associated_data) > _MAX_ASSOCIATED_DATA_BYTES:
        raise OutputCipherError("bridge_output_cipher_associated_data_invalid")


def _aead_associated_data(header: bytes, bridge_associated_data: bytes) -> bytes:
    return (
        _AAD_DOMAIN
        + len(header).to_bytes(2, "big")
        + header
        + len(bridge_associated_data).to_bytes(8, "big")
        + bridge_associated_data
    )


def _encrypt(
    secret: bytes,
    *,
    nonce: bytes,
    plaintext: bytes,
    associated_data: bytes,
) -> bytes:
    secret_copy = bytearray(secret)
    encrypted: object = None
    failed = False
    try:
        encrypted = AESGCM(secret_copy).encrypt(nonce, plaintext, associated_data)
    except Exception:
        failed = True
    finally:
        _wipe(secret_copy)
    if failed or type(encrypted) is not bytes:
        raise OutputCipherError("bridge_output_cipher_encryption_failed")
    return encrypted


def _decrypt(
    secret: bytes,
    *,
    nonce: bytes,
    ciphertext: bytes,
    associated_data: bytes,
) -> bytes:
    secret_copy = bytearray(secret)
    plaintext: object = None
    failed = False
    try:
        plaintext = AESGCM(secret_copy).decrypt(nonce, ciphertext, associated_data)
    except Exception:
        failed = True
    finally:
        _wipe(secret_copy)
    if failed or type(plaintext) is not bytes:
        raise OutputCipherError("bridge_output_cipher_authentication_failed")
    return plaintext


def _wipe(value: bytearray) -> None:
    value[:] = b"\0" * len(value)


__all__ = (
    "Aes256GcmOutputCipher",
    "OutputCipherError",
    "OutputCipherKey",
    "OutputCipherKeyResolver",
)

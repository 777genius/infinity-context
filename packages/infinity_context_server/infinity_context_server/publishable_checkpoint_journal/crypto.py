"""Local HMAC adapter for the publishable checkpoint journal."""

from __future__ import annotations

import hmac
import re
from dataclasses import dataclass
from hashlib import sha256
from typing import final

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")


@final
@dataclass(frozen=True, slots=True)
class HmacSha256JournalSigner:
    """A key-id-addressable HMAC-SHA256 signer injected into the service."""

    key_id: str
    secret: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.key_id, str) or not _IDENTIFIER.fullmatch(self.key_id):
            raise ValueError("journal signer key_id is invalid")
        if not isinstance(self.secret, bytes) or not self.secret:
            raise ValueError("journal signer secret is invalid")

    def sign(self, message: bytes) -> str:
        if not isinstance(message, bytes):
            raise TypeError("journal signer message must be exact bytes")
        return hmac.new(self.secret, message, sha256).hexdigest()

    def verify(self, message: bytes, signature: str) -> bool:
        if not isinstance(message, bytes) or not isinstance(signature, str):
            return False
        if not signature.isascii():
            return False
        return hmac.compare_digest(self.sign(message), signature)

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("HmacSha256JournalSigner is final")


__all__ = ("HmacSha256JournalSigner",)

"""Standard-library HMAC signer for local operation journals."""

from __future__ import annotations

import hashlib
import hmac
from typing import final

from infinity_context_server.resumable_operation_journal.domain import (
    OperationJournalError,
)


@final
class HmacSha256OperationJournalSigner:
    def __init__(self, *, key_id: str, secret: bytes) -> None:
        if not isinstance(key_id, str) or not key_id:
            raise OperationJournalError("operation_journal_signer_key_id_invalid")
        if not isinstance(secret, bytes) or len(secret) < 32:
            raise OperationJournalError("operation_journal_signer_secret_weak")
        self._key_id = key_id
        self._secret = secret

    @property
    def key_id(self) -> str:
        return self._key_id

    def sign(self, message: bytes) -> str:
        return hmac.new(self._secret, message, hashlib.sha256).hexdigest()

    def verify(self, message: bytes, signature: str) -> bool:
        return hmac.compare_digest(self.sign(message), signature)


__all__ = ("HmacSha256OperationJournalSigner",)

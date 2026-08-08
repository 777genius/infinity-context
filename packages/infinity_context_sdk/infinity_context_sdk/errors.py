"""Public SDK errors and safe HTTP error mapping."""

from __future__ import annotations

import httpx

from infinity_context_sdk._redaction import redact_sensitive_text


class InfinityContextError(RuntimeError):
    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        retryable: bool,
        unknown_commit_state: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.retryable = retryable
        self.unknown_commit_state = unknown_commit_state


def to_error(
    response: httpx.Response,
    *,
    mutation: bool = False,
) -> InfinityContextError:
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    error = payload.get("error", {}) if isinstance(payload, dict) else {}
    detail = payload.get("detail", {}) if isinstance(payload, dict) else {}
    code = str(error.get("code") or detail.get("code") or "memory.http_error")
    message = _safe_error_message(str(error.get("message") or response.text or code))
    retryable = bool(error.get("retryable", response.status_code >= 500))
    return InfinityContextError(
        status_code=response.status_code,
        code=code,
        message=message,
        retryable=retryable,
        unknown_commit_state=mutation and response.status_code >= 500,
    )


def _safe_error_message(value: str) -> str:
    return redact_sensitive_text(value.strip() or "Infinity Context request failed")[:500]


__all__ = ("InfinityContextError", "to_error")

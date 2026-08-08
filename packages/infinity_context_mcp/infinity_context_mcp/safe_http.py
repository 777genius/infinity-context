"""Small HTTP transport guardrails for credential-bearing local adapters."""

from __future__ import annotations

import urllib.request
from typing import Any


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    """Prevent urllib from forwarding authorization headers to another origin."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


_NO_REDIRECT_OPENER = urllib.request.build_opener(_RejectRedirects())


def open_without_redirects(request: urllib.request.Request, *, timeout: float):
    """Open one exact URL and surface every 30x response as HTTPError."""

    return _NO_REDIRECT_OPENER.open(request, timeout=timeout)


__all__ = ("open_without_redirects",)

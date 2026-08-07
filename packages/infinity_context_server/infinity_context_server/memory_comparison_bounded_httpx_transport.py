"""Bounded, environment-isolated httpx transport for local benchmark lanes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import final

import httpx

_DEFAULT_MAXIMUM_BYTES = 256_000
_STREAM_CHUNK_BYTES = 64_000


@final
@dataclass(frozen=True, slots=True)
class BoundedHttpResponse:
    status_code: int
    content: bytes

    def read_bounded(self, maximum_bytes: int) -> bytes:
        if maximum_bytes.__class__ is not int or len(self.content) > maximum_bytes:
            raise ValueError("response exceeds bound")
        return self.content


class BoundedHttpxTransport:
    """Read at most the configured response bound plus one rejection byte."""

    __slots__ = ("_maximum_bytes",)

    def __init__(self, maximum_bytes: int = _DEFAULT_MAXIMUM_BYTES) -> None:
        if maximum_bytes.__class__ is not int or maximum_bytes < 1:
            raise ValueError("maximum response bytes must be positive")
        self._maximum_bytes = maximum_bytes

    def request(self, method: str, url: str, **kwargs: object) -> BoundedHttpResponse:
        transport = httpx.HTTPTransport(retries=0, trust_env=False)
        with (
            httpx.Client(transport=transport, follow_redirects=False, trust_env=False) as client,
            client.stream(method, url, **kwargs) as response,
        ):
            content = bytearray()
            rejection_limit = self._maximum_bytes + 1
            for chunk in response.iter_bytes(chunk_size=min(_STREAM_CHUNK_BYTES, rejection_limit)):
                remaining = rejection_limit - len(content)
                if remaining <= 0:
                    break
                content.extend(chunk[:remaining])
                if len(content) == rejection_limit:
                    break
            return BoundedHttpResponse(response.status_code, bytes(content))


__all__ = ("BoundedHttpResponse", "BoundedHttpxTransport")

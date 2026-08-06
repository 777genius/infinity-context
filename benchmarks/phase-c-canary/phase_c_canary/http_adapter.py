from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from .hashing import canonical_json_bytes


@dataclass(frozen=True, slots=True)
class LoopbackJsonCompletionAdapter:
    endpoint: str
    timeout_seconds: float = 5

    def complete(self, request: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        parsed = urlsplit(self.endpoint)
        if (
            parsed.scheme != "http"
            or parsed.hostname != "127.0.0.1"
            or parsed.port is None
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError("fake adapter only permits IPv4 loopback")
        http_request = urllib.request.Request(
            self.endpoint,
            data=canonical_json_bytes(request),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(http_request, timeout=self.timeout_seconds) as response:
            payload = json.loads(response.read())
        if not isinstance(payload, dict) or set(payload) != {"envelope", "receipt"}:
            raise ValueError("fake completion response shape is invalid")
        return payload["envelope"], payload["receipt"]

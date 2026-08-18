"""Strict identity probe for an OpenAI-compatible TEI runtime."""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, build_opener

_MAX_INFO_BYTES = 65_536


@dataclass(frozen=True, slots=True)
class TeiIdentity:
    model_id: str
    model_sha: str
    build_sha: str
    inference_base_url: str


@dataclass(frozen=True, slots=True)
class TeiProbe:
    model_id: str
    model_sha: str
    build_sha: str
    inference_base_url: str
    info_url: str

    @classmethod
    def create(
        cls, *, model_id: str, model_sha: str, build_sha: str,
        inference_base_url: str, info_url: str,
    ) -> TeiProbe:
        inference, info = bound_runtime_urls(inference_base_url, info_url)
        return cls(model_id, model_sha, build_sha, inference, info)

    def verify(self) -> TeiIdentity:
        try:
            with _open_info(self.info_url, timeout=5) as response:
                if response.geturl() != self.info_url:
                    raise RuntimeError("embedding runtime info endpoint redirected")
                data = response.read(_MAX_INFO_BYTES + 1)
        except OSError as exc:
            raise RuntimeError("embedding runtime info endpoint is unavailable") from exc
        if len(data) > _MAX_INFO_BYTES:
            raise RuntimeError("embedding runtime info response exceeds its size limit")
        try:
            payload = json.loads(data)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("embedding runtime info response is malformed") from exc
        expected = {
            "model_id": self.model_id,
            "model_sha": self.model_sha,
            "sha": self.build_sha,
        }
        if not isinstance(payload, dict) or any(payload.get(k) != v for k, v in expected.items()):
            raise RuntimeError("embedding runtime identity does not match frozen profile")
        return TeiIdentity(
            self.model_id, self.model_sha, self.build_sha, self.inference_base_url
        )


def bound_runtime_urls(base_url: str, info_url: str) -> tuple[str, str]:
    inference = _normalized_url(base_url, "embedding inference base URL")
    info = _normalized_url(info_url, "embedding runtime info URL")
    if inference[:3] != info[:3]:
        raise RuntimeError("embedding runtime info URL does not match inference origin")
    inference_path = inference[3].rstrip("/")
    if not inference_path.endswith("/v1"):
        raise RuntimeError("embedding inference base URL path must end in /v1")
    if info[3] != (f"{inference_path[:-3]}/info" or "/info"):
        raise RuntimeError("embedding runtime info URL does not match inference path")
    return _render(*inference[:3], inference_path), _render(*info)


def _normalized_url(url: str, label: str) -> tuple[str, str, int, str]:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise RuntimeError(f"{label} has an invalid port") from exc
    if (
        parsed.scheme not in {"http", "https"} or parsed.hostname is None
        or parsed.username is not None or parsed.password is not None
        or parsed.query or parsed.fragment or not parsed.path.startswith("/")
        or "//" in parsed.path or "%" in parsed.path
        or any(part in {".", ".."} for part in parsed.path.split("/"))
    ):
        raise RuntimeError(f"{label} must be a credential-free HTTP(S) URL")
    effective_port = port or (443 if parsed.scheme == "https" else 80)
    return parsed.scheme, parsed.hostname.lower(), effective_port, parsed.path


def _render(scheme: str, host: str, port: int, path: str) -> str:
    default = (scheme, port) in {("http", 80), ("https", 443)}
    host = f"[{host}]" if ":" in host else host
    return f"{scheme}://{host if default else f'{host}:{port}'}{path}"


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _open_info(url: str, *, timeout: int):
    return build_opener(_RejectRedirects).open(url, timeout=timeout)  # noqa: S310

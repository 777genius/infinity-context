"""Safe transport and verification for the mem0 benchmark auth challenge."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import re
from dataclasses import dataclass
from urllib.parse import urlparse

MEM0_BENCHMARK_AUTH_CHALLENGE_PATH = "/benchmark/auth-challenge"
MEM0_BENCHMARK_AUTH_CHALLENGE_SCHEMA_VERSION = (
    "mem0-benchmark-auth-challenge.v1"
)
MEM0_BENCHMARK_PROBE_TOKEN_ENV = "MEM0_BENCHMARK_PROBE_TOKEN"
_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class AuthChallengeVerification:
    """Sanitized result of verifying one challenge response."""

    passed: bool
    reason_code: str | None = None


@dataclass(frozen=True)
class AuthChallengeProbeResult:
    """Sanitized transport and verification result for one challenge request."""

    passed: bool
    reason_code: str | None = None
    status_code: int | None = None
    error_type: str | None = None


def generate_auth_challenge_nonce() -> str:
    """Generate a cryptographically random 256-bit nonce encoded as lowercase hex."""

    import secrets

    return secrets.token_hex(32)


def is_safe_auth_challenge_target(base_url: str) -> bool:
    """Allow credentials only over HTTPS or an explicit loopback HTTP target."""

    parsed = urlparse(str(base_url or ""))
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        return False
    try:
        _ = parsed.port
    except ValueError:
        return False
    if parsed.scheme == "https":
        return True
    return _is_loopback_host(parsed.hostname)


def verify_auth_challenge_response(
    payload: object,
    *,
    nonce: str,
    token: str,
) -> AuthChallengeVerification:
    """Verify schema, nonce binding and HMAC without exposing secret material."""

    if not isinstance(payload, dict):
        return AuthChallengeVerification(False, "invalid_response_payload")
    if payload.get("schema_version") != MEM0_BENCHMARK_AUTH_CHALLENGE_SCHEMA_VERSION:
        return AuthChallengeVerification(False, "invalid_schema_version")

    nonce_sha256 = payload.get("nonce_sha256")
    signature = payload.get("signature")
    if not _is_sha256_hex(nonce_sha256):
        return AuthChallengeVerification(False, "invalid_nonce_sha256")
    if not _is_sha256_hex(signature):
        return AuthChallengeVerification(False, "invalid_signature")

    expected_nonce_sha256 = hashlib.sha256(nonce.encode("ascii")).hexdigest()
    if not hmac.compare_digest(nonce_sha256, expected_nonce_sha256):
        return AuthChallengeVerification(False, "nonce_sha256_mismatch")

    message = f"{MEM0_BENCHMARK_AUTH_CHALLENGE_SCHEMA_VERSION}\n{nonce}"
    expected_signature = hmac.new(
        token.encode("utf-8"),
        message.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected_signature):
        return AuthChallengeVerification(False, "signature_mismatch")
    return AuthChallengeVerification(True)


def probe_mem0_benchmark_auth_challenge(
    base_url: str,
    *,
    token: str,
    timeout_seconds: float,
) -> AuthChallengeProbeResult:
    """Call and verify the side-effect-free managed runtime challenge."""

    nonce = generate_auth_challenge_nonce()
    try:
        import httpx

        with httpx.Client(
            base_url=str(base_url).rstrip("/"),
            timeout=max(0.1, timeout_seconds),
            follow_redirects=False,
            trust_env=False,
        ) as client:
            response = client.post(
                MEM0_BENCHMARK_AUTH_CHALLENGE_PATH,
                headers={"X-Benchmark-Probe-Token": token},
                json={"nonce": nonce},
            )
            payload = response.json() if 200 <= response.status_code < 300 else None
    except Exception as exc:
        return AuthChallengeProbeResult(
            passed=False,
            reason_code="mem0_benchmark_auth_challenge_request_failed",
            error_type=type(exc).__name__,
        )

    if not 200 <= response.status_code < 300:
        return AuthChallengeProbeResult(
            passed=False,
            reason_code="mem0_benchmark_auth_challenge_unhealthy_status",
            status_code=response.status_code,
        )

    verification = verify_auth_challenge_response(payload, nonce=nonce, token=token)
    return AuthChallengeProbeResult(
        passed=verification.passed,
        reason_code=verification.reason_code,
        status_code=response.status_code,
    )


def _is_loopback_host(host: str) -> bool:
    normalized = host.rstrip(".").lower()
    if normalized == "localhost" or normalized.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _is_sha256_hex(value: object) -> bool:
    return isinstance(value, str) and _SHA256_HEX_RE.fullmatch(value) is not None

"""One-call live readiness probe for the local subscription-runtime bridge.

The caller transfers ownership of a dedicated chat adapter. This module makes
at most one provider attempt, closes the adapter on every exit path, and seals
only canonical evidence digests plus bounded token usage.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime

from infinity_context_server.memory_comparison_provider_provenance import (
    ProviderChatCompletion,
    ProviderRouteAttestation,
    canonical_request_sha256,
)
from infinity_context_server.memory_comparison_subscription_chat import (
    SUBSCRIPTION_CHAT_ENDPOINT_PATH,
    SUBSCRIPTION_OUTPUT_LIMIT_EVIDENCE,
    SUBSCRIPTION_RUNTIME_TRANSPORT_EVIDENCE,
    SUBSCRIPTION_RUNTIME_TRUST,
    SubscriptionRuntimeChatCompletions,
)
from infinity_context_server.memory_comparison_subscription_probe import (
    VerifiedSubscriptionRuntimeProbe,
    _subscription_runtime_probe_issuer,
)

SUBSCRIPTION_LIVE_PROBE_SYSTEM_PROMPT = (
    "Reply with exactly READY in uppercase and no punctuation or other text."
)
SUBSCRIPTION_LIVE_PROBE_USER_PROMPT = "Readiness check."
SUBSCRIPTION_LIVE_PROBE_EXPECTED_RESPONSE = "READY"
SUBSCRIPTION_LIVE_PROBE_MAX_OUTPUT_TOKENS = 8
SUBSCRIPTION_LIVE_PROBE_MAX_TOTAL_TOKENS = 512

_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_SAFE_ERROR_CODES = frozenset(
    {
        "subscription_live_probe_close_failed",
        "subscription_live_probe_failed",
        "subscription_live_probe_request_invalid",
        "subscription_live_probe_response_invalid",
        "subscription_live_probe_route_invalid",
        "subscription_live_probe_usage_invalid",
    }
)


class SubscriptionRuntimeLiveProbeError(RuntimeError):
    """Secret-safe readiness failure represented by a stable error code."""

    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        safe_code = code if code in _SAFE_ERROR_CODES else "subscription_live_probe_failed"
        self.code = safe_code
        super().__init__(safe_code)


def run_subscription_runtime_live_probe(
    adapter: SubscriptionRuntimeChatCompletions,
    *,
    expected_route: ProviderRouteAttestation,
    model: str,
    clock: Callable[[], datetime],
) -> VerifiedSubscriptionRuntimeProbe:
    """Perform one readiness completion and consume the dedicated adapter.

    The concrete adapter is required because it guarantees disabled retries.
    The adapter is closed even when request, route, response or evidence
    validation fails. Provider prompts and output never enter sealed state.
    """

    if type(adapter) is not SubscriptionRuntimeChatCompletions:
        raise TypeError("subscription live probe requires its dedicated adapter")

    evidence: VerifiedSubscriptionRuntimeProbe | None = None
    failure: SubscriptionRuntimeLiveProbeError | None = None
    try:
        evidence = _perform_probe(
            adapter,
            expected_route=expected_route,
            model=model,
            clock=clock,
        )
    except SubscriptionRuntimeLiveProbeError as exc:
        failure = exc
    except Exception:
        failure = SubscriptionRuntimeLiveProbeError("subscription_live_probe_failed")

    try:
        adapter.close()
    except Exception:
        if failure is None:
            failure = SubscriptionRuntimeLiveProbeError("subscription_live_probe_close_failed")

    if failure is not None:
        raise failure from None
    if evidence is None:  # pragma: no cover - defensive invariant
        raise SubscriptionRuntimeLiveProbeError("subscription_live_probe_failed")
    return evidence


def _perform_probe(
    adapter: SubscriptionRuntimeChatCompletions,
    *,
    expected_route: ProviderRouteAttestation,
    model: str,
    clock: Callable[[], datetime],
) -> VerifiedSubscriptionRuntimeProbe:
    trusted_model = _trusted_model(model)
    planned_route = _trusted_planned_route(expected_route, adapter=adapter)
    if not callable(clock):
        _fail("subscription_live_probe_request_invalid")

    completion = adapter.complete(
        model=trusted_model,
        system_prompt=SUBSCRIPTION_LIVE_PROBE_SYSTEM_PROMPT,
        user_prompt=SUBSCRIPTION_LIVE_PROBE_USER_PROMPT,
        max_output_tokens=SUBSCRIPTION_LIVE_PROBE_MAX_OUTPUT_TOKENS,
    )
    observed_route = adapter.route_attestation
    _require_observed_route(observed_route, planned=planned_route)
    total_tokens = _trusted_usage(completion)
    checked_at = _trusted_instant(clock())

    request_sha256 = canonical_request_sha256(
        endpoint_path=planned_route.endpoint_path,
        payload=_probe_request_payload(trusted_model),
    )
    response_sha256 = _response_evidence_sha256(
        completion,
        model=trusted_model,
        route=observed_route,
    )
    try:
        return _subscription_runtime_probe_issuer(
            route=observed_route,
            model=trusted_model,
            provider_call_count=1,
            total_tokens=total_tokens,
            request_evidence_sha256=request_sha256,
            response_evidence_sha256=response_sha256,
            checked_at=checked_at,
        )
    except Exception:
        raise SubscriptionRuntimeLiveProbeError("subscription_live_probe_failed") from None


def _trusted_model(value: object) -> str:
    if type(value) is not str or _MODEL_RE.fullmatch(value) is None:
        _fail("subscription_live_probe_request_invalid")
    return value


def _trusted_planned_route(
    route: object,
    *,
    adapter: SubscriptionRuntimeChatCompletions,
) -> ProviderRouteAttestation:
    actual = adapter.route_attestation
    if (
        type(route) is not ProviderRouteAttestation
        or route != actual
        or route.trust != SUBSCRIPTION_RUNTIME_TRUST
        or route.endpoint_path != SUBSCRIPTION_CHAT_ENDPOINT_PATH
        or route.transport_evidence != SUBSCRIPTION_RUNTIME_TRANSPORT_EVIDENCE
        or route.request_method != "POST"
        or route.response_status != 0
        or route.route_sha256
        != hashlib.sha256(f"{route.origin}{route.endpoint_path}".encode()).hexdigest()
        or adapter.output_limit_evidence != SUBSCRIPTION_OUTPUT_LIMIT_EVIDENCE
    ):
        _fail("subscription_live_probe_route_invalid")
    return route


def _require_observed_route(
    route: object,
    *,
    planned: ProviderRouteAttestation,
) -> None:
    if (
        type(route) is not ProviderRouteAttestation
        or route.trust != planned.trust
        or route.origin != planned.origin
        or route.endpoint_path != planned.endpoint_path
        or route.route_sha256 != planned.route_sha256
        or route.transport_evidence != planned.transport_evidence
        or route.credential_binding_id != planned.credential_binding_id
        or route.request_method != planned.request_method
        or route.response_status != 200
    ):
        _fail("subscription_live_probe_route_invalid")


def _trusted_usage(completion: object) -> int:
    if type(completion) is not ProviderChatCompletion:
        _fail("subscription_live_probe_response_invalid")
    if (
        completion.text != SUBSCRIPTION_LIVE_PROBE_EXPECTED_RESPONSE
        or completion.finish_reason != "stop"
        or completion.finish_reason_source != "provider_observed"
        or completion.provenance is not None
    ):
        _fail("subscription_live_probe_response_invalid")
    prompt_tokens = completion.prompt_tokens
    output_tokens = completion.completion_tokens
    if (
        type(prompt_tokens) is not int
        or type(output_tokens) is not int
        or prompt_tokens <= 0
        or not 1 <= output_tokens <= SUBSCRIPTION_LIVE_PROBE_MAX_OUTPUT_TOKENS
        or completion.token_usage_source != "provider_observed"
    ):
        _fail("subscription_live_probe_usage_invalid")
    total_tokens = prompt_tokens + output_tokens
    if total_tokens > SUBSCRIPTION_LIVE_PROBE_MAX_TOTAL_TOKENS:
        _fail("subscription_live_probe_usage_invalid")
    return total_tokens


def _trusted_instant(value: object) -> datetime:
    if type(value) is not datetime or value.tzinfo is None:
        _fail("subscription_live_probe_request_invalid")
    normalized = value.astimezone(UTC)
    if not 1970 <= normalized.year <= 2100:
        _fail("subscription_live_probe_request_invalid")
    return normalized


def _probe_request_payload(model: str) -> Mapping[str, object]:
    return {
        "max_tokens": SUBSCRIPTION_LIVE_PROBE_MAX_OUTPUT_TOKENS,
        "messages": [
            {"role": "system", "content": SUBSCRIPTION_LIVE_PROBE_SYSTEM_PROMPT},
            {"role": "user", "content": SUBSCRIPTION_LIVE_PROBE_USER_PROMPT},
        ],
        "model": model,
    }


def _response_evidence_sha256(
    completion: ProviderChatCompletion,
    *,
    model: str,
    route: ProviderRouteAttestation,
) -> str:
    payload = {
        "completion_text_sha256": hashlib.sha256(completion.text.encode()).hexdigest(),
        "completion_tokens": completion.completion_tokens,
        "finish_reason": completion.finish_reason,
        "finish_reason_source": completion.finish_reason_source,
        "model": model,
        "prompt_tokens": completion.prompt_tokens,
        "route_sha256": route.route_sha256,
        "token_usage_source": completion.token_usage_source,
    }
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _fail(code: str) -> None:
    raise SubscriptionRuntimeLiveProbeError(code)


__all__ = (
    "SUBSCRIPTION_LIVE_PROBE_EXPECTED_RESPONSE",
    "SUBSCRIPTION_LIVE_PROBE_MAX_OUTPUT_TOKENS",
    "SUBSCRIPTION_LIVE_PROBE_MAX_TOTAL_TOKENS",
    "SUBSCRIPTION_LIVE_PROBE_SYSTEM_PROMPT",
    "SUBSCRIPTION_LIVE_PROBE_USER_PROMPT",
    "SubscriptionRuntimeLiveProbeError",
    "run_subscription_runtime_live_probe",
)

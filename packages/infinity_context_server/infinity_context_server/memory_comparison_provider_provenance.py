"""Provider-neutral chat port and provenance contract composition."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

PROVIDER_CALL_PROVENANCE_SCHEMA_VERSION = "memory-comparison-provider-call.v1"
PROVIDER_PROVENANCE_CONTRACT_SCHEMA_VERSION = "memory-comparison-provider-contract.v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PUBLIC_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_SENSITIVE_RE = re.compile(
    r"(?:\bBearer\s+|\bAuthorization\b|\bapi[_-]?key\b|\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{4,})",
    re.IGNORECASE,
)
_PUBLIC_PROVENANCE_KEYS = frozenset(
    {
        "schema_version",
        "trust",
        "origin",
        "endpoint_path",
        "route_sha256",
        "transport_evidence",
        "credential_bound",
        "credential_binding_id",
        "request_method",
        "response_status",
        "requested_model",
        "observed_model",
        "response_id",
        "system_fingerprint",
        "request_sha256",
    }
)


@dataclass(frozen=True, slots=True)
class ProviderRouteAttestation:
    """Provider-owned safe route facts; secrets must already be commitments."""

    trust: str
    origin: str
    endpoint_path: str
    route_sha256: str
    transport_evidence: str
    credential_binding_id: str | None
    request_method: str = "POST"
    response_status: int = 0

    @property
    def credential_bound(self) -> bool:
        return bool(self.credential_binding_id)

    def public_payload(self) -> dict[str, object]:
        return {
            "trust": _safe_route_text(self.trust),
            "origin": _safe_route_text(self.origin),
            "endpoint_path": _safe_route_text(self.endpoint_path),
            "route_sha256": _safe_sha256(self.route_sha256),
            "transport_evidence": _safe_route_text(self.transport_evidence),
            "credential_bound": self.credential_bound,
            "credential_binding_id": (
                _safe_binding(self.credential_binding_id)
                if self.credential_binding_id is not None
                else None
            ),
            "request_method": _safe_route_text(self.request_method),
            "response_status": (
                self.response_status
                if isinstance(self.response_status, int)
                and not isinstance(self.response_status, bool)
                else 0
            ),
        }


@dataclass(frozen=True, slots=True)
class ProviderCallProvenance:
    """Observed and locally bound facts for one provider call."""

    route: ProviderRouteAttestation
    requested_model: str
    observed_model: str
    response_id: str
    system_fingerprint: str
    request_sha256: str

    def public_payload(self) -> dict[str, object]:
        payload = {
            "schema_version": PROVIDER_CALL_PROVENANCE_SCHEMA_VERSION,
            **self.route.public_payload(),
            "request_sha256": _safe_sha256(self.request_sha256),
        }
        for key, value in (
            ("requested_model", self.requested_model),
            ("observed_model", self.observed_model),
            ("response_id", self.response_id),
            ("system_fingerprint", self.system_fingerprint),
        ):
            public_value, value_hash = _public_identifier(value)
            payload[key] = public_value
            if value_hash is not None:
                payload[f"{key}_sha256"] = value_hash
        return payload


@dataclass(frozen=True, slots=True)
class ProviderChatCompletion:
    """Provider-neutral completion returned to benchmark adapters."""

    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    token_usage_source: str = ""
    finish_reason: str = ""
    finish_reason_source: str = ""
    provenance: ProviderCallProvenance | None = None


class ProviderChatCompletionsPort(Protocol):
    """Narrow provider-neutral completion port."""

    def complete(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int,
        temperature: float | None = None,
        response_format: Mapping[str, object] | None = None,
    ) -> ProviderChatCompletion:
        """Return one completion without exposing provider client types."""

    def close(self) -> None:
        """Release transport resources."""


class ProviderRoutePolicy(Protocol):
    """Provider-specific trust policy injected into generic composition."""

    @property
    def policy_id(self) -> str:
        """Return the stable policy identifier."""

    def call_issues(
        self,
        provenance: Mapping[str, object],
        *,
        required_model: str,
    ) -> Sequence[str]:
        """Return provider-specific issue suffixes for one public call payload."""

    def public_summary(self) -> Mapping[str, object]:
        """Return safe policy metadata for the contract summary."""


def canonical_request_sha256(
    *,
    endpoint_path: str,
    payload: Mapping[str, object],
) -> str:
    """Hash exact request semantics without headers or credentials."""

    canonical_json = json.dumps(
        dict(payload),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    material = f"POST\n{endpoint_path}\n{canonical_json}".encode()
    return hashlib.sha256(material).hexdigest()


def provider_provenance_contract(
    evaluations: Sequence[Mapping[str, object]],
    *,
    required_model: str,
    route_policy: ProviderRoutePolicy,
) -> dict[str, object]:
    """Compose generic per-call checks with an injected provider route policy."""

    model = str(required_model or "").strip()
    if not model:
        raise ValueError("provider provenance contract requires a model")
    issues: Counter[str] = Counter()
    trust: Counter[str] = Counter()
    observed_models: Counter[str] = Counter()
    fingerprints: Counter[str] = Counter()
    binding_ids: set[str] = set()
    response_ids: list[str] = []
    observed_call_count = 0
    for evaluation in evaluations:
        for report_key, stage in (("generation", "answerer"), ("judgment", "judge")):
            metadata = _mapping(_mapping(evaluation.get(report_key)).get("metadata"))
            raw_provenance = metadata.get("provider_provenance")
            if not isinstance(raw_provenance, Mapping) or not raw_provenance:
                issues[f"{stage}_missing"] += 1
                continue
            observed_call_count += 1
            typed_provenance, structurally_valid = _parse_public_provenance(
                raw_provenance
            )
            provenance = typed_provenance.public_payload()
            if not structurally_valid:
                issues[f"{stage}_payload"] += 1
            if raw_provenance.get("schema_version") != PROVIDER_CALL_PROVENANCE_SCHEMA_VERSION:
                issues[f"{stage}_schema"] += 1
            policy_issues = tuple(
                route_policy.call_issues(provenance, required_model=model)
            )
            for issue in policy_issues:
                issues[f"{stage}_{issue}"] += 1
            trust["rejected" if "route" in policy_issues else "accepted"] += 1
            if provenance.get("credential_bound") is not True:
                issues[f"{stage}_credential"] += 1
            binding_id = str(provenance.get("credential_binding_id") or "").strip()
            if binding_id.startswith("sha256:") and _SHA256_RE.fullmatch(binding_id[7:]):
                binding_ids.add(binding_id)
            else:
                issues[f"{stage}_credential_binding_id"] += 1
            requested_model = str(provenance.get("requested_model") or "").strip()
            observed_model = str(provenance.get("observed_model") or "").strip()
            observed_models[
                model if observed_model == model else "[rejected]"
            ] += 1
            if requested_model != model:
                issues[f"{stage}_requested_model"] += 1
            if observed_model != model:
                issues[f"{stage}_observed_model"] += 1
            response_id = str(provenance.get("response_id") or "").strip()
            if (
                _PUBLIC_IDENTIFIER_RE.fullmatch(response_id)
                and "response_id_shape" not in policy_issues
            ):
                response_ids.append(response_id)
            else:
                issues[f"{stage}_response_id"] += 1
            fingerprint = str(provenance.get("system_fingerprint") or "").strip()
            fingerprints[
                "accepted"
                if "system_fingerprint_shape" not in policy_issues
                else "[rejected]"
            ] += 1
            if _PUBLIC_IDENTIFIER_RE.fullmatch(fingerprint) is None:
                issues[f"{stage}_system_fingerprint"] += 1
            request_sha256 = str(provenance.get("request_sha256") or "").strip()
            if _SHA256_RE.fullmatch(request_sha256) is None:
                issues[f"{stage}_request_sha256"] += 1

    duplicate_response_id_count = len(response_ids) - len(set(response_ids))
    if duplicate_response_id_count:
        issues["duplicate_response_ids"] += duplicate_response_id_count
    if observed_call_count and len(binding_ids) != 1:
        issues["credential_binding_count"] += 1
    expected_call_count = len(evaluations) * 2
    if observed_call_count != expected_call_count:
        issues["call_count"] += abs(expected_call_count - observed_call_count)
    return {
        "schema_version": PROVIDER_PROVENANCE_CONTRACT_SCHEMA_VERSION,
        "route_policy_id": route_policy.policy_id,
        "route_policy": dict(route_policy.public_summary()),
        "matches": expected_call_count > 0 and not issues,
        "required_model": model,
        "expected_call_count": expected_call_count,
        "observed_call_count": observed_call_count,
        "credential_binding_count": len(binding_ids),
        "response_id_count": len(response_ids),
        "unique_response_id_count": len(set(response_ids)),
        "duplicate_response_id_count": duplicate_response_id_count,
        "trust_counts": dict(sorted(trust.items())),
        "observed_models": dict(sorted(observed_models.items())),
        "system_fingerprints": dict(sorted(fingerprints.items())),
        "issues": dict(sorted(issues.items())),
    }


def _public_identifier(value: str) -> tuple[str, str | None]:
    normalized = str(value or "").strip()
    if _looks_sensitive(normalized) or (
        normalized and _PUBLIC_IDENTIFIER_RE.fullmatch(normalized) is None
    ):
        return "[redacted]", hashlib.sha256(normalized.encode()).hexdigest()
    return normalized, None


def _parse_public_provenance(
    payload: Mapping[str, object],
) -> tuple[ProviderCallProvenance, bool]:
    string_fields = (
        "trust",
        "origin",
        "endpoint_path",
        "route_sha256",
        "transport_evidence",
        "credential_binding_id",
        "request_method",
        "requested_model",
        "observed_model",
        "response_id",
        "system_fingerprint",
        "request_sha256",
    )
    structurally_valid = set(payload) == _PUBLIC_PROVENANCE_KEYS and all(
        isinstance(payload.get(key), str) for key in string_fields
    )
    structurally_valid = (
        structurally_valid
        and isinstance(payload.get("credential_bound"), bool)
        and isinstance(payload.get("response_status"), int)
        and not isinstance(payload.get("response_status"), bool)
        and isinstance(payload.get("schema_version"), str)
    )
    credential_binding = (
        _strict_text(payload, "credential_binding_id")
        if payload.get("credential_bound") is True
        else None
    )
    route = ProviderRouteAttestation(
        trust=_strict_text(payload, "trust"),
        origin=_strict_text(payload, "origin"),
        endpoint_path=_strict_text(payload, "endpoint_path"),
        route_sha256=_strict_text(payload, "route_sha256"),
        transport_evidence=_strict_text(payload, "transport_evidence"),
        credential_binding_id=credential_binding,
        request_method=_strict_text(payload, "request_method"),
        response_status=_strict_int(payload, "response_status"),
    )
    return (
        ProviderCallProvenance(
            route=route,
            requested_model=_strict_text(payload, "requested_model"),
            observed_model=_strict_text(payload, "observed_model"),
            response_id=_strict_text(payload, "response_id"),
            system_fingerprint=_strict_text(payload, "system_fingerprint"),
            request_sha256=_strict_text(payload, "request_sha256"),
        ),
        structurally_valid,
    )


def _strict_text(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    return value.strip() if isinstance(value, str) else ""


def _strict_int(payload: Mapping[str, object], key: str) -> int:
    value = payload.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _looks_sensitive(value: str) -> bool:
    return bool(value and _SENSITIVE_RE.search(value))


def _safe_route_text(value: object) -> str:
    normalized = str(value or "").strip()
    return "[redacted]" if _looks_sensitive(normalized) else normalized


def _safe_binding(value: str | None) -> str:
    normalized = str(value or "").strip()
    if normalized.startswith("sha256:") and _SHA256_RE.fullmatch(normalized[7:]):
        return normalized
    return "[invalid]"


def _safe_sha256(value: object) -> str:
    normalized = str(value or "").strip()
    return normalized if _SHA256_RE.fullmatch(normalized) else "[invalid]"


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


__all__ = (
    "PROVIDER_CALL_PROVENANCE_SCHEMA_VERSION",
    "PROVIDER_PROVENANCE_CONTRACT_SCHEMA_VERSION",
    "ProviderCallProvenance",
    "ProviderChatCompletion",
    "ProviderChatCompletionsPort",
    "ProviderRouteAttestation",
    "ProviderRoutePolicy",
    "canonical_request_sha256",
    "provider_provenance_contract",
)

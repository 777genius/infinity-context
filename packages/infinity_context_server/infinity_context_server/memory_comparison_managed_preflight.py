"""Pure fail-closed preflight policy for production managed comparisons."""

from __future__ import annotations

import hashlib
import ipaddress
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import final
from urllib.parse import SplitResult, urlsplit, urlunsplit

from infinity_context_server.memory_comparison_backend_target import (
    FullComparisonBackendTarget,
)
from infinity_context_server.memory_comparison_case_loader import (
    cases_from_payload,
    parse_memory_comparison_dataset_bytes,
)
from infinity_context_server.memory_comparison_full_methodology import (
    FrozenFullComparisonMethodology,
    case_distribution,
    corpus_count,
    full_comparison_methodology_contract,
    public_full_comparison_methodology_contract,
)
from infinity_context_server.memory_comparison_full_profiles import (
    REQUIRED_FULL_COMPARISON_BACKENDS,
    FullComparisonProfile,
    frozen_full_comparison_profile,
    select_full_comparison_profile_cases,
)
from infinity_context_server.memory_comparison_full_scope import (
    FULL_COMPARISON_SCOPE_FULL,
    normalize_full_comparison_scope,
)
from infinity_context_server.memory_comparison_locomo_cases import (
    LOCOMO_INGEST_OFFICIAL_TURNS,
)
from infinity_context_server.memory_comparison_provider_provenance import (
    ProviderRouteAttestation,
)
from infinity_context_server.memory_comparison_target_identity import (
    mem0_runtime_target_identity_sha256,
)
from infinity_context_server.public_benchmark_models import BenchmarkValidationError

MANAGED_PREFLIGHT_SCHEMA_VERSION = "memory-comparison-managed-preflight.v1"
MANAGED_PREFLIGHT_REQUIRED_CREDENTIALS = (
    "openai",
    *REQUIRED_FULL_COMPARISON_BACKENDS,
)
MANAGED_PREFLIGHT_MAX_CONNECT_SECONDS = 30.0
MANAGED_PREFLIGHT_MAX_REQUEST_SECONDS = 300.0
MANAGED_PREFLIGHT_MAX_RUN_SECONDS = 172_800.0

_OFFICIAL_DIRECT_TRANSPORT = "httpx-direct-tls-no-env-v1"
_TARGET_IDENTITY_SCHEMA_VERSION = "memory-comparison-managed-target.v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CREDENTIAL_BINDING = re.compile(r"^sha256:[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_SENSITIVE_URL_TEXT = re.compile(
    r"(?:api[_-]?key|access[_-]?token|bearer|sk-(?:proj-|svcacct-)?)", re.IGNORECASE
)
_SAFE_HOST = re.compile(r"^[A-Za-z0-9.-]{1,253}$")
_SAFE_PATH = re.compile(r"^/[A-Za-z0-9._~!$&'()*+,;=:@/-]*$")

_ERROR_MESSAGES = MappingProxyType(
    {
        "request_invalid": "managed preflight request is invalid",
        "profile_invalid": "managed preflight profile is not frozen",
        "methodology_invalid": "managed preflight methodology is not frozen",
        "methodology_mismatch": "managed preflight methodology differs from profile",
        "dataset_metadata_invalid": "managed preflight dataset metadata is invalid",
        "dataset_mismatch": "managed preflight dataset differs from frozen profile",
        "scope_invalid": "managed preflight scope is invalid",
        "model_invalid": "managed preflight model is invalid",
        "model_mismatch": "managed preflight model differs from official methodology",
        "provider_route_invalid": "managed preflight provider route is invalid",
        "provider_route_mismatch": "managed preflight provider route is not official",
        "credential_invalid": "managed preflight credential binding is invalid",
        "credential_missing": "managed preflight required credential is missing",
        "credential_mismatch": "managed preflight credential binding differs from route",
        "endpoint_invalid": "managed preflight backend endpoint is invalid",
        "backend_targets_invalid": "managed preflight backend targets are invalid",
        "backend_targets_not_distinct": "managed preflight backend targets are not distinct",
        "timeouts_invalid": "managed preflight timeouts are invalid",
    }
)


class ManagedPreflightError(BenchmarkValidationError):
    """Machine-readable, secret-safe rejection from managed preflight."""

    def __init__(self, code: str) -> None:
        safe_code = code if code in _ERROR_MESSAGES else "request_invalid"
        self.code = safe_code
        super().__init__(_ERROR_MESSAGES[safe_code])


@final
@dataclass(frozen=True, slots=True)
class ManagedDatasetMetadata:
    """Exact metadata derived from the official dataset before preflight."""

    profile_id: str
    benchmark: str
    dataset_sha256: str
    case_count: int
    distribution: Mapping[str, int]
    corpus_count: int | None

    def __post_init__(self) -> None:
        if not _identifier(self.profile_id) or not _identifier(self.benchmark):
            _reject("dataset_metadata_invalid")
        if type(self.dataset_sha256) is not str or _SHA256.fullmatch(self.dataset_sha256) is None:
            _reject("dataset_metadata_invalid")
        if type(self.case_count) is not int or self.case_count <= 0:
            _reject("dataset_metadata_invalid")
        distribution = self.distribution
        if (
            type(distribution) not in {dict, MappingProxyType}
            or not distribution
            or any(
                not _identifier(key) or type(count) is not int or count <= 0
                for key, count in distribution.items()
            )
            or sum(distribution.values()) != self.case_count
        ):
            _reject("dataset_metadata_invalid")
        if self.corpus_count is not None and (
            type(self.corpus_count) is not int or self.corpus_count <= 0
        ):
            _reject("dataset_metadata_invalid")
        object.__setattr__(self, "distribution", MappingProxyType(dict(distribution)))

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedDatasetMetadata is final")


def managed_dataset_metadata_from_bytes(
    *,
    profile: FullComparisonProfile,
    dataset_bytes: bytes,
) -> ManagedDatasetMetadata:
    """Derive metadata from exact strict-parser bytes without filesystem access."""

    trusted = _trusted_profile(profile)
    if type(dataset_bytes) is not bytes:
        _reject("dataset_metadata_invalid")
    try:
        payload = parse_memory_comparison_dataset_bytes(dataset_bytes)
        locomo_mode = trusted.required_locomo_ingest_mode or LOCOMO_INGEST_OFFICIAL_TURNS
        cases = cases_from_payload(payload, locomo_ingest_mode=locomo_mode)
        selected = select_full_comparison_profile_cases(
            profile=trusted,
            cases=cases,
        )
    except (BenchmarkValidationError, TypeError, ValueError, KeyError):
        _reject("dataset_metadata_invalid")
    if not selected or len({case.case_id for case in selected}) != len(selected):
        _reject("dataset_metadata_invalid")
    return ManagedDatasetMetadata(
        profile_id=trusted.profile_id,
        benchmark=trusted.benchmark,
        dataset_sha256=hashlib.sha256(dataset_bytes).hexdigest(),
        case_count=len(selected),
        distribution=case_distribution(trusted, selected),
        corpus_count=corpus_count(trusted, selected),
    )


@final
@dataclass(frozen=True, slots=True)
class ManagedCredentialBinding:
    """Secret-free availability plus a one-way credential commitment."""

    credential_name: str
    configured: bool
    binding_id: str | None = field(repr=False)

    def __post_init__(self) -> None:
        if not _identifier(self.credential_name) or type(self.configured) is not bool:
            _reject("credential_invalid")
        if self.configured:
            if (
                type(self.binding_id) is not str
                or _CREDENTIAL_BINDING.fullmatch(self.binding_id) is None
            ):
                _reject("credential_invalid")
        elif self.binding_id is not None:
            _reject("credential_invalid")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedCredentialBinding is final")


def managed_backend_target_identity_sha256(
    *,
    backend_role: str,
    base_url: str,
) -> str:
    """Bind one exact backend role to its normalized endpoint without exposing it."""

    if not _identifier(backend_role):
        _reject("backend_targets_invalid")
    normalized, _ = _validated_backend_url(base_url)
    material = (f"{_TARGET_IDENTITY_SCHEMA_VERSION}\n{backend_role}\n{normalized}").encode()
    if backend_role == "mem0":
        return mem0_runtime_target_identity_sha256(normalized)
    return hashlib.sha256(material).hexdigest()


@final
@dataclass(frozen=True, slots=True)
class ManagedBackendEndpoint:
    """One sanitized backend endpoint bound to a committed target identity."""

    target: FullComparisonBackendTarget
    base_url: str
    credential: ManagedCredentialBinding
    loopback: bool = field(init=False)

    def __post_init__(self) -> None:
        if type(self.target) is not FullComparisonBackendTarget:
            _reject("endpoint_invalid")
        if type(self.credential) is not ManagedCredentialBinding:
            _reject("credential_invalid")
        normalized, loopback = _validated_backend_url(self.base_url)
        object.__setattr__(self, "base_url", normalized)
        object.__setattr__(self, "loopback", loopback)

        expected_identity = managed_backend_target_identity_sha256(
            backend_role=self.target.backend_role,
            base_url=normalized,
        )
        if self.target.target_identity_sha256 != expected_identity:
            _reject("backend_targets_invalid")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedBackendEndpoint is final")


@final
@dataclass(frozen=True, slots=True)
class ManagedPreflightTimeouts:
    """Bounded operation budgets; no transport implementation is implied."""

    connect_seconds: float
    request_seconds: float
    run_seconds: float

    def __post_init__(self) -> None:
        connect = _bounded_seconds(
            self.connect_seconds,
            maximum=MANAGED_PREFLIGHT_MAX_CONNECT_SECONDS,
        )
        request = _bounded_seconds(
            self.request_seconds,
            maximum=MANAGED_PREFLIGHT_MAX_REQUEST_SECONDS,
        )
        run = _bounded_seconds(
            self.run_seconds,
            maximum=MANAGED_PREFLIGHT_MAX_RUN_SECONDS,
        )
        if connect > request or request > run:
            _reject("timeouts_invalid")
        object.__setattr__(self, "connect_seconds", connect)
        object.__setattr__(self, "request_seconds", request)
        object.__setattr__(self, "run_seconds", run)

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedPreflightTimeouts is final")


@final
@dataclass(frozen=True, slots=True)
class ManagedPreflightRequest:
    """Provider-neutral composition input supplied by an outer composition root."""

    profile: FullComparisonProfile
    methodology: FrozenFullComparisonMethodology
    dataset: ManagedDatasetMetadata
    provider_route: ProviderRouteAttestation
    answerer_model: str
    judge_model: str
    openai_credential: ManagedCredentialBinding
    backend_endpoints: tuple[ManagedBackendEndpoint, ...]
    timeouts: ManagedPreflightTimeouts
    scope: str = FULL_COMPARISON_SCOPE_FULL

    def __post_init__(self) -> None:
        if (
            type(self.dataset) is not ManagedDatasetMetadata
            or type(self.openai_credential) is not ManagedCredentialBinding
            or type(self.backend_endpoints) is not tuple
            or any(type(item) is not ManagedBackendEndpoint for item in self.backend_endpoints)
            or type(self.timeouts) is not ManagedPreflightTimeouts
        ):
            _reject("request_invalid")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedPreflightRequest is final")


@final
@dataclass(frozen=True, slots=True)
class ManagedProviderRouteSummary:
    trust: str
    origin: str
    endpoint_path: str
    route_sha256: str
    transport_evidence: str
    credential_binding_id: str = field(repr=False)
    request_method: str = "POST"

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedProviderRouteSummary is final")


@final
@dataclass(frozen=True, slots=True)
class ManagedPreflightResult:
    """Immutable, sanitized report produced by the validated preflight policy."""

    schema_version: str
    ready: bool
    eligible: bool
    provider_calls_performed: bool
    live_state_touched: bool
    execution_authority_created: bool
    live_success: bool
    publishable: bool
    scope: str
    profile_id: str
    benchmark: str
    dataset_sha256: str
    dataset_case_count: int
    dataset_distribution: tuple[tuple[str, int], ...]
    dataset_corpus_count: int | None
    answerer_model: str
    judge_model: str
    provider_route: ManagedProviderRouteSummary
    credentials: tuple[ManagedCredentialBinding, ...]
    backend_endpoints: tuple[ManagedBackendEndpoint, ...]
    timeouts: ManagedPreflightTimeouts

    def __post_init__(self) -> None:
        try:
            normalized_scope = normalize_full_comparison_scope(self.scope)
        except BenchmarkValidationError:
            _reject("request_invalid")
        if (
            self.schema_version != MANAGED_PREFLIGHT_SCHEMA_VERSION
            or self.ready is not True
            or self.scope != normalized_scope
            or self.publishable is not False
            or self.eligible is not False
            or self.provider_calls_performed is not False
            or self.live_state_touched is not False
            or self.execution_authority_created is not False
            or self.live_success is not False
        ):
            _reject("request_invalid")

    def public_payload(self) -> dict[str, object]:
        """Return a fresh JSON-safe projection containing no credential values."""

        return {
            "schema_version": self.schema_version,
            "static_checks_passed": self.ready,
            "eligible": self.eligible,
            "credentials_verified": False,
            "provider_calls_performed": self.provider_calls_performed,
            "live_state_touched": self.live_state_touched,
            "execution_authority_created": self.execution_authority_created,
            "live_success": self.live_success,
            "publishable": self.publishable,
            "scope": self.scope,
            "profile_id": self.profile_id,
            "benchmark": self.benchmark,
            "dataset": {
                "sha256": self.dataset_sha256,
                "case_count": self.dataset_case_count,
                "distribution": dict(self.dataset_distribution),
                "corpus_count": self.dataset_corpus_count,
            },
            "provider": {
                "answerer_model": self.answerer_model,
                "judge_model": self.judge_model,
                "route": {
                    "trust": self.provider_route.trust,
                    "origin": self.provider_route.origin,
                    "endpoint_path": self.provider_route.endpoint_path,
                    "route_sha256": self.provider_route.route_sha256,
                    "transport_evidence": self.provider_route.transport_evidence,
                    "credential_bound": True,
                    "request_method": self.provider_route.request_method,
                },
            },
            "credentials": [
                {
                    "credential_name": item.credential_name,
                    "configured": item.configured,
                }
                for item in self.credentials
            ],
            "backends": [
                {
                    "backend_role": item.target.backend_role,
                    "target_identity_sha256": item.target.target_identity_sha256,
                    "endpoint_scheme": urlsplit(item.base_url).scheme,
                    "endpoint_sha256": hashlib.sha256(item.base_url.encode()).hexdigest(),
                    "loopback": item.loopback,
                    "credential_configured": item.credential.configured,
                }
                for item in self.backend_endpoints
            ],
            "timeouts": {
                "connect_seconds": self.timeouts.connect_seconds,
                "request_seconds": self.timeouts.request_seconds,
                "run_seconds": self.timeouts.run_seconds,
            },
        }

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedPreflightResult is final")


def validate_managed_preflight(request: ManagedPreflightRequest) -> ManagedPreflightResult:
    """Validate configuration only; perform no environment reads or I/O."""

    if type(request) is not ManagedPreflightRequest:
        _reject("request_invalid")
    profile = _trusted_profile(request.profile)
    methodology = _trusted_methodology(request.methodology)
    _validate_methodology(profile, methodology)
    _validate_dataset(profile, request.dataset)
    scope = _trusted_scope(request.scope)
    answerer_model = _model(request.answerer_model)
    judge_model = _model(request.judge_model)
    if answerer_model != methodology.get("answerer_model") or judge_model != methodology.get(
        "judge_model"
    ):
        _reject("model_mismatch")
    route = _trusted_provider_route(
        request.provider_route,
        methodology=methodology,
        openai_credential=request.openai_credential,
    )
    endpoints = _trusted_backend_endpoints(request.backend_endpoints)
    credentials = (request.openai_credential, *(item.credential for item in endpoints))
    if (
        tuple(item.credential_name for item in credentials)
        != MANAGED_PREFLIGHT_REQUIRED_CREDENTIALS
    ):
        _reject("credential_mismatch")
    if any(not item.configured or item.binding_id is None for item in credentials):
        _reject("credential_missing")
    return ManagedPreflightResult(
        schema_version=MANAGED_PREFLIGHT_SCHEMA_VERSION,
        ready=True,
        publishable=False,
        eligible=False,
        provider_calls_performed=False,
        live_state_touched=False,
        execution_authority_created=False,
        live_success=False,
        scope=scope,
        profile_id=profile.profile_id,
        benchmark=profile.benchmark,
        dataset_sha256=request.dataset.dataset_sha256,
        dataset_case_count=request.dataset.case_count,
        dataset_distribution=tuple(profile.expected_distribution.items()),
        dataset_corpus_count=request.dataset.corpus_count,
        answerer_model=answerer_model,
        judge_model=judge_model,
        provider_route=route,
        credentials=credentials,
        backend_endpoints=endpoints,
        timeouts=request.timeouts,
    )


def _trusted_profile(profile: object) -> FullComparisonProfile:
    try:
        return frozen_full_comparison_profile(profile)  # type: ignore[arg-type]
    except (BenchmarkValidationError, TypeError, ValueError):
        _reject("profile_invalid")


def _trusted_methodology(methodology: object) -> dict[str, object]:
    try:
        return public_full_comparison_methodology_contract(methodology)  # type: ignore[arg-type]
    except (BenchmarkValidationError, TypeError, ValueError):
        _reject("methodology_invalid")


def _validate_methodology(
    profile: FullComparisonProfile,
    methodology: dict[str, object],
) -> None:
    expected = public_full_comparison_methodology_contract(
        full_comparison_methodology_contract(profile)
    )
    if methodology != expected:
        _reject("methodology_mismatch")


def _validate_dataset(profile: FullComparisonProfile, dataset: ManagedDatasetMetadata) -> None:
    if type(dataset) is not ManagedDatasetMetadata:
        _reject("dataset_metadata_invalid")
    if (
        dataset.profile_id != profile.profile_id
        or dataset.benchmark != profile.benchmark
        or dataset.dataset_sha256 != profile.expected_dataset_hash
        or dataset.case_count != profile.expected_case_count
        or dict(dataset.distribution) != dict(profile.expected_distribution)
        or dataset.corpus_count != profile.expected_corpus_count
    ):
        _reject("dataset_mismatch")


def _trusted_scope(scope: object) -> str:
    if type(scope) is not str:
        _reject("scope_invalid")
    try:
        return normalize_full_comparison_scope(scope)  # type: ignore[arg-type]
    except BenchmarkValidationError:
        _reject("scope_invalid")


def _model(value: object) -> str:
    if type(value) is not str or not value or value != value.strip() or not _identifier(value):
        _reject("model_invalid")
    return value


def _trusted_provider_route(
    route: object,
    *,
    methodology: dict[str, object],
    openai_credential: ManagedCredentialBinding,
) -> ManagedProviderRouteSummary:
    if type(route) is not ProviderRouteAttestation:
        _reject("provider_route_invalid")
    official = methodology.get("official_provider_route")
    if type(official) is not dict:
        _reject("methodology_invalid")
    origin = official.get("origin")
    endpoint_path = official.get("endpoint_path")
    trust = official.get("trust")
    if not all(type(item) is str and item for item in (origin, endpoint_path, trust)):
        _reject("methodology_invalid")
    expected_route_sha256 = hashlib.sha256(f"{origin}{endpoint_path}".encode()).hexdigest()
    if (
        route.trust != trust
        or route.origin != origin
        or route.endpoint_path != endpoint_path
        or route.route_sha256 != expected_route_sha256
        or route.transport_evidence != _OFFICIAL_DIRECT_TRANSPORT
        or route.request_method != "POST"
        or type(route.response_status) is not int
        or route.response_status != 0
        or type(route.credential_binding_id) is not str
        or _CREDENTIAL_BINDING.fullmatch(route.credential_binding_id) is None
    ):
        _reject("provider_route_mismatch")
    if (
        type(openai_credential) is not ManagedCredentialBinding
        or openai_credential.credential_name != "openai"
    ):
        _reject("credential_mismatch")
    if not openai_credential.configured or openai_credential.binding_id is None:
        _reject("credential_missing")
    if openai_credential.binding_id != route.credential_binding_id:
        _reject("credential_mismatch")
    public = route.public_payload()
    if (
        public.get("credential_bound") is not True
        or public.get("credential_binding_id") != route.credential_binding_id
        or public.get("route_sha256") != route.route_sha256
    ):
        _reject("provider_route_invalid")
    return ManagedProviderRouteSummary(
        trust=route.trust,
        origin=route.origin,
        endpoint_path=route.endpoint_path,
        route_sha256=route.route_sha256,
        transport_evidence=route.transport_evidence,
        credential_binding_id=route.credential_binding_id,
        request_method=route.request_method,
    )


def _trusted_backend_endpoints(
    endpoints: object,
) -> tuple[ManagedBackendEndpoint, ...]:
    if (
        type(endpoints) is not tuple
        or len(endpoints) != len(REQUIRED_FULL_COMPARISON_BACKENDS)
        or any(type(item) is not ManagedBackendEndpoint for item in endpoints)
    ):
        _reject("backend_targets_invalid")
    roles = tuple(item.target.backend_role for item in endpoints)
    if roles != REQUIRED_FULL_COMPARISON_BACKENDS:
        _reject("backend_targets_invalid")
    identities = tuple(item.target.target_identity_sha256 for item in endpoints)
    if len(set(identities)) != len(identities):
        _reject("backend_targets_not_distinct")
    endpoint_commitments = tuple(
        hashlib.sha256(item.base_url.encode()).hexdigest() for item in endpoints
    )
    if len(set(endpoint_commitments)) != len(endpoint_commitments):
        _reject("backend_targets_not_distinct")
    for item in endpoints:
        normalized, loopback = _validated_backend_url(item.base_url)
        expected_identity = managed_backend_target_identity_sha256(
            backend_role=item.target.backend_role,
            base_url=normalized,
        )
        if (
            item.base_url != normalized
            or item.loopback is not loopback
            or item.target.target_identity_sha256 != expected_identity
        ):
            _reject("backend_targets_invalid")
        if item.credential.credential_name != item.target.backend_role:
            _reject("credential_mismatch")
        if not item.credential.configured or item.credential.binding_id is None:
            _reject("credential_missing")
    return endpoints


def _validated_backend_url(value: object) -> tuple[str, bool]:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > 2048
        or _SENSITIVE_URL_TEXT.search(value)
    ):
        _reject("endpoint_invalid")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        _reject("endpoint_invalid")
    hostname = parsed.hostname
    if (
        hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.scheme.casefold() not in {"http", "https"}
        or (parsed.path and _SAFE_PATH.fullmatch(parsed.path) is None)
    ):
        _reject("endpoint_invalid")
    scheme = parsed.scheme.casefold()
    normalized_host = hostname.casefold().removesuffix(".")
    loopback = _is_loopback(normalized_host)
    if scheme != "https" and not loopback:
        _reject("endpoint_invalid")
    if not loopback and _SAFE_HOST.fullmatch(normalized_host) is None:
        _reject("endpoint_invalid")
    if (scheme == "https" and port == 443) or (scheme == "http" and port == 80):
        port = None
    if ":" in normalized_host:
        normalized_host = f"[{normalized_host}]"
    netloc = f"{normalized_host}:{port}" if port is not None else normalized_host
    path = parsed.path.rstrip("/")
    return urlunsplit(SplitResult(scheme, netloc, path, "", "")), loopback


def _is_loopback(hostname: str) -> bool:
    if hostname.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _bounded_seconds(value: object, *, maximum: float) -> float:
    if type(value) not in {int, float} or not math.isfinite(value) or value <= 0 or value > maximum:
        _reject("timeouts_invalid")
    return float(value)


def _identifier(value: object) -> bool:
    return type(value) is str and _IDENTIFIER.fullmatch(value) is not None


def _reject(code: str) -> None:
    raise ManagedPreflightError(code)


__all__ = (
    "MANAGED_PREFLIGHT_MAX_CONNECT_SECONDS",
    "MANAGED_PREFLIGHT_MAX_REQUEST_SECONDS",
    "MANAGED_PREFLIGHT_MAX_RUN_SECONDS",
    "MANAGED_PREFLIGHT_REQUIRED_CREDENTIALS",
    "MANAGED_PREFLIGHT_SCHEMA_VERSION",
    "ManagedBackendEndpoint",
    "ManagedCredentialBinding",
    "ManagedDatasetMetadata",
    "ManagedPreflightError",
    "ManagedPreflightRequest",
    "ManagedPreflightResult",
    "ManagedPreflightTimeouts",
    "ManagedProviderRouteSummary",
    "managed_backend_target_identity_sha256",
    "managed_dataset_metadata_from_bytes",
    "validate_managed_preflight",
)

from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest
from infinity_context_server.memory_comparison_full_methodology import (
    full_comparison_methodology_contract,
)
from infinity_context_server.memory_comparison_full_profiles import (
    PROFILE_LOCOMO_TOP_50,
    PROFILE_LOCOMO_TOP_200,
    PROFILE_LONGMEMEVAL_TOP_50,
    PROFILE_LONGMEMEVAL_TOP_200,
    resolve_full_comparison_profile,
)
from infinity_context_server.memory_comparison_full_run_evidence import (
    FullComparisonBackendTarget,
)
from infinity_context_server.memory_comparison_managed_preflight import (
    MANAGED_PREFLIGHT_MAX_CONNECT_SECONDS,
    MANAGED_PREFLIGHT_MAX_REQUEST_SECONDS,
    MANAGED_PREFLIGHT_MAX_RUN_SECONDS,
    MANAGED_PREFLIGHT_SCHEMA_VERSION,
    ManagedBackendEndpoint,
    ManagedCredentialBinding,
    ManagedDatasetMetadata,
    ManagedPreflightError,
    ManagedPreflightRequest,
    ManagedPreflightTimeouts,
    managed_backend_target_identity_sha256,
    managed_dataset_metadata_from_bytes,
    validate_managed_preflight,
)
from infinity_context_server.memory_comparison_probe_transport import (
    mem0_runtime_target_identity_sha256,
)
from infinity_context_server.memory_comparison_provider_provenance import (
    ProviderRouteAttestation,
)

_ORIGIN = "https://api.openai.com"
_PATH = "/v1/chat/completions"
_ROUTE_SHA256 = hashlib.sha256(f"{_ORIGIN}{_PATH}".encode()).hexdigest()


def _binding(name: str, marker: str) -> ManagedCredentialBinding:
    return ManagedCredentialBinding(
        credential_name=name,
        configured=True,
        binding_id=f"sha256:{marker * 64}",
    )


def _target(backend_role: str, base_url: str) -> FullComparisonBackendTarget:
    return FullComparisonBackendTarget(
        backend_role=backend_role,
        target_identity_sha256=managed_backend_target_identity_sha256(
            backend_role=backend_role,
            base_url=base_url,
        ),
    )


def _route(
    *,
    binding: ManagedCredentialBinding | None = None,
) -> ProviderRouteAttestation:
    credential = binding or _binding("openai", "a")
    return ProviderRouteAttestation(
        trust="official_openai",
        origin=_ORIGIN,
        endpoint_path=_PATH,
        route_sha256=_ROUTE_SHA256,
        transport_evidence="httpx-direct-tls-no-env-v1",
        credential_binding_id=credential.binding_id,
        request_method="POST",
        response_status=0,
    )


def _request(
    *,
    scope: str = "full",
    infinity_url: str = "https://infinity.example.test/api",
    mem0_url: str = "http://127.0.0.1:8765",
) -> ManagedPreflightRequest:
    profile = resolve_full_comparison_profile(PROFILE_LOCOMO_TOP_50)
    assert profile is not None
    openai = _binding("openai", "a")
    infinity = _binding("infinity-context", "b")
    mem0 = _binding("mem0", "c")
    return ManagedPreflightRequest(
        profile=profile,
        methodology=full_comparison_methodology_contract(profile),
        dataset=ManagedDatasetMetadata(
            profile_id=profile.profile_id,
            benchmark=profile.benchmark,
            dataset_sha256=profile.expected_dataset_hash,
            case_count=profile.expected_case_count,
            distribution=dict(profile.expected_distribution),
            corpus_count=profile.expected_corpus_count,
        ),
        provider_route=_route(binding=openai),
        answerer_model="gpt-5",
        judge_model="gpt-5",
        openai_credential=openai,
        backend_endpoints=(
            ManagedBackendEndpoint(
                target=_target("infinity-context", infinity_url),
                base_url=infinity_url,
                credential=infinity,
            ),
            ManagedBackendEndpoint(
                target=_target("mem0", mem0_url),
                base_url=mem0_url,
                credential=mem0,
            ),
        ),
        timeouts=ManagedPreflightTimeouts(
            connect_seconds=10,
            request_seconds=120,
            run_seconds=86_400,
        ),
        scope=scope,
    )


def _assert_code(code: str, callback: object) -> None:
    assert callable(callback)
    with pytest.raises(ManagedPreflightError) as caught:
        callback()
    assert caught.value.code == code
    assert code not in str(caught.value)


def test_full_preflight_returns_deeply_immutable_sanitized_result() -> None:
    result = validate_managed_preflight(_request())

    assert result.ready is True
    assert result.publishable is False
    assert result.eligible is False
    assert result.provider_calls_performed is False
    assert result.live_state_touched is False
    assert result.execution_authority_created is False
    assert result.live_success is False
    assert result.scope == "full"
    assert result.schema_version == MANAGED_PREFLIGHT_SCHEMA_VERSION
    assert result.dataset_case_count == 1540
    assert tuple(item.target.backend_role for item in result.backend_endpoints) == (
        "infinity-context",
        "mem0",
    )
    assert result.backend_endpoints[0].loopback is False
    assert result.backend_endpoints[1].loopback is True
    assert result.timeouts.connect_seconds == 10.0
    with pytest.raises(FrozenInstanceError):
        result.publishable = False  # type: ignore[misc]
    with pytest.raises(TypeError):
        _request().dataset.distribution["multi-hop"] = 0  # type: ignore[index]

    first = result.public_payload()
    first["dataset"]["case_count"] = 0  # type: ignore[index]
    assert result.public_payload()["dataset"]["case_count"] == 1540  # type: ignore[index]

    backend = result.public_payload()["backends"][0]  # type: ignore[index]
    assert "base_url" not in backend
    assert backend["endpoint_scheme"] == "https"
    assert len(backend["endpoint_sha256"]) == 64
    serialized = json.dumps(result.public_payload(), sort_keys=True)
    assert "credential_binding_id" not in serialized
    assert "binding_id" not in serialized
    assert result.public_payload()["credentials_verified"] is False


def test_mem0_target_identity_matches_live_runtime_attestation_factory() -> None:
    url = "HTTPS://Mem0.Example.Test:443/v3/"
    assert managed_backend_target_identity_sha256(
        backend_role="mem0", base_url=url
    ) == mem0_runtime_target_identity_sha256(url)


def test_canary_is_ready_but_never_publishable() -> None:
    result = validate_managed_preflight(_request(scope=" CANARY "))

    assert result.ready is True
    assert result.scope == "canary"
    assert result.publishable is False
    assert result.public_payload()["publishable"] is False
    _assert_code(
        "request_invalid",
        lambda: replace(result, publishable=True),
    )


@pytest.mark.parametrize(
    "profile_id",
    (
        PROFILE_LOCOMO_TOP_50,
        PROFILE_LOCOMO_TOP_200,
        PROFILE_LONGMEMEVAL_TOP_50,
        PROFILE_LONGMEMEVAL_TOP_200,
    ),
)
def test_every_frozen_profile_is_supported(profile_id: str) -> None:
    profile = resolve_full_comparison_profile(profile_id)
    assert profile is not None
    request = replace(
        _request(),
        profile=profile,
        methodology=full_comparison_methodology_contract(profile),
        dataset=ManagedDatasetMetadata(
            profile_id=profile.profile_id,
            benchmark=profile.benchmark,
            dataset_sha256=profile.expected_dataset_hash,
            case_count=profile.expected_case_count,
            distribution=dict(profile.expected_distribution),
            corpus_count=profile.expected_corpus_count,
        ),
    )

    result = validate_managed_preflight(request)

    assert result.profile_id == profile_id
    assert result.benchmark == profile.benchmark
    assert result.dataset_case_count == profile.expected_case_count
    assert result.dataset_corpus_count == profile.expected_corpus_count


def test_dataset_metadata_is_derived_from_strict_bytes_and_wrong_bytes_fail_preflight() -> None:
    profile = resolve_full_comparison_profile(PROFILE_LOCOMO_TOP_50)
    assert profile is not None
    dataset_bytes = (
        Path(__file__).parents[1] / "fixtures/memory_comparison/managed-locomo-sandbox.json"
    ).read_bytes()
    metadata = managed_dataset_metadata_from_bytes(
        profile=profile,
        dataset_bytes=dataset_bytes,
    )

    assert metadata.profile_id == profile.profile_id
    assert metadata.benchmark == "locomo"
    assert metadata.dataset_sha256 == hashlib.sha256(dataset_bytes).hexdigest()
    assert metadata.case_count == 1
    assert dict(metadata.distribution) == {"single-hop": 1}
    assert metadata.corpus_count == 1

    request = _request()
    _assert_code(
        "dataset_mismatch",
        lambda: validate_managed_preflight(replace(request, dataset=metadata)),
    )


@pytest.mark.parametrize(
    "dataset_bytes",
    (
        b'{"sample_id":"x","sample_id":"y"}',
        b'{"value":NaN}',
        b"",
    ),
)
def test_dataset_metadata_derivation_rejects_ambiguous_or_invalid_bytes(
    dataset_bytes: bytes,
) -> None:
    profile = resolve_full_comparison_profile(PROFILE_LOCOMO_TOP_50)
    assert profile is not None
    _assert_code(
        "dataset_metadata_invalid",
        lambda: managed_dataset_metadata_from_bytes(
            profile=profile,
            dataset_bytes=dataset_bytes,
        ),
    )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("profile_id", "wrong-profile"),
        ("benchmark", "longmemeval"),
        ("dataset_sha256", "f" * 64),
        ("corpus_count", 11),
    ),
)
def test_dataset_metadata_must_match_frozen_profile(field: str, value: object) -> None:
    request = _request()
    dataset = replace(request.dataset, **{field: value})

    _assert_code(
        "dataset_mismatch",
        lambda: validate_managed_preflight(replace(request, dataset=dataset)),
    )


def test_dataset_count_and_distribution_must_both_match() -> None:
    request = _request()
    distribution = dict(request.dataset.distribution)
    distribution["multi-hop"] += 1
    dataset = replace(
        request.dataset,
        case_count=request.dataset.case_count + 1,
        distribution=distribution,
    )
    _assert_code(
        "dataset_mismatch",
        lambda: validate_managed_preflight(replace(request, dataset=dataset)),
    )

    distribution = dict(request.dataset.distribution)
    distribution["multi-hop"] -= 1
    distribution["temporal"] += 1
    dataset = replace(request.dataset, distribution=distribution)
    _assert_code(
        "dataset_mismatch",
        lambda: validate_managed_preflight(replace(request, dataset=dataset)),
    )


@pytest.mark.parametrize(
    "changes",
    (
        {"case_count": 0},
        {"case_count": True},
        {"dataset_sha256": "not-a-digest"},
        {"distribution": {}},
        {"distribution": {"bad": 1540.0}},
        {"corpus_count": 0},
    ),
)
def test_dataset_metadata_rejects_invalid_shape(changes: dict[str, object]) -> None:
    request = _request()
    _assert_code(
        "dataset_metadata_invalid",
        lambda: replace(request.dataset, **changes),
    )


def test_profile_and_methodology_are_revalidated_from_frozen_primitives() -> None:
    request = _request()
    object.__setattr__(request.profile, "expected_case_count", 1)
    _assert_code("profile_invalid", lambda: validate_managed_preflight(request))

    request = _request()
    object.__setattr__(request.methodology, "_commitment_sha256", "0" * 64)
    _assert_code("methodology_invalid", lambda: validate_managed_preflight(request))

    request = _request()
    other = resolve_full_comparison_profile(PROFILE_LONGMEMEVAL_TOP_50)
    assert other is not None
    _assert_code(
        "methodology_mismatch",
        lambda: validate_managed_preflight(
            replace(request, methodology=full_comparison_methodology_contract(other))
        ),
    )


def test_same_benchmark_cross_profile_methodology_is_rejected() -> None:
    request = _request()
    other = resolve_full_comparison_profile(PROFILE_LOCOMO_TOP_200)
    assert other is not None
    _assert_code(
        "methodology_mismatch",
        lambda: validate_managed_preflight(
            replace(request, methodology=full_comparison_methodology_contract(other))
        ),
    )


@pytest.mark.parametrize(
    ("field", "value", "code"),
    (
        ("answerer_model", "gpt-4.1", "model_mismatch"),
        ("judge_model", "gpt-4.1", "model_mismatch"),
        ("answerer_model", " gpt-5", "model_invalid"),
        ("judge_model", "", "model_invalid"),
    ),
)
def test_only_official_models_are_admitted(field: str, value: str, code: str) -> None:
    request = _request()
    _assert_code(code, lambda: validate_managed_preflight(replace(request, **{field: value})))


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("trust", "diagnostic_untrusted"),
        ("origin", "https://proxy.example.test"),
        ("endpoint_path", "/v1/responses"),
        ("route_sha256", "0" * 64),
        ("transport_evidence", "injected-diagnostic-transport"),
        ("request_method", "GET"),
        ("response_status", 200),
        ("response_status", True),
        ("credential_binding_id", "invalid"),
    ),
)
def test_only_planned_official_openai_route_is_admitted(field: str, value: object) -> None:
    request = _request()
    route = replace(request.provider_route, **{field: value})

    _assert_code(
        "provider_route_mismatch",
        lambda: validate_managed_preflight(replace(request, provider_route=route)),
    )


def test_openai_binding_must_be_present_and_match_route() -> None:
    request = _request()
    missing = ManagedCredentialBinding("openai", False, None)
    _assert_code(
        "credential_missing",
        lambda: validate_managed_preflight(replace(request, openai_credential=missing)),
    )

    mismatched = _binding("openai", "d")
    _assert_code(
        "credential_mismatch",
        lambda: validate_managed_preflight(replace(request, openai_credential=mismatched)),
    )


@pytest.mark.parametrize("index", (0, 1))
def test_both_backend_credentials_are_required_even_for_loopback(index: int) -> None:
    request = _request(scope="canary")
    endpoints = list(request.backend_endpoints)
    endpoint = endpoints[index]
    endpoints[index] = replace(
        endpoint,
        credential=ManagedCredentialBinding(endpoint.target.backend_role, False, None),
    )
    _assert_code(
        "credential_missing",
        lambda: validate_managed_preflight(replace(request, backend_endpoints=tuple(endpoints))),
    )


def test_credential_names_and_route_binding_are_exact() -> None:
    request = _request()
    endpoints = list(request.backend_endpoints)
    endpoints[0] = replace(endpoints[0], credential=_binding("mem0", "b"))
    _assert_code(
        "credential_mismatch",
        lambda: validate_managed_preflight(replace(request, backend_endpoints=tuple(endpoints))),
    )
    wrong_name = _binding("benchmark-openai", "a")
    _assert_code(
        "credential_mismatch",
        lambda: validate_managed_preflight(replace(request, openai_credential=wrong_name)),
    )


def test_raw_secret_is_never_retained_or_echoed() -> None:
    raw_secret = "sk-proj-super-secret-value-that-must-never-leak"
    with pytest.raises(ManagedPreflightError) as caught:
        ManagedCredentialBinding("openai", True, raw_secret)
    assert raw_secret not in str(caught.value)
    assert raw_secret not in repr(caught.value)

    request = _request()
    unsafe_route = replace(request.provider_route, credential_binding_id=raw_secret)
    with pytest.raises(ManagedPreflightError) as caught:
        validate_managed_preflight(replace(request, provider_route=unsafe_route))
    assert raw_secret not in str(caught.value)
    assert raw_secret not in repr(caught.value)
    assert raw_secret not in json.dumps(validate_managed_preflight(request).public_payload())


@pytest.mark.parametrize(
    "url",
    (
        "http://backend.example.test",
        "ftp://backend.example.test",
        "https://user:password@backend.example.test",
        "https://backend.example.test?token=secret",
        "https://backend.example.test/#fragment",
        "https://backend.example.test:invalid",
        "https://backend.example.test/%2Fsecret",
        " backend.example.test ",
        "https://backend.example.test/sk-proj-super-secret",
    ),
)
def test_backend_endpoint_rejects_unsafe_or_non_tls_remote_url(url: str) -> None:
    _assert_code(
        "endpoint_invalid",
        lambda: ManagedBackendEndpoint(
            _target("mem0", url),
            url,
            _binding("mem0", "c"),
        ),
    )


@pytest.mark.parametrize(
    ("url", "normalized"),
    (
        ("http://localhost:8080/", "http://localhost:8080"),
        ("http://127.9.8.7:8080", "http://127.9.8.7:8080"),
        ("http://[::1]:8080/", "http://[::1]:8080"),
        ("HTTPS://Backend.Example.Test/api/", "https://backend.example.test/api"),
    ),
)
def test_https_and_exact_loopback_endpoints_are_sanitized(
    url: str,
    normalized: str,
) -> None:
    target = _target("mem0", url)
    endpoint = ManagedBackendEndpoint(target, url, _binding("mem0", "c"))
    assert endpoint.base_url == normalized


def test_backend_target_identity_must_bind_role_and_normalized_url() -> None:
    target = FullComparisonBackendTarget("mem0", "0" * 64)
    _assert_code(
        "backend_targets_invalid",
        lambda: ManagedBackendEndpoint(
            target,
            "https://mem0.example.test",
            _binding("mem0", "c"),
        ),
    )


def test_backend_roles_order_and_target_identities_are_exact_and_distinct() -> None:
    request = _request()
    _assert_code(
        "backend_targets_invalid",
        lambda: validate_managed_preflight(
            replace(request, backend_endpoints=tuple(reversed(request.backend_endpoints)))
        ),
    )
    object.__setattr__(
        request.backend_endpoints[1].target,
        "target_identity_sha256",
        request.backend_endpoints[0].target.target_identity_sha256,
    )
    _assert_code(
        "backend_targets_not_distinct",
        lambda: validate_managed_preflight(
            replace(
                request,
                backend_endpoints=request.backend_endpoints,
            )
        ),
    )


@pytest.mark.parametrize(
    ("infinity_url", "mem0_url"),
    (
        ("https://shared.example.test/api", "https://shared.example.test/api"),
        ("https://shared.example.test/api", "https://shared.example.test:443/api"),
        ("https://shared.example.test/api", "https://shared.example.test./api"),
    ),
)
def test_backend_endpoints_must_not_use_the_same_normalized_url(
    infinity_url: str,
    mem0_url: str,
) -> None:
    _assert_code(
        "backend_targets_not_distinct",
        lambda: validate_managed_preflight(_request(infinity_url=infinity_url, mem0_url=mem0_url)),
    )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("connect_seconds", 0),
        ("connect_seconds", True),
        ("connect_seconds", float("nan")),
        ("connect_seconds", MANAGED_PREFLIGHT_MAX_CONNECT_SECONDS + 0.1),
        ("request_seconds", float("inf")),
        ("request_seconds", MANAGED_PREFLIGHT_MAX_REQUEST_SECONDS + 0.1),
        ("run_seconds", MANAGED_PREFLIGHT_MAX_RUN_SECONDS + 0.1),
    ),
)
def test_timeouts_must_be_positive_finite_and_bounded(field: str, value: object) -> None:
    request = _request()
    _assert_code("timeouts_invalid", lambda: replace(request.timeouts, **{field: value}))


@pytest.mark.parametrize(
    "values",
    (
        {"connect_seconds": 20, "request_seconds": 10, "run_seconds": 100},
        {"connect_seconds": 10, "request_seconds": 100, "run_seconds": 50},
    ),
)
def test_timeout_hierarchy_is_fail_closed(values: dict[str, object]) -> None:
    _assert_code("timeouts_invalid", lambda: ManagedPreflightTimeouts(**values))


def test_scope_and_request_types_are_exact() -> None:
    request = _request()
    _assert_code(
        "scope_invalid",
        lambda: validate_managed_preflight(replace(request, scope="sample")),
    )
    _assert_code(
        "scope_invalid",
        lambda: validate_managed_preflight(replace(request, scope=None)),  # type: ignore[arg-type]
    )
    _assert_code("request_invalid", lambda: validate_managed_preflight(object()))  # type: ignore[arg-type]

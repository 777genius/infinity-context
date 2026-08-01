from __future__ import annotations

import copy
import hashlib
import hmac
import json
import pickle
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from infinity_context_server import memory_comparison_managed_live_admission as live
from infinity_context_server.memory_comparison_full_methodology import (
    full_comparison_methodology_contract,
)
from infinity_context_server.memory_comparison_full_profiles import (
    PROFILE_LOCOMO_TOP_50,
    resolve_full_comparison_profile,
)
from infinity_context_server.memory_comparison_full_run_evidence import (
    FullComparisonBackendTarget,
)
from infinity_context_server.memory_comparison_managed_preflight import (
    ManagedBackendEndpoint,
    ManagedCredentialBinding,
    ManagedDatasetMetadata,
    ManagedPreflightRequest,
    ManagedPreflightTimeouts,
    managed_backend_target_identity_sha256,
)
from infinity_context_server.memory_comparison_mem0_contract import (
    MEM0_BENCHMARK_CAPABILITIES_SCHEMA_VERSION_V2,
)
from infinity_context_server.memory_comparison_mem0_runtime_attestation import (
    VerifiedMem0RuntimeAttestationValidation,
    build_verified_mem0_runtime_attestation,
    validate_mem0_runtime_attestation_for_backends,
)
from infinity_context_server.memory_comparison_provider_provenance import (
    ProviderRouteAttestation,
)
from infinity_context_server.memory_comparison_subscription_chat import (
    SubscriptionRuntimeChatCompletions,
)
from infinity_context_server.memory_comparison_subscription_live_probe import (
    SUBSCRIPTION_LIVE_PROBE_EXPECTED_RESPONSE,
    run_subscription_runtime_live_probe,
)

_RUN_ID = "managed-live-admission-run"
_PROBE_NONCE = "probe-" + ("p" * 40)
_INFINITY_URL = "https://infinity.example.test/api"
_MEM0_URL = "https://mem0.example.test"
_ORIGIN = "https://api.openai.com"
_PATH = "/v1/chat/completions"
_ROUTE_SHA256 = hashlib.sha256(f"{_ORIGIN}{_PATH}".encode()).hexdigest()
_SUBSCRIPTION_ORIGIN = "http://127.0.0.1:8890"
_SUBSCRIPTION_BEARER = "managed-live-test-token"
_SUBSCRIPTION_BINDING = "sha256:" + hashlib.sha256(_SUBSCRIPTION_BEARER.encode()).hexdigest()
_SUBSCRIPTION_ROUTE_SHA256 = hashlib.sha256(
    f"{_SUBSCRIPTION_ORIGIN}{live.SUBSCRIPTION_BRIDGE_ENDPOINT_PATH}".encode()
).hexdigest()


class _RuntimeBackend:
    def __init__(self, name: str, target: str | None = None) -> None:
        self.name = name
        if target is not None:
            self.runtime_target_identity_sha256 = target


def _binding(name: str, marker: str) -> ManagedCredentialBinding:
    return ManagedCredentialBinding(
        credential_name=name,
        configured=True,
        binding_id=f"sha256:{marker * 64}",
    )


def _subscription_probe(now: datetime) -> live.VerifiedSubscriptionRuntimeProbe:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": SUBSCRIPTION_LIVE_PROBE_EXPECTED_RESPONSE,
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 98, "completion_tokens": 2},
            },
        )

    adapter = SubscriptionRuntimeChatCompletions(
        bearer_token=_SUBSCRIPTION_BEARER,
        transport=httpx.MockTransport(handler),
        max_retries=0,
    )
    return run_subscription_runtime_live_probe(
        adapter,
        expected_route=adapter.route_attestation,
        model="gpt-5.6-sol",
        clock=lambda: now,
    )


def _target(role: str, url: str) -> FullComparisonBackendTarget:
    return FullComparisonBackendTarget(
        backend_role=role,
        target_identity_sha256=managed_backend_target_identity_sha256(
            backend_role=role,
            base_url=url,
        ),
    )


def _static_route(binding: ManagedCredentialBinding) -> ProviderRouteAttestation:
    return ProviderRouteAttestation(
        trust="official_openai",
        origin=_ORIGIN,
        endpoint_path=_PATH,
        route_sha256=_ROUTE_SHA256,
        transport_evidence="httpx-direct-tls-no-env-v1",
        credential_binding_id=binding.binding_id,
        request_method="POST",
        response_status=0,
    )


def _live_route(
    binding: ManagedCredentialBinding,
    *,
    status: int = 204,
) -> ProviderRouteAttestation:
    return replace(_static_route(binding), response_status=status)


def _request(
    *,
    scope: str = "canary",
    provider_kind: str = live.MANAGED_PROVIDER_SUBSCRIPTION_RUNTIME,
) -> ManagedPreflightRequest:
    profile = resolve_full_comparison_profile(PROFILE_LOCOMO_TOP_50)
    assert profile is not None
    if provider_kind == live.MANAGED_PROVIDER_SUBSCRIPTION_RUNTIME:
        provider = ManagedCredentialBinding(
            credential_name="subscription-runtime",
            configured=True,
            binding_id=_SUBSCRIPTION_BINDING,
        )
        provider_route = ProviderRouteAttestation(
            trust=live.SUBSCRIPTION_RUNTIME_TRUST,
            origin=_SUBSCRIPTION_ORIGIN,
            endpoint_path=live.SUBSCRIPTION_BRIDGE_ENDPOINT_PATH,
            route_sha256=_SUBSCRIPTION_ROUTE_SHA256,
            transport_evidence=live.SUBSCRIPTION_BRIDGE_TRANSPORT,
            credential_binding_id=_SUBSCRIPTION_BINDING,
            request_method="POST",
            response_status=0,
        )
        answerer_model = judge_model = "gpt-5.6-sol"
    else:
        provider = _binding("openai", "a")
        provider_route = _static_route(provider)
        answerer_model = judge_model = "gpt-5"
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
        provider_route=provider_route,
        answerer_model=answerer_model,
        judge_model=judge_model,
        openai_credential=provider,
        backend_endpoints=(
            ManagedBackendEndpoint(
                target=_target("infinity-context", _INFINITY_URL),
                base_url=_INFINITY_URL,
                credential=infinity,
            ),
            ManagedBackendEndpoint(
                target=_target("mem0", _MEM0_URL),
                base_url=_MEM0_URL,
                credential=mem0,
            ),
        ),
        timeouts=ManagedPreflightTimeouts(10, 120, 86_400),
        scope=scope,
        provider_kind=provider_kind,
    )


def _runtime_manifest(
    now: datetime,
    *,
    run_id: str,
    probe_nonce: str,
    target: str,
) -> dict[str, object]:
    instant = now.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return {
        "schema_version": MEM0_BENCHMARK_CAPABILITIES_SCHEMA_VERSION_V2,
        "runtime_mode": "managed_platform",
        "wrapper_source_sha256": "a" * 64,
        "wrapper_source_revision": "b" * 40,
        "config_fingerprint_sha256": "c" * 64,
        "sdk": {
            "distribution": "mem0ai",
            "version": "2.0.14",
            "source_revision": "b357a5a1b03c299ec8229c268e63cfac0f7c6566",
            "artifact_sha256": ("9c567df69af794278bc051400829d1a2d4f8aa659cae6cd019d88ec66dbf4f3f"),
            "verification": {
                "method": "direct_url_archive_info_sha256",
                "observed_sha256": (
                    "9c567df69af794278bc051400829d1a2d4f8aa659cae6cd019d88ec66dbf4f3f"
                ),
                "passed": True,
            },
        },
        "platform": {
            "api_origin": "https://api.mem0.ai",
            "api_generation": "v3",
            "add_path": "/v3/memories/add/",
            "search_path": "/v3/memories/search/",
            "event_path_template": "/v1/event/{event_id}/",
            "server_source_revision": None,
            "server_revision_attestable": False,
        },
        "timestamp": {
            "request_supported": True,
            "sdk_forwarding_supported": True,
            "event_completion_supported": True,
            "readback_supported": True,
            "attestation": {
                "status": "passed",
                "checked_at": instant,
                "probe_mode": "live_sentinel",
                "input_epoch_seconds": 1_672_531_200,
                "expected_created_at": "2023-01-01T00:00:00Z",
                "event_terminal_status": "SUCCEEDED",
                "readback_result_count": 1,
                "persisted_created_at": "2023-01-01T00:00:00Z",
                "delta_seconds": 0.0,
                "cleanup_succeeded": True,
                "failure_code": None,
            },
        },
        "refresh_binding": {
            "status": "passed",
            "run_id_sha256": hashlib.sha256(run_id.encode()).hexdigest(),
            "probe_nonce_sha256": hashlib.sha256(probe_nonce.encode()).hexdigest(),
            "target_identity_sha256": target,
            "refreshed_at": instant,
        },
    }


def _runtime_validation(
    request: ManagedPreflightRequest,
    now: datetime,
    *,
    run_id: str = _RUN_ID,
    probe_nonce: str = _PROBE_NONCE,
) -> VerifiedMem0RuntimeAttestationValidation:
    target = next(
        item.target.target_identity_sha256
        for item in request.backend_endpoints
        if item.target.backend_role == "mem0"
    )
    manifest = _runtime_manifest(
        now,
        run_id=run_id,
        probe_nonce=probe_nonce,
        target=target,
    )
    fingerprint = hashlib.sha256(
        json.dumps(
            manifest,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()
    binding = manifest["refresh_binding"]
    assert isinstance(binding, dict)
    message = "\n".join(
        (
            "mem0-benchmark-runtime-witness.v1",
            str(binding["run_id_sha256"]),
            str(binding["probe_nonce_sha256"]),
            str(binding["target_identity_sha256"]),
            str(binding["refreshed_at"]),
            fingerprint,
        )
    ).encode()
    token = "managed-live-runtime-probe-token"
    manifest["refresh_witness"] = {
        "algorithm": "hmac-sha256",
        "manifest_fingerprint_sha256": fingerprint,
        "signature": hmac.new(token.encode(), message, hashlib.sha256).hexdigest(),
    }
    verified = build_verified_mem0_runtime_attestation(
        runtime_manifest=manifest,
        benchmark_probe_token=token,
        openapi_fingerprint_sha256="d" * 64,
        openapi_contract_violations=(),
        probe_passed=True,
        run_id=run_id,
        probe_nonce=probe_nonce,
        target_identity_sha256=target,
    )
    assert verified is not None
    result = validate_mem0_runtime_attestation_for_backends(
        verified,
        (
            _RuntimeBackend("infinity-context"),
            _RuntimeBackend("mem0", target),
        ),
        run_id,
        probe_nonce,
        validated_at=now,
    )
    assert type(result) is VerifiedMem0RuntimeAttestationValidation
    return result


def _issue(
    *,
    request: ManagedPreflightRequest | None = None,
    now: datetime | None = None,
    validation: object | None = None,
    route: object | None = None,
    case_ids: tuple[str, ...] | None = None,
    allow_live: object = True,
    allow_paid_llm: object = True,
    allow_full_run: object | None = None,
    probe_credential: ManagedCredentialBinding | None = None,
    budget: live.ManagedLiveBudget | None = None,
    deadline_delta: timedelta = timedelta(minutes=1),
):
    current_request = request or _request()
    current_now = now or datetime.now(UTC)
    selected = (
        ()
        if current_request.scope == "full"
        else (case_ids if case_ids is not None else ("case-z", "case-a"))
    )
    current_budget = budget or live.ManagedLiveBudget(
        max_cases=(
            current_request.dataset.case_count
            if current_request.scope == "full"
            else max(1, len(selected))
        ),
        max_provider_calls=(
            current_request.dataset.case_count * 4
            if current_request.scope == "full"
            else max(1, len(selected)) * 4
        ),
        max_total_tokens=1_000_000,
    )
    return live.issue_verified_managed_live_admission(
        request=current_request,
        allow_live=allow_live,
        allow_paid_llm=allow_paid_llm,
        allow_full_run=(
            current_request.scope == "full" if allow_full_run is None else allow_full_run
        ),
        run_id=_RUN_ID,
        run_nonce_commitment_sha256="e" * 64,
        runtime_probe_nonce=_PROBE_NONCE,
        canary_case_ids=selected,
        mem0_probe_credential=probe_credential or _binding("mem0-probe", "f"),
        provider_kind=current_request.provider_kind,
        live_provider_evidence=(
            route
            if route is not None
            else (
                _subscription_probe(current_now)
                if current_request.provider_kind == live.MANAGED_PROVIDER_SUBSCRIPTION_RUNTIME
                else _live_route(current_request.openai_credential)
            )
        ),
        runtime_validation=(
            validation
            if validation is not None
            else _runtime_validation(current_request, current_now)
        ),
        budget=current_budget,
        issued_at=current_now,
        deadline=current_now + deadline_delta,
        now=current_now,
    )


def test_subscription_admission_binds_exact_material_and_consumes_once() -> None:
    request = _request()
    now = datetime.now(UTC)
    admission = _issue(request=request, now=now)

    assert repr(admission) == "VerifiedManagedLiveAdmission(<sealed-one-shot>)"
    material = live._consume_verified_managed_live_admission(
        admission,
        expected_request=request,
        now=now + timedelta(seconds=1),
    )

    assert material.request is request
    assert material.run_id == _RUN_ID
    assert material.run_nonce_commitment_sha256 == "e" * 64
    assert material.runtime_probe_nonce == _PROBE_NONCE
    assert material.runtime_probe_nonce_sha256 == hashlib.sha256(_PROBE_NONCE.encode()).hexdigest()
    assert material.canary_case_ids == ("case-z", "case-a")
    assert material.budget.max_cases == 2
    assert material.provider_usage_budget.readiness_probe_provider_calls == 1
    assert (
        material.provider_usage_budget.total_provider_attempt_ceiling
        == material.budget.max_provider_calls + 1
    )
    assert _PROBE_NONCE not in repr(material)
    with pytest.raises(live.ManagedLiveAdmissionError, match="consumed"):
        live._consume_verified_managed_live_admission(
            admission,
            expected_request=request,
            now=now + timedelta(seconds=1),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("allow_live", False),
        ("allow_live", 1),
        ("allow_paid_llm", False),
        ("allow_paid_llm", 1),
    ),
)
def test_explicit_flags_fail_before_preflight_callback(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    def _unexpected(_: object) -> object:
        raise AssertionError("preflight must not run before operator flags")

    monkeypatch.setattr(live, "validate_managed_preflight", _unexpected)
    with pytest.raises(live.ManagedLiveAdmissionError):
        _issue(**{field: value})


def test_official_live_route_is_rejected_without_opaque_call_evidence() -> None:
    request = _request(
        scope="canary",
        provider_kind=live.MANAGED_PROVIDER_OPENAI_API_KEY,
    )
    now = datetime.now(UTC)
    validation = _runtime_validation(request, now)

    for route in (
        _live_route(request.openai_credential, status=401),
        replace(
            _live_route(request.openai_credential),
            trust="diagnostic_untrusted",
        ),
        replace(
            _live_route(request.openai_credential),
            credential_binding_id="sha256:" + ("9" * 64),
        ),
    ):
        with pytest.raises(live.ManagedLiveAdmissionError, match="provider"):
            _issue(request=request, now=now, validation=validation, route=route)


def test_subscription_probe_and_runtime_evidence_each_mint_only_one_admission() -> None:
    request = _request()
    now = datetime.now(UTC)
    provider_evidence = _subscription_probe(now)
    runtime_validation = _runtime_validation(request, now)
    _issue(
        request=request,
        now=now,
        route=provider_evidence,
        validation=runtime_validation,
    )

    with pytest.raises(live.ManagedLiveAdmissionError, match="already reserved"):
        _issue(
            request=request,
            now=now,
            route=provider_evidence,
            validation=_runtime_validation(request, now),
        )

    unused_provider_evidence = _subscription_probe(now)
    with pytest.raises(live.ManagedLiveAdmissionError, match="runtime validation"):
        _issue(
            request=request,
            now=now,
            route=unused_provider_evidence,
            validation=runtime_validation,
        )

    # A failed runtime reservation cannot partially burn fresh provider evidence.
    admission = _issue(
        request=request,
        now=now,
        route=unused_provider_evidence,
        validation=_runtime_validation(request, now),
    )
    assert type(admission) is live.VerifiedManagedLiveAdmission


def test_live_evidence_reservation_is_atomic_under_concurrency() -> None:
    request = _request()
    now = datetime.now(UTC)
    provider_evidence = _subscription_probe(now)
    runtime_validation = _runtime_validation(request, now)

    def attempt() -> object:
        try:
            return _issue(
                request=request,
                now=now,
                route=provider_evidence,
                validation=runtime_validation,
            )
        except live.ManagedLiveAdmissionError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(lambda _: attempt(), range(2)))

    assert sum(type(item) is live.VerifiedManagedLiveAdmission for item in outcomes) == 1
    failures = tuple(item for item in outcomes if type(item) is live.ManagedLiveAdmissionError)
    assert len(failures) == 1
    assert "already reserved" in str(failures[0])


def test_provider_kind_rejects_unhashable_values_fail_closed() -> None:
    with pytest.raises(live.ManagedLiveAdmissionError, match="provider kind"):
        live._provider_kind([], scope="canary")


def test_runtime_validation_type_run_nonce_target_and_freshness_are_exact() -> None:
    request = _request()
    now = datetime.now(UTC)
    with pytest.raises(live.ManagedLiveAdmissionError, match="type"):
        _issue(request=request, now=now, validation={})

    wrong_run = _runtime_validation(request, now, run_id="different-run")
    with pytest.raises(live.ManagedLiveAdmissionError, match="binding differs"):
        _issue(request=request, now=now, validation=wrong_run)

    wrong_nonce = _runtime_validation(request, now, probe_nonce="x" * 40)
    with pytest.raises(live.ManagedLiveAdmissionError, match="binding differs"):
        _issue(request=request, now=now, validation=wrong_nonce)

    admission = _issue(
        request=request,
        now=now,
        deadline_delta=timedelta(seconds=180),
    )
    with pytest.raises(live.ManagedLiveAdmissionError, match="stale"):
        live._consume_verified_managed_live_admission(
            admission,
            expected_request=request,
            now=now + timedelta(seconds=121),
        )


def test_canary_cap_duplicates_and_order_are_fail_closed() -> None:
    request = _request(scope="canary")
    now = datetime.now(UTC)
    ordered = ("case-z", "case-a")
    admission = _issue(
        request=request,
        now=now,
        case_ids=ordered,
        allow_full_run=False,
    )
    material = live._consume_verified_managed_live_admission(
        admission,
        expected_request=request,
        now=now,
    )
    assert material.canary_case_ids == ordered

    for invalid in (
        tuple(f"case-{index}" for index in range(9)),
        ("same", "same"),
        (),
        ["case-a"],
    ):
        with pytest.raises(live.ManagedLiveAdmissionError, match="case IDs"):
            _issue(
                request=request,
                now=now,
                case_ids=invalid,  # type: ignore[arg-type]
                allow_full_run=False,
            )


def test_scope_and_budget_require_explicit_bounded_authority() -> None:
    full = _request(
        scope="full",
        provider_kind=live.MANAGED_PROVIDER_OPENAI_API_KEY,
    )
    with pytest.raises(live.ManagedLiveAdmissionError, match="explicit"):
        _issue(request=full, allow_full_run=False)

    canary = _request(scope="canary")
    with pytest.raises(live.ManagedLiveAdmissionError, match="full-run"):
        _issue(request=canary, allow_full_run=True)

    with pytest.raises(live.ManagedLiveAdmissionError, match="budget differs"):
        _issue(
            request=canary,
            allow_full_run=False,
            budget=live.ManagedLiveBudget(3, 8, 1000),
        )


def test_probe_credential_is_separate_and_all_commitments_are_bound() -> None:
    request = _request()
    with pytest.raises(live.ManagedLiveAdmissionError, match="separately"):
        _issue(
            request=request,
            probe_credential=ManagedCredentialBinding(
                credential_name="mem0-probe",
                configured=True,
                binding_id=request.backend_endpoints[1].credential.binding_id,
            ),
        )
    with pytest.raises(live.ManagedLiveAdmissionError, match="probe credential"):
        _issue(request=request, probe_credential=_binding("mem0", "f"))


def test_expiry_request_identity_replay_and_tamper_fail() -> None:
    request = _request()
    now = datetime.now(UTC)
    admission = _issue(
        request=request,
        now=now,
        deadline_delta=timedelta(seconds=2),
    )
    with pytest.raises(live.ManagedLiveAdmissionError, match="expired"):
        live._consume_verified_managed_live_admission(
            admission,
            expected_request=request,
            now=now + timedelta(seconds=3),
        )
    with pytest.raises(live.ManagedLiveAdmissionError, match="unavailable"):
        live._consume_verified_managed_live_admission(
            admission,
            expected_request=request,
            now=now + timedelta(seconds=1),
        )

    identity_admission = _issue(request=request, now=now)
    with pytest.raises(live.ManagedLiveAdmissionError, match="identity differs"):
        live._consume_verified_managed_live_admission(
            identity_admission,
            expected_request=_request(),
            now=now + timedelta(seconds=1),
        )

    tampered = _issue(request=request, now=now)
    object.__setattr__(
        tampered,
        "_VerifiedManagedLiveAdmission__commitment",
        "0" * 64,
    )
    with pytest.raises(live.ManagedLiveAdmissionError, match="integrity"):
        live._consume_verified_managed_live_admission(
            tampered,
            expected_request=request,
            now=now,
        )


def test_admission_is_final_noncopyable_and_nonserializable() -> None:
    admission = _issue()

    with pytest.raises(TypeError):
        copy.copy(admission)
    with pytest.raises(TypeError):
        copy.deepcopy(admission)
    with pytest.raises(TypeError):
        pickle.dumps(admission)
    with pytest.raises(TypeError):

        class _Subclass(live.VerifiedManagedLiveAdmission):
            pass


def test_subscription_canary_probe_is_accounted_and_authorizes_benchmark_budget() -> None:
    request = _request(
        scope="canary",
        provider_kind=live.MANAGED_PROVIDER_SUBSCRIPTION_RUNTIME,
    )
    now = datetime.now(UTC)
    probe = _subscription_probe(now)
    case_ids = ("future-case-2", "future-case-1")
    admission = live.issue_verified_managed_live_admission(
        request=request,
        allow_live=True,
        allow_paid_llm=True,
        allow_full_run=False,
        run_id=_RUN_ID,
        run_nonce_commitment_sha256="e" * 64,
        runtime_probe_nonce=_PROBE_NONCE,
        canary_case_ids=case_ids,
        mem0_probe_credential=_binding("mem0-probe", "f"),
        provider_kind=live.MANAGED_PROVIDER_SUBSCRIPTION_RUNTIME,
        live_provider_evidence=probe,
        runtime_validation=_runtime_validation(request, now),
        budget=live.ManagedLiveBudget(2, 8, 2_000_000),
        issued_at=now,
        deadline=now + timedelta(hours=2),
        now=now,
    )
    material = live._consume_verified_managed_live_admission(
        admission,
        expected_request=request,
        now=now + timedelta(seconds=1),
    )
    assert material.canary_case_ids == case_ids
    assert material.budget.max_provider_calls == 8
    assert material.provider_usage_budget.public_payload() == {
        "benchmark_max_provider_calls": 8,
        "readiness_probe_provider_calls": 1,
        "total_provider_attempt_ceiling": 9,
        "benchmark_max_total_tokens": 2_000_000,
        "readiness_probe_observed_tokens": 100,
        "total_token_ceiling": 2_000_100,
    }

    with pytest.raises(live.ManagedLiveAdmissionError, match="already reserved"):
        live.issue_verified_managed_live_admission(
            request=request,
            allow_live=True,
            allow_paid_llm=True,
            allow_full_run=False,
            run_id=_RUN_ID,
            run_nonce_commitment_sha256="e" * 64,
            runtime_probe_nonce=_PROBE_NONCE,
            canary_case_ids=case_ids,
            mem0_probe_credential=_binding("mem0-probe", "f"),
            provider_kind=live.MANAGED_PROVIDER_SUBSCRIPTION_RUNTIME,
            live_provider_evidence=probe,
            runtime_validation=_runtime_validation(request, now),
            budget=live.ManagedLiveBudget(2, 8, 2_000_000),
            issued_at=now,
            deadline=now + timedelta(hours=2),
            now=now,
        )

    with pytest.raises(live.ManagedLiveAdmissionError, match="budget"):
        live.issue_verified_managed_live_admission(
            request=request,
            allow_live=True,
            allow_paid_llm=True,
            allow_full_run=False,
            run_id=_RUN_ID,
            run_nonce_commitment_sha256="e" * 64,
            runtime_probe_nonce=_PROBE_NONCE,
            canary_case_ids=case_ids,
            mem0_probe_credential=_binding("mem0-probe", "f"),
            provider_kind=live.MANAGED_PROVIDER_SUBSCRIPTION_RUNTIME,
            live_provider_evidence=_subscription_probe(now),
            runtime_validation=_runtime_validation(request, now),
            budget=live.ManagedLiveBudget(2, 8, 2_000_001),
            issued_at=now,
            deadline=now + timedelta(hours=2),
            now=now,
        )

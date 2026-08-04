from __future__ import annotations

import copy
import hashlib
import inspect
import pickle
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import infinity_context_server.memory_comparison_managed_mem0_runtime_http as mem0_runtime_http
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
from infinity_context_server.memory_comparison_managed_mem0_runtime_authority import (
    ManagedMem0RuntimeAuthorityDescriptor,
    _register_pending_managed_mem0_runtime_authority,
)
from infinity_context_server.memory_comparison_managed_mem0_runtime_http import (
    ManagedMem0RuntimeAttestationPort,
    ManagedMem0RuntimeHttpError,
)
from infinity_context_server.memory_comparison_managed_preflight import (
    ManagedBackendEndpoint,
    ManagedCredentialBinding,
    ManagedDatasetMetadata,
    ManagedPreflightRequest,
    ManagedPreflightTimeouts,
    managed_backend_target_identity_sha256,
)
from infinity_context_server.memory_comparison_provider_provenance import (
    ProviderRouteAttestation,
)
from infinity_context_server.memory_comparison_subscription_chat import (
    SUBSCRIPTION_RUNTIME_ESTIMATED_USAGE_SOURCE,
    SubscriptionRuntimeChatCompletions,
)
from infinity_context_server.memory_comparison_subscription_live_probe import (
    SUBSCRIPTION_LIVE_PROBE_EXPECTED_RESPONSE,
    run_subscription_runtime_live_probe,
)
from test_memory_comparison_service_probes import _Transport

_RUN_ID = "managed-live-admission-run"
_PROBE_NONCE = "probe-" + ("p" * 40)
_MEM0_PROBE_TOKEN = "managed-live-runtime-probe-token"
_MEM0_PROBE_BINDING = "sha256:" + hashlib.sha256(_MEM0_PROBE_TOKEN.encode()).hexdigest()
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
_MEM0_RUNTIME_IMPLEMENTATION_SHA256 = hashlib.sha256(
    Path(mem0_runtime_http.__file__).read_bytes()
).hexdigest()


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
                "id": "chatcmpl-managed-live-probe-1",
                "model": "gpt-5.6-sol",
                "object": "chat.completion",
                "system_fingerprint": "subscription-runtime-codex-bridge-v1",
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
                "usage": {
                    "prompt_tokens": 98,
                    "completion_tokens": 2,
                    "total_tokens": 100,
                    "usage_source": SUBSCRIPTION_RUNTIME_ESTIMATED_USAGE_SOURCE,
                },
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


def _runtime_port(
    *,
    base_url: str = _MEM0_URL,
    probe_token: str = _MEM0_PROBE_TOKEN,
    probe_nonce: str = _PROBE_NONCE,
    timeout_seconds: float = 0.5,
    deadline_budget_seconds: float = 60.0,
    expected_runtime_mode: str = "managed_platform",
) -> ManagedMem0RuntimeAttestationPort:
    host = base_url.removeprefix("https://").split(":", 1)[0]
    return ManagedMem0RuntimeAttestationPort(
        base_url=base_url,
        benchmark_probe_token=probe_token,
        probe_nonce=probe_nonce,
        timeout_seconds=timeout_seconds,
        deadline_budget_seconds=deadline_budget_seconds,
        monotonic_clock=lambda: 100.0,
        expected_implementation_sha256=_MEM0_RUNTIME_IMPLEMENTATION_SHA256,
        allowed_target_hosts=(host,),
        vetted_transport=_Transport([], {}),
        expected_runtime_mode=expected_runtime_mode,
    )


def _issue(
    *,
    request: ManagedPreflightRequest | None = None,
    now: datetime | None = None,
    runtime_port: object | None = None,
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
        canary_case_ids=selected,
        mem0_probe_credential=probe_credential
        or ManagedCredentialBinding(
            credential_name="mem0-probe",
            configured=True,
            binding_id=_MEM0_PROBE_BINDING,
        ),
        mem0_runtime_port=(
            runtime_port
            if runtime_port is not None
            else _runtime_port(deadline_budget_seconds=deadline_delta.total_seconds())
        ),
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
        budget=current_budget,
        issued_at=current_now,
        deadline=current_now + deadline_delta,
        now=current_now,
    )


class _RegisteredRuntimeTestDouble:
    def __init__(self, descriptor: ManagedMem0RuntimeAuthorityDescriptor) -> None:
        self.descriptor = descriptor

    def authority_descriptor(self) -> ManagedMem0RuntimeAuthorityDescriptor:
        return self.descriptor

    def attest(
        self,
        *,
        run_id: str,
        probe_nonce_sha256: str,
        target_identity_sha256: str,
    ) -> object:
        raise AssertionError("admission must not attest")


def test_admission_accepts_registered_non_http_contract_implementation() -> None:
    request = _request()
    now = datetime.now(UTC)
    descriptor = replace(_runtime_port().authority_descriptor())
    port = _RegisteredRuntimeTestDouble(descriptor)
    _register_pending_managed_mem0_runtime_authority(port, descriptor)

    admission = _issue(request=request, now=now, runtime_port=port)
    material = live._consume_verified_managed_live_admission(
        admission,
        expected_request=request,
        now=now + timedelta(seconds=1),
    )

    assert material.mem0_runtime_port is port
    assert material.mem0_runtime_descriptor is descriptor


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
    assert (
        material.mem0_runtime_descriptor.probe_nonce_sha256
        == hashlib.sha256(_PROBE_NONCE.encode()).hexdigest()
    )
    assert type(material.mem0_runtime_descriptor) is ManagedMem0RuntimeAuthorityDescriptor
    assert material.mem0_runtime_port.authority_descriptor() is (material.mem0_runtime_descriptor)
    assert material.canary_case_ids == ("case-z", "case-a")
    assert material.budget.max_cases == 2
    assert material.provider_usage_budget.readiness_probe_provider_calls == 1
    assert (
        material.provider_usage_budget.total_provider_attempt_ceiling
        == material.budget.max_provider_calls + 1
    )
    assert _PROBE_NONCE not in repr(material)
    assert _MEM0_PROBE_TOKEN not in repr(material)
    with pytest.raises(live.ManagedLiveAdmissionError, match="consumed"):
        live._consume_verified_managed_live_admission(
            admission,
            expected_request=request,
            now=now + timedelta(seconds=1),
        )


def test_admission_api_has_no_plaintext_nonce_or_prior_runtime_validation() -> None:
    parameters = inspect.signature(live.issue_verified_managed_live_admission).parameters

    assert "runtime_probe_nonce" not in parameters
    assert "runtime_validation" not in parameters
    assert "mem0_runtime_port" in parameters


def test_consumed_mem0_runtime_authority_is_rejected_without_probe_io() -> None:
    request = _request()
    now = datetime.now(UTC)
    port = _runtime_port()
    descriptor = port.authority_descriptor()

    with pytest.raises(ManagedMem0RuntimeHttpError):
        port.attest(
            run_id=_RUN_ID,
            probe_nonce_sha256="0" * 64,
            target_identity_sha256=descriptor.target_identity_sha256,
        )

    with pytest.raises(live.ManagedLiveAdmissionError, match="unavailable"):
        _issue(request=request, now=now, runtime_port=port)


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
            _issue(request=request, now=now, route=route)


def test_subscription_probe_and_runtime_authority_each_mint_only_one_admission() -> None:
    request = _request()
    now = datetime.now(UTC)
    provider_evidence = _subscription_probe(now)
    runtime_port = _runtime_port()
    _issue(
        request=request,
        now=now,
        route=provider_evidence,
        runtime_port=runtime_port,
    )

    with pytest.raises(live.ManagedLiveAdmissionError, match="already reserved"):
        _issue(
            request=request,
            now=now,
            route=provider_evidence,
            runtime_port=_runtime_port(),
        )

    unused_provider_evidence = _subscription_probe(now)
    with pytest.raises(live.ManagedLiveAdmissionError, match="runtime authority"):
        _issue(
            request=request,
            now=now,
            route=unused_provider_evidence,
            runtime_port=runtime_port,
        )

    # A failed runtime reservation cannot partially burn fresh provider evidence.
    admission = _issue(
        request=request,
        now=now,
        route=unused_provider_evidence,
        runtime_port=_runtime_port(),
    )
    assert type(admission) is live.VerifiedManagedLiveAdmission


def test_live_evidence_reservation_is_atomic_under_concurrency() -> None:
    request = _request()
    now = datetime.now(UTC)
    provider_evidence = _subscription_probe(now)
    runtime_port = _runtime_port()

    def attempt() -> object:
        try:
            return _issue(
                request=request,
                now=now,
                route=provider_evidence,
                runtime_port=runtime_port,
            )
        except live.ManagedLiveAdmissionError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(lambda _: attempt(), range(2)))

    assert sum(type(item) is live.VerifiedManagedLiveAdmission for item in outcomes) == 1
    failures = tuple(item for item in outcomes if type(item) is live.ManagedLiveAdmissionError)
    assert len(failures) == 1
    assert "already reserved" in str(failures[0])


def test_admission_consume_is_atomic_under_concurrency() -> None:
    request = _request()
    now = datetime.now(UTC)
    admission = _issue(request=request, now=now)

    def attempt() -> object:
        try:
            return live._consume_verified_managed_live_admission(
                admission,
                expected_request=request,
                now=now + timedelta(seconds=1),
            )
        except live.ManagedLiveAdmissionError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(lambda _: attempt(), range(2)))

    failures = tuple(item for item in outcomes if type(item) is live.ManagedLiveAdmissionError)
    successes = tuple(item for item in outcomes if type(item) is not live.ManagedLiveAdmissionError)
    assert len(successes) == 1
    assert successes[0].mem0_runtime_port.authority_descriptor() is (
        successes[0].mem0_runtime_descriptor
    )
    assert len(failures) == 1
    assert "unavailable or consumed" in str(failures[0])


def test_provider_kind_rejects_unhashable_values_fail_closed() -> None:
    with pytest.raises(live.ManagedLiveAdmissionError, match="provider kind"):
        live._provider_kind([], scope="canary")


def test_runtime_authority_type_target_nonce_implementation_and_budget_are_exact() -> None:
    request = _request()
    now = datetime.now(UTC)
    with pytest.raises(live.ManagedLiveAdmissionError, match="not registered"):
        _issue(request=request, now=now, runtime_port={})

    wrong_runtime_mode = _runtime_port(expected_runtime_mode="oss")
    with pytest.raises(live.ManagedLiveAdmissionError, match="binding differs"):
        _issue(request=request, now=now, runtime_port=wrong_runtime_mode)

    wrong_target = _runtime_port(base_url="https://other-mem0.example.test")
    with pytest.raises(live.ManagedLiveAdmissionError, match="binding differs"):
        _issue(request=request, now=now, runtime_port=wrong_target)

    wrong_token = _runtime_port(probe_token="different-probe-token")
    with pytest.raises(live.ManagedLiveAdmissionError, match="binding differs"):
        _issue(request=request, now=now, runtime_port=wrong_token)

    for field, value in (
        ("implementation_sha256", "0" * 64),
        ("probe_nonce_sha256", "not-a-digest"),
        ("max_attempts", 2),
    ):
        port = _runtime_port()
        object.__setattr__(port.authority_descriptor(), field, value)
        with pytest.raises(live.ManagedLiveAdmissionError, match="descriptor changed"):
            _issue(request=request, now=now, runtime_port=port)

    with pytest.raises(live.ManagedLiveAdmissionError, match="deadline"):
        _issue(
            request=request,
            now=now,
            runtime_port=_runtime_port(
                timeout_seconds=0.5,
                deadline_budget_seconds=1.0,
            ),
            deadline_delta=timedelta(milliseconds=100),
        )

    near_deadline = _issue(
        request=request,
        now=now,
        runtime_port=_runtime_port(
            timeout_seconds=0.5,
            deadline_budget_seconds=2.0,
        ),
        deadline_delta=timedelta(seconds=2),
    )
    material = live._consume_verified_managed_live_admission(
        near_deadline,
        expected_request=request,
        now=now + timedelta(milliseconds=1_600),
    )
    assert material.mem0_runtime_descriptor.deadline_budget_seconds == 2.0


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
    with pytest.raises(live.ManagedLiveAdmissionError, match="binding differs"):
        _issue(request=request, probe_credential=_binding("mem0-probe", "f"))


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
    runtime_port = _runtime_port()
    admission = _issue(
        request=request,
        now=now,
        route=probe,
        runtime_port=runtime_port,
        case_ids=case_ids,
        budget=live.ManagedLiveBudget(2, 8, 2_000_000),
        deadline_delta=timedelta(hours=2),
    )
    material = live._consume_verified_managed_live_admission(
        admission,
        expected_request=request,
        now=now + timedelta(seconds=1),
    )
    assert material.canary_case_ids == case_ids
    assert material.budget.max_provider_calls == 8
    assert material.provider_usage_budget.public_payload() == {
        "provider_kind": live.MANAGED_PROVIDER_SUBSCRIPTION_RUNTIME,
        "benchmark_max_provider_calls": 8,
        "benchmark_provider_call_scope": "answer_judge_only",
        "readiness_probe_provider_calls": 1,
        "total_provider_attempt_ceiling": 9,
        "total_provider_attempt_ceiling_scope": "answer_judge_and_readiness_only",
        "backend_internal_provider_calls": "unmeasured",
        "backend_internal_provider_cost": "unmeasured",
        "total_provider_calls_claimed": False,
        "benchmark_reserved_token_ceiling": 2_000_000,
        "readiness_probe_estimated_tokens": 100,
        "readiness_probe_usage_source": SUBSCRIPTION_RUNTIME_ESTIMATED_USAGE_SOURCE,
        "total_accounted_tokens": 2_000_100,
        "token_accounting_publishable": False,
    }

    for invalid_changes in (
        {"readiness_probe_usage_source": "provider_observed"},
        {"token_accounting_publishable": True},
        {"total_accounted_tokens": 2_000_000},
    ):
        with pytest.raises(
            live.ManagedLiveAdmissionError,
            match="provider usage budget is invalid",
        ):
            replace(material.provider_usage_budget, **invalid_changes)

    with pytest.raises(live.ManagedLiveAdmissionError, match="already reserved"):
        _issue(
            request=request,
            now=now,
            route=probe,
            runtime_port=_runtime_port(),
            case_ids=case_ids,
            budget=live.ManagedLiveBudget(2, 8, 2_000_000),
            deadline_delta=timedelta(hours=2),
        )

    for invalid_budget in (
        live.ManagedLiveBudget(2, 7, 2_000_000),
        live.ManagedLiveBudget(2, 8, 2_000_001),
    ):
        with pytest.raises(live.ManagedLiveAdmissionError, match="budget"):
            _issue(
                request=request,
                now=now,
                route=_subscription_probe(now),
                runtime_port=_runtime_port(),
                case_ids=case_ids,
                budget=invalid_budget,
                deadline_delta=timedelta(hours=2),
            )

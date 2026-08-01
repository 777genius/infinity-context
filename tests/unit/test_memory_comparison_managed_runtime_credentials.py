from __future__ import annotations

import copy
import hashlib
import inspect
import json
import pickle
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from infinity_context_server import (
    memory_comparison_managed_runtime_credentials_context as credential_context_module,
)
from infinity_context_server.memory_comparison_full_methodology import (
    full_comparison_methodology_contract,
)
from infinity_context_server.memory_comparison_full_profiles import (
    PROFILE_LOCOMO_TOP_50,
    resolve_full_comparison_profile,
)
from infinity_context_server.memory_comparison_managed_preflight import (
    MANAGED_PREFLIGHT_PROVIDER_SUBSCRIPTION_RUNTIME,
    ManagedDatasetMetadata,
    ManagedPreflightRequest,
    ManagedPreflightTimeouts,
)
from infinity_context_server.memory_comparison_managed_runtime_credentials import (
    ManagedRuntimeCredentialAuthority,
    ManagedRuntimeCredentialError,
    issue_managed_runtime_credential_authority,
)
from infinity_context_server.memory_comparison_managed_runtime_credentials_context import (
    _inspect_completed_managed_runtime_credential_context,
)
from infinity_context_server.memory_comparison_subscription_chat import (
    SUBSCRIPTION_RUNTIME_ESTIMATED_USAGE_SOURCE,
    SubscriptionRuntimeChatCompletions,
)

_NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
_DEADLINE = _NOW + timedelta(seconds=60)
_RUN_ID = "managed-credential-run-001"
_INFINITY_ORIGIN = "https://INFINITY.example.test:443/api/"
_MEM0_ORIGIN = "http://127.0.0.1:8765/"
_SUBSCRIPTION_ORIGIN = "http://127.0.0.1:8890/"
_INFINITY_SECRET = "infinity-auth-super-secret"
_MEM0_SECRET = "mem0-api-super-secret"
_PROBE_SECRET = "mem0-probe-super-secret"
_SUBSCRIPTION_SECRET = "subscription-bearer-super-secret"
_MODEL = "gpt-5.6-sol"


def _authority(
    *,
    deadline: datetime = _DEADLINE,
) -> ManagedRuntimeCredentialAuthority:
    return issue_managed_runtime_credential_authority(
        run_id=_RUN_ID,
        infinity_origin=_INFINITY_ORIGIN,
        infinity_auth_token=_INFINITY_SECRET,
        mem0_origin=_MEM0_ORIGIN,
        mem0_api_key=_MEM0_SECRET,
        mem0_probe_token=_PROBE_SECRET,
        subscription_origin=_SUBSCRIPTION_ORIGIN,
        subscription_bearer_token=_SUBSCRIPTION_SECRET,
        request_timeout_seconds=10.0,
        issued_at=_NOW,
        deadline=deadline,
    )


def _request(authority: ManagedRuntimeCredentialAuthority) -> ManagedPreflightRequest:
    material = authority.preflight_material()
    profile = resolve_full_comparison_profile(PROFILE_LOCOMO_TOP_50)
    assert profile is not None
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
        provider_route=material.provider_route,
        answerer_model=_MODEL,
        judge_model=_MODEL,
        openai_credential=material.provider_credential,
        backend_endpoints=material.backend_endpoints,
        timeouts=ManagedPreflightTimeouts(1.0, 10.0, 120.0),
        scope="canary",
        provider_kind=MANAGED_PREFLIGHT_PROVIDER_SUBSCRIPTION_RUNTIME,
    )


def _bind(
    authority: ManagedRuntimeCredentialAuthority,
) -> ManagedPreflightRequest:
    request = _request(authority)
    authority.bind_preflight_request(request, run_id=_RUN_ID, deadline=_DEADLINE)
    return request


def _success_payload(text: str = "READY") -> dict[str, object]:
    return {
        "object": "chat.completion",
        "id": "chatcmpl-managed-credential-1",
        "model": _MODEL,
        "system_fingerprint": "subscription-runtime-credential-test-v1",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 19,
            "completion_tokens": 2,
            "total_tokens": 21,
            "usage_source": SUBSCRIPTION_RUNTIME_ESTIMATED_USAGE_SOURCE,
        },
    }


def _assert_secret_safe(value: object) -> None:
    rendered = repr(value)
    encoded = json.dumps({"rendered": rendered})
    for secret in (
        _INFINITY_SECRET,
        _MEM0_SECRET,
        _PROBE_SECRET,
        _SUBSCRIPTION_SECRET,
    ):
        assert secret not in rendered
        assert secret not in encoded


def test_exact_public_material_normalizes_targets_without_secrets() -> None:
    authority = _authority()
    material = authority.preflight_material()

    assert authority.preflight_material() is material
    assert tuple(item.base_url for item in material.backend_endpoints) == (
        "https://infinity.example.test/api",
        "http://127.0.0.1:8765",
    )
    assert material.provider_route.origin == "http://127.0.0.1:8890"
    assert material.provider_route.credential_binding_id == (
        "sha256:" + hashlib.sha256(_SUBSCRIPTION_SECRET.encode()).hexdigest()
    )
    assert material.mem0_probe_credential.binding_id == (
        "sha256:" + hashlib.sha256(_PROBE_SECRET.encode()).hexdigest()
    )
    assert material.backend_endpoints[1].credential.binding_id != (
        "sha256:" + hashlib.sha256(_MEM0_SECRET.encode()).hexdigest()
    )
    assert material.mem0_probe_credential.binding_id not in {
        item.credential.binding_id for item in material.backend_endpoints
    }
    _assert_secret_safe(authority)
    _assert_secret_safe(material)
    with pytest.raises(TypeError, match="noncopyable"):
        copy.copy(authority)
    with pytest.raises(TypeError, match="nonserializable"):
        pickle.dumps(authority)


def test_readiness_then_distinct_execution_adapter_preserve_exact_bearer() -> None:
    authority = _authority()
    request = _bind(authority)
    readiness_requests: list[httpx.Request] = []
    execution_requests: list[httpx.Request] = []

    def readiness_handler(raw: httpx.Request) -> httpx.Response:
        readiness_requests.append(raw)
        return httpx.Response(200, json=_success_payload())

    claim = authority.issue_subscription_readiness_claim(
        expected_request=request,
        run_id=_RUN_ID,
        subscription_origin=_SUBSCRIPTION_ORIGIN,
        deadline=_DEADLINE,
        now=_NOW,
        transport=httpx.MockTransport(readiness_handler),
    )
    proof = claim.run(model=_MODEL, clock=lambda: _NOW)
    assert type(proof).__name__ == "VerifiedSubscriptionRuntimeProbe"
    assert len(readiness_requests) == 1
    assert readiness_requests[0].headers["Authorization"] == (
        f"Bearer {_SUBSCRIPTION_SECRET}"
    )

    def execution_handler(raw: httpx.Request) -> httpx.Response:
        execution_requests.append(raw)
        return httpx.Response(200, json=_success_payload("ordinary response"))

    execution = authority.issue_subscription_execution_adapter(
        readiness_claim=claim,
        expected_request=request,
        run_id=_RUN_ID,
        subscription_origin=_SUBSCRIPTION_ORIGIN,
        deadline=_DEADLINE,
        now=_NOW,
        transport=httpx.MockTransport(execution_handler),
    )
    assert type(execution) is SubscriptionRuntimeChatCompletions
    assert execution.route_attestation == authority.preflight_material().provider_route
    assert execution.request_timeout_seconds == 10.0
    completion = execution.complete(
        model=_MODEL,
        system_prompt="system",
        user_prompt="user",
        max_output_tokens=8,
    )
    assert completion.text == "ordinary response"
    assert len(execution_requests) == 1
    assert execution_requests[0].headers["Authorization"] == (
        f"Bearer {_SUBSCRIPTION_SECRET}"
    )
    execution.close()

    with pytest.raises(ManagedRuntimeCredentialError) as replay:
        authority.issue_subscription_execution_adapter(
            readiness_claim=claim,
            expected_request=request,
            run_id=_RUN_ID,
            subscription_origin=_SUBSCRIPTION_ORIGIN,
            deadline=_DEADLINE,
            now=_NOW,
            transport=httpx.MockTransport(execution_handler),
        )
    assert replay.value.code == "managed_credentials_terminal"


def test_completed_readiness_context_inspection_is_stable_and_non_consuming() -> None:
    authority = _authority()
    request = _bind(authority)
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_success_payload())

    claim = authority.issue_subscription_readiness_claim(
        expected_request=request,
        run_id=_RUN_ID,
        subscription_origin=_SUBSCRIPTION_ORIGIN,
        deadline=_DEADLINE,
        now=_NOW,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ManagedRuntimeCredentialError) as incomplete:
        _inspect_completed_managed_runtime_credential_context(
            authority,
            claim,
            expected_request=request,
            expected_probe=object(),
            run_id=_RUN_ID,
            deadline=_DEADLINE,
        )
    assert incomplete.value.code == "managed_credentials_context_mismatch"
    assert calls == 0

    proof = claim.run(model=_MODEL, clock=lambda: _NOW)
    first = _inspect_completed_managed_runtime_credential_context(
        authority,
        claim,
        expected_request=request,
        expected_probe=proof,
        run_id=_RUN_ID,
        deadline=_DEADLINE,
    )
    second = _inspect_completed_managed_runtime_credential_context(
        authority,
        claim,
        expected_request=request,
        expected_probe=proof,
        run_id=_RUN_ID,
        deadline=_DEADLINE,
    )
    assert first == second
    assert len(first) == 64
    assert calls == 1

    foreign_authority = _authority()
    foreign_request = _bind(foreign_authority)
    foreign_claim = foreign_authority.issue_subscription_readiness_claim(
        expected_request=foreign_request,
        run_id=_RUN_ID,
        subscription_origin=_SUBSCRIPTION_ORIGIN,
        deadline=_DEADLINE,
        now=_NOW,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=_success_payload())
        ),
    )
    foreign_probe = foreign_claim.run(model=_MODEL, clock=lambda: _NOW)
    with pytest.raises(ManagedRuntimeCredentialError) as foreign:
        _inspect_completed_managed_runtime_credential_context(
            authority,
            claim,
            expected_request=request,
            expected_probe=foreign_probe,
            run_id=_RUN_ID,
            deadline=_DEADLINE,
        )
    assert foreign.value.code == "managed_credentials_context_mismatch"

    execution = authority.issue_subscription_execution_adapter(
        readiness_claim=claim,
        expected_request=request,
        run_id=_RUN_ID,
        subscription_origin=_SUBSCRIPTION_ORIGIN,
        deadline=_DEADLINE,
        now=_NOW,
        transport=httpx.MockTransport(lambda _: httpx.Response(500)),
    )
    execution.close()


def test_context_helper_uses_authority_owned_inspection_seam() -> None:
    source = inspect.getsource(credential_context_module)
    assert "_ManagedRuntimeCredentialAuthority__" not in source


def test_backend_configs_preserve_exact_secrets_and_are_single_use() -> None:
    authority = _authority()
    request = _bind(authority)
    infinity_transport = httpx.MockTransport(lambda _: httpx.Response(204))
    mem0_transport = httpx.MockTransport(lambda _: httpx.Response(204))

    material = authority.issue_backend_credential_material(
        expected_request=request,
        run_id=_RUN_ID,
        infinity_origin=_INFINITY_ORIGIN,
        mem0_origin=_MEM0_ORIGIN,
        deadline=_DEADLINE,
        now=_NOW,
        infinity_transport=infinity_transport,
        mem0_transport=mem0_transport,
    )

    _assert_secret_safe(material)
    assert not hasattr(material, "infinity")
    assert not hasattr(material, "mem0")
    assert not hasattr(material, "mem0_probe_token")
    with pytest.raises(TypeError, match="nonserializable"):
        pickle.dumps(material)
    probe_token = material.consume_mem0_probe_token(
        expected_request=request,
        run_id=_RUN_ID,
        deadline=_DEADLINE,
    )
    assert probe_token == _PROBE_SECRET
    with pytest.raises(ValueError, match="continuity failed"):
        material.consume_mem0_probe_token(
            expected_request=request,
            run_id=_RUN_ID,
            deadline=_DEADLINE,
        )
    infinity, mem0 = material.consume_for_http_execution(
        expected_request=request,
        run_id=_RUN_ID,
        deadline=_DEADLINE,
    )
    assert infinity.auth_token == _INFINITY_SECRET
    assert mem0.api_key == _MEM0_SECRET
    assert infinity.base_url == "https://infinity.example.test/api"
    assert mem0.base_url == "http://127.0.0.1:8765"
    assert infinity.transport is infinity_transport
    assert mem0.transport is mem0_transport
    lifecycle_infinity, lifecycle_mem0 = material.consume_for_http_lifecycle(
        expected_request=request,
        run_id=_RUN_ID,
        deadline=_DEADLINE,
    )
    policy_infinity, policy_mem0 = material.consume_for_http_policy(
        expected_request=request,
        run_id=_RUN_ID,
        deadline=_DEADLINE,
    )
    assert lifecycle_infinity.transport is None
    assert lifecycle_mem0.transport is None
    assert policy_infinity.transport is None
    assert policy_mem0.transport is None
    assert lifecycle_infinity is not policy_infinity
    assert lifecycle_mem0 is not policy_mem0
    _assert_secret_safe(infinity)
    _assert_secret_safe(mem0)
    with pytest.raises(ValueError, match="continuity failed"):
        material.consume_for_http_execution(
            expected_request=request,
            run_id=_RUN_ID,
            deadline=_DEADLINE,
        )
    with pytest.raises(ValueError, match="continuity failed"):
        material.consume_for_http_lifecycle(
            expected_request=request,
            run_id=_RUN_ID,
            deadline=_DEADLINE,
        )
    with pytest.raises(ValueError, match="continuity failed"):
        material.consume_for_http_policy(
            expected_request=request,
            run_id=_RUN_ID,
            deadline=_DEADLINE,
        )

    with pytest.raises(ManagedRuntimeCredentialError) as replay:
        authority.issue_backend_credential_material(
            expected_request=request,
            run_id=_RUN_ID,
            infinity_origin=_INFINITY_ORIGIN,
            mem0_origin=_MEM0_ORIGIN,
            deadline=_DEADLINE,
            now=_NOW,
        )
    assert replay.value.code == "managed_credentials_terminal"


def test_backend_material_rejects_equal_model_request_tamper_before_io() -> None:
    authority = _authority()
    request = _bind(authority)
    calls = 0

    def unexpected(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    material = authority.issue_backend_credential_material(
        expected_request=request,
        run_id=_RUN_ID,
        infinity_origin=_INFINITY_ORIGIN,
        mem0_origin=_MEM0_ORIGIN,
        deadline=_DEADLINE,
        now=_NOW,
        infinity_transport=httpx.MockTransport(unexpected),
        mem0_transport=httpx.MockTransport(unexpected),
    )
    object.__setattr__(request, "answerer_model", "gpt-5.6-sol-tampered")
    object.__setattr__(request, "judge_model", "gpt-5.6-sol-tampered")

    with pytest.raises(ValueError, match="continuity failed"):
        material.consume_for_http_execution(
            expected_request=request,
            run_id=_RUN_ID,
            deadline=_DEADLINE,
        )
    object.__setattr__(request, "answerer_model", _MODEL)
    object.__setattr__(request, "judge_model", _MODEL)
    lifecycle = material.consume_for_http_lifecycle(
        expected_request=request,
        run_id=_RUN_ID,
        deadline=_DEADLINE,
    )
    assert all(config.transport is None for config in lifecycle)
    policy = material.consume_for_http_policy(
        expected_request=request,
        run_id=_RUN_ID,
        deadline=_DEADLINE,
    )
    assert all(config.transport is None for config in policy)
    assert material.consume_mem0_probe_token(
        expected_request=request,
        run_id=_RUN_ID,
        deadline=_DEADLINE,
    ) == _PROBE_SECRET
    assert calls == 0


def test_request_mutation_after_bind_is_detected_and_backend_lane_terminal() -> None:
    authority = _authority()
    request = _bind(authority)
    object.__setattr__(request, "answerer_model", "tampered-model")

    with pytest.raises(ManagedRuntimeCredentialError) as caught:
        authority.issue_backend_credential_material(
            expected_request=request,
            run_id=_RUN_ID,
            infinity_origin=_INFINITY_ORIGIN,
            mem0_origin=_MEM0_ORIGIN,
            deadline=_DEADLINE,
            now=_NOW,
        )
    assert caught.value.code in {
        "managed_credentials_integrity_failed",
        "managed_credentials_preflight_invalid",
    }
    _assert_secret_safe(caught.value)

    with pytest.raises(ManagedRuntimeCredentialError) as replay:
        authority.issue_backend_credential_material(
            expected_request=request,
            run_id=_RUN_ID,
            infinity_origin=_INFINITY_ORIGIN,
            mem0_origin=_MEM0_ORIGIN,
            deadline=_DEADLINE,
            now=_NOW,
        )
    assert replay.value.code == "managed_credentials_terminal"


def test_wrong_backend_origin_burns_only_backend_credential_lane() -> None:
    authority = _authority()
    request = _bind(authority)

    with pytest.raises(ManagedRuntimeCredentialError) as caught:
        authority.issue_backend_credential_material(
            expected_request=request,
            run_id=_RUN_ID,
            infinity_origin="https://other.example.test/api",
            mem0_origin=_MEM0_ORIGIN,
            deadline=_DEADLINE,
            now=_NOW,
        )
    assert caught.value.code == "managed_credentials_context_mismatch"

    with pytest.raises(ManagedRuntimeCredentialError) as replay:
        authority.issue_backend_credential_material(
            expected_request=request,
            run_id=_RUN_ID,
            infinity_origin=_INFINITY_ORIGIN,
            mem0_origin=_MEM0_ORIGIN,
            deadline=_DEADLINE,
            now=_NOW,
        )
    assert replay.value.code == "managed_credentials_terminal"
    assert authority.preflight_material().provider_route is request.provider_route


def test_secret_tamper_fails_integrity_without_reflecting_secret() -> None:
    authority = _authority()
    state = object.__getattribute__(
        authority,
        "_ManagedRuntimeCredentialAuthority__state",
    )
    object.__setattr__(state, "infinity_secret", "attacker-secret-value")

    with pytest.raises(ManagedRuntimeCredentialError) as caught:
        authority.preflight_material()
    assert caught.value.code == "managed_credentials_integrity_failed"
    assert "attacker-secret-value" not in str(caught.value)
    assert "attacker-secret-value" not in repr(caught.value)

    with pytest.raises(ManagedRuntimeCredentialError) as terminal:
        authority.preflight_material()
    assert terminal.value.code in {
        "managed_credentials_integrity_failed",
        "managed_credentials_terminal",
    }


@pytest.mark.parametrize(
    ("overrides", "expected_code"),
    (
        ({"run_id": "wrong-run"}, "managed_credentials_context_mismatch"),
        (
            {"subscription_origin": "http://127.0.0.1:9000"},
            "managed_credentials_context_mismatch",
        ),
        ({"deadline": _DEADLINE + timedelta(seconds=1)}, "managed_credentials_context_mismatch"),
        ({"now": _DEADLINE}, "managed_credentials_expired"),
    ),
)
def test_wrong_context_or_deadline_terminalizes_readiness_lane(
    overrides: dict[str, object],
    expected_code: str,
) -> None:
    authority = _authority()
    request = _bind(authority)
    values: dict[str, object] = {
        "expected_request": request,
        "run_id": _RUN_ID,
        "subscription_origin": _SUBSCRIPTION_ORIGIN,
        "deadline": _DEADLINE,
        "now": _NOW,
        "transport": httpx.MockTransport(lambda _: httpx.Response(500)),
    }
    values.update(overrides)
    with pytest.raises(ManagedRuntimeCredentialError) as caught:
        authority.issue_subscription_readiness_claim(**values)  # type: ignore[arg-type]
    assert caught.value.code == expected_code

    with pytest.raises(ManagedRuntimeCredentialError) as replay:
        authority.issue_subscription_readiness_claim(
            expected_request=request,
            run_id=_RUN_ID,
            subscription_origin=_SUBSCRIPTION_ORIGIN,
            deadline=_DEADLINE,
            now=_NOW,
            transport=httpx.MockTransport(lambda _: httpx.Response(500)),
        )
    assert replay.value.code == "managed_credentials_terminal"


def test_concurrent_readiness_issue_burns_claim_before_any_provider_call() -> None:
    authority = _authority()
    request = _bind(authority)
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_success_payload())

    def issue() -> object:
        try:
            return authority.issue_subscription_readiness_claim(
                expected_request=request,
                run_id=_RUN_ID,
                subscription_origin=_SUBSCRIPTION_ORIGIN,
                deadline=_DEADLINE,
                now=_NOW,
                transport=httpx.MockTransport(handler),
            )
        except ManagedRuntimeCredentialError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = tuple(pool.map(lambda _: issue(), range(2)))
    claims = tuple(item for item in outcomes if not isinstance(item, Exception))
    errors = tuple(item for item in outcomes if isinstance(item, ManagedRuntimeCredentialError))
    assert len(claims) == 1
    assert len(errors) == 1
    assert errors[0].code == "managed_credentials_terminal"

    with pytest.raises(ManagedRuntimeCredentialError) as terminal:
        claims[0].run(model=_MODEL, clock=lambda: _NOW)
    assert terminal.value.code == "managed_credentials_terminal"
    assert calls == 0


def test_failed_readiness_is_one_attempt_no_retry_and_blocks_execution() -> None:
    authority = _authority()
    request = _bind(authority)
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, text="private provider failure")

    claim = authority.issue_subscription_readiness_claim(
        expected_request=request,
        run_id=_RUN_ID,
        subscription_origin=_SUBSCRIPTION_ORIGIN,
        deadline=_DEADLINE,
        now=_NOW,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ManagedRuntimeCredentialError) as caught:
        claim.run(model=_MODEL, clock=lambda: _NOW)
    assert caught.value.code == "managed_credentials_readiness_failed"
    assert "private provider failure" not in repr(caught.value)
    assert calls == 1

    with pytest.raises(ManagedRuntimeCredentialError):
        authority.issue_subscription_execution_adapter(
            readiness_claim=claim,
            expected_request=request,
            run_id=_RUN_ID,
            subscription_origin=_SUBSCRIPTION_ORIGIN,
            deadline=_DEADLINE,
            now=_NOW,
            transport=httpx.MockTransport(handler),
        )

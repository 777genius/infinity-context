"""Executable composition root for a managed subscription-runtime canary."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import secrets
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import final
from urllib.parse import urlsplit

from infinity_context_server.memory_comparison_full_methodology import (
    full_comparison_methodology_contract,
)
from infinity_context_server.memory_comparison_full_profiles import (
    FULL_COMPARISON_PROFILES,
    FullComparisonProfile,
    frozen_full_comparison_profile,
    resolve_full_comparison_profile,
)
from infinity_context_server.memory_comparison_full_scope import FULL_COMPARISON_SCOPE_CANARY
from infinity_context_server.memory_comparison_managed_live_admission import (
    MANAGED_PROVIDER_SUBSCRIPTION_RUNTIME,
    ManagedLiveBudget,
    issue_verified_managed_live_admission,
)
from infinity_context_server.memory_comparison_managed_live_composition import (
    prepare_verified_managed_live_run,
)
from infinity_context_server.memory_comparison_managed_mem0_auth import (
    MANAGED_MEM0_DATA_PLANE_AUTH_API_KEY,
    MANAGED_MEM0_DATA_PLANE_AUTH_NONE,
    expected_managed_mem0_runtime_mode,
)
from infinity_context_server.memory_comparison_managed_mem0_runtime_http import (
    ManagedMem0RuntimeAttestationPort,
    ManagedUtcClockPort,
)
from infinity_context_server.memory_comparison_managed_plan_builder import (
    MANAGED_CANARY_MAX_CASES,
    managed_policy_cases_from_dataset,
)
from infinity_context_server.memory_comparison_managed_preflight import (
    MANAGED_PREFLIGHT_PROVIDER_SUBSCRIPTION_RUNTIME,
    ManagedPreflightRequest,
    ManagedPreflightTimeouts,
    managed_dataset_metadata_from_bytes,
)
from infinity_context_server.memory_comparison_managed_production_composition import (
    evaluate_managed_production_pre_readiness,
    run_verified_managed_production_comparison,
)
from infinity_context_server.memory_comparison_managed_run import public_managed_run
from infinity_context_server.memory_comparison_managed_runtime_credentials import (
    issue_managed_runtime_credential_authority,
)
from infinity_context_server.memory_comparison_mem0_oss_ingress import (
    MEM0_OSS_INGRESS_API_KEY_ENV,
    Mem0OssIngressCredentialAuthority,
    Mem0OssIngressCredentialError,
    issue_mem0_oss_ingress_credential_authority,
)
from infinity_context_server.public_benchmark_artifacts import (
    validate_artifact_paths_do_not_overwrite_dataset,
    write_json_atomic,
)

MANAGED_LIVE_CLI_SUITE = "managed-comparison-live-subscription-canary"
MANAGED_LIVE_CLI_SCHEMA_VERSION = "managed-comparison-live-subscription-canary.v1"
MANAGED_LIVE_CLI_MODEL = "gpt-5.6-sol"
MANAGED_LIVE_CLI_MAX_DATASET_BYTES = 402_653_184
MANAGED_LIVE_CLI_MAX_TOTAL_TOKENS = 2_000_000
MANAGED_LIVE_CLI_MAX_RUN_SECONDS = 7_200.0
MANAGED_LIVE_CLI_MAX_REQUEST_SECONDS = 120.0
MANAGED_LIVE_CLI_SUCCESS = 0
MANAGED_LIVE_CLI_NO_GO = 2
MANAGED_LIVE_CLI_FAILURE = 3

_ENV_INFINITY_TOKEN = "MEMORY_EVAL_AUTH_TOKEN"
_ENV_MEM0_API_KEY = "MEM0_API_KEY"
_ENV_MEM0_PROBE_TOKEN = "MEM0_BENCHMARK_PROBE_TOKEN"
_ENV_SUBSCRIPTION_TOKEN = "SUBSCRIPTION_RUNTIME_BRIDGE_BEARER_TOKEN"
_SAFE_CODES = frozenset(
    {
        "artifact_path_invalid",
        "artifact_write_failed",
        "authorization_required",
        "config_invalid",
        "credential_missing",
        "dataset_too_large",
        "dataset_unreadable",
        "local_mem0_target_required",
        "mem0_oss_ingress_configuration_invalid",
        "pre_readiness_no_go",
        "profile_invalid",
    }
)


class ManagedLiveCliError(RuntimeError):
    """Fixed-code failure which never reflects credentials or provider text."""

    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        self.code = code if code in _SAFE_CODES else "managed_live_execution_failed"
        super().__init__(self.code)


@final
@dataclass(frozen=True, slots=True)
class ManagedLiveCliConfig:
    dataset_path: Path
    profile_id: str
    selected_case_ids: tuple[str, ...]
    run_id: str
    infinity_api_url: str
    mem0_api_url: str
    subscription_runtime_url: str
    max_total_tokens: int
    mem0_runtime_implementation_sha256: str
    allow_live: bool
    allow_paid_llm: bool
    operator_notified: bool
    mem0_local_auth_disabled_managed: bool = False
    mem0_oss_ingress_protected: bool = False
    allowed_mem0_hosts: tuple[str, ...] = ()
    report_out: Path | None = None
    connect_timeout_seconds: float = 10.0
    request_timeout_seconds: float = 120.0
    run_timeout_seconds: float = 3_600.0

    def __post_init__(self) -> None:
        urls = (self.infinity_api_url, self.mem0_api_url, self.subscription_runtime_url)
        booleans = (
            self.allow_live,
            self.allow_paid_llm,
            self.operator_notified,
            self.mem0_local_auth_disabled_managed,
            self.mem0_oss_ingress_protected,
        )
        if (
            not isinstance(self.dataset_path, Path)
            or type(self.profile_id) is not str
            or not self.profile_id
            or type(self.selected_case_ids) is not tuple
            or not 1 <= len(self.selected_case_ids) <= MANAGED_CANARY_MAX_CASES
            or any(
                type(item) is not str or not item or item != item.strip()
                for item in self.selected_case_ids
            )
            or len(set(self.selected_case_ids)) != len(self.selected_case_ids)
            or type(self.run_id) is not str
            or not self.run_id
            or any(type(value) is not str or not value for value in urls)
            or type(self.max_total_tokens) is not int
            or not 1 <= self.max_total_tokens <= MANAGED_LIVE_CLI_MAX_TOTAL_TOKENS
            or type(self.mem0_runtime_implementation_sha256) is not str
            or len(self.mem0_runtime_implementation_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in self.mem0_runtime_implementation_sha256
            )
            or any(type(value) is not bool for value in booleans)
            or type(self.allowed_mem0_hosts) is not tuple
            or any(type(host) is not str or not host for host in self.allowed_mem0_hosts)
            or (self.report_out is not None and not isinstance(self.report_out, Path))
            or not _bounded_timeout(self.connect_timeout_seconds, 30.0)
            or not _bounded_timeout(
                self.request_timeout_seconds,
                MANAGED_LIVE_CLI_MAX_REQUEST_SECONDS,
            )
            or not _bounded_timeout(
                self.run_timeout_seconds,
                MANAGED_LIVE_CLI_MAX_RUN_SECONDS,
            )
        ):
            raise ManagedLiveCliError("config_invalid")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedLiveCliConfig is final")


def run_managed_live_cli(
    config: ManagedLiveCliConfig,
    *,
    env: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Execute one bounded non-publishable canary through sealed authorities."""

    if type(config) is not ManagedLiveCliConfig:
        raise ManagedLiveCliError("config_invalid")
    if (
        config.allow_live is not True
        or config.allow_paid_llm is not True
        or config.operator_notified is not True
    ):
        return _failure("authorization_required")
    environment = os.environ if env is None else env
    if not isinstance(environment, Mapping):
        raise ManagedLiveCliError("config_invalid")
    try:
        validate_artifact_paths_do_not_overwrite_dataset(
            dataset_path=config.dataset_path,
            error_factory=lambda _: ManagedLiveCliError("artifact_path_invalid"),
            report_out=config.report_out,
        )
        report = _run_managed_live(config, environment)
    except ManagedLiveCliError as exc:
        report = _failure(exc.code)
    except OSError:
        report = _failure("dataset_unreadable")
    except Exception:
        report = _failure("managed_live_execution_failed")
    if config.report_out is not None:
        try:
            write_json_atomic(config.report_out, report)
        except (OSError, TypeError, ValueError) as exc:
            raise ManagedLiveCliError("artifact_write_failed") from exc
    return report


def _run_managed_live(
    config: ManagedLiveCliConfig,
    env: Mapping[str, str],
) -> dict[str, object]:
    profile = _profile(config.profile_id)
    dataset_bytes = _dataset_bytes(config.dataset_path)
    dataset = managed_dataset_metadata_from_bytes(
        profile=profile,
        dataset_bytes=dataset_bytes,
    )
    cases = managed_policy_cases_from_dataset(
        profile=profile,
        dataset_bytes=dataset_bytes,
        scope=FULL_COMPARISON_SCOPE_CANARY,
        selected_case_ids=config.selected_case_ids,
    )
    decision = evaluate_managed_production_pre_readiness(cases)
    if decision.decision != "go":
        return _failure("pre_readiness_no_go", blockers=decision.blockers)

    infinity_token = _required_secret(
        env,
        _ENV_INFINITY_TOKEN,
        fallback="MEMORY_SERVICE_TOKEN",
    )
    mem0_probe_token = _required_secret(env, _ENV_MEM0_PROBE_TOKEN)
    subscription_token = _required_secret(env, _ENV_SUBSCRIPTION_TOKEN)
    mem0_data_plane_auth_mode, mem0_api_key = _mem0_data_plane_auth(config, env)
    mem0_oss_ingress_authority = _mem0_oss_ingress_authority(config, env)
    try:
        expected_mem0_runtime_mode = expected_managed_mem0_runtime_mode(
            data_plane_auth_mode=mem0_data_plane_auth_mode,
            profile_runtime_mode=profile.required_mem0_runtime_mode,
        )
    except ValueError:
        raise ManagedLiveCliError("profile_invalid") from None
    clock = ManagedUtcClockPort()
    issued_at = clock.now()
    deadline = issued_at + timedelta(seconds=float(config.run_timeout_seconds))
    authority = issue_managed_runtime_credential_authority(
        run_id=config.run_id,
        infinity_origin=config.infinity_api_url,
        infinity_auth_token=infinity_token,
        mem0_origin=config.mem0_api_url,
        mem0_api_key=mem0_api_key,
        mem0_probe_token=mem0_probe_token,
        subscription_origin=config.subscription_runtime_url,
        subscription_bearer_token=subscription_token,
        request_timeout_seconds=float(config.request_timeout_seconds),
        issued_at=issued_at,
        deadline=deadline,
        mem0_data_plane_auth_mode=mem0_data_plane_auth_mode,
        mem0_oss_ingress_authority=mem0_oss_ingress_authority,
    )
    material = authority.preflight_material()
    request = ManagedPreflightRequest(
        profile=profile,
        methodology=full_comparison_methodology_contract(profile),
        dataset=dataset,
        provider_route=material.provider_route,
        answerer_model=MANAGED_LIVE_CLI_MODEL,
        judge_model=MANAGED_LIVE_CLI_MODEL,
        openai_credential=material.provider_credential,
        backend_endpoints=material.backend_endpoints,
        timeouts=ManagedPreflightTimeouts(
            connect_seconds=float(config.connect_timeout_seconds),
            request_seconds=float(config.request_timeout_seconds),
            run_seconds=float(config.run_timeout_seconds),
        ),
        scope=FULL_COMPARISON_SCOPE_CANARY,
        provider_kind=MANAGED_PREFLIGHT_PROVIDER_SUBSCRIPTION_RUNTIME,
        mem0_data_plane_auth_mode=material.mem0_data_plane_auth_mode,
    )
    authority.bind_preflight_request(request, run_id=config.run_id, deadline=deadline)
    readiness_claim = authority.issue_subscription_readiness_claim(
        expected_request=request,
        run_id=config.run_id,
        subscription_origin=config.subscription_runtime_url,
        deadline=deadline,
        now=clock.now(),
    )
    provider_probe = readiness_claim.run(
        model=MANAGED_LIVE_CLI_MODEL,
        clock=clock.now,
    )
    admitted_at = clock.now()
    remaining = (deadline - admitted_at).total_seconds()
    runtime_budget = max(0.001, remaining - 0.001)
    runtime_port = ManagedMem0RuntimeAttestationPort(
        base_url=config.mem0_api_url,
        benchmark_probe_token=mem0_probe_token,
        probe_nonce=secrets.token_urlsafe(32),
        timeout_seconds=float(config.request_timeout_seconds),
        deadline_budget_seconds=runtime_budget,
        monotonic_clock=time.monotonic,
        expected_implementation_sha256=config.mem0_runtime_implementation_sha256,
        allowed_target_hosts=config.allowed_mem0_hosts,
        expected_runtime_mode=expected_mem0_runtime_mode,
        mem0_oss_ingress_authority=mem0_oss_ingress_authority,
    )
    admission = issue_verified_managed_live_admission(
        request=request,
        allow_live=config.allow_live,
        allow_paid_llm=config.allow_paid_llm,
        allow_full_run=False,
        run_id=config.run_id,
        run_nonce_commitment_sha256=hashlib.sha256(secrets.token_bytes(32)).hexdigest(),
        canary_case_ids=config.selected_case_ids,
        mem0_probe_credential=material.mem0_probe_credential,
        mem0_runtime_port=runtime_port,
        provider_kind=MANAGED_PROVIDER_SUBSCRIPTION_RUNTIME,
        live_provider_evidence=provider_probe,
        budget=ManagedLiveBudget(
            max_cases=len(config.selected_case_ids),
            max_provider_calls=len(config.selected_case_ids) * 4,
            max_total_tokens=config.max_total_tokens,
        ),
        issued_at=admitted_at,
        deadline=deadline,
        now=admitted_at,
    )
    prepared = prepare_verified_managed_live_run(
        admission,
        expected_request=request,
        credential_authority=authority,
        readiness_claim=readiness_claim,
        dataset_bytes=dataset_bytes,
        now=clock.now(),
    )
    outcome = run_verified_managed_production_comparison(prepared)
    return {
        "suite": MANAGED_LIVE_CLI_SUITE,
        "schema_version": MANAGED_LIVE_CLI_SCHEMA_VERSION,
        "ok": True,
        "status": "completed",
        "provider_kind": MANAGED_PROVIDER_SUBSCRIPTION_RUNTIME,
        "profile_id": profile.profile_id,
        "scope": FULL_COMPARISON_SCOPE_CANARY,
        "selected_case_count": len(config.selected_case_ids),
        "publishable": False,
        "result": public_managed_run(outcome),
    }


def _profile(profile_id: str) -> FullComparisonProfile:
    try:
        profile = resolve_full_comparison_profile(profile_id)
        if profile is None:
            raise ValueError("managed profile is absent")
        return frozen_full_comparison_profile(profile)
    except (TypeError, ValueError):
        raise ManagedLiveCliError("profile_invalid") from None


def _dataset_bytes(path: Path) -> bytes:
    try:
        with path.open("rb") as handle:
            payload = handle.read(MANAGED_LIVE_CLI_MAX_DATASET_BYTES + 1)
    except OSError as exc:
        raise ManagedLiveCliError("dataset_unreadable") from exc
    if len(payload) > MANAGED_LIVE_CLI_MAX_DATASET_BYTES:
        raise ManagedLiveCliError("dataset_too_large")
    if not payload:
        raise ManagedLiveCliError("dataset_unreadable")
    return payload


def _required_secret(
    env: Mapping[str, str],
    name: str,
    *,
    fallback: str | None = None,
) -> str:
    value = env.get(name)
    if (not isinstance(value, str) or not value.strip()) and fallback is not None:
        value = env.get(fallback)
    if not isinstance(value, str) or not value.strip():
        raise ManagedLiveCliError("credential_missing")
    return value.strip()


def _mem0_data_plane_auth(
    config: ManagedLiveCliConfig,
    env: Mapping[str, str],
) -> tuple[str, str | None]:
    if config.mem0_local_auth_disabled_managed:
        if not config.mem0_oss_ingress_protected and not _is_authorized_loopback_mem0_target(
            config.mem0_api_url,
            allowed_hosts=config.allowed_mem0_hosts,
        ):
            raise ManagedLiveCliError("local_mem0_target_required")
        return MANAGED_MEM0_DATA_PLANE_AUTH_NONE, None
    value = env.get(_ENV_MEM0_API_KEY)
    if isinstance(value, str) and value.strip():
        return MANAGED_MEM0_DATA_PLANE_AUTH_API_KEY, value.strip()
    raise ManagedLiveCliError("credential_missing")


def _mem0_oss_ingress_authority(
    config: ManagedLiveCliConfig,
    env: Mapping[str, str],
) -> Mem0OssIngressCredentialAuthority | None:
    value = env.get(MEM0_OSS_INGRESS_API_KEY_ENV)
    configured = isinstance(value, str) and bool(value.strip())
    if not config.mem0_local_auth_disabled_managed:
        if config.mem0_oss_ingress_protected or configured:
            raise ManagedLiveCliError("mem0_oss_ingress_configuration_invalid")
        return None
    if not config.mem0_oss_ingress_protected:
        if configured:
            raise ManagedLiveCliError("mem0_oss_ingress_configuration_invalid")
        return None
    if not configured:
        raise ManagedLiveCliError("credential_missing")
    try:
        return issue_mem0_oss_ingress_credential_authority(
            run_id=config.run_id,
            base_url=config.mem0_api_url,
            ingress_api_key=value.strip(),
            allowed_target_hosts=config.allowed_mem0_hosts,
        )
    except Mem0OssIngressCredentialError:
        raise ManagedLiveCliError("mem0_oss_ingress_configuration_invalid") from None


def _mem0_api_key(config: ManagedLiveCliConfig, env: Mapping[str, str]) -> str | None:
    """Compatibility helper returning the sealed data-plane key, if any."""

    _, api_key = _mem0_data_plane_auth(config, env)
    return api_key


def _is_authorized_loopback_mem0_target(
    value: str,
    *,
    allowed_hosts: Sequence[str],
) -> bool:
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        if parsed.scheme != "http" or host is None or parsed.username or parsed.password:
            return False
        address = ipaddress.ip_address(host)
        return (
            isinstance(address, ipaddress.IPv4Address)
            and address.is_loopback
            and host in allowed_hosts
        )
    except ValueError:
        return False


def _bounded_timeout(value: object, maximum: float) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, int | float)
        and 0 < float(value) <= maximum
    )


def _failure(code: str, *, blockers: tuple[str, ...] = ()) -> dict[str, object]:
    safe_code = code if code in _SAFE_CODES else "managed_live_execution_failed"
    no_go = safe_code in {"authorization_required", "pre_readiness_no_go"}
    return {
        "suite": MANAGED_LIVE_CLI_SUITE,
        "schema_version": MANAGED_LIVE_CLI_SCHEMA_VERSION,
        "ok": False,
        "status": "no-go" if no_go else "failed",
        "reason_code": safe_code,
        "blockers": list(blockers),
        "provider_kind": MANAGED_PROVIDER_SUBSCRIPTION_RUNTIME,
        "scope": FULL_COMPARISON_SCOPE_CANARY,
        "publishable": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="infinity-context-managed-live-canary")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--profile", choices=FULL_COMPARISON_PROFILES, required=True)
    parser.add_argument("--case-id", dest="case_ids", action="append", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--infinity-api-url", required=True)
    parser.add_argument("--mem0-api-url", required=True)
    parser.add_argument("--subscription-runtime-url", required=True)
    parser.add_argument("--max-total-tokens", type=int, required=True)
    parser.add_argument("--mem0-runtime-implementation-sha256", required=True)
    parser.add_argument("--allow-live", action="store_true")
    parser.add_argument("--allow-paid-llm", action="store_true")
    parser.add_argument("--operator-notified", action="store_true")
    parser.add_argument("--mem0-local-auth-disabled-managed", action="store_true")
    parser.add_argument("--mem0-oss-ingress-protected", action="store_true")
    parser.add_argument("--allow-mem0-host", action="append", default=[])
    parser.add_argument("--report-out", type=Path, default=None)
    parser.add_argument("--connect-timeout-seconds", type=float, default=10.0)
    parser.add_argument("--request-timeout-seconds", type=float, default=120.0)
    parser.add_argument("--run-timeout-seconds", type=float, default=3_600.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        config = ManagedLiveCliConfig(
            dataset_path=args.dataset,
            profile_id=str(args.profile),
            selected_case_ids=tuple(args.case_ids),
            run_id=str(args.run_id),
            infinity_api_url=str(args.infinity_api_url),
            mem0_api_url=str(args.mem0_api_url),
            subscription_runtime_url=str(args.subscription_runtime_url),
            max_total_tokens=args.max_total_tokens,
            mem0_runtime_implementation_sha256=str(args.mem0_runtime_implementation_sha256),
            allow_live=args.allow_live,
            allow_paid_llm=args.allow_paid_llm,
            operator_notified=args.operator_notified,
            mem0_local_auth_disabled_managed=args.mem0_local_auth_disabled_managed,
            mem0_oss_ingress_protected=args.mem0_oss_ingress_protected,
            allowed_mem0_hosts=tuple(args.allow_mem0_host),
            report_out=args.report_out,
            connect_timeout_seconds=args.connect_timeout_seconds,
            request_timeout_seconds=args.request_timeout_seconds,
            run_timeout_seconds=args.run_timeout_seconds,
        )
        report = run_managed_live_cli(config)
    except ManagedLiveCliError as exc:
        report = _failure(exc.code)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, allow_nan=False))
    if report.get("ok") is True:
        return MANAGED_LIVE_CLI_SUCCESS
    if report.get("status") == "no-go":
        return MANAGED_LIVE_CLI_NO_GO
    return MANAGED_LIVE_CLI_FAILURE


__all__ = (
    "MANAGED_LIVE_CLI_SCHEMA_VERSION",
    "MANAGED_LIVE_CLI_SUITE",
    "ManagedLiveCliConfig",
    "ManagedLiveCliError",
    "main",
    "run_managed_live_cli",
)


if __name__ == "__main__":
    raise SystemExit(main())

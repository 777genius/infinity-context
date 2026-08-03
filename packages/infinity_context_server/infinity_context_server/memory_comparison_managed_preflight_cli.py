"""Static-only composition root for managed comparison preflight."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import secrets
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import final

from infinity_context_server.memory_comparison_backend_target import (
    FullComparisonBackendTarget,
)
from infinity_context_server.memory_comparison_full_methodology import (
    full_comparison_methodology_contract,
    public_full_comparison_methodology_contract,
)
from infinity_context_server.memory_comparison_full_profiles import (
    FULL_COMPARISON_PROFILES,
    FullComparisonProfile,
    resolve_full_comparison_profile,
)
from infinity_context_server.memory_comparison_managed_preflight import (
    ManagedBackendEndpoint,
    ManagedCredentialBinding,
    ManagedPreflightError,
    ManagedPreflightRequest,
    ManagedPreflightTimeouts,
    managed_backend_target_identity_sha256,
    managed_dataset_metadata_from_bytes,
    validate_managed_preflight,
)
from infinity_context_server.memory_comparison_provider_provenance import (
    ProviderRouteAttestation,
)
from infinity_context_server.public_benchmark_artifacts import (
    validate_artifact_paths_do_not_overwrite_dataset,
    write_json_atomic,
)

MANAGED_PREFLIGHT_CLI_SUITE = "managed-comparison-static-preflight"
MANAGED_PREFLIGHT_CLI_SCHEMA_VERSION = "managed-comparison-static-preflight.v1"
MANAGED_PREFLIGHT_MAX_DATASET_BYTES = 402_653_184

_CREDENTIAL_BINDING_CONTEXT = b"managed-comparison-static-preflight-credential.v1"
_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
_OPENAI_API_KEY = re.compile(r"^sk-[A-Za-z0-9_-]{20,}$")
_GENERIC_CREDENTIAL = re.compile(r"^\S{20,4096}$")
_OFFICIAL_DIRECT_TRANSPORT = "httpx-direct-tls-no-env-v1"
_SAFE_ERROR_CODES = frozenset(
    {
        "artifact_path_invalid",
        "artifact_write_failed",
        "config_invalid",
        "dataset_too_large",
        "dataset_unreadable",
        "profile_invalid",
    }
)


class ManagedPreflightCliError(RuntimeError):
    """Secret-safe composition failure."""

    def __init__(self, code: str) -> None:
        self.code = code if code in _SAFE_ERROR_CODES else "config_invalid"
        super().__init__("managed comparison static preflight failed")


@final
@dataclass(frozen=True, slots=True)
class ManagedPreflightCliConfig:
    dataset_path: Path
    profile_id: str
    infinity_api_url: str
    mem0_api_url: str
    infinity_auth_token_env: str = "MEMORY_EVAL_AUTH_TOKEN"
    mem0_api_key_env: str = "MEM0_API_KEY"
    openai_api_key_env: str = "MEMORY_OPENAI_API_KEY"
    report_out: Path | None = None
    connect_timeout_seconds: float = 10.0
    request_timeout_seconds: float = 120.0
    run_timeout_seconds: float = 86_400.0

    def __post_init__(self) -> None:
        if (
            not isinstance(self.dataset_path, Path)
            or type(self.profile_id) is not str
            or type(self.infinity_api_url) is not str
            or type(self.mem0_api_url) is not str
            or (self.report_out is not None and not isinstance(self.report_out, Path))
        ):
            raise ManagedPreflightCliError("config_invalid")
        for name in (
            self.infinity_auth_token_env,
            self.mem0_api_key_env,
            self.openai_api_key_env,
        ):
            if type(name) is not str or _ENV_NAME.fullmatch(name) is None:
                raise ManagedPreflightCliError("config_invalid")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedPreflightCliConfig is final")


def run_managed_preflight_cli(
    config: ManagedPreflightCliConfig,
    *,
    env: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Run static checks only and optionally write a private atomic report."""

    if type(config) is not ManagedPreflightCliConfig:
        raise ManagedPreflightCliError("config_invalid")
    environment = os.environ if env is None else env
    if not isinstance(environment, Mapping):
        raise ManagedPreflightCliError("config_invalid")
    try:
        validate_artifact_paths_do_not_overwrite_dataset(
            dataset_path=config.dataset_path,
            error_factory=lambda _: ManagedPreflightCliError("artifact_path_invalid"),
            report_out=config.report_out,
        )
    except ManagedPreflightCliError as exc:
        return _failed_report(exc.code)

    try:
        report = _run_static_checks(config, environment)
    except ManagedPreflightError as exc:
        report = _failed_report(exc.code)
    except ManagedPreflightCliError as exc:
        report = _failed_report(exc.code)
    except OSError:
        report = _failed_report("dataset_unreadable")

    if config.report_out is not None:
        try:
            write_json_atomic(config.report_out, report)
        except (OSError, TypeError, ValueError) as exc:
            raise ManagedPreflightCliError("artifact_write_failed") from exc
    return report


def _run_static_checks(
    config: ManagedPreflightCliConfig,
    env: Mapping[str, str],
) -> dict[str, object]:
    profile = _profile(config.profile_id)
    methodology = full_comparison_methodology_contract(profile)
    dataset = managed_dataset_metadata_from_bytes(
        profile=profile,
        dataset_bytes=_read_dataset_bytes(config.dataset_path),
    )
    openai_credential = _credential(
        "openai",
        _secret(
            env,
            config.openai_api_key_env,
            fallback="OPENAI_API_KEY",
        ),
    )
    infinity_credential = _credential(
        "infinity-context",
        _secret(
            env,
            config.infinity_auth_token_env,
            fallback="MEMORY_SERVICE_TOKEN",
        ),
    )
    mem0_credential = _credential(
        "mem0",
        _secret(env, config.mem0_api_key_env),
    )
    route = _planned_provider_route(
        profile=profile,
        credential=openai_credential,
    )
    endpoints = (
        _backend_endpoint(
            role="infinity-context",
            base_url=config.infinity_api_url,
            credential=infinity_credential,
        ),
        _backend_endpoint(
            role="mem0",
            base_url=config.mem0_api_url,
            credential=mem0_credential,
        ),
    )
    policy_result = validate_managed_preflight(
        ManagedPreflightRequest(
            profile=profile,
            methodology=methodology,
            dataset=dataset,
            provider_route=route,
            answerer_model="gpt-5",
            judge_model="gpt-5",
            openai_credential=openai_credential,
            backend_endpoints=endpoints,
            timeouts=ManagedPreflightTimeouts(
                connect_seconds=config.connect_timeout_seconds,
                request_seconds=config.request_timeout_seconds,
                run_seconds=config.run_timeout_seconds,
            ),
        )
    )
    policy_payload = policy_result.public_payload()
    policy_schema_version = policy_payload.pop("schema_version")
    return {
        "suite": MANAGED_PREFLIGHT_CLI_SUITE,
        "schema_version": MANAGED_PREFLIGHT_CLI_SCHEMA_VERSION,
        "policy_schema_version": policy_schema_version,
        "ok": True,
        "status": "static_checks_passed",
        "diagnostic_only": True,
        **policy_payload,
    }


def _profile(profile_id: str) -> FullComparisonProfile:
    try:
        profile = resolve_full_comparison_profile(profile_id)
    except (TypeError, ValueError):
        profile = None
    if profile is None:
        raise ManagedPreflightCliError("profile_invalid")
    return profile


def _read_dataset_bytes(path: Path) -> bytes:
    try:
        with path.open("rb") as handle:
            payload = handle.read(MANAGED_PREFLIGHT_MAX_DATASET_BYTES + 1)
    except OSError as exc:
        raise ManagedPreflightCliError("dataset_unreadable") from exc
    if len(payload) > MANAGED_PREFLIGHT_MAX_DATASET_BYTES:
        raise ManagedPreflightCliError("dataset_too_large")
    if not payload:
        raise ManagedPreflightCliError("dataset_unreadable")
    return payload


def _secret(
    env: Mapping[str, str],
    primary: str,
    *,
    fallback: str | None = None,
) -> str | None:
    value = env.get(primary)
    if (not isinstance(value, str) or not value.strip()) and fallback is not None:
        value = env.get(fallback)
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _credential(name: str, secret: str | None) -> ManagedCredentialBinding:
    valid = (
        secret is not None
        and _GENERIC_CREDENTIAL.fullmatch(secret) is not None
        and (name != "openai" or _OPENAI_API_KEY.fullmatch(secret) is not None)
    )
    if not valid:
        return ManagedCredentialBinding(name, False, None)
    nonce = secrets.token_bytes(32)
    digest = hmac.new(
        secret.encode(),
        _CREDENTIAL_BINDING_CONTEXT + b"\0" + name.encode() + b"\0" + nonce,
        hashlib.sha256,
    ).hexdigest()
    return ManagedCredentialBinding(name, True, f"sha256:{digest}")


def _backend_endpoint(
    *,
    role: str,
    base_url: str,
    credential: ManagedCredentialBinding,
) -> ManagedBackendEndpoint:
    target = FullComparisonBackendTarget(
        backend_role=role,
        target_identity_sha256=managed_backend_target_identity_sha256(
            backend_role=role,
            base_url=base_url,
        ),
    )
    return ManagedBackendEndpoint(
        target=target,
        base_url=base_url,
        credential=credential,
    )


def _planned_provider_route(
    *,
    profile: FullComparisonProfile,
    credential: ManagedCredentialBinding,
) -> ProviderRouteAttestation:
    methodology = public_full_comparison_methodology_contract(
        full_comparison_methodology_contract(profile)
    )
    route = methodology.get("official_provider_route")
    if type(route) is not dict or credential.binding_id is None:
        raise ManagedPreflightError("credential_missing")
    origin = str(route.get("origin") or "")
    endpoint_path = str(route.get("endpoint_path") or "")
    return ProviderRouteAttestation(
        trust=str(route.get("trust") or ""),
        origin=origin,
        endpoint_path=endpoint_path,
        route_sha256=hashlib.sha256(f"{origin}{endpoint_path}".encode()).hexdigest(),
        transport_evidence=_OFFICIAL_DIRECT_TRANSPORT,
        credential_binding_id=credential.binding_id,
        request_method="POST",
        response_status=0,
    )


def _failed_report(code: str) -> dict[str, object]:
    return {
        "suite": MANAGED_PREFLIGHT_CLI_SUITE,
        "schema_version": MANAGED_PREFLIGHT_CLI_SCHEMA_VERSION,
        "ok": False,
        "status": "static_checks_failed",
        "reason_code": str(code or "config_invalid"),
        "diagnostic_only": True,
        "static_checks_passed": False,
        "credentials_verified": False,
        "eligible": False,
        "publishable": False,
        "provider_calls_performed": False,
        "live_state_touched": False,
        "execution_authority_created": False,
        "live_success": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="infinity-context-managed-preflight",
        description=(
            "Validate frozen managed-comparison inputs without provider calls "
            "or live state changes."
        ),
    )
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument(
        "--profile",
        choices=FULL_COMPARISON_PROFILES,
        required=True,
    )
    parser.add_argument("--infinity-api-url", required=True)
    parser.add_argument("--mem0-api-url", required=True)
    parser.add_argument(
        "--infinity-auth-token-env",
        default="MEMORY_EVAL_AUTH_TOKEN",
    )
    parser.add_argument("--mem0-api-key-env", default="MEM0_API_KEY")
    parser.add_argument(
        "--openai-api-key-env",
        default="MEMORY_OPENAI_API_KEY",
    )
    parser.add_argument("--report-out", type=Path, default=None)
    parser.add_argument(
        "--connect-timeout-seconds",
        type=float,
        default=10.0,
    )
    parser.add_argument(
        "--request-timeout-seconds",
        type=float,
        default=120.0,
    )
    parser.add_argument(
        "--run-timeout-seconds",
        type=float,
        default=86_400.0,
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        config = ManagedPreflightCliConfig(
            dataset_path=args.dataset,
            profile_id=str(args.profile),
            infinity_api_url=str(args.infinity_api_url),
            mem0_api_url=str(args.mem0_api_url),
            infinity_auth_token_env=str(args.infinity_auth_token_env),
            mem0_api_key_env=str(args.mem0_api_key_env),
            openai_api_key_env=str(args.openai_api_key_env),
            report_out=args.report_out,
            connect_timeout_seconds=float(args.connect_timeout_seconds),
            request_timeout_seconds=float(args.request_timeout_seconds),
            run_timeout_seconds=float(args.run_timeout_seconds),
        )
        report = run_managed_preflight_cli(config)
    except ManagedPreflightCliError as exc:
        report = _failed_report(exc.code)
    print(
        json.dumps(
            report,
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
        )
    )
    return 0 if report.get("ok") is True else 1


__all__ = (
    "MANAGED_PREFLIGHT_CLI_SCHEMA_VERSION",
    "MANAGED_PREFLIGHT_CLI_SUITE",
    "MANAGED_PREFLIGHT_MAX_DATASET_BYTES",
    "ManagedPreflightCliConfig",
    "ManagedPreflightCliError",
    "run_managed_preflight_cli",
    "main",
)


if __name__ == "__main__":
    raise SystemExit(main())

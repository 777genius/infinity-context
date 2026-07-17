"""Secret-safe LLM provider readiness checks for preflight gates."""

from __future__ import annotations

import os
import shlex
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
OPENAI_API_KEY_ENV_NAMES = ("MEMORY_OPENAI_API_KEY", "OPENAI_API_KEY")
OPENAI_API_KEY_FILE_ENV = "MEMORY_OPENAI_API_KEY_FILE"
SUBSCRIPTION_RUNTIME_PROVIDER_ENV_NAMES = (
    "MEMORY_TOP_EVIDENCE_LLM_PROVIDER",
    "MEMORY_LLM_PROVIDER",
    "MEMORY_LLM_PROVIDER_RUNTIME",
    "MEMORY_LLM_PROVIDER_BRIDGE",
    "MEMORY_SUBSCRIPTION_RUNTIME_LLM_PROVIDER",
)
SUBSCRIPTION_RUNTIME_PROVIDER_VALUES = frozenset(
    {
        "codex",
        "codex-cli",
        "codex_cli",
        "codex-subscription-runtime",
        "codex_subscription_runtime",
        "subscription",
        "subscription-runtime",
        "subscription_runtime",
    }
)
SUBSCRIPTION_RUNTIME_COMMAND_ENV_NAMES = (
    "MEMORY_LLM_PROVIDER_BRIDGE_COMMAND",
    "MEMORY_SUBSCRIPTION_RUNTIME_LLM_COMMAND",
    "MEMORY_SUBSCRIPTION_RUNTIME_COMMAND",
    "MEMORY_CODEX_COMMAND",
    "SUBSCRIPTION_RUNTIME_LLM_COMMAND",
    "SUBSCRIPTION_RUNTIME_COMMAND",
)
SUBSCRIPTION_RUNTIME_DEFAULT_COMMANDS = (
    "subscription-runtime-codex",
    "subscription-runtime-openai",
    "codex",
)


@dataclass(frozen=True)
class LlmProviderReadiness:
    ready: bool
    source: str | None
    provider_kind: str | None
    failure_code: str | None
    failure_reason: str | None
    openai_key_env_present: bool
    openai_key_file_present: bool
    subscription_runtime_configured: bool
    subscription_runtime_command_configured: bool
    subscription_runtime_command_available: bool
    subscription_runtime_provider_env_var: str | None
    subscription_runtime_command_env_var: str | None

    @property
    def openai_key_present(self) -> bool:
        return self.openai_key_env_present or self.openai_key_file_present

    def sanitized_config(self) -> dict[str, object]:
        return {
            "ready": self.ready,
            "source": self.source,
            "provider_kind": self.provider_kind,
            "failure_code": self.failure_code,
            "openai_key_env_present": self.openai_key_env_present,
            "openai_key_file_present": self.openai_key_file_present,
            "openai_key_present": self.openai_key_present,
            "subscription_runtime_configured": self.subscription_runtime_configured,
            "subscription_runtime_command_configured": (
                self.subscription_runtime_command_configured
            ),
            "subscription_runtime_command_available": (
                self.subscription_runtime_command_available
            ),
            "subscription_runtime_provider_env_var": (
                self.subscription_runtime_provider_env_var
            ),
            "subscription_runtime_command_env_var": (
                self.subscription_runtime_command_env_var
            ),
        }


def evaluate_llm_provider_readiness(env: Mapping[str, str]) -> LlmProviderReadiness:
    """Return provider readiness using only secret-free diagnostics."""

    openai_env_var = _first_set_env_name(env, OPENAI_API_KEY_ENV_NAMES)
    openai_key_file_present = _api_key_file_present(env)
    provider_env_var = _subscription_runtime_provider_env_var(env)
    command_env_var = _first_set_env_name(env, SUBSCRIPTION_RUNTIME_COMMAND_ENV_NAMES)
    command_available = _subscription_runtime_command_available(
        env,
        command_env_var=command_env_var,
    )
    subscription_configured = provider_env_var is not None
    command_configured = command_env_var is not None

    if openai_env_var is not None:
        return LlmProviderReadiness(
            ready=True,
            source="openai_api_key_env",
            provider_kind="openai",
            failure_code=None,
            failure_reason=None,
            openai_key_env_present=True,
            openai_key_file_present=openai_key_file_present,
            subscription_runtime_configured=subscription_configured,
            subscription_runtime_command_configured=command_configured,
            subscription_runtime_command_available=command_available,
            subscription_runtime_provider_env_var=provider_env_var,
            subscription_runtime_command_env_var=command_env_var,
        )
    if openai_key_file_present:
        return LlmProviderReadiness(
            ready=True,
            source="openai_api_key_file",
            provider_kind="openai",
            failure_code=None,
            failure_reason=None,
            openai_key_env_present=False,
            openai_key_file_present=True,
            subscription_runtime_configured=subscription_configured,
            subscription_runtime_command_configured=command_configured,
            subscription_runtime_command_available=command_available,
            subscription_runtime_provider_env_var=provider_env_var,
            subscription_runtime_command_env_var=command_env_var,
        )
    if subscription_configured and command_available:
        return LlmProviderReadiness(
            ready=True,
            source="subscription_runtime_bridge",
            provider_kind="subscription-runtime",
            failure_code=None,
            failure_reason=None,
            openai_key_env_present=False,
            openai_key_file_present=False,
            subscription_runtime_configured=True,
            subscription_runtime_command_configured=command_configured,
            subscription_runtime_command_available=True,
            subscription_runtime_provider_env_var=provider_env_var,
            subscription_runtime_command_env_var=command_env_var,
        )

    failure_code = (
        "subscription_runtime_bridge_missing_command"
        if subscription_configured
        else "llm_provider_missing"
    )
    if command_available and not subscription_configured:
        failure_code = "subscription_runtime_bridge_not_selected"
    return LlmProviderReadiness(
        ready=False,
        source=None,
        provider_kind=None,
        failure_code=failure_code,
        failure_reason=_provider_failure_reason(failure_code),
        openai_key_env_present=False,
        openai_key_file_present=openai_key_file_present,
        subscription_runtime_configured=subscription_configured,
        subscription_runtime_command_configured=command_configured,
        subscription_runtime_command_available=command_available,
        subscription_runtime_provider_env_var=provider_env_var,
        subscription_runtime_command_env_var=command_env_var,
    )


def _provider_failure_reason(failure_code: str) -> str:
    if failure_code == "subscription_runtime_bridge_missing_command":
        return (
            "Subscription-runtime LLM provider is selected, but no bridge command "
            "is executable; set MEMORY_LLM_PROVIDER_BRIDGE_COMMAND or "
            "MEMORY_SUBSCRIPTION_RUNTIME_LLM_COMMAND to a non-secret executable"
        )
    if failure_code == "subscription_runtime_bridge_not_selected":
        return (
            "Subscription-runtime LLM bridge command is available, but the provider "
            "is not selected; set MEMORY_LLM_PROVIDER=subscription-runtime"
        )
    return (
        "Configure LLM readiness with MEMORY_OPENAI_API_KEY, OPENAI_API_KEY, "
        "MEMORY_OPENAI_API_KEY_FILE, or a subscription-runtime bridge using "
        "MEMORY_LLM_PROVIDER=subscription-runtime plus "
        "MEMORY_LLM_PROVIDER_BRIDGE_COMMAND"
    )


def _subscription_runtime_provider_env_var(env: Mapping[str, str]) -> str | None:
    for name in SUBSCRIPTION_RUNTIME_PROVIDER_ENV_NAMES:
        value = _normalized_provider_value(env.get(name, ""))
        if value in SUBSCRIPTION_RUNTIME_PROVIDER_VALUES:
            return name
    if _bool_env(env, "MEMORY_SUBSCRIPTION_RUNTIME_LLM_ENABLED"):
        return "MEMORY_SUBSCRIPTION_RUNTIME_LLM_ENABLED"
    return None


def _subscription_runtime_command_available(
    env: Mapping[str, str],
    *,
    command_env_var: str | None,
) -> bool:
    if command_env_var is not None:
        return _executable_available(env.get(command_env_var, ""), env=env)
    return any(
        _executable_available(command, env=env)
        for command in SUBSCRIPTION_RUNTIME_DEFAULT_COMMANDS
    )


def _executable_available(command: str, *, env: Mapping[str, str]) -> bool:
    executable = _command_executable(command)
    if not executable:
        return False
    if _has_path_separator(executable):
        path = Path(executable).expanduser()
        return path.is_file() and os.access(path, os.X_OK)
    return shutil.which(executable, path=env.get("PATH", "")) is not None


def _command_executable(command: str) -> str:
    text = str(command or "").strip()
    if not text:
        return ""
    try:
        parts = shlex.split(text)
    except ValueError:
        return ""
    return parts[0] if parts else ""


def _has_path_separator(value: str) -> bool:
    return "/" in value or "\\" in value


def _first_set_env_name(env: Mapping[str, str], names: tuple[str, ...]) -> str | None:
    for name in names:
        if env.get(name, "").strip():
            return name
    return None


def _api_key_file_present(env: Mapping[str, str]) -> bool:
    value = env.get(OPENAI_API_KEY_FILE_ENV, "").strip()
    if not value:
        return False
    path = Path(value).expanduser()
    try:
        return path.is_file() and bool(path.read_text(encoding="utf-8").strip())
    except OSError:
        return False


def _normalized_provider_value(value: str) -> str:
    return str(value or "").strip().lower()


def _bool_env(env: Mapping[str, str], name: str) -> bool:
    return env.get(name, "").strip().lower() in TRUE_VALUES

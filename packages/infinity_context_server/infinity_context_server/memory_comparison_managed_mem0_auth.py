"""Closed data-plane auth policy for managed Mem0 benchmark lanes."""

from __future__ import annotations

MANAGED_MEM0_DATA_PLANE_AUTH_NONE = "none"
MANAGED_MEM0_DATA_PLANE_AUTH_API_KEY = "api_key"
MANAGED_MEM0_RUNTIME_MODE_OSS = "oss"
MANAGED_MEM0_RUNTIME_MODE_PLATFORM = "managed_platform"
MANAGED_MEM0_DATA_PLANE_AUTH_MODES = frozenset(
    {
        MANAGED_MEM0_DATA_PLANE_AUTH_NONE,
        MANAGED_MEM0_DATA_PLANE_AUTH_API_KEY,
    }
)
MANAGED_MEM0_RUNTIME_MODES = frozenset(
    {
        MANAGED_MEM0_RUNTIME_MODE_OSS,
        MANAGED_MEM0_RUNTIME_MODE_PLATFORM,
    }
)


def managed_mem0_data_plane_auth_mode(value: object) -> str:
    """Accept only the two explicit data-plane auth modes."""

    if type(value) is not str or value not in MANAGED_MEM0_DATA_PLANE_AUTH_MODES:
        raise ValueError("managed Mem0 data-plane auth mode is invalid")
    return value


def managed_mem0_runtime_mode(value: object) -> str:
    """Accept only runtime modes with a safe public attestation representation."""

    if type(value) is not str or value not in MANAGED_MEM0_RUNTIME_MODES:
        raise ValueError("managed Mem0 runtime mode is invalid")
    return value


def expected_managed_mem0_runtime_mode(
    *,
    data_plane_auth_mode: object,
    profile_runtime_mode: object,
) -> str:
    """Derive the runtime witness expectation from frozen composition inputs."""

    auth_mode = managed_mem0_data_plane_auth_mode(data_plane_auth_mode)
    if auth_mode == MANAGED_MEM0_DATA_PLANE_AUTH_NONE:
        return MANAGED_MEM0_RUNTIME_MODE_OSS
    profile_mode = managed_mem0_runtime_mode(profile_runtime_mode)
    if profile_mode != MANAGED_MEM0_RUNTIME_MODE_PLATFORM:
        raise ValueError("managed Platform profile runtime mode is invalid")
    return profile_mode


__all__ = (
    "MANAGED_MEM0_DATA_PLANE_AUTH_API_KEY",
    "MANAGED_MEM0_DATA_PLANE_AUTH_MODES",
    "MANAGED_MEM0_DATA_PLANE_AUTH_NONE",
    "MANAGED_MEM0_RUNTIME_MODE_OSS",
    "MANAGED_MEM0_RUNTIME_MODE_PLATFORM",
    "MANAGED_MEM0_RUNTIME_MODES",
    "expected_managed_mem0_runtime_mode",
    "managed_mem0_data_plane_auth_mode",
    "managed_mem0_runtime_mode",
)

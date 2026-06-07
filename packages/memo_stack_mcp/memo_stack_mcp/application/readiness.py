"""Readiness helpers for the MCP application service."""

from __future__ import annotations

from typing import Any

from memo_stack_mcp.domain.models import MemoryGatewayError, public_error_code, safe_message


def build_readiness(
    *,
    health: dict[str, Any] | None,
    health_error: MemoryGatewayError | None,
    capabilities: dict[str, Any] | None,
    capabilities_error: MemoryGatewayError | None,
    writes_enabled: bool,
    deletes_enabled: bool,
) -> dict[str, Any]:
    api_reachable = health_error is None and bool(health)
    capabilities_available = capabilities_error is None and bool(capabilities)
    projection_ready, projection_reasons = _projection_readiness(capabilities)
    degraded_reasons: list[str] = []
    if not api_reachable:
        degraded_reasons.append("api.unreachable")
    if not capabilities_available:
        degraded_reasons.append("capabilities.unavailable")
    degraded_reasons.extend(projection_reasons)
    read_ready = api_reachable and capabilities_available
    return {
        "api_reachable": api_reachable,
        "read_ready": read_ready,
        "write_ready": read_ready and writes_enabled,
        "delete_ready": read_ready and deletes_enabled,
        "projection_ready": projection_ready,
        "degraded": bool(degraded_reasons),
        "degraded_reasons": degraded_reasons,
        "checked_endpoints": ["/v1/health", "/v1/capabilities"],
    }


def safe_gateway_error(error: MemoryGatewayError | None) -> dict[str, Any] | None:
    if error is None:
        return None
    return {
        "status_code": error.status_code,
        "code": public_error_code(error.code, status_code=error.status_code),
        "message": safe_message(error.message),
        "retryable": error.retryable,
    }


def _projection_readiness(capabilities: dict[str, Any] | None) -> tuple[bool, list[str]]:
    if not capabilities:
        return False, ["projection.unknown"]
    capability_items = capabilities.get("capabilities", [])
    if not isinstance(capability_items, list) or not capability_items:
        return False, ["projection.unknown"]
    reasons: list[str] = []
    for item in capability_items:
        if not isinstance(item, dict):
            reasons.append("projection.invalid_capability")
            continue
        status = str(item.get("status") or "")
        healthy = bool(item.get("healthy", status == "ok"))
        enabled = bool(item.get("enabled", True))
        name = str(item.get("adapter_name") or item.get("capability") or "adapter")
        if not enabled:
            reasons.append(f"{name}.disabled")
        elif not healthy or status not in {"ok", "healthy"}:
            reasons.append(f"{name}.degraded")
    return not reasons, reasons

"""Health response public contract DTOs."""

from __future__ import annotations

from dataclasses import dataclass

from ._json import JsonObject


@dataclass(frozen=True, slots=True)
class HealthResponseDto:
    """Public `/v1/health` response fields."""

    status: str
    service: str
    deploy_profile: str

    def to_dict(self) -> JsonObject:
        return {
            "status": self.status,
            "service": self.service,
            "deploy_profile": self.deploy_profile,
        }

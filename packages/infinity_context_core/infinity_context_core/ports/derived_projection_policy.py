"""Immutable policy for derived projection evidence lanes."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import final

DERIVED_NOT_PROJECTED_POLICY_SCHEMA_VERSION = "derived-projection-not-projected-policy.v1"
_LANE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class DerivedProjectionLanePolicyError(ValueError):
    """Raised when an immutable derived-lane disposition is malformed."""


@final
@dataclass(frozen=True, slots=True)
class DerivedProjectionLaneDisposition:
    """One immutable disposition for an arbitrary derived-projection lane."""

    lane: str
    disposition: str
    policy_sha256: str | None

    def __post_init__(self) -> None:
        if type(self.lane) is not str or _LANE.fullmatch(self.lane) is None:
            raise DerivedProjectionLanePolicyError("derived_lane_policy_lane_invalid")
        if self.disposition == "projected":
            if self.policy_sha256 is not None:
                raise DerivedProjectionLanePolicyError("derived_lane_policy_projected_invalid")
            return
        if (
            self.disposition != "not_projected"
            or type(self.policy_sha256) is not str
            or _SHA256.fullmatch(self.policy_sha256) is None
            or self.policy_sha256 != derived_not_projected_policy_sha256(self.lane)
        ):
            raise DerivedProjectionLanePolicyError("derived_lane_policy_not_projected_invalid")

    @property
    def is_not_projected(self) -> bool:
        return self.disposition == "not_projected"



def derived_not_projected_policy_sha256(lane: str) -> str:
    """Return the accepted immutable disabled-lane policy digest."""

    if type(lane) is not str or _LANE.fullmatch(lane) is None:
        raise DerivedProjectionLanePolicyError("derived_lane_policy_lane_invalid")
    encoded = json.dumps(
        {
            "disposition": "not_projected",
            "lane": lane,
            "schema_version": DERIVED_NOT_PROJECTED_POLICY_SCHEMA_VERSION,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


__all__ = (
    "DERIVED_NOT_PROJECTED_POLICY_SCHEMA_VERSION",
    "DerivedProjectionLaneDisposition",
    "DerivedProjectionLanePolicyError",
    "derived_not_projected_policy_sha256",
)

"""Feature metadata for code_identity."""

from dataclasses import dataclass

FEATURE_ID = "code_identity"


@dataclass(frozen=True, slots=True)
class CodeIdentityFeature:
    feature_id: str = FEATURE_ID


__all__ = ("FEATURE_ID", "CodeIdentityFeature")

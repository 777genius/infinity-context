"""Provider-neutral backend target primitives for full comparisons."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import final

from infinity_context_server.public_benchmark_models import BenchmarkValidationError

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")


class FullComparisonEvidenceError(BenchmarkValidationError):
    """Raised when full-comparison evidence primitives are invalid."""


@final
@dataclass(frozen=True, slots=True)
class FullComparisonBackendTarget:
    """One ordered backend role and its sanitized target commitment."""

    backend_role: str
    target_identity_sha256: str

    def __post_init__(self) -> None:
        if type(self.backend_role) is not str or not _ID_RE.fullmatch(self.backend_role):
            raise FullComparisonEvidenceError("backend role is invalid")
        if (
            type(self.target_identity_sha256) is not str
            or _SHA256_RE.fullmatch(self.target_identity_sha256) is None
        ):
            raise FullComparisonEvidenceError("backend target identity must be SHA-256")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("FullComparisonBackendTarget is final")


__all__ = ("FullComparisonBackendTarget", "FullComparisonEvidenceError")

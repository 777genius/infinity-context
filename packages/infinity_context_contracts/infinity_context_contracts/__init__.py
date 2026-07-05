"""Stable contracts for Infinity Context feature-sliced boundaries."""

from .capabilities import CapabilitiesResponseDto
from .common import ErrorDto, ErrorResponseDto, ResponseEnvelopeDto
from .health import HealthResponseDto

__all__ = [
    "CapabilitiesResponseDto",
    "ErrorDto",
    "ErrorResponseDto",
    "HealthResponseDto",
    "ResponseEnvelopeDto",
    "__version__",
]

__version__ = "0.1.0"

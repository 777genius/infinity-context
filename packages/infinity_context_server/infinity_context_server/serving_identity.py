"""Compatibility exports for serving attestation."""

from infinity_context_server.build_identity import (
    installed_distribution_digest,
    verify_installed_build_identity,
    write_installed_build_identity,
)
from infinity_context_server.serving_profile import (
    VerifiedServingProfile,
    build_verified_serving_profile,
)

__all__ = [
    "VerifiedServingProfile",
    "build_verified_serving_profile",
    "installed_distribution_digest",
    "verify_installed_build_identity",
    "write_installed_build_identity",
]

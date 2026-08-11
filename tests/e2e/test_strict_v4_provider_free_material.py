from __future__ import annotations

from datetime import UTC, datetime, timedelta

from infinity_context_core.features.projection_receipts import ProjectionReceiptAuthenticator
from infinity_context_core.features.projection_receipts.strict_v4_preparation import (
    authenticate_strict_v4_preparation_receipt,
)
from infinity_context_core.features.projection_receipts.strict_v4_writer_authority import (
    authenticate_strict_v4_writer_authority,
)
from strict_v4_provider_free_material import build_provider_free_strict_v4_material


def test_provider_free_strict_v4_material_is_fully_authenticated() -> None:
    authenticator = ProjectionReceiptAuthenticator(b"provider-free-material-test" * 2)
    registered_at = datetime(2026, 8, 11, tzinfo=UTC)
    material = build_provider_free_strict_v4_material(
        run_id_sha256="b" * 64,
        space_id=f"benchmark-space-{'1' * 48}",
        space_slug="provider-free-material",
        authenticator=authenticator,
        registered_at=registered_at,
        prepared_at=registered_at,
        sealed_at=registered_at + timedelta(seconds=1),
    )

    authenticate_strict_v4_preparation_receipt(
        material.receipt,
        authenticator=authenticator,
    )
    authenticate_strict_v4_writer_authority(
        material.authority,
        expected_receipt=material.receipt,
        authenticator=authenticator,
    )
    assert material.receipt.provider_calls == material.authority.provider_calls == 0
    assert material.receipt.paid_go_ready is material.authority.paid_go_ready is False

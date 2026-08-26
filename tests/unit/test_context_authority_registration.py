from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from infinity_context_core.features.projection_receipts import (
    ContextAuthorityRegistration,
    ProjectionReceiptAuthenticator,
    ProjectionReceiptError,
    context_authority_registration_sha256,
    register_context_authority_and_readback,
)
from test_projection_result_receipts import V3_AUTHORITY, V3_CONTEXT

WHEN = datetime(2026, 8, 9, tzinfo=UTC)
AUTHENTICATOR = ProjectionReceiptAuthenticator(b"v" * 32)


class _Port:
    def __init__(self, transform=lambda value: value) -> None:
        self._transform = transform
        self.calls = 0

    async def register_and_readback(self, **values):
        self.calls += 1
        result = ContextAuthorityRegistration(
            context=values["context"],
            authority=values["authority"],
            registration_sha256=values["registration_sha256"],
            registration_mac_sha256=values["registration_mac_sha256"],
            registered_at=values["registered_at"],
            created=self.calls == 1,
        )
        return self._transform(result)


def _register(port: _Port):
    return register_context_authority_and_readback(
        port,
        context=V3_CONTEXT,
        authority=V3_AUTHORITY,
        authenticator=AUTHENTICATOR,
        registered_at=WHEN,
    )


def test_exact_registration_and_authenticated_replay() -> None:
    async def scenario() -> None:
        port = _Port()
        created = await _register(port)
        replayed = await _register(port)
        assert created.created is True
        assert replayed.created is False
        assert created.registration_sha256 == context_authority_registration_sha256(
            V3_CONTEXT, V3_AUTHORITY
        )
        assert created.context.payload() == V3_CONTEXT.payload()
        assert created.authority.payload() == V3_AUTHORITY.payload()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("transform", "diagnostic"),
    (
        (lambda value: replace(value, registration_sha256="0" * 64), "context_authority_invalid"),
        (
            lambda value: replace(value, registration_mac_sha256="0" * 64),
            "context_authority_invalid",
        ),
        (lambda _value: None, "context_authority_missing"),
    ),
)
def test_divergent_tampered_and_missing_readback_fail_closed(transform, diagnostic) -> None:
    async def scenario() -> None:
        with pytest.raises(ProjectionReceiptError, match=diagnostic):
            await _register(_Port(transform))

    asyncio.run(scenario())


def test_port_collision_propagates_without_second_mutation() -> None:
    class _CollisionPort:
        async def register_and_readback(self, **_values):
            raise ProjectionReceiptError("projection_receipt.context_authority_collision")

    async def scenario() -> None:
        with pytest.raises(ProjectionReceiptError, match="context_authority_collision"):
            await _register(_CollisionPort())

    asyncio.run(scenario())

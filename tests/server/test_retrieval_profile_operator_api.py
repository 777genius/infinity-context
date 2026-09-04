from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from infinity_context_core.features.context_building.public import (
    ProfileActivationDecision,
    ProfileAttestationCheckpoint,
    RetrievalProfileIdentity,
)
from infinity_context_server.api.auth import require_strict_admin_service_token
from infinity_context_server.api.dependencies import get_container
from infinity_context_server.api.v1.retrieval_profiles import (
    RetrievalProfileOperationRequest,
    _result,
    router,
)
from infinity_context_server.retrieval_profile_composition import _bounded_qdrant_attestation


def test_operator_profile_path_is_strict_admin_authenticated() -> None:
    app, _ = _app()

    async def deny():
        raise HTTPException(status_code=401, detail="strict admin token required")

    app.dependency_overrides[require_strict_admin_service_token] = deny
    response = TestClient(app).post(
        "/v1/internal/retrieval-profiles/operations",
        json=_create_request(),
    )
    assert response.status_code == 401


def test_operator_qualification_output_binds_runtime_trust_provenance() -> None:
    provenance = {
        "supervisor_key_id": "deployment-key",
        "supervisor_trust_registry_generation": 41,
        "supervisor_trust_root_sha256": "a" * 64,
    }
    lifecycle = SimpleNamespace(runtime_trust_provenance=lambda: provenance)
    result = _result(
        RetrievalProfileOperationRequest(
            operation="attest", idempotency_key="qualification", profile_id="profile-a"
        ),
        "complete",
        lifecycle,
    )
    assert result["runtime_trust_provenance"] == provenance


def test_operator_create_replay_and_attestation_use_bounded_existing_use_cases() -> None:
    app, lifecycle = _app()
    app.dependency_overrides[require_strict_admin_service_token] = lambda: None
    client = TestClient(app)

    first = client.post("/v1/internal/retrieval-profiles/operations", json=_create_request())
    replay = client.post("/v1/internal/retrieval-profiles/operations", json=_create_request())
    attest = client.post(
        "/v1/internal/retrieval-profiles/operations",
        json={
            "operation": "attest",
            "idempotency_key": "operator-2",
            "profile_id": "profile-a",
        },
    )

    assert first.status_code == replay.status_code == attest.status_code == 200
    assert first.json() == replay.json()
    assert len(lifecycle.created) == 1
    assert lifecycle.attested[0][0] == "profile-a"
    assert len(lifecycle.attested[0][1]) == 64


def test_every_operator_phase_replays_lost_response_without_advancing() -> None:
    app, lifecycle = _app()
    app.dependency_overrides[require_strict_admin_service_token] = lambda: None
    client = TestClient(app)
    requests = (
        _create_request(),
        {
            "operation": "rebuild",
            "idempotency_key": "operator-rebuild",
            "profile_id": "profile-a",
        },
        {
            "operation": "attest",
            "idempotency_key": "operator-attest",
            "profile_id": "profile-a",
        },
        {
            "operation": "activate",
            "idempotency_key": "operator-activate",
            "profile_id": "profile-a",
        },
    )

    for request in requests:
        lost = client.post("/v1/internal/retrieval-profiles/operations", json=request)
        replay = client.post("/v1/internal/retrieval-profiles/operations", json=request)
        assert lost.status_code == replay.status_code == 200
        assert lost.json() == replay.json()

    assert len(lifecycle.created) == 1
    assert lifecycle.rebuilt == 1
    assert len(lifecycle.attested) == 1
    assert len(lifecycle.activated) == 1
    assert lifecycle.activated[0][1].startswith("operator-")
    assert len(lifecycle.activated[0][1]) == 73


def test_operator_same_key_different_canonical_request_conflicts() -> None:
    app, _ = _app()
    app.dependency_overrides[require_strict_admin_service_token] = lambda: None
    client = TestClient(app)
    assert (
        client.post(
            "/v1/internal/retrieval-profiles/operations", json=_create_request()
        ).status_code
        == 200
    )
    changed = {**_create_request(), "collection_name": "collection_other"}

    response = client.post("/v1/internal/retrieval-profiles/operations", json=changed)

    assert response.status_code == 409
    assert response.json()["detail"] == "retrieval_profile_idempotency_conflict"


def test_operator_recovery_requires_exact_strict_identity_and_provider_proof() -> None:
    app, lifecycle = _app()
    app.dependency_overrides[require_strict_admin_service_token] = lambda: None
    client = TestClient(app)
    reader = {
        "fence_kind": "reader",
        "profile_id": "profile-a",
        "operation_id": "query-a",
        "owner_instance_id": "runtime-a",
        "owner_generation": "generation-a",
        "stale_deadline": "2026-08-25T00:00:00Z",
        "reason": "runtime was externally confirmed absent",
        "idempotency_key": "recover-reader-a",
        "activation_lease_id": "lease-a",
        "maintenance_generation": 3,
    }
    response = client.post("/v1/internal/retrieval-profiles/recoveries", json=reader)
    assert response.status_code == 200
    assert lifecycle.registry.recoveries[0]["activation_lease_id"] == "lease-a"

    assert client.post(
        "/v1/internal/retrieval-profiles/recoveries", json={**reader, "unknown": True}
    ).status_code == 422
    provider = {
        **reader,
        "fence_kind": "provider_mutation",
        "idempotency_key": "recover-provider-a",
        "activation_lease_id": None,
        "mutation_epoch": 7,
    }
    assert client.post(
        "/v1/internal/retrieval-profiles/recoveries", json=provider
    ).status_code == 422
    accepted = client.post(
        "/v1/internal/retrieval-profiles/recoveries",
        json={**provider, "provider_receipt_id": "qdrant-reconciliation-a"},
    )
    assert accepted.status_code == 200


def test_operator_attestation_above_16384_returns_resumable_in_progress() -> None:
    lifecycle = _LargeAttestationLifecycle(16_385)
    app, _ = _app(lifecycle)
    app.dependency_overrides[require_strict_admin_service_token] = lambda: None
    client = TestClient(app)
    request = {
        "operation": "attest",
        "idempotency_key": "large-operator-attestation",
        "profile_id": "profile-large",
    }

    phases = []
    for _ in range(10):
        response = client.post("/v1/internal/retrieval-profiles/operations", json=request)
        assert response.status_code == 200
        phases.append(response.json()["phase"])
        if phases[-1] == "in_progress" and len(phases) == 1:
            conflict = client.post(
                "/v1/internal/retrieval-profiles/operations",
                json={**request, "profile_id": "profile-other"},
            )
            assert conflict.status_code == 409
            assert conflict.json()["detail"] == "retrieval_profile_idempotency_conflict"
        if phases[-1] == "complete":
            break

    assert phases[0] == "in_progress"
    assert phases[-1] == "complete"
    assert lifecycle.registry.checkpoint.complete is True
    assert lifecycle.registry.checkpoint.item_count == 16_385
    calls = lifecycle.projection.calls
    assert client.post(
        "/v1/internal/retrieval-profiles/operations", json=request
    ).json() == response.json()
    assert lifecycle.projection.calls == calls

    activate_request = {
        "operation": "activate",
        "idempotency_key": "large-operator-activation",
        "profile_id": "profile-large",
    }
    activation_phases = []
    for _ in range(10):
        activation = client.post(
            "/v1/internal/retrieval-profiles/operations", json=activate_request
        )
        activation_phases.append(activation.json()["phase"])
        if activation_phases[-1] == "complete":
            break
    assert activation_phases[0] == "in_progress"
    assert activation_phases[-1] == "complete"


def _app(lifecycle=None):
    lifecycle = lifecycle or _Lifecycle()
    container = SimpleNamespace(
        retrieval_profile_lifecycle=lifecycle,
        clock=SimpleNamespace(now=lambda: datetime(2026, 8, 25, tzinfo=UTC)),
    )
    app = FastAPI()
    app.include_router(router, prefix="/v1")
    app.dependency_overrides[get_container] = lambda: container
    return app, lifecycle


def _create_request() -> dict[str, object]:
    return {
        "operation": "create",
        "idempotency_key": "operator-1",
        "profile_id": "profile-a",
        "generation": "generation-a",
        "profile_digest": "a" * 64,
        "collection_name": "collection_a",
    }


class _Lifecycle:
    def __init__(self):
        self.created = []
        self.attested = []
        self.activated = []
        self.rebuilt = 0
        self.registry = _Receipts()

    async def create_building(self, identity, *, now):
        self.created.append(identity)

    async def attest(self, profile_id, *, operation_id, now):
        del now
        self.attested.append((profile_id, operation_id.removeprefix("operator-")))
        return ProfileActivationDecision(True, ())

    async def activate(self, profile_id, *, operation_id, now):
        del now
        self.activated.append((profile_id, operation_id))
        return ProfileActivationDecision(True, ())

    async def rebuild_profile_page(self, profile_id, *, now):
        del now
        self.rebuilt += 1
        return SimpleNamespace(
            profile_id=profile_id,
            projected_count=3,
            complete=True,
            next_cursor=None,
        )


class _Receipts:
    def __init__(self):
        self.rows = {}
        self.reservations = {}
        self.recoveries = []

    async def recover_abandoned_fence(self, **request):
        self.recoveries.append(request)
        return {
            "outcome": "released_for_fresh_attestation",
            "idempotency_key": request["idempotency_key"],
        }

    @asynccontextmanager
    async def operator_operation_lock(self, idempotency_key):
        del idempotency_key
        yield

    async def operator_receipt(self, *, idempotency_key, request_fingerprint):
        row = self.rows.get(idempotency_key)
        if row is None:
            return None
        fingerprint, result = row
        if fingerprint != request_fingerprint:
            raise RuntimeError("retrieval_profile_idempotency_conflict")
        return dict(result)

    async def reserve_operator_operation(
        self, *, idempotency_key, request_fingerprint, operation, profile_id, **_values
    ):
        reservation = (request_fingerprint, operation, profile_id)
        existing = self.reservations.get(idempotency_key)
        if existing is not None and existing != reservation:
            raise RuntimeError("retrieval_profile_idempotency_conflict")
        self.reservations[idempotency_key] = reservation

    async def record_operator_receipt(
        self, *, idempotency_key, request_fingerprint, result, **_values
    ):
        self.rows[idempotency_key] = (request_fingerprint, dict(result))
        self.reservations.pop(idempotency_key, None)
        return dict(result)


class _LargeAttestationLifecycle:
    def __init__(self, count):
        self.registry = _AttestationReceipts()
        self.projection = _LargeProjection(count)
        self.identity = RetrievalProfileIdentity(
            "profile-large", "generation-large", "a" * 64, "collection-large"
        )

    async def attest(self, profile_id, *, operation_id, now):
        assert profile_id == self.identity.profile_id
        await _bounded_qdrant_attestation(
            self.registry,
            self.projection,
            self.identity,
            operation_id=operation_id,
            now=now,
            expected_count=16_385,
            expected_digest="b" * 64,
        )
        return ProfileActivationDecision(True, ())

    async def activate(self, profile_id, *, operation_id, now):
        return await self.attest(profile_id, operation_id=operation_id, now=now)


class _AttestationReceipts(_Receipts):
    def __init__(self):
        super().__init__()
        self.checkpoints = {}
        self.pages = {}

    @property
    def checkpoint(self):
        return tuple(self.checkpoints.values())[-1]

    async def attestation_checkpoint(self, profile_id, operation_id):
        return self.checkpoints.get(operation_id)

    async def checkpoint_attestation(self, profile_id, operation_id, **values):
        receipt = values.get("page_receipt")
        prior = self.checkpoints.get(operation_id)
        page_count = 0 if prior is None else prior.scan_page_count
        if receipt is not None:
            self.pages[(operation_id, receipt.page_number)] = receipt
            page_count += 1
        self.checkpoints[operation_id] = ProfileAttestationCheckpoint(
            values["cursor"],
            values["item_count"],
            values["digest_accumulator"],
            values["complete"],
            values.get("scan_complete", False),
            page_count,
            values.get("validation_cursor"),
            values.get("validation_page_number", 0),
            values.get("validation_item_count", 0),
            values.get("validation_accumulator", "0" * 64),
            values.get("provider_epoch", 0),
        )

    async def attestation_page_receipt(self, profile_id, operation_id, page_number):
        return self.pages.get((operation_id, page_number))


class _LargeProjection:
    def __init__(self, count):
        self.count = count
        self.calls = 0

    async def attestation_epoch(self, identity, *, now):
        del identity, now
        return 0

    async def attestation_page(self, identity, *, cursor, limit):
        del identity
        self.calls += 1
        start = 0 if cursor is None else int(cursor)
        stop = min(self.count, start + limit)
        rows = tuple(
            (f"chunk-{index:06d}", 1, hashlib.sha256(str(index).encode()).hexdigest())
            for index in range(start, stop)
        )
        return rows, None if stop == self.count else str(stop)

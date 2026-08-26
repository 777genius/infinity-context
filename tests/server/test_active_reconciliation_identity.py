from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from infinity_context_core.features.context_building.public import (
    InstalledReleaseIdentity,
    ProfileActivationDecision,
    ProfileAttestationLease,
    ProfileReconciliationOperation,
    RetrievalProfileIdentity,
    RuntimeFenceOwner,
)
from infinity_context_server.retrieval_profile_composition import (
    ProfileAwareLocatorRetrievalService,
)

NOW = datetime(2026, 8, 26, tzinfo=UTC)
EMPTY_DIGEST = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def test_active_reconciliation_binds_exact_runtime_release_and_lifecycle_identity(
    monkeypatch,
) -> None:
    owner = _owner("generation-current")
    registry = _Registry(owner)
    service = _service(owner, registry)
    observed_operations = []
    _accept_attestation(monkeypatch, observed_operations)

    result = asyncio.run(service.reconcile_active(now=NOW))

    assert result.complete is True
    assert result.renewed is True
    assert result.runtime_instance_id == owner.instance_id
    assert result.runtime_generation == owner.generation
    assert result.release_identity_sha256 == owner.installed_release.digest()
    assert result.lifecycle_identity_sha256 == owner.lifecycle_identity_sha256()
    assert registry.recorded_owner == owner
    assert registry.lease.lease_id == "reconcile-1"

    restarted_owner = _owner("generation-restarted")
    registry.registered_owner = restarted_owner
    restarted = _service(restarted_owner, registry)
    successor = asyncio.run(restarted.reconcile_active(now=NOW + timedelta(seconds=20)))
    assert successor.complete is True
    assert successor.runtime_generation == restarted_owner.generation
    assert registry.operation_ids == ["reconcile-1", "reconcile-2"]
    assert observed_operations == registry.operation_ids


def test_active_reconciliation_rejects_missing_identity_before_observation(monkeypatch) -> None:
    registry = _Registry(_owner("generation-current"))
    service = _service(None, registry)
    _accept_attestation(monkeypatch)

    with pytest.raises(RuntimeError, match="reconciliation_runtime_identity_missing"):
        asyncio.run(service.reconcile_active(now=NOW))

    assert registry.recorded_owner is None
    assert registry.lease.lease_id == "activation"
    assert registry.mutations == []


@pytest.mark.parametrize(
    ("mismatch", "reason"),
    (
        ("missing", "runtime_incarnation_missing"),
        ("generation", "runtime_generation_mismatch"),
        ("release", "runtime_release_identity_mismatch"),
        ("lifecycle", "runtime_lifecycle_identity_mismatch"),
        ("launch_token", "runtime_launch_token_reused"),
    ),
)
def test_active_reconciliation_rejects_unregistered_identity_before_any_mutation(
    monkeypatch, mismatch: str, reason: str
) -> None:
    registered = _owner("generation-current")
    other = _owner("generation-other")
    if mismatch == "missing":
        presented = _owner("generation-missing")
        registered_owner = None
    elif mismatch == "generation":
        presented = replace(
            registered,
            generation="generation-stale",
            launch_token="unrecoverable-launch-stale-generation",
        )
        registered_owner = registered
    elif mismatch == "release":
        presented = replace(
            registered,
            installed_release=InstalledReleaseIdentity(
                "1" * 40,
                "sha256:" + "1" * 64,
                "sha256:" + "2" * 64,
                "sha256:" + "3" * 64,
            ),
        )
        registered_owner = registered
    elif mismatch == "lifecycle":
        presented = replace(registered, supervisor_key_id="test-unrecoverable-stale")
        registered_owner = registered
    else:
        presented = replace(registered, launch_token=other.launch_token)
        registered_owner = registered
    registry = _Registry(registered_owner, other_owner=other)
    service = _service(presented, registry)
    observed_operations = []
    _accept_attestation(monkeypatch, observed_operations)

    with pytest.raises(RuntimeError, match=reason):
        asyncio.run(service.reconcile_active(now=NOW))

    assert registry.lease.lease_id == "activation"
    assert registry.lease.expires_at == NOW + timedelta(seconds=5)
    assert registry.mutations == []
    assert observed_operations == []


def _owner(generation: str) -> RuntimeFenceOwner:
    return RuntimeFenceOwner.unrecoverable_current(
        instance_id="provider-free-reconciliation",
        generation=generation,
        key_id="test-unrecoverable",
    )


def _service(owner, registry):
    return ProfileAwareLocatorRetrievalService(
        fallback=object(),
        registry=registry,
        projection=_Projection(),
        sessions=object(),
        query_embeddings=object(),
        runtime_owner=owner,
    )


def _accept_attestation(monkeypatch, observed_operations=None) -> None:
    async def attest(*_args, **kwargs):
        if observed_operations is not None:
            observed_operations.append(kwargs["operation_id"])
        return 0, EMPTY_DIGEST, 4

    monkeypatch.setattr(
        "infinity_context_server.retrieval_profile_composition._bounded_qdrant_attestation",
        attest,
    )
    monkeypatch.setattr(
        "infinity_context_server.retrieval_profile_composition.assess_profile_activation",
        lambda *_args, **_kwargs: ProfileActivationDecision(True, ()),
    )


class _Registry:
    identity = RetrievalProfileIdentity("profile-active", "gen-active", "a" * 64, "active")

    def __init__(
        self,
        registered_owner: RuntimeFenceOwner | None,
        *,
        other_owner: RuntimeFenceOwner | None = None,
    ):
        self.registered_owner = registered_owner
        self.other_owner = other_owner
        self.recorded_owner = None
        self.operation_ids = []
        self.mutations = []
        self.lease = ProfileAttestationLease(
            "activation", "profile-active", "gen-active", "b" * 64, NOW, NOW + timedelta(seconds=5)
        )

    async def verify_registered_runtime_owner(self, owner):
        registered = self.registered_owner
        if registered is None:
            raise RuntimeError("retrieval_profile_runtime_incarnation_missing")
        if owner.launch_token == getattr(self.other_owner, "launch_token", None):
            raise RuntimeError("retrieval_profile_runtime_launch_token_reused")
        if owner.instance_id != registered.instance_id:
            raise RuntimeError("retrieval_profile_runtime_incarnation_missing")
        if owner.generation != registered.generation:
            raise RuntimeError("retrieval_profile_runtime_generation_mismatch")
        if owner.installed_release != registered.installed_release:
            raise RuntimeError("retrieval_profile_runtime_release_identity_mismatch")
        if owner.lifecycle_identity_sha256() != registered.lifecycle_identity_sha256():
            raise RuntimeError("retrieval_profile_runtime_lifecycle_identity_mismatch")

    async def active(self):
        return self.identity

    async def active_lease(self, *, now):
        return self.lease if now < self.lease.expires_at else None

    async def reconciliation_operation(self, profile_id):
        self.mutations.append("reconciliation_operation")
        operation_id = f"reconcile-{len(self.operation_ids) + 1}"
        self.operation_ids.append(operation_id)
        return ProfileReconciliationOperation(
            operation_id,
            profile_id,
            self.lease.lease_id,
            self.identity.generation,
            self.lease.evidence_digest,
            self.lease.issued_at,
            self.lease.expires_at,
            False,
        )

    async def coverage(self, profile_id):
        return SimpleNamespace(expected_count=0, expected_digest="e" * 64)

    async def update_lane(self, *_args, **_kwargs):
        self.mutations.append("update_lane")
        return None

    async def activation_evidence(self, profile_id, *, now):
        return SimpleNamespace()

    async def record_reconciliation(
        self,
        profile_id,
        evidence,
        *,
        operation,
        runtime_owner,
        now,
        expires_at,
        drifted,
        mutation_epoch,
    ):
        del profile_id, evidence, drifted
        if runtime_owner != self.registered_owner:
            raise RuntimeError("retrieval_profile_runtime_identity_mismatch")
        assert mutation_epoch == 4
        self.mutations.append("record_reconciliation")
        self.recorded_owner = runtime_owner
        self.lease = ProfileAttestationLease(
            operation.operation_id, "profile-active", "gen-active", "b" * 64, now, expires_at
        )


class _Projection:
    def adapter_for(self, identity):
        return self

    async def capabilities(self):
        return SimpleNamespace(
            enabled=True, healthy=True, supports_search=True, supports_filters=True
        )

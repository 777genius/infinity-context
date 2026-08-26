"""Real PostgreSQL interleavings for explicit abandoned-fence recovery."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from infinity_context_adapters.postgres import (
    RuntimeProcessSupervisor,
    build_async_engine,
    build_session_factory,
    registry_document,
    upgrade_schema,
)
from infinity_context_adapters.postgres.locator_profile_lifecycle import (
    PostgresRetrievalProfileRegistry,
)
from infinity_context_adapters.postgres.supervisor_trust import SupervisorTrustRegistry
from infinity_context_adapters.qdrant.profile_lifecycle import QdrantRetrievalProfileProjection
from infinity_context_core.features.context_building.public import (
    InstalledReleaseIdentity,
    RetrievalProfileIdentity,
    RuntimeFenceOwner,
)
from infinity_context_core.ports.adapters import EmbeddingResult, PortStatus
from postgres_test_database import PostgresTestDatabase
from sqlalchemy import text


def test_exact_fence_recovery_when_disposable_services_are_configured() -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    qdrant_url = os.getenv("INFINITY_SANDBOX_QDRANT_URL")
    if not database_url or not qdrant_url:
        pytest.skip("disposable PostgreSQL and Qdrant are not configured")
    asyncio.run(_assert_exact_recovery(database_url, qdrant_url))


async def _assert_exact_recovery(database_url: str, qdrant_url: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(
        database_url, prefix="locator_fence_recovery", asyncpg=asyncpg
    )
    await database.recreate()
    engine = build_async_engine(database.app_url)
    reader_process = None
    now = datetime.now(UTC)
    try:
        await upgrade_schema(engine)
        registry = PostgresRetrievalProfileRegistry(build_session_factory(engine))
        identity = RetrievalProfileIdentity(
            "profile-a", "generation-a", "a" * 64, f"recovery_{uuid4().hex}"
        )
        await registry.create_building(identity, now=now)
        async with engine.begin() as connection:
            evidence_version = int(
                await connection.scalar(
                    text("SELECT aggregate_version FROM memory_locator_profile_evidence_versions")
                )
                or 0
            )
            await connection.execute(
                text(
                    "UPDATE memory_locator_profiles SET state='active', "
                    "activation_lease_id='lease-a', activation_evidence_digest=:digest, "
                    "activation_lease_issued_at=:issued, activation_lease_expires_at=:expires, "
                    "activation_evidence_version=:version, activation_mutation_epoch=0, "
                    "reconciliation_drifted=FALSE WHERE profile_id='profile-a'"
                ),
                {
                    "digest": "b" * 64,
                    "issued": now,
                    "expires": now + timedelta(minutes=5),
                    "version": evidence_version,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO memory_locator_profile_lanes "
                    "(profile_id,lane_id,required,healthy,profile_qualified,checked_at,"
                    "observed_count,observed_digest) VALUES "
                    "('profile-a','qdrant_dense',TRUE,TRUE,TRUE,:checked,0,:digest)"
                ),
                {"checked": now, "digest": hashlib.sha256(b"").hexdigest()},
            )
            evidence_version = int(
                await connection.scalar(
                    text("SELECT aggregate_version FROM memory_locator_profile_evidence_versions")
                )
                or 0
            )
            await connection.execute(
                text(
                    "UPDATE memory_locator_profiles SET activation_evidence_version=:version, "
                    "activation_lease_expires_at=:expires, "
                    "reconciliation_drifted=FALSE WHERE profile_id='profile-a'"
                ),
                {"version": evidence_version, "expires": now + timedelta(minutes=5)},
            )

        reader_deadline = datetime.now(UTC) + timedelta(seconds=30)
        (
            reader_process,
            reader_supervisor,
            owner,
            child_result,
            reader_trust,
        ) = await _spawn_fence_writer(
            database.app_url,
            kind="reader",
            profile_id=identity.profile_id,
            operation_id="reader-abandoned",
            stale_deadline=reader_deadline,
            key_id="reader-process-supervisor",
            instance_id="runtime-a",
            generation="generation-a",
        )
        object.__setattr__(registry, "supervisor_trust", reader_trust)
        self_issued = _self_issued_current_owner(reader_trust, owner.supervisor_key_id)
        with pytest.raises(RuntimeError, match="supervisor_key_untrusted"):
            await registry.begin_profile_query(
                "hostile-self-issued-live-process",
                owner=self_issued,
                now=datetime.now(UTC),
                expires_at=datetime.now(UTC) + timedelta(seconds=10),
            )
        assert child_result["status"] == "admitted"
        assert child_result["pid"] == reader_process.pid == owner.process_pid
        with pytest.raises(TypeError):
            reader_supervisor.owner(instance_id="forged", generation="forged")  # type: ignore[call-arg]
        with pytest.raises(RuntimeError, match="runtime_process_mismatch"):
            await registry.begin_profile_query(
                "hostile-copied-child-owner",
                owner=owner,
                now=datetime.now(UTC),
                expires_at=datetime.now(UTC) + timedelta(seconds=10),
            )
        new_owner = RuntimeFenceOwner.unrecoverable_current(
            instance_id="runtime-b", generation="generation-b", key_id="test-unrecoverable"
        )
        second = await registry.begin_profile_query(
            "reader-new-owner",
            owner=new_owner,
            now=now,
            expires_at=now + timedelta(seconds=10),
        )
        maintenance_generation = await registry.begin_maintenance(
            reason="drain runtimes before exact abandoned reader recovery"
        )
        with pytest.raises(RuntimeError, match="maintenance_active"):
            await registry.begin_profile_query(
                "blocked-reader",
                owner=new_owner,
                now=now,
                expires_at=now + timedelta(seconds=10),
            )
        with pytest.raises(RuntimeError, match="maintenance_active"):
            await registry.begin_provider_mutation(
                identity.profile_id,
                "blocked-mutation",
                owner=new_owner,
                now=now,
                expires_at=now + timedelta(seconds=10),
            )
        with pytest.raises(RuntimeError, match="maintenance_active"):
            await registry.retire(identity.profile_id, now=now, maximum_retained=1)
        with pytest.raises(RuntimeError, match="maintenance_active"):
            await registry.authorize_collection_delete(identity.profile_id, now=now)
        await registry.finish_profile_query(
            identity.profile_id,
            "reader-new-owner",
            owner=new_owner,
            activation_lease_id=second.activation_lease_id or "",
        )
        await registry.acknowledge_maintenance(
            owner_instance_id=new_owner.instance_id,
            owner_generation=new_owner.generation,
            maintenance_generation=maintenance_generation,
        )
        with pytest.raises(RuntimeError, match="dead_owner_proof_required"):
            await registry.recover_abandoned_fence(
                **_reader_recovery(
                    owner,
                    reader_deadline,
                    "reader-recovery-unsealed",
                    maintenance_generation,
                )
            )
        with pytest.raises(RuntimeError, match="runtime_still_live"):
            reader_supervisor.prove_exit(maintenance_generation=maintenance_generation)
        unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
        try:
            unrelated_supervisor = RuntimeProcessSupervisor(
                key_id=owner.supervisor_key_id,
                process=unrelated,
                trust_root_sha256=owner.trust_root_sha256,
                trust_registry_generation=owner.trust_registry_generation,
                installed_release=owner.installed_release,
            )
            unrelated.terminate()
            unrelated.wait(timeout=10)
            unrelated_proof = unrelated_supervisor.prove_exit(
                maintenance_generation=maintenance_generation
            )
            with pytest.raises(RuntimeError, match="dead_proof_scope_invalid"):
                await registry.seal_dead_incarnation(
                    proof=replace(
                        unrelated_proof,
                        instance_id=owner.instance_id,
                        generation=owner.generation,
                        launch_token=owner.launch_token,
                    )
                )
        finally:
            if unrelated.poll() is None:
                unrelated.terminate()
                unrelated.wait(timeout=10)
        reader_process.terminate()
        reader_process.wait(timeout=10)
        reader_proof = reader_supervisor.prove_exit(maintenance_generation=maintenance_generation)
        with pytest.raises(RuntimeError, match="dead_proof_invalid"):
            await registry.seal_dead_incarnation(proof=replace(reader_proof, signature="A" * 88))
        for hostile in (
            replace(reader_proof, process_pid=reader_proof.process_pid + 1),
            replace(reader_proof, process_birth_identity="swapped-birth-token"),
            replace(reader_proof, executable_identity="/hostile/swapped-executable"),
            replace(reader_proof, instance_id=new_owner.instance_id),
            replace(reader_proof, proof_id="replayed-under-new-proof-id"),
        ):
            with pytest.raises(
                RuntimeError, match="(dead_proof_(scope_)?invalid|runtime_incarnation_missing)"
            ):
                await registry.seal_dead_incarnation(proof=hostile)
        proof_digest = await registry.seal_dead_incarnation(proof=reader_proof)
        assert await registry.seal_dead_incarnation(proof=reader_proof) == proof_digest
        wrong = _reader_recovery(
            owner, reader_deadline, "reader-recovery-wrong", maintenance_generation
        )
        wrong["owner_generation"] = "generation-new"
        with pytest.raises(RuntimeError, match="dead_owner_proof_required"):
            await registry.recover_abandoned_fence(**wrong)
        request = _reader_recovery(
            owner, reader_deadline, "reader-recovery-exact", maintenance_generation
        )
        receipt = await registry.recover_abandoned_fence(**request)
        assert receipt["outcome"] == "released_for_fresh_attestation"
        assert receipt["write_outcome"] == "applied"
        assert (
            receipt["launch_identity_sha256"] == hashlib.sha256(owner.launch_payload()).hexdigest()
        )
        assert receipt["release_identity_sha256"] == owner.installed_release.digest()
        assert receipt["sealed_dead_proof_id"] == reader_proof.proof_id
        assert receipt["sealed_dead_proof_sha256"] == proof_digest
        assert receipt["lifecycle_identity_sha256"] == owner.lifecycle_identity_sha256(
            sealed_proof_id=reader_proof.proof_id,
            sealed_proof_sha256=proof_digest,
        )
        replayed_receipt = await registry.recover_abandoned_fence(**request)
        assert replayed_receipt == {**receipt, "write_outcome": "idempotent_replay"}
        with pytest.raises(RuntimeError, match="recovery_idempotency_conflict"):
            await registry.recover_abandoned_fence(
                **{**request, "reason": "changed exact recovery reason"}
            )
        with pytest.raises(RuntimeError, match="query_fenced"):
            await registry.finish_profile_query(
                identity.profile_id,
                "reader-abandoned",
                owner=owner,
                activation_lease_id="lease-a",
            )

        qdrant_owner = RuntimeFenceOwner.unrecoverable_current(
            instance_id="runtime-qdrant-observer",
            generation="generation-qdrant",
            key_id="test-unrecoverable",
        )
        projection = QdrantRetrievalProfileProjection(
            qdrant_url,
            None,
            2,
            _FixedEmbedder(),
            registry,
            qdrant_owner,
        )
        await projection.prepare_profile(identity)
        mutation_deadline = datetime.now(UTC) + timedelta(minutes=5)
        (
            mutation_process,
            mutation_supervisor,
            mutation_owner,
            child_result,
            mutation_trust,
        ) = await _spawn_fence_writer(
            database.app_url,
            kind="provider_mutation",
            profile_id=identity.profile_id,
            operation_id="mutation-ambiguous",
            stale_deadline=mutation_deadline,
            key_id="mutation-process-supervisor",
            instance_id="runtime-c",
            generation="generation-c",
            additional_operation_id="mutation-ambiguous-second",
        )
        object.__setattr__(registry, "supervisor_trust", mutation_trust)
        mutation_epoch = int(child_result["mutation_epoch"])
        second_mutation_epoch = int(child_result["mutation_epochs"]["mutation-ambiguous-second"])
        provider_maintenance = await registry.begin_maintenance(
            reason="drain runtimes before ambiguous provider mutation recovery"
        )
        await registry.acknowledge_maintenance(
            owner_instance_id=new_owner.instance_id,
            owner_generation=new_owner.generation,
            maintenance_generation=provider_maintenance,
        )
        await registry.acknowledge_maintenance(
            owner_instance_id=qdrant_owner.instance_id,
            owner_generation=qdrant_owner.generation,
            maintenance_generation=provider_maintenance,
        )
        mutation_process.terminate()
        mutation_process.wait(timeout=10)
        await registry.seal_dead_incarnation(
            proof=mutation_supervisor.prove_exit(maintenance_generation=provider_maintenance)
        )
        with pytest.raises(ValueError, match="provider receipt"):
            await registry.recover_abandoned_fence(
                fence_kind="provider_mutation",
                profile_id=identity.profile_id,
                operation_id="mutation-ambiguous",
                owner_instance_id=mutation_owner.instance_id,
                owner_generation=mutation_owner.generation,
                stale_deadline=mutation_deadline,
                reason="provider outcome was independently reconciled",
                idempotency_key="mutation-recovery-missing-proof",
                mutation_epoch=mutation_epoch,
                maintenance_generation=provider_maintenance,
            )
        async with engine.connect() as connection:
            evidence_epoch = int(
                await connection.scalar(
                    text(
                        "SELECT aggregate_version FROM memory_locator_profile_evidence_versions "
                        "WHERE singleton = TRUE"
                    )
                )
                or 0
            )
        await projection.reconcile_provider_mutation(
            identity,
            receipt_id="qdrant-observation-a",
            maintenance_generation=provider_maintenance,
            evidence_epoch=evidence_epoch,
            operation_id="mutation-ambiguous",
            owner_instance_id=mutation_owner.instance_id,
            owner_generation=mutation_owner.generation,
            mutation_epoch=mutation_epoch,
            stale_deadline=mutation_deadline,
            observed_at=datetime.now(UTC),
        )
        assert not hasattr(registry, "record_provider_reconciliation_receipt")
        mutation_request = {
            "fence_kind": "provider_mutation",
            "profile_id": identity.profile_id,
            "operation_id": "mutation-ambiguous",
            "owner_instance_id": mutation_owner.instance_id,
            "owner_generation": mutation_owner.generation,
            "stale_deadline": mutation_deadline,
            "reason": "provider outcome was independently reconciled",
            "idempotency_key": "mutation-recovery-exact",
            "mutation_epoch": mutation_epoch,
            "provider_receipt_id": "qdrant-observation-a",
            "maintenance_generation": provider_maintenance,
        }
        competing_request = {
            **mutation_request,
            "idempotency_key": "mutation-recovery-competing",
        }
        raced = await asyncio.gather(
            registry.recover_abandoned_fence(**mutation_request),
            registry.recover_abandoned_fence(**competing_request),
            return_exceptions=True,
        )
        successes = [result for result in raced if isinstance(result, dict)]
        failures = [result for result in raced if isinstance(result, BaseException)]
        assert len(successes) == len(failures) == 1
        assert str(failures[0]) in {
            "retrieval_profile_provider_receipt_invalid",
            "retrieval_profile_recovery_target_changed",
            "retrieval_profile_maintenance_generation_invalid",
        }
        mutation_receipt = successes[0]
        assert mutation_receipt["outcome"] == "released_for_fresh_attestation"
        assert mutation_receipt["write_outcome"] == "applied"
        winner = (
            mutation_request
            if mutation_receipt["idempotency_key"] == mutation_request["idempotency_key"]
            else competing_request
        )
        assert await registry.recover_abandoned_fence(**winner) == {
            **mutation_receipt,
            "write_outcome": "idempotent_replay",
        }
        replayed_for_second_fence = {
            **mutation_request,
            "operation_id": "mutation-ambiguous-second",
            "mutation_epoch": second_mutation_epoch,
            "idempotency_key": "mutation-recovery-replayed-receipt",
        }
        with pytest.raises(RuntimeError, match="provider_receipt_invalid"):
            await registry.recover_abandoned_fence(**replayed_for_second_fence)

        second_evidence_epoch = await registry.maintenance_evidence_epoch(provider_maintenance)
        await projection.reconcile_provider_mutation(
            identity,
            receipt_id="qdrant-observation-b",
            maintenance_generation=provider_maintenance,
            evidence_epoch=second_evidence_epoch,
            operation_id="mutation-ambiguous-second",
            owner_instance_id=mutation_owner.instance_id,
            owner_generation=mutation_owner.generation,
            mutation_epoch=second_mutation_epoch,
            stale_deadline=mutation_deadline,
            observed_at=datetime.now(UTC),
        )
        second_receipt = await registry.recover_abandoned_fence(
            **{
                **replayed_for_second_fence,
                "provider_receipt_id": "qdrant-observation-b",
                "idempotency_key": "mutation-recovery-second-exact",
            }
        )
        assert second_receipt["outcome"] == "released_for_fresh_attestation"
        with pytest.raises(RuntimeError, match="provider_mutation_fenced"):
            await registry.finish_provider_mutation(
                identity.profile_id,
                "mutation-ambiguous",
                owner=mutation_owner,
                started_epoch=mutation_epoch,
                now=datetime.now(UTC),
            )
        async with engine.connect() as connection:
            assert (
                int(
                    await connection.scalar(
                        text("SELECT count(*) FROM memory_locator_profile_recovery_receipts")
                    )
                    or 0
                )
                == 3
            )
            row = (
                await connection.execute(
                    text(
                        "SELECT reconciliation_drifted, provider_mutation_epoch "
                        "FROM memory_locator_profiles WHERE profile_id='profile-a'"
                    )
                )
            ).one()
            assert row[0] is True and int(row[1]) > mutation_epoch
            receipt_state = (
                await connection.execute(
                    text(
                        "SELECT consumed_by_recovery_key, consumed_at FROM "
                        "memory_locator_provider_reconciliation_receipts "
                        "WHERE receipt_id='qdrant-observation-a'"
                    )
                )
            ).one()
            assert receipt_state[0] == winner["idempotency_key"]
            assert receipt_state[1] is not None
    finally:
        for process in (locals().get("reader_process"), locals().get("mutation_process")):
            if process is not None and process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
        if "identity" in locals():
            from qdrant_client import AsyncQdrantClient

            client = AsyncQdrantClient(url=qdrant_url, timeout=10, trust_env=False)
            try:
                if await client.collection_exists(identity.collection_name):
                    await client.delete_collection(identity.collection_name)
            finally:
                await client.close()
        await engine.dispose()
        await database.drop()


class _FixedEmbedder:
    async def embed_texts(self, texts):
        return EmbeddingResult(PortStatus.OK, tuple((1.0, 0.0) for _ in texts))


async def _spawn_fence_writer(
    postgres_url: str,
    *,
    kind: str,
    profile_id: str,
    operation_id: str,
    stale_deadline: datetime,
    key_id: str,
    instance_id: str,
    generation: str,
    additional_operation_id: str | None = None,
):
    root = __import__("pathlib").Path(__file__).resolve().parents[2]
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        str(root / "packages" / package)
        for package in (
            "infinity_context_adapters",
            "infinity_context_core",
            "infinity_context_contracts",
        )
    )
    process = subprocess.Popen(
        [sys.executable, "tests/e2e/runtime_fence_writer_process.py"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(root),
        env=environment,
    )
    signing_key = Ed25519PrivateKey.generate()
    public_key = (
        signing_key.public_key()
        .public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        .hex()
    )
    valid_from = datetime.now(UTC) - timedelta(minutes=1)
    valid_until = datetime.now(UTC) + timedelta(hours=1)
    _, root_sha256 = registry_document(
        registry_id=f"test-registry-{key_id}",
        generation=1,
        valid_from=valid_from,
        valid_until=valid_until,
        keys=((key_id, public_key),),
        installed_release=_release(),
    )
    trust = SupervisorTrustRegistry(
        f"test-registry-{key_id}",
        1,
        valid_from,
        valid_until,
        ((key_id, public_key),),
        _release(),
        root_sha256,
    )
    supervisor = RuntimeProcessSupervisor(
        key_id=key_id,
        process=process,
        trust_root_sha256=root_sha256,
        trust_registry_generation=1,
        installed_release=trust.installed_release,
        signing_key=signing_key,
        instance_id=instance_id,
        generation=generation,
    )
    owner = supervisor.owner()
    assert process.stdin is not None and process.stdout is not None
    process.stdin.write(
        json.dumps(
            {
                "postgres_url": postgres_url,
                "kind": kind,
                "profile_id": profile_id,
                "operation_id": operation_id,
                "operation_ids": [
                    item for item in (operation_id, additional_operation_id) if item is not None
                ],
                "stale_deadline": stale_deadline.isoformat(),
                "launch_identity": asdict(owner),
                "supervisor_trust": {
                    "registry_id": trust.registry_id,
                    "generation": trust.generation,
                    "valid_from": trust.valid_from.isoformat(),
                    "valid_until": trust.valid_until.isoformat(),
                    "keys": trust.keys,
                    "installed_release": trust.installed_release.payload(),
                    "root_sha256": trust.root_sha256,
                },
            },
            separators=(",", ":"),
        )
        + "\n"
    )
    process.stdin.flush()
    line = await asyncio.wait_for(asyncio.to_thread(process.stdout.readline), timeout=90)
    if not line:
        stderr = process.stderr.read() if process.stderr is not None else ""
        raise AssertionError(f"supervised fence writer failed: {stderr[-2000:]}")
    return process, supervisor, owner, json.loads(line), trust


def _self_issued_current_owner(trust, key_id: str) -> RuntimeFenceOwner:
    key = Ed25519PrivateKey.generate()
    pid = os.getpid()
    with open(f"/proc/{pid}/stat", encoding="utf-8") as stream:
        stat_value = stream.read()
    birth = stat_value[stat_value.rfind(")") + 2 :].split()[19]
    executable = os.path.realpath(f"/proc/{pid}/exe")
    with open(f"/proc/{pid}/exe", "rb") as stream:
        executable_sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
    values = {
        "instance_id": "hostile-self-issued-runtime",
        "generation": "hostile-self-issued-generation",
        "supervisor_key_id": key_id,
        "supervisor_public_key": key.public_key()
        .public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        .hex(),
        "trust_root_sha256": trust.root_sha256,
        "trust_registry_generation": trust.generation,
        "launch_token": "hostile-self-issued-live-launch",
        "process_pid": pid,
        "process_birth_identity": birth,
        "executable_identity": executable,
        "executable_sha256": executable_sha256,
        "installed_release": trust.installed_release,
    }
    unsigned = RuntimeFenceOwner(**values, launch_signature="")
    signature = base64.b64encode(key.sign(unsigned.launch_payload())).decode("ascii")
    return RuntimeFenceOwner(**values, launch_signature=signature)


def _reader_recovery(owner, deadline, key, maintenance_generation):
    return {
        "fence_kind": "reader",
        "profile_id": "profile-a",
        "operation_id": "reader-abandoned",
        "owner_instance_id": owner.instance_id,
        "owner_generation": owner.generation,
        "stale_deadline": deadline,
        "reason": "runtime process was externally confirmed absent",
        "idempotency_key": key,
        "activation_lease_id": "lease-a",
        "maintenance_generation": maintenance_generation,
    }


def _release() -> InstalledReleaseIdentity:
    return InstalledReleaseIdentity(
        "1" * 40,
        "sha256:" + "2" * 64,
        "sha256:" + "3" * 64,
        "sha256:" + "4" * 64,
    )

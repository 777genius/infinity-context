"""Provider-free SQLite E2E for sealed paired ingestion authority."""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import threading
from contextlib import closing
from dataclasses import asdict, fields, replace
from pathlib import Path

import pytest
from infinity_context_server.memory_comparison_ingestion_contracts import (
    IngestionMessage,
    IngestionUnit,
    IngestionUnitManifest,
    IngestionUnitMetadata,
    dataset_profile_commitment_sha256,
    ingestion_corpus_projection_sha256,
    ingestion_manifest_sha256,
    ingestion_source_audit_root_sha256,
    make_ingestion_source_audit,
    make_ingestion_unit,
    opaque_ingestion_corpus_id,
    opaque_ingestion_source_id,
)
from infinity_context_server.memory_comparison_paired_ingestion import (
    HmacPairedOperationReceiptVerifier,
    PairedIngestionCoordinator,
    PairedIngestionError,
    PairedLaneCleanupEvidence,
    PairedLaneReceipt,
    VerifiedPairedLaneCleanup,
    empty_inventory_sha256,
    make_cleanup_evidence,
    make_paired_lane_receipt,
)
from infinity_context_server.memory_comparison_paired_ingestion_authority import (
    PairedAdmissionRequest,
    PairedIngestionAuthorityError,
    PairedIngestionLane,
    PairedLaneBinding,
    PairedLaneManifestPolicy,
    VerifiedIngestionManifest,
    VerifiedPairedAdmission,
    build_paired_ingestion_authority,
    ingestion_unit_root_sha256,
)
from infinity_context_server.resumable_operation_journal import (
    HmacSha256OperationJournalSigner,
    NullOperationNotification,
    ResumableOperationJournalService,
)
from infinity_context_server.resumable_operation_journal.domain import sha256_commitment
from infinity_context_server.resumable_operation_journal.sqlite import (
    SQLiteOperationJournal,
)

_SECRET = b"paired-ingestion-test-secret-at-least-32-bytes"
_TARGET_SECRET = b"provider-free-target-authentication-key"
_ROUTE = "b" * 64
_RUN_ID = "paired-provider-free-e2e-r2"


class _ManifestVerifier:
    def __init__(self, *, forge: bool = False, revision: str = "v1") -> None:
        self.forge = forge
        self.key_id = f"manifest-verifier-{revision}"
        self._private_manifests: dict[str, IngestionUnitManifest] = {}

    def verify(self, manifest: IngestionUnitManifest) -> VerifiedIngestionManifest:
        manifest.validate()
        self._private_manifests[manifest.manifest_sha256] = manifest
        return self._proof(manifest)

    def reverify(self, projection) -> VerifiedIngestionManifest:
        manifest = self._private_manifests.get(projection.manifest_sha256)
        if manifest is None:
            raise RuntimeError("private manifest capability is missing")
        manifest.validate()
        if (
            projection.units != manifest.units
            or projection.corpus_projection_sha256 != manifest.corpus_projection_sha256
        ):
            raise RuntimeError("public projection diverged")
        return self._proof(manifest)

    def _proof(self, manifest: IngestionUnitManifest) -> VerifiedIngestionManifest:
        unit_root = ingestion_unit_root_sha256(manifest.units)
        return VerifiedIngestionManifest(
            manifest_sha256=("f" * 64 if self.forge else manifest.manifest_sha256),
            corpus_projection_sha256=manifest.corpus_projection_sha256,
            unit_root_sha256=unit_root,
            unit_count=len(manifest.units),
            verifier_key_id=self.key_id,
            verification_commitment_sha256=sha256_commitment(
                {"key_id": self.key_id, "manifest": manifest.manifest_sha256, "root": unit_root}
            ),
        )


class _AdmissionVerifier:
    def __init__(self, *, forge: bool = False, revision: str = "v1") -> None:
        self.forge = forge
        self.key_id = f"admission-verifier-{revision}"

    def verify(self, request: PairedAdmissionRequest) -> VerifiedPairedAdmission:
        verified_request = (
            replace(request, runtime_route_sha256="e" * 64) if self.forge else request
        )
        return VerifiedPairedAdmission(
            request=verified_request,
            admission_commitment_sha256=verified_request.commitment_sha256,
            verifier_key_id=self.key_id,
            verification_commitment_sha256=sha256_commitment(
                {"admission": verified_request.commitment_sha256, "key_id": self.key_id}
            ),
        )


class _SQLiteReceiptStore:
    def __init__(self, path: Path, *, explode: bool = False) -> None:
        self.path = path
        self.explode = explode
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS receipts (
                       lane TEXT NOT NULL,
                       operation_id TEXT NOT NULL,
                       payload_json TEXT NOT NULL,
                       PRIMARY KEY (lane, operation_id)
                   )"""
            )

    def load(self, *, lane, logical_operation_id):
        if self.explode:
            raise RuntimeError("sensitive-store-detail")
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT payload_json FROM receipts WHERE lane = ? AND operation_id = ?",
                (lane.value, logical_operation_id),
            ).fetchone()
        return None if row is None else _decode_receipt(row[0], "durable receipt")

    def save(self, *, lane, logical_operation_id, receipt):
        if self.explode:
            raise RuntimeError("sensitive-store-detail")
        encoded = _encode_receipt(receipt)
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT payload_json FROM receipts WHERE lane = ? AND operation_id = ?",
                (lane.value, logical_operation_id),
            ).fetchone()
            if row is not None and row[0] != encoded:
                raise RuntimeError("sensitive-divergent-receipt")
            connection.execute(
                "INSERT OR IGNORE INTO receipts VALUES (?, ?, ?)",
                (lane.value, logical_operation_id, encoded),
            )

    def tamper(self, lane: PairedIngestionLane) -> None:
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT operation_id, payload_json FROM receipts WHERE lane = ? LIMIT 1",
                (lane.value,),
            ).fetchone()
            payload = json.loads(row[1])
            payload["provider_receipt_sha256"] = "f" * 64
            connection.execute(
                "UPDATE receipts SET payload_json = ? WHERE lane = ? AND operation_id = ?",
                (_canonical(payload), lane.value, row[0]),
            )

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=5)
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection


class _SQLiteFakeLane:
    def __init__(
        self,
        lane: PairedIngestionLane,
        path: Path,
        *,
        crash_ordinal: int | None = None,
        duplicate_episode: bool = False,
        forge_cleanup: bool = False,
        dispatch_error: bool = False,
    ) -> None:
        self.lane = lane
        self.path = path
        self.crash_ordinal = crash_ordinal
        self.duplicate_episode = duplicate_episode
        self.forge_cleanup = forge_cleanup
        self.dispatch_error = dispatch_error
        self._crashed = False
        self._lock = threading.Lock()
        self.dispatch_log: list[tuple[str, int]] = []
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS target_results (
                       source_id TEXT PRIMARY KEY,
                       payload_json TEXT NOT NULL,
                       row_mac TEXT NOT NULL
                   )"""
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS counters (key TEXT PRIMARY KEY, value INTEGER NOT NULL)"
            )
            for key in ("extractions", "dispatches", "status"):
                connection.execute("INSERT OR IGNORE INTO counters VALUES (?, 0)", (key,))

    @property
    def extraction_count(self) -> int:
        return self._counter("extractions")

    @property
    def dispatch_count(self) -> int:
        return self._counter("dispatches")

    @property
    def status_count(self) -> int:
        return self._counter("status")

    def request_commitment_sha256(self, unit: IngestionUnit, *, binding: PairedLaneBinding) -> str:
        return sha256_commitment(
            {
                "binding": binding.binding_sha256,
                "payload": unit.provider_payload(),
                "unit_sha256": unit.unit_sha256,
            }
        )

    def dispatch(self, unit: IngestionUnit, *, binding: PairedLaneBinding) -> PairedLaneReceipt:
        if self.dispatch_error:
            raise RuntimeError("sensitive-adapter-detail")
        should_crash = False
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute("UPDATE counters SET value = value + 1 WHERE key = 'dispatches'")
            row = connection.execute(
                "SELECT payload_json, row_mac FROM target_results WHERE source_id = ?",
                (unit.metadata.source_id,),
            ).fetchone()
            if row is not None:
                return self._decode_authenticated(row)
            receipt = self._receipt(unit, binding)
            encoded = _encode_receipt(receipt)
            connection.execute(
                "INSERT INTO target_results VALUES (?, ?, ?)",
                (unit.metadata.source_id, encoded, _mac(encoded)),
            )
            connection.execute("UPDATE counters SET value = value + 1 WHERE key = 'extractions'")
            self.dispatch_log.append((unit.corpus_id, unit.ordinal))
            should_crash = self.crash_ordinal == unit.ordinal and not self._crashed
        if should_crash:
            self._crashed = True
            raise RuntimeError("sensitive-post-commit-crash")
        return receipt

    def status_readback(
        self, unit: IngestionUnit, *, binding: PairedLaneBinding
    ) -> PairedLaneReceipt:
        del binding
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute("UPDATE counters SET value = value + 1 WHERE key = 'status'")
            row = connection.execute(
                "SELECT payload_json, row_mac FROM target_results WHERE source_id = ?",
                (unit.metadata.source_id,),
            ).fetchone()
            if row is None:
                raise RuntimeError("sensitive-status-missing")
            return self._decode_authenticated(row)

    def cleanup(self, *, binding: PairedLaneBinding) -> PairedLaneCleanupEvidence:
        with self._lock, closing(self._connect()) as connection, connection:
            before = int(connection.execute("SELECT COUNT(*) FROM target_results").fetchone()[0])
            if not self.forge_cleanup:
                connection.execute("DELETE FROM target_results")
            count, root = _target_inventory(connection)
        claimed_count = 0 if self.forge_cleanup else count
        claimed_root = empty_inventory_sha256() if self.forge_cleanup else root
        absence = sha256_commitment(
            {
                "binding": binding.binding_sha256,
                "count": claimed_count,
                "lane": self.lane.value,
                "root": claimed_root,
            }
        )
        return make_cleanup_evidence(
            binding=binding,
            ingestion_manifest_sha256=binding.ingestion_manifest_sha256,
            deleted_record_count=before if not self.forge_cleanup else 0,
            residual_record_count=claimed_count,
            residual_root_sha256=claimed_root,
            provider_absence_receipt_sha256=absence,
        )

    def tamper_result(self, ordinal: int) -> None:
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                "SELECT source_id, payload_json, row_mac FROM target_results"
            ).fetchall()
            row = next(item for item in rows if json.loads(item[1])["ordinal"] == ordinal)
            payload = json.loads(row[1])
            payload["unit_sha256"] = "e" * 64
            encoded = _canonical(payload)
            connection.execute(
                "UPDATE target_results SET payload_json = ? WHERE source_id = ?",
                (encoded, row[0]),
            )

    def actual_inventory(self) -> tuple[int, str]:
        with closing(self._connect()) as connection, connection:
            return _target_inventory(connection)

    def _receipt(self, unit: IngestionUnit, binding: PairedLaneBinding) -> PairedLaneReceipt:
        provider_sha = sha256_commitment(
            {"lane": self.lane.value, "source": unit.metadata.source_id, "unit": unit.unit_sha256}
        )
        episode = (
            "episode_duplicate"
            if self.duplicate_episode
            else f"episode_{unit.ordinal}_{unit.unit_sha256[:12]}"
        )
        return make_paired_lane_receipt(
            lane=self.lane,
            run_id=binding.run_identity.run_id,
            ingestion_manifest_sha256=binding.ingestion_manifest_sha256,
            lane_binding_sha256=binding.binding_sha256,
            scope_commitment_sha256=binding.scope_commitment_sha256,
            ordinal=unit.ordinal,
            corpus_id=unit.corpus_id,
            source_id=unit.metadata.source_id,
            unit_sha256=unit.unit_sha256,
            request_commitment_sha256=self.request_commitment_sha256(unit, binding=binding),
            provider_receipt_sha256=provider_sha,
            scope_id=f"scope_{unit.corpus_id[-16:]}",
            episode_ids=(episode,) if self.lane is PairedIngestionLane.INFINITY else (),
            chunk_ids=(f"chunk_{unit.ordinal}_{unit.unit_sha256[:12]}",)
            if self.lane is PairedIngestionLane.INFINITY
            else (),
        )

    @staticmethod
    def _decode_authenticated(row) -> PairedLaneReceipt:
        if not hmac.compare_digest(_mac(row[0]), row[1]):
            raise RuntimeError("sensitive-target-mac-invalid")
        return _decode_receipt(row[0], "target result")

    def _counter(self, key: str) -> int:
        with closing(self._connect()) as connection, connection:
            return int(
                connection.execute("SELECT value FROM counters WHERE key = ?", (key,)).fetchone()[0]
            )

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=5)
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection


class _CleanupVerifier:
    def __init__(self, lane: _SQLiteFakeLane) -> None:
        self.lane = lane

    def verify(self, *, binding, evidence):
        count, root = self.lane.actual_inventory()
        if (
            binding.lane is not self.lane.lane
            or evidence.residual_record_count != count
            or evidence.residual_root_sha256 != root
        ):
            raise RuntimeError("sensitive-cleanup-readback-divergence")
        return VerifiedPairedLaneCleanup(
            evidence=evidence,
            verifier_key_id=f"cleanup-{self.lane.lane.value}-v1",
            verification_commitment_sha256=sha256_commitment(
                {
                    "binding": binding.binding_sha256,
                    "count": count,
                    "lane": evidence.lane.value,
                    "manifest": evidence.ingestion_manifest_sha256,
                    "provider_absence_receipt": evidence.provider_absence_receipt_sha256,
                    "root": root,
                    "run_id": evidence.run_id,
                    "scope": evidence.scope_commitment_sha256,
                }
            ),
        )


def _manifest() -> IngestionUnitManifest:
    corpora = tuple(
        opaque_ingestion_corpus_id(corpus_identity={"corpus": name}) for name in ("alpha", "beta")
    )
    units = tuple(
        make_ingestion_unit(
            ordinal=ordinal,
            corpus_id=corpora[ordinal % 2],
            message=IngestionMessage(role="user", content=f"public raw turn {ordinal}"),
            metadata=IngestionUnitMetadata(
                source_id=opaque_ingestion_source_id(source_identity={"turn": ordinal}),
                timestamp=1_700_000_000 + ordinal,
            ),
        )
        for ordinal in range(4)
    )
    audits = tuple(
        make_ingestion_source_audit(
            unit=unit,
            sample_id=f"private-sample-{unit.ordinal}",
            session_id="private-session",
            dia_id=f"D1:{unit.ordinal}",
            session_date="private-date",
            speaker="private-speaker",
            source_ref=f"private-ref-{unit.ordinal}",
        )
        for unit in units
    )
    dataset_sha, profile, policy = "d" * 64, "provider-free-test", "paired-e2e.v2"
    profile_sha = dataset_profile_commitment_sha256(dataset_sha256=dataset_sha, profile_id=profile)
    projection_sha = ingestion_corpus_projection_sha256(units, ingestion_policy_id=policy)
    audit_sha = ingestion_source_audit_root_sha256(audits)
    return IngestionUnitManifest(
        dataset_sha256=dataset_sha,
        profile_id=profile,
        ingestion_policy_id=policy,
        dataset_profile_commitment_sha256=profile_sha,
        corpus_projection_sha256=projection_sha,
        source_audit_sha256=audit_sha,
        units=units,
        source_audits=audits,
        manifest_sha256=ingestion_manifest_sha256(
            dataset_sha256=dataset_sha,
            profile_id=profile,
            ingestion_policy_id=policy,
            dataset_profile_commitment_sha256=profile_sha,
            corpus_projection_sha256=projection_sha,
            source_audit_sha256=audit_sha,
            units=units,
            source_audits=audits,
        ),
    )


def _stack(
    tmp_path: Path,
    *,
    crash_lane: PairedIngestionLane | None = None,
    duplicate_episode: bool = False,
    forge_cleanup_lane: PairedIngestionLane | None = None,
    dispatch_error_lane: PairedIngestionLane | None = None,
    store_error: bool = False,
    proof_revision: str = "v1",
):
    manifest = _manifest()
    manifest_verifier = _ManifestVerifier(revision=proof_revision)
    admission_verifier = _AdmissionVerifier(revision=proof_revision)
    signer = HmacSha256OperationJournalSigner(key_id="paired-signer-v1", secret=_SECRET)
    authority = build_paired_ingestion_authority(
        manifest,
        run_id=_RUN_ID,
        runtime_route_sha256=_ROUTE,
        signer_key_id=signer.key_id,
        manifest_verifier=manifest_verifier,
        admission_verifier=admission_verifier,
    )
    services = {}
    for lane in PairedIngestionLane:
        private = tmp_path / f"journal-{lane.value}"
        services[lane] = ResumableOperationJournalService(
            journal=SQLiteOperationJournal(private / "journal.sqlite3", private_directory=private),
            signer=signer,
            manifest_policy=PairedLaneManifestPolicy(authority.lane(lane)),
            receipt_verifier=HmacPairedOperationReceiptVerifier(signer),
            notifications=NullOperationNotification(),
        )
    infinity = _SQLiteFakeLane(
        PairedIngestionLane.INFINITY,
        tmp_path / "infinity.sqlite3",
        crash_ordinal=0 if crash_lane is PairedIngestionLane.INFINITY else None,
        duplicate_episode=duplicate_episode,
        forge_cleanup=forge_cleanup_lane is PairedIngestionLane.INFINITY,
        dispatch_error=dispatch_error_lane is PairedIngestionLane.INFINITY,
    )
    mem0 = _SQLiteFakeLane(
        PairedIngestionLane.MEM0,
        tmp_path / "mem0.sqlite3",
        crash_ordinal=0 if crash_lane is PairedIngestionLane.MEM0 else None,
        forge_cleanup=forge_cleanup_lane is PairedIngestionLane.MEM0,
        dispatch_error=dispatch_error_lane is PairedIngestionLane.MEM0,
    )
    store = _SQLiteReceiptStore(tmp_path / "receipts.sqlite3", explode=store_error)
    coordinator = PairedIngestionCoordinator(
        authority=authority,
        manifest_verifier=manifest_verifier,
        admission_verifier=admission_verifier,
        infinity_lane=infinity,
        mem0_lane=mem0,
        infinity_cleanup_verifier=_CleanupVerifier(infinity),
        mem0_cleanup_verifier=_CleanupVerifier(mem0),
        infinity_journal=services[PairedIngestionLane.INFINITY],
        mem0_journal=services[PairedIngestionLane.MEM0],
        receipt_store=store,
        signer=signer,
        max_corpus_workers=4,
    )
    return coordinator, authority, services, infinity, mem0, store


def test_happy_path_exact_inventory_order_and_authenticated_cleanup(tmp_path: Path) -> None:
    coordinator, _, services, infinity, mem0, _ = _stack(tmp_path)
    coordinator.initialize()
    result = coordinator.execute()
    assert len(result.receipts) == 8
    assert len(result.infinity_episode_ids) == len(set(result.infinity_episode_ids)) == 4
    assert len(result.infinity_chunk_ids) == len(set(result.infinity_chunk_ids)) == 4
    assert [
        (len(episodes), scope.startswith("scope_"))
        for _, scope, episodes in result.infinity_episode_ids_by_corpus
    ] == [(2, True), (2, True)]
    assert infinity.extraction_count == mem0.extraction_count == 4
    for lane in PairedIngestionLane:
        assert services[lane].snapshot(_RUN_ID).committed_count == 4
    for adapter in (infinity, mem0):
        by_corpus: dict[str, list[int]] = {}
        for corpus, ordinal in adapter.dispatch_log:
            by_corpus.setdefault(corpus, []).append(ordinal)
        assert sorted(by_corpus.values()) == [[0, 2], [1, 3]]
    first, second = coordinator.cleanup(), coordinator.cleanup()
    assert [proof.evidence.deleted_record_count for proof in first] == [4, 4]
    assert [proof.evidence.deleted_record_count for proof in second] == [0, 0]


@pytest.mark.parametrize("crash_lane", tuple(PairedIngestionLane))
def test_target_commit_then_crash_recovers_without_duplicate_extraction(
    tmp_path: Path, crash_lane: PairedIngestionLane
) -> None:
    coordinator, _, _, _, _, _ = _stack(tmp_path, crash_lane=crash_lane)
    coordinator.initialize()
    with pytest.raises(PairedIngestionError, match="paired corpus execution failed"):
        coordinator.execute()
    restarted, _, _, infinity, mem0, _ = _stack(tmp_path)
    restarted.initialize()
    restarted.resume()
    assert len(restarted.execute().receipts) == 8
    assert infinity.extraction_count == mem0.extraction_count == 4
    if crash_lane is PairedIngestionLane.INFINITY:
        assert infinity.dispatch_count == 5
        assert infinity.status_count == mem0.status_count == 0
    else:
        assert mem0.dispatch_count == 4
        assert mem0.status_count == 1
        assert infinity.status_count == 0


def test_mutated_manifest_and_forged_capabilities_fail_closed(tmp_path: Path) -> None:
    manifest = _manifest()
    signer = HmacSha256OperationJournalSigner(key_id="paired-signer-v1", secret=_SECRET)
    with pytest.raises(PairedIngestionAuthorityError):
        build_paired_ingestion_authority(
            manifest,
            run_id=_RUN_ID,
            runtime_route_sha256=_ROUTE,
            signer_key_id=signer.key_id,
            manifest_verifier=_ManifestVerifier(forge=True),
            admission_verifier=_AdmissionVerifier(),
        )
    with pytest.raises(PairedIngestionAuthorityError):
        build_paired_ingestion_authority(
            manifest,
            run_id=_RUN_ID,
            runtime_route_sha256=_ROUTE,
            signer_key_id=signer.key_id,
            manifest_verifier=_ManifestVerifier(),
            admission_verifier=_AdmissionVerifier(forge=True),
        )
    coordinator, authority, _, _, _, _ = _stack(tmp_path)
    object.__setattr__(authority.units[0], "payload_sha256", "f" * 64)
    with pytest.raises(PairedIngestionError, match="authority is invalid"):
        coordinator.initialize()


def test_private_manifest_is_capability_owned_and_proof_revision_is_durable(
    tmp_path: Path,
) -> None:
    coordinator, authority, _, _, _, _ = _stack(tmp_path, proof_revision="v1")
    coordinator.initialize()
    rendered = repr(authority) + json.dumps(asdict(authority), sort_keys=True)
    assert not hasattr(authority, "sealed_manifest")
    assert not hasattr(authority, "source_audits")
    assert "private-sample" not in rendered
    assert "private-session" not in rendered
    assert "source_audits" not in rendered

    changed, _, _, _, _, _ = _stack(tmp_path, proof_revision="v2")
    with pytest.raises(PairedIngestionError, match="journal initialization failed"):
        changed.initialize()


def test_duplicate_episode_inventory_fails_without_set_collapse(tmp_path: Path) -> None:
    coordinator, _, services, _, _, _ = _stack(tmp_path, duplicate_episode=True)
    coordinator.initialize()
    with pytest.raises(PairedIngestionError, match="globally unique"):
        coordinator.execute()
    assert all(
        services[lane].snapshot(_RUN_ID).run.phase.value == "active" for lane in PairedIngestionLane
    )
    with pytest.raises(PairedIngestionError, match="globally unique"):
        coordinator.execute()
    assert len(coordinator.cleanup()) == 2


def test_forged_cleanup_zero_is_rejected_by_independent_readback(tmp_path: Path) -> None:
    coordinator, _, _, _, _, _ = _stack(tmp_path, forge_cleanup_lane=PairedIngestionLane.MEM0)
    coordinator.initialize()
    coordinator.execute()
    with pytest.raises(PairedIngestionError, match="cleanup readback failed") as caught:
        coordinator.cleanup()
    assert "sensitive" not in str(caught.value)


def test_journal_receipt_and_target_tamper_fail_closed(tmp_path: Path) -> None:
    coordinator, _, _, _, _, store = _stack(tmp_path)
    coordinator.initialize()
    coordinator.execute()
    database = tmp_path / "journal-infinity" / "journal.sqlite3"
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute(
            "UPDATE operation_manifest SET authority_commitment_sha256 = ? WHERE ordinal = 0",
            ("f" * 64,),
        )
    with pytest.raises(PairedIngestionError, match="resume failed"):
        coordinator.resume()
    store.tamper(PairedIngestionLane.MEM0)
    restarted, _, _, _, _, _ = _stack(tmp_path)
    with pytest.raises(PairedIngestionError, match="corpus execution failed"):
        restarted.execute()


def test_authenticated_target_result_tamper_fails_status_recovery(tmp_path: Path) -> None:
    coordinator, _, _, _, _, _ = _stack(tmp_path, crash_lane=PairedIngestionLane.MEM0)
    coordinator.initialize()
    with pytest.raises(PairedIngestionError):
        coordinator.execute()
    _, _, _, _, mem0, _ = _stack(tmp_path)
    mem0.tamper_result(0)
    restarted, _, _, _, _, _ = _stack(tmp_path)
    restarted.initialize()
    restarted.resume()
    with pytest.raises(PairedIngestionError, match="corpus execution failed") as caught:
        restarted.execute()
    assert "sensitive" not in str(caught.value)


@pytest.mark.parametrize(
    ("dispatch_error_lane", "store_error"),
    ((PairedIngestionLane.INFINITY, False), (None, True)),
)
def test_adapter_and_store_secret_errors_are_sanitized(
    tmp_path: Path,
    dispatch_error_lane: PairedIngestionLane | None,
    store_error: bool,
) -> None:
    coordinator, _, _, _, _, _ = _stack(
        tmp_path, dispatch_error_lane=dispatch_error_lane, store_error=store_error
    )
    coordinator.initialize()
    with pytest.raises(PairedIngestionError) as caught:
        coordinator.execute()
    assert "sensitive" not in str(caught.value)


def _target_inventory(connection: sqlite3.Connection) -> tuple[int, str]:
    source_ids = [
        row[0]
        for row in connection.execute("SELECT source_id FROM target_results ORDER BY source_id")
    ]
    if not source_ids:
        return 0, empty_inventory_sha256()
    return len(source_ids), sha256_commitment({"records": source_ids})


def _encode_receipt(receipt: PairedLaneReceipt) -> str:
    receipt.__post_init__()
    payload = {field.name: getattr(receipt, field.name) for field in fields(receipt)}
    payload["lane"] = receipt.lane.value
    payload["episode_ids"] = list(receipt.episode_ids)
    payload["chunk_ids"] = list(receipt.chunk_ids)
    return _canonical(payload)


def _decode_receipt(raw: str, label: str) -> PairedLaneReceipt:
    del label
    try:
        payload = json.loads(raw)
        return PairedLaneReceipt(
            **{
                **payload,
                "lane": PairedIngestionLane(payload["lane"]),
                "episode_ids": tuple(payload["episode_ids"]),
                "chunk_ids": tuple(payload["chunk_ids"]),
            }
        )
    except Exception:
        raise RuntimeError("sensitive-corrupt-result") from None


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _mac(value: str) -> str:
    return hmac.new(_TARGET_SECRET, value.encode(), hashlib.sha256).hexdigest()

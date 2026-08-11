"""Installed production Mem0/Infinity dependency root for publishable runs."""

from __future__ import annotations

import hashlib
import os
import stat
import time
from dataclasses import dataclass, field
from pathlib import Path
from secrets import token_hex
from typing import final

from infinity_context_core.features.projection_receipts.strict_v4_preparation import (
    StrictV4PreparationReceipt,
)
from infinity_context_server.features.subscription_runtime_bridge import (
    Aes256GcmOutputCipher,
    BridgeJournal,
    HmacJournalIntegrity,
    OutputCipherKey,
)
from infinity_context_server.features.subscription_runtime_bridge.process_contracts import (
    BridgeFleetReadinessReceipt,
)
from infinity_context_server.memory_comparison_case_loader import (
    load_memory_comparison_cases_from_bytes,
)
from infinity_context_server.memory_comparison_locomo_cases import (
    LOCOMO_INGEST_OFFICIAL_TURNS,
)
from infinity_context_server.memory_comparison_managed_preflight import (
    managed_backend_target_identity_sha256,
)
from infinity_context_server.memory_comparison_publishable_methodology import (
    PUBLISHABLE_PRIORITY_METHODOLOGY_V4_COMMITMENT_SHA256,
)
from infinity_context_server.memory_comparison_publishable_profile import (
    public_publishable_comparison_profile,
    publishable_priority_comparison_profile_v4,
)
from infinity_context_server.public_benchmark_models import PublicBenchmarkCase
from infinity_context_server.publishable_durable_scheduler import (
    publishable_production_composition,
    retrieval_evidence_sqlite_authority,
    scheduler_subscription_bridge_adapter,
)
from infinity_context_server.publishable_durable_scheduler.contracts import (
    LOCOMO_PROFILE,
    LONGMEMEVAL_PROFILE,
    SchedulerBackendAuthority,
    SchedulerDeadlineTokenAuthority,
    SchedulerRunBinding,
    SchedulerSuiteAuthority,
)
from infinity_context_server.publishable_durable_scheduler.manifest import (
    SchedulerCaseAuthority,
    case_manifest_sha256,
)
from infinity_context_server.publishable_durable_scheduler.publishable_run_contracts import (
    PublishableProjectedOfficialCase,
    PublishableRunError,
    PublishableRunProviderInputs,
    PublishableRunRuntimeCapabilities,
)
from infinity_context_server.publishable_durable_scheduler.runner_official_request_renderer import (
    SCHEDULER_OFFICIAL_REQUEST_MAX_OUTPUT_TOKENS,
)

from .bridge_dispatch import HttpxRelayBridgeTransport
from .run_provider_config import (
    RunProviderConfig,
    RunProviderSecrets,
    parse_run_provider_inputs,
)
from .run_provider_extraction import open_sealed_extraction_suite
from .run_provider_preflight import preflight_run_provider

PUBLISHABLE_MEM0_INFINITY_PROVIDER_NAME = "mem0-infinity-production-v1"
PublishableProductionOpenMode = publishable_production_composition.PublishableProductionOpenMode
SQLiteSchedulerRetrievalEvidenceReader = (
    retrieval_evidence_sqlite_authority.SQLiteSchedulerRetrievalEvidenceReader
)
_MAX_DATASET_BYTES = 512 * 1024 * 1024
_JOURNAL_FILE = "subscription-bridge-journal.sqlite3"


@final
class Mem0InfinityPublishableRunDependencyFactory:
    """Open the production dependency session from the redacted provider DTO only."""

    __slots__ = ()

    def open_session(
        self,
        *,
        inputs: PublishableRunProviderInputs,
        mode: PublishableProductionOpenMode,
    ) -> _ProductionRunSession:
        if type(mode) is not PublishableProductionOpenMode:
            _fail("publishable_run_provider_mode_invalid")
        config, secrets = parse_run_provider_inputs(inputs)
        readiness = preflight_run_provider(
            config=config,
            secrets=secrets,
            mode=mode,
        )
        extraction = open_sealed_extraction_suite(
            config.extraction_terminal_paths,
            authentication_keys=secrets.extraction_authentication_keys,
        )
        projection = _OfficialCaseProjection.load(config)
        bridge_keys = _BridgeSecrets(secrets)
        suite = _suite(config, projection, extraction, readiness)
        return _ProductionRunSession(
            inputs=inputs,
            mode=mode,
            config=config,
            secrets=secrets,
            suite=suite,
            projection=projection,
            extraction=extraction,
            readiness=readiness,
            bridge_keys=bridge_keys,
        )


@final
class _OfficialCaseProjection:
    __slots__ = ("_by_benchmark", "_identities")

    def __init__(
        self,
        cases: tuple[tuple[PublicBenchmarkCase, ...], tuple[PublicBenchmarkCase, ...]],
    ) -> None:
        self._by_benchmark = {"locomo": cases[0], "longmemeval": cases[1]}
        self._identities = tuple(
            tuple(
                SchedulerCaseAuthority(case_id=case.case_id, case_alias=_case_alias(case))
                for case in group
            )
            for group in cases
        )

    @classmethod
    def load(cls, config: RunProviderConfig) -> _OfficialCaseProjection:
        groups: list[tuple[PublicBenchmarkCase, ...]] = []
        for expected_benchmark, expected_count, source in (
            ("locomo", LOCOMO_PROFILE.case_count, config.locomo_dataset),
            ("longmemeval", LONGMEMEVAL_PROFILE.case_count, config.longmemeval_dataset),
        ):
            cases = _load_authenticated_dataset_cases(
                source.path,
                expected_sha256=source.sha256,
            )
            if (
                len(cases) != expected_count
                or any(type(item) is not PublicBenchmarkCase for item in cases)
                or any(item.benchmark != expected_benchmark for item in cases)
                or len({item.case_id for item in cases}) != len(cases)
            ):
                _fail("publishable_run_provider_official_cases_invalid")
            groups.append(cases)
        return cls(tuple(groups))

    @property
    def identities(
        self,
    ) -> tuple[tuple[SchedulerCaseAuthority, ...], tuple[SchedulerCaseAuthority, ...]]:
        return self._identities

    def read_page(self, *, run, start_case_index: int, limit: int):
        try:
            benchmark = run.binding.profile.benchmark.value
            cases = self._by_benchmark[benchmark]
        except Exception:
            _fail("publishable_run_provider_official_case_request_invalid")
        if (
            type(start_case_index) is not int
            or type(limit) is not int
            or start_case_index < 0
            or limit < 1
            or start_case_index > len(cases)
        ):
            _fail("publishable_run_provider_official_case_request_invalid")
        stop = min(start_case_index + limit, len(cases))
        return tuple(
            PublishableProjectedOfficialCase(
                case_index=index,
                case_id=cases[index].case_id,
                case_alias=self._identities[run.run_index][index].case_alias,
                case=cases[index],
            )
            for index in range(start_case_index, stop)
        )


OfficialCaseProjection = _OfficialCaseProjection


@final
@dataclass(slots=True, repr=False)
class _ProductionRunSession:
    inputs: PublishableRunProviderInputs = field(repr=False)
    mode: PublishableProductionOpenMode
    config: RunProviderConfig = field(repr=False)
    secrets: RunProviderSecrets = field(repr=False)
    suite: SchedulerSuiteAuthority
    projection: _OfficialCaseProjection = field(repr=False)
    extraction: object = field(repr=False)
    readiness: BridgeFleetReadinessReceipt = field(repr=False)
    bridge_keys: _BridgeSecrets = field(repr=False)
    _journal: BridgeJournal | None = field(default=None, init=False, repr=False)
    _retrieval: SQLiteSchedulerRetrievalEvidenceReader | None = field(
        default=None, init=False, repr=False
    )
    _closed: bool = field(default=False, init=False, repr=False)

    @property
    def official_case_projection(self) -> _OfficialCaseProjection:
        self._require_open()
        return self.projection

    def open_runtime(self, *, case_authority_root_sha256: str) -> PublishableRunRuntimeCapabilities:
        self._require_open()
        if self._journal is not None or self._retrieval is not None:
            _fail("publishable_run_provider_runtime_already_open")
        journal: BridgeJournal | None = None
        retrieval: SQLiteSchedulerRetrievalEvidenceReader | None = None
        try:
            retrieval = SQLiteSchedulerRetrievalEvidenceReader.open(
                self.config.retrieval_database_path,
                authentication_key=self.secrets.retrieval_authentication_key,
                authority_root_sha256=self.config.retrieval_authority_root_sha256,
                case_authority_root_sha256=case_authority_root_sha256,
            )
            journal = _open_journal(
                self.inputs.state_root / _JOURNAL_FILE,
                mode=self.mode,
                authentication_key=self.secrets.bridge_journal_authentication_key,
            )
            cipher = Aes256GcmOutputCipher(
                key_resolver=_SingleOutputKeyResolver(
                    key_id=self.config.output_cipher_key_id,
                    key=self.secrets.output_cipher_key,
                ),
                maximum_ciphertext_bytes=self.config.maximum_ciphertext_bytes,
            )
            transport = HttpxRelayBridgeTransport(
                relay_origin=self.config.suite.mem0_base_url,
                maximum_request_bytes=self.config.maximum_bridge_request_bytes,
                connect_timeout_seconds=self.config.bridge_connect_timeout_seconds,
                read_timeout_seconds=self.config.bridge_read_timeout_seconds,
                write_timeout_seconds=self.config.bridge_write_timeout_seconds,
            )
            runtime = PublishableRunRuntimeCapabilities(
                extraction_suite=self.extraction,
                retrieval_authority=retrieval,
                output_cipher=cipher,
                bridge_keys=self.bridge_keys,
                bridge_fleet_readiness=self.readiness,
                bridge_transport=transport,
                bridge_journal=journal,
                clock=lambda: time.time_ns() // 1_000_000,
                lease_id_factory=lambda: f"publishable-{token_hex(16)}",
                lease_duration_ms=self.config.lease_duration_ms,
            )
        except BaseException:
            if journal is not None:
                journal.close()
            if retrieval is not None:
                retrieval.close()
            raise
        self._journal = journal
        self._retrieval = retrieval
        return runtime

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        first: BaseException | None = None
        for resource in (self._journal, self._retrieval):
            if resource is None:
                continue
            try:
                resource.close()
            except BaseException as error:
                if first is None:
                    first = error
        if first is not None:
            raise first

    def _require_open(self) -> None:
        if self._closed:
            _fail("publishable_run_provider_session_closed")

    def __repr__(self) -> str:
        return "_ProductionRunSession(authorities=<bound>, private_material=<redacted>)"


@final
class _BridgeSecrets:
    __slots__ = ("_items",)

    def __init__(self, secrets: RunProviderSecrets) -> None:
        self._items = {item.bridge_id: item for item in secrets.bridges}

    def authorization_bearer(self, bridge_id: str) -> str:
        return self._item(bridge_id).authorization_bearer

    def attestation_secret(self, bridge_id: str) -> bytes:
        return bytes(self._item(bridge_id).attestation_secret)

    def launcher_receipt_key(self, bridge_id: str) -> bytes:
        return bytes(self._item(bridge_id).launcher_receipt_key)

    def _item(self, bridge_id: str):
        try:
            return self._items[bridge_id]
        except (KeyError, TypeError):
            _fail("publishable_run_provider_bridge_secret_unavailable")

    def __repr__(self) -> str:
        return "_BridgeSecrets(<redacted>)"

    def __reduce_ex__(self, _protocol: int) -> object:
        raise TypeError("bridge secrets are nonserializable")


@final
class _SingleOutputKeyResolver:
    __slots__ = ("_key",)

    def __init__(self, *, key_id: str, key: bytes) -> None:
        self._key = OutputCipherKey(key_id=key_id, secret=bytes(key))

    def active_key(self) -> OutputCipherKey:
        return self._key

    def resolve_key(self, key_id: str, /) -> OutputCipherKey:
        if key_id != self._key.key_id:
            _fail("publishable_run_provider_output_key_unavailable")
        return self._key

    def __repr__(self) -> str:
        return "_SingleOutputKeyResolver(<redacted>)"


def _suite(config, projection, extraction, readiness) -> SchedulerSuiteAuthority:
    terminals = (extraction.locomo_terminal, extraction.longmemeval_terminal)
    if any(
        item.runtime_binding_commitment_sha256
        != config.runtime_authority.subscription_runtime_binding_commitment_sha256
        for item in terminals
    ):
        _fail("publishable_run_provider_extraction_runtime_cross_wire")
    suite = _suite_from_run_authorities(
        config,
        projection,
        terminals,
        readiness,
    )
    if any(
        item.scheduler_bridge_runtime_authority_sha256 != suite.bridge_boot.runtime_authority_sha256
        for item in terminals
    ):
        _fail("publishable_run_provider_extraction_runtime_cross_wire")
    return suite


def build_publishable_suite_from_prepared_receipts(
    *,
    config: RunProviderConfig,
    projection: OfficialCaseProjection,
    receipts: tuple[StrictV4PreparationReceipt, StrictV4PreparationReceipt],
    readiness: BridgeFleetReadinessReceipt,
) -> SchedulerSuiteAuthority:
    """Build the consumer-identical suite before extraction terminals exist."""

    if (
        type(config) is not RunProviderConfig
        or type(projection) is not _OfficialCaseProjection
        or type(receipts) is not tuple
        or len(receipts) != 2
        or any(type(item) is not StrictV4PreparationReceipt for item in receipts)
        or type(readiness) is not BridgeFleetReadinessReceipt
        or tuple(item.profile_id for item in receipts)
        != (LOCOMO_PROFILE.profile_id, LONGMEMEVAL_PROFILE.profile_id)
        or tuple(len(group) for group in projection.identities)
        != (LOCOMO_PROFILE.case_count, LONGMEMEVAL_PROFILE.case_count)
    ):
        _fail("publishable_run_provider_prepared_receipts_invalid")
    return _suite_from_run_authorities(config, projection, receipts, readiness)


def _suite_from_run_authorities(
    config,
    projection,
    authorities,
    readiness,
) -> SchedulerSuiteAuthority:
    profile = public_publishable_comparison_profile(publishable_priority_comparison_profile_v4())
    scheduler_profiles = (LOCOMO_PROFILE, LONGMEMEVAL_PROFILE)
    run_ids = (config.suite.locomo_run_id, config.suite.longmemeval_run_id)
    expected_dataset_sha = tuple(
        profile["benchmarks"][item.benchmark.value]["dataset_sha256"] for item in scheduler_profiles
    )
    if tuple(item.dataset_sha256 for item in authorities) != expected_dataset_sha:
        _fail("publishable_run_provider_extraction_dataset_cross_wire")
    backends = (
        SchedulerBackendAuthority(
            "infinity-context",
            managed_backend_target_identity_sha256(
                backend_role="infinity-context",
                base_url=config.suite.infinity_base_url,
            ),
        ),
        SchedulerBackendAuthority(
            "mem0",
            managed_backend_target_identity_sha256(
                backend_role="mem0", base_url=config.suite.mem0_base_url
            ),
        ),
    )
    bindings = []
    for index, (scheduler_profile, run_id, authority) in enumerate(
        zip(scheduler_profiles, run_ids, authorities, strict=True)
    ):
        limits = SchedulerDeadlineTokenAuthority(
            dispatch_not_before_unix_ms=config.suite.dispatch_not_before_unix_ms,
            dispatch_deadline_unix_ms=config.suite.dispatch_deadline_unix_ms,
            answer_max_output_tokens=SCHEDULER_OFFICIAL_REQUEST_MAX_OUTPUT_TOKENS,
            judge_max_output_tokens=SCHEDULER_OFFICIAL_REQUEST_MAX_OUTPUT_TOKENS,
            run_token_ceiling=(
                scheduler_profile.case_count * 4 * SCHEDULER_OFFICIAL_REQUEST_MAX_OUTPUT_TOKENS
            ),
        )
        if authority.run_id_sha256 != hashlib.sha256(run_id.encode()).hexdigest():
            _fail("publishable_run_provider_extraction_run_cross_wire")
        bindings.append(
            SchedulerRunBinding(
                run_id=run_id,
                profile=scheduler_profile,
                binding_commitment_sha256=authority.binding_commitment_sha256,
                dataset_sha256=authority.dataset_sha256,
                case_manifest_sha256=case_manifest_sha256(projection.identities[index]),
                backends=backends,
                limits=limits,
            )
        )
    try:
        suite = SchedulerSuiteAuthority(
            suite_id=config.suite.suite_id,
            publication_bundle_sha256=config.suite.publication_bundle_sha256,
            methodology_sha256=PUBLISHABLE_PRIORITY_METHODOLOGY_V4_COMMITMENT_SHA256,
            source_commit_sha256=config.suite.source_commit_sha256,
            bridge_boot=(
                scheduler_subscription_bridge_adapter.build_subscription_runtime_scheduler_bridge_boot_authority_from_fleet_readiness(
                    readiness
                )
            ),
            ordered_runs=tuple(bindings),
        )
    except Exception:
        _fail("publishable_run_provider_suite_invalid")
    return suite


def _open_journal(
    path: Path,
    *,
    mode: PublishableProductionOpenMode,
    authentication_key: bytes,
) -> BridgeJournal:
    integrity = HmacJournalIntegrity(authentication_key)
    if path.exists():
        return BridgeJournal.open(path, integrity=integrity)
    if mode is PublishableProductionOpenMode.RESUME:
        _fail("publishable_run_provider_journal_missing")
    return BridgeJournal.create(path, integrity=integrity)


def _load_authenticated_dataset_cases(
    path: Path,
    *,
    expected_sha256: str,
) -> tuple[PublicBenchmarkCase, ...]:
    descriptor: int | None = None
    cases: tuple[PublicBenchmarkCase, ...]
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        before = path.lstat()
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or _dataset_file_identity(before) != _dataset_file_identity(opened)
            or opened.st_nlink != 1
            or opened.st_mode & 0o022
            or not 1 <= opened.st_size <= _MAX_DATASET_BYTES
        ):
            raise OSError

        snapshot = _read_dataset_snapshot(descriptor)
        if (
            len(snapshot) != opened.st_size
            or hashlib.sha256(snapshot).hexdigest() != expected_sha256
        ):
            raise OSError

        cases = load_memory_comparison_cases_from_bytes(
            snapshot,
            locomo_ingest_mode=LOCOMO_INGEST_OFFICIAL_TURNS,
        )
        final = os.fstat(descriptor)
        after = path.lstat()
        if not (
            _dataset_file_identity(opened)
            == _dataset_file_identity(final)
            == _dataset_file_identity(after)
        ):
            raise OSError
    except Exception:
        _fail("publishable_run_provider_official_cases_invalid")
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                _fail("publishable_run_provider_official_cases_invalid")
    return cases


def _read_dataset_snapshot(descriptor: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        maximum_chunk_bytes = min(1024 * 1024, _MAX_DATASET_BYTES - total + 1)
        chunk = os.read(descriptor, maximum_chunk_bytes)
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > _MAX_DATASET_BYTES:
            raise OSError
    return b"".join(chunks)


def _dataset_file_identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_nlink,
        value.st_uid,
        value.st_gid,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _case_alias(case: PublicBenchmarkCase) -> str:
    digest = hashlib.sha256(f"{case.benchmark}\0case\0{case.case_id}".encode()).hexdigest()
    return f"{case.benchmark}-case-{digest}"


def _fail(code: str) -> None:
    raise PublishableRunError(code) from None


__all__ = (
    "PUBLISHABLE_MEM0_INFINITY_PROVIDER_NAME",
    "Mem0InfinityPublishableRunDependencyFactory",
    "OfficialCaseProjection",
    "build_publishable_suite_from_prepared_receipts",
)

"""Resumable official-case authority preparation for one publishable suite."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import final

from infinity_context_server.memory_comparison_publishable_profile import (
    PUBLISHABLE_PRIORITY_PROFILE_V4_COMMITMENT_SHA256,
    PUBLISHABLE_PRIORITY_PROFILE_V4_ID,
)
from infinity_context_server.publishable_durable_scheduler.contracts import (
    SchedulerRunAuthority,
    SchedulerSuiteAuthority,
    run_authority_from_suite,
)
from infinity_context_server.publishable_durable_scheduler.manifest import (
    BuiltSchedulerManifest,
    SchedulerCaseAuthority,
    build_scheduler_manifest,
)
from infinity_context_server.publishable_durable_scheduler.official_authority_contracts import (
    SCHEDULER_OFFICIAL_CASE_PAGE_ROW_LIMIT,
    SchedulerOfficialCaseAuthorityPage,
    SchedulerOfficialCaseAuthorityRow,
    SchedulerOfficialCaseAuthorityTerminal,
    SchedulerOfficialCaseRunScope,
)
from infinity_context_server.publishable_durable_scheduler.official_case_sqlite_authority import (
    SQLiteSchedulerOfficialCaseAuthorityBuilder,
    SQLiteSchedulerOfficialCaseReader,
)
from infinity_context_server.publishable_durable_scheduler.publishable_run_contracts import (
    PublishableOfficialCaseProjectionPort,
    PublishableProjectedOfficialCase,
    PublishableRunConfig,
    PublishableRunError,
    PublishableRunSecrets,
)
from infinity_context_server.publishable_durable_scheduler.runner_contracts import (
    SchedulerRunStoreSpec,
    SchedulerSuiteSealStoreSpec,
)


@final
@dataclass(frozen=True, slots=True, repr=False)
class PreparedPublishableOfficialCases:
    """Sealed reader plus exact scheduler stores derived from its identities."""

    runs: tuple[SchedulerRunAuthority, SchedulerRunAuthority]
    manifests: tuple[BuiltSchedulerManifest, BuiltSchedulerManifest]
    run_stores: tuple[SchedulerRunStoreSpec, SchedulerRunStoreSpec] = field(repr=False)
    seal_store: SchedulerSuiteSealStoreSpec = field(repr=False)
    terminal: SchedulerOfficialCaseAuthorityTerminal
    reader: SQLiteSchedulerOfficialCaseReader = field(repr=False)

    def __post_init__(self) -> None:
        if (
            type(self.runs) is not tuple
            or len(self.runs) != 2
            or any(type(item) is not SchedulerRunAuthority for item in self.runs)
            or type(self.manifests) is not tuple
            or len(self.manifests) != 2
            or any(type(item) is not BuiltSchedulerManifest for item in self.manifests)
            or type(self.run_stores) is not tuple
            or len(self.run_stores) != 2
            or any(type(item) is not SchedulerRunStoreSpec for item in self.run_stores)
            or type(self.seal_store) is not SchedulerSuiteSealStoreSpec
            or type(self.terminal) is not SchedulerOfficialCaseAuthorityTerminal
            or type(self.reader) is not SQLiteSchedulerOfficialCaseReader
        ):
            _fail("publishable_run_prepared_cases_invalid")

    def close(self) -> None:
        self.reader.close()

    def __repr__(self) -> str:
        return (
            "PreparedPublishableOfficialCases("
            f"authority_root_sha256={self.terminal.authority_root_sha256!r}, "
            f"case_count={self.terminal.case_count!r}, private_reader=<bound>)"
        )


def prepare_publishable_official_cases(
    *,
    suite: SchedulerSuiteAuthority,
    projection: PublishableOfficialCaseProjectionPort,
    config: PublishableRunConfig,
    secrets: PublishableRunSecrets,
) -> PreparedPublishableOfficialCases:
    """Replay every projected page, seal it, and derive both exact manifests."""

    if (
        type(suite) is not SchedulerSuiteAuthority
        or not callable(getattr(projection, "read_page", None))
        or type(config) is not PublishableRunConfig
        or type(secrets) is not PublishableRunSecrets
    ):
        _fail("publishable_run_official_case_inputs_invalid")
    runs = tuple(run_authority_from_suite(suite, run_index=index) for index in (0, 1))
    scopes = tuple(_scope(suite, run) for run in runs)
    builder = _open_builder(config, secrets, scopes)
    identities: list[tuple[SchedulerCaseAuthority, ...]] = []
    page_index = 0
    try:
        for run in runs:
            run_identities, page_index = _replay_run(
                builder=builder,
                projection=projection,
                run=run,
                first_page_index=page_index,
            )
            identities.append(run_identities)
        terminal = builder.finalize()
    finally:
        builder.close()
    if terminal.case_count != sum(run.binding.profile.case_count for run in runs):
        _fail("publishable_run_official_case_count_invalid")
    manifests = tuple(
        build_scheduler_manifest(run, suite=suite, ordered_cases=cases)
        for run, cases in zip(runs, identities, strict=True)
    )
    run_stores = tuple(
        SchedulerRunStoreSpec(
            run=run,
            manifest=manifest,
            database_path=path,
            private_directory=path.parent,
            authentication_secret=key,
        )
        for run, manifest, path, key in zip(
            runs,
            manifests,
            config.scheduler_database_paths,
            secrets.scheduler_authentication_keys,
            strict=True,
        )
    )
    seal_store = SchedulerSuiteSealStoreSpec(
        database_path=config.suite_seal_database_path,
        private_directory=config.suite_seal_database_path.parent,
        authentication_secret=secrets.suite_seal_authentication_key,
    )
    reader = SQLiteSchedulerOfficialCaseReader.open(
        config.official_case_authority_path,
        authentication_key=secrets.official_case_authentication_key,
        authority_root_sha256=terminal.authority_root_sha256,
    )
    try:
        return PreparedPublishableOfficialCases(
            runs=runs,
            manifests=manifests,
            run_stores=run_stores,
            seal_store=seal_store,
            terminal=terminal,
            reader=reader,
        )
    except BaseException:
        reader.close()
        raise


def _open_builder(
    config: PublishableRunConfig,
    secrets: PublishableRunSecrets,
    scopes: tuple[SchedulerOfficialCaseRunScope, SchedulerOfficialCaseRunScope],
) -> SQLiteSchedulerOfficialCaseAuthorityBuilder:
    arguments = {
        "run_scopes": scopes,
        "authentication_key": secrets.official_case_authentication_key,
    }
    if config.official_case_authority_path.exists():
        return SQLiteSchedulerOfficialCaseAuthorityBuilder.open(
            config.official_case_authority_path,
            **arguments,
        )
    return SQLiteSchedulerOfficialCaseAuthorityBuilder.create(
        config.official_case_authority_path,
        **arguments,
    )


def _scope(
    suite: SchedulerSuiteAuthority,
    run: SchedulerRunAuthority,
) -> SchedulerOfficialCaseRunScope:
    binding = run.binding
    return SchedulerOfficialCaseRunScope(
        suite_authority_sha256=suite.commitment_sha256,
        run_authority_sha256=run.commitment_sha256,
        run_binding_commitment_sha256=binding.binding_commitment_sha256,
        run_id=binding.run_id,
        benchmark=binding.profile.benchmark,
        scheduler_profile_id=binding.profile.profile_id,
        publishable_profile_id=PUBLISHABLE_PRIORITY_PROFILE_V4_ID,
        publishable_profile_sha256=PUBLISHABLE_PRIORITY_PROFILE_V4_COMMITMENT_SHA256,
        methodology_sha256=suite.methodology_sha256,
        dataset_sha256=binding.dataset_sha256,
        case_manifest_sha256=binding.case_manifest_sha256,
        case_count=binding.profile.case_count,
    )


def _replay_run(
    *,
    builder: SQLiteSchedulerOfficialCaseAuthorityBuilder,
    projection: PublishableOfficialCaseProjectionPort,
    run: SchedulerRunAuthority,
    first_page_index: int,
) -> tuple[tuple[SchedulerCaseAuthority, ...], int]:
    expected_count = run.binding.profile.case_count
    identities: list[SchedulerCaseAuthority] = []
    start = 0
    page_index = first_page_index
    while start < expected_count:
        limit = min(SCHEDULER_OFFICIAL_CASE_PAGE_ROW_LIMIT, expected_count - start)
        page = _read_page(projection, run=run, start=start, limit=limit)
        if not page:
            _fail("publishable_run_official_case_projection_incomplete")
        rows: list[SchedulerOfficialCaseAuthorityRow] = []
        for offset, item in enumerate(page):
            expected_index = start + offset
            if (
                type(item) is not PublishableProjectedOfficialCase
                or item.case_index != expected_index
                or item.case.benchmark != run.binding.profile.benchmark.value
            ):
                _fail("publishable_run_official_case_projection_divergent")
            item.__post_init__()
            identities.append(
                SchedulerCaseAuthority(case_id=item.case_id, case_alias=item.case_alias)
            )
            rows.append(
                SchedulerOfficialCaseAuthorityRow(
                    run_id=run.binding.run_id,
                    case_index=item.case_index,
                    case_id=item.case_id,
                    case_alias=item.case_alias,
                    case=item.case,
                )
            )
        builder.append_page(
            SchedulerOfficialCaseAuthorityPage(page_index=page_index, rows=tuple(rows))
        )
        start += len(page)
        page_index += 1
    if _read_page(projection, run=run, start=expected_count, limit=1):
        _fail("publishable_run_official_case_projection_overflow")
    return tuple(identities), page_index


def _read_page(
    projection: PublishableOfficialCaseProjectionPort,
    *,
    run: SchedulerRunAuthority,
    start: int,
    limit: int,
) -> tuple[PublishableProjectedOfficialCase, ...]:
    try:
        page = projection.read_page(
            run=run,
            start_case_index=start,
            limit=limit,
        )
    except PublishableRunError:
        raise
    except Exception:
        _fail("publishable_run_official_case_projection_failed")
    if (
        type(page) is not tuple
        or len(page) > limit
        or any(type(item) is not PublishableProjectedOfficialCase for item in page)
    ):
        _fail("publishable_run_official_case_projection_invalid")
    return page


def _fail(code: str) -> None:
    raise PublishableRunError(code) from None


__all__ = (
    "PreparedPublishableOfficialCases",
    "prepare_publishable_official_cases",
)

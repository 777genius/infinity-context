"""Resource-owning production composition for the two extraction workers."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from typing import final

from infinity_context_server.processes import (
    publishable_full_extraction_managed_mem0_v5_composition as run_composition,
)
from infinity_context_server.processes.publishable_full_extraction_suite import (
    PUBLISHABLE_EXTRACTION_BENCHMARKS,
    PublishableExtractionSuiteReadback,
    read_publishable_full_extraction_suite,
)
from infinity_context_server.processes.publishable_full_extraction_worker import (
    PublishableFullExtractionWorker,
)

PublishableFullExtractionCompositionError = (
    run_composition.PublishableFullExtractionCompositionError
)
PublishableFullExtractionRunConfiguration = (
    run_composition.PublishableFullExtractionRunConfiguration
)
publishable_full_extraction_state_paths = run_composition.publishable_full_extraction_state_paths


@final
@dataclass(frozen=True, slots=True)
class PublishableFullExtractionSuiteConfiguration:
    locomo: PublishableFullExtractionRunConfiguration
    longmemeval: PublishableFullExtractionRunConfiguration

    def __post_init__(self) -> None:
        configurations = (self.locomo, self.longmemeval)
        if any(
            type(item) is not PublishableFullExtractionRunConfiguration for item in configurations
        ):
            _fail("publishable_extraction_suite_configuration_invalid")
        for item, (profile_id, operation_count) in zip(
            configurations,
            PUBLISHABLE_EXTRACTION_BENCHMARKS,
            strict=True,
        ):
            receipt = item.preparation_receipt
            if (
                receipt.profile_id != profile_id
                or receipt.a1_authority.operation_count != operation_count
                or item.manifest_authority.operation_count != operation_count
                or item.admission.request.expected_operation_count != operation_count
                or len(item.runtime_receipt_authority.operations) != operation_count
            ):
                _fail("publishable_extraction_suite_profile_cross_wire")
        for values in (
            tuple(item.preparation_receipt.run_id_sha256 for item in configurations),
            tuple(item.preparation_receipt.binding_commitment_sha256 for item in configurations),
            tuple(item.preparation_receipt.dataset_sha256 for item in configurations),
            tuple(
                item.preparation_receipt.a1_context.manifest_context_sha256
                for item in configurations
            ),
            tuple(item.state_directory for item in configurations),
        ):
            if len(set(values)) != len(values):
                _fail("publishable_extraction_suite_run_cross_wire")
        if len({item.scheduler_bridge_runtime_authority_sha256 for item in configurations}) != 1:
            _fail("publishable_extraction_suite_runtime_cross_wire")


@final
class PublishableFullExtractionSuite:
    """Own both workers and expose only their authenticated terminal readback."""

    __slots__ = ("_closed", "locomo", "longmemeval")

    def __init__(
        self,
        *,
        locomo: PublishableFullExtractionWorker,
        longmemeval: PublishableFullExtractionWorker,
    ) -> None:
        if any(type(item) is not PublishableFullExtractionWorker for item in (locomo, longmemeval)):
            _fail("publishable_extraction_suite_worker_invalid")
        self.locomo = locomo
        self.longmemeval = longmemeval
        self._closed = False

    def readback(self) -> PublishableExtractionSuiteReadback:
        self._require_open()
        return read_publishable_full_extraction_suite(
            locomo_reader=self.locomo,
            longmemeval_reader=self.longmemeval,
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        first: BaseException | None = None
        for worker in (self.longmemeval, self.locomo):
            try:
                worker.close()
            except BaseException as error:
                if first is None:
                    first = error
        if first is not None:
            raise first

    def __enter__(self) -> PublishableFullExtractionSuite:
        self._require_open()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _require_open(self) -> None:
        if self._closed:
            _fail("publishable_extraction_suite_closed")


def build_publishable_full_extraction_suite(
    *,
    configuration: PublishableFullExtractionSuiteConfiguration,
) -> PublishableFullExtractionSuite:
    """Build both official workers, closing partial ownership on failure."""

    if type(configuration) is not PublishableFullExtractionSuiteConfiguration:
        _fail("publishable_extraction_suite_configuration_invalid")
    configuration.__post_init__()
    locomo: PublishableFullExtractionWorker | None = None
    try:
        locomo = run_composition.build_publishable_full_extraction_run(
            configuration=configuration.locomo,
        )
        longmemeval = run_composition.build_publishable_full_extraction_run(
            configuration=configuration.longmemeval,
        )
        return PublishableFullExtractionSuite(
            locomo=locomo,
            longmemeval=longmemeval,
        )
    except BaseException:
        if locomo is not None:
            with suppress(BaseException):
                locomo.close()
        raise


def _fail(code: str) -> None:
    raise PublishableFullExtractionCompositionError(code) from None


__all__ = (
    "PublishableFullExtractionSuite",
    "PublishableFullExtractionSuiteConfiguration",
    "build_publishable_full_extraction_suite",
    "publishable_full_extraction_state_paths",
)

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from infinity_context_server.processes import (
    publishable_full_extraction_managed_mem0_v5_composition as run_composition,
)
from infinity_context_server.processes import (
    publishable_full_extraction_managed_mem0_v5_suite_composition as suite_composition,
)
from infinity_context_server.processes.publishable_full_extraction_suite import (
    PUBLISHABLE_EXTRACTION_TOTAL_OPERATION_COUNT,
)
from infinity_context_server.processes.publishable_full_extraction_worker import (
    PublishableFullExtractionWorker,
)

PublishableFullExtractionCompositionError = (
    run_composition.PublishableFullExtractionCompositionError
)
PublishableFullExtractionSuite = suite_composition.PublishableFullExtractionSuite
PublishableFullExtractionSuiteConfiguration = (
    suite_composition.PublishableFullExtractionSuiteConfiguration
)
build_publishable_full_extraction_suite = suite_composition.build_publishable_full_extraction_suite


class _SizedOperations:
    def __init__(self, count: int) -> None:
        self.count = count

    def __len__(self) -> int:
        return self.count


def _run_configuration(
    *,
    profile_id: str,
    operation_count: int,
    seed: str,
    state_directory: Path,
) -> run_composition.PublishableFullExtractionRunConfiguration:
    configuration = object.__new__(run_composition.PublishableFullExtractionRunConfiguration)
    receipt = SimpleNamespace(
        profile_id=profile_id,
        run_id_sha256=(seed + "1" * 64)[:64],
        binding_commitment_sha256=(seed + "2" * 64)[:64],
        dataset_sha256=(seed + "3" * 64)[:64],
        a1_authority=SimpleNamespace(operation_count=operation_count),
        a1_context=SimpleNamespace(manifest_context_sha256=(seed + "4" * 64)[:64]),
    )
    values = {
        "preparation_receipt": receipt,
        "manifest_authority": SimpleNamespace(operation_count=operation_count),
        "admission": SimpleNamespace(
            request=SimpleNamespace(expected_operation_count=operation_count)
        ),
        "runtime_receipt_authority": SimpleNamespace(operations=_SizedOperations(operation_count)),
        "scheduler_bridge_runtime_authority_sha256": "c" * 64,
        "state_directory": state_directory,
    }
    for name, value in values.items():
        object.__setattr__(configuration, name, value)
    return configuration


def _suite_configuration(tmp_path: Path) -> PublishableFullExtractionSuiteConfiguration:
    return PublishableFullExtractionSuiteConfiguration(
        locomo=_run_configuration(
            profile_id="mem0-locomo-top50-v1",
            operation_count=5_882,
            seed="a",
            state_directory=tmp_path / "locomo",
        ),
        longmemeval=_run_configuration(
            profile_id="mem0-longmemeval-top50-v1",
            operation_count=124_344,
            seed="b",
            state_directory=tmp_path / "longmemeval",
        ),
    )


def _worker_shell() -> PublishableFullExtractionWorker:
    return object.__new__(PublishableFullExtractionWorker)


def test_suite_configuration_binds_exact_official_profiles_and_counts(
    tmp_path: Path,
) -> None:
    configuration = _suite_configuration(tmp_path)
    assert configuration.locomo.preparation_receipt.a1_authority.operation_count == 5_882
    assert configuration.longmemeval.preparation_receipt.a1_authority.operation_count == 124_344
    assert PUBLISHABLE_EXTRACTION_TOTAL_OPERATION_COUNT == 130_226
    assert (
        configuration.locomo.preparation_receipt.a1_authority.operation_count
        + configuration.longmemeval.preparation_receipt.a1_authority.operation_count
        == 130_226
    )

    object.__setattr__(
        configuration.longmemeval,
        "state_directory",
        configuration.locomo.state_directory,
    )
    with pytest.raises(
        PublishableFullExtractionCompositionError,
        match="publishable_extraction_suite_run_cross_wire",
    ):
        configuration.__post_init__()


def test_suite_build_closes_partial_worker_on_second_run_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configuration = _suite_configuration(tmp_path)
    first = _worker_shell()
    closed: list[PublishableFullExtractionWorker] = []
    calls = 0

    def build(**_kwargs: object) -> PublishableFullExtractionWorker:
        nonlocal calls
        calls += 1
        if calls == 1:
            return first
        raise RuntimeError("second run failed")

    monkeypatch.setattr(run_composition, "build_publishable_full_extraction_run", build)
    monkeypatch.setattr(
        PublishableFullExtractionWorker,
        "close",
        lambda self: closed.append(self),
    )

    with pytest.raises(RuntimeError, match="second run failed"):
        build_publishable_full_extraction_suite(configuration=configuration)
    assert closed == [first]


def test_suite_owner_closes_real_worker_type_in_reverse_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configuration = _suite_configuration(tmp_path)
    locomo, longmemeval = _worker_shell(), _worker_shell()
    workers = iter((locomo, longmemeval))
    closed: list[PublishableFullExtractionWorker] = []
    monkeypatch.setattr(
        run_composition,
        "build_publishable_full_extraction_run",
        lambda **_kwargs: next(workers),
    )
    monkeypatch.setattr(
        PublishableFullExtractionWorker,
        "close",
        lambda self: closed.append(self),
    )

    suite = build_publishable_full_extraction_suite(configuration=configuration)
    assert type(suite) is PublishableFullExtractionSuite
    assert suite.locomo is locomo
    assert suite.longmemeval is longmemeval
    suite.close()
    suite.close()
    assert closed == [longmemeval, locomo]
    assert suite_composition.build_publishable_full_extraction_suite is (
        build_publishable_full_extraction_suite
    )

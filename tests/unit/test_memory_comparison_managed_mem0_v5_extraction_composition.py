from __future__ import annotations

from pathlib import Path

import pytest
from infinity_context_server import memory_comparison_managed_mem0_v5_composition as subject
from infinity_context_server.memory_comparison_managed_mem0_v5_http_lane import (
    ManagedMem0V5HttpLane,
)
from test_memory_comparison_managed_mem0_v5_composition import (
    _inputs,
    _observed_authority,
    _Transport,
)


def test_extraction_capability_composition_is_checkpoint_and_network_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs, _values = _inputs(tmp_path)
    inputs["receipt_authority"] = _observed_authority(inputs)
    state = inputs["state_paths"]
    transport = inputs["transport"]
    assert type(state) is subject.ManagedMem0V5StatePaths
    assert type(transport) is _Transport

    def checkpoint_forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("checkpoint head must not open for extraction capabilities")

    monkeypatch.setattr(
        subject,
        "SQLiteManagedMem0V5CheckpointHead",
        checkpoint_forbidden,
    )
    monkeypatch.setattr(
        subject,
        "require_mem0_v5_observed_extraction_receipt_boundary",
        lambda **_kwargs: None,
    )

    capabilities = subject.compose_managed_mem0_v5_extraction_capabilities(**inputs)

    assert type(capabilities) is subject.ManagedMem0V5ExtractionCapabilities
    assert type(capabilities.http_lane) is ManagedMem0V5HttpLane
    assert capabilities.admission.request == inputs["request"]
    assert transport.calls == []
    assert not state.checkpoint.exists()
    assert not state.local_checkpoint_head.exists()

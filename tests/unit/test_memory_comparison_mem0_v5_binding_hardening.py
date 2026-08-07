from __future__ import annotations

import gc
import hashlib
import json
import weakref
from dataclasses import replace
from pathlib import Path

import pytest
from infinity_context_server import (
    memory_comparison_bounded_httpx_transport as bounded_transport_module,
)
from infinity_context_server import (
    memory_comparison_managed_mem0_v5_composition as composition_subject,
)
from infinity_context_server import (
    memory_comparison_managed_mem0_v5_paired_fingerprint as fingerprint_module,
)
from infinity_context_server import memory_comparison_mem0_oss_v5_http as http_module
from infinity_context_server.memory_comparison_managed_mem0_v5_clean_state_http import (
    ManagedMem0V5HmacDurableCleanStateFactory,
    ManagedMem0V5HttpCleanStateSnapshotFactory,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_lane import (
    ManagedMem0V5BudgetPolicy,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_paired_bridge import (
    managed_mem0_v5_paired_run_fingerprint,
)
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunError
from infinity_context_server.memory_comparison_mem0_oss_v5_http import (
    Mem0V5HttpError,
    Mem0V5HttpPort,
)
from infinity_context_server.memory_comparison_secret_validation import (
    is_bounded_text_secret,
)
from test_memory_comparison_managed_mem0_v5_composition import _inputs, _Transport
from test_memory_comparison_managed_mem0_v5_paired_bridge import _run, _sha
from test_memory_comparison_mem0_v5_evidence_foundations_r2 import _clean_request


def test_mutation_cannot_be_recomputed_or_written_back_as_new_authority() -> None:
    _authority_value, coordinator, run = _run()
    stable = managed_mem0_v5_paired_run_fingerprint(run)
    object.__setattr__(run._request, "route_sha256", _sha("mutated-route"))

    with pytest.raises(ManagedRunError, match="binding differs"):
        managed_mem0_v5_paired_run_fingerprint(run)
    with pytest.raises(AttributeError):
        object.__setattr__(run, "_binding_commitment_sha256", stable)
    with pytest.raises(ManagedRunError, match="binding differs"):
        run.admit()

    assert coordinator.admit_calls == 0


def test_registry_swap_is_rejected_and_registry_does_not_retain_run() -> None:
    _authority_one, _coordinator_one, first = _run(identity_seed="registry-one")
    _authority_two, _coordinator_two, second = _run(identity_seed="registry-two")
    first_state = fingerprint_module._EXPECTED[first]
    second_state = fingerprint_module._EXPECTED[second]
    fingerprint_module._EXPECTED[first] = second_state

    with pytest.raises(ManagedRunError, match="binding differs"):
        managed_mem0_v5_paired_run_fingerprint(first)

    fingerprint_module._EXPECTED[first] = first_state
    reference = weakref.ref(first)
    del first
    gc.collect()
    assert reference() is None


def _target(run: object, component: str) -> object:
    coordinator = run._coordinator
    lane = coordinator._lane
    return {
        "lane": lane,
        "control": lane._control,
        "receipt": coordinator._service._receipt_port,
        "verifier": lane._verifier,
        "service": coordinator._service,
        "progress": coordinator._progress,
        "signer": coordinator._progress._signer,
        "head": coordinator._progress._head,
        "durable": run._durable_clean_state,
    }[component]


_IDENTITY_SWAPS = (
    ("lane", "_bearer"),
    ("control", "_bearer"),
    ("receipt", "_secret"),
    ("verifier", "_observation_key"),
    ("verifier", "_request_binding_key"),
    ("verifier", "_request_binding_v2_key"),
    ("verifier", "_search_key"),
    ("verifier", "_clean_state_key"),
    ("signer", "_key"),
    ("head", "_hmac_key"),
    ("durable", "_hmac_key"),
)
_DELEGATE_SWAPS = (
    ("control", "_transport"),
    ("service", "_receipt_port"),
    ("progress", "_store"),
    ("progress", "_head"),
)


@pytest.mark.parametrize(("component", "attribute"), _IDENTITY_SWAPS + _DELEGATE_SWAPS)
def test_direct_bundle_run_rejects_nested_swap_before_admit_io(
    tmp_path: Path, component: str, attribute: str
) -> None:
    inputs, values = _inputs(tmp_path)
    transport = inputs["transport"]
    assert type(transport) is _Transport  # noqa: E721 - exact fixture contract
    composition = composition_subject.compose_managed_mem0_v5(**inputs)

    class DurableKey:
        def __init__(self) -> None:
            self.consume_calls = 0

        def validate(self) -> None:
            return None

        def consume(self) -> bytes:
            self.consume_calls += 1
            return b"direct-bundle-durable-key-value!!" * 2

    durable_key = DurableKey()
    bundle = composition.issue_paired_runtime(
        budget_policy=ManagedMem0V5BudgetPolicy(5),
        clean_state_snapshot_factory=ManagedMem0V5HttpCleanStateSnapshotFactory(),
        durable_clean_state_factory=ManagedMem0V5HmacDurableCleanStateFactory(
            path=tmp_path / "direct-clean-state.json",
            hmac_key_capability=durable_key,
        ),
    )
    paired_run = bundle.paired_run
    snapshot = json.dumps(fingerprint_module._paired_run_snapshot(paired_run), sort_keys=True)
    for secret_name in ("bearer", "receipt", "signing", "head"):
        secret = values[secret_name]
        assert secret.decode() not in snapshot
        assert hashlib.sha256(secret).hexdigest() not in snapshot
    verifier = paired_run._coordinator._lane._verifier
    for _component, key_name in _IDENTITY_SWAPS[3:8]:
        derived_key = getattr(verifier, key_name)
        assert derived_key.hex() not in snapshot
        assert hashlib.sha256(derived_key).hexdigest() not in snapshot
    durable_secret = b"direct-bundle-durable-key-value!!" * 2
    assert durable_secret.decode() not in snapshot
    assert hashlib.sha256(durable_secret).hexdigest() not in snapshot
    target = _target(paired_run, component)
    original = getattr(target, attribute)
    if (component, attribute) in _IDENTITY_SWAPS:
        if original.__class__ is str:
            replacement = (" " + original)[1:]
        else:
            replacement = bytes(bytearray(original))
        assert replacement == original
        assert replacement is not original
    else:
        replacement = object()
    object.__setattr__(target, attribute, replacement)

    with pytest.raises(ManagedRunError, match="binding differs"):
        paired_run.admit()

    assert durable_key.consume_calls == 1
    assert transport.calls == []


@pytest.mark.parametrize(
    "revision",
    ("", " revision", "revision/1", "révision", "revision\u200b", "a" * 513),
)
def test_clean_state_request_uses_adapter_exact_runtime_revision_grammar(
    revision: str,
) -> None:
    with pytest.raises(Mem0V5HttpError) as captured:
        replace(_clean_request(), runtime_source_revision=revision)

    assert captured.value.code == "mem0_v5_http_request_invalid"


def test_clean_state_request_accepts_runtime_revision_boundary() -> None:
    request = replace(_clean_request(), runtime_source_revision="a" * 512)

    assert request.runtime_source_revision == "a" * 512


def test_text_secret_rejects_lone_surrogate_without_leaking_unicode_error() -> None:
    value = "x" * 31 + "\ud800"

    assert is_bounded_text_secret(value) is False


def test_http_port_maps_lone_surrogate_secret_to_stable_configuration_error() -> None:
    class NoIoTransport:
        calls = 0

        def request(self, *_args: object, **_kwargs: object) -> object:
            self.calls += 1
            raise AssertionError("invalid secret reached transport")

    transport = NoIoTransport()
    with pytest.raises(Mem0V5HttpError) as captured:
        Mem0V5HttpPort(
            origin="http://127.0.0.1:8891",
            bearer_token="x" * 31 + "\ud800",
            timeout_seconds=5.0,
            transport=transport,
        )

    assert captured.value.code == "mem0_v5_http_configuration_invalid"
    assert transport.calls == 0


def test_common_httpx_transport_stops_after_bound_plus_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        status_code = 200

        def __init__(self) -> None:
            self.closed = False
            self.chunks_read = 0

        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *_args: object) -> None:
            self.closed = True

        def iter_bytes(self, *, chunk_size: int):
            assert chunk_size == 64_000
            for chunk in (b"x" * 256_000, b"overflow", b"must-not-be-read"):
                self.chunks_read += 1
                yield chunk

    response = FakeResponse()

    class FakeClient:
        def __init__(self, **kwargs: object) -> None:
            assert kwargs == {
                "transport": "isolated-transport",
                "follow_redirects": False,
                "trust_env": False,
            }
            self.closed = False

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *_args: object) -> None:
            self.closed = True

        def stream(self, method: str, url: str, **kwargs: object) -> FakeResponse:
            assert method == "POST"
            assert url == "http://127.0.0.1:8891/v5/runs/admit"
            assert kwargs["follow_redirects"] is False
            return response

    clients: list[FakeClient] = []

    def client_factory(**kwargs: object) -> FakeClient:
        client = FakeClient(**kwargs)
        clients.append(client)
        return client

    def transport_factory(**kwargs: object) -> str:
        assert kwargs == {"retries": 0, "trust_env": False}
        return "isolated-transport"

    monkeypatch.setattr(bounded_transport_module.httpx, "HTTPTransport", transport_factory)
    monkeypatch.setattr(bounded_transport_module.httpx, "Client", client_factory)

    result = http_module._HttpxTransport().request(
        "POST",
        "http://127.0.0.1:8891/v5/runs/admit",
        follow_redirects=False,
    )

    assert len(result.content) == 256_001
    assert result.content[-1:] == b"o"
    assert response.chunks_read == 2
    assert response.closed is True
    assert len(clients) == 1 and clients[0].closed is True
    with pytest.raises(ValueError, match="exceeds bound"):
        result.read_bounded(256_000)


def test_failed_delegate_mutation_blocks_abort_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _authority_value, coordinator, run = _run()

    def mutate_then_fail(_self: object, **_values: object) -> object:
        object.__setattr__(run._request, "route_sha256", _sha("mutated-during-admit"))
        raise RuntimeError("snapshot failed")

    monkeypatch.setattr(
        type(run._clean_state_snapshot),
        "prove_empty_scopes",
        mutate_then_fail,
    )

    with pytest.raises(RuntimeError, match="snapshot failed") as captured:
        run.admit()

    assert coordinator.admit_calls == 1
    assert coordinator.abort_calls == 0
    assert run._state.value == "abort_retry"
    assert any("paired abort failed: ManagedRunError" in note for note in captured.value.__notes__)

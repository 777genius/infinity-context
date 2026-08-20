from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from infinity_context_runtime_bridge import (
    BridgeDivergenceError,
    BridgeJournal,
    BridgeReceiptError,
    HmacJournalIntegrity,
    OutcomeUnknown,
    SubscriptionRuntimeBridgeAdapter,
    TerminalBridgeCall,
    canonical_openai_request_body,
)
from infinity_context_runtime_bridge.json_boundary import (
    canonical_json_bytes,
)
from infinity_context_runtime_bridge.request_contract import (
    derive_bridge_intent,
)
from subscription_runtime_bridge_test_support import (
    JOURNAL_KEY,
    AttestedFakeTransport,
    FakeSecrets,
    TestAuthenticatedCipher,
    build_runtime_response,
    make_binding,
    make_pool,
)

MAX_BYTES = 256 * 1024


class _ReplayFirstValidResponseTransport:
    """Return one authentic physical response for every later dispatch."""

    def __init__(self, pool, secrets) -> None:
        self._pool = pool
        self._secrets = secrets
        self.calls: list[tuple[str, bytes]] = []
        self.first_response: bytes | None = None

    def post_once(
        self,
        *,
        origin: str,
        route: str,
        bearer_token: str,
        request_body: bytes,
        maximum_response_bytes: int,
    ) -> bytes:
        bridge = next(item for item in self._pool.bridges if item.origin == origin)
        assert route == bridge.route
        assert bearer_token == self._secrets.authorization_bearer(bridge.bridge_id)
        self.calls.append((bridge.bridge_id, request_body))
        if self.first_response is None:
            self.first_response = canonical_json_bytes(
                build_runtime_response(
                    bridge=bridge,
                    request_body=request_body,
                    secret=self._secrets.attestation_secret(bridge.bridge_id),
                )
            )
        assert len(self.first_response) <= maximum_response_bytes
        return self.first_response


def test_exact_same_intent_and_request_nonce_replays_without_dispatch(
    tmp_path: Path,
) -> None:
    pool = make_pool()
    secrets = FakeSecrets(pool)
    transport = AttestedFakeTransport(pool, secrets)
    database = tmp_path / "bridge" / "journal.sqlite3"
    journal = BridgeJournal.create(database, integrity=HmacJournalIntegrity(JOURNAL_KEY))
    adapter = _adapter(pool, secrets, transport, journal)
    binding = make_binding()
    nonce = _nonce("exact-scheduler-intent")
    request = _request(nonce)

    dispatched = adapter.execute(binding=binding, canonical_request_body=request)
    replayed = adapter.execute(binding=binding, canonical_request_body=request)

    assert isinstance(dispatched, TerminalBridgeCall)
    assert isinstance(replayed, TerminalBridgeCall)
    assert dispatched.transport_dispatched is True
    assert replayed.transport_dispatched is False
    assert replayed.readback == dispatched.readback
    assert dispatched.readback.intent.request_identity_nonce == nonce
    assert len(transport.calls) == 1
    journal.close()

    reopened = BridgeJournal.open(database, integrity=HmacJournalIntegrity(JOURNAL_KEY))
    recovered = _adapter(pool, secrets, transport, reopened).execute(
        binding=binding,
        canonical_request_body=request,
    )
    assert isinstance(recovered, TerminalBridgeCall)
    assert recovered.transport_dispatched is False
    assert recovered.readback == dispatched.readback
    assert len(transport.calls) == 1
    reopened.close()


@pytest.mark.parametrize("lane_relation", ("same_lane", "cross_lane"))
def test_valid_response_reused_across_logical_calls_or_lanes_fails_closed(
    tmp_path: Path,
    lane_relation: str,
) -> None:
    pool = make_pool(3)
    secrets = FakeSecrets(pool)
    transport = _ReplayFirstValidResponseTransport(pool, secrets)
    first_binding = make_binding()
    first_lane = pool.select(first_binding).bridge_id
    second_binding = _other_binding(
        pool,
        first_binding=first_binding,
        same_lane=lane_relation == "same_lane",
    )
    second_lane = pool.select(second_binding).bridge_id
    assert (second_lane == first_lane) is (lane_relation == "same_lane")
    assert second_binding.logical_call_id != first_binding.logical_call_id

    first_database = tmp_path / "first" / "journal.sqlite3"
    first_journal = BridgeJournal.create(
        first_database,
        integrity=HmacJournalIntegrity(JOURNAL_KEY),
    )
    first_nonce = _nonce("scheduler-intent:first")
    first_request = _request(first_nonce)
    first = _adapter(pool, secrets, transport, first_journal).execute(
        binding=first_binding,
        canonical_request_body=first_request,
    )
    assert isinstance(first, TerminalBridgeCall)
    assert first.readback.intent.request_identity_nonce == first_nonce
    first_journal.close()

    second_database = tmp_path / "second" / "journal.sqlite3"
    second_journal = BridgeJournal.create(
        second_database,
        integrity=HmacJournalIntegrity(JOURNAL_KEY),
    )
    second_adapter = _adapter(pool, secrets, transport, second_journal)
    second_nonce = _nonce(f"scheduler-intent:second:{lane_relation}")
    second_request = _request(second_nonce)

    rejection = (
        "bridge_request_identity_invalid"
        if lane_relation == "same_lane"
        else "bridge_system_fingerprint_invalid"
    )
    with pytest.raises(BridgeReceiptError, match=rejection):
        second_adapter.execute(
            binding=second_binding,
            canonical_request_body=second_request,
        )

    unknown = second_adapter.lookup_outcome(second_binding.intent_id)
    assert isinstance(unknown, OutcomeUnknown)
    retry = second_adapter.execute(
        binding=second_binding,
        canonical_request_body=second_request,
    )
    assert isinstance(retry, OutcomeUnknown)
    assert len(transport.calls) == 2
    assert first_nonce != second_nonce
    second_journal.close()


def test_journal_rejects_one_authenticated_physical_receipt_rewrapped_for_new_intent(
    tmp_path: Path,
) -> None:
    pool = make_pool()
    secrets = FakeSecrets(pool)
    transport = _ReplayFirstValidResponseTransport(pool, secrets)
    journal = BridgeJournal.create(
        tmp_path / "bridge" / "journal.sqlite3",
        integrity=HmacJournalIntegrity(JOURNAL_KEY),
    )
    adapter = _adapter(pool, secrets, transport, journal)
    request = _request(_nonce("same-request-authority"))
    first_binding = make_binding(1)
    second_binding = make_binding(2)

    first = adapter.execute(
        binding=first_binding,
        canonical_request_body=request,
    )
    assert isinstance(first, TerminalBridgeCall)

    with pytest.raises(
        BridgeDivergenceError,
        match="bridge_journal_provider_receipt_reused",
    ):
        adapter.execute(
            binding=second_binding,
            canonical_request_body=request,
        )

    assert isinstance(adapter.lookup_outcome(second_binding.intent_id), OutcomeUnknown)
    replay = adapter.execute(
        binding=first_binding,
        canonical_request_body=request,
    )
    unknown_retry = adapter.execute(
        binding=second_binding,
        canonical_request_body=request,
    )
    assert isinstance(replay, TerminalBridgeCall)
    assert replay.transport_dispatched is False
    assert isinstance(unknown_retry, OutcomeUnknown)
    assert len(transport.calls) == 2
    statistics = journal.statistics()
    assert (
        statistics.intent_count,
        statistics.result_count,
        statistics.physical_receipt_count,
        statistics.event_count,
    ) == (2, 1, 1, 3)
    journal.close()


def test_dispatch_binding_hmac_rejects_cross_intent_rewrap_in_fresh_journal(
    tmp_path: Path,
) -> None:
    pool = make_pool(3)
    secrets = FakeSecrets(pool)
    transport = AttestedFakeTransport(pool, secrets)
    request = _request(_nonce("same-provider-authenticated-request"))
    first_binding = make_binding()
    second_binding = _other_binding(pool, first_binding=first_binding, same_lane=True)

    first_journal = BridgeJournal.create(
        tmp_path / "first" / "journal.sqlite3",
        integrity=HmacJournalIntegrity(JOURNAL_KEY),
    )
    first = _adapter(pool, secrets, transport, first_journal).execute(
        binding=first_binding,
        canonical_request_body=request,
    )
    assert isinstance(first, TerminalBridgeCall)
    first_journal.close()

    second_journal = BridgeJournal.create(
        tmp_path / "second" / "journal.sqlite3",
        integrity=HmacJournalIntegrity(JOURNAL_KEY),
    )
    _bridge, second_intent = derive_bridge_intent(
        pool=pool,
        binding=second_binding,
        request_body=request,
        maximum_request_bytes=MAX_BYTES,
    )
    assert second_journal.record_intent(second_intent).dispatch_granted is True
    second_journal.record_result(second_intent, first.readback.result)

    second_adapter = _adapter(pool, secrets, transport, second_journal)
    with pytest.raises(BridgeReceiptError, match="dispatch_binding_hmac_mismatch"):
        second_adapter.lookup_outcome(second_binding.intent_id)
    assert len(transport.calls) == 1
    second_journal.close()


def _adapter(pool, secrets, transport, journal) -> SubscriptionRuntimeBridgeAdapter:
    return SubscriptionRuntimeBridgeAdapter(
        pool=pool,
        secrets=secrets,
        transport=transport,
        journal=journal,
        output_cipher=TestAuthenticatedCipher(),
        maximum_request_bytes=MAX_BYTES,
        maximum_response_bytes=MAX_BYTES,
    )


def _request(nonce: str) -> bytes:
    return canonical_openai_request_body(
        {
            "max_completion_tokens": 32,
            "messages": [{"content": "private prompt", "role": "user"}],
            "model": "subscription-codex",
            "user": nonce,
        }
    )


def _nonce(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _other_binding(pool, *, first_binding, same_lane: bool):
    first_lane = pool.select(first_binding).bridge_id
    for index in range(1, 10_000):
        candidate = make_binding(index)
        if candidate.logical_call_id == first_binding.logical_call_id:
            continue
        if (pool.select(candidate).bridge_id == first_lane) is same_lane:
            return candidate
    raise AssertionError("test_binding_for_lane_not_found")

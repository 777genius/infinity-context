from __future__ import annotations

import hashlib
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest
from infinity_context_server.features.subscription_runtime_bridge import (
    AuthenticatedBridgeResult,
    BridgeAuthority,
    BridgeAuthorityError,
    BridgeJournal,
    BridgePoolAuthority,
    BridgeReceiptError,
    BridgeTransportError,
    HmacJournalIntegrity,
    NotFound,
    OutcomeUnknown,
    PrivateOutputError,
    SubscriptionRuntimeBridgeAdapter,
    TerminalBridgeCall,
    TokenUsage,
    canonical_openai_request_body,
)
from infinity_context_server.features.subscription_runtime_bridge.attestation import (
    output_associated_data,
)
from infinity_context_server.features.subscription_runtime_bridge.request_contract import (
    derive_bridge_intent,
)
from subscription_runtime_bridge_test_support import (
    JOURNAL_KEY,
    AttestedFakeTransport,
    FakeSecrets,
    TestAuthenticatedCipher,
    make_binding,
    make_pool,
    make_request,
)

MAX_REQUEST = 256 * 1024
MAX_RESPONSE = 256 * 1024


def test_happy_path_exact_replay_reopen_and_private_output(tmp_path: Path) -> None:
    pool = make_pool()
    secrets = FakeSecrets(pool)
    transport = AttestedFakeTransport(pool, secrets)
    cipher = TestAuthenticatedCipher()
    database = tmp_path / "private" / "bridge.sqlite3"
    journal = BridgeJournal.create(database, integrity=HmacJournalIntegrity(JOURNAL_KEY))
    adapter = _adapter(pool, secrets, transport, cipher, journal)
    binding = make_binding()
    request = make_request()

    completed = adapter.execute(binding=binding, canonical_request_body=request)

    assert isinstance(completed, TerminalBridgeCall)
    assert completed.transport_dispatched is True
    assert completed.readback.intent.bridge_id == pool.select(binding).bridge_id
    assert completed.readback.result.usage.prompt_tokens == 10
    assert completed.readback.result.usage.completion_tokens == 4
    assert completed.readback.result.usage.total_tokens == 14
    assert completed.private_output.render_for_judge() == "private completion"
    assert completed.readback.result.encrypted_output != b"private completion"
    replay = adapter.execute(binding=binding, canonical_request_body=request)
    assert isinstance(replay, TerminalBridgeCall)
    assert replay.transport_dispatched is False
    assert replay.readback == completed.readback
    assert len(transport.calls) == 1
    assert isinstance(adapter.lookup_outcome("absent-intent"), NotFound)

    database_bytes = database.read_bytes()
    assert b"private prompt" not in database_bytes
    assert b"private completion" not in database_bytes
    assert secrets.authorization_bearer("bridge-0").encode() not in database_bytes
    assert secrets.attestation_secret("bridge-0") not in database_bytes
    journal.close()

    reopened = BridgeJournal.open(database, integrity=HmacJournalIntegrity(JOURNAL_KEY))
    reopened_adapter = _adapter(pool, secrets, transport, cipher, reopened)
    readback = reopened_adapter.lookup_outcome(binding.intent_id)
    assert isinstance(readback, TerminalBridgeCall)
    assert readback.transport_dispatched is False
    assert readback.readback == completed.readback
    assert readback.private_output.render_for_judge() == "private completion"
    assert len(transport.calls) == 1
    reopened.close()


def test_deterministic_three_bridge_shard_binds_every_intent_and_result(tmp_path: Path) -> None:
    pool = make_pool(3)
    secrets = FakeSecrets(pool)
    transport = AttestedFakeTransport(pool, secrets)
    journal = BridgeJournal.create(
        tmp_path / "private" / "bridge.sqlite3",
        integrity=HmacJournalIntegrity(JOURNAL_KEY),
    )
    adapter = _adapter(pool, secrets, transport, TestAuthenticatedCipher(), journal)

    expected: list[str] = []
    for index in range(24):
        binding = make_binding(index)
        expected.append(pool.select(binding).bridge_id)
        outcome = adapter.execute(
            binding=binding,
            canonical_request_body=make_request(
                identity_nonce=hashlib.sha256(f"intent-{index}".encode()).hexdigest()
            ),
        )
        assert isinstance(outcome, TerminalBridgeCall)
        assert outcome.readback.intent.bridge_id == expected[-1]
        assert (
            outcome.readback.intent.bridge_authority_sha256
            == pool.select(binding).commitment_sha256
        )

    assert [bridge_id for bridge_id, _body in transport.calls] == expected
    assert set(expected) == {"bridge-0", "bridge-1", "bridge-2"}
    journal.close()


def test_intent_only_reopen_is_unknown_and_never_dispatches_again(tmp_path: Path) -> None:
    pool = make_pool()
    secrets = FakeSecrets(pool)
    provider_execution = AttestedFakeTransport(pool, secrets)

    class CrashAfterExecution:
        calls = 0

        def post_once(self, **kwargs):
            self.calls += 1
            provider_execution.post_once(**kwargs)
            raise BridgeTransportError("simulated_response_loss")

    transport = CrashAfterExecution()
    database = tmp_path / "private" / "bridge.sqlite3"
    journal = BridgeJournal.create(database, integrity=HmacJournalIntegrity(JOURNAL_KEY))
    adapter = _adapter(pool, secrets, transport, TestAuthenticatedCipher(), journal)
    binding = make_binding()
    request = make_request()

    with pytest.raises(BridgeTransportError, match="simulated_response_loss"):
        adapter.execute(binding=binding, canonical_request_body=request)
    assert isinstance(adapter.lookup_outcome(binding.intent_id), OutcomeUnknown)
    assert transport.calls == 1
    assert len(provider_execution.calls) == 1
    journal.close()

    reopened = BridgeJournal.open(database, integrity=HmacJournalIntegrity(JOURNAL_KEY))
    reopened_adapter = _adapter(
        pool,
        secrets,
        transport,
        TestAuthenticatedCipher(),
        reopened,
    )
    replay = reopened_adapter.execute(binding=binding, canonical_request_body=request)
    assert isinstance(replay, OutcomeUnknown)
    assert transport.calls == 1
    assert len(provider_execution.calls) == 1
    reopened.close()


@pytest.mark.parametrize(
    ("case", "mutate"),
    [
        (
            "hmac",
            lambda value: value["subscription_runtime"].__setitem__(
                "receipt_hmac_sha256", "0" * 64
            ),
        ),
        (
            "account",
            lambda value: value["subscription_runtime"]["runtime_selection"].__setitem__(
                "account_binding_hmac_sha256", "0" * 64
            ),
        ),
        (
            "model",
            lambda value: value["subscription_runtime"]["runtime_selection"].__setitem__(
                "model", "gpt-wrong"
            ),
        ),
        (
            "reasoning",
            lambda value: value["subscription_runtime"]["runtime_selection"].__setitem__(
                "reasoning_effort", "low"
            ),
        ),
        (
            "tier",
            lambda value: value["subscription_runtime"]["runtime_selection"].__setitem__(
                "service_tier", "default"
            ),
        ),
        (
            "request",
            lambda value: value["subscription_runtime"]["request_identity"].__setitem__(
                "request_body_sha256", "0" * 64
            ),
        ),
        (
            "usage",
            lambda value: value["usage"].__setitem__("total_tokens", 15),
        ),
        (
            "output",
            lambda value: value["subscription_runtime"]["output_identity"].__setitem__(
                "output_text_sha256", "0" * 64
            ),
        ),
        (
            "output_ceiling",
            lambda value: value["usage"].update(
                completion_tokens=33,
                completion_tokens_details={"reasoning_tokens": 1},
                total_tokens=43,
            ),
        ),
    ],
)
def test_adversarial_receipt_stays_unknown_and_is_never_retried(
    tmp_path: Path,
    case: str,
    mutate,
) -> None:
    del case
    pool = make_pool()
    secrets = FakeSecrets(pool)
    transport = AttestedFakeTransport(pool, secrets, mutate=mutate)
    journal = BridgeJournal.create(
        tmp_path / "private" / "bridge.sqlite3",
        integrity=HmacJournalIntegrity(JOURNAL_KEY),
    )
    adapter = _adapter(pool, secrets, transport, TestAuthenticatedCipher(), journal)
    binding = make_binding()
    request = make_request()

    with pytest.raises(BridgeReceiptError):
        adapter.execute(binding=binding, canonical_request_body=request)
    assert isinstance(adapter.lookup_outcome(binding.intent_id), OutcomeUnknown)
    replay = adapter.execute(binding=binding, canonical_request_body=request)
    assert isinstance(replay, OutcomeUnknown)
    assert len(transport.calls) == 1
    journal.close()


@pytest.mark.parametrize(
    "raw_mutate",
    [
        lambda raw: b'{"id":"duplicate",' + raw[1:],
        lambda raw: raw.replace(b'"created":1786320000', b'"created":NaN'),
        lambda raw: raw + b" " * (MAX_RESPONSE + 1),
    ],
)
def test_duplicate_nonfinite_and_oversized_responses_are_rejected(
    tmp_path: Path,
    raw_mutate,
) -> None:
    pool = make_pool()
    secrets = FakeSecrets(pool)
    transport = AttestedFakeTransport(pool, secrets, raw_mutate=raw_mutate)
    journal = BridgeJournal.create(
        tmp_path / "private" / "bridge.sqlite3",
        integrity=HmacJournalIntegrity(JOURNAL_KEY),
    )
    adapter = _adapter(pool, secrets, transport, TestAuthenticatedCipher(), journal)
    binding = make_binding()

    with pytest.raises(BridgeReceiptError):
        adapter.execute(binding=binding, canonical_request_body=make_request())
    assert isinstance(adapter.lookup_outcome(binding.intent_id), OutcomeUnknown)
    journal.close()


@pytest.mark.parametrize(
    "request_body",
    [
        b'{"max_completion_tokens":32,"messages":[],"model":"a","model":"b"}',
        b'{"max_completion_tokens":NaN,"messages":[],"model":"subscription-codex"}',
        b'{ "max_completion_tokens":32,"messages":[],"model":"subscription-codex"}',
    ],
)
def test_ambiguous_or_noncanonical_request_never_records_or_dispatches(
    tmp_path: Path,
    request_body: bytes,
) -> None:
    pool = make_pool()
    secrets = FakeSecrets(pool)
    transport = AttestedFakeTransport(pool, secrets)
    journal = BridgeJournal.create(
        tmp_path / "private" / "bridge.sqlite3",
        integrity=HmacJournalIntegrity(JOURNAL_KEY),
    )
    adapter = _adapter(pool, secrets, transport, TestAuthenticatedCipher(), journal)
    binding = make_binding()

    with pytest.raises(ValueError):
        adapter.execute(binding=binding, canonical_request_body=request_body)
    assert isinstance(adapter.lookup_outcome(binding.intent_id), NotFound)
    assert transport.calls == []
    journal.close()


def test_oversized_request_never_records_or_dispatches(tmp_path: Path) -> None:
    pool = make_pool()
    secrets = FakeSecrets(pool)
    transport = AttestedFakeTransport(pool, secrets)
    journal = BridgeJournal.create(
        tmp_path / "private" / "bridge.sqlite3",
        integrity=HmacJournalIntegrity(JOURNAL_KEY),
    )
    adapter = SubscriptionRuntimeBridgeAdapter(
        pool=pool,
        secrets=secrets,
        transport=transport,
        journal=journal,
        output_cipher=TestAuthenticatedCipher(),
        maximum_request_bytes=32,
        maximum_response_bytes=MAX_RESPONSE,
    )

    with pytest.raises(ValueError):
        adapter.execute(binding=make_binding(), canonical_request_body=make_request())
    assert transport.calls == []
    journal.close()


@pytest.mark.parametrize(
    ("request_body", "error"),
    [
        (
            canonical_openai_request_body(
                {
                    "max_completion_tokens": 32,
                    "messages": [{"content": "x", "role": "user"}] * 201,
                    "model": "subscription-codex",
                }
            ),
            "messages_invalid",
        ),
        (
            canonical_openai_request_body(
                {
                    "max_completion_tokens": 32,
                    "messages": [{"content": "x", "role": "user"}],
                    "model": "subscription-codex",
                    "user": "0" * 64,
                    "response_format": {
                        "json_schema": {
                            "name": "unsupported_runtime_schema",
                            "schema": {
                                "additionalProperties": False,
                                "properties": {"label": {"minLength": 1, "type": "string"}},
                                "required": ["label"],
                                "type": "object",
                            },
                            "strict": True,
                        },
                        "type": "json_schema",
                    },
                }
            ),
            "keyword_unsupported",
        ),
        (
            canonical_openai_request_body(
                {
                    "max_completion_tokens": 32,
                    "messages": [{"content": "x", "role": "user"}],
                    "model": "subscription-codex",
                    "temperature": None,
                }
            ),
            "temperature_invalid",
        ),
        (
            canonical_openai_request_body(
                {
                    "max_completion_tokens": 32,
                    "max_tokens": None,
                    "messages": [{"content": "x", "role": "user"}],
                    "model": "subscription-codex",
                }
            ),
            "output_token_limit_invalid",
        ),
        (
            canonical_openai_request_body(
                {
                    "max_completion_tokens": 32,
                    "messages": [{"content": "x", "role": "user"}],
                    "model": "subscription-codex",
                    "response_format": None,
                }
            ),
            "response_format_invalid",
        ),
        (
            canonical_openai_request_body(
                {
                    "max_completion_tokens": 32,
                    "messages": [{"content": "x", "role": "user"}],
                    "model": "subscription-codex",
                    "reasoning_effort": "high",
                }
            ),
            "schema_invalid",
        ),
        (
            canonical_openai_request_body(
                {
                    "max_completion_tokens": 32,
                    "messages": [{"content": "x", "role": "user"}],
                    "model": "subscription-codex",
                    "reasoning_effort": "low",
                }
            ),
            "schema_invalid",
        ),
        (
            canonical_openai_request_body(
                {
                    "max_completion_tokens": 32,
                    "messages": [{"content": "x", "role": "user"}],
                    "model": "subscription-codex",
                    "service_tier": "priority",
                }
            ),
            "schema_invalid",
        ),
        (
            canonical_openai_request_body(
                {
                    "max_completion_tokens": 32,
                    "messages": [{"content": "x", "role": "user"}],
                    "model": "subscription-codex",
                    "service_tier": "default",
                }
            ),
            "schema_invalid",
        ),
        (
            canonical_openai_request_body(
                {
                    "future_runtime_selector": "ignored",
                    "max_completion_tokens": 32,
                    "messages": [{"content": "x", "role": "user"}],
                    "model": "subscription-codex",
                }
            ),
            "schema_invalid",
        ),
        (
            canonical_openai_request_body(
                {
                    "max_completion_tokens": 32,
                    "messages": [{"content": "x", "role": "user"}],
                    "model": "gpt-wrong",
                }
            ),
            "public_model_invalid",
        ),
    ],
)
def test_runtime_incompatible_request_is_rejected_before_intent_or_dispatch(
    tmp_path: Path,
    request_body: bytes,
    error: str,
) -> None:
    pool = make_pool()
    secrets = FakeSecrets(pool)
    transport = AttestedFakeTransport(pool, secrets)
    journal = BridgeJournal.create(
        tmp_path / "private" / "bridge.sqlite3",
        integrity=HmacJournalIntegrity(JOURNAL_KEY),
    )
    adapter = _adapter(pool, secrets, transport, TestAuthenticatedCipher(), journal)
    binding = make_binding()

    with pytest.raises(ValueError, match=error):
        adapter.execute(binding=binding, canonical_request_body=request_body)
    assert isinstance(adapter.lookup_outcome(binding.intent_id), NotFound)
    assert transport.calls == []
    journal.close()


def test_journal_authenticated_but_unsigned_result_is_never_exposed(tmp_path: Path) -> None:
    pool = make_pool()
    secrets = FakeSecrets(pool)
    transport = AttestedFakeTransport(pool, secrets)
    cipher = TestAuthenticatedCipher()
    journal = BridgeJournal.create(
        tmp_path / "private" / "bridge.sqlite3",
        integrity=HmacJournalIntegrity(JOURNAL_KEY),
    )
    binding = make_binding()
    _bridge, intent = derive_bridge_intent(
        pool=pool,
        binding=binding,
        request_body=make_request(),
        maximum_request_bytes=MAX_REQUEST,
    )
    assert journal.record_intent(intent).dispatch_granted is True
    plaintext = b"forged private completion"
    unsigned = AuthenticatedBridgeResult(
        response_body_sha256="a" * 64,
        output_text_sha256=hashlib.sha256(plaintext).hexdigest(),
        attestation_sha256="b" * 64,
        receipt_hmac_sha256="c" * 64,
        dispatch_binding_hmac_sha256="d" * 64,
        thread_id="thread-forged",
        turn_id="turn-forged",
        usage=TokenUsage(
            prompt_tokens=10,
            cached_tokens=2,
            cache_write_tokens=None,
            completion_tokens=4,
            reasoning_tokens=1,
            total_tokens=14,
        ),
        encrypted_output=b"placeholder",
    )
    unsigned = replace(
        unsigned,
        encrypted_output=cipher.seal(
            plaintext,
            associated_data=output_associated_data(intent, unsigned),
        ),
    )
    journal.record_result(intent, unsigned)

    adapter = _adapter(pool, secrets, transport, cipher, journal)
    with pytest.raises(BridgeReceiptError, match="persisted_attestation_mismatch"):
        adapter.lookup_outcome(binding.intent_id)
    assert transport.calls == []
    journal.close()


def test_ciphertext_expansion_cannot_exceed_the_durable_response_bound(tmp_path: Path) -> None:
    class OversizedCipher:
        def seal(self, _plaintext: bytes, *, associated_data: bytes) -> bytes:
            del associated_data
            return b"x" * (MAX_RESPONSE + 1)

        def open(self, _ciphertext: bytes, *, associated_data: bytes) -> bytes:
            del associated_data
            raise AssertionError("oversized ciphertext must never become readable")

    pool = make_pool()
    secrets = FakeSecrets(pool)
    transport = AttestedFakeTransport(pool, secrets)
    journal = BridgeJournal.create(
        tmp_path / "private" / "bridge.sqlite3",
        integrity=HmacJournalIntegrity(JOURNAL_KEY),
    )
    binding = make_binding()
    adapter = _adapter(pool, secrets, transport, OversizedCipher(), journal)

    with pytest.raises(PrivateOutputError, match="ciphertext_invalid"):
        adapter.execute(binding=binding, canonical_request_body=make_request())
    assert isinstance(adapter.lookup_outcome(binding.intent_id), OutcomeUnknown)
    assert len(transport.calls) == 1
    journal.close()


def test_wrong_output_key_and_ciphertext_swap_reject_decryption(tmp_path: Path) -> None:
    pool = make_pool()
    secrets = FakeSecrets(pool)
    transport = AttestedFakeTransport(pool, secrets)
    cipher = TestAuthenticatedCipher()
    journal = BridgeJournal.create(
        tmp_path / "private" / "bridge.sqlite3",
        integrity=HmacJournalIntegrity(JOURNAL_KEY),
    )
    adapter = _adapter(pool, secrets, transport, cipher, journal)
    first = adapter.execute(
        binding=make_binding(1),
        canonical_request_body=make_request(identity_nonce=hashlib.sha256(b"intent-1").hexdigest()),
    )
    second = adapter.execute(
        binding=make_binding(2),
        canonical_request_body=make_request(identity_nonce=hashlib.sha256(b"intent-2").hexdigest()),
    )
    assert isinstance(first, TerminalBridgeCall)
    assert isinstance(second, TerminalBridgeCall)

    wrong_key_adapter = _adapter(
        pool,
        secrets,
        transport,
        TestAuthenticatedCipher(b"wrong-output-key-32-bytes-minimum!!"),
        journal,
    )
    wrong_key_outcome = wrong_key_adapter.lookup_outcome(make_binding(1).intent_id)
    assert isinstance(wrong_key_outcome, TerminalBridgeCall)
    with pytest.raises(PrivateOutputError, match="decryption_failed"):
        wrong_key_outcome.private_output.render_for_judge()

    second_aad = output_associated_data(second.readback.intent, second.readback.result)
    with pytest.raises(ValueError, match="authentication_failed"):
        cipher.open(first.readback.result.encrypted_output, associated_data=second_aad)
    journal.close()


def test_authority_is_immutable_loopback_only_and_secret_free() -> None:
    pool = make_pool()
    authority = pool.bridges[0]
    with pytest.raises(FrozenInstanceError):
        authority.origin = "http://127.0.0.1:1"  # type: ignore[misc]
    with pytest.raises(BridgeAuthorityError, match="not_loopback"):
        BridgeAuthority(
            bridge_id="bad",
            origin="https://example.com:443",
            account_binding_hmac_sha256="a" * 64,
            public_model="subscription-codex",
            base_instructions_sha256="b" * 64,
        )
    public = pool.public_payload()
    rendered = repr(public)
    assert "bearer" not in rendered
    assert "attestation-secret" not in rendered
    assert authority.CODEX_MODEL == "gpt-5.6-sol"
    assert authority.REASONING_EFFORT == "high"
    assert authority.SERVICE_TIER == "priority"


def test_json_schema_response_format_hashes_are_authenticated(tmp_path: Path) -> None:
    pool = make_pool()
    secrets = FakeSecrets(pool)
    transport = AttestedFakeTransport(pool, secrets)
    journal = BridgeJournal.create(
        tmp_path / "private" / "bridge.sqlite3",
        integrity=HmacJournalIntegrity(JOURNAL_KEY),
    )
    request = canonical_openai_request_body(
        {
            "max_completion_tokens": 16,
            "messages": [{"content": "judge privately", "role": "user"}],
            "model": "subscription-codex",
            "user": "0" * 64,
            "response_format": {
                "json_schema": {
                    "name": "judge",
                    "schema": {
                        "additionalProperties": False,
                        "properties": {"label": {"enum": ["OK"], "type": "string"}},
                        "required": ["label"],
                        "type": "object",
                    },
                    "strict": True,
                },
                "type": "json_schema",
            },
        }
    )
    outcome = _adapter(pool, secrets, transport, TestAuthenticatedCipher(), journal).execute(
        binding=make_binding(operation="judge"), canonical_request_body=request
    )
    assert isinstance(outcome, TerminalBridgeCall)
    assert outcome.readback.intent.response_format_type == "json_schema"
    assert outcome.readback.intent.response_schema_sha256 is not None
    journal.close()


def test_runtime_utf16_schema_key_order_and_unicode_model_are_exact(tmp_path: Path) -> None:
    authority = BridgeAuthority(
        bridge_id="bridge-unicode",
        origin="http://127.0.0.1:43100",
        account_binding_hmac_sha256="a" * 64,
        public_model="subscription-模型",
        base_instructions_sha256="b" * 64,
    )
    pool = BridgePoolAuthority(pool_id="unicode-pool", bridges=(authority,))
    secrets = FakeSecrets(pool)
    transport = AttestedFakeTransport(pool, secrets)
    journal = BridgeJournal.create(
        tmp_path / "private" / "bridge.sqlite3",
        integrity=HmacJournalIntegrity(JOURNAL_KEY),
    )
    request = canonical_openai_request_body(
        {
            "max_completion_tokens": 16,
            "messages": [{"content": "judge privately", "role": "user"}],
            "model": authority.public_model,
            "user": "0" * 64,
            "response_format": {
                "json_schema": {
                    "name": "unicode_keys",
                    "schema": {
                        "additionalProperties": False,
                        "properties": {
                            "\ue000": {"type": "string"},
                            "\U00010000": {"type": "string"},
                        },
                        "required": ["\ue000", "\U00010000"],
                        "type": "object",
                    },
                    "strict": True,
                },
                "type": "json_schema",
            },
        }
    )

    outcome = _adapter(pool, secrets, transport, TestAuthenticatedCipher(), journal).execute(
        binding=make_binding(operation="judge"),
        canonical_request_body=request,
    )

    assert isinstance(outcome, TerminalBridgeCall)
    assert (
        outcome.readback.intent.response_format_sha256
        == "9ba6c3dd9133debe7150ccf647a7bb4db1b5be7b18f79ae071b2764fc8a5fb3f"
    )
    assert (
        outcome.readback.intent.response_schema_sha256
        == "259eaec11210565fe4e63480c496deb604bbc7b889a121e34f5c344912fb77f1"
    )
    journal.close()


def _adapter(pool, secrets, transport, cipher, journal) -> SubscriptionRuntimeBridgeAdapter:
    return SubscriptionRuntimeBridgeAdapter(
        pool=pool,
        secrets=secrets,
        transport=transport,
        journal=journal,
        output_cipher=cipher,
        maximum_request_bytes=MAX_REQUEST,
        maximum_response_bytes=MAX_RESPONSE,
    )

"""Bounded provider-free support for the complete scheduler bridge traversal."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace

from infinity_context_core.ports.managed_full_run_extraction_ledger import (
    FULL_RUN_EXTRACTION_LEDGER_SCHEMA,
    FULL_RUN_EXTRACTION_PAGE_SIZE,
    ManagedFullRunExtractionContext,
    ManagedFullRunExtractionTerminal,
    canonical_sha256,
)
from infinity_context_runtime_bridge import (
    BridgeAuthority,
    BridgePoolAuthority,
    OutputCipherKey,
)
from infinity_context_runtime_bridge.contracts import (
    physical_provider_receipt_sha256,
)
from infinity_context_runtime_bridge.json_boundary import (
    canonical_json_bytes,
)
from infinity_context_server.processes.publishable_full_extraction_suite import (
    PUBLISHABLE_EXTRACTION_BENCHMARKS,
    PublishableExtractionSuiteReadback,
)
from infinity_context_server.processes.publishable_full_extraction_worker import (
    PublishableExtractionRunTerminal,
)
from infinity_context_server.publishable_durable_scheduler.contracts import (
    SchedulerSuiteAuthority,
)
from infinity_context_server.publishable_durable_scheduler.runner_contracts import (
    LOCOMO_EXTRACTION_OPERATION_COUNT,
    LONGMEMEVAL_EXTRACTION_OPERATION_COUNT,
    PUBLISHABLE_SUITE_CASE_COUNT,
    PUBLISHABLE_SUITE_EVALUATION_CALL_COUNT,
    SchedulerRunStoreSpec,
)
from infinity_context_server.publishable_durable_scheduler.runner_request_composition import (
    SchedulerAuthenticatedOfficialCase,
    SchedulerAuthenticatedRetrievalEvidence,
    SchedulerOfficialCaseKey,
    SchedulerRetrievalEvidenceKey,
    official_case_material_sha256,
)
from scheduler_subscription_bridge_composition_test_support import (
    SyntheticCaseReader,
    SyntheticRetrievalReader,
    sha,
)
from subscription_runtime_bridge_test_support import (
    FakeSecrets,
    build_runtime_response,
    runtime_attestation_canonical_bytes,
)

FULL_TRAVERSAL_TRANSPORT_CALL_CAP = PUBLISHABLE_SUITE_EVALUATION_CALL_COUNT
FULL_TRAVERSAL_CASE_READ_CAP = (
    PUBLISHABLE_SUITE_EVALUATION_CALL_COUNT + PUBLISHABLE_SUITE_CASE_COUNT + 4
)
FULL_TRAVERSAL_RETRIEVAL_READ_CAP = PUBLISHABLE_SUITE_EVALUATION_CALL_COUNT // 2
FULL_TRAVERSAL_NONCE_CAP = PUBLISHABLE_SUITE_EVALUATION_CALL_COUNT

_OUTPUT_KEY_ID = "scheduler-full-traversal-output-key-v1"
_OUTPUT_KEY_SECRET = hashlib.sha256(
    b"scheduler-subscription-bridge/full-traversal/output-key/v1"
).digest()
_NONCE_PREFIX = b"ICFT"
_NONCE_BYTES = 12


class BoundedAttestedFakeTransport:
    """Return official fake receipts while retaining counters, never request bodies."""

    __slots__ = (
        "_bridges_by_origin",
        "_secrets",
        "authenticated_physical_receipt_sha256",
        "call_count",
        "call_count_by_bridge_id",
        "maximum_request_bytes_observed",
        "maximum_response_bytes_observed",
        "request_identity_nonces",
    )

    def __init__(self, pool: BridgePoolAuthority, secrets: FakeSecrets) -> None:
        self._bridges_by_origin = {bridge.origin: bridge for bridge in pool.bridges}
        self._secrets = secrets
        self.authenticated_physical_receipt_sha256: set[str] = set()
        self.call_count = 0
        self.call_count_by_bridge_id = {bridge.bridge_id: 0 for bridge in pool.bridges}
        self.maximum_request_bytes_observed = 0
        self.maximum_response_bytes_observed = 0
        self.request_identity_nonces: set[str] = set()

    @property
    def calls(self) -> int:
        """Number of dispatched calls; unlike the small fake, this is not a body list."""

        return self.call_count

    def post_once(
        self,
        *,
        origin: str,
        route: str,
        bearer_token: str,
        request_body: bytes,
        maximum_response_bytes: int,
    ) -> bytes:
        if self.call_count >= FULL_TRAVERSAL_TRANSPORT_CALL_CAP:
            raise AssertionError("full_traversal_transport_call_cap_exceeded")
        bridge = self._bridges_by_origin.get(origin)
        if bridge is None:
            raise AssertionError("full_traversal_transport_origin_unknown")
        self._assert_bridge_request(
            bridge=bridge,
            route=route,
            bearer_token=bearer_token,
            request_body=request_body,
        )

        response_payload = build_runtime_response(
            bridge=bridge,
            request_body=request_body,
            secret=self._secrets.attestation_secret(bridge.bridge_id),
            output_text=self._output_text(),
        )
        runtime_receipt = response_payload["subscription_runtime"]
        receipt_hmac = runtime_receipt["receipt_hmac_sha256"]
        request_nonce = json.loads(request_body)["user"]
        if (
            type(receipt_hmac) is not str
            or len(receipt_hmac) != 64
            or type(request_nonce) is not str
            or len(request_nonce) != 64
        ):
            raise AssertionError("full_traversal_physical_receipt_identity_invalid")
        attestation = runtime_attestation_canonical_bytes(
            selection=runtime_receipt["runtime_selection"],
            request_identity=runtime_receipt["request_identity"],
            output_identity=runtime_receipt["output_identity"],
            usage=response_payload["usage"],
            requested_tokens=runtime_receipt["output_token_limit"]["requested_tokens"],
        )
        self.authenticated_physical_receipt_sha256.add(
            physical_provider_receipt_sha256(
                attestation_sha256=hashlib.sha256(attestation).hexdigest(),
                receipt_hmac_sha256=receipt_hmac,
            )
        )
        self.request_identity_nonces.add(request_nonce)
        response = canonical_json_bytes(response_payload)
        self.maximum_request_bytes_observed = max(
            self.maximum_request_bytes_observed,
            len(request_body),
        )
        self.maximum_response_bytes_observed = max(
            self.maximum_response_bytes_observed,
            len(response),
        )
        if len(response) > maximum_response_bytes:
            raise AssertionError("full_traversal_transport_response_cap_exceeded")
        self.call_count += 1
        self.call_count_by_bridge_id[bridge.bridge_id] += 1
        return response

    def _output_text(self) -> str:
        slot = self.call_count % 4
        if slot in (0, 2):
            return "Postgres"
        infinity = slot == 1
        if self.call_count < 6_160:
            label = "CORRECT" if infinity else "WRONG"
            return f'{{"reasoning":"exact","label":"{label}"}}'
        verdict = "yes" if infinity else "no"
        return f"<thinking>exact</thinking>{verdict}"

    def _assert_bridge_request(
        self,
        *,
        bridge: BridgeAuthority,
        route: str,
        bearer_token: str,
        request_body: bytes,
    ) -> None:
        if route != bridge.route:
            raise AssertionError("full_traversal_transport_route_crosswire")
        if bearer_token != self._secrets.authorization_bearer(bridge.bridge_id):
            raise AssertionError("full_traversal_transport_bearer_crosswire")
        if type(request_body) is not bytes:
            raise AssertionError("full_traversal_transport_request_invalid")


class CountingOfficialCaseReader:
    """Delegate to the official synthetic authority with bounded aggregate counts."""

    __slots__ = ("_delegate", "read_count", "read_count_by_benchmark")

    authority_root_sha256 = SyntheticCaseReader.authority_root_sha256

    def __init__(self) -> None:
        self._delegate = SyntheticCaseReader()
        self.read_count = 0
        self.read_count_by_benchmark = {"locomo": 0, "longmemeval": 0}

    def read_exact(
        self,
        *,
        key: SchedulerOfficialCaseKey,
    ) -> SchedulerAuthenticatedOfficialCase:
        if self.read_count >= FULL_TRAVERSAL_CASE_READ_CAP:
            raise AssertionError("full_traversal_case_read_cap_exceeded")
        result = self._delegate.read_exact(key=key)
        metadata = dict(result.case.metadata)
        if key.benchmark.value == "locomo":
            metadata["category"] = _locomo_category(key.case_index)
        else:
            metadata["question_type"] = _longmemeval_question_type(key.case_index)
        case = replace(result.case, metadata=metadata)
        result = SchedulerAuthenticatedOfficialCase(
            key=key,
            material_sha256=official_case_material_sha256(key, case),
            case=case,
        )
        self.read_count += 1
        self.read_count_by_benchmark[key.benchmark.value] += 1
        return result


def _locomo_category(case_index: int) -> int:
    for end, category in ((282, 1), (603, 2), (699, 3), (1_540, 4)):
        if case_index < end:
            return category
    raise AssertionError("full_traversal_locomo_case_index_invalid")


def _longmemeval_question_type(case_index: int) -> str:
    for end, question_type in (
        (78, "knowledge-update"),
        (211, "multi-session"),
        (267, "single-session-assistant"),
        (297, "single-session-preference"),
        (367, "single-session-user"),
        (500, "temporal-reasoning"),
    ):
        if case_index < end:
            return question_type
    raise AssertionError("full_traversal_longmemeval_case_index_invalid")


class CountingRetrievalEvidenceReader:
    """Delegate retrieval reads with bounded benchmark/backend aggregate counts."""

    __slots__ = (
        "_delegate",
        "read_count",
        "read_count_by_backend_role",
        "read_count_by_benchmark",
        "read_count_by_benchmark_and_backend",
    )

    authority_root_sha256 = SyntheticRetrievalReader.authority_root_sha256

    def __init__(self) -> None:
        self._delegate = SyntheticRetrievalReader()
        self.read_count = 0
        self.read_count_by_benchmark = {"locomo": 0, "longmemeval": 0}
        self.read_count_by_backend_role = {"infinity-context": 0, "mem0": 0}
        self.read_count_by_benchmark_and_backend = {
            (benchmark, backend): 0
            for benchmark in ("locomo", "longmemeval")
            for backend in ("infinity-context", "mem0")
        }

    def read_exact(
        self,
        *,
        key: SchedulerRetrievalEvidenceKey,
    ) -> SchedulerAuthenticatedRetrievalEvidence:
        if self.read_count >= FULL_TRAVERSAL_RETRIEVAL_READ_CAP:
            raise AssertionError("full_traversal_retrieval_read_cap_exceeded")
        result = self._delegate.read_exact(key=key)
        benchmark = key.case_key.benchmark.value
        self.read_count += 1
        self.read_count_by_benchmark[benchmark] += 1
        self.read_count_by_backend_role[key.backend_role] += 1
        self.read_count_by_benchmark_and_backend[(benchmark, key.backend_role)] += 1
        return result


class DeterministicOutputKeyResolver:
    """Resolve one stable AES-256-GCM test key across composition reopenings."""

    __slots__ = ("_key", "active_key_call_count", "resolve_key_call_count")

    def __init__(self) -> None:
        self._key = OutputCipherKey(_OUTPUT_KEY_ID, _OUTPUT_KEY_SECRET)
        self.active_key_call_count = 0
        self.resolve_key_call_count = 0

    def active_key(self) -> OutputCipherKey:
        self.active_key_call_count += 1
        return self._key

    def resolve_key(self, key_id: str, /) -> OutputCipherKey:
        self.resolve_key_call_count += 1
        if key_id != self._key.key_id:
            raise KeyError("full_traversal_output_key_unknown")
        return self._key


class DeterministicNonceSource:
    """Issue up to 8,160 globally indexed, deterministic, unique 12-byte nonces."""

    __slots__ = ("_next_index", "call_count")

    def __init__(self, *, start_index: int = 0) -> None:
        if type(start_index) is not int or not 0 <= start_index <= FULL_TRAVERSAL_NONCE_CAP:
            raise ValueError("full_traversal_nonce_start_invalid")
        self._next_index = start_index
        self.call_count = 0

    @property
    def next_index(self) -> int:
        return self._next_index

    def __call__(self, size: int) -> bytes:
        if size != _NONCE_BYTES:
            raise ValueError("full_traversal_nonce_size_invalid")
        if self._next_index >= FULL_TRAVERSAL_NONCE_CAP:
            raise AssertionError("full_traversal_nonce_cap_exceeded")
        index = self._next_index
        self._next_index += 1
        self.call_count += 1
        return _NONCE_PREFIX + index.to_bytes(8, "big")


def synthetic_extraction_suite_readback(
    suite: SchedulerSuiteAuthority,
    specs: tuple[SchedulerRunStoreSpec, SchedulerRunStoreSpec],
) -> PublishableExtractionSuiteReadback:
    """Build the real sealed-suite contracts bound to the scheduler authorities."""

    expected_counts = (
        LOCOMO_EXTRACTION_OPERATION_COUNT,
        LONGMEMEVAL_EXTRACTION_OPERATION_COUNT,
    )
    if tuple(count for _, count in PUBLISHABLE_EXTRACTION_BENCHMARKS) != expected_counts:
        raise AssertionError("full_traversal_extraction_operation_authority_drift")
    terminals = tuple(
        _synthetic_extraction_run_terminal(
            suite=suite,
            spec=spec,
            index=index,
            profile_id=profile_id,
            receipt_count=receipt_count,
        )
        for index, (spec, (profile_id, receipt_count)) in enumerate(
            zip(specs, PUBLISHABLE_EXTRACTION_BENCHMARKS, strict=True)
        )
    )
    return PublishableExtractionSuiteReadback(
        locomo_terminal=terminals[0],
        longmemeval_terminal=terminals[1],
    )


def _synthetic_extraction_run_terminal(
    *,
    suite: SchedulerSuiteAuthority,
    spec: SchedulerRunStoreSpec,
    index: int,
    profile_id: str,
    receipt_count: int,
) -> PublishableExtractionRunTerminal:
    run = spec.run
    context = ManagedFullRunExtractionContext(
        profile_id=profile_id,
        run_id_sha256=hashlib.sha256(run.binding.run_id.encode("utf-8")).hexdigest(),
        binding_commitment_sha256=run.binding.binding_commitment_sha256,
        methodology_commitment_sha256=suite.methodology_sha256,
        admission_commitment_sha256=sha(f"full-traversal-admission:{index}"),
        ingestion_root_sha256=sha(f"full-traversal-ingestion:{index}"),
        a1_terminal_commitment_sha256=sha(f"full-traversal-a1-terminal:{index}"),
        a1_manifest_context_sha256=sha(f"full-traversal-a1-context:{index}"),
        runtime_binding_commitment_sha256=sha(f"full-traversal-phase-c-runtime:{index}"),
        expected_receipt_count=receipt_count,
    )
    page_count = (
        receipt_count + FULL_RUN_EXTRACTION_PAGE_SIZE - 1
    ) // FULL_RUN_EXTRACTION_PAGE_SIZE
    pages_root = sha(f"full-traversal-receipt-pages:{index}")
    ledger_body = {
        "schema_version": FULL_RUN_EXTRACTION_LEDGER_SCHEMA,
        "context_commitment_sha256": context.commitment_sha256,
        "receipt_count": receipt_count,
        "page_count": page_count,
        "receipt_pages_root_sha256": pages_root,
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }
    ledger = ManagedFullRunExtractionTerminal(
        context_commitment_sha256=context.commitment_sha256,
        receipt_count=receipt_count,
        page_count=page_count,
        receipt_pages_root_sha256=pages_root,
        prompt_tokens=0,
        completion_tokens=0,
        total_tokens=0,
        terminal_commitment_sha256=canonical_sha256(ledger_body),
    )
    return PublishableExtractionRunTerminal(
        profile_id=context.profile_id,
        run_id_sha256=context.run_id_sha256,
        binding_commitment_sha256=context.binding_commitment_sha256,
        methodology_commitment_sha256=context.methodology_commitment_sha256,
        admission_commitment_sha256=context.admission_commitment_sha256,
        ingestion_root_sha256=context.ingestion_root_sha256,
        a1_terminal_commitment_sha256=context.a1_terminal_commitment_sha256,
        a1_manifest_context_sha256=context.a1_manifest_context_sha256,
        runtime_binding_commitment_sha256=context.runtime_binding_commitment_sha256,
        scheduler_bridge_runtime_authority_sha256=(suite.bridge_boot.runtime_authority_sha256),
        preparation_receipt_sha256=sha(f"full-traversal-preparation:{index}"),
        dataset_sha256=run.binding.dataset_sha256,
        a2_terminal_commitment_sha256=sha(f"full-traversal-a2-terminal:{index}"),
        expected_receipt_count=receipt_count,
        journal_manifest_commitment_sha256=sha(f"full-traversal-journal-manifest:{index}"),
        journal_state_commitment_sha256=sha(f"full-traversal-journal-state:{index}"),
        journal_head_event_sha256=sha(f"full-traversal-journal-head:{index}"),
        ledger_terminal=ledger,
    )


__all__ = (
    "BoundedAttestedFakeTransport",
    "CountingOfficialCaseReader",
    "CountingRetrievalEvidenceReader",
    "DeterministicNonceSource",
    "DeterministicOutputKeyResolver",
    "FULL_TRAVERSAL_CASE_READ_CAP",
    "FULL_TRAVERSAL_NONCE_CAP",
    "FULL_TRAVERSAL_RETRIEVAL_READ_CAP",
    "FULL_TRAVERSAL_TRANSPORT_CALL_CAP",
    "synthetic_extraction_suite_readback",
)

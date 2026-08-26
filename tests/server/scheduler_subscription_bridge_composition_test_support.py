"""Provider-free capabilities for the scheduler/subscription-bridge seam tests."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import replace

from infinity_context_core.ports.managed_full_run_extraction_ledger import (
    FULL_RUN_EXTRACTION_PAGE_SIZE,
    ManagedFullRunExtractionContext,
    ManagedFullRunExtractionTerminal,
    canonical_sha256,
)
from infinity_context_runtime_bridge import (
    BridgeAuthority,
    BridgePoolAuthority,
)
from infinity_context_runtime_bridge.process_contracts import (
    BridgeFleetReadinessReceipt,
    BridgeLaunchReceipt,
    PendingLaunchMetadata,
    ProcessIdentity,
    RuntimeHealthEvidence,
)
from infinity_context_server.memory_comparison_models import RetrievedMemory
from infinity_context_server.memory_comparison_publishable_methodology import (
    PUBLISHABLE_PRIORITY_METHODOLOGY_V4_COMMITMENT_SHA256,
    SUBSCRIPTION_RUNTIME_BASE_INSTRUCTIONS_SHA256,
)
from infinity_context_server.memory_comparison_publishable_profile import (
    public_publishable_comparison_profile,
    publishable_priority_comparison_profile_v4,
)
from infinity_context_server.public_benchmark_models import PublicBenchmarkCase
from infinity_context_server.publishable_durable_scheduler import (
    scheduler_subscription_bridge_adapter as scheduler_bridge_adapter,
)
from infinity_context_server.publishable_durable_scheduler.contracts import (
    LOCOMO_PROFILE,
    LONGMEMEVAL_PROFILE,
    SchedulerBackendAuthority,
    SchedulerDeadlineTokenAuthority,
    SchedulerRunBinding,
    SchedulerSuiteAuthority,
    run_authority_from_suite,
)
from infinity_context_server.publishable_durable_scheduler.manifest import (
    SchedulerCaseAuthority,
    build_scheduler_manifest,
    case_manifest_sha256,
)
from infinity_context_server.publishable_durable_scheduler.runner_contracts import (
    LOCOMO_EXTRACTION_OPERATION_COUNT,
    LONGMEMEVAL_EXTRACTION_OPERATION_COUNT,
    SchedulerExtractionTerminalEvidence,
    SchedulerRunStoreSpec,
    authenticate_extraction_terminal,
)
from infinity_context_server.publishable_durable_scheduler.runner_official_request_renderer import (
    SCHEDULER_OFFICIAL_REQUEST_MAX_OUTPUT_TOKENS,
    SCHEDULER_OFFICIAL_REQUEST_MODEL,
)
from infinity_context_server.publishable_durable_scheduler.runner_request_composition import (
    SchedulerAuthenticatedOfficialCase,
    SchedulerAuthenticatedRetrievalEvidence,
    SchedulerDecryptedPrivateAnswer,
    official_case_material_sha256,
    retrieval_evidence_material_sha256,
)

CASE_ROOT = hashlib.sha256(b"scheduler-bridge-case-root").hexdigest()
RETRIEVAL_ROOT = hashlib.sha256(b"scheduler-bridge-retrieval-root").hexdigest()
DECRYPT_POLICY = hashlib.sha256(b"scheduler-bridge-decrypt-policy").hexdigest()
BRIDGE_JOURNAL_KEY = b"scheduler-bridge-journal-integrity-key-material"
RUN_STORE_SECRETS = (
    b"scheduler-locomo-store-authentication-key",
    b"scheduler-longmem-store-authentication-key",
)
_CIPHER_KEY = b"scheduler-bridge-test-output-key-material"
_LAUNCHER_RECEIPT_KEY = b"scheduler-bridge-test-launcher-receipt-key-material"


def sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def bridge_pool(size: int = 3) -> BridgePoolAuthority:
    return BridgePoolAuthority(
        pool_id="publishable-scheduler-pool",
        bridges=tuple(
            BridgeAuthority(
                bridge_id=f"scheduler-bridge-{index}",
                origin=f"http://127.0.0.1:{45200 + index}",
                account_binding_hmac_sha256=sha(f"account:{index}"),
                public_model=SCHEDULER_OFFICIAL_REQUEST_MODEL,
                base_instructions_sha256=SUBSCRIPTION_RUNTIME_BASE_INSTRUCTIONS_SHA256,
            )
            for index in range(size)
        ),
    )


def bridge_fleet_readiness(
    pool: BridgePoolAuthority | None = None,
) -> BridgeFleetReadinessReceipt:
    selected_pool = pool or bridge_pool()
    launches = []
    for index, bridge in enumerate(selected_pool.bridges):
        runtime_authority_sha256 = sha(f"runtime-authority:{bridge.commitment_sha256}")
        pending = PendingLaunchMetadata.issue(
            account_name=f"account-{index + 10}",
            bridge_id=bridge.bridge_id,
            generation=1,
            launch_id=sha(f"launch:{index}:{bridge.commitment_sha256}"),
            mode="create",
            process=ProcessIdentity(
                pid=51_000 + index,
                start_ticks=710_000 + index,
                pgid=51_000 + index,
                boot_id="11111111-2222-4333-8444-555555555555",
            ),
            runtime_authority_sha256=runtime_authority_sha256,
            started_at_unix_ms=1_000 + index,
            key=_LAUNCHER_RECEIPT_KEY,
        )
        launches.append(
            BridgeLaunchReceipt.issue(
                pending=pending,
                health=RuntimeHealthEvidence(
                    response_body_sha256=sha(f"health:{index}"),
                    observed_at_unix_ms=1_100 + index,
                ),
                bridge_authority_sha256=bridge.commitment_sha256,
                runtime_authority_sha256=runtime_authority_sha256,
                ready_at_unix_ms=1_200 + index,
                key=_LAUNCHER_RECEIPT_KEY,
            )
        )
    return BridgeFleetReadinessReceipt(
        pool=selected_pool,
        launches=tuple(launches),
    )


def official_suite_and_manifests(readiness: BridgeFleetReadinessReceipt):
    profile = public_publishable_comparison_profile(publishable_priority_comparison_profile_v4())
    case_groups = tuple(
        tuple(
            SchedulerCaseAuthority(
                case_id=f"{benchmark}-case-{index}",
                case_alias=f"{benchmark}-{index}",
            )
            for index in range(scheduler_profile.case_count)
        )
        for benchmark, scheduler_profile in (
            ("locomo", LOCOMO_PROFILE),
            ("longmemeval", LONGMEMEVAL_PROFILE),
        )
    )
    backends = (
        SchedulerBackendAuthority("infinity-context", sha("infinity-target")),
        SchedulerBackendAuthority("mem0", sha("mem0-target")),
    )

    def binding(index: int) -> SchedulerRunBinding:
        scheduler_profile = (LOCOMO_PROFILE, LONGMEMEVAL_PROFILE)[index]
        benchmark = scheduler_profile.benchmark.value
        limits = SchedulerDeadlineTokenAuthority(
            dispatch_not_before_unix_ms=1_000,
            dispatch_deadline_unix_ms=100_000,
            answer_max_output_tokens=SCHEDULER_OFFICIAL_REQUEST_MAX_OUTPUT_TOKENS,
            judge_max_output_tokens=SCHEDULER_OFFICIAL_REQUEST_MAX_OUTPUT_TOKENS,
            run_token_ceiling=(
                scheduler_profile.case_count * 4 * SCHEDULER_OFFICIAL_REQUEST_MAX_OUTPUT_TOKENS
            ),
        )
        return SchedulerRunBinding(
            run_id=f"{benchmark}-scheduler-bridge-run",
            profile=scheduler_profile,
            binding_commitment_sha256=sha(f"binding:{benchmark}"),
            dataset_sha256=profile["benchmarks"][benchmark]["dataset_sha256"],
            case_manifest_sha256=case_manifest_sha256(case_groups[index]),
            backends=backends,
            limits=limits,
        )

    suite = SchedulerSuiteAuthority(
        suite_id="publishable-scheduler-bridge-suite",
        publication_bundle_sha256=sha("publication-bundle"),
        methodology_sha256=PUBLISHABLE_PRIORITY_METHODOLOGY_V4_COMMITMENT_SHA256,
        source_commit_sha256=sha("source-commit"),
        bridge_boot=scheduler_bridge_adapter.build_subscription_runtime_scheduler_bridge_boot_authority_from_fleet_readiness(
            readiness
        ),
        ordered_runs=(binding(0), binding(1)),
    )
    runs = tuple(run_authority_from_suite(suite, run_index=index) for index in (0, 1))
    manifests = tuple(
        build_scheduler_manifest(run, suite=suite, ordered_cases=cases)
        for run, cases in zip(runs, case_groups, strict=True)
    )
    return suite, runs, manifests, case_groups


def run_store_specs(tmp_path, suite, runs, manifests):
    tmp_path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return tuple(
        SchedulerRunStoreSpec(
            run=run,
            manifest=manifest,
            database_path=tmp_path / run.binding.profile.benchmark.value / "scheduler.sqlite3",
            private_directory=tmp_path / run.binding.profile.benchmark.value,
            authentication_secret=secret,
        )
        for run, manifest, secret in zip(
            runs,
            manifests,
            RUN_STORE_SECRETS,
            strict=True,
        )
    )


class SyntheticCaseReader:
    authority_root_sha256 = CASE_ROOT

    def read_exact(self, *, key):
        if key.benchmark.value == "locomo":
            metadata = {
                "_evaluator_ground_truth": "Postgres",
                "category": 3,
                "reference_date": "January 04, 2024",
            }
            question = "Which database did Alex choose?"
        else:
            metadata = {
                "_evaluator_ground_truth": "Postgres",
                "question_date": "2024/01/04 (Thu) 09:30",
                "question_type": "knowledge-update",
            }
            question = "Which database does Alex use now?"
        case = PublicBenchmarkCase(
            benchmark=key.benchmark.value,
            case_id=key.case_id,
            question=question,
            expected_terms=(),
            metadata=metadata,
        )
        return SchedulerAuthenticatedOfficialCase(
            key=key,
            material_sha256=official_case_material_sha256(key, case),
            case=case,
        )


class SyntheticRetrievalReader:
    authority_root_sha256 = RETRIEVAL_ROOT

    def read_exact(self, *, key):
        memories = (
            RetrievedMemory(
                text=f"Alex chose Postgres via {key.backend_role}.",
                rank=1,
                score=1.0,
                metadata={"backend": key.backend_role},
            ),
        )
        return SchedulerAuthenticatedRetrievalEvidence(
            key=key,
            material_sha256=retrieval_evidence_material_sha256(key, memories),
            memories=memories,
        )


class EmbeddedAadCipher:
    """Test-only authenticated cipher that carries its public AAD for reopening."""

    def seal(self, plaintext: bytes, *, associated_data: bytes) -> bytes:
        nonce = hashlib.sha256(_CIPHER_KEY + associated_data + plaintext).digest()[:16]
        encrypted = _xor(plaintext, _stream(nonce, len(plaintext)))
        body = len(associated_data).to_bytes(4, "big") + associated_data + nonce + encrypted
        tag = hmac.new(_CIPHER_KEY, body, hashlib.sha256).digest()
        return body + tag

    def open(self, ciphertext: bytes, *, associated_data: bytes) -> bytes:
        embedded, nonce, encrypted, tag, body = self._parts(ciphertext)
        if embedded != associated_data:
            raise ValueError("test_cipher_associated_data_mismatch")
        expected = hmac.new(_CIPHER_KEY, body, hashlib.sha256).digest()
        if not hmac.compare_digest(expected, tag):
            raise ValueError("test_cipher_authentication_failed")
        return _xor(encrypted, _stream(nonce, len(encrypted)))

    def open_embedded(self, ciphertext: bytes) -> bytes:
        associated_data, _, _, _, _ = self._parts(ciphertext)
        return self.open(ciphertext, associated_data=associated_data)

    @staticmethod
    def _parts(ciphertext: bytes):
        if type(ciphertext) is not bytes or len(ciphertext) < 52:
            raise ValueError("test_ciphertext_invalid")
        size = int.from_bytes(ciphertext[:4], "big")
        split = 4 + size
        if size < 1 or split + 48 > len(ciphertext):
            raise ValueError("test_ciphertext_invalid")
        associated_data = ciphertext[4:split]
        nonce = ciphertext[split : split + 16]
        encrypted = ciphertext[split + 16 : -32]
        return associated_data, nonce, encrypted, ciphertext[-32:], ciphertext[:-32]


class EmbeddedAadDecryptor:
    policy_sha256 = DECRYPT_POLICY

    def __init__(self, cipher: EmbeddedAadCipher) -> None:
        self._cipher = cipher
        self.observed_ciphertext_sha256: list[str] = []

    def decrypt_exact(self, ciphertext: bytes, *, context):
        if hashlib.sha256(ciphertext).hexdigest() != context.ciphertext_sha256:
            raise ValueError("test_decrypt_ciphertext_crosswire")
        plaintext = self._cipher.open_embedded(ciphertext)
        self.observed_ciphertext_sha256.append(context.ciphertext_sha256)
        return SchedulerDecryptedPrivateAnswer(
            context=context,
            answer=plaintext.decode("utf-8", errors="strict"),
        )

    def __repr__(self) -> str:
        return "EmbeddedAadDecryptor(private_material=<redacted>)"


class AuthenticatedExtractionReader:
    read_policy_sha256 = sha("scheduler-extraction-read-policy")

    def __init__(self, suite, specs) -> None:
        self._items = tuple(
            authenticate_extraction_terminal(
                run_authority_sha256=spec.run.commitment_sha256,
                read_policy_sha256=self.read_policy_sha256,
                evidence=_extraction_evidence(suite, spec.run, index),
                authentication_secret=spec.authentication_secret,
            )
            for index, spec in enumerate(specs)
        )

    def read_terminal(self, *, run):
        return next(
            (item for item in self._items if item.run_authority_sha256 == run.commitment_sha256),
            None,
        )


def _extraction_evidence(suite, run, index: int) -> SchedulerExtractionTerminalEvidence:
    expected = (
        LOCOMO_EXTRACTION_OPERATION_COUNT if index == 0 else LONGMEMEVAL_EXTRACTION_OPERATION_COUNT
    )
    context = ManagedFullRunExtractionContext(
        profile_id=run.binding.profile.profile_id,
        run_id_sha256=hashlib.sha256(run.binding.run_id.encode()).hexdigest(),
        binding_commitment_sha256=run.binding.binding_commitment_sha256,
        methodology_commitment_sha256=suite.methodology_sha256,
        admission_commitment_sha256=sha(f"admission:{index}"),
        ingestion_root_sha256=sha(f"ingestion:{index}"),
        a1_terminal_commitment_sha256=sha(f"a1-terminal:{index}"),
        a1_manifest_context_sha256=sha(f"a1-context:{index}"),
        runtime_binding_commitment_sha256=suite.bridge_boot.runtime_authority_sha256,
        expected_receipt_count=expected,
    )
    page_count = (expected + FULL_RUN_EXTRACTION_PAGE_SIZE - 1) // FULL_RUN_EXTRACTION_PAGE_SIZE
    pages_root = sha(f"pages:{index}")
    body = {
        "context_commitment_sha256": context.commitment_sha256,
        "page_count": page_count,
        "receipt_count": expected,
        "receipt_pages_root_sha256": pages_root,
        "schema_version": "managed-full-run-extraction-ledger.v1",
        "usage": {"completion_tokens": 0, "prompt_tokens": 0, "total_tokens": 0},
    }
    terminal = ManagedFullRunExtractionTerminal(
        context_commitment_sha256=context.commitment_sha256,
        receipt_count=expected,
        page_count=page_count,
        receipt_pages_root_sha256=pages_root,
        prompt_tokens=0,
        completion_tokens=0,
        total_tokens=0,
        terminal_commitment_sha256=canonical_sha256(body),
    )
    return SchedulerExtractionTerminalEvidence(context=context, terminal=terminal)


def seed_all_scheduler_calls(
    runner,
    *,
    charged_tokens: int,
    entry_indexes: tuple[int, ...] = (0, 1),
) -> None:
    """Provider-free bulk fixture; the production runner has no bulk path."""

    from infinity_context_server.publishable_durable_scheduler.sqlite_rows import (
        call_values,
        run_values,
    )
    from infinity_context_server.publishable_durable_scheduler.state_models import (
        SchedulerCallPhase,
    )

    for index in entry_indexes:
        entry = runner._entries[index]
        repository = entry.store._repository
        with repository.immediate() as connection:
            before_run, event_head = repository.load_run(connection)
            states = repository.load_calls_bounded(connection)
            final_states = []
            for state in states:
                if state.phase is SchedulerCallPhase.COMMITTED:
                    final_states.append(state)
                    continue
                ciphertext = (
                    f"synthetic-ciphertext:{state.logical_call_id}".encode()
                    if state.stage.value == "answer"
                    else None
                )
                terminal = replace(
                    state,
                    phase=SchedulerCallPhase.COMMITTED,
                    attempt_count=1,
                    lease_id="provider-free-suite-seed",
                    lease_expires_unix_ms=3_000,
                    request_sha256=sha(f"request:{state.logical_call_id}"),
                    intent_sha256=sha(f"intent:{state.logical_call_id}"),
                    terminal_evidence_sha256=sha(f"receipt:{state.logical_call_id}"),
                    charged_tokens=charged_tokens,
                    version=4,
                )
                expected = repository._calls[state.logical_call_id]
                repository._update_call(
                    connection,
                    call_values(
                        terminal,
                        shard_index=expected.shard_index,
                        answer_ciphertext=ciphertext,
                    ),
                    answer_ciphertext=ciphertext,
                    before_version=state.version,
                )
                final_states.append(terminal)
            updated_run = replace(
                before_run,
                reserved_tokens=0,
                consumed_tokens=sum(item.charged_tokens for item in final_states),
                burned_tokens=0,
                inflight_logical_call_id=None,
            )
            repository._update_run(
                connection,
                run_values(updated_run, event_head_sha256=event_head),
                before_version=before_run.version,
            )


def _stream(nonce: bytes, length: int) -> bytes:
    output = bytearray()
    counter = 0
    while len(output) < length:
        output.extend(hashlib.sha256(_CIPHER_KEY + nonce + counter.to_bytes(8, "big")).digest())
        counter += 1
    return bytes(output[:length])


def _xor(left: bytes, right: bytes) -> bytes:
    return bytes(a ^ b for a, b in zip(left, right, strict=True))

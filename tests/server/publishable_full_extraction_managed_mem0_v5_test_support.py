from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any

from infinity_context_core.ports.managed_cleanup_v3_contracts import PROFILE_ORACLES
from infinity_context_core.ports.managed_full_run_extraction_ledger import (
    ManagedFullRunExtractionContext,
)
from infinity_context_server import (
    memory_comparison_managed_mem0_v5_extraction_projection as extraction,
)
from infinity_context_server import (
    memory_comparison_managed_mem0_v5_projector as projector,
)
from infinity_context_server import (
    memory_comparison_managed_mem0_v5_runtime_attestation as attestation,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_dispatch_guard import (
    ManagedMem0V5SingleDispatchGuardPort,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_http_evidence import (
    HmacSha256ManagedMem0V5EvidenceVerifier,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_http_lane import (
    ManagedMem0V5HttpLane,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    MEM0_V5_SEALED_INPUT_SCHEMA_VERSION,
    ManagedMem0V5ManifestAuthority,
    ManagedMem0V5SourceMessage,
    ManagedMem0V5SourceUnit,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_request_binding import (
    ManagedMem0V5RequestBindingV2Context,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_runtime_attestation import (
    ManagedMem0V5ExpectedRuntimeAuthority,
    VerifiedManagedMem0V5RuntimeAttestationValidation,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_storage_witness import (
    create_managed_mem0_v5_storage_witness_authority,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    Mem0OssAdmissionRequest,
    Mem0OssFullRunAdmission,
    canonical_sha256,
    manifest_root_sha256,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_observed_receipt import (
    Mem0V5ObservedExtractionOperationAuthority,
    Mem0V5ObservedExtractionReceiptAuthority,
)
from infinity_context_server.memory_comparison_target_identity import (
    mem0_runtime_target_identity_sha256,
)
from infinity_context_server.processes.publishable_full_extraction_contracts import (
    MANAGED_MEM0_EXTRACTION_NAMESPACE,
    MANAGED_MEM0_EXTRACTION_OPERATION_KIND,
    PublishableExtractionCommand,
    PublishableExtractionRunAuthority,
)
from infinity_context_server.resumable_operation_journal.domain import (
    LogicalOperationIdentity,
    OperationManifest,
    OperationRunIdentity,
    sha256_commitment,
)

EVIDENCE_KEY = b"publishable-http-evidence-key-32b"
assert len(EVIDENCE_KEY) == 33


def sha(value: object) -> str:
    return hashlib.sha256(repr(value).encode()).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode()


@dataclass(frozen=True, slots=True)
class SyntheticRun:
    manifest: ManagedMem0V5ManifestAuthority
    admission: Mem0OssFullRunAdmission
    receipt_authority: Mem0V5ObservedExtractionReceiptAuthority
    authority: PublishableExtractionRunAuthority
    expected_runtime: ManagedMem0V5ExpectedRuntimeAuthority
    runtime_attestation: VerifiedManagedMem0V5RuntimeAttestationValidation
    target_identity_sha256: str

    def command(self, ordinal: int) -> PublishableExtractionCommand:
        operation = self.authority.operation_manifest.operations[ordinal]
        observed = self.receipt_authority.operations[ordinal]
        unit = self.manifest.units[ordinal]
        return PublishableExtractionCommand(
            run_id=self.authority.journal_identity.run_id,
            run_identity_commitment_sha256=sha256_commitment(
                self.authority.journal_identity.commitment_payload()
            ),
            logical_operation_id=operation.logical_operation_id,
            ordinal=ordinal,
            admission_commitment_sha256=self.admission.commitment_sha256,
            operation_id_sha256=observed.operation_id_sha256,
            unit_identity_sha256=unit.unit_identity_sha256,
            unit_sha256=unit.unit_sha256,
            route_sha256=self.admission.request.route_sha256,
            scope_sha256=unit.scope_sha256,
            request_body_sha256=observed.request_body_sha256,
        )


def build_locomo_run() -> SyntheticRun:
    profile_id = "mem0-locomo-top50-v1"
    oracle = PROFILE_ORACLES[profile_id]
    count = int(oracle["operation_count"])
    manifest = synthetic_manifest(profile_id=profile_id, operation_count=count)
    request = Mem0OssAdmissionRequest(
        run_id="publishable-locomo-http-adapter",
        route_sha256=sha("runtime-route"),
        credential_binding_sha256=sha("credential"),
        model=extraction.MEM0_V5_EXTRACTION_MODEL,
        reasoning_effort="high",
        service_tier="default",
        runtime_source_revision="mem0-oss-v5-pinned",
        runtime_source_sha256=sha("runtime-source"),
        runtime_base_sha256=sha("runtime-base"),
        expected_operation_count=count,
    )
    admission = Mem0OssFullRunAdmission(
        request=request,
        ingestion_manifest_sha256=manifest.ingestion_manifest_sha256,
        ingestion_root_sha256=manifest.ingestion_root_sha256,
        ingestion_unit_count=count,
    )
    request_projector = extraction.PinnedMem0V5ExtractionRequestProjector()
    operations = tuple(
        Mem0V5ObservedExtractionOperationAuthority(
            operation_id_sha256=canonical_sha256(
                {
                    "admission_commitment_sha256": admission.commitment_sha256,
                    "unit_index": ordinal,
                    "unit_identity_sha256": unit.unit_identity_sha256,
                }
            ),
            unit_identity_sha256=unit.unit_identity_sha256,
            unit_sha256=unit.unit_sha256,
            scope_sha256=unit.scope_sha256,
            sequence=ordinal,
            request_body_sha256=request_projector.project(
                unit,
                current_date=manifest.current_date,
            ).request_body_sha256,
        )
        for ordinal, unit in enumerate(manifest.units)
    )
    receipt_authority = Mem0V5ObservedExtractionReceiptAuthority(
        admission_commitment_sha256=admission.commitment_sha256,
        model=request.model,
        reasoning_effort=request.reasoning_effort,
        service_tier=request.service_tier,
        base_instructions_sha256=sha("base-instructions"),
        runtime_source_sha256=request.runtime_source_sha256,
        route_binding_sha256=request.route_sha256,
        account_binding_hmac_sha256=sha("account-binding"),
        node_executable_path="/usr/local/bin/node",
        node_executable_sha256=sha("node-executable"),
        response_format_type="json_schema",
        response_format_sha256=extraction.MEM0_V5_EXTRACTION_RESPONSE_FORMAT_SHA256,
        response_schema_sha256=extraction.MEM0_V5_EXTRACTION_SCHEMA_SHA256,
        operations=operations,
    )
    operation_manifest = OperationManifest(
        tuple(
            LogicalOperationIdentity(
                run_id=request.run_id,
                operation_key=operation.operation_id_sha256,
                operation_kind=MANAGED_MEM0_EXTRACTION_OPERATION_KIND,
                ordinal=ordinal,
                authority_commitment_sha256=manifest.authority_commitment_sha256,
            )
            for ordinal, operation in enumerate(operations)
        )
    )
    identity = OperationRunIdentity(
        run_id=request.run_id,
        operation_namespace=MANAGED_MEM0_EXTRACTION_NAMESPACE,
        manifest_commitment_sha256=operation_manifest.commitment_sha256,
        policy_commitment_sha256=sha("policy"),
        signer_key_id="publishable-test-signer",
        expected_operation_count=count,
    )
    runtime_binding = sha("subscription-runtime-binding")
    context = ManagedFullRunExtractionContext(
        profile_id=profile_id,
        run_id_sha256=hashlib.sha256(request.run_id.encode()).hexdigest(),
        binding_commitment_sha256=sha("run-binding"),
        methodology_commitment_sha256=sha("methodology"),
        admission_commitment_sha256=admission.commitment_sha256,
        ingestion_root_sha256=manifest.ingestion_root_sha256,
        a1_terminal_commitment_sha256=sha("a1-terminal"),
        a1_manifest_context_sha256=sha("a1-manifest-context"),
        runtime_binding_commitment_sha256=runtime_binding,
        expected_receipt_count=count,
    )
    authority = PublishableExtractionRunAuthority(
        journal_identity=identity,
        operation_manifest=operation_manifest,
        runtime_receipt_authority=receipt_authority,
        ledger_context=context,
        preparation_receipt_sha256=sha("preparation"),
        dataset_sha256=str(oracle["dataset_sha256"]),
        a2_terminal_commitment_sha256=sha("a2-terminal"),
        scheduler_bridge_runtime_authority_sha256=sha("scheduler-bridge-runtime"),
    )
    expected = expected_runtime_authority(
        receipt_authority=receipt_authority,
        subscription_runtime_binding_sha256=runtime_binding,
    )
    target = mem0_runtime_target_identity_sha256("http://127.0.0.1:19091")
    validation = issue_runtime_attestation(
        expected=expected,
        run_id_sha256=context.run_id_sha256,
        target_identity_sha256=target,
    )
    return SyntheticRun(
        manifest,
        admission,
        receipt_authority,
        authority,
        expected,
        validation,
        target,
    )


def synthetic_manifest(
    *,
    profile_id: str,
    operation_count: int,
) -> ManagedMem0V5ManifestAuthority:
    oracle = PROFILE_ORACLES[profile_id]
    corpus_count = int(oracle["corpus_count"])
    units: list[ManagedMem0V5SourceUnit] = []
    for sequence in range(operation_count):
        corpus_id = f"corpus-{sequence % corpus_count}"
        source_id = f"source-{sequence}"
        messages = (ManagedMem0V5SourceMessage("user", f"message-{sequence}"),)
        unit_sha = canonical_sha256(
            {"source_messages": [message.payload() for message in messages]}
        )
        source_sha = sha(("source", sequence))
        scope = canonical_sha256(
            {
                "corpus_id": corpus_id,
                "source_id": source_id,
                "source_sha256": source_sha,
                "unit_sha256": unit_sha,
            }
        )
        units.append(
            ManagedMem0V5SourceUnit(
                sequence=sequence,
                corpus_id=corpus_id,
                source_id=source_id,
                observation_date="2026-08-10",
                source_messages=messages,
                unit_identity_sha256=canonical_sha256(
                    {
                        "sequence": sequence,
                        "scope_sha256": scope,
                        "unit_sha256": unit_sha,
                    }
                ),
                unit_sha256=unit_sha,
                source_sha256=source_sha,
                scope_sha256=scope,
            )
        )
    typed_units = tuple(units)
    root = manifest_root_sha256(tuple(unit.manifest_unit() for unit in typed_units))
    current_date = "2026-08-10"
    ingestion_manifest = canonical_sha256(
        {"current_date": current_date, "ingestion_root_sha256": root}
    )
    unsigned = {
        "schema_version": MEM0_V5_SEALED_INPUT_SCHEMA_VERSION,
        "ingestion_manifest_sha256": ingestion_manifest,
        "ingestion_root_sha256": root,
        "current_date": current_date,
        "units": [unit.private_payload() for unit in typed_units],
    }
    sealed = canonical_sha256(unsigned)
    authority_commitment = projector._authority_commitment(
        case_count=int(oracle["case_count"]),
        corpus_count=corpus_count,
        operation_count=operation_count,
        ingestion_manifest_sha256=ingestion_manifest,
        ingestion_root_sha256=root,
        sealed_payload_sha256=sealed,
    )
    return ManagedMem0V5ManifestAuthority(
        current_date=current_date,
        case_count=int(oracle["case_count"]),
        corpus_count=corpus_count,
        units=typed_units,
        ingestion_manifest_sha256=ingestion_manifest,
        ingestion_root_sha256=root,
        sealed_payload_sha256=sealed,
        authority_commitment_sha256=authority_commitment,
    )


def expected_runtime_authority(
    *,
    receipt_authority: Mem0V5ObservedExtractionReceiptAuthority,
    subscription_runtime_binding_sha256: str,
) -> ManagedMem0V5ExpectedRuntimeAuthority:
    return ManagedMem0V5ExpectedRuntimeAuthority(
        source_commit_sha1="1" * 40,
        source_tree_sha1="2" * 40,
        source_manifest_sha256=sha("source-manifest"),
        source_closure_sha256=sha("source-closure"),
        phase_c_infinity_commit_sha1="3" * 40,
        phase_c_infinity_tree_sha1="4" * 40,
        phase_c_release_manifest_sha256=sha("phase-c-release"),
        runtime_binding_commitment_sha256=sha("adapter-runtime-binding"),
        subscription_runtime_binding_commitment_sha256=(subscription_runtime_binding_sha256),
        runtime_source_sha256=receipt_authority.runtime_source_sha256,
        runtime_route_binding_sha256=receipt_authority.route_binding_sha256,
        runtime_transport_origin_sha256=sha("transport-origin"),
        expected_account_binding_hmac_sha256=(receipt_authority.account_binding_hmac_sha256),
        expected_base_instructions_sha256=receipt_authority.base_instructions_sha256,
        extraction_system_prompt_sha256=extraction.MEM0_V5_EXTRACTION_SYSTEM_PROMPT_SHA256,
        extraction_response_format_sha256=(extraction.MEM0_V5_EXTRACTION_RESPONSE_FORMAT_SHA256),
        extraction_response_schema_sha256=extraction.MEM0_V5_EXTRACTION_SCHEMA_SHA256,
        requested_output_tokens=extraction.MEM0_V5_EXTRACTION_MAX_TOKENS,
        output_limit_enforced=False,
        usage_attestation_required=False,
    )


def issue_runtime_attestation(
    *,
    expected: ManagedMem0V5ExpectedRuntimeAuthority,
    run_id_sha256: str,
    target_identity_sha256: str,
) -> VerifiedManagedMem0V5RuntimeAttestationValidation:
    root = b"runtime-attestation-test-root-key"
    now = int(time.time())
    request = {
        "schema_version": attestation.REQUEST_SCHEMA,
        "target_origin_sha256": target_identity_sha256,
        "run_id_sha256": run_id_sha256,
        "probe_nonce_sha256": sha("probe-nonce"),
        "validity_seconds": 900,
    }
    static = expected.public_payload()
    implementation = attestation._canonical_sha256(
        {
            "schema_version": "mem0-oss-adapter-v5.implementation-binding.v1",
            "route_contract_sha256": attestation._ROUTE_SHA256,
            **static,
        }
    )
    unsigned = {
        "schema_version": attestation.RESPONSE_SCHEMA,
        "service": "mem0-oss-adapter-v5",
        "route_contract_sha256": attestation._ROUTE_SHA256,
        "target_origin_sha256": target_identity_sha256,
        "run_id_sha256": run_id_sha256,
        "probe_nonce_sha256": request["probe_nonce_sha256"],
        **static,
        "implementation_binding_sha256": implementation,
        "issued_at_unix": now,
        "expires_at_unix": now + 900,
        "provider_calls": 0,
    }
    signing_key = hmac.new(
        root,
        attestation._RESPONSE_KEY_DOMAIN,
        hashlib.sha256,
    ).digest()
    response = {
        **unsigned,
        "attestation_hmac_sha256": hmac.new(
            signing_key,
            attestation._RESPONSE_DOMAIN + attestation._canonical_json(unsigned),
            hashlib.sha256,
        ).hexdigest(),
    }
    return attestation._verify_and_issue(
        response,
        request=request,
        root_secret=root,
        expected_authority=expected,
        now_unix=now,
    )


class _Bearer:
    def validate(self) -> None:
        return None

    def consume(self) -> str:
        return "publishable-test-bearer-token-value"


class _EvidenceKey:
    def validate(self) -> None:
        return None

    def consume(self) -> bytes:
        return EVIDENCE_KEY


class _CleanupBinding:
    def cleanup_context(self, **_kwargs: object) -> object:
        raise AssertionError("cleanup is outside the extraction adapter")


class _Response:
    status_code = 200

    def __init__(self, payload: dict[str, object]) -> None:
        self._content = canonical(payload)

    def read_bounded(self, maximum_bytes: int) -> bytes:
        if len(self._content) > maximum_bytes:
            raise ValueError("oversized")
        return self._content


class RecordingHttpTransport:
    def __init__(self, run: SyntheticRun, runtime_receipt: dict[str, object] | None = None) -> None:
        self.run = run
        self.runtime_receipt = runtime_receipt or {}
        self.calls: list[dict[str, object]] = []
        self.tamper_binding_hmac = False
        self.tamper_admission_runtime = False

    def request(self, method: str, url: str, **kwargs: Any) -> _Response:
        body = json.loads(kwargs["content"])
        call = {"method": method, "url": url, "body": body, **kwargs}
        self.calls.append(call)
        headers = kwargs["headers"]
        assert headers["Authorization"] == "Bearer publishable-test-bearer-token-value"
        assert headers["X-Request-Commitment-SHA256"] == canonical_sha256(body)
        if url.endswith("/v5/runs/admit"):
            return _Response(
                {
                    "admission_commitment_sha256": self.run.admission.commitment_sha256,
                    "runtime_binding_commitment_sha256": (
                        sha("tampered-admission-runtime")
                        if self.tamper_admission_runtime
                        else (
                            self.run.expected_runtime.subscription_runtime_binding_commitment_sha256
                        )
                    ),
                    "accepted": True,
                }
            )
        if url.endswith("/v5/operations/request-binding"):
            operation_id = str(body["operation_id_sha256"])
            ordinal = next(
                item.sequence
                for item in self.run.receipt_authority.operations
                if item.operation_id_sha256 == operation_id
            )
            unit = self.run.manifest.units[ordinal]
            context = ManagedMem0V5RequestBindingV2Context.from_authority(
                authority=self.run.manifest,
                unit=unit,
                operation_id_sha256=operation_id,
                admission=self.run.admission,
            )
            evidence = {
                **context.evidence_payload(),
                "request_body_sha256": (
                    self.run.receipt_authority.operations[ordinal].request_body_sha256
                ),
            }
            unsigned = {
                **evidence,
                "request_binding_evidence_sha256": canonical_sha256(evidence),
            }
            key = evidence_key(b"request-binding/v2")
            signature = hmac.new(key, canonical(unsigned), hashlib.sha256).hexdigest()
            if self.tamper_binding_hmac:
                signature = "0" * 64
            return _Response(
                {
                    **unsigned,
                    "request_binding_hmac_sha256": signature,
                }
            )
        if url.endswith(("/v5/operations/dispatch", "/v5/operations/status")):
            return _Response(
                {
                    "admission_commitment_sha256": self.run.admission.commitment_sha256,
                    "operation_id_sha256": body["operation_id_sha256"],
                    "runtime_receipt": self.runtime_receipt,
                }
            )
        raise AssertionError(f"unexpected path: {url}")


def evidence_key(domain: bytes) -> bytes:
    root = hmac.new(
        EVIDENCE_KEY,
        b"mem0-oss-adapter-v5/evidence-key/v1",
        hashlib.sha256,
    ).digest()
    return hmac.new(root, domain, hashlib.sha256).digest()


def build_lane(
    run: SyntheticRun,
    transport: RecordingHttpTransport,
    *,
    dispatch_guard: ManagedMem0V5SingleDispatchGuardPort | None = None,
) -> ManagedMem0V5HttpLane:
    issuer, _ = create_managed_mem0_v5_storage_witness_authority()
    verifier = HmacSha256ManagedMem0V5EvidenceVerifier(
        key_capability=_EvidenceKey(),
        storage_witness_issuer=issuer,
    )
    return ManagedMem0V5HttpLane(
        origin="http://127.0.0.1:19091",
        bearer_capability=_Bearer(),
        timeout_seconds=1,
        evidence_verifier=verifier,
        dispatch_binding=verifier,
        cleanup_binding=_CleanupBinding(),
        dispatch_guard=dispatch_guard,
        transport=transport,
    )


def idempotency_key(kind: str, binding: str) -> str:
    return canonical_sha256({"kind": kind, "binding": binding})


def scaled_receipt_authority(count: int) -> Mem0V5ObservedExtractionReceiptAuthority:
    admission = sha(("scaled-admission", count))
    operations = tuple(
        Mem0V5ObservedExtractionOperationAuthority(
            operation_id_sha256=canonical_sha256(
                {
                    "admission_commitment_sha256": admission,
                    "unit_index": sequence,
                    "unit_identity_sha256": sha(("identity", sequence)),
                }
            ),
            unit_identity_sha256=sha(("identity", sequence)),
            unit_sha256=sha(("unit", sequence)),
            scope_sha256=sha(("scope", sequence)),
            sequence=sequence,
            request_body_sha256=sha(("request", sequence)),
        )
        for sequence in range(count)
    )
    return Mem0V5ObservedExtractionReceiptAuthority(
        admission_commitment_sha256=admission,
        model=extraction.MEM0_V5_EXTRACTION_MODEL,
        reasoning_effort="high",
        service_tier="default",
        base_instructions_sha256=sha("scaled-base"),
        runtime_source_sha256=sha("scaled-source"),
        route_binding_sha256=sha("scaled-route"),
        account_binding_hmac_sha256=sha("scaled-account"),
        node_executable_path="/usr/local/bin/node",
        node_executable_sha256=sha("scaled-node"),
        response_format_type="json_schema",
        response_format_sha256=extraction.MEM0_V5_EXTRACTION_RESPONSE_FORMAT_SHA256,
        response_schema_sha256=extraction.MEM0_V5_EXTRACTION_SCHEMA_SHA256,
        operations=operations,
    )


__all__ = (
    "RecordingHttpTransport",
    "SyntheticRun",
    "build_lane",
    "build_locomo_run",
    "idempotency_key",
    "scaled_receipt_authority",
    "sha",
)

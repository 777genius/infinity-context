"""Run the logical provider-free E2E after the reviewed compose stack is healthy."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from .canonical import read_private_text
from .contracts import SYNTHETIC_OUTPUT, PinnedRequestProjector, RunFixture
from .fake_runtime import AuthenticatedCallCounter
from .http_client import AdapterHttpClient, LoopbackHttpTransport
from .lifecycle import DockerAdapterLifecycle, require_pinned_docker_host
from .readiness import wait_for_stack
from .receipt import NodeReceiptCanonicalizer, ReceiptAuthority, ReceiptVerifier
from .scenario import ProviderFreeE2EScenario
from .state_audit import IndependentStateAuditor
from .storage_audit import IndependentStorageAuditor, QdrantHttp


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--runtime-authority-mirror", type=Path, required=True)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--compose-file", type=Path, required=True)
    parser.add_argument("--project-name", required=True)
    parser.add_argument("--lifecycle-fd", type=int, required=True)
    parser.add_argument("--adapter-port", type=int, default=19091)
    parser.add_argument("--qdrant-port", type=int, default=6334)
    args = parser.parse_args()

    require_pinned_docker_host()
    wait_for_stack(adapter_port=args.adapter_port, qdrant_port=args.qdrant_port)

    fixture = RunFixture.create(PinnedRequestProjector())
    secrets_dir = args.run_root / "secrets"
    ingress = read_private_text(secrets_dir / "ingress-bearer")
    state_hmac = read_private_text(secrets_dir / "state-hmac").encode()
    receipt_secret = read_private_text(secrets_dir / "runtime-receipt-secret").encode()
    runtime_repo = args.runtime_authority_mirror / "repo"
    canonicalizer = NodeReceiptCanonicalizer(
        runtime_repo=runtime_repo,
        node_executable=args.node,
    )
    qdrant = QdrantHttp(port=args.qdrant_port)
    state_root = args.run_root / "state"
    scenario = ProviderFreeE2EScenario(
        fixture=fixture,
        adapter=AdapterHttpClient(
            bearer_token=ingress,
            transport=LoopbackHttpTransport(port=args.adapter_port),
        ),
        receipt_verifier=ReceiptVerifier(
            authority=ReceiptAuthority(
                account_binding_hmac_sha256=fixture.account_binding_hmac_sha256,
                base_instructions_sha256=fixture.base_instructions_sha256,
                request_body_sha256=fixture.request_body_sha256,
                response_format_sha256=fixture.response_format_sha256,
                response_schema_sha256=fixture.response_schema_sha256,
                output_text_sha256=hashlib.sha256(SYNTHETIC_OUTPUT.encode()).hexdigest(),
            ),
            receipt_secret=receipt_secret,
            canonicalizer=canonicalizer,
        ),
        state_auditor=IndependentStateAuditor(
            path=state_root / "operations.sqlite3", hmac_key=state_hmac
        ),
        storage_auditor=IndependentStorageAuditor(
            qdrant=qdrant, history_db=state_root / "mem0" / "history.db"
        ),
        qdrant=qdrant,
        counter=AuthenticatedCallCounter(
            args.run_root / "fake-runtime" / "counter.json", key=receipt_secret
        ),
        lifecycle=DockerAdapterLifecycle(
            lifecycle_fd=args.lifecycle_fd,
            host_port=args.adapter_port,
        ),
        operation_state_path=state_root / "operations.sqlite3",
        durable_artifact_roots=(state_root, args.run_root / "fake-runtime"),
        forbidden_artifact_bytes=(
            ingress.encode(),
            state_hmac,
            receipt_secret,
            read_private_text(secrets_dir / "runtime-bearer").encode(),
        ),
    )
    result = scenario.run()
    print(json.dumps(asdict(result), sort_keys=True))


if __name__ == "__main__":
    main()

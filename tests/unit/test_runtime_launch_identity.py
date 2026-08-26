from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import asdict, replace

import pytest
from infinity_context_adapters.postgres import RuntimeProcessSupervisor
from infinity_context_core.features.context_building.public import (
    InstalledReleaseIdentity,
    RuntimeFenceOwner,
)
from infinity_context_server.config import DeployProfile, Settings


def test_supervisor_issues_immutable_process_bound_owner_without_owner_arguments() -> None:
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        supervisor = RuntimeProcessSupervisor(
            key_id="unit-supervisor",
            process=process,
            trust_root_sha256="a" * 64,
            trust_registry_generation=7,
            installed_release=_release(),
        )
        owner = supervisor.owner()
        assert owner.process_pid == process.pid
        assert RuntimeFenceOwner.from_launch_identity_json(json.dumps(asdict(owner))) == owner
        with pytest.raises(TypeError):
            supervisor.owner(instance_id="forged", generation="forged")  # type: ignore[call-arg]
        with pytest.raises(RuntimeError, match="runtime_process_mismatch"):
            owner.assert_current_process()
        for hostile in (
            replace(owner, process_pid=owner.process_pid + 1),
            replace(owner, process_birth_identity="swapped"),
            replace(owner, executable_identity="/swapped/executable"),
        ):
            with pytest.raises(RuntimeError, match="runtime_process_mismatch"):
                hostile.assert_current_process()
    finally:
        process.terminate()
        process.wait(timeout=5)


def _release() -> InstalledReleaseIdentity:
    return InstalledReleaseIdentity(
        "1" * 40,
        "sha256:" + "2" * 64,
        "sha256:" + "3" * 64,
        "sha256:" + "4" * 64,
    )


def test_server_qdrant_runtime_requires_external_supervisor_launch_identity() -> None:
    settings = Settings(
        deploy_profile=DeployProfile.SERVER,
        service_token="unit-token",
        qdrant_enabled=True,
        embeddings_enabled=True,
        embeddings_provider="openai",
        openai_api_key="unit-key",
    )
    with pytest.raises(RuntimeError, match="RETRIEVAL_RUNTIME_LAUNCH_IDENTITY_JSON"):
        settings.validate_for_startup()

    malformed = settings.model_copy(
        update={
            "retrieval_runtime_launch_identity_json": '{"not":"a launch identity"}',
            "retrieval_supervisor_trust_registry_path": "/deployment/trust.json",
            "retrieval_supervisor_trust_root_sha256": "a" * 64,
            "retrieval_supervisor_key_id": "deployment-key",
            "retrieval_supervisor_trust_registry_generation": 1,
        }
    )
    with pytest.raises(RuntimeError, match="runtime_launch_invalid"):
        malformed.validate_for_startup()


def test_canary_qdrant_runtime_has_the_same_recoverable_provider_policy() -> None:
    settings = Settings(
        deploy_profile=DeployProfile.CANARY,
        qdrant_enabled=True,
        embeddings_enabled=True,
        embeddings_provider="openai",
        openai_api_key="unit-key",
    )
    with pytest.raises(RuntimeError, match="RETRIEVAL_RUNTIME_LAUNCH_IDENTITY_JSON"):
        settings.validate_for_startup()

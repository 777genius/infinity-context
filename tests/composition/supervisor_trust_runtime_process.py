"""Test runtime: consume only a launcher envelope plus pinned public deployment config."""

from __future__ import annotations

import json
import os
from pathlib import Path

from infinity_context_server.build_identity import repository_source_release_identity
from infinity_context_server.config import Settings
from infinity_context_server.retrieval_profile_composition import (
    _runtime_owner_from_settings,
)

if __name__ == "__main__":
    os.setgroups([])
    os.setgid(int(os.environ["TEST_RUNTIME_GID"]))
    os.setuid(int(os.environ["TEST_RUNTIME_UID"]))
    envelope = input()
    settings = Settings(
        deploy_profile="server",
        service_token="composition-token",
        qdrant_enabled=True,
        embeddings_enabled=True,
        embeddings_provider="openai",
        openai_api_key="composition-not-a-provider-credential",
        retrieval_runtime_launch_identity_json=envelope,
        retrieval_supervisor_trust_registry_path=os.environ["TEST_SUPERVISOR_REGISTRY_PATH"],
        retrieval_supervisor_trust_root_sha256=os.environ["TEST_SUPERVISOR_ROOT_SHA256"],
        retrieval_supervisor_key_id=os.environ["TEST_SUPERVISOR_KEY_ID"],
        retrieval_supervisor_trust_registry_generation=int(
            os.environ["TEST_SUPERVISOR_REGISTRY_GENERATION"]
        ),
    )
    release = repository_source_release_identity(
        Path(__file__).resolve().parents[2],
        service_revision=os.environ["TEST_RELEASE_REVISION"],
    )
    owner = _runtime_owner_from_settings(settings, expected_release=release)
    print(
        json.dumps(
            {
                "consumed": True,
                "pid": owner.process_pid,
                "supervisor_key_id": owner.supervisor_key_id,
                "trust_registry_generation": owner.trust_registry_generation,
                "trust_root_sha256": owner.trust_root_sha256,
                "installed_release_identity_sha256": owner.installed_release.digest(),
                "lifecycle_identity_sha256": owner.lifecycle_identity_sha256(),
            },
            sort_keys=True,
        ),
        flush=True,
    )

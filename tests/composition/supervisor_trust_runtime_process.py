"""Test runtime: consume only a launcher envelope plus pinned public deployment config."""

from __future__ import annotations

import json
import os
import stat
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
    runtime_root = Path(os.environ["TEST_RUNTIME_SOURCE_ROOT"]).resolve(strict=True)
    registry_path = Path(os.environ["TEST_SUPERVISOR_REGISTRY_PATH"])
    envelope = input()
    settings = Settings(
        deploy_profile="server",
        service_token="composition-token",
        qdrant_enabled=True,
        embeddings_enabled=True,
        embeddings_provider="openai",
        openai_api_key="composition-not-a-provider-credential",
        retrieval_runtime_launch_identity_json=envelope,
        retrieval_supervisor_trust_registry_path=str(registry_path),
        retrieval_supervisor_trust_root_sha256=os.environ["TEST_SUPERVISOR_ROOT_SHA256"],
        retrieval_supervisor_key_id=os.environ["TEST_SUPERVISOR_KEY_ID"],
        retrieval_supervisor_trust_registry_generation=int(
            os.environ["TEST_SUPERVISOR_REGISTRY_GENERATION"]
        ),
    )
    release = repository_source_release_identity(
        runtime_root,
        service_revision=os.environ["TEST_RELEASE_REVISION"],
    )
    owner = _runtime_owner_from_settings(settings, expected_release=release)
    registry_metadata = registry_path.stat()
    source_metadata = runtime_root.stat()
    print(
        json.dumps(
            {
                "consumed": True,
                "pid": owner.process_pid,
                "runtime_gid": os.getegid(),
                "runtime_source_mode": stat.S_IMODE(source_metadata.st_mode),
                "runtime_source_owner_uid": source_metadata.st_uid,
                "runtime_source_root": str(runtime_root),
                "runtime_uid": os.geteuid(),
                "registry_mode": stat.S_IMODE(registry_metadata.st_mode),
                "registry_owner_uid": registry_metadata.st_uid,
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

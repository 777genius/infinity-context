"""Supervised child that is itself the concrete PostgreSQL fence writer."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import datetime

from infinity_context_adapters.postgres import build_async_engine, build_session_factory
from infinity_context_adapters.postgres.locator_profile_lifecycle import (
    PostgresRetrievalProfileRegistry,
)
from infinity_context_adapters.postgres.supervisor_trust import SupervisorTrustRegistry
from infinity_context_core.features.context_building.public import (
    InstalledReleaseIdentity,
    RuntimeFenceOwner,
)


async def _write(config: dict[str, object]) -> dict[str, object]:
    engine = build_async_engine(str(config["postgres_url"]))
    try:
        trust = config["supervisor_trust"]
        registry = PostgresRetrievalProfileRegistry(
            build_session_factory(engine),
            SupervisorTrustRegistry(
                registry_id=str(trust["registry_id"]),
                generation=int(trust["generation"]),
                valid_from=datetime.fromisoformat(str(trust["valid_from"])),
                valid_until=datetime.fromisoformat(str(trust["valid_until"])),
                keys=tuple(tuple(item) for item in trust["keys"]),
                installed_release=InstalledReleaseIdentity(**trust["installed_release"]),
                root_sha256=str(trust["root_sha256"]),
            ),
        )
        owner = RuntimeFenceOwner.from_launch_identity_json(
            json.dumps(config["launch_identity"], separators=(",", ":"))
        )
        deadline = datetime.fromisoformat(str(config["stale_deadline"]))
        if config["kind"] == "reader":
            admission = await registry.begin_profile_query(
                str(config["operation_id"]), owner=owner, now=datetime.now(deadline.tzinfo),
                expires_at=deadline,
            )
            result = {"status": str(admission.status), "mutation_epoch": None}
        else:
            epochs = {}
            for operation_id in config.get("operation_ids", [config["operation_id"]]):
                epochs[str(operation_id)] = await registry.begin_provider_mutation(
                    str(config["profile_id"]), str(operation_id), owner=owner,
                    now=datetime.now(deadline.tzinfo), expires_at=deadline,
                )
            result = {
                "status": "admitted",
                "mutation_epoch": epochs[str(config["operation_id"])],
                "mutation_epochs": epochs,
            }
        return {**result, "pid": owner.process_pid}
    finally:
        await engine.dispose()


if __name__ == "__main__":
    configuration = json.loads(sys.stdin.readline())
    print(json.dumps(asyncio.run(_write(configuration)), sort_keys=True), flush=True)
    time.sleep(120)

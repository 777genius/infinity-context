"""Bounded production operator entry point for Retrieval V2 profile lifecycle."""

from __future__ import annotations

import asyncio
from dataclasses import asdict

from infinity_context_adapters.postgres import RuntimeDeathProof
from infinity_context_core.features.context_building.public import InstalledReleaseIdentity

from infinity_context_server.composition import build_container
from infinity_context_server.config import Settings


async def retrieval_profile_lifecycle_command(
    *, operation: str, target: str, limit: int, deadline_seconds: float
) -> dict[str, object]:
    invalid = _validate(operation, target, limit, deadline_seconds)
    if invalid is not None:
        return invalid
    container = None
    try:
        container = build_container(Settings())
        lifecycle = container.retrieval_profile_lifecycle
        async with asyncio.timeout(deadline_seconds):
            now = container.clock.now()
            if operation == "rollback":
                retired = await lifecycle.rollback(target, now=now)
                return _transition_result(operation, target, retired)
            if operation == "retire":
                retired = await lifecycle.retire(target, now=now)
                return _transition_result(operation, target, retired)
            if operation == "delete":
                cleanup = await lifecycle.delete(target, now=now)
                steps = 1
                while cleanup.phase != "complete" and steps < limit:
                    cleanup = await lifecycle.retirement.cleanup_step(target, now=now)
                    steps += 1
                return {
                    "status": "ok" if cleanup.phase == "complete" else "pending",
                    "operation": operation,
                    "target": target,
                    "phase": cleanup.phase,
                    "attempt_count": cleanup.attempt_count,
                    "error_code": cleanup.last_error_code,
                    "steps": steps,
                }
            if target == "active":
                reconcile_active = getattr(container.locator_retrieval, "reconcile_active", None)
                if reconcile_active is None:
                    raise RuntimeError("retrieval_profile_reconciliation_unavailable")
                result = await reconcile_active(now=now)
                response = {
                    "status": "ok" if result.complete else "pending",
                    "operation": operation,
                    "target": target,
                    "phase": "complete" if result.complete else "in_progress",
                    "renewed": result.renewed,
                }
                if result.renewed:
                    response["provenance"] = {
                        "runtime_instance_id": result.runtime_instance_id,
                        "runtime_generation": result.runtime_generation,
                        "release_identity_sha256": result.release_identity_sha256,
                        "lifecycle_identity_sha256": result.lifecycle_identity_sha256,
                    }
                return response
            result = await lifecycle.reconcile(now=now, limit=limit)
            return {
                "status": "ok" if result.failed == 0 else "degraded",
                "operation": operation,
                "target": target,
                **asdict(result),
            }
    except TimeoutError:
        return _failed(operation, target, "profile_operation_deadline_exceeded")
    except RuntimeError as exc:
        code = str(exc)
        return _failed(
            operation,
            target,
            code if code.startswith("retrieval_profile_") else "profile_operation_failed",
        )
    except Exception:
        return _failed(operation, target, "profile_operation_failed")
    finally:
        if container is not None:
            await container.engine.dispose()


async def retrieval_profile_recovery_command(**request) -> dict[str, object]:
    """Run the exact auditable recovery CAS; never infer abandonment from TTL."""

    container = None
    try:
        container = build_container(Settings())
        return await container.retrieval_profile_lifecycle.registry.recover_abandoned_fence(
            **request
        )
    except (RuntimeError, ValueError) as exc:
        code = str(exc)
        return {
            "status": "refused",
            "error_code": (
                code if code.startswith("retrieval_profile_") else "profile_recovery_invalid"
            ),
        }
    finally:
        if container is not None:
            await container.engine.dispose()


async def retrieval_profile_maintenance_command(**request) -> dict[str, object]:
    """Drive the durable drain/dead-seal/provider-observation maintenance protocol."""

    container = None
    try:
        container = build_container(Settings())
        lifecycle = container.retrieval_profile_lifecycle
        registry = lifecycle.registry
        action = request.pop("action")
        if action == "begin":
            generation = await registry.begin_maintenance(reason=request["reason"])
            return {"status": "ok", "maintenance_generation": generation, "active": True}
        generation = request["maintenance_generation"]
        if action == "complete":
            await registry.complete_maintenance(generation)
            return {"status": "ok", "maintenance_generation": generation, "active": False}
        owner = {
            "owner_instance_id": request["owner_instance_id"],
            "owner_generation": request["owner_generation"],
            "maintenance_generation": generation,
        }
        if action == "acknowledge":
            await registry.acknowledge_maintenance(**owner)
            return {"status": "ok", "maintenance_generation": generation, "acknowledged": True}
        if action == "seal_dead":
            proof = await registry.seal_dead_incarnation(
                proof=RuntimeDeathProof(
                    proof_id=request["proof_id"],
                    instance_id=request["owner_instance_id"],
                    generation=request["owner_generation"],
                    supervisor_key_id=request["supervisor_key_id"],
                    trust_root_sha256=request["trust_root_sha256"],
                    trust_registry_generation=request["trust_registry_generation"],
                    launch_token=request["launch_token"],
                    process_pid=request["process_pid"],
                    process_birth_identity=request["process_birth_identity"],
                    executable_identity=request["executable_identity"],
                    executable_sha256=request["executable_sha256"],
                    installed_release=InstalledReleaseIdentity(
                        service_revision=request["release_revision"],
                        source_tree_digest_sha256=request["release_source_tree_sha256"],
                        installed_distribution_digest_sha256=(
                            request["release_installed_distribution_sha256"]
                        ),
                        runtime_modules_digest_sha256=(
                            request["release_runtime_modules_sha256"]
                        ),
                    ),
                    maintenance_generation=generation,
                    exit_observation_id=request["exit_observation_id"],
                    exited_at=request["exited_at"],
                    exit_code=request["exit_code"],
                    signature=request["signature"],
                )
            )
            return {"status": "ok", "maintenance_generation": generation, "proof_sha256": proof}
        identity = next(
            (
                item
                for item in await registry.routable()
                if item.profile_id == request["profile_id"]
            ),
            None,
        )
        if identity is None:
            raise RuntimeError("retrieval_profile_missing")
        epoch = await registry.maintenance_evidence_epoch(generation)
        digest = await lifecycle.projection.reconcile_provider_mutation(
            identity,
            receipt_id=request["receipt_id"],
            maintenance_generation=generation,
            evidence_epoch=epoch,
            operation_id=request["operation_id"],
            owner_instance_id=request["owner_instance_id"],
            owner_generation=request["owner_generation"],
            mutation_epoch=request["mutation_epoch"],
            stale_deadline=request["stale_deadline"],
            observed_at=container.clock.now(),
        )
        return {"status": "ok", "receipt_id": request["receipt_id"], "receipt_sha256": digest}
    except (KeyError, RuntimeError, ValueError) as exc:
        code = str(exc)
        return {
            "status": "refused",
            "error_code": (
                code if code.startswith("retrieval_profile_") else "profile_maintenance_invalid"
            ),
        }
    finally:
        if container is not None:
            await container.engine.dispose()


def _validate(operation, target, limit, deadline_seconds) -> dict[str, object] | None:
    if operation not in {"rollback", "retire", "delete", "reconcile"}:
        return {"status": "refused", "error_code": "profile_operation_invalid"}
    if not target or target != target.strip() or len(target) > 120:
        return {"status": "refused", "error_code": "profile_target_invalid"}
    if not 1 <= limit <= 100 or not 0.1 <= deadline_seconds <= 300:
        return {"status": "refused", "error_code": "profile_bound_invalid"}
    if operation == "reconcile" and target not in {"active", "pending"}:
        return {"status": "refused", "error_code": "profile_reconcile_target_invalid"}
    if operation != "reconcile" and target in {"active", "pending"}:
        return {"status": "refused", "error_code": "profile_id_required"}
    return None


def _transition_result(operation, target, retired) -> dict[str, object]:
    return {
        "status": "ok",
        "operation": operation,
        "target": target,
        "retired_profile_ids": list(retired),
    }


def _failed(operation: str, target: str, code: str) -> dict[str, object]:
    return {
        "status": "failed",
        "operation": operation,
        "target": target,
        "error_code": code,
    }

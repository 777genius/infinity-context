"""Authentication and bounded argument policy for the Qdrant rebuild command."""

from __future__ import annotations

import argparse
import asyncio
import os
import secrets

from infinity_context_server.admin_projection_repair import reindex_qdrant
from infinity_context_server.config import Settings


def authorize_qdrant_rebuild(token_env: str) -> dict[str, object] | None:
    if (
        not token_env
        or len(token_env) > 80
        or any(character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_" for character in token_env)
    ):
        return {
            "status": "refused",
            "operation": "reindex-qdrant",
            "reason": "auth token environment variable name is invalid",
        }
    configured = Settings().service_token
    supplied = os.environ.get(token_env)
    if not configured or not supplied or not secrets.compare_digest(configured, supplied):
        return {
            "status": "refused",
            "operation": "reindex-qdrant",
            "reason": "admin authorization preflight failed",
        }
    return None


def configure_qdrant_rebuild_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--operation-id", default=None)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="perform the read-only canonical/auth preflight without enqueueing",
    )
    parser.add_argument(
        "--auth-token-env",
        default="INFINITY_CONTEXT_ADMIN_TOKEN",
        help="environment variable holding the configured service authorization token",
    )
    parser.add_argument(
        "--deadline-seconds",
        type=float,
        default=30.0,
        choices=(5.0, 10.0, 30.0, 60.0, 120.0),
    )


async def run_qdrant_rebuild(args: argparse.Namespace) -> dict[str, object]:
    auth_failure = authorize_qdrant_rebuild(args.auth_token_env)
    if auth_failure is not None:
        return auth_failure
    try:
        return await asyncio.wait_for(
            reindex_qdrant(
                space=args.space,
                memory_scope=args.memory_scope,
                dry_run=args.dry_run or args.preflight_only,
                confirmed=args.i_understand_this_enqueues_projection_jobs,
                operation_id=args.operation_id,
                batch_size=args.batch_size,
            ),
            timeout=args.deadline_seconds,
        )
    except TimeoutError:
        return {
            "status": "failed",
            "operation": "reindex-qdrant",
            "reason": "admin preflight deadline exceeded",
        }

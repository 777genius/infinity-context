"""Generic local Memo Stack smoke test.

Run after `docker compose up` or `make memo-stack-up`.
The script uses only the public SDK and HTTP API.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from time import time
from typing import Any

from memo_stack_sdk import MemoStackClient, MemoStackError


class SmokeFailure(RuntimeError):
    """Raised when the smoke path completes HTTP calls but violates memory expectations."""


@dataclass(frozen=True)
class SmokeConfig:
    api_url: str
    auth_token: str
    space_slug: str
    profile_external_ref: str
    thread_external_ref: str
    run_id: str
    timeout: float

    @classmethod
    def from_env(cls) -> SmokeConfig:
        run_id = os.getenv("MEMORY_SMOKE_RUN_ID") or str(int(time()))
        return cls(
            api_url=os.getenv("MEMORY_SMOKE_API_URL", "http://127.0.0.1:7788"),
            auth_token=os.getenv(
                "MEMORY_SMOKE_AUTH_TOKEN",
                os.getenv("MEMORY_SERVICE_TOKEN", "local-dev-token"),
            ),
            space_slug=os.getenv("MEMORY_SMOKE_SPACE", "memo-stack-smoke"),
            profile_external_ref=os.getenv("MEMORY_SMOKE_PROFILE", "default"),
            thread_external_ref=os.getenv(
                "MEMORY_SMOKE_THREAD",
                f"smoke-{run_id}",
            ),
            run_id=run_id,
            timeout=float(os.getenv("MEMORY_SMOKE_TIMEOUT", "15")),
        )


def run_smoke(client: Any, config: SmokeConfig) -> dict[str, Any]:
    fact_marker = f"SMOKE_MEMORY_FACT_{config.run_id}"
    updated_marker = f"SMOKE_MEMORY_FACT_UPDATED_{config.run_id}"
    document_marker = f"SMOKE_MEMORY_DOCUMENT_{config.run_id}"

    health = client.health()
    if health.get("status") != "ok":
        raise SmokeFailure("Memory server health check failed")

    space = _data(
        client.create_space(
            slug=config.space_slug,
            name=f"{config.space_slug} smoke",
        )
    )
    profile = _data(
        client.create_profile(
            space_id=str(space["id"]),
            external_ref=config.profile_external_ref,
            name=f"{config.profile_external_ref} smoke",
        )
    )

    fact = _data(
        client.remember_fact(
            space_slug=config.space_slug,
            profile_external_ref=config.profile_external_ref,
            thread_external_ref=config.thread_external_ref,
            text=f"{fact_marker}: initial smoke fact for Memo Stack.",
            kind="note",
            classification="internal",
            source_refs=[
                {
                    "source_type": "manual",
                    "source_id": f"smoke-fact-{config.run_id}",
                }
            ],
            idempotency_key=f"smoke-fact-{config.run_id}",
        )
    )
    updated = _data(
        client.update_fact(
            str(fact["id"]),
            expected_version=int(fact.get("version", 1)),
            text=f"{updated_marker}: updated smoke fact for Memo Stack.",
            reason="integration smoke update",
            source_refs=[
                {
                    "source_type": "manual",
                    "source_id": f"smoke-fact-updated-{config.run_id}",
                }
            ],
        )
    )
    document = _data(
        client.ingest_document(
            space_slug=config.space_slug,
            profile_external_ref=config.profile_external_ref,
            thread_external_ref=config.thread_external_ref,
            title=f"Memo Stack smoke document {config.run_id}",
            text=f"{document_marker}: document recall smoke for Memo Stack.",
            source_external_id=f"smoke-doc-{config.run_id}",
            classification="internal",
            idempotency_key=f"smoke-doc-{config.run_id}",
        )
    )

    search = _data(
        client.search(
            space_slug=config.space_slug,
            profile_external_ref=config.profile_external_ref,
            thread_external_ref=config.thread_external_ref,
            query=updated_marker,
            token_budget=512,
            max_facts=5,
            max_chunks=5,
        )
    )
    _assert_items_contain(search, updated_marker, "search")

    context = _data(
        client.build_context(
            space_slug=config.space_slug,
            profile_external_ref=config.profile_external_ref,
            thread_external_ref=config.thread_external_ref,
            query=f"{updated_marker} {document_marker}",
            token_budget=768,
            max_facts=5,
            max_chunks=5,
        )
    )
    rendered_text = str(context.get("rendered_text", ""))
    if updated_marker not in rendered_text:
        raise SmokeFailure("Updated fact was not rendered in context")
    if document_marker not in rendered_text:
        raise SmokeFailure("Document chunk was not rendered in context")

    client.forget_fact(str(fact["id"]))
    after_forget = _data(
        client.build_context(
            space_slug=config.space_slug,
            profile_external_ref=config.profile_external_ref,
            thread_external_ref=config.thread_external_ref,
            query=updated_marker,
            token_budget=512,
            max_facts=10,
            max_chunks=0,
        )
    )
    if updated_marker in str(after_forget.get("rendered_text", "")):
        raise SmokeFailure("Forgotten fact leaked back into context")

    return {
        "ok": True,
        "api_url": config.api_url,
        "space_id": space["id"],
        "profile_id": profile["id"],
        "thread_external_ref": config.thread_external_ref,
        "fact_id": fact["id"],
        "updated_fact_version": updated.get("version"),
        "document_id": document["id"],
        "search_items": len(search.get("items", [])),
        "context_items": len(context.get("items", [])),
        "after_forget_items": len(after_forget.get("items", [])),
    }


def main() -> int:
    config = SmokeConfig.from_env()
    client = MemoStackClient(
        base_url=config.api_url,
        token=config.auth_token,
        timeout=config.timeout,
    )
    try:
        result = run_smoke(client, config)
    except MemoStackError as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": exc.code,
                    "status_code": exc.status_code,
                    "retryable": exc.retryable,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    except SmokeFailure as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


def _data(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    if not isinstance(data, dict):
        raise SmokeFailure("Expected response envelope with object data")
    return data


def _assert_items_contain(payload: dict[str, Any], marker: str, operation: str) -> None:
    items = payload.get("items")
    if not isinstance(items, list):
        raise SmokeFailure(f"{operation} response did not include item list")
    if not any(marker in str(item.get("text", "")) for item in items if isinstance(item, dict)):
        raise SmokeFailure(f"{operation} did not return expected marker")


if __name__ == "__main__":
    raise SystemExit(main())

"""Shared helpers for eval suites."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

from infinity_context_server.eval_constants import _FORBIDDEN_SNAPSHOT_MARKERS


def _seed_eval_scope(
    client: TestClient,
    headers: dict[str, str],
    *,
    space_slug: str = "eval",
    space_name: str = "Eval Suite",
    alpha_external_ref: str = "eval-alpha",
    alpha_name: str = "Eval Alpha",
    beta_external_ref: str = "eval-beta",
    beta_name: str = "Eval Beta",
) -> tuple[dict[str, bool], str, str, str]:
    checks: dict[str, bool] = {}
    fallback_space_id = "space_eval"
    fallback_alpha_memory_scope_id = "memory_scope_alpha"
    fallback_beta_memory_scope_id = "memory_scope_beta"

    space_response = client.post(
        "/v1/spaces",
        json={"slug": space_slug, "name": space_name},
        headers=headers,
    )
    checks["space_scope"] = _status_ok(space_response.status_code)
    space_id = _response_data_id(space_response) or fallback_space_id

    alpha_response = client.post(
        "/v1/memory-scopes",
        json={"space_id": space_id, "external_ref": alpha_external_ref, "name": alpha_name},
        headers=headers,
    )
    checks["alpha_memory_scope_scope"] = _status_ok(alpha_response.status_code)
    alpha_memory_scope_id = _response_data_id(alpha_response) or fallback_alpha_memory_scope_id

    beta_response = client.post(
        "/v1/memory-scopes",
        json={"space_id": space_id, "external_ref": beta_external_ref, "name": beta_name},
        headers=headers,
    )
    checks["beta_memory_scope_scope"] = _status_ok(beta_response.status_code)
    beta_memory_scope_id = _response_data_id(beta_response) or fallback_beta_memory_scope_id

    return checks, space_id, alpha_memory_scope_id, beta_memory_scope_id


def _response_data_id(response) -> str | None:
    try:
        value = response.json()["data"]["id"]
    except (KeyError, TypeError, ValueError):
        return None
    return str(value) if value else None


def _json_data_list(response) -> list[dict[str, object]]:
    try:
        data = response.json()["data"]
    except (KeyError, TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def _json_path_str(response, *path: str) -> str:
    try:
        value = response.json()
        for key in path:
            value = value[key]
    except (KeyError, TypeError, ValueError):
        return ""
    return str(value) if value is not None else ""


def _json_path_int(response, *path: str) -> int:
    try:
        value = response.json()
        for key in path:
            value = value[key]
    except (KeyError, TypeError, ValueError):
        return 0
    return value if isinstance(value, int) else 0


def _first_suggestion_id(response) -> str | None:
    suggestion_ids = _json_path_value(response, "data", "suggestion_ids")
    if not isinstance(suggestion_ids, list) or not suggestion_ids:
        return None
    value = suggestion_ids[0]
    return str(value) if value else None


def _json_path_value(response, *path: str):
    try:
        value = response.json()
        for key in path:
            value = value[key]
    except (KeyError, TypeError, ValueError):
        return None
    return value


def _response_data_thread_id(response) -> str | None:
    try:
        value = response.json()["data"]["thread_id"]
    except (KeyError, TypeError, ValueError):
        return None
    return str(value) if value else None


def _remember_eval_fact(
    client: TestClient,
    headers: dict[str, str],
    *,
    space_id: str | None = None,
    memory_scope_id: str | None = None,
    text: str,
    source_id: str,
    idempotency_key: str | None = None,
    classification: str = "internal",
    thread_id: str | None = None,
    space_slug: str | None = None,
    memory_scope_external_ref: str | None = None,
    thread_external_ref: str | None = None,
) -> bool:
    response = _remember_eval_fact_response(
        client,
        headers,
        space_id=space_id,
        memory_scope_id=memory_scope_id,
        thread_id=thread_id,
        space_slug=space_slug,
        memory_scope_external_ref=memory_scope_external_ref,
        thread_external_ref=thread_external_ref,
        text=text,
        source_id=source_id,
        idempotency_key=idempotency_key,
        classification=classification,
    )
    return _status_ok(response.status_code)


def _remember_eval_fact_response(
    client: TestClient,
    headers: dict[str, str],
    *,
    text: str,
    source_id: str,
    idempotency_key: str | None = None,
    classification: str = "internal",
    space_id: str | None = None,
    memory_scope_id: str | None = None,
    thread_id: str | None = None,
    space_slug: str | None = None,
    memory_scope_external_ref: str | None = None,
    thread_external_ref: str | None = None,
):
    payload = {
        "text": text,
        "kind": "note",
        "source_refs": [{"source_type": "manual", "source_id": source_id}],
        "classification": classification,
    }
    for key, value in (
        ("space_id", space_id),
        ("memory_scope_id", memory_scope_id),
        ("thread_id", thread_id),
        ("space_slug", space_slug),
        ("memory_scope_external_ref", memory_scope_external_ref),
        ("thread_external_ref", thread_external_ref),
    ):
        if value is not None:
            payload[key] = value
    return client.post(
        "/v1/facts",
        json=payload,
        headers=_with_idempotency(headers, idempotency_key),
    )


def _seed_eval_updated_fact(
    client: TestClient,
    headers: dict[str, str],
    *,
    space_id: str,
    memory_scope_id: str,
    old_text: str,
    new_text: str,
    old_source_id: str,
    new_source_id: str,
    idempotency_key: str,
    reason: str,
    classification: str = "internal",
) -> bool:
    created = client.post(
        "/v1/facts",
        json={
            "space_id": space_id,
            "memory_scope_id": memory_scope_id,
            "text": old_text,
            "kind": "note",
            "source_refs": [{"source_type": "manual", "source_id": old_source_id}],
            "classification": classification,
        },
        headers=_with_idempotency(headers, idempotency_key),
    )
    if not _status_ok(created.status_code):
        return False
    data = created.json()["data"]
    if data.get("text") == new_text:
        return True
    updated = client.patch(
        f"/v1/facts/{data['id']}",
        json={
            "expected_version": data["version"],
            "text": new_text,
            "reason": reason,
            "source_refs": [{"source_type": "manual", "source_id": new_source_id}],
        },
        headers=headers,
    )
    return updated.status_code == 200


def _seed_eval_deleted_fact(
    client: TestClient,
    headers: dict[str, str],
    *,
    space_id: str,
    memory_scope_id: str,
    text: str,
    source_id: str,
    idempotency_key: str,
    classification: str = "internal",
) -> bool:
    created = client.post(
        "/v1/facts",
        json={
            "space_id": space_id,
            "memory_scope_id": memory_scope_id,
            "text": text,
            "kind": "note",
            "source_refs": [{"source_type": "manual", "source_id": source_id}],
            "classification": classification,
        },
        headers=_with_idempotency(headers, idempotency_key),
    )
    if not _status_ok(created.status_code):
        return False
    data = created.json()["data"]
    if data.get("status") == "deleted":
        return True
    deleted = client.delete(f"/v1/facts/{data['id']}", headers=headers)
    return deleted.status_code == 200


def _ratio(passed: int, total: int) -> float:
    if total <= 0:
        return 1.0
    return round(passed / total, 4)


def _status_ok(status_code: int) -> bool:
    return status_code in {200, 201}


def _with_idempotency(headers: dict[str, str], key: str | None) -> dict[str, str]:
    if key is None:
        return headers
    return {**headers, "Idempotency-Key": key}


def _git_report(root: Path | None = None) -> dict[str, object]:
    root = (root or Path.cwd()).resolve()
    commit = _git_output(root, "rev-parse", "HEAD")
    short_commit = _git_output(root, "rev-parse", "--short", "HEAD")
    dirty = _git_output(root, "status", "--short")
    return {
        "commit": commit,
        "short_commit": short_commit,
        "dirty": bool(dirty) if dirty is not None else True,
    }


def _git_output(root: Path, *args: str) -> str | None:
    git_bin = shutil.which("git") or "/usr/bin/git"
    try:
        result = subprocess.run(
            [git_bin, *args],
            cwd=root,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _write_redacted_report(result: dict[str, object], report_out: Path | None) -> None:
    if report_out is None:
        return
    serialized = _stable_json(result)
    safety_errors = _snapshot_safety_errors(serialized)
    if safety_errors:
        raise ValueError(f"Eval report contains forbidden markers: {', '.join(safety_errors)}")
    report_out.parent.mkdir(parents=True, exist_ok=True)
    report_out.write_text(serialized, encoding="utf-8")

def _stable_json(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _snapshot_safety_errors(serialized_payload: str) -> list[str]:
    return [
        f"forbidden_marker:{marker}"
        for marker in _FORBIDDEN_SNAPSHOT_MARKERS
        if marker.lower() in serialized_payload.lower()
    ]

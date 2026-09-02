"""ID remapping helpers for memory_scope snapshot imports."""

from __future__ import annotations

from typing import Any

from infinity_context_server.memory_scope_transfer_records import bounded_optional_text


def remap_fact(
    item: dict[str, Any],
    *,
    fact_id_map: dict[str, str],
    thread_id_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    fact_id = str(item["id"])
    return {
        **item,
        "id": fact_id_map.get(fact_id, fact_id),
        "thread_id": _remap_optional_thread_id(item.get("thread_id"), thread_id_map or {}),
    }


def remap_document(
    item: dict[str, Any],
    *,
    document_id_map: dict[str, str],
    extraction_job_id_map: dict[str, str] | None = None,
    thread_id_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    document_id = str(item["id"])
    extraction_job_id_map = extraction_job_id_map or {}
    return {
        **item,
        "id": document_id_map.get(document_id, document_id),
        "thread_id": _remap_optional_thread_id(item.get("thread_id"), thread_id_map or {}),
        "source_external_id": _remap_source_external_id(
            source_type=str(item.get("source_type") or ""),
            source_external_id=str(item.get("source_external_id") or ""),
            extraction_job_id_map=extraction_job_id_map,
        ),
    }


def remap_episode(
    item: dict[str, Any],
    *,
    episode_id_map: dict[str, str],
    thread_id_map: dict[str, str],
) -> dict[str, Any]:
    episode_id = str(item["id"])
    source_thread_id = episode_source_thread_id(item)
    return {
        **item,
        "id": episode_id_map.get(episode_id, episode_id),
        "thread_id": thread_id_map.get(source_thread_id, source_thread_id),
    }


def remap_chunk(
    item: dict[str, Any],
    *,
    document_id_map: dict[str, str],
    episode_id_map: dict[str, str],
    chunk_id_map: dict[str, str],
    thread_id_map: dict[str, str],
    asset_id_map: dict[str, str] | None = None,
    extraction_job_id_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    chunk_id = str(item["id"])
    document_id = item.get("document_id")
    episode_id = item.get("episode_id")
    thread_id = item.get("thread_id")
    asset_id_map = asset_id_map or {}
    extraction_job_id_map = extraction_job_id_map or {}
    mapped_thread_id = _remap_optional_thread_id(thread_id, thread_id_map)
    return {
        **item,
        "id": chunk_id_map.get(chunk_id, chunk_id),
        "thread_id": mapped_thread_id,
        "document_id": (
            document_id_map.get(str(document_id), str(document_id))
            if document_id is not None
            else None
        ),
        "episode_id": (
            episode_id_map.get(str(episode_id), str(episode_id)) if episode_id is not None else None
        ),
        "source_external_id": _remap_source_external_id(
            source_type=str(item.get("source_type") or ""),
            source_external_id=str(item.get("source_external_id") or ""),
            extraction_job_id_map=extraction_job_id_map,
        ),
        "metadata_json": _remap_chunk_metadata(
            item.get("metadata_json") or item.get("metadata") or {},
            asset_id_map=asset_id_map,
            extraction_job_id_map=extraction_job_id_map,
        ),
    }


def remap_source_ref(
    item: dict[str, Any],
    *,
    fact_id_map: dict[str, str],
    chunk_id_map: dict[str, str],
    document_id_map: dict[str, str] | None = None,
    extraction_job_id_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    chunk_id = item.get("chunk_id")
    mapped_chunk_id = (
        chunk_id_map.get(str(chunk_id), str(chunk_id)) if chunk_id is not None else None
    )
    source_type = str(item.get("source_type") or "")
    source_id = str(item.get("source_id") or "")
    extraction_job_id_map = extraction_job_id_map or {}
    document_id_map = document_id_map or {}
    return {
        **item,
        "fact_id": fact_id_map.get(str(item["fact_id"]), str(item["fact_id"])),
        "source_id": (
            extraction_job_id_map.get(source_id, source_id)
            if source_type == "asset_extraction"
            else document_id_map.get(source_id, source_id)
            if source_type == "document"
            else source_id
        ),
        "chunk_id": mapped_chunk_id,
    }


def remap_capture(
    item: dict[str, Any],
    *,
    fact_id_map: dict[str, str],
    document_id_map: dict[str, str],
    episode_id_map: dict[str, str],
    chunk_id_map: dict[str, str],
    capture_id_map: dict[str, str],
    asset_id_map: dict[str, str] | None = None,
    anchor_id_map: dict[str, str] | None = None,
    extraction_job_id_map: dict[str, str] | None = None,
    extraction_artifact_id_map: dict[str, str] | None = None,
    thread_id_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    capture_id = str(item["id"])
    mapped_capture_id = capture_id_map.get(capture_id, capture_id)
    parent_capture_id = item.get("parent_capture_id")
    return {
        **item,
        "id": mapped_capture_id,
        "thread_id": _remap_optional_thread_id(item.get("thread_id"), thread_id_map or {}),
        "idempotency_key": _remap_capture_idempotency_key(
            item,
            mapped_capture_id=mapped_capture_id,
        ),
        "parent_capture_id": (
            capture_id_map.get(str(parent_capture_id), str(parent_capture_id))
            if parent_capture_id is not None
            else None
        ),
        "evidence_refs": _remap_capture_evidence_refs(
            item.get("evidence_refs"),
            fact_id_map=fact_id_map,
            thread_id_map=thread_id_map or {},
            document_id_map=document_id_map,
            episode_id_map=episode_id_map,
            chunk_id_map=chunk_id_map,
            capture_id_map=capture_id_map,
            asset_id_map=asset_id_map or {},
            anchor_id_map=anchor_id_map or {},
            extraction_job_id_map=extraction_job_id_map or {},
            extraction_artifact_id_map=extraction_artifact_id_map or {},
        ),
    }


def remap_anchor(
    item: dict[str, Any],
    *,
    anchor_id_map: dict[str, str],
) -> dict[str, Any]:
    anchor_id = str(item["id"])
    if anchor_id not in anchor_id_map:
        return item
    return {**item, "id": anchor_id_map[anchor_id]}


def remap_context_link(
    item: dict[str, Any],
    *,
    context_link_id_map: dict[str, str],
    context_link_suggestion_id_map: dict[str, str] | None = None,
    fact_id_map: dict[str, str],
    document_id_map: dict[str, str],
    episode_id_map: dict[str, str],
    chunk_id_map: dict[str, str],
    capture_id_map: dict[str, str],
    asset_id_map: dict[str, str],
    anchor_id_map: dict[str, str],
    thread_id_map: dict[str, str] | None = None,
    extraction_job_id_map: dict[str, str] | None = None,
    extraction_artifact_id_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    link_id = str(item["id"])
    source_type = str(item.get("source_type") or "")
    target_type = str(item.get("target_type") or "")
    suggestion_id_map = context_link_suggestion_id_map or {}
    extraction_job_id_map = extraction_job_id_map or {}
    extraction_artifact_id_map = extraction_artifact_id_map or {}
    return {
        **item,
        "id": context_link_id_map.get(link_id, link_id),
        "source_id": remap_endpoint_id(
            source_type=source_type,
            source_id=str(item.get("source_id")),
            fact_id_map=fact_id_map,
            thread_id_map=thread_id_map or {},
            document_id_map=document_id_map,
            episode_id_map=episode_id_map,
            chunk_id_map=chunk_id_map,
            capture_id_map=capture_id_map,
            asset_id_map=asset_id_map,
            anchor_id_map=anchor_id_map,
            extraction_job_id_map=extraction_job_id_map,
            extraction_artifact_id_map=extraction_artifact_id_map,
        ),
        "target_id": remap_endpoint_id(
            source_type=target_type,
            source_id=str(item.get("target_id")),
            fact_id_map=fact_id_map,
            thread_id_map=thread_id_map or {},
            document_id_map=document_id_map,
            episode_id_map=episode_id_map,
            chunk_id_map=chunk_id_map,
            capture_id_map=capture_id_map,
            asset_id_map=asset_id_map,
            anchor_id_map=anchor_id_map,
            extraction_job_id_map=extraction_job_id_map,
            extraction_artifact_id_map=extraction_artifact_id_map,
        ),
        "metadata_json": _remap_context_link_metadata(
            item.get("metadata_json") or item.get("metadata") or {},
            context_link_suggestion_id_map=suggestion_id_map,
            fact_id_map=fact_id_map,
            thread_id_map=thread_id_map or {},
            document_id_map=document_id_map,
            episode_id_map=episode_id_map,
            chunk_id_map=chunk_id_map,
            capture_id_map=capture_id_map,
            asset_id_map=asset_id_map,
            anchor_id_map=anchor_id_map,
            extraction_job_id_map=extraction_job_id_map,
            extraction_artifact_id_map=extraction_artifact_id_map,
        ),
    }


def episode_source_thread_id(item: dict[str, Any]) -> str:
    return str(item.get("thread_id") or item["id"])


def _remap_capture_idempotency_key(
    item: dict[str, Any],
    *,
    mapped_capture_id: str,
) -> str:
    capture_id = str(item["id"])
    if mapped_capture_id == capture_id:
        return str(item.get("idempotency_key") or capture_id)
    return bounded_optional_text(f"imported-{mapped_capture_id}", 120) or mapped_capture_id


def _remap_optional_thread_id(value: object, thread_id_map: dict[str, str]) -> str | None:
    if value is None:
        return None
    return thread_id_map.get(str(value))


def _remap_capture_evidence_refs(
    value: object,
    *,
    fact_id_map: dict[str, str],
    thread_id_map: dict[str, str],
    document_id_map: dict[str, str],
    episode_id_map: dict[str, str],
    chunk_id_map: dict[str, str],
    capture_id_map: dict[str, str],
    asset_id_map: dict[str, str],
    anchor_id_map: dict[str, str],
    extraction_job_id_map: dict[str, str],
    extraction_artifact_id_map: dict[str, str],
) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    refs: list[dict[str, object]] = []
    for ref in value:
        if not isinstance(ref, dict):
            continue
        next_ref = dict(ref)
        source_type = str(next_ref.get("source_type") or "")
        source_id = next_ref.get("source_id")
        if source_id is not None:
            next_ref["source_id"] = _remap_evidence_source_id(
                source_type=source_type,
                source_id=str(source_id),
                fact_id_map=fact_id_map,
                thread_id_map=thread_id_map,
                document_id_map=document_id_map,
                episode_id_map=episode_id_map,
                chunk_id_map=chunk_id_map,
                capture_id_map=capture_id_map,
                asset_id_map=asset_id_map,
                anchor_id_map=anchor_id_map,
                extraction_job_id_map=extraction_job_id_map,
                extraction_artifact_id_map=extraction_artifact_id_map,
            )
        asset_id = next_ref.get("asset_id")
        if asset_id is not None:
            next_ref["asset_id"] = asset_id_map.get(str(asset_id), str(asset_id))
        chunk_id = next_ref.get("chunk_id")
        if chunk_id is not None:
            next_ref["chunk_id"] = chunk_id_map.get(str(chunk_id), str(chunk_id))
        refs.append(next_ref)
    return refs


def _remap_evidence_source_id(
    *,
    source_type: str,
    source_id: str,
    fact_id_map: dict[str, str],
    thread_id_map: dict[str, str],
    document_id_map: dict[str, str],
    episode_id_map: dict[str, str],
    chunk_id_map: dict[str, str],
    capture_id_map: dict[str, str],
    asset_id_map: dict[str, str],
    anchor_id_map: dict[str, str],
    extraction_job_id_map: dict[str, str],
    extraction_artifact_id_map: dict[str, str],
) -> str:
    return remap_endpoint_id(
        source_type=source_type,
        source_id=source_id,
        fact_id_map=fact_id_map,
        thread_id_map=thread_id_map,
        document_id_map=document_id_map,
        episode_id_map=episode_id_map,
        chunk_id_map=chunk_id_map,
        capture_id_map=capture_id_map,
        asset_id_map=asset_id_map,
        anchor_id_map=anchor_id_map,
        extraction_job_id_map=extraction_job_id_map,
        extraction_artifact_id_map=extraction_artifact_id_map,
    )


def remap_endpoint_id(
    *,
    source_type: str,
    source_id: str,
    fact_id_map: dict[str, str],
    thread_id_map: dict[str, str] | None = None,
    document_id_map: dict[str, str],
    episode_id_map: dict[str, str],
    chunk_id_map: dict[str, str],
    capture_id_map: dict[str, str],
    asset_id_map: dict[str, str],
    anchor_id_map: dict[str, str],
    extraction_job_id_map: dict[str, str] | None = None,
    extraction_artifact_id_map: dict[str, str] | None = None,
) -> str:
    if source_type == "fact":
        return fact_id_map.get(source_id, source_id)
    if source_type == "thread":
        return (thread_id_map or {}).get(source_id, source_id)
    if source_type == "document":
        return document_id_map.get(source_id, source_id)
    if source_type == "episode":
        return episode_id_map.get(source_id, source_id)
    if source_type == "chunk":
        return chunk_id_map.get(source_id, source_id)
    if source_type == "capture":
        return capture_id_map.get(source_id, source_id)
    if source_type == "asset":
        return asset_id_map.get(source_id, source_id)
    if source_type == "anchor":
        return anchor_id_map.get(source_id, source_id)
    if source_type == "asset_extraction":
        return (extraction_job_id_map or {}).get(source_id, source_id)
    if source_type == "extraction_artifact":
        return (extraction_artifact_id_map or {}).get(source_id, source_id)
    return source_id


def _remap_context_link_metadata(
    value: object,
    *,
    context_link_suggestion_id_map: dict[str, str],
    fact_id_map: dict[str, str],
    thread_id_map: dict[str, str],
    document_id_map: dict[str, str],
    episode_id_map: dict[str, str],
    chunk_id_map: dict[str, str],
    capture_id_map: dict[str, str],
    asset_id_map: dict[str, str],
    anchor_id_map: dict[str, str],
    extraction_job_id_map: dict[str, str],
    extraction_artifact_id_map: dict[str, str],
) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    metadata: dict[str, object] = dict(value)
    approved_from_suggestion_id = metadata.get("approved_from_suggestion_id")
    if approved_from_suggestion_id is not None:
        metadata["approved_from_suggestion_id"] = context_link_suggestion_id_map.get(
            str(approved_from_suggestion_id),
            str(approved_from_suggestion_id),
        )
    for type_key, id_key in (
        ("original_target_type", "original_target_id"),
        ("approved_target_type", "approved_target_id"),
    ):
        target_type = metadata.get(type_key)
        target_id = metadata.get(id_key)
        if target_type is not None and target_id is not None:
            metadata[id_key] = remap_endpoint_id(
                source_type=str(target_type),
                source_id=str(target_id),
                fact_id_map=fact_id_map,
                thread_id_map=thread_id_map,
                document_id_map=document_id_map,
                episode_id_map=episode_id_map,
                chunk_id_map=chunk_id_map,
                capture_id_map=capture_id_map,
                asset_id_map=asset_id_map,
                anchor_id_map=anchor_id_map,
                extraction_job_id_map=extraction_job_id_map,
                extraction_artifact_id_map=extraction_artifact_id_map,
            )
    if "edit_events" in metadata:
        metadata["edit_events"] = _remap_context_link_edit_events(
            metadata.get("edit_events"),
            fact_id_map=fact_id_map,
            thread_id_map=thread_id_map,
            document_id_map=document_id_map,
            episode_id_map=episode_id_map,
            chunk_id_map=chunk_id_map,
            capture_id_map=capture_id_map,
            asset_id_map=asset_id_map,
            anchor_id_map=anchor_id_map,
            extraction_job_id_map=extraction_job_id_map,
            extraction_artifact_id_map=extraction_artifact_id_map,
        )
    if "review_events" in metadata:
        metadata["review_events"] = remap_context_link_review_events(
            metadata.get("review_events"),
            context_link_suggestion_id_map=context_link_suggestion_id_map,
            fact_id_map=fact_id_map,
            thread_id_map=thread_id_map,
            document_id_map=document_id_map,
            episode_id_map=episode_id_map,
            chunk_id_map=chunk_id_map,
            capture_id_map=capture_id_map,
            asset_id_map=asset_id_map,
            anchor_id_map=anchor_id_map,
            extraction_job_id_map=extraction_job_id_map,
            extraction_artifact_id_map=extraction_artifact_id_map,
        )
    return metadata


def remap_context_link_review_events(
    value: object,
    *,
    context_link_suggestion_id_map: dict[str, str],
    fact_id_map: dict[str, str],
    thread_id_map: dict[str, str],
    document_id_map: dict[str, str],
    episode_id_map: dict[str, str],
    chunk_id_map: dict[str, str],
    capture_id_map: dict[str, str],
    asset_id_map: dict[str, str],
    anchor_id_map: dict[str, str],
    extraction_job_id_map: dict[str, str],
    extraction_artifact_id_map: dict[str, str],
) -> list[object]:
    if not isinstance(value, list):
        return []
    events: list[object] = []
    for event in value:
        if not isinstance(event, dict):
            events.append(event)
            continue
        next_event = dict(event)
        suggestion_id = next_event.get("suggestion_id")
        if suggestion_id is not None:
            next_event["suggestion_id"] = context_link_suggestion_id_map.get(
                str(suggestion_id),
                str(suggestion_id),
            )
        source_type = next_event.get("source_type")
        source_id = next_event.get("source_id")
        if source_type is not None and source_id is not None:
            next_event["source_id"] = remap_endpoint_id(
                source_type=str(source_type),
                source_id=str(source_id),
                fact_id_map=fact_id_map,
                thread_id_map=thread_id_map,
                document_id_map=document_id_map,
                episode_id_map=episode_id_map,
                chunk_id_map=chunk_id_map,
                capture_id_map=capture_id_map,
                asset_id_map=asset_id_map,
                anchor_id_map=anchor_id_map,
                extraction_job_id_map=extraction_job_id_map,
                extraction_artifact_id_map=extraction_artifact_id_map,
            )
        target_type = next_event.get("target_type")
        target_id = next_event.get("target_id")
        if target_type is not None and target_id is not None:
            next_event["target_id"] = remap_endpoint_id(
                source_type=str(target_type),
                source_id=str(target_id),
                fact_id_map=fact_id_map,
                thread_id_map=thread_id_map,
                document_id_map=document_id_map,
                episode_id_map=episode_id_map,
                chunk_id_map=chunk_id_map,
                capture_id_map=capture_id_map,
                asset_id_map=asset_id_map,
                anchor_id_map=anchor_id_map,
                extraction_job_id_map=extraction_job_id_map,
                extraction_artifact_id_map=extraction_artifact_id_map,
            )
        for type_key, id_key in (
            ("original_target_type", "original_target_id"),
            ("approved_target_type", "approved_target_id"),
        ):
            override_type = next_event.get(type_key)
            override_id = next_event.get(id_key)
            if override_type is not None and override_id is not None:
                next_event[id_key] = remap_endpoint_id(
                    source_type=str(override_type),
                    source_id=str(override_id),
                    fact_id_map=fact_id_map,
                    thread_id_map=thread_id_map,
                    document_id_map=document_id_map,
                    episode_id_map=episode_id_map,
                    chunk_id_map=chunk_id_map,
                    capture_id_map=capture_id_map,
                    asset_id_map=asset_id_map,
                    anchor_id_map=anchor_id_map,
                    extraction_job_id_map=extraction_job_id_map,
                    extraction_artifact_id_map=extraction_artifact_id_map,
                )
        events.append(next_event)
    return events


def _remap_context_link_edit_events(
    value: object,
    *,
    fact_id_map: dict[str, str],
    thread_id_map: dict[str, str],
    document_id_map: dict[str, str],
    episode_id_map: dict[str, str],
    chunk_id_map: dict[str, str],
    capture_id_map: dict[str, str],
    asset_id_map: dict[str, str],
    anchor_id_map: dict[str, str],
    extraction_job_id_map: dict[str, str],
    extraction_artifact_id_map: dict[str, str],
) -> list[object]:
    if not isinstance(value, list):
        return []
    events: list[object] = []
    for event in value:
        if not isinstance(event, dict):
            events.append(event)
            continue
        next_event = dict(event)
        for key in ("previous", "next"):
            endpoint = next_event.get(key)
            if isinstance(endpoint, dict):
                next_event[key] = _remap_context_link_endpoint_snapshot(
                    endpoint,
                    fact_id_map=fact_id_map,
                    thread_id_map=thread_id_map,
                    document_id_map=document_id_map,
                    episode_id_map=episode_id_map,
                    chunk_id_map=chunk_id_map,
                    capture_id_map=capture_id_map,
                    asset_id_map=asset_id_map,
                    anchor_id_map=anchor_id_map,
                    extraction_job_id_map=extraction_job_id_map,
                    extraction_artifact_id_map=extraction_artifact_id_map,
                )
        events.append(next_event)
    return events


def _remap_context_link_endpoint_snapshot(
    value: dict[str, object],
    *,
    fact_id_map: dict[str, str],
    thread_id_map: dict[str, str],
    document_id_map: dict[str, str],
    episode_id_map: dict[str, str],
    chunk_id_map: dict[str, str],
    capture_id_map: dict[str, str],
    asset_id_map: dict[str, str],
    anchor_id_map: dict[str, str],
    extraction_job_id_map: dict[str, str],
    extraction_artifact_id_map: dict[str, str],
) -> dict[str, object]:
    endpoint = dict(value)
    source_type = endpoint.get("source_type")
    source_id = endpoint.get("source_id")
    if source_type is not None and source_id is not None:
        endpoint["source_id"] = remap_endpoint_id(
            source_type=str(source_type),
            source_id=str(source_id),
            fact_id_map=fact_id_map,
            thread_id_map=thread_id_map,
            document_id_map=document_id_map,
            episode_id_map=episode_id_map,
            chunk_id_map=chunk_id_map,
            capture_id_map=capture_id_map,
            asset_id_map=asset_id_map,
            anchor_id_map=anchor_id_map,
            extraction_job_id_map=extraction_job_id_map,
            extraction_artifact_id_map=extraction_artifact_id_map,
        )
    target_type = endpoint.get("target_type")
    target_id = endpoint.get("target_id")
    if target_type is not None and target_id is not None:
        endpoint["target_id"] = remap_endpoint_id(
            source_type=str(target_type),
            source_id=str(target_id),
            fact_id_map=fact_id_map,
            thread_id_map=thread_id_map,
            document_id_map=document_id_map,
            episode_id_map=episode_id_map,
            chunk_id_map=chunk_id_map,
            capture_id_map=capture_id_map,
            asset_id_map=asset_id_map,
            anchor_id_map=anchor_id_map,
            extraction_job_id_map=extraction_job_id_map,
            extraction_artifact_id_map=extraction_artifact_id_map,
        )
    return endpoint


def _remap_source_external_id(
    *,
    source_type: str,
    source_external_id: str,
    extraction_job_id_map: dict[str, str],
) -> str:
    if source_type != "asset_extraction" or not source_external_id:
        return source_external_id
    return extraction_job_id_map.get(source_external_id, source_external_id)


def _remap_chunk_metadata(
    value: object,
    *,
    asset_id_map: dict[str, str],
    extraction_job_id_map: dict[str, str],
) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    metadata = dict(value)
    asset_id = metadata.get("asset_id")
    if asset_id is not None:
        metadata["asset_id"] = asset_id_map.get(str(asset_id), str(asset_id))
    extraction_job_id = metadata.get("extraction_job_id")
    if extraction_job_id is not None:
        metadata["extraction_job_id"] = extraction_job_id_map.get(
            str(extraction_job_id),
            str(extraction_job_id),
        )
    refs = metadata.get("source_refs")
    if isinstance(refs, list):
        metadata["source_refs"] = [
            _remap_chunk_source_ref(
                ref,
                asset_id_map=asset_id_map,
                extraction_job_id_map=extraction_job_id_map,
            )
            for ref in refs
            if isinstance(ref, dict)
        ]
    return metadata


def _remap_chunk_source_ref(
    ref: dict[str, object],
    *,
    asset_id_map: dict[str, str],
    extraction_job_id_map: dict[str, str],
) -> dict[str, object]:
    next_ref = dict(ref)
    source_type = str(next_ref.get("source_type") or "")
    source_id = next_ref.get("source_id")
    if source_type == "asset_extraction" and source_id is not None:
        next_ref["source_id"] = extraction_job_id_map.get(str(source_id), str(source_id))
    asset_id = next_ref.get("asset_id")
    if asset_id is not None:
        next_ref["asset_id"] = asset_id_map.get(str(asset_id), str(asset_id))
    return next_ref

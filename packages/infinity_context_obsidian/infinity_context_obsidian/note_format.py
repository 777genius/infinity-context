"""Infinity Context managed Obsidian note format."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import Any

from infinity_context_obsidian.domain import (
    NOTE_SCHEMA_VERSION,
    ManagedFactNote,
    NoteKind,
    SyncMode,
    SyncStateRecord,
    content_hash,
)
from infinity_context_obsidian.frontmatter import (
    FrontmatterError,
    dump_frontmatter,
    split_frontmatter,
)
from infinity_context_obsidian.layout import DEFAULT_ROOT_FOLDER, ObsidianVaultLayout, safe_filename

FACTS_DIR = PurePosixPath(f"{DEFAULT_ROOT_FOLDER}/generated/facts")
TEXT_START = "<!-- infinity-context-managed:fact-text:start -->"
TEXT_END = "<!-- infinity-context-managed:fact-text:end -->"


class NoteFormatError(ValueError):
    pass


def fact_note_path(
    fact_id: str,
    *,
    layout: ObsidianVaultLayout | None = None,
    space_slug: str = "default",
    memory_scope_external_ref: str = "default",
) -> PurePosixPath:
    if layout is None:
        return FACTS_DIR / f"{safe_filename(fact_id)}.md"
    return layout.fact_note_path(
        fact_id,
        space_slug=space_slug,
        memory_scope_external_ref=memory_scope_external_ref,
    )


def render_fact_note(
    fact: Mapping[str, Any],
    *,
    space_slug: str,
    memory_scope_external_ref: str,
    sync_mode: SyncMode = SyncMode.DIRECT,
) -> str:
    fact_id = str(fact["id"])
    version = int(fact["version"])
    text = str(fact["text"]).replace("\r\n", "\n").replace("\r", "\n").strip("\n")
    metadata = {
        "infinity_context_schema": NOTE_SCHEMA_VERSION,
        "infinity_context_kind": NoteKind.FACT.value,
        "infinity_context_id": fact_id,
        "infinity_context_version": version,
        "infinity_context_sync_mode": sync_mode.value,
        "infinity_context_hash": content_hash(text),
        "infinity_context_space_slug": space_slug,
        "infinity_context_memory_scope_external_ref": memory_scope_external_ref,
        "infinity_context_managed": True,
    }
    title = _title_for_fact(fact)
    body = "\n".join(
        [
            f"# {title}",
            "",
            TEXT_START,
            text,
            TEXT_END,
            "",
            "## Infinity Context Metadata",
            "",
            f"- Fact id: `{fact_id}`",
            f"- Version: `{version}`",
            f"- Kind: `{fact.get('kind', 'note')}`",
            f"- Status: `{fact.get('status', 'active')}`",
            f"- Category: `{fact.get('category') or ''}`",
            "",
            "Edit only the managed text block above for direct sync.",
            "",
        ]
    )
    return dump_frontmatter(metadata) + body


def parse_fact_note(path: PurePosixPath, markdown: str) -> ManagedFactNote:
    try:
        metadata, body = split_frontmatter(markdown)
    except FrontmatterError as exc:
        raise NoteFormatError(str(exc)) from exc
    schema = str(metadata.get("infinity_context_schema") or "")
    if schema != NOTE_SCHEMA_VERSION:
        raise NoteFormatError(f"Unsupported note schema: {schema or 'missing'}")
    kind = str(metadata.get("infinity_context_kind") or "")
    if kind != NoteKind.FACT.value:
        raise NoteFormatError(f"Unsupported note kind: {kind or 'missing'}")
    fact_id = str(metadata.get("infinity_context_id") or "").strip()
    if not fact_id:
        raise NoteFormatError("Missing infinity_context_id")
    version_value = metadata.get("infinity_context_version")
    if not isinstance(version_value, int):
        raise NoteFormatError("infinity_context_version must be an integer")
    mode_value = str(metadata.get("infinity_context_sync_mode") or SyncMode.READONLY.value)
    try:
        sync_mode = SyncMode(mode_value)
    except ValueError as exc:
        raise NoteFormatError(f"Unsupported sync mode: {mode_value}") from exc
    text = _extract_managed_text(body).strip("\n")
    return ManagedFactNote(
        path=path,
        fact_id=fact_id,
        version=version_value,
        sync_mode=sync_mode,
        text=text,
        content_hash=content_hash(text),
        stored_hash=_optional_str(metadata.get("infinity_context_hash")),
        frontmatter=metadata,
    )


def state_record_for_note(note: ManagedFactNote, version: int | None = None) -> SyncStateRecord:
    return SyncStateRecord(
        path=note.path,
        infinity_context_id=note.fact_id,
        kind=NoteKind.FACT,
        version=version or note.version,
        content_hash=note.content_hash,
    )


def _extract_managed_text(body: str) -> str:
    start = body.find(TEXT_START)
    if start == -1:
        raise NoteFormatError("Missing managed text start marker")
    content_start = start + len(TEXT_START)
    end = body.find(TEXT_END, content_start)
    if end == -1:
        raise NoteFormatError("Missing managed text end marker")
    return body[content_start:end].strip("\n")


def _title_for_fact(fact: Mapping[str, Any]) -> str:
    text = str(fact.get("text") or "").strip().splitlines()
    first_line = text[0] if text else str(fact["id"])
    return first_line[:80] or str(fact["id"])


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)

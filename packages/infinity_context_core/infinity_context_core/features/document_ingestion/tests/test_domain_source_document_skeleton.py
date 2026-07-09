"""Feature-local checks for document_ingestion source document domain."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, fields, is_dataclass

import pytest
from infinity_context_core.features.document_ingestion import public


def test_source_document_draft_normalizes_hashes_and_freezes_values() -> None:
    scope = public.DocumentIngestionScope(
        space_id=" space-1 ",
        memory_scope_id=" scope-1 ",
        thread_id=" thread-1 ",
    )
    origin = public.SourceDocumentOrigin(
        source_type=" upload ",
        source_external_id=" doc.txt ",
        uri=" file://doc.txt ",
    )

    draft = public.SourceDocumentDraft.create(
        scope=scope,
        title=" Requirements ",
        origin=origin,
        text="\r\nHello\x00 world.\r\n\nSecond line.\r\n",
        classification=" internal ",
    )

    assert draft.scope.space_id == "space-1"
    assert draft.scope.memory_scope_id == "scope-1"
    assert draft.scope.thread_id == "thread-1"
    assert draft.origin.source_type == "upload"
    assert draft.origin.source_external_id == "doc.txt"
    assert draft.title == "Requirements"
    assert draft.content.text == "Hello world.\n\nSecond line."
    assert draft.content.content_hash == public.content_hash_for_text(
        "Hello world.\n\nSecond line."
    )
    assert draft.classification == "internal"
    assert is_dataclass(draft)
    assert not hasattr(draft, "__dict__")
    _assert_frozen(draft)


def test_source_document_snapshot_is_created_from_validated_draft() -> None:
    scope = public.DocumentIngestionScope(space_id="space-1", memory_scope_id="scope-1")
    origin = public.SourceDocumentOrigin(
        source_type="markdown",
        source_external_id="readme.md",
    )
    draft = public.SourceDocumentDraft.create(
        scope=scope,
        title="Readme",
        origin=origin,
        text="Document text",
        classification="internal",
    )

    document = public.SourceDocument.from_draft(document_id="doc-1", draft=draft)

    assert document.identity.document_id == "doc-1"
    assert document.identity.scope is scope
    assert document.title == "Readme"
    assert document.origin is origin
    assert document.content_hash == draft.content.content_hash
    assert document.status == "active"
    assert document.classification == "internal"
    _assert_frozen(document)


def test_source_document_rejects_blank_required_values() -> None:
    scope = public.DocumentIngestionScope(space_id="space-1", memory_scope_id="scope-1")
    origin = public.SourceDocumentOrigin(source_type="upload", source_external_id="doc.txt")

    with pytest.raises(public.DocumentIngestionValidationError):
        public.SourceDocumentDraft.create(
            scope=scope,
            title=" ",
            origin=origin,
            text="Document text",
        )

    with pytest.raises(public.DocumentIngestionValidationError):
        public.SourceDocumentDraft.create(
            scope=scope,
            title="Document",
            origin=origin,
            text="\n\t ",
        )


def _assert_frozen(value: object) -> None:
    field_name = fields(value)[0].name
    try:
        setattr(value, field_name, None)
    except FrozenInstanceError:
        pass
    else:  # pragma: no cover - clearer assertion failure only.
        raise AssertionError(f"{type(value).__name__} should be immutable")

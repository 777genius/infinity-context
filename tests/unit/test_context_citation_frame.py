"""Citation reliability: char ranges must map to source coordinates.

Mirrors the ``context_hydration`` chunk citation path: the quote snippet is built
over the clean chunk body (not the enriched retrieval text) and its range is mapped
to the source via ``chunk.char_start``. A regression here means the citation points
into the wrong coordinate space and/or quotes retrieval metadata (title / hints)
instead of the verbatim evidence.
"""

from datetime import UTC, datetime
from types import SimpleNamespace

from infinity_context_core.application.context_collectors import _rag_chunk_item
from infinity_context_core.application.context_link_expansion_items import (
    _linked_chunk_context_item,
)
from infinity_context_core.application.context_ranking import dedupe_rank_items
from infinity_context_core.application.context_snippets import (
    QuerySnippet,
    query_focused_snippet,
    query_snippet_diagnostics,
    source_refs_with_query_snippet,
)
from infinity_context_core.application.document_text import document_chunk_retrieval_text
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.application.use_cases.build_context_item_projection import (
    _chunk_context_item,
)
from infinity_context_core.application.use_cases.build_context_keyword_aggregation_support import (
    _with_duplicate_member_source_refs,
)
from infinity_context_core.domain.assets import MemoryContextLink, MemoryContextLinkId
from infinity_context_core.domain.entities import (
    MemoryChunk,
    MemoryChunkId,
    MemoryChunkKind,
    MemoryDocumentId,
    MemoryScopeId,
    SourceRef,
    SpaceId,
)
from infinity_context_core.ports.capabilities import (
    CapabilityRecallCandidate,
    MemoryCapability,
)

_CHUNK_BODY = (
    "user: What is the retry budget for the export job?\n"
    "assistant: The export retry budget is 20 records per run."
)
_CHUNK_CHAR_START = 500


def _cite(body: str, query: str) -> tuple[QuerySnippet, SourceRef]:
    snippet = query_focused_snippet(query=query, text=body)
    assert snippet is not None
    ref = SourceRef(
        source_type="conversation",
        source_id="thread-1",
        chunk_id="chunk-1",
        char_start=_CHUNK_CHAR_START,
        char_end=_CHUNK_CHAR_START + len(body),
    )
    ref = source_refs_with_query_snippet(
        (ref,),
        snippet,
        include_char_range=True,
        source_char_base=_CHUNK_CHAR_START,
    )[0]
    return snippet, ref


def test_citation_char_range_resolves_to_source_evidence() -> None:
    snippet, ref = _cite(_CHUNK_BODY, "What is the retry budget for the export job?")
    body = _CHUNK_BODY
    assert ref.char_start is not None and ref.char_end is not None
    # The cited slice in the source document contains the matched evidence.
    cited = body[ref.char_start - _CHUNK_CHAR_START : ref.char_end - _CHUNK_CHAR_START]
    assert "retry budget" in cited
    # The range is the snippet window shifted to the source origin.
    assert ref.char_start == _CHUNK_CHAR_START + snippet.char_start
    assert ref.char_end == _CHUNK_CHAR_START + snippet.char_end


def test_citation_range_stays_within_source_chunk_and_narrows() -> None:
    filler = "The team reviewed unrelated roadmap items and staffing notes. " * 8
    body = filler + _CHUNK_BODY + filler
    _s, ref = _cite(body, "What is the retry budget for the export job?")
    assert ref.char_start is not None and ref.char_end is not None
    assert ref.char_start >= _CHUNK_CHAR_START
    assert ref.char_end <= _CHUNK_CHAR_START + len(body)
    # Narrowed toward the evidence rather than spanning the whole padded body.
    assert ref.char_end - ref.char_start < len(body)
    cited = body[ref.char_start - _CHUNK_CHAR_START : ref.char_end - _CHUNK_CHAR_START]
    assert "retry budget" in cited


def test_citation_preview_is_verbatim_evidence_not_retrieval_hints() -> None:
    snippet, ref = _cite(_CHUNK_BODY, "What is the retry budget for the export job?")
    assert "Retrieval hints" not in ref.quote_preview
    assert ref.quote_preview == snippet.text
    assert "retry budget" in ref.quote_preview


def test_query_snippet_diagnostic_matches_citation_char_range() -> None:
    snippet, ref = _cite(_CHUNK_BODY, "What is the retry budget for the export job?")
    diagnostics = query_snippet_diagnostics(
        snippet,
        source_char_base=_CHUNK_CHAR_START,
    )
    assert diagnostics["query_snippet_char_start"] == ref.char_start
    assert diagnostics["query_snippet_char_end"] == ref.char_end


def test_chunk_collectors_share_one_citation_frame_so_dedupe_merges_one_ref() -> None:
    chunk = MemoryChunk.create(
        chunk_id=MemoryChunkId("chunk_1"),
        space_id=SpaceId("space_1"),
        memory_scope_id=MemoryScopeId("scope_1"),
        document_id=MemoryDocumentId("document_1"),
        source_type="document",
        source_external_id="source_1",
        source_hash="hash_1",
        kind=MemoryChunkKind.DOCUMENT_SECTION,
        text=_CHUNK_BODY,
        normalized_text=_CHUNK_BODY.casefold(),
        sequence=1,
        char_start=_CHUNK_CHAR_START,
        char_end=_CHUNK_CHAR_START + len(_CHUNK_BODY),
        token_estimate=20,
        now=datetime(2026, 6, 18, tzinfo=UTC),
        metadata={"title": "Export Runbook"},
    )
    query = "retry budget"
    keyword_item = _chunk_context_item(
        chunk=chunk,
        text=document_chunk_retrieval_text(text=chunk.text, metadata=chunk.metadata),
        retrieval_source="keyword_chunks",
        base_score=0.5,
        score=0.6,
        relevance=None,
        query_text=query,
    )
    rag_item = _rag_chunk_item(
        CapabilityRecallCandidate(
            item_id=str(chunk.id),
            item_type="chunk",
            text="provider text must not render",
            score=0.7,
            source_refs=(),
            capability=MemoryCapability.RAG_RECALL,
            adapter_name="test-adapter",
        ),
        chunk,
        query_text=query,
    )

    linked_item = _linked_chunk_context_item(
        chunk,
        link=MemoryContextLink.create(
            link_id=MemoryContextLinkId("context_link_1"),
            space_id=SpaceId("space_1"),
            memory_scope_id=MemoryScopeId("scope_1"),
            source_type="anchor",
            source_id="anchor_1",
            target_type="chunk",
            target_id=str(chunk.id),
            relation_type="evidence_of",
            confidence="high",
            reason="test link",
            now=datetime(2026, 6, 18, tzinfo=UTC),
        ),
        query_text=query,
    )

    keyword_ref = keyword_item.source_refs[0]
    rag_ref = rag_item.source_refs[0]
    linked_ref = linked_item.source_refs[0]
    assert (keyword_ref.quote_preview, keyword_ref.char_start, keyword_ref.char_end) == (
        rag_ref.quote_preview,
        rag_ref.char_start,
        rag_ref.char_end,
    )
    assert (keyword_ref.quote_preview, keyword_ref.char_start, keyword_ref.char_end) == (
        linked_ref.quote_preview,
        linked_ref.char_start,
        linked_ref.char_end,
    )
    assert "Retrieval hints" not in (keyword_ref.quote_preview or "")
    assert "Export Runbook" not in (keyword_ref.quote_preview or "")
    assert "retry budget" in (keyword_ref.quote_preview or "")
    assert keyword_ref.char_start is not None
    assert keyword_ref.char_end is not None
    assert keyword_ref.char_start >= _CHUNK_CHAR_START
    # The emitted char range indexes the clean chunk body in source coordinates,
    # so a doubled source_char_base would point outside the matched evidence.
    cited = _CHUNK_BODY[
        keyword_ref.char_start - _CHUNK_CHAR_START : keyword_ref.char_end - _CHUNK_CHAR_START
    ]
    assert "retry budget" in cited

    merged = dedupe_rank_items((keyword_item, rag_item, linked_item))
    assert len(merged) == 1
    assert len(merged[0].source_refs) == 1
    assert merged[0].diagnostics["provenance"]["source_ref_count"] == 1


def test_chunk_collectors_share_fallback_preview_without_snippet() -> None:
    # No clean-body window exists for this query, so the quote falls back to the
    # plain body preview. All collectors must pass the identical preview into
    # chunk_source_refs, otherwise dialogue-turn refs diverge past char 200 and
    # dedupe keeps multiple refs for one chunk.
    body = (
        "user: D1:1 hello there\n"
        + "The team reviewed unrelated roadmap items and staffing notes. " * 4
        + "assistant: D1:2 the follow-up lands beyond the two hundred char cap."
    )
    chunk = MemoryChunk.create(
        chunk_id=MemoryChunkId("chunk_1"),
        space_id=SpaceId("space_1"),
        memory_scope_id=MemoryScopeId("scope_1"),
        document_id=MemoryDocumentId("document_1"),
        source_type="document",
        source_external_id="thread:session_1",
        source_hash="hash_1",
        kind=MemoryChunkKind.DOCUMENT_SECTION,
        text=body,
        normalized_text=body.casefold(),
        sequence=1,
        char_start=0,
        char_end=len(body),
        token_estimate=40,
        now=datetime(2026, 6, 18, tzinfo=UTC),
        metadata={"title": "Export Runbook"},
    )
    query = "nonexistent term xyzzy"
    keyword_item = _chunk_context_item(
        chunk=chunk,
        text=document_chunk_retrieval_text(text=chunk.text, metadata=chunk.metadata),
        retrieval_source="keyword_chunks",
        base_score=0.5,
        score=0.6,
        relevance=None,
        query_text=query,
    )
    rag_item = _rag_chunk_item(
        CapabilityRecallCandidate(
            item_id=str(chunk.id),
            item_type="chunk",
            text="provider text must not render",
            score=0.7,
            source_refs=(),
            capability=MemoryCapability.RAG_RECALL,
            adapter_name="test-adapter",
        ),
        chunk,
        query_text=query,
    )
    linked_item = _linked_chunk_context_item(
        chunk,
        link=MemoryContextLink.create(
            link_id=MemoryContextLinkId("context_link_1"),
            space_id=SpaceId("space_1"),
            memory_scope_id=MemoryScopeId("scope_1"),
            source_type="anchor",
            source_id="anchor_1",
            target_type="chunk",
            target_id=str(chunk.id),
            relation_type="evidence_of",
            confidence="high",
            reason="test link",
            now=datetime(2026, 6, 18, tzinfo=UTC),
        ),
        query_text=query,
    )

    expected_refs = keyword_item.source_refs
    assert len(expected_refs) >= 2  # fallback ref + dialogue-turn refs
    assert rag_item.source_refs == expected_refs
    assert linked_item.source_refs == expected_refs

    merged = dedupe_rank_items((keyword_item, rag_item, linked_item))
    assert len(merged) == 1
    assert len(merged[0].source_refs) == len(expected_refs)


def test_duplicate_member_merge_reuses_shared_citation_frame() -> None:
    # The keyword-aggregation duplicate-member merge renders member evidence over
    # the enriched retrieval text (title + retrieval hints). Quoting that render
    # would emit refs that diverge from the member chunk's own collector refs, so
    # dedupe keeps duplicates quoting retrieval metadata instead of the body.
    member_chunk = MemoryChunk.create(
        chunk_id=MemoryChunkId("chunk_member"),
        space_id=SpaceId("space_1"),
        memory_scope_id=MemoryScopeId("scope_1"),
        document_id=MemoryDocumentId("document_1"),
        source_type="document",
        source_external_id="source_1",
        source_hash="hash_1",
        kind=MemoryChunkKind.DOCUMENT_SECTION,
        text=_CHUNK_BODY,
        normalized_text=_CHUNK_BODY.casefold(),
        sequence=2,
        char_start=_CHUNK_CHAR_START,
        char_end=_CHUNK_CHAR_START + len(_CHUNK_BODY),
        token_estimate=20,
        now=datetime(2026, 6, 18, tzinfo=UTC),
        metadata={"title": "Export Runbook"},
    )
    enriched_member_text = document_chunk_retrieval_text(
        text=member_chunk.text,
        metadata=member_chunk.metadata,
    )

    def _candidate(chunk: MemoryChunk, candidate_id: str, member_ids: tuple[str, ...]):
        return SimpleNamespace(
            admission=SimpleNamespace(candidate_id=candidate_id),
            chunk=chunk,
            member_ids=member_ids,
            member_evidence_text=enriched_member_text,
            aggregation_query="retry budget",
        )

    owner = _candidate(member_chunk, "owner", ("m1", "m2"))
    duplicate = _candidate(member_chunk, "duplicate", ("m1",))
    item = ContextItem(
        item_id="owner",
        item_type="chunk",
        text="owner aggregation item",
        score=0.985,
        source_refs=(),
        is_instruction=False,
        diagnostics={},
    )

    merged_item = _with_duplicate_member_source_refs(
        item,
        candidate=owner,
        candidates=(owner, duplicate),
        provenance_admitted_ids=frozenset({"duplicate"}),
    )

    expected_refs = _chunk_context_item(
        chunk=member_chunk,
        text=enriched_member_text,
        retrieval_source="keyword_aggregation_chunks",
        base_score=0.78,
        score=0.985,
        relevance=None,
        query_text="retry budget",
    ).source_refs
    assert merged_item.source_refs == expected_refs
    ref = merged_item.source_refs[0]
    assert "Retrieval hints" not in (ref.quote_preview or "")
    assert "Export Runbook" not in (ref.quote_preview or "")
    assert "retry budget" in (ref.quote_preview or "")
    assert ref.char_start is not None and ref.char_end is not None
    cited = _CHUNK_BODY[
        ref.char_start - _CHUNK_CHAR_START : ref.char_end - _CHUNK_CHAR_START
    ]
    assert "retry budget" in cited

    # Without a resolvable query snippet the merge must still match the member's
    # own fallback refs (clean body preview), not quote the enriched render.
    fallback_duplicate = SimpleNamespace(
        admission=SimpleNamespace(candidate_id="duplicate"),
        chunk=member_chunk,
        member_ids=("m1",),
        member_evidence_text=enriched_member_text,
        aggregation_query="nonexistent term xyzzy",
    )
    fallback_expected = _chunk_context_item(
        chunk=member_chunk,
        text=enriched_member_text,
        retrieval_source="keyword_aggregation_chunks",
        base_score=0.78,
        score=0.985,
        relevance=None,
        query_text="nonexistent term xyzzy",
    ).source_refs
    fallback_merged = _with_duplicate_member_source_refs(
        item,
        candidate=owner,
        candidates=(owner, fallback_duplicate),
        provenance_admitted_ids=frozenset({"duplicate"}),
    )
    assert fallback_merged.source_refs == fallback_expected

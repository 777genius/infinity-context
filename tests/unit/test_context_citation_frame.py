"""Citation reliability: char ranges must map to the source and previews must be clean.

Mirrors the context_hydration chunk path, which builds the citation snippet over the
clean chunk body and maps offsets back to the source via ``chunk.char_start``. A
regression here means citations point into the wrong coordinate space (enriched
retrieval text) and/or quote polluted text (title / retrieval hints) instead of the
evidence.
"""

from infinity_context_core.application.context_snippets import (
    query_focused_snippet,
    source_refs_with_query_snippet,
)
from infinity_context_core.domain.entities import SourceRef

# Raw source chunk body as stored; the chunk starts at document offset 500.
_CHUNK_BODY = (
    "user: What is the retry budget for the export job?\n"
    "assistant: The export retry budget is 20 records per run."
)
_CHUNK_CHAR_START = 500


def _snippet_and_refs():
    snippet = query_focused_snippet(
        query="What is the retry budget for the export job?",
        text=_CHUNK_BODY,
    )
    assert snippet is not None
    ref = SourceRef(
        source_type="conversation",
        source_id="thread-1",
        chunk_id="chunk-1",
        char_start=_CHUNK_CHAR_START,
        char_end=_CHUNK_CHAR_START + len(_CHUNK_BODY),
    )
    enriched = source_refs_with_query_snippet(
        (ref,),
        snippet,
        include_char_range=True,
        source_char_base=_CHUNK_CHAR_START,
    )
    return snippet, enriched[0]


def test_citation_char_range_maps_to_source_coordinates() -> None:
    snippet, ref = _snippet_and_refs()
    # Invariant: the exposed range equals the snippet's body-relative range
    # shifted to the source origin (chunk.char_start).
    assert ref.char_start == _CHUNK_CHAR_START + snippet.char_start
    assert ref.char_end == _CHUNK_CHAR_START + snippet.char_end


def test_citation_range_narrows_and_stays_within_source_chunk() -> None:
    filler = ("The team reviewed unrelated roadmap items and staffing notes. " * 8)
    body = filler + _CHUNK_BODY + filler
    snippet = query_focused_snippet(
        query="What is the retry budget for the export job?",
        text=body,
    )
    assert snippet is not None
    ref = SourceRef(source_type="conversation", source_id="t", chunk_id="c")
    ref = source_refs_with_query_snippet(
        (ref,), snippet, include_char_range=True, source_char_base=_CHUNK_CHAR_START
    )[0]
    # Range is source-frame and stays inside the chunk's source span.
    assert ref.char_start is not None and ref.char_end is not None
    assert ref.char_start >= _CHUNK_CHAR_START
    assert ref.char_end <= _CHUNK_CHAR_START + len(body)
    # It narrowed toward the evidence (not the whole padded body).
    assert ref.char_end - ref.char_start < len(body)
    # The cited source slice really contains the previewed evidence.
    cited = body[ref.char_start - _CHUNK_CHAR_START : ref.char_end - _CHUNK_CHAR_START]
    assert "retry budget" in cited


def test_citation_preview_is_clean_evidence_not_retrieval_hints() -> None:
    snippet, ref = _snippet_and_refs()
    assert "Retrieval hints" not in ref.quote_preview
    assert ref.quote_preview == snippet.text
    # The preview must actually contain the matched evidence.
    assert "retry budget" in ref.quote_preview

"""Deterministic chunking for documents and transcript episodes."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TextChunk:
    text: str
    char_start: int
    char_end: int
    sequence: int


@dataclass(frozen=True)
class ChunkTextOptions:
    target_chars: int = 1200
    overlap_chars: int = 120
    min_chars: int = 160


def chunk_text(text: str, options: ChunkTextOptions | None = None) -> tuple[TextChunk, ...]:
    opts = options or ChunkTextOptions()
    cleaned = text.strip()
    if not cleaned:
        return ()
    if len(cleaned) <= opts.target_chars:
        return (TextChunk(text=cleaned, char_start=0, char_end=len(cleaned), sequence=0),)

    chunks: list[TextChunk] = []
    start = 0
    sequence = 0
    while start < len(cleaned):
        hard_end = min(len(cleaned), start + opts.target_chars)
        end = _best_boundary(cleaned, start, hard_end, opts.min_chars)
        chunk = cleaned[start:end].strip()
        if chunk:
            actual_start = start + len(cleaned[start:end]) - len(cleaned[start:end].lstrip())
            chunks.append(
                TextChunk(
                    text=chunk,
                    char_start=actual_start,
                    char_end=end,
                    sequence=sequence,
                )
            )
            sequence += 1
        if end >= len(cleaned):
            break
        start = max(end - opts.overlap_chars, start + 1)
    return tuple(chunks)


def _best_boundary(text: str, start: int, hard_end: int, min_chars: int) -> int:
    if hard_end >= len(text):
        return len(text)
    lower_bound = min(hard_end, start + min_chars)
    window = text[lower_bound:hard_end]
    for marker in ("\n\n", "\n", ". ", "? ", "! ", "; "):
        idx = window.rfind(marker)
        if idx >= 0:
            return lower_bound + idx + len(marker)
    return hard_end

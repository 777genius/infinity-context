from infinity_context_core.application.chunker import ChunkTextOptions, chunk_text


def test_chunk_text_backtracks_chunk_start_to_nearby_line_prefix() -> None:
    text = (
        "session_4 date: 2023-05-07 "
        + "context before turn " * 3
        + "\n"
        "D4:5 Caroline: "
        + "sentimental handmade bowl value " * 3
        + "A friend made it for my 18th birthday ten years ago. "
        + "colors and self-expression details " * 4
        + "\nD4:6 Melanie: That sounds great."
    )

    chunks = chunk_text(
        text,
        ChunkTextOptions(
            target_chars=260,
            overlap_chars=45,
            min_chars=120,
            line_prefix_scan_chars=180,
        ),
    )

    birthday_chunks = tuple(chunk for chunk in chunks[1:] if "18th birthday" in chunk.text)

    assert birthday_chunks
    assert birthday_chunks[0].text.startswith("D4:5 Caroline:")
    assert birthday_chunks[0].char_start == text.index("D4:5 Caroline:")

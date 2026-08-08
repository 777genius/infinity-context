"""Shared fail-closed validation for bounded textual secrets."""

from __future__ import annotations

import unicodedata


def is_bounded_text_secret(value: object, *, minimum: int = 32, maximum: int = 4_096) -> bool:
    """Accept exact text only when its UTF-8 bytes and characters are safe."""

    if value.__class__ is not str:
        return False
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return minimum <= len(encoded) <= maximum and not any(
        character.isspace() or unicodedata.category(character).startswith("C")
        for character in value
    )


__all__ = ("is_bounded_text_secret",)

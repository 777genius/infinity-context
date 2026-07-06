"""Restore-safe sys.modules isolation for provider-SDK import seam tests.

Popping only top-level SDK modules from sys.modules leaves their submodules
cached, so any later re-import binds a fresh top-level module object without
its submodule attributes (e.g. ``sqlalchemy`` without ``dialects``). The
context manager below unloads the whole module tree and restores the original
interpreter state afterwards so the rest of the test session stays healthy.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager


@contextmanager
def provider_sdk_modules_unloaded(*top_level_names: str) -> Iterator[None]:
    saved = sys.modules.copy()
    for name in list(sys.modules):
        if any(name == top or name.startswith(f"{top}.") for top in top_level_names):
            del sys.modules[name]
    try:
        yield
    finally:
        sys.modules.update(saved)

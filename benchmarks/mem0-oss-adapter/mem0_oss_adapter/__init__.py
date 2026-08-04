"""Isolated, auth-free Mem0 OSS benchmark compatibility adapter.

The package intentionally does not import FastAPI, Mem0, FastEmbed, or Qdrant at
module import time.  That keeps configuration discovery side-effect free and lets
unit tests replace every provider-bound port.
"""

__all__ = ()

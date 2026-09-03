"""Deterministic seeding.

The task requires: same brief run twice -> same video. GPT calls are made
at temperature 0 as a first line of defense, but that alone isn't a
provider-backed guarantee, so:

  1. The plan is cached on disk keyed by a hash of the brief. A second run
     of an identical brief reuses the cached plan and never calls the
     model again.
  2. Any pseudo-randomness *we* introduce inside generated compositions
     (e.g. staggered entrance offsets across N feature callouts) is drawn
     from a seeded PRNG derived from the brief hash, never from
     Python's `random` module or JS `Math.random()` in emitted HTML.
"""
from __future__ import annotations

import hashlib


def brief_hash(brief: str) -> str:
    """Stable content hash for a brief, used as the cache key and seed source."""
    return hashlib.sha256(brief.strip().encode("utf-8")).hexdigest()[:16]


def seed_from_brief(brief: str) -> int:
    """32-bit integer seed derived from the brief, for a seeded PRNG."""
    h = hashlib.sha256(brief.strip().encode("utf-8")).digest()
    return int.from_bytes(h[:4], "big")


class Mulberry32:
    """Small seeded PRNG. Deterministic across runs given the same seed.

    Mirrors the mulberry32 algorithm so behavior is easy to reason about
    and, if ever needed, reimplement identically in the generated
    composition's own JS (we don't currently emit JS-side randomness at
    all -- see builder.py -- but if a future blueprint needs it, this is
    the one PRNG the whole system should standardize on).
    """

    def __init__(self, seed: int):
        self._state = seed & 0xFFFFFFFF

    def next(self) -> float:
        self._state = (self._state + 0x6D2B79F5) & 0xFFFFFFFF
        t = self._state
        t = (t ^ (t >> 15)) * (t | 1) & 0xFFFFFFFF
        t ^= (t + ((t ^ (t >> 7)) * (t | 61) & 0xFFFFFFFF)) & 0xFFFFFFFF
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296

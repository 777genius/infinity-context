from __future__ import annotations

import hashlib

from infinity_context_server.memory_comparison_benchmark_identity import (
    mem0_benchmark_corpus_user_id,
    mem0_benchmark_user_id,
)


def test_benchmark_user_id_is_collision_resistant_and_adapter_safe() -> None:
    colliding_under_old_slug = (
        ("Run_X", "run-x"),
        ("A/B", "a-b"),
        ("a" * 80 + "first", "a" * 80 + "second"),
    )
    for left, right in colliding_under_old_slug:
        left_id = mem0_benchmark_user_id(left)
        right_id = mem0_benchmark_user_id(right)
        assert left_id != right_id
        assert len(left_id) <= 160
        assert len(right_id) <= 160
        assert left_id.endswith(hashlib.sha256(left.encode()).hexdigest())
        assert right_id.endswith(hashlib.sha256(right.encode()).hexdigest())


def test_corpus_user_id_is_run_and_corpus_scoped() -> None:
    alpha = mem0_benchmark_corpus_user_id("run-1", "corpus-alpha")
    beta = mem0_benchmark_corpus_user_id("run-1", "corpus-beta")
    next_run = mem0_benchmark_corpus_user_id("run-2", "corpus-alpha")

    assert len({alpha, beta, next_run}) == 3
    assert len(alpha) <= 160
    assert alpha.endswith(hashlib.sha256(b"run-1\0corpus-alpha").hexdigest())

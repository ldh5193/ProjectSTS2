"""Structural tests for sim/rng.py (the .NET seeded Knuth subtractive port).

Bit-exact agreement with .NET 9 `System.Random(int)` lives in
tests/test_rng_oracle.py, which checks the same Python implementation
against vectors emitted by `tools/RngOracle/`.
"""
from __future__ import annotations

from sim.rng import (
    DotNetSeededRandom,
    PlayerRngSet,
    Rng,
    RunRngSet,
    get_deterministic_hash_code,
)


def test_deterministic_hash_is_stable():
    a = get_deterministic_hash_code("monster_ai")
    b = get_deterministic_hash_code("monster_ai")
    assert a == b
    assert get_deterministic_hash_code("monster_ai") != get_deterministic_hash_code("shuffle")


def test_deterministic_hash_returns_signed_int32():
    for s in ["", "a", "monster_ai", "rewards", "abcdef" * 20]:
        h = get_deterministic_hash_code(s)
        assert -(2 ** 31) <= h < 2 ** 31


def test_random_is_deterministic_for_same_seed():
    a = DotNetSeededRandom(42)
    b = DotNetSeededRandom(42)
    for _ in range(100):
        assert a.next() == b.next()


def test_random_different_seeds_diverge():
    a = DotNetSeededRandom(1)
    b = DotNetSeededRandom(2)
    assert a.next() != b.next()


def test_random_next_in_int32_range():
    r = DotNetSeededRandom(123)
    for _ in range(1000):
        v = r.next()
        assert 0 <= v < 2 ** 31


def test_random_next_max_in_range():
    r = DotNetSeededRandom(7)
    for _ in range(10_000):
        v = r.next_max(10)
        assert 0 <= v < 10


def test_random_next_double_in_unit_interval():
    r = DotNetSeededRandom(7)
    for _ in range(1000):
        v = r.next_double()
        assert 0.0 <= v < 1.0


def test_rng_counter_advances_per_call():
    r = Rng(42, "monster_ai")
    assert r.counter == 0
    r.next_int(0, 10)
    assert r.counter == 1
    r.next_int(0, 10)
    assert r.counter == 2
    r.next_float()
    assert r.counter == 3


def test_rng_fast_forward_reproduces_stream():
    r1 = Rng(42, "shuffle")
    for _ in range(5):
        r1.next_int(0, 1000)
    r2 = Rng(42, "shuffle")
    r2.fast_forward(5)
    assert r1.next_int(0, 1000) == r2.next_int(0, 1000)


def test_rng_categories_are_independent():
    rs = RunRngSet(seed=42)
    a = rs.monster_ai.next_int(0, 1_000_000)
    b = rs.shuffle.next_int(0, 1_000_000)
    assert a != b


def test_player_and_run_sets_have_expected_categories():
    p = PlayerRngSet(0)
    r = RunRngSet(0)
    assert set(p.rngs) == {"rewards", "shops", "transformations"}
    assert "monster_ai" in r.rngs and "shuffle" in r.rngs
    assert len(r.rngs) == 12


def test_rng_set_snapshot_restore_roundtrip():
    rs = RunRngSet(seed=99)
    for _ in range(3):
        rs.monster_ai.next_int(0, 100)
    for _ in range(7):
        rs.shuffle.next_int(0, 100)
    snap = rs.snapshot()
    restored = RunRngSet.restore(snap)
    assert restored.monster_ai.next_int(0, 100) == rs.monster_ai.next_int(0, 100)
    assert restored.shuffle.next_int(0, 100) == rs.shuffle.next_int(0, 100)


def test_rng_rejects_rewind():
    r = Rng(0, "x")
    r.next_int(0, 10)
    try:
        r.fast_forward(0)
    except ValueError:
        return
    raise AssertionError("rewind should have been rejected")

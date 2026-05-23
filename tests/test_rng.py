"""Tests for the PRNG port — sim/rng.py.

These tests verify structural correctness (determinism, range, counter advance,
category independence). Bit-exact agreement with the real game's .NET
xoshiro256** stream is NOT verified here — it requires test vectors that can
only be extracted from a running game (Phase 7 L6).
"""
from __future__ import annotations

from sim.rng import (
    PlayerRngSet,
    Rng,
    RunRngSet,
    Xoshiro256StarStar,
    get_deterministic_hash_code,
)


def test_deterministic_hash_is_stable():
    # Hash function must be deterministic; values themselves are arbitrary but stable.
    a = get_deterministic_hash_code("monster_ai")
    b = get_deterministic_hash_code("monster_ai")
    assert a == b
    assert get_deterministic_hash_code("monster_ai") != get_deterministic_hash_code("shuffle")


def test_deterministic_hash_returns_signed_int32():
    for s in ["", "a", "monster_ai", "rewards", "abcdef" * 20]:
        h = get_deterministic_hash_code(s)
        assert -(2 ** 31) <= h < 2 ** 31


def test_xoshiro_is_deterministic_for_same_seed():
    a = Xoshiro256StarStar(42)
    b = Xoshiro256StarStar(42)
    for _ in range(100):
        assert a.next_uint64() == b.next_uint64()


def test_xoshiro_different_seeds_diverge():
    a = Xoshiro256StarStar(1)
    b = Xoshiro256StarStar(2)
    assert a.next_uint64() != b.next_uint64()


def test_xoshiro_uint64_range():
    r = Xoshiro256StarStar(123)
    for _ in range(1000):
        v = r.next_uint64()
        assert 0 <= v < 2 ** 64


def test_xoshiro_next_int_in_range():
    r = Xoshiro256StarStar(7)
    for _ in range(10_000):
        v = r.next_int_max(10)
        assert 0 <= v < 10


def test_xoshiro_next_double_in_unit_interval():
    r = Xoshiro256StarStar(7)
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
    # Create an Rng, advance by 5 calls, then create a new Rng and fast-forward 5,
    # both should produce the same next number.
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
    # Independent streams should almost always disagree on the first sample.
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
    # After restore, the next draw must match the original's continuation.
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

"""PRNG port — notes/04_prng.md.

Implements xoshiro256** with SplitMix64 seed expansion (the standard pattern
.NET 6+ adopted for System.Random) plus the project's deterministic string
hash + per-category Rng wrapper.

This module is algorithmically correct (matches the xoshiro256** spec) but
has not yet been validated against bit-exact game output. Validation requires
extracting test vectors via the running mod (Phase 7 L6, see notes/07_validation.md).
Until then, treat it as "structurally faithful, not byte-exact."
"""
from __future__ import annotations

MASK64 = 0xFFFFFFFFFFFFFFFF


def get_deterministic_hash_code(s: str) -> int:
    """StringHelper.GetDeterministicHashCode replica. Returns signed Int32."""
    num = 352654597
    num2 = num
    n = len(s)
    i = 0
    while i < n:
        num = (((num << 5) + num) ^ ord(s[i])) & 0xFFFFFFFF
        if i + 1 >= n:
            break
        num2 = (((num2 << 5) + num2) ^ ord(s[i + 1])) & 0xFFFFFFFF
        i += 2

    result = (num + num2 * 1566083941) & 0xFFFFFFFF
    if result >= 2 ** 31:
        result -= 2 ** 32
    return result


def _split_mix_64(state: int) -> tuple[int, int]:
    """One step of SplitMix64. Returns (new_state, output)."""
    state = (state + 0x9E3779B97F4A7C15) & MASK64
    z = state
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E7B5) & MASK64
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASK64
    return state, z ^ (z >> 31)


def _rotl64(x: int, k: int) -> int:
    return ((x << k) | (x >> (64 - k))) & MASK64


class Xoshiro256StarStar:
    """xoshiro256** core. Bit-exact to the standard spec."""

    __slots__ = ("s0", "s1", "s2", "s3")

    def __init__(self, seed: int):
        s = seed & MASK64
        s, self.s0 = _split_mix_64(s)
        s, self.s1 = _split_mix_64(s)
        s, self.s2 = _split_mix_64(s)
        s, self.s3 = _split_mix_64(s)
        # SplitMix64 never produces an all-zero quadruplet for non-zero seed.

    def next_uint64(self) -> int:
        result = (_rotl64((self.s1 * 5) & MASK64, 7) * 9) & MASK64
        t = (self.s1 << 17) & MASK64
        self.s2 ^= self.s0
        self.s3 ^= self.s1
        self.s1 ^= self.s2
        self.s0 ^= self.s3
        self.s2 ^= t
        self.s3 = _rotl64(self.s3, 45)
        return result

    def next_int_max(self, max_exclusive: int) -> int:
        # Multiplicative reduction (Lemire-style, no rejection) — matches the .NET 9
        # System.Random fast-path and guarantees exactly one next_uint64() call per
        # invocation, which is critical for counter-based save/load determinism.
        # Tiny bias when max_exclusive is not a power of two; acceptable for sim use.
        if max_exclusive <= 0:
            raise ValueError("max_exclusive must be > 0")
        if max_exclusive == 1:
            return 0
        return (self.next_uint64() * max_exclusive) >> 64

    def next_double(self) -> float:
        # 53-bit precision (matches .NET 6+ NextDouble).
        return (self.next_uint64() >> 11) * (1.0 / (1 << 53))


class Rng:
    """Counter-tracked, category-aware wrapper. Mirrors decompiled MegaCrit.Sts2.Core.Random.Rng.

    Construct with a base seed and optional category name; the name's deterministic
    hash is folded in so each category has an independent stream.
    """

    __slots__ = ("seed", "counter", "_rng")

    def __init__(self, seed: int, name: str = "", counter: int = 0):
        if name:
            seed = (seed + get_deterministic_hash_code(name)) & 0xFFFFFFFF
        self.seed = seed
        self.counter = 0
        self._rng = Xoshiro256StarStar(seed)
        if counter:
            self.fast_forward(counter)

    def fast_forward(self, target_counter: int) -> None:
        if target_counter < self.counter:
            raise ValueError(
                f"cannot rewind RNG (have {self.counter}, asked {target_counter})"
            )
        while self.counter < target_counter:
            self._rng.next_uint64()
            self.counter += 1

    def next_int(self, min_inclusive: int, max_exclusive: int) -> int:
        if max_exclusive <= min_inclusive:
            raise ValueError("max must exceed min")
        self.counter += 1
        return min_inclusive + self._rng.next_int_max(max_exclusive - min_inclusive)

    def next_float(self, lo: float = 0.0, hi: float = 1.0) -> float:
        self.counter += 1
        return self._rng.next_double() * (hi - lo) + lo

    def next_item(self, items):
        if not items:
            return None
        return items[self.next_int(0, len(items))]


# Category names — notes/04_prng.md §2.
PLAYER_CATEGORIES = ("rewards", "shops", "transformations")
RUN_CATEGORIES = (
    "monster_ai", "combat_targets", "shuffle", "combat_card_generation",
    "combat_potion_generation", "unknown_map_point", "combat_energy_costs",
    "combat_card_selection", "combat_orb_generation", "treasure_room_relics",
    "niche", "up_front",
)


class _RngSet:
    """Bag of named Rngs sharing a base seed."""

    def __init__(self, seed: int, categories: tuple[str, ...]):
        self.seed = seed
        self.rngs: dict[str, Rng] = {c: Rng(seed, c) for c in categories}

    def __getattr__(self, name: str) -> Rng:
        try:
            return self.rngs[name]
        except KeyError as e:
            raise AttributeError(name) from e

    def snapshot(self) -> dict:
        return {"seed": self.seed, "counters": {k: r.counter for k, r in self.rngs.items()}}

    @classmethod
    def restore(cls, snapshot: dict) -> "_RngSet":
        # cls is a subclass (PlayerRngSet / RunRngSet) which fixes the category list.
        s = cls(snapshot["seed"])
        for k, c in snapshot["counters"].items():
            s.rngs[k].fast_forward(c)
        return s


class PlayerRngSet(_RngSet):
    def __init__(self, seed: int):
        super().__init__(seed, PLAYER_CATEGORIES)


class RunRngSet(_RngSet):
    def __init__(self, seed: int):
        super().__init__(seed, RUN_CATEGORIES)

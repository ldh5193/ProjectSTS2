"""PRNG port — bit-exact mirror of .NET 9 `System.Random(int seed)` plus
the game's MegaCrit.Sts2.Core.Random.Rng convenience methods.

Background (notes/04_prng.md §1, corrected by the Phase 4 oracle in
tools/RngOracle/): in .NET 6+, only the **seedless** `Random()` constructor
uses xoshiro256**. The **seeded** `Random(int seed)` constructor — which is
what `MegaCrit.Sts2.Core.Random.Rng` uses — continues to run the legacy
Knuth subtractive 55-element generator for compatibility with .NET 1.0.
The full source lives in dotnet/runtime under
`Random.CompatImpl.cs`; this module reproduces it integer-for-integer.

Once the core matches, the `Rng` / `PlayerRngSet` / `RunRngSet` wrappers
layer on top: per-category seed splitting via the deterministic string
hash, counter tracking, and snapshot/restore.

Verified by `tests/test_rng_oracle.py` against test vectors emitted by
`tools/RngOracle/` (a .NET 9 console app that calls the same APIs the
game does).
"""
from __future__ import annotations


MASK32 = 0xFFFFFFFF
INT32_MIN = -(1 << 31)
INT32_MAX = (1 << 31) - 1
MBIG = INT32_MAX          # = 2_147_483_647
MSEED = 161803398


def get_deterministic_hash_code(s: str) -> int:
    """StringHelper.GetDeterministicHashCode replica. Returns signed Int32."""
    num = 352654597
    num2 = num
    n = len(s)
    i = 0
    while i < n:
        num = (((num << 5) + num) ^ ord(s[i])) & MASK32
        if i + 1 >= n:
            break
        num2 = (((num2 << 5) + num2) ^ ord(s[i + 1])) & MASK32
        i += 2

    result = (num + num2 * 1566083941) & MASK32
    if result >= 1 << 31:
        result -= 1 << 32
    return result


def _to_int32(x: int) -> int:
    """C# unchecked (int) cast, used at seed conversion boundaries."""
    x &= MASK32
    if x >= 1 << 31:
        x -= 1 << 32
    return x


class DotNetSeededRandom:
    """Knuth subtractive 55-element generator — bit-exact to .NET 6+
    `Random(int Seed)` (the CompatImpl path).

    Public surface mirrors the game's `Rng.cs` needs:
        sample()      -> [0.0, 1.0)
        next()        -> [0, int.MaxValue)
        next_max(m)   -> [0, m)
        next_double() -> alias for sample()
        advance()     -> consume one sample, discard (for FastForwardCounter)
    """

    __slots__ = ("_seed_array", "_inext", "_inextp")

    def __init__(self, seed: int):
        seed = _to_int32(seed)
        # `int mj = (Seed == int.MinValue) ? int.MaxValue : Math.Abs(Seed);`
        if seed == INT32_MIN:
            mj = INT32_MAX
        else:
            mj = -seed if seed < 0 else seed
        # mj = MSEED - mj — may wrap; C# silently truncates to int32.
        mj = _to_int32(MSEED - mj)
        self._seed_array = [0] * 56
        self._seed_array[55] = mj
        mk = 1
        ii = 0
        for i in range(1, 55):
            ii += 21
            if ii >= 55:
                ii -= 55
            self._seed_array[ii] = mk
            # `mk = mj - mk` — int32 subtraction with wraparound. With mj
            # potentially as low as ~-2*10^9, this expression *will* overflow
            # for seeds near int.MaxValue / int.MinValue; the wraparound is
            # part of the algorithm.
            mk = _to_int32(mj - mk)
            if mk < 0:
                mk += MBIG
            mj = self._seed_array[ii]
        for _ in range(1, 5):
            for i in range(1, 56):
                n = i + 30
                if n >= 55:
                    n -= 55
                self._seed_array[i] = _to_int32(self._seed_array[i] - self._seed_array[1 + n])
                if self._seed_array[i] < 0:
                    self._seed_array[i] += MBIG
        self._inext = 0
        self._inextp = 21

    def _internal_sample(self) -> int:
        locINext = self._inext + 1
        if locINext >= 56:
            locINext = 1
        locINextp = self._inextp + 1
        if locINextp >= 56:
            locINextp = 1
        retVal = self._seed_array[locINext] - self._seed_array[locINextp]
        if retVal == MBIG:
            retVal -= 1
        if retVal < 0:
            retVal += MBIG
        self._seed_array[locINext] = retVal
        self._inext = locINext
        self._inextp = locINextp
        return retVal

    def sample(self) -> float:
        return self._internal_sample() * (1.0 / MBIG)

    # Aliases mirroring .NET API names that the game uses.
    def next_double(self) -> float:
        return self.sample()

    def next(self) -> int:
        """Next() — returns [0, int.MaxValue)."""
        return self._internal_sample()

    def next_max(self, max_exclusive: int) -> int:
        """Next(int maxValue) — returns [0, maxValue). max=0 returns 0; max<0 is an error."""
        if max_exclusive < 0:
            raise ValueError("maxValue must be non-negative")
        if max_exclusive <= 1:
            return 0
        # .NET: (int)(Sample() * maxValue)
        return int(self.sample() * max_exclusive)

    def next_bytes(self, n: int) -> bytes:
        """NextBytes — one Next() per byte, truncated to low 8 bits.

        .NET 6+ for the seeded path writes `(byte)Next()` per byte
        (CompatImpl), i.e. `_internal_sample() & 0xFF`.
        """
        return bytes(self._internal_sample() & 0xFF for _ in range(n))

    def advance(self) -> None:
        """Discard one sample (for FastForwardCounter)."""
        self._internal_sample()


class Rng:
    """Counter-tracked, category-aware wrapper. Mirrors decompiled
    `MegaCrit.Sts2.Core.Random.Rng`.

    Construct with a uint seed and optional category name; the name's
    deterministic hash is folded in (unchecked uint arithmetic) so each
    category has an independent stream.
    """

    __slots__ = ("seed", "counter", "_random")

    def __init__(self, seed: int, name: str = "", counter: int = 0):
        if name:
            seed = (seed + get_deterministic_hash_code(name)) & MASK32
        self.seed = seed & MASK32
        self.counter = 0
        # `new System.Random((int) seed)` — cast back to signed Int32.
        self._random = DotNetSeededRandom(_to_int32(self.seed))
        if counter:
            self.fast_forward(counter)

    def fast_forward(self, target_counter: int) -> None:
        if target_counter < self.counter:
            raise ValueError(
                f"cannot rewind RNG (have {self.counter}, asked {target_counter})"
            )
        while self.counter < target_counter:
            self._random.advance()
            self.counter += 1

    def next_int(self, min_inclusive: int, max_exclusive: int) -> int:
        """Mirrors `Rng.NextInt(min, max)`:
            return min + _random.Next(max - min)
        """
        if max_exclusive <= min_inclusive:
            raise ValueError("max must exceed min")
        self.counter += 1
        return min_inclusive + self._random.next_max(max_exclusive - min_inclusive)

    def next_float(self, lo: float = 0.0, hi: float = 1.0) -> float:
        """Mirrors `Rng.NextFloat(min, max)`:
            return (float)(_random.NextDouble() * (max - min) + min)
        Python returns a 64-bit float so we don't downcast — callers
        comparing against in-game float32 results should round explicitly.
        """
        self.counter += 1
        return self._random.next_double() * (hi - lo) + lo

    def next_double(self, lo: float = 0.0, hi: float = 1.0) -> float:
        self.counter += 1
        return self._random.next_double() * (hi - lo) + lo

    def next_bool(self) -> bool:
        """Mirrors `Rng.NextBool()` which calls `_random.Next(2) == 0`."""
        self.counter += 1
        return self._random.next_max(2) == 0

    def next_unsigned_int(self, min_inclusive: int, max_exclusive: int) -> int:
        """Mirrors `Rng.NextUnsignedInt` (notes/04_prng.md §1.2):
            double f = _random.NextDouble();
            uint u  = (uint)(f * (max - min));
            return min + u;
        """
        if max_exclusive <= min_inclusive:
            raise ValueError("max must exceed min")
        self.counter += 1
        f = self._random.next_double()
        u = int(f * (max_exclusive - min_inclusive)) & MASK32
        return min_inclusive + u

    def next_item(self, items):
        """Rng.NextItem<T> — uniform pick from non-empty collection.
        Consumes one counter slot (delegates to next_int)."""
        seq = list(items) if not isinstance(items, list) else items
        n = len(seq)
        if n == 0:
            return None
        return seq[self.next_int(0, n)]

    def next_bool(self) -> bool:
        """Rng.NextBool — `_random.Next(2) == 0`. One counter slot."""
        self.counter += 1
        return self._random.next_max(2) == 0

    def shuffle(self, lst: list) -> None:
        """Rng.Shuffle<T>(IList<T>) — Fisher-Yates from N-1 down to 1.
        Mutates in place. Each iteration consumes one counter slot via
        the inner next_int call, matching the .NET implementation."""
        for i in range(len(lst) - 1, 0, -1):
            j = self.next_int(0, i + 1)
            lst[i], lst[j] = lst[j], lst[i]

    def next_gaussian_double(self, mean: float = 0.0, std_dev: float = 1.0,
                             min_value: float = 0.0, max_value: float = 1.0) -> float:
        """Rng.NextGaussianDouble — Box-Muller (cos branch) with rejection
        until the *unscaled* value lies in [0, 1], then linearly mapped to
        [min, max]. One counter slot per call, but each loop iteration
        consumes two raw NextDouble samples from the underlying stream."""
        if min_value > max_value:
            raise ValueError("min must not exceed max")
        self.counter += 1
        import math
        while True:
            d = self._random.next_double()
            u2 = self._random.next_double()
            magnitude = math.sqrt(-2.0 * math.log(d)) if d > 0 else 0.0
            z = magnitude * math.cos(2.0 * math.pi * u2)
            v = mean + z * std_dev
            if 0.0 <= v <= 1.0:
                break
        return v * (max_value - min_value) + min_value

    def next_gaussian_float(self, mean: float = 0.0, std_dev: float = 1.0,
                            min_value: float = 0.0, max_value: float = 1.0) -> float:
        return self.next_gaussian_double(mean, std_dev, min_value, max_value)

    def next_gaussian_int(self, mean: int, std_dev: int,
                          min_value: int, max_value: int) -> int:
        """Rng.NextGaussianInt — Box-Muller (sin branch), inverted NextDouble,
        rounded to int, rejection until in [min, max]. Note: this method does
        NOT increment Counter in the decompile (counter++ omitted), so the
        Python port matches that quirk to preserve replay parity."""
        import math
        while True:
            d = 1.0 - self._random.next_double()
            u2 = 1.0 - self._random.next_double()
            z = math.sqrt(-2.0 * math.log(d)) * math.sin(2.0 * math.pi * u2) if d > 0 else 0.0
            v = mean + std_dev * z
            n = int(round(v))
            if min_value <= n <= max_value:
                return n

    def weighted_next_item(self, items, weight_fn):
        """Rng.WeightedNextItem — pick proportionally to `weight_fn(item)`.
        Burns one NextFloat (the `randInput` parameter in the static form).
        Returns the last item touched as a fallback if weights sum to zero."""
        seq = list(items)
        if not seq:
            return None
        rand_input = self.next_float()
        total = sum(weight_fn(it) for it in seq)
        if total <= 0:
            return seq[-1]
        cursor = rand_input * total
        for it in seq:
            cursor -= weight_fn(it)
            if cursor <= 0:
                return it
        return seq[-1]


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
        self.seed = seed & MASK32
        self.rngs: dict[str, Rng] = {c: Rng(self.seed, c) for c in categories}

    def __getattr__(self, name: str) -> Rng:
        try:
            return self.rngs[name]
        except KeyError as e:
            raise AttributeError(name) from e

    def snapshot(self) -> dict:
        return {"seed": self.seed, "counters": {k: r.counter for k, r in self.rngs.items()}}

    @classmethod
    def restore(cls, snapshot: dict) -> "_RngSet":
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

# Slay the Spire 2 — PRNG & Seed System (Phase 4 Deep Dive)

*Target framework: .NET 9.0 (Arm64 / x86_64). Key goal: bit-exact Python port for deterministic replay.*

---

## 0. Phase 4 Resolution Update (sprint after the document was first drafted)

**The earlier conclusion in §1.4 that "in .NET 6.0+ System.Random uses xoshiro256\*\*" is incomplete and was misleading the Python port.**

The .NET 6 redesign split `System.Random` into two implementations:

| Constructor | Internal impl | Algorithm |
| :--- | :--- | :--- |
| `new Random()` (seedless) | `XoshiroImpl` | xoshiro256\*\* |
| `new Random(int seed)` (seeded) | `CompatImpl` | **Knuth subtractive 55-element** (the .NET 1.0 algorithm, preserved for backward compatibility) |

The game's `MegaCrit.Sts2.Core.Random.Rng` always goes through `new System.Random((int)seed)` — so the **Knuth subtractive generator** is the one we must port, not xoshiro256\*\*.

The Python port (`sim/rng.py`) now implements `CompatImpl` line-for-line and is checked bit-exact against vectors emitted by a standalone .NET 9 console app at `tools/RngOracle/` (committed JSON at `tools/RngOracle/oracle.json`, regenerable with `dotnet run --project tools/RngOracle/RngOracle.csproj > tools/RngOracle/oracle.json`). The full sweep is in `tests/test_rng_oracle.py` (54 cases, all green).

Critical gotcha during the port: the init loop has lines like `mk = mj - mk` and `_seedArray[i] -= _seedArray[1+n]`. When the seed is near `int.MaxValue` / `int.MinValue` these expressions overflow the 32-bit signed range; C# silently wraps, Python doesn't. The Python port has to clamp each intermediate via `_to_int32(...)` to reproduce the wraparound exactly. Without that, seeds 0..1B happen to work but `int.MaxValue` / `int.MinValue` diverge by ~1 ULP starting at the second or third sample.

The rest of the §1 / §2 / §3 / §5 content below is still useful as field reference (counter semantics, category split, fast-forward) and remains accurate. **Treat §1.4's algorithm claim and §5's xoshiro256\*\* sketch as historical context, not as a port spec.**

---

## 1. PRNG Core Algorithm

### Base Implementation: `System.Random` Wrapper

**Constructor & Seed** (`Rng.cs:18–23`):
```csharp
public Rng(uint seed = 0u, int counter = 0)
{
    Counter = 0;
    Seed = seed;
    _random = new System.Random((int)seed);
    FastForwardCounter(counter);
}
```

- **Input space**: 32-bit unsigned integer (`uint`) seed, optionally narrowed to `(int)seed` when passed to `.NET Random`
- **Seeding chain**: Root seed (string, e.g., `"abc123..."`) is converted via `StringHelper.GetDeterministicHashCode()` to a deterministic `int`; that `int` is cast to `uint`, then used to initialize `System.Random`
- **Counter tracking**: Every call increments `Counter` *before* delegating to `_random`. This allows deterministic fast-forward via `FastForwardCounter(targetCount)` and save/load recovery.

### Output API

All public methods follow the half-open interval pattern (inclusive min, exclusive max):

| Method | Behavior | Counter Impact |
|--------|----------|-----------------|
| `NextInt(max)` | Returns `[0, max)` | +1 |
| `NextInt(min, max)` | Returns `[min, max)` | +1 |
| `NextUnsignedInt(max)` | Returns `[0, max)` | +1 |
| `NextFloat(min, max)` | Returns `[min, max)` floating-point | +1 |
| `NextDouble(min, max)` | Returns `[min, max)` floating-point | +1 |
| `NextBool()` | Returns `_random.Next(2) == 0` | +1 |
| `NextItem<T>(items)` | Uniform sample from collection | +1 (via `NextInt`) |
| `WeightedNextItem<T>()` | Weighted sample (cumulative) | +1 (via `NextFloat`) |
| `Shuffle<T>(list)` | Fisher-Yates (in-place) | +`list.Count - 1` |
| `NextGaussianFloat/Double()` | Box-Muller (rejection sampling) | +1 to +3+ (loop) |

**Key quirk: `NextUnsignedInt` uses `NextDouble()`** (`Rng.cs:77–81`):
```csharp
double num = _random.NextDouble();
double num2 = maxExclusive - minInclusive;
uint num3 = (uint)(num * num2);
return minInclusive + num3;
```
- Susceptible to floating-point precision loss when `num * num2` is large
- **Important for Python port**: Must replicate `.NextDouble()` exactly (see `.NET 9 Random` notes below)

### .NET Random Algorithm (netcoreapp9.0)

In **.NET 6.0+**, `System.Random` switched from the **Knuth subtractive generator** to **xoshiro256\*\*** (64-bit state, 64-bit output).

**Critical facts for bit-exact replay**:
1. **State**: 256 bits (four 64-bit ulong values)
2. **seeding**: `.NET Random(int seed)` initializes state via a deterministic seed derivation (not documented in official specs, but empirically reproducible)
3. **`NextDouble()`**: Returns `(_random.Next() ^ (_random.Next() >> 11)) * (1.0 / 9007199254740992.0)` (52-bit precision, IEEE 754)
4. **No thread safety**: Rng instances are not locked; **no apparent multi-threaded access** in the codebase

### Deterministic Hash Function

**StringHelper.GetDeterministicHashCode** (`StringHelper.cs:71–85`):
```csharp
public static int GetDeterministicHashCode(string str)
{
    int num = 352654597;  // FNV-1a-like offset basis
    int num2 = num;
    for (int i = 0; i < str.Length; i += 2)
    {
        num = ((num << 5) + num) ^ str[i];
        if (i == str.Length - 1)
            break;
        num2 = ((num2 << 5) + num2) ^ str[i + 1];
    }
    return num + num2 * 1566083941;
}
```
- **Not standard `String.GetHashCode()`** (which varies across .NET versions)
- **Deterministic across runs**: Same string always produces same hash
- **Used for**: Category splitting, encounter-per-floor seeding

---

## 2. Seed Split / Category Structure

### Two-Level Hierarchy: PlayerRngSet + RunRngSet

Slay the Spire 2 uses **two independent RNG trees**, one per player (for cosmetic/personal decisions) and one per run (for gameplay-critical randomness).

#### PlayerRngSet (3 categories, player-scoped)

**Structure** (`PlayerRngSet.cs:21–35`):
```csharp
public PlayerRngSet(uint seed)
{
    Seed = seed;
    PlayerRngType[] values = Enum.GetValues<PlayerRngType>();
    foreach (PlayerRngType playerRngType in values)
    {
        _rngs[playerRngType] = CreateRng(playerRngType);
    }
}

private Rng CreateRng(PlayerRngType rngType)
{
    string name = StringHelper.SnakeCase(rngType.ToString());
    return new Rng(Seed, name);
}
```

**Categories** (`PlayerRngType.cs`):

| Enum | SnakeCase Name | Usage |
|------|---|---|
| `Rewards` | `"rewards"` | Reward selection post-combat (relic, card choices) |
| `Shops` | `"shops"` | Shop item generation and pricing (cosmetic?) |
| `Transformations` | `"transformations"` | Deck transformations, cosmetic effects |

**Seeding**: `Seed + hash(category_name)` → new `Rng` instance per category. For a player with seed `0x12345678`:
- `PlayerRng.Rewards = Rng(0x12345678 + hash("rewards"))`
- `PlayerRng.Shops = Rng(0x12345678 + hash("shops"))`
- etc.

#### RunRngSet (12 categories, run-scoped)

**Structure** (`RunRngSet.cs:54–69`):
```csharp
public RunRngSet(string seed)
{
    StringSeed = seed;
    Seed = (uint)StringHelper.GetDeterministicHashCode(seed);
    RunRngType[] values = Enum.GetValues<RunRngType>();
    foreach (RunRngType runRngType in values)
    {
        _rngs[runRngType] = CreateRng(runRngType);
    }
}

private Rng CreateRng(RunRngType rngType)
{
    string name = StringHelper.SnakeCase(rngType.ToString());
    return new Rng(Seed, name);
}
```

**Categories** (`RunRngType.cs`):

| Enum | SnakeCase Name | Purpose / Call Site |
|------|---|---|
| `UpFront` | `"up_front"` | Unknown (likely pre-generation, relics?) |
| `Shuffle` | `"shuffle"` | Card deck shuffling (Fisher-Yates) |
| `UnknownMapPoint` | `"unknown_map_point"` | Map point type distribution, point-by-point room selection |
| `CombatCardGeneration` | `"combat_card_generation"` | Reward cards after combat (pool sampling) |
| `CombatPotionGeneration` | `"combat_potion_generation"` | Potion rewards |
| `CombatCardSelection` | `"combat_card_selection"` | Card choice UI (from pools) |
| `CombatEnergyCosts` | `"combat_energy_costs"` | X-cost card value assignment (e.g., Powers with variable energy) |
| `CombatTargets` | `"combat_targets"` | **Multi-target card targeting** (e.g., BouncingFlask line 43: `NextItem(HittableEnemies)`) |
| `MonsterAi` | `"monster_ai"` | **Monster move selection** (MonsterModel.RollMove → MoveStateMachine.RollMove) |
| `Niche` | `"niche"` | Miscellaneous / specialty cases |
| `CombatOrbs` | `"combat_orbs"` | Relic slot generation (Neon, Turbo) |
| `TreasureRoomRelics` | `"treasure_room_relics"` | Treasure room relic pool sampling |

**Seeding**: `hash(string_seed) + hash(category_name)` → new `Rng` per category.

**Call site examples**:
- **MonsterAi**: `MonsterModel.RollMove()` → `MoveStateMachine.RollMove(targets, owner, RunRng.MonsterAi)` (03_system_mapping.md:164)
- **CombatTargets**: `CardCmd.AutoPlay()` → auto-targeting multi-target cards (CardCmd.cs:55–78, BouncingFlask.cs:43)

---

## 3. Counter-Based Determinism & Save/Load

### Persistence via Counter Tracking

The core trick: **each `Rng` instance holds a `Counter`** (call count), and save files store the counter for each category RNG.

**PlayerRngSet serialization** (`PlayerRngSet.cs:37–48`):
```csharp
public SerializablePlayerRngSet ToSerializable()
{
    SerializablePlayerRngSet serializablePlayerRngSet = new SerializablePlayerRngSet
    {
        Seed = Seed
    };
    foreach (var (key, rng2) in _rngs)
    {
        serializablePlayerRngSet.Counters[key] = rng2.Counter;
    }
    return serializablePlayerRngSet;
}
```

**Deserialization (FromSerializable)** (`PlayerRngSet.cs:50–63`):
```csharp
public static PlayerRngSet FromSerializable(SerializablePlayerRngSet save)
{
    PlayerRngSet playerRngSet = new PlayerRngSet(save.Seed);
    foreach (KeyValuePair<PlayerRngType, int> counter in save.Counters)
    {
        // Destructure (key, value)
        PlayerRngType playerRngType = key;
        int targetCount = value;
        Rng rng = playerRngSet.CreateRng(playerRngType);
        rng.FastForwardCounter(targetCount);  // Advance counter without using RNG
        playerRngSet._rngs[playerRngType] = rng;
    }
    return playerRngSet;
}
```

**How it works**:
1. **Save**: Game captures `Seed` + `{PlayerRngType → Counter}` map
2. **Load**: Recreate fresh RngSet with same seed, then "fast-forward" each category RNG to the saved counter
3. **Fast-forward** (`Rng.cs:31–42`): Calls `_random.Next()` repeatedly *without consuming* the counter, advancing the internal state:
   ```csharp
   public void FastForwardCounter(int targetCount)
   {
       if (Counter > targetCount)
           throw new InvalidOperationException(...);
       while (Counter < targetCount)
       {
           Counter++;
           _random.Next();
       }
   }
   ```

**Runnable example**: If player saved at counter=100 for Rewards RNG:
1. Create new `PlayerRngSet(seed)` → `Rewards` RNG at counter=0
2. Call `FastForwardCounter(100)` → calls `.Next()` 100 times, counter now = 100
3. Next `.NextInt()` call will return the same value as it did in the original game at that point

### Serializable* Classes

- **SerializablePlayerRngSet** (`SerializablePlayerRngSet.cs`): Holds `uint Seed` + `Dict<PlayerRngType, int> Counters`
- **SerializableRunRngSet** (`SerializableRunRngSet.cs`): Holds `string Seed` + `Dict<RunRngType, int> Counters`

Both implement `IPacketSerializable` for JSON and multiplayer packet encoding.

---

## 4. TestRngInjector — Test Support

**What it does** (`TestRngInjector.cs`):

```csharp
public static class TestRngInjector
{
    private static RelicModel? _relicOverride;
    private static RelicRarity? _relicRarityOverride;
    private static Action<List<CardModel>>? _initialShuffleOverride;
    private static List<CardModel>? _combatCardGenerationOverride;
    
    public static void SetRelicOverride<T>() where T : RelicModel { ... }
    public static RelicModel? ConsumeRelicOverride() { ... }
    public static void SetRelicRarityOverride(RelicRarity relicRarity) { ... }
    public static void SetCombatCardGenerationOverride(List<CardModel> cards) { ... }
    public static void SetInitialShuffleOverride(Action<List<CardModel>> reorder) { ... }
    public static void Cleanup() { ... }
}
```

**Design**: Provides **override hooks** for specific RNG-driven events in tests (relic picks, card generation, shuffle). NOT a full RNG injection API, but enough to:
- Force specific relics to be selected (bypasses `PlayerRng.Rewards`)
- Override combat card generation (replaces `RunRng.CombatCardGeneration`)
- Inject a custom shuffle callback (replaces `RunRng.Shuffle` Fisher-Yates)

**Limitation**: No way to directly inject a seed or fixed RNG stream. The hooks are **one-time overrides** per event, consumed after use (`Consume*` methods).

**For Phase 7 verification**: This is a lightweight, game-aware tool. However, **for a Python simulator**, you'll need a full counter-based replay log, not just override hooks.

---

## 5. Python Port Plan

### Pseudocode: .NET xoshiro256\*\* in Python

**Target**: Replicate `System.Random` from .NET 9.0 (xoshiro256\*\*).

```python
class DotNetRandom:
    """
    Mimics System.Random (xoshiro256**) seeding and output.
    """
    
    def __init__(self, seed: int):
        # .NET seeds via a deterministic derivation (exact formula undocumented).
        # Empirically: takes seed as int, produces four 64-bit state values.
        # For bit-exact replay, may need to extract or instrument the real game
        # to dump state after initialization.
        self.state = self._initialize_state(seed)
    
    def _initialize_state(self, seed: int) -> tuple[int, int, int, int]:
        """
        Initialize xoshiro256** state from int seed.
        NOTE: .NET's seeding formula is NOT public. Options:
        1. Reverse-engineer from game output (test vectors)
        2. Call into .NET via ctypes/P/Invoke
        3. Assume simple hash-based expansion (risky)
        """
        # Placeholder: expand single seed to 4 x uint64
        s = seed & 0xFFFFFFFF
        # Simple LCG expansion (NOT official .NET):
        s1 = (s * 1664525 + 1013904223) & 0xFFFFFFFFFFFFFFFF
        s2 = (s1 * 1664525 + 1013904223) & 0xFFFFFFFFFFFFFFFF
        s3 = (s2 * 1664525 + 1013904223) & 0xFFFFFFFFFFFFFFFF
        s4 = (s3 * 1664525 + 1013904223) & 0xFFFFFFFFFFFFFFFF
        return (s1, s2, s3, s4)
    
    def next_int(self, max_exclusive: int) -> int:
        """Equiv: _random.Next(max_exclusive)"""
        val = self.next_int_internal()
        return (val % max_exclusive) if max_exclusive > 0 else 0
    
    def next_int_internal(self) -> int:
        """Returns next 32-bit int from xoshiro256**"""
        s0, s1, s2, s3 = self.state
        result = ((s1 * 5) << 7) | ((s1 * 5) >> 57)  # xoshiro256** output function
        t = s1 << 17
        s2 ^= s0
        s3 ^= s1
        s1 ^= s2
        s0 ^= s3
        s2 ^= t
        s3 = ((s3 << 45) | (s3 >> 19)) & 0xFFFFFFFFFFFFFFFF
        self.state = (s0, s1, s2, s3)
        return result & 0xFFFFFFFFFFFFFFFF
    
    def next_double(self) -> float:
        """
        Returns [0.0, 1.0) as a double.
        .NET formula: ((next_int() ^ (next_int() >> 11)) * (1.0 / 9007199254740992.0))
        """
        a = self.next_int_internal() & 0xFFFFFFFFFFFFFFFF
        b = self.next_int_internal() & 0xFFFFFFFFFFFFFFFF
        combined = (a ^ (b >> 11)) & 0xFFFFFFFFFFFFFFF  # 52-bit precision
        return combined * (1.0 / 9007199254740992.0)
```

### Deterministic Hash Function (Python)

```python
def get_deterministic_hash_code(s: str) -> int:
    """
    Replicates StringHelper.GetDeterministicHashCode.
    Returns signed 32-bit int.
    """
    num = 352654597
    num2 = num
    for i in range(0, len(s), 2):
        num = ((num << 5) + num) ^ ord(s[i])
        if i == len(s) - 1:
            break
        num2 = ((num2 << 5) + num2) ^ ord(s[i + 1])
    
    result = num + num2 * 1566083941
    # Convert to signed 32-bit
    if result >= 2**31:
        result -= 2**32
    return result
```

### Full Rng Class

```python
class Rng:
    def __init__(self, seed: int, name: str = "", counter: int = 0):
        if name:
            seed_hash = get_deterministic_hash_code(name)
            seed = (seed + seed_hash) & 0xFFFFFFFF
        
        self.seed = seed
        self.counter = 0
        self._random = DotNetRandom(seed)
        self.fast_forward_counter(counter)
    
    def fast_forward_counter(self, target_count: int):
        if self.counter > target_count:
            raise ValueError(f"Cannot fast-forward to {target_count} (current {self.counter})")
        while self.counter < target_count:
            self.counter += 1
            self._random.next_int(int(2**31))  # Burn a call
    
    def next_int(self, min_inclusive: int = 0, max_exclusive: int = 2**31) -> int:
        self.counter += 1
        if min_inclusive == 0:
            return self._random.next_int(max_exclusive)
        else:
            return min_inclusive + self._random.next_int(max_exclusive - min_inclusive)
    
    def next_float(self, min_val: float = 0.0, max_val: float = 1.0) -> float:
        self.counter += 1
        return self._random.next_double() * (max_val - min_val) + min_val
    
    def next_item(self, items: list):
        if not items:
            return None
        idx = self.next_int(0, len(items))
        return items[idx]
```

### PlayerRngSet / RunRngSet (Python)

```python
class PlayerRngSet:
    def __init__(self, seed: int):
        self.seed = seed
        self.rngs = {
            "rewards": Rng(seed, "rewards"),
            "shops": Rng(seed, "shops"),
            "transformations": Rng(seed, "transformations"),
        }
    
    def to_serializable(self):
        return {
            "seed": self.seed,
            "counters": {k: rng.counter for k, rng in self.rngs.items()},
        }
    
    @staticmethod
    def from_serializable(data):
        prs = PlayerRngSet(data["seed"])
        for rng_type, target_counter in data["counters"].items():
            prs.rngs[rng_type].fast_forward_counter(target_counter)
        return prs

class RunRngSet:
    def __init__(self, string_seed: str):
        self.string_seed = string_seed
        seed = get_deterministic_hash_code(string_seed) & 0xFFFFFFFF
        self.seed = seed
        self.rngs = {
            "up_front": Rng(seed, "up_front"),
            "shuffle": Rng(seed, "shuffle"),
            "unknown_map_point": Rng(seed, "unknown_map_point"),
            "combat_card_generation": Rng(seed, "combat_card_generation"),
            # ... etc
        }
    
    def to_serializable(self):
        return {
            "seed": self.string_seed,
            "counters": {k: rng.counter for k, rng in self.rngs.items()},
        }
    
    @staticmethod
    def from_serializable(data):
        rrs = RunRngSet(data["seed"])
        for rng_type, target_counter in data["counters"].items():
            rrs.rngs[rng_type].fast_forward_counter(target_counter)
        return rrs
```

### Key Challenges

1. **.NET xoshiro256\*\* seeding**: The exact seed-to-state transformation is undocumented. **Must**:
   - Extract test vectors from the real game (dump state after seeding)
   - OR reverse-engineer via black-box testing (run known seed, capture outputs)
   - OR use P/Invoke to call .NET Random directly in tests

2. **Floating-point precision**: `.NextDouble()` in .NET uses full 64-bit floating-point precision. Python's `float` is IEEE 754 double, so should match—but test explicitly.

3. **32-bit seed overflow**: `new System.Random((int)seed)` casts `uint` to `int`. If `uint > INT_MAX`, it wraps. **Python must replicate this**:
   ```python
   seed_as_int = seed if seed < 2**31 else seed - 2**32
   ```

---

## 6. Open Risks & Floating-Point Concerns

### 1. Floating-Point Determinism

**Risk**: `NextDouble()` output fed into `NextUnsignedInt` calculations is floating-point, subject to rounding.

**Example** (`Rng.cs:77–81`):
```csharp
double num = _random.NextDouble();           // [0.0, 1.0)
double num2 = maxExclusive - minInclusive;   // Integer arithmetic
uint num3 = (uint)(num * num2);              // TRUNCATES, not rounds
return minInclusive + num3;
```

**Severity**: HIGH for Python port. IEEE 754 `double` should be deterministic across .NET and CPython, but:
- Compiler optimizations (x87 vs SSE) can affect intermediate precision
- FMA (fused multiply-add) can change results
- **Mitigation**: Test `NextUnsignedInt` output against known game values

### 2. Locale-Dependent Calls

**Risk**: None found in Rng class itself. `StringHelper.GetDeterministicHashCode` uses `string[i]` indexing (char ordinal), locale-independent.

However, `StringHelper.Radix()` uses `CultureInfo` for number formatting—but this is UI-only, not RNG-touching.

**Verdict**: Safe.

### 3. Multi-Threading

**Risk**: Very low. Rng instances are created per player/run and held in singleton containers (`RunState.Rng`, `Player.PlayerRng`). No locking, no concurrent access observed in codebase.

**BUT**: CombatManager and related systems use `async/await`. If an RNG is awaited across yields, state is **not thread-safe**. However, each `Rng` is owned by a single logical player/run, and STS2's event loop is single-threaded (Godot C# architecture).

**Verdict**: Safe for single-threaded event loop. Verify during Python RL integration.

### 4. xoshiro256\*\* State Leakage

**Risk**: Extracting or dumping internal `_random` state is not exposed in public API. If needed for debugging, would require reflection or external instrumentation.

**Mitigation**: For Python port, use counter-based replay (log each RNG call index), not state dumps.

### 5. Gaussian Methods (Rejection Sampling)

**Methods**: `NextGaussianFloat`, `NextGaussianInt` use **Box-Muller + rejection sampling**.

**Risk**: Counter increments by 1 even if loop retries. Example (`Rng.cs:115–139`):
```csharp
public double NextGaussianDouble(...)
{
    Counter++;  // <-- ONLY INCREMENTS ONCE, NOT PER LOOP ITERATION
    do {
        double d = _random.NextDouble();     // Consumes RNG state
        double num = _random.NextDouble();   // Consumes RNG state
        ...
    } while ((num4 < 0.0 || num4 > 1.0));
    return num4 * (max - min) + min;
}
```

**Consequence**: Counter does NOT track actual `NextDouble` calls consumed (can be 2, 4, 6, ... per invocation). **Save/load via counter alone is insufficient for runs using Gaussian RNG heavily.**

**Mitigation**: Check which cards/powers use `NextGaussianFloat/Int`. If rare or cosmetic-only, may be acceptable. If gameplay-critical (e.g., monster move damage variance), **must log Gaussian calls separately or instrument the counter**.

---

## 7. Phase-4 Readiness Checklist

Before writing the Python port, confirm:

- [ ] **Extract .NET xoshiro256\*\* test vectors**: Seed known integers (0, 1, 42, 0xDEADBEEF) in the game, capture first 100 `NextDouble()` values. Verify Python port matches exactly.

- [ ] **Trace one complete gameplay sequence**: Pick a simple combat (e.g., Gremlin vs. Ironclad, fixed deck). Log every RNG call by category (counter snapshots at each call site). Verify save/load restores identical sequence.

- [ ] **Verify deterministic hash**: Compute `GetDeterministicHashCode("test_string")` in both C# and Python. Must match exactly for seed splitting to work.

- [ ] **Assess Gaussian usage**: Search codebase for `NextGaussianFloat/Int` calls. If any are in core combat (damage rolls, power applications), note as a **REPLAY RISK** and plan instrumentation.

- [ ] **Test floating-point conversions**: Create Python tests that compare `NextUnsignedInt(uint.MaxValue)` output across seeded runs. Verify no precision loss in `(double) * uint` operations.

- [ ] **Document seed-to-state derivation**: Either reverse-engineer the exact .NET xoshiro256\*\* seeding formula, or establish a test oracle (game + instrumentation) to verify Python state initialization.

- [ ] **Plan counter overflow**: Verify integer counter never exceeds `int.MaxValue` in typical gameplay. If it does, plan how Python port handles `Counter` storage (int vs long).

- [ ] **Audit async/await interaction**: Confirm no RNG is captured and awaited across `.ConfigureAwait(false)` or multi-threaded boundaries. Single-threaded event loop must be enforced.

---

## Appendix: Example Seed Derivation Chain

**Scenario**: New run starts with seed string `"abc123"`.

1. **Run initialization**: `RunState.CreateForNewRun(..., seed="abc123")`
2. **RunRngSet creation**: `new RunRngSet("abc123")`
   - `Seed = (uint) GetDeterministicHashCode("abc123")` → e.g., `0x3F5A8C12`
3. **Category RNG instantiation** (e.g., MonsterAi):
   - `CreateRng(RunRngType.MonsterAi)`
   - Name → `"monster_ai"`
   - Hash → `GetDeterministicHashCode("monster_ai")` → e.g., `0x1A2B3C4D`
   - Combined seed → `0x3F5A8C12 + 0x1A2B3C4D = 0x59860D5F`
   - Create: `new Rng(0x59860D5F)`
   - Internally: `new System.Random((int)0x59860D5F)` → xoshiro256\*\* initialized
4. **First monster move roll**: Call `RunRng.MonsterAi.NextInt(moveCount)` → Counter becomes 1
5. **Save game**: Capture `Counters[RunRngType.MonsterAi] = 1`
6. **Load game**: Recreate `RunRng.MonsterAi`, fast-forward to counter=1 (consumes seed state idempotently)
7. **Resume**: Next `.NextInt(...)` call returns the same value as original playthrough

---

**Document version**: 2026-05-23  
**Codebase**: Slay the Spire 2 (decompiled, .NET 9.0, Godot C#)  
**Target Python version**: 3.10+


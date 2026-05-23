# STS2 Map Generation — Spec for sim/map_gen.py

Source: `decompiled/MegaCrit.Sts2.Core.Map/StandardActMap.cs` + related.
Verified by Phase-A1 agent sweep 2026-05-24.

---

## 1. Entry Point

`StandardActMap.CreateFor(runState, replaceTreasureWithElites)` (line 94–97).

Call chain:
1. `RunManager.GenerateMap()` (line 549) → `State.Act.CreateMap(...)`.
2. `ActModel.CreateMap()` (line 411) → `StandardActMap.CreateFor(...)`.
3. Constructor: `StandardActMap(Rng mapRng, ActModel actModel, bool isMultiplayer, bool shouldReplaceTreasureWithElites, bool hasSecondBoss=false, MapPointTypeCounts? override=null, bool enablePruning=true)`.

**Alternative map types** (triggered by Relic/Card effects, lower priority for port):
- `SpoilsActMap` (SpoilsMap card)
- `GoldenPathActMap` (GoldenCompass relic, linear)
- `SavedActMap` (deserialize)

## 2. Grid

- **Width**: 7 columns, fixed.
- **Height**: `actModel.GetNumberOfRooms(isMultiplayer) + 1` rows.

Room counts per act (`ActModel.GenerateRooms`):

| Act | Base rooms (`GenerateRooms` loop) | Total rows (incl. boss + ancient) |
|---|---|---|
| Underdocks (Act 1 alt) | 15 | 17 |
| Hive (Act 2) | 14 | 16 |
| Glory (Act 3) | 13 | 15 |
| Overgrowth (Act 1) | 15 | 17 |

Multiplayer: BaseNumberOfRooms - 1 (ActModel.cs:180).

## 3. RNG

**Map-only RNG**: `new Rng(runState.Rng.Seed, $"act_{runState.CurrentActIndex + 1}_map")` (StandardActMap.cs:95). Isolated per act, name-hashed seed. Not from `RunRngSet` categories — independent stream.

## 4. Tree Structure & Path Generation

- **Start node**: (col=3, row=0) — Ancient.
- **Floor 1 (row=1)**: 7 independent starting nodes, each column independently `rng.NextInt(0, 7)` (line 193). Constraint: at least 2 unique start columns (line 195–200).
- **Floors 2 to N-1**: paths interweave via `GenerateNextCoord()` that picks lateral offset ∈ {-1, 0, +1}.
- **Crossover validation** (line 166–187 `HasInvalidCrossover()`): paths cannot cross.
- **Final row N**: All nodes converge to boss at (col=3, row=N).
- **Optional second boss** (`actModel.HasSecondBoss`): (col=3, row=N+1) linked from primary boss.

## 5. Room Type Assignment

Order in `StandardActMap` (lines 230–289):

**Fixed assignments** (cannot be modified):
- Row 0: `Ancient`.
- Row 1: all `Monster` (line 253–257).
- Row N-1 (penultimate): all `RestSite` (line 231–236).
- Row N-7 (treasure row): `Treasure` or `Elite` per `ShouldReplaceTreasureWithElites` (lines 237–252). Single column wide.
- Row N: `Boss`.

**Dynamic assignments**: counts come from `MapPointTypeCounts` produced by `ActModel.GetMapPointTypes(mapRng)`:

| Act | Unknown count | Rest count | Elite base | Shop |
|---|---|---|---|---|
| Underdocks | `Gaussian(12, σ=1, [10,14])` | `Gaussian(7, σ=1, [6,7])` | 8 (×1.6 if A1 SwarmingElites) | fixed 3 |
| Hive | `Gaussian(12, σ=1, [10,14]) - 1` | `Gaussian(6, σ=1, [6,7])` | 8 (×1.6 if A1) | 3 |
| Glory | `Gaussian(12, σ=1, [10,14]) - 1` | `Uniform(5, 7)` | 8 (×1.6 if A1) | 3 |
| Overgrowth | `Gaussian(12, σ=1, [10,14])` | `Gaussian(7, σ=1, [6,7])` | 8 (×1.6 if A1) | 3 |

Algorithm:
1. Build a queue of types {`NumOfRests` × RestSite, `NumOfShops` × Shop, `NumOfElites` × Elite, `NumOfUnknowns` × Unknown}.
2. Shuffle the remaining unassigned (Monster-default) nodes.
3. Assign via `GetNextValidPointType()` respecting `IsValidPointType` constraints:
   - **Lower** (row < 6): no Elite/Rest.
   - **Upper** (row ≥ N-2): no Rest.
   - **With parents**: no Elite/Rest/Treasure/Shop same as ancestor chain.
   - **With children**: same constraint on descendant.
   - **With siblings** (Rest/Monster/Unknown/Elite/Shop): no same-type on parallel paths.
4. Loop up to 3 times with `AssignRemainingTypesToRandomPoints()`.
5. Unassigned remainders become `Monster`.

## 6. Post-Processing (line 84–91)

1. **Pruning & Repair** (`MapPathPruning.PruneAndRepair`, 3 iterations): remove duplicate path segments, re-assign pruned types.
2. **Center Grid**: shift columns left/right.
3. **Spread Adjacent**: avoid node overlap.
4. **Straighten Paths**: clean up linear intermediate nodes.

## 7. Special Cases

- **Neow skip** (RunManager.cs:553): `if !State.ExtraFields.StartedWithNeow && State.CurrentActIndex == 0`, starting point type changes from `Ancient` to `Monster`.
- **Tutorial discovery order** (first run): `ActModel.ApplyActDiscoveryOrderModifications` forces specific encounters into normal/elite slots — see notes/09_encounters.md §4.

## 8. Python Port Plan (sim/map_gen.py)

Module layout:
```
sim/map_gen.py
  RoomType enum (Ancient, Monster, Elite, RestSite, Shop, Treasure, Unknown, Boss)
  MapPoint dataclass(col, row, room_type, parents=[], children=[])
  MapPointTypeCounts dataclass(num_rests, num_shops, num_elites, num_unknowns)
  StandardActMap class
    .generate(rng: Rng, act: ActSpec, is_multiplayer=False,
              replace_treasure_with_elites=False, has_second_boss=False)
    -> RunMap
```

Required Rng methods (extension to `sim.rng.Rng`):
- `next_int(0, 7)` ✓ already exists
- `next_bool()` — add: `next_max(2) == 0`
- `shuffle(list)` — add: Fisher-Yates in-place
- `next_gaussian_int(mean, std, min, max)` — Box-Muller with rejection
- `next_item(list)` ✓
- `weighted_next_item(items, weight_fn)` — cumulative

Validation: same seed → identical map. Eventually test against in-game maps via STS2_MCP `state.map.options` (notes/06_mcp_api.md §2.5).

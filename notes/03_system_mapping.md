# Slay the Spire 2 — Core Subsystem Mapping

*Generated from decompiled C# source (MegaCrit.Sts2.Core.* namespaces). Target: five critical game subsystems for Phase 3 RL agent integration.*

---

## 1. PRNG / Seed Management

### Key Classes

| Class | File | Purpose |
|-------|------|---------|
| `Rng` | `/MegaCrit.Sts2.Core.Random/Rng.cs` | Wraps `.NET Random` with counter tracking; base RNG for all randomization |
| `PlayerRngSet` | `/MegaCrit.Sts2.Core.Random/PlayerRngSet.cs` | Splits a single seed across player-category RNGs (Rewards, Shops, Transformations) |
| `RunRngType` (enum) | `/MegaCrit.Sts2.Core.Entities.Rngs/RunRngType.cs` | 12 run-level RNG categories: MonsterAi, CombatTargets, CombatCardGeneration, etc. |

### Algorithm & API

- **Engine**: Wraps .NET `System.Random` (line 10: `private readonly System.Random _random`)
- **Seeding**: Single `uint` seed passed to constructor; transformed via `StringHelper.GetDeterministicHashCode(name)` for category splitting (PlayerRngSet:27-34)
- **Counter**: Incremented on every call (`Counter++` before each `.Next()` call); allows deterministic replay via `FastForwardCounter(targetCount)`
- **Key Methods**:
  ```csharp
  public int NextInt(int minInclusive, int maxExclusive)
  public uint NextUnsignedInt(uint minInclusive, uint maxExclusive)
  public float NextFloat(float min, float max)
  public T? NextItem<T>(IEnumerable<T> items)  // samples from list
  public T WeightedNextItem<T>(float randInput, IEnumerable<T> items, Func<T, float> weightFetcher, T fallback)
  ```

### Run-Level Seeding Structure

- **PlayerRngSet**: 3 categories via enum (Rewards, Shops, Transformations)
- **RunRngSet** (via enum RunRngType): 12 categories, all seeded from `RunState.Rng.Seed` + category name hash
  - `MonsterAi` → controls monster move selection
  - `CombatTargets` → controls target selection for attacks
  - `CombatCardGeneration` → card rewards from combat
  - (others: Shuffle, UnknownMapPoint, CardSelection, EnergyCosts, Orbs, Potions, etc.)

---

## 2. Combat State Machine & Turn Lifecycle

### Key Classes

| Class | File | Purpose |
|-------|------|---------|
| `CombatManager` | `/MegaCrit.Sts2.Core.Combat/CombatManager.cs` | Singleton orchestrating turn flow; entry point for combat state transitions |
| `CombatState` | `/MegaCrit.Sts2.Core.Combat/CombatState.cs` | Immutable snapshot of creature list, modifiers, round number, and current side (Player/Enemy) |
| `CombatStateTracker` | `/MegaCrit.Sts2.Core.Combat/CombatStateTracker.cs` | Subscribes to combat history and creature changes; triggers UI updates |

### Turn Lifecycle & Key Entry Points

```
StartTurn() → SetupPlayerTurn() → [PlayPhase] → SetReadyToEndTurn()
    ↓
AfterAllPlayersReadyToEndTurn() → EndPlayerTurnPhaseOne() → Hook.BeforeTurnEnd()
    ↓
EndPlayerTurnPhaseTwo() → SwitchFromPlayerToEnemySide()
    ↓
[Enemy performs moves via PerformMove()] → EndEnemyTurn()
    ↓
SwitchSides() → [next round]
```

**Critical Methods** (CombatManager):
- `StartTurn()` (line 246): Async; starts either player or enemy turn depending on `CurrentSide`
- `SetupPlayerTurn(Player, PlayerChoiceContext)` (line 420): Draws 5 cards, sets up hand, fires `BeforePlayPhaseStart` hook
- `SetReadyToEndTurn(Player, bool, Func<Task>?)` (line 469): Marks player as ready; if all ready → triggers `AfterAllPlayersReadyToEndTurn()`
- `AfterAllPlayersReadyToEndTurn()` (line 801): **Phase 1 end** → clears play phase flag, fires hooks, waits for queue
- `EndPlayerTurnPhaseOneInternal()` (line 836): Runs turn-end card effects (Ethereal/TurnEndInHand)
- `EndPlayerTurnPhaseTwoInternal()` (line 948): **Phase 2 end** → handles Retain, flushes remaining hand cards to discard
- `SwitchFromPlayerToEnemySide()` (line 989): Calls `creature.Monster.RollMove()` on each enemy (line 598)
- `EndEnemyTurn()` (line 557): Calls `EndEnemyTurnInternal()`, then `StartTurn()` for next round

**One-Turn Execution Hook** (for external bot):
- **`RollMove(IEnumerable<Creature> targets)`** in MonsterModel (line 598 in CombatManager → calls `creature.Monster.RollMove()`)
  - Chains to `MonsterMoveStateMachine.RollMove()` which deterministically selects the next move
  - Then **`PerformMove()`** (MonsterModel:359) executes that move asynchronously
- **For player input**: `CardCmd.AutoPlay()` (line 33–100) is the primary action dispatcher:
  - Checks playability, targets, energy costs
  - Enqueues card to play pile
  - Fires `OnEnqueuePlayVfx()` and waits for visual effects

**Core State Property** (CombatState):
```csharp
public int RoundNumber { get; set; }
public CombatSide CurrentSide { get; set; }  // Player or Enemy
public IReadOnlyList<Creature> Allies { get; }
public IReadOnlyList<Creature> Enemies { get; }
```

---

## 3. Card Effects & Dispatch

### Key Classes

| Class | File | Purpose |
|-------|------|---------|
| `CardModel` | `/MegaCrit.Sts2.Core.Models/CardModel.cs` | Abstract base for all cards; holds cost, keywords, upgrades, target type |
| `CardCmd` | `/MegaCrit.Sts2.Core.Commands/CardCmd.cs` | Static dispatcher for card actions (Play, Exhaust, Discard, etc.) |
| `PlayCardAction` | `/MegaCrit.Sts2.Core.GameActions/PlayCardAction.cs` | Game action wrapping a single card play (for replay/multiplayer serialization) |

### Effect Architecture

**CardModel** (abstract):
- Properties:
  - `public int EnergyCost` → cost to play (X-cost cards set `CapturedXValue`)
  - `public TargetType TargetType` → None, AnyEnemy, AnyAlly
  - `public CardKeyword Keywords` → Unplayable, Ethereal, Retain, etc.
  - `public virtual int MaxUpgradeLevel => 1` → upgrade cap
  - `public int CurrentUpgradeLevel` → current upgrade state
- **No explicit `Execute()` or `Use()` method on CardModel**; effects are encoded in:
  - Subclass implementations (e.g., individual card classes under `MegaCrit.Sts2.Core.Models.Cards/`)
  - **Hook system** (e.g., `Hook.ShouldPlay()`, `BeforePlayPhaseStart`)

**Dispatch Flow** (CardCmd.AutoPlay):
1. Check `Hook.ShouldPlay(combatState, card, out AbstractModel preventer, type)` (line 45)
2. If blocked, call `MoveToResultPileWithoutPlaying()` and return
3. Validate target (line 55–78): if TargetType is AnyEnemy/AnyAlly and target is null, auto-select via `Rng.CombatTargets.NextItem()`
4. Capture X-cost/Star cost (line 81–92)
5. Add card to Play pile via `CardPileCmd.Add(card, PileType.Play)` (line 95)
6. Fire `card.OnEnqueuePlayVfx(target)` for visuals (line 99)
7. *Actual effect execution is likely in individual card subclass overrides or hooks*

**PlayCardAction.ExecuteAction()** (line 58):
```csharp
_card = NetCombatCard.ToCardModel();
NCardPlayQueue.Instance?.UpdateCardBeforeExecution(this);
Creature target = await Player.Creature.CombatState.GetCreatureAsync(TargetId, 10.0);
// [... validation, targeting, effect execution]
```

**Keyword System**:
- `CardKeyword enum` includes: Unplayable, Ethereal, Retain, Sly, etc.
- Ethereal cards are exhausted at turn end if not played (CombatManager line 898)
- Retain cards are kept in hand (line 966)

### Card Pile Management

- Piles: Hand, Draw, Discard, Exhaust, Play, Reward (CardPile type enum)
- Tied to player via `CardPile.Cards` (IReadOnlyList<CardModel>)

---

## 4. Monster AI & Intent System

### Key Classes

| Class | File | Purpose |
|-------|------|---------|
| `MonsterModel` | `/MegaCrit.Sts2.Core.Models/MonsterModel.cs` | Abstract base for monsters; holds HP, powers, and move state machine |
| `MonsterMoveStateMachine` | `/MegaCrit.Sts2.Core.MonsterMoves.MonsterMoveStateMachine/MonsterMoveStateMachine.cs` | Deterministic state machine rolling moves based on RNG and creature targets |
| `MoveState` | `/MegaCrit.Sts2.Core.MonsterMoves.MonsterMoveStateMachine/MoveState.cs` | Leaf node in state tree; contains `Intents` and async `PerformMove()` method |
| `AbstractIntent` | `/MegaCrit.Sts2.Core.MonsterMoves.Intents/AbstractIntent.cs` | Base class for intent types (AttackIntent, DefendIntent, BuffIntent, DebuffIntent, SummonIntent, etc.) |

### AI Decision Flow

**Rolling a Move** (MonsterModel line 340–343):
```csharp
public void RollMove(IEnumerable<Creature> targets)
{
    NextMove = MoveStateMachine.RollMove(targets, Creature, RunRng.MonsterAi);
}
```

- Calls `MonsterMoveStateMachine.RollMove()` with **targets**, **owner** (the monster creature), and **RNG** (`RunRng.MonsterAi`)
- State machine follows conditional/random branches to select next move (MonsterMoveStateMachine line 34–42)

**MonsterMoveStateMachine Logic** (line 34–80):
```csharp
public MoveState RollMove(IEnumerable<Creature> targets, Creature owner, Rng rng)
{
    FindNextMoveState(targets, owner, rng, logMove: true);
    if (!_currentState.IsMove) throw...
    return (MoveState)_currentState;
}

private void FindNextMoveState(...)
{
    // Traverse state tree (conditional/random branches) until reaching a MoveState
    do {
        string nextState = _currentState.GetNextState(owner, rng);
        SetCurrentState(nextState ? States[nextState] : _initialState);
        // Checks CanTransitionAway and MustPerformOnceBeforeTransitioning
    } while (!_currentState.IsMove);
}
```

**Move Execution** (MonsterModel line 359–378):
```csharp
public async Task PerformMove()
{
    // ... setup, await timers ...
    MoveState move = NextMove;
    IReadOnlyList<Creature> targets = combatState.PlayerCreatures;
    await move.PerformMove(targets);  // Executes intents
    MoveStateMachine?.OnMovePerformed(move);
    // ... cleanup, death handling ...
}
```

**MoveState.PerformMove()** (line 55–60):
```csharp
public async Task PerformMove(IEnumerable<Creature> targets)
{
    _performedAtLeastOnce = true;
    Creature[] arg = targets.ToArray();
    await _onPerform(arg);  // Calls the lambda/action bound to this state
}
```

**Intent System** (AbstractIntent & subclasses):
- Each MoveState holds `IReadOnlyList<AbstractIntent> Intents`
- Intents provide:
  - `IntentType` enum (Attack, Defend, Buff, Debuff, Summon, Sleep, Stun, etc.)
  - `GetIntentLabel()` → localized text for UI
  - `GetTexture()` & `GetAnimation()` → visuals
- Intents are **not executable objects**; they describe what the move will do (used for player previews)
- Actual effect execution is in the `_onPerform` lambda bound to MoveState

**Intent Types** (from `/MegaCrit.Sts2.Core.MonsterMoves.Intents`):
- AttackIntent, SingleAttackIntent, MultiAttackIntent
- DefendIntent
- BuffIntent, DebuffIntent
- StatusIntent
- SummonIntent
- StunIntent, SleepIntent
- HealIntent, EscapeIntent, CardDebuffIntent, DeathBlowIntent
- HiddenIntent, UnknownIntent

---

## 5. Map & Encounter Generation

### Key Classes

| Class | File | Purpose |
|-------|------|---------|
| `StandardActMap` | `/MegaCrit.Sts2.Core.Map/StandardActMap.cs` | Procedurally generates a 7-wide × (rooms+1)-tall map for an Act |
| `ActModel` | `/MegaCrit.Sts2.Core.Models/ActModel.cs` | Abstract base defining room pools, map styling, and encounter selection |
| `EncounterModel` | `/MegaCrit.Sts2.Core.Models/EncounterModel.cs` | Abstract base for individual encounters; generates monsters on demand |
| `MapPoint` | `/MegaCrit.Sts2.Core.Map/MapPoint.cs` | Single grid cell; holds `MapPointType` and a reference encounter |

### Map Generation (Act 1 Example)

**Entry Point** (StandardActMap):
```csharp
public StandardActMap(Rng mapRng, ActModel actModel, bool isMultiplayer, 
                      bool shouldReplaceTreasureWithElites, bool hasSecondBoss = false, ...)
{
    _mapLength = actModel.GetNumberOfRooms(isMultiplayer) + 1;
    Grid = new MapPoint[7, _mapLength];  // 7 columns, (rooms + 1) rows
    
    GenerateMap();          // Fill grid with MapPoints (connectivity)
    AssignPointTypes();     // Assign type (Monster, Elite, Boss, etc.)
    MapPathPruning.PruneAndRepair(...);  // Trim invalid paths
    Grid = MapPostProcessing.CenterGrid(Grid);
    Grid = MapPostProcessing.SpreadAdjacentMapPoints(Grid);
    Grid = MapPostProcessing.StraightenPaths(Grid);
}

public static StandardActMap CreateFor(RunState runState, bool replaceTreasureWithElites)
{
    return new StandardActMap(
        new Rng(runState.Rng.Seed, $"act_{runState.CurrentActIndex + 1}_map"),
        runState.Act,
        runState.Players.Count > 1,
        replaceTreasureWithElites,
        runState.Act.HasSecondBoss
    );
}
```

**Map Structure**:
- **Width**: 7 columns (fixed)
- **Height**: `actModel.GetNumberOfRooms(isMultiplayer) + 1` rows
- **Boss placement**: Center column, last row (line 77)
- **Starting point**: Center column, row 0 (line 78)

**Point Types** (MapPointType enum, from restrictions):
- Monster, Elite, Boss, Treasure, Shop, RestSite, Event, Unknown

**Encounter Selection** (implicit in flow):
1. StandardActMap assigns **types** to points (line 84)
2. When player moves to a point, the room system instantiates an encounter:
   - Encounter picked from ActModel's room pool matching the point type
   - EncounterModel.GenerateMonstersWithSlots() called on demand (line 189)

### Encounter Generation

**EncounterModel.GenerateMonstersWithSlots()** (line 189):
```csharp
public void GenerateMonstersWithSlots(IRunState runState)
{
    if (_rng == null)
    {
        uint seed = (uint)((int)runState.Rng.Seed + runState.TotalFloor 
                          + StringHelper.GetDeterministicHashCode(base.Id.Entry));
        _rng = new Rng(seed);
    }
    _monstersWithSlots = GenerateMonsters();  // Subclass override
    // ... validate monsters ...
}
```

- Seed per encounter = (run seed + total floor + encounter ID hash)
- Calls abstract `GenerateMonsters()` (implemented by each encounter type)
- Returns `IReadOnlyList<(MonsterModel, string?)>` tuples (monster + optional slot name)

**ActModel** (abstract):
- Holds `RoomSet _rooms` with pooled encounters by RoomType
- `GetMapPointTypes(Rng rng)` → counts of each room type for this act
- Specific acts inherit and define encounter pools

**Example: Act 1 Map Generation**
1. Player starts run with seed (e.g., `0x12345678`)
2. `StandardActMap.CreateFor(runState, ...)` called
3. Rng seeded as `new Rng(seed, "act_1_map")` (salt by act index)
4. GenerateMap() builds connectivity (depth-first search with constraints)
5. AssignPointTypes() uses point-type counts to place Monster/Elite/Boss/etc. rooms
6. When player enters a room, encounter is instantiated and `GenerateMonstersWithSlots()` called
7. Encounter seed = (runState.Rng.Seed + totalFloor + hash(encounterID))
8. Monsters spawned deterministically from that seed

---

## Bonus: AutoSlay System

**File**: `/MegaCrit.Sts2.Core.AutoSlay/AutoSlayer.cs`

**Status**: **Full in-game auto-play system** suitable for hijacking by an external bot.

**Key Findings**:
- Singleton: `public static bool IsActive { get; private set; }`
- Room handler architecture: Maps `RoomType` (Monster, Elite, Boss, Event, Shop, Treasure, RestSite) to `IRoomHandler` implementations
  - `CombatRoomHandler` for combat encounters (line 64)
  - `EventRoomHandler`, `ShopRoomHandler`, `TreasureRoomHandler`, `RestSiteRoomHandler` for other room types
- Screen handlers for decision points (RewardsScreen, CardRewardScreen, DeckUpgradeScreen, etc.)
- Uses `Rng` field (line 45) for deterministic auto-play
- `Watchdog` mechanism (line 47) for timeout detection
- Flag: `NonInteractiveMode.AutoSlayerCheck = () => IsActive` (line 59) — used by game to suppress UI during auto-play

**Action Channel**:
- AutoSlayer calls room handlers' methods to issue actions
- Room handlers likely enqueue game actions (e.g., PlayCardAction, MoveToMapCoordAction) via `ActionQueueSet`
- Full integration with combat turn loop and card play

**Potential for External Bot**:
- Bot could replace or wrap room/screen handlers to implement custom AI
- Or intercept action queue before execution
- **No explicit `RegisterHandler()` or override interface**, so integration would require subclassing or monkey-patching

---

## Open Questions for Phase 4/5

1. **Card Effect Resolution**: Where are individual card effects (Damage/Block/Buff application) executed?
   - CardModel has no `Execute()` method; search for subclass overrides in `/MegaCrit.Sts2.Core.Models.Cards/` (580+ files)
   - Likely in hooks or command builders (e.g., DamageCmd, PowerCmd)
   - **File to read**: `/MegaCrit.Sts2.Core.Commands/DamageCmd.cs` and `PowerCmd.cs`

2. **Monster Move Branching**: How do ConditionalBranchState and RandomBranchState work?
   - Current code shows `GetNextState()` returns a string ID; conditional/random nodes return different IDs based on RNG or creature state
   - **File to read**: `/MegaCrit.Sts2.Core.MonsterMoves.MonsterMoveStateMachine/ConditionalBranchState.cs` and `RandomBranchState.cs`

3. **Encounter Pool Selection**: How are specific encounters chosen from ActModel's room pools?
   - GenerateMonstersWithSlots() exists, but where is the encounter instance selected from the pool?
   - Likely in room initialization or map node instantiation
   - **File to read**: `/MegaCrit.Sts2.Core.Rooms/CombatRoom.cs` (likely calls act.GetEncounterForPoint() or similar)

4. **Hook System Integration**: What is the complete list of hook names and when they fire?
   - Seen: `BeforePlayPhaseStart`, `ShouldPlay`, `BeforeTurnEnd`, `AfterTurnEnd`, `BeforeFlush`, `AfterCardRetained`
   - **File to read**: `/MegaCrit.Sts2.Core.Hooks/Hook.cs` (static methods, likely 100+ hooks)

5. **AutoSlayer Action Enqueueing**: How does AutoSlayer translate room handler decisions into GameActions?
   - Does it directly call ActionExecutor.Enqueue() or use intermediate command builders?
   - **File to read**: `/MegaCrit.Sts2.Core.AutoSlay/Handlers/Rooms/CombatRoomHandler.cs`

---

**Report generated**: 2026-05-23  
**Codebase version**: Slay the Spire 2 (Godot/C# decompiled)  
**Scope**: MegaCrit.Sts2.Core.* namespaces (3,369 .cs files)

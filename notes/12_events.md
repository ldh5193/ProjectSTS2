# STS2 Events & ? Rooms — Spec for sim/events.py

Source: `decompiled/MegaCrit.Sts2.Core.Odds/UnknownMapPointOdds.cs`, `RoomSet.cs`, `EventModel.cs`, per-event classes in `MegaCrit.Sts2.Core.Models.Events/`.
Verified by Phase-A5 agent sweep 2026-05-24.

---

## 1. ? Room Outcome Distribution (`UnknownMapPointOdds`)

| Outcome | Base probability |
|---|---|
| Monster (combat) | 10% |
| Elite | -1 (disabled by default) |
| Treasure | 2% |
| Shop | 3% |
| Event | 85% (computed as `1 - sum(positive others)`) |

`EventOdds = Math.Max(0, 1 - non_event_sum_positive)`.

**RNG**: `RunRng.UnknownMapPoint` (notes/04_prng.md §2).

**First-run special** (UnknownMapPointOdds.cs:103–111): if `unlockState.NumberOfRuns == 0`, the first 3 unknown rooms are forced to `[Event, Event, Monster]`.

Modder hooks `Hook.ModifyUnknownMapPointRoomTypes` + `Hook.ModifyOddsIncreaseForUnrolledRoomType` can adjust at runtime.

## 2. Event Pools by Act

### Act 1 (Overgrowth) — 13 events

AromaOfChaos, ByrdonisNest, DenseVegetation, JungleMazeAdventure, LuminousChoir, MorphicGrove, SapphireSeed, SunkenStatue, TabletOfTruth, UnrestSite, Wellspring, WhisperingHollow, WoodCarvings.

### Act 2 (Hive) — 10 events

Amalgamator, Bugslayer, ColorfulPhilosophers, ColossalFlower, FieldOfManSizedHoles, InfestedAutomaton, LostWisp, SpiritGrafter, TheLanternKey, ZenWeaver.

### Act 3 (Glory) — 7 events

BattlewornDummy, GraveOfTheForgotten, HungryForMushrooms, Reflections, RoundTeaParty, Trial, TinkerTime.

Cross-act: ColorfulPhilosophers appears in both Act 2 and Act 3.

### Ancient encounters (act start, one of N)

- Act 1: **Neow** (always).
- Act 2: Orobas, Pael, Tezcatara.
- Act 3: Nonupeipe, Tanx, Vakuu.

The user's "특정 시드에 맞는 1/2/3막 당 첫 유물 선택지" likely refers to these Ancient encounters offering relic choices as part of their option set.

## 3. Event Structure

Each event is a class deriving `EventModel`:
- `Id`, `Rarity` (Common/Uncommon/Rare event-level — affects ?-room weighting if any).
- `IsAllowed(IRunState)` predicate — pre-conditions (gold, HP fraction, owned items, etc).
- `OnEnter(player, choice_context)` async — display intro, possibly pre-roll.
- Options: each `EventOption` has `Title`, `Description`, `IsAllowed`, `IsEnabled`, `OnSelect(player)` async.

### Example — DenseVegetation (Act 1)

Two options:
1. **TrudgeOn**: Take 8 HP damage, gain 61–100 gold.
2. **Rest**: Heal to full, then forced combat with `DenseVegetationEventEncounter`.

### Example — ByrdonisNest (Act 1)

`IsAllowed`: no player has an event pet (line 35). Specific reward/cost details require reading the .cs file.

### Example — UnrestSite (Act 1)

`IsAllowed`: all players at ≤70% max HP (line 26–28). Likely heals or upgrades cards.

### Example — FakeMerchant (Act 2/3)

`IsAllowed`: act ≥ 2, single-player, ≥100 gold OR has Foul Potion.

## 4. Anti-Repeat

`RunState._visitedEventIds: HashSet<ModelId>` accumulates as events are visited.

`RoomSet.EnsureNextEventIsValid()` (RoomSet.cs:104–119): advance `eventsVisited` cursor until:
1. `NextEvent.IsAllowed(runState)` AND
2. `event.Id not in visitedEventIds`.

If all events exhausted within an act, warning logged ("All unique events exhausted, allowing repetition") and the cursor wraps.

Cross-act: pools differ per act; no global anti-repeat.

## 5. Per-Event RNG

Each event has its own deterministic `Rng` (EventModel.cs:193):
```csharp
Rng = new Rng((uint)(
    Owner.RunState.Rng.Seed
    + (IsShared ? 0 : Owner.NetId)
    + (ulong)StringHelper.GetDeterministicHashCode(Id.Entry)
));
```

So an event's internal random outcomes (e.g., DenseVegetation's gold roll 61–100) are deterministic per `(run_seed, player, event_id)`.

## 6. Python Port Plan (sim/events.py)

```python
class EventOptionEffect(str, Enum):
    HP_LOSE, HP_HEAL, GOLD_GAIN, GOLD_LOSE, ADD_CURSE, ADD_CARD, REMOVE_CARD,
    UPGRADE_RANDOM, ADD_RELIC, REPLACE_RELIC, ENTER_COMBAT, NO_OP, ...

@dataclass
class EventOption:
    label: str
    is_allowed: Callable[[RunState], bool] = lambda rs: True
    effects: list[Callable[[RunState, Rng], None]] = field(default_factory=list)

@dataclass
class EventDef:
    id: str
    act: str
    options: list[EventOption]
    is_allowed: Callable[[RunState], bool] = lambda rs: True

EVENTS_BY_ACT: dict[str, list[EventDef]] = {
    "overgrowth": [
        EventDef("DenseVegetation", "overgrowth", [
            EventOption("TrudgeOn", effects=[
                lambda rs, rng: rs.lose_hp(8),
                lambda rs, rng: rs.gain_gold(rng.next_int(61, 101)),
            ]),
            EventOption("Rest", effects=[
                lambda rs, rng: rs.heal(rs.max_hp),
                lambda rs, rng: rs.enter_combat("DenseVegetationEventEncounter"),
            ]),
        ]),
        # ...12 more
    ],
    "hive": [...],
    "glory": [...],
}

def roll_unknown_room(rng: Rng, run_state: RunState) -> str:
    # First-run special override checked by caller
    odds = [("monster", 0.10), ("treasure", 0.02), ("shop", 0.03)]
    f = rng.next_float()
    cum = 0
    for name, p in odds:
        cum += p
        if f < cum:
            return name
    return "event"

def select_event(act: str, run_state: RunState, rng: Rng) -> EventDef:
    pool = EVENTS_BY_ACT[act]
    candidates = [e for e in pool
                  if e.id not in run_state.history_events and e.is_allowed(run_state)]
    if not candidates:
        candidates = [e for e in pool if e.is_allowed(run_state)]
    return rng.next_item(candidates)
```

First slice: implement Neow (Ancient/Act 1 start) + 3 Act-1 events (DenseVegetation, Wellspring, WoodCarvings) with full effects. Others are scaffolds with a single "leave" option so the agent can still pass them.

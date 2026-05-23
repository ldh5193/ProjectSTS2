# STS2 Encounter Pools & Selection — Spec for sim/encounter.py

Source: `decompiled/MegaCrit.Sts2.Core.Models/ActModel.cs` + per-encounter classes.
Verified by Phase-A2 agent sweep 2026-05-24.

---

## 1. Pool Catalog (per act)

There are 4 acts: **Overgrowth** (Act 1 primary), **Hive** (Act 2), **Glory** (Act 3), **Underdocks** (Act 1 alt).

### Act 1 — Overgrowth (22 encounters)

- **Weak (3)**: FuzzyWurmCrawlerWeak, NibbitsWeak, ShrinkerBeetleWeak.
- **Normal (~12)**: CubexConstructNormal, FlyconidNormal, FogmogNormal, InkletsNormal, MawlerNormal, NibbitsNormal, RubyRaidersNormal, SlitheringStranglerNormal, SnappingJaxfruitNormal, SlimesNormal, SlimesWeak (yes, weak-tagged but in normal pool), VineShamblerNormal.
- **Elite (3)**: BygoneEffigyElite, ByrdonisElite, PhrogParasiteElite.
- **Boss (3)**: CeremonialBeastBoss, TheKinBoss, VantomBoss.

### Act 2 — Hive (20 encounters)

- **Weak (2)**: ExoskeletonsWeak, ThievingHopperWeak, TunnelerWeak.
- **Normal (~11)**: BowlbugsNormal, ChompersNormal, ExoskeletonsNormal, HunterKillerNormal, LouseProgenitorNormal, MytesNormal, OvicopterNormal, SlumberingBeetleNormal, SpinyToadNormal, TheObscuraNormal, BowlbugsWeak.
- **Elite (3)**: DecimillipedeElite, EntomancerElite, InfestedPrismsElite.
- **Boss (3)**: KaiserCrabBoss, KnowledgeDemonBoss, TheInsatiableBoss.

### Act 3 — Glory (18 encounters)

- **Weak (2)**: DevotedSculptorWeak, ScrollsOfBitingWeak, TurretOperatorWeak.
- **Normal (~10)**: AxebotsNormal, ConstructMenagerieNormal, FabricatorNormal, FrogKnightNormal, GlobeHeadNormal, OwlMagistrateNormal, ScrollsOfBitingNormal, SlimedBerserkerNormal, TheLostAndForgottenNormal, TunnelerNormal.
- **Elite (3)**: KnightsElite, MechaKnightElite, SoulNexusElite.
- **Boss (3)**: DoormakerBoss, QueenBoss, TestSubjectBoss.

### Underdocks (Act 1 alt, 20 encounters)

- **Weak (3)**: CorpseSlugsWeak, SeapunkWeak, SludgeSpinnerWeak, ToadpolesWeak.
- **Normal (~10)**: CorpseSlugsNormal, CultistsNormal, FossilStalkerNormal, GremlinMercNormal, HauntedShipNormal, LivingFogNormal, PunchConstructNormal, SeapunkNormal, SewerClamNormal, TwoTailedRatsNormal.
- **Elite (3)**: PhantasmalGardenersElite, SkulkingColonyElite, TerrorEelElite.
- **Boss (3)**: LagavulinMatriarchBoss, SoulFyshBoss, WaterfallGiantBoss.

**Event-tied** (spawned by events, not from pool): TheArchitectEventEncounter, BattlewornDummyEventEncounter, MysteriousKnightEventEncounter, PunchOffEventEncounter, DenseVegetationEventEncounter.

**EncounterTag enum** (used for anti-repeat): Nibbit, Slimes, Shrinker, Thieves, Crawler, Mushroom, Knights, Scrolls, Seapunk, Slugs, Exoskeletons, Burrower, Chomper, Workers.

---

## 2. Selection Algorithm

### Phase 1 — Static pool generation at run start

`ActModel.GenerateRooms(rng, unlockState, isMultiplayer)` (ActModel.cs:224–279):

```csharp
// Weak slots (3 for Act1/Underdocks, 2 for Act2/3)
GrabBag<EncounterModel> weakBag = ...;
for (int i = 0; i < NumberOfWeakEncounters; i++) {
    if (weakBag.Empty) refill from AllWeakEncounters with weight=1.0;
    AddWithoutRepeatingTags(_rooms.normalEncounters, weakBag, rng);
}

// Normal (non-weak) slots
GrabBag<EncounterModel> normalBag = ...;
for (int j = NumberOfWeakEncounters; j < GetNumberOfRooms(isMultiplayer); j++) {
    if (normalBag.Empty) refill from AllRegularEncounters with weight=1.0;
    AddWithoutRepeatingTags(_rooms.normalEncounters, normalBag, rng);
}

// Elite: always exactly 15 generated
for (int k = 0; k < 15; k++) {
    if (eliteBag.Empty) refill from AllEliteEncounters;
    AddWithoutRepeatingTags(_rooms.eliteEncounters, eliteBag, rng);
}

// Boss / Ancient: single uniform pick
_rooms.Boss = rng.NextItem(AllBossEncounters);
_rooms.Ancient = rng.NextItem(GetUnlockedAncients(unlockState)...);
```

`AddWithoutRepeatingTags()` (line 309–320):
```csharp
encounter = grabBag.GrabAndRemove(rng, e =>
    !e.SharesTagsWith(encounters.LastOrDefault())
    && e != encounters.LastOrDefault()
);
if (encounter == null) encounter = grabBag.GrabAndRemove(rng);  // fallback
encounters.Add(encounter);
```

### Phase 2 — Per-floor pull via cycling

`RoomSet`:
```csharp
NextNormalEncounter => normalEncounters[normalEncountersVisited % normalEncounters.Count];
NextEliteEncounter  => eliteEncounters[eliteEncountersVisited  % eliteEncounters.Count];
NextBossEncounter   => (bossEncountersVisited > 0 && SecondBoss != null) ? SecondBoss : Boss;
```

The counter advances each time a player enters that room type. Modulo allows pool wrap-around if the player visits more rooms than were generated.

---

## 3. Weighting

**Uniform 1.0** for all normal/weak/elite/boss/ancient. No rarity tiering beyond the bag membership itself.

Anti-repeat is the only modulating factor.

---

## 4. First-Run Discovery Order (tutorial)

`Overgrowth.ApplyActDiscoveryOrderModifications` overrides if `unlockState.NumberOfRuns == 0`:

| Slot | Forced encounter |
|---|---|
| normalEncounters[0] | NibbitsWeak |
| normalEncounters[1] | SlimesWeak |
| normalEncounters[2] | ShrinkerBeetleWeak |
| normalEncounters[3] | InkletsNormal |
| normalEncounters[4] | MawlerNormal |
| normalEncounters[5] | RubyRaidersNormal |
| normalEncounters[6] | NibbitsNormal |
| eliteEncounters[0]  | ByrdonisElite |
| eliteEncounters[1]  | PhrogParasiteElite |
| events[0]           | ByrdonisNest |
| events[1]           | SapphireSeed |

Acts 2 and 3 have empty `ApplyActDiscoveryOrderModifications()`.

**Per-act boss discovery order** (first run picks first unseen boss):
- Overgrowth: VantomBoss → CeremonialBeastBoss → TheKinBoss.
- Hive: TheInsatiableBoss → KnowledgeDemonBoss → KaiserCrabBoss.
- Glory: QueenBoss → TestSubjectBoss → DoormakerBoss.
- Underdocks: WaterfallGiantBoss → SoulFyshBoss → LagavulinMatriarchBoss.

---

## 5. A10 (DoubleBoss) — final act only

`RunManager.cs:499–503`:
```csharp
if (i == State.Acts.Count - 1
    && AscensionManager.HasLevel(AscensionLevel.DoubleBoss))
{
    EncounterModel secondBoss = State.Rng.UpFront.NextItem(
        act.AllBossEncounters.Where(e => e.Id != act.BossEncounter.Id)
    );
    act.SetSecondBossEncounter(secondBoss);
}
```

Uses `State.Rng.UpFront` (RunRngSet category — see notes/04_prng.md §2). Selects a boss different from the primary.

`RoomSet.NextBossEncounter` returns SecondBoss after the first boss visit count > 0.

---

## 6. RNG Category

- Encounter pool generation: `State.Rng` (root) consumed via the GrabBag's `NextItem`/`GrabAndRemove` calls. The map RNG (notes/08_map_gen.md §3) is separate from this; encounter generation uses the run's main Rng (NOT the per-act map Rng).
- Boss/Ancient selection: `State.Rng` (or `State.Rng.UpFront`).
- A10 second boss: explicitly `State.Rng.UpFront.NextItem(...)`.

---

## 7. Python Port Plan (sim/encounter.py)

```python
ENCOUNTERS_BY_ACT = {
    "overgrowth": {
        "weak": ["FuzzyWurmCrawlerWeak", "NibbitsWeak", "ShrinkerBeetleWeak"],
        "normal": [...],
        "elite": ["BygoneEffigyElite", "ByrdonisElite", "PhrogParasiteElite"],
        "boss": ["CeremonialBeastBoss", "TheKinBoss", "VantomBoss"],
        "num_weak_slots": 3,
        "num_total_rooms": 15,
    },
    "hive": {...},
    "glory": {...},
    "underdocks": {...},
}
ENCOUNTER_TAGS = {"NibbitsWeak": "Nibbit", ...}

@dataclass
class EncounterPools:
    normal: list[str]    # length = num_total_rooms (weak then normal)
    elite: list[str]     # always 15
    boss: str
    ancient: str
    second_boss: str | None  # A10 only, final act only
    normal_visited: int = 0
    elite_visited: int = 0
    boss_visited: int = 0

    def next_normal(self) -> str:
        eid = self.normal[self.normal_visited % len(self.normal)]
        self.normal_visited += 1
        return eid
    # ...

def generate_pools(act: str, rng: Rng, is_first_run: bool,
                   ascension: int, is_final_act: bool) -> EncounterPools:
    ...
```

Anti-repeat: track previously-added encounter, skip same-tag candidates unless the bag is exhausted.

First slice (MVP): support Overgrowth + Underdocks. Map only NibbitsWeak + SludgeSpinnerWeak to live sim Monsters (the others are stubs that auto-die after 1 turn — placeholder, learning still works because the agent loses HP but combat resolves).

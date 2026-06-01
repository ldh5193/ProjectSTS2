# Phase 9 — Multi-Character Fidelity Plan

Date: 2026-06-01
Status: PLANNING (research + design only; no sim/training code changed by this doc)
Scope: extend the STS2 simulator from **Ironclad-only** (~97% faithful, see
`docs/FIDELITY_AUDIT.md`, 809 tests green) to **all playable single-player
characters at 100%**. Multiplayer content remains OUT OF SCOPE.

Every number and mechanic below was re-derived from the decompile under
`decompiled/MegaCrit.Sts2.Core.*` (~3370 .cs files) — file refs are cited
inline. Do NOT trust STS1 assumptions; STS2 differs (new characters
Necrobinder/Regent, 5 orb types incl. Glass/Plasma, a Star resource, a
persistent Osty minion).

The sim already threads a `character: Character` arg end-to-end
(`sim/env_run.py:334`, `sim/game_state.py:140,205`) and the `Character` enum
already lists all six (`sim/game_state.py:67-73`):
`IRONCLAD, SILENT, DEFECT, NECROBINDER, REGENT, DEPRIVED`. Only Ironclad is
wired (`_CHARACTER_STARTING_HP`/`_GOLD` only hold Ironclad;
`game_state.py:235-236` builds the starting deck/relic only when
`character is Character.IRONCLAD`).

---

## 1. Character Roster

The character archetype set lives in `decompiled/MegaCrit.Sts2.Core.Models.Characters/`
(`CharacterModel` base = `decompiled/MegaCrit.Sts2.Core.Models/CharacterModel.cs`).
Eight files exist there; two are non-playable:

- `RandomCharacter.cs` — character-select "?" wrapper, picks one of the real
  ones; not a distinct run identity.
- `DeprecatedCharacter.cs` — cut/legacy content holder.
- `Deprived.cs` — a **debug/sandbox** character: `StartingHp => 1000`,
  `MaxEnergy => 100`, `StartingDeck => Array.Empty`, `StartingRelics =>
  Array.Empty`, `CardPool => MockCardPool`, borrows `IroncladRelicPool` /
  `IroncladPotionPool`. It is in the enum (`game_state.py:73`) but is **not a
  real playable identity** — treat as a test fixture only, not a fidelity
  target.

That leaves **five real playable characters**. Base values come from each
character file; `MaxEnergy` defaults to `3` and `BaseOrbSlotCount` to `0`
(`CharacterModel.cs:59,63`).

| Character | File | StartHP | StartGold | Start Relic | MaxEnergy | OrbSlots | Signature |
|-----------|------|--------:|----------:|-------------|----------:|---------:|-----------|
| Ironclad | `Ironclad.cs` | 80 | 99 | `BurningBlood` | 3 | 0 | Strength / block / exhaust-rage (DONE) |
| Silent | `Silent.cs` | 70 | 99 | `RingOfTheSnake` | 3 | 0 | Shivs + Poison + discard |
| Defect | `Defect.cs` | 75 | 99 | `CrackedCore` | 3 | **3** | **Orbs** (Lightning/Frost/Dark/Plasma/Glass) + Focus |
| Necrobinder | `Necrobinder.cs` | 66 | 99 | `BoundPhylactery` | 3 | 0 | **Osty** persistent minion (summon/sacrifice) |
| Regent | `Regent.cs` | 75 | 99 | `DivineRight` | 3 | 0 | **Stars** resource (gain/spend, star-cost cards) |

Ascension note: `MaxEnergy` is base-3 for all five; the engine's
`PlayerCombatState.MaxEnergy` runs it through `Hook.ModifyMaxEnergy`
(`PlayerCombatState.cs:68`). There is no per-character starting-HP ascension
penalty baked into `CharacterModel`; ascension HP/heal/curse effects are global
and already handled in `sim/game_state.py:_apply_ascension_effects` (line 442).
So the per-character ascension delta is just "lower base HP" (already in the
table) — no new per-character ascension code is required.

### Starting decks (exact, from each character file)

- **Ironclad** (`Ironclad.cs:36-48`): 5× StrikeIronclad, 4× DefendIronclad,
  1× Bash. (already in sim, `cards.py:70`.)
- **Silent** (`Silent.cs:40-54`): 5× StrikeSilent, 5× DefendSilent,
  1× Neutralize, 1× Survivor. (12-card starting deck — the only one >10.)
- **Defect** (`Defect.cs:38-50`): 4× StrikeDefect, 4× DefendDefect, 1× Zap,
  1× Dualcast.
- **Necrobinder** (`Necrobinder.cs:45-57`): 4× StrikeNecrobinder,
  4× DefendNecrobinder, 1× Bodyguard, 1× Unleash.
- **Regent** (`Regent.cs:38-50`): 4× StrikeRegent, 4× DefendRegent,
  1× FallingStar, 1× Venerate.

### Energy / resource model (per character)

All five use the standard 3-energy model (`CharacterModel.MaxEnergy => 3`). The
*additional* per-turn resource differs:

- **Defect** — an **Orb queue** with base capacity 3 (`Defect.cs:60
  BaseOrbSlotCount => 3`). Orbs are not energy; they trigger passively at turn
  end and can be evoked.
- **Regent** — a **Star** counter (`PlayerCombatState.cs:70 Stars`,
  `GainStars`/`LoseStars` at lines 167-182). Some cards cost stars
  (`CanonicalStarCost`, e.g. `FallingStar.cs:16 => 2`) and excess energy cost
  can be paid with stars (`PlayerCombatState.cs:150
  ShouldPayExcessEnergyCostWithStars`). `ShouldAlwaysShowStarCounter => true`
  (`Regent.cs:30`).
- **Necrobinder** — a **summoned minion ("Osty")**, a persistent secondary
  creature with its own HP that the player buffs and sacrifices (resource =
  the minion's existence + HP, not a numeric pool).
- **Silent / Ironclad** — no extra resource (standard 3-energy).

### Signature mechanic detail (decompile-verified)

- **Defect = Orbs.** `OrbQueue` (`decompiled/MegaCrit.Sts2.Core.Entities.Orbs/OrbQueue.cs`):
  bounded list, `maxCapacity = 10`, `Capacity` grows via `AddCapacity`,
  channel = `TryEnqueue` (fails silently if capacity 0; throws if full;
  overflow eviction is *oldest-first* via `Remove(_orbs.Last())` only on
  capacity shrink). `BeforeTurnEnd`/`AfterTurnStart` fire each orb's passive
  `triggerCount` times (modifiable by `Hook.ModifyOrbPassiveTriggerCount`).
  Five orb types (`OrbModel._validOrbs`,
  `decompiled/MegaCrit.Sts2.Core.Models/OrbModel.cs:27-34`):
  - `LightningOrb` (`Models.Orbs/LightningOrb.cs`): passive 3 dmg to random
    enemy at turn end; evoke 8 dmg.
  - `FrostOrb` (`Models.Orbs/FrostOrb.cs`): passive block; evoke bigger block.
  - `DarkOrb` (`Models.Orbs/DarkOrb.cs`): passive *accumulates* (`_evokeVal +=
    PassiveVal` each turn end, base 6); evoke hits the lowest-HP enemy for the
    accumulated value.
  - `PlasmaOrb` (`Models.Orbs/PlasmaOrb.cs`): gives energy.
  - `GlassOrb` (`Models.Orbs/GlassOrb.cs`): STS2-new orb type.
  Orb values scale via `OrbModel.ModifyOrbValue -> Hook.ModifyOrbValue`
  (`OrbModel.cs:237-240`) — this is the **Focus** hook
  (`Models.Powers/FocusPower.cs`, plus `TemporaryFocusPower`, `BiasedCognitionPower`).

- **Silent = Shivs + Poison + discard.** Shiv is a 0-cost Exhaust attack token
  (`Models.Cards/Shiv.cs`: `CardTag.Shiv`, `CardKeyword.Exhaust`, 4 dmg,
  targets AllEnemies when "Fan of Knives" is active). Poison is a stacking
  damage-over-time power (`Models.Powers/PoisonPower.cs`); applied by
  `DeadlyPoison`, `PoisonedStab` (`Models.Cards/`). Shiv damage scales with
  `AccuracyPower` (`Models.Powers/AccuracyPower.cs`). Shivs come from
  `TokenCardPool` (14 tokens). Discard payoffs exist as a card family. Starting
  relic `RingOfTheSnake` (`Models.Relics/RingOfTheSnake.cs`) = draw 2 on combat
  start.

- **Necrobinder = Osty minion.** `Osty` is a `MonsterModel`
  (`decompiled/MegaCrit.Sts2.Core.Models.Monsters/Osty.cs`) owned by the player
  side: `MinInitialHp == MaxInitialHp == 1`, a `NOTHING_MOVE` state machine
  (it does not act on its own; the player drives it). Summoned via
  `OstyCmd.Summon` (`decompiled/MegaCrit.Sts2.Core.Commands/OstyCmd.cs`),
  tracked on the player as `Owner.Osty` / `Owner.IsOstyMissing`
  (`Entities.Players/Player.cs`). `MinionPower`
  (`Models.Powers/MinionPower.cs`) flags the creature: `OwnerIsSecondaryEnemy
  => true`, survives owner death, not fatal on death. Cards:
  - `Bodyguard.cs` — `OstyCmd.Summon(... SummonVar(5))`; upgrade +2 HP.
  - `Unleash.cs` — `CardTag.OstyAttack`; damage = `osty.CurrentHp` (multiplier
    var pulls live Osty HP); glows red while Osty missing.
  - plus `SummonForth`, `MinionStrike`, `MinionDiveBomb`, `MinionSacrifice`,
    `NecroMastery` and powers `SummonNextTurnPower`, `NecroMasteryPower`,
    `PhylacteryUnbound` relic. Starting relic `BoundPhylactery`
    (`Models.Relics/BoundPhylactery.cs`).

- **Regent = Stars.** A counter resource on `PlayerCombatState` (`Stars`,
  `GainStars`, `LoseStars`, `StarsChanged` event). Cards declare
  `CanonicalStarCost` (e.g. `FallingStar.cs:16 => 2`, `Venerate.cs`). Powers
  generate stars over time: `StarNextTurnPower` (`Models.Powers/StarNextTurnPower.cs`
  — `AfterEnergyReset -> PlayerCmd.GainStars(Amount)`), `DyingStarPower`,
  `ChildOfTheStarsPower`, `RoyaltiesPower`. Excess energy can be paid in stars
  (`PlayerCombatState.cs:150`). Star cards: `ChildOfTheStars`, `CloakOfStars`,
  `DyingStar`, `GuidingStar`, `SevenStars`, `Stardust`, `Venerate`,
  `FallingStar`. Starting relic `DivineRight` (`Models.Relics/DivineRight.cs`).

---

## 2. Per-Character Pool Sizes (from the decompile)

Counted from the `new CardModel[N]` / `new RelicModel[N]` / `new PotionModel[N]`
array literals in each pool file under
`decompiled/MegaCrit.Sts2.Core.Models.{CardPools,RelicPools,PotionPools}/`.

### Card pools (`Models.CardPools/*CardPool.cs`)

| Pool | Cards | Notes |
|------|------:|-------|
| `IroncladCardPool` | 87 | already in sim |
| `SilentCardPool` | 88 | |
| `DefectCardPool` | 88 | epoch-gated subsets (Defect2/5/7Epoch) |
| `NecrobinderCardPool` | 88 | |
| `RegentCardPool` | 88 | |
| `ColorlessCardPool` | 64 | shared, any character |
| `CurseCardPool` | 18 | shared |
| `StatusCardPool` | 11 | shared (Wound/Dazed/etc.) |
| `TokenCardPool` | 14 | shared (Shivs, Smites, etc.) |
| `QuestCardPool` | 3 | shared |
| `EventCardPool` | 27 | event-granted |

Character-color cards new to Phase 9 = 88 + 88 + 88 + 88 = **352** (Silent +
Defect + Necrobinder + Regent), minus the 6 Strike/Defend basics already
trivially mirror-able. Each pool also includes per-character Strike/Defend
basics (e.g. `StrikeSilent`, `DefendDefect`).

### Relic pools (`Models.RelicPools/*RelicPool.cs`)

| Pool | Relics |
|------|------:|
| `IroncladRelicPool` | 8 |
| `SilentRelicPool` | 8 |
| `DefectRelicPool` | 8 |
| `NecrobinderRelicPool` | 8 |
| `RegentRelicPool` | 8 |
| `SharedRelicPool` | 118 |
| `EventRelicPool` | 137 |
| `FallbackRelicPool` | (list-built, small) |

**Key finding:** each character has only **8 character-specific relics**; the
bulk (`SharedRelicPool` 118, `EventRelicPool` 137) is shared and already
modeled for Ironclad. So per new character the *new* relic work is the 8 in its
pool + its starting relic (`RingOfTheSnake`, `CrackedCore`, `BoundPhylactery`,
`DivineRight`) ≈ 9 relics each (the starting relic is usually also in/near the
pool). New character relics total ≈ **4 × ~9 = ~36** plus auditing the shared
pool for character-gated effects.

### Potion pools (`Models.PotionPools/*PotionPool.cs`)

The per-character potion pool files (`IroncladPotionPool`, `SilentPotionPool`,
`DefectPotionPool`, `NecrobinderPotionPool`, `RegentPotionPool`) do **not**
declare a `new PotionModel[N]` literal — they subclass/extend the
`SharedPotionPool` (45 potions, `SharedPotionPool.cs`). Potions are essentially
shared; a few may be character-flavored (e.g. a Focus/orb potion for Defect, a
poison potion for Silent). Net new potion work is **small** — audit the 45
shared + any per-character override, likely <10 new potions total.

### Powers (`Models.Powers/`)

There is no per-character power-pool file; powers are referenced by cards/relics.
The character-specific power families to add:

- Defect: `FocusPower`, `TemporaryFocusPower`, `BiasedCognitionPower`,
  orb-trigger powers (`HotfixPower`, `EchoForm`-like), `BufferPower`, etc.
- Silent: `PoisonPower`, `AccuracyPower`, shiv/discard powers.
- Necrobinder: `MinionPower`, `SummonNextTurnPower`, `NecroMasteryPower`.
- Regent: `StarNextTurnPower`, `DyingStarPower`, `ChildOfTheStarsPower`,
  `RoyaltiesPower`.

Rough unique-new-power count per character: **~15–25** (most card effects reuse
the shared power set Ironclad already has — Vulnerable/Weak/Strength/Block etc.).

### Events

Events are shared (`Models.Events/`) and gated by act, not character, with a
handful of character-flavored branches. No per-character event pool file exists.
Net new event work is **minimal** (audit for character-gated options).

### Summary of net-new content (4 new characters)

- Cards: ~352 character-color (≈ 4 × 88) + the few new tokens/status they touch.
- Relics: ~36 character relics + 4 starting relics + shared-pool audit.
- Powers: ~60–100 new power classes total across the four.
- Potions/events: small (mostly shared).

---

## 3. New Primitives Required

These are mechanical systems the sim does **not** have today (Ironclad never
needed them). Each must integrate with the existing combat hook system in
`sim/combat.py` + `sim/powers.py` (the project already models powers as objects
with `on_*` hooks and a damage pipeline in `sim/damage.py`).

### 3.1 ORB SYSTEM (Defect) — biggest new primitive

Real mechanic (`Entities.Orbs/OrbQueue.cs`, `Models/OrbModel.cs`,
`Models.Orbs/{Lightning,Frost,Dark,Plasma,Glass}Orb.cs`):

- A per-player ordered orb list with an integer `Capacity` (Defect base 3;
  hard max 10). Channel = append (no-op if capacity 0). When already full,
  channeling a new orb **evokes the front orb first** (real game behavior;
  `OrbQueue.RemoveCapacity` shows oldest-first removal semantics; channel-when-
  full evoke is in the channel command, not the queue).
- Each orb has `PassiveVal`/`EvokeVal` (decimals), both routed through
  `ModifyOrbValue -> Hook.ModifyOrbValue` so **Focus** (and Lock-On / orb-value
  relics) scale them.
- Passive triggers: at the relevant turn boundary, `OrbQueue.BeforeTurnEnd`
  (`OrbQueue.cs:81`) and `AfterTurnStart` iterate all orbs, each firing
  `triggerCount` times (default 1, modifiable by hook).
- Per-orb behavior: Lightning (random/targeted damage), Frost (block), Dark
  (accumulating then nuke lowest-HP), Plasma (energy), Glass (STS2-specific).
- Evoke = pop + run `Evoke()`. Dark's evoke value is the accumulated counter,
  not a flat number.

Integration sketch:

- New `sim/orbs.py`: `OrbType` enum, `Orb` dataclass (`type`, `evoke_counter`
  for Dark), `OrbQueue` (list + `capacity`). Methods: `channel(orb)`,
  `evoke_front()`, `evoke_index(i)`, `trigger_passives(when)`, `set_focus`.
- Hook into `CombatState` in `sim/combat.py`: add `orb_queue`, call
  `trigger_passives("turn_end")` in the end-turn path and
  `trigger_passives("turn_start")` at start; route orb damage/block through the
  existing `sim/damage.py` pipeline so Vulnerable/relics apply.
- Focus: add a `FocusPower` (and Temporary Focus) in `sim/powers.py`; orb value
  = `base + focus` (Lightning/Frost/Dark add Focus to passive AND evoke;
  Plasma/energy orbs are Focus-immune per real classes). Expose a
  `modify_orb_value(orb, base)` hook so relics/powers compose.
- Channel actions come from cards (Zap, Dualcast, Ball Lightning…). Evoke is
  *also* card-driven in STS2 (no free-standing "evoke" button) — verify per
  card; if any card lets the player choose which orb to evoke, that becomes an
  action (see §4).

### 3.2 STAR RESOURCE (Regent)

Real mechanic (`Entities.Players/PlayerCombatState.cs:70-182`): an int `Stars`
counter, `GainStars`/`LoseStars`, `StarsChanged` event, persists for the
combat. Cards have `CanonicalStarCost`; some energy overpayment is auto-paid in
stars (`ShouldPayExcessEnergyCostWithStars`, line 150).

Integration sketch:

- Add `stars: int` to the player combat state in `sim/combat.py`; `gain_stars`
  / `lose_stars` helpers; reset to 0 at combat start.
- Extend card cost/playability in `sim/action_space.py` + `sim/cards.py`:
  a card is playable if `energy >= energy_cost AND stars >= star_cost`; spend
  both on play. Add the excess-energy-paid-with-stars rule behind a flag.
- Star-generating powers (`StarNextTurnPower` etc.) fire on `AfterEnergyReset`
  (turn start) → reuse the existing power hook timing.

### 3.3 OSTY MINION / SUMMON RESOURCE (Necrobinder)

Real mechanic (`Models.Monsters/Osty.cs`, `Commands/OstyCmd.cs`,
`Models.Powers/MinionPower.cs`, `Entities.Players/Player.cs` Osty fields): a
single persistent friendly creature with its own HP, no autonomous moves
(`NOTHING_MOVE`), driven by the player's cards (summon, buff HP, attack-for-its-
HP, sacrifice). Survives the player's turn; `IsOstyMissing` gates cards.

Integration sketch:

- The sim already has a `Creature` abstraction (`sim/creatures.py`). Add an
  optional `osty: Creature | None` on the player-side combat state with its own
  HP/powers, on the *player's* team (so enemy AoE/targeting can include it and
  it can take hits). It does not take turns.
- Commands: `summon_osty(hp)`, `sacrifice_osty()`, `osty_attack(target)` (damage
  = osty.hp). Wire `IsOstyMissing` into card playability/glow in
  `sim/action_space.py`.
- `MinionPower` semantics: not removed on death, not fatal — model as a flag on
  the osty creature.

### 3.4 SHIV / TOKEN-CARD + POISON + DISCARD (Silent)

- Shiv: a 0-cost Exhaust attack token generated into hand
  (`Models.Cards/Shiv.cs`, `TokenCardPool`). The sim already has Exhaust and
  card-generation primitives (Ironclad has Anger/clones); needs the Shiv token
  + Accuracy scaling (`AccuracyPower`).
- Poison: stacking DoT (`Models.Powers/PoisonPower.cs`) — loses 1 stack/turn,
  deals stack-count damage at turn start, ignores block. Add `PoisonPower` to
  `sim/powers.py`.
- Discard synergy: cards that trigger "on discard" / reward discarding. The sim
  has a discard pile; add an `on_discard` hook in `sim/powers.py`/`cards.py`.

None of these is as structurally heavy as orbs — they fit the existing
power/card hook model. The only genuinely new combat *state* is poison stacks
(a power) and the Accuracy scaling on shivs.

### 3.5 Focus / orb-value / Star / Osty hooks summary

New hooks to add to the `sim/powers.py` hook surface (mirroring the C# `Hook`
class): `modify_orb_value`, `modify_orb_passive_trigger_count`,
`after_energy_reset` (for stars), `should_pay_excess_energy_with_stars`, and
osty-aware targeting in `sim/damage.py`.

---

## 4. Obs / Action-Space Impact

### Current state

- `sim/env_run.py:45` — `OBS_DIM = 504` (v4.4); built by a cursor-packed encoder
  (combat block, deck/pile features, shop block, etc.). `OBS_DIM_V3 = 256`
  legacy.
- `sim/action_space.py` — `Discrete(300)`, fixed `RANGES` table
  (`action_space.py:61-162`). The combat range (`0..60`) is end-turn +
  play_card(idx) untargeted/targeted. There is **no** representation of orbs,
  stars, osty, or character id anywhere in obs or actions. There is reserved
  headroom: `reserved` action range `246..300` (54 slots) and the obs has a few
  pad dims.
- The mod side mirror is `tools/STS2MCP-src/McpMod.ObsBuilder.cs` (one-to-one
  port of the Python obs builder) — **it must be updated in lockstep**, which
  requires a Unity/Godot mod rebuild (user task). This is the key difference
  from the Ironclad campaign, where `OBS_DIM` was held fixed: Phase 9 **will
  change `OBS_DIM`**.

### Proposed obs extension — version it as v5 (`OBS_DIM = 560`)

Append a new **character block** at the end of the v4.4 layout (never reshuffle
existing cursors, so v4.4 Ironclad checkpoints stay loadable for warm-starts;
the new tail is zero for Ironclad):

```
[0 .. 503)   existing v4.4 layout (unchanged)
[504 .. 510) character one-hot: ironclad, silent, defect, necrobinder, regent, (pad)   6 dims
[510 .. 511) star resource: stars / 10                                                  1 dim
[511 .. 521) orb queue: 10 slots, each = orb_type_id / 5 (0 = empty)                   10 dims
[521 .. 531) orb queue evoke-value: 10 slots, each = evoke_val / 30 (Dark accumulator) 10 dims
[531 .. 532) orb capacity / 10                                                          1 dim
[532 .. 533) focus / 10                                                                 1 dim
[533 .. 537) osty: present, osty_hp/40, osty_block/40, (pad)                            4 dims
[537 .. 541) poison-on-each-enemy (up to 4 enemies) / 20                                4 dims
[541 .. 560) pad to a clean OBS_DIM = 560                                              19 dims
```

`OBS_DIM` v5 = **560** (504 → 560; the +56 block above, rounded). All new dims
normalize to [0, 1] like the rest. Ironclad runs leave the entire `[504..560)`
tail at 0, so the v5 encoder is a strict superset and an Ironclad v4.4 policy
can be re-trained from a v5 obs with the head re-initialized (or padded).

### Proposed action-space extension

Most new mechanics are **card-driven** (channel/evoke happen as part of playing a
card; star cost is paid implicitly; osty summon/attack are card plays), so they
need **no** new actions — they ride the existing `combat` range
(`action_space.py:61-67`). The exceptions, allocated from the `reserved`
range (`246..300`, currently masked):

- **Evoke-target / orb-pick** (if any card asks the player which orb to evoke or
  which slot to channel into): add `orb_select` = 10 slots at `246..256`.
- **Osty target** is already covered: Osty is a friendly creature, and any card
  targeting "self/ally" reuses the existing target encoding; Osty-as-target for
  enemy AoE is automatic. No new action needed unless a card explicitly targets
  Osty (then reuse target slots).
- Keep `N_ACTIONS = 300` if `orb_select` fits in reserved (it does: 10 ≤ 54).
  If future characters need more, bump to `Discrete(320)` at the very end only.

Recommendation: **action space stays `Discrete(300)`** (use reserved tail for
`orb_select` only if a card actually exposes a choice; spot-check `Tempest`,
`Multi-Cast`, `Recursion`-style cards). The big change is obs only.

### Mod parity note

`McpMod.ObsBuilder.cs` and `McpMod.StateBuilder.cs` (the mod state dict) must
emit orbs/stars/osty/poison + character id and pack the v5 tail identically.
This is gated on a user Unity/Godot mod rebuild (per `memory/`: mod obs parity
needs a Unity build). Until then, multi-char models can be trained and evaluated
**in-sim** but not deployed live.

---

## 5. Test-Environment Design

Mirror the Ironclad approach (per-subsystem registries + a fidelity scorecard +
a `tests/` suite), parametrized by character.

1. **Parametrize pools by character.** Promote the Ironclad-only registries to
   per-character maps:
   - `sim/game_state.py`: fill `_CHARACTER_STARTING_HP` / `_GOLD` for all five
     (already have the numbers in §1) and build the per-character starting deck
     + relic in the `RunState` factory (replace the `if character is IRONCLAD`
     guard at `game_state.py:235-236` with a dispatch table).
   - `sim/cards.py`, `sim/card_catalog.py`: add `SILENT_LIBRARY`,
     `DEFECT_LIBRARY`, `NECROBINDER_LIBRARY`, `REGENT_LIBRARY` + per-rarity
     splits, like `IRONCLAD_COMMON/UNCOMMON/RARE` (`card_catalog.py:475-477`).
   - `sim/relics.py`: add `_SILENT_POOL_IDS` etc. alongside
     `_IRONCLAD_POOL_IDS` (`relics.py:2297`); `sim/rewards.py` keys card/relic
     reward pools off `rs.character`.
2. **Per-character fidelity scorecard.** Extend `docs/FIDELITY_AUDIT.md` (or a
   new `docs/FIDELITY_AUDIT_<char>.md`) with the same 4-count table (Real /
   Faithful / N/A / TODO) for each character's cards, relics, powers, plus the
   new primitives (orb types covered, star cards covered, osty cards covered).
   Target: 100% faithful per character.
3. **Per-character test suites.** Mirror `tests/` structure:
   `tests/silent/`, `tests/defect/`, `tests/necrobinder/`, `tests/regent/`,
   plus `tests/orbs/`, `tests/stars/`, `tests/osty/` for the primitives. Each
   card/relic/power gets a behavior test against decompile-derived expected
   values (the Ironclad campaign's pattern). A parametrized
   `test_starting_setup.py` asserts each character's StartHP/Gold/deck/relic
   exactly matches §1.
4. **Smoke/driveability.** A `RunEnv(character=X)` full-run smoke test per
   character (random-legal-action rollout to victory/defeat without exceptions),
   mirroring the existing Ironclad run smoke test.
5. Keep the existing **809 tests green** throughout — new content is additive;
   the Ironclad path must not regress (the obs v5 tail is zero for Ironclad).

---

## 6. Training Plan

### Recommendation: a single **character-conditioned agent** (obs includes
character one-hot), NOT five separate policies.

Rationale:

- Shared structure dominates: map, shop, events, ~255 shared relics, the entire
  run economy, and the combat/damage pipeline are identical across characters.
  A conditioned net amortizes that and transfers (the Ironclad-mastered base is
  a warm start for the shared layers).
- The obs v5 character one-hot (`[504..510)`) is exactly the conditioning
  signal; the policy learns character-specific play from it.
- Avoids 5× the compute and 5× the babysitting of the loop the Ironclad
  campaign already ran.
- Curriculum: phase the characters in as their sim support lands (train
  Ironclad+Silent first once Silent is faithful, then add Defect once orbs
  land, etc.). The env samples a character per episode from the set currently
  supported (a `--characters` flag), weighted to oversample the newest one.

Fallback: if the conditioned agent underperforms a specialist on a hard
character (e.g. Defect orb sequencing), fine-tune a per-character head from the
shared trunk — cheaper than from scratch.

### Launch recipe (per `memory/venv-python-path` + `scripts/launch_train.ps1`)

Training MUST use the non-Store uv CPython via `scripts/launch_train.ps1` (Store
Python suspends when detached). Example, once multi-char env + obs v5 exist:

```
powershell -File scripts\launch_train.ps1 -Name arch_p9a_multichar_silent -Seed 9101 `
  -ExtraArgs "--net-arch 1280,1280 --reward-preset win_meta --best-metric win_rate `
              --characters ironclad,silent --eval-ascension 10 --eval-every 50000 `
              --eval-episodes 50 --ent-coef 0.03 --lr-init 3e-4 --lr-final 1e-5 `
              --steps 40000000 --curriculum --warm-start models/v3/<ironclad_best>.zip"
```

(`--characters` and `--warm-start` are new train_v3 flags to add; warm-start
must handle the obs-dim change 504→560 by padding/zero-init the new input
weights, since the trunk is reused.)

Eval: per-character win-rate at A10 (success bar from memory: beat human ~17%
for Ironclad; set per-character human-baseline targets as data allows). Report a
per-character win-rate vector each eval.

---

## 7. Batch Order + Effort Estimate

Execute one batch per iteration (like the Ironclad fidelity-100 campaign). Order
characters easiest-first to reuse machinery, hardest-primitive (Defect orbs)
mid-campaign once the pattern is proven. Sizes: S ≈ 1 session, M ≈ 2–3, L ≈ 4+.

**P9.0 — Scaffolding (M).** Per-character starting setup: fill
`_CHARACTER_STARTING_HP/_GOLD`, per-character starting-deck/relic dispatch
(`game_state.py:235`), per-character library + rarity splits stubs in
`cards.py`/`card_catalog.py`, pool-id sets in `relics.py`, `rewards.py`
character keying, and obs **v5** layout (`OBS_DIM 504→560`, character one-hot)
behind a flag (Ironclad tail = 0, all 809 tests stay green). `test_starting_setup`.

**P9.1 — Silent (L), no heavy primitive.**
- a) Poison + Accuracy + Shiv token + discard hooks (`sim/powers.py`,
  `sim/cards.py`). (M)
- b) Silent 88 cards in batches (~3 sub-batches of ~30). (L)
- c) Silent 8 relics + `RingOfTheSnake` starting relic. (S)
- d) Silent-specific powers (~15). (M)
- e) Tests: `tests/silent/`, `tests/orbs`-style for poison/shiv. (M)

**P9.2 — Defect (L+), the orb system.**
- a) **Orb primitive**: `sim/orbs.py` (queue, 5 orb types, channel/evoke/passive),
  Focus power + `modify_orb_value` hook, combat.py turn-boundary wiring,
  obs v5 orb dims. (L) ← largest single batch in the campaign.
- b) Defect 88 cards in ~3 sub-batches (channel/evoke/Focus cards). (L)
- c) Defect 8 relics + `CrackedCore` (channel a Dark orb on combat start). (S)
- d) Defect powers (Focus/Temporary Focus/Biased Cognition/orb-trigger). (M)
- e) Tests: `tests/orbs/`, `tests/defect/`. (M)

**P9.3 — Necrobinder (L), the Osty minion.**
- a) **Osty primitive**: friendly persistent creature on player team, summon/
  sacrifice/attack commands, `MinionPower`, `IsOstyMissing` gating, osty obs
  dims + enemy-targeting awareness in `sim/damage.py`. (M–L)
- b) Necrobinder 88 cards (~3 sub-batches). (L)
- c) Necrobinder 8 relics + `BoundPhylactery`. (S)
- d) Powers (`SummonNextTurnPower`, `NecroMasteryPower`, `PhylacteryUnbound`). (M)
- e) Tests: `tests/osty/`, `tests/necrobinder/`. (M)

**P9.4 — Regent (L), the Star resource.**
- a) **Star primitive**: `stars` on combat state, gain/lose, star-cost
  playability + excess-energy-paid-in-stars, star obs dim. (M)
- b) Regent 88 cards (~3 sub-batches; star-cost + star-gen cards). (L)
- c) Regent 8 relics + `DivineRight`. (S)
- d) Powers (`StarNextTurnPower`, `DyingStarPower`, `ChildOfTheStarsPower`,
  `RoyaltiesPower`). (M)
- e) Tests: `tests/stars/`, `tests/regent/`. (M)

**P9.5 — Shared-pool + potion + event audit (M).** Re-audit `SharedRelicPool`
(118), `EventRelicPool` (137), `SharedPotionPool` (45), and shared events for
character-gated effects now that all five are wired; close any per-character
fidelity gaps. Per-character fidelity scorecards to 100%.

**P9.6 — Mod parity (BLOCKED on user Unity/Godot build).** Update
`McpMod.ObsBuilder.cs` + `McpMod.StateBuilder.cs` to emit the v5 character block
(orbs/stars/osty/poison/char-id), rebuild the mod, re-export ONNX. Required only
for **live deployment**, not for in-sim training.

**P9.7 — Training (per §6).** Character-conditioned agent: warm-start from the
Ironclad base (pad obs 504→560), curriculum-add characters as each lands,
eval per-character A10 win-rate.

### Rough total

- New content: ~352 character cards + ~36 character relics + ~60–100 powers +
  3 major primitives (orbs L, osty M–L, stars M) + 1 minor (poison/shiv).
- Estimated **~18–24 implementation batches** (vs the Ironclad campaign's
  Phase 7/8 batch cadence), the orb system being the single largest.
- Obs/action: obs `504 → 560` (v5, additive tail); action space stays
  `Discrete(300)` (reserved tail covers any `orb_select`).

---

## Appendix — key decompiled refs

- Character defs: `decompiled/MegaCrit.Sts2.Core.Models.Characters/{Ironclad,Silent,Defect,Necrobinder,Regent,Deprived,RandomCharacter,DeprecatedCharacter}.cs`
- Base: `decompiled/MegaCrit.Sts2.Core.Models/CharacterModel.cs`
- Orbs: `decompiled/MegaCrit.Sts2.Core.Entities.Orbs/OrbQueue.cs`,
  `decompiled/MegaCrit.Sts2.Core.Models/OrbModel.cs`,
  `decompiled/MegaCrit.Sts2.Core.Models.Orbs/{Lightning,Frost,Dark,Plasma,Glass}Orb.cs`
- Stars: `decompiled/MegaCrit.Sts2.Core.Entities.Players/PlayerCombatState.cs`,
  `decompiled/MegaCrit.Sts2.Core.Models.Powers/StarNextTurnPower.cs`,
  `decompiled/MegaCrit.Sts2.Core.Models.Cards/FallingStar.cs`
- Osty: `decompiled/MegaCrit.Sts2.Core.Models.Monsters/Osty.cs`,
  `decompiled/MegaCrit.Sts2.Core.Commands/OstyCmd.cs`,
  `decompiled/MegaCrit.Sts2.Core.Models.Powers/MinionPower.cs`,
  `decompiled/MegaCrit.Sts2.Core.Models.Cards/{Bodyguard,Unleash}.cs`
- Silent: `decompiled/MegaCrit.Sts2.Core.Models.Cards/{Shiv,Neutralize,Survivor,DeadlyPoison,PoisonedStab}.cs`,
  `decompiled/MegaCrit.Sts2.Core.Models.Powers/{PoisonPower,AccuracyPower}.cs`
- Pools: `decompiled/MegaCrit.Sts2.Core.Models.{CardPools,RelicPools,PotionPools}/`
- Sim entry points: `sim/game_state.py` (Character enum line 67, factory 205),
  `sim/env_run.py` (OBS_DIM 504 line 45, action space line 347),
  `sim/action_space.py` (RANGES 61, N_ACTIONS 165), `sim/cards.py`,
  `sim/card_catalog.py`, `sim/relics.py`, `sim/rewards.py`, `sim/combat.py`,
  `sim/powers.py`, `sim/damage.py`, `sim/creatures.py`
- Mod parity: `tools/STS2MCP-src/McpMod.ObsBuilder.cs`
- Launch: `scripts/launch_train.ps1`, `scripts/train_v3.py`

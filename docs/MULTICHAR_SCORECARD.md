# Multi-Character Fidelity Scorecard

Date: 2026-06-01
Status: **Phase 9.4 (Regent + Stars resource) complete — ALL 5 CHARACTERS'
CORE MECHANICS DONE.** Ironclad (100%), Silent (P9.1), Defect (P9.2, orbs),
Necrobinder (P9.3, Osty), and Regent (P9.4, Stars) are all faithful. obs v5
(504 -> 560) with the orb/focus/osty/poison/star slots now fully live.

See `docs/MULTICHAR_FIDELITY_PLAN.md` for the authoritative plan (roster,
obs v5 layout, primitives, batch order) and `docs/FIDELITY_AUDIT.md` for the
Ironclad critical-path audit.

---

## Per-character status

| Character   | Start setup | Card pool | Relics | Primitive | Critical-path fidelity | Batch |
|-------------|:-----------:|:---------:|:------:|:---------:|:----------------------:|:-----:|
| Ironclad    | done | done (87) | done | n/a | **100%** (Ironclad audit) | shipped |
| Silent      | done | **65/88 faithful** (+Shiv token; 22 by-type placeholders) | **8/8** | **poison/shiv/discard DONE** | faithful | **P9.1 shipped** |
| Defect      | done | **86/88 faithful** (2 transform/persistent-block placeholders) | **8/8** | **orb system DONE** | faithful | **P9.2 shipped** |
| Necrobinder | done | **66/88 faithful** (22 by-type placeholders) | **8/8** | **osty minion DONE** | faithful | **P9.3 shipped** |
| Regent      | done | **50/88 faithful** (38 by-type placeholders) | **8/8** | **stars DONE** | faithful | **P9.4 shipped** |
| Deprived    | fixture | fallback | fallback | n/a | debug fixture (not a target) | n/a |

"scaffold" = the character can be constructed, reset, masked, and stepped at
A0 (its starting HP / gold / relic / deck / energy / orb-slot count are
faithful), but its signature cards/relics/powers are TODO stubs with no real
effect.

---

## What P9.0 (scaffold) delivered

### obs v5 (504 -> 560), additive tail
The v4.4 layout `[0..504)` is **byte-identical** for Ironclad (verified by
`tests/test_multichar_scaffold.py` + the existing shop-obs tests, which now
anchor on `OBS_DIM_V4_4 = 504`). The new tail `[504..560)`:

| Indices | Dims | Field | Filled by |
|---------|-----:|-------|-----------|
| `[504..510)` | 6 | character one-hot (ironclad/silent/defect/necrobinder/regent + pad) | **P9.0 (live)** |
| `[510..511)` | 1 | star resource / 10 | **P9.4 (live)** |
| `[511..521)` | 10 | orb-queue slot type-ids / 5 | **P9.2 (live)** |
| `[521..531)` | 10 | orb-queue evoke values / 30 | **P9.2 (live)** |
| `[531..532)` | 1 | orb capacity / 10 | **P9.2 (live)** |
| `[532..533)` | 1 | focus / 10 | **P9.2 (live)** |
| `[533..537)` | 4 | osty present / hp / block / pad | **P9.3 (live)** |
| `[537..541)` | 4 | per-enemy poison / 20 | **P9.1 (live)** |
| `[541..560)` | 19 | pad to a clean 560 | — |

Only the character one-hot carries a value in P9.0; every mechanic slot is 0
until its batch lands. Ironclad's whole tail is 0 except the `[504]` bit.

### Per-character starting setup (`sim/game_state.py`)
StartHP (Ironclad 80 / Silent 70 / Defect 75 / Necrobinder 66 / Regent 75),
StartGold 99, base energy 3, orb-slot count (Defect 3, else 0), starting relic,
and starting deck are now dispatched off the `Character` enum. Non-Ironclad
signature starter cards/relics are faithful-shaped **TODO stubs** (no
fabricated effects) so `new_run` never crashes.

### Per-character pools (`sim/card_catalog.py`, `sim/relics.py`, `sim/rewards.py`)
`CHARACTER_CARD_POOLS` (card-reward pool) and `_CHARACTER_RELIC_POOL_IDS`
(character-exclusive relics) are keyed by character. Ironclad is fully
populated; the other four are empty and **fall back to the Ironclad pool**
during scaffold training so the card-reward path never produces an empty /
crashing reward. `generate_card_reward(..., character=...)` selects the pool.

### Warm-start padding (`scripts/train_v3.py`)
`pad_state_dict_for_obs_change` zero-pads any first-layer weight whose
in_features == 504 out to 560; `warm_start_load` tries a plain
`MaskablePPO.load` and falls back to the padded graft on shape mismatch. A
504-dim Ironclad checkpoint (h21b/h24) warm-starts into the 560-dim v5 obs
with bit-identical Ironclad logits at step 0. `--characters` CSV flag added
(P9.0 uses the first; full per-episode sampling is P9.7).

---

## P9.1 (Silent) — what shipped

### Signature mechanics (faithful, decompiled refs)
- **Poison** (`PoisonPower.cs`): stacking DoT; ticks at the owner's turn start
  (`apply_poison_tick`, already wired in combat) for `stacks` Unblockable damage,
  then −1. Stacks additively; falls off at 1. Per-enemy poison now populates the
  obs v5 slot `[537..541)` (poison/20, alive-enemy order).
- **Shiv** (`Shiv.cs`): 0-cost Attack token, 4 dmg, Exhaust (upgrade +2). Generated
  by Blade Dance (3), Cloak and Dagger (1), Fan of Knives (4), Infinite Blades
  (1/turn), Ninja Scroll relic (3 turn-1). **Accuracy** (`AccuracyPower.cs`) adds
  +amount damage to Shiv-tagged attacks only (verified: boosts Shiv, not Strike).
- **Discard** (new `on_discard` hook): added `_discard_card_from_hand` +
  `on_card_discarded` power hook + `on_card_discarded` relic hook. Survivor /
  Acrobatics / Prepared / Dagger Throw / Calculated Gamble discard; Tingsha (3
  dmg) and Tough Bandages (3 block) pay off on discard; Memento Mori scales with
  cards discarded this turn; Murder with cards drawn this turn.

### Cards: 65/88 faithful (+Shiv) ; 22 by-type placeholders
Placeholders carry **faithful cost/type/rarity** (from each `.cs` `base(...)`)
but defer their effect because they need an absent card-selection / branching
primitive (hand-select-to-discard targeting, on-discard card transforms,
intangible/wraith). Deferred: abrasive, blade_of_ink, bullet_time,
corrosive_wave, expose, flanking, hand_trick, hidden_daggers, knife_trap,
malaise, master_planner, mirage, nightmare, precise_cut, reflex, shadow_step,
shadowmeld, storm_of_steel, suppress, untouchable, up_my_sleeve, wraith_form.

### Relics: 8/8 (`SilentRelicPool.cs`)
RingOfTheSnake (+2 hand draw turn 1, real `ModifyHandDraw`), HelicalDart (+1
Temp Dex on Shiv play), NinjaScroll (3 Shivs turn 1), PaperKrane (Weak-mult
modifier — faithful no-op, primitive absent), SneckoSkull (+1 Poison given,
wired into APPLY_POWER), Tingsha (3 dmg on discard), ToughBandages (3 block on
discard), TwistedFunnel (already in EventRelicPool). Gated OUT of cross-character
reward pools so Silent relics never drop for Ironclad.

### Powers (Silent-unique, decompiled)
OutbreakPower (every-3rd-poison AoE), InfiniteBladesPower (turn-start Shiv),
SerpentFormPower (per-card-play random dmg), AccelerantPower, AccuracyPower
(reused), EnvenomPower (reused), NoxiousFumesPower (reused), PhantomBladesPower,
SpeedsterPower, SneakyPower (multiplayer-only no-op), ToolsOfTheTradePower
(draw+discard turn start), WellLaidPlansPower (persistent retain), plus reused
Blur/Dexterity/Weak/Burst/Strangle/PiercingWail.

## P9.2 (Defect) — what shipped

### Orb system (new primitive, faithful — `sim/orbs.py` + `sim/combat.py`)
- **OrbQueue** (`OrbQueue.cs`): capacity (Defect base 3, hard max 10); channel
  appends; channeling into a FULL queue evokes the front (oldest) orb first
  (OrbCmd.Channel overflow). `add_orb_slots` (Capacitor/RunicCapacitor).
- **Five orb types** (`Models.Orbs/*.cs`), decompile-exact:
  Lightning (passive 3 / evoke 8, random enemy), Frost (passive 2 / evoke 5
  block), Dark (passive +6 ACCUMULATES into evoke_val base 6; evoke hits the
  lowest-HP enemy for the total), Plasma (passive +1 / evoke +2 energy,
  **Focus-immune**), Glass (passive 4 to ALL then −1; evoke = passive×2 to ALL).
- **Focus** (`FocusPower.cs`): ModifyOrbValue -> max(value+Amount, 0). Scales
  Lightning/Frost/Dark/Glass passive+evoke; **Plasma ignores Focus** (verified
  against PlasmaOrb.cs returning raw 1m/2m). TemporaryFocus (Hotfix/FocusedStrike)
  decays at turn end.
- **Passive timing** (`OrbQueue.BeforeTurnEnd` / `AfterTurnStart`): Lightning/
  Frost/Dark/Glass fire at player turn END (after the turn-end power hooks);
  Plasma fires at player turn START. Each orb fires `triggerCount` times
  (GoldPlatedCables +1 for the front orb via ModifyOrbPassiveTriggerCount).
- Channel/evoke are CARD/RELIC-DRIVEN (no free-standing orb action — action
  space stays Discrete(300)). New DSL ops: channel_orb, evoke_orb,
  evoke_all_orbs, add_orb_slots, channel_orb_per_enemy, channel_orb_x,
  damage_hits_per_orb, gain_energy_per_current. obs v5 orb slots [511..533) live.

### Cards: 86/88 faithful ; 2 by-type placeholders
Start deck (Defect.cs): 4× StrikeDefect, 4× DefendDefect, 1× Zap (channel 1
Lightning), 1× Dualcast (evoke front orb ×2). Placeholders (need an absent
transform / persistent-block primitive): **modded, genetic_algorithm**. All
others carry exact cost/damage/block/orb-effect/upgrade.

### Relics: 8/8 (`DefectRelicPool.cs`)
CrackedCore (channel 1 Lightning turn 1 — starter), DataDisk (+1 Focus on combat
enter), EmotionChip (re-fire all orb passives at turn start if HP lost last
turn), GoldPlatedCables (front orb +1 passive trigger), PowerCell (+2 hand draw
turn 1), Metronome (every 7th orb channeled -> 30 AoE), RunicCapacitor (+3 orb
slots turn 1), SymbioticVirus (channel 1 Dark turn 1). Gated to the Defect
character-relic pool (7 droppable; CrackedCore is the starter).

### Powers (Defect-unique, decompiled)
FocusPower, TemporaryFocusPower (Hotfix/FocusedStrike), ThunderPower (dmg on
evoke), StormPower (channel Lightning on Power play), HailstormPower (AoE per
Frost orb), CoolantPower (block per Frost orb), SmokestackPower (turn-end AoE),
LoopPower (retrigger front orb at turn start), EchoFormPower (replay first card),
CreativeAiPower (add a Power each turn), FeralPower, IterationPower,
MachineLearningPower (+draw), SignalBoostPower, SpinnerPower (channel Glass on
attack), SubroutinePower, ConsumingShadowPower, TrashToTreasurePower,
BiasedCognitionPower (Focus over time). Buffer reuses the shared BufferPower.

### Tests
`tests/test_defect_orbs.py` (16) + `tests/test_defect_cards.py` (32): orb
value model + Focus scaling (and Plasma immunity), capacity/channel/overflow,
per-orb passive timing + evoke with exact values, signature cards (Zap/Dualcast/
BallLightning/ColdSnap/Glacier/Chill/Capacitor/Tempest/Barrage/MultiCast/
DoubleEnergy/Rainbow), powers (Thunder/Storm/Loop/Hailstorm/BiasedCognition),
upgrades, CrackedCore + relic pool, the 88-card pool, and an A0 RunEnv(Defect)
integration run reaching deep floors.

## P9.3 (Necrobinder) — what shipped

### Osty minion (new primitive, faithful — `sim/osty.py` + `sim/combat.py`)
- **Osty** (`Osty.cs`): a persistent FRIENDLY creature on `cs.osty` with its own
  HP/block; MinInitialHp==MaxInitialHp==1; NOTHING_MOVE (never acts on its own).
  Re-created per combat (does NOT carry between combats — verified: Player.Osty
  is the combat pet, reset each encounter).
- **Summon** (`OstyCmd.Summon`): amount 0 = no-op; if Osty ALIVE -> GainMaxHp
  (raise maxHp + heal by amount); if MISSING -> SetMaxHp(amount); Heal(amount) +
  attach DieForYou. **Sacrifice** (`Sacrifice.cs`): block == Osty.MaxHp*2, then
  kill Osty. **Attack-for-HP** (`Unleash.cs`/`Protector.cs`): deal Osty.CurrentHp.
  **OstyAttack** cards (`Poke`/`Snap`/`SicEm`/`Flatten`/`BoneShards`/`HighFive`/
  `Rattle`/`Fetch`/`RightHandHand`): deal a base value, gated on Osty alive.
- **DieForYou taunt** (`DieForYouPower.cs`): a POWERED enemy attack aimed at the
  player is redirected to the living Osty (wired in `damage.deal_damage` via the
  player's `_osty_guardian`); unpowered hits are not redirected.
- **NecroMastery** (`NecroMasteryPower.cs`): when Osty loses HP, deal hp_lost ×
  stacks Unblockable to ALL enemies (fired from `deal_damage` + on sacrifice).
- **Doom** (`DoomPower`, reused): execute-threshold debuff; an enemy at HP <= its
  Doom dies at its turn end (Scourge 13 / Oblivion 3 / Deathbringer 21 / End of
  Days 29 immediate / NegativePulse 7). obs v5 osty slots `[533..537)` live.

### Cards: 66/88 faithful ; 22 by-type placeholders
Start deck (Necrobinder.cs): 4× StrikeNecrobinder, 4× DefendNecrobinder, 1×
Bodyguard (Summon 5), 1× Unleash (deal Osty HP). Placeholders need an absent
primitive (Soul token gen, card-select-exhaust, Ethereal gen, X-cost summon
loop, History-count scaling): borrowed_time, call_of_the_void, death_march,
dredge, forbidden_grimoire, glimpse_beyond, neurosurge, no_escape, pagestorm,
parse, pull_from_below, reaper_form, seance, sentry_mode, sleight_of_flesh,
soul_storm, the_scythe (partial), times_up, transfigure, undeath, wisp, sow.
All others carry exact cost/damage/block/summon/doom/upgrade.

### Relics: 8/8 (`NecrobinderRelicPool.cs`)
BoundPhylactery (starter: Summon 1 at combat start + every round after 1),
BoneFlute (+2 block on Osty attack), IvoryTile (+1 energy when a card spends >=3
energy), BigHat / FuneraryMask / BookRepairKnife / Bookmark / UndyingSigil
(faithful no-op markers — Soul/Ethereal gen, doom-death heal, retain-cost,
incoming-damage ×0.5 primitives absent). Gated OUT of cross-character pools.

### Powers (Necrobinder-unique, decompiled)
MinionPower, DieForYouPower, NecroMasteryPower, SummonNextTurnPower (Invoke),
HauntPower (per-card AoE), CalcifyPower (+dmg), LethalityPower (+% dmg),
FriendshipPower (+max energy), DemesnePower (+draw/+energy), DanseMacabrePower /
SpiritOfAshPower (block per card), DevourLifePower (Summon per card). Doom
reuses the shared DoomPower; Eidolon reuses IntangiblePower.

### Tests
`tests/test_necrobinder_osty.py` (24) + `tests/test_necrobinder_cards.py` (20):
summon/persist/grow/revive, DieForYou taunt (powered redirect, unpowered not),
NecroMastery scaling, sacrifice (MaxHp*2 + kill), SummonNextTurn, BoundPhylactery
combat-start + per-round summon, obs osty slots (present/hp; zero for Ironclad),
signature cards (Bodyguard/Unleash/Poke/Snap/BoneShards/SicEm/Reanimate/Spur/
PullAggro/Sacrifice/NecroMastery), Doom cards (Scourge/EndOfDays/turn-end kill),
the 88-card pool + reward keying, relic pool + BoneFlute/IvoryTile, and an A0
RunEnv(Necrobinder) integration run reaching deep floors.

## P9.4 (Regent) — what shipped

### Star resource (new primitive, faithful — `sim/combat.py`)
- **Stars** (`PlayerCombatState.cs:70-182`): an int counter on `cs.stars`,
  `gain_stars`/`lose_stars` (clamped >= 0, no upper cap — matches GainStars/
  LoseStars which only floor at 0). **Persists for the whole combat** (NOT reset
  per turn — verified: no per-turn reset in PlayerCombatState; reset to 0 at
  combat start). Per-character: 0 for non-Regent.
- **Star-cost playability + spend** (`HasEnoughResourcesFor` / `SpendResources`,
  CardModel.cs:146-165, 1397-1410): a card is playable iff `energy >= energy_cost
  AND stars >= star_cost`; both are spent on play (stars first, firing
  AfterStarsSpent before the card resolves). `CardDef.star_cost` carries each
  card's CanonicalStarCost (FallingStar 2, GuidingStar 2, Comet 5, SevenStars 7,
  …).
- **Excess-energy-paid-with-stars** (`ShouldPayExcessEnergyCostWithStars`,
  Hook.cs:1816): off by default (no obtainable Regent card/relic in the pool
  grants it); when a power flags it, each missing energy is paid at **2 stars**
  (`star_cost += (energy_cost - energy) * 2`, energy spend capped at current
  energy) — modeled exactly and unit-tested via a fixture power.
- **obs v5 star slot `[510..511)`** = stars / 10 (live; zero for non-Regent).

### Cards: 50/88 faithful ; 38 by-type placeholders
Start deck (Regent.cs): 4× StrikeRegent (6 dmg), 4× DefendRegent (5 block),
1× FallingStar (0 energy / star 2, 8 dmg + Weak + Vuln), 1× Venerate (GainStars
2). Implemented signature/star cards carry .cs-exact cost/star-cost/damage/block/
star-gain/upgrade: SolarStrike, ShiningStrike, GuidingStar, KnockoutBlow,
CelestialMight (×3), Comet (33 / star 5), SevenStars (7×7 / star 7), DyingStar,
GammaBlast, AstralPulse, MeteorShower, CloakOfStars, GatherLight, Glow,
HiddenCache (StarNextTurn 3), ChildOfTheStars, Tyranny, Stardust, etc.
Placeholders (faithful cost/type/rarity, deferred — need an absent primitive:
Forge upgrade-in-combat, card-select/retain, history-count scaling, colorless
gen, SovereignBlade/Minion token): arsenal, beat_into_shape, begone, big_bang,
black_hole, bundle_of_joy, charge, conqueror, convergence, crash_landing,
decisions_decisions, foregone_conclusion, furnace, genesis, guards,
i_am_invincible, know_thy_place, largesse, manifest_authority, monarchs_gaze,
monologue, neutron_aegis, orbit, pale_blue_dot, parry, pillar_of_creation,
prophesize, royal_gamble, royalties, seeking_edge, spectrum_shift, summon_forth,
terraforming, the_sealed_throne, the_smith, void_form (cost-zero power partially
modeled), + 2 more.

### Relics: 8/8 (`RegentRelicPool.cs`)
DivineRight (starter: GainStars 3 on combat enter), GalacticDust (every 10 stars
spent -> 10 block), LunarPastry (+1 star at turn end), MiniRegent (first
star-spend each turn -> +1 Strength), Regalite (+2 block whenever a card enters
combat). FencingManual (Forge 10), OrangeDough (2 colorless cards turn 1), and
VitruvianMinion (Minion-card ×2 dmg/block) are faithful no-op markers
(Forge / colorless-gen / Minion-tag primitives absent). Gated to the Regent
character-relic pool (7 droppable; DivineRight is the starter).

### Powers (Regent-unique, decompiled)
StarNextTurnPower (AfterEnergyReset -> GainStars + Remove), ChildOfTheStarsPower
(AfterStarsSpent -> block per star spent), TyrannyPower (+draw + exhaust at turn
start), VoidFormPower (first N cards/turn cost 0 energy AND 0 stars),
ConquerorPower / RoyaltiesPower (registered, faithful-shaped; SovereignBlade /
combat-end-gold paths partially modeled). DyingStar reuses Weak; FallingStar/
Comet/GammaBlast reuse Weak/Vulnerable.

### Tests
`tests/test_regent_stars.py` (20) + `tests/test_regent_cards.py` (29): stars
gain/lose/clamp/persistence, star-cost playability + spend with exact values,
excess-energy-paid-in-stars (2/energy, partial), StarNextTurn / ChildOfTheStars /
VoidForm powers, DivineRight 3-star starter, obs star slot (set / zero for
Ironclad), start deck, signature + star cards (FallingStar/Venerate/SolarStrike/
GuidingStar/Comet/SevenStars/DyingStar/GammaBlast/AstralPulse/KnockoutBlow/
ShiningStrike/CelestialMight/CloakOfStars/GatherLight/Glow/HiddenCache/
ChildOfTheStars/MeteorShower), the 88-card pool + reward keying, relic pool +
GalacticDust/MiniRegent/LunarPastry/Regalite, and an A0 RunEnv(Regent)
integration run reaching deep floors.

## Known TODOs flagged in code (next batches)

- `P9.1 deferred` Silent: 22 cards needing a card-selection/transform primitive
  (see list above) + PaperKrane's Weak-multiplier modifier.
- `P9.2 deferred` Defect: 2 cards (modded transform-status, genetic_algorithm
  persistent-block) need an absent primitive.
- `P9.3 deferred` Necrobinder: 22 cards needing an absent primitive (Soul token
  gen, card-select-exhaust, Ethereal card gen, X-cost summon loop, History-count
  damage scaling) + 4 relics that are faithful no-op markers (BigHat/FuneraryMask
  Soul/Ethereal gen, BookRepairKnife doom-death heal, Bookmark retain-cost,
  UndyingSigil incoming-damage ×0.5 — primitives absent).
- `P9.4 deferred` Regent: 38 cards needing an absent primitive (Forge
  upgrade-in-combat, card-select/retain, history-count damage scaling, colorless
  card gen, SovereignBlade/Minion token) land as faithful by-type placeholders +
  3 relics that are faithful no-op markers (FencingManual Forge, OrangeDough
  colorless-gen, VitruvianMinion Minion-tag — primitives absent).

---

## Mod parity (BLOCKED — user Unity/Godot build)

The OBS_DIM change 504 -> 560 means `tools/STS2MCP-src/McpMod.ObsBuilder.cs`
(the C# obs mirror) is now **out of parity** with the sim. The mod must emit
the v5 tail (character id + orb/star/osty/poison) identically before any
multi-character model can be deployed live. This requires a Unity/Godot mod
rebuild + ONNX re-export (P9.6) and is a **user task** — the C#/Steam folder
was intentionally NOT edited in this batch. Multi-character models can be
trained and evaluated **in-sim** in the meantime.

# Multi-Character Fidelity Scorecard

Date: 2026-06-01
Status: **Phase 9.2 (Defect + orb system) complete.** Ironclad (100%), Silent
(P9.1), and Defect (P9.2, orb system) are faithful; Necrobinder/Regent remain
scaffold-only. obs v5 (504 -> 560) with the orb/focus slots now live.

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
| Necrobinder | scaffold | TODO (88) | TODO (8) | **osty** TODO | scaffold-only | P9.3 |
| Regent      | scaffold | TODO (88) | TODO (8) | **stars** TODO | scaffold-only | P9.4 |
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
| `[510..511)` | 1 | star resource / 10 | P9.4 |
| `[511..521)` | 10 | orb-queue slot type-ids / 5 | **P9.2 (live)** |
| `[521..531)` | 10 | orb-queue evoke values / 30 | **P9.2 (live)** |
| `[531..532)` | 1 | orb capacity / 10 | **P9.2 (live)** |
| `[532..533)` | 1 | focus / 10 | **P9.2 (live)** |
| `[533..537)` | 4 | osty present / hp / block / pad | P9.3 |
| `[537..541)` | 4 | per-enemy poison / 20 | P9.1 |
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

## Known TODOs flagged in code (next batches)

- `P9.1 deferred` Silent: 22 cards needing a card-selection/transform primitive
  (see list above) + PaperKrane's Weak-multiplier modifier.
- `P9.2 deferred` Defect: 2 cards (modded transform-status, genetic_algorithm
  persistent-block) need an absent primitive.
- `TODO(P9.3)` Necrobinder: Osty minion primitive, Bodyguard/Unleash,
  BoundPhylactery, MinionPower, 88 cards, 8 relics, obs osty slots.
- `TODO(P9.4)` Regent: Star resource primitive, FallingStar/Venerate,
  DivineRight, star powers, 88 cards, 8 relics, obs star slot.

---

## Mod parity (BLOCKED — user Unity/Godot build)

The OBS_DIM change 504 -> 560 means `tools/STS2MCP-src/McpMod.ObsBuilder.cs`
(the C# obs mirror) is now **out of parity** with the sim. The mod must emit
the v5 tail (character id + orb/star/osty/poison) identically before any
multi-character model can be deployed live. This requires a Unity/Godot mod
rebuild + ONNX re-export (P9.6) and is a **user task** — the C#/Steam folder
was intentionally NOT edited in this batch. Multi-character models can be
trained and evaluated **in-sim** in the meantime.

# Relic catalog — 80 most-common relics (Cycle B reference)

Source: Phase-A4 sweep on `decompiled/MegaCrit.Sts2.Core.Models.Relics/*.cs`.
Verified 2026-05-24.

For full details see the agent output transcript; this file captures the
porting-priority and hook-mapping needed by `sim/relics.py`.

## Group A — Portable now (≈58 relics)

Use only basic hooks already supported (or trivially add).

| Hook | Relics |
|---|---|
| AfterCombatVictory | BurningBlood (heal 6), BlackBlood (heal 12) |
| AfterRoomEntered(CombatRoom) | Vajra (+1 Str), OddlySmoothStone (+1 Dex), BronzeScales (+3 Thorns), DataDisk (+1 Focus), Gorget (+4 Plating), DivineRight (+3 Stars), FestivePopper (turn-1 dmg 9 to all) |
| AfterRoomEntered(RestSiteRoom) | MealTicket (heal 15), EternalFeather (heal +3 per 5 deck cards) |
| AfterRoomEntered(Boss) | Pantograph (heal 25) |
| BeforeCombatStart | Anchor (+10 block) |
| BeforeSideTurnStart(round 1) | BagOfMarbles (Vuln 1 all), RedMask (Weak 1 all), TwistedFunnel (Poison 4 all), SymbioticVirus (1 Dark Orb — defer) |
| AfterSideTurnStart(round 1) | Lantern (+1 energy), Akabeko (+8 Vigor), FencingManual (defer), RingOfTheSnake (+2 draw turn 1) |
| ModifyHandDraw | BagOfPreparation (+2 turn 1), RingOfTheDrake (+2 first 3 turns), Pendulum (+1 every 3 turns) |
| AfterPlayerTurnStart | MercuryHourglass (3 dmg all every turn), BloodVial (heal 2 turn 1) |
| AfterDamageReceived(unblocked) | CentennialPuzzle (draw 3 once/combat), SelfFormingClay (defer) |
| AfterDeath | GremlinHorn (+1 energy + draw 1) |
| AfterCardPlayed(every Nth Attack) | Kusarigama (6 dmg/3 attacks), OrnamentalFan (+4 block/3 attacks), Nunchaku (+1 energy/10 attacks), PenNib (2× dmg on 10th attack) |
| AfterCardPlayed(every Nth Skill) | LetterOpener (5 dmg all/3 skills), TuningFork (+7 block/10 skills) |
| ModifyDamageAdditive | StrikeDummy (+3 to Strike), MiniatureCannon (+3 to upgraded Attacks) |
| ModifyDamageMultiplicative | PaperPhrog (+25% vs Vulnerable) |
| AfterCurrentHpChanged | RedSkull (3 Str when ≤50% HP) |
| AfterBlockCleared | HornCleat (+14 block on turn 2 when cleared), SparklingRouge (1 Str + 1 Dex on turn 3) |
| BeforeTurnEnd | Orichalcum (+6 block if 0 block) |
| AfterTurnEnd | ParryingShield (6 dmg if block ≥ 10) |
| AfterCardDiscarded | Tingsha (3 dmg random) |
| AfterCardExhausted | JossPaper (draw per 5 exhausted) |
| AfterObtained | Strawberry (+7 max HP), Pear (+10 max HP), PotionBelt (+2 potion slots), WarPaint/Whetstone (defer — card upgrade) |

## Group B — Defer (requires DSL extension, ~22 relics)

Pets (BoundPhylactery, PhylacteryUnbound, BoneFlute), Orbs (CrackedCore, InfusedCore, GoldPlatedCables), card-pile rewards (BookOfFiveRings, LuckyFysh), card upgrade hooks (WarPaint, Whetstone, FencingManual, StoneCracker), map mods (JuzuBracelet, Planisphere), reward mods (AmethystAubergine, BowlerHat, LastingCandy, TinyMailbox, PetrifiedToad).

## Power dependencies (priority order for `sim/powers.py`)

Tier 1 (multi-relic / multi-card): **StrengthPower** ✓, **VulnerablePower** ✓, **WeakPower** ✓, **DexterityPower**, **FrailPower**, **PoisonPower**, **ThornsPower**, **PlatingPower**, **FocusPower**.

Tier 2: VigorPower, RagePower, RupturePower, FeelNoPainPower, ColossusPower, JugglingPower, AggressionPower, BarricadePower, ViciousPower, InfernoPower, DrumOfBattlePower.

Tier 3 (single-card rare): CrueltyPower, CrimsonMantlePower, DarkEmbracePower, DemonFormPower, ManglePower, JuggernautPower, OneTwoPunchPower, HellraiserPower, PyrePower, TankPower, UnmovablePower, FlameBarrierPower, NoDrawPower, FreeAttackPower, NoEnergyGainPower.

## Initial implementation plan

`sim/relics.py` should expose:
```python
@dataclass(frozen=True)
class RelicDef:
    id: str
    rarity: RelicRarity
    hooks: dict[str, Callable[[RunState, dict | None], None]]
    merchant_cost: int = 0

RELIC_REGISTRY: dict[str, RelicDef] = {
    "BURNING_BLOOD": RelicDef(..., hooks={"after_combat_victory": lambda rs, ctx: rs.heal(6)}),
    "VAJRA": RelicDef(..., hooks={"on_combat_start": lambda rs, cs: cs.player.add_or_stack_power(make_power("strength", 1, cs.player))}),
    "ANCHOR": RelicDef(..., hooks={"on_combat_start": lambda rs, cs: gain_block(cs.player, 10)}),
    "BLOOD_VIAL": RelicDef(..., hooks={"on_player_turn_start": lambda rs, cs: rs.heal(2) if cs.turn_number == 1 else None}),
    ...
}
```

The run_engine drives hooks at the correct lifecycle points; combat.py
checks `rs.relics` and calls on-combat-start / on-turn-start hooks.

# Card Effect Operations — DSL Extension Reference (Cycle B)

Source: Phase-A sweeps on `decompiled/MegaCrit.Sts2.Core.Models.Cards/*.cs`.
Verified 2026-05-24.

Spec for the EffectOp / Target additions in `sim/dsl.py` and the new
branches in `sim/combat.py::_resolve_single_effect`.

## New EffectOps

| Op | Used by (cards) | Semantics |
|---|---|---|
| `DRAW_CARD` | PommelStrike, ShrugItOff, BattleTrance, DrumOfBattle, BurningPact | `self.draw(amount)` |
| `ENERGY_GAIN` | Bloodletting, ExpectAFight, Offering | `self.player.energy += amount` |
| `SELF_HP_LOSE` | Bloodletting (3), Bloodwall (2), Breakthrough (1), Hemokinesis (2), Brand (1), Offering (6) | Unblockable / unpowered; goes straight to HP via `player.lose_hp(amount)` |
| `EXHAUST_RANDOM` | Cinder | Pop one random hand card into exhaust pile |
| `EXHAUST_SELF` | Tremble, BurningPact, TrueGrit, Brand, Cinder, InfernalBlade, Offering, NotYet, Impervious, FiendFire, HowlFromBeyond, PactsEnd | Move the just-played card from discard → exhaust |
| `COPY_TO_DISCARD` | Anger | Push a copy of the played card into discard |
| `UPGRADE_ALL_IN_HAND` | Armaments+ | Tag every hand card with `+` upgrade marker |
| `AUTO_PLAY_FROM_DRAW` | Havoc | Pop top of draw, resolve its effects, exhaust |

## New Targets

| Target | Used by | Semantics |
|---|---|---|
| `RANDOM_ENEMY` | SwordBoomerang | Single random alive enemy. With one monster, collapses to that monster. |

## New Scalings

| Scaling | Used by | Semantics |
|---|---|---|
| `BLOCK_AMOUNT` | BodySlam | Damage = current `player.block` (overrides base `amount`) |
| `STRIKE_TAG_COUNT` | PerfectedStrike | Damage = base + count of cards in deck whose id contains `"strike"` |

## hit_count field

Effect now takes `hit_count: int = 1`. Used by SwordBoomerang (3), TwinStrike (2), Dismantle (2 if Vulnerable), FightMe (2), Conflagration (variable), TearAsunder (variable), FiendFire (variable), KinPriest BEAM (3). For variable-count cards the DSL records the *base* hit_count; conditional bumps live in the card-specific branch.

## DSL Coverage Tiers (per `notes/10_card_rewards.md` Ironclad pool)

- **SIMPLE → portable now** (single EffectOp): Strike(済), Defend(済), Bash(済), IronWave(済), Inflame(済), Anger, BodySlam, PommelStrike, ShrugItOff, Tremble, TwinStrike, Thunderclap, Bloodletting, Cinder, Headbutt, MoltenFist, TrueGrit, Havoc, BattleTrance, Bludgeon, Colossus, DrumOfBattle, FeelNoPain, Inferno, Juggling, Rage, Rupture, StoneArmor, Vicious, Aggression, Barricade.
- **MEDIUM → needs new EffectOp or conditional logic**: Armaments, Bloodwall, Breakthrough, PerfectedStrike, SetupStrike, SwordBoomerang, AshenStrike, Bully, BurningPact, Dismantle, Dominate, ExpectAFight, FightMe, FlameBarrier, Pillage, Rampage, SecondWind, Spite, Stomp, Taunt, Brand, Conflagration, Cruelty, CrimsonMantle, DarkEmbrace, Feed, Hellraiser, Juggernaut, Mangle, NotYet, OneTwoPunch, Pyre, Tank, TearAsunder.
- **COMPLEX → deferred**: EvilEye, ForgottenRitual, Hemokinesis, HowlFromBeyond, InfernalBlade, Unrelenting, Uppercut, FiendFire, Impervious, Offering, DemonForm, PactsEnd, PrimalForce, Stoke, Thrash, Whirlwind.

## Powers Catalog (referenced by cards, 30 unique)

Already in `sim/powers.py`: Strength, Vulnerable, Weak.

To add (priority order by usage frequency):
- **Tier 1** (multi-card): NoDrawPower (BattleTrance), FreeAttackPower (Unrelenting), StrengthPower-source (DrumOfBattle, FightMe, Brand, Mangle).
- **Tier 2** (single-card commons/uncommons): ColossusPower, DrumOfBattlePower, FeelNoPainPower, InfernoPower, JugglingPower, RagePower, RupturePower, PlatingPower (StoneArmor), AggressionPower, BarricadePower, ViciousPower.
- **Tier 3** (rare-only, low priority): CrueltyPower, CrimsonMantlePower, DarkEmbracePower, DemonFormPower, ManglePower, JuggernautPower, OneTwoPunchPower, HellraiserPower, PyrePower, TankPower, UnmovablePower, FlameBarrierPower.
- **Game-internal**: NoEnergyGainPower (ExpectAFight; trivial).

Most Tier 1/2 are no-op stubs except for the few that modify damage (Strength variants) or block (Plating). Plug into `Power.modify_damage_additive/multiplicative` once added.

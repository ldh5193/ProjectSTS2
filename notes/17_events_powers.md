# Act-1 events + Power class catalog (Cycle B reference)

Source: Phase-A6 sweep.

## Act-1 events (13)

Per-event numeric effects ready to drop into `sim/events.py`.

| Event | IsAllowed | Options → Effects |
|---|---|---|
| AromaOfChaos | none | LET_GO: transform 1 deck card / MAINTAIN: upgrade 1 deck card |
| ByrdonisNest | !HasEventPet | EAT: +7 max HP / TAKE: +1 ByrdonisEgg card |
| DenseVegetation | shared | TRUDGE_ON: −8 HP + Rng.NextInt(61,101) gold / REST: full heal + combat |
| JungleMazeAdventure | shared | SOLO: −18 HP + 135-165 gold / JOIN: 35-65 gold |
| LuminousChoir | gold ≥ 99 + relics available | FLESH: remove 2 cards + SporeMind curse / TRIBUTE: −99-149 gold + 1 relic |
| MorphicGrove | gold ≥ 100 + ≥2 transformable | LONER: +5 max HP / GROUP: −all gold + transform 2 cards |
| SapphireSeed | none | EAT: +9 HP heal + upgrade 1 card / PLANT: enchant 1 card "Sown" |
| SunkenStatue | none | GRAB_SWORD: +1 SwordOfStone relic / DIVE: 101-121 gold + −7 HP |
| TabletOfTruth | none | SMASH: +20 HP / DECIPHER step N (1-5): −3/6/12/24/(maxHP-1) max HP + upgrade 1 random (all on step 4) |
| UnrestSite | HP ≤ 70% | REST: full heal + PoorSleep curse / KILL: −8 max HP + 1 relic |
| Wellspring | none | BOTTLE: +1 random potion / BATHE: remove 1 card + Guilty curse |
| WhisperingHollow | gold ≥ 44 | GOLD: −26-44 gold + 2 potions / HUG: transform 1 card + −9 HP |
| WoodCarvings | ≥1 basic removable | BIRD: → Peck / SNAKE: enchant Slither / TORUS: → ToricToughness |

All damage values are unblockable + unpowered.
Shared events apply to every player in MP.

## Powers catalog (19 core)

Already in `sim/powers.py`: Strength, Vulnerable, Weak.

| Power | Stack | Hooks | Effect |
|---|---|---|---|
| **Dexterity** | Counter | ModifyBlockAdditive | +amount block on powered block |
| **Frail** | Counter (duration) | ModifyBlockMultiplicative, AfterTurnEnd(enemy) | ×0.75 block on powered block |
| **Blur** | Counter | ShouldClearBlock=false, AfterSideTurnStart(player) | Block persists 1 turn |
| **BlockNextTurn** | Counter | AfterBlockCleared | Gain N block when block hits 0; one-shot |
| **Barricade** | Single | ShouldClearBlock=false | Block persists indefinitely |
| **Thorns** | Counter | BeforeDamageReceived(target=owner) | Reflect amount unblockable to attacker |
| **CurlUp** | Counter | AfterDamageReceived → AfterCardPlayed | When same card replays, +amount block, remove |
| **Ritual** | Counter | AfterTurnEnd(owner) | +amount Strength each turn end (skip first) |
| **Artifact** | Counter | TryModifyPowerAmountReceived | Block 1 incoming visible debuff per stack |
| **Confused** | Single | AfterCardDrawn | Random 0-3 cost on each drawn card |
| **Debilitate** | Counter | AfterTurnEnd(owner) | +50% Vuln dmg, -50% Weak dmg multipliers |
| **TempStrength** (abstract) | Counter | BeforeApplied, AfterTurnEnd | Expires at turn end + applies neg Str |
| **Asleep** | Counter | AfterDamageReceived, BeforeTurnEnd, AfterTurnEnd | Wake on damage / tick; LagavulinMatriarch-only |
| **Regen** | Counter | AfterTurnEnd(owner) | Heal amount, decrement |
| **EchoForm** | Counter | ModifyCardPlayCount | Replay first N cards/turn |
| **NoBlock** | Counter (duration) | ModifyBlockMultiplicative=0, AfterTurnEnd(enemy) | Powered block → 0 |
| **Plating** | Counter | (block-reduction resistance — when block cleared, retain some) | STS2 specific; relic Gorget grants |
| **Focus** | Counter | (orb passive boost — defer with orbs) | DataDisk relic, Defect-relevant |
| **Poison** | Counter | AfterTurnEnd(owner) | Damage = stack count; decrement |
| **Vigor** | Counter | Next attack +amount damage; remove after | Akabeko, BattleTrance interaction |

## Implementation priority

Tier 1 (block multi-card/relic effects): **Dexterity** (block), **Frail** (block debuff), **Thorns** (reflection), **Plating** (defense buff), **Poison** (DoT), **Vigor** (one-shot dmg buff).
Tier 2: Ritual, Artifact, Regen, Barricade, Blur.
Tier 3 (specific cards/bosses): Debilitate, EchoForm, NoBlock, Confused, TempStrength, Asleep, BlockNextTurn, CurlUp, Focus.

Tier 1 covers ~50% of relics + 20+ cards. Get those in next.

# Boss / Elite / Normal Monsters — Catalog (Cycle B reference)

Source: Phase-A4 (bosses/elites) + Phase-A5 (normals) sweeps.
Verified 2026-05-24.

Full per-monster move details are in the agent transcripts; this is the
HP / move-summary table used to seed `sim/monsters.py` and
`sim/encounter.py`.

## Act 1 — Overgrowth Bosses

### CeremonialBeast (262/252 HP)
5-state cycle: STAMP → PLOW (20/18 dmg + Str +2) → STUN → BEAST_CRY (Ringing) → STOMP (17/15) → CRUSH (19/17 dmg + Str +3/4). Initial: STAMP.

### TheKin (KinFollower×2 @62/58 + KinPriest @199/190)
KinFollower moves: QUICK_SLASH (5), BOOMERANG×2 (2), POWER_DANCE (Str +2/3). One starts with DANCE.
KinPriest moves: ORB_FRAILTY (9/8 dmg + Frail), ORB_WEAKNESS (9/8 + Weak), BEAM×3 (3 each), RITUAL (Str +2/3).

### Vantom (183/173 HP, starts +9 Slippery)
4-state: INK_BLOT (8/7) → INKY_LANCE×2 (7/6) → DISMEMBER (30/27 + 3 Wound to discard) → PREPARE (Str +2).

## Act 1 — Elites

| Elite | HP (Tough/Norm) | Move summary |
|---|---|---|
| BygoneEffigy | 132/127 | SLEEP → WAKE (Str +10) → SLASHES (15/13) repeat. Starts with Slow +1. |
| Byrdonis | 90/81 | PECK×3 (4/3) → SWOOP (19/17). Starts with Territorial +1. |
| PhrogParasite | 66/61 | LASH×4 (5/4), INFECT (3 Infection to discard). Starts with Infested +4. |

## Act 2 — Hive Bosses

### KaiserCrab (Crusher 219/209 + Rocket 209/199)
Crusher 5-cycle: THRASH (14/12), ENLARGING_STRIKE (4), BUG_STING×2 (7/6 + Weak +2 + Frail +2), ADAPT (Str +2/3), GUARDED_STRIKE (14/12 + Block 18). Powers: BackAttackLeft, CrabRage.
Rocket 5-cycle: RETICLE (4/3), PRECISION_BEAM (20/18), CHARGE_UP (Str +2/3), LASER (35/31), RECHARGE (sleep). Powers: Surrounded, BackAttackRight, CrabRage.

### KnowledgeDemon (399/379, IsBurnt flag)
Curse-counter branches:
- CURSE_OF_KNOWLEDGE (8/9/10 self-dmg via card choice 0/1/2)
- SLAP (18/17), KNOWLEDGE_OVERWHELMING×3 (9/8, sets Burnt), PONDER (13/11 + heal 30 × players + Str +2/3, clears Burnt).

### TheInsatiable (341/321, HasLiquified flag)
Cycle: LIQUIFY (SandpitPower + 6 FranticEscape) → THRASH1×2 (9/8) → LUNGING_BITE (31/28) → SALIVATE (Str +2/3) → THRASH2×2 (9/8) → BITE (repeat).

## Act 2 — Elites

| Elite | HP | Pattern |
|---|---|---|
| Decimillipede×3 (Front/Mid/Back) | 46/40-52/46 each, Reattach +25 | WRITHE×2 (6/5), BULK (7/6 + Str +2), CONSTRICT (9/8 + Weak +1). Revival on death. |
| Entomancer | 155/145 | PHEROMONE (PersonalHive+1 + Str+1, or Str+2 if Hive≥3), BEES×7-8 (3 ea), SPEAR (20/18). Starts PersonalHive +1. |
| InfestedPrism | 215/200, VitalSpark +1 | JAB (24/22), RADIATE (18/16 + 18 block), WHIRLWIND×3 (10/9), PULSATE (20/22 block + Str +4/5). |

## Act 3 — Glory Bosses

### Doormaker (HP hidden → 512/489 on DRAMATIC_OPEN)
DRAMATIC_OPEN → HUNGER (35/30) → SCRUTINY (26/24) → GRASP×2 (11/10 + Str +3/4) → HUNGER repeat. Power cycles HungerPower → ScrutinyPower → GraspPower.

### Queen (419/400) + TorchHeadAmalgam (211/199, Minion +1)
Queen normal: PUPPET_STRINGS (Chains +3) → YOUR_MINE (Frail/Weak/Vuln +99) → conditional [BURN_BRIGHT_FOR_ME (Str +1 allies, +20 block) if amalgam alive | OFF_WITH_YOUR_HEAD×5 (4/3) if dead] → EXECUTION (18/15) → ENRAGE (Str +2).
Amalgam 5-cycle: TACKLE1 (19/18), TACKLE2 (19/18), BEAM×3 (8), TACKLE3 (15/14), TACKLE4 (15/14).

### TestSubject (111/100 → 212/200 → 313/300, 3 phases)
Phase 1: BITE (22/20), SKULL_BASH (16/14 + Vuln +1). Starts Adaptable + Enrage +2/3.
Death triggers RESPAWN → Phase 2 (+PainfulStabs+1), Phase 3 (+Nemesis+1, removes Adaptable).
Phase 2+: MULTI_CLAW (11/10 × 3+ExtraCount), PHASE3_LACERATE×3 (11/10), BIG_POUNCE (45), BURNING_GROWL (3-5 Burn + Str +2/3).

## Act 3 — Elites

| Elite | HP | Pattern |
|---|---|---|
| Knights (Flail+Spectral+Magi) | 108/97/89 (Tough) | Flail: WAR_CHANT (Str+3), FLAIL×2 (10/9), RAM (17/15). Spectral: HEX (+2), SOUL_SLASH (17/15), SOUL_FLAME×3 (4/3). Magi 5-cycle: POWER_SHIELD (7/6 + block 5/9), DAMPEN (DampenPower), RAM (11/10), PREP (block 5/9), MAGIC_BOMB (40/35). |
| MechaKnight | 320/300, Artifact +3 | CHARGE (30/25) → FLAMETHROWER (4 Burn to hand) → WINDUP (15 block + Str +5, IsWoundUp=true) → HEAVY_CLEAVE (40/35) → FLAMETHROWER repeat. |
| SoulNexus | 254/234 | Random (no-repeat): SOUL_BURN (31/29), MAELSTROM×4 (7/6), DRAIN_LIFE (19/18 + Vuln +2 + Weak +2). |

## Underdocks / Act-1-alt Bosses

LagavulinMatriarch (Asleep + Plating mechanic), SoulFysh, WaterfallGiant — defer detail extraction until used.

## Normal monster summary (selected)

For Cycle B porting we focus on the simplest mono-monster encounters
first. Already ported: NibbitWeak (alone), SludgeSpinnerWeak.

Next to port (1막):
- ShrinkerBeetleWeak: 38-42 HP. SHRINKER (Shrink debuff) → CHOMP (7-8) → STOMP (13-14) → CHOMP/STOMP cycle.
- FuzzyWurmCrawlerWeak: 55-59 HP. FIRST_ACID_GOOP → INHALE → ACID_GOOP cycle with Str +7 buff.
- SnappingJaxfruitNormal: 31-36 HP + Flyconid 47-53. ENERGY_ORB (3-4 dmg + Str +2) repeating.
- MawlerNormal: 72-76 HP. Random branch: RIP_AND_TEAR (14-16), ROAR (Vuln +3), CLAW×2 (4-5).

Multi-monster encounters (Inklets, Slimes, RubyRaiders, etc.) require
combat.py to gain a `monsters: list[Monster]` field — deferred.

## Implementation priority for `sim/monsters.py`

1. **Already done**: NibbitWeak, SludgeSpinnerWeak.
2. **Phase 1**: Solo 1막 weak/normal that match current single-monster combat (Shrinker, FuzzyWurm, Mawler, SnappingJaxfruit, VineShambler, Fogmog, CubexConstruct).
3. **Phase 2**: 1막 bosses (CeremonialBeast, Vantom — solo). TheKin needs multi-monster.
4. **Phase 3**: Multi-monster combat refactor → 1막 elites (PhrogParasite, ByrdonisElite, BygoneEffigy) + multi-monster normals.
5. **Phase 4**: 2막 + 3막 content.

3막 보스까지 완주 학습 목표 시 Phase 1-4 모두 + 80% relic + 50% card 효과까지는 필요. 현재 (cycle B 첫 슬라이스)는 Phase 1만 + 핵심 카드 효과 + 핵심 relic 효과까지 가능 범위.

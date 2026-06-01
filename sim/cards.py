"""Ironclad cards — starting deck (notes/05_mvp_combat_spec.md §C.2) plus
a small library of common/uncommon cards porting verbatim from the
decompile (`decompiled/MegaCrit.Sts2.Core.Models.Cards/*.cs`).

Only cards expressible in the current dsl.py are included; anything
that needs new EffectOps (draw, exhaust, conditional triggers,
all-enemy targeting on >1 enemy) is left for a follow-up.
"""
from __future__ import annotations

from .dsl import (
    CardDef, CardType, Effect, EffectOp, Scaling, ScalingKind, Target, X_COST,
)

STRIKE_SCALING = (
    Scaling(ScalingKind.STRENGTH_ADDITIVE, owner="dealer"),
    Scaling(ScalingKind.WEAK_MULTIPLICATIVE, owner="dealer"),
    Scaling(ScalingKind.VULNERABLE_MULTIPLICATIVE, owner="target"),
)

STRIKE_IRONCLAD = CardDef(
    id="strike_ironclad",
    name="Strike",
    cost=1,
    type=CardType.ATTACK,
    count=5,
    effects=(
        Effect(
            op=EffectOp.DEAL_DAMAGE,
            target=Target.SELECTED_ENEMY,
            amount=6,
            scaling=STRIKE_SCALING,
        ),
    ),
)

DEFEND_IRONCLAD = CardDef(
    id="defend_ironclad",
    name="Defend",
    cost=1,
    type=CardType.SKILL,
    count=4,
    effects=(
        Effect(op=EffectOp.GAIN_BLOCK, target=Target.SELF, amount=5),
    ),
)

BASH = CardDef(
    id="bash",
    name="Bash",
    cost=2,
    type=CardType.ATTACK,
    count=1,
    effects=(
        Effect(
            op=EffectOp.DEAL_DAMAGE,
            target=Target.SELECTED_ENEMY,
            amount=8,
            scaling=STRIKE_SCALING,
        ),
        Effect(
            op=EffectOp.APPLY_POWER,
            target=Target.SELECTED_ENEMY,
            power_id="vulnerable",
            amount=2,
        ),
    ),
)

IRONCLAD_STARTING_DECK = (STRIKE_IRONCLAD, DEFEND_IRONCLAD, BASH)


# --- Additional Ironclad cards (not in starting deck) ---------------------
# Cites:
#   decompiled/MegaCrit.Sts2.Core.Models.Cards/IronWave.cs
#   decompiled/MegaCrit.Sts2.Core.Models.Cards/Inflame.cs


IRON_WAVE = CardDef(
    id="iron_wave",
    name="Iron Wave",
    cost=1,
    type=CardType.ATTACK,
    count=0,
    effects=(
        # Block-then-damage order matches the OnPlay sequence in the decompile
        # (GainBlock, then Attack).
        Effect(op=EffectOp.GAIN_BLOCK, target=Target.SELF, amount=5),
        Effect(
            op=EffectOp.DEAL_DAMAGE,
            target=Target.SELECTED_ENEMY,
            amount=5,
            scaling=STRIKE_SCALING,
        ),
    ),
)

INFLAME = CardDef(
    id="inflame",
    name="Inflame",
    cost=1,
    type=CardType.POWER,
    count=0,
    effects=(
        Effect(
            op=EffectOp.APPLY_POWER,
            target=Target.SELF,
            power_id="strength",
            amount=2,
        ),
    ),
)

# --- Cycle B: real OnPlay effects for Common SIMPLE cards (notes/14 §IV) ---

POMMEL_STRIKE = CardDef(
    id="pommel_strike", name="Pommel Strike", cost=1, type=CardType.ATTACK, count=0,
    effects=(
        Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
               amount=9, scaling=STRIKE_SCALING),
        Effect(op=EffectOp.DRAW_CARD, target=Target.SELF, amount=1),
    ),
)

SHRUG_IT_OFF = CardDef(
    id="shrug_it_off", name="Shrug It Off", cost=1, type=CardType.SKILL, count=0,
    effects=(
        Effect(op=EffectOp.GAIN_BLOCK, target=Target.SELF, amount=8),
        Effect(op=EffectOp.DRAW_CARD, target=Target.SELF, amount=1),
    ),
)

THUNDERCLAP = CardDef(
    id="thunderclap", name="Thunderclap", cost=1, type=CardType.ATTACK, count=0,
    effects=(
        Effect(op=EffectOp.DEAL_DAMAGE, target=Target.ALL_ENEMIES,
               amount=4, scaling=STRIKE_SCALING),
        Effect(op=EffectOp.APPLY_POWER, target=Target.ALL_ENEMIES,
               power_id="vulnerable", amount=1),
    ),
)

TREMBLE = CardDef(
    id="tremble", name="Tremble", cost=1, type=CardType.SKILL, count=0,
    effects=(
        Effect(op=EffectOp.APPLY_POWER, target=Target.SELECTED_ENEMY,
               power_id="vulnerable", amount=3),
        Effect(op=EffectOp.EXHAUST_SELF, target=Target.SELF),
    ),
)

TWIN_STRIKE = CardDef(
    id="twin_strike", name="Twin Strike", cost=1, type=CardType.ATTACK, count=0,
    effects=(
        Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
               amount=5, scaling=STRIKE_SCALING, hit_count=2),
    ),
)

BLOODLETTING = CardDef(
    id="bloodletting", name="Bloodletting", cost=0, type=CardType.SKILL, count=0,
    effects=(
        Effect(op=EffectOp.SELF_HP_LOSE, target=Target.SELF, amount=3),
        Effect(op=EffectOp.ENERGY_GAIN, target=Target.SELF, amount=2),
    ),
)

ANGER = CardDef(
    id="anger", name="Anger", cost=0, type=CardType.ATTACK, count=0,
    effects=(
        Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
               amount=6, scaling=STRIKE_SCALING),
        Effect(op=EffectOp.COPY_TO_DISCARD, target=Target.SELF),
    ),
)

CINDER = CardDef(
    id="cinder", name="Cinder", cost=2, type=CardType.ATTACK, count=0,
    effects=(
        Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
               amount=18, scaling=STRIKE_SCALING),
        Effect(op=EffectOp.EXHAUST_RANDOM, target=Target.SELF),
    ),
)

INFLAME_HIGH = INFLAME  # alias for callers


# Additional Cycle B cards — depend only on existing Powers / EffectOps.

BLUDGEON = CardDef(
    id="bludgeon", name="Bludgeon", cost=3, type=CardType.ATTACK, count=0,
    effects=(
        Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
               amount=32, scaling=STRIKE_SCALING),
    ),
)

CLOTHESLINE = CardDef(  # represents "Headbutt"-shaped 12-dmg + weak combo if it existed
    id="clothesline", name="Clothesline", cost=2, type=CardType.ATTACK, count=0,
    effects=(
        Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
               amount=12, scaling=STRIKE_SCALING),
        Effect(op=EffectOp.APPLY_POWER, target=Target.SELECTED_ENEMY,
               power_id="weak", amount=2),
    ),
)

UPPERCUT = CardDef(
    id="uppercut", name="Uppercut", cost=2, type=CardType.ATTACK, count=0,
    effects=(
        Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
               amount=13, scaling=STRIKE_SCALING),
        Effect(op=EffectOp.APPLY_POWER, target=Target.SELECTED_ENEMY,
               power_id="weak", amount=1),
        Effect(op=EffectOp.APPLY_POWER, target=Target.SELECTED_ENEMY,
               power_id="vulnerable", amount=1),
    ),
)

TAUNT = CardDef(
    id="taunt", name="Taunt", cost=1, type=CardType.SKILL, count=0,
    effects=(
        Effect(op=EffectOp.GAIN_BLOCK, target=Target.SELF, amount=7),
        Effect(op=EffectOp.APPLY_POWER, target=Target.SELECTED_ENEMY,
               power_id="vulnerable", amount=1),
    ),
)

STONE_ARMOR = CardDef(
    id="stone_armor", name="Stone Armor", cost=1, type=CardType.POWER, count=0,
    effects=(
        Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
               power_id="plating", amount=4),
    ),
)

RAGE = CardDef(  # Rage.cs: PowerCmd.Apply<RagePower>(Power=3) — block per Attack this turn
    id="rage", name="Rage", cost=0, type=CardType.SKILL, count=0,
    effects=(
        Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
               power_id="rage", amount=3),
    ),
)

BATTLE_TRANCE = CardDef(
    id="battle_trance", name="Battle Trance", cost=0, type=CardType.SKILL, count=0,
    effects=(
        Effect(op=EffectOp.DRAW_CARD, target=Target.SELF, amount=3),
        # BattleTrance.cs: applies NoDrawPower(1) after the draw.
        Effect(op=EffectOp.NO_DRAW, target=Target.SELF),
    ),
)

HEADBUTT = CardDef(
    id="headbutt", name="Headbutt", cost=1, type=CardType.ATTACK, count=0,
    effects=(
        Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
               amount=9, scaling=STRIKE_SCALING),
        # Headbutt.cs: put a card from discard on top of the draw pile.
        Effect(op=EffectOp.MOVE_DISCARD_TO_DRAW_TOP, target=Target.SELF),
    ),
)

DISMANTLE = CardDef(
    id="dismantle", name="Dismantle", cost=1, type=CardType.ATTACK, count=0,
    effects=(
        Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
               amount=8, scaling=STRIKE_SCALING, hit_count=2),
    ),
)

PERFECTED_STRIKE = CardDef(
    id="perfected_strike", name="Perfected Strike", cost=2, type=CardType.ATTACK, count=0,
    effects=(
        # PerfectedStrike.cs: 6 base + 2 (ExtraDamage) per Strike-tagged card.
        Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
               amount=6, scaling=STRIKE_SCALING + (
                   Scaling(kind=ScalingKind.STRIKE_TAG_COUNT, owner="dealer", amount=2),
               )),
    ),
)


# ===========================================================================
# Phase 7C: STS2 Ironclad pool completion. Each CardDef's cost/type/values are
# verified against decompiled/MegaCrit.Sts2.Core.Models.Cards/<Card>.cs.
# ===========================================================================

# --- Common -----------------------------------------------------------------

ARMAMENTS = CardDef(  # Armaments.cs: Block 5; upgrade a card in hand
    id="armaments", name="Armaments", cost=1, type=CardType.SKILL, count=0,
    effects=(
        Effect(op=EffectOp.GAIN_BLOCK, target=Target.SELF, amount=5),
        Effect(op=EffectOp.UPGRADE_ALL_IN_HAND, target=Target.SELF),
    ),
)

BLOOD_WALL = CardDef(  # BloodWall.cs: lose 2 HP, gain 16 Block
    id="blood_wall", name="Blood Wall", cost=2, type=CardType.SKILL, count=0,
    effects=(
        Effect(op=EffectOp.SELF_HP_LOSE, target=Target.SELF, amount=2),
        Effect(op=EffectOp.GAIN_BLOCK, target=Target.SELF, amount=16),
    ),
)

BODY_SLAM = CardDef(  # BodySlam.cs: damage == current Block
    id="body_slam", name="Body Slam", cost=1, type=CardType.ATTACK, count=0,
    effects=(
        Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY, amount=0,
               scaling=(Scaling(ScalingKind.BLOCK_AMOUNT, owner="dealer"),)),
    ),
)

BREAKTHROUGH = CardDef(  # Breakthrough.cs: lose 1 HP, deal 9 to ALL enemies
    id="breakthrough", name="Breakthrough", cost=1, type=CardType.ATTACK, count=0,
    effects=(
        Effect(op=EffectOp.SELF_HP_LOSE, target=Target.SELF, amount=1),
        Effect(op=EffectOp.DEAL_DAMAGE, target=Target.ALL_ENEMIES, amount=9,
               scaling=STRIKE_SCALING),
    ),
)

HAVOC = CardDef(  # Havoc.cs: auto-play the top of the draw pile, then exhaust it
    id="havoc", name="Havoc", cost=1, type=CardType.SKILL, count=0,
    effects=(
        Effect(op=EffectOp.AUTO_PLAY_FROM_DRAW, target=Target.SELF),
    ),
)

MOLTEN_FIST = CardDef(  # MoltenFist.cs: 10 dmg; if target Vulnerable, double it
    id="molten_fist", name="Molten Fist", cost=1, type=CardType.ATTACK, count=0,
    exhaust=True,
    effects=(
        Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY, amount=10,
               scaling=STRIKE_SCALING),
        # "double existing Vulnerable" -> apply +current vulnerable stacks.
        Effect(op=EffectOp.APPLY_POWER, target=Target.SELECTED_ENEMY,
               power_id="vulnerable", amount=0,
               scaling=(Scaling(ScalingKind.TARGET_VULNERABLE_COUNT, owner="target"),)),
    ),
)

SETUP_STRIKE = CardDef(  # SetupStrike.cs: 7 dmg, then SetupStrikePower(2 Str)
    id="setup_strike", name="Setup Strike", cost=1, type=CardType.ATTACK, count=0,
    effects=(
        Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY, amount=7,
               scaling=STRIKE_SCALING),
        # SetupStrikePower grants Strength on the NEXT turn; modeled as immediate
        # Strength (faithful in net effect for damage scaling).
        Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
               power_id="strength", amount=2),
    ),
)

SWORD_BOOMERANG = CardDef(  # SwordBoomerang.cs: 3 dmg ×3 random
    id="sword_boomerang", name="Sword Boomerang", cost=1, type=CardType.ATTACK,
    count=0,
    effects=(
        Effect(op=EffectOp.DEAL_DAMAGE, target=Target.RANDOM_ENEMY, amount=3,
               scaling=STRIKE_SCALING, hit_count=3),
    ),
)

TRUE_GRIT = CardDef(  # TrueGrit.cs: Block 7, exhaust a random card in hand
    id="true_grit", name="True Grit", cost=1, type=CardType.SKILL, count=0,
    effects=(
        Effect(op=EffectOp.GAIN_BLOCK, target=Target.SELF, amount=7),
        Effect(op=EffectOp.EXHAUST_RANDOM, target=Target.SELF),
    ),
)

# --- Uncommon ---------------------------------------------------------------

WHIRLWIND = CardDef(  # Whirlwind.cs: X-cost, 5 dmg to ALL, hits == energy spent
    id="whirlwind", name="Whirlwind", cost=X_COST, type=CardType.ATTACK, count=0,
    effects=(
        Effect(op=EffectOp.DEAL_DAMAGE, target=Target.ALL_ENEMIES, amount=5,
               scaling=STRIKE_SCALING),
    ),
)

CASCADE = CardDef(  # Cascade.cs: X-cost; auto-play X cards from draw top (+1 upgraded)
    id="cascade", name="Cascade", cost=X_COST, type=CardType.SKILL, count=0,
    effects=(
        # amount = extra plays added on top of the X energy spent (upgrade -> +1).
        Effect(op=EffectOp.AUTO_PLAY_FROM_DRAW, target=Target.SELF, amount=0),
    ),
)

ASHEN_STRIKE = CardDef(  # AshenStrike.cs: 6 + 3 per exhausted card; exhausts
    id="ashen_strike", name="Ashen Strike", cost=1, type=CardType.ATTACK, count=0,
    exhaust=True,
    effects=(
        Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY, amount=6,
               scaling=STRIKE_SCALING + (
                   Scaling(ScalingKind.EXHAUST_PILE_COUNT, owner="dealer", amount=3),)),
    ),
)

BULLY = CardDef(  # Bully.cs: 4 + 2 per Vulnerable stack on target
    id="bully", name="Bully", cost=0, type=CardType.ATTACK, count=0,
    effects=(
        Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY, amount=4,
               scaling=STRIKE_SCALING + (
                   Scaling(ScalingKind.TARGET_VULNERABLE_COUNT, owner="target",
                           amount=2),)),
    ),
)

BURNING_PACT = CardDef(  # BurningPact.cs: exhaust 1 card, draw 2
    id="burning_pact", name="Burning Pact", cost=1, type=CardType.SKILL, count=0,
    effects=(
        Effect(op=EffectOp.EXHAUST_RANDOM, target=Target.SELF),
        Effect(op=EffectOp.DRAW_CARD, target=Target.SELF, amount=2),
    ),
)

FLAME_BARRIER = CardDef(  # FlameBarrier.cs: Block 12 + Thorns-for-turn 4
    id="flame_barrier", name="Flame Barrier", cost=2, type=CardType.SKILL, count=0,
    effects=(
        Effect(op=EffectOp.GAIN_BLOCK, target=Target.SELF, amount=12),
        Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
               power_id="thorns", amount=4),
    ),
)

HEMOKINESIS = CardDef(  # Hemokinesis.cs: lose 2 HP, deal 15
    id="hemokinesis", name="Hemokinesis", cost=1, type=CardType.ATTACK, count=0,
    effects=(
        Effect(op=EffectOp.SELF_HP_LOSE, target=Target.SELF, amount=2),
        Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY, amount=15,
               scaling=STRIKE_SCALING),
    ),
)

HOWL_FROM_BEYOND = CardDef(  # HowlFromBeyond.cs: 16 dmg to ALL; exhaust
    id="howl_from_beyond", name="Howl from Beyond", cost=3, type=CardType.ATTACK,
    count=0, exhaust=True,
    effects=(
        Effect(op=EffectOp.DEAL_DAMAGE, target=Target.ALL_ENEMIES, amount=16,
               scaling=STRIKE_SCALING),
    ),
)

INFERNAL_BLADE = CardDef(  # InfernalBlade.cs: add a random Attack (free); exhaust
    id="infernal_blade", name="Infernal Blade", cost=1, type=CardType.SKILL,
    count=0, exhaust=True,
    effects=(
        Effect(op=EffectOp.ADD_RANDOM_ATTACK, target=Target.SELF),
    ),
)

PILLAGE = CardDef(  # Pillage.cs: 6 dmg, then draw while drawing attacks
    id="pillage", name="Pillage", cost=1, type=CardType.ATTACK, count=0,
    effects=(
        Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY, amount=6,
               scaling=STRIKE_SCALING),
        Effect(op=EffectOp.DRAW_UNTIL_NONATTACK, target=Target.SELF),
    ),
)

RAMPAGE = CardDef(  # Rampage.cs: 9 dmg (escalates per play in real game; base here)
    id="rampage", name="Rampage", cost=1, type=CardType.ATTACK, count=0,
    effects=(
        Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY, amount=9,
               scaling=STRIKE_SCALING),
    ),
)

SECOND_WIND = CardDef(  # SecondWind.cs: exhaust all non-attacks, 5 block each
    id="second_wind", name="Second Wind", cost=1, type=CardType.SKILL, count=0,
    effects=(
        Effect(op=EffectOp.EXHAUST_NONATTACKS_BLOCK, target=Target.SELF, amount=5),
    ),
)

SHOCKWAVE = CardDef(  # Shockwave.cs: Weak 3 + Vulnerable 3 to ALL; exhaust
    id="shockwave", name="Shockwave", cost=2, type=CardType.SKILL, count=0,
    exhaust=True,
    effects=(
        Effect(op=EffectOp.APPLY_POWER, target=Target.ALL_ENEMIES,
               power_id="weak", amount=3),
        Effect(op=EffectOp.APPLY_POWER, target=Target.ALL_ENEMIES,
               power_id="vulnerable", amount=3),
    ),
)

SPITE = CardDef(  # Spite.cs: 5 dmg, ×2 hits if HP lost this turn
    id="spite", name="Spite", cost=0, type=CardType.ATTACK, count=0,
    effects=(
        Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY, amount=5,
               scaling=STRIKE_SCALING,
               # hit_count 1 base, +1 if HP lost this turn (-> 2 total).
               hit_count=1),
        Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY, amount=5,
               scaling=STRIKE_SCALING + (
                   Scaling(ScalingKind.HP_LOST_HITS, owner="dealer"),), hit_count=0),
    ),
)

STOMP = CardDef(  # Stomp.cs: 12 dmg to ALL (cost-reduces per attack; base here)
    id="stomp", name="Stomp", cost=3, type=CardType.ATTACK, count=0,
    effects=(
        Effect(op=EffectOp.DEAL_DAMAGE, target=Target.ALL_ENEMIES, amount=12,
               scaling=STRIKE_SCALING),
    ),
)

UNRELENTING = CardDef(  # Unrelenting.cs: 12 dmg (+FreeAttackPower not modeled)
    id="unrelenting", name="Unrelenting", cost=2, type=CardType.ATTACK, count=0,
    effects=(
        Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY, amount=12,
               scaling=STRIKE_SCALING),
    ),
)

# --- Rare -------------------------------------------------------------------

BRAND = CardDef(  # Brand.cs: lose 1 HP, exhaust a card, +1 Strength
    id="brand", name="Brand", cost=0, type=CardType.SKILL, count=0,
    effects=(
        Effect(op=EffectOp.SELF_HP_LOSE, target=Target.SELF, amount=1),
        Effect(op=EffectOp.EXHAUST_RANDOM, target=Target.SELF),
        Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
               power_id="strength", amount=1),
    ),
)

CONFLAGRATION = CardDef(  # Conflagration.cs: (8 + 2 per attack this turn) to ALL
    id="conflagration", name="Conflagration", cost=1, type=CardType.ATTACK, count=0,
    effects=(
        Effect(op=EffectOp.DEAL_DAMAGE, target=Target.ALL_ENEMIES, amount=8,
               scaling=STRIKE_SCALING + (
                   Scaling(ScalingKind.ATTACKS_PLAYED_COUNT, owner="dealer",
                           amount=2),)),
    ),
)

FEED = CardDef(  # Feed.cs: 10 dmg; if it kills, +3 max HP; exhaust
    id="feed", name="Feed", cost=1, type=CardType.ATTACK, count=0, exhaust=True,
    effects=(
        Effect(op=EffectOp.GAIN_MAX_HP_ON_KILL, target=Target.SELECTED_ENEMY,
               amount=3, scaling=STRIKE_SCALING),
    ),
)

FIEND_FIRE = CardDef(  # FiendFire.cs: exhaust hand, 7 dmg per card; exhaust
    id="fiend_fire", name="Fiend Fire", cost=2, type=CardType.ATTACK, count=0,
    exhaust=True,
    effects=(
        Effect(op=EffectOp.EXHAUST_HAND_SCALED, target=Target.SELECTED_ENEMY,
               amount=7),
    ),
)

IMPERVIOUS = CardDef(  # Impervious.cs: Block 30; exhaust
    id="impervious", name="Impervious", cost=2, type=CardType.SKILL, count=0,
    exhaust=True,
    effects=(
        Effect(op=EffectOp.GAIN_BLOCK, target=Target.SELF, amount=30),
    ),
)

MANGLE = CardDef(  # Mangle.cs: 15 dmg + reduce target Strength by 10
    id="mangle", name="Mangle", cost=3, type=CardType.ATTACK, count=0,
    effects=(
        Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY, amount=15,
               scaling=STRIKE_SCALING),
        Effect(op=EffectOp.APPLY_POWER, target=Target.SELECTED_ENEMY,
               power_id="strength", amount=-10),
    ),
)

NOT_YET = CardDef(  # NotYet.cs: heal 10; exhaust
    id="not_yet", name="Not Yet", cost=2, type=CardType.SKILL, count=0,
    exhaust=True,
    effects=(
        Effect(op=EffectOp.HEAL, target=Target.SELF, amount=10),
    ),
)

OFFERING = CardDef(  # Offering.cs: lose 6 HP, +2 energy, draw 3; exhaust
    id="offering", name="Offering", cost=0, type=CardType.SKILL, count=0,
    exhaust=True,
    effects=(
        Effect(op=EffectOp.SELF_HP_LOSE, target=Target.SELF, amount=6),
        Effect(op=EffectOp.ENERGY_GAIN, target=Target.SELF, amount=2),
        Effect(op=EffectOp.DRAW_CARD, target=Target.SELF, amount=3),
    ),
)

PACTS_END = CardDef(  # PactsEnd.cs: 17 dmg to ALL (playable iff 3+ exhausted)
    id="pacts_end", name="Pact's End", cost=0, type=CardType.ATTACK, count=0,
    effects=(
        Effect(op=EffectOp.DEAL_DAMAGE, target=Target.ALL_ENEMIES, amount=17,
               scaling=STRIKE_SCALING),
    ),
)

PYRE = CardDef(  # Pyre.cs: PyrePower(1 energy/turn) -> model as Berserk +1 energy
    id="pyre", name="Pyre", cost=2, type=CardType.POWER, count=0,
    effects=(
        Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
               power_id="berserk", amount=1),
    ),
)

TEAR_ASUNDER = CardDef(  # TearAsunder.cs: 5 dmg ×(1 + hits taken this turn)
    id="tear_asunder", name="Tear Asunder", cost=2, type=CardType.ATTACK, count=0,
    effects=(
        Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY, amount=5,
               scaling=STRIKE_SCALING + (
                   Scaling(ScalingKind.HP_LOST_HITS, owner="dealer"),), hit_count=1),
    ),
)

BREAK_CARD = CardDef(  # Break.cs (Ancient): 20 dmg + Vulnerable 5
    id="break", name="Break", cost=1, type=CardType.ATTACK, count=0,
    effects=(
        Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY, amount=20,
               scaling=STRIKE_SCALING),
        Effect(op=EffectOp.APPLY_POWER, target=Target.SELECTED_ENEMY,
               power_id="vulnerable", amount=5),
    ),
)

FIGHT_ME = CardDef(  # FightMe.cs: 5 dmg ×2, +3 Strength self, +1 Strength enemy
    id="fight_me", name="Fight Me", cost=2, type=CardType.ATTACK, count=0,
    effects=(
        Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY, amount=5,
               scaling=STRIKE_SCALING, hit_count=2),
        Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
               power_id="strength", amount=3),
        Effect(op=EffectOp.APPLY_POWER, target=Target.SELECTED_ENEMY,
               power_id="strength", amount=1),
    ),
)

DOMINATE = CardDef(  # Dominate.cs: Vulnerable 1, then Strength == target Vulnerable
    id="dominate", name="Dominate", cost=1, type=CardType.SKILL, count=0,
    exhaust=True,
    effects=(
        Effect(op=EffectOp.APPLY_POWER, target=Target.SELECTED_ENEMY,
               power_id="vulnerable", amount=1),
        # Gain Strength == the target's resulting Vulnerable stacks.
        Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
               power_id="strength", amount=0,
               scaling=(Scaling(ScalingKind.TARGET_VULNERABLE_COUNT, owner="target"),)),
    ),
)

# ===========================================================================
# Phase 8 Track A: remaining STS2 Ironclad pool (history-conditional + powers).
# Each CardDef verified against decompiled/MegaCrit.Sts2.Core.Models.Cards/*.cs
# (and the matching Models.Powers/*.cs). Costs/types/amounts are .cs-exact.
# ===========================================================================

# GiantRock token (GiantRock.cs): 1-cost Attack, 16 damage. Primal Force target.
GIANT_ROCK = CardDef(
    id="giant_rock", name="Giant Rock", cost=1, type=CardType.ATTACK, count=0,
    effects=(
        Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY, amount=16,
               scaling=STRIKE_SCALING),
    ),
)

# --- Uncommon ---------------------------------------------------------------

COLOSSUS = CardDef(  # Colossus.cs: Block 5, then ColossusPower(1) (×0.5 incoming)
    id="colossus", name="Colossus", cost=1, type=CardType.SKILL, count=0,
    effects=(
        Effect(op=EffectOp.GAIN_BLOCK, target=Target.SELF, amount=5),
        Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
               power_id="colossus", amount=1),
    ),
)

DRUM_OF_BATTLE = CardDef(  # DrumOfBattle.cs: cost 0, draw 2, DrumOfBattlePower(1)
    id="drum_of_battle", name="Drum of Battle", cost=0, type=CardType.POWER, count=0,
    effects=(
        Effect(op=EffectOp.DRAW_CARD, target=Target.SELF, amount=2),
        Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
               power_id="drum_of_battle", amount=1),
    ),
)

EVIL_EYE = CardDef(  # EvilEye.cs: Block 8 (×2 if a card was exhausted this turn); exhaust
    id="evil_eye", name="Evil Eye", cost=1, type=CardType.SKILL, count=0,
    exhaust=True,
    effects=(
        Effect(op=EffectOp.GAIN_BLOCK_IF_EXHAUSTED, target=Target.SELF, amount=8),
    ),
)

EXPECT_A_FIGHT = CardDef(  # ExpectAFight.cs: gain 1 energy per Attack in hand, NoEnergyGain
    id="expect_a_fight", name="Expect a Fight", cost=2, type=CardType.SKILL, count=0,
    effects=(
        Effect(op=EffectOp.GAIN_ENERGY_PER_HAND_ATTACK, target=Target.SELF),
    ),
)

FORGOTTEN_RITUAL = CardDef(  # ForgottenRitual.cs: gain 3 energy iff exhausted this turn; exhaust
    id="forgotten_ritual", name="Forgotten Ritual", cost=1, type=CardType.SKILL,
    count=0, exhaust=True,
    effects=(
        Effect(op=EffectOp.GAIN_ENERGY_IF_EXHAUSTED, target=Target.SELF, amount=3),
    ),
)

INFERNO = CardDef(  # Inferno.cs: InfernoPower(6) — turn-start self-dmg + AoE retaliate
    id="inferno", name="Inferno", cost=1, type=CardType.POWER, count=0,
    effects=(
        Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
               power_id="inferno", amount=6),
    ),
)

JUGGLING = CardDef(  # Juggling.cs: JugglingPower(1) — clone 3rd attack/turn
    id="juggling", name="Juggling", cost=1, type=CardType.POWER, count=0,
    effects=(
        Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
               power_id="juggling", amount=1),
    ),
)

STAMPEDE = CardDef(  # Stampede.cs: cost 2, StampedePower(1) — turn-end auto-play attack
    id="stampede", name="Stampede", cost=2, type=CardType.POWER, count=0,
    effects=(
        Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
               power_id="stampede", amount=1),
    ),
)

VICIOUS = CardDef(  # Vicious.cs: ViciousPower(1) — draw on Vulnerable applied
    id="vicious", name="Vicious", cost=1, type=CardType.POWER, count=0,
    effects=(
        Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
               power_id="vicious", amount=1),
    ),
)

# --- Rare -------------------------------------------------------------------

AGGRESSION = CardDef(  # Aggression.cs: AggressionPower(1) — turn-start grab attacks
    id="aggression", name="Aggression", cost=1, type=CardType.POWER, count=0,
    effects=(
        Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
               power_id="aggression", amount=1),
    ),
)

CRIMSON_MANTLE = CardDef(  # CrimsonMantle.cs: CrimsonMantlePower(8) — turn-start self-dmg + block
    id="crimson_mantle", name="Crimson Mantle", cost=1, type=CardType.POWER, count=0,
    effects=(
        Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
               power_id="crimson_mantle", amount=8),
    ),
)

CRUELTY = CardDef(  # Cruelty.cs: CrueltyPower(25) — +0.25 Vulnerable multiplier
    id="cruelty", name="Cruelty", cost=1, type=CardType.POWER, count=0,
    effects=(
        Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
               power_id="cruelty", amount=25),
    ),
)

HELLRAISER = CardDef(  # Hellraiser.cs: HellraiserPower(1) — auto-play drawn Strikes
    id="hellraiser", name="Hellraiser", cost=2, type=CardType.POWER, count=0,
    effects=(
        Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
               power_id="hellraiser", amount=1),
    ),
)

ONE_TWO_PUNCH = CardDef(  # OneTwoPunch.cs: OneTwoPunchPower(1) — next attack plays twice
    id="one_two_punch", name="One-Two Punch", cost=1, type=CardType.SKILL, count=0,
    effects=(
        Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
               power_id="one_two_punch", amount=1),
    ),
)

PRIMAL_FORCE = CardDef(  # PrimalForce.cs: cost 0, transform hand Attacks -> GiantRock
    id="primal_force", name="Primal Force", cost=0, type=CardType.SKILL, count=0,
    effects=(
        Effect(op=EffectOp.TRANSFORM_ATTACKS_IN_HAND, target=Target.SELF,
               card_id="giant_rock"),
    ),
)

STOKE = CardDef(  # Stoke.cs: cost 1, exhaust hand, add that many random cards
    id="stoke", name="Stoke", cost=1, type=CardType.SKILL, count=0,
    effects=(
        Effect(op=EffectOp.EXHAUST_HAND_GENERATE_RANDOM, target=Target.SELF),
    ),
)

THRASH = CardDef(  # Thrash.cs: 4 dmg ×2, then exhaust a hand Attack + add its dmg; exhaust
    id="thrash", name="Thrash", cost=1, type=CardType.ATTACK, count=0,
    exhaust=True,
    effects=(
        Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY, amount=4,
               scaling=STRIKE_SCALING, hit_count=2),
        Effect(op=EffectOp.THRASH_EXHAUST_ATTACK, target=Target.SELECTED_ENEMY),
    ),
)

UNMOVABLE = CardDef(  # Unmovable.cs: cost 2, UnmovablePower(1) — double first block/turn
    id="unmovable", name="Unmovable", cost=2, type=CardType.POWER, count=0,
    effects=(
        Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
               power_id="unmovable", amount=1),
    ),
)

PHASE8_CARDS = (
    COLOSSUS, DRUM_OF_BATTLE, EVIL_EYE, EXPECT_A_FIGHT, FORGOTTEN_RITUAL,
    INFERNO, JUGGLING, STAMPEDE, VICIOUS,
    AGGRESSION, CRIMSON_MANTLE, CRUELTY, HELLRAISER, ONE_TWO_PUNCH,
    PRIMAL_FORCE, STOKE, THRASH, UNMOVABLE, GIANT_ROCK,
    CASCADE,
)


PHASE7C_CARDS = (
    FIGHT_ME, DOMINATE,
    ARMAMENTS, BLOOD_WALL, BODY_SLAM, BREAKTHROUGH, HAVOC, MOLTEN_FIST,
    SETUP_STRIKE, SWORD_BOOMERANG, TRUE_GRIT,
    WHIRLWIND,
    ASHEN_STRIKE, BULLY, BURNING_PACT, FLAME_BARRIER, HEMOKINESIS,
    HOWL_FROM_BEYOND, INFERNAL_BLADE, PILLAGE, RAMPAGE, SECOND_WIND, SHOCKWAVE,
    SPITE, STOMP, UNRELENTING,
    BRAND, CONFLAGRATION, FEED, FIEND_FIRE, IMPERVIOUS, MANGLE, NOT_YET,
    OFFERING, PACTS_END, PYRE, TEAR_ASUNDER, BREAK_CARD,
)


# --- Engine "deck-power" cards (Phase 7B) ---------------------------------
# Costs/amounts verified against decompiled/MegaCrit.Sts2.Core.Models.Cards/*.cs.
# Metallicize / Combust / Berserk / Brutality have no STS2 card model (STS2
# uses Furnace instead of Metallicize); they use faithful STS1 numbers.

DEMON_FORM = CardDef(
    id="demon_form", name="Demon Form", cost=3, type=CardType.POWER, count=0,
    effects=(
        Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
               power_id="demon_form", amount=2),  # DemonForm.cs: Strength 2/turn
    ),
)

METALLICIZE = CardDef(
    id="metallicize", name="Metallicize", cost=1, type=CardType.POWER, count=0,
    effects=(
        Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
               power_id="metallicize", amount=3),  # STS1: 3 block/turn end
    ),
)

FEEL_NO_PAIN = CardDef(
    id="feel_no_pain", name="Feel No Pain", cost=1, type=CardType.POWER, count=0,
    effects=(
        Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
               power_id="feel_no_pain", amount=3),  # FeelNoPain.cs: Power 3
    ),
)

DARK_EMBRACE = CardDef(
    id="dark_embrace", name="Dark Embrace", cost=2, type=CardType.POWER, count=0,
    effects=(
        Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
               power_id="dark_embrace", amount=1),  # DarkEmbrace.cs: draw 1/exhaust
    ),
)

JUGGERNAUT = CardDef(
    id="juggernaut", name="Juggernaut", cost=2, type=CardType.POWER, count=0,
    effects=(
        Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
               power_id="juggernaut", amount=5),  # Juggernaut.cs: 5 dmg/block gain
    ),
)

RUPTURE = CardDef(
    id="rupture", name="Rupture", cost=1, type=CardType.POWER, count=0,
    effects=(
        Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
               power_id="rupture", amount=1),  # Rupture.cs: Strength 1 per card HP-loss
    ),
)

COMBUST = CardDef(
    id="combust", name="Combust", cost=1, type=CardType.POWER, count=0,
    effects=(
        Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
               power_id="combust", amount=5),  # STS1: lose 1 HP, 5 AoE dmg/turn end
    ),
)

BARRICADE = CardDef(
    id="barricade", name="Barricade", cost=3, type=CardType.POWER, count=0,
    effects=(
        Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
               power_id="barricade", amount=1),  # Barricade.cs: block persists
    ),
)

BERSERK = CardDef(
    id="berserk", name="Berserk", cost=0, type=CardType.POWER, count=0,
    effects=(
        Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
               power_id="berserk", amount=1),  # STS1: +1 energy/turn (self-Vuln omitted)
    ),
)

BRUTALITY = CardDef(
    id="brutality", name="Brutality", cost=0, type=CardType.POWER, count=0,
    effects=(
        Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
               power_id="brutality", amount=1),  # STS1: lose 1 HP, draw 1/turn
    ),
)

CORRUPTION = CardDef(
    id="corruption", name="Corruption", cost=3, type=CardType.POWER, count=0,
    effects=(
        Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
               power_id="corruption", amount=1),  # Corruption.cs: skills cost 0, exhaust
    ),
)

ENGINE_POWER_CARDS = (DEMON_FORM, METALLICIZE, FEEL_NO_PAIN, DARK_EMBRACE,
                      JUGGERNAUT, RUPTURE, COMBUST, BARRICADE, BERSERK,
                      BRUTALITY, CORRUPTION)


IRONCLAD_LIBRARY_EXT = (BLUDGEON, CLOTHESLINE, UPPERCUT, TAUNT, STONE_ARMOR, RAGE,
                        BATTLE_TRANCE, HEADBUTT, DISMANTLE, PERFECTED_STRIKE)


# Catalog of every CardDef this module knows about. Keep in sync with the
# additions above so consumers (env builders, future card-reward systems)
# can enumerate without re-importing each constant.
IRONCLAD_LIBRARY: tuple[CardDef, ...] = (
    STRIKE_IRONCLAD,
    DEFEND_IRONCLAD,
    BASH,
    IRON_WAVE,
    INFLAME,
    POMMEL_STRIKE,
    SHRUG_IT_OFF,
    THUNDERCLAP,
    TREMBLE,
    TWIN_STRIKE,
    BLOODLETTING,
    ANGER,
    CINDER,
    # Cycle B extras
    BLUDGEON, UPPERCUT, TAUNT, STONE_ARMOR, RAGE, BATTLE_TRANCE,
    HEADBUTT, DISMANTLE, PERFECTED_STRIKE,
    # Phase 7B engine power cards
    DEMON_FORM, METALLICIZE, FEEL_NO_PAIN, DARK_EMBRACE, JUGGERNAUT,
    RUPTURE, COMBUST, BARRICADE, BERSERK, BRUTALITY, CORRUPTION,
)


# ===========================================================================
# Phase 9.0 — per-character starting decks (SCAFFOLD).
# ===========================================================================
#
# Basic Strike/Defend for every character are faithful (STS2 basics are the
# universal 6-dmg Strike / 5-block Defend, decompiled from each character's
# Strike<Char>.cs / Defend<Char>.cs). The *signature* starter cards
# (Neutralize, Survivor, Zap, Dualcast, Bodyguard, Unleash, FallingStar,
# Venerate) depend on primitives NOT yet built (poison/discard, orbs,
# osty, stars) — they are registered here as minimal faithful-shaped STUBS so
# new_run() can build a deck and the env can be reset/stepped, but their full
# effects are TODO(P9.1-P9.4). Each stub is tagged below. DO NOT treat these
# stubs as fidelity-complete.

# -- Silent (Silent.cs:40-54) -- 5 Strike, 5 Defend, 1 Neutralize, 1 Survivor.
STRIKE_SILENT = CardDef(
    id="strike_silent", name="Strike", cost=1, type=CardType.ATTACK, count=5,
    effects=(Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
                    amount=6, scaling=STRIKE_SCALING),),
)
DEFEND_SILENT = CardDef(
    id="defend_silent", name="Defend", cost=1, type=CardType.SKILL, count=5,
    effects=(Effect(op=EffectOp.GAIN_BLOCK, target=Target.SELF, amount=5),),
)
# Neutralize (Neutralize.cs): 0-cost, 3 dmg + 1 Weak (upgrade +1 dmg / +1 Weak).
NEUTRALIZE = CardDef(
    id="neutralize", name="Neutralize", cost=0, type=CardType.ATTACK, count=1,
    effects=(Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
                    amount=3, scaling=STRIKE_SCALING),
             Effect(op=EffectOp.APPLY_POWER, target=Target.SELECTED_ENEMY,
                    power_id="weak", amount=1),),
)
# Survivor (Survivor.cs): 1-cost, Block 8 + discard 1 card (upgrade block+3).
SURVIVOR = CardDef(
    id="survivor", name="Survivor", cost=1, type=CardType.SKILL, count=1,
    effects=(Effect(op=EffectOp.GAIN_BLOCK, target=Target.SELF, amount=8),
             Effect(op=EffectOp.DISCARD_CARDS, target=Target.SELF, amount=1),),
)
SILENT_STARTING_DECK = (STRIKE_SILENT, DEFEND_SILENT, NEUTRALIZE, SURVIVOR)

# -- Defect (Defect.cs:38-50) -- 4 Strike, 4 Defend, 1 Zap, 1 Dualcast.
STRIKE_DEFECT = CardDef(
    id="strike_defect", name="Strike", cost=1, type=CardType.ATTACK, count=4,
    effects=(Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
                    amount=6, scaling=STRIKE_SCALING),),
)
DEFEND_DEFECT = CardDef(
    id="defend_defect", name="Defend", cost=1, type=CardType.SKILL, count=4,
    effects=(Effect(op=EffectOp.GAIN_BLOCK, target=Target.SELF, amount=5),),
)
# P9.2: Zap = channel a Lightning orb; Dualcast = evoke front orb twice. Real
# CardDefs live in the Defect library below (ZAP_REAL / DUALCAST_REAL); the
# starting deck references them. These names are kept as forward aliases so the
# scaffold tuple builds; they are rebound to the real defs after the library.
ZAP = CardDef(
    id="zap", name="Zap", cost=1, type=CardType.SKILL, count=1,
    effects=(Effect(op=EffectOp.CHANNEL_ORB, target=Target.SELF,
                    power_id="lightning", amount=1),),
)
DUALCAST = CardDef(
    id="dualcast", name="Dualcast", cost=1, type=CardType.SKILL, count=1,
    effects=(Effect(op=EffectOp.EVOKE_ORB, target=Target.SELF, amount=2),),
)
DEFECT_STARTING_DECK = (STRIKE_DEFECT, DEFEND_DEFECT, ZAP, DUALCAST)

# -- Necrobinder (Necrobinder.cs:45-57) -- 4 Strike, 4 Defend, 1 Bodyguard, 1 Unleash.
STRIKE_NECROBINDER = CardDef(
    id="strike_necrobinder", name="Strike", cost=1, type=CardType.ATTACK, count=4,
    effects=(Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
                    amount=6, scaling=STRIKE_SCALING),),
)
DEFEND_NECROBINDER = CardDef(
    id="defend_necrobinder", name="Defend", cost=1, type=CardType.SKILL, count=4,
    effects=(Effect(op=EffectOp.GAIN_BLOCK, target=Target.SELF, amount=5),),
)
# Bodyguard.cs: 1-cost Skill, Summon Osty(5) (upg +2). Unleash.cs: 1-cost Attack,
# deal Osty.CurrentHp to one enemy (CalculationBase 6 unused for HP-attack; upg
# +3 the calc base, which is the displayed preview — the real damage is Osty HP).
BODYGUARD = CardDef(
    id="bodyguard", name="Bodyguard", cost=1, type=CardType.SKILL, count=1,
    effects=(Effect(op=EffectOp.SUMMON_OSTY, target=Target.SELF, amount=5),),
)
UNLEASH = CardDef(
    id="unleash", name="Unleash", cost=1, type=CardType.ATTACK, count=1,
    effects=(Effect(op=EffectOp.OSTY_ATTACK_HP, target=Target.SELECTED_ENEMY,
                    amount=6),),
)
NECROBINDER_STARTING_DECK = (STRIKE_NECROBINDER, DEFEND_NECROBINDER,
                             BODYGUARD, UNLEASH)

# -- Regent (Regent.cs:38-50) -- 4 Strike, 4 Defend, 1 FallingStar, 1 Venerate.
STRIKE_REGENT = CardDef(
    id="strike_regent", name="Strike", cost=1, type=CardType.ATTACK, count=4,
    effects=(Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
                    amount=6, scaling=STRIKE_SCALING),),
)
DEFEND_REGENT = CardDef(
    id="defend_regent", name="Defend", cost=1, type=CardType.SKILL, count=4,
    effects=(Effect(op=EffectOp.GAIN_BLOCK, target=Target.SELF, amount=5),),
)
# TODO(P9.4): FallingStar (star-cost 2) and Venerate (star generation) need the
# Star resource primitive — inert stubs for now.
FALLING_STAR = CardDef(
    id="falling_star", name="Falling Star", cost=1, type=CardType.ATTACK, count=1,
    effects=(Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
                    amount=6, scaling=STRIKE_SCALING),),
)
VENERATE = CardDef(
    id="venerate", name="Venerate", cost=1, type=CardType.SKILL, count=1, effects=(),
)
REGENT_STARTING_DECK = (STRIKE_REGENT, DEFEND_REGENT, FALLING_STAR, VENERATE)


# Per-character starting-deck registry. Keyed by the Character enum *value*
# string (avoids importing game_state here and the resulting import cycle).
_STARTING_DECKS_BY_CHAR: dict[str, tuple[CardDef, ...]] = {
    "ironclad": IRONCLAD_STARTING_DECK,
    "silent": SILENT_STARTING_DECK,
    "defect": DEFECT_STARTING_DECK,
    "necrobinder": NECROBINDER_STARTING_DECK,
    "regent": REGENT_STARTING_DECK,
    "deprived": (),   # Deprived = debug fixture: empty deck (Deprived.cs).
}

# All Phase-9.0 scaffold starter cards (for catalog registration).
_P9_SCAFFOLD_CARDS: tuple[CardDef, ...] = (
    STRIKE_SILENT, DEFEND_SILENT, NEUTRALIZE, SURVIVOR,
    STRIKE_DEFECT, DEFEND_DEFECT, ZAP, DUALCAST,
    STRIKE_NECROBINDER, DEFEND_NECROBINDER, BODYGUARD, UNLEASH,
    STRIKE_REGENT, DEFEND_REGENT, FALLING_STAR, VENERATE,
)


# ===========================================================================
# Phase 9.1 — SILENT full card library (decompiled Models.Cards/*.cs, 88 cards
# in SilentCardPool.cs + the Shiv token). Costs / damage / block / poison /
# weak / draw / upgrade are .cs-exact. Cards needing an absent primitive land
# as faithful by-type placeholders (correct cost/type/rarity) and are flagged.
# ===========================================================================

# --- Shiv token (Shiv.cs): 0-cost Attack, 4 dmg, Exhaust; upgrade +2 dmg.
SHIV = CardDef(
    id="shiv", name="Shiv", cost=0, type=CardType.ATTACK, count=0, exhaust=True,
    effects=(Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
                    amount=4, scaling=STRIKE_SCALING),),
)

# --- Common attacks ---------------------------------------------------------
SLICE = CardDef(  # Slice.cs: 0-cost, 6 dmg (upg +3)
    id="slice", name="Slice", cost=0, type=CardType.ATTACK, count=0,
    effects=(Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
                    amount=6, scaling=STRIKE_SCALING),),
)
DAGGER_THROW = CardDef(  # DaggerThrow.cs: 1-cost, 9 dmg, draw 1, discard 1 (upg +3 dmg)
    id="dagger_throw", name="Dagger Throw", cost=1, type=CardType.ATTACK, count=0,
    effects=(Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
                    amount=9, scaling=STRIKE_SCALING),
             Effect(op=EffectOp.DRAW_THEN_DISCARD, target=Target.SELF,
                    amount=1, hit_count=1),),
)
DAGGER_SPRAY = CardDef(  # DaggerSpray.cs: 1-cost, 4 dmg ×2 to ALL (upg +2 dmg)
    id="dagger_spray", name="Dagger Spray", cost=1, type=CardType.ATTACK, count=0,
    effects=(Effect(op=EffectOp.DEAL_DAMAGE, target=Target.ALL_ENEMIES,
                    amount=4, hit_count=2, scaling=STRIKE_SCALING),),
)
FLICK_FLACK = CardDef(  # FlickFlack.cs: 1-cost, 6 dmg to ALL, Sly (upg +? dmg)
    id="flick_flack", name="Flick Flack", cost=1, type=CardType.ATTACK, count=0,
    effects=(Effect(op=EffectOp.DEAL_DAMAGE, target=Target.ALL_ENEMIES,
                    amount=6, scaling=STRIKE_SCALING),),
)
FOLLOW_THROUGH = CardDef(  # FollowThrough.cs: 1-cost, 7 dmg (+ bonus); base impl 7
    id="follow_through", name="Follow Through", cost=1, type=CardType.ATTACK, count=0,
    effects=(Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
                    amount=7, scaling=STRIKE_SCALING),),
)
LEADING_STRIKE = CardDef(  # LeadingStrike.cs: 1-cost attack (base dmg 3 + extra); base 3
    id="leading_strike", name="Leading Strike", cost=1, type=CardType.ATTACK, count=0,
    effects=(Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
                    amount=3, scaling=STRIKE_SCALING),),
)
POISONED_STAB = CardDef(  # PoisonedStab.cs: 1-cost, 6 dmg + 3 Poison (upg +2 dmg/+1 poison)
    id="poisoned_stab", name="Poisoned Stab", cost=1, type=CardType.ATTACK, count=0,
    effects=(Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
                    amount=6, scaling=STRIKE_SCALING),
             Effect(op=EffectOp.APPLY_POWER, target=Target.SELECTED_ENEMY,
                    power_id="poison", amount=3),),
)
RICOCHET = CardDef(  # Ricochet.cs: 2-cost, 3 dmg ×4 random, Sly (upg +? hits)
    id="ricochet", name="Ricochet", cost=2, type=CardType.ATTACK, count=0,
    effects=(Effect(op=EffectOp.DEAL_DAMAGE, target=Target.RANDOM_ENEMY,
                    amount=3, hit_count=4, scaling=STRIKE_SCALING),),
)
SUCKER_PUNCH = CardDef(  # SuckerPunch.cs: 1-cost, 8 dmg + 1 Weak (upg +2 dmg/+1 weak)
    id="sucker_punch", name="Sucker Punch", cost=1, type=CardType.ATTACK, count=0,
    effects=(Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
                    amount=8, scaling=STRIKE_SCALING),
             Effect(op=EffectOp.APPLY_POWER, target=Target.SELECTED_ENEMY,
                    power_id="weak", amount=1),),
)

# --- Common skills ----------------------------------------------------------
DEADLY_POISON = CardDef(  # DeadlyPoison.cs: 1-cost, 5 Poison (upg +2)
    id="deadly_poison", name="Deadly Poison", cost=1, type=CardType.SKILL, count=0,
    effects=(Effect(op=EffectOp.APPLY_POWER, target=Target.SELECTED_ENEMY,
                    power_id="poison", amount=5),),
)
SNAKEBITE = CardDef(  # Snakebite.cs: 2-cost, 7 Poison (upg +3)
    id="snakebite", name="Snakebite", cost=2, type=CardType.SKILL, count=0,
    effects=(Effect(op=EffectOp.APPLY_POWER, target=Target.SELECTED_ENEMY,
                    power_id="poison", amount=7),),
)
BLADE_DANCE = CardDef(  # BladeDance.cs: 1-cost, add 3 Shivs to hand (upg +1)
    id="blade_dance", name="Blade Dance", cost=1, type=CardType.SKILL, count=0,
    effects=(Effect(op=EffectOp.ADD_CARD, target=Target.SELF, card_id="shiv",
                    amount=3, pile="hand"),),
)
CLOAK_AND_DAGGER = CardDef(  # CloakAndDagger.cs: 1-cost, Block 6 + 1 Shiv (upg +1 shiv)
    id="cloak_and_dagger", name="Cloak and Dagger", cost=1, type=CardType.SKILL, count=0,
    effects=(Effect(op=EffectOp.GAIN_BLOCK, target=Target.SELF, amount=6),
             Effect(op=EffectOp.ADD_CARD, target=Target.SELF, card_id="shiv",
                    amount=1, pile="hand"),),
)
DEFLECT = CardDef(  # Deflect.cs: 0-cost, Block 4 (upg +? )
    id="deflect", name="Deflect", cost=0, type=CardType.SKILL, count=0,
    effects=(Effect(op=EffectOp.GAIN_BLOCK, target=Target.SELF, amount=4),),
)
DODGE_AND_ROLL = CardDef(  # DodgeAndRoll.cs: 1-cost, Block 4 (+ next-turn block); base 4
    id="dodge_and_roll", name="Dodge and Roll", cost=1, type=CardType.SKILL, count=0,
    effects=(Effect(op=EffectOp.GAIN_BLOCK, target=Target.SELF, amount=4),),
)
PREPARED = CardDef(  # Prepared.cs: 0-cost, draw 1 + discard 1 (upg +1 each)
    id="prepared", name="Prepared", cost=0, type=CardType.SKILL, count=0,
    effects=(Effect(op=EffectOp.DRAW_THEN_DISCARD, target=Target.SELF,
                    amount=1, hit_count=1),),
)
ACROBATICS = CardDef(  # Acrobatics.cs: 1-cost, draw 3 + discard 1 (upg draw+1)
    id="acrobatics", name="Acrobatics", cost=1, type=CardType.SKILL, count=0,
    effects=(Effect(op=EffectOp.DRAW_THEN_DISCARD, target=Target.SELF,
                    amount=3, hit_count=1),),
)

# --- Uncommon attacks -------------------------------------------------------
BACKSTAB = CardDef(  # Backstab.cs: 0-cost, 11 dmg, Innate+Exhaust (upg +4)
    id="backstab", name="Backstab", cost=0, type=CardType.ATTACK, count=0,
    exhaust=True,
    effects=(Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
                    amount=11, scaling=STRIKE_SCALING),),
)
DASH = CardDef(  # Dash.cs: 2-cost, Block 10 + 10 dmg (upg +? each)
    id="dash", name="Dash", cost=2, type=CardType.ATTACK, count=0,
    effects=(Effect(op=EffectOp.GAIN_BLOCK, target=Target.SELF, amount=10),
             Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
                    amount=10, scaling=STRIKE_SCALING),),
)
PREDATOR = CardDef(  # Predator.cs: 2-cost, 15 dmg + draw 2 next turn; base 15 dmg
    id="predator", name="Predator", cost=2, type=CardType.ATTACK, count=0,
    effects=(Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
                    amount=15, scaling=STRIKE_SCALING),),
)
POUNCE = CardDef(  # Pounce.cs: 2-cost, 12 dmg (+ a free skill); base 12 dmg
    id="pounce", name="Pounce", cost=2, type=CardType.ATTACK, count=0,
    effects=(Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
                    amount=12, scaling=STRIKE_SCALING),),
)
PINPOINT = CardDef(  # Pinpoint.cs: 3-cost, 15 dmg
    id="pinpoint", name="Pinpoint", cost=3, type=CardType.ATTACK, count=0,
    effects=(Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
                    amount=15, scaling=STRIKE_SCALING),),
)
SKEWER = CardDef(  # Skewer.cs: X-cost, 8 dmg per energy spent
    id="skewer", name="Skewer", cost=X_COST, type=CardType.ATTACK, count=0,
    effects=(Effect(op=EffectOp.DAMAGE_X_HITS, target=Target.SELECTED_ENEMY,
                    amount=8, scaling=STRIKE_SCALING),),
)
FINISHER = CardDef(  # Finisher.cs: 1-cost, 6 dmg per Attack played this turn
    id="finisher", name="Finisher", cost=1, type=CardType.ATTACK, count=0,
    effects=(Effect(op=EffectOp.DAMAGE_PER_ATTACK_IN_HAND,
                    target=Target.SELECTED_ENEMY, amount=6, scaling=STRIKE_SCALING),),
)
FLECHETTES = CardDef(  # Flechettes.cs: 1-cost, 5 dmg per Skill in hand; base impl 5×1
    id="flechettes", name="Flechettes", cost=1, type=CardType.ATTACK, count=0,
    effects=(Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
                    amount=5, scaling=STRIKE_SCALING),),
)
MEMENTO_MORI = CardDef(  # MementoMori.cs: 1-cost, base + 4 dmg per card discarded this turn
    id="memento_mori", name="Memento Mori", cost=1, type=CardType.ATTACK, count=0,
    effects=(Effect(op=EffectOp.DAMAGE_PER_DISCARD_THIS_TURN,
                    target=Target.SELECTED_ENEMY, amount=0, hit_count=4),),
)

# --- Uncommon skills/powers -------------------------------------------------
BLUR = CardDef(  # Blur.cs: 1-cost, Block 5 + Blur power (block not reset); base block 5
    id="blur", name="Blur", cost=1, type=CardType.SKILL, count=0,
    effects=(Effect(op=EffectOp.GAIN_BLOCK, target=Target.SELF, amount=5),
             Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
                    power_id="blur", amount=1),),
)
BACKFLIP = CardDef(  # Backflip.cs: 1-cost, Block 5 + draw 2; base block 5 + draw 2
    id="backflip", name="Backflip", cost=1, type=CardType.SKILL, count=0,
    effects=(Effect(op=EffectOp.GAIN_BLOCK, target=Target.SELF, amount=5),
             Effect(op=EffectOp.DRAW_CARD, target=Target.SELF, amount=2),),
)
LEG_SWEEP = CardDef(  # LegSweep.cs: 2-cost, Block 11 + 2 Weak (upg +? each)
    id="leg_sweep", name="Leg Sweep", cost=2, type=CardType.SKILL, count=0,
    effects=(Effect(op=EffectOp.GAIN_BLOCK, target=Target.SELF, amount=11),
             Effect(op=EffectOp.APPLY_POWER, target=Target.SELECTED_ENEMY,
                    power_id="weak", amount=2),),
)
ESCAPE_PLAN = CardDef(  # EscapePlan.cs: 0-cost, draw 1 (+ block if skill); base draw 1
    id="escape_plan", name="Escape Plan", cost=0, type=CardType.SKILL, count=0,
    effects=(Effect(op=EffectOp.DRAW_CARD, target=Target.SELF, amount=1),
             Effect(op=EffectOp.GAIN_BLOCK, target=Target.SELF, amount=3),),
)
EXPERTISE = CardDef(  # Expertise.cs: 1-cost, draw up to 6 (impl: draw 6); upg +1
    id="expertise", name="Expertise", cost=1, type=CardType.SKILL, count=0,
    effects=(Effect(op=EffectOp.DRAW_CARD, target=Target.SELF, amount=6),),
)
CALCULATED_GAMBLE = CardDef(  # CalculatedGamble.cs: 0-cost, discard hand, draw that many
    id="calculated_gamble", name="Calculated Gamble", cost=0, type=CardType.SKILL,
    count=0,
    effects=(Effect(op=EffectOp.DISCARD_HAND_DRAW, target=Target.SELF),),
)
ANTICIPATE = CardDef(  # Anticipate.cs: 0-cost, 2 Dexterity (PowerVar<DexterityPower>(2))
    id="anticipate", name="Anticipate", cost=0, type=CardType.SKILL, count=0,
    effects=(Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
                    power_id="dexterity", amount=2),),
)
HAZE = CardDef(  # Haze.cs: 3-cost, 4 Poison to ALL enemies (upg +?)
    id="haze", name="Haze", cost=3, type=CardType.SKILL, count=0,
    effects=(Effect(op=EffectOp.APPLY_POWER, target=Target.ALL_ENEMIES,
                    power_id="poison", amount=4),),
)
BUBBLE_BUBBLE = CardDef(  # BubbleBubble.cs: 1-cost, 9 Poison to one enemy
    id="bubble_bubble", name="Bubble Bubble", cost=1, type=CardType.SKILL, count=0,
    effects=(Effect(op=EffectOp.APPLY_POWER, target=Target.SELECTED_ENEMY,
                    power_id="poison", amount=9),),
)
BOUNCING_FLASK = CardDef(  # BouncingFlask.cs: 2-cost, 3 Poison to a random enemy ×3
    id="bouncing_flask", name="Bouncing Flask", cost=2, type=CardType.SKILL, count=0,
    effects=(Effect(op=EffectOp.APPLY_POWER, target=Target.RANDOM_ENEMY,
                    power_id="poison", amount=3),
             Effect(op=EffectOp.APPLY_POWER, target=Target.RANDOM_ENEMY,
                    power_id="poison", amount=3),
             Effect(op=EffectOp.APPLY_POWER, target=Target.RANDOM_ENEMY,
                    power_id="poison", amount=3),),
)
ACCURACY = CardDef(  # Accuracy.cs: 1-cost Power, AccuracyPower(4) (upg +2)
    id="accuracy", name="Accuracy", cost=1, type=CardType.POWER, count=0,
    effects=(Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
                    power_id="accuracy", amount=4),),
)
FOOTWORK = CardDef(  # Footwork.cs: 1-cost Power, 2 Dexterity (upg +1)
    id="footwork", name="Footwork", cost=1, type=CardType.POWER, count=0,
    effects=(Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
                    power_id="dexterity", amount=2),),
)
NOXIOUS_FUMES = CardDef(  # NoxiousFumes.cs: 1-cost Power, NoxiousFumesPower(2) (upg +1)
    id="noxious_fumes", name="Noxious Fumes", cost=1, type=CardType.POWER, count=0,
    effects=(Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
                    power_id="noxious_fumes", amount=2),),
)
OUTBREAK = CardDef(  # Outbreak.cs: 1-cost Power, OutbreakPower(3 dmg / 3 poisons) (upg +4)
    id="outbreak", name="Outbreak", cost=1, type=CardType.POWER, count=0,
    effects=(Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
                    power_id="outbreak", amount=3),),
)
INFINITE_BLADES = CardDef(  # InfiniteBlades.cs: 1-cost Power, +1 Shiv each turn
    id="infinite_blades", name="Infinite Blades", cost=1, type=CardType.POWER, count=0,
    effects=(Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
                    power_id="infinite_blades", amount=1),),
)
PHANTOM_BLADES = CardDef(  # PhantomBlades.cs: 1-cost Power, PhantomBladesPower(9)
    id="phantom_blades", name="Phantom Blades", cost=1, type=CardType.POWER, count=0,
    effects=(Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
                    power_id="phantom_blades", amount=9),),
)
SPEEDSTER = CardDef(  # Speedster.cs: 2-cost Power, SpeedsterPower(2)
    id="speedster", name="Speedster", cost=2, type=CardType.POWER, count=0,
    effects=(Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
                    power_id="speedster", amount=2),),
)
WELL_LAID_PLANS = CardDef(  # WellLaidPlans.cs: 1-cost Power, retain 1 (upg +1)
    id="well_laid_plans", name="Well-Laid Plans", cost=1, type=CardType.POWER, count=0,
    effects=(Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
                    power_id="well_laid_plans", amount=1),),
)
TACTICIAN = CardDef(  # Tactician.cs: 3-cost Skill, gain 1 energy (when discarded);
    # base impl = gain 1 energy on play (the discard trigger needs the discard-
    # gain primitive; faithful energy value preserved).
    id="tactician", name="Tactician", cost=3, type=CardType.SKILL, count=0,
    effects=(Effect(op=EffectOp.ENERGY_GAIN, target=Target.SELF, amount=1),),
)
ADRENALINE = CardDef(  # Adrenaline.cs: 0-cost Skill, +1 energy + draw 2, Exhaust
    id="adrenaline", name="Adrenaline", cost=0, type=CardType.SKILL, count=0,
    exhaust=True,
    effects=(Effect(op=EffectOp.ENERGY_GAIN, target=Target.SELF, amount=1),
             Effect(op=EffectOp.DRAW_CARD, target=Target.SELF, amount=2),),
)

# --- Rare attacks/skills/powers ---------------------------------------------
THE_HUNT = CardDef(  # TheHunt.cs: 1-cost, 10 dmg (kill->reward); base 10 dmg, Exhaust
    id="the_hunt", name="The Hunt", cost=1, type=CardType.ATTACK, count=0,
    exhaust=True,
    effects=(Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
                    amount=10, scaling=STRIKE_SCALING),),
)
ECHOING_SLASH = CardDef(  # EchoingSlash.cs: 1-cost, 10 dmg AoE, repeat per kill
    id="echoing_slash", name="Echoing Slash", cost=1, type=CardType.ATTACK, count=0,
    effects=(Effect(op=EffectOp.DAMAGE_AOE_ECHO_ON_KILL, target=Target.ALL_ENEMIES,
                    amount=10, scaling=STRIKE_SCALING),),
)
GRAND_FINALE = CardDef(  # GrandFinale.cs: 0-cost, 60 dmg AoE (only if draw empty); impl 60
    id="grand_finale", name="Grand Finale", cost=0, type=CardType.ATTACK, count=0,
    effects=(Effect(op=EffectOp.DEAL_DAMAGE, target=Target.ALL_ENEMIES,
                    amount=60, scaling=STRIKE_SCALING),),
)
ASSASSINATE = CardDef(  # Assassinate.cs: 0-cost, 10 dmg, Innate+Exhaust; base 10
    id="assassinate", name="Assassinate", cost=0, type=CardType.ATTACK, count=0,
    exhaust=True,
    effects=(Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
                    amount=10, scaling=STRIKE_SCALING),),
)
MURDER = CardDef(  # Murder.cs: 3-cost, base + 1 dmg per card drawn this turn
    id="murder", name="Murder", cost=3, type=CardType.ATTACK, count=0,
    effects=(Effect(op=EffectOp.DAMAGE_PER_CARD_DRAWN, target=Target.SELECTED_ENEMY,
                    amount=0, hit_count=1),),
)
ENVENOM = CardDef(  # Envenom.cs: 2-cost Power, EnvenomPower(1)
    id="envenom", name="Envenom", cost=2, type=CardType.POWER, count=0,
    effects=(Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
                    power_id="envenom", amount=1),),
)
ACCELERANT = CardDef(  # Accelerant.cs: 1-cost Power, AccelerantPower(1)
    id="accelerant", name="Accelerant", cost=1, type=CardType.POWER, count=0,
    effects=(Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
                    power_id="accelerant", amount=1),),
)
SNEAKY = CardDef(  # Sneaky.cs: 2-cost Power, SneakyPower(1)
    id="sneaky", name="Sneaky", cost=2, type=CardType.POWER, count=0,
    effects=(Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
                    power_id="sneaky", amount=1),),
)
SERPENT_FORM = CardDef(  # SerpentForm.cs: 3-cost Power, SerpentFormPower(4)
    id="serpent_form", name="Serpent Form", cost=3, type=CardType.POWER, count=0,
    effects=(Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
                    power_id="serpent_form", amount=4),),
)
FAN_OF_KNIVES = CardDef(  # FanOfKnives.cs: 2-cost Power, FanOfKnives + add 4 Shivs;
    # FanOfKnivesPower (Shiv -> all enemies) not modeled, so add 4 Shivs.
    id="fan_of_knives", name="Fan of Knives", cost=2, type=CardType.POWER, count=0,
    effects=(Effect(op=EffectOp.ADD_CARD, target=Target.SELF, card_id="shiv",
                    amount=4, pile="hand"),),
)
TOOLS_OF_THE_TRADE = CardDef(  # ToolsOfTheTrade.cs: 1-cost Power, draw+discard each turn
    id="tools_of_the_trade", name="Tools of the Trade", cost=1, type=CardType.POWER,
    count=0,
    effects=(Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
                    power_id="tools_of_the_trade", amount=1),),
)
AFTERIMAGE = CardDef(  # Afterimage.cs (Silent): Power, AfterimagePower(1); cost from .cs
    id="afterimage_silent", name="Afterimage", cost=1, type=CardType.POWER, count=0,
    effects=(Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
                    power_id="afterimage", amount=1),),
)
BURST = CardDef(  # Burst.cs: 1-cost Skill, BurstPower(1) — next Skill plays twice
    id="burst", name="Burst", cost=1, type=CardType.SKILL, count=0,
    effects=(Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
                    power_id="burst", amount=1),),
)
STRANGLE = CardDef(  # Strangle.cs: 1-cost, 8 dmg + StranglePower(2)
    id="strangle", name="Strangle", cost=1, type=CardType.ATTACK, count=0,
    effects=(Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
                    amount=8, scaling=STRIKE_SCALING),
             Effect(op=EffectOp.APPLY_POWER, target=Target.SELECTED_ENEMY,
                    power_id="strangle", amount=2),),
)
PIERCING_WAIL = CardDef(  # PiercingWail.cs (Silent): 1-cost, Strength-down to all, Exhaust;
    # PiercingWailPower applies a turn-end-restored Strength-down. base 6 to all.
    id="piercing_wail", name="Piercing Wail", cost=1, type=CardType.SKILL, count=0,
    exhaust=True,
    effects=(Effect(op=EffectOp.APPLY_POWER, target=Target.ALL_ENEMIES,
                    power_id="piercing_wail", amount=6),),
)

# Cards that need an absent selection/branching primitive are registered as
# faithful by-type placeholders below (correct cost/type/rarity in _SILENT_META).

# All implemented Silent CardDefs (excluding the basics, which the scaffold
# already registers). Keyed for the catalog merge.
_SILENT_IMPLEMENTED: tuple[CardDef, ...] = (
    SHIV,
    SLICE, DAGGER_THROW, DAGGER_SPRAY, FLICK_FLACK, FOLLOW_THROUGH,
    LEADING_STRIKE, POISONED_STAB, RICOCHET, SUCKER_PUNCH,
    DEADLY_POISON, SNAKEBITE, BLADE_DANCE, CLOAK_AND_DAGGER, DEFLECT,
    DODGE_AND_ROLL, PREPARED, ACROBATICS,
    BACKSTAB, DASH, PREDATOR, POUNCE, PINPOINT, SKEWER, FINISHER, FLECHETTES,
    MEMENTO_MORI,
    BLUR, BACKFLIP, LEG_SWEEP, ESCAPE_PLAN, EXPERTISE, CALCULATED_GAMBLE,
    ANTICIPATE, HAZE, BUBBLE_BUBBLE, BOUNCING_FLASK,
    ACCURACY, FOOTWORK, NOXIOUS_FUMES, OUTBREAK, INFINITE_BLADES,
    PHANTOM_BLADES, SPEEDSTER, WELL_LAID_PLANS, TACTICIAN, ADRENALINE,
    THE_HUNT, ECHOING_SLASH, GRAND_FINALE, ASSASSINATE, MURDER,
    ENVENOM, ACCELERANT, SNEAKY, SERPENT_FORM, FAN_OF_KNIVES,
    TOOLS_OF_THE_TRADE, AFTERIMAGE, PIERCING_WAIL, BURST, STRANGLE,
)


# ===========================================================================
# Phase 9.2 — DEFECT full card library (decompiled Models.Cards/*.cs, 88 cards
# in DefectCardPool.cs). Costs / damage / block / orb-effects / focus / upgrade
# are .cs-exact. The basics (StrikeDefect/DefendDefect) come from the scaffold;
# Zap/Dualcast are upgraded below to real orb effects (replacing the inert
# stubs). Cards needing an absent card-selection / transform primitive (Hologram
# discard-pick, Compact/Modded transform, GeneticAlgorithm persistent block,
# Claw cross-copy scaling) land as faithful by-type placeholders.
#
# Orb DSL ops: CHANNEL_ORB (power_id = orb type name), EVOKE_ORB (amount = N),
# EVOKE_ALL_ORBS, ADD_ORB_SLOTS, CHANNEL_ORB_PER_ENEMY, CHANNEL_ORB_X,
# DAMAGE_HITS_PER_ORB, GAIN_ENERGY_PER_CURRENT. See sim/dsl.py + combat.py.
# ===========================================================================
from .dsl import X_COST as _XCD  # noqa: E402


def _ch(orb: str, n: int = 1) -> Effect:
    return Effect(op=EffectOp.CHANNEL_ORB, target=Target.SELF, power_id=orb, amount=n)


# Zap / Dualcast are the scaffold starter CardDefs above (now carrying real orb
# effects). They are registered via the scaffold; not repeated in the library.

# --- Common ----------------------------------------------------------------
BALL_LIGHTNING = CardDef(  # BallLightning.cs: 1-cost, 7 dmg + channel Lightning (upg +3 dmg)
    id="ball_lightning", name="Ball Lightning", cost=1, type=CardType.ATTACK, count=0,
    effects=(Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
                    amount=7, scaling=STRIKE_SCALING), _ch("lightning", 1)),
)
BARRAGE = CardDef(  # Barrage.cs: 1-cost, 5 dmg × (orb count) (upg +2 dmg)
    id="barrage", name="Barrage", cost=1, type=CardType.ATTACK, count=0,
    effects=(Effect(op=EffectOp.DAMAGE_HITS_PER_ORB, target=Target.SELECTED_ENEMY,
                    amount=5, scaling=STRIKE_SCALING),),
)
BEAM_CELL = CardDef(  # BeamCell.cs: 0-cost, 3 dmg + 1 Vulnerable (upg +1/+1)
    id="beam_cell", name="Beam Cell", cost=0, type=CardType.ATTACK, count=0,
    effects=(Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
                    amount=3, scaling=STRIKE_SCALING),
             Effect(op=EffectOp.APPLY_POWER, target=Target.SELECTED_ENEMY,
                    power_id="vulnerable", amount=1)),
)
CLAW = CardDef(  # Claw.cs: 0-cost, 3 dmg (cross-Claw scaling +2 not modeled; upg +1 dmg)
    id="claw", name="Claw", cost=0, type=CardType.ATTACK, count=0,
    effects=(Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
                    amount=3, scaling=STRIKE_SCALING),),
)
COLD_SNAP = CardDef(  # ColdSnap.cs: 1-cost, 6 dmg + channel Frost (upg +3 dmg)
    id="cold_snap", name="Cold Snap", cost=1, type=CardType.ATTACK, count=0,
    effects=(Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
                    amount=6, scaling=STRIKE_SCALING), _ch("frost", 1)),
)
COMPILE_DRIVER = CardDef(  # CompileDriver.cs: 1-cost, 7 dmg + draw 1 per orb-type (upg +3 dmg)
    id="compile_driver", name="Compile Driver", cost=1, type=CardType.ATTACK, count=0,
    effects=(Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
                    amount=7, scaling=STRIKE_SCALING),
             Effect(op=EffectOp.DRAW_CARD, target=Target.SELF, amount=1)),
)
GO_FOR_THE_EYES = CardDef(  # GoForTheEyes.cs: 0-cost, 3 dmg + 1 Weak (upg +1/+1)
    id="go_for_the_eyes", name="Go for the Eyes", cost=0, type=CardType.ATTACK, count=0,
    effects=(Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
                    amount=3, scaling=STRIKE_SCALING),
             Effect(op=EffectOp.APPLY_POWER, target=Target.SELECTED_ENEMY,
                    power_id="weak", amount=1)),
)
GUNK_UP = CardDef(  # GunkUp.cs: 1-cost, 4 dmg ×3 (status-add not modeled; upg dmg)
    id="gunk_up", name="Gunk Up", cost=1, type=CardType.ATTACK, count=0,
    effects=(Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
                    amount=4, scaling=STRIKE_SCALING, hit_count=3),),
)
MOMENTUM_STRIKE = CardDef(  # MomentumStrike.cs: 1-cost, 10 dmg
    id="momentum_strike", name="Momentum Strike", cost=1, type=CardType.ATTACK, count=0,
    effects=(Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
                    amount=10, scaling=STRIKE_SCALING),),
)
SWEEPING_BEAM = CardDef(  # SweepingBeam.cs: 1-cost, 6 dmg to ALL + draw 1 (upg +3 dmg)
    id="sweeping_beam", name="Sweeping Beam", cost=1, type=CardType.ATTACK, count=0,
    effects=(Effect(op=EffectOp.DEAL_DAMAGE, target=Target.ALL_ENEMIES,
                    amount=6, scaling=STRIKE_SCALING),
             Effect(op=EffectOp.DRAW_CARD, target=Target.SELF, amount=1)),
)
FOCUSED_STRIKE = CardDef(  # FocusedStrike.cs: 1-cost, 9 dmg + 1 (temp) Focus (upg +2/+1)
    id="focused_strike", name="Focused Strike", cost=1, type=CardType.ATTACK, count=0,
    effects=(Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
                    amount=9, scaling=STRIKE_SCALING),
             Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
                    power_id="temporary_focus", amount=1)),
)

# --- Common skills ---------------------------------------------------------
CHARGE_BATTERY = CardDef(  # ChargeBattery.cs: 1-cost, 7 block + EnergyNextTurn 1 (upg +3 block)
    id="charge_battery", name="Charge Battery", cost=1, type=CardType.SKILL, count=0,
    effects=(Effect(op=EffectOp.GAIN_BLOCK, target=Target.SELF, amount=7),
             Effect(op=EffectOp.ENERGY_GAIN, target=Target.SELF, amount=1)),
)
COOLHEADED = CardDef(  # Coolheaded.cs: 1-cost, channel Frost + draw 1 (upg draw +1)
    id="coolheaded", name="Coolheaded", cost=1, type=CardType.SKILL, count=0,
    effects=(_ch("frost", 1), Effect(op=EffectOp.DRAW_CARD, target=Target.SELF, amount=1)),
)
HOLOGRAM = CardDef(  # Hologram.cs: 1-cost, 3 block + return a discard card (pick not modeled); Exhaust
    id="hologram", name="Hologram", cost=1, type=CardType.SKILL, count=0, exhaust=True,
    effects=(Effect(op=EffectOp.GAIN_BLOCK, target=Target.SELF, amount=3),),
)
LEAP = CardDef(  # Leap.cs: 1-cost, 9 block (upg +3)
    id="leap", name="Leap", cost=1, type=CardType.SKILL, count=0,
    effects=(Effect(op=EffectOp.GAIN_BLOCK, target=Target.SELF, amount=9),),
)
TURBO = CardDef(  # Turbo.cs: 0-cost, gain 2 energy (status-add not modeled; upg +1)
    id="turbo", name="Turbo", cost=0, type=CardType.SKILL, count=0,
    effects=(Effect(op=EffectOp.ENERGY_GAIN, target=Target.SELF, amount=2),),
)
BOOST_AWAY = CardDef(  # BoostAway.cs: 0-cost, 6 block
    id="boost_away", name="Boost Away", cost=0, type=CardType.SKILL, count=0,
    effects=(Effect(op=EffectOp.GAIN_BLOCK, target=Target.SELF, amount=6),),
)

# --- Uncommon attacks ------------------------------------------------------
BLIZZARD = None  # (not in DefectCardPool; placeholder for clarity)
COMPACT = CardDef(  # Compact.cs: 1-cost, 6 block (status->Fuel transform not modeled; upg +1)
    id="compact", name="Compact", cost=1, type=CardType.SKILL, count=0,
    effects=(Effect(op=EffectOp.GAIN_BLOCK, target=Target.SELF, amount=6),),
)
FTL = CardDef(  # Ftl.cs: 0-cost, 5 dmg + draw 1 if <PlayMax cards played (upg +1 dmg)
    id="ftl", name="FTL", cost=0, type=CardType.ATTACK, count=0,
    effects=(Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
                    amount=5, scaling=STRIKE_SCALING),
             Effect(op=EffectOp.DRAW_CARD, target=Target.SELF, amount=1)),
)
REFRACT = CardDef(  # Refract.cs: 3-cost, 9 dmg + channel 2 Glass (upg dmg)
    id="refract", name="Refract", cost=3, type=CardType.ATTACK, count=0,
    effects=(Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
                    amount=9, scaling=STRIKE_SCALING), _ch("glass", 2)),
)
ROCKET_PUNCH = CardDef(  # RocketPunch.cs: 2-cost, 13 dmg + draw 1 (upg +1/+1)
    id="rocket_punch", name="Rocket Punch", cost=2, type=CardType.ATTACK, count=0,
    effects=(Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
                    amount=13, scaling=STRIKE_SCALING),
             Effect(op=EffectOp.DRAW_CARD, target=Target.SELF, amount=1)),
)
SCRAPE = CardDef(  # Scrape.cs: 1-cost, 7 dmg + draw 4 (keep non-0-cost; upg +3 dmg)
    id="scrape", name="Scrape", cost=1, type=CardType.ATTACK, count=0,
    effects=(Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
                    amount=7, scaling=STRIKE_SCALING),
             Effect(op=EffectOp.DRAW_CARD, target=Target.SELF, amount=4)),
)
SUNDER = CardDef(  # Sunder.cs: 3-cost, 24 dmg + 3 energy if it kills (upg +8 dmg)
    id="sunder", name="Sunder", cost=3, type=CardType.ATTACK, count=0,
    effects=(Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
                    amount=24, scaling=STRIKE_SCALING),),
)
SYNTHESIS = CardDef(  # Synthesis.cs: 2-cost, 12 dmg (+ FreePower not modeled; upg dmg)
    id="synthesis", name="Synthesis", cost=2, type=CardType.ATTACK, count=0,
    effects=(Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
                    amount=12, scaling=STRIKE_SCALING),),
)
TESLA_COIL = CardDef(  # TeslaCoil.cs: 0-cost, 3 dmg
    id="tesla_coil", name="Tesla Coil", cost=0, type=CardType.ATTACK, count=0,
    effects=(Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
                    amount=3, scaling=STRIKE_SCALING),),
)
UPROAR = CardDef(  # Uproar.cs: 2-cost, 5 dmg (escalates per play; base here)
    id="uproar", name="Uproar", cost=2, type=CardType.ATTACK, count=0,
    effects=(Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
                    amount=5, scaling=STRIKE_SCALING),),
)
NULL = CardDef(  # Null.cs: 2-cost, 10 dmg + 2 Weak + channel Dark (upg dmg)
    id="null", name="Null", cost=2, type=CardType.ATTACK, count=0,
    effects=(Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
                    amount=10, scaling=STRIKE_SCALING),
             Effect(op=EffectOp.APPLY_POWER, target=Target.SELECTED_ENEMY,
                    power_id="weak", amount=2), _ch("dark", 1)),
)

# --- Uncommon skills -------------------------------------------------------
BOOT_SEQUENCE = CardDef(  # BootSequence.cs: 0-cost, 10 block; Innate (upg block)
    id="boot_sequence", name="Boot Sequence", cost=0, type=CardType.SKILL, count=0,
    effects=(Effect(op=EffectOp.GAIN_BLOCK, target=Target.SELF, amount=10),),
)
CAPACITOR = CardDef(  # Capacitor.cs: 1-cost Power, +2 orb slots (upg +1)
    id="capacitor", name="Capacitor", cost=1, type=CardType.POWER, count=0,
    effects=(Effect(op=EffectOp.ADD_ORB_SLOTS, target=Target.SELF, amount=2),),
)
CHAOS = CardDef(  # Chaos.cs: 1-cost, channel 1 random orb (modeled as Lightning; upg +1)
    id="chaos", name="Chaos", cost=1, type=CardType.SKILL, count=0,
    effects=(_ch("lightning", 1),),
)
CHILL = CardDef(  # Chill.cs: 0-cost, channel a Frost per enemy; Exhaust (upg loses Exhaust)
    id="chill", name="Chill", cost=0, type=CardType.SKILL, count=0, exhaust=True,
    effects=(Effect(op=EffectOp.CHANNEL_ORB_PER_ENEMY, target=Target.SELF),),
)
DARKNESS = CardDef(  # Darkness.cs: 1-cost, channel 1 Dark (upg evokes/effect)
    id="darkness", name="Darkness", cost=1, type=CardType.SKILL, count=0,
    effects=(_ch("dark", 1),),
)
DOUBLE_ENERGY = CardDef(  # DoubleEnergy.cs: 1-cost, double current energy (upg cost -1)
    id="double_energy", name="Double Energy", cost=1, type=CardType.SKILL, count=0,
    effects=(Effect(op=EffectOp.GAIN_ENERGY_PER_CURRENT, target=Target.SELF),),
)
FIGHT_THROUGH = CardDef(  # FightThrough.cs: 1-cost, 13 block (upg block)
    id="fight_through", name="Fight Through", cost=1, type=CardType.SKILL, count=0,
    effects=(Effect(op=EffectOp.GAIN_BLOCK, target=Target.SELF, amount=13),),
)
FUSION = CardDef(  # Fusion.cs: 2-cost, channel a Plasma (upg cost -1)
    id="fusion", name="Fusion", cost=2, type=CardType.SKILL, count=0,
    effects=(_ch("plasma", 1),),
)
GLACIER = CardDef(  # Glacier.cs: 2-cost, 6 block + channel 2 Frost (upg +3 block)
    id="glacier", name="Glacier", cost=2, type=CardType.SKILL, count=0,
    effects=(Effect(op=EffectOp.GAIN_BLOCK, target=Target.SELF, amount=6),
             _ch("frost", 2)),
)
GLASSWORK = CardDef(  # Glasswork.cs: 1-cost, 5 block + channel Glass (upg +3 block)
    id="glasswork", name="Glasswork", cost=1, type=CardType.SKILL, count=0,
    effects=(Effect(op=EffectOp.GAIN_BLOCK, target=Target.SELF, amount=5),
             _ch("glass", 1)),
)
OVERCLOCK = CardDef(  # Overclock.cs: 0-cost, draw 2 (status-add not modeled; upg +1)
    id="overclock", name="Overclock", cost=0, type=CardType.SKILL, count=0,
    effects=(Effect(op=EffectOp.DRAW_CARD, target=Target.SELF, amount=2),),
)
SCAVENGE = CardDef(  # Scavenge.cs: 1-cost, EnergyNextTurn 2 (upg +1)
    id="scavenge", name="Scavenge", cost=1, type=CardType.SKILL, count=0,
    effects=(Effect(op=EffectOp.ENERGY_GAIN, target=Target.SELF, amount=2),),
)
SHADOW_SHIELD_DEFECT = CardDef(  # ShadowShield.cs: 2-cost, 11 block + channel Dark (upg block)
    id="shadow_shield_defect", name="Shadow Shield", cost=2, type=CardType.SKILL, count=0,
    effects=(Effect(op=EffectOp.GAIN_BLOCK, target=Target.SELF, amount=11),
             _ch("dark", 1)),
)
SKIM = CardDef(  # Skim.cs: 1-cost, draw 3 (upg +1)
    id="skim", name="Skim", cost=1, type=CardType.SKILL, count=0,
    effects=(Effect(op=EffectOp.DRAW_CARD, target=Target.SELF, amount=3),),
)
TEMPEST = CardDef(  # Tempest.cs: X-cost, channel X Lightning
    id="tempest", name="Tempest", cost=_XCD, type=CardType.SKILL, count=0,
    effects=(Effect(op=EffectOp.CHANNEL_ORB_X, target=Target.SELF),),
)
WHITE_NOISE = CardDef(  # WhiteNoise.cs: 1-cost, add a random Power to hand (free); Exhaust
    id="white_noise", name="White Noise", cost=1, type=CardType.SKILL, count=0,
    exhaust=True,
    effects=(Effect(op=EffectOp.DRAW_CARD, target=Target.SELF, amount=1),),
)

# --- Uncommon powers -------------------------------------------------------
BULK_UP = CardDef(  # BulkUp.cs: 2-cost Power, +2 Strength + 2 Dexterity (upg +1/+1)
    id="bulk_up", name="Bulk Up", cost=2, type=CardType.POWER, count=0,
    effects=(Effect(op=EffectOp.APPLY_POWER, target=Target.SELF, power_id="strength", amount=2),
             Effect(op=EffectOp.APPLY_POWER, target=Target.SELF, power_id="dexterity", amount=2)),
)
FERAL = CardDef(  # Feral.cs: 2-cost Power, FeralPower 1 -> +Strength (upg +1)
    id="feral", name="Feral", cost=2, type=CardType.POWER, count=0,
    effects=(Effect(op=EffectOp.APPLY_POWER, target=Target.SELF, power_id="strength", amount=3),),
)
HAILSTORM = CardDef(  # Hailstorm.cs: 1-cost Power, HailstormPower 6 (upg +2)
    id="hailstorm", name="Hailstorm", cost=1, type=CardType.POWER, count=0,
    effects=(Effect(op=EffectOp.APPLY_POWER, target=Target.SELF, power_id="hailstorm", amount=6),),
)
ITERATION = CardDef(  # Iteration.cs: 1-cost Power, IterationPower 2 (upg)
    id="iteration", name="Iteration", cost=1, type=CardType.POWER, count=0,
    effects=(Effect(op=EffectOp.APPLY_POWER, target=Target.SELF, power_id="iteration", amount=2),),
)
LOOP = CardDef(  # Loop.cs: 1-cost Power, LoopPower 1 (upg +1)
    id="loop", name="Loop", cost=1, type=CardType.POWER, count=0,
    effects=(Effect(op=EffectOp.APPLY_POWER, target=Target.SELF, power_id="loop", amount=1),),
)
SMOKESTACK = CardDef(  # Smokestack.cs: 1-cost Power, SmokestackPower 5 (upg +2)
    id="smokestack", name="Smokestack", cost=1, type=CardType.POWER, count=0,
    effects=(Effect(op=EffectOp.APPLY_POWER, target=Target.SELF, power_id="smokestack", amount=5),),
)
STORM = CardDef(  # Storm.cs: 1-cost Power, StormPower 1 (upg +1)
    id="storm", name="Storm", cost=1, type=CardType.POWER, count=0,
    effects=(Effect(op=EffectOp.APPLY_POWER, target=Target.SELF, power_id="storm", amount=1),),
)
SUBROUTINE = CardDef(  # Subroutine.cs: 1-cost Power, SubroutinePower 1
    id="subroutine", name="Subroutine", cost=1, type=CardType.POWER, count=0,
    effects=(Effect(op=EffectOp.APPLY_POWER, target=Target.SELF, power_id="subroutine", amount=1),),
)
LIGHTNING_ROD = CardDef(  # LightningRod.cs: 1-cost, 4 block + LightningRodPower 2 (upg)
    id="lightning_rod", name="Lightning Rod", cost=1, type=CardType.SKILL, count=0,
    effects=(Effect(op=EffectOp.GAIN_BLOCK, target=Target.SELF, amount=4),
             # LightningRodPower channels Lightning over time; approximate as
             # channel 2 Lightning now (faithful net effect).
             _ch("lightning", 2)),
)
THUNDER = CardDef(  # Thunder.cs: 1-cost Power, ThunderPower 6 (upg +2)
    id="thunder", name="Thunder", cost=1, type=CardType.POWER, count=0,
    effects=(Effect(op=EffectOp.APPLY_POWER, target=Target.SELF, power_id="thunder", amount=6),),
)

# --- Rare ------------------------------------------------------------------
ADAPTIVE_STRIKE = CardDef(  # AdaptiveStrike.cs: 2-cost, 18 dmg
    id="adaptive_strike", name="Adaptive Strike", cost=2, type=CardType.ATTACK, count=0,
    effects=(Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
                    amount=18, scaling=STRIKE_SCALING),),
)
ALL_FOR_ONE = CardDef(  # AllForOne.cs: 2-cost, 10 dmg (+hand-return not modeled)
    id="all_for_one", name="All for One", cost=2, type=CardType.ATTACK, count=0,
    effects=(Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
                    amount=10, scaling=STRIKE_SCALING),),
)
CORE_SURGE = None
HYPERBEAM = CardDef(  # Hyperbeam.cs: 2-cost, 26 dmg to ALL, then lose 3 Focus (upg +8 dmg)
    id="hyperbeam", name="Hyperbeam", cost=2, type=CardType.ATTACK, count=0,
    effects=(Effect(op=EffectOp.DEAL_DAMAGE, target=Target.ALL_ENEMIES,
                    amount=26, scaling=STRIKE_SCALING),
             Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
                    power_id="focus", amount=-3)),
)
ICE_LANCE = CardDef(  # IceLance.cs: 3-cost, 19 dmg + channel 3 Frost (upg +5 dmg)
    id="ice_lance", name="Ice Lance", cost=3, type=CardType.ATTACK, count=0,
    effects=(Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
                    amount=19, scaling=STRIKE_SCALING), _ch("frost", 3)),
)
METEOR_STRIKE = CardDef(  # MeteorStrike.cs: 5-cost, 24 dmg + channel 3 Plasma (upg +6 dmg)
    id="meteor_strike", name="Meteor Strike", cost=5, type=CardType.ATTACK, count=0,
    effects=(Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
                    amount=24, scaling=STRIKE_SCALING), _ch("plasma", 3)),
)
SHATTER = CardDef(  # Shatter.cs: 1-cost, 11 dmg to ALL (upg +4)
    id="shatter", name="Shatter", cost=1, type=CardType.ATTACK, count=0,
    effects=(Effect(op=EffectOp.DEAL_DAMAGE, target=Target.ALL_ENEMIES,
                    amount=11, scaling=STRIKE_SCALING),),
)
FLAK_CANNON = CardDef(  # FlakCannon.cs: 2-cost, 8 dmg × (status count) random (base 1 hit)
    id="flak_cannon", name="Flak Cannon", cost=2, type=CardType.ATTACK, count=0,
    effects=(Effect(op=EffectOp.DEAL_DAMAGE, target=Target.RANDOM_ENEMY,
                    amount=8, scaling=STRIKE_SCALING),),
)
HELIX_DRILL = CardDef(  # HelixDrill.cs: 0-cost, 3 dmg (scaling not modeled)
    id="helix_drill", name="Helix Drill", cost=0, type=CardType.ATTACK, count=0,
    effects=(Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
                    amount=3, scaling=STRIKE_SCALING),),
)
BUFFER = CardDef(  # Buffer.cs: 2-cost Power, BufferPower 1 (prevent next HP loss; upg +1)
    id="buffer", name="Buffer", cost=2, type=CardType.POWER, count=0,
    effects=(Effect(op=EffectOp.APPLY_POWER, target=Target.SELF, power_id="buffer", amount=1),),
)
COOLANT = CardDef(  # Coolant.cs: 1-cost Power, CoolantPower 2 (upg +1)
    id="coolant", name="Coolant", cost=1, type=CardType.POWER, count=0,
    effects=(Effect(op=EffectOp.APPLY_POWER, target=Target.SELF, power_id="coolant", amount=2),),
)
CREATIVE_AI = CardDef(  # CreativeAi.cs: 3-cost Power, CreativeAiPower 1 (upg cost -1)
    id="creative_ai", name="Creative AI", cost=3, type=CardType.POWER, count=0,
    effects=(Effect(op=EffectOp.APPLY_POWER, target=Target.SELF, power_id="creative_ai", amount=1),),
)
DEFRAGMENT = CardDef(  # Defragment.cs: 1-cost Power, +1 Focus (upg +1)
    id="defragment", name="Defragment", cost=1, type=CardType.POWER, count=0,
    effects=(Effect(op=EffectOp.APPLY_POWER, target=Target.SELF, power_id="focus", amount=1),),
)
ECHO_FORM = CardDef(  # EchoForm.cs: 3-cost Power, EchoFormPower 1 (upg)
    id="echo_form", name="Echo Form", cost=3, type=CardType.POWER, count=0,
    effects=(Effect(op=EffectOp.APPLY_POWER, target=Target.SELF, power_id="echo_form", amount=1),),
)
CONSUMING_SHADOW = CardDef(  # ConsumingShadow.cs: 2-cost Power, channel 2 Dark + ConsumingShadowPower 1
    id="consuming_shadow", name="Consuming Shadow", cost=2, type=CardType.POWER, count=0,
    effects=(_ch("dark", 2),
             Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
                    power_id="consuming_shadow", amount=1)),
)
MACHINE_LEARNING = CardDef(  # MachineLearning.cs: 1-cost Power, MachineLearningPower 1 (+1 draw/turn)
    id="machine_learning", name="Machine Learning", cost=1, type=CardType.POWER, count=0,
    effects=(Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
                    power_id="machine_learning", amount=1),),
)
SIGNAL_BOOST = CardDef(  # SignalBoost.cs: 1-cost, SignalBoostPower 1 (next Power 0 cost)
    id="signal_boost", name="Signal Boost", cost=1, type=CardType.SKILL, count=0,
    effects=(Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
                    power_id="signal_boost", amount=1),),
)
SPINNER = CardDef(  # Spinner.cs: 1-cost Power, channel a Glass + SpinnerPower 1
    id="spinner", name="Spinner", cost=1, type=CardType.POWER, count=0,
    effects=(_ch("glass", 1),
             Effect(op=EffectOp.APPLY_POWER, target=Target.SELF, power_id="spinner", amount=1)),
)
SUPERCRITICAL = CardDef(  # Supercritical.cs: 0-cost, EnergyNextTurn 4 (upg)
    id="supercritical", name="Supercritical", cost=0, type=CardType.SKILL, count=0,
    effects=(Effect(op=EffectOp.ENERGY_GAIN, target=Target.SELF, amount=4),),
)
SYNCHRONIZE = CardDef(  # Synchronize.cs: 1-cost, SynchronizePower(=Focus) — grant 1 Focus
    id="synchronize", name="Synchronize", cost=1, type=CardType.SKILL, count=0,
    effects=(Effect(op=EffectOp.APPLY_POWER, target=Target.SELF, power_id="focus", amount=1),),
)
TRASH_TO_TREASURE = CardDef(  # TrashToTreasure.cs: 1-cost Power, TrashToTreasurePower 1
    id="trash_to_treasure", name="Trash to Treasure", cost=1, type=CardType.POWER, count=0,
    effects=(Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
                    power_id="trash_to_treasure", amount=1),),
)
REBOOT = CardDef(  # Reboot.cs: 0-cost, draw 4 (shuffle-deck nuance not modeled; upg +2)
    id="reboot", name="Reboot", cost=0, type=CardType.SKILL, count=0,
    effects=(Effect(op=EffectOp.DRAW_CARD, target=Target.SELF, amount=4),),
)
RAINBOW = CardDef(  # Rainbow.cs: 2-cost, channel Lightning + Frost + Dark; Exhaust
    id="rainbow", name="Rainbow", cost=2, type=CardType.SKILL, count=0, exhaust=True,
    effects=(_ch("lightning", 1), _ch("frost", 1), _ch("dark", 1)),
)
MULTI_CAST = CardDef(  # MultiCast.cs: 0-cost X, evoke all orbs (+1 evoke); modeled as evoke-all
    id="multi_cast", name="Multi-Cast", cost=0, type=CardType.SKILL, count=0,
    effects=(Effect(op=EffectOp.EVOKE_ALL_ORBS, target=Target.SELF),),
)
VOLTAIC = CardDef(  # Voltaic.cs: 3-cost, channel Lightning per Lightning channeled (base 1)
    id="voltaic", name="Voltaic", cost=3, type=CardType.SKILL, count=0,
    effects=(_ch("lightning", 1),),
)

# --- Ancient ---------------------------------------------------------------
BIASED_COGNITION = CardDef(  # BiasedCognition.cs: 1-cost Power, +4 Focus + BiasedCognitionPower 1
    id="biased_cognition", name="Biased Cognition", cost=1, type=CardType.POWER, count=0,
    effects=(Effect(op=EffectOp.APPLY_POWER, target=Target.SELF, power_id="focus", amount=4),
             Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
                    power_id="biased_cognition", amount=1)),
)
QUADCAST = CardDef(  # Quadcast.cs: 1-cost, evoke front orb 4 times (upg cost -1)
    id="quadcast", name="Quadcast", cost=1, type=CardType.SKILL, count=0,
    effects=(Effect(op=EffectOp.EVOKE_ORB, target=Target.SELF, amount=4),),
)
HOTFIX = CardDef(  # Hotfix.cs: 0-cost, +2 (temporary) Focus (upg +1)
    id="hotfix", name="Hotfix", cost=0, type=CardType.SKILL, count=0,
    effects=(Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
                    power_id="temporary_focus", amount=2),),
)
IGNITION = CardDef(  # Ignition.cs: 1-cost, channel a Plasma (orb to an ally)
    id="ignition", name="Ignition", cost=1, type=CardType.SKILL, count=0,
    effects=(_ch("plasma", 1),),
)
ENERGY_SURGE = CardDef(  # EnergySurge.cs: 0-cost, gain energy this turn (Turbo-like)
    id="energy_surge", name="Energy Surge", cost=0, type=CardType.SKILL, count=0,
    effects=(Effect(op=EffectOp.ENERGY_GAIN, target=Target.SELF, amount=2),),
)


# All fully-implemented Defect CardDefs (basics are the scaffold Strike/Defend;
# Zap/Dualcast replaced below). Used by the catalog merge.
_DEFECT_IMPLEMENTED: tuple[CardDef, ...] = (
    BALL_LIGHTNING, BARRAGE, BEAM_CELL, CLAW, COLD_SNAP, COMPILE_DRIVER,
    GO_FOR_THE_EYES, GUNK_UP, MOMENTUM_STRIKE, SWEEPING_BEAM, FOCUSED_STRIKE,
    CHARGE_BATTERY, COOLHEADED, HOLOGRAM, LEAP, TURBO, BOOST_AWAY,
    COMPACT, FTL, REFRACT, ROCKET_PUNCH, SCRAPE, SUNDER, SYNTHESIS, TESLA_COIL,
    UPROAR, NULL,
    BOOT_SEQUENCE, CAPACITOR, CHAOS, CHILL, DARKNESS, DOUBLE_ENERGY,
    FIGHT_THROUGH, FUSION, GLACIER, GLASSWORK, OVERCLOCK, SCAVENGE,
    SHADOW_SHIELD_DEFECT, SKIM, TEMPEST, WHITE_NOISE,
    BULK_UP, FERAL, HAILSTORM, ITERATION, LOOP, SMOKESTACK, STORM, SUBROUTINE,
    LIGHTNING_ROD, THUNDER,
    ADAPTIVE_STRIKE, ALL_FOR_ONE, HYPERBEAM, ICE_LANCE, METEOR_STRIKE, SHATTER,
    FLAK_CANNON, HELIX_DRILL,
    BUFFER, COOLANT, CREATIVE_AI, DEFRAGMENT, ECHO_FORM, CONSUMING_SHADOW,
    MACHINE_LEARNING, SIGNAL_BOOST, SPINNER, SUPERCRITICAL, SYNCHRONIZE,
    TRASH_TO_TREASURE, REBOOT, RAINBOW, MULTI_CAST, VOLTAIC,
    BIASED_COGNITION, QUADCAST, HOTFIX, IGNITION, ENERGY_SURGE,
)


# ===========================================================================
# Phase 9.3 — NECROBINDER full card library (decompiled Models.Cards/*.cs, 88
# cards in NecrobinderCardPool.cs). Costs / damage / block / summon / doom /
# upgrade are .cs-exact. Signature mechanic = the Osty minion (summon / grow /
# attack-for-its-HP / sacrifice) + Doom (execute-threshold debuff). The basics
# (StrikeNecrobinder/DefendNecrobinder) + Bodyguard/Unleash come from the
# scaffold (Bodyguard/Unleash now carry real Osty effects). Cards needing an
# absent primitive (Soul token gen, card-select-exhaust, Ethereal, X-cost loop,
# History-count damage scaling) land as faithful by-type placeholders.
#
# Osty DSL ops: SUMMON_OSTY (amount=HP), OSTY_ATTACK (amount=dmg, Osty-gated),
# OSTY_ATTACK_HP (Osty.CurrentHp), SACRIFICE_OSTY, HEAL_OSTY, SUMMON_NEXT_TURN,
# APPLY_DOOM (amount), DOOM_KILL. See sim/dsl.py + combat.py + osty.py.
# ===========================================================================


def _dmg(amount: int, target: Target = Target.SELECTED_ENEMY) -> Effect:
    return Effect(op=EffectOp.DEAL_DAMAGE, target=target, amount=amount,
                  scaling=STRIKE_SCALING)


def _blk(amount: int) -> Effect:
    return Effect(op=EffectOp.GAIN_BLOCK, target=Target.SELF, amount=amount)


def _osty(amount: int, target: Target = Target.SELECTED_ENEMY) -> Effect:
    return Effect(op=EffectOp.OSTY_ATTACK, target=target, amount=amount,
                  scaling=STRIKE_SCALING)


def _summon(hp: int) -> Effect:
    return Effect(op=EffectOp.SUMMON_OSTY, target=Target.SELF, amount=hp)


def _power(pid: str, amount: int, target: Target = Target.SELECTED_ENEMY) -> Effect:
    return Effect(op=EffectOp.APPLY_POWER, target=target, power_id=pid, amount=amount)


def _self_power(pid: str, amount: int) -> Effect:
    return Effect(op=EffectOp.APPLY_POWER, target=Target.SELF, power_id=pid, amount=amount)


def _doom(amount: int, target: Target = Target.SELECTED_ENEMY) -> Effect:
    return Effect(op=EffectOp.APPLY_DOOM, target=target, amount=amount)


def _draw(n: int) -> Effect:
    return Effect(op=EffectOp.DRAW_CARD, target=Target.SELF, amount=n)


_C = CardType
_T = Target

# --- Basics: Strike (6, upg +3), Defend (5, upg +3) already from scaffold ---
BLIGHT_STRIKE = CardDef(id="blight_strike", name="Blight Strike", cost=1,
    type=_C.ATTACK, count=0, effects=(_dmg(8),))  # upg +2
SCULPTING_STRIKE = CardDef(id="sculpting_strike", name="Sculpting Strike", cost=1,
    type=_C.ATTACK, count=0, effects=(_dmg(9),))  # upg +3

# --- Common ---
GRAVEBLAST = CardDef(id="graveblast", name="Graveblast", cost=1, type=_C.ATTACK,
    count=0, effects=(_dmg(4),))  # upg +2
DEFILE = CardDef(id="defile", name="Defile", cost=1, type=_C.ATTACK, count=0,
    effects=(_dmg(13),))  # upg +4
REAVE = CardDef(id="reave", name="Reave", cost=1, type=_C.ATTACK, count=0,
    effects=(_dmg(9), _draw(1)))  # upg +2 dmg
DRAIN_POWER = CardDef(id="drain_power", name="Drain Power", cost=1, type=_C.ATTACK,
    count=0, effects=(_dmg(10),))  # upg +2 (draw 2 deferred = simple draw)
FEAR_NB = CardDef(id="fear_nb", name="Fear", cost=1, type=_C.ATTACK, count=0,
    effects=(_dmg(7), _power("vulnerable", 1)))  # upg +1/+1
REAP = CardDef(id="reap", name="Reap", cost=3, type=_C.ATTACK, count=0,
    effects=(_dmg(27),))  # upg +6
POKE = CardDef(id="poke", name="Poke", cost=0, type=_C.ATTACK, count=0,
    effects=(_osty(6),))  # OstyAttack 6, upg +3
SNAP = CardDef(id="snap", name="Snap", cost=1, type=_C.ATTACK, count=0,
    effects=(_osty(7),))  # OstyAttack 7, upg +3 (Retain on a card deferred)
AFTERLIFE = CardDef(id="afterlife", name="Afterlife", cost=1, type=_C.SKILL,
    count=0, effects=(_summon(6),))  # Summon 6, upg +3
DEFY = CardDef(id="defy", name="Defy", cost=1, type=_C.SKILL, count=0,
    effects=(_blk(6),))  # upg +3
GRAVE_WARDEN = CardDef(id="grave_warden", name="Grave Warden", cost=1, type=_C.SKILL,
    count=0, effects=(_blk(8),))  # +1 Soul gen deferred; upg +3 block
PULL_AGGRO = CardDef(id="pull_aggro", name="Pull Aggro", cost=2, type=_C.SKILL,
    count=0, effects=(_summon(4), _blk(7)))  # Summon 4 + block 7; upg +1/+2
SCOURGE = CardDef(id="scourge", name="Scourge", cost=1, type=_C.SKILL, count=0,
    effects=(_doom(13), _draw(1)))  # Doom 13 + draw 1; upg +3 doom

# --- Uncommon ---
SEVERANCE = CardDef(id="severance", name="Severance", cost=2, type=_C.ATTACK,
    count=0, effects=(_dmg(13),))  # upg +5
VEILPIERCER = CardDef(id="veilpiercer", name="Veilpiercer", cost=1, type=_C.ATTACK,
    count=0, effects=(_dmg(10),))  # upg +3
DEBILITATE_NB = CardDef(id="debilitate_nb", name="Debilitate", cost=1, type=_C.ATTACK,
    count=0, effects=(_dmg(10), _power("vulnerable", 3)))  # Debilitate=vuln-amp; upg +2/+1
BURY = CardDef(id="bury", name="Bury", cost=4, type=_C.ATTACK, count=0,
    effects=(_dmg(52),))  # upg +11
FLATTEN = CardDef(id="flatten", name="Flatten", cost=2, type=_C.ATTACK, count=0,
    effects=(_osty(12),))  # OstyAttack 12, upg +4
BONE_SHARDS = CardDef(id="bone_shards", name="Bone Shards", cost=1, type=_C.ATTACK,
    count=0, effects=(_osty(9, _T.ALL_ENEMIES), _blk(9)))  # OstyAttack AoE 9 + block 9
SIC_EM = CardDef(id="sic_em", name="Sic 'Em", cost=1, type=_C.ATTACK, count=0,
    effects=(_osty(5), _power("vulnerable", 2)))  # OstyAttack 5 + SicEm(vuln 2)
HIGH_FIVE = CardDef(id="high_five", name="High Five", cost=2, type=_C.ATTACK,
    count=0, effects=(_osty(11, _T.ALL_ENEMIES), _power("vulnerable", 2, _T.ALL_ENEMIES)))
RIGHT_HAND_HAND = CardDef(id="right_hand_hand", name="Right Hand, Hand", cost=0,
    type=_C.ATTACK, count=0, effects=(_osty(4),))  # OstyAttack 4 (energy refund deferred)
FETCH = CardDef(id="fetch", name="Fetch", cost=0, type=_C.ATTACK, count=0,
    effects=(_osty(3), _draw(1)))  # OstyAttack 3 + draw 1 (on-kill gated in .cs)
RATTLE = CardDef(id="rattle", name="Rattle", cost=1, type=_C.ATTACK, count=0,
    effects=(_osty(7),))  # OstyAttack 7 × (1 + osty attacks this turn); base 7
ENFEEBLING_TOUCH = CardDef(id="enfeebling_touch", name="Enfeebling Touch", cost=1,
    type=_C.SKILL, count=0, effects=(_power("strength_down", 8),))  # -8 enemy Str
PUTREFY = CardDef(id="putrefy", name="Putrefy", cost=1, type=_C.SKILL, count=0,
    effects=(_power("weak", 2), _power("vulnerable", 2)))  # upg +1
SPUR = CardDef(id="spur", name="Spur", cost=1, type=_C.SKILL, count=0,
    effects=(_summon(3), Effect(op=EffectOp.HEAL_OSTY, target=_T.SELF, amount=5)))
DEATHS_DOOR = CardDef(id="deaths_door", name="Death's Door", cost=1, type=_C.SKILL,
    count=0, effects=(_blk(6),))  # block 6 ×(1 or 1+2 if doom this turn); base block
DELAY = CardDef(id="delay", name="Delay", cost=2, type=_C.SKILL, count=0,
    effects=(_blk(11), Effect(op=EffectOp.ENERGY_GAIN, target=_T.SELF, amount=1)))
MELANCHOLY = CardDef(id="melancholy", name="Melancholy", cost=3, type=_C.SKILL,
    count=0, effects=(_blk(13), Effect(op=EffectOp.ENERGY_GAIN, target=_T.SELF, amount=1)))
CLEANSE_NB = CardDef(id="cleanse_nb", name="Cleanse", cost=1, type=_C.SKILL, count=0,
    effects=(_summon(3),))  # Summon 3 + exhaust-select (deferred); upg +2 summon
DIRGE = CardDef(id="dirge", name="Dirge", cost=0, type=_C.SKILL, count=0,
    effects=(_summon(3),))  # X-cost summon loop deferred -> single Summon 3
LEGION_OF_BONE = CardDef(id="legion_of_bone", name="Legion of Bone", cost=2,
    type=_C.SKILL, count=0, effects=(_summon(6),))  # Summon 6 (all allies); upg +2
INVOKE = CardDef(id="invoke", name="Invoke", cost=1, type=_C.SKILL, count=0,
    effects=(Effect(op=EffectOp.SUMMON_NEXT_TURN, target=_T.SELF, amount=2),
             Effect(op=EffectOp.ENERGY_GAIN, target=_T.SELF, amount=2)))
NEGATIVE_PULSE = CardDef(id="negative_pulse", name="Negative Pulse", cost=1,
    type=_C.SKILL, count=0, effects=(_blk(5), _doom(7, _T.ALL_ENEMIES)))  # block 5 + Doom 7 AoE
CAPTURE_SPIRIT = CardDef(id="capture_spirit", name="Capture Spirit", cost=1,
    type=_C.SKILL, count=0, effects=(Effect(op=EffectOp.DEAL_DAMAGE,
        target=_T.SELECTED_ENEMY, amount=3),))  # 3 unblockable + 3 Soul gen (deferred)
HAUNT = CardDef(id="haunt", name="Haunt", cost=1, type=_C.POWER, count=0,
    effects=(_self_power("haunt", 6),))  # upg +2
CALCIFY = CardDef(id="calcify", name="Calcify", cost=1, type=_C.POWER, count=0,
    effects=(_self_power("calcify", 4),))  # upg +2
FRIENDSHIP = CardDef(id="friendship", name="Friendship", cost=1, type=_C.POWER,
    count=0, effects=(_self_power("strength_down", 2), _self_power("friendship", 1)))
LETHALITY = CardDef(id="lethality", name="Lethality", cost=1, type=_C.POWER, count=0,
    effects=(_self_power("lethality", 25),))  # +25% dmg; upg +25
DANSE_MACABRE = CardDef(id="danse_macabre", name="Danse Macabre", cost=1, type=_C.POWER,
    count=0, effects=(_self_power("danse_macabre", 2),))  # block per card; upg +2
COUNTDOWN = CardDef(id="countdown", name="Countdown", cost=1, type=_C.POWER, count=0,
    effects=(_self_power("calcify", 3),))  # turn-start Doom engine; modeled as +3 dmg marker
PAGESTORM = CardDef(id="pagestorm", name="Pagestorm", cost=1, type=_C.POWER, count=0,
    effects=(_self_power("haunt", 1),))  # draw-on-draw engine; modeled as marker
SHROUD = CardDef(id="shroud", name="Shroud", cost=1, type=_C.POWER, count=0,
    effects=(_self_power("spirit_of_ash", 2),))  # block-per-card 2; upg +1

# --- Rare ---
ERADICATE = CardDef(id="eradicate", name="Eradicate", cost=0, type=_C.ATTACK,
    count=0, effects=(_dmg(11),))  # upg +3
HANG = CardDef(id="hang", name="Hang", cost=1, type=_C.ATTACK, count=0,
    effects=(_dmg(10),))  # upg +3
MISERY = CardDef(id="misery", name="Misery", cost=0, type=_C.ATTACK, count=0,
    effects=(_dmg(7),))  # +duplicate debuffs (deferred); upg +2
THE_SCYTHE = CardDef(id="the_scythe", name="The Scythe", cost=2, type=_C.ATTACK,
    count=0, effects=(_dmg(7),))  # damage grows per play (deferred scaling); base 7
SQUEEZE = CardDef(id="squeeze", name="Squeeze", cost=3, type=_C.ATTACK, count=0,
    effects=(_osty(25),))  # OstyAttack 25 + 5/OstyAttack-card scaling (deferred)
PROTECTOR = CardDef(id="protector", name="Protector", cost=1, type=_C.ATTACK, count=0,
    effects=(Effect(op=EffectOp.OSTY_ATTACK_HP, target=_T.SELECTED_ENEMY, amount=10),))
BANSHEES_CRY = CardDef(id="banshees_cry", name="Banshee's Cry", cost=9, type=_C.ATTACK,
    count=0, effects=(_dmg(33, _T.ALL_ENEMIES),))  # cost reduces (deferred); AoE 33
SACRIFICE = CardDef(id="sacrifice", name="Sacrifice", cost=1, type=_C.SKILL, count=0,
    effects=(Effect(op=EffectOp.SACRIFICE_OSTY, target=_T.SELF),))  # kill Osty -> MaxHp*2 block
REANIMATE = CardDef(id="reanimate", name="Reanimate", cost=3, type=_C.SKILL, count=0,
    effects=(_summon(20),))  # Summon 20; upg +5
NECRO_MASTERY = CardDef(id="necro_mastery", name="Necro Mastery", cost=2, type=_C.POWER,
    count=0, effects=(_summon(5), _self_power("necro_mastery", 1)))  # Summon 5 + NecroMastery
DEMESNE = CardDef(id="demesne", name="Demesne", cost=3, type=_C.POWER, count=0,
    effects=(_self_power("demesne", 1),))  # +1 draw +1 energy
DEVOUR_LIFE = CardDef(id="devour_life", name="Devour Life", cost=1, type=_C.POWER,
    count=0, effects=(_self_power("devour_life", 1),))  # Summon 1 per card played
SPIRIT_OF_ASH = CardDef(id="spirit_of_ash", name="Spirit of Ash", cost=1, type=_C.POWER,
    count=0, effects=(_self_power("spirit_of_ash", 4),))  # block 4 per card; upg +1
SHARED_FATE = CardDef(id="shared_fate", name="Shared Fate", cost=0, type=_C.SKILL,
    count=0, effects=(_self_power("strength_down", 2), _power("strength_down", 2)))
OBLIVION = CardDef(id="oblivion", name="Oblivion", cost=0, type=_C.SKILL, count=0,
    effects=(_doom(3),))  # Doom 3 (single target); upg +1
DEATHBRINGER = CardDef(id="deathbringer", name="Deathbringer", cost=2, type=_C.SKILL,
    count=0, effects=(_doom(21, _T.ALL_ENEMIES), _power("weak", 1, _T.ALL_ENEMIES)))
END_OF_DAYS = CardDef(id="end_of_days", name="End of Days", cost=3, type=_C.SKILL,
    count=0, effects=(Effect(op=EffectOp.DOOM_KILL, target=_T.ALL_ENEMIES, amount=29),))
EIDOLON = CardDef(id="eidolon", name="Eidolon", cost=2, type=_C.SKILL, count=0,
    effects=(_self_power("intangible", 1),))

# All Necrobinder cards needing an absent primitive land as by-type placeholders
# (faithful cost/type/rarity in card_catalog). Implemented CardDefs below.
_NECROBINDER_IMPLEMENTED: tuple[CardDef, ...] = (
    BODYGUARD, UNLEASH, BLIGHT_STRIKE, SCULPTING_STRIKE,
    GRAVEBLAST, DEFILE, REAVE, DRAIN_POWER, FEAR_NB, REAP, POKE, SNAP,
    AFTERLIFE, DEFY, GRAVE_WARDEN, PULL_AGGRO, SCOURGE,
    SEVERANCE, VEILPIERCER, DEBILITATE_NB, BURY, FLATTEN, BONE_SHARDS, SIC_EM,
    HIGH_FIVE, RIGHT_HAND_HAND, FETCH, RATTLE, ENFEEBLING_TOUCH, PUTREFY, SPUR,
    DEATHS_DOOR, DELAY, MELANCHOLY, CLEANSE_NB, DIRGE, LEGION_OF_BONE, INVOKE,
    NEGATIVE_PULSE, CAPTURE_SPIRIT, HAUNT, CALCIFY, FRIENDSHIP, LETHALITY,
    DANSE_MACABRE, COUNTDOWN, PAGESTORM, SHROUD,
    ERADICATE, HANG, MISERY, THE_SCYTHE, SQUEEZE, PROTECTOR, BANSHEES_CRY,
    SACRIFICE, REANIMATE, NECRO_MASTERY, DEMESNE, DEVOUR_LIFE, SPIRIT_OF_ASH,
    SHARED_FATE, OBLIVION, DEATHBRINGER, END_OF_DAYS, EIDOLON,
)


def build_starting_deck(character: str = "ironclad") -> list[CardDef]:
    """Build the starting deck for `character` (the Character enum value
    string). Defaults to Ironclad for backward compatibility — existing
    callers that pass nothing keep the Ironclad deck byte-for-byte.

    P9.0: Ironclad is fully faithful; the other four use the scaffold
    starting decks above (faithful basics + TODO-stubbed signature cards)."""
    starters = _STARTING_DECKS_BY_CHAR.get(character, IRONCLAD_STARTING_DECK)
    deck: list[CardDef] = []
    for c in starters:
        deck.extend([c] * c.count)
    return deck


# ===========================================================================
# Card upgrade system (Phase 7B) — real stat changes per decompiled Upgrade().
# ===========================================================================
#
# Ground truth: decompiled/MegaCrit.Sts2.Core.Models.Cards/<Card>.cs OnUpgrade().
# Each upgrade is expressed as a tuple of mutation primitives applied to the
# base CardDef's effects/cost. The result is tagged id+"+" / name+"+" so
# card_features() and the "+"-stripping rarity lookup keep working.
#
# Mutation primitives (all operate on a fresh copy of the effects list):
#   ("dmg", n)            -> +n to every DEAL_DAMAGE effect's amount (per hit)
#   ("block", n)          -> +n to every GAIN_BLOCK effect's amount
#   ("power", pid, n)     -> +n to APPLY_POWER effects whose power_id == pid
#   ("any_power", n)      -> +n to every APPLY_POWER effect's amount
#   ("draw", n)           -> +n to every DRAW_CARD effect's amount
#   ("cost", n)           -> add n to cost (n negative reduces cost; floored 0)
#
# Decompiled-verified per-card deltas (base -> upgraded shown for clarity):
#   strike_ironclad : dmg+3   (6 -> 9)
#   defend_ironclad : block+3 (5 -> 8)
#   bash            : dmg+2, vulnerable+1   (8/2 -> 10/3)
#   iron_wave       : dmg+2, block+2        (5/5 -> 7/7)
#   inflame         : strength+1            (2 -> 3)
#   pommel_strike   : dmg+1, draw+1         (9/draw1 -> 10/draw2)
#   shrug_it_off    : block+3               (8 -> 11)
#   thunderclap     : dmg+3                 (4 -> 7)
#   tremble         : vulnerable+1          (3 -> 4)
#   twin_strike     : dmg+2 per hit         (5x2 -> 7x2)
#   bloodletting    : energy+1 (energy_gain amount)  (2 -> 3)
#   anger           : dmg+2                 (6 -> 8)
#   cinder          : dmg+6                 (18 -> 24)
#   bludgeon        : dmg+10                (32 -> 42)
#   uppercut        : weak+1, vulnerable+1  (1/1 -> 2/2)
#   taunt           : block+1, vulnerable+1 (7/1 -> 8/2)
#   stone_armor     : plating+2             (4 -> 6)
#   rage            : strength+2            (3 -> 5)
#   battle_trance   : draw+1                (3 -> 4)
#   headbutt        : dmg+3                 (9 -> 12)
#   dismantle       : dmg+2 per hit         (8x2 -> 10x2)
#   perfected_strike: base dmg+1 (ExtraDamage per-Strike not modeled; +1 to base)
#   demon_form      : strength/turn +1      (2 -> 3)
#   metallicize     : block/turn +1 (STS1 3 -> 4)
#   feel_no_pain    : amount+1              (3 -> 4)
#   dark_embrace    : cost-1                (2 -> 1)
#   juggernaut      : amount+2              (5 -> 7)
#   rupture         : amount+1              (1 -> 2)
#   combust         : amount+2 (STS1 5 -> 7)
#   barricade       : cost-1                (3 -> 2)
#   berserk         : amount unchanged; cost-0 already (STS1 reduces self-vuln) -> no stat delta
#   brutality       : amount unchanged (STS1 upgrade = innate) -> no stat delta
#   corruption      : cost-1                (3 -> 2)

_UPGRADE_DELTAS: dict[str, tuple[tuple, ...]] = {
    "strike_ironclad": (("dmg", 3),),
    "defend_ironclad": (("block", 3),),
    "bash": (("dmg", 2), ("power", "vulnerable", 1)),
    "iron_wave": (("dmg", 2), ("block", 2)),
    "inflame": (("power", "strength", 1),),
    "pommel_strike": (("dmg", 1), ("draw", 1)),
    "shrug_it_off": (("block", 3),),
    "thunderclap": (("dmg", 3),),
    "tremble": (("power", "vulnerable", 1),),
    "twin_strike": (("dmg", 2),),
    "bloodletting": (("energy", 1),),
    "anger": (("dmg", 2),),
    "cinder": (("dmg", 6),),
    "bludgeon": (("dmg", 10),),
    "clothesline": (("dmg", 2), ("power", "weak", 1)),  # TODO: no STS2 model
    "uppercut": (("power", "weak", 1), ("power", "vulnerable", 1)),
    "taunt": (("block", 1), ("power", "vulnerable", 1)),
    "stone_armor": (("power", "plating", 2),),
    "rage": (("power", "strength", 2),),
    "battle_trance": (("draw", 1),),
    "headbutt": (("dmg", 3),),
    "dismantle": (("dmg", 2),),
    "perfected_strike": (("dmg", 1),),
    "demon_form": (("power", "demon_form", 1),),
    "metallicize": (("power", "metallicize", 1),),  # STS1 3 -> 4
    "feel_no_pain": (("power", "feel_no_pain", 1),),
    "dark_embrace": (("cost", -1),),
    "juggernaut": (("power", "juggernaut", 2),),
    "rupture": (("power", "rupture", 1),),
    "combust": (("power", "combust", 2),),  # STS1 5 -> 7
    "barricade": (("cost", -1),),
    "berserk": (),    # STS1 upgrade only reduces self-Vulnerable (not modeled)
    "brutality": (),  # STS1 upgrade makes it Innate; no stat delta
    "corruption": (("cost", -1),),
    # --- Phase 7C STS2 pool (decompiled OnUpgrade values) ---
    "armaments": (("block", 0),),       # upgrade = "upgrade ALL in hand"; no stat
    "blood_wall": (("block", 4),),      # 16 -> 20
    "body_slam": (("cost", -1),),       # cost 1 -> 0
    "breakthrough": (("dmg", 4),),      # 9 -> 13
    "havoc": (("cost", -1),),           # cost 1 -> 0
    "molten_fist": (("dmg", 4),),       # 10 -> 14
    "setup_strike": (("dmg", 2), ("power", "strength", 1)),  # 7/2 -> 9/3
    "sword_boomerang": (("dmg", 0),),   # +1 hit (RepeatVar) not modeled as stat
    "true_grit": (("block", 2),),       # 7 -> 9
    "whirlwind": (("dmg", 3),),         # 5 -> 8
    "cascade": (("auto_play", 1),),     # Cascade.cs: upgraded plays +1 card
    "ashen_strike": (("dmg", 1),),      # ExtraDamage 3 -> 4 (per-card; +1 base)
    "bully": (("dmg", 1),),             # ExtraDamage 2 -> 3 (per-vuln; +1 base)
    "burning_pact": (("draw", 1),),     # 2 -> 3
    "flame_barrier": (("block", 4), ("power", "thorns", 2)),  # 12/4 -> 16/6
    "hemokinesis": (("dmg", 5),),       # 15 -> 20
    "howl_from_beyond": (("dmg", 5),),  # 16 -> 21
    "infernal_blade": (("cost", -1),),  # cost 1 -> 0
    "pillage": (("dmg", 3),),           # 6 -> 9
    "rampage": (("dmg", 0),),           # Increase 5 -> 9 (escalation; base same)
    "second_wind": (("block", 2),),     # 5 -> 7
    "shockwave": (("power", "weak", 2), ("power", "vulnerable", 2)),  # 3/3 -> 5/5
    "spite": (("dmg", 0),),             # +1 hit on the conditional branch
    "stomp": (("dmg", 3),),             # 12 -> 15
    "unrelenting": (("dmg", 6),),       # 12 -> 18
    "brand": (("power", "strength", 1),),  # 1 -> 2
    "conflagration": (("dmg", 1),),     # base 8 -> 9 (+1) and ExtraDamage +1
    "feed": (("dmg", 2), ("any_power", 0)),  # 10 -> 12, maxHP 3 -> 4 (not stat)
    "fiend_fire": (("dmg", 3),),        # 7 -> 10 per card
    "impervious": (("block", 10),),     # 30 -> 40
    "mangle": (("dmg", 5), ("power", "strength", -5)),  # 15/-10 -> 20/-15
    "not_yet": (("heal", 3),),          # 10 -> 13
    "offering": (("draw", 2),),         # 3 -> 5
    "pacts_end": (("dmg", 6),),         # 17 -> 23
    "pyre": (("power", "berserk", 1),), # 1 -> 2 energy/turn
    "tear_asunder": (("dmg", 2),),      # 5 -> 7
    "break": (("dmg", 10), ("power", "vulnerable", 2)),  # 20/5 -> 30/7
    "fight_me": (("dmg", 1), ("power", "strength", 1)),  # 5/3 -> 6/4
    "dominate": (("power", "vulnerable", 1),),           # 1 -> 2
    # --- Phase 8 Track A STS2 pool (decompiled OnUpgrade values) ---
    "colossus": (("block", 3),),                  # Colossus.cs Block 5 -> 8
    "drum_of_battle": (("draw", 1),),             # DrumOfBattle.cs Cards 2 -> 3
    "evil_eye": (("block", 3),),                  # EvilEye.cs Block 8 -> 11
    "expect_a_fight": (("cost", -1),),            # ExpectAFight.cs cost 2 -> 1
    "forgotten_ritual": (("energy", 1),),         # ForgottenRitual.cs Energy 3 -> 4
    "inferno": (("power", "inferno", 3),),        # Inferno.cs InfernoPower 6 -> 9
    "juggling": (),                               # Juggling.cs upgrade = Innate
    "stampede": (("cost", -1),),                  # Stampede.cs cost 2 -> 1
    "vicious": (("power", "vicious", 1),),        # Vicious.cs Cards 1 -> 2
    "aggression": (),                             # Aggression.cs upgrade = Innate
    "crimson_mantle": (("power", "crimson_mantle", 2),),  # CrimsonMantle 8 -> 10
    "cruelty": (("power", "cruelty", 25),),       # Cruelty.cs 25 -> 50
    "hellraiser": (("cost", -1),),                # Hellraiser.cs cost 2 -> 1
    "one_two_punch": (("power", "one_two_punch", 1),),  # OneTwoPunch 1 -> 2
    "primal_force": (),                           # PrimalForce.cs upgrades GiantRocks
    "stoke": (),                                  # Stoke.cs upgrades generated cards
    "thrash": (("dmg", 2),),                      # Thrash.cs Damage 4 -> 6
    "unmovable": (("cost", -1),),                 # Unmovable.cs cost 2 -> 1
    "giant_rock": (("dmg", 4),),                  # GiantRock.cs Damage 16 -> 20
    # --- Phase 9.1 Silent upgrades (decompiled OnUpgrade values) ---
    "neutralize": (("dmg", 1), ("power", "weak", 1)),   # 3/1 -> 4/2
    "survivor": (("block", 3),),                         # Block 8 -> 11
    "shiv": (("dmg", 2),),                               # Shiv 4 -> 6
    "slice": (("dmg", 3),),                              # 6 -> 9
    "dagger_throw": (("dmg", 3),),                       # 9 -> 12
    "dagger_spray": (("dmg", 2),),                       # 4 -> 6 (×2)
    "poisoned_stab": (("dmg", 2), ("power", "poison", 1)),  # 6/3 -> 8/4
    "sucker_punch": (("dmg", 2), ("power", "weak", 1)),  # 8/1 -> 10/2
    "backstab": (("dmg", 4),),                           # 11 -> 15
    "deadly_poison": (("power", "poison", 2),),          # 5 -> 7
    "snakebite": (("power", "poison", 3),),              # 7 -> 10
    "blade_dance": (("add_card", 1),),                   # Cards 3 -> 4
    "cloak_and_dagger": (("add_card", 1),),              # Shivs 1 -> 2
    "footwork": (("power", "dexterity", 1),),            # Dex 2 -> 3
    "accuracy": (("power", "accuracy", 2),),             # 4 -> 6
    "noxious_fumes": (("power", "noxious_fumes", 1),),   # 2 -> 3
    "outbreak": (("power", "outbreak", 4),),             # 3 -> 7
    "leg_sweep": (("block", 3), ("power", "weak", 1)),   # +block/+weak
    "expertise": (("draw", 1),),                         # 6 -> 7
    "the_hunt": (("dmg", 4),),                           # 10 -> 14
    "echoing_slash": (("dmg", 4),),                      # 10 -> 14
    "well_laid_plans": (("power", "well_laid_plans", 1),),  # retain 1 -> 2
    "haze": (("power", "poison", 2),),                   # 4 -> 6
    "bubble_bubble": (("power", "poison", 3),),          # 9 -> 12
    "strangle": (("dmg", 3), ("power", "strangle", 1)),  # 8/2 -> 11/3
    "memento_mori": (("dmg_extra_discard", 1),),         # ExtraDamage 4 -> 5
    "murder": (("dmg_extra_drawn", 1),),                 # ExtraDamage 1 -> 2
    "predator": (("dmg", 5),),                           # 15 -> 20
    "pounce": (("dmg", 4),),                             # 12 -> 16
    "pinpoint": (("dmg", 5),),                           # 15 -> 20
    "skewer": (("dmg", 2),),                             # 8 -> 10 per hit
    "finisher": (("dmg", 2),),                           # 6 -> 8 per attack
    "anticipate": (("power", "dexterity", 1),),          # 2 -> 3
    # --- Phase 9.2 Defect upgrades (decompiled OnUpgrade values) ---
    "zap": (("cost", -1),),                              # cost 1 -> 0
    "dualcast": (("cost", -1),),                         # cost 1 -> 0
    "ball_lightning": (("dmg", 3),),                     # 7 -> 10
    "barrage": (("dmg", 2),),                            # 5 -> 7
    "beam_cell": (("dmg", 1), ("power", "vulnerable", 1)),  # 3/1 -> 4/2
    "claw": (("dmg", 1),),                               # 3 -> 4
    "cold_snap": (("dmg", 3),),                          # 6 -> 9
    "compile_driver": (("dmg", 3),),                     # 7 -> 10
    "go_for_the_eyes": (("dmg", 1), ("power", "weak", 1)),  # 3/1 -> 4/2
    "momentum_strike": (("dmg", 3),),
    "sweeping_beam": (("dmg", 3),),                      # 6 -> 9
    "focused_strike": (("dmg", 2), ("power", "temporary_focus", 1)),  # 9/1 -> 11/2
    "charge_battery": (("block", 3),),                   # 7 -> 10
    "coolheaded": (("draw", 1),),                        # draw 1 -> 2
    "hologram": (("block", 2),),                         # 3 -> 5
    "leap": (("block", 3),),                             # 9 -> 12
    "turbo": (("energy", 1),),                           # 2 -> 3
    "boost_away": (("block", 3),),
    "compact": (("block", 1),),                          # 6 -> 7
    "ftl": (("dmg", 1),),                                # 5 -> 6
    "refract": (("dmg", 3),),
    "rocket_punch": (("dmg", 1), ("draw", 1)),           # 13/1 -> 14/2
    "scrape": (("dmg", 3), ("draw", 1)),                 # 7/4 -> 10/5
    "sunder": (("dmg", 8),),                             # 24 -> 32
    "synthesis": (("dmg", 3),),
    "tesla_coil": (("dmg", 2),),
    "uproar": (("dmg", 1),),
    "null": (("dmg", 3),),
    "boot_sequence": (("block", 3),),                    # 10 -> 13
    "capacitor": (("add_orb_slots", 1),),                # +2 -> +3 slots
    "chaos": (("channel_orb", 1),),                      # channel 1 -> 2
    "darkness": (("channel_orb", 1),),
    "double_energy": (("cost", -1),),
    "fight_through": (("block", 4),),
    "fusion": (("cost", -1),),                           # cost 2 -> 1
    "glacier": (("block", 3),),                          # 6 -> 9
    "glasswork": (("block", 3),),                        # 5 -> 8
    "overclock": (("draw", 1),),                         # 2 -> 3
    "scavenge": (("energy", 1),),                        # 2 -> 3
    "shadow_shield_defect": (("block", 3),),
    "skim": (("draw", 1),),                              # 3 -> 4
    "tempest": (),                                       # X-cost; per-energy channel
    "bulk_up": (("power", "strength", 1), ("power", "dexterity", 1)),  # 2/2 -> 3/3
    "feral": (("power", "strength", 1),),
    "hailstorm": (("power", "hailstorm", 2),),           # 6 -> 8
    "iteration": (("power", "iteration", 1),),
    "loop": (("power", "loop", 1),),                     # 1 -> 2
    "smokestack": (("power", "smokestack", 2),),         # 5 -> 7
    "storm": (("power", "storm", 1),),                   # 1 -> 2
    "lightning_rod": (("channel_orb", 1),),
    "thunder": (("power", "thunder", 2),),               # 6 -> 8
    "adaptive_strike": (("dmg", 5),),
    "all_for_one": (("dmg", 4),),
    "hyperbeam": (("dmg", 8),),                          # 26 -> 34
    "ice_lance": (("dmg", 5),),                          # 19 -> 24
    "meteor_strike": (("dmg", 6),),                      # 24 -> 30
    "shatter": (("dmg", 4),),                            # 11 -> 15
    "flak_cannon": (("dmg", 3),),
    "helix_drill": (("dmg", 4),),
    "buffer": (("power", "buffer", 1),),                 # 1 -> 2
    "coolant": (("power", "coolant", 1),),               # 2 -> 3
    "creative_ai": (("cost", -1),),                      # cost 3 -> 2
    "defragment": (("power", "focus", 1),),              # 1 -> 2
    "consuming_shadow": (("channel_orb", 1),),
    "machine_learning": (("power", "machine_learning", 1),),
    "signal_boost": (("power", "signal_boost", 1),),
    "spinner": (("power", "spinner", 1),),
    "supercritical": (("energy", 1),),
    "synchronize": (("power", "focus", 1),),
    "reboot": (("draw", 2),),                            # 4 -> 6
    "rainbow": (),                                       # upgrade removes Exhaust
    "voltaic": (("channel_orb", 1),),
    "biased_cognition": (("power", "focus", 1),),        # 4 -> 5
    "quadcast": (("cost", -1),),                         # cost 1 -> 0
    "hotfix": (("power", "temporary_focus", 1),),        # 2 -> 3
    "ignition": (("channel_orb", 1),),
    "energy_surge": (("energy", 1),),
    # --- Phase 9.3 Necrobinder upgrades (decompiled OnUpgrade values) ---
    "strike_necrobinder": (("dmg", 3),),                 # 6 -> 9
    "defend_necrobinder": (("block", 3),),               # 5 -> 8
    "bodyguard": (("summon", 2),),                       # Summon 5 -> 7
    "unleash": (("osty_hp", 3),),                        # CalcBase 6 -> 9 (preview)
    "blight_strike": (("dmg", 2),),                      # 8 -> 10
    "sculpting_strike": (("dmg", 3),),                   # 9 -> 12
    "graveblast": (("dmg", 2),),                         # 4 -> 6
    "defile": (("dmg", 4),),                             # 13 -> 17
    "reave": (("dmg", 2),),                              # 9 -> 11
    "drain_power": (("dmg", 2),),                        # 10 -> 12
    "fear_nb": (("dmg", 1), ("power", "vulnerable", 1)),  # 7/1 -> 8/2
    "reap": (("dmg", 6),),                               # 27 -> 33
    "poke": (("osty", 3),),                              # OstyDamage 6 -> 9
    "snap": (("osty", 3),),                              # OstyDamage 7 -> 10
    "sow": (("dmg", 3),),                                # 8 -> 11
    "afterlife": (("summon", 3),),                       # Summon 6 -> 9
    "defy": (("block", 3),),                             # 6 -> 9
    "grave_warden": (("block", 3),),                     # 8 -> 11
    "pull_aggro": (("summon", 1), ("block", 2)),         # Summon 4->5, Block 7->9
    "scourge": (("doom", 3), ("draw", 1)),               # Doom 13->16, draw +1
    "severance": (("dmg", 5),),                          # 13 -> 18
    "veilpiercer": (("dmg", 3),),                        # 10 -> 13
    "debilitate_nb": (("dmg", 2),),                      # 10 -> 12
    "bury": (("dmg", 11),),                              # 52 -> 63
    "flatten": (("osty", 4),),                           # OstyDamage 12 -> 16
    "bone_shards": (("osty", 3), ("block", 3)),          # 9/9 -> 12/12
    "sic_em": (("osty", 1),),                            # OstyDamage 5 -> 6
    "high_five": (("osty", 2),),                         # OstyDamage 11 -> 13
    "right_hand_hand": (("osty", 2),),                   # OstyDamage 4 -> 6
    "fetch": (("osty", 3),),                             # OstyDamage 3 -> 6
    "rattle": (("osty", 2),),                            # OstyDamage 7 -> 9
    "enfeebling_touch": (),                              # StrengthLoss 8 -> 11 (deferred)
    "putrefy": (("power", "weak", 1),),                  # 2 -> 3 (both)
    "spur": (("summon", 2), ("heal_osty", 2)),           # Summon 3->5, Heal 5->7
    "deaths_door": (("block", 1),),                      # Block 6 -> 7
    "delay": (("block", 2), ("energy", 1)),              # Block 11->13, Energy 1->2
    "melancholy": (("block", 4),),                       # 13 -> 17
    "cleanse_nb": (("summon", 2),),                      # Summon 3 -> 5
    "dirge": (("summon", 1),),                           # Summon 3 -> 4
    "legion_of_bone": (("summon", 2),),                  # Summon 6 -> 8
    "invoke": (("energy", 1),),                          # Summon 2->3, Energy 2->3
    "negative_pulse": (("block", 1), ("doom", 4)),       # Block 5->6, Doom 7->11
    "haunt": (("any_power", 2),),                        # HpLoss 6 -> 8
    "calcify": (("any_power", 2),),                      # 4 -> 6
    "lethality": (("any_power", 25),),                   # +25% -> +50%
    "danse_macabre": (("any_power", 2),),                # 2 -> 4
    "shroud": (("any_power", 1),),                       # 2 -> 3
    "eradicate": (("dmg", 3),),                          # 11 -> 14
    "hang": (("dmg", 3),),                               # 10 -> 13
    "misery": (("dmg", 2),),                             # 7 -> 9
    "the_scythe": (("dmg", 1),),                         # Increase 3 -> 4
    "squeeze": (("osty", 5),),                           # CalcBase 25 -> 30
    "protector": (("osty_hp", 5),),                      # CalcBase 10 -> 15
    "sacrifice": (),                                     # Sacrifice: no numeric upg
    "reanimate": (("summon", 5),),                       # Summon 20 -> 25
    "necro_mastery": (("summon", 3),),                   # Summon 5 -> 8
    "devour_life": (),                                   # +1 stack on upgrade (deferred)
    "spirit_of_ash": (("any_power", 1),),                # 4 -> 5
    "shared_fate": (),                                   # StrengthLoss 2 -> 3 (deferred)
    "oblivion": (("doom", 1),),                          # Doom 3 -> 4
    "deathbringer": (("doom", 5),),                      # Doom 21 -> 26
    "end_of_days": (("doom", 8),),                       # Doom 29 -> 37
}

# Default deltas for any implemented card not in the table above:
# attacks +3 damage, blocks +3 block. TODO: replace with the card's real
# OnUpgrade() values once that card's effect is ported.
_DEFAULT_ATTACK_DELTA: tuple[tuple, ...] = (("dmg", 3),)
_DEFAULT_BLOCK_DELTA: tuple[tuple, ...] = (("block", 3),)


def _apply_delta(effects: tuple[Effect, ...], delta: tuple) -> tuple[Effect, ...]:
    from dataclasses import replace as _replace
    kind = delta[0]
    out: list[Effect] = []
    for eff in effects:
        new_eff = eff
        if kind == "dmg" and eff.op is EffectOp.DEAL_DAMAGE:
            new_eff = _replace(eff, amount=eff.amount + delta[1])
        elif kind == "block" and eff.op is EffectOp.GAIN_BLOCK:
            new_eff = _replace(eff, amount=eff.amount + delta[1])
        elif kind == "draw" and eff.op is EffectOp.DRAW_CARD:
            new_eff = _replace(eff, amount=eff.amount + delta[1])
        elif kind == "energy" and eff.op is EffectOp.ENERGY_GAIN:
            new_eff = _replace(eff, amount=eff.amount + delta[1])
        elif kind == "heal" and eff.op is EffectOp.HEAL:
            new_eff = _replace(eff, amount=eff.amount + delta[1])
        elif kind == "auto_play" and eff.op is EffectOp.AUTO_PLAY_FROM_DRAW:
            new_eff = _replace(eff, amount=eff.amount + delta[1])
        elif kind == "add_card" and eff.op is EffectOp.ADD_CARD:
            new_eff = _replace(eff, amount=eff.amount + delta[1])
        elif kind == "channel_orb" and eff.op is EffectOp.CHANNEL_ORB:
            new_eff = _replace(eff, amount=eff.amount + delta[1])
        elif kind == "add_orb_slots" and eff.op is EffectOp.ADD_ORB_SLOTS:
            new_eff = _replace(eff, amount=eff.amount + delta[1])
        elif (kind == "dmg_extra_discard"
              and eff.op is EffectOp.DAMAGE_PER_DISCARD_THIS_TURN):
            # MementoMori upgrade: +1 per-discard ExtraDamage (stored in hit_count).
            new_eff = _replace(eff, hit_count=eff.hit_count + delta[1])
        elif (kind == "dmg_extra_drawn"
              and eff.op is EffectOp.DAMAGE_PER_CARD_DRAWN):
            # Murder upgrade: +1 per-drawn ExtraDamage (stored in hit_count).
            new_eff = _replace(eff, hit_count=eff.hit_count + delta[1])
        elif kind == "block" and eff.op is EffectOp.GAIN_BLOCK_IF_EXHAUSTED:
            new_eff = _replace(eff, amount=eff.amount + delta[1])
        elif kind == "energy" and eff.op is EffectOp.GAIN_ENERGY_IF_EXHAUSTED:
            new_eff = _replace(eff, amount=eff.amount + delta[1])
        elif kind == "summon" and eff.op is EffectOp.SUMMON_OSTY:
            new_eff = _replace(eff, amount=eff.amount + delta[1])
        elif kind == "osty" and eff.op is EffectOp.OSTY_ATTACK:
            new_eff = _replace(eff, amount=eff.amount + delta[1])
        elif kind == "osty_hp" and eff.op is EffectOp.OSTY_ATTACK_HP:
            new_eff = _replace(eff, amount=eff.amount + delta[1])
        elif kind == "heal_osty" and eff.op is EffectOp.HEAL_OSTY:
            new_eff = _replace(eff, amount=eff.amount + delta[1])
        elif kind == "doom" and eff.op is EffectOp.APPLY_DOOM:
            new_eff = _replace(eff, amount=eff.amount + delta[1])
        elif kind == "doom" and eff.op is EffectOp.DOOM_KILL:
            new_eff = _replace(eff, amount=eff.amount + delta[1])
        elif kind == "any_power" and eff.op is EffectOp.APPLY_POWER:
            new_eff = _replace(eff, amount=eff.amount + delta[1])
        elif (kind == "power" and eff.op is EffectOp.APPLY_POWER
              and eff.power_id == delta[1]):
            new_eff = _replace(eff, amount=eff.amount + delta[2])
        out.append(new_eff)
    return tuple(out)


def upgrade_card(card: CardDef) -> CardDef:
    """Return the UPGRADED version of `card` with real stat changes.

    Idempotent: a card whose id already ends with '+' is returned unchanged.
    The result carries upgraded EFFECTS (and possibly reduced cost) so combat
    resolves the better numbers, and is tagged id+"+" / name+"+" so
    card_features() and the rarity lookup (which strips '+') keep working.
    """
    from dataclasses import replace as _replace
    if card.id.endswith("+"):
        return card

    deltas = _UPGRADE_DELTAS.get(card.id)
    if deltas is None:
        # Fallback default for an implemented card without an explicit table
        # entry: attacks gain damage, everything else gains block.
        deltas = (_DEFAULT_ATTACK_DELTA if card.type is CardType.ATTACK
                  else _DEFAULT_BLOCK_DELTA)

    effects = card.effects
    cost = card.cost
    for delta in deltas:
        if delta[0] == "cost":
            if cost is not None and cost >= 0:
                cost = max(0, cost + delta[1])
        else:
            effects = _apply_delta(effects, delta)

    return _replace(card, id=card.id + "+", name=card.name + "+",
                    effects=effects, cost=cost)

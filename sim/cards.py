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


def build_starting_deck() -> list[CardDef]:
    deck: list[CardDef] = []
    for c in IRONCLAD_STARTING_DECK:
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
        elif kind == "block" and eff.op is EffectOp.GAIN_BLOCK_IF_EXHAUSTED:
            new_eff = _replace(eff, amount=eff.amount + delta[1])
        elif kind == "energy" and eff.op is EffectOp.GAIN_ENERGY_IF_EXHAUSTED:
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

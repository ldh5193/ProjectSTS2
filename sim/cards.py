"""Ironclad cards — starting deck (notes/05_mvp_combat_spec.md §C.2) plus
a small library of common/uncommon cards porting verbatim from the
decompile (`decompiled/MegaCrit.Sts2.Core.Models.Cards/*.cs`).

Only cards expressible in the current dsl.py are included; anything
that needs new EffectOps (draw, exhaust, conditional triggers,
all-enemy targeting on >1 enemy) is left for a follow-up.
"""
from __future__ import annotations

from .dsl import CardDef, CardType, Effect, EffectOp, Scaling, ScalingKind, Target

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

RAGE = CardDef(  # simplified: +3 strength (real Rage applies RagePower)
    id="rage", name="Rage", cost=0, type=CardType.SKILL, count=0,
    effects=(
        Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
               power_id="strength", amount=3),
    ),
)

BATTLE_TRANCE = CardDef(
    id="battle_trance", name="Battle Trance", cost=0, type=CardType.SKILL, count=0,
    effects=(
        Effect(op=EffectOp.DRAW_CARD, target=Target.SELF, amount=3),
        # NoDraw power deferred — skip for now (still draws 3 unconditionally).
    ),
)

HEADBUTT = CardDef(
    id="headbutt", name="Headbutt", cost=1, type=CardType.ATTACK, count=0,
    effects=(
        Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
               amount=9, scaling=STRIKE_SCALING),
        # "move card from discard to draw top" — needs new EffectOp; skip second effect.
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
        Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
               amount=6, scaling=STRIKE_SCALING + (
                   __import__("sim.dsl", fromlist=["Scaling", "ScalingKind"]).Scaling(
                       kind=__import__("sim.dsl", fromlist=["ScalingKind"]).ScalingKind.STRIKE_TAG_COUNT,
                       owner="dealer"),
               )),
    ),
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

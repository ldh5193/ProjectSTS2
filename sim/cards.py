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
)


def build_starting_deck() -> list[CardDef]:
    deck: list[CardDef] = []
    for c in IRONCLAD_STARTING_DECK:
        deck.extend([c] * c.count)
    return deck

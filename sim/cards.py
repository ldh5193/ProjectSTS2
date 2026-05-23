"""Ironclad starting deck — notes/05_mvp_combat_spec.md §C.2."""
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


def build_starting_deck() -> list[CardDef]:
    deck: list[CardDef] = []
    for c in IRONCLAD_STARTING_DECK:
        deck.extend([c] * c.count)
    return deck

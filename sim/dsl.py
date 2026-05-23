"""Card-effect DSL — Phase 6 formalization of notes/05_mvp_combat_spec.md §E."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Target(str, Enum):
    SELF = "self"
    SELECTED_ENEMY = "selected_enemy"
    ALL_ENEMIES = "all_enemies"


class CardType(str, Enum):
    ATTACK = "attack"
    SKILL = "skill"
    POWER = "power"


class EffectOp(str, Enum):
    DEAL_DAMAGE = "deal_damage"
    GAIN_BLOCK = "gain_block"
    APPLY_POWER = "apply_power"


class ScalingKind(str, Enum):
    STRENGTH_ADDITIVE = "strength_additive"
    VULNERABLE_MULTIPLICATIVE = "vulnerable_multiplicative"
    WEAK_MULTIPLICATIVE = "weak_multiplicative"


@dataclass(frozen=True)
class Scaling:
    kind: ScalingKind
    owner: str  # "dealer" or "target"


@dataclass(frozen=True)
class Effect:
    op: EffectOp
    target: Target
    amount: int = 0
    power_id: str | None = None
    duration: int = 0
    scaling: tuple[Scaling, ...] = ()


@dataclass(frozen=True)
class CardDef:
    id: str
    name: str
    cost: int
    type: CardType
    effects: tuple[Effect, ...]
    count: int = 1  # copies in starting deck

"""Card-effect DSL — Phase 6 formalization of notes/05_mvp_combat_spec.md §E."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Target(str, Enum):
    SELF = "self"
    SELECTED_ENEMY = "selected_enemy"
    ALL_ENEMIES = "all_enemies"
    RANDOM_ENEMY = "random_enemy"


class CardType(str, Enum):
    ATTACK = "attack"
    SKILL = "skill"
    POWER = "power"


class EffectOp(str, Enum):
    DEAL_DAMAGE = "deal_damage"
    GAIN_BLOCK = "gain_block"
    APPLY_POWER = "apply_power"
    # Cycle B additions (notes/14_card_ops.md):
    DRAW_CARD = "draw_card"               # PommelStrike, ShrugItOff
    ENERGY_GAIN = "energy_gain"            # Bloodletting
    SELF_HP_LOSE = "self_hp_lose"          # Bloodwall (Unblockable self-damage)
    EXHAUST_RANDOM = "exhaust_random"      # Cinder
    EXHAUST_SELF = "exhaust_self"          # Tremble keyword
    COPY_TO_DISCARD = "copy_to_discard"    # Anger
    UPGRADE_ALL_IN_HAND = "upgrade_all_in_hand"  # Armaments upgraded
    AUTO_PLAY_FROM_DRAW = "auto_play_from_draw"  # Havoc


class ScalingKind(str, Enum):
    STRENGTH_ADDITIVE = "strength_additive"
    VULNERABLE_MULTIPLICATIVE = "vulnerable_multiplicative"
    WEAK_MULTIPLICATIVE = "weak_multiplicative"
    BLOCK_AMOUNT = "block_amount"          # BodySlam: damage = current block
    STRIKE_TAG_COUNT = "strike_tag_count"  # PerfectedStrike: +N per Strike in deck


@dataclass(frozen=True)
class Scaling:
    kind: ScalingKind
    owner: str  # "dealer" or "target"


@dataclass(frozen=True)
class Effect:
    op: EffectOp
    target: Target = Target.SELF
    amount: int = 0
    power_id: str | None = None
    duration: int = 0
    scaling: tuple[Scaling, ...] = ()
    hit_count: int = 1   # SwordBoomerang (3), TwinStrike (2)


@dataclass(frozen=True)
class CardDef:
    id: str
    name: str
    cost: int
    type: CardType
    effects: tuple[Effect, ...]
    count: int = 1  # copies in starting deck

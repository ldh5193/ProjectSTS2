"""Damage / block resolution pipeline.

Mirrors Hook.ModifyDamageInternal (notes/05_mvp_combat_spec.md §D.3, §D.5):

  modified = base
  modified += sum(power.modify_damage_additive(...) for power in dealer.powers + target.powers)
  for power in dealer.powers + target.powers:
      modified *= power.modify_damage_multiplicative(...)
  blocked = min(target.block, modified_floor)
  target.block -= blocked
  unblocked = modified_floor - blocked
  target.lose_hp(unblocked)
"""
from __future__ import annotations

from math import floor

from .creatures import Creature


def compute_modified_damage(base_amount: int, dealer: Creature, target: Creature) -> int:
    additive = 0
    for p in dealer.powers + target.powers:
        additive += p.modify_damage_additive(dealer, target, base_amount)

    modified = float(base_amount + additive)
    for p in dealer.powers + target.powers:
        modified *= p.modify_damage_multiplicative(dealer, target, base_amount)

    # Game uses decimal; we floor to int for simulator (matches §D.5 "13.5 → 13").
    return max(0, floor(modified))


def deal_damage(base_amount: int, dealer: Creature, target: Creature) -> tuple[int, int]:
    """Resolve a single attack. Returns (blocked_amount, hp_loss)."""
    modified = compute_modified_damage(base_amount, dealer, target)
    blocked = min(target.block, modified)
    target.block -= blocked
    unblocked = modified - blocked
    hp_loss = target.lose_hp(unblocked)
    return blocked, hp_loss


def gain_block(creature: Creature, amount: int) -> None:
    # No Frail/Dexterity modeled in MVP. Block accumulates without turn-reset
    # (notes/05_mvp_combat_spec.md §D.4: "persists across turns until depleted").
    creature.block += amount

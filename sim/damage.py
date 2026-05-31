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
    # TODO(faithful): real game keeps fractional damage through the block step
    # and only truncates at HP-loss. We floor here (before block). Matters only
    # for multi-hit fractional cases that don't exist in current content.
    return max(0, floor(modified))


def deal_damage(base_amount: int, dealer: Creature, target: Creature) -> tuple[int, int]:
    """Resolve a single attack. Returns (blocked_amount, hp_loss)."""
    modified = compute_modified_damage(base_amount, dealer, target)
    blocked = min(target.block, modified)
    target.block -= blocked
    unblocked = modified - blocked
    # HP-loss modifiers (relic-powers): The Boot (dealer-side, raise small
    # powered hits to 5) then Tungsten Rod (target-side, −1 HP loss). Order
    # mirrors the decompile: ModifyHpLostBeforeOsty (Boot) then AfterOsty
    # (Tungsten Rod). Both are no-ops unless the relic-power is present.
    if unblocked > 0:
        for p in dealer.powers:
            unblocked = p.modify_hp_lost(dealer, target, unblocked)
        for p in target.powers:
            unblocked = p.modify_hp_lost(dealer, target, unblocked)
        unblocked = max(0, unblocked)
    hp_loss = target.lose_hp(unblocked)
    # Thorns: if target has thorns AND took unblocked damage from a powered
    # attack (we approximate "powered" as "the attack went through deal_damage"
    # rather than self-damage). Dealer takes thorns damage, unblockable.
    thorns = target.get_power("thorns") if hasattr(target, "get_power") else None
    if (thorns is not None and thorns.amount > 0 and unblocked > 0
            and dealer is not target and dealer.alive):
        dealer.lose_hp(thorns.amount)
    # Attack-reaction hooks (Phase 8B): fire on_attacked for every power held by
    # the TARGET (Curl Up, Flame Barrier, Reflect, Slumber/Asleep, Flutter) and
    # by the DEALER (Painful Stabs, Envenom react to landing an attack). Iterate
    # snapshots so a hook that removes its own power is safe. Guarded on
    # dealer is not target (self-damage does not trigger reactions).
    if dealer is not target:
        for p in list(target.powers):
            p.on_attacked(target, dealer, blocked, unblocked)
        for p in list(dealer.powers):
            p.on_attacked(dealer, target, blocked, unblocked)
    # Vigor (VigorPower.cs): consumed after the powered attack it boosted.
    # We treat any attack routed through deal_damage as a powered attack, so
    # remove the dealer's Vigor entirely (ModifyAmount(-amountWhenStarted)).
    vigor = dealer.get_power("vigor") if hasattr(dealer, "get_power") else None
    if vigor is not None:
        dealer.powers.remove(vigor)
    return blocked, hp_loss


def gain_block(creature: Creature, amount: int) -> None:
    """Add block to a creature, applying Dexterity (additive +N from owner),
    Frail (×0.75) and any other block-multiplicative powers (Unmovable ×2 on
    the owner's first N card block-gains this turn)."""
    actual = float(amount)
    if hasattr(creature, "get_power"):
        for p in creature.powers:
            actual += p.modify_block_additive(creature, amount)
        for p in creature.powers:
            actual *= p.modify_block_multiplicative(creature, amount)
    creature.block += max(0, int(actual))


def apply_poison_tick(creature: Creature) -> int:
    """Apply Poison damage at the START of the owner's turn (PoisonPower.cs
    AfterSideTurnStart): HP -= stacks (unblockable), then stacks -= 1.
    Returns the HP loss (0 if no poison)."""
    poison = creature.get_power("poison") if hasattr(creature, "get_power") else None
    if poison is None or poison.amount <= 0:
        return 0
    loss = creature.lose_hp(poison.amount)
    poison.amount -= 1
    if poison.amount <= 0:
        creature.powers.remove(poison)
    return loss

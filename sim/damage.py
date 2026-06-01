"""Damage / block resolution pipeline.

GROUND TRUTH (decompiled, exact):
  - decompiled/MegaCrit.Sts2.Core.Commands/CreatureCmd.cs Damage() lines 134-154
  - decompiled/MegaCrit.Sts2.Core.Hooks/Hook.cs ModifyDamage()/ModifyDamageInternal()
    lines 1130-1213 / 1950-1994
  - decompiled/MegaCrit.Sts2.Core.Entities.Creatures/Creature.cs
    DamageBlockInternal() 367-372, LoseHpInternal() 374-386

Real pipeline (all arithmetic is C# `decimal`, NOT float):
  1. modified = base                                            (ModifyDamageInternal)
     modified += Σ ModifyDamageAdditive   (Strength, Vigor, ...)   — additive pass
     modified *= Π ModifyDamageMultiplicative (Vulnerable ×1.5,
                  Weak ×0.75, DoubleDamage ×2, Soar/Colossus ×0.5) — mult pass
     modified  = clamp to smallest ModifyDamageCap (Slippery=1, HardToKill)
     modified  = Math.Max(0m, modified)                         (NOT floored yet)
  2. blocked  = Unblockable ? 0 : Math.Min(Block, modified)     (DamageBlockInternal)
     Block   -= (int)blocked                                    (block truncates here)
  3. unblocked = Math.Max(modified - blocked, 0m)               (still decimal)
     unblocked = ModifyHpLostBeforeOsty(...)  (The Boot, HardenedShell, Buffer)
     unblocked = ModifyHpLostAfterOsty(...)   (Tungsten Rod, Intangible, BeatingRemnant)
  4. hpLoss = (int)Math.Min(unblocked, 999999999m)              (LoseHpInternal — the
     CurrentHp -= hpLoss                                         ONLY truncation of dmg)

EXACTNESS NOTE (resolves the campaign's "floor-before-block vs truncate-at-HP-loss"):
We floor the modified amount BEFORE the block step. For a SINGLE attack instance with
an INTEGER Block (always true — Block is stored int), this is mathematically identical
to the real game's truncate-at-HP-loss for both the final HP loss AND the residual
Block, because for modified m>=0 and integer B:
    floor(m) - min(B, floor(m)) == (int)( m - min(B, m) )   and
    B - min(B, floor(m))        == B - (int) min(B, m).
Verified exhaustively in tests/test_damage_exactness.py. The real game never carries a
fractional damage instance across hits (each hit is an independent decimal), so there is
no multi-hit accumulation case where this diverges. Hence the sim is bit-exact.

`powered` mirrors ValueProp.IsPoweredAttack() == Move && !Unpowered
(decompiled ValuePropExtensions.cs:5-12). Strength / Vulnerable / Weak / DoubleDamage /
Shrink / Soar / Colossus / Cruelty / Vigor all `return base/1m` when
`!props.IsPoweredAttack()`, so UNPOWERED damage (Thorns, Juggernaut, Combust,
FlameBarrier, Reflect, Inferno, Charon's Ashes, relic/potion AoE bursts) ignores every
additive AND multiplicative damage-power. The damage CAP and the HP-lost (Osty) hooks
are NOT powered-gated and still apply.
"""
from __future__ import annotations

from math import floor

from .creatures import Creature


def compute_modified_damage(base_amount: int, dealer: Creature, target: Creature,
                            powered: bool = True) -> int:
    if powered:
        additive = 0
        for p in dealer.powers + target.powers:
            additive += p.modify_damage_additive(dealer, target, base_amount)

        modified = float(base_amount + additive)
        for p in dealer.powers + target.powers:
            modified *= p.modify_damage_multiplicative(dealer, target, base_amount)
    else:
        # Unpowered (ValueProp.Unpowered): no Strength/Vulnerable/Weak/etc.
        modified = float(base_amount)

    # See module docstring: flooring here before block is bit-exact vs the
    # decompile's truncate-at-HP-loss for single integer-block attack instances.
    result = max(0, floor(modified))
    # Damage-cap powers (ModifyDamageCap): Slippery (cap 1), Hard To Kill (cap
    # `amount`). Applied regardless of powered (not IsPoweredAttack-gated). The
    # smallest cap across the target's powers wins.
    for p in target.powers:
        result = p.modify_damage_cap(dealer, target, result)
    return max(0, result)


def deal_damage(base_amount: int, dealer: Creature, target: Creature,
                powered: bool = True) -> tuple[int, int]:
    """Resolve a single attack. Returns (blocked_amount, hp_loss).

    `powered=False` mirrors AttackCommand.Unpowered() / DamageProps.nonCardUnpowered:
    the hit skips all Strength/Vulnerable/Weak/multiplier powers (see module docstring)."""
    # Osty taunt (DieForYouPower.ModifyUnblockedDamageTarget): a POWERED attack
    # aimed at the pet's owner (the player) is redirected to the living pet
    # (Osty). The player carries `_osty_guardian` -> the Osty creature while a
    # summon is up. Unpowered hits (Thorns/poison/orb passives) are NOT
    # redirected (the .cs gates on props.IsPoweredAttack()).
    if powered and dealer is not target:
        guardian = getattr(target, "_osty_guardian", None)
        if (guardian is not None and guardian is not target
                and getattr(guardian, "alive", False) and guardian.hp > 0):
            target = guardian
    modified = compute_modified_damage(base_amount, dealer, target, powered=powered)
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
    # NecroMastery (NecroMasteryPower.AfterCurrentHpChanged on Osty, delta<0):
    # when the pet (Osty) loses HP from any hit, deal hp_lost * stacks
    # Unblockable|Unpowered to all enemies. Osty carries a `_combat` back-ref
    # (set on summon) and the minion marker; the player holds NecroMastery.
    if hp_loss > 0 and target.get_power("minion") is not None:
        cs = getattr(target, "_combat", None)
        if cs is not None:
            from .osty import _fire_osty_hp_loss
            _fire_osty_hp_loss(cs, hp_loss)
    # Thorns (ThornsPower.cs:17-24): triggers only on a POWERED attack
    # (props.IsPoweredAttack()), NOT on unpowered damage (Juggernaut/Combust/
    # potion/relic bursts). Dealer takes thorns damage, unblockable.
    thorns = target.get_power("thorns") if hasattr(target, "get_power") else None
    if (powered and thorns is not None and thorns.amount > 0 and unblocked > 0
            and dealer is not target and dealer.alive):
        dealer.lose_hp(thorns.amount)
    # Attack-reaction hooks (Phase 8B): fire on_attacked for every power held by
    # the TARGET (Curl Up, Flame Barrier, Reflect, Slumber/Asleep, Flutter) and
    # by the DEALER (Painful Stabs, Envenom react to landing an attack). These
    # decompiled powers gate on props.IsPoweredAttack(), so an UNPOWERED hit
    # triggers no reactions. Iterate snapshots so a hook that removes its own
    # power is safe. Guarded on
    # dealer is not target (self-damage does not trigger reactions).
    if powered and dealer is not target:
        for p in list(target.powers):
            p.on_attacked(target, dealer, blocked, unblocked)
        for p in list(dealer.powers):
            p.on_attacked(dealer, target, blocked, unblocked)
    # Vigor (VigorPower.cs): consumed after the POWERED attack it boosted (it
    # is IsPoweredAttack-gated). An unpowered hit neither benefits from nor
    # consumes Vigor. Remove the dealer's Vigor entirely after a powered hit.
    if powered:
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

"""Power (buff/debuff) system.

Cites: decompiled/MegaCrit.Sts2.Core.*/powers — Strength, Vulnerable, Weak.

Key invariants from the decompile (notes/05_mvp_combat_spec.md §D.3):
- StrengthPower: additive bonus to dealer's powered attacks. Returns base.Amount
  (i.e. stack count contributes linearly: Strength 3 → +3).
- VulnerablePower: multiplicative ×1.5 on damage incoming to owner. Returns the
  static 1.5 value regardless of stack count. Stacks are duration, not multiplier.
- WeakPower: multiplicative ×0.75 on damage outgoing from owner. (Standard STS1
  semantics; STS2 decompile confirms via WeakPower.ModifyDamageMultiplicative.)
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Power:
    id: str
    amount: int = 1

    def modify_damage_additive(self, dealer, target, base_amount: int) -> int:
        return 0

    def modify_damage_multiplicative(self, dealer, target, base_amount: int) -> float:
        return 1.0


@dataclass
class StrengthPower(Power):
    id: str = field(default="strength", init=False)

    def modify_damage_additive(self, dealer, target, base_amount: int) -> int:
        # Only the dealer's own Strength counts.
        if self._owner is not dealer:
            return 0
        return self.amount

    _owner: object = None


@dataclass
class VulnerablePower(Power):
    id: str = field(default="vulnerable", init=False)

    def modify_damage_multiplicative(self, dealer, target, base_amount: int) -> float:
        # Only when the Vulnerable creature is the target.
        if target is not self._owner:
            return 1.0
        return 1.5

    _owner: object = None


@dataclass
class WeakPower(Power):
    id: str = field(default="weak", init=False)

    def modify_damage_multiplicative(self, dealer, target, base_amount: int) -> float:
        # Only when the Weak creature is the dealer.
        if dealer is not self._owner:
            return 1.0
        return 0.75

    _owner: object = None


POWER_REGISTRY: dict[str, type[Power]] = {
    "strength": StrengthPower,
    "vulnerable": VulnerablePower,
    "weak": WeakPower,
}


def make_power(power_id: str, amount: int, owner) -> Power:
    cls = POWER_REGISTRY[power_id]
    p = cls(amount=amount)
    p._owner = owner
    return p

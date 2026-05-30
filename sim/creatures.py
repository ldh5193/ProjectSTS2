"""Creature base + Player/Monster.

Cites: notes/05_mvp_combat_spec.md §C (player), §B (monster).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .powers import Power


@dataclass
class Creature:
    name: str
    hp: int
    max_hp: int
    block: int = 0
    powers: list[Power] = field(default_factory=list)
    alive: bool = True

    def get_power(self, power_id: str) -> Power | None:
        for p in self.powers:
            if p.id == power_id:
                return p
        return None

    def add_or_stack_power(self, new_power: Power) -> None:
        existing = self.get_power(new_power.id)
        if existing is None:
            self.powers.append(new_power)
        else:
            existing.amount += new_power.amount

    def lose_hp(self, amount: int) -> int:
        actual = min(self.hp, amount)
        self.hp -= actual
        if self.hp <= 0:
            self.hp = 0
            self.alive = False
        return actual

    def heal(self, amount: int) -> int:
        """Restore up to `amount` HP, capped at max_hp. Returns HP gained."""
        if amount <= 0 or not self.alive:
            return 0
        before = self.hp
        self.hp = min(self.max_hp, self.hp + amount)
        return self.hp - before

    def gain_max_hp(self, amount: int) -> None:
        """Permanently raise max HP and heal by the same amount (Feed)."""
        if amount <= 0:
            return
        self.max_hp += amount
        self.hp += amount


@dataclass
class Player(Creature):
    energy: int = 0
    max_energy: int = 3


@dataclass
class Monster(Creature):
    def intent_damage(self) -> int:
        """Raw outgoing damage the current intent would deal this turn.

        Default 0; attacking monsters override this. The RL env uses it to
        populate the agent's "incoming damage next turn" observation.
        """
        return 0

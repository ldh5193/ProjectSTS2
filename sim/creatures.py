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

    # Powers that count as "debuffs" for Artifact negation (STS: a debuff is a
    # power applied by an enemy that the owner does not want). The owner-applied
    # buffs (strength/dexterity/etc.) are NOT negated.
    _DEBUFF_IDS = frozenset({"weak", "frail", "vulnerable", "poison"})

    def add_or_stack_power(self, new_power: Power) -> None:
        # Status-immunity relics (Ginger -> Weak, Turnip -> Frail). If the
        # owner carries an immunity power, the matching debuff is ignored.
        if new_power.id == "weak" and any(p.blocks_weak() for p in self.powers):
            return
        if new_power.id == "frail" and any(p.blocks_frail() for p in self.powers):
            return
        # Artifact: consume one charge to negate an incoming debuff.
        if new_power.id in self._DEBUFF_IDS:
            art = self.get_power("artifact")
            if art is not None and art.amount > 0:
                art.amount -= 1
                if art.amount <= 0:
                    self.powers.remove(art)
                return
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

    def lose_max_hp(self, amount: int) -> int:
        """Permanently reduce max HP (CreatureCmd.LoseMaxHp; PaperCuts). Current
        HP is clamped to the new max. Returns the max-HP reduction applied (the
        max cannot go below 1). Dropping current HP to 0 kills the creature."""
        if amount <= 0:
            return 0
        reduced = min(amount, self.max_hp - 1)
        self.max_hp -= reduced
        if self.hp > self.max_hp:
            self.hp = self.max_hp
        if self.hp <= 0:
            self.hp = 0
            self.alive = False
        return reduced


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

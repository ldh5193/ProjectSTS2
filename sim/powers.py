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

    # ---- trigger hooks (no-op defaults; engine powers override) ----
    # `cs` is the CombatState, `owner` is the creature that holds this power
    # (i.e. the side whose event just fired).

    def on_turn_start(self, cs, owner) -> None:
        """Owner's turn begins (after draw for the player)."""

    def on_turn_end(self, cs, owner) -> None:
        """Owner's turn ends."""

    def on_card_exhausted(self, cs, owner, card) -> None:
        """A card belonging to `owner` was exhausted."""

    def on_block_gained(self, cs, owner, amount: int) -> None:
        """Owner just gained `amount` block (amount > 0)."""

    def on_hp_lost_from_card(self, cs, owner, amount: int) -> None:
        """Owner lost `amount` HP from a card effect (amount > 0)."""

    def modify_card_cost(self, card) -> int | None:
        """Return an override cost for `card`, or None to leave unchanged
        (Corruption: skills cost 0)."""
        return None

    def blocks_block_reset(self) -> bool:
        """If True, the owner's block is NOT reset at turn start (Barricade)."""
        return False


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


@dataclass
class DexterityPower(Power):
    """+amount block on powered block from owner (additive)."""
    id: str = field(default="dexterity", init=False)

    def modify_block_additive(self, dealer, base_amount: int) -> int:
        if dealer is not self._owner:
            return 0
        return self.amount

    _owner: object = None


@dataclass
class FrailPower(Power):
    """×0.75 block on powered block from owner. Counter is duration (tick at owner turn end)."""
    id: str = field(default="frail", init=False)

    def modify_block_multiplicative(self, dealer, base_amount: int) -> float:
        if dealer is not self._owner:
            return 1.0
        return 0.75

    _owner: object = None


@dataclass
class ThornsPower(Power):
    """When owner takes powered attack damage, attacker takes amount unblockable."""
    id: str = field(default="thorns", init=False)
    _owner: object = None


@dataclass
class PlatingPower(Power):
    """Plating (PlatingPower.cs): NOT damage reduction. It grants the owner
    Block equal to `amount` at the owner's turn-end (BeforeTurnEndEarly,
    side == Owner.Side), and decrements at enemy turn-end by the attacker
    count (1 in single-player). Enemies also gain `amount` block at round-1
    side start. We model the recurring block-gain at the owner's turn end
    (the faithful BeforeTurnEndEarly trigger) and decay the counter at the
    same point. See combat.py end-of-turn handling."""
    id: str = field(default="plating", init=False)
    _owner: object = None


@dataclass
class PoisonPower(Power):
    """Poison (PoisonPower.cs): ticks at the START of the owner's turn
    (AfterSideTurnStart, side == Owner.Side): deals `amount` unblockable
    damage, then decrements by 1."""
    id: str = field(default="poison", init=False)
    _owner: object = None


@dataclass
class VigorPower(Power):
    """Vigor (VigorPower.cs): +amount additive damage on the owner's next
    powered attack, then the power is removed entirely after that attack
    (consumed). See deal_damage() which performs the consumption."""
    id: str = field(default="vigor", init=False)

    def modify_damage_additive(self, dealer, target, base_amount: int) -> int:
        if dealer is not self._owner:
            return 0
        return self.amount

    _owner: object = None


# ---------------------------------------------------------------------------
# Engine powers (Ironclad "deck-power" cards). Each overrides exactly one
# trigger hook. Strength gains stack via the existing make_power/add_or_stack.
# Cites: decompiled/MegaCrit.Sts2.Core.Models.Powers/{DemonForm,FeelNoPain,
#   DarkEmbrace,Juggernaut,Rupture,Barricade,Corruption}Power.cs.
# Note: STS2 has no separate Metallicize/Berserk/Brutality/Combust power
#   (Furnace is STS2's turn-start block-gain analog). Those four are modelled
#   here with faithful STS1 semantics so the classic Ironclad engine works.
# ---------------------------------------------------------------------------


@dataclass
class DemonFormPower(Power):
    """DemonFormPower.cs (AfterSideTurnStart, side == Owner.Side): owner gains
    Strength == amount at the start of every owner turn. StackType Counter — the
    counter does not decrement (it is the per-turn Strength gain)."""
    id: str = field(default="demon_form", init=False)
    _owner: object = None

    def on_turn_start(self, cs, owner) -> None:
        owner.add_or_stack_power(make_power("strength", self.amount, owner))


@dataclass
class MetallicizePower(Power):
    """Gain `amount` Block at turn end (STS1 MetallicizePower). STS2 ships this
    as FurnacePower at turn *start*; we follow the task's turn-end semantics."""
    id: str = field(default="metallicize", init=False)
    _owner: object = None

    def on_turn_end(self, cs, owner) -> None:
        from .damage import gain_block
        gain_block(owner, self.amount)


@dataclass
class FeelNoPainPower(Power):
    """FeelNoPainPower.cs (AfterCardExhausted): whenever a card the owner owns
    is exhausted, gain `amount` Block (Unpowered — Dexterity/Frail still apply
    via gain_block, matching CreatureCmd.GainBlock)."""
    id: str = field(default="feel_no_pain", init=False)
    _owner: object = None

    def on_card_exhausted(self, cs, owner, card) -> None:
        from .damage import gain_block
        gain_block(owner, self.amount)


@dataclass
class DarkEmbracePower(Power):
    """DarkEmbracePower.cs (AfterCardExhausted, non-ethereal): draw `amount`
    cards per exhausted card. STS2 base amount is 1."""
    id: str = field(default="dark_embrace", init=False)
    _owner: object = None

    def on_card_exhausted(self, cs, owner, card) -> None:
        cs.draw(self.amount)


@dataclass
class JuggernautPower(Power):
    """JuggernautPower.cs (AfterBlockGained, amount > 0): deal `amount` damage
    (Unpowered) to a random hittable enemy. STS2 base amount is 5."""
    id: str = field(default="juggernaut", init=False)
    _owner: object = None

    def on_block_gained(self, cs, owner, amount: int) -> None:
        from .damage import deal_damage
        enemies = cs.alive_monsters()
        if not enemies:
            return
        target = cs.rng.choice(enemies)
        deal_damage(self.amount, owner, target)


@dataclass
class RupturePower(Power):
    """RupturePower.cs (AfterDamageReceived from a non-card source): when the
    owner loses HP from a card effect, gain Strength == amount. STS2 base 1."""
    id: str = field(default="rupture", init=False)
    _owner: object = None

    def on_hp_lost_from_card(self, cs, owner, amount: int) -> None:
        owner.add_or_stack_power(make_power("strength", self.amount, owner))


@dataclass
class CombustPower(Power):
    """Combust (STS1): at turn end lose `multiplier` HP and deal `amount`
    damage to ALL enemies. STS1 default: lose 1 HP, deal 5 to all per stack.
    We store damage in `amount` and HP-loss-per-turn in `multiplier`."""
    id: str = field(default="combust", init=False)
    multiplier: int = 1
    _owner: object = None

    def on_turn_end(self, cs, owner) -> None:
        from .damage import deal_damage
        owner.lose_hp(self.multiplier)
        for m in cs.alive_monsters():
            if m.alive:
                deal_damage(self.amount, owner, m)


@dataclass
class BarricadePower(Power):
    """BarricadePower.cs (ShouldClearBlock -> False for owner): the owner's
    block is not reset at the start of its turn."""
    id: str = field(default="barricade", init=False)
    _owner: object = None

    def blocks_block_reset(self) -> bool:
        return True


@dataclass
class BerserkPower(Power):
    """Berserk (STS1): at the start of each turn, gain `amount` energy."""
    id: str = field(default="berserk", init=False)
    _owner: object = None

    def on_turn_start(self, cs, owner) -> None:
        owner.energy += self.amount


@dataclass
class BrutalityPower(Power):
    """Brutality (STS1): at the start of each turn, lose `amount` HP and draw
    `amount` cards."""
    id: str = field(default="brutality", init=False)
    _owner: object = None

    def on_turn_start(self, cs, owner) -> None:
        owner.lose_hp(self.amount)
        cs.draw(self.amount)


@dataclass
class CorruptionPower(Power):
    """CorruptionPower.cs: Skills cost 0 (TryModifyEnergyCostInCombat) and are
    exhausted when played (ModifyCardPlayResultPileTypeAndPosition)."""
    id: str = field(default="corruption", init=False)
    _owner: object = None

    def modify_card_cost(self, card) -> int | None:
        # CardType.SKILL → 0. Imported lazily to avoid a dsl import cycle.
        from .dsl import CardType
        if card.type is CardType.SKILL:
            return 0
        return None


POWER_REGISTRY: dict[str, type[Power]] = {
    "strength": StrengthPower,
    "vulnerable": VulnerablePower,
    "weak": WeakPower,
    "dexterity": DexterityPower,
    "frail": FrailPower,
    "thorns": ThornsPower,
    "plating": PlatingPower,
    "poison": PoisonPower,
    "vigor": VigorPower,
    # Engine powers (Ironclad deck-power cards)
    "demon_form": DemonFormPower,
    "metallicize": MetallicizePower,
    "feel_no_pain": FeelNoPainPower,
    "dark_embrace": DarkEmbracePower,
    "juggernaut": JuggernautPower,
    "rupture": RupturePower,
    "combust": CombustPower,
    "barricade": BarricadePower,
    "berserk": BerserkPower,
    "brutality": BrutalityPower,
    "corruption": CorruptionPower,
}


def make_power(power_id: str, amount: int, owner) -> Power:
    cls = POWER_REGISTRY[power_id]
    p = cls(amount=amount)
    p._owner = owner
    return p

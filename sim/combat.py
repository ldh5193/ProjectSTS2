"""Combat state machine — skeleton wiring player/monster + turn cycle.

Cites: notes/03_system_mapping.md §2 (turn lifecycle), notes/05_mvp_combat_spec.md §C.

Minimal scope: single SludgeSpinnerWeak vs Ironclad, no orbs/potions/relics.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from .cards import build_starting_deck
from .creatures import Player
from .damage import deal_damage, gain_block
from .dsl import CardDef, EffectOp, Target
from .monsters import SludgeSpinnerWeak
from .powers import make_power


PLAYER_MAX_HP = 80
PLAYER_ENERGY_PER_TURN = 3
HAND_SIZE = 5


@dataclass
class CombatState:
    player: Player
    monster: SludgeSpinnerWeak
    draw_pile: list[CardDef]
    discard_pile: list[CardDef] = field(default_factory=list)
    hand: list[CardDef] = field(default_factory=list)
    exhaust_pile: list[CardDef] = field(default_factory=list)
    rng: random.Random = field(default_factory=random.Random)
    turn_number: int = 0
    is_player_turn: bool = True

    @classmethod
    def new_combat(cls, seed: int | None = None) -> "CombatState":
        rng = random.Random(seed)
        deck = build_starting_deck()
        rng.shuffle(deck)
        player = Player(
            name="Ironclad",
            hp=PLAYER_MAX_HP,
            max_hp=PLAYER_MAX_HP,
            energy=PLAYER_ENERGY_PER_TURN,
            max_energy=PLAYER_ENERGY_PER_TURN,
        )
        monster = SludgeSpinnerWeak.spawn(rng)
        return cls(player=player, monster=monster, draw_pile=deck, rng=rng)

    # ---- pile management ----

    def draw(self, n: int) -> None:
        for _ in range(n):
            if not self.draw_pile:
                if not self.discard_pile:
                    return
                self.draw_pile = self.discard_pile
                self.discard_pile = []
                self.rng.shuffle(self.draw_pile)
            self.hand.append(self.draw_pile.pop())

    # ---- turn lifecycle ----

    def start_player_turn(self) -> None:
        self.turn_number += 1
        self.is_player_turn = True
        self.player.energy = self.player.max_energy
        # Block does NOT auto-reset per §D.4. (No Barricade modeled.)
        self.player.block = 0  # Simplification: STS-style turn reset for player
        self.draw(HAND_SIZE)

    def can_play(self, card_index: int) -> bool:
        if not (0 <= card_index < len(self.hand)):
            return False
        card = self.hand[card_index]
        return self.player.energy >= card.cost

    def play_card(self, card_index: int, target_is_monster: bool = True) -> None:
        if not self.can_play(card_index):
            raise ValueError(f"cannot play card at index {card_index}")
        card = self.hand.pop(card_index)
        self.player.energy -= card.cost
        self._resolve_effects(card)
        self.discard_pile.append(card)

    def _resolve_effects(self, card: CardDef) -> None:
        for eff in card.effects:
            target = self.monster if eff.target is Target.SELECTED_ENEMY else self.player
            if eff.op is EffectOp.DEAL_DAMAGE:
                deal_damage(eff.amount, self.player, target)
            elif eff.op is EffectOp.GAIN_BLOCK:
                gain_block(target, eff.amount)
            elif eff.op is EffectOp.APPLY_POWER:
                assert eff.power_id is not None
                target.add_or_stack_power(make_power(eff.power_id, eff.amount, target))

    def end_player_turn(self) -> None:
        self.is_player_turn = False
        # Discard hand at end of player turn (STS convention).
        self.discard_pile.extend(self.hand)
        self.hand.clear()
        # Weak's owner is player → tick at end of player turn.
        self._tick_powers(self.player, ids=("weak",))
        self.monster_turn()
        if self.monster.alive:
            self.start_player_turn()

    def monster_turn(self) -> dict:
        # Monster block also resets per turn in MVP (matches STS UI).
        self.monster.block = 0
        event = self.monster.take_turn(self.rng, self.player)
        # Vulnerable's owner is monster → tick at end of monster turn.
        self._tick_powers(self.monster, ids=("vulnerable",))
        return event

    @staticmethod
    def _tick_powers(creature, ids: tuple[str, ...]) -> None:
        for p in list(creature.powers):
            if p.id in ids:
                p.amount -= 1
                if p.amount <= 0:
                    creature.powers.remove(p)

    # ---- terminal conditions ----

    def player_won(self) -> bool:
        return not self.monster.alive

    def player_lost(self) -> bool:
        return not self.player.alive

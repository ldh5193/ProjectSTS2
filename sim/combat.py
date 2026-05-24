"""Combat state machine — skeleton wiring player/monster + turn cycle.

Cites: notes/03_system_mapping.md §2 (turn lifecycle), notes/05_mvp_combat_spec.md §C.

Minimal scope: single SludgeSpinnerWeak vs Ironclad, no orbs/potions/relics.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from .cards import build_starting_deck
from .creatures import Monster, Player
from .damage import apply_poison_tick, deal_damage, gain_block
from .dsl import CardDef, EffectOp, Target
from .monsters import SludgeSpinnerWeak
from .powers import make_power


PLAYER_MAX_HP = 80
PLAYER_ENERGY_PER_TURN = 3
HAND_SIZE = 5


@dataclass
class CombatState:
    player: Player
    # `monster` keeps the legacy single-enemy API; `monsters` is the new
    # multi-enemy list. They're kept in sync — see _sync_monsters().
    monster: Monster
    draw_pile: list[CardDef]
    discard_pile: list[CardDef] = field(default_factory=list)
    hand: list[CardDef] = field(default_factory=list)
    exhaust_pile: list[CardDef] = field(default_factory=list)
    rng: random.Random = field(default_factory=random.Random)
    turn_number: int = 0
    is_player_turn: bool = True
    monsters: list[Monster] = field(default_factory=list)
    target_index: int = 0  # which monster Target.SELECTED_ENEMY hits

    def _sync_monsters(self) -> None:
        """Ensure `self.monsters` includes `self.monster` for legacy code."""
        if not self.monsters:
            self.monsters = [self.monster]
        elif self.monster is not self.monsters[0]:
            # The legacy field is the canonical "first" enemy.
            self.monsters[0] = self.monster

    def alive_monsters(self) -> list[Monster]:
        self._sync_monsters()
        return [m for m in self.monsters if m.alive]

    @classmethod
    def new_combat(cls, seed: int | None = None, monster_factory=None,
                   monsters_factory=None) -> "CombatState":
        """Build a fresh combat.

        `monster_factory(rng) -> Monster` (single-enemy mode, default
        SludgeSpinnerWeak) keeps existing callers working.
        `monsters_factory(rng) -> list[Monster]` is the new multi-enemy
        constructor; supplying it overrides monster_factory.
        """
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
        if monsters_factory is not None:
            monsters = monsters_factory(rng)
            cs = cls(player=player, monster=monsters[0], monsters=monsters,
                     draw_pile=deck, rng=rng)
            return cs
        if monster_factory is None:
            monster_factory = SludgeSpinnerWeak.spawn
        monster = monster_factory(rng)
        return cls(player=player, monster=monster, monsters=[monster],
                   draw_pile=deck, rng=rng)

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
            self._resolve_single_effect(card, eff)

    def _resolve_single_effect(self, card: CardDef, eff) -> None:  # noqa: PLR0912
        # Multi-monster targeting: SELECTED_ENEMY uses target_index (clamped
        # to alive); RANDOM_ENEMY picks one alive at random; ALL_ENEMIES hits
        # every alive monster. SELF always hits the player.
        alive = self.alive_monsters()
        if eff.target is Target.SELF:
            targets = [self.player]
        elif eff.target is Target.SELECTED_ENEMY:
            if not alive:
                targets = []
            else:
                idx = min(self.target_index, len(alive) - 1)
                targets = [alive[idx]]
        elif eff.target is Target.RANDOM_ENEMY:
            targets = [self.rng.choice(alive)] if alive else []
        elif eff.target is Target.ALL_ENEMIES:
            targets = list(alive)
        else:
            targets = []

        if eff.op is EffectOp.DEAL_DAMAGE:
            # Damage scaling: block-amount or strike-tag-count override base amount.
            base_amount = eff.amount
            for sc in eff.scaling:
                if sc.kind.value == "block_amount":
                    base_amount = self.player.block
                    break
                if sc.kind.value == "strike_tag_count":
                    base_amount += sum(1 for c in self.draw_pile + self.discard_pile + self.hand
                                       if "strike" in c.id)
                    break
            for _ in range(max(1, eff.hit_count)):
                for t in targets:
                    if t.alive:
                        deal_damage(base_amount, self.player, t)
            return
        if eff.op is EffectOp.GAIN_BLOCK:
            for t in targets:
                gain_block(t, eff.amount)
            return
        if eff.op is EffectOp.APPLY_POWER:
            assert eff.power_id is not None
            for t in targets:
                t.add_or_stack_power(make_power(eff.power_id, eff.amount, t))
            return
        if eff.op is EffectOp.DRAW_CARD:
            self.draw(eff.amount)
            return
        if eff.op is EffectOp.ENERGY_GAIN:
            self.player.energy += eff.amount
            return
        if eff.op is EffectOp.SELF_HP_LOSE:
            # Unblockable self-damage (Bloodletting, Bloodwall, Breakthrough).
            self.player.lose_hp(eff.amount)
            return
        if eff.op is EffectOp.EXHAUST_RANDOM:
            if self.hand:
                idx = self.rng.randrange(len(self.hand))
                self.exhaust_pile.append(self.hand.pop(idx))
            return
        if eff.op is EffectOp.EXHAUST_SELF:
            # Move the just-played card from discard back to exhaust.
            if self.discard_pile and self.discard_pile[-1] is card:
                self.exhaust_pile.append(self.discard_pile.pop())
            return
        if eff.op is EffectOp.COPY_TO_DISCARD:
            self.discard_pile.append(card)
            return
        if eff.op is EffectOp.UPGRADE_ALL_IN_HAND:
            # Placeholder: tag id with '+' (Cycle B leaves real per-card upgrades for later).
            from dataclasses import replace
            for i, c in enumerate(self.hand):
                if not c.id.endswith("+"):
                    self.hand[i] = replace(c, id=c.id + "+", name=c.name + "+")
            return
        if eff.op is EffectOp.AUTO_PLAY_FROM_DRAW:
            # Havoc: play the top of draw pile, then exhaust it.
            if self.draw_pile:
                c = self.draw_pile.pop()
                # Resolve its effects against the current target context.
                self._resolve_effects(c)
                self.exhaust_pile.append(c)
            return

    def end_player_turn(self) -> None:
        self.is_player_turn = False
        # Discard hand at end of player turn (STS convention).
        self.discard_pile.extend(self.hand)
        self.hand.clear()
        # Weak's owner is player → tick at end of player turn.
        self._tick_powers(self.player, ids=("weak",))
        # Poison ticks at end of owner's turn — player's poison hits player.
        apply_poison_tick(self.player)
        self.monster_turn()
        if self.alive_monsters():
            self.start_player_turn()

    def monster_turn(self) -> list[dict]:
        events: list[dict] = []
        for m in self.alive_monsters():
            # Monster block resets per turn in MVP (matches STS UI).
            m.block = 0
            events.append(m.take_turn(self.rng, self.player))
            # Vulnerable's owner is monster → tick at end of monster turn.
            self._tick_powers(m, ids=("vulnerable",))
            apply_poison_tick(m)
            if not self.player.alive:
                break
        # Re-target if the previously selected monster died this turn.
        alive = self.alive_monsters()
        if alive and self.target_index >= len(alive):
            self.target_index = 0
        return events

    @staticmethod
    def _tick_powers(creature, ids: tuple[str, ...]) -> None:
        for p in list(creature.powers):
            if p.id in ids:
                p.amount -= 1
                if p.amount <= 0:
                    creature.powers.remove(p)

    # ---- terminal conditions ----

    def player_won(self) -> bool:
        return not self.alive_monsters()

    def player_lost(self) -> bool:
        return not self.player.alive

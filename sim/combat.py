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

    # ---- power-trigger fan-out helpers ----

    @staticmethod
    def _fire_power_hook(creature, hook: str, *args) -> None:
        """Call `hook(*args)` on every power the creature currently holds.
        Iterates a snapshot so a hook that mutates `powers` is safe."""
        for p in list(creature.powers):
            getattr(p, hook)(*args)

    def start_player_turn(self) -> None:
        self.turn_number += 1
        self.is_player_turn = True
        self.player.energy = self.player.max_energy
        # Block resets at turn start unless a power (Barricade) blocks the reset.
        if not any(p.blocks_block_reset() for p in self.player.powers):
            self.player.block = 0
        # Poison ticks at the START of the owner's turn (PoisonPower.cs).
        apply_poison_tick(self.player)
        self.draw(HAND_SIZE)
        # Turn-start triggers: DemonForm (Strength), Berserk (energy),
        # Brutality (lose HP + draw). Fire after the draw, per the .cs ordering
        # of AfterSideTurnStart (DemonForm) which runs once the turn is set up.
        self._fire_power_hook(self.player, "on_turn_start", self, self.player)

    def effective_cost(self, card: CardDef) -> int:
        """Card's energy cost after player power overrides (Corruption: skills
        cost 0). Takes the minimum override across powers, floored at 0."""
        cost = card.cost
        for p in self.player.powers:
            override = p.modify_card_cost(card)
            if override is not None:
                cost = min(cost, override)
        return max(0, cost)

    def _exhaust_card(self, card: CardDef) -> None:
        """Move a card to the exhaust pile and fire on_card_exhausted for the
        player's powers (Feel No Pain block, Dark Embrace draw)."""
        self.exhaust_pile.append(card)
        self._fire_power_hook(self.player, "on_card_exhausted",
                              self, self.player, card)

    def can_play(self, card_index: int) -> bool:
        if not (0 <= card_index < len(self.hand)):
            return False
        card = self.hand[card_index]
        return self.player.energy >= self.effective_cost(card)

    def play_card(self, card_index: int, target_is_monster: bool = True) -> None:
        if not self.can_play(card_index):
            raise ValueError(f"cannot play card at index {card_index}")
        card = self.hand.pop(card_index)
        self.player.energy -= self.effective_cost(card)
        self._resolve_effects(card)
        # Corruption: skills are exhausted on play instead of discarded.
        from .dsl import CardType
        if (card.type is CardType.SKILL
                and any(p.id == "corruption" for p in self.player.powers)):
            self._exhaust_card(card)
        else:
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
                before = t.block
                gain_block(t, eff.amount)
                if t is self.player:
                    gained = t.block - before
                    if gained > 0:
                        # Juggernaut: deal damage to a random enemy on block gain.
                        self._fire_power_hook(t, "on_block_gained", self, t, gained)
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
            lost = self.player.lose_hp(eff.amount)
            if lost > 0:
                # Rupture: gain Strength when HP is lost from a card effect.
                self._fire_power_hook(self.player, "on_hp_lost_from_card",
                                      self, self.player, lost)
            return
        if eff.op is EffectOp.EXHAUST_RANDOM:
            if self.hand:
                idx = self.rng.randrange(len(self.hand))
                self._exhaust_card(self.hand.pop(idx))
            return
        if eff.op is EffectOp.EXHAUST_SELF:
            # Move the just-played card from discard back to exhaust.
            if self.discard_pile and self.discard_pile[-1] is card:
                self._exhaust_card(self.discard_pile.pop())
            return
        if eff.op is EffectOp.COPY_TO_DISCARD:
            self.discard_pile.append(card)
            return
        if eff.op is EffectOp.UPGRADE_ALL_IN_HAND:
            # Armaments: REAL upgrade of every (not-yet-upgraded) card in hand.
            from .cards import upgrade_card
            for i, c in enumerate(self.hand):
                if not c.id.endswith("+"):
                    self.hand[i] = upgrade_card(c)
            return
        if eff.op is EffectOp.AUTO_PLAY_FROM_DRAW:
            # Havoc: play the top of draw pile, then exhaust it.
            if self.draw_pile:
                c = self.draw_pile.pop()
                # Resolve its effects against the current target context.
                self._resolve_effects(c)
                self._exhaust_card(c)
            return

    # Duration debuffs that decay by 1 at the END of the bearer's OWN turn.
    # In the real game (WeakPower/VulnerablePower/FrailPower .cs) these tick in
    # AfterTurnEnd when side == Enemy; STS turn structure means a debuff lasts
    # the faithful number of the bearer's own turns. We therefore decrement a
    # creature's duration debuffs at the end of that creature's own turn:
    #   - Player's Weak/Frail decay at end of the player's turn.
    #   - Monster's Weak/Vulnerable decay at end of that monster's turn.
    _DURATION_DEBUFFS: tuple[str, ...] = ("weak", "vulnerable", "frail")

    def end_player_turn(self) -> None:
        self.is_player_turn = False
        # Discard hand at end of player turn (STS convention).
        self.discard_pile.extend(self.hand)
        self.hand.clear()
        # Turn-end triggers: Metallicize (block), Combust (lose HP + AoE).
        # Fire before plating/decay so block stacks then plating adds on top.
        self._fire_power_hook(self.player, "on_turn_end", self, self.player)
        # End-of-owner-turn effects for the player: Plating block-gain, then
        # decay duration debuffs (Weak/Frail the player bears).
        self._end_of_turn_effects(self.player)
        self.monster_turn()
        if self.alive_monsters():
            self.start_player_turn()

    def monster_turn(self) -> list[dict]:
        events: list[dict] = []
        for m in self.alive_monsters():
            # Monster block resets per turn in MVP (matches STS UI).
            m.block = 0
            # Poison ticks at the START of the owner's (monster's) turn.
            apply_poison_tick(m)
            if not m.alive:
                continue
            # Turn-start triggers for the monster (so monster engine powers,
            # if ever used, fire consistently with the player).
            self._fire_power_hook(m, "on_turn_start", self, m)
            events.append(m.take_turn(self.rng, self.player))
            # Turn-end triggers for the monster (Metallicize-likes).
            self._fire_power_hook(m, "on_turn_end", self, m)
            # End-of-owner-turn effects for the monster: Plating block-gain,
            # then decay duration debuffs (Weak/Vulnerable the monster bears).
            self._end_of_turn_effects(m)
            if not self.player.alive:
                break
        # Re-target if the previously selected monster died this turn.
        alive = self.alive_monsters()
        if alive and self.target_index >= len(alive):
            self.target_index = 0
        return events

    @classmethod
    def _end_of_turn_effects(cls, creature) -> None:
        """Resolve a creature's own turn-end: grant Plating block, then decay
        its duration debuffs."""
        cls._apply_plating(creature)
        cls._tick_powers(creature, ids=cls._DURATION_DEBUFFS)

    @staticmethod
    def _apply_plating(creature) -> None:
        """Plating (PlatingPower.cs BeforeTurnEndEarly): at the owner's turn
        end, gain Block == amount, then decrement the counter (by the attacker
        count == 1 in single-player)."""
        plating = creature.get_power("plating") if hasattr(creature, "get_power") else None
        if plating is None or plating.amount <= 0:
            return
        creature.block += plating.amount
        plating.amount -= 1
        if plating.amount <= 0:
            creature.powers.remove(plating)

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

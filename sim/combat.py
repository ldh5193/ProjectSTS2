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
    # Back-reference to the owning RunState — set by run_engine._start_combat
    # so per-attack relic hooks (Kunai/Shuriken/Pen Nib) can read rs.relics.
    # None in standalone combat tests (hooks are then skipped harmlessly).
    run_state: object = None
    # Per-step counter of POWER-type cards played. Incremented in play_card;
    # read+reset by RunEnv._reward each env step for the power_card_played
    # reward (scaling-engine signal). Lives here because play_card is the
    # single choke point that sees a card's type. Zero in standalone tests.
    powers_played_this_step: int = 0

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
        # NoDraw (Battle Trance): the player cannot draw for the rest of the turn.
        if self.player.get_power("no_draw") is not None:
            return
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
        self._attacks_played_this_turn = 0
        self._hp_lost_this_turn = False
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
        cost 0). Takes the minimum override across powers, floored at 0.

        X-cost cards (cost == X_COST) consume ALL remaining energy, so their
        effective cost is the player's current energy."""
        from .dsl import X_COST
        if card.cost == X_COST:
            return self.player.energy
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
        # Unplayable cards: status cards (Wound/Burn/FranticEscape, cost < 0
        # and not an X-cost card) can never be played. X_COST == -1 is the only
        # legal negative cost.
        from .dsl import X_COST
        if card.cost < 0 and card.cost != X_COST:
            return False
        return self.player.energy >= self.effective_cost(card)

    # Energy spent on the X-cost card currently resolving (Whirlwind hit count,
    # Cascade auto-plays). 0 when no X-cost card is mid-resolution.
    _x_value: int = field(default=0, init=False)
    # Per-turn counters for damage scaling (reset at start_player_turn):
    #   _attacks_played_this_turn -> Conflagration scaling.
    #   _hp_lost_this_turn -> Spite/TearAsunder "if HP lost this turn" triggers.
    _attacks_played_this_turn: int = field(default=0, init=False)
    _hp_lost_this_turn: bool = field(default=False, init=False)

    def play_card(self, card_index: int, target_is_monster: bool = True) -> None:
        if not self.can_play(card_index):
            raise ValueError(f"cannot play card at index {card_index}")
        from .dsl import CardType, X_COST
        card = self.hand.pop(card_index)
        spent = self.effective_cost(card)
        self.player.energy -= spent
        # X-cost cards repeat their effect once per energy spent.
        self._x_value = spent if card.cost == X_COST else 0
        self._resolve_effects(card)
        self._x_value = 0
        # Per-attack relic hooks (Kunai/Shuriken/Pen Nib) fire after an
        # ATTACK card resolves. Only when a RunState is attached (real runs;
        # standalone combat tests leave run_state=None).
        if card.type is CardType.ATTACK and self.run_state is not None:
            from .relics import trigger_on_attack_played
            trigger_on_attack_played(self.run_state, self, card)
        # Exhaust keyword: card leaves play to the exhaust pile. Also Corruption:
        # skills are exhausted on play instead of discarded.
        if card.exhaust or (
                card.type is CardType.SKILL
                and any(p.id == "corruption" for p in self.player.powers)):
            self._exhaust_card(card)
        else:
            self.discard_pile.append(card)
        if card.type is CardType.ATTACK:
            self._attacks_played_this_turn += 1
        if card.type is CardType.POWER:
            self.powers_played_this_step += 1

    def _resolve_effects(self, card: CardDef) -> None:
        for eff in card.effects:
            self._resolve_single_effect(card, eff)

    def _resolve_damage_scaling(self, eff, targets) -> tuple[int, int]:
        """Compute (base_damage, hit_count) for a DEAL_DAMAGE-shaped effect,
        applying any ScalingKind overrides and the X-cost hit multiplier."""
        base_amount = eff.amount
        hit_count = eff.hit_count
        # X-cost attacks (Whirlwind) multi-hit == energy spent.
        if self._x_value:
            hit_count = self._x_value
        target0 = targets[0] if targets else None
        for sc in eff.scaling:
            k = sc.kind.value
            if k == "block_amount":
                base_amount = self.player.block
            elif k == "strike_tag_count":
                strikes = sum(
                    1 for c in self.draw_pile + self.discard_pile + self.hand
                    if "strike" in c.id)
                base_amount += sc.amount * strikes
            elif k == "strength_multiplier":
                st = self.player.get_power("strength")
                if st is not None:
                    # +mult × Strength extra (the additive Strength applies once
                    # via the normal pipeline; here we add the EXTRA copies).
                    base_amount += st.amount * sc.amount
            elif k == "exhaust_pile_count":
                base_amount += sc.amount * len(self.exhaust_pile)
            elif k == "target_vulnerable_count":
                if target0 is not None:
                    v = target0.get_power("vulnerable")
                    base_amount += sc.amount * (v.amount if v else 0)
            elif k == "attacks_played_count":
                base_amount += sc.amount * self._attacks_played_this_turn
            elif k == "hp_lost_hits":
                if self._hp_lost_this_turn:
                    hit_count += 1
        return base_amount, max(0, hit_count)

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
            base_amount, hit_count = self._resolve_damage_scaling(eff, targets)
            for _ in range(max(0, hit_count)):
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
                amt = eff.amount
                # MoltenFist: add Vulnerable equal to the target's CURRENT stacks
                # (doubling it). Scaling reads the target's existing power.
                for sc in eff.scaling:
                    if sc.kind.value == "target_vulnerable_count":
                        v = t.get_power("vulnerable")
                        amt += sc.amount * (v.amount if v else 0)
                if amt != 0:
                    t.add_or_stack_power(make_power(eff.power_id, amt, t))
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
            # Havoc/Cascade: play the top of draw pile, then exhaust it. Cascade
            # is X-cost, so it repeats once per energy spent (self._x_value).
            repeat = self._x_value if self._x_value else 1
            for _ in range(max(1, repeat)):
                if not self.draw_pile:
                    break
                c = self.draw_pile.pop()
                self._resolve_effects(c)
                self._exhaust_card(c)
            return
        if eff.op is EffectOp.HEAL:
            self.player.heal(eff.amount)
            return
        if eff.op is EffectOp.GAIN_MAX_HP_ON_KILL:
            # Feed: deal damage to the selected enemy; if it kills, gain max HP.
            base_amount, _ = self._resolve_damage_scaling(eff, targets)
            for t in targets:
                if t.alive:
                    was_alive = t.alive
                    deal_damage(base_amount, self.player, t)
                    if was_alive and not t.alive:
                        self.player.gain_max_hp(eff.amount)
            return
        if eff.op is EffectOp.LIFESTEAL_AOE:
            # Reaper: AoE attack; heal the player by total UNBLOCKED damage dealt.
            base_amount, _ = self._resolve_damage_scaling(eff, targets)
            total_unblocked = 0
            for t in list(self.alive_monsters()):
                if t.alive:
                    _, hp_loss = deal_damage(base_amount, self.player, t)
                    total_unblocked += hp_loss
            self.player.heal(total_unblocked)
            return
        if eff.op is EffectOp.DOUBLE_STRENGTH:
            # Limit Break: double the player's current Strength.
            st = self.player.get_power("strength")
            if st is not None and st.amount != 0:
                self.player.add_or_stack_power(
                    make_power("strength", st.amount, self.player))
            return
        if eff.op is EffectOp.EXHAUST_HAND_SCALED:
            # Fiend Fire: exhaust the whole hand, then deal `amount` damage to
            # the selected enemy once per card exhausted.
            cards = list(self.hand)
            self.hand.clear()
            n = len(cards)
            for c in cards:
                self._exhaust_card(c)
            for t in targets:
                for _ in range(n):
                    if t.alive:
                        deal_damage(eff.amount, self.player, t)
            return
        if eff.op is EffectOp.EXHAUST_NONATTACKS_BLOCK:
            # Second Wind: exhaust all non-attack cards in hand; gain `amount`
            # block per card exhausted.
            from .dsl import CardType
            non_attacks = [c for c in self.hand if c.type is not CardType.ATTACK]
            for c in non_attacks:
                self.hand.remove(c)
                self._exhaust_card(c)
                gain_block(self.player, eff.amount)
            return
        if eff.op is EffectOp.EXHAUST_HAND_GENERATE:
            # Stoke: exhaust the whole hand, add `card_id` (per exhausted) to hand.
            cards = list(self.hand)
            self.hand.clear()
            n = len(cards)
            for c in cards:
                self._exhaust_card(c)
            from .card_catalog import CARDS
            gen = CARDS.get(eff.card_id) if eff.card_id else None
            for _ in range(n):
                if gen is not None:
                    self.hand.append(gen)
            return
        if eff.op is EffectOp.ADD_CARD:
            from .card_catalog import CARDS
            gen = CARDS.get(eff.card_id) if eff.card_id else None
            if gen is not None:
                pile = (self.hand if eff.pile == "hand"
                        else self.discard_pile if eff.pile == "discard"
                        else self.draw_pile)
                for _ in range(max(1, eff.amount)):
                    pile.append(gen)
            return
        if eff.op is EffectOp.ADD_RANDOM_ATTACK:
            # Infernal Blade: add a random Attack card (free this turn) to hand.
            from .card_catalog import CARDS, RARITY_OF, CardRarity
            from .dsl import CardType
            from dataclasses import replace as _replace
            attack_ids = [cid for cid, r in RARITY_OF.items()
                          if CARDS[cid].type is CardType.ATTACK
                          and r is not CardRarity.ANCIENT]
            if attack_ids:
                cid = self.rng.choice(attack_ids)
                # Free this turn -> cost 0 copy.
                self.hand.append(_replace(CARDS[cid], cost=0))
            return
        if eff.op is EffectOp.MOVE_DISCARD_TO_DRAW_TOP:
            # Headbutt: move a card from discard to the top of the draw pile.
            # Heuristic (no UI selection in sim): pick the highest-cost card.
            if self.discard_pile:
                idx = max(range(len(self.discard_pile)),
                          key=lambda i: self.discard_pile[i].cost
                          if self.discard_pile[i].cost is not None
                          and self.discard_pile[i].cost >= 0 else 0)
                self.draw_pile.append(self.discard_pile.pop(idx))
            return
        if eff.op is EffectOp.DRAW_UNTIL_NONATTACK:
            # Pillage: draw cards while the drawn card is an Attack (cap 10 hand).
            from .dsl import CardType
            while len(self.hand) < 10:
                before = len(self.hand)
                self.draw(1)
                if len(self.hand) == before:
                    break  # no card drawn (empty piles or NoDraw)
                if self.hand[-1].type is not CardType.ATTACK:
                    break
            return
        if eff.op is EffectOp.NO_DRAW:
            self.player.add_or_stack_power(make_power("no_draw", 1, self.player))
            return

    # Duration debuffs that decay by 1 at the END of the bearer's OWN turn.
    # In the real game (WeakPower/VulnerablePower/FrailPower .cs) these tick in
    # AfterTurnEnd when side == Enemy; STS turn structure means a debuff lasts
    # the faithful number of the bearer's own turns. We therefore decrement a
    # creature's duration debuffs at the end of that creature's own turn:
    #   - Player's Weak/Frail decay at end of the player's turn.
    #   - Monster's Weak/Vulnerable decay at end of that monster's turn.
    _DURATION_DEBUFFS: tuple[str, ...] = ("weak", "vulnerable", "frail", "no_draw")

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
            hp_before = self.player.hp
            events.append(m.take_turn(self.rng, self.player))
            if self.player.hp < hp_before:
                self._hp_lost_this_turn = True
            # Drain any status cards the monster queued this turn (Insatiable
            # FranticEscape, Vantom/MechaKnight/TestSubject Burn/Wound, ...)
            # into the player's piles. See monsters._queue_status.
            self._drain_status_cards(m)
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

    def _drain_status_cards(self, monster) -> None:
        """Insert status cards a monster queued during its turn into the
        player's piles. The monster accumulates (CardDef, pile) tuples on its
        `pending_status_cards` attribute (monsters._queue_status). Piles:
        "draw" / "discard" / "hand". Cards are inserted at random positions in
        draw to mirror the real shuffle-in behavior."""
        pending = getattr(monster, "pending_status_cards", None)
        if not pending:
            return
        for card, pile in pending:
            if pile == "hand":
                self.hand.append(card)
            elif pile == "discard":
                self.discard_pile.append(card)
            else:  # "draw" — shuffle into a random position
                if self.draw_pile:
                    idx = self.rng.randint(0, len(self.draw_pile))
                    self.draw_pile.insert(idx, card)
                else:
                    self.draw_pile.append(card)
        pending.clear()

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

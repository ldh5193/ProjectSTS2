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
    # Per-combat energy-cost overrides keyed by id(CardDef). SneckoEye /
    # FakeSneckoEye (ConfusedPower) populate this on draw: each drawn card with
    # a non-negative canonical cost gets a random cost 0-3 that holds for the
    # rest of combat (decompiled ConfusedPower.AfterCardDrawn:
    # card.EnergyCost.SetThisCombat(Rng.CombatEnergyCosts.NextInt(4))). Cleared
    # at combat start. CardDef is frozen, so we key the override by identity.
    cost_overrides: dict = field(default_factory=dict)
    # Chemical X (ChemicalX.cs Increase(2)): X-cost cards behave as if their X
    # is +2. Applied to _x_value when resolving an X-cost card. Set by the
    # relic's combat-start hook so standalone combat stays at 0.
    chemical_x_bonus: int = 0
    # Phase 9.2 Defect: the orb queue (None for non-Defect; capacity 0 means
    # channels are no-ops). Created/sized by run_engine._start_combat from the
    # RunState's orb_slots, or directly in tests. See sim/orbs.py.
    orb_queue: object = None  # sim.orbs.OrbQueue | None
    # Phase 9.3 Necrobinder: the persistent friendly minion (None when no Osty
    # is summoned). A Creature on the player's side with its own HP/block; it
    # never takes a turn (Osty.cs NOTHING_MOVE). Re-created per combat (does not
    # carry between combats). See sim/osty.py.
    osty: object = None  # sim.creatures.Creature | None

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
            cs._attach_combat_refs()
            return cs
        if monster_factory is None:
            monster_factory = SludgeSpinnerWeak.spawn
        monster = monster_factory(rng)
        cs = cls(player=player, monster=monster, monsters=[monster],
                 draw_pile=deck, rng=rng)
        cs._attach_combat_refs()
        return cs

    def _attach_combat_refs(self) -> None:
        """Give monsters that need a combat back-reference one (LivingShield's
        GetAllyCount). Harmless for monsters without the attribute."""
        for m in self.monsters:
            if hasattr(m, "_combat"):
                m._combat = self

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
                # PerfectFit.ModifyShuffleOrder (non-initial shuffle): any card
                # carrying the PerfectFit enchant is moved to the TOP of the draw
                # pile (popped first). The draw pile pops from the END, so "top"
                # is the last element. Stable across multiple PerfectFit cards.
                self._apply_perfect_fit_shuffle()
                # Reshuffle event: TheAbacus (+block), BiiigHug-style on_shuffle
                # relic hooks fire when the discard pile is reshuffled into draw.
                if self.run_state is not None:
                    from .relics import trigger_on_shuffle
                    trigger_on_shuffle(self.run_state, self)
            card = self.draw_pile.pop()
            # Card-affliction powers (Hex/Hunger/Tangled): a card entering combat
            # gets afflicted (AfterCardEnteredCombat). The power may return a
            # replacement card (with an affliction attached) to swap in.
            for p in list(self.player.powers):
                replacement = p.on_card_entered_combat(self, self.player, card)
                if replacement is not None:
                    card = replacement
            self.hand.append(card)
            # Track cards drawn this turn (Murder scales with CardDrawnEntry).
            self._cards_drawn_this_turn = getattr(self, "_cards_drawn_this_turn", 0) + 1
            # Confused (ConfusedPower from SneckoEye/FakeSneckoEye): each drawn
            # card with a non-negative canonical cost gets a random cost 0-3 for
            # the rest of combat (ConfusedPower.AfterCardDrawn). Fired before the
            # relic hook so the override is in place when read.
            self._fire_power_hook(self.player, "on_card_drawn", self, self.player, card)
            # Per-card-drawn relic hooks (e.g. Necronomicon-style). Fired after
            # the card lands in hand so the relic can read it.
            if self.run_state is not None:
                from .relics import trigger_on_card_drawn
                trigger_on_card_drawn(self.run_state, self, card)

    def _apply_perfect_fit_shuffle(self) -> None:
        """PerfectFit.ModifyShuffleOrder (non-initial shuffle): move every
        PerfectFit-enchanted card to the top of the draw pile so it is drawn
        first. The draw pile pops from the end, so the top is the tail."""
        pf = [c for c in self.draw_pile
              if getattr(getattr(c, "enchantment", None), "shuffle_to_top", None)
              and c.enchantment.shuffle_to_top()]
        if not pf:
            return
        rest = [c for c in self.draw_pile if c not in pf]
        # Drawn first == last to be popped: place PerfectFit cards at the tail.
        self.draw_pile = rest + pf

    # ---- turn lifecycle ----

    # ---- power-trigger fan-out helpers ----

    @staticmethod
    def _fire_power_hook(creature, hook: str, *args) -> None:
        """Call `hook(*args)` on every power the creature currently holds.
        Iterates a snapshot so a hook that mutates `powers` is safe."""
        for p in list(creature.powers):
            getattr(p, hook)(*args)

    def apply_player_affliction_power(self, power_id: str, amount: int):
        """Apply a card-affliction status power (Hex/Hunger/Dampen/Tangled) to
        the player and fire its AfterApplied (on_applied) hook so it mutates the
        player's cards immediately. Mirrors PowerCmd.Apply + AfterApplied for the
        monster-applied affliction powers. Returns the applied Power."""
        from .powers import make_power
        p = make_power(power_id, amount, self.player)
        self.player.add_or_stack_power(p)
        p.on_applied(self, self.player)
        return p

    def remove_player_affliction_power(self, power_id: str) -> None:
        """Remove a card-affliction power from the player and fire its
        AfterRemoved (on_removed) hook so the card mutations are reverted."""
        p = self.player.get_power(power_id)
        if p is None:
            return
        self.player.powers.remove(p)
        p.on_removed(self, self.player)

    # ---- Phase 9.2 Defect orb engine -------------------------------------

    def orb_focus(self) -> int:
        """Current Focus value (sum of FocusPower-like modifiers on the player).
        Computed via the modify_orb_value hook against a 0 baseline so any power
        that scales orb values (Focus / TemporaryFocus) is composed correctly."""
        v = 0
        for p in self.player.powers:
            v = p.modify_orb_value(self.player, v)
        return v

    def _orb_trigger_count(self, orb) -> int:
        """How many times `orb` fires its passive at a turn boundary
        (Hook.ModifyOrbPassiveTriggerCount). Player powers, then relics
        (GoldPlatedCables +1 for the front orb)."""
        count = 1
        for p in self.player.powers:
            count = p.modify_orb_passive_trigger_count(orb, count)
        if self.run_state is not None:
            from .relics import modify_orb_passive_trigger_count
            count = modify_orb_passive_trigger_count(self.run_state, self, orb, count)
        return max(0, count)

    def channel_orb(self, orb_type) -> None:
        """Channel one orb of `orb_type` (a name string or OrbType) into the
        queue. Overflow evokes the front orb first (OrbCmd.Channel). Fires the
        on_orb_channeled hook for player powers + relics (Metronome)."""
        from .orbs import OrbQueue, OrbType
        if self.orb_queue is None:
            return
        if isinstance(orb_type, str):
            orb_type = OrbType[orb_type.upper()]
        orb = self.orb_queue.channel(orb_type, self._evoke_orb)
        if orb is None:
            return
        self._fire_power_hook(self.player, "on_orb_channeled", self, self.player, orb)
        if self.run_state is not None:
            from .relics import trigger_on_orb_channeled
            trigger_on_orb_channeled(self.run_state, self, orb)

    def evoke_front_orb(self) -> None:
        """Evoke the front (oldest) orb (Dualcast/MultiCast). No-op if empty."""
        if self.orb_queue is None:
            return
        self.orb_queue.evoke_front(self._evoke_orb)

    def add_orb_slots(self, n: int) -> None:
        if self.orb_queue is not None:
            self.orb_queue.add_capacity(n)

    def _evoke_orb(self, orb) -> None:
        """Resolve an orb's Evoke (called by the queue on pop/overflow).
        Routes damage/block/energy through the combat pipeline, then fires
        on_orb_evoked (Thunder)."""
        from .orbs import OrbType
        focus = self.orb_focus()
        val = orb.evoke_value(focus)
        targets: list = []
        if orb.type is OrbType.LIGHTNING:
            alive = self.alive_monsters()
            if alive and val > 0:
                t = self.rng.choice(alive)
                deal_damage(val, self.player, t)
                targets = [t]
        elif orb.type is OrbType.FROST:
            gain_block(self.player, val)
            targets = [self.player]
        elif orb.type is OrbType.DARK:
            alive = self.alive_monsters()
            if alive and val > 0:
                t = min(alive, key=lambda m: m.hp)
                deal_damage(val, self.player, t)
                targets = [t]
        elif orb.type is OrbType.PLASMA:
            if self.player.get_power("no_energy_gain") is None:
                self.player.energy += val
            targets = [self.player]
        elif orb.type is OrbType.GLASS:
            if val > 0:
                targets = [m for m in self.alive_monsters() if m.alive]
                for t in list(targets):
                    if t.alive:
                        deal_damage(val, self.player, t)
        self._fire_power_hook(self.player, "on_orb_evoked",
                              self, self.player, orb, targets)

    def trigger_orb_passive(self, orb) -> None:
        """Resolve a single passive trigger for `orb` (OrbModel.Passive)."""
        from .orbs import OrbType
        focus = self.orb_focus()
        val = orb.passive_value(focus)
        if orb.type is OrbType.LIGHTNING:
            alive = self.alive_monsters()
            if alive and val > 0:
                deal_damage(val, self.player, self.rng.choice(alive))
        elif orb.type is OrbType.FROST:
            gain_block(self.player, val)
        elif orb.type is OrbType.DARK:
            # Accumulates into the evoke value (DarkOrb.Passive: _evokeVal += val).
            orb.dark_evoke += val
        elif orb.type is OrbType.PLASMA:
            if self.player.get_power("no_energy_gain") is None:
                self.player.energy += val
        elif orb.type is OrbType.GLASS:
            if val > 0:
                for m in list(self.alive_monsters()):
                    if m.alive:
                        deal_damage(val, self.player, m)
                orb.glass_passive = max(0, orb.glass_passive - 1)

    def _fire_orb_passives(self, when: str) -> None:
        """Fire orb passives at a turn boundary. `when` == 'turn_end'
        (BeforeTurnEnd: Lightning/Frost/Dark/Glass) or 'turn_start'
        (AfterTurnStart: Plasma). Each orb fires triggerCount times, left to
        right (oldest first)."""
        from .orbs import OrbType
        if self.orb_queue is None:
            return
        end_types = {OrbType.LIGHTNING, OrbType.FROST, OrbType.DARK, OrbType.GLASS}
        start_types = {OrbType.PLASMA}
        want = end_types if when == "turn_end" else start_types
        for orb in list(self.orb_queue.orbs):
            if orb.type not in want:
                continue
            for _ in range(self._orb_trigger_count(orb)):
                self.trigger_orb_passive(orb)

    def start_player_turn(self) -> None:
        self.turn_number += 1
        self.is_player_turn = True
        self._attacks_played_this_turn = 0
        # EmotionChip (Defect relic): remember whether HP was lost on the
        # turn that just ended before clearing the per-turn flag.
        self._hp_lost_last_turn = getattr(self, "_hp_lost_this_turn", False)
        self._hp_lost_this_turn = False
        self._block_gains_this_turn = 0
        self._cards_exhausted_this_turn = 0
        self._cards_discarded_this_turn = 0
        self._cards_drawn_this_turn = 0
        # Max-energy modifiers (Demesne +amount, WasteAway −amount). Applied to
        # the base per-turn energy (ModifyMaxEnergy), floored at 0.
        energy = self.player.max_energy
        for p in self.player.powers:
            energy = p.modify_max_energy(self.player, energy)
        self.player.energy = max(0, energy)
        # Block resets at turn start unless a power (Barricade) blocks the reset.
        # SturdyClamp caps retained block instead of clearing it (block_reset_cap).
        if not any(p.blocks_block_reset() for p in self.player.powers):
            caps = [c for c in (p.block_reset_cap() for p in self.player.powers)
                    if c is not None]
            if caps:
                self.player.block = min(self.player.block, min(caps))
            else:
                self.player.block = 0
        # Poison ticks at the START of the owner's turn (PoisonPower.cs).
        apply_poison_tick(self.player)
        # Osty block resets at the player's turn start (it shares the player's
        # turn; it has no turn of its own — Osty.cs NOTHING_MOVE). Keep the
        # player-side taunt back-ref current in case the queue was rebuilt.
        if self.osty is not None and self.osty.alive:
            self.osty.block = 0
            self.osty._combat = self
            self.player._osty_guardian = self.osty
        # Hand-draw modifiers (ModifyHandDraw): Demesne/Tyranny (+amount),
        # MindRot (−amount, floored at 0).
        hand_draw = HAND_SIZE
        for p in self.player.powers:
            hand_draw = p.modify_hand_draw(self.player, hand_draw)
        self.draw(max(0, hand_draw))
        # Turn-start triggers: DemonForm (Strength), Berserk (energy),
        # Brutality (lose HP + draw). Fire after the draw, per the .cs ordering
        # of AfterSideTurnStart (DemonForm) which runs once the turn is set up.
        self._fire_power_hook(self.player, "on_turn_start", self, self.player)
        # Orb passives that fire AfterTurnStart (PlasmaOrb: +energy). Fired here,
        # after the turn is set up and the on_turn_start hooks (Loop) have run.
        self._fire_orb_passives("turn_start")
        # Monster-side reactions to the player's turn starting (RampartPower:
        # the Living Shield re-armors its Turret Operator each player turn).
        for m in self.alive_monsters():
            self._fire_power_hook(m, "on_player_turn_start", self, m)

    def effective_cost(self, card: CardDef) -> int:
        """Card's energy cost after player power overrides (Corruption: skills
        cost 0). Takes the minimum override across powers, floored at 0.

        X-cost cards (cost == X_COST) consume ALL remaining energy, so their
        effective cost is the player's current energy."""
        from .dsl import X_COST
        if card.cost == X_COST:
            return self.player.energy
        # Confused (SneckoEye): a per-combat random cost override, set on draw.
        cost = self.cost_overrides.get(id(card), card.cost)
        for p in self.player.powers:
            override = p.modify_card_cost(card)
            if override is not None:
                cost = min(cost, override)
        # Entangled (TangledPower): Attack cards cost +Amount energy this turn.
        affl = getattr(card, "affliction", None)
        if affl is not None:
            cost += affl.energy_cost_delta()
        return max(0, cost)

    def _exhaust_card(self, card: CardDef) -> None:
        """Move a card to the exhaust pile and fire on_card_exhausted for the
        player's powers (Feel No Pain block, Dark Embrace draw)."""
        self.exhaust_pile.append(card)
        self._cards_exhausted_this_turn += 1
        self._fire_power_hook(self.player, "on_card_exhausted",
                              self, self.player, card)
        # Per-exhaust relic hook (JossPaper: every Nth card exhausted -> draw).
        if self.run_state is not None:
            from .relics import trigger_on_card_exhausted
            trigger_on_card_exhausted(self.run_state, self, card)

    def _discard_card_from_hand(self, card: CardDef) -> None:
        """Move a card from hand to the discard pile and fire on_card_discarded
        for the player's powers (Silent discard payoffs) and any discard-trigger
        relics (Tingsha damage / ToughBandages block, AfterCardDiscarded). Used
        by Survivor / Acrobatics / Prepared / DaggerThrow / CalculatedGamble."""
        self.discard_pile.append(card)
        self._cards_discarded_this_turn += 1
        self._fire_power_hook(self.player, "on_card_discarded",
                              self, self.player, card)
        if self.run_state is not None:
            from .relics import trigger_on_card_discarded
            trigger_on_card_discarded(self.run_state, self, card)

    def _discard_n_from_hand(self, n: int) -> None:
        """Discard up to `n` cards from hand. No selection UI in the sim, so we
        discard the LOWEST-value cards (keeps the strongest cards), mirroring a
        sensible player; the count + the discard hooks are what matter for
        fidelity (Silent's discard synergies care about the count, not which)."""
        from .dsl import X_COST

        def _val(c):
            cost = c.cost if (c.cost is not None and c.cost != X_COST) else 0
            return cost
        for _ in range(n):
            if not self.hand:
                return
            idx = min(range(len(self.hand)), key=lambda i: _val(self.hand[i]))
            self._discard_card_from_hand(self.hand.pop(idx))

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
    # Combat-history counters (Phase 8 Track A):
    #   _block_gains_this_turn  -> Unmovable (doubles first N card block-gains).
    #   _cards_exhausted_this_turn -> EvilEye / ForgottenRitual conditionals,
    #     and ShouldGlowGold-style "was a card exhausted this turn" checks.
    # Both reset at start_player_turn. _cards_exhausted_this_turn increments in
    # _exhaust_card; _block_gains_this_turn increments on player card block-gain.
    _block_gains_this_turn: int = field(default=0, init=False)
    _cards_exhausted_this_turn: int = field(default=0, init=False)
    # Silent (Phase 9.1): cards discarded / drawn this turn, for MementoMori
    # (dmg × discarded this turn) and Murder (dmg × drawn this turn). Reset at
    # start_player_turn.
    _cards_discarded_this_turn: int = field(default=0, init=False)
    _cards_drawn_this_turn: int = field(default=0, init=False)

    def play_card(self, card_index: int, target_is_monster: bool = True) -> None:
        if not self.can_play(card_index):
            raise ValueError(f"cannot play card at index {card_index}")
        from .dsl import CardType, X_COST
        card = self.hand.pop(card_index)
        spent = self.effective_cost(card)
        self.player.energy -= spent
        # X-cost cards repeat their effect once per energy spent. Chemical X
        # (ChemicalX.cs) makes X-cost cards behave as if X is +chemical_x_bonus.
        self._x_value = (spent + self.chemical_x_bonus) if card.cost == X_COST else 0
        # One-Two Punch: the next N Attacks play one extra time this turn.
        extra_plays = 0
        otp = self.player.get_power("one_two_punch")
        if (card.type is CardType.ATTACK and otp is not None and otp.amount > 0):
            extra_plays = 1
            otp.amount -= 1
            if otp.amount <= 0:
                self.player.powers.remove(otp)
        # Duplicator (DuplicationPower): the next card of ANY type plays one
        # extra time. Consumes one stack (AfterModifyingCardPlayCount).
        dup = self.player.get_power("duplication")
        if dup is not None and dup.amount > 0:
            extra_plays += 1
            dup.amount -= 1
            if dup.amount <= 0:
                self.player.powers.remove(dup)
        # Burst (BurstPower.cs): the next N Skills play one extra time this turn.
        # Consumes one stack per Skill (AfterModifyingCardPlayCount); removed at
        # turn end (handled in end_player_turn).
        burst = self.player.get_power("burst")
        if (card.type is CardType.SKILL and burst is not None and burst.amount > 0):
            extra_plays += 1
            burst.amount -= 1
            if burst.amount <= 0:
                self.player.powers.remove(burst)
        # Echo Form (EchoFormPower.cs): the FIRST card played each turn is
        # played `amount` extra times. Consume the per-turn flag.
        echo = self.player.get_power("echo_form")
        if echo is not None and not getattr(echo, "_used_this_turn", False):
            echo._used_this_turn = True
            extra_plays += echo.amount
        # Per-card enchant play-count (Glam: first play replays +Times this
        # combat). EnchantPlayCount(originalPlayCount) -> originalPlayCount+Times.
        ench = getattr(card, "enchantment", None)
        if ench is not None:
            extra_plays += ench.play_count(1) - 1
        alive_before = [m for m in self.monsters if m.alive]
        # Accuracy (AccuracyPower.cs): the active card is read by the power's
        # modify_damage_additive (Shiv-tagged attacks only). Latch it for the
        # duration of this card's resolution.
        acc = self.player.get_power("accuracy")
        if acc is not None:
            acc._active_card = card
        # Gigantification (GigantificationPower): the owner's next powered
        # Attack deals ×3 (applied via modify_damage_multiplicative). Snapshot
        # whether a stack was active so we consume exactly one after the Attack.
        gig = self.player.get_power("gigantification")
        gig_active = (card.type is CardType.ATTACK
                      and gig is not None and gig.amount > 0)
        for _ in range(1 + extra_plays):
            self._resolve_effects(card)
            # Enchantment.OnPlay runs after the card's own effects each play
            # (CardModel.OnPlayWrapper order: OnPlay -> Enchantment.OnPlay).
            if ench is not None:
                self._resolve_enchant_on_play(card, ench)
        self._x_value = 0
        # Consume one Gigantification stack after the powered Attack resolves
        # (GigantificationPower.AfterAttack -> PowerCmd.Decrement).
        if gig_active and gig is not None:
            gig.amount -= 1
            if gig.amount <= 0 and gig in self.player.powers:
                self.player.powers.remove(gig)
        # Detect monsters that died during this card's resolution.
        newly_dead = [m for m in alive_before if not m.alive]
        # Crab Rage (CrabRagePower.cs AfterDeath, ally died): each surviving
        # monster's powers react to an ally's death. Fire for every corpse.
        for dead in newly_dead:
            for m in self.monsters:
                if m is not dead and m.alive:
                    self._fire_power_hook(m, "on_monster_death", self, m, dead)
            # The corpse's OWN powers react to its death (InfestedPower:
            # PhrogParasite spawns Wrigglers). Then drain any monsters it
            # queued into the live combat list (mid-combat spawn).
            self._fire_power_hook(dead, "on_self_death", self, dead)
        self._drain_pending_spawns()
        # On-monster-death relic hooks (GremlinHorn: +1 energy & draw on each
        # enemy death).
        if self.run_state is not None and newly_dead:
            from .relics import trigger_on_monster_death
            for m in newly_dead:
                trigger_on_monster_death(self.run_state, self, m)
        # Juggling: count this card toward the player's attacks-this-turn and
        # clone it on the 3rd Attack (AfterCardPlayed).
        self._fire_power_hook(self.player, "on_card_played", self, self.player, card)
        # Per-card enchant AfterCardPlayed reactions (once, after all plays):
        #   Glam     — _usedThisCombat=True + status=Disabled (no more replays).
        #   Vigorous — status=Disabled (the +Amount damage was one-shot).
        #   Goopy    — Amount++ (its block grows each play).
        if ench is not None:
            from .enchantments import GLAM, VIGOROUS, GOOPY
            if ench.id == GLAM and not ench.used_this_combat:
                ench.used_this_combat = True
                ench.status = "disabled"
            elif ench.id == VIGOROUS:
                ench.status = "disabled"
            elif ench.id == GOOPY:
                ench.amount += 1
        # Enrage (EnragePower.cs AfterCardPlayed, Skill): monsters react to the
        # player playing a card (Strength on Skills).
        for m in self.alive_monsters():
            self._fire_power_hook(m, "on_player_card_played", self, m, card)
        # Per-attack relic hooks (Kunai/Shuriken/Pen Nib) fire after an
        # ATTACK card resolves. Only when a RunState is attached (real runs;
        # standalone combat tests leave run_state=None).
        if self.run_state is not None:
            from .relics import trigger_on_attack_played, trigger_on_card_played
            if card.type is CardType.ATTACK:
                trigger_on_attack_played(self.run_state, self, card)
            # General per-card relic hook (LetterOpener counts Skills,
            # Nunchaku/OrnamentalFan count Attacks via card type).
            trigger_on_card_played(self.run_state, self, card)
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

    def _resolve_enchant_on_play(self, card, ench) -> None:
        """Run an Enchantment.OnPlay (called once per play of the card).

        Faithful to each Enchantments/*.cs OnPlay:
          Swift  — once: draw Amount, then status=Disabled.
          Sown   — once: gain Amount energy, then status=Disabled.
          Adroit — every play: gain Amount block (with Dexterity etc).
          Corrupted — every play: 2 unblockable self-damage.
          Momentum  — every play: ExtraDamage += Amount (boosts later plays).
        """
        from .enchantments import (SWIFT, SOWN, ADROIT, CORRUPTED, MOMENTUM)
        from .damage import gain_block
        if ench.id == SWIFT:
            if ench.status == "normal":
                self.draw(ench.amount)
                ench.status = "disabled"
        elif ench.id == SOWN:
            if ench.status == "normal":
                if self.player.get_power("no_energy_gain") is None:
                    self.player.energy += ench.amount
                ench.status = "disabled"
        elif ench.id == ADROIT:
            gain_block(self.player, ench.amount)
        elif ench.id == CORRUPTED:
            # 2 unblockable, unpowered self-damage (CreatureCmd.Damage Move|
            # Unblockable|Unpowered). lose_hp is unblockable; unpowered == no
            # scaling powers.
            self.player.lose_hp(2)
        elif ench.id == MOMENTUM:
            ench.extra_damage += ench.amount

    def _resolve_damage_scaling(self, eff, targets, card=None) -> tuple[int, int]:
        """Compute (base_damage, hit_count) for a DEAL_DAMAGE-shaped effect,
        applying any ScalingKind overrides and the X-cost hit multiplier.

        `card` (the source CardDef) lets a per-card Enchantment add damage on a
        POWERED attack (Sharp/Momentum/Vigorous additive, Corrupted/Instinct
        multiplicative) — EnchantDamageAdditive / EnchantDamageMultiplicative."""
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
        # Per-card enchantment damage (powered card attack only). The additive
        # pass (Sharp +Amount, Momentum +ExtraDamage, Vigorous +Amount once) and
        # the multiplicative pass (Corrupted ×1.5, Instinct ×2) mirror the
        # EnchantDamage* hooks. MysticLighter relic +damage to any enchanted
        # card's powered attack is applied here too (per-card, relic-gated).
        ench = getattr(card, "enchantment", None) if card is not None else None
        if ench is not None:
            base_amount += ench.damage_additive()
            mult = ench.damage_multiplicative()
            if mult != 1.0:
                base_amount = int(base_amount * mult)
            # MysticLighter.cs: powered attacks from ENCHANTED cards deal +Damage.
            if self.run_state is not None:
                from .relics import mystic_lighter_bonus
                base_amount += mystic_lighter_bonus(self.run_state)
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
            base_amount, hit_count = self._resolve_damage_scaling(eff, targets, card)
            for _ in range(max(0, hit_count)):
                for t in targets:
                    if t.alive:
                        deal_damage(base_amount, self.player, t)
            return
        if eff.op is EffectOp.GAIN_BLOCK:
            # Per-card enchant block (Nimble +Amount, Goopy +Amount-1) adds to
            # the card's own block-gain (EnchantBlockAdditive, powered card block).
            ench_block = 0
            ench = getattr(card, "enchantment", None)
            if ench is not None:
                ench_block = ench.block_additive()
            for t in targets:
                before = t.block
                gain_block(t, eff.amount + (ench_block if t is self.player else 0))
                if t is self.player:
                    gained = t.block - before
                    # Unmovable counts each card block-gain attempt this turn.
                    self._block_gains_this_turn += 1
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
                # SneckoSkull (Silent relic): the player gives +1 Poison stack
                # when applying Poison to an enemy (ModifyPowerAmountGiven).
                if (eff.power_id == "poison" and t is not self.player and amt > 0
                        and self.run_state is not None):
                    from .relics import poison_amount_bonus
                    amt += poison_amount_bonus(self.run_state)
                if amt != 0:
                    p = make_power(eff.power_id, amt, t)
                    # Unmovable needs a CombatState back-reference for its
                    # per-turn block-gain count check.
                    p._cs = self
                    t.add_or_stack_power(p)
                    # Vicious: when the player applies Vulnerable to an enemy,
                    # the player draws cards (AfterPowerAmountChanged).
                    if (eff.power_id == "vulnerable" and t is not self.player
                            and amt > 0):
                        self._fire_power_hook(self.player, "on_vulnerable_applied",
                                              self, self.player)
                    # Outbreak: the player applied Poison to an enemy (counter).
                    if (eff.power_id == "poison" and t is not self.player
                            and amt > 0):
                        self._fire_power_hook(self.player, "on_poison_applied",
                                              self, self.player)
            return
        if eff.op is EffectOp.DRAW_CARD:
            self.draw(eff.amount)
            return
        if eff.op is EffectOp.ENERGY_GAIN:
            # NoEnergyGain (Expect a Fight's debuff) zeroes any energy gain.
            if self.player.get_power("no_energy_gain") is None:
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
            # is X-cost, so it repeats once per energy spent (self._x_value);
            # its upgrade adds eff.amount (+1) extra plays. Havoc is fixed at 1.
            if self._x_value:
                repeat = self._x_value + (eff.amount or 0)
            else:
                repeat = 1
            # Auto-played cards resolve as their own plays and must NOT inherit
            # Cascade's X-value (which would wrongly multi-hit their attacks).
            saved_x = self._x_value
            self._x_value = 0
            try:
                for _ in range(max(1, repeat)):
                    if not self.draw_pile:
                        break
                    c = self.draw_pile.pop()
                    self._resolve_effects(c)
                    self._exhaust_card(c)
            finally:
                self._x_value = saved_x
            return
        if eff.op is EffectOp.HEAL:
            self.player.heal(eff.amount)
            return
        if eff.op is EffectOp.GAIN_MAX_HP_ON_KILL:
            # Feed: deal damage to the selected enemy; if it kills, gain max HP.
            base_amount, _ = self._resolve_damage_scaling(eff, targets, card)
            for t in targets:
                if t.alive:
                    was_alive = t.alive
                    deal_damage(base_amount, self.player, t)
                    if was_alive and not t.alive:
                        self.player.gain_max_hp(eff.amount)
            return
        if eff.op is EffectOp.LIFESTEAL_AOE:
            # Reaper: AoE attack; heal the player by total UNBLOCKED damage dealt.
            base_amount, _ = self._resolve_damage_scaling(eff, targets, card)
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
        if eff.op is EffectOp.THRASH_EXHAUST_ATTACK:
            # Thrash: exhaust a random Attack card in hand, then deal its base
            # damage to the selected enemy (Thrash.cs). The card's damage is
            # added as one extra hit at this attack's target.
            from .dsl import CardType
            attacks = [c for c in self.hand if c.type is CardType.ATTACK]
            if attacks:
                chosen = self.rng.choice(attacks)
                self.hand.remove(chosen)
                bonus = max(
                    (e.amount for e in chosen.effects
                     if e.op is EffectOp.DEAL_DAMAGE), default=0)
                self._exhaust_card(chosen)
                for t in targets:
                    if t.alive and bonus > 0:
                        deal_damage(bonus, self.player, t)
            return
        if eff.op is EffectOp.TRANSFORM_ATTACKS_IN_HAND:
            # Primal Force: transform every Attack in hand into card_id (GiantRock).
            from .dsl import CardType
            from .card_catalog import CARDS
            gen = CARDS.get(eff.card_id) if eff.card_id else None
            if gen is not None:
                for i, c in enumerate(self.hand):
                    if c.type is CardType.ATTACK:
                        self.hand[i] = gen
            return
        if eff.op is EffectOp.EXHAUST_HAND_GENERATE_RANDOM:
            # Stoke: exhaust the whole hand, then add that many RANDOM Ironclad
            # cards (non-Ancient) to hand.
            from .card_catalog import CARDS, RARITY_OF, CardRarity
            cards = list(self.hand)
            self.hand.clear()
            n = len(cards)
            for c in cards:
                self._exhaust_card(c)
            pool = [cid for cid, r in RARITY_OF.items()
                    if r is not CardRarity.ANCIENT]
            for _ in range(n):
                if pool:
                    self.hand.append(CARDS[self.rng.choice(pool)])
            return
        if eff.op is EffectOp.GAIN_ENERGY_PER_HAND_ATTACK:
            # Expect a Fight: gain 1 energy per Attack card in hand, then apply
            # NoEnergyGain (no further energy gain this turn).
            from .dsl import CardType
            n = sum(1 for c in self.hand if c.type is CardType.ATTACK)
            if self.player.get_power("no_energy_gain") is None:
                self.player.energy += n
            self.player.add_or_stack_power(
                make_power("no_energy_gain", 1, self.player))
            return
        if eff.op is EffectOp.GAIN_BLOCK_IF_EXHAUSTED:
            # Evil Eye: gain `amount` block; doubled if a card was exhausted
            # this turn (WasCardExhaustedThisTurn).
            times = 2 if self._cards_exhausted_this_turn > 0 else 1
            for _ in range(times):
                before = self.player.block
                gain_block(self.player, eff.amount)
                self._block_gains_this_turn += 1
                gained = self.player.block - before
                if gained > 0:
                    self._fire_power_hook(self.player, "on_block_gained",
                                          self, self.player, gained)
            return
        if eff.op is EffectOp.GAIN_ENERGY_IF_EXHAUSTED:
            # Forgotten Ritual: gain `amount` energy iff a card was exhausted
            # this turn. (Itself exhausts via the Exhaust keyword.)
            if self._cards_exhausted_this_turn > 0:
                if self.player.get_power("no_energy_gain") is None:
                    self.player.energy += eff.amount
            return
        # ---- Phase 9.1 Silent effect ops --------------------------------
        if eff.op is EffectOp.DISCARD_CARDS:
            # Survivor / Prepared: discard `amount` cards from hand.
            self._discard_n_from_hand(max(1, eff.amount))
            return
        if eff.op is EffectOp.DRAW_THEN_DISCARD:
            # Acrobatics / DaggerThrow: draw `amount` (DRAW), then discard
            # `duration` cards. We encode draw count in `amount`, discard in
            # `hit_count` (reused field) so both numbers stay on one Effect.
            self.draw(eff.amount)
            self._discard_n_from_hand(max(1, eff.hit_count))
            return
        if eff.op is EffectOp.DISCARD_HAND_DRAW:
            # CalculatedGamble: discard the whole hand, then draw that many.
            n = len(self.hand)
            for c in list(self.hand):
                self.hand.remove(c)
                self._discard_card_from_hand(c)
            self.draw(n)
            return
        if eff.op is EffectOp.DAMAGE_PER_DISCARD_THIS_TURN:
            # MementoMori: base dmg + ExtraDamage(amount) × cards discarded this
            # turn, single target. eff.amount == base, eff.hit_count reused as
            # per-discard ExtraDamage.
            n = self._cards_discarded_this_turn
            dmg = eff.amount + eff.hit_count * n
            for t in targets:
                if t.alive and dmg > 0:
                    deal_damage(dmg, self.player, t)
            return
        if eff.op is EffectOp.DAMAGE_PER_CARD_DRAWN:
            # Murder: base dmg + ExtraDamage(amount) × cards drawn this turn.
            n = self._cards_drawn_this_turn
            dmg = eff.amount + eff.hit_count * n
            for t in targets:
                if t.alive and dmg > 0:
                    deal_damage(dmg, self.player, t)
            return
        if eff.op is EffectOp.DAMAGE_X_HITS:
            # Skewer: X-cost attack, hit count == energy spent on it.
            hits = self._x_value
            for _ in range(max(0, hits)):
                for t in targets:
                    if t.alive:
                        deal_damage(eff.amount, self.player, t)
            return
        if eff.op is EffectOp.DAMAGE_PER_ATTACK_IN_HAND:
            # Finisher: deal `amount` damage once per Attack played this turn.
            hits = self._attacks_played_this_turn
            base_amount, _ = self._resolve_damage_scaling(eff, targets, card)
            for _ in range(max(0, hits)):
                for t in targets:
                    if t.alive:
                        deal_damage(base_amount, self.player, t)
            return
        if eff.op is EffectOp.DAMAGE_AOE_ECHO_ON_KILL:
            # EchoingSlash: AoE `amount`; repeat the whole AoE once per enemy
            # killed by that wave (EchoingSlash.cs while-loop on WasTargetKilled).
            base_amount, _ = self._resolve_damage_scaling(eff, targets, card)
            waves = 1
            guard = 0
            while waves > 0 and guard < 20:
                guard += 1
                waves -= 1
                alive_now = [m for m in self.alive_monsters()]
                killed = 0
                for t in alive_now:
                    was = t.alive
                    deal_damage(base_amount, self.player, t)
                    if was and not t.alive:
                        killed += 1
                waves += killed
            return
        if eff.op is EffectOp.BLOCK_PER_ENEMY_POISON:
            # Mirage: gain block == total Poison stacks across all live enemies.
            total = 0
            for m in self.alive_monsters():
                pz = m.get_power("poison")
                if pz is not None and pz.amount > 0:
                    total += pz.amount
            if total > 0:
                gain_block(self.player, total)
            return
        # ---- Phase 9.2 Defect orb effect ops ----------------------------
        if eff.op is EffectOp.CHANNEL_ORB:
            # Channel `amount` orbs of type eff.power_id (e.g. "lightning").
            for _ in range(max(1, eff.amount)):
                self.channel_orb(eff.power_id)
            return
        if eff.op is EffectOp.EVOKE_ORB:
            # Dualcast/Quadcast: evoke the FRONT orb `amount` times. Dualcast (2)
            # evokes the same front orb twice (the .cs evokes without dequeue
            # first, then dequeues) — we model the net as `amount` evokes of the
            # front-most orb; if the queue empties, stop.
            for _ in range(max(1, eff.amount)):
                if self.orb_queue is None or self.orb_queue.is_empty():
                    break
                self.evoke_front_orb()
            return
        if eff.op is EffectOp.EVOKE_ALL_ORBS:
            # MultiCast: evoke every orb currently in the queue.
            if self.orb_queue is not None:
                while not self.orb_queue.is_empty():
                    self.evoke_front_orb()
            return
        if eff.op is EffectOp.ADD_ORB_SLOTS:
            self.add_orb_slots(max(0, eff.amount))
            return
        if eff.op is EffectOp.CHANNEL_ORB_PER_ENEMY:
            # Chill: channel a Frost orb per (alive) enemy.
            n = len(self.alive_monsters())
            for _ in range(n):
                self.channel_orb("frost")
            return
        if eff.op is EffectOp.CHANNEL_ORB_X:
            # Tempest: X-cost; channel `_x_value` Lightning orbs.
            for _ in range(max(0, self._x_value)):
                self.channel_orb("lightning")
            return
        if eff.op is EffectOp.DAMAGE_HITS_PER_ORB:
            # Barrage: hit count == number of orbs in the queue.
            hits = len(self.orb_queue.orbs) if self.orb_queue is not None else 0
            base_amount, _ = self._resolve_damage_scaling(eff, targets, card)
            for _ in range(max(0, hits)):
                for t in targets:
                    if t.alive:
                        deal_damage(base_amount, self.player, t)
            return
        if eff.op is EffectOp.GAIN_ENERGY_PER_CURRENT:
            # DoubleEnergy: gain energy equal to current energy (double it).
            if self.player.get_power("no_energy_gain") is None:
                self.player.energy += self.player.energy
            return
        # ---- Phase 9.3 Necrobinder / Osty effect ops --------------------
        if eff.op is EffectOp.SUMMON_OSTY:
            from .osty import summon_osty
            summon_osty(self, max(0, eff.amount))
            return
        if eff.op is EffectOp.HEAL_OSTY:
            from .osty import osty_alive
            if osty_alive(self) and self.osty is not None:
                self.osty.heal(max(0, eff.amount))
            return
        if eff.op is EffectOp.SACRIFICE_OSTY:
            # Sacrifice.cs: block == Osty.MaxHp*2, then kill Osty.
            from .osty import sacrifice_osty
            block = sacrifice_osty(self)
            if block > 0:
                gain_block(self.player, block)
            return
        if eff.op is EffectOp.OSTY_ATTACK:
            # Poke/Snap/SicEm/Flatten/etc.: deal `amount` from Osty iff alive.
            # The player's powers (Strength/Lethality) apply (FromOsty == the
            # player is the dealer for scaling). No-op while Osty is missing.
            from .osty import osty_attack_damage
            dmg = osty_attack_damage(self, eff.amount)
            if dmg > 0:
                base_amount, hit_count = self._resolve_damage_scaling(eff, targets, card)
                for _ in range(max(1, hit_count)):
                    for t in targets:
                        if t.alive:
                            deal_damage(base_amount, self.player, t)
            return
        if eff.op is EffectOp.OSTY_ATTACK_HP:
            # Unleash/Protector: deal Osty.CurrentHp (FromOsty) iff Osty alive.
            from .osty import osty_alive
            if osty_alive(self) and self.osty is not None:
                dmg = self.osty.hp
                if dmg > 0:
                    for t in targets:
                        if t.alive:
                            deal_damage(dmg, self.player, t)
            return
        if eff.op is EffectOp.SUMMON_NEXT_TURN:
            self.player.add_or_stack_power(
                make_power("summon_next_turn", max(0, eff.amount), self.player))
            return
        if eff.op is EffectOp.APPLY_DOOM:
            for t in targets:
                if t.alive:
                    t.add_or_stack_power(make_power("doom", eff.amount, t))
            return
        if eff.op is EffectOp.DOOM_KILL:
            # EndOfDays: apply Doom `amount`, then any enemy whose HP <= its Doom
            # is killed immediately (DoomPower.DoomKill).
            for t in targets:
                if t.alive:
                    t.add_or_stack_power(make_power("doom", eff.amount, t))
            for t in list(self.alive_monsters()):
                dp = t.get_power("doom")
                if dp is not None and t.hp <= dp.amount:
                    t.hp = 0
                    t.alive = False
            return

    # Duration debuffs that decay by 1 at the END of the bearer's OWN turn.
    # In the real game (WeakPower/VulnerablePower/FrailPower .cs) these tick in
    # AfterTurnEnd when side == Enemy; STS turn structure means a debuff lasts
    # the faithful number of the bearer's own turns. We therefore decrement a
    # creature's duration debuffs at the end of that creature's own turn:
    #   - Player's Weak/Frail decay at end of the player's turn.
    #   - Monster's Weak/Vulnerable decay at end of that monster's turn.
    _DURATION_DEBUFFS: tuple[str, ...] = ("weak", "vulnerable", "frail", "no_draw",
                                          "no_energy_gain", "blur", "double_damage",
                                          "reflect", "soar", "shrink",
                                          "covered", "no_block", "knockdown")

    def end_player_turn(self) -> None:
        self.is_player_turn = False
        # Relic turn-end hooks (Orichalcum: BeforeTurnEndVeryEarly block check;
        # Sai/Kusarigama). Fire BEFORE the player's turn-end power hooks so
        # Orichalcum sees the pre-Metallicize block value (block == 0 check).
        if self.run_state is not None:
            from .relics import trigger_on_player_turn_end
            trigger_on_player_turn_end(self.run_state, self)
        # Turn-end triggers (Metallicize block, Combust AoE, Stampede auto-play
        # of hand Attacks) fire BEFORE the hand is discarded so Stampede still
        # sees its Attacks (StampedePower.BeforeTurnEndEarly).
        self._fire_power_hook(self.player, "on_turn_end", self, self.player)
        # Orb passives that fire BeforeTurnEnd (Lightning dmg / Frost block /
        # Dark accumulate / Glass AoE). Fired after the turn-end power hooks.
        self._fire_orb_passives("turn_end")
        # One-Two Punch: any unused charge is removed at turn end.
        otp = self.player.get_power("one_two_punch")
        if otp is not None:
            self.player.powers.remove(otp)
        # Burst (BurstPower.cs AfterTurnEnd side==Owner): any unused charge is
        # removed at the player's own turn end.
        burst = self.player.get_power("burst")
        if burst is not None:
            self.player.powers.remove(burst)
        # Rage (RagePower.cs AfterTurnEnd side==Owner.Side): removed entirely at
        # the player's own turn end.
        rage = self.player.get_power("rage")
        if rage is not None:
            self.player.powers.remove(rage)
        # Tangled (TangledPower.cs AfterTurnEnd side==Owner): removed at the
        # player's own turn end, clearing the Entangled afflictions (+cost).
        if self.player.get_power("tangled") is not None:
            self.remove_player_affliction_power("tangled")
        # Retain (RetainHandPower from Stable Serum): keep up to `amount` cards
        # in hand at end of turn instead of discarding them; the counter
        # decrements by 1 each of the owner's turn ends (AfterTurnEnd). With no
        # selection UI in the sim we retain the highest-cost cards (the cards a
        # player most wants to keep). Cards flagged ethereal/status are not
        # specially handled here (the sim has no ethereal hand cards yet).
        retain = self.player.get_power("retain_hand")
        # WellLaidPlans (WellLaidPlansPower.cs): retain up to `amount` cards at
        # end of turn (persistent, no decay). Reuse the retain machinery: if no
        # RetainHand power is present, synthesize an equivalent retain count from
        # WellLaidPlans so the highest-value cards are kept.
        wlp = self.player.get_power("well_laid_plans")
        retained: list = []
        if retain is None and wlp is not None and wlp.amount > 0 and self.hand:
            from .dsl import X_COST as _XC

            def _ck(c):
                return c.cost if (c.cost is not None and c.cost != _XC) else 0
            n_keep = min(wlp.amount, len(self.hand))
            kept = sorted(self.hand, key=_ck, reverse=True)[:n_keep]
            kept_ids = {id(c) for c in kept}
            retained = [c for c in self.hand if id(c) in kept_ids]
            self.hand = [c for c in self.hand if id(c) not in kept_ids]
        if retain is not None and retain.amount > 0 and self.hand:
            from .dsl import X_COST
            n_keep = min(2, len(self.hand))

            def _cost_key(c):
                return c.cost if (c.cost is not None and c.cost != X_COST) else 0
            kept = sorted(self.hand, key=_cost_key, reverse=True)[:n_keep]
            kept_ids = set()
            for c in kept:
                kept_ids.add(id(c))
            retained = [c for c in self.hand if id(c) in kept_ids]
            self.hand = [c for c in self.hand if id(c) not in kept_ids]
        # Ethereal (GhostSeed enchant keyword / Hexed affliction): a card with
        # the Ethereal keyword still in hand at end of turn is EXHAUSTED instead
        # of discarded (CardKeyword.Ethereal). Resolve this BEFORE the discard.
        from .enchantments import card_keywords, KW_ETHEREAL, KW_RETAIN
        ethereal = [c for c in self.hand if KW_ETHEREAL in card_keywords(c)]
        for c in ethereal:
            self.hand.remove(c)
            self._exhaust_card(c)
        # Per-card Retain (Steady / RoyallyApproved enchant keyword): the card
        # stays in hand at end of turn rather than being discarded. Collect them
        # alongside the RetainHandPower-retained cards.
        kw_retained = [c for c in self.hand if KW_RETAIN in card_keywords(c)]
        for c in kw_retained:
            self.hand.remove(c)
        # Discard hand at end of player turn (STS convention).
        self.discard_pile.extend(self.hand)
        self.hand.clear()
        # Re-seat retained cards into the hand for next turn, and tick the
        # retain counter down (it expires when it reaches 0).
        if kw_retained:
            self.hand.extend(kw_retained)
        if retained:
            self.hand.extend(retained)
        if retain is not None:
            retain.amount -= 1
            if retain.amount <= 0 and retain in self.player.powers:
                self.player.powers.remove(retain)
        # End-of-owner-turn effects for the player: Plating block-gain, then
        # decay duration debuffs (Weak/Frail the player bears).
        self._end_of_turn_effects(self.player)
        self.monster_turn()
        # Flame Barrier (FlameBarrierPower.cs): removed at the END of the enemy
        # turn (Owner.Side != side), i.e. after the monsters have attacked into
        # the player's retaliatory barrier this round.
        fb = self.player.get_power("flame_barrier")
        if fb is not None:
            self.player.powers.remove(fb)
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
                # Inferno: when the owner takes unblocked damage, retaliate
                # against all enemies (InfernoPower.AfterDamageReceived).
                self._fire_power_hook(self.player, "on_owner_hp_lost",
                                      self, self.player)
            # Drain any status cards the monster queued this turn (Insatiable
            # FranticEscape, Vantom/MechaKnight/TestSubject Burn/Wound, ...)
            # into the player's piles. See monsters._queue_status.
            self._drain_status_cards(m)
            # Drain any monsters this monster summoned during its turn (Fogmog
            # IllusionMove -> EyeWithTeeth) into the live combat list.
            self._drain_pending_spawns()
            # Turn-end triggers for the monster (Metallicize-likes).
            self._fire_power_hook(m, "on_turn_end", self, m)
            # End-of-owner-turn effects for the monster: Plating block-gain,
            # then decay duration debuffs (Weak/Vulnerable the monster bears).
            self._end_of_turn_effects(m)
            if not self.player.alive:
                # Death-prevention relics (LizardTail): once per run, when the
                # player would die, instead heal a fraction of max HP and
                # survive. Fired here (the dominant death vector is a monster
                # attack) before the loop breaks so a revive aborts the loss.
                if self.run_state is not None:
                    from .relics import trigger_on_player_would_die
                    trigger_on_player_would_die(self.run_state, self)
                if not self.player.alive:
                    break
        # Re-target if the previously selected monster died this turn.
        alive = self.alive_monsters()
        if alive and self.target_index >= len(alive):
            self.target_index = 0
        return events

    def _drain_pending_spawns(self) -> None:
        """Append monsters any creature queued on its `pending_spawns` (Fogmog
        IllusionMove summons, PhrogParasite InfestedPower death spawns) into the
        live `self.monsters` list so they participate in combat. Mirrors the
        real game's CreatureCmd.Add. Idempotent — clears each source list."""
        for src in list(self.monsters):
            pending = getattr(src, "pending_spawns", None)
            if not pending:
                continue
            for newcomer in pending:
                if newcomer not in self.monsters:
                    self.monsters.append(newcomer)
            pending.clear()
        self._attach_combat_refs()

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

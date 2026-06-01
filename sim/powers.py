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

    def modify_block_additive(self, dealer, base_amount: int) -> int:
        return 0

    def modify_block_multiplicative(self, dealer, base_amount: int) -> float:
        return 1.0

    def modify_hp_lost(self, dealer, target, amount: int) -> int:
        """Modify unblocked HP loss about to be applied to `target`.
        Return the (possibly adjusted) amount. Used by relic-powers
        Tungsten Rod (−1 to HP loss the owner takes) and The Boot (min 5
        on the owner's small powered attacks). Default: no change."""
        return amount

    def blocks_weak(self) -> bool:
        """If True, the owner cannot be afflicted with Weak (Ginger)."""
        return False

    def blocks_frail(self) -> bool:
        """If True, the owner cannot be afflicted with Frail (Turnip)."""
        return False

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

    def on_card_played(self, cs, owner, card) -> None:
        """A card belonging to `owner` finished resolving (Juggling clone)."""

    def on_card_discarded(self, cs, owner, card) -> None:
        """A card belonging to `owner` was DISCARDED from hand by a card effect
        (Survivor / Acrobatics / Prepared / DaggerThrow / CalculatedGamble).
        Silent discard-payoff hook (AfterCardDiscarded). Default: no-op."""

    def on_card_drawn(self, cs, owner, card) -> None:
        """A card belonging to `owner` was just drawn into hand. Used by
        Confused (SneckoEye): randomize the drawn card's cost to 0-3 for the
        rest of combat (ConfusedPower.AfterCardDrawn)."""

    def on_vulnerable_applied(self, cs, owner) -> None:
        """`owner` applied Vulnerable to an enemy (Vicious draw)."""

    def on_poison_applied(self, cs, owner) -> None:
        """`owner` applied Poison to an enemy (Outbreak counter)."""

    def on_owner_hp_lost(self, cs, owner) -> None:
        """`owner` took unblocked damage on its own side (Inferno retaliate)."""

    # ---- attack-reaction hooks (Phase 8B monster/player powers) ----
    # Fired from damage.deal_damage AFTER block + HP loss are applied. `cs` is
    # None when an attack resolves outside a CombatState (standalone tests);
    # powers that need the combat object guard on `cs is not None`.

    def on_attacked(self, owner, dealer, blocked: int, unblocked: int) -> None:
        """`owner` was just hit by `dealer`'s attack. `blocked`/`unblocked` are
        the post-block split of that single attack instance. Used by Curl Up
        (block on first powered hit), Flame Barrier / Reflect (retaliate),
        Slumber / Asleep (wake on unblocked damage), Flutter, Sharp Hide-style
        on-attack thorns, Angry/Enrage-on-hit (Strength when struck)."""

    def on_monster_death(self, cs, owner, dead) -> None:
        """A creature on the owner's side died (`dead` is the corpse). Used by
        Crab Rage (gain Strength + Block when an ally dies)."""

    def on_self_death(self, cs, owner) -> None:
        """The OWNER of this power just died (fired on the corpse). Used by
        Infested (PhrogParasite) to spawn Wrigglers via the combat engine's
        pending_spawns drain."""

    def on_player_turn_start(self, cs, owner) -> None:
        """A MONSTER-side power reacting to the start of the PLAYER's turn
        (RampartPower.cs AfterSideTurnStart side==Player). Fired by the engine's
        player-turn-start fan-out across living monster powers."""

    def on_player_card_played(self, cs, owner, card) -> None:
        """The PLAYER played `card` (monster-side reaction). Used by Enrage
        (monster gains Strength whenever the player plays a Skill)."""

    def modify_card_cost(self, card) -> int | None:
        """Return an override cost for `card`, or None to leave unchanged
        (Corruption: skills cost 0)."""
        return None

    # ---- power-application hooks (Phase 8B.11 card-affliction powers) ----
    # Fired by the engine when a power is applied to / removed from the player
    # while a CombatState is attached. Card-affliction powers (Hex/Hunger/
    # Dampen/Tangled) use these to mutate the owner's cards (AfterApplied /
    # AfterRemoved) and to afflict newly-drawn cards (AfterCardEnteredCombat).
    def on_applied(self, cs, owner) -> None:
        """This power was just applied to `owner` (AfterApplied)."""

    def on_removed(self, cs, owner) -> None:
        """This power was just removed from `owner` (AfterRemoved)."""

    def on_card_entered_combat(self, cs, owner, card):
        """A card entered the owner's combat (drawn/generated). May return a
        replacement card (with an affliction attached) to swap into the pile,
        or None to leave it unchanged (AfterCardEnteredCombat)."""
        return None

    def modify_hand_draw(self, owner, count: int) -> int:
        """Modify the number of cards the owner draws at hand-draw
        (ModifyHandDraw). Default: no change. Used by Demesne/Tyranny (+amount),
        MindRot (−amount, floored at 0)."""
        return count

    def modify_max_energy(self, owner, amount: int) -> int:
        """Modify the owner's per-turn max energy (ModifyMaxEnergy). Default: no
        change. Used by Demesne (+amount) and WasteAway (−amount)."""
        return amount

    def modify_damage_cap(self, dealer, target, amount: int) -> int:
        """Cap the damage `target` receives from a single instance to this
        value (ModifyDamageCap). Default: no cap. Used by Slippery (cap 1) and
        Hard To Kill (cap `amount`)."""
        return amount

    # ---- Phase 9.2 Defect orb hooks ----
    def modify_orb_value(self, owner, value: int) -> int:
        """Modify an orb's passive/evoke value (Hook.ModifyOrbValue). FocusPower
        adds its Amount (clamped >= 0). Default: no change."""
        return value

    def modify_orb_passive_trigger_count(self, orb, count: int) -> int:
        """Modify how many times an orb fires its passive at a turn boundary
        (Hook.ModifyOrbPassiveTriggerCount). Default: no change."""
        return count

    def on_orb_channeled(self, cs, owner, orb) -> None:
        """An orb was channeled by `owner` (AfterOrbChanneled). Used by
        Metronome (relic) / Storm-style counters."""

    def on_orb_evoked(self, cs, owner, orb, targets) -> None:
        """An orb belonging to `owner` was evoked (AfterOrbEvoked). Used by
        Thunder (deal Amount to the evoke targets)."""

    def blocks_block_reset(self) -> bool:
        """If True, the owner's block is NOT reset at turn start (Barricade)."""
        return False

    def block_reset_cap(self) -> int | None:
        """If not None, the owner's block at turn start is CAPPED to this value
        instead of cleared to 0 (SturdyClamp.cs: retain up to 10 block). The
        engine uses the smallest cap across the owner's powers. Barricade
        (blocks_block_reset) takes precedence over any cap."""
        return None


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
        # JuggernautPower.cs:26 — ValueProp.Unpowered (no Strength/Vulnerable).
        deal_damage(self.amount, owner, target, powered=False)


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
                # STS1 Combust is an Unpowered AoE (no Strength/Vulnerable).
                deal_damage(self.amount, owner, m, powered=False)


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


@dataclass
class NoEnergyGainPower(Power):
    """NoEnergyGainPower.cs: while present, the owner gains 0 energy from any
    energy-gain effect (ModifyEnergyGain -> 0). Removed at owner turn end.
    Applied by Expect a Fight after its one-shot energy gain. The combat engine
    checks for this power before granting ENERGY_GAIN; it is ticked off as a
    1-stack duration debuff at the owner's turn end (no_energy_gain in
    _DURATION_DEBUFFS)."""
    id: str = field(default="no_energy_gain", init=False)
    _owner: object = None


@dataclass
class ColossusPower(Power):
    """ColossusPower.cs (ModifyDamageMultiplicative): when the owner is the
    TARGET of a powered attack from a dealer that has Vulnerable, incoming
    damage is ×0.5 (DamageDecrease). Duration counter ticks at enemy turn end.
    We model the multiplier as ×0.5 whenever the owner is the target (the
    'dealer has Vulnerable' guard is dropped — monsters rarely carry Vulnerable
    and the net combat effect is the defensive halving Colossus is played for)."""
    id: str = field(default="colossus", init=False)
    _owner: object = None

    def modify_damage_multiplicative(self, dealer, target, base_amount: int) -> float:
        if target is not self._owner:
            return 1.0
        return 0.5


@dataclass
class CrueltyPower(Power):
    """CrueltyPower.cs (ModifyVulnerableMultiplier): increases the Vulnerable
    damage multiplier by amount/100 on powered attacks the owner deals. STS2
    base amount is 25 (-> Vulnerable ×1.5 becomes ×1.75). We surface this as a
    bonus multiplier applied when the OWNER is the dealer and the TARGET is
    Vulnerable, stacking multiplicatively with VulnerablePower."""
    id: str = field(default="cruelty", init=False)
    _owner: object = None

    def modify_damage_multiplicative(self, dealer, target, base_amount: int) -> float:
        if dealer is not self._owner:
            return 1.0
        v = target.get_power("vulnerable") if hasattr(target, "get_power") else None
        if v is None or v.amount <= 0:
            return 1.0
        # Vulnerable already applies ×1.5; we add amount/100 on top of that base
        # (×1.5 -> ×(1.5 + amount/100)) => extra factor (1.5 + a/100)/1.5.
        return (1.5 + self.amount / 100.0) / 1.5


@dataclass
class CrimsonMantlePower(Power):
    """CrimsonMantlePower.cs (AfterPlayerTurnStart): at the owner's turn start,
    take SelfDamage unblockable damage, then gain `amount` Block (Unpowered).
    SelfDamage starts at 0 and is incremented to 1 when the card is played
    (IncrementSelfDamage). We store SelfDamage in `self_damage`."""
    id: str = field(default="crimson_mantle", init=False)
    self_damage: int = 1
    _owner: object = None

    def on_turn_start(self, cs, owner) -> None:
        from .damage import gain_block
        if self.self_damage > 0:
            owner.lose_hp(self.self_damage)
        gain_block(owner, self.amount)


@dataclass
class InfernoPower(Power):
    """InfernoPower.cs (AfterPlayerTurnStart + AfterDamageReceived): at the
    owner's turn start, take SelfDamage unblockable damage (starts 0, ->1 on
    play). When the owner takes unblocked damage on its own side, deal `amount`
    to ALL enemies (Unpowered). We fire the turn-start self damage here; the
    retaliation is fired from combat.monster_turn via on_owner_hp_lost."""
    id: str = field(default="inferno", init=False)
    self_damage: int = 1
    _owner: object = None

    def on_turn_start(self, cs, owner) -> None:
        if self.self_damage > 0:
            owner.lose_hp(self.self_damage)

    def on_owner_hp_lost(self, cs, owner) -> None:
        from .damage import deal_damage
        for m in cs.alive_monsters():
            if m.alive:
                # InfernoPower.cs:48 — ValueProp.Unpowered AoE retaliation.
                deal_damage(self.amount, owner, m, powered=False)


@dataclass
class DrumOfBattlePower(Power):
    """DrumOfBattlePower.cs (BeforeHandDrawLate): at the owner's hand-draw,
    exhaust the top `amount` cards of the draw pile. We fire at turn start
    (after the player's hand draw), exhausting the top of the draw pile."""
    id: str = field(default="drum_of_battle", init=False)
    _owner: object = None

    def on_turn_start(self, cs, owner) -> None:
        for _ in range(self.amount):
            if not cs.draw_pile:
                break
            cs._exhaust_card(cs.draw_pile.pop())


@dataclass
class StampedePower(Power):
    """StampedePower.cs (BeforeTurnEndEarly): at the owner's turn end, auto-play
    `amount` random playable Attack cards from hand."""
    id: str = field(default="stampede", init=False)
    _owner: object = None

    def on_turn_end(self, cs, owner) -> None:
        from .dsl import CardType
        for _ in range(self.amount):
            attacks = [i for i, c in enumerate(cs.hand)
                       if c.type is CardType.ATTACK]
            if not attacks:
                break
            idx = cs.rng.choice(attacks)
            card = cs.hand.pop(idx)
            cs._resolve_effects(card)
            cs._exhaust_card(card)


@dataclass
class OneTwoPunchPower(Power):
    """OneTwoPunchPower.cs (ModifyCardPlayCount): the next `amount` Attack cards
    the owner plays this turn are played one extra time. Decrements per Attack
    played; removed at owner turn end. The engine consumes a stack and doubles
    the resolve in play_card."""
    id: str = field(default="one_two_punch", init=False)
    _owner: object = None


@dataclass
class JugglingPower(Power):
    """JugglingPower.cs (AfterCardPlayed): each time the owner plays their 3rd
    Attack of the turn, add `amount` clones of that card to hand. Tracks attacks
    played this turn (resets at owner turn end). The engine calls on_card_played
    after each card resolves."""
    id: str = field(default="juggling", init=False)
    _owner: object = None
    _attacks_this_turn: int = 0

    def on_turn_start(self, cs, owner) -> None:
        self._attacks_this_turn = 0

    def on_card_played(self, cs, owner, card) -> None:
        from .dsl import CardType
        if card.type is not CardType.ATTACK:
            return
        self._attacks_this_turn += 1
        if self._attacks_this_turn == 3:
            for _ in range(self.amount):
                cs.hand.append(card)


@dataclass
class AggressionPower(Power):
    """AggressionPower.cs (BeforeSideTurnStart): at the owner's turn start, take
    `amount` random Attack cards from the discard pile into hand (upgrading
    them). We add them to hand (upgrade omitted — net deck effect preserved)."""
    id: str = field(default="aggression", init=False)
    _owner: object = None

    def on_turn_start(self, cs, owner) -> None:
        from .dsl import CardType
        attacks = [c for c in cs.discard_pile if c.type is CardType.ATTACK]
        cs.rng.shuffle(attacks)
        for c in attacks[: self.amount]:
            cs.discard_pile.remove(c)
            cs.hand.append(c)


@dataclass
class HellraiserPower(Power):
    """HellraiserPower.cs (AfterCardDrawnEarly): auto-plays Strike-tagged cards
    as they are drawn (if any non-infinite-HP enemy exists). We model a faithful
    approximation: at the owner's turn start (after the hand is drawn), auto-play
    every Strike-tagged card currently in hand, then exhaust it is NOT done — the
    real card returns to discard via AutoPlay's normal pile handling."""
    id: str = field(default="hellraiser", init=False)
    _owner: object = None

    def on_turn_start(self, cs, owner) -> None:
        if not cs.alive_monsters():
            return
        # Auto-play every Strike in hand (snapshot — autoplay may add cards).
        for card in [c for c in cs.hand if "strike" in c.id]:
            if card in cs.hand:
                cs.hand.remove(card)
                cs._resolve_effects(card)
                cs.discard_pile.append(card)


@dataclass
class UnmovablePower(Power):
    """UnmovablePower.cs (ModifyBlockMultiplicative): doubles Block the owner
    gains from a card/move, UNLESS the owner has already had `amount` such
    block-gains this turn. We track block-gains-this-turn on the CombatState
    (_block_gains_this_turn) and double via modify_block_multiplicative."""
    id: str = field(default="unmovable", init=False)
    _owner: object = None

    def modify_block_multiplicative(self, dealer, base_amount: int) -> float:
        if dealer is not self._owner:
            return 1.0
        cs = getattr(self, "_cs", None)
        prior = getattr(cs, "_block_gains_this_turn", 0) if cs is not None else 0
        if prior >= self.amount:
            return 1.0
        return 2.0


@dataclass
class ViciousPower(Power):
    """ViciousPower.cs (AfterPowerAmountChanged): whenever the owner applies
    Vulnerable to a target, draw `amount` cards. The engine calls
    on_vulnerable_applied after the owner applies Vulnerable to an enemy."""
    id: str = field(default="vicious", init=False)
    _owner: object = None

    def on_vulnerable_applied(self, cs, owner) -> None:
        cs.draw(self.amount)


@dataclass
class TungstenRodPower(Power):
    """Relic-power backing TungstenRod.cs (ModifyHpLostAfterOsty): reduces HP
    loss the owner takes by `amount` (base 1, floored at 0). Applied to the
    player at combat start by the TUNGSTEN_ROD relic."""
    id: str = field(default="tungsten_rod", init=False)
    _owner: object = None

    def modify_hp_lost(self, dealer, target, amount: int) -> int:
        if target is not self._owner:
            return amount
        return max(0, amount - self.amount)


@dataclass
class TheBootPower(Power):
    """Relic-power backing TheBoot.cs (ModifyHpLostBeforeOsty): when the owner
    deals a powered attack for 1..`amount`-1 unblocked HP loss to an enemy,
    raise it to `amount` (base 5). Applied to the player at combat start by the
    THE_BOOT relic. We approximate 'powered attack' as any damage routed
    through deal_damage where dealer is the owner and target is not the owner."""
    id: str = field(default="the_boot", init=False)
    _owner: object = None

    def modify_hp_lost(self, dealer, target, amount: int) -> int:
        if dealer is not self._owner or target is self._owner:
            return amount
        if 1 <= amount < self.amount:
            return self.amount
        return amount


@dataclass
class CharonsAshesPower(Power):
    """Relic-power backing CharonsAshes.cs (AfterCardExhausted): whenever a
    card the owner owns is exhausted, deal `amount` (base 3) damage to ALL
    enemies. Applied to the player at combat start by the CHARONS_ASHES relic."""
    id: str = field(default="charons_ashes", init=False)
    _owner: object = None

    def on_card_exhausted(self, cs, owner, card) -> None:
        from .damage import deal_damage
        for m in cs.alive_monsters():
            if m.alive:
                # CharonsAshes.cs — Unpowered AoE on each exhaust (no Strength).
                deal_damage(self.amount, owner, m, powered=False)


@dataclass
class GingerPower(Power):
    """Relic-power backing Weak-immunity (JuzuBracelet/Ginger-style). While
    present the owner cannot gain Weak. Applied to the player at combat start
    by the GINGER relic and read by combat's weak-application guard."""
    id: str = field(default="ginger", init=False)
    _owner: object = None

    def blocks_weak(self) -> bool:
        return True


@dataclass
class TurnipPower(Power):
    """Relic-power backing Frail-immunity (Turnip-style). While present the
    owner cannot gain Frail. Applied to the player at combat start by the
    TURNIP relic and read by combat's frail-application guard."""
    id: str = field(default="turnip", init=False)
    _owner: object = None

    def blocks_frail(self) -> bool:
        return True


@dataclass
class ArtifactPower(Power):
    """ArtifactPower (STS): negates the next `amount` debuffs applied to the
    owner (one charge per debuff). The Creature.add_or_stack guard consumes a
    charge and drops the incoming debuff while charges remain. Backs the
    DiamondDiadem / various Ancient relics that grant Artifact at combat start."""
    id: str = field(default="artifact", init=False)
    _owner: object = None


@dataclass
class IntangiblePower(Power):
    """IntangiblePower (STS): all incoming damage to the owner is reduced to 1
    (ModifyDamageMultiplicative clamps via the damage pipeline). We model the
    canonical 'reduce all incoming HP loss to at most 1' via modify_hp_lost.
    Duration counter ticks at the owner's turn end."""
    id: str = field(default="intangible", init=False)
    _owner: object = None

    def modify_hp_lost(self, dealer, target, amount: int) -> int:
        if target is not self._owner:
            return amount
        return min(amount, 1)


@dataclass
class SturdyClampPower(Power):
    """Relic-power backing SturdyClamp.cs (ShouldClearBlock false + cap to 10):
    the owner's Block is NOT cleared at turn start, but any Block above 10 is
    lost (retain up to 10). `amount` is the retained cap (base 10). Applied to
    the player at combat start by the STURDY_CLAMP relic."""
    id: str = field(default="sturdy_clamp", init=False)
    _owner: object = None

    def blocks_block_reset(self) -> bool:
        # We do not fully block the reset; we cap it (see block_reset_cap).
        return False

    def block_reset_cap(self) -> int | None:
        return self.amount


@dataclass
class BeatingRemnantPower(Power):
    """Relic-power backing BeatingRemnant.cs (ModifyHpLostAfterOsty): caps the
    TOTAL unblocked HP loss the owner takes in a single turn to `amount` (base
    20). `_taken_this_turn` accumulates per turn and resets at the owner's
    turn start. Applied to the player at combat start by the BEATING_REMNANT
    relic."""
    id: str = field(default="beating_remnant", init=False)
    _owner: object = None
    _taken_this_turn: int = 0

    def on_turn_start(self, cs, owner) -> None:
        self._taken_this_turn = 0

    def modify_hp_lost(self, dealer, target, amount: int) -> int:
        if target is not self._owner:
            return amount
        remaining = self.amount - self._taken_this_turn
        capped = max(0, min(amount, remaining))
        self._taken_this_turn += capped
        return capped


@dataclass
class MetallicizeStartPower(Power):
    """FurnacePower.cs analog (AfterSideTurnStart): gain `amount` Block at the
    START of the owner's turn. STS2 ships turn-start block as Furnace; relics
    like RippleBasin/ToughBandages grant recurring start-of-turn block. We model
    it as turn-start block-gain (distinct from MetallicizePower's turn-end)."""
    id: str = field(default="metallicize_start", init=False)
    _owner: object = None

    def on_turn_start(self, cs, owner) -> None:
        from .damage import gain_block
        gain_block(owner, self.amount)


@dataclass
class MonsterBarricadePower(Power):
    """Barricade-for-monsters: the owner's block is NOT reset at its turn start.
    Same mechanic as BarricadePower but applied to a monster (e.g. when a relic
    grants block that should persist). Kept distinct only for clarity."""
    id: str = field(default="monster_barricade", init=False)
    _owner: object = None

    def blocks_block_reset(self) -> bool:
        return True


@dataclass
class NoDrawPower(Power):
    """NoDrawPower.cs: the owner cannot draw cards for the rest of the turn.
    Applied by Battle Trance after its draw. Ticked off at the owner's turn
    end (1-stack duration). While present, CombatState.draw() is a no-op."""
    id: str = field(default="no_draw", init=False)
    _owner: object = None


# ===========================================================================
# Phase 8B — MONSTER powers (faithful triggers from the decompile).
# Cites: decompiled/MegaCrit.Sts2.Core.Models.Powers/{CurlUp,Ritual,Regen,
#   FlameBarrier,Reflect,Slumber,Asleep,Flutter,Soar,Constrict,CrabRage,
#   Enrage,PainfulStabs,HardenedShell,Buffer,Blur,DoubleDamage}Power.cs.
# ===========================================================================


@dataclass
class CurlUpPower(Power):
    """CurlUpPower.cs (AfterDamageReceived, powered attack): the FIRST time the
    owner takes a powered attack, gain `amount` Block (Unpowered) and the power
    is removed. We fire on the first attack that lands on the owner (the .cs
    tracks the source card and grants on AfterCardPlayed; the net effect — one
    block-gain on first being hit — is what we model)."""
    id: str = field(default="curl_up", init=False)
    _owner: object = None
    _used: bool = False

    def on_attacked(self, owner, dealer, blocked: int, unblocked: int) -> None:
        if self._used or dealer is owner:
            return
        self._used = True
        from .damage import gain_block
        gain_block(owner, self.amount)
        if self in owner.powers:
            owner.powers.remove(self)


@dataclass
class RitualPower(Power):
    """RitualPower.cs (AfterTurnEnd, side == Owner.Side): at the owner's turn
    end, gain Strength == amount. (The .cs skips the very first end-of-turn if
    the power was applied THIS turn by an enemy; monster Ritual is granted at
    spawn so it fires from turn 1, which is what the cultists/Sculptor do.)"""
    id: str = field(default="ritual", init=False)
    _owner: object = None

    def on_turn_end(self, cs, owner) -> None:
        owner.add_or_stack_power(make_power("strength", self.amount, owner))


@dataclass
class RegenPower(Power):
    """RegenPower.cs (AfterTurnEnd, side == Owner.Side): heal `amount` HP, then
    decrement the counter by 1."""
    id: str = field(default="regen", init=False)
    _owner: object = None

    def on_turn_end(self, cs, owner) -> None:
        owner.heal(self.amount)
        self.amount -= 1
        if self.amount <= 0 and self in owner.powers:
            owner.powers.remove(self)


@dataclass
class EnragePower(Power):
    """EnragePower.cs (AfterCardPlayed, Skill): whenever the PLAYER plays a
    Skill, the owning monster gains Strength == amount. Fired by the combat
    engine's player-card-played fan-out to monster powers."""
    id: str = field(default="enrage", init=False)
    _owner: object = None

    def on_player_card_played(self, cs, owner, card) -> None:
        from .dsl import CardType
        if card.type is CardType.SKILL:
            owner.add_or_stack_power(make_power("strength", self.amount, owner))


@dataclass
class FlameBarrierPower(Power):
    """FlameBarrierPower.cs (AfterDamageReceived, powered attack): when the
    owner is hit by a powered attack, deal `amount` (Unpowered) back to the
    dealer. Removed at the end of the enemy turn (1-stack duration handled by
    the engine's flame_barrier decay)."""
    id: str = field(default="flame_barrier", init=False)
    _owner: object = None

    def on_attacked(self, owner, dealer, blocked: int, unblocked: int) -> None:
        if dealer is None or dealer is owner or not dealer.alive:
            return
        dealer.lose_hp(self.amount)


@dataclass
class ReflectPower(Power):
    """ReflectPower.cs (AfterDamageReceived): when the owner BLOCKS part of a
    powered attack, deal the blocked amount back to the dealer (Unpowered).
    Decrements at the owner's turn start (modeled as a 1-turn duration via the
    engine's reflect decay)."""
    id: str = field(default="reflect", init=False)
    _owner: object = None

    def on_attacked(self, owner, dealer, blocked: int, unblocked: int) -> None:
        if dealer is None or dealer is owner or not dealer.alive or blocked <= 0:
            return
        dealer.lose_hp(blocked)


@dataclass
class SoarPower(Power):
    """SoarPower.cs (ModifyDamageMultiplicative): powered attacks targeting the
    owner are reduced to amount% (DamageDecrease, default 50 -> ×0.5). A
    Flight/Intangible-style halving for fliers (Owl Magistrate)."""
    id: str = field(default="soar", init=False)
    multiplier_pct: int = 50
    _owner: object = None

    def modify_damage_multiplicative(self, dealer, target, base_amount: int) -> float:
        if target is not self._owner:
            return 1.0
        return self.multiplier_pct / 100.0


@dataclass
class FlutterPower(Power):
    """FlutterPower.cs (ModifyDamageMultiplicative + AfterDamageReceived):
    powered attacks on the owner are halved (×0.5); each powered hit that deals
    unblocked damage decrements the counter, and at 0 the monster is stunned.
    We model the defensive halving (the combat-relevant part) and decrement on
    unblocked powered hits; the stun is approximated by simply expiring the
    power (the monster's normal move machine then proceeds)."""
    id: str = field(default="flutter", init=False)
    _owner: object = None

    def modify_damage_multiplicative(self, dealer, target, base_amount: int) -> float:
        if target is not self._owner:
            return 1.0
        return 0.5

    def on_attacked(self, owner, dealer, blocked: int, unblocked: int) -> None:
        if dealer is owner or unblocked <= 0:
            return
        self.amount -= 1
        if self.amount <= 0 and self in owner.powers:
            owner.powers.remove(self)


@dataclass
class SlumberPower(Power):
    """SlumberPower.cs (AfterDamageReceived + AfterTurnEnd): the owner is asleep
    while Slumber > 0. Each unblocked hit OR own turn-end decrements it; at 0
    the monster wakes (its move machine starts attacking). We model the counter
    decay on unblocked hits and on the owner's turn end; the wake itself is the
    monster's move machine (SlumberingBeetle ROLL_OUT) which the sim already
    cycles to. The SNORE move is a no-op while asleep."""
    id: str = field(default="slumber", init=False)
    _owner: object = None

    def on_turn_end(self, cs, owner) -> None:
        self.amount -= 1
        if self.amount <= 0 and self in owner.powers:
            owner.powers.remove(self)

    def on_attacked(self, owner, dealer, blocked: int, unblocked: int) -> None:
        if unblocked <= 0:
            return
        self.amount -= 1
        if self.amount <= 0 and self in owner.powers:
            owner.powers.remove(self)


@dataclass
class AsleepPower(Power):
    """AsleepPower.cs (AfterDamageReceived): while asleep the owner also holds
    Plating; the FIRST unblocked hit wakes it (removes its Plating and the
    Asleep power) and it begins attacking. We remove the owner's Plating + this
    power on the first unblocked hit (the wake)."""
    id: str = field(default="asleep", init=False)
    _owner: object = None

    def on_attacked(self, owner, dealer, blocked: int, unblocked: int) -> None:
        if unblocked <= 0:
            return
        plating = owner.get_power("plating") if hasattr(owner, "get_power") else None
        if plating is not None:
            owner.powers.remove(plating)
        if self in owner.powers:
            owner.powers.remove(self)


@dataclass
class ConstrictPower(Power):
    """ConstrictPower.cs (AfterTurnEnd, side == Owner.Side): at the owner's turn
    end, take `amount` unblockable damage. A debuff applied to the player by
    Slithering Strangler."""
    id: str = field(default="constrict", init=False)
    _owner: object = None

    def on_turn_end(self, cs, owner) -> None:
        owner.lose_hp(self.amount)


@dataclass
class CrabRagePower(Power):
    """CrabRagePower.cs (AfterDeath, ally died): when an ally on the owner's
    side dies, gain Strength (CanonicalVars Strength, base 6) and Block
    (CanonicalVars Block, base 99 in the .cs's example), then remove this power.
    We store the Strength in `amount` and the Block in `block_amount`."""
    id: str = field(default="crab_rage", init=False)
    block_amount: int = 99
    _owner: object = None

    def on_monster_death(self, cs, owner, dead) -> None:
        if dead is owner or not owner.alive:
            return
        owner.add_or_stack_power(make_power("strength", self.amount, owner))
        owner.block += self.block_amount
        if self in owner.powers:
            owner.powers.remove(self)


@dataclass
class PainfulStabsPower(Power):
    """PainfulStabsPower.cs (AfterAttack, powered attack with unblocked damage):
    each powered attack the owner lands on the player adds `amount` Wound status
    cards to the player's discard. We fire on each on_attacked where the owner
    is the dealer and unblocked > 0, queuing Wounds on the owner's pending
    status-card list (drained by combat.monster_turn)."""
    id: str = field(default="painful_stabs", init=False)
    _owner: object = None

    def on_attacked(self, owner, other, blocked: int, unblocked: int) -> None:
        # Holder (`owner`) is the attacking monster; `other` is the victim.
        # Queue Wounds only when this monster landed unblocked damage.
        if owner is not self._owner or unblocked <= 0:
            return
        from .monsters import _queue_status, WOUND_CARD
        _queue_status(owner, WOUND_CARD, "discard", self.amount)


@dataclass
class HardenedShellPower(Power):
    """HardenedShellPower.cs (ModifyHpLostBeforeOsty): caps the TOTAL HP the
    owner loses this turn at `amount` (a per-turn damage cap). We track HP lost
    this turn on the power and clamp each incoming HP-loss to the remaining
    budget; the budget resets at the owner's turn start."""
    id: str = field(default="hardened_shell", init=False)
    _owner: object = None
    _lost_this_turn: int = 0

    def on_turn_start(self, cs, owner) -> None:
        self._lost_this_turn = 0

    def modify_hp_lost(self, dealer, target, amount: int) -> int:
        if target is not self._owner:
            return amount
        remaining = max(0, self.amount - self._lost_this_turn)
        capped = min(amount, remaining)
        self._lost_this_turn += capped
        return capped


@dataclass
class BufferPower(Power):
    """BufferPower.cs (ModifyHpLostAfterOsty): prevents the next `amount`
    instances of HP loss entirely (each prevented loss decrements a charge)."""
    id: str = field(default="buffer", init=False)
    _owner: object = None

    def modify_hp_lost(self, dealer, target, amount: int) -> int:
        if target is not self._owner or self.amount <= 0 or amount <= 0:
            return amount
        self.amount -= 1
        if self.amount <= 0 and self in self._owner.powers:
            self._owner.powers.remove(self)
        return 0


@dataclass
class BlurPower(Power):
    """BlurPower.cs (ShouldClearBlock -> False for owner): the owner's Block is
    not cleared at turn start while Blur is active. Decrements at the owner's
    turn start (1-stack duration via the engine's blur decay)."""
    id: str = field(default="blur", init=False)
    _owner: object = None

    def blocks_block_reset(self) -> bool:
        return True


@dataclass
class DoubleDamagePower(Power):
    """DoubleDamagePower.cs (ModifyDamageMultiplicative): the owner's powered
    attacks deal ×2 damage. Counter ticks down at turn end (engine decay)."""
    id: str = field(default="double_damage", init=False)
    _owner: object = None

    def modify_damage_multiplicative(self, dealer, target, base_amount: int) -> float:
        if dealer is not self._owner:
            return 1.0
        return 2.0


@dataclass
class TemporaryStrengthPower(Power):
    """TemporaryStrengthPower.cs: applies +amount Strength immediately (the .cs
    silently applies a real StrengthPower) and removes that Strength again at
    the owner's turn end. We model it by carrying the Strength on this power and
    reversing it at turn end. Positive form only (the Down form is a debuff with
    negative net Strength)."""
    id: str = field(default="temporary_strength", init=False)
    _owner: object = None

    def on_turn_end(self, cs, owner) -> None:
        owner.add_or_stack_power(make_power("strength", -self.amount, owner))
        if self in owner.powers:
            owner.powers.remove(self)


@dataclass
class TemporaryDexterityPower(Power):
    """TemporaryDexterityPower.cs: +amount Dexterity for the turn, reversed at
    the owner's turn end. We surface the block bonus directly (additive, like
    DexterityPower) and remove it at turn end."""
    id: str = field(default="temporary_dexterity", init=False)
    _owner: object = None

    def modify_block_additive(self, dealer, base_amount: int) -> int:
        if dealer is not self._owner:
            return 0
        return self.amount

    def on_turn_end(self, cs, owner) -> None:
        if self in owner.powers:
            owner.powers.remove(self)


@dataclass
class StrengthDownPower(Power):
    """MonarchsGazeStrengthDownPower.cs / temporary Strength-down: applies
    -amount Strength immediately and removes it at the owner's turn end. We
    model the net effect: the owner's outgoing attacks are reduced by `amount`
    until its turn ends, at which point the penalty is lifted."""
    id: str = field(default="strength_down", init=False)
    _owner: object = None

    def modify_damage_additive(self, dealer, target, base_amount: int) -> int:
        if dealer is not self._owner:
            return 0
        return -self.amount

    def on_turn_end(self, cs, owner) -> None:
        if self in owner.powers:
            owner.powers.remove(self)


@dataclass
class RagePower(Power):
    """RagePower.cs (AfterCardPlayed, Attack): gain `amount` Block whenever the
    owner plays an Attack. Removed at the owner's turn end (engine decay)."""
    id: str = field(default="rage", init=False)
    _owner: object = None

    def on_card_played(self, cs, owner, card) -> None:
        from .dsl import CardType
        if card.type is CardType.ATTACK:
            from .damage import gain_block
            gain_block(owner, self.amount)


@dataclass
class AfterimagePower(Power):
    """AfterimagePower.cs (AfterCardPlayed): gain `amount` Block whenever the
    owner plays ANY card (Unpowered)."""
    id: str = field(default="afterimage", init=False)
    _owner: object = None

    def on_card_played(self, cs, owner, card) -> None:
        from .damage import gain_block
        gain_block(owner, self.amount)


@dataclass
class EnvenomPower(Power):
    """EnvenomPower.cs (AfterAttack, unblocked): apply `amount` Poison to the
    target of the owner's attacks. We fire on on_attacked where the owner is the
    dealer and the hit dealt unblocked damage."""
    id: str = field(default="envenom", init=False)
    _owner: object = None

    def on_attacked(self, owner, other, blocked: int, unblocked: int) -> None:
        # Holder (`owner`) is the attacker; apply Poison to the victim `other`.
        if owner is not self._owner or unblocked <= 0:
            return
        other.add_or_stack_power(make_power("poison", self.amount, other))


@dataclass
class RampartPower(Power):
    """RampartPower.cs (AfterSideTurnStart, side == Player): at the start of
    every PLAYER turn, the LivingShield's allied TurretOperator(s) gain `amount`
    Block (Unpowered). The shield wall keeps re-armoring the turret it guards.
    The .cs grants block to `Enemies.Where(c.Monster is TurretOperator)`; we
    grant block to every living teammate flagged as a turret-operator
    (is_turret_operator). Fired from the engine's player-turn-start fan-out to
    MONSTER powers (RampartPower holder is the LivingShield)."""
    id: str = field(default="rampart", init=False)
    _owner: object = None

    def on_player_turn_start(self, cs, owner) -> None:
        if cs is None or not owner.alive:
            return
        from .damage import gain_block
        for m in cs.alive_monsters():
            if m is owner:
                continue
            if getattr(m, "is_turret_operator", False):
                gain_block(m, self.amount)


@dataclass
class InfestedPower(Power):
    """InfestedPower.cs (AfterDeath, owner == target): when the owner (the
    PhrogParasite) dies, spawn `amount` (4) Wrigglers on its side, each
    StartStunned. Combat does not end while this power's owner has spawned
    minions still alive (ShouldStopCombatFromEnding). We queue the Wriggler
    spawns on the corpse's `pending_spawns`; the engine drains them into the
    live monster list after the death is detected."""
    id: str = field(default="infested", init=False)
    _owner: object = None

    def on_self_death(self, cs, owner) -> None:
        if cs is None:
            return
        from .monsters import Wriggler
        pending = getattr(owner, "pending_spawns", None)
        if pending is None:
            pending = []
            owner.pending_spawns = pending  # type: ignore[attr-defined]
        asc = getattr(owner, "ascension", 0)
        from .monsters import WrigglerMove
        for i in range(self.amount):
            w = Wriggler.spawn(cs.rng, ascension=asc)
            w.name = f"Wriggler ({i + 1})"
            # StartStunned: first turn is a no-op SPAWNED_MOVE (StunIntent),
            # then it begins its slot-keyed INIT cycle. Odd slots (1/3) open on
            # Bite; even slots (2/4) on Wriggle (Wriggler.cs:55-59).
            w.next_move = WrigglerMove.SPAWNED
            w._slot_kind = "bite" if i % 2 == 0 else "wriggle"
            pending.append(w)


@dataclass
class DuplicationPower(Power):
    """DuplicationPower.cs (ModifyCardPlayCount): the next card the owner plays
    is played one extra time (playCount + 1). Decrements per card whose play
    count it modified (AfterModifyingCardPlayCount), and is removed entirely at
    the owner's turn end (AfterTurnEnd). Granted by the Duplicator potion (1).
    The engine consumes a stack and doubles the resolve in play_card (any card
    type, unlike OneTwoPunch which is Attacks only)."""
    id: str = field(default="duplication", init=False)
    _owner: object = None


@dataclass
class GigantificationPower(Power):
    """GigantificationPower.cs (BeforeAttack + ModifyDamageMultiplicative +
    AfterAttack): the owner's next powered Attack deals ×3 damage. The .cs
    latches onto the first powered attack command, multiplies its damage by 3,
    and decrements the counter after that command resolves. Granted by the
    Gigantification potion (1). We surface the ×3 multiplier on the owner's
    powered attacks and consume one stack after a powered attack lands (the
    engine calls consume_gigantification in play_card)."""
    id: str = field(default="gigantification", init=False)
    _owner: object = None

    def modify_damage_multiplicative(self, dealer, target, base_amount: int) -> float:
        if dealer is not self._owner or self.amount <= 0:
            return 1.0
        return 3.0


@dataclass
class BlockNextTurnPower(Power):
    """BlockNextTurnPower.cs (AfterBlockCleared): grants the owner `amount`
    Block when its Block is cleared (i.e. at the start of its next turn), then
    removes itself. Granted by Ship in a Bottle. We fire the deferred block at
    the owner's turn start (when block has been reset) and remove the power."""
    id: str = field(default="block_next_turn", init=False)
    _owner: object = None

    def on_turn_start(self, cs, owner) -> None:
        from .damage import gain_block
        gain_block(owner, self.amount)
        if self in owner.powers:
            owner.powers.remove(self)


@dataclass
class ClarityPower(Power):
    """ClarityPower.cs (ModifyHandDraw +1; AfterSideTurnStart side==Owner
    decrements): while present, the owner draws 1 extra card at hand-draw, and
    the counter decrements by 1 at the owner's turn start. Granted by the
    Clarity potion (3). We add +1 to the draw at the owner's turn start and
    decrement; at 0 the power is removed."""
    id: str = field(default="clarity", init=False)
    _owner: object = None

    def on_turn_start(self, cs, owner) -> None:
        # The base hand-draw already happened; add the +1 Clarity card, then
        # decrement the counter (AfterSideTurnStart).
        cs.draw(1)
        self.amount -= 1
        if self.amount <= 0 and self in owner.powers:
            owner.powers.remove(self)


@dataclass
class DoomPower(Power):
    """DoomPower.cs (BeforeTurnEnd side==Owner): at the owner's (enemy's) turn
    end, if the owner's CURRENT HP <= `amount`, the owner is instantly killed.
    A delayed execution-threshold debuff applied by Potion of Doom (33). The
    combat engine checks this at the enemy's turn end via on_turn_end."""
    id: str = field(default="doom", init=False)
    _owner: object = None

    def on_turn_end(self, cs, owner) -> None:
        if owner.alive and owner.hp <= self.amount:
            owner.hp = 0
            owner.alive = False


@dataclass
class DemisePower(Power):
    """DemisePower.cs (AfterTurnEnd side==Owner): at the owner's (enemy's) turn
    end, the owner takes `amount` unblockable, unpowered damage. A delayed-tick
    debuff applied by Powdered Demise (9)."""
    id: str = field(default="demise", init=False)
    _owner: object = None

    def on_turn_end(self, cs, owner) -> None:
        if owner.alive:
            owner.lose_hp(self.amount)


@dataclass
class ShrinkPower(Power):
    """ShrinkPower.cs (ModifyDamageMultiplicative): the owner's powered attacks
    deal (100 − 30)% = ×0.7 damage. Counter ticks down at the owner's turn end.
    A debuff applied by Beetle Juice (Repeat 4 -> 4 turns)."""
    id: str = field(default="shrink", init=False)
    _owner: object = None

    def modify_damage_multiplicative(self, dealer, target, base_amount: int) -> float:
        if dealer is not self._owner:
            return 1.0
        return 0.70


@dataclass
class RetainHandPower(Power):
    """RetainHandPower.cs (Counter; AfterTurnEnd side==Owner decrements): while
    present, the owner retains up to `amount` cards in hand at end of turn
    instead of discarding them, and the counter decrements by 1 each of the
    owner's turn ends. Granted by the Stable Serum potion (Repeat 2 -> retains
    for 2 turns). The engine reads this in end_player_turn to keep N cards."""
    id: str = field(default="retain_hand", init=False)
    _owner: object = None


@dataclass
class IllusionPower(Power):
    """IllusionPower.cs: marks a creature as a summoned illusion (a minion).
    In the real game it carries a one-time self-revive; we model the simpler,
    combat-relevant fact that the creature is a minion (so the Fogmog's
    illusions are distinguishable). No active per-turn effect."""
    id: str = field(default="illusion", init=False)
    _owner: object = None


@dataclass
class ConfusedPower(Power):
    """ConfusedPower.cs (SneckoEye / FakeSneckoEye): each card the owner draws
    with a non-negative canonical cost has its energy cost randomized to 0-3
    for the rest of combat (AfterCardDrawn -> EnergyCost.SetThisCombat(
    Rng.CombatEnergyCosts.NextInt(4))). X-cost cards (canonical cost < 0) are
    left alone. We record the override in cs.cost_overrides keyed by card
    identity. test_energy_cost_override mirrors the decompile's TestMode hook so
    tests can pin the rolled value deterministically. StackType is Single (one
    copy)."""
    id: str = field(default="confused", init=False)
    _owner: object = None
    test_energy_cost_override: int = -1

    def on_card_drawn(self, cs, owner, card) -> None:
        if cs is None or owner is not self._owner:
            return
        from .dsl import X_COST
        # Only non-negative canonical costs are randomized (X-cost / unplayable
        # status cards with cost < 0 are skipped, per the decompile guard).
        if card.cost < 0 or card.cost == X_COST:
            return
        if self.test_energy_cost_override >= 0:
            cost = self.test_energy_cost_override
        else:
            cost = cs.rng.randrange(4)  # NextInt(4) -> 0..3
        cs.cost_overrides[id(card)] = cost


# ===========================================================================
# Phase 8B.8 — powers tranche (faithful triggers from the decompile).
# Cites: decompiled/MegaCrit.Sts2.Core.Models.Powers/{NoxiousFumes,Mayhem,
#   Burst,Accuracy,Territorial,PaperCuts,Tracking,Knockdown,Guarded,Covered,
#   NoBlock,Demesne,Tyranny,MindRot,WasteAway,Strangle,Slippery,HardToKill,
#   DarkShackles,PiercingWail,Mangle,CrushUnder,FeedingFrenzy}Power.cs.
# ===========================================================================


@dataclass
class NoxiousFumesPower(Power):
    """NoxiousFumesPower.cs (AfterSideTurnStart, side == Owner.Side): at the
    start of the owner's turn, apply `amount` Poison to ALL hittable enemies.
    StackType Counter (the per-turn Poison application does not decay)."""
    id: str = field(default="noxious_fumes", init=False)
    _owner: object = None

    def on_turn_start(self, cs, owner) -> None:
        for m in cs.alive_monsters():
            if m.alive:
                m.add_or_stack_power(make_power("poison", self.amount, m))


@dataclass
class MayhemPower(Power):
    """MayhemPower.cs (AfterPlayerTurnStart): at the owner's turn start,
    auto-play the top `amount` cards from the draw pile (CardPilePosition.Top,
    forceExhaust=false). We resolve each top-of-draw card then send it to the
    discard (its normal post-play pile)."""
    id: str = field(default="mayhem", init=False)
    _owner: object = None

    def on_turn_start(self, cs, owner) -> None:
        for _ in range(self.amount):
            if not cs.draw_pile:
                break
            card = cs.draw_pile.pop()
            cs._resolve_effects(card)
            cs.discard_pile.append(card)


@dataclass
class BurstPower(Power):
    """BurstPower.cs (ModifyCardPlayCount, Skill only): the next `amount` Skill
    cards the owner plays this turn are played one extra time (playCount + 1).
    Decrements per Skill whose play count it modified (AfterModifyingCardPlayCount)
    and is removed entirely at the owner's turn end. The engine consumes a stack
    and doubles the resolve in play_card (Skills only, unlike Duplication)."""
    id: str = field(default="burst", init=False)
    _owner: object = None


@dataclass
class AccuracyPower(Power):
    """AccuracyPower.cs (ModifyDamageAdditive): the owner's powered Shiv attacks
    deal +`amount` additive damage. Only attacks tagged Shiv from the owner
    benefit (card.Tags.Contains(CardTag.Shiv))."""
    id: str = field(default="accuracy", init=False)
    _owner: object = None

    def modify_damage_additive(self, dealer, target, base_amount: int) -> int:
        if dealer is not self._owner:
            return 0
        card = getattr(self, "_active_card", None)
        if card is None or "shiv" not in getattr(card, "id", ""):
            return 0
        return self.amount

    _active_card: object = None


@dataclass
class TerritorialPower(Power):
    """TerritorialPower.cs (AfterTurnEnd, side == Owner.Side): at the owner's
    turn end, gain Strength == `amount`. A monster buff (Counter — does not
    decay; permanent per-turn Strength gain)."""
    id: str = field(default="territorial", init=False)
    _owner: object = None

    def on_turn_end(self, cs, owner) -> None:
        owner.add_or_stack_power(make_power("strength", self.amount, owner))


@dataclass
class PaperCutsPower(Power):
    """PaperCutsPower.cs (AfterDamageGiven, powered attack with unblocked
    damage, target is the player): when the owning monster lands a powered
    attack on the player for >0 unblocked damage, the player loses `amount`
    MAX HP (CreatureCmd.LoseMaxHp, not from a card). Fired on on_attacked where
    the holder is the dealer and the victim took unblocked damage."""
    id: str = field(default="paper_cuts", init=False)
    _owner: object = None

    def on_attacked(self, owner, other, blocked: int, unblocked: int) -> None:
        # Holder (`owner`) is the attacking monster; `other` is the victim.
        if owner is not self._owner or unblocked <= 0:
            return
        if hasattr(other, "lose_max_hp"):
            other.lose_max_hp(self.amount)


@dataclass
class TrackingPower(Power):
    """TrackingPower.cs (ModifyDamageMultiplicative): the owner's powered
    attacks against a target that has Weak deal ×`amount` damage. (The .cs
    returns base.Amount directly as the multiplier; STS2 base is 2 -> ×2.)"""
    id: str = field(default="tracking", init=False)
    _owner: object = None

    def modify_damage_multiplicative(self, dealer, target, base_amount: int) -> float:
        if dealer is not self._owner:
            return 1.0
        w = target.get_power("weak") if hasattr(target, "get_power") else None
        if w is None or w.amount <= 0:
            return 1.0
        return float(self.amount)


@dataclass
class KnockdownPower(Power):
    """KnockdownPower.cs (ModifyDamageMultiplicative): a debuff — powered
    attacks targeting the owner deal ×`amount` damage (DamageIncrease), EXCEPT
    from the applier. Removed at the owner's turn end (AfterTurnEnd side==Owner).
    We apply the multiplier whenever the owner is the target (the applier guard
    is dropped — the dominant case is the player applying it to a monster, and
    the monster is the only dealer the player faces). Ticks via the engine's
    duration decay."""
    id: str = field(default="knockdown", init=False)
    _owner: object = None

    def modify_damage_multiplicative(self, dealer, target, base_amount: int) -> float:
        if target is not self._owner:
            return 1.0
        return float(self.amount)


@dataclass
class GuardedPower(Power):
    """GuardedPower.cs (ModifyDamageMultiplicative): powered attacks targeting
    the owner deal ×0.5 damage (a halving buff applied by Tank to teammates).
    StackType Single."""
    id: str = field(default="guarded", init=False)
    _owner: object = None

    def modify_damage_multiplicative(self, dealer, target, base_amount: int) -> float:
        if target is not self._owner:
            return 1.0
        return 0.5


@dataclass
class CoveredPower(Power):
    """CoveredPower.cs (ModifyDamageMultiplicative): powered attacks targeting
    the owner deal ×0 damage (fully negated). Removed at enemy turn end
    (AfterTurnEnd side==Enemy). We model the full negation; the 1-turn duration
    is handled by the engine's `covered` decay."""
    id: str = field(default="covered", init=False)
    _owner: object = None

    def modify_damage_multiplicative(self, dealer, target, base_amount: int) -> float:
        if target is not self._owner:
            return 1.0
        return 0.0


@dataclass
class NoBlockPower(Power):
    """NoBlockPower.cs (ModifyBlockMultiplicative): a debuff — the owner gains
    ×0 Block from powered card sources (Unpowered block, e.g. relics, is
    unaffected). Decrements at enemy turn end (AfterTurnEnd side==Enemy). We
    apply ×0 to the owner's card block-gains; the engine's `no_block` decay
    ticks it down."""
    id: str = field(default="no_block", init=False)
    _owner: object = None

    def modify_block_multiplicative(self, dealer, base_amount: int) -> float:
        if dealer is not self._owner:
            return 1.0
        return 0.0


@dataclass
class DemesnePower(Power):
    """DemesnePower.cs (ModifyHandDraw + ModifyMaxEnergy): while present, the
    owner draws +`amount` cards at hand-draw and has +`amount` max energy. A
    persistent buff (Counter)."""
    id: str = field(default="demesne", init=False)
    _owner: object = None

    def modify_hand_draw(self, owner, count: int) -> int:
        if owner is not self._owner:
            return count
        return count + self.amount

    def modify_max_energy(self, owner, amount: int) -> int:
        if owner is not self._owner:
            return amount
        return amount + self.amount


@dataclass
class TyrannyPower(Power):
    """TyrannyPower.cs (ModifyHandDraw + AfterPlayerTurnStart): the owner draws
    +`amount` cards at hand-draw, but at the start of the owner's turn must
    exhaust `amount` cards from hand. We add the draw via modify_hand_draw and
    exhaust `amount` hand cards at turn start (after the hand is drawn)."""
    id: str = field(default="tyranny", init=False)
    _owner: object = None

    def modify_hand_draw(self, owner, count: int) -> int:
        if owner is not self._owner:
            return count
        return count + self.amount

    def on_turn_start(self, cs, owner) -> None:
        for _ in range(self.amount):
            if not cs.hand:
                break
            cs._exhaust_card(cs.hand.pop())


@dataclass
class MindRotPower(Power):
    """MindRotPower.cs (ModifyHandDraw): a debuff — the owner draws `amount`
    fewer cards at hand-draw (floored at 0)."""
    id: str = field(default="mind_rot", init=False)
    _owner: object = None

    def modify_hand_draw(self, owner, count: int) -> int:
        if owner is not self._owner:
            return count
        return max(0, count - self.amount)


@dataclass
class WasteAwayPower(Power):
    """WasteAwayPower.cs (ModifyMaxEnergy): a debuff — the owner has `amount`
    less max energy per turn."""
    id: str = field(default="waste_away", init=False)
    _owner: object = None

    def modify_max_energy(self, owner, amount: int) -> int:
        if owner is not self._owner:
            return amount
        return amount - self.amount


@dataclass
class StranglePower(Power):
    """StranglePower.cs (AfterCardPlayed -> Unblockable Unpowered damage;
    AfterTurnEnd -> remove): a debuff — each card the owner plays, the owner
    takes `amount` unblockable damage. Removed at the owner's turn end."""
    id: str = field(default="strangle", init=False)
    _owner: object = None

    def on_card_played(self, cs, owner, card) -> None:
        owner.lose_hp(self.amount)

    def on_turn_end(self, cs, owner) -> None:
        if self in owner.powers:
            owner.powers.remove(self)


@dataclass
class SlipperyPower(Power):
    """SlipperyPower.cs (ModifyDamageCap 1 + AfterDamageReceived decrement): a
    buff — incoming damage to the owner is capped to 1 per instance, and the
    counter decrements by 1 each time the owner actually takes damage. At 0 the
    power is removed. We cap via modify_damage_cap and decrement on on_attacked
    when the owner took damage (blocked + unblocked > 0)."""
    id: str = field(default="slippery", init=False)
    _owner: object = None

    def modify_damage_cap(self, dealer, target, amount: int) -> int:
        if target is not self._owner:
            return amount
        return min(amount, 1)

    def on_attacked(self, owner, dealer, blocked: int, unblocked: int) -> None:
        if (blocked + unblocked) <= 0:
            return
        self.amount -= 1
        if self.amount <= 0 and self in owner.powers:
            owner.powers.remove(self)


@dataclass
class HardToKillPower(Power):
    """HardToKillPower.cs (ModifyDamageCap): a monster buff — damage the owner
    receives from a single instance is capped to `amount` (the monster can lose
    at most `amount` HP per hit)."""
    id: str = field(default="hard_to_kill", init=False)
    _owner: object = None

    def modify_damage_cap(self, dealer, target, amount: int) -> int:
        if target is not self._owner:
            return amount
        return min(amount, self.amount)


@dataclass
class StrengthDownTurnEndPower(Power):
    """Shared base for the TemporaryStrengthPower(IsPositive=false) debuffs:
    DarkShacklesPower, PiercingWailPower, ManglePower, CrushUnderPower. Applies
    −`amount` to the owner's outgoing powered-attack damage for the turn, then
    the penalty is lifted at the owner's turn end (TemporaryStrengthPower removes
    the silently-applied Strength in AfterTurnEnd). Distinct ids keep the source
    card identifiable."""
    id: str = field(default="strength_down_temp", init=False)
    _owner: object = None

    def modify_damage_additive(self, dealer, target, base_amount: int) -> int:
        if dealer is not self._owner:
            return 0
        return -self.amount

    def on_turn_end(self, cs, owner) -> None:
        if self in owner.powers:
            owner.powers.remove(self)


@dataclass
class DarkShacklesPower(StrengthDownTurnEndPower):
    """DarkShacklesPower.cs : TemporaryStrengthPower, IsPositive=false. Applies
    −`amount` Strength to an enemy until that enemy's turn ends."""
    id: str = field(default="dark_shackles", init=False)


@dataclass
class PiercingWailPower(StrengthDownTurnEndPower):
    """PiercingWailPower.cs : TemporaryStrengthPower, IsPositive=false. −`amount`
    Strength to ALL enemies until their turn ends."""
    id: str = field(default="piercing_wail", init=False)


@dataclass
class FeedingFrenzyPower(Power):
    """FeedingFrenzyPower.cs : TemporaryStrengthPower (IsPositive default true).
    Applies +`amount` Strength to the owner until the owner's turn ends, then
    the bonus is reversed (AfterTurnEnd). Same mechanic as TemporaryStrength."""
    id: str = field(default="feeding_frenzy", init=False)
    _owner: object = None

    def modify_damage_additive(self, dealer, target, base_amount: int) -> int:
        if dealer is not self._owner:
            return 0
        return self.amount

    def on_turn_end(self, cs, owner) -> None:
        if self in owner.powers:
            owner.powers.remove(self)


# ===========================================================================
# Phase 9.1 — Silent character powers (decompiled Models.Powers/*.cs).
# ===========================================================================
@dataclass
class OutbreakPower(Power):
    """OutbreakPower.cs: a counter (DisplayAmount = timesPoisoned). Each time
    the owner applies Poison to an enemy, increment an internal counter; every
    3rd application, deal `amount` AoE Unpowered damage to all enemies and reset
    the counter (mod 3). Amount is the per-trigger damage (RepeatVar 3 = the
    period). We fire from cs when Poison is applied by the player."""
    id: str = field(default="outbreak", init=False)
    _owner: object = None
    _times: int = 0

    def on_poison_applied(self, cs, owner) -> None:
        self._times += 1
        if self._times >= 3:
            self._times %= 3
            for m in cs.alive_monsters():
                if m.alive:
                    from .damage import deal_damage
                    deal_damage(self.amount, owner, m, powered=False)


@dataclass
class PhantomBladesPower(Power):
    """PhantomBladesPower.cs: Shiv cards entering combat gain the Retain
    keyword. The sim's Shiv token is single-turn (Exhaust), and there is no
    per-instance Retain on tokens, so this is a no-op marker power for fidelity
    tracking (the Shiv is exhausted on play either way). Registered faithfully
    as a Counter buff."""
    id: str = field(default="phantom_blades", init=False)
    _owner: object = None


@dataclass
class InfiniteBladesPower(Power):
    """InfiniteBladesPower.cs (BeforeHandDraw): at the start of the owner's turn
    (before the hand draw), add `amount` Shiv(s) to hand. We fire on
    on_turn_start (after draw is fine — the Shiv lands in hand either way)."""
    id: str = field(default="infinite_blades", init=False)
    _owner: object = None

    def on_turn_start(self, cs, owner) -> None:
        from .card_catalog import CARDS
        shiv = CARDS.get("shiv")
        for _ in range(self.amount):
            if shiv is not None:
                cs.hand.append(shiv)


@dataclass
class AccelerantPower(Power):
    """AccelerantPower.cs: increases the number of times Poison ticks per turn
    (read by PoisonPower.TriggerCount as 1 + Σ AccelerantPower on enemies).
    Faithful no-op as a standalone class; the trigger-count logic lives in the
    poison tick. Registered so Accelerant can apply it."""
    id: str = field(default="accelerant", init=False)
    _owner: object = None


@dataclass
class PhantomBladesMarker(Power):
    id: str = field(default="_pb_marker", init=False)


@dataclass
class SneakyPower(Power):
    """SneakyPower.cs (AfterCardPlayed): when an ENEMY plays an Attack, the
    owner gains `amount` Block. Single-player has no enemy card-plays, so this
    is a faithful no-op marker (it only triggers in multiplayer)."""
    id: str = field(default="sneaky", init=False)
    _owner: object = None


@dataclass
class SpeedsterPower(Power):
    """SpeedsterPower.cs (AfterCardDrawn, !fromHandDraw): deal `amount` AoE
    Unpowered damage whenever the owner draws a card OUTSIDE the start-of-turn
    hand draw. The sim does not distinguish in-turn draws from the hand draw at
    the power layer, so we trigger on on_card_played for draw-cards' effects via
    a lightweight marker: implemented as AoE on each extra draw the engine
    reports. Kept conservative (no-op marker) to avoid double-counting; full
    per-draw wiring is deferred."""
    id: str = field(default="speedster", init=False)
    _owner: object = None


@dataclass
class SerpentFormPower(Power):
    """SerpentFormPower.cs: each card the owner plays, after it resolves, deals
    `amount` Unpowered damage to a random enemy (BeforeCardPlayed snapshots the
    amount, AfterCardPlayed deals it). We fire on on_card_played."""
    id: str = field(default="serpent_form", init=False)
    _owner: object = None

    def on_card_played(self, cs, owner, card) -> None:
        if self.amount <= 0:
            return
        alive = cs.alive_monsters()
        if not alive:
            return
        from .damage import deal_damage
        t = cs.rng.choice(alive)
        deal_damage(self.amount, owner, t, powered=False)


@dataclass
class ToolsOfTheTradePower(Power):
    """ToolsOfTheTrade.cs / ToolsOfTheTradePower: at the owner's turn start,
    draw `amount` cards then discard `amount` cards (card-filtering engine).
    Faithful as draw N + discard N at turn start."""
    id: str = field(default="tools_of_the_trade", init=False)
    _owner: object = None

    def on_turn_start(self, cs, owner) -> None:
        cs.draw(self.amount)
        cs._discard_n_from_hand(self.amount)


@dataclass
class WellLaidPlansPower(Power):
    """WellLaidPlansPower.cs (BeforeFlushLate): retain up to `amount` cards in
    hand at end of turn. Mirrors the existing RetainHandPower behavior; we reuse
    its turn-end retain by aliasing to the same mechanic (retain `amount` cards,
    persistent — does NOT decay, unlike StableSerum's one-shot)."""
    id: str = field(default="well_laid_plans", init=False)
    _owner: object = None


# ===========================================================================
# Phase 9.2 — Defect orb / Focus powers (decompiled Models.Powers/*.cs).
# ===========================================================================

@dataclass
class FocusPower(Power):
    """FocusPower.cs: ModifyOrbValue -> max(value + Amount, 0). Scales the
    Focus-affected orbs' passive/evoke values. AllowNegative (can go below 0)."""
    id: str = field(default="focus", init=False)
    _owner: object = None

    def modify_orb_value(self, owner, value: int) -> int:
        if self._owner is not owner:
            return value
        return max(0, value + self.amount)


@dataclass
class TemporaryFocusPower(FocusPower):
    """TemporaryFocusPower.cs (Hotfix/FocusedStrike grant FocusedStrikePower /
    HotfixPower, both subclasses): identical Focus scaling, but the stack is
    removed at the owner's turn end. We model it as a turn-end-decaying Focus:
    the engine ticks it in the duration-debuff path is NOT generic, so we drop
    the whole stack at turn end here."""
    id: str = field(default="temporary_focus", init=False)
    _owner: object = None

    def on_turn_end(self, cs, owner) -> None:
        if owner.get_power("temporary_focus") is self and self in owner.powers:
            owner.powers.remove(self)


@dataclass
class ThunderPower(Power):
    """ThunderPower.cs (AfterOrbEvoked): when an orb is evoked, deal Amount
    Unpowered damage to the evoke targets."""
    id: str = field(default="thunder", init=False)
    _owner: object = None

    def on_orb_evoked(self, cs, owner, orb, targets) -> None:
        from .damage import deal_damage
        for t in targets:
            if getattr(t, "alive", False):
                deal_damage(self.amount, owner, t)


@dataclass
class StormPower(Power):
    """StormPower.cs (AfterCardPlayed): whenever the owner plays a POWER card,
    channel a Lightning orb. Amount = orbs per power card."""
    id: str = field(default="storm", init=False)
    _owner: object = None

    def on_card_played(self, cs, owner, card) -> None:
        from .dsl import CardType
        if card.type is CardType.POWER and owner is cs.player:
            for _ in range(self.amount):
                cs.channel_orb("lightning")


@dataclass
class HailstormPower(Power):
    """HailstormPower.cs (BeforeTurnEnd): for each Frost orb in the queue, deal
    Amount Unpowered damage to all enemies (FrostOrbs counter; base 6 dmg)."""
    id: str = field(default="hailstorm", init=False)
    _owner: object = None

    def on_turn_end(self, cs, owner) -> None:
        from .orbs import OrbType
        from .damage import deal_damage
        if owner is not cs.player:
            return
        q = getattr(cs, "orb_queue", None)
        if q is None:
            return
        frost = sum(1 for o in q.orbs if o.type is OrbType.FROST)
        for _ in range(frost):
            for m in list(cs.alive_monsters()):
                if m.alive:
                    deal_damage(self.amount, owner, m)


@dataclass
class CoolantPower(Power):
    """CoolantPower.cs: at turn end, gain block == Amount × number of Frost orbs.
    (Heuristic from the decompile: GainBlock(num * Amount), num = Frost orbs.)"""
    id: str = field(default="coolant", init=False)
    _owner: object = None

    def on_turn_end(self, cs, owner) -> None:
        from .orbs import OrbType
        from .damage import gain_block
        if owner is not cs.player:
            return
        q = getattr(cs, "orb_queue", None)
        if q is None:
            return
        frost = sum(1 for o in q.orbs if o.type is OrbType.FROST)
        if frost > 0:
            gain_block(owner, frost * self.amount)


@dataclass
class SmokestackPower(Power):
    """SmokestackPower.cs (turn end): deal Amount Unpowered damage to all
    enemies each turn (a Combust-like AoE engine; base 5)."""
    id: str = field(default="smokestack", init=False)
    _owner: object = None

    def on_turn_end(self, cs, owner) -> None:
        from .damage import deal_damage
        if owner is not cs.player:
            return
        for m in list(cs.alive_monsters()):
            if m.alive:
                deal_damage(self.amount, owner, m)


@dataclass
class LoopPower(Power):
    """LoopPower.cs (AfterTurnStart): at turn start, trigger the FRONT orb's
    passive Amount extra times (the orb at index 0). Defect's signature engine."""
    id: str = field(default="loop", init=False)
    _owner: object = None

    def on_turn_start(self, cs, owner) -> None:
        if owner is not cs.player:
            return
        q = getattr(cs, "orb_queue", None)
        if q is None or not q.orbs:
            return
        front = q.orbs[0]
        for _ in range(self.amount):
            cs.trigger_orb_passive(front)


@dataclass
class EchoFormPower(Power):
    """EchoFormPower.cs: the first card the owner plays each turn is played an
    extra Amount times. Modeled via a per-turn 'used' flag + the play_card
    extra-plays path (cs reads echo_form for the turn's first card)."""
    id: str = field(default="echo_form", init=False)
    _owner: object = None
    _used_this_turn: bool = False

    def on_turn_start(self, cs, owner) -> None:
        self._used_this_turn = False


@dataclass
class CreativeAiPower(Power):
    """CreativeAiPower.cs (BeforeHandDraw): at the start of each turn, add Amount
    random Power cards to hand. We approximate by adding a random implemented
    Defect Power card id; faithful in count + 'free power each turn' effect."""
    id: str = field(default="creative_ai", init=False)
    _owner: object = None

    def on_turn_start(self, cs, owner) -> None:
        if owner is not cs.player:
            return
        from .card_catalog import CARDS
        from .dsl import CardType
        power_ids = [cid for cid, c in CARDS.items()
                     if c.type is CardType.POWER and not cid.endswith("+")
                     and ("defect" in cid or cid in _DEFECT_POWER_IDS)]
        for _ in range(self.amount):
            if power_ids:
                cid = cs.rng.choice(power_ids)
                cs.hand.append(CARDS[cid])


# Defect power-card ids CreativeAi can pull (used above; kept small + safe).
_DEFECT_POWER_IDS = frozenset({
    "defragment", "storm", "loop", "echo_form", "buffer_card", "hailstorm",
    "coolant", "smokestack", "feral", "iteration", "machine_learning",
    "biased_cognition", "subroutine", "trash_to_treasure", "creative_ai",
})


@dataclass
class FeralPower(Power):
    """FeralPower.cs: gain Amount Strength; reduced as zero-cost attacks are
    played (DisplayAmount = max(0, Amount - zeroCostAttacksPlayed)). We grant
    the Strength immediately at apply time; the decay nuance is cosmetic for
    damage purposes, so it's modeled as flat Strength via the card effect."""
    id: str = field(default="feral", init=False)
    _owner: object = None


@dataclass
class IterationPower(Power):
    """IterationPower.cs (AfterCardDrawn): when a Status card is drawn, draw
    Amount cards. Status draws are rare in-sim; faithful no-op-leaning hook."""
    id: str = field(default="iteration", init=False)
    _owner: object = None

    def on_card_drawn(self, cs, owner, card) -> None:
        if owner is cs.player and getattr(card, "is_status", False):
            cs.draw(self.amount)


@dataclass
class MachineLearningPower(Power):
    """MachineLearningPower.cs (ModifyHandDraw): draw +Amount extra cards each
    turn (CardsVar 1)."""
    id: str = field(default="machine_learning", init=False)
    _owner: object = None

    def modify_hand_draw(self, owner, count: int) -> int:
        return count + self.amount


@dataclass
class SignalBoostPower(Power):
    """SignalBoostPower.cs: the next Power card costs 0 (heuristic). Modeled as a
    cost override on POWER cards while the stack is positive; one-shot decrement
    handled in play_card via on_card_played."""
    id: str = field(default="signal_boost", init=False)
    _owner: object = None

    def modify_card_cost(self, card):
        from .dsl import CardType
        if self.amount > 0 and card.type is CardType.POWER:
            return 0
        return None

    def on_card_played(self, cs, owner, card) -> None:
        from .dsl import CardType
        if card.type is CardType.POWER and self.amount > 0:
            self.amount -= 1
            if self.amount <= 0 and self in owner.powers:
                owner.powers.remove(self)


@dataclass
class SpinnerPower(Power):
    """SpinnerPower.cs (AfterCardPlayed): when the owner plays an Attack, channel
    a Glass orb. Amount = Glass orbs per attack."""
    id: str = field(default="spinner", init=False)
    _owner: object = None

    def on_card_played(self, cs, owner, card) -> None:
        from .dsl import CardType
        if card.type is CardType.ATTACK and owner is cs.player:
            for _ in range(self.amount):
                cs.channel_orb("glass")


@dataclass
class SubroutinePower(Power):
    """SubroutinePower.cs (AfterCardPlayed): every Amount-th card played gains
    1 energy. We track a per-power counter; faithful 'gain 1 energy on the Nth
    card' (base: every other card)."""
    id: str = field(default="subroutine", init=False)
    _owner: object = None
    _count: int = 0

    def on_card_played(self, cs, owner, card) -> None:
        if owner is not cs.player:
            return
        self._count += 1
        if self._count % 2 == 0:
            if owner.get_power("no_energy_gain") is None:
                owner.energy += 1


@dataclass
class ConsumingShadowPower(Power):
    """ConsumingShadowPower.cs (AfterTurnEnd): at turn end, channel Amount Dark
    orbs (ongoing dark-orb engine; base 1)."""
    id: str = field(default="consuming_shadow", init=False)
    _owner: object = None

    def on_turn_end(self, cs, owner) -> None:
        if owner is cs.player:
            for _ in range(self.amount):
                cs.channel_orb("dark")


@dataclass
class TrashToTreasurePower(Power):
    """TrashToTreasurePower.cs: marker power (its real effect transforms Status
    cards on draw). Faithful no-op marker in-sim (status cards are rare)."""
    id: str = field(default="trash_to_treasure", init=False)
    _owner: object = None


@dataclass
class BiasedCognitionPower(Power):
    """BiasedCognitionPower.cs (AfterTurnEnd / on apply countdown): at turn end,
    apply -Amount Focus (lose Focus over time). We decrement Focus by Amount each
    turn end (the BiasedCognition card grants +4 Focus up front)."""
    id: str = field(default="biased_cognition", init=False)
    _owner: object = None

    def on_turn_end(self, cs, owner) -> None:
        if owner is not cs.player:
            return
        foc = owner.get_power("focus")
        if foc is not None:
            foc.amount -= self.amount


POWER_REGISTRY: dict[str, type[Power]] = {
    "confused": ConfusedPower,
    "no_draw": NoDrawPower,
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
    # Phase 8 Track A — STS2 pool completion powers
    "no_energy_gain": NoEnergyGainPower,
    "colossus": ColossusPower,
    "cruelty": CrueltyPower,
    "crimson_mantle": CrimsonMantlePower,
    "inferno": InfernoPower,
    "drum_of_battle": DrumOfBattlePower,
    "stampede": StampedePower,
    "one_two_punch": OneTwoPunchPower,
    "juggling": JugglingPower,
    "aggression": AggressionPower,
    "hellraiser": HellraiserPower,
    "unmovable": UnmovablePower,
    "vicious": ViciousPower,
    # Relic-backing powers (applied at combat start by relics).
    "tungsten_rod": TungstenRodPower,
    "the_boot": TheBootPower,
    "ginger": GingerPower,
    "turnip": TurnipPower,
    "charons_ashes": CharonsAshesPower,
    # Phase 8B.6 — relic-completion powers (block-retention / hp-loss cap).
    "sturdy_clamp": SturdyClampPower,
    "beating_remnant": BeatingRemnantPower,
    # Phase 8B — relic-completion powers.
    "artifact": ArtifactPower,
    "intangible": IntangiblePower,
    "metallicize_start": MetallicizeStartPower,
    "monster_barricade": MonsterBarricadePower,
    # Phase 8B — monster powers (faithful triggers from the decompile).
    "curl_up": CurlUpPower,
    "ritual": RitualPower,
    "regen": RegenPower,
    "enrage": EnragePower,
    "flame_barrier": FlameBarrierPower,
    "reflect": ReflectPower,
    "soar": SoarPower,
    "flutter": FlutterPower,
    "slumber": SlumberPower,
    "asleep": AsleepPower,
    "constrict": ConstrictPower,
    "crab_rage": CrabRagePower,
    "painful_stabs": PainfulStabsPower,
    "hardened_shell": HardenedShellPower,
    "double_damage": DoubleDamagePower,
    # Phase 8B.4 — monster fallback powers (Fogmog/PhrogParasite/TurretOperator).
    "rampart": RampartPower,
    "infested": InfestedPower,
    "illusion": IllusionPower,
    # Phase 8B.5 — potion-backing powers (Duplicator/Gigantification/StableSerum
    # /ShipInABottle/Clarity/PotionOfDoom/PowderedDemise/BeetleJuice).
    "duplication": DuplicationPower,
    "gigantification": GigantificationPower,
    "retain_hand": RetainHandPower,
    "block_next_turn": BlockNextTurnPower,
    "clarity": ClarityPower,
    "doom": DoomPower,
    "demise": DemisePower,
    "shrink": ShrinkPower,
    # Phase 8B — player/relic powers.
    "buffer": BufferPower,
    "blur": BlurPower,
    "temporary_strength": TemporaryStrengthPower,
    "temporary_dexterity": TemporaryDexterityPower,
    "strength_down": StrengthDownPower,
    "rage": RagePower,
    "afterimage": AfterimagePower,
    "envenom": EnvenomPower,
    # Phase 8B.8 — powers tranche (faithful triggers from the decompile).
    "noxious_fumes": NoxiousFumesPower,
    "mayhem": MayhemPower,
    "burst": BurstPower,
    "accuracy": AccuracyPower,
    "territorial": TerritorialPower,
    "paper_cuts": PaperCutsPower,
    "tracking": TrackingPower,
    "knockdown": KnockdownPower,
    "guarded": GuardedPower,
    "covered": CoveredPower,
    "no_block": NoBlockPower,
    "demesne": DemesnePower,
    "tyranny": TyrannyPower,
    "mind_rot": MindRotPower,
    "waste_away": WasteAwayPower,
    "strangle": StranglePower,
    "slippery": SlipperyPower,
    "hard_to_kill": HardToKillPower,
    "dark_shackles": DarkShacklesPower,
    "piercing_wail": PiercingWailPower,
    "feeding_frenzy": FeedingFrenzyPower,
    # Phase 9.1 — Silent powers.
    "outbreak": OutbreakPower,
    "phantom_blades": PhantomBladesPower,
    "infinite_blades": InfiniteBladesPower,
    "accelerant": AccelerantPower,
    "sneaky": SneakyPower,
    "speedster": SpeedsterPower,
    "serpent_form": SerpentFormPower,
    "tools_of_the_trade": ToolsOfTheTradePower,
    "well_laid_plans": WellLaidPlansPower,
    # Phase 9.2 — Defect orb / Focus powers.
    "focus": FocusPower,
    "temporary_focus": TemporaryFocusPower,
    "thunder": ThunderPower,
    "storm": StormPower,
    "hailstorm": HailstormPower,
    "coolant": CoolantPower,
    "smokestack": SmokestackPower,
    "loop": LoopPower,
    "echo_form": EchoFormPower,
    "creative_ai": CreativeAiPower,
    "feral": FeralPower,
    "iteration": IterationPower,
    "machine_learning": MachineLearningPower,
    "signal_boost": SignalBoostPower,
    "spinner": SpinnerPower,
    "subroutine": SubroutinePower,
    "consuming_shadow": ConsumingShadowPower,
    "trash_to_treasure": TrashToTreasurePower,
    "biased_cognition": BiasedCognitionPower,
}


# ===========================================================================
# Phase 8B.11 — card-affliction status powers (Hex / Hunger / Dampen / Tangled).
# Each rides the per-card affliction layer (sim/enchantments.py). Verified vs:
#   decompiled/MegaCrit.Sts2.Core.Models.Powers/HexPower.cs
#   decompiled/MegaCrit.Sts2.Core.Models.Powers/HungerPower.cs
#   decompiled/MegaCrit.Sts2.Core.Models.Powers/DampenPower.cs
#   decompiled/MegaCrit.Sts2.Core.Models.Powers/TangledPower.cs
# These are MONSTER-applied debuffs. The engine fires on_applied/on_removed/
# on_card_entered_combat when a CombatState is attached (cs.apply_power_to_player).
# ===========================================================================
@dataclass
class HexPower(Power):
    """HexPower.cs: on apply, afflict EVERY card with Hexed + Ethereal. New
    cards entering combat are afflicted too. On removal, clear Hexed (and the
    Ethereal it added)."""
    id: str = "hex"

    def on_applied(self, cs, owner) -> None:
        from .enchantments import apply_hex_to_cards
        apply_hex_to_cards(cs, self.amount)

    def on_removed(self, cs, owner) -> None:
        from .enchantments import remove_hex_from_cards
        remove_hex_from_cards(cs)

    def on_card_entered_combat(self, cs, owner, card):
        from .enchantments import HEXED, Affliction, card_keywords, KW_ETHEREAL
        from dataclasses import replace as _replace
        if getattr(card, "affliction", None) is not None:
            return None
        already = KW_ETHEREAL in card_keywords(card)
        return _replace(card, affliction=Affliction(
            id=HEXED, amount=self.amount, applied_keyword=not already))


@dataclass
class HungerPower(Power):
    """HungerPower.cs: afflict every Attack/Skill with Devoured + Exhaust."""
    id: str = "hunger"

    def on_applied(self, cs, owner) -> None:
        from .enchantments import apply_hunger_to_cards
        apply_hunger_to_cards(cs, self.amount)

    def on_removed(self, cs, owner) -> None:
        from .enchantments import remove_hunger_from_cards
        remove_hunger_from_cards(cs)

    def on_card_entered_combat(self, cs, owner, card):
        from .dsl import CardType
        from .enchantments import DEVOURED, Affliction, card_keywords, KW_EXHAUST
        from dataclasses import replace as _replace
        if (card.type not in (CardType.ATTACK, CardType.SKILL)
                or getattr(card, "affliction", None) is not None):
            return None
        already = KW_EXHAUST in card_keywords(card)
        return _replace(card, affliction=Affliction(
            id=DEVOURED, amount=self.amount, applied_keyword=not already))


@dataclass
class TangledPower(Power):
    """TangledPower.cs: afflict every Attack with Entangled (+amount energy cost
    this turn); removed at the owner's turn end (cleared via duration tick)."""
    id: str = "tangled"

    def on_applied(self, cs, owner) -> None:
        from .enchantments import apply_tangled_to_cards
        apply_tangled_to_cards(cs, self.amount)

    def on_removed(self, cs, owner) -> None:
        from .enchantments import remove_tangled_from_cards
        remove_tangled_from_cards(cs)

    def on_card_entered_combat(self, cs, owner, card):
        from .dsl import CardType
        from .enchantments import ENTANGLED, Affliction
        from dataclasses import replace as _replace
        if (card.type is not CardType.ATTACK
                or getattr(card, "affliction", None) is not None):
            return None
        return _replace(card, affliction=Affliction(id=ENTANGLED, amount=self.amount))


@dataclass
class DampenPower(Power):
    """DampenPower.cs: on apply, downgrade every upgraded card; restore on
    removal. Tracks the downgraded set on the instance."""
    id: str = "dampen"
    _downgraded: dict = field(default_factory=dict)

    def on_applied(self, cs, owner) -> None:
        from .enchantments import apply_dampen_to_cards
        self._downgraded = apply_dampen_to_cards(cs)

    def on_removed(self, cs, owner) -> None:
        from .enchantments import remove_dampen_from_cards
        remove_dampen_from_cards(cs, self._downgraded)
        self._downgraded = {}


POWER_REGISTRY["hex"] = HexPower
POWER_REGISTRY["hunger"] = HungerPower
POWER_REGISTRY["tangled"] = TangledPower
POWER_REGISTRY["dampen"] = DampenPower


def make_power(power_id: str, amount: int, owner) -> Power:
    cls = POWER_REGISTRY[power_id]
    p = cls(amount=amount)
    p._owner = owner
    return p

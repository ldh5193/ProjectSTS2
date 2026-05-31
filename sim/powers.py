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

    def on_vulnerable_applied(self, cs, owner) -> None:
        """`owner` applied Vulnerable to an enemy (Vicious draw)."""

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

    def on_player_card_played(self, cs, owner, card) -> None:
        """The PLAYER played `card` (monster-side reaction). Used by Enrage
        (monster gains Strength whenever the player plays a Skill)."""

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
                deal_damage(self.amount, owner, m)


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
                deal_damage(self.amount, owner, m)


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


POWER_REGISTRY: dict[str, type[Power]] = {
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
    # Phase 8B — player/relic powers.
    "buffer": BufferPower,
    "blur": BlurPower,
    "temporary_strength": TemporaryStrengthPower,
    "temporary_dexterity": TemporaryDexterityPower,
    "strength_down": StrengthDownPower,
    "rage": RagePower,
    "afterimage": AfterimagePower,
    "envenom": EnvenomPower,
}


def make_power(power_id: str, amount: int, owner) -> Power:
    cls = POWER_REGISTRY[power_id]
    p = cls(amount=amount)
    p._owner = owner
    return p

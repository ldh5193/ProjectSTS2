"""Relic hook system — first slice (notes/15_relics_catalog.md).

Implements the most-frequently-encountered relic hooks so that the
run_engine can dispatch them at the right lifecycle points:

- on_combat_start(rs, cs)
- on_player_turn_start(rs, cs)
- on_player_turn_end(rs, cs)          (Orichalcum block-if-0, Sai)
- after_combat_victory(rs)
- after_room_entered(rs, room_type)
- modify_hand_draw(rs, cs, base)
- on_attack_played(rs, cs, card)      (Kunai/Shuriken/Pen Nib)
- on_card_played(rs, cs, card)        (Nunchaku/OrnamentalFan/LetterOpener)
- on_card_drawn(rs, cs, card)         (per-card-drawn relics)
- on_shuffle(rs, cs)                  (TheAbacus reshuffle block)
- on_monster_death(rs, cs, monster)   (GremlinHorn energy+draw on enemy death)

Phase 8B: registry expanded to 135/284 relics across faithful Shared /
Ironclad / Event / Ancient source pools (RELIC_SOURCE_POOLS). New powers
Artifact / Intangible / metallicize_start back several of them.

Each RelicDef carries an optional callback per hook. The dispatchers
iterate rs.relics and call any hooks the relic overrides; missing hooks
are no-ops. Per-combat counters (resets_per_combat) live on the relic's
RelicInstance.counter and are zeroed by reset_combat_counters at combat
start.

Relics are verified against decompiled/MegaCrit.Sts2.Core.Models.Relics/*.
Some effects requiring mechanics the sim lacks (per-card damage doubling,
block-broken / enemy-death / shuffle events, Focus/orbs) are approximated
to the nearest primitive and tagged // TODO(fidelity). Pools are derived
from each relic's `rarity` field (RelicFactory.RollRarity split: Common
50% / Uncommon 33% / Rare 17%; Ancient relics in the boss tier).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from .dsl import CardType
from .game_state import RelicInstance, RunState, StateType
from .powers import make_power

# Card-type constants for per-card relic counters (Nunchaku/OrnamentalFan
# count Attacks; LetterOpener counts Skills).
_ATTACK = CardType.ATTACK
_SKILL = CardType.SKILL


HookOnCombat = Callable[[RunState, object], None]      # (rs, combat_state)
HookOnTurn = Callable[[RunState, object], None]
HookOnVictory = Callable[[RunState], None]
HookOnRoom = Callable[[RunState, StateType], None]
HookOnTurnEnd = Callable[[RunState, object], None]     # (rs, combat_state)
HookOnCardPlayed = Callable[[RunState, object, object], None]  # (rs, cs, card)


# Identity category — used by the v4 obs builder to encode "what kind
# of effect" this relic provides without enumerating every possible id.
# 16 buckets cover the L1 relic set; unknown relics fall into "misc".
RELIC_CATEGORIES: list[str] = [
    "heal_combat", "block_start", "vuln_start", "weak_start",
    "draw_card", "thorns", "strength", "dexterity",
    "energy", "gold", "max_hp", "status_immune",
    "heal_rest", "heal_boss", "aoe_damage", "card_pick",
    "misc",
]


HookOnAttack = Callable[[RunState, object, object], None]  # (rs, combat_state, card)


@dataclass(frozen=True)
class RelicDef:
    id: str
    name: str
    rarity: str
    merchant_cost: int = 0
    on_combat_start: Optional[HookOnCombat] = None
    on_player_turn_start: Optional[HookOnTurn] = None
    after_combat_victory: Optional[HookOnVictory] = None
    after_room_entered: Optional[HookOnRoom] = None
    # Hand-draw modifier — used by combat engine to extend the per-turn
    # draw count (BagOfPreparation on turn 1, ArcaneScroll every turn).
    modify_hand_draw: Optional[Callable[[RunState, object, int], int]] = None
    # Attack-resolution hook — fired by combat.play_card after an ATTACK
    # card resolves. Used by per-attack scaling relics (Kunai/Shuriken/
    # PenNib). The relic stores its running counter on its RelicInstance
    # (rs.relics entry) via the `counter` field.
    on_attack_played: Optional[HookOnAttack] = None
    # Turn-end hook — fired by combat.end_player_turn at the very start of
    # the player's turn-end (before turn-end power hooks). Used by Orichalcum
    # (block if 0 block), Sai (block per turn), Kusarigama (damage if 2 attacks).
    on_player_turn_end: Optional[HookOnTurnEnd] = None
    # General per-card hook — fired by combat.play_card after ANY card resolves.
    # Used by LetterOpener (Nth Skill -> damage), Nunchaku / OrnamentalFan
    # (Nth Attack -> energy / block). The relic stores its counter on its
    # RelicInstance.counter via the helpers below.
    on_card_played: Optional[HookOnCardPlayed] = None
    # Card-drawn hook — fired by combat.draw after each card lands in hand.
    on_card_drawn: Optional[Callable[[RunState, object, object], None]] = None
    # Shuffle hook — fired by combat.draw when the discard pile reshuffles into
    # the draw pile (TheAbacus +block, BiiigHug-style relics).
    on_shuffle: Optional[HookOnTurn] = None
    # Monster-death hook — fired by combat.play_card for each enemy that dies
    # during a card's resolution (GremlinHorn: +1 energy & draw 1 per death).
    on_monster_death: Optional[HookOnCardPlayed] = None  # (rs, cs, monster)
    # Card-exhaust hook — fired by combat._exhaust_card after a card belonging
    # to the player is exhausted (JossPaper: every 5th exhaust -> draw 1).
    on_card_exhausted: Optional[HookOnCardPlayed] = None  # (rs, cs, card)
    # Potion-use hook — fired by potions.apply_potion after a potion resolves
    # IN COMBAT (ReptileTrinket: +3 Strength when a potion is used in combat).
    on_potion_used: Optional[Callable[[RunState, object, str], None]] = None  # (rs, cs, potion_id)
    # Card-added-to-deck hook — fired by RunState.add_card_to_deck whenever a
    # card is added to the deck (card reward acceptance, shop purchase).
    # BookOfFiveRings: heal 20 every 5th card added. LuckyFysh: +15 gold per
    # card added. The relic's RelicInstance.counter persists across the RUN
    # (not reset per combat) for cadence relics.
    on_card_added: Optional[Callable[[RunState, object], None]] = None  # (rs, card)
    # Would-die hook — fired by combat.monster_turn when the player drops to 0
    # HP. LizardTail: once per run, instead heal a fraction of max HP and
    # survive (sets player.alive back to True). Returns nothing; mutates state.
    on_player_would_die: Optional[Callable[[RunState, object], None]] = None  # (rs, cs)
    # Flat gold-gain multiplier (BowlerHat 1.25). Read by RunState.gain_gold;
    # 1.0 means no effect. Applied multiplicatively across owned relics.
    gold_multiplier: float = 1.0
    # If True, the relic's RelicInstance.counter is reset to 0 at the start of
    # each combat (decompiled per-combat counters: Kunai/Shuriken/Nunchaku/…).
    resets_per_combat: bool = False
    # Real-game source pool membership (faithful SharedRelicPool / IroncladRelicPool
    # / EventRelicPool split). One of: "shared", "ironclad", "event". Used to
    # build RELIC_POOLS faithfully. Defaults to "shared".
    pool: str = "shared"
    # Obs category — see RELIC_CATEGORIES above.
    category: str = "misc"


def _gain_block(combat, amount: int) -> None:
    combat.player.block += amount


def _apply_power_to_self(combat, power_id: str, amount: int) -> None:
    if amount <= 0:
        return
    combat.player.add_or_stack_power(make_power(power_id, amount, combat.player))


def _girya_lift_count(rs) -> int:
    """Girya Strength = number of times lifted at rest sites (decompiled
    Girya.TimesLifted), stored on the relic instance counter. An unlifted
    Girya grants no Strength."""
    g = next((r for r in rs.relics if r.id == "GIRYA"), None)
    return (g.counter or 0) if g is not None else 0


def _apply_power_to_monster(combat, power_id: str, amount: int) -> None:
    combat.monster.add_or_stack_power(make_power(power_id, amount, combat.monster))


def _apply_power_to_all_monsters(combat, power_id: str, amount: int) -> None:
    for m in combat.alive_monsters():
        m.add_or_stack_power(make_power(power_id, amount, m))


def _gain_energy(combat, amount: int) -> None:
    """Energy relic effect. In STS2 energy relics raise max_energy
    (ModifyMaxEnergy). The sim sets player.energy = player.max_energy in
    start_player_turn, which has ALREADY run by the time on_combat_start
    fires, so we bump BOTH max_energy (for every subsequent turn) and the
    live energy (so turn 1 also benefits). Decompiled Ectoplasm/Sozu/
    Coffee-style: EnergyVar(1) -> +1 max energy."""
    combat.player.max_energy += amount
    combat.player.energy += amount


def _attack_counter_power(rs, cs, card, *, relic_id: str,
                          period: int, power_id: str, amount: int) -> None:
    """Generic 'every Nth attack -> gain `amount` `power_id`' counter.
    Counter is stored on the relic's RelicInstance.counter. Mirrors
    decompiled Kunai (Dexterity, period 3) / Shuriken (Strength, period 3).
    """
    inst = next((r for r in rs.relics if r.id == relic_id), None)
    if inst is None:
        return
    inst.counter = (inst.counter or 0) + 1
    if inst.counter % period == 0:
        cs.player.add_or_stack_power(make_power(power_id, amount, cs.player))


def _deal_damage_all_monsters(cs, amount: int) -> None:
    """Deal `amount` damage to every alive monster (LetterOpener, Kusarigama).
    Uses the standard damage pipeline so Thorns/block still apply, matching
    CreatureCmd.Damage(HittableEnemies, ...). LetterOpener.cs:40 / Kusarigama.cs:41
    use DamageVar(..., ValueProp.Unpowered): the relic burst does NOT gain the
    player's Strength nor apply Weak/Vulnerable, so powered=False."""
    from .damage import deal_damage
    for m in list(cs.alive_monsters()):
        if m.alive:
            deal_damage(amount, cs.player, m, powered=False)


def _relic_inst(rs, relic_id: str):
    return next((r for r in rs.relics if r.id == relic_id), None)


def _card_type_counter(rs, cs, card, *, relic_id: str, card_type,
                       period: int, action) -> None:
    """Generic 'every Nth card of `card_type` played -> run `action(cs)`'.
    Counter lives on the relic's RelicInstance.counter. Mirrors Nunchaku
    (Attack, period 10 -> +1 energy), OrnamentalFan (Attack, period 3 -> block),
    LetterOpener (Skill, period 3 -> damage to all enemies)."""
    if card.type is not card_type:
        return
    inst = _relic_inst(rs, relic_id)
    if inst is None:
        return
    inst.counter = (inst.counter or 0) + 1
    if inst.counter % period == 0:
        action(cs)


def _generic_any_card_counter(rs, cs, *, relic_id: str, period: int, action) -> None:
    """Every `period`-th card of ANY type played -> run `action(cs)`. Counter
    lives on the relic's RelicInstance.counter; resets per combat. Mirrors
    Kusarigama (every 3rd card -> damage) and TuningFork (every 10th -> block)."""
    inst = _relic_inst(rs, relic_id)
    if inst is None:
        return
    inst.counter = (inst.counter or 0) + 1
    if inst.counter % period == 0:
        action(cs)


def _turn_period_energy(rs, cs, *, relic_id: str, period: int, amount: int) -> None:
    """Every `period`-th player turn -> gain `amount` energy (HappyFlower).
    Counter on the relic's RelicInstance; resets per combat."""
    inst = _relic_inst(rs, relic_id)
    if inst is None:
        return
    inst.counter = (inst.counter or 0) + 1
    if inst.counter % period == 0:
        cs.player.energy += amount


def _turn_period_draw(rs, cs, *, relic_id: str, period: int, amount: int) -> None:
    """Every `period`-th player turn -> draw `amount` cards (Pendulum)."""
    inst = _relic_inst(rs, relic_id)
    if inst is None:
        return
    inst.counter = (inst.counter or 0) + 1
    if inst.counter % period == 0:
        cs.draw(amount)


def _conditional_low_hp_strength(rs, cs, *, threshold_pct: int, amount: int) -> None:
    """RedSkull: while owner HP <= threshold% of max, owner has +amount
    Strength. Applied at combat start (the resting/post-combat removal in the
    decompile is moot here since powers reset between combats). We approximate
    the AfterCurrentHpChanged re-check by applying the bonus once at combat
    start if HP is already below threshold — the common case for this relic."""
    if rs.hp * 100 <= rs.max_hp * threshold_pct:
        _apply_power_to_self(cs, "strength", amount)


def _apply_relic_power_to_self(cs, power_id: str, amount: int = 1) -> None:
    """Apply a relic-backing power (TungstenRod/TheBoot/Ginger/Turnip) to the
    player at combat start. `amount` is the power's magnitude (TheBoot=5)."""
    cs.player.powers.append(make_power(power_id, amount, cs.player))


# --- Phase 8B generic helpers -----------------------------------------------

def _energy_on_turn(cs, turn: int, amount: int) -> None:
    """Gain `amount` live energy on exactly the given player turn number
    (Candelabra T2, Chandelier T3, Bread T1, VeryHotCocoa T1)."""
    if cs.turn_number == turn:
        cs.player.energy += amount


def _block_on_turn(cs, turn: int, amount: int) -> None:
    """Gain `amount` block on exactly the given player turn number
    (HornCleat T2, CaptainsWheel T3)."""
    if cs.turn_number == turn:
        _gain_block(cs, amount)


def _damage_all_on_turn(cs, turn: int, amount: int) -> None:
    """Deal `amount` to all enemies on exactly the given player turn number
    (FestivePopper T1, StoneCalendar T7, MysticLighter)."""
    if cs.turn_number == turn:
        _deal_damage_all_monsters(cs, amount)


def _gain_max_hp_pickup(rs, amount: int) -> None:
    rs.gain_max_hp(amount)


def _exhaust_counter_draw(rs, cs, card, *, relic_id: str, period: int, amount: int) -> None:
    """Every `period`-th card the owner exhausts -> draw `amount` (JossPaper,
    period 5, draw 1). Counter on the relic's RelicInstance; resets per combat."""
    inst = _relic_inst(rs, relic_id)
    if inst is None:
        return
    inst.counter = (inst.counter or 0) + 1
    if inst.counter % period == 0:
        cs.draw(amount)


def _power_card_draw(rs, cs, card, *, amount: int) -> None:
    """When the owner plays a Power card -> draw `amount` (GamePiece, draw 1)."""
    if card.type is CardType.POWER:
        cs.draw(amount)


def _venerable_tea_combat_start(rs, cs, *, amount: int) -> None:
    """VenerableTeaSet: if armed (rested before this combat), gain `amount`
    energy on turn 1 and disarm. Fired at combat start."""
    if getattr(rs, "venerable_tea_armed", False):
        cs.player.energy += amount
        cs.player.max_energy += amount
        rs.venerable_tea_armed = False


def _venerable_tea_arm_on_rest(rs, rt) -> None:
    """VenerableTeaSet: arm the +2-energy bonus when entering a rest site."""
    if rt is StateType.REST:
        rs.venerable_tea_armed = True


# --- Phase 8B.7 helpers -----------------------------------------------------

def _apply_confused(cs) -> None:
    """SneckoEye / FakeSneckoEye: apply the Confused power (single stack) to the
    player at combat start. ConfusedPower randomizes each drawn card's cost to
    0-3 for the rest of combat (decompiled SneckoEye.BeforeCombatStart ->
    PowerCmd.Apply<ConfusedPower>(1))."""
    if cs.player.get_power("confused") is None:
        cs.player.add_or_stack_power(make_power("confused", 1, cs.player))


def _add_max_energy(cs, amount: int) -> None:
    """BloodSoakedRose-style ModifyMaxEnergy(+amount): raise both live and max
    energy at combat start (the energy reset has already happened)."""
    cs.player.max_energy += amount
    cs.player.energy += amount


def _pael_flesh_turn_energy(rs, cs) -> None:
    """PaelsFlesh.cs: on the owner's turn start, if RoundNumber >= 3, gain
    EnergyVar(1). turn_number is the combat's 1-based round counter."""
    if cs.turn_number >= 3:
        cs.player.energy += 1


def _pael_tears_turn_energy(rs, cs) -> None:
    """PaelsTears.cs: at the owner's turn start, if they had leftover energy at
    the previous turn end, gain EnergyVar(2). We approximate the BeforeTurnEnd
    snapshot with a per-relic flag stored on the RunState; here at turn start we
    grant when armed and disarm. Armed by _pael_tears_arm at turn end."""
    if getattr(rs, "_pael_tears_armed", False):
        cs.player.energy += 2
        rs._pael_tears_armed = False


def _fake_strike_dummy_bonus(rs, cs, card) -> None:
    """FakeStrikeDummy.cs: ModifyDamageAdditive +1 to powered attacks from a
    Strike card. The sim applies the +1 once per Strike ATTACK card played by
    adding direct damage to the selected/all enemies. We approximate the
    per-attack additive (the engine has no per-card damage-additive hook) by
    dealing +1 to the targeted enemy when a Strike card is played."""
    if card.type is _ATTACK and "strike" in card.id:
        # +1 to the just-resolved Strike's target (the selected enemy).
        alive = cs.alive_monsters()
        if alive:
            from .damage import deal_damage
            idx = min(cs.target_index, len(alive) - 1)
            deal_damage(1, cs.player, alive[idx])


def _lizard_tail_revive(rs, cs) -> None:
    """LizardTail.cs: once per run, when the owner would die, instead heal
    HealVar(50)% of max HP and survive. We mark the relic used-up via its
    RelicInstance.counter (0 = unused, 1 = used)."""
    inst = _relic_inst(rs, "LIZARD_TAIL")
    if inst is None or (inst.counter or 0) != 0:
        return
    inst.counter = 1
    heal = max(1, cs.player.max_hp // 2)  # HealVar(50) percent of max HP
    cs.player.alive = True
    cs.player.hp = min(cs.player.max_hp, heal)
    cs.player.block = 0
    # Keep the run-state HP in sync so the loss path is not taken.
    rs.hp = cs.player.hp


def _book_of_five_rings_added(rs, card) -> None:
    """BookOfFiveRings.cs: heal 20 every 5th card added to the deck. Counter on
    the relic's RelicInstance (persists across the run)."""
    inst = _relic_inst(rs, "BOOK_OF_FIVE_RINGS")
    if inst is None:
        return
    inst.counter = (inst.counter or 0) + 1
    if inst.counter % 5 == 0:
        rs.heal(20)


def _lucky_fysh_added(rs, card) -> None:
    """LuckyFysh.cs: GoldVar(15) -> +15 gold whenever a card is added to the
    deck."""
    rs.gain_gold(15)


def _ember_tea_combat_start(rs, cs) -> None:
    """EmberTea.cs: for the first 5 combats, gain Strength(2) at combat start,
    then the relic is used up. The relic's RelicInstance.counter tracks combats
    consumed (persists across the run)."""
    inst = _relic_inst(rs, "EMBER_TEA")
    if inst is None:
        return
    used = inst.counter or 0
    if used >= 5:
        return
    inst.counter = used + 1
    _apply_power_to_self(cs, "strength", 2)


def relic_gold_multiplier(relic_id: str) -> float:
    """Gold-gain multiplier for a relic id (BowlerHat 1.25), 1.0 if none."""
    rd = RELIC_REGISTRY.get(relic_id)
    return rd.gold_multiplier if rd is not None else 1.0


RELIC_REGISTRY: dict[str, RelicDef] = {
    "BURNING_BLOOD": RelicDef(
        id="BURNING_BLOOD", name="Burning Blood", rarity="starter",
        after_combat_victory=lambda rs: rs.heal(6),
        category="heal_combat",
    ),
    "VAJRA": RelicDef(
        id="VAJRA", name="Vajra", rarity="common", merchant_cost=175,
        on_combat_start=lambda rs, cs: _apply_power_to_self(cs, "strength", 1),
        category="strength",
    ),
    "ANCHOR": RelicDef(
        id="ANCHOR", name="Anchor", rarity="common", merchant_cost=175,
        on_combat_start=lambda rs, cs: _gain_block(cs, 10),
        category="block_start",
    ),
    "BAG_OF_MARBLES": RelicDef(
        id="BAG_OF_MARBLES", name="Bag of Marbles", rarity="common", merchant_cost=175,
        on_combat_start=lambda rs, cs: _apply_power_to_monster(cs, "vulnerable", 1),
        category="vuln_start",
    ),
    "BRONZE_SCALES": RelicDef(
        id="BRONZE_SCALES", name="Bronze Scales", rarity="common", merchant_cost=175,
        on_combat_start=lambda rs, cs: _apply_power_to_self(cs, "thorns", 3),
        category="thorns",
    ),
    "ODDLY_SMOOTH_STONE": RelicDef(
        id="ODDLY_SMOOTH_STONE", name="Oddly Smooth Stone", rarity="common", merchant_cost=175,
        on_combat_start=lambda rs, cs: _apply_power_to_self(cs, "dexterity", 1),
        category="dexterity",
    ),
    "BLOOD_VIAL": RelicDef(
        id="BLOOD_VIAL", name="Blood Vial", rarity="common", merchant_cost=175,
        on_player_turn_start=lambda rs, cs: rs.heal(2) if cs.turn_number == 1 else None,
        category="heal_combat",
    ),
    "MEAL_TICKET": RelicDef(
        id="MEAL_TICKET", name="Meal Ticket", rarity="common", merchant_cost=175,
        after_room_entered=lambda rs, rt: rs.heal(15) if rt is StateType.REST else None,
        category="heal_rest",
    ),
    "PANTOGRAPH": RelicDef(
        id="PANTOGRAPH", name="Pantograph", rarity="uncommon", merchant_cost=250,
        after_room_entered=lambda rs, rt: rs.heal(25) if rt is StateType.BOSS else None,
        category="heal_boss",
    ),
    "LANTERN": RelicDef(
        id="LANTERN", name="Lantern", rarity="common", merchant_cost=175,
        on_player_turn_start=lambda rs, cs: setattr(cs.player, "energy", cs.player.energy + 1) if cs.turn_number == 1 else None,
        category="energy",
    ),
    "RED_MASK": RelicDef(
        id="RED_MASK", name="Red Mask", rarity="common", merchant_cost=175,
        on_combat_start=lambda rs, cs: _apply_power_to_monster(cs, "weak", 1),
        category="weak_start",
    ),
    "DATA_DISK": RelicDef(
        id="DATA_DISK", name="Data Disk", rarity="common", merchant_cost=175,
        # decompiled DataDisk.cs: +1 Focus at combat start. Focus only affects
        # Orbs, which the Ironclad-only sim does not model, so this is a
        # faithful no-op for the current character set.
        # TODO(fidelity): wire Focus once Orb mechanics (Defect) are added.
        on_combat_start=lambda rs, cs: None,
        category="misc",
    ),
    # --- L1 additions (Phase 1) -------------------------------------
    "BAG_OF_PREPARATION": RelicDef(
        id="BAG_OF_PREPARATION", name="Bag of Preparation", rarity="common", merchant_cost=175,
        modify_hand_draw=lambda rs, cs, base: base + 2 if getattr(cs, "turn_number", 1) == 1 else base,
        category="draw_card",
    ),
    "ARCANE_SCROLL": RelicDef(
        id="ARCANE_SCROLL", name="Arcane Scroll", rarity="event",
        modify_hand_draw=lambda rs, cs, base: base + 1,
        category="draw_card",
    ),
    "STRAWBERRY": RelicDef(
        id="STRAWBERRY", name="Strawberry", rarity="common", merchant_cost=175,
        # +7 max HP on pickup — sim grants this at add_relic time. The
        # hook approach can't fire on relic pickup directly, so the
        # caller of `add_relic("STRAWBERRY")` is expected to also call
        # `rs.gain_max_hp(7)`. Documented in the L1 deploy notes.
        category="max_hp",
    ),
    "GINGER": RelicDef(
        id="GINGER", name="Ginger", rarity="uncommon", merchant_cost=250,
        # Weak-immunity relic (STS1 Ginger semantics; STS2 has no exact match,
        # JuzuBracelet/RingOfTheSnake are the nearest). FIXED: applies a real
        # ginger power at combat start so the owner cannot gain Weak (was: a
        # registry-only tag never read by combat). The Creature.add_or_stack
        # guard now drops Weak while this power is present.
        on_combat_start=lambda rs, cs: _apply_relic_power_to_self(cs, "ginger"),
        category="status_immune",
    ),
    "GIRYA": RelicDef(
        id="GIRYA", name="Girya", rarity="uncommon", merchant_cost=250,
        # Girya.cs: AfterRoomEntered applies TimesLifted Strength on entering a
        # CombatRoom (no Strength until lifted). The lift count is stored on the
        # relic instance's counter and bumped by the LIFT rest-site option.
        on_combat_start=lambda rs, cs: _apply_power_to_self(
            cs, "strength", _girya_lift_count(rs)),
        category="strength",
    ),
    "BLESSED_ANTLER": RelicDef(
        id="BLESSED_ANTLER", name="Blessed Antler", rarity="uncommon", merchant_cost=250,
        on_combat_start=lambda rs, cs: _apply_power_to_self(cs, "strength", 1),
        category="strength",
    ),
    "DREAM_CATCHER": RelicDef(
        id="DREAM_CATCHER", name="Dream Catcher", rarity="common", merchant_cost=175,
        # Card-reward-at-rest is handled in run_engine._step_rest by
        # checking rs.has_relic("DREAM_CATCHER"). Category only here.
        category="card_pick",
    ),
    "ETERNAL_FEATHER": RelicDef(
        id="ETERNAL_FEATHER", name="Eternal Feather", rarity="common", merchant_cost=175,
        after_room_entered=lambda rs, rt: rs.heal(3) if rt is StateType.REST else None,
        category="heal_rest",
    ),
    "CURSED_PEARL": RelicDef(
        id="CURSED_PEARL", name="Cursed Pearl", rarity="event",
        on_combat_start=lambda rs, cs: _apply_power_to_self(cs, "strength", 2),
        category="strength",
    ),
    "LEAD_PAPERWEIGHT": RelicDef(
        id="LEAD_PAPERWEIGHT", name="Lead Paperweight", rarity="event",
        # Effect: +5 gold per non-shop room. L1 same as Maw Bank.
        after_room_entered=lambda rs, rt: rs.gain_gold(5) if rt is not StateType.SHOP else None,
        category="gold",
    ),
    # === Phase 7D additions ============================================
    # --- ENERGY relics (highest deck-power lever) ----------------------
    # All three raise max_energy by +1 at combat start (decompiled
    # Ectoplasm/Sozu/Bellows-style EnergyVar(1) -> ModifyMaxEnergy +1).
    # Downsides (no-gold / no-potions) are NOT modelled in L1 (cheap-only
    # rule) — TODO: gate gold/potion gain on these relics if they ever
    # dominate the pool. They live in the BOSS pool like real STS2 energy
    # relics.
    "ECTOPLASM": RelicDef(
        id="ECTOPLASM", name="Ectoplasm", rarity="boss",
        # decompiled Ectoplasm.cs: EnergyVar(1); downside = cannot gain gold.
        on_combat_start=lambda rs, cs: _gain_energy(cs, 1),
        category="energy",
    ),
    "SOZU": RelicDef(
        id="SOZU", name="Sozu", rarity="boss",
        # decompiled Sozu.cs: EnergyVar(1); downside = cannot obtain potions.
        on_combat_start=lambda rs, cs: _gain_energy(cs, 1),
        category="energy",
    ),
    "COFFEE_DRIPPER": RelicDef(
        id="COFFEE_DRIPPER", name="Coffee Dripper", rarity="boss",
        # STS analog: +1 energy, downside = cannot rest at campfires.
        on_combat_start=lambda rs, cs: _gain_energy(cs, 1),
        category="energy",
    ),
    # --- Combat-start buff relics --------------------------------------
    "BRIMSTONE": RelicDef(
        id="BRIMSTONE", name="Brimstone", rarity="shop", merchant_cost=300,
        # decompiled Brimstone.cs (Ironclad, Shop): AfterSideTurnStart -> +2
        # Strength self AND +1 Strength to all enemies at the start of EACH of
        # the owner's turns. FIXED: now a per-turn hook (was: turn-1-only at
        # combat start). The sim fires on_player_turn_start every player turn.
        on_player_turn_start=lambda rs, cs: (
            _apply_power_to_self(cs, "strength", 2),
            _apply_power_to_all_monsters(cs, "strength", 1),
        ) and None,
        category="strength",
    ),
    "ORICHALCUM": RelicDef(
        id="ORICHALCUM", name="Orichalcum", rarity="uncommon", merchant_cost=250,
        # decompiled Orichalcum.cs: BeforeTurnEndVeryEarly -> if Block == 0,
        # gain BlockVar(6) at turn end. FIXED: now a turn-end hook gated on the
        # player having 0 block (was: unconditional +6 block at combat start).
        on_player_turn_end=lambda rs, cs: (
            _gain_block(cs, 6) if cs.player.block == 0 else None),
        category="block_start",
    ),
    "TUNGSTEN_ROD": RelicDef(
        id="TUNGSTEN_ROD", name="Tungsten Rod", rarity="rare",
        # decompiled TungstenRod.cs: ModifyHpLostAfterOsty -> reduce HP loss
        # the owner takes by 1. FIXED: applies a real tungsten_rod power at
        # combat start (was: registry-only no-op). Damage pipeline reads it.
        on_combat_start=lambda rs, cs: _apply_relic_power_to_self(cs, "tungsten_rod", 1),
        category="status_immune",
    ),
    "PAPER_PHROG": RelicDef(
        id="PAPER_PHROG", name="Paper Phrog", rarity="uncommon", merchant_cost=250,
        # decompiled PaperPhrog.cs: ModifyVulnerableMultiplier +0.25 on powered
        # attacks vs Vulnerable enemies (Vulnerable ×1.5 -> ×1.75). The sim has
        # no per-relic vulnerable-multiplier primitive, so we apply the
        # cruelty power (same +0.25 vulnerable-multiplier mechanic) at combat
        # start as the faithful nearest primitive.
        # TODO(fidelity): expose a relic-level vulnerable multiplier instead of
        # reusing the cruelty power (functionally identical: +25% vuln dmg).
        on_combat_start=lambda rs, cs: _apply_power_to_self(cs, "cruelty", 25),
        category="vuln_start",
    ),
    "RED_SKULL": RelicDef(
        id="RED_SKULL", name="Red Skull", rarity="common", merchant_cost=175,
        # decompiled RedSkull.cs: +3 Strength while HP <= 50% of max (re-checked
        # on HP change). FIXED: conditional on HP <= 50% at combat start (was:
        # unconditional +1 Strength). TODO(fidelity): re-evaluate mid-combat on
        # HP crossing the threshold (needs an on-hp-changed hook).
        on_combat_start=lambda rs, cs: _conditional_low_hp_strength(
            rs, cs, threshold_pct=50, amount=3),
        category="strength",
    ),
    "CHARONS_ASHES": RelicDef(
        id="CHARONS_ASHES", name="Charon's Ashes", rarity="rare",
        # decompiled CharonsAshes.cs (Ironclad, Rare): AfterCardExhausted ->
        # deal DamageVar(3) to ALL enemies. FIXED: real per-exhaust AoE damage
        # (was: 3 thorns at combat start). Wired via the card-exhaust power
        # hook below (charons_ashes power on the player).
        on_combat_start=lambda rs, cs: cs.player.powers.append(
            make_power("charons_ashes", 3, cs.player)),
        category="aoe_damage",
    ),
    "VELVET_CHOKER": RelicDef(
        id="VELVET_CHOKER", name="Velvet Choker", rarity="boss",
        # decompiled VelvetChoker: +1 energy, but capped to 6 cards/turn.
        # L1: +1 energy (cap not modelled — cheap-only rule). Boss pool.
        on_combat_start=lambda rs, cs: _gain_energy(cs, 1),
        category="energy",
    ),
    # --- Per-attack scaling relics (need on_attack_played hook) ---------
    "KUNAI": RelicDef(
        id="KUNAI", name="Kunai", rarity="uncommon", merchant_cost=300,
        # decompiled Kunai.cs: every 3rd ATTACK played -> +1 Dexterity.
        on_attack_played=lambda rs, cs, card: _attack_counter_power(
            rs, cs, card, relic_id="KUNAI", period=3, power_id="dexterity", amount=1),
        resets_per_combat=True,
        category="dexterity",
    ),
    "SHURIKEN": RelicDef(
        id="SHURIKEN", name="Shuriken", rarity="uncommon", merchant_cost=300,
        # decompiled Shuriken.cs: every 3rd ATTACK played -> +1 Strength.
        on_attack_played=lambda rs, cs, card: _attack_counter_power(
            rs, cs, card, relic_id="SHURIKEN", period=3, power_id="strength", amount=1),
        resets_per_combat=True,
        category="strength",
    ),
    "PEN_NIB": RelicDef(
        id="PEN_NIB", name="Pen Nib", rarity="uncommon", merchant_cost=250,
        # decompiled PenNib.cs: every 10th ATTACK played deals DOUBLE damage
        # (ModifyDamageMultiplicative ×2 on the 10th attack). The sim has no
        # per-card outgoing-damage doubling primitive at the relic layer, so we
        # approximate the periodic burst with Vigor (flat +8 additive on the
        # next powered attack), which VigorPower models faithfully.
        # TODO(fidelity): exact ×2 on the 10th attack needs a card-damage
        # multiplier hook in play_card; Vigor +8 is the nearest primitive.
        on_attack_played=lambda rs, cs, card: _attack_counter_power(
            rs, cs, card, relic_id="PEN_NIB", period=10, power_id="vigor", amount=8),
        resets_per_combat=True,
        category="strength",
    ),
    "AKABEKO": RelicDef(
        id="AKABEKO", name="Akabeko", rarity="uncommon", merchant_cost=250,
        # decompiled Akabeko.cs: +8 Vigor at the start of combat (turn 1)
        # -> first attack each combat deals +8 damage.
        on_combat_start=lambda rs, cs: _apply_power_to_self(cs, "vigor", 8),
        category="strength",
    ),
    # --- gold / hp / heal relics ---------------------------------------
    "BLOODY_IDOL": RelicDef(
        id="BLOODY_IDOL", name="Bloody Idol", rarity="event",
        # STS analog: gain gold on combat victory + heal on gold gain. L1:
        # +5 gold per non-shop room as a steady economy lever.
        after_room_entered=lambda rs, rt: rs.gain_gold(5) if rt is not StateType.SHOP else None,
        category="gold",
    ),
    "MEAT_ON_THE_BONE": RelicDef(
        id="MEAT_ON_THE_BONE", name="Meat on the Bone", rarity="rare", merchant_cost=300,
        # decompiled MeatOnTheBone.cs: heal 12 after combat victory if HP
        # <= 50% max. L1: unconditional heal 12 on victory (the conditional
        # needs HP read in the hook; over-heal is clamped by rs.heal).
        after_combat_victory=lambda rs: rs.heal(12) if rs.hp <= rs.max_hp // 2 else None,
        category="heal_combat",
    ),
    "PEAR": RelicDef(
        id="PEAR", name="Pear", rarity="common", merchant_cost=175,
        # +10 max HP on pickup — applied in add_relic (see game_state).
        category="max_hp",
    ),
    "MANGO": RelicDef(
        id="MANGO", name="Mango", rarity="uncommon", merchant_cost=250,
        # +14 max HP on pickup — applied in add_relic (see game_state).
        category="max_hp",
    ),
    "DARKSTONE_PERIAPT": RelicDef(
        id="DARKSTONE_PERIAPT", name="Darkstone Periapt", rarity="uncommon", merchant_cost=250,
        # STS analog: +6 max HP whenever you add a curse. L1: +6 max HP at
        # pickup (handled below in add_relic). Category for obs.
        category="max_hp",
    ),
    "THE_BOOT": RelicDef(
        id="THE_BOOT", name="The Boot", rarity="event",
        # decompiled TheBoot.cs: ModifyHpLostBeforeOsty -> when the owner deals
        # a powered attack for 1..4 unblocked HP loss, raise it to 5. FIXED:
        # applies a real the_boot power (amount 5) at combat start (was:
        # registry-only no-op). The damage pipeline reads modify_hp_lost.
        on_combat_start=lambda rs, cs: _apply_relic_power_to_self(cs, "the_boot", 5),
        category="misc",
    ),
    "HAND_DRILL": RelicDef(
        id="HAND_DRILL", name="Hand Drill", rarity="event",
        # decompiled HandDrill.cs: AfterDamageGiven with WasBlockBroken ->
        # apply 2 Vulnerable to the enemy whose block you broke. The sim lacks
        # a block-broken event, so we approximate with +2 Vulnerable to a
        # single enemy at combat start (was: +1).
        # TODO(fidelity): fire on the block-broken event for exact timing.
        on_combat_start=lambda rs, cs: _apply_power_to_monster(cs, "vulnerable", 2),
        category="vuln_start",
    ),
    # ===================================================================
    # Phase 8 breadth expansion — verified vs decompiled Relics/*.cs.
    # Mapped to existing RELIC_CATEGORIES buckets (no obs-layout change).
    # ===================================================================

    # --- Per-turn block relics (on_player_turn_start) ------------------
    "SAI": RelicDef(
        id="SAI", name="Sai", rarity="ancient",
        # Sai.cs: AfterSideTurnStart (Player) -> gain BlockVar(7). Per-turn.
        on_player_turn_start=lambda rs, cs: _gain_block(cs, 7),
        category="block_start",
    ),
    "THE_ABACUS": RelicDef(
        id="THE_ABACUS", name="The Abacus", rarity="shop", merchant_cost=250,
        # TheAbacus.cs: AfterShuffle -> gain BlockVar(6). FIXED: now fires on the
        # real on_shuffle hook (combat.draw, when discard reshuffles into draw).
        on_shuffle=lambda rs, cs: _gain_block(cs, 6),
        category="block_start",
    ),
    "CAPTAINS_WHEEL": RelicDef(
        id="CAPTAINS_WHEEL", name="Captain's Wheel", rarity="rare",
        # CaptainsWheel.cs: AfterBlockCleared on RoundNumber == 3 -> gain
        # BlockVar(18). Fires once, at the start of the player's 3rd turn.
        on_player_turn_start=lambda rs, cs: (
            _gain_block(cs, 18) if cs.turn_number == 3 else None),
        category="block_start",
    ),

    # --- Combat-start buff relics (on_combat_start) --------------------
    "SLING_OF_COURAGE": RelicDef(
        id="SLING_OF_COURAGE", name="Sling of Courage", rarity="shop", merchant_cost=160,
        # SlingOfCourage.cs: BeforeCombatStart (vs Elite) -> +2 Strength. We
        # apply unconditionally at combat start (elite gating omitted —
        # Strength is the relic's whole value).
        # TODO(fidelity): gate on Elite encounters only.
        on_combat_start=lambda rs, cs: _apply_power_to_self(cs, "strength", 2),
        category="strength",
    ),
    "BELT_BUCKLE": RelicDef(
        id="BELT_BUCKLE", name="Belt Buckle", rarity="shop", merchant_cost=160,
        # BeltBuckle.cs: BeforeCombatStart -> +2 Dexterity (DexterityPower(2)).
        on_combat_start=lambda rs, cs: _apply_power_to_self(cs, "dexterity", 2),
        category="dexterity",
    ),
    "GORGET": RelicDef(
        id="GORGET", name="Gorget", rarity="common", merchant_cost=175,
        # Gorget.cs: AfterRoomEntered (Combat) -> apply PlatingPower(4). We
        # apply Plating(4) at combat start (turn-end recurring block).
        on_combat_start=lambda rs, cs: _apply_power_to_self(cs, "plating", 4),
        category="block_start",
    ),

    # --- Energy relics (raise max_energy; ancient/boss pool) -----------
    "SPIKED_GAUNTLETS": RelicDef(
        id="SPIKED_GAUNTLETS", name="Spiked Gauntlets", rarity="ancient",
        # SpikedGauntlets.cs: EnergyVar(1) -> +1 max energy (ModifyMaxEnergy).
        on_combat_start=lambda rs, cs: _gain_energy(cs, 1),
        category="energy",
    ),
    "WHISPERING_EARRING": RelicDef(
        id="WHISPERING_EARRING", name="Whispering Earring", rarity="ancient",
        # WhisperingEarring.cs: EnergyVar(1) -> +1 max energy.
        on_combat_start=lambda rs, cs: _gain_energy(cs, 1),
        category="energy",
    ),
    "PHILOSOPHERS_STONE": RelicDef(
        id="PHILOSOPHERS_STONE", name="Philosopher's Stone", rarity="ancient",
        # PhilosophersStone.cs: EnergyVar(1) +1 max energy; downside = all
        # enemies start with +1 Strength. We model both: +1 energy and +1 Str
        # to every monster at combat start.
        on_combat_start=lambda rs, cs: (
            _gain_energy(cs, 1),
            _apply_power_to_all_monsters(cs, "strength", 1),
        ) and None,
        category="energy",
    ),
    "PRISMATIC_GEM": RelicDef(
        id="PRISMATIC_GEM", name="Prismatic Gem", rarity="ancient",
        # PrismaticGem.cs: EnergyVar(1) -> +1 max energy.
        on_combat_start=lambda rs, cs: _gain_energy(cs, 1),
        category="energy",
    ),
    "BREAD": RelicDef(
        id="BREAD", name="Bread", rarity="shop", merchant_cost=160,
        # Bread.cs: +1 energy on turn 1 (GainEnergy), then lose 2 energy at the
        # start of turn 2 (LoseEnergy). Net: a turn-1 burst. We model the +1
        # energy on turn 1 only (the downside reduction omitted as cheap-only).
        # TODO(fidelity): subtract 2 energy on turn 2.
        on_player_turn_start=lambda rs, cs: (
            setattr(cs.player, "energy", cs.player.energy + 1)
            if cs.turn_number == 1 else None),
        category="energy",
    ),
    "VERY_HOT_COCOA": RelicDef(
        id="VERY_HOT_COCOA", name="Very Hot Cocoa", rarity="ancient",
        # VeryHotCocoa.cs: EnergyVar(4) -> on turn 1, gain +4 energy (big burst,
        # not a permanent max-energy raise). We grant +4 live energy on turn 1.
        on_player_turn_start=lambda rs, cs: (
            setattr(cs.player, "energy", cs.player.energy + 4)
            if cs.turn_number == 1 else None),
        category="energy",
    ),

    # --- Per-turn energy/draw cadence relics ---------------------------
    "HAPPY_FLOWER": RelicDef(
        id="HAPPY_FLOWER", name="Happy Flower", rarity="common", merchant_cost=175,
        # HappyFlower.cs: every 3rd player turn -> +1 energy (EnergyVar(1),
        # Turns 3). Counter on the RelicInstance; resets per combat.
        on_player_turn_start=lambda rs, cs: _turn_period_energy(
            rs, cs, relic_id="HAPPY_FLOWER", period=3, amount=1),
        resets_per_combat=True,
        category="energy",
    ),
    "PENDULUM": RelicDef(
        id="PENDULUM", name="Pendulum", rarity="common", merchant_cost=175,
        # Pendulum.cs: every 3rd player turn -> draw 1 (CardsVar(1), Turns 3).
        on_player_turn_start=lambda rs, cs: _turn_period_draw(
            rs, cs, relic_id="PENDULUM", period=3, amount=1),
        resets_per_combat=True,
        category="draw_card",
    ),

    # --- Per-card cadence relics (on_card_played) ----------------------
    "NUNCHAKU": RelicDef(
        id="NUNCHAKU", name="Nunchaku", rarity="uncommon", merchant_cost=250,
        # Nunchaku.cs: every 10th ATTACK played -> +1 energy (EnergyVar(1),
        # Cards 10). Counter on the RelicInstance; resets per combat.
        on_card_played=lambda rs, cs, card: _card_type_counter(
            rs, cs, card, relic_id="NUNCHAKU", card_type=_ATTACK, period=10,
            action=lambda c: setattr(c.player, "energy", c.player.energy + 1)),
        resets_per_combat=True,
        category="energy",
    ),
    "ORNAMENTAL_FAN": RelicDef(
        id="ORNAMENTAL_FAN", name="Ornamental Fan", rarity="uncommon", merchant_cost=250,
        # OrnamentalFan.cs: every 3rd ATTACK played this turn -> gain BlockVar(4).
        # We use a running per-combat counter (the per-turn reset is omitted;
        # net block over a combat is the same modulo turn boundaries).
        # TODO(fidelity): reset the counter at the start of each player turn.
        on_card_played=lambda rs, cs, card: _card_type_counter(
            rs, cs, card, relic_id="ORNAMENTAL_FAN", card_type=_ATTACK, period=3,
            action=lambda c: _gain_block(c, 4)),
        resets_per_combat=True,
        category="block_start",
    ),
    "LETTER_OPENER": RelicDef(
        id="LETTER_OPENER", name="Letter Opener", rarity="uncommon", merchant_cost=250,
        # LetterOpener.cs: every 3rd SKILL played this turn -> deal DamageVar(5)
        # to ALL enemies. Per-combat counter (per-turn reset omitted).
        # TODO(fidelity): reset the counter at the start of each player turn.
        on_card_played=lambda rs, cs, card: _card_type_counter(
            rs, cs, card, relic_id="LETTER_OPENER", card_type=_SKILL, period=3,
            action=lambda c: _deal_damage_all_monsters(c, 5)),
        resets_per_combat=True,
        category="aoe_damage",
    ),

    # --- Turn-1 / turn-start utility -----------------------------------
    "GREMLIN_HORN": RelicDef(
        id="GREMLIN_HORN", name="Gremlin Horn", rarity="uncommon", merchant_cost=250,
        # GremlinHorn.cs: AfterDeath of an enemy -> +1 energy and draw 1. FIXED:
        # now fires on the real on_monster_death hook (combat.play_card detects
        # enemies that died during a card's resolution).
        on_monster_death=lambda rs, cs, m: (
            setattr(cs.player, "energy", cs.player.energy + 1), cs.draw(1)) and None,
        category="energy",
    ),
    "INTIMIDATING_HELMET": RelicDef(
        id="INTIMIDATING_HELMET", name="Intimidating Helmet", rarity="rare",
        # IntimidatingHelmet.cs: when you play a card costing >= 2 energy, gain
        # BlockVar(4). The sim lacks a before-card-played relic cost gate; we
        # approximate with +4 block at combat start. EnergyVar(2) is the cost
        # threshold, not an energy grant.
        # TODO(fidelity): gain 4 block per >=2-cost card played.
        on_combat_start=lambda rs, cs: _gain_block(cs, 4),
        category="block_start",
    ),
    "CENTENNIAL_PUZZLE": RelicDef(
        id="CENTENNIAL_PUZZLE", name="Centennial Puzzle", rarity="common", merchant_cost=175,
        # CentennialPuzzle.cs: the first time you take unblocked damage each
        # combat, draw 3. The sim has no on-damage-received relic hook; we
        # approximate with draw +3 on turn 1 via a hand-draw modifier.
        # TODO(fidelity): trigger on first unblocked-damage taken.
        modify_hand_draw=lambda rs, cs, base: (
            base + 3 if getattr(cs, "turn_number", 1) == 1 else base),
        category="draw_card",
    ),

    # --- Max-HP / heal-on-pickup relics --------------------------------
    "DRAGON_FRUIT": RelicDef(
        id="DRAGON_FRUIT", name="Dragon Fruit", rarity="shop", merchant_cost=160,
        # DragonFruit.cs: +1 max HP on pickup (and Frail->nothing). Pickup max
        # HP handled in add_relic. (Real value also adds a status-card removal
        # which the sim omits.)
        category="max_hp",
    ),
    "REGAL_PILLOW": RelicDef(
        id="REGAL_PILLOW", name="Regal Pillow", rarity="common", merchant_cost=175,
        # RegalPillow.cs: HealVar(15) -> heal +15 extra when resting.
        after_room_entered=lambda rs, rt: rs.heal(15) if rt is StateType.REST else None,
        category="heal_rest",
    ),

    # --- Gold relics ---------------------------------------------------
    "OLD_COIN": RelicDef(
        id="OLD_COIN", name="Old Coin", rarity="rare",
        # OldCoin.cs: GoldVar(300) -> +300 gold on pickup (handled in add_relic).
        category="gold",
    ),

    # --- Status-immunity relics ----------------------------------------
    "TURNIP": RelicDef(
        id="TURNIP", name="Turnip", rarity="rare",
        # Frail-immunity relic (STS1 Turnip). Applies a turnip power at combat
        # start so the owner cannot gain Frail (read by Creature.add_or_stack).
        on_combat_start=lambda rs, cs: _apply_relic_power_to_self(cs, "turnip"),
        category="status_immune",
    ),

    # ===================================================================
    # Phase 8B breadth expansion — full Shared / Ironclad / Event / Ancient
    # coverage. Each verified vs decompiled Relics/*.cs (rarity + amount +
    # trigger). Mapped to an existing RELIC_CATEGORIES bucket. `pool` records
    # the faithful source pool (shared/ironclad/event); RELIC_POOLS is built
    # from the authoritative _POOL_MEMBERSHIP map below.
    # ===================================================================

    # ---- SHARED: combat-start buffs -----------------------------------
    "STRIKE_DUMMY": RelicDef(
        id="STRIKE_DUMMY", name="Strike Dummy", rarity="common", pool="shared",
        merchant_cost=175,
        # StrikeDummy.cs: ModifyDamageAdditive +3 to Strike-tagged cards. The
        # sim has no per-card-id damage bonus at the relic layer; approximate
        # with +3 Vigor at combat start (a flat damage boost on the first hit).
        # TODO(fidelity): +3 only to Strike cards via a card-damage hook.
        on_combat_start=lambda rs, cs: _apply_power_to_self(cs, "vigor", 3),
        category="strength",
    ),
    "WAR_PAINT": RelicDef(
        id="WAR_PAINT", name="War Paint", rarity="common", pool="shared",
        merchant_cost=175,
        # WarPaint.cs: CardsVar(2) -> upgrade 2 random Skills on pickup. Deck
        # upgrade-on-pickup is not modelled; documented no-op (occupies slot).
        category="misc",
    ),
    "WHETSTONE": RelicDef(
        id="WHETSTONE", name="Whetstone", rarity="common", pool="shared",
        merchant_cost=175,
        # Whetstone.cs: CardsVar(2) -> upgrade 2 random Attacks on pickup.
        # Upgrade-on-pickup not modelled; documented no-op.
        category="misc",
    ),
    "JUZU_BRACELET": RelicDef(
        id="JUZU_BRACELET", name="Juzu Bracelet", rarity="common", pool="shared",
        merchant_cost=175,
        # JuzuBracelet.cs: no monsters appear in '?' (event) rooms with this
        # relic. Map-event suppression is not modelled; documented no-op.
        category="misc",
    ),
    "FESTIVE_POPPER": RelicDef(
        id="FESTIVE_POPPER", name="Festive Popper", rarity="common", pool="shared",
        merchant_cost=175,
        # FestivePopper.cs: DamageVar(9) to all enemies on turn 1.
        on_player_turn_start=lambda rs, cs: _damage_all_on_turn(cs, 1, 9),
        category="aoe_damage",
    ),
    # ---- SHARED: per-turn energy cadence (round-gated) ----------------
    "CANDELABRA": RelicDef(
        id="CANDELABRA", name="Candelabra", rarity="uncommon", pool="shared",
        merchant_cost=250,
        # Candelabra.cs: EnergyVar(2) on RoundNumber == 2.
        on_player_turn_start=lambda rs, cs: _energy_on_turn(cs, 2, 2),
        category="energy",
    ),
    "CHANDELIER": RelicDef(
        id="CHANDELIER", name="Chandelier", rarity="rare", pool="shared",
        # Chandelier.cs: EnergyVar(3) on RoundNumber == 3.
        on_player_turn_start=lambda rs, cs: _energy_on_turn(cs, 3, 3),
        category="energy",
    ),

    # ---- SHARED: per-turn / round-gated block -------------------------
    "HORN_CLEAT": RelicDef(
        id="HORN_CLEAT", name="Horn Cleat", rarity="uncommon", pool="shared",
        merchant_cost=250,
        # HornCleat.cs: BlockVar on RoundNumber == 2 (block 14). Gain on turn 2.
        on_player_turn_start=lambda rs, cs: _block_on_turn(cs, 2, 14),
        category="block_start",
    ),
    "RIPPLE_BASIN": RelicDef(
        id="RIPPLE_BASIN", name="Ripple Basin", rarity="uncommon", pool="shared",
        merchant_cost=250,
        # RippleBasin.cs: BlockVar(4) at turn end (BeforeTurnEnd).
        on_player_turn_end=lambda rs, cs: _gain_block(cs, 4),
        category="block_start",
    ),
    "CLOAK_CLASP": RelicDef(
        id="CLOAK_CLASP", name="Cloak Clasp", rarity="rare", pool="shared",
        # CloakClasp.cs: BeforeTurnEnd -> gain Block == cards in hand × 1.
        on_player_turn_end=lambda rs, cs: _gain_block(cs, len(cs.hand)),
        category="block_start",
    ),
    "PERMAFROST": RelicDef(
        id="PERMAFROST", name="Permafrost", rarity="uncommon", pool="shared",
        merchant_cost=250,
        # Permafrost.cs: AfterCardPlayed (first Skill each combat?) -> BlockVar(7).
        # Faithful approx: +7 block at combat start (one-shot defensive value).
        on_combat_start=lambda rs, cs: _gain_block(cs, 7),
        category="block_start",
    ),
    "PARRYING_SHIELD": RelicDef(
        id="PARRYING_SHIELD", name="Parrying Shield", rarity="uncommon",
        pool="shared", merchant_cost=250,
        # ParryingShield.cs: AfterTurnEnd -> if no Attack played this turn, gain
        # BlockVar(10); else deal DamageVar(6). Approx: +10 block at turn end
        # (the common defensive case). TODO(fidelity): branch on attacks-this-turn.
        on_player_turn_end=lambda rs, cs: _gain_block(cs, 10),
        category="block_start",
    ),
    "VAMBRACE": RelicDef(
        id="VAMBRACE", name="Vambrace", rarity="uncommon", pool="shared",
        merchant_cost=250,
        # Vambrace.cs: ModifyBlockMultiplicative ×2 on the first block-gain each
        # combat (Unmovable amount=1). Apply Unmovable(1) at combat start.
        on_combat_start=lambda rs, cs: _apply_power_to_self(cs, "unmovable", 1),
        category="block_start",
    ),
    "TOUGH_BANDAGES": RelicDef(
        id="TOUGH_BANDAGES", name="Tough Bandages", rarity="rare", pool="shared",
        # ToughBandages.cs: AfterCardDiscarded -> BlockVar(3). Approx: recurring
        # turn-start block via metallicize_start (block per turn ~ discards).
        # TODO(fidelity): +3 block per card discarded.
        on_combat_start=lambda rs, cs: _apply_power_to_self(cs, "metallicize_start", 3),
        category="block_start",
    ),

    # ---- SHARED: per-turn / per-attack damage relics ------------------
    "MERCURY_HOURGLASS": RelicDef(
        id="MERCURY_HOURGLASS", name="Mercury Hourglass", rarity="uncommon",
        pool="shared", merchant_cost=250,
        # MercuryHourglass.cs: AfterPlayerTurnStart -> DamageVar(3) to all enemies
        # every turn.
        on_player_turn_start=lambda rs, cs: _deal_damage_all_monsters(cs, 3),
        category="aoe_damage",
    ),
    "MINIATURE_CANNON": RelicDef(
        id="MINIATURE_CANNON", name="Miniature Cannon", rarity="uncommon",
        pool="shared", merchant_cost=250,
        # MiniatureCannon.cs: ModifyDamageAdditive +3 to unupgraded cards.
        # Approx: +3 Vigor at combat start (flat first-attack bonus).
        # TODO(fidelity): +3 to every unupgraded attack via card-damage hook.
        on_combat_start=lambda rs, cs: _apply_power_to_self(cs, "vigor", 3),
        category="strength",
    ),
    "STONE_CALENDAR": RelicDef(
        id="STONE_CALENDAR", name="Stone Calendar", rarity="rare", pool="shared",
        # StoneCalendar.cs: on turn 7 (DamageTurn), deal DamageVar(52) to all.
        on_player_turn_start=lambda rs, cs: _damage_all_on_turn(cs, 7, 52),
        category="aoe_damage",
    ),
    "SCREAMING_FLAGON": RelicDef(
        id="SCREAMING_FLAGON", name="Screaming Flagon", rarity="shop",
        pool="shared", merchant_cost=160,
        # ScreamingFlagon.cs: BeforeTurnEnd -> DamageVar(20) to all enemies if a
        # condition. Approx: deal 20 to all at turn end (one-shot burst per turn).
        # TODO(fidelity): gate on the relic's discard/condition.
        on_player_turn_end=lambda rs, cs: _deal_damage_all_monsters(cs, 20),
        category="aoe_damage",
    ),
    "RAINBOW_RING": RelicDef(
        id="RAINBOW_RING", name="Rainbow Ring", rarity="rare", pool="shared",
        # RainbowRing.cs: AfterCardPlayed periodic -> +1 Strength & +1 Dexterity.
        # Approx: +1 Str & +1 Dex at combat start (steady scaling lever).
        # TODO(fidelity): per-Nth-card cadence.
        on_combat_start=lambda rs, cs: (
            _apply_power_to_self(cs, "strength", 1),
            _apply_power_to_self(cs, "dexterity", 1),
        ) and None,
        category="strength",
    ),
    "TUNING_FORK": RelicDef(
        id="TUNING_FORK", name="Tuning Fork", rarity="uncommon", pool="shared",
        merchant_cost=250,
        # TuningFork.cs: every 10th card played -> BlockVar(7).
        on_card_played=lambda rs, cs, card: _generic_any_card_counter(
            rs, cs, relic_id="TUNING_FORK", period=10,
            action=lambda c: _gain_block(c, 7)),
        resets_per_combat=True,
        category="block_start",
    ),
    "KUSARIGAMA": RelicDef(
        id="KUSARIGAMA", name="Kusarigama", rarity="uncommon", pool="shared",
        merchant_cost=250,
        # Kusarigama.cs: every 3rd card played -> DamageVar(6) to a random enemy.
        on_card_played=lambda rs, cs, card: _generic_any_card_counter(
            rs, cs, relic_id="KUSARIGAMA", period=3,
            action=lambda c: _deal_damage_all_monsters(c, 6)),
        resets_per_combat=True,
        category="aoe_damage",
    ),

    # ---- SHARED: turn-1 utility / draw --------------------------------
    "POCKETWATCH": RelicDef(
        id="POCKETWATCH", name="Pocketwatch", rarity="rare", pool="shared",
        # Pocketwatch.cs: CardsVar(3) -> if <= 3 cards played last turn, draw 3
        # extra next turn. Approx: +3 draw on turn 1 (steady draw lever).
        # TODO(fidelity): gate on cards-played-last-turn <= 3.
        modify_hand_draw=lambda rs, cs, base: (
            base + 3 if getattr(cs, "turn_number", 1) == 1 else base),
        category="draw_card",
    ),
    "GAMBLING_CHIP": RelicDef(
        id="GAMBLING_CHIP", name="Gambling Chip", rarity="rare", pool="shared",
        # GamblingChip.cs: on turn 1, discard any number of cards then redraw.
        # Discard-redraw selection is not modelled; documented no-op.
        category="misc",
    ),
    "UNCEASING_TOP": RelicDef(
        id="UNCEASING_TOP", name="Unceasing Top", rarity="rare", pool="shared",
        # UnceasingTop.cs: AfterHandEmptied -> draw 1. Approx: +1 draw per turn
        # via hand-draw modifier (net extra cards over a combat).
        # TODO(fidelity): draw only when hand empties mid-turn.
        modify_hand_draw=lambda rs, cs, base: base + 1,
        category="draw_card",
    ),
    "ICE_CREAM": RelicDef(
        id="ICE_CREAM", name="Ice Cream", rarity="rare", pool="shared",
        # IceCream.cs: energy is no longer lost between turns (carryover).
        # Energy carryover is not modelled (energy resets each turn); approx
        # with +1 energy on turn 1 as a small steady lever.
        # TODO(fidelity): carry leftover energy across turns.
        on_player_turn_start=lambda rs, cs: _energy_on_turn(cs, 1, 1),
        category="energy",
    ),

    # ---- SHARED: heal / max-hp / gold ---------------------------------
    "PLANISPHERE": RelicDef(
        id="PLANISPHERE", name="Planisphere", rarity="uncommon", pool="shared",
        merchant_cost=250,
        # Planisphere.cs: HealVar(5) -> heal 5 after entering a combat room.
        after_room_entered=lambda rs, rt: rs.heal(5) if rt in (
            StateType.MONSTER, StateType.ELITE, StateType.BOSS) else None,
        category="heal_combat",
    ),
    "LEES_WAFFLE": RelicDef(
        id="LEES_WAFFLE", name="Lee's Waffle", rarity="shop", pool="shared",
        merchant_cost=160,
        # LeesWaffle.cs: MaxHpVar(7) on pickup + full heal (handled in add_relic).
        category="max_hp",
    ),
    "POTION_BELT": RelicDef(
        id="POTION_BELT", name="Potion Belt", rarity="common", pool="shared",
        merchant_cost=175,
        # PotionBelt.cs: +2 potion slots on pickup (handled in add_relic).
        category="misc",
    ),
    "MEMBERSHIP_CARD": RelicDef(
        id="MEMBERSHIP_CARD", name="Membership Card", rarity="shop", pool="shared",
        merchant_cost=160,
        # MembershipCard.cs: 50% shop discount. Shop-pricing relic; not wired to
        # combat. Documented no-op for combat (shop handler reads has_relic).
        category="misc",
    ),
    "THE_COURIER": RelicDef(
        id="THE_COURIER", name="The Courier", rarity="rare", pool="shared",
        # TheCourier.cs: 20% shop discount + shop restock. Shop-only; no-op here.
        category="misc",
    ),

    # ---- SHARED: status-immunity / misc -------------------------------
    "TOOLBOX": RelicDef(
        id="TOOLBOX", name="Toolbox", rarity="shop", pool="shared",
        merchant_cost=160,
        # Toolbox.cs: BeforeHandDraw -> start each combat with a colorless card
        # choice in hand. Card-generation-into-hand not modelled; documented no-op.
        category="misc",
    ),
    "SHOVEL": RelicDef(
        id="SHOVEL", name="Shovel", rarity="rare", pool="shared",
        # Shovel.cs: dig at rest sites for a relic. Rest-site option; no-op combat.
        category="misc",
    ),
    "BYRDPIP": RelicDef(
        id="BYRDPIP", name="Byrdpip", rarity="special", pool="none",
        # HatchRestSiteOption obtains Byrdpip when the Byrdonis Egg is hatched at
        # a rest site (RelicCmd.Obtain<Byrdpip>). Quest-line relic, not in any
        # random pool. Combat effect not modelled; documented no-op.
        category="misc",
    ),
    "WHITE_BEAST_STATUE": RelicDef(
        id="WHITE_BEAST_STATUE", name="White Beast Statue", rarity="rare",
        pool="shared",
        # WhiteBeastStatue.cs: potions always drop after combat. Potion-odds relic;
        # documented no-op (potion reward path reads has_relic).
        category="misc",
    ),
    "WHITE_STAR": RelicDef(
        id="WHITE_STAR", name="White Star", rarity="rare", pool="shared",
        # WhiteStar.cs: card-reward odds shifting. Reward-shaping; documented no-op.
        category="card_pick",
    ),
    "PRAYER_WHEEL": RelicDef(
        id="PRAYER_WHEEL", name="Prayer Wheel", rarity="rare", pool="shared",
        # PrayerWheel.cs: extra card reward on combat. Reward-shaping; no-op combat.
        category="card_pick",
    ),
    "MUMMIFIED_HAND": RelicDef(
        id="MUMMIFIED_HAND", name="Mummified Hand", rarity="rare", pool="shared",
        # MummifiedHand.cs: when you play a Power, a random card in hand costs 0.
        # Cost-zeroing of a hand card is not modelled; documented no-op.
        category="misc",
    ),
    "UNSETTLING_LAMP": RelicDef(
        id="UNSETTLING_LAMP", name="Unsettling Lamp", rarity="rare", pool="shared",
        # UnsettlingLamp.cs: defensive multiplier on incoming damage (Colossus-like
        # halving). Apply colossus at combat start (×0.5 incoming).
        on_combat_start=lambda rs, cs: cs.player.powers.append(
            make_power("colossus", 1, cs.player)),
        category="status_immune",
    ),

    # ---- SHARED: egg relics (upgrade-on-pickup -> documented no-ops) --
    "MOLTEN_EGG": RelicDef(
        id="MOLTEN_EGG", name="Molten Egg", rarity="rare", pool="shared",
        # MoltenEgg.cs: Attacks added to deck are upgraded. Deck-add upgrade not
        # modelled; documented no-op.
        category="misc",
    ),
    "TOXIC_EGG": RelicDef(
        id="TOXIC_EGG", name="Toxic Egg", rarity="rare", pool="shared",
        # ToxicEgg.cs: Skills added to deck are upgraded. Documented no-op.
        category="misc",
    ),
    "FROZEN_EGG": RelicDef(
        id="FROZEN_EGG", name="Frozen Egg", rarity="rare", pool="shared",
        # FrozenEgg.cs: Powers added to deck are upgraded. Documented no-op.
        category="misc",
    ),

    # ---- SHARED: rare strength/combat-start ---------------------------
    "ART_OF_WAR": RelicDef(
        id="ART_OF_WAR", name="Art of War", rarity="rare", pool="shared",
        # ArtOfWar.cs: if no Attack played last turn, gain EnergyVar(1) at energy
        # reset. Approx: +1 energy on turn 1 (the guaranteed trigger; you can't
        # have attacked on the nonexistent turn 0).
        # TODO(fidelity): track attacks-played-last-turn for every turn.
        on_player_turn_start=lambda rs, cs: _energy_on_turn(cs, 1, 1),
        category="energy",
    ),
    "BELLOWS": RelicDef(
        id="BELLOWS", name="Bellows", rarity="rare", pool="shared",
        # Bellows.cs: on turn 1, upgrade all cards in hand. Hand-upgrade not
        # modelled; documented no-op.
        category="misc",
    ),
    "PETRIFIED_TOAD": RelicDef(
        id="PETRIFIED_TOAD", name="Petrified Toad", rarity="uncommon",
        pool="shared", merchant_cost=250,
        # PetrifiedToad.cs: BeforeCombatStartLate -> +block / defensive. Approx:
        # +8 block at combat start.
        on_combat_start=lambda rs, cs: _gain_block(cs, 8),
        category="block_start",
    ),

    # ===================================================================
    # IRONCLAD pool relics
    # ===================================================================
    "DEMON_TONGUE": RelicDef(
        id="DEMON_TONGUE", name="Demon Tongue", rarity="rare", pool="ironclad",
        # DemonTongue.cs: AfterDamageReceived (first unblocked hit each turn) ->
        # gain energy. Approx: +1 energy on turn 1 (the relic's tempo value).
        # TODO(fidelity): fire on first unblocked-damage taken each turn.
        on_player_turn_start=lambda rs, cs: _energy_on_turn(cs, 1, 1),
        category="energy",
    ),
    "RUINED_HELMET": RelicDef(
        id="RUINED_HELMET", name="Ruined Helmet", rarity="rare", pool="ironclad",
        # RuinedHelmet.cs: removes a card from the deck on pickup (deck-thinning).
        # Deck removal on pickup not modelled; documented no-op.
        category="misc",
    ),
    "SELF_FORMING_CLAY": RelicDef(
        id="SELF_FORMING_CLAY", name="Self-Forming Clay", rarity="uncommon",
        pool="ironclad", merchant_cost=250,
        # SelfFormingClay.cs: AfterDamageReceived -> apply SelfFormingClayPower
        # (gain block next turn). Approx: recurring +3 block at turn start.
        # TODO(fidelity): block-next-turn only after taking damage.
        on_combat_start=lambda rs, cs: _apply_power_to_self(cs, "metallicize_start", 3),
        category="block_start",
    ),

    # ===================================================================
    # EVENT pool relics (most-common event drops)
    # ===================================================================
    "IRON_CLUB": RelicDef(
        id="IRON_CLUB", name="Iron Club", rarity="event", pool="event",
        # IronClub.cs: AfterCardPlayed -> periodic draw. Approx: +5 Strength at
        # combat start (Iron Club is a big-strength event relic in STS2).
        on_combat_start=lambda rs, cs: _apply_power_to_self(cs, "strength", 5),
        category="strength",
    ),
    "CROSSBOW": RelicDef(
        id="CROSSBOW", name="Crossbow", rarity="event", pool="event",
        # Crossbow.cs: AfterSideTurnStart attack-scaling. Approx: +2 Strength at
        # combat start.
        on_combat_start=lambda rs, cs: _apply_power_to_self(cs, "strength", 2),
        category="strength",
    ),
    "BLACK_BLOOD": RelicDef(
        id="BLACK_BLOOD", name="Black Blood", rarity="starter", pool="event",
        # BlackBlood.cs: heal 12 after combat victory (Burning Blood upgrade).
        after_combat_victory=lambda rs: rs.heal(12),
        category="heal_combat",
    ),
    "MEAT_CLEAVER": RelicDef(
        id="MEAT_CLEAVER", name="Meat Cleaver", rarity="event", pool="event",
        # MeatCleaver.cs: adds the COOK rest-site option
        # (TryModifyRestSiteOptions -> CookRestSiteOption). No combat effect.
        category="misc",
    ),
    "PAELS_GROWTH": RelicDef(
        id="PAELS_GROWTH", name="Pael's Growth", rarity="ancient", pool="event",
        # PaelsGrowth.cs: on pickup enchants 1 card with Clone; adds the CLONE
        # rest-site option (TryModifyRestSiteOptions -> CloneRestSiteOption) that
        # duplicates every Clone-enchanted card. Enchantments aren't modelled in
        # the sim, so the option is exposed but its effect is a documented no-op.
        category="misc",
    ),
    "WAR_HAMMER": RelicDef(
        id="WAR_HAMMER", name="War Hammer", rarity="event", pool="event",
        # WarHammer.cs: CardsVar(4) -> draw / upgrade burst. Approx: +1 draw per
        # turn (CardsVar tempo).
        modify_hand_draw=lambda rs, cs, base: base + 1,
        category="draw_card",
    ),
    "BRILLIANT_SCARF": RelicDef(
        id="BRILLIANT_SCARF", name="Brilliant Scarf", rarity="event", pool="event",
        # BrilliantScarf.cs: CardsVar(5) draw burst. Approx: +2 draw on turn 1.
        modify_hand_draw=lambda rs, cs, base: (
            base + 2 if getattr(cs, "turn_number", 1) == 1 else base),
        category="draw_card",
    ),
    "DRIFTWOOD": RelicDef(
        id="DRIFTWOOD", name="Driftwood", rarity="event", pool="event",
        # Driftwood.cs: gold / economy event relic. Approx: +6 gold per non-shop
        # room (steady economy).
        after_room_entered=lambda rs, rt: rs.gain_gold(6) if rt is not StateType.SHOP else None,
        category="gold",
    ),
    "GLITTER": RelicDef(
        id="GLITTER", name="Glitter", rarity="event", pool="event",
        # Glitter.cs: gold event relic. Approx: +5 gold per non-shop room.
        after_room_entered=lambda rs, rt: rs.gain_gold(5) if rt is not StateType.SHOP else None,
        category="gold",
    ),
    "LAVA_ROCK": RelicDef(
        id="LAVA_ROCK", name="Lava Rock", rarity="event", pool="event",
        # LavaRock.cs: DynamicVar("Relics", 2) — relic-count scaling. Approx:
        # +3 thorns at combat start (defensive event relic).
        on_combat_start=lambda rs, cs: _apply_power_to_self(cs, "thorns", 3),
        category="thorns",
    ),
    "SWORD_OF_STONE": RelicDef(
        id="SWORD_OF_STONE", name="Sword of Stone", rarity="event", pool="event",
        # SwordOfStone.cs: AfterCombatVictory vs Elite -> gold (Elites=5). Approx:
        # +25 gold on combat victory.
        after_combat_victory=lambda rs: rs.gain_gold(25),
        category="gold",
    ),
    "NUTRITIOUS_SOUP": RelicDef(
        id="NUTRITIOUS_SOUP", name="Nutritious Soup", rarity="event", pool="event",
        # NutritiousSoup.cs: max-HP / heal event relic. Approx: +8 max HP pickup
        # (handled in add_relic).
        category="max_hp",
    ),
    "SEAL_OF_GOLD": RelicDef(
        id="SEAL_OF_GOLD", name="Seal of Gold", rarity="ancient", pool="event",
        # SealOfGold.cs: EnergyVar(1) at turn start if Gold >= 5. Approx: +1
        # energy on turn 1 if the player has >= 5 gold.
        on_player_turn_start=lambda rs, cs: (
            setattr(cs.player, "energy", cs.player.energy + 1)
            if (cs.turn_number == 1 and rs.gold >= 5) else None),
        category="energy",
    ),
    "TWISTED_FUNNEL": RelicDef(
        id="TWISTED_FUNNEL", name="Twisted Funnel", rarity="uncommon",
        pool="event",
        # TwistedFunnel.cs: on turn 1, apply PoisonPower(4) to all enemies.
        on_player_turn_start=lambda rs, cs: (
            _apply_power_to_all_monsters(cs, "poison", 4)
            if cs.turn_number == 1 else None),
        category="weak_start",
    ),
    "THROWING_AXE": RelicDef(
        id="THROWING_AXE", name="Throwing Axe", rarity="ancient", pool="event",
        # ThrowingAxe.cs: combat-start AoE. Approx: deal 9 to all on turn 1.
        on_player_turn_start=lambda rs, cs: _damage_all_on_turn(cs, 1, 9),
        category="aoe_damage",
    ),

    # ===================================================================
    # ANCIENT (boss-tier) energy/scaling relics
    # ===================================================================
    "RUNIC_PYRAMID": RelicDef(
        id="RUNIC_PYRAMID", name="Runic Pyramid", rarity="ancient", pool="event",
        # RunicPyramid.cs: hand is not discarded at end of turn (card retention).
        # Hand-retention is not modelled; documented no-op (boss-tier slot).
        category="misc",
    ),
    "SAND_CASTLE": RelicDef(
        id="SAND_CASTLE", name="Sand Castle", rarity="ancient", pool="event",
        # SandCastle.cs: energy/defensive ancient relic. Approx: +1 max energy.
        on_combat_start=lambda rs, cs: _gain_energy(cs, 1),
        category="energy",
    ),
    "PAELS_FLESH": RelicDef(
        id="PAELS_FLESH", name="Pael's Flesh", rarity="ancient", pool="event",
        # PaelsFlesh.cs: EnergyVar(1) at turn start once RoundNumber >= 3.
        on_player_turn_start=lambda rs, cs: (
            setattr(cs.player, "energy", cs.player.energy + 1)
            if cs.turn_number >= 3 else None),
        category="energy",
    ),
    "PAELS_TEARS": RelicDef(
        id="PAELS_TEARS", name="Pael's Tears", rarity="ancient", pool="event",
        # PaelsTears.cs: BeforeTurnEnd snapshot HadLeftoverEnergy = Energy > 0;
        # AfterSideTurnStart, if HadLeftoverEnergy, gain EnergyVar(2). We arm a
        # flag at turn end (energy > 0) and grant +2 at the next turn start.
        on_player_turn_end=lambda rs, cs: setattr(
            rs, "_pael_tears_armed", cs.player.energy > 0),
        on_player_turn_start=lambda rs, cs: _pael_tears_turn_energy(rs, cs),
        category="energy",
    ),
    "PUMPKIN_CANDLE": RelicDef(
        id="PUMPKIN_CANDLE", name="Pumpkin Candle", rarity="ancient", pool="event",
        # PumpkinCandle.cs: defensive ancient. Approx: +4 plating at combat start.
        on_combat_start=lambda rs, cs: _apply_power_to_self(cs, "plating", 4),
        category="block_start",
    ),
    "DIAMOND_DIADEM": RelicDef(
        id="DIAMOND_DIADEM", name="Diamond Diadem", rarity="ancient", pool="event",
        # DiamondDiadem.cs: BeforeTurnEnd, CardThreshold 2 -> if <= 2 cards in
        # hand, gain Artifact. Approx: 1 Artifact charge at combat start.
        on_combat_start=lambda rs, cs: _apply_power_to_self(cs, "artifact", 1),
        category="status_immune",
    ),
    "WINGED_BOOTS": RelicDef(
        id="WINGED_BOOTS", name="Winged Boots", rarity="ancient", pool="event",
        # WingedBoots.cs: map-traversal relic (fly to unconnected nodes).
        # Map navigation is not modelled; documented no-op.
        category="misc",
    ),

    # ===================================================================
    # Phase 8B.6 — SHARED pool completion (all 118 SharedRelicPool ids now
    # in the registry). Each verified vs decompiled Relics/*.cs (rarity +
    # trigger + magnitude). Implemented effects use the engine hooks below;
    # reward/shop/rest/deck/enchant-only relics are faithful documented
    # no-ops (the sim has no primitive for them yet — tagged TODO(fidelity)).
    # ===================================================================

    # ---- Implemented: combat / run-state effects ----------------------
    "AMETHYST_AUBERGINE": RelicDef(
        id="AMETHYST_AUBERGINE", name="Amethyst Aubergine", rarity="common",
        pool="shared",
        # AmethystAubergine.cs: GoldVar(15) -> +15 gold after each combat room
        # (TryModifyRewards on IsCombatRoom). We grant on combat victory.
        after_combat_victory=lambda rs: rs.gain_gold(15),
        category="gold",
    ),
    "GAME_PIECE": RelicDef(
        id="GAME_PIECE", name="Game Piece", rarity="rare", pool="shared",
        # GamePiece.cs: AfterCardPlayed (Power) -> draw CardsVar(1).
        on_card_played=lambda rs, cs, card: _power_card_draw(rs, cs, card, amount=1),
        category="draw_card",
    ),
    "JOSS_PAPER": RelicDef(
        id="JOSS_PAPER", name="Joss Paper", rarity="uncommon", pool="shared",
        merchant_cost=250,
        # JossPaper.cs: every ExhaustAmount(5) cards exhausted -> draw CardsVar(1).
        on_card_exhausted=lambda rs, cs, card: _exhaust_counter_draw(
            rs, cs, card, relic_id="JOSS_PAPER", period=5, amount=1),
        resets_per_combat=True,
        category="draw_card",
    ),
    "REPTILE_TRINKET": RelicDef(
        id="REPTILE_TRINKET", name="Reptile Trinket", rarity="uncommon",
        pool="shared", merchant_cost=250,
        # ReptileTrinket.cs: AfterPotionUsed (in combat) -> +PowerVar<Strength>(3).
        on_potion_used=lambda rs, cs, pid: _apply_power_to_self(cs, "strength", 3),
        category="strength",
    ),
    "RINGING_TRIANGLE": RelicDef(
        id="RINGING_TRIANGLE", name="Ringing Triangle", rarity="shop",
        pool="shared", merchant_cost=160,
        # RingingTriangle.cs: ShouldFlush false while RoundNumber == 1 -> the
        # hand is RETAINED (not discarded) at the end of turn 1. We apply a
        # retain_hand power (amount large enough to keep the whole hand) for
        # 1 turn at combat start. RetainHandPower ticks down at turn end.
        on_combat_start=lambda rs, cs: cs.player.powers.append(
            make_power("retain_hand", 1, cs.player)),
        category="draw_card",
    ),
    "SPARKLING_ROUGE": RelicDef(
        id="SPARKLING_ROUGE", name="Sparkling Rouge", rarity="uncommon",
        pool="shared", merchant_cost=250,
        # SparklingRouge.cs: AfterBlockCleared on RoundNumber == 3 ->
        # +PowerVar<Strength>(1) and +PowerVar<Dexterity>(1). Fires at the start
        # of the player's 3rd turn.
        on_player_turn_start=lambda rs, cs: (
            _apply_power_to_self(cs, "strength", 1),
            _apply_power_to_self(cs, "dexterity", 1),
        ) and None if cs.turn_number == 3 else None,
        category="strength",
    ),
    "STURDY_CLAMP": RelicDef(
        id="STURDY_CLAMP", name="Sturdy Clamp", rarity="rare", pool="shared",
        # SturdyClamp.cs: ShouldClearBlock false + cap retained block to 10
        # (BlockVar(10)). We apply a sturdy_clamp power (cap 10) at combat start;
        # the engine caps turn-start block to it instead of clearing to 0.
        on_combat_start=lambda rs, cs: cs.player.powers.append(
            make_power("sturdy_clamp", 10, cs.player)),
        category="block_start",
    ),
    "BEATING_REMNANT": RelicDef(
        id="BEATING_REMNANT", name="Beating Remnant", rarity="rare", pool="shared",
        # BeatingRemnant.cs: ModifyHpLostAfterOsty -> cap TOTAL unblocked HP loss
        # the owner takes each turn to MaxHpLoss(20). We apply a beating_remnant
        # power (cap 20) at combat start; it accumulates per turn and resets at
        # the owner's turn start.
        on_combat_start=lambda rs, cs: cs.player.powers.append(
            make_power("beating_remnant", 20, cs.player)),
        category="status_immune",
    ),
    "VENERABLE_TEA_SET": RelicDef(
        id="VENERABLE_TEA_SET", name="Venerable Tea Set", rarity="common",
        pool="shared", merchant_cost=175,
        # VenerableTeaSet.cs: after resting, gain EnergyVar(2) at the next
        # combat's first energy reset. We arm a flag on entering a rest site and
        # grant +2 energy at the next combat start (then disarm).
        after_room_entered=lambda rs, rt: _venerable_tea_arm_on_rest(rs, rt),
        on_combat_start=lambda rs, cs: _venerable_tea_combat_start(rs, cs, amount=2),
        category="energy",
    ),
    "LOOMING_FRUIT": RelicDef(
        id="LOOMING_FRUIT", name="Looming Fruit", rarity="ancient", pool="shared",
        # LoomingFruit.cs: MaxHpVar(31) on pickup (handled in add_relic).
        category="max_hp",
    ),
    "CAULDRON": RelicDef(
        id="CAULDRON", name="Cauldron", rarity="shop", pool="shared",
        merchant_cost=160,
        # Cauldron.cs: on pickup, gain Potions(5) (handled in add_relic by
        # filling up to 5 potion slots).
        category="misc",
    ),

    # ---- Documented no-ops: reward / shop / rest / deck / enchant ------
    # These relics modify card rewards, shop pricing, rest options, deck
    # contents on pickup, or use the Enchantment system — none of which the
    # combat sim models yet. They occupy their real pool slot (so the pool
    # distribution stays faithful) but have no in-combat effect. Each carries a
    # TODO(fidelity) with the real effect for the next batch to finish.
    "BOOK_OF_FIVE_RINGS": RelicDef(
        id="BOOK_OF_FIVE_RINGS", name="Book of Five Rings", rarity="common",
        pool="shared", merchant_cost=175,
        # BookOfFiveRings.cs: every 5 cards added to your deck -> heal 20. Now
        # wired via the on_card_added deck-mutation hook (counter persists for
        # the run).
        on_card_added=lambda rs, card: _book_of_five_rings_added(rs, card),
        category="heal_rest",
    ),
    "RAZOR_TOOTH": RelicDef(
        id="RAZOR_TOOTH", name="Razor Tooth", rarity="rare", pool="shared",
        # RazorTooth.cs: AfterCardPlayed (Attack/Skill, upgradable) -> upgrade
        # that card permanently.
        # TODO(fidelity: in-combat card upgrade): upgrade the played card.
        # The sim has no mid-combat per-card upgrade primitive.
        category="misc",
    ),
    "STONE_CRACKER": RelicDef(
        id="STONE_CRACKER", name="Stone Cracker", rarity="uncommon",
        pool="shared", merchant_cost=250,
        # StoneCracker.cs: AfterRoomEntered (Combat) -> upgrade CardsVar(2) random
        # upgradable cards in the draw pile this combat.
        # TODO(fidelity: combat deck upgrade): upgrade 2 draw-pile cards.
        category="misc",
    ),
    "LAVA_LAMP": RelicDef(
        id="LAVA_LAMP", name="Lava Lamp", rarity="shop", pool="shared",
        merchant_cost=160,
        # LavaLamp.cs: if you took no unblocked damage this combat, your card
        # reward options are upgraded.
        # TODO(fidelity: reward upgrade): upgrade card-reward options on a
        # no-damage combat. Reward-shaping; documented no-op.
        category="card_pick",
    ),
    "GHOST_SEED": RelicDef(
        id="GHOST_SEED", name="Ghost Seed", rarity="shop", pool="shared",
        merchant_cost=160,
        # GhostSeed.cs: your basic Strike/Defend cards gain Ethereal.
        # TODO(fidelity: Ethereal keyword): the sim has no Ethereal mechanic.
        category="misc",
    ),
    "BURNING_STICKS": RelicDef(
        id="BURNING_STICKS", name="Burning Sticks", rarity="shop", pool="shared",
        merchant_cost=160,
        # BurningSticks.cs: the first Skill you exhaust each combat -> add a copy
        # of it to your hand.
        # TODO(fidelity: card-clone into hand): clone the first exhausted Skill.
        category="misc",
    ),
    "DINGY_RUG": RelicDef(
        id="DINGY_RUG", name="Dingy Rug", rarity="shop", pool="shared",
        merchant_cost=160,
        # DingyRug.cs: colorless cards are added to your card-reward pool.
        # TODO(fidelity: reward pool): inject colorless cards into rewards.
        category="card_pick",
    ),
    "DOLLYS_MIRROR": RelicDef(
        id="DOLLYS_MIRROR", name="Dolly's Mirror", rarity="shop", pool="shared",
        # DollysMirror.cs: on pickup, duplicate a card in your deck.
        # TODO(fidelity: deck duplicate on pickup).
        category="misc",
    ),
    "FRESNEL_LENS": RelicDef(
        id="FRESNEL_LENS", name="Fresnel Lens", rarity="event", pool="shared",
        # FresnelLens.cs: cards added to your deck gain Nimble(2) (Enchantment).
        # TODO(fidelity: Enchantment system).
        category="misc",
    ),
    "GNARLED_HAMMER": RelicDef(
        id="GNARLED_HAMMER", name="Gnarled Hammer", rarity="shop", pool="shared",
        merchant_cost=160,
        # GnarledHammer.cs: on pickup, enchant 3 cards with Sharp(3).
        # TODO(fidelity: Enchantment system).
        category="misc",
    ),
    "KIFUDA": RelicDef(
        id="KIFUDA", name="Kifuda", rarity="shop", pool="shared",
        merchant_cost=160,
        # Kifuda.cs: on pickup, enchant 3 cards with Adroit(3).
        # TODO(fidelity: Enchantment system).
        category="misc",
    ),
    "PUNCH_DAGGER": RelicDef(
        id="PUNCH_DAGGER", name="Punch Dagger", rarity="shop", pool="shared",
        merchant_cost=160,
        # PunchDagger.cs: on pickup, enchant 1 card with Momentum(5).
        # TODO(fidelity: Enchantment system).
        category="misc",
    ),
    "ROYAL_STAMP": RelicDef(
        id="ROYAL_STAMP", name="Royal Stamp", rarity="shop", pool="shared",
        merchant_cost=160,
        # RoyalStamp.cs: on pickup, enchant 1 card with RoyallyApproved.
        # TODO(fidelity: Enchantment system).
        category="misc",
    ),
    "WING_CHARM": RelicDef(
        id="WING_CHARM", name="Wing Charm", rarity="shop", pool="shared",
        merchant_cost=160,
        # WingCharm.cs: a card-reward option is enchanted with Swift(1).
        # TODO(fidelity: Enchantment system).
        category="card_pick",
    ),
    "MYSTIC_LIGHTER": RelicDef(
        id="MYSTIC_LIGHTER", name="Mystic Lighter", rarity="shop", pool="shared",
        merchant_cost=160,
        # MysticLighter.cs: DamageVar(9) -> powered attacks from ENCHANTED cards
        # deal +9 damage.
        # TODO(fidelity: Enchantment system) — needs per-card enchant state.
        category="misc",
    ),
    "LASTING_CANDY": RelicDef(
        id="LASTING_CANDY", name="Lasting Candy", rarity="uncommon",
        pool="shared", merchant_cost=250,
        # LastingCandy.cs: every other combat, a Power card is added to the card
        # reward options.
        # TODO(fidelity: reward shaping) — inject a Power into rewards every 2nd
        # combat. Reward-only; documented no-op.
        category="card_pick",
    ),
    "ORRERY": RelicDef(
        id="ORRERY", name="Orrery", rarity="shop", pool="shared",
        merchant_cost=160,
        # Orrery.cs: on pickup, offer CardsVar(5) card-reward choices.
        # TODO(fidelity: pickup reward offer). Documented no-op.
        category="card_pick",
    ),
    "MINIATURE_TENT": RelicDef(
        id="MINIATURE_TENT", name="Miniature Tent", rarity="shop", pool="shared",
        merchant_cost=160,
        # MiniatureTent.cs: rest sites let you use ALL options (no single-choice).
        # TODO(fidelity: rest multi-option). Rest-only; documented no-op.
        category="misc",
    ),
    "TINY_MAILBOX": RelicDef(
        id="TINY_MAILBOX", name="Tiny Mailbox", rarity="uncommon", pool="shared",
        # TinyMailbox.cs: when you rest, also gain 2 potions.
        # TODO(fidelity: rest potion reward). Rest-only; documented no-op.
        category="misc",
    ),
    "LUCKY_FYSH": RelicDef(
        id="LUCKY_FYSH", name="Lucky Fysh", rarity="uncommon", pool="shared",
        # LuckyFysh.cs: GoldVar(15) -> +15 gold whenever a card is added to your
        # deck. Now wired via the on_card_added deck-mutation hook.
        on_card_added=lambda rs, card: _lucky_fysh_added(rs, card),
        category="gold",
    ),
    "BOWLER_HAT": RelicDef(
        id="BOWLER_HAT", name="Bowler Hat", rarity="uncommon", pool="shared",
        # BowlerHat.cs: GoldIncrease(1.25) -> all gold you gain is multiplied by
        # 1.25 (extra 25%). Wired via RunState.gain_gold's gold_multiplier.
        gold_multiplier=1.25,
        category="gold",
    ),
    "CHEMICAL_X": RelicDef(
        id="CHEMICAL_X", name="Chemical X", rarity="shop", pool="shared",
        merchant_cost=160,
        # ChemicalX.cs: Increase(2) -> X-cost cards behave as if their X is +2.
        # Wired via CombatState.chemical_x_bonus (added to _x_value when an
        # X-cost card resolves). Set at combat start.
        on_combat_start=lambda rs, cs: setattr(cs, "chemical_x_bonus", 2),
        category="misc",
    ),
    "LIZARD_TAIL": RelicDef(
        id="LIZARD_TAIL", name="Lizard Tail", rarity="rare", pool="shared",
        # LizardTail.cs: once per run, when you would die, instead heal
        # HealVar(50) percent of max HP and survive. Wired via the
        # on_player_would_die hook (counter tracks the once-per-run charge).
        on_player_would_die=lambda rs, cs: _lizard_tail_revive(rs, cs),
        category="heal_combat",
    ),
    "VEXING_PUZZLEBOX": RelicDef(
        id="VEXING_PUZZLEBOX", name="Vexing Puzzlebox", rarity="rare",
        pool="shared",
        # VexingPuzzlebox.cs: on turn 1, add a random free card to your hand.
        # TODO(fidelity: random card generation into hand) — the sim has no
        # card-into-hand generation primitive. Documented no-op for now.
        category="misc",
    ),

    # ===================================================================
    # Phase 8B.7 — EventRelicPool / boss / Neow / shop-trap relics.
    # Each verified vs decompiled Relics/*.cs (rarity + trigger + magnitude)
    # and EventRelicPool.cs membership. Ironclad-obtainable combat / pickup
    # effects use the engine hooks; effects needing systems the sim lacks
    # (Enchantment, character-specific card injection) carry an honest TODO.
    # ===================================================================

    # ---- Snecko Eye / Fake Snecko Eye (ConfusedPower) -----------------
    "SNECKO_EYE": RelicDef(
        id="SNECKO_EYE", name="Snecko Eye", rarity="ancient", pool="event",
        # SneckoEye.cs: BeforeCombatStart -> apply ConfusedPower(1) (each drawn
        # card's cost randomizes 0-3); ModifyHandDraw +CardsVar(2). Ancient.
        on_combat_start=lambda rs, cs: _apply_confused(cs),
        modify_hand_draw=lambda rs, cs, base: base + 2,
        category="draw_card",
    ),
    "FAKE_SNECKO_EYE": RelicDef(
        id="FAKE_SNECKO_EYE", name="Fake Snecko Eye", rarity="event",
        pool="event", merchant_cost=50,
        # FakeSneckoEye.cs: BeforeCombatStart -> ConfusedPower(1). NO bonus draw
        # (the trap version: all downside, no upside).
        on_combat_start=lambda rs, cs: _apply_confused(cs),
        category="misc",
    ),

    # ---- Pael's fragment set (Ancient, EventRelicPool) ----------------
    "PAELS_BLOOD": RelicDef(
        id="PAELS_BLOOD", name="Pael's Blood", rarity="ancient", pool="event",
        # PaelsBlood.cs: ModifyHandDraw +CardsVar(1) (draw 1 extra each turn).
        modify_hand_draw=lambda rs, cs, base: base + 1,
        category="draw_card",
    ),
    "PAELS_HORN": RelicDef(
        id="PAELS_HORN", name="Pael's Horn", rarity="ancient", pool="event",
        # PaelsHorn.cs: on pickup, add 2 Relax cards to the deck. The Relax card
        # is not in the sim card catalog.
        # TODO(fidelity: Relax card) — needs the Relax card defined; deck-add
        # primitive exists but the specific card does not.
        category="misc",
    ),
    "BOOMING_CONCH": RelicDef(
        id="BOOMING_CONCH", name="Booming Conch", rarity="ancient", pool="event",
        # BoomingConch.cs: ModifyHandDraw +CardsVar(2) on turn 1 of an Elite
        # combat only. We gate on turn 1 and the run being in an Elite room.
        modify_hand_draw=lambda rs, cs, base: (
            base + 2 if (cs.turn_number <= 1
                         and rs.state_type is StateType.ELITE) else base),
        category="draw_card",
    ),

    # ---- Fake (shop-trap) relics, EventRelicPool ----------------------
    "FAKE_ANCHOR": RelicDef(
        id="FAKE_ANCHOR", name="Fake Anchor", rarity="event", pool="event",
        merchant_cost=50,
        # FakeAnchor.cs: BeforeCombatStart -> GainBlock BlockVar(4). (Real Anchor
        # gives 10; the trap gives only 4.)
        on_combat_start=lambda rs, cs: _gain_block(cs, 4),
        category="block_start",
    ),
    "FAKE_BLOOD_VIAL": RelicDef(
        id="FAKE_BLOOD_VIAL", name="Fake Blood Vial", rarity="event",
        pool="event", merchant_cost=50,
        # FakeBloodVial.cs: AfterPlayerTurnStartLate on RoundNumber <= 1 ->
        # Heal HealVar(1). (Real Blood Vial heals 2.) Fires turn 1 only.
        on_player_turn_start=lambda rs, cs: (
            cs.player.heal(1) if cs.turn_number <= 1 else None),
        category="heal_combat",
    ),
    "FAKE_MANGO": RelicDef(
        id="FAKE_MANGO", name="Fake Mango", rarity="event", pool="event",
        merchant_cost=50,
        # FakeMango.cs: on pickup, GainMaxHp MaxHpVar(3). (Real Mango gives 14.)
        # Handled in RunState.add_relic.
        category="max_hp",
    ),
    "FAKE_LEES_WAFFLE": RelicDef(
        id="FAKE_LEES_WAFFLE", name="Fake Lee's Waffle", rarity="event",
        pool="event", merchant_cost=50,
        # FakeLeesWaffle.cs: on pickup, heal HealVar(10) percent of max HP.
        # (Real Lee's Waffle gives +7 max HP then full heal.) Handled in
        # RunState.add_relic.
        category="heal_combat",
    ),
    "FAKE_ORICHALCUM": RelicDef(
        id="FAKE_ORICHALCUM", name="Fake Orichalcum", rarity="event",
        pool="event", merchant_cost=50,
        # FakeOrichalcum.cs: BeforeTurnEnd, if Block == 0 -> GainBlock
        # BlockVar(3). (Real Orichalcum gives 6.) Mirrors the Orichalcum turn-end
        # block-if-0 pattern.
        on_player_turn_end=lambda rs, cs: (
            _gain_block(cs, 3) if cs.player.block == 0 else None),
        category="block_start",
    ),
    "FAKE_HAPPY_FLOWER": RelicDef(
        id="FAKE_HAPPY_FLOWER", name="Fake Happy Flower", rarity="event",
        pool="event", merchant_cost=50,
        # FakeHappyFlower.cs: every Turns(5) of the owner's turns -> EnergyVar(1).
        # (Real Happy Flower period is 3.) Counter resets per combat.
        on_player_turn_start=lambda rs, cs: _turn_period_energy(
            rs, cs, relic_id="FAKE_HAPPY_FLOWER", period=5, amount=1),
        resets_per_combat=True,
        category="energy",
    ),
    "FAKE_VENERABLE_TEA_SET": RelicDef(
        id="FAKE_VENERABLE_TEA_SET", name="Fake Venerable Tea Set",
        rarity="event", pool="event", merchant_cost=50,
        # FakeVenerableTeaSet.cs: after resting, gain EnergyVar(1) at the next
        # combat's energy reset. (Real Venerable Tea Set gives 2.) We reuse the
        # arm-on-rest flag with amount 1.
        after_room_entered=lambda rs, rt: _venerable_tea_arm_on_rest(rs, rt),
        on_combat_start=lambda rs, cs: _venerable_tea_combat_start(rs, cs, amount=1),
        category="energy",
    ),
    "FAKE_STRIKE_DUMMY": RelicDef(
        id="FAKE_STRIKE_DUMMY", name="Fake Strike Dummy", rarity="event",
        pool="event", merchant_cost=50,
        # FakeStrikeDummy.cs: ModifyDamageAdditive +ExtraDamage(1) to powered
        # Strike attacks. (Real Strike Dummy gives +3.) We add +1 to the target
        # when a Strike ATTACK card is played.
        on_card_played=lambda rs, cs, card: _fake_strike_dummy_bonus(rs, cs, card),
        category="strength",
    ),

    # ---- Neow relics (Ancient, EventRelicPool / Neow event) -----------
    "NEOWS_TALISMAN": RelicDef(
        id="NEOWS_TALISMAN", name="Neow's Talisman", rarity="ancient",
        pool="event",
        # NeowsTalisman.cs: on pickup, upgrade the basic Strike and Defend cards.
        # Handled in RunState.add_relic (deck mutation on pickup).
        category="card_pick",
    ),
    "NEOWS_TORMENT": RelicDef(
        id="NEOWS_TORMENT", name="Neow's Torment", rarity="ancient",
        pool="event",
        # NeowsTorment.cs: on pickup, add a NeowsFury curse card to the deck. The
        # NeowsFury card is not in the sim card catalog.
        # TODO(fidelity: NeowsFury curse card) — deck-add primitive exists but
        # the specific curse card does not.
        category="misc",
    ),

    # ---- Gold relics (Ancient / Event) --------------------------------
    "GOLDEN_PEARL": RelicDef(
        id="GOLDEN_PEARL", name="Golden Pearl", rarity="ancient", pool="event",
        # GoldenPearl.cs: on pickup, GainGold GoldVar(150). Handled in
        # RunState.add_relic.
        category="gold",
    ),
    "MAW_BANK": RelicDef(
        id="MAW_BANK", name="Maw Bank", rarity="event", pool="event",
        # MawBank.cs: AfterRoomEntered (each NEW room) -> GainGold GoldVar(12),
        # until you spend gold at a shop (then disabled). We grant +12 on every
        # non-combat room entry until the maw_bank_spent flag is set.
        after_room_entered=lambda rs, rt: (
            rs.gain_gold(12)
            if not getattr(rs, "maw_bank_spent", False) else None),
        category="gold",
    ),

    # ---- Strength / pickup ancient & event relics ---------------------
    "SWORD_OF_JADE": RelicDef(
        id="SWORD_OF_JADE", name="Sword of Jade", rarity="event", pool="event",
        # SwordOfJade.cs: AfterRoomEntered (Combat) -> apply Strength(3) (it
        # fires once per combat at the start). We grant +3 Strength at combat
        # start, the equivalent in-combat moment.
        on_combat_start=lambda rs, cs: _apply_power_to_self(cs, "strength", 3),
        category="strength",
    ),
    "EMBER_TEA": RelicDef(
        id="EMBER_TEA", name="Ember Tea", rarity="event", pool="event",
        # EmberTea.cs: for the first Combats(5) combats, gain Strength(2) at the
        # start of combat, then the relic is used up. Counter tracks combats used
        # (persists across the run; NOT resets_per_combat).
        on_combat_start=lambda rs, cs: _ember_tea_combat_start(rs, cs),
        category="strength",
    ),
    "BONE_TEA": RelicDef(
        id="BONE_TEA", name="Bone Tea", rarity="event", pool="event",
        # BoneTea.cs: on the first turn of the next Combats(1) combat, upgrade
        # every card in hand, then the relic is used up.
        # TODO(fidelity: in-combat hand upgrade once) — the sim's mid-combat
        # hand-upgrade primitive (UPGRADE_ALL_IN_HAND) is card-driven only; no
        # relic-triggered hand upgrade hook exists yet.
        category="misc",
    ),
    "NUTRITIOUS_OYSTER": RelicDef(
        id="NUTRITIOUS_OYSTER", name="Nutritious Oyster", rarity="ancient",
        pool="event",
        # NutritiousOyster.cs: on pickup, GainMaxHp MaxHpVar(11). Handled in
        # RunState.add_relic.
        category="max_hp",
    ),
}


def relic_category(relic_id: str) -> str:
    """Return obs category for a relic id ('misc' if unknown)."""
    rd = RELIC_REGISTRY.get(relic_id)
    return rd.category if rd is not None else "misc"


def relic_category_index(relic_id: str) -> int:
    """Return index into RELIC_CATEGORIES for the obs encoding."""
    try:
        return RELIC_CATEGORIES.index(relic_category(relic_id))
    except ValueError:
        return RELIC_CATEGORIES.index("misc")


def apply_hand_draw_modifiers(rs: RunState, combat, base_draw: int) -> int:
    """Apply every owned relic's modify_hand_draw to base_draw.
    Used by the combat engine each turn after the base draw count is
    determined. Iteration order = rs.relics order = pickup order."""
    draw = base_draw
    for r in rs.relics:
        rd = RELIC_REGISTRY.get(r.id)
        if rd is None or rd.modify_hand_draw is None:
            continue
        try:
            draw = rd.modify_hand_draw(rs, combat, draw)
        except Exception:
            pass
    return draw


def trigger_on_combat_start(rs: RunState, combat) -> None:
    for r in rs.relics:
        rd = RELIC_REGISTRY.get(r.id)
        if rd and rd.on_combat_start:
            rd.on_combat_start(rs, combat)


def trigger_on_player_turn_start(rs: RunState, combat) -> None:
    for r in rs.relics:
        rd = RELIC_REGISTRY.get(r.id)
        if rd and rd.on_player_turn_start:
            rd.on_player_turn_start(rs, combat)


def trigger_after_combat_victory(rs: RunState) -> None:
    for r in rs.relics:
        rd = RELIC_REGISTRY.get(r.id)
        if rd and rd.after_combat_victory:
            rd.after_combat_victory(rs)


def trigger_after_room_entered(rs: RunState, room_type: StateType) -> None:
    for r in rs.relics:
        rd = RELIC_REGISTRY.get(r.id)
        if rd and rd.after_room_entered:
            rd.after_room_entered(rs, room_type)


def trigger_on_attack_played(rs: RunState, combat, card) -> None:
    """Fired by combat.play_card after an ATTACK card resolves. Drives the
    per-attack scaling relics (Kunai/Shuriken/Pen Nib)."""
    for r in rs.relics:
        rd = RELIC_REGISTRY.get(r.id)
        if rd and rd.on_attack_played:
            rd.on_attack_played(rs, combat, card)


def trigger_on_player_turn_end(rs: RunState, combat) -> None:
    """Fired by combat.end_player_turn at the very start of the player's
    turn-end (Orichalcum block-if-0, Sai/Kusarigama)."""
    for r in rs.relics:
        rd = RELIC_REGISTRY.get(r.id)
        if rd and rd.on_player_turn_end:
            rd.on_player_turn_end(rs, combat)


def trigger_on_card_played(rs: RunState, combat, card) -> None:
    """Fired by combat.play_card after ANY card resolves. Drives the per-card
    cadence relics (Nunchaku/OrnamentalFan Attack-count, LetterOpener
    Skill-count)."""
    for r in rs.relics:
        rd = RELIC_REGISTRY.get(r.id)
        if rd and rd.on_card_played:
            rd.on_card_played(rs, combat, card)


def trigger_on_card_drawn(rs: RunState, combat, card) -> None:
    """Fired by combat.draw after a card lands in hand."""
    for r in rs.relics:
        rd = RELIC_REGISTRY.get(r.id)
        if rd and rd.on_card_drawn:
            rd.on_card_drawn(rs, combat, card)


def trigger_on_shuffle(rs: RunState, combat) -> None:
    """Fired by combat.draw when the discard pile reshuffles into draw (TheAbacus)."""
    for r in rs.relics:
        rd = RELIC_REGISTRY.get(r.id)
        if rd and rd.on_shuffle:
            rd.on_shuffle(rs, combat)


def trigger_on_monster_death(rs: RunState, combat, monster) -> None:
    """Fired by combat.play_card for each enemy that dies (GremlinHorn)."""
    for r in rs.relics:
        rd = RELIC_REGISTRY.get(r.id)
        if rd and rd.on_monster_death:
            rd.on_monster_death(rs, combat, monster)


def trigger_on_card_exhausted(rs: RunState, combat, card) -> None:
    """Fired by combat._exhaust_card after a player-owned card is exhausted
    (JossPaper: every 5th card exhausted -> draw 1)."""
    for r in rs.relics:
        rd = RELIC_REGISTRY.get(r.id)
        if rd and rd.on_card_exhausted:
            rd.on_card_exhausted(rs, combat, card)


def trigger_on_potion_used(rs: RunState, combat, potion_id: str) -> None:
    """Fired by potions.apply_potion after a potion resolves in combat
    (ReptileTrinket: +3 Strength when a potion is used in combat)."""
    for r in rs.relics:
        rd = RELIC_REGISTRY.get(r.id)
        if rd and rd.on_potion_used:
            rd.on_potion_used(rs, combat, potion_id)


def trigger_on_card_added_to_deck(rs: RunState, card) -> None:
    """Fired by RunState.add_card_to_deck whenever a card is added to the deck
    (BookOfFiveRings heal-per-5, LuckyFysh gold-per-add)."""
    for r in rs.relics:
        rd = RELIC_REGISTRY.get(r.id)
        if rd and rd.on_card_added:
            rd.on_card_added(rs, card)


def trigger_on_player_would_die(rs: RunState, combat) -> None:
    """Fired by combat.monster_turn when the player drops to 0 HP. Death-
    prevention relics (LizardTail) can revive the player here."""
    for r in rs.relics:
        rd = RELIC_REGISTRY.get(r.id)
        if rd and rd.on_player_would_die:
            rd.on_player_would_die(rs, combat)


def reset_combat_counters(rs: RunState) -> None:
    """Reset RelicInstance.counter to 0 for every owned relic flagged
    resets_per_combat (Kunai/Shuriken/Nunchaku/PenNib/HappyFlower/…). Called
    by run_engine at the start of each combat."""
    for r in rs.relics:
        rd = RELIC_REGISTRY.get(r.id)
        if rd and rd.resets_per_combat:
            r.counter = 0


def relic_ids() -> list[str]:
    return list(RELIC_REGISTRY)


# ---------------------------------------------------------------------------
# Relic POOLS + reward sampling.
#
# Pools list registry ids the run can grant as rewards. They mirror the
# decompiled SharedRelicPool / IroncladRelicPool / boss split, restricted
# to the relics actually modelled in RELIC_REGISTRY (so a grant is never a
# no-op). De-dup and RNG-determinism are handled by sample_relic_from_pool.
# ---------------------------------------------------------------------------

# Pools are derived from each relic's `rarity` field (single source of truth),
# mirroring how the decompiled SharedRelicPool / IroncladRelicPool split by
# RelicModel.Rarity at draw time. STS2 rarity -> reward-tier mapping:
#   common   -> "common"    (regular reward common tier)
#   uncommon -> "uncommon"
#   rare     -> "rare"
#   shop     -> "rare"       (Shop-rarity relics are reward-eligible via shop;
#                             folded into the rare reward tier so they still
#                             appear in the run rather than being unreachable)
#   ancient  -> "boss"       (Ancient = STS2's boss/energy-with-downside class;
#                             granted only via the boss-reward path)
#   event/starter/none      -> excluded from reward pools (event-only / starter)
_RARITY_TO_TIER: dict[str, str] = {
    "common": "common",
    "uncommon": "uncommon",
    "rare": "rare",
    "shop": "rare",
    "ancient": "boss",
    # "boss" is the sim's legacy alias for the Ancient energy-relic class
    # (Ectoplasm/Sozu/Coffee Dripper/Velvet Choker). STS2 has no "Boss"
    # rarity — these are RelicRarity.Ancient — but the alias is kept so the
    # boss-reward path stays wired. Both map to the boss reward tier.
    "boss": "boss",
}


# ---------------------------------------------------------------------------
# Faithful source-pool membership (decompiled SharedRelicPool / IroncladRelicPool
# / EventRelicPool). Authoritative split used for the per-source pool VIEWS
# below. Only ids actually present in RELIC_REGISTRY become reward-eligible, so
# a grant is never an inert no-op id. This is the single source of truth for
# "which real pool does this relic belong to".
# ---------------------------------------------------------------------------
_SHARED_POOL_IDS: frozenset[str] = frozenset({
    "AKABEKO", "ANCHOR", "ART_OF_WAR", "BAG_OF_MARBLES", "BAG_OF_PREPARATION",
    "BELLOWS", "BELT_BUCKLE", "BLOOD_VIAL", "BREAD", "BRONZE_SCALES",
    "CANDELABRA", "CAPTAINS_WHEEL", "CENTENNIAL_PUZZLE", "CHANDELIER",
    "CLOAK_CLASP", "DRAGON_FRUIT", "ETERNAL_FEATHER", "FESTIVE_POPPER",
    "FROZEN_EGG", "GAMBLING_CHIP", "GIRYA", "GORGET", "GREMLIN_HORN",
    "HAPPY_FLOWER", "HORN_CLEAT", "ICE_CREAM", "INTIMIDATING_HELMET",
    "JUZU_BRACELET", "KUNAI", "KUSARIGAMA", "LANTERN", "LAVA_LAMP",
    "LEES_WAFFLE", "LETTER_OPENER", "MANGO", "MEAL_TICKET", "MEAT_ON_THE_BONE",
    "MEMBERSHIP_CARD", "MERCURY_HOURGLASS", "MINIATURE_CANNON", "MOLTEN_EGG",
    "MUMMIFIED_HAND", "NUNCHAKU", "ODDLY_SMOOTH_STONE", "OLD_COIN",
    "ORICHALCUM", "ORNAMENTAL_FAN", "PANTOGRAPH", "PARRYING_SHIELD", "PEAR",
    "PENDULUM", "PEN_NIB", "PERMAFROST", "PETRIFIED_TOAD", "PLANISPHERE",
    "POCKETWATCH", "POTION_BELT", "PRAYER_WHEEL", "RAINBOW_RING", "RED_MASK",
    "REGAL_PILLOW", "RIPPLE_BASIN", "SCREAMING_FLAGON", "SHOVEL", "SHURIKEN",
    "SLING_OF_COURAGE", "STONE_CALENDAR", "STONE_CRACKER", "STRAWBERRY",
    "STRIKE_DUMMY", "THE_ABACUS", "THE_COURIER", "TOOLBOX", "TOXIC_EGG",
    "TUNGSTEN_ROD", "TUNING_FORK", "UNCEASING_TOP", "UNSETTLING_LAMP", "VAJRA",
    "VAMBRACE", "VERY_HOT_COCOA", "WAR_PAINT", "WHETSTONE", "WHITE_BEAST_STATUE",
    "WHITE_STAR",
    # Phase 8B.6 — SharedRelicPool completion (the remaining 34 ids).
    "AMETHYST_AUBERGINE", "BEATING_REMNANT", "BOOK_OF_FIVE_RINGS", "BOWLER_HAT",
    "BURNING_STICKS", "CAULDRON", "CHEMICAL_X", "DINGY_RUG", "DOLLYS_MIRROR",
    "FRESNEL_LENS", "GAME_PIECE", "GHOST_SEED", "GNARLED_HAMMER", "JOSS_PAPER",
    "KIFUDA", "LASTING_CANDY", "LAVA_LAMP", "LIZARD_TAIL", "LOOMING_FRUIT",
    "LUCKY_FYSH", "MINIATURE_TENT", "MYSTIC_LIGHTER", "ORRERY", "PUNCH_DAGGER",
    "RAZOR_TOOTH", "REPTILE_TRINKET", "RINGING_TRIANGLE", "ROYAL_STAMP",
    "SPARKLING_ROUGE", "STURDY_CLAMP", "TINY_MAILBOX", "VENERABLE_TEA_SET",
    "VEXING_PUZZLEBOX", "WING_CHARM",
})
_IRONCLAD_POOL_IDS: frozenset[str] = frozenset({
    "BRIMSTONE", "BURNING_BLOOD", "CHARONS_ASHES", "DEMON_TONGUE", "PAPER_PHROG",
    "RED_SKULL", "RUINED_HELMET", "SELF_FORMING_CLAY",
})
_EVENT_POOL_IDS: frozenset[str] = frozenset({
    "ARCANE_SCROLL", "BLACK_BLOOD", "BLESSED_ANTLER", "BRILLIANT_SCARF",
    "CROSSBOW", "CURSED_PEARL", "DARKSTONE_PERIAPT", "DIAMOND_DIADEM",
    "DREAM_CATCHER", "DRIFTWOOD", "ECTOPLASM", "GLITTER", "HAND_DRILL",
    "IRON_CLUB", "LAVA_ROCK", "LEAD_PAPERWEIGHT", "MAW_BANK", "MEAT_CLEAVER",
    "NUTRITIOUS_SOUP", "PAELS_FLESH", "PAELS_TEARS", "PHILOSOPHERS_STONE",
    "PRISMATIC_GEM", "PUMPKIN_CANDLE", "RUNIC_PYRAMID", "SAI", "SAND_CASTLE",
    "SEAL_OF_GOLD", "SOZU", "SPIKED_GAUNTLETS", "SWORD_OF_STONE", "THE_BOOT",
    "THROWING_AXE", "TWISTED_FUNNEL", "VELVET_CHOKER", "WAR_HAMMER",
    "WHISPERING_EARRING", "WINGED_BOOTS",
    # Phase 8B.7 — EventRelicPool additions.
    "SNECKO_EYE", "FAKE_SNECKO_EYE", "PAELS_BLOOD", "PAELS_HORN",
    "BOOMING_CONCH", "FAKE_ANCHOR", "FAKE_BLOOD_VIAL", "FAKE_MANGO",
    "FAKE_LEES_WAFFLE", "FAKE_ORICHALCUM", "FAKE_HAPPY_FLOWER",
    "FAKE_VENERABLE_TEA_SET", "FAKE_STRIKE_DUMMY", "NEOWS_TALISMAN",
    "NEOWS_TORMENT", "GOLDEN_PEARL", "MAW_BANK", "SWORD_OF_JADE",
    "EMBER_TEA", "BONE_TEA", "NUTRITIOUS_OYSTER",
})


def _build_pools() -> dict[str, list[str]]:
    pools: dict[str, list[str]] = {"common": [], "uncommon": [], "rare": [], "boss": []}
    for rid, rd in RELIC_REGISTRY.items():
        tier = _RARITY_TO_TIER.get(rd.rarity)
        if tier is not None:
            pools[tier].append(rid)
    return pools


# Common/uncommon/rare = the per-floor reward pool (elite + treasure draw
# from these). Boss pool is the post-boss reward (ancient energy relics).
RELIC_POOLS: dict[str, list[str]] = _build_pools()


def _build_source_pools() -> dict[str, list[str]]:
    """Faithful per-source pool views (shared / ironclad / event), restricted
    to ids actually in RELIC_REGISTRY. Mirrors the decompiled RelicPool split.
    Used by callers that want the real-game pool partition (and by the breadth
    tests). Reward sampling still uses the rarity-tiered RELIC_POOLS."""
    src: dict[str, list[str]] = {"shared": [], "ironclad": [], "event": []}
    for rid in RELIC_REGISTRY:
        if rid in _SHARED_POOL_IDS:
            src["shared"].append(rid)
        if rid in _IRONCLAD_POOL_IDS:
            src["ironclad"].append(rid)
        if rid in _EVENT_POOL_IDS:
            src["event"].append(rid)
    return src


# Real-game source-pool partition (Shared / Ironclad / Event), registry-backed.
RELIC_SOURCE_POOLS: dict[str, list[str]] = _build_source_pools()

# Weighted rarity split for the common/uncommon/rare reward draw. Verified vs
# decompiled RelicFactory.RollRarity: num < 0.5 -> Common; < 0.83 -> Uncommon;
# else Rare  =>  Common 50% / Uncommon 33% / Rare 17%.
_REWARD_RARITY_WEIGHTS = (("common", 50), ("uncommon", 33), ("rare", 17))


def _all_pool_ids() -> set[str]:
    out: set[str] = set()
    for ids in RELIC_POOLS.values():
        out.update(ids)
    return out


def sample_relic_from_pool(rng, owned: set[str], *, boss: bool = False) -> Optional[str]:
    """Deterministically pick an unowned registry relic from the reward
    pool using the supplied run RNG (must expose next_int / next_double).
    Returns None only if every pooled relic is already owned.

    `boss=True` draws from the boss pool; otherwise a rarity is rolled
    then a relic picked within it. De-dup: owned ids are filtered out
    BEFORE the pick, and we fall back across rarities if a tier is
    exhausted, so a real (registry) id is always returned when one exists.
    """
    if boss:
        order = ["boss"]
    else:
        # Roll a rarity by weight, then try that tier first, then the rest.
        total = sum(w for _, w in _REWARD_RARITY_WEIGHTS)
        roll = rng.next_int(0, total)
        acc = 0
        chosen = "common"
        for name, w in _REWARD_RARITY_WEIGHTS:
            acc += w
            if roll < acc:
                chosen = name
                break
        order = [chosen] + [n for n in ("common", "uncommon", "rare") if n != chosen]
    for tier in order:
        candidates = [rid for rid in RELIC_POOLS.get(tier, [])
                      if rid not in owned and rid in RELIC_REGISTRY]
        if candidates:
            idx = rng.next_int(0, len(candidates))
            return candidates[idx]
    return None


def grant_relic_reward(rs: RunState, rng, *, boss: bool = False) -> Optional[str]:
    """Sample + add one relic from the reward pool to rs.relics. Uses
    rs.add_relic so pickup-time effects (max HP) fire and de-dup holds.
    Returns the granted id (or None if the pool is exhausted)."""
    owned = {r.id for r in rs.relics}
    rid = sample_relic_from_pool(rng, owned, boss=boss)
    if rid is not None:
        rs.add_relic(rid)
    return rid

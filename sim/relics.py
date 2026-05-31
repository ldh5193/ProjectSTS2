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
    # If True, the relic's RelicInstance.counter is reset to 0 at the start of
    # each combat (decompiled per-combat counters: Kunai/Shuriken/Nunchaku/…).
    resets_per_combat: bool = False
    # Obs category — see RELIC_CATEGORIES above.
    category: str = "misc"


def _gain_block(combat, amount: int) -> None:
    combat.player.block += amount


def _apply_power_to_self(combat, power_id: str, amount: int) -> None:
    combat.player.add_or_stack_power(make_power(power_id, amount, combat.player))


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
    """Deal `amount` unblockable-by-block damage to every alive monster
    (LetterOpener, Kusarigama). Uses the standard damage pipeline so Thorns/
    block still apply, matching CreatureCmd.Damage(HittableEnemies, ...)."""
    from .damage import deal_damage
    for m in list(cs.alive_monsters()):
        if m.alive:
            deal_damage(amount, cs.player, m)


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
        on_combat_start=lambda rs, cs: _apply_power_to_self(cs, "strength", 1),
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
    "MAW_BANK": RelicDef(
        id="MAW_BANK", name="Maw Bank", rarity="common", merchant_cost=175,
        # +12 gold whenever you enter a non-shop room. Sim hook fires
        # on every room entry; we filter inside the lambda.
        after_room_entered=lambda rs, rt: rs.gain_gold(12) if rt is not StateType.SHOP else None,
        category="gold",
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
        # TheAbacus.cs: AfterShuffle -> gain BlockVar(6). The sim has no shuffle
        # event; approximate as +6 block at the start of each turn (a reshuffle
        # happens roughly per turn once the deck cycles).
        # TODO(fidelity): fire on draw-pile reshuffle for exact timing.
        on_player_turn_start=lambda rs, cs: _gain_block(cs, 6),
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
        # GremlinHorn.cs: AfterDeath of an enemy -> +1 energy and draw 1. The
        # sim has no enemy-death relic hook; approximate with +1 energy on
        # turn 1 (the relic's value is mid-combat tempo).
        # TODO(fidelity): fire on enemy death (needs an on-death hook).
        on_player_turn_start=lambda rs, cs: (
            setattr(cs.player, "energy", cs.player.energy + 1)
            if cs.turn_number == 1 else None),
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

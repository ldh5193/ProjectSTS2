"""Relic hook system — first slice (notes/15_relics_catalog.md).

Implements the most-frequently-encountered relic hooks so that the
run_engine can dispatch them at the right lifecycle points:

- on_combat_start(rs, cs)
- on_player_turn_start(rs, cs)
- after_combat_victory(rs)
- after_room_entered(rs, room_type)

Each RelicDef carries an optional callback per hook. The dispatcher
(`trigger`) iterates rs.relics and calls any hooks the relic
overrides. Missing hooks are no-ops.

Coverage in this slice (12 relics):

- BurningBlood (Ironclad starter): heal 6 after combat victory.
- Vajra: +1 Strength at combat start.
- Anchor: +10 block at combat start.
- BagOfMarbles: 1 Vulnerable to enemy at combat start (turn 1).
- BronzeScales: 3 Thorns to self at combat start.
- DataDisk: +1 Focus at combat start (no-op behavioral, registry only).
- OddlySmoothStone: +1 Dexterity at combat start.
- BloodVial: heal 2 at start of turn 1.
- MealTicket: heal 15 on rest-site entry.
- Pantograph: heal 25 on boss-room entry.
- Lantern: +1 energy on turn 1.
- RedMask: 1 Weak to enemy at combat start (turn 1).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from .game_state import RelicInstance, RunState, StateType
from .powers import make_power


HookOnCombat = Callable[[RunState, object], None]      # (rs, combat_state)
HookOnTurn = Callable[[RunState, object], None]
HookOnVictory = Callable[[RunState], None]
HookOnRoom = Callable[[RunState, StateType], None]


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
    # Obs category — see RELIC_CATEGORIES above.
    category: str = "misc"


def _gain_block(combat, amount: int) -> None:
    combat.player.block += amount


def _apply_power_to_self(combat, power_id: str, amount: int) -> None:
    combat.player.add_or_stack_power(make_power(power_id, amount, combat.player))


def _apply_power_to_monster(combat, power_id: str, amount: int) -> None:
    combat.monster.add_or_stack_power(make_power(power_id, amount, combat.monster))


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
        # Focus has no in-sim effect yet (orb-related). Registry presence
        # is enough so the relic can be granted without crashing.
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
        # Combat power-application check — combat code reads
        # rs.has_relic("GINGER") before applying weak.
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


def relic_ids() -> list[str]:
    return list(RELIC_REGISTRY)

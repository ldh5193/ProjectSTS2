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
    ),
    "VAJRA": RelicDef(
        id="VAJRA", name="Vajra", rarity="common", merchant_cost=175,
        on_combat_start=lambda rs, cs: _apply_power_to_self(cs, "strength", 1),
    ),
    "ANCHOR": RelicDef(
        id="ANCHOR", name="Anchor", rarity="common", merchant_cost=175,
        on_combat_start=lambda rs, cs: _gain_block(cs, 10),
    ),
    "BAG_OF_MARBLES": RelicDef(
        id="BAG_OF_MARBLES", name="Bag of Marbles", rarity="common", merchant_cost=175,
        on_combat_start=lambda rs, cs: _apply_power_to_monster(cs, "vulnerable", 1),
    ),
    "BRONZE_SCALES": RelicDef(
        id="BRONZE_SCALES", name="Bronze Scales", rarity="common", merchant_cost=175,
        on_combat_start=lambda rs, cs: _apply_power_to_self(cs, "thorns", 3),
    ),
    "ODDLY_SMOOTH_STONE": RelicDef(
        id="ODDLY_SMOOTH_STONE", name="Oddly Smooth Stone", rarity="common", merchant_cost=175,
        on_combat_start=lambda rs, cs: _apply_power_to_self(cs, "dexterity", 1),
    ),
    "BLOOD_VIAL": RelicDef(
        id="BLOOD_VIAL", name="Blood Vial", rarity="common", merchant_cost=175,
        on_player_turn_start=lambda rs, cs: rs.heal(2) if cs.turn_number == 1 else None,
    ),
    "MEAL_TICKET": RelicDef(
        id="MEAL_TICKET", name="Meal Ticket", rarity="common", merchant_cost=175,
        after_room_entered=lambda rs, rt: rs.heal(15) if rt is StateType.REST else None,
    ),
    "PANTOGRAPH": RelicDef(
        id="PANTOGRAPH", name="Pantograph", rarity="uncommon", merchant_cost=250,
        after_room_entered=lambda rs, rt: rs.heal(25) if rt is StateType.BOSS else None,
    ),
    "LANTERN": RelicDef(
        id="LANTERN", name="Lantern", rarity="common", merchant_cost=175,
        on_player_turn_start=lambda rs, cs: setattr(cs.player, "energy", cs.player.energy + 1) if cs.turn_number == 1 else None,
    ),
    "RED_MASK": RelicDef(
        id="RED_MASK", name="Red Mask", rarity="common", merchant_cost=175,
        on_combat_start=lambda rs, cs: _apply_power_to_monster(cs, "weak", 1),
    ),
    "DATA_DISK": RelicDef(
        id="DATA_DISK", name="Data Disk", rarity="common", merchant_cost=175,
        # Focus has no in-sim effect yet (orb-related). Registry presence
        # is enough so the relic can be granted without crashing.
        on_combat_start=lambda rs, cs: None,
    ),
}


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

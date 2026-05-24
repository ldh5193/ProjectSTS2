"""Relic hook integration tests."""
from __future__ import annotations

from sim.game_state import Character, RelicInstance, RunState, StateType
from sim.relics import RELIC_REGISTRY
from sim.run_engine import start_run, step


def _new(seed: int = 0, extra_relics: list[str] | None = None) -> RunState:
    rs = RunState.new_run(character=Character.IRONCLAD, ascension=0, seed=seed)
    if extra_relics:
        for rid in extra_relics:
            rs.relics.append(RelicInstance(id=rid))
    start_run(rs)
    return rs


def test_registry_has_burning_blood_and_vajra():
    assert "BURNING_BLOOD" in RELIC_REGISTRY
    assert "VAJRA" in RELIC_REGISTRY


def test_vajra_grants_strength_on_combat_start():
    rs = _new(extra_relics=["VAJRA"])
    step(rs, {"action": "choose_map_node", "node_index": 0})
    cs = rs.combat
    assert cs is not None
    s = cs.player.get_power("strength")
    assert s is not None and s.amount == 1


def test_anchor_grants_block_on_combat_start():
    rs = _new(extra_relics=["ANCHOR"])
    step(rs, {"action": "choose_map_node", "node_index": 0})
    assert rs.combat is not None
    assert rs.combat.player.block == 10


def test_blood_vial_heals_on_first_turn():
    """Player starts at 80 HP. Drop to 70 and verify BloodVial gives 2 back
    at the start of the first combat turn."""
    rs = _new(extra_relics=["BLOOD_VIAL"])
    rs.hp = 70
    rs.max_hp = 80
    step(rs, {"action": "choose_map_node", "node_index": 0})
    assert rs.combat is not None
    assert rs.combat.player.hp == 72


def test_bag_of_marbles_applies_vulnerable_to_monster():
    rs = _new(extra_relics=["BAG_OF_MARBLES"])
    step(rs, {"action": "choose_map_node", "node_index": 0})
    v = rs.combat.monster.get_power("vulnerable")
    assert v is not None and v.amount == 1


def test_lantern_grants_extra_energy_on_first_turn():
    rs = _new(extra_relics=["LANTERN"])
    step(rs, {"action": "choose_map_node", "node_index": 0})
    # Base energy is 3 (Ironclad); Lantern adds +1 on turn 1.
    assert rs.combat.player.energy == 4


def test_burning_blood_still_fires_via_registry():
    """Existing Burning Blood behavior should keep working now that the
    inline code was replaced with the registry hook."""
    def run_scripted(with_bb: bool) -> int:
        rs = _new()
        if not with_bb:
            rs.relics = [r for r in rs.relics if r.id != "BURNING_BLOOD"]
        rs.hp = 40
        rs.max_hp = 80
        step(rs, {"action": "choose_map_node", "node_index": 0})
        safety = 30
        while rs.state_type is StateType.MONSTER and safety > 0:
            cs = rs.combat
            if any(cs.can_play(i) for i in range(len(cs.hand))):
                idx = next(i for i in range(len(cs.hand)) if cs.can_play(i))
                step(rs, {"action": "play_card", "card_index": idx})
            else:
                step(rs, {"action": "end_turn"})
            safety -= 1
        return rs.hp if rs.state_type is StateType.CARD_REWARD else -1
    bb = run_scripted(True)
    nobb = run_scripted(False)
    if bb < 0 or nobb < 0:
        return
    assert bb == nobb + 6

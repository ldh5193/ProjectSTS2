"""Run engine integration tests — start the run, walk the map, win/lose
a few combats, advance acts.
"""
from __future__ import annotations

from sim.game_state import Ascension, Character, RunState, StateType
from sim.run_engine import reachable_map_nodes, start_run, step


def _new(seed: int = 42, ascension: int = 0) -> RunState:
    rs = RunState.new_run(character=Character.IRONCLAD,
                          ascension=ascension, seed=seed)
    start_run(rs)
    return rs


def test_start_run_enters_map_with_floor_1_options():
    rs = _new(0)
    assert rs.state_type is StateType.MAP
    assert rs.act == 1
    options = reachable_map_nodes(rs)
    # Floor 1 = Ancient (single-node, Neow-skip placeholder); the first
    # 7-way choice happens at floor 2 via Ancient.children.
    assert len(options) == 1
    assert options[0].floor == 1


def test_choose_map_node_advances_into_room():
    rs = _new(0)
    # Floor 1 is forced Monster.
    result = step(rs, {"action": "choose_map_node", "node_index": 0})
    assert result.floor_advanced
    assert rs.state_type is StateType.MONSTER
    assert rs.combat is not None


def test_invalid_node_index_does_not_terminate():
    rs = _new(0)
    result = step(rs, {"action": "choose_map_node", "node_index": 99})
    assert result.invalid_action
    assert not rs.is_terminal()


def test_play_through_first_combat_to_reward():
    rs = _new(0)
    step(rs, {"action": "choose_map_node", "node_index": 0})
    # Hammer end_turn until combat resolves; the placeholder Strike/Defend deck
    # against SludgeSpinnerWeak should resolve within ~10 turns.
    safety = 30
    while rs.state_type is StateType.MONSTER and safety > 0:
        # If we have any playable card, play hand[0]; else end the turn.
        cs = rs.combat
        hand_ok = any(cs.can_play(i) for i in range(len(cs.hand)))
        if hand_ok:
            idx = next(i for i in range(len(cs.hand)) if cs.can_play(i))
            step(rs, {"action": "play_card", "card_index": idx})
        else:
            step(rs, {"action": "end_turn"})
        safety -= 1
    # Either the agent won (card reward open) or lost (game over).
    assert rs.state_type in (StateType.CARD_REWARD, StateType.GAME_OVER)


def test_skip_card_reward_returns_to_map():
    rs = _new(0)
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
    if rs.state_type is StateType.CARD_REWARD:
        step(rs, {"action": "skip_card_reward"})
        assert rs.state_type is StateType.MAP


def test_burning_blood_heals_after_combat_win():
    """Run the same scripted combat once with Burning Blood and once
    without; the BB run should end exactly 6 HP higher (heal applied at
    the moment of victory)."""
    def run_scripted(with_relic: bool) -> int:
        rs = _new(0)
        rs.hp = 40
        rs.max_hp = 80
        if not with_relic:
            rs.relics = [r for r in rs.relics if r.id != "BURNING_BLOOD"]
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

    with_bb = run_scripted(True)
    without_bb = run_scripted(False)
    if with_bb < 0 or without_bb < 0:
        return  # combat didn't resolve to a win; nothing to assert
    assert with_bb == without_bb + 6


def test_run_state_carries_deck_modifications_into_subsequent_combats():
    rs = _new(0)
    initial_deck_size = len(rs.deck)
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
    if rs.state_type is StateType.CARD_REWARD:
        step(rs, {"action": "select_card_reward", "card_index": 0})
        assert len(rs.deck) == initial_deck_size + 1


def test_run_does_not_advance_past_terminal_state():
    rs = _new(0)
    rs.is_dead = True
    rs.state_type = StateType.GAME_OVER
    res = step(rs, {"action": "choose_map_node", "node_index": 0})
    assert res.invalid_action

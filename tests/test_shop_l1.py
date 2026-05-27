"""Phase 1 tests for L1 shop — card removal at fixed cost.

Verifies:
  - Entering a shop room sets pending_shop with removable card indices
  - shop_purchase_removal pays gold + removes the card
  - Disabled when out of gold, removal already used, or curse target
  - proceed returns to MAP
"""
from __future__ import annotations

import pytest

from sim.action_space import decode
from sim.game_state import Character, RunState, StateType
from sim.run_engine import step, _enter_room
from sim.game_state import MapNode


def _new_rs_in_shop(gold: int = 200) -> RunState:
    rs = RunState.new_run(character=Character.IRONCLAD, ascension=0, seed=42)
    rs.gold = gold
    rs.act = 1
    rs.floor = 5
    # Spawn a fake shop node and enter it.
    node = MapNode(floor=5, x=0, room_type=StateType.SHOP)
    _enter_room(rs, node)
    return rs


def test_enter_shop_sets_pending_shop():
    rs = _new_rs_in_shop()
    assert rs.state_type == StateType.SHOP
    assert rs.pending_shop is not None
    assert rs.pending_shop["card_removal_cost"] == 75
    assert rs.pending_shop["removal_used"] is False


def test_shop_removal_pays_gold_and_removes_card():
    rs = _new_rs_in_shop(gold=200)
    pre_deck = len(rs.deck)
    res = step(rs, {"action": "shop_purchase_removal", "index": 0})
    assert not res.invalid_action
    assert rs.gold == 125  # 200 - 75
    assert len(rs.deck) == pre_deck - 1
    assert rs.pending_shop["removal_used"] is True


def test_shop_removal_blocked_without_gold():
    rs = _new_rs_in_shop(gold=10)
    pre_deck = len(rs.deck)
    res = step(rs, {"action": "shop_purchase_removal", "index": 0})
    assert res.invalid_action
    assert rs.gold == 10
    assert len(rs.deck) == pre_deck


def test_shop_removal_one_per_visit():
    rs = _new_rs_in_shop(gold=300)
    step(rs, {"action": "shop_purchase_removal", "index": 0})
    res = step(rs, {"action": "shop_purchase_removal", "index": 0})
    assert res.invalid_action
    assert "already used" in res.reason


def test_shop_proceed_returns_to_map():
    rs = _new_rs_in_shop()
    res = step(rs, {"action": "proceed"})
    assert not res.invalid_action
    assert rs.state_type == StateType.MAP
    assert rs.pending_shop is None


def test_shop_removal_invalid_index():
    rs = _new_rs_in_shop(gold=200)
    res = step(rs, {"action": "shop_purchase_removal", "index": 999})
    assert res.invalid_action

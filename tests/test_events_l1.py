"""Phase 1 tests for sim/events.py — L1 event registry.

Verifies that each L1 event:
  - Is registered with the expected id
  - Generates the expected number of options
  - Applies effects without crashing
  - Mutates RunState in the expected direction (HP +/-, gold +/-,
    deck +/-, relic +/-, max_hp +/-)
"""
from __future__ import annotations

import pytest

from sim.events import (
    EVENT_REGISTRY, apply_option, pick_event,
)
from sim.game_state import Ascension, Character, RunState, StateType


def _new_rs(act: int = 1, floor: int = 1, gold: int = 200, hp: int = 60,
            max_hp: int = 80) -> RunState:
    rs = RunState.new_run(character=Character.IRONCLAD, ascension=0, seed=42)
    rs.act = act
    rs.floor = floor
    rs.gold = gold
    rs.hp = hp
    rs.max_hp = max_hp
    return rs


def test_registry_has_ten_events():
    assert len(EVENT_REGISTRY) == 10


def test_brain_leech_share_adds_card():
    rs = _new_rs()
    pre_deck = len(rs.deck)
    ok = apply_option(rs, "brain_leech", 0)  # share_knowledge
    assert ok
    assert len(rs.deck) == pre_deck + 1
    assert rs.hp == 60  # no HP loss


def test_brain_leech_rip_loses_hp_and_adds_card():
    rs = _new_rs()
    pre_deck = len(rs.deck)
    ok = apply_option(rs, "brain_leech", 1)  # rip
    assert ok
    assert rs.hp == 55  # -5 HP
    assert len(rs.deck) == pre_deck + 1


def test_wellspring_bottle_adds_potion():
    rs = _new_rs()
    pre_potions = sum(1 for p in rs.potions if p is not None)
    ok = apply_option(rs, "wellspring", 0)  # bottle
    assert ok
    post = sum(1 for p in rs.potions if p is not None)
    assert post == pre_potions + 1


def test_wellspring_bathe_removes_card_adds_curse():
    rs = _new_rs()
    pre_deck = len(rs.deck)
    ok = apply_option(rs, "wellspring", 1)  # bathe
    assert ok
    # -1 card, +1 curse = net 0 in size but curse content changed.
    assert len(rs.deck) == pre_deck
    assert any(c.id == "guilty" for c in rs.deck)


def test_grave_confront_adds_curse_and_upgrades():
    rs = _new_rs()
    upgradables_before = sum(1 for c in rs.deck if not c.id.endswith("+")
                             and c.id != "ascenders_bane")
    ok = apply_option(rs, "grave_of_the_forgotten", 0)  # confront
    assert ok
    assert any(c.id == "decay" for c in rs.deck)
    upgradables_after = sum(1 for c in rs.deck if not c.id.endswith("+")
                            and c.id not in {"ascenders_bane", "decay"})
    # Exactly one card got upgraded.
    assert upgradables_after == upgradables_before - 1


def test_grave_accept_grants_relic():
    rs = _new_rs()
    ok = apply_option(rs, "grave_of_the_forgotten", 1)  # accept
    assert ok
    assert rs.has_relic("FORGOTTEN_SOUL")


def test_trash_heap_dive_in_loses_hp_grants_relic():
    rs = _new_rs(hp=60)
    pre_relics = len(rs.relics)
    ok = apply_option(rs, "trash_heap", 0)  # dive_in
    assert ok
    assert rs.hp == 52  # -8 HP
    assert len(rs.relics) == pre_relics + 1


def test_trash_heap_grab_gold_and_card():
    rs = _new_rs(gold=200)
    pre_deck = len(rs.deck)
    ok = apply_option(rs, "trash_heap", 1)  # grab
    assert ok
    assert rs.gold == 300  # +100
    assert len(rs.deck) == pre_deck + 1


def test_tablet_decipher_loses_max_hp_upgrades():
    rs = _new_rs(max_hp=80, hp=80)
    ok = apply_option(rs, "tablet_of_truth", 0)  # decipher
    assert ok
    assert rs.max_hp == 77  # -3 max_hp
    # hp clamped to new max — was 80, max became 77 → hp = 77
    assert rs.hp == 77


def test_tablet_smash_heals():
    rs = _new_rs(hp=50, max_hp=80)
    ok = apply_option(rs, "tablet_of_truth", 1)  # smash
    assert ok
    assert rs.hp == 70  # +20


def test_tablet_decipher_disabled_when_no_upgradable():
    rs = _new_rs()
    # Mark every card as already upgraded.
    from dataclasses import replace
    for i, c in enumerate(rs.deck):
        rs.deck[i] = replace(c, id=c.id + "+", name=c.name + "+")
    options = EVENT_REGISTRY["tablet_of_truth"].generate_options(rs)
    assert options[0].enabled is False  # decipher locked


def test_abyssal_baths_immerse_gains_max_hp_loses_hp():
    rs = _new_rs(hp=60, max_hp=80)
    ok = apply_option(rs, "abyssal_baths", 0)  # immerse
    assert ok
    assert rs.max_hp == 82  # +2
    # hp = 60 + 2 (heal from gain_max_hp) - 3 (immerse damage) = 59
    assert rs.hp == 59


def test_abyssal_baths_abstain_heals_10():
    rs = _new_rs(hp=60, max_hp=80)
    ok = apply_option(rs, "abyssal_baths", 1)  # abstain
    assert ok
    assert rs.hp == 70  # +10


def test_wood_carvings_upgrades_basic():
    rs = _new_rs()
    upgradable_count = sum(1 for c in rs.deck if not c.id.endswith("+"))
    ok = apply_option(rs, "wood_carvings", 0)  # bird
    assert ok
    new_upgradable = sum(1 for c in rs.deck if not c.id.endswith("+")
                         and c.id != "ascenders_bane")
    assert new_upgradable == upgradable_count - 1


def test_neow_only_at_floor_zero():
    rs = _new_rs(floor=0)
    assert EVENT_REGISTRY["neow"].is_allowed(rs)
    rs.floor = 5
    assert not EVENT_REGISTRY["neow"].is_allowed(rs)


def test_neow_grants_relic():
    rs = _new_rs(floor=0)
    ok = apply_option(rs, "neow", 0)  # arcane scroll
    assert ok
    assert rs.has_relic("ARCANE_SCROLL")


def test_wongos_act_2_only():
    rs = _new_rs(act=1, gold=200)
    assert not EVENT_REGISTRY["welcome_to_wongos"].is_allowed(rs)
    rs.act = 2
    assert EVENT_REGISTRY["welcome_to_wongos"].is_allowed(rs)


def test_wongos_bargain_costs_gold():
    rs = _new_rs(act=2, gold=200)
    ok = apply_option(rs, "welcome_to_wongos", 0)  # bargain_bin
    assert ok
    assert rs.gold == 100
    assert rs.has_relic("WONGO_COMMON_RELIC")


def test_wongos_locked_options_disabled():
    rs = _new_rs(act=2, gold=50)
    options = EVENT_REGISTRY["welcome_to_wongos"].generate_options(rs)
    assert options[0].enabled is False  # bargain (100g)
    assert options[1].enabled is False  # featured (200g)
    assert options[2].enabled is False  # mystery (300g)
    assert options[3].enabled is True   # leave always enabled


def test_punch_off_fight_loses_hp():
    rs = _new_rs(hp=50)
    ok = apply_option(rs, "punch_off", 0)  # fight
    assert ok
    assert rs.hp == 35  # -15
    assert rs.has_relic("PUNCH_OFF_RELIC")


def test_punch_off_skip_no_op():
    rs = _new_rs(hp=50)
    ok = apply_option(rs, "punch_off", 1)  # skip
    assert ok
    assert rs.hp == 50  # unchanged


def test_pick_event_returns_eligible():
    rs = _new_rs(act=1, floor=5, hp=60)
    evt = pick_event(rs)
    assert evt is not None
    assert evt.is_allowed(rs)


def test_apply_option_invalid_id_returns_false():
    rs = _new_rs()
    assert not apply_option(rs, "nonexistent_event", 0)


def test_apply_option_out_of_range_returns_false():
    rs = _new_rs()
    assert not apply_option(rs, "brain_leech", 99)


def test_apply_option_disabled_returns_false():
    rs = _new_rs(act=2, gold=10)
    # Wongo's bargain_bin requires gold>=100 — locked here.
    assert not apply_option(rs, "welcome_to_wongos", 0)


def test_event_marked_in_history():
    rs = _new_rs()
    assert "brain_leech" not in rs.history_events
    apply_option(rs, "brain_leech", 0)
    assert "brain_leech" in rs.history_events

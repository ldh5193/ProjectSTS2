"""Phase 8 fidelity tests: expanded events, Neow, rest site, ascension A2.

Proves:
  - The event registry grew past the original 10.
  - New events apply their real decompiled effects:
      * a max-HP event (Cook rest / AbyssalBaths) raises max_hp
      * a card-removal event (SlipperyBridge) thins the deck
      * a relic event (HungryForMushrooms / SunkenStatue) grants a real
        registry relic
  - Neow offers a representative bonus/drawback set (2 positive + 1 cursed).
  - Rest site exposes >2 enabled options; Dig grants a relic; Lift gives the
    permanent Girya buff.
  - A2 WearyTraveler reduces a heal by 0.8.
"""
from __future__ import annotations

from sim.events import EVENT_REGISTRY, apply_option
from sim.game_state import Ascension, Character, RelicInstance, RunState, StateType
from sim.relics import RELIC_REGISTRY


def _new_rs(act: int = 1, floor: int = 7, gold: int = 200, hp: int = 60,
            max_hp: int = 80, ascension: int = 0) -> RunState:
    rs = RunState.new_run(character=Character.IRONCLAD,
                          ascension=ascension, seed=42)
    rs.act = act
    rs.floor = floor
    rs.gold = gold
    rs.hp = hp
    rs.max_hp = max_hp
    return rs


# --- registry growth -------------------------------------------------------

def test_registry_grew_past_ten():
    assert len(EVENT_REGISTRY) >= 24
    # The new events are present.
    for eid in ("bugslayer", "slippery_bridge", "hungry_for_mushrooms",
                "sunken_statue", "lost_wisp", "this_or_that", "reflections"):
        assert eid in EVENT_REGISTRY


# --- new events apply real effects -----------------------------------------

def test_slippery_bridge_thins_deck():
    """Overcome removes a card from the deck."""
    rs = _new_rs()
    pre = len(rs.deck)
    ok = apply_option(rs, "slippery_bridge", 0)  # overcome
    assert ok
    assert len(rs.deck) == pre - 1


def test_hungry_for_mushrooms_grants_real_relic():
    rs = _new_rs()
    pre = {r.id for r in rs.relics}
    ok = apply_option(rs, "hungry_for_mushrooms", 0)  # big mushroom
    assert ok
    new = {r.id for r in rs.relics} - pre
    assert len(new) == 1
    granted = next(iter(new))
    assert granted in RELIC_REGISTRY


def test_sunken_statue_grab_grants_registry_relic():
    rs = _new_rs()
    pre = {r.id for r in rs.relics}
    ok = apply_option(rs, "sunken_statue", 0)  # grab sword -> pooled relic
    assert ok
    new = {r.id for r in rs.relics} - pre
    assert len(new) == 1
    assert next(iter(new)) in RELIC_REGISTRY


def test_lost_wisp_claim_adds_curse_and_relic():
    rs = _new_rs()
    pre_deck = len(rs.deck)
    pre_relics = len(rs.relics)
    ok = apply_option(rs, "lost_wisp", 0)  # claim
    assert ok
    assert len(rs.deck) == pre_deck + 1          # decay curse added
    assert any(c.id == "decay" for c in rs.deck)
    assert len(rs.relics) == pre_relics + 1      # relic granted


def test_this_or_that_plain_costs_hp_grants_gold():
    rs = _new_rs(hp=60, gold=100)
    ok = apply_option(rs, "this_or_that", 0)  # plain: -6 HP, +gold
    assert ok
    assert rs.hp == 54
    assert rs.gold > 100


def test_bugslayer_adds_a_card():
    rs = _new_rs(act=1)
    pre = len(rs.deck)
    ok = apply_option(rs, "bugslayer", 0)  # exterminate
    assert ok
    assert len(rs.deck) == pre + 1


def test_drowning_beacon_climb_lowers_max_hp_grants_relic():
    rs = _new_rs(max_hp=80, hp=80)
    pre_relics = len(rs.relics)
    ok = apply_option(rs, "drowning_beacon", 1)  # climb: -13 max HP + relic
    assert ok
    assert rs.max_hp == 67
    assert len(rs.relics) == pre_relics + 1


def test_abyssal_baths_immerse_raises_max_hp():
    """A maxHP event raises max_hp (AbyssalBaths.Immerse: +2 max HP)."""
    rs = _new_rs(max_hp=80, hp=80)
    ok = apply_option(rs, "abyssal_baths", 0)  # immerse
    assert ok
    assert rs.max_hp == 82


# --- Neow ------------------------------------------------------------------

def test_neow_offers_two_positive_one_cursed():
    rs = _new_rs(act=1, floor=0)
    evt = EVENT_REGISTRY["neow"]
    opts = evt.generate_options(rs)
    assert len(opts) == 3
    cursed = [o for o in opts if "cursed" in o.id]
    positive = [o for o in opts if o.id.startswith("neow_pos_")]
    assert len(cursed) == 1
    assert len(positive) == 2
    # The cursed option carries a curse tag.
    assert "CURSE" in cursed[0].tag


def test_neow_positive_grants_registry_relic():
    rs = _new_rs(act=1, floor=0)
    pre = {r.id for r in rs.relics}
    ok = apply_option(rs, "neow", 0)  # first positive option
    assert ok
    new = {r.id for r in rs.relics} - pre
    assert len(new) == 1
    assert next(iter(new)) in RELIC_REGISTRY


def test_neow_cursed_adds_curse_card():
    rs = _new_rs(act=1, floor=0)
    pre_deck = len(rs.deck)
    ok = apply_option(rs, "neow", 2)  # cursed option
    assert ok
    assert len(rs.deck) == pre_deck + 1  # curse card added


# --- rest site -------------------------------------------------------------

def _enter_rest(rs: RunState):
    """Drive the engine into a rest room and return the pending options."""
    from sim.run_engine import _enter_room
    from sim.game_state import MapNode
    node = MapNode(floor=rs.floor, x=0, room_type=StateType.REST)
    _enter_room(rs, node)
    return rs.pending_rest_options


def test_rest_site_exposes_more_than_two_enabled_options():
    rs = _new_rs(hp=40, max_hp=80)
    opts = _enter_rest(rs)
    enabled = [o for o in opts if o["is_enabled"]]
    # rest + smith + dig + cook (>=2 removable) => at least 3 enabled.
    assert len(enabled) > 2
    ids = {o["id"] for o in opts}
    assert {"rest", "smith", "dig", "cook", "lift"} <= ids


def test_rest_dig_grants_relic():
    rs = _new_rs()
    _enter_rest(rs)
    pre = len(rs.relics)
    from sim.run_engine import _step_rest, StepResult
    res = StepResult()
    _step_rest(rs, {"action": "choose_rest_option", "index": 3}, res)  # dig
    assert len(rs.relics) == pre + 1


def test_rest_lift_increments_girya_buff():
    rs = _new_rs()
    rs.relics.append(RelicInstance(id="GIRYA"))
    _enter_rest(rs)
    from sim.run_engine import _step_rest, StepResult
    res = StepResult()
    _step_rest(rs, {"action": "choose_rest_option", "index": 5}, res)  # lift
    girya = next(r for r in rs.relics if r.id == "GIRYA")
    assert (girya.counter or 0) >= 1


def test_rest_cook_removes_cards_and_raises_max_hp():
    rs = _new_rs(max_hp=80, hp=80)
    _enter_rest(rs)
    pre_deck = len(rs.deck)
    from sim.run_engine import _step_rest, StepResult
    res = StepResult()
    _step_rest(rs, {"action": "choose_rest_option", "index": 4}, res)  # cook
    assert len(rs.deck) == pre_deck - 2
    assert rs.max_hp == 89  # +9 max HP


# --- ascension A2 ----------------------------------------------------------

def test_a2_reduces_heal_by_point_eight():
    """A2 WearyTraveler multiplies heal-type effects by 0.8."""
    rs_a0 = _new_rs(hp=10, max_hp=100, ascension=0)
    rs_a2 = _new_rs(hp=10, max_hp=100, ascension=int(Ascension.WEARY_TRAVELER))
    healed_a0 = rs_a0.heal(50)
    healed_a2 = rs_a2.heal(50)
    assert healed_a0 == 50
    assert healed_a2 == 40  # 50 * 0.8


def test_a2_reduces_rest_heal():
    """Rest-site heal (30% max HP) is reduced by 0.8 under A2."""
    from sim.run_engine import _step_rest, StepResult
    rs = _new_rs(hp=10, max_hp=100, ascension=int(Ascension.WEARY_TRAVELER))
    _enter_rest(rs)
    res = StepResult()
    _step_rest(rs, {"action": "choose_rest_option", "index": 0}, res)  # rest
    # base heal = 30, A2 -> 24.
    assert rs.hp == 10 + 24

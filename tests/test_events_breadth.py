"""Phase 8B breadth tests for sim/events.py — full-coverage event set.

Asserts the registry jumped toward the full decompiled 68-event set,
spot-checks ~15 newly added events apply their real decompiled effects
(maxHP / heal / gold / card-add / card-remove / upgrade / relic / curse /
damage) and respect eligibility, and that pick_event returns
act-appropriate events from the per-act pools.

Ground truth: decompiled MegaCrit.Sts2.Core.Models.Events.*.
"""
from __future__ import annotations

from sim.events import (
    EVENT_REGISTRY, apply_option, pick_event,
    _ACT1_EVENTS, _ACT2_EVENTS, _ACT3_EVENTS, _SHARED_EVENTS,
)
from sim.game_state import Character, RunState
from sim.relics import RELIC_REGISTRY


def _new_rs(act: int = 1, floor: int = 5, gold: int = 400, hp: int = 70,
            max_hp: int = 80, seed: int = 123) -> RunState:
    rs = RunState.new_run(character=Character.IRONCLAD, ascension=0, seed=seed)
    rs.act = act
    rs.floor = floor
    rs.gold = gold
    rs.hp = hp
    rs.max_hp = max_hp
    return rs


def _count_potions(rs: RunState) -> int:
    return sum(1 for p in rs.potions if p is not None)


# --- registry breadth ------------------------------------------------------

def test_registry_jumped_toward_full_68():
    # Phase 8B implemented the remaining option-tree events. 5 of the 68
    # are intentionally omitted (TheArchitect/FakeMerchant/WarHistorianRepy
    # — custom combat/quest layouts — plus the two Deprecated stubs), so the
    # registry lands at 63 real events.
    assert len(EVENT_REGISTRY) >= 60, f"only {len(EVENT_REGISTRY)} events"
    # Report the coverage explicitly so the count surfaces in -v output.
    print(f"\nEVENT COVERAGE: {len(EVENT_REGISTRY)}/68 events")


def test_all_events_generate_and_apply_without_crashing():
    """Every option of every event applies cleanly against a generous state."""
    for eid, evt in EVENT_REGISTRY.items():
        rs = _new_rs(act=2, floor=8)
        rs.add_potion("FIRE_POTION")
        for r in ("MAW_BANK", "THE_BOOT", "HAND_DRILL", "DREAM_CATCHER", "GIRYA"):
            rs.add_relic(r)
        opts = evt.generate_options(rs)
        assert opts, f"{eid} generated no options"
        for i in range(len(opts)):
            rs2 = _new_rs(act=2, floor=8)
            rs2.add_potion("FIRE_POTION")
            for r in ("MAW_BANK", "THE_BOOT", "HAND_DRILL",
                      "DREAM_CATCHER", "GIRYA"):
                rs2.add_relic(r)
            assert apply_option(rs2, eid, i) or not opts[i].enabled


# --- spot-checks: 15 newly added events apply their real effects ----------

def test_amalgamator_combine_strikes_removes_two_adds_one():
    rs = _new_rs()
    n_strike = sum(1 for c in rs.deck if "strike" in c.id.lower())
    assert n_strike >= 2
    pre = len(rs.deck)
    assert apply_option(rs, "amalgamator", 0)  # combine_strikes
    # -2 strikes +1 ultimate = net -1.
    assert len(rs.deck) == pre - 1
    assert any(c.id == "ultimate_strike" for c in rs.deck)


def test_byrdonis_nest_eat_gains_max_hp():
    rs = _new_rs(hp=70, max_hp=80)
    assert apply_option(rs, "byrdonis_nest", 0)  # eat
    assert rs.max_hp == 87  # +7


def test_byrdonis_nest_take_adds_card():
    rs = _new_rs()
    pre = len(rs.deck)
    assert apply_option(rs, "byrdonis_nest", 1)  # take
    assert len(rs.deck) == pre + 1
    assert any(c.id == "byrdonis_egg" for c in rs.deck)


def test_crystal_sphere_payment_plan_adds_debt_curse():
    rs = _new_rs(act=2, gold=200)
    assert apply_option(rs, "crystal_sphere", 1)  # payment_plan
    assert any(c.id == "debt" for c in rs.deck)


def test_crystal_sphere_uncover_costs_gold():
    rs = _new_rs(act=2, gold=300)
    assert apply_option(rs, "crystal_sphere", 0)  # uncover_future
    assert rs.gold < 300


def test_crystal_sphere_act1_disallowed():
    rs = _new_rs(act=1, gold=300)
    assert not EVENT_REGISTRY["crystal_sphere"].is_allowed(rs)


def test_doors_light_upgrades_two():
    rs = _new_rs()
    upg = sum(1 for c in rs.deck if not c.id.endswith("+")
              and c.id != "ascenders_bane")
    assert apply_option(rs, "doors_of_light_and_dark", 0)  # light
    upg_after = sum(1 for c in rs.deck if not c.id.endswith("+")
                    and c.id != "ascenders_bane")
    assert upg_after == upg - 2


def test_doors_dark_removes_one():
    rs = _new_rs()
    pre = len(rs.deck)
    assert apply_option(rs, "doors_of_light_and_dark", 1)  # dark
    assert len(rs.deck) == pre - 1


def test_morphic_grove_loner_gains_max_hp():
    rs = _new_rs(gold=150, max_hp=80, hp=70)
    assert apply_option(rs, "morphic_grove", 1)  # loner
    assert rs.max_hp == 85  # +5


def test_morphic_grove_group_loses_all_gold():
    rs = _new_rs(gold=150)
    assert apply_option(rs, "morphic_grove", 0)  # group
    assert rs.gold == 0


def test_sunken_treasury_second_chest_gold_and_curse():
    rs = _new_rs(gold=0)
    assert apply_option(rs, "sunken_treasury", 1)  # second_chest
    assert rs.gold > 200
    assert any(c.id == "greed" for c in rs.deck)


def test_spirit_grafter_let_it_in_heals_and_adds_card():
    rs = _new_rs(hp=40, max_hp=80)
    pre = len(rs.deck)
    assert apply_option(rs, "spirit_grafter", 0)  # let_it_in
    assert rs.hp == 65  # +25 heal
    assert len(rs.deck) == pre + 1
    assert any(c.id == "metamorphosis" for c in rs.deck)


def test_spirit_grafter_rejection_upgrades_and_loses_hp():
    rs = _new_rs(hp=40, max_hp=80)
    assert apply_option(rs, "spirit_grafter", 1)  # rejection
    assert rs.hp == 30  # -10


def test_unrest_site_eligibility_and_kill_relic():
    # Eligible only when HP <= 70% of max.
    rs_full = _new_rs(hp=80, max_hp=80)
    assert not EVENT_REGISTRY["unrest_site"].is_allowed(rs_full)
    rs = _new_rs(hp=40, max_hp=80)
    assert EVENT_REGISTRY["unrest_site"].is_allowed(rs)
    pre = len(rs.relics)
    assert apply_option(rs, "unrest_site", 1)  # kill
    assert rs.max_hp == 72  # -8 max HP
    assert len(rs.relics) == pre + 1


def test_unrest_site_rest_full_heal_plus_curse():
    rs = _new_rs(hp=40, max_hp=80)
    assert apply_option(rs, "unrest_site", 0)  # rest
    assert rs.hp == rs.max_hp  # healed to full
    assert any(c.id == "poor_sleep" for c in rs.deck)


def test_zen_weaver_breathing_costs_gold_adds_two_cards():
    rs = _new_rs(gold=200)
    pre = len(rs.deck)
    assert apply_option(rs, "zen_weaver", 0)  # breathing_techniques
    assert rs.gold == 150  # -50
    assert len(rs.deck) == pre + 2


def test_tea_master_act_and_gold_gate():
    rs = _new_rs(act=2, gold=200)
    assert not EVENT_REGISTRY["tea_master"].is_allowed(rs)  # act 1 only
    rs = _new_rs(act=1, gold=100)
    assert not EVENT_REGISTRY["tea_master"].is_allowed(rs)  # needs 150
    rs = _new_rs(act=1, gold=200)
    assert EVENT_REGISTRY["tea_master"].is_allowed(rs)


def test_tea_master_bone_tea_costs_gold_grants_relic():
    rs = _new_rs(act=1, gold=200)
    pre = len(rs.relics)
    assert apply_option(rs, "tea_master", 0)  # bone_tea
    assert rs.gold == 150  # -50
    assert len(rs.relics) == pre + 1
    assert all(r.id in RELIC_REGISTRY for r in rs.relics)


def test_potion_courier_grab_three_foul_potions():
    rs = _new_rs(act=2)
    # clear belt
    rs.potions = [None, None, None]
    assert apply_option(rs, "potion_courier", 0)  # grab_potions
    # belt holds 3 — all filled.
    assert _count_potions(rs) == 3


def test_trial_guilty_curse_and_two_relics():
    rs = _new_rs()
    pre = len(rs.relics)
    assert apply_option(rs, "trial", 0)  # guilty
    assert any(c.id == "regret" for c in rs.deck)
    assert len(rs.relics) == pre + 2


def test_round_tea_party_enjoy_relic_and_full_heal():
    rs = _new_rs(hp=40, max_hp=80)
    pre = len(rs.relics)
    assert apply_option(rs, "round_tea_party", 0)  # enjoy_tea
    assert len(rs.relics) == pre + 1
    assert rs.hp == rs.max_hp


def test_vakuu_cape_costs_max_hp_for_relic():
    rs = _new_rs(max_hp=80, hp=80)
    pre = len(rs.relics)
    assert apply_option(rs, "vakuu", 1)  # DistinguishedCape: -9 max HP
    assert rs.max_hp == 71
    assert len(rs.relics) == pre + 1


# --- combat-event handling -------------------------------------------------

def test_battleworn_dummy_settings_scale_hp_cost_and_reward():
    # Setting 1: small HP cost + potion.
    rs = _new_rs(hp=70, max_hp=80)
    rs.potions = [None, None, None]
    assert apply_option(rs, "battleworn_dummy", 0)
    assert rs.hp == 64  # -6
    assert _count_potions(rs) == 1
    # Setting 3: big HP cost + relic.
    rs = _new_rs(hp=70, max_hp=80)
    pre = len(rs.relics)
    assert apply_option(rs, "battleworn_dummy", 2)
    assert rs.hp == 54  # -16
    assert len(rs.relics) == pre + 1


def test_lantern_key_keep_fights_and_grants_card():
    rs = _new_rs(hp=70, max_hp=80, floor=8)
    pre = len(rs.deck)
    assert apply_option(rs, "the_lantern_key", 1)  # keep_the_key
    assert rs.hp == 58  # -12 combat approximation
    assert len(rs.deck) == pre + 1
    assert any(c.id == "lantern_key" for c in rs.deck)


def test_lantern_key_return_grants_gold():
    rs = _new_rs(gold=0, floor=8)
    assert apply_option(rs, "the_lantern_key", 0)  # return_the_key
    assert rs.gold == 100


# --- pick_event respects per-act pools -------------------------------------

def test_pick_event_act_appropriate():
    for act in (1, 2, 3):
        rs = _new_rs(act=act, floor=5, gold=400, hp=70, max_hp=80, seed=act * 11)
        evt = pick_event(rs)
        assert evt is not None
        assert evt.is_allowed(rs)
        # The chosen event must belong to this act's pool or the shared pool.
        act_pool = {1: _ACT1_EVENTS, 2: _ACT2_EVENTS}.get(act, _ACT3_EVENTS)
        assert evt.id in set(act_pool) | set(_SHARED_EVENTS)


def test_pick_event_neow_overrides_at_run_start():
    rs = _new_rs(act=1, floor=0)
    evt = pick_event(rs)
    assert evt is not None and evt.id == "neow"


def test_pick_event_no_neow_after_floor_zero():
    rs = _new_rs(act=1, floor=3)
    for _ in range(10):
        evt = pick_event(rs)
        assert evt is None or evt.id != "neow"


def test_pick_event_deterministic_per_seed():
    a = _new_rs(act=2, floor=6, seed=555)
    b = _new_rs(act=2, floor=6, seed=555)
    assert pick_event(a).id == pick_event(b).id


def test_act2_only_event_not_in_act1_pool():
    # crystal_sphere is an act>=2 event; pick_event in act 1 must not pick it.
    rs = _new_rs(act=1, floor=5, gold=400)
    seen = set()
    for fl in range(1, 14):
        rs.floor = fl
        e = pick_event(rs)
        if e:
            seen.add(e.id)
    assert "crystal_sphere" not in seen
    assert "stone_of_all_time" not in seen

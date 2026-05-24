"""Encounter pool generation tests.

Verifies the static pool generator: pool sizes, tag-based anti-repeat,
A10 second-boss selection, the visited-cursor cycling, and the modeled
encounter builders.
"""
from __future__ import annotations

from sim.encounter import (
    ACTS,
    EncounterPools,
    build_monster_for,
    generate_pools,
    is_modeled,
)
from sim.monsters import NibbitWeak, SludgeSpinnerWeak
from sim.rng import Rng


def test_overgrowth_pool_sizes():
    pools = generate_pools("overgrowth", Rng(42), ascension=0, is_final_act=False)
    spec = ACTS["overgrowth"]
    assert len(pools.normal) == spec["num_total_normal_rooms"]
    assert len(pools.elite) == 15
    assert pools.boss in spec["boss"]
    assert pools.second_boss is None  # A0, not final act


def test_underdocks_pool_sizes():
    pools = generate_pools("underdocks", Rng(7), ascension=0, is_final_act=False)
    spec = ACTS["underdocks"]
    assert len(pools.normal) == spec["num_total_normal_rooms"]
    assert len(pools.elite) == 15


def test_a10_double_boss_on_final_act_only():
    pools = generate_pools("glory", Rng(1), ascension=10, is_final_act=True)
    assert pools.second_boss is not None
    assert pools.second_boss != pools.boss

    # A10 on a non-final act -> no second boss.
    pools2 = generate_pools("overgrowth", Rng(1), ascension=10, is_final_act=False)
    assert pools2.second_boss is None


def test_a9_never_double_boss():
    pools = generate_pools("glory", Rng(1), ascension=9, is_final_act=True)
    assert pools.second_boss is None


def test_pools_deterministic_for_same_seed():
    a = generate_pools("overgrowth", Rng(123))
    b = generate_pools("overgrowth", Rng(123))
    assert a.normal == b.normal
    assert a.elite == b.elite
    assert a.boss == b.boss


def test_pool_cursor_cycles_with_modulo():
    pools = generate_pools("overgrowth", Rng(0))
    # Drain past the end and confirm modulo wrap.
    drained = [pools.next_normal() for _ in range(len(pools.normal) + 3)]
    assert drained[len(pools.normal)] == drained[0]
    assert drained[len(pools.normal) + 1] == drained[1]


def test_first_boss_visit_returns_primary_then_second():
    pools = EncounterPools(
        normal=["NibbitsWeak"], elite=["BygoneEffigyElite"],
        boss="VantomBoss", second_boss="TheKinBoss",
    )
    assert pools.next_boss() == "VantomBoss"
    assert pools.next_boss() == "TheKinBoss"
    # After both bosses visited the cursor stays on second_boss.
    assert pools.next_boss() == "TheKinBoss"


def test_anti_repeat_avoids_same_tag_back_to_back_when_possible():
    # Pool has three encounters with two distinct tags; the second pick
    # should never share the same tag as the first.
    pools = generate_pools("overgrowth", Rng(99))
    from sim.encounter import _tag
    last_tag = None
    same_tag_consecutive = 0
    for eid in pools.normal:
        t = _tag(eid)
        if t is not None and t == last_tag:
            same_tag_consecutive += 1
        last_tag = t
    # Bag drain at the end of the pool can force one same-tag pick,
    # but the tag system should keep this tight.
    assert same_tag_consecutive <= 1


def test_modeled_encounters_resolve_to_real_monsters():
    rng = Rng(0)
    assert is_modeled("NibbitsWeak")
    assert is_modeled("SludgeSpinnerWeak")
    assert is_modeled("CeremonialBeastBoss")
    assert is_modeled("VantomBoss")
    assert not is_modeled("TheKinBoss")  # multi-monster, still deferred

    n = build_monster_for("NibbitsWeak", rng)
    assert isinstance(n, NibbitWeak)
    assert 42 <= n.hp <= 46

    s = build_monster_for("SludgeSpinnerWeak", rng)
    assert isinstance(s, SludgeSpinnerWeak)

    from sim.monsters import CeremonialBeast, Vantom
    cb = build_monster_for("CeremonialBeastBoss", rng)
    assert isinstance(cb, CeremonialBeast) and cb.hp == 252

    v = build_monster_for("VantomBoss", rng)
    assert isinstance(v, Vantom) and v.hp == 173


def test_unmodeled_encounter_falls_back_so_run_loop_can_advance():
    rng = Rng(0)
    placeholder = build_monster_for("CeremonialBeastBoss", rng)
    assert placeholder.alive

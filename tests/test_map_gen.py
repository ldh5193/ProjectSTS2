"""Map generator structural tests."""
from __future__ import annotations

from sim.game_state import StateType
from sim.map_gen import ACT_SPECS, WIDTH, generate_act_map
from sim.rng import Rng


def test_overgrowth_layout_dimensions():
    rmap = generate_act_map("overgrowth", Rng(0))
    spec = ACT_SPECS["overgrowth"]
    # Row 1..N-1 are full-width; row N is boss-only (1 node).
    assert rmap.boss_floor == spec.num_rooms + 1
    assert len(rmap.floors) == rmap.boss_floor
    # Row 1 (index 0) full-width
    assert len(rmap.floors[0]) == WIDTH
    # Boss floor (last) only 1 node at col 3
    assert len(rmap.floors[-1]) == 1
    assert rmap.floors[-1][0].room_type is StateType.BOSS


def test_fixed_rows_are_correct_type():
    rmap = generate_act_map("overgrowth", Rng(42))
    # Row 1: Monster
    assert all(n.room_type is StateType.MONSTER for n in rmap.floors[0])
    # Rest row (N-1 = rmap.boss_floor - 1): RestSite
    rest_floor = rmap.boss_floor - 1
    assert all(n.room_type is StateType.REST for n in rmap.floors[rest_floor - 1])
    # Treasure row (N-7)
    treasure_floor = rmap.boss_floor - 7
    treasure_nodes = rmap.floors[treasure_floor - 1]
    assert len(treasure_nodes) == 1
    assert treasure_nodes[0].room_type in (StateType.TREASURE, StateType.ELITE)


def test_no_elite_or_rest_below_row_6():
    rmap = generate_act_map("overgrowth", Rng(7))
    for f in range(1, 6):
        for n in rmap.floors[f - 1]:
            assert n.room_type is not StateType.ELITE
            assert n.room_type is not StateType.REST


def test_floor_1_nodes_connect_to_floor_2():
    rmap = generate_act_map("overgrowth", Rng(99))
    for n in rmap.floors[0]:
        # Every floor-1 node should have at least 1 successor on floor 2.
        successors = [c for c in n.children if c[0] == 2]
        assert successors, f"floor-1 col {n.x} has no successors"


def test_rest_row_nodes_link_to_boss():
    rmap = generate_act_map("overgrowth", Rng(13))
    rest_floor = rmap.boss_floor - 1
    for n in rmap.floors[rest_floor - 1]:
        assert (rmap.boss_floor, 3) in n.children


def test_deterministic_for_same_seed():
    a = generate_act_map("overgrowth", Rng(2025))
    b = generate_act_map("overgrowth", Rng(2025))

    def shape(rmap):
        return [[(n.room_type.value, n.x) for n in floor] for floor in rmap.floors]
    assert shape(a) == shape(b)


def test_swarming_elites_ascension_increases_elite_count():
    base = 0
    swarm = 0
    for s in range(20):
        m0 = generate_act_map("overgrowth", Rng(s), ascension=0)
        m1 = generate_act_map("overgrowth", Rng(s), ascension=1)
        base += sum(1 for floor in m0.floors for n in floor if n.room_type is StateType.ELITE)
        swarm += sum(1 for floor in m1.floors for n in floor if n.room_type is StateType.ELITE)
    # ×1.6 elite base count should produce noticeably more elites on average.
    assert swarm > base


def test_replace_treasure_with_elites_flag():
    plain = generate_act_map("overgrowth", Rng(1))
    elites = generate_act_map("overgrowth", Rng(1), replace_treasure_with_elites=True)
    treasure_floor = plain.boss_floor - 7
    assert plain.floors[treasure_floor - 1][0].room_type is StateType.TREASURE
    assert elites.floors[treasure_floor - 1][0].room_type is StateType.ELITE


def test_each_act_has_expected_room_count():
    for key, spec in ACT_SPECS.items():
        rmap = generate_act_map(key, Rng(0))
        assert rmap.boss_floor == spec.num_rooms + 1

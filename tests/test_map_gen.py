"""Map generator structural tests."""
from __future__ import annotations

from sim.game_state import StateType
from sim.map_gen import ACT_SPECS, WIDTH, generate_act_map
from sim.rng import Rng


def test_overgrowth_layout_dimensions():
    rmap = generate_act_map("overgrowth", Rng(0))
    spec = ACT_SPECS["overgrowth"]
    # GetNumberOfFloors = NumberOfRooms + 2 (notes/08 §2): floor 1 = Ancient,
    # floor 2..N-1 = generated content, floor N = Boss.
    assert rmap.boss_floor == spec.num_rooms + 2
    assert rmap.boss_floor == 17  # Overgrowth/Underdocks ground truth
    assert len(rmap.floors) == rmap.boss_floor
    # Floor 1 (Ancient): single Monster placeholder at col 3 (Neow-skip rule).
    assert len(rmap.floors[0]) == 1
    assert rmap.floors[0][0].room_type is StateType.MONSTER
    assert rmap.floors[0][0].x == 3
    # Floor 2 (first generated row): full 7-column width.
    assert len(rmap.floors[1]) == WIDTH
    # Boss floor (last) only 1 node at col 3
    assert len(rmap.floors[-1]) == 1
    assert rmap.floors[-1][0].room_type is StateType.BOSS


def test_fixed_rows_are_correct_type():
    rmap = generate_act_map("overgrowth", Rng(42))
    # Floor 2 (first generated, "row 1" in 0-indexed game): all Monster.
    assert all(n.room_type is StateType.MONSTER for n in rmap.floors[1])
    # Rest row (N-1 = rmap.boss_floor - 1): RestSite
    rest_floor = rmap.boss_floor - 1
    assert all(n.room_type is StateType.REST for n in rmap.floors[rest_floor - 1])
    # Treasure row (N-7)
    treasure_floor = rmap.boss_floor - 7
    treasure_nodes = rmap.floors[treasure_floor - 1]
    assert len(treasure_nodes) == 1
    assert treasure_nodes[0].room_type in (StateType.TREASURE, StateType.ELITE)


def test_no_elite_or_rest_in_early_floors():
    rmap = generate_act_map("overgrowth", Rng(7))
    # Game spec "row < 6" (0-indexed) → sim floors 1..6 (Ancient + first 5
    # generated rows) cannot host Elite/Rest.
    for f in range(1, 7):
        for n in rmap.floors[f - 1]:
            assert n.room_type is not StateType.ELITE
            assert n.room_type is not StateType.REST


def test_ancient_connects_to_full_floor_2():
    rmap = generate_act_map("overgrowth", Rng(99))
    # The single Ancient node at floor 1 should fan out to every floor-2
    # column (notes/08 §4: row 1 starting columns are independently picked).
    ancient = rmap.floors[0][0]
    floor2_cols = {n.x for n in rmap.floors[1]}
    ancient_targets = {c[1] for c in ancient.children if c[0] == 2}
    assert ancient_targets == floor2_cols


def test_generated_rows_connect_forward():
    rmap = generate_act_map("overgrowth", Rng(99))
    # Each floor-2 node should have at least one successor on floor 3.
    for n in rmap.floors[1]:
        successors = [c for c in n.children if c[0] == 3]
        assert successors, f"floor-2 col {n.x} has no successors"


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
    # Ground truth from notes/08 §2 (GetNumberOfFloors = num_rooms + 2):
    # Overgrowth/Underdocks 17, Hive 16, Glory 15.
    expected = {"overgrowth": 17, "underdocks": 17, "hive": 16, "glory": 15}
    for key, spec in ACT_SPECS.items():
        rmap = generate_act_map(key, Rng(0))
        assert rmap.boss_floor == spec.num_rooms + 2
        assert rmap.boss_floor == expected[key], (
            f"{key}: boss_floor={rmap.boss_floor}, expected={expected[key]}")

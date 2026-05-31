"""UNDERDOCKS Act-1 variant tests.

Covers the per-run Act-1 coin flip (Overgrowth <-> Underdocks, mirroring
ActModel.GetRandomList), and proves an Underdocks run produces a valid map,
real (non-fallback) encounters, a real Underdocks boss, the correct boss
floor, and steps cleanly to its boss.
"""
from __future__ import annotations

from sim.encounter import UNDERDOCKS, is_modeled, is_multi_encounter
from sim.game_state import Character, RunState, StateType
from sim.run_engine import _act_order, reachable_map_nodes, start_run, step


def _new(seed: int, ascension: int = 0) -> RunState:
    rs = RunState.new_run(character=Character.IRONCLAD,
                          ascension=ascension, seed=seed)
    start_run(rs)
    return rs


def _act1_variant(seed: int) -> str:
    """Return the Act-1 variant ('overgrowth'|'underdocks') for a seed."""
    rs = RunState.new_run(character=Character.IRONCLAD, ascension=0, seed=seed)
    return _act_order(rs)[0]


# --- 1. Distribution: ~half Underdocks, ~half Overgrowth -------------------

def test_act1_variant_is_a_coin_flip_across_seeds():
    n = 4000
    counts = {"overgrowth": 0, "underdocks": 0}
    for seed in range(n):
        counts[_act1_variant(seed)] += 1
    # Both variants must show up, roughly balanced (binomial, ~50%).
    assert counts["underdocks"] > 0
    assert counts["overgrowth"] > 0
    frac = counts["underdocks"] / n
    assert 0.45 <= frac <= 0.55, counts


def test_acts_2_and_3_are_always_hive_then_glory():
    for seed in range(200):
        order = _act_order(RunState.new_run(character=Character.IRONCLAD,
                                            ascension=0, seed=seed))
        assert order[0] in ("overgrowth", "underdocks")
        assert order[1] == "hive"
        assert order[2] == "glory"


def test_act_order_is_deterministic_from_run_seed():
    for seed in (1, 7, 42, 1234, 99999):
        a = _act1_variant(seed)
        b = _act1_variant(seed)
        assert a == b


def _find_seed(variant: str) -> int:
    for seed in range(10000):
        if _act1_variant(seed) == variant:
            return seed
    raise AssertionError(f"no seed produced variant {variant}")


# --- 2/3. Map + encounters + boss for an Underdocks run --------------------

def test_underdocks_run_generates_valid_map():
    seed = _find_seed("underdocks")
    rs = _new(seed)
    assert rs.act == 1
    assert _act_order(rs)[0] == "underdocks"
    rmap = rs.maps[0]
    assert rmap is not None
    # num_rooms=15 -> boss at floor 17 (Ancient + 15 + Boss).
    assert rmap.boss_floor == 17
    # Boss floor is a single node at col 3 (StateType.BOSS).
    boss_nodes = rmap.floors[rmap.boss_floor - 1]
    assert len(boss_nodes) == 1
    assert boss_nodes[0].room_type is StateType.BOSS


def test_underdocks_pool_has_no_fallback_encounters():
    allids = (UNDERDOCKS["weak"] + UNDERDOCKS["normal"]
              + UNDERDOCKS["elite"] + UNDERDOCKS["boss"])
    unmodeled = [e for e in allids
                 if not (is_modeled(e) or is_multi_encounter(e))]
    assert unmodeled == [], f"Underdocks fallbacks remain: {unmodeled}"


def test_underdocks_encounters_are_real_not_sludge():
    seed = _find_seed("underdocks")
    rs = _new(seed)
    pools = rs._pools
    # Every normal/elite/boss pick the engine will hand out must be a real
    # Underdocks encounter id (never a Sludge fallback substitution).
    for eid in pools.normal:
        assert eid in (UNDERDOCKS["weak"] + UNDERDOCKS["normal"]), eid
        assert is_modeled(eid) or is_multi_encounter(eid)
    for eid in pools.elite:
        assert eid in UNDERDOCKS["elite"], eid
        assert is_modeled(eid) or is_multi_encounter(eid)
    assert pools.boss in UNDERDOCKS["boss"]


def test_underdocks_boss_is_a_real_underdocks_boss():
    # WaterfallGiant / SoulFysh / Lagavulin are the three Underdocks bosses.
    seen = set()
    found = 0
    for seed in range(10000):
        if _act1_variant(seed) != "underdocks":
            continue
        rs = _new(seed)
        assert rs._pools.boss in UNDERDOCKS["boss"]
        seen.add(rs._pools.boss)
        found += 1
        if found >= 200:
            break
    assert found > 0
    # Over many runs all three bosses should appear.
    assert seen == set(UNDERDOCKS["boss"]), seen


# --- 4. Full Act-1 Underdocks run steps to its boss without errors ---------

def _buff_player(rs: RunState) -> None:
    """Give the combat player enough Strength that greedy Strikes punch
    through monster block/plating, so the integration walk reliably resolves
    every Underdocks room (we're testing engine traversal, not balance)."""
    from sim.powers import make_power
    cs = rs.combat
    if cs is None:
        return
    if cs.player.get_power("strength") is None:
        cs.player.add_or_stack_power(make_power("strength", 50, cs.player))


def _auto_combat(rs: RunState, safety: int = 4000) -> None:
    """Greedily play any playable card then end turn until combat resolves."""
    _buff_player(rs)
    while rs.in_combat() and safety > 0:
        safety -= 1
        cs = rs.combat
        rs.hp = cs.player.hp = cs.player.max_hp  # keep alive during traversal
        _buff_player(rs)
        playable = [i for i in range(len(cs.hand)) if cs.can_play(i)]
        if playable:
            step(rs, {"action": "play_card", "card_index": playable[0],
                      "target": 0})
        else:
            step(rs, {"action": "end_turn"})


def _clear_overlays(rs: RunState) -> None:
    """Resolve any non-map overlay (card reward / rest / event / shop /
    treasure) by skipping/proceeding back to the map."""
    guard = 50
    while rs.state_type is not StateType.MAP and not rs.is_terminal() and guard:
        guard -= 1
        st = rs.state_type
        if st in (StateType.CARD_REWARD, StateType.CARD_SELECT):
            step(rs, {"action": "skip_card_reward"})
        elif st is StateType.REST:
            step(rs, {"action": "choose_rest_option", "index": 0})
        elif st is StateType.EVENT:
            step(rs, {"action": "proceed"})
        elif st is StateType.SHOP:
            step(rs, {"action": "proceed"})
        elif st is StateType.TREASURE:
            step(rs, {"action": "proceed"})
        elif rs.in_combat():
            _auto_combat(rs)
        else:
            break


def test_full_underdocks_act1_steps_to_boss():
    seed = _find_seed("underdocks")
    # Low ascension + a generous deck-less greedy player won't always survive
    # honestly; the point is the engine drives Underdocks rooms to the boss
    # without raising. Give the player a big HP buffer so it reaches the boss.
    rs = _new(seed, ascension=0)
    rs.max_hp = 9999
    rs.hp = 9999

    boss_floor = rs.maps[0].boss_floor
    reached_boss = False
    fought_boss = False
    guard = 2000
    while not rs.is_terminal() and guard:
        guard -= 1
        if rs.state_type is StateType.MAP:
            rs.hp = rs.max_hp
            options = reachable_map_nodes(rs)
            if not options:
                break
            # Walk forward; the boss floor is a single funnel node anyway.
            r = step(rs, {"action": "choose_map_node", "index": 0})
            assert not r.invalid_action, r.reason
            if rs.current_node[0] == boss_floor:
                reached_boss = True
                if rs.state_type is StateType.BOSS:
                    fought_boss = True
        elif rs.in_combat():
            if rs.current_node[0] == boss_floor:
                reached_boss = True
                fought_boss = True
            _auto_combat(rs)
        else:
            _clear_overlays(rs)

    assert reached_boss, "never reached the Underdocks boss floor"
    assert fought_boss, "never entered Underdocks boss combat"
    # Stepped to (and through) the Act-1 boss without raising; the run is
    # either still going (advanced to Hive) or terminal (victory/defeat).
    assert rs.act >= 1

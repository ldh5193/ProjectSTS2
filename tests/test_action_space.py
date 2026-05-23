"""Layout + mask + decode coverage for the Discrete(300) action space."""
from __future__ import annotations

from sim.action_space import (
    N_ACTIONS,
    RANGES,
    build_mask,
    decode,
    find_range,
    range_named,
)


def test_total_is_300():
    assert N_ACTIONS == 300
    assert sum(r.size for r in RANGES) == 300


def test_ranges_are_contiguous_and_non_overlapping():
    cursor = 0
    for r in RANGES:
        assert r.start == cursor, f"gap or overlap at {r.name}: expected {cursor}, got {r.start}"
        cursor = r.stop
    assert cursor == 300


def test_named_lookup_and_range_membership():
    combat = range_named("combat")
    assert combat.size == 61
    assert combat.start == 0
    assert combat.contains(0) and combat.contains(60)
    assert not combat.contains(61)
    assert find_range(0) is combat
    assert find_range(72).name == "card_reward"


# --- mask --------------------------------------------------------------------


def _combat_state():
    return {
        "state_type": "monster",
        "battle": {
            "is_play_phase": True,
            "enemies": [
                {"entity_id": "NIBBIT_0", "combat_id": 1, "hp": 43, "max_hp": 43},
            ],
        },
        "player": {
            "energy": 3,
            "hand": [
                {"id": "STRIKE_IRONCLAD", "target_type": "AnyEnemy", "can_play": True, "cost": 1},
                {"id": "DEFEND_IRONCLAD", "target_type": "Self", "can_play": True, "cost": 1},
            ],
        },
    }


def test_mask_in_combat_allows_end_turn_targeted_strike_and_self_defend():
    state = _combat_state()
    mask = build_mask(state)
    # end_turn legal
    assert mask[0] is True
    # play strike (index 0) targeting enemy 0 -> combat range index 11
    assert mask[11] is True
    # play defend (index 1, self-target) -> combat range index 2
    assert mask[2] is True
    # no other combat slots
    legal_in_combat = [i for i in range(61) if mask[i]]
    assert sorted(legal_in_combat) == sorted([0, 2, 11])
    # Everything outside combat is masked
    assert all(m is False for m in mask[61:])


def test_mask_in_card_reward_marks_visible_picks_and_skip():
    state = {
        "state_type": "card_select",
        "card_select": [
            {"id": "iron_wave"}, {"id": "inflame"}, {"id": "anger"},
        ],
    }
    mask = build_mask(state)
    # card_reward starts at 72, three picks legal (72, 73, 74)
    cr = range_named("card_reward")
    assert mask[cr.start] and mask[cr.start + 1] and mask[cr.start + 2]
    assert mask[cr.start + 3] is False
    # skip lives at the end of the range (local 5)
    assert mask[cr.start + 5] is False  # skip is masked because predicate yields 0..2 only


def test_mask_in_menu_uses_options_list():
    state = {
        "state_type": "menu",
        "menu_screen": "main",
        "options": ["singleplayer", "multiplayer", "settings", "quit"],
    }
    mask = build_mask(state)
    ms = range_named("menu_select")
    assert sum(mask[ms.start:ms.stop]) == 4


# --- decode ------------------------------------------------------------------


def test_decode_combat_end_turn():
    assert decode(0, _combat_state()) == {"action": "end_turn"}


def test_decode_combat_untargeted_play():
    body = decode(2, _combat_state())
    assert body == {"action": "play_card", "card_index": 1}


def test_decode_combat_targeted_play_picks_enemy_combat_id():
    body = decode(11, _combat_state())
    assert body["action"] == "play_card"
    assert body["card_index"] == 0
    # The mod returns combat_id as an int in the live API; fall back to entity_id
    # if missing. The test fixture has both, so combat_id wins.
    assert body["target"] == 1


def test_decode_targeted_play_invalid_when_enemy_slot_empty():
    state = _combat_state()
    state["battle"]["enemies"] = []
    body = decode(11, state)
    assert body["action"] == "invalid"


def test_decode_menu_select_uses_state_options():
    state = {"state_type": "menu", "options": ["singleplayer", "settings", "quit"]}
    ms = range_named("menu_select")
    assert decode(ms.start, state) == {"action": "menu_select", "option": "singleplayer"}
    assert decode(ms.start + 2, state) == {"action": "menu_select", "option": "quit"}
    assert decode(ms.start + 3, state)["action"] == "invalid"


def test_decode_skip_card_reward():
    cr = range_named("card_reward")
    body = decode(cr.start + 5, {"state_type": "card_select", "card_select": [{}]})
    assert body == {"action": "skip_card_reward"}


def test_decode_out_of_range_is_invalid():
    assert decode(N_ACTIONS, {})["action"] == "invalid"
    assert decode(-1, {})["action"] == "invalid"
